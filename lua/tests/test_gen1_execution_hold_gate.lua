-- Run the reviewed actuator probe in a fresh fixture-backed Gambatte process.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_execution_hold_gate")
local JSON=dofile(ROOT.."/lua/json_codec.lua")
local input=assert(io.open(ROOT.."/.cache/gen1-execution-probe-input.json","r"))
local config=assert(JSON.decode(input:read("*a")));input:close()
local report={schema=1,passed=false,release_ready=false,variant=t.variant,
    rom_sha1=gameinfo.getromhash():lower(),checkpoints=JSON.array(),evidence={}}
local function checkpoint(label)
    report.checkpoints[#report.checkpoints+1]={label=label,frame=emu.framecount()}
    local file=assert(io.open(config.result_path,"w"));file:write(assert(JSON.encode(report)));file:close()
end
local ok,why=xpcall(function()
    assert(report.rom_sha1==config.rom_sha1 and t.variant==config.variant,"wrong isolated cartridge")
    luanet.load_assembly("System");luanet.load_assembly("System.Windows.Forms")
    local Application=luanet.import_type("System.Windows.Forms.Application")
    local Process=luanet.import_type("System.Diagnostics.Process")
    local forms=Application.OpenForms:GetEnumerator();local main
    while forms:MoveNext() do
        if tostring(forms.Current:GetType().FullName)=="BizHawk.Client.EmuHawk.MainForm" then
            assert(not main,"multiple MainForms");main=forms.Current
        end
    end
    assert(main,"MainForm absent")
    local process=Process.GetCurrentProcess()
    local core_type=tostring(main.Emulator:GetType().FullName)
    report.host={process_id=tonumber(process.Id),core_type=core_type,version=client.getversion()}
    checkpoint("private_fixture_ready")
    local ctx={config=config,report=report,main_form=main,checkpoint=checkpoint,
        host={available=true,matches_requested_core=core_type==config.probe_options.expected_host.core_type,
              process_id=tonumber(process.Id)}}
    ctx.check=function(name,actual,expected)
        if not t.check(name,actual==expected,tostring(actual).." / "..tostring(expected)) then
            error("execution probe assertion failed: "..name)
        end
    end
    dofile(ROOT.."/lua/tests/platform_execution_probe.lua")(ctx)
end,debug.traceback)
report.passed=ok and t.failures==0;report.failure=not ok and tostring(why) or nil
checkpoint("complete")
t.check("private Gambatte execution probe completed",report.passed,tostring(why))
t.finish()
