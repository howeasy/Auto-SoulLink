"""NDS phase -> registry composite over the REAL lua/hook_registry.lua, the real NDS binding
and fake io/event objects (pack sites from data/games/gen4_hgss)."""
import pytest
from lupa.lua54 import LuaError

from tests.unit.test_nds_hook_binding import PACK, ROOT, Env

BATTLE = ["battle_start_ov12", "battle_faint_cmd", "battle_outcome_copy"]
PC = ["pc_place_first_in_box", "pc_delete_by_index_pair"]
FOUR = BATTLE + ["battle_controller_try_faint"]


class World(Env):
    def __init__(self, phases=None, **cfg):
        super().__init__()
        self.PS = self.lua.eval("dofile")((ROOT / "lua/nds/phase_signals.lua").as_posix())
        self.registry = self.lua.eval("dofile")((ROOT / "lua/hook_registry.lua").as_posix())
        self.load(*BATTLE, *PC, "battle_controller_try_faint")
        self.resident(12)
        self.flags = self.lua.table_from({"battle": True, "pc": False})
        self.calls = self.lua.table_from({"new": 0})
        self.handler_hits = self.lua.table_from({"n": 0})
        phases = phases or {"battle": BATTLE, "pc": PC, "empty": []}
        lua_phases = self.lua.table()
        for name, sites in phases.items():
            lua_phases[name] = self.lua.table_from({
                "sites": self.lua.table_from([self.site(n) for n in sites]),
                "active": self.lua.eval("function(flags,name) return function() return flags[name] end end")(self.flags, name)})
        binding, registry, calls = self.binding, self.registry, self.calls
        wrapped = self.lua.eval("""function(real,calls) return {new=function(o) calls.new=calls.new+1 return real.new(o) end} end""")(registry, calls)
        capture = self.lua.eval("""function(binding) return function(site,...)
            local ctx=binding:context(site)
            if ctx==nil then return nil end
            return {id=site.id,pc=ctx.pc,frame=ctx.frame}
        end end""")(binding)
        self.cfg_ps = self.lua.table_from({"Registry": wrapped, "binding": binding, "owner": "g4", "max_pending": 8,
                                           "capture": capture, "phases": lua_phases, **cfg})
        self.sig = self.PS.new(self.cfg_ps)

    def ids(self):
        return [e["id"] for e in self.sig.drain(self.sig).values()]

    def fire(self, name):
        s = PACK["sites"][name]
        self.st.pc = s["address"] + 4
        self.st.fire(s["address"], int(s["fire_hex"], 16))

    def status(self):
        return self.sig.status(self.sig)


def test_arm_disarm_lifecycle_tracks_actual_handles():
    w = World(cap=3)
    assert w.sig.arm(w.sig, "battle") is True
    s = w.status()
    assert s["owned"] == 3 and s["armed"]["battle"] is True and s["registered"] == 3
    assert w.sig.arm(w.sig, "battle") is True and w.st.count() == 3  # idempotent, no double registration
    w.fire("battle_faint_cmd")
    assert w.ids() == ["battle_faint_cmd"] and w.ids() == []
    assert w.sig.disarm(w.sig, "battle") is True
    s = w.status()
    assert s["owned"] == 0 and w.st.count() == 0 and len(s["armed"]) == 0 and s["registered"] == 3 and s["failure"] is None
    assert w.sig.arm(w.sig, "battle") is True  # owner namespace released: re-arm works
    assert w.status()["registered"] == 6  # cumulative, unlike `owned`


def test_last_queued_event_survives_disarm_and_is_drained_exactly_once():
    w = World(cap=3)
    w.sig.arm(w.sig, "battle")
    w.fire("battle_start_ov12")
    w.fire("battle_outcome_copy")
    assert w.sig.disarm(w.sig, "battle") is True
    assert w.status()["held"] == 2
    assert w.ids() == ["battle_start_ov12", "battle_outcome_copy"]
    assert w.ids() == [] and w.status()["held"] == 0


def test_zero_site_phase_builds_no_registry():
    w = World()
    assert w.sig.arm(w.sig, "empty") is True
    assert w.calls["new"] == 0 and w.status()["owned"] == 0 and len(w.status()["armed"]) == 0
    assert w.sig.disarm(w.sig, "empty") is True


