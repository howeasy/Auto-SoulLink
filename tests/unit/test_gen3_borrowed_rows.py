"""MODEL checks against real DuoRun helpers, existing RR bytes and actual ROM. No new game fixture."""
import json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/"tools")]
import e2e_duo as h
from server.adapters import gen3_codec as c
from tools import gen3_borrowed_rows as d


def runner(case):
    # Absent companion build skips (tests/TESTING.md); a present-but-wrong one still fails
    # own_facts' COMPANION_SHA1 check.
    if not (ROOT/h.ROM_REL).is_file():
        pytest.skip(f"RR companion build absent: {h.ROM_REL}")
    r=object.__new__(h.DuoRun)
    r.game="gen3_rr";r.gcfg=h.GAMES["gen3_rr"];r.scenario="borrowed_party_"+case+"_gen3"
    r.cfg=dict(d.ROWS[r.scenario]);r.attempt=1
    a,b=r._gen3_fixture_saved("a"),r._gen3_fixture_saved("b")
    r._link_keys={"a":h.gen3_key(a[0][1]),"b":h.gen3_key(b[0][1])}
    r._gen3_flushed=lambda pid:r._gen3_fixture_bytes(pid)
    r._gen3_flush_boundary=lambda:None # no emulator; saved bytes are the existing fixture
    r._links_json=lambda:[{"status":"alive","a":{"key":r._link_keys["a"]},"b":{"key":r._link_keys["b"]}}]
    r._pydec_note=lambda text:None
    return r


def receipts(r):
    image=r._gen3_fixture_bytes("a")
    parsed=c.parse_flash(image,cfru=True);count=parsed["sb1"][0x34]
    raw=[parsed["sb1"][0x38+i*100:0x38+(i+1)*100].hex() for i in range(count)]
    facts=d.own_facts(r)
    # Same order the retained 3008cd9b cut observed: leading inactive end, begin,
    # held window, registered loan end, queued HP0 write, restore marker.
    own=r._gen3_fixture_saved("a")[0][1]
    values=[("BORROW_BASELINE",dict(key=r._link_keys["a"],raw_party_hex=raw,rom_sha1=facts["rom_sha1"])),
            ("BORROW_SIGNAL",dict(kind="borrowed_party_begin",frame=300)),
            ("BORROW_BATTLE",dict(outcome=2)),("BORROW_SIGNAL",dict(kind="borrowed_party_end",frame=400)),
            ("BORROW_RESTORED",dict(key=r._link_keys["a"],borrowed=False,frame=500,
                                    hp=own["hp"] if r.scenario.endswith("_battle_gen3") else 0))]
    return {"a":"\n".join(tag+" "+json.dumps(value) for tag,value in values)+"\nSAVE_WITNESS borrowed counter=4->5\n",
            "b":"RESULT: PASS (idle peer; no save)\n"}




def test_actual_duorun_rom_route_and_both_rows():
    for case in ("menu","battle"):
        r=runner(case);f=d.own_facts(r)
        # School's raw destination warp is (4,7); retained cd888b59 physical
        # destination confirms it. Center's separate +1 landing cannot be transferred here.
        assert f["arrival"]==[4,7] and len(f["paths"]["city"])==13 and len(f["paths"]["school"])==6
        assert f["menu_option"]==(0 if case=="menu" else 3)
        assert r.cfg["no_save"]==("b",)


def test_actual_saved_codec_accepts_unchanged_borrow_battle_and_rejects_missing_restore():
    r=runner("battle");texts=receipts(r)
    d.saved_oracle(r,texts)
    texts["a"]=texts["a"].replace('"kind": "borrowed_party_end"','"kind": "unrelated"')
    with pytest.raises(RuntimeError,match="begin/end"):d.saved_oracle(r,texts)


