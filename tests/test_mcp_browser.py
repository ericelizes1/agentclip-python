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
    assert 'pip install' in msg
    assert 'agentclip' in msg


def test_ensure_chromium_installed_skips_when_present(monkeypatch):
    """If Chromium is already on disk, _ensure_chromium_installed must
    not shell out to `playwright install`. Pin this so first-use
    latency stays cold-start-only — every subsequent browser_open
    should be near-instant."""
    monkeypatch.setattr(Path, 'exists', lambda self: True)
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
        opened = mcp_server._browser_open_impl(
            url=url,
            viewport_width=1440,
            viewport_height=900,
            headless=True,
            wait_until='networkidle',
        )
        sid = opened['session_id']
        assert opened['title'] == 'browser-test fixture'
        assert opened['viewport'] == {'width': 1440, 'height': 900}

        out = tmp_path / 'shot.png'
        shot = mcp_server._browser_screenshot_impl(sid, out_path=str(out), full_page=False)
        assert shot['path'] == str(out)
        assert shot['bytes'] > 0
        # PNG magic bytes — pin that we got an actual PNG, not random bytes.
        assert out.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'

        closed = mcp_server._browser_close_impl(sid)
        assert closed == {'closed': True}

        with pytest.raises(ValueError):
            mcp_server._browser_screenshot_impl(sid, out_path=None, full_page=False)


@needs_browser
def test_type_click_and_wait_for_text(tmp_path):
    """The fixture's submit button writes the typed text into a status
    div; we wait for it and confirm get_text returns the new state.
    Exercises type, click, wait_for_text, and get_text together."""
    with _serve_fixture() as url:
        opened = mcp_server._browser_open_impl(
            url=url,
            viewport_width=1440,
            viewport_height=900,
            headless=True,
            wait_until='networkidle',
        )
        sid = opened['session_id']
        try:
            typed = mcp_server._browser_type_impl(
                sid,
                text='hello there',
                placeholder='Ask the fixture...',
                selector=None,
                role=None,
                delay_ms=15,
            )
            assert typed['typed_chars'] == len('hello there')

            mcp_server._browser_click_impl(
                sid,
                selector='#go',
                text=None,
                role=None,
                name=None,
            )

            matched = mcp_server._browser_wait_for_text_impl(
                sid, text='submitted: hello there', timeout_ms=5_000
            )
            assert matched['matched'] == 'submitted: hello there'

            text = mcp_server._browser_get_text_impl(sid, selector='#status')
            assert text['text'] == 'submitted: hello there'
        finally:
            mcp_server._browser_close_impl(sid)


@needs_browser
def test_screenshot_default_path_lands_under_tmp(tmp_path, monkeypatch):
    """When ``out_path`` is omitted, screenshot picks a path under
    /tmp/agentclip-shots/ — pin it so agents can rely on the convention
    rather than parsing it out of the response."""
    monkeypatch.setattr(mcp_server, '_DEFAULT_SHOT_DIR', tmp_path / 'shots')

    with _serve_fixture() as url:
        opened = mcp_server._browser_open_impl(
            url=url,
            viewport_width=1440,
            viewport_height=900,
            headless=True,
            wait_until='networkidle',
        )
        sid = opened['session_id']
        try:
            shot = mcp_server._browser_screenshot_impl(sid, out_path=None, full_page=False)
            path = Path(shot['path'])
            assert path.exists()
            assert path.is_relative_to(tmp_path / 'shots')
            assert path.suffix == '.png'
        finally:
            mcp_server._browser_close_impl(sid)


@needs_browser
def test_wait_for_text_times_out_cleanly(tmp_path):
    """Waiting for text that never appears should raise TimeoutError
    with a useful message — agents act on that text."""
    with _serve_fixture() as url:
        opened = mcp_server._browser_open_impl(
            url=url,
            viewport_width=1440,
            viewport_height=900,
            headless=True,
            wait_until='networkidle',
        )
        sid = opened['session_id']
        try:
            with pytest.raises(TimeoutError) as exc:
                mcp_server._browser_wait_for_text_impl(
                    sid, text='this will never appear', timeout_ms=500
                )
            assert 'this will never appear' in str(exc.value)
        finally:
            mcp_server._browser_close_impl(sid)