def test_failed_registry_new_is_handled_without_throwing_and_cleans_up():
    w = World(cap=3)
    w.st.put(PACK["sites"]["battle_outcome_copy"]["address"] + 9, "ff")  # third pin bad: nothing registered yet
    ok, why = w.sig.arm(w.sig, "battle")
    assert ok is None and "full registration pin mismatch" in why
    s = w.status()
    assert s["owned"] == 0 and w.st.count() == 0 and len(s["retained"]) == 0 and "battle" in s["faults"] and s["failure"]
    w.load(*BATTLE)
    assert w.sig.arm(w.sig, "battle")[0] is None  # latched: no re-arm


def test_partial_construction_with_failed_cleanup_retains_handle_and_owner():
    w = World(cap=3)
    w.st.bad_register = "g4.battle:battle_faint_cmd"  # second registration returns a null GUID
    w.st.fail_remove = True  # the unwind cannot remove the first handle
    ok, why = w.sig.arm(w.sig, "battle")
    assert ok is None and "registration failed" in why and "cleanup failed" in why
    s = w.status()
    assert s["owned"] == 1 and s["retained"]["battle"]["handles"] == 1 and s["retained"]["battle"]["owner"] == "g4.battle"
    assert w.st.count() == 1
    w.st.fail_remove = False
    w.st.bad_register = None
    assert w.sig.arm(w.sig, "battle")[0] is None  # still latched
    assert w.sig.recover(w.sig) is True  # explicit recovery: retried close succeeds, fault clears
    s = w.status()
    assert s["owned"] == 0 and w.st.count() == 0 and s["failure"] is None and len(s["retained"]) == 0
    assert w.sig.arm(w.sig, "battle") is True


def test_failed_close_latches_counts_handles_blocks_rearm_and_keeps_the_last_event():
    w = World(cap=3)
    w.sig.arm(w.sig, "battle")
    w.fire("battle_faint_cmd")
    w.st.fail_remove = True
    assert w.sig.disarm(w.sig, "battle") is False
    s = w.status()
    assert s["owned"] == 3 and s["retained"]["battle"]["handles"] == 3 and "battle" in s["faults"]
    assert w.sig.failure == s["faults"]["battle"] and "close failed" in s["faults"]["battle"]
    assert w.ids() == ["battle_faint_cmd"] and w.ids() == []  # surviving event, once
    w.fire("battle_faint_cmd")  # the closed registry no longer captures
    assert w.ids() == []
    ok, why = w.sig.arm(w.sig, "pc")
    assert ok is None and why == w.sig.failure and w.status()["owned"] == 3
    assert w.sig.close(w.sig) is False  # still cannot release
    w.st.fail_remove = False
    assert w.sig.recover(w.sig) is True and w.status()["owned"] == 0 and w.sig.failure is None
    assert w.sig.arm(w.sig, "pc") is True


def test_fourth_production_hook_is_refused_and_observer_allowance_is_explicit():
    w = World({"four": FOUR}, cap=3)
    ok, why = w.sig.arm(w.sig, "four")
    assert ok is None and "budget 3 exceeded" in why and w.status()["owned"] == 0 and w.st.count() == 0
    assert w.sig.failure is None and w.status()["refused"] == 1  # F3: refused and counted, not latched
    w4 = World({"four": FOUR}, cap=3, observer_allowance=1)
    assert w4.sig.arm(w4.sig, "four") is True and w4.status()["owned"] == 4 and w4.status()["budget"] == 4
    with pytest.raises(LuaError, match="cap 0..3"):
        World({"x": BATTLE}, cap=4)
    with pytest.raises(LuaError, match="cap 0..3"):
        World({"x": BATTLE}, observer_allowance=2)


def test_default_cap_is_one_concurrent_hook_owner_ruling():
    w = World({"two": PC, "one": ["battle_start_ov12"]})
    assert w.status()["budget"] == 1
    assert w.sig.arm(w.sig, "two")[0] is None  # 2 > 1
    w = World({"two": PC, "one": ["battle_start_ov12"]})
    assert w.sig.arm(w.sig, "one") is True and w.status()["owned"] == 1
    assert w.sig.arm(w.sig, "two")[0] is None  # and total, not per phase


def test_status_aggregates_across_phases():
    w = World({"a": ["battle_start_ov12"], "b": PC}, cap=3)
    w.sig.arm(w.sig, "a")
    w.sig.arm(w.sig, "b")
    w.fire("battle_start_ov12")
    w.fire("pc_place_first_in_box")
    s = w.status()
    assert s["owned"] == 3 and s["pending"] == 2 and set(s["armed"]) == {"a", "b"} and s["registered"] == 3
    w.sig.disarm(w.sig, "a")
    s = w.status()
    assert s["owned"] == 2 and s["registered"] == 3 and s["held"] == 1 and s["pending"] == 1
    assert sorted(w.ids()) == ["battle_start_ov12", "pc_place_first_in_box"]


