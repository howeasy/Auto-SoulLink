"""Source-derived, isolated map fixtures for the native receptionist component.

CONTINUE sets BIT_NO_PREVIOUS_MAP and reuses cached map/sprite data. The live
fixture hook clears that bit once at LoadMapHeader, so the cartridge itself
loads the new map, objects, collision, tileset and music. No test redirects PC,
adds a sprite, invokes the receptionist directly, or writes a user's save.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from tools.build_gen1_native_trade import ROOT, TARGETS, read_symbols

RAM_FIELDS = (
    "wCurMap", "wCurMapTileset", "wCurMapHeader", "wCurMapHeaderEnd", "wNumSprites", "wMapSpriteData",
    "wSpriteIndex", "hTextID", "hLoadedROMBank", "wOverworldMap", "wCurrentTileBlockMapViewPointer",
    "wTilesetBank", "wTileMap", "wShadowOAM", "wShadowOAMEnd", "wPartyCount", "wPartySpecies", "wPartyMons",
    "wPartyMonOT", "wPartyMonNicks", "wTopMenuItemY", "wMenuJoypadPollCount", "wMenuWrappingEnabled",
    "wMenuWatchMovingOutOfBounds", "wPartyMenuAnimMonEnabled", "hUILayoutFlags", "wUpdateSpritesEnabled",
    "wLinkState", "hSerialConnectionStatus", "wEnteringCableClub", "wIsInBattle",
)
ROM_FIELDS = ("LoadMapHeader", "PrintText", "CableClubNPC", "SavePartyAndDexData", "SaveGameData",
              "InternalClockTradeAnim", "TryEvolvingMon", "CloseTextDisplay", "WaitForTextScrollButtonPress")


def receptionist_maps(variant: str) -> dict[str, dict]:
    """Enumerate every typed receptionist and verify its physical ROM dispatch."""
    target = TARGETS[variant]
    repo = "pokeyellow" if variant == "yellow" else "pokered"
    source = ROOT / f".cache/pret/{repo}"
    syms = read_symbols(source / f"{target}.sym")
    lock = json.loads((ROOT / "data/pret_sources.lock.json").read_text())
    pin = lock["clean_roms"][target]
    rom = (ROOT / pin["filename"]).read_bytes()
    if hashlib.sha1(rom).hexdigest() != pin["sha1"]:
        raise ValueError("canonical fixture ROM hash differs")

    def flat(name):
        bank, address = syms[name]
        return bank * 0x4000 + address % 0x4000

    constants = (source / "constants/map_constants.asm").read_text()
    result = {}
    for script in sorted((source / "scripts").glob("*.asm")):
        text = script.read_text()
        if "script_cable_club_receptionist" not in text:
            continue
        labels = re.findall(r"^(\w+):\s*\n\s*script_cable_club_receptionist\b", text, re.M)
        if len(labels) != 1:
            raise ValueError("ambiguous typed receptionist in " + script.name)
        name = script.stem
        header_text = (source / f"data/maps/headers/{name}.asm").read_text()
        map_name = re.search(r"map_header \w+, (\w+),", header_text)[1]
        match = re.search(rf"map_const {map_name},\s*(\d+),\s*(\d+)\s*;\s*\$([0-9A-F]+)", constants)
        if match is None:
            raise ValueError("missing canonical map dimensions " + map_name)
        width, height, map_id = int(match[1]), int(match[2]), int(match[3], 16)
        objects = (source / f"data/maps/objects/{name}.asm").read_text()
        entries = re.findall(r"^\s*object_event\s+(.+)$", objects, re.M)
        selected = [(index + 1, row) for index, row in enumerate(entries) if "SPRITE_LINK_RECEPTIONIST" in row]
        if len(selected) != 1:
            raise ValueError("missing or extra physical receptionist " + name)
        object_slot, row = selected[0]
        parts = [item.strip() for item in row.split(",")]
        if len(parts) != 6 or parts[3:5] != ["STAY", "DOWN"]:
            raise ValueError("unexpected receptionist placement " + name)
        x, y = int(parts[0]), int(parts[1]) + 1
        pointer_label = re.search(rf"dw_const (\w+),\s*{parts[5]}\b", text)[1]
        if pointer_label != labels[0] or rom[flat(pointer_label)] != 0xF6:
            raise ValueError("typed receptionist ROM byte differs " + name)
        header = rom[flat(name + "_h"):flat(name + "_h") + 12]
        if header[1:3] != bytes((height, width)) or header[9] != 0:
            raise ValueError("unexpected interior map header " + name)
        expected_pointers = b"".join(syms[name + suffix][1].to_bytes(2, "little")
                                     for suffix in ("_Blocks", "_TextPointers", "_Script"))
        if header[3:9] != expected_pointers or header[10:12] != syms[name + "_Object"][1].to_bytes(2, "little"):
            raise ValueError("canonical map pointers differ " + name)
        blocks = rom[flat(name + "_Blocks"):flat(name + "_Blocks") + width * height]
        if blocks != (source / f"maps/{name}.blk").read_bytes():
            raise ValueError("map blocks differ " + name)
        sprite_symbols = [f"wSprite{object_slot:02d}StateData1", f"wSprite{object_slot:02d}StateData2"]
        result[name] = {
            "variant": variant, "source_commit": lock["sources"][repo]["commit"], "base_sha1": pin["sha1"],
            "map_name": name, "map_id": map_id, "x": x, "y": y, "width": width, "height": height,
            "object_count": len(entries), "object_slot": object_slot,
            "header_hex": header[:10].hex(), "blocks_hex": blocks.hex(),
            "ram": {field: syms[field][1] for field in RAM_FIELDS + tuple(sprite_symbols)},
            "rom": {field: {"bank": syms[field][0], "address": syms[field][1]} for field in ROM_FIELDS},
        }
    if not result or "IndigoPlateauLobby" not in result:
        raise ValueError("receptionist catalog is incomplete")
    return result


def make_fixture(variant: str, map_name: str, directory: Path) -> dict:
    return write_fixture(receptionist_maps(variant)[map_name], directory)


def write_fixture(info: dict, directory: Path, *, pokedex=None, safari=False) -> dict:
    """Write an isolated source-derived pre-run fixture; never a live mutation API."""
    import copy
    info = copy.deepcopy(info)
    variant = info["variant"]
    map_name = info["map_name"]
    directory = directory.resolve()
    if not directory.is_relative_to(ROOT.resolve()):
        raise ValueError("receptionist fixtures must remain inside this worktree")
    directory.mkdir(parents=True, exist_ok=True)
    target = TARGETS[variant]
    repo = "pokeyellow" if variant == "yellow" else "pokered"
    syms = read_symbols(ROOT / f".cache/pret/{repo}/{target}.sym")
    fixture = ROOT / f"tests/fixtures/gen1/{variant}_town.SaveRAM"
    raw = bytearray(fixture.read_bytes())
    info["base_fixture_sha256"] = hashlib.sha256(raw).hexdigest()

    def offset(name):
        bank, address = syms[name]
        return bank * 0x2000 + address - 0xA000

    def main_offset(name):
        return offset("sMainData") + syms[name][1] - syms["wMainDataStart"][1]

    x, y, width = info["x"], info["y"], info["width"]
    pointer = syms["wOverworldMap"][1] + 7 + width + (width + 6) * (y >> 1) + (x >> 1)
    start = main_offset("wCurMap")
    raw[start:start + 7] = bytes((info["map_id"], pointer & 255, pointer >> 8, y, x, y & 1, x & 1))
    # LoadTilesetHeader applies wDestinationWarpID when the old/new tilesets
    # differ. This is a same-map CONTINUE fixture, so preserve that identity.
    raw[main_offset("wCurMapTileset")] = bytes.fromhex(info["header_hex"])[0]
    raw[main_offset("wStatusFlags4")] &= ~0x20  # normal map entry reloads sprite data
    if pokedex is not None:
        # Read the exact CheckEvent operand and bit from DrawStartMenu itself.
        b, p = syms["DrawStartMenu"]
        lock = json.loads((ROOT/"data/pret_sources.lock.json").read_text())
        rom = (ROOT/lock["clean_roms"][target]["filename"]).read_bytes()
        code = rom[b*0x4000+p%0x4000:b*0x4000+p%0x4000+5]
        if code[0] != 0xFA or code[3] != 0xCB or code[4] & 0xC7 != 0x47:
            raise ValueError("Pokedex CheckEvent instructions changed")
        address = int.from_bytes(code[1:3], "little")
        index = address-syms["wEventFlags"][1]
        mask = 1 << ((code[4]-0x47)//8)
        position = main_offset("wEventFlags")+index
        raw[position] = (raw[position] | mask) if pokedex else (raw[position] & ~mask)
        info["pokedex"] = bool(pokedex)
        info["pokedex_address"], info["pokedex_mask"] = address, mask
    if safari:
        raw[main_offset("wSafariSteps"):main_offset("wSafariSteps")+2] = (500).to_bytes(2,"big")
        raw[main_offset("wNumSafariBalls")] = 30
        raw[main_offset("wSafariZoneGameOver")] = 0
    raw[offset("sMainDataCheckSum")] = 255 - (sum(raw[offset("sGameData"):offset("sGameDataEnd")]) & 255)
    output = directory / f"{variant}-{map_name}.SaveRAM"
    output.write_bytes(raw)
    info["fixture"] = str(output)
    info["fixture_sha256"] = hashlib.sha256(raw).hexdigest()
    return info
