-- Gen 2 source-candidate predicate. Inspection is SOURCE/MODEL only; check()
-- deliberately cannot authorize runtime writes before a separate qualified rebind.
local M = {}
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

function M.new(pack, title, io, evaluator, ownership)
    assert(type(evaluator) == "table" and type(evaluator.check) == "function", "shared GB evaluator required")
    assert(type(ownership) == "table", "explicit host ownership observations required")
    for _, name in ipairs({"capture", "valid", "admitted", "no_conflicting_owner",
                           "mapped_rom_bank", "effective_wram_bank"}) do
        assert(ownership[name] ~= nil, name .. " observation required")
    end
    local self = {}
    function self:check()
        return false, "Gen 2 checkpoint is SOURCE_CANDIDATE; runtime qualification is OPEN"
    end
    function self:inspect_candidate()
        local ok, matches, why = pcall(function()
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
                for _, condition in ipairs(primary.state_predicates) do
                    if masked(read(condition.address, condition.read_domain), condition.mask) ~= condition.value then
                        return false, condition.symbol .. " predicate refused"
                    end
                end
                if not banks_match() or ownership.valid(held) ~= true
                    or ownership.admitted(title, pack.source.rom_sha1) ~= true
                    or ownership.no_conflicting_owner() ~= true then
                    return false, "held identity, bank or ownership changed"
                end
                return true
            end)
            return accepted, reason
        end)
        return {candidate_match=ok and matches == true, runtime_authorized=false,
            evidence_level="SOURCE_MODEL", physical_status="OPEN",
            reason=ok and why or ("checkpoint evidence unavailable: " .. tostring(matches))}
    end
    return self
end
return M
