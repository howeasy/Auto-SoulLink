-- Real cold boot and normal menus. No CPU/register/cartridge writes or injected stop.
local ROOT=SLINK_ROOT or os.getenv('SLINK_ROOT')
local G=dofile(ROOT..'/lua/tests/gatelib.lua');local t=G.start("test_gen1_bootstrap_gate",{no_boot=true})
package.path=ROOT..'/lua/?.lua;'..ROOT..'/data/games/gen1_rby/?.lua;'..package.path
local JSON=require('json_codec');local output=assert(os.getenv('SLINK_BOOTSTRAP_RESULT'))
local profile=require('gen1_bootstrap_sites').titles[t.variant]
local source=t.variant=='yellow' and 'pokeyellow' or 'pokered'
local target=t.variant=='blue' and 'pokeblue' or source
local symbols={}
for line in io.lines(ROOT..'/.cache/pret/'..source..'/'..target..'.sym')do
    local _,address,name=line:match('^(%x+):(%x+) (%S+)$');if address then symbols[name]=tonumber(address,16)end
end
local function read(name)return memory.read_u8(assert(symbols[name]),'System Bus')end
local screenshots=JSON.array();local phase='baseline'
local function shot(label)
    local path=output..'.'..label..'.png';client.screenshot(path);screenshots[#screenshots+1]=path
end
local function state_image()
    local bytes={}
    for address=0xC000,0xDFFF do bytes[#bytes+1]=memory.read_u8(address,'System Bus')end
    for address=0,0x7FFF do bytes[#bytes+1]=memory.read_u8(address,'CartRAM')end
    return t.M.bytesToHex(bytes)
end
local initial=memorysavestate.savecorestate();local original_image=state_image()
local observer,hook,bounded_owner;local returned;local held=false;local result
local function drive()
    returned=nil;held=false
    for index=1,12000 do
        local beat=index%16;local buttons={A=beat<2,Start=beat==8,Down=false,Left=false,Right=false,B=false}
        if read('wMaxMenuItem')==3 and read('wTopMenuItemY')==2 and read('wTopMenuItemX')==1 then
            buttons={Down=read('wCurrentMenuItem')==0,A=read('wCurrentMenuItem')>0 and beat<2,Start=false,B=false}
        end
        t.step(buttons)
        if index%512==0 then shot(phase..'-'..index)end
        if returned then
            for _=1,180 do t.step({A=false,Start=false,Down=false,Left=false,Right=false,B=false})end
            shot(phase..'-bedroom')
            local x,y,map=read('wXCoord'),read('wYCoord'),read('wCurMap')
            for _=1,24 do t.step({Left=true,A=false,Start=false,Down=false,Right=false,B=false})end
            assert(read('wCurMap')==map and (read('wXCoord')~=x or read('wYCoord')~=y),'new-game bedroom is not walkable')
            shot(phase..'-walked')
            held=true;return
        end
    end
    error('normal new game did not complete')
end
local ok,why=xpcall(function()
    local site=profile.sites['end']
    hook=event.on_bus_exec(function()
        if memory.read_u8(profile.bank_address,'System Bus')==site.bank then returned=emu.framecount()end
    end,site.address,'test-bootstrap-read-only-return','System Bus')
    local start=emu.framecount();drive();local baseline,frames=state_image(),emu.framecount()-start
    memorysavestate.loadcorestate(initial);phase='observed'
    local scope={context_generation=string.rep('a',32),physical_instance=string.rep('1',32)}
    local bounded=os.getenv('SLINK_BOOTSTRAP_BOUNDED')=='1'
    if bounded then
        local authority={};local allow=true
        bounded_owner=require('platform_bounded_execution').new({profile='gambatte',owner_id=scope.physical_instance,
            expected_host=require('platform_execution').supported_profile('gambatte'),
            authorize=function(value)return allow and value==authority end})
        t.step=function(buttons)
            if buttons then joypad.set(buttons)end
            local ok,reason=bounded_owner.step_one(authority);assert(ok,reason)
            assert(bounded_owner.status().host.physical_stop_verified)
            t.frame=t.frame+1
        end
    end
    observer=require('gen1_bootstrap_observer').new({variant=t.variant,final_sha1=gameinfo.getromhash():lower(),
        owned=function()return scope end,held=function()return held and (not bounded_owner or bounded_owner.status().host.physical_stop_verified)end})
    start=emu.framecount();drive()
    assert(state_image()==baseline and emu.framecount()-start==frames,'observer changed memory or frame outcomes')
    result={receipt=assert(observer.peek()),point=require('gen1_full_save').capture(t.M,t.variant),
        frame=emu.framecount(),observer_equal=true,frames=frames,normal_menu_entry=true,walked=true,
        bounded=bounded,authorized_steps=bounded_owner and bounded_owner.status().steps or nil}
    if bounded_owner then
        assert(result.authorized_steps==frames,'bounded bootstrap frame accounting differs')
        local before=emu.framecount();local advanced=bounded_owner.step_one({})
        assert(not advanced and emu.framecount()==before and bounded_owner.status().host.physical_stop_verified,
            'foreign frame authority escaped the hold')
    end
end,debug.traceback)
if observer then observer.close()end
if hook then event.unregisterbyid(hook)end
memorysavestate.loadcorestate(initial);memorysavestate.removestate(initial)
local restored=state_image()==original_image
if not restored then ok=false;why='test restore changed original WRAM or SRAM'end
local file=assert(io.open(output,'w'));file:write(assert(JSON.encode({passed=ok,error=not ok and tostring(why)or nil,
    result=result,restored=restored,screenshots=screenshots})));file:close()
t.check('normal new game, walkable bedroom and read-only observer match',ok,tostring(why));t.finish()
