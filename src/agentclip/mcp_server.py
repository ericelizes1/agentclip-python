"""MCP server exposing agentclip tools to any agent runtime that speaks MCP.

This module is deliberately thin: every tool is a one-screen wrapper
that calls into the SDK and persists any returned credentials via the
state store. Real logic belongs in ``sdk.py`` so the CLI can mirror
the same behavior without duplication.

Run with::

    agentclip-mcp           # via the console script
    python -m agentclip.mcp_server   # equivalent

It speaks stdio MCP, the only transport every agent runtime supports
today. SSE/HTTP transports can come later if a deployment needs them.
"""

from __future__ import annotations

import asyncio
import atexit
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .sdk import AgentClipClient
from .state import StateStore

mcp = FastMCP('agentclip')
"""The single FastMCP instance for this server.

Imported by tests and by the ``agentclip-mcp`` console script. Tools are
registered at import time via the @mcp.tool decorators below, which
keeps the server definition self-contained in this one module.
"""


@mcp.tool()
def slideshow_create(
    title: Annotated[
        str | None,
        Field(
            description=(
                'Short headline for the slideshow, shown above the fold in '
                'the public viewer. Optional but recommended.'
            )
        ),
    ] = None,
    description: Annotated[
        str | None,
        Field(
            description=(
                'Longer "what was being tested" context — also read aloud '
                'as the spoken intro on the rendered video. Set this at '
                'the start of the run, before the first slide. Write it '
                'as 2-4 complete sentences, not telegraphic bullets.'
            )
        ),
    ] = None,
    run_type: Annotated[
        str | None,
        Field(
            description=(
                'What kind of clip this is — drives the narration voice + '
                'pacing across the whole rendered video. Pick from the '
                "user's trigger phrasing per SKILL.md: demo (showcase / "
                'recruiter — "demo this", "show this off", "what shipped"), '
                'qa (verification — "QA this", "smoke test", "regression"), '
                'guide (how-to / investigation — "how do I X", "explain", '
                '"compare", "investigate"), bug (repro — "reproduce", '
                '"what\'s broken"). Defaults to demo server-side if omitted. '
                '"walkthrough" is accepted as a deprecated synonym for demo.'
            )
        ),
    ] = None,
) -> dict:
    """Start a new slideshow. Returns the id, share URL, and write token.

    The write token is cached locally; subsequent tools (slideshow_add_slide,
    slideshow_update_slide, slideshow_set_summary) will pick it up
    automatically when given the returned slideshow id.
    """
    client = AgentClipClient()
    try:
        result = client.create_slideshow(
            title=title,
            description=description,
            run_type=run_type,
        )
    finally:
        client.close()

    StateStore().remember(
        result.id,
        write_token=result.write_token,
        share_url=result.share_url,
        title=title,
    )

    return {
        'id': result.id,
        'share_url': result.share_url,
        'write_token': result.write_token,
    }


@mcp.tool()
def slideshow_add_slide(
    slideshow_id: Annotated[
        str,
        Field(description='ID returned by slideshow_create.'),
    ],
    media_path: Annotated[
        str,
        Field(
            description=(
                'Absolute path on the local filesystem to the media file. '
                'Images: PNG, JPEG, GIF (animated GIFs render natively), WebP. '
                'Videos: MP4, WebM, MOV. Maximum 25MB. Save the file to disk '
                'before calling this tool.'
            )
        ),
    ],
    caption: Annotated[
        str,
        Field(
            description=(
                'One- or two-sentence caption. Active voice: action + '
                'expectation + result. See SKILL.md for examples.'
            )
        ),
    ],
) -> dict:
    """Append a media clip + caption as the next slide.

    Accepts both static images and short video clips. The backend
    classifies the upload by its Content-Type and the viewer renders
    image clips with <img> and video clips with <video>.
    """
    write_token = _resolve_token(slideshow_id)
    client = AgentClipClient()
    try:
        result = client.add_slide(
            slideshow_id,
            media_path=media_path,
            caption=caption,
            write_token=write_token,
        )
    finally:
        client.close()
    return result.model_dump()


@mcp.tool()
def slideshow_update_slide(
    slideshow_id: Annotated[
        str,
        Field(description='ID returned by slideshow_create.'),
    ],
    slide_position: Annotated[
        int,
        Field(description='1-based position of the slide to update.'),
    ],
    media_path: Annotated[
        str | None,
        Field(
            description=(
                'New media path (image or short video). Omit to leave the existing media in place.'
            )
        ),
    ] = None,
    caption: Annotated[
        str | None,
        Field(
            description='New caption. Omit to leave the existing caption in place.',
        ),
    ] = None,
) -> dict:
    """Replace the image and/or caption of an existing slide.

    Prefer this over piling up corrected slides; see SKILL.md.
    """
    write_token = _resolve_token(slideshow_id)
    client = AgentClipClient()
    try:
        result = client.update_slide(
            slideshow_id,
            slide_position,
            media_path=media_path,
            caption=caption,
            write_token=write_token,
        )
    finally:
        client.close()
    return result.model_dump()


