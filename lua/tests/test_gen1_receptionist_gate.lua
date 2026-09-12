-- Actual object interaction. The only map setup is a one-shot fixture flag;
-- normal CONTINUE and LoadMapHeader initialize the map. No CPU redirection.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local JSON=dofile(ROOT.."/lua/json_codec.lua")
local function read_json(path)
    local f=assert(io.open(path,"r"));local raw=f:read("*a");f:close();return assert(JSON.decode(raw))
end
local input=read_json(assert(os.getenv("SLINK_RECEPTIONIST_INPUT")))
local fixture,manifest=input.fixture,input.manifest
local a,rom=fixture.ram,fixture.rom
local function r(p)return memory.read_u8(p,"System Bus")end
local function w(p,v)memory.write_u8(p,v,"System Bus")end
local function hex(p,count,domain)
    local result={}
    for i=0,count-1 do result[#result+1]=string.format("%02X",memory.read_u8(p+i,domain or "System Bus"))end
    return table.concat(result)
end
local map_fixture=dofile(ROOT.."/lua/tests/gen1_map_fixture.lua").start(fixture,"receptionist")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_receptionist_gate")
map_fixture:close()
local M=t.M
local overlay=manifest.foreground.overlay
local s,case,clock
local hooks,observations={},{}
local function party_storage()return hex(a.wPartyCount,a.wPartyMonNicks+66-a.wPartyCount)end
local function failure(message)s.errors[#s.errors+1]=message end
local function hook(address,bank,fn)
    hooks[#hooks+1]=event.on_bus_exec(function()
        if s and (bank==0 or r(a.hLoadedROMBank)==bank)then fn()end
    end,address,"receptionist-gate-"..#hooks,"System Bus")
end
local function own_hook(name,fn)hook(manifest.receptionist[name],manifest.receptionist.entry.bank,fn)end
local function menu_state()
    local data=hex(a.wTopMenuItemY,8)
    for _,name in ipairs({"wMenuJoypadPollCount","wMenuWrappingEnabled","wMenuWatchMovingOutOfBounds",
            "wPartyMenuAnimMonEnabled","hUILayoutFlags","wUpdateSpritesEnabled"})do data=data..hex(a[name],1)end
    return data
end
hook(manifest.receptionist.entry.address,manifest.receptionist.entry.bank,function()
    s.entry=s.entry+1;s.entry_frame=t.frame;s.union_before=hex(overlay,16);s.menu_before=menu_state()
    if r(a.wSpriteIndex)~=fixture.object_slot then failure("wrong physical receptionist object")end
end)
own_hook("after_query",function()
    s.query_restored=hex(overlay,16)==s.union_before
    if not s.query_restored then failure("availability query leaked the borrowed union")end
end)
own_hook("menu_input",function()s.menus=s.menus+1;clock=0 end)
own_hook("offer_entry",function()s.offer_preimage=hex(overlay,16)end)
own_hook("selection_check",function()
    if not case.selection_mutation then return end
    local slot=emu.getregister("A")
    if case.selection_mutation=="fainted"then
        w(a.wPartyMons+slot*44+1,0);w(a.wPartyMons+slot*44+2,0)
    elseif case.selection_mutation=="removed"then
        w(a.wPartyCount,slot);w(a.wPartySpecies+slot,255)
    elseif case.selection_mutation=="invalid-species"then
        w(a.wPartyMons+slot*44,31);w(a.wPartySpecies+slot,31)
    end
    -- The test introduces this drift; the cartridge may not make another write.
    s.expected_party_after_injection=party_storage()
end)
own_hook("offer_result",function()
    if s.offer_preimage and hex(overlay,16)~=s.offer_preimage then failure("offer leaked the borrowed union")end
    s.offer_result=emu.getregister("B")
end)
own_hook("menus_restored",function()
    s.menus_restored=menu_state()==s.menu_before
    if not s.menus_restored then failure("native menu state was not restored")end
end)
own_hook("notice",function()
    local pointer=emu.getregister("H")*256+emu.getregister("L")
    local name
    for key,value in pairs(manifest.receptionist.messages)do if pointer==value then name=key end end
    if not name then failure("unknown trade notice")end
    s.notices[#s.notices+1]={name=name};s.notice_active=true;clock=0
end)
own_hook("notice_done",function()
    s.notice_active=false
    local notice=s.notices[#s.notices]
    notice.lines={hex(a.wTileMap+281,18),hex(a.wTileMap+321,18)}
    local expected=input.notice_lines[notice.name]
    for line=1,2 do
        if notice.lines[line]:sub(1,#expected[line])~=expected[line]then failure("native trade notice text differs")end
    end
    if case.screenshot_notice then client.screenshot(input.output.."-"..case.id..".png")end
end)
for _,name in ipairs({"CableClubNPC","SaveGameData","SavePartyAndDexData","InternalClockTradeAnim","TryEvolvingMon"})do
    hook(rom[name].address,rom[name].bank,function()s.calls[name]=s.calls[name]+1 end)
end
hook(rom.PrintText.address,rom.PrintText.bank,function()
    if s.calls.CableClubNPC>0 then
        s.cable_text[#s.cable_text+1]=string.format("%02X:%04X",r(a.hLoadedROMBank),emu.getregister("H")*256+emu.getregister("L"))
    end
end)
local function lease()
    if input.baseline or not s or emu.getregister("PC")~=0x40 then return end
    local sp=emu.getregister("SP")
    local caller=r(sp+2)+256*r(sp+3)
    if r(a.hLoadedROMBank)~=manifest.receptionist.entry.bank then return end
    if caller==manifest.receptionist.query_return and r(overlay+5)==1 then
        s.query_frames=s.query_frames+1
        if case.reply=="missing" or s.replied then return end
        if s.query_frames<(case.reply_delay or 1)then return end
        s.replied=true
        if case.reply~="disabled"then w(overlay+10,1);w(overlay+11,case.mask)end
        for i,value in ipairs(case.token)do w(overlay+11+i,case.reply=="zero-token" and 0 or value)end
        local generation=r(overlay+6)
        if case.reply=="stale"then generation=(generation+1)%256 end
        if case.reply=="wrong-generation"then w(overlay+6,(generation+1)%256)end
        if case.reply=="wrong-magic"then w(overlay,0)end
        if case.reply=="wrong-version"then w(overlay+4,2)end
        if case.reply=="wrong-state"then w(overlay+5,4)end
        w(overlay+7,generation)
    elseif caller==manifest.receptionist.offer_return and r(overlay+5)==2 then
        s.offer_frames=s.offer_frames+1
        if not s.offer then
            s.offer={slot=r(overlay+9),generation=r(overlay+6),token=hex(overlay+12,4)}
            local expected={}
            for _,value in ipairs(case.token)do expected[#expected+1]=string.format("%02X",value)end
            if s.offer.token~=table.concat(expected)then failure("query token did not survive until offer")end
            if r(overlay+8)~=255 then failure("offer began with an invented result")end
        end
        if case.offer_reply=="missing" or s.offer_frames<(case.offer_delay or 1)then return end
        local repair=case.offer_repair_after and s.offer_frames>=case.offer_repair_after
        if s.offer_replied and not repair then return end
        s.offer_replied=true
        local kind=repair and "accepted" or case.offer_reply
        for i,value in ipairs(case.token)do w(overlay+11+i,value)end
        w(overlay+8,kind=="rejected" and 1 or 0)
        if kind=="wrong-magic"then w(overlay,0)end
        if kind=="wrong-version"then w(overlay+4,2)end
        if kind=="wrong-state"then w(overlay+5,4)end
        if kind=="wrong-generation"then w(overlay+6,(s.offer.generation+1)%256)end
        if kind=="wrong-slot"then w(overlay+9,(s.offer.slot+1)%6)end
        if kind=="invalid-result"then w(overlay+8,2)end
        if kind=="unset-result"then w(overlay+8,255)end
        if kind=="wrong-token"then w(overlay+12,bit.bxor(case.token[1],1))end
        w(overlay+7,kind=="stale" and (s.offer.generation+1)%256 or s.offer.generation)
    end
end
local ok,why=xpcall(function()
    assert(map_fixture.loads==1 and t.variant==fixture.variant,"fixture did not use the native map loader")
    assert(gameinfo.getromhash():lower()==input.final_sha1,"wrong receptionist artifact")
    assert(M.getCurrentMap()==fixture.map_id and r(a.wNumSprites)==fixture.object_count,"wrong map/object count")
    assert(hex(a.wCurMapHeader,10)==fixture.header_hex:upper(),"native map header differs")
    local blocks={}
    for row=0,fixture.height-1 do
        blocks[#blocks+1]=hex(a.wOverworldMap+(row+3)*(fixture.width+6)+3,fixture.width)
    end
    assert(table.concat(blocks)==fixture.blocks_hex:upper(),"native map blocks differ")
    local cart_before=hex(0,0x8000,"CartRAM")
    for _,current in ipairs(input.cases)do
        case=current
        for _=1,120 do if M.isPartyWriteSafe()then break end;t.step({})end
        assert(M.isPartyWriteSafe(),"not at a verified checkpoint before case")
        assert(r(t.x_addr)==fixture.x and r(t.y_addr)==fixture.y,"player moved out of receptionist reach")
        for i,raw in ipairs(case.party)do
            local blob=assert(M.hexToBytes(raw))
            for j=1,44 do w(a.wPartyMons+(i-1)*44+j-1,blob[j])end
            for j=1,11 do w(a.wPartyMonOT+(i-1)*11+j-1,blob[44+j]);w(a.wPartyMonNicks+(i-1)*11+j-1,blob[55+j])end
            w(a.wPartySpecies+i-1,blob[1])
        end
        w(a.wPartyCount,#case.party);w(a.wPartySpecies+#case.party,255)
        local before=party_storage()
        s={id=case.id,entry=0,menus=0,query_frames=0,offer_frames=0,notices={},calls={CableClubNPC=0,SaveGameData=0,SavePartyAndDexData=0,
            InternalClockTradeAnim=0,TryEvolvingMon=0},cable_text={},errors={}}
        clock=0
        local returned=false
        for frame=1,3000 do
            lease()
            local holding=case.hold_open and frame>=9 and frame<110
            if not holding then clock=clock+1 end
            local buttons={}
            if frame<=8 then buttons.Up=true
            elseif holding then buttons.A=true
            elseif s.entry==0 and s.calls.CableClubNPC==0 then buttons.A=frame%30<6
            elseif s.calls.CableClubNPC>0 then buttons.A=clock%30<6
            elseif s.notice_active then buttons.A=clock>=12 and clock%30<6
            elseif s.menus>0 then
                local row=s.menus==1 and (case.choice or 0) or (case.party_row or 0)
                if case.cancel_menu==s.menus then buttons.B=clock>=90 and clock<96
                else
                    for down=1,row do
                        local start=10+(down-1)*12
                        if clock>=start and clock<start+5 then buttons.Down=true end
                    end
                    buttons.A=clock>=90 and clock<96
                end
            end
            t.step(buttons)
            if s.menus>0 and not s.notice_active and clock==6 then
                local hidden=true
                for p=a.wShadowOAM,a.wShadowOAMEnd-1,4 do local y=r(p);if y>0 and y<160 then hidden=false end end
                if not hidden then failure("overworld sprites cover native menu")end
                s.sprites_hidden=hidden
                if input.screenshots and case.id==input.screenshots then
                    client.screenshot(input.output.."-menu"..s.menus..".png")
                end
            end
            if case.hold_open and frame==100 and(s.menus~=1 or s.offer)then failure("held opening A selected another choice")end
            if (s.entry>0 or s.calls.CableClubNPC>0)and M.isPartyWriteSafe()then returned=true;break end
        end
        assert(returned,case.id..": receptionist did not return to overworld")
        assert(#s.errors==0,case.id..": "..table.concat(s.errors,"; "))
        assert(s.entry==(input.baseline and 0 or 1),case.id..": wrong custom entry count")
        assert(s.calls.CableClubNPC==(case.cable and 1 or 0),case.id..": wrong Cable Club path")
        assert(s.menus==case.menus,case.id..": wrong number of native menus "..s.menus)
        if case.expected_slot~=nil then assert(s.offer and s.offer.slot==case.expected_slot,case.id..": wrong filtered party selection")
        else assert(not s.offer,case.id..": unexpected offer")end
        if case.expected_notice then
            assert(#s.notices==1 and s.notices[1].name==case.expected_notice,case.id..": wrong native notice")
        else assert(#s.notices==0,case.id..": unexpected native notice")end
        if case.expected_result~=nil then assert(s.offer_result==case.expected_result,case.id..": wrong offer disposition")end
        if case.minimum_offer_frames then assert(s.offer_frames>=case.minimum_offer_frames,case.id..": wait ended prematurely")end
        for name,count in pairs(s.calls)do if name~="CableClubNPC"then assert(count==0,case.id..": offer invoked "..name)end end
        assert(party_storage()==(s.expected_party_after_injection or before),case.id..": offer/cancel changed party")
        assert(r(a.wPartySpecies+#case.party)==255 and r(a.wNumSprites)==fixture.object_count,"party/object geometry changed")
        s.party_unchanged=true;s.returned_to_overworld=true
        observations[#observations+1]=s;t.log("[ok] "..fixture.map_name.."/"..case.id)
        s=nil
        for _=1,10 do t.step({})end
    end
    assert(hex(0,0x8000,"CartRAM")==cart_before,"receptionist offer/cancel wrote SRAM")
end,debug.traceback)
for _,id in ipairs(hooks)do event.unregisterbyid(id)end
local result={schema="gen1-receptionist-observation-v1",variant=t.variant,map_name=fixture.map_name,
    final_sha1=gameinfo.getromhash():lower(),native_map_loads=map_fixture.loads,object_count=fixture.object_count,
    direct_cpu_redirect=false,runtime_ready=false,cases=JSON.array(observations),passed=ok,
    failed_case=not ok and s or nil,error=not ok and tostring(why)or nil}
local f=assert(io.open(input.output,"w"));f:write(assert(JSON.encode(result)));f:close()
if not ok then client.screenshot(input.output.."-failure.png")end
t.check("native receptionist component",ok,tostring(why));t.finish()
