"""Lazy first-run setup for the AgentClip CLI.

The first time `agentclip` runs (any subcommand), we:

1. Check for a marker file at ~/.agentclip/.setup-complete. If it exists,
   the CLI proceeds immediately — the entire check is a single `Path.exists()`
   call so the perf cost on subsequent invocations is negligible.

2. If the marker is missing, run setup once: install the bundled skill into
   the supported agent runtimes (Claude Code, Codex, OpenCode), register the
   MCP server, install Playwright Chromium, and (when stdin is a TTY) prompt
   for a creator credit.
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
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from . import __version__

HostName = str
SUPPORTED_HOSTS: tuple[HostName, ...] = ('claude', 'codex', 'opencode')
_MCP_SERVER_NAME = 'agentclip'
_MCP_SERVER_COMMAND = 'agentclip-mcp'
_OPENCODE_SCHEMA = 'https://opencode.ai/config.json'


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


def default_skill_dir(host: HostName) -> Path:
    """Resolve the default skill directory for a supported host."""
    env_map = {
        'claude': 'AGENTCLIP_CLAUDE_SKILL_DIR',
        'codex': 'AGENTCLIP_CODEX_SKILL_DIR',
        'opencode': 'AGENTCLIP_OPENCODE_SKILL_DIR',
    }
    override = os.environ.get(env_map[host])
    if override:
        return Path(override).expanduser()

    defaults = {
        'claude': Path.home() / '.claude' / 'skills' / 'agentclip',
        'codex': Path.home() / '.codex' / 'skills' / 'agentclip',
        'opencode': Path.home() / '.config' / 'opencode' / 'skills' / 'agentclip',
    }
    return defaults[host]


def _install_skill_file(
    *,
    quiet: bool,
    target_dir: Path,
    host: HostName,
) -> Path | None:
    """Copy the bundled SKILL.md into the host's skill directory.

    Idempotent: if the destination already exists with identical contents
    we report "already installed" and do nothing. If contents differ
    (e.g., the agentclip package was upgraded), we overwrite — the skill
    is a docs file, not a credential, so overwriting is safe.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / 'SKILL.md'

    skill_source = resources.files('agentclip.skill').joinpath('SKILL.md')
    with resources.as_file(skill_source) as src_path:
        new_bytes = src_path.read_bytes()
        if dest.exists() and dest.read_bytes() == new_bytes:
            if not quiet:
                print(f'  {host}: skill already installed at {dest}')
            return dest
        shutil.copyfile(src_path, dest)
    if not quiet:
        print(f'  {host}: skill installed: {dest}')
    return dest


def install_skills(
    *,
    hosts: tuple[HostName, ...] = SUPPORTED_HOSTS,
    quiet: bool = False,
    skill_dir: Path | None = None,
) -> list[Path]:
    """Install the bundled skill for one or more supported hosts."""
    installed: list[Path] = []
    for host in hosts:
        target = skill_dir if skill_dir is not None and len(hosts) == 1 else default_skill_dir(host)
        dest = _install_skill_file(quiet=quiet, target_dir=target, host=host)
        if dest is not None:
            installed.append(dest)
    return installed


def default_mcp_config_path(host: HostName = 'claude') -> Path:
    """Resolve the MCP config path for a supported host."""
    legacy = os.environ.get('AGENTCLIP_MCP_CONFIG')
    if host == 'claude' and legacy:
        return Path(legacy).expanduser()

    env_map = {
        'claude': 'AGENTCLIP_CLAUDE_MCP_CONFIG',
        'codex': 'AGENTCLIP_CODEX_MCP_CONFIG',
        'opencode': 'AGENTCLIP_OPENCODE_MCP_CONFIG',
    }
    override = os.environ.get(env_map[host])
    if override:
        return Path(override).expanduser()

    defaults = {
        'claude': Path.home() / '.claude' / 'mcp.json',
        'codex': Path.home() / '.codex' / 'config.json',
        'opencode': Path.home() / '.config' / 'opencode' / 'opencode.json',
    }
    return defaults[host]


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


