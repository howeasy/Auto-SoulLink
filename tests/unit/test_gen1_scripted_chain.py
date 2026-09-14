"""Route chaining in the scripted New Game bootstrap; BizHawk globals stubbed under lupa.

The bootstrap is a `--lua=` top-level script, so every BizHawk global it touches
(emu, memory, joypad, gameinfo, os.getenv, SLINK_RUNTIME_STATUS) is stubbed and
its ROOT is a temp copy holding the real json_codec / point-fields / signature
modules plus a small pret .sym. Route modules are stubs whose step() phases are
scripted from Python. No emulator, no product process.
"""

import json
import shutil
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "lua/tests/gen1_scripted_new_game.lua"
ROOT_FILES = ("lua/json_codec.lua", "lua/tests/gen1_rb_point_fields.lua",
              "lua/tests/gen1_rb_mart_signature.lua")
# pokered.sym (pret 405b624); every symbol route_point() reads.
SYMBOLS = {
    "wCurMap": 0xD35E, "wXCoord": 0xD362, "wYCoord": 0xD361, "wPartyCount": 0xD163,
    "wIsInBattle": 0xD057, "wCurOpponent": 0xD059, "wTopMenuItemY": 0xCC24,
    "wTopMenuItemX": 0xCC25, "wMaxMenuItem": 0xCC28, "wCurrentMenuItem": 0xCC26,
    "wBattleMonMoves": 0xD01C, "wBattleMonPP": 0xD02D, "wTextBoxID": 0xD125,
    "wOaksLabCurScript": 0xD5F0, "wPalletTownCurScript": 0xD5F1, "wJoyIgnore": 0xCD6B,
    "wStatusFlags5": 0xD730, "wBattleResult": 0xCF0B, "wPartyMon1HP": 0xD16C,
    "wEventFlags": 0xD747, "wNumBagItems": 0xD31D, "wBagItems": 0xD31E,
    "wPlayerMoney": 0xD347, "wViridianMartCurScript": 0xD60D,
    "wSimulatedJoypadStatesIndex": 0xCD38, "wSpritePlayerStateData1FacingDirection": 0xC109,
    "wBattleType": 0xD05A, "wNumRunAttempts": 0xD120, "wListMenuID": 0xCF94,
    "wCurItem": 0xCF91, "wItemQuantity": 0xCF96, "wChosenMenuItem": 0xD12D,
    "wMenuExitMethod": 0xD12E, "wListScrollOffset": 0xCC36,
    "wMenuWatchMovingOutOfBounds": 0xCC37, "wFontLoaded": 0xCFC4,
}
STUB_MODULE = """
local NAME=%r
local M={}
function M.new(expected)
    LOG[#LOG+1]={kind="new",module=NAME,expected=expected}
    return {step=function(handshake,status,point,frame)
        LOG[#LOG+1]={kind="step",module=NAME,frame=frame,point=point,handshake=handshake,status=status}
        return IDLE,PHASE(NAME,frame)
    end}
end
return M
"""
PRELUDE = """
LOG={}
IDLE={A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false}
local framecount=0
local function original_advance()
    framecount=framecount+1
    LOG[#LOG+1]={kind="advance",frame=framecount}
end
ORIGINAL_ADVANCE=original_advance
emu={framecount=function() return framecount end,frameadvance=original_advance,
     yield=function() LOG[#LOG+1]={kind="yield"} end}
RAM={}
memory={read_u8=function(addr,domain) return RAM[addr] or 0 end}
JOYPAD={}
joypad={set=function(buttons) JOYPAD[#JOYPAD+1]=buttons end}
gameinfo={getromhash=function() return ROM_SHA1 end}
os.getenv=function(name) return ENV[name] end
STATUS={observation_loop=true,
        host={owner_id=PHYS,held=false,lease_owned=true},
        context={context_generation=GEN,physical_instance=PHYS},
        runtime={connected=true,session_state="admitted",failed=false}}
SLINK_RUNTIME_STATUS=function() return STATUS end
"""
LAUNCHER = """
for _=1,LAUNCH_FRAMES do
    LOG[#LOG+1]={kind="launch",wrapped=emu.frameadvance~=ORIGINAL_ADVANCE}
    emu.frameadvance()
end
"""


