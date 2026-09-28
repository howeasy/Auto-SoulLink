"""Falsifier for the pokeemerald-expansion wild tables (card EXP-DATA-WILD).

data/games/gen3_exp/28877d73/expansion_encounters.json is generated from the pinned expansion
source by tools/gen_gen3_exp_wild.py, and served by Gen3ExpansionAdapter.encounter_table(). This
file re-derives the pack from the pin INDEPENDENTLY -- its own reader for the wild group, its own
field/method/rod split, its own first-map-wins reduction -- so a generator that parses the pin
wrong is visible here instead of agreeing with itself. What is deliberately NOT re-implemented is
the map numbering (tools/gen_gen3_trainers.map_keys) and the slot weights
(server.adapters.gen3_frlge._WILD_METHODS): those are shared, separately-pinned helpers, and the
test's job is to hold the generator to them.

Controls, in the order a reviewer should want them:
  1. source slot multiset -- per (area_id, method), the pack's summed rate must equal the SOURCE's
     own slots for that cell. Additive, so a reduction that dropped, duplicated or invented a slot
     cannot satisfy it even if the same wrong reduction ran on both sides.
  2. per-entry equality after reduction -- species, summed rate, min and max level, every cell.
  3. slot chance -- the pin's declared `encounter_rates`/`groups` must equal the repo's proven
     _WILD_METHODS, and the rod `groups` must be ascending runs that partition the fishing slots.
     This is the "no invented chance weights, no conflated rods" check: the rod split is read from
     the pin's index lists, never re-guessed as 0-1/2-4/5-9.
  4. unknown area -- encounter_table() answers None for a blank/unknown area id and a real table
     for a real one (the positive half is what stops an always-None method from passing).
  5. copy isolation -- the returned table is a deepcopy; mutating it cannot corrupt the cached pack.
  6. generator check -- `--check` really runs and really passes against a regeneration.

Plus the pack-only oracles that need no source: the pin binding, the fail-closed loader, lazy
loading, client-emittable area ids, adapter-owned species names, and the Frontier/scope bound.

SOURCE/MODEL only: the pack is the source's DECLARED table. No ROM read-back has been performed,
so nothing here may be read as ROM-verified.

The pinned source (data/gen3_exp_sources.lock.json: tag expansion/1.17.0, commit
e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7) is not checked into this repo. Point
SLINK_EXPANSION_SRC at a checkout, or keep one at .cache/expansion-src (this build host) or
.cache/expansion/<commit>; an absent source is a named skip, but a PRESENT source at the wrong
commit -- or a present checkout missing one of the files the controls read -- is a hard failure,
never a silent pass.
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

from server.adapters import gen3_expansion as _gen3_expansion_mod, gen3_frlge  # noqa: E402
from server.adapters.gen3_expansion import ROM_TYPE, Gen3ExpansionAdapter  # noqa: E402
from tools.gen_gen3_exp_trainers import enum_values  # noqa: E402
from tools.gen_gen3_trainers import map_keys  # noqa: E402

_LOCK = json.loads((_REPO / "data/gen3_exp_sources.lock.json").read_text(encoding="utf-8"))
_PIN = _LOCK["source"]["commit"]
_JSON_PACK = _REPO / "data/games/gen3_exp/28877d73/expansion_encounters.json"
_AREA_MAP = _REPO / "data/games/gen3_exp/28877d73/area_map.json"
_AREAS_LUA = _REPO / "data/games/gen3_exp/28877d73/gen3_exp_areas.lua"
_WILD_JSON = "src/data/wild_encounters.json"
# Every source file the generator and the controls below read. A checkout missing any of them
# cannot produce the pack, and running a reduced control set against a partial tree would look
# like a pass.
_NEEDED = ("src/data/wild_encounters.json", "include/constants/species.h",
           "data/maps/map_groups.json", "src/data/region_map/region_map_sections.json",
           "include/config/wild_encounter.h", "include/config/overworld.h")

# The repo's one table of Gen 3 slot weights, transcribed from pret src/wild_encounter.c:73-160
# (server/adapters/gen3_frlge.py). Deliberately shared with the generator, not retyped: the
# generator refuses to ship weights that differ from this, and the test proves that refusal's
# premise (the pin agrees with pret's table) rather than trusting the generator's copy.
_PROVEN: dict[tuple[str, str], tuple[int, ...]] = {
    (habitat, method): tuple(rates)
    for habitat, methods in gen3_frlge._WILD_METHODS
    for method, rates in methods
}


# ── pinned source ────────────────────────────────────────────────────────────────────────────

def _find_expansion_src() -> Path | None:
    env = os.environ.get("SLINK_EXPANSION_SRC")
    if env:
        return Path(env)
    d = _REPO
    for _ in range(6):
        for rel in (".cache/expansion-src", f".cache/expansion/{_PIN}"):
            if (d / rel).is_dir():
                return d / rel
        parent = d.parent
        if parent == d:
            break
        d = parent
    return None


def _git_head(path: Path) -> str | None:
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def _need_source() -> Path:
    src = _find_expansion_src()
    if src is None:
        pytest.skip(f"pokeemerald-expansion checkout not found (set SLINK_EXPANSION_SRC; pin {_PIN})")
    head = _git_head(src)
    assert head == _PIN, f"{src} is at {head}, not the pin {_PIN} (data/gen3_exp_sources.lock.json)"
    missing = [rel for rel in _NEEDED if not (src / rel).exists()]
    assert not missing, (f"{src} is at the pin but is missing {missing}; the source-gated "
                         "controls below would silently cover less than they claim")
    # map_keys() reads every grouped folder's own map.json; a tree with none cannot number a map.
    assert next((src / "data/maps").glob("*/map.json"), None), \
        f"{src}/data/maps has no */map.json -- map numbering cannot be re-derived"
    return src


# ── pack / adapter helpers ──────────────────────────────────────────────────────────────────

def _adapter() -> Gen3ExpansionAdapter:
    return Gen3ExpansionAdapter(rom_type=ROM_TYPE)


def _pack() -> dict:
    return json.loads(_JSON_PACK.read_text(encoding="utf-8"))


def _area_map() -> dict:
    return json.loads(_AREA_MAP.read_text(encoding="utf-8"))


# ── the pin, read this file's own way ────────────────────────────────────────────────────────

def _wild_group(data: dict) -> dict:
    """The single for_maps group. gBattlePyramid/gBattlePike headers are Frontier tables with no
    `map` key and no area_id; they are not map wild encounters and must not be extracted."""
    groups = [g for g in data["wild_encounter_groups"] if g.get("for_maps")]
    assert [g.get("label") for g in groups] == ["gWildMonHeaders"]
    return groups[0]


def _pin_wild(src: Path) -> dict:
    return _wild_group(json.loads((src / _WILD_JSON).read_text(encoding="utf-8")))


def _pin_plan(src: Path) -> list[tuple[str, list[tuple[str, list[int]]]]]:
    """[(habitat, [(method, [slot rates])]), ...] from the pin's own `fields` block.

    The rod split comes from the fishing field's `groups` index lists -- the test's own reading,
    written separately from the generator's so a wrong split shows up as a disagreement rather
    than as two copies of the same mistake. The ungrouped habitat labels (Grass / Surfing /
    Rock Smash) are taken from _PROVEN: the source declares no labels, and control 3 below is
    what proves _PROVEN is the right label vocabulary for this pin.
    """
    plan = []
    for field in _pin_wild(src)["fields"]:
        rates = [int(r) for r in field["encounter_rates"]]
        groups = field.get("groups")
        if groups:
            methods = [(" ".join(w.capitalize() for w in name.split("_")),
                        [rates[i] for i in indexes]) for name, indexes in groups.items()]
        else:
            bare = field["type"].removesuffix("_mons")  # pin says land_mons, _PROVEN says land
            labels = [m for (habitat, m) in _PROVEN if habitat == bare]
            assert len(labels) == 1, f"no proven method label for habitat {field['type']!r}"
            methods = [(labels[0], rates)]
        plan.append((field["type"], methods))
    return plan


def _pin_cells(src: Path) -> dict[tuple[str, str], list[tuple[str, int, int, int]]]:
    """(area_id, method) -> the source's RAW slots as (species macro, rate, min, max), no
    aggregation. Control 1 compares this additively against the pack, so it holds whatever the
    generator's reduction does."""
    area_map = _area_map()
    positions = {map_id: tuple(int(p) for p in key.split(":"))
                 for map_id, key in map_keys(src).items()}
    plan = _pin_plan(src)                   # once: the wild JSON is ~1.5 MB, re-read per map is not
    first_set: dict[tuple[int, int], dict] = {}
    for entry in _pin_wild(src)["encounters"]:
        pos = positions.get(entry["map"])
        if pos is None or pos in first_set:
            continue                        # unmapped, or a later set for the same map: not "set 0"
        first_set[pos] = entry
    cells: dict[tuple[str, str], list[tuple[str, int, int, int]]] = {}
    for pos in sorted(first_set):           # (group, num) as ints: 0:10 after 0:9
        area = area_map.get(f"{pos[0]}:{pos[1]}")
        if not area:
            continue
        entry = first_set[pos]
        for habitat, methods in plan:
            table = entry.get(habitat)
            if table is None:
                continue
            mons = table["mons"]
            offset = 0
            for method, rates in methods:
                if (area, method) not in cells:  # first map wins per area AND per method
                    cells[(area, method)] = [
                        (mons[offset + i]["species"], rate,
                         mons[offset + i]["min_level"], mons[offset + i]["max_level"])
                        for i, rate in enumerate(rates)]
                offset += len(rates)
    return cells


