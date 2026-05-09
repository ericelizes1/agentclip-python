---
title: "feat: Quality gates — caption verifier + script reviewer subagents"
type: feat
status: active
date: 2026-05-09
origin: docs/brainstorms/2026-05-09-quality-gates-and-subagents-requirements.md
---

# feat: Quality gates — caption verifier + script reviewer subagents

## Overview

Add two narrow quality-gate subagents to the agentclip skill — a per-slide caption verifier and a one-shot whole-script reviewer — to make caption-vs-screenshot drift a structural impossibility instead of a discipline problem. The verifier runs after every `slideshow_add_slide` and forces correction via `slideshow_update_slide` when the caption drifts from the pixels. The reviewer runs once before `slideshow_set_summary` and catches voice / banned-phrase / opener-shape drift across the whole clip. Both are invoked by the host agent through its native subagent primitive (Claude Code's `Task` tool, etc.) — agentclip itself ships no new Python code, no MCP tools, and takes on no model-API dependency.

This plan is intentionally documentation-heavy: the architectural decision (made in the brainstorm) was *not* to put the verifier in agentclip-python's MCP server, because that would force a model-API billing relationship and mandatory per-call latency on every user. The skill describes the pattern; the host agent runs it.

---

## Problem Frame

The agentclip skill produces clips by capturing screenshots, writing captions, and assembling slides. Captions are the product — they become spoken narration. The skill currently has voice rules and banned-phrase lists but no structural enforcement that captions describe the actual screenshot.

Concrete failure observed in clip `UisOCaH5UbO-yKcn` (v0.app hero, 2026-05-09): three of five captions drifted from what was pixel-visible (claimed "no template picker" while one was on screen; claimed four components when only two were in the rail; claimed "version one is done" while the right panel still rendered "Creating dashboard page"). The clip shipped to a public URL before the user caught the drift in manual audit.

The brainstorm grounded the response in three external findings (carried forward — see origin):

1. Anthropic's published subagent guidance: subagents are for *"noisy, bounded tasks where the main session only needs a summary"* — reviewer agents are the canonical positive case.
2. MJ1 paper (arxiv 2603.07990, March 2026): multimodal judges fail because *"visual tokens receive vanishingly small attention weights in deeper transformer layers"* — fix is a structured chain (enumerate visible elements first, decompose claims, verify each, score). +1.7–3.8 benchmark points without fine-tuning.
3. Cognition's *Don't Build Multi-Agents*: 36.9% of multi-agent failures come from agents interpreting ambiguous instructions differently. Keep chains sequential and short.

---

## Requirements Trace

- R1. Per-slide caption-vs-screenshot drift on the next recorded clip drops to zero on the user's first audit (vs 3-of-5 on the v0 clip). *(see origin Success criteria)*
- R2. Whole-script voice drift across a 5-slide clip drops to zero or near-zero per audit. *(see origin Success criteria)*
- R3. The orchestrator agent does not feel meaningfully slower — verifier subagent latency stays under ~3s/slide on Haiku-tier. *(see origin Success criteria)*
- R4. Verifier false positives stay rare enough that the orchestrator isn't stuck in retry loops (<1 false positive per clip). *(see origin Success criteria)*
- R5. agentclip-python takes on no new mandatory dependency on a model API provider — quality gates run in the host agent's existing model context. *(see origin Approach: "alternative considered: server-side verifier" was rejected)*
- R6. The captioning step itself stays in the main agent loop, not in a subagent — visual grounding is preserved by tight coupling to the capture context. *(see origin Anti-patterns to explicitly not do)*

---

## Scope Boundaries

- This plan does not add server-side verification to the agentclip MCP server. Slide submission stays unauthenticated-content-wise; the verifier runs in the host agent's loop.
- This plan does not add motion / GIF / video capture support. Adjacent and complementary, but a separate brainstorm. *(see origin Higher-upside alternative)*
- This plan does not build an automated eval harness (promptfoo / DeepEval) for the verifier itself. The verifier ships with manual smoke testing; an eval suite is a separate plan once we have ground-truth data from real usage.
- This plan does not generalize to non-Claude-Code hosts. Codex / Gemini / Pi compatibility is acknowledged in the skill (each host has its own subagent primitive) but the recipes optimize for Claude Code's `Task` tool, where the user actually runs agentclip today.

### Deferred to Follow-Up Work

- Promptfoo eval suite for the caption verifier with a set of (image, caption, expected_match) cases — separate plan, once we have 10+ real examples to ground the rubric.
- Motion / GIF capture (`browser_record_gif` MCP tool) — separate brainstorm.
- Per-host adaptation of the subagent recipes for Codex / Gemini / Pi — opportunistic, when a real user on those hosts asks.

---

## Context & Research

### Relevant Code and Patterns

- `src/agentclip/skill/SKILL.md` — the file most of this plan modifies. Already has Step 0 (spine + run_type), Step 1 (create), Step 2 (screenshots), Step 3 (captions), Step 4 (fix in place), Step 5 (summary), Step 6 (handoff). New rules slot into Step 3 (visual-vet) and as new Step 3.5 (verifier) and Step 5b (script reviewer).
- `src/agentclip/skill/__init__.py` — bundling pattern for the skill module.
- `src/agentclip/setup.py` `_install_skill()` — copies SKILL.md into `~/.claude/skills/agentclip/`. Idempotent. No code change needed; the new SKILL.md ships through this same path.
- `src/agentclip/mcp_server.py` — confirmed: no new tools required for this plan. The brainstorm explicitly rejected the server-side verifier alternative.
- `CHANGELOG.md` — current version 0.6.1 (post async/threading fix). Bump to 0.7.0 for this plan; new behavior is meaningfully larger than a patch.
- `CLAUDE.md` / `AGENTS.md` — both currently point at the dogfood loop. Add a section explaining the new quality gates and the host's responsibility to spawn the verifier/reviewer subagents.

### Institutional Learnings

- No `docs/solutions/` corpus in this repo yet — nothing to pull. This plan's pattern (skill-prescribed subagent recipe, no server-side dependency) is itself a candidate for a future `docs/solutions/` entry once it's proven on a second clip.

### External References

All carried from origin Sources & References — full URLs there. The three load-bearing ones:
- *Create custom subagents (Claude Code Docs)* — establishes the Task subagent shape, fresh context, summary-back semantics.
- *MJ1: Multimodal Judgment via Grounded Verification* (arxiv 2603.07990) — directly informs the verifier's prompt structure (the enumerate-first chain).
- *Don't Build Multi-Agents* (Cognition) — anti-patterns that constrain the recipe.

---

## Key Technical Decisions

- **Verifier and reviewer live in the SKILL.md as recipes the host agent invokes — not as new MCP tools or new Python code.** Keeps agentclip-python free of model-API dependencies and per-call costs. The cost of "host has to spawn a subagent" is already paid by Claude Code's existing `Task` tool. *(see origin Approach: alternative considered)*
- **Verifier fires *after* `slideshow_add_slide`, not before.** Matches the existing skill convention ("fix slides in place, don't pile on corrections" — Step 4). Slide lands first; if the verifier rejects, the orchestrator calls `slideshow_update_slide`. Briefly-live bad caption is acceptable; pre-write latency is not. *(see origin Open question 1)*
- **Verifier prompt is hardcoded in SKILL.md** as a fenced block the host copies into the subagent's system prompt. Single source of truth; no separate file to drift. The chain (enumerate → decompose → cross-check → emit JSON) follows MJ1 exactly. *(see origin Approach: per-slide caption verifier)*
- **Script reviewer reads the full slide list via the public API** (`GET /api/v1/slideshow/<share_token>/`) — no new auth, no extra orchestrator state. *(see origin Dependencies / assumptions)*
- **Style rubric is the existing SKILL.md prose, not a parallel JSON.** The reviewer's prompt instructs it to load SKILL.md from `~/.claude/skills/agentclip/SKILL.md` and apply the per-run_type rules verbatim. Avoids JSON-vs-prose drift. *(resolves origin Open question 3)*
- **No automatic retry loop on verifier rejection.** The orchestrator gets the suggested correction, applies it once via `slideshow_update_slide`, and moves on. If the corrected caption is *also* wrong, that's a known limitation called out in the skill — better than a stuck loop. Aligns with R4 (false-positive ceiling).
- **Cost ceiling deferred** to first-pass observation rather than pre-spec. *(resolves origin Open question 4 — explicitly defer)*

---

## Open Questions

### Resolved During Planning

- *When does the verifier fire?* After `slideshow_add_slide`, fixing via `slideshow_update_slide` on rejection. (See decision above.)
- *Where does the verifier live?* Skill-level recipe; no new code in agentclip-python. (See decision above.)
- *Style rubric source?* SKILL.md prose, loaded by the reviewer subagent at run time. (See decision above.)

### Deferred to Implementation

- Exact wording of the verifier system prompt — the brainstorm sketches the chain; the implementer should iterate on the prompt against the v0.app re-recording (U4) until the verifier catches the same three drift cases the user caught manually.
- Exact JSON shape returned by the verifier — directional shape is documented in the technical design below; the implementer should pick the field names that integrate cleanest with how the orchestrator consumes them.
- Whether to add a one-line `Execution note` in the skill recommending the host pre-load `Task` subagent schemas at the start of a clip (Claude Code-specific deferred-tool quirk). Decide once we test against the live tool list.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

**Per-slide caption verifier — invocation flow:**

```
After every slideshow_add_slide call, the orchestrator agent spawns a
subagent (Task tool in Claude Code) with:

  system_prompt: <CAPTION_VERIFIER_PROMPT from SKILL.md>
  inputs:
    - image: file at the path returned by browser_screenshot
    - caption: the string just sent to slideshow_add_slide
    - run_type: walkthrough | guide | bug

The verifier subagent follows the MJ1 chain:
  1. Enumerate visible UI elements (concrete, not interpretive)
  2. Decompose caption into atomic claims
  3. Mark each claim ✓ supported / ✗ unsupported, with evidence
  4. Emit:
      {
        "matches": bool,
        "claims": [{ "text": str, "supported": bool, "evidence": str }],
        "suggested_caption": str | null
      }

On matches=true: orchestrator continues to next slide.
On matches=false:
  orchestrator calls slideshow_update_slide(slide_position, caption=suggested_caption)
  one retry max; if the verifier rejects the corrected caption, ship anyway
  and log a "low-confidence caption" note in the orchestrator's chat output.
```

**Whole-script reviewer — invocation flow:**

```
After the final slideshow_add_slide, before slideshow_set_summary:

  The orchestrator agent spawns a subagent with:

    system_prompt: <SCRIPT_REVIEWER_PROMPT from SKILL.md>
    inputs:
      - slideshow_id (the reviewer fetches captions itself via the public API)
      - run_type
      - the SKILL.md path on disk (~/.claude/skills/agentclip/SKILL.md)

  The reviewer applies the run_type voice rules from SKILL.md and emits:

    {
      "voice_consistent": bool,
      "banned_phrase_hits": [{ "slide": int, "phrase": str, "fix": str }],
      "opener_shape_match": bool,  // does description follow the 2-4-sentence rule
      "spine_drift": [{ "slide": int, "issue": str, "fix": str }],
      "summary_suggestion": str | null  // optional pre-cooked summary in voice
    }

  Orchestrator applies fixes via slideshow_update_slide for each finding,
  uses summary_suggestion (if present) as the input to slideshow_set_summary,
  and ships.
```

**What does NOT change:**

```
- agentclip-python source code (no new MCP tools, no new CLI commands)
- The existing slideshow_* and browser_* MCP tools (untouched)
- The agentclip API / database schema
```

---

## Implementation Units

- [ ] U1. **SKILL.md: visual-vet rule + verifier and reviewer recipes**

**Goal:** Add three new sections to the bundled skill that direct host agents to (a) read each screenshot before captioning, (b) spawn a caption verifier subagent after every `slideshow_add_slide`, and (c) spawn a whole-script reviewer subagent before `slideshow_set_summary`. All three include hardcoded prompt blocks the host copies into the subagent.

**Requirements:** R1, R2, R5, R6

**Dependencies:** None — first unit.

**Files:**
- Modify: `src/agentclip/skill/SKILL.md`

**Approach:**
- Insert visual-vet rule at the top of Step 3 ("Write captions in the right voice"), one paragraph: *"After every `browser_screenshot`, Read the returned PNG path before writing the caption. If the caption mentions something not visible in the image, rewrite it. Mental-model captions cause structural drift — the screenshot is the source of truth."* Free intermediate that helps even if the verifier isn't spawned.
- Insert new **Step 3.5: Verify the caption** after Step 3 and before the existing Step 4. Three subsections:
  1. **When and how to spawn** — instructs the host agent to invoke a verifier subagent (Claude Code: `Task` tool with general-purpose subagent_type and a custom system prompt; other hosts: equivalent primitive). Fires after every `slideshow_add_slide` whose caption claims something visual.
  2. **The verifier system prompt** — fenced block, hardcoded. Follows the MJ1 chain (enumerate visible elements first, decompose claims, cross-check, emit structured JSON). Prompt instructs the subagent to read the image at the provided path before doing anything else.
  3. **Acting on the result** — `matches=true` → next slide. `matches=false` → call `slideshow_update_slide(slide_position, caption=suggested_caption)`, then move on. Single retry max, no infinite loops.
- Insert new **Step 5b: Review the whole script** between existing Steps 5 and 6. Same three-subsection structure as 3.5: when/how to spawn, the reviewer system prompt (covers voice consistency, banned phrases, opener-shape, spine drift, optional summary suggestion), and how to apply findings via `slideshow_update_slide`.
- Add a paragraph under "Anti-patterns" reinforcing: don't put captioning itself in a subagent (loses visual grounding); don't run verifiers in parallel; don't feed the verifier a text description instead of the bytes.
- Update the "Tool reference" table footer with a note that subagent invocation is the host's responsibility, not an agentclip-shipped tool.

**Patterns to follow:**
- Existing SKILL.md section structure (numbered Step N: Title, then prose with examples). New sections match style.
- Existing fenced examples in the skill (e.g., the worked-example Python blocks) — verifier and reviewer prompts use the same fenced-code convention.

**Test scenarios:**
- *Manual smoke (covered by U4):* re-record the v0.app walkthrough; verify the verifier subagent rejects the same three drifted captions the user caught by hand on `UisOCaH5UbO-yKcn`.
- *Manual smoke (covered by U4):* re-record a clip with intentionally consistent captions; verify the verifier returns `matches=true` for all of them with no false positives.
- *Manual smoke (covered by U4):* introduce a banned phrase ("seamless", "robust") in one slide's caption; verify the script reviewer flags it.
- *Test expectation: none for the SKILL.md file itself* — pytest doesn't cover prose. Skill behavior is validated through U4.

**Verification:**
- Both new sections render as readable Markdown when viewed in the GitHub web UI.
- The verifier and reviewer prompt blocks are fenced and copy-pasteable as-is into a Task subagent's `prompt` field.
- The skill still reads coherently top-to-bottom — new sections don't disrupt the existing flow.

---

- [ ] U2. **CHANGELOG entry + version bump to 0.7.0**

**Goal:** Capture the new skill behavior in the changelog and bump the package version. Even though no Python changes ship, the skill is the user-facing surface and bundled with the package.

**Requirements:** Indirect — supports R1/R2 by communicating the new pattern to users on upgrade.

**Dependencies:** U1 (the changelog entry describes what U1 ships).

**Files:**
- Modify: `pyproject.toml` (version `0.6.1` → `0.7.0`)
- Modify: `CHANGELOG.md` (new `## [0.7.0] - 2026-05-09` section)

**Approach:**
- Bump to **0.7.0** (minor) — new user-facing behavior in the bundled skill, not just a fix. Calls out: visual-vet rule, verifier subagent recipe, script reviewer subagent recipe, deliberate non-decision to NOT build server-side verification.
- CHANGELOG entry follows the established voice in the file (problem → fix, with quotable specifics). Cite the v0 clip's three-of-five drift as the motivating evidence so future readers understand why this landed.

**Patterns to follow:**
- Existing 0.6.1 / 0.6.0 / 0.5.0 changelog entries — same voice, same structure (Added / Changed / Fixed subsections).

**Test scenarios:**
- *Test expectation: none — pyproject + changelog are config and prose.*

**Verification:**
- `agentclip version` after `uv tool install --reinstall --from /Users/ericelizes/code/agentclip-python agentclip` reports `0.7.0`.
- The CHANGELOG entry renders correctly on GitHub.

---

- [ ] U3. **CLAUDE.md / AGENTS.md updates: document the new quality-gate pattern for dogfooders**

**Goal:** Tell future agents working in either repo (agentclip-python or agentclip) that the skill now expects them to spawn caption-verifier and script-reviewer subagents during clip recording, with a one-line example of how to do it from Claude Code.

**Requirements:** R1, R2 (extends the dogfooding loop to actually use the gates).

**Dependencies:** U1 (the docs reference the new SKILL.md sections).

**Files:**
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md` (mirror — `cp CLAUDE.md AGENTS.md` is the existing pattern in this repo)

**Approach:**
- Add a new **"When recording clips, spawn the quality-gate subagents"** subsection under the existing "Dogfooding agentclip from inside this session" block. Three sentences max. Point at SKILL.md Steps 3.5 and 5b for the actual recipe.
- One concrete callout: *"If you skip these, you'll ship a clip with caption drift on the first audit — see commit `60cf540`'s clip log for evidence."*

**Patterns to follow:**
- Existing CLAUDE.md style — short, dense, points at SKILL.md / source rather than restating it.

**Test scenarios:**
- *Test expectation: none — pure docs.*

**Verification:**
- `diff CLAUDE.md AGENTS.md` returns empty (mirror is exact).
- The new subsection points at the right SKILL.md anchors.

---

- [ ] U4. **Verification: re-record the v0.app walkthrough with the gates and audit**

**Goal:** Empirical proof the gates work. Record a fresh v0.app walkthrough using the new SKILL.md, confirm the verifier catches drift on at least one slide, confirm the script reviewer flags the run-type voice issues that would have slipped past the captioning agent, and confirm the final clip is shippable on first audit.

**Requirements:** R1, R2, R3, R4

**Dependencies:** U1 (skill sections must exist), U2 (version installed), U3 (recommended but not blocking).

**Files:**
- No file changes. This unit is execution against the live API.
- Optional artifact: append a short "Verification log" section to this plan after the run, capturing the share URL, what the verifier caught, and any false positives.

**Approach:**
- Restart Claude Code so the new skill loads.
- Run the same v0.app walkthrough flow as the prior recording (`/agentclip` → drive v0 → assemble).
- Force the orchestrator to use Steps 3.5 and 5b — spawn verifier + reviewer subagents as described.
- Audit each caption against its screenshot manually, the same way the user audited `UisOCaH5UbO-yKcn`.
- Confirm: zero drift on first audit, verifier latency reasonable (<3s/slide), no false-positive retry loops.

**Execution note:** This is the empirical test of the whole plan — treat it as the single load-bearing acceptance criterion. If the verifier doesn't catch the v0 drift cases, iterate the prompt in U1 before declaring done.

**Test scenarios:**
- *Happy path:* fresh recording produces 5 slides with all captions accurate to their screenshots; manual audit finds zero issues.
- *Verifier-catches-drift:* deliberately seed a wrong-by-one-detail caption (e.g., claim "no template picker" when one is on screen); verifier flags it; orchestrator updates the slide; second-pass audit finds the corrected caption matches.
- *Reviewer-catches-banned-phrase:* deliberately include "seamless" or "robust" in one caption; reviewer flags it before `set_summary`; orchestrator updates the slide.
- *No false-positive loop:* a caption that's correct doesn't get flagged twice or loop.

**Verification:**
- A new clip URL exists, audited clean on first read.
- Verifier and reviewer findings (if any) are logged in this plan's verification section so future runs can compare.
- If the gates don't catch the seeded drift cases, U1 is reopened and re-iterated before this plan ships.

---

## System-Wide Impact

- **Interaction graph:** New subagent spawn points sit between existing skill steps. No change to MCP tool surface, no change to API contract, no change to the agentclip database schema.
- **Error propagation:** Verifier or reviewer subagent failures (timeout, malformed JSON, host doesn't support subagents) MUST degrade gracefully — the orchestrator should ship the clip with a one-line note "verification skipped: <reason>" rather than block. Anti-pattern: blocking clip creation on a quality gate that the host can't run.
- **State lifecycle risks:** Brief window where a wrong caption is live before the verifier corrects it. Acceptable per Key Technical Decisions. The clip page renders the latest caption; the share URL doesn't change.
- **API surface parity:** None — agentclip-python and agentclip's API are unchanged.
- **Integration coverage:** The verifier needs the actual PNG bytes, not a description. Pin this in the SKILL.md verifier prompt explicitly. (If the host's subagent system doesn't accept image inputs, the recipe falls back to "skip verification with note" rather than feeding it text.)
- **Unchanged invariants:** All existing slideshow_* and browser_* MCP tools work identically. The CLI surface (`agentclip slideshow create / add / summary / list / delete`) is unchanged. `pip install agentclip` setup behavior unchanged. CHANGELOG voice unchanged.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Host doesn't support subagents (Codex edit modes, future hosts) | Skill recipe degrades gracefully — orchestrator notes "verification skipped" and ships. R5 holds: no agentclip-side dependency. |
| Verifier prompt doesn't catch the v0 drift cases on first iteration | U4 is the explicit empirical test. If the gate misses, iterate U1's prompt before shipping the package. |
| Verifier flags accurate captions (false positives) and the orchestrator gets stuck retrying | Single-retry max in the recipe (Key Technical Decisions). After one correction attempt, ship and log "low-confidence" — never loop. |
| Reviewer over-edits voice in ways that lose the agent's authorial choices | Reviewer's prompt makes voice changes only when a specific banned-phrase/run-type rule is violated, not for stylistic taste. Plus orchestrator applies fixes via `slideshow_update_slide` — anything obviously wrong, the user can re-edit via the existing edit URL. |
| Verifier latency exceeds 3s/slide and visibly slows recording | R3 acceptance — measure during U4. If too slow, swap to a faster model tier in the recipe (Haiku → Haiku-mini equivalents) or run the verifier async / batch at end. Decision deferred to post-U4 measurement. |
| Skill bloat — SKILL.md is already long; adding two new sections + prompt blocks could push past readability | Sections are concrete and load-bearing. If the file genuinely becomes unreadable, future plan can extract the verifier and reviewer prompts to sibling files in `src/agentclip/skill/` and reference them from SKILL.md. Not in scope for this plan. |

---

## Documentation / Operational Notes

- The `agentclip install-skill --force` command (existing) is what users run to refresh the bundled skill after upgrading. Mention this in the CHANGELOG so users know to do it.
- The auto-MCP-registration from 0.6.0 still applies — `pip install agentclip` followed by `agentclip install-mcp` followed by a Claude Code restart is the full upgrade path.
- No DB migrations, no API schema changes, no Fly.io secrets to rotate. Pure SDK release.

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-05-09-quality-gates-and-subagents-requirements.md](../brainstorms/2026-05-09-quality-gates-and-subagents-requirements.md)
- Related code: `src/agentclip/skill/SKILL.md`, `src/agentclip/setup.py` (`_install_skill`), `src/agentclip/mcp_server.py` (no changes, but the architectural decision to *not* modify it is load-bearing).
- Related prior commits: `60cf540` (the v0.app clip with 3-of-5 drift, motivating evidence), `cb1349d` (auto-MCP-registration, the install path users follow), `206c43e` (lazy Chromium / `[browser]` fold-in, sets the precedent for "ship features as defaults, not extras").
- External docs: see origin Sources & References for the full list — the three load-bearing ones are Anthropic's subagent docs, the MJ1 paper, and Cognition's *Don't Build Multi-Agents*.
