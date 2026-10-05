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
            -- records, OT fields and nicknames first, wPartyCount LAST (the engine's order: RemoveMonFromParty
            -- decrements the count after the swaps), so an interrupted write never leaves a decremented count
            -- over records that have not shifted yet.
            local rest = {}
            for i = 2, block_length do rest[i - 1] = bytes[i] end
            gate:write_batch({{domain = "System Bus", addr = block + 1, bytes = rest},
                              {domain = "System Bus", addr = block, bytes = {bytes[1]}}})
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
    local io_, coords = deps.io, deps.coords
    assert(type(reads) == "table" and type(reads.read_party) == "function", "reads.read_party required")
    assert(type(census) == "table" and type(census.read_storage_box) == "function", "a box census reader required")
    assert(type(Boxes) == "table", "the polished_boxes.lua module required")
    assert(type(reader) == "table" and type(reader.insert_mon) == "function", "a polished_boxes.lua reader required")
    assert(type(writes) == "table" and type(writes.arm) == "function", "the overworld writer required")
    local mail = deps.mail or {}
    -- party_mon (withdraw) dependencies. NOT asserted here: a graph composed without them still runs box_mon, and
    -- withdraw refuses by name (its own contract: nothing defaulted, a missing table is a refusal).
    local STATS, BASE, VARIANT, MOVE_PP = deps.stats, deps.base_stats, deps.variant_record, deps.move_pp
    local c, s = profile.constants, profile.structs.party
    local MEMORIAL, PER_BOX = Boxes.MEMORIAL_BOX, Boxes.MONS_PER_BOX
    local block, block_length, mons_at, ots_at, nicks_at = writes:block()
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
            -- raw is 1-based and `from` a zero-based offset: the removed slot's first byte is index from + 1.
            -- (Starting at `from` overwrote the LAST byte of the preceding slot: Codex P1, 2026-10-05.)
            for i = from + 1, limit[array] - width[array] do out[i] = raw[i + width[array]] end
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
            -- The box half first, in TWO steps with a verification between them. A reset reloads the last save, so
            -- neither half persists on its own; an exception or lifetime loss mid-write can leave a partial party
            -- until the next save/reload (the count is written last to keep that window small).
            --   step 1  stage_entry writes ONLY the sealed 49-byte entry, into an unallocated, unreferenced pokedb
            --           entry; it is read back (checksum + byte equality) before anything is published. A failure
            --           here publishes nothing: the bytes sit in a free entry the game cannot see.
            --   step 2  publish_entry sets the allocation flag, the Banks bit and the Entries pointer, which are
            --           read back below (and the neighbouring Banks bits must be unchanged) before the party is
            --           touched, so a bad entry is never published and the party original never removed for it.
            local blob = blob_of(raw, slot)
            local want = Boxes.entry_from_party(blob)
            writes:arm("box_deposit")
            local staged_ok, staged, swhy = pcall(function() return reader.stage_entry(writes, box, blob) end)
            writes:disarm()
            if not staged_ok then refuse("box write refused: " .. tostring(staged)) end
            if not staged then refuse("box " .. box .. " refused the deposit: " .. tostring(swhy)) end
            do
                local have, bad1 = reader.entry_bytes(staged.bank, staged.entry), nil
                if not Boxes.verify(have) then bad1 = "entry checksum fails" end
                for i = 1, #want do
                    if have[i] ~= want[i] then bad1 = bad1 or "entry bytes differ from the sealed entry" end
                end
                if bad1 then
                    refuse("deposit read-back refused: " .. bad1 .. " (nothing published: the entry is in an unallocated,"
                           .. " unreferenced pokedb slot; party untouched)")
                end
            end
            local banks_before = reader.banks_byte(box, staged.slot)
            writes:arm("box_deposit")
            local boxed, placed, bwhy = pcall(function() return reader.publish_entry(writes, staged) end)
            writes:disarm()
            local PUBLISHED = " (the entry may be partly published; party untouched)"
            if not boxed then refuse("box publish refused: " .. tostring(placed) .. PUBLISHED) end
            if not placed then refuse("box " .. box .. " refused the publish: " .. tostring(bwhy) .. PUBLISHED) end
            -- READ-BACK 0 (before the party half): the entry bytes (checksum + equality with what was sealed), the
            -- WRAM allocation flag, the Banks bit and the Entries pointer byte, re-read through the box reader's io.
            do
                local snap = reader.read_boxes("gameplay")
                local function at(list)
                    for _, w in ipairs(list or {}) do
                        if w.box == box and w.slot == placed.slot then return w end
                    end
                end
                local bad
                if not snap then bad = "the box census is unreadable"
                elseif at(snap.unflagged) then bad = "allocation flag not set"
                elseif at(snap.bad_eggs) then bad = "entry checksum fails"
                elseif at(snap.invalid) then bad = "invalid pointer or record"
                else
                    local got = at(snap.mons)
                    if not got then bad = "Entries pointer byte does not point at the entry"
                    elseif got.entry ~= placed.entry then bad = "Entries pointer byte"
                    elseif got.bank ~= placed.bank then bad = "Banks bit"
                    else
                        local have = from_hex(got.raw_hex)
                        if not Boxes.verify(have) then bad = "entry checksum fails" end
                        for i = 1, #want do
                            if have[i] ~= want[i] then bad = bad or "entry bytes differ from the sealed entry" end
                        end
                    end
                end
                local mask = 1 << ((placed.slot - 1) & 7)
                if not bad and ((banks_before ~ reader.banks_byte(box, placed.slot)) & ~mask & 0xFF) ~= 0 then
                    bad = "neighbouring Banks bits changed"
                end
                if bad then refuse("deposit read-back refused: " .. bad .. PUBLISHED) end
            end
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

    -- ── party_mon (withdraw) — docs/polished/WITHDRAW.md §1-§2 ───────────────────────────────────────────────
    -- The engine (engine/pc/bills_pc.asm SetStorageBoxPointer .party :582-613, GetStorageMon :1342,
    -- DecodeTempMon :887, SetTempPartyMonData :960) appends to the party and clears only the box slot's pointer
    -- byte and its Banks bit. It never frees the pokedb entry: those bytes, the name-MSB checksum and the
    -- allocation flag stay, and NewStoragePointer (:392) reuses the entry later. This executor follows that
    -- exactly, but PARTY half first (count last), verified, THEN the box half: a failure or lifetime loss in
    -- between leaves the mon in BOTH places (a retry reconciles), never in neither. (The earlier box-first order
    -- left ZERO live copies on 72 of 73 injected failure points.)
    -- Known limit: reconciliation matches by identity key plus byte equality, so two byte-identical INDEPENDENT mons
    -- (one boxed, one in the party) collapse into one on a reconcile; the key cannot tell them apart.
    -- sNewBox<n> flat CartRAM + the 0x21 record stride, and the Banks byte at +0x14 (NEWBOX §1.1).
    -- Declared BEFORE require_withdraw, which assigns it: as a later `local`, the assignment compiled
    -- to a global and every withdraw raised inside record_flat (introduced in a0487e8bd).
    local BOX1
    local function require_withdraw()
        if type(io_) ~= "table" or type(io_.read_u8) ~= "function" then
            refuse("withdraw is not composed: no live io for the option bytes")
        end
        if type(coords) ~= "table" or type(coords.sNewBox1) ~= "table" then
            refuse("withdraw is not composed: no newbox coordinates for the box record")
        end
        BOX1 = coords.sNewBox1[1] * 0x2000 + coords.sNewBox1[2] - 0xA000
        if type(STATS) ~= "table" or type(STATS.party_from_savemon) ~= "function" then
            refuse("withdraw is not composed: polished_stats.lua is not loaded")
        end
        if type(BASE) ~= "table" or type(VARIANT) ~= "table" or type(MOVE_PP) ~= "table" then
            refuse("withdraw is not composed: base_stats / variant_record / move_pp are all required")
        end
    end
    -- NATURES_OPT bit 0, PERFECT_IVS_OPT bit 3 (constants/ram_constants.asm:101,104);
    -- EV_OPTMASK EQU %11 = $03 (constants/ram_constants.asm:125) - NOT %1011: bit 3 of
    -- wInitialOptions2 is the RTC option, so $0B would enable EVs on a save that has them off.
    local NATURES_OPT, PERFECT_IVS_OPT, EV_OPTMASK = 0, 3, 0x03
    -- wInitialOptions 00:CFF6 / wInitialOptions2 00:CFF7 (constants/ram_constants.asm:101,104,125). WRAM0, so bank 0.
    local OPT1, OPT2 = 0xCFF6, 0xCFF7
    local function live_options()
        for _, at in ipairs({OPT1, OPT2}) do
            if io_.bank_valid(0, at, 1) ~= true then return nil, "options: WRAM0 is not mapped" end
        end
        local a, b = io_.read_u8(OPT1, "System Bus"), io_.read_u8(OPT2, "System Bus")
        if not integer(a, 0, 255) or not integer(b, 0, 255) then
            return nil, "options: wInitialOptions unreadable"
        end
        return {apply_evs = (b & EV_OPTMASK) ~= 0, natures_on = ((a >> NATURES_OPT) & 1) == 1,
                perfect_ivs = ((a >> PERFECT_IVS_OPT) & 1) == 1}
    end
    -- sNewBox<n> flat CartRAM + the 0x21 record stride, and the Banks byte at +0x14 (NEWBOX §1.1)
    local function record_flat(box) return BOX1 + 0x21 * (box - 1) end
    local function hex_bytes(h, n, what)
        local out = {}
        if type(h) ~= "string" or #h ~= 2 * n then refuse(what .. " is not " .. n .. " bytes") end
        for i = 1, n do out[i] = tonumber(h:sub(2 * i - 1, 2 * i), 16) end
        return out
    end
    local function pad(out, n)
        for i = #out + 1, n do out[i] = 0 end
        if #out ~= n then refuse("name field is " .. #out .. " bytes, expected " .. n) end
        return out
    end

    --- party_mon. true, note on success; nil, why on refusal. Never raises.
    --- Order (docs/polished/WITHDRAW.md section 2): the PARTY half first (record, OT, nickname, wPartyCount LAST), a
    --- read-back of the appended slot, THEN the box half (Entries byte + Banks bit), then the final read-back. Any
    --- failure between the halves leaves the mon in BOTH places, never in neither; withdraw() on that both-places
    --- state removes the box copy idempotently (the party copy must equal the rebuilt record) instead of refusing.
    function self.withdraw(key)
        local okr, result, note = pcall(function()
            require_withdraw()
            local boxes, why = scan()
            if not boxes then refuse("box census incomplete: " .. tostring(why)) end
            local party = party_block()
            local found, box, hits = nil, nil, 0
            for index = 1, c.NUM_BOXES do
                for _, m in ipairs(boxes[index] or {}) do
                    if m.key == key then
                        hits = hits + 1
                        found, box = m, index
                    end
                end
            end
            if hits > 1 then refuse("ambiguous duplicate boxed key") end
            if not found then refuse("key not boxed") end
            -- a second party match is an ambiguity, not "absent": refuse by name before any write
            local pmon, pwhy = find_key(party.mons, key)
            if pwhy then refuse(pwhy .. " in the party") end
            -- the 49-byte savemon, checksum re-proved here (the census already refuses Bad Eggs; a change between
            -- the scan and now would be a torn image)
            local entry = hex_bytes(found.raw_hex, 49, "box entry")
            if not Boxes.verify(entry) then
                refuse("box entry checksum mismatch (a Bad Egg is never withdrawn)")
            end
            local opts, owhy = live_options()
            if not opts then refuse(owhy) end
            local record, view, swhy = STATS.party_from_savemon(entry, {
                apply_evs = opts.apply_evs, natures_on = opts.natures_on, perfect_ivs = opts.perfect_ivs,
                base_stats = BASE, variant_record = VARIANT, move_pp = MOVE_PP})
            if not record then refuse("stat rebuild refused: " .. tostring(swhy)) end
            -- nickname 11 B (already decoded back to the party-side encoding), OT 8 name bytes + 3 EXTRA
            -- (savemon bytes 30..32, which carry hyper training - bills_pc.asm:960 reads the mask from
            -- wTempMonOT + PLAYER_NAME_LENGTH)
            local nick = pad(hex_bytes(found.nickname_raw_hex, 11, "nickname"), 11)
            local ot = {}
            for i = 1, 8 do ot[i] = hex_bytes(found.ot_raw_hex, 8, "OT name")[i] end
            for i = 1, 3 do ot[8 + i] = entry[29 + i] end
            -- what the party slot must hold: record 48 + OT 11 + nickname 11, the blob_of layout
            local want = {}
            for i = 1, #record do want[#want + 1] = record[i] end
            for i = 1, #ot do want[#want + 1] = ot[i] end
            for i = 1, #nick do want[#want + 1] = nick[i] end
            if #want ~= STRIDE then refuse("rebuilt party slot is " .. #want .. " bytes, expected " .. STRIDE) end
            local function slot_is_want(raw, slot)
                local have = blob_of(raw, slot)
                for i = 1, STRIDE do
                    if have[i] ~= want[i] then return false end
                end
                return true
            end
            local rec = record_flat(box)
            local slot = found.slot                          -- 0-based, as the census reports it
            local entries_at = rec + slot
            local bits_at = rec + 0x14 + (slot >> 3)
            local append = pmon == nil
            local target, expected = nil, party.count
            if append then
                if party.count >= c.PARTY_LENGTH then refuse("party full (" .. party.count .. "/" .. c.PARTY_LENGTH .. ")") end
                target, expected = party.count, party.count + 1  -- append: the engine only raises the count past it
            else
                -- BOTH-PLACES state (an earlier withdraw died between its halves). Finish the box removal only if
                -- the party copy is byte-for-byte what this withdraw would have appended.
                target = pmon.slot
                local now, praw = party_block()
                if target >= now.count then refuse("party changed during withdraw") end
                if not slot_is_want(praw, target) then
                    refuse("withdraw reconcile refused: the party copy differs from the boxed entry (the box copy is kept)")
                end
            end
            -- ── PARTY HALF: record, OT, nickname, wPartyCount LAST, permit = exactly those spans ──
            local function append_to_party()
                -- the slot index was planned from an earlier read: prove the party did not move under it
                local live = party_block()
                if live.count ~= party.count then refuse("party changed during withdraw") end
                local at_rec = block + mons_at + target * s.End
                local at_ot = block + ots_at + target * c.NAME_LENGTH
                local at_nick = block + nicks_at + target * c.MON_NAME_LENGTH
                writes:arm("party_collection", function(domain, addr, n)
                    return domain == "System Bus" and ((addr == at_rec and n == s.End) or (addr == at_ot and n == c.NAME_LENGTH)
                           or (addr == at_nick and n == c.MON_NAME_LENGTH) or (addr == block and n == 1))
                end)
                local okp, perr = pcall(function()
                    writes:write_batch({
                        {domain = "System Bus", addr = at_rec, bytes = record},
                        {domain = "System Bus", addr = at_ot, bytes = ot},
                        {domain = "System Bus", addr = at_nick, bytes = nick},
                        {domain = "System Bus", addr = block, bytes = {party.count + 1}},
                    })
                end)
                writes:disarm()
                if not okp then refuse("party half refused: " .. tostring(perr) .. " (the box copy is untouched)") end
                -- READ-BACK 1: the appended slot is exactly what was built and the count rose by one
                local after, araw = party_block()
                if after.count ~= expected then
                    refuse("read-back refused: party count " .. party.count .. " -> " .. tostring(after.count)
                           .. " (the box copy is untouched)")
                end
                if not slot_is_want(araw, target) then
                    refuse("read-back refused: the appended party slot differs from what was built (the box copy is untouched)")
                end
                local landed = find_key(after.mons, key)
                if not landed then refuse("read-back refused: the withdrawn mon is not in the party (the box copy is untouched)") end
                if landed.hp ~= view.hp or landed.status ~= 0 then
                    refuse("read-back refused: hp " .. tostring(landed.hp) .. "/" .. tostring(view.hp)
                           .. " status " .. tostring(landed.status) .. " (the box copy is untouched)")
                end
            end
            -- ── BOX HALF: the slot pointer byte and its Banks bit, nothing else, permit = exactly those two ──
            -- Two steps, each verified. The Entries byte goes first and ALONE: for a BANK-2 mon the Banks bit is what
            -- selects the pokedb bank, so clearing it while a silently failed Entries write left a non-zero pointer
            -- would redirect that pointer into bank 1 (an unallocated entry: the census then refuses everything and
            -- a retry cannot reconcile). The Banks bit is only touched once the Entries byte is proved 0.
            local cleared
            local function remove_box_copy()
                writes:arm("box_deposit", function(domain, addr, n)
                    return domain == "CartRAM" and n == 1 and addr == entries_at
                end)
                local oke, eerr = pcall(function()
                    writes:write_batch({{domain = "CartRAM", addr = entries_at, bytes = {0}}})
                end)
                writes:disarm()
                if not oke then
                    refuse("box half refused: " .. tostring(eerr) .. " (the mon is in the party AND the box; a retry reconciles)")
                end
                if io_.read_u8(entries_at, "CartRAM") ~= 0 then
                    refuse("withdraw read-back refused: Entries byte not cleared (box untouched beyond that byte)")
                end
                local bits = io_.read_u8(bits_at, "CartRAM")
                if not integer(bits, 0, 255) then refuse("box Banks byte unreadable (the Entries byte is already clear)") end
                cleared = bits & ~(1 << (slot & 7)) & 0xFF
                writes:arm("box_deposit", function(domain, addr, n)
                    return domain == "CartRAM" and n == 1 and addr == bits_at
                end)
                local okb, werr = pcall(function()
                    writes:write_batch({{domain = "CartRAM", addr = bits_at, bytes = {cleared}}})
                end)
                writes:disarm()
                if not okb then
                    refuse("box half refused: " .. tostring(werr) .. " (the mon is in the party; the Entries byte is clear)")
                end
                if io_.read_u8(bits_at, "CartRAM") ~= cleared then
                    refuse("withdraw read-back refused: Banks byte not cleared (the mon is in the party; the Entries byte is clear)")
                end
            end
            if append then append_to_party() end
            remove_box_copy()
            -- ── FINAL READ-BACK: the box no longer reads the mon (slot empty, pokedb entry untouched), the party does ──
            local after, araw = party_block()
            if after.count ~= expected then
                refuse("read-back refused: party count " .. party.count .. " -> " .. tostring(after.count))
            end
            if not find_key(after.mons, key) or not slot_is_want(araw, target) then
                refuse("read-back refused: the withdrawn mon is not in the party")
            end
            local after_boxes, cwhy = scan()
            if not after_boxes then
                refuse("read-back refused: the census no longer completes (" .. tostring(cwhy) .. ")")
            end
            if find_key(after_boxes[box], key) then
                refuse("read-back refused: box " .. box .. " still reads the mon")
            end
            if io_.read_u8(entries_at, "CartRAM") ~= 0 then refuse("read-back refused: the Entries byte did not clear") end
            if io_.read_u8(bits_at, "CartRAM") ~= cleared then
                refuse("read-back refused: the Banks bit did not clear")
            end
            return true, {box = box, from_slot = slot + 1, slot = target, hp = view.hp, max_hp = view.max_hp,
                          level = view.level, durability = "VOLATILE_UNTIL_NATIVE_SAVE",
                          reconciled = (not append) or nil,
                          message = (not append) and "withdraw reconciled: removed the box copy" or nil}
        end)
        if okr then return result, note end
        return nil, tostring(result)
    end

    -- Not composed, refused by name rather than stubbed:
    --  * memorialize targets the memorial box, and NEWBOX §6.2 leaves that choice an OPEN owner ruling.
    function self.memorialize()
        return nil, "Polished memorialize is not composed: the memorial box choice is an open owner ruling (NEWBOX 6.2)"
    end
    -- A settle only exists after a native save witness; Polished composes no save site, so there is never one.
    function self.settle() return true end
    function self.settle_memorial() return true end
    return self