@mcp.tool()
def slideshow_set_summary(
    slideshow_id: Annotated[
        str,
        Field(description='ID returned by slideshow_create.'),
    ],
    summary: Annotated[
        str,
        Field(
            description=(
                'TL;DR of the QA run. Aim for under 80 words: outcome, '
                'counts (passes/fails), bug list if any. Set near end of run.'
            )
        ),
    ],
) -> dict:
    """Set the slideshow summary. Call once near the end of the run."""
    write_token = _resolve_token(slideshow_id)
    client = AgentClipClient()
    try:
        result = client.set_summary(
            slideshow_id,
            summary=summary,
            write_token=write_token,
        )
    finally:
        client.close()
    return result.model_dump()


def _resolve_token(slideshow_id: str) -> str:
    """Look up the write_token for ``slideshow_id`` from the local state file.

    Surfaced as its own helper because every mutation tool needs the same
    "no token? give the user a real error" treatment, and the agent reads
    that error message verbatim, so it has to be useful, not a traceback.
    """
    token = StateStore().get_token(slideshow_id)
    if token is None:
        raise ValueError(
            f'no write_token cached locally for slideshow {slideshow_id!r}. '
            'Was this slideshow created on a different machine? '
            'Set AGENTCLIP_WRITE_TOKEN_<id> in env or use the CLI to import it.'
        )
    return token


# ---------------------------------------------------------------------------
# Browser tools
# ---------------------------------------------------------------------------
# Why these live in the same MCP server as the slideshow tools: the whole
# job of agentclip is "agent drives a browser, captures, narrates, ships."
# Forcing the agent to bring its own browser tooling breaks the dogfood
# loop (and historically led to OS-level screencapture leaks). Shipping
# viewport-only Playwright primitives as MCP tools makes the privacy
# boundary structural — the only screenshots an agent can take are
# tab-scoped PNGs that land on disk at a known path.
#
# Sessions are process-local: an MCP server runs for the lifetime of the
# agent's IDE session, so a dict in module scope is the right scope.
# Each session pins its own Playwright runtime + browser + context + page;
# closing the server (atexit) tears them down.
#
# Threading model: FastMCP runs tool handlers inside an asyncio loop, but
# Playwright's sync API actively refuses to coexist with one
# ("It looks like you are using Playwright Sync API inside the asyncio
# loop"). We resolve this by routing every browser_* call through a single
# dedicated worker thread. The thread has no event loop of its own, so
# sync_playwright works there; reusing the SAME thread across calls is
# critical because Playwright sync objects are thread-bound (a browser
# created in one thread can't be driven from another).

_BrowserSession = dict[str, Any]
_browser_sessions: dict[str, _BrowserSession] = {}
_DEFAULT_SHOT_DIR = Path('/tmp/agentclip-shots')

# max_workers=1 makes this effectively a serializer — all browser ops run
# in the same OS thread, in the order they're submitted. Cheap and exactly
# what Playwright's sync API needs.
_browser_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='agentclip-browser')


async def _run_in_browser_thread(func, *args, **kwargs):
    """Run a sync browser helper in the dedicated worker thread.

    All Playwright-touching work goes through this; the asyncio event
    loop stays free, the sync API doesn't see a competing loop, and
    Playwright objects all live in the same thread for their entire
    lifetime.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_browser_executor, lambda: func(*args, **kwargs))


def _require_playwright() -> Any:
    """Import Playwright. Playwright is a hard dependency since 0.5.0,
    so this should always succeed; the helper exists only to rewrite
    the unlikely import error into something an agent can act on (e.g.
    if a user installed agentclip with `--no-deps` and forgot)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            'Playwright is missing — agentclip ships it as a core '
            'dependency, so this usually means agentclip was installed '
            'with --no-deps or in a stale env. Run: '
            '`pip install --upgrade agentclip`'
        ) from exc
    return sync_playwright


def _ensure_chromium_installed(verbose: bool = True) -> None:
    """Make sure the Chromium binary Playwright needs is on disk.

    The Chromium download is ~200MB, so we don't ship it as a wheel —
    Playwright maintains its own per-browser binary cache under
    ``~/Library/Caches/ms-playwright`` (macOS) etc. Calling
    ``playwright install chromium`` is idempotent: it no-ops when the
    binary already exists, and downloads it (with a TTY progress bar)
    when it doesn't.

    Called at the start of ``browser_open`` so users hit the download
    once, on first browser-tool use, rather than during ``pip install``
    when they may not even need a browser. The ~1 minute of first-run
    latency is the price of a 200MB binary not bloating the wheel.
    """
    import subprocess
    import sys

    sync_playwright = _require_playwright()
    # Cheap probe: try to read the chromium executable path. Playwright
    # raises an Error if the browser isn't installed for the current
    # version — that's our trigger to install.
    try:
        with sync_playwright() as p:
            _ = p.chromium.executable_path
            # `executable_path` returns a string even when the binary
            # is missing (it's where the binary *would* be). Verify
            # it actually exists before declaring success.
            if Path(_).exists():
                return
    except Exception:
        # Any failure during probe → fall through to install.
        pass

    if verbose:
        print(
            'agentclip: Chromium not found, downloading via '
            '`playwright install chromium` (~200MB, one-time)…',
            file=sys.stderr,
        )
    # `playwright install` lives in the same env as the Python
    # interpreter that imported playwright; reach it via -m so we don't
    # depend on `playwright` being on PATH.
    subprocess.run(
        [sys.executable, '-m', 'playwright', 'install', 'chromium'],
        check=True,
    )


