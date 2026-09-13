-- Witness of a battery-save (CONTINUE) boot. Install before the boot. No frame, cartridge
-- write, admission, or release authority: it records where the CPU went and publishes the
-- ordered witness once, under a held frame.
--
-- The path is source-pinned (data/games/gen1_rby/continue_sites.json, its own file and hash so
-- the New Game receipts already journaled against bootstrap_sites.json keep verifying):
--   load    TryLoadSaveFile entry (MainMenu runs it BEFORE any choice, for the save preview)
--   loaded  TryLoadSaveFile.done: same SP as the entry, register A = wSaveFileStatus (2 = good)
--   chose   MainMenu.choseContinue (the player selected CONTINUE; may repeat if they back out)
--   pressed MainMenu.pressedA (confirmed on the continue info screen)
--   enter   SpecialEnterMap (jumped to from pressedA: same SP)
-- Anything out of this order, a bad checksum, a stack mismatch, or a hit after completion is a
-- failure; the witness is then never published.
local JSON=require('json_codec')
local Data=require('gen1_continue_sites')
local M={}
local ORDER={'load','loaded','chose','pressed','enter'}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function hex(address,count,domain)
    local out={};for i=0,count-1 do out[#out+1]=string.format('%02X',memory.read_u8(address+i,domain or 'System Bus'))end
    return table.concat(out)
end
function M.new(options)
    assert(type(options.owned)=='function' and type(options.held)=='function','owned continue observer required')
    local profile=assert(Data.titles[options.variant]);local sites=assert(profile.sites,'continue sites')
    local owner=copy(options.owned())
    assert(type(owner.context_generation)=='string' and type(owner.physical_instance)=='string','pre-admission physical identity required')
    local hooks={};local seen={};local finished,failure;local closed=false
    local function check()
        assert(not closed and not failure,failure or 'continue observer closed')
        assert(gameinfo.getromhash():lower()==options.final_sha1 and JSON.encode(owner)==JSON.encode(options.owned()),'continue physical context changed')
    end
    local function close_hooks()for _,id in ipairs(hooks)do event.unregisterbyid(id)end;hooks={}end
    local ok,why=pcall(function()
        check()
        for _,kind in ipairs(ORDER)do
            local site=sites[kind]
            assert(hex(site.rom_offset,#site.expected_hex/2,'ROM')==site.expected_hex,'continue ROM anchor differs: '..kind)
            hooks[#hooks+1]=assert(event.on_bus_exec(function()
                if closed or failure or memory.read_u8(profile.bank_address,'System Bus')~=site.bank then return end
                local success,reason=pcall(function()
                    check();assert(not finished,'boot restarted after continue completion')
                    assert(emu.getregister('PC')==site.address and hex(site.address,#site.expected_hex/2)==site.expected_hex,'continue instruction site changed')
                    local witness={frame=emu.framecount(),pc=site.address,bank=site.bank,sp=emu.getregister('SP')}
                    if kind=='load' then
                        assert(not seen.load,'save file loaded twice');seen.load=witness
                    elseif kind=='loaded' then
                        assert(seen.load and not seen.loaded and witness.sp==seen.load.sp and witness.frame>=seen.load.frame,'save file load return lacks its entry')
                        witness.status=emu.getregister('A')
                        assert(witness.status==2,'save file checksum rejected');seen.loaded=witness
                    elseif kind=='chose' then
                        assert(seen.loaded,'CONTINUE chosen before the save file loaded');seen.chose=witness;seen.pressed=nil
                    elseif kind=='pressed' then
                        assert(seen.chose and witness.sp==seen.chose.sp and witness.frame>=seen.chose.frame,'CONTINUE confirmed without the choice');seen.pressed=witness
                    else
                        assert(seen.pressed and witness.sp==seen.pressed.sp and witness.frame>=seen.pressed.frame,'map entered without CONTINUE confirmation')
                        seen.enter=witness
                        finished={schema='rby-continue-receipt-v1',source_sha256=Data.sha256,variant=options.variant,
                            context_generation=owner.context_generation,physical_instance=owner.physical_instance,
                            final_sha1=options.final_sha1,load=seen.load,loaded=seen.loaded,chose=seen.chose,pressed=seen.pressed,enter=witness}
                    end
                end)
                if not success then failure=tostring(reason)end
            end,site.address,'slink-continue-'..kind,'System Bus'))
        end
    end)
    if not ok then close_hooks();error(why,0)end
    return {peek=function()check();assert(options.held(),'continue publication requires held frame');return finished and copy(finished)end,
        status=function()return {loaded=seen.loaded~=nil,chosen=seen.chose~=nil,complete=finished~=nil,failed=failure,closed=closed}end,
        close=function()closed=true;close_hooks()end}
end
return M
