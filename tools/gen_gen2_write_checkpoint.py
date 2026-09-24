"""Generate source-qualified Gen 2 checkpoint candidates, never write permission.

The synchronous candidate is before CheckAPressOW in OWPlayerInput. Its entire
small instruction body and PlayerEvents caller prefix are assembled from pinned
source assertions and symbols, then compared with the real ROM. No Gen 1 delay
offset, IRQ stack recipe, or live liveness claim is inherited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.gen2_source_data import ROOT, load_context, rom_offset

TITLES = ("crystal", "gold", "silver")
SCHEMA = "gen2-write-checkpoint-v1"
EVENTS = "engine/overworld/events.asm"
RAM_CONSTANTS = "constants/ram_constants.asm"

OW_SOURCE = """OWPlayerInput:
call PlayerMovement
ret c
and a
jr nz, .NoAction
farcall CheckStandingOnIce
jr c, .NoAction
call CheckAPressOW
jr c, .Action
call CheckMenuOW
jr c, .Action
.NoAction:
xor a
ret
.Action:
push af
farcall StopPlayerForEvent
pop af
scf
ret
CheckAPressOW:
"""
CALLER_SOURCE = """PlayerEvents:
xor a
ld a, [wScriptRunning]
and a
ret nz
call Dummy_CheckEnabledMapEventsBit5
call CheckTrainerEvent
jr c, .ok
call CheckTileEvent
jr c, .ok
call RunMemScript
jr c, .ok
call RunSceneScript
jr c, .ok
call CheckTimeEvents
jr c, .ok
call OWPlayerInput
jr c, .ok
xor a
ret
.ok
"""


def _code(text: str) -> list[tuple[int, str]]:
    return [(i, " ".join(line.split(";", 1)[0].split()))
            for i, line in enumerate(text.splitlines(), 1)
            if line.split(";", 1)[0].strip()]


def _cite(ctx, path: str, snippet: str) -> dict:
    """Require one complete consecutive code sequence, preserving source lines."""
    source = ctx.read_source(path)
    lines = _code(source)
    wanted = [line for _, line in _code(snippet)]
    hits = [i for i in range(len(lines) - len(wanted) + 1)
            if [line for _, line in lines[i:i + len(wanted)]] == wanted]
    if not wanted or len(hits) != 1:
        raise ValueError(f"{ctx.title}: missing/ambiguous source assertion in {path}: {snippet!r}")
    start = hits[0]
    return {"commit": ctx.source_commit, "path": path,
            "line_start": lines[start][0], "line_end": lines[start + len(wanted) - 1][0],
            "source_text_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest()}


def _declaration(ctx, name: str) -> dict:
    path = "ram/hram.asm" if name.startswith("h") else "ram/wram.asm"
    source = ctx.read_source(path)
    matches = [(i, line) for i, line in _code(source)
               if re.fullmatch(re.escape(name) + r"::(?: db)?", line)]
    if len(matches) != 1:
        raise ValueError(f"{ctx.title}: missing/ambiguous declaration: {name}")
    return _cite(ctx, path, matches[0][1])


def _enum(ctx, path: str, names: tuple[str, ...]) -> tuple[dict, dict]:
    cite = _cite(ctx, path, "const_def\n" + "\n".join(f"const {name}" for name in names))
    return dict(zip(names, range(len(names)), strict=True)), cite


def _literal(ctx, path: str, name: str) -> tuple[int, dict]:
    matches = []
    for _, line in _code(ctx.read_source(path)):
        match = re.fullmatch(r"DEF " + re.escape(name) + r" EQU (\$[0-9a-f]+|\d+)", line, re.I)
        if match:
            raw = match.group(1)
            matches.append((int(raw[1:], 16) if raw.startswith("$") else int(raw), line))
    if len(matches) != 1:
        raise ValueError(f"{ctx.title}: missing/ambiguous literal: {name}")
    value, line = matches[0]
    return value, _cite(ctx, path, line)


def _memory(ctx, name: str) -> dict:
    symbol = ctx.symbol(name)
    bank, address = symbol.bank, symbol.address
    region = ("WRAM0" if 0xC000 <= address < 0xD000 else
              "WRAMX" if 0xD000 <= address < 0xE000 else
              "HRAM" if 0xFF80 <= address < 0xFFFF else None)
    if region is None or (region == "WRAMX" and bank != 1) or (region != "WRAMX" and bank != 0):
        raise ValueError(f"{ctx.title}: unsupported memory ownership for {name}: {bank}:{address:04x}")
    return {"symbol": name, "bank": bank, "address": address, "region": region,
            "read_domain": "System Bus", "width": 1, "source": _declaration(ctx, name)}


def _word(value: int) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise ValueError("CPU word outside 16-bit range")
    return value.to_bytes(2, "little")


class _Encoder:
    """Only the fixed, source-asserted CPU sequences in this generator."""

    def __init__(self, ctx, label: str):
        self.ctx = ctx
        symbol = ctx.symbol(label)
        self.bank, self.start = symbol.bank, symbol.address
        rom_offset(self.bank, self.start)
        self.data = bytearray()

    @property
    def pc(self) -> int:
        return self.start + len(self.data)

    def call(self, name: str) -> None:
        symbol = self.ctx.symbol(name)
        rom_offset(symbol.bank, symbol.address)
        if symbol.bank not in (0, self.bank):
            raise ValueError(f"near call crosses ROM bank: {name}")
        self.data.extend(b"\xcd" + _word(symbol.address))

    def farcall(self, name: str) -> None:
        symbol = self.ctx.symbol(name)
        rom_offset(symbol.bank, symbol.address)
        rst = self.ctx.symbol("FarCall")
        if rst.bank != 0 or rst.address not in range(0, 0x40, 8) or symbol.bank > 255:
            raise ValueError("farcall bank/RST encoding changed")
        self.data.extend(bytes((0x3E, symbol.bank, 0x21)) + _word(symbol.address)
                         + bytes((0xC7 + rst.address,)))

    def branch(self, opcode: int, name: str) -> None:
        symbol = self.ctx.symbol(name)
        delta = symbol.address - (self.pc + 2)
        if symbol.bank != self.bank or not -128 <= delta <= 127:
            raise ValueError(f"invalid relative target: {name}")
        self.data.extend(bytes((opcode, delta & 255)))

    def label(self, name: str) -> None:
        symbol = self.ctx.symbol(name)
        if (symbol.bank, symbol.address) != (self.bank, self.pc):
            raise ValueError(f"source/symbol instruction layout changed: {name}")

    def anchor(self, source: dict) -> dict:
        offset = rom_offset(self.bank, self.start)
        end = self.start + len(self.data)
        if not self.data or end > (0x4000 if self.bank == 0 else 0x8000):
            raise ValueError("anchor crosses mapped ROM bank")
        if self.ctx.rom[offset:offset + len(self.data)] != self.data:
            raise ValueError(f"{self.ctx.title}: ROM anchor mismatch at {self.bank:02x}:{self.start:04x}")
        return {"bank": self.bank, "address": self.start, "rom_offset": offset,
                "expected_hex": self.data.hex().upper(), "source": source,
                "instruction_set": "SM83", "evidence": "SOURCE"}


def _anchors(ctx) -> tuple[dict, int, int]:
    ow_cite = _cite(ctx, EVENTS, OW_SOURCE)
    caller_cite = _cite(ctx, EVENTS, CALLER_SOURCE)
    macro_cite = _cite(ctx, "macros/farcall.asm",
                       "MACRO farcall\nld a, BANK(\\1)\nld hl, \\1\nrst FarCall\nENDM")
    # Count direct transfer references over the pinned assembly tree. No guessed
    # stack search or alternate call path is silently accepted.
    transfers = []
    pattern = re.compile(r"(?:call|jp|jr|farcall|farjp|callfar) (?:\w+, )?OWPlayerInput$")
    census = subprocess.run(["git", "-C", str(ctx.source_dir), "grep", "-l", "-z", "-F",
                             "OWPlayerInput", "--", "*.asm"], capture_output=True, check=False)
    if census.returncode != 0:
        raise ValueError(f"{ctx.title}: cannot enumerate OWPlayerInput source references")
    for rel in sorted(census.stdout.decode("utf-8").rstrip("\0").split("\0")):
        for line_no, line in _code(ctx.read_source(rel)):
            if pattern.fullmatch(line):
                transfers.append((rel, line_no, line))
    if len(transfers) != 1 or transfers[0][0] != EVENTS or transfers[0][2] != "call OWPlayerInput":
        raise ValueError(f"{ctx.title}: OWPlayerInput caller missing/ambiguous: {transfers}")

    ow = _Encoder(ctx, "OWPlayerInput")
    ow.call("PlayerMovement")
    ow.data.extend((0xD8, 0xA7))  # ret c; and a
    ow.branch(0x20, "OWPlayerInput.NoAction")
    ow.farcall("CheckStandingOnIce")
    ow.branch(0x38, "OWPlayerInput.NoAction")
    checkpoint_pc = ow.pc
    ow.call("CheckAPressOW")
    ow.branch(0x38, "OWPlayerInput.Action")
    ow.call("CheckMenuOW")
    ow.branch(0x38, "OWPlayerInput.Action")
    ow.label("OWPlayerInput.NoAction")
    ow.data.extend((0xAF, 0xC9))
    ow.label("OWPlayerInput.Action")
    ow.data.append(0xF5)
    ow.farcall("StopPlayerForEvent")
    ow.data.extend((0xF1, 0x37, 0xC9))
    ow.label("CheckAPressOW")

    caller = _Encoder(ctx, "PlayerEvents")
    caller.data.extend(b"\xaf\xfa" + _word(ctx.symbol("wScriptRunning").address) + b"\xa7\xc0")
    caller.call("Dummy_CheckEnabledMapEventsBit5")
    for name in ("CheckTrainerEvent", "CheckTileEvent", "RunMemScript", "RunSceneScript", "CheckTimeEvents"):
        caller.call(name)
        caller.branch(0x38, "PlayerEvents.ok")
    caller.call("OWPlayerInput")
    return_pc = caller.pc
    caller.branch(0x38, "PlayerEvents.ok")
    caller.data.extend((0xAF, 0xC9))
    caller.label("PlayerEvents.ok")
    anchors = {"ow_player_input": ow.anchor(ow_cite), "player_events_caller": caller.anchor(caller_cite)}
    anchors["ow_player_input"]["macro_source"] = macro_cite
    anchors["player_events_caller"]["unique_direct_transfer_source"] = {
        "path": transfers[0][0], "line": transfers[0][1], "commit": ctx.source_commit}
    return anchors, checkpoint_pc, return_pc


def _predicates(ctx) -> list[dict]:
    map_status, map_cite = _enum(ctx, RAM_CONSTANTS,
                                ("MAPSTATUS_START", "MAPSTATUS_ENTER", "MAPSTATUS_HANDLE", "MAPSTATUS_DONE"))
    events, event_cite = _enum(ctx, RAM_CONSTANTS, ("MAPEVENTS_ON", "MAPEVENTS_OFF"))
    scripts, script_cite = _enum(ctx, RAM_CONSTANTS,
                               ("SCRIPT_OFF", "SCRIPT_READ", "SCRIPT_WAIT_MOVEMENT", "SCRIPT_WAIT"))
    flags, flag_cite = _enum(ctx, RAM_CONSTANTS,
                            ("UNUSED_SCRIPT_FLAG_0", "UNUSED_SCRIPT_FLAG_1", "SCRIPT_RUNNING", "RUN_DEFERRED_SCRIPT"))
    movement, move_cite = _literal(ctx, RAM_CONSTANTS, "SCRIPTED_MOVEMENT_STATE_F")
    disconnected, serial_cite = _literal(ctx, "constants/serial_constants.asm", "CONNECTION_NOT_ESTABLISHED")
    link_cite = _cite(ctx, "constants/serial_constants.asm", "const_def\nconst LINK_NULL\nconst LINK_TIMECAPSULE")
    script_end = _cite(ctx, "engine/overworld/scripting.asm", """.resume
