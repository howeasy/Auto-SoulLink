-- Read-only interruption gate for the RR-DURABLE shadow witness.
-- Offsets: patch/src/trade_targets/abi.h SlinkMailboxV2/SlinkTradeWitnessV2,
-- RR base: patch/src/handlers.c RT_BASE, pinned by data/games/gen3_rr/profile.json.
-- COMMIT_ENTERED is scene launch (no-return), not evidence TradeMons ran.
local M = {}
local W = 0x50
local SIG = 0x4B4E4C53 -- 'SLNK' little-endian

local function key_parts(key)
    if type(key) ~= "string" then return nil end
    local pid, ot = key:match("^([0-9A-Fa-f]+):([0-9A-Fa-f]+)$")
    if not pid or #pid ~= 8 or #ot ~= 8 then return nil end
    return tonumber(pid, 16), tonumber(ot, 16)
end

function M.sample(io, base, old_key, before_counter, after_counter)
    local pid, ot = key_parts(old_key)
    if not pid or type(base) ~= "number" then return nil, "invalid old key or native base" end
    if type(before_counter) ~= "number" or type(after_counter) ~= "number"
       or after_counter ~= before_counter + 1 then
        return nil, "native pre-save counter did not advance exactly once"
    end
    local ok, result, why = pcall(function()
        if io.u32(base) ~= SIG then return nil, "shadow signature missing" end
        local witness = base + W
        local rev = io.u16(witness + 0x18)
        if rev == 0 or rev % 2 ~= 0 then return nil, "witness publication is not stable" end
        local epoch, visit = io.u32(witness), io.u32(witness + 4)
        local bits, flags = io.u32(witness + 0x1C), io.u16(witness + 0x1A)
        local pre_seq, scene_seq = io.u16(witness + 0x20), io.u16(witness + 0x22)
        local final_result, save_status = io.u8(witness + 0x2A), io.u8(witness + 0x2B)
        local old_pid, old_ot = io.u32(witness + 0x40), io.u32(witness + 0x44)
        local token = {}
        for i = 0, 15 do token[i + 1] = io.u8(witness + 8 + i) end
        if io.u16(witness + 0x18) ~= rev then return nil, "witness changed during read" end
        if epoch == 0 or visit == 0 or io.u32(base + 0x44) ~= epoch
           or io.u32(base + 0x48) ~= 3 then
            return nil, "shadow epoch or SCENE phase changed"
        end
        if bits ~= 3 or flags ~= 3 or final_result ~= 0 or save_status ~= 1
           or pre_seq == 0 or scene_seq == 0 then
            return nil, "commit window is not PRE_SAVE_OK plus COMMIT_ENTERED before scene/post-save"
        end
        if old_pid ~= pid or old_ot ~= ot then return nil, "old native identity changed" end
        local expected = {0x54, 0x33, 0x46, 0x52}
        local function append_u32(v)
            for i = 0, 3 do expected[#expected + 1] = (v >> (8 * i)) & 0xFF end
        end
        append_u32(epoch); append_u32(visit); append_u32((~visit) & 0xFFFFFFFF)
        for i = 1, 16 do
            if token[i] ~= expected[i] then return nil, "opaque native token changed" end
        end
        return {bits=bits, epoch=epoch, visit=visit, revision=rev, pre_seq=pre_seq,
                scene_seq=scene_seq, counter_before=before_counter,
                counter_after=after_counter, old_key=old_key}
    end)
    if not ok then return nil, "native witness unreadable: " .. tostring(result) end
    return result, why
end

function M.success(io, base, old_key, new_key, before_counter, after_counter)
    local old_pid, old_ot = key_parts(old_key)
    local new_pid, new_ot = key_parts(new_key)
    if not old_pid or not new_pid or type(base) ~= "number" then
        return nil, "invalid outgoing/received key or native base"
    end
    if type(before_counter) ~= "number" or type(after_counter) ~= "number"
       or after_counter ~= before_counter + 2 then
        return nil, "native pre/post-save counters did not both advance"
    end
    local ok, result, why = pcall(function()
        if io.u32(base) ~= SIG or io.u32(base + 0x48) ~= 4 then
            return nil, "shadow signature or DONE phase missing"
        end
        local w = base + W
        local rev = io.u16(w + 0x18)
        if rev == 0 or rev % 2 ~= 0 then return nil, "terminal witness publication is torn" end
        local epoch, visit = io.u32(w), io.u32(w + 4)
        local bits, flags = io.u32(w + 0x1C), io.u16(w + 0x1A)
        local seq = {}
        for i = 0, 4 do seq[i + 1] = io.u16(w + 0x20 + 2 * i) end
        local token = {}
        for i = 0, 15 do token[i + 1] = io.u8(w + 8 + i) end
        local result_code, save_status = io.u8(w + 0x2A), io.u8(w + 0x2B)
        local old_p, old_o = io.u32(w + 0x40), io.u32(w + 0x44)
        local new_p, new_o = io.u32(w + 0x48), io.u32(w + 0x4C)
        if io.u16(w + 0x18) ~= rev then return nil, "terminal witness changed during read" end
        if epoch == 0 or visit == 0 or io.u32(base + 0x44) ~= epoch then
            return nil, "terminal epoch changed"
        end
        if bits ~= 31 or flags ~= 3 or result_code ~= 1 or save_status ~= 1 then
            return nil, "terminal trade lacks all native scene/post-save milestones"
        end
        if seq[1] == 0 or seq[2] == 0 or seq[2] ~= seq[3] or seq[3] ~= seq[4]
           or seq[5] == 0 then return nil, "terminal milestone sequences are incomplete" end
        if old_p ~= old_pid or old_o ~= old_ot or new_p ~= new_pid or new_o ~= new_ot then
            return nil, "terminal old/received identity mismatch"
        end
        local expected = {0x54, 0x33, 0x46, 0x52}
        local function append_u32(v)
            for i = 0, 3 do expected[#expected + 1] = (v >> (8 * i)) & 0xFF end
        end
        append_u32(epoch); append_u32(visit); append_u32((~visit) & 0xFFFFFFFF)
        for i = 1, 16 do
            if token[i] ~= expected[i] then return nil, "terminal opaque native token changed" end
        end
        return {bits=bits, epoch=epoch, visit=visit, revision=rev, pre_seq=seq[1],
                scene_seq=seq[2], final_seq=seq[5], counter_before=before_counter,
                counter_after=after_counter, old_key=old_key, new_key=new_key}
    end)
    if not ok then return nil, "terminal native witness unreadable: " .. tostring(result) end
    return result, why
end

return M
