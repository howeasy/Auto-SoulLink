-- Polished Crystal 3.2.3 battle wiring (POL-BATTLE): the Explode Mode (W-3) and Rival Team Swap (W-4)
-- writers bound to the engine sites the composed client registers. Pure: no emulator globals, no I/O of its
-- own beyond the injected io, no activation.
--
-- WHY A SEPARATE MODULE. lua/gen2/signals.lua S.new_polished owns OBSERVATION: it registers sites under the
-- DEV_OVERLAY_SHA1 admission and publishes facts. lua/gen2/polished_writes.lua owns the WRITES: it asserts the
-- gate PC it was armed at, the reason, the ownership policy and the Mirror Herb exclusion, then writes
-- through the shared permit. Neither may depend on the other. This module is the seam between them: it turns
-- the two write-window site hits into writer calls, IN the engine's own CPU hold, because both windows are
-- mid-frame (SendInUserPkmn copies the party into the battle struct inside one routine -- the vanilla client
-- parks a reply and lands it at a frame end instead, which is not transferable; EXPLODE_RIVAL.md 10.4).
--
-- THE SEAM (what lua/gen2/entry.lua compose_polished calls; this card does not edit entry.lua):
--
--   local battle = PolishedBattle.compose({
--       root   = root, io = io_, profile = profile, pack = pack, hold = hold,
--       coords = coords,                        -- {label = {bank, addr}} covering polished_writes.W.COORDS
--       Permit = Permit, policy = policy,        -- OPTIONAL: omit BOTH and this composes INERT
--       seams  = {pending_explode=fn, pending_rival=fn, exploded=fn, rival_applied=fn, rival_refused=fn},
--       log    = deps.log,
--   })
--   local binder = Signals.new_polished({... , battle_sites = battle.sites,
--                                          on_write_window = battle.on_write_window})
--   -- battle.writes is the writer; nothing here arms it on its own, and the coordinator's write card owns
--   -- whether it is composed at all.
--
-- `seams` is the ONLY thing this module asks of the client, because the client's queues are its own:
--   pending_explode() -> party slot the server ordered force_explode for, or nil
--   pending_rival()   -> array of {record=48 bytes, ot=11, nick=11} (polished_codec.encode_party_mon), or nil
--   exploded(slot) / rival_applied(mons) / rival_refused(why) / explode_refused(why) -- report back
-- lua/gen2/client.lua already keeps exactly these: `pending_battle_writes` (cmd == "force_explode" -> slot)
-- and `self.rival.pending` (client.lua replace_rival_team).
--
-- INERT BY CONSTRUCTION. Without Permit AND policy there is no writer, writes_enabled is false, and
-- on_write_window answers nil for every site: the sites may still be registered for their OBSERVATIONS, but
-- no write is ever armed and no write event is ever published.
--
-- Spec: docs/polished/BATTLE_FLOW.md 1.2-1.3 (the copyback boundary), docs/polished/EXPLODE_RIVAL.md 6
-- (priority resolves through wCurPlayerMove), 9.1 (explode write order), 10.4-10.5 (the rival PC gate).
local B = {}

-- polished_writes.lua's snapshot contract names its own fields; these are the RAM labels behind each one.
local FIELDS = {wBattlePlayerAction = "player_action", wCurBattleMon = "active_slot", wCurMoveNum = "move_num",
                wCurOTMon = "cur_ot_mon"}

-- The sites this module asks the binder for, in the order they appear in a turn.
B.SITES = {"battle_faint", "battle_end", "wild_ready", "trainer_ready", "explode_hold", "rival_swap_gate"}
-- The two of them that are write windows, and the reason each one may write at.
B.WINDOWS = {explode_hold = "battle_hold", rival_swap_gate = "rival_swap"}
-- Labels this module reads itself (the writer reads the rest of W.COORDS).
B.READS = {"wBattleMode", "wLinkMode", "wCurBattleMon", "wCurMoveNum", "wBattlePlayerAction", "wCurOTMon"}

local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

local function callable(value) return type(value) == "function" or type(value) == "userdata" end

local function copy(value)
    if type(value) ~= "table" then return value end
    local out = {}
    for key, item in pairs(value) do out[key] = copy(item) end
    return out
end

