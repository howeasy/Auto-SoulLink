"""EXP-MON-GIVEN: the expansion's mon_given site is GiveScriptedMonToPlayer, not GiveCapturedMonToPlayer.

givemon/createmon -> ScriptGiveMonParameterized -> GiveScriptedMonToPlayer (src/pokemon.c:6674), and
ScriptGiveMon (starter) reaches the same routine; wild capture (Cmd_givecaughtmon) and ScriptGiveEgg
go through GiveCapturedMonToPlayer (src/pokemon.c:2941). A mon_given pin in the latter never fires for
a scripted gift (live: Steven's Beldum) and double-fired with capture_wild at the same address.
"""
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "data/games/gen3_exp/28877d73"
ARTIFACTS = Path(os.environ.get("SLINK_EXPANSION_ARTIFACTS", ROOT / ".cache/expansion-output/reference"))
BASE = 0x08000000


def sites():
    pack = json.loads((PACK / "engine_signals.json").read_text(encoding="utf-8"))
    return pack["titles"]["emerald_expansion_28877d73"]["artifacts"]["clean"]["sites"]


def test_pack_pins_mon_given_in_giveScriptedMonToPlayer():
    site = sites()["mon_given"]
    f = site["function"]
    assert (f["symbol"], f["address"], f["size"]) == ("GiveScriptedMonToPlayer", 0x081C2E74, 0xC0)
    assert (f["anchor_offset"], f["capture_offset"]) == (0x64, 0x68)
    assert site["expected_hex"] == "3800347680BCB846F0BC02BC08476420"
    assert site["rom_offset"] == 0x1C2ED8 and site["capture_offset"] == 4
    assert site["context"]["expected_hex"] == "F0B5C6460B06804600B51B0E052B44D9"
    assert site["point"] == ["R0", "R7", "R8", "R13", "R15", "CPSR"]


def test_contract_names_the_scripted_routine_and_not_the_capture_one():
    site = sites()["mon_given"]
    assert "GiveScriptedMonToPlayer" in site["capture_contract"]
    assert "share" not in site["capture_contract"]
    assert "GiveCapturedMonToPlayer" not in site["capture_contract"].split("Wild capture")[0]
    assert site["address"] != sites()["capture_wild"]["address"]


def test_capture_and_gift_sites_are_distinct_functions():
    s = sites()
    assert s["capture_wild"]["function"]["symbol"] == "GiveCapturedMonToPlayer"
    assert s["mon_given"]["function"]["symbol"] == "GiveScriptedMonToPlayer"


def _rom():
    if not all((ARTIFACTS / n).is_file() for n in ("pokeemerald.gba", "pokeemerald.sym")):
        pytest.skip("reference expansion ROM absent")
    return (ARTIFACTS / "pokeemerald.gba").read_bytes()


def test_rom_bytes_at_pin_and_unique():
    rom, site = _rom(), sites()["mon_given"]
    want = bytes.fromhex(site["expected_hex"])
    assert rom[site["rom_offset"]:site["rom_offset"] + len(want)] == want
    assert rom.count(want) == 1


def _bl_targets(rom, start, size):
    out = []
    for off in range(start - BASE, start - BASE + size - 3, 2):
        hi, lo = (int.from_bytes(rom[off + i:off + i + 2], "little") for i in (0, 2))
        if hi & 0xF800 == 0xF000 and lo & 0xF800 == 0xF800:
            disp = (hi & 0x7FF) << 12
            disp -= (disp & 0x400000) << 1
            out.append((BASE + off, BASE + off + 4 + disp + ((lo & 0x7FF) << 1)))
    return out


def test_rom_witness_createmon_and_starter_reach_the_pinned_function():
    rom = _rom()
    from tools.pin_gen3_site import parse_symbols
    sym = parse_symbols((ARTIFACTS / "pokeemerald.sym").read_text())
    def calls(name):
        return {t for _, t in _bl_targets(rom, sym[name]["address"], sym[name]["size"])}
    scripted, captured = sym["GiveScriptedMonToPlayer"]["address"], sym["GiveCapturedMonToPlayer"]["address"]
    assert sym["ScriptGiveMonParameterized"]["address"] in calls("ScrCmd_createmon")
    assert scripted in calls("ScriptGiveMonParameterized") and captured not in calls("ScriptGiveMonParameterized")
    assert scripted in calls("ScriptGiveMon")  # starter (CB2_GiveStarter) and debug give
    assert captured in calls("ScriptGiveEgg") and scripted not in calls("ScriptGiveEgg")
    assert captured in calls("Cmd_givecaughtmon") and scripted not in calls("Cmd_givecaughtmon")


def test_rom_witness_pin_is_the_single_return_after_party_count_store():
    capstone = pytest.importorskip("capstone")
    rom = _rom()
    site = sites()["mon_given"]
    f = site["function"]
    code = rom[f["address"] - BASE:f["address"] - BASE + f["size"]]
    ops = list(capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB).disasm(code, f["address"]))
    by = {i.address - f["address"]: i for i in ops}
    pin = f["capture_offset"]
    # pin = `pop {r7}` of the epilogue, directly after `movs r0, r7; strb r4, [r6, #0x18]`
    # (inlined CalculatePlayerPartyCount store); R0 is the outcome, R8 still the source mon
    assert by[pin].mnemonic == "pop" and by[pin].op_str == "{r7}"
    assert (by[pin - 2].mnemonic, by[pin - 2].op_str) == ("strb", "r4, [r6, #0x18]")
    assert (by[pin - 4].mnemonic, by[pin - 4].op_str) == ("movs", "r0, r7")
    # exactly one function return, so every path (slot<6, party, PC, can't-give) crosses the pin
    returns = [i for i in ops if i.mnemonic == "bx" and i.op_str == "r1"]
    assert len(returns) == 1 and returns[0].address - f["address"] == pin + 8
