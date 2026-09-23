"""Pack-driven negative controls; no emulator or ROM required."""
import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
ROOT = Path(__file__).resolve().parents[2]


class World:
    def __init__(self, title="radical_red", kind="companion"):
        folder = "gen3_rr" if title == "radical_red" else "gen3_frlg"
        self.pack = json.loads((ROOT / "data/games" / folder / "write_checkpoint.json").read_text())[title]
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute("""
            mem = {}; rom = {}; unreadable = nil
            function put(a, v, n)
                for i=0,n-1 do mem[a+i] = v % 256; v = math.floor(v/256) end
            end
            function read(a, n, domain)
                local source = domain == 'ROM' and rom or mem
                local v = 0
                for i=0,n-1 do
                    if a+i == unreadable or source[a+i] == nil then return nil end
                    v = v + source[a+i] * 256^i
                end
                return v
            end
            cpu = {R15=452, CPSR=31}; idle = true; frame = 7; writes = {}
            deps = {io={read_u8=function(a,d) return read(a,1,d) end,
                read_u16_le=function(a,d) return read(a,2,d) end,
                read_u32_le=function(a,d) return read(a,4,d) end,
                write_u8=function(a,v) writes[#writes+1]={a,v} end},
                regs=function() return cpu end, native_idle=function() return idle end,
                frame=function() return frame end}
        """)
        g = self.lua.globals()
        cpu = self.pack["cpu"]  # a parked frame end for this title
        g.cpu.R15 = cpu.get("observed_pc", cpu["pc_min"])
        g.cpu.CPSR = cpu["mode"] | cpu["thumb"] << 5
        for anchor in self.pack["anchors"].values():
            for i, byte in enumerate(bytes.fromhex(anchor["expected_hex"][kind])):
                g.rom[anchor["rom_offset"] + i] = byte
        for p in self.pack["predicates"].values():
            g.put(p["address"] + p["offset"], p["expect"], p["width"])
        for i, (name, p) in enumerate(self.pack["pointers"].items()):
            if name != "pokemon_storage_base":
                g.put(p["address"], 0x02010000 + i * 0x1000, 4)
        t = self.pack["tasks"]
        for i in range(t["count"] * t["struct_size"]):
            g.mem[t["address"] + i] = 0
        for i, fn in enumerate(t["allowed_overworld_tasks"].values()):
            base = t["address"] + i * t["struct_size"]
            g.put(base + t["func_offset"], fn | 1, 4)
            g.put(base + t["is_active_offset"], 1, 1)
        guard = self.pack["battle"]["commit_guard"]
        for slot in range(4):   # the guard is indexed by battler; all four must be readable and < 3
            g.put(guard["address"] + guard.get("offset", 0) + slot, 0, guard["width"])
        for spec in self.pack["battle"]["clauses"]:
            # after the guard: battle_comm_0 shares the guard's address, and 1 is < 3 for both
            value = 1 if spec["compare"] == "nonzero" else spec["expect"]
            g.put(spec["address"] + spec.get("offset", 0), value, spec["width"])
        if "native" in self.pack:
            n = self.pack["native"]
            g.put(n["base"], n["sig"], 4)
            g.put(n["base"] + n["abi_off"], n["abi"], 2)
            g.put(n["base"] + n["opcode_off"], 0, 2)
            g.put(n["base"] + n["status_off"], 2, 2)          # ST_OK, not ST_BUSY
            g.put(n["info"] + n["info_drawn_off"], 1, 1)
            g.put(n["info"] + n["info_ack_off"], 1, 1)
        snd = self.pack["sound"]
        if "player_se1" in snd:
            g.put(snd["player_se1"]["address"] + snd["ident_off"], snd["ident_magic"], 4)
            g.put(snd["player_se1"]["address"] + snd["tracks_off"], 0x03005000, 4)
        module = self.lua.execute((ROOT / "lua/gen3/safety.lua").read_text(encoding="utf-8"))
        self.safety = module.new(self.lua.table_from(self.pack, recursive=True), g.deps, kind)

    def check(self, snapshot=None):
        return self.safety.check(self.safety, snapshot)[0]

    def check_reason(self, reason, args=None):
        """(ok, reason_string, sorted clause keys) for one reason; the probe reads the same three."""
        result = self.safety.check(self.safety, None, reason,
                                   self.lua.table_from(args or {}, recursive=True))
        return bool(result[0]), result[1], list(self.safety.last_clauses.values())


