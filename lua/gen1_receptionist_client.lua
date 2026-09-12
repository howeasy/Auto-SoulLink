-- Native receptionist lease -> durable offer -> exact server acknowledgement.
-- No frames, party writes, connection ownership or linked-pair inference here.
local JSON=require("json_codec")
local Receipts=require("gen1_command_receipts")
local Identity=require("platform_identity")
local Codec=require("gen1_party_codec")
local M={}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function same(a,b)return assert(JSON.encode(a))==assert(JSON.encode(b))end
local function token(value)return type(value)=="string" and #value==32 and value:match("^[0-9a-f]+$")end
function M.query(mem,manifest)
    local ui,ram=manifest.receptionist,manifest.ram
    if gameinfo.getromhash():lower()~=manifest.final_sha1 or emu.getregister("PC")~=0x40
        or memory.read_u8(ram.hLoadedROMBank,"System Bus")~=ui.entry.bank then return nil end
    local sp=emu.getregister("SP")
    local caller=memory.read_u8(sp+2,"System Bus")+256*memory.read_u8(sp+3,"System Bus")
    if caller~=ui.query_return then return nil end
    local bytes={};for i=0,15 do bytes[#bytes+1]=memory.read_u8(manifest.foreground.overlay+i,"System Bus")end
    if mem.bytesToHex({table.unpack(bytes,1,6)})~="534C54310101" or bytes[7]==bytes[8] then return nil end
    return {schema="rby-receptionist-query-v1",pc=0x40,bank=ui.entry.bank,caller=caller,overlay_hex=mem.bytesToHex(bytes)}
end
function M.new(options)
    local mem,manifest,journal=options.memory,copy(options.manifest),options.journal
    assert(manifest.schema=="gen1-native-trade-build-v1" and manifest.receptionist and manifest.foreground,
        "native receptionist artifact required")
    assert(type(options.authorize)=="function" and type(options.eligible_slots)=="function"
        and type(options.context_generation)=="function","owned receptionist policies required")
    local ui,ram,overlay=manifest.receptionist,manifest.ram,manifest.foreground.overlay
    local self={visit=nil,closed=false}
    local function r(p)return memory.read_u8(p,"System Bus")end
    local function w(p,value)memory.write_u8(p,value,"System Bus")end
    local function hex(p,count)
        local values={};for i=0,count-1 do values[#values+1]=r(p+i)end;return mem.bytesToHex(values)
    end
    local function checkpoint(caller,command)
        if emu.getregister("PC")~=0x40 or r(ram.hLoadedROMBank)~=ui.entry.bank then return false end
        local sp=emu.getregister("SP")
        return r(sp+2)+r(sp+3)*256==caller and hex(overlay,5)=="534C543101" and r(overlay+5)==command
    end
    local function guard(action)
        assert(not self.closed and gameinfo.getromhash():lower()==manifest.final_sha1,"receptionist artifact/observer changed")
        local visit=self.visit
        if not visit then return false end
        assert(options.context_generation()==visit.context,"receptionist physical context changed")
        return options.authorize(action)==true
    end
    local hook=event.on_bus_exec(function()
        if r(ram.hLoadedROMBank)~=ui.entry.bank then return end
        local context=options.context_generation();assert(token(context),"receptionist context generation required")
        local nonce=assert((options.new_nonce or Identity.new_nonce)())
        assert(token(nonce) and nonce:sub(1,8)~="00000000","fresh receptionist token required")
        self.visit={context=context,token_hex=nonce:sub(1,8):upper()}
    end,ui.entry.address,"slink-receptionist-client","System Bus")
    assert(hook,"native receptionist entry observer unavailable")
    function self.adopt_query(token_hex)
        assert(not self.visit and M.query(mem,manifest),"original native query checkpoint required")
        assert(type(token_hex)=="string" and #token_hex==8 and token_hex:match("^[0-9A-F]+$")
            and token_hex~="00000000","fresh receptionist token required")
        self.visit={context=options.context_generation(),token_hex=token_hex}
    end
    function self.step()
        if not self.visit then return end
        local visit=self.visit
        if checkpoint(ui.query_return,1) and not visit.snapshot then
            if not guard("query")then return end
            local snapshot=assert(Receipts.party_snapshot(mem,manifest.variant))
            assert(snapshot.battle_flag==0,"receptionist query is not in overworld")
            local mask=options.eligible_slots(copy(snapshot))
            if mask==nil then return end
            assert(type(mask)=="number" and mask%1==0 and mask>=0 and mask<64,"bounded linked-party mask required")
            local generation=r(overlay+6)
            if not guard("query")or not checkpoint(ui.query_return,1)or generation~=r(overlay+6)then return end
            visit.snapshot=snapshot;visit.mask=mask;visit.query_generation=generation
            w(overlay+10,1);w(overlay+11,mask)
            for i=1,4 do w(overlay+11+i,tonumber(visit.token_hex:sub(i*2-1,i*2),16))end
            w(overlay+7,generation) -- publish last, after the exact query body
        elseif checkpoint(ui.offer_return,2) and visit.snapshot then
            if not guard("offer")then return end
            local generation,slot=r(overlay+6),r(overlay+9)
            if hex(overlay+12,4)~=visit.token_hex or r(overlay+8)~=255 then return end
            if slot>=6 or math.floor(visit.mask/2^slot)%2~=1 then return end
            local snapshot=assert(Receipts.party_snapshot(mem,manifest.variant))
            if not same(snapshot,visit.snapshot)then return end
            local mon=assert(Codec.validateBlob(assert(mem.readPartyBlob(slot)),manifest.variant))
            local payload={event="trade_offer",payload={schema="rby-receptionist-offer-v1",
                final_sha1=manifest.final_sha1,context_generation=visit.context,query_generation=visit.query_generation,
                offer_generation=generation,token_hex=visit.token_hex,slot=slot,key=mon.key,snapshot=snapshot}}
            local stored=assert(journal.store:read())
            local previous=stored.observation.gen1_receptionist
            if not previous or not same(previous.payload,payload)then
                -- A previous unacknowledged offer cannot silently be replaced by
                -- a new native visit, even after a client restart or UI timeout.
                if previous and previous.phase=="queued"then return end
                local baseline=copy(stored.observation)
                baseline.gen1_receptionist={phase="queued",payload=payload}
                if options.observe then assert(options.observe(JSON.array({payload}),baseline))
                else assert(journal:append(payload,baseline))end
                return
            end
            if previous.phase=="acknowledged" and guard("offer_ack") and checkpoint(ui.offer_return,2)
                and r(overlay+6)==generation and r(overlay+9)==slot and hex(overlay+12,4)==visit.token_hex then
                w(overlay+8,0);w(overlay+7,generation)
            end
        end
    end
    function self.close()if not self.closed then event.unregisterbyid(hook);self.closed=true end end
    return self
end
return M
