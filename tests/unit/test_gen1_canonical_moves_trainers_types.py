"""Gen 1 moves, trainers and types must match the pret decomps, parsed at test time.

Closes three clauses of the `canonical.generated-data` release row. Each clause is one
positive test (zero differences against BOTH pokered and pokeyellow) and one negative
control (a mutated copy must be reported), so a green run proves the check bites.

Skips when the decomps are not cloned; the release gate treats a skip as a failure,
which is the intended contract (tests/unit/test_gen1_items.py sets the precedent).
"""
from __future__ import annotations

import copy
import glob
import json
import os
import re
import sys

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
try:
    import gen_gen1_trainers as trainers_tool
    import gen_moves_data as moves_tool
finally:
    sys.path.pop(0)

from server.adapters import gen1_rby as adapter  # noqa: E402

DECOMPS = {"red/blue": "pokered", "yellow": "pokeyellow"}
PRET = {title: moves_tool.find_pret(name) for title, name in DECOMPS.items()}
if not all(os.path.isdir(p) for p in PRET.values()):
    pytest.skip("pokered/pokeyellow not cloned — run tools/build_pret_syms.py", allow_module_level=True)

DATA = os.path.join(ROOT, "data", "games", "gen1_rby")


def _load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


# ── 1. moves ─────────────────────────────────────────────────────────────────

def test_moves_match_pret():
    assert moves_tool.check_gen1_all(_load("moves.json")["moves"]) == []


def test_moves_check_bites():
    moves = _load("moves.json")["moves"]
    moves[1]["type"] = "Fighting"          # the Gen 2 retcon, wrong for Gen 1
    moves[164]["pp"] = 1
    del moves[100]
    diffs = moves_tool.check_gen1_all(moves)
    assert any("KARATE_CHOP type" in d for d in diffs)
    assert any("count shipped=164" in d for d in diffs)
    assert {d.split(":")[0] for d in diffs} == {"red/blue", "yellow"}, "each title must report"


# ── 2. trainers ──────────────────────────────────────────────────────────────

def _trainer_dirs():
    return {t: trainers_tool.find_pret(n) for t, n in trainers_tool.TITLES.items()}


def test_trainers_match_pret_and_upr_pin():
    assert trainers_tool.check(_load("trainers.json"), _load("upr_layout.json"), _trainer_dirs()) == []


def test_trainers_check_bites():
    shipped, layout = _load("trainers.json"), _load("upr_layout.json")
    shipped["classes"]["234"] = "Misty"                 # the shift that once shipped
    shipped["named_trainers"]["243"]["4"] = "Blue"      # the phantom Champion party
    layout["profiles"]["yellow"]["settings"]["TrainerDataClassCounts"][25] += 1
    diffs = trainers_tool.check(shipped, layout, _trainer_dirs())
    assert any("class 234" in d and "Brock" in d for d in diffs)
    assert any("named_trainers[243][4]" in d for d in diffs)
    assert any(d.startswith("yellow: party counts") for d in diffs)
    assert not any(d.startswith("red: party counts") for d in diffs)


def test_trainer_id_offset_is_pret_opp_id_offset():
    """The 200 the tables are keyed by is pret's constant, not a guess."""
    offset, consts = trainers_tool.parse_constants(
        os.path.join(PRET["red/blue"], "constants", "trainer_constants.asm"))
    assert offset == 200 and consts[0] == "NOBODY" and consts[-1] == "LANCE"
    rivals = {offset + consts.index(c) for c in ("RIVAL1", "RIVAL2", "RIVAL3")}
    assert rivals == adapter.Gen1Adapter._RIVAL_IDS


# ── 3. types ─────────────────────────────────────────────────────────────────

