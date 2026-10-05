-- lua/gen2/polished_overworld.lua -- the Polished Crystal v3.2.3 OVERWORLD write path: the hold, the armed
-- writer and the box executor compose_polished wires in (lua/gen2/entry.lua C-COMPOSE).
--
-- WHY A PREDICATE HOLD AND NOT A PC HOLD. The vanilla Gen 2 client writes inside a bus-exec hold at the
-- checkpoint PC (OWPlayerInput, before `call CheckAPressOW`), because that is where the U2 PHYSICAL receipt
-- proved a write lands. Polished has no such PC: data/games/polished_crystal/write_checkpoint.json
-- titles.polished_crystal.primary is {"status": "UNRESOLVED", "execution_before": null} (OverworldLoop
-- 25:50d5 is the right neighbourhood, but no execution_before instruction was re-derived). Nothing here may
-- invent one. So the hold is a PREDICATE hold, evaluated in the same frame as the write, from the live
-- bytes the game itself uses (docs/polished/HELLO_GATE.md §1, docs/polished/LIVE_RESULTS.md gate_transitions):
--   wMapStatus == MAPSTATUS_HANDLE (2)  OverworldLoop runs, not the title/menu/map load
--   wScriptRunning == 0                 no script owns the game
--   wGameLogicPaused == 0               no native save is running
--   wBattleMode == 0                    not in a battle
--   wLinkMode == 0                      not on a link cable
--   sWritingBackup != 1                 no backup save in progress (CartRAM)
-- plus: the WRAM bank that owns the party is the mapped one (io.bank_valid), the permit's lifetime token is
-- the frame count (a write that crosses a frame refuses), and every write is verified by reading it back.
-- This is strictly weaker than a CPU hold: it proves the engine is between frames and idle, not that the CPU
-- sits at a proven instruction. Recorded as DEV_OVERLAY_PREDICATE_HOLD, never as a receipt.
--
-- DECLARED WRITES (and nothing else):
--   System Bus  the party block wPartyCount..wPartyMonNicknamesEnd (01:DCCE..01:DE7A, bank 1); for a faint,
--               that one record's Status (+32) and HP (+34..35) bytes.
--   CartRAM     the six newbox pokedb sections and the 20 GAMEPLAY box records (sNewBox1..20; the backup
--               copies are never writable) - NEWBOX §1.
--   WRAM        the two pokedb allocation-flag windows wPokeDB{1,2}UsedEntries - NEWBOX §2.
-- wMirrorHerbPendingBoosts (01:D284) is asserted disjoint from the party block and never appears in a range.
--
-- BOX OPS. deposit() is the vanilla box_mon contract (party -> a newbox box) built on Polished's own two
-- halves: the engine deposits by erasing the target box pointer, allocating a pokedb entry, writing it and
-- repointing the slot (UpdateStorageBoxMonFromTemp, engine/pc/bills_pc.asm:495-531), and removes a party mon
-- by shifting its slot to the end and decrementing wPartyCount (RemoveMonFromParty -> ShiftPartySlotToEnd ->
-- SwapPartyMons, bills_pc.asm:539-623). This module runs the box half first, so a reset between the halves
-- leaves a duplicate, never a loss. withdraw() and memorialize() are refused by name, not stubbed: see below.
local O = {}

