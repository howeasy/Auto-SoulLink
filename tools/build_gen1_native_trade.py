"""Build an isolated native RBY trade-engine artifact from pinned symbols.

This is not a releasable companion: no receptionist hook/capability is published.
The caller must implement admission, prepared validation and durable recovery.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from tools._build_tools_bootstrap import ensure_rgbds
from tools.verify_canonical_sources import verify

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "patch/gen1/src/native_trade.asm"
TARGETS = {"red": "pokered", "blue": "pokeblue", "yellow": "pokeyellow"}
CALLS = ("Bankswitch", "SaveScreenTilesToBuffer2", "SkipFixedLengthTextEntries", "CopyData", "AddNTimes",
         "RemovePokemon", "AddEnemyMonToPlayerParty", "ClearScreen", "LoadFontTilePatterns",
         "LoadHpBarAndStatusTilePatterns", "InternalClockTradeAnim", "TryEvolvingMon",
         "InGameTrade_RestoreScreen", "RedrawMapView", "UpdateSprites", "Delay3", "PlaySound", "DelayFrames",
         "PlayDefaultMusic", "SavePartyAndDexData")
RAM = ("wIsInBattle", "wLinkState", "hSerialConnectionStatus", "wEnteringCableClub", "wPartyCount", "wPartySpecies",
       "wTradingWhichPlayerMon", "wEnemyPartyCount", "wEnemyPartySpecies", "wEnemyMons", "wOptions",
       "wStatusFlags5", "wFontLoaded", "wForceEvolution", "wUpdateSpritesEnabled", "hAutoBGTransferEnabled",
       "hTileAnimations", "hWY", "wPartyMonOT", "wTradedPlayerMonOT", "wPartyMons", "wTradedPlayerMonSpecies",
       "wTradedPlayerMonOTID", "wEnemyMonOT", "wTradedEnemyMonOT", "wTradedEnemyMonOTID", "wTradedEnemyMonSpecies",
       "wWhichPokemon", "wRemoveMonFromBox", "wTradingWhichEnemyMon", "wCurPartySpecies", "wLoadedMon",
       "wAudioFadeOutControl", "wAudioSavedROMBank", "wNewSoundID")


def read_symbols(path):
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+):([0-9a-fA-F]+) (\S+)", line)
        if match:
            bank, address, name = match.groups()
            result[name] = (int(bank, 16), int(address, 16))
    return result


def build(title, *, verified=False, probe=False):
    if title not in TARGETS:
        raise ValueError("RBY title required")
    if not verified:
        report = verify()
        if report["failures"]:
            raise ValueError("canonical prerequisites failed: " + repr(report["failures"]))
    lock = json.loads((ROOT / "data/pret_sources.lock.json").read_text())
    target = TARGETS[title]
    record = lock["clean_roms"][target]
    source = record["source"]
    symbols = read_symbols(ROOT / f".cache/pret/{source}/{target}.sym")
    if (symbols["wTradingWhichPlayerMon"] != symbols["wTradedPlayerMonSpecies"]
            or symbols["wTradingWhichEnemyMon"] != symbols["wTradedEnemyMonSpecies"]):
        raise ValueError("native selection/species aliases differ")
    if (symbols["wPartyMon2"][1] - symbols["wPartyMon1"][1] != 44
            or symbols["wPartyMon2OT"][1] - symbols["wPartyMon1OT"][1] != 11
            or symbols["wPartyMonOT"][1] - symbols["wPartyMons"][1] != 6 * 44):
        raise ValueError("canonical party geometry differs")
    serial = (ROOT / f".cache/pret/{source}/constants/serial_constants.asm").read_text()
    if not re.search(r"DEF LINK_STATE_TRADING\s+EQU \$32\b", serial):
        raise ValueError("native trading state differs")
    if title == "yellow":
        constants = (ROOT / ".cache/pret/pokeyellow/constants/pikachu_emotion_constants.asm").read_text()
        names = re.findall(r"^\s*const (PIKAHAPPY_\w+)", constants, re.M)
        if names.index("PIKAHAPPY_TRADE") + 1 != 11 or "const_def 1" not in constants:
            raise ValueError("Pikachu trade happiness event differs")
    data = (ROOT / record["filename"]).read_bytes()
    if len(data) != 0x100000 or hashlib.sha1(data).hexdigest() != record["sha1"]:
        raise ValueError("exact canonical cartridge required")
    order_bank, order_address = symbols["PokedexOrder"]
    order_flat = order_bank * 0x4000 + order_address % 0x4000
    order = data[order_flat:order_flat+190]
    if sorted(dex for dex in order if dex) != list(range(1, 152)):
        raise ValueError("canonical internal species table differs")
    # Derive the exact music setup from the original cable-trade instructions.
    def address(name):
        return symbols[name][1].to_bytes(2, "little")
    def flat_symbol(name):
        b, pointer = symbols[name]
        return b * 0x4000 + pointer % 0x4000
    prefix = b"\x3e\x0a\xea" + address("wAudioFadeOutControl") + b"\x3e"
    middle = b"\xea" + address("wAudioSavedROMBank") + b"\x3e"
    suffix = (b"\xea" + address("wNewSoundID") + b"\xcd" + address("PlaySound")
              + b"\x0e\x64\xcd" + address("DelayFrames"))
    music_pattern = re.compile(re.escape(prefix) + b"(.)" + re.escape(middle) + b"(.)" + re.escape(suffix), re.S)
    trade_start, trade_end = flat_symbol("TradeCenter_Trade.doTrade"), flat_symbol("TradeCenter_Trade.usingExternalClock")
    matches = list(music_pattern.finditer(data[trade_start:trade_end]))
    if len(matches) != 1 or matches[0][1][0] != symbols["Music_SafariZone"][0]:
        raise ValueError("original trade music setup differs")
    match = matches[0]
    trade_music = {"bank": match[1][0], "id": match[2][0], "flat": trade_start + match.start(), "bytes": match[0].hex()}
    bank = 0x3B if title == "yellow" else 0x3F
    if any(data[bank * 0x4000:(bank + 1) * 0x4000]):
        raise ValueError("native payload bank is not empty")
    imports = list(CALLS) + (["ModifyPikachuHappiness"] if title == "yellow" else [])
    definitions = [f"DEF SLINK_TRADE_BANK EQU ${bank:02X}", f"DEF SLINK_YELLOW EQU {int(title == 'yellow')}"]
    definitions += [f"DEF SLINK_TRADE_MUSIC_BANK EQU ${trade_music['bank']:02X}", f"DEF SLINK_TRADE_MUSIC_ID EQU ${trade_music['id']:02X}"]
    definitions.append("MACRO slink_species_table\n db " + ",".join(map(str, [0] + [int(bool(dex)) for dex in order])) + "\nENDM")
    anchors = {}
    for name in imports:
        b, address = symbols[name]
        if not (b == 0 and 0 <= address < 0x4000 or 1 <= b < 64 and 0x4000 <= address < 0x8000):
            raise ValueError("invalid bank-qualified native routine " + name)
        definitions += [f"DEF {name} EQU ${address:04X}", f"DEF {name}Bank EQU ${b:02X}"]
        flat = b * 0x4000 + address % 0x4000
        anchors[name] = {"bank": b, "address": address, "flat": flat, "bytes": data[flat:flat + 16].hex()}
    ram_fields = list(RAM) + (["wPrinterConnectionOpen"] if title == "yellow" else [])
    for name in ram_fields:
        b, address = symbols[name]
        if b != 0 or not (0xC000 <= address < 0xE000 or 0xFF00 <= address <= 0xFFFF):
            raise ValueError("invalid native RAM field " + name)
        definitions.append(f"DEF {name} EQU ${address:04X}")
    directory = ROOT / "patch/gen1/build" / ("native_" + title)
    directory.mkdir(parents=True, exist_ok=True)
    assembly = directory / "trade.asm"
    text = "\n".join(definitions) + "\n" + SOURCE.read_text(encoding="utf-8")
    if probe:
        text += '''
SECTION "Native trade test entry", ROMX[$4700], BANK[SLINK_TRADE_BANK]
NativeTradeTestEntry::
    ei
    call SlinkTradeApply
NativeTradeTestReturned::
    di
    ret
NativeTradeTestEnd::
'''
    assembly.write_text(text, encoding="utf-8")
    rgbds = Path(ensure_rgbds())
    suffix = ".exe" if os.name == "nt" else ""
    obj, image, sym = (directory / name for name in ("trade.o", "trade.gb", "trade.sym"))
    subprocess.run([str(rgbds / ("rgbasm" + suffix)), "-o", str(obj), str(assembly)], check=True)
    subprocess.run([str(rgbds / ("rgblink" + suffix)), "-p", "0", "-o", str(image), "-n", str(sym), str(obj)], check=True)
    linked = read_symbols(sym)
    start, end = linked["SlinkTradeApply"][1], linked["SlinkTradeApplyEnd"][1]
    if not 0x4800 == start < end <= 0x8000 or linked["SlinkTradeApply"][0] != bank:
        raise ValueError("native payload escaped its reserved bank")
    flat = bank * 0x4000 + start - 0x4000
    payload = image.read_bytes()[flat:flat + end - start]
    final = bytearray(data)
    final[flat:flat + len(payload)] = payload
    probe_symbols = None
    if probe:
        probe_end = linked["NativeTradeTestEnd"][1]
        if not 0x4700 < probe_end < 0x4800:
            raise ValueError("test-only entry escaped its free-bank span")
        probe_flat = bank * 0x4000 + 0x700
        final[probe_flat:probe_flat + probe_end - 0x4700] = image.read_bytes()[probe_flat:probe_flat + probe_end - 0x4700]
        probe_symbols = {name: linked[name][1] for name in ("NativeTradeTestEntry", "NativeTradeTestReturned")}
        probe_symbols["bank"] = bank
    assert len(final) == len(data) and final[0x100:0x150] == data[0x100:0x150]
    output = ROOT / f"patch/gen1/build/native_trade_{title}.gb"
    output.write_bytes(final)
    assert output.read_bytes() == final
    info = {"schema": "gen1-native-trade-build-v1", "runtime_ready": False, "variant": title,
            "source_commit": lock["sources"][source]["commit"], "base_sha1": record["sha1"],
            "final_sha1": hashlib.sha1(final).hexdigest(), "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "entry": {"bank": bank, "address": start}, "size": len(payload), "native_calls": anchors,
            "ram": {name: symbols[name][1] for name in ram_fields}, "test_probe": probe_symbols, "trade_music": trade_music,
            "output": output.relative_to(ROOT).as_posix()}
    (directory / "manifest.json").write_text(json.dumps(info, indent=2) + "\n")
    return info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", choices=TARGETS)
    parser.add_argument("--probe", action="store_true", help="include isolated test-only free-bank entry")
    args = parser.parse_args()
    report = verify()
    if report["failures"]:
        raise SystemExit("canonical validation failed: " + repr(report["failures"]))
    for title in [args.rom] if args.rom else TARGETS:
        result = build(title, verified=True, probe=args.probe)
        print(json.dumps({key: result[key] for key in ("variant", "runtime_ready", "entry", "size", "final_sha1", "output")}))