def _pin_reduced(src: Path) -> dict[tuple[str, str], dict[str, tuple[int, int, int]]]:
    """(area_id, method) -> species macro -> (summed rate, min level, max level), using this
    file's own reduction of _pin_cells(). Control 2 compares it to the pack cell for cell."""
    out: dict[tuple[str, str], dict[str, tuple[int, int, int]]] = {}
    for cell, slots in _pin_cells(src).items():
        agg: dict[str, list[int]] = {}
        for macro, rate, low, high in slots:
            cur = agg.setdefault(macro, [0, low, high])
            cur[0] += rate
            cur[1] = min(cur[1], low)
            cur[2] = max(cur[2], high)
        out[cell] = {macro: tuple(v) for macro, v in agg.items()}
    return out


# ── 1. source slot multiset (additive) ───────────────────────────────────────────────────────

def test_source_slot_multiset_matches_the_pin():
    """Whole-file, every (area_id, method): the pack's summed rate equals the source's own slot
    rates for that cell, and the pack has exactly one entry per distinct source species. Additive
    and reduction-independent -- a dropped, duplicated or invented slot fails here even if the
    same wrong reduction is applied to both sides."""
    src = _need_source()
    pack = _pack()["encounters"]
    cells = _pin_cells(src)
    assert cells, "the pin declares no wild cells at all"
    for (area, method), slots in cells.items():
        entries = pack[area][method]
        assert sum(e["rate"] for e in entries) == sum(rate for _, rate, _, _ in slots), (area, method)
        assert len(entries) == len({macro for macro, _, _, _ in slots}), (area, method)
    assert {(a, m) for a in pack for m in pack[a]} == set(cells)


