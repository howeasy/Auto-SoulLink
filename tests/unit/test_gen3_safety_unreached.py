"""PLAN §5.3 forbidden states that have no PHYSICAL receipt: evolution, link, native op staged,
mid-relocation. Each is driven with its SOURCE values through safety.lua AND writes.lua, so the
refusal is shown with an empty write log, not only a false predicate.
Derivation: docs/gen3/research/checkpoint_unreached_states.md."""
import json
import sys

import pytest

from tests.unit.test_gen3_safety import ROOT, World, lupa

sys.path.insert(0, str(ROOT / "tools"))
import gen_gen3_write_checkpoint as G  # noqa: E402

TITLES = [("firered", "clean"), ("leafgreen", "clean"),
          ("radical_red", "clean"), ("radical_red", "companion")]


def sym(title, name):
    # RR ships no symbols; the FireRed value is used and its RR standing is cited in the doc.
    path = ROOT / "data/gen3/pret" / ("pokeleafgreen.sym" if title == "leafgreen" else "pokefirered.sym")
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[3] == name:
            return int(parts[0], 16)
    raise KeyError(name)


def writer(w):
    w.lua.globals().deps.safety = w.safety
    module = w.lua.execute((ROOT / "lua/gen3/writes.lua").read_text(encoding="utf-8"))
    return module.new(w.lua.globals().deps)


def assert_refused(w, reason):
    ok, why = w.safety.check(w.safety, None)
    assert ok is False and reason in why
    wr = writer(w)
    with pytest.raises(lupa.LuaError, match=reason):
        wr.arm(wr, "overworld", w.lua.eval("function() return true end"))
    with pytest.raises(lupa.LuaError, match="no armed"):
        wr.write_u16(wr, 0x02010000, 0)
    assert len(w.lua.globals().writes) == 0 and len(wr.log) == 0


def set_pred(w, name, value):
    p = w.pack["predicates"][name]
    w.lua.globals().put(p["address"] + p["offset"], value, p["width"])


def add_task(w, fn):
    t = w.pack["tasks"]
    base = t["address"] + 3 * t["struct_size"]  # World fills slots 0-2 with the allow-list
    w.lua.globals().put(base + t["func_offset"], fn | 1, 4)
    w.lua.globals().put(base + t["is_active_offset"], 1, 1)


@pytest.mark.parametrize("title,kind", TITLES)
def test_positive_control_arms_and_writes(title, kind):
    w = World(title, kind)
    wr = writer(w)
    wr.arm(wr, "overworld", w.lua.eval("function() return true end"))
    wr.write_u16(wr, 0x02010000, 0)
    assert len(w.lua.globals().writes) == 2


@pytest.mark.parametrize("title,kind", TITLES)
@pytest.mark.parametrize("clause", ["callback2", "task_scene", "task_begin", "in_battle"])
def test_evolution(title, kind, clause):
    w = World(title, kind)
    if clause == "callback2":  # evolution_scene.c:310,374 SetMainCallback2(CB2_EvolutionSceneUpdate)
        rr = json.loads((ROOT / "data/games/gen3_rr/profile.json").read_text())["titles"]["radical_red"]
        cb2 = (rr["rom"]["CB2_EVOLUTION_UPDATE_ADDR"] if title == "radical_red"
               else sym(title, "CB2_EvolutionSceneUpdate") | 1)
        set_pred(w, "callback2", cb2)
        assert_refused(w, "forbidden state: callback2")
    elif clause == "in_battle":  # battle_main.c:711 set, :3925 cleared only after TryEvolvePokemon
        set_pred(w, "in_battle", 2)
        assert_refused(w, "forbidden state: in_battle")
    else:  # evolution_scene.c:293 / :202 CreateTask
        add_task(w, sym(title, "Task_EvolutionScene" if clause == "task_scene" else "Task_BeginEvolutionScene"))
        assert_refused(w, "unknown active task")


@pytest.mark.parametrize("kind", ["clean", "companion"])
def test_rr_evolution_task_from_engine_signals_is_refused(kind):
    path = ROOT / "data/games/gen3_rr/engine_signals.json"
    signals = json.loads(path.read_text(encoding="utf-8"))
    site = signals["titles"]["radical_red"]["artifacts"][kind]["sites"]["evolve_species_store"]
    task = site["function"]
    assert task["symbol"] == "Task_EvolutionScene"
    w = World("radical_red", kind)
    assert w.check()
    add_task(w, task["address"])
    assert_refused(w, "unknown active task")
    assert list(w.safety.last_clauses.values()) == ["task"]


