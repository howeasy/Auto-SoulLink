-- scenario_ghost.lua — peer-ghost over the REAL two-instance loop (needs --overworld-presence).
--
-- A walks (joypad-held directions) while B asserts the ghost: spawned (GhostState.active==1,
-- oeId!=0xFF), receives moving targets (wx changes), and actually moves (dispx/dispy deltas).
-- Motion-quality metric: a "stall" = a frame where the partner is flagged moving (mv==1) but the
-- interpolated position didn't change. max consecutive stall run is the ghoststutter number the
-- WS3-A lead-extrapolation work tightens; the baseline bar here is deliberately loose (<=10) and
-- the measured value is logged for before/after comparison.
local GHOST = 0x0203F850
local GH_ACTIVE, GH_OEID, GH_WX, GH_MV = GHOST + 0, GHOST + 1, GHOST + 6, GHOST + 11
local GH_DISPX, GH_DISPY = GHOST + 28, GHOST + 32

return function(ctx)
    local log = ctx.log
    if not ctx.wait_go() then return false, "no go-file" end

    if ctx.player == "a" then
        -- Walk a loop so the partner's ghost has continuous targets (probed walkable from the
        -- start tile (18,17): Left/Up first). Log the tile per leg + assert we actually moved.
        local function poe()
            local id = memory.read_u8(0x02037078 + 5)
            if id >= 16 then id = 0 end
            return 0x02036E38 + id * 0x24
        end
        local function tile()
            return memory.read_s16_le(poe() + 0x10), memory.read_s16_le(poe() + 0x12)
        end
        log("walking a loop for the partner's ghost")
        local x0, y0 = tile()
        local tiles_moved = 0
        local legs = {"Left", "Up", "Right", "Down"}
        for rep = 1, 6 do
            for _, dir in ipairs(legs) do
                local ax, ay = tile()
                for _ = 1, 150 do
                    joypad.set({[dir] = true})
                    coroutine.yield()
                end
                joypad.set({})
                local bx, by = tile()
                tiles_moved = tiles_moved + math.abs(bx - ax) + math.abs(by - ay)
                log(string.format("leg %d %-5s: (%d,%d) -> (%d,%d)", rep, dir, ax, ay, bx, by))
            end
        end
        if tiles_moved < 8 then
            return false, "player A barely moved (" .. tiles_moved .. " tiles) — input not reaching the core?"
        end
        return true, "walked the loop (" .. tiles_moved .. " tiles)"
    end

    -- B: the ghost of A must spawn…
    local spawned = ctx.wait_until(function()
        return (memory.read_u8(GH_ACTIVE) == 1 and memory.read_u8(GH_OEID) ~= 0xFF) or nil
    end, 7200, "ghost spawn (active=1, oeId valid)")
    if not spawned then
        return false, string.format("ghost never spawned (active=%d oeId=0x%02X)",
            memory.read_u8(GH_ACTIVE), memory.read_u8(GH_OEID))
    end
    log("ghost spawned: oeId=" .. memory.read_u8(GH_OEID))

    -- …receive moving targets, and move smoothly while A walks. NB GhostState.dispx/dispy are
    -- PLAIN px despite the struct comment's "px << 8" (drive_ghost assigns wx straight in).
    -- Two stall metrics:
    --   behind-target stall = mv==1 AND disp != target AND disp not moving -> the DRIVER is
    --     broken (hard fail, must stay <= 3);
    --   at-target stall    = mv==1 AND disp == target -> the LERP drained a stale sample
    --     (the WS3-A lead-extrapolation jank) OR the partner is bumping a wall; logged for
    --     before/after comparison, not a hard gate here.
    local prev_dx, prev_dy = memory.read_s32_le(GH_DISPX), memory.read_s32_le(GH_DISPY)
    local first_wx = memory.read_s16_le(GH_WX)
    local wx_changed = false
    local total_px = 0
    local behind_run, max_behind, at_run, max_at = 0, 0, 0, 0
    for i = 1, 2400 do
        local dx, dy = memory.read_s32_le(GH_DISPX), memory.read_s32_le(GH_DISPY)
        local wx, wy = memory.read_s16_le(GH_WX), memory.read_s16_le(GHOST + 8)
        local mv = memory.read_u8(GH_MV)
        local moved = (dx ~= prev_dx) or (dy ~= prev_dy)
        local at_target = (dx == wx) and (dy == wy)
        if wx ~= first_wx then wx_changed = true end
        if moved then
            total_px = total_px + math.abs(dx - prev_dx) + math.abs(dy - prev_dy)
            behind_run, at_run = 0, 0
        elseif mv == 1 and not at_target then
            behind_run = behind_run + 1
            if behind_run > max_behind then max_behind = behind_run end
            at_run = 0
        elseif mv == 1 then
            at_run = at_run + 1
            if at_run > max_at then max_at = at_run end
            behind_run = 0
        else
            behind_run, at_run = 0, 0
        end
        prev_dx, prev_dy = dx, dy
        if i % 600 == 0 then
            log(string.format("sample wx=%d wy=%d dispx=%d dispy=%d mv=%d", wx, wy, dx, dy, mv))
        end
        coroutine.yield()
    end
    log(string.format("GHOSTMETRIC moved_px=%d max_behind_stall=%d max_at_target_stall=%d wx_changed=%s",
        total_px, max_behind, max_at, tostring(wx_changed)))
    pcall(function()
        client.screenshot(ctx.duo.wt .. "/patch/build/e2e_ghost_b.png")
    end)
    if not wx_changed then return false, "ghost target never updated (no ghost_pos relay?)" end
    if total_px < 200 then return false, "ghost barely moved (" .. total_px .. "px)" end
    if max_behind > 3 then
        return false, "ghost stalled behind a live target (max run " .. max_behind .. " frames)"
    end
    -- Lead-extrapolation regression gate: with the WS3-A driver + advancing-mv sender the
    -- measured value is 0-1 (was 28 pre-lead); 6 leaves headroom for relay timing noise.
    if max_at > 6 then
        return false, "ghost paused at stale targets (max run " .. max_at ..
            " frames) — lead extrapolation regressed"
    end
    return true, string.format("ghost followed (%dpx, behind-stall %d, at-target-stall %d)",
        total_px, max_behind, max_at)
end
