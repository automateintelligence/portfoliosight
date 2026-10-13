"""A-PS-10 — runtime code reaches only Tiingo, tsp.gov, R2 and MailChannels, never yfinance or
qse.env, and redacts tokens from logs.

Claim: no module under portfoliosight/data/, portfoliosight/engine/, portfoliosight/api/,
portfoliosight/jobs/ or scripts/ (excluding portfoliosight/frontier_cli.py and
scripts/make_fixtures.py) imports yfinance, references qse.env, or contains a URL host other than
api.tiingo.com, www.tsp.gov, *.r2.cloudflarestorage.com and api.mailchannels.net; and no log line
emitted by the Tiingo adapter contains the API key.

Pinned interface (the product must provide exactly this):
- Static leg. "Module" = every `*.py` and `*.sh` file, and every other file that starts with a
  `#!` line, under the five scoped directories (`__pycache__` skipped). In those files every
  `https?://...` literal, comments and docstrings included, must have one of the four allowed
  hosts (a templated account id in front of `.r2.cloudflarestorage.com` is fine). Scripts that
  must reach another host (localhost, portfoliosight.ai) take the base URL from the environment
  or an argument instead of spelling `http(s)://<host>` in the file.
- Log leg. `portfoliosight.data.providers.tiingo.TiingoProvider()` reads `TIINGO_API_KEY` from
  the environment when constructed, sends `Authorization: Token <key>` through `requests`, logs
  through the standard `logging` module (records must reach the root logger), writes at least one
  log line containing `404` for a 404 response and one containing `429` for a 429 response, and
  waits on a 429 by calling `time.sleep(...)` (looked up on the `time` module at call time, so
  the test can replace it). In log text the word `Token` (or `api_token=` / `api_token:`) is
  only ever followed by a redaction marker: `***` (three or more asterisks), `[REDACTED]`,
  `<redacted>` or `REDACTED`. Exceptions the adapter raises must not carry the key in their
  message either (the test logs them with their traceback, as a caller would).
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _project_python() -> Path | None:
    """The project's virtualenv interpreter: this checkout's, else the main checkout's (worktree)."""
    roots = [ROOT]
    dot_git = ROOT / ".git"
    if dot_git.is_file():  # linked worktree: "gitdir: <main>/.git/worktrees/<name>"
        roots.append(Path(dot_git.read_text().split(":", 1)[1].strip()).parents[2])
    for root in roots:
        candidate = root / ".venv" / "bin" / "python"
        if candidate.exists():
            return candidate
    return None


_VENV_PY = _project_python()
_OUTER = (
    os.environ.get("PS_GATE_INNER") != "1"
    and _VENV_PY is not None
    and Path(sys.prefix).resolve() != _VENV_PY.parents[1].resolve()
)


def _need(module: str):
    """Import a product (or dev-dependency) module, failing the test cleanly when it is absent."""
    try:
        return importlib.import_module(module)
    except Exception as exc:  # ImportError, or an import-time crash in the product
        pytest.fail(f"A-PS-10 red: cannot import {module}: {type(exc).__name__}: {exc}")


SCOPED_DIRS = (
    "portfoliosight/data",
    "portfoliosight/engine",
    "portfoliosight/api",
    "portfoliosight/jobs",
    "scripts",
)
EXCLUDED_FILES = ("portfoliosight/frontier_cli.py", "scripts/make_fixtures.py")
ALLOWED_HOSTS = ("api.tiingo.com", "www.tsp.gov", "api.mailchannels.net")
ALLOWED_SUFFIX = ".r2.cloudflarestorage.com"
URL_RE = re.compile(r"""https?://[^\s"']+""")
YFINANCE_RE = re.compile(r"\byfinance\b")
QSE_ENV_RE = re.compile(r"qse\.env")

SENTINEL = "ZZ-SENTINEL-KEY-ZZ"
REDACTION_RE = re.compile(r"""^["'(\[<]*(\*{3,}|\[redacted\]|<redacted>|redacted)""", re.IGNORECASE)
TOKEN_VALUE_RE = re.compile(r"(?:\bToken\s+|api_token\s*[=:]\s*)(\S+)")
TIINGO_URL = re.compile(r"https://api\.tiingo\.com/.*")
PRICE_ROWS = [
    {"date": "2001-05-31T00:00:00.000Z", "close": 114.8, "adjClose": 36.83, "divCash": 0.0},
    {"date": "2001-06-01T00:00:00.000Z", "close": 115.6, "adjClose": 37.09, "divCash": 0.0},
    {"date": "2001-06-04T00:00:00.000Z", "close": 116.1, "adjClose": 37.25, "divCash": 0.0},
    {"date": "2001-06-05T00:00:00.000Z", "close": 117.8, "adjClose": 37.79, "divCash": 0.0},
]
for _row in PRICE_ROWS:
    _row["splitFactor"] = 1.0


