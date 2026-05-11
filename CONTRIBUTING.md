# Contributing to AgentClip

Thanks for considering a contribution. AgentClip is a small, focused project, so the contribution loop is meant to be fast.

## What kind of contributions are welcome

- **Bug fixes.** A failing test plus the fix is the gold path.
- **Documentation.** Typos, clarifications, better examples, especially in `SKILL.md`.
- **New SKILL.md guidance.** If your agents are doing something well that the current skill doesn't teach, propose it.
- **MCP integration polish.** Better tool descriptions, better error messages, better defaults.
- **Tests.** Coverage gaps, especially for the SDK wire shapes.

## What's out of scope (for now)

- **Account systems / login flows.** v1 is intentionally accountless; the `write_token` is the credential. We'll revisit when there's a real reason.
- **New storage backends.** Object storage is a Django-side concern.

## Dev setup

```bash
# Clone and enter
git clone https://github.com/ericelizes1/agentclip
cd agentclip

# Install with uv (recommended) or pip
uv sync --extra dev
# or:  pip install -e '.[dev]'

# Run the test suite
uv run pytest -q

# Lint and format
uv run ruff check .
uv run ruff format .
```

## How to propose a change

1. **Open an issue first** for anything beyond a trivial typo. Saves both of us time if the direction is wrong.
2. **Branch off `main`.** Atomic commits with conventional prefixes: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.
3. **Write the test first** when adding behavior. We don't squash; commit history is part of the project signal.
4. **Open a PR.** CI runs on every push (lint + format + tests across Python 3.11/3.12/3.13).
5. **Match the existing style.** Single-quote strings, no semicolons, descriptive names, no comments unless the *why* is non-obvious.

## Hard rules for user-facing copy

These are project conventions; the reviewer will hold the line on them:

- **No em dashes** in user-facing copy (README, error messages, the landing page). Use commas, periods, "and".
- **No model or vendor names** in marketing copy ("Claude" / "GPT" / etc.). The skill ships for any agent runtime.
- **Founders / operators / engineers** is the audience phrasing. Never "non-technical founders".
- **Honest README.** No invented stars, users, or production deployments.

## License

By contributing, you agree your contribution is licensed under the [MIT License](LICENSE).