class Harness:
    def __init__(self, tmp_path, mode, chain, variant="red", frames=8):
        root = tmp_path / "root"
        for name in ROOT_FILES:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, root / name)
        sym = "\n".join(f"00:{address:04x} {name}" for name, address in SYMBOLS.items()) + "\n"
        for source, target in (("pokered", "pokered"), ("pokered", "pokeblue"), ("pokeyellow", "pokeyellow")):
            (root / ".cache/pret" / source).mkdir(parents=True, exist_ok=True)
            (root / ".cache/pret" / source / f"{target}.sym").write_text(sym)
        self.staged = tmp_path / "staged"
        self.staged.mkdir()
        for name in ("rb", "parcel"):
            (self.staged / f"{name}.lua").write_text(STUB_MODULE % name)
        (self.staged / "launcher.lua").write_text(LAUNCHER)
        self.expected = {"run_id": "r" * 32, "player": "a", "rom_sha1": "a" * 40,
                         "context_generation": "c" * 32, "physical_instance": "p" * 32}
        (self.staged / "go.json").write_text(json.dumps({**self.expected, "ready": True}))
        self.input = {"schema": "gen1-scripted-normal-buttons-v1", "player": "a", "variant": variant,
                      "run_id": "r" * 32, "rom_sha1": "a" * 40,
                      "launcher": str(self.staged / "launcher.lua"),
                      "progress": str(self.staged / "progress.json"),
                      "failure": str(self.staged / "failure.json"),
                      "max_boot_frames": 20000, "deadline_seconds": 1800,
                      "route": {"mode": mode, "module": str(self.staged / "rb.lua"),
                                "handshake": str(self.staged / "go.json"),
                                "progress": str(self.staged / "route_progress.json"),
                                "chain": [{"module": str(self.staged / "parcel.lua"), **entry}
                                          for entry in chain]}}
        (self.staged / "input.json").write_text(json.dumps(self.input))
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        g = self.lua.globals()
        g.SLINK_ROOT = str(root)
        g.ROM_SHA1 = "A" * 40
        g.PHYS, g.GEN = "p" * 32, "c" * 32
        g.ENV = self.lua.table_from({"SLINK_SCRIPTED_INPUT": str(self.staged / "input.json")})
        g.LAUNCH_FRAMES = frames
        self.phases = {}
        g.PHASE = lambda name, frame: self.phases.get(name, "walking")
        self.lua.execute(PRELUDE)

    def run(self):
        self.lua.execute(BOOTSTRAP.read_text())
        return self.log()

    def log(self):
        entries = []
        for entry in self.lua.globals().LOG.values():
            entries.append({str(key): value for key, value in entry.items()})
        return entries

    def route_progress(self):
        return json.loads((self.staged / "route_progress.json").read_text())

    def failure(self):
        return json.loads((self.staged / "failure.json").read_text())


PARCEL_CHAIN = [{"after": "lab-loss-complete", "terminal": "first-ball-readback"}]


