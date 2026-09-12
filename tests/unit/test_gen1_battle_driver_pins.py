"""Pins for lua/tests/gen1_battle_driver.lua: every PC / WRAM address the driver relies on, and
the core.asm facts its state machine encodes, checked against the three .sym files, the clean
ROM bytes and the pret source (Red, Blue, Yellow)."""

import re

import tests.unit.test_battle_force_window_analysis as analysis
from tests.unit.test_battle_force_window_analysis import census, lo_hi, rom_at, routine

pinned = analysis.pinned  # module-scoped fixture, parametrised red/blue/yellow


def block(text, label):
    """Source from a local `.label` line to the next label of any kind (analysis.local stops only
    at global `Label:` lines, which these routines have none of after the local labels)."""
    start = re.search(rf"^{re.escape(label)}\s*(;.*)?\n", text, re.M).end()
    end = re.compile(r"^\.?[A-Za-z_]\w*", re.M).search(text, start)
    return text[start:end.start() if end else len(text)]

RB, Y = "rb", "y"
# bank $0F PCs the driver hooks (read-only bus-exec, bank-filtered on hLoadedROMBank)
SITES = {
    "display_battle_menu": ("DisplayBattleMenu", {RB: 0x4EB3, Y: 0x4F78}),
    "move_selection_menu": ("MoveSelectionMenu", {RB: 0x5219, Y: 0x5320}),
    "select_enemy_move": ("SelectEnemyMove", {RB: 0x5564, Y: 0x56D6}),
    "execute_player_move": ("ExecutePlayerMove", {RB: 0x565E, Y: 0x57D0}),
    "execute_enemy_move": ("ExecuteEnemyMove", {RB: 0x66BC, Y: 0x6842}),
}
# WRAM/HRAM the driver reads; a single value means identical across the three titles
ADDRESSES = {
    "wTopMenuItemY": 0xCC24, "wTopMenuItemX": 0xCC25, "wCurrentMenuItem": 0xCC26,
    "wMaxMenuItem": 0xCC28, "wMenuWatchedKeys": 0xCC29, "wPlayerMoveListIndex": 0xCC2E,
    "wPlayerMonNumber": 0xCC2F, "wMenuJoypadPollCount": 0xCC34, "wListScrollOffset": 0xCC36,
    "wMoveMenuType": 0xCCDB, "wPlayerSelectedMove": 0xCCDC, "wEnemySelectedMove": 0xCCDD,
    "wActionResultOrTookBattleTurn": 0xCD6A, "wNumMovesMinusOne": 0xCD6C,
    "hJoyPressed": 0xFFB3, "hJoyHeld": 0xFFB4, "hJoy5": 0xFFB5, "hJoy7": 0xFFB7,
    "hLoadedROMBank": 0xFFB8, "hFrameCounter": 0xFFD5,
    "wCurItem": {RB: 0xCF91, Y: 0xCF90}, "wWhichPokemon": {RB: 0xCF92, Y: 0xCF91},
    "wEnemyMonHP": {RB: 0xCFE6, Y: 0xCFE5}, "wBattleMonHP": {RB: 0xD015, Y: 0xD014},
    "wBattleMonMoves": {RB: 0xD01C, Y: 0xD01B}, "wBattleMonPP": {RB: 0xD02D, Y: 0xD02C},
    "wIsInBattle": {RB: 0xD057, Y: 0xD056}, "wNumRunAttempts": {RB: 0xD120, Y: 0xD11F},
    "wPartyCount": {RB: 0xD163, Y: 0xD162}, "wListCount": {RB: 0xD12A, Y: 0xD129},
}


def title_key(p):
    return Y if p.title == "yellow" else RB


def span(p, start, end):
    """Clean-ROM bytes from label `start` up to label `end` (same bank)."""
    a, b = p.sym[start], p.sym[end]
    assert a[0] == b[0] and a[1] < b[1], (start, end)
    return p.rom[census.flat(a):census.flat(b)]


def jr_target(p, label, offset):
    """Absolute target of the `jr` whose opcode sits at `offset` bytes after `label`."""
    disp = p.rom[census.flat(p.sym[label]) + offset + 1]
    return p.sym[label][1] + offset + 2 + (disp - 256 if disp > 127 else disp)


def test_hooked_pcs_are_bank_0f_and_exactly_as_tabled(pinned):
    p = pinned
    for name, (label, want) in SITES.items():
        assert p.sym[label] == (0x0F, want[title_key(p)]), (name, p.title)


def test_driver_addresses_match_the_sym(pinned):
    p = pinned
    for label, want in ADDRESSES.items():
        if isinstance(want, dict):
            want = want[title_key(p)]
        assert p.sym[label] == (0, want), (label, p.title)