def test_borrow_oracle_rejects_spurious_own_faint_and_wrong_link():
    r=runner("battle");texts=receipts(r)
    texts["a"]+='TX faint '+r._link_keys["a"]+' '+json.dumps(dict(event="faint",key=r._link_keys["a"]))+'\n'
    with pytest.raises(RuntimeError,match="own faint"):d.saved_oracle(r,texts)
    texts=receipts(r);r._links_json=lambda:[]
    with pytest.raises(RuntimeError,match="alive linked"):d.saved_oracle(r,texts)


def test_lua_draft_parses_and_uses_no_game_data_write_apis():
    from lupa import LuaRuntime
    source=(ROOT / "lua/tests/duo/scenario_gen3_borrowed.lua").read_text()
    assert LuaRuntime().execute("return type(assert(load(...)))",source)=="function"
    assert "memory.write" not in source and "ctx.lose_active" not in source


def test_menu_oracle_cannot_accept_saved_healthy_target_as_command_success():
    r=runner("menu");texts=receipts(r);r._links_json=lambda:[]
    texts["a"]=texts["a"].replace("SAVE_WITNESS ","BORROW_HELD "+json.dumps(dict(frames=120,party_write_count=0,hidden_ticks=4,start_frame=100,end_frame=220))+"\nSAVE_WITNESS ")
    with pytest.raises(RuntimeError,match="ownHP0"):d.saved_oracle(r,texts)


def test_actual_route_composes_rr_dialogue_recovery_outside_incidental_wrapper():
    """Run actual carrier, Routes wrapper and traced_follow with a locked post-door scene."""
    from lupa import LuaRuntime
    lua=LuaRuntime(unpack_returned_tuples=True)
    source=(ROOT / "lua/tests/gen3_scripted_play.lua").read_text()
    start=source.index("local function traced_follow(cp, path_name, label)")
    end=source.index("--- Route either admitted respawn interior",start)
    facts=d.own_facts(runner("menu"))
    lua.globals().ROOT=ROOT.as_posix();lua.globals().FACTS=lua.table_from(facts,recursive=True)
    lua.execute(r'''
        F={locked=false,group=3,num=19,x=12,y=37,clears=0,frames=0}
        local delta={Left={-1,0},Right={1,0},Up={0,-1},Down={0,1}}
        PATHS={};TITLE='radical_red';RR_TRACE=false
        G={shot=function() end,finish=function(ok,msg) if not ok then error(msg) end end}
        H={pos=function() return F.x,F.y end,scene_quiet=function() return not F.locked end}
        play={}
        play.map=function() return F.group*256+F.num end
        play.on_field=function() return not F.locked end
        play.in_battle=function() return false end
        play.wait_at=function(_,x,y) return F.x==x and F.y==y end
        play.at=function() return tostring(F.x)..','..tostring(F.y) end
        play.clear_dialogue=function() F.clears=F.clears+1;F.locked=false end
        play.step=function(_,dir)
            if F.locked then return false,'locked' end
            local d=delta[dir];F.x=F.x+d[1];F.y=F.y+d[2];return true
        end
        original_step=play.step
        play.follow=function(cp,name)
            if name=='pc_to_pokecenter_entrance' then F.x,F.y=7,8;return end
            for _,dir in ipairs(PATHS[name].dirs) do assert(play.step(cp,dir,play.map()),'plain step locked') end
        end
        SP={PATHS=PATHS,DEST={center_exit={group=3,num=1,x=26,y=27}}}
        SP.warp_to=function(_,dir,_,dest)
            F.group,F.num,F.x,F.y=dest.group,dest.num,dest.x,dest.y
            F.locked=dir=='Down' -- retained post-Center scene, requires ordinary A
        end
        c={player='a',D={wt=ROOT},SP=SP,play=play,cp={},session={signals={drain=function() return {} end}}}
        c.wait_go=function() return true end
        c.go_value=function(name) return name=='BORROW' and FACTS or 'K1' end
        c.in_battle=play.in_battle;c.on_field=play.on_field
        c.log=function() end;c.jlog=function() end
        c.frames=function(n) F.frames=F.frames+n end
        c.G={pred_ok=function() return not F.locked end,map=function() return F.group,F.num end,
             pos=function() return F.x,F.y end}
        c.walk_to_pc=function() F.group,F.num,F.x,F.y=5,4,11,2 end
        c.follow_path=function(name,path,from,to,label)
            PATHS[name]={from=from,to=to,dirs=path,battles=false};play.follow(c.cp,name,label)
        end
        c.party=function() error('MODEL_REACHED_SCHOOL') end
    ''')
    lua.execute(source[start:end]+"\nSP.traced_follow=traced_follow")
    result=lua.execute("local fn=dofile(ROOT..'/lua/tests/duo/scenario_gen3_borrowed.lua'); return pcall(fn,c)")
    ok,msg=result[:2]
    assert not ok and "MODEL_REACHED_SCHOOL" in str(msg), result
    assert lua.globals().F.clears>0 and lua.globals().F.x==6 and lua.globals().F.y==3
    assert lua.execute("return play.step==original_step") is True


