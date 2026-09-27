-- scenario_gen3_npc_trade.lua — npc_trade_gen3: S-9 `trade_done` on FR/LG (card NAT-LEGS).
--
-- SYNTH setup, disclosed (O-33): A boots firered_party_trade_synth.sav -- party[1] is a Lv10 ABRA
-- of the player's own OT, and CONTINUE warps into Route2_House (15.1) at (7,3), one tile below
-- Reyley (7,2), who trades MR. MIME for ABRA (pret pokefirered data/maps/Route2_House/scripts.inc,
-- src/data/ingame_trades.h INGAME_TRADE_MR_MIME). The runner links A's ABRA with B's slot 1.
-- NATIVE, ordinary buttons only: face Up, A to talk, A through the offer and YES, the party menu
-- (ChoosePartyMon, PARTY_MENU_TYPE_CHOOSE_SINGLE_MON: A picks) -> ABRA, A through the trade scene
-- (STATE_END_LINK_TRADE waits for A) and "Hey, thanks!" until the script sets
-- FLAG_DID_MIMIEN_TRADE. The client must emit key_change reason npc_trade (TradeMons: trade_begin
-- then trade_done). Whatever the server replies is recorded, not required. B idles.
local MR_MIME, ABRA = 122, 63
local FLAG_DID_MIMIEN_TRADE, SB1_FLAGS = 0x248, 0x0EE0    -- flags.h:609, global.h:790

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

local function traded_flag(ctx)
    local sb1 = memory.read_u32_le(ctx.cp.pointers.gSaveBlock1Ptr.address, "System Bus")
    if sb1 < 0x02000000 or sb1 >= 0x02040000 then return false end
    local byte = memory.read_u8(sb1 + SB1_FLAGS + FLAG_DID_MIMIEN_TRADE // 8, "System Bus")
    return (byte >> (FLAG_DID_MIMIEN_TRADE % 8)) & 1 == 1
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
    local m = ctx.find(linked)
    if not (m and m.species == ABRA and m.slot == 1) then
        return false, "the linked key " .. linked .. " is not the fixture's slot-1 ABRA"
    end
    ctx.log("WHERE " .. ctx.play.where(ctx.cp))
    if traded_flag(ctx) then return false, "FLAG_DID_MIMIEN_TRADE is already set" end
    tap_signals(ctx, { trade_begin = true, trade_done = true, trade_evolve_species_store = true })
    ctx.log("READY " .. linked)
    if not ctx.face("Up") then return false, "could not face Reyley" end
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
    if memory.read_u8(S.gPartyMenu + 9) ~= 1 then return false, "party cursor never reached ABRA (slot 1)" end
    local ok, why = ctx.press_confirmed("A", 20)
    if not ok then return false, "party A: " .. why end
    ctx.log("PICKED slot=1 " .. linked)
    local done = ctx.mash_until(function() return ctx.sent("key_change") > 0 and traded_flag(ctx) end, 240, "A")
    if not done then
        return false, ctx.fmt("no npc_trade key_change + FLAG_DID_MIMIEN_TRADE (key_change sent %d, flag %s)",
                              ctx.sent("key_change"), tostring(traded_flag(ctx)))
    end
    local kc = ctx.last_sent("key_change")
    ctx.log(ctx.fmt("NPC_TRADE old=%s new=%s reason=%s species=%s", tostring(kc.old_key), tostring(kc.new_key),
                    tostring(kc.reason), tostring(kc.new_species)))
    if kc.old_key ~= linked or kc.reason ~= "npc_trade" or kc.new_species ~= MR_MIME then
        return false, "the key_change is not ABRA -> MR. MIME by npc_trade"
    end
    if not ctx.wait_until(function() return ctx.on_field() and ctx.player_idle() end, 60, "the field after the trade") then
        return false, "the field never settled after the trade"
    end
    ctx.frames(240)                                            -- the server's reply (recorded, not required)
    ok, why = ctx.save("npc_trade")
    if not ok then return false, why end
    return true, "traded " .. linked .. " -> " .. kc.new_key
end
