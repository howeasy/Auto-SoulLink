-- scenario_gen3_rival_swap.lua — rival_swap_gen3 (RR only): a BLOCKED NEGATIVE CONTROL.
--
-- NOT a qualification of the rival swap (Codex C4-6b finding 6). The runner queues a DUMMY blob
-- (100 zero bytes) with NO session/battle_id, straight to B's queue. The new client declares
-- battle_identity, so the C5-10 identity gate (2dc1b750; docs/gen3/research/
-- rival_swap_refresh_window.md §3.3: missing -> refuse, nothing written) answers stale_battle_id
-- before anything is staged. What this characterizes is only that refusal path: the command
-- reaches a real battle and is refused by name instead of hanging or writing.
--
-- A idles; B walks into a real battle and parks at the action menu -- no input, so pressing A
-- cannot pre-empt the server's command. Once B logs READY_IN_BATTLE the runner
-- (orchestrate_rival_swap_gen3) queues replace_rival_team over the debug API.
return function(ctx)
    if ctx.player == "a" then
        if not ctx.wait_go(nil, 300) then return false, "no go-file" end
        if not ctx.wait_until(ctx.partner_done, 300, "B's result") then
            return false, "B never finished"
        end
        return true, "idle (rival_swap only drives B's cartridge)"
    end

    if not ctx.wait_go() then return false, "no go-file" end
    if not ctx.hunt("rival_swap") then return false, "no wild encounter" end
    local turn = ctx.await_turn(60, "B")
    if turn ~= "action" then return false, "never reached the action menu (" .. tostring(turn) .. ")" end
    ctx.log("READY_IN_BATTLE")
    if not ctx.wait_received("replace_rival_team", nil, 300) then
        return false, "replace_rival_team never arrived"
    end
    if not ctx.wait_sent("rival_team_replaced", nil, 120) then
        return false, "no rival_team_replaced reply"
    end
    local reply = ctx.last_sent("rival_team_replaced") or {}
    if reply.error ~= "stale_battle_id" then
        return false, "expected error=stale_battle_id, got " .. tostring(reply.error)
    end
    ctx.run_away("rival_swap")
    return true, "NEGATIVE CONTROL: identity-less dummy team refused with stale_battle_id (not qualified)"
end
