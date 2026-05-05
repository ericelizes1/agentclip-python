'''The ``agentclip`` Typer CLI.

Mirrors the MCP tool surface for humans, CI, and any agent runtime
that doesn't speak MCP yet. Every command is a thin wrapper over
AgentClipClient (same logic, same error envelopes) so behavior never
diverges between an agent calling slideshow_create and a developer
running ``agentclip slideshow create``.

Two non-tool commands round it out:
- ``agentclip install-skill`` writes SKILL.md to ``~/.claude/skills/agentclip/``.
- ``agentclip slideshow list`` shows what's cached locally (tokens stay hidden).

Output goes to stdout as JSON when --json is passed, otherwise as a
short human-readable summary. Agents that want to parse output should
use --json explicitly; humans get the friendly path by default.
'''

from __future__ import annotations

import json
import shutil
import sys
from importlib import resources
from pathlib import Path

import typer

from . import __version__
from .sdk import AgentClipClient, AgentClipError
from .state import StateStore

app = typer.Typer(
    name='agentclip',
    help='Turn AI agent QA runs into shareable slideshows.',
    no_args_is_help=True,
    add_completion=False,
)
slideshow_app = typer.Typer(help='Create and manage slideshows.', no_args_is_help=True)
app.add_typer(slideshow_app, name='slideshow')


def _print(payload: dict, *, as_json: bool, summary: str | None = None) -> None:
    '''Single output path so --json behavior stays consistent across commands.'''
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    elif summary:
        typer.echo(summary)
    else:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _bail(message: str, *, body: str | None = None) -> 'typer.Exit':
    '''Print a real error to stderr and exit non-zero.

    Returned (not raised) so call sites read as ``raise _bail(...)``,
    a pattern that lets type-checkers see the control-flow exit.
    '''
    typer.echo(f'agentclip: {message}', err=True)
    if body:
        typer.echo(body, err=True)
    return typer.Exit(code=1)


# ---------- slideshow create ----------


@slideshow_app.command('create')
def slideshow_create(
    title: str | None = typer.Option(None, '--title', '-t', help='Optional title.'),
    description: str | None = typer.Option(
        None, '--description', '-d', help='Longer "what was being tested" context.'
    ),
    as_json: bool = typer.Option(False, '--json', help='Emit JSON instead of a summary.'),
) -> None:
    '''Create a new slideshow and cache its write_token locally.'''
    try:
        with AgentClipClient() as client:
            result = client.create_slideshow(title=title, description=description)
    except AgentClipError as exc:
        raise _bail(str(exc), body=exc.body) from exc

    StateStore().remember(
        result.id,
        write_token=result.write_token,
        share_url=result.share_url,
        title=title,
    )

    _print(
        result.model_dump(),
        as_json=as_json,
        summary=(
            f'created slideshow {result.id}\n'
            f'  share: {result.share_url}\n'
            f'  write_token cached in {StateStore().path}'
        ),
    )


# ---------- slideshow add ----------


@slideshow_app.command('add')
def slideshow_add(
    slideshow_id: str = typer.Argument(..., help='ID returned by `agentclip slideshow create`.'),
    image: Path = typer.Argument(..., exists=True, dir_okay=False, help='Path to screenshot.'),
    caption: str = typer.Option(..., '--caption', '-c', help='Caption for this slide.'),
    as_json: bool = typer.Option(False, '--json'),
) -> None:
    '''Append a slide to an existing slideshow.'''
    token = _require_token(slideshow_id)
    try:
        with AgentClipClient() as client:
            result = client.add_slide(
                slideshow_id, image_path=image, caption=caption, write_token=token
            )
    except AgentClipError as exc:
        raise _bail(str(exc), body=exc.body) from exc

    _print(
        result.model_dump(),
        as_json=as_json,
        summary=f'added slide #{result.position}: {result.caption}',
    )


# ---------- slideshow update ----------


