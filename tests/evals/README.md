# agentclip skill evals

Regression coverage for the agentclip SKILL.md. Catches caption drift, run_type misclassification, banned-phrase slips, and voice inconsistency without driving a real browser.

## How it works

For each seed in `seeds.json`:

1. **SUT call** — `claude -p` is given the seed's user prompt, a synthetic capture trace (frame + interesting moment per slide), and the full SKILL.md as context. It returns a structured JSON object: `{run_type, title, description, captions[], summary}`.
2. **Judge call** — `claude -p` grades that output against the per-run-type rubric in `rubrics.json`. Returns `{overall_score, verdict, criteria[], banned_phrases_found[], cringe_caption_indices[], notes}`.

No API key needed. `claude -p` uses Claude Code session auth. No real browser, no real clip published — this is the cheap caption-quality tier.

## Run

```sh
# all seeds
python tests/evals/run.py

# specific seeds
python tests/evals/run.py demo-signup-flow bug-503-signup
```

Output lands in `tests/evals/results/<seed_id>.json` plus a roll-up `_summary.json`. The `results/` dir is gitignored.

## What's covered

| seed | run_type | tests |
|---|---|---|
| `demo-signup-flow` | demo | presenter voice, present-tense captions, lands non-obvious detail per slide |
| `qa-checkout-flow` | qa | checklist voice, per-slide verdict, summary pass/fail counts |
| `guide-cloudflare-radar` | guide | analytical voice, lands a takeaway, specifics over generalities |
| `bug-503-signup` | bug | terse factual voice, establish-reproduce-prove arc, summary states outcome |

## What's not covered (yet)

- **Tool-use behavior** — the SUT runs in pure-text mode. To test "did Claude pick the right browser tool / handle MCP-tool failures cleanly" you need a tier-2 harness with real tools. Tracked separately.
- **Render fidelity** — TTS pronunciation, slide pacing, video stitch quality. Those need the rendered MP4, not just the captions.
- **Real-world spine quality** — the synthetic capture traces in `seeds.json` pre-suggest what's interesting per slide. A real run has noisier input.

## Adding a seed

Add an entry to `seeds.json`:

```json
{
  "id": "kebab-case-id",
  "expected_run_type": "demo|qa|guide|bug",
  "user_prompt": "what the user typed",
  "audience": "who will watch this",
  "slides": [
    {"frame": "what was captured", "moment": "what is interesting about it"},
    ...
  ]
}
```

Two-to-six slides is the sweet spot. The `moment` field is what would have caught your eye while running — give the SUT enough to write a real caption from.

## Tweaking the rubric

`rubrics.json` has a `_shared` block (criteria that apply to every run_type) and per-type blocks with a `voice_definition` plus `extra_criteria`. Criteria weights are unnormalized — the judge weight-averages them.

When you change a rubric, re-run the relevant seeds and inspect the judge's `criteria[]` reasons. If a criterion keeps tripping a real-looking caption, the rubric is probably stricter than the skill rules — tighten the skill or loosen the rubric, not both.

## Cost

Each seed = 2 `claude -p` calls (SUT + judge). Each call sends ~12K-15K tokens (SKILL.md + prompt) and gets back ~1K tokens. With Anthropic's prompt-cache TTL of 5 minutes, back-to-back runs should reuse the cached SKILL.md block. Budget roughly $0.05-$0.20 per seed.

## Known limits

- `claude -p` JSON output sometimes wraps the result in code fences depending on model mood. `run.py` strips them defensively.
- The harness has no retry on transient failures yet. Re-run the failing seed by name if you see a `subprocess.CalledProcessError`.
- The SUT's choice of run_type is graded but not enforced — when it picks wrong, the rest of the grading still proceeds against the seed's expected type. The `chose_wrong_run_type` annotation (`*` in the summary) is the signal.