def _read_toml_config(path: Path) -> dict:
    """Load a TOML config file, returning {} for missing or empty files."""
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"Can't safely modify {path} — TOML parse failed: {exc}. "
            f'Fix the file by hand or delete it and re-run `agentclip install-mcp`.'
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


def _install_codex_json_registration(
    *,
    config_path: Path | None = None,
    quiet: bool = False,
) -> tuple[Path, str]:
    """Add (or update) the agentclip entry in Codex's config.json."""
    target = config_path or default_mcp_config_path('codex')
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
        print(f'  codex: mcp registration {status}: {target}')
    return target, status


def _codex_toml_config_path() -> Path:
    return Path.home() / '.codex' / 'config.toml'


def _install_codex_toml_registration(*, quiet: bool = False) -> tuple[Path, str]:
    """Add (or update) the agentclip entry in Codex's config.toml."""
    target = _codex_toml_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    config = _read_toml_config(target)
    existing = config.get('mcp_servers', {}).get(_MCP_SERVER_NAME)
    block = f'\n[mcp_servers.{_MCP_SERVER_NAME}]\ncommand = "{_MCP_SERVER_COMMAND}"\n'

    if existing == {'command': _MCP_SERVER_COMMAND}:
        status = 'unchanged'
        if not quiet:
            print(f'  codex: mcp registration unchanged: {target}')
        return target, status

    text = target.read_text() if target.exists() else ''
    section_re = re.compile(
        rf'(?ms)^\[mcp_servers\.{re.escape(_MCP_SERVER_NAME)}\]\n.*?(?=^\[|\Z)'
    )
    if existing is None:
        status = 'added'
        new_text = text.rstrip() + block + '\n' if text.strip() else block.lstrip()
    else:
        status = 'updated'
        replacement = f'[mcp_servers.{_MCP_SERVER_NAME}]\ncommand = "{_MCP_SERVER_COMMAND}"\n'
        if section_re.search(text):
            new_text = section_re.sub(replacement, text).rstrip() + '\n'
        else:
            new_text = text.rstrip() + block + '\n'

    target.write_text(new_text)
    if not quiet:
        print(f'  codex: mcp registration {status}: {target}')
    return target, status


def _install_opencode_mcp_registration(
    *,
    config_path: Path | None = None,
    quiet: bool = False,
) -> tuple[Path, str]:
    """Add (or update) the agentclip entry in OpenCode's opencode.json."""
    target = config_path or default_mcp_config_path('opencode')
    target.parent.mkdir(parents=True, exist_ok=True)

    config = _read_mcp_config(target)
    config.setdefault('$schema', _OPENCODE_SCHEMA)
    servers = config.setdefault('mcp', {})
    desired = {
        'type': 'local',
        'command': [_MCP_SERVER_COMMAND],
        'enabled': True,
    }

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
        print(f'  opencode: mcp registration {status}: {target}')
    return target, status


def install_host_mcp_registrations(
    *,
    hosts: tuple[HostName, ...] = SUPPORTED_HOSTS,
    quiet: bool = False,
    config_path: Path | None = None,
) -> list[tuple[HostName, Path, str]]:
    """Install MCP registrations for one or more supported hosts."""
    results: list[tuple[HostName, Path, str]] = []
    for host in hosts:
        if host == 'claude':
            path, status = install_mcp_registration(config_path=config_path, quiet=quiet)
            results.append((host, path, status))
            continue
        if host == 'codex':
            path, status = _install_codex_json_registration(config_path=config_path, quiet=quiet)
            results.append((host, path, status))
            # Codex in this environment also reads config.toml; keep it in sync
            # when present so a single install works across both config styles.
            toml_path, toml_status = _install_codex_toml_registration(quiet=quiet)
            results.append((host, toml_path, toml_status))
            continue
        if host == 'opencode':
            path, status = _install_opencode_mcp_registration(
                config_path=config_path, quiet=quiet
            )
            results.append((host, path, status))
            continue
        raise ValueError(f'unsupported host: {host}')
    return results


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