-- The composed write kinds. "party_hp" is the name lua/gen2/client.lua asks for before it runs ANY deferred
-- command (run_deferred / at_checkpoint, the vanilla U2 kind name): it means "the overworld hold", nothing
-- more specific. The other three are what a writer authorizes, one per declared range set.
O.KINDS = {party_hp = true, party_faint = true, party_collection = true, box_deposit = true}
-- lua/gen2/client.lua run_deferred arms the faint write with this reason
O.FAINT_REASON = "overworld"
O.MAPSTATUS_HANDLE = 2            -- constants/ram_constants.asm:207-210 (HELLO_GATE.md §1)
O.QUALIFICATION = "DEV_OVERLAY_PREDICATE_HOLD"
-- sWritingBackup 00:ABE5 -> flat CartRAM (the same byte lua/gen2/polished_boxes.lua refuses on)
O.SAVING = {bank = 0, addr = 0xABE5}
-- THE HOLD SITE: `call DelayFrame` inside NextOverworldFrame (engine/overworld/events.asm:99 calls it, :114
-- defines it; the routine is 25:5185..25:51D7). It is the idle-overworld frame wait: the overworld loop reaches it
-- once per frame after MapEvents and HandleMapObjects, so a write here is between frames, out of any script that
-- has already run, and BEFORE the next frame's MapEvents (a script cannot start and finish between two of these).
-- `call z, DelayFrame` = cc a8 0d (DelayFrame 00:0DA8); that byte triple occurs ONCE in the routine - verified
-- over the built ROM by tests/unit/test_polished_write_path.py, which also re-derives both addresses from
-- data/polished/polished_slink.sym and re-reads the bytes through the executed (overlay) ROM.
O.HOLD = {bank = 0x25, pc = 0x51BF, bytes = {0xCC, 0xA8, 0x0D},
          routine = "NextOverworldFrame", routine_start = 0x5185, routine_end = 0x51D7,
          instruction = "call z, DelayFrame"}
-- The armed reason -> the kind the hold is asked for. arm() re-checks the predicate: a permit armed for a box
-- write must not be usable in a frame the hold refuses (round-2 review item 5: the box path writes through the
-- permit directly, so authorize() alone never saw it).
O.KIND_OF_REASON = {[O.FAINT_REASON] = "party_hp", party_collection = "party_collection", box_deposit = "box_deposit"}

local function integer(value, low, high)
    return type(value) == "number" and value == math.floor(value) and value >= low and value <= high
end

local function saving_byte(io)
    local at = O.SAVING
    local value = io.read_u8(at.bank * 0x2000 + at.addr - 0xA000, "CartRAM")
    return integer(value, 0, 255) and value or nil
end

-- ── the hold ────────────────────────────────────────────────────────────────────────────────────────────

