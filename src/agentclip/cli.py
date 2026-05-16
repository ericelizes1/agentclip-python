"""The ``agentclip`` Typer CLI.

Mirrors the MCP tool surface for humans, CI, and any agent runtime
that doesn't speak MCP yet. Every command is a thin wrapper over
AgentClipClient (same logic, same error envelopes) so behavior never
diverges between an agent calling slideshow_create and a developer
running ``agentclip slideshow create``.

Two non-tool commands round it out:
- ``agentclip install-skill`` writes SKILL.md to the supported host skill dirs.
- ``agentclip slideshow list`` shows what's cached locally (tokens stay hidden).

Output goes to stdout as JSON when --json is passed, otherwise as a
short human-readable summary. Agents that want to parse output should
use --json explicitly; humans get the friendly path by default.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from . import __version__
from .sdk import AgentClipClient, AgentClipError
from .setup import SUPPORTED_HOSTS, ensure_setup, run_setup
from .state import StateStore

app = typer.Typer(
    name='agentclip',
    help='Turn AI agent QA runs into shareable slideshows.',
    no_args_is_help=True,
    add_completion=False,
)
slideshow_app = typer.Typer(help='Create and manage slideshows.', no_args_is_help=True)
app.add_typer(slideshow_app, name='slideshow')
SLIDESHOW_MEDIA_ARGUMENT = typer.Argument(
    ...,
    exists=True,
    dir_okay=False,
    help='Path to image or video clip (PNG, JPEG, GIF, WebP, MP4, WebM, MOV).',
)
SLIDESHOW_UPDATE_MEDIA_OPTION = typer.Option(
    None,
    '--media',
    '-m',
    exists=True,
    dir_okay=False,
    help='New media file (image or video).',
)
INSTALL_SKILL_TARGET_OPTION = typer.Option(
    None,
    '--target',
    help='Directory to install SKILL.md into. Only valid with a single --host.',
)
INSTALL_MCP_CONFIG_OPTION = typer.Option(
    None,
    '--config',
    help=(
        'Path to the MCP config file. Only valid with a single --host. '
        'Claude also honors AGENTCLIP_MCP_CONFIG for backwards compatibility.'
    ),
)
UNINSTALL_MCP_CONFIG_OPTION = typer.Option(
    None,
    '--config',
    help='Path to the MCP config file. Defaults to ~/.claude.json for claude.',
)
HOSTS_OPTION = typer.Option(
    None,
    '--host',
    '-H',
    help='Target host runtime(s): claude, codex, opencode. Repeat to target multiple hosts.',
)

# Curation lives in its own namespace because it operates on a different
# resource (the home gallery) than slideshow CRUD does. Adding gallery
# verbs under `slideshow` would drift into a bag-of-everything subcommand.
gallery_app = typer.Typer(
    help='Manage which slideshows are featured on the home gallery.',
    no_args_is_help=True,
)
app.add_typer(gallery_app, name='gallery')

# Auth namespace caches the admin token to ~/.agentclip/state.json so
# gallery commands don't need --admin-token on every call. Same shape as
# `gh auth login`, `gcloud auth login`, `stripe login` — interactive
# prompt now, transparent reads from disk forever after.
auth_app = typer.Typer(
    help='Cache credentials so gallery commands run without re-pasting tokens.',
    no_args_is_help=True,
)
app.add_typer(auth_app, name='auth')


# Subcommands that we explicitly do NOT want to trigger lazy first-run
# setup. `version` is a status query, `setup` runs setup itself, and
# `install-skill` is the manual fallback for the same step setup
# performs — running it nested would be confusing.
_SKIP_LAZY_SETUP = frozenset({'version', 'setup', 'install-skill', 'install-mcp', 'uninstall-mcp'})


def _normalize_hosts(hosts: list[str] | None) -> tuple[str, ...]:
    if not hosts:
        return SUPPORTED_HOSTS

    normalized: list[str] = []
    for host in hosts:
        value = host.strip().lower()
        if value not in SUPPORTED_HOSTS:
            supported = ', '.join(SUPPORTED_HOSTS)
            raise _bail(f'unsupported host {host!r}. Expected one of: {supported}')
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def _single_host_override_error(flag: str) -> typer.Exit:
    return _bail(f'{flag} only works when exactly one --host is selected')


@app.callback()
def _lazy_first_run(ctx: typer.Context) -> None:
    """Run lazy first-run setup before any subcommand executes.

    Typer dispatches the subcommand AFTER this callback returns, so
    inserting setup here means a fresh `pip install agentclip` followed
    by `agentclip slideshow create ...` does the right thing without an
    explicit setup step. Subsequent invocations are a single Path.exists()
    check.

    Skipped for status-only or setup-adjacent subcommands so they stay
    fast and never recurse on themselves.
    """
    if ctx.invoked_subcommand in _SKIP_LAZY_SETUP:
        return
    ensure_setup()


def _print(payload: dict, *, as_json: bool, summary: str | None = None) -> None:
    """Single output path so --json behavior stays consistent across commands."""
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    elif summary:
        typer.echo(summary)
    else:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _artifact_lines(result) -> list[str]:
    """Render the optional clip artifact URLs as indented summary lines.

    The URLs resolve lazily — first fetch triggers the render — so
    printing them at create / summary time is fine even before the
    renders complete. Backwards compatible: an older API that doesn't
    surface these fields just returns nothing here.
    """
    lines: list[str] = []
    mp4 = getattr(result, 'clip_mp4_url', None)
    pdf = getattr(result, 'clip_pdf_url', None)
    embed = getattr(result, 'embed_url', None)
    if mp4:
        lines.append(f'  mp4:   {mp4}     # paste in GitHub PRs / READMEs')
    if pdf:
        lines.append(f'  pdf:   {pdf}     # download branded walkthrough')
    if embed:
        lines.append(f'  embed: {embed}     # iframe target for Notion / Substack')
    return lines


def _create_summary(result, *, store_path) -> str:
    body = [
        f'created clip {result.id}',
        f'  share: {result.share_url}',
        *_artifact_lines(result),
        f'  write_token cached in {store_path}',
    ]
    return '\n'.join(body)


def _bail(message: str, *, body: str | None = None) -> typer.Exit:
    """Print a real error to stderr and exit non-zero.

    Returned (not raised) so call sites read as ``raise _bail(...)``,
    a pattern that lets type-checkers see the control-flow exit.
    """
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
    run_type: str | None = typer.Option(
        None,
        '--type',
        '-T',
        help=(
            'Run type — drives the narration voice + pacing. One of: '
            'demo (showcase / feature reveal / recruiter clip), '
            'qa (smoke / regression / verification), '
            'guide (how-to / investigation / comparative analysis), or '
            'bug (repro / evidence). Defaults to demo. '
            '"walkthrough" is accepted as a deprecated synonym for demo.'
        ),
    ),
    as_json: bool = typer.Option(False, '--json', help='Emit JSON instead of a summary.'),
) -> None:
    """Create a new clip and cache its write_token locally."""
    try:
        with AgentClipClient() as client:
            result = client.create_slideshow(
                title=title,
                description=description,
                run_type=run_type,
            )
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
        summary=_create_summary(result, store_path=store.path),
    )

    # First-create nudge: fires once if no whoami is set, then never
    # again. The flag lives in state.json so it survives restarts.
    if store.get_whoami() is None and not store.get_flag('credit_nudge_shown'):
        if not as_json:
            typer.echo('')
            typer.echo('  tip: credit yourself on clips you make.')
            typer.echo("       agentclip whoami --set 'Your Name' --url https://you.example")
            typer.echo('       (this hint shows once; clear with `agentclip whoami --skip-tip`)')
        store.set_flag('credit_nudge_shown')


# ---------- slideshow add ----------


@slideshow_app.command('add')
def slideshow_add(
    slideshow_id: str = typer.Argument(..., help='ID returned by `agentclip slideshow create`.'),
    media: Path = SLIDESHOW_MEDIA_ARGUMENT,
    caption: str = typer.Option(..., '--caption', '-c', help='Caption for this slide.'),
    as_json: bool = typer.Option(False, '--json'),
) -> None:
    """Append a slide to an existing slideshow. Accepts image or video clip."""
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
    media: Path | None = SLIDESHOW_UPDATE_MEDIA_OPTION,
    caption: str | None = typer.Option(None, '--caption', '-c', help='New caption.'),
    as_json: bool = typer.Option(False, '--json'),
) -> None:
    """Replace the media and/or caption of an existing slide."""
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


# ---------- slideshow narrate ----------


def _share_token_from(slideshow_id_or_token: str) -> str:
    """Resolve a UUID slideshow_id to its share_token via cached state.

    The narrate API endpoint keys off ``share_token`` (the public,
    URL-safe component); other CLI commands key off the UUID
    ``slideshow_id``. This helper accepts either: a UUID is looked up
    in the local state store; anything else (including a real
    share_token) is returned unchanged.
    """
    import re

    is_uuid = bool(re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-', slideshow_id_or_token))
    if not is_uuid:
        return slideshow_id_or_token
    share_url = StateStore().get_share_url(slideshow_id_or_token)
    if not share_url:
        raise _bail(
            f'no cached share_url for {slideshow_id_or_token}; pass the share_token directly'
        )
    # Extract the token from a URL like https://agentclip.dev/s/<token>/
    parts = [p for p in share_url.rstrip('/').split('/') if p]
    return parts[-1]


@slideshow_app.command('narrate')
def slideshow_narrate(
    slideshow_id_or_token: str = typer.Argument(
        ..., help='Slideshow ID (UUID) or share_token (the URL slug).'
    ),
    voice: str | None = typer.Option(
        None,
        '--voice',
        '-v',
        help=(
            'Override the voice (alloy, echo, fable, onyx, nova, shimmer). '
            'Defaults to the run_type voice.'
        ),
    ),
    force: bool = typer.Option(
        False,
        '--force',
        '-f',
        help='Regenerate audio even on slides that already have it.',
    ),
    dry_run: bool = typer.Option(
        False,
        '--dry-run',
        help='Estimate cost without calling OpenAI or saving anything.',
    ),
    as_json: bool = typer.Option(False, '--json'),
) -> None:
    """Generate or regenerate narration for a clip.

    In normal use you don't need this — hitting any clip's `.mp4`
    URL auto-narrates and renders. Use `narrate` only to force a
    regeneration (e.g. trying a different voice) on a clip that
    already has audio.
    """
    share_token = _share_token_from(slideshow_id_or_token)
    # The endpoint authenticates via write_token, which the state
    # store caches under the original UUID id. If the caller passed a
    # share_token directly, we still need the UUID for token lookup —
    # bail with a friendly message in that case.
    import re

    if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-', slideshow_id_or_token):
        write_token = _require_token(slideshow_id_or_token)
    else:
        # Find the slideshow_id whose cached share_url contains this token.
        store = StateStore()
        match = next(
            (
                sid
                for sid, entry in store.all_slideshows().items()
                if (entry.get('share_url') or '').rstrip('/').endswith(f'/s/{share_token}')
            ),
            None,
        )
        if not match:
            raise _bail(
                f'no cached write_token for share_token {share_token}; '
                f'narrate requires the write_token, which is only available '
                f'on the machine that created the clip'
            )
        write_token = _require_token(match)

    try:
        with AgentClipClient() as client:
            result = client.narrate_slideshow(
                share_token,
                write_token=write_token,
                voice=voice,
                force=force,
                dry_run=dry_run,
            )
    except AgentClipError as exc:
        raise _bail(str(exc), body=exc.body) from exc

    narration = result.get('narration', {}) if isinstance(result, dict) else {}
    summary_text = (
        f'narrate: {narration.get("narrated", 0)} narrated, '
        f'{narration.get("skipped", 0)} skipped, '
        f'cost ~${narration.get("total_cost_usd", "0.00")}'
        f'{" (dry run)" if narration.get("dry_run") else ""}'
    )
    _print(narration or result, as_json=as_json, summary=summary_text)


# ---------- slideshow summary ----------


@slideshow_app.command('summary')
def slideshow_summary(
    slideshow_id: str = typer.Argument(...),
    summary: str = typer.Argument(..., help='TL;DR of the QA run, under 80 words.'),
    as_json: bool = typer.Option(False, '--json'),
) -> None:
    """Set the slideshow's summary near the end of an agent run."""
    token = _require_token(slideshow_id)
    try:
        with AgentClipClient() as client:
            result = client.set_summary(slideshow_id, summary=summary, write_token=token)
    except AgentClipError as exc:
        raise _bail(str(exc), body=exc.body) from exc

    # Echo the share + artifact URLs after setting summary — this is
    # the agent's "I'm done" moment, so the next thing the user does
    # is paste the link somewhere. Pre-warm has already enqueued the
    # render jobs server-side so the URLs are usually ready by the
    # time anyone clicks.
    share_url = StateStore().get_share_url(slideshow_id) or ''
    summary_lines = ['summary set.']
    if share_url:
        summary_lines.append(f'  share: {share_url}')
        summary_lines.append(
            f'  mp4:   {share_url.rstrip("/")}.mp4     # paste in GitHub PRs / READMEs'
        )
        summary_lines.append(
            f'  pdf:   {share_url.rstrip("/")}.pdf     # download branded walkthrough'
        )
    _print(result.model_dump(), as_json=as_json, summary='\n'.join(summary_lines))


