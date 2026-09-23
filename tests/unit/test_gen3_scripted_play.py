"""gen3_scripted_play.lua's LEGS table (card gen3-P3-C3-5).

Pure-Lua checks through lupa: no emulator, no ROM. The script's top-level code only builds the
LEGS table (closures aren't called), so it loads with SLINK_ROOT set and nothing else stubbed —
same shape as test_gen1_scripted_host.py's `dofile` pattern. This does NOT run any leg; it
checks the table's SHAPE (site-kind coverage, citation format, no frame-count terminal), which
is exactly what a runtime BizHawk gate cannot check for itself before it burns emulator minutes.
"""
from __future__ import annotations

import os
import re

import pytest
from lupa import LuaError, LuaRuntime

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_SCRIPT = os.path.join(_REPO, "lua", "tests", "gen3_scripted_play.lua")
with open(_SCRIPT, encoding="utf-8") as _f:
    _SCRIPT_SRC = _f.read()

# docs/gen3_engine_sites.md "PINNED / UNVERIFIED matrix" — the 23 recognized site kinds.
_KNOWN_KINDS = {
    "frame_control", "battle_begin", "battle_end", "faint", "capture_wild", "mon_given",
    "pc_move", "whiteout", "map_load", "evolve_species_store", "trade_done", "save",
    "poison_faint", "borrowed_party", "nature_change", "pc_deposit", "pc_withdraw",
    "pc_box_place", "pc_release_begin", "pc_release", "trade_evolve_species_store",
    "trade_begin", "poison_hp_before",
}

# The card's required minimum coverage (a kind counts whether its leg is open or not — an open
# leg's citation stands in for the run not yet scripted).
_REQUIRED_MIN_COVERAGE = {
    "battle_begin", "battle_end", "faint", "capture_wild", "mon_given", "pc_move", "save",
    "map_load",
}
_EVOLVE_OR_TRADE = {"evolve_species_store", "trade_done"}

# A citation must point under one of these — same test as "is this an actual pret path". `lua/`
# and `include/` cover the handful of legs that cite this repo's own pinned RAM addresses
# (lua/games/gen3_frlge.lua) or pret's constants headers, alongside the map/source data.
# `docs/` covers the research notes and PHYSICAL receipts a pinned route is derived
# from; `patch/` covers a fact parsed out of the staged ROM with tools/gba_map.py.
_CITATION_ROOTS = ("data/maps", "data/layouts", "src/", "data/", "lua/", "include/",
                   "docs/", "patch/")

# Coordinate/map/counter/predicate terminal helpers gen3_scripted_play.lua actually uses.
_TERMINAL_HELPERS = (
    "G.pos", "G.map", "mapid(", "G.pred_ok", "G.pred(", "G.save_counter", "party_count(",
    "wait_for_map_change", "G.mash", "G.flash_domain", "in_battle(", "mash_a(", "lab_scene_var(",
    # the PC legs terminate on the KEYED party snapshot, read on the field after leaving the PC
    "party_snapshot(", "departed_key(", "survivors_intact(", "slot0_hp(",
    # route1_faint's own stop condition (gBattleResults.playerFaintCounter advancing)
    "player_faints(",
)


@pytest.fixture(scope="module")
def lua():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    return runtime


@pytest.fixture(scope="module")
def module(lua):
    os.environ.setdefault("SLINK_ROOT", _REPO.replace("\\", "/"))
    return lua.execute(f'return dofile("{_SCRIPT.replace(chr(92), "/")}")')


@pytest.fixture(scope="module")
def legs(module):
    return module.LEGS


def _py_list(lua_table):
    """A lupa table (1-based) as a Python list, however it was built."""
    return [lua_table[i] for i in range(1, len(lua_table) + 1)]


def test_the_script_loads_without_running_any_leg(legs):
    """dofile must not touch memory/emu/joypad at module scope — those are only reachable from
    inside a leg's run() closure, which this test never calls."""
    assert len(legs) >= 9


def test_every_leg_names_at_least_one_known_site_kind(legs):
    for i in range(1, len(legs) + 1):
        leg = legs[i]
        name = leg["name"]
        kinds = _py_list(leg["exercises"])
        assert kinds, f"leg {name!r} names no site kinds"
        unknown = [k for k in kinds if k not in _KNOWN_KINDS]
        assert not unknown, f"leg {name!r} names unknown kind(s) {unknown}"


def test_every_leg_carries_a_pret_citation(legs):
    for i in range(1, len(legs) + 1):
        leg = legs[i]
        name = leg["name"]
        sources = _py_list(leg["source"])
        assert sources, f"leg {name!r} has no source citations"
        for cite in sources:
            assert any(root in cite for root in _CITATION_ROOTS), (
                f"leg {name!r} citation {cite!r} does not point under data/maps, "
                f"data/layouts, src/ or data/"
            )


def test_required_site_kinds_are_covered_somewhere_in_the_union(legs):
    covered = set()
    for i in range(1, len(legs) + 1):
        covered |= set(_py_list(legs[i]["exercises"]))
    missing = _REQUIRED_MIN_COVERAGE - covered
    assert not missing, f"no leg (open or not) exercises {missing}"
    assert covered & _EVOLVE_OR_TRADE, "no leg exercises evolve_species_store or trade_done"


def test_open_legs_are_marked_and_give_a_reason(legs):
    saw_open = False
    for i in range(1, len(legs) + 1):
        leg = legs[i]
        if leg["open"]:
            saw_open = True
            assert leg["open_reason"], f"leg {leg['name']!r} is open with no reason"
    assert saw_open, "expected at least one open leg (catch/PC/faint/gift/trade/evolution)"


def test_pinned_legs_are_not_open(legs):
    pinned = {
        "starter", "rival_battle", "leave_lab_for_parcel", "parcel_fetch", "parcel_deliver",
        "route1_catch", "route1_faint", "viridian_pc_deposit_withdraw", "save",
    }
    seen = set()
    for i in range(1, len(legs) + 1):
        leg = legs[i]
        if leg["name"] in pinned:
            seen.add(leg["name"])
            assert not leg["open"], f"leg {leg['name']!r} should be pinned (run), not open"
    assert seen == pinned


def test_leg_names_are_unique(legs):
    names = [legs[i]["name"] for i in range(1, len(legs) + 1)]
    assert len(names) == len(set(names))


# ── source-level check: no run body ends on a bare frame count ─────────────────────────────────
# A runtime frame BUDGET (G.advance()'s runaway cap, or a bounded `for _ = 1, N do ... end` that
# polls a coordinate/predicate every iteration) is fine and used throughout; what's disallowed is
# a leg whose *only* stop condition is "N frames elapsed" with no coordinate/map/counter/
# predicate check inside the loop. Every `run = function` body in the source is required to
# reference at least one of the terminal helpers (open legs, which only log and return, are
# exempt — they have no loop to terminate).

_RUN_BODY_RE = re.compile(r"run = function\(cp\)(.*?)\n\}", re.DOTALL)