@pytest.mark.parametrize("title,kind", TITLES)
@pytest.mark.parametrize("clause", ["link_callback", "link_players_received", "link_transferring",
                                    "callback1", "task"])
def test_link(title, kind, clause):
    w = World(title, kind)
    if clause == "link_callback":  # link.c:394 OpenLink
        set_pred(w, clause, sym(title, "LinkCB_RequestPlayerDataExchange") | 1)
    elif clause in ("link_players_received", "link_transferring"):  # link.c:540 / rfu_2.c:2065, main.c:195
        set_pred(w, clause, 1)
    elif clause == "callback1":  # overworld.c:1605,1643 link rooms run CB2_Overworld + this cb1
        set_pred(w, clause, sym(title, "CB1_UpdateLinkState") | 1)
    else:  # cable_club.c:873
        add_task(w, sym(title, "Task_EnterCableClubSeat"))
        assert_refused(w, "unknown active task")
        return
    assert_refused(w, "forbidden state: " + clause)


@pytest.mark.parametrize("title,kind", TITLES)
@pytest.mark.parametrize("comm_type", [1, 2, 3])
def test_wireless_comm_type_alone_is_idle(title, kind, comm_type):
    # gWirelessCommType is the sticky transport selector: the title menu's adapter probe sets 1
    # (main_menu.c:573 -> link.c:248) and nothing clears it on the field.  With no link session it
    # must NOT refuse (receipt checkpoint_fr_parcel_lineage_2026-09-22.txt: 300/300 idle refused).
    w = World(title, kind)
    w.lua.globals().put(sym(title, "gWirelessCommType"), comm_type, 1)
    assert w.check()
    set_pred(w, "link_players_received", 1)  # the same frame once a partner is connected
    assert_refused(w, "forbidden state: link_players_received")


@pytest.mark.parametrize("title,kind", TITLES)
def test_pc_menu_task(title, kind):  # pokemon_storage_system_menu.c:356; FR pc_menu receipt row is SKIP
    w = World(title, kind)
    add_task(w, sym(title, "Task_PCMainMenu"))
    assert_refused(w, "unknown active task")


@pytest.mark.parametrize("title,kind", TITLES)
@pytest.mark.parametrize("idle", ["false", "nil", "1"])
def test_native_staged(title, kind, idle):
    w = World(title, kind)
    w.lua.execute("idle = " + idle)
    assert_refused(w, "native transaction in flight")


@pytest.mark.parametrize("title,kind", TITLES)
def test_mid_relocation_every_pointer(title, kind):
    w = World(title, kind)
    names = [n for n in w.pack["pointers"] if n != "pokemon_storage_base"]
    assert names
    for name in names:
        w = World(title, kind)
        g = w.lua.globals()
        wr = writer(w)
        wr.arm(wr, "overworld", w.lua.eval("function() return true end"))
        a = w.pack["pointers"][name]["address"]
        g.put(a, g.read(a, 4) + 4, 4)  # load_save.c:75 offset step: 4-aligned, < 128
        with pytest.raises(lupa.LuaError, match="pointer moved: " + name):
            wr.write_u16(wr, 0x02010000, 0)
        assert len(g.writes) == 0 and len(wr.log) == 0


@pytest.mark.parametrize("title,kind,expect", [
    ("firered", "clean", "7c210140"),        # movs r1,#0x7C ; ands r1,r0 (load_save.c:75)
    ("leafgreen", "clean", "7c210140"),
    ("radical_red", "clean", "00210021"),    # movs r1,#0 twice: RR offset is always 0
    ("radical_red", "companion", "00210021")])
def test_save_block_offset_instruction(title, kind, expect):
    pack = "gen3_rr" if title == "radical_red" else "gen3_frlg"
    if not G.ROMS[(pack, title, kind)][0].exists():
        pytest.skip("ROM not present")
    rom = G.load_rom(pack, title, kind)
    at = sym("firered", "SetSaveBlocksPointers") - G.ROM_BASE + 0x0A
    assert rom[at:at + 4].hex() == expect
