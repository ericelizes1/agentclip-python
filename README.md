# AgentClip Python SDK

One install for shareable videos from your AI agent.

[![PyPI](https://img.shields.io/pypi/v/agentclip.svg)](https://pypi.org/project/agentclip/)
[![Python](https://img.shields.io/pypi/pyversions/agentclip.svg)](https://pypi.org/project/agentclip/)
[![CI](https://github.com/ericelizes1/agentclip-python/actions/workflows/ci.yml/badge.svg)](https://github.com/ericelizes1/agentclip-python/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/pypi/l/agentclip.svg)](https://github.com/ericelizes1/agentclip-python/blob/main/LICENSE)

Your agent drives the browser. AgentClip ships the browser tools, screenshot and recording capture, MCP server, CLI, and bundled agent skill that turns the work into a narrated URL anyone can watch.

> **Live demo:** https://agentclip.dev

## Status

Built in May 2026. Early. APIs may shift before a 1.0 tag.

## Quick start

```bash
pip install agentclip
```

Then restart your agent runtime and ask for a clip:

> QA the signup flow on localhost:3000 and post a clip.

That is the intended path. The first time `agentclip` runs, setup automatically:

- installs the bundled `agentclip` skill
- registers the `agentclip-mcp` server
- installs Playwright Chromium for viewport-only browser capture
- enables screenshots and short video/GIF-style recordings

After that, your agent has the browser and slideshow tools it needs to create a narrated, shareable video.

Or run with no install:

```bash
uvx agentclip --help
```

## Supported agents

`agentclip setup` installs the skill and MCP registration for the agent runtimes most people use locally:

- `Claude Code` / Claude MCP config
- `Codex`
- `OpenCode`
- any MCP client that can run `agentclip-mcp`

If you only want one runtime:

```bash
agentclip setup --host codex
agentclip setup --host opencode
agentclip setup --host claude
```

Restart the agent after setup. Skills and MCP tools are loaded at agent startup, not mid-session.

## 60-second CLI example

Or use the CLI directly:

```bash
agentclip slideshow create --title "Signup QA" --description "Fresh-user signup flow."
agentclip slideshow add <slideshow_id> /tmp/shot1.png --caption "Clicked Sign Up. Form posted."
agentclip slideshow summary <slideshow_id> "Signup passed. One real bug at slide 4."

# Manage what you've made:
agentclip slideshow list
agentclip slideshow delete <slideshow_id>
```

## What gets installed

`agentclip setup` now installs the bundled skill and MCP registration for:

- `Claude` (`~/.claude/skills/agentclip/`, `~/.claude/mcp.json`)
- `Codex` (`~/.codex/skills/agentclip/`, `~/.codex/config.json` + `~/.codex/config.toml`)
- `OpenCode` (`~/.config/opencode/skills/agentclip/`, `~/.config/opencode/opencode.json`)

If you want to re-run just one host:

```bash
agentclip setup --host codex
agentclip install-skill --host opencode
agentclip install-mcp --host claude
```

Manual MCP shape, if you need it:

- `Claude` / `Codex` JSON-style config:

```json
{
  "mcpServers": {
    "agentclip": {
      "command": "agentclip-mcp"
    }
  }
}
```

- `OpenCode` `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "agentclip": {
      "type": "local",
      "enabled": true,
      "command": ["agentclip-mcp"]
    }
  }
}
```

Restart your agent runtime after install so the new tools and skill load.

If the skill does not appear after restart, verify the install:

```bash
agentclip version
agentclip whoami
agentclip setup --force --host codex
```

Then fully quit and reopen the agent runtime. Starting a new chat is not always enough.

## Tools

| Tool | Description |
|---|---|
| `browser_open` | Launch built-in Chromium in a fixed viewport and return a session id. |
| `browser_navigate` / `browser_click` / `browser_type` / `browser_press_key` | Drive the page through the flow you want to show. |
| `browser_screenshot` | Save a viewport-only PNG to disk for `slideshow_add_slide`. |
| `browser_start_recording` / `browser_stop_recording` | Capture a short animated recording to disk when motion is the story. |
| `browser_get_text` / `browser_wait_for_text` / `browser_close` | Pull text, wait for loaded states, and clean up sessions. |
| `slideshow_create` | Start a clip. Returns id, share URL, and a write_token used for subsequent mutations. |
| `slideshow_add_slide` | Append a screenshot, GIF, or short video plus caption. The local state store auto-supplies the write_token. |
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
- `src/agentclip/browser.py`: built-in Playwright browser runtime, screenshots, and recordings
- `src/agentclip/mcp_server.py`: MCP server registering both browser and slideshow tools
- `src/agentclip/state.py`: atomic-write `~/.agentclip/state.json` for write_tokens
- `src/agentclip/skill/SKILL.md`: the bundled agent skill

## Self-hosting the backend

Companion repo: [`ericelizes1/agentclip`](https://github.com/ericelizes1/agentclip) — the platform monorepo with the Django API and Next.js frontend. Reference deploy is **Fly.io** apps + **Neon** Postgres + **Cloudflare R2** object storage, with secrets sourced from **1Password**; `docker compose up --build` covers any Docker host. Point `AGENTCLIP_BASE_URL` at your domain. Full guide at [docs.agentclip.dev/self-hosting](https://docs.agentclip.dev/self-hosting).

## Development

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contributor guide. CI runs lint + format + tests across Python 3.11/3.12/3.13 on every PR.

## License

MIT. See [LICENSE](LICENSE).
