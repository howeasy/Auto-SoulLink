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
                         -- Continue runs LoadBox (C engine/menus/save.asm:601, G :543), copying the
                         -- stored box over sBox; only SaveBox (C :275, G :282) syncs back. A reset
                         -- before the next SAVE reverts any active-box edit.
                         reset_before_save=active and "LOADBOX_REVERTS_ACTIVE_EDIT" or "NOT_APPLICABLE",
                         reassert_after_full_save=operation == "memorial" or active},
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

-- ── CartRAM gate + command executor ─────────────────────────────────────────────────────
-- The U2 write kind a box plan needs: the active sBox (current box) is box_deposit / box_withdraw,
-- any other sBoxN is backing_box. Active edits revert on a reset before SAVE (Continue's LoadBox);
-- backing edits are plain SRAM, durable at once (C engine/menus/save.asm:266-296,596-601; G :273,543).
function B.kind_of(profile, requirements)
    local span = requirements.before_spans[1]
    if span.address == profile.derived.active_box_flat then
        return requirements.operation == "withdraw" and "box_withdraw" or "box_deposit"
    end
    return "backing_box"
end

-- The injected gate B.new commits through: preflight re-proves the held checkpoint for the plan's
-- kind, the observed box state and the preimage; execute writes the one span behind the shared permit.
-- p = {Permit, profile, io (read_range/write_u8/bank_valid/domain_size), check(kind), lifetime, provenance}.
function B.cart_gate(p)
    local io, profile = p.io, p.profile
    local d = profile.derived
    local regions = {{d.active_box_flat, d.active_box_copy_length}}
    for _, row in ipairs(profile.storage_boxes) do regions[#regions + 1] = {row.flat, row.length} end
    local permit = p.Permit.new({
        write_u8 = function(addr, value) io.write_u8(addr, value, "CartRAM") end,
        domains = {CartRAM = {
            bounds = function(addr, n)
                for _, r in ipairs(regions) do if addr >= r[1] and addr + n <= r[1] + r[2] then return true end end
                return false
            end,
            -- ponytail: CartRAM is linear in BizHawk's domain; the held checkpoint is re-proven per span
            -- in preflight/execute, not per byte (the evaluator re-reads its anchors every call).
            mapped = function() return true end, pointer_stable = function() return true end}},
        lifetime = p.lifetime,
        provenance = p.provenance,
    })
    local function wram(source)
        if io.bank_valid(source.bank, source.address, 1) ~= true then return nil end
        return io.read_range(source.address, 1, "System Bus")[1]
    end
    local gate = {}
    function gate.preflight(req)
        local kind = B.kind_of(profile, req)
        if p.check(kind) ~= true then return nil, "checkpoint refused write kind " .. kind end
        local s = req.state_sources
        if wram(s.current_box) ~= req.observed_state.current_box
           or wram(s.saved_at_least_once) ~= req.observed_state.saved_at_least_once then
            return nil, "observed box state changed"
        end
        if io.domain_size("CartRAM") < 32768 then return nil, "CartRAM smaller than 32 KiB" end
        for _, span in ipairs(req.before_spans) do
            local live = io.read_range(span.address, #span.bytes, "CartRAM")
            for i = 1, #span.bytes do if live[i] ~= span.bytes[i] then return nil, "box preimage changed" end end
        end
        return {mapping_qualified=true, domain="CartRAM", domain_size=32768, kind=kind}
    end
    function gate.execute(ticket, spans)
        assert(p.check(ticket.kind) == true, "checkpoint lost before the box write")
        local span = spans[1]
        permit:scope("box-" .. ticket.kind, nil, function()
            permit:write_batch({{domain="CartRAM", addr=span.address, bytes=span.bytes}})
        end)
        return {status="written", completed=#span.bytes}
    end
    return gate
end

-- box_mon / party_mon / memorialize as the native PC performs them (C/G engine/pokemon/move_mon.asm):
-- deposit = RestorePPOfDepositedPokemon (:711-775) then append; withdraw = append the 32-byte record,
-- CalcMonStats with stat exp (:1402-1618), status 0, HP = max HP (:640-690); RemoveMonFromPartyOrBox
-- (:1222-1370) compacts the fixed arrays. Party first on withdraw, box first on deposit (Gen 1 order).
-- A key found both in the party and in a box is a reset-interrupted command: it completes only when
-- the two records match in full (every byte, PP counts excepted; OT, nickname, species marker) and
-- refuses otherwise. p = {profile, reads, key(mon), writes (write_party_block), box (B.new), io,
-- base_stats(species), move_pp(move), mail = {[item]=true}, covers(kind)}. Returns true | nil, why.
function B.executor(p)
    local profile, reads, io = p.profile, p.reads, p.io
    local c, d, ram = profile.constants, profile.derived, profile.ram
    local MEMORIAL, CAP, STRIDE, NAME = c.NUM_BOXES - 1, c.PARTY_LENGTH, c.PARTYMON_STRUCT_LENGTH, c.NAME_LENGTH
    local P = {records = CAP + 2, ots = CAP + 2 + CAP * STRIDE}
    P.nicks = P.ots + CAP * NAME
    local X = {records = ram.sBoxMon1 - ram.sBox, ots = ram.sBoxMonOTs - ram.sBox, nicks = ram.sBoxMonNicknames - ram.sBox}
    local function refuse(why) error(why, 0) end
    local function need(...)
        for _, kind in ipairs({...}) do
            if p.covers(kind) ~= true then refuse("unproven write kind " .. kind .. " (no PHYSICAL receipt)") end
        end
    end
    local function wram_byte(name)
        assert(io.bank_valid(profile.ram_bank[name], ram[name], 1) == true, name .. ": WRAM bank unavailable")
        return io.read_range(ram[name], 1, "System Bus")[1]
    end
    local function from_hex(h)
        local out = {}
        for i = 1, #h, 2 do out[#out + 1] = tonumber(h:sub(i, i + 1), 16) end
        return out
    end
    local function find(list, key)
        local hit
        for _, m in ipairs(list) do
            if not m.is_egg and p.key(m) == key then
                if hit then refuse("ambiguous duplicate key") end
                hit = m.slot
            end
        end
        return hit
    end
    local function party()
        local r, why = reads.read_party()
        if not r then refuse("party unreadable: " .. tostring(why)) end
        return from_hex(r.raw_hex), r.mons
    end
    local function load_box(index, cur)
        local active = index == cur
        local flat = active and d.active_box_flat or profile.storage_boxes[index + 1].flat
        local raw = {}
        for i, b in ipairs(io.read_range(flat, active and d.active_box_copy_length or c.BOX_LENGTH, "CartRAM")) do raw[i] = b end
        local decoded, why = (active and reads.decode_active_box_block or reads.decode_box_block)(raw)
        if not decoded then refuse("box " .. (index + 1) .. " unreadable: " .. tostring(why)) end
        return {index = index, raw = raw, list = decoded.mons, active = active}
    end
    local function boxed(key, cur)
        local found
        for index = 0, c.NUM_BOXES - 1 do
            local b = load_box(index, cur)
            local slot = find(b.list, key)
            if slot then
                if found then refuse("ambiguous duplicate boxed key") end
                b.slot, found = slot, b
            end
        end
        return found
    end
    local function state(cur) return {current_box = cur, saved_at_least_once = wram_byte("wSavedAtLeastOnce")} end
    local function current()
        local cur, why = reads.read_current_box_num()
        if cur == nil then refuse("current box unreadable: " .. tostring(why)) end
        return cur
    end

    -- 1-based raw accessors: party record i of slot s is praw[P.records + s*STRIDE + i].
    local function prec(raw, s) local out = {} for i = 1, STRIDE do out[i] = raw[P.records + s * STRIDE + i] end return out end
    local function pname(raw, base, s) local out = {} for i = 1, NAME do out[i] = raw[base + s * NAME + i] end return out end
    local function brec(b, s) local out = {} for i = 1, c.BOXMON_STRUCT_LENGTH do out[i] = b.raw[X.records + s * c.BOXMON_STRUCT_LENGTH + i] end return out end
    local function bname(b, base, s) local out = {} for i = 1, NAME do out[i] = b.raw[base + s * NAME + i] end return out end

    local function same(praw, ps, b)
        local pr, br = prec(praw, ps), brec(b, b.slot)
        if praw[2 + ps] ~= b.raw[2 + b.slot] then return false end
        for i = 1, c.BOXMON_STRUCT_LENGTH do
            local pp = i > c.MON_PP and i <= c.MON_PP + c.NUM_MOVES
            if (pp and math.floor(pr[i] / 64) ~= math.floor(br[i] / 64)) or (not pp and pr[i] ~= br[i]) then return false end
        end
        local a1, a2 = pname(praw, P.ots, ps), bname(b, X.ots, b.slot)
        local n1, n2 = pname(praw, P.nicks, ps), bname(b, X.nicks, b.slot)
        for i = 1, NAME do if a1[i] ~= a2[i] or n1[i] ~= n2[i] then return false end end
        return true
    end
    local function mail(item) return p.mail[item] == true end
    -- RemoveMonFromPartyOrBox also shifts sPartyMail (:1336-1370); SLink never writes party mail, so a
    -- removal refuses while the removed mon or any later one holds mail. Stricter than the native PC,
    -- which refuses only a selected mail holder (C engine/pokemon/bills_pc.asm:1595-1616,
    -- PCString_RemoveMail) and SHIFTS sPartyMail for the rest (move_mon.asm:1336-1370). (OMP BOX F5)
    local function no_mail_from(praw, s)
        for slot = s, praw[1] - 1 do
            if mail(praw[P.records + slot * STRIDE + c.MON_ITEM + 1]) then
                refuse("mail holder in the party (party mail is never shifted; T-3)")
            end
        end
    end
    local function removed(raw, s)
        local count, out = raw[1], {}
        for i, b in ipairs(raw) do out[i] = b end
        out[1] = count - 1
        for position = s + 2, count + 1 do out[position] = raw[position + 1] end
        if s == CAP - 1 then
            out[P.ots + s * NAME + 1] = 255
        else
            for _, f in ipairs({{P.records, STRIDE}, {P.ots, NAME}, {P.nicks, NAME}}) do
                for position = f[1] + s * f[2] + 1, f[1] + (CAP - 1) * f[2] do out[position] = raw[position + f[2]] end
            end
        end
        return out
    end
    local function write_party(bytes)
        p.writes:arm("box-party")
        local ok, err = pcall(p.writes.write_party_block, p.writes, bytes)
        p.writes:disarm()
        if not ok then error(err, 0) end
    end
    local function payload(praw, s)
        local rec = prec(praw, s)
        local out = {}
        for i = 1, c.BOXMON_STRUCT_LENGTH do out[i] = rec[i] end
        for m = 1, c.NUM_MOVES do
            local move = out[c.MON_MOVES + m]
            if move == 0 then break end
            local base, ups = p.move_pp(move), math.floor(out[c.MON_PP + m] / 64)
            out[c.MON_PP + m] = ups * 64 + base + ups * math.min(math.floor(base / 5), 7)
        end
        return {bytes = out, ot = pname(praw, P.ots, s), nickname = pname(praw, P.nicks, s),
                species_marker = praw[2 + s]}
    end
    -- ponytail (OMP BOX F3): the level is the record's byte, not CalcLevel(exp) (move_mon.asm:649-655);
    -- they differ only for a glitched exp/level pair. The pad byte after MON_STATUS is zeroed too (the
    -- native leaves it); a byte-wise oracle against a native withdraw must mask +33.
    local function party_record(b)
        local rec = brec(b, b.slot)
        local level, species = rec[c.MON_LEVEL + 1], rec[c.MON_SPECIES + 1]
        local base = p.base_stats(species)
        local dv1, dv2 = rec[c.MON_DVS + 1], rec[c.MON_DVS + 2]
        local atk, def, spd, spc = math.floor(dv1 / 16), dv1 % 16, math.floor(dv2 / 16), dv2 % 16
        local hp_dv = (atk % 2) * 8 + (def % 2) * 4 + (spd % 2) * 2 + spc % 2
        local function statexp(offset) return rec[offset + 1] * 256 + rec[offset + 2] end
        local rows = {{base.hp, hp_dv, c.MON_HP_EXP}, {base.attack, atk, c.MON_ATK_EXP},
                      {base.defense, def, c.MON_DEF_EXP}, {base.speed, spd, c.MON_SPD_EXP},
                      {base.special_attack, spc, c.MON_SPC_EXP}, {base.special_defense, spc, c.MON_SPC_EXP}}
        local out = {}
        for i = 1, STRIDE do out[i] = rec[i] or 0 end
        out[c.MON_STATUS + 1], out[c.MON_STATUS + 2] = 0, 0
        for i, row in ipairs(rows) do
            -- GetSquareRoot: the first b in 1..254 with b*b >= stat exp, else 255.
            local e, root = statexp(row[3]), 255
            for b = 1, 254 do if b * b >= e then root = b; break end end
            local v = math.floor(((row[1] + row[2]) * 2 + math.floor(root / 4)) * level / 100)
            v = math.min(999, v + (i == 1 and level + 10 or 5))
            local at = c.MON_MAXHP + (i - 1) * 2
            out[at + 1], out[at + 2] = math.floor(v / 256), v % 256
        end
        out[c.MON_HP + 1], out[c.MON_HP + 2] = out[c.MON_MAXHP + 1], out[c.MON_MAXHP + 2]
        return out, bname(b, X.ots, b.slot), bname(b, X.nicks, b.slot), b.raw[2 + b.slot]
    end
    local function inserted(raw, rec, ot, nick, marker)
        local n, out = raw[1], {}
        for i, b in ipairs(raw) do out[i] = b end
        out[1], out[2 + n], out[3 + n] = n + 1, marker, 255
        for i = 1, STRIDE do out[P.records + n * STRIDE + i] = rec[i] end
        for i = 1, NAME do out[P.ots + n * NAME + i], out[P.nicks + n * NAME + i] = ot[i], nick[i] end
        return out
    end
    local function commit(plan) p.box.commit(plan) end

    local ops = {}
    function ops.deposit(key)
        local cur = current()
        local praw, pmons = party()
        local ps, hit = find(pmons, key), boxed(key, cur)
        if not ps then
            if hit then return true end
            refuse("key not in party")
        end
        if praw[1] <= 1 then refuse("last party mon") end
        if hit then
            -- a reset-interrupted deposit, or the box copy saved into another slot by a box change (F4):
            -- the box holds the intended copy, so the party copy goes, in any box, on a full-record match
            if not same(praw, ps, hit) then refuse("key exists in both party and box") end
            need("party_collection")
            no_mail_from(praw, ps)
            write_party(removed(praw, ps))
            return true
        end
        no_mail_from(praw, ps)
        local b = load_box(cur, cur)
        if #b.list >= c.MONS_PER_BOX then refuse("current box full") end
        need("party_collection", "box_deposit")
        commit(p.box.plan_deposit(state(cur), cur, b.raw, payload(praw, ps)))
        write_party(removed(praw, ps))
        return true
    end
    -- Durability (OMP BOX review F1): a backing sBoxN is plain SRAM, durable at once, while the party is
    -- WRAM until the next native SAVE. Removing the box copy before that save loses the mon on a reset
    -- (the saved party lacks it, the slot lost it). With opts.defer_backing the party copy is written now
    -- and the box copy stays (a duplicate, never a loss); the caller settles it after the save witness.
    -- An active-sBox withdraw needs no deferral: LoadBox restores the active copy from its backing slot.
    function ops.withdraw(key, opts)
        local cur = current()
        local praw, pmons = party()
        local ps, hit = find(pmons, key), boxed(key, cur)
        local kind = hit and (hit.active and "box_withdraw" or "backing_box")
        if ps then
            if not hit then return true end
            if not same(praw, ps, hit) then refuse("key exists in both party and box") end
            need(kind)
            commit(p.box.plan_withdraw(state(cur), hit.index, hit.raw, hit.slot))
            return true
        end
        if not hit then refuse("key not boxed") end
        if praw[1] >= CAP then refuse("party full") end
        local rec, ot, nick, marker = party_record(hit)
        if mail(rec[c.MON_ITEM + 1]) then refuse("boxed mon holds mail (T-3)") end
        need("party_collection", kind)
        write_party(inserted(praw, rec, ot, nick, marker))
        if not hit.active and type(opts) == "table" and opts.defer_backing == true then
            return true, "backing removal deferred to the save witness"
        end
        commit(p.box.plan_withdraw(state(cur), hit.index, hit.raw, hit.slot))
        return true
    end
    -- After a native SAVE witnessed the party: drop the box copy of a party mon (full-record match), the
    -- deferred half of a backing withdraw. No party copy (a reset before the save) or no box copy: nothing.
    function ops.settle(key)
        local cur = current()
        local praw, pmons = party()
        local ps, hit = find(pmons, key), boxed(key, cur)
        if not ps or not hit then return true end
        if not same(praw, ps, hit) then refuse("key exists in both party and box") end
        need(hit.active and "box_withdraw" or "backing_box")
        commit(p.box.plan_withdraw(state(cur), hit.index, hit.raw, hit.slot))
        return true
    end
    function ops.memorialize(key)
        local cur = current()
        local praw, pmons = party()
        local ps, mem = find(pmons, key), load_box(MEMORIAL, cur)
        mem.slot = find(mem.list, key)
        if not ps then
            if mem.slot then return true end
            refuse("key not in party")
        end
        if praw[1] <= 1 then refuse("last party mon") end
        no_mail_from(praw, ps)
        if mem.slot then
            if not same(praw, ps, mem) then refuse("key exists in both party and memorial box") end
            need("party_collection")
            write_party(removed(praw, ps))
            return true
        end
        if #mem.list >= c.MONS_PER_BOX then refuse("memorial box full") end
        -- A box copy of this mon elsewhere is an unsettled deferred withdraw's source: it goes too, after
        -- the memorial and the party (a reset in between leaves a duplicate, never a loss).
        local source = boxed(key, cur)
        if source and not same(praw, ps, source) then refuse("key exists in both party and box") end
        need("party_collection", mem.active and "box_deposit" or "backing_box")
        if source then need(source.active and "box_withdraw" or "backing_box") end
        local st = state(cur)
        commit(mem.active and p.box.plan_deposit(st, MEMORIAL, mem.raw, payload(praw, ps))
               or p.box.plan_memorial(st, mem.raw, payload(praw, ps)))
        write_party(removed(praw, ps))
        if source then commit(p.box.plan_withdraw(state(cur), source.index, source.raw, source.slot)) end
        return true
    end

    local self = {memorial_box = MEMORIAL}
    for name, fn in pairs(ops) do
        self[name] = function(key, opts)
            local ok, result, note = pcall(fn, key, opts)
            if ok then return result, note end
            return nil, tostring(result)
        end
    end
    return self
end

return B
