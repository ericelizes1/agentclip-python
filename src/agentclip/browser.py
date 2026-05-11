"""Playwright-backed browser runtime for AgentClip's MCP server.

The public slideshow tools consume files on disk. This runtime fills the
gap by giving agents a built-in browser that can capture both still PNGs
and short animated GIF recordings without ever touching the OS desktop.
"""

from __future__ import annotations

import io
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_VIEWPORT_WIDTH = 1440
DEFAULT_VIEWPORT_HEIGHT = 900
ARTIFACT_ROOT = Path(tempfile.gettempdir()) / 'agentclip-artifacts'


class BrowserRuntimeError(RuntimeError):
    """Raised when the built-in browser runtime cannot satisfy a request."""


@dataclass
class RecordingState:
    frames: list[bytes] = field(default_factory=list)
    durations_ms: list[int] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)


@dataclass
class BrowserSession:
    session_id: str
    playwright: object
    browser: object
    context: object
    page: object
    viewport_width: int
    viewport_height: int
    recording: RecordingState | None = None


class BrowserRuntime:
    """Owns Playwright sessions and disk-backed capture artifacts."""

    def __init__(self, artifact_root: Path | None = None):
        self._artifact_root = artifact_root or ARTIFACT_ROOT
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = threading.RLock()

    def open(
        self,
        *,
        url: str,
        viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
        viewport_height: int = DEFAULT_VIEWPORT_HEIGHT,
    ) -> dict:
        if viewport_width <= 0 or viewport_height <= 0:
            raise BrowserRuntimeError('viewport dimensions must be positive integers')

        session = self._create_session(
            url=url,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return {
            'session_id': session.session_id,
            'url': session.page.url,
            'title': session.page.title(),
            'viewport_width': viewport_width,
            'viewport_height': viewport_height,
        }

    def navigate(self, session_id: str, *, url: str) -> dict:
        session = self._require_session(session_id)
        session.page.goto(url, wait_until='load')
        self._record_frame(session, duration_ms=700)
        return self._page_result(session)

    def click(self, session_id: str, *, selector: str) -> dict:
        session = self._require_session(session_id)
        session.page.locator(selector).first.click()
        self._record_frame(session, duration_ms=700)
        return self._page_result(session)

    def type(
        self,
        session_id: str,
        *,
        selector: str,
        text: str,
        clear_first: bool = True,
    ) -> dict:
        session = self._require_session(session_id)
        locator = session.page.locator(selector).first
        if clear_first:
            locator.fill('')
        locator.fill(text)
        self._record_frame(session, duration_ms=650)
        result = self._page_result(session)
        result['typed'] = text
        return result

    def press_key(self, session_id: str, *, key: str) -> dict:
        session = self._require_session(session_id)
        session.page.keyboard.press(key)
        self._record_frame(session, duration_ms=650)
        result = self._page_result(session)
        result['key'] = key
        return result

    def wait_for_text(self, session_id: str, *, text: str, timeout_ms: int = 10000) -> dict:
        session = self._require_session(session_id)
        session.page.get_by_text(text, exact=False).first.wait_for(timeout=timeout_ms)
        self._record_frame(session, duration_ms=800)
        result = self._page_result(session)
        result['text'] = text
        return result

    def get_text(self, session_id: str, *, selector: str = 'body', max_chars: int = 4000) -> dict:
        session = self._require_session(session_id)
        text = session.page.locator(selector).first.inner_text()
        clipped = text[:max_chars]
        return {
            'session_id': session_id,
            'selector': selector,
            'text': clipped,
            'truncated': len(clipped) != len(text),
        }

    def screenshot(self, session_id: str) -> dict:
        session = self._require_session(session_id)
        path = self._artifact_path('shots', session_id, 'png')
        session.page.screenshot(path=str(path))
        return {
            'session_id': session_id,
            'path': str(path),
            'bytes': path.stat().st_size,
        }

    def start_recording(self, session_id: str) -> dict:
        session = self._require_session(session_id)
        if session.recording is not None:
            raise BrowserRuntimeError(f'session {session_id} is already recording')
        session.recording = RecordingState()
        self._record_frame(session, duration_ms=900)
        return {
            'session_id': session_id,
            'recording_active': True,
        }

    def stop_recording(self, session_id: str) -> dict:
        session = self._require_session(session_id)
        recording = session.recording
        if recording is None:
            raise BrowserRuntimeError(f'session {session_id} is not recording')

        self._record_frame(session, duration_ms=1200)
        path = self._artifact_path('recordings', session_id, 'gif')
        _write_gif(recording.frames, path, recording.durations_ms)
        duration_ms = sum(recording.durations_ms)
        session.recording = None
        return {
            'session_id': session_id,
            'path': str(path),
            'bytes': path.stat().st_size,
            'duration_ms': duration_ms,
            'format': 'gif',
        }

    def close(self, session_id: str) -> dict:
        with self._lock:
            session = self._require_session(session_id)
            recording_result = None
            if session.recording is not None:
                recording_result = self.stop_recording(session_id)
            self._sessions.pop(session_id, None)

        errors: list[str] = []
        for resource in (session.page, session.context, session.browser, session.playwright):
            try:
                resource.close()
            except AttributeError:
                try:
                    resource.stop()
                except Exception as exc:  # pragma: no cover - cleanup best effort
                    errors.append(str(exc))
            except Exception as exc:  # pragma: no cover - cleanup best effort
                errors.append(str(exc))

        result = {'session_id': session_id, 'closed': True}
        if recording_result is not None:
            result['recording'] = recording_result
        if errors:
            result['cleanup_errors'] = errors
        return result

    def _require_session(self, session_id: str) -> BrowserSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise BrowserRuntimeError(
                f'no browser session {session_id!r}. Open a session with browser_open first.'
            )
        return session

    def _create_session(
        self,
        *,
        url: str,
        viewport_width: int,
        viewport_height: int,
    ) -> BrowserSession:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - exercised by tests via patching
            raise BrowserRuntimeError(
                'Playwright is unavailable. Re-run `agentclip setup --force` to install Chromium.'
            ) from exc

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={
                'width': viewport_width,
                'height': viewport_height,
            }
        )
        page = context.new_page()
        page.goto(url, wait_until='load')
        return BrowserSession(
            session_id=f'br_{uuid.uuid4().hex[:12]}',
            playwright=pw,
            browser=browser,
            context=context,
            page=page,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )

    def _record_frame(self, session: BrowserSession, *, duration_ms: int) -> None:
        recording = session.recording
        if recording is None:
            return
        frame = session.page.screenshot(type='png')
        recording.frames.append(frame)
        recording.durations_ms.append(duration_ms)

    def _artifact_path(self, kind: str, session_id: str, extension: str) -> Path:
        root = self._artifact_root / kind
        root.mkdir(parents=True, exist_ok=True)
        return root / f'{session_id}-{int(time.time() * 1000)}.{extension}'

    def _page_result(self, session: BrowserSession) -> dict:
        return {
            'session_id': session.session_id,
            'url': session.page.url,
            'title': session.page.title(),
        }


_RUNTIME = BrowserRuntime()


def get_browser_runtime() -> BrowserRuntime:
    return _RUNTIME


def _write_gif(frames: list[bytes], path: Path, durations_ms: list[int]) -> None:
    if not frames:
        raise BrowserRuntimeError('recording captured no frames')
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - exercised by tests via patching
        raise BrowserRuntimeError(
            'Pillow is unavailable. Reinstall agentclip so recording support is available.'
        ) from exc

    opened = [Image.open(io.BytesIO(frame)).convert('RGB') for frame in frames]
    if len(opened) == 1:
        opened.append(opened[0].copy())
        durations_ms = [durations_ms[0], durations_ms[0]]

    first, rest = opened[0], opened[1:]
    first.save(
        path,
        save_all=True,
        append_images=rest,
        duration=durations_ms,
        loop=0,
        optimize=False,
    )
