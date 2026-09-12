"""Durable Gen 1 HUD notices on the real client journal, executor, router and overlay.

The server contract (server/gen1_hud_feedback.py) is exercised from the Lua side: the
receipt the client persists is verified by the server's own verify_receipt, and one case
runs the real durable runtime against the real Python runtime over a modeled transport.
"""

import json
import time

import pytest
from lupa.lua54 import LuaError

from server.gen1_hud_feedback import (RECEIPT_SCHEMA, STATE_RECEIPT_SCHEMA, build_notice,
                                      build_state, verify_receipt, verify_state_receipt)
from server.protocol import canonical_json, decode_frame, digest
from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import (
    runtime,  # noqa: F401
    runtime as lua_store,
)
from tests.unit.test_gen1_runtime_client import client as stub_client
from tests.unit.test_gen1_runtime_server import RuntimeCase

INTENT_SCHEMA = "rby-hud-notice-intent-v1"
STATUS_SCHEMA = "rby-hud-service-status-v1"
ID1, ID2, ID3, ID4 = "1" * 32, "2" * 32, "3" * 32, "4" * 32
GB_OVERLAY = ("{screen_w=160,screen_h=144,hud_x=2,hud_y=134,hud_right=158,prompt_y=36,prompt_h=10,"
              "gameover_y=50,font_size=8,char_width=5}")

# Real client_journal over the modeled disk (start), real hud.lua drawing into a recording gui,
# real gen1_hud_service and command_service_router beside a physical fixture service that
# fails loudly if a notice ever reaches it, all under the shared command_executor.
HARNESS = r"""
    package.path=root..'/data/games/gen1_rby/?.lua;'..package.path
    package.loaded.platform_identity={new_nonce=new_id}
    Runtime=require('gen1_runtime')
    frame=100;now=1000;draws={};boxes=0;box_log={};fail_draw=false;fail_receipt=false;touched={}
    emu={framecount=function()return frame end}
    gui={drawText=function(x,y,text,color)
            if fail_draw then fail_draw=false;error('display lost',0)end
            draws[#draws+1]={frame=frame,text=text,color=color,y=y}
        end,
        drawBox=function(x,y,right,bottom,outline,fill)
            boxes=boxes+1;box_log[#box_log+1]={x=x,y=y,right=right,bottom=bottom,outline=outline,fill=fill}end}
    local function trap(name)
        return setmetatable({},{__index=function(_,key)
            touched[#touched+1]=name..'.'..tostring(key);error(name..' touched: '..tostring(key),0)end})
    end
    memory=trap('memory');host=trap('host');holds=trap('holds')
    -- held recovery shape: admitted, lifecycle-held, no operation hold
    CONTROL={admitted=true,operation_held=false,held=true,authority='hold'}
    function load_overlay()
        package.loaded.hud=nil
        Overlay=require('hud');Overlay.init(GB_OVERLAY)
        return Overlay
    end
    function build()
        package.loaded.gen1_hud_service=nil;package.loaded.command_service_router=nil
        Service=require('gen1_hud_service')
        hud=Service.new({journal=journal,overlay=Overlay,player='b',frame=function()return frame end,
            wall=function()return now end,memory=memory,host=host,holds=holds})
        physical={handles=function(body)return body.cmd=='force_faint'end,
            ready=function()return false,'physical fixture never ready'end,adapter={},
            operations={request=function()return nil end,accept=function()return true end,
                authorize_apply=function()return false,'physical fixture'end,revoke=function()end,
                status=function()return {kind='physical'}end}}
        for _,name in ipairs({'prepare','classify','apply','receipt'})do
            physical.adapter[name]=function()error('physical service reached: '..name,0)end
        end
        router=require('command_service_router').new({hud,physical})
        -- the unwrap-then-route shape gen1_runtime.new installs on the shared executor
        local adapter={}
        for _,name in ipairs({'prepare','classify','receipt'})do
            adapter[name]=function(wrapped,...)return router.adapter[name](Runtime.unwrap(wrapped,'b'),...)end
        end
        adapter.apply=function(wrapped,intent,identity)
            local body=Runtime.unwrap(wrapped,'b')
            assert(router.operations.authorize_apply(body,intent,identity,CONTROL))
            return router.adapter.apply(body,intent,identity)
        end
        executor=require('command_executor').new(journal,adapter)
        local complete=journal.complete_command
        journal.complete_command=function(self,...)
            if fail_receipt then fail_receipt=false;return false,'receipt persistence lost'end
            return complete(self,...)
        end
    end
    -- process replacement or the in-process slink.lua reload: fresh modules, the journal on disk survives
    function restart()if Overlay then assert(Overlay.clear())end;load_overlay();build()end
    restart()
    function deliver(text) -- the server answers the oldest durable event, which may be an earlier command_ack
        local commands=assert(JSON.decode(text))
        assert(journal:append({event='fixture'}))
        assert(journal:accept_response(assert(journal:pending_events())[1].operation_id,commands))
    end
    function step(id)return executor:step(id)end
    function ready(text)return router.ready(assert(JSON.decode(text)),nil,CONTROL)end
    function authorize(text)return router.operations.authorize_apply(assert(JSON.decode(text)),nil,nil,CONTROL)end
    function route_prepare(text)
        return pcall(router.adapter.prepare,assert(JSON.decode(text)),{command_id=string.rep('1',32),command_sequence=1})
    end
    function state_json()
        local state=assert(store:read())
        return assert(JSON.encode(state))
    end
    function status_json()return assert(JSON.encode(hud.status()))end
    function router_status_json()return assert(JSON.encode(router.operations.status()))end
    function draws_json()return assert(JSON.encode(JSON.array(draws)))end
    function boxes_json()return assert(JSON.encode(JSON.array(box_log)))end
""".replace("GB_OVERLAY", GB_OVERLAY)


