"""Check word budgets for the active documentation."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
BUDGETS = {
    "CLAUDE.md": 700,
    "_plans/PROGRESS.md": 1000,
    "README.md": 2500,
    "CHANGELOG.md": 2500,
}

failed = False
for name, limit in BUDGETS.items():
    count = len((ROOT / name).read_text(encoding="utf-8").split())
    print(f"{name}: {count}/{limit} words")
    failed |= count > limit

changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
unreleased = re.search(r"^## \[Unreleased\][^\n]*\n.*?(?=^## |\Z)", changelog, re.M | re.S)
if unreleased is None:
    print("CHANGELOG.md: missing [Unreleased] section")
    failed = True
else:
    count = len(unreleased.group().split())
    print(f"CHANGELOG.md [Unreleased]: {count}/600 words")
    failed |= count > 600

sys.exit(int(failed))
