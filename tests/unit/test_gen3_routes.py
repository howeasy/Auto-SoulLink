"""Read-only ROM tile verification and injected route/snapshot falsifiers; no emulator."""
import json
import re
from pathlib import Path

import pytest
from lupa import LuaRuntime

from tools import gba_map

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "lua/tests/gen3_routes.lua"
ROMS = {"firered": "Pokemon - FireRed Version (USA).gba", "leafgreen": "Pokemon - LeafGreen Version (USA).gba"}
MAPS = {(3, 1): "ViridianCity", (3, 20): "Route2", (15, 0): "Route2_ViridianForest_SouthEntrance",
        (1, 0): "ViridianForest"}

def _up(rel):
    """`rel` under the checkout root or the nearest ancestor holding it: a worktree has no .cache or
    ROMs of its own, the main checkout does. Never counts levels (parents[2] raised IndexError on the
    main checkout and silently pointed elsewhere at any other worktree depth)."""
    for d in (ROOT, *ROOT.parents):
        if (d / rel).exists():
            return d / rel
    return ROOT / rel


PRET = _up(".cache/pret/pokefirered")


def _need_pret():
    if not PRET.exists():
        pytest.skip(f"pret pokefirered not cloned ({PRET})")


def _rom(title):
    p = _up(ROMS[title])
    if not p.exists():
        pytest.skip(f"{ROMS[title]} not present (ROMs are gitignored)")
    return p



