"""Gen 1 trade save/step fixes, the Gen 1 side of review 1b33bc31 (BLOCKER-2, MAJOR-1, MINOR-2).

MODEL, never physical proof: the linked Red bank-$3F code runs in the Gen 2 trade MODEL CPU
(tests/unit/test_gen2_trade_service.py TradeMachine) with every pret native a spy, resolved by
address from data/pret/pokered.sym. The pureRGB overlay is a port of the same code linked into
pureRGB, so it is held to the vanilla hunks by source parity instead.

Vanilla facts (pret/pokered 405b624): CableClubNPC asks "we have to save the game" and runs
`callfar SaveGameData` before any link (engine/link/cable_club_npc.asm:56-67); the Trade Center
then saves only party+dex after each trade (engine/link/cable_club.asm:864), which is safe only
because nothing else can change in between. SaveMainData records wOptions, wStatusFlags5 (both
in wMainData) and hTileAnimations (engine/menus/save.asm:208-244). The START menu (and SAVE)
opens only on the OverworldLoop frames checked in home/overworld.asm:46-80.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_gen1_trade_patch import _rgbds
from tests.unit.test_gen2_trade_service import TradeMachine

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "patch/gen1/src"
PURE = ROOT / "patch/gen1/purergb/overlay"

# pret/pokered 405b624 RAM (data/pret/pokered.sym)
OVERLAY, BACKUP = 0xC508, 0xD8A4 + 44
H_TILE_ANIM, H_WY, W_OPTIONS = 0xFFD7, 0xFFB0, 0xD355
W_CURRENT_MENU_ITEM = 0xCC26
YES, NO = 0, 1


@pytest.fixture(autouse=True)
def isolate_data_dir():
    """This suite writes no server state."""
    yield


def _multisym(path: Path) -> dict[tuple[int, int], set[str]]:
    rows: dict[tuple[int, int], set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if m := re.fullmatch(r"([0-9a-fA-F]+):([0-9a-fA-F]+) (\S+)", line):
            rows.setdefault((int(m[1], 16), int(m[2], 16)), set()).add(m[3])
    return rows


class Syms(dict):
    native_calls: dict


@pytest.fixture(scope="module")
def linked(tmp_path_factory):
    rgbds, suffix = _rgbds()
    out = tmp_path_factory.mktemp("gen1-trade-save")
    asm, link = str(rgbds / ("rgbasm" + suffix)), str(rgbds / ("rgblink" + suffix))
    subprocess.run([asm, "-o", str(out / "slink.o"), str(SOURCE / "slink.asm")],
                   check=True, capture_output=True)
    subprocess.run([asm, "-I", str(SOURCE) + "/", "-o", str(out / "trade.o"),
                    str(SOURCE / "trade.asm")], check=True, capture_output=True)
    subprocess.run([link, "-p", "0x00", "-o", str(out / "stub.gb"), "-n", str(out / "stub.sym"),
                    str(out / "slink.o"), str(out / "trade.o")], check=True, capture_output=True)
    own = {name: at for at, names in _multisym(out / "stub.sym").items() for name in names}
    natives = {at: names for at, names in _multisym(ROOT / "data/pret/pokered.sym").items()
               if at[1] < 0x8000 and at[0] != 0x3F}
    return (out / "stub.gb").read_bytes(), own, natives


class Halt(Exception):
    pass


class Gen1Machine(TradeMachine):
    """Every native is a spy that scrambles the registers it does not return."""

    def __init__(self, linked, answers=(), append_fails=False, spied=()):
        image, own, natives = linked
        self.rom, self.title = image, "gen1"
        self.symbols = Syms(own)
        self.natives = dict(natives)
        for name in spied:  # own routines a test stands in for
            self.natives[own[name]] = {name}
        self.symbols.native_calls = {at: "+".join(sorted(n)) for at, n in self.natives.items()}
        self.r = dict.fromkeys("afbcdehl", 0)
        self.ram = bytearray(65536)
        self.bank, self.pc, self.sp = 0x3F, 0, 0xDFF0
        self.mailbox = 0x10000  # Machine.write's Gen 2 mailbox probe never fires
        self.written, self.mailbox_flag_samples, self.clear_vblank_on_mailbox = [], [], False
        self.lowest_sp = self.sp
        self.answers, self.append_fails = list(answers), append_fails
        self.calls: list[str] = []
        self.saves: list[dict] = []
        self.texts: list[int] = []
        self.halt_on_done = False

    def text_at(self, address):
        out, bank = [], 0x3F if address >= 0x4000 else 0
        base = bank * 0x4000 + address - (0x4000 if bank else 0)
        for byte in self.rom[base:base + 64]:
            if byte in (0x57, 0x58):  # <DONE> <PROMPT>
                break
            out.append(chr(byte - 0x80 + ord("A")) if 0x80 <= byte <= 0x99 else
                       chr(byte - 0xA0 + ord("a")) if 0xA0 <= byte <= 0xB9 else
                       "." if byte == 0xE8 else " ")  # pret constants/charmap.asm
        return re.sub(" +", " ", "".join(out)).strip()

    def native_call(self, joined):
        names = set(joined.split("+"))
        if "Bankswitch" in names:
            target = (self.r["b"], self.pair("hl"))
            names = self.natives.get(target)
            assert names, f"unmodeled banked call {target}"
        name = (names & SPIES).pop() if names & SPIES else None
        assert name, f"unmodeled native {sorted(names)}"
        self.calls.append(name)
        hl, keep = self.pair("hl"), ()
        if name in ("CopyData",):
            bc, de = self.pair("bc"), self.pair("de")
            for i in range(bc):
                self.ram[de + i] = self.read(hl + i)
            self.set_pair("hl", hl + bc), self.set_pair("de", de + bc), self.set_pair("bc", 0)
            keep = ("h", "l", "d", "e", "b", "c")
        elif name == "SkipFixedLengthTextEntries":
            self.set_pair("hl", hl + 11 * self.r["a"])
            keep = ("h", "l")
        elif name == "AddNTimes":
            self.set_pair("hl", hl + self.pair("bc") * self.r["a"])
            keep = ("h", "l")
        elif name == "YesNoChoice":
            assert self.answers, "an unscripted YES/NO was asked"
            self.ram[W_CURRENT_MENU_ITEM] = self.answers.pop(0)
        elif name == "PrintText":
            self.texts.append(hl)
        elif name in ("SaveGameData", "SavePartyAndDexData"):
            self.saves.append({"kind": name, "anim": self.ram[H_TILE_ANIM],
                               "options": self.ram[W_OPTIONS], "wy": self.ram[H_WY],
                               "texts": len(self.texts)})
        elif name == "AddEnemyMonToPlayerParty":
            self.r["f"] = 0x10 if self.append_fails else 0
            keep = ("f",)
        elif name == "DelayFrame" and self.halt_on_done and self.ram[OVERLAY + 5] == 7:
            raise Halt
        for reg in "abcdehl":
            if reg not in keep:
                self.r[reg] = 0xA5
        return True


SPIES = {"CopyData", "SkipFixedLengthTextEntries", "AddNTimes", "YesNoChoice", "PrintText",
         "SaveGameData", "SavePartyAndDexData", "AddEnemyMonToPlayerParty", "DelayFrame", "Joypad",
         "SaveScreenTilesToBuffer2", "LoadScreenTilesFromBuffer2", "ClearSprites",
         "LoadFontTilePatterns", "ClearScreen", "InGameTrade_RestoreScreen", "RedrawMapView",
         "Delay3", "UpdateSprites", "WaitForSoundToFinish", "PlaySoundWaitForCurrent",
         "RemovePokemon", "PlaySound", "DelayFrames", "LoadHpBarAndStatusTilePatterns",
         "InternalClockTradeAnim", "TryEvolvingMon", "PlayDefaultMusic",
         "SlinkSfxService", "SlinkTradeService"}


def _stage(m: Gen1Machine) -> None:
    """A two-mon party offering slot 0 and one staged incoming mon, the display borrowed state."""
    table = m.symbols["SlinkTradeSpeciesTable"][1]
    species = next(i for i in range(1, 191) if m.rom[0xFC000 + table - 0x4000 + i])
    name = bytes([0x80, 0x81, 0x50]) + bytes(8)
    m.ram[0xFFAA] = 0xFF                                     # hSerialConnectionStatus: no cable
    m.ram[0xD163:0xD166] = bytes([2, species, species])      # wPartyCount, wPartySpecies
    m.ram[0xD166] = 0xFF
    for slot in range(2):
        m.ram[0xD16B + 44 * slot] = species                  # wPartyMons
        m.ram[0xD16B + 44 * slot + 2] = 20                   # HP
        m.ram[0xD2B5 + 11 * slot:0xD2B5 + 11 * slot + 11] = name  # wPartyMonNicks
    m.ram[0xD89C:0xD89F] = bytes([1, species, 0xFF])         # wEnemyPartyCount/Species
    m.ram[0xD8A4], m.ram[0xD8A6] = species, 20               # wEnemyMons
    m.ram[0xD9EE:0xD9EE + 11] = name                         # wEnemyMonNicks
    m.ram[H_TILE_ANIM], m.ram[W_OPTIONS], m.ram[H_WY] = 0x02, 0x03, 0x90


# ── BLOCKER-2, responder: YES needs a second, save consent; the save lands after the restore ──

@pytest.mark.parametrize("answers,result,saved", [
    ((NO,), 1, False),        # the trade question's NO: one question, no save
    ((YES, NO), 1, False),    # YES to the trade, NO to the save: a decline, DONE result 1
    ((YES, YES), 0, True),    # both: the full native save, then DONE result 0
])
def test_partner_prompt_requires_save_consent_and_saves_the_restored_state(linked, answers, result, saved):
    m = Gen1Machine(linked, answers)
    _stage(m)
    m.run("SlinkPartnerPrompt")
    assert m.r["d"] == result and m.answers == []
    assert "SavePartyAndDexData" not in m.calls
    if saved:
        # after slink_restore_prompt_state: SaveMainData records hTileAnimations/wOptions
        assert m.saves == [{"kind": "SaveGameData", "anim": 0x02, "options": 0x03, "wy": 0x90,
                            "texts": 2}]
        assert m.text_at(m.texts[1]) == "We have to save before trading."
        assert m.calls.index("SaveGameData") > m.calls.index("InGameTrade_RestoreScreen")
    else:
        assert m.saves == []


# ── BLOCKER-2, both roles at commit: a full save of the restored state, never party-only ──

def test_apply_commits_with_a_full_native_save_after_the_restores(linked):
    m = Gen1Machine(linked)
    _stage(m)
    m.run("SlinkTradeApply")
    assert m.r["d"] == 0 and m.r["a"] == 0 and not m.r["f"] & 0x10
    assert [s["kind"] for s in m.saves] == ["SaveGameData"]
    assert m.saves[0]["anim"] == 0x02 and m.saves[0]["options"] == 0x03  # restored, not the borrowed 0
    assert m.calls.index("SaveGameData") > m.calls.index("PlayDefaultMusic")


@pytest.mark.parametrize("append_fails,result", [(True, 2), (False, 0)])
def test_apply_saves_nothing_on_the_uncertain_append(linked, append_fails, result):
    m = Gen1Machine(linked, append_fails=append_fails)
    _stage(m)
    m.run("SlinkTradeApply")
    assert m.r["d"] == result and len(m.saves) == (0 if append_fails else 1)


# ── MINOR-2: the uncertain hold says "reset"; a normal commit's hold does not ──

@pytest.mark.parametrize("append_fails", [True, False])
def test_service_prints_a_reset_notice_only_before_the_uncertain_hold(linked, append_fails):
    m = Gen1Machine(linked, append_fails=append_fails)
    _stage(m)
    preimage = bytes(range(0x40, 0x50))
    m.ram[BACKUP:BACKUP + 16] = preimage
    m.ram[OVERLAY:OVERLAY + 16] = b"SLT1" + bytes([1, 5, 3, 2, 0xFF, 0, 1, 0, 9, 8, 7, 6])
    m.halt_on_done = True
    with pytest.raises(Halt):
        m.run("SlinkTradeService")
    assert m.ram[OVERLAY + 5] == 7 and m.ram[OVERLAY + 8] == (2 if append_fails else 0)
    notices = [m.text_at(t) for t in m.texts]
    assert notices == (["Trade error. Please reset."] if append_fails else [])


# ── MAJOR-1 analog: pickup only on a frame where vanilla could open START (and SAVE) ──

IDLE_FAULTS = {
    "walking": (0xCFC5, 0x08),            # wWalkCounter mid-step
    "ledge_or_fishing": (0xD736, 1 << 6),  # wMovementFlags BIT_LEDGE_OR_FISHING
    "scripted_movement": (0xD730, 1 << 7), # wStatusFlags5 BIT_SCRIPTED_MOVEMENT_STATE
    "start_ignored": (0xCD6B, 1 << 3),     # wJoyIgnore & PAD_START
    "opponent": (0xD059, 0xC9),            # wCurOpponent: a battle starts this frame
    "safari_over": (0xDA46, 1),            # wSafariZoneGameOver
    "script_warp": (0xD72D, 1 << 3),       # wStatusFlags3 BIT_WARP_FROM_CUR_SCRIPT
    "fly_warp": (0xD732, 1 << 3),          # wStatusFlags6 BIT_FLY_WARP
    "dungeon_warp": (0xD732, 1 << 4),      # wStatusFlags6 BIT_DUNGEON_WARP
}


@pytest.mark.parametrize("fault", [None, *IDLE_FAULTS])
def test_foreground_picks_up_the_lease_only_on_an_idle_overworld_frame(linked, fault):
    m = Gen1Machine(linked, spied=("SlinkSfxService", "SlinkTradeService"))
    m.ram[OVERLAY + 10] = 1                     # the lease's armed availability byte
    m.ram[m.sp + 12], m.ram[m.sp + 13] = 0x02, 0x04  # DelayFrame returns into OverworldLoop
    if fault:
        address, value = IDLE_FAULTS[fault]
        m.ram[address] = value
    m.run("SlinkForeground")
    assert m.calls == ["SlinkSfxService"] + ([] if fault else ["SlinkTradeService"])


# ── BLOCKER-2, proposer: consent + save before the party picker and any OFFER ──

def _ops(path: Path, start: str, end: str) -> list[str]:
    """Instruction lines strictly between the first `start` line and the next `end` line;
    comments dropped, whitespace collapsed, `nativecall`/`farcall` read as `call`."""
    ops = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = re.sub(r"\s+", " ", line.split(";")[0]).strip()
        line = re.sub(r"^(?:nativecall|farcall|callfar) ", "call ", line)
        if line:
            ops.append(line)
    first = ops.index(start)
    return ops[first + 1:ops.index(end, first + 1)]


@pytest.mark.parametrize("src", [SOURCE, PURE], ids=["redblue", "purergb"])
def test_receptionist_saves_after_consent_and_before_the_party_picker(src):
    ops = _ops(src / "trade_receptionist.asm", "call .mainMenu", "call .offer")
    consent = ops.index("call SlinkTradeUIMustSave")
    assert ops[consent + 1:consent + 3] == ["jr c, .selectedCancel", "call SlinkTradeUISave"]
    assert ops.index("call .partyMenu") > consent + 2


# pureRGB names the constants the Red/Blue source spells as literals (cited there).
PURE_NAMES = {"NAME_LENGTH": "11", "SFX_SAVE": "SLINK_SFX_SAVE", "PAD_START": "1 << 3",
              "1 << BIT_LEDGE_OR_FISHING": "1 << 6", "1 << BIT_SCRIPTED_MOVEMENT_STATE": "1 << 7",
              "1 << BIT_WARP_FROM_CUR_SCRIPT": "1 << 3",
              "(1 << BIT_FLY_WARP) | (1 << BIT_DUNGEON_WARP)": "(1 << 3) | (1 << 4)"}


def _pure(ops: list[str]) -> list[str]:
    out = []
    for op in ops:
        for name, literal in PURE_NAMES.items():
            op = op.replace(name, literal)
        out.append(op)
    return out


@pytest.mark.parametrize("red,pure,start,end", [
    ("trade_ui.asm", "trade_ui.asm", "SlinkTradeUIMustSave::", "SlinkTradeUINameTable::"),
    ("trade_prompt.asm", "trade_prompt.asm", ".choice", ".unavailable"),
    ("native_trade.asm", "native_trade.asm", "call PlayDefaultMusic", ".refused"),
    ("trade_service.asm", "trade_service.asm", ".apply", ".publish"),
    ("trade_service.asm", "slink.asm", "ld a, [wWalkCounter]", "jp SlinkTradeService"),
])
def test_purergb_overlay_carries_the_same_save_and_step_hunks(red, pure, start, end):
    mine = _ops(SOURCE / red, start, end)
    assert mine == _pure(_ops(PURE / pure, start, end))


def _must_save_lines(path: Path) -> tuple[str, str]:
    m = re.search(r'SlinkTradeUIMustSave::.*?text "([^"]+)"\s*line "([^"]+)"',
                  path.read_text(encoding="utf-8"), re.S)
    assert m, path
    return m[1], m[2]


@pytest.mark.parametrize("driver,before", [
    ("lua/tests/test_gen1_receptionist_gate.lua", '"TRADE WHICH?", 22'),
    ("lua/tests/duo/duo_gen1_main.lua", '"TRADE WHICH?", 22'),
    ("lua/tests/duo/duo_gen1_main.lua", 'answer_must_save("PARTNER")'),
])
def test_physical_drivers_anchor_the_must_save_prompt_on_the_patch_text(driver, before):
    """The live drivers answer the must-save YES before the picker (proposer) and before
    menu_result (partner), anchored on the exact lines both builds print at +281/+321."""
    first, second = _must_save_lines(SOURCE / "trade_ui.asm")
    assert (first, second) == _must_save_lines(PURE / "trade_ui.asm")
    text = (ROOT / driver).read_text(encoding="utf-8")
    anchors = [f'"{first}", 281', f'"{second}", 321']
    assert all(a in text for a in anchors), driver
    assert text.index(anchors[0]) < text.index(before)
