-- scenario_gen3_rival_swap.lua — rival_swap_gen3 (RR only): a BLOCKED NEGATIVE CONTROL.
--
-- NOT a qualification of the rival swap (Codex C4-6b finding 6). The runner sends a DUMMY blob
-- (100 zero bytes, not a real party), and lua/gen3/native.lua answers refresh_failed because
-- entry.lua's refresh_enemy has no write window in the battle's first frames yet (commit
-- 9505648b; the window is OMP card C4-8's design, docs/gen3/research/rival_swap_refresh_window.md).
-- What this characterizes is only the refusal path: the command reaches a real battle and is
-- answered with the documented error instead of hanging or writing. The swap stays BLOCKED until
-- a valid team is sent and refreshed in battle; SCENARIOS["rival_swap_gen3"]["control"] says so.
--
-- Also blocked on tests/fixtures/gen3/rr_battle{,_b}.sav (not built yet) and on RR walking/battle
-- symbols reused from FR (SCENARIOS' comment).
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
    if reply.error ~= "refresh_failed" then
        return false, "expected error=refresh_failed, got " .. tostring(reply.error)
    end
    ctx.run_away("rival_swap")
    return true, "NEGATIVE CONTROL: dummy team refused with refresh_failed (swap BLOCKED, not qualified)"
end
