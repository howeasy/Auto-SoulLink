"""Read-only ROM tile verification and injected route/snapshot falsifiers; no emulator."""
import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

from tools import gba_map

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "lua/tests/gen3_routes.lua"
PRET = ROOT.parents[2] / ".cache/pret/pokefirered"
ROMS = {"firered": "Pokemon - FireRed Version (USA).gba", "leafgreen": "Pokemon - LeafGreen Version (USA).gba"}
MAPS = {(3, 1): "ViridianCity", (3, 20): "Route2", (15, 0): "Route2_ViridianForest_SouthEntrance",
        (1, 0): "ViridianForest"}


@pytest.fixture
def env():
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua, lua.execute(SOURCE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("title", ROMS)
def test_every_route_tile_against_rom_and_all_event_objects(env, title):
    _, routes = env
    rom = gba_map.load(ROOT.parents[2] / ROMS[title], sym_path=ROOT / f"data/gen3/pret/poke{title}.sym")
    for name, p in routes.paths.items():
        g, n, x, y, ex, ey, moves = [p[i] for i in range(1, 8)]
        grid = rom.map(g, n)
        events = json.loads((PRET / "data/maps" / MAPS[g, n] / "map.json").read_text())
        blocked = {(o["x"], o["y"]) for o in events["object_events"]}
        for token in moves.split():
            dx, dy = {"U": (0, -1), "D": (0, 1), "L": (-1, 0), "R": (1, 0)}[token[0]]
            for _ in range(int(token[1:])):
                x, y = x + dx, y + dy
                assert grid.collision[y][x] == 0, (title, name, x, y)
                assert grid.behaviour[y][x] in (0, 2), (title, name, x, y)
                assert (x, y) not in blocked, (title, name, "object", x, y)
        assert (x, y) == (ex, ey)
    # The final trainer sight step is normal terrain, not an invented battle flag.
    forest = rom.map(1, 0)
    assert forest.collision[45][42] == 0
    assert forest.behaviour[45][42] == 0
    assert rom.map(15, 0).behaviour[10][7] == forest.behaviour[62][29] == 0x65


def test_snapshot_uses_actual_policy_and_counts_frames_not_calls(env):
    lua, routes = env
    lua.execute("""
        f=10; count=2; allow=true; calls={}; mem={}
        c={cp={battle={clauses={{name='battle_comm_0',address=30,width=1}}}},
           party=function() return {{key='K',slot=1,hp=20}} end,
           in_battle=function() return true end,party_base=function() return 0x02024284 end}
        ram={BATTLERS_COUNT_ADDR=1,BATTLER_PARTY_INDEXES_ADDR=2,BATTLE_TYPE_ADDR=3,
             BATTLE_MONS_ADDR=100,BATTLE_OUTCOME_ADDR=4,TRAINER_OPPONENT_ADDR=5}
        mem[2]=0;mem[3]=8;mem[4]=0;mem[5]=102
        io_={u8=function(a) if a==1 then return count end return mem[a] or 0 end,
             u16=function(a) return mem[a] or 0 end,u32=function(a) return mem[a] or 0 end}
        policy={snapshot=function() return {} end,check=function(_,s,reason)
            calls[#calls+1]=reason;return allow end}
        frame=function() return f end; regs=function() return {R15=452,CPSR=31} end
    """)
    g = lua.globals()
    snapshot = routes.snapshotter(g.c, g.io_, g.policy, g.ram, g.frame, g.regs)
    s = snapshot("K")
    assert s.trainer_id == 102 and s.is_trainer and s.target_count == 1
    assert len(s.active_bytes) == 0x58 and s.samples == 1
    assert snapshot("K").samples == 1
    g.f = 11
    g.allow = False
    s = snapshot("K")
    assert s.samples == 2 and not s.battle_permit and not s.overworld_permit
    assert list(g.calls.values()) == ["battle_faint", "overworld"] * 3
    g.count = 5
    s, why = snapshot("K")
    assert s is None and "battler count" in why


@pytest.mark.parametrize("budget,hp,reason", [(0, 20, "budget"), (100, 19, "bench target")])
def test_prep_fails_before_pressing_when_budget_or_target_is_wrong(env, budget, hp, reason):
    lua, routes = env
    lua.execute("""
        presses=0
        c={party=function() return {{hp=20}} end,find=function() return {slot=1,hp=HP} end,
           in_battle=function() return false end,peek=function() return 0x02025000 end,
           G={map=function() return 3,1 end,pos=function() return 24,39 end,
              tap=function() presses=presses+1 end},
           SP={SB1_KEYITEMS_POCKET_OFFSET=0x3B8,BAG_KEYITEMS_COUNT=30}}
        t={START={24,39},SEGMENTS={{'Up',8,{24,31}}},after_scene=function() return false end,
           before_scene=function() return true end}
    """)
    g = lua.globals()
    g.HP = hp
    ok, why = routes.enter_trainer(g.c, g.t, lambda: 10, "prep", 102,
                                  lua.table_from({"max_frames": budget, "target_key": "K",
                                                  "target_slot": 1, "target_hp": 20}))
    assert ok is False and reason in why
    assert g.presses == 0


def test_budget_covers_nested_helpers_and_restores_frameadvance(env):
    lua, routes = env
    lua.execute("""
        n=0; old=function() n=n+1 end; e={frameadvance=old}
        frame=function() return n end
        helper=function() for i=1,5 do e.frameadvance() end end
    """)
    g = lua.globals()
    ok, why = routes.with_budget(g.e, g.frame, 3, g.helper)
    assert not ok and "PREPARATION frame budget" in why and g.n == 3
    assert lua.eval("e.frameadvance==old")


def test_nested_helper_stops_on_first_fainted_lead_frame(env):
    lua, routes = env
    lua.execute("""
        n=0; old=function() n=n+1 end; e={frameadvance=old}
        frame=function() return n end
        check=function() assert(n<2,'PREPARATION lead fainted') end
        helper=function() for i=1,20 do e.frameadvance() end end
    """)
    g = lua.globals()
    ok, why = routes.with_budget(g.e, g.frame, 50, g.helper, g.check)
    assert not ok and "lead fainted" in why and g.n == 2
    assert lua.eval("e.frameadvance==old")
