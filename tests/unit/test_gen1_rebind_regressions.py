"""Gen 1 rebind regressions (review P3_SHARED_MODULES_REVIEW_2026-09-22): MODEL controls.

Each test pins one behaviour Gen 1 had on master 8f6a986 that the shared-module rebind lost,
plus a master-equivalence differential that drives the SAME scripted client scenarios through
master's files (extracted with `git archive` to a scratch dir) and through this tree.
"""
from __future__ import annotations

import io as _io
import json
import pathlib
import random
import subprocess
import tarfile

import lupa
import pytest

import tests.unit.test_gen1_client as tgc
from tests.unit.test_gen1_signals import Harness

REPO = pathlib.Path(__file__).resolve().parents[2]
MASTER = "8f6a986"
DUO = (REPO / "lua" / "tests" / "duo" / "duo_gen1_main.lua").read_text(encoding="utf-8")


def _world(root=REPO, monkeypatch=None):
    if monkeypatch is not None:
        rom = tgc._rom("red")  # the real dump in THIS tree (skips loudly without it)
        monkeypatch.setattr(tgc, "ENTRY", (root / "lua" / "gen1" / "entry.lua").as_posix())
        monkeypatch.setattr(tgc, "REPO", root)
        monkeypatch.setattr(tgc, "_rom", lambda title: rom)
    w = tgc.World("red")
    rng = random.Random(1)
    w.seed_party([tgc._mon(rng, 0x99, nick="BULBA"), tgc._mon(rng, 0xB1, nick="PIDGEY")])
    w.set_map(0x0C)
    w.give_poke_ball()
    return w


def _trace(w):
    """One ordered list of what a server or a player can observe: sent lines and panel clears."""
    trace = []

    def send(line):
        msg = json.loads(str(line))
        w.sent.append(msg)
        trace.append(("sent", msg))

    w.net.send = send
    assert w.client.panel is not None, "the clean Red pack must carry the panel for this control"
    clear = w.client.panel.clear
    w.client.panel.clear = lambda panel: (trace.append(("clear",)), clear(panel))[1]
    return trace


def _step(w, trace, n=1):
    for _ in range(n):
        try:
            w.step()
        except lupa.LuaError as err:
            trace.append(("frame_error", "pump boom" in str(err)))


def _off_checkpoint(w):
    w.regs["PC"] = 0x1234


# ── U1: a handler error never silences later engine signals ──────────────────────────────

def test_u1_registry_keeps_queuing_after_a_handler_error():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    registry = lua.eval("dofile")((REPO / "lua" / "hook_registry.lua").as_posix())
    state, options = lua.eval("""function()
        local s={callbacks={}}
        return s,{owner='u1',max_pending=8,sites={{id='a'}},
            validate=function(site) return {id=site.id} end,
            register=function(site,fn) s.callbacks[site.id]=fn; return 1 end,
            unregister=function() return true end,
            valid_handle=function(h) return h==1 end,
            capture=function(site) return {kind=site.id} end,
            on_event=function() if s.boom then s.boom=false; error('handler exploded') end end}
    end""")()
    service = registry.new(options)
    state.boom = True
    state.callbacks.a()
    state.callbacks.a()
    status = service.status(service)
    assert "handler exploded" in str(status.handler_error) and status.failed is None
    assert len(service.drain(service)) == 2


def test_u1_gen1_signals_after_a_battle_loop_head_handler_error_still_queue():
    h = Harness("red")
    handlers = h.lua.table(battle_loop_head=h.lua.eval("function() error('W-10 refusal') end"))
    h.svc = h.S.new(h._profile, h._sites, h._io, handlers)
    h.arrive("battle_loop_head")
    h.arrive("move_mon")
    assert [s["kind"] for s in h.drain()] == ["battle_loop_head", "move_mon"]
    assert "W-10 refusal" in str(h.status().handler_error)


def test_u1_client_logs_the_handler_error_and_later_signals_still_reach_the_client():
    w = _world()
    w.connect()
    w.client.on_battle_loop_head = w.lua.eval("function() error('W-10 refusal') end")
    w.fire("battle_loop_head")
    w.fire("save_witness")
    w.step()
    assert w.saveram_calls == 1
    assert any("battle_loop_head" in line and "W-10 refusal" in line for line in w.logs)


