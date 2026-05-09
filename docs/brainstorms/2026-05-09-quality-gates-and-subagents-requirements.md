# Quality gates and subagents for agentclip

**Date:** 2026-05-09
**Scope:** Standard, feature-tier
**Status:** Brainstorm → ready to plan

## Problem

The agentclip skill produces clips by capturing screenshots, writing captions, and assembling slides. The captions are *the* product — they become the spoken narration, they're what makes the URL worth opening. But the agent currently writes captions from a mental model of what *should* be on screen, not from what the screenshot actually contains.

Concrete failure observed in the v0.app hero recording (clip `UisOCaH5UbO-yKcn`, 2026-05-09):

| Slide | Caption claimed | Screenshot actually showed |
|---|---|---|
| 1 | "No template picker" | "Start with a template" cards prominently visible |
| 4 | "sidebar, KPI cards, revenue chart, activity feed" | Only sidebar.tsx + kpi-cards.tsx in the rail |
| 5 | "Version one is done" | Right panel rendering placeholder, "Creating dashboard page" |

Three of five captions drifted from the pixels. The clip shipped to a public URL before the user caught it manually. The skill has voice rules and banned-phrase lists; it has nothing that pins captions to the actual image.

Secondary problem the user surfaced in the same session: even when individual captions are accurate, no one reviews the *whole script* against the established walkthrough patterns we researched (the Replit / Cursor opener shapes, the run_type voice rules). Voice consistency drift across a 5-slide clip is invisible until the rendered video is heard.

## Goals

1. Make caption-vs-screenshot drift a structural impossibility, not a discipline problem.
2. Catch whole-script issues (voice drift, off-pattern openers, banned phrases that slipped) before the clip ships.
3. Do this without bloating the skill into a multi-agent swarm — single orchestrator stays the model.
4. Make every quality gate deletable: each one earns its keep against measured drift, and we drop ones that don't.

## Non-goals

- Building an "agent that produces clips end-to-end with no human." The skill is for an existing coding agent; we add quality gates, not autonomy.
- Verification of motion / video clips. Out of scope for this brainstorm — listed below as an adjacent feature.
- Replacing the agent's primary captioning step with a subagent. Captioning is tightly coupled to the capture context; splitting it costs more than it saves (anti-pattern from the research below).

## Research grounding

The web-research pass turned up three findings that anchor the recommended shape:

1. **Anthropic's published guidance on subagents** (Claude Code docs, 2025–2026) is explicit: subagents are for *"noisy, bounded tasks where the main session only needs a summary."* The canonical positive example they give is a *reviewer agent* with a limited toolset, checklist-driven, returning compact pass/fail. Caption verification fits this shape exactly.

2. **MJ1 paper (arxiv 2603.07990, March 2026)** identifies the failure mode head-on: in multimodal judges, *visual tokens receive vanishingly small attention weights in deeper transformer layers* — the model effectively stops seeing the image by the time it scores. Fix: a structured chain that forces the verifier to enumerate visible elements **before** comparing them to the claim, decompose the caption into discrete claims, and verify each one. Reported gain: +1.7–3.8 points on multimodal benchmarks without any fine-tuning. **This is the verifier's prompt structure**, not just a recommendation.

3. **Cognition's "Don't Build Multi-Agents"** + the *Multi-Agent Trap* synthesis: 36.9% of multi-agent failures in documented production cases come from agents interpreting ambiguous instructions differently. At 95% per-step reliability, a 10-step chain runs at 59.9% end-to-end. Translation for us: keep the chain sequential and short. Adding *one* verifier subagent per slide is fine; splitting capture / caption / verify / summarize across four agents is not.

No comparable tool (Cursor, Cline, Aider, Devin) currently uses subagents for output verification — they verify code via tests, which doesn't port to caption-vs-screenshot. This is unbuilt territory in the agent-tool world; agentclip's verification problem genuinely doesn't have a prior implementation to copy.

## Approach

### Recommended

**Single orchestrator loop with two narrow subagent quality gates.** Keep the existing capture/caption/summarize flow exactly as it is; add a per-slide verifier and a one-shot script reviewer at the end.