def _get_session(session_id: str) -> _BrowserSession:
    session = _browser_sessions.get(session_id)
    if session is None:
        raise ValueError(
            f'unknown browser session {session_id!r}. '
            "Open one with browser_open first; sessions don't survive a server restart."
        )
    return session


# --- sync implementations ---
# All the actual Playwright work happens here, in plain sync functions.
# Each is invoked through `_run_in_browser_thread` from the public async
# @mcp.tool wrappers below. Splitting like this lets the existing pytest
# suite keep calling the *_impl helpers directly (they're pure sync), while
# the FastMCP-facing functions stay async — the shape FastMCP requires.


_RECORDINGS_DIR = Path('/tmp/agentclip-recordings')


def _browser_open_impl(
    url: str,
    viewport_width: int,
    viewport_height: int,
    headless: bool,
    wait_until: str,
    record_video: bool = False,
) -> dict:
    _ensure_chromium_installed()
    sync_playwright = _require_playwright()
    pw_cm = sync_playwright()
    pw = pw_cm.start()
    browser = pw.chromium.launch(headless=headless)
    context_kwargs: dict[str, Any] = {
        'viewport': {'width': viewport_width, 'height': viewport_height},
    }
    if record_video:
        _RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        context_kwargs['record_video_dir'] = str(_RECORDINGS_DIR)
        context_kwargs['record_video_size'] = {'width': viewport_width, 'height': viewport_height}
    context = browser.new_context(**context_kwargs)
    page = context.new_page()
    page.goto(url, wait_until=wait_until)

    session_id = uuid.uuid4().hex[:12]
    _browser_sessions[session_id] = {
        'playwright_cm': pw_cm,
        'playwright': pw,
        'browser': browser,
        'context': context,
        'page': page,
        'record_video': record_video,
        'recording_active': record_video,
        'video_path': None,
    }
    return {
        'session_id': session_id,
        'url': page.url,
        'title': page.title(),
        'viewport': {'width': viewport_width, 'height': viewport_height},
        'recording_active': record_video,
    }


def _browser_navigate_impl(session_id: str, url: str, wait_until: str) -> dict:
    session = _get_session(session_id)
    session['page'].goto(url, wait_until=wait_until)
    return {'url': session['page'].url, 'title': session['page'].title()}


def _browser_type_impl(
    session_id: str,
    text: str,
    placeholder: str | None,
    selector: str | None,
    role: str | None,
    delay_ms: int,
) -> dict:
    session = _get_session(session_id)
    page = session['page']

    target = None
    if placeholder is not None:
        target = page.get_by_placeholder(placeholder).first
    elif selector is not None:
        target = page.locator(selector).first
    elif role is not None:
        target = page.get_by_role(role).first

    if target is not None:
        target.click()
        target.type(text, delay=delay_ms)
        try:
            box = target.bounding_box()
        except Exception:
            box = None
    else:
        page.keyboard.type(text, delay=delay_ms)
        box = None

    return {'typed_chars': len(text), 'target_box': box}


def _browser_click_impl(
    session_id: str,
    selector: str | None,
    text: str | None,
    role: str | None,
    name: str | None,
) -> dict:
    session = _get_session(session_id)
    page = session['page']

    if selector is not None:
        page.locator(selector).first.click()
    elif text is not None:
        page.get_by_text(text, exact=True).first.click()
    elif role is not None:
        if name:
            page.get_by_role(role, name=name).first.click()
        else:
            page.get_by_role(role).first.click()
    else:
        raise ValueError('browser_click needs one of: selector, text, or role.')

    return {'url': page.url, 'title': page.title()}


def _browser_press_key_impl(session_id: str, key: str) -> dict:
    session = _get_session(session_id)
    session['page'].keyboard.press(key)
    return {'pressed': key}


def _browser_wait_for_text_impl(
    session_id: str,
    text: str | list[str],
    timeout_ms: int,
) -> dict:
    session = _get_session(session_id)
    page = session['page']
    candidates = [text] if isinstance(text, str) else list(text)

    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        body = page.evaluate('document.body.innerText')
        for cand in candidates:
            if cand in body:
                waited = int((timeout_ms / 1000 - (deadline - time.time())) * 1000)
                return {'matched': cand, 'waited_ms': waited}
        time.sleep(0.5)
    raise TimeoutError(f'none of {candidates!r} appeared in page body within {timeout_ms}ms')


_ANNOTATION_OVERLAY_ID = '__agentclip_overlay__'