# ── U2: the duo save-witness tee observes one new queued save_witness through the API ─────

def _tee_chunk():
    start = DUO.index("local _on_bus_exec = deps.on_bus_exec")
    end = DUO.index("return _on_bus_exec(fn, addr, name, dom)\nend\n", start)
    return DUO[start:end] + "return _on_bus_exec(fn, addr, name, dom)\nend\n"


@pytest.mark.parametrize("drop", [False, True])
def test_u2_duo_save_witness_tee_dumps_exactly_when_the_signal_queues(drop):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    registry = lua.eval("dofile")((REPO / "lua" / "hook_registry.lua").as_posix())
    g = lua.globals()
    hooks, logs, dumps = {}, [], []
    g.deps = lua.table(on_bus_exec=lambda fn, addr, name, dom: hooks.setdefault(str(name), fn) and 1)
    g.log, g.fmt = lambda s: logs.append(str(s)), lua.eval("string.format")
    g.dump_save_witness = lambda: dumps.append(1)
    lua.execute(_tee_chunk())
    options = lua.eval("""function(drop) return {owner='SLink-gen1',max_pending=8,sites={{id='save_witness'}},
        name_for_site=function(site) return 'SLink-gen1-'..site.id end,
        validate=function(site) return {id=site.id} end,
        register=function(site,fn,name) return deps.on_bus_exec(fn,0,name,'System Bus') end,
        unregister=function() return true end, valid_handle=function(h) return h==1 end,
        capture=function(site) if drop then return nil end return {kind=site.id} end} end""")(drop)
    service = registry.new(options)
    g.SLINK_GEN1_CLIENT = lua.table(signals=service)
    hooks["SLink-gen1-save_witness"]()
    if drop:
        assert dumps == [] and logs == ["SAVE_WITNESS_DUMP_SKIPPED why=pending-0-to-0"]
    else:
        assert dumps == [1] and logs == []
        assert service.status(service).pending == 1


def test_u2_peek_is_a_detached_copy():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    registry = lua.eval("dofile")((REPO / "lua" / "hook_registry.lua").as_posix())
    fire, options = lua.eval("""function()
        local s={}
        return function() s.fn() end, {owner='peek',max_pending=4,sites={{id='a'}},
            validate=function(site) return {id=site.id} end,
            register=function(site,fn) s.fn=fn; return 1 end, unregister=function() return true end,
            valid_handle=function(h) return h==1 end, capture=function(site) return {kind=site.id} end}
    end""")()
    service = registry.new(options)
    fire()
    view = service.peek(service)
    view[1].kind, view[2] = "mutated", lua.table(kind="forged")
    assert [e.kind for e in service.drain(service).values()] == ["a"]


# ── U3: a direct send_hello() (inspect/apex gates) sends one hello, as on master ──────────

def test_u3_direct_send_hello_sends_one_hello_and_the_session_does_not_repeat_it():
    w = _world()
    w.connected = True  # the inspect gate sets t.online and never calls frame_end first
    w.client.send_hello(w.client)
    assert len(w.events("hello")) == 1 and w.client.hello_sent is True
    w.step(40)  # the apex gates then settle through frame_end
    assert len(w.events("hello")) == 1


# ── listed diff 1: a savestate rewind keeps the session (one hello, panel kept) ───────────

def test_diff1_clock_rewind_keeps_one_hello_and_the_panel():
    w = _world()
    trace = _trace(w)
    w.connect()
    w.step(10)
    w.frame -= 8
    w.step(10)
    assert len(w.events("hello")) == 1 and ("clear",) not in trace


# ── listed diff 4: wIsInBattle == $FF (lost battle / blackout) is in battle, not unreadable

def test_diff4_hello_during_a_blackout_is_sent_like_master():
    w = _world()
    w.bus[w.ram["wIsInBattle"]] = 0xFF
    _off_checkpoint(w)
    w.connect()
    hello = w.events("hello")
    assert len(hello) == 1 and hello[0]["in_battle"] is True


# ── listed diff 6: one pump error propagates, the session and panel survive ──────────────