def test_move_menu_state_is_x5_one_based_cursor_and_max_is_move_count_plus_one(pinned):
    p = pinned
    src = routine(p.core, "MoveSelectionMenu")
    regular = block(src, ".regularmenu")
    assert "ld b, $5" in regular and "ld a, $c" in regular and "jr .menuset" in regular
    assert "\tld [hli], a ; wTopMenuItemY\n\tld a, b\n\tld [hli], a ; wTopMenuItemX\n" in block(src, ".menuset")
    assert re.search(r"ld a, \[wPlayerMoveListIndex\]\n\tinc a\n\.selectedmoveknown\n\tld \[hli\], a ; wCurrentMenuItem", src)
    assert re.search(r"ld a, \[wNumMovesMinusOne\]\n\tinc a\n\tinc a\n\tld \[hli\], a ; wMaxMenuItem", src)
    assert "ld b, ~(PAD_LEFT | PAD_RIGHT | PAD_START)" in src
    rom = span(p, "MoveSelectionMenu", "SelectMenuItem")
    assert b"\x06\x05\x3e\x0c\x18" in rom                                   # ld b,5 / ld a,$c / jr .menuset
    assert b"\xfa" + lo_hi(p, "wNumMovesMinusOne") + b"\x3c\x3c\x22" in rom  # max = moves-1 +2
    assert b"\xfa" + lo_hi(p, "wPlayerMoveListIndex") + b"\x3c\x22" in rom   # cur = index + 1
    assert b"\x06\xc7" in rom                                               # watched = ~(LEFT|RIGHT|START)
    # .regularmenu bails out with Struggle already selected when nothing is usable
    assert regular.startswith("\tcall AnyMoveToSelect\n\tret z\n")


def test_move_cursor_wraps_through_the_sentinel_row(pinned):
    p = pinned
    up = span(p, "SelectMenuItem_CursorUp", "SelectMenuItem_CursorDown")
    down = span(p, "SelectMenuItem_CursorDown", "AnyMoveToSelect")
    cur = lo_hi(p, "wCurrentMenuItem")
    nmm1 = lo_hi(p, "wNumMovesMinusOne")
    assert up.startswith(b"\xfa" + cur + b"\xa7\xc2" + lo_hi(p, "SelectMenuItem"))  # cur==0 -> wrap
    assert b"\xfa" + nmm1 + b"\x3c\xea" + cur in up                                  # cur = moves
    assert b"\xfa" + nmm1 + b"\x3c\x3c\xb8\xc2" + lo_hi(p, "SelectMenuItem") in down  # cur==moves+1 ?
    assert b"\x3e\x01\xea" + cur in down                                             # -> cur = 1


def test_a_on_a_move_commits_or_prompts_no_pp_and_b_cancels_to_the_loop(pinned):
    p = pinned
    src = routine(p.core, "SelectMenuItem")
    assert "jr z, .noPP" in src and "jr z, .disabled" in src
    assert re.search(r"\.noPP\n\tld hl, MoveNoPPText\n\.print\n\tcall PrintText\n\tcall LoadScreenTilesFromBuffer1\n\tjp MoveSelectionMenu", src)
    nopp = (p.root / "data/text/text_2.asm").read_text(encoding="utf-8")
    assert re.search(r'_MoveNoPPText::\n\ttext "No PP left for"\n\tline "this move!"\n\tprompt', nopp)
    rom = span(p, "SelectMenuItem", "MoveNoPPText")
    cur = lo_hi(p, "wCurrentMenuItem")
    assert b"\xfa" + cur + b"\x3d\xea" + cur in rom                       # 1-based -> 0-based
    assert b"\xf1\xc0" in rom                                              # pop af / ret nz  (B: no move)
    assert (b"\x21" + lo_hi(p, "wBattleMonPP") + b"\xfa" + cur + b"\x4f\x06\x00\x09\x7e\xe6\x3f\x28") in rom
    assert (b"\xfa" + cur + b"\x21" + lo_hi(p, "wBattleMonMoves") + b"\x4f\x06\x00\x09\x7e\xea"
            + lo_hi(p, "wPlayerSelectedMove") + b"\xaf\xc9") in rom      # commit, ret z


def test_main_loop_cancel_edge_and_both_execute_sites(pinned):
    p = pinned
    src = routine(p.core, "MainInBattleLoop")
    assert "jr nz, MainInBattleLoop ; if the player didn't select a move, jump" in src
    assert src.count("call ExecutePlayerMove") == 2 and src.count("call ExecuteEnemyMove") == 2
    rom = span(p, "MainInBattleLoop", "HandlePoisonBurnLeechSeed")
    assert rom.count(b"\xcd" + lo_hi(p, "ExecutePlayerMove")) == 2
    assert rom.count(b"\xcd" + lo_hi(p, "ExecuteEnemyMove")) == 2
    seq = (b"\xcd" + lo_hi(p, "MoveSelectionMenu") + b"\xf5\xcd" + lo_hi(p, "LoadScreenTilesFromBuffer1")
           + b"\xcd" + lo_hi(p, "DrawHUDsAndHPBars") + b"\xf1\x20")
    at = rom.find(seq)
    assert at >= 0 and rom.count(seq) == 1
    assert jr_target(p, "MainInBattleLoop", at + len(seq) - 1) == p.sym["MainInBattleLoop"][1]
    assert rom[at + len(seq) + 1:at + len(seq) + 4] == b"\xcd" + lo_hi(p, "SelectEnemyMove")
    # a used turn (item / switch / failed run) still passes ExecutePlayerMove's entry
    assert rom_at(p, "ExecutePlayerMove", 10) == (b"\xaf\xe0\xf3\xfa" + lo_hi(p, "wPlayerSelectedMove")
                                                  + b"\x3c\xca" + lo_hi(p, "ExecutePlayerMoveDone"))
    assert "jp nz, ExecutePlayerMoveDone" in routine(p.core, "ExecutePlayerMove")


