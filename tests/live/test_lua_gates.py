"""The companion-patch opcode gates, as pytest.

`lua/tests/test_live_*.lua` and `test_mailbox_*.lua` are one headless BizHawk gate per
opcode/feature — collectively the patch's executable spec. P5 (docs/gen3/PLAN.md §14, card C5-4)
binds them to the NEW Gen 3 client's native layer through `lua/tests/gen3_gatelib.lua`
(`lua/gen3/native.lua` over the real writes/safety sink); none of the ported gates loads the old
client (`lua/mailbox.lua`, `lua/memory_gba.lua`, `lua/clients/gen3_frlge_client.lua`). Patch ops
the client never sends go through gen3_gatelib's test-only raw poster (card C5-4b), never through
new native.lua surface.

Every gate file is in exactly one of three lists (tests/unit/test_gen3_gatelib.py enforces it):
  PORTED    runs live through gen3_gatelib;
  DEFERRED  owner-deferred post-RC feature (docs/gen3/TODO.md). Also bound to gen3_gatelib (C5-4c),
            but skipped with the reason unless SLINK_GATES_DEFERRED=1 opts in;
  GAP       needs something neither native.lua nor the raw poster provides — a skip naming it.
Gates that tested the old client's own driver live in lua/tests/archive/gen3_old_client/ (see its
README); this file only ever scans lua/tests/ itself, so they are never loaded.

    SLINK_LIVE=1 pytest tests/live/test_lua_gates.py -q                           # the RC set
    SLINK_LIVE=1 pytest tests/live/test_lua_gates.py -q -k playse                 # one gate
    SLINK_LIVE=1 SLINK_GATES_DEFERRED=1 pytest tests/live/test_lua_gates.py -q    # + deferred

A gate is never launched (never hung) when its prerequisite is missing: EmuHawk, the ROM, or a
fresh savestate (BizHawk stops on a modal version dialog when handed a state from another
release, so `savestate.load` on a stale file blocks forever; tools/mkstates.py owns the freshness
check). Under SLINK_LIVE=1 a PORTED gate with a missing prerequisite FAILS with the reason, and
the module fails if zero ported gates executed; deferred gates skip.
"""
import functools
import os
import re
import shutil
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import mkstates  # noqa: E402
from run_gate import run_gate  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live opcode gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

GATE_DIR = os.path.join(REPO, "lua", "tests")
ROM_REL = "patch/build/slink_RR.gba"
ROM = os.path.join(REPO, ROM_REL)
# The clean ROM lives at the repo root under a name with spaces, which BizHawk's CLI parser
# splits; stage a space-free copy next to the patched build.
CLEAN_SRC = os.path.join(REPO, "Pokemon - Radical Red.gba")
CLEAN_REL = "patch/build/rr_clean.gba"
STATE_RE = re.compile(r"(slink_[a-z0-9]+\.State)")

# Ported onto lua/tests/gen3_gatelib.lua.
PORTED = (
    "test_live_boxsync.lua",           # raw OP_DEPOSIT_MON / OP_WITHDRAW_MON
    "test_live_calctoggle.lua",        # native:config{battle_calc}
    "test_live_choices.lua",           # native:show_choices
    "test_live_choices_guards.lua",    # raw OP_SHOW_CHOICES over malformed MENU_BUF (patch guards)
    "test_live_choosepartymon.lua",    # native:choose_mon
    "test_live_createmon.lua",         # raw OP_CREATE_MON
    "test_live_enemyparty.lua",        # raw OP_CREATE_MON (enemy party)
    "test_live_enemyparty_route.lua",  # native:transfer("enemy")  (savestate-free, standalone)
    "test_live_events.lua",            # gatelib EvRing drain (faint/outcome producers)
    "test_live_ewramtail.lua",         # read-only watch + paint instrumentation
    "test_live_explode_route.lua",     # raw OP_FORCE_MOVE_SLOT (C5-FMS-FIX semantics)
    "test_live_forcemove.lua",         # raw OP_FORCE_MOVE_SLOT (C5-FMS-FIX semantics)
    "test_live_givemon.lua",           # raw OP_CREATE_MON (bump = GIVE_MON)
    "test_live_infoscreen.lua",        # raw SlinkInfo staging + OP_SHOW_INFO (incl. guards)
    "test_live_memorialize.lua",       # raw OP_MEMORIALIZE (+ OP_CREATE_MON filler)
    "test_live_menu.lua",              # native:show_menu
    "test_live_partyevents.lua",       # gatelib EvRing drain (party producers)
    "test_live_pcnpc.lua",             # native:config{pc_trade_npc} + service() trade_request
    "test_live_playse.lua",            # native:play_sound
    "test_live_setpartymon.lua",       # native:transfer("party")
    "test_live_soullinkmenu.lua",      # native:link_panel staging + the START-menu hook
    "test_live_startmenu.lua",         # read-only START-menu recon
    "test_live_tradescene.lua",        # native:transfer("enemy") then transfer("scene")
    "test_mailbox_absent.lua",         # negative control: native absent on the clean ROM
    "test_mailbox_battle.lua",         # raw OP_FORCE_FAINT / OP_FORCE_MOVE / unknown opcode
    "test_mailbox_ping.lua",           # raw OP_PING + beacon stability
)
# Negative controls: they assert the patch is ABSENT, so they need the unpatched ROM.
CLEAN_ROM_GATES = {"test_mailbox_absent.lua"}