# ---------- auth login / logout / status ----------


def _resolve_admin_token(flag: str | None) -> str | None:
    """Resolve admin token in priority order: flag > env > state file.

    The flag's typer envvar already covers the env-var case; this helper
    layers the state-file fallback on top so an `agentclip auth login`'d
    machine never needs --admin-token or AGENTCLIP_ADMIN_TOKEN again.
    """
    if flag:
        return flag
    return StateStore().get_admin_token()


@auth_app.command('login')
def auth_login(
    admin_token: str | None = typer.Option(
        None,
        '--admin-token',
        envvar='AGENTCLIP_ADMIN_TOKEN',
        help=(
            'Admin token to cache. When omitted, prompts interactively '
            'with hidden input so the value never appears on screen.'
        ),
    ),
) -> None:
    """Cache an admin token to ~/.agentclip/state.json.

    The cached token authorizes future `agentclip gallery add/remove`
    calls without --admin-token on every invocation. The state file is
    written with 0600 perms (owner read/write only).
    """
    token = admin_token
    if not token:
        token = typer.prompt('Paste admin token', hide_input=True).strip()
    if not token:
        raise _bail('admin token cannot be empty')

    store = StateStore()
    store.set_admin_token(token)
    typer.echo(f'admin token cached in {store.path} (perms 0600).')


