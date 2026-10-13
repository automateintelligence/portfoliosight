"""The smoke suite has exactly one test per definition of done (spec 10, 11; A-PS-65).

``web/e2e/smoke.spec.ts`` declares 31 tests with static titles ``DoD-01`` to ``DoD-31``, each
once, and the two production projects of ``web/playwright.config.ts`` between them run every one.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "web" / "e2e" / "smoke.spec.ts"
CONFIG = ROOT / "web" / "playwright.config.ts"
TITLE = re.compile(r"^DoD-(0[1-9]|[12]\d|3[01])\b")
DECLARED = re.compile(r"""^[ \t]*test((?:\.\w+)*)\(\s*(["'`])(.*?)\2""", re.MULTILINE)
MODIFIERS = {"only", "skip", "fixme", "fail", "slow"}


def declared_titles(source: str) -> list[str]:
    """Titles of the tests a spec declares as ``test("title", ...)``, in file order."""
    titles = []
    for match in DECLARED.finditer(source):
        chain = set(filter(None, match.group(1).split(".")))
        if chain <= MODIFIERS:
            titles.append(match.group(3))
    return titles


def _regex(name: str, source: str) -> re.Pattern[str]:
    found = re.search(name + r"\s*[:=]\s*/((?:[^/\\\n]|\\.)+)/", source)
    assert found, f"{name} is not a regular expression literal in web/playwright.config.ts"
    return re.compile(found.group(1))


def test_the_parser_reads_declarations_only():
    sample = "\n".join(
        (
            'test.describe("share", () => {',
            '  test("DoD-31 share", async () => {',
            '    await test.step("DoD-99 a step", async () => {});',
            "  });",
            "});",
            'test.use({ baseURL: "x" });',
            "test(`DoD-${n} dynamic`, async () => {});",
            "test('other', async () => {});",
        )
    )
    assert declared_titles(sample) == ["DoD-31 share", "DoD-${n} dynamic", "other"]


def test_one_test_per_definition_of_done():
    titles = declared_titles(SMOKE.read_text(encoding="utf-8"))
    assert not [t for t in titles if "${" in t], "smoke test titles must be static strings"
    assert not [t for t in titles if not TITLE.match(t)], "every smoke test is named DoD-NN"
    numbers = sorted(int(t[4:6]) for t in titles)
    assert numbers == list(range(1, 32)), f"expected DoD-01 to DoD-31 once each, found {numbers}"
    assert len(titles) == 31
    assert all(len(t) > len("DoD-NN ") for t in titles), "each title says what it demonstrates"


def test_every_definition_of_done_runs_in_a_production_project():
    config = CONFIG.read_text(encoding="utf-8")
    desktop_block = config[config.index('name: "chromium-desktop"') :].split("}", 1)[0]
    not_on_desktop = _regex("grepInvert", desktop_block)
    not_on_phone = _regex("desktopOnly", config)
    assert 'name: "chromium-phone"' in config and "grepInvert: desktopOnly" in config
    titles = declared_titles(SMOKE.read_text(encoding="utf-8"))
    nowhere = [t for t in titles if not_on_desktop.search(t) and not_on_phone.search(t)]
    assert not nowhere, f"smoke tests that no production project runs: {nowhere}"
    on_phone = [t for t in titles if not not_on_phone.search(t)]
    assert len(on_phone) >= 12, "the phone project runs the first-screen and control tests"
    assert any(t.startswith("DoD-04") for t in on_phone), "DoD 4 is the phone layout"