def held_model(case="opponent"):
    """Actual DuoRun fixture/codec records for a non-battle row, carrying the command's
    own-HP0 consequence in the retained cut's order: held window, registered loan ends,
    queued force_faint HP0 write, restore marker."""
    r=runner(case);texts=receipts(r)
    if case=="opponent":
        texts["a"]=texts["a"].replace('"kind": "borrowed_party_begin"','"kind": "borrowed_party_opponent_begin"')
    held=dict(frames=120,party_write_count=0,hidden_ticks=4,start_frame=100,end_frame=220)
    texts["a"]=texts["a"].replace("SAVE_WITNESS ","BORROW_HELD "+json.dumps(held)+"\nSAVE_WITNESS ")
    # The queued force_faint's own-party HP0 landing, logged exactly as the client
    # logs it: slot1's hp field of the real party base, after the registered loan
    # ends (menu 7091 after 6862/6900/7053; opponent 6460 after 6231/6269/6422).
    borrow=d.own_facts(r)["borrow"]
    hp_off,hp_len=next((off,size) for name,off,size in c._PARTY_TAIL if name=="hp")
    hp_at=borrow["party_base"]+c.PARTY_MON_SIZE+hp_off
    texts["a"]=texts["a"].replace("SAVE_WITNESS ",
        "[client] [SLink-gen3] write overworld 0x%X +%d frame 460\nSAVE_WITNESS "%(hp_at,hp_len))
    a,b=r._gen3_fixture_saved("a"),r._gen3_fixture_saved("b")
    from copy import deepcopy
    a=deepcopy(a);a[0][1]["hp"]=0
    r._gen3_saved=lambda pid:a if pid=="a" else b
    r._links_json=lambda:[]
    return r,texts

def test_opponent_row_uses_native_option1_and_new_begin_kind():
    r,texts=held_model();facts=d.own_facts(r)
    assert facts["menu_option"]==1 and facts["begin_kind"]=="borrowed_party_opponent_begin"
    d.saved_oracle(r,texts)
    # A ViewYourTeam hook cannot qualify the different ViewOpponent producer.
    texts["a"]=texts["a"].replace('borrowed_party_opponent_begin','borrowed_party_begin')
    with pytest.raises(RuntimeError,match="begin/end"): d.saved_oracle(r,texts)

def test_school_approach_is_actual_adjacent_plain_tile_not_assumed_counter():
    facts=d.own_facts(runner("opponent"))
    npc=facts["borrow"]["npc"]
    assert abs(facts["approach"][0]-npc["x"])+abs(facts["approach"][1]-npc["y"])==1
    # The former (6,4) is two tiles away and cannot directly interact on plain6,3.
    assert facts["approach"]!=[npc["x"],npc["y"]+2]

