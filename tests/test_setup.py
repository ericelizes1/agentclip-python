'''Unit tests for the lazy first-run setup module.

The integration test (test_setup_integration.py) covers the full
cold-start flow against a real tmp HOME. These tests pin individual
pieces in isolation so we can localize regressions.
'''

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agentclip import setup as setup_mod


@pytest.fixture
def marker(tmp_path: Path) -> Path:
    '''Marker path inside a per-test tmp dir; never touches real $HOME.'''
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    '''AGENTCLIP_SETUP_MARKER lets CI / tests redirect without arg-passing.'''
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


def test_run_setup_short_circuits_when_marker_exists(marker: Path, skill_dir: Path) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('done')
    with patch.object(setup_mod, '_install_playwright_chromium') as mock_browser:
        ran = setup_mod.run_setup(marker_path=marker, skill_dir=skill_dir, quiet=True)
    assert ran is False
    mock_browser.assert_not_called()


def test_run_setup_force_runs_even_with_marker(marker: Path, skill_dir: Path) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('done')
    with patch.object(setup_mod, '_install_playwright_chromium', return_value=True) as mock_browser:
        ran = setup_mod.run_setup(
            marker_path=marker, skill_dir=skill_dir, quiet=True, force=True,
        )
    assert ran is True
    mock_browser.assert_called_once()


def test_run_setup_writes_marker_after_first_run(marker: Path, skill_dir: Path) -> None:
    with patch.object(setup_mod, '_install_playwright_chromium', return_value=True):
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
    '''Running twice must leave the file in the same state, not error.'''
    setup_mod._install_skill(quiet=True, skill_dir=skill_dir)
    first = (skill_dir / 'SKILL.md').read_bytes()
    setup_mod._install_skill(quiet=True, skill_dir=skill_dir)
    second = (skill_dir / 'SKILL.md').read_bytes()
    assert first == second


# ---------- browser extra detection ----------


def test_install_playwright_skips_when_extra_missing() -> None:
    '''Without [browser] extra installed, the function reports success
    without invoking subprocess at all.'''
    with patch.object(setup_mod, '_has_browser_extra', return_value=False), \
         patch.object(subprocess, 'run') as mock_run:
        ok = setup_mod._install_playwright_chromium(quiet=True)
    assert ok is True
    mock_run.assert_not_called()


def test_install_playwright_runs_command_when_extra_present() -> None:
    fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')
    with patch.object(setup_mod, '_has_browser_extra', return_value=True), \
         patch.object(subprocess, 'run', return_value=fake_result) as mock_run:
        ok = setup_mod._install_playwright_chromium(quiet=True)
    assert ok is True
    mock_run.assert_called_once()
    cmd = mock_run.call_args.args[0]
    assert 'playwright' in cmd
    assert 'install' in cmd
    assert 'chromium' in cmd


def test_install_playwright_returns_false_on_nonzero_exit() -> None:
    fake_result = subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr='boom')
    with patch.object(setup_mod, '_has_browser_extra', return_value=True), \
         patch.object(subprocess, 'run', return_value=fake_result):
        ok = setup_mod._install_playwright_chromium(quiet=True)
    assert ok is False


def test_install_playwright_handles_timeout() -> None:
    with patch.object(setup_mod, '_has_browser_extra', return_value=True), \
         patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired(cmd='', timeout=1)):
        ok = setup_mod._install_playwright_chromium(quiet=True)
    assert ok is False


# ---------- ensure_setup (the lazy hot path) ----------


def test_ensure_setup_is_noop_when_marker_exists(marker: Path) -> None:
    '''Hot path: a single Path.exists() and we're done.'''
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('done')
    with patch.object(setup_mod, 'run_setup') as mock_run:
        setup_mod.ensure_setup(marker_path=marker)
    mock_run.assert_not_called()


def test_ensure_setup_runs_setup_when_marker_missing(marker: Path) -> None:
    with patch.object(setup_mod, 'run_setup') as mock_run:
        setup_mod.ensure_setup(marker_path=marker)
    mock_run.assert_called_once()