--- The overworld hold. check(kind) re-reads the whole predicate set every time it is asked, so a caller
--- cannot cache an accept across frames. covers(kind) is what this graph is allowed to do at all.
--- site (optional): {bank, pc, bytes, routine, routine_start, routine_end}. When given, the hold additionally
--- requires that the CPU is executing THAT instruction in THAT bank, re-read at check time (i.e. at the moment the
--- hook fires, because the client's checkpoint hook calls check() synchronously inside the exec callback).
function O.checkpoint(profile, io, log, site)
    assert(type(profile) == "table" and profile.title == "polished" and type(profile.ram) == "table",
           "generated Polished profile required")
    assert(type(io) == "table" and type(io.read_u8) == "function" and type(io.bank_valid) == "function"
           and type(io.read_range) == "function", "explicit read_u8/read_range/bank_valid required")
    local ram, banks, hram = profile.ram, profile.ram_bank, profile.hram
    -- an HRAM register (hROMBank) is in the profile's hram table, always bank 0
    local function byte(name)
        local at, bank = ram[name], banks[name]
        local hram_at = (hram ~= nil) and hram[name] or nil
        if at == nil and hram_at ~= nil then at, bank = hram_at, 0 end
        -- WRAM ($C000-$DFFF) or HRAM ($FF80-$FFFF, bank 0): hROMBank is an HRAM register
        local wram = integer(at, 0xC000, 0xDFFF)
        local hram_window = integer(at, 0xFF80, 0xFFFF) and bank == 0
        if not (wram or hram_window) or not integer(bank, 0, 7) then return nil, "missing " .. name end
        if io.bank_valid(bank, at, 1) ~= true then return nil, name .. " bank not mapped" end
        return io.read_u8(at, "System Bus")
    end
    if site ~= nil then
        assert(integer(site.bank, 1, 0x7F) and integer(site.pc, 0x4000, 0x7FFF) and type(site.bytes) == "table",
               "a hold site needs a bank, a PC and its instruction bytes")
        assert(type(site.routine_start) == "number" and site.routine_start <= site.pc
               and site.pc + #site.bytes <= site.routine_end, "the hold site must lie inside its named routine")
        for i, byte in ipairs(site.bytes) do assert(integer(byte, 0, 255), "hold site byte out of range") end
    end
    local last
    local function refuse(why)
        if log and last ~= why then
            last = why
            log("[SLink-gen2] overworld write refused: " .. tostring(why))
        end
        return false, why
    end
    local self = {qualification = O.QUALIFICATION, facts = {}}
    function self:covers(kind) return O.KINDS[kind] == true end
    function self:check(kind)
        if not self:covers(kind) then return refuse("no composed Polished write kind " .. tostring(kind)) end
        for _, name in ipairs({"wMapStatus", "wScriptRunning", "wGameLogicPaused", "wBattleMode", "wLinkMode"}) do
            local value, why = byte(name)
            if value == nil then return refuse(why) end
            self.facts[name] = value
        end
        if self.facts.wMapStatus ~= O.MAPSTATUS_HANDLE then
            return refuse("overworld loop not running (wMapStatus $" .. string.format("%02X", self.facts.wMapStatus) .. ")")
        end
        if self.facts.wScriptRunning ~= 0 then return refuse("a script owns the game (wScriptRunning)") end
        if self.facts.wGameLogicPaused ~= 0 then return refuse("native save running (wGameLogicPaused)") end
        if self.facts.wBattleMode ~= 0 then
            return refuse("in battle (wBattleMode $" .. string.format("%02X", self.facts.wBattleMode) .. ")")
        end
        if self.facts.wLinkMode ~= 0 then return refuse("link cable active (wLinkMode)") end
        local saving = saving_byte(io)
        if saving == nil then return refuse("sWritingBackup unreadable") end
        if saving == 1 then return refuse("backup save in progress (sWritingBackup)") end
        -- the PC hold, when one is composed: the executing bank must be the site's bank and the executed bytes
        -- must still be the instruction (a patched/relocated ROM never holds the write)
        if site ~= nil then
            local rom_bank, bank_why = byte("hROMBank")
            if rom_bank == nil then return refuse(bank_why) end
            if rom_bank ~= site.bank then
                return refuse("not at the " .. site.routine .. " hold (hROMBank $" .. string.format("%02X", rom_bank) .. ")")
            end
            -- the ROM domain is addressed by its LINEAR offset, not the banked bus address
            local rom_at = site.bank * 0x4000 + (site.pc - 0x4000)
            for i, expected in ipairs(site.bytes) do
                local got = io.read_u8(rom_at + i - 1, "ROM")
                if got ~= expected then
                    return refuse("hold site bytes differ at " .. string.format("%02X:%04X", site.bank, site.pc)
                                  .. " (patched ROM)")
                end
            end
        end
        last = nil
        return true, kind
    end
    return self
end

-- ── the writer ─────────────────────────────────────────────────────────────────────────────────────────

--- coords: polished_boxes.lua's B.COORD_LABELS map ({bank, address}), exactly P.newbox_coords().
--- policy: the vanilla write_policy shape {authorize(operation, request), pointer_stable(token, addr, n),
---          provenance(domain, addr, n, reason, token), lifetime = {capture, valid}}.
function O.writes(profile, coords, io, Permit, policy, hold)
    assert(type(profile) == "table" and profile.title == "polished", "generated Polished profile required")
    assert(Permit and type(Permit.new) == "function" and type(Permit.sequence_length) == "function",
           "shared write permit factory required")
    assert(type(io) == "table" and type(io.write_u8) == "function" and type(io.read_u8) == "function"
           and type(io.bank_valid) == "function" and type(io.read_range) == "function",
           "explicit write_u8/read_u8/read_range/bank_valid required")
    assert(type(policy) == "table", "explicit ownership policy required")
    for _, name in ipairs({"authorize", "pointer_stable", "provenance"}) do
        assert(type(policy[name]) == "function", "explicit policy." .. name .. " required")
    end
    assert(type(policy.lifetime) == "table" and type(policy.lifetime.capture) == "function"
           and type(policy.lifetime.valid) == "function", "explicit lifetime capture/valid required")
    local c, s, ram, banks = profile.constants, profile.structs.party, profile.ram, profile.ram_bank
    assert(c.PARTY_LENGTH == 6 and c.NAME_LENGTH == 11 and c.MON_NAME_LENGTH == 11, "Polished party constants")
    assert(s.End == 48 and s.Status == 32 and s.HP == 34, "party_struct geometry disagrees (RAM.md §2.1)")

    -- the party block, and the derived sub-offsets (the same derivation lua/gen2/polished.lua makes)
    local block, base, bank = ram.wPartyCount, ram.wPartyMons, banks.wPartyMons
    local mons_at = base - block
    local ots_at = mons_at + c.PARTY_LENGTH * s.End
    local nicks_at = ots_at + c.PARTY_LENGTH * c.NAME_LENGTH
    local block_length = nicks_at + c.PARTY_LENGTH * c.MON_NAME_LENGTH
    assert(integer(block, 0xC000, 0xDFFF) and integer(base, 0xC000, 0xDFFF) and integer(bank, 1, 7)
           and mons_at > 0 and ram.wPartyMonOTs == block + ots_at and ram.wPartyMonNicknames == block + nicks_at
           and ram.wPartyMonNicknamesEnd == block + block_length and banks.wPartyCount == bank
           and block >= 0xD000 and block + block_length <= 0xE000,
           "party block geometry disagrees with the profile")
    -- wMirrorHerbPendingBoosts is the ENEMY party's gap; it must never be inside a declared party span
    local herb = ram.wMirrorHerbPendingBoosts
    if herb ~= nil then
        assert(not (herb < block + block_length and herb + 1 > block),
               "party block overlaps wMirrorHerbPendingBoosts")
    end

    -- the newbox spans, in the flat domains polished_boxes.lua writes (CartRAM bank*0x2000 + addr-0xA000,
    -- WRAM bank*0x1000 + addr-0xD000). Declared here so the permit can refuse anything outside them.
    local SECTIONS = {{"sBoxMons1A", 167}, {"sBoxMons1B", 28}, {"sBoxMons1C", 12},
                      {"sBoxMons2A", 167}, {"sBoxMons2B", 28}, {"sBoxMons2C", 12}}
    local spans = {CartRAM = {}, WRAM = {}}
    local function cart_span(label, length)
        local row = coords[label]
        assert(type(row) == "table" and integer(row[1], 0, 3) and integer(row[2], 0xA000, 0xBFFF)
               and row[2] + length <= 0xC000, "newbox coordinate missing or outside its SRAM bank: " .. label)
        spans.CartRAM[#spans.CartRAM + 1] = {at = row[1] * 0x2000 + row[2] - 0xA000, n = length}
    end
    local function wram_span(label, length)
        local row = coords[label]
        assert(type(row) == "table" and integer(row[1], 0, 7) and integer(row[2], 0xD000, 0xDFFF)
               and row[2] + length <= 0xE000, "newbox coordinate missing or outside its WRAM window: " .. label)
        spans.WRAM[#spans.WRAM + 1] = {at = row[1] * 0x1000 + row[2] - 0xD000, n = length}
    end
    for _, section in ipairs(SECTIONS) do cart_span(section[1], section[2] * 49) end
    for n = 1, 20 do cart_span("sNewBox" .. n, 33) end
    for d = 1, 2 do wram_span("wPokeDB" .. d .. "UsedEntries", 26) end

    local function inside(list, addr, n)
        for _, span in ipairs(list) do
            if addr >= span.at and addr + n <= span.at + span.n then return true end
        end
        return false
    end

    -- the declared System Bus ranges, per armed reason
    local ranges = {[O.FAINT_REASON] = {}, party_collection = {{addr = block, n = block_length, bank = bank}}}
    for slot = 0, c.PARTY_LENGTH - 1 do
        local at = base + slot * s.End
        table.insert(ranges[O.FAINT_REASON], {addr = at + s.Status, n = 1, bank = bank})
        table.insert(ranges[O.FAINT_REASON], {addr = at + s.HP, n = 2, bank = bank})
    end
    local function declared(reason, addr, n)
        for _, r in ipairs(ranges[reason] or {}) do
            if addr >= r.addr and addr + n <= r.addr + r.n then return r end
        end
    end
    local function permitted(reason, addr, n)
        if declared(reason, addr, n) then return true end
        return reason == "box_deposit" and (inside(spans.CartRAM, addr, n) or inside(spans.WRAM, addr, n))
    end

    local gate = Permit.new({
        write_u8 = io.write_u8,
        domains = {
            ["System Bus"] = {
                bounds = function(addr, n, reason) return permitted(reason, addr, n) == true end,
                mapped = function(addr, n, reason)
                    local r = declared(reason, addr, n)
                    return r ~= nil and io.bank_valid(r.bank, addr, n) == true
                end,
                pointer_stable = function(addr, n, _reason, token)
                    return policy.pointer_stable(token, addr, n) == true
                end,
            },
            CartRAM = {
                bounds = function(addr, n, reason) return reason == "box_deposit" and inside(spans.CartRAM, addr, n) end,
                mapped = function(addr, n, reason) return reason == "box_deposit" and inside(spans.CartRAM, addr, n) end,
                pointer_stable = function(addr, n, _reason, token)
                    return policy.pointer_stable(token, addr, n) == true
                end,
            },
            WRAM = {
                bounds = function(addr, n, reason) return reason == "box_deposit" and inside(spans.WRAM, addr, n) end,
                mapped = function(addr, n, reason) return reason == "box_deposit" and inside(spans.WRAM, addr, n) end,
                pointer_stable = function(addr, n, _reason, token)
                    return policy.pointer_stable(token, addr, n) == true
                end,
            },
        },
        lifetime = {
            capture = policy.lifetime.capture,
            valid = function(token, reason) return policy.lifetime.valid(token, reason) == true end,
        },
        provenance = function(domain, addr, n, reason, token)
            local supplied = policy.provenance(domain, addr, n, reason, token)
            assert(type(supplied) == "table" and type(supplied.site) == "string" and supplied.site ~= "",
                   "write-site provenance required")
            local receipt = {}
            for key, value in pairs(supplied) do receipt[key] = value end
            receipt.domain, receipt.addr, receipt.n, receipt.why = domain, addr, n, reason
            receipt.title, receipt.artifact, receipt.rom_sha1 = profile.title, profile.artifact, profile.rom_sha1
            return receipt
        end,
    })

    local self = setmetatable({}, {__index = function(_, key)
        if key == "armed" or key == "log" then return gate[key] end
    end})
    -- arm re-proves the hold. The box path writes through the permit directly (polished_boxes.lua insert_mon),
    -- so without this the box bytes would never see the predicate set at all.
    function self:arm(reason, allow)
        assert(hold, "the writer needs the hold it re-checks on arm")
        local kind = O.KIND_OF_REASON[reason]
        assert(kind ~= nil, "no composed Polished write kind for the armed reason " .. tostring(reason))
        local ok, why = hold:check(kind)
        assert(ok == true, "write refused at arm(" .. tostring(reason) .. "): " .. tostring(why))
        return gate:arm(reason, allow)
    end
    function self:disarm() return gate:disarm() end
    function self:write_batch(spans_) return gate:write_batch(spans_) end
    function self:block() return block, block_length, mons_at, ots_at, nicks_at end

    local function wram(addr, n)
        assert(io.bank_valid(bank, addr, n) == true, "party WRAM bank unavailable")
        local out = io.read_range(addr, n, "System Bus")
        for i = 1, n do assert(integer(out[i], 0, 255), "unavailable or malformed System Bus read") end
        return out
    end
    local function be16(bytes, at) return bytes[at] * 256 + bytes[at + 1] end

    -- force_faint: the keyed record's HP to 0 and its Status byte to 0 (what the vanilla writer writes,
    -- lua/gen2/writes.lua faint_party_slot - a Gen 2 mon is fainted by HP 0; there is no FNT status bit).
    -- Refused unless the overworld hold authorized this operation, then both bytes are proven by read-back.
    function self:faint_party_slot(slot, snapshot)
        return gate:guard(function()
            assert(integer(slot, 0, c.PARTY_LENGTH - 1), "party slot out of range")
            assert(gate.armed == O.FAINT_REASON, "write refused: the faint gate is not armed")
            assert(snapshot == nil or (type(snapshot) == "table" and integer(snapshot.mode, 0, 255)),
                   "explicit battle snapshot required")
            assert(snapshot == nil or snapshot.mode == 0,
                   "an in-battle faint is not composed (no battle_hold receipt on Polished)")
            assert(snapshot == nil or snapshot.link_mode == nil or snapshot.link_mode == 0,
                   "linked or unknown battle context refused")
            assert(policy.authorize("party_faint", {slot = slot, snapshot = snapshot}) == true,
                   "write ownership refused")
            local at = base + slot * s.End
            local was = {status = wram(at + s.Status, 1)[1], hp = be16(wram(at + s.HP, 2), 1)}
            gate:write_batch({
                {domain = "System Bus", addr = at + s.Status, bytes = {0}},
                {domain = "System Bus", addr = at + s.HP, bytes = {0, 0}},
            })
            local now = {status = wram(at + s.Status, 1)[1], hp = be16(wram(at + s.HP, 2), 1)}
            assert(now.status == 0 and now.hp == 0,
                   "read-back refused: the party record still holds HP/status")
            return {slot = slot, hp_before = was.hp, status_before = was.status}
        end)
    end

    -- the whole party block, for a deposit's compaction (RemoveMonFromParty's shift and decrement)
    function self:write_party_block(bytes)
        return gate:guard(function()
            assert(Permit.sequence_length(bytes, "party block") == block_length, "party block length mismatch")
            assert(policy.authorize("party_collection", {length = block_length}) == true,
                   "write ownership refused")
            gate:write_batch({{domain = "System Bus", addr = block, bytes = bytes}})
            local after = wram(block, block_length)
            for i = 1, block_length do
                assert(after[i] == bytes[i], "read-back refused: the party block did not take the write")
            end
            return true
        end)
    end
    return self
end

-- ── the box executor (box_mon) ───────────────────────────────────────────────────────────────────────────

--- deps = {profile, reads, census, boxes (the polished_boxes.lua MODULE), reader (one B.new over the same
---         coordinates), writes, log}
function O.boxes(deps)
    assert(type(deps) == "table", "box executor deps required")
    local profile, reads, census = deps.profile, deps.reads, deps.census
    local Boxes, reader, writes = deps.boxes, deps.reader, deps.writes
    assert(type(reads) == "table" and type(reads.read_party) == "function", "reads.read_party required")
    assert(type(census) == "table" and type(census.read_storage_box) == "function", "a box census reader required")
    assert(type(Boxes) == "table", "the polished_boxes.lua module required")
    assert(type(reader) == "table" and type(reader.insert_mon) == "function", "a polished_boxes.lua reader required")
    assert(type(writes) == "table" and type(writes.arm) == "function", "the overworld writer required")
    local mail = deps.mail or {}
    local c, s = profile.constants, profile.structs.party
    local MEMORIAL, PER_BOX = Boxes.MEMORIAL_BOX, Boxes.MONS_PER_BOX
    local _, block_length, mons_at, ots_at, nicks_at = writes:block()
    local STRIDE = s.End + c.NAME_LENGTH + c.MON_NAME_LENGTH

    local function refuse(why) error(why, 0) end
    local function from_hex(h)
        local out = {}
        for i = 1, #h, 2 do out[#out + 1] = tonumber(h:sub(i, i + 1), 16) end
        return out
    end
    local function party_block()
        local r = reads.read_party()
        if not r then refuse("party unreadable") end
        local raw = from_hex(r.raw_hex)
        if #raw ~= block_length then refuse("party block length disagrees with the profile") end
        return r, raw
    end
    -- the 70-byte transfer blob, straight from the live block (never re-encoded)
    local function blob_of(raw, slot)
        local out = {}
        for i = 1, s.End do out[i] = raw[mons_at + slot * s.End + i] end
        for i = 1, c.NAME_LENGTH do out[s.End + i] = raw[ots_at + slot * c.NAME_LENGTH + i] end
        for i = 1, c.MON_NAME_LENGTH do
            out[s.End + c.NAME_LENGTH + i] = raw[nicks_at + slot * c.MON_NAME_LENGTH + i]
        end
        return out
    end
    -- RemoveMonFromParty's compaction: every byte from the removed slot's record to the end of the block
    -- shifts up one slot, and the count drops by one (raw is 1-based: byte offset 0 is wPartyCount, so the
    -- removed slot's first byte is raw[mons_at + slot * STRIDE + 1]). Bytes past the new count are not read
    -- by anything; the engine's ShiftPartySlotToEnd leaves the same tail it brought.
    local function removed(raw, slot)
        local out = {}
        for i = 1, #raw do out[i] = raw[i] end
        -- three parallel arrays, three strides: records (48), OT fields (11), nicknames (11). Each slot from the
        -- removed one takes its successor's bytes; the vacated tail keeps what the shift brought (the engine's
        -- ShiftPartySlotToEnd leaves the same tail). Bytes past the new count are read by nothing.
        local first = {mons_at + slot * s.End, ots_at + slot * c.NAME_LENGTH, nicks_at + slot * c.MON_NAME_LENGTH}
        local width = {s.End, c.NAME_LENGTH, c.MON_NAME_LENGTH}
        local limit = {first[1] + (c.PARTY_LENGTH - slot) * s.End, first[2] + (c.PARTY_LENGTH - slot) * c.NAME_LENGTH,
                       first[3] + (c.PARTY_LENGTH - slot) * c.MON_NAME_LENGTH}
        for array = 1, 3 do
            local from = first[array]
            for i = from, limit[array] - width[array] do out[i] = raw[i + width[array]] end
        end
        out[1] = raw[1] - 1
        return out
    end
    -- the 20-box walk the client already does, as one complete census or nothing
    local function scan()
        local boxes = {}
        for index = 0, c.NUM_BOXES - 1 do
            local read, why = census.read_storage_box(index)
            if not read then return nil, why or ("box " .. (index + 1) .. " unreadable") end
            boxes[index + 1] = read.mons or {}
        end
        return boxes
    end
    local function find_key(list, key)
        local hit
        for _, mon in ipairs(list) do
            if mon.key == key then
                if hit then return nil, "ambiguous duplicate key" end
                hit = mon
            end
        end
        return hit
    end

    local self = {memorial_box = MEMORIAL, qualification = O.QUALIFICATION}

    --- box_mon. true, note on success; nil, why on refusal. Never raises.
    function self.deposit(key)
        local okr, result, note = pcall(function()
            local boxes, why = scan()
            if not boxes then refuse("box census incomplete: " .. tostring(why)) end
            local party, raw = party_block()
            local slot, mon = nil, nil
            for _, m in ipairs(party.mons) do
                if m.key == key and not m.is_egg then
                    if slot then refuse("ambiguous duplicate key") end
                    slot, mon = m.slot, m
                end
            end
            if not slot then refuse("key not in party") end
            if party.count <= 1 then refuse("last party mon") end
            -- SwapPartyMons swaps sPartyMon1Mail with the mon (DoMailSwap, engine/pc/bills_pc.asm:289-297:
            -- MAIL_STRUCT_LENGTH = $2f bytes per slot), and SLink never rewrites that SRAM block. So a removal
            -- refuses while the removed mon OR ANY LATER party slot holds Mail (ItemIsMail, home/header.asm:114:
            -- item >= FIRST_MAIL) - the vanilla rule (lua/gen2/boxes.lua no_mail_from). Mirroring the swap instead
            -- would mean declaring a 6 x $2f-byte SRAM range this writer never populates.
            for _, later in ipairs(party.mons) do
                if later.slot >= slot and mail[later.held_item] then
                    refuse("party mail in the party (slot " .. later.slot .. " holds item "
                           .. tostring(later.held_item) .. "; sPartyMail is never shifted, T-3)")
                end
            end
            local box, refusal = nil, "no free box slot"
            for index = 1, c.NUM_BOXES do
                if index ~= MEMORIAL then
                    local hit = find_key(boxes[index], key)
                    if hit then refuse("key already boxed (box " .. index .. " slot " .. hit.slot .. ")") end
                    if not box and #boxes[index] < PER_BOX then box = index end
                end
            end
            if not box then refuse(refusal) end
            -- the box half first (the engine's own order), so a reset between the halves duplicates, never loses
            writes:arm("box_deposit")
            local boxed, placed, bwhy = pcall(function() return reader.insert_mon(writes, box, blob_of(raw, slot)) end)
            writes:disarm()
            if not boxed then refuse("box write refused: " .. tostring(placed)) end
            if not placed then refuse("box " .. box .. " refused the deposit: " .. tostring(bwhy)) end
            writes:arm("party_collection")
            local dropped, dwhy = pcall(function() return writes:write_party_block(removed(raw, slot)) end)
            writes:disarm()
            if not dropped then refuse("party compaction refused: " .. tostring(dwhy)) end
            -- READ-BACK 1: the party. The count dropped by one and the key is gone from it.
            local after = reads.read_party()
            if not after then refuse("read-back refused: the party became unreadable") end
            if after.count ~= party.count - 1 then
                refuse("read-back refused: party count " .. party.count .. " -> " .. tostring(after.count))
            end
            for _, m in ipairs(after.mons) do
                if m.key == key then refuse("read-back refused: the mon is still in the party") end
            end
            -- READ-BACK 2: the box. A fresh census re-reads the pointer byte, the WRAM allocation flag and the
            -- pokedb entry itself, and a bad checksum / unflagged pointer / corrupt pointer makes it
            -- incomplete (polished.lua P.census) - so this proves the entry the game will decode.
            local after_boxes, cwhy = scan()
            if not after_boxes then refuse("read-back refused: the census no longer completes (" .. tostring(cwhy) .. ")") end
            local found = find_key(after_boxes[box], key)
            if not found then refuse("read-back refused: box " .. box .. " does not read the mon back") end
            -- the census reports slots 0-based (client.lua's box_entry contract), insert_mon reports them 1-based
            if found.slot + 1 ~= placed.slot or found.bank ~= placed.bank or found.entry ~= placed.entry then
                refuse("read-back refused: box " .. box .. " slot " .. tostring(found.slot + 1)
                       .. " entry " .. tostring(found.bank) .. "/" .. tostring(found.entry)
                       .. " is not the written one")
            end
            return true, {box = box, slot = placed.slot, entry = placed.entry, bank = placed.bank,
                          durability = placed.durability, nickname = mon.nickname}
        end)
        if okr then return result, note end
        return nil, tostring(result)
    end

    -- Not composed, refused by name rather than stubbed:
    --  * party_mon needs the savemon -> party_struct direction, and a party record's stats and PP are not in
    --    the savemon: they are reconstructed (CalcPkmnStats predef, engine/pc/bills_pc.asm:923, and PP from
    --    the PPUps byte + the move's base PP). No receipt proves that arithmetic here, and a wrong stat is a
    --    silently corrupt mon, so it refuses instead.
    --  * memorialize targets the memorial box, and NEWBOX §6.2 leaves that choice an OPEN owner ruling.
    function self.withdraw()
        return nil, "Polished party_mon is not composed: savemon->party stat/PP reconstruction unqualified"
    end
    function self.memorialize()
        return nil, "Polished memorialize is not composed: the memorial box choice is an open owner ruling (NEWBOX 6.2)"
    end
    -- A settle only exists after a native save witness; Polished composes no save site, so there is never one.
    function self.settle() return true end
    function self.settle_memorial() return true end
    return self
end

return O