def test_leading_inactive_restore_does_not_qualify_or_hide_real_pair():
    r=runner("battle");texts=receipts(r)
    early='BORROW_SIGNAL '+json.dumps({'kind':'borrowed_party_end','frame':200})+'\n'
    texts['a']=texts['a'].replace('BORROW_SIGNAL ',early+'BORROW_SIGNAL ',1)
    d.saved_oracle(r,texts)
    # Keep the actual early LoadPlayerParty, but remove the post-borrow restore.
    marker='BORROW_SIGNAL '+json.dumps({'kind':'borrowed_party_end','frame':400})
    before,after=texts['a'].rsplit(marker,1)
    texts['a']=before+after
    with pytest.raises(RuntimeError,match='begin/end'):d.saved_oracle(r,texts)

@pytest.mark.parametrize('fault',['only_early_end','wrong_begin','extra_distinct_begin'])
def test_restore_prefix_never_supplies_missing_or_wrong_borrow_proof(fault):
    r=runner("battle");texts=receipts(r)
    if fault=='only_early_end':
        texts['a']=texts['a'].replace('"kind": "borrowed_party_begin"','"kind": "borrowed_party_end"')
    elif fault=='wrong_begin':
        texts['a']=texts['a'].replace('"kind": "borrowed_party_begin"','"kind": "borrowed_party_opponent_begin"')
    else:
        texts['a']=texts['a'].replace('BORROW_BATTLE ',
            'BORROW_SIGNAL '+json.dumps({'kind':'borrowed_party_opponent_begin'})+'\nBORROW_BATTLE ',1)
    with pytest.raises(RuntimeError,match='begin/end'):d.saved_oracle(r,texts)

def test_borrow_oracle_binds_hold_loan_end_queued_HP0_and_restore_markers():
    for case in ("menu","opponent"):
        r,texts=held_model(case);notes=[]
        r._pydec_note=notes.append
        d.saved_oracle(r,texts)
        assert any("held end 220 < loan end 400 < own HP0 460 <= restore 500" in n for n in notes),notes

@pytest.mark.parametrize("fault",["restore_before_held_end","loan_end_inside_hold","hp_written_inside_loan",
                                   "wrong_party_address","hp_write_absent","restore_frame_absent"])
def test_fabricated_borrow_order_is_refused(fault):
    """Structure alone let a restore that precedes the hold it claims to follow through."""
    r,texts=held_model("menu")
    if fault=="restore_before_held_end":
        texts["a"]=texts["a"].replace('"frame": 500','"frame": 210')
    elif fault=="loan_end_inside_hold":
        texts["a"]=texts["a"].replace('"borrowed_party_end", "frame": 400','"borrowed_party_end", "frame": 200')
    elif fault=="hp_written_inside_loan":
        texts["a"]=texts["a"].replace("frame 460","frame 380")
    elif fault=="wrong_party_address":
        # Same party region and width, but slot0's HP field rather than the target's.
        hp_off=next(o for n,o,_ in c._PARTY_TAIL if n=="hp")
        base=d.own_facts(r)["borrow"]["party_base"]
        texts["a"]=texts["a"].replace("0x%X"%(base+c.PARTY_MON_SIZE+hp_off),"0x%X"%(base+hp_off))
    elif fault=="hp_write_absent":
        texts["a"]="".join(line for line in texts["a"].splitlines(True) if "write overworld" not in line)
    else:
        texts["a"]=texts["a"].replace(', "frame": 500','')
    with pytest.raises(RuntimeError,match="borrow order"):d.saved_oracle(r,texts)

def test_restored_marker_must_follow_the_loan_end_without_a_held_window():
    r=runner("battle");texts=receipts(r)
    d.saved_oracle(r,texts)
    texts["a"]=texts["a"].replace('"borrowed_party_end", "frame": 400','"borrowed_party_end", "frame": 600')
    with pytest.raises(RuntimeError,match="borrow order"):d.saved_oracle(r,texts)

