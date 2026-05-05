'''Real implementation of the qagent client surface.

The SDK is the source of truth. The CLI and MCP server are thin wrappers
on top — anything they can do, you can do by importing this module.

Design notes:
- Synchronous httpx, not async. Agent runtimes call us one tool at a time
  and pay the round-trip serially anyway. Async would buy nothing and
  complicate every call site.
- write_token is captured at create() and re-sent on every mutation. We
  do not stash it inside this object — the caller (CLI, MCP, library
  user) decides where to persist it. See state.py for the default.
- We never raise on 4xx without context. httpx's raise_for_status() loses
  the response body, which is exactly the part the user needs.
'''

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from ._models import SlideshowCreated

DEFAULT_BASE_URL = 'https://qagent.app'
'''Public hosted backend. Override with QAGENT_BASE_URL or base_url=.'''


class QAgentError(Exception):
    '''Base class for SDK errors. Carries the HTTP response body when present.'''

    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class QAgentClient:
    '''HTTP client for the qagent backend.

    Typical usage::

        client = QAgentClient()
        result = client.create_slideshow(title='Signup flow QA')
        # result.write_token is now the only way to mutate this slideshow

    The client is reusable across many slideshows. Resolve the base URL
    once; persist write_tokens however you like.
    '''

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ):
        resolved = base_url or os.environ.get('QAGENT_BASE_URL') or DEFAULT_BASE_URL
        self.base_url = resolved.rstrip('/')
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)

    def __enter__(self) -> 'QAgentClient':
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def create_slideshow(
        self,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> SlideshowCreated:
        '''Create a new slideshow. Returns the id, share URL, and write token.

        The write token is the only credential that authorizes future
        mutations on this slideshow. Lose it and the slideshow is frozen.
        '''
        payload: dict[str, Any] = {}
        if title is not None:
            payload['title'] = title
        if description is not None:
            payload['description'] = description

        response = self._http.post(f'{self.base_url}/api/slideshow/', json=payload)
        return SlideshowCreated.model_validate(self._parse(response, expected=201))

    def _parse(self, response: httpx.Response, *, expected: int) -> dict[str, Any]:
        '''Parse a JSON response and surface backend errors with their bodies.

        The hosted backend returns JSON error envelopes; we re-raise them
        as QAgentError so callers can show the user something useful
        instead of a stripped-down "HTTP 400" with no detail.
        '''
        if response.status_code != expected:
            raise QAgentError(
                f'qagent backend returned {response.status_code} (expected {expected})',
                status_code=response.status_code,
                body=response.text,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise QAgentError(
                'qagent backend returned non-JSON response',
                status_code=response.status_code,
                body=response.text,
            ) from exc


def _resolve_image(path: str | os.PathLike[str]) -> Path:
    '''Validate an image path before we try to upload it.

    Failing at the SDK boundary gives a much better error than letting
    httpx blow up mid-multipart-stream.
    '''
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise QAgentError(f'image not found: {resolved}')
    if not resolved.is_file():
        raise QAgentError(f'image path is not a file: {resolved}')
    return resolved
