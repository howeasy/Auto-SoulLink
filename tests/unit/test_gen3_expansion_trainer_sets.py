"""Falsifier for the pokeemerald-expansion trainer sets (card XC4).

Mirrors tests/unit/test_calc_trainer_sets.py's species+level whole-file multiset check: parses
the PINNED expansion source directly (independent of tools/gen_gen3_exp_trainers.py's own
block-based parser -- a flat regex scan is the "ground truth from the decomp, not from a second
copy" this repo's other trainer-set tests already use) and checks it against both generated
outputs: the vendored calc setdex (calc/src/js/data/sets/games/EmeraldExpansion.js) and the
trainer-panel data pack (data/games/gen3_exp/28877d73/gen3_exp_trainers.json).

The pinned source (data/gen3_exp_sources.lock.json: tag expansion/1.17.0, commit
e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7) lives only on the build host (ssh hgbox, ~/slink-exp)
-- never checked into this repo -- so most runs of this file hit the "source not found" skip.
Point SLINK_EXPANSION_SRC at a local copy (or a `.cache/expansion/<commit>` checkout under the
repo, same walk-up convention as pret) to run the source-comparison tests for real: an absent
source is a named skip, but a PRESENT source at the wrong commit is a hard failure, never a
silent pass -- the whole point of pinning.

The adapter tests at the bottom (trainer_info/trainers_for_area/trainer_party/trainer_brief)
need no pinned source: they exercise the shipped data pack directly.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from server.adapters.gen3_expansion import ROM_TYPE, Gen3ExpansionAdapter  # noqa: E402
from tools.gen_gen3_exp_trainers import enum_values  # noqa: E402

_LOCK = json.loads((_REPO / "data/gen3_exp_sources.lock.json").read_text(encoding="utf-8"))
_PIN = _LOCK["source"]["commit"]
_JSON_PACK = _REPO / "data/games/gen3_exp/28877d73/gen3_exp_trainers.json"
_JS_SETDEX = _REPO / "calc/src/js/data/sets/games/EmeraldExpansion.js"


def _canon(s: str) -> str:
    """Fold a species name down to bare lowercase alnum -- sidesteps SPECIES_MR_MIME vs
    "Mr. Mime" / "Nidoran-F" vs SPECIES_NIDORAN_F without a per-name exceptions table."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _find_expansion_src() -> Path | None:
    env = os.environ.get("SLINK_EXPANSION_SRC")
    if env:
        return Path(env)
    d = _REPO
    for _ in range(6):
        cand = d / ".cache" / "expansion" / _PIN
        if cand.is_dir():
            return cand
        parent = d.parent
        if parent == d:
            break
        d = parent
    return None


def _git_head(path: Path) -> str | None:
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def _need_source() -> Path:
    src = _find_expansion_src()
    if src is None:
        pytest.skip(f"pokeemerald-expansion checkout not found (set SLINK_EXPANSION_SRC; pin {_PIN})")
    head = _git_head(src)
    assert head == _PIN, f"{src} is at {head}, not the pin {_PIN} (data/gen3_exp_sources.lock.json)"
    return src


def _source_species_level_multiset(src: Path) -> Counter:
    """A flat regex scan for every (.species, .lvl) pair in src/data/trainers.h -- deliberately
    NOT tools/gen_gen3_exp_trainers.py's own block-based party parser, so a bug there can't hide
    from this check. Names are resolved to calc spelling via Gen3ExpansionAdapter (id resolution
    is not the risky part under test here; the party-block extraction is)."""
    text = (src / "src/data/trainers.h").read_text(encoding="utf-8")
    text = re.sub(r"#line \d+\n\s*", "", text)
    species_ids = enum_values((src / "include/constants/species.h").read_text(encoding="utf-8"), "SPECIES_")
    adapter = Gen3ExpansionAdapter(rom_type=ROM_TYPE)
    c: Counter = Counter()
    # .lvl always follows .species within the same TrainerMon struct literal, well under 300
    # chars away in this build -- bounded so this stays a fast forward scan, not a
    # backtracking crawl over a 1.3MB file.
    for sp, lvl in re.findall(r"\.species\s*=\s*(SPECIES_\w+),.{1,300}?\.lvl\s*=\s*(\d+),", text, re.S):
        sid = species_ids.get(sp)
        if sid is None:
            continue
        c[(_canon(adapter.calc_species(sid)), int(lvl))] += 1
    return c