def test_actual_menu_cancel_block_quits_main_menu_instead_of_reentering_loan():
    from lupa import LuaRuntime
    source=(ROOT/'lua/tests/duo/scenario_gen3_borrowed.lua').read_text()
    start=source.index('        if not ctx.wait_go("RESTORE")')
    end=source.index('    else\n        -- Primary party_menu',start)
    lua=LuaRuntime(unpack_returned_tuples=True)
    state=lua.execute('''
        local state='picker'
        facts={party_cancel_task=0x0811FEA4}
        ctx={wait_go=function() return true end,frames=function() end}
        ctx.task_live=function(name)
            return (state=='main' and name=='Task_MultichoiceMenu_HandleInput')
                or (state=='quit' and name=='Task_YesNoMenu_HandleInput')
        end
        ctx.task_address_live=function(address) return state=='party_cancel' and address==facts.party_cancel_task end
        ctx.wait_until=function(pred) assert(pred(),'wrong task transition');return true end
        ctx.G={tap=function(button)
            if state=='picker' and button=='B' then state='party_cancel'
            elseif state=='party_cancel' and button=='A' then state='main'
            elseif state=='main' and button=='B' then state='quit'
            elseif state=='quit' and button=='A' then state='field'
            else error('reentered loan or wrong native input: '..state..'/'..button) end
        end}
    '''+source[start:end]+'''\nreturn state''')
    assert state=='field'

def test_actual_picker_waits_for_fade_before_native_selection_input():
    """The chooser task exists during fade, but native code ignores its A input."""
    from lupa import LuaRuntime
    source=(ROOT/'lua/tests/duo/scenario_gen3_borrowed.lua').read_text()
    start=source.index('    local function picker()')
    end=source.index('    local function party_writes(',start)
    lua=LuaRuntime(unpack_returned_tuples=True)
    got=lua.execute('''
        local fade,popup=true,false
        local ctx={party_menu_up=function() return true end,
            task_live=function(name) return name=='Task_HandleChooseMonInput' end,
            G={pred_ok=function(_,name) assert(name=='palette_fade_active');return not fade end},cp={}}
    '''+source[start:end]+'''
        local premature=picker()
        local polls=0
        repeat polls=polls+1;if polls==3 then fade=false end until picker() or polls==10
        -- Native Task_HandleChooseMonInput ignores A while gPaletteFade.active.
        if not fade then popup=true end
        return premature,polls,popup
    ''')
    assert got==(False,3,True)

def test_actual_first_loan_press_releases_mash_override_for_new_a_edge():
    from lupa import LuaRuntime
    source=(ROOT/'lua/tests/duo/scenario_gen3_borrowed.lua').read_text()
    start=source.index('            if not ctx.wait_until(picker,30,"fade-ready before loan A")')
    end=source.index('            if not ctx.wait_until(function() return ctx.task_live',start)
    boot=(ROOT/'lua/tests/gen3_boot_check.lua').read_text()
    idle=boot[boot.index('function M.idle(n)'):boot.index('--- Mash A (and Start every 4th beat)')]
    lua=LuaRuntime(unpack_returned_tuples=True)
    presses=lua.execute('''
        local held,last,accepted=true,true,0
        joypad={set=function(keys) held=keys.A==true end}
        local M={advance=function()
            if held and not last then accepted=accepted+1 end
            last=held
        end}
    '''+idle+'''
        local slot=0
        local cursor=function() return slot end
        local picker=function() return true end
        local ctx={G=M,cp={},wait_until=function(p) return p() end,
            jlog=function() end,peek=function() return 0 end,
            emulator={framecount=function() return 1 end}}
        M.pred_ok=function() return true end
    '''+source[start:end]+'''\nreturn accepted''')
    assert presses==1