end

-- ── the BATTLE hold (sibling of O.checkpoint; lua/gen2/polished_explode.lua composes it) ─────────────────────
--
-- The overworld predicate above refuses a battle by construction (wBattleMode == 0, hROMBank == the overworld
-- bank), so the battle writers get their own hold with the SAME shape and refusal conventions and a battle fact
-- set. O.checkpoint's body is untouched: this is a sibling, not a mode.
--   wBattleMode in {WILD, TRAINER}   a battle is running (not 0, nothing outside the source enumeration)
--   wLinkMode == 0                   never write into a link battle (the other Game Boy would desync)
--   wGameLogicPaused == 0            no native save is running
--   sWritingBackup != 1              no backup save in progress
-- and, per kind, the instruction bytes of the named sites re-read from the EXECUTED ROM at check time (so a
-- patched or relocated ROM never takes a write), plus, for a PC-hold kind, hROMBank == the site's bank.
--
-- THE SITES (bank 0F, ROM = the overlay; each byte sequence occurs ONCE in bank 0F and once in its routine -
-- verified by tests/unit/test_polished_explode_path.py over the executed overlay ROM, and every address
-- re-derived there from data/polished/polished_slink.sym):
--   explode       0f:416A  CD 35 42  `call DetermineMoveOrder` inside BattleTurn (engine/battle/core.asm:190): the
--                                    PC hold the client hooks (write_checkpoint.json battle_hold.execution_before)
--   rival_gate    0f:47DD  21 8B D2  `ld hl, wOTPartyMons` inside SendInUserPkmn's enemy branch: the PC where
--                                    wOTPartyMons[wCurPartyMon] has not been copied yet (battle_hold.rival_swap_gate)
--   trainer_ready 0f:7271  D7 00 40 07  inside InitEnemy's trainer branch. A UNIQUE-BYTE ANCHOR ONLY: the
--                                    2-byte D7 00 occurs 4x in bank 0F, so the 4-byte sequence plus the address is
--                                    the pin. No mnemonic is claimed for it.
-- rival_gate and trainer_ready are anchors for the frame-end rival poll (lua/gen2/client.lua rival_tick is a
-- frame_end POLL, not a PC hold): a frame-kind check re-reads their bytes but does not require the CPU to be
-- there. Only `explode` is a PC hold.
O.BATTLE_MODES = {[1] = true, [2] = true}            -- WILD_BATTLE, TRAINER_BATTLE (profile.constants)
O.BATTLE_QUALIFICATION = "DEV_OVERLAY_PREDICATE_HOLD"
O.BATTLE_SITES = {
    explode = {bank = 0x0F, pc = 0x416A, bytes = {0xCD, 0x35, 0x42}, routine = "BattleTurn",
               routine_start = 0x4109, routine_end = 0x41A7, instruction = "call DetermineMoveOrder"},
    rival_gate = {bank = 0x0F, pc = 0x47DD, bytes = {0x21, 0x8B, 0xD2}, routine = "SendInUserPkmn",
                  routine_start = 0x4748, routine_end = 0x493C, instruction = "ld hl, wOTPartyMons"},
    trainer_ready = {bank = 0x0F, pc = 0x7271, bytes = {0xD7, 0x00, 0x40, 0x07}, routine = "InitEnemy",
                     routine_start = 0x7260, routine_end = 0x72E0},
}
-- kind -> the sites whose bytes are re-read, and `at` = the site the CPU must be executing (hROMBank). The first
-- two are what lua/gen2/client.lua asks for; the last two are the writer operations lua/gen2/polished_explode.lua
-- maps battle_explode and enemy_party to.
O.BATTLE_KINDS = {
    battle_faint = {at = "explode", sites = {"explode"}},
    battle_bench = {sites = {"rival_gate", "trainer_ready"}},
    explode = {at = "explode", sites = {"explode"}},
    rival = {sites = {"rival_gate", "trainer_ready"}},
}

