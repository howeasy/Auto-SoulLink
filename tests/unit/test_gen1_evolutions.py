"""Gen 1 evolution families must be Gen 1's, not a later generation's.

`Gen1Adapter.evo_family` used to delegate to `pokemon_data.base_form(sid, False)`,
the CFRU/Gen 3+ table. That answers "what is the earliest form of this line in a
MODERN game", which for Gen 1 species produces groupings RBY has no concept of:

    base_form(106) == base_form(107) == 236     # Tyrogue

Hitmonlee and Hitmonchan are unrelated in RBY — `pokered/data/pokemon/evos_moves.asm`
gives both an empty evolution list (`:683`, `:694`). The Fighting Dojo lets you take
exactly one, so the canonical Soul Link split (A takes Hitmonlee, B takes Hitmonchan)
was rejected by the species clause, and `state.py` force-fainted and memorialised a
live mon.

THE OBVIOUS FIX WAS WRONG, WHICH IS WHY THIS FILE EXISTS. Clamping `base_form()`
to 1..151 looks like a one-line repair. Enumerating every merge over species 1..151
shows 236:[106,107] is the ONLY one joining unrelated species; 172:[25,26],
173:[35,36] and 174:[39,40] are *real* families remapped to a Gen 2 baby form. A
clamp would have split Pikachu/Raichu, Clefairy/Clefable and Jigglypuff/Wigglytuff
and broken the species clause for three legitimate lines. `test_real_families_stay_together`
is the assertion that would have caught it.
"""
import json
import os

import pytest

from server.adapters.gen1_rby import Gen1Adapter

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVOS = os.path.join(REPO, "data", "games", "gen1_rby", "evolutions.json")


@pytest.fixture
def adapter():
    return Gen1Adapter()


def test_evolutions_json_exists():
    """Without it `evo_family` degrades to identity and the clause under-rejects."""
    assert os.path.exists(EVOS), (
        "data/games/gen1_rby/evolutions.json is missing — regenerate with "
        "`python tools/gen_gen1_evos.py`")


def test_the_hitmons_are_not_the_same_family(adapter):
    """The bug this file exists for. Tyrogue does not exist in Gen 1."""
    assert adapter.evo_family(106) != adapter.evo_family(107), (
        "Hitmonlee and Hitmonchan share an evolution family — the Fighting Dojo "
        "split will be rejected by the species clause and one mon buried")


@pytest.mark.parametrize("a,b", [
    (25, 26),     # Pikachu / Raichu        — base_form maps both to 172 (Pichu)
    (35, 36),     # Clefairy / Clefable     — 173 (Cleffa)
    (39, 40),     # Jigglypuff / Wigglytuff — 174 (Igglybuff)
])
def test_real_families_stay_together(adapter, a, b):
    """These are the three lines a `base_form()` clamp would have wrongly split."""
    assert adapter.evo_family(a) == adapter.evo_family(b)


@pytest.mark.parametrize("members", [
    (1, 2, 3),              # Bulbasaur line
    (4, 5, 6),              # Charmander line
    (7, 8, 9),              # Squirtle line
    (63, 64, 65),           # Abra line
    (129, 130),             # Magikarp / Gyarados
    (133, 134, 135, 136),   # Eevee + the three eeveelutions
])
def test_known_lines_share_one_family(adapter, members):
    fams = {adapter.evo_family(m) for m in members}
    assert len(fams) == 1, f"{members} split across families {fams}"


@pytest.mark.parametrize("a,b", [
    (150, 151),   # Mewtwo / Mew        — related in lore, not by evolution
    (124, 125),   # Jynx / Electabuzz   — base_form gives them adjacent Gen 2 babies
    (125, 126),   # Electabuzz / Magmar
    (83, 84),     # Farfetch'd / Doduo  — adjacent dex, unrelated
])
def test_unrelated_species_stay_apart(adapter, a, b):
    assert adapter.evo_family(a) != adapter.evo_family(b)


def test_family_is_an_equivalence_relation(adapter):
    """Reflexive, symmetric and transitive — a clause comparing representatives
    for equality is only correct if the mapping is a genuine partition."""
    for sid in range(1, 152):
        assert adapter.evo_family(sid) == adapter.evo_family(adapter.evo_family(sid)), (
            f"species {sid}: family representative is not its own representative")


def test_every_gen1_species_is_classified(adapter):
    for sid in range(1, 152):
        fam = adapter.evo_family(sid)
        assert 1 <= fam <= 151, f"species {sid} maps outside Gen 1 range: {fam}"


def test_family_count_matches_edge_count():
    """151 species minus 72 evolution edges = 79 families.

    A mismatch means the generator emitted a duplicate or cyclic edge, which
    union-find would silently absorb.
    """
    with open(EVOS) as f:
        data = json.load(f)
    edges = sum(len(v) for v in data["evolutions"].values())
    families = len(set(data["family"].values()))
    assert edges == 72, f"expected 72 evolution edges from pret, got {edges}"
    assert families == 151 - edges, (
        f"{families} families from {edges} edges over 151 species — "
        f"expected {151 - edges}; a duplicate or cyclic edge was absorbed")


def test_unknown_species_is_its_own_family(adapter):
    """MissingNo and glitch ids must not all collapse into one family.

    `evo_family(0) == 0` previously meant two glitch mons tripped the species
    clause against each other.
    """
    assert adapter.evo_family(9999) == 9999
