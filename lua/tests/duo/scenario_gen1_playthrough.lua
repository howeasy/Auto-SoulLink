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

    local IN_BATTLE = 0xD057
    local CUR_MAP   = 0xD35E
    local MAX_MENU  = 0xCC28
    local CUR_MENU  = 0xCC26
    local BAG_QTY0  = 0xD31F      -- wBagItems[0].quantity
    local function u8(a) return M.read_u8(a) end

    log(fmt("start: map=0x%02X party=%d balls=%d", u8(CUR_MAP), ctx.party_count(), u8(BAG_QTY0)))
    if u8(CUR_MAP) ~= 0x0C then
        return false, fmt("expected to start on Route 1 (0x0C), got 0x%02X", u8(CUR_MAP))
    end
    -- The Nuzlocke gate must come from the REAL bag, not a debug POST. If this is false the
    -- server will (correctly) ignore our capture, so assert it before spending frames.
    if not M.hasPokeballs() then
        return false, "hasPokeballs() is false — the real bag read is what gates the rules"
    end

    -- Stock the bag to 40 balls. This is the ONE thing the scenario hands itself, and it is
    -- deliberately the most inert one available: Poké Balls are an item the game sells, and
    -- topping them up changes nothing about the encounter, the throw, the capture event or
    -- the link. Gen 1's catch rate on a full-HP wild mon is low enough that 5 balls made this
    -- a coin flip — a real player weakens the mon first, which is a lot of menu driving for
    -- no extra coverage. The RULES all still have to happen for real.
    M.write_u8(BAG_QTY0, 40)
    local party_before = ctx.party_count()
    local balls_before = u8(BAG_QTY0)
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
        for _ = 1, 80 do
            press("A", 4, 12)
            if u8(MAX_MENU) == 1 then return true end
            if u8(IN_BATTLE) == 0 then return false end
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
        local entered = false
        for i = 1, 600 do
            ctx.hold(({"Up", "Down"})[(i % 2) + 1], 12, function() return u8(IN_BATTLE) ~= 0 end)
            if u8(IN_BATTLE) ~= 0 then entered = true break end
        end
        if not entered then return false, "no wild encounter after 600 held steps in the grass" end
        met_species = u8(0xCFE5)
        log(fmt("hunt %d: wild species=0x%02X level=%d (balls=%d)",
                hunt, met_species, u8(0xCFF3), u8(BAG_QTY0)))
        if u8(IN_BATTLE) ~= 1 then
            return false, fmt("expected a WILD battle (wIsInBattle==1), got %d", u8(IN_BATTLE))
        end

        -- 2. Throw balls until it sticks, the battle ends, or we run out.
        local party_at_start = ctx.party_count()
        local throws, attempts = 0, 0
        while u8(IN_BATTLE) ~= 0 and throws < 5 and attempts < 20 do
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
        log(fmt("hunt %d: it got away (balls=%d) — back into the grass", hunt, u8(BAG_QTY0)))
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
            mon.key, mon.species_index, mon.level, u8(CUR_MAP)))
    log(fmt("balls %d -> %d, party %d -> %d",
            balls_before, u8(BAG_QTY0), party_before, ctx.party_count()))

    -- Give the client frames to notice the new party member and send `capture`, and to
    -- receive whatever the server sends back.
    ctx.frames(600)
    ctx.wait_partner_done(9000)
    return true, "caught " .. mon.key
end
