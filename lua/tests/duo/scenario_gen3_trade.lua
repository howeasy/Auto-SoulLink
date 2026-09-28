-- scenario_gen3_trade.lua — trade_gen3 / trade_decline_gen3 (RR companion, both sides).
--
-- The runner links both slot-1 mons and names each side's partner key in the go-file
-- ("PARTNER <key>"). A (rr_battle2, Route 1 grass) walks to the Viridian Pokemon Center and talks
-- to the companion patch's trade NPC (patch/src/handlers.c drive_trade_npc: localId 0xF1, spawned
-- at currentCoords (10,9) = map tile (3,2), MOVEMENT_TYPE_WANDER_AROUND clamped to +-1 tile).
-- The talk is an ordinary A press facing it; check_peer_interact bumps SlinkState.pi_count, the
-- client sends trade_request, and everything after that is the SERVER's menu flow on the NATIVE
-- menus (server/state.py _handle_trade_request .. _commit_trade): A picks "Trade" on the
-- show_choices list and its linked mon on the choose_mon party screen; B answers show_menu's
-- YES/NO (YES for trade_gen3, B/NO for trade_decline_gen3). On YES both clients run the durable
-- native trade (RR-DURABLE, the shared FR/LG producer): apply_prepare -> the native "save the
-- game?" pre-save -> apply_ready, then apply_trade -> the native scene -> the native post-save ->
-- trade_done. A is pressed only while the durable producer owns the screen (producer_phase
-- PRE_SAVE 1 or SCENE 3 at profile native.TRADE_BASE + 0x48, the T5 FR driver's gate), so no press
-- can reach the NPC again. Both halves then save on the runner's SAVE; the oracle decodes the
-- flash itself (PYDEC).
--
-- Game facts: the Center 1F geometry is tools/gba_map.py's parse of the pinned RR ROM
--   python tools/gba_map.py patch/build/slink_RR.gba --map 5.4 --dump
--   -> rows 2-3 "....###..##...." / "....#######....", row 4 all open; objects 4 (2,3) wander,
--      20 (5,6), 3 (4,7); bfs (7,8)->(7,4) = Up x4 (the nurse path), then row 4 west to (3,4)
-- and the NPC's tile/ids are handlers.c's PCNPC_TILE_X/Y, TN_LOCALID. Every coordinate the walk
-- uses at runtime is the NPC's LIVE object-event position (it wanders), never a screenshot.
local SC2 = 0x03000F9C          -- sScriptContext2Enabled (patch/src/handlers.c:532)
local TN_LOCALID = 0xF1         -- handlers.c:122
local OE_STRIDE = 0x24
local ADJ = { ["0,-1"] = "Up", ["0,1"] = "Down", ["-1,0"] = "Left", ["1,0"] = "Right" }
local DELTA = { Up = { 0, -1 }, Down = { 0, 1 }, Left = { -1, 0 }, Right = { 1, 0 } }
local FACING = { Down = 1, Up = 2, Left = 3, Right = 4 }

local function u8(a) return memory.read_u8(a, "System Bus") end
local function u16(a) return memory.read_u16_le(a, "System Bus") end
local function u32(a) return memory.read_u32_le(a, "System Bus") end
local function s16(a) local v = u16(a); return v >= 0x8000 and v - 0x10000 or v end

local function native_block(ctx)
    local JSON = dofile(ctx.D.wt .. "/lua/json_codec.lua")
    local f = assert(io.open(ctx.D.wt .. "/data/games/gen3_rr/profile.json", "rb"))
    local doc = JSON.decode(f:read("a")); f:close()
    local N = assert(doc.native, "gen3_rr profile has no native block")
    N.PARTY_COUNT_ADDR = assert(doc.titles.radical_red.ram.PARTY_COUNT_ADDR)
    return N
end

local function oe(N, i) return N.OBJECT_EVENTS_BASE + i * OE_STRIDE end
local function player_slot(N) local id = u8(N.GPLAYER_AVATAR + 5); return id < 16 and id or 0 end
local function npc_slot(N)
    for i = 0, 15 do
        local b = oe(N, i)
        if (u8(b) & 1) == 1 and u8(b + 8) == TN_LOCALID then return i end
    end
end
local function tile_of(N, i) return s16(oe(N, i) + 0x10) - 7, s16(oe(N, i) + 0x12) - 7 end
local function occupied(N, x, y)
    local me = player_slot(N)
    for i = 0, 15 do
        if i ~= me and (u8(oe(N, i)) & 1) == 1 then
            local ox, oy = tile_of(N, i)
            if ox == x and oy == y then return true end
        end
    end
    return false
end
local function player_idle(N)
    local f = u8(oe(N, player_slot(N)))
    return (f & 0x40) == 0 or (f & 0x80) ~= 0
end
local function facing(N) return u8(oe(N, player_slot(N)) + 0x18) & 0x0F end
local function field_cb(N) return u32(N.GMAIN_CB2_PTR) == N.CB2_OVERWORLD end

local function face(ctx, N, dir)
    for _ = 1, 6 do
        ctx.wait_until(function() return player_idle(N) end, 5, "idle before a turn")
        if facing(N) == FACING[dir] then return true end
        ctx.G.tap(dir, 3, 20)
    end
    return facing(N) == FACING[dir]
end
--- One step into a FREE tile (checked first, so the step never bumps an object), proven by the
--- player's map position.
local function step(ctx, N, dir)
    local px, py = ctx.G.pos(ctx.cp)
    local wx, wy = px + DELTA[dir][1], py + DELTA[dir][2]
    if occupied(N, wx, wy) then return false end
    for _ = 1, 12 do joypad.set({ [dir] = true }); emu.frameadvance() end
    joypad.set({})
    ctx.frames(8)
    local nx, ny = ctx.G.pos(ctx.cp)
    return nx == wx and ny == wy
end

--- Route 1 grass -> the Center door (the boxsync walk) -> (7,4) -> west along row 4 to (3,4).
local function walk_to_npc(ctx, N)
    local SP, cp, play = ctx.SP, ctx.cp, ctx.play
    SP.return_to_grass_origin(cp, "trade a")
    play.follow(cp, "route1_grass_to_north_edge", "trade a")
    SP.warp_to(cp, "Up", 30, SP.DEST.viridian_south, "trade a Route1->Viridian")
    play.follow(cp, "route1_edge_to_pokecenter_door", "trade a")
    SP.warp_to(cp, "Up", 30, SP.DEST.center, "trade a Center door")
    play.follow(cp, "pokecenter_entrance_to_nurse", "trade a")      -- (7,8) -> (7,4)
    local deadline = os.time() + 120
    while os.time() < deadline do
        local x, y = ctx.G.pos(cp)
        if x == 3 and y == 4 then return true end
        if not step(ctx, N, "Left") then ctx.frames(16) end          -- a wanderer in the row: wait
    end
    return false, "never reached (3,4) on row 4"
end

--- Talk to the trade NPC where it stands NOW: from (3,4) it is at (3,3) (Up) or further in, in
--- which case step Up to (3,3) and meet it Up or Left. A is pressed only when the 0xF1 object
--- is on the faced tile, the player is idle and no script owns the field.
local function talk(ctx, N)
    local before = u8(N.PI_COUNT)
    local deadline = os.time() + 300
    while os.time() < deadline do
        local i = npc_slot(N)
        if i then
            local nx, ny = tile_of(N, i)
            local px, py = ctx.G.pos(ctx.cp)
            local dir = ADJ[(nx - px) .. "," .. (ny - py)]
            if dir then
                if face(ctx, N, dir) and u8(SC2) == 0 and player_idle(N) then
                    local mx, my = tile_of(N, i)
                    if mx == nx and my == ny then
                        joypad.set({ A = true }); emu.frameadvance(); joypad.set({})
                        ctx.frames(20)
                        if u8(N.PI_COUNT) ~= before then
                            ctx.log(ctx.fmt("TALKED npc=(%d,%d) player=(%d,%d) facing=%s pi_count=%d->%d",
                                            nx, ny, px, py, dir, before, u8(N.PI_COUNT)))
                            return true
                        end
                        -- anything else answered the press (a real NPC): close it, try again
                        while u8(SC2) ~= 0 do ctx.G.tap("B", 2, 20) end
                    end
                end
            elseif px == 3 and py == 4 then
                step(ctx, N, "Up")
            end
        end
        ctx.frames(8)
    end
    return false
end

--- Press `button` on the 16-frame cadence while `gate()` holds, until `done()`.
local function press_until(ctx, done, gate, button, secs, what)
    local n = 0
    return ctx.wait_until(function()
        if done() then return true end
        n = n + 1
        if n % 16 == 0 and gate() then
            joypad.set({ [button] = true }); emu.frameadvance(); joypad.set({})
        end
    end, secs, what)
end

--- A change-only trace of what the trade leg runs through (callback2, the field lock, the
--- script context, the companion beacon, the party count, gMain.inBattle), <= 80 lines.
local function tracer(ctx, N)
    local last, lines = nil, 0
    return function(tag)
        local st = ctx.fmt("cb2=%08X sc2=%d ctx=%d beacon=%d count=%d inbattle=%d phase=%s",
                           u32(N.GMAIN_CB2_PTR), u8(SC2), u8(0x03000EA8),
                           u32(N.BASE) == N.SIG and 1 or 0, u8(N.PARTY_COUNT_ADDR),
                           (u8(0x030030F0 + 0x439) & 2) >> 1, tostring(ctx.trade_phase()))
        if st ~= last and lines < 80 then
            lines = lines + 1
            ctx.log(ctx.fmt("TRACE %s frame=%d %s", tag or "", emu.framecount(), st))
            local _, _, facts = ctx.center_state()
            ctx.log("TRACE_REFUSED " .. table.concat(facts.bad, ","))
            if last and last:find("beacon=1") and st:find("beacon=0") then ctx.G.shot("trade_beacon_lost_" .. ctx.player) end
            last = st
        end
    end
end

--- The durable native trade on this side: A only while the producer owns the screen (its native
--- pre-save dialog or its scene), until the client's trade_done. Returns the report.
local function run_scene(ctx, N)
    local trace = tracer(ctx, N)
    local phase = function() return u32(N.TRADE_BASE + 0x48) end   -- shadow producer_phase
    if not ctx.wait_until(function() trace("wait"); return ctx.received("apply_prepare") > 0 end, 600,
                          "apply_prepare") then return nil, "no apply_prepare" end
    if not press_until(ctx, function() trace("prepare"); return ctx.sent("apply_ready") > 0 end,
                       function() return phase() == 1 end, "A", 600, "apply_ready") then
        return nil, "no apply_ready (producer phase " .. phase() .. ")"
    end
    local ready = ctx.last_sent("apply_ready")
    if not ready or ready.ok ~= true then return nil, "apply_ready refused the trade" end
    if not ctx.wait_until(function() trace("wait"); return ctx.received("apply_trade") > 0 end, 600,
                          "apply_trade") then return nil, "no apply_trade" end
    if not press_until(ctx, function() trace("scene"); return ctx.sent("trade_done") > 0 end,
                       function() return phase() == 3 end, "A", 900, "trade_done") then
        return nil, "no trade_done (client trade phase " .. tostring(ctx.trade_phase()) .. ")"
    end
    return ctx.last_sent("trade_done")
end

--- Wait up to `secs` for the FIRST show_choices, or the server's named refusal, that arrives
--- strictly AFTER `rx0` (a ctx.rx_count() snapshot taken right before the talk). Returns the rx
--- entry, or nil on timeout. The refusal is typed (OMP cx-bfa0a588 F1): an untagged msgbox. Every
--- server notice the walk can queue carries a `phone` tag (dead_zone, fallen, first_link), the
--- trade refusal never does (server/state.py _handle_trade_request). PHYSICAL live trade_decline_gen3_rr_as_a (card RR-FC-FIX): the walk to the NPC
--- crosses Route 1 grass, which can queue an unrelated msgbox first (server/state.py dz_text, "X
--- is a dead zone!" -- a wild-encounter notice, nothing to do with trade); the first version of
--- this fix checked ctx.received("msgbox") > 0 / ctx.rx_after(0, ...), counting from the start of
--- the whole receipt, and reported that stale notice as the trade refusal. Scoped to `rx0` so only
--- a real response to THIS request ever counts.
local function wait_trade_answer(ctx, rx0, secs)
    local function answered()
        return ctx.rx_after(rx0, function(m)
            return m.cmd == "show_choices" or (m.cmd == "msgbox" and m.phone == nil)
        end)
    end
    if not ctx.wait_until(function() return answered() ~= nil end, secs,
                          "show_choices or the unavailability msgbox") then
        return nil
    end
    return answered()
end

local function a_side(ctx, N, linked, partner, decline)
    local ok, why = walk_to_npc(ctx, N)
    if not ok then return false, why end
    if not ctx.wait_until(function() return npc_slot(N) end, 60, "the trade NPC spawned") then
        return false, "the trade NPC never spawned in the Center"
    end
    ctx.log("AT_NPC npc_oe=" .. npc_slot(N))
    -- rx0 BEFORE talk(), not after: PHYSICAL live trade_decline_gen3_rr_as_a (card RR-FC-FIX,
    -- second round) -- the patch sends trade_request in the SAME FRAME A talks (talk()'s own doc
    -- comment), and this run's own receipt shows the server's msgbox landing (line "RX msgbox
    -- text=Trade unavailable...") BEFORE talk() ever logs TALKED (gated on a LATER poll seeing
    -- pi_count move). A snapshot taken after talk() returns can already be past the real answer,
    -- which is exactly what turned into "TIMEOUT waiting for show_choices or the unavailability
    -- msgbox" here.
    local rx0 = ctx.rx_count()
    if not talk(ctx, N) then return false, "never talked to the trade NPC" end
    if not ctx.wait_sent("trade_request", nil, 60) then return false, "no trade_request after the talk" end
    -- The durable build trades (RR-DURABLE). The server's named refusal is only for an RR client
    -- without the witness (the old UPS); here it is a failure, logged with its text.
    local answer = wait_trade_answer(ctx, rx0, 120)
    if not answer then return false, "no show_choices" end
    if answer.cmd == "msgbox" then
        ctx.log("REFUSED_UNAVAILABLE reason=" .. tostring(answer.text))
        return false, "the server refused the trade: " .. tostring(answer.text)
    end
    -- the list is up once the script owns the field; A on its first row (Trade)
    if not ctx.wait_until(function() return u8(SC2) ~= 0 end, 60, "the choices script") then
        return false, "the Trade/Say hey list never opened"
    end
    press_until(ctx, function() return ctx.sent("menu_result") > 0 end,
                function() return u8(SC2) ~= 0 end, "A", 120, "menu_result")
    local choice = ctx.last_sent("menu_result")
    if not choice or choice.choice ~= 0 then return false, "the list answered " .. tostring(choice and choice.choice) end
    ctx.log("CHOSE_TRADE")
    if not ctx.wait_received("choose_mon", nil, 120) then return false, "no choose_mon" end
    local slot = ctx.find(linked).slot
    local ready = ctx.wait_until(function()
        return ctx.party_menu_up() and ctx.task_live("Task_HandleChooseMonInput")
    end, 120, "the party chooser")
    if not ready then return false, "the party chooser never took input" end
    local cursor = function() return u8(ctx.sym.gPartyMenu + 9) end   -- struct PartyMenu.slotId
    ctx.frames(60)                  -- the screen fades in before Task_HandleChooseMonInput reads keys
    -- pret party_menu.c UpdatePartySelectionSingleLayout: slot 0 is the left panel, RIGHT enters
    -- the right column (slot 1..), DOWN walks it. The party count byte is logged beside the
    -- cursor trail (RR profile ram.PARTY_COUNT_ADDR).
    local seen = {}
    for _ = 1, 12 do
        seen[#seen + 1] = cursor()
        if cursor() == slot then break end
        ctx.G.tap(cursor() == 0 and "Right" or (cursor() < slot and "Down" or "Up"), 3, 20)
    end
    ctx.log(ctx.fmt("PARTY_CURSOR %s party_count=%d", table.concat(seen, ","), u8(N.PARTY_COUNT_ADDR)))
    if cursor() ~= slot then return false, "the party cursor never reached slot " .. slot end
    press_until(ctx, function() return ctx.sent("mon_chosen") > 0 end,
                function() return not field_cb(N) end, "A", 120, "mon_chosen")
    local chosen = ctx.last_sent("mon_chosen")
    if not chosen or chosen.slot ~= slot then return false, "mon_chosen said " .. tostring(chosen and chosen.slot) end
    ctx.log("CHOSE_MON slot=" .. slot .. " key=" .. linked)
    if decline then
        -- typed like the refusal (F1): the server's decline notice is untagged; a dead-zone
        -- notice from the walk carries phone="dead_zone"
        local rx1 = ctx.rx_count()
        local told = ctx.wait_until(function()
            return ctx.rx_after(rx1, function(m)
                return m.cmd == "msgbox" and m.phone == nil and tostring(m.text):find("^Your partner declined")
            end)
        end, 900, "the decline notice")
        if not told then return false, "no decline notice" end
        if ctx.received("apply_prepare") > 0 or ctx.received("apply_trade") > 0 then
            return false, "a trade command arrived after the decline"
        end
        return true
    end
    local report, rwhy = run_scene(ctx, N)
    if not report then return false, rwhy end
    return true, report
end

local function b_side(ctx, N, decline)
    if not ctx.wait_received("show_menu", nil, 1500) then return false, "no offer (show_menu)" end
    if not ctx.wait_until(function() return u8(SC2) ~= 0 end, 120, "the YES/NO script") then
        return false, "the offer's YES/NO never opened"
    end
    local button = decline and "B" or "A"
    press_until(ctx, function() return ctx.sent("menu_result") > 0 end,
                function() return u8(SC2) ~= 0 end, button, 120, "menu_result")
    local answer = ctx.last_sent("menu_result")
    local want = decline and 0 or 1
    if not answer or answer.choice ~= want then
        return false, "the YES/NO answered " .. tostring(answer and answer.choice) .. ", not " .. want
    end
    ctx.log((decline and "DECLINED" or "ACCEPTED") .. " choice=" .. answer.choice)
    if decline then
        ctx.frames(600)
        if ctx.received("apply_prepare") > 0 or ctx.received("apply_trade") > 0 then
            return false, "a trade command arrived after a decline"
        end
        return true
    end
    local report, why = run_scene(ctx, N)
    if not report then return false, why end
    return true, report
end

return function(ctx)
    if not ctx.rr then return false, "trade_gen3 is the RR companion's PC trade NPC" end
    local decline = ctx.D.scenario == "trade_decline_gen3"
    local N = native_block(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local linked = ctx.linked()
    local partner
    local f = assert(io.open(ctx.D.go_file, "r"))
    for l in f:lines() do partner = l:match("^PARTNER (%S+)$") or partner end
    f:close()
    local mon = linked and ctx.find(linked)
    if not mon or not partner then return false, "go-file needs LINKED (in the party) and PARTNER" end
    local ok, report
    if ctx.player == "a" then ok, report = a_side(ctx, N, linked, partner, decline)
    else ok, report = b_side(ctx, N, decline) end
    if not ok then return false, report end
    if type(report) ~= "table" then
        -- nothing moved: the partner declined
        if not decline then return false, "no trade report" end
        if not ctx.find(linked) then return false, linked .. " left the party though the trade never completed" end
        if ctx.received("apply_trade") > 0 then return false, "apply_trade arrived though the trade never completed" end
        ctx.log("KEPT " .. linked .. " slot=" .. ctx.find(linked).slot)
    else
        if report.new_key ~= partner then
            return false, "trade_done new_key " .. tostring(report.new_key) .. ", expected " .. partner
        end
        -- the cartridge, not the client's word: the partner's mon in the party, ours nowhere
        local got = ctx.wait_until(function() return ctx.find(partner) end, 60, "the partner's mon")
        if not got then return false, partner .. " is not in the party after trade_done" end
        if ctx.find(linked) then return false, linked .. " is still in the party after the trade" end
        ctx.log(ctx.fmt("TRADED gave=%s got=%s slot=%d species=%d level=%d",
                        linked, partner, got.slot, got.species, got.level))
    end
    if not ctx.wait_go("SAVE", 1200) then return false, "the runner never released the SAVE" end
    local traded = type(report) == "table"
    local sok, swhy = ctx.save(traded and "trade" or "trade_decline")
    if not sok then return false, swhy end
    if traded then return true, "traded " .. linked .. " for " .. partner end
    return true, "declined; nothing moved"
end
