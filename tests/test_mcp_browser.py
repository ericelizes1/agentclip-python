"""End-to-end tests for the browser_* MCP tools.

These actually launch headless Chromium (via the package's [browser]
extra) and drive a tiny local HTTP fixture, so they exercise the same
Playwright path the real MCP server takes — the structural privacy
guarantee (viewport-only PNGs that land on disk) is meaningless if it
isn't pinned by an integration test.

If Playwright + Chromium aren't installed, the import-error test still
runs and the rest are skipped with a clear reason.
"""

from __future__ import annotations

import http.server
import socketserver
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from agentclip import mcp_server


# ---------------------------------------------------------------------------
# Fixtures: tiny static HTTP server with a deterministic page
# ---------------------------------------------------------------------------

FIXTURE_HTML = """<!doctype html>
<html><head><title>browser-test fixture</title></head>
<body>
  <h1 id="hero">Hello from the fixture</h1>
  <input id="q" placeholder="Ask the fixture..." />
  <button id="go">Go</button>
  <div id="status">idle</div>
  <script>
    document.getElementById('go').addEventListener('click', () => {
      const q = document.getElementById('q').value;
      document.getElementById('status').textContent = 'submitted: ' + q;
    });
  </script>
</body></html>
"""


class _FixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — http.server's required name
        body = FIXTURE_HTML.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args, **kwargs):  # silence per-request stderr noise
        pass


@contextmanager
def _serve_fixture():
    # Bind to port 0 so OS picks a free one — keeps tests parallel-safe.
    with socketserver.TCPServer(('127.0.0.1', 0), _FixtureHandler) as srv:
        host, port = srv.server_address
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://{host}:{port}/'
        finally:
            srv.shutdown()


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    # Chromium binary is installed lazily by `playwright install chromium`.
    # If it isn't there, browser_open will raise at launch time.
    return True


needs_browser = pytest.mark.skipif(
    not _playwright_available(),
    reason="Playwright not installed (pip install 'agentclip[browser]')",
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_require_playwright_message_when_missing(monkeypatch):
    """Playwright is a core dependency since 0.5.0 so this should
    basically always succeed. The helper still rewrites the unlikely
    import error (e.g. user installed with --no-deps) into something
    actionable — pin that wording so the agent's next step is clear."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'playwright.sync_api' or name.startswith('playwright.'):
            raise ImportError('mocked: playwright not installed')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)

    with pytest.raises(RuntimeError) as exc:
        mcp_server._require_playwright()
    msg = str(exc.value)
    # Should point at the recovery action, not at the old [browser] extra.
    assert "pip install" in msg
    assert "agentclip" in msg


def test_ensure_chromium_installed_skips_when_present(monkeypatch):
    """If Chromium is already on disk, _ensure_chromium_installed must
    not shell out to `playwright install`. Pin this so first-use
    latency stays cold-start-only — every subsequent browser_open
    should be near-instant."""
    monkeypatch.setattr(
        Path, 'exists', lambda self: True
    )
    called = {'n': 0}

    def fake_run(*args, **kwargs):
        called['n'] += 1
        return None

    import subprocess
    monkeypatch.setattr(subprocess, 'run', fake_run)
    mcp_server._ensure_chromium_installed(verbose=False)
    assert called['n'] == 0


@needs_browser
def test_open_screenshot_close_happy_path(tmp_path):
    """Full open → screenshot → close cycle. Pins three things at once:
    a session is allocated, a viewport-only PNG lands on disk at the
    requested path, and close releases the session id."""
    with _serve_fixture() as url:
        opened = mcp_server.browser_open(url=url, headless=True)
        sid = opened['session_id']
        assert opened['title'] == 'browser-test fixture'
        assert opened['viewport'] == {'width': 1440, 'height': 900}

        out = tmp_path / 'shot.png'
        shot = mcp_server.browser_screenshot(sid, out_path=str(out))
        assert shot['path'] == str(out)
        assert shot['bytes'] > 0
        # PNG magic bytes — pin that we got an actual PNG, not random bytes.
        assert out.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'

        closed = mcp_server.browser_close(sid)
        assert closed == {'closed': True}

        with pytest.raises(ValueError):
            mcp_server.browser_screenshot(sid)


@needs_browser
def test_type_click_and_wait_for_text(tmp_path):
    """The fixture's submit button writes the typed text into a status
    div; we wait for it and confirm get_text returns the new state.
    Exercises type, click, wait_for_text, and get_text together."""
    with _serve_fixture() as url:
        opened = mcp_server.browser_open(url=url, headless=True)
        sid = opened['session_id']
        try:
            typed = mcp_server.browser_type(
                sid, text='hello there', placeholder='Ask the fixture...'
            )
            assert typed['typed_chars'] == len('hello there')

            mcp_server.browser_click(sid, selector='#go')

            matched = mcp_server.browser_wait_for_text(
                sid, text='submitted: hello there', timeout_ms=5_000
            )
            assert matched['matched'] == 'submitted: hello there'

            text = mcp_server.browser_get_text(sid, selector='#status')
            assert text['text'] == 'submitted: hello there'
        finally:
            mcp_server.browser_close(sid)


@needs_browser
def test_screenshot_default_path_lands_under_tmp(tmp_path, monkeypatch):
    """When ``out_path`` is omitted, screenshot picks a path under
    /tmp/agentclip-shots/ — pin it so agents can rely on the convention
    rather than parsing it out of the response."""
    monkeypatch.setattr(mcp_server, '_DEFAULT_SHOT_DIR', tmp_path / 'shots')

    with _serve_fixture() as url:
        opened = mcp_server.browser_open(url=url, headless=True)
        sid = opened['session_id']
        try:
            shot = mcp_server.browser_screenshot(sid)
            path = Path(shot['path'])
            assert path.exists()
            assert path.is_relative_to(tmp_path / 'shots')
            assert path.suffix == '.png'
        finally:
            mcp_server.browser_close(sid)


@needs_browser
def test_wait_for_text_times_out_cleanly(tmp_path):
    """Waiting for text that never appears should raise TimeoutError
    with a useful message — agents act on that text."""
    with _serve_fixture() as url:
        opened = mcp_server.browser_open(url=url, headless=True)
        sid = opened['session_id']
        try:
            with pytest.raises(TimeoutError) as exc:
                mcp_server.browser_wait_for_text(
                    sid, text='this will never appear', timeout_ms=500
                )
            assert 'this will never appear' in str(exc.value)
        finally:
            mcp_server.browser_close(sid)


def test_get_session_unknown_id_raises_clearly():
    with pytest.raises(ValueError) as exc:
        mcp_server._get_session('not-a-real-session')
    msg = str(exc.value)
    assert 'browser_open' in msg
    assert 'not-a-real-session' in msg
