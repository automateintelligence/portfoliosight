"""The container's health probe: 0 only for a 200, and the secret goes in the header."""

from __future__ import annotations

import http.server
import threading

import pytest

from portfoliosight.api import healthcheck


class _Handler(http.server.BaseHTTPRequestHandler):
    seen: list[tuple[str, str | None]] = []

    def do_GET(self):  # noqa: N802 (the base class names it)
        _Handler.seen.append((self.path, self.headers.get("x-ps-gate")))
        self.send_response(200 if self.headers.get("x-ps-gate") == "probe-secret" else 403)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002 (the base class names it)
        pass


@pytest.fixture
def port():
    _Handler.seen = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()
    thread.join(5)


def test_probe_passes_with_the_secret_and_fails_without(port, monkeypatch, capsys):
    monkeypatch.setenv("PS_GATE_SECRET", "probe-secret")
    assert healthcheck.probe(port=port) == 0
    assert _Handler.seen == [("/v1/health", "probe-secret")]
    monkeypatch.setenv("PS_GATE_SECRET", "wrong")
    assert healthcheck.probe(port=port) == 1
    monkeypatch.delenv("PS_GATE_SECRET")
    assert healthcheck.probe(port=port) == 1
    printed = capsys.readouterr()
    assert "HTTP 403" in printed.err and "secret" not in printed.err + printed.out


def test_probe_fails_when_nothing_listens(monkeypatch, capsys):
    monkeypatch.setattr(healthcheck, "TIMEOUT_SECONDS", 0.5)
    assert healthcheck.probe(port=1) == 1
    assert "health probe failed" in capsys.readouterr().err
    assert (healthcheck.HOST, healthcheck.PORT) == ("127.0.0.1", 8000)