def test_get_session_unknown_id_raises_clearly():
    with pytest.raises(ValueError) as exc:
        mcp_server._get_session('not-a-real-session')
    msg = str(exc.value)
    assert 'browser_open' in msg
    assert 'not-a-real-session' in msg


# --- async wrapper regression test ---
# The previous suite called mcp_server.browser_open(...) directly, which
# bypassed the async wrapper FastMCP actually invokes. That hid a real
# bug for one whole release: Playwright's sync API refuses to coexist
# with an asyncio loop ("It looks like you are using Playwright Sync API
# inside the asyncio loop"), so the tools failed the moment the live
# MCP server tried to use them. This test pins the fix — every browser
# tool MUST be an async function, and at least one full open→shot→close
# cycle MUST work when driven through an event loop.


def test_browser_tools_are_async():
    """Structural check — every browser_* @mcp.tool wrapper must be a
    coroutine function so FastMCP can await it. If this fails, the bug
    is back: a sync @mcp.tool will run Playwright on the FastMCP loop's
    thread and crash with the asyncio error."""
    import inspect

    for name in (
        'browser_open',
        'browser_navigate',
        'browser_type',
        'browser_click',
        'browser_press_key',
        'browser_wait_for_text',
        'browser_screenshot',
        'browser_get_text',
        'browser_close',
        'browser_list_sessions',
        'browser_start_recording',
        'browser_stop_recording',
    ):
        fn = getattr(mcp_server, name)
        # FastMCP wraps the original function; the wrapped callable still
        # has `__wrapped__` (or the wrapper itself is a coroutine fn).
        target = getattr(fn, '__wrapped__', fn)
        assert inspect.iscoroutinefunction(target), (
            f'{name} must be async — sync browser tools crash under '
            f'FastMCP because Playwright sync refuses to run inside an '
            f'asyncio loop. See _run_in_browser_thread in mcp_server.py.'
        )


@needs_browser
def test_async_open_screenshot_close_under_event_loop(tmp_path):
    """End-to-end through the async wrapper, driven under an asyncio
    loop — the same shape of call FastMCP makes. Catches the
    'Sync API inside asyncio loop' regression by actually running it."""
    import asyncio

    async def run():
        with _serve_fixture() as url:
            opened = await mcp_server.browser_open(url=url, headless=True)
            sid = opened['session_id']
            assert opened['title'] == 'browser-test fixture'

            out = tmp_path / 'shot-async.png'
            shot = await mcp_server.browser_screenshot(session_id=sid, out_path=str(out))
            assert shot['path'] == str(out)
            assert out.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'

            closed = await mcp_server.browser_close(session_id=sid)
            assert closed == {'closed': True}

    asyncio.run(run())


@needs_browser
def test_start_recording_without_record_flag_returns_helpful_error(tmp_path):
    """If the agent opens a session without record_video=True and then
    calls start_recording, raise a clear error pointing at the right fix.
    This is the recovery the skill steers agents toward."""
    with _serve_fixture() as url:
        opened = mcp_server._browser_open_impl(
            url=url,
            viewport_width=800,
            viewport_height=600,
            headless=True,
            wait_until='load',
        )
        sid = opened['session_id']
        try:
            with pytest.raises(ValueError, match='record_video=True'):
                mcp_server._browser_start_recording_impl(sid)
        finally:
            mcp_server._browser_close_impl(sid)


@needs_browser
def test_record_open_and_stop_writes_webm(tmp_path):
    """End-to-end: open with record_video=True, do an interaction, stop
    recording, get back a real WebM on disk. Pins the privacy guarantee
    (viewport-only) and the wire shape (path/bytes/format)."""
    with _serve_fixture() as url:
        opened = mcp_server._browser_open_impl(
            url=url,
            viewport_width=800,
            viewport_height=600,
            headless=True,
            wait_until='load',
            record_video=True,
        )
        assert opened['recording_active'] is True
        sid = opened['session_id']

        # start_recording is a no-op confirmation when already recording.
        confirmed = mcp_server._browser_start_recording_impl(sid)
        assert confirmed == {'session_id': sid, 'recording_active': True}

        # Drive one interaction so the video has at least one frame change.
        mcp_server._browser_click_impl(sid, '#go', None, None, None)

        result = mcp_server._browser_stop_recording_impl(sid)
        assert result['format'] == 'webm'
        assert result['bytes'] > 0
        assert Path(result['path']).exists()
        assert Path(result['path']).suffix == '.webm'


