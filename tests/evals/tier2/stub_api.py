"""Tiny stub of the agentclip backend API.

Stands in for ``api.agentclip.dev`` during Tier 2 evals so tests never
hit production. Records every request to an in-memory transcript so the
judge can inspect what the agent actually called and with what arguments.

Configurable failure injection per-test: set ``stub.fail_run_type`` to
return 400 on ``slideshow_create`` calls with that ``run_type``, etc.
Lets the eval validate fallback / retry behavior without coordinating
with the real backend.

Usage:
    server = StubAPI(host='127.0.0.1', port=0)
    server.start()
    # ... AGENTCLIP_API_URL=http://127.0.0.1:<server.port> claude -p ...
    transcript = server.transcript
    server.stop()
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


def _parse_multipart_minimal(raw: bytes, content_type: str) -> dict:
    """Pull text form-fields out of a multipart/form-data body.

    Doesn't try to be a full multipart parser — we only need the caption /
    title / summary text fields plus a recorded note for the file part.
    Anything we can't decode as text becomes ``{'_media_bytes': N}``.
    """
    # Boundary is in the Content-Type after `boundary=`.
    boundary = None
    for part in content_type.split(';'):
        part = part.strip()
        if part.startswith('boundary='):
            boundary = part.split('=', 1)[1].strip().strip('"')
            break
    if boundary is None:
        return {'_raw_len': len(raw)}
    sep = b'--' + boundary.encode()
    fields: dict[str, Any] = {}
    for chunk in raw.split(sep):
        if not chunk or chunk in (b'--', b'--\r\n'):
            continue
        # Strip leading \r\n if present.
        if chunk.startswith(b'\r\n'):
            chunk = chunk[2:]
        # Headers / body split.
        try:
            headers_blob, body = chunk.split(b'\r\n\r\n', 1)
        except ValueError:
            continue
        headers_text = headers_blob.decode('utf-8', errors='replace')
        # Find name + filename in Content-Disposition.
        name = None
        filename = None
        for line in headers_text.splitlines():
            if line.lower().startswith('content-disposition:'):
                for piece in line.split(';'):
                    piece = piece.strip()
                    if piece.startswith('name='):
                        name = piece.split('=', 1)[1].strip().strip('"')
                    elif piece.startswith('filename='):
                        filename = piece.split('=', 1)[1].strip().strip('"')
        if name is None:
            continue
        # Trim trailing \r\n.
        if body.endswith(b'\r\n'):
            body = body[:-2]
        if filename:
            # Binary file field — just record metadata.
            fields[name] = {'_filename': filename, '_bytes': len(body)}
        else:
            try:
                fields[name] = body.decode('utf-8')
            except UnicodeDecodeError:
                fields[name] = {'_bytes': len(body)}
    return fields


def _share_token() -> str:
    """Mirror the backend's share_token shape (~16 url-safe chars)."""
    return uuid.uuid4().hex[:16]


def _write_token() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex[:16]


def _edit_token() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex


