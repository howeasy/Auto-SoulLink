-- HUD-SHOT: pixel proof for lua/hud.lua word-wrap + burst-drain (commit 7d64f76).
-- Standalone: no client/server, just dofile the shared hud.lua directly and drive
-- H.show/H.prompt on a plain title-screen boot of the Gen 1 Red ROM.
local SLINK_ROOT = "E:/Google Drive/SLink/.claude/worktrees/gen1-master-release-plan-6b4279/"
local SCRATCH = "C:/Users/howar/AppData/Local/Temp/claude/E--Google-Drive-SLink--claude-worktrees-gen1-master-release-plan-6b4279/e136b7e5-2160-411d-b1cf-7b538efc4203/scratchpad/hud_shot/"

-- console.log only reaches EmuHawk's own Lua Console window, not our subprocess
-- stdout (no server/slink.lua tee here) -- tee it to a file ourselves so the card's
-- "console log" deliverable exists.
local logf = io.open(SCRATCH .. "console.log", "w")
local real_console_log = console.log
console.log = function(msg)
    real_console_log(msg)
    if logf then logf:write(tostring(msg) .. "\n"); logf:flush() end
end

console.log("=== HUD_SHOT boot " .. os.date() .. " ===")

-- Counting shim: hud_queue is module-local (not exposed), so use draw-call counts
-- as a proxy for "how many lines got rendered this frame" / "did anything render".
local draw_text_calls, draw_box_calls = 0, 0
local real_drawText, real_drawBox = gui.drawText, gui.drawBox
gui.drawText = function(...) draw_text_calls = draw_text_calls + 1; return real_drawText(...) end
gui.drawBox  = function(...) draw_box_calls  = draw_box_calls  + 1; return real_drawBox(...)  end

local H = dofile(SLINK_ROOT .. "lua/hud.lua")
H.init({ screen_w = 160, screen_h = 144 })
console.log("[HUD_SHOT] init ok (Gen1 160x144)")

-- 30-char/line budget (char_width=5) x 3 lines: this message needs exactly 3 lines.
local LONG_MSG = "Bulbasaur and Charmander linked! Route 1 pair formed, watch both HP bars closely"
-- 4-line prompt: deliberately longer than the 30x4=120 char budget to also exercise
-- the ellipsis fallback path (watch console for a "[SLink-HUD] message exceeds" line).
local PROMPT_MSG = "Route 1 rendezvous complete. Both trainers should now proceed north together toward Viridian Forest before the next gym challenge begins."

-- Push order matters: enqueue() drops the OLDEST entry once the queue exceeds
-- MAX_QUEUE=4 (lua/hud.lua:239). Pushing 5 distinct messages in one frame always
-- evicts whichever was pushed FIRST, regardless of which one we care about --
-- so LONG_MSG is pushed 2nd (not 1st) to survive as the queue head and be the
-- thing visible in the frame-180 screenshot. (Pushing it 1st, as the card's literal
-- wording suggests, would have it silently evicted the same frame — a real
-- eviction-order gotcha worth flagging, not simulating away.)
local BURST = { "Pidgey linked!", "Rattata linked!", "Caterpie linked!", "Weedle linked!" }

local frame = 0
local shots = { 180, 700, 1000 }
local shot_i = 1
local last_text, last_box = -1, -1

event.onframeend(function()
    frame = frame + 1

    if frame == 120 then
        H.show(BURST[1], 200, 200, 255, 240)
        H.show(LONG_MSG, 255, 255, 255, 300)
        H.show(BURST[2], 200, 200, 255, 240)
        H.show(BURST[3], 200, 200, 255, 240)
        H.show(BURST[4], 200, 200, 255, 240)
        console.log("[HUD_SHOT] frame=120 queued burst[1] + LONG + burst[2..4] (5 pushes, cap=4)")
    end

    if frame == 1300 then
        H.prompt(PROMPT_MSG, 255, 255, 0, 300)
        console.log("[HUD_SHOT] frame=1300 prompt queued")
    end

    draw_text_calls, draw_box_calls = 0, 0
    H.render()

    -- Transition-only logging (not per-frame) so the emulator isn't starved.
    if draw_text_calls ~= last_text or draw_box_calls ~= last_box then
        console.log(string.format("[HUD_SHOT] frame=%d draws text=%d box=%d", frame, draw_text_calls, draw_box_calls))
        last_text, last_box = draw_text_calls, draw_box_calls
    end

    if shot_i <= #shots and frame == shots[shot_i] then
        local path = SCRATCH .. "hud_shot_" .. frame .. ".png"
        client.screenshot(path)
        console.log(string.format("HUD_SHOT frame=%d queue_proxy_text=%d queue_proxy_box=%d -> %s",
                                   frame, draw_text_calls, draw_box_calls, path))
        shot_i = shot_i + 1
    end

    if frame == 1310 then
        local path = SCRATCH .. "hud_shot_1310_prompt.png"
        client.screenshot(path)
        console.log(string.format("HUD_SHOT frame=%d (prompt) queue_proxy_text=%d queue_proxy_box=%d -> %s",
                                   frame, draw_text_calls, draw_box_calls, path))
    end

    if frame == 1400 then
        console.log("[HUD_SHOT] exiting")
        if logf then logf:close() end
        client.exit()
    end
end)