def test_actual_picker_accepts_bound_rr_direct_handler_after_first_selection_only():
    from lupa import LuaRuntime
    source=(ROOT/'lua/tests/duo/scenario_gen3_borrowed.lua').read_text()
    start=source.index('    local function picker()')
    end=source.index('    local function party_writes(',start)
    lua=LuaRuntime(unpack_returned_tuples=True)
    result=lua.execute('''
        local current=0x0811FB28
        local facts={party_choose_task=0x090B6230}
        local ctx={cp={},party_menu_up=function() return true end,
          task_live=function(name) return name=='Task_HandleChooseMonInput' and current==0x0811FB28 end,
          task_address_live=function(address) return current==address end,
          G={pred_ok=function() return true end}}
    '''+source[start:end]+'''
        local original=picker()
        current=facts.party_choose_task
        local after_selection=picker()
        current=0x090B6232
        local unrelated=picker()
        return original,after_selection,unrelated
    ''')
    assert result==(True,True,False)

@pytest.mark.parametrize('available',[2,3])
def test_actual_native_selection_uses_available_party_and_start_confirmation(available):
    from lupa import LuaRuntime
    source=(ROOT/'lua/tests/duo/scenario_gen3_borrowed.lua').read_text()
    start=source.index('        -- Primary party_menu')
    end=source.index('        if not ctx.mash_until(ctx.in_battle',start)
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.globals().AVAILABLE=available
    result=lua.execute('''
        local at,state,entered,confirmed,starts=0,'choose',0,false,0
        local order={0,0,0};local facts={selected_order_address=100,confirm_slot=6,party_selection_max=3}
        local cursor=function() return at end
        local picker=function() return state=='choose' end
        local u8=function(address) return order[address-99] end
        local selection_trace=function() end
        local ctx={cp={},wait_until=function(p) return p() end,
            jlog=function() end,peek=function() return 0 end,emulator={framecount=function() return 1 end}}
        ctx.party=function() local p={};for i=1,AVAILABLE do p[i]={slot=i-1,key='loan'..i} end;return p end
        ctx.task_live=function(name) return state=='popup' and name=='Task_HandleSelectionMenuInput' end
        ctx.G={idle=function() end,pred_ok=function() return true end,shot=function() end,
            tap=function(button)
                -- RR lays the loan out in TWO columns: row inputs step +/-2, column inputs +/-1.
                if button=='Down' then at=math.min(at+2,AVAILABLE-1)
                elseif button=='Up' then at=math.max(0,at-2)
                elseif button=='Right' then at=math.min(at+1,AVAILABLE-1)
                elseif button=='Left' then at=math.max(0,at-1)
                elseif button=='Start' then starts=starts+1;at=6
                elseif button=='A' and at==6 then confirmed=true
                elseif button=='A' and state=='choose' then state='popup'
                elseif button=='A' and state=='popup' then
                    entered=entered+1;order[at+1]=at+1;state='choose';if entered==3 then at=6 end
                else error('invalid native selection input') end
            end}
        local function run()
    '''+source[start:end]+'''
            return confirmed,entered,starts
        end
        return run()
    ''')
    assert result==(True,available,1 if available==2 else 0)


SCENARIO="lua/tests/duo/scenario_gen3_borrowed.lua"
RR_GRID_STEP={"Down":2,"Up":-2,"Right":1,"Left":-1}   # 0/1, 2/3, 4/5 per the retained cursor shot
_GRID_STEP=[None]

def _grid_step():
    """The scenario's ACTUAL rr_grid_step, executed as written."""
    if _GRID_STEP[0] is None:
        from lupa import LuaRuntime
        source=(ROOT/SCENARIO).read_text()
        start=source.index('        local function rr_grid_step(at,to)')
        end=source.index("\n        end\n",start)+len("\n        end\n")
        _GRID_STEP[0]=LuaRuntime().execute(source[start:end]+"\nreturn rr_grid_step\n")
    return _GRID_STEP[0]

