'''Tests for AgentClipClient using httpx.MockTransport.

We inject a MockTransport via the http_client= parameter to exercise
real request shapes without hitting a network. Each test asserts both
the response handling and the wire-format the SDK actually sends —
because the wire-format is the contract with the Django backend, and
silent regressions there would be invisible in the SDK's own surface.
'''

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import httpx
import pytest

from agentclip.sdk import AgentClipClient, AgentClipError
from agentclip.state import StateStore


def make_client(handler, state_store: StateStore | None = None) -> AgentClipClient:
    '''Wire an AgentClipClient up to a MockTransport handler.

    Tests get a per-call isolated StateStore by default so a real
    ~/.agentclip/state.json on the developer's machine cannot bleed
    a stored whoami into the request body and break wire-shape
    assertions. Pass ``state_store=`` to inject a pre-configured one
    (e.g., to test the whoami auto-application path).
    '''
    http = httpx.Client(transport=httpx.MockTransport(handler))
    if state_store is None:
        # tempfile.mkdtemp because tmp_path is a pytest fixture and we
        # want make_client usable from non-fixture contexts too. Each
        # test gets its own throwaway directory; gc-cleanup is left
        # to the OS, which is fine for the test workload.
        state_store = StateStore(path=Path(tempfile.mkdtemp()) / 'state.json')
    return AgentClipClient(
        base_url='https://agentclip.test',
        http_client=http,
        state_store=state_store,
    )


# ---------- create_slideshow ----------


def test_create_slideshow_posts_json_body():
    captured: dict = {}

    def handler(request):
        captured['url'] = str(request.url)
        captured['method'] = request.method
        captured['body'] = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                'id': 'ss_1',
                'share_url': 'https://agentclip.test/s/abc',
                'write_token': 'wt_secret',
            },
        )

    client = make_client(handler)
    result = client.create_slideshow(title='hello', description='testing')

    assert captured['method'] == 'POST'
    assert captured['url'] == 'https://agentclip.test/api/slideshow/'
    assert captured['body'] == {'title': 'hello', 'description': 'testing'}
    assert result.id == 'ss_1'
    assert result.write_token == 'wt_secret'


def test_create_slideshow_omits_unset_fields():
    captured: dict = {}

    def handler(request):
        captured['body'] = json.loads(request.content)
        return httpx.Response(
            201,
            json={'id': 'ss_1', 'share_url': 'https://q/s/1', 'write_token': 'wt'},
        )

    make_client(handler).create_slideshow()
    assert captured['body'] == {}


def test_create_slideshow_raises_on_non_201_with_body():
    def handler(request):
        return httpx.Response(429, text='rate limited')

    with pytest.raises(AgentClipError) as exc:
        make_client(handler).create_slideshow()
    assert exc.value.status_code == 429
    assert exc.value.body == 'rate limited'


# ---------- add_slide ----------


def test_add_slide_sends_multipart_with_auth(tmp_path):
    captured: dict = {}

    def handler(request):
        captured['method'] = request.method
        captured['url'] = str(request.url)
        captured['auth'] = request.headers.get('authorization')
        captured['content_type'] = request.headers.get('content-type', '')
        captured['body'] = request.content
        return httpx.Response(
            201,
            json={
                'id': 1,
                'position': 1,
                'caption': 'first slide',
                'media_url': 'https://q/s/x/img/1.png',
            },
        )

    image = tmp_path / 'shot.png'
    image.write_bytes(b'\x89PNG\r\n\x1a\nfake')

    client = make_client(handler)
    result = client.add_slide(
        'ss_x', media_path=image, caption='first slide', write_token='wt_secret'
    )

    assert captured['method'] == 'POST'
    assert captured['url'] == 'https://agentclip.test/api/slideshow/ss_x/slides/'
    assert captured['auth'] == 'Bearer wt_secret'
    assert captured['content_type'].startswith('multipart/form-data')
    # Body should contain both the caption text and the file bytes
    assert b'first slide' in captured['body']
    assert b'\x89PNG' in captured['body']
    assert result.position == 1


def test_add_slide_rejects_missing_media(tmp_path):
    client = make_client(lambda r: httpx.Response(500))
    with pytest.raises(AgentClipError, match='media not found'):
        client.add_slide(
            'ss_x',
            media_path=tmp_path / 'does-not-exist.png',
            caption='c',
            write_token='wt',
        )


# ---------- update_slide ----------


def test_update_slide_caption_only_sends_json_patch():
    captured: dict = {}

    def handler(request):
        captured['method'] = request.method
        captured['content_type'] = request.headers.get('content-type', '')
        captured['body'] = request.content
        return httpx.Response(
            200,
            json={
                'id': 7,
                'position': 3,
                'caption': 'fixed',
                'media_url': 'https://q/s/x/img/3.png',
            },
        )

    result = make_client(handler).update_slide(
        'ss_x', 3, caption='fixed', write_token='wt'
    )

    assert captured['method'] == 'PATCH'
    assert 'application/json' in captured['content_type']
    assert json.loads(captured['body']) == {'caption': 'fixed'}
    assert result.caption == 'fixed'


def test_update_slide_with_image_sends_multipart(tmp_path):
    captured: dict = {}

    def handler(request):
        captured['content_type'] = request.headers.get('content-type', '')
        captured['body'] = request.content
        return httpx.Response(
            200,
            json={
                'id': 7,
                'position': 3,
                'caption': 'new caption',
                'media_url': 'https://q/s/x/img/3.png',
            },
        )

    image = tmp_path / 'new.png'
    image.write_bytes(b'\x89PNG\r\n\x1a\nfake')

    make_client(handler).update_slide(
        'ss_x', 3, media_path=image, caption='new caption', write_token='wt'
    )
    assert captured['content_type'].startswith('multipart/form-data')
    assert b'new caption' in captured['body']
    assert b'\x89PNG' in captured['body']


