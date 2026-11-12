"""Rank Python files by how often they change times how complex they are, like CodeScene's hotspots.

Code that is both complex and often changed is where readability matters most. Usage:
    uv run scripts/hotspots.py [--since "6 months ago"]
"""

import argparse
import subprocess
from collections import Counter
from pathlib import Path

import lizard

ROOT = Path(__file__).resolve().parent.parent


def commit_counts(since: str | None) -> Counter[str]:
    """Count the commits that touched each tracked Python file."""
    command = ["git", "log", "--format=", "--name-only", *([f"--since={since}"] if since else [])]
    log = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    tracked = set(
        subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    )
    return Counter(name for name in log.split() if name in tracked)


def complexity(path: str) -> tuple[int, int, str]:
    """Return a file's total and worst cyclomatic complexity, and the name of its most complex function."""
    functions = lizard.analyze_file(str(ROOT / path)).function_list
    if not functions:
        return 0, 0, "-"
    worst = max(functions, key=lambda f: f.cyclomatic_complexity)
    return sum(f.cyclomatic_complexity for f in functions), worst.cyclomatic_complexity, worst.name


def main() -> None:
    """Print the hotspot table, the riskiest file first."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", help='only count commits since this date, e.g. "6 months ago"')
    commits = commit_counts(parser.parse_args().since)

    rows = [(path, count, *complexity(path)) for path, count in commits.items()]
    rows.sort(key=lambda row: row[1] * row[2], reverse=True)
    print(f"{'file':<24} {'commits':>7} {'complexity':>10} {'score':>6}  most complex function")
    for path, count, total, worst, name in rows:
        print(f"{path:<24} {count:>7} {total:>10} {count * total:>6}  {name} ({worst})")


if __name__ == "__main__":
    main()
