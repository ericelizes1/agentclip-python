# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-05-07

The render-pipeline release. Backend now produces a server-rendered MP4, a branded PDF walkthrough, an OG-tagged poster image, and a chrome-less iframe embed page for every clip — all materialized lazily on first external fetch and pre-warmed on `slideshow_set_summary`. This package surfaces the artifact URLs at the CLI/SDK boundary so agents can hand them straight off.

### Added

- `clip_mp4_url`, `clip_pdf_url`, `embed_url` (and `edit_url`) on the `slideshow_create` response model. Surfaced in the CLI's create-summary output as `mp4:`, `pdf:`, and `embed:` lines so the agent can echo them into PR descriptions, Slack messages, or wherever the user is going to paste them.
- `slideshow_set_summary` summary block echoes the share + `.mp4` + `.pdf` URLs at the agent's "I'm done" moment, since that's the moment the renders pre-warm server-side and the URLs become useful.
- `StateStore.get_share_url` so callers can resolve the cached share URL by `slideshow_id` without a server round-trip.

### Changed

- Bundled `SKILL.md` updated to walk through the four artifact surfaces (share, MP4 for GitHub, PDF for downloads, embed for iframes) and to clarify that narration is now automatic — agents do not call `narrate` as a separate step.

### Notes

- Backwards-compatible. Older API versions that don't surface the new fields parse cleanly; the artifact lines simply don't print.

[0.2.0]: https://github.com/ericelizes1/agentclip-python/compare/v0.1.0...v0.2.0

## [0.1.0] - 2026-05-06

First public release. Backend is live at https://agentclip.dev; this package is the canonical client.

### Added

- Python SDK (`AgentClipClient`) with `create_slideshow`, `add_slide`, `update_slide`, `set_summary`, `delete_slideshow`.
- Typer CLI mirroring the SDK: `agentclip slideshow create | add | update | summary | delete | list`, plus `agentclip whoami`, `agentclip install-skill`, `agentclip setup`, `agentclip version`.
- MCP server (`agentclip-mcp`) registering four tools: `slideshow_create`, `slideshow_add_slide`, `slideshow_update_slide`, `slideshow_set_summary`.
- Bundled Claude skill at `src/agentclip/skill/SKILL.md` covering when to screenshot, caption style, narrative arc, summary format, and anti-patterns.
- Local state store at `~/.agentclip/state.json` for write_token persistence with atomic writes and 0600 permissions. Tracks slideshows, an optional `whoami` creator credit (auto-applied to every new clip), and one-time CLI nudge flags.
- Lazy first-run setup that wires the bundled Claude skill, downloads browser drivers if `[browser]` is installed, and writes a marker so subsequent invocations are instant. Bypassed for `version`, `setup`, and `install-skill` to keep them fast and non-recursive.
- Optional `[browser]` extra pulling Playwright for standalone CLI users; agent runtimes that bring their own browser substrate skip it by default.
- 65-test suite covering SDK wire shapes (httpx MockTransport), state persistence, CLI flow, and lazy setup.
- `justfile` with `test`, `lint`, `format`, and a guarded `release` recipe that enforces version match + changelog block + clean tree before tagging.

### Notes

- Default backend URL: `https://agentclip.dev`. Override with `AGENTCLIP_BASE_URL` for self-hosted deploys.
- v0.1 has no account flow; the `write_token` returned at create time is the only credential. Cache it via the state store or pass it explicitly.

[Unreleased]: https://github.com/ericelizes1/agentclip-python/compare/v0.2.0...HEAD
[0.1.0]: https://github.com/ericelizes1/agentclip-python/releases/tag/v0.1.0