def test_poll_drives_phases_from_predicates_disarming_before_arming():
    w = World({"a": ["battle_start_ov12"], "b": ["pc_place_first_in_box"]})  # cap 1: hand-over must free first
    w.flags["a"], w.flags["b"] = True, False
    w.sig.poll(w.sig)
    assert set(w.status()["armed"]) == {"a"}
    w.fire("battle_start_ov12")
    w.flags["a"], w.flags["b"] = False, True
    w.sig.poll(w.sig)
    s = w.status()
    assert set(s["armed"]) == {"b"} and s["owned"] == 1 and s["failure"] is None
    assert w.ids() == ["battle_start_ov12"]  # drained before the registry went away
    w.flags["b"] = False
    w.sig.poll(w.sig)
    assert w.status()["owned"] == 0


def test_throwing_predicate_latches_instead_of_throwing():
    w = World({"a": ["battle_start_ov12"]})
    w.flags["a"] = True
    w.cfg_ps["phases"]["a"]["active"] = w.lua.eval("function() error('pred') end")
    w.sig = w.PS.new(w.cfg_ps)
    w.sig.poll(w.sig)
    assert "pred" in w.sig.failure and w.status()["owned"] == 0


def test_on_demand_arm_fire_auto_remove_then_zero_handles():
    w = World({"seam": ["battle_faint_cmd"], "other": ["battle_start_ov12"]})
    assert w.sig.request(w.sig, "seam") is True
    s = w.status()
    assert s["armed"]["seam"] == "on_demand" and s["owned"] == 1 and w.st.count() == 1
    assert w.ids() == []  # nothing fired yet: stays armed
    assert w.st.count() == 1
    # A second request while one is armed (cap 1) is refused, not queued, and is not a fault.
    ok, why = w.sig.request(w.sig, "other")
    assert ok is None and why.startswith("busy") and w.sig.failure is None
    assert w.sig.request(w.sig, "seam")[1].startswith("busy")
    w.fire("battle_faint_cmd")
    assert w.ids() == ["battle_faint_cmd"]  # the drain that returns the event removes the hook
    s = w.status()
    assert s["owned"] == 0 and w.st.count() == 0 and len(s["armed"]) == 0 and s["failure"] is None
    assert w.ids() == []
    assert w.sig.request(w.sig, "other") is True  # free again
    assert w.sig.disarm(w.sig, "other") is True and w.status()["owned"] == 0


def test_on_demand_auto_remove_failure_latches_but_keeps_the_event():
    w = World({"seam": ["battle_faint_cmd"]})
    w.sig.request(w.sig, "seam")
    w.fire("battle_faint_cmd")
    w.st.fail_remove = True
    assert w.ids() == ["battle_faint_cmd"]
    s = w.status()
    assert s["owned"] == 1 and "seam" in s["faults"] and w.sig.request(w.sig, "seam")[0] is None


def test_active_overlay_fire_word_mismatch_latches_through_the_registry():
    w = World({"b": BATTLE}, cap=3)
    w.sig.arm(w.sig, "b")
    s = PACK["sites"]["battle_faint_cmd"]
    w.st.pc = s["address"] + 4
    w.st.fire(s["address"], 0xDEADBEEF)  # owning overlay active, wrong word: corruption
    assert w.ids() == []
    assert "fire word differs" in w.sig.failure and "fire word differs" in w.status()["faults"]["b"]
    assert w.status()["owned"] == 0 and w.st.count() == 0  # a dead registry's hooks are removed, not left costing fps
    assert w.sig.arm(w.sig, "b")[0] is None  # latched


def test_wrong_overlay_hit_is_dropped_by_the_composite_without_a_fault():
    w = World({"b": BATTLE}, cap=3)
    w.sig.arm(w.sig, "b")
    w.resident(13)
    w.fire("battle_faint_cmd")
    w.st.fire(PACK["sites"]["battle_faint_cmd"]["address"], 0x12345678)
    assert w.ids() == [] and w.sig.failure is None