def test_chain_handoff_same_snapshot_once(tmp_path):
    h = Harness(tmp_path, "rb-parcel", PARCEL_CHAIN, frames=6)
    calls = {"rb": 0, "parcel": 0}

    def phase(name, frame):
        calls[name] += 1
        if name == "rb":
            return "lab-loss-complete" if calls["rb"] >= 3 else "walking"
        return "first-ball-readback" if calls["parcel"] >= 3 else "lab_exit"

    h.lua.globals().PHASE = phase
    log = h.run()
    news = [e for e in log if e["kind"] == "new"]
    assert [e["module"] for e in news] == ["rb", "parcel"]
    assert h.lua.eval("rawequal")(news[0]["expected"], news[1]["expected"])
    steps = [e for e in log if e["kind"] == "step"]
    handoff = next(i for i, e in enumerate(steps) if e["module"] == "parcel")
    rb_last, parcel_first = steps[handoff - 1], steps[handoff]
    assert rb_last["module"] == "rb" and rb_last["frame"] == parcel_first["frame"]
    rawequal = h.lua.eval("rawequal")
    assert rawequal(rb_last["point"], parcel_first["point"])
    assert rawequal(rb_last["handshake"], parcel_first["handshake"])
    assert rawequal(rb_last["status"], parcel_first["status"])
    # Both steps of the handoff frame sit inside one wrapped_advance: one advance follows them.
    seq = [(e["kind"], e.get("module")) for e in log if e["kind"] in ("step", "advance")]
    i = seq.index(("step", "parcel"))
    assert seq[i - 1] == ("step", "rb") and seq[i + 1] == ("advance", None)
    assert i + 2 == len(seq) or seq[i + 2][0] == "step"
    assert sum(e["kind"] == "advance" for e in log) == 6
    assert sum(e["module"] == "rb" for e in steps) == 3 and calls["parcel"] == 3
    progress = h.route_progress()
    assert progress["stage"] == "first-ball-readback"
    assert [entry["stage"] for entry in progress["chain_handoffs"]] == ["lab-loss-complete"]
    assert progress["chain_handoffs"][0]["frame"] == rb_last["frame"]
    # Unhooked at the chain terminal, not at the first module's terminal.
    launches = [e["wrapped"] for e in log if e["kind"] == "launch"]
    assert launches == [True] * 5 + [False]


def test_starter_only_terminal_unchanged(tmp_path):
    h = Harness(tmp_path, "rb-starter-rival", [], frames=5)
    h.lua.globals().PHASE = lambda name, frame: "lab-loss-complete" if frame >= 2 else "walking"
    log = h.run()
    assert [e["module"] for e in log if e["kind"] == "new"] == ["rb"]
    assert [e["frame"] for e in log if e["kind"] == "step"] == [0, 1, 2]
    assert [e["wrapped"] for e in log if e["kind"] == "launch"] == [True, True, True, False, False]
    assert sum(e["kind"] == "advance" for e in log) == 5
    progress = h.route_progress()
    assert progress["stage"] == "lab-loss-complete" and progress["route_frames"] == 3
    assert "chain_handoffs" not in progress
    assert not (h.staged / "failure.json").exists()


def test_yellow_route_refused(tmp_path):
    h = Harness(tmp_path, "rb-starter-rival", [], variant="yellow", frames=2)
    with pytest.raises(LuaError, match="assertion failed"):
        h.run()
    assert h.failure()["stage"] == "failure"
    assert not any(e["kind"] == "new" for e in h.log())


@pytest.mark.parametrize("mode,chain", [
    ("rb-parcel", []),
    ("rb-starter-rival", PARCEL_CHAIN),
    ("rb-parcel", [{"after": "walking", "terminal": "first-ball-readback"}]),
    ("rb-parcel", PARCEL_CHAIN * 2),
])
def test_malformed_chain_refused(tmp_path, mode, chain):
    h = Harness(tmp_path, mode, chain, frames=2)
    with pytest.raises(LuaError, match="assertion failed"):
        h.run()
    assert not any(e["kind"] == "new" for e in h.log())


def test_chain_budget_monotonic(tmp_path):
    h = Harness(tmp_path, "rb-parcel", PARCEL_CHAIN, frames=120001)
    h.lua.globals().PHASE = lambda name, frame: "lab-loss-complete" if name == "rb" and frame >= 10 else "walking"
    with pytest.raises(LuaError, match="R/B route made no bounded progress"):
        h.run()
    assert "no bounded progress" in h.failure()["error"]
    progress = h.route_progress()
    assert progress["chain_handoffs"][0]["route_frames"] == 11
    assert progress["route_frames"] == 119400 and progress["stage"] == "walking"
    steps = [e for e in h.log() if e["kind"] == "step"]
    assert len(steps) == 119999 + 1  # 119999 frames stepped, plus the extra parcel step on the handoff frame
