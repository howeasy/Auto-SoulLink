-- O-33 SYNTH setup only. The native Ball/capture/bonus/save path follows it.
-- No production writer or emitted event is substituted here.
local M = {}
local function hex(raw)
    local out = {}
    for i, b in ipairs(raw) do out[i] = string.format("%02x", b) end
    return table.concat(out)
end
local function unhex(value)
    if type(value) ~= "string" or #value ~= 200 or value:find("[^%da-fA-F]") then return nil end
    local out = {}
    for i = 1, #value, 2 do out[#out+1] = tonumber(value:sub(i,i+1), 16) end
    return out
end
local function equal(a, b)
    if type(a) ~= type(b) then return false end
    if type(a) ~= "table" then return a == b end
    for k, v in pairs(a) do if not equal(v, b[k]) then return false end end
    for k in pairs(b) do if a[k] == nil then return false end end
    return true
end
local function bytes(ctx, read)
    local base = ctx.enemy_base
    if type(base) ~= "number" or base % 4 ~= 0 or base < 0x02000000 or base + 100 > 0x02040000 then
        return nil, "unbound enemy record"
    end
    local out = {}
    for i = 0, 99 do out[i+1] = read(base+i) end
    return out
end
function M.snapshot(ctx, read)
    read = read or function(at) return memory.read_u8(at, "System Bus") end
    local raw, why = bytes(ctx, read)
    if not raw then return nil, why end
    local mon, bad = ctx.reader.decode_party_mon(raw)
    if not mon then return nil, bad end
    return {raw=hex(raw), key=ctx.reader.key(mon), species=mon.species, level=mon.level}
end
function M.apply(ctx, packet, read, write)
    if ctx.D.scenario ~= "shiny_bonus_gen3" or ctx.shiny_setup_applied then
        return nil, "shiny setup wrong scenario or repeated"
    end
    if not ctx.wild_ready("SYNTH shiny setup") then return nil, "shiny setup not at wild action menu" end
    read = read or function(at) return memory.read_u8(at, "System Bus") end
    write = write or function(at, value) memory.write_u8(at, value, "System Bus") end
    local before, after = unhex(packet.before), unhex(packet.after)
    local current = bytes(ctx, read)
    if not before or not after or not current or not equal(current, before) then
        return nil, "shiny setup stale or malformed preimage"
    end
    local a, b = ctx.reader.decode_party_mon(before), ctx.reader.decode_party_mon(after)
    if not a or not b or a.is_bad_egg ~= 0 or b.is_bad_egg ~= 0 or a.has_species ~= 1
       or a.is_egg ~= 0 or a.hp <= 0 or (not ctx.reader.rr and (not a.checksum_ok or not b.checksum_ok)) then
        return nil, "shiny setup invalid native record"
    end
    local old_pid, new_pid = a.personality, b.personality
    if ctx.reader.key(a) ~= packet.before_key or ctx.reader.key(b) ~= packet.after_key
       or old_pid == new_pid or old_pid % 25 ~= new_pid % 25 or (old_pid & 255) ~= (new_pid & 255) then
        return nil, "shiny setup identity/nature/gender mismatch"
    end
    local shiny = (new_pid >> 16) ~ (new_pid & 65535) ~ (b.ot_id >> 16) ~ (b.ot_id & 65535)
    a.personality, b.personality = nil, nil
    if shiny >= 8 or not equal(a,b) then return nil, "shiny setup changed unrelated record fields" end
    -- One Lua slice: no emulated frame runs between the preimage check and
    -- complete checksum/permutation-consistent record replacement.
    for i = 1, 100 do write(ctx.enemy_base+i-1, after[i]) end
    if not equal(bytes(ctx, read), after) then return nil, "shiny setup readback mismatch" end
    ctx.shiny_setup_applied = true
    return packet.after_key
end
return M
