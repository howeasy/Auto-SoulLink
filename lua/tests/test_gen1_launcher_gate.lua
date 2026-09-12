-- Observe an actual generated launcher. Instrumentation only observes native
-- yield/status and exits the private test process; it never grants frames.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_launcher_gate")
local M=t.M
local JSON=dofile(ROOT.."/lua/json_codec.lua")
local function read(path)
    local file=io.open(path,"r");if not file then return nil end
    local value=assert(JSON.decode(file:read("*a")));file:close();return value
end
local input=assert(read(assert(os.getenv("SLINK_LAUNCHER_TEST_INPUT"))))
local memorial_writes,repair_injected=0,false
local fault_armed=false
if type(input.memorial_fault)=="number"then
    local original_write=memory.write_u8
    memory.write_u8=function(address,value,domain)
        fault_armed=fault_armed or read(input.directory.."/memorial-fault-go.json")~=nil
        if fault_armed and not repair_injected and memorial_writes==input.memorial_fault then
            repair_injected=true;error("explicit memorial write interruption fixture")
        end
        if fault_armed then memorial_writes=memorial_writes+1 end
        return original_write(address,value,domain)
    end
end
local function publish(name,value)
    local path=input.directory.."/"..name.."-"..input.player..".json"
    local file=assert(io.open(path..".tmp","w"));file:write(assert(JSON.encode(value)));file:close()
    if name=="diagnostic" then os.remove(path)end
    assert(os.rename(path..".tmp",path))
end
local function wram()
    local values={};for address=0xC000,0xDFFF do values[#values+1]=memory.read_u8(address,"System Bus")end
    return M.bytesToHex(values)
end
local function sram()
    local values={};for address=0,0x7FFF do values[#values+1]=memory.read_u8(address,"CartRAM")end
    return M.bytesToHex(values)
end
publish("observed",{variant=t.variant,save_identity={ot_id=string.format("%04X",M.readPlayerId()),trainer_name=M.readPlayerName()},
    blob=M.bytesToHex(assert(M.readPartyBlob(0))),save_path=os.getenv("SLINK_GATE_SAVERAM")})
local deadline=os.time()+45
while not read(input.directory.."/go.json")do assert(os.time()<deadline,"launcher startup timed out");t.step({})end
for _=1,180 do if M.isPartyWriteSafe()then break end;t.step({})end
assert(M.isPartyWriteSafe(),"launcher needs a verified initial checkpoint")
local initial_frame,before=emu.framecount(),wram()
local before_sram=sram()
local original_yield=emu.yield
local reported,finished,faint_reported,memorial_reported,actor_fixture=false,false,false,false,false
local diagnostic_time=0
local hp_offset=(M.PARTY_BASE_ADDR+M.HP_OFFSET-0xC000)*2+1
local fainted_wram=before:sub(1,hp_offset-1).."0000"..before:sub(hp_offset+4)
emu.yield=function()
    original_yield()
    if not SLINK_RUNTIME_STATUS then return end
    local status=SLINK_RUNTIME_STATUS()
    if not status.host then return end
    assert(status.host.physical_stop_verified and emu.framecount()==initial_frame,"launcher advanced the held game")
    local current_wram=wram()
    if not input.memorial then
        assert(current_wram==before or (input.faint and not input.withhold and input.player=="b" and reported and current_wram==fainted_wram),"launcher changed unrelated WRAM")
    end
    local runtime=status.runtime
    if input.memorial and reported and os.time()~=diagnostic_time then
        diagnostic_time=os.time()
        publish("diagnostic",{status=status,point=require("gen1_full_save").capture(M,t.variant)})
    end
    local complete=input.enrollment and status.initial_observation=="acknowledged" or not input.enrollment and runtime and runtime.pending_commands>0
    if runtime and runtime.session_state=="admitted" and complete and not reported then
        assert(sram()==before_sram,"launcher changed SRAM")
        publish("ready",{status=status,frame_before=initial_frame,frame_after=emu.framecount(),
            wram_unchanged=true,sram_unchanged=true,actual_generated_launcher=true})
        reported=true
    end
    if input.memorial and reported and input.player=="a" and not actor_fixture and read(input.directory.."/death-fixture.json")then
        -- Explicit actor-source fixture; recipient write/save/ACK use production.
        M.forceFaint(0);actor_fixture=true
    end
    if input.memorial and reported and not memorial_reported and M.getPartyCount()==1 and runtime.pending_commands==0 then
        local Full=require("gen1_full_save");local layout=require("gen1_full_save_layout")[t.variant]
        local allowed={};for _,region in pairs(layout.regions)do
            for address=region.address,region.address+region.length-1 do allowed[address]=true end
        end
        allowed[layout.status]=true
        local current=wram()
        for address=0xC000,0xDFFF do
            local i=(address-0xC000)*2+1
            assert(allowed[address] or current:sub(i,i+1)==before:sub(i,i+1),"memorial changed unrelated WRAM")
        end
        publish("memorial",{point=Full.capture(M,t.variant),unchanged_outside_owned_ranges=true,
            repair_injected=repair_injected,save_path=os.getenv("SLINK_GATE_SAVERAM")})
        memorial_reported=true
    end
    if input.faint and not input.memorial and input.player=="b" and reported and not faint_reported and current_wram==fainted_wram
        and runtime.pending_commands==0 then
        assert(sram()==before_sram,"faint changed SRAM")
        publish("faint",{status=status,only_target_hp_changed=true,sram_unchanged=true})
        faint_reported=true
    end
    if input.withhold and input.player=="b" and reported and not faint_reported and runtime.pending_commands>0 then
        assert(current_wram==before and sram()==before_sram,"withheld permit changed memory")
        publish("faint",{status=status,only_target_hp_changed=false,sram_unchanged=true});faint_reported=true
    end
    if reported and read(input.directory.."/finish.json")then
        finished=true
        t.check("generated launcher enters isolated held durable service",true)
        t.finish()
    end
end
local ok,why=xpcall(function()dofile(input.launcher)end,debug.traceback)
emu.yield=original_yield
if input.expect_mismatch then
    t.check("mismatched client bundle refuses before client startup",not ok and not SLINK_RUNTIME_STATUS
        and tostring(why):find("client files differ",1,true)~=nil and emu.framecount()==initial_frame and wram()==before,tostring(why))
    t.finish()
end
if not finished then t.check("generated launcher completed qualification",false,tostring(why));t.finish()end
