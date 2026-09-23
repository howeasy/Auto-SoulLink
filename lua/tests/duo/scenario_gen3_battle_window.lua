-- T2 / A2: A receives one keyed force_faint, B idles without saving. Run each case with
-- gen3_frlg and gen3_lgfr to exercise both titles. The runner queues ONLY force_faint after
-- READY_BATTLE_WINDOW (not an injected death + memorialize); the target must remain in party.
-- D.battle_window_case = "trainer_bench" (town seed, slot1) or "active_end" (battle seed, slot0).
--
-- New injected seams required at integration (this module neither pokes nor stages game data):
--   ctx.enter_trainer(label, expected_trainer_id) -> true | false, why
--     Bind C4-PROBE2's normal-input Route22 route/parking helper, not its full run_trainer
--     which continues on to faint the lead and exits the emulator. Squirtle fixtures face
--     trainer330 (pret c75f3523 opponents.h / Route22/scripts.inc / trainer_parties.h:3759).
--   ctx.battle_window_snapshot(key) -> immutable table, or nil, why:
--     frame, in_battle (boolean), outcome, is_trainer (boolean), trainer_id, battlers_count,
--     active_slots (player party slots, zero based), party_base, target_count,
--     target={key,slot,hp}, active_bytes (raw 0x58-byte gBattleMons[0], not hex),
--     battle_permit, overworld_permit (actual policy verdicts), tuple (full receipt text).
--     Read actual RAM/identity independently of write logs; target_count must count duplicates.
--     Both permit booleans and the tuple come from the pinned policy, not reconstructed gates.
-- Existing ctx.watch runs after EVERY client frame, including frames inside game helpers.
-- Existing ctx.on_write runs synchronously inside the sink's completed-write log callback.
--
-- pret: party HP +0x56, record100 bytes (pokemon.h); active exclusion client.battler_of;
-- battle_controller_player.c:186-244 commits choices; battle.h outcomes WON=1, RAN=4.
-- A2 must not confuse an overworld application with an in-battle success. T2 must not accept
-- whiteout recovery healing its bench target. The Python oracle must independently decode the
-- final save (unique key/slot, HP0, no boxed duplicate) and verify save-witness hashes/counters.
local fmt = string.format
local HOLD_FRAMES = 120
local TRAINER_ID = 330

local function integer(n) return type(n) == "number" and n % 1 == 0 end

local function peer(ctx)
    local text = ctx.wait_until(function()
        local s = ctx.partner_result()
        if s and s:find("\nRESULT:", 1, true) then return s end
        if s and s:match("^RESULT:") then return s end
    end, 1800, "battle-window A result")
    local verdict
    for line in ((text or "") .. "\n"):gmatch("([^\r\n]+)") do
        verdict = line:match("^RESULT: (%u+)") or verdict
    end
    if verdict ~= "PASS" then return false, "battle-window partner did not PASS" end
    return true, "idle (no save); battle-window A passed"
end

