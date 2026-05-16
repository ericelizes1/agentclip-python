"""Eval harness for the agentclip skill.

Runs each seed through Claude via `claude -p` with the current SKILL.md
appended as a system prompt, captures structured output, then grades it
with a second `claude -p` call against the per-run-type rubric.

No API key needed -- `claude -p` uses the Claude Code session auth.

Run:
    python tests/evals/run.py              # all seeds
    python tests/evals/run.py demo-signup-flow qa-checkout-flow
    python tests/evals/run.py --judge-only results/  # re-grade saved outputs

Output:
    tests/evals/results/<seed_id>.json     # full trace per seed
    tests/evals/results/_summary.json      # roll-up scores
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

EVALS_DIR = Path(__file__).parent
SKILL_PATH = EVALS_DIR.parent.parent / 'src' / 'agentclip' / 'skill' / 'SKILL.md'
RESULTS_DIR = EVALS_DIR / 'results'

SUT_JSON_SCHEMA = {
    'type': 'object',
    'properties': {
        # Only the four canonical run_types are allowed. walkthrough was
        # transitionally accepted during the taxonomy switch but is now
        # rejected at schema level -- a SUT that still files walkthrough
        # is using stale skill guidance and should fail the eval.
        'run_type': {'type': 'string', 'enum': ['demo', 'qa', 'guide', 'bug']},
        'title': {'type': 'string'},
        'description': {'type': 'string'},
        'captions': {'type': 'array', 'items': {'type': 'string'}},
        'summary': {'type': 'string'},
    },
    'required': ['run_type', 'title', 'description', 'captions', 'summary'],
}

JUDGE_JSON_SCHEMA = {
    'type': 'object',
    'properties': {
        'overall_score': {'type': 'number'},
        'verdict': {'type': 'string', 'enum': ['pass', 'borderline', 'fail']},
        'criteria': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'score': {'type': 'number'},
                    'reason': {'type': 'string'},
                },
                'required': ['name', 'score', 'reason'],
            },
        },
        'banned_phrases_found': {'type': 'array', 'items': {'type': 'string'}},
        'cringe_caption_indices': {'type': 'array', 'items': {'type': 'integer'}},
        'notes': {'type': 'string'},
    },
    'required': ['overall_score', 'verdict', 'criteria', 'banned_phrases_found', 'notes'],
}


def load_seeds() -> list[dict]:
    return json.loads((EVALS_DIR / 'seeds.json').read_text())


def load_rubrics() -> dict:
    return json.loads((EVALS_DIR / 'rubrics.json').read_text())


def load_skill() -> str:
    return SKILL_PATH.read_text()


def build_sut_prompt(seed: dict, skill_text: str) -> str:
    """Prompt that asks Claude to produce the structured fields a real
    agentclip clip would have, following the skill's rules. No tool use
    -- the agent is being told what was captured."""
    slides_block = '\n'.join(
        f'Slide {i + 1}: {s["frame"]}\n  Interesting moment: {s["moment"]}'
        for i, s in enumerate(seed['slides'])
    )
    return f"""You are following the agentclip skill (full text below). The user has just asked you:

> {seed['user_prompt']}

You already drove the browser and captured these moments. Your job now is to produce the title, description, captions, and summary that the agentclip skill rules require. Pick the run_type the skill's trigger-phrase mapping points to.

## Captured moments
{slides_block}

## Audience for this clip
{seed['audience']}

## The skill
{skill_text}

---

Produce a single JSON object matching the schema. Output only the JSON. Do not include any prose, explanation, or code fences. Captions array length must match the number of captured moments above ({len(seed['slides'])} captions)."""


def build_judge_prompt(seed: dict, sut_output: dict, rubric: dict, shared: dict) -> str:
    """Prompt that asks Claude to grade the SUT output against the rubric."""
    captions_block = '\n'.join(
        f'  {i + 1}. {c}' for i, c in enumerate(sut_output.get('captions', []))
    )
    criteria = shared['criteria'] + rubric.get('extra_criteria', [])
    criteria_block = '\n'.join(
        f'- **{c["name"]}** (weight {c["weight"]}): {c["definition"]}' for c in criteria
    )
    banned = ', '.join(f'"{p}"' for p in shared['banned_phrases'])
    return f"""You are a strict reviewer of AgentClip clip content. Grade the following clip honestly against the per-run-type rubric. Cringeworthy AI-presenter slop should fail. Tight, specific, voice-consistent work should pass.

