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
--   cable_welcome_message  the global script context parked in CableClub_EventScript_
--                         WelcomeToCableClub -- the Direct Corner attendant's no-adapter branch
--                         -- waiting at the \p of CableClub_Text_WelcomeWhichCableClubService
--                         ("...CABLE CLUB.\p"): `waitmessage` holds the script there until A,
--                         so it is a STABLE refusing state (live r8: after 240 frames the script
--                         sat here, never at the multichoice the old witness demanded). VAR_RESULT
--                         read there is IsWirelessAdapterConnected's own return (0 = FALSE,
--                         observed). Probe box_mon <linked>, held. This proves refusal during
--                         the welcome MESSAGE wait, NOT during the service multichoice.
--   cable_save            TRADE CENTER -> the party check -> EventScript_AskSaveGame: the save
--                         prompt with task50_save_game alive (G4 draft row 3). The same probe,
--                         held BEFORE the save lands (this run's one in-game save, the witness;
--                         it lands before any probe moves a byte, so it is no persistence proof of
--                         the later deposit/withdraw).
--   cable_link            YES through the save -> TryTradeLinkup: with no cable partner
--                         Task_LinkupAwaitConnection spins until B (cable_club.c:208-214). The
--                         same probe must still be held; every held frame samples sLinkOpen/
--                         gLinkCallback for row 6 (CABLE_CALLBACK_NULL, witnessed or the
--                         no-cable-partner limit).
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

--- A released probe that never landed: when the script is over and the refusal rests on a
--- predicate pret never clears (ctx.stale_predicates; no map change or later script clears
--- either), that is a PRODUCT FINDING, recorded as such -- not a harness timeout.
local function not_landed(ctx, name, cmd, linked, script_live)
    local held = ctx.queued(cmd, linked)
    local stale = ctx.stale_predicates()
    if #stale > 0 and not script_live() then
        ctx.log(fmt("FINDING stale_predicate %s %s %s idle_field=true held=%s", name, cmd,
                    table.concat(stale, " "), tostring(held and held.why)))
        return fmt("PRODUCT FINDING: %s released to an idle field, but the overworld checkpoint still "
                   .. "refuses on a pointer pret never clears (%s)", name, table.concat(stale, "; "))
    end
    return fmt("%s: the probe never landed once released (%s)", name, tostring(held and held.why))
end

--- Face the counter north and talk across it, logging where A stands and faces first.
local function talk_across(ctx, name)
    local faced = ctx.face("Up")
    local x, y = ctx.G.pos(ctx.cp)
    ctx.log(fmt("TALK %s at=(%d,%d) facing=%d idle=%s", name, x, y, ctx.facing(), tostring(ctx.player_idle())))
    if not faced then return false, name .. ": could not face the counter (facing " .. ctx.facing() .. ")" end
    ctx.G.tap("A", 3, 13)
    return true
