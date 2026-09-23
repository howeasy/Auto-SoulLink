"""Pack-driven negative controls; no emulator or ROM required."""
import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
ROOT = Path(__file__).resolve().parents[2]


def committed_pack(title):
    folder = "gen3_rr" if title == "radical_red" else "gen3_frlg"
    return json.loads((ROOT / "data/games" / folder / "write_checkpoint.json").read_text())[title]


class World:
    def __init__(self, title="radical_red", kind="companion", pack=None):
        self.pack = committed_pack(title) if pack is None else pack
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
                                  "palette_fade_active", "script_context_status",
                                  "soft_reset_disabled"])
def test_each_forbidden_state(name):
    w = World()
    p = w.pack["predicates"][name]
    w.lua.globals().put(p["address"] + p["offset"], p.get("mask", p["expect"] ^ 1), p["width"])
    assert not w.check()


def test_two_failed_predicates_report_the_same_reason_regardless_of_pairs_order():
    """C4-ORDER falsifier: Lua's pairs() traversal order is unspecified, and overworld's
    predicate loop (safety.lua ~line 69) picks its 'first failure' reason straight from that
    order. This swaps in a controlled-order pairs() (ascending vs descending key sort) so
    enumeration order is the ONLY thing that varies between the two runs -- exactly the axis
    real pairs() leaves unspecified, without depending on any particular Lua build's hash
    behaviour. Before the fix the reported reason flips between 'forbidden state:
    palette_fade_active' and 'forbidden state: script_context_status' depending on which
    order is used; after the fix (ipairs over the module's fixed predicate list) the reason
    is the same regardless of how pairs() would have ordered them."""
    w = World()
    for p_name in ("palette_fade_active", "script_context_status"):
        p = w.pack["predicates"][p_name]
        w.lua.globals().put(p["address"] + p["offset"], p.get("mask", p["expect"] ^ 1), p["width"])
    w.lua.execute("""
        local real_pairs = pairs
        local function controlled(order)
            return function(t)
                local keys = {}
                for k in real_pairs(t) do keys[#keys + 1] = k end
                table.sort(keys, function(a, b)
                    if order == "asc" then return tostring(a) < tostring(b) else return tostring(a) > tostring(b) end
                end)
                local i = 0
                return function()
                    i = i + 1
                    if keys[i] == nil then return nil end
                    return keys[i], t[keys[i]]
                end
            end
        end
        asc_pairs = controlled("asc")
        desc_pairs = controlled("desc")
    """)
    g = w.lua.globals()
    reasons = set()
    for order_pairs in (g.asc_pairs, g.desc_pairs):
        g.pairs = order_pairs
        ok, why, clauses = w.check_reason("overworld")
        assert ok is False and set(clauses) >= {"palette_fade_active", "script_context_status"}, (why, clauses)
        reasons.add(why)
    assert len(reasons) == 1, reasons


def test_pairs_override_assumption_still_holds():
    """The falsifier above only works because safety.lua resolves `pairs` as a plain global
    (no `local pairs = pairs` alias) and the predicate loop walks the module's fixed
    `predicates` list via ipairs. Pin both, so a future refactor that shadows `pairs` locally
    doesn't silently turn the falsifier above into a no-op."""
    src = (ROOT / "lua/gen3/safety.lua").read_text(encoding="utf-8")
    assert "local pairs" not in src, \
        "safety.lua now aliases pairs locally; the pairs-order falsifier above needs updating"
    assert "ipairs(predicates)" in src, "predicate loop no longer walks the module's fixed list"