# ── 2. per-entry equality after reduction ───────────────────────────────────────────────────

def test_every_entry_matches_the_pin_after_reduction():
    """Species, summed rate, min level and max level, cell for cell -- the full projection, not
    just the totals control 1 checks."""
    src = _need_source()
    species = enum_values((src / "include/constants/species.h").read_text(encoding="utf-8"), "SPECIES_")
    assert species, "include/constants/species.h yielded no SPECIES_ values"
    expected = {(area, method): {species[macro]: value for macro, value in per_species.items()}
                for (area, method), per_species in _pin_reduced(src).items()}
    actual = {(area, method): {e["species_id"]: (e["rate"], e["min_level"], e["max_level"])
                               for e in entries}
              for area, block in _pack()["encounters"].items()
              for method, entries in block.items()}
    assert actual == expected


# ── 3. slot chance ───────────────────────────────────────────────────────────────────────────

def test_slot_chance_weights_come_from_the_pin_not_a_constant():
    """The pin's declared per-method rate vectors must equal the repo's proven _WILD_METHODS, so
    the pack's weights are the source's own and are cross-checked against pret
    src/wild_encounter.c rather than invented here."""
    src = _need_source()
    declared = {(habitat.removesuffix("_mons"), method): tuple(rates)
                for habitat, methods in _pin_plan(src)
                for method, rates in methods}
    assert declared == _PROVEN

    # And the SHIPPED pack must carry those same weights, rod by rod. Summing the pack's entries
    # per rod over every fishing area preserves the total whatever the within-cell aggregation did,
    # so this is exact -- a merged fishing table, or Old Rod's slots handed to Good Rod, cannot
    # reproduce three per-rod totals even when each cell's 10-slot partition still balances.
    fishing_methods = {m for (habitat, m) in _PROVEN if habitat == "fishing"}
    cells = _pin_cells(src)
    want: dict[str, int] = {}
    for (_area, method), slots in cells.items():
        if method in fishing_methods:
            want[method] = want.get(method, 0) + sum(rate for _, rate, _, _ in slots)
    assert set(want) == fishing_methods, sorted(want)
    for method in fishing_methods:
        cell_count = sum(1 for _cell, m in cells if m == method)
        assert want[method] == sum(_PROVEN[("fishing", method)]) * cell_count, (method, want[method])
    got: dict[str, int] = {}
    for block in _pack()["encounters"].values():
        for method, entries in block.items():
            if method in fishing_methods:
                got[method] = got.get(method, 0) + sum(e["rate"] for e in entries)
    assert got == want, (got, want)


