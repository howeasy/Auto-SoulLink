"""Pin the source facts behind docs/gen1_reference/BATTLE_FORCE_FAINT_WINDOW.md.

That document concludes there is NO held battle force-faint window. These tests do not
prove the conclusion; they make every instruction, address and source line it cites fail
loudly if the pinned pret sources, .sym files or clean ROMs drift from what was read.
"""
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCK = json.loads((ROOT / "data/pret_sources.lock.json").read_text())
CHECKPOINT = json.loads((ROOT / "data/games/gen1_rby/write_checkpoint.json").read_text())
NO_WAIT = ("DelayFrame", "Delay3", "DelayFrames", "halt")
DELAY_FRAME = bytes.fromhex("3e01e0d676f0d6a720fac9")  # ld a,1; ldh [hVBlankOccurred],a; halt; ...


def _tools():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import gen_gen1_acquisition_sources as census
    finally:
        sys.path.pop(0)
    return census


census = _tools()


@pytest.fixture(scope="module", params=["red", "blue", "yellow"])
def pinned(request):
    source, target = census.TITLES[request.param]
    root = ROOT / ".cache/pret" / source
    return SimpleNamespace(
        title=request.param, root=root, sym=census.symbols(root / f"{target}.sym"),
        rom=(ROOT / LOCK["clean_roms"][target]["filename"]).read_bytes(),
        core=(root / "engine/battle/core.asm").read_text(encoding="utf-8"),
    )


def rom_at(p, name, length):
    offset = census.flat(p.sym[name])
    return p.rom[offset:offset + length]


def lo_hi(p, name):
    return bytes((p.sym[name][1] & 255, p.sym[name][1] >> 8))


def routine(text, name):
    """Source text from the `name:` label to the next global label."""
    start = re.search(rf"^{re.escape(name)}::?\n", text, re.M).end()
    end = re.compile(r"^[A-Za-z_]\w*::?\s*(;.*)?$", re.M).search(text, start)
    return text[start:end.start() if end else len(text)]


def local(text, label):
    """Source text from a local `.label` to the next local or global label."""
    start = re.search(rf"^{re.escape(label)}\s*(;.*)?\n", text, re.M).end()
    end = re.compile(r"^\.?[A-Za-z_]\w*::?\s*(;.*)?$", re.M).search(text, start)
    return text[start:end.start()]


def test_loop_head_copies_battle_hp_down_then_faints_on_zero(pinned):
    p = pinned
    assert p.sym["MainInBattleLoop"][0] == 0x0F
    head = (b"\xcd" + lo_hi(p, "ReadPlayerMonCurHPAndStatus") + b"\x21" + lo_hi(p, "wBattleMonHP")
            + b"\x2a\xb6\xca" + lo_hi(p, "HandlePlayerMonFainted"))
    assert rom_at(p, "MainInBattleLoop", len(head)) == head
    assert "jp z, HandlePlayerMonFainted" in routine(p.core, "MainInBattleLoop").splitlines()[4]


def test_battle_struct_is_the_source_and_the_party_slot_the_copy(pinned):
    p = pinned
    copy = (b"\xfa" + lo_hi(p, "wPlayerMonNumber") + b"\x21" + lo_hi(p, "wPartyMon1HP") + b"\x01\x2c\x00"
            + b"\xcd" + lo_hi(p, "AddNTimes") + b"\x54\x5d"  # ld d,h ; ld e,l  -> de = party slot
            + b"\x21" + lo_hi(p, "wBattleMonHP") + b"\x01\x04\x00" + b"\xc3" + lo_hi(p, "CopyData"))
    assert rom_at(p, "ReadPlayerMonCurHPAndStatus", len(copy)) == copy
    hp = p.sym["wBattleMonHP"][1]
    assert (p.sym["wBattleMonPartyPos"][1], p.sym["wBattleMonStatus"][1]) == (hp + 2, hp + 3)
    assert p.sym["wPartyMon1HP"][1] == p.sym["wPartyMon1Species"][1] + 1