xor a
ld [wScriptRunning], a
ld a, SCRIPT_OFF
ld [wScriptMode], a
ld hl, wScriptFlags
res UNUSED_SCRIPT_FLAG_0, [hl]
call StopScript
ret""")
    script_stack = _cite(ctx, "engine/overworld/scripting.asm",
                         "Script_endall:\nxor a\nld [wScriptStackSize], a\nld [wScriptRunning], a")
    script_dispatch = _cite(ctx, "engine/overworld/scripting.asm",
                            "StopScript:\nld hl, wScriptFlags\nres SCRIPT_RUNNING, [hl]\nret")
    script_wait = _cite(ctx, "engine/overworld/scripting.asm",
                        "WaitScript:\ncall StopScript\nld hl, wScriptDelay")
    movement_cite = _cite(ctx, "engine/overworld/scripting.asm",
                          "WaitScriptMovement:\ncall StopScript\nld hl, wStateFlags\nbit SCRIPTED_MOVEMENT_STATE_F, [hl]")
    battle_cite = _cite(ctx, "engine/battle/core.asm",
                        "call BattleEnd_HandleRoamMons\nxor a\nld [wLowHealthAlarm], a\nld [wBattleMode], a\nld [wBattleType], a")
    joy_cite = _cite(ctx, "home/joypad.asm", """ld a, [wJoypadDisable]
