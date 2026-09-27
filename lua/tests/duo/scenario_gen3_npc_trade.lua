-- scenario_gen3_npc_trade.lua — npc_trade_gen3: S-9 `trade_done` on FR/LG and Emerald (card
-- NAT-LEGS, NAT-LEGS-3).
--
-- FR/LG SYNTH setup, disclosed (O-33): A boots firered_party_trade_synth.sav -- party[1] is a
-- Lv10 ABRA of the player's own OT, and CONTINUE warps into Route2_House (15.1) at (7,3), one
-- tile below Reyley (7,2), who trades MR. MIME for ABRA (pret pokefirered
-- data/maps/Route2_House/scripts.inc, src/data/ingame_trades.h INGAME_TRADE_MR_MIME).
-- Emerald SYNTH setup (card NAT-LEGS-3): A boots emerald_trade.sav -- party[1] is a Lv7 RALTS of
-- the player's own OT, and CONTINUE warps into RustboroCity_House1 (11.10) at (6,5), one tile
-- below the trader (6,4), who trades SEEDOT for RALTS (pret pokeemerald c65e93f2
-- data/maps/RustboroCity_House1/scripts.inc, src/data/trade.h INGAME_TRADE_SEEDOT). Both traders
-- face down at their NPC tile, so the leg is the same on both games: face Up, A to talk, A
-- through the offer and YES, the party menu (ChoosePartyMon, PARTY_MENU_TYPE_CHOOSE_SINGLE_MON:
-- A picks) -> the player's mon, A through the trade scene (STATE_END_LINK_TRADE waits for A) and
-- the closing text until the script sets its own "trade completed" flag. The runner links A's
-- traded-away mon with B's slot 1. The client must emit key_change reason npc_trade (TradeMons:
-- trade_begin then trade_done). Whatever the server replies is recorded, not required. B idles.
--
-- card RR-NPCTRADE-2: Route2_House/Reyley (MR_MIME, INGAME_TRADE index 0) is DEAD on the real RR
-- ROM -- GetInGameTradeSpeciesInfo is CFRU-detoured (0x08053a9c -> 0x090A4A2D) to read a SEPARATE
-- runtime table (ROM 0x09147C74, stride 0x2C) instead of the static sInGameTrades table, and that
-- table's index 0 decodes to species=1375 (an unassigned RR species id) / requestedSpecies=162
-- (Furret), not Mr Mime-Galar/Abra -- so the live species check (`goto_if_ne VAR_RESULT,
-- VAR_0x8009`, Route2_House_EventScript_Reyley) always fails and the trade can never complete
-- (docs/gen3/research/rr_ingame_trades.md "RR-NPCTRADE-2"). Index 1 (JYNX/"Dontae",
-- CeruleanCity_House3, group.num 7.2) decodes cleanly (species=508 Carnivine, requested=1164
-- Snom) and RR's own compiled Dontae script confirms flag 0x024A -- radical_red now targets that
-- trade instead. Dontae faces UP (vanilla movementType FACE_UP), the OPPOSITE of Reyley/the
-- Emerald trader (both face DOWN), so the player's stand tile (2,1) needs to face DOWN toward
-- him, not Up.
local NPC_TRADE = {
    -- species: {mine (traded away), theirs (received)}; flag: the save's own "trade completed"
    -- bit, at SaveBlock1 offset sb1_flags (FRLG global.h:790 flags[], Emerald pokeemerald
    -- include/global.h "flags" -- gen3_fixtures.py EMERALD_KINDS/build_emerald_seed uses the same
    -- 0x1270 base to set story flags); face: the direction the player must face to interact
    -- (default "Up" -- only radical_red's trader faces the other way, see the card note above).
    firered   = {mine = 63,  theirs = 122, flag = 0x248, sb1_flags = 0x0EE0},   -- ABRA -> MR. MIME
    leafgreen = {mine = 63,  theirs = 122, flag = 0x248, sb1_flags = 0x0EE0},
    emerald   = {mine = 392, theirs = 298, flag = 0x99,  sb1_flags = 0x1270},   -- RALTS -> SEEDOT
    -- (Emerald FLAG_RUSTBORO_NPC_TRADE_COMPLETED, pret include/constants/flags.h:175)
    -- card RR-NPCTRADE-2: RR's JYNX/"Dontae" trade at CeruleanCity_House3 (docs/gen3/research/
    -- rr_ingame_trades.md "RR-NPCTRADE-2") -- flag 0x24A read directly from RR's compiled Dontae
    -- script (checkflag 0x024A), same SaveBlock1 flags-array offset as vanilla. species decoded
    -- from the runtime CFRU trade-info table (ROM 0x09147C74 idx1), not the static sInGameTrades
    -- table: Snom (1164) requested, Carnivine (508) offered.
    radical_red = {mine = 1164, theirs = 508, flag = 0x24A, sb1_flags = 0x0EE0, face = "Down"},
}