# JavaScript that paints an SVG overlay onto the page from a structured
# annotation list and returns a description of what landed. Runs inside
# the page context via page.evaluate(). Kept here as a single string so
# the Python side stays simple -- one inject, one screenshot, one remove.
_DRAW_ANNOTATIONS_JS = r"""
(({annotations, overlayId}) => {
  // Idempotent cleanup -- a previous screenshot's overlay may still be
  // hanging around if the prior call crashed before remove.
  const prev = document.getElementById(overlayId);
  if (prev) prev.remove();

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.id = overlayId;
  svg.style.cssText = (
    'position:fixed;top:0;left:0;width:100vw;height:100vh;' +
    'pointer-events:none;z-index:2147483647;'
  );
  svg.setAttribute('width', String(window.innerWidth));
  svg.setAttribute('height', String(window.innerHeight));
  svg.setAttribute('viewBox', `0 0 ${window.innerWidth} ${window.innerHeight}`);

  const defs = document.createElementNS(SVG_NS, 'defs');
  const arrowMarker = document.createElementNS(SVG_NS, 'marker');
  arrowMarker.setAttribute('id', `${overlayId}-arrowhead`);
  arrowMarker.setAttribute('viewBox', '0 0 10 10');
  arrowMarker.setAttribute('refX', '9');
  arrowMarker.setAttribute('refY', '5');
  arrowMarker.setAttribute('markerWidth', '7');
  arrowMarker.setAttribute('markerHeight', '7');
  arrowMarker.setAttribute('orient', 'auto-start-reverse');
  const arrowPath = document.createElementNS(SVG_NS, 'path');
  arrowPath.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
  arrowPath.setAttribute('fill', '#ff3b30');
  arrowMarker.appendChild(arrowPath);
  defs.appendChild(arrowMarker);
  svg.appendChild(defs);

  const placed = [];
  const failed = [];

  function rectFromTarget(target) {
    if (!target) return null;
    if (typeof target === 'string') {
      const el = document.querySelector(target);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.left, y: r.top, w: r.width, h: r.height };
    }
    if (typeof target === 'object' && 'x' in target && 'y' in target) {
      // Pixel-coordinate fallback. width/height optional -- treat as point.
      return {
        x: target.x,
        y: target.y,
        w: target.w ?? 0,
        h: target.h ?? 0,
      };
    }
    return null;
  }

  function makeLabel(text, x, y, color) {
    if (!text) return null;
    const padding = 8;
    const fontSize = 16;
    const charWidth = fontSize * 0.6;
    const textWidth = text.length * charWidth;
    const boxWidth = textWidth + padding * 2;
    const boxHeight = fontSize + padding * 2;
    const group = document.createElementNS(SVG_NS, 'g');
    const rect = document.createElementNS(SVG_NS, 'rect');
    rect.setAttribute('x', String(x));
    rect.setAttribute('y', String(y));
    rect.setAttribute('width', String(boxWidth));
    rect.setAttribute('height', String(boxHeight));
    rect.setAttribute('rx', '4');
    rect.setAttribute('fill', color);
    rect.setAttribute('fill-opacity', '0.95');
    group.appendChild(rect);
    const t = document.createElementNS(SVG_NS, 'text');
    t.setAttribute('x', String(x + padding));
    t.setAttribute('y', String(y + padding + fontSize - 2));
    t.setAttribute('fill', 'white');
    t.setAttribute('font-family', '-apple-system, system-ui, sans-serif');
    t.setAttribute('font-size', String(fontSize));
    t.setAttribute('font-weight', '600');
    t.textContent = text;
    group.appendChild(t);
    return { node: group, width: boxWidth, height: boxHeight };
  }

  for (let i = 0; i < annotations.length; i++) {
    const ann = annotations[i];
    const color = ann.color || '#ff3b30';
    const padding = ann.padding ?? 12;

    if (ann.type === 'circle' || ann.type === 'rect') {
      const rect = rectFromTarget(ann.target);
      if (!rect) {
        failed.push({ index: i, type: ann.type, reason: 'target not found' });
        continue;
      }
      if (ann.type === 'circle') {
        const cx = rect.x + rect.w / 2;
        const cy = rect.y + rect.h / 2;
        const r = Math.max(rect.w, rect.h) / 2 + padding;
        const circle = document.createElementNS(SVG_NS, 'circle');
        circle.setAttribute('cx', String(cx));
        circle.setAttribute('cy', String(cy));
        circle.setAttribute('r', String(r));
        circle.setAttribute('stroke', color);
        circle.setAttribute('stroke-width', '4');
        circle.setAttribute('fill', 'none');
        svg.appendChild(circle);
        if (ann.label) {
          const lbl = makeLabel(ann.label, cx - 80, cy + r + 8, color);
          if (lbl) svg.appendChild(lbl.node);
        }
        placed.push({ index: i, type: 'circle', cx, cy, r });
      } else {
        const r = document.createElementNS(SVG_NS, 'rect');
        const x = rect.x - padding;
        const y = rect.y - padding;
        const w = rect.w + padding * 2;
        const h = rect.h + padding * 2;
        r.setAttribute('x', String(x));
        r.setAttribute('y', String(y));
        r.setAttribute('width', String(w));
        r.setAttribute('height', String(h));
        r.setAttribute('rx', '6');
        r.setAttribute('stroke', color);
        r.setAttribute('stroke-width', '4');
        r.setAttribute('fill', color);
        r.setAttribute('fill-opacity', '0.12');
        svg.appendChild(r);
        if (ann.label) {
          const lbl = makeLabel(ann.label, x, y + h + 8, color);
          if (lbl) svg.appendChild(lbl.node);
        }
        placed.push({ index: i, type: 'rect', x, y, w, h });
      }
    } else if (ann.type === 'arrow') {
      const fromRect = rectFromTarget(ann.from ?? ann.target);
      const toRect = rectFromTarget(ann.to);
      if (!fromRect || !toRect) {
        failed.push({ index: i, type: 'arrow', reason: 'from or to not found' });
        continue;
      }
      const x1 = fromRect.x + fromRect.w / 2;
      const y1 = fromRect.y + fromRect.h / 2;
      const x2 = toRect.x + toRect.w / 2;
      const y2 = toRect.y + toRect.h / 2;
      const line = document.createElementNS(SVG_NS, 'line');
      line.setAttribute('x1', String(x1));
      line.setAttribute('y1', String(y1));
      line.setAttribute('x2', String(x2));
      line.setAttribute('y2', String(y2));
      line.setAttribute('stroke', color);
      line.setAttribute('stroke-width', '4');
      line.setAttribute('marker-end', `url(#${overlayId}-arrowhead)`);
      svg.appendChild(line);
      if (ann.label) {
        const midX = (x1 + x2) / 2;
        const midY = (y1 + y2) / 2;
        const lbl = makeLabel(ann.label, midX, midY, color);
        if (lbl) svg.appendChild(lbl.node);
      }
      placed.push({ index: i, type: 'arrow', x1, y1, x2, y2 });
    } else if (ann.type === 'label') {
      const rect = rectFromTarget(ann.target);
      if (!rect) {
        failed.push({ index: i, type: 'label', reason: 'target not found' });
        continue;
      }
      const lbl = makeLabel(
        ann.label || ann.text || '',
        rect.x + rect.w + 8,
        rect.y,
        color,
      );
      if (lbl) {
        svg.appendChild(lbl.node);
        placed.push({ index: i, type: 'label', x: rect.x + rect.w + 8, y: rect.y });
      } else {
        failed.push({ index: i, type: 'label', reason: 'empty label text' });
      }
    } else {
      failed.push({ index: i, type: ann.type, reason: 'unknown annotation type' });
    }
  }

  document.body.appendChild(svg);
  return { placed, failed };
})
"""