def notice(now=1000, **changes):
    values = {"kind": "link_pending", "surface": "hud", "text": ">> Got Pikachu", "r": 100, "g": 180, "b": 255,
              "frames": 300, "now": lambda: now}
    values.update(changes)
    return build_notice(**values)


def terminal_state():
    return build_state({"cmd": "game_over"})


def wrapped(body, sequence, command_id):
    return {"command_id": command_id, "command_sequence": sequence, "body": {"cmd": body["cmd"], "body": body}}


FAINT_BODY = {"cmd": "force_faint", "key": "1234:5678:99", "death_id": "d" * 32}


def faint(sequence, command_id):
    return wrapped(FAINT_BODY, sequence, command_id)


def harness(lua):
    start(lua)
    lua.execute(HARNESS)
    return lua.globals()


def entry(lua, command_id):
    return next(e for e in json.loads(lua.globals().state_json())["inbox"] if e["command_id"] == command_id)


def draws(lua):
    return json.loads(lua.globals().draws_json())


def command_for(body, sequence, command_id):
    return {"command_id": command_id, "command_sequence": sequence, "body": body}


def status_of(lua):
    return json.loads(lua.globals().status_json())


def test_notice_at_head_persists_intent_draws_once_and_settles_with_the_exact_server_receipt(runtime):  # noqa: F811
    g = harness(runtime)
    body = notice()
    g.deliver(json.dumps([wrapped(body, 1, ID1)]))
    assert g.ready(json.dumps(body)) is True and g.authorize(json.dumps(body)) is True
    assert status_of(runtime) == {"schema": STATUS_SCHEMA, "pending": 1, "retained": 0, "drawn": 0, "expired": 0}
    done, result = g.step(ID1)
    assert done is True and result["outcome"] == "ACK", dict(result.items())
    assert draws(runtime) == [{"frame": 100, "text": ">> Got Pikachu", "color": "#64B4FF", "y": 133}]
    record = entry(runtime, ID1)
    assert record["intent"] == {"schema": INTENT_SCHEMA, "command_id": ID1, "body_digest": digest(body),
                                "surface": "hud", "frames": 300}
    receipt = {"schema": RECEIPT_SCHEMA, "command_id": ID1, "command_sequence": 1, "body_digest": digest(body),
               "disposition": "drawn", "frame": 100}
    assert record["outcome"] == "ACK" and record["receipt"] == receipt
    assert verify_receipt(command_for(body, 1, ID1), receipt) == {"disposition": "drawn", "frame": 100}
    outbox = json.loads(g.state_json())["outbox"]
    assert outbox[-1]["payload"] == {"event": "command_ack", "command_id": ID1, "command_sequence": 1,
                                     "outcome": "ACK", "receipt": receipt}
    done, result = g.step(ID1)
    assert done is True and result["replayed"] is True and len(draws(runtime)) == 1
    assert status_of(runtime) == {"schema": STATUS_SCHEMA, "pending": 0, "retained": 1, "drawn": 1, "expired": 0}
    assert json.loads(g.router_status_json()) == [status_of(runtime), {"kind": "physical"}]
    # settled under the held recovery control shape, with no memory, hold or permit access at all
    assert list(g.touched.values()) == []
    assert runtime.eval("router.operations.request({},CONTROL)") is None
    assert runtime.eval("router.operations.accept(nil)") is True


