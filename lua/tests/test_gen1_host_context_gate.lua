local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
package.path=ROOT.."/lua/?.lua;"..package.path
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_host_context_gate")
local JSON=require("json_codec")
local input=assert(io.open(assert(os.getenv("SLINK_HOST_CONTEXT_INPUT")),"r"))
local config=assert(JSON.decode(input:read("*a")));input:close()
local result={schema="slink-host-context-test-v1",variant=t.variant,case=config.case,passed=false}
local owner
local ok,why=xpcall(function()
    local authority={}
    owner=require("platform_bounded_execution").new({profile="gambatte",owner_id=assert(require("platform_identity").new_nonce()),
        expected_host=require("platform_execution").supported_profile("gambatte"),authorize=function(value)return value==authority end})
    local before=emu.framecount()
    result.before=before
    if config.case=="same_frame_load"or config.case=="older_state_load"then
        savestate.save(config.state)
        local file=assert(io.open(config.state,"rb"));assert(#file:read("*a")>0);file:close()
        if config.case=="older_state_load"then
            for _=1,5 do assert(owner.step_one(authority));assert(owner.yield_held())end
            assert(emu.framecount()==before+5)
        end
        result.pre_load=emu.framecount()
        savestate.load(config.state)
        assert(emu.framecount()==before,"actual savestate did not restore its frame")
        assert(owner.status().failed and owner.status().failed:find("savestate load"),"load callback did not invalidate the owner")
        assert(not owner.step_one(authority),"stale authority survived savestate load")
    elseif config.case=="menu_power"then
        local App=luanet.import_type("System.Windows.Forms.Application")
        local Enum=luanet.import_type("System.Enum")
        local Flags=luanet.import_type("System.Reflection.BindingFlags")
        local Array=luanet.import_type("System.Array")
        local Object=luanet.import_type("System.Object")
        local flags=Enum.Parse(luanet.ctype(Flags),"Instance, Public, NonPublic")
        local forms=App.OpenForms:GetEnumerator();local main
        while forms:MoveNext()do if tostring(forms.Current:GetType().FullName)=="BizHawk.Client.EmuHawk.MainForm"then main=forms.Current end end
        local find=luanet.get_method_bysig(main:GetType(),"GetMethod","System.String","System.Reflection.BindingFlags")
        local method=assert(find("HardReset",flags))
        local invoke=luanet.get_method_bysig(method,"Invoke","System.Object","System.Object[]")
        invoke(main,Array.CreateInstance(luanet.ctype(Object),0)) -- actual menu/hotkey reset implementation
        assert(not owner.step_one(authority),"queued native Power reset consumed a frame")
    elseif config.case=="controller_power"then
        joypad.set({Power=true})
        local held=owner.yield_held() -- outer input chain latches the real Lua button override
        assert(not held or not owner.step_one(authority),"controller Power input consumed a frame")
        assert(owner.status().failed,"reset input did not invalidate the current owner")
    else error("unknown context test")end
    assert(emu.framecount()==before,"a frame escaped after context invalidation")
    result.final=owner.status();result.after=emu.framecount()
    assert(result.final.host.physical_stop_verified,"context refusal lost the independent hold")
end,debug.traceback)
result.passed=ok;result.error=not ok and tostring(why)or nil
if owner then pcall(function()owner.set_held(true,"context test complete")end)end
local output=assert(io.open(config.output,"w"));output:write(assert(JSON.encode(result)));output:close()
t.check("host context invalidation precedes the next frame",ok,tostring(why));t.finish()