def _browser_screenshot_impl(
    session_id: str,
    out_path: str | None,
    full_page: bool,
    annotations: list[dict] | None = None,
) -> dict:
    session = _get_session(session_id)
    if out_path is None:
        _DEFAULT_SHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        out_path = str(_DEFAULT_SHOT_DIR / f'{session_id}-{ts}.png')

    page = session['page']
    annotation_result: dict[str, Any] | None = None
    if annotations:
        # Inject the overlay, screenshot with it visible, remove it. Any
        # failure to place a specific annotation (selector missed, target
        # off-screen) is surfaced in `failed[]` so the agent can decide
        # whether to retry with different selectors.
        annotation_result = page.evaluate(
            _DRAW_ANNOTATIONS_JS,
            {'annotations': annotations, 'overlayId': _ANNOTATION_OVERLAY_ID},
        )

    page.screenshot(path=out_path, full_page=full_page)

    if annotations:
        # Tear down the overlay so subsequent screenshots / interactions /
        # page.evaluate calls don't see it. The id is interpolated here so
        # the same Python constant drives both inject and remove.
        page.evaluate(
            '(overlayId) => { '
            'const el = document.getElementById(overlayId); '
            'if (el) el.remove(); '
            '}',
            _ANNOTATION_OVERLAY_ID,
        )

    size = Path(out_path).stat().st_size
    result: dict[str, Any] = {'path': out_path, 'bytes': size, 'full_page': full_page}
    if annotation_result is not None:
        result['annotations'] = annotation_result
    return result


def _browser_get_text_impl(session_id: str, selector: str | None) -> dict:
    session = _get_session(session_id)
    page = session['page']
    if selector is None:
        text = page.evaluate('document.body.innerText')
    else:
        text = page.locator(selector).first.inner_text()
    return {'text': text, 'url': page.url, 'title': page.title()}


def _browser_close_impl(session_id: str) -> dict:
    if session_id not in _browser_sessions:
        return {'closed': False, 'reason': 'session not found (already closed?)'}
    session = _browser_sessions[session_id]
    result: dict[str, Any] = {'closed': True}
    if session.get('record_video') and session.get('recording_active'):
        # Finalize the recording on close so the agent doesn't lose the
        # video if they forgot to call stop_recording.
        path = _finalize_recording(session_id)
        if path is not None:
            result['video_path'] = path
    _close_session(session_id)
    return result


