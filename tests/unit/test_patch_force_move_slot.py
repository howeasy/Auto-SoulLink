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
PLAYER_BUFFER_RUN_COMMAND = 0x0802E3B5     # FR sym 0x0802E3B4: idle dispatcher, NOT a menu
CFRU_CHOOSE_ACTION = 0x090A9EA1            # RR: detour target of 0x0802E438 / post-L-window spelling
BATTLE_TYPE_LINK = 0x02


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


def _gate(src: str):
    """drive_force_move's `parked` expression as a Python predicate (comm, ctrl, type_flags) -> bool.
    Evaluated, not pattern-matched: the C is translated token-for-token and run on a truth table."""
    defs = _defines(src)
    expr = re.search(r"u8 parked =(.*?);", _body(src, "drive_force_move"), re.S).group(1)
    expr = re.sub(r"\b(0x[0-9A-Fa-f]+|\d+)u\b", r"\1", expr)
    expr = expr.replace("&&", " and ").replace("||", " or ").replace("!(", " not (")
    code = compile(" ".join(expr.split()), "parked", "eval")

    def parked(comm: int, ctrl: int, type_flags: int = 0) -> bool:
        ns = dict(defs, comm=comm, c=ctrl,
                  R32=lambda a: type_flags if a == defs["RV_BATTLE_TYPE"] else 0)
        return bool(eval(code, {}, ns))
    return parked


def test_swap_gate_matches_the_parked_menus():
    parked = _gate(_src())
    ctrls = (HANDLE_INPUT_CHOOSE_ACTION, CFRU_CHOOSE_ACTION, HANDLE_INPUT_CHOOSE_MOVE,
             PLAYER_BUFFER_RUN_COMMAND, 0)
    got = {(comm, ctrl) for comm in range(7) for ctrl in ctrls if parked(comm, ctrl)}
    want = {(WAIT_ACTION_CHOSEN, HANDLE_INPUT_CHOOSE_ACTION),
            (WAIT_ACTION_CHOSEN, CFRU_CHOOSE_ACTION),
            (WAIT_ACTION_CASE_CHOSEN, HANDLE_INPUT_CHOOSE_MOVE)}
    fmt = lambda xs: sorted((c, hex(k)) for c, k in xs)  # noqa: E731
    assert got == want, f"extra {fmt(got - want)}, missing {fmt(want - got)}"


def test_swap_gate_refuses_link_battles():
    parked = _gate(_src())
    for comm, ctrl in ((1, HANDLE_INPUT_CHOOSE_ACTION), (1, CFRU_CHOOSE_ACTION), (2, HANDLE_INPUT_CHOOSE_MOVE)):
        assert parked(comm, ctrl, 0)
        assert not parked(comm, ctrl, BATTLE_TYPE_LINK), (comm, hex(ctrl))
        assert parked(comm, ctrl, 1 << 24)   # CFRU bit-24 mode is not link


def test_zero_pp_slot_is_refused_before_the_swap():
    body = _body(_src(), "drive_force_move")
    branch = body[body.index("if (parked)"):]
    pp = re.search(r"R8\(gBattleMons \+ b \* BATTLE_MON_SIZE \+ 0x24 \+ AM->move_pos\) == 0\)", branch)
    assert pp, "no pp[move_pos] == 0 refusal in the parked branch"
    refusal = branch[pp.end():branch.index("*cf =")]
    assert "AM->armed = 0" in refusal and "ST_FAIL" in refusal and "return;" in refusal


def test_staging_bounds_every_arg():
    src = _src()
    case = src[src.index("case OP_FORCE_MOVE_SLOT:"):]
    guard = case[:case.index("{ ack(ST_FAIL")]
    assert sorted(re.findall(r"MB->args\[(\d)\] > 3", guard)) == ["0", "1", "2"], guard


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
    pytest.importorskip("numpy", reason="tools/research needs numpy (not a runtime requirement)")
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
    assert syms[PLAYER_BUFFER_RUN_COMMAND - 1] == "PlayerBufferRunCommand"


