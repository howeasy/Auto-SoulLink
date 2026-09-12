local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
package.path=ROOT.."/lua/?.lua;"..package.path
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_execution_window_gate")
local JSON=require("json_codec")
local input=assert(io.open(assert(os.getenv("SLINK_EXECUTION_WINDOW_INPUT")),"r"))
local config=assert(JSON.decode(input:read("*a")));input:close()
local result={schema="slink-operation-window-live-test-v1",variant=t.variant,passed=false}
local owner
local ok,why=xpcall(function()
    local nonce=require("platform_identity").new_nonce
    local clock=assert(require("platform_clock").new());local offset=0
    local scope={operation_id=assert(nonce()),operation_digest=string.rep("a",64),
        context_generation=assert(nonce()),binding_digest=string.rep("b",64),phase="native_commit"}
    local Window=require("execution_window")
    local window=Window.new({clock=function()return clock()+offset end,current_scope=function()return scope end,
        verify_grant=function(packet)return packet.proof_digest==string.rep("c",64)end}) -- explicit issuer fixture
    owner=require("platform_bounded_execution").new({profile="gambatte",owner_id=assert(nonce()),
        expected_host=require("platform_execution").supported_profile("gambatte"),
        authorize=function(value)return value==scope and window:consume(scope)end})
    local rate=owner.status().frame_rate
    if config.pace then client.speedmode(100)end
    local pacer=config.pace and require("frame_pacer").new({clock=clock,numerator=rate.numerator,denominator=rate.denominator})or nil
    local function grant()
        local packet=assert(window:challenge())
        packet.frames=10;packet.ttl_ms=1000;packet.proof_digest=string.rep("c",64)
        packet=assert(JSON.decode(assert(JSON.encode(packet))))
        assert(window:accept(packet))
    end
    local before=emu.framecount();local callbacks=0;local started=clock()
    local hook=event.on_bus_exec(function()callbacks=callbacks+1 end,0x40,"operation-window-vblank","System Bus")
    for _=1,3 do
        grant()
        for _=1,10 do
            if pacer then while not pacer:take(window:ready(),owner.status().host.user_paused)do assert(owner.yield_held())end end
            assert(window:ready());assert(owner.step_one(scope));assert(owner.yield_held())
        end
        assert(not window:ready()and window:status().remaining==0,"window exceeded its frame budget")
        assert(owner.status().host.physical_stop_verified,"budget exhaustion released the physical hold")
    end
    assert(callbacks==30 and emu.framecount()==before+30,"renewals changed the exact native frame count")
    result.elapsed=clock()-started;result.frame_rate=rate;result.paced=config.pace==true
    if pacer then
        local expected=29*rate.denominator/rate.numerator
        assert(result.elapsed>=expected-0.01 and result.elapsed<=expected*1.25+0.05,"native frame pacing differs from the cartridge clock")
    end
    grant();offset=2
    assert(not window:ready(),"expired operation credits remained available")
    assert(not owner.step_one(scope),"expired credit authorized a frame")
    assert(emu.framecount()==before+30 and owner.status().host.physical_stop_verified)
    event.unregisterbyid(hook)
    result.window=window:status();result.host=owner.status();result.frames=30;result.callbacks=callbacks
end,debug.traceback)
result.passed=ok;result.error=not ok and tostring(why)or nil
if owner then pcall(function()owner.set_held(true,"operation window test complete")end)end
local output=assert(io.open(config.output,"w"));output:write(assert(JSON.encode(result)));output:close()
t.check("operation credits bound actual frames",ok,tostring(why));t.finish()