@auth_app.command('logout')
def auth_logout() -> None:
    """Clear the cached admin token."""
    StateStore().clear_admin_token()
    typer.echo('admin token cleared.')


@auth_app.command('status')
def auth_status() -> None:
    """Show whether an admin token is currently cached (value masked)."""
    token = StateStore().get_admin_token()
    if not token:
        typer.echo('not logged in. Run `agentclip auth login` to cache an admin token.')
        return
    masked = token[:4] + '…' + token[-4:] if len(token) > 8 else '…'
    typer.echo(f'logged in. cached admin token: {masked}')


# ---------- gallery add / remove ----------


@gallery_app.command('add')
def gallery_add_cmd(
    share_token: str = typer.Argument(
        ...,
        help='URL-safe slug from a slideshow share URL (the part after /s/).',
    ),
    position: int = typer.Option(
        0,
        '--position',
        '-p',
        help='Gallery position; 0 is the home-page hero. Lower sorts first.',
    ),
    admin_token: str | None = typer.Option(
        None,
        '--admin-token',
        envvar='AGENTCLIP_ADMIN_TOKEN',
        help='Bearer token. Falls back to AGENTCLIP_ADMIN_TOKEN env var.',
    ),
    as_json: bool = typer.Option(False, '--json'),
) -> None:
    """Feature a slideshow in the curated home gallery.

    Requires the deployment's AGENTCLIP_ADMIN_TOKEN. Pass via the
    --admin-token flag or export AGENTCLIP_ADMIN_TOKEN in your shell.
    Position 0 lands the slideshow as the home-page hero.
    """
    admin_token = _resolve_admin_token(admin_token)
    if not admin_token:
        raise _bail(
            'no admin token. Run `agentclip auth login` once, '
            'pass --admin-token, or export AGENTCLIP_ADMIN_TOKEN.',
        )

    try:
        with AgentClipClient() as client:
            client.feature_slideshow(share_token, position=position, admin_token=admin_token)
    except AgentClipError as exc:
        raise _bail(str(exc), body=exc.body) from exc

    payload = {'share_token': share_token, 'position': position, 'is_gallery': True}
    _print(payload, as_json=as_json, summary=f'added to gallery at position {position}.')