end

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
    local function at_welcome()
        return ctx.script_at("CableClub_EventScript_WelcomeToCableClub",
                             "CableClub_EventScript_UnusedWelcomeToCableClub")
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
    local ok_face, why_face = talk_across(ctx, "cable_welcome_message")
    if not ok_face then return false, why_face end
    if not ctx.wait_until(script_live, 10, "the Direct Corner attendant's script") then
        return false, "cable_welcome_message: the attendant's script never started"
    end
    -- drive by the witnessed position, not a delay: the no-adapter branch's welcome message
    if not ctx.wait_until(function() return at_welcome() end, 10, "CableClub_EventScript_WelcomeToCableClub") then
        ctx.log("WITNESS cable_welcome_message script=CableClub_EventScript_WelcomeToCableClub at=nil adapter_connected=unobserved")
        return false, "cable_welcome_message: the attendant never entered CableClub_EventScript_WelcomeToCableClub (the no-adapter branch)"
    end
    local at, result = at_welcome(), ctx.special_result()
    ctx.log(fmt("WITNESS cable_welcome_message script=CableClub_EventScript_WelcomeToCableClub at=%s var_result=%d "
                .. "adapter_connected=%s", tostring(at), result,
                result == 0 and "false(observed: IsWirelessAdapterConnected's VAR_RESULT)" or "TRUE"))
    if result ~= 0 then return false, "cable_welcome_message: IsWirelessAdapterConnected returned " .. result end
    local clause, why = ctx.hold_probe("cable_welcome_message", "box_mon", linked, function()
        return script_live() and at_welcome() ~= nil
    end, 600)
    if not clause then return false, why end
    -- cable_save (G4 draft §3.2 row 3): A past the \p, TRADE CENTER (multichoice row 0) and the
    -- party check reach EventScript_AskSaveGame (cable_club.inc:367 -> std_msgbox.inc:57-60):
    -- `special Field_AskSaveTheGame` creates task50_save_game (start_menu.c:620-626) and the
    -- script waits. Stop mashing on that task, before any YES: the save prompt waits for input,
    -- a stable refusing state, and the SAME box_mon is held there. The save lands after it.
    local function saving() return ctx.task_live("task50_save_game") end
    if not ctx.mash_until(saving, 60, "A") then
        return false, "cable_save: task50_save_game never started (EventScript_AskSaveGame not reached)"
    end
    clause, why = ctx.hold_probe("cable_save", "box_mon", linked, saving, 600, true)
    if not clause then return false, why end
    -- then YES through the save prompts until the linkup task waits: every A on this road means
    -- "go on", so overshoot is harmless -- for a SAME-save fixture. With a save on the cartridge
    -- start_menu.c:731 always shows the overwrite prompt (default YES, :754-759); a different-file
    -- save (gDifferentSaveFile) asks "replace the previous file?" with NO as the default
    -- (SaveDialogCB_AskReplacePreviousFilePrintYesNoMenu, :761-766): there A declines, the script
    -- aborts, and the run FAILS at the linkup wait -- never a false pass.
    local function linking() return ctx.task_live("Task_LinkupAwaitConnection") end
    if not ctx.mash_until(linking, 90, "A") then
        return false, "cable_link: Task_LinkupAwaitConnection never started (save or party check refused?)"
    end
    ctx.frames(60)
    -- row 6 (null callback while open), sampled on every held frame of the link wait. pret
    -- link.c: OpenLink sets sLinkOpen (InitLink :373) and then gLinkCallback (:394) in one
    -- function, so "open before exchange" has no frame boundary (a recorded limit). Three sites
    -- NULL the callback: ClearLinkCallback/_2 (:746-757; callers cable_club.c:637/693/886,
    -- field_fadetransition.c:661) and LinkCB_RequestPlayerDataExchange itself (:1128-1134), the
    -- most direct route once a partner connects -- but LinkMain2 runs the callback only with
    -- LINK_STAT_CONN_ESTABLISHED (:512-523), and with no cable partner Task_LinkupAwaitConnection
    -- returns on playerCount < 2 (cable_club.c:208-214), so none is reached. The expected receipt
    -- is the LIMIT form, carrying its evidence: the link open on EVERY held frame, the callback
    -- never 0 and always LinkCB_RequestPlayerDataExchange (the .sym address, ctx.sym).
    local link_cb = ctx.sym.LinkCB_RequestPlayerDataExchange | 1
    local held_n, open_n, null_n, other_cb = 0, 0, 0, nil
    local function linking_sampled()
        if not linking() then return false end
        held_n = held_n + 1
        if ctx.peek("sLinkOpen", 1) ~= 0 then
            open_n = open_n + 1
            local cb = ctx.peek("gLinkCallback", 4)
            if cb == 0 then null_n = null_n + 1 elseif cb ~= link_cb then other_cb = other_cb or cb end
        end
        return true
    end
    clause, why = ctx.hold_probe("cable_link", "box_mon", linked, linking_sampled, 600, true)
    if not clause then return false, why end
    if open_n == 0 then
        return false, "cable_link: sLinkOpen never read 1 during the link wait (nothing sampled for row 6)"
    end
    if null_n > 0 then
        ctx.log(fmt("CABLE_CALLBACK_NULL sLinkOpen=1 gLinkCallback=0 held_frames=%d open_frames=%d null_frames=%d",
                    held_n, open_n, null_n))
    else
        if open_n ~= held_n then
            return false, fmt("cable_link: the link was open on %d of %d held frames; the no-partner limit "
                              .. "needs every one", open_n, held_n)
        end
        if other_cb then
            return false, fmt("cable_link: gLinkCallback read 0x%08X, not LinkCB_RequestPlayerDataExchange "
                              .. "(0x%08X)", other_cb, link_cb)
        end
        ctx.log(fmt("CABLE_CALLBACK_NULL limit=no-cable-partner held_frames=%d open_frames=%d null_frames=0 "
                    .. "callback=0x%08X:LinkCB_RequestPlayerDataExchange", held_n, open_n, link_cb))
    end
    ctx.log(fmt("CONTROL_RELEASED cable_link box_mon %s", linked))
    G.tap("B", 3, 13)                                    -- CheckLinkCanceledBeforeConnection
    local ok, swhy = settle_field("cable_link")
    if not ok then return false, swhy end
    if not ctx.wait_sent("stats_cache", linked, 60) then
        return false, not_landed(ctx, "cable_link", "box_mon", linked, script_live)
    end
    if not ctx.observe_boxed(linked) then return false, "cable_link: " .. linked .. " never read back boxed" end
    ctx.log(fmt("CONTROL_SETTLED cable_link box_mon %s", linked))

    play.follow(cp, "center2f_direct_corner_to_union_room", "center_controls a")
    ok_face, why_face = talk_across(ctx, "union_room_attendant")
    if not ok_face then return false, why_face end
    if not ctx.wait_until(script_live, 10, "the Union Room attendant's script") then
        return false, "union_room_attendant: the script never started"
    end
    ctx.frames(120)
    at, result = at_adapter_message(), ctx.special_result()
    ctx.log(fmt("WITNESS union_room_attendant script=CableClub_EventScript_UnionRoomAdapterNotConnected "
                .. "at=%s var_result=%d adapter_connected=%s", tostring(at), result,
                (at and result == 0) and "false(observed: IsWirelessAdapterConnected's VAR_RESULT)"
                or "unobserved"))
    if not at then
        return false, "union_room_attendant: not in CableClub_EventScript_UnionRoomAdapterNotConnected"
    end
    if result ~= 0 then return false, "union_room_attendant: IsWirelessAdapterConnected returned " .. result end
    clause, why = ctx.hold_probe("union_room_attendant", "party_mon", linked, function()
        return script_live() and at_adapter_message() ~= nil
    end, 600)
    if not clause then return false, why end
    ctx.log(fmt("CONTROL_RELEASED union_room_attendant party_mon %s", linked))
    ok, swhy = settle_field("union_room_attendant")
    if not ok then return false, swhy end
    if not ctx.wait_sent("sync_retrieve_done", linked, 60) then
        return false, not_landed(ctx, "union_room_attendant", "party_mon", linked, script_live)
    end
    if not ctx.observe_returned(linked) then return false, linked .. " never read back in the party" end
    ctx.log(fmt("CONTROL_SETTLED union_room_attendant party_mon %s", linked))
    return true, "the cable menu, the Cable Club save prompt, the cable link wait and the Union Room "
                 .. "attendant each held a keyed probe; each landed once released"
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