class StubAPI:
    """In-process HTTP stub mimicking the agentclip backend.

    Stores all slideshows in a dict keyed by id, records every request
    to a transcript list. The HTTP handler is a closure over the running
    instance so each test gets isolated state.
    """

    def __init__(self, host: str = '127.0.0.1', port: int = 0):
        self._host = host
        self._port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.slideshows: dict[str, dict] = {}
        self.transcript: list[dict] = []
        # Failure-injection hooks. Each is checked at the relevant endpoint.
        self.fail_run_type: str | None = None  # 400 if slideshow_create gets this run_type
        self.fail_next_add_slide: bool = False  # one-shot 500 on the next add_slide
        self.fail_create_status: int | None = None  # forced status on the next create

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError('stub not started')
        return self._server.server_address[1]

    @property
    def base_url(self) -> str:
        return f'http://{self._host}:{self.port}'

    def start(self) -> None:
        handler = _make_handler(self)
        self._server = HTTPServer((self._host, self._port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        # Tiny wait to ensure the listening socket is ready before tests
        # fire off subprocess.run(claude ...) in another thread.
        time.sleep(0.05)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)


def _make_handler(stub: StubAPI):
    """Closure-bind ``stub`` into the BaseHTTPRequestHandler subclass."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args, **kwargs):
            # Silence per-request stderr noise; transcript captures everything.
            pass

        def _read_body(self) -> dict:
            length = int(self.headers.get('Content-Length') or 0)
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            content_type = (self.headers.get('Content-Type') or '').lower()
            # slideshow_add_slide / update_slide ship multipart/form-data
            # with the media PNG as a file field. Don't try to parse the
            # whole body -- pull out the text form fields we care about
            # (caption, title) and record media metadata only.
            if 'multipart/form-data' in content_type:
                return _parse_multipart_minimal(raw, content_type)
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {'_raw_len': len(raw)}

        def _json(self, status: int, payload: dict) -> None:
            # Record request + response together. The judge cross-references
            # the agent's reported share_url against the create response,
            # so the response payload must be in the transcript -- recording
            # only the request silently makes share_url_real unpassable.
            stub.transcript.append(
                {
                    'method': self.command,
                    'path': self.path,
                    'body': getattr(self, '_req_body', None),
                    'status': status,
                    'response': payload,
                    't': time.time(),
                }
            )
            data = json.dumps(payload).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802 — http.server signature
            body = self._read_body()
            self._req_body = body
            # ----- slideshow_create -----
            if self.path == '/api/slideshow/' or self.path == '/api/slideshow':
                run_type = body.get('run_type')
                if stub.fail_create_status:
                    status = stub.fail_create_status
                    stub.fail_create_status = None
                    return self._json(status, {'detail': 'forced failure'})
                if stub.fail_run_type and run_type == stub.fail_run_type:
                    return self._json(400, {'run_type': [f'"{run_type}" is not a valid choice.']})
                sid = uuid.uuid4().hex
                share = _share_token()
                slideshow = {
                    'id': sid,
                    'share_token': share,
                    'share_url': f'https://agentclip.dev/s/{share}/',
                    'write_token': _write_token(),
                    'edit_token': _edit_token(),
                    'title': body.get('title') or '',
                    'description': body.get('description') or '',
                    'run_type': run_type or 'demo',
                    'slides': [],
                    'summary': '',
                }
                stub.slideshows[sid] = slideshow
                return self._json(201, slideshow)
            # ----- slideshow_add_slide -----
            if self.path.startswith('/api/slideshow/') and self.path.endswith('/slides/'):
                sid = self.path.split('/')[3]
                if sid not in stub.slideshows:
                    return self._json(404, {'detail': 'not found'})
                if stub.fail_next_add_slide:
                    stub.fail_next_add_slide = False
                    return self._json(500, {'detail': 'forced failure'})
                # Slide ids are int in the SDK's pydantic model — return an
                # int, not a uuid hex string, or the SDK rejects with a
                # validation error and the agent thinks the call failed.
                # The first version of this stub got that wrong and tier 2
                # surfaced it as "agent retries forever, never progresses."
                slide_position = len(stub.slideshows[sid]['slides']) + 1
                slide_id = len(stub.slideshows) * 1000 + slide_position
                slide = {
                    'id': slide_id,
                    'position': slide_position,
                    'caption': body.get('caption') or '',
                    'media_url': f'{stub.base_url}/fake-media/{slide_id}.png',
                }
                stub.slideshows[sid]['slides'].append({**body, **slide})
                return self._json(201, slide)
            return self._json(404, {'detail': f'unrouted POST {self.path}'})

        def do_PATCH(self) -> None:  # noqa: N802
            body = self._read_body()
            self._req_body = body
            # ----- slideshow_set_summary / update -----
            if self.path.startswith('/api/slideshow/'):
                sid = self.path.rstrip('/').split('/')[-1]
                if sid not in stub.slideshows:
                    return self._json(404, {'detail': 'not found'})
                stub.slideshows[sid].update(
                    {k: v for k, v in body.items() if k in {'summary', 'title', 'description'}}
                )
                return self._json(200, stub.slideshows[sid])
            return self._json(404, {'detail': f'unrouted PATCH {self.path}'})

        def do_GET(self) -> None:  # noqa: N802
            self._req_body = None
            if self.path.startswith('/api/v1/slideshow/'):
                share = self.path.rstrip('/').split('/')[-1]
                for s in stub.slideshows.values():
                    if s['share_token'] == share:
                        return self._json(200, s)
                return self._json(404, {'detail': 'not found'})
            return self._json(200, {'ok': True})

    return _Handler


if __name__ == '__main__':
    # Tiny smoke runner for ad-hoc inspection: `python stub_api.py 8765`.
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    stub = StubAPI(port=port)
    stub.start()
    print(f'stub listening at {stub.base_url}; ctrl-c to stop')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stub.stop()
        print()
        print('transcript:')
        print(json.dumps(stub.transcript, indent=2))
