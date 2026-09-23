-- scenario_gen3_rival_swap.lua — rival_swap_gen3 (RR only, PLAN §14 P5, card C5-5).
--
-- BLOCKED like the other "battle"-target RR scenarios (tests/fixtures/gen3/rr_battle{,_b}.sav do
-- not exist yet, GAMES["gen3_rr_new"]'s comment) and carrying the same RR walking/symbol-reuse
-- risk (SCENARIOS["rival_swap_gen3"]'s comment) -- written for structural correctness, not yet
-- exercised.
--
-- A idles; B walks into a real battle (ctx.hunt, the same Route-1-shaped grass hunt the FRLG
-- scenarios use) and parks at the action menu -- no input, so pressing A cannot pre-empt the
-- server's command. Once B logs READY_IN_BATTLE the runner
-- (orchestrate_rival_swap_gen3) queues replace_rival_team over the debug API.
-- lua/gen3/native.lua:243-244 always answers refresh_failed today (entry.lua's refresh_enemy has
-- no write window in the battle's first frames yet, commit 9505648b) -- that is the DOCUMENTED,
-- EXPECTED outcome this scenario asserts, not a bug it is chasing.
return function(ctx)
    if ctx.player == "a" then
        if not ctx.wait_go(300) then return false, "no go-file" end
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
    return true, "rival_team_replaced error=refresh_failed (expected: no refresh window yet)"
end