def test_handler_error_is_surfaced_once_and_close_drains():
    w = World({"b": BATTLE}, cap=3)
    boom = w.lua.eval("function() error('handler') end")
    w.cfg_ps["on_event"] = boom
    w.sig = w.PS.new(w.cfg_ps)
    w.sig.arm(w.sig, "b")
    w.fire("battle_faint_cmd")
    assert len(w.sig.drain(w.sig)) == 1 and "handler" in w.sig.handler_error
    w.sig.handler_error = None  # session clears it after logging
    w.fire("battle_start_ov12")
    w.sig.drain(w.sig)
    assert w.sig.handler_error is None  # ponytail: reported once per distinct message per registry
    w.fire("battle_outcome_copy")
    assert w.sig.close(w.sig) is True
    assert w.status()["owned"] == 0 and len(w.sig.drain(w.sig)) == 1  # close drained the rest, once


def test_close_after_events_returns_them_once_and_releases_everything():
    w = World(cap=3)
    w.sig.arm(w.sig, "battle")
    w.fire("battle_faint_cmd")
    assert w.sig.close(w.sig) is True and w.st.count() == 0 and w.status()["owned"] == 0
    assert w.ids() == ["battle_faint_cmd"] and w.ids() == []


def test_poll_budget_overrun_is_a_counted_refusal_and_never_locks_out_the_on_demand_hook():
    """F3: two predicates want hooks at cap 1; the loser is refused every poll, nothing latches, request() still works."""
    w = World({"a": ["battle_start_ov12"], "b": ["pc_place_first_in_box"], "seam": ["battle_faint_cmd"]})
    w.flags["a"], w.flags["b"], w.flags["seam"] = True, True, False
    for _ in range(3):
        w.sig.poll(w.sig)
    s = w.status()
    assert set(s["armed"]) == {"a"} and s["refused"] == 3 and "busy" in s["last_refusal"]
    assert w.sig.failure is None and len(s["faults"]) == 0                      # never latched
    w.flags["a"] = False
    w.sig.poll(w.sig)                                                       # "a" disarmed; "b" arms next poll
    w.flags["b"] = False
    w.sig.poll(w.sig)
    assert w.status()["owned"] == 0
    assert w.sig.request(w.sig, "seam") is True                             # the D7 seam can still arm
    w.fire("battle_faint_cmd")
    assert w.ids() == ["battle_faint_cmd"] and w.status()["owned"] == 0


def test_throwing_predicate_disarms_an_armed_phase_fail_closed():
    """F4: the hook must not stay armed (and costing fps) behind a predicate that throws."""
    w = World({"a": ["battle_start_ov12"]})
    w.flags["a"] = True
    w.sig.poll(w.sig)
    assert w.status()["owned"] == 1
    w.fire("battle_start_ov12")
    w.cfg_ps["phases"]["a"]["active"] = w.lua.eval("function() error('pred') end")
    w.sig.poll(w.sig)
    s = w.status()
    assert s["owned"] == 0 and w.st.count() == 0 and len(s["armed"]) == 0 and "pred" in w.sig.failure
    assert w.ids() == ["battle_start_ov12"]                                 # the queued event was still drained


def _mutant(w, old, new):
    src = (ROOT / "lua/nds/phase_signals.lua").read_text(encoding="utf-8")
    assert src.count(old) == 1, old
    return w.lua.eval("function(s) return assert(load(s, '=ps'))() end")(src.replace(old, new)).new(w.cfg_ps)


def test_control_revert_f4_leaves_the_hook_armed():
    w = World({"a": ["battle_start_ov12"]})
    w.flags["a"] = True
    mutant = _mutant(w, 'latch(name,"predicate",result); want[name]=false end', 'latch(name,"predicate",result) end')
    mutant.poll(mutant)
    assert mutant.status(mutant)["owned"] == 1
    w.cfg_ps["phases"]["a"]["active"] = w.lua.eval("function() error('pred') end")
    mutant.poll(mutant)
    assert mutant.status(mutant)["owned"] == 1                              # reverted: still armed behind a throwing predicate


def test_control_revert_f3_latches_a_poll_overrun():
    w = World({"a": ["battle_start_ov12"], "b": ["pc_place_first_in_box"]})
    w.flags["a"], w.flags["b"] = True, True
    mutant = _mutant(
        w,
        'refused=refused+1\n            last_refusal=phase..": busy: hook budget "..budget.." exceeded: "'
        '..count_owned().." owned + "..#sites\n            return nil,last_refusal',
        'latch(phase,"budget","hook budget exceeded")\n            return nil,faults[phase].message')
    mutant.poll(mutant)
    assert mutant.failure is not None                                       # reverted: permanent fault, request() dead too
    assert mutant.request(mutant, "a")[0] is None