def test_extra_predicate_not_in_the_module_list_still_refuses():
    """C4-ORDER review fix (OMP ACCEPT-WITH-FIXES): switching the predicate loop to
    ipairs(predicates) means a pack predicate NOT in the module's list is never visited by that
    loop -- so with no reverse check it would be silently skipped (never evaluated, never
    refused) instead of counted as an unknown predicate. Red on dc855dda (admitted); green once
    the preamble asserts every pack.predicates name is in the module's known set."""
    w = World()
    pack = dict(w.pack)
    pack["predicates"] = dict(w.pack["predicates"])
    pack["predicates"]["zz_extra_predicate"] = {"address": 0x02020000, "offset": 0, "width": 1, "expect": 0}
    module = w.lua.execute((ROOT / "lua/gen3/safety.lua").read_text(encoding="utf-8"))
    safety = module.new(w.lua.table_from(pack, recursive=True), w.lua.globals().deps, "companion")
    ok, why = safety.check(safety, None)
    assert ok is False, why
    assert list(safety.last_clauses.values()) == ["pack"], (why, list(safety.last_clauses.values()))


def test_radical_red_extra_anchor_saveblocks_setter_is_verified():
    """radical_red's pack carries an extra ROM anchor (saveblocks_setter) beyond the module's
    fixed `anchors` list; sorted_pairs(pack.anchors) must still verify every key present in the
    pack, not just the module's five, mirroring the predicate coverage guard above."""
    w = World("radical_red", "companion")
    anchor = w.pack["anchors"]["saveblocks_setter"]
    good = bytes.fromhex(anchor["expected_hex"]["companion"])[0]
    w.lua.globals().rom[anchor["rom_offset"]] = good ^ 0xFF
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
    del w.pack["predicates"]["link_callback"]
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
                  "script_context_status", "soft_reset_disabled"]


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
RR_BATTLE_KEYS = BATTLE_KEYS  # C5-RR-BW: the FR/LG seven


@pytest.mark.parametrize("title,kind,keys", [
    ("firered", "clean", BATTLE_KEYS),
    ("leafgreen", "clean", BATTLE_KEYS),
    ("radical_red", "companion", RR_BATTLE_KEYS),
])
def test_battle_input_accepts_and_names_each_broken_clause(title, kind, keys):
    w = World(title, kind)
    for reason in ("battle_faint", "battle_commit"):
        ok, why, clauses = w.check_reason(reason, {"battler": 0})
        if reason == "battle_commit" and "commit_hold" in w.pack["battle"]:  # RR holds commits
            assert ok is False and clauses == ["battle_commit_hold"], clauses
            continue
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


# ── C5-RR-BW: RR's window is the parked menu too (docs/gen3/research/rr_battle_tuple_2026-09-23.md) ──
# Addresses and controller values are the spec's byte facts, never read from the pack under test:
# gBattleCommunication 0x02023E82, gBattleControllerExecFlags 0x02023BC8, gBattlerControllerFuncs
# 0x03004FE0.  CFRU's input handler keeps exec bit 0 set while parked and clears it inside the
# commit call, which also stores PlayerBufferRunCommand (0x0802E3B5).
def rr_battle_world(kind, comm, flags, controller, pack=None):
    w = World("radical_red", kind, pack)
    g = w.lua.globals()
    g.put(0x02023E82, comm, 1)
    g.put(0x02023BC8, flags, 4)
    g.put(0x03004FE0, controller, 4)
    return w


@pytest.mark.parametrize("kind", ["clean", "companion"])
def test_rr_battle_faint_admits_the_parked_action_menu(kind):
    ok, why, clauses = rr_battle_world(kind, 1, 1, 0x0802E439).check_reason("battle_faint")
    assert ok is True and clauses == [], why


@pytest.mark.parametrize("kind", ["clean", "companion"])
@pytest.mark.parametrize("state,comm,flags,controller,refused_by", [
    ("commit_frame", 1, 0, 0x0802E3B5, ["battle_exec_flags_input", "battle_input_controller"]),
    ("menu_draw", 1, 1, 0x08032B95, ["battle_input_controller"]),
    ("l_subui_open", 1, 1, 0x090A9E41, ["battle_input_controller"]),
    # post-L-window spelling: fail-closed until safety.lua grows an `in` compare (spec §5)
    ("l_subui_returned", 1, 1, 0x090A9EA1, ["battle_input_controller"]),
    ("opponent_bit_pending", 1, 3, 0x0802E439, ["battle_exec_flags_input"]),
    ("doubles_battler2", 4, 4, 0x0802E3B5,
     ["battle_comm_0", "battle_exec_flags_input", "battle_input_controller"]),
    ("bit24_after_commit", 1, 0, 0x090ACD8D, ["battle_exec_flags_input", "battle_input_controller"]),
])
def test_rr_battle_faint_refuses_every_other_battler0_state(kind, state, comm, flags, controller, refused_by):
    ok, why, clauses = rr_battle_world(kind, comm, flags, controller).check_reason("battle_faint")
    assert ok is False and clauses == refused_by, (state, clauses)


