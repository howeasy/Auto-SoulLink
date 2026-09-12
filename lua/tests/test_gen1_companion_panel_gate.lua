-- Actual ABI-3 panel protocol on combined R/B artifacts; no CPU redirection.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
package.path=ROOT.."/lua/?.lua;"..package.path
local JSON=require("json_codec")
local spec_file=assert(io.open(assert(os.getenv("SLINK_COMPANION_MANIFEST")),"r"))
local input=assert(JSON.decode(spec_file:read("*a")));spec_file:close()
local fixture=input.panel_fixture
local map_fixture=require("tests.gen1_map_fixture").start(fixture,"abi3-panel-map")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_companion_panel_gate")
map_fixture:close()
local mem=t.M
local f=assert(io.open(assert(os.getenv("SLINK_COMPANION_MANIFEST")),"r"))
local manifest=assert(JSON.decode(f:read("*a")));f:close()
local panel,ram=manifest.companion.panel,manifest.ram
local function r(p)return memory.read_u8(p,"System Bus")end
local function w(p,v)memory.write_u8(p,v,"System Bus")end
local function hex(p,n,d)local v={};for i=0,n-1 do v[#v+1]=memory.read_u8(p+i,d or "System Bus")end;return mem.bytesToHex(v)end
local function field(n)return panel.mailbox+panel.controls[n]end
local active,calls=nil,0
local hooks={}
hooks[#hooks+1]=event.on_bus_exec(function()
    if r(ram.hLoadedROMBank)==manifest.entry.bank then calls=calls+1 end
end,manifest.entry.address,"abi3-no-trade","System Bus")
hooks[#hooks+1]=event.on_bus_exec(function()
    if active and r(field("state"))==2 and r(field("generation"))%2==0 and r(panel.bg_enabled)~=0 then
        local gen=r(field("generation"));active.portions[gen]=active.portions[gen]or {}
        active.portions[gen][r(panel.bg_portion)]=true
    end
end,panel.bg_transfer,"abi3-portions","System Bus")
hooks[#hooks+1]=event.on_bus_exec(function()
    if active and r(ram.hLoadedROMBank)==panel.bank then
        local gen=r(field("generation"));local seen=active.portions[gen]or {}
        assert(r(0xFF47)==0 and r(field("transfers"))==7 and gen%2==0 and gen~=r(field("ack"))
            and seen[0]and seen[1]and seen[2],"reveal preceded three stable BG transfers")
        active.reveals[#active.reveals+1]={generation=gen,page=r(field("page")),frame=t.frame}
    end
end,panel.reveal,"abi3-reveal","System Bus")
local results={}
local modes={"missing","wrap","B","START","held-A","odd","stale-even","changed-transfer","no-bg","lease-expiry","visible-generation-change","canary"}
local ok,why=xpcall(function()
    assert(panel.protocol=="slink-gen1-panel-generation-v1"and gameinfo.getromhash():lower()==manifest.final_sha1,"wrong ABI-3 artifact")
    assert(mem.panelSupported()and mem.panelAbi()==3 and r(mem.PANEL_CAPS)==6,"ABI fields differ")
    if fixture then
        assert(map_fixture.loads==1 and mem.getCurrentMap()==fixture.map_id,"native panel fixture map differs")
        assert((r(fixture.pokedex_address)&fixture.pokedex_mask~=0)==fixture.pokedex,"Pokedex fixture differs")
    end
    for _,mode in ipairs(modes)do
        for _=1,120 do if mem.isPartyWriteSafe()then break end;t.step({})end
        assert(mem.isPartyWriteSafe(),"initial checkpoint absent")
        local before={party=hex(manifest.readback.party.address,404),save=hex(0,0x8000,"CartRAM"),map=mem.getCurrentMap()}
        t.hold("Start",8);for _=1,30 do t.step({})end
        local last=r(ram.wMaxMenuItem)-1
        if fixture then assert(last==(fixture.pokedex and 7 or 6),"wrong pre/post Pokedex menu geometry")end
        for _=1,10 do
            if r(ram.wCurrentMenuItem)==last then break end
            t.hold("Down",6);for _=1,8 do t.step({})end
        end
        assert(r(ram.wCurrentMenuItem)==last,"SLINK row not reached")
        active={mode=mode,portions={},reveals={}}
        local rows={};for i=1,36 do rows[i]="RC PAGE "..(i<=18 and "ONE"or "TWO")end
        local first,closed,age,previous,mutated=nil,false,0,nil,false
        for frame=1,1400 do
            local state=r(field("state"))
            if state~=0 then first=first or t.frame end
            if state==1 and mode~="missing"then
                if mode=="odd"or mode=="stale-even"then
                    w(field("generation"),mode=="odd"and 1 or r(field("ack")));w(field("pages"),2);w(field("state"),2)
                else assert(mem.panelStage(rows),"valid staging refused")end
            end
            state=r(field("state"))
            if mode=="no-bg"and state==2 then w(panel.bg_enabled,0)end
            if mode=="changed-transfer"and state==2 and r(field("transfers"))~=0 and not mutated then
                w(field("generation"),(r(field("generation"))+2)%256);mutated=true
            end
            if state==3 then
                local gen=r(field("generation"));if gen~=previous then age=0;previous=gen end;age=age+1
                assert(r(field("ack"))==gen and gen%2==0,"display lacks exact ACK")
                local base=r(panel.bg_destination)+256*r(panel.bg_destination+1)
                for row=0,17 do assert(hex(base+row*32,20)==hex(ram.wTileMap+row*20,20),"revealed VRAM is incomplete")end
                if mode=="visible-generation-change"and age==30 then w(field("generation"),(gen+2)%256);mutated=true
                elseif mode=="canary"and age==30 then w(field("canary")+7,0);mutated=true end
            end
            if mode~="missing"and mode~="odd"and mode~="stale-even"and mode~="no-bg"and mode~="lease-expiry"then mem.panelHeartbeat(true)end
            local buttons={}
            if frame<=6 or(mode=="held-A"and frame<=150)then buttons.A=true
            elseif state==3 then
                if mode=="wrap"and age>=40 and age<46 then buttons[#active.reveals<3 and "A"or "B"]=true
                elseif mode=="B"and age>=40 and age<46 then buttons.B=true
                elseif mode=="START"and age>=40 and age<46 then buttons.Start=true
                elseif mode=="held-A"then
                    if #active.reveals==1 and frame>=170 and frame<176 then buttons.A=true
                    elseif #active.reveals==2 and age>=40 and age<46 then buttons.B=true end
                end
            end
            if mode=="held-A"and frame<=150 then assert(#active.reveals<=1,"held opening A advanced")end
            t.step(buttons)
            if first and r(field("state"))==0 then closed=true;break end
        end
        assert(closed,mode..": did not close")
        local blank=mode=="missing"or mode=="odd"or mode=="stale-even"or mode=="changed-transfer"or mode=="no-bg"
        assert(#active.reveals==(blank and 0 or mode=="wrap"and 3 or mode=="held-A"and 2 or 1),mode..": unexpected reveal count")
        if blank or mode=="lease-expiry"then assert(t.frame-first<=181,mode..": exceeded180-frame closure")end
        if mode=="wrap"then assert(active.reveals[1].page==0 and active.reveals[2].page==1 and active.reveals[3].page==0,"A did not wrap")end
        for frame=1,240 do t.step({B=frame%30<8});if mem.isPartyWriteSafe()then break end end
        assert(mem.isPartyWriteSafe()and mem.getCurrentMap()==before.map,mode..": map control did not return")
        assert(hex(manifest.readback.party.address,404)==before.party and hex(0,0x8000,"CartRAM")==before.save,mode..": party/save changed")
        assert(calls==0 and r(mem.PANEL_CAPS)==6,"trade/SFX leaked from panel")
        if mode=="canary"then assert(not mem.panelSupported(),"canary fault ignored")end
        results[#results+1]={mode=mode,closed=true,reveals=JSON.array(active.reveals),party_unchanged=true,save_unchanged=true}
        active=nil
    end
end,debug.traceback)
for _,id in ipairs(hooks)do event.unregisterbyid(id)end
local out=assert(io.open(assert(os.getenv("SLINK_COMPANION_PANEL_RESULT")),"w"))
out:write(assert(JSON.encode({passed=ok,error=not ok and tostring(why)or nil,variant=t.variant,final_sha1=manifest.final_sha1,cases=JSON.array(results),native_trade_calls=calls})));out:close()
t.check("combined ABI-3 panel",ok,tostring(why));t.finish()
