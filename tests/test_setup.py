"""Unit tests for the lazy first-run setup module.

The integration test (test_setup_integration.py) covers the full
cold-start flow against a real tmp HOME. These tests pin individual
pieces in isolation so we can localize regressions.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agentclip import setup as setup_mod


@pytest.fixture
def marker(tmp_path: Path) -> Path:
    """Marker path inside a per-test tmp dir; never touches real $HOME."""
    return tmp_path / 'agentclip' / '.setup-complete'


@pytest.fixture
def skill_dir(tmp_path: Path) -> Path:
    return tmp_path / 'claude-skills'


# ---------- is_setup_complete ----------


def test_is_setup_complete_returns_false_when_marker_missing(marker: Path) -> None:
    assert setup_mod.is_setup_complete(marker_path=marker) is False


def test_is_setup_complete_returns_true_when_marker_exists(marker: Path) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('anything')
    assert setup_mod.is_setup_complete(marker_path=marker) is True


def test_is_setup_complete_honors_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AGENTCLIP_SETUP_MARKER lets CI / tests redirect without arg-passing."""
    override = tmp_path / 'override-marker'
    monkeypatch.setenv('AGENTCLIP_SETUP_MARKER', str(override))
    assert setup_mod.is_setup_complete() is False

    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text('done')
    assert setup_mod.is_setup_complete() is True


# ---------- write_marker ----------


def test_write_marker_creates_parent_dir_and_records_version(marker: Path) -> None:
    setup_mod.write_marker(marker_path=marker)
    body = json.loads(marker.read_text())
    assert 'version' in body
    assert 'completed_at' in body


# ---------- run_setup idempotence ----------


def test_run_setup_short_circuits_when_marker_exists(
    marker: Path, skill_dir: Path, monkeypatch
) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('done')
    monkeypatch.setenv('AGENTCLIP_MCP_CONFIG', str(skill_dir / 'mcp.json'))
    with patch.object(setup_mod, 'install_mcp_registration') as mock_mcp:
        ran = setup_mod.run_setup(marker_path=marker, skill_dir=skill_dir, quiet=True)
    assert ran is False
    mock_mcp.assert_not_called()


def test_run_setup_force_runs_even_with_marker(
    marker: Path, skill_dir: Path, monkeypatch
) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('done')
    monkeypatch.setenv('AGENTCLIP_MCP_CONFIG', str(skill_dir / 'mcp.json'))
    with patch.object(
        setup_mod, 'install_mcp_registration', return_value=(skill_dir, 'added')
    ) as mock_mcp:
        ran = setup_mod.run_setup(
            marker_path=marker,
            skill_dir=skill_dir,
            quiet=True,
            force=True,
        )
    assert ran is True
    mock_mcp.assert_called_once()


def test_run_setup_writes_marker_after_first_run(
    marker: Path, skill_dir: Path, monkeypatch
) -> None:
    monkeypatch.setenv('AGENTCLIP_MCP_CONFIG', str(skill_dir / 'mcp.json'))
    with patch.object(
        setup_mod, 'install_mcp_registration', return_value=(skill_dir, 'added')
    ):
        setup_mod.run_setup(marker_path=marker, skill_dir=skill_dir, quiet=True)
    assert marker.exists()
    body = json.loads(marker.read_text())
    assert body['version']


# ---------- skill installation ----------


def test_install_skill_writes_skill_md(skill_dir: Path) -> None:
    setup_mod._install_skill(quiet=True, skill_dir=skill_dir)
    dest = skill_dir / 'SKILL.md'
    assert dest.exists()
    assert dest.stat().st_size > 0


def test_install_skill_is_idempotent(skill_dir: Path) -> None:
    """Running twice must leave the file in the same state, not error."""
    setup_mod._install_skill(quiet=True, skill_dir=skill_dir)
    first = (skill_dir / 'SKILL.md').read_bytes()
    setup_mod._install_skill(quiet=True, skill_dir=skill_dir)
    second = (skill_dir / 'SKILL.md').read_bytes()
    assert first == second


# Browser/Chromium install moved out of setup in 0.5.0 — Chromium now
# downloads lazily on first browser_open call (see mcp_server.py). The
# previous suite of _install_playwright_chromium tests was removed
# alongside that function.

# ---------- ensure_setup (the lazy hot path) ----------


def test_ensure_setup_is_noop_when_marker_exists(marker: Path) -> None:
    """Hot path: a single Path.exists() and we're done."""
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('done')
    with patch.object(setup_mod, 'run_setup') as mock_run:
        setup_mod.ensure_setup(marker_path=marker)
    mock_run.assert_not_called()


def test_ensure_setup_runs_setup_when_marker_missing(marker: Path) -> None:
    with patch.object(setup_mod, 'run_setup') as mock_run:
        setup_mod.ensure_setup(marker_path=marker)
    mock_run.assert_called_once()