def _walk(start,to):
    """The scenario's own 12-press budget over RR's two-column grid."""
    step,at,presses=_grid_step(),start,[]
    for _ in range(12):
        if at==to:break
        button=step(at,to);presses.append(button)
        at=max(0,min(at+RR_GRID_STEP[button],5))
    return at==to,presses,at

@pytest.mark.parametrize('start,slot',[(a,b) for a in range(6) for b in range(6)])
def test_actual_rr_grid_selection_movement_reaches_every_loan_cell(start,slot):
    """Every ordered pair of visible cells, including 0->1, 2->4 and the live 1->2 stall."""
    reached,presses,at=_walk(start,slot)
    assert reached,f"cursor stuck at {at} after {presses}: {start}->{slot}"

def test_actual_rr_grid_selection_movement_refuses_a_cell_off_the_grid():
    """The stall branch is reachable: no input reaches a cell the two-column grid lacks."""
    reached,presses,at=_walk(0,7)
    assert not reached and at<=5,(presses,at)


MAIN="lua/tests/duo/duo_gen3_main.lua"
_PARTY_PICK=[None]

def _party_pick():
    """The shared party_pick exactly as written, replayed with RR's two-column cursor and
    the scenario's own rr_grid_step; the optional callbacks are supplied or withheld."""
    if _PARTY_PICK[0] is None:
        from lupa import LuaRuntime
        main=(ROOT/MAIN).read_text();borrow=(ROOT/SCENARIO).read_text()
        pick=main[main.index("local function party_pick(slot)"):main.index("--- POK")]
        start=borrow.index('        local function rr_grid_step(at,to)')
        grid=borrow[start:borrow.index("\n        end\n",start)+len("\n        end\n")]
        _PARTY_PICK[0]=LuaRuntime(unpack_returned_tuples=True).execute('''
            local CURSOR,TAPS,SENT,TARGET,STEP,READY,COLUMNS=0,{},false,0,nil,nil,2
            local S={gPartyMenu=0x0203C750,Task_HandleChooseMonInput='choose',Task_HandleSelectionMenuInput='popup'}
            local memory={read_u8=function(address) if address==S.gPartyMenu+9 then return CURSOR end return 0 end}
            local G={tap=function(button)
                TAPS[#TAPS+1]=button
                local delta={Down=COLUMNS,Up=-COLUMNS,Right=1,Left=-1}
                if delta[button] then CURSOR=math.max(0,math.min(CURSOR+delta[button],5)) end
            end}
            local press=function(key) if key=='A' then SENT=true end return true end
            local party_menu_up=function() return true end
            local party_task=function() return true end
            local ctx={wait_until=function(p) return p() end,
                battler_slot=function() return SENT and TARGET or -1 end}
        '''+grid+pick+'''
            local function run(at,slot,step,ready,columns)
                CURSOR,TAPS,SENT,TARGET,COLUMNS=at,{},false,slot,columns
                STEP=step=="grid" and rr_grid_step or nil
                READY=ready=="never" and function() return false end or nil
                ctx.party_cursor_step=STEP;ctx.party_picker_ready=READY
                local ok,why=party_pick(slot)
                return ok,why,#TAPS,table.concat(TAPS,","),CURSOR
            end
            return run
        ''')
    return _PARTY_PICK[0]

def test_actual_party_pick_uses_the_bound_rr_grid_step_for_the_live_send_out():
    """The retained live failure: ctx.send_out(1) under the vertical rule could not cross
    to the next column; the scenario-bound rr_grid_step reaches it."""
    ok,why,taps,pressed,cursor=_party_pick()(0,1,"grid",None,2)
    assert ok and cursor==1,(why,pressed)

def test_actual_party_pick_without_the_optional_callbacks_keeps_the_vertical_default():
    ok,why,taps,pressed,cursor=_party_pick()(0,1,None,None,1)
    assert ok and pressed=="Down",(why,pressed)