local function tap_signals(ctx, kinds)
    local sigs = assert(ctx.session.signals, "the client armed no signal source")
    local drain = sigs.drain
    sigs.drain = function(self)
        local out = drain(self)
        for _, s in ipairs(out) do
            if kinds[s.kind] then ctx.log(ctx.fmt("SIGNAL %s frame=%d address=0x%08X", s.kind, s.frame, s.address)) end
        end
        return out
    end
end

local function traded_flag(ctx, fx)
    local sb1 = memory.read_u32_le(ctx.cp.pointers.gSaveBlock1Ptr.address, "System Bus")
    if sb1 < 0x02000000 or sb1 >= 0x02040000 then return false end
    local byte = memory.read_u8(sb1 + fx.sb1_flags + fx.flag // 8, "System Bus")
    return (byte >> (fx.flag % 8)) & 1 == 1
end

return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local linked = ctx.linked()
    if not linked then return false, "the go-file names no LINKED key" end
    if ctx.player == "b" then
        ctx.log("READY " .. linked)
        if not ctx.wait_until(ctx.partner_done, 1500, "A's RESULT") then return false, "A never finished" end
        return true, "idled while A traded"
    end
    local fx = assert(NPC_TRADE[ctx.title], "npc_trade_gen3: no NPC_TRADE facts for title " .. tostring(ctx.title))
    local m = ctx.find(linked)
    if not (m and m.species == fx.mine and m.slot == 1) then
        return false, "the linked key " .. linked .. " is not the fixture's slot-1 mon"
    end
    ctx.log("WHERE " .. ctx.play.where(ctx.cp))
    if traded_flag(ctx, fx) then return false, "the trade's completion flag is already set" end
    tap_signals(ctx, { trade_begin = true, trade_done = true, trade_evolve_species_store = true })
    ctx.log("READY " .. linked)
    if not ctx.face(fx.face or "Up") then return false, "could not face the trader" end
    -- talk, read the offer, YES (the default): A on a 16-frame cadence until the party menu is up
    if not ctx.mash_until(function() return ctx.party_menu_up() and ctx.task_live("Task_HandleChooseMonInput") end,
                          60, "A") then
        return false, "the trade offer never opened the party menu"
    end
    local S, G = ctx.sym, ctx.G
    for _ = 1, 8 do
        local at = memory.read_u8(S.gPartyMenu + 9)            -- gPartyMenu.slotId
        if at == 1 then break end
        G.tap(at < 1 and "Down" or "Up", 3, 20)
    end
    if memory.read_u8(S.gPartyMenu + 9) ~= 1 then return false, "party cursor never reached the traded mon (slot 1)" end
    local ok, why = ctx.press_confirmed("A", 20)
    if not ok then return false, "party A: " .. why end
    ctx.log("PICKED slot=1 " .. linked)
    local done = ctx.mash_until(function() return ctx.sent("key_change") > 0 and traded_flag(ctx, fx) end, 240, "A")
    if not done then
        return false, ctx.fmt("no npc_trade key_change + completion flag (key_change sent %d, flag %s)",
                              ctx.sent("key_change"), tostring(traded_flag(ctx, fx)))
    end
    local kc = ctx.last_sent("key_change")
    ctx.log(ctx.fmt("NPC_TRADE old=%s new=%s reason=%s species=%s", tostring(kc.old_key), tostring(kc.new_key),
                    tostring(kc.reason), tostring(kc.new_species)))
    if kc.old_key ~= linked or kc.reason ~= "npc_trade" or kc.new_species ~= fx.theirs then
        return false, "the key_change is not the fixture's npc_trade"
    end
    if not ctx.wait_until(function() return ctx.on_field() and ctx.player_idle() end, 60, "the field after the trade") then
        return false, "the field never settled after the trade"
    end
    ctx.frames(240)                                            -- the server's reply (recorded, not required)
    ok, why = ctx.save("npc_trade")
    if not ok then return false, why end
    return true, "traded " .. linked .. " -> " .. kc.new_key
end