def test_rr_controller_detours_match_the_pins():
    """The second action-menu spelling, and where the hand-back really puts the slot in RR."""
    import sys
    pytest.importorskip("numpy", reason="tools/research needs numpy (not a runtime requirement)")
    sys.path.insert(0, str(REPO / "tools" / "research"))
    import rr_battle_tuple as t
    try:
        rr = t.rsc.ROMS["clean"][0].read_bytes()
    except OSError:
        pytest.skip("Radical Red ROM not on this machine")
    # HandleInputChooseAction is detoured to the CFRU body; the L-window close stores it directly
    assert t.detour(rr, 0x0802E438) == CFRU_CHOOSE_ACTION
    assert t.ldr_value(rr, 0x090A9E76) == CFRU_CHOOSE_ACTION
    # CFRU's own sprite callbacks compare the slot against BOTH spellings
    assert {t.ldr_value(rr, a) for a in (0x09068D6C, 0x09069832)} == {HANDLE_INPUT_CHOOSE_ACTION}
    assert {t.ldr_value(rr, a) for a in (0x09068D72, 0x09069838)} == {CFRU_CHOOSE_ACTION}
    # PlayerBufferExecCompleted: LDR@0x0802E34A; bx -> 0x0904459A, which stores RunCommand, or
    # 0x090ACD8D in the CFRU bit-24 mode, into the slot (str r1,[r0] @0x090445BA), then returns
    assert t.detour(rr, 0x0802E34A) == 0x0904459B
    assert t.ldr_value(rr, 0x090445B2) == 0x090ACD8D
    assert t.ldr_value(rr, 0x090445B6) == PLAYER_BUFFER_RUN_COMMAND
    assert struct.unpack_from("<H", rr, 0x090445BA - 0x08000000)[0] == 0x6001   # str r1, [r0]
    assert t.ldr_value(rr, 0x090445BC) == 0x0802E34F


# Every CODE/DATA pin of the companion ROM hash. A rebuild must re-pin them together (docs listed in
# ADDRESSES.md's rebuild note are records, not checked here). The reference pair is engine_signals.json.
# The Radical Red companion's identity has ONE data source, the "rr" row of patch/dist/companion_pins.json (written by
# patch/tools/build.py; a release stamp changes the exact hash every time). These files used to carry its md5/sha1 as text; they now
# read the row (or cite its canonical sha1), so a stamp rewrites one file.
COMPANION_READERS = (
    "server/patcher.py",
    "tools/gen_gen3_profile.py",
    "tools/gen_gen3_write_checkpoint.py",
    "tools/pin_gen3_site.py",
    "tools/research/rr_save_callers.py",
    "tests/unit/test_gen3_profile.py",
)
COMPANION_CITERS = ("data/games/gen3_rr/profile.json", "data/games/gen3_rr/write_checkpoint.json")


def test_companion_hash_pins_agree():
    import json
    row = json.loads((REPO / "patch/dist/companion_pins.json").read_text(encoding="utf-8"))["pins"]["rr"]
    sig = json.loads((REPO / "data/games/gen3_rr/engine_signals.json").read_text(encoding="utf-8"))
    comp = sig["titles"]["radical_red"]["artifacts"]["companion"]
    # the generated admission row names the cartridge exactly as the row does
    assert (comp["rom_md5"], comp["rom_sha1"]) == (row["patched_md5"], row["rom_sha1"])
    # the generated citations name its canonical identity (the version field zeroed), which a stamp does not move
    stale = [f for f in COMPANION_CITERS if row["canonical_sha1"] not in (REPO / f).read_text(encoding="utf-8")]
    assert not stale, f"canonical sha1 {row['canonical_sha1']} missing from {stale}"
    # and nothing else carries the exact hashes as text
    literal = [f for f in COMPANION_READERS
               if row["patched_md5"] in (REPO / f).read_text(encoding="utf-8")
               or row["rom_sha1"] in (REPO / f).read_text(encoding="utf-8")]
    assert not literal, f"companion md5/sha1 hard-coded in {literal}; read patch/dist/companion_pins.json (tools/rr_companion.py)"
