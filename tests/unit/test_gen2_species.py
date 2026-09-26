"""Independent controls for selected Gen 2 species packs; SOURCE/MODEL only."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen_gen2_species as species  # noqa: E402


@pytest.fixture(scope="module")
def packs():
    return {title: species.build(title) for title in ("crystal", "gold", "silver")}


def test_species_are_national_order_and_egg_is_separate(packs):
    for pack in packs.values():
        assert pack["index_to_national"] == {str(n): n for n in range(1, 252)}
        assert len(pack["species"]) == 251
        assert pack["egg"]["index"] == 253
        assert pack["egg"]["national_dex"] is None
        assert not ({"0", "252", "253", "254", "255"} & pack["species"].keys())
        assert pack["species"]["122"]["name"] == "MR.MIME"
        assert pack["species"]["29"]["name"] == "NIDORAN♀"
        assert pack["species"]["32"]["name"] == "NIDORAN♂"


def test_gen2_split_stats_and_types_have_independent_controls(packs):
    for pack in packs.values():
        assert pack["species"]["1"]["base_stats"] == {
            "hp": 45, "attack": 49, "defense": 49, "speed": 45,
            "special_attack": 65, "special_defense": 65}
        assert pack["species"]["113"]["base_stats"]["special_attack"] == 35
        assert pack["species"]["113"]["base_stats"]["special_defense"] == 105
        assert pack["species"]["81"]["types"] == ["ELECTRIC", "STEEL"]
        assert pack["species"]["251"]["const"] == "CELEBI"


def test_gold_silver_equal_only_after_independent_reads(packs):
    assert packs["gold"]["source"] != packs["silver"]["source"]
    for key in ("index_to_national", "species", "egg"):
        assert packs["gold"][key] == packs["silver"][key]


def test_source_constants_missing_or_reordered_are_refused():
    source = (ROOT / ".cache/gen2-build/pokecrystal/constants/pokemon_constants.asm").read_text()
    bad = source.replace("const BULBASAUR", "const_skip\n\tconst BULBASAUR", 1)
    with pytest.raises(ValueError):
        species.parse_species_constants(bad)


def test_rom_name_and_stat_drift_refused(monkeypatch):
    context = species.load_context("crystal")
    from dataclasses import replace
    for symbol, delta in (("PokemonNames", 0), ("BaseData", 1)):
        raw = bytearray(context.rom)
        location = species.rom_offset(*context.symbol(symbol)) + delta
        raw[location] ^= 1
        monkeypatch.setattr(species, "load_context", lambda *a, raw=bytes(raw), **k: replace(context, rom=raw))
        with pytest.raises(ValueError, match="ROM/source"):
            species.build("crystal")


def test_check_detects_stale_species_without_writing(tmp_path, packs, monkeypatch):
    monkeypatch.setattr(species, "build", lambda title, root=ROOT: copy.deepcopy(packs[title]))
    args = ["--out-dir", str(tmp_path)]
    assert species.main(args) == 0
    path = tmp_path / "gen2_crystal/species_index.json"
    stale = json.loads(path.read_text())
    stale["species"]["113"]["base_stats"]["special_attack"] = 105
    path.write_text(json.dumps(stale))
    before = path.read_bytes()
    assert species.main([*args, "--check"]) == 1
    assert path.read_bytes() == before


def test_wrong_source_context_refused(monkeypatch):
    context = species.load_context("crystal")
    from dataclasses import replace
    monkeypatch.setattr(species, "load_context", lambda *a, **k: replace(context, source_commit="0" * 40))
    with pytest.raises(ValueError, match="source"):
        species.build("crystal")
