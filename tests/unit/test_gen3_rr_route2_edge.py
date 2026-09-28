"""Route 1 south connection recovery is bounded by live map, tile and field witnesses."""

from lupa import LuaRuntime


def _drive(body: str):
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua.execute("local Edge=dofile('lua/tests/gen3_rr_route2_edge.lua')\n" + body)


def test_unproven_off_field_state_at_edge_refuses_without_input():
    state = _drive('''
      local c={map=787,x=12,y=39,field=false,battle=false,callback2=0x08123456,
               tasks='summary',warps=0,lines={}}
      local io={state=function() return c end,
        enter_warp=function() c.warps=c.warps+1;c.map=768;return true end,
        log=function(s) c.lines[#c.lines+1]=s end}
      local ok,why=Edge.cross(io)
      assert(ok==false and why:find('off-field',1,true))
      return c
    ''')
    assert (state["warps"], state["map"]) == (0, 787)


def test_new_off_field_nonbattle_state_after_first_press_refuses():
    state = _drive('''
      local c={map=787,x=12,y=39,field=true,battle=false,callback2=0x080556B5,
               tasks='',warps=0}
      local io={state=function() return c end,
        enter_warp=function() c.warps=c.warps+1
          if c.warps==1 then c.field=false;return false,'map never changed from 787' end
          c.map=768;return true end,
        log=function() end}
      local ok,why=Edge.cross(io)
      assert(ok==false and why:find('off-field',1,true))
      return c
    ''')
    assert (state["warps"], state["map"]) == (1, 787)


def test_new_battle_during_crossing_is_fled_before_one_retry():
    state = _drive('''
      local c={map=787,x=12,y=39,field=true,battle=false,callback2=0x080565B5,
               tasks='',fights=0,warps=0}
      local io={state=function() return c end,
        fight_through=function() c.fights=c.fights+1;c.battle=false;c.field=true;return true end,
        settle=function() return true end,
        enter_warp=function() c.warps=c.warps+1
          if c.warps==1 then c.battle=true;c.field=false;c.callback2=0x08011101
            return false,'map never changed from 787' end
          c.map=768;return true end,
        log=function() end}
      local ok=Edge.cross(io)
      assert(ok==true)
      return c
    ''')
    assert (state["fights"], state["warps"], state["map"]) == (1, 2, 768)


def test_second_battle_on_the_only_retry_is_terminal():
    state = _drive('''
      local c={map=787,x=12,y=39,field=true,battle=false,callback2=0x080565B5,
               tasks='',fights=0,warps=0}
      local io={state=function() return c end,
        fight_through=function() c.fights=c.fights+1;c.battle=false;c.field=true;return true end,
        settle=function() return true end,
        enter_warp=function() c.warps=c.warps+1;c.battle=true;c.field=false
          return false,'map never changed from 787' end,
        log=function() end}
      local ok,why=Edge.cross(io)
      assert(ok==false and why:find('retried crossing failed',1,true))
      return c
    ''')
    assert (state["fights"], state["warps"]) == (1, 2)


def test_battle_recovery_must_restore_field_at_same_edge():
    state = _drive('''
      local c={map=787,x=12,y=39,field=true,battle=false,callback2=0x080565B5,
               tasks='',fights=0,warps=0}
      local io={state=function() return c end,
        fight_through=function() c.fights=c.fights+1;c.battle=false;c.field=false;return true end,
        settle=function() return true end,
        enter_warp=function() c.warps=c.warps+1;c.battle=true;c.field=false
          return false,'map never changed from 787' end,
        log=function() end}
      local ok,why=Edge.cross(io)
      assert(ok==false and why:find('field did not settle',1,true))
      return c
    ''')
    assert (state["fights"], state["warps"]) == (1, 1)


def test_wrong_edge_or_live_battle_refuses_without_input():
    for x, battle in ((11, False), (12, True)):
        result = _drive(f'''
          local c={{map=787,x={x},y=39,field=false,battle={str(battle).lower()},
                   callback2=0,tasks='',warps=0}}
          local io={{state=function() return c end,
            enter_warp=function() c.warps=c.warps+1;return true end,
            log=function() end}}
          local ok,why=Edge.cross(io)
          assert(ok==false and type(why)=='string')
          return c
        ''')
        assert result["warps"] == 0


def test_field_still_open_after_failed_press_does_not_blindly_retry():
    state = _drive('''
      local c={map=787,x=12,y=39,field=true,battle=false,callback2=0x080556B5,
               tasks='',warps=0}
      local io={state=function() return c end,
        enter_warp=function() c.warps=c.warps+1;return false,'map never changed from 787' end,
        log=function() end}
      local ok,why=Edge.cross(io)
      assert(ok==false and why:find('map never changed from 787'))
      return c
    ''')
    assert state["warps"] == 1
