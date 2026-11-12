#!/usr/bin/env bash
# Code quality checks, run by CI before the tests. Run locally with: uv run scripts/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."

code=(main.py ask.py scripts tests)

echo "== Formatting (ruff format)"
ruff format --check "${code[@]}"

echo "== Lint, naming, docstrings, complexity, nesting, conditionals, arguments (ruff)"
ruff check "${code[@]}"

echo "== Types (pyright)"
pyright

echo "== Function length <= 50 lines, cyclomatic complexity <= 10, arguments <= 4 (lizard)"
lizard --length 50 --CCN 10 --arguments 4 --warnings_only main.py ask.py scripts
# pytest-bdd step functions receive their fixtures as arguments, so tests get a looser argument limit
lizard --length 50 --CCN 10 --arguments 7 --warnings_only tests

echo "== Cognitive complexity <= 10 (complexipy)"
complexipy --max-complexity-allowed 10 --failed --quiet "${code[@]}"

echo "All quality checks passed."
