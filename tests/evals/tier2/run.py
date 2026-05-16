"""Tier 2 eval orchestrator for the agentclip skill.

Spins up an HTTP fixture server (deterministic target page) and an API
stub (mimicking api.agentclip.dev), points the agentclip MCP at the
stub via AGENTCLIP_API_URL, then runs ``claude -p`` with the seed prompt.
The agent drives a real browser through the fixture, calls the real MCP
tools, and the stub records every backend interaction.

After the agent finishes, a second ``claude -p`` invocation grades the
result against the rubric, cross-referencing the agent's self-report
against the stub transcript so fabricated success claims fail.

What is real:
  - claude -p (the only thing not mocked, per design)
  - The agentclip MCP server and the agentclip browser tools (real Playwright)
  - The fixture HTTP server (serves a real local HTML page)

What is mocked:
  - api.agentclip.dev (StubAPI in stub_api.py)
  - The slideshow render/PDF/MP4 pipeline (stub returns URLs that look real)

Run:
    python tests/evals/tier2/run.py                # all seeds
    python tests/evals/tier2/run.py demo-signup-loom

Output:
    tests/evals/tier2/results/<seed_id>.json       # full trace + transcript per seed
    tests/evals/tier2/results/_summary.json
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

# Make sibling stub_api importable when run as a script.
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from stub_api import StubAPI  # noqa: E402

SEEDS_PATH = _HERE / 'seeds.json'
RUBRIC_PATH = _HERE / 'rubric.json'
FIXTURES_DIR = _HERE / 'fixtures'
RESULTS_DIR = _HERE / 'results'

# JSON schema the SUT must produce as its final structured output. Lets
# us cross-reference what the agent CLAIMS happened against what the
# stub RECORDS — fabricated success fails on this mismatch.
SUT_REPORT_SCHEMA = {
    'type': 'object',
    'properties': {
        'share_url': {'type': 'string'},
        'run_type_used': {
            'type': 'string',
            'enum': ['demo', 'qa', 'guide', 'bug', 'walkthrough'],
        },
        'title': {'type': 'string'},
        'description': {'type': 'string'},
        'captions': {'type': 'array', 'items': {'type': 'string'}},
        'summary': {'type': 'string'},
        'annotations_used_on_slides': {'type': 'array', 'items': {'type': 'integer'}},
        'tool_failures_recovered_from': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': [
        'share_url',
        'run_type_used',
        'title',
        'description',
        'captions',
        'summary',
        'annotations_used_on_slides',
    ],
}

JUDGE_SCHEMA = {
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
        'notes': {'type': 'string'},
    },
    'required': ['overall_score', 'verdict', 'criteria', 'banned_phrases_found', 'notes'],
}


class FixtureServer:
    """Serves a single HTML fixture from FIXTURES_DIR on a free port."""

    def __init__(self, fixture: str):
        self._fixture = fixture
        self._httpd: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if self._httpd is None:
            raise RuntimeError('fixture server not started')
        host, port = self._httpd.server_address
        return f'http://{host}:{port}/{self._fixture}'

    def start(self) -> None:
        handler = functools.partial(
            http.server.SimpleHTTPRequestHandler,
            directory=str(FIXTURES_DIR),
        )
        # Silence per-request log noise.
        handler_cls = (
            type(
                'SilentHandler',
                (handler.func,),
                {
                    'log_message': lambda self, *a, **kw: None,
                },
            )
            if False
            else handler
        )  # noqa: F841
        self._httpd = socketserver.TCPServer(('127.0.0.1', 0), _silent(handler))
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        time.sleep(0.05)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)


def _silent(handler_factory):
    """Wrap a handler factory so per-request stderr noise is silenced."""

    def make(*args, **kwargs):
        h = handler_factory(*args, **kwargs)
        h.log_message = lambda *a, **kw: None
        return h

    return make


def build_sut_prompt(seed: dict, fixture_url: str, stub_base: str) -> str:
    prompt = seed['user_prompt'].replace('{fixture_url}', fixture_url)
    expects_annotations = seed.get('expects_annotations', False)
    annotation_hint = (
        '\n\nWhen a caption uses deictic words (watch / notice / see / look at / '
        'right here / this part), you MUST use the `annotations` argument on '
        '`browser_screenshot` to circle / rect / arrow the referenced element. '
        'Captions pointing at nothing visual are weak.'
        if expects_annotations
        else ''
    )
    return f"""{prompt}

The agentclip MCP server in this session is wired to a TEST BACKEND at {stub_base} — not production. Treat it as a real backend: call slideshow_create, slideshow_add_slide, slideshow_set_summary as documented. The fixture URL above ({fixture_url}) is a real local page; drive it with the agentclip browser MCP tools.{annotation_hint}

When you're done, return ONLY a JSON object matching this exact schema (no prose, no code fences):

{json.dumps(SUT_REPORT_SCHEMA['properties'], indent=2)}

