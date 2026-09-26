-- T2: A receives one keyed force_faint, B idles without saving. Run with gen3_frlg and
-- gen3_lgfr to exercise both titles. The runner queues ONLY force_faint after
-- READY_BATTLE_WINDOW (not an injected death + memorialize); the target must remain in party.
-- D.battle_window_case = "trainer_bench" (town seed, slot1). A2 (active_end_gen3) left this
-- carrier with mechanism P+H (owner rulings 15-18): the active battler is no longer held to the
-- battle's end, so it runs on scenario_gen3_linked_faint_active.lua's "command" case.
--
-- New injected seams required at integration (this module neither pokes nor stages game data):
-- SINGLES ONLY; doubles player slots belong to D1-D5, not this carrier.
--   ctx.enter_trainer(label, expected_trainer_id, prep) -> true | false, why
--     T2 uses Rick102, NOT the Route22 rival. PREPARATION: train the lead to prep.level_floor
--     (13), within prep.max_frames (ctx.preparation_budget: <=1,782,000 for these fixtures),
--     by normal Route1 Tackle battles and normal
--     Viridian nurse healing. Reuse GRASS_ORIGIN/GRASS_LOOP/hunt; no game-data staging/pokes.
--     Heal the lead to full HP/status0 before walking to Rick, and verify those at entry.
--     Training is a no-op if already at the floor. Fail if budget/floor fails or a forced switch
--     would involve the bench. prep.target_key/slot/hp must remain unchanged on EVERY frame.
--     Then normal Route2/Forest route to Rick; return parked, battle_permit=true, outcome=0,
--     is_trainer=true, trainer_id=expected. Integration owns this route/preparation binding.
--     Required normal-input chain (binding belongs to 2B-INTEGRATE-DUO):
--       1. Reuse mkstates_gen3_tutorials.lua's tutorial prefix (c08328b4/e4c30fff, receipts
--          66d2a802): (24,39) U8 L2 U22 ->(22,9), U into TutorialTriggerRight while var4051=1.
--          A only, never B; prove var4051=2, TeachyTV366 granted and field quiet at(22,8).
--       2. Train to the level floor and heal normally in the Viridian Pokemon Center.
--       3. Walk north through(20,0), U to Route2(8,79), then the plan's gate/Forest route to
--          Rick's first sight tile(42,45). Revalidate full HP/status0 and the parked postcondition.
--     Scene2 makes both tutorial coordinate triggers inactive. No route may assume scene1
--     passability: the previously suggested western shortcut crosses Cut tree(18,5).
--     pret trainer_parties.h:273-284: Rick's Weedle6 (Poison Sting/String Shot), Caterpie6
--     (Tackle/String Shot), .iv0 = IV0 (battle_main.c:1576). The rival .iv50 = IV6. Both town
--     fixtures have no Potions. Coordinator FC-T2-FLOOR ruling (Monte Carlo, not reproduced
--     here): LG8 wins30-58%, LG10 87-92%, LG13 99.6%; FR9 57-75%. Poison dominates risk.
--     BOTH titles therefore train to13. One whole-attempt retry is allowed only for the named
--     T2_RNG_LOSS AFTER the bench write; it never qualifies as PASS. Pre-READY loss is prep failure.
--     ctx.party() must expose lead level/hp/max_hp/status from actual RAM (status0 means none).
--   ctx.battle_window_snapshot(key) -> immutable table, or nil, why:
--     frame, samples, in_battle (boolean), outcome, is_trainer (boolean), trainer_id, battlers_count,
--     active_slots (player party slots, zero based), party_base, target_count,
--     target={key,slot,hp}, active_bytes (raw 0x58-byte gBattleMons[0], not hex),
--     battle_permit, overworld_permit (actual policy verdicts), tuple (full receipt text).
--     Read actual RAM/identity independently of write logs; target_count must count duplicates.
--     Both permit booleans and the tuple come from the pinned policy, not reconstructed gates.
--     samples is a positive monotonic count of distinct sampled frames (coalesce same-frame
--     calls). party_base is 4-aligned EWRAM with room for six100-byte records. In battle there
--     are exactly2 battlers and one player active slot; target_count counts ALL matching keys.
--     The carrier serializes samples/active_hex/in_battle/target_hp/trainer_id itself; tuple
--     must not duplicate those fields or frame/slot/hp. Include the remaining full clause/CPU
--     values in tuple. active_bytes must be exactly0x58 (pret pokemon.h BattlePokemon).
-- Runner sets D.battle_window_case, town/slot1 for T2, then queues one force_faint ONLY after
-- READY. Both orientations run A as the mutation subject; B never saves.
-- Existing ctx.watch runs after EVERY client frame, including frames inside game helpers.
-- Existing ctx.on_write runs synchronously inside the sink's completed-write log callback.
--
-- pret: party HP +0x56, record100 bytes (pokemon.h); active exclusion client.battler_of;
-- battle_controller_player.c:186-244 commits choices; battle.h outcomes WON=1, RAN=4.
-- T2 must not accept whiteout recovery healing its bench target. The Python oracle must independently decode the
-- final save (unique key/slot, HP0, no boxed duplicate) and verify save-witness hashes/counters.
local fmt = string.format
local TRAINER_ID = 102

