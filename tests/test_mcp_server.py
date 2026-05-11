from __future__ import annotations

from agentclip import mcp_server


class _FakeRuntime:
    def __init__(self):
        self.calls = []

    def open(self, **kwargs):
        self.calls.append(('open', kwargs))
        return {'session_id': 'br_test', **kwargs}

    def screenshot(self, session_id):
        self.calls.append(('screenshot', session_id))
        return {'session_id': session_id, 'path': '/tmp/shot.png', 'bytes': 123}

    def start_recording(self, session_id):
        self.calls.append(('start_recording', session_id))
        return {'session_id': session_id, 'recording_active': True}

    def stop_recording(self, session_id):
        self.calls.append(('stop_recording', session_id))
        return {
            'session_id': session_id,
            'path': '/tmp/clip.gif',
            'bytes': 456,
            'duration_ms': 1400,
        }

    def close(self, session_id):
        self.calls.append(('close', session_id))
        return {'session_id': session_id, 'closed': True}


def test_browser_tools_delegate_to_runtime(monkeypatch) -> None:
    runtime = _FakeRuntime()
    monkeypatch.setattr('agentclip.mcp_server.get_browser_runtime', lambda: runtime)

    opened = mcp_server.browser_open(
        'https://example.test',
        viewport_width=1280,
        viewport_height=720,
    )
    shot = mcp_server.browser_screenshot('br_test')
    started = mcp_server.browser_start_recording('br_test')
    stopped = mcp_server.browser_stop_recording('br_test')
    closed = mcp_server.browser_close('br_test')

    assert opened['session_id'] == 'br_test'
    assert shot['path'].endswith('.png')
    assert started['recording_active'] is True
    assert stopped['path'].endswith('.gif')
    assert closed['closed'] is True
    assert runtime.calls == [
        ('open', {'url': 'https://example.test', 'viewport_width': 1280, 'viewport_height': 720}),
        ('screenshot', 'br_test'),
        ('start_recording', 'br_test'),
        ('stop_recording', 'br_test'),
        ('close', 'br_test'),
    ]
