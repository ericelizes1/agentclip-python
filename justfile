default:
    @just --list

# --- Dev ---

test:
    uv run pytest tests/ -q

test-watch:
    uv run pytest tests/ -q --watch

lint:
    uv run ruff check .

format:
    uv run ruff format .

# --- Release ---

# 1. Bump pyproject.toml: version = '0.1.1'
# 2. Add a [0.1.1] block to CHANGELOG.md
# 3. Commit those changes
# 4. just release 0.1.1
release version:
    @grep -q "version = '{{version}}'" pyproject.toml || (echo "Bump version in pyproject.toml first" && exit 1)
    @grep -q "## \[{{version}}\]" CHANGELOG.md || (echo "Add a [{{version}}] entry to CHANGELOG.md first" && exit 1)
    @git diff --quiet || (echo "Working tree dirty — commit first" && exit 1)
    git tag v{{version}}
    git push origin main --tags
    uv build
    uv publish
    gh release create v{{version}} --generate-notes
