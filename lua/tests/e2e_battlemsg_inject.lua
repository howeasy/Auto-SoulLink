-- e2e_battlemsg_inject.lua — TRUE END-TO-END: run the REAL production client (same dofile as
-- slink_gen3.lua) against a REAL server, from the in-battle savestate. The harness has pre-queued real
-- server commands (msgbox shiny/linked + force_faint) via /api/debug/queue_command; they arrive in the
-- hello response and flow through the production dispatch_commands -> show_fallback -> the native
-- in-battle notification. This wrapper just watches BattleNotif.active rising edges and screenshots each
-- notification mid-display, proving the right text + thematic color rendered for each injected event.
-- HARDENED: incremental log flush every write (diagnose silent mid-run deaths), pcall'd dofile, and a
-- periodic mailbox/BN heartbeat so a stall is visible in the partial log.
local WT  = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/e2e_result.txt"
local logf = io.open(OUT, "w")
local function log(s)
    console.log(s)
    if logf then logf:write(s .. "\n"); logf:flush() end
end

-- production client config (what slink_gen3.lua sets)
SLINK_HOST   = "127.0.0.1"
SLINK_PORT   = 54399          -- the harness's throwaway server (NOT the real 54321)
SLINK_PLAYER = "a"

-- Capture the production client's own console.log lines into our result file: the client logs every
-- dispatch decision (msgbox native vs fallback, force_faint routing, config), which is exactly the
-- visibility a headless run lacks.
local _console_log = console.log
console.log = function(s)
    _console_log(s)
    if logf then logf:write("[client] " .. tostring(s) .. "\n"); logf:flush() end
end

pcall(function() client.speedmode(400) end)
local okst, errst = pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_battle2.State")
log("savestate load ok=" .. tostring(okst) .. (errst and (" err=" .. tostring(errst)) or ""))
emu.frameadvance()

local okc, errc = pcall(dofile, WT .. "/lua/clients/gen3_frlge_client.lua")   -- the REAL production client
log("client dofile ok=" .. tostring(okc) .. (errc and (" err=" .. tostring(errc)) or ""))
if not okc then
    log("RESULT: FAIL (client dofile error)")
    if logf then logf:close() end
    client.exit()
    return
end

local BN_ACTIVE = 0x0203FD00
local MB_STATUS = 0x0203F806
local shots, prev_active, shoot_at = 0, 0, nil
for frame = 1, 5000 do
    local ok, err = pcall(function()
        local active = memory.read_u8(BN_ACTIVE)
        if active == 1 and prev_active == 0 then         -- a notification just ARMED
            shots = shots + 1
            shoot_at = frame + 40                         -- screenshot mid-display
            log(string.format("notification #%d armed at frame %d", shots, frame))
        end
        prev_active = active
        if shoot_at and frame >= shoot_at then
            pcall(function() client.screenshot(WT .. "/patch/build/e2e_msg" .. shots .. ".png") end)
            log(string.format("shot e2e_msg%d.png (frame %d)", shots, frame))
            shoot_at = nil
        end
        if frame % 600 == 0 then
            log(string.format("heartbeat f=%d BN=%d mb_status=%04X shots=%d",
                frame, active, memory.read_u16_le(MB_STATUS), shots))
        end
    end)
    if not ok then log("watch error f=" .. frame .. ": " .. tostring(err)) end
    if shots >= 3 and not shoot_at then break end
    emu.frameadvance()
end
log("done: " .. shots .. " notifications captured")
log((shots >= 3) and "RESULT: PASS" or "RESULT: FAIL")
if logf then logf:close() end
client.exit()
