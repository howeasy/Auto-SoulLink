-- lua/gen2/polished_boxes.lua -- Polished Crystal v3.2.3 PC storage ("newbox"): read every box, move a mon
-- into the memorial box, insert a partner's mon. Spec: docs/polished/NEWBOX.md (section refs below are its).
-- Byte for byte the same seal/verify/checksum as server/adapters/polished_codec.py, and the identity key is
-- the injected polished.lua P.mon_key (= polished_codec.key). No emulator globals; tests/unit/test_polished_boxes.py.
--
-- Layout (§1): 20 box records of 33 bytes (Entries[20] = pokedb entry 1..207 or 0, Banks[3] = bit (slot-1)
-- set -> pokedb bank 2, Name[9], Theme), a gameplay copy sNewBox1..20 and a saved copy sBackupNewBox1..20;
-- 2 pokedb banks x 207 entries of 49 bytes in sections A (1..167), B (168..195), C (196..207); WRAM allocation
-- flags wPokeDB{1,2}UsedEntries (bit e-1). A slot whose flag is clear reads as empty (§2). Box edits need no
-- save-checksum fix (§5); gameplay-record edits are volatile until the next native save (§5, LoadStorageSystem
-- copies backup -> gameplay on Continue). wCurBox plays no part in durability, so there is no current-box rule.
--
-- COORDINATES: `coords[label] = {bank, address}` (the writes.lua W.SYM shape), one row per B.COORD_LABELS
-- label, exactly the .sym values. tools/gen_polished_profile.py should emit them as profile field `newbox`
-- (a later card; not emitted yet): for each label in B.COORD_LABELS, `newbox[label] = [bank, addr]` read from
-- the overlay .sym (polished_slink.sym; identical to polishedcrystal.sym for every label here). B.new checks
-- the 0x21 record stride, the windows and that no pokedb section runs past its SRAM bank.
--
-- DOMAINS: reads are io.read_u8(offset, domain) as gen2/reads.lua's io does; writes go through the injected
-- shared write permit (lua/write_permit.lua) as `permit:write_batch` spans, so the binder's permit must
-- declare both domains. "CartRAM": flat = bank*0x2000 + addr-0xA000 (NEWBOX top note; the mapping
-- lua/gen2/boxes.lua uses). "WRAM": bank 0 = addr-0xC000, bank n = n*0x1000 + addr-0xD000, the flat Gambatte
-- domain mapping of lua/tests/test_gen2_scripted_gate.lua G.wram_offset (Gen 2 live gates use it).
-- UNVERIFIED for Polished: neither mapping has been exercised on a Polished save/state yet (NEWBOX §7).
--
-- WRITE CONTRACT (§6): every write op takes the armed permit first and refuses without one (and the permit
-- itself refuses an unarmed batch); it also refuses while wGameLogicPaused ~= 0 or sWritingBackup == 1.
-- "PC UI closed" and the overworld safe state are the caller's (no PC-open predicate is measured, §7).
-- Order: entry bytes, then the WRAM flag, then the pointer (bank bit, then Entries byte), so a torn write
-- never points at garbage. A Bad Egg (checksum mismatch) is never decoded, moved or written.
local B = {}

B.NUM_BOXES, B.MONS_PER_BOX, B.MEMORIAL_BOX = 20, 20, 20 -- memorial = box 20: NEWBOX §6.2 proposal, owner ruling open
B.ENTRY_SIZE, B.ENTRIES_PER_BANK = 49, 207
local RECORD, BANKS_AT = 0x21, 0x14
local SECTIONS = {{"A", 1, 167}, {"B", 168, 195}, {"C", 196, 207}}  -- pokemon_data_constants.asm:299 ff
local NAME_ENC = {[0x7F] = 0x7A, [0x53] = 0x7B, [0x00] = 0x7C}       -- EncodeTempMon .charmap_loop
local NAME_DEC = {[0xFA] = 0x7F, [0xFB] = 0x53, [0xFC] = 0x00}       -- DecodeTempMon, bills_pc.asm:906
local TERMINATOR = 0x53

