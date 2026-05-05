'''Tests for the local write_token state store.

Uses tmp_path so each test gets an isolated directory; AGENTCLIP_STATE_PATH
is not used here because constructing StateStore(path=...) directly is
clearer in test code.
'''

from __future__ import annotations

import json

import pytest

from agentclip.state import StateStore


def test_remember_and_get_token(tmp_path):
    store = StateStore(path=tmp_path / 'state.json')
    store.remember(
        'ss_abc',
        write_token='wt_secret',
        share_url='https://q.example/s/abc',
        title='hello',
    )
    assert store.get_token('ss_abc') == 'wt_secret'


def test_get_token_missing_returns_none(tmp_path):
    store = StateStore(path=tmp_path / 'state.json')
    assert store.get_token('does_not_exist') is None


def test_remember_creates_parent_dir(tmp_path):
    nested = tmp_path / 'a' / 'b' / 'state.json'
    StateStore(path=nested).remember(
        'ss_x',
        write_token='wt',
        share_url='https://q.example/s/x',
    )
    assert nested.exists()


def test_remember_is_idempotent_overwrite(tmp_path):
    store = StateStore(path=tmp_path / 'state.json')
    store.remember('ss_x', write_token='old', share_url='https://q.example/s/x')
    store.remember('ss_x', write_token='new', share_url='https://q.example/s/x2')
    assert store.get_token('ss_x') == 'new'
    assert store.all_slideshows()['ss_x']['share_url'] == 'https://q.example/s/x2'


def test_corrupt_state_treated_as_empty(tmp_path):
    '''A wedged state file should not brick the CLI.'''
    path = tmp_path / 'state.json'
    path.write_text('{this is not valid json')
    store = StateStore(path=path)
    assert store.get_token('anything') is None
    # Subsequent writes recover and replace the corrupt file.
    store.remember('ss_y', write_token='wt', share_url='https://q.example/s/y')
    assert store.get_token('ss_y') == 'wt'


def test_atomic_write_no_partial_file_on_disk(tmp_path):
    '''After a successful remember(), the dir contains exactly state.json.

    The atomic-write path writes to a tempfile and renames; we verify no
    .state-*.json.tmp leftovers escape into the user's directory.
    '''
    store = StateStore(path=tmp_path / 'state.json')
    store.remember('ss_x', write_token='wt', share_url='https://q.example/s/x')
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != 'state.json']
    assert leftovers == [], f'unexpected files left behind: {leftovers}'


def test_state_file_is_valid_json(tmp_path):
    path = tmp_path / 'state.json'
    StateStore(path=path).remember(
        'ss_x',
        write_token='wt',
        share_url='https://q.example/s/x',
        title='Sample',
    )
    data = json.loads(path.read_text())
    assert data['slideshows']['ss_x']['title'] == 'Sample'
    assert data['slideshows']['ss_x']['write_token'] == 'wt'


def test_state_file_perms_are_tightened(tmp_path):
    '''write_tokens are credentials; the file must be 0600.'''
    pytest.importorskip('os')
    import os
    import stat

    path = tmp_path / 'state.json'
    StateStore(path=path).remember(
        'ss_x', write_token='wt', share_url='https://q.example/s/x'
    )
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600