@gallery_app.command('remove')
def gallery_remove_cmd(
    share_token: str = typer.Argument(...),
    admin_token: str | None = typer.Option(
        None,
        '--admin-token',
        envvar='AGENTCLIP_ADMIN_TOKEN',
        help='Bearer token. Falls back to AGENTCLIP_ADMIN_TOKEN env var.',
    ),
    as_json: bool = typer.Option(False, '--json'),
) -> None:
    """Drop a slideshow from the curated home gallery.

    The slideshow itself stays public at /s/<share_token>; only its
    home-page placement is removed. The featured_at audit timestamp
    is preserved so you can answer 'when was this last featured?'.
    """
    admin_token = _resolve_admin_token(admin_token)
    if not admin_token:
        raise _bail(
            'no admin token. Run `agentclip auth login` once, '
            'pass --admin-token, or export AGENTCLIP_ADMIN_TOKEN.',
        )

    try:
        with AgentClipClient() as client:
            client.unfeature_slideshow(share_token, admin_token=admin_token)
    except AgentClipError as exc:
        raise _bail(str(exc), body=exc.body) from exc

    _print(
        {'share_token': share_token, 'is_gallery': False},
        as_json=as_json,
        summary='removed from gallery.',
    )


# ---------- slideshow delete ----------


@slideshow_app.command('delete')
def slideshow_delete(
    slideshow_id: str = typer.Argument(...),
    yes: bool = typer.Option(
        False,
        '--yes',
        '-y',
        help='Skip the confirmation prompt.',
    ),
    as_json: bool = typer.Option(False, '--json'),
) -> None:
    """Delete a slideshow and all its slides. Cannot be undone."""
    token = _require_token(slideshow_id)
    if not yes and not typer.confirm(
        f'Delete slideshow {slideshow_id}? This cannot be undone.',
        default=False,
    ):
        typer.echo('aborted.')
        raise typer.Exit(code=1)

    try:
        with AgentClipClient() as client:
            client.delete_slideshow(slideshow_id, write_token=token)
    except AgentClipError as exc:
        raise _bail(str(exc), body=exc.body) from exc

    StateStore().forget_slideshow(slideshow_id)
    _print({'slideshow_id': slideshow_id, 'deleted': True}, as_json=as_json, summary='deleted.')


