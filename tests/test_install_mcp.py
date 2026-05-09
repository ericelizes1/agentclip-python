"""Tests for the auto-registration of the agentclip MCP server in
Claude Code's mcp.json. This is what makes ``pip install agentclip`` a
single-step setup instead of "now go find a JSON file" for every user.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentclip.cli import app
from agentclip.setup import install_mcp_registration, uninstall_mcp_registration

runner = CliRunner()


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


# --- install_mcp_registration ----------------------------------------------


def test_install_creates_file_when_missing(tmp_path):
    target = tmp_path / 'mcp.json'

    path, status = install_mcp_registration(config_path=target, quiet=True)

    assert path == target
    assert status == 'added'
    config = _read(target)
    assert config['mcpServers']['agentclip'] == {'command': 'agentclip-mcp'}


def test_install_preserves_other_servers(tmp_path):
    """Critical: a user with five other MCP servers registered must not
    lose any of them when we add ours."""
    target = tmp_path / 'mcp.json'
    target.write_text(
        json.dumps(
            {
                'mcpServers': {
                    'github': {'command': 'gh-mcp'},
                    'filesystem': {'command': 'fs-mcp', 'args': ['/tmp']},
                }
            }
        )
    )

    install_mcp_registration(config_path=target, quiet=True)

    config = _read(target)
    assert set(config['mcpServers'].keys()) == {'github', 'filesystem', 'agentclip'}
    assert config['mcpServers']['github'] == {'command': 'gh-mcp'}
    assert config['mcpServers']['filesystem'] == {'command': 'fs-mcp', 'args': ['/tmp']}


def test_install_is_idempotent(tmp_path):
    target = tmp_path / 'mcp.json'

    _, first = install_mcp_registration(config_path=target, quiet=True)
    _, second = install_mcp_registration(config_path=target, quiet=True)

    assert first == 'added'
    assert second == 'unchanged'


def test_install_updates_when_command_drifts(tmp_path):
    """If the user manually pointed agentclip at a stale path, our
    install should put it back to the canonical command."""
    target = tmp_path / 'mcp.json'
    target.write_text(
        json.dumps(
            {'mcpServers': {'agentclip': {'command': '/some/old/path/agentclip-mcp'}}}
        )
    )

    _, status = install_mcp_registration(config_path=target, quiet=True)

    assert status == 'updated'
    config = _read(target)
    assert config['mcpServers']['agentclip'] == {'command': 'agentclip-mcp'}


def test_install_creates_parent_directory(tmp_path):
    """~/.claude may not exist on a fresh machine — first install
    creates it."""
    target = tmp_path / 'fresh' / 'claude' / 'mcp.json'

    install_mcp_registration(config_path=target, quiet=True)

    assert target.exists()


def test_install_rejects_malformed_json(tmp_path):
    """Refuse to overwrite a config we can't parse — better to error
    loudly than to silently destroy the user's other entries."""
    target = tmp_path / 'mcp.json'
    target.write_text('{ this is not valid json')

    with pytest.raises(ValueError) as exc:
        install_mcp_registration(config_path=target, quiet=True)
    msg = str(exc.value)
    assert 'JSON parse failed' in msg
    assert 'agentclip install-mcp' in msg


def test_install_handles_empty_file(tmp_path):
    """Some setups leave an empty mcp.json. Treat it as missing."""
    target = tmp_path / 'mcp.json'
    target.touch()

    _, status = install_mcp_registration(config_path=target, quiet=True)

    assert status == 'added'


# --- uninstall_mcp_registration --------------------------------------------


def test_uninstall_removes_only_agentclip(tmp_path):
    target = tmp_path / 'mcp.json'
    target.write_text(
        json.dumps(
            {
                'mcpServers': {
                    'github': {'command': 'gh-mcp'},
                    'agentclip': {'command': 'agentclip-mcp'},
                }
            }
        )
    )

    _, status = uninstall_mcp_registration(config_path=target, quiet=True)

    assert status == 'removed'
    config = _read(target)
    assert 'agentclip' not in config['mcpServers']
    assert config['mcpServers']['github'] == {'command': 'gh-mcp'}


def test_uninstall_noop_when_file_missing(tmp_path):
    target = tmp_path / 'nope.json'
    _, status = uninstall_mcp_registration(config_path=target, quiet=True)
    assert status == 'not_present'


def test_uninstall_noop_when_entry_missing(tmp_path):
    target = tmp_path / 'mcp.json'
    target.write_text(json.dumps({'mcpServers': {'github': {'command': 'gh-mcp'}}}))

    _, status = uninstall_mcp_registration(config_path=target, quiet=True)

    assert status == 'not_present'
    # Other servers untouched
    assert _read(target)['mcpServers']['github'] == {'command': 'gh-mcp'}


# --- CLI surface -----------------------------------------------------------


def test_cli_install_mcp(tmp_path, monkeypatch):
    target = tmp_path / 'mcp.json'
    monkeypatch.setenv('AGENTCLIP_MCP_CONFIG', str(target))

    result = runner.invoke(app, ['install-mcp'])

    assert result.exit_code == 0, result.output
    assert 'added' in result.output
    assert 'restart Claude Code' in result.output
    config = _read(target)
    assert config['mcpServers']['agentclip']['command'] == 'agentclip-mcp'


def test_cli_install_mcp_idempotent(tmp_path, monkeypatch):
    target = tmp_path / 'mcp.json'
    monkeypatch.setenv('AGENTCLIP_MCP_CONFIG', str(target))

    runner.invoke(app, ['install-mcp'])
    second = runner.invoke(app, ['install-mcp'])

    assert second.exit_code == 0
    assert 'unchanged' in second.output
    # No "restart Claude Code" line on a no-op — agents read this output
    # and shouldn't be told to restart when nothing changed.
    assert 'restart Claude Code' not in second.output


def test_cli_uninstall_mcp(tmp_path, monkeypatch):
    target = tmp_path / 'mcp.json'
    monkeypatch.setenv('AGENTCLIP_MCP_CONFIG', str(target))
    runner.invoke(app, ['install-mcp'])

    result = runner.invoke(app, ['uninstall-mcp'])

    assert result.exit_code == 0
    assert 'removed' in result.output
    assert 'agentclip' not in _read(target)['mcpServers']


def test_cli_install_mcp_surfaces_parse_error(tmp_path, monkeypatch):
    target = tmp_path / 'mcp.json'
    target.write_text('{ broken')
    monkeypatch.setenv('AGENTCLIP_MCP_CONFIG', str(target))

    result = runner.invoke(app, ['install-mcp'])

    assert result.exit_code != 0
    assert 'JSON parse failed' in result.output


# --- run_setup integration -------------------------------------------------


def test_run_setup_registers_mcp(tmp_path, monkeypatch):
    """Pin that first-run setup actually wires up the MCP server, since
    that's the whole user-facing promise of this change — `pip install`
    should leave Claude Code one restart away from working."""
    from agentclip import setup as setup_mod

    marker = tmp_path / '.setup-complete'
    skill_dir = tmp_path / 'skills'
    mcp_config = tmp_path / 'mcp.json'
    monkeypatch.setenv('AGENTCLIP_MCP_CONFIG', str(mcp_config))

    setup_mod.run_setup(quiet=True, marker_path=marker, skill_dir=skill_dir)

    assert mcp_config.exists()
    assert _read(mcp_config)['mcpServers']['agentclip']['command'] == 'agentclip-mcp'
