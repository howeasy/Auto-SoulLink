-- RR-specific preparation and physical evidence for command_executor's adapter
-- contract. No journal, session or retry policy lives here. The existing RR client
-- also uses this adapter while its durable dispatcher binding is being integrated.
local Storage = {}
local kinds = {box_mon="deposit",party_mon="withdraw",memorialize="memorialize"}
local EMPTY_PARTY = string.rep("00",100)
local EMPTY_BOX = string.rep("00",58)
local function copy(value)
    if type(value)~="table" then return value end
    local result={}
    for key,item in pairs(value) do result[key]=copy(item) end
    return result
end

function Storage.new(M, MB, io, context, withdrawal)
    if withdrawal and (type(withdrawal)~="table" or type(withdrawal.prepare)~="function"
        or type(withdrawal.verify)~="function" or type(withdrawal.check_context)~="function") then
        return nil,"complete local withdrawal evidence binding required"
    end
    local self = {}
    -- Volatile native mailbox ownership only. The durable intent belongs to the
    -- shared command inbox; losing this lease never proves an earlier effect failed.
    local native = nil
    local function hex_at(address,size)
        local bytes = {}
        for i=0,size-1 do bytes[#bytes+1]=io.read_u8(address+i) end
        return M.bytesToHex(bytes)
    end
    local function party()
        local result={}
        for slot=0,5 do result[slot+1]=hex_at(M.PARTY_BASE+slot*M.MON_SIZE,100) end
        return result
    end
    local function same(a,b)
        for i=1,6 do if a[i]~=b[i] then return false end end
        return true
    end
    -- Read-only projection of the existing RR native/Lua 58-byte representation.
    -- Exact copies/10-bit packing verified against RR's 0x090B6B78 primitive.
    local function compressed(raw)
        local b=assert(M.hexToBytes(raw));local out={}
        local function copy(first,last)
            for off=first,last do out[#out+1]=b[off+1] end
        end
        copy(0,27);copy(0x20,0x2A)
        local packed=0
        for i=0,3 do
            local off=0x2C+i*2
            packed=packed|(((b[off+1]|(b[off+2]<<8))&0x3FF)<<(i*10))
        end
        for i=0,4 do out[#out+1]=(packed>>(i*8))&255 end
        copy(0x38,0x3D);copy(0x44,0x4B)
        return M.bytesToHex(out)
    end
    local function signature(intent)
        return intent.kind..":"..intent.key..":"..intent.slot..":"..intent.box..":"..intent.pos
            ..":"..table.concat(intent.before_party)..":"..intent.before_box
            ..":"..tostring(intent.source_box)..":"..tostring(intent.source_pos)
            ..":"..(intent.withdrawal and intent.withdrawal.party_sha256 or "legacy")
    end

    function self.prepare(body)
        local kind=kinds[body.cmd]
        if kind=="memorialize" and body.source_box~=nil then kind="boxed_memorialize" end
        local current=context.sample()
        local ok,reason=context.storage_prerequisite(kind,current)
        if not ok then return nil,reason end
        local slot,box,pos=body.slot or 0,body.box,body.pos
        if type(slot)~="number" or slot%1~=0 or slot<0 or slot>5
            or type(box)~="number" or box%1~=0 or box<0 or box>=M.BOXES_PER_STORE
            or type(pos)~="number" or pos%1~=0 or pos<0 or pos>=M.MONS_PER_BOX then
            return nil,"invalid storage coordinates"
        end
        local box_addr=M.boxMonAddr(box,pos)
        if not box_addr then return nil,"box address unavailable" end
        local before_party,before_box=party(),hex_at(box_addr,58)
        local source=kind=="withdraw" and box_addr or (M.PARTY_BASE+slot*M.MON_SIZE)
        local source_box_hex
        if kind=="boxed_memorialize" then
            if type(body.source_box)~="number" or body.source_box%1~=0 or body.source_box<0
                or body.source_box>=M.BOXES_PER_STORE or type(body.source_pos)~="number"
                or body.source_pos%1~=0 or body.source_pos<0 or body.source_pos>=M.MONS_PER_BOX then
                return nil,"invalid boxed memorial source"
            end
            source=M.boxMonAddr(body.source_box,body.source_pos)
            if source==box_addr or not M.boxSlotOccupied(source) or before_box~=EMPTY_BOX then
                return nil,"boxed memorial source/destination unavailable"
            end
            source_box_hex=hex_at(source,58)
        end
        if M.monKey(source)~=body.key then return nil,"storage source identity changed" end
        if kind=="boxed_memorialize" then
            -- The death obligation is supplied by the admitted rules coordinator;
            -- compressed RR boxes do not contain current HP.
        elseif kind=="withdraw" then
            if slot~=current.count or before_party[slot+1]~=EMPTY_PARTY or not M.boxSlotOccupied(source) then
                return nil,"withdraw source/destination is not available"
            end
        else
            if slot>=current.count or not M.slotOccupied(source) or before_box~=EMPTY_BOX then
                return nil,"deposit source/destination is not available"
            end
            if kind=="memorialize" and io.read_u16_le(source+M.OFF_HP)~=0 then
                return nil,"memorial target is not fainted"
            end
        end
        local intent={schema=withdrawal and "rr-storage-intent-v2" or "rr-storage-intent-v1",
            kind=kind,key=body.key,slot=slot,box=box,pos=pos,
            pre_count=current.count,before_party=before_party,before_box=before_box,
            save_fingerprint=current.save_fingerprint,swap_seq=current.swap.seq,
            guard={pid=io.read_u32_le(source),otid=io.read_u32_le(source+4),count=current.count}}
        intent.source_box=body.source_box;intent.source_pos=body.source_pos
        intent.before_source_box=source_box_hex
        intent.after_party={table.unpack(before_party)}
        if kind=="boxed_memorialize" then
            intent.after_count=current.count;intent.after_box=source_box_hex
        elseif kind=="withdraw" then
            intent.after_count=current.count+1;intent.after_box=EMPTY_BOX
            if withdrawal then
                local proof,problem=withdrawal.prepare(before_box)
                if not proof then return nil,problem end
                intent.withdrawal=proof
                intent.after_party[slot+1]=proof.expected_party
            end
        else
            intent.after_count=current.count-1;intent.after_box=compressed(before_party[slot+1])
            if kind=="deposit" then
                for index=slot+1,current.count-1 do intent.after_party[index]=before_party[index+1] end
            else
                intent.after_party[slot+1]=before_party[current.count]
            end
            intent.after_party[current.count]=EMPTY_PARTY
        end
        return intent
    end

    function self.classify(body,intent)
        local kind=kinds[body.cmd]
        if kind=="memorialize" and body.source_box~=nil then kind="boxed_memorialize" end
        local schema=withdrawal and "rr-storage-intent-v2" or "rr-storage-intent-v1"
        if intent.schema~=schema or kind~=intent.kind or body.key~=intent.key then
            return "diverged","storage intent does not match command"
        end
        if (body.slot or 0)~=intent.slot or body.box~=intent.box or body.pos~=intent.pos
            or body.source_box~=intent.source_box or body.source_pos~=intent.source_pos then
            return "diverged","storage coordinates differ from prepared command"
        end
        local current=context.sample()
        local ok,reason=context.storage_readback_prerequisite(current)
        if not ok then return "diverged",reason end
        if current.save_fingerprint~=intent.save_fingerprint or current.swap.seq~=intent.swap_seq then
            return "diverged","save or borrowed-party epoch changed"
        end
        if withdrawal and kind=="withdraw" then
            local verified,problem=withdrawal.verify(intent.withdrawal,intent.before_box)
            if not verified then return "diverged",problem end
            if intent.after_party[intent.slot+1]~=intent.withdrawal.expected_party then
                return "diverged","prepared withdrawal destination differs from pinned evidence"
            end
        end
        -- Local evidence/hash services may have yielded. Do not carry a count,
        -- save binding or ownership sample across that work into a receipt.
        current=context.sample()
        ok,reason=context.storage_readback_prerequisite(current)
        if not ok then return "diverged",reason end
        if current.save_fingerprint~=intent.save_fingerprint or current.swap.seq~=intent.swap_seq then
            return "diverged","save or borrowed-party epoch changed during verification"
        end
        local actual,boxed=party(),hex_at(M.boxMonAddr(intent.box,intent.pos),58)
        local source_boxed=intent.source_box and hex_at(M.boxMonAddr(intent.source_box,intent.source_pos),58) or nil
        local final=context.sample()
        ok,reason=context.storage_readback_prerequisite(final)
        if not ok then return "diverged",reason end
        if final.count~=current.count or final.save_fingerprint~=current.save_fingerprint
            or final.swap.seq~=current.swap.seq then
            return "diverged","storage context changed during physical readback"
        end
        if withdrawal and kind=="withdraw" then
            ok,reason=withdrawal.check_context(intent.withdrawal)
            if not ok then return "diverged",reason end
        end
        if current.count==intent.after_count and boxed==intent.after_box
            and (not source_boxed or source_boxed==EMPTY_BOX) then
            local matches=same(actual,intent.after_party)
            if intent.kind=="withdraw" and not withdrawal then
                local expected={table.unpack(intent.after_party)}
                expected[intent.slot+1]=actual[intent.slot+1]
                local base=M.PARTY_BASE+intent.slot*M.MON_SIZE
                matches=same(actual,expected) and compressed(actual[intent.slot+1])==intent.before_box
                    and M.slotOccupied(base) and io.read_u8(base+M.OFF_LEVEL)>0
                    and io.read_u8(base+M.OFF_LEVEL)<=100
                    and io.read_u16_le(base+M.OFF_HP)==io.read_u16_le(base+M.OFF_MAX_HP)
                for off=0x5A,0x62,2 do matches=matches and io.read_u16_le(base+off)>0 end
            end
            if matches then return "after",{party=actual,box=boxed,source_boxed=source_boxed,count=current.count} end
        end
        if current.count==intent.pre_count and boxed==intent.before_box and same(actual,intent.before_party)
            and source_boxed==intent.before_source_box then
            if native and native.signature==signature(intent) then
                return "diverged","native storage is pending or refused; reconcile before retrying"
            end
            return "before",{party=actual,box=boxed,count=current.count}
        end
        return "diverged","storage readback differs from both prepared states"
    end

    function self.apply(body,intent)
        if native then return nil,"native storage lease is unresolved" end
        local state,reason=self.classify(body,intent)
        if state~="before" then return nil,type(reason)=="string" and reason or "storage prestate changed" end
        local seq,problem
        if intent.kind=="boxed_memorialize" then
            if not MB.move_box_mon then return nil,"guarded box migration unavailable" end
            seq,problem=MB.move_box_mon(intent.source_box,intent.source_pos,intent.box,intent.pos,intent.guard)
        elseif intent.kind=="deposit" then seq,problem=MB.deposit_mon(intent.slot,intent.box,intent.pos,intent.guard)
        elseif intent.kind=="withdraw" then seq,problem=MB.withdraw_mon(intent.box,intent.pos,intent.slot,intent.guard)
        else seq,problem=MB.memorialize_mon(intent.slot,intent.box,intent.pos,intent.guard) end
        if not seq then return nil,problem or "native storage submission refused" end
        native={signature=signature(intent),seq=seq}
        return seq
    end

    function self.receipt(body,intent,observation)
        local state,current=self.classify(body,intent)
        if state~="after" then return nil,current end
        if not observation or observation.count~=current.count or observation.box~=current.box
            or observation.source_boxed~=current.source_boxed
            or not same(observation.party,current.party) then return nil,"storage evidence changed" end
        native=nil
        return {schema=withdrawal and "rr-storage-receipt-v2" or "rr-storage-receipt-v1",kind=intent.kind,key=intent.key,
            box=intent.box,pos=intent.pos,party_count=current.count,party=current.party,boxed=current.box,
            source_box=intent.source_box,source_pos=intent.source_pos,source_boxed=current.source_boxed,
            withdrawal=copy(intent.withdrawal),durability="live_ram_only"}
    end
    return self
end

-- Selected only by the future admitted bootstrap/private validation. Missing
-- local evidence refuses construction; never fall back to the v1 predicate.
-- Keep legacy new() explicit until loader/admission integration is validated.
function Storage.new_verified(M, MB, io, context, withdrawal)
    if type(withdrawal)~="table" or type(withdrawal.prepare)~="function"
        or type(withdrawal.verify)~="function" or type(withdrawal.check_context)~="function" then
        return nil,"verified withdrawal binding required"
    end
    return Storage.new(M, MB, io, context, withdrawal)
end
return Storage
