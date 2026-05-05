# agentclip

Turn your AI agent's QA runs into shareable clips.

[![PyPI](https://img.shields.io/pypi/v/agentclip.svg)](https://pypi.org/project/agentclip/)
[![Python](https://img.shields.io/pypi/pyversions/agentclip.svg)](https://pypi.org/project/agentclip/)
[![CI](https://github.com/ericelizes/agentclip/actions/workflows/ci.yml/badge.svg)](https://github.com/ericelizes/agentclip/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/pypi/l/agentclip.svg)](https://github.com/ericelizes/agentclip/blob/main/LICENSE)

Your AI agent drives the browser. AgentClip captures the moments that matter, screenshots and captions, and ships you back a single URL anyone can watch.

The product is the artifact (the clip URL) plus the prompt engineering (the bundled skill) that makes generated runs actually good. The backend, MCP plumbing, and CLI are commodity.

> **Live demo:** https://agentclip.dev

## Status

Built in May 2026. Early. APIs may shift before a 1.0 tag.

## Install

```bash
pip install agentclip
agentclip install-skill
```

Or run with no install:

```bash
uvx agentclip --help
```

## 60-second example

```bash
# 1. Install the bundled skill into your agent runtime
agentclip install-skill

# 2. Ask your agent in plain English:
#    "QA the signup flow on localhost:3000 and post a clip."

# The agent calls slideshow_create, captures screenshots after each
# meaningful action, calls slideshow_add_slide with active-voice captions,
# then slideshow_set_summary at the end. You get back a share URL.

# Or use the CLI directly:
agentclip slideshow create --title "Signup QA" --description "fresh-user flow"
agentclip slideshow add <slideshow_id> /tmp/shot1.png --caption "Clicked Sign Up. Form posted."
agentclip slideshow summary <slideshow_id> "Signup passed. One real bug at slide 4."
```

## MCP install (Claude Desktop, Claude Code, Cursor)

Add to your `claude_desktop_config.json` (or equivalent):

```json
{
  "mcpServers": {
    "agentclip": {
      "command": "uvx",
      "args": ["agentclip-mcp"]
    }
  }
}
```

Restart your agent runtime. The four tools below will register automatically.

## Tools

| Tool | Description |
|---|---|
| `slideshow_create` | Start a clip. Returns id, share URL, and a write_token used for subsequent mutations. |
| `slideshow_add_slide` | Append a screenshot + caption. The local state store auto-supplies the write_token. |
| `slideshow_update_slide` | Replace the image and/or caption of a slide already in the clip. |
| `slideshow_set_summary` | Set the clip's TL;DR, near the end of the run. |

## Configuration

| Env var | Purpose | Default |
|---|---|---|
| `AGENTCLIP_BASE_URL` | Backend URL. Override for self-hosted. | `https://agentclip.dev` |
| `AGENTCLIP_STATE_PATH` | Write-token cache file. | `~/.agentclip/state.json` |

## Layout

- `src/agentclip/sdk.py`: `AgentClipClient`, sync HTTP client over `httpx`
- `src/agentclip/cli.py`: `agentclip ...` Typer CLI, thin wrapper over the SDK
- `src/agentclip/mcp_server.py`: MCP server registering the four tools
- `src/agentclip/state.py`: atomic-write `~/.agentclip/state.json` for write_tokens
- `src/agentclip/skill/SKILL.md`: the bundled agent skill

## Self-hosting the backend

Companion repo: [`ericelizes/agentclip-app`](https://github.com/ericelizes/agentclip-app) ships a Django backend, a public viewer, and a `.do/app.yaml` for one-command deploy to DigitalOcean App Platform. Then point `AGENTCLIP_BASE_URL` at your domain.

## Development

```bash
uv sync --all-extras --dev
uv run pytest -q
uv run ruff check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contributor guide. CI runs lint + format + tests across Python 3.11/3.12/3.13 on every PR.

## License

MIT. See [LICENSE](LICENSE).
