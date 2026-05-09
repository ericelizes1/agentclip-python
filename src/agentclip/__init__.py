"""agentclip: turn AI agent QA runs into shareable slideshows."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from .sdk import DEFAULT_BASE_URL, AgentClipClient, AgentClipError

# Read the version from installed package metadata so pyproject.toml is
# the single source of truth — previously this was hardcoded and drifted
# multiple releases behind the actual published version.
try:
    __version__ = _pkg_version('agentclip')
except PackageNotFoundError:
    # In-tree development without an editable install (rare). Falling
    # back to '0+dev' avoids a hard crash for someone reading the
    # source without installing.
    __version__ = '0+dev'

__all__ = [
    '__version__',
    'DEFAULT_BASE_URL',
    'AgentClipClient',
    'AgentClipError',
]