and (1 << JOYPAD_DISABLE_MON_FAINT_F) | (1 << JOYPAD_DISABLE_SGB_TRANSFER_F) | (1 << 4)
ret nz
ld a, [wGameLogicPaused]
and a
ret nz""")
    input_cite = _cite(ctx, "home/joypad.asm", """StopAutoInput::
xor a
ld [wAutoInputBank], a
ld [wAutoInputAddress], a
ld [wAutoInputAddress + 1], a
ld [wAutoInputLength], a
ld [wInputType], a
ret""")
    saved_cite = _cite(ctx, "engine/menus/save.asm", "ld a, $1\nld [wSavedAtLeastOnce], a\nret")
    erase_cite = _cite(ctx, "engine/menus/save.asm", """ErasePreviousSave:
call EraseBoxes
call EraseHallOfFame
call EraseLinkBattleStats
call EraseMysteryGift""")
    save_evidence = [saved_cite, erase_cite,
                     _cite(ctx, "engine/menus/save.asm", ".erase\ncall ErasePreviousSave\n.ok\nand a\nret")]
    if ctx.title == "crystal":
        save_evidence.append(_cite(ctx, "engine/menus/save.asm", """HallOfFame_InitSaveIfNeeded:
ld a, [wSavedAtLeastOnce]
and a
ret nz
call ErasePreviousSave
ret"""))
    unsaved_cite = _cite(ctx, "engine/menus/intro_menu.asm", "xor a\nld [wCurBox], a\nld [wSavedAtLeastOnce], a")
    rows = [
        ("wMapStatus", 255, map_status["MAPSTATUS_HANDLE"], "ordinary map handler", [map_cite]),
        ("wMapEventStatus", 255, events["MAPEVENTS_ON"], "map events enabled; not a menu detector", [event_cite]),
        ("wScriptRunning", 255, 0, "no pending player event", [script_end]),
        ("wScriptMode", 255, scripts["SCRIPT_OFF"], "reject WAIT and WAIT_MOVEMENT even when dispatch bit is clear", [script_cite, script_end, script_wait]),
        ("wScriptFlags", (1 << flags["SCRIPT_RUNNING"]) | (1 << flags["RUN_DEFERRED_SCRIPT"]), 0,
         "reject running and deferred dispatch; availability remains unmeasured", [flag_cite, script_dispatch]),
        ("wScriptStackSize", 255, 0, "conservative rejection of nested script state", [script_stack]),
        ("wJoypadDisable", 255, 0, "strict zero is stronger than the engine disable mask", [joy_cite]),
        ("wGameLogicPaused", 255, 0, "reject paused game/save logic", [joy_cite]),
        ("wInputType", 255, 0, "normal input only; no automated stream", [input_cite]),
        ("wBattleMode", 255, 0, "overworld battle-mode value; not an ownership proof alone", [battle_cite]),
        ("wStateFlags", 1 << movement, 0, "reject scripted movement", [move_cite, movement_cite]),
        ("hMapEntryMethod", 255, 0, "reject map entry lifecycle", [
            _cite(ctx, EVENTS, "xor a\nldh [hMapEntryMethod], a\nld a, MAPSTATUS_HANDLE\nld [wMapStatus], a\nret")]),
        ("wLinkMode", 255, 0, "LINK_NULL; host serial/trade ownership must also be absent", [link_cite]),
        ("hSerialConnectionStatus", 255, disconnected, "disconnected serial status", [serial_cite]),
        ("wSavedAtLeastOnce", 255, 1,
         "strict first-save prerequisite for box/memorial writes; not save durability proof",
         [*save_evidence, unsaved_cite]),
    ]
    result = []
    for name, mask, value, reason, evidence in rows:
        if not 0 <= value <= mask <= 255 or value & ~mask:
            raise ValueError(f"invalid source-derived predicate: {name}")
        result.append({**_memory(ctx, name), "operator": "masked_equal", "mask": mask,
                       "value": value, "reason": reason, "semantic_source": evidence,
                       "qualification": "PROPOSED_STRICT_CONJUNCTION"})
    return result


CORE = "engine/battle/core.asm"
TURN_SOURCE = """.skip_iteration
call ParsePlayerAction
jr nz, .loop1
call EnemyTriesToFlee
jr c, .quit
call DetermineMoveOrder
jr c, .false
call Battle_EnemyFirst
jr .proceed
.false
call Battle_PlayerFirst
.proceed
"""
START_TAIL_SOURCE = """call DoBattle
call ExitBattle
pop af
ld [wTimeOfDayPal], a
scf
ret
"""


def _census(ctx, name: str, pattern: str) -> list[tuple[str, int, str]]:
    """Every direct transfer to `name` in the pinned assembly tree."""
    census = subprocess.run(["git", "-C", str(ctx.source_dir), "grep", "-l", "-z", "-F", name, "--", "*.asm"],
                            capture_output=True, check=False)
    if census.returncode != 0:
        raise ValueError(f"{ctx.title}: cannot enumerate {name} source references")
    regex = re.compile(pattern)
    return [(rel, line_no, line) for rel in sorted(census.stdout.decode("utf-8").rstrip("\0").split("\0"))
            for line_no, line in _code(ctx.read_source(rel)) if regex.fullmatch(line)]


def _battle_hold(ctx) -> dict:
    """O-30 in-battle faint site (docs/gen2/reviews/INBATTLE_FAINT_FACTS_2026-09-23.md §2): before
    `call DetermineMoveOrder` in BattleTurn, the player's action committed. Held on the StartBattle ->
    DoBattle -> (jp) BattleTurn main thread: [SP] is StartBattle's return from `call DoBattle`."""
    turns = _census(ctx, "BattleTurn", r"(?:call|jp|jr) (?:\w+, )?BattleTurn")
    if [line for _, _, line in turns] != ["jp BattleTurn"] or turns[0][0] != CORE:
        raise ValueError(f"{ctx.title}: BattleTurn entry missing/ambiguous: {turns}")
    orders = _census(ctx, "DetermineMoveOrder", r"(?:call|jp|jr|farcall|callfar) (?:\w+, )?DetermineMoveOrder")
    if [line for _, _, line in orders] != ["call DetermineMoveOrder"]:
        raise ValueError(f"{ctx.title}: DetermineMoveOrder caller missing/ambiguous: {orders}")
    turn = _Encoder(ctx, "BattleTurn.skip_iteration")
    turn.call("ParsePlayerAction")
    turn.branch(0x20, "BattleTurn.loop1")
    turn.call("EnemyTriesToFlee")
    turn.branch(0x38, "BattleTurn.quit")
    pc = turn.pc
    turn.call("DetermineMoveOrder")
    turn.branch(0x38, "BattleTurn.false")
    turn.call("Battle_EnemyFirst")
    turn.branch(0x18, "BattleTurn.proceed")
    turn.label("BattleTurn.false")
    turn.call("Battle_PlayerFirst")
    turn.label("BattleTurn.proceed")
    # StartBattle's tail: the one executed `call DoBattle` (Crystal's CallDoBattle is unreferenced).
    start = ctx.symbol("StartBattle")
    tail = bytearray()
    for name in ("DoBattle", "ExitBattle"):
        target = ctx.symbol(name)
        if target.bank != start.bank:
            raise ValueError(f"near call crosses ROM bank: {name}")
        tail.extend(b"\xcd" + _word(target.address))
    tail.extend(b"\xf1\xea" + _word(ctx.symbol("wTimeOfDayPal").address) + b"\x37\xc9")
    base = rom_offset(start.bank, start.address)
    window = ctx.rom[base:rom_offset(start.bank, 0x7FFF) + 1]
    hits = [i for i in range(len(window)) if window.startswith(bytes(tail), i)]
    if len(hits) != 1:
        raise ValueError(f"{ctx.title}: StartBattle tail missing/ambiguous in ROM: {hits}")
    tail_address = start.address + hits[0]
    caller = {"bank": start.bank, "address": tail_address, "rom_offset": rom_offset(start.bank, tail_address),
              "expected_hex": bytes(tail).hex().upper(), "source": _cite(ctx, CORE, START_TAIL_SOURCE),
              "instruction_set": "SM83", "evidence": "SOURCE"}
    link_cite = _cite(ctx, "constants/serial_constants.asm", "const_def\nconst LINK_NULL\nconst LINK_TIMECAPSULE")
    action, action_cite = _enum(ctx, "constants/battle_constants.asm",
                                ("BATTLEPLAYERACTION_USEMOVE", "BATTLEPLAYERACTION_USEITEM", "BATTLEPLAYERACTION_SWITCH"))
    skip = _cite(ctx, "engine/battle/effect_commands.asm",
                 "ld a, [wBattlePlayerAction]\nand a ; BATTLEPLAYERACTION_USEMOVE?\nret nz")
    # Struct fields (battle_struct wBattleMon) have no `name::` line: the pinned .sym (sym_sha256 in
    # the source record) is their evidence.
    targets = {name: {"symbol": name, "bank": ctx.symbol(name).bank, "address": ctx.symbol(name).address,
                      "width": width, "evidence": "SYM"}
               for name, width in (("wBattleMonHP", 2), ("wBattlePlayerAction", 1), ("wCurBattleMon", 1),
                                   ("wBattleMonSpecies", 1), ("wPlayerSubStatus5", 1), ("wBattleType", 1))}
    return {
        "id": "battle-turn-before-determine-move-order", "acceptance": "ALL_REQUIRED_SAME_HELD_EXECUTION",
        "execution_before": {"bank": turn.bank, "pc": pc, "rom_offset": rom_offset(turn.bank, pc),
                             "instruction": "call DetermineMoveOrder", "instruction_offset": pc - turn.start,
                             "source": _cite(ctx, CORE, "call DetermineMoveOrder")},
        "anchors": {"battle_turn": turn.anchor(_cite(ctx, CORE, TURN_SOURCE)), "start_battle_caller": caller},
        "caller_return": tail_address + 3,
        "state_predicates": [{**_memory(ctx, "wLinkMode"), "operator": "masked_equal", "mask": 255, "value": 0,
                              "reason": "LINK_NULL: a write in a link battle desyncs the other Game Boy",
                              "semantic_source": [link_cite], "qualification": "PROPOSED_STRICT_CONJUNCTION"}],
        # The write set (facts doc §2): HP 0 and the action byte LAST; the party mirror in between.
        "write": {"skip_action": action["BATTLEPLAYERACTION_USEITEM"], "sources": [action_cite, skip],
                  "targets": targets},
        # Transform rewrites wBattleMonSpecies to the foe's; the slot is still ours (Gen 1 active_faint_guard).
        "transformed_bit": 3,
        "transformed_source": _cite(ctx, "constants/battle_constants.asm",
                                    "const_def\nconst SUBSTATUS_TOXIC\nconst_skip\nconst_skip\nconst SUBSTATUS_TRANSFORMED"),
    }


