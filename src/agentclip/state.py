'''Local persistence for slideshow write_tokens.

The hosted backend has no accounts in v1: a slideshow is mutable iff
the caller can present its write_token. That means losing the token
silently freezes the slideshow forever, so we cache it locally the
moment it's issued.

Default location is ``~/.agentclip/state.json``. Override with
``AGENTCLIP_STATE_PATH`` for tests or ephemeral environments.

Format::

    {
      "slideshows": {
        "<slideshow_id>": {
          "write_token": "...",
          "share_url": "...",
          "title": "Signup flow QA",
          "created_at": "2026-05-05T18:30:21+00:00"
        }
      }
    }
'''

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def default_state_path() -> Path:
    '''Resolve the state file path, honoring AGENTCLIP_STATE_PATH when set.'''
    override = os.environ.get('AGENTCLIP_STATE_PATH')
    if override:
        return Path(override).expanduser()
    return Path.home() / '.agentclip' / 'state.json'


class StateStore:
    '''JSON-backed key-value store for write_tokens.

    Reads are lazy and re-read each call: the file is small, and other
    processes (a parallel CLI invocation, the MCP server) may be writing
    to it. Writes are atomic via tempfile + rename, so a kill mid-write
    cannot leave a partial file on disk.
    '''

    def __init__(self, path: Path | None = None):
        self.path = path or default_state_path()

    def _read(self) -> dict:
        if not self.path.exists():
            return {'slideshows': {}}
        try:
            return json.loads(self.path.read_text())
        except json.JSONDecodeError:
            # Treat a corrupt state file as empty rather than crashing.
            # Worst case the user has to paste their write_token in by
            # hand for one slideshow; better than wedging the CLI.
            return {'slideshows': {}}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # NamedTemporaryFile + os.replace is the standard atomic write
        # pattern: rename is atomic on POSIX, so the file either has the
        # old contents or the new contents, never half of each.
        with tempfile.NamedTemporaryFile(
            mode='w',
            dir=self.path.parent,
            prefix='.state-',
            suffix='.json.tmp',
            delete=False,
        ) as tmp:
            json.dump(data, tmp, indent=2, sort_keys=True)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = tmp.name
        os.replace(tmp_path, self.path)
        # Tighten perms; write_tokens are credentials.
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            # Filesystems that ignore chmod (e.g. some FAT mounts) are
            # fine; nothing we can do, and the user opted into that path.
            pass

    def remember(
        self,
        slideshow_id: str,
        *,
        write_token: str,
        share_url: str,
        title: str | None = None,
    ) -> None:
        '''Cache the write_token for ``slideshow_id``.

        Idempotent: re-remembering the same id overwrites the prior entry,
        which is what the user wants when they re-create with the same
        title and the backend hands back a new id+token pair.
        '''
        data = self._read()
        data.setdefault('slideshows', {})[slideshow_id] = {
            'write_token': write_token,
            'share_url': share_url,
            'title': title,
            'created_at': datetime.now(UTC).isoformat(),
        }
        self._write(data)

    def get_token(self, slideshow_id: str) -> str | None:
        entry = self._read().get('slideshows', {}).get(slideshow_id)
        return entry.get('write_token') if entry else None

    def all_slideshows(self) -> dict[str, dict]:
        return dict(self._read().get('slideshows', {}))

    def forget_slideshow(self, slideshow_id: str) -> bool:
        '''Drop the cached entry for ``slideshow_id``.

        Returns True when an entry existed and was removed, False when
        nothing was cached. Used after ``delete_slideshow`` to keep the
        local cache from accumulating stale tokens for rows that no
        longer exist on the backend.
        '''
        data = self._read()
        slideshows = data.get('slideshows', {})
        if slideshow_id not in slideshows:
            return False
        del slideshows[slideshow_id]
        self._write(data)
        return True

    # ----- whoami: optional creator credit applied to every new clip -----

    def get_whoami(self) -> dict | None:
        '''Return the stored creator credit, or None if not set.

        Shape: ``{'name': str, 'url': str}``. ``url`` may be empty when the
        user set a name but no URL; the SDK passes empty strings through
        unchanged so the backend does its own URL validation.
        '''
        data = self._read().get('whoami')
        if not data or not data.get('name'):
            return None
        return {'name': data['name'], 'url': data.get('url', '')}

    def set_whoami(self, name: str, url: str | None = None) -> None:
        '''Store the creator credit. Overwrites any prior entry.'''
        data = self._read()
        data['whoami'] = {'name': name, 'url': url or ''}
        self._write(data)

    def clear_whoami(self) -> None:
        '''Remove the creator credit. No-op if none was set.'''
        data = self._read()
        if 'whoami' in data:
            del data['whoami']
            self._write(data)

    # ----- nudge flags: one-time CLI hints -----

    def get_flag(self, key: str) -> bool:
        '''Return True if a one-time CLI flag has been raised.

        Used by the CLI's first-create nudge to fire the credit-yourself
        tip exactly once per machine. Never errors when the key is absent.
        '''
        return bool(self._read().get('flags', {}).get(key))

    def set_flag(self, key: str) -> None:
        '''Raise a one-time CLI flag.'''
        data = self._read()
        data.setdefault('flags', {})[key] = True
        self._write(data)