_GHOST = "peer ghost deferred post-RC (owner 2026-09-22, docs/gen3/TODO.md)"
_TEXT = "native text disabled for the RC (owner 2026-09-23, docs/gen3/TODO.md)"
DEFERRED_OPT_IN = "SLINK_GATES_DEFERRED"
DEFERRED = {
    "test_live_ghostavatar.lua": _GHOST,
    "test_live_ghostbattle.lua": _GHOST,
    "test_live_ghostlayer.lua": _GHOST,
    "test_live_ghostshow.lua": _GHOST,
    "test_live_ghosttint.lua": _GHOST,
    "test_live_ghostwarp.lua": _GHOST,
    "test_live_peerinteract.lua": _GHOST + " (OP_GHOST_SPAWN talk-to-ghost)",
    "test_live_spawnnpc.lua": _GHOST + " (OP_SPAWN/DESPAWN_PEER_NPC, the ghost's engine NPC)",
    "test_live_battlemsg.lua": _TEXT + " (OP_SHOW_BATTLE_MESSAGE)",
    "test_live_message.lua": _TEXT + " (OP_SHOW_MESSAGE; OP_PLAY_FANFARE rides with it)",
    "test_live_msgboxdismiss.lua": _TEXT + " (OP_SHOW_MESSAGE)",
}
GAP = {}   # C5-4b ported every former gap onto the raw poster
UNPORTED = {**{g: "DEFERRED: " + r for g, r in DEFERRED.items()},
            **{g: "GAP: " + r for g, r in GAP.items()}}


def _gates():
    return sorted(PORTED)


def gate_files():
    """Every opcode gate file on disk (the manifest must cover exactly these). lua/tests/ only:
    the archive folder is never listed, so an archived gate can never be run from here."""
    return sorted(f for f in os.listdir(GATE_DIR)
                  if (f.startswith("test_live_") or f.startswith("test_mailbox_"))
                  and f.endswith(".lua"))


def _required_state(gate):
    """The savestate a gate loads, or None if it runs from a cold boot."""
    with open(os.path.join(GATE_DIR, gate), encoding="utf-8", errors="replace") as f:
        m = STATE_RE.search(f.read())
    return m.group(1) if m else None


@functools.cache
def _emu_version():
    return mkstates.emuhawk_version()


def prerequisite_problem(gate):
    """Why `gate` cannot run on this host (EmuHawk, ROM, fresh savestate), or None."""
    if not os.path.exists(mkstates.EMUHAWK):
        return f"EmuHawk not found at {mkstates.EMUHAWK}"
    if gate in CLEAN_ROM_GATES:
        if not os.path.exists(CLEAN_SRC):
            return f"unpatched ROM missing: {os.path.basename(CLEAN_SRC)}"
    elif not os.path.exists(ROM):
        return "patched ROM missing — python patch/tools/build.py"
    need = _required_state(gate)
    if need:
        stale, why = mkstates.is_stale(os.path.join(mkstates.STATE_DIR, need), _emu_version())
        if stale:
            return f"{need} {why} — rebuild with `python tools/mkstates.py`"
    return None


def _clean_rom():
    dst = os.path.join(REPO, CLEAN_REL)
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(CLEAN_SRC):
        shutil.copyfile(CLEAN_SRC, dst)
    return CLEAN_REL


EXECUTED = []   # ported gates that actually launched EmuHawk this session


def _run(gate, strict):
    """Run one gate. strict (a PORTED gate under SLINK_LIVE=1): a missing prerequisite FAILS with its
    reason, so a run in which nothing executed can never read as green (R2 M3). Deferred: skips."""
    problem = prerequisite_problem(gate)
    if problem:
        (pytest.fail if strict else pytest.skip)(f"{gate}: prerequisite missing — {problem}")
    rom = _clean_rom() if gate in CLEAN_ROM_GATES else ROM_REL
    if strict:
        EXECUTED.append(gate)
    passed, result_path, text = run_gate(f"lua/tests/{gate}", rom=rom, timeout=300, quiet=True)
    assert passed, (f"{gate} did not report PASS\n"
                    f"result: {result_path}\n{text[-2000:]}")


def check_executed(selected, executed):
    """Session guard: selected ported gates but none executed is a failure, never a green run."""
    if selected and not executed:
        pytest.fail(f"zero of {selected} selected ported gates executed", pytrace=False)


@pytest.fixture(scope="module", autouse=True)
def _ported_gates_executed(request):
    yield
    selected = sum(1 for i in request.session.items if getattr(i, "originalname", "") == "test_gate")
    tr = request.config.pluginmanager.get_plugin("terminalreporter")
    if tr and selected:
        tr.write_line(f"[test_lua_gates] ported gates executed: {len(EXECUTED)}/{selected}")
    check_executed(selected, len(EXECUTED))


@pytest.mark.parametrize("gate", _gates())
def test_gate(gate):
    _run(gate, strict=True)


@pytest.mark.parametrize("gate", sorted(DEFERRED))
def test_deferred_gate(gate):
    if os.environ.get(DEFERRED_OPT_IN) != "1":
        pytest.skip(f"DEFERRED: {DEFERRED[gate]} — set {DEFERRED_OPT_IN}=1 to run it")
    _run(gate, strict=False)


@pytest.mark.parametrize("gate", sorted(GAP))
def test_gap_gate(gate):
    pytest.skip("GAP: " + GAP[gate])
