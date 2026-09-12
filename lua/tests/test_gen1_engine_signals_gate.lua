-- Original-routine observation differential in a cloned core. CPU injection,
-- party setup and frame ownership are explicit test fixtures, not runtime grants.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_engine_signals_gate")
package.path=ROOT.."/lua/?.lua;"..ROOT.."/data/games/gen1_rby/?.lua;"..package.path
local JSON=require("json_codec")
local Signals=require("gen1_engine_signals")
local Journal=require("client_journal")
local Store=require("state_store")
local Storage=require("platform_storage")
local input=assert(io.open(os.getenv("SLINK_SIGNAL_INPUT"),"r"));local spec=assert(JSON.decode(input:read("*a")));input:close()
local output=os.getenv("SLINK_SIGNAL_RESULT")
local source=t.variant=="yellow" and "pokeyellow" or "pokered"
local target=t.variant=="blue" and "pokeblue" or source
local profile=require("gen1_engine_signal_data").titles[t.variant]
local symbols_path=ROOT.."/.cache/pret/"..source.."/"..target..".sym"
local source_symbols=assert(io.open(symbols_path,"r"));local symbols_text=source_symbols:read("*a");source_symbols:close()
local private_symbols=assert(io.open(output..".sym","w"))
private_symbols:write(symbols_text,string.format("\n%02x:%04x SLinkTestStarterCall\n",profile.sites.starter_begin.bank,profile.sites.starter_begin.address))
private_symbols:close()
local probe,mode,stop_hook,return_hook
local Full=require("gen1_full_save")
local oracle=dofile(ROOT.."/lua/tests/gb_routine_oracle.lua").new({
    symbols_path=output..".sym",step=function()
        t.step({A=mode~="starter" and t.frame%20<10,B=mode=="starter" and t.frame%20<10});if probe then probe:flush()end
    end,scratch=0xCB00,marker=0xCBF0,stack=0xDFFE,bankswitch="Bankswitch",enable_interrupts=true,timeout_frames=1800})
local boot=memorysavestate.savecorestate();local cases=JSON.array()
local function write(name,value)memory.write_u8(oracle.address(name),value,"System Bus")end
local function put(address,hex)
    for i=1,#hex,2 do memory.write_u8(address+(i-1)/2,tonumber(hex:sub(i,i+1),16),"System Bus")end