@pytest.mark.parametrize("kind", ["clean", "companion"])
@pytest.mark.parametrize("hold", [True, False], ids=["committed_pack", "hold_lifted"])
def test_rr_battle_commit_refuses_the_commit_frame(kind, hold):
    """comm 1 < 3 passes the guard; the refusal must come from the new clauses, with or without
    the pack's battle_commit hold (REV-C5-RR-BW-FIX 2)."""
    pack = committed_pack("radical_red")
    if not hold:
        del pack["battle"]["commit_hold"]
    w = rr_battle_world(kind, 1, 0, 0x0802E3B5, pack)
    ok, why, clauses = w.check_reason("battle_commit", {"battler": 0})
    expect = ["battle_commit_hold"] * hold + ["battle_exec_flags_input", "battle_input_controller"]
    assert ok is False and clauses == expect, clauses


@pytest.mark.parametrize("kind", ["clean", "companion"])
def test_rr_battle_commit_is_held_at_the_parked_menu(kind):
    """REV-C5-RR-BW-FIX 2: at the admissible parked menu the hold is the ONLY failing clause;
    battle_faint there admits. FR/LG carry no hold."""
    w = rr_battle_world(kind, 1, 1, 0x0802E439)
    ok, why, clauses = w.check_reason("battle_commit", {"battler": 0})
    assert ok is False and clauses == ["battle_commit_hold"] and "0x090AA114" in why
    assert w.check_reason("battle_faint")[0] is True
    assert "commit_hold" not in committed_pack("firered")["battle"]
    assert "commit_hold" not in committed_pack("leafgreen")["battle"]


# ── REV-C5-RR-BW-FIX 1: a pack missing a battle clause refuses as {"pack"}, never admits ───────
# Dropping the controller pin left exec == 1 alone, which admits the draw frame and both L-window
# controllers; an empty clause list admitted every frame.  safety.lua now checks the battle clause
# SET both ways (like the overworld predicates) before evaluating anything.
def pack_without(title, drop):
    """The committed pack with the named battle clauses removed (None = every clause)."""
    pack = committed_pack(title)
    clauses = pack["battle"]["clauses"]
    pack["battle"]["clauses"] = [] if drop is None else [c for c in clauses if c["name"] not in drop]
    return pack


RR_NON_PARKED = [("menu_draw", 1, 1, 0x08032B95), ("l_subui_open", 1, 1, 0x090A9E41),
                 ("l_subui_returned", 1, 1, 0x090A9EA1), ("commit_frame", 1, 0, 0x0802E3B5)]


@pytest.mark.parametrize("kind", ["clean", "companion"])
@pytest.mark.parametrize("drop", [("battle_input_controller",), None], ids=["pin_removed", "empty"])
@pytest.mark.parametrize("state,comm,flags,controller", RR_NON_PARKED)
def test_rr_incomplete_battle_block_refuses_as_pack(kind, drop, state, comm, flags, controller):
    w = rr_battle_world(kind, comm, flags, controller, pack_without("radical_red", drop))
    for reason in ("battle_faint", "battle_commit"):
        ok, why, clauses = w.check_reason(reason, {"battler": 0})
        assert ok is False and clauses == ["pack"], (state, reason, clauses)


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
@pytest.mark.parametrize("drop", [("battle_input_controller",), None], ids=["pin_removed", "empty"])
@pytest.mark.parametrize("state,flags,controller", [
    ("menu_draw", 1, "HandleChooseActionAfterDma3"), ("post_choice", 0, "PlayerBufferRunCommand")])