def test_fishing_rods_partition_the_declared_slots_in_ascending_runs():
    """The rod split is the pin's `groups` index lists. Each rod must be a contiguous ascending
    run and the three rods must partition the ten fishing slots exactly once -- the check that
    stops a re-guessed 0-1/2-4/5-9 (or a rod sharing a slot with another) from being what the
    board shows."""
    src = _need_source()
    fishing = next(f for f in _pin_wild(src)["fields"] if f["type"] == "fishing_mons")
    groups = fishing["groups"]
    total = len(fishing["encounter_rates"])
    assert sorted(groups) == ["good_rod", "old_rod", "super_rod"]
    taken: list[int] = []
    for name, indexes in groups.items():
        assert indexes == sorted(indexes) and len(set(indexes)) == len(indexes), name
        taken += indexes
    assert sorted(taken) == list(range(total)), (groups, total)
    # Each rod's rate vector must equal the proven table's row for THAT rod: a merged fishing
    # table, or Old Rod's slots handed to Good Rod, fails here even when the 10-slot partition
    # above still balances out.
    rod_rates = {name: tuple(int(fishing["encounter_rates"][i]) for i in indexes)
                 for name, indexes in groups.items()}
    assert rod_rates == {"old_rod": _PROVEN[("fishing", "Old Rod")],
                         "good_rod": _PROVEN[("fishing", "Good Rod")],
                         "super_rod": _PROVEN[("fishing", "Super Rod")]}, rod_rates


def test_pack_entries_are_ranked_by_descending_rate_and_carry_a_real_weighting():
    """Pack-only half of control 3: every cell is ordered by (-rate, species_id) as the board and
    stream overlays assume, no rate is zero or negative, and at least one cell in the shipped pack
    has genuinely unequal rates -- a flat or uniformly-weighted table fails here."""
    pack = _pack()["encounters"]
    unequal = 0
    for area, block in pack.items():
        for method, entries in block.items():
            assert entries == sorted(entries, key=lambda e: (-e["rate"], e["species_id"])), (area, method)
            assert all(e["rate"] > 0 for e in entries), (area, method)
            assert all(e["min_level"] <= e["max_level"] for e in entries), (area, method)
            if len({e["rate"] for e in entries}) > 1:
                unequal += 1
    assert unequal, "every wild cell has a single flat rate -- the slot weights did not survive"
    assert pack, "the pack has no wild tables at all"


# ── 4. unknown area ──────────────────────────────────────────────────────────────────────────

def test_unknown_area_returns_none_but_a_known_area_does_not():
    """A blank or unknown area_id is None, never an empty dict (the board keys off the truthiness
    of the result), and a real area from the pack still answers -- the positive half is what stops
    an always-None method from passing this."""
    a = _adapter()
    assert a.encounter_table("") is None
    assert a.encounter_table("   ") is None
    assert a.encounter_table("__no_such_area__") is None
    assert a.encounter_table("route_9999") is None
    known = next(iter(_pack()["encounters"]))
    table = a.encounter_table(known)
    assert table, known
    assert set(table) <= {"Grass", "Surfing", "Rock Smash", "Old Rod", "Good Rod", "Super Rod"}


