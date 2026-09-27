"""The pinned pret/pokefirered clone for Gen 3 unit tests (tests/TESTING.md, "Absent input skips;
present-but-wrong input fails").

`.cache/` is gitignored, so a worktree usually has none of its own: look at $SLINK_PRET_FIRERED_SRC
first (not SLINK_PRET_SRC, which is Gen 1's pret/pokered path, tools/gen1_foundation.py:11), else
the checkout and its ancestors. Walking up is
safe only because the clone found is then checked against the pin in data/gen3_sources.lock.json:
absent skips by name, a clone at another commit fails.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PIN = json.loads((ROOT / "data/gen3_sources.lock.json").read_text(encoding="utf-8"))["source"]["commit"]
REL = ".cache/pret/pokefirered"


def find(root=ROOT, env=os.environ):
    if env.get("SLINK_PRET_FIRERED_SRC"):
        return Path(env["SLINK_PRET_FIRERED_SRC"])
    return next((d / REL for d in (root, *root.parents) if (d / REL).exists()), root / REL)


def head(path):
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def require(path, rev=head):
    """`path` if it is a pret/pokefirered clone at the pin; skip when absent, fail when wrong."""
    if not path.exists():
        pytest.skip(f"pret pokefirered not cloned ({path}); set SLINK_PRET_FIRERED_SRC or clone it at {PIN[:8]}")
    got = rev(path)
    if got != PIN:
        pytest.fail(f"{path} is at {got}, not the pinned pret/pokefirered {PIN} (data/gen3_sources.lock.json)")
    return path


# ── pret/pokeemerald: the same pattern, its own env var and pin ──────────────────────────────
# The pin is the commit data/gen3/pret/pokeemerald.sym was published from (docs/gen3_emerald/PLAN.md E0).
EMERALD_PIN = json.loads((ROOT / "data/gen3/pret/pokeemerald_provenance.json")
                         .read_text(encoding="utf-8"))["origin"]["source_commit"]
EMERALD_REL = ".cache/pret/pokeemerald"


def find_emerald(root=ROOT, env=os.environ):
    if env.get("SLINK_PRET_EMERALD_SRC"):
        return Path(env["SLINK_PRET_EMERALD_SRC"])
    return next((d / EMERALD_REL for d in (root, *root.parents) if (d / EMERALD_REL).exists()), root / EMERALD_REL)


def require_emerald(path, rev=head):
    """`path` if it is a pret/pokeemerald clone at the pin; skip when absent, fail when wrong."""
    if not path.exists():
        pytest.skip(f"pret pokeemerald not cloned ({path}); set SLINK_PRET_EMERALD_SRC or clone it at {EMERALD_PIN[:8]}")
    got = rev(path)
    if got != EMERALD_PIN:
        pytest.fail(f"{path} is at {got}, not the pinned pret/pokeemerald {EMERALD_PIN} "
                    "(data/gen3/pret/pokeemerald_provenance.json)")
    return path
