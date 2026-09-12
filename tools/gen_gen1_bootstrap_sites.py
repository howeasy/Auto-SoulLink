"""Pin the normal New Game entry and the return from Oak's initialization, and the CONTINUE path.

CONTINUE (a battery-save boot) is `MainMenu -> predef TryLoadSaveFile` (before any choice: it
fills the save preview, so its entry/return alone only proves SaveRAM loaded) then
`.choseContinue -> .pressedA -> SpecialEnterMap` (the selected path). Five sites pin it, in a
SEPARATE file with its own hash: every New Game receipt already journaled carries the hash of
bootstrap_sites.json and is re-verified against it on each reopen, so that file never changes.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
try:
    from gen_gen1_acquisition_sources import TITLES, symbols
    from gen_gen1_capture_sites import operand, site
    from gen_gen1_engine_signals import lua
    from verify_canonical_sources import verify
finally:
    sys.path.pop(0)

OUTPUT = ROOT / "data/games/gen1_rby/bootstrap_sites.json"
LUA = OUTPUT.with_name("gen1_bootstrap_sites.lua")
CONTINUE_OUTPUT = OUTPUT.with_name("continue_sites.json")
CONTINUE_LUA = OUTPUT.with_name("gen1_continue_sites.lua")
FIELDS = {
    "trainer": ("wPlayerName", 11),
    "player_id": ("wPlayerID", 2),
    "party": ("wPartyDataStart", 404),
    "box": ("wBoxDataStart", 1122),
    "owned": ("wPokedexOwned", 19),
    "seen": ("wPokedexSeen", 19),
    "current_box": ("wCurrentBoxNum", 1),
}


def build():
    assert verify(rom_dir=ROOT)["status"] == "pass", "canonical bootstrap sources differ"
    lock = json.loads((ROOT / "data/pret_sources.lock.json").read_text())
    result = {"schema": "rby-bootstrap-sites-v1", "titles": {}}
    for variant, (source, target) in TITLES.items():
        repo = ROOT / ".cache/pret" / source
        syms = symbols(repo / (target + ".sym"))
        rom = (ROOT / lock["clean_roms"][target]["filename"]).read_bytes()
        menu = (repo / "engine/menus/main_menu.asm").read_text(encoding="utf-8")
        oak = (repo / "engine/movie/oak_speech/oak_speech.asm").read_text(encoding="utf-8")
        assert "StartNewGame:\n\tld hl, wStatusFlags6" in menu
        assert (
            "\tres BIT_DEBUG_MODE, [hl]\n\t; fallthrough\nStartNewGameDebug:\n\tcall OakSpeech\n"
            in menu
        )
        assert (
            "\tld hl, wPlayerName\n\tld bc, wBoxDataEnd - wPlayerName\n\txor a\n\tcall FillMemory"
            in oak
        )
        assert "\tcall PrepareOakSpeech\n\tpredef InitPlayerData2\n" in oak
        assert "\tcall ChoosePlayerName\n" in oak and "\tcall ChooseRivalName\n" in oak
        init_files = list(repo.glob("engine/**/init_player_data.asm"))
        assert len(init_files) == 1
        init = init_files[0].read_text(encoding="utf-8")
        for name in ("wPartyCount", "wBoxCount", "wNumBagItems", "wNumBoxItems"):
            assert f"\tld hl, {name}\n\tcall InitializeEmptyList\n" in init
        assert (
            "InitializeEmptyList:\n\txor a ; count\n\tld [hli], a\n\tdec a ; terminator\n\tld [hl], a\n\tret"
            in init
        )
        bank, begin = syms["StartNewGame"]
        call_bank, call = syms["StartNewGameDebug"]
        assert call_bank == bank and call == begin + 5 and syms["OakSpeech"][0] == bank
        entry = site(rom, "StartNewGame", bank, begin, 8)
        expected = (
            b"\x21"
            + syms["wStatusFlags6"][1].to_bytes(2, "little")
            + b"\xcb\x8e\xcd"
            + syms["OakSpeech"][1].to_bytes(2, "little")
        )
        assert bytes.fromhex(entry["expected_hex"]) == expected
        end = site(rom, "StartNewGameDebug+3", bank, call + 3, 5 if variant != "yellow" else 10)
        expected = b"\x0e\x14\xcd" + syms["DelayFrames"][1].to_bytes(2, "little")
        if variant == "yellow":
            expected = (
                b"\x3e\x08\xea" + syms["wPlayerMovingDirection"][1].to_bytes(2, "little") + expected
            )
        assert bytes.fromhex(end["expected_hex"]) == expected
        assert syms["wPokedexSeen"][1] - syms["wPokedexOwned"][1] == 19
        assert syms["wNumBagItems"][1] - syms["wPokedexSeen"][1] == 19
        assert syms["wPartyDataEnd"][1] - syms["wPartyDataStart"][1] == 404
        assert syms["wBoxDataEnd"][1] - syms["wBoxDataStart"][1] == 1122
        result["titles"][variant] = {
            "source_commit": lock["sources"][source]["commit"],
            "clean_sha1": lock["clean_roms"][target]["sha1"],
            "bank_address": syms["hLoadedROMBank"][1],
            "fields": {
                name: {"address": syms[label][1], "length": length}
                for name, (label, length) in FIELDS.items()
            },
            "sites": {"begin": entry, "end": end},
        }
    result["sha256"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result


def build_continue():
    assert verify(rom_dir=ROOT)["status"] == "pass", "canonical bootstrap sources differ"
    lock = json.loads((ROOT / "data/pret_sources.lock.json").read_text())
    result = {"schema": "rby-continue-sites-v1", "titles": {}}
    for variant, (source, target) in TITLES.items():
        repo = ROOT / ".cache/pret" / source
        syms = symbols(repo / (target + ".sym"))
        rom = (ROOT / lock["clean_roms"][target]["filename"]).read_bytes()
        menu = (repo / "engine/menus/main_menu.asm").read_text(encoding="utf-8")
        save = (repo / "engine/menus/save.asm").read_text(encoding="utf-8")
        assert "\tpredef TryLoadSaveFile\n" in menu and "\tjr z, .choseContinue\n" in menu
        assert "TryLoadSaveFile:\n\tcall ClearScreen\n\tcall LoadFontTilePatterns\n" in save
        assert "\tld a, $2 ; good checksum\n\tjr .done\n" in save
        assert "\tld a, $1 ; bad checksum\n.done\n\tld [wSaveFileStatus], a\n\tret\n" in save
        assert ".choseContinue\n\tcall DisplayContinueGameInfo\n\tld hl, wCurrentMapScriptFlags\n" in menu
        assert "\tjr nz, .pressedA\n" in menu
        assert ".pressedA\n\tcall GBPalWhiteOutWithDelay3\n\tcall ClearScreen\n" in menu
        assert "\tjp z, SpecialEnterMap\n" in menu and "\tjp nz, SpecialEnterMap\n" in menu
        assert ("SpecialEnterMap::\n\txor a\n\tldh [hJoyPressed], a\n\tldh [hJoyHeld], a\n\tldh [hJoy5], a\n"
                "\tld [wCableClubDestinationMap], a\n") in menu
        continue_sites = {}
        for kind, label, length, expected in (
            ("load", "TryLoadSaveFile", 6, b"\xcd" + operand(syms, "ClearScreen") + b"\xcd" + operand(syms, "LoadFontTilePatterns")),
            ("loaded", "TryLoadSaveFile.done", 4, b"\xea" + operand(syms, "wSaveFileStatus") + b"\xc9"),
            ("chose", "MainMenu.choseContinue", 6,
             b"\xcd" + operand(syms, "DisplayContinueGameInfo") + b"\x21" + operand(syms, "wCurrentMapScriptFlags")),
            ("pressed", "MainMenu.pressedA", 6, b"\xcd" + operand(syms, "GBPalWhiteOutWithDelay3") + b"\xcd" + operand(syms, "ClearScreen")),
            ("enter", "SpecialEnterMap", 10, b"\xaf\xe0" + operand(syms, "hJoyPressed")[:1] + b"\xe0" + operand(syms, "hJoyHeld")[:1]
             + b"\xe0" + operand(syms, "hJoy5")[:1] + b"\xea" + operand(syms, "wCableClubDestinationMap")),
        ):
            site_bank, cpu = syms[label]
            row = site(rom, label, site_bank, cpu, length)
            assert bytes.fromhex(row["expected_hex"]) == expected, label
            continue_sites[kind] = row
        assert continue_sites["load"]["bank"] == continue_sites["loaded"]["bank"] != 0
        assert {continue_sites[k]["bank"] for k in ("chose", "pressed", "enter")} == {syms["MainMenu"][0]}
        result["titles"][variant] = {
            "source_commit": lock["sources"][source]["commit"],
            "clean_sha1": lock["clean_roms"][target]["sha1"],
            "bank_address": syms["hLoadedROMBank"][1],
            "save_file_status": syms["wSaveFileStatus"][1],
            "sites": continue_sites,
        }
    result["sha256"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for build_one, output, module in ((build, OUTPUT, LUA), (build_continue, CONTINUE_OUTPUT, CONTINUE_LUA)):
        value = build_one()
        encoded = json.dumps(value, indent=2, sort_keys=True) + "\n"
        source = "-- Generated by tools/gen_gen1_bootstrap_sites.py.\nreturn " + lua(value) + "\n"
        if args.check:
            assert (
                output.read_text(encoding="utf-8") == encoded
                and module.read_text(encoding="utf-8") == source
            )
        else:
            output.write_text(encoded, encoding="utf-8", newline="\n")
            module.write_text(source, encoding="utf-8", newline="\n")
    print("OK: normal New Game and CONTINUE bootstrap sites for Red, Blue and Yellow")


if __name__ == "__main__":
    main()
