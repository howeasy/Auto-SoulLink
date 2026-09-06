-- Loaded as a separate LuaFile solely by the private stopped/reload observer.
local C=assert(SLINK_EXEC_HELPER,"private helper context missing")
local Application=luanet.import_type("System.Windows.Forms.Application")
local forms=Application.OpenForms:GetEnumerator();local main
while forms:MoveNext() do
    if tostring(forms.Current:GetType().FullName)=="BizHawk.Client.EmuHawk.MainForm" then
        assert(not main,"multiple MainForms");main=forms.Current
    end
end
assert(main,"MainForm unavailable")
local Thread=luanet.import_type("System.Threading.Thread")
local Execution=dofile(C.source_root.."/lua/platform_execution.lua")
local owner,reason=Execution.new({owner_id=C.owner_id,profile=C.profile,expected_host=C.expected_host,
    exclusive_ownership="emulator_process",control_context="between_frames"})
local ticks=0
local function record(phase,why)
    local state=owner and owner.status() or {}
    local line={phase,tostring(ticks),tostring(emu.framecount()),tostring(Thread.CurrentThread.ManagedThreadId),
        tostring(main.BlockFrameAdvance),tostring(main.EmulatorPaused),C.owner_id,state.lease_name or "",
        (tostring(why or ""):gsub("[\t\r\n]"," "))}
    local file=assert(io.open(C.status_path,"w"));file:write(table.concat(line,"\t"),"\n");file:close()
end
if not owner then record("refused",reason);return end
local held,why=owner.set_held(true,"private helper retained hold")
if not held then record("failed",why);return end
local exit_id=event.onexit(function() record("exit","only this helper LuaFile was stopped") end,"private_execution_helper_exit")
if type(exit_id)~="string" or exit_id:gsub("[{}%-]","")==string.rep("0",32) then
    record("failed","helper exit callback unavailable");return
end
while true do
    ticks=ticks+1;record("held")
    local yielded,error_text=owner.yield_held()
    if not yielded then record("failed",error_text);return end
end
