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
from datetime import datetime, timezone
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
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        self._write(data)

    def get_token(self, slideshow_id: str) -> str | None:
        entry = self._read().get('slideshows', {}).get(slideshow_id)
        return entry.get('write_token') if entry else None

    def all_slideshows(self) -> dict[str, dict]:
        return dict(self._read().get('slideshows', {}))
