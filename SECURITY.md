# Security Policy

## Supported versions

AgentClip is pre-1.0. We patch the most recent minor release.

| Version | Supported |
|---|---|
| 0.1.x | yes |
| < 0.1 | no |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security bugs.**

Email <eric@elizes.dev> with:

- A description of the issue and the impact
- Steps to reproduce, ideally a minimal repro
- The version you tested against
- Whether you'd like to be credited in the advisory

You'll get an acknowledgement within 72 hours and a remediation plan within
seven days for confirmed issues. Coordinated disclosure timelines are
negotiable but default to 30 days from confirmation.

## What's in scope

- The `agentclip` Python package (SDK, CLI, MCP server, bundled skill)
- Authentication and write_token handling
- Storage paths, including local state at `~/.agentclip/state.json`

## What's out of scope (handle via the appropriate upstream)

- Vulnerabilities in pinned dependencies (httpx, typer, mcp, pydantic) — report to those projects directly
- Issues in the hosted backend deployed at agentclip.dev — see `agentclip-app/SECURITY.md`
- Issues in agent runtimes that consume our MCP server (Claude Desktop, Cursor, etc.)

## Disclosure history

None yet.
