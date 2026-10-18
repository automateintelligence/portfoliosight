# qse/ - a selected pull of Quant Scenario Engine code

This directory holds ten files copied byte-identical from the QSE repository. PortfolioSight
imports `qse.distributions` only (`qse.distributions.joint`: the GARCH(1,1)-t panel fit, the
residual pool and the filtered historical simulation). QSE itself is not installed here: its
dependency list carries torch and xgboost.

The commit is pinned in `qse/qse.lock.json` (QSE commit `ca8c0445a56712c92dc028e68845b94963fdd590`
at the time of writing), together with a sha256 per file. `qse/` has no `__init__.py`; it is a
namespace package, as in QSE.

## The rule

Never edit a file here. Edit it in QSE, merge it there, then:

    .venv/bin/python scripts/sync_qse.py --commit <new QSE sha>

and merge the result here. The script reads the commit with `git`, so the QSE working tree is
never touched, rewrites the files and the lock, and closes the files.

## Three read-only layers

1. Agents: `.claude/settings.json` denies `Edit` and `Write` under `qse/`.
2. Disk: `scripts/sync_qse.py` closes every file it writes with `chmod a-w` (mode 0444).
   After a fresh clone the files are writable again; `scripts/sync_qse.py --check` closes them.
3. Backstop: `tests/test_qse_sync.py` fails on any drift from the lock, on any file under
   `qse/` that the lock does not name, and on a lock that is not the pinned commit. There is no
   pre-commit setup in this repository, so there is no hook.
