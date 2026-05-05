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


def main() -> None:
    '''Entry point for the ``qagent-mcp`` console script.'''
    mcp.run()


if __name__ == '__main__':
    main()
