-- scenario_gen3_link.lua — link_gen3 (D-1 on FRLG): both halves catch on Route 1.
--
-- Nothing is injected: each cartridge hunts the pinned Route 1 grass square
-- (gen3_scripted_play.lua hunt_encounter), opens the battle BAG and throws Poke Balls through the
-- pinned pocket/cursor witnesses (throw_pokeball_from_bag) until the catch lands, declining the
-- nickname with B. The client reports `capture`; the server pairs the two captures BY AREA
-- (the runner's assert_link_new reads the pair off /api/status). The first capturer's mon is
-- quarantined (box_mon; server/state.py "quarantine: ... -> box (pending link)") until the
-- partner's capture forms the link and party_mon returns it: that half waits for the KEYED
-- sync_retrieve_done and reads the mon back in its party. A partner that finishes first means
-- the link never formed -- a consequence of the partner's own failure, reported as such (live
-- link_gen3 run 1: B's quarantined capture was correctly boxed, and B misreported A's FAIL as
-- "not in the party"). The second capturer is never quarantined; it waits for the partner.
return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local key, why = ctx.catch("link")
    if not key then return false, "hunt ended " .. tostring(why) end
    ctx.log("CAUGHT " .. key)
    local quarantined = function() return ctx.received("box_mon", key) > 0 end
    ctx.wait_until(function()
        return ctx.sent("sync_retrieve_done", key) > 0 or ctx.sent("sync_retrieve_failed", key) > 0
            or ctx.sent("box_mon_failed", key) > 0 or ctx.partner_done()
    end, 600, "post-link party sync or the partner")
    ctx.frames(120)
    for _, m in ipairs(ctx.party() or {}) do ctx.log(ctx.fmt("PARTY slot=%d key=%s species=%d", m.slot, m.key, m.species)) end
    if quarantined() then
        if ctx.sent("sync_retrieve_done", key) == 0 then
            local where = ctx.observe_boxed(key, 5)
            return false, "CONSEQUENCE: the partner finished before the link formed; " .. key
                       .. " stays quarantined in the PC" .. (where and (" at " .. where) or "")
        end
        if not ctx.observe_returned(key) then
            return false, "sync_retrieve_done sent but " .. key .. " was never read back in the party"
        end
    elseif not ctx.find(key) then
        return false, "the caught " .. key .. " is not in the party before the SAVE (never quarantined)"
    end
    local ok, why2 = ctx.save("link")
    if not ok then return false, why2 end
    return true, "caught " .. key
end