B.COORD_LABELS = {"sBoxMons1A", "sBoxMons1B", "sBoxMons1C", "sBoxMons2A", "sBoxMons2B", "sBoxMons2C",
    "wPokeDB1UsedEntries", "wPokeDB2UsedEntries", "wGameLogicPaused", "sWritingBackup"}
for n = 1, B.NUM_BOXES do
    B.COORD_LABELS[#B.COORD_LABELS + 1] = "sNewBox" .. n
    B.COORD_LABELS[#B.COORD_LABELS + 1] = "sBackupNewBox" .. n
end

local function integer(value, low, high)
    return type(value) == "number" and value == math.floor(value) and value >= low and value <= high
end

local function bytes_ok(bytes, length)
    if type(bytes) ~= "table" or #bytes ~= length then return false end
    for i = 1, length do if not integer(bytes[i], 0, 255) then return false end end
    return true
end

local function hex(bytes, from, to)
    local out = {}
    for i = from or 1, to or #bytes do out[#out + 1] = string.format("%02x", bytes[i]) end
    return table.concat(out)
end

-- ── per-entry checksum (§3) ──────────────────────────────────────────────────
-- `e` is the 49-byte entry as stored, 1-based (e[1] = E[0]).

--- ChecksumTempMon: 127 + E[i]*(i+1) for i 0..31, + (E[i]&$7F)*(i+2) for i 32..48, mod 65536.
function B.checksum(e)
    local sum = 127
    for i = 0, 31 do sum = sum + e[i + 1] * (i + 1) end
    for i = 32, 48 do sum = sum + (e[i + 1] & 0x7F) * (i + 2) end
    return sum & 0xFFFF
end

--- .WriteChecksum: the MSB of name byte 32+k is checksum bit 15-k; E[48]'s MSB is 0. Returns a new table.
function B.seal(e)
    local sum, out = B.checksum(e), {}
    for i = 1, B.ENTRY_SIZE do out[i] = e[i] end
    for k = 0, 16 do
        local bit = k < 16 and (sum >> (15 - k)) & 1 or 0
        out[33 + k] = (out[33 + k] & 0x7F) | (bit << 7)
    end
    return out
end

--- false is what the game shows as a Bad Egg.
function B.verify(e)
    local sealed = B.seal(e)
    for i = 1, B.ENTRY_SIZE do if sealed[i] ~= e[i] then return false end end
    return true
end

--- §6.3 step 1 from a party transfer blob (48-byte party_struct + 11-byte OT field + 11-byte nickname,
--- polished.lua decode_transfer_blob's order): a sealed entry (= polished_codec.party_to_savemon).
function B.entry_from_party(blob)
    local e = {}
    for i = 1, 22 do e[i] = blob[i] end                     -- party bytes 0-21
    local ups = 0
    for i = 0, 3 do ups = ups | ((blob[23 + i] >> 6) << (2 * i)) end
    e[23] = ups                                              -- 4 PP bytes -> PPUps DDCCBBAA
    for i = 0, 5 do e[24 + i] = blob[27 + i] end             -- party 26-31 -> 23-28
    for i = 0, 2 do e[30 + i] = blob[49 + 8 + i] end         -- Extra = OT field bytes 8-10
    for i = 0, 9 do local b = blob[60 + i]; e[33 + i] = NAME_ENC[b] or b & 0x7F end
    for i = 0, 6 do local b = blob[49 + i]; e[43 + i] = NAME_ENC[b] or b & 0x7F end
    return B.seal(e)
end

local function decode_name(e, at, length)
    local out = {}
    for i = 0, length - 1 do
        local b = e[at + 1 + i] | 0x80
        out[#out + 1] = NAME_DEC[b] or b
    end
    out[#out + 1] = TERMINATOR
    return out
end

-- ── reader/writer ────────────────────────────────────────────────────────────

--- coords: {[label] = {bank, address}} for B.COORD_LABELS. io: read_u8(offset, domain).
--- mon_key: polished.lua P.mon_key. decode_text (optional): charmap bytes -> string, for nicknames.
function B.new(coords, io, mon_key, decode_text)
    if type(coords) ~= "table" then return nil, "newbox coords required" end
    if type(io) ~= "table" or type(io.read_u8) ~= "function" then return nil, "injected read_u8 required" end
    if type(mon_key) ~= "function" then return nil, "mon_key (polished.lua P.mon_key) required" end
    if decode_text ~= nil and type(decode_text) ~= "function" then return nil, "name decoder must be a function" end
    local flat, wflat = {}, {}
    local function sram(label, length)
        local row = coords[label]
        if type(row) ~= "table" or not integer(row[1], 0, 3) or not integer(row[2], 0xA000, 0xBFFF)
           or row[2] + length > 0xC000 then
            error("newbox coordinate missing or outside its SRAM bank: " .. label, 0)
        end
        flat[label] = row[1] * 0x2000 + row[2] - 0xA000
    end
    local function wram(label, length)
        local row = coords[label]
        local bank, addr = type(row) == "table" and row[1], type(row) == "table" and row[2]
        if integer(bank, 0, 0) and integer(addr, 0xC000, 0xCFFF) and addr + length <= 0xD000 then
            wflat[label] = addr - 0xC000
        elseif integer(bank, 1, 7) and integer(addr, 0xD000, 0xDFFF) and addr + length <= 0xE000 then
            wflat[label] = bank * 0x1000 + addr - 0xD000
        else
            error("newbox coordinate missing or outside its WRAM bank window: " .. label, 0)
        end
    end
    local ok, why = pcall(function()
        for n = 1, B.NUM_BOXES do
            for _, copy in ipairs({"sNewBox", "sBackupNewBox"}) do
                local label = copy .. n
                sram(label, RECORD)
                if flat[label] ~= flat[copy .. 1] + RECORD * (n - 1) then error("newbox record stride disagrees: " .. label, 0) end
            end
        end
        for d = 1, 2 do
            for _, s in ipairs(SECTIONS) do sram("sBoxMons" .. d .. s[1], (s[3] - s[2] + 1) * B.ENTRY_SIZE) end
            wram("wPokeDB" .. d .. "UsedEntries", 26)
        end
        wram("wGameLogicPaused", 1)
        sram("sWritingBackup", 1)
    end)
    if not ok then return nil, tostring(why) end

    local CART, WRAM = "CartRAM", "WRAM"
    local function rd(domain, offset)
        local value = io.read_u8(offset, domain)
        if not integer(value, 0, 255) then error("unavailable or malformed " .. domain .. " read", 0) end
        return value
    end
    local function record(copy, box) return flat[(copy == "backup" and "sBackupNewBox" or "sNewBox") .. box] end
    local function bank_byte(rec, slot) return rec + BANKS_AT + ((slot - 1) >> 3) end
    -- §2 GetStorageBoxPointer: (entry, pokedb bank) of a slot; entry 0 = empty
    local function pointer(rec, slot)
        local e = rd(CART, rec + slot - 1)
        return e, 1 + ((rd(CART, bank_byte(rec, slot)) >> ((slot - 1) & 7)) & 1)
    end
    local function entry_at(d, e)
        for _, s in ipairs(SECTIONS) do
            if e >= s[2] and e <= s[3] then return flat["sBoxMons" .. d .. s[1]] + B.ENTRY_SIZE * (e - s[2]) end
        end
        error("pokedb entry outside 1..207", 0)
    end
    local function flag_byte(d, e) return wflat["wPokeDB" .. d .. "UsedEntries"] + ((e - 1) >> 3) end
    local function flagged(d, e) return (rd(WRAM, flag_byte(d, e)) >> ((e - 1) & 7)) & 1 == 1 end
    local function read_entry(d, e)
        local at, out = entry_at(d, e), {}
        for i = 1, B.ENTRY_SIZE do out[i] = rd(CART, at + i - 1) end
        return out
    end

    -- a verified entry -> the box mon record (polished_codec.decode_savemon's field names)
    local function decode(e)
        local form_byte, personality = e[22], e[21]
        local mon = {species_id = e[1] | (((form_byte >> 5) & 1) << 8), form = form_byte & 0x1F,
            gender = form_byte & 0x80 ~= 0 and "female" or "male", is_egg = form_byte & 0x40 ~= 0,
            shiny = personality & 0x80 ~= 0, held_item = e[2], ot_id = e[7] * 256 + e[8], level = e[29],
            dv_bytes = e[18] * 65536 + e[19] * 256 + e[20], raw_hex = hex(e)}
        if mon.species_id < 1 or not integer(mon.level, 1, 100) then return nil, "invalid record species/level" end
        local nickname, ot = decode_name(e, 32, 10), decode_name(e, 42, 7)
        mon.nickname_raw_hex, mon.ot_raw_hex = hex(nickname), hex(ot)
        if decode_text then
            local okn, text = pcall(decode_text, nickname)
            if okn and type(text) == "string" then mon.nickname = text end
        end
        mon.key = mon_key(mon)
        return mon
    end

    local r = {memorial_box = B.MEMORIAL_BOX, generation = 0}

    --- §6.1: every box of one copy ("gameplay" = what the game shows, the default; "backup" = the saved
    --- copy). {copy, complete, generation, boxes[1..20] = {box, mons}, mons, bad_eggs, unflagged, invalid}.
    --- generation counts complete gameplay scans (client.lua box_generation's KEY-SCOPE-5 role) and is
    --- nil on an incomplete one: a corrupt pointer or an invalid record makes the census incomplete.
    function r.read_boxes(copy)
        local okr, result = pcall(function()
            local snap = {copy = copy == "backup" and "backup" or "gameplay", complete = true, boxes = {}, mons = {},
                          bad_eggs = {}, unflagged = {}, invalid = {}}
            for box = 1, B.NUM_BOXES do
                local rec, list = record(snap.copy, box), {}
                for slot = 1, B.MONS_PER_BOX do
                    local e, d = pointer(rec, slot)
                    local where = {box = box, slot = slot, bank = d, entry = e}
                    if e > B.ENTRIES_PER_BANK then
                        where.reason = "corrupt pointer"
                        snap.invalid[#snap.invalid + 1], snap.complete = where, false
                    elseif e ~= 0 and not flagged(d, e) then
                        snap.unflagged[#snap.unflagged + 1] = where   -- the game shows an empty slot
                    elseif e ~= 0 then
                        local raw = read_entry(d, e)
                        if not B.verify(raw) then
                            where.bad_egg = true                       -- never decoded
                            snap.bad_eggs[#snap.bad_eggs + 1] = where
                        else
                            local mon, why = decode(raw)
                            if mon then
                                mon.box, mon.slot, mon.bank, mon.entry = box, slot, d, e
                                list[#list + 1] = mon
                                snap.mons[#snap.mons + 1] = mon
                            else
                                where.reason = why
                                snap.invalid[#snap.invalid + 1], snap.complete = where, false
                            end
                        end
                    end
                end
                snap.boxes[box] = {box = box, mons = list}
            end
            if snap.complete and snap.copy == "gameplay" then
                r.generation = r.generation + 1
                snap.generation = r.generation
            end
            return snap
        end)
        if not okr then return nil, tostring(result) end
        return result
    end

    local function refuse(why) error(why, 0) end
    local function gated(permit)
        if type(permit) ~= "table" or type(permit.write_batch) ~= "function" or not permit.armed then
            refuse("write refused: no armed write window")
        end
        if rd(WRAM, wflat.wGameLogicPaused) ~= 0 then refuse("game logic paused (native save running)") end
        if rd(CART, flat.sWritingBackup) == 1 then refuse("backup save in progress") end
    end
    local function free_slot(rec)
        for slot = 1, B.MONS_PER_BOX do if rd(CART, rec + slot - 1) == 0 then return slot end end
    end
    -- the bank-bit span of an EMPTY slot (its old bit is junk, §1.1); written before its Entries byte
    local function bank_span(rec, slot, d)
        local at, bit = bank_byte(rec, slot), 1 << ((slot - 1) & 7)
        local old = rd(CART, at)
        return {domain = CART, addr = at, bytes = {d == 2 and (old | bit) or (old & ~bit & 0xFF)}}
    end
    local function wrap(fn)
        return function(...)
            local okw, result = pcall(fn, ...)
            if okw then return result end
            return nil, tostring(result)
        end
    end

    --- §6.2: pointer move of gameplay (box, slot) into the first empty slot of box 20. No pokedb or flag
    --- write. Volatile until the next native save: a reset reverts both halves together (never a loss).
    r.move_to_memorial = wrap(function(permit, box, slot)
        gated(permit)
        if not integer(box, 1, B.NUM_BOXES - 1) then refuse("source box outside 1..19") end
        if not integer(slot, 1, B.MONS_PER_BOX) then refuse("slot outside 1..20") end
        local src = record("gameplay", box)
        local e, d = pointer(src, slot)
        if e == 0 then refuse("empty slot") end
        if e > B.ENTRIES_PER_BANK then refuse("corrupt pointer") end
        if not flagged(d, e) then refuse("unflagged entry (the game shows an empty slot)") end
        if not B.verify(read_entry(d, e)) then refuse("bad egg (checksum mismatch) is never moved") end
        local mem = record("gameplay", B.MEMORIAL_BOX)
        local m = free_slot(mem)
        if not m then refuse("memorial box full") end
        permit:write_batch({bank_span(mem, m, d), {domain = CART, addr = mem + m - 1, bytes = {e}},
                            {domain = CART, addr = src + slot - 1, bytes = {0}}})
        return {box = B.MEMORIAL_BOX, slot = m, from_box = box, from_slot = slot, bank = d, entry = e,
                durability = "VOLATILE_UNTIL_NATIVE_SAVE"}
    end)

    --- §6.3: `bytes` = a 49-byte sealed entry (verified, never re-sealed) or a 70-byte party transfer blob
    --- (built + sealed here). Picks the first free pokedb entry (bank 1 then 2, flag clear and no record of
    --- either copy pointing at it), writes it, sets its flag, then points the first empty slot of `box` at it.
    --- The gameplay record only: a reset before the next native save drops the mon (backup mirror: not done).
    r.insert_mon = wrap(function(permit, box, bytes)
        gated(permit)
        if not integer(box, 1, B.NUM_BOXES) then refuse("box outside 1..20") end
        local e
        if bytes_ok(bytes, B.ENTRY_SIZE) then
            if not B.verify(bytes) then refuse("entry checksum mismatch (the game would show a Bad Egg)") end
            e = {}
            for i = 1, B.ENTRY_SIZE do e[i] = bytes[i] end
        elseif bytes_ok(bytes, 70) then
            e = B.entry_from_party(bytes)
        else
            refuse("49-byte entry or 70-byte party blob required")
        end
        local mon, why = decode(e)
        if not mon then refuse(why) end
        local rec = record("gameplay", box)
        local s = free_slot(rec)
        if not s then refuse("box full") end
        local referenced = {{}, {}}
        for _, copy in ipairs({"gameplay", "backup"}) do
            for b = 1, B.NUM_BOXES do
                for slot = 1, B.MONS_PER_BOX do
                    local pe, pd = pointer(record(copy, b), slot)
                    if pe ~= 0 then referenced[pd][pe] = true end
                end
            end
        end
        local d, entry
        for bank = 1, 2 do
            for i = 1, B.ENTRIES_PER_BANK do
                if not referenced[bank][i] and not flagged(bank, i) then d, entry = bank, i; break end
            end
            if d then break end
        end
        if not d then refuse("no free pokedb entry: native save required") end
        local fb = flag_byte(d, entry)
        permit:write_batch({{domain = CART, addr = entry_at(d, entry), bytes = e},
                            {domain = WRAM, addr = fb, bytes = {rd(WRAM, fb) | (1 << ((entry - 1) & 7))}},
                            bank_span(rec, s, d), {domain = CART, addr = rec + s - 1, bytes = {entry}}})
        return {box = box, slot = s, bank = d, entry = entry, key = mon.key,
                durability = "VOLATILE_UNTIL_NATIVE_SAVE"}
    end)

    return r
end

return B
