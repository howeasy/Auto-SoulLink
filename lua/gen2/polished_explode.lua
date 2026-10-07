-- lua/gen2/polished_explode.lua -- the Polished Crystal v3.2.3 explode (W-3) / rival team swap (W-4) CLIENT PATH:
-- the ONE writer the shared client (lua/gen2/client.lua) is given, plus the battle hold it re-checks and the
-- p.battle_hold facts it hooks. Composed by compose_polished (lua/gen2/entry.lua); spec docs/polished/EXPLODE_RIVAL.md.
--
-- WHY A FACADE. The client has ONE writer slot (p.writes) and calls writes:arm("overworld" | "battle_hold" |
-- "rival_swap"), faint_party_slot, faint_active_battler, explode_active_battler, write_enemy_party, and reads
-- writes.sym.wCurOTMon. The overworld writer (polished_overworld.lua O.writes) has the first two only;
-- polished_writes.lua has explode_active_battler / write_enemy_party only, and no `sym`. This module routes each
-- call to the writer that owns it and fills in what the client never supplies:
--   * snapshot.bank / snapshot.pc: polished_writes.common() asserts the snapshot was taken at the gate PC. The
--     client builds one snapshot per hold and never stamps them, so the facade stamps the site it is serving
--     (explode -> battle_hold.execution_before, rival -> battle_hold.rival_swap_gate). That assertion is
--     therefore tautological here, and it is NOT what pins the CPU to the PC. Three guards do, honestly bounded:
--     (a) a HOOK-ENTRY TOKEN: the client's bus-exec callback (client.lua, p.battle_hold_entry) enters the token
--     "explode" before it runs at_battle_hold and clears it after (disarm() clears it too, so one hold arms ONE write
--     and a failed write cannot leave it open); arm() and every write refuse unless the token
--     names their site ("explode" for the explode, "rival_gate" for the rival write - a future rival hold sets
--     it). So a call made outside the exec callback is refused. What it proves is "BizHawk reported an execution
--     of 0f:416A and we are inside that callback", NOT a PC register read-back (none is made);
--     (b) arm() re-proves the BATTLE hold (hROMBank == 0x0F, the site bytes re-read from the executed ROM) and
--     every write authorize() re-proves it again; (c) the client re-reads hROMBank before it asks.
--   * snapshot.move_num: read from wCurMoveNum (the client does not carry it); polished_writes re-reads it.
--   faint_party_slot -> the overworld writer (its own gate asserts reason "overworld" and snapshot.mode == 0, so a
--   bench faint ARMED for a battle reason is refused there, by name: an in-battle faint is not composed).
--   faint_active_battler (F1) additionally requires a keyed snapshot, actual PC/bank at the hold,
--   USEMOVE, no pending/deferred switch and no Transform. It zeros both HP/status mirrors and
--   publishes the player-first faint notification only if none exists. No action byte is changed.
--   The shared client supplies the key only when composed with the opt-in settlement interface below (F2);
--   without it its unkeyed active-faint call still refuses.
--
-- THE BATTLE HOLD (polished_overworld.lua O.battle_checkpoint, kinds battle_faint / battle_bench / explode /
-- rival): wBattleMode in {1,2}, wLinkMode == 0, wGameLogicPaused == 0, no backup save, and the site bytes
-- re-read at the linear ROM offset. battle_faint/explode additionally need hROMBank == 0x0F (a PC hold, 0f:416A
-- `call DetermineMoveOrder`). rival_tick is a frame_end POLL, not a PC hold: its kinds only re-read the site bytes.
-- Qualification DEV_OVERLAY_PREDICATE_HOLD; no receipt exists.
--
-- ACTIVE-SPECIES MATCH. client.lua compares the party mon with the battle struct before it writes (the battle
-- struct must be that slot's). Its vanilla compare is the raw wBattleMonSpecies byte against mon.species_id, but a
-- Polished mon.species_id is the EFFECTIVE id (polished.lua effective(): species + EXTSPECIES bit * 256, and a
-- regional variant maps to its record index >= 292), so the raw compare never matched species > 255 or a variant.
-- E.new therefore hands the client p.battle_species_matches, which compares reads.read_battle_mon("player")
-- (the SAME decoder as the party read: ext-species bit, form, variant map) against the party mon's id.
--
-- p.battle_hold SHAPE (what the client reads, client.lua at_battle_hold): execution_before {bank, pc},
-- write.targets {wBattleMonSpecies, wBattlePlayerAction}. It is FABRICATED here from the pinned .sym (no pack row
-- carries a `write` block): wPlayerSubStatus5 does NOT exist in Polished, so that target and transformed_bit are
-- OMITTED. The vanilla Transform exception (battle struct species differs from the party mon's) therefore never
-- applies: an active battler whose battle-struct species differs from its party record waits (kept) instead of
-- being written. client.lua `target()` returns nil for an absent target (one-line guard, see its commit).
--
-- WHAT COMPOSING p.battle_hold CHANGES. A force_faint/force_explode that arrives IN a battle now queues for the
-- next battle hold (client.lua:557) instead of waiting for the overworld checkpoint. Only force_explode of the
-- ACTIVE battler lands there. Every other queued write (an active faint, a bench faint) is refused by name at
-- the hold and stays queued, with one refusal line in the log per hold. Polished composes no battle_end engine
-- signal (only capture_party is bound), so the client's battle_end hand-off to the checkpoint never runs:
-- entry.lua sets p.battle_release_poll and client.lua release_battle_writes hands the queue to the overworld
-- checkpoint when wBattleMode reads 0 - the same moment it landed before. Without that hand-off a death
-- queued in battle would never land (measured). p.battle_bench is NOT composed (a bench faint on receipt
-- would be refused every frame); p.rival_swap is NOT composed either, see below.
--
-- RIVAL SWAP IS WIRED BUT NOT COMPOSED, two measured blockers (both in files this card does not own):
--   1. the client decodes a replace_rival_team blob with c.PARTYMON_STRUCT_LENGTH / c.MON_HP / c.MON_SPECIES,
--      none of which is in the generated Polished profile.constants (it would raise on a nil);
--   2. rival_tick polls at a frame end while wCurOTMon == 0xFF, and polished_writes.write_enemy_party refuses
--      cur_ot_mon outside the NEW party (the write is only valid at 0f:47DD, after wCurOTMon is committed).
-- writes.sym IS provided, so the client announces trainer_battle_start; with rival_swap unset it answers
-- replace_rival_team "unsupported". write_enemy_party is reachable and tested through this facade at the real
-- gate state (tests/unit/test_polished_explode_path.py).
local E = {}

-- polished_writes.lua W.COORDS, {bank, address} straight from data/polished/polished_slink.sym (the test
-- re-derives every one). The profile carries only some of them; wCurOTMon = 00:c4dd, wBattlePlayerAction = 01:d0f4.
E.COORDS = {
    wBattleMonMoves = {0, 0xC4A7}, wBattleMonPP = {0, 0xC4B0}, wCurPlayerMove = {0, 0xC540},
    wCurMoveNum = {1, 0xD0DB}, wCurBattleMon = {1, 0xD0DA}, wBattlePlayerAction = {1, 0xD0F4},
    wPartyCount = {1, 0xDCCE}, wPartyMons = {1, 0xDCD6}, wOTPartyCount = {1, 0xD283},
    wMirrorHerbPendingBoosts = {1, 0xD284}, wOTPartyMons = {1, 0xD28B}, wOTPartyMonOTs = {1, 0xD3AB},
    wOTPartyMonNicknames = {1, 0xD3ED}, wOTPartyDataEnd = {1, 0xD42F}, wCurOTMon = {0, 0xC4DD},
    wCurPartyMon = {1, 0xD10C},
}
-- F1 coordinates from polished_slink.sym, independently pinned by the plain-faint tests.
-- Kept separate so existing explode-only coordinate consumers retain their 16-label ABI.
E.FAINT_COORDS = {
    wBattleMonStatus = {0, 0xC4B6}, wBattleMonHP = {0, 0xC4B8},
    wPlayerSwitchTarget = {0, 0xC524}, wDeferredSwitch = {0, 0xC523},
    wWhichMonFaintedFirst = {0, 0xC54F}, wPlayerSubStatus2 = {0, 0xC4E2},
    wBattleMode = {1, 0xD233}, wLinkMode = {0, 0xCEC1}, hROMBank = {0, 0xFF87},
}
-- client.lua at_battle_hold reads these through p.battle_hold.write.targets ({bank, address})
E.TARGETS = {wBattleMonSpecies = {bank = 0, address = 0xC4A5, width = 1},
             wBattlePlayerAction = {bank = 1, address = 0xD0F4, width = 1}}
-- the armed reason -> the battle-hold kind it re-proves on arm()
E.KIND_OF_REASON = {battle_hold = "explode", rival_swap = "rival"}
-- the polished_writes.lua authorize() operation -> the battle-hold kind
E.KIND_OF_OPERATION = {battle_explode = "explode", enemy_party = "rival"}
E.KIND_OF_OPERATION.battle_faint = "explode"
-- the armed reason -> the hook-entry site the CPU must be inside
E.SITE_OF_REASON = {battle_hold = "explode", rival_swap = "rival_gate"}

local function copy(value)
    if type(value) ~= "table" then return value end
    local out = {}
    for key, item in pairs(value) do out[key] = copy(item) end
    return out
end

--- deps: root, profile (generated Polished title), io, Permit (lua/write_permit.lua), overworld (the O.writes writer),
--- overworld_hold (its O.checkpoint), reads (the composed Polished reads), log. modules (optional, a test seam): {W = polished_writes, O = polished_overworld}.
--- Returns {writes, checkpoint, safety, battle_hold, sym, entry, species_matches}.
function E.new(deps)
    assert(type(deps) == "table", "Polished explode options required")
    local profile, io, Permit, log = assert(deps.profile), assert(deps.io), assert(deps.Permit), deps.log
    local overworld, overworld_hold = assert(deps.overworld), assert(deps.overworld_hold)
    local reads = assert(deps.reads, "the composed reads (read_battle_mon) are required")
    assert(type(reads.read_battle_mon) == "function", "reads.read_battle_mon required")
    assert(type(overworld.faint_party_slot) == "function" and type(overworld.arm) == "function",
           "the overworld writer is required")
    assert(type(io.read_u8) == "function" and type(io.bank_valid) == "function"
           and type(io.framecount) == "function", "explicit read_u8/bank_valid/framecount required")
    local modules = deps.modules or {}
    local W = modules.W or dofile(assert(deps.root, "root required") .. "/lua/gen2/polished_writes.lua")
    local O = modules.O or dofile(deps.root .. "/lua/gen2/polished_overworld.lua")

    local sym = copy(E.COORDS)
    for label, row in pairs(E.FAINT_COORDS) do sym[label] = copy(row) end
    local explode_site, rival_site = O.BATTLE_SITES.explode, O.BATTLE_SITES.rival_gate
    local hold = {
        execution_before = {bank = explode_site.bank, pc = explode_site.pc, instruction = explode_site.instruction,
                            expected_hex = "cd3542"},
        rival_swap_gate = {bank = rival_site.bank, pc = rival_site.pc},
        write = {targets = copy(E.TARGETS)},
    }
    local battle = O.battle_checkpoint(profile, io, log, O.BATTLE_SITES)

    local held, still = function() return io.framecount() end, function(token) return token == io.framecount() end
    local policy = {
        authorize = function(operation)
            local kind = E.KIND_OF_OPERATION[operation]
            return kind ~= nil and battle:check(kind) == true
        end,
        pointer_stable = function() return true end, -- the battle struct and the enemy party block are fixed WRAM
        lifetime = {capture = held, valid = still},
        provenance = function() return {site = "lua/gen2/polished_explode.lua battle",
                                        evidence = "DEV_OVERLAY_PREDICATE_HOLD"} end,
    }
    local writer = W.new(profile, sym, io, Permit, policy, hold)

    -- the hook-entry token: which PC site the client's exec callback is currently inside (nil = none)
    local entered
    local entry = {enter = function(site) entered = site end, leave = function() entered = nil end}
    local function inside_hook(site)
        assert(entered == site, "write refused: not inside the " .. site .. " hold hook")
    end
    local function species_matches(mon)
        local battle = reads.read_battle_mon("player")
        -- nil == nil must not match: an unreadable battle struct or a mon without an id is never "the same mon"
        return type(battle) == "table" and battle.species_id ~= nil and mon.species_id ~= nil
               and battle.species_id == mon.species_id
    end

    local function wram(label, offset)
        local row = sym[label]
        assert(io.bank_valid(row[1], row[2] + (offset or 0), 1) == true, "read refused: " .. label .. " bank not mapped")
        return io.read_u8(row[2] + (offset or 0), "System Bus")
    end
    -- the snapshot polished_writes re-checks, stamped with the site it is being served at
    local function stamped(snapshot, site)
        assert(type(snapshot) == "table", "explicit battle snapshot required")
        local out = copy(snapshot)
        out.bank, out.pc = site.bank, site.pc
        return out
    end

    local self = setmetatable({sym = sym, qualification = O.BATTLE_QUALIFICATION, hold = hold},
        {__index = function(_, key)
            if key == "armed" then return overworld.armed or writer.armed end
            if key == "log" then return writer.log end
        end})
    function self:arm(reason, allow)
        if reason == O.FAINT_REASON then return overworld:arm(reason, allow) end
        local kind = E.KIND_OF_REASON[reason]
        if kind == nil then
            error("no composed Polished write for the armed reason " .. tostring(reason), 0)
        end
        inside_hook(E.SITE_OF_REASON[reason])
        local ok, why = battle:check(kind)
        assert(ok == true, "write refused at arm(" .. tostring(reason) .. "): " .. tostring(why))
        return writer:arm(reason, allow)
    end
    function self:disarm()
        entered = nil -- a write (landed or refused) spends the token: the next arm needs its own enter()
        overworld:disarm()
        return writer:disarm()
    end
    function self:faint_party_slot(slot, snapshot) return overworld:faint_party_slot(slot, snapshot) end
    function self:faint_active_battler(slot, snapshot)
        -- No pending-command bookkeeping here: F2 must supply the target key and retain
        -- named preflight refusals. A post-write error explicitly reports partial state.
        assert(type(snapshot) == "table" and type(snapshot.key) == "string" and #snapshot.key > 0,
               "unkeyed active-battler faint is not composed on Polished: F2 must supply the target key; USEITEM is unsupported")
        inside_hook("explode")
        local snap = stamped(snapshot, hold.execution_before)
        assert(type(snap.key) == "string" and #snap.key > 0, "active faint needs target key")
        local party = reads.read_party()
        assert(type(party) == "table" and type(party.mons) == "table", "active faint party unreadable")
        local target, hits
        hits = 0
        for _, mon in ipairs(party.mons) do
            if mon.key == snap.key then
                hits = hits + 1
                if mon.slot == slot then target = mon end
            end
        end
        assert(hits == 1 and target ~= nil, "active faint target key changed or ambiguous")
        assert(not target.is_egg, "active faint egg refused")
        assert(species_matches(target), "active faint battle species mismatch")
        assert(type(target.raw_hex) == "string" and #target.raw_hex == profile.structs.party.End * 2
               and target.raw_hex:match("^%x+$"), "active faint party record unreadable")
        snap.party_record = {}
        for byte in target.raw_hex:gmatch("%x%x") do snap.party_record[#snap.party_record + 1] = tonumber(byte, 16) end
        return writer:faint_active_battler(slot, snap)
    end
    function self:explode_active_battler(slot, snapshot)
        inside_hook("explode")
        local snap = stamped(snapshot, hold.execution_before)
        if snap.move_num == nil then snap.move_num = wram("wCurMoveNum") end
        return writer:explode_active_battler(slot, snap)
    end
    function self:write_enemy_party(mons, snapshot)
        inside_hook("rival_gate")
        return writer:write_enemy_party(mons, stamped(snapshot, hold.rival_swap_gate))
    end

    -- the client asks ONE safety object for every kind: the overworld hold owns party_hp, the battle hold the rest
    local safety = {check = function(kind)
        if O.BATTLE_KINDS[kind] ~= nil then return battle:check(kind) end
        return overworld_hold:check(kind)
    end}
    -- F2 (docs/polished/PLAIN_FAINT_F2.md): the OPTIONAL settlement interface compose_polished hands the shared client
    -- (p.active_faint_settlement). It is read-only evidence the client cannot build itself and is NOT a writer: the
    -- client still calls the writers above. attempt_mark/attempted_since classify a thrown error by the OPERATION-SCOPED
    -- permit receipts of both writers (a receipt with attempted > 0 is a write that reached memory; nil = unknowable);
    -- native() reads the player's battle HP / FAINTED bit / first-faint order for the evidence trail.
    local function log_length(writer_log)
        return type(writer_log) == "table" and #writer_log or nil
    end
    local settlement = {version = 1, deadline_frames = 1800}
    function settlement.attempt_mark()
        return {overworld = log_length(overworld.log), battle = log_length(writer.log)}
    end
    function settlement.attempted_since(mark)
        if type(mark) ~= "table" then return nil end
        for name, source in pairs({overworld = overworld.log, battle = writer.log}) do
            local before = mark[name]
            if before == nil or type(source) ~= "table" or #source < before then return nil end
            for i = before + 1, #source do
                if (source[i].attempted or 0) > 0 then return true end
            end
        end
        return false
    end
    function settlement.native()
        local ok, value = pcall(function()
            return {hp = wram("wBattleMonHP") * 256 + wram("wBattleMonHP", 1), order = wram("wWhichMonFaintedFirst"),
                    status = wram("wBattleMonStatus"),
                    fainted = (wram("wPlayerSubStatus2") & 0x04) ~= 0}
        end)
        return ok and value or nil
    end
    return {writes = self, checkpoint = battle, safety = safety, battle_hold = hold, sym = sym, entry = entry,
            species_matches = species_matches, settlement = settlement}
end

return E
