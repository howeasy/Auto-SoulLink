"""tests/unit/test_gen3_rr_generators.py -- receipts for the Radical Red data
generators (tools/gen_rr_*.py) against data/gen3_rr_sources.lock.json.
See docs/gen3_requirements.md row F-7.

Offline (always run): the lock parses, and every generator's own
cached_source()/cached_source_path() calls name a source the lock declares
-- and every declared source is actually read by some generator (no orphan
pins).

Online (needs a populated cache): if $SLINK_RR_SRC_CACHE holds the pinned
sources verified against their hashes, this runs each generator's --check
against them. Absent cache => named pytest.skip (never a silent pass);
present-but-wrong-hash => a named FAIL, because cached_source() itself
raises rather than returning unverified bytes. Populate the cache with:
    python tools/fetch_rr_sources.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "data" / "gen3_rr_sources.lock.json"

sys.path.insert(0, str(ROOT / "tools"))
import fetch_rr_sources as rrfetch  # noqa: E402

GENERATOR_SCRIPTS = [
    "tools/gen_rr_species.py",
    "tools/gen_rr_types.py",
    "tools/gen_rr_natdex.py",
    "tools/gen_rr_encounters.py",
    "tools/gen_rr_sprites.py",
    "tools/gen_rr_priority_trainers.py",
]


def _lock() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _cached_source_names(script_relpath: str) -> set[str]:
    text = (ROOT / script_relpath).read_text(encoding="utf-8")
    return set(re.findall(r'cached_source(?:_path)?\("([^"]+)"', text))


def test_lock_parses():
    lock = _lock()
    assert lock["schema_version"] == 1
    assert lock["sources"], "lock declares no sources"
    for name, entry in lock["sources"].items():
        assert entry.get("fetch_url"), f"{name}: missing fetch_url"
        assert entry.get("sha256") or entry.get("content_sha256"), f"{name}: no hash pin"


@pytest.mark.parametrize("script", GENERATOR_SCRIPTS)
def test_generator_pins_are_declared(script):
    """Every source name a generator's own code passes to cached_source()/
    cached_source_path() must exist in the lock -- catches a generator that
    silently reverted to a live, unpinned fetch."""
    lock = _lock()
    declared = _cached_source_names(script)
    assert declared, f"{script} never calls cached_source()/cached_source_path()"
    missing = declared - set(lock["sources"])
    assert not missing, f"{script} reads {missing}, not declared in {LOCK_PATH}"


def test_every_lock_source_is_read_by_some_generator():
    lock = _lock()
    used: set[str] = set()
    for script in GENERATOR_SCRIPTS:
        used |= _cached_source_names(script)
    unused = set(lock["sources"]) - used
    assert not unused, f"lock declares source(s) no generator reads: {unused}"


@pytest.mark.parametrize("script", GENERATOR_SCRIPTS)
def test_generator_check_against_cache(script):
    """ONLINE: run `python <script> --check` against the cached, pinned
    sources it declares. Skips by name when any of them isn't cached yet;
    a cached-but-wrong-hash file is never treated as a skip -- cached_source
    raises, which surfaces here as a FAIL naming the source."""
    for name in sorted(_cached_source_names(script)):
        try:
            rrfetch.cached_source(name, allow_fetch=False)
        except FileNotFoundError as exc:
            pytest.skip(f"{name} not cached (run `python tools/fetch_rr_sources.py`): {exc}")
    result = subprocess.run(
        [sys.executable, str(ROOT / script), "--check"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, (
        f"{script} --check drifted from its committed output (exit {result.returncode}). "
        f"See docs/gen3_requirements.md F-7 -- for gen_rr_priority_trainers.py this is a "
        f"known, currently-reproducible finding (the community Google Sheet has moved on "
        f"from what produced the committed roster), not a broken pin.\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