CONTEST_DROP_SOURCE = """ld hl, wPartyCount
ld a, 1
ld [hli], a
"""
CONTEST_ABORT_SOURCE = """checkflag ENGINE_BUG_CONTEST_TIMER
iffalse .finish
setflag ENGINE_DAILY_BUG_CONTEST
special ContestReturnMons
"""


def _contest_mask(ctx) -> dict:
    """O-30 ruling (a): ContestDropOffMons masks the party to one mon for the whole Bug-Catching
    Contest; ContestReturnMons restores it. The contest timer flag brackets that window at every
    checkpoint hold (BugContestResultsScript clears it inside the same script that returns the mons,
    WarpToSpawnPoint after Script_AbortBugContest returned them): a death for a masked-out mon waits."""
    names = ("STATUSFLAGS2_ROCKETS_IN_RADIO_TOWER_F", "STATUSFLAGS2_SAFARI_GAME_F", "STATUSFLAGS2_BUG_CONTEST_TIMER_F")
    bits, bit_cite = _enum(ctx, RAM_CONSTANTS, names)
    return {**_memory(ctx, "wStatusFlags2"), "bit": bits["STATUSFLAGS2_BUG_CONTEST_TIMER_F"], "sources": [
        bit_cite,
        _cite(ctx, "data/events/engine_flags.asm", "engine_flag wStatusFlags2, STATUSFLAGS2_BUG_CONTEST_TIMER_F"),
        _cite(ctx, "engine/events/bug_contest/contest_2.asm", CONTEST_DROP_SOURCE),
        _cite(ctx, "engine/events/misc_scripts.asm", CONTEST_ABORT_SOURCE),
    ]}


