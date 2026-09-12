-- Original delivery routines and original nickname UI. CPU/data setup and
-- post-return stop are explicit fixtures; the observer itself only reads.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_capture_gate")
package.path=ROOT.."/lua/?.lua;"..ROOT.."/data/games/gen1_rby/?.lua;"..package.path
local JSON=require("json_codec");local Data=require("gen1_capture_sites");local profile=Data.titles[t.variant]
local output=assert(os.getenv("SLINK_CAPTURE_RESULT"));local input=assert(io.open(os.getenv("SLINK_CAPTURE_INPUT"),"r"))
local spec=assert(JSON.decode(input:read("*a")));input:close()
local source=t.variant=="yellow" and "pokeyellow" or "pokered";local target=t.variant=="blue" and "pokeblue" or source
local original=assert(io.open(ROOT.."/.cache/pret/"..source.."/"..target..".sym","r"))
local symbols=original:read("*a");original:close();local file=assert(io.open(output..".sym","w"));file:write(symbols)
for _,destination in ipairs({"party","box"})do
    local site=profile.sites[destination.."_begin"]
    file:write(string.format("\n%02x:%04x SLinkCapture_%s\n",site.bank,site.address,destination))
end
file:close()
local observer
local input_frame=0
local oracle=dofile(ROOT.."/lua/tests/gb_routine_oracle.lua").new({symbols_path=output..".sym",scratch=0xCB00,marker=0xCBF0,
    stack=0xDFFE,bankswitch="Bankswitch",enable_interrupts=true,timeout_frames=1800,
    step=function()input_frame=input_frame+1;t.step({B=input_frame%20<10,A=false})end})
local function write(name,value)oracle.write(oracle.address(name),value)end
local function put(name,hex)
    local address=oracle.address(name)
    for i=1,#hex,2 do oracle.write(address+(i-1)/2,tonumber(hex:sub(i,i+1),16))end
end
local boot=memorysavestate.savecorestate();local rows=JSON.array();local stop_hook
local function state_image()
    local bytes={}
    for address=0xC000,0xDFFF do bytes[#bytes+1]=memory.read_u8(address,'System Bus')end
    for address=0,0x7FFF do bytes[#bytes+1]=memory.read_u8(address,'CartRAM')end
    return t.M.bytesToHex(bytes)
end
local ok,why=xpcall(function()
    for _,case in ipairs(spec.cases)do
        memorysavestate.loadcorestate(boot)
        put('wPartyDataStart',case.party_hex);put('wBoxDataStart',case.box_hex)
        write('wCurrentBoxNum',3);write('wIsInBattle',1);write('wBattleType',0)
        write('wCurPartySpecies',case.species);write('wEnemyMonSpecies2',case.species);write('wCurEnemyLevel',7)
        write('wEnemyBattleStatus3',0)
        oracle.invoke('LoadEnemyMonData')
        write('wCapturedMonSpecies',case.species);write('wCurPartySpecies',case.species);write('wMonDataLocation',0)
        local scope={context_generation=string.rep('a',32)}
        local site=profile.sites[case.destination..'_end']
        local stop=case.destination=='party' and oracle.address('ItemUseBall.done') or site.address+3
        stop_hook=event.on_bus_exec(function()
            if memory.read_u8(profile.addresses.hLoadedROMBank,'System Bus')==site.bank then
                oracle.write(0xCBF0,0xA5);emu.setregister('PC',0xCB0E)
            end
        end,stop,'fixture-capture-return-stop','System Bus')
        local clone=memorysavestate.savecorestate();input_frame=0
        local start=emu.framecount();oracle.invoke('SLinkCapture_'..case.destination)
        local baseline,frames=state_image(),emu.framecount()-start
        memorysavestate.loadcorestate(clone)
        observer=require('gen1_capture_observer').new({variant=t.variant,final_sha1=gameinfo.getromhash():lower(),
            owned=function()return scope end,held=function()return true end})
        input_frame=0;start=emu.framecount()
        oracle.invoke('SLinkCapture_'..case.destination)
        assert(state_image()==baseline and emu.framecount()-start==frames,'capture observer changed memory or frame outcomes')
        memorysavestate.removestate(clone)
        event.unregisterbyid(stop_hook);stop_hook=nil
        local signals=observer.peek();assert(#signals==2,'capture needs one call and one return')
        rows[#rows+1]={destination=case.destination,signals=signals,observer_equal=true,frames=frames}
        assert(observer.acknowledge(signals));assert(#observer.peek()==0);observer.close();observer=nil
    end
end,debug.traceback)
if stop_hook then event.unregisterbyid(stop_hook)end
if observer then observer.close()end
memorysavestate.loadcorestate(boot);memorysavestate.removestate(boot)
local result=assert(io.open(output,'w'));result:write(assert(JSON.encode({passed=ok,reason=ok and 'passed' or tostring(why),cases=rows})));result:close()
t.check('capture delivery observer completed original routines',ok,tostring(why));t.finish()