def test_diff6_pump_error_propagates_without_a_second_hello_or_panel_clear():
    w = _world()
    trace = _trace(w)
    w.connect()
    w.net.pump = w.lua.eval("function() error('pump boom', 0) end")
    with pytest.raises(lupa.LuaError, match="pump boom"):
        w.step()
    w.net.pump = lambda: None
    w.step(5)
    assert len(w.events("hello")) == 1 and ("clear",) not in trace


# ── U6: a PC mismatch on a hit the filter drops latches nothing ──────────────────────────

def test_u6_filtered_hit_with_a_wrong_pc_does_not_stop_later_signals():
    h = Harness("red")
    h.start()
    h.arrive("bag_received", wrong_pc=True)  # carry clear: the filter drops this hit first
    assert h.status().failed is None
    h.arrive("move_mon")
    assert [s["kind"] for s in h.drain()] == ["move_mon"]


def test_n1_a_throwing_filter_drops_one_hit_and_later_signals_still_queue():
    """Reviewer's probe: bag_received with the F register missing. Master let that error escape
    one hit and still queued move_mon; it must never latch the service."""
    h = Harness("red")
    h.start()
    del h.regs["F"]
    h.arrive("bag_received")
    h.regs["F"] = 0
    assert h.status().failed is None
    h.arrive("move_mon")
    assert [s["kind"] for s in h.drain()] == ["move_mon"]


def test_n1_client_logs_each_new_filter_error_once_never_per_frame():
    w = _world()
    w.connect()

    def filter_logs():
        return [line for line in w.logs if "signal filter" in line]

    del w.regs["F"]
    w.fire("bag_received")
    w.regs["F"] = 0
    w.step(5)
    logs = filter_logs()
    assert len(logs) == 1 and "bag_received" in logs[0] and "'F'" in logs[0]
    w.step(60)
    assert len(filter_logs()) == 1
    del w.regs["F"]
    w.fire("bag_received")
    w.regs["F"] = 0
    w.step(3)
    assert len(filter_logs()) == 2


def test_n1_signals_filter_status_is_a_detached_copy():
    h = Harness("red")
    h.start()
    del h.regs["F"]
    h.arrive("bag_received")
    view = h.svc.filter_status(h.svc)
    view.accept_errors = 99
    assert h.svc.filter_status(h.svc).accept_errors == 1


