"""Tests for Layer B rewrite_text hook (offline / print-prompt + client hardening)."""

from __future__ import annotations

import http.server
import json
import sys
import threading
import time
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "service" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rewrite_text  # noqa: E402
from rewrite_text import (  # noqa: E402
    _check_remote,
    _flag_env,
    _lexical_divergence,
    _select_candidate,
    build_prompt,
    rewrite,
)


def _rewrite_kwargs(**overrides):
    kwargs = dict(
        backend="print-prompt",
        model=None,
        base_url=None,
        api_key=None,
        strength="paraphrase",
        lang="French",
        original_lang="English",
        timeout=5.0,
        layer_a_after=True,
        temperature=0.9,
        candidates=1,
    )
    kwargs.update(overrides)
    return kwargs


def test_build_prompt_paraphrase_is_word_choice_plus_syntax():
    p = build_prompt("paraphrase", "Hello world facts 42.", lang="French", original_lang="English")
    assert "Hello world facts 42." in p
    assert "clause order" in p
    assert "function words" in p


def test_build_prompt_humanize_and_code_contain_text():
    for strength, keyword in (("humanize", "human wrote it"), ("code", "comments")):
        p = build_prompt(strength, "ABC 123", lang="French", original_lang="English")
        assert "ABC 123" in p
        assert keyword in p


def test_build_prompt_unknown_strength_raises():
    with pytest.raises(ValueError):
        build_prompt("nope", "ABC", lang="French", original_lang="English")


def test_print_prompt_backend():
    out, info = rewrite("Sample prose about water marks.", **_rewrite_kwargs())
    assert info["mode"] == "print-prompt"
    assert "Sample prose" in out
    assert info["backend"] == "print-prompt"
    assert info["temperature"] == 0.9


def test_print_prompt_ignores_candidates():
    out, info = rewrite("Sample prose about water marks.", **_rewrite_kwargs(candidates=2))
    assert info["mode"] == "print-prompt"
    assert isinstance(out, str)
    assert "Sample prose" in out


def test_structural_and_backtranslate_prompts():
    for strength in ("structural", "backtranslate"):
        p = build_prompt(strength, "ABC 123", lang="German", original_lang="English")
        assert "ABC 123" in p


def test_lexical_divergence_identical_is_zero():
    assert _lexical_divergence("the cat sat", "the cat sat") == 0.0


def test_lexical_divergence_fully_different_higher_than_similar():
    similar = _lexical_divergence("the cat sat on the mat", "the dog sat on the mat")
    different = _lexical_divergence("the cat sat on the mat", "alpha beta gamma delta")
    assert different > similar


def test_lexical_divergence_empty_inputs():
    assert _lexical_divergence("", "") == 0.0
    assert _lexical_divergence("", "text") == 1.0
    assert _lexical_divergence("text", "") == 1.0


def test_select_candidate_prefers_more_divergent():
    original = "the cat sat on the mat"
    best, scores = _select_candidate(
        original,
        ["the cat sat on the mat", "the dog sat on the mat", "alpha beta gamma delta"],
    )
    assert best == "alpha beta gamma delta"
    assert len(scores) == 3


# ---------------------------------------------------------------------------
# HTTP client hardening: default-deny allowlist, scheme guard, no redirects
# ---------------------------------------------------------------------------


def _rewrite_http_kwargs(base_url: str, **overrides):
    kwargs = dict(
        backend="openai-compatible",
        model="m",
        base_url=base_url,
        api_key="sk-test-key-123",
        strength="paraphrase",
        lang="French",
        original_lang="English",
        timeout=5.0,
        layer_a_after=False,
        temperature=0.9,
        candidates=1,
    )
    kwargs.update(overrides)
    return kwargs


def test_check_remote_loopback_allowed_without_opt_in():
    # Must not raise.
    _check_remote("http://127.0.0.1:11434", allow_remote=False)
    _check_remote("http://localhost:11434", allow_remote=False)
    _check_remote("http://[::1]:11434", allow_remote=False)


def test_check_remote_denies_non_loopback_without_opt_in():
    with pytest.raises(SystemExit):
        _check_remote("http://example.com:11434", allow_remote=False)


def test_check_remote_allows_non_loopback_with_opt_in(capsys):
    _check_remote("http://example.com:11434", allow_remote=True)
    err = capsys.readouterr().err
    assert "content will leave this machine" in err


def test_check_remote_denies_non_http_scheme():
    with pytest.raises(SystemExit):
        _check_remote("file:///etc/passwd", allow_remote=True)


def test_flag_env(monkeypatch):
    assert not _flag_env("WATERMARKS_REWRITE_ALLOW_REMOTE")
    monkeypatch.setenv("WATERMARKS_REWRITE_ALLOW_REMOTE", "1")
    assert _flag_env("WATERMARKS_REWRITE_ALLOW_REMOTE")
    monkeypatch.setenv("WATERMARKS_REWRITE_ALLOW_REMOTE", "true")
    assert _flag_env("WATERMARKS_REWRITE_ALLOW_REMOTE")
    monkeypatch.setenv("WATERMARKS_REWRITE_ALLOW_REMOTE", "0")
    assert not _flag_env("WATERMARKS_REWRITE_ALLOW_REMOTE")


def test_openai_compatible_sends_reasoning_effort_when_set():
    captured = {}

    class Collector(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            captured["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"choices": [{"message": {"content": "rewritten"}}]}')

        def log_message(self, format, *args):  # noqa: A002
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Collector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        result, _ = rewrite(
            "hello",
            **_rewrite_http_kwargs(
                f"http://127.0.0.1:{server.server_address[1]}",
                reasoning_effort="none",
            ),
        )
        assert result == "rewritten"
        assert captured["body"]["reasoning_effort"] == "none"

        captured.clear()
        rewrite(
            "hello",
            **_rewrite_http_kwargs(
                f"http://127.0.0.1:{server.server_address[1]}",
                reasoning_effort=None,
            ),
        )
        assert "reasoning_effort" not in captured["body"]
    finally:
        server.shutdown()


def test_rewrite_denies_remote_host_without_opt_in():
    with pytest.raises(SystemExit):
        rewrite("secret text", **_rewrite_http_kwargs("http://example.com:11434"))


def test_rewrite_blocks_redirect_and_never_sends_key():
    """A 302 from the (loopback) endpoint must not re-send the API key to the
    redirect target — the request must fail instead."""
    state: dict = {"collector_port": None}
    captured: dict = {}

    class Redirector(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{state['collector_port']}/collect",
            )
            self.end_headers()

        def log_message(self, format, *args):  # noqa: A002
            pass

    class Collector(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            captured["auth"] = self.headers.get("Authorization")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                b'{"choices": [{"message": {"content": "rewritten"}}]}'
            )

        def log_message(self, format, *args):  # noqa: A002
            pass

    collector = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Collector)
    redirector = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Redirector)
    state["collector_port"] = collector.server_address[1]
    threading.Thread(target=collector.serve_forever, daemon=True).start()
    threading.Thread(target=redirector.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError):
            rewrite(
                "secret text",
                **_rewrite_http_kwargs(
                    f"http://127.0.0.1:{redirector.server_address[1]}"
                ),
            )
        time.sleep(0.2)
        assert captured == {}, "redirect target received a request (key leak?)"
    finally:
        collector.shutdown()
        redirector.shutdown()