def _uninstall_codex_json_registration(
    *,
    config_path: Path | None = None,
    quiet: bool = False,
) -> tuple[Path, str]:
    target = config_path or default_mcp_config_path('codex')
    if not target.exists():
        return target, 'not_present'
    config = _read_mcp_config(target)
    servers = config.get('mcpServers', {})
    if _MCP_SERVER_NAME not in servers:
        return target, 'not_present'
    del servers[_MCP_SERVER_NAME]
    target.write_text(json.dumps(config, indent=2, sort_keys=True) + '\n')
    if not quiet:
        print(f'  codex: removed mcp entry from {target}')
    return target, 'removed'


def _uninstall_codex_toml_registration(*, quiet: bool = False) -> tuple[Path, str]:
    target = _codex_toml_config_path()
    if not target.exists():
        return target, 'not_present'
    _read_toml_config(target)
    text = target.read_text()
    section_re = re.compile(
        rf'(?ms)^\[mcp_servers\.{re.escape(_MCP_SERVER_NAME)}\]\n.*?(?=^\[|\Z)'
    )
    if not section_re.search(text):
        return target, 'not_present'
    new_text = section_re.sub('', text).strip()
    target.write_text(new_text + '\n' if new_text else '')
    if not quiet:
        print(f'  codex: removed mcp entry from {target}')
    return target, 'removed'


def _uninstall_opencode_mcp_registration(
    *,
    config_path: Path | None = None,
    quiet: bool = False,
) -> tuple[Path, str]:
    target = config_path or default_mcp_config_path('opencode')
    if not target.exists():
        return target, 'not_present'
    config = _read_mcp_config(target)
    servers = config.get('mcp', {})
    if _MCP_SERVER_NAME not in servers:
        return target, 'not_present'
    del servers[_MCP_SERVER_NAME]
    target.write_text(json.dumps(config, indent=2, sort_keys=True) + '\n')
    if not quiet:
        print(f'  opencode: removed mcp entry from {target}')
    return target, 'removed'


def uninstall_host_mcp_registrations(
    *,
    hosts: tuple[HostName, ...] = SUPPORTED_HOSTS,
    quiet: bool = False,
    config_path: Path | None = None,
) -> list[tuple[HostName, Path, str]]:
    """Remove MCP registrations for one or more supported hosts."""
    results: list[tuple[HostName, Path, str]] = []
    for host in hosts:
        if host == 'claude':
            path, status = uninstall_mcp_registration(config_path=config_path, quiet=quiet)
            results.append((host, path, status))
            continue
        if host == 'codex':
            path, status = _uninstall_codex_json_registration(
                config_path=config_path, quiet=quiet
            )
            results.append((host, path, status))
            toml_path, toml_status = _uninstall_codex_toml_registration(quiet=quiet)
            results.append((host, toml_path, toml_status))
            continue
        if host == 'opencode':
            path, status = _uninstall_opencode_mcp_registration(
                config_path=config_path, quiet=quiet
            )
            results.append((host, path, status))
            continue
        raise ValueError(f'unsupported host: {host}')
    return results


def run_setup(
    *,
    quiet: bool = False,
    force: bool = False,
    marker_path: Path | None = None,
    skill_dir: Path | None = None,
    hosts: tuple[HostName, ...] = SUPPORTED_HOSTS,
) -> bool:
    """Run the full first-run setup. Idempotent."""
    target = marker_path or default_marker_path()
    if not force and target.exists():
        if not quiet:
            print(f'agentclip: setup already complete ({target})')
        return False

    if not quiet:
        print('agentclip: first-run setup...')

    install_skills(quiet=quiet, skill_dir=skill_dir, hosts=hosts)
    try:
        install_host_mcp_registrations(quiet=quiet, hosts=hosts)
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