**Per-slide caption verifier (subagent).**
- Spawned automatically from the skill *after* `slideshow_add_slide` (or before — see open question).
- Inputs: the screenshot path (raw bytes, not a description), the draft caption, and a compact rubric.
- Internally follows the MJ1 pattern, hardcoded in the verifier's system prompt:
  1. Enumerate visible UI elements (buttons, labels, status text, panels).
  2. Decompose the caption into atomic claims.
  3. Cross-check each claim against the enumeration.
  4. Emit a structured result.
- Output: `{matches: bool, mismatches: [{claim, actual}], suggestion?: str}`.
- On mismatch: the orchestrator agent rewrites the caption in its own context (not in another subagent — captioning stays in the main loop) and calls `slideshow_update_slide`.
- Bounded — no further tool calls. Cheaper model tier (Haiku-class) is sufficient.

**Whole-script reviewer (subagent).**
- Spawned once, after the final slide and before `slideshow_set_summary`.
- Inputs: the slideshow ID (it can fetch all captions itself via the agentclip API), the chosen `run_type`, and the style rubric (banned phrases, voice rules per run_type, real-walkthrough opener patterns).
- Output: `{voice_consistent: bool, banned_phrase_hits: [...], opener_shape_match: bool, suggestions: [{slide, fix}]}`.
- Orchestrator agent applies fixes via `slideshow_update_slide`, then writes the summary.
- Cheaper model tier; bounded; one round.

**Why subagents specifically (not just a smarter prompt to the main agent):**
- Fresh context — the verifier doesn't see the agent's mental model of what was *supposed* to be on screen. It sees only the image and the claim. Mental-model contamination was the root cause of the v0 drift.
- Forced structure — the MJ1 chain is hardcoded in the verifier's prompt. Enforcing the same chain in the main agent's loop is fragile (agents skip steps under pressure to make progress).
- Independent failure mode — when the verifier fails (timeout, malformed JSON), the orchestrator can decide to ship anyway with a flagged-low-confidence note. A failure inside the main agent's captioning step doesn't have that exit.

### Alternative considered: single-agent with stricter prompting

Add a step to SKILL.md that says *"After every browser_screenshot, Read the returned PNG file and write the caption strictly from what's visible."* No subagent.

- **Pro:** Zero infra. One paragraph in SKILL.md.
- **Pro:** Nothing extra to maintain.
- **Con:** It's already what the skill *implies*, and it didn't prevent the v0 drift. Discipline rules drift; structural gates don't.
- **Con:** No way to catch whole-script voice drift without another pass anyway.

