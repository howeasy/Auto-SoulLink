-- Gen 2 checkpoint policy over the shared GB evaluator. inspect_candidate() is SOURCE/MODEL
-- evidence and never authority. check() authorizes ONLY behind a PHYSICAL write-window receipt
-- (M.qualified: schema gen2-write-window-receipt-v1, written by tests/live/test_gen2_write_windows.py
-- after lua/tests/gen2_write_windows.lua proved the idle write and refused every negative on the
-- running cartridge) for the same title and the identical checkpoint rows. Crystal and Gold carry
-- their own receipts; Silver's pack rows equal Gold's (primary is byte-identical), so a Gold
-- receipt covers Silver ONLY while those rows stay identical. Authorization is not admission:
-- admission stays with admission.json / entry.lua (O-22, card U3).
local M = {}
M.RECEIPT_SCHEMA = "gen2-write-window-receipt-v1"
-- title -> the title whose PHYSICAL receipt may authorize it (rows must still be identical).
M.RECEIPT_TITLE = {crystal="crystal", gold="gold", silver="gold"}
M.RECEIPT_CONTROLS = {idle_party_write="authorized", idle_box_write="authorized", start_menu="refused",
    script_text="refused", mid_warp="refused", battle_party_write="refused"}
M.SAVE_WINDOW = {refused=true, MODEL_ONLY=true}
local REQUIRED = {
    wMapStatus=true, wMapEventStatus=true, wScriptRunning=true, wScriptMode=true,
    wScriptFlags=true, wScriptStackSize=true, wJoypadDisable=true, wGameLogicPaused=true,
    wInputType=true, wBattleMode=true, wStateFlags=true, hMapEntryMethod=true,
    wLinkMode=true, hSerialConnectionStatus=true, wSavedAtLeastOnce=true,
}
local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end
local function masked(value, mask)
    local result, place = 0, 1
    for _ = 1, 8 do
        if value % 2 == 1 and mask % 2 == 1 then result = result + place end
        value, mask, place = math.floor(value / 2), math.floor(mask / 2), place * 2
    end
    return result
end
local function same(a, b)
    if type(a) ~= type(b) then return false end
    if type(a) ~= "table" then return a == b end
    for key, value in pairs(a) do if not same(value, b[key]) then return false end end
    for key in pairs(b) do if a[key] == nil then return false end end
    return true
end

