-- Run canonical cartridge routines and SLink from the SAME cloned emulator state.
-- This gate covers live party/current-box records, names, lists, dex and SRAM-bank
-- selection. Unused tail slots are not authoritative: RemovePokemon explicitly leaves
-- them unspecified (engine/pokemon/remove_mon.asm). Save/reset and Yellow PC policy
-- require separate gates; this oracle invokes the common storage primitives directly.
local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
local G = dofile(ROOT .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("test_gen1_storage_differential")
local M = t.M
local source = t.variant == "yellow" and "pokeyellow" or "pokered"
local target = t.variant == "blue" and "pokeblue" or source
local symbols = {}
local f = assert(io.open(ROOT .. "/.cache/pret/" .. source .. "/" .. target .. ".sym", "r"))
for line in f:lines() do
    local bank, addr, name = line:match("^(%x+):(%x+) (%S+)$")
    if bank then symbols[name] = {bank=tonumber(bank,16), addr=tonumber(addr,16)} end
end
f:close()
local function address(name) return assert(symbols[name], "missing canonical symbol " .. name).addr end
local function read(addr) return memory.read_u8(addr, "System Bus") end
local function write(addr,v) memory.write_u8(addr,v,"System Bus") end
local function bytes(addr,n)
    local out = {}
    for i=0,n-1 do out[i+1]=read(addr+i) end
    return out
end
local function put(addr,data,n)
    for i=1,n or #data do write(addr+i-1,data[i]) end
end
local function append(out,addr,n,label)
    for i=0,n-1 do out[#out+1]={label..":"..i,read(addr+i)} end
end
local function snapshot()
    local out={}
    local pc,bc=read(address("wPartyCount")),read(address("wBoxCount"))
    assert(pc<=6 and bc<=20,"oracle produced invalid storage counts")
    append(out,address("wPartyCount"),pc+2,"party species/count")
    append(out,address("wBoxCount"),bc+2,"box species/count")
    append(out,address("wPartyMons"),pc*44,"party struct")
    append(out,address("wPartyMonOT"),pc*11,"party OT")
    append(out,address("wPartyMonNicks"),pc*11,"party nickname")
    append(out,address("wBoxMons"),bc*33,"box struct")
    append(out,address("wBoxMonOT"),bc*11,"box OT")
    append(out,address("wBoxMonNicks"),bc*11,"box nickname")
    append(out,address("wPokedexOwned"),19,"dex owned")
    append(out,address("wPokedexSeen"),19,"dex seen")
    append(out,address("wCurrentBoxNum"),1,"current box")
    out[#out+1]={"SRAM bank",emu.getregister("SRAM BANK")}
    return out
end
local function compare(want,got)
    if #want~=#got then return "authoritative range length "..#want.." vs "..#got end
    for i=1,#want do
        if want[i][1]~=got[i][1] or want[i][2]~=got[i][2] then
            return want[i][1].." canonical="..want[i][2].." SLink="..got[i][2]
        end
    end
end
local specimen=bytes(M.PARTY_BASE_ADDR,44)
local ot=bytes(M.PARTY_OT_NAMES_ADDR,11)
local nick=bytes(M.PARTY_NICKS_ADDR,11)
local boot=memorysavestate.savecorestate()

local function seed(pc,bc,stale_level)
    memorysavestate.loadcorestate(boot)
    M._party_tail_cache=nil
    write(address("wPartyCount"),pc)
    write(address("wBoxCount"),bc)
    for _,spec in ipairs({{pc,44,"wPartyMons","wPartyMonOT","wPartyMonNicks","wPartySpecies",0},
                           {bc,33,"wBoxMons","wBoxMonOT","wBoxMonNicks","wBoxSpecies",100}}) do
        for slot=0,spec[1]-1 do
            local dst=address(spec[3])+slot*spec[2]
            put(dst,specimen,spec[2])
            -- Unique valid OTIDs; keep original species, experience, stats, HP and DVs.
            write(dst+12,0x12);write(dst+13,spec[7]+slot)
            if spec[2]==33 then write(dst+3,stale_level and 1 or specimen[34]) end
            put(address(spec[4])+slot*11,ot)
            put(address(spec[5])+slot*11,nick)
            -- Distinct valid text and status/PP-Up data make compaction comparisons
            -- sensitive to mixing parallel arrays and silently stripping packed bits.
            write(address(spec[4])+slot*11,0x80+slot%26)
            write(address(spec[5])+slot*11,0x99-slot%26)
            write(dst+4,({0,1,0x08,0x10,0x20,0x40})[slot%6+1])
            for move=0,3 do
                if read(dst+8+move)~=0 then
                    write(dst+29+move,read(dst+29+move)%64+(slot%4)*64)
                end
            end
            write(address(spec[6])+slot,specimen[1])
        end
        write(address(spec[6])+spec[1],0xFF)
    end
end

local function key(slot)
    local addr=address("wBoxMons")+slot*33
    return string.format("%02X%02X:%04X:%02X",read(addr+27),read(addr+28),
                         read(addr+12)*256+read(addr+13),read(addr))
end

local function canonical(deposit,slot)
    write(address("wWhichPokemon"),slot)
    write(address("wCurPartySpecies"),specimen[1])
    write(address("wMoveMonType"),deposit and 1 or 0)
    -- Test-only RAM trampoline, outside the compared party/box/save ranges. Interrupts
    -- are disabled; the cartridge's routines execute unchanged. Completion spins in
    -- place so a later overworld frame cannot alter the poststate before it is read.
    local code={0xF3}
    local function emit(...) for _,v in ipairs({...}) do code[#code+1]=v end end
    local switch=address("Bankswitch")
    for _,name in ipairs({"_MoveMon","_RemovePokemon"}) do
        if name=="_RemovePokemon" then
            -- These two symbols alias one scratch byte. Match BillsPC's ordering:
            -- publish RemoveMonFromBox only AFTER MoveMon has consumed MoveMonType.
            local flag=address("wRemoveMonFromBox")
            emit(0x3E,deposit and 0 or 1,0xEA,flag%256,math.floor(flag/256))
        end
        local sym=assert(symbols[name])
        emit(0x06,sym.bank,0x21,sym.addr%256,math.floor(sym.addr/256),
             0xCD,switch%256,math.floor(switch/256))
    end
    emit(0x3E,0xA5,0xEA,0xFF,0xC7,0x18,0xFE)
    write(0xC7FF,0);put(0xC800,code)
    emu.setregister("SP",0xDFFE)
    emu.setregister("PC",0xC800)
    for _=1,12 do
        t.step()
        if read(0xC7FF)==0xA5 then return end
    end
    error("canonical storage routine did not return")
end

local cases,failed=0,0
local function run_case(deposit,pc,bc,slot,stale)
    seed(pc,bc,stale)
    local selected=not deposit and key(slot) or nil
    local clone=memorysavestate.savecorestate()
    canonical(deposit,slot)
    local expected=snapshot()
    memorysavestate.loadcorestate(clone)
    memorysavestate.removestate(clone)
    local ok,err
    if deposit then ok,err=M.depositPartyMon(slot) else ok,err=M.retrieveBoxMon(selected) end
    local mismatch=compare(expected,snapshot())
    cases=cases+1
    if not ok or mismatch then
        failed=failed+1
        if failed<=12 then
            t.check(string.format("%s p=%d b=%d slot=%d stale=%s",deposit and "deposit" or "withdraw",
                                  pc,bc,slot,tostring(stale)),false,mismatch or err)
        end
    end
end

local ok,err=pcall(function()
    -- Existing bootstrap fixtures may contain a level-5 starter with zero experience.
    -- Normalize ONLY the cloned specimen through the actual cartridge's withdrawal;
    -- the committed fixture is never changed and no Python/Lua formula supplies the
    -- expected level/stats. 1000 XP is legal for every canonical growth curve.
    seed(0,1)
    local exp=address("wBoxMons")+14
    write(exp,0);write(exp+1,3);write(exp+2,0xE8)
    canonical(false,0)
    specimen=bytes(address("wPartyMons"),44)
    if specimen[2]*256+specimen[3] > specimen[35]*256+specimen[36] then
        specimen[2],specimen[3]=specimen[35],specimen[36]
    end
    t.check("canonical specimen has nonzero XP and legal derived level",
            specimen[16]==3 and specimen[17]==0xE8 and specimen[34]>=1 and specimen[34]<=100)
    local before=snapshot()
    local same=snapshot()
    t.check("comparator accepts the same authoritative state",compare(before,same)==nil)
    same[1][2]=(same[1][2]+1)%256
    t.check("comparator detects a one-byte mutation",compare(before,same)~=nil)
    for pc=2,6 do for bc=0,19 do for slot=0,pc-1 do run_case(true,pc,bc,slot) end end end
    t.check("400 canonical deposit/party-compaction cases",failed==0,"failures="..failed)
    for pc=0,5 do for bc=1,20 do for slot=0,bc-1 do run_case(false,pc,bc,slot) end end end
    t.check("1260 canonical withdraw/box-compaction/append cases",failed==0,"failures="..failed)
    run_case(false,1,1,0,true)
    t.check("withdraw derives level from experience despite stale BoxLevel",failed==0)
end)
memorysavestate.loadcorestate(boot)
memorysavestate.removestate(boot)
t.check("differential harness completed",ok,tostring(err))
t.check("all 1661 expected transformations executed",cases==1661,"cases="..cases)
t.finish("storage differential")
