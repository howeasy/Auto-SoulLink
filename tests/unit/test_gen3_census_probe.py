"""E2-CENSUS-2 (cx-cb4fb1b8): pure logic in lua/tests/probe_gen3_frameend_census.lua --
label()'s task clause (MINOR 3/12), the pack-driven task geometry (MINOR 4), and the
Emerald hooks probe's capture_offset anchor (MINOR 5/6) -- offline via lupa, no EmuHawk.
"""
from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "lua/tests/probe_gen3_frameend_census.lua").read_text(encoding="utf-8")

# data/games/gen3_emerald/write_checkpoint.json tasks.allowed_overworld_tasks, Thumb-bit
# stripped (card E2-CENSUS-2's pin).
ALLOWED = {
    "Task_RunPerStepCallback": 0x0809D88C,
    "Task_RunTimeBasedEvents": 0x0809D908,
    "Task_MuddySlope": 0x0809E638,
    "Task_WeatherMain": 0x080AB1B0,
}
NOT_ALLOWED = 0x0806E811  # any func address absent from ALLOWED


@pytest.fixture
def module():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    # Executing the definition chunk only defines P (the main-guard keeps run() from firing --
    # `lua.execute` does not see BizHawk's `source == "main"`), so no BizHawk global is needed.
    return lua, lua.execute(SOURCE)


def tasks_pack(lua, struct_size=8, func_offset=0, is_active_offset=4, count=1, allowed=None):
    return lua.table_from({
        "address": 0, "count": count, "struct_size": struct_size,
        "func_offset": func_offset, "is_active_offset": is_active_offset,
        "allowed_overworld_tasks": lua.table_from(allowed or ALLOWED),
    })


def one_slot_io(lua, func, active=True, thumb=True):
    """A single task slot at base 0: func word at +0, is_active byte at +4 (matches tasks_pack's
    default func_offset/is_active_offset)."""
    mem = {0: (func | 1) if thumb else func, 4: 1 if active else 0}
    read = lambda a: mem.get(int(a), 0)  # noqa: E731
    return lua.table_from({"read_u8": read, "read_u32": read})


def fake_G(clean=True):
    """A stand-in for lua/tests/gen3_boot_check.lua's G: pred_ok always reports `clean`, so
    P.label's four predicate checks fall straight through to the task clause."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    return lua, lua.table_from({"pred_ok": lambda cp, name: clean})


def test_mask_strips_the_thumb_bit(module):
    _, probe = module
    assert probe.mask(0x0809D88D) == 0x0809D88C
    assert probe.mask(0x0809D88C) == 0x0809D88C


@pytest.mark.parametrize("name,addr", sorted(ALLOWED.items()))
def test_tasks_allowed_admits_each_of_the_four_allowed_funcs(module, name, addr):
    lua, probe = module
    tasks = tasks_pack(lua, allowed=ALLOWED)
    assert probe.tasks_allowed(one_slot_io(lua, addr), tasks) is True, name


def test_tasks_allowed_refuses_a_non_allowed_func(module):
    lua, probe = module
    tasks = tasks_pack(lua, allowed=ALLOWED)
    assert probe.tasks_allowed(one_slot_io(lua, NOT_ALLOWED), tasks) is False


def test_tasks_allowed_ignores_an_inactive_slot_whatever_its_func(module):
    lua, probe = module
    tasks = tasks_pack(lua, allowed=ALLOWED)
    assert probe.tasks_allowed(one_slot_io(lua, NOT_ALLOWED, active=False), tasks) is True


@pytest.mark.parametrize("name,addr", sorted(ALLOWED.items()))
def test_label_reports_overworld_idle_for_each_allowed_task(name, addr):
    G_lua, G = fake_G(clean=True)
    tasks = tasks_pack(G_lua, allowed=ALLOWED)
    cp = G_lua.table_from({"tasks": tasks})
    probe = G_lua.execute(SOURCE)
    assert probe.label(G, one_slot_io(G_lua, addr), cp) == "overworld-idle", name


def test_label_reports_task_refused_for_a_non_allowed_task():
    G_lua, G = fake_G(clean=True)
    tasks = tasks_pack(G_lua, allowed=ALLOWED)
    cp = G_lua.table_from({"tasks": tasks})
    probe = G_lua.execute(SOURCE)
    assert probe.label(G, one_slot_io(G_lua, NOT_ALLOWED), cp) == "overworld-task-refused"


def test_label_checks_predicates_before_the_task_clause():
    """A dirty predicate (in_battle refused) must win over a clean task set -- the task clause
    is the LAST gate before overworld-idle, mirroring lua/gen3/safety.lua's clause order."""
    G_lua, G = fake_G(clean=False)
    tasks = tasks_pack(G_lua, allowed=ALLOWED)
    cp = G_lua.table_from({"tasks": tasks})
    probe = G_lua.execute(SOURCE)
    assert probe.label(G, one_slot_io(G_lua, ALLOWED["Task_WeatherMain"]), cp) == "in-battle"