return function(ctx)
    local mode = ctx.D.battle_window_case
    if mode ~= "trainer_bench" and mode ~= "active_end" then
        return false, "battle_window_case must be trainer_bench or active_end"
    end
    if not ctx.wait_go(nil, 1800) then return false, "no go-file" end
    if ctx.player == "b" then return peer(ctx) end
    if ctx.player ~= "a" then return false, "unknown battle-window player" end
    if type(ctx.battle_window_snapshot) ~= "function" then
        return false, "missing battle_window_snapshot integration seam"
    end
    local key = ctx.linked()
    local slot = mode == "trainer_bench" and 1 or 0
    local mon = key and ctx.find(key)
    if not mon or mon.key ~= key or mon.slot ~= slot or mon.hp <= 0 then
        return false, "battle-window target must be a living unique key in slot " .. slot
    end
    if mode == "trainer_bench" then
        if type(ctx.enter_trainer) ~= "function" then return false, "missing enter_trainer route seam" end
        local ok, why = ctx.enter_trainer("battle_window trainer", TRAINER_ID)
        if not ok then return false, "trainer route: " .. tostring(why) end
    else
        if not ctx.hunt("battle_window active_end") then return false, "no wild encounter" end
        if ctx.SP.verify_fight_cursor(ctx.cp, "incidental_battle") ~= "fight" then
            return false, "active_end: no action menu"
        end
    end

    local function snapshot()
        local s, why = ctx.battle_window_snapshot(key)
        if type(s) ~= "table" or not integer(s.frame) or type(s.in_battle) ~= "boolean"
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
    local trainer = mode == "trainer_bench"
    if not initial.in_battle or initial.outcome ~= 0 or not initial.battle_permit
        or initial.target.hp == 0 or initial.is_trainer ~= trainer
        or (trainer and initial.trainer_id ~= TRAINER_ID) then
        return false, "wrong trainer/type or unparked battle-window start"
    end
    if (initial.active_slots[1] == slot) == trainer then
        return false, "wrong active/bench target slot at battle-window start"
    end
    local rx0, attempts0 = ctx.received("force_faint", key), ctx.attempted()
    if rx0 ~= 0 or ctx.battle_hold(key) then return false, "stale force_faint before READY" end
    local address = initial.party_base + slot * 100 + 0x56
    local failed, landed, closed, ending, exit_frame
    local function fail(s) failed = failed or s end
    local function note_exit(s)
        if not exit_frame then
            exit_frame = s.frame
            ctx.log(fmt("BATTLE_WINDOW_EXIT %s %s frame=%d outcome=%d %s", mode, key,
                        s.frame, s.outcome, s.tuple))
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
        if trainer then
            if reason ~= "battle_faint" or not s.in_battle or s.outcome ~= 0
                or not s.battle_permit or not s.is_trainer or s.trainer_id ~= TRAINER_ID
                or s.active_slots[1] == slot then
                return fail("trainer bench faint landed outside the in-battle bench window")
            end
            if s.active_bytes ~= initial.active_bytes then return fail("active battle record changed at bench write") end
        else
            if reason ~= "overworld" or s.in_battle or not ending or s.outcome ~= 4
                or not s.overworld_permit then
                return fail("active target mutated before the normal battle end/overworld window")
            end
            note_exit(s) -- the write can precede this frame's watcher; RAM is already out of battle
        end
        landed = s.frame
        ctx.log(fmt("BATTLE_WINDOW_LANDED %s %s slot=%d frame=%d reason=%s address=0x%08X len=2 hp=0 %s",
                    mode, key, slot, s.frame, reason, address, s.tuple))
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
            if s.target.hp ~= 0 then fail("target revived after the witnessed faint") end
            return
        end
        if s.target.hp == 0 or ctx.attempted() ~= attempts0 then
            return fail("target mutated without the required write witness")
        end
        if trainer then
            if not s.in_battle then fail("trainer bench write was deferred until battle end") end
        elseif s.in_battle then
            if s.active_slots[1] ~= slot then return fail("active_end target switched out") end
            if ctx.received("force_faint", key) > rx0 and not ctx.battle_hold(key) then
                fail("active target is not held in battle_pending")
            end
        else
            if not ending or s.outcome ~= 4 then return fail("unexpected battle end") end
            note_exit(s)
        end
    end))
    local function finish(ok, message) closed = true; return ok, message end
    ctx.log(fmt("READY_BATTLE_WINDOW %s %s slot=%d frame=%d trainer=%d %s", mode, key, slot,
                initial.frame, trainer and TRAINER_ID or 0, initial.tuple))
    local got = ctx.wait_until(function()
        return failed or ctx.received("force_faint", key) > rx0
    end, 120, "fresh battle-window force_faint")
    if failed then return finish(false, failed) end
    if not got then return finish(false, "no fresh keyed force_faint") end
    if not trainer then
        for _ = 1, HOLD_FRAMES do
            ctx.frames(1)
            if failed then return finish(false, failed) end
        end
        ctx.log(fmt("BATTLE_WINDOW_HELD active_end %s frames=%d attempted=0", key, HOLD_FRAMES))
        ending = true
        ctx.log("BATTLE_WINDOW_EXIT_INPUT active_end " .. key)
        local ok, err = ctx.run_away("battle_window active_end")
        if failed then return finish(false, failed) end
        if not ok then return finish(false, "RUN failed: " .. tostring(err)) end
    end
    local hit = ctx.wait_until(function() return failed or landed end, 90, "battle-window HP write")
    if failed then return finish(false, failed) end
    if not hit then return finish(false, "no witnessed battle-window HP write") end
    if trainer then
        local ok, err = ctx.try(ctx.play.fight_through, ctx.cp, 4000)
        if failed then return finish(false, failed) end
        if not ok then return finish(false, "trainer completion: " .. tostring(err)) end
    end
    ctx.play.wait_scene_settled(ctx.cp, 3000)
    local final, err = snapshot()
    if failed then return finish(false, failed) end
    if not final then return finish(false, err) end
    if final.in_battle or final.outcome ~= (trainer and 1 or 4) or final.target.hp ~= 0 then
        return finish(false, "battle did not finish normally with target HP0 (whiteout is not persistence)")
    end
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