def _host(url: str) -> str:
    rest = url.split("://", 1)[1]
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    authority = authority.rsplit("@", 1)[-1]
    authority = re.sub(r":\d+$", "", authority)
    return authority.rstrip(").,;>`]\\").lower()


def _allowed(host: str) -> bool:
    return host in ALLOWED_HOSTS or (
        host.endswith(ALLOWED_SUFFIX) and len(host) > len(ALLOWED_SUFFIX)
    )


def _scoped_files() -> list[Path]:
    files = []
    for rel in SCOPED_DIRS:
        base = ROOT / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.relative_to(ROOT).as_posix() in EXCLUDED_FILES:
                continue
            if path.suffix in (".py", ".sh"):
                files.append(path)
                continue
            with path.open("rb") as handle:
                if handle.read(2) == b"#!":
                    files.append(path)
    return files


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines: list[tuple[str, str]] = []
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))

    def emit(self, record):
        try:
            self.lines.append((record.name, self.format(record)))
        except Exception as exc:  # a broken log call must not hide the rest
            text = f"UNFORMATTABLE {record.name} {record.msg!r} {record.args!r} {exc!r}"
            self.lines.append((record.name, text))


if _OUTER:

    def test_a_ps_10_in_project_venv():
        env = dict(os.environ, PS_GATE_INNER="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        proc = subprocess.run(
            [
                str(_VENV_PY),
                "-m",
                "pytest",
                "-q",
                "--noconftest",
                "-p",
                "no:cacheprovider",
                __file__,
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        print(proc.stdout[-8000:], proc.stderr[-2000:])
        assert proc.returncode == 0, "A-PS-10 is red inside the project virtualenv (output above)"

else:

    def test_host_parser_examples():
        """Guards the test's own URL handling."""
        assert _host("https://api.tiingo.com/tiingo/daily/{symbol}/prices?x=1") == "api.tiingo.com"
        assert _host("https://{account}.r2.cloudflarestorage.com") == (
            "{account}.r2.cloudflarestorage.com"
        )
        assert _allowed(_host("https://${CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com/b"))
        assert _allowed(_host("https://www.tsp.gov/data/fund-price-history.csv)."))
        assert not _allowed(_host("https://query1.finance.yahoo.com/v8/x"))
        assert not _allowed(_host("http://localhost:8000/v1/health"))
        assert not _allowed(_host("https://r2.cloudflarestorage.com.evil.example/x"))
        assert not _allowed(_host("https://api.tiingo.com.evil.example/x"))
        assert not _allowed(_host("https://.r2.cloudflarestorage.com"))

    def test_static_scan_of_scoped_modules():
        files = _scoped_files()
        assert (ROOT / "portfoliosight" / "data").is_dir(), "portfoliosight/data/ does not exist"
        hits_by_host: dict[str, int] = {}
        forbidden: list[str] = []
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), start=1):
                if YFINANCE_RE.search(line):
                    forbidden.append(f"{rel}:{number}: yfinance")
                if QSE_ENV_RE.search(line):
                    forbidden.append(f"{rel}:{number}: qse.env")
                for match in URL_RE.finditer(line):
                    host = _host(match.group(0))
                    hits_by_host[host] = hits_by_host.get(host, 0) + 1
                    if not _allowed(host):
                        forbidden.append(f"{rel}:{number}: host {host}")
        # Control hits: the scan must have read the real provider code.
        assert hits_by_host.get("api.tiingo.com", 0) >= 1, (
            f"no api.tiingo.com URL found in {len(files)} scoped files: the scan saw no adapter"
        )
        assert hits_by_host.get("www.tsp.gov", 0) >= 1, (
            f"no www.tsp.gov URL found in {len(files)} scoped files: the scan saw no TSP provider"
        )
        scanned = {p.relative_to(ROOT).as_posix() for p in files}
        assert "portfoliosight/data/providers/tiingo.py" in scanned
        assert "portfoliosight/frontier_cli.py" not in scanned
        assert "scripts/make_fixtures.py" not in scanned
        assert not forbidden, "forbidden references in runtime code:\n" + "\n".join(forbidden[:40])

    def test_tiingo_adapter_logs_never_carry_the_key(monkeypatch, capfd):
        responses = _need("responses")
        monkeypatch.setenv("TIINGO_API_KEY", SENTINEL)
        slept: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda seconds=0, *a, **k: slept.append(seconds))
        mod = _need("portfoliosight.data.providers.tiingo")
        if hasattr(mod, "sleep"):
            monkeypatch.setattr(mod, "sleep", lambda seconds=0, *a, **k: slept.append(seconds))
        cls = getattr(mod, "TiingoProvider", None)
        assert cls is not None, "portfoliosight.data.providers.tiingo.TiingoProvider is missing"

        capture = _Capture()
        root = logging.getLogger()
        saved_root_level = root.level
        saved_disable = logging.root.manager.disable
        saved_levels = {}
        logging.disable(logging.NOTSET)
        root.addHandler(capture)
        root.setLevel(logging.DEBUG)
        for name, logger in list(logging.root.manager.loggerDict.items()):
            if isinstance(logger, logging.Logger) and name.split(".")[0] in (
                "portfoliosight",
                "tiingo",
                "urllib3",
                "requests",
            ):
                saved_levels[name] = (logger.level, logger.disabled)
                logger.setLevel(logging.DEBUG)
                logger.disabled = False

        served: list[tuple[int, str, str]] = []
        state = {"vbiax_429": 0}

        def serve(request):
            path = request.path_url.split("?", 1)[0].lower().rstrip("/")
            auth = request.headers.get("Authorization", "")
            parts = path.split("/")
            symbol = parts[3] if len(parts) > 3 else ""
            is_prices = path.endswith("/prices")
            if symbol == "nosuch":
                status, headers, body = 404, {}, {"detail": "Not found."}
            elif symbol == "vbiax" and state["vbiax_429"] == 0:
                state["vbiax_429"] += 1
                status, headers = 429, {"Retry-After": "1"}
                body = {"detail": "Error: You have run over your hourly request allocation."}
            elif is_prices:
                status, headers, body = 200, {}, PRICE_ROWS
            else:
                status, headers = 200, {}
                body = {
                    "ticker": symbol.upper(),
                    "name": "Recorded Fund",
                    "exchangeCode": "NYSE ARCA",
                    "startDate": "2001-05-31",
                    "endDate": "2001-06-05",
                    "description": "",
                }
            served.append((status, path, auth))
            headers = dict(headers, **{"Content-Type": "application/json"})
            return (status, headers, json.dumps(body))

        outcomes = {}
        try:
            with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
                mock.add_callback(responses.GET, TIINGO_URL, callback=serve)
                provider = cls()
                calls = [
                    (
                        "daily VTI",
                        lambda: provider.fetch_daily("VTI", date(2001, 5, 31), date(2001, 6, 5)),
                    ),
                    ("meta VTI", lambda: provider.fetch_meta("VTI")),
                    (
                        "daily NOSUCH",
                        lambda: provider.fetch_daily("NOSUCH", date(2001, 5, 31), date(2001, 6, 5)),
                    ),
                    ("meta NOSUCH", lambda: provider.fetch_meta("NOSUCH")),
                    (
                        "daily VBIAX",
                        lambda: provider.fetch_daily("VBIAX", date(2001, 5, 31), date(2001, 6, 5)),
                    ),
                ]
                for label, call in calls:
                    try:
                        outcomes[label] = call()
                    except Exception as exc:  # error paths may raise; their logs still count
                        outcomes[label] = exc
                        logging.getLogger("a_ps_10.caller").exception("caller saw %s fail", label)
        finally:
            root.removeHandler(capture)
            root.setLevel(saved_root_level)
            logging.disable(saved_disable)
            for name, (level, disabled) in saved_levels.items():
                logging.getLogger(name).setLevel(level)
                logging.getLogger(name).disabled = disabled

        statuses = [status for status, _, _ in served]
        assert statuses.count(200) >= 1, f"no 200 was replayed (served: {statuses})"
        assert statuses.count(404) >= 1, f"no 404 was replayed (served: {statuses})"
        assert statuses.count(429) == 1, (
            f"the forced 429 was not replayed once (served: {statuses})"
        )
        for status, path, auth in served:
            assert auth == f"Token {SENTINEL}", (
                f"request {path} did not carry 'Authorization: Token <TIINGO_API_KEY>' from the env"
            )
        first = outcomes["daily VTI"]
        assert not isinstance(first, Exception), f"fetch_daily(VTI) raised on a 200: {first!r}"
        assert len(first) == len(PRICE_ROWS), f"fetch_daily(VTI) returned {len(first)} rows"

        adapter_lines = [
            line
            for name, chunk in capture.lines
            if name != "a_ps_10.caller"
            for line in chunk.splitlines()
        ]
        text = "\n".join(chunk for _, chunk in capture.lines)
        out, err = capfd.readouterr()
        # Must-not-contain: the key, anywhere a line could carry it.
        assert SENTINEL not in text, "the Tiingo API key appears in the captured log text"
        assert SENTINEL not in out and SENTINEL not in err, "the key was printed to stdout/stderr"
        for match in TOKEN_VALUE_RE.finditer(text + "\n" + out + "\n" + err):
            assert REDACTION_RE.match(match.group(1)), (
                f"log text has a token value that is not a redaction marker: {match.group(0)[:40]!r}"
            )
        assert any(re.search(r"\b404\b", line) for line in adapter_lines), (
            f"no log line for the 404 (got {len(adapter_lines)} adapter lines)"
        )
        assert any(re.search(r"\b429\b", line) for line in adapter_lines), (
            f"no log line for the 429 (got {len(adapter_lines)} adapter lines)"
        )