def _pret_type_ids(pret_dir):
    """type const name -> id from constants/type_constants.asm (`const NAME`, with the
    `const_next 20` hole between GHOST and FIRE)."""
    ids, cur = {}, 0
    with open(os.path.join(pret_dir, "constants", "type_constants.asm"), encoding="utf-8") as f:
        for line in f:
            if m := re.match(r"^\s*const_next\s+(\d+)", line):
                cur = int(m.group(1))
            elif m := re.match(r"^\s*const\s+(\w+)", line):
                ids[m.group(1)] = cur
                cur += 1
    return ids


def _pret_species_types(pret_dir):
    """national dex -> (type1 id, type2 id) from every data/pokemon/base_stats/*.asm
    (`db DEX_X ; pokedex id` then `db T1, T2 ; type`), dex numbers from
    constants/pokedex_constants.asm."""
    dex = {}
    with open(os.path.join(pret_dir, "constants", "pokedex_constants.asm"), encoding="utf-8") as f:
        for line in f:
            if m := re.match(r"^\s*const\s+(DEX_\w+)", line):
                dex[m.group(1)] = len(dex) + 1
    type_ids = _pret_type_ids(pret_dir)
    out = {}
    for path in glob.glob(os.path.join(pret_dir, "data", "pokemon", "base_stats", "*.asm")):
        with open(path, encoding="utf-8") as f:
            src = f.read()
        d = re.search(r"^\s*db\s+(DEX_\w+)\s*;\s*pokedex id", src, re.M).group(1)
        t1, t2 = re.search(r"^\s*db\s+(\w+),\s*(\w+)\s*;\s*type", src, re.M).groups()
        out[dex[d]] = (type_ids[t1], type_ids[t2])
    return out


def _type_diffs(type_ids, species_types, adapter_type_ids, adapter_species_types):
    diffs = []
    # BIRD ($06) is defined and named on the cartridge but no species or move carries it;
    # the adapter deliberately leaves it out. Every other id must be present and named
    # by the same word (PSYCHIC_TYPE -> Psychic).
    for const, tid in type_ids.items():
        want = moves_tool.normalize_type(const)
        if const == "BIRD":
            continue
        if adapter_type_ids.get(tid) != want:
            diffs.append(f"type {tid:#04x}: adapter={adapter_type_ids.get(tid)!r} pret={want!r}")
    for tid in set(adapter_type_ids) - set(type_ids.values()):
        diffs.append(f"type {tid:#04x}: adapter has it, pret does not")
    if sorted(species_types) != list(range(1, 152)):
        diffs.append(f"pret parsed {len(species_types)} species, expected 151")
    for dex in range(1, 152):
        if adapter_species_types.get(dex) != species_types.get(dex):
            diffs.append(f"species {dex}: adapter={adapter_species_types.get(dex)} pret={species_types.get(dex)}")
    return diffs


@pytest.mark.parametrize("title", sorted(DECOMPS))
def test_types_match_pret(title):
    assert _type_diffs(_pret_type_ids(PRET[title]), _pret_species_types(PRET[title]),
                       adapter._TYPE_IDS, adapter._SPECIES_TYPES) == []


def test_types_check_bites():
    pret = PRET["red/blue"]
    ids = copy.deepcopy(adapter._TYPE_IDS)
    ids[0x14] = "Flame"
    ids[0x06] = "Bird"
    species = copy.deepcopy(adapter._SPECIES_TYPES)
    species[25] = (0x00, 0x00)          # Pikachu as Normal
    del species[151]
    diffs = _type_diffs(_pret_type_ids(pret), _pret_species_types(pret), ids, species)
    assert any(d.startswith("type 0x14") for d in diffs)
    assert not any(d.startswith("type 0x06") for d in diffs), "BIRD is the documented exception"
    assert any(d.startswith("species 25:") for d in diffs)
    assert any(d.startswith("species 151:") for d in diffs)


@pytest.mark.parametrize("title", sorted(DECOMPS))
def test_move_types_are_pret_type_names(title):
    names = {moves_tool.normalize_type(c) for c in _pret_type_ids(PRET[title])}
    bad = [(m["id"], m["type"]) for m in _load("moves.json")["moves"] if m["type"] not in names]
    assert bad == []
