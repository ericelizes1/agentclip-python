from __future__ import annotations

from pathlib import Path

from agentclip.browser import BrowserRuntime, BrowserSession


class _FakeLocator:
    def __init__(self, page: _FakePage, selector: str):
        self._page = page
        self._selector = selector

    @property
    def first(self) -> _FakeLocator:
        return self

    def click(self) -> None:
        self._page.events.append(f'click:{self._selector}')

    def fill(self, text: str) -> None:
        self._page.values[self._selector] = text
        self._page.events.append(f'fill:{self._selector}:{text}')

    def inner_text(self) -> str:
        return self._page.text_by_selector.get(self._selector, '')

    def wait_for(self, timeout: int) -> None:
        self._page.events.append(f'wait:{self._selector}:{timeout}')


class _FakeKeyboard:
    def __init__(self, page: _FakePage):
        self._page = page

    def press(self, key: str) -> None:
        self._page.events.append(f'press:{key}')


class _FakePage:
    def __init__(self):
        self.url = 'https://example.test/'
        self.events: list[str] = []
        self.values: dict[str, str] = {}
        self.text_by_selector = {'body': 'hello world', '#summary': 'summary text'}
        self.keyboard = _FakeKeyboard(self)

    def title(self) -> str:
        return 'Example Page'

    def goto(self, url: str, wait_until: str = 'load') -> None:
        self.url = url
        self.events.append(f'goto:{url}:{wait_until}')

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)

    def get_by_text(self, text: str, exact: bool = False) -> _FakeLocator:
        return _FakeLocator(self, f'text={text}:{exact}')

    def screenshot(self, *, path: str | None = None, type: str | None = None) -> bytes | None:
        png = (
            b'\x89PNG\r\n\x1a\n'
            b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01'
            b'\x0b\xe7\x02\xbc\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        if path is not None:
            Path(path).write_bytes(png)
            return None
        return png

    def close(self) -> None:
        self.events.append('page-close')


class _FakeContext:
    def close(self) -> None:
        return None


class _FakeBrowser:
    def close(self) -> None:
        return None


class _FakePlaywright:
    def stop(self) -> None:
        return None


def _make_session() -> BrowserSession:
    return BrowserSession(
        session_id='br_test',
        playwright=_FakePlaywright(),
        browser=_FakeBrowser(),
        context=_FakeContext(),
        page=_FakePage(),
        viewport_width=1440,
        viewport_height=900,
    )


def test_screenshot_writes_png_to_disk(tmp_path, monkeypatch) -> None:
    runtime = BrowserRuntime(artifact_root=tmp_path)
    monkeypatch.setattr(runtime, '_create_session', lambda **kwargs: _make_session())

    opened = runtime.open(url='https://example.test')
    shot = runtime.screenshot(opened['session_id'])

    assert shot['path'].endswith('.png')
    assert Path(shot['path']).exists()
    assert shot['bytes'] > 0


def test_recording_tracks_actions_and_writes_gif(tmp_path, monkeypatch) -> None:
    runtime = BrowserRuntime(artifact_root=tmp_path)
    monkeypatch.setattr(runtime, '_create_session', lambda **kwargs: _make_session())

    written: dict[str, object] = {}

    def _fake_write_gif(frames, path, durations_ms):
        written['frames'] = len(frames)
        written['durations'] = list(durations_ms)
        path.write_bytes(b'GIF89a')

    monkeypatch.setattr('agentclip.browser._write_gif', _fake_write_gif)

    opened = runtime.open(url='https://example.test')
    runtime.start_recording(opened['session_id'])
    runtime.navigate(opened['session_id'], url='https://example.test/next')
    runtime.click(opened['session_id'], selector='#cta')
    runtime.type(opened['session_id'], selector='#search', text='agentclip')
    result = runtime.stop_recording(opened['session_id'])

    assert result['format'] == 'gif'
    assert Path(result['path']).exists()
    assert written['frames'] == 5
    assert result['duration_ms'] == sum(written['durations'])


def test_close_auto_stops_active_recording(tmp_path, monkeypatch) -> None:
    runtime = BrowserRuntime(artifact_root=tmp_path)
    monkeypatch.setattr(runtime, '_create_session', lambda **kwargs: _make_session())
    monkeypatch.setattr(
        'agentclip.browser._write_gif',
        lambda frames, path, durations_ms: path.write_bytes(b'GIF89a'),
    )

    opened = runtime.open(url='https://example.test')
    runtime.start_recording(opened['session_id'])
    closed = runtime.close(opened['session_id'])

    assert closed['closed'] is True
    assert closed['recording']['format'] == 'gif'
    assert Path(closed['recording']['path']).exists()