Fields:
- `share_url`: the share URL returned by slideshow_create (e.g. https://agentclip.dev/s/<token>/).
- `run_type_used`: the run_type value you passed to slideshow_create.
- `title`, `description`, `summary`: exactly the strings you sent.
- `captions`: in slide order.
- `annotations_used_on_slides`: 1-based slide positions that had non-empty annotations.
- `tool_failures_recovered_from`: brief notes on any retries (e.g. ["slideshow_create rejected 'walkthrough', retried with 'demo'"]). Empty list if none."""


def build_judge_prompt(seed: dict, sut_report: dict, transcript: list[dict], rubric: dict) -> str:
    banned = ', '.join(f'"{p}"' for p in rubric['banned_phrases'])
    criteria_block = '\n'.join(
        f'- **{c["name"]}** (weight {c["weight"]}): {c["definition"]}' for c in rubric['criteria']
    )
    captions_block = '\n'.join(
        f'  {i + 1}. {c}' for i, c in enumerate(sut_report.get('captions', []))
    )
    # Compact transcript for the judge — show method/path/status + the
    # body keys that matter for cross-referencing.
    compact_trace = []
    for entry in transcript:
        b = entry.get('body') or {}
        keys_of_interest = {
            k: b.get(k)
            for k in ('title', 'description', 'run_type', 'caption', 'summary')
            if k in b
        }
        compact_trace.append(
            {
                'method': entry['method'],
                'path': entry['path'],
                'status': entry['status'],
                'body_excerpt': keys_of_interest,
            }
        )
    return f"""You are a strict Tier 2 reviewer of an agentclip end-to-end agent run. The agent claimed to produce a clip; your job is to grade against the rubric, cross-referencing the agent's self-report against the test backend's transcript so any fabricated success fails.

## Seed
- id: {seed['id']}
- expected_run_type: {seed['expected_run_type']}
- expected_min_slides: {seed.get('expected_min_slides', 0)}
- expected_max_slides: {seed.get('expected_max_slides', 999)}
- expects_annotations: {seed.get('expects_annotations', False)}
- stub_config: {json.dumps(seed.get('stub_config', {}))}

## Agent self-report
- share_url: {sut_report.get('share_url', '<missing>')}
- run_type_used: {sut_report.get('run_type_used', '<missing>')}
- title: {sut_report.get('title', '<missing>')}
- description: {sut_report.get('description', '<missing>')}
- captions:
{captions_block}
- summary: {sut_report.get('summary', '<missing>')}
- annotations_used_on_slides: {sut_report.get('annotations_used_on_slides', [])}
- tool_failures_recovered_from: {sut_report.get('tool_failures_recovered_from', [])}

## Backend transcript (what the stub actually saw)
{json.dumps(compact_trace, indent=2)}

## Rubric
{criteria_block}

## Banned phrases (any type, case-insensitive substring)
{banned}

## Grading rules
- For each criterion, give a score 0.0 to 1.0 and a one-sentence reason.
- List every banned phrase you find (exact substring matches) in any text field.
- overall_score is the weight-averaged criterion score.
- verdict: "pass" if overall_score >= 0.80 AND zero banned phrases AND share_url is real AND run_type matches; "fail" if overall_score < 0.60 OR any banned phrase OR share_url not in transcript; otherwise "borderline".

Output only the JSON object matching the schema. No prose, no code fences."""


def claude_p(
    prompt: str,
    schema: dict,
    env: dict | None = None,
    timeout: int = 360,
    *,
    allow_tools: bool = False,
    max_budget_usd: float | None = None,
) -> tuple[dict, dict]:
    """Invoke claude -p with structured-output validation. Returns (parsed, envelope).

    When ``allow_tools`` is True, MCP / Bash / Edit tool calls are auto-approved
    via --permission-mode bypassPermissions. Required for the SUT call where
    the agent has to actually drive a browser and hit the API stub. Leave
    False for the judge call (which only needs to read + reason).

    Uses Popen + os.killpg so the whole process tree (claude + its MCP
    subprocess + Playwright Chromium) dies on timeout. plain subprocess.run
    timeout doesn't reach the grandchildren and an agent stuck in a tool
    loop runs for hours past the deadline."""
    import os as _os
    import signal

    cmd = [
        'claude',
        '-p',
        '--output-format',
        'json',
        '--json-schema',
        json.dumps(schema),
        '--no-session-persistence',
        '--exclude-dynamic-system-prompt-sections',
    ]
    if allow_tools:
        cmd += ['--permission-mode', 'bypassPermissions']
    if max_budget_usd is not None:
        cmd += ['--max-budget-usd', str(max_budget_usd)]
    cmd.append(prompt)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,  # new process group so killpg can reach all children
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # SIGKILL the whole process group so Playwright/MCP children die too.
        try:
            _os.killpg(_os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout, stderr = '', ''
        raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr) from None

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=stdout, stderr=stderr)

    envelope = json.loads(stdout)
    if envelope.get('is_error'):
        raise RuntimeError(
            f'claude -p reported error: {str(envelope.get("result", envelope))[:500]}'
        )
    parsed = envelope.get('structured_output')
    if parsed is None:
        text = (envelope.get('result') or '').strip()
        if text.startswith('```'):
            text = '\n'.join(ln for ln in text.splitlines() if not ln.startswith('```')).strip()
        if not text:
            raise RuntimeError(
                f'no structured_output and no result text. keys: {sorted(envelope.keys())}'
            )
        parsed = json.loads(text)
    return parsed, envelope


def run_seed(seed: dict, rubric: dict) -> dict:
    start = time.time()
    fixture_server = FixtureServer(seed['fixture'])
    fixture_server.start()
    stub = StubAPI()
    stub.start()
    # Apply stub failure injection from the seed config.
    for k, v in seed.get('stub_config', {}).items():
        setattr(stub, k, v)

    env = os.environ.copy()
    # SDK reads AGENTCLIP_BASE_URL (not AGENTCLIP_API_URL — the project
    # CLAUDE.md is stale on this). Set both to be defensive.
    env['AGENTCLIP_BASE_URL'] = stub.base_url
    env['AGENTCLIP_API_URL'] = stub.base_url
    # Ensure the agent runs with a clean transcript folder pre-creation
    # to avoid polluting unrelated runs.

    sut_prompt = build_sut_prompt(seed, fixture_server.url, stub.base_url)
    sut_error = None
    sut_report: dict | None = None
    sut_envelope: dict | None = None
    try:
        sut_report, sut_envelope = claude_p(
            sut_prompt,
            SUT_REPORT_SCHEMA,
            env=env,
            timeout=seed.get('timeout_s', 600),
            allow_tools=True,
            max_budget_usd=seed.get('max_budget_usd', 3.0),
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        RuntimeError,
        json.JSONDecodeError,
    ) as e:
        sut_error = f'{type(e).__name__}: {str(e)[:500]}'

    transcript = list(stub.transcript)
    fixture_server.stop()
    stub.stop()

    duration = round(time.time() - start, 1)
    if sut_error or sut_report is None:
        return {
            'seed_id': seed['id'],
            'error': sut_error or 'no SUT report produced',
            'transcript': transcript,
            'duration_s': duration,
        }

    # Judge the result.
    judge_prompt = build_judge_prompt(seed, sut_report, transcript, rubric)
    try:
        judge_report, _ = claude_p(judge_prompt, JUDGE_SCHEMA, timeout=240)
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        RuntimeError,
        json.JSONDecodeError,
    ) as e:
        return {
            'seed_id': seed['id'],
            'sut_report': sut_report,
            'transcript': transcript,
            'error': f'judge failed: {type(e).__name__}: {str(e)[:500]}',
            'duration_s': duration,
        }

    return {
        'seed_id': seed['id'],
        'expected_run_type': seed['expected_run_type'],
        'sut_report': sut_report,
        'transcript_summary': _summarize_transcript(transcript),
        'judge': judge_report,
        'duration_s': duration,
    }


def _summarize_transcript(transcript: list[dict]) -> dict:
    by_method = {}
    statuses = []
    for e in transcript:
        by_method.setdefault(e['method'], 0)
        by_method[e['method']] += 1
        statuses.append({'method': e['method'], 'path': e['path'], 'status': e['status']})
    return {
        'total_calls': len(transcript),
        'by_method': by_method,
        'calls_in_order': statuses,
    }


def write_result(result: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f'{result["seed_id"]}.json'
    out.write_text(json.dumps(result, indent=2) + '\n')
    return out


def print_summary(results: list[dict]) -> None:
    print()
    print('=' * 78)
    print('TIER 2 EVAL SUMMARY')
    print('=' * 78)
    print(f'{"seed_id":<44} {"score":<8} {"verdict":<12} {"duration":<8}')
    print('-' * 78)
    pass_count = border_count = fail_count = 0
    for r in results:
        seed = r['seed_id']
        if 'error' in r:
            print(f'{seed:<44} {"ERROR":<8} {r["error"][:30]:<12} {r.get("duration_s", 0)}s')
            fail_count += 1
            continue
        v = r['judge']['verdict']
        s = r['judge']['overall_score']
        dur = r['duration_s']
        print(f'{seed:<44} {s:<8.2f} {v:<12} {dur}s')
        if v == 'pass':
            pass_count += 1
        elif v == 'fail':
            fail_count += 1
        else:
            border_count += 1
    print('-' * 78)
    print(f'pass: {pass_count}   borderline: {border_count}   fail: {fail_count}')

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
            }
            for r in results
        ],
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / '_summary.json').write_text(json.dumps(summary, indent=2) + '\n')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('seed_ids', nargs='*', help='Specific seed IDs to run (default: all)')
    args = parser.parse_args()

    seeds = json.loads(SEEDS_PATH.read_text())
    rubric = json.loads(RUBRIC_PATH.read_text())

    if args.seed_ids:
        wanted = set(args.seed_ids)
        seeds = [s for s in seeds if s['id'] in wanted]
        missing = wanted - {s['id'] for s in seeds}
        if missing:
            print(f'unknown seed ids: {sorted(missing)}', file=sys.stderr)
            return 2

    print(f'running {len(seeds)} Tier 2 seed(s) — stub stands in for api.agentclip.dev')
    results = []
    for seed in seeds:
        print(f'  -> {seed["id"]} ... ', end='', flush=True)
        r = run_seed(seed, rubric)
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
