"""pureRGB species/types pack (data/games/gen1_purergb/{species_index,types}.json).

Internal id is the only safe key (docs/purergb/PLAN.md S3.3): forms/spirits share a
dex number with their base species, so keying by dex would collide. The ROM-agreement
tests are skipped without a pinned pureRGB checkout -- `tools/gen_gen1_species.py`
itself already fails loudly on any ROM/source disagreement across all three titles,
these tests just pin the facts a consumer needs to hold going forward.
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACK = os.path.join(REPO, "data", "games", "gen1_purergb")
sys.path.insert(0, os.path.join(REPO, "tools"))


def _load(name):
    path = os.path.join(PACK, name)
    if not os.path.exists(path):
        pytest.skip(f"{path} missing -- regenerate with tools/gen_gen1_species.py --foundation purergb")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def species_index():
    return _load("species_index.json")


@pytest.fixture(scope="module")
def types_doc():
    return _load("types.json")


def test_all_190_internal_ids_present(species_index):
    assert sorted(int(k) for k in species_index["species"]) == list(range(1, 191))


def test_classification_counts(species_index):
    counts = {}
    for row in species_index["species"].values():
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    assert counts == {
        "ordinary": 151, "form": 7, "spirit": 5, "missingno": 1,
        "picture_only": 3, "unused": 23,
    }


def test_missingno_is_dex_zero_and_obtainable(species_index):
    row = species_index["species"]["181"]  # internal $B5
    assert row["classification"] == "missingno"
    assert row["dex"] == 0
    assert row["obtainable"] is True


def test_spirits_are_not_obtainable(species_index):
    for row in species_index["species"].values():
        if row["classification"] == "spirit":
            assert row["obtainable"] is False, row


def test_form_base_species_points_at_the_base(species_index):
    sp = species_index["species"]
    # Floating Magneton (internal $38 = 56) -> Magneton (internal $36 = 54).
    assert sp["56"]["base_species"] == 54
    # Volcanic Magmar (internal $34 = 52) -> Magmar (internal $33 = 51).
    assert sp["52"]["base_species"] == 51


def test_floating_magneton_types(types_doc, species_index):
    names = types_doc["type_names"]
    t1, t2 = species_index["species"]["56"]["types"]
    assert (names[str(t1)], names[str(t2)]) == ("Electric", "Floating")


def test_transform_edges_count_and_shape(species_index):
    edges = species_index["transform_edges"]
    assert len(edges) == 9
    assert any(e["bidirectional"] for e in edges), "Mewtwo/Armored Mewtwo edge must be bidirectional"


@pytest.mark.skipif(not os.environ.get("SLINK_PURERGB_SRC"), reason="needs a pinned pureRGB checkout + built ROMs")
def test_rom_agrees_with_source_for_a_sample():
    import gen_gen1_species as species_tool
    species_index_doc, types_doc_, disagreements = species_tool.build("purergb")
    assert disagreements == []
    # 35-byte-stride sample: Onix (ordinary, dex 95) and Hardened Onix (form, NonDex:3).
    onix = next(v for v in species_index_doc["species"].values() if v["name"] == "ONIX" and v["classification"] == "ordinary")
    assert onix["stats"] == {"hp": 55, "atk": 25, "def": 180, "spd": 80, "spc": 75}
