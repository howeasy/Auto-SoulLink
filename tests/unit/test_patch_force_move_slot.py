"""C5-FMS-FIX: the companion's FORCE_MOVE_SLOT driver must use the real gBattleCommunication states.

`HandleTurnActionSelectionState` switches on `gBattleCommunication[battler]` through a 7-entry jump
table at 0x0801409C that is byte-identical in FireRed and Radical Red, so pret's 0-based enum holds:
0 BEFORE_ACTION_CHOSEN (emit ChooseAction), 1 WAIT_ACTION_CHOSEN (action menu parked),
2 WAIT_ACTION_CASE_CHOSEN (move menu parked), 3 WAIT_ACTION_CONFIRMED_STANDBY (emit the standby /
stop-bounce message, then ++), 4 WAIT_ACTION_CONFIRMED (counted as done).

The old driver used a 1-based reading: it gated on comm 2 (action menu) / 3 (move menu) and wrote 4.
It also left its own routine in `gBattlerControllerFuncs[b]` after disarming, and the engine never
reassigns that slot (only controllers do), so the player's controller went dead.

What this catches: the gate and write values and the controller hand-back, read from the C source
and resolved through its #defines; the enum and case bodies, read from pret and the ROM bytes when
those are on the machine. What it can't catch: runtime behaviour. There is no C harness, so the
swap's frame ordering, CFRU's controller detours and the on-screen menus need a live gate
(lua/tests/test_live_forcemove.lua) on a REBUILT companion ROM.
"""
from __future__ import annotations

import pathlib
import re
import struct

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
HANDLERS_C = REPO / "patch" / "src" / "handlers.c"

# pret pokefirered battle_main.c enum (0-based), proven for RR by the byte-identical jump table.
WAIT_ACTION_CHOSEN, WAIT_ACTION_CASE_CHOSEN, WAIT_ACTION_CONFIRMED_STANDBY = 1, 2, 3
HANDLE_INPUT_CHOOSE_ACTION = 0x0802E439   # FR sym 0x0802E438 (RR detours the body to CFRU)
HANDLE_INPUT_CHOOSE_MOVE = 0x0802EA11      # FR sym 0x0802EA10 (RR: thunk to CFRU 0x090AB8B8)
PLAYER_BUFFER_EXEC_COMPLETED = 0x0802E33D  # FR sym 0x0802E33C


def _src() -> str:
    return HANDLERS_C.read_text(encoding="utf-8")


def _defines(src: str) -> dict[str, int]:
    out = {}
    for name, val in re.findall(r"^#define\s+(\w+)\s+(?:\(\(.*\)\s*)?(0x[0-9A-Fa-f]+|\d+)u?\)?\s*(?:/\*.*)?$", src, re.M):
        out[name] = int(val, 0)
    return out


def _body(src: str, fn: str) -> str:
    m = re.search(r"static void " + fn + r"\(void\)\s*\{", src)
    assert m, fn
    depth, i = 1, m.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return src[m.end():i - 1]


def _val(tok: str, defs: dict[str, int]) -> int:
    tok = tok.rstrip("u")
    return int(tok, 0) if tok[0].isdigit() else defs[tok]


def test_swap_gate_matches_the_parked_menus():
    src = _src()
    defs = _defines(src)
    cond = re.search(r"if\s*\((.*?)\)\s*\{\s*\*cf\s*=", _body(src, "drive_force_move"), re.S).group(1)
    clauses, depth, start = [], 0, 0          # split on top-level || only
    for i, ch in enumerate(cond):
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if depth == 0 and cond.startswith("||", i):
            clauses.append(cond[start:i])
            start = i + 2
    clauses.append(cond[start:])
    gate = set()
    for clause in clauses:
        comms = re.findall(r"comm\s*==\s*(\w+)", clause)
        ctrls = re.findall(r"\*cf\s*==\s*(\w+)", clause)
        assert len(comms) == 1 and ctrls, clause
        gate |= {(_val(comms[0], defs), _val(c, defs)) for c in ctrls}
    assert gate == {(WAIT_ACTION_CHOSEN, HANDLE_INPUT_CHOOSE_ACTION),
                    (WAIT_ACTION_CASE_CHOSEN, HANDLE_INPUT_CHOOSE_MOVE)}


