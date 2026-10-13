"""Runtime code reaches only the four allowed hosts and never the forbidden sources (A-PS-10)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
FORBIDDEN = {"yfinance": re.compile(r"\byfinance\b"), "qse.env": re.compile(r"qse\.env")}


def _host(url: str) -> str:
    authority = re.split(r"[/?#]", url.split("://", 1)[1], maxsplit=1)[0]
    authority = re.sub(r":\d+$", "", authority.rsplit("@", 1)[-1])
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
            if path.suffix in (".py", ".sh") or path.read_bytes()[:2] == b"#!":
                files.append(path)
    return files


def test_host_rule():
    assert _allowed(_host("https://api.tiingo.com/tiingo/daily/{symbol}/prices?x=1"))
    assert _allowed(_host("https://${account}.r2.cloudflarestorage.com/bucket"))
    assert _allowed(_host("https://www.tsp.gov/data/fund-price-history.csv)."))
    for url in (
        "https://query1.finance.yahoo.com/v8/x",
        "http://localhost:8000/v1/health",
        "https://portfoliosight.ai/api/presets",
        "https://api.cloudflare.com/client/v4",
        "https://api.tiingo.com.evil.example/x",
        "https://.r2.cloudflarestorage.com",
    ):
        assert not _allowed(_host(url)), url


def test_scoped_code_names_only_allowed_hosts_and_no_forbidden_source():
    hits: dict[str, int] = {}
    problems: list[str] = []
    files = _scoped_files()
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in FORBIDDEN.items():
                if pattern.search(line):
                    problems.append(f"{rel}:{number}: {label}")
            for match in URL_RE.finditer(line):
                host = _host(match.group(0))
                hits[host] = hits.get(host, 0) + 1
                if not _allowed(host):
                    problems.append(f"{rel}:{number}: host {host}")
    assert not problems, "forbidden references in runtime code:\n" + "\n".join(problems)
    # The scan must have read the real provider code.
    assert hits.get("api.tiingo.com", 0) >= 1 and hits.get("www.tsp.gov", 0) >= 1
    scanned = {path.relative_to(ROOT).as_posix() for path in files}
    assert {
        "portfoliosight/data/providers/tiingo.py",
        "portfoliosight/data/providers/tsp.py",
        "portfoliosight/data/store.py",
        "scripts/r2_backup.sh",
        "scripts/seed_r2_from_lake.py",
    } <= scanned
    assert "portfoliosight/frontier_cli.py" not in scanned


def test_only_the_store_module_imports_boto3():
    importers = []
    for path in sorted((ROOT / "portfoliosight").rglob("*.py")):
        if re.search(r"^\s*(import|from)\s+boto(3|core)\b", path.read_text(), flags=re.M):
            importers.append(path.relative_to(ROOT).as_posix())
    assert importers == ["portfoliosight/data/store.py"]
