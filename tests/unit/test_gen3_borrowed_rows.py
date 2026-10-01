"""MODEL checks against real DuoRun helpers, existing RR bytes and actual ROM. No new game fixture."""
import json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/"tools")]
import e2e_duo as h
from server.adapters import gen3_codec as c
from tools import gen3_borrowed_rows as d


def runner(case):
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
    values=[("BORROW_BASELINE",dict(key=r._link_keys["a"],raw_party_hex=raw,rom_sha1=facts["rom_sha1"])),
            ("BORROW_SIGNAL",dict(kind="borrowed_party_begin")),
            ("BORROW_BATTLE",dict(outcome=2)),("BORROW_SIGNAL",dict(kind="borrowed_party_end")),
            ("BORROW_RESTORED",dict(key=r._link_keys["a"],borrowed=False))]
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


def opponent_model():
    """Actual DuoRun fixture/codec records, with the command's own-HP0 consequence."""
    r=runner("opponent");texts=receipts(r)
    texts["a"]=texts["a"].replace('"kind": "borrowed_party_begin"','"kind": "borrowed_party_opponent_begin"')
    held=dict(frames=120,party_write_count=0,hidden_ticks=4,start_frame=100,end_frame=220)
    texts["a"]=texts["a"].replace("SAVE_WITNESS ","BORROW_HELD "+json.dumps(held)+"\nSAVE_WITNESS ")
    a,b=r._gen3_fixture_saved("a"),r._gen3_fixture_saved("b")
    from copy import deepcopy
    a=deepcopy(a);a[0][1]["hp"]=0
    r._gen3_saved=lambda pid:a if pid=="a" else b
    r._links_json=lambda:[]
    return r,texts

def test_opponent_row_uses_native_option1_and_new_begin_kind():
    r,texts=opponent_model();facts=d.own_facts(r)
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
    early='BORROW_SIGNAL '+json.dumps({'kind':'borrowed_party_end'})+'\n'
    texts['a']=texts['a'].replace('BORROW_SIGNAL ',early+'BORROW_SIGNAL ',1)
    d.saved_oracle(r,texts)
    # Keep the actual early LoadPlayerParty, but remove the post-borrow restore.
    marker='BORROW_SIGNAL '+json.dumps({'kind':'borrowed_party_end'})
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
                if button=='Right' or button=='Down' then at=math.min(at+1,AVAILABLE-1)
                elseif button=='Up' then at=math.max(0,at-1)
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