def test_battle_menu_columns_and_watched_keys(pinned):
    p = pinned
    src = routine(p.core, "DisplayBattleMenu")
    assert "ld b, $9 ; top menu item X" in block(src, ".leftColumn")
    assert "ld b, $f ; top menu item X" in block(src, ".rightColumn")
    assert "add $2 ; if we're in the right column, the actual id is +2" in src
    rom = span(p, "DisplayBattleMenu", "MoveSelectionMenu")
    hmi = lo_hi(p, "HandleMenuInput")
    assert b"\x06\x09\x18" in rom and b"\x06\x0f\x18" in rom
    assert b"\x21\x24\xcc\x3e\x0e\x22\x78\x22\x23\x23\x3e\x01\x22\x36\x11\xcd" + hmi in rom  # left: RIGHT|A
    assert b"\x21\x24\xcc\x3e\x0e\x22\x78\x22\x23\x23\x3e\x01\x22\x3e\x21\x22\xcd" + hmi in rom  # right: LEFT|A
    # SWITCH/STATS/CANCEL box: y=x=$c, cur=0, max=2, watched B|A
    assert b"\x21\x24\xcc\x3e\x0c\x22\x22\xaf\x22\x23\x3e\x02\x22\x3e\x03\x22\xaf\x77\xcd" + hmi in rom
    assert "ld a, [wWhichPokemon]\n\tld [wPlayerMonNumber], a" in routine(p.core, "SwitchPlayerMon")


def test_party_and_bag_menu_state(pinned):
    p = pinned
    init = rom_at(p, "PartyMenuInit", 64)
    assert (b"\x21\x24\xcc\x3c\x22\xaf\x22\xfa" + lo_hi(p, "wPartyAndBillsPCSavedMenuItem") + b"\xf5\x22\x23\xfa"
            + lo_hi(p, "wPartyCount") + b"\xa7\x28\x01\x3d\x22") in init  # y=1 x=0 max=count-1
    bag = span(p, "DisplayListMenuID", "DisplayListMenuIDLoop")
    assert bag.startswith(b"\xaf\xe0\xba\x3e\x01\xe0\xb7")  # hJoy7 = 1 only inside list menus
    assert (b"\xfa" + lo_hi(p, "wListCount") + b"\xfe\x02\x38\x02\x3e\x02\xea\x28\xcc\x3e\x04\xea\x24\xcc"
            b"\x3e\x05\xea\x25\xcc\x3e\x07\xea\x29\xcc") in bag  # max 2|1, y=4, x=5, A|B|SELECT
    assert "hJoy7" not in p.core  # battle menus never touch it: edge-only input


def test_menu_input_is_an_edge_against_the_games_last_poll(pinned):
    p = pinned
    # JoypadLowSensitivity: hJoy7==0 -> hJoy5 = hJoyPressed; a new press arms the 30-frame repeat delay
    assert rom_at(p, "JoypadLowSensitivity", 24) == (
        b"\xcd" + lo_hi(p, "Joypad") + b"\xf0\xb7\xa7\xf0\xb3\x28\x02\xf0\xb4\xe0\xb5\xf0\xb3\xa7\x28\x05\x3e\x1e\xe0\xd5\xc9")
    # _Joypad: pressed = (last ^ input) & input, against hJoyLast from the PREVIOUS poll
    joypad = rom_at(p, "_Joypad", 32)
    assert joypad.startswith(b"\xf0" + bytes([p.sym["hJoyInput"][1] & 0xFF]))
    assert b"\xca" + lo_hi(p, "TrySoftReset") in joypad
    assert b"\xf0\xb1\x5f\xa8\x57\xa3\xe0\xb2\x7a\xa0\xe0\xb3\x78\xe0\xb1" in joypad  # hJoyLast ^ hJoyInput
    # HandleMenuInput_: PlaceMenuCursor + Delay3 before polling; only wMenuJoypadPollCount==1 gives up
    hmi = span(p, "HandleMenuInput_", "PlaceMenuCursor")
    assert b"\xcd" + lo_hi(p, "PlaceMenuCursor") + b"\xcd" + lo_hi(p, "Delay3") in hmi
    assert b"\xcd" + lo_hi(p, "JoypadLowSensitivity") + b"\xf0\xb5\xa7\x20" in hmi
    assert b"\xfa\x34\xcc\x3d\x28" in hmi
    assert rom_at(p, "Delay3", 5) == b"\x0e\x03\xc3" + lo_hi(p, "DelayFrames")