def test_frlg_incomplete_battle_block_refuses_as_pack(title, drop, state, flags, controller):
    w = World(title, "clean", pack_without(title, drop))
    s, g = pret_syms(title), w.lua.globals()
    g.put(s["gBattleCommunication"][0], 1, 1)
    g.put(s["gBattleControllerExecFlags"][0], flags, 4)
    g.put(s["gBattlerControllerFuncs"][0], player(title, controller) | 1, 4)
    ok, why, clauses = w.check_reason("battle_faint")
    assert ok is False and clauses == ["pack"], (state, clauses)


@pytest.mark.parametrize("title,kind", [("firered", "clean"), ("radical_red", "companion")])
@pytest.mark.parametrize("mutation", ["unknown_name", "duplicate", "bad_compare", "no_expect",
                                      "bad_version", "no_battle"])
def test_malformed_battle_block_refuses_as_pack_instead_of_raising(title, kind, mutation):
    pack = committed_pack(title)
    block = pack["battle"]
    clauses = block["clauses"]
    if mutation == "unknown_name":
        clauses.append(dict(clauses[0], name="battle_extra"))
    elif mutation == "duplicate":
        clauses.append(dict(clauses[1]))
    elif mutation == "bad_compare":
        clauses[1]["compare"] = "lt"
    elif mutation == "no_expect":
        del clauses[1]["expect"]
    elif mutation == "bad_version":
        block["version"] = "gen3-battle-v0"
    if mutation == "no_battle":
        pack.pop("battle")
    # the World fixture seeds RAM from the committed block; the mutated pack goes to safety.lua
    w = World(title, kind)
    module = w.lua.execute((ROOT / "lua/gen3/safety.lua").read_text(encoding="utf-8"))
    w.safety = module.new(w.lua.table_from(pack, recursive=True), w.lua.globals().deps, kind)
    ok, why, clauses = w.check_reason("battle_faint")
    assert ok is False and clauses == ["pack"], (mutation, why)


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


# -- C4-SAVE: the two pointers pret never resets (live center_controls_gen3 r9, f926a8b4) ----------
# Engine values come from the title's own .sym, never from the pack under test, so a pack that
# still reads gLinkCallback / sSaveDialogCB is falsified.  RR reads the FireRed symbols (its
# pack is proven against them byte-for-byte by tools/gen_gen3_write_checkpoint.py).
SAVE_LINK_TITLES = [("firered", "clean"), ("leafgreen", "clean"),
                    ("radical_red", "clean"), ("radical_red", "companion")]


def engine(title):
    s = pret_syms("firered" if title == "radical_red" else title)
    return {name: v[0] for name, v in s.items()}


def put_active_task(w, fn):
    """Occupy the first free gTasks slot with an active task running fn."""
    t, g = w.pack["tasks"], w.lua.globals()
    for i in range(t["count"]):
        base = t["address"] + i * t["struct_size"]
        if g.mem[base + t["is_active_offset"]] == 0:
            g.put(base + t["func_offset"], fn | 1, 4)
            g.put(base + t["is_active_offset"], 1, 1)
            return
    raise AssertionError("no free task slot")


@pytest.mark.parametrize("title,kind", SAVE_LINK_TITLES)
def test_stale_link_callback_with_the_link_closed_is_admitted(title, kind):
    """A cancelled no-partner Cable Club link: CloseLink (link.c:419-426) clears sLinkOpen but
    leaves gLinkCallback on LinkCB_RequestPlayerDataExchange, which only LinkMain2 runs, and only
    while sLinkOpen (:512-523).  Live FR r9: link_callback=0x0800A721 with sLinkOpen=0."""
    w, s = World(title, kind), engine(title)
    g = w.lua.globals()
    g.put(s["gLinkCallback"], s["LinkCB_RequestPlayerDataExchange"] | 1, 4)
    g.put(s["sLinkOpen"], 0, 1)
    ok, why, clauses = w.check_reason("overworld")
    assert ok is True and clauses == [], (why, clauses)


