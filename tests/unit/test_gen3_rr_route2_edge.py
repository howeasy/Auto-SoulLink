"""Route 1 south connection recovery is bounded by live map, tile and field witnesses."""

from lupa import LuaRuntime


def _drive(body: str):
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua.execute("local Edge=dofile('lua/tests/gen3_rr_route2_edge.lua')\n" + body)


def test_off_field_menu_at_pinned_edge_is_closed_before_crossing():
    state = _drive('''
      local c={map=787,x=12,y=39,field=false,battle=false,callback2=0x08123456,
               tasks='summary',backs=0,warps=0,lines={}}
      local io={state=function() return c end,
        leave_menu=function() c.backs=c.backs+1;c.field=true;c.callback2=0x080556B5 end,
        enter_warp=function() c.warps=c.warps+1;c.map=768;return true end,
        log=function(s) c.lines[#c.lines+1]=s end}
      local ok,why=Edge.cross(io)
      assert(ok==true and why==nil)
      return c
    ''')
    assert (state["backs"], state["warps"], state["map"]) == (1, 1, 768)


def test_new_off_field_ui_after_first_press_gets_one_retry():
    state = _drive('''
      local c={map=787,x=12,y=39,field=true,battle=false,callback2=0x080556B5,
               tasks='',backs=0,warps=0}
      local io={state=function() return c end,
        leave_menu=function() c.backs=c.backs+1;c.field=true end,
        enter_warp=function() c.warps=c.warps+1
          if c.warps==1 then c.field=false;return false,'map never changed from 787' end
          c.map=768;return true end,
        log=function() end}
      local ok=Edge.cross(io)
      assert(ok==true)
      return c
    ''')
    assert (state["backs"], state["warps"], state["map"]) == (1, 2, 768)


def test_wrong_edge_or_live_battle_refuses_without_input():
    for x, battle in ((11, False), (12, True)):
        result = _drive(f'''
          local c={{map=787,x={x},y=39,field=false,battle={str(battle).lower()},
                   callback2=0,tasks='',backs=0,warps=0}}
          local io={{state=function() return c end,
            leave_menu=function() c.backs=c.backs+1 end,
            enter_warp=function() c.warps=c.warps+1;return true end,
            log=function() end}}
          local ok,why=Edge.cross(io)
          assert(ok==false and type(why)=='string')
          return c
        ''')
        assert (result["backs"], result["warps"]) == (0, 0)


def test_field_still_open_after_failed_press_does_not_blindly_retry():
    state = _drive('''
      local c={map=787,x=12,y=39,field=true,battle=false,callback2=0x080556B5,
               tasks='',backs=0,warps=0}
      local io={state=function() return c end,
        leave_menu=function() c.backs=c.backs+1 end,
        enter_warp=function() c.warps=c.warps+1;return false,'map never changed from 787' end,
        log=function() end}
      local ok,why=Edge.cross(io)
      assert(ok==false and why=='map never changed from 787')
      return c
    ''')
    assert (state["backs"], state["warps"]) == (0, 1)
