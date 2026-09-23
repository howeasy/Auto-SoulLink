-- scenario_gen3_explode.lua — explode_gen3 (RR only, PLAN §14 P5, card C5-5).
--
-- BLOCKED like the other "battle"-target RR scenarios (tests/fixtures/gen3/rr_battle{,_b}.sav do
-- not exist), and further on a fixture this row cannot supply at all: B needs to already be
-- positioned in a trainer's sightline (the OLD client's row used slink_prebattle.State for
-- exactly this), which "battle" (a grass encounter fixture) is not. Written for structural
-- correctness, not yet exercised.
--
-- Ported behaviour-for-behaviour from the OLD RR duo driver's scenario_explode.lua (trusted RR
-- addresses, docs/gen3/PLAN.md §0 "old RR client addresses trusted"): a coerced move only
-- EXECUTES if the foe also commits an action, so B drives itself into a REAL battle (not a
-- frozen state) and parks at the action menu with NO input (pressing A would commit our own
-- move and pre-empt the Explosion). A zeroes its own linked mon's HP directly
-- (ctx.zero_hp, duo_gen3_main.lua) once released; the overworld watcher reads that as a faint
-- and the client sends `faint`, which the server (--explode-mode) answers by queuing
-- force_explode to B instead of force_faint. lua/gen3/client.lua's explode_step (Variant-3)
-- stamps Explosion into the move slot and skips the menu; the engine then runs the turn for
-- real. PASS bar for B is the battle reaching an OUTCOME (gBattleOutcome ~= 0) -- the original
-- native controller-swap bug was a SOFTLOCK in an open menu that never resolved.
local gBattleMons    = 0x02023BE4
local BM_MOVES       = 0x0C
local BM_HP          = 0x28
local BM_MAXHP       = 0x2C
local gBattleOutcome = 0x02023E8A
local CTRL           = 0x03004FE0      -- gBattlerControllerFuncs[0]
local ACTION_MENU    = 0x0802E439      -- action-select controller (old driver, re-validated then)
local MOVE_EXPLOSION = 153

return function(ctx)
    local log = ctx.log

    if ctx.player == "a" then
        if not ctx.wait_go() then return false, "no go-file" end
        local linked = ctx.linked()
        if not linked then return false, "the go-file names no LINKED key" end
        if not ctx.find(linked) then return false, "the linked key " .. linked .. " is not in the party" end
        ctx.frames(120)
        if not ctx.zero_hp(linked) then return false, "could not zero " .. linked .. "'s HP" end
        log("wrote HP=0 to " .. linked .. " -- partner's mon must now Explode")
        if not ctx.wait_sent("memorialize_done", linked, 1800) then
            return false, "own mon never memorialized"
        end
        local ok, why = ctx.save("explode")
        if not ok then return false, why end
        return true, "faint sent + own mon memorialized"
    end

    -- ── B: drive into a live battle, advance the intro to the ACTION MENU ──────────
    local function loaded()  return memory.read_u16_le(gBattleMons + BM_MAXHP) > 0 end
    local function at_menu() return memory.read_u32_le(CTRL) == ACTION_MENU end
    local function bmon_hp()  return memory.read_u16_le(gBattleMons + BM_HP) end
    local function bmon_mv0() return memory.read_u16_le(gBattleMons + BM_MOVES) end

    local step = 0
    local reached = ctx.wait_until(function()
        if at_menu() then joypad.set({}); return true end
        step = step + 1
        if not loaded() then
            if step <= 60 then joypad.set({ Down = true })
            elseif step % 2 == 0 then joypad.set({ A = true })
            else joypad.set({}) end
        else
            if step % 2 == 0 then joypad.set({ A = true }) else joypad.set({}) end
        end
        return nil
    end, 300, "battle action menu")
    joypad.set({})
    if not reached then
        return false, string.format("never reached the action menu (loaded=%s)", tostring(loaded()))
    end
    log(string.format("IN_BATTLE at action menu: bHP=%d move0=%d", bmon_hp(), bmon_mv0()))

    if not ctx.wait_go(300) then return false, "no go-file after reaching the menu" end

    local stamped = ctx.wait_until(function()
        return bmon_mv0() == MOVE_EXPLOSION or nil
    end, 300, "force_explode to stamp Explosion")
    if not stamped then
        return false, "force_explode never stamped Explosion (move0=" .. bmon_mv0() .. ")"
    end
    log("Explosion stamped into move slot 0 + menu skipped (Variant-3)")

    local mash = 0
    local outcome = ctx.wait_until(function()
        local o = memory.read_u8(gBattleOutcome)
        if o ~= 0 then joypad.set({}); return o end
        mash = mash + 1
        if mash % 3 == 0 then joypad.set({ A = true }) else joypad.set({}) end
        return nil
    end, 300, "battle to resolve (outcome ~= 0)")
    joypad.set({})
    if not outcome then
        return false, string.format("battle never resolved (bHP=%d — softlock?)", bmon_hp())
    end
    log(string.format("resolved: outcome=%d bHP=%d", outcome, bmon_hp()))
    if not ctx.wait_sent("memorialize_done", nil, 1800) then
        return false, "partner's mon never memorialized after the Explosion"
    end
    local ok, why = ctx.save("explode")
    if not ok then return false, why end
    return true, string.format("Explosion executed + battle resolved (outcome=%d)", outcome)
end