@pytest.mark.parametrize("title,kind", [("firered", "clean"), ("leafgreen", "clean"),
                                      ("radical_red", "clean"), ("radical_red", "companion")])
def test_committed_census_positive(title, kind):
    assert World(title, kind).check()


@pytest.mark.parametrize("name", ["callback1", "callback2", "field_controls_locked", "in_battle",
                                  "link_callback", "link_players_received", "link_transferring",
                                  "palette_fade_active", "save_dialog_cb", "script_context_status",
                                  "soft_reset_disabled"])
def test_each_forbidden_state(name):
    w = World()
    p = w.pack["predicates"][name]
    w.lua.globals().put(p["address"] + p["offset"], p.get("mask", p["expect"] ^ 1), p["width"])
    assert not w.check()


@pytest.mark.parametrize("r15,cpsr", [(452, 16), (452, 18), (452, 63), (16384, 31)])
def test_cpu_refuses_other_mode_thumb_or_unparked_pc(r15, cpsr):
    w = World()
    w.lua.globals().cpu.R15 = r15
    w.lua.globals().cpu.CPSR = cpsr
    assert not w.check()


@pytest.mark.parametrize("r15,cpsr,ok", [
    (0x080008AC, 0x6000003F, True),   # WaitForVBlank, System mode, Thumb (FR census row)
    (0x080008AC, 0x6000001F, False),  # same PC, T=0
    (0x0000001C, 0x00000012, False),  # BIOS IRQ vector in IRQ mode: refused on purpose
    (0x000001C4, 0x0000001F, False),  # the RR BIOS park is not an FR park
])
def test_firered_parked_cpu(r15, cpsr, ok):
    w = World("firered", "clean")
    w.lua.globals().cpu.R15 = r15
    w.lua.globals().cpu.CPSR = cpsr
    assert bool(w.check()) is ok


def test_unknown_active_task():
    w = World()
    t = w.pack["tasks"]
    w.lua.globals().put(t["address"] + t["func_offset"], 0x08000001, 4)
    assert not w.check()


@pytest.mark.parametrize("category", ["anchor", "predicate", "task", "pointer"])
def test_unreadable_input(category):
    w = World()
    p = w.pack
    address = {"anchor": p["anchors"]["cb1_overworld"]["rom_offset"],
               "predicate": p["predicates"]["callback1"]["address"],
               "task": p["tasks"]["address"] + p["tasks"]["is_active_offset"],
               "pointer": p["pointers"]["gSaveBlock1Ptr"]["address"]}[category]
    w.lua.globals().unreadable = address
    assert not w.check()


def test_rom_rechecked_and_native_idle_fail_closed():
    w = World()
    assert w.check()
    w.lua.globals().idle = False
    assert not w.check()
    w.lua.globals().idle = None
    assert not w.check()
    w.lua.globals().idle = True
    a = w.pack["anchors"]["frame_control"]["rom_offset"]
    w.lua.globals().rom[a] = w.lua.globals().rom[a] ^ 1
    assert not w.check()


@pytest.mark.parametrize("change", ["cpu=nil", "cpu.R15=nil", "cpu.CPSR=nil",
                                   "deps.native_idle=function() error('unreadable') end",
                                   "deps.io.read_u8=function() error('unreadable') end"])
def test_unavailable_dependencies_return_false(change):
    w = World()
    w.lua.execute(change)
    assert not w.check()


def test_missing_required_evidence_fails_closed():
    w = World()
    module = w.lua.execute((ROOT / "lua/gen3/safety.lua").read_text(encoding="utf-8"))
    del w.pack["predicates"]["save_dialog_cb"]
    w.safety = module.new(w.lua.table_from(w.pack, recursive=True), w.lua.globals().deps, "companion")
    assert not w.check()


def test_pointer_movement_refuses_before_write():
    w = World()
    g = w.lua.globals()
    g.deps.safety = w.safety
    module = w.lua.execute((ROOT / "lua/gen3/writes.lua").read_text(encoding="utf-8"))
    writer = module.new(g.deps)
    writer.arm(writer, "overworld", w.lua.eval("function() return true end"))
    g.put(w.pack["pointers"]["gSaveBlock1Ptr"]["address"], 0x02020000, 4)
    with pytest.raises(lupa.LuaError, match="pointer moved"):
        writer.write_u16(writer, 0x02010000, 0)
    assert len(g.writes) == 0


