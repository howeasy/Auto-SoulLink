"""The companion-patch opcode gates, as pytest.

`lua/tests/test_live_*.lua` and `test_mailbox_*.lua` are one headless BizHawk gate per
opcode/feature — collectively the patch's executable spec.  They used to be launched by
hand, one EmuHawk invocation at a time, which is why they rotted quietly.  This runs the
whole set with one command:

    SLINK_LIVE=1 pytest tests/live -q                 # everything
    SLINK_LIVE=1 pytest tests/live -q -k memorialize  # one gate

Each gate is skipped (never hung) when its prerequisite is missing.  That matters for the
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

# Gates that need a live SLink server or a second instance rather than just the emulator —
# those are tests/e2e/test_duo.py's job.
NOT_STANDALONE = {"test_live_enemyparty_route.lua", "test_live_explode_route.lua",
                  "test_live_msgbox_route.lua"}
# Negative controls: they assert the patch is ABSENT, so they need the unpatched ROM.
CLEAN_ROM_GATES = {"test_mailbox_absent.lua"}


def _gates():
    names = sorted(f for f in os.listdir(GATE_DIR)
                   if (f.startswith("test_live_") or f.startswith("test_mailbox_"))
                   and f.endswith(".lua") and f not in NOT_STANDALONE)
    return names


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
