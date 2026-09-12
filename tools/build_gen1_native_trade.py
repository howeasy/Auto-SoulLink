"""Build an isolated native RBY trade-engine artifact from pinned symbols.

This is not a releasable companion: no public capability is published.
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
from tools.gen_gen1_codec_data import name_bytes
from tools.verify_canonical_sources import verify

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "patch/gen1/src/native_trade.asm"
SERVICE_SOURCE = ROOT / "patch/gen1/src/trade_service.asm"
RECEPTIONIST_SOURCE = ROOT / "patch/gen1/src/trade_receptionist.asm"
UI_SOURCE = ROOT / "patch/gen1/src/trade_ui.asm"
PROMPT_SOURCE = ROOT / "patch/gen1/src/trade_prompt.asm"
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
PROMPT_STATE = (
    "wOptions", "wStatusFlags5", "wFontLoaded", "wUpdateSpritesEnabled", "hAutoBGTransferEnabled",
    "hTileAnimations", "hWY", "hUILayoutFlags", "wPartyMenuAnimMonEnabled", "wWhichPokemon",
    "wTopMenuItemY", "wTopMenuItemX", "wCurrentMenuItem", "wTileBehindCursor", "wMaxMenuItem",
    "wMenuWatchedKeys", "wLastMenuItem", "wPartyAndBillsPCSavedMenuItem", "wMenuJoypadPollCount",
    "wMenuWrappingEnabled", "wMenuWatchMovingOutOfBounds", "wMenuCursorLocation", "wMenuCursorLocation + 1",
    "wTextBoxID", "wTwoOptionMenuID",
)


def read_symbols(path):
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+):([0-9a-fA-F]+) (\S+)", line)
        if match:
            bank, address, name = match.groups()
            result[name] = (int(bank, 16), int(address, 16))
    return result


def build(title, *, verified=False, probe=False, foreground=False, receptionist=False):
    if title not in TARGETS:
        raise ValueError("RBY title required")
    if receptionist:
        foreground = True
    if probe and foreground:
        raise ValueError("foreground entry cannot include the IRQ test injector")
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
    if foreground:
        imports.append("DelayFrame")
    if receptionist:
        imports += ["CableClubNPC", "WaitForTextScrollButtonPress", "TextBoxBorder", "PlaceString",
                    "HandleMenuInput", "LoadScreenTilesFromBuffer2", "ClearSprites", "Joypad", "PrintText", "YesNoChoice"]
    definitions = [f"DEF SLINK_TRADE_BANK EQU ${bank:02X}", f"DEF SLINK_YELLOW EQU {int(title == 'yellow')}",
                   f"DEF SLINK_TRADE_UI EQU {int(receptionist)}"]
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
    foreground_meta = None
    receptionist_meta = None
    if foreground:
        ram_fields += ["wSerialPartyMonsPatchList", "wEnemyMonNicks", "wLinkEnemyTrainerName",
                       "hLoadedROMBank", "wPokedexOwned", "wPlayerName", "wPlayerID", "wCurMap"]
        if title == "yellow":
            ram_fields.append("wPikachuHappiness")
        header = ROOT / f".cache/pret/{source}/home/header.asm"
        header_text = header.read_text()
        for vector in range(0, 0x40, 8):
            if f'SECTION "rst{vector:x}", ROM0[${vector:04x}]'.lower() not in header_text.lower():
                raise ValueError("unused RST source layout changed")
            if data[vector:vector+8] != b"\xff" + b"\0" * 7:
                raise ValueError("reserved RST vector bytes differ")
        # A source-declared unused span is required; zero-byte scanning alone
        # cannot authorize overwriting an instruction or a table.
        for file in (ROOT / f".cache/pret/{source}").rglob("*.asm"):
            if file == header:
                continue
            if re.search(r"(?im)^\s*rst\s+", file.read_text(encoding="utf-8")):
                raise ValueError("cartridge uses a reserved RST: " + str(file))
        delay = symbols["DelayFrame"][1]
        halt = symbols["DelayFrame.halt"][1]
        if data[delay:delay+11] != bytes((0x3E, 1, 0xE0, symbols["hVBlankOccurred"][1] & 255,
                                        0x76, 0xF0, symbols["hVBlankOccurred"][1] & 255, 0xA7, 0x20, 0xFA, 0xC9)):
            raise ValueError("terminal DelayFrame instructions differ")
        returns = [symbols[name][1] + 3 for name in ("OverworldLoop", "OverworldLoopLessDelay")]
        if any(symbols[name][0] for name in ("DelayFrame", "OverworldLoop", "OverworldLoopLessDelay")):
            raise ValueError("foreground caller roots must be ROM0")
        if returns[0] >> 8 != returns[1] >> 8:
            raise ValueError("foreground caller pages differ")
        if symbols["wSerialPartyMonsPatchList"] != symbols["wSurroundingTiles"]:
            raise ValueError("serial/map scratch union differs")
        definitions += [f"DEF SlinkDelayFrameHalt EQU ${halt:04X}",
                        f"DEF SlinkOverworldReturn EQU ${returns[0]:04X}",
                        f"DEF SlinkOverworldLessReturn EQU ${returns[1]:04X}"]
        foreground_meta = {"hook": delay+8, "expected_hook_hex": data[delay+8:delay+11].hex(),
                           "original_callers": returns, "overlay": symbols["wSerialPartyMonsPatchList"][1],
                           "backup": symbols["wEnemyMons"][1]+44,
                           "borrowed_union": "wSurroundingTiles/wTileMapBackup; restored before native use and return"}
    if receptionist:
        alphabet = set(name_bytes(ROOT / f".cache/pret/{source}"))
        definitions.append("MACRO slink_name_table\n db " + ",".join(str(int(i in alphabet)) for i in range(256)) + "\nENDM")
        ram_fields += ["wTileMap", "wTopMenuItemY", "wTopMenuItemX", "wCurrentMenuItem", "wMaxMenuItem",
                       "wMenuWatchedKeys", "wLastMenuItem", "wMenuJoypadPollCount", "wMenuWrappingEnabled",
                       "wMenuWatchMovingOutOfBounds", "wPartyMonNicks", "hFrameCounter",
                       "wPartyMenuAnimMonEnabled", "hUILayoutFlags", "hLoadedROMBank", "hJoyHeld"]
        for field in (*PROMPT_STATE, "wEnemyMonNicks"):
            name = field.split(" + ")[0]
            if name not in ram_fields:
                ram_fields.append(name)
        definitions.append("MACRO slink_save_prompt_state\n" + "\n".join(
            f" {'ldh' if name.startswith('h') else 'ld'} a, [{name}]\n push af" for name in PROMPT_STATE) + "\nENDM")
        definitions.append("MACRO slink_restore_prompt_state\n" + "\n".join(
            f" pop af\n {'ldh' if name.startswith('h') else 'ld'} [{name}], a" for name in reversed(PROMPT_STATE)) + "\nENDM")
        bank_npc, address_npc = symbols["CableClubNPC"]
        pattern = bytes((0x21, address_npc & 255, address_npc >> 8, 0x06, bank_npc, 0xCD,
                         symbols["Bankswitch"][1] & 255, symbols["Bankswitch"][1] >> 8))
        start = symbols["DisplayTextID"][1]
        end = symbols["AfterDisplayingTextID"][1]
        sites = [i for i in range(start, end) if data[i:i+8] == pattern]
        if len(sites) != 1 or data[sites[0]-4:sites[0]-2] != b"\xfe\xf6" or data[sites[0]+8] != 0x18:
            raise ValueError("canonical receptionist dispatch differs")
        if symbols["wMaxMenuItem"][1] - symbols["wTopMenuItemY"][1] != 4:
            raise ValueError("native menu geometry changed")
        receptionist_meta = {"dispatch": sites[0], "expected_hex": data[sites[0]:sites[0]+10].hex(),
                             "original": {"bank": bank_npc, "address": address_npc},
                             "text_continuation": symbols["HoldTextDisplayOpen"][1]}
    ram_fields = list(dict.fromkeys(ram_fields))
    for name in ram_fields:
        b, address = symbols[name]
        if b != 0 or not (0xC000 <= address < 0xE000 or 0xFF00 <= address <= 0xFFFF):
            raise ValueError("invalid native RAM field " + name)
        definitions.append(f"DEF {name} EQU ${address:04X}")
    prefix_name = "receptionist_" if receptionist else ("foreground_" if foreground else "native_")
    directory = ROOT / "patch/gen1/build" / (prefix_name + title)
    directory.mkdir(parents=True, exist_ok=True)
    assembly = directory / "trade.asm"
    text = "\n".join(definitions) + "\n" + SOURCE.read_text(encoding="utf-8")
    if foreground:
        text += "\n" + SERVICE_SOURCE.read_text(encoding="utf-8")
    if receptionist:
        text += "\n" + (ROOT / f".cache/pret/{source}/constants/charmap.asm").read_text(encoding="utf-8")
        text += "\n" + (ROOT / f".cache/pret/{source}/macros/const.asm").read_text(encoding="utf-8")
        text += "\n" + (ROOT / f".cache/pret/{source}/macros/scripts/text.asm").read_text(encoding="utf-8")
        text += "\n" + RECEPTIONIST_SOURCE.read_text(encoding="utf-8")
        text += "\n" + UI_SOURCE.read_text(encoding="utf-8")
        text += "\n" + PROMPT_SOURCE.read_text(encoding="utf-8")
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
    if foreground:
        bridge_end = linked["SlinkDelayFrameBridgeEnd"][1]
        service_start, service_end = linked["SlinkTradeService"][1], linked["SlinkTradeServiceEnd"][1]
        if linked["SlinkDelayFrameBridge"] != (0, 1) or not 1 < bridge_end <= 0x38:
            raise ValueError("foreground bridge escaped unused RST span")
        if linked["SlinkTradeService"][0] != bank or not 0x4500 == service_start < service_end <= 0x4800:
            raise ValueError("foreground service escaped reserved span")
        assembled = image.read_bytes()
        final[1:bridge_end] = assembled[1:bridge_end]
        service_flat = bank*0x4000 + service_start-0x4000
        final[service_flat:service_flat+service_end-service_start] = assembled[service_flat:service_flat+service_end-service_start]
        site = foreground_meta["hook"]
        final[site:site+3] = b"\xc3\x01\0"
        foreground_meta.update(bridge={"start": 1, "end": bridge_end}, service={"bank": bank, "address": service_start},
                               wait_return=linked["SlinkTradeService.waitForReceipt"][1]+3)
    if receptionist:
        extra_sections = {}
        for label, end_label, lower, upper in (
                ("SlinkTradeUIWaitReleased", "SlinkTradeUIEnd", 0x5400, 0x5800),
                ("SlinkPartnerPrompt", "SlinkPartnerPromptEnd", 0x5800, 0x6000)):
            section_start, section_end = linked[label][1], linked[end_label][1]
            if linked[label] != (bank, lower) or not section_start < section_end <= upper:
                raise ValueError("trade UI escaped its reserved span: " + label)
            section_flat = bank * 0x4000 + section_start - 0x4000
            final[section_flat:section_flat + section_end - section_start] = image.read_bytes()[section_flat:section_flat + section_end - section_start]
            extra_sections[label] = {"bank": bank, "address": section_start, "size": section_end - section_start}
        start_npc, end_npc = linked["SlinkReceptionist"][1], linked["SlinkReceptionistEnd"][1]
        if linked["SlinkReceptionist"] != (bank, 0x4C00) or not start_npc < end_npc <= 0x5400:
            raise ValueError("receptionist escaped reserved span")
        npc_flat = bank*0x4000 + start_npc-0x4000
        final[npc_flat:npc_flat+end_npc-start_npc] = image.read_bytes()[npc_flat:npc_flat+end_npc-start_npc]
        site = receptionist_meta["dispatch"]
        continuation = receptionist_meta["text_continuation"] - (site+10)
        if not -128 <= continuation <= 127:
            raise ValueError("text continuation escaped relative branch")
        final[site:site+10] = bytes((0x21, start_npc & 255, start_npc >> 8, 0x06, bank, 0xCD,
                                   symbols["Bankswitch"][1] & 255, symbols["Bankswitch"][1] >> 8,
                                   0x18, continuation & 255))
        receptionist_meta.update(entry={"bank": bank, "address": start_npc}, size=end_npc-start_npc,
            query_return=linked["SlinkReceptionist.queryWait"][1]+3,
            offer_return=linked["SlinkReceptionist.offerWait"][1]+3,
            menu_input=linked["SlinkTradeUIMenuInput"][1],
            restore_menus=linked["SlinkReceptionist.restoreMenus"][1],
            after_query=linked["SlinkReceptionist.afterQuery"][1],
            offer_entry=linked["SlinkReceptionist.offer"][1],
            party_entry=linked["SlinkReceptionist.partyMenu"][1],
            selection_check=linked["SlinkReceptionist.selectionCheck"][1],
            offer_result=linked["SlinkReceptionist.offerReturned"][1],
            notice=linked["SlinkTradeUINotice"][1],
            notice_done=linked["SlinkTradeUINoticeDone"][1],
            messages={name: linked["SlinkReceptionist."+name+"Text"][1] for name in
                      ("noLinked", "offerSent", "offerRejected", "offerUnknown", "invalidParty", "selectionChanged")},
            menus_restored=linked["SlinkReceptionist.menusRestored"][1])
        receptionist_meta["ui"] = extra_sections["SlinkTradeUIWaitReleased"]
        receptionist_meta["partner_prompt"] = {
            **extra_sections["SlinkPartnerPrompt"], "choice": linked["SlinkPartnerPrompt.choice"][1],
            "question": linked["SlinkPartnerPrompt.question"][1],
            "saved_fields": {name: symbols[name.split(" + ")[0]][1] + (1 if " + " in name else 0) for name in PROMPT_STATE},
        }
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
    output = ROOT / f"patch/gen1/build/{prefix_name}trade_{title}.gb"
    output.write_bytes(final)
    assert output.read_bytes() == final
    info = {"schema": "gen1-native-trade-build-v1", "runtime_ready": False, "variant": title,
            "source_commit": lock["sources"][source]["commit"], "base_sha1": record["sha1"],
            "final_sha1": hashlib.sha1(final).hexdigest(), "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "entry": {"bank": bank, "address": start}, "size": len(payload), "native_calls": anchors,
            "ram": {name: symbols[name][1] for name in ram_fields}, "test_probe": probe_symbols, "trade_music": trade_music,
            "output": output.relative_to(ROOT).as_posix()}
    if foreground:
        info["foreground"] = foreground_meta
        save_bank, save_address = symbols["sGameData"]
        save_end_bank, save_end = symbols["sMainDataCheckSum"]
        party_start, party_end = symbols["wPartyDataStart"][1], symbols["wPartyDataEnd"][1]
        if save_bank != save_end_bank or party_end-party_start != 404:
            raise ValueError("native receipt storage geometry differs")
        info["readback"] = {
            "party": {"address": party_start, "length": party_end-party_start, "domain": "System Bus"},
            "save": {"address": save_bank*0x2000+save_address%0x2000,
                     "length": save_end-save_address+1, "domain": "CartRAM"},
            "saved_party_offset": symbols["sPartyData"][1]-save_address,
        }
    if receptionist:
        info["receptionist"] = receptionist_meta
    (directory / "manifest.json").write_text(json.dumps(info, indent=2) + "\n")
    return info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", choices=TARGETS)
    parser.add_argument("--probe", action="store_true", help="include isolated test-only free-bank entry")
    parser.add_argument("--foreground", action="store_true", help="include unadvertised foreground lease/service prototype")
    parser.add_argument("--receptionist", action="store_true", help="include native receptionist menu prototype")
    args = parser.parse_args()
    report = verify()
    if report["failures"]:
        raise SystemExit("canonical validation failed: " + repr(report["failures"]))
    for title in [args.rom] if args.rom else TARGETS:
        result = build(title, verified=True, probe=args.probe, foreground=args.foreground, receptionist=args.receptionist)
        print(json.dumps({key: result[key] for key in ("variant", "runtime_ready", "entry", "size", "final_sha1", "output")}))