--- sites: O.BATTLE_SITES-shaped ({bank, pc, bytes, routine, routine_start, routine_end}). Same check(kind)
--- -> ok, why contract as O.checkpoint, qualification DEV_OVERLAY_PREDICATE_HOLD.
function O.battle_checkpoint(profile, io, log, sites)
    assert(type(profile) == "table" and profile.title == "polished" and type(profile.ram) == "table",
           "generated Polished profile required")
    assert(type(io) == "table" and type(io.read_u8) == "function" and type(io.bank_valid) == "function",
           "explicit read_u8/bank_valid required")
    assert(type(sites) == "table", "battle hold sites required")
    for _, kind in pairs(O.BATTLE_KINDS) do
        for _, id in ipairs(kind.sites) do
            local site = sites[id]
            assert(type(site) == "table" and integer(site.bank, 1, 0x7F) and integer(site.pc, 0x4000, 0x7FFF)
                   and type(site.bytes) == "table", "battle hold site missing or malformed: " .. id)
            assert(site.routine_start <= site.pc and site.pc + #site.bytes <= site.routine_end,
                   "the battle hold site must lie inside its named routine: " .. id)
            for _, value in ipairs(site.bytes) do assert(integer(value, 0, 255), "hold site byte out of range") end
        end
    end
    local ram, banks, hram = profile.ram, profile.ram_bank, profile.hram
    -- a copy of O.checkpoint's reader (kept separate so the overworld body stays untouched)
    local function byte(name)
        local at, bank = ram[name], banks[name]
        local hram_at = (hram ~= nil) and hram[name] or nil
        if at == nil and hram_at ~= nil then at, bank = hram_at, 0 end
        local wram = integer(at, 0xC000, 0xDFFF)
        local hram_window = integer(at, 0xFF80, 0xFFFF) and bank == 0
        if not (wram or hram_window) or not integer(bank, 0, 7) then return nil, "missing " .. name end
        if io.bank_valid(bank, at, 1) ~= true then return nil, name .. " bank not mapped" end
        return io.read_u8(at, "System Bus")
    end
    local last
    local function refuse(why)
        if log and last ~= why then
            last = why
            log("[SLink-gen2] battle write refused: " .. tostring(why))
        end
        return false, why
    end
    local self = {qualification = O.BATTLE_QUALIFICATION, facts = {}}
    function self:covers(kind) return O.BATTLE_KINDS[kind] ~= nil end
    function self:check(kind)
        local want = O.BATTLE_KINDS[kind]
        if want == nil then return refuse("no composed Polished battle write kind " .. tostring(kind)) end
        local observed = self.facts
        for _, name in ipairs({"wBattleMode", "wLinkMode", "wGameLogicPaused"}) do
            local value, why = byte(name)
            if value == nil then return refuse(why) end
            observed[name] = value
        end
        if not O.BATTLE_MODES[observed.wBattleMode] then
            return refuse("not in a battle (wBattleMode $" .. string.format("%02X", observed.wBattleMode) .. ")")
        end
        if observed.wLinkMode ~= 0 then return refuse("link cable active (wLinkMode)") end
        if observed.wGameLogicPaused ~= 0 then return refuse("native save running (wGameLogicPaused)") end
        local saving = saving_byte(io)
        if saving == nil then return refuse("sWritingBackup unreadable") end
        if saving == 1 then return refuse("backup save in progress (sWritingBackup)") end
        if want.at ~= nil then
            local hold_bank, bank_why = byte("hROMBank")
            if hold_bank == nil then return refuse(bank_why) end
            if hold_bank ~= sites[want.at].bank then
                return refuse("not at the " .. sites[want.at].routine .. " hold (hROMBank $"
                              .. string.format("%02X", hold_bank) .. ")")
            end
        end
        for _, id in ipairs(want.sites) do
            local site = sites[id]
            -- the ROM domain is addressed by its LINEAR offset, not the banked bus address
            local rom_at = site.bank * 0x4000 + (site.pc - 0x4000)
            for i, expected in ipairs(site.bytes) do
                local seen = io.read_u8(rom_at + i - 1, "ROM")
                if seen ~= expected then
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

return O