@pytest.fixture
def env():
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua, lua.execute(SOURCE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("title", ROMS)
def test_every_route_tile_against_rom_and_all_event_objects(env, title):
    _need_pret()
    _, routes = env
    rom = gba_map.load(_rom(title), sym_path=ROOT / f"data/gen3/pret/poke{title}.sym")
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
    _need_pret()
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
    # G4-SYNTH-TRAINER: A boots the cached-native trainer fixture (one step to Rick), so the row
    # needs no 1.8M-frame prep; the frame guard still covers the whole wall budget at 16x, and
    # B must wait at least as long as the runner does.
    assert cfg["target"]["a"] == "trainer"
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


@pytest.mark.parametrize("title", ROMS)
def test_learning_prompt_command_pins_match_both_roms(title):
    syms = {}
    for line in (ROOT / f"data/gen3/pret/poke{title}.sym").read_text().splitlines():
        parts = line.split()
        if len(parts) == 4:
            syms.setdefault(parts[3], int(parts[0], 16))
    rom = _rom(title).read_bytes()
    start = syms["BattleScript_AskToLearnMove"] - 0x08000000
    assert rom[start + 17] == 0x5A
    assert rom[start + 32] == 0x5B
    assert int.from_bytes(rom[start + 33:start + 37], "little") == start + 0x08000000
    assert syms["BattleScript_ForgotAndLearnedNewMove"] == start + 0x08000000 + 45


def test_prompt_declines_first_question_and_confirms_stop_only_when_ready(env):
    lua, routes = env
    lua.execute("""
        logs={};mem={};s={gBattlescriptCurrInstr=1,gBattleScripting=100,
          gBattleCommunication=200,gBattleControllerExecFlags=2,gMoveToLearn=3,
          BattleScript_AskToLearnMove=1000,BattleScript_ForgotAndLearnedNewMove=1045}
        io_={u8=function(a) return mem[a] or 0 end,u16=function(a) return mem[a] or 0 end,
             u32=function(a) return mem[a] or 0 end}
        mem[3]=55;mem[1017]=0x5A;mem[1032]=0x5B
        log=function(t) logs[#logs+1]=t end
    """)
    g = lua.globals()
    prompt = routes.move_prompt(g.io_, g.s, g.log)
    g.mem[1] = 1017
    assert prompt() == (True, None)  # window not initialized
    g.mem[131] = 1
    assert prompt() == (True, "B")
    g.mem[1] = 1032
    g.mem[201] = 1
    assert prompt() == (True, "Up")  # never A on NO
    g.mem[201] = 0
    assert prompt() == (True, "A")
    g.mem[2] = 1
    assert prompt() == (True, None)
    g.mem[1] = 2000
    assert prompt() is False
    assert any("PREP_MOVE_PROMPT" in s and "move=55" in s for s in g.logs.values())


def test_training_handles_level13_prompt_while_battle_is_still_live(env):
    lua, routes = env
    lua.execute("""
        m={level=12,hp=35,max_hp=35,status=0,moves={33},pp={30}}
        battle=false;prompt=false;handled=0
        policy=function() handled=handled+1;prompt=false;return true,'A' end
        c={party=function() return {m} end,log=function() end,move_prompt=policy,
           hunt=function() battle=true;return true end,in_battle=function() return battle end,
           await_turn=function(_,_,handler)
               if prompt then
                   assert(handler,'B-only wait loops at Stop learning Water Gun')
                   assert(battle and m.level==13)
                   handler();battle=false;return 'over'
               end
               return 'action'
           end,
           use_move=function() m.level=13;prompt=true;return true end,
           play={wait_scene_settled=function() return true end}}
        heal=function() end;guard=function() end
    """)
    g = lua.globals()
    routes.train(g.c, "prep", 13, g.heal, g.guard)
    assert g.handled == 1 and not g.battle


def test_real_await_turn_uses_prompt_policy_and_releases_button_edges(env):
    lua, _ = env
    source = (ROOT / "lua/tests/duo/duo_gen3_main.lua").read_text()
    body = source[source.index("function ctx.await_turn("):source.index("--- At the action menu")]
    lua.execute("""
        phase='forget';cursor=1;held=nil;presses={};battle=true;cp={}
        ctx={wait_until=function(fn)
            for i=1,100 do
                local result=fn()
                if result then return result end
                if held then
                    presses[#presses+1]=held
                    if phase=='forget' and held=='B' then phase='stop'
                    elseif phase=='stop' and held=='Up' then cursor=0
                    elseif phase=='stop' and held=='A' and cursor==0 then phase='done';battle=false
                    elseif phase=='stop' and held=='B' then phase='forget' end
                end
            end
        end}
        joypad={set=function(buttons) held=nil;for k in pairs(buttons) do held=k end end}
        play={in_battle=function() return battle end}
        party_menu_up=function() return false end;action_menu_up=function() return false end
        policy=function()
            if phase=='forget' then return true,'B' end
            if phase=='stop' then return true,cursor==0 and 'A' or 'Up' end
            return false
        end
    """)
    lua.execute(body)
    g = lua.globals()
    assert g.ctx.await_turn(60, "B", g.policy) == "over"
    assert list(g.presses.values()) == ["B", "Up", "A"]


@pytest.mark.parametrize("blocked", [False, True, "locked"])
def test_first_tutorial_leg_waits_for_controls_with_await_policy_loaded(env, blocked):
    lua, routes = env
    source = (ROOT / "lua/tests/duo/duo_gen3_main.lua").read_text()
    body = source[source.index("function ctx.await_turn("):source.index("--- At the action menu")]
    lua.globals().r = routes
    lua.execute("""
        f=0;x=24;y=39;presses=0;logs={};await_calls=0;first_press=nil
        c={cp={},play={},party=function() return {{level=9,experience=428,hp=27,max_hp=27}} end,
           find=function() return {slot=1,hp=17} end,in_battle=function() return false end,
           on_field=function() return true end,peek=function() return 1 end,
           log=function(s) logs[#logs+1]=s end,frames=function() f=f+1 end,
           wait_until=function() await_calls=await_calls+1;error('battle wait during tutorial') end,
           G={map=function() return 3,1 end,pos=function() return x,y end,
              pred_ok=function(_,name) return f>=100 and BLOCKED~='locked' end,
              pred=function(_,name) return f>=100 and BLOCKED~='locked' and 0 or 1,0 end,
              tap=function(button)
                  first_press=first_press or f;presses=presses+1;f=f+1
                  if f>=100 and not BLOCKED and button=='Up' then y=y-1 end
              end},
           SP={DEST={route1_north={}},warp_to=function() error('PREFIX_COMPLETE') end}}
        ctx=c
        t={START={24,39},TRIGGER={24,30},SEGMENTS={{'Up',8,{24,31}}},
           after_scene=function() return true end}
        r.paths.tutorial_to_town={3,1,24,30,24,30,''}
        prep={max_frames=5000,target_key='K',target_slot=1,target_hp=17,level_floor=13}
    """)
    lua.execute(body)  # actual new await/edge code is loaded, not a stand-in
    g = lua.globals()
    g.BLOCKED = blocked
    ok, why = routes.enter_trainer(g.c, g.t, lambda: g.f, "prep", 102, g.prep)
    assert not ok
    assert g.await_calls == 0  # neither await nor its edge clearing runs on this path
    if blocked == "locked":
        assert "controls never settled" in why and g.presses == 0
        assert any("PREP_BLOCKED_READY" in s and "field_controls_locked=1/0" in s
                   and "script_context_status=1/0" in s for s in g.logs.values())
    elif blocked:
        assert "route blocked going Up" in why
        assert any("PREP_BLOCKED" in s and "field_controls_locked=0/0" in s
                   and "script_context_status=0/0" in s for s in g.logs.values())
    else:
        assert "PREFIX_COMPLETE" in why
        assert (g.x, g.y, g.presses) == (24, 30, 9)
        assert g.first_press >= 100


def route_motion(lua):
    """Exercise the driver's real local step/warp functions, with only IO/time faked."""
    source = SOURCE.read_text()
    lua.globals().R = lua.execute(source)
    step = source[source.index("    local function step("):source.index("    local function walk(")]
    warp = source[source.index("    local function warp("):source.index("    local function lead()", source.index("    local function warp("))]
    return lua.execute(step + warp + "\nreturn {step=step,warp=warp}")


@pytest.mark.parametrize("title", ROMS)
def test_gate_nonanimated_door_then_forest_arrow_landing_waits_for_unlock(env, title):
    _need_pret()
    lua, _ = env
    rom = gba_map.load(_rom(title), sym_path=ROOT / f"data/gen3/pret/poke{title}.sym")
    gate, forest = rom.map(15, 0), rom.map(1, 0)
    assert (gate.collision[1][7], gate.behaviour[1][7]) == (0, 0x60)
    assert (gate.collision[2][7], gate.behaviour[2][7]) == (0, 0)
    assert (forest.collision[62][29], forest.behaviour[62][29]) == (0, 0x65)
    assert (forest.collision[61][29], forest.behaviour[61][29]) == (0, 0)
    events = json.loads((PRET / "data/maps/Route2_ViridianForest_SouthEntrance/map.json").read_text())
    assert events["warp_events"][3] == {
        "x": 7, "y": 1, "elevation": 3, "dest_map": "MAP_VIRIDIAN_FOREST", "dest_warp_id": "0"}
    arrival = json.loads((PRET / "data/maps/ViridianForest/map.json").read_text())["warp_events"][0]
    assert (arrival["x"], arrival["y"]) == (29, 62)
    lua.execute("""
        g=15;n=0;x=7;y=2;f=0;first_press=nil;label='gate';delta={Up={0,-1}}
        c={cp={},in_battle=function() return false end,G={
           map=function() return g,n end,pos=function() return x,y end},
           SP={warp_to=function(_,dir,_,dest)
               assert(dir=='Up' and g==15 and n==0 and x==7 and y==2)
               -- Step onto non-animated door7,1; step event warps before returning.
               g=dest.group;n=dest.num;x=dest.x;y=dest.y
           end}}
        guard=function() end;quiet=function() return f>=100 end
        at=function(a,b,u,v) return g==a and n==b and x==u and y==v end
        field_diagnostic=function() end
        tick=function(button)
            f=f+1
            if button then first_press=first_press or f;if quiet() then y=y-1 end end
        end
        await=function(pred,limit)
            for i=1,limit do if pred() then return true end;tick() end
            return false
        end
        dest={group=1,num=0,x=29,y=62}
    """)
    motion = route_motion(lua)
    g = lua.globals()
    motion.warp("Up", g.dest)
    motion.step("Up", False)
    assert (g.g, g.n, g.x, g.y) == (1, 0, 29, 61)
    assert g.first_press >= 100


@pytest.mark.parametrize("destination", [1, -1, 255])
def test_step_accepts_only_valid_map_change_without_coordinate_change(env, destination):
    lua, _ = env
    lua.execute("""
        g=15;n=0;x=7;y=2;presses=0;delta={Up={0,-1}}
        c={cp={},in_battle=function() return false end,G={
           map=function() return g,n end,pos=function() return x,y end}}
        tick=function(button) if button then presses=presses+1;g=DESTINATION;n=0 end end
        guard=function() end;field_diagnostic=function() end
    """)
    lua.globals().DESTINATION = destination
    motion = route_motion(lua)
    if destination == 1:
        motion.step("Up", False)
        assert lua.globals().presses == 1
    else:
        with pytest.raises(Exception, match="route blocked going Up"):
            motion.step("Up", False)
        assert lua.globals().presses == 60


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("landed", [False, True])
def test_walk_waits_for_delayed_encounter_and_does_not_repeat_completed_step(env, shared, landed):
    lua, routes = env
    lua.execute("""
        f=0;x=10;y=56;phase='field';fled=0;presses=0;delta={Right={1,0}}
        label='Route2';logs={}
        quiet=function() return phase=='field' or phase=='escaped' end
        c={cp={},in_battle=function() return phase=='battle' end,on_field=quiet,
           log=function(s) logs[#logs+1]=s end,
           G={pos=function() return x,y end,map=function() return 3,20 end,
              pred_ok=quiet},play={fight_through=function() error('unmanaged fight') end}}
        tick=function(button)
            f=f+1
            if phase=='field' and button then
                phase='transition';presses=presses+1
                if LANDED then x=x+1 end
            elseif phase=='escaped' and button then x=x+1;presses=presses+1 end
            if phase=='transition' and f>=180 then phase='battle' end
            if phase=='exit' and f>=200 then phase='escaped' end
        end
        c.frames=function() tick() end
        c.run_away=function() assert(phase=='battle');fled=fled+1;phase='exit';return true end
        guard=function() end;field_diagnostic=function() end
        old_step=function()
            local oldx=x
            for i=1,60 do tick('Right');if x~=oldx then return true end end
            return false,'stalled'
        end
        c.play.step=old_step
        follow=function() return c.play.step(c.cp,'Right',1,true,nil) end
    """)
    g = lua.globals()
    g.LANDED = landed
    if shared:
        ok, result = routes.with_incidental_escape(g.c, "prep", g.follow)
        assert ok and result
        assert lua.eval("c.play.step==old_step")
    else:
        route_motion(lua).step("Right", True)
    assert g.fled == 1 and g.x == 11 and g.phase == "escaped"
    assert g.presses == (1 if landed else 2)


@pytest.mark.parametrize("title", ROMS)
def test_route2_blocked_tiles_are_tall_grass_on_both_roms(title):
    rom = gba_map.load(_rom(title), sym_path=ROOT / f"data/gen3/pret/poke{title}.sym")
    m = rom.map(3, 20)
    assert [(m.collision[56][x], m.behaviour[56][x]) for x in (10, 11)] == [(0, 2), (0, 2)]


@pytest.mark.parametrize("never_ready", [False, True])
def test_shared_walk_transition_is_bounded_and_preserves_hunt_ownership(env, never_ready):
    lua, routes = env
    lua.execute("""
        f=0;started=false
        old=function() started=true;return false,'stalled' end
        fight=function() end
        c={cp={},play={step=old,fight_through=fight},log=function() end,
           frames=function() f=f+1 end,on_field=function() return not started end,
           in_battle=function() return started and f>=120 and not NEVER end,
           run_away=function() error('hunt encounter was consumed') end,
           G={pred_ok=function() return not started end,pos=function() return 10,56 end}}
        fn=function()
            local ok,why=c.play.step(c.cp,'Right',1,true,false)
            assert(not ok);return why
        end
    """)
    g = lua.globals()
    g.NEVER = never_ready
    ok, why = routes.with_incidental_escape(g.c, "hunt", g.fn)
    assert lua.eval("c.play.step==old and c.play.fight_through==fight")
    if never_ready:
        assert not ok and "transition never reached" in why and g.f == 1800
    else:
        assert ok and why == "in_battle" and g.f == 120


def test_shared_walk_retries_when_transition_returns_to_field_without_battle(env):
    lua, routes = env
    lua.execute("""
        f=0;x=10;calls=0
        c={cp={},log=function() end,frames=function() f=f+1 end,
           on_field=function() return calls==0 or f>=120 end,in_battle=function() return false end,
           run_away=function() error('no battle to escape') end,
           G={pred_ok=function() return true end,pos=function() return x,56 end},
           play={step=function()
               calls=calls+1
               if calls==1 then return false,'stalled' end
               x=x+1;return true
           end}}
        fn=function() return c.play.step(c.cp,'Right',1,true,nil) end
    """)
    g = lua.globals()
    assert routes.with_incidental_escape(g.c, "prep", g.fn) == (True, True)
    assert g.calls == 2 and g.f == 120 and g.x == 11


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


def test_a_cached_trainer_fixture_skips_the_t2_walk_and_meets_rick(env):
    """G4-SYNTH-TRAINER (6e85ddfc): {firered,leafgreen}_party_trainer.sav stands at (41,45) on
    Viridian Forest 1.0, one step west of Rick 102's sight line. run() settles, logs PREP_READY,
    then PREP_FIXTURE -- no tutorial, training, heal or walk -- and takes the one step Right into
    the same Rick asserts. A save anywhere else still needs the town start tile."""
    lua, routes = env
    lua.globals().r = routes
    lua.execute("""
        f=0;x=41;y=45;g=1;n=0;logs={};battling=false;steps={}
        c={cp={},battler_slot=function() return 0 end,
           party=function() return {{level=13,experience=1261,hp=40,max_hp=40,status=0}} end,
           find=function() return {slot=1,hp=15} end,in_battle=function() return battling end,
           on_field=function() return true end,
           peek=function() error('the tutorial precondition ran') end,
           log=function(s) logs[#logs+1]=s end,frames=function() f=f+1 end,
           walk_to_pc=function() error('HEAL_REACHED') end,
           battle_window_snapshot=function()
               return {battle_permit=true,is_trainer=true,trainer_id=102,outcome=0} end,
           G={map=function() return g,n end,pos=function() return x,y end,
              tap=function(dir) f=f+1; steps[#steps+1]=dir; if dir=='Right' then x=x+1; battling=true end end,
              pred_ok=function() return not battling end},
           play={fight_through=function() error('no fight') end,follow=function() error('no walk') end}}
        t={START={24,39},TRIGGER={24,38},SEGMENTS={}}
        prep={max_frames=30000,target_key='K',target_slot=1,target_hp=15,level_floor=13}
    """)
    g = lua.globals()
    assert routes.enter_trainer(g.c, g.t, lambda: g.f, "prep", 102, g.prep) is True
    logs = list(g.logs.values())
    assert any(s.startswith("PREP_READY ") for s in logs)
    assert "PREP_FIXTURE trainer at=(41,45)" in logs
    assert logs.index(next(s for s in logs if s.startswith("PREP_READY "))) < logs.index(
        "PREP_FIXTURE trainer at=(41,45)")
    assert not any(s.startswith(("PREP_TUTORIAL", "PREP_ROUTE", "PREP_HEAL")) for s in logs)
    assert list(g.steps.values()) == ["Right"]
    lua.execute("x=12;y=37;g=3;n=19;battling=false")              # neither fixture tile
    ok, why = routes.enter_trainer(g.c, g.t, lambda: g.f, "prep", 102, g.prep)
    assert not ok and "T2 needs the town or the trainer fixture" in why
