"""Environment loading and log redaction."""

from __future__ import annotations

import logging
import os

import pytest

from portfoliosight.data import secrets


def test_load_env_sets_only_missing_names(tmp_path, monkeypatch):
    env_file = tmp_path / "ps.env"
    env_file.write_text(
        "# a comment\n"
        "\n"
        "PS_TEST_ALPHA=one\n"
        "export PS_TEST_BETA='two words'\n"
        'PS_TEST_GAMMA="three"\n'
        "PS_TEST_KEPT=from-file\n"
        "not a pair\n"
    )
    for name in ("PS_TEST_ALPHA", "PS_TEST_BETA", "PS_TEST_GAMMA"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PS_TEST_KEPT", "from-environment")

    loaded = secrets.load_env(env_file)

    assert os.environ["PS_TEST_ALPHA"] == "one"
    assert os.environ["PS_TEST_BETA"] == "two words"
    assert os.environ["PS_TEST_GAMMA"] == "three"
    assert os.environ["PS_TEST_KEPT"] == "from-environment"
    assert sorted(loaded) == ["PS_TEST_ALPHA", "PS_TEST_BETA", "PS_TEST_GAMMA"]
    for name in loaded:
        monkeypatch.delenv(name, raising=False)


def test_load_env_missing_file_loads_nothing(tmp_path):
    assert secrets.load_env(tmp_path / "absent.env") == []


def test_default_path_is_the_portfoliosight_env_file():
    assert secrets.DEFAULT_ENV_FILE.as_posix() == "~/.secrets/portfoliosight.env"


def _record(msg: str, *args) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)


@pytest.mark.parametrize(
    ("msg", "args", "expected"),
    [
        ("Authorization: Token abc123", (), "Authorization: Token [redacted]"),
        ("header %s", ("Token abc123",), "header Token [redacted]"),
        ("url ?api_token=abc123&x=1", (), "url ?api_token=[redacted]"),
        ("key is %s here", ("s3cr3t-value",), "key is [redacted] here"),
        ("Token [redacted] stays", (), "Token [redacted] stays"),
        ("nothing to hide %d", (7,), "nothing to hide 7"),
    ],
)
def test_filter_rewrites_tokens_and_configured_values(msg, args, expected):
    record = _record(msg, *args)
    assert secrets.RedactingFilter(["s3cr3t-value", ""]).filter(record) is True
    assert record.getMessage() == expected
    assert "abc123" not in record.getMessage() and "s3cr3t-value" not in str(record.args)


def test_filter_reads_named_secrets_from_the_environment(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "ZZ-SENTINEL-KEY-ZZ")
    record = _record("fetching with ZZ-SENTINEL-KEY-ZZ")
    secrets.RedactingFilter().filter(record)
    assert record.getMessage() == "fetching with [redacted]"


def test_install_redaction_is_idempotent(caplog):
    name = "portfoliosight.test_secrets.install"
    secrets.install_redaction([name], values=["first-value"])
    secrets.install_redaction([name], values=["second-value"])
    logger = logging.getLogger(name)
    filters = [f for f in logger.filters if isinstance(f, secrets.RedactingFilter)]
    assert len(filters) == 1
    with caplog.at_level(logging.INFO, logger=name):
        logger.info("a first-value b second-value c Token xyz")
    assert caplog.messages == ["a [redacted] b [redacted] c Token [redacted]"]


def test_redacted_traceback_keeps_the_trace_and_drops_the_secret(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "tiingo-key-abcdef123456")

    def failing():
        raise RuntimeError("GET failed with Authorization: Token tiingo-key-abcdef123456")

    with pytest.raises(RuntimeError) as caught:
        failing()
    text = secrets.redacted_traceback(caught.value)
    assert text.startswith("Traceback (most recent call last):")
    assert "in failing" in text and text.endswith("Token [redacted]")
    assert "tiingo-key-abcdef123456" not in text
