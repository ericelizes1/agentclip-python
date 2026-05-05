'''qagent — turn AI agent QA runs into shareable slideshows.'''

from .sdk import DEFAULT_BASE_URL, QAgentClient, QAgentError

__version__ = '0.1.0'

__all__ = [
    '__version__',
    'DEFAULT_BASE_URL',
    'QAgentClient',
    'QAgentError',
]