# ---------- slideshow list ----------


@slideshow_app.command('list')
def slideshow_list(
    as_json: bool = typer.Option(False, '--json'),
) -> None:
    """List slideshows whose write_tokens are cached on this machine."""
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
    target: Path | None = INSTALL_SKILL_TARGET_OPTION,
    hosts: list[str] | None = HOSTS_OPTION,
    force: bool = typer.Option(
        False, '--force', help='Overwrite an existing SKILL.md without prompting.'
    ),
) -> None:
    """Install the bundled agentclip skill so agents pick up the prompt guidance.

    The skill is what makes generated slideshows actually good. It teaches
    the agent when to screenshot, how to caption, and how to write the
    summary. Reinstall after upgrading the package to pull in updates.
    """
    from .setup import default_skill_dir, install_skills

    selected_hosts = _normalize_hosts(hosts)
    if target is not None and len(selected_hosts) != 1:
        raise _single_host_override_error('--target')

    if force and target is None:
        for host in selected_hosts:
            dest = default_skill_dir(host) / 'SKILL.md'
            if dest.exists():
                dest.unlink()

    if target is not None and force:
        dest = target / 'SKILL.md'
        if dest.exists():
            dest.unlink()

    installed = install_skills(
        hosts=selected_hosts,
        quiet=True,
        skill_dir=target,
    )
    for dest in installed:
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
            typer.echo(f'  saved. {label} will be credited on every clip.')
            typer.echo("  change anytime: agentclip whoami --set '...' --url '...'")