def _json_pack_multiset() -> Counter:
    data = json.loads(_JSON_PACK.read_text(encoding="utf-8"))
    c: Counter = Counter()
    for t in data["trainers"].values():
        for mon in t["party"]:
            c[(_canon(mon["species"]), mon["level"])] += 1
    return c


def _js_setdex_multiset() -> Counter:
    text = _JS_SETDEX.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("//")]
    text = "\n".join(lines).strip()
    assert text.startswith("var "), _JS_SETDEX
    body = text[text.index("=") + 1:].strip().rstrip(";")
    dex = json.loads(body)
    c: Counter = Counter()
    for species, sets in dex.items():
        for entry in sets.values():
            c[(_canon(species), entry["level"])] += 1
    return c


def test_json_pack_identity_matches_lock_pin():
    data = json.loads(_JSON_PACK.read_text(encoding="utf-8"))
    assert data["source"]["commit"] == _PIN


def test_gen3_exp_trainers_json_matches_pinned_source():
    src = _need_source()
    assert _json_pack_multiset() == _source_species_level_multiset(src)


def test_emerald_expansion_js_matches_pinned_source():
    src = _need_source()
    assert _js_setdex_multiset() == _source_species_level_multiset(src)


# --------------------------------------------------------------------------------------
# Adapter tests -- no pinned source needed, exercise the shipped data pack directly.
# --------------------------------------------------------------------------------------

def _adapter() -> Gen3ExpansionAdapter:
    return Gen3ExpansionAdapter(rom_type=ROM_TYPE)


def _pack() -> dict:
    return json.loads(_JSON_PACK.read_text(encoding="utf-8"))


def test_trainer_info_and_party_for_a_gym_leader():
    a = _adapter()
    data = _pack()
    tid, roxanne = next((int(k), v) for k, v in data["trainers"].items() if v["const"] == "TRAINER_ROXANNE_1")
    assert a.trainer_info(tid) == ("Roxanne", "Leader")
    party = a.trainer_party(tid)
    assert party == roxanne["party"]
    assert [p["species"] for p in party] == ["Geodude", "Geodude", "Nosepass"]


def test_trainers_for_area_lists_only_key_trainers_of_that_area():
    a = _adapter()
    data = _pack()
    tid = next(int(k) for k, v in data["trainers"].items() if v["const"] == "TRAINER_ROXANNE_1")
    area = data["trainers"][str(tid)]["area"]
    assert area  # Roxanne's base fight has a resolved area (Route 104)
    listed = a.trainers_for_area(area)
    assert tid in listed
    for other in listed:
        t = data["trainers"][str(other)]
        assert t.get("key") is True
        assert t.get("area") == area


def test_trainer_brief_matches_trainer_party_and_info_for_the_champion():
    a = _adapter()
    data = _pack()
    tid = next(int(k) for k, v in data["trainers"].items() if v["const"] == "TRAINER_WALLACE")
    brief = a.trainer_brief(tid)
    assert brief is not None
    assert (brief["name"], brief["class"]) == a.trainer_info(tid)
    assert brief["party"] == a.trainer_party(tid)
    assert brief["level_cap"] == max(p["level"] for p in brief["party"])


def test_unknown_trainer_id_returns_empty():
    a = _adapter()
    assert a.trainer_info(999999) == ("", "")
    assert a.trainer_party(999999) == []
    assert a.trainer_brief(999999) is None
    assert a.trainers_for_area("") == []
    assert a.trainers_for_area("nonexistent_area") == []