def test_task_set_prints_masked_hex_so_it_compares_with_the_allow_list(module):
    lua, probe = module
    tasks = tasks_pack(lua, allowed=ALLOWED)
    got = probe.task_set(one_slot_io(lua, ALLOWED["Task_MuddySlope"]), tasks)
    assert got == "0809E638"


# ── geometry: read from the pack, never a hardcoded 0x28/+4 struct offset ──────────────────────
def test_task_geometry_is_read_from_the_pack_not_hardcoded():
    assert "0x28" not in SOURCE, "struct offset must come from tasks.struct_size, not a literal"
    for field in ("tasks.struct_size", "tasks.func_offset", "tasks.is_active_offset"):
        assert field in SOURCE


def test_geometry_fields_thread_through_to_the_actual_read_addresses(module):
    """struct_size/func_offset/is_active_offset are not just read and ignored: the addresses
    P.tasks_allowed actually queries must be base + i*struct_size (+ the two offsets)."""
    lua, probe = module
    tasks = tasks_pack(lua, struct_size=12, func_offset=2, is_active_offset=6, count=2, allowed=ALLOWED)
    seen_u8 = []

    def read_u8(a):
        seen_u8.append(int(a))
        return 0   # every slot inactive: func_offset is never read

    io = lua.table_from({"read_u8": read_u8, "read_u32": lambda a: 0})
    assert probe.tasks_allowed(io, tasks) is True
    assert seen_u8 == [6, 18]   # slot 0: 0*12+6; slot 1: 1*12+6


def test_geometry_reads_func_at_func_offset_once_active(module):
    lua, probe = module
    tasks = tasks_pack(lua, struct_size=12, func_offset=2, is_active_offset=6, count=1, allowed=ALLOWED)
    mem = {6: 1, 2: ALLOWED["Task_MuddySlope"] | 1}
    read = lambda a: mem.get(int(a), 0)  # noqa: E731
    io = lua.table_from({"read_u8": read, "read_u32": read})
    assert probe.tasks_allowed(io, tasks) is True


# ── the sampler arms only once checkpoint-clean, and the verdict is a 90% rate ─────────────────
def test_the_sampler_arms_only_once_checkpoint_clean():
    assert 'P.label(G, MEMIO, cp) == "overworld-idle"' in SOURCE
    assert "CLEAN_HOLD" in SOURCE
    assert "never reached a checkpoint-clean frame" in SOURCE


def test_the_final_verdict_is_a_90_percent_rate_not_a_nonzero_count():
    assert "idle >= 0.9 * frame" in SOURCE
    assert "idle > 0" not in SOURCE  # the old, too-weak verdict this replaces


# ── probe_gen3_hooks.lua's Emerald anchor: address + capture_offset, mirroring signals.lua:94 ──
def test_emerald_hooks_anchor_includes_capture_offset():
    hooks = (ROOT / "lua/tests/probe_gen3_hooks.lua").read_text(encoding="utf-8")
    assert "sites.frame_control.address + (sites.frame_control.capture_offset or 0)" in hooks
    assert "sites.battle_end.address + (sites.battle_end.capture_offset or 0)" in hooks
    assert "cb2.address + (cb2.offset or 0)" in hooks, "watch base must come from the checkpoint predicate"
