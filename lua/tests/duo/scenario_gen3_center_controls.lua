-- scenario_gen3_center_controls.lua — center_controls_gen3: G4 item 2a (4)'s negative controls on
-- the Viridian Center 2F (docs/gen3/G4_request_draft.md; the nurse control rides whiteout_gen3).
--
-- Geometry from pret/ROM (tools/gba_map.py on 5.4/5.5, both titles identical): the 1F escalator
-- (1,6) is MB_UP_ESCALATOR 0x6A -- stepping onto it warps (field_control_avatar.c
-- TryStartWarpEventScript -> DoEscalatorWarp) and EscalatorWarpInEffect_7 walks the player EAST
-- off the 2F escalator, so the 2F arrival is (2,6). ViridianCity_PokemonCenter_2F/map.json: the
-- Union Room attendant (6,2), the Direct Corner (cable) attendant (10,2), each across an
-- MB_COUNTER 0x80 tile at y=3, talked to from (x,4) facing north.
--
-- A (the runner queues each probe once A logs CONTROL_LIVE <name>; ctx.hold_probe checks it):
--   cable_menu            Direct Corner attendant, no wireless adapter -> the Cable Club service
--                         multichoice (cable_club.inc CableClub_EventScript_WelcomeToCableClub);
--                         probe box_mon <linked>, held while the script waits.
--   cable_link            TRADE CENTER -> the party check -> EventScript_AskSaveGame (YES: this
--                         run's one in-game save, the witness) -> TryTradeLinkup: with no cable
--                         partner Task_LinkupAwaitConnection spins until B (cable_club.c:216-237).
--                         The same probe must still be held there. B cancels; the probe then
--                         lands on the 2F (CONTROL_RELEASED, BOXED_OBSERVED).
--   union_room_attendant  IsWirelessAdapterConnected is FALSE under BizHawk (no RFU adapter), so
--                         the script prints CableClub_Text_UnionRoomAdapterNotConnected and
--                         waits; probe party_mon <linked> (the runner re-sends A's stats_cache
--                         stats) held, then lands after A dismisses it (RETURNED_OBSERVED).
-- NOT DRIVABLE: Union Room entry/return -- CableClub_EventScript_UnionRoomAttendant branches to
-- the adapter-not-connected message BEFORE CableClub_EventScript_AskEnterUnionRoom, and the
-- MAP_UNION_ROOM warp is only reached from EnterUnionRoom, so no scripted input reaches it
-- without wireless hardware. B idles (no save).
local fmt = string.format

local DEST_2F = { group = 5, num = 5, x = 2, y = 6 }

local function a_side(ctx, linked)
    local SP, cp, G, play = ctx.SP, ctx.cp, ctx.G, ctx.play
    local function script_live() return not G.pred_ok(cp, "script_context_status") end
    local function settle_field(label)
        -- dismiss the attendant's closing text until the script has ended and the field holds
        if not ctx.mash_until(function() return not script_live() and ctx.on_field() end, 60, "A") then
            return false, label .. ": the script never ended"
        end
        ctx.frames(60)
        return true
    end

    ctx.walk_to_pc("center_controls a")
    play.follow(cp, "center_pc_to_escalator", "center_controls a")
    SP.warp_to(cp, "Left", 30, DEST_2F, "center_controls a escalator")
    play.follow(cp, "center2f_to_direct_corner", "center_controls a")
    G.tap("Up", 3, 20)                                   -- face the counter (10,3): no step
    G.tap("A", 3, 13)
    if not ctx.wait_until(script_live, 10, "the Direct Corner attendant's script") then
        return false, "cable_menu: the attendant's script never started"
    end
    ctx.frames(240)                                      -- message + delay 15 + the multichoice
    local clause, why = ctx.hold_probe("cable_menu", "box_mon", linked, script_live, 600)
    if not clause then return false, why end
    -- TRADE CENTER (row 0), then YES through the save prompts, until the linkup task waits
    G.tap("A", 3, 13)
    local function linking() return ctx.task_live("Task_LinkupAwaitConnection") end
    if not ctx.mash_until(linking, 90, "A") then
        return false, "cable_link: Task_LinkupAwaitConnection never started (save or party check refused?)"
    end
    ctx.frames(60)
    clause, why = ctx.hold_probe("cable_link", "box_mon", linked, linking, 600, true)
    if not clause then return false, why end
    G.tap("B", 3, 13)                                    -- CheckLinkCanceledBeforeConnection
    local ok, swhy = settle_field("cable_link")
    if not ok then return false, swhy end
    if not ctx.wait_sent("stats_cache", linked, 60) then
        local held = ctx.queued("box_mon", linked)
        return false, "cable_link: the probe never landed once released (" .. tostring(held and held.why) .. ")"
    end
    if not ctx.observe_boxed(linked) then return false, "cable_link: " .. linked .. " never read back boxed" end
    ctx.log(fmt("CONTROL_RELEASED cable_link box_mon %s", linked))

    play.follow(cp, "center2f_direct_corner_to_union_room", "center_controls a")
    G.tap("Up", 3, 20)
    G.tap("A", 3, 13)
    if not ctx.wait_until(script_live, 10, "the Union Room attendant's script") then
        return false, "union_room_attendant: the script never started"
    end
    ctx.frames(120)
    clause, why = ctx.hold_probe("union_room_attendant", "party_mon", linked, script_live, 600)
    if not clause then return false, why end
    ok, swhy = settle_field("union_room_attendant")
    if not ok then return false, swhy end
    if not ctx.wait_sent("sync_retrieve_done", linked, 60) then
        local held = ctx.queued("party_mon", linked)
        return false, "union_room_attendant: the probe never landed once released ("
                   .. tostring(held and held.why) .. ")"
    end
    if not ctx.observe_returned(linked) then return false, linked .. " never read back in the party" end
    ctx.log(fmt("CONTROL_RELEASED union_room_attendant party_mon %s", linked))
    return true, "the cable menu, the cable link wait and the Union Room attendant each held a "
                 .. "keyed probe; each landed once released"
end

return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local linked = ctx.linked()
    local mon = linked and ctx.find(linked)
    if not mon or mon.slot ~= 1 then return false, "the LINKED key must be party slot 1" end
    if ctx.player == "b" then
        if not ctx.wait_until(ctx.partner_done, 2300, "A's result") then return false, "A never finished" end
        return true, "idle (center_controls drives only A)"
    end
    return a_side(ctx, linked)
end
