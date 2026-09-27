-- Read-only checkpoint. Pack semantics: docs/gen3_write_checkpoint.md §4;
-- ROM offsets (not anchor.address) select bytes, including frame_control's slice.
local S = {}
local anchors = {"cb1_overworld", "cb2_overworld", "frame_control", "run_tasks", "try_saving_data"}
-- The contract: this list defines both the checked SET of overworld predicates and the
-- first-failure PRIORITY order (deliberate, not alphabetical) -- pack.predicates must match
-- it exactly, checked both ways in overworld()'s preamble.
local predicates = {"callback1", "callback2", "field_controls_locked", "in_battle",
    "link_callback", "link_transferring", "palette_fade_active",
    "link_players_received", "script_context_status", "soft_reset_disabled"}
local known_predicates = {}
for _, name in ipairs(predicates) do known_predicates[name] = true end
-- The battle clause SET (REV-C5-RR-BW-FIX 1), checked both ways in battle() before anything is
-- evaluated: a pack missing one (the generator dropped an unproven pin) or carrying an unknown
-- one refuses as "pack", never runs a weaker set. Evaluation order stays the pack's.
local battle_clauses = {"battle_main_func", "battle_comm_0", "battle_exec_flags_input",
    "battle_input_controller", "battle_not_link", "battle_engine_loaded", "battle_outcome_open"}
local known_battle_clauses = {}
for _, name in ipairs(battle_clauses) do known_battle_clauses[name] = true end
local battle_compares = {eq = true, eq_rom = true, eq_symbol = true, nonzero = true}
local function uint(v, limit)
    assert(type(v) == "number" and v % 1 == 0 and v >= 0 and v <= limit, "unreadable integer")
    return v