# ---------- install-mcp / uninstall-mcp ----------


@app.command('install-mcp')
def install_mcp(
    config: Path | None = INSTALL_MCP_CONFIG_OPTION,
    hosts: list[str] | None = HOSTS_OPTION,
) -> None:
    """Register the agentclip MCP server in supported host configs.

    Idempotent and safe — reads any existing mcp.json, adds (or updates)
    just the agentclip entry, and preserves every other server you have
    registered. Restart the target host after running this for the new
    tools to load.

    First-run setup runs this automatically, so most users never call it
    directly. Manual invocation is for re-running after you reset your
    config or moved the file.
    """
    from .setup import install_host_mcp_registrations

    selected_hosts = _normalize_hosts(hosts)
    if config is not None and len(selected_hosts) != 1:
        raise _single_host_override_error('--config')

    try:
        results = install_host_mcp_registrations(
            config_path=config,
            quiet=True,
            hosts=selected_hosts,
        )
    except ValueError as exc:
        raise _bail(str(exc)) from exc

    changed_hosts: set[str] = set()
    for host, path, status in results:
        typer.echo(f'{host}: mcp registration {status}: {path}')
        if status in {'added', 'updated'}:
            changed_hosts.add(host)
    if changed_hosts:
        typer.echo(f'  restart {", ".join(sorted(changed_hosts))} to load the new tools.')


@app.command('uninstall-mcp')
def uninstall_mcp(
    config: Path | None = UNINSTALL_MCP_CONFIG_OPTION,
    hosts: list[str] | None = HOSTS_OPTION,
) -> None:
    """Remove the agentclip MCP server from supported host configs.

    Other registered servers are preserved. No-op if the file or entry
    isn't present. Safe to run on a config that's never seen agentclip.
    """
    from .setup import uninstall_host_mcp_registrations

    selected_hosts = _normalize_hosts(hosts)
    if config is not None and len(selected_hosts) != 1:
        raise _single_host_override_error('--config')

    try:
        results = uninstall_host_mcp_registrations(
            config_path=config,
            quiet=True,
            hosts=selected_hosts,
        )
    except ValueError as exc:
        raise _bail(str(exc)) from exc

    removed_hosts: set[str] = set()
    for host, path, status in results:
        typer.echo(f'{host}: mcp registration {status}: {path}')
        if status == 'removed':
            removed_hosts.add(host)
    if removed_hosts:
        typer.echo(f'  restart {", ".join(sorted(removed_hosts))} to drop the tools.')


# ---------- whoami ----------