local function integer(n) return type(n) == "number" and n % 1 == 0 end

local function peer(ctx)
    local text = ctx.wait_until(function()
        local s = ctx.partner_result()
        if s and s:find("\nRESULT:", 1, true) then return s end
        if s and s:match("^RESULT:") then return s end
    end, 7200, "battle-window A result")
    local verdict
    for line in ((text or "") .. "\n"):gmatch("([^\r\n]+)") do
        verdict = line:match("^RESULT: (%u+)") or verdict
    end
    if verdict ~= "PASS" then return false, "battle-window partner did not PASS" end
    return true, "idle (no save); battle-window A passed"
end

return function(ctx)
    local mode = ctx.D.battle_window_case
    if mode ~= "trainer_bench" then return false, "battle_window_case must be trainer_bench" end
    if not ctx.wait_go(nil, 1800) then return false, "no go-file" end
    if ctx.player == "b" then return peer(ctx) end
    if ctx.player ~= "a" then return false, "unknown battle-window player" end
    if type(ctx.battle_window_snapshot) ~= "function" then
        return false, "missing battle_window_snapshot integration seam"
    end
    local key = ctx.linked()
    local slot = 1
    local mon = key and ctx.find(key)
    if not mon or mon.key ~= key or mon.slot ~= slot or mon.hp <= 0 then
        return false, "battle-window target must be a living unique key in slot " .. slot
    end
    do
        if type(ctx.enter_trainer) ~= "function" then return false, "missing enter_trainer route seam" end
        local floor = ctx.D.battle_window_level_floor or 13
        if floor ~= 13 then return false, "invalid preparation level floor (budget pinned to13)" end
        local before = (ctx.party() or {})[1]
        if not before or before.slot ~= 0 or not integer(before.level) then return false, "unreadable prep lead" end
        local preparing, prep_error = true, nil
        ctx.watch(function()
            if not preparing then return true end
            local ok, t, lead, primary = pcall(function()
                return ctx.find(key), (ctx.party() or {})[1], not ctx.in_battle() or ctx.battler_slot()==0
            end)
            if not ok or not t or t.key ~= key or t.slot ~= slot or t.hp ~= mon.hp then
                prep_error = "PREPARATION altered bench target HP/key/slot"
                return true
            end
            if not lead or lead.hp<=0 or not primary then
                prep_error = fmt("PREPARATION lead fainted or bench switched in hp=%s primary=%s",
                                 tostring(lead and lead.hp),tostring(primary))
                return true
            end
        end)
        if type(ctx.preparation_budget)~="function" then return false,"missing preparation_budget seam" end
        local budget_ok, budget = pcall(ctx.preparation_budget,before,floor)
        if not budget_ok then return false,"PREPARATION budget: "..tostring(budget) end
        local ok, why = ctx.enter_trainer("battle_window trainer", TRAINER_ID,
            {level_floor=floor, max_frames=budget, target_key=key, target_slot=slot, target_hp=mon.hp})
        preparing = false
        local after, target = (ctx.party() or {})[1], ctx.find(key)
        if prep_error or not target or target.key ~= key or target.slot ~= slot or target.hp ~= mon.hp then
            return false, prep_error or "PREPARATION altered bench target HP/key/slot"
        end
        if not ok then return false, "trainer route: " .. tostring(why) end
        if not after or after.slot ~= 0 or not integer(after.level) or after.level < floor then
            return false, "PREPARATION did not reach the level floor within its budget"
        end
        if not integer(after.max_hp) or after.max_hp <= 0 or after.hp ~= after.max_hp or after.status ~= 0 then
            return false, "PREPARATION lead must enter at full HP with no status"
        end
        ctx.log(fmt("PREP_LEVEL before=%d after=%d floor=%d hp=full status=none", before.level, after.level, floor))
    end

    local function snapshot()
        local s, why = ctx.battle_window_snapshot(key)
        if type(s) ~= "table" or not integer(s.frame) or not integer(s.samples) or s.samples < 1
            or type(s.in_battle) ~= "boolean"
            or not integer(s.outcome) or type(s.is_trainer) ~= "boolean"
            or type(s.active_slots) ~= "table" or type(s.active_bytes) ~= "string"
            or #s.active_bytes ~= 0x58 or type(s.tuple) ~= "string" or #s.tuple == 0
            or type(s.battle_permit) ~= "boolean" or type(s.overworld_permit) ~= "boolean"
            or not integer(s.party_base) or s.party_base < 0x02000000
            or s.party_base + 600 > 0x02040000 or s.party_base % 4 ~= 0 then
            return nil, "unreadable battle snapshot: " .. tostring(why)
        end
        local t = s.target
        if s.target_count ~= 1 or type(t) ~= "table" or t.key ~= key or t.slot ~= slot
            or not integer(t.hp) or t.hp < 0 then
            return nil, "wrong key/slot or ambiguous target in battle snapshot"
        end
        if s.in_battle and (s.battlers_count ~= 2 or #s.active_slots ~= 1
            or not integer(s.active_slots[1]) or s.active_slots[1] < 0 or s.active_slots[1] > 5) then
            return nil, "battle-window requires a readable single battle"
        end
        return s
    end
    local initial, why = snapshot()
    if not initial then return false, why end
    if not initial.in_battle or initial.outcome ~= 0 or not initial.battle_permit
        or initial.target.hp == 0 or not initial.is_trainer or initial.trainer_id ~= TRAINER_ID then
        return false, "wrong trainer/type or unparked battle-window start"
    end
    if initial.active_slots[1] == slot then
        return false, "wrong active/bench target slot at battle-window start"
    end
    local rx0, attempts0 = ctx.received("force_faint", key), ctx.attempted()
    if rx0 ~= 0 or ctx.battle_hold(key) then return false, "stale force_faint before READY" end
    local address = initial.party_base + slot * 100 + 0x56
    local function evidence(s)
        local hex = s.active_bytes:gsub(".", function(c) return fmt("%02X", c:byte()) end)
        return fmt("samples=%d active_hex=%s in_battle=%d target_hp=%d trainer_id=%d %s",
            s.samples, hex, s.in_battle and 1 or 0, s.target.hp, s.trainer_id or 0, s.tuple)
    end
    local failed, landed, closed, exit_frame
    local function fail(s) failed = failed or s end
    local function note_exit(s)
        if not exit_frame then
            exit_frame = s.frame
            ctx.log(fmt("BATTLE_WINDOW_EXIT %s %s frame=%d outcome=%d %s", mode, key,
                        s.frame, s.outcome, evidence(s)))
        end
    end
    local function on_write(reason)
        if closed then return end
        local s, err = snapshot()
        if not s then return fail(err) end
        local lines = ctx.write_lines()
        local w = lines[#lines]
        if ctx.received("force_faint", key) ~= rx0 + 1 then return fail("write without fresh keyed RX") end
        if not w or w.reason ~= reason or w.address ~= address or w.len ~= 2 or w.frame ~= s.frame then
            return fail("wrong write address/length/frame for target HP")
        end
        if landed or s.party_base ~= initial.party_base or s.target.hp ~= 0
            or ctx.attempted() - attempts0 ~= 2 then
            return fail("write lacks exclusive two-byte HP0 readback")
        end
        if reason ~= "battle_faint" or not s.in_battle or s.outcome ~= 0
            or not s.battle_permit or not s.is_trainer or s.trainer_id ~= TRAINER_ID
            or s.active_slots[1] == slot then
            return fail("trainer bench faint landed outside the in-battle bench window")
        end
        if s.active_bytes ~= initial.active_bytes then return fail("active battle record changed at bench write") end
        landed = s.frame
        ctx.log(fmt("BATTLE_WINDOW_LANDED %s %s slot=%d frame=%d reason=%s address=0x%08X len=2 hp=0 %s",
                    mode, key, slot, s.frame, reason, address, evidence(s)))
    end
    -- ctx.watch itself swallows exceptions. Latch them here, so a dead observer cannot PASS.
    local function guarded(fn)
        return function(...)
            if closed then return true end
            local ok, err = pcall(fn, ...)
            if not ok then fail("battle-window observer error: " .. tostring(err)) end
            return failed ~= nil
        end
    end
    ctx.on_write("battle_faint", guarded(function() on_write("battle_faint") end))
    ctx.on_write("overworld", guarded(function() on_write("overworld") end))
    ctx.watch(guarded(function()
        local s, err = snapshot()
        if not s then return fail(err) end
        if s.party_base ~= initial.party_base then return fail("party base changed") end
        if ctx.received("force_faint", key) > rx0 + 1 then return fail("duplicate force_faint during carrier") end
        if landed then
            if ctx.attempted() - attempts0 ~= 2 then return fail("extra client write after target HP write") end
            if s.outcome == 2 and s.trainer_id == TRAINER_ID then
                note_exit(s)
                return fail("T2_RNG_LOSS: lead fainted to Rick after the SLink write landed")
            end
            if s.target.hp ~= 0 then fail("target revived after the witnessed faint") end
            if not s.in_battle then note_exit(s) end
            return
        end
        if s.target.hp == 0 or ctx.attempted() ~= attempts0 then
            return fail("target mutated without the required write witness")
        end
        if not s.in_battle then fail("trainer bench write was deferred until battle end") end
    end))
    local function finish(ok, message) closed = true; return ok, message end
    ctx.log(fmt("READY_BATTLE_WINDOW %s %s slot=%d frame=%d trainer=%d %s", mode, key, slot,
                initial.frame, TRAINER_ID, evidence(initial)))
    local got = ctx.wait_until(function()
        return failed or ctx.received("force_faint", key) > rx0
    end, 120, "fresh battle-window force_faint")
    if failed then return finish(false, failed) end
    if not got then return finish(false, "no fresh keyed force_faint") end
    local hit = ctx.wait_until(function() return failed or landed end, 90, "battle-window HP write")
    if failed then return finish(false, failed) end
    if not hit then return finish(false, "no witnessed battle-window HP write") end
    do
        local ok, err = ctx.try(ctx.play.fight_through, ctx.cp, 4000)
        if failed then return finish(false, failed) end
        if not ok then
            local last = snapshot()
            if last and last.outcome == 2 and last.trainer_id == TRAINER_ID then
                note_exit(last)
                return finish(false, "T2_RNG_LOSS: lead fainted to Rick after the SLink write landed")
            end
            return finish(false, "trainer completion: " .. tostring(err))
        end
    end
    ctx.play.wait_scene_settled(ctx.cp, 3000)
    local final, err = snapshot()
    if failed then return finish(false, failed) end
    if not final then return finish(false, err) end
    if final.in_battle or final.outcome ~= 1 or final.target.hp ~= 0 then
        return finish(false, "battle did not finish normally with target HP0 (whiteout is not persistence)")
    end
    note_exit(final)
    local saved, swhy = ctx.save("battle_window " .. mode)
    if failed then return finish(false, failed) end
    if not saved then return finish(false, "save: " .. tostring(swhy)) end
    final, err = snapshot()
    if not final or final.target.hp ~= 0 or final.in_battle then
        return finish(false, err or "target revived or new battle at save")
    end
    ctx.log(fmt("BATTLE_WINDOW_SAVED %s %s slot=%d hp=0", mode, key, slot))
    return finish(true, mode .. " keyed faint and normal save (PYDEC required)")
end
