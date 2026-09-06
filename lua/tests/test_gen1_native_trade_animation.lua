-- Execute the original animation from an isolated cloned core. This proves the
-- scene itself, not receptionist reachability, party exchange, evolution or save.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_native_trade_animation")
client.frameskip(0)
local M=t.M
package.path=ROOT.."/lua/?.lua;"..package.path
local JSON=require("json_codec")
local source=t.variant=="yellow" and "pokeyellow" or "pokered"
local target=t.variant=="blue" and "pokeblue" or source
local trace,expected,hooks=JSON.array(),{},{}
local frame,pending,phase=0,nil,nil
local samples=JSON.array()
local function step()
    frame=frame+1
    t.step({A=frame%20<8})
    local sample_delay=phase and (phase.name=="Trade_ShowEnemyMon" and 200 or 120)
    if phase and frame-phase.frame==sample_delay and #samples<4 then
        local path=ROOT.."/.cache/native-trade-"..t.variant.."-"..phase.name..".png"
        client.screenshot(path)
        local vram={}
        for address=0x8000,0x9FFF do vram[#vram+1]=string.format("%02X",memory.read_u8(address,"System Bus")) end
        samples[#samples+1]={phase=phase.name,frame=frame,vram_hex=table.concat(vram),screenshot=path}
    end
end
-- wTempPic occupies only the first784 bytes of the1300-byte wOverworldMap
-- union. CB00/CBF0 are in the unused tail during this isolated movie. The
-- trampoline checks its own bytes each frame and the original core is restored.
local oracle=dofile(ROOT.."/lua/tests/gb_routine_oracle.lua").new({
    symbols_path=ROOT.."/.cache/pret/"..source.."/"..target..".sym",step=step,
    scratch=0xCB00,marker=0xCBF0,stack=0xDFFE,bankswitch="Bankswitch",
    enable_interrupts=true,timeout_frames=9000})
local a,r,w=oracle.address,oracle.read,oracle.write
local function hook(name,callback)
    local symbol=oracle.symbol(name)
    hooks[#hooks+1]=event.on_bus_exec(function()
        if symbol.bank==0 or r(a("hLoadedROMBank"))==symbol.bank then callback() end
    end,symbol.address,"native-trade-"..name,"System Bus")
end
local boot=memorysavestate.savecorestate()
local ok,reason=pcall(function()
    local in_sequence=false
    for line in io.lines(ROOT.."/.cache/pret/"..source.."/engine/movie/trade.asm") do
        if line=="InternalClockTradeFuncSequence:" then in_sequence=true
        elseif in_sequence and line:match("^%s*db %-1") then break
        elseif in_sequence then
            local name=line:match("^%s*tradefunc ([%w_]+)")
            if name then expected[#expected+1]=name end
        end
    end
    assert(#expected==16,"pinned original sequence differs")
    local sequence=oracle.symbol("InternalClockTradeFuncSequence")
    local distinct={}
    for _,name in ipairs(expected)do distinct[name]=true end
    for name in pairs(distinct)do
        hook(name,function()
            if pending==name then
                trace[#trace+1]={name=name,frame=frame};pending=nil
                if name=="Trade_ShowPlayerMon" or name=="Trade_AnimLeftToRight" or name=="Trade_ShowEnemyMon" then
                    phase={name=name,frame=frame}
                end
            end
        end)
    end
    local loops=0
    hook("TradeAnimCommon.loop",function()
        local sp=emu.getregister("SP")
        local pointer=r(sp)+256*r(sp+1)
        local index=pointer-sequence.address+1
        assert(index==loops+1 and index<=#expected+1,"native sequence pointer skipped/replayed a phase")
        assert(pending==nil,"native animation omitted a function entry")
        loops=loops+1
        pending=expected[index]
    end)
    local party_before={}
    for address=M.PARTY_COUNT_ADDR,M.PARTY_NICKS_ADDR+66-1 do party_before[address]=r(address) end
    local player_name={}
    for i=0,10 do player_name[i]=r(M.PLAYER_NAME_ADDR+i) end
    w(a("wTradedPlayerMonSpecies"),r(M.PARTY_BASE_ADDR))
    w(a("wTradedEnemyMonSpecies"),0x99) -- explicit incoming Bulbasaur animation fixture
    oracle.copy(a("wTradedPlayerMonOT"),M.PARTY_OT_NAMES_ADDR,11)
    oracle.copy(a("wTradedPlayerMonOTID"),M.PARTY_BASE_ADDR+12,2)
    local peer={0x8F,0x84,0x84,0x91,0x50,0x50,0x50,0x50,0x50,0x50,0x50}
    for i,byte in ipairs(peer)do
        w(a("wLinkEnemyTrainerName")+i-1,byte);w(a("wTradedEnemyMonOT")+i-1,byte)
    end
    w(a("wTradedEnemyMonOTID"),0x12);w(a("wTradedEnemyMonOTID")+1,0x34)
    local options=r(a("wOptions"))
    -- Native cable-club entry loads the font before the animation's HP/status
    -- tiles. An overworld-only caller otherwise displays text using map tiles.
    oracle.invoke("LoadFontTilePatterns")
    local font=oracle.symbol("FontGraphics")
    local font_size=a("FontGraphicsEnd")-font.address
    local font_rom=font.bank*0x4000+font.address%0x4000
    for offset=0,font_size-1 do
        local byte=memory.read_u8(font_rom+offset,"ROM")
        assert(r(a("vFont")+offset*2)==byte and r(a("vFont")+offset*2+1)==byte,"native font was not loaded")
    end
    t.check("canonical font pixels are loaded for trade text",font_size>0)
    oracle.invoke("LoadHpBarAndStatusTilePatterns")
    local started=frame
    oracle.invoke("InternalClockTradeAnim")
    t.check("every original trade function executes in order",#trace==#expected and loops==#expected+1)
    for i,name in ipairs(expected)do assert(trace[i].name==name,"native scene order differs") end
    t.check("original animation advances real frames",frame-started>500,tostring(frame-started))
    t.check("outgoing, cable and incoming visual samples captured",#samples==3,tostring(#samples))
    if #samples==3 then
        t.check("visual phases change VRAM",samples[1].vram_hex~=samples[2].vram_hex and samples[2].vram_hex~=samples[3].vram_hex)
    end
    t.check("original scene restores options",r(a("wOptions"))==options)
    for address,byte in pairs(party_before)do assert(r(address)==byte,"animation changed party memory") end
    for offset,byte in pairs(player_name)do assert(r(M.PLAYER_NAME_ADDR+offset)==byte,"animation changed save name") end
    local output=assert(io.open(ROOT.."/.cache/gen1-native-trade-animation-"..t.variant..".json","w"))
    output:write(assert(JSON.encode({variant=t.variant,rom_sha1=gameinfo.getromhash():lower(),
        native_entry="InternalClockTradeAnim",frames=frame-started,expected=JSON.array(expected),
        trace=trace,samples=samples,font_bytes_verified=font_size*2,party_unchanged=true})));output:close()
end)
for _,id in ipairs(hooks)do event.unregisterbyid(id)end
memorysavestate.loadcorestate(boot);memorysavestate.removestate(boot)
t.check("original trade animation gate completed",ok,tostring(reason))
t.finish()
