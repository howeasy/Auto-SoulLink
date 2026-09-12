-- Storage boundaries on a live cartridge: every refusal the production writers make at the
-- edges of the party/box geometry leaves WRAM, HRAM and the whole 32 KB of SRAM byte for
-- byte as they were, and the compensation the server issues to a PC initiator (the opposite
-- canonical operation) reproduces the cartridge's own MoveMon result exactly.
--
-- Clauses covered, by manifest row:
--   memory.<title>.differential "boundary failures": depositPartyMon refuses the last party
--     member, a full current box and an invalid slot; retrieveBoxMon refuses a full party.
--   memory.<title>.storage "invalid current box refusal": wCurrentBoxNum >= 12 (the changed-
--     boxes bit masked off) refuses both writers; "whole empty reserved box": a live record
--     hidden past the memorial box count refuses the memorial and a dead one is left in
--     place, untouched, by a successful memorial; "canonical initiator deposit undo": a
--     canonical deposit undone through retrieveBoxMon, and a canonical withdrawal undone
--     through depositPartyMon, equal the cartridge's own inverse MoveMon on a cloned state.
-- The seeding and the canonical trampoline are the ones test_gen1_storage_differential.lua
-- proved; nothing here supplies an expected byte from a formula.
local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
local G = dofile(ROOT .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("test_gen1_storage_boundaries")
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
local function sym(name) return assert(symbols[name], "missing canonical symbol " .. name) end
local function address(name) return sym(name).addr end
local function sram_offset(name) local s=sym(name) return s.bank*0x2000+s.addr-0xA000 end
local function read(addr,domain) return memory.read_u8(addr, domain or "System Bus") end
local function write(addr,v,domain) memory.write_u8(addr,v,domain or "System Bus") end
local function bytes(addr,n,domain)
    local out = {}
    for i=0,n-1 do out[i+1]=read(addr+i,domain) end
    return out
end
local function put(addr,data,n,domain)
    for i=1,n or #data do write(addr+i-1,data[i],domain) end
end
local function compare(want,got,label)
    if #want~=#got then return (label or "").." length "..#want.." vs "..#got end
    for i=1,#want do
        if want[i]~=got[i] then
            return string.format("%s offset $%04X before=%d after=%d",label or "",i-1,want[i],got[i])
        end
    end
end

-- ── the two oracles ──────────────────────────────────────────────────────────────────────
-- Everything a refusal may not touch: work RAM, high RAM, all four SRAM banks, the bank
-- register. Compared whole, so a stray write anywhere is a failure, not just one inside
-- the ranges the writer is supposed to use.
local function image()
    return {wram=bytes(0xC000,0x2000), hram=bytes(0xFF80,0x7F), sram=bytes(0,0x8000,"CartRAM"),
            bank=emu.getregister("SRAM BANK")}
end
local function unchanged(before,after)
    return compare(before.wram,after.wram,"WRAM") or compare(before.hram,after.hram,"HRAM")
        or compare(before.sram,after.sram,"SRAM")
        or (before.bank~=after.bank and "SRAM bank "..before.bank.." -> "..after.bank or nil)
end
-- The authoritative storage ranges the differential gate compares canonical against SLink.
local function authoritative()
    local out={}
    local function append(addr,n,label) for i=0,n-1 do out[#out+1]={label..":"..i,read(addr+i)} end end
    local pc,bc=read(address("wPartyCount")),read(address("wBoxCount"))
    assert(pc<=6 and bc<=20,"oracle produced invalid storage counts")
    append(address("wPartyCount"),pc+2,"party species/count")
    append(address("wBoxCount"),bc+2,"box species/count")
    append(address("wPartyMons"),pc*44,"party struct")
    append(address("wPartyMonOT"),pc*11,"party OT")
    append(address("wPartyMonNicks"),pc*11,"party nickname")
    append(address("wBoxMons"),bc*33,"box struct")
    append(address("wBoxMonOT"),bc*11,"box OT")
    append(address("wBoxMonNicks"),bc*11,"box nickname")
    append(address("wPokedexOwned"),19,"dex owned")
    append(address("wPokedexSeen"),19,"dex seen")
    append(address("wCurrentBoxNum"),1,"current box")
    out[#out+1]={"SRAM bank",emu.getregister("SRAM BANK")}
    return out
end
local function same_records(want,got)
    if #want~=#got then return "authoritative range length "..#want.." vs "..#got end
    for i=1,#want do
        if want[i][1]~=got[i][1] or want[i][2]~=got[i][2] then
            return want[i][1].." canonical="..want[i][2].." SLink="..got[i][2]
        end
    end
end

-- ── seeding, as the differential gate does it ────────────────────────────────────────────
local specimen=bytes(M.PARTY_BASE_ADDR,44)
local ot=bytes(M.PARTY_OT_NAMES_ADDR,11)
local nick=bytes(M.PARTY_NICKS_ADDR,11)
local boot=memorysavestate.savecorestate()

local function seed(pc,bc)
    memorysavestate.loadcorestate(boot)
    M._party_tail_cache=nil
    M._memorial_reservations=nil
    write(address("wPartyCount"),pc)
    write(address("wBoxCount"),bc)
    for _,spec in ipairs({{pc,44,"wPartyMons","wPartyMonOT","wPartyMonNicks","wPartySpecies",0},
                           {bc,33,"wBoxMons","wBoxMonOT","wBoxMonNicks","wBoxSpecies",100}}) do
        for slot=0,spec[1]-1 do
            local dst=address(spec[3])+slot*spec[2]
            put(dst,specimen,spec[2])
            write(dst+12,0x12);write(dst+13,spec[7]+slot)
            if spec[2]==33 then write(dst+3,specimen[34]) end
            put(address(spec[4])+slot*11,ot)
            put(address(spec[5])+slot*11,nick)
            write(address(spec[4])+slot*11,0x80+slot%26)
            write(address(spec[5])+slot*11,0x99-slot%26)
            write(dst+4,({0,1,0x08,0x10,0x20,0x40})[slot%6+1])
            write(address(spec[6])+slot,specimen[1])
        end
        write(address(spec[6])+spec[1],0xFF)
    end
end

local function box_key(slot)
    local addr=address("wBoxMons")+slot*33
    return string.format("%02X%02X:%04X:%02X",read(addr+27),read(addr+28),
                         read(addr+12)*256+read(addr+13),read(addr))
end
local function party_key(slot) return M.monKey(M.PARTY_BASE_ADDR+slot*M.PARTY_STRUCT_SIZE) end

-- The cartridge's own MoveMon/RemovePokemon pair through a RAM trampoline, exactly as the
-- differential gate drives it (interrupts off, completion spins in place).
local function canonical(deposit,slot)
    write(address("wWhichPokemon"),slot)
    write(address("wCurPartySpecies"),specimen[1])
    write(address("wMoveMonType"),deposit and 1 or 0)
    local code={0xF3}
    local function emit(...) for _,v in ipairs({...}) do code[#code+1]=v end end
    local switch=address("Bankswitch")
    for _,name in ipairs({"_MoveMon","_RemovePokemon"}) do
        if name=="_RemovePokemon" then
            local flag=address("wRemoveMonFromBox")
            emit(0x3E,deposit and 0 or 1,0xEA,flag%256,math.floor(flag/256))
        end
        local s=sym(name)
        emit(0x06,s.bank,0x21,s.addr%256,math.floor(s.addr/256),
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
local function invoke(names)
    local code={0xF3}
    local function emit(...) for _,v in ipairs({...}) do code[#code+1]=v end end
    local switch=address("Bankswitch")
    for _,name in ipairs(names) do
        local s=sym(name)
        emit(0x06,s.bank,0x21,s.addr%256,math.floor(s.addr/256),0xCD,switch%256,math.floor(switch/256))
    end
    emit(0x3E,0xA5,0xEA,0xFF,0xC7,0x18,0xFE)
    write(0xC7FF,0);put(0xC800,code)
    emu.setregister("SP",0xDFFE);emu.setregister("PC",0xC800)
    for _=1,40 do t.step();if read(0xC7FF)==0xA5 then return end end
    error("canonical save routine did not return")
end

-- A refusal is only a refusal if the message is the production one AND nothing moved.
local refusals=0
local function refuses(what,ok,err,expected,before)
    refusals=refusals+1
    local drift=unchanged(before,image())
    return t.check(what, ok==false and err==expected and drift==nil,
                   drift or ("returned "..tostring(ok).." / "..tostring(err)))
end

local ok,err=pcall(function()
    -- The differential specimen is the boot party's first mon; make its box copy withdrawable
    -- with nonzero experience exactly as the differential gate normalizes it.
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

    -- The whole-image comparator itself: it must see one byte anywhere in SRAM or WRAM.
    seed(3,4)
    local probe=image()
    write(0x7FFF,(read(0x7FFF,"CartRAM")+1)%256,"CartRAM")
    t.check("comparator detects a one-byte SRAM mutation",unchanged(probe,image())~=nil)
    write(0x7FFF,(read(0x7FFF,"CartRAM")-1)%256,"CartRAM")
    write(0xDFFD,(read(0xDFFD)+1)%256)
    t.check("comparator detects a one-byte WRAM mutation",unchanged(probe,image())~=nil)
    write(0xDFFD,(read(0xDFFD)-1)%256)
    t.check("comparator accepts the restored image",unchanged(probe,image())==nil)

    -- ── differential: boundary failures ──────────────────────────────────────────────────
    local all=true
    for _,bc in ipairs({0,10,19}) do
        seed(1,bc)
        local before=image()
        local r,e=M.depositPartyMon(0)
        all=refuses("deposit refuses the last party member (box="..bc..")",r,e,"last mon in party",before) and all
    end
    for _,pc in ipairs({2,6}) do
        seed(pc,20)
        for slot=0,pc-1 do
            local before=image()
            local r,e=M.depositPartyMon(slot)
            all=refuses("deposit refuses a full current box (party="..pc..", slot="..slot..")",r,e,"box full",before) and all
        end
    end
    seed(3,5)
    for _,slot in ipairs({-1,3,6,1.5,"1",true,"nil"}) do
        if slot=="nil" then slot=nil end                  -- ipairs stops at a real nil
        local before=image()
        local r,e=M.depositPartyMon(slot)
        all=refuses("deposit refuses invalid slot "..tostring(slot),r,e,"invalid slot",before) and all
    end
    for _,bc in ipairs({1,20}) do
        seed(6,bc)
        for _,slot in ipairs(bc==1 and {0} or {0,bc-1}) do
            local before=image()
            local r,e=M.retrieveBoxMon(box_key(slot))
            all=refuses("withdraw refuses a full party (box="..bc..", slot="..slot..")",r,e,"party full",before) and all
        end
    end
    t.check("every boundary refusal is exact and leaves WRAM/HRAM/SRAM byte-identical",all)
    -- Positive controls on the same seeds, so the refusals are not vacuous.
    seed(2,19)
    t.check("control: one past the boundary, deposit succeeds",M.depositPartyMon(0)==true
            and M.getPartyCount()==1 and M.getBoxCount()==20)
    seed(5,20)
    t.check("control: one past the boundary, withdraw succeeds",M.retrieveBoxMon(box_key(19))==true
            and M.getPartyCount()==6 and M.getBoxCount()==19)

    -- ── storage: invalid current box ─────────────────────────────────────────────────────
    local invalid_ok=true
    for _,v in ipairs({12,13,127,0x8C,0x8D,0xFF}) do
        seed(3,2)
        write(address("wCurrentBoxNum"),v)
        local before=image()
        local r,e=M.depositPartyMon(0)
        invalid_ok=refuses(string.format("deposit refuses wCurrentBoxNum=$%02X",v),r,e,"invalid current box",before) and invalid_ok
        local r2,e2=M.retrieveBoxMon(box_key(0))
        invalid_ok=refuses(string.format("withdraw refuses wCurrentBoxNum=$%02X",v),r2,e2,"invalid current box",before) and invalid_ok
    end
    t.check("wCurrentBoxNum >= 12 refuses both writers without mutation",invalid_ok)
    for _,v in ipairs({11,0x8B,0,0x80}) do
        seed(3,2)
        write(address("wCurrentBoxNum"),v)
        t.check(string.format("control: wCurrentBoxNum=$%02X is a legal box and deposit succeeds",v),
                M.depositPartyMon(0)==true and M.getBoxCount()==3)
    end

    -- ── storage: canonical initiator undo ────────────────────────────────────────────────
    -- The server compensates a PC initiator whose partner cannot follow with the OPPOSITE
    -- canonical operation. Prove the writer that carries it out reproduces the cartridge's
    -- own inverse MoveMon from the state the initiator's real PC move left behind.
    local undo_cases,undo_failed=0,0
    local function undo_case(deposit_first,pc,bc,slot)
        seed(pc,bc)
        canonical(deposit_first,slot)                    -- the initiator's own PC move
        local undone_key=deposit_first and box_key(bc) or party_key(pc)
        local clone=memorysavestate.savecorestate()
        canonical(not deposit_first, deposit_first and bc or pc)   -- cartridge inverse
        local expected=authoritative()
        memorysavestate.loadcorestate(clone);memorysavestate.removestate(clone)
        M._party_tail_cache=nil                           -- the server's copy is what a live undo has
        local r,e
        if deposit_first then r,e=M.retrieveBoxMon(undone_key) else r,e=M.depositPartyMon(pc) end
        local mismatch=same_records(expected,authoritative())
        undo_cases=undo_cases+1
        local restored=M.getPartyCount()==pc and M.getBoxCount()==bc
        if not r or mismatch or not restored then
            undo_failed=undo_failed+1
            if undo_failed<=12 then
                t.check(string.format("%s undo p=%d b=%d slot=%d",deposit_first and "deposit" or "withdraw",pc,bc,slot),
                        false,mismatch or e or "counts not restored")
            end
        end
    end
    for pc=2,6 do for _,bc in ipairs({0,5,18}) do for slot=0,pc-1 do undo_case(true,pc,bc,slot) end end end
    t.check("canonical deposit undone through retrieveBoxMon equals the cartridge withdraw ("..undo_cases.." cases)",undo_failed==0,"failures="..undo_failed)
    local deposit_undo=undo_cases
    for _,pc in ipairs({1,3,5}) do for _,bc in ipairs({1,7,20}) do for _,slot in ipairs({0,bc-1}) do undo_case(false,pc,bc,slot) end end end
    t.check("canonical withdrawal undone through depositPartyMon equals the cartridge deposit ("..(undo_cases-deposit_undo).." cases)",undo_failed==0,"failures="..undo_failed)

    -- ── storage: whole empty reserved box ────────────────────────────────────────────────
    -- Box 12 is the memorial. Its count may say empty while a record sits past the count.
    local memoff=sram_offset("sBox12")
    local boxlen=address("wBoxDataEnd")-address("wBoxDataStart")
    local structs_off=memoff+1+(M.BOX_MAX_MONS+1)
    local ots_off=structs_off+M.BOX_MAX_MONS*M.BOX_STRUCT_SIZE
    local nicks_off=ots_off+M.BOX_MAX_MONS*11
local function memorial_state(initialized)
        seed(3,2)
        write(address("wCurrentBoxNum"),0)
        -- Party slot 1 is the dead one (HP 0); the memorial requires a fainted selection.
        write(address("wPartyMons")+44+1,0);write(address("wPartyMons")+44+2,0)
        invoke({"SaveGameData"})              -- a real canonical main save and checksum
        if initialized == false then
            -- A genuinely empty pre-ChangeBox image. Its zero header is legal:
            -- EmptyAllSRAMBoxes will install the FF terminator during init.
            for i=0,boxlen-1 do write(memoff+i,0,"CartRAM") end
        else
            local did,why=M.protectSramBoxes()    -- first-time init, as the cartridge would
            assert(did and not why,"memorial geometry init refused: "..tostring(why))
            write(memoff,0,"CartRAM");write(memoff+1,0xFF,"CartRAM")
        end
    end
    local function hidden_record(slot,hp)
        local base=structs_off+slot*M.BOX_STRUCT_SIZE
        put(base,specimen,M.BOX_STRUCT_SIZE,"CartRAM")
        write(base+M.HP_OFFSET,math.floor(hp/256),"CartRAM");write(base+M.HP_OFFSET+1,hp%256,"CartRAM")
        put(ots_off+slot*11,ot,11,"CartRAM");put(nicks_off+slot*11,nick,11,"CartRAM")
    end
    local hidden_ok=true
    for _,slot in ipairs({0,7,19}) do
        memorial_state()
        hidden_record(slot,specimen[35]*256+specimen[36])   -- alive: full HP
        M._memorial_reservations=nil
        local before=image()
        local r,e=M.depositMemorialMon(1)
        hidden_ok=refuses("memorial refuses a live record hidden at reserved slot "..slot,r,e,
                          "memorial box contains a live Pokemon",before) and hidden_ok
    end
    t.check("a live record anywhere in the reserved box image refuses the memorial",hidden_ok)
    local first_use_ok=true
    for _,slot in ipairs({0,7,19}) do
        memorial_state(false)
        hidden_record(slot,specimen[35]*256+specimen[36])
        local before=image()
        local r,e=M.depositMemorialMon(1)
        first_use_ok=refuses("first-use memorial refuses hidden live slot "..slot,r,e,
            "unowned memorial box is not empty before initialization",before) and first_use_ok
    end
    memorial_state(false)
    hidden_record(19,0)
    local before=image()
    local r,e=M.depositMemorialMon(1)
    first_use_ok=refuses("first-use memorial refuses hidden dead tail",r,e,
        "unowned memorial box is not empty before initialization",before) and first_use_ok
    memorial_state(false)
    write(nicks_off+19*11+10,0x80,"CartRAM")
    before=image();r,e=M.depositMemorialMon(1)
    first_use_ok=refuses("first-use memorial refuses unowned nickname tail",r,e,
        "unowned memorial box is not empty before initialization",before) and first_use_ok
    memorial_state(false)
    write(memoff+20,0x99,"CartRAM")
    before=image();r,e=M.depositMemorialMon(1)
    first_use_ok=refuses("first-use memorial refuses unowned species-list tail",r,e,
        "unowned memorial box is not empty before initialization",before) and first_use_ok
    t.check("whole pre-init reserved image refuses all hidden record/name/list content",first_use_ok)
    memorial_state(false)
    local first,first_error=M.depositMemorialMon(1)
    t.check("genuinely empty first-use memorial succeeds and persists initialized bit",
        first==true and first_error==nil and read(memoff,"CartRAM")==1
            and read(address("wCurrentBoxNum"))>=0x80,tostring(first_error))
    memorial_state()
    hidden_record(19,0)                                     -- dead tail record, legal to ignore
    M._memorial_reservations=nil
    local tail_before=bytes(memoff+1+2,boxlen-3,"CartRAM")  -- everything past count and species[0..1]
    local others_before={}
    for i=6,10 do others_before[i]=bytes(sram_offset("sBox7")+(i-6)*boxlen,boxlen,"CartRAM") end
    local buried,reason=M.depositMemorialMon(1)
    t.check("memorial with a dead tail record succeeds",buried==true and reason==nil,tostring(reason))
    local tail_after=bytes(memoff+1+2,boxlen-3,"CartRAM")
    -- Only slot 0 of the struct, OT and nickname arrays may differ; the dead tail and every
    -- other slot are byte-identical, and boxes 7..11 of the same bank are untouched.
    local touched_outside=nil
    for i=1,#tail_before do
        if tail_before[i]~=tail_after[i] then
            local off=memoff+1+2+(i-1)
            local in_slot0=(off>=structs_off and off<structs_off+M.BOX_STRUCT_SIZE)
                or (off>=ots_off and off<ots_off+11) or (off>=nicks_off and off<nicks_off+11)
            if not in_slot0 then touched_outside=string.format("box 12 offset $%04X",off);break end
        end
    end
    t.check("memorial writes only slot 0 of the reserved box; the dead tail record is untouched",
            touched_outside==nil and read(memoff,"CartRAM")==1,touched_outside)
    local others_ok=true
    for i=6,10 do
        others_ok=others_ok and compare(others_before[i],bytes(sram_offset("sBox7")+(i-6)*boxlen,boxlen,"CartRAM"))==nil
    end
    t.check("boxes 7..11 in the memorial bank are byte-identical after the memorial",others_ok)
end)
memorysavestate.loadcorestate(boot)
memorysavestate.removestate(boot)
t.check("boundary harness completed",ok,tostring(err))
t.check("all 42 refusals were exercised",refusals==42,"refusals="..refusals)
t.finish("storage boundaries")