def test_battle_menu_waits_in_a_busy_loop_and_only_delay_frame_halts(pinned):
    p = pinned
    window = (p.root / "home/window.asm").read_text(encoding="utf-8")
    menu = routine(window, "HandleMenuInput_")
    loop2 = menu[menu.index(".loop2\n"):menu.index("\tjr .loop2")]
    assert "call Delay3" in menu[menu.index(".loop1\n"):menu.index(".loop2\n")]
    assert not any(wait in loop2 for wait in NO_WAIT)
    for path, name, stop in (("home/joypad2.asm", "JoypadLowSensitivity", "WaitForTextScrollButtonPress"),
                             ("engine/joypad.asm", "_Joypad", "TrySoftReset")):
        text = (p.root / path).read_text(encoding="utf-8")
        body = text[text.index(f"{name}::"):text.index(f"{stop}:")]
        assert not any(wait in body for wait in NO_WAIT), (path, name)
    assert "call DelayFrame" in routine((p.root / "engine/joypad.asm").read_text(encoding="utf-8"), "TrySoftReset")
    # .loop2 is HandleMenuInput_+0x17: the return address of the transient Delay3 halt.
    assert rom_at(p, "HandleMenuInput_", 0x18)[0x14:] == b"\xcd" + lo_hi(p, "Delay3") + b"\xe5"
    assert rom_at(p, "DelayFrame", len(DELAY_FRAME)) == DELAY_FRAME
    profile = CHECKPOINT[p.title]
    assert profile["write_safe"]["delay_frame"] == p.sym["DelayFrame"][1]
    assert profile["BATTLE_FLAG_ADDR"] == p.sym["wIsInBattle"][1]


def test_player_move_has_no_hp_gate_and_faint_is_only_caught_after_damage(pinned):
    p = pinned
    prologue = b"\xaf\xe0\xf3\xfa" + lo_hi(p, "wPlayerSelectedMove") + b"\x3c\xca" + lo_hi(p, "ExecutePlayerMoveDone")
    assert rom_at(p, "ExecutePlayerMove", len(prologue)) == prologue
    player = routine(p.core, "ExecutePlayerMove")
    assert "wBattleMonHP" not in player[:player.index(".playerHasNoSpecialCondition")]
    enemy = p.core[p.core.index("ExecuteEnemyMove:"):p.core.index("ExecuteEnemyMoveDone:")]
    assert "\tld hl, wBattleMonHP\n\tld a, [hli]\n\tld b, [hl]\n\tor b\n\tret z\n" in enemy
    poison = routine(p.core, "HandlePoisonBurnLeechSeed")
    assert poison.rstrip().endswith("\tld a, [hli]\n\tor [hl]\n\tret nz          ; test if fainted\n"
                                    "\tcall DrawHUDsAndHPBars\n\tld c, 20\n\tcall DelayFrames\n\txor a\n\tret")


def test_switch_and_medicine_overwrite_battle_hp_from_the_party_copy(pinned):
    p = pinned
    switch = routine(p.core, "SwitchPlayerMon")
    assert "call LoadBattleMonFromParty" in switch and "ReadPlayerMonCurHPAndStatus" not in switch
    assert "ld [wActionResultOrTookBattleTurn], a" in local(p.core, ".notAlreadyOut")
    medicine = local((p.root / "engine/items/item_effects.asm").read_text(encoding="utf-8"), ".updateInBattleData")
    assert "ld a, [wPlayerMonNumber]" in medicine and "ld [wBattleMonHP], a" in medicine
    assert "jr nz, MainInBattleLoop" in local(p.core, ".selectPlayerMove")


def test_genuine_faint_path_owns_status_result_and_yellow_happiness(pinned):
    p = pinned
    faint = routine(p.core, "RemoveFaintedPlayerMon")
    for line in ("ld hl, wPartyGainExpFlags", "ld [wBattleMonStatus], a", "call ReadPlayerMonCurHPAndStatus",
                 "ld [wBattleResult], a", "ld hl, PlayerMonFaintedText"):
        assert line in faint, line
    assert ("PIKAHAPPY_FAINTED" in faint) is (p.title == "yellow")
    assert ("IsThisPartyMonStarterPikachu" in faint) is (p.title == "yellow")
    assert "ld a, [wIsInBattle]" in routine(p.core, "HandlePlayerMonFainted")


def test_loop_reentry_sites_are_exactly_the_seven_analysed(pinned):
    sites = re.findall(r"^\t((?:jr|jp)(?: nz,)?) MainInBattleLoop\b", pinned.core, re.M)
    assert sorted(sites) == ["jp", "jp", "jp", "jp", "jp nz,", "jr", "jr nz,"]
