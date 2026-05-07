"""agentclip: turn AI agent QA runs into shareable slideshows."""

from .sdk import DEFAULT_BASE_URL, AgentClipClient, AgentClipError

__version__ = '0.3.1'

__all__ = [
    '__version__',
    'DEFAULT_BASE_URL',
    'AgentClipClient',
    'AgentClipError',
]
