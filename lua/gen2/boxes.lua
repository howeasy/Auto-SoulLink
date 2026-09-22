-- Gen 2 box-side edit plans, SOURCE/MODEL only. No emulator API or bank arithmetic.
-- Pins: pokecrystal@7a7881d0, pokegold@656583c9.
-- move_mon.asm SendGetMonIntoFromBox appends PC deposits; RemoveMonFromPartyOrBox
-- compacts records/OTs/nicknames through the fixed arrays. SendMonIntoBox's
-- capture prepend is deliberately a different operation, not implemented here.
-- save.asm SaveBoxAddress copies sBox..sBoxEnd (1102), never backing padding.
-- PLAN 5.5: pre-first-SAVE refusal; memorial backing refuses current box 13.
-- Input records are prepared box payloads (32+11+11+separate egg marker).
-- Party edits, PP restoration/healing, memorial.json, save witnesses and
-- reassertion after a qualified full SAVE are external caller obligations.
-- Gate contract: preflight(requirements) must verify current state/before bytes,
-- checkpoint/permit authority and qualified linear CartRAM mapping. It returns
-- a private ticket with mapping_qualified/domain/domain_size. execute(ticket,
-- spans) is the injected validated-span executor and rechecks permit lifetime.
-- Preflight may annotate its ticket, but must not change its requirements input.
-- No gate is activated here; no source flat address implies physical mapping.
local B = {}

local function integer(value, low, high)
    return type(value) == "number" and value == math.floor(value) and value >= low and value <= high
end

local function bytes(value, count, label)
    assert(type(value) == "table" and getmetatable(value) == nil, label .. ": plain byte array required")
    local result = {}
    for key, item in pairs(value) do
        assert(integer(key, 1, count) and integer(item, 0, 255), label .. ": invalid byte/index")
    end
    for i = 1, count do
        assert(integer(value[i], 0, 255), label .. ": incomplete byte array")
        result[i] = value[i]
    end
    return result
end

local function copy(value)
    if type(value) ~= "table" then return value end
    local result = {}
    for key, item in pairs(value) do result[key] = copy(item) end
    return result
end

local function same(actual, expected)
    if type(actual) ~= type(expected) then return false end
    if type(expected) ~= "table" then return actual == expected end
    if getmetatable(actual) ~= nil then return false end
    for key, value in pairs(expected) do if not same(actual[key], value) then return false end end
    for key in pairs(actual) do if expected[key] == nil then return false end end
    return true
end

local function slice(value, start, count)
    local out = {}
    for i = 1, count do out[i] = value[start + i] end
    return out
end

local function put(target, offset, value)
    for i = 1, #value do target[offset + i] = value[i] end
end

