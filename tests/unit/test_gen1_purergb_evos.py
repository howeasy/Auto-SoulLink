"""pureRGB evolutions pack (data/games/gen1_purergb/evolutions.json).

Keys are INTERNAL species ids, not national dex (docs/purergb/PLAN.md S3.3: forms
share a dex with their base species, so dex cannot key an edge). pureRGB adds a
level-37 `EVOLVE_LEVEL` beside the existing `EVOLVE_TRADE` for the four classic
trade-evolution species -- same edge, extra method -- so 76 method entries land on
only 72 unique edges; the family count (79) is unchanged from vanilla's shape.
"""
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVOS = os.path.join(REPO, "data", "games", "gen1_purergb", "evolutions.json")
SPECIES = os.path.join(REPO, "data", "games", "gen1_purergb", "species_index.json")


def _load(path):
    if not os.path.exists(path):
        pytest.skip(f"{path} missing -- regenerate with tools/gen_gen1_evos.py --foundation purergb")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def evos():
    return _load(EVOS)


@pytest.fixture(scope="module")
def species():
    return _load(SPECIES)


def test_edge_and_family_counts(evos):
    n_edges = sum(len(v) for v in evos["evolutions"].values())
    n_families = len(set(evos["family"].values()))
    assert (n_edges, n_families) == (72, 79)


def test_eevee_family_is_one_group(evos, species):
    name_to_id = {v["name"]: int(k) for k, v in species["species"].items()
                  if v["classification"] == "ordinary"}
    eevee, flareon, jolteon, vaporeon = (
        name_to_id["EEVEE"], name_to_id["FLAREON"], name_to_id["JOLTEON"], name_to_id["VAPOREON"])
    families = evos["family"]
    assert len({families[str(eevee)], families[str(flareon)], families[str(jolteon)], families[str(vaporeon)]}) == 1


def test_four_trade_species_also_carry_level_37(evos, species):
    """Haunter/Kadabra/Graveler/Machoke: EVOLVE_TRADE *and* EVOLVE_LEVEL 37 -- same
    edge either way, which is exactly why edges (72) < methods (76)."""
    name_to_id = {v["name"]: int(k) for k, v in species["species"].items()
                  if v["classification"] == "ordinary"}
    for from_name, to_name in (("HAUNTER", "GENGAR"), ("KADABRA", "ALAKAZAM"),
                                ("GRAVELER", "GOLEM"), ("MACHOKE", "MACHAMP")):
        src, dst = name_to_id[from_name], name_to_id[to_name]
        assert evos["evolutions"][str(src)] == [dst]


def test_transform_edges_present(evos):
    assert len(evos.get("transform_edges", [])) == 9
