local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
package.path=ROOT.."/lua/?.lua;"..package.path
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_bounded_execution_gate")
local JSON=require("json_codec")
local f=assert(io.open(assert(os.getenv("SLINK_BOUNDED_INPUT")),"r"));local config=assert(JSON.decode(f:read("*a")));f:close()
local result={schema="bounded-host-test-v1",variant=t.variant,checks=JSON.array(),passed=false}
local owner
local ok,why=xpcall(function()
    if config.paused then client.pause()end
    local bus_calls=0
    local hook=event.on_bus_exec(function()bus_calls=bus_calls+1 end,0x40,"bounded-frame-vblank","System Bus")
    local authority={};local allow=true
    owner=require("platform_bounded_execution").new({profile="gambatte",owner_id=assert(require("platform_identity").new_nonce()),
        expected_host=require("platform_execution").supported_profile("gambatte"),
        authorize=function(value)return value==authority and allow end})
    local initial=emu.framecount()
    assert(owner.status().host.user_paused==config.paused,"initial pause differs")
    for index=1,30 do
        local before=emu.framecount()
        local advanced,receipt=owner.step_one(authority)
        assert(advanced,receipt)
        assert(receipt.before==before and receipt.after==before+1 and receipt.step==index,"frame receipt differs")
        assert(owner.status().host.user_paused==config.paused and owner.status().host.physical_stop_verified,"pause/hold changed")
        assert(owner.yield_held());assert(emu.framecount()==before+1,"frame escaped held yield")
        result.checks[#result.checks+1]=receipt
    end
    assert(bus_calls==30 and emu.framecount()==initial+30,"memory callbacks or frame budget differ")
    local before=emu.framecount()
    allow=false
    local advanced,problem=owner.step_one(authority)
    assert(not advanced and tostring(problem):find("authority"),"expired authority advanced a frame")
    assert(emu.framecount()==before and owner.status().host.physical_stop_verified,"authority refusal did not retain hold")
    assert(not owner.set_held(false,"test unbounded release"),"unbounded release was exposed")
    result.bus_callbacks=bus_calls;result.final=owner.status()
    event.unregisterbyid(hook)
end,debug.traceback)
result.passed=ok;result.error=not ok and tostring(why)or nil
if owner then pcall(function()owner.set_held(true,"bounded qualification completed")end)end
local out=assert(io.open(config.output,"w"));out:write(assert(JSON.encode(result)));out:close()
t.check("bounded owned frame stepping",ok,tostring(why));t.finish()
