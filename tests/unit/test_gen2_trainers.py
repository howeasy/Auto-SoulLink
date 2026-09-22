"""Known trainer controls and source/ROM refusal; no emulator or fixture injection."""
from dataclasses import replace

import pytest

from tools import gen_gen2_trainers as generator
from tools.gen2_source_data import load_context
from tools.gen_gen2_charmap import parse_charmap
from tools.gen_gen2_statics import values


@pytest.fixture(scope="module")
def contexts():
    return {title: load_context(title) for title in ("crystal", "gold", "silver")}


@pytest.fixture(scope="module")
def packs(contexts):
    return {title: generator.build(ctx) for title, ctx in contexts.items()}


def test_source_known_falkner_and_full_class_inventory(packs):
    for title, pack in packs.items():
        assert pack["classes"]["1"] == "Leader"
        assert pack["named_trainers"]["1"]["1"] == "Falkner"
        party = pack["parties"]["1"]["1"]
        assert [(mon["species"], mon["level"]) for mon in party["party"]] == [(16, 7), (17, 9)]
        assert party["trainer_type"] == 1
        assert party["party"][0]["moves"] == [33, 189, 0, 0]
        assert len(pack["classes"]) == (68 if title == "crystal" else 67)
        assert set(pack["parties"]) == set(pack["classes"]) - {"0"}
        assert pack["parties"]["10"] == {}  # Explicit empty PokemonProfGroup, not lost coverage.
        assert pack["parties"]["12"]["2"]["runtime_party_source"] == "SRAM_OVERRIDE"
    assert packs["crystal"]["parties"] != packs["gold"]["parties"]
    # Their source parties are equal; title provenance is intentionally separate.
    assert packs["gold"]["named_trainers"] == packs["silver"]["named_trainers"]


@pytest.mark.parametrize("flag,fields,item,moves", [
    ("NORMAL", "10, BULBASAUR", None, None),
    ("MOVES", "10, BULBASAUR, TACKLE, GROWL, NO_MOVE, NO_MOVE", None, [33, 45, 0, 0]),
    ("ITEM", "10, BULBASAUR, BERRY", 173, None),
    ("ITEM_MOVES", "10, BULBASAUR, BERRY, TACKLE, GROWL, NO_MOVE, NO_MOVE", 173, [33, 45, 0, 0]),
])
def test_four_source_record_shapes(contexts, flag, fields, item, moves):
    ctx = contexts["crystal"]

    class Source:
        def __getattr__(self, name):
            return getattr(ctx, name)

        def read_source(self, path):
            assert path == "data/trainers/parties.asm"
            return f'ExampleGroup:\n db "ACE@", TRAINERTYPE_{flag}\n db {fields}\n db -1\n'

    chars = parse_charmap(ctx.read_source("constants/charmap.asm"))
    row = generator.parse_parties(Source(), values(ctx), chars["encoding"])["ExampleGroup"][0]
    assert row["party"] == [{"level": 10, "species": 1, "item": item, "moves": moves}]
    assert row["encoded"][-1] == 255


@pytest.mark.parametrize("target", ["TrainerGroups", "FalknerGroup", "TrainerClassNames"])
def test_actual_rom_pointer_name_and_party_tamper_refuse(contexts, target):
    ctx = contexts["crystal"]
    symbol = ctx.symbol(target)
    offset = symbol.bank * 0x4000 + symbol.address - 0x4000
    rom = bytearray(ctx.rom)
    rom[offset] ^= 1
    with pytest.raises(ValueError, match="byte mismatch"):
        generator.build(replace(ctx, rom=bytes(rom)))


def test_check_detects_drift_without_rewriting(tmp_path, monkeypatch, packs):
    from tools import gen_gen2_charmap as common

    monkeypatch.setattr(common, "load_context", lambda title, root: title)
    monkeypatch.setattr(generator, "build", lambda title: packs[title])
    argv = ["--root", str(tmp_path)]
    assert generator.main(argv) == 0
    paths = list(tmp_path.glob("data/games/*/trainers.json"))
    assert len(paths) == 3
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
    assert generator.main([*argv, "--check"]) == 0
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
    paths[0].write_bytes(b"{}\n")
    assert generator.main([*argv, "--check"]) == 1
    assert paths[0].read_bytes() == b"{}\n"