@slideshow_app.command('update')
def slideshow_update(
    slideshow_id: str = typer.Argument(...),
    position: int = typer.Argument(..., help='1-based slide position to replace.'),
    image: Path | None = typer.Option(
        None, '--image', exists=True, dir_okay=False, help='New screenshot.'
    ),
    caption: str | None = typer.Option(None, '--caption', '-c', help='New caption.'),
    as_json: bool = typer.Option(False, '--json'),
) -> None:
    '''Replace the image and/or caption of an existing slide.'''
    if image is None and caption is None:
        raise _bail('pass --image, --caption, or both')

    token = _require_token(slideshow_id)
    try:
        with AgentClipClient() as client:
            result = client.update_slide(
                slideshow_id,
                position,
                image_path=image,
                caption=caption,
                write_token=token,
            )
    except AgentClipError as exc:
        raise _bail(str(exc), body=exc.body) from exc

    _print(
        result.model_dump(),
        as_json=as_json,
        summary=f'updated slide #{result.position}: {result.caption}',
    )


# ---------- slideshow summary ----------


@slideshow_app.command('summary')
def slideshow_summary(
    slideshow_id: str = typer.Argument(...),
    summary: str = typer.Argument(..., help='TL;DR of the QA run, under 80 words.'),
    as_json: bool = typer.Option(False, '--json'),
) -> None:
    '''Set the slideshow's summary near the end of an agent run.'''
    token = _require_token(slideshow_id)
    try:
        with AgentClipClient() as client:
            result = client.set_summary(slideshow_id, summary=summary, write_token=token)
    except AgentClipError as exc:
        raise _bail(str(exc), body=exc.body) from exc

    _print(result.model_dump(), as_json=as_json, summary='summary set.')


# ---------- slideshow list ----------


@slideshow_app.command('list')
def slideshow_list(
    as_json: bool = typer.Option(False, '--json'),
) -> None:
    '''List slideshows whose write_tokens are cached on this machine.'''
    entries = StateStore().all_slideshows()
    redacted = {
        sid: {k: v for k, v in entry.items() if k != 'write_token'}
        for sid, entry in entries.items()
    }
    if as_json:
        typer.echo(json.dumps(redacted, indent=2, sort_keys=True))
        return

    if not entries:
        typer.echo('no slideshows cached locally yet.')
        return

    for sid, entry in sorted(entries.items()):
        title = entry.get('title') or '(no title)'
        typer.echo(f'{sid}  {title}')
        typer.echo(f'  share: {entry.get("share_url")}')


# ---------- install-skill ----------


@app.command('install-skill')
def install_skill(
    target: Path = typer.Option(
        Path.home() / '.claude' / 'skills' / 'agentclip',
        '--target',
        help='Directory to install SKILL.md into. Defaults to ~/.claude/skills/agentclip.',
    ),
    force: bool = typer.Option(
        False, '--force', help='Overwrite an existing SKILL.md without prompting.'
    ),
) -> None:
    '''Install the bundled agentclip skill so agents pick up the prompt guidance.

    The skill is what makes generated slideshows actually good. It teaches
    the agent when to screenshot, how to caption, and how to write the
    summary. Reinstall after upgrading the package to pull in updates.
    '''
    skill_source = resources.files('agentclip.skill').joinpath('SKILL.md')
    if not skill_source.is_file():
        raise _bail('SKILL.md not bundled with this install. Open a github issue.')

    target.mkdir(parents=True, exist_ok=True)
    dest = target / 'SKILL.md'
    if dest.exists() and not force:
        raise _bail(f'{dest} already exists. Pass --force to overwrite.')

    with resources.as_file(skill_source) as src_path:
        shutil.copyfile(src_path, dest)
    typer.echo(f'installed skill to {dest}')


# ---------- version ----------


@app.command('version')
def version() -> None:
    '''Print the installed agentclip version.'''
    typer.echo(__version__)


def _require_token(slideshow_id: str) -> str:
    token = StateStore().get_token(slideshow_id)
    if token is None:
        raise _bail(
            f'no write_token cached for slideshow {slideshow_id!r}. '
            f'Was it created on this machine?'
        )
    return token


if __name__ == '__main__':
    sys.exit(app())