def test_actual_party_pick_refuses_while_a_borrower_picker_predicate_is_false():
    """A supplied predicate outranks the old task check and presses nothing; here that
    default would have proceeded, so this cannot pass through a Lua and/or fallback."""
    pick=_party_pick()
    assert pick(0,1,"grid",None,2)[0] is True
    ok,why,taps,pressed,cursor=pick(0,1,"grid","never",2)
    assert not ok and pressed=="" and "never took input" in why,(why,pressed)


def pp_model(case,mutate):
    """Actual fixture records with the saved party's slot-1 PP replaced by `mutate`."""
    from copy import deepcopy
    r=runner(case);texts=receipts(r)
    a,b=deepcopy(r._gen3_fixture_saved("a")),r._gen3_fixture_saved("b")
    a[0][1]["pp"]=mutate(a[0][1])
    r._gen3_saved=lambda pid:a if pid=="a" else b
    return r,texts

def rom_empty_pp(r):
    """RR's own move table PP byte for move 0 (BATTLE_MOVES_ADDR+4) with the PP-Up bonus."""
    return h.gen3_limits("radical_red",(ROOT / r._gen3_rom("a")).read_bytes())["max_pp"]

def healed(mon,max_pp,offset=0):
    return [max_pp(0,mon["pp_bonuses"],i)+offset if m==0 else pp
            for i,(m,pp) in enumerate(zip(mon["moves"],mon["pp"]))]

def test_actual_battle_accepts_the_native_heal_of_the_targets_empty_moves():
    """RR's battle heal refills every move slot from its own move table, so the target's
    UNUSED slots carry the ROM's move-0 PP instead of 0 -- with no harness write."""
    r=runner("battle");max_pp=rom_empty_pp(r)
    mon=r._gen3_fixture_saved("a")[0][1]
    assert any(m==0 for m in mon["moves"]),mon["moves"]
    r,texts=pp_model("battle",lambda m:healed(m,max_pp))
    d.saved_oracle(r,texts)

def test_occupied_move_pp_change_stays_refused_in_battle():
    r,texts=pp_model("battle",lambda mon:[pp+1 if i==next(j for j,m in enumerate(mon["moves"]) if m) else pp
                                         for i,pp in enumerate(mon["pp"])])
    with pytest.raises(RuntimeError,match="record1"):d.saved_oracle(r,texts)

def test_wrong_empty_move_pp_value_stays_refused_in_battle():
    r=runner("battle");max_pp=rom_empty_pp(r)
    r,texts=pp_model("battle",lambda m:healed(m,max_pp,1))
    with pytest.raises(RuntimeError,match="empty move"):d.saved_oracle(r,texts)

def test_menu_row_keeps_empty_move_pp_strict():
    from copy import deepcopy
    r,texts=held_model("menu");max_pp=rom_empty_pp(r)
    mon=r._gen3_fixture_saved("a")[0][1]
    assert any(m==0 for m in mon["moves"]),mon["moves"]
    a=deepcopy(r._gen3_fixture_saved("a"));a[0][1]["pp"]=healed(mon,max_pp);a[0][1]["hp"]=0
    r._gen3_saved=lambda pid:a if pid=="a" else r._gen3_fixture_saved("b")
    with pytest.raises(RuntimeError,match="record1"):d.saved_oracle(r,texts)


@pytest.mark.parametrize("field,value",[("contest",[1,2,3,4,5,6]),("unknown",1),("ribbons",0x80000000)])
def test_battle_changes_the_record_diff_skips_are_still_refused(field,value):
    """gen3_record_diff skips RR's lossy contest/unknown and masks the ribbon bit, so the
    battle row's strict equality has to catch those itself."""
    from copy import deepcopy
    r=runner("battle");texts=receipts(r)
    a=deepcopy(r._gen3_fixture_saved("a"));a[0][1][field]=value
    r._gen3_saved=lambda pid:a if pid=="a" else r._gen3_fixture_saved("b")
    with pytest.raises(RuntimeError,match="beyond the native empty-move heal"):d.saved_oracle(r,texts)