def build_title(ctx) -> dict:
    if ctx.title not in TITLES:
        raise ValueError(f"unsupported selected title: {ctx.title}")
    anchors, pc, return_pc = _anchors(ctx)
    predicates = _predicates(ctx)
    bottom, top = ctx.symbol("wStackBottom"), ctx.symbol("wStackTop")
    stack_kind, allocation = ("WRAM0", "$100 - 1") if ctx.title == "crystal" else ("WRAMX", "$fc")
    stack_cite = _cite(ctx, "ram/wram.asm",
                       f'SECTION "Stack", {stack_kind}\nwStackBottom::\nds {allocation}\nwStackTop::\nds 1')
    expected_bank = 0 if stack_kind == "WRAM0" else 1
    expected_size = 0xFF if stack_kind == "WRAM0" else 0xFC
    region_min, region_end = (0xC000, 0xD000) if expected_bank == 0 else (0xD000, 0xE000)
    if (bottom.bank != expected_bank or top.bank != expected_bank
            or top.address - bottom.address != expected_size
            or not region_min <= bottom.address < top.address < region_end):
        raise ValueError(f"{ctx.title}: stack allocation/bank differs from source")
    stack_init = _cite(ctx, "home/init.asm", "ld sp, wStackTop")
    wram_register, wram_cite = _literal(ctx, "constants/hardware.inc", "rWBK")
    serial_register, sc_cite = _literal(ctx, "constants/hardware.inc", "rSC")
    serial_bit, sc_bit_cite = _literal(ctx, "constants/hardware.inc", "B_SC_START")
    rom_bank = anchors["ow_player_input"]["bank"]
    if rom_bank != anchors["player_events_caller"]["bank"]:
        raise ValueError("caller and checkpoint ROM banks disagree")
    def caller_stack(value: int) -> dict:
        return {"read_domain": "System Bus", "region": stack_kind, "bank": expected_bank,
                "minimum_sp": bottom.address, "exclusive_stack_end": top.address,
                "required_words": [{"offset_from_sp": 0, "value": value, "endianness": "little"}],
                "required_read_bytes": 2, "must_fit_entire_read": True,
                "source": [stack_cite, stack_init], "search_for_return_address": False}

    def ownership(bank: int) -> dict:
        return {
            "rom_bank_shadow": {**_memory(ctx, "hROMBank"), "equals": bank},
            "mapped_rom_bank": bank, "mapped_rom_bank_must_equal_shadow": True,
            "effective_wram_bank": 1,
            "wram_bank_register": {"address": wram_register, "source": wram_cite,
                                   "binding": "CGB effective bank 1; DMG fixed-bank mapping must be qualified separately"},
            "serial_control": {"address": serial_register, "mask": 1 << serial_bit, "value": 0,
                               "source": [sc_cite, sc_bit_cite]},
            "host": ["admitted exact ROM identity", "unchanged session/reset epoch",
                     "no pending trade or serial-owner lease", "no save, box-load, or staged-writer owner",
                     "synchronous CPU hold before the instruction", "recheck every anchor in ROM and mapped System Bus",
                     "all reads and bank/PC/stack evidence available in the same hold"],
            "cached_frame_acceptance_allowed": False,
        }

    hold = _battle_hold(ctx)
    hold["caller_stack"] = caller_stack(hold.pop("caller_return"))
    hold["ownership_requirements"] = ownership(hold["execution_before"]["bank"])
    candidate = {
        "maturity": "SOURCE_CANDIDATE", "runtime_authorized": False,
        "battle_hold": hold,
        "contest_mask": _contest_mask(ctx),
        "primary": {
            "id": "ow-player-input-before-check-a-press", "acceptance": "ALL_REQUIRED_SAME_HELD_EXECUTION",
            "execution_before": {"bank": rom_bank, "pc": pc, "rom_offset": rom_offset(rom_bank, pc),
                                 "instruction": "call CheckAPressOW", "instruction_offset": pc - anchors["ow_player_input"]["address"],
                                 "source": _cite(ctx, EVENTS, "call CheckAPressOW")},
            "anchors": anchors,
            "caller_stack": caller_stack(return_pc),
            "state_predicates": predicates,
            "ownership_requirements": ownership(rom_bank),
        },
        "irq_anchor": {"status": "UNAVAILABLE", "reason": "No generated IRQ anchor proof in this pack; never substitute Gen 1 DelayFrame offsets or stack words."},
        "physical": {"status": "OPEN", "liveness": "UNMEASURED", "negative_controls": "UNRUN",
                     "required_controls": ["idle reacquisition", "textbox", "START and nested menus", "battle/evolution/whiteout",
                                           "warp/Continue", "Elm scene and script waits", "ice/automated/scripted movement",
                                           "deferred script/phone", "Cable Club/trade", "save/box-load/overwrite",
                                           "reset/state-load/ROM-change", "corrupt anchor/caller/bank/unreadable predicate"]},
    }
    return {"schema": SCHEMA, "generator": "tools/gen_gen2_write_checkpoint.py",
            "source": ctx.source_record(), "titles": {ctx.title: candidate}}


def render(value: dict) -> str:
    return json.dumps(value, sort_keys=True, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        # Validate every title before changing any pack.
        outputs = {ROOT / "data" / "games" / f"gen2_{title}" / "write_checkpoint.json":
                   render(build_title(load_context(title, root=ROOT))) for title in TITLES}
        stale = [path for path, text in outputs.items()
                 if not path.is_file() or path.read_bytes() != text.encode("utf-8")]
        if args.check:
            for path in stale:
                print(f"stale: {path.relative_to(ROOT)}", file=sys.stderr)
            return int(bool(stale))
        for path in stale:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(outputs[path], encoding="utf-8", newline="\n")
        print(f"Gen 2 checkpoint candidates current for {', '.join(TITLES)}; PHYSICAL OPEN")
        return 0
    except (OSError, ValueError) as exc:
        print(f"checkpoint generation refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