function B.new(profile, gate)
    assert(type(profile) == "table" and ({crystal=true, gold=true, silver=true})[profile.title], "selected profile required")
    assert(type(gate) == "table" and type(gate.preflight) == "function" and type(gate.execute) == "function", "injected box gate required")
    local p = copy(profile)
    local c, d, a = assert(p.constants), assert(p.derived), assert(p.ram)
    assert(type(p.rom_sha1) == "string" and #p.rom_sha1 == 40 and p.rom_sha1:match("^[0-9a-f]+$"), "profile ROM provenance required")
    assert(c.NUM_BOXES == 14 and c.MONS_PER_BOX == 20 and c.BOXMON_STRUCT_LENGTH == 32
           and c.NAME_LENGTH == 11 and c.MON_NAME_LENGTH == 11 and c.BOX_LENGTH == 1104
           and c.EGG == 253 and c.MON_SPECIES == 0 and c.MON_LEVEL == 31, "unsupported Gen 2 box dimensions")
    assert(integer(d.active_box_flat, 0, 32768 - 1102) and d.active_box_copy_length == 1102,
           "generated active flat mapping/copy length required")
    assert(a.sBoxEnd - a.sBox == d.active_box_copy_length, "active copy length differs from source symbols")
    assert(type(p.storage_boxes) == "table" and #p.storage_boxes == 14, "fourteen generated flat boxes required")
    local backing = {}
    for i = 1, 14 do
        local row = p.storage_boxes[i]
        assert(row.number == i and row.length == 1104 and integer(row.flat, 0, 32768 - 1104), "generated backing flat mapping required")
        backing[i] = row.flat
        for j = 1, i - 1 do
            assert(row.flat + 1104 <= backing[j] or backing[j] + 1104 <= row.flat, "backing box intervals overlap")
        end
        assert(row.flat + 1104 <= d.active_box_flat or d.active_box_flat + 1102 <= row.flat, "active/backing intervals overlap")
    end
    assert(backing[14] == 0x79e0, "selected source Box 14 flat pin mismatch")
    assert(type(p.ram_bank) == "table" and integer(a.wCurBox, 0, 65535)
           and integer(a.wSavedAtLeastOnce, 0, 65535)
           and integer(p.ram_bank.wCurBox, 0, 7) and integer(p.ram_bank.wSavedAtLeastOnce, 0, 7),
           "observed state source symbols/banks required")
    local records, ots, nicknames = a.sBoxMon1 - a.sBox, a.sBoxMonOTs - a.sBox, a.sBoxMonNicknames - a.sBox
    assert(records == 22 and ots == 662 and nicknames == 882, "source box field partition differs")
    local plans, self = setmetatable({}, {__mode="k"}), {}

    local function mon(value)
        assert(type(value) == "table", "complete box payload required")
        local result = {bytes=bytes(value.bytes,32,"record"), ot=bytes(value.ot,11,"OT"), nickname=bytes(value.nickname,11,"nickname")}
        local species, marker = result.bytes[1], value.species_marker
        assert(integer(species,1,251) and integer(result.bytes[32],1,100), "invalid record species/level")
        assert(integer(marker,1,251) or marker == 253, "explicit species marker required")
        assert(marker == 253 or marker == species, "record/species marker mismatch")
        result.species_marker = marker
        return result
    end

    local function checked(state, index, before, memorial)
        assert(type(state) == "table" and integer(state.current_box,0,13), "current box index required")
        assert(integer(state.saved_at_least_once,0,255) and state.saved_at_least_once ~= 0, "box edit refused before first SAVE")
        assert(integer(index,0,13), "box index out of bounds")
        assert(not memorial or (index == 13 and state.current_box ~= 13), "memorial backing refused while Box 14 is current")
        local active = index == state.current_box
        local raw = bytes(before,active and 1102 or 1104,"box")
        local count = raw[1]
        assert(integer(count,0,20) and raw[count+2] == 255, "invalid box count/terminator")
        for slot = 0, count-1 do
            mon({bytes=slice(raw,records+slot*32,32),ot=slice(raw,ots+slot*11,11),
                 nickname=slice(raw,nicknames+slot*11,11),species_marker=raw[slot+2]})
        end
        return raw, active, count
    end

    local function finish(state, index, before, after, active, operation, removed)
        local address = active and d.active_box_flat or backing[index+1]
        local requirements = {
            domain="CartRAM", domain_size=32768, require_qualified_linear_mapping=true,
            title=p.title, rom_sha1=p.rom_sha1, operation=operation,
            observed_state={current_box=state.current_box,saved_at_least_once=state.saved_at_least_once},
            state_sources={current_box={address=a.wCurBox,bank=p.ram_bank.wCurBox},
                           saved_at_least_once={address=a.wSavedAtLeastOnce,bank=p.ram_bank.wSavedAtLeastOnce}},
            before_spans={{domain="CartRAM",address=address,bytes=slice(before,0,1102)}},
        }
        local plan = {
            schema="gen2-box-plan-v1", title=p.title, operation=operation, box_index=index,
            owner=active and "active" or "backing", state=copy(requirements.observed_state),
            before=before, after=after, removed=removed,
            spans={{domain="CartRAM",address=address,bytes=slice(after,0,1102)}},
            untouched={{domain="CartRAM",address=0,length=address},
                       {domain="CartRAM",address=address+1102,length=32768-address-1102}},
            obligations={party_coordination="EXTERNAL_REQUIRED", prepared_record="PP_AND_PARTY_TRANSFORMS_EXTERNAL",
                         durability="UNQUALIFIED", checksum="BOX_BYTES_UNCHECKSUMMED",
                         memorial_record=operation == "memorial" and "EXTERNAL_REQUIRED" or "NOT_APPLICABLE",
                         reassert_after_full_save=operation == "memorial"},
            requirements=requirements,
        }
        if active then
            plan.copyback={mode="ENGINE_SAVEBOX_DEFERRED",from_address=address,to_address=backing[index+1],length=1102}
        else
            plan.copyback={mode="NONE_WHILE_INACTIVE",padding_untouched=true}
        end
        plans[plan] = copy(plan)
        return plan
    end

    local function insert(state,index,before,payload,memorial)
        local raw, active, count = checked(state,index,before,memorial)
        assert(count < 20, "box full")
        local incoming, after = mon(payload), copy(raw)
        after[1], after[count+2], after[count+3] = count+1, incoming.species_marker, 255
        put(after,records+count*32,incoming.bytes)
        put(after,ots+count*11,incoming.ot)
        put(after,nicknames+count*11,incoming.nickname)
        return finish(state,index,raw,after,active,memorial and "memorial" or "deposit")
    end

    function self.plan_deposit(state,index,before,payload) return insert(state,index,before,payload,false) end
    function self.plan_memorial(state,before,payload) return insert(state,13,before,payload,true) end

    function self.plan_withdraw(state,index,before,slot)
        local raw, active, count = checked(state,index,before,false)
        assert(integer(slot,0,count-1), "withdraw slot out of bounds")
        local removed = mon({bytes=slice(raw,records+slot*32,32),ot=slice(raw,ots+slot*11,11),
                             nickname=slice(raw,nicknames+slot*11,11),species_marker=raw[slot+2]})
        local after = copy(raw)
        after[1] = count-1
        for position = slot+2, count+1 do after[position] = raw[position+1] end
        if slot == 19 then
            after[ots+slot*11+1] = 255
        else
            -- Native RemoveMonFromPartyOrBox shifts the complete fixed arrays,
            -- including unused slots; the final record/name bytes remain stale.
            for _, field in ipairs({{records,32},{ots,11},{nicknames,11}}) do
                local base, width = field[1], field[2]
                for position = base+slot*width+1, base+19*width do after[position] = raw[position+width] end
            end
        end
        return finish(state,index,raw,after,active,"withdraw",removed)
    end

    function self.commit(plan)
        local frozen = plans[plan]
        assert(frozen and same(plan,frozen), "unknown, consumed or modified box plan")
        -- Only plans created by this instance can reach the gate. Retire before
        -- calling external code; a refusal/error needs a fresh observed plan.
        plans[plan] = nil
        bytes(frozen.spans[1].bytes,1102,"plan payload")
        local requirements = copy(frozen.requirements)
        local ticket, why = gate.preflight(requirements)
        assert(same(requirements,frozen.requirements), "box preflight changed sealed requirements")
        assert(type(ticket) == "table" and ticket.mapping_qualified == true
               and ticket.domain == "CartRAM" and ticket.domain_size == 32768, "box gate refused: " .. tostring(why or "unqualified mapping"))
        local result = gate.execute(ticket,copy(frozen.spans),copy(frozen.requirements))
        assert(type(result) == "table" and result.status == "written" and result.completed == 1102,
               "box gate did not report complete write; no rollback is implied")
        return result
    end
    return self
end

return B
