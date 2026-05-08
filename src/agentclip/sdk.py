"""Real implementation of the agentclip client surface.

The SDK is the source of truth. The CLI and MCP server are thin wrappers
on top; anything they can do, you can do by importing this module.

Design notes:
- Synchronous httpx, not async. Agent runtimes call us one tool at a time
  and pay the round-trip serially anyway. Async would buy nothing and
  complicate every call site.
- write_token is captured at create() and re-sent on every mutation. We
  do not stash it inside this object. The caller (CLI, MCP, library user)
  decides where to persist it. See state.py for the default.
- We never raise on 4xx without context. httpx's raise_for_status() loses
  the response body, which is exactly the part the user needs.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx

from ._models import SlideAdded, SlideshowCreated, SlideshowPatched, SlideUpdated
from .state import StateStore

DEFAULT_BASE_URL = 'https://api.agentclip.dev'
"""Public hosted backend. Override with AGENTCLIP_BASE_URL or base_url=.

This is the API origin (Django service), not the marketing site. The web
host (agentclip.dev) does not forward /api/* — POSTs hit Cloudflare's
trailing-slash 308 and lose the body, so the CLI must talk to the API
host directly.
"""


class AgentClipError(Exception):
    """Base class for SDK errors. Carries the HTTP response body when present."""

    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class AgentClipClient:
    """HTTP client for the agentclip backend.

    Typical usage::

        client = AgentClipClient()
        result = client.create_slideshow(title='Signup flow QA')
        # result.write_token is now the only way to mutate this slideshow

    The client is reusable across many slideshows. Resolve the base URL
    once; persist write_tokens however you like.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
        state_store: StateStore | None = None,
    ):
        resolved = base_url or os.environ.get('AGENTCLIP_BASE_URL') or DEFAULT_BASE_URL
        self.base_url = resolved.rstrip('/')
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)
        # state_store is the seam for whoami auto-application. The default
        # uses the real filesystem path; tests inject a stub pointed at
        # tmp_path so they never touch ~/.agentclip/.
        self._state = state_store if state_store is not None else StateStore()

    def __enter__(self) -> AgentClipClient:
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
        run_type: str | None = None,
        created_by: str | None = None,
        created_by_url: str | None = None,
    ) -> SlideshowCreated:
        """Create a new slideshow. Returns the id, share URL, and write token.

        The write token is the only credential that authorizes future
        mutations on this slideshow. Lose it and the slideshow is frozen.

        Creator credit (``created_by``, ``created_by_url``):
        - When passed explicitly, the call-site values win.
        - When not passed, the SDK reads ``StateStore.get_whoami()`` and
          fills both fields from there. This is how every clip an agent
          posts gets credited automatically once the user has run
          ``agentclip whoami --set ...`` once on their machine.
        - When neither is passed and no whoami is stored, the fields are
          omitted from the request body so the backend stores empty
          strings (not nulls).
        """
        payload: dict[str, Any] = {}
        if title is not None:
            payload['title'] = title
        if description is not None:
            payload['description'] = description
        if run_type is not None:
            payload['run_type'] = run_type

        # Auto-apply the local whoami credit when the caller didn't override.
        if created_by is None and created_by_url is None:
            stored = self._state.get_whoami()
            if stored is not None:
                created_by = stored['name']
                created_by_url = stored['url'] or None

        if created_by is not None:
            payload['created_by'] = created_by
        if created_by_url is not None:
            payload['created_by_url'] = created_by_url

        response = self._http.post(f'{self.base_url}/api/slideshow/', json=payload)
        return SlideshowCreated.model_validate(self._parse(response, expected=201))

    def add_slide(
        self,
        slideshow_id: str,
        *,
        media_path: str | os.PathLike[str],
        caption: str,
        write_token: str,
    ) -> SlideAdded:
        """Append a slide. The slide's ``position`` is assigned by the backend.

        Captions and images are uploaded together as one multipart request
        so a network failure cannot leave a slide with one and not the other.
        """
        image = _resolve_media(media_path)
        with image.open('rb') as fh:
            files = {'media': (image.name, fh, _guess_mime(image))}
            data = {'caption': caption}
            response = self._http.post(
                f'{self.base_url}/api/slideshow/{slideshow_id}/slides/',
                files=files,
                data=data,
                headers=_auth(write_token),
            )
        return SlideAdded.model_validate(self._parse(response, expected=201))

    def update_slide(
        self,
        slideshow_id: str,
        slide_position: int,
        *,
        media_path: str | os.PathLike[str] | None = None,
        caption: str | None = None,
        write_token: str,
    ) -> SlideUpdated:
        """Replace fields on an existing slide. Image, caption, or both.

        At least one of ``media_path`` and ``caption`` must be provided.
        A no-op PATCH would silently succeed and waste a round-trip.
        """
        if media_path is None and caption is None:
            raise AgentClipError('update_slide requires media_path and/or caption')

        url = f'{self.base_url}/api/slideshow/{slideshow_id}/slides/{slide_position}/'
        headers = _auth(write_token)
        data: dict[str, str] = {}
        if caption is not None:
            data['caption'] = caption

        if media_path is not None:
            image = _resolve_media(media_path)
            with image.open('rb') as fh:
                files = {'media': (image.name, fh, _guess_mime(image))}
                response = self._http.patch(url, files=files, data=data, headers=headers)
        else:
            # No image, no multipart needed. Simpler JSON keeps the request
            # debuggable in curl and matches Django's PATCH expectations.
            response = self._http.patch(url, json=data, headers=headers)

        return SlideUpdated.model_validate(self._parse(response, expected=200))

    def set_summary(
        self,
        slideshow_id: str,
        *,
        summary: str,
        write_token: str,
    ) -> SlideshowPatched:
        """Set the slideshow's TL;DR. Called near the end of an agent run.

        Title and description live on the same endpoint; if you ever need
        to mutate them, drop down to ``patch_slideshow``.
        """
        return self.patch_slideshow(slideshow_id, summary=summary, write_token=write_token)

    def patch_slideshow(
        self,
        slideshow_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        summary: str | None = None,
        write_token: str,
    ) -> SlideshowPatched:
        """Lower-level PATCH. ``set_summary`` is the named shortcut callers want."""
        payload: dict[str, str] = {}
        if title is not None:
            payload['title'] = title
        if description is not None:
            payload['description'] = description
        if summary is not None:
            payload['summary'] = summary
        if not payload:
            raise AgentClipError('patch_slideshow needs at least one field to update')

        response = self._http.patch(
            f'{self.base_url}/api/slideshow/{slideshow_id}/',
            json=payload,
            headers=_auth(write_token),
        )
        return SlideshowPatched.model_validate(self._parse(response, expected=200))

    def narrate_slideshow(
        self,
        share_token: str,
        *,
        write_token: str,
        voice: str | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> dict:
        """Generate or regenerate per-slide narration for a clip.

        Auth: Bearer <write_token>. Idempotent by default — slides
        with audio already set are skipped unless ``force=True``.
        ``dry_run=True`` reports estimated cost without calling
        OpenAI or writing to the database.

        Note: in normal use you don't need to call this. Hitting any
        clip's ``.mp4`` URL auto-narrates and renders. This method
        exists for force-regeneration cases (e.g. switching voices on
        an already-narrated clip).
        """
        body: dict[str, Any] = {}
        if voice is not None:
            body['voice'] = voice
        if force:
            body['force'] = True
        if dry_run:
            body['dry_run'] = True
        response = self._http.post(
            f'{self.base_url}/api/v1/slideshow/{share_token}/narrate/',
            json=body,
            headers=_auth(write_token),
        )
        return self._parse(response, expected=200)

    def feature_slideshow(
        self,
        share_token: str,
        *,
        position: int = 0,
        admin_token: str,
    ) -> None:
        """Add a slideshow to the curated home gallery.

        Auth: Bearer <AGENTCLIP_ADMIN_TOKEN>. The deploy must have the
        admin token set as an env var; without it the backend returns
        503 (fail-closed by design).

        ``position`` orders the gallery — lower sorts first; position 0
        is the home-page hero. Calling repeatedly with different
        positions is the supported way to reorder.
        """
        if position < 0:
            raise AgentClipError('position must be >= 0')
        response = self._http.post(
            f'{self.base_url}/api/v1/slideshow/{share_token}/feature/',
            json={'position': position},
            headers=_auth(admin_token),
        )
        if response.status_code != 200:
            raise AgentClipError(
                f'agentclip backend returned {response.status_code} (expected 200)',
                status_code=response.status_code,
                body=response.text,
            )

    def unfeature_slideshow(self, share_token: str, *, admin_token: str) -> None:
        """Drop a slideshow from the curated home gallery.

        Auth: Bearer <AGENTCLIP_ADMIN_TOKEN>. 204 on success; idempotent
        from the caller's view: a 404 is treated as 'already gone'.
        """
        response = self._http.delete(
            f'{self.base_url}/api/v1/slideshow/{share_token}/feature/',
            headers=_auth(admin_token),
        )
        if response.status_code in (204, 404):
            return
        raise AgentClipError(
            f'agentclip backend returned {response.status_code} (expected 204)',
            status_code=response.status_code,
            body=response.text,
        )

    def delete_slideshow(self, slideshow_id: str, *, write_token: str) -> None:
        """Delete a slideshow and all its slides. Auth: Bearer <write_token>.

        Idempotent from the caller's view: a 404 is treated as "already
        gone" and does not raise. Anything else surfaces as AgentClipError.
        Slide media in R2 is not cleaned up server-side (v0.1 limitation);
        the database row and its FK-cascaded slides are removed.
        """
        response = self._http.delete(
            f'{self.base_url}/api/slideshow/{slideshow_id}/',
            headers=_auth(write_token),
        )
        if response.status_code in (204, 404):
            return
        raise AgentClipError(
            f'agentclip backend returned {response.status_code} (expected 204)',
            status_code=response.status_code,
            body=response.text,
        )

    def _parse(self, response: httpx.Response, *, expected: int) -> dict[str, Any]:
        """Parse a JSON response and surface backend errors with their bodies.

        The hosted backend returns JSON error envelopes; we re-raise them
        as AgentClipError so callers can show the user something useful
        instead of a stripped-down "HTTP 400" with no detail.
        """
        if response.status_code != expected:
            raise AgentClipError(
                f'agentclip backend returned {response.status_code} (expected {expected})',
                status_code=response.status_code,
                body=response.text,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise AgentClipError(
                'agentclip backend returned non-JSON response',
                status_code=response.status_code,
                body=response.text,
            ) from exc


def _resolve_media(path: str | os.PathLike[str]) -> Path:
    """Validate a media path before we try to upload it.

    Failing at the SDK boundary gives a much better error than letting
    httpx blow up mid-multipart-stream. Accepts both image and video
    paths; the backend classifies by Content-Type at upload.
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise AgentClipError(f'media not found: {resolved}')
    if not resolved.is_file():
        raise AgentClipError(f'media path is not a file: {resolved}')
    return resolved


def _guess_mime(path: Path) -> str:
    """Best-effort MIME type for the multipart upload.

    Django + django-storages will sniff the body itself, so falling back
    to application/octet-stream is safe; we set a real type when we can
    so users see correct previews in places like image-aware logging.
    """
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or 'application/octet-stream'


def _auth(write_token: str) -> dict[str, str]:
    """Bearer-token header. Centralized so the format stays consistent."""
    return {'Authorization': f'Bearer {write_token}'}