def _browser_start_recording_impl(session_id: str) -> dict:
    """Mid-session start is not supported by Playwright -- recording must
    be enabled at context creation. If the session was opened with
    record_video=True, recording is already active and this is a no-op
    that returns confirmation. Otherwise, this raises with the remediation
    the agent should follow."""
    session = _get_session(session_id)
    if not session.get('record_video'):
        raise ValueError(
            f'session {session_id!r} was not opened with record_video=True. '
            'Playwright cannot start recording mid-session. Close this session '
            'and re-open with browser_open(url=..., record_video=True), then '
            'drive the flow. Use browser_stop_recording to finalize the video.'
        )
    if not session.get('recording_active'):
        raise ValueError(
            f'session {session_id!r} already had its recording finalized. '
            'Open a new session with record_video=True.'
        )
    return {'session_id': session_id, 'recording_active': True}


def _browser_stop_recording_impl(session_id: str) -> dict:
    """Finalize the recording. Closes the page+context (which is what
    Playwright requires to flush the WebM to disk), then returns the path.
    The session id is no longer usable after this -- open a new session
    if you need to keep driving the page."""
    session = _get_session(session_id)
    if not session.get('record_video'):
        raise ValueError(
            f'session {session_id!r} was not opened with record_video=True. '
            'Nothing to stop. Re-open the session with record_video=True next time.'
        )
    if not session.get('recording_active'):
        raise ValueError(
            f'session {session_id!r} already had its recording finalized. '
            'The video path was returned at that time.'
        )
    path = _finalize_recording(session_id)
    _close_session(session_id)
    if path is None:
        raise RuntimeError(
            f'recording finalize for {session_id!r} returned no path. '
            'The context may have closed before the video flushed; '
            're-run the flow with record_video=True.'
        )
    size = Path(path).stat().st_size if Path(path).exists() else 0
    return {
        'session_id': session_id,
        'path': path,
        'bytes': size,
        'format': 'webm',
    }


def _finalize_recording(session_id: str) -> str | None:
    """Flush the in-progress video to disk and return its path.

    Playwright writes the video when the *page* closes within a context
    that has record_video_dir set. We close the page to force the flush,
    then read page.video.path(). Returns None if anything fails -- callers
    treat the recording as lost in that case rather than blocking close."""
    session = _browser_sessions.get(session_id)
    if session is None:
        return None
    page = session.get('page')
    video = getattr(page, 'video', None) if page is not None else None
    if video is None:
        session['recording_active'] = False
        return None
    try:
        page.close()
    except Exception:  # noqa: BLE001 - cleanup best effort
        pass
    try:
        path = str(video.path())
    except Exception:  # noqa: BLE001 - cleanup best effort
        path = None
    session['recording_active'] = False
    session['video_path'] = path
    return path


def _browser_list_sessions_impl() -> dict:
    return {
        'sessions': [
            {
                'session_id': sid,
                'url': sess['page'].url,
                'title': sess['page'].title(),
            }
            for sid, sess in _browser_sessions.items()
        ]
    }


def _close_session(session_id: str) -> None:
    """Tear down a session's browser + Playwright runtime in order. Errors
    are swallowed because we may be running at process exit."""
    session = _browser_sessions.pop(session_id, None)
    if session is None:
        return
    for key in ('context', 'browser'):
        with suppress(Exception):
            session[key].close()
    with suppress(Exception):
        session['playwright_cm'].__exit__(None, None, None)


@atexit.register
def _close_all_sessions() -> None:
    # Best-effort. At interpreter shutdown the browser worker thread may
    # already be torn down and the asyncio loop is gone, so we accept that
    # some cleanup just doesn't happen — the OS will reap the chromium
    # subprocess regardless.
    for sid in list(_browser_sessions.keys()):
        with suppress(Exception):
            _close_session(sid)


# --- async @mcp.tool wrappers ---
# These are what FastMCP registers and what the MCP protocol calls. Each
# delegates to its sync impl through the dedicated browser worker thread
# (see _run_in_browser_thread). Keeping the async wrappers thin keeps the
# Playwright-vs-asyncio rule visible in one place: every line that touches
# Playwright runs in `_browser_executor`, never in the FastMCP loop.