# ── master-equivalence differential ──────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def master_root(tmp_path_factory):
    try:
        blob = subprocess.run(["git", "-C", str(REPO), "archive", MASTER, "lua", "data"],
                              check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip(f"master {MASTER} not available in this clone")
    root = tmp_path_factory.mktemp("master_8f6a986")
    with tarfile.open(fileobj=_io.BytesIO(blob)) as tar:
        tar.extractall(root, filter="data")
    return root


def _boot(w, t):
    _step(w, t, 3)
    w.connected = True
    _step(w, t, 70)


def _idle(w, t):
    w.connected = True
    _step(w, t, 125)


def _rewind(w, t):
    w.connected = True
    _step(w, t, 40)
    w.frame -= 25
    _step(w, t, 70)


def _blackout(w, t):
    w.bus[w.ram["wIsInBattle"]] = 0xFF
    _off_checkpoint(w)
    w.connected = True
    _step(w, t, 35)
    w.connected = False
    _step(w, t, 3)
    w.connected = True
    _step(w, t, 35)


def _pump_error(w, t):
    w.connected = True
    _step(w, t, 10)
    w.net.pump = w.lua.eval("function() error('pump boom', 0) end")
    _step(w, t)
    w.net.pump = lambda: None
    _step(w, t, 60)


def _reconnect(w, t):
    w.connected = True
    _step(w, t, 10)
    w.connected = False
    _step(w, t, 4)
    w.connected = True
    _step(w, t, 60)


def _direct_hello(w, t):
    w.connected = True
    w.client.send_hello(w.client)
    _step(w, t, 60)


def _save_reset(w, t):
    w.connected = True
    _step(w, t, 10)
    saved = bytes(w.bus)
    w.bus[w.ram["wPlayerID"]:w.ram["wPlayerID"] + 2] = b"\x00\x00"
    w.bus[w.ram["wPartyCount"]] = 0
    _step(w, t, 60)
    w.bus[:] = saved
    _step(w, t, 70)


SCENARIOS = {"boot": _boot, "idle": _idle, "rewind": _rewind, "blackout": _blackout,
             "pump_error": _pump_error, "reconnect": _reconnect, "direct_hello": _direct_hello,
             "save_reset": _save_reset}


def _one_clear_per_run(trace):
    return [e for i, e in enumerate(trace) if not (e == ("clear",) and i and trace[i - 1] == ("clear",))]


# The only difference the review marked KEEP that these scenarios reach: a WRAM clear changes
# the save identity (wPlayerID 0 and back), and each identity change invalidates the session,
# which clears the (pure-Lua) panel state again before the same re-hello (KEEP #2 and #3).
KEEP = {"save_reset": _one_clear_per_run}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_master_equivalence_differential(name, master_root, monkeypatch):
    traces = []
    for root in (master_root, REPO):
        w = _world(root, monkeypatch)
        t = _trace(w)
        SCENARIOS[name](w, t)
        traces.append(KEEP.get(name, list)(t))
    master, head = traces
    assert any(entry[0] == "sent" for entry in master), "the scenario must be observable"
    assert head == master


# ── W14: a phase callback that parks (duo ball_gate_new's rival hold) runs as on master ───

_PARK_STUB = """
local real_dofile = dofile
model_ram, model_frame, model_steps, model_log = {}, 0, 0, {}
emu = {framecount = function() return model_frame end}
memory = {read_u8 = function() return 0 end}
gameinfo = {getromhash = function() return string.rep("ab", 20) end}
dofile = function(path)
    if path:match("/lua/gen1/entry.lua$") then
        return {harness_bus_u8 = function() return function(a) return model_ram[a] or 0 end end}
    elseif path:match("/gen1_rb_ball_gate_inputs.lua$") then
        return {new = function()
            local calls = 0
            local phases = {"walk", "walk", "rival-challenge-dialogue", "fight", "fight", "lab-loss-complete"}
            return {step = function(_, _, point, frame)
                calls = calls + 1
                return {A = calls % 2 == 1}, phases[math.min(calls, #phases)]
            end}
        end}
    end
    return real_dofile(path)
end
model_step = function(buttons)
    model_steps = model_steps + 1; model_frame = model_frame + 1
    model_log[#model_log + 1] = buttons and buttons.A and "A" or "-"
end
"""

_PARK_RUN = """
local P = dofile(HOST)
local play = P.new(ROOT, "red", "a", {})
play.point = function() return {tick = model_frame} end
local seen = {}
local receipts = play.run(model_step, {"lab"}, function(name, phase, frame, point)
    seen[#seen + 1] = name .. ":" .. phase .. "@" .. frame .. "/" .. point.tick
    if phase == "rival-challenge-dialogue" then
        for _ = 1, PARK do model_step(nil) end   -- the duo wait_until: yield_frame() per frame
    end
end, 10)
return receipts.lab, model_steps, model_frame, table.concat(seen, ","), table.concat(model_log)
"""


def _park_run(host_path, park=50):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_PARK_STUB)
    g = lua.globals()
    g.HOST, g.ROOT, g.PARK = pathlib.Path(host_path).as_posix(), REPO.as_posix(), park
    return lua.execute(_PARK_RUN)


def test_w14_parked_phase_callback_matches_master(tmp_path_factory):
    """ball_gate_new parks 900 s inside on_phase; master counted only loop iterations against
    max_frames_each (so 50 parked frames under a 10-iteration bound pass), did not re-read the
    point, and stepped the pre-park buttons afterwards."""
    scratch = tmp_path_factory.mktemp("w14_master")
    master = scratch / "gen1_scripted_play.lua"
    master.write_bytes(subprocess.run(["git", "show", f"{MASTER}:lua/tests/gen1_scripted_play.lua"],
                                      cwd=REPO, check=True, capture_output=True).stdout)
    want = _park_run(master)
    assert want[0] == 6 and want[1] == 56  # 6 iterations; 5 route steps + 50 parked + 1 idle
    assert _park_run(REPO / "lua" / "tests" / "gen1_scripted_play.lua") == want
