-- tools/polished_live/duo_play.lua -- ONE side of the two-instance Polished Soul Link PLAY scenarios, launched by
-- `duo.py --scenario NAME|all`. The REAL client runs through the real entry (lua/slink.lua -> gen2 ->
-- compose_polished); this driver presses buttons, reads, and executes the runner's STEPS one at a time.
--
-- Step protocol (file based; the runner is tools/polished_live/duo.py play_main):
--   the runner writes <POL_RUN>/step_<k>.json = {"op": ..., ...} for k = 1, 2, ... in order;
--   this driver polls for the next k every 30 frames while the client keeps ticking, runs it, and appends
--   PLAY_STEP {"k":k,"op":...,"ok":...,...} to POL_OUT. Ops:
--     catch                     NATIVE wild catch on the fixture's Route 29 grass (walk, Bag -> Ball, throw; never
--                               Run: a fled battle would send no_catch and dead-zone the area). Result: the client's
--                               own `capture` line (key, area_id) and the capture-site hit count.
--     snapshot                  cartridge read-back: party (slot, key, species, HP/MaxHP big-endian, status) read
--                               from WRAM, and the box census keys read from CartRAM.
--     await_cmd {cmd,key,frames} wait until the SERVER's reply delivered `cmd` (for `key`), let the client run it at
--                               its overworld hold, then snapshot. The command is never executed by this driver.
--     synth_hp0 {keys|all}      SYNTH SETUP (disclosed): poke current HP to 0 in the named party records (WRAM),
--                               then drop the client's TCP session (connector.disconnect) so its native reconnect
--                               re-sends hello carrying that party. Every SYNTH byte is listed in the result and is
--                               written through the UNTAPPED writer, so the client's own write count stays clean.
--     idle {frames}
--     stop                      finish (exit marker RESULT: ... duo-play-side-<role>)
-- Bounds: 1800-frame NPC stall while walking, 9000 frames per battle, DUO_HOLD_CAP total frames; no per-frame log.
local L = dofile(os.getenv("SLINK_ROOT") .. "/tools/polished_live/pol_lib.lua")
local fmt, J = string.format, L.json
local ROLE = os.getenv("DUO_ROLE") or "?"
local HOLD_CAP = tonumber(os.getenv("DUO_HOLD_CAP")) or 400000
local STALL = 1800
local WALK = {46, 51}            -- Route 29 grass run on the warp fixture's row (live.lua POL_WALK default)
local STRIDE, STATUS_OFF, HP_OFF, MAXHP_OFF = 48, 32, 34, 36
client.speedmode(400)
L.log(fmt("[play %s] boot frame %d rom %s", ROLE, emu.framecount(), gameinfo.getromhash()))

-- the UNTAPPED writer, captured before the tap: only synth_hp0 uses it, and every byte it writes is reported
local raw_write_u8 = memory.write_u8
local client_writes = {}
for _, k in ipairs({"write_u8", "write_s8", "write_u16_le", "write_u16_be", "write_s16_le", "write_s16_be", "write_u24_le",
                    "write_u24_be", "write_u32_le", "write_u32_be", "write_s32_le", "write_s32_be", "writebyte",
                    "writebyterange", "write_bytes_as_array", "write_bytes_as_dict", "writefloat"}) do
    local fn = memory[k]
    if fn ~= nil then
        memory[k] = function(...)
            local a = {...}
            client_writes[#client_writes + 1] = fmt("%s(%s,%s,%s) frame %d", k, tostring(a[1]), tostring(a[2]),
                                                    tostring(a[3]), emu.framecount())
            return fn(...)
        end
    end
end

-- read-only exec probes, registered BEFORE the client exactly as live.lua does
local sites = J.decode(L.slurp(L.ROOT .. "/data/games/polished_crystal/engine_signals.json"))
local cap = sites.titles.polished_crystal.sites.capture_party
local cap_hits = 0
L.hook_at("capture_site", cap.bank, cap.addr, function(right_bank) if right_bank then cap_hits = cap_hits + 1 end end)
for _, name in ipairs({"OWPlayerInput", "SetInitialOptions.joypad_loop", "LoadBattleMenu", "BattleMenu_Run",
                       "PokeBallEffect", "PokeBallEffect.caught", "PokeBallEffect.SendToPC", "BlinkCursor", "YesNoBox",
                       "StartBattle", "ExitBattle", "BattlePack"}) do
    if L.SYM[name] then L.hook(name) end