@pytest.mark.parametrize("title,kind", SAVE_LINK_TITLES)
@pytest.mark.parametrize("callback", ["LinkCB_RequestPlayerDataExchange", None])
def test_an_open_cable_link_is_refused(title, kind, callback):
    """OpenLink's cable branch (link.c:390-394) sets sLinkOpen and gLinkCallback together; the
    callback clears itself (:1128-1134) long before the partner's player data is in, so the
    None case is a live link that no pointer clause saw (gReceivedRemoteLinkPlayers still 0)."""
    w, s = World(title, kind), engine(title)
    g = w.lua.globals()
    g.put(s["gLinkCallback"], s[callback] | 1 if callback else 0, 4)
    g.put(s["sLinkOpen"], 1, 1)
    ok, why, clauses = w.check_reason("overworld")
    assert ok is False and clauses == ["link_callback"], (why, clauses)


@pytest.mark.parametrize("title,kind", SAVE_LINK_TITLES)
@pytest.mark.parametrize("dialog_cb", ["SaveDialogCB_DoSave", "SaveDialogCB_ReturnSuccess"])
def test_a_live_start_menu_save_is_refused_without_the_dialog_pointer(title, kind, dialog_cb):
    """Every frame of a START-menu save runs inside Task_StartMenuHandleInput (start_menu.c:
    378-394, destroyed only when StartCB_Save2 returns TRUE :583-600) under the lock ShowStartMenu
    took (:405, released at :586/:598 in that same call).  TrySavingData runs synchronously inside
    SaveDialogCB_DoSave (:791-805).  The refusal must not need sSaveDialogCB."""
    w, s = World(title, kind), engine(title)
    g = w.lua.globals()
    g.put(s["sSaveDialogCB"], s[dialog_cb] | 1, 4)
    g.put(s["sLockFieldControls"], 1, 1)
    put_active_task(w, s["Task_StartMenuHandleInput"])
    ok, why, clauses = w.check_reason("overworld")
    assert ok is False and {"task", "field_controls_locked"} <= set(clauses), (why, clauses)


@pytest.mark.parametrize("title,kind", SAVE_LINK_TITLES)
def test_a_live_script_save_is_refused_without_the_dialog_pointer(title, kind):
    """EventScript_AskSaveGame (std_msgbox.inc:57-60): special Field_AskSaveTheGame creates
    task50_save_game (start_menu.c:620-626), then waitstate parks the script CONTEXT_WAITING
    (scrcmd.c:127-131, script.c:360-363) until the task's ScriptContext_Enable (:651-653)."""
    w, s = World(title, kind), engine(title)
    g = w.lua.globals()
    g.put(s["sSaveDialogCB"], s["SaveDialogCB_DoSave"] | 1, 4)
    g.put(s["sLockFieldControls"], 1, 1)
    g.put(s["sGlobalScriptContextStatus"], 1, 1)
    put_active_task(w, s["task50_save_game"])
    ok, why, clauses = w.check_reason("overworld")
    assert ok is False and {"task", "field_controls_locked", "script_context_status"} <= set(clauses), \
        (why, clauses)


@pytest.mark.parametrize("title,kind", SAVE_LINK_TITLES)
def test_a_finished_save_leaves_the_field_writable(title, kind):
    """After a save sSaveDialogCB rests on SaveDialogCB_ReturnSuccess forever: every assignment
    (start_menu.c:608-842) is non-NULL.  Live LG r9: 0x0806F9E1 on an idle field, held 404x."""
    w, s = World(title, kind), engine(title)
    w.lua.globals().put(s["sSaveDialogCB"], s["SaveDialogCB_ReturnSuccess"] | 1, 4)
    ok, why, clauses = w.check_reason("overworld")
    assert ok is True and clauses == [], (why, clauses)