end
-- pairs() order is unspecified; anything that turns iteration order into a returned or logged
-- value (an assert message, a first-failure reason) must walk keys in a fixed order instead.
-- No canonical order is defined for these string-keyed tables, so alphabetical is the fallback.
local function sorted_pairs(t)
    local keys = {}
    for k in pairs(t) do keys[#keys + 1] = k end
    table.sort(keys)
    local i = 0
    return function()
        i = i + 1
        if keys[i] == nil then return nil end
        return keys[i], t[keys[i]]
    end
end
function S.new(pack, deps, kind)
    local self = {}
    local function read(addr, width, domain)
        uint(addr, 4294967295)
        local names = {[1] = "read_u8", [2] = "read_u16_le", [4] = "read_u32_le"}
        local fn = assert(deps.io[assert(names[width], "invalid width")])
        return uint(fn(addr, domain or "System Bus"), 256 ^ width - 1)
    end
    local function pointers()
        local p, out = assert(pack.pointers), {}
        assert(p.gSaveBlock1Ptr and p.gSaveBlock2Ptr, "missing save pointers")
        assert(p.gPokemonStoragePtr or p.pokemon_storage_base, "missing storage location")
        for name, spec in sorted_pairs(p) do
            local value = name == "pokemon_storage_base" and uint(spec.address, 4294967295)
                or read(spec.address, 4)
            assert(value > 0 and value % 4 == 0, "invalid pointer: " .. name)
            out[name] = value
        end
        return out
    end
    -- Snapshot is opaque to writers. Failure returns nil, reason; never a partial snapshot.
    function self:snapshot()
        local ok, result = pcall(pointers)
        if ok then return result end
        return nil, tostring(result)
    end
    -- Refusal returns false, reason: the first failure in check order (callers match on it).
    -- self.last_clauses is the sorted list of EVERY failing clause key of the last check:
    -- predicate names, "cpu", "task", "native", "pointer", or {"pack"} when the pack/ROM
    -- preamble fails (nothing after it is evaluated); {} on accept. Refuse iff any clause fails.
    -- The G3-signed overworld predicate, VERBATIM: same clause order, same messages, same
    -- last_clauses keys as before the reason dispatch existed. Any edit in this
    -- function invalidates the G3 receipts; tests/unit/test_gen3_safety.py pins the
    -- accept/refuse result and the clause keys for a matrix of failing clauses.
    local function overworld(snapshot)
        self.last_clauses = {}
        local ok, result = pcall(function()
            assert(pack.version == "gen3-overworld-v1", "unsupported checkpoint")
            assert(type(kind) == "string", "artifact kind required")
            for _, name in ipairs(anchors) do assert(pack.anchors[name], "missing anchor: " .. name) end
            for _, a in sorted_pairs(pack.anchors) do
                local hex = assert(a.expected_hex[kind], "unverified artifact anchor")
                assert(#hex > 0 and #hex == a.length * 2 and not hex:find("[^%x]"), "invalid anchor bytes")
                for i = 1, a.length do
                    assert(read(a.rom_offset + i - 1, 1, "ROM") == tonumber(hex:sub(i * 2 - 1, i * 2), 16),
                        "ROM anchor differs")
                end
            end
            for _, name in ipairs(predicates) do assert(pack.predicates[name], "missing predicate: " .. name) end
            -- Coverage guard: the clause loop below only walks the module's fixed list, so a
            -- pack predicate NOT in that list would otherwise be silently skipped (never
            -- evaluated, never refused) instead of refusing the whole checkpoint.
            for name in sorted_pairs(pack.predicates) do assert(known_predicates[name], "unknown predicate: " .. name) end
        end)
        if not ok then self.last_clauses = {"pack"}; return false, tostring(result) end
        -- Every clause is evaluated (reads only), so the refusal names all of them.
        local failed, first = {}, nil
        local function clause(key, fn)
            local good, why = pcall(fn)
            if not good then failed[#failed + 1] = key; first = first or tostring(why) end
        end
        for _, name in ipairs(predicates) do
            local p = pack.predicates[name]
            clause(name, function()
                local value = read(p.address + p.offset, p.width)
                if p.mask then value = value & uint(p.mask, 256 ^ p.width - 1) end
                assert(value == p.expect, "forbidden state: " .. name)
            end)
        end
        -- One parked range per title, from the pack. A frame end taken inside an IRQ handler
        -- fails the mode test on purpose; the next parked frame admits (checkpoint doc §4.3).
        clause("cpu", function()
            local cpu, regs = assert(pack.cpu), deps.regs()
            local pc, cpsr = uint(regs.R15, 4294967295), uint(regs.CPSR, 4294967295)
            local parked = cpsr % 32 == cpu.mode and math.floor(cpsr / 32) % 2 == cpu.thumb
                and pc >= cpu.pc_min and pc <= cpu.pc_max
            -- G5-RR-CPU-IRQ (owner ruling 23): a pack may also admit the IRQ vector entry, but only
            -- when the banked return address (R14 of the IRQ bank) - 4 is inside the halt it
            -- interrupted; an interrupt taken from game code stays refused (a write may be mid-way).
            -- G5-CPU-HARDEN: RR-only by construction (the shape is pinned to RR's HLE-BIOS halt), so a
            -- pack not titled radical_red that carries irq_entry is refused, never honoured; R14_irq
            -- of an ARM-state IRQ is a word address, so an unaligned one is not that halt's return.
            -- X3: the expansion reference build is the one other title (IntrWait's halt, R14 0x1F8,
            -- docs/gen3_emerald/probes/exp_cpu_irq_bios_2026-09-27.txt); still exact titles only.
            local irq = (pack.title == "radical_red" or pack.title == "emerald_expansion_28877d73")
                and cpu.irq_entry or nil
            if not parked and irq and cpsr % 32 == irq.mode and math.floor(cpsr / 32) % 2 == irq.thumb then
                local lr, at_vector = uint(regs.R14, 4294967295), false
                for _, v in ipairs(irq.pc) do at_vector = at_vector or pc == v end
                parked = at_vector and lr % 4 == 0 and lr >= irq.lr_min and lr <= irq.lr_max
            end
            assert(parked, "CPU outside parked checkpoint")
        end)
        clause("task", function()
            local t, allowed = assert(pack.tasks), {}
            for _, address in pairs(t.allowed_overworld_tasks) do allowed[uint(address, 4294967295)] = true end
            assert(next(allowed), "empty task allow-list")
            assert(uint(t.count, 256) > 0 and uint(t.struct_size, 65535) > 0, "invalid task layout")
            for i = 0, t.count - 1 do
                local base = t.address + i * t.struct_size
                if read(base + t.is_active_offset, 1) ~= 0 then
                    local fn = read(base + t.func_offset, 4)
                    assert(fn % 2 == 1 and allowed[fn - 1], "unknown active task")
                end
            end
        end)
        clause("native", function()
            assert(deps.native_idle() == true, "native transaction in flight or unreadable")
        end)
        clause("pointer", function()
            local current = pointers()
            if snapshot then
                for name, value in sorted_pairs(current) do assert(snapshot[name] == value, "pointer moved: " .. name) end
                for name in sorted_pairs(snapshot) do assert(current[name] ~= nil, "pointer layout changed") end
            end
        end)
        table.sort(failed)
        self.last_clauses = failed
        if first then return false, first end
        return true, "verified overworld checkpoint"
    end
    -- ── the other reasons: docs/gen3/research/battle_write_predicate.md §5 ──────────────────
    -- Shared preamble: the ROM anchors are re-verified for every reason (a cached positive must
    -- never survive a changed ROM), then the reason's own block must exist. The pointer clause
    -- is NOT here: the battle sets write the party (a fixed EWRAM base, gPlayerParty) and the
    -- native/sound sets write arenas that are not behind a save pointer.
    local function preamble(block)
        assert(pack.version == "gen3-overworld-v1", "unsupported checkpoint")
        assert(type(kind) == "string", "artifact kind required")
        for _, name in ipairs(anchors) do assert(pack.anchors[name], "missing anchor: " .. name) end
        for _, a in sorted_pairs(pack.anchors) do
            local hex = assert(a.expected_hex[kind], "unverified artifact anchor")
            assert(#hex > 0 and #hex == a.length * 2 and not hex:find("[^%x]"), "invalid anchor bytes")
            for i = 1, a.length do
                assert(read(a.rom_offset + i - 1, 1, "ROM") == tonumber(hex:sub(i * 2 - 1, i * 2), 16),
                    "ROM anchor differs")
            end
        end
        if block then assert(pack[block], "missing " .. block .. " block") end
    end

    local function value_of(spec, index)
        local offset = spec.offset or 0
        if index ~= nil then offset = offset + index end
        local value = read(spec.address + offset, spec.width)
        if spec.mask then value = value & uint(spec.mask, 256 ^ spec.width - 1) end
        return value
    end

    -- Every clause is evaluated (reads only); the refusal names all of them, sorted, exactly
    -- like the overworld path, so a probe's clause attribution works for every reason.
    local function run_clauses(entries)
        local failed, first = {}, nil
        for _, entry in ipairs(entries) do
            local ok, why = pcall(entry.fn)
            if not ok then
                failed[#failed + 1] = entry.key
                first = first or tostring(why)
            end
        end
        table.sort(failed)
        self.last_clauses = failed
        if first then return false, first end
        return true, "verified " .. tostring(entries.reason or "checkpoint")
    end

    local function clause_entries(block)
        local entries = {}
        for _, spec in ipairs(block) do
            entries[#entries + 1] = {key = spec.name, fn = function()
                local value = value_of(spec)
                if spec.compare == "nonzero" then
                    assert(value ~= 0, "forbidden state: " .. spec.name)
                else
                    assert(value == spec.expect, "forbidden state: " .. spec.name)
                end
            end}
        end
        return entries
    end

    -- G4-PH (docs/gen3/research/rr_active_faint_parity_scope_2026-09-23.md §3.2, §5.3): the pack's
    -- battle.handoff is the one controller-slot write a battle_commit plan may carry, and only as
    -- the LAST entry of exactly the P+H plan. BATTLER 0 ONLY (R1 M1): every battle clause pins
    -- battler 0, so slot 0 is the only slot a clause proves parked.
    -- Returns {address, width, value}, or nil (absent / malformed / battler ~= 0).
    local function input_controller()
        for _, c in ipairs(pack.battle and pack.battle.clauses or {}) do
            if c.name == "battle_input_controller" then return c end
        end
    end
    local head_rules = {set = true, keep = true, value = true}
    -- P head rows: an address and exactly one rule (set / keep / value). Explode head rows
    -- (G5-EXPLODE-HANDOFF): an address XOR a ptr + offset, a value, and an optional group "moves".
    local function valid_rows(rows, explode)
        assert(type(rows) == "table" and #rows > 0)
        for _, row in ipairs(rows) do
            assert(row.width == 1 or row.width == 2 or row.width == 4)
            if explode then
                assert((row.address == nil) ~= (row.ptr == nil))
                if row.ptr then uint(row.ptr, 4294967295); uint(row.offset, 65535)
                else uint(row.address, 4294967295) end
                uint(row.value, 256 ^ row.width - 1)
                assert(row.group == nil or row.group == "moves")
            else
                uint(row.address, 4294967295)
                local rules = 0
                for rule in pairs(head_rules) do
                    if row[rule] ~= nil then rules = rules + 1; uint(row[rule], 256 ^ row.width - 1) end
                end
                assert(rules == 1)
            end
        end
    end
    -- shape nil = P's hand-off; "explode" = the same entry, only when the pack also proves the
    -- Explode+H shape (RR, owner ruling 19)
    local function handoff_entry(battler, shape)
        local h = type(pack.battle) == "table" and pack.battle.handoff
        if type(h) ~= "table" or battler ~= 0 or (shape ~= nil and shape ~= "explode") then return nil end
        local ok, entry = pcall(function()
            local ctrl = assert(input_controller())
            assert(uint(h.address, 4294967295) == ctrl.address + (ctrl.offset or 0))
            assert(h.stride == 4 and h.width == 4 and uint(h.value, 4294967295) % 2 == 1)
            -- R1 L1: the P head the plan must carry (generator: data/games/*/profile.json)
            assert(type(h.head) == "table" and #h.head == 3)
            valid_rows(h.head, false)
            if shape == "explode" then
                assert(type(h.explode) == "table")
                valid_rows(h.explode.head, true)
                -- F1 M4: the shape must pin its chosen action outside the all-or-none "moves"
                -- group, or an all-grouped head would admit [comm, hand-off] alone. G5-CPU-HARDEN:
                -- exactly one such row, and exactly the generator's: a direct address (a ptr row
                -- vanishes while its pointer reads 0), P's no_op_action address (both are
                -- CHOSEN_ACTION_ADDR), width 1, value B_ACTION_USE_MOVE = 0.
                local no_op
                for _, row in ipairs(h.head) do if row.name == "no_op_action" then no_op = row end end
                assert(no_op)
                local pinned = 0
                for _, row in ipairs(h.explode.head) do
                    if row.name == "chosen_action" then
                        assert(row.group == nil and row.ptr == nil and row.address == no_op.address
                            and row.width == 1 and row.value == 0)
                        pinned = pinned + 1
                    end
                end
                assert(pinned == 1)
            end
            return {h.address, h.width, h.value}
        end)
        if ok then return entry end
    end
    function self:handoff_entry(battler, shape) return handoff_entry(battler, shape) end
    -- R1 L2: a GBA bus alias is the same byte. IWRAM (0x03xxxxxx) repeats every 0x8000 and EWRAM
    -- (0x02xxxxxx) every 0x40000; fold both onto their base range before comparing.
    local function canonical(addr)
        if addr >= 0x03000000 and addr < 0x04000000 then return 0x03000000 + addr % 0x8000 end
        if addr >= 0x02000000 and addr < 0x03000000 then return 0x02000000 + addr % 0x40000 end
        return addr
    end
    -- does any plan entry write a controller slot (the 4 words from the controller pin, through
    -- any mirror)? A malformed plan counts as touching, so the hand-off clause judges (and refuses) it.
    local function touches_slots(plan)
        if plan == nil then return false end
        local ok, hit = pcall(function()
            local ctrl = input_controller()
            local lo = canonical(ctrl.address + (ctrl.offset or 0))
            for _, w in ipairs(plan) do
                local a = canonical(w[1])
                if a < lo + 16 and a + w[2] > lo then return true end
            end
            return false
        end)
        return not ok or hit
    end
    -- R1 L1: the WHOLE plan, row for row, must be one of the pack's shapes, then the commit write
    -- (the guard's byte := its value), then the hand-off. Live values are read on this same frame;
    -- the client read them to build the plan.
    --   P+H: status3 = live | PERISH, timer = live & 0xF0, action = NOTHING_FAINTED.
    --   Explode+H (G5-EXPLODE-HANDOFF, only where the pack carries handoff.explode): commit_plan's
    --   rows; the "moves" group is all-or-none, a ptr row sits at read_u32(ptr) + offset and is
    --   absent while that pointer reads 0 (commit_plan's own rules).
    local function p_rows()
        local rows = {}
        for i, row in ipairs(pack.battle.handoff.head) do
            local v = row.value
            if row.set then v = read(row.address, row.width) | row.set end
            if row.keep then v = read(row.address, row.width) & row.keep end
            rows[i] = {row.address, row.width, v, row.name}
        end
        return rows
    end
    local function explode_rows(with_moves)
        local rows = {}
        for _, row in ipairs(pack.battle.handoff.explode.head) do
            if row.group ~= "moves" or with_moves then
                local addr = row.address
                if row.ptr then
                    local base = read(row.ptr, 4)
                    addr = base ~= 0 and base + row.offset or nil
                end
                if addr then rows[#rows + 1] = {addr, row.width, row.value, row.name} end
            end
        end
        return rows
    end
    local function matches(plan, head, entry, battler)
        local guard = pack.battle.commit_guard
        local want = {}
        for i, w in ipairs(head) do want[i] = w end
        want[#want + 1] = {guard.address + (guard.offset or 0) + battler, guard.width, guard.value, "commit"}
        want[#want + 1] = {entry[1], entry[2], entry[3], "hand-off"}
        if #plan ~= #want then return false, #plan .. " rows, want " .. #want end
        for i, w in ipairs(want) do
            local got = plan[i]
            if not (got[1] == w[1] and got[2] == w[2] and got[3] == w[3]) then
                return false, "row " .. i .. " is not the " .. w[4] .. " write"
            end
        end
        return true
    end
    local function check_handoff_plan(plan, battler)
        assert(battler == 0, "the hand-off is battler 0 only")
        local entry = assert(handoff_entry(battler), "no proven battle.handoff")
        local ok, why = matches(plan, p_rows(), entry, battler)
        if ok then return end
        why = "not the P+H plan: " .. why
        if handoff_entry(battler, "explode") then
            for _, with_moves in ipairs({true, false}) do
                if matches(plan, explode_rows(with_moves), entry, battler) then return end
            end
            why = why .. "; nor the Explode+H plan"
        end
        error(why, 0)
    end

    local function battle(reason, snapshot, args)
        self.last_clauses = {}
        local ok, result = pcall(function()
            preamble("battle")
            local block = pack.battle
            assert(block.version == "gen3-battle-v1", "unsupported battle block")
            assert(type(block.clauses) == "table", "missing battle clauses")
            local seen = {}
            for _, spec in ipairs(block.clauses) do
                local name = spec.name
                assert(known_battle_clauses[name], "unknown battle clause: " .. tostring(name))
                assert(not seen[name], "duplicate battle clause: " .. name)
                assert(battle_compares[spec.compare], "unsupported battle compare: " .. name)
                assert(spec.compare == "nonzero" or type(spec.expect) == "number",
                    "battle clause without expect: " .. name)
                seen[name] = true
            end
            for _, name in ipairs(battle_clauses) do assert(seen[name], "missing battle clause: " .. name) end
            assert(block.commit_hold == nil or type(block.commit_hold) == "string", "invalid commit_hold")
            if reason == "battle_commit" then assert(block.commit_guard, "missing battle commit guard") end
        end)
        if not ok then self.last_clauses = {"pack"}; return false, tostring(result) end
        local entries = clause_entries(pack.battle.clauses)
        if reason == "battle_commit" then
            -- REV-C5-RR-BW-FIX 2: a pack may HOLD battle_commit outright (RR: CFRU's parked
            -- controller outlives the commit). A clause, not an early return, so last_clauses
            -- still names every other failure alongside it.
            local hold = pack.battle.commit_hold
            local guard = pack.battle.commit_guard
            local battler = args and args.battler
            local plan = args and args.plan
            if touches_slots(plan) then
                -- G4-PH §5.3 + R1 M1/L1: a plan that writes a controller slot must be exactly the
                -- battler-0 P+H plan; that clause REPLACES the hold (RR), and judges every such plan (FR/LG).
                -- A plan without a slot write (Explode, the pre-hand-off P) is untouched.
                entries[#entries + 1] = {key = "battle_commit_handoff", fn = function()
                    local ok, why = pcall(check_handoff_plan, plan, battler)
                    if not ok then
                        error((hold or "battle_commit refused") .. " (hand-off tail: " .. tostring(why) .. ")", 0)
                    end
                end}
            elseif hold then
                entries[#entries + 1] = {key = "battle_commit_hold", fn = function() error(hold, 0) end}
            end
            entries[#entries + 1] = {key = "battle_commit_guard", fn = function()
                assert(type(battler) == "number" and battler % 1 == 0 and battler >= 0 and battler <= 3,
                    "battle_commit needs a battler 0..3")
                local value = value_of(guard, battler)
                assert(value < guard.value, "committed past the guard: " .. tostring(value))
            end}
        end
        entries.reason = reason
        return run_clauses(entries)
    end

    local function native()
        self.last_clauses = {}
        if not pack.native then
            self.last_clauses = {"native_present"}
            return false, "no native block in this pack (native bytes belong to the companion)"
        end
        local ok, result = pcall(preamble, "native")
        if not ok then self.last_clauses = {"pack"}; return false, tostring(result) end
        local n = assert(pack.native, "missing native block")
        assert(n.version == "gen3-native-v1", "unsupported native block")
        local entries = {
            {key = "native_present", fn = function()
                assert(kind == "companion", "native bytes belong to the companion artifact")
                assert(read(n.base, 4) == n.sig, "companion signature absent")
                assert(read(n.base + n.abi_off, 2) == n.abi, "companion ABI differs")
            end},
            {key = "native_idle", fn = function()
                assert(read(n.base + n.opcode_off, 2) == 0, "mailbox opcode pending")
                assert(read(n.base + n.status_off, 2) ~= n.busy, "mailbox status busy")
                assert(read(n.info + n.info_drawn_off, 1) == read(n.info + n.info_ack_off, 1),
                    "panel handshake differs")
            end},
        }
        return run_clauses(entries)
    end

    local function sound(args)
        self.last_clauses = {}
        local ok, result = pcall(preamble, "sound")
        if not ok then self.last_clauses = {"pack"}; return false, tostring(result) end
        local s = assert(pack.sound, "missing sound block")
        assert(s.version == "gen3-sound-v1", "unsupported sound block")
        local player = (args and args.player)
            or (s.player_se1 and s.player_se1.address)
        local track = (args and args.track)
            or (player and read(player + s.tracks_off, 4))
        local function in_iwram(address)
            return type(address) == "number" and address >= s.iwram_min and address < s.iwram_max
        end
        local entries = {
            {key = "sound_player_ready", fn = function()
                assert(in_iwram(player), "no SE1 player resolved")
                assert(read(player + s.ident_off, 4) == s.ident_magic, "m4a driver not initialised")
            end},
            {key = "sound_addresses_in_iwram", fn = function()
                if player == nil then return end   -- unresolved is named by sound_player_ready
                assert(in_iwram(player), "player outside IWRAM")
                assert(in_iwram(track), "track outside IWRAM")
            end},
        }
        return run_clauses(entries)
    end

    -- The reason selects the clause set. "overworld" (or nil) is the G3-signed predicate and
    -- keeps its exact behaviour; an unknown reason refuses by name rather than guessing.
    function self:check(snapshot, reason, args)
        local which = reason or "overworld"
        if which == "overworld" then return overworld(snapshot) end
        if which == "battle_faint" or which == "battle_commit" then return battle(which, snapshot, args) end
        if which == "native" then return native() end
        if which == "sound" then return sound(args) end
        self.last_clauses = {"reason"}
        return false, "unknown write reason: " .. tostring(which)
    end
    return self
end
return S
