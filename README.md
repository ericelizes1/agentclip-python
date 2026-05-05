# qagent

Turn AI agent QA runs into shareable slideshows.

QAgent is an MCP server, CLI, and Claude Code skill. You ask your local AI agent
to QA a web app. The agent drives the browser (via its existing tools), takes
screenshots at meaningful moments, writes captions, and uploads everything as a
**slideshow** — a single shareable URL anyone can watch.

The product is the artifact (the slideshow URL) plus the prompt engineering
(the skill) that makes agent-generated runs actually good.

## Status

Built in May 2026. Early. APIs may shift before a 1.0 tag.

## Install

```bash
pip install qagent
# or, no install:
uvx qagent --help
```

## 60-second example

```bash
# In Claude Code, after installing the skill:
qagent install-skill

# Then ask the agent: "QA the signup flow on localhost:3000 and post a slideshow."
# The agent calls slideshow_create, takes screenshots, calls slideshow_add_slide
# after each meaningful step, then slideshow_set_summary at the end. You get
# back a share URL.
```

## Layout

- `src/qagent/sdk.py` — real implementation, sync HTTP client over `httpx`
- `src/qagent/cli.py` — `qagent ...` Typer CLI, thin wrapper over the SDK
- `src/qagent/mcp_server.py` — MCP server registering 4 tools, thin wrapper over the SDK
- `src/qagent/state.py` — `~/.qagent/state.json` write_token persistence
- `src/qagent/skill/SKILL.md` — the Claude skill, installed to `~/.claude/skills/qagent/`

## Tools (MCP + CLI mirror)

| Tool | Purpose |
|---|---|
| `slideshow_create` | Start a slideshow. Returns id, share URL, write token. |
| `slideshow_add_slide` | Append a screenshot + caption. |
| `slideshow_update_slide` | Replace a slide (image and/or caption). |
| `slideshow_set_summary` | Set the run's TL;DR near the end. |

## License

MIT.