end

SLINK_HOST, SLINK_PORT, SLINK_PLAYER = os.getenv("SLINK_HOST"), tonumber(os.getenv("SLINK_PORT")), os.getenv("SLINK_PLAYER")
dofile(L.ROOT .. "/lua/slink.lua")
if not SLINK_GEN2_CLIENT then L.die("the Gen 2 route did not start a client") end
local P = SLINK_GEN2_PARTS
L.check("admitted as the Polished overlay (DEV_OVERLAY_SHA1)", P.pack == "polished_crystal" and P.title == "polished"
        and P.artifact_kind == "overlay" and P.qualification == "DEV_OVERLAY_SHA1")
local okpm, PM = pcall(dofile, L.ROOT .. "/lua/gen2/polished.lua")
if not okpm then PM = nil end

-- wire tap: every hello/capture the client sent (frame + party key/hp), every command the server sent back
local C = package.loaded["connector"]
local hellos, captures, received = {}, {}, {}
local orig_send, orig_recv = C.send, C.receive
C.send = function(line, ...)
    local ok, msg = pcall(J.decode, line)
    if ok and type(msg) == "table" then
        if msg.event == "hello" then
            local party = {}
            for _, e in ipairs(msg.party or {}) do party[#party + 1] = {key = e.key, hp = e.hp} end
            hellos[#hellos + 1] = {frame = emu.framecount(), party = party}
        elseif msg.event == "capture" then
            captures[#captures + 1] = {frame = emu.framecount(), key = msg.key, area_id = msg.area_id,
                                       species_id = msg.species_id, level = msg.level, in_box = msg.in_box}
        end
    end
    return orig_send(line, ...)
end
C.receive = function(...)
    local line = orig_recv(...)
    if line ~= nil then
        local ok, msg = pcall(J.decode, line)
        if ok and type(msg) == "table" and type(msg.commands) == "table" then
            for _, c in ipairs(msg.commands) do
                if type(c) == "table" and c.cmd ~= "noop" then
                    received[#received + 1] = {frame = emu.framecount(), cmd = tostring(c.cmd), key = c.key}
                end
            end
        end
    end
    return line
end

-- ── cartridge read-back ──────────────────────────────────────────────────────────────────────────
-- party records read (and SYNTH-poked) in the WRAM domain at the symbol's own bank (L.woff), never through
-- whatever WRAMX bank SVBK happens to map on the System Bus
local function pbyte(slot, off) return L.rw("wPartyMons", slot * STRIDE + off) end
local function be16(slot, off) return pbyte(slot, off) * 256 + pbyte(slot, off + 1) end
local function snapshot()
    local party, why = P.reads:read_party()
    local mons = {}
    for i, m in ipairs(party and party.mons or {}) do
        local slot = i - 1
        mons[#mons + 1] = {slot = slot, key = m.key, species = pbyte(slot, 0), hp = be16(slot, HP_OFF),
                           max_hp = be16(slot, MAXHP_OFF), status = pbyte(slot, STATUS_OFF)}
    end
    local box, box_why = {}, nil
    local okb, err = pcall(function()
        for b = 0, 19 do
            local list, w = P.reads.read_storage_box(b)
            if not list then box_why = tostring(w) return end
            for _, m in ipairs(list) do
                local k = m.key
                if k == nil and PM then local okk, kk = pcall(PM.mon_key, m) k = okk and kk or nil end
                box[#box + 1] = {box = b, slot = m.slot, key = k}
            end
        end
    end)
    if not okb then box_why = tostring(err) end
    return {frame = emu.framecount(), party_count = L.rw("wPartyCount"), party = mons,
            party_why = party == nil and tostring(why) or nil, box = box, box_why = box_why}
end
local function slot_of(snap, key)
    for _, m in ipairs(snap.party) do if m.key == key then return m.slot end end
    return nil
end

-- ── native catch (ported from live.lua STAGE 2; Bag -> Ball, never Run) ─────────────────────────────
local BALL_POCKET = 2
local function walk_for_battle()
    local f, dir, lastx, moved = emu.framecount(), "Left", L.rw("wXCoord"), emu.framecount()
    while not L.after("StartBattle", f) do
        if emu.framecount() - f > 20000 then return false, "no wild battle in 20000 frames" end
        local x = L.rw("wXCoord")
        if x ~= lastx then lastx, moved = x, emu.framecount() end
        if emu.framecount() - moved > STALL then return false, fmt("NPC stall: x unchanged %d frames", STALL) end
        if x <= WALK[1] then dir = "Right" elseif x >= WALK[2] then dir = "Left" end
        if L.recent("BlinkCursor", 2) then L.pulse("A") else L.frame({[dir] = true}) end
    end
    L.idle(2)
    return true
end
local function battle_throw()
    local f_start, handled, last_act, prepped, prep_pulses = emu.framecount(), -1, emu.framecount(), -1, 0
    local throws, foe = 0, nil
    while not L.after("OWPlayerInput", f_start) do
        local f = emu.framecount()
        if f - f_start > 9000 then return nil, "battle did not end in 9000 frames" end
        local menu, btn = L.hit.LoadBattleMenu, nil
        if menu and menu > handled and f - menu >= 6 and not foe then
            foe = {species = L.rw("wEnemyMonSpecies"), level = L.rw("wEnemyMonLevel")}
        end
        if menu and menu > handled and f - menu >= 6 then
            if L.after("PokeBallEffect", menu) or L.after("BattleMenu_Run", menu) then handled = menu
            elseif L.after("BattlePack", menu) then btn = L.rw("wCurPocket") == BALL_POCKET and "A" or "Right"
            elseif prepped ~= menu then
                btn = "Start"                                               -- START on Bag (menu.asm QUICK_PACK)
                if (emu.framecount() % 16) < 2 then prep_pulses = prep_pulses + 1 end
                if prep_pulses >= 2 then prepped, prep_pulses = menu, 0 end
            else btn = "A" end
        elseif L.recent("YesNoBox", 40) then btn = "B"                      -- nickname? NO
        elseif L.recent("BlinkCursor", 2) then btn = "A"
        elseif f - math.max(last_act, L.hit.BlinkCursor or 0, L.hit.LoadBattleMenu or 0) > 90 then btn = "B" end
        if btn and (f % 16) < 2 then last_act = f end
        local before = L.hits.PokeBallEffect
        L.pulse(btn)
        if L.hits.PokeBallEffect > before then throws = throws + 1 end
    end
    local caught = L.hit["PokeBallEffect.caught"] ~= nil and L.hit["PokeBallEffect.caught"] >= f_start
    L.to_overworld(nil, nil, 30, 3000, "play-after-battle")
    return {caught = caught, throws = throws, foe = foe, frames = emu.framecount() - f_start,
            run_used = L.after("BattleMenu_Run", f_start)}
end
local function op_catch(step)
    local attempts, cap0, c0, battles = tonumber(step.attempts) or 4, cap_hits, #captures, {}
    for i = 1, attempts do
        local ok, why = walk_for_battle()
        if not ok then return {ok = false, why = why, battles = battles} end
        local b, bwhy = battle_throw()
        if not b then return {ok = false, why = bwhy, battles = battles} end
        battles[#battles + 1] = b
        if b.caught then break end
    end
    local f = emu.framecount()
    while #captures == c0 and emu.framecount() - f < 600 do L.frame() end
    local cev = captures[c0 + 1]
    return {ok = cev ~= nil, why = cev == nil and "the client sent no capture line" or nil, capture = cev,
            capture_site_hits = cap_hits - cap0, battles = battles, snapshot = snapshot()}
end

local function op_await(step)
    local f0, found = emu.framecount(), nil
    local frames = tonumber(step.frames) or 3600
    while emu.framecount() - f0 < frames do
        for _, r in ipairs(received) do
            if r.cmd == step.cmd and (step.key == nil or r.key == step.key) then found = r break end
        end
        if found then break end
        L.frame()
    end
    if found then L.idle(tonumber(step.settle) or 300) end           -- the client runs it at its overworld hold
    return {ok = found ~= nil, why = found == nil and fmt("%s %s not received in %d frames", tostring(step.cmd),
            tostring(step.key), frames) or nil, received = found, snapshot = snapshot()}
end

local function op_synth_hp0(step)
    local before = snapshot()
    local want, writes = {}, {}
    for _, k in ipairs(step.keys or {}) do want[k] = true end
    for _, m in ipairs(before.party) do
        if step.all == true or want[m.key] then
            for _, off in ipairs({HP_OFF, HP_OFF + 1}) do
                local addr = L.woff("wPartyMons", m.slot * STRIDE + off)
                writes[#writes + 1] = {wram = addr, old = memory.read_u8(addr, "WRAM"), new = 0, slot = m.slot, key = m.key}
                raw_write_u8(addr, 0, "WRAM")
            end
        end
    end
    local h0 = #hellos
    C.disconnect()                       -- SYNTH: drop the session; the client's own reconnect re-sends hello
    local f = emu.framecount()
    while #hellos == h0 and emu.framecount() - f < STALL do L.frame() end
    L.idle(tonumber(step.settle) or 300)
    local h = hellos[h0 + 1]
    return {ok = #writes > 0 and h ~= nil, why = (#writes == 0 and "no party record matched") or (h == nil and
            "no hello re-sent after the reconnect") or nil, synth_writes = writes, before = before,
            rehello = h, snapshot = snapshot()}
end

-- ── boot + step loop ─────────────────────────────────────────────────────────────────────────────
if not L.to_overworld(24, 3, 60, 8000, "continue") then L.die("CONTINUE did not reach map 24:3") end
local f0 = emu.framecount()
while not SLINK_GEN2_CLIENT.hello_sent and emu.framecount() - f0 < STALL do L.frame() end
L.check("client sent its hello", #hellos > 0)
L.idle(300)
L.log("PLAY_READY " .. J.encode({role = ROLE, frame = emu.framecount(), hellos = #hellos}))

local k, held, stopped = 0, 0, false
while held < HOLD_CAP do
    if held % 30 == 0 then
        local path = fmt("%s/step_%d.json", L.RUN, k + 1)
        local fh = io.open(path, "rb")
        if fh then
            local text = fh:read("*a")
            fh:close()
            local okd, step = pcall(J.decode, text)
            k = k + 1
            local res
            if not okd or type(step) ~= "table" then res = {ok = false, why = "unreadable step file"}
            elseif step.op == "stop" then stopped = true res = {ok = true}
            elseif step.op == "catch" then res = op_catch(step)
            elseif step.op == "snapshot" then res = {ok = true, snapshot = snapshot()}
            elseif step.op == "await_cmd" then res = op_await(step)
            elseif step.op == "synth_hp0" then res = op_synth_hp0(step)
            elseif step.op == "idle" then L.idle(tonumber(step.frames) or 60) res = {ok = true}
            else res = {ok = false, why = "unknown op " .. tostring(step.op)} end
            res.k, res.op, res.label, res.frame = k, okd and step.op or "?", okd and step.label or nil, emu.framecount()
            res.client_writes = #client_writes
            local oke, line = pcall(J.encode, res)
            L.log("PLAY_STEP " .. (oke and line or J.encode({k = k, op = res.op, ok = false, why = "encode: " .. tostring(line)})))
            if stopped then break end
        end
    end
    L.frame()
    held = held + 1
end
L.check("stop step seen (not the hold cap)", stopped, held)
L.log("PLAY_FINAL " .. J.encode({role = ROLE, frame = emu.framecount(), client_writes = #client_writes,
      client_write_log = table.concat(client_writes, "; "):sub(1, 1500), received = #received, hellos = #hellos,
      captures = #captures}))
L.finish("duo-play-side-" .. ROLE)