def test_no_run_body_terminates_on_a_bare_frame_count():
    bodies = _RUN_BODY_RE.findall(_SCRIPT_SRC)
    assert len(bodies) >= 9, "expected one run body per leg"
    for body in bodies:
        is_open_stub = "G.phase(" in body and "OPEN" in body and "for " not in body
        if is_open_stub:
            continue
        # route1_catch's run() delegates its hunt+catch loop (shared with resume()) to a named
        # function; test_route1_catch_loop_carries_a_terminal_helper checks THAT body instead of
        # this thin wrapper.
        if "_loop(cp)" in body:
            continue
        assert any(h in body for h in _TERMINAL_HELPERS), (
            "a non-open leg's run body has no coordinate/map/counter/predicate terminal helper:\n"
            + body
        )


# ── polarity + address-arithmetic regressions (Codex review cx-378ce251) ───────────────────────


def test_lab_scene_var_offset_arithmetic(module):
    """VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB=0x4055 (pret include/constants/vars.h:137),
    SaveBlock1.vars[] at SB1+0x1000 (pret include/global.h:791), each entry a u16 -> byte offset
    0x1000 + (0x4055-0x4000)*2 == 0x10AA (the coordinator's arithmetic, checked independently)."""
    assert module.LAB_SCENE_VAR_OFFSET == 0x10AA


@pytest.fixture
def stubbed_module():
    """A SEPARATE runtime (not the shared `lua`/`module` fixtures, which never stub `memory`)
    with just enough of the BizHawk `memory` API to exercise `in_battle(cp)` for real: a plain
    dict-backed byte store, keyed by absolute address."""
    os.environ.setdefault("SLINK_ROOT", _REPO.replace("\\", "/"))
    runtime = LuaRuntime(unpack_returned_tuples=True)
    store: dict[int, int] = {}

    def read_u8(addr, _domain=None):
        return store.get(int(addr), 0)

    runtime.globals().memory = runtime.table(
        read_u8=read_u8, read_u16_le=read_u8, read_u32_le=read_u8,
    )
    mod = runtime.execute(f'return dofile("{_SCRIPT.replace(chr(92), "/")}")')
    return mod, store, runtime


def test_in_battle_polarity_wrapper(stubbed_module):
    """The pack row (data/games/gen3_frlg/write_checkpoint.json firered.predicates.in_battle) is
    expect=0, mask=2: G.pred_ok(cp,"in_battle") is TRUE exactly when the raw byte reads
    expect-equal, and that means NOT in a battle (Codex cx-378ce251). A fake pred whose raw byte
    equals `expect` must therefore make the wrapper read False (not in_battle); flipping the
    masked bit must make it read True (in_battle)."""
    module, store, runtime = stubbed_module
    address, offset, mask, expect = 0x02020000, 1081, 2, 0
    cp = runtime.table(predicates=runtime.table(
        in_battle=runtime.table(address=address, offset=offset, mask=mask, expect=expect, width=1),
    ))

    store[address + offset] = expect  # raw == expect -> pred_ok True -> NOT in battle
    assert module.in_battle(cp) is False

    store[address + offset] = mask  # masked bit set, raw != expect -> pred_ok False -> in battle
    assert module.in_battle(cp) is True


# ── lint: a Lua multi-return call (G.pos/G.map/obj0_pos) inside a string.format argument list
# must be LAST, or every following argument is dropped ("bad argument #N to format": PHYSICAL,
# three lane runs lost to this on 2026-09-21).
MULTI_RETURN = ("G.pos(cp)", "G.map(cp)", "obj0_pos()")


def _format_arg_lists(src: str):
    i = 0
    while True:
        i = src.find("string.format(", i)
        if i < 0:
            return
        depth, j = 0, i + len("string.format")
        while j < len(src):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield src[i:j + 1]
        i = j


