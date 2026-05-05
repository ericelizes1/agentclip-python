'''MCP server exposing qagent tools to Claude Code, Cursor, and friends.

This module is deliberately thin: every tool is a one-screen wrapper
that calls into the SDK and persists any returned credentials via the
state store. Real logic belongs in ``sdk.py`` so the CLI can mirror
the same behavior without duplication.

Run with::

    qagent-mcp           # via the console script
    python -m qagent.mcp_server   # equivalent

It speaks stdio MCP — the only transport every agent runtime supports
today. SSE/HTTP transports can come later if a deployment needs them.
'''

from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .sdk import QAgentClient
from .state import StateStore

mcp = FastMCP('qagent')
'''The single FastMCP instance for this server.

Imported by tests and by the ``qagent-mcp`` console script. Tools are
registered at import time via the @mcp.tool decorators below, which
keeps the server definition self-contained in this one module.
'''


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
                'Longer "what was being tested" context. Set this at the '
                'start of the run, before the first slide.'
            )
        ),
    ] = None,
) -> dict:
    '''Start a new slideshow. Returns the id, share URL, and write token.

    The write token is cached locally; subsequent tools (slideshow_add_slide,
    slideshow_update_slide, slideshow_set_summary) will pick it up
    automatically when given the returned slideshow id.
    '''
    client = QAgentClient()
    try:
        result = client.create_slideshow(title=title, description=description)
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
    image_path: Annotated[
        str,
        Field(
            description=(
                'Absolute path on the local filesystem to the screenshot. '
                'PNG or JPEG. The agent should save the screenshot to disk '
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
    '''Append a screenshot + caption as the next slide in the slideshow.'''
    write_token = _resolve_token(slideshow_id)
    client = QAgentClient()
    try:
        result = client.add_slide(
            slideshow_id,
            image_path=image_path,
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
    image_path: Annotated[
        str | None,
        Field(
            description=(
                'New screenshot path. Omit to leave the existing image in place.'
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
    '''Replace the image and/or caption of an existing slide.

    Prefer this over piling up corrected slides — see SKILL.md.
    '''
    write_token = _resolve_token(slideshow_id)
    client = QAgentClient()
    try:
        result = client.update_slide(
            slideshow_id,
            slide_position,
            image_path=image_path,
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
    '''Set the slideshow summary. Call once near the end of the run.'''
    write_token = _resolve_token(slideshow_id)
    client = QAgentClient()
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
    '''Look up the write_token for ``slideshow_id`` from the local state file.

    Surfaced as its own helper because every mutation tool needs the same
    "no token? give the user a real error" treatment, and the agent reads
    that error message verbatim — so it has to be useful, not a traceback.
    '''
    token = StateStore().get_token(slideshow_id)
    if token is None:
        raise ValueError(
            f'no write_token cached locally for slideshow {slideshow_id!r}. '
            'Was this slideshow created on a different machine? '
            'Set QAGENT_WRITE_TOKEN_<id> in env or use the CLI to import it.'
        )
    return token


def main() -> None:
    '''Entry point for the ``qagent-mcp`` console script.'''
    mcp.run()


if __name__ == '__main__':
    main()
