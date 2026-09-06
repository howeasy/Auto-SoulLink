-- Real cartridge RAM, verified overworld checkpoint, and flushed local journal.
-- Fail immediately before/after the actual forceFaint call, reopen the journal,
-- and require independent poststate classification before emitting its receipt.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_command_receipts_gate")
local M=t.M
package.path=ROOT.."/lua/?.lua;"..package.path
local JSON=require("json_codec")
local Storage=require("platform_storage")
local Store=require("state_store")
local Journal=require("client_journal")
local Executor=require("command_executor")
local Policy=require("gen1_force_faint_executor")
local Receipts=require("gen1_command_receipts")
local Identity=require("platform_identity")
local rom_hash=gameinfo.getromhash():lower()
local run_id=assert(Identity.new_nonce())
local evidence={variant=t.variant,rom_sha1=rom_hash,cases=JSON.array()}
local native_faint,native_write=M.forceFaint,M.write_u8
local boot
local opened_store
local ok,reason=pcall(function()
    for _=1,300 do if M.isPartyWriteSafe() then break end;t.step() end
    assert(M.isPartyWriteSafe(),"verified overworld checkpoint unavailable")
    boot=memorysavestate.savecorestate()
    -- The old town fixture was hand-built with zero experience at level5. Derive
    -- a valid record through the cartridge's _MoveMon/CalcStats, then transplant
    -- that exact record into the original overworld checkpoint. No routine-hook
    -- scratch or CPU state is allowed to become write-safety evidence.
    local source=t.variant=="yellow" and "pokeyellow" or "pokered"
    local target=t.variant=="blue" and "pokeblue" or source
    local oracle=dofile(ROOT.."/lua/tests/gb_routine_oracle.lua").new({
        symbols_path=ROOT.."/.cache/pret/"..source.."/"..target..".sym",step=t.step,
        scratch=0xC800,marker=0xC7FF,stack=0xDFFE,bankswitch="Bankswitch"})
    local a,r,w,cp=oracle.address,oracle.read,oracle.write,oracle.copy
    cp(a("wBoxMons"),a("wPartyMons"),33);cp(a("wBoxMonOT"),a("wPartyMonOT"),11)
    cp(a("wBoxMonNicks"),a("wPartyMonNicks"),11)
    local species=r(a("wPartyMon1Species"))
    w(a("wBoxMon1Exp"),0);w(a("wBoxMon1Exp")+1,3);w(a("wBoxMon1Exp")+2,0xE8)
    w(a("wBoxCount"),1);w(a("wBoxSpecies"),species);w(a("wBoxSpecies")+1,255)
    w(a("wPartyCount"),0);w(a("wPartySpecies"),255)
    w(a("wWhichPokemon"),0);w(a("wCurPartySpecies"),species);w(a("wMoveMonType"),0)
    oracle.invoke("_MoveMon");w(a("wRemoveMonFromBox"),1);oracle.invoke("_RemovePokemon")
    local canonical_blob=assert(M.readPartyBlob(0))
    assert(require("gen1_party_codec").validateBlob(canonical_blob,t.variant))
    memorysavestate.loadcorestate(boot)
    for i=1,44 do M.write_u8(M.PARTY_BASE_ADDR+i-1,canonical_blob[i]) end
    for i=1,11 do
        M.write_u8(M.PARTY_OT_NAMES_ADDR+i-1,canonical_blob[44+i])
        M.write_u8(M.PARTY_NICKS_ADDR+i-1,canonical_blob[55+i])
    end
    local specimen=memorysavestate.savecorestate()
    t.check("native specimen at original verified checkpoint",M.isPartyWriteSafe())
    evidence.specimen="cartridge _MoveMon/_RemovePokemon; boxed experience fixture 1000"
    for _,boundary in ipairs({"before_effect","after_effect"}) do
        memorysavestate.loadcorestate(specimen)
        local before=assert(Receipts.party_snapshot(M,t.variant))
        local identity={ot_id=before.save_id,trainer_name=before.save_name}
        local binding={run_id=run_id,player="a",variant=t.variant,save_id=before.save_id,
            save_name=before.save_name,rom_sha1=rom_hash}
        local path=ROOT.."/patch/build/receipts-"..run_id.."/"..boundary..".json"
        local function open()
            local store=assert(Store.open(assert(Storage.new(path)),binding,Journal.initial()))
            opened_store=store
            return store,assert(Journal.open(store))
        end
        local store,journal=open()
        local operation=assert(journal:append({event="tick"}))
        local command_id=assert(Identity.new_nonce())
        local command={cmd="force_faint",key=assert(M.readPartySlot(0)).key}
        assert(journal:accept_response(operation,JSON.array({
            {command_id=command_id,command_sequence=1,body=command}})))
        local fault,write_count=boundary,0
        M.write_u8=function(address,value)
            write_count=write_count+1
            return native_write(address,value)
        end
        M.forceFaint=function(slot)
            if fault=="before_effect" then error("injected exception before physical write",0) end
            local result=native_faint(slot)
            if fault=="after_effect" then error("injected exception after physical write",0) end
            return result
        end
        local adapter=Policy.new(M,t.variant,identity,function()
            if gameinfo.getromhash():lower()~=rom_hash then return false,"ROM changed" end
            return M.isPartyWriteSafe()
        end)
        local original={}
        for a=0xC000,0xDFFF do original[a]=memory.read_u8(a,"System Bus") end
        local executed,diagnostic=Executor.new(journal,adapter):step(command_id)
        t.check(boundary.." returns retryable NACK",not executed and diagnostic.outcome=="NACK" and diagnostic.retryable)
        t.check(boundary.." retains intent without receipt",journal:get_command(command_id).intent~=nil
            and journal:get_command(command_id).outcome==nil and #journal:pending_events()==0)
        local calls_before_reopen=write_count
        t.check(boundary.." reaches expected physical boundary",write_count==(boundary=="before_effect" and 0 or 2))
        store:close();store,journal=open()
        fault=nil
        local resumed,result=Executor.new(journal,adapter):step(command_id)
        t.check(boundary.." recovers from exact readback",resumed and result.outcome=="ACK")
        t.check(boundary.." executes only the missing effect",write_count==2
            and (boundary~="after_effect" or write_count==calls_before_reopen))
        local unrelated=0
        for a=0xC000,0xDFFF do
            if a~=M.PARTY_BASE_ADDR+M.HP_OFFSET and a~=M.PARTY_BASE_ADDR+M.HP_OFFSET+1
                and memory.read_u8(a,"System Bus")~=original[a] then unrelated=unrelated+1 end
        end
        t.check(boundary.." preserves every unrelated WRAM byte",unrelated==0,tostring(unrelated))
        t.check(boundary.." exact party readback",JSON.encode(result.receipt.after)==JSON.encode(assert(Receipts.party_snapshot(M,t.variant))))
        store:close();store,journal=open()
        local ack=journal:pending_events()[1]
        t.check(boundary.." physical receipt and ACK survive together",ack and ack.payload.event=="command_ack"
            and ack.payload.outcome=="ACK" and #journal:pending_commands()==0)
        t.check(boundary.." completed replay avoids all writes",Executor.new(journal,adapter):step(command_id) and write_count==2)
        evidence.cases[#evidence.cases+1]={boundary=boundary,command=command,identity=identity,
            receipt=ack.payload.receipt,physical_writes=write_count,unrelated_wram_changes=unrelated}
        assert(journal:accept_response(ack.operation_id,JSON.array()))
        t.check(boundary.." server confirmation advances floor",(assert(store:read())).command_floor==1)
        store:close();opened_store=nil
    end
    local output=assert(io.open(ROOT.."/.cache/gen1-command-receipts-"..t.variant..".json","w"))
    output:write(assert(JSON.encode(evidence)));output:close()
end)
M.forceFaint,M.write_u8=native_faint,native_write
if opened_store then opened_store:close() end
if boot then memorysavestate.loadcorestate(boot) end
t.log("rom_sha1="..rom_hash)
t.check("live prepared command recovery completed",ok,tostring(reason))
t.finish()
