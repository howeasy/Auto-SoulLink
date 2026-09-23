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
-- A (the runner queues each probe once A logs CONTROL_LIVE <name>; ctx.hold_probe checks it, and
-- each control's live() carries its source-pinned WITNESS on every sampled frame):
--   cable_menu            the global script context parked in CableClub_EventScript_
--                         SelectCableClubRoom with Task_MultichoiceMenu_HandleInput up -- the
--                         Cable Club service menu, which the Direct Corner attendant only
--                         reaches when IsWirelessAdapterConnected returned FALSE (the adapter
--                         branch goes to CableClub_EventScript_DirectCornerSelectService
--                         instead): the script position IS the observation of that result.
--                         Probe box_mon <linked>, held.
--   cable_link            TRADE CENTER -> the party check -> EventScript_AskSaveGame (YES: this
--                         run's one in-game save, the witness; it lands BEFORE any probe moves a
--                         byte, so it is no persistence proof of the later deposit/withdraw) ->
--                         TryTradeLinkup: with no cable partner Task_LinkupAwaitConnection spins
--                         until B (cable_club.c:216-237). The same probe must still be held.
--   union_room_attendant  a caller return address inside CableClub_EventScript_
--                         UnionRoomAdapterNotConnected on the script stack (its msgbox waits in
--                         the std script): IsWirelessAdapterConnected returned FALSE, observed.
--                         Probe party_mon <linked> (the runner re-sends A's stats_cache stats).
-- Each release logs CONTROL_RELEASED BEFORE its cancel/dismiss input; the probe's ACK and the
-- cartridge read-back follow, then CONTROL_SETTLED.
-- NOT REACHED: Union Room entry/return -- unreachable while IsWirelessAdapterConnected returns
-- FALSE (observed above): CableClub_EventScript_UnionRoomAttendant branches to the
-- adapter-not-connected message BEFORE CableClub_EventScript_AskEnterUnionRoom, and the
-- MAP_UNION_ROOM warp is only reached from EnterUnionRoom. B idles (no save).
local fmt = string.format

local DEST_2F = { group = 5, num = 5, x = 2, y = 6 }
-- pret include/constants/vars.h:176; PalletTown_ProfessorOaksLab/scripts.inc:658 sets it to 1
-- with the Pokedex. At 1, the 2F's ON_FRAME table (cable_club.inc CableClub_OnFrame) runs
-- CableClub_EventScript_Tutorial on arrival: lockall, TEALA's msgbox, Movement_PlayerApproach-
-- Counter (walk_up x2: (2,6) -> (2,4)), a second msgbox, then the var -> 2. Live FR r6 stalled
-- stepping Up into that lockall ("First, I need to show you this ...").
local VAR_MAP_SCENE_POKEMON_CENTER_TEALA = 0x407C
local TUTORIAL_END = { x = 2, y = 4 }

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
    local function at_service_menu()
        return ctx.script_at("CableClub_EventScript_SelectCableClubRoom", "CableClub_EventScript_Colosseum"),
               ctx.task_live("Task_MultichoiceMenu_HandleInput")
    end
    local function at_adapter_message()
        return ctx.script_at("CableClub_EventScript_UnionRoomAdapterNotConnected",
                             "CableClub_EventScript_WirelessClubAttendant")
    end

    ctx.walk_to_pc("center_controls a")
    play.follow(cp, "center_pc_to_escalator", "center_controls a")
    local teala = ctx.game_var(VAR_MAP_SCENE_POKEMON_CENTER_TEALA)
    SP.warp_to(cp, "Left", 30, DEST_2F, "center_controls a escalator")
    if teala == 1 then
        if not ctx.wait_until(script_live, 10, "CableClub_EventScript_Tutorial") then
            return false, "the 2F tutorial (VAR_MAP_SCENE_POKEMON_CENTER_TEALA=1) never started"
        end
        if not ctx.mash_until(function() return not script_live() and ctx.on_field() end, 120, "A") then
            return false, "the 2F tutorial never ended"
        end
        ctx.frames(30)
        local x, y = G.pos(cp)
        local after = ctx.game_var(VAR_MAP_SCENE_POKEMON_CENTER_TEALA)
        ctx.log(fmt("TEALA_TUTORIAL var=1->%s at=(%d,%d)", tostring(after), x, y))
        if after ~= 2 or x ~= TUTORIAL_END.x or y ~= TUTORIAL_END.y then
            return false, fmt("the 2F tutorial did not end at (%d,%d) with the var at 2", TUTORIAL_END.x, TUTORIAL_END.y)
        end
        play.follow(cp, "center2f_counter_to_direct_corner", "center_controls a")
    else
        ctx.log(fmt("TEALA_TUTORIAL var=%s skipped", tostring(teala)))
        play.follow(cp, "center2f_to_direct_corner", "center_controls a")
    end
    G.tap("Up", 3, 20)                                   -- face the counter (10,3): no step
    G.tap("A", 3, 13)
    if not ctx.wait_until(script_live, 10, "the Direct Corner attendant's script") then
        return false, "cable_menu: the attendant's script never started"
    end
    ctx.frames(240)                                      -- message + delay 15 + the multichoice
    local at, menu = at_service_menu()
    ctx.log(fmt("WITNESS cable_menu script=CableClub_EventScript_SelectCableClubRoom at=%s "
                .. "multichoice=%s adapter_connected=%s", tostring(at), tostring(menu),
                at and "false(observed: the no-adapter branch)" or "unobserved"))
    if not (at and menu) then
        return false, "cable_menu: not parked at the Cable Club service multichoice (the no-adapter branch)"
    end
    local clause, why = ctx.hold_probe("cable_menu", "box_mon", linked, function()
        local a, m = at_service_menu()
        return script_live() and a ~= nil and m
    end, 600)
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
    ctx.log(fmt("CONTROL_RELEASED cable_link box_mon %s", linked))
    G.tap("B", 3, 13)                                    -- CheckLinkCanceledBeforeConnection
    local ok, swhy = settle_field("cable_link")
    if not ok then return false, swhy end
    if not ctx.wait_sent("stats_cache", linked, 60) then
        local held = ctx.queued("box_mon", linked)
        return false, "cable_link: the probe never landed once released (" .. tostring(held and held.why) .. ")"
    end
    if not ctx.observe_boxed(linked) then return false, "cable_link: " .. linked .. " never read back boxed" end
    ctx.log(fmt("CONTROL_SETTLED cable_link box_mon %s", linked))

    play.follow(cp, "center2f_direct_corner_to_union_room", "center_controls a")
    G.tap("Up", 3, 20)
    G.tap("A", 3, 13)
    if not ctx.wait_until(script_live, 10, "the Union Room attendant's script") then
        return false, "union_room_attendant: the script never started"
    end
    ctx.frames(120)
    at = at_adapter_message()
    ctx.log(fmt("WITNESS union_room_attendant script=CableClub_EventScript_UnionRoomAdapterNotConnected "
                .. "at=%s adapter_connected=%s", tostring(at),
                at and "false(observed: the adapter-not-connected branch)" or "unobserved"))
    if not at then
        return false, "union_room_attendant: not in CableClub_EventScript_UnionRoomAdapterNotConnected"
    end
    clause, why = ctx.hold_probe("union_room_attendant", "party_mon", linked, function()
        return script_live() and at_adapter_message() ~= nil
    end, 600)
    if not clause then return false, why end
    ctx.log(fmt("CONTROL_RELEASED union_room_attendant party_mon %s", linked))
    ok, swhy = settle_field("union_room_attendant")
    if not ok then return false, swhy end
    if not ctx.wait_sent("sync_retrieve_done", linked, 60) then
        local held = ctx.queued("party_mon", linked)
        return false, "union_room_attendant: the probe never landed once released ("
                   .. tostring(held and held.why) .. ")"
    end
    if not ctx.observe_returned(linked) then return false, linked .. " never read back in the party" end
    ctx.log(fmt("CONTROL_SETTLED union_room_attendant party_mon %s", linked))
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
