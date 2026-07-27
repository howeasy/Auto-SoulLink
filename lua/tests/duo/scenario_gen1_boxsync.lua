-- scenario_gen1_boxsync.lua — party/box sync across two machines.
--
-- The Soul Link rule: linked mons must both be in the party or both in the box. When A
-- deposits their half of a pair, the server has to box B's half automatically.
--
-- Unlike the Gen 3 boxsync scenario — which queues box_mon/party_mon at both instances via
-- the debug API and checks the storage round-trip — this drives the REAL RULE:
--
--   A deposits its linked mon with the production depositPartyMon
--     -> the client notices the mon left the party and emits `party_to_box`
--     -> the server's _handle_party_to_box sends `box_mon` to B
--     -> B's client executes it, deferred until a safe overworld frame
--
-- So this covers the whole chain, including the deferred-command queue that used to bind
-- to a nil global and crash the Gen 1 client on the first box_mon it ever received, and
-- the safe-state gate that decides when it is allowed to run.
--
-- Both sides start with a filler in slot 1 (see duo_gen1_main): depositPartyMon refuses to
-- box the last party mon.
return function(ctx)
    local log = ctx.log
    if not ctx.wait_go() then return false, "no go-file" end

    local key0 = ctx.slot_key(0)
    if not key0 then return false, "no mon in slot 0" end
    local pre_count = ctx.party_count()
    if pre_count < 2 then
        return false, "need a filler mon to deposit anything (party=" .. pre_count .. ")"
    end
    log(string.format("go received; linked key=%s party=%d", key0, pre_count))

    if ctx.player == "a" then
        ctx.frames(120)     -- let the link-inject commands drain
        local slot = ctx.find_slot_by_key(key0)
        if not slot then return false, "linked mon vanished before the deposit" end
        local ok, err = ctx.M.depositPartyMon(slot)
        if not ok then return false, "depositPartyMon failed: " .. tostring(err) end
        log("deposited the linked mon — client should emit party_to_box")

        local gone = ctx.wait_until(function()
            return ctx.find_slot_by_key(key0) == nil or nil
        end, 3600, "our own mon to leave the party")
        if not gone then return false, "our mon never left the party" end
        if ctx.party_count() ~= pre_count - 1 then
            return false, string.format("party %d, expected %d",
                                        ctx.party_count(), pre_count - 1)
        end
        -- Stay alive: client.exit() would stop this instance sending, and B is waiting on
        -- a command the SERVER only issues after our party_to_box arrives.
        log("deposit done; staying alive until B reports")
        ctx.wait_partner_done(14400)
        return true, "party_to_box emitted for " .. key0
    end

    -- B: untouched. Its linked mon must be boxed by the server's sync rule alone.
    local boxed = ctx.wait_until(function()
        return ctx.find_slot_by_key(key0) == nil or nil
    end, 14400, "box_mon to arrive from the server")
    if not boxed then
        return false, "linked mon never left B's party (box_mon never applied)"
    end
    -- And it must actually be IN the box, not simply deleted.
    local box_count = ctx.M.getBoxCount()
    if box_count < 1 then
        return false, "mon left the party but the box is empty — it was lost, not stored"
    end
    log(string.format("linked mon auto-boxed by the sync rule (box now holds %d)", box_count))
    return true, "box_mon applied for " .. key0
end
