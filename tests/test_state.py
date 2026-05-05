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


# ---------- whoami ----------


def test_whoami_set_and_get(tmp_path):
    store = StateStore(path=tmp_path / 'state.json')
    store.set_whoami('Eric Elizes', 'https://elizes.dev')
    assert store.get_whoami() == {'name': 'Eric Elizes', 'url': 'https://elizes.dev'}


def test_whoami_get_when_never_set_returns_none(tmp_path):
    store = StateStore(path=tmp_path / 'state.json')
    assert store.get_whoami() is None


def test_whoami_clear_removes_entry(tmp_path):
    store = StateStore(path=tmp_path / 'state.json')
    store.set_whoami('Eric', 'https://elizes.dev')
    store.clear_whoami()
    assert store.get_whoami() is None


def test_whoami_set_without_url_stores_empty_string(tmp_path):
    '''Name only, URL omitted: get_whoami returns name with empty url.'''
    store = StateStore(path=tmp_path / 'state.json')
    store.set_whoami('Eric')
    assert store.get_whoami() == {'name': 'Eric', 'url': ''}


def test_whoami_coexists_with_slideshows(tmp_path):
    '''Setting whoami must not clobber the slideshows map and vice versa.'''
    store = StateStore(path=tmp_path / 'state.json')
    store.remember('ss_x', write_token='wt', share_url='https://q.example/s/x')
    store.set_whoami('Eric', 'https://elizes.dev')

    assert store.get_token('ss_x') == 'wt'
    assert store.get_whoami()['name'] == 'Eric'

    store.clear_whoami()
    assert store.get_token('ss_x') == 'wt'  # tokens still intact


def test_whoami_corrupt_state_returns_none(tmp_path):
    '''Same recovery shape as get_token: corrupt JSON treated as empty.'''
    path = tmp_path / 'state.json'
    path.write_text('{this is not valid json')
    store = StateStore(path=path)
    assert store.get_whoami() is None


# ---------- one-time flags (used by the CLI's first-create nudge) ----------


def test_flag_default_is_false(tmp_path):
    store = StateStore(path=tmp_path / 'state.json')
    assert store.get_flag('any_flag_name') is False


def test_flag_set_then_get(tmp_path):
    store = StateStore(path=tmp_path / 'state.json')
    store.set_flag('credit_nudge_shown')
    assert store.get_flag('credit_nudge_shown') is True
    # Other flags remain unset.
    assert store.get_flag('other_flag') is False
