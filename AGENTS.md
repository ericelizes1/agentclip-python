# Claude / Codex / coding-agent instructions for `agentclip-python`

This is the Python SDK + CLI + MCP server for AgentClip — published as `agentclip` on PyPI. The bundled skill at `src/agentclip/skill/SKILL.md` is what coding agents read when the user asks them to "make a clip", "show what happened", "demo this", "how do I X", or "repro the bug visually".

The deployment side (Django REST API + Next.js frontend behind agentclip.dev) lives in the sister repo: <https://github.com/ericelizes1/agentclip>.

## Dogfooding agentclip from inside this session

If you (the coding agent) want to actually use agentclip while working on this package — e.g., to capture a clip of a fix you just shipped — you need three things:

1. **The package installed in your env.** From this checkout:
   ```
   pip install -e .[browser]
   ```
   The `[browser]` extra adds Playwright, which is the only safe screenshot path (see "Never use OS screen capture" below).

2. **A session restart.** Skill files are loaded at session start. After install, the skill lands at `~/.claude/skills/agentclip/SKILL.md`. Tell the user: *"I've installed agentclip — restart this session and the skill will load."* Until they restart, the skill is invisible to you.

3. **Verify the install.** After restart:
   ```
   agentclip --version
   agentclip whoami       # (prompts to set a creator credit on first run)
   ```

To run the in-progress local build instead of the published PyPI version:

```
uvx --from /Users/<you>/code/agentclip-python agentclip <command>
```

## What the skill does

When triggered, the skill walks you through:
1. Pick a `run_type` (walkthrough / guide / bug — see SKILL.md for the trigger-phrase mapping)
2. Drive a browser through the relevant flow
3. Take **viewport-only** screenshots (NEVER full-screen — see anti-patterns)
4. Call `agentclip slideshow create` → `add` (×N) → `summary`
5. Hand back the share URL

The full rules — caption voice, banned phrases, run-type-specific guidance — are in `src/agentclip/skill/SKILL.md`. **Read it before recording anything.**

## Never use OS screen capture

When making clips, do **not** use `screencapture` (macOS), `scrot` (Linux), `gnome-screenshot`, or any OS-level capture tool. They include the IDE, terminal panes, and the user's chat with you — all of which become public when the clip ships.

Use viewport-only capture only:
- **`agentclip[browser]` (Playwright)** — the canonical path; install with `pip install agentclip[browser]`
- A browser MCP tool (Chrome / Playwright / Puppeteer) — see SKILL.md "Saving MCP screenshots to disk" for the data-URL → file recipe
- Your own scripted Playwright / Puppeteer with a fixed viewport

This isn't a stylistic preference. It's a privacy boundary.

## Useful CLI commands while developing

```
agentclip slideshow create --type walkthrough --title "..." -d "..."
agentclip slideshow add <slideshow_id> /tmp/01.png --caption "..."
agentclip slideshow summary <slideshow_id> "..."
agentclip slideshow list                    # cached write_tokens on this machine
agentclip slideshow delete <id> --yes       # use this if you upload the wrong thing
agentclip gallery add <share_token> -p 0    # feature in the home gallery (needs AGENTCLIP_ADMIN_TOKEN)
```

## Run the test suite

```
pytest
```

There aren't yet evals for the skill itself (promptfoo / DeepEval — planned). When you change SKILL.md, smoke-test it by triggering a real clip and reviewing the captions before merging.

## Coordinating with the API repo

The `run_type` vocabulary in SKILL.md must match the Django `RunType` enum at `agentclip/api/slideshows/models.py`. Current values: `walkthrough`, `guide`, `bug`. If you change the vocab here, you also need:

- `agentclip/api/slideshows/models.py` — update `RunType` choices
- `agentclip/api/slideshows/migrations/` — add a new migration that maps old values forward (see `0011_slideshow_runtype_consolidate.py` for the pattern)
- `agentclip/api/slideshows/narration.py` — update voice mapping
- `agentclip/api/slideshows/test_runtype.py` + `test_narration_bookends.py` — update assertions
- `agentclip/web/lib/api-schema.json` + `api-types.ts` — regen via `pnpm gen:api` after the API change
- `src/agentclip/cli.py` — update `--type` help text

Ship API changes first (with both old and new accepted, ideally), then the SKILL.md change. Otherwise the skill tells the agent to use values the API rejects.
