-- Controlled original inventory routine and physical faint executor proof.
-- Setup registers, CPU invocation and write authority are explicit fixtures.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_ball_activation_gate")
package.path=ROOT.."/lua/?.lua;"..ROOT.."/data/games/gen1_rby/?.lua;"..package.path
local JSON=require("json_codec");local Store=require("state_store");local Storage=require("platform_storage")
local Journal=require("client_journal");local Signals=require("gen1_engine_signals")
local input=assert(io.open(os.getenv("SLINK_BALL_INPUT"),"r"));local spec=assert(JSON.decode(input:read("*a")));input:close()
local output=os.getenv("SLINK_BALL_RESULT");local source=t.variant=="yellow" and "pokeyellow" or "pokered"
local target=t.variant=="blue" and "pokeblue" or source
local probe,argument_hook,destination
local oracle=dofile(ROOT.."/lua/tests/gb_routine_oracle.lua").new({
    symbols_path=ROOT.."/.cache/pret/"..source.."/"..target..".sym",scratch=0xCB00,marker=0xCBF0,stack=0xDFFE,bankswitch="Bankswitch",
    step=function()t.step({});if probe then probe:flush()end end})
local function put(address,hex)
    for i=1,#hex,2 do memory.write_u8(address+(i-1)/2,tonumber(hex:sub(i,i+1),16),"System Bus")end
end
local function full_image()
    local rows={};for p=0xC000,0xDFFF do rows[#rows+1]=string.format("%02X",memory.read_u8(p,"System Bus"))end
    for p=0,0x7FFF do rows[#rows+1]=string.format("%02X",memory.read_u8(p,"CartRAM"))end
    return table.concat(rows)
end
local boot=memorysavestate.savecorestate();local cases=JSON.array();local receipt,command
local ok,why=xpcall(function()
    for _,kind in ipairs({"bag","pc","full","split","nonball"})do
        memorysavestate.loadcorestate(boot)
        local addr=oracle.address(kind=="pc" and "wNumBoxItems" or "wNumBagItems");destination=addr
        memory.write_u8(addr,0,"System Bus");memory.write_u8(addr+1,255,"System Bus")
        if kind=="full"then
            memory.write_u8(addr,20,"System Bus")
            for slot=0,19 do memory.write_u8(addr+1+slot*2,20+slot,"System Bus");memory.write_u8(addr+2+slot*2,1,"System Bus")end
            memory.write_u8(addr+41,255,"System Bus")
        elseif kind=="split"then
            memory.write_u8(addr,1,"System Bus");memory.write_u8(addr+1,4,"System Bus")
            memory.write_u8(addr+2,98,"System Bus");memory.write_u8(addr+3,255,"System Bus")
        end
        memory.write_u8(oracle.address("wCurItem"),kind=="nonball" and 20 or 4,"System Bus")
        memory.write_u8(oracle.address("wItemQuantity"),5,"System Bus")
        local clone=memorysavestate.savecorestate()
        local store=assert(Store.open(assert(Storage.new(output.."."..kind..".store")),{fixture=kind},Journal.initial()))
        local journal=assert(Journal.open(store))
        local context={context_generation=string.rep("a",32)}
        probe=Signals.new({journal=journal,variant=t.variant,final_sha1=gameinfo.getromhash():lower(),
            owned=function()return context end,held=function()return true end})
        -- Bankswitch uses HL for the callee; supply the original routine's HL
        -- argument at entry in both observer-on and observer-off cloned runs.
        argument_hook=event.on_bus_exec(function()emu.setregister("H",math.floor(destination/256));emu.setregister("L",destination%256)end,
            oracle.address("AddItemToInventory_"),"fixture-inventory-argument","System Bus")
        oracle.invoke("AddItemToInventory_")
        local events=assert(journal:pending_events());local expected=kind=="bag" or kind=="split"
        assert(#events==(expected and 1 or 0),"bag activation did not match original successful destination: "..kind)
        local image=full_image();local frame=emu.framecount()
        probe:close();probe=nil;store:close()
        memorysavestate.loadcorestate(clone);oracle.invoke("AddItemToInventory_")
        assert(full_image()==image and emu.framecount()==frame,"observer changed original inventory outcome")
        event.unregisterbyid(argument_hook);argument_hook=nil;memorysavestate.removestate(clone)
        cases[#cases+1]={kind=kind,events=events,unchanged=true}
    end
    memorysavestate.loadcorestate(boot)
    put(oracle.address("wPartyDataStart"),spec.party_hex)
    memory.write_u8(oracle.address("wIsInBattle"),1,"System Bus")
    memory.write_u8(oracle.address("wPlayerMonNumber"),0,"System Bus")
    memory.write_u8(oracle.address("wBattleMonHP"),0,"System Bus");memory.write_u8(oracle.address("wBattleMonHP")+1,10,"System Bus")
    local store=assert(Store.open(assert(Storage.new(output..".faint.store")),{fixture="faint"},Journal.initial()))
    local journal=assert(Journal.open(store));local op=assert(journal:append({event="fixture-command-delivery"}))
    local identity={ot_id=string.format("%04X",t.M.readPlayerId()),trainer_name=t.M.readPlayerName()}
    command={cmd="force_faint",key=t.M.readPartySlot(0).key}
    local id=string.rep("f",32)
    assert(journal:accept_response(op,JSON.array({{command_id=id,command_sequence=1,body=command}})))
    local executor=require("command_executor").new(journal,require("gen1_force_faint_executor").new(t.M,t.variant,identity,function()return true end))
    local frame=emu.framecount();local complete,diagnostic=executor:step(id)
    assert(complete,JSON.encode(diagnostic));assert(emu.framecount()==frame,"faint writer advanced a frame")
    receipt=assert(journal:get_command(id)).receipt
    assert(executor:step(id));assert(emu.framecount()==frame,"faint replay advanced a frame")
    store:close()
end,debug.traceback)
if probe then probe:close()end;if argument_hook then event.unregisterbyid(argument_hook)end
memorysavestate.loadcorestate(boot);memorysavestate.removestate(boot)
local file=assert(io.open(output,"w"));file:write(assert(JSON.encode({passed=ok,reason=ok and "passed" or tostring(why),
    variant=t.variant,cases=cases,receipt=receipt,command=command})));file:close()
t.check("original bag activation and physical faint readback",ok,tostring(why));t.finish()