@needs_browser
def test_screenshot_with_annotation_circles_selector(tmp_path):
    """Pin: passing annotations=[{type: 'circle', target: '#hero', label: 'X'}]
    yields a PNG whose bytes differ from the un-annotated capture of the
    same page. The visual difference is the only honest assertion (we
    can't grep an SVG inside a PNG), but it's enough to catch a regression
    where the overlay isn't actually painted before the screenshot."""
    with _serve_fixture() as url:
        opened = mcp_server._browser_open_impl(
            url=url,
            viewport_width=800,
            viewport_height=600,
            headless=True,
            wait_until='load',
        )
        sid = opened['session_id']
        try:
            plain_path = tmp_path / 'plain.png'
            annotated_path = tmp_path / 'annotated.png'
            plain = mcp_server._browser_screenshot_impl(
                sid,
                str(plain_path),
                full_page=False,
            )
            annotated = mcp_server._browser_screenshot_impl(
                sid,
                str(annotated_path),
                full_page=False,
                annotations=[
                    {'type': 'circle', 'target': '#hero', 'label': 'live'},
                ],
            )
            assert 'annotations' in annotated
            assert annotated['annotations']['failed'] == []
            assert len(annotated['annotations']['placed']) == 1
            assert annotated['annotations']['placed'][0]['type'] == 'circle'
            # Annotated PNG must differ from plain -- the overlay was drawn.
            assert plain_path.read_bytes() != annotated_path.read_bytes()
        finally:
            mcp_server._browser_close_impl(sid)


@needs_browser
def test_screenshot_annotation_reports_missing_target(tmp_path):
    """A bad selector lands in `failed[]`, not as an exception. Lets the
    agent recover with a better selector instead of having to wrap every
    call in a try/except."""
    out = tmp_path / 'shot.png'
    with _serve_fixture() as url:
        opened = mcp_server._browser_open_impl(
            url=url,
            viewport_width=800,
            viewport_height=600,
            headless=True,
            wait_until='load',
        )
        sid = opened['session_id']
        try:
            result = mcp_server._browser_screenshot_impl(
                sid,
                str(out),
                full_page=False,
                annotations=[
                    {'type': 'circle', 'target': '#does-not-exist'},
                ],
            )
            assert result['annotations']['placed'] == []
            assert len(result['annotations']['failed']) == 1
            assert result['annotations']['failed'][0]['reason'] == 'target not found'
            # Screenshot still wrote -- the failure is informational, not fatal.
            assert out.exists()
        finally:
            mcp_server._browser_close_impl(sid)


@needs_browser
def test_screenshot_overlay_removed_after_capture(tmp_path):
    """The overlay must be torn down after the screenshot so subsequent
    captures, page.evaluate calls, or interactions don't see it. Pins
    the cleanup that prevents 'annotations stuck on the page' bugs."""
    out1 = tmp_path / 'first.png'
    out2 = tmp_path / 'second.png'
    with _serve_fixture() as url:
        opened = mcp_server._browser_open_impl(
            url=url,
            viewport_width=800,
            viewport_height=600,
            headless=True,
            wait_until='load',
        )
        sid = opened['session_id']
        try:
            mcp_server._browser_screenshot_impl(
                sid,
                str(out1),
                full_page=False,
                annotations=[{'type': 'rect', 'target': '#hero', 'label': 'first'}],
            )
            # After the annotated capture, the overlay should be gone.
            still_present = mcp_server._browser_sessions[sid]['page'].evaluate(
                f"() => !!document.getElementById('{mcp_server._ANNOTATION_OVERLAY_ID}')"
            )
            assert still_present is False
            # Second un-annotated capture should match the plain baseline,
            # not the prior annotated frame.
            mcp_server._browser_screenshot_impl(sid, str(out2), full_page=False)
            assert out1.read_bytes() != out2.read_bytes()
        finally:
            mcp_server._browser_close_impl(sid)
