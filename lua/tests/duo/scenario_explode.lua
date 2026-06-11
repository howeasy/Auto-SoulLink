-- scenario_explode.lua — EXPLODE MODE end-to-end through the REAL server loop (--explode-mode).
--
-- WHY a live battle (not a frozen savestate): a coerced move only EXECUTES if the foe also
-- commits an action. In a frozen battle savestate the foe's controller never commits, so the
-- turn script never runs and nothing resolves (documented limitation). So B drives itself into
-- a real battle from slink_prebattle.State and advances the intro to the ACTION MENU, then waits
-- there (no input — pressing A would open FIGHT and commit OUR move, pre-empting the Explosion).
--
-- Flow: B reaches the action menu -> logs IN_BATTLE -> runner links A0<->B0 + writes go ->
-- A (overworld) zeroes its linked mon -> `faint` -> server _propagate_faint (explode_mode)
-- queues `force_explode` for B's linked mon -> B's production client runs the Variant-3
-- menu-skip (native_battle_control OFF = the shipping path): stamps Explosion into the move
-- slot, commits it, and advances the controller so the ENGINE executes the turn. B then mashes
-- A to push through the move/faint text.
--
-- PASS bar (B): Explosion stamped into the battle-mon move slot (move0==153) AND the battle
-- REACHES AN OUTCOME (gBattleOutcome != 0). The outcome is the decisive assert — the original
-- native controller-swap bug was a SOFTLOCK in an open menu that NEVER resolved; a Variant-3
-- RAM-poke that only zeroed HP without executing would also leave outcome==0 forever.
-- PASS bar (A): own mon memorialized out of the party (the normal linked-death flow).
local gBattleMons    = 0x02023BE4
local BM_MOVES       = 0x0C
local BM_HP          = 0x28
local BM_MAXHP       = 0x2C
local gBattleOutcome = 0x02023E8A
local CTRL           = 0x03004FE0      -- gBattlerControllerFuncs[0]
local ACTION_MENU    = 0x0802E439      -- action-select controller (re-validated this build)
local MOVE_EXPLOSION = 153

return function(ctx)
    local log = ctx.log
    local key0 = ctx.slot_key(0)

    if ctx.player == "a" then
        if not ctx.wait_go(36000) then return false, "no go-file" end
        ctx.frames(120)
        memory.write_u16_le(ctx.slot_base(0) + ctx.OFF_HP, 0)
        log("wrote HP=0 to slot0 (" .. key0 .. ") — partner's mon must now Explode")
        local gone = ctx.wait_until(function()
            return ctx.find_slot_by_key(key0) == nil or nil
        end, 21600, "memorialize of " .. key0)
        if not gone then return false, "own mon never memorialized" end
        return true, "faint sent + own mon memorialized"
    end

    -- ── B: drive into a live battle, advance the intro to the ACTION MENU ──────────
    local function loaded()  return memory.read_u16_le(gBattleMons + BM_MAXHP) > 0 end
    local function at_menu() return memory.read_u32_le(CTRL) == ACTION_MENU end
    local function bmon_hp()  return memory.read_u16_le(gBattleMons + BM_HP) end
    local function bmon_mv0() return memory.read_u16_le(gBattleMons + BM_MOVES) end
    local function party_hp() return memory.read_u16_le(ctx.slot_base(0) + ctx.OFF_HP) end

    local step = 0
    local reached = ctx.wait_until(function()
        if at_menu() then joypad.set({}); return true end   -- stop the instant the menu is up
        step = step + 1
        if not loaded() then
            -- not in battle yet: step into the trainer's sightline, then mash A through the
            -- walk-up cutscene + "You are challenged by X!" intro.
            if step <= 60 then joypad.set({ Down = true })
            elseif step % 2 == 0 then joypad.set({ A = true })
            else joypad.set({}) end
        else
            -- battle loaded, intro text rolling: advance with A until the action menu appears.
            if step % 2 == 0 then joypad.set({ A = true }) else joypad.set({}) end
        end
        return nil
    end, 18000, "battle action menu")
    joypad.set({})
    if not reached then
        return false, string.format("never reached the action menu (loaded=%s)", tostring(loaded()))
    end
    log(string.format("IN_BATTLE at action menu: bHP=%d move0=%d", bmon_hp(), bmon_mv0()))

    -- Wait at the menu (NO input) for the runner's go + the partner's faint to arrive.
    if not ctx.wait_go(21600) then return false, "no go-file after reaching the menu" end

    -- force_explode stamps Explosion into the move slot and skips the menu (Variant-3).
    local stamped = ctx.wait_until(function()
        return bmon_mv0() == MOVE_EXPLOSION or nil
    end, 21600, "force_explode to stamp Explosion")
    if not stamped then
        return false, "force_explode never stamped Explosion (move0=" .. bmon_mv0() .. ")"
    end
    log("Explosion stamped into move slot 0 + menu skipped (Variant-3)")

    -- Now the menu is gone; mash A to advance the move/faint/whiteout text and let the engine
    -- run the turn. The battle MUST reach an outcome — that's the no-softlock proof.
    local mash = 0
    local outcome = ctx.wait_until(function()
        local o = memory.read_u8(gBattleOutcome)
        if o ~= 0 then joypad.set({}); return o end
        mash = mash + 1
        if mash % 3 == 0 then joypad.set({ A = true }) else joypad.set({}) end
        return nil
    end, 21600, "battle to resolve (outcome != 0)")
    joypad.set({})
    if not outcome then
        return false, string.format("battle never resolved (bHP=%d partyHP=%d — softlock?)",
            bmon_hp(), party_hp())
    end
    log(string.format("resolved: outcome=%d bHP=%d partyHP=%d", outcome, bmon_hp(), party_hp()))
    if party_hp() ~= 0 then
        return false, "battle resolved but linked mon party HP != 0 (" .. party_hp() .. ")"
    end
    return true, string.format("Explosion executed + battle resolved (outcome=%d)", outcome)
end
