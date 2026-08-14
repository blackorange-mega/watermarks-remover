"""Tests for the GUI server's static routes, headers and session guard."""

from __future__ import annotations

import http.client
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gui"))

from server import app  # noqa: E402


@pytest.fixture(scope="module")
def server():
    srv = app.make_server()
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    thread.join(timeout=5)


def request(server, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    try:
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, dict(resp.getheaders()), resp.read()
    finally:
        conn.close()


def test_serves_the_shipped_assets(server):
    status, headers, body = request(server, "/")
    assert status == 200
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert b"<html" in body.lower()

    status, headers, _ = request(server, "/assets/app.js")
    assert status == 200
    # nosniff is set, so the script type has to be right or the page won't run
    assert headers["Content-Type"] == "text/javascript; charset=utf-8"


@pytest.mark.parametrize(
    "path",
    [
        "/assets/../server/app.py",
        "/assets/%2e%2e/server/app.py",
        "/assets/....//server/app.py",
        "/assets/../../../../etc/passwd",
        "/assets/C:/Windows/win.ini",
        "/assets/",
        "/assets/missing.css",
    ],
)
def test_only_files_in_the_asset_table_are_served(server, path):
    status, _, _ = request(server, path)
    assert status == 404


def test_asset_table_stays_inside_the_web_directory():
    web = app.WEB_DIR.resolve()
    assert app.ASSETS
    for target in app.ASSETS.values():
        assert target.is_relative_to(web)


def test_control_characters_cannot_inject_a_header(tmp_path, server):
    target = tmp_path / "report.txt"
    target.write_text("ok", encoding="utf-8")
    fid = app.register(target, 'a"\r\nSet-Cookie: pwned=1.txt')

    status, headers, body = request(
        server, f"/api/download?id={fid}", {"X-WM-Token": app.TOKEN}
    )
    assert status == 200
    assert body == b"ok"
    assert "Set-Cookie" not in headers
    assert "\n" not in headers["Content-Disposition"]


def test_api_needs_the_session_token(server):
    status, _, _ = request(server, "/api/download?id=whatever")
    assert status == 403

    status, _, _ = request(server, "/api/download?id=whatever", {"X-WM-Token": "wrong"})
    assert status == 403