MUTATIONS = {
    "unknown_field": lambda b: b.__setitem__("sound", "beep"),
    "missing_field": lambda b: b.pop("frames"),
    "schema": lambda b: b.__setitem__("schema", "slink-gen1-hud-notice-v2"),
    "kind": lambda b: b.__setitem__("kind", "trade"),
    "surface": lambda b: b.__setitem__("surface", "sound"),
    "empty_text": lambda b: b.__setitem__("text", ""),
    "long_text": lambda b: b.__setitem__("text", "x" * 31),
    "non_ascii_text": lambda b: b.__setitem__("text", "Pokémon"),
    "control_text": lambda b: b.__setitem__("text", "Poke\nmon"),
    "r_high": lambda b: b.__setitem__("r", 256),
    "g_negative": lambda b: b.__setitem__("g", -1),
    "b_fraction": lambda b: b.__setitem__("b", 1.5),
    "frames_zero": lambda b: b.__setitem__("frames", 0),
    "frames_high": lambda b: b.__setitem__("frames", 601),
    "expiry_before_issue": lambda b: b.__setitem__("expires_at", 999),
    "expiry_too_far": lambda b: b.__setitem__("expires_at", 1121),
    "null_issue": lambda b: b.__setitem__("issued_at", None),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_malformed_notice_is_refused_before_intent_or_draw(runtime, name):  # noqa: F811
    g = harness(runtime)
    body = notice()
    MUTATIONS[name](body)
    g.deliver(json.dumps([wrapped(body, 1, ID1)]))
    done, result = g.step(ID1)
    assert done is False and result["outcome"] == "NACK" and result["phase"] == "prepare", dict(result.items())
    record = entry(runtime, ID1)
    assert draws(runtime) == [] and "intent" not in record and "outcome" not in record


def test_notice_waits_behind_the_physical_head_and_a_later_physical_command_becomes_head(runtime):  # noqa: F811
    g = harness(runtime)
    first = notice()
    second = notice(kind="link_formed", surface="prompt", text="Linked!")
    g.deliver(json.dumps([faint(1, ID1), wrapped(first, 2, ID2)]))
    assert g.ready(json.dumps(first))[0] is False
    done, result = g.step(ID2)
    assert done is False and result["phase"] == "prepare" and "command head" in result["reason"]
    assert draws(runtime) == []
    ok, why = g.route_prepare(json.dumps(FAINT_BODY))
    assert ok is False and "physical service reached: prepare" in why  # never the HUD service
    g.complete(ID1, "ACK", json.dumps({"schema": "fixture-physical-receipt-v1"}))
    assert g.ready(json.dumps(first)) is True
    done, result = g.step(ID2)
    assert done is True and result["outcome"] == "ACK" and len(draws(runtime)) == 1
    g.deliver(json.dumps([wrapped(second, 3, ID3), faint(4, ID4)]))
    done, result = g.step(ID3)
    assert done is True and result["outcome"] == "ACK"
    assert [(d["text"], d["y"]) for d in draws(runtime)] == [(">> Got Pikachu", 133), ("Linked!", 37)]
    pending = [e["command_id"] for e in json.loads(g.state_json())["inbox"] if "outcome" not in e]
    assert pending == [ID4]
    assert g.ready(json.dumps(second))[0] is False
    ok, why = g.route_prepare(json.dumps(FAINT_BODY))
    assert ok is False and "physical service reached: prepare" in why
    assert status_of(runtime)["pending"] == 0 and status_of(runtime)["retained"] == 2


def test_router_refuses_a_second_service_claiming_notices(runtime):  # noqa: F811
    g = harness(runtime)
    runtime.globals().body_json = json.dumps(notice())
    g.deliver(json.dumps([wrapped(notice(), 1, ID1)]))
    runtime.execute("claimer={handles=hud.handles,ready=hud.ready,adapter=hud.adapter,operations=hud.operations}"
                    ";twice=require('command_service_router').new({hud,physical,claimer})")
    with pytest.raises(LuaError, match="multiple services claim"):
        runtime.execute("twice.ready(JSON.decode(body_json),nil,CONTROL)")
    with pytest.raises(LuaError, match="multiple services claim"):
        runtime.execute("twice.adapter.prepare(JSON.decode(body_json),{})")


@pytest.mark.parametrize(("now", "disposition", "frame", "count"), [(1030, "drawn", 100, 1), (1031, "expired", -1, 0)])
def test_the_client_wall_clock_decides_expiry_at_the_ttl_boundary(runtime, now, disposition, frame, count):  # noqa: F811
    g = harness(runtime)
    body = notice()  # issued 1000, expires 1030
    g.deliver(json.dumps([wrapped(body, 1, ID1)]))
    runtime.execute(f"now={now}")
    done, result = g.step(ID1)
    assert done is True and result["outcome"] == "ACK"
    receipt = entry(runtime, ID1)["receipt"]
    assert (receipt["disposition"], receipt["frame"]) == (disposition, frame) and len(draws(runtime)) == count
    assert verify_receipt(command_for(body, 1, ID1), receipt) == {"disposition": disposition, "frame": frame}
    status = status_of(runtime)
    assert (status["drawn"], status["expired"], status["retained"]) == (count, 1 - count, count)


def test_display_failure_after_the_intent_retries_and_draws_exactly_once_after_restart(runtime):  # noqa: F811
    g = harness(runtime)
    body = notice()
    g.deliver(json.dumps([wrapped(body, 1, ID1)]))
    runtime.execute("fail_draw=true")
    done, result = g.step(ID1)
    assert done is False and result["outcome"] == "NACK" and result["phase"] == "apply" and "display lost" in result["reason"]
    record = entry(runtime, ID1)
    assert record["intent"]["schema"] == INTENT_SCHEMA and "outcome" not in record and draws(runtime) == []
    assert runtime.eval("Overlay.retained().hud") == 0  # a failed draw retains nothing
    g.restart()
    runtime.execute("frame=101")
    done, result = g.step(ID1)
    assert done is True and result["outcome"] == "ACK"
    assert draws(runtime) == [{"frame": 101, "text": ">> Got Pikachu", "color": "#64B4FF", "y": 133}]
    assert entry(runtime, ID1)["receipt"]["frame"] == 101


def test_receipt_persistence_failure_after_the_draw_settles_later_without_a_redraw(runtime):  # noqa: F811
    g = harness(runtime)
    body = notice()
    g.deliver(json.dumps([wrapped(body, 1, ID1)]))
    runtime.execute("fail_receipt=true")
    done, result = g.step(ID1)
    assert done is False and result["outcome"] == "NACK" and result["phase"] == "persist_receipt"
    assert len(draws(runtime)) == 1 and "outcome" not in entry(runtime, ID1)
    runtime.execute("frame=101")
    done, result = g.step(ID1)
    assert done is True and result["outcome"] == "ACK" and len(draws(runtime)) == 1
    assert entry(runtime, ID1)["receipt"]["frame"] == 100  # the actual draw frame, remembered in this VM


@pytest.mark.parametrize(("later", "count", "disposition", "frame"), [(1010, 2, "drawn", 101), (1031, 1, "expired", -1)])
def test_a_lost_vm_after_the_draw_redraws_at_most_once_within_the_ttl(runtime, later, count, disposition, frame):  # noqa: F811
    g = harness(runtime)
    body = notice()
    g.deliver(json.dumps([wrapped(body, 1, ID1)]))
    runtime.execute("fail_receipt=true")
    done, result = g.step(ID1)
    assert done is False and len(draws(runtime)) == 1
    runtime.execute(f"now={later};frame=101")
    g.restart()
    done, result = g.step(ID1)
    assert done is True and result["outcome"] == "ACK"
    receipt = entry(runtime, ID1)["receipt"]
    assert len(draws(runtime)) == count and (receipt["disposition"], receipt["frame"]) == (disposition, frame)
    assert verify_receipt(command_for(body, 1, ID1), receipt) == {"disposition": disposition, "frame": frame}
    done, result = g.step(ID1)
    assert result["replayed"] is True and len(draws(runtime)) == count


def test_same_vm_reload_replays_the_persisted_receipt_and_draws_new_notices_on_the_fresh_overlay(runtime):  # noqa: F811
    g = harness(runtime)
    body = notice()
    g.deliver(json.dumps([wrapped(body, 1, ID1)]))
    done, result = g.step(ID1)
    assert done is True and result["outcome"] == "ACK"
    receipt = entry(runtime, ID1)["receipt"]
    # slink.lua evicts every checked module on reload; the journal on disk survives
    g.restart()
    done, result = g.step(ID1)
    assert done is True and result["replayed"] is True and len(draws(runtime)) == 1
    assert entry(runtime, ID1)["receipt"] == receipt
    outbox = json.loads(g.state_json())["outbox"]
    assert outbox[-1]["payload"]["event"] == "command_ack"  # still awaiting the server acknowledgement
    assert runtime.eval("Overlay.retained().hud") == 0  # the old overlay instance's retention is gone
    g.accept(outbox[-1]["operation_id"], "[]")
    assert json.loads(g.state_json())["inbox"] == [] and status_of(runtime)["pending"] == 0
    g.deliver(json.dumps([wrapped(notice(text="Second"), 2, ID2)]))
    done, result = g.step(ID2)
    assert done is True and result["outcome"] == "ACK"
    assert [d["text"] for d in draws(runtime)] == [">> Got Pikachu", "Second"]
    assert runtime.eval("Overlay.retained().hud") == 1


def test_overlay_preserves_fifo_and_every_notice_frame_budget(runtime):  # noqa: F811
    harness(runtime)
    runtime.execute(r"""
        assert(Overlay.present({surface='hud',text='A',frames=2,r=1,g=2,b=3})==true)
        assert(Overlay.present({surface='hud',text='B',frames=1,r=1,g=2,b=3})==true)
        assert(Overlay.retained().hud==1) -- B consumed its one-frame budget in present()
        Overlay.render()
        assert(Overlay.retained().hud==0)
        local erase=boxes;Overlay.render();assert(boxes==erase+1) -- one transparent erase box, no text
        assert(Overlay.present({surface='prompt',text='\226\152\133 Linked \195\169',frames=1,r=1,g=2,b=3})==true)
        for i=1,20 do assert(Overlay.present({surface='prompt',text='P'..i,frames=5}))end
        assert(Overlay.retained().prompt==20)
        local before_clear=boxes
        assert(Overlay.clear()==true)
        assert(boxes==before_clear+1) -- the visible prompt surface was actually erased
        assert(Overlay.retained().hud==0 and Overlay.retained().prompt==0)
    """)
    # frames is the total displayed-frame budget, including present()'s immediate draw.
    assert [d["text"] for d in draws(runtime)] == ["A", "B", "A", "* Linked e"] + [f"P{i}" for i in range(1, 21)]
    assert draws(runtime)[3]["color"] == "#010203" and draws(runtime)[4]["color"] == "#FFFFFF"


def test_terminal_game_over_survives_ack_retirement_and_vm_reload_without_new_commands(runtime):  # noqa: F811
    g = harness(runtime)
    body = terminal_state()
    g.deliver(json.dumps([wrapped(body, 1, ID1)]))
    done, result = g.step(ID1)
    assert done is True and result["outcome"] == "ACK"
    receipt = entry(runtime, ID1)["receipt"]
    assert receipt == {"schema": STATE_RECEIPT_SCHEMA, "command_id": ID1, "command_sequence": 1,
                       "body_digest": digest(body), "disposition": "applied", "frame": 100}
    assert verify_state_receipt(command_for(body, 1, ID1), receipt) == {"disposition": "applied", "frame": 100}
    state = json.loads(g.state_json())
    assert state["version"] == "slink-client-journal-v3"
    assert state["hud_state"] == {"schema": "slink-gen1-hud-client-state-v1", "mode": "game_over", "text": "",
                                  "command_id": ID1, "command_sequence": 1, "body_digest": digest(body), "frame": 100}
    assert draws(runtime)[-1]["text"] == "GAME OVER!" and runtime.eval("Overlay.is_game_over()") is True
    ack = state["outbox"][-1]
    g.accept(ack["operation_id"], "[]")
    assert json.loads(g.state_json())["inbox"] == []
    assert json.loads(g.state_json())["hud_state"] == state["hud_state"]
    count = len(draws(runtime))
    g.restart()  # the previous overlay erases, then the new instance restores visibly
    assert len(draws(runtime)) == count + 1 and draws(runtime)[-1]["text"] == "GAME OVER!"
    assert json.loads(g.boxes_json())[-2]["fill"] == 0  # actual transparent erase before restore
    assert runtime.eval("Overlay.is_game_over()") is True
    assert json.loads(g.state_json())["outbox"] == []
    assert status_of(runtime)["pending"] == 0
    g.deliver(json.dumps([wrapped(body, 2, ID2)]))  # duplicate semantic state after reconnect
    before_duplicate = len(draws(runtime))
    assert g.step(ID2)[0] is True
    assert len(draws(runtime)) == before_duplicate
    assert entry(runtime, ID2)["receipt"]["frame"] == 100
    assert json.loads(g.state_json())["hud_state"] == state["hud_state"]
    runtime.execute("assert(Overlay.clear())")  # explicit close/new-run erases persistent GUI pixels
    assert runtime.eval("Overlay.is_game_over()") is False
    assert json.loads(g.boxes_json())[-1]["fill"] == 0


def test_terminal_state_replay_after_local_receipt_loss_restores_without_an_effect_flood(runtime):  # noqa: F811
    g = harness(runtime)
    body = terminal_state()
    g.deliver(json.dumps([wrapped(body, 1, ID1)]))
    runtime.execute("fail_receipt=true")
    done, result = g.step(ID1)
    assert done is False and result["phase"] == "persist_receipt"
    assert json.loads(g.state_json())["hud_state"]["command_id"] == ID1
    assert "outcome" not in entry(runtime, ID1)
    old_draws = len(draws(runtime))
    runtime.execute("frame=101")
    g.restart()  # one visible restoration from durable state, not a new apply
    assert len(draws(runtime)) == old_draws + 1
    done, result = g.step(ID1)
    assert done is True and result["outcome"] == "ACK"
    assert len(draws(runtime)) == old_draws + 1
    assert entry(runtime, ID1)["receipt"]["frame"] == 100
    done, result = g.step(ID1)
    assert done is True and result["replayed"] is True and len(draws(runtime)) == old_draws + 1


@pytest.mark.parametrize("fault", ["mode", "extra", "digest", "version"])
def test_unknown_or_tampered_persisted_terminal_state_fails_closed(runtime, fault):  # noqa: F811
    g = harness(runtime)
    g.deliver(json.dumps([wrapped(terminal_state(), 1, ID1)]))
    assert g.step(ID1)[0] is True
    runtime.globals().fault = fault
    runtime.execute("state=assert(store:read());"
                    "if fault=='mode' then state.hud_state.mode='rebuilding' "
                    "elseif fault=='extra' then state.hud_state.extra=true "
                    "elseif fault=='digest' then state.hud_state.body_digest='x' "
                    "else state.version='slink-client-journal-v2' end;assert(store:commit(state))")
    with pytest.raises(LuaError, match="client HUD state|journal"):
        g.restart()


def test_terminal_state_waits_behind_physical_fifo_and_refuses_sound(runtime):  # noqa: F811
    g = harness(runtime)
    body = terminal_state()
    g.deliver(json.dumps([faint(1, ID1), wrapped(body, 2, ID2)]))
    assert g.ready(json.dumps(body))[0] is False
    assert g.step(ID2)[0] is False and draws(runtime) == []
    g.complete(ID1, "ACK", json.dumps({"schema": "fixture-physical-receipt-v1"}))
    assert g.ready(json.dumps(body)) is True
    assert g.step(ID2)[0] is True and draws(runtime)[-1]["text"] == "GAME OVER!"
    assert list(g.touched.values()) == []
    bad = {**body, "sound": 26}
    g.deliver(json.dumps([wrapped(bad, 3, ID3)]))
    assert g.step(ID3)[0] is False


# The real held faint service beside the HUD service: the head decides which service owns
# the command, and only the physical head can make the free loop's writer pending.
FAINT_FIXTURE = r"""
    package.path=root..'/data/games/gen1_rby/?.lua;'..package.path
    package.loaded.platform_identity={new_nonce=new_id}
    now=1;frame=100;physical_writes=0;held=true;draws={}
    emu={framecount=function()return frame end};gameinfo={getromhash=function()return string.rep('e',40)end}
    gui={drawText=function(_,_,text)draws[#draws+1]=text end,drawBox=function()end}
    context={context_generation=string.rep('c',32),save_identity={ot_id='0000',trainer_name='SAME'}}
    current={hp=10}
    package.loaded.gen1_force_faint_executor={new=function()return {
        prepare=function()return {schema='fixture-intent'}end,
        classify=function()return current.hp==0 and 'after' or 'before',current end,
        apply=function()physical_writes=physical_writes+1;current={hp=0}end,
        receipt=function()return {schema='fixture-receipt',hp=current.hp}end}end}
    package.loaded.gen1_command_receipts={party_snapshot=function()return current end}
    package.loaded.gen1_write_checkpoint={capture=function()return {fixture=true}end}
    mem={profile={},isPartyWriteSafe=function()return true end}
    faint=require('gen1_held_faint').new({journal=journal,memory=mem,player='b',variant='yellow',
        clock=function()return now end,owned=function()return context end,
        host={status=function()return {owner_id=string.rep('b',32),capability_id='fixture',process_id=1,
            physical_stop_verified=held}end}})
    Overlay=require('hud');Overlay.init(GB_OVERLAY)
    hud=require('gen1_hud_service').new({journal=journal,overlay=Overlay,player='b',
        frame=function()return frame end,wall=function()return 1000 end})
    router=require('command_service_router').new({hud,faint})
    function writer_pending()return faint.pending()end -- gen1_client_entry: the held faint service alone
    local adapter={}
    for _,name in ipairs({'prepare','classify','receipt'})do
        adapter[name]=function(wrapped,...)return router.adapter[name](require('gen1_runtime').unwrap(wrapped,'b'),...)end
    end
    adapter.apply=function(wrapped,intent,identity)
        local body=require('gen1_runtime').unwrap(wrapped,'b')
        assert(router.operations.authorize_apply(body,intent,identity,{admitted=true,operation_held=true}))
        return router.adapter.apply(body,intent,identity)
    end
    executor=require('command_executor').new(journal,adapter)
    function deliver(text)
        local commands=assert(JSON.decode(text))
        assert(journal:append({event='fixture'}))
        assert(journal:accept_response(assert(journal:pending_events())[1].operation_id,commands))
    end
    function step(id)return executor:step(id)end
    function ready(text,held_now)
        return router.ready(assert(JSON.decode(text)),nil,{admitted=true,operation_held=held_now,held=not held_now})
    end
    function request_json()
        return JSON.encode(router.operations.request({binding_digest=string.rep('f',64)},{admitted=true,operation_held=true}))
    end
""".replace("GB_OVERLAY", GB_OVERLAY)


def test_a_notice_head_never_makes_the_real_held_faint_writer_pending(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    lua.execute(FAINT_FIXTURE)
    g = lua.globals()
    body = notice()
    g.deliver(json.dumps([wrapped(body, 1, ID1), faint(2, ID2)]))
    assert g.writer_pending() is False  # party is write-safe, but the head is a no-write notice
    assert g.ready(json.dumps(body), False) is True
    assert g.ready(json.dumps(FAINT_BODY), True)[0] is False
    done, result = g.step(ID1)
    assert done is True and result["outcome"] == "ACK" and g.physical_writes == 0
    assert list(g.draws.values()) == [">> Got Pikachu"]
    assert g.writer_pending() is True  # the physical command is the head now
    assert g.ready(json.dumps(FAINT_BODY), True) is True
    done, result = g.step(ID2)  # prepares the faint intent, then arms waiting for the write permit
    assert done is False and result["pending"] is True and g.physical_writes == 0
    requested = json.loads(g.request_json())
    assert requested["evidence"]["schema"] == "rby-held-faint-evidence-v1" and requested["window"]["scope"]["phase"] == "force_faint"
    assert g.ready(json.dumps(body), False)[0] is False


LAUNCH = {"schema": "slink-gen1-launch-v1", "protocol": "slink-gen1-durable-v1", "mode": "free_service",
          "run_id": "a" * 32, "player": "a", "host": "localhost", "port": 9000, "initial_observations": True,
          "cartridge": {"variant": "yellow", "final_rom_sha1": "e" * 40}}

# gen1_client_entry with its collaborators modeled as in test_gen1_runtime_client, except the
# store, journal, router, HUD service and overlay, which are the real modules.
ENTRY_HARNESS = r"""
    package.path=root..'/lua/?.lua;'..package.path
    physical=false;nonce=0;frame=100;draws={};boxes=0;pending_faint=false;prior_clears=0
    gameinfo={getromhash=function()return string.rep('e',40)end}
    emu={framecount=function()return frame end,yield=function()end,frameadvance=function()error('startup advanced a frame')end}
    gui={drawText=function(_,_,text)draws[#draws+1]={frame=frame,text=text}end,drawBox=function()boxes=boxes+1 end}
    event={onloadstate=function()return 'load-hook'end,unregisterbyid=function()end}
    console={log=function()end}
    package.loaded['memory_gb']={initProfile=function()end,isPartyWriteSafe=function()return true end,
        readPlayerId=function()return 0 end,readPlayerName=function()return 'SAME'end,read_u8=function()return 1 end}
    package.loaded['games.gen1_rby']={}
    package.loaded['gen1_runtime_profiles']={metadata=function(_,cartridge)return cartridge end}
    package.loaded['platform_identity']={new_nonce=function()nonce=nonce+1;return string.format('%032x',nonce)end}
    local host={set_held=function(value)physical=value;return true end,
        status=function()return {held=physical,physical_stop_verified=physical}end,
        yield_held=function()assert(physical);return true end}
    package.loaded['platform_execution']={supported_profile=function()return {}end,new=function()return host end}
    package.loaded['platform_clock']={new=function()return function()return 0 end end}
    luanet={load_assembly=function()end,import_type=function(name)
        if name=='System.IO.Path'then return {GetFullPath=function(value)return value end,GetDirectoryName=function()return 'tmp'end}end
        error('unexpected type '..name)
    end}
    package.loaded['platform_storage']={new=function()return backend end} -- the store fixture's modeled disk
    package.loaded['connector']={}
    package.loaded['gen1_bootstrap_observer']={new=function()return {close=function()end,status=function()return{}end}end}
    package.loaded['gen1_initial_observation']={new=function()return {signals={status=function()return{}end},
        step=function()end,close=function()end}end}
    package.loaded['gen1_held_faint']={new=function()return {handles=function(body)return body.cmd=='force_faint'end,
        ready=function()return false,'faint fixture is not ready'end,pending=function()return pending_faint end,
        operations={request=function()return nil end,accept=function()return true end,
            authorize_apply=function()return false,'faint fixture'end,revoke=function()end,status=function()return {kind='faint'}end},
        adapter={prepare=function()error('faint fixture reached',0)end,classify=function()error('faint fixture reached',0)end,
            apply=function()error('faint fixture reached',0)end,receipt=function()error('faint fixture reached',0)end}}end}
    package.loaded['gen1_acquisition_observers']={new=function()return {close=function()end}end}
    package.loaded['battle_force_authority']={service=function()return {revoke=function()return true end,
        close=function()return true end,status=function()return{}end}end}
    local Real=require('gen1_runtime')
    package.loaded['gen1_runtime']={unwrap=Real.unwrap,new=function(options)
        runtime_options=options
        return {step=function()return true end,has_service_lease=function()return false end,is_bound=function()return true end,
            observe=function()return {1}end,status=function()return {}end,revoke=function()end}
    end}
    SLINK_RUNTIME_OVERLAY_CLEAR=function()prior_clears=prior_clears+1;return true end
    service=assert(require('gen1_client_entry').start(assert(JSON.decode(launch_json)),{root=root,storage_root='tmp'}))
    assert(prior_clears==1 and type(SLINK_RUNTIME_OVERLAY_CLEAR)=='function')
    assert(service:step()) -- verified overworld: store and journal open, router composed under the startup hold
    CONTROL={admitted=true,operation_held=false,held=true,authority='hold'}
    journal=assert(require('client_journal').open(service.store,function()nonce=nonce+1;return string.format('%032x',nonce)end))
    local event=assert(journal:append({event='fixture'}))
    assert(journal:accept_response(event,JSON.array({assert(JSON.decode(notice_json))})))
    body=assert(JSON.decode(body_json));faint_body=assert(JSON.decode(faint_json))
    assert(runtime_options.operation_ready(body,nil,CONTROL)==true)
    local ok,why=runtime_options.operation_ready(faint_body,nil,CONTROL)
    assert(ok==false and why=='faint fixture is not ready')
    assert(runtime_options.operation_execution.authorize_apply(body,nil,{command_id=string.rep('1',32),command_sequence=1},CONTROL)==true)
    assert(runtime_options.operation_execution.authorize_apply(faint_body,nil,{},CONTROL)==false)
    assert(runtime_options.operation_execution.request({},CONTROL)==nil and runtime_options.operation_execution.accept(nil)==true)
    local adapter={}
    for _,name in ipairs({'prepare','classify','receipt'})do
        adapter[name]=function(wrapped,...)return runtime_options.executor_adapter[name](Real.unwrap(wrapped,'a'),...)end
    end
    adapter.apply=function(wrapped,intent,identity)
        local unwrapped=Real.unwrap(wrapped,'a')
        assert(runtime_options.operation_execution.authorize_apply(unwrapped,intent,identity,CONTROL))
        return runtime_options.executor_adapter.apply(unwrapped,intent,identity)
    end
    executor=require('command_executor').new(journal,adapter)
    function step(id)return executor:step(id)end
    function status_json()return assert(JSON.encode(service:status()))end
    function draws_json()return assert(JSON.encode(JSON.array(draws)))end
"""


def test_client_entry_composes_the_router_over_hud_and_held_faint_and_renders_once_per_frame(runtime):  # noqa: F811
    lua = runtime
    body = notice(now=int(time.time()))  # the entry's HUD service reads os.time
    body["expires_at"] = body["issued_at"] + 120
    lua.globals().launch_json = json.dumps(LAUNCH)
    lua.globals().notice_json = json.dumps(wrapped(body, 1, ID1))
    lua.globals().body_json = json.dumps(body)
    lua.globals().faint_json = json.dumps(FAINT_BODY)
    lua.execute(ENTRY_HARNESS)
    g = lua.globals()
    assert g.physical is True  # the startup hold is on: the notice settles while held
    done, result = g.step(ID1)
    assert done is True and result["outcome"] == "ACK", dict(result.items())
    assert json.loads(g.draws_json()) == [{"frame": 100, "text": ">> Got Pikachu"}]
    status = json.loads(g.status_json())
    assert status["hud"] == {"schema": STATUS_SCHEMA, "pending": 0, "retained": 1, "drawn": 1, "expired": 0}
    assert status["phase"] == "held_service" and status["hold_mux"]["held"] is True
    lua.execute("frame=101;assert(service:step())")  # one overlay render per new emulated frame
    assert [d["frame"] for d in json.loads(g.draws_json())] == [100, 101]
    lua.execute("assert(service:step())")  # same frame while held: no render
    assert len(json.loads(g.draws_json())) == 2
    lua.execute("local before=boxes;service:close();assert(boxes==before+1 and SLINK_RUNTIME_OVERLAY_CLEAR==nil)")


# The real durable runtime and gen1_runtime binding over the real Python runtime: the server
# commits a notice, the client draws it while held and the server verifies the receipt.
E2E_HARNESS = r"""
    package.path=root..'/data/games/gen1_rby/?.lua;'..package.path
    local data=assert(JSON.decode(client_input))
    Journal=require('client_journal');Runtime=require('gen1_runtime')
    gameinfo={getromhash=function()return data.cartridge.final_rom_sha1 end}
    frame=100;now=1000;draws={};held=true;nonce=0;t=0;connected=false;incoming={};outgoing={}
    emu={framecount=function()return frame end}
    gui={drawText=function(_,_,text)draws[#draws+1]={frame=frame,text=text}end,drawBox=function()end}
    context=data.context
    initial=Journal.initial();store=assert(open_store())
    ids=0
    journal=assert(Journal.open(store,function()ids=ids+1;return data.id_prefix..string.format('%030x',ids)end))
    transport={
        init=function(host,port,options)assert(options.discard_on_disconnect);connected=true;incoming={};outgoing={}end,
        connected=function()return connected end,
        pump=function()end,
        send=function(line)outgoing[#outgoing+1]=line;return true end,
        receive=function()return table.remove(incoming,1)end,
        disconnect=function()connected=false;incoming={};outgoing={}end,
        queue_status=function()return {send_lines=0,send_bytes=0,send_offset=0,receive_lines=0,receive_bytes=0,
            partial_receive_bytes=0,pending_receive_bytes=0,ready_receive_bytes=0}end,
    }
    Overlay=require('hud');Overlay.init(GB_OVERLAY)
    hud=require('gen1_hud_service').new({journal=journal,overlay=Overlay,player=data.player,
        frame=function()return frame end,wall=function()return now end})
    physical={handles=function(body)return body.cmd=='force_faint'end,
        ready=function()return false,'physical operations are outside this case'end,adapter={},
        operations={request=function()return nil end,accept=function()return true end,
            authorize_apply=function()return false,'physical fixture'end,revoke=function()end,
            status=function()return {kind='physical'}end}}
    for _,name in ipairs({'prepare','classify','apply','receipt'})do
        physical.adapter[name]=function()error('unexpected physical '..name,0)end
    end
    router=require('command_service_router').new({hud,physical})
    options={player=data.player,variant=data.variant,run_id=data.run_id,server_host='127.0.0.1',server_port=9000,
        journal=journal,transport=transport,clock=function()return t end,
        host={set_held=function(value)held=value;return true end},
        read_context=function()return context end,
        operation_ready=router.ready,operation_execution=router.operations,executor_adapter=router.adapter,
        new_nonce=function()nonce=nonce+1;return data.nonce_prefix..string.format('%030x',nonce)end,
    }
    runtime=assert(Runtime.new(options))
    function step()return runtime:step()end
    function pop()return table.remove(outgoing,1)end
    function push(raw)incoming[#incoming+1]=raw end
    function state_json()local state=assert(store:read());return assert(JSON.encode(state))end
    function status_json()return assert(JSON.encode(runtime:status()))end
    function draws_json()return assert(JSON.encode(JSON.array(draws)))end
""".replace("GB_OVERLAY", GB_OVERLAY)


def hud_client(case, player):
    lua = lua_store.__wrapped__()
    report = case.hello(player)
    lua.globals().client_input = json.dumps({
        "player": player,
        "run_id": case.runtime.journal.run_id,
        "variant": case.variants[player],
        "cartridge": case.contract["players"][player],
        "context": {"context_generation": report["context_generation"], **report["gen1_metadata"]},
        "id_prefix": "bb",
        "nonce_prefix": "dd",
    })
    lua.execute(E2E_HARNESS)
    return lua


@pytest.mark.parametrize("terminal", [False, True])
def test_real_durable_runtime_settles_server_hud_while_held_and_verifies_the_receipt(tmp_path, terminal):
    case = RuntimeCase(tmp_path)
    clients = {"a": stub_client(case, "a"), "b": hud_client(case, "b")}
    owners = {p: object() for p in clients}
    tick = 0

    def exchange(count):
        nonlocal tick
        for _ in range(count):
            tick += 1
            case.time = 10 + tick * 0.05
            for p, lua in clients.items():
                g = lua.globals()
                g.t = tick * 0.05
                assert g.step() is True, json.loads(g.status_json())
                while (line := g.pop()) is not None:
                    response = case.runtime.process(decode_frame(line.encode()), owners[p])
                    g.push(canonical_json(response))
                assert g.held is True

    try:
        exchange(8)
        assert all(json.loads(c.globals().status_json())["session_state"] == "admitted" for c in clients.values())
        body = terminal_state() if terminal else notice(now=1000)  # client b's modeled clock reads 1000
        snapshot = case.runtime.journal.snapshot()
        case.runtime.journal.commit("b", "e" * 32, {"event": "fixture"}, expected_revision=snapshot.revision,
                                    state=snapshot.state, commands={"a": [], "b": [body]}, result={"ack": "ACK"})
        command_id = case.runtime.journal.pending("b")[0]["command_id"]
        exchange(40)
        record = case.runtime.journal.command("b", command_id)
        assert record["outcome"] == "ACK"
        assert record["receipt"] == {"schema": STATE_RECEIPT_SCHEMA if terminal else RECEIPT_SCHEMA, "command_id": command_id,
                                     "command_sequence": record["command_sequence"], "body_digest": digest(body),
                                     "disposition": "applied" if terminal else "drawn", "frame": 100}
        assert case.runtime.journal.pending("b") == []
        g = clients["b"].globals()
        assert json.loads(g.draws_json()) == [{"frame": 100, "text": "GAME OVER!" if terminal else ">> Got Pikachu"}]
        client_state = json.loads(g.state_json())
        assert not any(row["command_id"] == command_id for row in client_state["inbox"])
        assert client_state["command_floor"] >= record["command_sequence"]
        assert (client_state.get("hud_state", {}).get("mode") == "game_over") is terminal
        status = json.loads(g.status_json())
        assert status["operation_execution"][0] == {"schema": STATUS_SCHEMA, "pending": 0, "retained": 0 if terminal else 1,
                                                    "drawn": 1, "expired": 0}
        # The paired runtime has granted a service lease, but this harness deliberately
        # does not select service execution.  The no-write HUD receipt must still settle
        # while the physical host remains held.
        assert status["control"]["held"] is True and status["control"]["authority"] == "service"
        assert status["control"]["service_execution"] is False
    finally:
        case.close()
