--[[
  lua/tests/probe_gen1_catchloop.lua — WHY does the Gen 1 catch loop end a battle early?

  This is the probe docs/gen1_catch_loop_finding.md asks for, rebuilt. Read that first.

  Recap of what is known. H.throw() pressed A twice to use the ball, then polled for the
  bag count to drop WHILE PRESSING NOTHING. Gen 1 blocks on the "Aww! It appeared to be
  caught!" text box waiting for input and only decrements the bag at the very end of the
  ball routine, so the poll never saw the decrement inside its own window — it dropped
  later, when the CALLER's corrective B presses dismissed the text. Every attempt was
  finishing the previous attempt's throw, so throw() returned false every time.

  Pressing B inside the wait loop took detected throws from 0 to 2. What still ends the
  battle after about two throws is the open question, and four hypotheses have already
  been killed by guessing. So this logs state after EVERY attempt instead of testing a
  fifth.

  Deliberately NOT a gate: it asserts almost nothing and finishes PASS regardless. Its
  output is the dump.

      python tools/run_gb_gate.py lua/tests/probe_gen1_catchloop.lua --rom red --target battle

  The three signals that discriminate, which the earlier rounds did not have:
    wNumRunAttempts    nonzero  => the cursor reached RUN and we ran. The leading suspicion.
    wEscapedFromBattle nonzero  => the wild mon fled, or we escaped.
    wBattleResult               => the engine's own verdict for the battle.
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("probe_gen1_catchloop")
local M = t.M
local fmt = string.format

-- Yellow shifts most of these by -1; take everything from the profile where one exists.
local IN_BATTLE = M.BATTLE_FLAG_ADDR
local ENEMY_HP  = M.ENEMY_MON_HP_ADDR
local ENEMY_SP  = M.ENEMY_MON_SPECIES_ADDR
local BAG_QTY0  = M.BAG_ITEMS_ADDR + 1
local CUR_MAP   = M.MAP_ID_ADDR
-- Genuinely unshifted in Yellow (pret puts both at 0xCC26/0xCC28 in either game); the same
-- literals gen1_hunt.lua uses, with the same justification.
local CUR_MENU, MAX_MENU = 0xCC26, 0xCC28
-- Probe-only reads, derived from wIsInBattle rather than hardcoded so Yellow follows:
--   pokered    wIsInBattle 0xD057 -> wNumRunAttempts 0xD120 (+0xC9), wEscapedFromBattle 0xD078 (+0x21)
--   pokeyellow             0xD056 ->                 0xD11F,                            0xD077
local RUN_ATTEMPTS  = IN_BATTLE + 0xC9
local ESCAPED       = IN_BATTLE + 0x21
local BATTLE_RESULT = 0xCF0B   -- same address in both decomps

local function u8(a) return M.read_u8(a) end

local function our_hp()
    local mon = M.readPartySlot(0)
    if not mon then return -1, -1 end
    return mon.hp, mon.maxHP
end

local function snapshot(tag)
    local hp, mx = our_hp()
    return fmt("%-20s in_battle=%d our=%d/%d enemy=%d balls=%3d party=%d "
               .. "maxMenu=%d curMenu=%d run=%d escaped=%d result=0x%02X",
               tag, u8(IN_BATTLE), hp, mx, M.read_u16_be(ENEMY_HP), u8(BAG_QTY0),
               M.getPartyCount(), u8(MAX_MENU), u8(CUR_MENU),
               u8(RUN_ATTEMPTS), u8(ESCAPED), u8(BATTLE_RESULT))
end

--- Top the active battler back up. MUST write the BATTLE struct, not the party struct:
--- MainInBattleLoop opens every turn with ReadPlayerMonCurHPAndStatus, which copies
--- wBattleMonHP INTO the party struct (core.asm:280, :1798-1809), so a party-only write is
--- erased before the next turn. Same reason force_faint had to move.
local function heal()
    if not M.BATTLE_MON_HP_ADDR then return false end
    local _, mx = our_hp()
    if mx <= 0 then return false end
    M.write_u16_be(M.BATTLE_MON_HP_ADDR, mx)
    local base = M.PARTY_BASE_ADDR + 0 * M.PARTY_STRUCT_SIZE
    M.write_u16_be(base + M.HP_OFFSET, mx)
    return true
end

local function press(btn, hold_frames, settle)
    t.hold(btn, hold_frames or 10)
    for _ = 1, (settle or 18) do t.step(nil) end
end

-- ── setup ────────────────────────────────────────────────────────────────────
local id0 = u8(M.BAG_ITEMS_ADDR)
local is_ball = false
for _, b in ipairs(M.BALL_ITEM_IDS) do
    if id0 == b then is_ball = true end
end
t.check("bag slot 0 holds a Poke Ball", is_ball, fmt("slot 0 = item 0x%02X", id0))

-- Never let the loop be ball-limited; we are diagnosing the ENDING, not the odds.
M.write_u8(BAG_QTY0, 60)
t.log("[probe] stocked 60 balls; " .. snapshot("setup"))

-- ── find a battle ────────────────────────────────────────────────────────────
-- Left/Right only. Route 1's ledges are one-way and run horizontally, so Up/Down pacing
-- eventually hops one southward into Pallet Town, which has grass tiles and encounter
-- rate 0 — that reads as endless bad luck rather than as a bug.
local start_map = u8(CUR_MAP)
local found = false
for i = 1, 600 do
    local dir = (i % 2 == 0) and "Left" or "Right"
    t.hold(dir, 12, function() return u8(IN_BATTLE) ~= 0 end)
    if u8(IN_BATTLE) ~= 0 then
        found = true
        break
    end
    if u8(CUR_MAP) ~= start_map then
        t.log(fmt("[probe] walked off map 0x%02X onto 0x%02X — aborting",
                  start_map, u8(CUR_MAP)))
        break
    end
end
t.check("found a wild battle", found)
if not found then
    t.finish("no encounter")
    return
end

t.log(fmt("[probe] wild species=0x%02X  %s", u8(ENEMY_SP), snapshot("battle start")))

-- ── the catch loop, instrumented ─────────────────────────────────────────────

--- Wait for the battle menu. Checks BEFORE pressing: the moment the menu is up an A
--- confirms whatever the cursor sits on, and the fixtures were built by throwing balls so
--- the restored wBattleAndStartSavedMenuItem starts on ITEM.
local function wait_for_menu()
    for _ = 1, 80 do
        if u8(MAX_MENU) == 1 then return true end
        if u8(IN_BATTLE) == 0 then return false end
        press("A", 4, 12)
    end
    return false
end

local function press_in_battle(btn)
    if u8(IN_BATTLE) == 0 then return false end
    press(btn)
    return u8(IN_BATTLE) ~= 0
end

--- Move to the left column, row `row` (0 = FIGHT, 1 = ITEM).
---
--- SECOND FINDING. The old blind Left/Up/(Down) sequence assumed Up always lands on row 0.
--- Each column is a TWO-item wrapping menu, so Up from row 0 wraps to row 1 and the
--- following Down wraps straight back to row 0 — meaning whenever the cursor already sat
--- on FIGHT, this returned FIGHT while claiming to have selected ITEM. That is exactly the
--- alternating "could not reach ITEM" in the first probe run: half of every attempt budget
--- was being thrown away. Drive the cursor by READING it instead of counting presses.
local function left_column(row)
    if not press_in_battle("Left") then return false end
    -- The cursor must be VERIFIED to move, not assumed to. wMaxMenuItem reads 1 in
    -- states that are not an interactive battle menu, so wait_for_menu can return true
    -- while the game is still holding a text box -- and a text box ignores Down entirely.
    -- Measured: on Blue that produced ONE throw followed by 59 consecutive "could not
    -- reach ITEM", because the loop pressed Down forever at text that only B dismisses.
    -- Red happened to get past it, which is why this looked cartridge-specific rather
    -- than like a missing state check.
    for _ = 1, 8 do
        if u8(CUR_MENU) == row then return true end
        local was = u8(CUR_MENU)
        if not press_in_battle("Down") then return false end
        if u8(CUR_MENU) == was then
            -- Down did nothing: not a live menu. Advance the text and retry.
            if not press_in_battle("B") then return false end
        end
    end
    return u8(CUR_MENU) == row
end

--- Throw one ball. THE DOCUMENTED FIX IS APPLIED HERE: press B inside the wait loop
--- instead of idling, so the text advances and the bag decrement lands inside our own
--- window rather than in the caller's corrective presses.
local function throw()
    if u8(IN_BATTLE) == 0 then return false, "not in battle" end
    local before = u8(BAG_QTY0)
    if not left_column(1) then return false, "could not reach ITEM" end
    press("A", 10, 45)                       -- open the bag
    press("A", 10, 45)                       -- use slot 0 = POKe BALL
    for _ = 1, 60 do
        press("B", 3, 9)                     -- the fix: advance the text
        if u8(BAG_QTY0) < before then return true, "ball consumed" end
        if u8(IN_BATTLE) == 0 then return true, "battle ended during throw" end
    end
    return false, "bag count never dropped"
end

local throws, attempts = 0, 0
while u8(IN_BATTLE) ~= 0 and throws < 30 and attempts < 60 do
    attempts = attempts + 1
    local pre = snapshot(fmt("attempt %2d pre", attempts))
    if not wait_for_menu() then
        t.log(fmt("attempt %2d: wait_for_menu gave up", attempts))
        t.log("    " .. snapshot("no-menu"))
        break
    end
    local ok, why = throw()
    if ok then throws = throws + 1 end
    -- THE FINDING: our level-5 starter takes ~3 damage a turn and has 20 HP, so it dies
    -- after ~7 throws and the loop then spins uselessly because the battle menu never
    -- returns. Keeping it alive is harness scaffolding of exactly the same kind as
    -- stocking 60 balls -- the rule under test is the dead zone / species clause, not
    -- whether a Squirtle survives a Pidgey.
    local hp_now = our_hp()
    if hp_now <= 8 and u8(IN_BATTLE) ~= 0 then
        heal()
        t.log(fmt("    [heal] topped up from %d HP", hp_now))
    end
    t.log(fmt("attempt %2d: throw=%-5s (%s)", attempts, tostring(ok), why))
    t.log("    " .. pre)
    t.log("    " .. snapshot(fmt("attempt %2d post", attempts)))
end

-- ── classify the ending ──────────────────────────────────────────────────────
local hp = our_hp()
local enemy = M.read_u16_be(ENEMY_HP)
local verdict
if u8(IN_BATTLE) ~= 0 then
    verdict = "still in battle (loop bound hit)"
elseif M.getPartyCount() > 1 then
    verdict = "CAUGHT IT"
elseif hp == 0 then
    verdict = "we fainted"
elseif enemy == 0 then
    verdict = "we KO'd it"
elseif u8(RUN_ATTEMPTS) > 0 then
    verdict = "WE RAN (wNumRunAttempts > 0)"
elseif u8(ESCAPED) ~= 0 then
    verdict = "it fled / we escaped (wEscapedFromBattle)"
else
    verdict = "ended with both alive and no run recorded"
end

t.log(fmt("[probe] VERDICT: %s after %d attempts / %d detected throws",
          verdict, attempts, throws))
t.log("[probe] " .. snapshot("final"))
t.check("the probe reached a conclusion", true)
t.finish(verdict)
