# agentclip skill — Tier 2 eval

End-to-end agent-loop regression coverage for the agentclip skill. The agent drives a real Playwright browser through a local fixture page, calls real MCP tools, and the test backend is a stub — production at `api.agentclip.dev` is never touched.

## What's real, what's mocked

| Component | Status |
|---|---|
| `claude -p` (the SUT) | **Real** — this is the only thing not mocked. We're testing what an actual agent does. |
| agentclip MCP server | **Real** — `mcp__agentclip__*` tools fire real Playwright + real HTTP calls. |
| Playwright browser | **Real** — opens headless Chromium, navigates, screenshots, runs JS. |
| Fixture HTML pages | **Local** — deterministic pages served from `fixtures/` on a free port. |
| `api.agentclip.dev` | **Stubbed** — `stub_api.py` mimics the backend. Records every request. Configurable failure injection. |
| OpenAI TTS / MP4 render | **Out of scope** — Tier 2 grades captions + behavior, not rendered audio. |

The judge is also `claude -p`, run separately, with structured-output validation.

## What it covers vs Tier 1

| Concern | Tier 1 (dry-run captions) | Tier 2 (full loop) |
|---|---|---|
| Run_type picked correctly | ✓ | ✓ |
| Voice landing per type | ✓ | ✓ (graded on real captions) |
| Banned phrases | ✓ | ✓ |
| Title shape | ✓ | ✓ |
| Tool order (create → add → summary) | ✗ | ✓ |
| Real share_url produced | ✗ | ✓ (cross-ref with stub transcript) |
| Annotation usage on deictic captions | ✗ | ✓ |
| Fallback on 400 (e.g. deprecated `walkthrough`) | ✗ | ✓ (stub injects the rejection) |
| Fabrication detection | ✗ | ✓ (agent self-report vs stub transcript) |

## Run

```sh
# all seeds
python tests/evals/tier2/run.py

# specific seeds
python tests/evals/tier2/run.py demo-signup-loom
```

Results land in `tests/evals/tier2/results/<seed_id>.json` plus a roll-up `_summary.json`. The `results/` dir is gitignored.

## Adding a seed

Each seed is a dict in `seeds.json`:

```json
{
  "id": "kebab-case-id",
  "user_prompt": "Demo ... at {fixture_url} like ...",
  "fixture": "signup-flow.html",
  "expected_run_type": "demo|qa|guide|bug",
  "expected_min_slides": 3,
  "expected_max_slides": 6,
  "expects_annotations": true,
  "stub_config": {
    "fail_run_type": "walkthrough"
  },
  "timeout_s": 360
}
```

- `{fixture_url}` in the prompt is interpolated to the local fixture URL at run time.
- `stub_config` accepts any public attribute name on `StubAPI` (e.g. `fail_run_type`, `fail_next_add_slide`, `fail_create_status`).

## Cost + duration

Each seed runs a full agent loop. Expect:
- **Duration**: 3–6 minutes per seed (real browser + real MCP + real Claude turns).
- **Tokens**: ~50K–100K per seed.
- **Cost**: $1–3 per seed with Sonnet, more with Opus.

Don't run per-PR. Run on releases or on a weekly cron. Tier 1 (cheap, ~$0.30/seed, ~2min total) stays per-commit.

## Known limits

- Tier 2 does not grade rendered MP4 audio quality. Captions sound the same on paper; whether the TTS pronounces "AS-level" correctly is a separate human-in-loop check.
- The fixture HTTP server and stub API both bind to `127.0.0.1` on free ports. If you have aggressive firewall rules on loopback, the agent's MCP-driven Playwright may fail to reach them.
- The agent's `claude -p` session inherits whatever skills are auto-loaded from `~/.claude/skills/`. The dominant signal is still the agentclip skill, but if you have a heavily-customized environment, your Tier 2 results may not match a clean install.