@mcp.tool()
async def browser_open(
    url: Annotated[
        str,
        Field(description='URL to load in a new browser session.'),
    ],
    viewport_width: Annotated[
        int,
        Field(
            description=(
                'Viewport width in pixels. Default 1440 — common laptop '
                'size, matches v0 / Linear / Stripe target layouts.'
            ),
            ge=320,
            le=3840,
        ),
    ] = 1440,
    viewport_height: Annotated[
        int,
        Field(
            description='Viewport height in pixels. Default 900.',
            ge=240,
            le=2160,
        ),
    ] = 900,
    headless: Annotated[
        bool,
        Field(
            description=(
                'Run Chromium headless (default true). Set false to see '
                'the browser window — useful for interactive debugging '
                'on a desktop dev machine.'
            )
        ),
    ] = True,
    wait_until: Annotated[
        str,
        Field(
            description=(
                'When to consider the initial navigation complete: '
                '"load", "domcontentloaded", "networkidle", or "commit". '
                'Default "networkidle" — best for SPAs that finish '
                'rendering after the network goes quiet.'
            )
        ),
    ] = 'networkidle',
    record_video: Annotated[
        bool,
        Field(
            description=(
                'Record a viewport-only WebM video of the whole session. '
                'Pass true when motion is the story (animations, drag-and-drop, '
                'race conditions visible only in sequence). Playwright requires '
                'this be set at session open time -- you cannot start recording '
                'mid-session. Call browser_stop_recording to finalize and get '
                'the file path. Defaults to false (still PNGs only).'
            )
        ),
    ] = False,
) -> dict:
    """Open a new browser session at ``url``. Returns a session_id used by
    every other browser tool, plus the resolved final URL and page title.

    Sessions are viewport-only: screenshots taken from this session can
    only contain the browser tab, never the OS desktop. This is the
    structural reason to use these tools instead of OS screencapture.
    """
    return await _run_in_browser_thread(
        _browser_open_impl,
        url,
        viewport_width,
        viewport_height,
        headless,
        wait_until,
        record_video,
    )


@mcp.tool()
async def browser_start_recording(
    session_id: Annotated[str, Field(description='Session id from browser_open.')],
) -> dict:
    """Confirm a recording is in progress for this session.

    Playwright cannot start recording in an already-open session, so the
    real switch is the ``record_video=True`` flag on ``browser_open``. If
    that flag was set, this returns ``{recording_active: true}`` -- nothing
    further to do. If it wasn't, this raises a clear error explaining how
    to re-open the session correctly. Call ``browser_stop_recording`` to
    finalize the video and get the file path."""
    return await _run_in_browser_thread(_browser_start_recording_impl, session_id)


@mcp.tool()
async def browser_stop_recording(
    session_id: Annotated[str, Field(description='Session id from browser_open.')],
) -> dict:
    """Finalize the video for this session and return the path on disk.

    Pass the returned ``path`` to ``slideshow_add_slide`` as ``media_path``
    to attach the motion clip as a slide. After this call the session is
    closed -- open a new one if you need to keep driving. The video is a
    viewport-only WebM, same privacy guarantee as ``browser_screenshot``."""
    return await _run_in_browser_thread(_browser_stop_recording_impl, session_id)


@mcp.tool()
async def browser_navigate(
    session_id: Annotated[str, Field(description='Session id from browser_open.')],
    url: Annotated[str, Field(description='URL to navigate to.')],
    wait_until: Annotated[
        str,
        Field(description='Same options as browser_open. Default "networkidle".'),
    ] = 'networkidle',
) -> dict:
    """Navigate the existing session's tab to ``url``. Reuses the same
    viewport and browser context."""
    return await _run_in_browser_thread(
        _browser_navigate_impl,
        session_id,
        url,
        wait_until,
    )


@mcp.tool()
async def browser_type(
    session_id: Annotated[str, Field(description='Session id from browser_open.')],
    text: Annotated[str, Field(description='Text to type into the focused or located element.')],
    placeholder: Annotated[
        str | None,
        Field(
            description=(
                'Locate the target by its placeholder attribute (e.g. '
                "'Ask v0 to build…'). Most reliable selector for forms."
            )
        ),
    ] = None,
    selector: Annotated[
        str | None,
        Field(description='CSS selector for the target element. Used if placeholder is unset.'),
    ] = None,
    role: Annotated[
        str | None,
        Field(
            description=(
                'ARIA role of the target (e.g. "textbox", "searchbox"). '
                'Used if placeholder and selector are both unset.'
            )
        ),
    ] = None,
    delay_ms: Annotated[
        int,
        Field(description='Delay between keystrokes. 0 for paste-fast, 15-30 for human feel.'),
    ] = 15,
) -> dict:
    """Type ``text`` into the page. If ``placeholder``, ``selector``, or
    ``role`` is provided, focuses that element first; otherwise types
    into whatever currently has focus. Returns the located element's
    bounding box so the agent can verify it found the right thing."""
    return await _run_in_browser_thread(
        _browser_type_impl,
        session_id,
        text,
        placeholder,
        selector,
        role,
        delay_ms,
    )


@mcp.tool()
async def browser_click(
    session_id: Annotated[str, Field(description='Session id from browser_open.')],
    selector: Annotated[
        str | None,
        Field(description='CSS selector for the element to click.'),
    ] = None,
    text: Annotated[
        str | None,
        Field(
            description=(
                'Locate by visible text (exact match preferred). Used if selector is unset.'
            )
        ),
    ] = None,
    role: Annotated[
        str | None,
        Field(description='ARIA role (e.g. "button"). Used if both above are unset.'),
    ] = None,
    name: Annotated[
        str | None,
        Field(description='Accessible name to pair with role (e.g. role="button" name="Submit").'),
    ] = None,
) -> dict:
    """Click an element. Provide one of selector / text / role+name.
    Returns the page URL and title after the click in case it triggered
    a navigation."""
    return await _run_in_browser_thread(
        _browser_click_impl,
        session_id,
        selector,
        text,
        role,
        name,
    )


