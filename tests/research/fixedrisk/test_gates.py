"""scripts/fixed_risk_gates.py: a case or check whose bank cannot be built is a recorded failure."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

from portfoliosight.research.fixedrisk import agreement
from portfoliosight.research.fixedrisk.garch_bank import GarchFitFailed
from tests.research.fixedrisk import fakes

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "fixed_risk_gates.py"


@pytest.fixture(scope="module")
def gates():
    spec = importlib.util.spec_from_file_location("fixed_risk_gates_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_fit_failure_is_a_failed_case_and_a_failed_check(gates, monkeypatch):
    inputs = fakes.synthetic_inputs()
    month = gates.data.schedule(inputs, "tsp")[3]
    monkeypatch.setitem(gates._STATE, "inputs", inputs)

    def refuse(ctx, engine, seed):
        raise GarchFitFailed("TSP-F", ctx.origin, "optimizer did not converge")

    monkeypatch.setattr(gates.driver, "real_make_bank", refuse)
    rows = gates._agreement_case((7, "tsp", month, 0.4, "d25", "garch"))
    assert len(rows) == len(agreement.SOLVERS) * len(agreement.AGREEMENT_OBJECTIVES)
    assert all(r["case"] == 7 and r["month"] == month and r["value"] == -math.inf for r in rows)
    assert all("GarchFitFailed" in r["error"] and "TSP-F" in r["error"] for r in rows)
    decision = agreement.agreement_decision(
        [
            agreement.AgreementRow(**{k: r[k] for k in agreement.AgreementRow.__dataclass_fields__})
            for r in rows
        ],
        expected_pairs=60,
    )
    assert decision.pairs == 60 and set(decision.passes.values()) == {0}
    assert decision.reference_failed == ((7, "B"), (7, "U1"))

    fd = gates._fd(("tsp", month, "garch"))
    assert fd["passed"] is False and "TSP-F" in fd["error"]
