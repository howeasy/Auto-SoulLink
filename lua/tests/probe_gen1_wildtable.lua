--[[
  probe_gen1_wildtable.lua — is wGrassMons where we think it is?

  ANSWER: yes, and forcing WORKS. This probe previously said otherwise, and it was wrong.

  The old version "cleared" any pre-existing battle by mashing B -- but B does not flee a
  wild battle in Gen 1, there is no cancel, you have to select RUN. Its own log line read
  `in_battle=1` immediately after claiming the clear succeeded. So every measurement it took
  described the battle gatelib's boot walk had already started, whose species was latched
  BEFORE the table was written. Four hypotheses were recorded dead against that false
  negative; all four were answering a question the experiment never actually asked.

  With a leave_battle() that really runs away, the forced species is served:
      at flip: curPartySpecies=0x85 enemyMonSpecies2=0x85 enemyMon=0x85  (MAGIKARP, level 5)

  So verify against something the GAME put there, not something we wrote. Route 1's ROM data
  (data/wild/maps/Route1.asm) is:
      def_grass_wildmons 25      ; encounter rate
      db  3, PIDGEY              ; slot 0
      db  3, RATTATA             ; slot 1
      db  3, RATTATA
      db  2, RATTATA
      db  2, PIDGEY
      db  3, PIDGEY
  If wGrassRate reads 25 and slot 0 reads (3, PIDGEY), the address is right and the problem is
  timing. If it does not, the address is wrong and every "the write took" readback is worthless.

  Run against the BATTLE fixture (Route 1).
  Result file: patch/build/probe_gen1_wildtable_result.txt
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("probe_gen1_wildtable")
local M = t.M
local fmt = string.format

local PIDGEY, RATTATA, MAGIKARP = 0x24, 0xA5, 0x85
local rate_addr = M.GRASS_RATE_ADDR
local mons_addr = rate_addr and (rate_addr + 1)

t.check("the profile exposes GRASS_RATE_ADDR", rate_addr ~= nil,
        fmt("variant=%s", t.variant))
if not rate_addr then t.finish("no address") return end

t.log(fmt("wGrassRate=%#06x wGrassMons=%#06x map=0x%02X",
          rate_addr, mons_addr, M.read_u8(M.MAP_ID_ADDR)))

-- 1. The rate byte the GAME loaded. Route 1 is 25.
local rate = M.read_u8(rate_addr)
t.check("wGrassRate reads Route 1's ROM value (25)", rate == 25,
        fmt("got %d — if this is wrong, the address is wrong and every readback lies", rate))

-- 2. The slot table the GAME loaded, dumped so a wrong stride is visible too.
local dump = {}
for slot = 0, 9 do
    dump[#dump + 1] = fmt("%d:(%d,0x%02X)", slot,
                          M.read_u8(mons_addr + slot * 2),
                          M.read_u8(mons_addr + slot * 2 + 1))
end
t.log("slots " .. table.concat(dump, " "))

t.check("slot 0 is Route 1's (level 3, PIDGEY)",
        M.read_u8(mons_addr) == 3 and M.read_u8(mons_addr + 1) == PIDGEY,
        fmt("got (%d, 0x%02X) want (3, 0x%02X)",
            M.read_u8(mons_addr), M.read_u8(mons_addr + 1), PIDGEY))
t.check("slot 1 is Route 1's (level 3, RATTATA)",
        M.read_u8(mons_addr + 2) == 3 and M.read_u8(mons_addr + 3) == RATTATA,
        fmt("got (%d, 0x%02X) want (3, 0x%02X)",
            M.read_u8(mons_addr + 2), M.read_u8(mons_addr + 3), RATTATA))

-- 3. ARE WE ALREADY IN A BATTLE? gen1_gatelib's boot probes movement with Left/Right to
--    prove the game is live, and on a grass fixture that can trigger an encounter by itself.
--    If so, the species was decided BEFORE any write and the walk loop below would find
--    in_battle set on its first check — measuring a battle that predates the experiment.
local IN_BATTLE = M.BATTLE_FLAG_ADDR
local ENEMY_SP  = M.ENEMY_MON_SPECIES_ADDR
-- Informational, not a failure: gatelib's boot proves the game is live by WALKING, and on
-- a grass fixture that starts an encounter more often than not. What matters is that we
-- leave it before forcing, which the hard check below enforces.
t.log(fmt("on entry: in_battle=%d enemy=0x%02X",
          M.read_u8(IN_BATTLE), M.read_u8(ENEMY_SP)))

local function force()
    for slot = 0, 9 do
        M.write_u8(mons_addr + slot * 2, 5)
        M.write_u8(mons_addr + slot * 2 + 1, MAGIKARP)
    end
end
local function walk_to_battle()
    for i = 1, 400 do
        t.hold(({"Left", "Right"})[(i % 2) + 1], 12,
               function() return M.read_u8(IN_BATTLE) ~= 0 end)
        if M.read_u8(IN_BATTLE) ~= 0 then return true end
    end
    return false
end
--- Leave a wild battle by actually RUNNING.
---
--- THE FLAW THAT INVALIDATED EVERY EARLIER RUN OF THIS PROBE. The old version mashed B,
--- and B does not flee a wild battle in Gen 1 -- there is no cancel, you have to select
--- RUN. So the "cleared the pre-existing battle" step never cleared anything: its own log
--- line read `in_battle=1` right after claiming success. Every measurement below it was
--- therefore taken on the battle gatelib's boot walk had already started, whose species was
--- latched BEFORE the table was forced. That is why forcing looked broken, and it is why
--- the four hypotheses recorded dead in this file were all answering the wrong question.
---
--- The battle menu is two columns: >FIGHT PKMN / ITEM RUN. RUN is the right column, row 1.
--- Drive the cursor by READING wCurrentMenuItem rather than counting presses -- each column
--- is a two-item WRAPPING menu, so a blind Up/Down lands on the wrong row exactly when the
--- cursor already sat where you wanted it.
local CUR_MENU, MAX_MENU = 0xCC26, 0xCC28
local function leave_battle()
    for _ = 1, 30 do
        if M.read_u8(IN_BATTLE) == 0 then return true end
        -- Advance any text until an interactive menu is up.
        for _ = 1, 60 do
            if M.read_u8(MAX_MENU) == 1 or M.read_u8(IN_BATTLE) == 0 then break end
            t.hold("B", 4, nil)
            for _ = 1, 8 do t.step(nil) end
        end
        if M.read_u8(IN_BATTLE) == 0 then return true end
        t.hold("Right", 10, nil)
        for _ = 1, 12 do t.step(nil) end
        for _ = 1, 6 do
            if M.read_u8(CUR_MENU) == 1 then break end
            local was = M.read_u8(CUR_MENU)
            t.hold("Down", 10, nil)
            for _ = 1, 12 do t.step(nil) end
            if M.read_u8(CUR_MENU) == was then
                t.hold("B", 4, nil)
                for _ = 1, 8 do t.step(nil) end
            end
        end
        t.hold("A", 10, nil)                     -- confirm RUN
        for _ = 1, 40 do t.step(nil) end
        for _ = 1, 40 do                          -- dismiss "Got away safely!"
            if M.read_u8(IN_BATTLE) == 0 then return true end
            t.hold("B", 3, nil)
            for _ = 1, 8 do t.step(nil) end
        end
    end
    return M.read_u8(IN_BATTLE) == 0
end


-- Clear it if so, then re-check, so the experiment starts from the overworld either way.
if M.read_u8(IN_BATTLE) ~= 0 then
    local left = leave_battle()
    t.log(fmt("cleared the pre-existing battle: ok=%s in_battle=%d",
              tostring(left), M.read_u8(IN_BATTLE)))
    -- HARD STOP if we could not. Continuing would measure the species of a battle that
    -- started before the force, which is precisely the mistake that made this probe report
    -- a false negative for four rounds.
    t.check("reached the overworld before forcing the table", left,
            "still in the boot-walk battle; every measurement below would be about THAT "
            .. "battle, whose species was chosen before anything was written")
    if not left then t.finish("could not leave the pre-existing battle") return end
end

-- 4. Force it, walk, and take the SECOND encounter.
--
-- `wIsInBattle == 0` is NOT the same as "no encounter pending". TryDoWildEncounter picks the
-- slot on a step, but the flag does not flip until several frames later (fade, music), so an
-- encounter committed by gen1_gatelib's boot movement probe is already decided while
-- in_battle still reads 0. A table forced inside that gap applies to the NEXT encounter, not
-- the one about to appear — which is exactly the (3, PIDGEY) we kept measuring.
force()
-- Flush anything already committed. If nothing is pending this simply meets a wild mon from
-- the forced table, which is the answer we want either way.
if walk_to_battle() then
    t.log(fmt("first encounter after forcing: 0x%02X (level %d) — flushing it",
              M.read_u8(ENEMY_SP), M.read_u8(M.ENEMY_MON_LEVEL_ADDR)))
    leave_battle()
    for _ = 1, 120 do t.step(nil) end
end
force()                                   -- the battle reloaded the table on its way out
t.check("the forced table reads back as MAGIKARP", M.read_u8(mons_addr + 1) == MAGIKARP,
        fmt("got 0x%02X", M.read_u8(mons_addr + 1)))

local entered = walk_to_battle()
t.check("a second encounter happened", entered, fmt("in_battle=%d", M.read_u8(IN_BATTLE)))

if entered then
    -- Sample BOTH, and sample late. wCurOpponent is what wild_encounters.asm writes the
    -- chosen slot's species into; wEnemyMon (0xCFE5) is the battle struct that
    -- LoadEnemyMonData builds from it a few frames later. Reading the struct the instant
    -- wIsInBattle flips can catch it before it is populated.
    -- MEASURE WHAT THE SLOT READ ACTUALLY WRITES. The earlier version asserted on
    -- wCurOpponent, which TryDoWildEncounter never touches -- it is set for TRAINER
    -- battles, so reading 0x00 in a wild battle is correct and told us nothing. pokered
    -- engine/battle/wild_encounters.asm:74-79 is explicit:
    --     add hl, bc / ld a,[hli] / ld [wCurEnemyLevel],a
    --     ld a,[hl]  / ld [wCurPartySpecies],a / ld [wEnemyMonSpecies2],a
    -- so wCurPartySpecies and wEnemyMonSpecies2 are the two bytes that carry the chosen
    -- slot, and wEnemyMon is only built from them later by LoadEnemyMonData. If those two
    -- hold MAGIKARP and wEnemyMon holds PIDGEY, the table IS being read and something
    -- downstream overrides. If they hold PIDGEY, the read never saw our bytes.
    -- Derived from wGrassRate so Yellow's -1 shift follows: 0xD887 -> 0xCF91 / 0xCFD8.
    local CUR_SPECIES = M.GRASS_RATE_ADDR - 0x8F6   -- wCurPartySpecies
    local ENEMY_SP2   = M.GRASS_RATE_ADDR - 0x8AF   -- wEnemyMonSpecies2
    local CUR_OPPONENT = M.CUR_OPPONENT_ADDR
    t.log(fmt("at flip: curPartySpecies=0x%02X enemyMonSpecies2=0x%02X enemyMon=0x%02X curOpponent=0x%02X",
              M.read_u8(CUR_SPECIES), M.read_u8(ENEMY_SP2), M.read_u8(ENEMY_SP),
              CUR_OPPONENT and M.read_u8(CUR_OPPONENT) or 0))
    for _ = 1, 120 do t.step(nil) end
    t.log(fmt("after 120f: curPartySpecies=0x%02X enemyMonSpecies2=0x%02X enemyMon=0x%02X level=%d",
              M.read_u8(CUR_SPECIES), M.read_u8(ENEMY_SP2), M.read_u8(ENEMY_SP),
              M.read_u8(M.ENEMY_MON_LEVEL_ADDR)))
    local met = M.read_u8(ENEMY_SP)
    t.check("wCurPartySpecies holds the forced species",
            M.read_u8(CUR_SPECIES) == MAGIKARP,
            fmt("curPartySpecies=0x%02X want 0x%02X — THIS is the byte the slot read "
                .. "writes (wild_encounters.asm:78)", M.read_u8(CUR_SPECIES), MAGIKARP))
    t.log(fmt("met 0x%02X; table now reads slot0=(%d,0x%02X) rate=%d",
              met, M.read_u8(mons_addr), M.read_u8(mons_addr + 1), M.read_u8(rate_addr)))
    t.check("the forced species is what we actually met", met == MAGIKARP,
            fmt("met 0x%02X, forced 0x%02X — if the table still reads MAGIKARP here, the "
                .. "game is not reading these bytes; if it reads PIDGEY again, something "
                .. "reloaded it between the write and the encounter", met, MAGIKARP))
end

t.finish(fmt("variant=%s", t.variant))
