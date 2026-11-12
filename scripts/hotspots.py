"""Rank Python files by how often they change times how complex they are, like CodeScene's hotspots.

Code that is both complex and often changed is where readability matters most. Usage:
    uv run scripts/hotspots.py
"""

import subprocess
from collections import Counter
from pathlib import Path

import lizard

ROOT = Path(__file__).resolve().parent.parent


def git(*args: str) -> list[str]:
    """Run a git command in the repo and return its output, split on whitespace."""
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()


def commit_counts() -> Counter[str]:
    """Count the commits that touched each tracked Python file."""
    tracked = set(git("ls-files", "*.py"))
    return Counter(name for name in git("log", "--format=", "--name-only") if name in tracked)


def complexity(path: str) -> tuple[int, int, str]:
    """Return a file's total and worst cyclomatic complexity, and the name of its most complex function."""
    functions = lizard.analyze_file(str(ROOT / path)).function_list
    if not functions:
        return 0, 0, "-"
    worst = max(functions, key=lambda f: f.cyclomatic_complexity)
    return sum(f.cyclomatic_complexity for f in functions), worst.cyclomatic_complexity, worst.name


def main() -> None:
    """Print the hotspot table, the riskiest file first."""
    rows = [(path, count, *complexity(path)) for path, count in commit_counts().items()]
    rows.sort(key=lambda row: row[1] * row[2], reverse=True)
    print(f"{'file':<24} {'commits':>7} {'complexity':>10} {'score':>6}  most complex function")
    for path, count, total, worst, name in rows:
        print(f"{path:<24} {count:>7} {total:>10} {count * total:>6}  {name} ({worst})")


if __name__ == "__main__":
    main()