def test_every_area_the_pack_carries_is_one_the_client_can_emit():
    """area_id is what lua/gen3/reads.lua sends; an id nothing emits would put a wild table on a
    row the client never produces. Cross-checked against gen3_exp_areas.lua's values, not the pack."""
    valid = set(re.findall(r'=\s*"([^"]+)"', _AREAS_LUA.read_text(encoding="utf-8")))
    areas = _pack()["encounters"]
    assert areas
    for area in areas:
        assert area in valid, area
        assert area in set(_area_map().values()), area


# ── 5. copy isolation ───────────────────────────────────────────────────────────────────────

def test_encounter_table_is_copy_isolated():
    """The pack is process-wide cached, so a caller that mutates what it was handed would corrupt
    every later read. Mutate deeply, then prove a fresh call is untouched."""
    a = _adapter()
    area = next(iter(_pack()["encounters"]))
    first = a.encounter_table(area)
    method = next(iter(first))
    first[method][0]["rate"] = -999
    first[method][0]["min_level"] = -1
    first["Injected Method"] = [{"species_id": 0, "name": "Injected", "rate": 1,
                                 "min_level": 1, "max_level": 1}]
    second = a.encounter_table(area)
    assert "Injected Method" not in second
    assert all(e["rate"] != -999 and e["min_level"] != -1
               for entries in second.values() for e in entries)
    assert second == _pack()["encounters"][area]


# ── 6. generator check ──────────────────────────────────────────────────────────────────────