def test_update_slide_no_args_raises():
    client = make_client(lambda r: httpx.Response(500))
    with pytest.raises(AgentClipError, match='requires media_path and/or caption'):
        client.update_slide('ss_x', 1, write_token='wt')


# ---------- set_summary ----------


def test_set_summary_patches_slideshow_with_auth():
    captured: dict = {}

    def handler(request):
        captured['url'] = str(request.url)
        captured['method'] = request.method
        captured['auth'] = request.headers.get('authorization')
        captured['body'] = json.loads(request.content)
        return httpx.Response(
            200,
            json={'id': 'ss_x', 'summary': 'wrap'},
        )

    result = make_client(handler).set_summary(
        'ss_x', summary='wrap', write_token='wt_secret'
    )

    assert captured['method'] == 'PATCH'
    assert captured['url'] == 'https://agentclip.test/api/slideshow/ss_x/'
    assert captured['auth'] == 'Bearer wt_secret'
    assert captured['body'] == {'summary': 'wrap'}
    assert result.summary == 'wrap'


def test_patch_slideshow_no_fields_raises():
    with pytest.raises(AgentClipError, match='at least one field'):
        make_client(lambda r: httpx.Response(500)).patch_slideshow(
            'ss_x', write_token='wt'
        )


# ---------- error handling ----------


def test_non_json_response_surfaces_body():
    def handler(request):
        return httpx.Response(500, text='<html>boom</html>')

    with pytest.raises(AgentClipError) as exc:
        make_client(handler).create_slideshow()
    assert exc.value.status_code == 500
    assert '<html>boom</html>' in (exc.value.body or '')


def test_base_url_trailing_slash_is_normalized():
    captured: dict = {}

    def handler(request):
        captured['url'] = str(request.url)
        return httpx.Response(
            201, json={'id': 'ss_1', 'share_url': 'x', 'write_token': 'wt'}
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    AgentClipClient(
        base_url='https://agentclip.test/',
        http_client=http,
        state_store=StateStore(path=Path(tempfile.mkdtemp()) / 'state.json'),
    ).create_slideshow()
    assert captured['url'] == 'https://agentclip.test/api/slideshow/'


# ---------- whoami auto-application ----------


def _store_with_whoami(tmp_path, name='Eric Elizes', url='https://elizes.dev') -> StateStore:
    '''Build a StateStore at tmp_path with whoami pre-set.'''
    s = StateStore(path=tmp_path / 'state.json')
    s.set_whoami(name, url)
    return s


def test_create_slideshow_auto_applies_whoami_when_set(tmp_path):
    captured: dict = {}

    def handler(request):
        captured['body'] = json.loads(request.content)
        return httpx.Response(
            201, json={'id': 'ss_1', 'share_url': 'x', 'write_token': 'wt'}
        )

    client = make_client(handler, state_store=_store_with_whoami(tmp_path))
    client.create_slideshow(title='hello')

    # The whoami values were merged into the request body without the
    # caller having to pass them explicitly.
    assert captured['body']['created_by'] == 'Eric Elizes'
    assert captured['body']['created_by_url'] == 'https://elizes.dev'


def test_create_slideshow_caller_overrides_stored_whoami(tmp_path):
    captured: dict = {}

    def handler(request):
        captured['body'] = json.loads(request.content)
        return httpx.Response(
            201, json={'id': 'ss_1', 'share_url': 'x', 'write_token': 'wt'}
        )

    client = make_client(handler, state_store=_store_with_whoami(tmp_path))
    client.create_slideshow(
        title='hello',
        created_by='Override Name',
        created_by_url='https://override.example',
    )

    # Caller arguments win over stored whoami.
    assert captured['body']['created_by'] == 'Override Name'
    assert captured['body']['created_by_url'] == 'https://override.example'


def test_create_slideshow_omits_created_by_when_no_whoami(tmp_path):
    '''Empty state store means the request body has no created_by fields.

    Sending '' would persist as empty strings; omitting lets the backend
    default to its own empty-string columns. Either works, but omitting
    is cleaner on the wire.
    '''
    captured: dict = {}

    def handler(request):
        captured['body'] = json.loads(request.content)
        return httpx.Response(
            201, json={'id': 'ss_1', 'share_url': 'x', 'write_token': 'wt'}
        )

    client = make_client(handler)  # default isolated, empty store
    client.create_slideshow(title='hello')

    assert 'created_by' not in captured['body']
    assert 'created_by_url' not in captured['body']


def test_create_slideshow_handles_whoami_with_no_url(tmp_path):
    '''Name-only whoami sends created_by but omits created_by_url.'''
    captured: dict = {}

    def handler(request):
        captured['body'] = json.loads(request.content)
        return httpx.Response(
            201, json={'id': 'ss_1', 'share_url': 'x', 'write_token': 'wt'}
        )

    store = StateStore(path=tmp_path / 'state.json')
    store.set_whoami('Eric Elizes')  # url omitted
    client = make_client(handler, state_store=store)
    client.create_slideshow(title='hello')

    assert captured['body']['created_by'] == 'Eric Elizes'
    assert 'created_by_url' not in captured['body']
