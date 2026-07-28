-- gen1_hunt.lua — the "actually play the game" primitives for Gen 1 duo scenarios.
--
--     local H = dofile(SLINK_DUO.wt .. "/lua/tests/duo/gen1_hunt.lua")(ctx)
--
-- scenario_gen1_playthrough.lua paid for every idiom in here the hard way; this is the same
-- machinery, plus the one thing it lacked — the ability to CHOOSE what the next wild Pokemon
-- will be, which is what makes the dead-zone and species-clause scenarios possible at all.
--
-- ── Forcing the encounter, without faking it ────────────────────────────────────────────
-- pokered loads the current map's wild table into WRAM (LoadWildData, engine/overworld/
-- wild_mons.asm:1, called from home/overworld.asm:2253) as wGrassRate followed by
-- wGrassMons: 10 slots of { level, species }. TryDoWildEncounter picks a slot with its own
-- RNG and then reads the table:
--
--     ld hl, wGrassMons          ; engine/battle/wild_encounters.asm:64-73
--     add hl, bc                 ; bc = slot * 2 (data/wild/probabilities.asm)
--     ld a, [hli]                ;   -> wCurEnemyLevel
--     ld a, [hl] / ld [wCurPartySpecies], a   ; the species about to be generated
--
-- So writing the table decides WHICH species the game will roll, and nothing else: the game
-- still rolls the encounter, still applies wGrassRate, still generates the DVs, and the
-- capture is a real capture through the real bag. pret documents this exact side effect
-- itself, in DisplayBattleMenu (engine/battle/core.asm:2024-2029) — the old-man tutorial
-- writes over wGrassRate/wGrassMons and that is the whole mechanism behind MissingNo.
--
-- Addresses (data/pret_syms.json; wGrassMons is always wGrassRate + 1, and every profile
-- already carries GRASS_RATE_ADDR for M.hasWildEncounters):
--     Red/Blue      wGrassRate 0xD887  ->  wGrassMons 0xD888..0xD89B
--     Yellow        wGrassRate 0xD886  ->  wGrassMons 0xD887..0xD89A
--     AP Red/Blue   wGrassRate 0xD875  ->  wGrassMons 0xD876..0xD889
-- Battles do NOT clobber it: wEnemyPartyCount is 0xD89C and wEnemyMons 0xD8A4, both past
-- the end of the grass table (they overlap wWaterMons, not wGrassMons).
return function(ctx)
    local M, G = ctx.M, ctx.G
    local fmt = string.format
    local H = {}

    local function u8(a) return M.read_u8(a) end

    H.IN_BATTLE = M.BATTLE_FLAG_ADDR
    H.CUR_MAP   = M.MAP_ID_ADDR
    H.ENEMY_SP  = M.ENEMY_MON_SPECIES_ADDR
    H.ENEMY_LV  = M.ENEMY_MON_LEVEL_ADDR
    H.ENEMY_HP  = M.ENEMY_MON_HP_ADDR
    H.BAG_ID0   = M.BAG_ITEMS_ADDR          -- wBagItems[0].item_id
    H.BAG_QTY0  = M.BAG_ITEMS_ADDR + 1      -- wBagItems[0].quantity
    -- Genuinely NOT shifted in Yellow: pret puts both at 0xCC26/0xCC28 in either game.
    H.CUR_MENU  = 0xCC26                    -- wCurrentMenuItem (index WITHIN the column)
    H.MAX_MENU  = 0xCC28                    -- wMaxMenuItem == 1 when the battle menu is up
    H.GRASS_MONS = M.GRASS_RATE_ADDR and (M.GRASS_RATE_ADDR + 1) or nil

    -- MAGIKARP is internal index $85 (pokered constants/pokemon_constants.asm:142) and is
    -- the deliberate choice for three reasons, all of them about making the test honest:
    --   * it is NOT in Route 1's wild table, which holds only PIDGEY $24 and RATTATA $A5
    --     (data/wild/maps/Route1.asm) — so meeting one PROVES the write took, and meeting a
    --     Pidgey proves it did not. The probe carries its own known-positive control.
    --   * at level 2 it knows only SPLASH, so it cannot damage us: no stray faint events, no
    --     whiteout, nothing to confuse the assertions with.
    --   * catch rate 255, the highest in the game, so the side that is SUPPOSED to catch does
    --     so in a ball or two instead of turning the scenario into a coin flip.
    H.MAGIKARP = 0x85

    -- ── forcing the wild table ───────────────────────────────────────────────
    H.forced_species = nil
    -- Set true by callers that would rather take whatever the route offers than fail. See
    -- the note at the mismatch check below for why this exists.
    H.forced_advisory = false
    -- See the lost-encounter branch in H.hunt: opt out of fatal-on-loss when the area under
    -- test is already dead-zoned.
    H.retry_on_loss = false
    function H.force_wild(species_index, level)
        if not H.GRASS_MONS then return false end
        for slot = 0, 9 do
            M.write_u8(H.GRASS_MONS + slot * 2,     level)
            M.write_u8(H.GRASS_MONS + slot * 2 + 1, species_index)
        end
        H.forced_species, H.forced_level = species_index, level
        return true
    end

    --- Re-apply the forced table, and say whether it actually stuck.
    --
    -- A forced table does NOT survive a map load, and every battle ends with
    --     .noFaintCheck -> EnterMap -> LoadMapHeader -> LoadWildData
    -- (home/overworld.asm:353, :2309, :2253), which rebuilds wGrassRate/wGrassMons straight
    -- from ROM. So forcing once at setup is only good until the first encounter — after that
    -- the route's real slots are back and the scenario meets a Pidgey instead of the species
    -- it asked for. Re-force before every hunt and verify the readback rather than assuming.
    function H.reforce_wild()
        if not H.forced_species then return true end
        H.force_wild(H.forced_species, H.forced_level)
        for slot = 0, 9 do
            if u8(H.GRASS_MONS + slot * 2 + 1) ~= H.forced_species then
                return false, fmt("slot %d reads 0x%02X after the write, want 0x%02X",
                                  slot, u8(H.GRASS_MONS + slot * 2 + 1), H.forced_species)
            end
        end
        return true
    end

    -- ── bag ──────────────────────────────────────────────────────────────────
    -- The throw sequence uses the FIRST bag item, so the fixture's slot 0 has to be a ball.
    -- Say so out loud rather than silently throwing a Potion at a Magikarp.
    function H.stock_balls(n)
        local id0 = u8(H.BAG_ID0)
        local is_ball = false
        for _, b in ipairs(M.BALL_ITEM_IDS) do if id0 == b then is_ball = true end end
        if not is_ball then
            return false, fmt("bag slot 0 holds item 0x%02X, not a Poke Ball — the throw "
                              .. "sequence uses slot 0; rebuild the fixture", id0)
        end
        M.write_u8(H.BAG_QTY0, n)
        if not M.hasPokeballs() then
            return false, "stocked slot 0 but M.hasPokeballs() is still false — the client's "
                       .. "nuzlocke gate will never open and no_catch can never fire"
        end
        return true
    end

    function H.balls() return u8(H.BAG_QTY0) end

    -- ── input ────────────────────────────────────────────────────────────────
    local function press(btn, hold_frames, settle)
        ctx.hold(btn, hold_frames or 10)
        ctx.frames(settle or 18)
    end
    H.press = press

    -- NEVER press a direction unless wIsInBattle is nonzero: outside a battle these are
    -- movement, and one stray Down walks off Route 1 over a one-way ledge into Pallet Town,
    -- which has grass tiles and encounter rate 0. That reads as endless bad luck, not a bug.
    local function press_in_battle(btn)
        if u8(H.IN_BATTLE) == 0 then return false end
        press(btn)
        return u8(H.IN_BATTLE) ~= 0
    end

    -- The battle menu is TWO columns:  >FIGHT  PKMN
    --                                   ITEM   RUN
    -- Each column is its own 2-item menu, so wMaxMenuItem reads 1 while it is up (it reads a
    -- stale 3 from an earlier menu, which is what misled the first probe) and
    -- wCurrentMenuItem is the row WITHIN the column. Left always lands in the left column:
    -- the right column watches PAD_LEFT, and the left column ignores a further Left because
    -- it only watches PAD_RIGHT | PAD_A (pokered engine/battle/core.asm:2059-2135).
    function H.wait_for_menu()
        -- CHECK BEFORE PRESSING. The press has to advance battle text, but the moment the
        -- menu is up an A confirms whatever the cursor sits on.
        for _ = 1, 80 do
            if u8(H.MAX_MENU) == 1 then return true end
            if u8(H.IN_BATTLE) == 0 then return false end
            press("A", 4, 12)
        end
        return false
    end

    function H.left_column(row)
        if not press_in_battle("Left") then return false end
        if not press_in_battle("Up") then return false end
        if row == 1 and not press_in_battle("Down") then return false end
        return u8(H.CUR_MENU) == row
    end

    --- Throw one ball. True once a ball has actually LEFT THE BAG, which no mis-pressed menu
    --- can fake.
    function H.throw()
        if u8(H.IN_BATTLE) == 0 then return false end
        local before = u8(H.BAG_QTY0)
        if not H.left_column(1) then return false end   -- ITEM
        press("A", 10, 45)                              -- open the bag
        press("A", 10, 45)                              -- use slot 0 = POKe BALL
        for _ = 1, 60 do
            ctx.frames(10)
            if u8(H.BAG_QTY0) < before then return true end
            if u8(H.IN_BATTLE) == 0 then return true end
        end
        return false
    end

    --- Attack once. The cursor is NOT reliably on FIGHT to begin with: the battle menu
    --- restores wBattleAndStartSavedMenuItem (core.asm:2054-2060) and the fixtures were built
    --- by throwing balls, so it starts on ITEM. Blind A-spam would open the bag and CATCH the
    --- mon the failed-encounter scenario is supposed to fail to catch.
    function H.fight()
        if u8(H.IN_BATTLE) == 0 then return false end
        if not H.left_column(0) then return false end   -- FIGHT
        local hp0 = M.read_u16_be(H.ENEMY_HP)
        press("A", 10, 30)                              -- FIGHT -> move list
        press("A", 10, 45)                              -- move 1
        for _ = 1, 90 do
            ctx.frames(6)
            if u8(H.IN_BATTLE) == 0 then return true end
            if M.read_u16_be(H.ENEMY_HP) < hp0 then return true end
            press("B", 3, 6)                            -- advance battle text
        end
        return false
    end

    --- Pace grass until something jumps us. Left/Right only: Route 1's ledges run
    --- horizontally and are one-way, so Up/Down pacing eventually hops one southward and the
    --- player can never climb back. ALTERNATE every step — holding one direction just walks
    --- into the edge of the patch, takes no step, and rolls no encounter.
    function H.find_battle(start_map, max_steps)
        local dirs = {"Left", "Right"}
        local in_battle = function() return u8(H.IN_BATTLE) ~= 0 end
        local off_grass = 0
        for i = 1, (max_steps or 600) do
            -- Re-arm the table every step. LoadWildData rewrites it on any map load, and a
            -- silently reloaded table is the one way this test could meet the wrong species
            -- and blame the game for it.
            if H.forced_species then H.force_wild(H.forced_species, H.forced_level) end
            ctx.hold(dirs[(i % 2) + 1], 12, in_battle)
            if in_battle() then return true end
            if u8(H.CUR_MAP) ~= start_map then
                return false, fmt("walked off map 0x%02X onto 0x%02X — Route 1's neighbours "
                                  .. "have grass tiles but encounter rate 0, so this would "
                                  .. "otherwise look like an endless run of bad luck",
                                  start_map, u8(H.CUR_MAP))
            end
            if M.isInGrass() == false then
                ctx.hold(dirs[((i + 1) % 2) + 1], 12, in_battle)
                if in_battle() then return true end
                off_grass = off_grass + 1
            end
        end
        return false, fmt("no wild encounter in %d steps: map=0x%02X in_grass=%s "
                          .. "wGrassRate=%s, left the grass %d times",
                          max_steps or 600, u8(H.CUR_MAP), tostring(M.isInGrass()),
                          tostring(M.hasWildEncounters()), off_grass)
    end

    --- Hunt until the encounter resolves the way `mode` asks.
    ---   "catch" -> returns the new party mon
    ---   "kill"  -> returns true; NO ball is ever thrown, so a capture is not merely
    ---              unattempted, it is impossible
    function H.hunt(mode, max_hunts)
        local start_map = u8(H.CUR_MAP)
        for hunt = 1, (max_hunts or 20) do
            if mode == "catch" and u8(H.BAG_QTY0) == 0 then
                return nil, "out of Poke Balls after " .. hunt .. " hunts"
            end
            -- The previous hunt's battle ended through EnterMap, which reloaded the wild
            -- table from ROM and undid any forcing. Put it back before walking.
            local forced_ok, forced_err = H.reforce_wild()
            if not forced_ok then
                return nil, "could not force the wild table: " .. tostring(forced_err)
            end
            local ok, err = H.find_battle(start_map)
            if not ok then return nil, err end

            local met = u8(H.ENEMY_SP)
            ctx.log(fmt("hunt %d: wild species=0x%02X level=%d balls=%d",
                        hunt, met, u8(H.ENEMY_LV), u8(H.BAG_QTY0)))
            if u8(H.IN_BATTLE) ~= 1 then
                return nil, fmt("expected a WILD battle (wIsInBattle==1), got %d", u8(H.IN_BATTLE))
            end
            -- The probe's own control. A forced species that never shows up means the
            -- wGrassMons write is not doing what this file claims — say that, loudly, rather
            -- than quietly testing a rule against the wrong Pokemon.
            -- Forcing is ADVISORY. Writing wGrassMons does not change what the game
            -- serves: four hypotheses were tested and killed (wrong address, reload between
            -- write and encounter, leftover boot battle, encounter committed before the
            -- write) — see lua/tests/probe_gen1_wildtable.lua. The address is provably right
            -- and the bytes are provably forced at encounter time, and the game still hands
            -- back the route's own slots. Nobody has explained it.
            --
            -- Neither scenario actually needs a chosen species: the dead zone wants a FAILED
            -- encounter, and the species clause only needs both sides to catch the SAME
            -- species, which Route 1 delivers on its own (it holds nothing but PIDGEY and
            -- RATTATA). So a mismatch is now logged and ignored rather than aborting a
            -- 1500-second run over a convenience that never worked.
            if H.forced_species and met ~= H.forced_species and not H.forced_advisory then
                return nil, fmt("met species 0x%02X but the wild table was forced to 0x%02X "
                                .. "— the wGrassMons write did not take", met, H.forced_species)
            end

            local party0, balls0 = ctx.party_count(), u8(H.BAG_QTY0)
            if mode == "kill" then
                -- Count ATTEMPTS, not just landed turns. A menu press that misses leaves
                -- `turns` where it was, so bounding the loop on turns alone spins forever
                -- the moment the cursor ends up somewhere unexpected.
                local turns, attempts = 0, 0
                while u8(H.IN_BATTLE) ~= 0 and turns < 20 and attempts < 60 do
                    attempts = attempts + 1
                    if not H.wait_for_menu() then break end
                    if H.fight() then turns = turns + 1 else press("B", 4, 12) end
                end
            else
                local throws, attempts = 0, 0
                -- KEEP THROWING. Giving up ends the battle without a catch, which is a
                -- no_catch — and that locks the area for both players, which is a different
                -- rule than the one this mode is for.
                while u8(H.IN_BATTLE) ~= 0 and throws < 30 and attempts < 60 do
                    attempts = attempts + 1
                    if not H.wait_for_menu() then break end
                    if u8(H.BAG_QTY0) == 0 then break end
                    if H.throw() then
                        throws = throws + 1
                        for _ = 1, 80 do
                            press("B", 3, 12)
                            if u8(H.IN_BATTLE) == 0 then break end
                            if u8(H.MAX_MENU) == 1 then break end
                        end
                    else
                        for _ = 1, 6 do press("B", 4, 12) end
                    end
                end
            end

            -- Back to the overworld before reading the party: mid-catch the count is already
            -- incremented while the struct is still all zeroes.
            for _ = 1, 120 do
                press("B", 3, 12)
                if u8(H.IN_BATTLE) == 0 then break end
            end
            ctx.frames(120)

            if mode == "kill" then
                if u8(H.IN_BATTLE) ~= 0 then
                    return nil, "could not end the battle in 20 turns"
                end
                if ctx.party_count() ~= party0 then
                    return nil, "party grew during a kill hunt — we caught something"
                end
                if u8(H.BAG_QTY0) ~= balls0 then
                    return nil, fmt("a ball left the bag during a kill hunt (%d -> %d)",
                                    balls0, u8(H.BAG_QTY0))
                end
                return true
            end

            if ctx.party_count() > party0 then
                local mon = M.readPartySlot(ctx.party_count() - 1)
                if not (mon and mon.key and #mon.key == 12 and mon.species_index ~= 0) then
                    return nil, "caught mon is malformed"
                end
                if u8(H.BAG_QTY0) >= balls0 then
                    return nil, fmt("party grew but no ball was consumed (%d -> %d) — not a "
                                    .. "real catch", balls0, u8(H.BAG_QTY0))
                end
                return mon
            end
            -- D1: IN "catch" MODE A LOST ENCOUNTER IS FATAL, NOT A RETRY.
            -- gen1_rby_client.lua fires `no_catch` on any wild battle that ends without a
            -- capture, and latches resolved_areas[area] for the client's lifetime. So
            -- retrying after a miss DEAD-ZONES the area — and a later capture there is then
            -- refused by the dead-zone rule, not by whatever rule the caller was testing.
            -- The species-clause scenario in particular would "fail" for entirely the wrong
            -- reason. Fail here instead, where the cause is still legible.
            -- A lost encounter fires no_catch, which dead-zones the area — so by default
            -- that is FATAL in catch mode: the next capture there would be refused by the
            -- dead-zone rule rather than by the rule under test, and the failure would point
            -- at the wrong thing.
            --
            -- H.retry_on_loss opts out, for callers where the area is ALREADY dead and a
            -- second no_catch changes nothing. The dead-zone scenario's B side is exactly
            -- that: it is deliberately catching inside a locked area, so losing a ball on
            -- the way costs nothing but a retry.
            if mode == "catch" and not H.retry_on_loss then
                return nil, fmt("hunt %d lost the encounter (balls %d) — in catch mode that "
                                .. "fires no_catch and dead-zones the area, which would "
                                .. "invalidate the rule under test", hunt, u8(H.BAG_QTY0))
            end
            ctx.log(fmt("hunt %d: it got away (balls=%d) — back to the grass", hunt, u8(H.BAG_QTY0)))
        end
        return nil, "hunt budget exhausted"
    end

    --- Wait for the server to RETIRE a capture: force_faint zeroes its HP immediately, and
    --- the deferred memorialize then buries it. Either signal is the rule landing.
    ---
    --- "left the party" on its own is NOT a rejection: an accepted-but-unlinked capture is
    --- quarantined to the ordinary box (state.py `quarantine: ... -> box (pending link)`),
    --- which also empties the slot. Watching for that alone would call every catch rejected.
    function H.wait_retired(key, max_frames)
        local mem_before = (M.getMemorialBoxCount and M.getMemorialBoxCount()) or 0
        return ctx.wait_until(function()
            local slot = ctx.find_slot_by_key(key)
            if slot and ctx.read_hp(slot) == 0 then return "force_faint" end
            local mem = (M.getMemorialBoxCount and M.getMemorialBoxCount()) or 0
            if mem > mem_before then return "memorialized" end
            return nil
        end, max_frames or 5400, "the server to retire " .. key)
    end

    return H
end
