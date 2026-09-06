-- RR 4.1 observation ownership and storage prerequisites. Read-only; this is not
-- cartridge admission, a durable session, or permission to advance the emulator.
-- Addresses are pinned in patch/src/ADDRESSES.md and the RR peer-ghost reader.
local Context = {}
local CB2 = 0x030030F4
local FIELD = 0x080565B5
local SCRIPT_LOCK = 0x03000F9C

function Context.new(memory_api, mailbox, io)
    local M, MB = memory_api, mailbox
    local self = {}
    function self.sample()
        local result = {owner="unavailable", party_observable=false, patch_present=false}
        if not MB or not MB.present() then return result end
        result.patch_present = true
        local sb1, sb2 = io.read_u32_le(M.SB1_PTR_ADDR), io.read_u32_le(M.SB2_PTR_ADDR)
        local count = io.read_u8(M.PARTY_COUNT_ADDR)
        if sb1 < 0x02000000 or sb1 >= 0x02040000 or sb2 < 0x02000000 or sb2 >= 0x02040000
            or count > 6 or not M.hasLoadedTrainerName(sb2) then return result end
        local identity = {}
        for i=0,13 do identity[#identity+1] = string.format("%02X",io.read_u8(sb2+i)) end
        result.save_fingerprint = string.format("%08X:%08X:%s",sb1,sb2,table.concat(identity))
        result.count = count
        result.swap = MB.read_swap_state()
        result.in_battle = M.isInBattle()
        result.callback2 = io.read_u32_le(CB2)
        result.script_locked = io.read_u8(SCRIPT_LOCK) ~= 0
        if result.swap and result.swap.active ~= 0 then
            result.owner = "borrowed_party"
        elseif result.in_battle then
            result.owner = "battle"
            result.party_observable = true
        elseif result.callback2 == FIELD then
            result.owner = result.script_locked and "field_script" or "field_idle"
            result.party_observable = true
        else
            result.owner = "other_callback"
        end
        -- Even the final-KO callback transition needs a complete counted party
        -- before it can supply HP evidence. Borrowed records are never ours.
        if result.owner ~= "borrowed_party" then
            local identities={}
            for slot=0,count-1 do
                local address=M.PARTY_BASE+slot*M.MON_SIZE
                if not M.slotOccupied(address) then
                    result.party_invalid=true
                    result.party_observable=false
                    result.owner="invalid_party"
                    break
                else
                    local key=M.monKey(address)
                    if identities[key] then
                        result.identity_ambiguous=true
                        result.party_observable=false
                        result.owner="ambiguous_party"
                        break
                    end
                    identities[key]=true
                end
            end
        end
        return result
    end

    function self.storage_readback_prerequisite(context)
        context = context or self.sample()
        if context.owner ~= "field_idle" then return false,"storage blocked by "..context.owner end
        -- These known writer tasks must never be overridden by a wall-clock timeout.
        for i=0,15 do
            local task=M.TASKS_BASE_ADDR+i*(M.TASK_STRUCT_SIZE or 40)
            -- RR DestroyTask (08077520) clears +4, not the function pointer.
            if io.read_u8(task+4)~=0 then
                local fn=io.read_u32_le(task)
                for _,writer in ipairs(M.POST_BATTLE_WRITER_TASKS or {}) do
                    if fn == writer then return false,"post-battle party writer active" end
                end
            end
        end
        return true
    end
    function self.storage_prerequisite(operation, context)
        if operation ~= "deposit" and operation ~= "withdraw" and operation ~= "memorialize"
            and operation ~= "boxed_memorialize" then
            return false,"unknown RR storage operation"
        end
        context = context or self.sample()
        local ok,reason = self.storage_readback_prerequisite(context)
        if not ok then return false,reason end
        if operation == "withdraw" and context.count >= 6 then return false,"party full" end
        if (operation == "deposit" or operation == "memorialize") and context.count <= 1 then
            return false,"last party member"
        end
        return true
    end
    return self
end
return Context
