-- scenario_gen1_faint.lua — two-instance Soul Link faint propagation on Gen 1.
--
-- The rule this proves is the core of SLink: when one player's linked mon dies, the
-- partner's linked mon must die too, on the other machine, through the real server.
--
-- Runner orchestration: both instances hello, the runner links A slot0 <-> B slot0 using
-- the MYKEY lines, then writes the go-file.
--   A: zero slot 0's HP -> the production client emits `faint` -> the server queues
--      force_faint for B's linked key.
--   B: assert the linked mon's HP reaches 0 without anyone touching that machine.
--
-- This is the end-to-end version of two things that were only ever unit-tested before:
-- the client's faint detection (which reads HP big-endian on Gen 1) and its force_faint
-- handler — the very handler whose queue used to bind to a nil global and crash.
--
-- HP is read and written through ctx, never with raw memory calls: Gen 1 is big-endian
-- where Gen 3 is little-endian, and a scenario poking bytes directly would silently write
-- a byte-swapped value.
return function(ctx)
    local log = ctx.log
    if not ctx.wait_go() then return false, "no go-file" end

    local key0 = ctx.slot_key(0)
    if not key0 then return false, "no mon in slot 0" end
    local pre_count = ctx.party_count()
    log(string.format("go received; slot0 key=%s hp=%d party=%d",
                      key0, ctx.read_hp(0), pre_count))

    if ctx.player == "a" then
        -- Let the link-inject commands (msgbox / jingle) drain first.
        ctx.frames(120)
        ctx.write_hp(0, 0)
        log("wrote HP=0 to slot 0 — the client should emit `faint`")
        -- Confirm OUR side registered it, so a failure on B can be attributed.
        local seen = ctx.wait_until(function()
            return ctx.read_hp(0) == 0 or ctx.find_slot_by_key(key0) == nil
        end, 3600, "own faint to stick")
        if not seen then return false, "our own HP write did not stick" end
        -- STAY ALIVE until B has its verdict. Returning here would call client.exit() and
        -- kill this emulator, and the client would never get the frames it needs to send
        -- the faint at all — measured: A's log ended after `hello`, with no ticks.
        log("faint written; staying alive until B reports")
        ctx.wait_partner_done(14400)
        return true, "faint emitted for " .. key0
    end

    -- B: nothing touches this instance. The partner's death has to arrive over TCP as
    -- force_faint and be applied by the production client.
    --
    -- GETTING THIS ASSERTION RIGHT TOOK THREE TRIES, and both earlier ones were unsound:
    --   * "HP==0 or the mon left the party" passed whenever the mon merely disappeared —
    --     which the memorialize queued by the same faint does anyway, so a completely no-op
    --     forceFaint still passed. That is a test that cannot fail.
    --   * "HP==0" alone is unobservable: force_faint lands, the client reports the faint, and
    --     the deferred memorialize buries the mon — the 0-HP window is about two frames wide,
    --     and at 400x speed the poll can step straight over it. Measured: the mon really did
    --     faint (B emitted `faint` and then `memorialize_done`) and this still timed out.
    --
    -- So: latch the transient if we catch it, and otherwise require DURABLE corroboration —
    -- the mon in B's memorial box. A disappearance with nothing in the graveyard is still a
    -- failure, which is exactly the no-op-forceFaint case the first version let through.
    local M = ctx.M
    local saw_zero, buried = false, false
    ctx.wait_until(function()
        local s = ctx.find_slot_by_key(key0)
        if s then
            if ctx.read_hp(s) == 0 then saw_zero = true return true end
            return nil
        end
        for i = 0, (M.BOX_MAX_MONS or 20) - 1 do
            local m = M.readMemorialBoxSlot and M.readMemorialBoxSlot(i)
            if m and m.key == key0 then buried = true return true end
        end
        return nil
    end, 14400, "force_faint to arrive from the server")

    if not (saw_zero or buried) then
        return false, "linked mon never fainted on B (force_faint never applied, and it is "
                      .. "not in the memorial box either)"
    end
    log(saw_zero and "observed the linked mon at 0 HP"
                 or  "linked mon was already buried in the memorial box — it died")
    log("linked mon died from the partner's faint — propagation works")
    return true, "force_faint applied to " .. key0
end
