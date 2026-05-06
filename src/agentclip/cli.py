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
from .setup import ensure_setup, run_setup
from .state import StateStore

app = typer.Typer(
    name='agentclip',
    help='Turn AI agent QA runs into shareable slideshows.',
    no_args_is_help=True,
    add_completion=False,
)
slideshow_app = typer.Typer(help='Create and manage slideshows.', no_args_is_help=True)
app.add_typer(slideshow_app, name='slideshow')


# Subcommands that we explicitly do NOT want to trigger lazy first-run
# setup. `version` is a status query, `setup` runs setup itself, and
# `install-skill` is the manual fallback for the same step setup
# performs — running it nested would be confusing.
_SKIP_LAZY_SETUP = frozenset({'version', 'setup', 'install-skill'})


@app.callback()
def _lazy_first_run(ctx: typer.Context) -> None:
    '''Run lazy first-run setup before any subcommand executes.

    Typer dispatches the subcommand AFTER this callback returns, so
    inserting setup here means a fresh `pip install agentclip` followed
    by `agentclip slideshow create ...` does the right thing without an
    explicit setup step. Subsequent invocations are a single Path.exists()
    check.

    Skipped for status-only or setup-adjacent subcommands so they stay
    fast and never recurse on themselves.
    '''
    if ctx.invoked_subcommand in _SKIP_LAZY_SETUP:
        return
    ensure_setup()


def _print(payload: dict, *, as_json: bool, summary: str | None = None) -> None:
    '''Single output path so --json behavior stays consistent across commands.'''
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    elif summary:
        typer.echo(summary)
    else:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _bail(message: str, *, body: str | None = None) -> typer.Exit:
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

    store = StateStore()
    store.remember(
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
            f'  write_token cached in {store.path}'
        ),
    )

    # First-create nudge: fires once if no whoami is set, then never
    # again. The flag lives in state.json so it survives restarts.
    if store.get_whoami() is None and not store.get_flag('credit_nudge_shown'):
        if not as_json:
            typer.echo('')
            typer.echo("  tip: credit yourself on clips you make.")
            typer.echo("       agentclip whoami --set 'Your Name' --url https://you.example")
            typer.echo("       (this hint shows once; clear with `agentclip whoami --skip-tip`)")
        store.set_flag('credit_nudge_shown')


# ---------- slideshow add ----------


@slideshow_app.command('add')
def slideshow_add(
    slideshow_id: str = typer.Argument(..., help='ID returned by `agentclip slideshow create`.'),
    media: Path = typer.Argument(
        ..., exists=True, dir_okay=False,
        help='Path to image or video clip (PNG, JPEG, GIF, WebP, MP4, WebM, MOV).',
    ),
    caption: str = typer.Option(..., '--caption', '-c', help='Caption for this slide.'),
    as_json: bool = typer.Option(False, '--json'),
) -> None:
    '''Append a slide to an existing slideshow. Accepts image or video clip.'''
    token = _require_token(slideshow_id)
    try:
        with AgentClipClient() as client:
            result = client.add_slide(
                slideshow_id, media_path=media, caption=caption, write_token=token
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
    media: Path | None = typer.Option(
        None, '--media', '-m', exists=True, dir_okay=False,
        help='New media file (image or video).',
    ),
    caption: str | None = typer.Option(None, '--caption', '-c', help='New caption.'),
    as_json: bool = typer.Option(False, '--json'),
) -> None:
    '''Replace the media and/or caption of an existing slide.'''
    if media is None and caption is None:
        raise _bail('pass --media, --caption, or both')

    token = _require_token(slideshow_id)
    try:
        with AgentClipClient() as client:
            result = client.update_slide(
                slideshow_id,
                position,
                media_path=media,
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

    # Interactive whoami prompt: only fire when stdin is a TTY (so CI
    # and scripted use don't wedge on input). Skipped silently when
    # whoami is already set so a re-install does not re-prompt.
    store = StateStore()
    if sys.stdin.isatty() and store.get_whoami() is None:
        typer.echo('')
        typer.echo('optional: credit yourself on clips you create.')
        name = typer.prompt('  name (or press Enter to skip)', default='', show_default=False)
        if name.strip():
            url = typer.prompt('  url (or press Enter to skip)', default='', show_default=False)
            store.set_whoami(name.strip(), url.strip() or None)
            label = f'"{name.strip()}"'
            if url.strip():
                label += f' -> {url.strip()}'
            typer.echo(f'  saved. clips will display "Filed by {label}".')
            typer.echo("  change anytime: agentclip whoami --set '...' --url '...'")


# ---------- whoami ----------


@app.command('whoami')
def whoami(
    set_name: str | None = typer.Option(
        None, '--set', help='Set the creator credit name displayed on clips you make.'
    ),
    url: str | None = typer.Option(
        None, '--url', help='Optional URL the credit links to (portfolio, GitHub, LinkedIn).',
    ),
    clear: bool = typer.Option(
        False, '--clear', help='Remove the stored creator credit.'
    ),
    skip_tip: bool = typer.Option(
        False, '--skip-tip', help='Suppress the first-create credit nudge without setting a credit.',
    ),
) -> None:
    '''Manage the creator credit applied to every clip you create.

    Without flags: prints the stored credit (or "no credit set").
    With --set: stores the credit so every future slideshow_create
    auto-applies it. With --clear: removes the stored credit.
    With --skip-tip: marks the first-create nudge as shown.
    '''
    store = StateStore()

    if clear:
        store.clear_whoami()
        typer.echo('credit cleared.')
        return

    if skip_tip:
        store.set_flag('credit_nudge_shown')
        typer.echo('first-create nudge suppressed.')
        return

    if set_name is not None:
        if not set_name.strip():
            raise _bail('--set requires a non-empty name.')
        store.set_whoami(set_name.strip(), url.strip() if url else None)
        label = f'"{set_name.strip()}"'
        if url and url.strip():
            label += f' -> {url.strip()}'
        typer.echo(f'saved. clips will display "Filed by {label}".')
        return

    # No flags: print current credit.
    current = store.get_whoami()
    if current is None:
        typer.echo('no credit set.')
        typer.echo("  set with: agentclip whoami --set 'Your Name' --url https://you.example")
    else:
        line = f'name: {current["name"]}'
        if current['url']:
            line += f'\n url:  {current["url"]}'
        typer.echo(line)


# ---------- setup ----------


@app.command('setup')
def setup(
    force: bool = typer.Option(
        False, '--force', help='Re-run setup even if the marker exists.',
    ),
    quiet: bool = typer.Option(
        False, '--quiet', '-q', help='Suppress per-step status output.',
    ),
) -> None:
    '''Run first-run setup explicitly.

    Lazy first-run does this automatically the first time you invoke
    any other subcommand, so most users will never call this directly.
    Re-run with --force after upgrading the package to refresh the
    bundled skill or after changing browser extras.
    '''
    ran = run_setup(force=force, quiet=quiet)
    if not ran and not quiet:
        typer.echo('  (pass --force to re-run anyway.)')


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
