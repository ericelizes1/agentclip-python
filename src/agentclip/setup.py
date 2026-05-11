"""Lazy first-run setup for the AgentClip CLI.

The first time `agentclip` runs (any subcommand), we:

1. Check for a marker file at ~/.agentclip/.setup-complete. If it exists,
   the CLI proceeds immediately — the entire check is a single `Path.exists()`
   call so the perf cost on subsequent invocations is negligible.

2. If the marker is missing, run setup once: install the bundled Claude Code
   skill into ~/.claude/skills/agentclip/, register the MCP server, install
   Playwright Chromium, and (when stdin is a TTY) prompt for a creator credit.
   Then write the marker so this never runs again.

The model is borrowed from Vite / Astro / Bun's first-run patterns —
`pip install agentclip` is the only step the user thinks about; setup
happens transparently when they actually invoke the CLI.

Tests that don't want real filesystem mutations override the marker
location via AGENTCLIP_SETUP_MARKER (or use the lower-level
`is_setup_complete()` / `run_setup()` API directly with `marker_path`).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from . import __version__


def default_marker_path() -> Path:
    """Resolve the setup-complete marker path, honoring the env override.

    Lives next to state.json so the entire AgentClip footprint on disk
    sits under one directory the user can wipe with a single rm.
    """
    override = os.environ.get('AGENTCLIP_SETUP_MARKER')
    if override:
        return Path(override).expanduser()
    return Path.home() / '.agentclip' / '.setup-complete'


def is_setup_complete(marker_path: Path | None = None) -> bool:
    """Fast path: a single file existence check.

    Designed to add < 1ms to subsequent `agentclip` invocations. We do
    NOT read or parse the marker contents; if the file is there at all,
    setup is considered complete. Re-running `agentclip setup --force`
    is the supported way to refresh.
    """
    return (marker_path or default_marker_path()).exists()


def write_marker(marker_path: Path | None = None) -> Path:
    """Stamp the setup-complete marker with version + timestamp.

    The contents aren't load-bearing for the existence check, but they
    help triage when a contributor reports "setup ran twice" by giving
    a human-readable record of when this machine was set up.
    """
    target = marker_path or default_marker_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                'version': __version__,
                'completed_at': datetime.now(UTC).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return target


def _install_skill(quiet: bool, skill_dir: Path | None = None) -> Path | None:
    """Copy the bundled SKILL.md into ~/.claude/skills/agentclip/SKILL.md.

    Idempotent: if the destination already exists with identical contents
    we report "already installed" and do nothing. If contents differ
    (e.g., the agentclip package was upgraded), we overwrite — the skill
    is a docs file, not a credential, so overwriting is safe.
    """
    target_dir = skill_dir or Path.home() / '.claude' / 'skills' / 'agentclip'
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / 'SKILL.md'

    skill_source = resources.files('agentclip.skill').joinpath('SKILL.md')
    with resources.as_file(skill_source) as src_path:
        new_bytes = src_path.read_bytes()
        if dest.exists() and dest.read_bytes() == new_bytes:
            if not quiet:
                print(f'  skill already installed at {dest}')
            return dest
        shutil.copyfile(src_path, dest)
    if not quiet:
        print(f'  skill installed: {dest}')
    return dest


_DEFAULT_MCP_CONFIG_PATH = Path.home() / '.claude' / 'mcp.json'
_MCP_SERVER_NAME = 'agentclip'
_MCP_SERVER_COMMAND = 'agentclip-mcp'


def default_mcp_config_path() -> Path:
    """Resolve the Claude Code MCP config path, honoring an env override."""
    override = os.environ.get('AGENTCLIP_MCP_CONFIG')
    if override:
        return Path(override).expanduser()
    return _DEFAULT_MCP_CONFIG_PATH


def _read_mcp_config(path: Path) -> dict:
    """Load the MCP config JSON, returning {} for missing or empty files."""
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Can't safely modify {path} — JSON parse failed at "
            f'line {exc.lineno}: {exc.msg}. Fix the file by hand or '
            f'delete it and re-run `agentclip install-mcp`.'
        ) from exc


def _install_playwright_chromium(quiet: bool) -> bool:
    """Run `playwright install chromium` for the built-in browser runtime."""
    if not quiet:
        print('  installing playwright chromium...')
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'playwright', 'install', 'chromium'],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        if not quiet:
            print(
                f'  playwright install failed: {exc}. '
                'Run `agentclip setup --force` or `python -m playwright install chromium` '
                'if you need the built-in browser.'
            )
        return False

    if result.returncode != 0:
        if not quiet:
            stderr_tail = (result.stderr or '').splitlines()[-3:]
            print(f'  playwright install exited {result.returncode}.')
            for line in stderr_tail:
                print(f'    {line}')
        return False

    if not quiet:
        print('  playwright chromium ready.')
    return True


def install_mcp_registration(
    *,
    config_path: Path | None = None,
    quiet: bool = False,
) -> tuple[Path, str]:
    """Add (or update) the agentclip entry in Claude Code's mcp.json."""
    target = config_path or default_mcp_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    config = _read_mcp_config(target)
    servers = config.setdefault('mcpServers', {})
    desired = {'command': _MCP_SERVER_COMMAND}

    existing = servers.get(_MCP_SERVER_NAME)
    if existing == desired:
        status = 'unchanged'
    elif existing is None:
        servers[_MCP_SERVER_NAME] = desired
        status = 'added'
    else:
        servers[_MCP_SERVER_NAME] = desired
        status = 'updated'

    target.write_text(json.dumps(config, indent=2, sort_keys=True) + '\n')

    if not quiet:
        if status == 'unchanged':
            print(f'  mcp registration already current at {target}')
        elif status == 'added':
            print(f'  registered MCP server in {target}')
        else:
            print(f'  updated MCP server entry in {target}')

    return target, status


