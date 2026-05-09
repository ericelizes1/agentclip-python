# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-05-09

### Added

- **Browser primitives in the MCP server.** Ten new tools — `browser_open`, `browser_navigate`, `browser_type`, `browser_click`, `browser_press_key`, `browser_wait_for_text`, `browser_screenshot`, `browser_get_text`, `browser_close`, `browser_list_sessions` — drive a Playwright Chromium instance from any MCP-speaking agent. `browser_screenshot` writes a viewport-only PNG to disk and returns the path; you pass that path straight into `slideshow_add_slide`. Sessions are scoped to the MCP server lifetime and torn down at exit. Closes the dogfood gap where agents had no canonical way to capture screenshots and would fall back to OS-level screencapture (which leaks IDE / terminal / chat windows to the public clip URL — a privacy bug).
- `run_type` parameter on the `slideshow_create` MCP tool. The SDK already accepted it; the MCP tool didn't expose it, which forced agents to use `walkthrough` (the server-side default) regardless of trigger phrasing.

### Changed

- `SKILL.md` "Browser tooling" section now names the agentclip-mcp `browser_*` tools as Method 1 (the canonical path), with a worked example. Other browser MCPs and scripted Playwright remain as fallbacks.
- `CLAUDE.md` documents how to register the agentclip-mcp server in `~/.claude/mcp.json` (and the local-checkout variant for development).

## [0.3.2] - 2026-05-07

Fix: `pip install agentclip` was broken out of the box. The default backend URL pointed at the marketing host, which 308-redirects `/api/*` and Cloudflare strips the body — so every `slideshow create` failed with `expected 201`. Default now points at the API host directly.

### Fixed

- `DEFAULT_BASE_URL` now resolves to `https://api.agentclip.dev` (was `https://agentclip.dev`). The marketing host doesn't forward `/api/*` to the Django service; the trailing-slash redirect plus Cloudflare's body-strip on 308 made every CLI/SDK write fail. Existing users who exported `AGENTCLIP_BASE_URL` are unaffected.

### Notes

- No API or schema changes. Drop-in replacement for 0.3.1.

[0.3.2]: https://github.com/ericelizes1/agentclip-python/compare/v0.3.1...v0.3.2

## [0.3.1] - 2026-05-07

Skill rewrite: caption + intro + outro guidance is now run-type-aware. Same content, different run_type, totally different voice.

### Changed

- `SKILL.md` Step 4 (captions) replaced the universal "action + expectation + result" rule with five explicit voice profiles — one per run_type — each with concrete good examples. Bug repros stay terse and stack-trace-adjacent. Demos read like a presenter narrating in present tense, with no setup or recap. Onboarding evals are observational. Competitive teardowns are analytical with named comparisons.
- `SKILL.md` Step 2 (description = spoken intro) gets per-run-type opener examples. Demo intros explicitly ban *"Welcome to..."*, *"Today we'll be looking at..."*, *"I'm excited to show you..."* — the MP4 starts where the action is.
- `SKILL.md` Step 6 (summary = spoken outro) gets per-run-type wrap examples. Demos land the value in one sentence, not a recap.
- New anti-patterns called out by name: corporate-presenter cringe, court-reporter past tense in demos, buzzword filler (*seamless*, *robust*, *leverage*), as-we-can-see-isms.
- Added a second worked example contrasting the *same* flow recorded as `smoke_test` (QA log) vs `demo` (presenter). Makes the run-type → voice mapping concrete.

### Notes

- No code changes. Backend pipeline is unchanged. This release is entirely about the prompt the bundled skill plants in the agent — better prompt, better captions, better narration.
- Run `agentclip install-skill --force` to refresh the cached skill on a previously-installed system.

[0.3.1]: https://github.com/ericelizes1/agentclip-python/compare/v0.3.0...v0.3.1

## [0.3.0] - 2026-05-07

The walkthrough release. Backend now produces a clip that opens with a brand title card + spoken intro and closes with an end card + spoken outro, with the narration voice picked automatically from the clip's `run_type`. The CLI/SDK exposes the new knobs and adds an explicit `narrate` command for force-regeneration use cases.

### Added

- `agentclip slideshow create --type/-T <run_type>` — sets the clip's run type at create time. Drives the narration voice + pacing for the whole rendered MP4 (intro + every slide + outro share one voice). Values: `bug_repro` (onyx), `smoke_test` (nova), `demo` (shimmer, slightly slower), `onboarding_eval` (nova), `competitive_teardown` (echo), `generic` (default, nova).
- `agentclip slideshow narrate <id_or_token>` — explicit CLI for narration. Accepts a slideshow_id (UUID) or a share_token. Flags: `--voice`, `--force`, `--dry-run`. In normal use you don't need this — hitting any clip's `.mp4` URL auto-narrates and renders. Use it for force-regeneration (e.g. trying a different voice on an already-narrated clip).
- `AgentClipClient.narrate_slideshow()` — SDK equivalent.
- `run_type` field on `SlideshowCreated` so the CLI/SDK can echo it back at create time.

### Changed

- Bundled `SKILL.md` rewrite. Adds a Step 0 pre-flight that picks the spine + run_type from the trigger phrasing — agent only asks the user when the prompt is too ambiguous to map. Vocabulary shifts from "slideshow" to "clip" / "walkthrough" in user-facing prose; tool names + CLI command verbs unchanged. Caption guidance gets a "narration-friendly" addendum (em-dashes for natural pacing, complete sentences, jargon-free for a listener). Old "Filed by" framing dropped throughout.
- CLI summary block at create time prints `created clip <id>` instead of `created slideshow <id>`. The CLI command structure (`agentclip slideshow ...`) is unchanged for backwards compatibility.
- `agentclip whoami --set ...` output drops the "Filed by" phrasing in favor of "X will be credited on every clip."

### Notes

- Backwards-compatible. Older API versions that don't surface the new `run_type` field parse cleanly; the CLI flag just sends an extra payload key the older API ignores.
- The narrate CLI command requires the local state store to have the clip's `write_token` cached. That's how clips are mutated in general — the credential is yours, not the platform's.

[0.3.0]: https://github.com/ericelizes1/agentclip-python/compare/v0.2.0...v0.3.0

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

[Unreleased]: https://github.com/ericelizes1/agentclip-python/compare/v0.3.1...HEAD
[0.1.0]: https://github.com/ericelizes1/agentclip-python/releases/tag/v0.1.0
