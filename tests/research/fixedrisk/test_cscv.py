import math

import numpy as np
import pandas as pd
import pytest

from portfoliosight.research.fixedrisk import cscv


def _monthly(k, length_days=0):
    origins = pd.date_range("2000-01-01", periods=k, freq="MS")
    return origins, origins + pd.Timedelta(days=length_days)


def test_blocks_use_array_split_and_70_splits():
    origins, ends = _monthly(19)
    m = cscv.cscv_masks(origins, ends)
    assert [len(b) for b in m.blocks] == [3, 3, 3, 2, 2, 2, 2, 2]
    assert len(m.splits) == 70
    assert len({s.train_blocks for s in m.splits}) == 70
    for s in m.splits:
        assert not (s.train & s.test).any()
        assert s.test.sum() == sum(len(m.blocks[b]) for b in s.test_blocks)  # never removed


def test_purge_and_embargo_on_known_endpoints():
    origins, ends = _monthly(16, 45)  # each interval runs 45 days: overlaps the next origin
    m = cscv.cscv_masks(origins, ends)
    after = next(s for s in m.splits if s.train_blocks == (4, 5, 6, 7))  # test = origins 0..7
    # origin 8 (2000-09-01) starts inside test origin 7's interval [08-01, 09-15]: purged;
    # origin 9 (10-01) is inside one month after 09-15: embargoed; origin 10 (11-01) is kept.
    assert np.flatnonzero(after.train).tolist() == [10, 11, 12, 13, 14, 15]
    assert (after.purged, after.embargoed) == (1, 1)
    before = next(s for s in m.splits if s.train_blocks == (0, 1, 2, 3))  # test = origins 8..15
    # training origin 7 [08-01, 09-15] meets test origin 8 (starts 09-01): purged; no embargo
    assert np.flatnonzero(before.train).tolist() == [0, 1, 2, 3, 4, 5, 6]
    assert (before.purged, before.embargoed) == (1, 0)


def test_closed_interval_touching_endpoints_are_purged():
    origins = pd.date_range("2000-01-01", periods=8, freq="MS")
    ends = origins.to_series().shift(-1).fillna(origins[-1] + pd.Timedelta(days=30)).to_numpy()
    m = cscv.cscv_masks(origins, ends, blocks=8)  # one origin per block; end(i) == origin(i+1)
    split = next(s for s in m.splits if s.train_blocks == (0, 2, 4, 6))
    # every training origin touches the next (test) origin at a single day: all purged
    assert not split.train.any() and split.purged == 4


def test_manifest_round_trip():
    origins, ends = _monthly(40, 30)
    m = cscv.cscv_masks(origins, ends)
    back = cscv.CscvMasks.from_manifest(m.to_manifest())
    assert all(
        (a.train == b.train).all() and (a.test == b.test).all()
        for a, b in zip(m.splits, back.splits, strict=True)
    )
    assert (back.origins == m.origins).all()


def test_too_few_origins():
    origins, ends = _monthly(5)
    with pytest.raises(ValueError):
        cscv.cscv_masks(origins, ends)


def _flip_case(k=160, c=2):
    """Arm a returns base + shift_a in the first half, base - shift_a in the second half."""
    origins, ends = _monthly(k, 0)
    m = cscv.cscv_masks(origins, ends)
    shifts = np.array([0.001, 0.002, 0.003, 0.004])
    sign = np.where(np.arange(k) < k // 2, 1.0, -1.0)
    base = np.zeros((k, c))
    x = base[None] + shifts[:, None, None] * sign[None, :, None]
    return m, x


def test_rank_lambda_and_pbo_on_constructed_case():
    m, x = _flip_case()
    res = cscv.cscv_run(m, x)
    assert len(res.evaluable) == 70 and res.computable
    first = next(r for r in res.evaluable if m.splits[r["split"]].train_blocks == (0, 1, 2, 3))
    # training is all +shift: the largest shift wins (U4); test is all -shift: U4 ranks worst
    assert first["chosen"] == 3 and first["rank"] == 1.0
    assert first["omega"] == pytest.approx(0.2) and first["lambda"] == pytest.approx(math.log(0.25))
    second = next(r for r in res.evaluable if m.splits[r["split"]].train_blocks == (4, 5, 6, 7))
    assert second["chosen"] == 0 and second["rank"] == 1.0
    expected = np.mean([r["lambda"] < 0 for r in res.evaluable])
    assert res.pbo == pytest.approx(expected)
    assert res.pbo >= 2 / 70  # at least the two pure-half splits have lambda < 0
    assert len(res.choice_shares(("U1", "U2", "U3", "U4"))) == 4


def test_monotone_arms_have_zero_pbo_and_tie_order():
    origins, ends = _monthly(160)
    m = cscv.cscv_masks(origins, ends)
    shifts = np.array([0.0, 0.01, 0.02, 0.03])
    x = np.zeros((4, 160, 2)) + shifts[:, None, None]
    assert cscv.cscv_run(m, x).pbo == 0.0  # best in training is best on test: omega = .8
    ties = np.zeros((4, 160, 2))
    res = cscv.cscv_run(m, ties)
    assert all(r["chosen"] == 0 and r["tied"] for r in res.evaluable)  # fixed order U1 first
    assert all(r["rank"] == 2.5 and r["lambda"] == 0.0 for r in res.evaluable)  # average ranks
    assert res.pbo == 0.0


def test_minimum_sizes_drop_splits_and_fifty_split_rule():
    origins, ends = _monthly(64)  # 32 per side: below 60
    m = cscv.cscv_masks(origins, ends)
    res = cscv.cscv_run(m, np.zeros((4, 64, 2)))
    assert res.evaluable == [] and len(res.dropped) == 70 and res.pbo is None
    assert "PBO not computable" in res.pbo_note
    # block 0 empty in the common mask: only the 35 splits with it on the test side can pass
    m2, x = _flip_case()
    x[:, :20, :] = np.nan
    res2 = cscv.cscv_run(m2, x)
    assert len(res2.evaluable) == 35 and res2.pbo is None
    assert any("keeps" in d["reason"] for d in res2.dropped)


def test_training_block_minimum():
    m, x = _flip_case()
    x[:, :18, :] = np.nan  # block 0 keeps 2 origins in the mask
    res = cscv.cscv_run(m, x)
    assert any("training block" in d["reason"] for d in res.dropped)


def test_all_masked_returns_note():
    m, x = _flip_case()
    res = cscv.cscv_run(m, np.full_like(x, np.nan))
    assert res.pairs == 0 and res.pbo is None