## Expected run_type
{seed['expected_run_type']}

## Voice definition for {seed['expected_run_type']}
{rubric['voice_definition']}

## Rubric criteria
{criteria_block}

## Banned phrases (any type, case-insensitive substring)
{banned}

## Clip to grade
- **chose_run_type:** {sut_output.get('run_type', '<missing>')}
- **title:** {sut_output.get('title', '<missing>')}
- **description:** {sut_output.get('description', '<missing>')}
- **captions:**
{captions_block}
- **summary:** {sut_output.get('summary', '<missing>')}

## Grading rules
- For each criterion, give a score 0.0 to 1.0 and a one-sentence reason.
- List every banned phrase you find (exact substring matches).
- List the indices (0-based) of captions that read as AI cringe or court-reporter past-tense narration.
- overall_score is the weight-averaged criterion score.
- verdict: "pass" if overall_score >= 0.80 and zero banned phrases and run_type matches; "fail" if overall_score < 0.60 or any banned phrase; otherwise "borderline".

Output only the JSON object matching the schema. No prose, no code fences."""


def claude_p(prompt: str, schema: dict, model: str | None, timeout: int = 240) -> tuple[dict, dict]:
    """Invoke `claude -p` with a JSON schema and return (parsed_output, envelope).

    Uses --disable-slash-commands so auto-loaded skills don't double-load
    SKILL.md (the eval supplies it explicitly), and
    --exclude-dynamic-system-prompt-sections to keep prompt-cache reuse
    high across seeds. OAuth is preserved (no API key needed).

    Raises subprocess.CalledProcessError on non-zero exit, or RuntimeError
    if claude returned is_error.
    """
    cmd = [
        'claude',
        '-p',
        '--disable-slash-commands',
        '--exclude-dynamic-system-prompt-sections',
        '--output-format',
        'json',
        '--json-schema',
        json.dumps(schema),
        '--no-session-persistence',
    ]
    if model:
        cmd += ['--model', model]
    cmd.append(prompt)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True)
    envelope = json.loads(proc.stdout)
    # With --json-schema the validated object lives in `structured_output`.
    # If schema validation fails, claude returns is_error: true and the
    # raw text in `result` for debugging.
    if envelope.get('is_error'):
        raise RuntimeError(f'claude -p reported error: {envelope.get("result", envelope)[:500]}')
    parsed = envelope.get('structured_output')
    if parsed is None:
        # Fall back to parsing the text result -- some claude versions don't
        # populate structured_output even with --json-schema.
        text = envelope.get('result', '').strip()
        if text.startswith('```'):
            text = '\n'.join(ln for ln in text.splitlines() if not ln.startswith('```')).strip()
        if not text:
            raise RuntimeError(
                f'claude -p returned no structured_output and no result text. '
                f'envelope keys: {sorted(envelope.keys())}'
            )
        parsed = json.loads(text)
    return parsed, envelope


CLAUDE_ERRORS = (
    subprocess.CalledProcessError,
    subprocess.TimeoutExpired,
    json.JSONDecodeError,
    RuntimeError,
)


def run_seed(
    seed: dict, skill_text: str, rubrics: dict, sut_model: str | None, judge_model: str | None
) -> dict:
    start = time.time()
    sut_prompt = build_sut_prompt(seed, skill_text)
    try:
        sut_output, _ = claude_p(sut_prompt, SUT_JSON_SCHEMA, model=sut_model, timeout=300)
    except CLAUDE_ERRORS as e:
        return {
            'seed_id': seed['id'],
            'error': f'SUT call failed: {type(e).__name__}: {e}',
            'duration_s': round(time.time() - start, 1),
        }

    rubric_key = seed['expected_run_type']
    rubric = rubrics.get(rubric_key)
    shared = rubrics['_shared']
    if rubric is None:
        return {
            'seed_id': seed['id'],
            'error': f'No rubric for run_type {rubric_key!r}',
            'sut_output': sut_output,
        }

    judge_prompt = build_judge_prompt(seed, sut_output, rubric, shared)
    try:
        judge_output, _ = claude_p(judge_prompt, JUDGE_JSON_SCHEMA, model=judge_model, timeout=180)
    except CLAUDE_ERRORS as e:
        return {
            'seed_id': seed['id'],
            'sut_output': sut_output,
            'error': f'Judge call failed: {type(e).__name__}: {e}',
            'duration_s': round(time.time() - start, 1),
        }

    return {
        'seed_id': seed['id'],
        'expected_run_type': seed['expected_run_type'],
        'chose_run_type': sut_output.get('run_type'),
        'run_type_match': sut_output.get('run_type') == seed['expected_run_type'],
        'sut_output': sut_output,
        'judge': judge_output,
        'duration_s': round(time.time() - start, 1),
    }


def write_result(result: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f'{result["seed_id"]}.json'
    out.write_text(json.dumps(result, indent=2) + '\n')
    return out


def print_summary(results: list[dict]) -> None:
    print()
    print('=' * 70)
    print('EVAL SUMMARY')
    print('=' * 70)
    print(f'{"seed_id":<30} {"type":<10} {"score":<8} {"verdict":<12} {"banned"}')
    print('-' * 70)
    pass_count = 0
    fail_count = 0
    border_count = 0
    for r in results:
        seed = r['seed_id']
        if 'error' in r:
            print(f'{seed:<30} {"-":<10} {"ERROR":<8} {r["error"][:30]}')
            fail_count += 1
            continue
        judge = r.get('judge', {})
        verdict = judge.get('verdict', '-')
        score = judge.get('overall_score', 0.0)
        banned = len(judge.get('banned_phrases_found', []))
        run_type = r.get('chose_run_type', '-')
        match = '*' if not r.get('run_type_match') else ''
        print(f'{seed:<30} {run_type + match:<10} {score:<8.2f} {verdict:<12} {banned}')
        if verdict == 'pass':
            pass_count += 1
        elif verdict == 'fail':
            fail_count += 1
        else:
            border_count += 1
    print('-' * 70)
    print(f'pass: {pass_count}   borderline: {border_count}   fail: {fail_count}')
    print(f'(* = chose wrong run_type)')
    summary = {
        'pass': pass_count,
        'borderline': border_count,
        'fail': fail_count,
        'total': len(results),
        'seeds': [
            {
                'id': r['seed_id'],
                'verdict': r.get('judge', {}).get('verdict', 'error'),
                'score': r.get('judge', {}).get('overall_score', 0.0),
                'run_type_match': r.get('run_type_match', False),
            }
            for r in results
        ],
    }
    (RESULTS_DIR / '_summary.json').write_text(json.dumps(summary, indent=2) + '\n')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('seed_ids', nargs='*', help='Specific seed IDs to run (default: all)')
    parser.add_argument(
        '--sut-model',
        default='sonnet',
        help='Model for the system-under-test call (default: sonnet). Use "" to inherit Claude Code default.',
    )
    parser.add_argument(
        '--judge-model',
        default='sonnet',
        help='Model for the judge call (default: sonnet).',
    )
    args = parser.parse_args()

    sut_model = args.sut_model or None
    judge_model = args.judge_model or None

    seeds = load_seeds()
    if args.seed_ids:
        wanted = set(args.seed_ids)
        seeds = [s for s in seeds if s['id'] in wanted]
        missing = wanted - {s['id'] for s in seeds}
        if missing:
            print(f'Unknown seed ids: {sorted(missing)}', file=sys.stderr)
            return 2

    skill_text = load_skill()
    rubrics = load_rubrics()
    print(
        f'Running {len(seeds)} seed(s) via `claude -p` (sut={sut_model or "default"}, judge={judge_model or "default"})...'
    )

    results = []
    for seed in seeds:
        print(f'  -> {seed["id"]} (expected {seed["expected_run_type"]})... ', end='', flush=True)
        r = run_seed(seed, skill_text, rubrics, sut_model, judge_model)
        write_result(r)
        results.append(r)
        if 'error' in r:
            print(f'ERROR ({r["duration_s"]}s)')
        else:
            v = r['judge']['verdict']
            s = r['judge']['overall_score']
            print(f'{v} {s:.2f} ({r["duration_s"]}s)')

    print_summary(results)
    return 0


if __name__ == '__main__':
    sys.exit(main())
