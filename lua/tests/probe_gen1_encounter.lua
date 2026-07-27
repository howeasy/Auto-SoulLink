--[[
  lua/tests/probe_gen1_encounter.lua — can we actually PLAY the game from a script?

  Every Gen 1 live test so far has injected the state it then verifies: pairs come from
  /api/inject_link, battles from poking wIsInBattle. Nothing has ever walked into grass,
  met a wild Pokémon and thrown a ball. This probe establishes whether that is drivable
  before any scenario is written on top of it — measure first, per the pattern that found
  every other Gen 1 defect.

  Questions it answers, in order:
    1. Does walking in Route 1 grass reliably trigger a wild encounter, and in how long?
    2. What does the battle menu look like in RAM — which index is ITEM?
    3. Can we open the bag, select a Poké Ball and throw it?
    4. Does the catch stick (party count goes up)?

  Runs against tests/fixtures/gen1/<rom>_battle.SaveRAM, which starts on Route 1 (map 0x0C)
  at (10,35) — fixtures that until now nothing loaded.

  Result file: patch/build/probe_gen1_encounter_result.txt
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("probe_gen1_encounter")
local M = t.M
local fmt = string.format

local IN_BATTLE   = 0xD057
local CUR_MAP     = 0xD35E
local Y_COORD     = 0xD361
local X_COORD     = 0xD362
local CUR_MENU    = 0xCC26
local MAX_MENU    = 0xCC28
local NUM_BAG     = 0xD31D
local BAG_ITEMS   = 0xD31E
local ENEMY_SPEC  = 0xCFE5
local ENEMY_LEVEL = 0xCFF3
local BATTLE_TYPE = 0xD05A
local TEXT_ID     = 0xD125   -- wTextBoxID, nonzero while a box is up

local function u8(a) return M.read_u8(a) end
local function pos() return u8(X_COORD), u8(Y_COORD) end

t.check("started on Route 1 (map 0x0C)", u8(CUR_MAP) == 0x0C,
        fmt("map=0x%02X pos=(%d,%d)", u8(CUR_MAP), pos()))

-- Bag contents, so we know a ball is actually there and at which slot.
do
    local n = u8(NUM_BAG)
    local parts, ball_slot = {}, nil
    for i = 0, math.min(n, 20) - 1 do
        local id, qty = u8(BAG_ITEMS + i * 2), u8(BAG_ITEMS + i * 2 + 1)
        parts[#parts + 1] = fmt("[%d]id=%d x%d", i, id, qty)
        if id == 4 and not ball_slot then ball_slot = i end   -- POKE_BALL = 4
    end
    t.check("bag holds a Poké Ball", ball_slot ~= nil,
            fmt("n=%d %s -> ball at slot %s", n, table.concat(parts, " "), tostring(ball_slot)))
end

-- ── 1. Trigger a real wild encounter by walking ──────────────────────────────
-- Gen 1 needs a direction HELD to move; a tap only turns. Alternate up/down so we stay in
-- the same patch of grass rather than walking off the route.
local dirs = {"Up", "Down"}
local steps, entered = 0, false
for i = 1, 400 do
    local d = dirs[(i % 2) + 1]
    for _ = 1, 12 do
        t.step({[d] = true})
        if u8(IN_BATTLE) ~= 0 then entered = true break end
    end
    steps = i
    if entered then break end
end
t.check("walking in grass triggers a wild encounter", entered,
        fmt("after %d held steps, wIsInBattle=%d", steps, u8(IN_BATTLE)))
if not entered then t.finish("no encounter") return end

t.check("it is a WILD battle (wIsInBattle == 1)", u8(IN_BATTLE) == 1,
        fmt("wIsInBattle=%d wBattleType=%d", u8(IN_BATTLE), u8(BATTLE_TYPE)))
t.check("enemy mon is loaded", u8(ENEMY_SPEC) ~= 0,
        fmt("species=0x%02X level=%d", u8(ENEMY_SPEC), u8(ENEMY_LEVEL)))

-- ── 2. Get to the battle menu ────────────────────────────────────────────────
-- "Wild X appeared!" plus the send-out text has to be cleared first. Press A until the
-- battle menu is actually up, which we detect via wMaxMenuItem == 3 (FIGHT/PKMN/ITEM/RUN).
local at_menu = false
for _ = 1, 60 do
    t.hold("A", 4, nil)
    for _ = 1, 12 do t.step(nil) end
    if u8(MAX_MENU) == 3 then at_menu = true break end
    if u8(IN_BATTLE) == 0 then break end
end
t.check("reached the battle menu (wMaxMenuItem == 3)", at_menu,  -- wTextBoxID stays 1: the menu itself is a text box
        fmt("wMaxMenuItem=%d wCurrentMenuItem=%d wTextBoxID=%d in_battle=%d",
            u8(MAX_MENU), u8(CUR_MENU), u8(TEXT_ID), u8(IN_BATTLE)))
t.log(fmt("battle menu: cur=%d max=%d", u8(CUR_MENU), u8(MAX_MENU)))

-- ── 3. Throw a Poké Ball and catch it. ─────────────────────────────────────
-- Layout confirmed by screenshot (patch/build/probe_enc_05_left.png), NOT derived:
--     >FIGHT   PKMN
--      ITEM    RUN
-- Left column is FIGHT(0)/ITEM(1); the right column is PKMN/RUN with +2 applied. That is
-- pokered's "swapped the positions ... in first generation English versions"
-- (engine/battle/core.asm:2141) — ITEM is DOWN from FIGHT, in the same column.
local ROOT = (SLINK_ROOT or os.getenv("SLINK_ROOT"))

-- Wait for the battle menu proper: each column is its own 2-item menu, so wMaxMenuItem==1.
local menu_up = false
for _ = 1, 40 do
    t.hold("A", 3, nil)
    for _ = 1, 10 do t.step(nil) end
    if u8(MAX_MENU) == 1 then menu_up = true break end
    if u8(IN_BATTLE) == 0 then break end
end
t.check("battle menu is up (wMaxMenuItem == 1, two-column layout)", menu_up,
        fmt("max=%d cur=%d", u8(MAX_MENU), u8(CUR_MENU)))

if menu_up then
    -- Make sure we are on FIGHT in the LEFT column, then step down to ITEM.
    t.hold("Left", 6, nil); for _ = 1, 10 do t.step(nil) end
    t.hold("Up", 6, nil);   for _ = 1, 10 do t.step(nil) end
    t.hold("Down", 6, nil); for _ = 1, 12 do t.step(nil) end
    t.check("cursor moved to ITEM (left column, row 1)", u8(CUR_MENU) == 1,
            fmt("cur=%d", u8(CUR_MENU)))
    client.screenshot(ROOT .. "/patch/build/probe_enc_06_item.png")

    t.hold("A", 6, nil); for _ = 1, 40 do t.step(nil) end
    client.screenshot(ROOT .. "/patch/build/probe_enc_07_bag.png")
    t.log(fmt("bag opened? max=%d cur=%d in_battle=%d", u8(MAX_MENU), u8(CUR_MENU), u8(IN_BATTLE)))

    -- The bag check above proved POKE_BALL (id 4) is at slot 0, so A uses it.
    local party_before = M.getPartyCount()
    local balls_before = u8(BAG_ITEMS + 1)
    t.hold("A", 6, nil); for _ = 1, 30 do t.step(nil) end
    client.screenshot(ROOT .. "/patch/build/probe_enc_08_thrown.png")

    -- The throw succeeds into a nickname prompt ("Do you want to give a nickname to
    -- PIDGEY?"), confirmed by screenshot. Mash **B**, not A: B advances text AND answers NO
    -- on a yes/no, whereas A would answer YES and drop us into the naming screen with no way
    -- back. Run until the battle actually ends, so the party struct is finalised before we
    -- read it — reading during the catch shows count=2 with an all-zero slot.
    local caught = false
    for _ = 1, 200 do
        t.hold("B", 3, nil)
        for _ = 1, 12 do t.step(nil) end
        if u8(IN_BATTLE) == 0 then caught = M.getPartyCount() > party_before break end
    end
    for _ = 1, 60 do t.step(nil) end
    client.screenshot(ROOT .. "/patch/build/probe_enc_09_after.png")

    t.check("a Poké Ball was actually consumed", u8(BAG_ITEMS + 1) < balls_before,
            fmt("balls %d -> %d", balls_before, u8(BAG_ITEMS + 1)))
    t.check("battle ended and we are back in the overworld", u8(IN_BATTLE) == 0,
            fmt("in_battle=%d map=0x%02X", u8(IN_BATTLE), u8(CUR_MAP)))
    t.check("CAUGHT a real wild Pokemon", caught,
            fmt("party %d -> %d", party_before, M.getPartyCount()))
    if caught then
        local mon = M.readPartySlot(M.getPartyCount() - 1)
        t.check("the caught mon has a well-formed SLink key",
                mon and mon.key and #mon.key == 12 and mon.species_index ~= 0,
                fmt("key=%s species=0x%02X level=%d hp=%d/%d",
                    mon and mon.key or "?", mon and mon.species_index or 0,
                    mon and mon.level or 0, mon and mon.hp or 0, mon and mon.maxHP or 0))
        t.check("it is the Pidgey we actually met, not a leftover",
                mon and mon.species_index == 0x24,
                fmt("caught species 0x%02X, met 0x24", mon and mon.species_index or 0))
    end
end

t.finish(fmt("variant=%s map=0x%02X in_battle=%d enemy=0x%02X",
             t.variant, u8(CUR_MAP), u8(IN_BATTLE), u8(ENEMY_SPEC)))
