"""Script grants, native trade records and Odd Egg source/ROM checks."""
from dataclasses import replace

import pytest

from tools import gen_gen2_gifts as generator
from tools.gen2_source_data import load_context
from tools.gen_gen2_charmap import constants, parse_charmap
from tools.gen_gen2_statics import values


@pytest.fixture(scope="module")
def contexts():
    return {title: load_context(title) for title in ("crystal", "gold", "silver")}


@pytest.fixture(scope="module")
def packs(contexts):
    return {title: generator.build(ctx) for title, ctx in contexts.items()}


def test_scripted_grants_eggs_and_version_prizes(packs):
    for title, pack in packs.items():
        assert len(pack["gifts"]) == (14 if title == "crystal" else 16)
        eggs = [row for row in pack["gifts"] if row["kind"] == "egg_reception"]
        assert len(eggs) == 1 and eggs[0]["species"] == 175 and eggs[0]["level"] == 5
        assert eggs[0]["capture_at_reception"] is False
        assert pack["policies"] == {"egg_reception_is_capture": False, "hatch_area_id": "gift_daycare"}
        assert pack["exclusions"][0]["constant"] == "MYSTERY_EGG"
        assert pack["exclusions"][0]["kind"] == "key_item"
        assert any(row["target"] == "DayCare_GiveEgg" for row in pack["native_callers"])
        shuckle = next(row["grant"] for row in pack["caller_inventory"] if row["kind"] == "borrowed_gift")
        assert (shuckle["species"], shuckle["level"], shuckle["item"]) == (213, 15, 173)
        prizes = [row["species"] for row in pack["gifts"] if row["map_name"] == "GoldenrodGameCorner" and row["applicability"]["selected"]]
        assert prizes == {"crystal": [63, 104, 202], "gold": [63, 23, 147], "silver": [63, 27, 147]}[title]
    assert any(row["kind"] == "post_grant_customization" for row in packs["crystal"]["caller_inventory"])


def test_npc_trade_identity_and_odd_egg_bytes(packs):
    for title, pack in packs.items():
        assert len(pack["npc_trades"]) == (7 if title == "crystal" else 6)
        mike = pack["npc_trades"][0]
        assert mike["requested_species"] == (63 if title == "crystal" else 96)
        assert mike["offered_species"] == 66
        assert (mike["nickname"], mike["ot_id"], mike["ot_name"]) == ("MUSCLE", 37460, "MIKE")
        assert len(bytes.fromhex(mike["record_hex"])) == 32
    odd = packs["crystal"]["odd_eggs"]
    assert odd["applicable"] and len(odd["records"]) == 14 and odd["record_length"] == 59
    assert [row["species"] for row in odd["records"]] == [172, 172, 173, 173, 174, 174, 238, 238, 240, 240, 239, 239, 236, 236]
    assert odd["records"][0]["threshold"] == 5242 and odd["records"][-1]["threshold"] == 65535
    assert packs["gold"]["odd_eggs"]["applicable"] is False


@pytest.mark.parametrize("symbol", ["NPCTrades", "OddEggs", "OddEggProbabilities"])
def test_native_table_byte_tamper_refuses(contexts, symbol):
    ctx = contexts["crystal"]
    entry = ctx.symbol(symbol)
    offset = entry.bank * 0x4000 + entry.address - 0x4000
    rom = bytearray(ctx.rom)
    rom[offset] ^= 1
    changed = replace(ctx, rom=bytes(rom))
    names = values(ctx)
    encoding = parse_charmap(ctx.read_source("constants/charmap.asm"))["encoding"]
    lengths = constants(ctx.read_source("constants/text_constants.asm").split("; GetName types")[0])
    with pytest.raises(ValueError, match="byte mismatch"):
        if symbol == "NPCTrades":
            generator.trade_data(changed, names, encoding, lengths)
        else:
            generator.odd_eggs(changed, names, encoding, lengths)


def test_check_detects_drift_without_writing(tmp_path, monkeypatch, packs):
    from tools import gen_gen2_charmap as common

    monkeypatch.setattr(common, "load_context", lambda title, root: title)
    monkeypatch.setattr(generator, "build", lambda title: packs[title])
    argv = ["--root", str(tmp_path)]
    assert generator.main(argv) == 0
    assert generator.main([*argv, "--check"]) == 0
    path = tmp_path / "data/games/gen2_silver/gifts.json"
    path.write_bytes(b"{}\n")
    before = path.stat().st_mtime_ns
    assert generator.main([*argv, "--check"]) == 1
    assert path.read_bytes() == b"{}\n" and path.stat().st_mtime_ns == before
