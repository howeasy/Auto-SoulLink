-- Canonical SRAM initialization, checksum/load routines and real core reset proof.
-- This invokes storage primitives from cloned states. It does not prove PC menus or
-- the production write-safe predicate. The isolated runner owns all save mutations.
local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
local G = dofile(ROOT .. "/lua/tests/gen1_gatelib.lua")
local Shared = dofile(ROOT .. "/lua/tests/gatelib.lua")
local t = G.start("test_gen1_storage_persistence")
local M = t.M
local source = t.variant == "yellow" and "pokeyellow" or "pokered"
local target = t.variant == "blue" and "pokeblue" or source
local symbols = {}
local f = assert(io.open(ROOT .. "/.cache/pret/" .. source .. "/" .. target .. ".sym", "r"))
for line in f:lines() do
    local bank, addr, name = line:match("^(%x+):(%x+) (%S+)$")
    if bank then symbols[name] = {bank=tonumber(bank,16),addr=tonumber(addr,16)} end
end
f:close()
local function sym(name) return assert(symbols[name],"missing canonical symbol "..name) end
local function addr(name) return sym(name).addr end
local function read(a,domain) return memory.read_u8(a,domain or "System Bus") end
local function write(a,v,domain) memory.write_u8(a,v,domain or "System Bus") end
local function bytes(a,n,domain)
    local out={}
    for i=0,n-1 do out[i+1]=read(a+i,domain) end
    return out
end
local function put(a,data,domain)
    for i,v in ipairs(data) do write(a+i-1,v,domain) end
end
local function compare(want,got)
    if #want~=#got then return "length "..#want.." versus "..#got end
    for i=1,#want do
        if want[i]~=got[i] then
            return string.format("offset $%04X canonical=%d actual=%d",i-1,want[i],got[i])
        end
    end
end
local function sram_offset(name)
    local s=sym(name)
    return s.bank*0x2000+s.addr-0xA000
