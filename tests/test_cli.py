'''CLI command coverage for agentclip whoami and the first-create nudge.

Uses Typer's CliRunner against a per-test isolated state.json so the
developer's real ~/.agentclip/state.json never leaks into assertions
and tests never write to the real one.

The slideshow create command path (and its nudge) is covered with a
mocked HTTP backend via the same MockTransport seam as the SDK tests;
we are exercising the CLI's surrounding behavior, not the wire shape.
'''

from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

from agentclip.cli import app
from agentclip.state import StateStore


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    '''Point AGENTCLIP_STATE_PATH at tmp_path so the CLI uses an isolated store.'''
    path = tmp_path / 'state.json'
    monkeypatch.setenv('AGENTCLIP_STATE_PATH', str(path))
    return StateStore(path=path)


def test_whoami_no_args_prints_no_credit_when_unset(isolated_state):
    runner = CliRunner()
    result = runner.invoke(app, ['whoami'])
    assert result.exit_code == 0
    assert 'no credit set' in result.stdout


def test_whoami_set_then_get(isolated_state):
    runner = CliRunner()
    result = runner.invoke(app, ['whoami', '--set', 'Eric Elizes', '--url', 'https://elizes.dev'])
    assert result.exit_code == 0
    assert 'Filed by' in result.stdout

    # Reading back surfaces the stored credit.
    result = runner.invoke(app, ['whoami'])
    assert result.exit_code == 0
    assert 'Eric Elizes' in result.stdout
    assert 'https://elizes.dev' in result.stdout


def test_whoami_set_without_url(isolated_state):
    runner = CliRunner()
    result = runner.invoke(app, ['whoami', '--set', 'Eric'])
    assert result.exit_code == 0
    assert isolated_state.get_whoami() == {'name': 'Eric', 'url': ''}


def test_whoami_clear(isolated_state):
    isolated_state.set_whoami('Eric', 'https://elizes.dev')
    runner = CliRunner()
    result = runner.invoke(app, ['whoami', '--clear'])
    assert result.exit_code == 0
    assert isolated_state.get_whoami() is None


def test_whoami_set_empty_name_fails(isolated_state):
    runner = CliRunner()
    result = runner.invoke(app, ['whoami', '--set', '   '])
    assert result.exit_code != 0
    assert 'non-empty name' in result.stdout + result.stderr


def test_whoami_skip_tip_suppresses_nudge(isolated_state):
    runner = CliRunner()
    result = runner.invoke(app, ['whoami', '--skip-tip'])
    assert result.exit_code == 0
    assert isolated_state.get_flag('credit_nudge_shown') is True


def test_first_create_nudge_fires_once(isolated_state, monkeypatch):
    '''Slideshow create with no whoami stored shows the credit hint once.

    Second create call has the flag raised and stays silent.
    '''
    runner = CliRunner()

    # Mock the backend: every POST returns a fake created slideshow.
    def handler(request):
        return httpx.Response(
            201,
            json={
                'id': 'ss_demo',
                'share_url': 'https://agentclip.test/s/abc/',
                'write_token': 'wt_secret',
            },
        )

    # Patch httpx.Client used by the SDK so the CLI's create path hits the mock.
    real_client_cls = httpx.Client

    def _mock_client(*args, **kwargs):
        return real_client_cls(transport=httpx.MockTransport(handler))

    monkeypatch.setattr('agentclip.sdk.httpx.Client', _mock_client)

    # First create: nudge fires.
    result1 = runner.invoke(app, ['slideshow', 'create', '--title', 'first'])
    assert result1.exit_code == 0, result1.stdout + (result1.stderr or '')
    assert 'tip:' in result1.stdout.lower()

    # Second create: nudge stays silent (flag was raised by call 1).
    result2 = runner.invoke(app, ['slideshow', 'create', '--title', 'second'])
    assert result2.exit_code == 0
    assert 'tip:' not in result2.stdout.lower()


def test_first_create_nudge_skipped_when_whoami_set(isolated_state, monkeypatch):
    '''If the user already set whoami, the nudge never fires.'''
    isolated_state.set_whoami('Eric', 'https://elizes.dev')
    runner = CliRunner()

    def handler(request):
        return httpx.Response(
            201,
            json={
                'id': 'ss_demo',
                'share_url': 'https://agentclip.test/s/abc/',
                'write_token': 'wt_secret',
            },
        )

    real_client_cls = httpx.Client

    def _mock_client(*args, **kwargs):
        return real_client_cls(transport=httpx.MockTransport(handler))

    monkeypatch.setattr('agentclip.sdk.httpx.Client', _mock_client)

    result = runner.invoke(app, ['slideshow', 'create', '--title', 'silent'])
    assert result.exit_code == 0
    assert 'tip:' not in result.stdout.lower()
