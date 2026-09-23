"""Read-only ROM tile verification and injected route/snapshot falsifiers; no emulator."""
import json
import re
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
        c={play={},party=function() return {{hp=20,level=6,max_hp=20}} end,log=function() end,find=function() return {slot=1,hp=HP} end,
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


def test_prep_budget_covers_pret_experience_gap_and_nurse_trips(env):
    lua, routes = env
    species = (PRET / "src/data/pokemon/species_info.h").read_text()
    squirtle = species.split("[SPECIES_SQUIRTLE] =")[1].split("\n    },")[0]
    assert ".growthRate = GROWTH_MEDIUM_SLOW" in squirtle
    tables = (PRET / "src/data/pokemon/experience_tables.h").read_text()
    assert "(6 * CUBE(n)) / 5 - (15 * SQUARE(n)) + (100 * n) - 140" in tables
    encounters = json.loads((PRET / "src/data/wild_encounters.json").read_text())
    yields = []
    for group in encounters["wild_encounter_groups"]:
        for area in group.get("encounters", []):
            if area["map"] not in ("MAP_ROUTE1", "MAP_ROUTE2"):
                continue
            for mon in area["land_mons"]["mons"]:
                info = species.split(f'[{mon["species"]}] =')[1].split("\n    },")[0]
                base = int(re.search(r"\.expYield = (\d+)", info)[1])
                yields.append(base * mon["min_level"] // 7)
    assert min(yields) == 15
    for level, exp, wins in [(6, 179, 73), (9, 419, 57)]:
        budget = routes.preparation_budget(lua.table_from({"level": level, "experience": exp}), 13)
        assert budget >= 30000 + wins * 24000
        assert budget <= 1800000


def test_runner_and_partner_allow_the_full_preparation_budget(env):
    from tools import e2e_duo

    lua, _ = env
    cfg = e2e_duo.SCENARIOS["trainer_bench_gen3"]
    # At the configured 16x, a 1.8M-frame prep needs 1875 ideal seconds; allow CPU/I/O
    # contention and post-READY proof. B must wait just as long without its frame guard firing.
    assert cfg["timeout"] >= 7200
    assert cfg["frames"] >= cfg["timeout"] * 60 * 16
    carrier = lua.execute((ROOT / "lua/tests/duo/scenario_gen3_battle_window.lua").read_text())
    lua.execute("""
        wait_seconds=0
        c={player='b',D={battle_window_case='trainer_bench'},wait_go=function() return true end,
           wait_until=function(fn,s) wait_seconds=s;return fn() end,
           partner_result=function() return 'RESULT: PASS' end}
    """)
    assert carrier(lua.globals().c)[0]
    assert lua.globals().wait_seconds >= cfg["timeout"]


@pytest.mark.parametrize("fail", [False, True])
def test_shared_transit_escapes_instead_of_fighting_and_restores_policy(env, fail):
    lua, routes = env
    lua.execute("""
        attacks=0; escapes=0
        old=function() attacks=attacks+1; error('lead fainted at HP5') end
        c={play={fight_through=old},run_away=function() escapes=escapes+1;return true end,
           log=function() end}
        transit=function()
            assert(c.play.fight_through({})) -- same dispatch as playlib.handle_encounter
            if FAIL then error('route blocked') end
            return true
        end
    """)
    g = lua.globals()
    g.FAIL = fail
    ok, why = routes.with_incidental_escape(g.c, "prep", g.transit)
    assert ok is not fail
    if fail:
        assert "route blocked" in why
    assert g.escapes == 1 and g.attacks == 0
    assert lua.eval("c.play.fight_through==old")


def test_training_heals_before_hunt_and_runs_at_low_hp(env):
    lua, routes = env
    lua.execute("""
        events={}; m={level=6,experience=179,hp=8,max_hp=25,status=0,moves={33},pp={30}}
        battle=false; hunts=0
        c={party=function() return {m} end,log=function() end,
           hunt=function() events[#events+1]='hunt';hunts=hunts+1;battle=true;return true end,
           in_battle=function() return battle end,
           await_turn=function() return battle and 'action' or 'over' end,
           use_move=function()
               events[#events+1]='attack'
               if hunts==1 then m.hp=12 else m.level=13;battle=false end
               return true
           end,
           run_away=function() events[#events+1]='run';battle=false;return true end,
           play={wait_scene_settled=function() return true end}}
        heal=function() events[#events+1]='heal';m.hp=m.max_hp end
        guard=function() end
    """)
    g = lua.globals()
    routes.train(g.c, "prep", 13, g.heal, g.guard)
    assert list(g.events.values()) == ["heal", "hunt", "attack", "run", "heal", "hunt", "attack"]


def test_training_can_finish_normal_four_hit_pidgey_before_healing(env):
    lua, routes = env
    lua.execute("""
        hits=0;heals=0;battle=false
        m={level=6,hp=23,max_hp=23,status=0,moves={33},pp={30}}
        c={party=function() return {m} end,log=function() end,
           hunt=function() battle=true;return true end,in_battle=function() return battle end,
           await_turn=function() return battle and 'action' or 'over' end,
           use_move=function()
               hits=hits+1
               if hits==4 then m.level=13;battle=false else m.hp=m.hp-3 end
               return true
           end,
           run_away=function() error('healthy lead abandoned a winnable battle') end,
           play={wait_scene_settled=function() return true end}}
        heal=function() heals=heals+1;m.hp=23 end
        guard=function() end
    """)
    g = lua.globals()
    routes.train(g.c, "prep", 13, g.heal, g.guard)
    assert g.hits == 4 and g.heals == 1


def test_preparation_wraps_actual_shared_follow_and_logs_nested_frames(env):
    lua, routes = env
    lua.globals().r = routes
    lua.execute("""
        f=0;x=24;y=39;g=3;n=1;logs={};attacks=0;escapes=0
        old=function() attacks=attacks+1;error('unmanaged battle') end
        e={frameadvance=function() f=f+1 end}
        c={emulator=e,cp={},party=function() return {{level=13,experience=1261,hp=30,max_hp=30,status=0}} end,
           find=function() return {slot=1,hp=15} end,in_battle=function() return false end,
           on_field=function() return true end,peek=function() return 1 end,
           log=function(s) logs[#logs+1]=s end,frames=function() e.frameadvance() end,
           run_away=function() escapes=escapes+1;return true end,
           walk_to_pc=function() error('HEAL_REACHED') end,
           G={map=function() return g,n end,pos=function() return x,y end,
              tap=function() y=y-1;e.frameadvance() end,pred_ok=function() return true end},
           play={fight_through=old,follow=function()
               c.play.fight_through({})
               for i=1,6001 do e.frameadvance() end
           end},
           SP={DEST={route1_north={group=3,num=19,x=12,y=0}},warp_to=function(_,_,_,d)
                g=d.group;n=d.num;x=d.x;y=d.y end}}
        t={START={24,39},TRIGGER={24,38},SEGMENTS={},after_scene=function() return true end}
        r.paths.tutorial_to_town={3,1,24,38,24,38,''}
        prep={max_frames=30000,target_key='K',target_slot=1,target_hp=15,level_floor=13}
    """)
    g = lua.globals()
    ok, why = routes.enter_trainer(g.c, g.t, lambda: g.f, "prep", 102, g.prep)
    assert not ok and "HEAL_REACHED" in why
    assert g.escapes == 2 and g.attacks == 0
    assert lua.eval("c.play.fight_through==old and e.frameadvance~=nil")
    progress = [s for s in g.logs.values() if s.startswith("PREP_PROGRESS")]
    assert len(progress) >= 3
    assert all("level=13 exp=1261 hp=30/30" in s and "frames=" in s for s in progress)