@mcp.tool()
async def browser_press_key(
    session_id: Annotated[str, Field(description='Session id from browser_open.')],
    key: Annotated[
        str,
        Field(
            description=(
                'Key name in Playwright format: "Enter", "Escape", "Tab", '
                '"ArrowDown", "Control+a", etc. See Playwright docs for the full list.'
            )
        ),
    ],
) -> dict:
    """Press a single key (or chord) on the focused element / page."""
    return await _run_in_browser_thread(_browser_press_key_impl, session_id, key)


@mcp.tool()
async def browser_wait_for_text(
    session_id: Annotated[str, Field(description='Session id from browser_open.')],
    text: Annotated[
        str | list[str],
        Field(
            description=(
                'Substring (or list of substrings) to wait for in the page body. '
                'Returns when ANY of them appears.'
            )
        ),
    ],
    timeout_ms: Annotated[
        int,
        Field(description='Max time to wait, in milliseconds.', ge=100, le=300_000),
    ] = 30_000,
) -> dict:
    """Poll the page body for a substring (or any of several). Useful
    for SPAs whose DOM ids/classes change build-to-build but whose
    user-visible text is stable.

    Returns which substring matched, or raises TimeoutError if none did
    in time. The agent should usually run a screenshot right after this
    returns successfully — that's the whole point of waiting."""
    return await _run_in_browser_thread(
        _browser_wait_for_text_impl,
        session_id,
        text,
        timeout_ms,
    )


@mcp.tool()
async def browser_screenshot(
    session_id: Annotated[str, Field(description='Session id from browser_open.')],
    out_path: Annotated[
        str | None,
        Field(
            description=(
                'Absolute path to write the PNG. If omitted, a path is '
                'generated under /tmp/agentclip-shots/ and returned.'
            )
        ),
    ] = None,
    full_page: Annotated[
        bool,
        Field(
            description=(
                'Capture the full scrollable page instead of just the '
                'viewport. Default false — viewport is the right default '
                'for clip slides; full_page is only useful for archival.'
            )
        ),
    ] = False,
    annotations: Annotated[
        list[dict] | None,
        Field(
            description=(
                'Optional list of annotations to bake into the screenshot. '
                'Each item is a dict: {"type": "circle"|"rect"|"arrow"|"label", '
                '"target": "<css selector>" or {"x": int, "y": int, "w": int?, "h": int?}, '
                '"label": "<optional text>", "color": "<optional hex, default #ff3b30>", '
                '"padding": <optional int, default 12>}. arrow uses "from" + "to" instead of '
                '"target". Direct attention to the specific element the slide caption is '
                'talking about — captions like "watch the X" should annotate X. The result '
                'dict reports placed/failed per annotation so you can recover from selector '
                'misses (e.g. element was off-screen) by retrying with a better selector.'
            )
        ),
    ] = None,
) -> dict:
    """Capture a viewport-scoped PNG and write it to disk. Returns the
    written path and byte size — agents pass the returned path straight
    into ``slideshow_add_slide`` as ``media_path``.

    With ``annotations``, an SVG overlay (circles/rectangles/arrows/labels
    tied to CSS selectors) is injected onto the page before capture and
    baked into the PNG — so it ships everywhere downstream (PDF, MP4
    frames, OG card, raw <img> paste) without any render-time work.

    Critically, this method only ever captures the browser viewport (or
    the full scrollable page); it can never capture the OS desktop, IDE
    windows, or other tabs. That structural property is why
    OS-screencapture leaks (which historically happened when agents
    fell back to ``screencapture -x``) are impossible here."""
    return await _run_in_browser_thread(
        _browser_screenshot_impl,
        session_id,
        out_path,
        full_page,
        annotations,
    )


@mcp.tool()
async def browser_get_text(
    session_id: Annotated[str, Field(description='Session id from browser_open.')],
    selector: Annotated[
        str | None,
        Field(
            description=(
                'CSS selector for the element to read. If omitted, returns the full body innerText.'
            )
        ),
    ] = None,
) -> dict:
    """Read text from the page. Useful for verifying a wait, extracting
    a URL the agent should navigate to next, or grabbing a generated
    artifact id from the rendered output."""
    return await _run_in_browser_thread(_browser_get_text_impl, session_id, selector)


@mcp.tool()
async def browser_close(
    session_id: Annotated[str, Field(description='Session id from browser_open.')],
) -> dict:
    """Close the session and free the Chromium process. Always call this
    when done; otherwise the browser leaks until the MCP server exits."""
    return await _run_in_browser_thread(_browser_close_impl, session_id)


@mcp.tool()
async def browser_list_sessions() -> dict:
    """List currently open browser sessions. Mainly for debugging when
    an agent loses track of a session_id mid-flow."""
    return await _run_in_browser_thread(_browser_list_sessions_impl)


def main() -> None:
    """Entry point for the ``agentclip-mcp`` console script."""
    mcp.run()


if __name__ == '__main__':
    main()