**Verdict:** ship this rule *as well* (it's free), but don't expect it alone to solve the problem.

### Alternative considered: server-side verifier in the MCP

Make `slideshow_add_slide` itself reject mismatched captions by calling a verifier model from inside the agentclip API.

- **Pro:** Quality gate is structural — agents literally can't bypass it.
- **Pro:** Centralizes the verifier so every agentclip user benefits.
- **Con:** Forces the API to depend on a model provider (Anthropic / OpenAI), gain a billing relationship, and pay per call. Pushes infra cost from optional to mandatory.
- **Con:** Latency on every slide submit. Adds a new failure mode to the write path.

**Verdict:** maybe a year from now, when the verifier is well-tuned and we've decided server-side cost is worth eating. Not for v1.

### Higher-upside alternative: motion / GIF capture

The user raised this in the same conversation. v0's "watch components stream in" sequence is dramatically more compelling as a 3-second motion clip than a static frame. Playwright supports both per-segment GIFs and full-session video recording. `media_path` already accepts MP4/WebM/MOV per the skill.

Concrete shape: add `browser_record_gif(session_id, duration_ms)` MCP tool returning a `.gif` path that drops straight into `slideshow_add_slide`. Cheapest add for the biggest visual lift on certain run_types (walkthrough especially).

**Treat as a separate brainstorm.** It's an additive feature, not a quality gate. Mixing the two slows both. Documented here as a known adjacent.

## Anti-patterns to explicitly not do

Pulled from the research:
1. **Splitting captioning into a subagent.** Tightly coupled to the capture context; loses the immediate visual grounding. Keep captioning in the main loop.
2. **Parallel verifier subagents per slide.** Adds variance without value. Sequential one-by-one is fine for the slide cadence we ship at.
3. **Long chains.** Per-slide chain stays under 5 steps (capture → caption → verify → maybe-update → next). Whole-script reviewer is one extra call near the end.
4. **Multi-agent for speed.** Adding parallel captioners doesn't fix mental-model drift, it multiplies it.
5. **Verifier reading a textual description of the screenshot instead of the bytes.** Every intermediary summarization step bleeds out the visual grounding the verifier exists to enforce.

## Success criteria

This change pays off if:
- Caption-vs-screenshot drift on the *next* recorded clip drops to zero on the user's first audit (vs 3-of-5 on the v0 clip).
- Whole-script voice drift across a 5-slide clip drops to zero or near-zero per audit.
- The orchestrator agent does *not* feel meaningfully slower — verifier subagent latency stays under ~3s/slide on Haiku-tier.
- Verifier false positives (rejecting accurate captions) stay rare enough that the orchestrator isn't stuck in retry loops. Soft target: <1 false positive per clip.

## Dependencies / assumptions

- The host runtime (Claude Code, Codex, etc.) supports a Task / subagent primitive. Claude Code does (`Agent` / `Task` tool). Other hosts vary — degrade gracefully on hosts without one.
- The verifier needs the actual PNG bytes. The skill must pass the file path; the host's subagent system must support image inputs. Claude Code does.
- The model used by the verifier must be multimodal. Haiku-class is fine.
- The whole-script reviewer can fetch slides via the public API (`GET /api/v1/slideshow/<share_token>/`) — no new auth needed.

## Open questions (for planning)

1. **Verifier timing — before or after `slideshow_add_slide`?**
   - Before: never lets a bad caption hit the database; cleaner but adds latency before the slide is durable.
   - After: slide lands first, verifier runs async, orchestrator updates if needed. Faster, but a bad caption is briefly live.
   - Recommendation in plan: *after*, with `slideshow_update_slide` as the correction path. Matches existing skill pattern ("fix slides in place, don't pile on corrections").

2. **Where does the verifier live?** Three locations possible:
   - In the skill (recommended action only — host spawns subagent itself). Simplest. Zero infra in agentclip-python.
   - In agentclip-python as a CLI subcommand (`agentclip verify-caption <image> <caption>`) that the skill recommends invoking. Self-contained but requires a model API key in the user's env.
   - In the agentclip-mcp server as an MCP tool (`verify_caption(image_path, caption) → result`). Cleanest UX, same dependency cost as the CLI option.
   - Likely answer: skill-level recommendation first (free), MCP tool later if measured value warrants.

3. **Style rubric — where stored?** The verifier needs the run_type voice rules. SKILL.md has them in prose; the verifier wants them as structured rules. Generate from SKILL.md or maintain a parallel JSON/YAML rubric? Plan should resolve.

4. **Cost ceiling.** What's an acceptable cost-per-clip for the quality gates? Need a number to size the verifier model choice.

## Next-step options

- **Plan it** (recommended) — `/ce-plan` with this doc to lay out the verifier subagent integration, the script-reviewer pattern, and the SKILL.md changes in implementation order.
- **Add the visual-vet rule to SKILL.md now** as a free intermediate. Doesn't replace the verifier, but reduces drift today before the bigger work lands.
- **Spin up the motion/GIF brainstorm** as a separate doc (`/ce-brainstorm` with a fresh prompt). Adjacent feature, different shape.

## References

- Anthropic — *Create custom subagents (Claude Code docs)*: https://code.claude.com/docs/en/sub-agents
- Anthropic — *Best practices for Claude Code*: https://code.claude.com/docs/en/best-practices
- Cognition — *Don't Build Multi-Agents*: https://cognition.ai/blog/dont-build-multi-agents
- Towards Data Science — *The Multi-Agent Trap*
- *MJ1: Multimodal Judgment via Grounded Verification* (arxiv 2603.07990): https://arxiv.org/html/2603.07990
- Patronus AI — *Announcing the Industry-First Multimodal LLM-as-a-Judge*: https://www.patronus.ai/blog/announcing-the-first-multimodal-llm-as-a-judge
- *Agent-as-a-Judge: Rise of Agent Evaluation for LLMs* (arxiv 2508.02994)
- ComposioHQ — *agent-orchestrator* (open source): https://github.com/ComposioHQ/agent-orchestrator
