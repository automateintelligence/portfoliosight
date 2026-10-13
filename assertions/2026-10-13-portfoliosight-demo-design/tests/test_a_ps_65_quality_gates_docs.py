"""A-PS-65 — quality gates, one smoke test per DoD item, no skipped tests, docs updated.

Claim: `ruff check . && ruff format --check . && pyright .` exit 0; `pytest --cov=portfoliosight
--cov-report=term-missing` passes with >= 80% total line coverage and 100% on
`portfoliosight/engine/`; `npm run lint && npm run typecheck && npm test` exit 0 in `web/`;
`web/e2e/smoke.spec.ts` defines exactly one test per DoD item 1-31 named `DoD-NN`; no test in
`tests/`, `web/tests/` or `web/e2e/` carries an unconditional `skip`, `xfail`, `only` or `todo`
marker; `README.md` is <= 60 lines, names the WSL working copy as the lake and
`/mnt/d/portfoliosight-data` as the backup, and does not name `/mnt/d` as the lake; `ROADMAP.md`
contains the Appendix B items.

Pinned interface (the product must provide exactly this): the project virtualenv `.venv` with
`ruff`, `pyright`, `pytest`, `pytest-cov`; `tests/` (Python), `web/package.json` with scripts
`lint`, `typecheck`, `test` (vitest) and `web/node_modules`; `web/e2e/smoke.spec.ts` declaring
its 31 tests as `test("DoD-NN ...", ...)` with static string titles; `README.md`, `ROADMAP.md`.
`ruff` and `pyright` run over the whole repository (the committed configuration decides whether
that includes `assertions/`; pyright is run as `pyright -p . .` so that configuration applies).
"On main" is read as "on the checked-out reviewed revision": every check works on the working
tree it runs in and never looks at a branch name. Coverage is measured with an EMPTY coverage configuration: no omit,
no excluded lines in the engine, no `# pragma: no cover` in engine sources.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"
ENGINE = ROOT / "portfoliosight" / "engine"
SMOKE = WEB / "e2e" / "smoke.spec.ts"
PRAGMA = "pragma: " + "no cover"
TITLE = re.compile(r"^DoD-(0[1-9]|[12]\d|3[01])\b")
MARKER = re.compile(
    r"pytest\.mark\.skip\(|pytest\.mark\.xfail|\.skip\(|\.only\(|\.todo\(|test\.fixme"
)
ALLOWED_ENV = ("PS_LIVE_TESTS", "PS_SHARE_TEST_RECIPIENT")
PY_SUFFIXES = {".py"}
JS_SUFFIXES = {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}
SKIP_DIRS = {"__gate__", "node_modules", "__pycache__", "test-results", "playwright-report"}
LAKE = "~/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core"
BACKUP = "/mnt/d/portfoliosight-data"


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


def _child_env(venv_bin: Path | None = None) -> dict:
    env = dict(os.environ)
    for name in ("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PS_GATE_INNER", "PS_LIVE_TESTS", "PYTHONPATH"):
        env.pop(name, None)
    env["CI"] = "1"
    if venv_bin is not None:
        env["VIRTUAL_ENV"] = str(venv_bin.parent)
        env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
    return env


def _run(cmd, *, cwd, env, timeout):
    label = " ".join(str(c) for c in cmd[:4])
    try:
        return subprocess.run(
            [str(c) for c in cmd], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError as exc:
        pytest.fail(f"A-PS-65 red: cannot run `{label}`: {exc}")
    except subprocess.TimeoutExpired:
        pytest.fail(f"A-PS-65 red: `{label}` did not finish within {timeout} s")


def _tail(proc, n=2500) -> str:
    return (proc.stdout[-n:] + "\n" + proc.stderr[-n:]).strip()


def _venv_bin() -> Path:
    py = _project_python()
    if py is None:
        pytest.fail("A-PS-65 red: no project virtualenv (.venv/bin/python) to run the gates in")
    return py.parent


# ------------------------------------------------------------- Python gates


def test_ruff_and_pyright_exit_zero():
    venv_bin = _venv_bin()
    env = _child_env(venv_bin)
    for tool in ("ruff", "pyright"):
        assert (venv_bin / tool).exists(), f"A-PS-65 red: `{tool}` is not in the project virtualenv"
    gates = (
        ["ruff", "check", "."],
        ["ruff", "format", "--check", "."],
        ["pyright", "-p", ".", "."],
    )
    for args in gates:
        proc = _run([venv_bin / args[0], *args[1:]], cwd=ROOT, env=env, timeout=600)
        assert proc.returncode == 0, (
            f"A-PS-65 red: `{' '.join(args)}` exited {proc.returncode}:\n" + _tail(proc)
        )
    shown = _run([venv_bin / "ruff", "check", "--show-files", "."], cwd=ROOT, env=env, timeout=120)
    checked = [Path(line.strip()) for line in shown.stdout.splitlines() if line.strip()]
    product = [f for f in checked if "assertions" not in f.parts]
    assert any("portfoliosight" in f.parts for f in product), (
        "A-PS-65 red: ruff checks no product file"
    )
    assert any("tests" in f.parts for f in product), "A-PS-65 red: ruff checks no file under tests/"


def test_pytest_passes_with_coverage_thresholds():
    venv_bin = _venv_bin()
    if not (ROOT / "tests").is_dir():
        pytest.fail("A-PS-65 red: tests/ does not exist")
    if not ENGINE.is_dir():
        pytest.fail("A-PS-65 red: portfoliosight/engine/ does not exist")
    engine_files = sorted(p for p in ENGINE.rglob("*.py") if "__pycache__" not in p.parts)
    pragma = [
        p.relative_to(ROOT).as_posix()
        for p in engine_files
        if PRAGMA in p.read_text(encoding="utf-8")
    ]
    assert not pragma, f"A-PS-65 red: coverage exclusion pragmas in engine sources: {pragma}"

    with tempfile.TemporaryDirectory(prefix="ps-gate-a65-") as tmp:
        rc_file = Path(tmp) / "empty.coveragerc"
        rc_file.write_text("")  # our own, empty: the product cannot reach its figure by omission
        report = Path(tmp) / "coverage.json"
        env = _child_env(venv_bin)
        env["COVERAGE_FILE"] = str(Path(tmp) / ".coverage")
        cmd = [venv_bin / "python", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"]
        cmd += ["--cov=portfoliosight", f"--cov-config={rc_file}"]
        cmd += ["--cov-report=term-missing", f"--cov-report=json:{report}"]
        proc = _run(cmd, cwd=ROOT, env=env, timeout=1200)
        assert proc.returncode == 0, (
            f"A-PS-65 red: `pytest --cov=portfoliosight` exited {proc.returncode}:\n" + _tail(proc)
        )
        if not report.is_file():
            pytest.fail("A-PS-65 red: pytest wrote no coverage JSON report:\n" + _tail(proc))
        data = json.loads(report.read_text())

    total = data["totals"]["percent_covered"]
    assert total >= 80, f"A-PS-65 red: total line coverage is {total:.2f}%, below 80%"
    assert data["totals"]["num_statements"] >= 200, "A-PS-65 red: coverage measured almost no code"

    rows = {}
    for name, row in data["files"].items():
        path = (ROOT / name).resolve()
        if ENGINE.resolve() in path.parents:
            rows[path.relative_to(ROOT.resolve()).as_posix()] = row
    on_disk = {p.relative_to(ROOT).as_posix() for p in engine_files}
    unreported = sorted(on_disk - set(rows))
    assert not unreported, (
        f"A-PS-65 red: engine modules absent from the coverage report: {unreported}"
    )
    assert len([r for r in rows.values() if r["summary"]["num_statements"] > 0]) >= 6, (
        f"A-PS-65 red: fewer than six engine modules with code in the report: {sorted(rows)}"
    )
    below = {
        name: (round(row["summary"]["percent_covered"], 2), row.get("missing_lines", [])[:20])
        for name, row in sorted(rows.items())
        if row["summary"]["percent_covered"] != 100 or row.get("missing_lines")
    }
    assert not below, f"A-PS-65 red: engine modules below 100% line coverage (missing): {below}"
    excluded = {
        name: row["excluded_lines"] for name, row in rows.items() if row.get("excluded_lines")
    }
    assert not excluded, f"A-PS-65 red: engine lines excluded from coverage: {excluded}"


# ---------------------------------------------------------------- web gates


def test_npm_lint_typecheck_and_test_exit_zero():
    package = WEB / "package.json"
    if not package.is_file():
        pytest.fail("A-PS-65 red: web/package.json does not exist")
    if not (WEB / "node_modules").is_dir():
        pytest.fail("A-PS-65 red: web/node_modules is missing; run `npm ci` in web/ first")
    scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
    expected = {"lint": r"eslint|biome|oxlint", "typecheck": r"\btsc\b", "test": r"vitest"}
    for name, tool in expected.items():
        assert re.search(tool, scripts.get(name, "")), (
            f"A-PS-65 red: web/package.json script `{name}` must run {tool}; is "
            f"{scripts.get(name)!r}"
        )
        assert not re.search(r"\|\|\s*(true|exit 0|:)|--passWithNoTests", scripts[name]), (
            f"A-PS-65 red: web/package.json script `{name}` cannot fail: {scripts[name]!r}"
        )
    env = _child_env()
    for args, timeout in ((["run", "lint"], 400), (["run", "typecheck"], 400), (["test"], 900)):
        proc = _run(["npm", *args], cwd=WEB, env=env, timeout=timeout)
        assert proc.returncode == 0, (
            f"A-PS-65 red: `npm {' '.join(args)}` exited {proc.returncode} in web/:\n" + _tail(proc)
        )


# ------------------------------------------------- smoke-test titles (parser)


def _lex_ts(src: str) -> tuple[str, dict[int, tuple[str, bool]]]:
    """TypeScript source with comments and string contents blanked (same length, newlines kept),
    plus every string literal as {offset of its opening quote: (text, is_static)}."""
    out = list(src)
    strings: dict[int, tuple[str, bool]] = {}
    n = len(src)

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    def quoted(i: int) -> int:
        quote, j = src[i], i + 1
        while j < n and src[j] != quote and src[j] != "\n":
            j += 2 if src[j] == "\\" else 1
        strings[i] = (src[i + 1 : j], True)
        blank(i + 1, j)
        return j + 1

    def template(i: int) -> int:
        j, static = i + 1, True
        while j < n and src[j] != "`":
            if src[j] == "\\":
                j += 2
            elif src.startswith("${", j):
                static, depth, j = False, 1, j + 2
                while j < n and depth:
                    if src[j] in "'\"":
                        j = quoted(j)
                        continue
                    if src[j] == "`":
                        j = template(j)
                        continue
                    depth += {"{": 1, "}": -1}.get(src[j], 0)
                    j += 1
            else:
                j += 1
        strings[i] = (src[i + 1 : j], static)
        blank(i + 1, j)
        return j + 1

    i, prev, word, spaced = 0, "", "", False
    while i < n:
        char = src[i]
        if src.startswith("//", i):
            end = src.find("\n", i)
            end = n if end < 0 else end
            blank(i, end)
            i = end
        elif src.startswith("/*", i):
            end = src.find("*/", i + 2)
            end = n if end < 0 else end + 2
            blank(i, end)
            i = end
        elif char in "'\"":
            i, prev, word = quoted(i), char, ""
        elif char == "`":
            i, prev, word = template(i), char, ""
        elif char == "/" and (prev == "" or prev in "(,=:[!&|?{};+-*%<>~^" or word == "return"):
            j, in_class = i + 1, False  # a regular-expression literal
            while j < n and src[j] != "\n" and (src[j] != "/" or in_class):
                if src[j] == "\\":
                    j += 1
                elif src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                j += 1
            blank(i + 1, j)
            i, prev, word = j + 1, "/", ""
        else:
            if char.isalnum() or char in "_$":
                word = char if spaced else word + char
            elif not char.isspace():
                word = ""
            spaced = char.isspace()
            prev = prev if spaced else char
            i += 1
    return "".join(out), strings


_DECLARE = re.compile(r"(?<![.\w$])(?:test|it)((?:\s*\.\s*[A-Za-z_]\w*)*)\s*\(\s*")
_TEST_MODIFIERS = {"only", "skip", "fixme", "fail"}


def _test_titles(src: str) -> list[tuple[int, str, bool]]:
    """(offset, title, is_static) of every test declared as `test("title", ...)` in the source."""
    code, strings = _lex_ts(src)
    titles = []
    for match in _DECLARE.finditer(code):
        chain = set(re.findall(r"\w+", match.group(1)))
        if not chain <= _TEST_MODIFIERS or match.end() not in strings:
            continue
        text, static = strings[match.end()]
        titles.append((match.start(), text, static))
    return titles


def test_title_parser_control():
    sample = """
    import { test, expect } from "@playwright/test";
    // test("DoD-99 commented out", async () => {});
    /* test("DoD-98 block", () => {}); */
    test.describe("smoke", () => {
      test.use({ baseURL: "https://portfoliosight.ai" });
      test("DoD-01 loads", async ({ page }) => {
        await page.route("**/api/**", (r) => r.continue());
        await test.step("DoD-97 a step, not a test", async () => {});
        expect(/DoD-\\d+ "x/.test("DoD-96 not a test")).toBe(true);
      });
      test.only('DoD-02 gate', async () => {});
      test.skip(`DoD-03 tmpl`, async () => {});
      test(`DoD-${n} dynamic`, async () => {});
      test . fixme ( "other title" , async () => {});
    });
    """
    found = [(title, static) for _, title, static in _test_titles(sample)]
    assert found == [
        ("DoD-01 loads", True),
        ("DoD-02 gate", True),
        ("DoD-03 tmpl", True),
        ("DoD-${n} dynamic", False),
        ("other title", True),
    ]
    assert "DoD-97 a step, not a test" not in [title for title, _ in found]


def _smoke_source() -> str:
    if not SMOKE.is_file():
        pytest.fail("A-PS-65 red: web/e2e/smoke.spec.ts does not exist")
    return SMOKE.read_text(encoding="utf-8")


def test_smoke_spec_has_exactly_one_test_per_dod_item():
    titles = _test_titles(_smoke_source())
    dynamic = [title for _, title, static in titles if not static]
    assert not dynamic, f"A-PS-65 red: smoke test titles must be static strings: {dynamic[:5]}"
    stray = [title for _, title, _ in titles if not TITLE.match(title)]
    assert not stray, f"A-PS-65 red: smoke tests not named DoD-NN: {stray[:10]}"
    numbers = sorted(int(title[4:6]) for _, title, _ in titles)
    wanted = list(range(1, 32))
    missing = sorted(set(wanted) - set(numbers))
    duplicated = sorted({k for k in numbers if numbers.count(k) > 1})
    assert not missing, f"A-PS-65 red: smoke.spec.ts has no test for DoD items {missing}"
    assert not duplicated, f"A-PS-65 red: smoke.spec.ts has more than one test for {duplicated}"
    assert numbers == wanted and len(titles) == 31


# -------------------------------------------------------- skip-marker grep


def _statement(lines: list[str], index: int, column: int) -> str:
    """The marker's statement: from the hit to where its parentheses close (at most 8 lines)."""
    text, depth, opened = "", 0, False
    for offset, line in enumerate(lines[index : index + 8]):
        piece = line[column:] if offset == 0 else line
        for char in piece:
            if char == "(":
                depth, opened = depth + 1, True
            elif char == ")":
                depth -= 1
            text += char
            if opened and depth <= 0:
                return text
        text += "\n"
    return text


def _unconditional_markers(relative: str, src: str) -> list[str]:
    """Skip/xfail/only/todo markers that the spec's three exceptions do not cover."""
    lines = src.splitlines()
    dod9 = (0, 0)
    if relative.endswith("e2e/smoke.spec.ts"):
        titles = _test_titles(src)
        for k, (offset, title, _) in enumerate(titles):
            if re.match(r"DoD-09\b", title):
                end = titles[k + 1][0] if k + 1 < len(titles) else len(src)
                dod9 = (src.count("\n", 0, offset), src.count("\n", 0, end))
    bad = []
    for index, line in enumerate(lines):
        for match in MARKER.finditer(line):
            statement = _statement(lines, index, match.start())
            if any(name in line or name in statement for name in ALLOWED_ENV):
                continue
            argument = statement.split("(", 1)[1].lstrip() if "(" in statement else ""
            runtime_skip = match.group(0) == ".skip(" and argument[:1] not in (
                "'",
                '"',
                "`",
                ")",
                "",
            )
            in_dod9 = dod9[0] < index <= dod9[1]
            if in_dod9 and runtime_skip and re.search(r"collaps", statement, re.IGNORECASE):
                continue  # DoD 9: no position with both neighbouring ladders collapsed
            bad.append(f"{relative}:{index + 1}: {line.strip()[:120]}")
    return bad


def test_skip_marker_rule_control():
    py = (
        "import os, pytest\n"
        "@pytest.mark.skip(reason='later')\n"
        "def test_a(): ...\n"
        "@pytest.mark.xfail\n"
        "def test_b(): ...\n"
        "@pytest.mark.skip(\n    reason='needs PS_LIVE_TESTS=1'\n)\n"
        "def test_c(): ...\n"
        "def test_d():\n    pytest.skip('no reason')\n"
        "live = pytest.mark.skipif(os.environ.get('PS_LIVE_TESTS') != '1', reason='live')\n"
    )
    bad = _unconditional_markers("tests/test_x.py", py)
    assert [b.split(":")[1] for b in bad] == ["2", "4", "11"]
    ts = (
        'test("DoD-08 risk", async () => {\n  test.skip(!found, "ladders collapsed");\n});\n'
        'test("DoD-09 div", async () => {\n'
        '  test.skip(!found, "no position with both neighbouring ladders collapsed");\n'
        '  test.skip(!process.env.PS_SHARE_TEST_RECIPIENT, "no recipient");\n'
        '  test.skip(slow, "too slow");\n});\n'
        'test.skip("DoD-10 word collapsed", async () => {});\n'
        'test.only("DoD-11", async () => {});\nit.todo("DoD-12");\ntest.fixme();\n'
    )
    bad = _unconditional_markers("web/e2e/smoke.spec.ts", ts)
    assert [b.split(":")[1] for b in bad] == ["2", "7", "9", "10", "11", "12"]
    assert not _unconditional_markers("web/tests/a.test.ts", "describe('x', () => { it('a', f) })")


def test_no_unconditional_skip_xfail_only_or_todo_in_the_test_trees():
    trees = (
        (ROOT / "tests", PY_SUFFIXES),
        (WEB / "tests", JS_SUFFIXES),
        (WEB / "e2e", JS_SUFFIXES),
    )
    scanned: dict[str, int] = {}
    bad: list[str] = []
    for tree, suffixes in trees:
        label = tree.relative_to(ROOT).as_posix()
        if not tree.is_dir():
            pytest.fail(f"A-PS-65 red: {label}/ does not exist")
        scanned[label] = 0
        for path in sorted(tree.rglob("*")):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            if SKIP_DIRS & set(path.relative_to(ROOT).parts):
                continue
            scanned[label] += 1
            bad += _unconditional_markers(
                path.relative_to(ROOT).as_posix(),
                path.read_text(encoding="utf-8", errors="replace"),
            )
    empty = [label for label, count in scanned.items() if count == 0]
    assert not empty, f"A-PS-65 red: no test file found under {empty}; scanned {scanned}"
    assert list((ROOT / "tests").rglob("test_*.py")), "A-PS-65 red: tests/ holds no test_*.py"
    assert SMOKE.is_file(), "A-PS-65 red: web/e2e/smoke.spec.ts does not exist"
    assert not bad, "A-PS-65 red: unconditional skip/xfail/only/todo markers:\n" + "\n".join(
        bad[:30]
    )


# ----------------------------------------------------------------------- docs


def _window(lines: list[str], index: int) -> str:
    return "\n".join(lines[max(0, index - 1) : index + 2])


def _readme_problems(text: str) -> list[str]:
    problems = []
    lines = text.splitlines()
    if len(lines) > 60:
        problems.append(f"README.md has {len(lines)} lines, more than 60")
    for needle in (LAKE, BACKUP):
        if needle not in text:
            problems.append(f"README.md does not contain {needle}")
    for index, line in enumerate(lines):
        window = _window(lines, index)
        if LAKE in line and not re.search(r"\blake\b", window.replace(LAKE, ""), re.IGNORECASE):
            problems.append(f"line {index + 1}: the WSL working copy is not named as the lake")
        if BACKUP in line and not re.search(r"\bback(ed)?[ -]?up\b", window, re.IGNORECASE):
            problems.append(f"line {index + 1}: {BACKUP} is not named as the backup")
        if BACKUP in line and re.search(r"\blake\b", line.replace(LAKE, ""), re.IGNORECASE):
            if LAKE not in line:
                problems.append(f"line {index + 1}: names {BACKUP} together with the lake")
        if "/mnt/d" in line.replace(BACKUP, ""):
            if not re.search(r"mirror", window, re.IGNORECASE):
                problems.append(f"line {index + 1}: names /mnt/d other than as QSE's mirror")
            if re.search(r"/mnt/d\S*\s+(is|as|holds|hosts)\s+the\s+(data\s*)?lake\b", line):
                problems.append(f"line {index + 1}: names /mnt/d as the lake")
    return problems


def test_readme_rule_control():
    good = (
        "# PortfolioSight\n\n## Data\n"
        f"- The lake is the WSL working copy `{LAKE}/`;\n"
        "  `/mnt/d/tft-quantile-forecaster` is only QSE's mirror of it.\n"
        f"- R2 is canonical; `{BACKUP}` is the laptop backup of the bucket.\n"
    )
    assert _readme_problems(good) == []
    old = f"The corpus lands in `data/` (symlinked to `/mnt/d/tft-quantile-forecaster/...`).\n{BACKUP}\n"
    problems = _readme_problems(old + "x\n" * 70)
    assert len(problems) >= 4 and any("mirror" in p for p in problems)
    assert _readme_problems(good.replace("only QSE's mirror of it", "the lake"))


def test_readme_names_the_lake_and_the_backup():
    readme = ROOT / "README.md"
    if not readme.is_file():
        pytest.fail("A-PS-65 red: README.md does not exist")
    problems = _readme_problems(readme.read_text(encoding="utf-8"))
    assert not problems, "A-PS-65 red: " + "; ".join(problems)


def test_roadmap_contains_the_appendix_b_items():
    roadmap = ROOT / "ROADMAP.md"
    if not roadmap.is_file():
        pytest.fail("A-PS-65 red: ROADMAP.md does not exist")
    text = roadmap.read_text(encoding="utf-8")
    missing = [
        item
        for item in ("Paid tier", "Data license", "exact-ENB", "FERS planner")
        if item not in text
    ]
    assert not missing, f"A-PS-65 red: ROADMAP.md lacks the Appendix B items {missing}"
    assert "portfoliosight" in text.lower() and len(text) != 0
