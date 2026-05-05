# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05

Initial public release.

### Added

- Python SDK (`AgentClipClient`) with `create_slideshow`, `add_slide`, `update_slide`, `set_summary`.
- Typer CLI mirroring the SDK, plus `agentclip install-skill` and `agentclip slideshow list`.
- MCP server (`agentclip-mcp`) registering four tools: `slideshow_create`, `slideshow_add_slide`, `slideshow_update_slide`, `slideshow_set_summary`.
- Bundled Claude skill at `src/agentclip/skill/SKILL.md` covering when to screenshot, caption style, narrative arc, summary format, and anti-patterns.
- Local state store at `~/.agentclip/state.json` for write_token persistence with atomic writes and 0600 permissions.
- 20-test suite covering SDK wire shapes (httpx MockTransport) and state persistence.

### Notes

- Default backend URL: `https://agentclip.dev`. Override with `AGENTCLIP_BASE_URL` for self-hosted deploys.
- v0.1 has no account flow; the `write_token` returned at create time is the only credential.

[Unreleased]: https://github.com/ericelizes/agentclip/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ericelizes/agentclip/releases/tag/v0.1.0