-- Symbols of the pack's state predicates that `read` refuses, in pack order. Pure.
function M.failing_predicates(primary, read)
    local failed = {}
    for _, condition in ipairs(primary.state_predicates) do
        if masked(read(condition.address, condition.read_domain), condition.mask) ~= condition.value then
            failed[#failed + 1] = condition.symbol
        end
    end
    return failed
end

-- true, or nil,why: `receipt` is a PHYSICAL write-window receipt that may authorize `title`.
function M.qualified(pack, title, receipt)
    local owner = M.RECEIPT_TITLE[title]
    if not owner then return nil, "no PHYSICAL write-window receipt path for " .. tostring(title) end
    if type(receipt) ~= "table" or receipt.schema ~= M.RECEIPT_SCHEMA or receipt.evidence_level ~= "PHYSICAL"
       or receipt.result ~= "PASS" then
        return nil, "PHYSICAL write-window receipt required"
    end
    local data = type(pack) == "table" and type(pack.titles) == "table" and pack.titles[title]
    if receipt.title ~= owner or type(data) ~= "table" or type(pack.source) ~= "table"
       or (owner == title and receipt.rom_sha1 ~= pack.source.rom_sha1) then
        return nil, "write-window receipt belongs to another title or ROM"
    end
    if not same(receipt.checkpoint, data.primary) then
        return nil, "write-window receipt proved other checkpoint rows than this pack's"
    end
    for name, want in pairs(M.RECEIPT_CONTROLS) do
        if type(receipt.controls) ~= "table" or receipt.controls[name] ~= want then
            return nil, "write-window receipt control not " .. want .. ": " .. name
        end
    end
    if not M.SAVE_WINDOW[receipt.save_window] or receipt.persisted ~= true then
        return nil, "write-window receipt lacks the save-window verdict or the save/reload persistence proof"
    end
    return true
end

function M.new(pack, title, io, evaluator, ownership, receipt)
    assert(type(evaluator) == "table" and type(evaluator.check) == "function", "shared GB evaluator required")
    assert(type(ownership) == "table", "explicit host ownership observations required")
    for _, name in ipairs({"capture", "valid", "admitted", "no_conflicting_owner",
                           "mapped_rom_bank", "effective_wram_bank"}) do
        assert(ownership[name] ~= nil, name .. " observation required")
    end
    local self = {}
    local evaluate
    local qualified, unqualified = true, nil
    if receipt == nil then
        qualified, unqualified = false, "Gen 2 checkpoint is SOURCE_CANDIDATE; runtime qualification is OPEN"
    else
        qualified, unqualified = M.qualified(pack, title, receipt)
    end
    -- The runtime authority: the same held evaluation inspect_candidate reports, but only behind
    -- the PHYSICAL receipt. Must run inside the synchronous CPU hold at the checkpoint PC.
    function self:check()
        if not qualified then return false, unqualified end
        local ok, matches, why = pcall(evaluate)
        if not ok then return false, "checkpoint evidence unavailable: " .. tostring(matches) end
        return matches == true, why
    end
    function self:inspect_candidate()
        local ok, matches, why = pcall(evaluate)
        return {candidate_match=ok and matches == true, runtime_authorized=false,
            evidence_level="SOURCE_MODEL", physical_status="OPEN",
            reason=ok and why or ("checkpoint evidence unavailable: " .. tostring(matches))}
    end
    function evaluate()
        do
            assert(type(pack) == "table" and pack.schema == "gen2-write-checkpoint-v1", "unsupported Gen 2 checkpoint pack")
            assert(type(title) == "string" and type(pack.titles) == "table", "selected title required")
            local count = 0
            for key in pairs(pack.titles) do count = count + 1; assert(key == title, "checkpoint title mismatch") end
            assert(count == 1, "exactly one selected checkpoint title required")
            local data = assert(pack.titles[title], "checkpoint title missing")
            assert(data.runtime_authorized == false and data.maturity == "SOURCE_CANDIDATE"
                and data.physical.status == "OPEN", "source-candidate authorization metadata differs")
            local primary = assert(data.primary, "source checkpoint unavailable")
            assert(primary.acceptance == "ALL_REQUIRED_SAME_HELD_EXECUTION", "held execution contract required")
            local owner = assert(primary.ownership_requirements, "game ownership facts required")
            assert(owner.cached_frame_acceptance_allowed == false and owner.mapped_rom_bank_must_equal_shadow == true,
                "fresh bank/ownership policy required")
            local held = ownership.capture()
            assert(held ~= nil and ownership.valid(held) == true, "synchronous CPU hold unavailable")
            assert(ownership.admitted(title, pack.source.rom_sha1) == true, "exact admitted identity unavailable")
            assert(ownership.no_conflicting_owner() == true, "another writer, save or trade owns the game")
            local function banks_match()
                return ownership.mapped_rom_bank() == owner.mapped_rom_bank
                    and ownership.effective_wram_bank() == owner.effective_wram_bank
            end
            assert(banks_match(), "mapped bank evidence differs")
            assert(primary.execution_before.bank == owner.mapped_rom_bank, "checkpoint bank facts differ")
            local rom_size = io.domain_size("ROM")
            assert(integer(rom_size, 1, 0x800000), "actual ROM domain size unavailable")
            local anchors = {}
            for _, name in ipairs({"ow_player_input", "player_events_caller"}) do
                local anchor = assert(primary.anchors[name], "required source anchor missing")
                assert(anchor.bank == owner.mapped_rom_bank and anchor.instruction_set == "SM83", "anchor bank/instruction set differs")
                anchors[#anchors + 1] = {domain="ROM", address=anchor.rom_offset, expected_hex=anchor.expected_hex}
                anchors[#anchors + 1] = {domain="System Bus", address=anchor.address, expected_hex=anchor.expected_hex}
            end
            local stack = primary.caller_stack
            assert(stack.search_for_return_address == false and stack.must_fit_entire_read == true
                and stack.read_domain == "System Bus", "bounded source caller contract required")
            assert(type(stack.required_words) == "table" and getmetatable(stack.required_words) == nil,
                "caller words require a plain array")
            local word_count, last_word = 0, 0
            for key in next, stack.required_words do
                assert(integer(key, 1, 65536), "caller words have an invalid index")
                word_count, last_word = word_count + 1, math.max(last_word, key)
            end
            assert(word_count > 0 and word_count == last_word, "caller words are empty or sparse")
            local words = {}
            for _, word in ipairs(stack.required_words) do
                assert(word.endianness == "little", "source caller is not little-endian")
                words[#words + 1] = {offset=word.offset_from_sp, values={word.value}}
            end
            local seen, count_predicates = {}, 0
            for key, condition in pairs(primary.state_predicates) do
                assert(integer(key, 1, 15) and type(condition) == "table" and REQUIRED[condition.symbol]
                    and not seen[condition.symbol], "missing, duplicate or unknown game predicate")
                seen[condition.symbol], count_predicates = true, count_predicates + 1
                assert(condition.width == 1 and condition.operator == "masked_equal"
                    and condition.read_domain == "System Bus" and integer(condition.mask, 1, 255)
                    and integer(condition.value, 0, 255), "unsupported game predicate")
            end
            assert(count_predicates == 15, "complete Gen 2 state predicate required")
            local spec = {
                domains={ROM={first=0, limit=rom_size}, ["System Bus"]={first=0, limit=0x10000}},
                anchors=anchors, pc=primary.execution_before.pc,
                stack={domain=stack.read_domain, minimum_sp=stack.minimum_sp,
                    exclusive_end=stack.exclusive_stack_end, read_bytes=stack.required_read_bytes, words=words},
            }
            local accepted, reason = evaluator.check(spec, io, function(read)
                local shadow = owner.rom_bank_shadow
                if read(shadow.address, "System Bus") ~= shadow.equals then return false, "ROM bank shadow differs" end
                local bank = read(owner.wram_bank_register.address, "System Bus") % 8
                if bank == 0 then bank = 1 end
                if bank ~= owner.effective_wram_bank then return false, "effective WRAM bank differs" end
                local serial = owner.serial_control
                if masked(read(serial.address, "System Bus"), serial.mask) ~= serial.value then
                    return false, "serial transfer owns the game"
                end
                local failed = M.failing_predicates(primary, read)
                if failed[1] then return false, failed[1] .. " predicate refused" end
                if not banks_match() or ownership.valid(held) ~= true
                    or ownership.admitted(title, pack.source.rom_sha1) ~= true
                    or ownership.no_conflicting_owner() ~= true then
                    return false, "held identity, bank or ownership changed"
                end
                return true
            end)
            return accepted, reason
        end
    end
    return self
end
return M
