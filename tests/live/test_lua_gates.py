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
  DEFERRED  owner-deferred post-RC feature (docs/gen3/TODO.md) — reported as a skip with the reason;
  GAP       needs something neither native.lua nor the raw poster provides — a skip naming it.
Deferred and gap gates still use the old binding and are never run here.

    SLINK_LIVE=1 pytest tests/live/test_lua_gates.py -q                 # everything
    SLINK_LIVE=1 pytest tests/live/test_lua_gates.py -q -k playse       # one gate

Each gate is skipped (never hung) when its prerequisite is missing. That matters for the
savestate in particular: BizHawk stops on a modal version dialog when handed a state from
another release, so `savestate.load` on a stale file blocks forever rather than erroring.
tools/mkstates.py owns the freshness check; see it for how to rebuild.
"""
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

_GHOST = "peer ghost deferred post-RC (owner 2026-09-22, docs/gen3/TODO.md): no lua/gen3/ghost.lua"
_TEXT = "native text disabled for the RC (owner 2026-09-23, docs/gen3/TODO.md): no message opcodes"
DEFERRED = {
    "test_live_ghostavatar.lua": _GHOST,
    "test_live_ghostbattle.lua": _GHOST,
    "test_live_ghostdoor.lua": _GHOST,
    "test_live_ghostlayer.lua": _GHOST,
    "test_live_ghostorphan.lua": _GHOST,
    "test_live_ghostreceiver.lua": _GHOST,
    "test_live_ghostscript.lua": _GHOST + "; also OP_SHOW_MESSAGE (native text)",
    "test_live_ghostshow.lua": _GHOST,
    "test_live_ghoststutter.lua": _GHOST,
    "test_live_ghosttint.lua": _GHOST,
    "test_live_ghostwarp.lua": _GHOST,
    "test_live_peerinteract.lua": _GHOST + " (OP_GHOST_SPAWN talk-to-ghost)",
    "test_live_spawnnpc.lua": _GHOST + " (OP_SPAWN/DESPAWN_PEER_NPC, the ghost's engine NPC)",
    "test_live_battlemsg.lua": _TEXT + " (OP_SHOW_BATTLE_MESSAGE)",
    "test_live_message.lua": _TEXT + " (OP_SHOW_MESSAGE; also OP_PLAY_FANFARE, not in native.lua)",
    "test_live_msgboxdismiss.lua": _TEXT + " (OP_SHOW_MESSAGE)",
    "test_live_msgbox_route.lua": _TEXT + " (OP_SHOW_MESSAGE)",
}
GAP = {}   # C5-4b ported every former gap onto the raw poster
UNPORTED = {**{g: "DEFERRED: " + r for g, r in DEFERRED.items()},
            **{g: "GAP: " + r for g, r in GAP.items()}}


def _gates():
    return sorted(PORTED)


def gate_files():
    """Every opcode gate file on disk (the manifest must cover exactly these)."""
    return sorted(f for f in os.listdir(GATE_DIR)
                  if (f.startswith("test_live_") or f.startswith("test_mailbox_"))
                  and f.endswith(".lua"))


def _required_state(gate):
    """The savestate a gate loads, or None if it runs from a cold boot."""
    with open(os.path.join(GATE_DIR, gate), encoding="utf-8", errors="replace") as f:
        m = STATE_RE.search(f.read())
    return m.group(1) if m else None


@pytest.fixture(scope="session")
def emu_version():
    if not os.path.exists(mkstates.EMUHAWK):
        pytest.skip(f"EmuHawk not found at {mkstates.EMUHAWK}")
    if not os.path.exists(ROM):
        pytest.skip("patched ROM missing — python patch/tools/build.py")
    return mkstates.emuhawk_version()


@pytest.fixture(scope="session")
def clean_rom():
    if not os.path.exists(CLEAN_SRC):
        pytest.skip(f"unpatched ROM missing: {os.path.basename(CLEAN_SRC)}")
    dst = os.path.join(REPO, CLEAN_REL)
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(CLEAN_SRC):
        shutil.copyfile(CLEAN_SRC, dst)
    return CLEAN_REL


@pytest.mark.parametrize("gate", _gates())
def test_gate(gate, emu_version, request):
    need = _required_state(gate)
    if need:
        path = os.path.join(mkstates.STATE_DIR, need)
        stale, why = mkstates.is_stale(path, emu_version)
        if stale:
            pytest.skip(f"{need} {why} — rebuild with `python tools/mkstates.py`")
    rom = request.getfixturevalue("clean_rom") if gate in CLEAN_ROM_GATES else ROM_REL
    passed, result_path, text = run_gate(f"lua/tests/{gate}", rom=rom, timeout=300, quiet=True)
    assert passed, (f"{gate} did not report PASS\n"
                    f"result: {result_path}\n{text[-2000:]}")


@pytest.mark.parametrize("gate", sorted(UNPORTED))
def test_unported_gate(gate):
    pytest.skip(UNPORTED[gate])
