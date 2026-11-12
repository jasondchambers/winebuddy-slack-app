#!/usr/bin/env bash
# Code quality checks, run by CI before the tests. Run locally with: uv run scripts/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."

code=(main.py ask.py scripts tests)

echo "== Formatting (ruff format)"
ruff format --check "${code[@]}"

echo "== Lint, naming, docstrings; cyclomatic complexity <= 10, nesting, conditionals, arguments <= 4 (ruff)"
ruff check "${code[@]}"

echo "== Types (pyright)"
pyright

echo "== Function length <= 50 lines (lizard; ruff has no line-count rule)"
lizard --length 50 --warnings_only main.py ask.py scripts
# ruff's argument limit is off for tests: pytest-bdd step functions receive their fixtures as arguments
lizard --length 50 --arguments 7 --warnings_only tests

echo "== Cognitive complexity <= 10 (complexipy)"
complexipy --max-complexity-allowed 10 --failed --quiet "${code[@]}"

echo "All quality checks passed."
