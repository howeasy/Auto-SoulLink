"""Falsifiers for the Emerald move/item tables (card EF-9).

These are pure-pret SOURCE assertions: they parse the two read-only pret
checkouts (`.cache/pret/pokefirered` c75f352, `.cache/pret/pokeemerald`
c65e93f2) as text and compare them to each other and to the shared Gen 3
server data. No SLink runtime is imported beyond the two static data modules
under test.

The claim being falsified (PLAN.md section "Server data") is that vanilla Gen 3
move stats are title-independent -- pokeemerald's src/data/battle_moves.h is
NOT byte-identical to pokefirered's, so "the tables agree" is a real assertion
and not a tautology. The item side proves the inverse shape: ids 0-374 are
shared, and Emerald alone adds exactly {375 Magma Emblem, 376 Old Sea Map},
which is why server/data/items/gen3_vanilla.py must not grow them.

Skips (per-test, not module-wide) when either checkout is absent, same
`_find_pret_checkout` / `needs_pret` pattern as test_gen3_emerald_areas.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from server.data.items.gen3_vanilla import ITEM_NAMES as VANILLA_ITEM_NAMES
from server.data.moves.gen3_vanilla import MOVE_DATA as VANILLA_MOVE_DATA

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "tools"))

import gen_area_map as gam  # noqa: E402

PRET_FRLG = "pokefirered"
PRET_EMERALD = "pokeemerald"
MOVE_FIELDS = ("type", "power", "accuracy", "pp")
EMERALD_ONLY = ((375, "ITEM_MAGMA_EMBLEM"), (376, "ITEM_OLD_SEA_MAP"))
EMERALD_ONLY_FIRST = EMERALD_ONLY[0][0]
# pokefirered src/data/battle_moves.h:3479 .accuracy = 0
# pokeemerald src/data/battle_moves.h:3479 .accuracy = 95
KNOWN_MOVE_DIFFS = {"MOVE_NATURE_POWER": {"accuracy": (0, 95)}}


def _missing_pret_repos() -> list[str]:
    """Which of the two checkouts this test needs are actually absent, so the skip reason names
    the repo that is missing instead of a blanket message covering both regardless of which."""
    missing = []
    for repo in (PRET_FRLG, PRET_EMERALD):
        try:
            gam._find_pret_checkout(repo)
        except FileNotFoundError:
            missing.append(repo)
    return missing


_MISSING_PRET = _missing_pret_repos()
needs_pret = pytest.mark.skipif(
    bool(_MISSING_PRET),
    reason=" and ".join(f"{repo} not cloned" for repo in _MISSING_PRET),
)

_DEFINE_RE = re.compile(r"^#define\s+([A-Z0-9_]+)\s+(\d+)\s*$")
_ENUMERATOR_RE = re.compile(r"^\s*([A-Z0-9_]+)\s*=\s*(\d+)\s*,?\s*$")
_MOVE_BLOCK_RE = re.compile(r"^\[MOVE_(\w+)\]\s*=")
_MOVE_FIELD_RE = re.compile(r"^\.(\w+)\s*=\s*(.+?),?\s*$")
# pret spells unused slots either as the id in hex (ITEM_034 == 52) or ITEM_UNUSED_*.
_PLACEHOLDER_RE = re.compile(r"^ITEM_(?:[0-9A-F]{3}|UNUSED[A-Z0-9_]*)$")


def _read(repo: str, rel: str) -> str:
    return (Path(gam._find_pret_checkout(repo)) / rel).read_text(encoding="utf-8")


def _constants(text: str, prefix: str) -> dict[str, int]:
    """{NAME: int} for `#define NAME <int>` lines and bare `NAME = <int>,` enumerators.

    Aliases (`#define ITEM_TM01_FOCUS_PUNCH ITEM_TM01`, pokefirered items.h:361) and
    hex sentinels (`ITEM_LIST_END 0xFFFF`, pokeemerald items.h:424) carry no integer
    literal and are therefore skipped, which is exactly the wanted behaviour.
    """
    out: dict[str, int] = {}
    for line in text.splitlines():
        stripped = line.strip()
        m = _DEFINE_RE.match(stripped) or _ENUMERATOR_RE.match(stripped)
        if m is not None and m.group(1).startswith(prefix):
            out[m.group(1)] = int(m.group(2))
    return out


def _move_ids(repo: str) -> dict[str, int]:
    return _constants(_read(repo, "include/constants/moves.h"), "MOVE_")


def _move_tables(repo: str) -> tuple[list[str], dict[str, dict[str, int]]]:
    """Return (declaration order of the gBattleMoves blocks, {MOVE_NAME: {field: int}}).

    Types are resolved through the tree's own include/constants/pokemon.h rather than
    a hardcoded table, so the parse stays a pret-source assertion end to end.
    """
    types = _constants(_read(repo, "include/constants/pokemon.h"), "TYPE_")
    order: list[str] = []
    stats: dict[str, dict[str, int]] = {}
    current: str | None = None
    for raw in _read(repo, "src/data/battle_moves.h").splitlines():
        line = raw.strip()
        block = _MOVE_BLOCK_RE.match(line)
        if block is not None:
            current = "MOVE_" + block.group(1)
            order.append(current)
            stats[current] = {}
            continue
        if current is None:
            continue
        field = _MOVE_FIELD_RE.match(line)
        if field is None or field.group(1) not in MOVE_FIELDS:
            continue
        key, value = field.group(1), field.group(2).strip()
        if key == "type":
            assert value in types, f"{current}: unknown type token {value!r}"
            stats[current][key] = types[value]
        else:
            assert value.isdigit(), f"{current}: .{key} is not an integer: {value!r}"
            stats[current][key] = int(value)
    return order, stats


def _by_move_id(repo: str) -> dict[int, dict[str, int]]:
    order, stats = _move_tables(repo)
    ids = _move_ids(repo)
    declared = [name for name, _ in sorted(ids.items(), key=lambda kv: kv[1])]
    # Precondition for comparing by id at all: battle_moves.h lists blocks in id order.
    assert order == declared, f"{repo}: battle_moves.h block order != include/constants/moves.h ids"
    # "MOVES_COUNT" does not start with "MOVE_", so it is not in `ids` -- read it on its own.
    moves_count = _constants(_read(repo, "include/constants/moves.h"), "MOVES_")
    assert len(order) == moves_count["MOVES_COUNT"], f"{repo}: {len(order)} blocks vs MOVES_COUNT"
    return {ids[name]: stats[name] for name in order}


def _item_ids(repo: str) -> dict[int, str]:
    text = _read(repo, "include/constants/items.h")
    # Only parse items defined before ITEMS_COUNT; usage-type aliases come after
    items_count_idx = text.find("#define ITEMS_COUNT")
    if items_count_idx != -1:
        text = text[:items_count_idx]
    items = _constants(text, "ITEM_")
    return {v: k for k, v in items.items()}


# --- moves ---

@needs_pret
def test_both_titles_declare_the_same_355_moves():
    """Gen 3 has one move table: 355 gBattleMoves blocks (MOVE_NONE .. MOVE_PSYCHO_BOOST)."""
    frlg, emerald = _move_tables(PRET_FRLG)[1], _move_tables(PRET_EMERALD)[1]
    assert len(frlg) == len(emerald) == 355
    assert set(frlg) == set(emerald), f"symmetric difference: {sorted(set(frlg) ^ set(emerald))}"
    assert "MOVE_NONE" in frlg and "MOVE_PSYCHO_BOOST" in frlg


@needs_pret
def test_move_stats_are_identical_in_both_titles():
    """PLAN.md records the two battle_moves.h as not byte-identical while the four
    stats are equal. If that ever stops being true, the shared table is a lie --
    so this compares values, not the assumption. Except: KNOWN_MOVE_DIFFS lists real pret divergences."""
    frlg, emerald = _by_move_id(PRET_FRLG), _by_move_id(PRET_EMERALD)
    assert set(frlg) == set(emerald)
    move_ids_frlg = _move_ids(PRET_FRLG)
    known_diff_ids = {move_ids_frlg[name] for name in KNOWN_MOVE_DIFFS}
    mismatches = [
        (mid, {f: frlg[mid][f] for f in MOVE_FIELDS}, {f: emerald[mid][f] for f in MOVE_FIELDS})
        for mid in sorted(frlg)
        if any(frlg[mid][f] != emerald[mid][f] for f in MOVE_FIELDS)
        and mid not in known_diff_ids
    ]
    assert not mismatches, f"{len(mismatches)} move(s) differ: {mismatches[:8]}"
    # Verify known differences exist and match the table exactly
    for move_name, expected_diffs in KNOWN_MOVE_DIFFS.items():
        mid = move_ids_frlg[move_name]
        for field, (frlg_val, emerald_val) in expected_diffs.items():
            assert frlg[mid][field] == frlg_val, f"{move_name}: FRLG {field} should be {frlg_val}, got {frlg[mid][field]}"
            assert emerald[mid][field] == emerald_val, f"{move_name}: Emerald {field} should be {emerald_val}, got {emerald[mid][field]}"


@needs_pret
def test_vanilla_move_module_matches_the_parsed_pret_tables():
    """server/data/moves/gen3_vanilla.py is keyed by move id (tools/gen_move_data.py
    numbers blocks positionally; _by_move_id pins that those two agree), so this is
    a direct value comparison, not a name lookup. Module is built from FRLG; Emerald
    has known differences (E3) that this test skips."""
    move_ids_frlg = _move_ids(PRET_FRLG)
    known_diff_ids = {move_ids_frlg[name] for name in KNOWN_MOVE_DIFFS}

    for repo in (PRET_FRLG, PRET_EMERALD):
        parsed = _by_move_id(repo)
        assert set(parsed) == set(VANILLA_MOVE_DATA), f"{repo}: id set differs"
        wrong = {
            mid: {f: (parsed[mid][f], VANILLA_MOVE_DATA[mid][f]) for f in MOVE_FIELDS
                  if parsed[mid][f] != VANILLA_MOVE_DATA[mid][f]}
            for mid in sorted(parsed)
            if mid not in known_diff_ids
        }
        wrong = {mid: diff for mid, diff in wrong.items() if diff}
        assert not wrong, f"{repo}: {len(wrong)} move(s) wrong (parsed, module): {dict(list(wrong.items())[:8])}"


# --- items ---

@needs_pret
def test_item_ids_0_to_374_carry_the_same_names_in_both_titles():
    frlg, emerald = _item_ids(PRET_FRLG), _item_ids(PRET_EMERALD)
    # 0-374 are the ids both titles share; 375/376 are Emerald-only (the next test).
    shared = range(EMERALD_ONLY_FIRST)
    missing = {i: (frlg.get(i), emerald.get(i)) for i in shared if not (i in frlg and i in emerald)}
    assert not missing, f"ids present in one title only: {missing}"
    renamed = [
        (i, frlg[i], emerald[i])
        for i in shared
        if frlg[i] != emerald[i]
        and not _PLACEHOLDER_RE.match(frlg[i])
        and not _PLACEHOLDER_RE.match(emerald[i])
    ]
    assert not renamed, f"{len(renamed)} renamed id(s): {renamed[:8]}"


@needs_pret
def test_emerald_alone_adds_exactly_the_two_emerald_items():
    frlg, emerald = _item_ids(PRET_FRLG), _item_ids(PRET_EMERALD)
    for item_id, name in EMERALD_ONLY:
        assert emerald[item_id] == name, f"pokeemerald id {item_id} is {emerald.get(item_id)!r}, not {name}"
    assert [i for i in emerald if i >= EMERALD_ONLY_FIRST] == [i for i, _ in EMERALD_ONLY]
    leaked = sorted(i for i in frlg if i >= EMERALD_ONLY_FIRST)
    assert not leaked, f"pokefirered has no Emerald items, found {leaked}"


@needs_pret
def test_emerald_items_count_is_377_and_frlgs_is_375():
    assert _constants(_read(PRET_EMERALD, "include/constants/items.h"), "ITEMS_") == {"ITEMS_COUNT": 377}
    assert _constants(_read(PRET_FRLG, "include/constants/items.h"), "ITEMS_") == {"ITEMS_COUNT": 375}


def test_vanilla_item_module_contains_no_emerald_only_id():
    """5f050857 fixed the FRLG table to 0-374; 375/376 are a title overlay, not this table."""
    assert not [i for i in VANILLA_ITEM_NAMES if i >= 375], f"leaked Emerald ids: {sorted(i for i in VANILLA_ITEM_NAMES if i >= 375)}"