end
local function invoke(names)
    local code={0xF3}
    local function emit(...) for _,v in ipairs({...}) do code[#code+1]=v end end
    local switch=addr("Bankswitch")
    for _,name in ipairs(names) do
        local s=type(name)=="table" and name or sym(name)
        emit(0x06,s.bank,0x21,s.addr%256,math.floor(s.addr/256),
             0xCD,switch%256,math.floor(switch/256))
    end
    emit(0x3E,0xA5,0xEA,0xFF,0xC7,0x18,0xFE)
    write(0xC7FF,0);put(0xC800,code)
    emu.setregister("SP",0xDFFE);emu.setregister("PC",0xC800)
    for _=1,40 do t.step();if read(0xC7FF)==0xA5 then return end end
    error("canonical storage/save routine did not return")
end
local function cart() return bytes(0,0x8000,"CartRAM") end
local function saved_party() return bytes(sram_offset("sPartyData"),addr("wPartyDataEnd")-addr("wPartyDataStart"),"CartRAM") end
local function live_party() return bytes(addr("wPartyDataStart"),addr("wPartyDataEnd")-addr("wPartyDataStart")) end
local boot=memorysavestate.savecorestate()
local saved_flag=sram_offset("sMainData")+addr("wCurrentBoxNum")-addr("wMainDataStart")
local memoff=sram_offset("sBox12")
local boxlen=addr("wBoxDataEnd")-addr("wBoxDataStart")

-- Replay the exact 8 instruction bytes controlling ChangeBox's first-time wipe.
-- The remainder of ChangeBox opens menus and is deliberately outside this gate.
local function change_box_init_branch()
    local entry,empty=sym("ChangeBox"),sym("EmptyAllSRAMBoxes")
    local expected={0x21,addr("wCurrentBoxNum")%256,math.floor(addr("wCurrentBoxNum")/256),
                    0xCB,0x7E,0xCC,empty.addr%256,math.floor(empty.addr/256)}
    local base=entry.bank*0x4000+entry.addr%0x4000
    local found=0
    for off=0,80 do
        local candidate=bytes(base+off,#expected,"ROM")
        if not compare(expected,candidate) then found=found+1;put(0xC900,candidate) end
    end
    assert(found==1,"ChangeBox initialization branch expected-byte anchor is ambiguous or absent")
    write(0xC900+#expected,0xC9)
    invoke({{bank=entry.bank,addr=0xC900}})
end

local ok,err=pcall(function()
    local all_init_ok=true
    for index=0,11 do
        memorysavestate.loadcorestate(boot)
        write(addr("wCurrentBoxNum"),index)
        invoke({"SaveGameData"}) -- establish a real canonical main save/checksum
        -- Arbitrary unused tails must be retained, just as EmptySRAMBox does.
        for off=0x4000,0x7FFF do write(off,(off*13+index)%256,"CartRAM") end
        local seed=memorysavestate.savecorestate()
        invoke({"EmptyAllSRAMBoxes"})
        write(addr("wCurrentBoxNum"),index+0x80)
        invoke({"SaveMainData"})
        local expected=cart()
        memorysavestate.loadcorestate(seed);memorysavestate.removestate(seed)
        local initial_bank=emu.getregister("SRAM BANK")
        local initialized,reason=M.protectSramBoxes()
        local mismatch=compare(expected,cart())
        local pass=initialized and reason==nil and mismatch==nil
            and read(addr("wCurrentBoxNum"))==index+0x80
            and read(saved_flag,"CartRAM")==index+0x80
            and emu.getregister("SRAM BANK")==initial_bank
        all_init_ok=t.check("canonical SRAM initialization/current-box "..index,pass,mismatch or reason) and all_init_ok
        local before=cart()
        local again,why=M.protectSramBoxes()
        t.check("initialization is idempotent/current-box "..index,
                not again and why==nil and compare(before,cart())==nil)
    end
    t.check("all 12 current-box initialization transformations match the cartridge",all_init_ok)

    memorysavestate.loadcorestate(boot)
    write(addr("wCurrentBoxNum"),2);invoke({"SaveGameData"})
    write(addr("wCurrentBoxNum"),5)
    local initialized,reason=M.protectSramBoxes()
    t.check("persisted and live current-box indices remain independent",
            initialized and not reason and read(saved_flag,"CartRAM")==0x82
            and read(addr("wCurrentBoxNum"))==0x85)

    memorysavestate.loadcorestate(boot)
    -- Start from saved A/B/C and an empty box. A normal deposit followed by C's
    -- memorial must persist BOTH the current box and the resulting party: saving
    -- only the party would permanently lose A on reset.
    local specimen=bytes(addr("wPartyMons"),44)
    local ot=bytes(addr("wPartyMonOT"),11)
    local nick=bytes(addr("wPartyMonNicks"),11)
    for slot=0,2 do
        put(addr("wPartyMons")+slot*44,specimen)
        write(addr("wPartyMons")+slot*44+12,0x42)
        write(addr("wPartyMons")+slot*44+13,slot)
        put(addr("wPartyMonOT")+slot*11,ot)
        put(addr("wPartyMonNicks")+slot*11,nick)
        write(addr("wPartySpecies")+slot,specimen[1])
    end
    write(addr("wPartyCount"),3);write(addr("wPartySpecies")+3,0xFF)
    write(addr("wBoxCount"),0);write(addr("wBoxSpecies"),0xFF)
    write(addr("wCurrentBoxNum"),0)
    -- C is dead; A and B stay live.
    write(addr("wPartyMons")+88+1,0);write(addr("wPartyMons")+88+2,0)
    invoke({"SaveGameData"})
    local consistent=memorysavestate.savecorestate()
    for id_byte=0,1 do
        memorysavestate.loadcorestate(consistent)
        -- A valid existing save belonging to another player is not backing for
        -- this party. No checksum is corrupted by changing only the live ID.
        local id=addr("wPlayerID")+id_byte
        write(id,(read(id)+1)%256)
        local prior_wram,prior_sram=bytes(0xC000,0x2000),cart()
        M._memorial_reservations=nil
        local accepted,rejection=M.depositMemorialMon(2)
        t.check("saved/live player-ID byte "..id_byte.." mismatch refuses before mutation",
                not accepted and tostring(rejection):find("identity",1,true)~=nil
                and compare(prior_wram,bytes(0xC000,0x2000))==nil
                and compare(prior_sram,cart())==nil,tostring(rejection))
    end
    memorysavestate.loadcorestate(consistent);memorysavestate.removestate(consistent)
    local deposited,deposit_error=M.depositPartyMon(0)
    assert(deposited,"ordinary deposit refused: "..tostring(deposit_error))
    local expected_box=bytes(addr("wBoxDataStart"),boxlen)
    t.check("ordinary deposit leaves A live in current box before memorial",
            M.getBoxCount()==1 and M.getPartyCount()==2
            and read(addr("wBoxMons")+12)==0x42 and read(addr("wBoxMons")+13)==0)
    M._memorial_reservations=nil
    local buried,why=M.depositMemorialMon(1)
    assert(buried,"memorial deposit refused: "..tostring(why))
    local grave=bytes(memoff,boxlen,"CartRAM")
    local expected_party=live_party()
    t.check("memorial written with one surviving party mon",read(memoff,"CartRAM")==1 and M.getPartyCount()==1)
    -- Source-derived expected persisted range: run the canonical save on a clone.
    local post=memorysavestate.savecorestate()
    invoke({"SaveCurrentBoxData","SavePartyAndDexData"})
    local expected_save=cart()
    memorysavestate.loadcorestate(post);memorysavestate.removestate(post)
    t.check("memorial poststate matches canonical current-box then party/dex save",
            compare(expected_save,cart())==nil,compare(expected_save,cart()))
    t.check("saved party matches immediate live party",compare(expected_party,saved_party())==nil,
            compare(expected_party,saved_party()))
    t.check("saved current box retains A after unsaved ordinary deposit then memorial",
            compare(expected_box,bytes(sram_offset("sCurBoxData"),boxlen,"CartRAM"))==nil,
            compare(expected_box,bytes(sram_offset("sCurBoxData"),boxlen,"CartRAM")))

    -- Force authoritative WRAM data to be absent before invoking cartridge loaders.
    for a=addr("wPartyDataStart"),addr("wPartyDataEnd")-1 do write(a,0) end
    for a=addr("wBoxDataStart"),addr("wBoxDataEnd")-1 do write(a,0) end
    write(addr("wCurrentBoxNum"),0)
    invoke({"LoadMainData","LoadCurrentBoxData","LoadPartyAndDexData"})
    t.check("canonical loader accepts persisted initialization flag",read(addr("wCurrentBoxNum"))==0x80)
    t.check("canonical loader retains grave bytes",compare(grave,bytes(memoff,boxlen,"CartRAM"))==nil)
    t.check("canonical loader does not resurrect the memorial party mon",
            compare(expected_party,live_party())==nil,compare(expected_party,live_party()))
    t.check("canonical loader does not lose the previously boxed mon",
            compare(expected_box,bytes(addr("wBoxDataStart"),boxlen))==nil,
            compare(expected_box,bytes(addr("wBoxDataStart"),boxlen)))
    change_box_init_branch()
    t.check("cartridge ChangeBox first-time branch preserves grave after reload",
            compare(grave,bytes(memoff,boxlen,"CartRAM"))==nil)
    local protected=memorysavestate.savecorestate()
    write(addr("wCurrentBoxNum"),0)
    change_box_init_branch()
    t.check("negative control: cleared initialized flag really erases grave",read(memoff,"CartRAM")==0)
    memorysavestate.loadcorestate(protected);memorysavestate.removestate(protected)

    -- The documented BizHawk API reboots the core. No savestate reload substitutes
    -- for this check; CONTINUE must read the just-written battery SRAM.
    memorysavestate.removestate(boot);boot=nil
    assert(client.reboot_core,"BizHawk reboot_core dependency missing")
    client.reboot_core()
    M._party_tail_cache=nil;M._memorial_reservations=nil
    local booted=Shared.prove_booted(M,"gen1_rby",t.step,t.hold)
    t.check("real core reset reaches playable CONTINUE",booted)
    t.check("real reset preserves initialized bit",read(addr("wCurrentBoxNum"))==0x80)
    t.check("real reset preserves grave",compare(grave,bytes(memoff,boxlen,"CartRAM"))==nil)
    t.check("real reset does not resurrect the memorial party mon",
            compare(expected_party,live_party())==nil,compare(expected_party,live_party()))
    t.check("real reset retains the previously boxed mon with complete box fidelity",
            compare(expected_box,bytes(addr("wBoxDataStart"),boxlen))==nil,
            compare(expected_box,bytes(addr("wBoxDataStart"),boxlen)))
end)
if boot then memorysavestate.loadcorestate(boot);memorysavestate.removestate(boot) end
t.check("persistence harness completed",ok,tostring(err))
t.finish("canonical storage persistence")
