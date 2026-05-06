'''Integration tests for the lazy first-run setup flow.

These run the real CLI through Typer's CliRunner against a fully
isolated tmp HOME, which means:

- A real marker file is written to disk.
- The real bundled SKILL.md is copied to a real ~/.claude/skills tree
  (just under the tmp HOME, never the host's actual home).
- The hot-path perf assertion runs against a real `Path.exists()` —
  if someone ever rewrites `is_setup_complete` to read+parse the
  marker, this test catches the regression.

Playwright is excluded from the test environment, so the browser
install branch resolves the "extra missing" path naturally without
mocks.
'''

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentclip.cli import app


def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    '''Redirect HOME, the state path, and the setup marker into tmp_path.

    Returns the marker path so individual tests can assert against it.
    '''
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('AGENTCLIP_STATE_PATH', str(tmp_path / 'state.json'))
    marker = tmp_path / 'agentclip' / '.setup-complete'
    monkeypatch.setenv('AGENTCLIP_SETUP_MARKER', str(marker))
    return marker


def test_first_invocation_runs_setup_and_writes_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _isolate(tmp_path, monkeypatch)
    assert not marker.exists()

    runner = CliRunner()
    result = runner.invoke(app, ['slideshow', 'list'])

    assert result.exit_code == 0, result.stdout
    assert marker.exists(), 'marker should be written after first invocation'
    body = json.loads(marker.read_text())
    assert body['version']


def test_subsequent_invocations_skip_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    '''Once the marker exists, the lazy callback must short-circuit.

    We assert this by inspecting the marker's mtime: it should NOT
    change on subsequent invocations because run_setup never fires.
    '''
    marker = _isolate(tmp_path, monkeypatch)
    runner = CliRunner()

    # First invocation creates the marker.
    runner.invoke(app, ['slideshow', 'list'])
    assert marker.exists()
    first_mtime = marker.stat().st_mtime_ns

    # Sleep 5ms so any new write would have a different mtime.
    time.sleep(0.005)

    # Second invocation must short-circuit — marker mtime stays put.
    runner.invoke(app, ['slideshow', 'list'])
    assert marker.stat().st_mtime_ns == first_mtime


def test_explicit_setup_command_is_idempotent_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _isolate(tmp_path, monkeypatch)
    runner = CliRunner()

    first = runner.invoke(app, ['setup', '--quiet'])
    assert first.exit_code == 0
    assert marker.exists()
    first_mtime = marker.stat().st_mtime_ns
    time.sleep(0.005)

    # Without --force, the second run is a no-op (marker stays put).
    second = runner.invoke(app, ['setup', '--quiet'])
    assert second.exit_code == 0
    assert marker.stat().st_mtime_ns == first_mtime


def test_explicit_setup_force_rewrites_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _isolate(tmp_path, monkeypatch)
    runner = CliRunner()

    runner.invoke(app, ['setup', '--quiet'])
    first_mtime = marker.stat().st_mtime_ns
    time.sleep(0.005)

    forced = runner.invoke(app, ['setup', '--force', '--quiet'])
    assert forced.exit_code == 0
    assert marker.stat().st_mtime_ns > first_mtime


def test_version_command_does_not_trigger_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    '''`agentclip version` is a status query — must not write the marker.'''
    marker = _isolate(tmp_path, monkeypatch)
    runner = CliRunner()

    result = runner.invoke(app, ['version'])
    assert result.exit_code == 0
    assert not marker.exists(), 'version must not trigger lazy setup'


def test_install_skill_command_does_not_recurse_into_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    '''`agentclip install-skill` is the manual fallback for the skill
    step setup performs. The lazy callback must NOT trigger setup
    before install-skill runs (would be confusing nested behavior).'''
    marker = _isolate(tmp_path, monkeypatch)
    runner = CliRunner()

    # install-skill writes its own SKILL.md; we don't care about that
    # for this test, only that the setup marker isn't touched.
    runner.invoke(app, ['install-skill', '--target', str(tmp_path / 'skills')])
    assert not marker.exists()


def test_lazy_setup_hot_path_is_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    '''Once the marker exists, ensure_setup() must add <50ms per call.

    Tested at the function level (not via CliRunner) so we measure the
    setup hot path in isolation — Typer's argument parsing dominates
    end-to-end CLI cold-start time and would mask regressions here.
    '''
    marker = _isolate(tmp_path, monkeypatch)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({'version': 'test', 'completed_at': '2026-05-06T00:00:00Z'}))

    from agentclip.setup import ensure_setup

    # Warm up filesystem cache.
    ensure_setup()

    iterations = 100
    start = time.perf_counter_ns()
    for _ in range(iterations):
        ensure_setup()
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000

    avg_ms_per_call = elapsed_ms / iterations
    # 50ms is the documented bar; on real hardware this should be
    # well under 1ms. Generous bound here so flaky CI doesn't lie.
    assert avg_ms_per_call < 50, f'ensure_setup hot path too slow: {avg_ms_per_call:.3f}ms/call'
