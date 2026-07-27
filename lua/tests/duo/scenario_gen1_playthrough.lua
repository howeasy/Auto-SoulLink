-- scenario_gen1_playthrough.lua — actually PLAY the game, on two cartridges, into a real link.
--
-- This is the scenario the audit said did not exist. Every other Gen 1 duo scenario injects
-- the state it verifies: pairs arrive via POST /api/inject_link, battles are staged by poking
-- wIsInBattle, and the Nuzlocke gate is force-set over HTTP. None of them has ever caught a
-- Pokémon, and none proves encounter linking — the rule SLink is actually for.
--
-- Here nothing is injected. Both instances start on Route 1, walk into the grass, meet a real
-- wild Pokémon, open the bag and throw a real Poké Ball. The production client sees the new
-- party member on its own and emits `capture`; the server pairs the two catches by area. The
-- runner then asserts the link exists in server state, which neither instance can fabricate.
--
-- Everything below is measured, not derived — see lua/tests/probe_gen1_encounter.lua and the
-- screenshots it leaves in patch/build/. In particular the battle menu is TWO columns:
--     >FIGHT   PKMN
--      ITEM    RUN
-- so ITEM is DOWN from FIGHT in the SAME column (pokered swaps the item/party ids in the
-- English builds, engine/battle/core.asm:2141). Reading wCurrentMenuItem alone is misleading:
-- it is 0/1 within whichever column is active.
return function(ctx)
    local log = ctx.log
    local M   = ctx.M
    local fmt = string.format
    if not ctx.wait_go() then return false, "no go-file" end

    -- EVERY address comes from the loaded profile, never a literal. Yellow shifts nearly all
    -- of WRAM by -1, and the first version of this file hardcoded Red's addresses: on Yellow
    -- it read the ball count as 255 and the map as the wrong byte. That is precisely the bug
    -- class the Yellow pairing exists to catch, and it caught it here first.
    -- The two menu addresses are the exception and are genuinely NOT shifted (pret: both
    -- games put wCurrentMenuItem at 0xCC26 and wMaxMenuItem at 0xCC28).
    local IN_BATTLE = M.BATTLE_FLAG_ADDR
    local CUR_MAP   = M.MAP_ID_ADDR
    local ENEMY_SP  = M.ENEMY_MON_SPECIES_ADDR
    local ENEMY_LV  = M.ENEMY_MON_LEVEL_ADDR
    local BAG_QTY0  = M.BAG_ITEMS_ADDR + 1      -- wBagItems[0].quantity
    local MAX_MENU  = 0xCC28
    local CUR_MENU  = 0xCC26
    local function u8(a) return M.read_u8(a) end

    -- Report the map; do NOT require a specific one. The three battery fixtures were built
    -- independently and do not all sit on the same route (Red/Blue are on Route 1 = 0x0C,
    -- Yellow came out on Route 3 = 0x0E). Which route does not matter to this scenario —
    -- what matters is that it has wild encounters and that BOTH instances are in the same
    -- area, since Soul Link pairs the first catch per area. The runner checks the pairing.
    local start_map = u8(CUR_MAP)
    -- wYCoord / wXCoord sit immediately after wCurMap in both profiles (pret: wCurMap,
    -- wYCoord, wXCoord), so they ride the same -1 Yellow shift as MAP_ID_ADDR.
    local Y_COORD, X_COORD = CUR_MAP + 3, CUR_MAP + 4
    local home_x, home_y = u8(X_COORD), u8(Y_COORD)
    log(fmt("MAP 0x%02X pos=(%d,%d) party=%d balls=%d",
            start_map, home_x, home_y, ctx.party_count(), u8(BAG_QTY0)))

    -- Wild encounters need the map to have them at all, and the player to be standing on a
    -- grass tile. Both are things the GAME knows, so ask it instead of inferring from
    -- coordinates (see M.isInGrass / M.hasWildEncounters, which mirror TryDoWildEncounter).
    if M.hasWildEncounters() == false then
        return false, fmt("map 0x%02X has no wild encounters (wGrassRate == 0)", start_map)
    end

    -- Stock the bag. The most inert thing this scenario hands itself: Poké Balls are an item
    -- the game sells, and topping them up changes nothing about the encounter, the capture,
    -- or the link. (This line was silently lost in an edit once and the run quietly went back
    -- to 5 balls, which looks exactly like bad luck rather than a bug — hence the log below.)
    M.write_u8(BAG_QTY0, 40)
    local party_before = ctx.party_count()
    local balls_before = u8(BAG_QTY0)
    -- Snapshot the wild-encounter table NOW, before any battle. It shares memory with the
    -- enemy party (wram.asm:2145-2172 is a UNION), so the first wild battle overwrites it and
    -- the game only rebuilds it on map entry — after which the player can walk in grass
    -- forever with nothing happening. Earlier versions of this scenario appeared to work only
    -- because their buggy pacing drifted across the map boundary and back, reloading it by
    -- accident. Restoring the snapshot is exactly what map entry does.
    local wild_data = M.snapshotWildData()
    log(fmt("stocked: balls=%d wGrassRate=%s wildData=%s",
            balls_before, tostring(M.hasWildEncounters()),
            wild_data and (#wild_data .. " bytes") or "nil"))
    -- Snapshot the starting keys. The property that matters is that a NEW mon entered the
    -- party — that is exactly what the client turns into a `capture` event. Comparing against
    -- the species we last met is weaker AND wrong across hunts: a mon that got away leaves
    -- met_species pointing at the wrong encounter.

    -- At 400x speed a blind press sequence loses menu edges, so nothing here is fired and
    -- hoped for: every step is verified against an observable, and the whole sequence retries.
    -- The observable for "the ball was thrown" is the BAG COUNT going down, which cannot be
    -- faked by a mis-pressed menu.
    local function press(btn, hold_frames, settle)
        ctx.hold(btn, hold_frames or 10)
        ctx.frames(settle or 18)
    end

    local function wait_for_menu()
        -- Each column is its own 2-item menu, so wMaxMenuItem==1 means the battle menu is up.
        -- (It reads 3 earlier, left over from a previous menu — that misled the first probe.)
        --
        -- Advance with B, NOT A. B clears text without confirming a selection; A confirms
        -- whatever the cursor sits on, which at a fresh battle menu is FIGHT. That made the
        -- scenario attack the wild mon between throws — a level-5 Squirtle one-shots a
        -- level-3 Rattata, so the battle ended with "it got away" and the run burned 18 balls
        -- over 20 hunts without a single catch. A Nuzlocke player throwing balls never
        -- presses FIGHT.
        -- CHECK BEFORE PRESSING. The press has to advance text, but the moment the menu is
        -- up an A confirms whatever the cursor sits on — FIGHT — and a level-5 starter
        -- one-shots a level-3 wild mon, ending the battle with "it got away". Testing first
        -- means we never press at a live menu. (Using B instead does not work: B does not
        -- advance this text reliably, and the run then never reaches the menu at all.)
        for _ = 1, 80 do
            if u8(MAX_MENU) == 1 then return true end
            if u8(IN_BATTLE) == 0 then return false end
            press("A", 4, 12)
        end
        return false
    end

    -- Returns true once a ball has actually left the bag.
    local function try_throw()
        local before = u8(BAG_QTY0)
        press("Left"); press("Up"); press("Down")
        if u8(CUR_MENU) ~= 1 then return false end          -- not on ITEM; caller retries
        press("A", 10, 45)                                   -- open the bag
        press("A", 10, 45)                                   -- use slot 0 = POKé BALL
        for _ = 1, 60 do
            ctx.frames(10)
            if u8(BAG_QTY0) < before then return true end
            if u8(IN_BATTLE) == 0 then return true end
        end
        return false
    end

    -- ── Hunt until we actually catch something ──────────────────────────────
    -- A ball missing and the battle ending is ORDINARY game behaviour, not an error. The
    -- first version returned FAIL on a miss, which made the whole scenario a coin flip.
    -- A real Nuzlocke player walks back into the grass, so that is what this does.
    local met_species, mon
    for hunt = 1, 20 do
        if u8(BAG_QTY0) == 0 then return false, "out of Poké Balls after " .. hunt .. " hunts" end

        -- 1. Walk in the grass until something jumps us. Gen 1 needs a direction HELD.
        -- Pace EAST-WEST, never north-south. Route 1's ledges run horizontally and are
        -- one-way: pacing Up/Down eventually hops one southward and the player can never
        -- climb back to the grass, drifts to Pallet Town, and every later hunt reports "no
        -- wild encounter" — which is exactly what the area_enter:route_1 ->
        -- area_enter:pallet_town pair in the client log was telling us. Left/Right stays on
        -- one row, so it cannot cross a ledge, and grass tiles span the row either way.
        -- Pace, but let the GAME tell us when we have stepped off the grass and turn around
        -- immediately. Four blind heuristics failed here before this: Up/Down pacing hops
        -- Route 1's one-way ledges and strands the player in Pallet Town, and walking "back
        -- to the start tile" just grinds against the ledge it fell off. wTileMap[9,9] vs
        -- wGrassTile is the exact test TryDoWildEncounter runs, so it cannot disagree with
        -- the game about whether an encounter is even possible.
        -- ALTERNATE every step. Holding one direction just walks into the edge of the patch
        -- and stops: no step is taken, so no encounter is ever rolled, and the grass check
        -- keeps reading true because the player never moved. (That is exactly what the first
        -- version of this loop did — it only flipped direction on leaving the grass, which
        -- therefore never happened: "left the grass 0 times, in_grass=true".)
        local dirs = {"Left", "Right"}
        local entered, off_grass = false, 0
        local in_battle = function() return u8(IN_BATTLE) ~= 0 end
        for i = 1, 600 do
            ctx.hold(dirs[(i % 2) + 1], 12, in_battle)
            if in_battle() then entered = true break end
            if M.isInGrass() == false then
                -- Stepped off the patch: immediately step back the way we came, so we cannot
                -- wander far enough to fall down one of Route 1's one-way ledges.
                ctx.hold(dirs[((i + 1) % 2) + 1], 12, in_battle)
                if in_battle() then entered = true break end
                off_grass = off_grass + 1
            end
        end
        if not entered then
            return false, fmt("no wild encounter in 600 steps (left the grass %d times, "
                              .. "in_grass=%s, wGrassRate=%s)", off_grass,
                              tostring(M.isInGrass()), tostring(M.hasWildEncounters()))
        end
        met_species = u8(ENEMY_SP)
        log(fmt("hunt %d: wild species=0x%02X level=%d (balls=%d)",
                hunt, met_species, u8(ENEMY_LV), u8(BAG_QTY0)))
        if u8(IN_BATTLE) ~= 1 then
            return false, fmt("expected a WILD battle (wIsInBattle==1), got %d", u8(IN_BATTLE))
        end

        -- 2. Throw balls until it sticks, the battle ends, or we run out.
        local party_at_start = ctx.party_count()
        -- KEEP THROWING. Giving up after 5 balls ends the battle without a catch, which is
        -- a `no_catch` — and in Soul Link a failed FIRST encounter locks the area as a dead
        -- zone for BOTH players, so every later capture there is (correctly) refused and no
        -- pair can ever form. That is the rule working, not a bug, but it means a scenario
        -- that wants a link must actually land the catch. Gen 1's rate on a full-HP wild mon
        -- is roughly 1 in 5, so 30 throws out of a 40-ball bag makes a miss vanishingly
        -- unlikely, and we never voluntarily leave the battle.
        local throws, attempts = 0, 0
        while u8(IN_BATTLE) ~= 0 and throws < 30 and attempts < 60 do
            attempts = attempts + 1
            if not wait_for_menu() then break end
            if u8(BAG_QTY0) == 0 then break end
            if try_throw() then
                throws = throws + 1
                log(fmt("  threw ball %d — balls=%d party=%d in_battle=%d",
                        throws, u8(BAG_QTY0), ctx.party_count(), u8(IN_BATTLE)))
                for _ = 1, 80 do
                    press("B", 3, 12)
                    if u8(IN_BATTLE) == 0 then break end
                    if u8(MAX_MENU) == 1 then break end
                end
            else
                for _ = 1, 6 do press("B", 4, 12) end
            end
        end

        -- Make sure we are back in the overworld before reading the party: mid-catch the
        -- count is already incremented while the struct is still all zeroes.
        for _ = 1, 120 do
            press("B", 3, 12)
            if u8(IN_BATTLE) == 0 then break end
        end
        ctx.frames(120)

        if ctx.party_count() > party_at_start then
            mon = M.readPartySlot(ctx.party_count() - 1)
            break
        end
        M.restoreWildData(wild_data)     -- the battle just ate the wild table; put it back
        log(fmt("hunt %d: it got away (balls=%d) in_grass=%s wGrassRate=%s — back to the grass",
                hunt, u8(BAG_QTY0), tostring(M.isInGrass()), tostring(M.hasWildEncounters())))
    end

    if not mon then
        return false, fmt("caught nothing in 20 hunts (balls left %d)", u8(BAG_QTY0))
    end
    if u8(BAG_QTY0) >= balls_before then
        return false, fmt("party grew but no ball was consumed (%d -> %d) — not a real catch",
                          balls_before, u8(BAG_QTY0))
    end

    if not (mon and mon.key and #mon.key == 12 and mon.species_index ~= 0) then
        return false, fmt("caught mon is malformed (key=%s species=0x%02X)",
                          mon and mon.key or "nil", mon and mon.species_index or 0)
    end
    for s0 = 0, party_before - 1 do
        if ctx.slot_key(s0) == mon.key then
            return false, "the 'caught' mon has a key we already had — no new mon entered"
        end
    end

    -- The runner reads this line to pair the two catches and check server state.
    log(fmt("CAUGHT %s species=0x%02X level=%d on map 0x%02X",
            mon.key, mon.species_index, mon.level, start_map))
    log(fmt("balls %d -> %d, party %d -> %d",
            balls_before, u8(BAG_QTY0), party_before, ctx.party_count()))

    -- Give the client frames to notice the new party member and send `capture`, and to
    -- receive whatever the server sends back.
    ctx.frames(600)
    ctx.wait_partner_done(9000)
    return true, "caught " .. mon.key
end
