"""MODEL: execute assembled pureRGB trade control flow with native graphics effects.

The pinned native restore reloads sprites, then font ($8800), overwriting their
walking frames. Ordinary NPC trades subsequently close text; foreground trades
must explicitly run that native sprite reload after restoring presentation state.
No LCD timing, hardware or physical trade qualification is claimed here.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_gen1_trade_patch import _symbols
from tests.unit.test_gen1_trade_save import Gen1Machine
from tools._build_tools_bootstrap import ensure_rgbds

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "patch/gen1/purergb/overlay"


@pytest.fixture(autouse=True)
def isolate_data_dir():
    yield


@pytest.fixture(scope="module")
def native_source():
    source = Path(os.environ.get("SLINK_PURERGB_SRC") or ROOT / ".cache/purergb")
    if not source.is_dir():
        pytest.skip(f"pinned pureRGB source absent at {source}; set SLINK_PURERGB_SRC")
    expected = json.loads((ROOT / "data/purergb_sources.lock.json").read_text())["source"]["commit"]
    assert subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() == expected
    return source


@pytest.fixture(scope="module")
def linked(tmp_path_factory, native_source):
    """Assemble the actual apply source/macros against pinned pureRGB symbols."""
    out = tmp_path_factory.mktemp("pure-trade-restore")
    native = _symbols(ROOT / "data/purergb/purered_slink.sym")
    text = (SOURCE / "native_trade.asm").read_text()
    names = set(re.findall(r"\b[A-Za-z_]\w*\b", text)) & set(native)
    names |= {"_Bankswitch", "InitMapSprites", "LoadPlayerSpriteGraphics", "SFX_Headers_1"}
    definitions, calls = [], {}
    for name in sorted(names):
        bank, address = native[name]
        if address < 0x8000 and not name.startswith("Slink"):
            calls.setdefault((bank, address), []).append(name)
        elif not name.startswith("Slink"):
            definitions.append(f"DEF {name} EQU ${address:04x}")
    for (bank, address), labels in calls.items():
        section = f"ROMX[${address:04x}], BANK[${bank:x}]" if bank else f"ROM0[${address:04x}]"
        definitions.append(f'SECTION "Native {labels[0]}", {section}\n' +
                           "\n".join(name + "::" for name in labels) + "\nret")
    includes = out / "engine/slink"
    includes.mkdir(parents=True)
    shutil.copyfile(SOURCE / "species_table.inc", includes / "species_table.inc")
    unit = out / "test.asm"
    unit.write_text('DEF _RED EQU 1\nINCLUDE "includes.asm"\n' + "\n".join(definitions) +
                    f'\nINCLUDE "{(SOURCE / "native_trade.asm").as_posix()}"\n')
    rgbds = Path(ensure_rgbds("v1.0.3"))
    suffix = ".exe" if os.name == "nt" else ""
    subprocess.run([str(rgbds / ("rgbasm" + suffix)), "-I", str(native_source) + "/",
                    "-I", str(out) + "/", "-o", str(out / "test.o"), str(unit)],
                   check=True, capture_output=True)
    layout = out / "layout.link"
    layout.write_text('ROMX $3f\n  "SLink Native Trade"\n')
    subprocess.run([str(rgbds / ("rgblink" + suffix)), "-p", "0", "-l", str(layout),
                    "-o", str(out / "test.gb"), "-n", str(out / "test.sym"), str(out / "test.o")],
                   check=True, capture_output=True)
    return (out / "test.gb").read_bytes(), _symbols(out / "test.sym"), {at: set(ns) for at, ns in calls.items()}


class GraphicsMachine(Gen1Machine):
    """Native effects follow the pinned reload/font/player branches; others are spies."""
    def __init__(self, linked, mode=0, font=0, append_fails=False):
        super().__init__(linked, append_fails=append_fails)
        # This existing MODEL CPU handles CALL but lacks pureRGB's RST $00.
        # Identify only farcall macro instruction boundaries, not operand bytes.
        code = self.rom[0x3f * 0x4000:0x3f * 0x4000 + self.symbols["SlinkTradeSpeciesTable"][1] - 0x4000]
        self.bank_rst_sites = {0x4000 + m.start() + 5 for m in re.finditer(b"\x06.\x21..\xc7", code, re.S)}
        self.native = _symbols(ROOT / "data/purergb/purered_slink.sym")
        self.mode, self.font = mode, font
        self.player_tiles = {0: 0x11, 1: 0x22, 2: 0x33, 3: 0x44}
        self.original = {}
        for name, value in {"wWalkBikeSurfState": mode, "wFontLoaded": font,
                            "hTileAnimations": 2, "wOptions": 3, "hWY": 0x90,
                            "wUpdateSpritesEnabled": 1}.items():
            self.put(name, value)
            self.original[name] = value
        species = 1
        self.put("hSerialConnectionStatus", 0xff)
        self.put("wPartyCount", 2)
        self.put("wPartySpecies", species)
        self.put("wPartySpecies", species, 1)
        self.put("wPartySpecies", 0xff, 2)
        self.put("wPartyMons", species)
        self.put("wPartyMons", 20, 2)
        self.put("wEnemyPartyCount", 1)
        self.put("wEnemyPartySpecies", species)
        self.put("wEnemyPartySpecies", 0xff, 1)
        self.put("wEnemyMons", species)
        self.put("wEnemyMons", 20, 2)
        self.load_player()

    def fetch(self):
        address = self.pc
        byte = super().fetch()
        if address in self.bank_rst_sites:
            assert byte == 0xc7
            self.invoke(0)
            return 0  # the native RST completed; continue via a MODEL NOP
        return byte

    def at(self, name):
        return self.native[name][1]

    def put(self, name, value, offset=0):
        self.ram[self.at(name) + offset] = value

    def get(self, name):
        return self.ram[self.at(name)]

    def load_player(self):
        # home/overworld.asm:788-818: animation disabled makes non-bike players walk.
        mode = self.get("wWalkBikeSurfState")
        if mode != 1 and not self.get("hTileAnimations"):
            mode = 0
            self.put("wWalkBikeSurfState", mode)
        for name in ("vNPCSprites", "vNPCSprites2"):
            start = self.at(name)
            self.ram[start:start + 12 * 16] = bytes([self.player_tiles[mode]]) * (12 * 16)

    def load_font(self):
        start = self.at("vFont")
        self.ram[start:start + 128 * 16] = bytes([0x99]) * (128 * 16)

    def native_call(self, joined):
        names = set(joined.split("+"))
        if "_Bankswitch" in names:
            names = self.natives[(self.r["b"], self.pair("hl"))]
        name = sorted(names)[0]
        self.calls.append(name)
        keep = set()
        if name == "CopyData":
            for i in range(self.pair("bc")):
                self.ram[self.pair("de") + i] = self.read(self.pair("hl") + i)
        elif name in ("AddNTimes", "SkipFixedLengthTextEntries"):
            stride = self.pair("bc") if name == "AddNTimes" else 11
            self.set_pair("hl", self.pair("hl") + stride * self.r["a"])
            keep = {"h", "l"}
        elif name == "AddEnemyMonToPlayerParty":
            self.r["f"] = 0x10 if self.append_fails else 0
            keep = {"f"}
        elif name == "InGameTrade_RestoreScreen":
            # home/palettes.asm -> home/reload_sprites.asm: player load THEN font.
            self.load_player()
            self.load_font()
        elif name == "LoadFontTilePatterns":
            self.load_font()
        elif name == "InitMapSprites":
            # FONT bit forces safe upper-frame reload even for unchanged outdoor set.
            assert self.get("wFontLoaded") & 1
            self.ram[self.at("vNPCSprites2") + 12 * 16] = 0x55
        elif name == "LoadPlayerSpriteGraphics":
            self.load_player()
        elif name == "SaveGameData":
            self.saves.append({n: self.get(n) for n in self.original})
        elif name not in {"SaveScreenTilesToBuffer2", "RemovePokemon", "PlaySound", "DelayFrames",
                           "ClearScreen", "LoadHpBarAndStatusTilePatterns", "InternalClockTradeAnim",
                           "TryEvolvingMon", "RedrawMapView", "UpdateSprites", "Delay3", "PlayDefaultMusic"}:
            raise AssertionError(f"unmodeled native {name}")
        for reg in "abcdehl":
            if reg not in keep:
                self.r[reg] = 0xa5
        return True


@pytest.mark.parametrize("mode", [0, 1, 2, 3])
@pytest.mark.parametrize("font", [0, 0x80])
def test_trade_returns_with_player_walking_tiles_and_state_restored(linked, mode, font):
    m = GraphicsMachine(linked, mode, font)
    m.run("SlinkTradeApply")
    assert m.r["d"] == 0
    start = m.at("vNPCSprites2")
    assert m.ram[start:start + 12 * 16] == bytes([m.player_tiles[mode]]) * (12 * 16), \
        "trade left font glyphs in the player's walking frame tiles until area change"
    assert m.ram[start + 12 * 16] == 0x55, "map NPC walking frames also need the native close-text reload"
    assert {n: m.get(n) for n in m.original} == m.original
    assert m.saves == [m.original]
    assert m.calls.index("InitMapSprites") > m.calls.index("InGameTrade_RestoreScreen")
    assert m.calls.index("SaveGameData") > m.calls.index("LoadPlayerSpriteGraphics")


def test_uncertain_append_does_not_reload_or_save(linked):
    m = GraphicsMachine(linked, mode=2, append_fails=True)
    m.run("SlinkTradeApply")
    assert m.r["d"] == 2 and not m.saves
    assert "InitMapSprites" not in m.calls
    assert {n: m.get(n) for n in m.original} == m.original


def test_refused_trade_has_no_native_effects(linked):
    m = GraphicsMachine(linked)
    m.put("wIsInBattle", 1)
    m.run("SlinkTradeApply")
    assert m.r["d"] == 1 and m.r["f"] & 0x10
    assert not m.calls


def test_native_graphics_model_is_bound_to_pinned_source(native_source):
    """Fail if the native call order/VRAM alias/branch facts used above drift."""
    def read(path):
        return (native_source / path).read_text()
    reload = read("home/reload_sprites.asm")
    assert reload.index("call LoadPlayerSpriteGraphics") < reload.index("call LoadFontTilePatterns")
    assert "call ReloadMapSpriteTilePatterns" in read("home/palettes.asm")
    assert "call RestoreScreenTilesAndReloadTilePatterns" in read("engine/events/in_game_trades.asm")
    assert "ld hl, vFont" in read("engine/menus/load_font.asm")
    vram = read("ram/vram.asm")
    assert "vFont::     ds $80 tiles" in vram and "vNPCSprites2:: ds $80 tiles" in vram
    player = read("home/overworld.asm").split("LoadPlayerSpriteGraphics::", 1)[1].split("IsBikeRidingAllowed::", 1)[0]
    assert player.index("ldh a, [hTileAnimations]") < player.index(".startWalking\n")
    assert "ld [wWalkBikeSurfState], a" in player
    close = read("home/text_script.asm").split("CloseTextDisplayPart2:", 1)[1]
    assert close.index("call InitMapSprites") < close.index("res BIT_FONT_LOADED") < close.index("LoadPlayerSpriteGraphics")