def test_generator_check_passes_against_a_regenerated_copy():
    src = _need_source()
    r = subprocess.run([sys.executable, str(_REPO / "tools/gen_gen3_exp_wild.py"),
                        "--src", str(src), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_generator_refuses_a_source_at_another_commit(tmp_path):
    """The area-map digest covers map_groups.json and wild_encounters.json but NOT
    include/constants/species.h, the file every species id in the pack comes from -- so a
    checkout at another commit is refused on the pin itself, not on the digest."""
    src = _need_source()
    for rel in _NEEDED:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text((src / rel).read_text(encoding="utf-8"), encoding="utf-8")
    r = subprocess.run([sys.executable, str(_REPO / "tools/gen_gen3_exp_wild.py"),
                        "--src", str(tmp_path), "--check"], capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert _PIN in r.stderr


def test_generator_refuses_dirty_tracked_source_at_the_pin(monkeypatch, capsys):
    """A species.h edit at the pinned HEAD is not covered by the area-map digest."""
    from tools import gen_gen3_exp_wild as generator

    src = _need_source()
    assert generator.tracked_changes(src) == "", "the shared pinned source must be clean"
    monkeypatch.setattr(generator, "tracked_changes", lambda _src: " M include/constants/species.h")
    monkeypatch.setattr(sys, "argv", ["gen_gen3_exp_wild.py", "--src", str(src), "--check"])
    assert generator.main() == 2
    assert "dirty tracked source" in capsys.readouterr().err


# ── pack-only oracles (no pinned source needed) ─────────────────────────────────────────────

def test_encounters_pack_is_bound_to_the_pin():
    pack = _pack()
    assert pack["source"]["commit"] == _PIN, "the pack was built from another source commit"
    assert pack["title"] == ROM_TYPE


def test_encounters_pack_source_mismatch_fails_closed(tmp_path, monkeypatch):
    """A present pack whose source.commit does not match the lock must raise, never serve
    stale/wrong wild tables quietly."""
    bad = _pack()
    bad["source"]["commit"] = "0" * 40
    bad_path = tmp_path / "expansion_encounters.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr(_gen3_expansion_mod, "ENCOUNTERS_PACK", bad_path)
    _gen3_expansion_mod._load_encounters_pack.cache_clear()
    try:
        with pytest.raises(ValueError):
            _gen3_expansion_mod._load_encounters_pack()
    finally:
        _gen3_expansion_mod._load_encounters_pack.cache_clear()


def test_encounters_pack_is_lazy_loaded():
    """Constructing the adapter (what calc_profile() and a Manager render do) must not parse the
    wild pack; only an encounter_table() call should."""
    _gen3_expansion_mod._load_encounters_pack.cache_clear()
    try:
        a = Gen3ExpansionAdapter(rom_type=ROM_TYPE)
        assert _gen3_expansion_mod._load_encounters_pack.cache_info().currsize == 0
        assert a.calc_profile() is not None
        assert _gen3_expansion_mod._load_encounters_pack.cache_info().currsize == 0
        a.encounter_table(next(iter(_pack()["encounters"])))
        assert _gen3_expansion_mod._load_encounters_pack.cache_info().currsize == 1
    finally:
        _gen3_expansion_mod._load_encounters_pack.cache_clear()


def test_pack_species_names_are_the_adapters_own():
    """A wild row must be spelled the way the rest of the board spells that species, and must not
    be the adapter's "Species #N" fallback -- that would mean data.json has no row for an id the
    pin's species.h defines."""
    a = _adapter()
    checked = 0
    for area, block in _pack()["encounters"].items():
        for method, entries in block.items():
            for entry in entries:
                assert not entry["name"].startswith("Species #"), (area, method, entry)
                assert entry["name"] == a.species_name(entry["species_id"]), (area, method, entry)
                checked += 1
    assert checked


def test_unmapped_and_skipped_sets_are_reported_not_silently_dropped():
    """A map with encounters but no area_id, and a map shipping more than one wild set, are both
    named in the pack instead of being lost quietly. Both lists must equal what the pin implies."""
    src = _need_source()
    area_map = _area_map()
    positions = {map_id: tuple(int(p) for p in key.split(":"))
                 for map_id, key in map_keys(src).items()}
    seen, alt, unmapped = set(), [], []
    for entry in _pin_wild(src)["encounters"]:
        pos = positions.get(entry["map"])
        if pos is None:
            unmapped.append(entry["map"])
            continue
        if pos in seen:
            alt.append(entry["map"])
            continue
        seen.add(pos)
        if f"{pos[0]}:{pos[1]}" not in area_map:
            unmapped.append(entry["map"])
    pack = _pack()
    assert pack["unmapped_maps"] == sorted(set(unmapped))
    assert pack["alt_sets_skipped"] == sorted(set(alt))


def test_only_the_map_group_is_extracted_and_the_build_declares_no_others():
    """Scope bound, from the pin. The two non-for_maps groups are Frontier tables (no `map` key),
    so nothing in the pack can come from them; and this build compiles out Overworld Wild
    Encounters and time-of-day tables, so gWildMonHeaders is the whole map wild story and the
    single-method shape is the right one. If a future build turns either on, this fails before the
    pack can quietly become incomplete."""
    src = _need_source()
    groups = {g["label"]: g for g in json.loads(
        (src / _WILD_JSON).read_text(encoding="utf-8"))["wild_encounter_groups"]}
    for label, group in groups.items():
        if label != "gWildMonHeaders":
            assert not group.get("for_maps"), label
            assert all("map" not in e for e in group["encounters"]), label
    config = (src / "include/config/wild_encounter.h").read_text(encoding="utf-8")
    assert re.search(r"#define\s+WE_OW_ENCOUNTERS\s+FALSE", config), "OWE now compiled in?"
    assert re.search(r"#define\s+WE_FLAG_NO_ENCOUNTER\s+0\b", config)
    overworld = (src / "include/config/overworld.h").read_text(encoding="utf-8")
    assert re.search(r"#define\s+OW_TIME_OF_DAY_ENCOUNTERS\s+FALSE", overworld), \
        "time-of-day tables now compiled in?"


def test_no_time_of_day_suffix_and_no_hidden_habitat_in_the_pin():
    """The reduction is one method per habitat with no Morn/Day/Nite axis, which is only true
    because the pin carries no time-suffixed base_labels and no hidden-mons habitat. A hidden
    habitat appearing here is the one that would silently vanish from the pack."""
    src = _need_source()
    habitats = {f["type"] for f in _pin_wild(src)["fields"]}
    assert habitats == {"land_mons", "water_mons", "rock_smash_mons", "fishing_mons"}, habitats
    for entry in _pin_wild(src)["encounters"]:
        assert not re.search(r"_(MORNING|DAY|EVENING|NIGHT)$", entry["base_label"]), entry
    # One C symbol per base_label: the build's header tool makes gXxxInfo/gXxx arrays straight from
    # these names, so two maps sharing one would compile into the same table.
    labels = [e["base_label"] for e in _pin_wild(src)["encounters"]]
    duplicates = [label for label, n in Counter(labels).items() if n > 1]
    assert not duplicates, duplicates
