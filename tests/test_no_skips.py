"""No test is switched off (spec 10, DoD 26, expectation M9; A-PS-65).

A skip, xfail, only, todo or fixme marker in ``tests/``, ``web/tests/`` or ``web/e2e/`` is allowed
in two cases only: its own statement names ``PS_LIVE_TESTS`` (the live tests, off unless that
variable is 1), or it is the run-time skip of the collapsed-ladder leg inside the DoD 9 smoke
test. An absent share recipient is a failure, never a skip.

The marker spellings are put together from pieces so that this file does not contain them.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TREES = (
    ("tests", {".py"}),
    ("web/tests", {".ts", ".tsx", ".mts", ".js", ".jsx", ".mjs"}),
    ("web/e2e", {".ts", ".tsx", ".mts", ".js", ".jsx", ".mjs"}),
)
IGNORED_DIRS = {"__gate__", "node_modules", "__pycache__", "artifacts", "test-results"}
SMOKE = "web/e2e/smoke.spec.ts"

_MARK = "pytest" + r"\.mark\."
_DOT = r"\."
MARKER = re.compile(
    "|".join(
        (
            _MARK + "skip" + r"\(",
            _MARK + "xfail",
            _DOT + "skip" + r"\(",
            _DOT + "only" + r"\(",
            _DOT + "todo" + r"\(",
            "test" + _DOT + "fixme",
        )
    )
)
LIVE = "PS_" + "LIVE_TESTS"
# A marker whose first argument is a title (or nothing) declares a test off; anything else is a
# condition evaluated while the test runs.
TITLE_STARTS = ("'", '"', "`", ")", "")
DOD9 = re.compile(r"""^\s*test\(\s*["'`]DoD-09\b""")
NEXT_TEST = re.compile(r"""^\s*test(?:\.\w+)*\(\s*["'`]""")


def _statement(lines: list[str], index: int, column: int) -> str:
    """The marker's statement: from the hit to where its parentheses close (eight lines at most)."""
    text, depth, opened = "", 0, False
    for offset, line in enumerate(lines[index : index + 8]):
        for char in line[column:] if offset == 0 else line:
            if char == "(":
                depth, opened = depth + 1, True
            elif char == ")":
                depth -= 1
            text += char
            if opened and depth <= 0:
                return text
        text += "\n"
    return text


def _dod9_lines(relative: str, lines: list[str]) -> range:
    """The line span of the DoD 9 smoke test (empty for any other file)."""
    if relative != SMOKE:
        return range(0)
    starts = [i for i, line in enumerate(lines) if DOD9.match(line)]
    if not starts:
        return range(0)
    later = [i for i, line in enumerate(lines) if i > starts[0] and NEXT_TEST.match(line)]
    return range(starts[0] + 1, later[0] if later else len(lines))


def unconditional_markers(relative: str, source: str) -> list[str]:
    """Markers that neither exception covers, as ``path:line: text``."""
    lines = source.splitlines()
    dod9 = _dod9_lines(relative, lines)
    bad = []
    for index, line in enumerate(lines):
        for match in MARKER.finditer(line):
            statement = _statement(lines, index, match.start())
            if LIVE in line or LIVE in statement:
                continue
            argument = statement.split("(", 1)[1].lstrip() if "(" in statement else ""
            runtime = match.group(0).endswith("skip(") and argument[:1] not in TITLE_STARTS
            if index in dod9 and runtime and re.search("collaps", statement, re.IGNORECASE):
                continue
            bad.append(f"{relative}:{index + 1}: {line.strip()[:120]}")
    return bad


def _files() -> list[Path]:
    found = []
    for tree, suffixes in TREES:
        base = ROOT / tree
        assert base.is_dir(), f"{tree}/ does not exist"
        files = [
            path
            for path in sorted(base.rglob("*"))
            if path.is_file()
            and path.suffix in suffixes
            and not IGNORED_DIRS & set(path.relative_to(ROOT).parts)
        ]
        assert files, f"no test file found under {tree}/"
        found += files
    return found


def test_the_rule_allows_exactly_the_two_exceptions():
    skip, only, todo = "skip", "only", "todo"
    python = "\n".join(
        (
            f"@pytest.mark.{skip}(reason='later')",
            "def test_a(): ...",
            "@pytest.mark." + "xfail",
            "def test_b(): ...",
            f"live = pytest.mark.{skip}if(os.environ.get('{LIVE}') != '1', reason='live')",
            f"off = pytest.mark.{skip}(\n    reason='{LIVE}=1 required'\n)",
            f"def test_c():\n    pytest.{skip}('no reason')",
        )
    )
    assert [b.split(":")[1] for b in unconditional_markers("tests/test_x.py", python)] == [
        "1",
        "3",
        "10",
    ]
    smoke = "\n".join(
        (
            'test("DoD-08 risk", async () => {',
            f'  step.{skip}(none === null, "ladders collapsed");',
            "});",
            'test("DoD-09 div", async () => {',
            f'  step.{skip}(none === null, "no position with collapsed ladders");',
            f'  test.{skip}(!process.env.PS_SHARE_TEST_RECIPIENT, "no recipient");',
            f'  test.{skip}("collapsed, but unconditional");',
            "});",
            f'test.{only}("DoD-10", async () => {{}});',
            f'it.{todo}("DoD-11");',
            "test." + "fixme();",
        )
    )
    assert [b.split(":")[1] for b in unconditional_markers(SMOKE, smoke)] == [
        "2",
        "6",
        "7",
        "9",
        "10",
        "11",
    ]
    # the same lines in another file get no DoD 9 allowance
    assert len(unconditional_markers("web/e2e/other.spec.ts", smoke)) == 7
    assert unconditional_markers("web/tests/a.test.ts", "describe('x', () => { it('a', f) })") == []


def test_no_test_is_switched_off():
    files = _files()
    assert (ROOT / SMOKE) in files, f"{SMOKE} is not in the scan"
    bad: list[str] = []
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        bad += unconditional_markers(relative, path.read_text(encoding="utf-8", errors="replace"))
    assert not bad, "markers that switch a test off:\n" + "\n".join(bad)


def test_the_share_test_fails_without_its_recipient():
    """DoD 31 reads the recipient as a required setting: no branch runs the test without it."""
    source = (ROOT / SMOKE).read_text(encoding="utf-8")
    start = source.index('test("DoD-31')
    body = source[start:]
    assert 'env("PS_SHARE_TEST_RECIPIENT")' in body
    assert not re.search(r"PS_SHARE_TEST_RECIPIENT[^\n]*\?\?", body), "a fallback for the recipient"
    helpers = (ROOT / "web/e2e/helpers.ts").read_text(encoding="utf-8")
    required = helpers[helpers.index("export function env(") :].split("\n}\n", 1)[0]
    assert "throw new Error" in required, "env() must fail when the variable is absent"
