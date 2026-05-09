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

from typing import Annotated

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
                "user's trigger phrasing per SKILL.md: walkthrough "
                '(feature reveal — "demo", "show this off", "what '
                'shipped"), guide (how-to — "how do I X", "tutorial"), '
                'bug (repro — "reproduce", "what\'s broken"). Defaults to '
                'walkthrough server-side if omitted.'
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

import atexit
import time
import uuid
from pathlib import Path
from typing import Any

_BrowserSession = dict[str, Any]
_browser_sessions: dict[str, _BrowserSession] = {}
_DEFAULT_SHOT_DIR = Path('/tmp/agentclip-shots')


def _require_playwright() -> Any:
    """Lazy-import Playwright so ``agentclip[browser]`` is only required
    when an agent actually invokes a browser tool. The import error gets
    rewritten into a message the agent can act on, because raw
    ``ModuleNotFoundError`` traces are hard to recover from."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Browser tools require Playwright. Install with: "
            "`pip install 'agentclip[browser]'` then "
            "`playwright install chromium`."
        ) from exc
    return sync_playwright


def _get_session(session_id: str) -> _BrowserSession:
    session = _browser_sessions.get(session_id)
    if session is None:
        raise ValueError(
            f"unknown browser session {session_id!r}. "
            "Open one with browser_open first; sessions don't survive a server restart."
        )
    return session


def _close_session(session_id: str) -> None:
    """Tear down a session's browser + Playwright runtime in order. Errors
    are swallowed because we may be running at process exit."""
    session = _browser_sessions.pop(session_id, None)
    if session is None:
        return
    for key in ('context', 'browser'):
        try:
            session[key].close()
        except Exception:
            pass
    try:
        session['playwright_cm'].__exit__(None, None, None)
    except Exception:
        pass


@atexit.register
def _close_all_sessions() -> None:
    for sid in list(_browser_sessions.keys()):
        _close_session(sid)


@mcp.tool()
def browser_open(
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
) -> dict:
    """Open a new browser session at ``url``. Returns a session_id used by
    every other browser tool, plus the resolved final URL and page title.

    Sessions are viewport-only: screenshots taken from this session can
    only contain the browser tab, never the OS desktop. This is the
    structural reason to use these tools instead of OS screencapture.
    """
    sync_playwright = _require_playwright()
    pw_cm = sync_playwright()
    pw = pw_cm.start()
    browser = pw.chromium.launch(headless=headless)
    context = browser.new_context(
        viewport={'width': viewport_width, 'height': viewport_height}
    )
    page = context.new_page()
    page.goto(url, wait_until=wait_until)

    session_id = uuid.uuid4().hex[:12]
    _browser_sessions[session_id] = {
        'playwright_cm': pw_cm,
        'playwright': pw,
        'browser': browser,
        'context': context,
        'page': page,
    }
    return {
        'session_id': session_id,
        'url': page.url,
        'title': page.title(),
        'viewport': {'width': viewport_width, 'height': viewport_height},
    }


@mcp.tool()
def browser_navigate(
    session_id: Annotated[str, Field(description='Session id from browser_open.')],
    url: Annotated[str, Field(description='URL to navigate to.')],
    wait_until: Annotated[
        str,
        Field(description='Same options as browser_open. Default "networkidle".'),
    ] = 'networkidle',
) -> dict:
    """Navigate the existing session's tab to ``url``. Reuses the same
    viewport and browser context."""
    session = _get_session(session_id)
    session['page'].goto(url, wait_until=wait_until)
    return {'url': session['page'].url, 'title': session['page'].title()}


@mcp.tool()
def browser_type(
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


@mcp.tool()
def browser_click(
    session_id: Annotated[str, Field(description='Session id from browser_open.')],
    selector: Annotated[
        str | None,
        Field(description='CSS selector for the element to click.'),
    ] = None,
    text: Annotated[
        str | None,
        Field(
            description=(
                'Locate by visible text (exact match preferred). '
                'Used if selector is unset.'
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
    session = _get_session(session_id)
    page = session['page']

    if selector is not None:
        page.locator(selector).first.click()
    elif text is not None:
        page.get_by_text(text, exact=True).first.click()
    elif role is not None:
        page.get_by_role(role, name=name).first.click() if name else page.get_by_role(role).first.click()
    else:
        raise ValueError("browser_click needs one of: selector, text, or role.")

    return {'url': page.url, 'title': page.title()}


@mcp.tool()
def browser_press_key(
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
    session = _get_session(session_id)
    session['page'].keyboard.press(key)
    return {'pressed': key}


@mcp.tool()
def browser_wait_for_text(
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
    session = _get_session(session_id)
    page = session['page']
    candidates = [text] if isinstance(text, str) else list(text)

    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        body = page.evaluate('document.body.innerText')
        for cand in candidates:
            if cand in body:
                return {'matched': cand, 'waited_ms': int((timeout_ms / 1000 - (deadline - time.time())) * 1000)}
        time.sleep(0.5)
    raise TimeoutError(
        f'none of {candidates!r} appeared in page body within {timeout_ms}ms'
    )


@mcp.tool()
def browser_screenshot(
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
) -> dict:
    """Capture a viewport-scoped PNG and write it to disk. Returns the
    written path and byte size — agents pass the returned path straight
    into ``slideshow_add_slide`` as ``media_path``.

    Critically, this method only ever captures the browser viewport (or
    the full scrollable page); it can never capture the OS desktop, IDE
    windows, or other tabs. That structural property is why
    OS-screencapture leaks (which historically happened when agents
    fell back to ``screencapture -x``) are impossible here."""
    session = _get_session(session_id)
    if out_path is None:
        _DEFAULT_SHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        out_path = str(_DEFAULT_SHOT_DIR / f'{session_id}-{ts}.png')

    session['page'].screenshot(path=out_path, full_page=full_page)
    size = Path(out_path).stat().st_size
    return {'path': out_path, 'bytes': size, 'full_page': full_page}


@mcp.tool()
def browser_get_text(
    session_id: Annotated[str, Field(description='Session id from browser_open.')],
    selector: Annotated[
        str | None,
        Field(
            description=(
                'CSS selector for the element to read. If omitted, '
                'returns the full body innerText.'
            )
        ),
    ] = None,
) -> dict:
    """Read text from the page. Useful for verifying a wait, extracting
    a URL the agent should navigate to next, or grabbing a generated
    artifact id from the rendered output."""
    session = _get_session(session_id)
    page = session['page']
    if selector is None:
        text = page.evaluate('document.body.innerText')
    else:
        text = page.locator(selector).first.inner_text()
    return {'text': text, 'url': page.url, 'title': page.title()}


@mcp.tool()
def browser_close(
    session_id: Annotated[str, Field(description='Session id from browser_open.')],
) -> dict:
    """Close the session and free the Chromium process. Always call this
    when done; otherwise the browser leaks until the MCP server exits."""
    if session_id not in _browser_sessions:
        return {'closed': False, 'reason': 'session not found (already closed?)'}
    _close_session(session_id)
    return {'closed': True}


@mcp.tool()
def browser_list_sessions() -> dict:
    """List currently open browser sessions. Mainly for debugging when
    an agent loses track of a session_id mid-flow."""
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


def main() -> None:
    """Entry point for the ``agentclip-mcp`` console script."""
    mcp.run()


if __name__ == '__main__':
    main()