# ── C4-B2: the reason dispatch ────────────────────────────────────────────────────────────────
# The overworld path is the G3-signed predicate and must not move: nil and "overworld" return the
# same result, the same message and the same clause keys as each other, and each clause is still
# independently detectable by name.  The battle/native/sound sets are additive.

OVERWORLD_KEYS = ["callback1", "callback2", "field_controls_locked", "in_battle", "link_callback",
                  "link_players_received", "link_transferring", "palette_fade_active",
                  "save_dialog_cb", "script_context_status", "soft_reset_disabled"]


@pytest.mark.parametrize("reason", [None, "overworld"])
def test_overworld_accept_is_message_identical(reason):
    w = World()
    ok, why, clauses = w.check_reason(reason)
    assert ok is True
    assert why == "verified overworld checkpoint"
    assert clauses == []


@pytest.mark.parametrize("name", OVERWORLD_KEYS)
def test_overworld_clause_attribution_unchanged(name):
    """One broken predicate still names exactly itself, for nil and for "overworld"."""
    w = World()
    p = w.pack["predicates"][name]
    w.lua.globals().put(p["address"] + p["offset"], p.get("mask", p["expect"] ^ 1), p["width"])
    for reason in (None, "overworld"):
        ok, why, clauses = w.check_reason(reason)
        assert ok is False and clauses == [name] and name in why


@pytest.mark.parametrize("key,break_it", [
    ("cpu", lambda w: w.lua.execute("cpu.R15 = 452; cpu.CPSR = 16")),
    ("task", lambda w: w.lua.globals().put(w.pack["tasks"]["address"] + w.pack["tasks"]["func_offset"], 0x08000001, 4)),
    ("native", lambda w: w.lua.execute("idle = false")),
    ("pointer", lambda w: w.lua.globals().put(w.pack["pointers"]["gSaveBlock1Ptr"]["address"], 2, 4)),
])
def test_overworld_non_predicate_clauses_unchanged(key, break_it):
    w = World()
    break_it(w)
    ok, why, clauses = w.check_reason("overworld")
    assert ok is False and clauses == [key]


def test_unknown_reason_refuses_by_name():
    w = World()
    ok, why, clauses = w.check_reason("memorial_rename")
    assert ok is False and clauses == ["reason"] and "memorial_rename" in why


BATTLE_KEYS = ["battle_main_func", "battle_comm_0", "battle_exec_flags_input", "battle_input_controller",
               "battle_not_link", "battle_engine_loaded", "battle_outcome_open"]
RR_BATTLE_KEYS = ["battle_main_func", "battle_comm_0", "battle_not_link", "battle_engine_loaded",
                  "battle_outcome_open"]


@pytest.mark.parametrize("title,kind,keys", [
    ("firered", "clean", BATTLE_KEYS),
    ("leafgreen", "clean", BATTLE_KEYS),
    ("radical_red", "companion", RR_BATTLE_KEYS),
])
def test_battle_input_accepts_and_names_each_broken_clause(title, kind, keys):
    w = World(title, kind)
    for reason in ("battle_faint", "battle_commit"):
        ok, why, clauses = w.check_reason(reason, {"battler": 0})
        assert ok is True and clauses == [] and reason in why
    for name in keys:
        spec = next(c for c in w.pack["battle"]["clauses"] if c["name"] == name)
        w2 = World(title, kind)
        if spec["compare"] == "nonzero":
            w2.lua.globals().put(spec["address"] + spec.get("offset", 0), 0, spec["width"])
        elif spec.get("mask"):
            w2.lua.globals().put(spec["address"] + spec.get("offset", 0), spec["mask"], spec["width"])
        else:
            w2.lua.globals().put(spec["address"] + spec.get("offset", 0), spec["expect"] ^ 1, spec["width"])
        ok, why, clauses = w2.check_reason("battle_faint")
        assert ok is False and clauses == [name] and name in why


# ── C4-BW: the battle_faint window is the PARKED action menu, not "exec flags == 0" ────────────
# pret: STATE_BEFORE_ACTION_CHOSEN emits CHOOSE_ACTION and MarkBattlerForControllerExec(0) sets
# bit 0 (battle_main.c:3133-3135, battle_util.c:185-191); only PlayerBufferExecCompleted clears
# it, once the player has chosen (battle_controller_player.c:186-200). The engine values below
# come from the title's own .sym (never the pack under test), so the old pack is falsified.
def pret_syms(title):
    """{name: [addresses in .sym order]} -- every spelling of a static name."""
    out = {}
    for line in (ROOT / "data/gen3/pret" / f"poke{title}.sym").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[1] in ("l", "g"):
            out.setdefault(parts[3], []).append(int(parts[0], 16))
    return out