-- deps: root, io, profile, coords, pack, hold, Permit, policy, seams, log. Returns self.
function B.compose(deps)
    assert(type(deps) == "table", "Polished battle wiring options required")
    local root, io_, log = assert(deps.root), assert(deps.io), deps.log
    local profile, coords, pack, hold = assert(deps.profile), assert(deps.coords), assert(deps.pack), assert(deps.hold)
    assert(profile.title == "polished" and type(profile.ram) == "table" and type(profile.ram_bank) == "table",
           "generated Polished profile required")
    assert(pack.schema == "polished-engine-signals-v1" and pack.runtime_admission == "NOT_GRANTED",
           "generated Polished engine-site pack required")
    assert(type(hold) == "table" and type(hold.titles) == "table"
           and type(hold.titles.polished_crystal) == "table", "generated Polished write checkpoint required")
    local battle_hold = assert(hold.titles.polished_crystal.battle_hold, "battle_hold checkpoint required")
    local sites = assert(pack.titles.polished_crystal.sites, "Polished engine sites required")

    -- The gate a write may land at comes from the CHECKPOINT, the site that observes it from the SIGNALS pack;
    -- both are re-derived here and must agree, so neither can drift into a write at the other's PC.
    local gate = {}
    for id in pairs(B.WINDOWS) do
        local row = assert(sites[id], id .. ": absent from the generated Polished engine-site pack")
        local checkpoint = id == "explode_hold" and battle_hold.execution_before or battle_hold.rival_swap_gate
        assert(type(checkpoint) == "table" and integer(row.bank, 1, 255) and integer(row.addr, 0x4000, 0x7FFF),
               id .. ": gate coordinates required")
        assert(row.bank == checkpoint.bank and row.addr == checkpoint.pc,
               id .. ": the engine-site pack and the write checkpoint name different PCs")
        assert(type(row.find_hex) == "string" and row.expected_hex == row.find_hex,
               id .. ": the gate PC must be pinned by byte sequence")
        gate[id] = {bank = row.bank, pc = row.addr, rom_offset = row.rom_offset, reason = B.WINDOWS[id]}
    end

    local at, bank_of = {}, {}
    for label, row in pairs(coords) do
        at[label], bank_of[label] = row[2], row[1]
    end
    for _, label in ipairs(B.READS) do
        local addr = at[label] or profile.ram[label]
        local bank = bank_of[label] or profile.ram_bank[label]
        assert(integer(addr, 0xC000, 0xDFFF) and integer(bank, 0, 7), "no WRAM coordinate for " .. label)
    end

    -- The writer is OPTIONAL. Without it there is nothing to arm and this composition is inert.
    local writes, explosion = nil, nil
    if deps.Permit ~= nil or deps.policy ~= nil then
        assert(deps.Permit and deps.policy, "Permit and policy are required together")
        local W = dofile(root .. "/lua/gen2/polished_writes.lua")
        assert(integer(W.EXPLOSION, 0, 255), "the Polished explosion move id is missing")
        writes, explosion = assert(W.new(profile, coords, io_, deps.Permit, deps.policy, battle_hold)), W.EXPLOSION
    end
    local seams = deps.seams or {}
    if writes ~= nil then
        for _, name in ipairs({"pending_explode", "pending_rival"}) do
            assert(callable(seams[name]), "seams." .. name .. " is required to compose the battle writers")
        end
    end

    local function read(label)
        local addr = at[label] or profile.ram[label]
        local bank = bank_of[label] or profile.ram_bank[label]
        assert(io_.bank_valid(bank, addr, 1) == true, "read refused: " .. label .. " bank not mapped")
        return io_.read_u8(addr, "System Bus")
    end
    -- The engine is inside the gated instruction, so the snapshot the writer re-checks is read here, not later.
    local function snapshot(id, context, fields)
        local g = gate[id]
        assert(type(context) == "table" and context.bank == g.bank and context.pc == g.pc,
               id .. ": a write may only be attempted at its own PC")
        local result = {link_mode = read("wLinkMode"), mode = read("wBattleMode"), bank = g.bank, pc = g.pc}
        for _, label in ipairs(fields) do result[assert(FIELDS[label], "unknown snapshot field: "..label)] = read(label) end
        return result
    end

    local self = {sites = copy(B.SITES), writes = writes, writes_enabled = writes ~= nil,
                  explosion_move = explosion, gates = gate}

    local landed, refused = {}, {}

    -- Called by signals.lua INSIDE the hook, at the site PC. nil means "nothing owed": these sites fire on
    -- every turn / every send-out, so silence is the normal answer and only a landed write is published.
    function self.on_write_window(id, context)
        if writes == nil then return nil end
        local g = assert(gate[id], "not a write window: " .. tostring(id))
        assert(type(context) == "table" and context.bank == g.bank and context.pc == g.pc,
               id .. ": a write may only be attempted at its own PC")
        if id == "explode_hold" then
            local slot = seams.pending_explode()
            if slot == nil then return nil end
            local snapshot_ = snapshot(id, context, {"wBattlePlayerAction", "wCurBattleMon", "wCurMoveNum"})
            if snapshot_.link_mode ~= 0 or snapshot_.mode == 0 then
                refused[id] = "not a solo battle"
                if seams.explode_refused then seams.explode_refused(refused[id]) end
                return nil
            end
            local ok, err = pcall(function()
                writes:arm(g.reason)
                writes:explode_active_battler(slot, snapshot_)
            end)
            writes:disarm()
            if not ok then
                landed[id], refused[id] = nil, tostring(err)
                if seams.explode_refused then seams.explode_refused(err) end
                return nil
            end
            landed[id], refused[id] = {slot = slot, move = explosion}, nil
            if seams.exploded then seams.exploded(slot) end
            return {ok = true, result = {reason = g.reason, slot = slot, move = explosion}}
        end
        local mons = seams.pending_rival()
        if mons == nil then return nil end
        local snapshot_ = snapshot(id, context, {"wCurOTMon"})
        local ok, err = pcall(function()
            writes:arm(g.reason)
            writes:write_enemy_party(mons, snapshot_)
        end)
        writes:disarm()
        if not ok then
            landed[id], refused[id] = nil, tostring(err)
            if seams.rival_refused then seams.rival_refused(err) end
            return nil
        end
        local result = {reason = g.reason, count = #mons}
        for i = 1, #mons do result[i] = mons[i].record[1] end -- each record's own Species byte (+0)
        landed[id], refused[id] = result, nil
        if seams.rival_applied then seams.rival_applied(mons) end
        return {ok = true, result = result}
    end

    function self:status()
        return {writes_enabled = self.writes_enabled, gates = gate, landed = copy(landed), refused = copy(refused)}
    end
    return self
end

return B