@pytest.mark.parametrize("rel", [
    "lua/tests/gen3_scripted_play.lua", "lua/tests/gen3_rr_scripted_play.lua",
    "lua/tests/probe_gen3_battle_census.lua", "lua/tests/probe_gen3_exec_addr.lua",
    "lua/tests/probe_gen3_rr_bag.lua", "lua/tests/mkstate_gen3_rr_fill.lua",
    "lua/tests/gen3_fr_newgame_inputs.lua", "lua/tests/gen3_boot_check.lua",
])
def test_no_multi_return_call_mid_format_arguments(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
        src = fh.read()
    bad = []
    for call in _format_arg_lists(src):
        body = call[len("string.format("):-1]
        for name in MULTI_RETURN:
            k = body.find(name)
            while k >= 0:
                rest = body[k + len(name):].lstrip()
                if rest.startswith(","):
                    bad.append((name, " ".join(call[:80].split())))
                k = body.find(name, k + 1)
    assert not bad, bad


# -- connection arrivals (FR lane run 13) ------------------------------------------------------
# Crossing a map CONNECTION lands the player ON the destination's edge row, not one tile inside
# it: y=0 when walking off a map's bottom edge, y=height-1 when walking off its top. Two paths
# said y=1 and cost a lane run ("route1_north_to_south_edge: start tile (12,0) is not the path's
# from (12,1)"). This needs no ROM -- it is the rule itself, guarded.

ARRIVAL_ROW = {
    # path -> the row the player arrives on, having crossed a connection to get there
    "route1_north_to_south_edge": 0,    # Viridian City's down connection -> Route 1 top row
    "route1_edge_to_lab_door": 0,       # Route 1's down connection -> Pallet Town top row
    "route1_south_to_north_edge": 39,   # Pallet Town's up connection -> Route 1 bottom row
    "route1_south_to_grass_spot": 39,   # same arrival
    "route1_edge_to_mart_door": 39,     # Route 1's up connection -> Viridian City bottom row
    "route1_edge_to_pokecenter_door": 39,
}


def test_connection_arrival_paths_start_on_the_destination_edge_row(module):
    for name, row in ARRIVAL_ROW.items():
        entry = module.PATHS[name]
        assert entry["from"][2] == row, (
            f"{name} starts at y={entry['from'][2]}, but crossing a connection to get there "
            f"lands the player on row {row}"
        )


def test_the_two_route1_crossings_are_exact_mirrors(module):
    """Each pair walks the same corridor in opposite directions, so their step counts must
    match -- the y=0 fix added one Down to each, not a whole new route."""
    north = module.PATHS["route1_south_to_north_edge"]["dirs"]
    south = module.PATHS["route1_north_to_south_edge"]["dirs"]
    assert len(south) == len(north) + 1, "the southbound path should be the northbound one + 1"
    assert south[1] == "Down", "the extra step is the one off the arrival row"


# -- the grass hunt must RESUME the square, not restart it (Codex cx-bc675fa4) -----------------
# An encounter interrupts the loop wherever it fires. Restarting at step 1 from there walks off
# the band: interrupted at (13,37), a fresh "Right" goes to (14,37), which is not grass. The
# loop is a cycle, so resuming at the step the player is standing on is the fix.

_DELTA = {"Up": (0, -1), "Down": (0, 1), "Left": (-1, 0), "Right": (1, 0)}


def _square(module):
    loop = module.GRASS_LOOP
    return [loop[i] for i in range(1, len(loop) + 1)]


def test_the_grass_loop_is_a_closed_square_inside_the_band(module):
    x, y = module.GRASS_ORIGIN[1], module.GRASS_ORIGIN[2]
    assert (x, y) == (12, 37)
    seen = [(x, y)]
    for step in _square(module):
        x, y = x + _DELTA[step][0], y + _DELTA[step][1]
        seen.append((x, y))
    assert seen[-1] == (12, 37), "the loop must close"
    for tx, ty in seen:
        assert tx in (12, 13) and ty in (37, 38), f"({tx},{ty}) leaves the pinned grass band"


@pytest.mark.parametrize("interrupt_after", [1, 2, 3, 4])
def test_resuming_the_loop_after_an_interruption_stays_in_the_band(module, interrupt_after):
    """Two consecutive hunts, the first cut short at each edge of the square in turn. Resuming
    at the step the player stands on keeps every tile inside the band; restarting at step 1
    would not."""
    loop = _square(module)
    x, y = module.GRASS_ORIGIN[1], module.GRASS_ORIGIN[2]
    step = 0
    for _ in range(interrupt_after):                  # first hunt, interrupted
        d = loop[step % len(loop)]
        x, y = x + _DELTA[d][0], y + _DELTA[d][1]
        step += 1
    assert x in (12, 13) and y in (37, 38)
    for _ in range(len(loop) * 2):                    # second hunt, resuming
        d = loop[step % len(loop)]
        x, y = x + _DELTA[d][0], y + _DELTA[d][1]
        step += 1
        assert x in (12, 13) and y in (37, 38), (
            f"resuming after {interrupt_after} steps walked to ({x},{y}), off the grass band")


def test_the_loop_cursor_persists_across_calls_in_the_source():
    """The cursor has to outlive one hunt_encounter call, or "resume" means nothing."""
    assert "\nlocal grass_step = 1" in _SCRIPT_SRC, "grass_step must be file-scoped"
    body = _SCRIPT_SRC.split("local function hunt_encounter")[1].split("\nlocal ")[0]
    assert "grass_step = ((grass_step - 2)" in body, "the cursor must rewind on an encounter"


# ── route1_catch / route1_faint whiteout recovery (card gen3-P3-C3-18) ─────────────────────────
# Both legs own their own battle (hunt_encounter calls play.step with enc=false), so playlib's
# own whiteout detector never sees a displacement there; check_whiteout is this file's own copy
# of the same signal, and these legs must raise it and declare recover()/resume() or a whiteout
# just runs off the end of the leg looking like an ordinary loss.


def test_route1_legs_declare_recover_and_resume(legs):
    for i in range(1, len(legs) + 1):
        leg = legs[i]
        if leg["name"] in ("route1_catch", "route1_faint"):
            assert callable(leg["recover"]), f"{leg['name']} has no recover()"
            assert callable(leg["resume"]), f"{leg['name']} has no resume()"


def test_recover_helper_reuses_existing_paths_and_resets_the_grass_cursor():
    """recover_to_route1_grass must not invent a new BFS path (the file already has the two it
    needs) and must reset grass_step, or a resumed hunt starts mid-square from the fresh origin
    instead of the step a whiteout actually interrupted."""
    body = _SCRIPT_SRC.split("local function recover_to_route1_grass")[1].split(
        "\nlocal function heal_at_nurse")[0]
    assert "recover_to_pallet_town(cp)" in body
    assert '"town_start_to_oak_trigger"' in body
    assert '"route1_south_to_grass_spot"' in body
    assert "grass_step = 1" in body, "recovery must reset the grass loop cursor"


def test_route1_catch_waits_for_the_menu_witness_before_touching_the_action_menu():
    """ROOT CAUSE of FR run 18's fainted starter (and run 19's replay of the same class of bug):
    a Right press issued on a timer can land on the still-open 'Wild X appeared!'/'Go! X!' intro
    text and does nothing, so the cursor stays at its battle-start default (FIGHT) for the mash
    that follows. verify_fight_cursor (the engine witness, not a frame count) must appear BEFORE
    the Right press in source order, not after, and the tail must settle before judging a
    whiteout (resolve_battle_and_check_whiteout, not a bare check_whiteout call)."""
    body = _SCRIPT_SRC.split("local function route1_catch_loop")[1].split(
        "\nLEGS[#LEGS + 1] = {")[0]
    verify_at = body.index('verify_fight_cursor(cp, "route1_catch")')
    right_at = body.index('G.tap("Right", 3, 20)')
    assert verify_at < right_at, "the menu witness must be confirmed before Right selects BAG"
    assert "resolve_battle_and_check_whiteout(cp, 160)" in body


def test_route1_faint_run_checks_for_whiteout_after_each_battle():
    leg_src = _SCRIPT_SRC.split('name = "route1_faint"')[1].split(
        '\n-- ── leg: viridian_pc_deposit_withdraw')[0]
    assert "resolve_battle_and_check_whiteout(cp, 160)" in leg_src
    assert 'verify_fight_cursor(cp, "route1_faint")' in leg_src


@pytest.fixture
def emu_stubbed(request):
    """Like `stubbed_module`, plus the bare minimum G.phase needs (emu.framecount, console.log)
    so check_whiteout's logging call on the whiteout path doesn't blow up on a missing global —
    neither touches a file (M.phase only writes to `out`, which stays nil: G.open is never
    called here) or the emulator for real. Optional `savestate.save` (param-marked tests only),
    for save_battle_state_once. Returns (runtime, module, store, logged, save_calls).
    """
    os.environ.setdefault("SLINK_ROOT", _REPO.replace("\\", "/"))
    runtime = LuaRuntime(unpack_returned_tuples=True)
    store: dict[int, int] = {}

    runtime.globals().memory = runtime.table(
        read_u8=lambda a, *_: store.get(int(a), 0) & 0xFF,
        read_u16_le=lambda a, *_: store.get(int(a), 0) & 0xFFFF,
        read_u32_le=lambda a, *_: store.get(int(a), 0),
        read_s16_le=lambda a, *_: store.get(int(a), 0),
    )
    runtime.globals().emu = runtime.table(framecount=lambda: 0)
    logged: list[str] = []
    runtime.globals().console = runtime.table(log=lambda s: logged.append(str(s)))
    save_calls: list[str] = []
    runtime.globals().savestate = runtime.table(
        save=lambda path: (save_calls.append(path), True)[1])
    mod = runtime.execute(f'return dofile("{_SCRIPT.replace(chr(92), "/")}")')
    return runtime, mod, store, logged, save_calls


def _fake_cp(runtime, store, ptr_addr, sb1_addr, group, num):
    store[ptr_addr] = sb1_addr
    store[sb1_addr + 0x04] = group
    store[sb1_addr + 0x05] = num
    # Source-defined outdoor checkpoint -> Pallet house respawn.
    store[sb1_addr + 0x1C] = 3
    store[sb1_addr + 0x1D] = 0
    store[sb1_addr + 0x1E] = 255
    store[sb1_addr + 0x20] = 6
    store[sb1_addr + 0x22] = 8
    return runtime.table(pointers=runtime.table(
        gSaveBlock1Ptr=runtime.table(address=ptr_addr)))


def test_check_whiteout_raises_when_displaced_to_the_heal_map(emu_stubbed):
    runtime, module, store, logged, _ = emu_stubbed
    ptr_addr, sb1_addr = 0x03005008, 0x02020000
    # The outdoor Pallet checkpoint projects to the house (4.0), not the outdoor map.
    cp = _fake_cp(runtime, store, ptr_addr, sb1_addr, 4, 0)
    store[sb1_addr], store[sb1_addr + 2] = 8, 5
    with pytest.raises(LuaError):
        module.check_whiteout(cp, 3 * 256 + 19, 12, 37)  # before_map = Route1 (3.19)


def test_check_whiteout_does_not_raise_when_still_on_the_same_map(emu_stubbed):
    runtime, module, store, logged, _ = emu_stubbed
    ptr_addr, sb1_addr = 0x03005008, 0x02020000
    cp = _fake_cp(runtime, store, ptr_addr, sb1_addr, 3, 19)  # still on Route1
    store[sb1_addr], store[sb1_addr + 2] = 12, 37
    module.check_whiteout(cp, 3 * 256 + 19, 12, 37)  # before_map == current map: no whiteout
    assert not logged, "a same-map read must not log or raise a whiteout"


def test_route1_faint_resume_short_circuits_on_an_existing_faint(emu_stubbed):
    """resume() is only ever called by run_leg after check_whiteout() raised, and a one-mon party
    can only white out BY fainting -- so resume() must accept that without re-grinding, checking
    the (likely reset) counter first and falling back to the whiteout itself as evidence."""
    _, module, store, logged, _ = emu_stubbed
    faint_leg = None
    for i in range(1, len(module.LEGS) + 1):
        if module.LEGS[i]["name"] == "route1_faint":
            faint_leg = module.LEGS[i]
    assert faint_leg is not None
    battle_results_addr = 0x03004F90

    store[battle_results_addr] = 0
    faint_leg["resume"](None)
    assert any("accepted the whiteout itself" in line for line in logged)

    logged.clear()
    store[battle_results_addr] = 2
    faint_leg["resume"](None)
    assert any("survived the recovery walk" in line for line in logged)


# ── the action-menu witness (card gen3-P3-C3-21) ───────────────────────────────────────────────


def test_action_menu_witness_addresses(module):
    """gBattlerControllerFuncs[0] (pokefirered.sym line 802) reads HandleInputChooseAction
    (pokefirered.sym line 1990, 0802e438, +1 for the Thumb bit) exactly when the player's action
    menu is waiting for input; gActionSelectionCursor (pokefirered.sym line 146) is the per-
    battler cursor, battler 0 the player."""
    assert module.BATTLER_CTRL_ADDR == 0x03004FE0
    assert module.HANDLE_INPUT_CHOOSE_ACTION == 0x0802E438 | 1
    assert module.ACTION_CURSOR_ADDR == 0x02023FF8
    assert (module.ACTION_FIGHT, module.ACTION_BAG) == (0, 1)


# ── pc_release's confirmation (coordinator addendum to card gen3-P3-C3-21) ─────────────────────


def test_pc_release_confirms_yes_before_the_trailing_messages():
    """ShowYesNoWindow(1) starts the cursor on NO and does not wrap (pret
    src/pokemon_storage_system_tasks.c:2595-2599), so RELEASE's own confirmation needs an Up
    before the A that accepts it, followed by exactly two more A's for the trailing
    MSG_WAS_RELEASED / MSG_BYE_BYE messages (src/pokemon_storage_system_tasks.c:1307-1339)."""
    leg_src = _SCRIPT_SRC.split('name = "pc_release"')[1].split('\n-- ── leg: save')[0]
    release_at = leg_src.index('-- RELEASE -> Yes/No confirm')
    up_at = leg_src.index('pc_press("Up", PC_WAIT.cursor)')
    assert release_at < up_at, "Up must come after selecting RELEASE"
    tail = leg_src[up_at:leg_src.index("leave_storage")]
    a_presses = re.findall(r'pc_press\("A"', tail)
    assert len(a_presses) == 3, f"expected YES + MSG_WAS_RELEASED + MSG_BYE_BYE, got {a_presses}"


def test_save_battle_state_once_saves_no_more_than_once(emu_stubbed):
    _, module, _store, _logged, save_calls = emu_stubbed
    module.save_battle_state_once(None)
    module.save_battle_state_once(None)
    module.save_battle_state_once(None)
    assert len(save_calls) == 1, f"expected exactly one save, got {save_calls}"


# ── FR run 19: the whiteout must be caught HERE, not in the middle of the next hunt ────────────
# root cause: in_battle clears well before a whiteout's own heal-and-warp sequence actually lands
# the player on the heal map (the trailing "whited out!" message and walk-home narration both run
# AFTER the battle callback hands control back). check_whiteout, read right when in_battle
# clears, therefore saw the OLD map and never raised -- the real displacement fired later,
# unnoticed, inside the NEXT hunt_encounter's walk. resolve_battle_and_check_whiteout's fix is to
# settle the scene first (the same wait opts.battle already does for every OTHER absorbed
# battle); this drives route1_catch through exactly that timing and checks run_leg's recover()
# actually engages before the retried attempt.


def test_whiteout_settles_before_the_map_read_so_recovery_engages_before_the_next_attempt():
    os.environ.setdefault("SLINK_ROOT", _REPO.replace("\\", "/"))
    runtime = LuaRuntime(unpack_returned_tuples=True)

    # Load once with an inert `memory` (module-scope code touches no host API) just to read the
    # real witness address/value constants off the loaded module before wiring the real fake.
    runtime.globals().memory = runtime.table(
        read_u8=lambda *_: 0, read_u16_le=lambda *_: 0,
        read_u32_le=lambda *_: 0, read_s16_le=lambda *_: 0,
    )
    module = runtime.execute(f'return dofile("{_SCRIPT.replace(chr(92), "/")}")')

    PTR_ADDR, SB1_ADDR = 0x03005008, 0x02020000
    IN_BATTLE_ADDR, SCS_ADDR, FCL_ADDR = 0x03000300, 0x03000400, 0x03000500
    BATTLE_OUTCOME_ADDR = 0x02023E8A
    GRASS_X, GRASS_Y = 12, 37
    HOUSE_X, HOUSE_Y = 8, 5
    HEAL_GROUP, HEAL_NUM = 4, 0
    ROUTE1_GROUP, ROUTE1_NUM = 3, 19
    B_OUTCOME_CAUGHT = 7

    # A tiny clock (ticks once per emu.frameadvance, i.e. once per M.advance) and an "epoch"
    # the recover() spy resets for the second attempt: t0/battle_len drive when in_battle clears,
    # warp_at/quiet_from drive when the map (and the scene) actually settle -- decoupled on
    # purpose, the same gap the real engine leaves between the two. battle_len/warp_at are past
    # the ~750 frames route1_catch_loop's OWN pinned Right+A+30xA bag mash burns before it ever
    # reaches resolve_battle_and_check_whiteout, so `before_map` is captured on the grass, not
    # already mid-warp.
    clock = {"t": 0}
    ep = {"t0": 0, "battle_len": 1900, "warp_at": 2000, "quiet_from": 2000,
          "cursor": module.ACTION_FIGHT, "outcome": 0}
    calls = {"recover": 0}

    def in_battle():
        return (clock["t"] - ep["t0"]) < ep["battle_len"]

    def warped():
        return ep["warp_at"] is not None and clock["t"] >= ep["warp_at"]

    def quiet():
        return ep["quiet_from"] is not None and clock["t"] >= ep["quiet_from"]

    def read_u8(addr, *_a):
        addr = int(addr)
        if addr == SB1_ADDR + 0x1C:
            return 3
        if addr == SB1_ADDR + 0x1E:
            return 255
        if addr == IN_BATTLE_ADDR:
            return 2 if in_battle() else 0          # mask=2, expect=0: pred_ok True == NOT in battle
        if addr in (SCS_ADDR, FCL_ADDR):
            return 0 if quiet() else 1              # expect=0 == idle/unlocked
        if addr == SB1_ADDR + 0x04:
            return HEAL_GROUP if warped() else ROUTE1_GROUP
        if addr == SB1_ADDR + 0x05:
            return HEAL_NUM if warped() else ROUTE1_NUM
        if addr == module.ACTION_CURSOR_ADDR:
            return ep["cursor"]
        if addr == BATTLE_OUTCOME_ADDR:
            return ep["outcome"]
        return 0

    def read_s16_le(addr, *_a):
        addr = int(addr)
        if addr == SB1_ADDR + 0x20:
            return 6
        if addr == SB1_ADDR + 0x22:
            return 8
        if addr == SB1_ADDR + 0x00:
            return HOUSE_X if warped() else GRASS_X
        if addr == SB1_ADDR + 0x02:
            return HOUSE_Y if warped() else GRASS_Y
        return 0

    def read_u32_le(addr, *_a):
        addr = int(addr)
        if addr == PTR_ADDR:
            return SB1_ADDR
        if addr == module.BATTLER_CTRL_ADDR:
            return module.HANDLE_INPUT_CHOOSE_ACTION    # the action menu is always "up" here
        return 0

    runtime.globals().memory = runtime.table(
        read_u8=read_u8, read_u16_le=read_u8, read_u32_le=read_u32_le, read_s16_le=read_s16_le,
    )
    runtime.globals().emu = runtime.table(
        framecount=lambda: clock["t"], frameadvance=lambda: clock.__setitem__("t", clock["t"] + 1))
    joy = {}

    def joypad_set(buttons):
        joy.clear()
        if buttons:
            for k in buttons:
                joy[k] = True
        if joy.get("Right"):
            ep["cursor"] = module.ACTION_BAG

    runtime.globals().joypad = runtime.table(set=joypad_set)
    logged: list[str] = []
    runtime.globals().console = runtime.table(log=lambda s: logged.append(str(s)))
    runtime.globals().savestate = runtime.table(save=lambda *_: True)
    runtime.globals().client = runtime.table(exit=lambda *_: None, screenshot=lambda *_: None)

    cp = runtime.table(
        pointers=runtime.table(gSaveBlock1Ptr=runtime.table(address=PTR_ADDR)),
        predicates=runtime.table(
            in_battle=runtime.table(address=IN_BATTLE_ADDR, offset=0, mask=2, expect=0, width=1),
            script_context_status=runtime.table(address=SCS_ADDR, offset=0, mask=1, expect=0, width=1),
            field_controls_locked=runtime.table(address=FCL_ADDR, offset=0, mask=1, expect=0, width=1),
        ),
    )

    catch_leg = None
    for i in range(1, len(module.LEGS) + 1):
        if module.LEGS[i]["name"] == "route1_catch":
            catch_leg = module.LEGS[i]
    assert catch_leg is not None, "no route1_catch leg"
    # route1_catch's own leg.run walks the whole way from the lab to the grass before it ever
    # calls route1_catch_loop; that walk is irrelevant here (it is exercised elsewhere, e.g.
    # test_route1_legs_declare_recover_and_resume) and this test starts already positioned on
    # the grass. Drive the loop directly through play.run_leg by using leg.resume (the loop
    # itself) as BOTH the first attempt and the retry -- run_leg's own attempt>0 rule is what
    # decides which body runs, not what this test is checking.
    leg = runtime.table(name="route1_catch", run=catch_leg["resume"], resume=catch_leg["resume"])

    def recover_spy(_cp):
        """Stands in for recover_to_route1_grass: back on the grass, no more warping, and (so
        the retried attempt can actually finish) a fresh battle that gets caught outright."""
        calls["recover"] += 1
        ep["t0"] = clock["t"]
        ep["battle_len"] = 40
        ep["warp_at"] = None
        ep["quiet_from"] = clock["t"] + 60
        ep["cursor"] = module.ACTION_FIGHT
        ep["outcome"] = B_OUTCOME_CAUGHT

    leg["recover"] = recover_spy

    module.play.run_leg(cp, leg, runtime.table(max_recoveries=1))

    assert calls["recover"] == 1, "recover() must run exactly once"
    whiteout_at = next(i for i, line in enumerate(logged) if "phase whiteout " in line)
    recover_at = next(i for i, line in enumerate(logged) if "whiteout-recover " in line)
    caught_at = next(i for i, line in enumerate(logged) if "phase caught " in line)
    assert whiteout_at < recover_at < caught_at, (
        "expected: the whiteout is DETECTED, THEN recover() runs, THEN the retried attempt "
        "catches -- got this order instead:\n" + "\n".join(logged))


# ── the bag witness (card gen3-P3-C3-23): pin the battle bag's pocket/item navigation ──────────
# The old code mashed A ~30 times inside the bag hoping to land on POKE BALL. throw_pokeball_
# from_bag replaces that with a witness-driven sequence: wait for gMain.callback2 ==
# CB2_BagMenuRun, steer gBagMenuState.pocket to POKEBALLS(2) (bounded at 2 presses), verify the
# plaintext bag-slot item id, select it, verify gSpecialVar_ItemId agrees, then confirm the
# USE/CANCEL popup's default row. Every address below is cross-checked against the pinned pret
# checkout's own symbol table, not just re-asserted from the source comments.

_SYM_PATH = os.path.join(_REPO, "data", "gen3", "pret", "pokefirered.sym")
_SYM_LINE_RE = re.compile(r"^([0-9a-fA-F]{8})\s+[gl]\s+([0-9a-fA-F]{8})\s+(\S+)\s*$")


def _parse_sym(names):
    """{symbol name -> (address, size)} for exactly the requested names, read straight out of
    the pinned pret checkout's .sym file — the same file the source comments cite by line, but
    this reads the ADDRESSES independently rather than trusting a copied-down hex literal."""
    wanted = set(names)
    found = {}
    with open(_SYM_PATH, encoding="utf-8") as fh:
        for line in fh:
            m = _SYM_LINE_RE.match(line.rstrip("\n"))
            if m and m.group(3) in wanted:
                found[m.group(3)] = (int(m.group(1), 16), int(m.group(2), 16))
    missing = wanted - found.keys()
    assert not missing, f"symbol(s) {missing} not found in {_SYM_PATH}"
    return found


def test_bag_witness_addresses_match_the_pret_sym_file(module):
    sym = _parse_sym(("gBagMenuState", "gSpecialVar_ItemId", "gMain", "CB2_BagMenuRun"))

    bag_addr, bag_size = sym["gBagMenuState"]
    assert bag_addr == module.BAG_MENU_STATE_ADDR
    # struct BagStruct (include/item_menu.h): u32 bagCallback, u8 location, bool8 bagOpen,
    # u16 pocket, u16 itemsAbove[3], u16 cursorPos[3] -- 4+1+1+2+6+6 == 0x14, matching the
    # symbol's own recorded size, which is the independent cross-check the offsets are right.
    assert bag_size == 0x14
    assert module.BAG_POCKET_OFF == 0x06
    assert module.BAG_ITEMS_ABOVE_OFF == 0x08
    assert module.BAG_CURSOR_POS_OFF == 0x0E

    special_var_addr, _ = sym["gSpecialVar_ItemId"]
    assert special_var_addr == module.SPECIAL_VAR_ITEM_ID_ADDR

    gmain_addr, _ = sym["gMain"]
    assert gmain_addr + 0x04 == module.GMAIN_CALLBACK2_ADDR  # struct Main.callback2 @ +0x04

    cb2_bagmenurun_addr, _ = sym["CB2_BagMenuRun"]
    assert cb2_bagmenurun_addr | 1 == module.CB2_BAG_MENU_RUN  # +1 for the Thumb bit

    assert module.BAG_POCKET_POKEBALLS == 2       # OPEN_BAG_POKEBALLS
    assert module.ITEM_POKE_BALL == 4             # include/constants/items.h:8
    assert module.SB1_POKEBALLS_POCKET_OFFSET == 0x0430


def test_throw_pokeball_from_bag_checks_witnesses_in_source_order():
    """Every gate must appear before the press it guards: the bag-up wait before the pocket
    steer, the pocket check before the plaintext item-id read, the item-id read before the
    selecting A, and gSpecialVar_ItemId's check before the final confirming A."""
    body = _SCRIPT_SRC.split("local function throw_pokeball_from_bag")[1].split(
        "\n-- ── leg: route1_catch")[0]
    bag_up_at = body.index("bag_menu_up()")
    pocket_loop_at = body.index("for _ = 1, 4 do")  # press, wait for the switch, settle (FR run 22)
    pocket_check_at = body.index("could not steer gBagMenuState.pocket")
    item_id_read_at = body.index("bag_pokeballs_item_id(cp, slot)")
    item_id_check_at = body.index("the POKEBALLS pocket's cursor slot")
    select_a_at = body.index('G.tap("A", 3, 20)')
    selected_check_at = body.index("selected_item_id()")
    confirm_a_at = body.index('G.tap("A", 3, 30)')
    assert (bag_up_at < pocket_loop_at < pocket_check_at < item_id_read_at < item_id_check_at
            < select_a_at < selected_check_at < confirm_a_at), (
        "the bag witness checks are out of order:\n" + body)


def test_route1_catch_loop_no_longer_mashes_a_blindly_inside_the_bag():
    """ROOT CAUSE this card fixes: FR run 21 showed a battle that never resolved because the old
    code pressed A ~30 times inside the bag hoping to land on POKE BALL. That mash must be gone,
    replaced by the witness-driven call."""
    loop_body = _SCRIPT_SRC.split("local function route1_catch_loop")[1].split(
        "\nLEGS[#LEGS + 1] = {")[0]
    assert "throw_pokeball_from_bag(cp, \"route1_catch\")" in loop_body
    assert "for _ = 1, 30 do G.tap(\"A\"" not in loop_body, (
        "the blind 30x-A bag mash should have been replaced by throw_pokeball_from_bag")


@pytest.fixture
def bag_stubbed():
    """A fresh runtime with just enough of the BizHawk API for throw_pokeball_from_bag to run
    for real: memory (a dict-backed store), joypad, emu (framecount/frameadvance), console,
    client (exit/screenshot) and savestate -- no emulator, no ROM. Returns
    (runtime, module, store, logged, exits)."""
    os.environ.setdefault("SLINK_ROOT", _REPO.replace("\\", "/"))
    runtime = LuaRuntime(unpack_returned_tuples=True)
    store: dict[int, int] = {}

    runtime.globals().memory = runtime.table(
        read_u8=lambda a, *_: store.get(int(a), 0) & 0xFF,
        read_u16_le=lambda a, *_: store.get(int(a), 0) & 0xFFFF,
        read_u32_le=lambda a, *_: store.get(int(a), 0),
    )
    runtime.globals().joypad = runtime.table(set=lambda *_: None)
    runtime.globals().emu = runtime.table(
        framecount=lambda: 0, frameadvance=lambda: None)
    logged: list[str] = []
    runtime.globals().console = runtime.table(log=lambda s: logged.append(str(s)))
    exits: list[bool] = []
    runtime.globals().client = runtime.table(
        exit=lambda *_: exits.append(True), screenshot=lambda *_: None)
    runtime.globals().savestate = runtime.table(save=lambda *_: True, load=lambda *_: True)
    mod = runtime.execute(f'return dofile("{_SCRIPT.replace(chr(92), "/")}")')
    return runtime, mod, store, logged, exits


def _in_battle_cp(runtime, store, address=0x03000300):
    """A `cp` whose predicates.in_battle reads TRUE (mask=2, expect=0; raw bit set -> in
    battle) -- the same shape stubbed_module's own in_battle test uses."""
    store[address] = 2
    return runtime.table(predicates=runtime.table(
        in_battle=runtime.table(address=address, offset=0, mask=2, expect=0, width=1)))


def test_throw_pokeball_from_bag_fails_loudly_on_the_wrong_pocket(bag_stubbed):
    """FAKE-RAM regression: the bag menu is up (gMain.callback2 == CB2_BagMenuRun) but
    gBagMenuState.pocket is stuck on KEYITEMS(1) -- e.g. a ProcessPocketSwitchInput change that
    breaks the clamp. Two bounded Right presses cannot fix that, so the function must fail
    loudly, naming the witness, rather than pressing on into whatever pocket happens to be open."""
    runtime, module, store, logged, exits = bag_stubbed
    cp = _in_battle_cp(runtime, store)
    store[module.GMAIN_CALLBACK2_ADDR] = module.CB2_BAG_MENU_RUN   # bag menu is up
    store[module.BAG_MENU_STATE_ADDR + module.BAG_POCKET_OFF] = 1  # stuck on KEYITEMS, not 2

    module.throw_pokeball_from_bag(cp, "test")

    assert exits, "a wrong pocket must reach G.finish(false, ...) -> client.exit()"
    fail_lines = [line for line in logged if "RESULT: FAIL" in line]
    assert fail_lines, "expected a FAIL result, got:\n" + "\n".join(logged)
    assert "gBagMenuState.pocket" in fail_lines[-1] and "POKEBALLS(2)" in fail_lines[-1], (
        f"the failure must name the witness that didn't match: {fail_lines[-1]}")
    assert "reads 1" in fail_lines[-1]


def test_throw_pokeball_from_bag_fails_loudly_on_the_wrong_item(bag_stubbed):
    """FAKE-RAM regression: the pocket steer succeeds, but the plaintext bag slot under the
    cursor holds some other item (not ITEM_POKE_BALL) -- must fail before ever pressing A on it,
    naming the witness and the bad item id."""
    runtime, module, store, logged, exits = bag_stubbed
    cp = _in_battle_cp(runtime, store)
    store[module.GMAIN_CALLBACK2_ADDR] = module.CB2_BAG_MENU_RUN
    store[module.BAG_MENU_STATE_ADDR + module.BAG_POCKET_OFF] = module.BAG_POCKET_POKEBALLS
    # itemsAbove[2] = cursorPos[2] = 0 -> slot 0; gSaveBlock1Ptr -> a fake SaveBlock1 whose
    # POKEBALLS pocket slot 0 holds ITEM_NONE (0), not ITEM_POKE_BALL (4).
    ptr_addr, sb1_addr = 0x03005008, 0x02020000
    store[ptr_addr] = sb1_addr
    store[sb1_addr + module.SB1_POKEBALLS_POCKET_OFFSET] = 0
    cp = runtime.table(
        predicates=cp.predicates,
        pointers=runtime.table(gSaveBlock1Ptr=runtime.table(address=ptr_addr)))

    module.throw_pokeball_from_bag(cp, "test")

    assert exits, "a wrong item id must reach G.finish(false, ...) -> client.exit()"
    fail_lines = [line for line in logged if "RESULT: FAIL" in line]
    assert fail_lines, "expected a FAIL result, got:\n" + "\n".join(logged)
    assert "ITEM_POKE_BALL" in fail_lines[-1] and "slot 0" in fail_lines[-1]


# ── the parcel-delivery oracle (card gen3-P3-C3-26): FALSE PASS FOUND ──────────────────────────
# The old parcel_deliver leg called wait_scene_settled and reported success the instant it
# returned true, with NO RAM check at all. But PalletTown_ProfessorOaksLab_EventScript_ProfOak
# (data/maps/PalletTown_ProfessorOaksLab/scripts.inc:567-660) is a TALK-TO script (`lock;
# faceplayer`), triggered by pressing A while facing the object -- and the old leg only ever
# faced Oak, never pressed A, so the field was already idle+unlocked (nothing had started) the
# instant it finished walking, which is exactly what "settled" reads as. A PHYSICAL RAM dump
# (slink_fr_parcel_deliver.State) caught it: ITEM_OAKS_PARCEL was still in the key-items pocket
# and every POKe BALLS slot read 0 after a run this leg had reported PASS.

def test_parcel_oracle_address_arithmetic(module):
    """Every offset/id below is source arithmetic, independently checked here rather than just
    re-typed from a comment: pret include/global.h:779,790 (SaveBlock1.bagPocket_KeyItems at
    +0x03B8, SaveBlock1.flags[] at +0x0EE0), include/constants/global.h:37-38
    (BAG_KEYITEMS_COUNT=30, BAG_POKEBALLS_COUNT=13), include/constants/items.h:421
    (ITEM_OAKS_PARCEL=349), include/constants/flags.h:1324,1375 (FLAG_SYS_POKEDEX_GET =
    SYS_FLAGS(0x800)+0x29 == 0x829)."""
    assert module.SB1_KEYITEMS_POCKET_OFFSET == 0x03B8
    assert module.BAG_KEYITEMS_COUNT == 30
    assert module.ITEM_OAKS_PARCEL == 349
    assert module.SB1_FLAGS_OFFSET == 0x0EE0
    assert module.FLAG_SYS_POKEDEX_GET == 0x829
    assert module.BAG_POKEBALLS_COUNT == 13
    # bagPocket_KeyItems (+0x03B8) and bagPocket_PokeBalls (+0x0430) are adjacent slabs of the
    # same struct ItemSlot[] run (pret include/global.h:779-780) -- 30 slots * 4 bytes apart,
    # not two independently-guessed offsets.
    assert (module.SB1_KEYITEMS_POCKET_OFFSET + module.BAG_KEYITEMS_COUNT * 4
            == module.SB1_POKEBALLS_POCKET_OFFSET)


def test_lab_entrance_to_oak_matches_the_rom_bfs(module):
    """tools/gba_map.py "patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba" --map 4.3 --bfs
    6,12 6,4 returns exactly 8x Up (Oak's object_event sits at (6,3), solid; the door's landing
    tile is (6,12)) -- geometry from the ROM/decomp, never a screenshot."""
    entry = module.PATHS["lab_entrance_to_oak"]
    assert (entry["from"][1], entry["from"][2]) == (6, 12)
    assert (entry["to"][1], entry["to"][2]) == (6, 4)
    dirs = [entry["dirs"][i] for i in range(1, len(entry["dirs"]) + 1)]
    assert dirs == ["Up"] * 8


def test_parcel_deliver_run_body_talks_before_it_waits_and_verifies_after(module):
    """Source-order check: the walk to Oak, then facing him, then ACTUALLY STARTING the
    interaction, then riding the scene out, then the real oracle -- in that order, both in
    run() and in resume() (the whiteout-restart tail reuses the same shape). Scoped to the
    parcel_deliver leg specifically -- every other leg also has a `run = function(cp)`."""
    leg_src = _SCRIPT_SRC.split("-- ── leg: parcel_deliver", 1)[1].split(
        "-- ── leg: route1_catch", 1)[0]
    run_body = leg_src.split("run = function(cp)", 1)[1].split(
        "LEGS[#LEGS].resume = function(cp)", 1)[0]
    resume_body = leg_src.split("LEGS[#LEGS].resume = function(cp)", 1)[1]
    # run() walks there directly; resume() reaches the same tile through leg.deliver_from_town
    # (the whiteout-restart path, which also ends at "lab_entrance_to_oak") -- different walk
    # markers, same tail after it.
    walk_markers = {
        "run": 'play.follow(cp, "lab_entrance_to_oak"',
        "resume": "leg.deliver_from_town(cp)",
    }
    for label, body in (("run", run_body), ("resume", resume_body)):
        walk_at = body.index(walk_markers[label])
        face_at = body.index('G.tap("Up", 2, 13)', walk_at)
        start_at = body.index("start_oak_delivery(cp,", face_at)
        settle_at = body.index("wait_scene_settled(cp,", start_at)
        verify_at = body.index("verify_parcel_delivered(cp,", settle_at)
        assert walk_at < face_at < start_at < settle_at < verify_at, (
            f"parcel_deliver's {label} tail is out of order:\n" + body)


@pytest.fixture
def parcel_cp(bag_stubbed):
    """A `cp` with a fake gSaveBlock1Ptr, for the overworld save-data oracle
    (key_items_has_parcel / pokedex_get_flag / pokeballs_pocket_has_poke_ball /
    start_oak_delivery / verify_parcel_delivered) -- none of them touch a predicate, only
    cp.pointers.gSaveBlock1Ptr, so no fake predicates are needed here (unlike _in_battle_cp)."""
    runtime, module, store, logged, exits = bag_stubbed
    ptr_addr, sb1_addr = 0x03005008, 0x02020000
    store[ptr_addr] = sb1_addr
    cp = runtime.table(pointers=runtime.table(gSaveBlock1Ptr=runtime.table(address=ptr_addr)))
    return runtime, module, store, logged, exits, cp, sb1_addr


def _set_parcel_slot(store, sb1_addr, module, slot, item_id):
    store[sb1_addr + module.SB1_KEYITEMS_POCKET_OFFSET + slot * 4] = item_id


def _set_pokedex_flag(store, sb1_addr, module, value):
    flag = module.FLAG_SYS_POKEDEX_GET
    byte_addr = sb1_addr + module.SB1_FLAGS_OFFSET + (flag // 8)
    bit = 1 << (flag % 8)
    cur = store.get(byte_addr, 0)
    store[byte_addr] = (cur | bit) if value else (cur & ~bit)


def _set_ball_slot(store, sb1_addr, module, slot, item_id):
    store[sb1_addr + module.SB1_POKEBALLS_POCKET_OFFSET + slot * 4] = item_id


def test_key_items_has_parcel_reads_every_slot(parcel_cp):
    _, module, store, _, _, cp, sb1_addr = parcel_cp
    assert module.key_items_has_parcel(cp) is False   # every slot ITEM_NONE(0) by default
    _set_parcel_slot(store, sb1_addr, module, 0, module.ITEM_OAKS_PARCEL)
    assert module.key_items_has_parcel(cp) is True
    _set_parcel_slot(store, sb1_addr, module, 0, 0)
    _set_parcel_slot(store, sb1_addr, module, 5, module.ITEM_OAKS_PARCEL)  # not just slot 0
    assert module.key_items_has_parcel(cp) is True


def test_pokedex_get_flag_bit_math(parcel_cp):
    _, module, store, _, _, cp, sb1_addr = parcel_cp
    assert module.pokedex_get_flag(cp) is False
    _set_pokedex_flag(store, sb1_addr, module, True)
    assert module.pokedex_get_flag(cp) is True


def test_pokeballs_pocket_has_poke_ball_reads_every_slot(parcel_cp):
    _, module, store, _, _, cp, sb1_addr = parcel_cp
    assert module.pokeballs_pocket_has_poke_ball(cp) is False
    _set_ball_slot(store, sb1_addr, module, 3, module.ITEM_POKE_BALL)  # not just slot 0
    assert module.pokeballs_pocket_has_poke_ball(cp) is True


def test_verify_parcel_delivered_fails_loudly_on_the_physically_observed_false_pass(parcel_cp):
    """FAKE-RAM regression: the exact bad state the coordinator's PHYSICAL RAM dump of
    slink_fr_parcel_deliver.State found -- ITEM_OAKS_PARCEL still in the key-items pocket slot 0,
    every POKe BALLS slot 0. The old leg reported this run a PASS; this oracle must not."""
    _, module, store, logged, exits, cp, sb1_addr = parcel_cp
    _set_parcel_slot(store, sb1_addr, module, 0, module.ITEM_OAKS_PARCEL)

    module.verify_parcel_delivered(cp, "test")

    assert exits, "the false-pass RAM state must reach G.finish(false, ...) -> client.exit()"
    fail_lines = [line for line in logged if "RESULT: FAIL" in line]
    assert fail_lines, "expected a FAIL result, got:\n" + "\n".join(logged)
    assert "ITEM_OAKS_PARCEL" in fail_lines[-1] and "key-items pocket" in fail_lines[-1]


def test_verify_parcel_delivered_passes_on_the_good_state(parcel_cp):
    """FAKE-RAM: parcel gone, dex flag set, a POKe BALL in the pocket -- must NOT fail."""
    _, module, store, logged, exits, cp, sb1_addr = parcel_cp
    _set_pokedex_flag(store, sb1_addr, module, True)
    _set_ball_slot(store, sb1_addr, module, 0, module.ITEM_POKE_BALL)
    store[sb1_addr + module.LAB_SCENE_VAR_OFFSET] = 6

    module.verify_parcel_delivered(cp, "test")

    assert not exits, "the good RAM state must not fail"
    assert not [line for line in logged if "RESULT: FAIL" in line]


def test_verify_parcel_delivered_checks_the_dex_flag_not_just_the_ball(parcel_cp):
    """FAKE-RAM: the parcel is gone and a ball is already in the pocket, but
    FLAG_SYS_POKEDEX_GET never got set -- a partial scene, not a completed one, must still
    fail."""
    _, module, store, logged, exits, cp, sb1_addr = parcel_cp
    _set_ball_slot(store, sb1_addr, module, 0, module.ITEM_POKE_BALL)

    module.verify_parcel_delivered(cp, "test")

    assert exits
    fail_lines = [line for line in logged if "RESULT: FAIL" in line]
    assert fail_lines and "FLAG_SYS_POKEDEX_GET" in fail_lines[-1]


def test_start_oak_delivery_fails_loudly_if_the_parcel_never_leaves(parcel_cp):
    """FAKE-RAM: A is mashed but the parcel never disappears (the interaction never really
    started) -- must fail loudly naming the item, rather than mashing forever."""
    _, module, store, logged, exits, cp, sb1_addr = parcel_cp
    _set_parcel_slot(store, sb1_addr, module, 0, module.ITEM_OAKS_PARCEL)  # never removed

    module.start_oak_delivery(cp, "test")

    assert exits
    fail_lines = [line for line in logged if "RESULT: FAIL" in line]
    assert fail_lines and "ITEM_OAKS_PARCEL" in fail_lines[-1]


def test_start_oak_delivery_stops_as_soon_as_the_parcel_leaves(parcel_cp):
    """FAKE-RAM: the parcel disappears after a few A presses (standing in for the scene's own
    `removeitem`) -- start_oak_delivery must return quietly, never calling G.finish."""
    runtime, module, store, logged, exits, cp, sb1_addr = parcel_cp
    _set_parcel_slot(store, sb1_addr, module, 0, module.ITEM_OAKS_PARCEL)
    presses = {"n": 0, "held": False}

    def joypad_set(buttons):
        held = bool(buttons and buttons["A"])
        if held and not presses["held"]:
            presses["n"] += 1
        presses["held"] = held
        if presses["n"] == 3:
            _set_parcel_slot(store, sb1_addr, module, 0, 0)

    runtime.globals().joypad = runtime.table(set=joypad_set)

    module.start_oak_delivery(cp, "test")

    assert not exits, "must return once the parcel leaves, not mash on to the frame budget"
    assert presses["n"] == 3, "no A press may follow the observed removal"
