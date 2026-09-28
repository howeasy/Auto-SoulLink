"""Reset-phase control must exit cleanly without manufacturing trade completion or a SAVE."""

from pathlib import Path

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def _run(body: str):
    lua = LuaRuntime(unpack_returned_tuples=True)
    source = (ROOT / "lua/tests/duo/gen3_rr_reset_flow.lua").read_text(encoding="utf-8")
    lua.globals().F = lua.execute(source)
    return lua.execute(body)


def test_commit_marker_exits_before_trade_done_traded_or_runner_save():
    state = _run('''
      local c={logs={},sent_done=0,traded=0,saves=0,waits=0}
      c.log=function(s) c.logs[#c.logs+1]=s end
      c.sent=function(name) return name=='trade_done' and c.sent_done or 0 end
      c.last_sent=function() return nil end
      c.wait_until=function(pred)
        c.waits=c.waits+1
        return pred()
      end
      c.wait_go=function(marker) if marker=='SAVE' then c.saves=c.saves+1 end;return true end
      local function trade(ctx)
        ctx.wait_until(function() return ctx.sent('trade_done')>0 end,900,'trade_done')
        if ctx.sent('trade_done')==0 then return false,'no trade_done' end
        c.traded=c.traded+1
        ctx.wait_go('SAVE')
        return true
      end
      local ok,why=F.initial(c,{trade_driver=trade,interrupt=true,
        probe=function() return {bits=3,epoch=7,visit=11,old_key='11223344:55667788'} end})
      assert(ok==false and why=='EXPECTED_RESET_PARTIAL_COMMIT')
      return c
    ''')
    assert (state["traded"], state["sent_done"], state["saves"], state["waits"]) == (0, 0, 0, 1)


def test_missing_commit_marker_never_becomes_an_expected_interruption():
    state = _run('''
      local c={logs={},sent_done=0,saves=0}
      c.log=function(s) c.logs[#c.logs+1]=s end
      c.sent=function() return 0 end
      c.last_sent=function() return nil end
      c.wait_until=function(pred) pred();return false end
      c.wait_go=function(marker) if marker=='SAVE' then c.saves=c.saves+1 end;return true end
      local function trade(ctx)
        ctx.wait_until(function() return false end,900,'trade_done')
        return false,'no trade_done'
      end
      local ok,why=F.initial(c,{trade_driver=trade,interrupt=true,probe=function() return nil end})
      assert(ok==false and why:find('reset window not witnessed',1,true))
      return c
    ''')
    assert state["saves"] == 0


def test_native_success_exits_at_save_gate_without_manual_save():
    state = _run('''
      local c={logs={},sent_done=1,saves=0,traded=0}
      c.log=function(s) c.logs[#c.logs+1]=s end
      c.sent=function(name) return name=='trade_done' and c.sent_done or 0 end
      c.last_sent=function(name)
        if name=='trade_done' then return {token='t1',new_key='AABBCCDD:00112233'} end
      end
      c.wait_until=function(pred) return pred() end
      c.wait_go=function(marker) if marker=='SAVE' then c.saves=c.saves+1 end;return true end
      local function trade(ctx)
        ctx.wait_until(function() return ctx.sent('trade_done')>0 end,900,'trade_done')
        c.traded=c.traded+1
        ctx.wait_go('SAVE')
        return false,'runner never released SAVE'
      end
      local ok,why=F.initial(c,{trade_driver=trade,stop_before_manual_save=true,
        validate_success=function(report)
          return {token=report.token,new_key=report.new_key,counter_before=4,counter_after=6}
        end})
      assert(ok==false and why=='EXPECTED_NATIVE_SUCCESS_NO_MANUAL_SAVE')
      return c
    ''')
    assert (state["traded"], state["saves"]) == (1, 0)


def test_uncertain_trade_done_cannot_satisfy_success_control():
    state = _run('''
      local c={logs={},saves=0}
      c.log=function(s) c.logs[#c.logs+1]=s end
      c.sent=function() return 1 end
      c.last_sent=function(name)
        if name=='trade_done' then return {token='t1',uncertain=true,after_reset=true} end
      end
      c.wait_until=function(pred) return pred() end
      c.wait_go=function(marker) if marker=='SAVE' then c.saves=c.saves+1 end;return true end
      local function trade(ctx) ctx.wait_go('SAVE');return false,'runner never released SAVE' end
      local ok,why=F.initial(c,{trade_driver=trade,stop_before_manual_save=true})
      assert(ok==false and why:find('reset window not witnessed',1,true))
      return c
    ''')
    assert state["saves"] == 0


def test_reload_requires_saved_key_and_matching_after_reset_report():
    state = _run('''
      local c={D={expected_key='11223344:55667788'},player='a',logs={},saves=0}
      c.jlog=function(tag,value) c.logs[#c.logs+1]={tag=tag,value=value} end
      c.party=function() return {{key='11223344:55667788',slot=1}} end
      c.last_sent=function(name)
        if name=='trade_done' then return {token='t1',uncertain=true,after_reset=true} end
      end
      c.wait_until=function(pred) return pred() end
      c.save=function() c.saves=c.saves+1 end
      local ok=F.reload(c,{counter=function() return 5 end,
        require_after_reset=true,token='t1'})
      assert(ok==true)
      return c
    ''')
    assert state["saves"] == 0
    assert [state["logs"][i]["tag"] for i in range(1, len(state["logs"]) + 1)] == [
        "RESET_RELOADED", "RESET_AFTER_RESET"]


def test_reload_cannot_accept_wrong_key_or_uncertain_token():
    for own_key, token in (("00000000:00000000", "t1"), ("11223344:55667788", "wrong")):
        state = _run(f'''
          local c={{D={{expected_key='11223344:55667788'}},player='a',logs={{}},saves=0}}
          c.jlog=function(tag,value) c.logs[#c.logs+1]={{tag=tag,value=value}} end
          c.party=function() return {{{{key='{own_key}',slot=1}}}} end
          c.last_sent=function(name)
            if name=='trade_done' then return {{token='t1',uncertain=true,after_reset=true}} end
          end
          c.wait_until=function(pred) return pred() end
          c.save=function() c.saves=c.saves+1 end
          local ok=F.reload(c,{{counter=function() return 5 end,
            require_after_reset=true,token='{token}'}})
          assert(ok==false)
          return c
        ''')
        assert state["saves"] == 0