def battle_world(title, comm, flags, controller):
    """A FR/LG world at HandleTurnActionSelectionState with battler 0 in the given state."""
    w = World(title, "clean")
    s, g = pret_syms(title), w.lua.globals()
    g.put(s["gBattleCommunication"][0], comm, 1)
    g.put(s["gBattleControllerExecFlags"][0], flags, 4)
    g.put(s["gBattlerControllerFuncs"][0], controller | 1, 4)  # u32 Thumb pointers, battler 0 first
    return w


def player(title, name):
    """The player controller's spelling (battle_controller_player.o links first)."""
    return pret_syms(title)[name][0]


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_battle_faint_admits_the_parked_action_menu(title):
    w = battle_world(title, 1, 1, player(title, "HandleInputChooseAction"))
    ok, why, clauses = w.check_reason("battle_faint")
    assert ok is True and clauses == [], why


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
@pytest.mark.parametrize("state,comm,flags,controller,refused_by", [
    # the frame after A: the choice sits in gBattleBufferB, flags clear, controller back to run
    ("post_choice", 1, 0, lambda t: player(t, "PlayerBufferRunCommand"),
     ["battle_exec_flags_input", "battle_input_controller"]),
    ("move_submenu", 2, 1, lambda t: player(t, "HandleInputChooseMove"),
     ["battle_comm_0", "battle_input_controller"]),
    ("target_menu", 2, 1, lambda t: player(t, "HandleInputChooseTarget"),
     ["battle_comm_0", "battle_input_controller"]),
    ("party_menu", 2, 1, lambda t: player(t, "WaitForMonSelection"),
     ["battle_comm_0", "battle_input_controller"]),
    ("bag", 2, 1, lambda t: player(t, "CompleteWhenChoseItem"),
     ["battle_comm_0", "battle_input_controller"]),
    ("menu_draw", 1, 1, lambda t: player(t, "HandleChooseActionAfterDma3"),
     ["battle_input_controller"]),
    # Teachy TV: Pokedude's own HandleInputChooseAction, gPlayerParty swapped out (teachy_tv.c:1178)
    ("pokedude", 1, 1, lambda t: pret_syms(t)["HandleInputChooseAction"][-1],
     ["battle_input_controller"]),
    # doubles: battler 2 is asked only once battler 0 is confirmed (comm 4); flags = bit 2
    ("doubles_battler2", 4, 4, lambda t: player(t, "PlayerBufferRunCommand"),
     ["battle_comm_0", "battle_exec_flags_input", "battle_input_controller"]),
])
def test_battle_faint_refuses_every_other_battler0_state(title, state, comm, flags, controller, refused_by):
    ok, why, clauses = battle_world(title, comm, flags, controller(title)).check_reason("battle_faint")
    assert ok is False and clauses == refused_by, (state, clauses)


def test_rr_battle_window_is_unchanged_and_fail_closed():
    """RR keeps flags == 0 until its own gBattlerControllerFuncs / CFRU pins exist."""
    w = World("radical_red", "companion")
    names = [c["name"] for c in w.pack["battle"]["clauses"]]
    assert "battle_input_controller" not in names and "battle_exec_flags_input" not in names
    flags = next(c for c in w.pack["battle"]["clauses"] if c["name"] == "battle_exec_flags_idle")
    assert flags["expect"] == 0
    w.lua.globals().put(flags["address"], 1, 4)          # the parked menu stays refused on RR
    ok, why, clauses = w.check_reason("battle_faint")
    assert ok is False and clauses == ["battle_exec_flags_idle"]


def test_battle_commit_guard_is_named_and_fail_closed():
    """The guard reads gBattleCommunication[battler]; battler 0 shares the byte with the
    battle_comm_0 clause, so the guard-only cases use battler 2."""
    w = World("firered", "clean")
    guard = w.pack["battle"]["commit_guard"]
    assert w.check_reason("battle_commit", {"battler": 2})[0] is True
    w.lua.globals().put(guard["address"] + guard.get("offset", 0) + 2, 3, guard["width"])
    ok, why, clauses = w.check_reason("battle_commit", {"battler": 2})
    assert ok is False and clauses == ["battle_commit_guard"] and "committed" in why
    for bad in (None, -1, 4, 1.5, "2"):
        ok, why, clauses = w.check_reason("battle_commit", {"battler": bad})
        assert ok is False and clauses == ["battle_commit_guard"], bad
    # a non-committed battler must not be refused by the guard
    assert w.check_reason("battle_faint", {"battler": 4})[0] is True


