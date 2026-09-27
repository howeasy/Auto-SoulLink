"""Catalog completeness for the vanilla Gen 3 titles: FireRed, LeafGreen and Emerald.

A Radical Red audit found wild species the server could not resolve -- `species_types()`
returned None and `species_name()` had no entry, so the board rendered a nameless,
typeless encounter. The committed encounter JSON is a GENERATED artifact
(tools/gen_gen3_wild.py, from pinned pret/pokefirered and pret/pokeemerald), and its
`species_id` values are pret's own `SPECIES_*` constants: the national-dex range 1-386
for FRLG, and the CFRU range 269-410 for Emerald (386-410 are the Hoenn species that
CFRU numbers past Deoxys, e.g. 392 = Ralts, `to_national(392) == 280`). A generator
that reads a different `species.h` revision, or a hand-edit, silently emits ids the
server catalog does not carry. These are the falsifiers for that.

Every read goes through the production seam -- `Gen3Adapter(is_rr=False,
rom_type=...)`, the same object server.py builds from the hello `rom_type` -- so a
catalog regression in pokemon_data.py fails here too. FRLG and Emerald are covered by
the same adapter class and differ only in `rom_type`, so both are parameterized.

FRLG gift/static species are NOT covered: the FRLG pack ships no statics table
(`_FIXED_SPECIES_GIFTS` in server/adapters/gen3_frlge.py:54 is a set of area_ids, not
species), so there is no species list to assert against. Emerald's does exist
(data/games/gen3_emerald/statics.json) and is checked by name at the bottom.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from server.adapters.gen3_frlge import Gen3Adapter
from server.pokemon_data import SPECIES_NAMES

ROOT = Path(__file__).resolve().parents[2]
FRLGE = ROOT / "data" / "games" / "gen3_frlge"
EMERALD = ROOT / "data" / "games" / "gen3_emerald"

# rom_type -> the committed encounter file the adapter loads (gen3_frlge._VANILLA_WILD).
TITLES = {
    "firered": FRLGE / "firered_encounters.json",
    "leafgreen": FRLGE / "leafgreen_encounters.json",
    "emerald": EMERALD / "emerald_encounters.json",
}

# A title that silently loaded nothing would make every species assertion below pass by
# iterating an empty set, so each title has to actually carry a wild dex.
MIN_WILD_SPECIES = 90  # FR/LG carry 99 distinct wild species, Emerald more

CASES = sorted(TITLES.items())


def _adapter(rom_type: str) -> Gen3Adapter:
    return Gen3Adapter(is_rr=False, rom_type=rom_type)


def _unresolved(adapter: Gen3Adapter, species_id: int) -> bool:
    """True when the catalog has no name for `species_id`.

    pokemon_data.species_name() (server/pokemon_data.py:586) never returns empty -- it
    falls back to the literal '#<id>'. Asserting "non-empty" would be a tautology, so
    the falsifier keys on that fallback instead: it is the exact shape a species gap
    takes on the board.
    """
    return adapter.species_name(species_id) == f"#{species_id}"


def _wild_species(rom_type: str) -> dict[int, list[str]]:
    """{species_id: [area_id, ...]} as the ADAPTER serves it, not as the file stores it.

    Reading through `encounter_table` is the point: the file is data, the adapter is
    the contract the server and the client actually consume.
    """
    adapter = _adapter(rom_type)
    areas = json.loads(TITLES[rom_type].read_text(encoding="utf-8"))["encounters"]
    seen: dict[int, list[str]] = {}
    for area_id in areas:
        table = adapter.encounter_table(area_id)
        assert table is not None, f"{rom_type}: {area_id} is committed but the adapter serves None"
        for method, entries in table.items():
            assert entries, f"{rom_type}: {area_id}/{method} is an empty method"
            for entry in entries:
                seen.setdefault(entry["species_id"], []).append(f"{area_id}/{method}")
    return seen


# ── the coverage itself ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rom_type,path", CASES)
def test_the_adapter_serves_every_committed_wild_area(rom_type: str, path: Path) -> None:
    """No committed area may be invisible to the adapter, and none may be invented.

    A renamed or un-loaded encounter file leaves `encounter_table` returning None for
    everything, which blanks the encounters panel for the whole title while every
    other assertion below stays vacuously green.
    """
    committed = json.loads(path.read_text(encoding="utf-8"))["encounters"]
    adapter = _adapter(rom_type)
    served = {area for area in committed if adapter.encounter_table(area) is not None}
    assert served == set(committed), (
        f"{rom_type}: unserved areas {sorted(set(committed) - served)}")


@pytest.mark.parametrize("rom_type,path", CASES)
def test_each_title_really_ships_a_wild_dex(rom_type: str, path: Path) -> None:
    """Guards the vacuous case: an empty table must fail, not pass."""
    species = _wild_species(rom_type)
    assert len(species) >= MIN_WILD_SPECIES, (
        f"{rom_type}: only {len(species)} wild species reachable through the adapter "
        f"(expected at least {MIN_WILD_SPECIES})")


# ── the three catalog falsifiers ────────────────────────────────────────────────────────

@pytest.mark.parametrize("rom_type,path", CASES)
def test_every_wild_species_has_a_name(rom_type: str, path: Path) -> None:
    missing = {sid: sites[0] for sid, sites in sorted(_wild_species(rom_type).items())
               if _unresolved(_adapter(rom_type), sid)}
    assert not missing, f"{rom_type}: species with no catalog name: {missing}"


@pytest.mark.parametrize("rom_type,path", CASES)
def test_every_wild_species_has_types(rom_type: str, path: Path) -> None:
    adapter = _adapter(rom_type)
    missing = {sid: sites[0] for sid, sites in sorted(_wild_species(rom_type).items())
               if adapter.species_types(sid) is None}
    assert not missing, f"{rom_type}: species with no catalog types: {missing}"


@pytest.mark.parametrize("rom_type,path", CASES)
def test_every_wild_species_evo_base_is_in_the_catalog(rom_type: str, path: Path) -> None:
    """The base form must itself be a species the server can name and type.

    The species clause and the dupes reroll both key on `evo_family()`, and the board
    prints the base; an entry pointing outside the catalog (EVO_FAMILY holds CFRU ids
    from several numbering generations) would render the chain header blank.
    """
    adapter = _adapter(rom_type)
    broken: dict[int, tuple[int, str]] = {}
    for sid, sites in sorted(_wild_species(rom_type).items()):
        base = adapter.evo_family(sid)
        if _unresolved(adapter, base) or adapter.species_types(base) is None:
            broken[sid] = (base, sites[0])
    assert not broken, f"{rom_type}: evo base outside the catalog: {broken}"


# ── Emerald gift/static species ─────────────────────────────────────────────────────────

def _canon(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


#: every display name the catalog can produce, canon'd for the macro-name comparison.
_CATALOG_NAMES = {_canon(name) for name in SPECIES_NAMES.values()}


def _static_macros() -> list[str]:
    """Every pret `SPECIES_*` macro statics.json names, flattened across the list and
    scalar spellings of the `species` field (a starter entry carries three)."""
    entries = json.loads((EMERALD / "statics.json").read_text(encoding="utf-8"))["entries"]
    out: list[str] = []
    for entry in entries:
        species = entry.get("species") or []
        out.extend(species if isinstance(species, list) else [species])
    return out

def test_emerald_statics_carry_species_the_server_can_name() -> None:
    """data/games/gen3_emerald/statics.json names species by pret macro, not by id.

    A gift or static the board cannot name links fine and then renders blank, and the
    name is the only thing tying the entry to the catalog, so it is checked here.
    """
    macros = _static_macros()
    assert len(macros) >= 10, f"statics.json shrank to {len(macros)} species: {macros}"
    unknown = sorted(m for m in macros
                     if _canon(m.removeprefix("SPECIES_")) not in _CATALOG_NAMES)
    assert not unknown, f"emerald statics name species outside the catalog: {unknown}"