@app.command('whoami')
def whoami(
    set_name: str | None = typer.Option(
        None, '--set', help='Set the creator credit name displayed on clips you make.'
    ),
    url: str | None = typer.Option(
        None,
        '--url',
        help='Optional URL the credit links to (portfolio, GitHub, LinkedIn).',
    ),
    clear: bool = typer.Option(False, '--clear', help='Remove the stored creator credit.'),
    skip_tip: bool = typer.Option(
        False,
        '--skip-tip',
        help='Suppress the first-create credit nudge without setting a credit.',
    ),
) -> None:
    """Manage the creator credit applied to every clip you create.

    Without flags: prints the stored credit (or "no credit set").
    With --set: stores the credit so every future slideshow_create
    auto-applies it. With --clear: removes the stored credit.
    With --skip-tip: marks the first-create nudge as shown.
    """
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
        typer.echo(f'saved. {label} will be credited on every clip.')
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
        False,
        '--force',
        help='Re-run setup even if the marker exists.',
    ),
    quiet: bool = typer.Option(
        False,
        '--quiet',
        '-q',
        help='Suppress per-step status output.',
    ),
    hosts: list[str] | None = HOSTS_OPTION,
) -> None:
    """Run first-run setup explicitly.

    Lazy first-run does this automatically the first time you invoke
    any other subcommand, so most users will never call this directly.
    Re-run with --force after upgrading the package to refresh the
    bundled skill or repair the built-in browser runtime.
    """
    ran = run_setup(force=force, quiet=quiet, hosts=_normalize_hosts(hosts))
    if not ran and not quiet:
        typer.echo('  (pass --force to re-run anyway.)')


# ---------- version ----------


@app.command('version')
def version() -> None:
    """Print the installed agentclip version."""
    typer.echo(__version__)


@app.command('capture')
def capture(
    url: str = typer.Argument(..., help='URL to load.'),
    out: Path = typer.Option(
        ...,
        '--out',
        '-o',
        help='Output PNG path.',
        dir_okay=False,
    ),
    width: int = typer.Option(1440, '--width', help='Viewport width (default 1440).'),
    height: int = typer.Option(900, '--height', help='Viewport height (default 900).'),
    wait: str = typer.Option(
        'networkidle',
        '--wait',
        help='Playwright wait_until: load, domcontentloaded, networkidle, or commit.',
    ),
    full_page: bool = typer.Option(
        False,
        '--full-page',
        help='Capture the full scrollable page instead of just the viewport.',
    ),
    timeout_ms: int = typer.Option(
        20000,
        '--timeout-ms',
        help='Navigation timeout in milliseconds (default 20000).',
    ),
) -> None:
    """Capture a viewport-only PNG of a URL to disk.

    Same Playwright runtime the MCP browser tools use, exposed as a single
    one-shot command so an agent can produce a clip-ready screenshot
    without keeping a session open. The output is viewport-only -- never
    contains the IDE, terminal, or other tabs -- which is the privacy
    boundary AgentClip relies on. Pass the resulting path straight to
    ``agentclip slideshow add``.
    """
    # Lazy import so a missing playwright install doesn't break the CLI's
    # other subcommands -- only `capture` actually needs it.
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise _bail(
            'playwright is not installed. Run `pip install agentclip` or '
            '`agentclip setup --force` to install the bundled Chromium.'
        ) from exc

    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={'width': width, 'height': height})
                page = context.new_page()
                page.set_default_navigation_timeout(timeout_ms)
                page.goto(url, wait_until=wait)
                page.screenshot(path=str(out), full_page=full_page)
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - surface Playwright errors as CLI failures
        raise _bail(f'capture failed: {exc}') from exc

    size = out.stat().st_size
    typer.echo(f'wrote {out} ({size} bytes, {width}x{height})')


def _require_token(slideshow_id: str) -> str:
    token = StateStore().get_token(slideshow_id)
    if token is None:
        raise _bail(
            f'no write_token cached for slideshow {slideshow_id!r}. Was it created on this machine?'
        )
    return token


if __name__ == '__main__':
    sys.exit(app())