def test_native_clauses_and_attribution():
    w = World("radical_red", "companion")
    n = w.pack["native"]
    ok, why, clauses = w.check_reason("native")
    assert ok is True and clauses == []
    w2 = World("radical_red", "companion")
    w2.lua.globals().put(n["base"] + n["status_off"], n["busy"], 2)
    ok, why, clauses = w2.check_reason("native")
    assert ok is False and clauses == ["native_idle"] and "busy" in why
    w3 = World("radical_red", "companion")
    w3.lua.globals().put(n["base"] + n["opcode_off"], 16, 2)
    assert w3.check_reason("native")[2] == ["native_idle"]
    w4 = World("radical_red", "companion")
    w4.lua.globals().put(n["base"], n["sig"] ^ 1, 4)
    assert w4.check_reason("native")[2] == ["native_present"]
    w5 = World("radical_red", "companion")
    w5.lua.globals().put(n["info"] + n["info_ack_off"], 0, 1)
    assert w5.check_reason("native")[2] == ["native_idle"]


@pytest.mark.parametrize("title,kind", [("firered", "clean"), ("radical_red", "clean")])
def test_native_absent_or_clean_artifact_refuses_by_name(title, kind):
    w = World(title, kind)
    ok, why, clauses = w.check_reason("native")
    assert ok is False and clauses == ["native_present"]


def test_sound_clauses_and_attribution():
    w = World("firered", "clean")
    snd = w.pack["sound"]
    player = snd["player_se1"]["address"]
    ok, why, clauses = w.check_reason("sound")
    assert ok is True and clauses == []
    w2 = World("firered", "clean")
    w2.lua.globals().put(player + snd["ident_off"], snd["ident_magic"] ^ 1, 4)
    ok, why, clauses = w2.check_reason("sound")
    assert ok is False and clauses == ["sound_player_ready"]
    w3 = World("firered", "clean")
    w3.lua.globals().put(player + snd["tracks_off"], 0x02000000, 4)   # not IWRAM
    assert w3.check_reason("sound")[2] == ["sound_addresses_in_iwram"]
    # an explicit player/track from the caller wins over the pack's static one
    w4 = World("firered", "clean")
    w4.lua.globals().put(0x03006000 + snd["ident_off"], snd["ident_magic"], 4)
    assert w4.check_reason("sound", {"player": 0x03006000, "track": 0x03007000})[0] is True
    # the RR pack carries no static player: the caller must resolve one
    rr = World("radical_red", "companion")
    assert rr.check_reason("sound")[2] == ["sound_player_ready"]
    rr.lua.globals().put(0x03006000 + rr.pack["sound"]["ident_off"], rr.pack["sound"]["ident_magic"], 4)
    assert rr.check_reason("sound", {"player": 0x03006000, "track": 0x03007000})[0] is True


def test_writes_arm_passes_args_through():
    """writes:arm(reason, allow, args) must reach safety:check with the args (the commit guard)."""
    w = World("firered", "clean")
    g = w.lua.globals()
    guard = w.pack["battle"]["commit_guard"]
    g.put(guard["address"] + guard.get("offset", 0) + 1, 3, guard["width"])   # battler 1 = committed
    g.deps.safety = w.safety
    module = w.lua.execute((ROOT / "lua/gen3/writes.lua").read_text(encoding="utf-8"))
    writer = module.new(g.deps)
    with pytest.raises(lupa.LuaError, match="committed past the guard"):
        writer.arm(writer, "battle_commit", w.lua.eval("function() return true end"),
                   w.lua.table_from({"battler": 1}, recursive=True))
    g.put(guard["address"] + guard.get("offset", 0) + 1, 1, guard["width"])
    writer.arm(writer, "battle_commit", w.lua.eval("function() return true end"),
               w.lua.table_from({"battler": 1}, recursive=True))
    writer.write_u16(writer, 0x02024284 + 0x56, 0)
    assert len(g.writes) == 2