def uninstall_mcp_registration(
    *,
    config_path: Path | None = None,
    quiet: bool = False,
) -> tuple[Path, str]:
    """Remove the agentclip entry from Claude Code's mcp.json."""
    target = config_path or default_mcp_config_path()
    if not target.exists():
        if not quiet:
            print(f'  no mcp config at {target} (nothing to uninstall)')
        return target, 'not_present'

    config = _read_mcp_config(target)
    servers = config.get('mcpServers', {})
    if _MCP_SERVER_NAME not in servers:
        if not quiet:
            print(f'  no agentclip entry in {target} (nothing to uninstall)')
        return target, 'not_present'

    del servers[_MCP_SERVER_NAME]
    target.write_text(json.dumps(config, indent=2, sort_keys=True) + '\n')
    if not quiet:
        print(f'  removed agentclip entry from {target}')
    return target, 'removed'


def run_setup(
    *,
    quiet: bool = False,
    force: bool = False,
    marker_path: Path | None = None,
    skill_dir: Path | None = None,
) -> bool:
    """Run the full first-run setup. Idempotent."""
    target = marker_path or default_marker_path()
    if not force and target.exists():
        if not quiet:
            print(f'agentclip: setup already complete ({target})')
        return False

    if not quiet:
        print('agentclip: first-run setup...')

    _install_skill(quiet=quiet, skill_dir=skill_dir)
    try:
        install_mcp_registration(quiet=quiet)
    except ValueError as exc:
        if not quiet:
            print(f'  mcp registration skipped: {exc}')
    _install_playwright_chromium(quiet=quiet)
    write_marker(marker_path=target)

    if not quiet:
        print('agentclip: setup complete.')
    return True


def ensure_setup(marker_path: Path | None = None) -> None:
    """Cheap fast-path used by the lazy callback."""
    if is_setup_complete(marker_path=marker_path):
        return
    run_setup(marker_path=marker_path)