end
local function get(address,count)
    local out={};for i=0,count-1 do out[#out+1]=string.format("%02X",memory.read_u8(address+i,"System Bus"))end
    return table.concat(out)
end
local function state_image()
    local out={get(0xC000,0x2000)}
    for p=0,0x7FFF do out[#out+1]=string.format("%02X",memory.read_u8(p,"CartRAM"))end
    return table.concat(out)
end
local function invoke(cause)
    if cause=="starter"then
        -- Stop the test after the real AddPartyMon return, before resuming its
        -- enclosing text script. This hook is test-only CPU control.
        local returned=false
        local stop=profile.sites.starter_end.address+(t.variant=="yellow" and 2 or 3)
        if spec.complete_starter then
            assert(oracle.symbol("TextScriptEnd").bank==0)
            stop=oracle.address("TextScriptEnd")
            return_hook=event.on_bus_exec(function()
                if memory.read_u8(profile.addresses.hLoadedROMBank,"System Bus")==profile.sites.starter_end.bank then returned=true end
            end,profile.sites.starter_end.address,"fixture-starter-return-observed","System Bus")
        end
        stop_hook=event.on_bus_exec(function()
            if (spec.complete_starter and returned) or (not spec.complete_starter and
                memory.read_u8(profile.addresses.hLoadedROMBank,"System Bus")==profile.sites.starter_end.bank)then
                memory.write_u8(0xCBF0,0xA5,"System Bus");emu.setregister("PC",0xCB0E)
            end
        end,stop,"fixture-starter-return-stop","System Bus")
    end
    oracle.invoke(cause=="battle" and "RemoveFaintedPlayerMon" or cause=="poison" and "ApplyOutOfBattlePoisonDamage" or "SLinkTestStarterCall")
    if stop_hook then event.unregisterbyid(stop_hook);stop_hook=nil end
    if return_hook then event.unregisterbyid(return_hook);return_hook=nil end
end
local ok,why=xpcall(function()
    for _,cause in ipairs(spec.only_starter and {"starter"} or {"battle","poison","starter"})do
        mode=cause
        memorysavestate.loadcorestate(boot)
        put(profile.addresses.wPartyDataStart,spec.party_hex)
        write("wPlayerMonNumber",0);write("wWhichPokemon",0)
        write("wIsInBattle",cause=="battle" and 1 or 0)
        write("wInHandlePlayerMonFainted",0)
        write("wBattleMonSpecies",tonumber(spec.party_hex:sub(17,18),16))
        write("wBattleMonHP",0);memory.write_u8(oracle.address("wBattleMonHP")+1,0,"System Bus")
        write("wBattleMonStatus",0);write("wBattleMonLevel",5)
        write("wLowHealthAlarm",0);write("wStepCounter",0)
        write("wStatusFlags5",0)
        if t.variant=="yellow"then write("wPikachuMapScriptFlags",0)end
        if cause=="poison"then
            write("wPartyMon1HP",0);memory.write_u8(oracle.address("wPartyMon1HP")+1,1,"System Bus")
            write("wPartyMon1Status",8)
        elseif cause=="starter"then
            write("wPartyCount",0);write("wPartySpecies",255)
            write("wCurMap",profile.starter_map);write("wMonDataLocation",0)
            write("wCurEnemyLevel",5);write("wCurPartySpecies",spec.species or 153);write("wPokedexNum",spec.species or 153)
            if spec.complete_starter then
                local value=memory.read_u8(oracle.address("wStatusFlags4"),"System Bus")
                write("wStatusFlags4",value-bit.band(value,8))
            end
        end
        local initial_point=Full.capture(t.M,t.variant);local initial_frame=emu.framecount()
        local case_start=memorysavestate.savecorestate();local input_frame=t.frame
        local store=assert(Store.open(assert(Storage.new(output.."."..cause..".store")),
            {fixture=cause,variant=t.variant},Journal.initial()))
        local journal=assert(Journal.open(store))
        local context={context_generation=spec.context_generation or (cause=="battle" and string.rep("a",32) or string.rep("b",32))}
        probe=Signals.new({journal=journal,variant=t.variant,final_sha1=gameinfo.getromhash():lower(),
            owned=function()return context end,held=function()return true end})
        invoke(cause)
        local events=assert(journal:pending_events())
        local signals=JSON.array()
        for _,entry in ipairs(events)do for _,row in ipairs(entry.payload.payload.signals)do signals[#signals+1]=row end end
        assert(#signals==(cause=="starter" and 2 or 1),"original routine did not produce the exact source signals")
        if cause=="starter"then assert(signals[1].kind=="starter_begin" and signals[2].kind=="starter_end","starter call was not paired")
        else assert(signals[1].kind==cause.."_faint","wrong source signal")end
        local final_point=Full.capture(t.M,t.variant);local final_frame=emu.framecount()
        oracle.invoke("HealParty")
        assert(memory.read_u16_be(oracle.address("wPartyMon1HP"),"System Bus")>0,"original HealParty did not heal")
        local after_healing=get(profile.addresses.wPartyDataStart,404)
        local observed_image=state_image();local observed_frame=emu.framecount()
        probe:close();probe=nil;store:close()
        memorysavestate.loadcorestate(case_start);t.frame=input_frame
        invoke(cause);oracle.invoke("HealParty")
        assert(state_image()==observed_image and emu.framecount()==observed_frame,
            "read-only engine observer changed native WRAM/SRAM/frame outcome")
        memorysavestate.removestate(case_start)
        cases[#cases+1]={cause=cause,signals=signals,events=events,after_healing=after_healing,unchanged=true,
            initial_point=initial_point,initial_frame=initial_frame,final_point=final_point,final_frame=final_frame}
    end
end,debug.traceback)
if probe then probe:close()end
if stop_hook then event.unregisterbyid(stop_hook)end
if return_hook then event.unregisterbyid(return_hook)end
memorysavestate.loadcorestate(boot);memorysavestate.removestate(boot)
local file=assert(io.open(output,"w"));file:write(assert(JSON.encode({variant=t.variant,passed=ok,
    reason=ok and "passed" or tostring(why),cases=cases})));file:close()
t.check("engine source signals survive original healing",ok,tostring(why));t.finish()