def test_forced_choice_lands_in_standby_and_hands_the_controller_back():
    src = _src()
    defs = _defines(src)
    body = _body(src, "slink_force_controller")
    writes = re.findall(r"R8\(gBattleCommunication \+ b\)\s*=\s*(\w+);", body)
    assert [_val(w, defs) for w in writes] == [WAIT_ACTION_CONFIRMED_STANDBY]
    calls = [c for c in re.findall(r"(\w+)\(\);", body) if defs.get(c) == PLAYER_BUFFER_EXEC_COMPLETED]
    assert calls, "controller slot never handed back to PlayerBufferRunCommand"
    # the hand-back comes after the comm write: it is the commit, as on a real menu pick
    assert body.index(calls[0] + "();") > body.index("gBattleCommunication + b")


def _pret_battle_main() -> pathlib.Path | None:
    for d in (REPO, *REPO.parents):
        p = d / ".cache" / "pret" / "pokefirered" / "src" / "battle_main.c"
        if p.exists():
            return p
    return None


def test_pret_enum_matches_the_pins():
    p = _pret_battle_main()
    if p is None:
        pytest.skip("pret pokefirered not cached (E:/Google Drive/SLink/.cache/pret/pokefirered)")
    enum = re.search(r"enum\s*\{\s*(STATE_BEFORE_ACTION_CHOSEN,.*?)\};", p.read_text(), re.S).group(1)
    names = [n.strip() for n in enum.split(",") if n.strip()]
    assert names.index("STATE_WAIT_ACTION_CHOSEN") == WAIT_ACTION_CHOSEN
    assert names.index("STATE_WAIT_ACTION_CASE_CHOSEN") == WAIT_ACTION_CASE_CHOSEN
    assert names.index("STATE_WAIT_ACTION_CONFIRMED_STANDBY") == WAIT_ACTION_CONFIRMED_STANDBY


def test_rr_bytes_match_the_pins():
    import sys
    sys.path.insert(0, str(REPO / "tools" / "research"))
    import rr_save_callers as r
    try:
        rr, fr = (r.ROMS[k][0].read_bytes() for k in ("clean", "fr"))
    except OSError:
        pytest.skip("Radical Red / FireRed ROMs not on this machine")
    o = lambda a: a - 0x08000000  # noqa: E731
    table = struct.unpack_from("<7I", rr, o(0x0801409C))
    assert table == struct.unpack_from("<7I", fr, o(0x0801409C))
    standby, confirmed = table[WAIT_ACTION_CONFIRMED_STANDBY], table[WAIT_ACTION_CONFIRMED_STANDBY + 1]
    assert rr[o(standby):o(confirmed)] == fr[o(standby):o(confirmed)]
    # case [3] calls BtlController_EmitLinkStandbyMsg (0x0800EB54): BL at 0x08014B02
    hi, lo = struct.unpack_from("<2H", rr, o(0x08014B02))
    off = ((hi & 0x7FF) << 12 | (lo & 0x7FF) << 1)
    off -= (1 << 23) if off & (1 << 22) else 0
    assert 0x08014B02 + 4 + off == 0x0800EB54 and standby <= 0x08014B02 < confirmed
    # the controller addresses resolve to the FR functions they are named for
    syms = {int(a, 16): n for a, _, _, n in
            (ln.split() for ln in (REPO / "data/gen3/pret/pokefirered.sym").read_text().splitlines()
             if len(ln.split()) == 4)}
    assert syms[HANDLE_INPUT_CHOOSE_ACTION - 1] == "HandleInputChooseAction"
    assert syms[HANDLE_INPUT_CHOOSE_MOVE - 1] == "HandleInputChooseMove"
    assert syms[PLAYER_BUFFER_EXEC_COMPLETED - 1] == "PlayerBufferExecCompleted"
