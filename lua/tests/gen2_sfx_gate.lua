--[[
  lua/tests/gen2_sfx_gate.lua -- card P4.2c: the PHYSICAL native-sound gate on the patched Gen 2 ROMs (the
  <title>_overlay cartridge, staged and sha1-checked by tools/run_gb_gate.py). Copies lua/tests/gen2_panel_gate.lua's
  frame: boot the qualified <title>_battle fixture warm (gen2_qualify.lua stage "boot"), bind the CLEAN facts to
  the verified overlay, then drive normal buttons only.

  The requests are posted by the SHIPPED binding (lua/gen2/panel.lua request_sfx -> lua/sfx_arbiter.lua ->
  gb_panel's queue -> mailbox +7), serviced every frame as the client does. patch/gen2/src/sfx.asm plays a code
  from the DelayFrame bridge only, holding it while wMusicFade runs or CheckSFX (ch5-8) is busy. A sound counts
  as PLAYED on the first frame one of wChannel5..8 has SOUND_CHANNEL_ON (Flags1 bit 0) and CHANNEL_MUSIC_ID ==
  the exact native id (C/G audio/engine.asm _PlaySFX -> LoadChannel stores wMusicID into every loaded channel;
  C constants/audio_constants.asm channel_struct). Every fact is WRAM read through the decomp; no ears, no vision.

  Contexts (per title), each with P.DEADLINE frames from post to the id on a channel:
    idle        the quiet overworld, all four codes: the exact-id table (SUCCESS $01 ITEM, FAILURE $19 WRONG,
                BOO $24 BUMP, NOTIFY $08 READ_TEXT_2)
    movement    posted while wWalkingDirection != STANDING, walking Route 29 east (source grid BFS, no grass)
    transition  the Route 29 -> New Bark connection's FadeToMapMusic (MapSetupScript_Connection): posted on the
                first frame wMusicFade != 0; must stay HELD (+7 unchanged) for the whole fade and play after it
    start_menu  the idle START menu (New Bark Town)
    text        START > SAVE: posted while "Would you like to / save the game?" is printing (PrintLetterDelay
                spins on wTextDelayFrames, no DelayFrame: C home/print_text.asm .wait); answered NO
    battle_anim a real wild battle: posted on the first BattleAnimDelayFrame frame (the send-out animation;
                OMP P41C F4: that wait never calls DelayFrame). Anim-wait frames and service visits while it is
                pending are counted.
    battle_menu the idle battle menu (then RUN)
    reset       the native chord; at Reset's entry the request byte is made pending (the client's own post, or
                the client writes it there). The SlinkResetSoundBridge latch (+12 = $FF) must drop it, and no
                PlaySFX with that id may run and no channel may carry it for P.REBOOT_WATCH frames after.
  A context that misses its deadline is FAIL and is card P4.2d's input (a GetJoypad second site, Codex).

  Environment: the panel gate's, plus SLINK_GEN2_SFX_FACTS from tests/live/test_gen2_sfx_gate.py (sites and RAM
  from data/gen2/<title>_slink.sym, native ids from the decomp's constants/sfx_constants.asm).
  Result file: patch/build/gen2_sfx_gate_result.txt. Printed: CASE (one per context), RESET, RECEIPT (json after
  the tag); RESULT: PASS|FAIL last.
--]]
local P = {}
P.RESULT = "patch/build/gen2_sfx_gate_result.txt"
P.SCRIPTED_GATE = "lua/tests/test_gen2_scripted_gate.lua"
P.FRAME_ALIGN = "lua/tests/gen2_frame_align.lua"
P.SCHEMA = "gen2-sfx-gate-v1"
P.CAPS = 0x07                      -- PANEL | SFX | SFX_NOTIFY (patch/gen2/src/slink.asm)
P.OFF_SFX, P.OFF_HOLD, P.OFF_HOLD_AT = 7, 12, 13     -- patch/gb/slink_abi.inc
P.RESET_BLOCKED = 0xFF             -- sfx.asm SLINK_SFX_RESET_BLOCKED
P.STANDING = 0xFF                  -- wWalkingDirection STANDING (-1)
P.SOUND_CHANNEL_ON = 0x01          -- Flags1 bit 0; Flags1 is channel_struct +3
-- The Gen 1 bound on the DelayFrame bridge alone (patch/gen1/README.md:52-55, docs/gen2/GEN2_BINDING_PLAN.md P4.2).
P.DEADLINE = 300
P.QUIET_BOUND = 900
P.REBOOT_WATCH = 900
P.HOLD, P.REST = 12, 8
P.OPEN_BOUND = 600
P.CODES = {SUCCESS=1, FAILURE=2, BOO=3, NOTIFY=4}
P.WALK_BUDGET = 6000
P.BATTLE_BUDGET = {max_frames=40000, max_phase_frames=20000, settle_frames=30}

local fmt = string.format
P.DIRS = {{"Up", 0, -1}, {"Left", -1, 0}, {"Down", 0, 1}, {"Right", 1, 0}}

-- Pure: the channel base (of `bases`) carrying `id` with SOUND_CHANNEL_ON, or nil.
function P.playing(read, bases, id)
    for i, base in ipairs(bases) do
        if read(base + 3) & P.SOUND_CHANNEL_ON ~= 0 and read(base) == id and read(base + 1) == 0 then return i + 4 end
    end
end

-- Pure: BFS over a source grid (0 wall, 1 floor, 2 grass) from (x, y) to the first tile goal(x, y) accepts,
-- never through grass (a wild battle mid-context) unless `grass_goal`, where only the goal may be grass.
-- Returns the first direction name, the path length, or nil.
function P.first_step(map, x, y, goal, grass_goal)
    local w, h = map.width, map.height
    local function cell(cx, cy) return map.grid[cy * w + cx + 1] end
    local seen, queue, head = {[y * w + x] = true}, {{x, y, nil, 0}}, 1
    while queue[head] do
        local cx, cy, first, n = queue[head][1], queue[head][2], queue[head][3], queue[head][4]
        head = head + 1
        if n > 0 and goal(cx, cy) then return first, n end
        for _, d in ipairs(P.DIRS) do
            local nx, ny = cx + d[2], cy + d[3]
            if nx >= 0 and nx < w and ny >= 0 and ny < h and not seen[ny * w + nx] then
                local c = cell(nx, ny)
                if c == 1 or (c == 2 and grass_goal and goal(nx, ny)) then
                    seen[ny * w + nx] = true
                    queue[#queue + 1] = {nx, ny, first or d[1], n + 1}
                end
            end
        end
    end
end

-- Pure: the verdict of one context case; nil = PASS.
function P.problem(c, deadline)
    if not c.accepted then return "the binding refused the request (sfx_present false?)" end
    if not c.posted then return "the request never reached mailbox +7" end
    if c.pre_playing then return "the id was already on a channel when posted: attribution lost" end
    if not c.played then
        return fmt("id $%02X never on ch5-8 within %d frames (consumed %s)", c.id, deadline, tostring(c.consumed))
    end
    if c.consumed == nil or c.played < c.consumed then return "a channel carried the id before the ROM consumed +7" end
    if c.watch_fade then
        if not c.fade_at_post or c.fade_at_post == 0 then return "not posted inside the music fade" end
        if c.dropped_in_fade then return "the request left +7 while the fade was still running (dropped, not held)" end
        if not c.fade_end then return "the fade never ended" end
        if c.played < c.fade_end then return "played during the fade" end
        if c.played - c.fade_end > deadline then return fmt("played %d frames after the fade", c.played - c.fade_end) end
        return nil
    end
    if c.played - c.posted > deadline then return fmt("latency %d > %d frames", c.played - c.posted, deadline) end
end

function P.scripted_gate(root)
    local previous = SLINK_GEN2_GATE_LIBRARY
    SLINK_GEN2_GATE_LIBRARY = true
    local ok, SG = pcall(dofile, root .. "/" .. P.SCRIPTED_GATE)
    local ok2, F = pcall(dofile, root .. "/" .. P.FRAME_ALIGN)
    SLINK_GEN2_GATE_LIBRARY = previous
    assert(ok and type(SG) == "table", "cannot load " .. P.SCRIPTED_GATE .. ": " .. tostring(SG))
    assert(ok2 and type(F) == "table", "cannot load " .. P.FRAME_ALIGN .. ": " .. tostring(F))
    return SG, F
end

function P.main(real, getenv, SG, F)
    local evidence = (live_api ~= nil and real == live_api) and "PHYSICAL" or "MODEL"
    local root = getenv("SLINK_ROOT") or SLINK_ROOT or "."
    local lines, failures = {}, 0
    local function log(s)
        lines[#lines + 1] = s
        local f = io.open(root .. "/" .. P.RESULT, "w")
        if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    end
    local function check(what, ok, detail)
        if not ok then failures = failures + 1 end
        log(fmt("  [%s] %s%s", ok and "ok" or "FAIL", what, detail and ("  -- " .. tostring(detail)) or ""))
        return ok
    end
    local function finish(extra)
        log(fmt("RESULT: %s %s (%d checks failed)", failures == 0 and "PASS" or "FAIL", extra or "sfx", failures))
        return failures == 0
    end
    log(fmt("[gen2_sfx_gate] P4.2c %s overlay native sound", tostring(getenv("SLINK_GEN2_TITLE"))))

    local on_frame = function() end
    local api = setmetatable({advance=function() real.advance(); on_frame() end}, {__index=real})

    local ok, ctx = pcall(function()
        if not SG or not F then SG, F = P.scripted_gate(root) end
        local json = dofile(root .. "/lua/json_codec.lua")
        local overlay_sha1 = assert(getenv("SLINK_GEN2_OVERLAY_SHA1"), "SLINK_GEN2_OVERLAY_SHA1 missing"):lower()
        local f = assert(io.open(root .. "/data/games/gen2_" .. getenv("SLINK_GEN2_TITLE") .. "/profile.json", "rb"))
        local wrapper = assert(json.decode(f:read("a"), {items=1000000}))
        f:close()
        local ov = wrapper.titles[getenv("SLINK_GEN2_TITLE")].overlay
        assert(type(ov) == "table" and ov.rom_sha1 == overlay_sha1 and ov.base_sha1 == getenv("SLINK_GEN2_ROM_SHA1"),
               "profile overlay block differs from the staged overlay")
        assert(real.romhash():lower() == overlay_sha1, "running ROM is not the staged overlay")
        local view = setmetatable({romhash=function() return ov.base_sha1 end}, {__index=api})
        local c = SG.context(view, getenv)
        assert(c.case.name == c.env.title .. "_battle", "the sfx gate runs on <title>_battle")
        assert(c.qualify ~= nil and c.qualify.stage == "boot", "SLINK_GEN2_QUALIFY stage \"boot\" required")
        c.sfx_facts = assert(c.json.decode(assert(getenv("SLINK_GEN2_SFX_FACTS"), "SLINK_GEN2_SFX_FACTS missing")))
        assert(c.sfx_facts.overlay_sha1 == overlay_sha1, "sfx facts belong to another overlay")
        c.overlay, c.overlay_sha1 = ov, overlay_sha1
        return c
    end)
    if not check("environment, clean facts and the running overlay ROM bound", ok, not ok and ctx or nil) then
        return finish("bad environment")
    end
    ctx.log = log
    local json, title, sf, ov = ctx.json, ctx.env.title, ctx.sfx_facts, ctx.overlay
    local function J(value) return assert(json.encode(value)) end
    local MB = ov.ram.wSlinkMailbox
    local function u8(addr) return api.read_u8(addr, "System Bus") end
    local function wram1(site) return api.read_range(SG.wram_offset(site.bank, site.addr, 1), 1, "WRAM")[1] end
    local frame = api.framecount
    local CH = {sf.ram.wChannel5.addr, sf.ram.wChannel6.addr, sf.ram.wChannel7.addr, sf.ram.wChannel8.addr}
    local FADE, CUR_SFX = sf.ram.wMusicFade.addr, sf.ram.wCurSFX.addr
    local SOUND = {}
    for code, id in pairs(sf.sounds) do SOUND[tonumber(code)] = id end
    local function on_channel(id) return P.playing(u8, CH, id) end
    local function channels_quiet()
        for _, base in ipairs(CH) do if u8(base + 3) & P.SOUND_CHANNEL_ON ~= 0 then return false end end
        return true
    end

    -- ── hooks: SG's UI origins + the sound sites (bytes re-validated against the overlay) ─────────────
    local state = SG.hooks(ctx)
    local binding = ctx.Binding.new({read_u8=api.read_u8, read_range=api.read_range, register=api.register,
        framecount=api.framecount, on_bus_exec=api.on_bus_exec, unregister=api.unregister},
        {bus_domain="System Bus", rom_domain="ROM", bank_domain="System Bus", pc_register="PC", sp_register="SP",
         bank_address=ctx.profile.hram.hROMBank})
    local hits, handles, hook_errors, on_hit = {}, {}, {}, {}
    local function watch(id)
        local site = assert(sf.sites[id], "sfx facts lack site " .. id)
        local valid = binding:validate({id=id, bank=site.bank, address=site.addr, expected_hex=site.hex,
                                        capture_offset=0, rom_offset=site.flat})
        hits[id] = {}
        local handle = binding:register(valid, function()
            local okc, hit = pcall(binding.context, binding, valid)
            if not okc then hook_errors[#hook_errors + 1] = tostring(hit) return end
            if hit then
                local list = hits[id]
                if list[#list] ~= hit.frame then list[#list + 1] = hit.frame end
                if #list > 4000 then table.remove(list, 1) end
                if on_hit[id] then
                    local okh, why = pcall(on_hit[id], hit.frame)
                    if not okh then hook_errors[#hook_errors + 1] = id .. ": " .. tostring(why) end
                end
            end
        end, "SLink-p42c-" .. id)
        assert(binding:valid_handle(handle), id .. ": hook registration failed")
        handles[#handles + 1] = handle
    end
    local hooked, hook_why = pcall(function()
        for _, id in ipairs({"BattleAnimDelayFrame", "PlaySFX", "Reset", "SlinkSfxService"}) do watch(id) end
    end)
    local function release()
        for _, h in ipairs(handles) do pcall(api.unregister, h) end
        handles = {}
        state.release()
    end
    if not check("overlay sound sites bind on the running ROM", hooked, not hooked and hook_why or nil) then
        release()
        return finish("no hooks")
    end
    -- The longest stretch of frames in [from, to] with no service visit: the worst latency any request
    -- posted in that window could see on quiet channels (OMP P41C F4's battle-animation worst case).
    local function service_gap(from, to)
        local last, worst = from, 0
        for _, f in ipairs(hits.SlinkSfxService) do
            if f >= from and f <= to then
                if f - last > worst then worst = f - last end
                last = f
            end
        end
        return math.max(worst, to - last)
    end
    local function count_since(id, from)
        local n = 0
        for _, f in ipairs(hits[id]) do if f > from then n = n + 1 end end
        return n
    end

    -- ── arrival ──────────────────────────────────────────────────────────────────────────────────
    local idle_buttons = {}
    for _, name in ipairs(SG.BUTTONS) do idle_buttons[name] = false end
    local host = ctx.Host.new({step=SG.button_step(ctx), frame=api.framecount, idle=idle_buttons})
    local case, q = ctx.case, ctx.qualify
    local arrived, result = pcall(ctx.Qualify.run, host, SG.qualify_observer(ctx), ctx.facts, q.facts,
        {name=case.name, title=case.title, attempt_id=case.attempt_id, stage="boot",
         stage_fingerprint=q.stage_fingerprint, max_frames=case.max_frames,
         max_phase_frames=case.max_phase_frames, settle_frames=case.settle_frames})
    if not check("post-CONTINUE overworld arrival on the overlay", arrived, not arrived and result or nil) then
        release()
        return finish("no arrival")
    end

    -- ── the shipped binding, serviced every frame; the case monitor ──────────────────────────────
    local Panel = dofile(root .. "/lua/gen2/panel.lua")
    local Permit = dofile(root .. "/lua/write_permit.lua")
    local HUD = dofile(root .. "/lua/hud.lua")
    local io_ = {read_u8=function(addr) return api.read_u8(addr, "System Bus") end, framecount=api.framecount,
                 write_u8=function(addr, value, domain) api.write_u8(addr, value, domain) end}
    local writes = Panel.writes(io_, Permit)
    local panel = assert(Panel.new(ctx.profile, ctx.charmap, io_, writes, HUD.sanitize))
    local cases, cur = {}, nil
    local client = true
    on_frame = function()
        if client then
            local served, why = panel:service()
            if not served then hook_errors[#hook_errors + 1] = "panel service: " .. tostring(why) end
        end
        local c = cur
        if not c or c.done then return end
        local f, req, fade = frame(), u8(MB + P.OFF_SFX), u8(FADE)
        if not c.posted then
            if req == c.code then c.posted, c.fade_at_post = f, fade end
            return
        end
        if not c.consumed and req ~= c.code then c.consumed, c.hold_at_consume = f, u8(MB + P.OFF_HOLD_AT) end
        if not c.consumed then
            c.anim_frames = count_since("BattleAnimDelayFrame", c.posted)
            c.service_visits = count_since("SlinkSfxService", c.posted)
        end
        if c.watch_fade then
            if fade ~= 0 then
                c.fade_frames = c.fade_frames + 1
                if req ~= c.code then c.dropped_in_fade = true end
            elseif c.fade_frames > 0 and not c.fade_end then
                c.fade_end = f
            end
        end
        if not c.played then
            local ch = on_channel(c.id)
            if ch then c.played, c.channel, c.cur_sfx = f, ch, u8(CUR_SFX) end
        end
    end
    local function arm(name, code, extra)
        local c = {name=name, code=code, id=SOUND[code], armed=frame(), fade_frames=0}
        for k, v in pairs(extra or {}) do c[k] = v end
        c.pre_playing = on_channel(c.id) ~= nil
        c.accepted = panel:request_sfx(code)
        cases[#cases + 1], cur = c, c
        return c
    end
    local function close(c)
        c.done = true
        if cur == c then cur = nil end
        local why = P.problem(c, P.DEADLINE)
        c.latency = c.played and c.posted and c.played - c.posted or json.null
        check(fmt("%s: code %d -> $%02X on ch5-8 within %d frames", c.name, c.code, c.id or -1, P.DEADLINE), why == nil,
              why or fmt("latency %s, channel %s, visits %s, anim frames %s", tostring(c.latency), tostring(c.channel),
                         tostring(c.service_visits), tostring(c.anim_frames)))
        c.result = why == nil and "PASS" or "FAIL"
        c.problem = why
        log("CASE " .. J({context=c.name, code=c.code, id=c.id, accepted=c.accepted, posted=c.posted or json.null,
            consumed=c.consumed or json.null, played=c.played or json.null, latency=c.latency,
            channel=c.channel or json.null, cur_sfx=c.cur_sfx or json.null, pre_playing=c.pre_playing,
            service_visits=c.service_visits or json.null, anim_frames=c.anim_frames or json.null,
            fade_at_post=c.fade_at_post or json.null, fade_frames=c.fade_frames, fade_end=c.fade_end or json.null,
            dropped_in_fade=c.dropped_in_fade or false, printing=c.printing == nil and json.null or c.printing,
            result=c.result, problem=why or json.null}))
    end

    -- ── primitives ───────────────────────────────────────────────────────────────────────────────
    local function step(buttons)
        local b = {}
        for k in pairs(idle_buttons) do b[k] = false end
        for k, v in pairs(buttons or {}) do b[k] = v end
        api.set_buttons(b)
        api.advance()
    end
    local function idle(n) for _ = 1, n do step() end end
    local function press(button, hold)
        for _ = 1, hold or P.HOLD do step({[button]=true}) end
        idle(P.REST)
    end
    local function wait(pred, n)
        for _ = 1, n do
            if pred() then return true end
            step()
        end
        return pred() and true or false
    end
    local function rows() return SG.screen(ctx) end
    local function on_screen(needle)
        for _, row in ipairs(rows()) do if table.concat(row):find(needle, 1, true) then return true end end
        return false
    end
    local function dump(tag)
        for y, row in ipairs(rows()) do log(fmt("  %s %02d |%s|", tag, y - 1, table.concat(row))) end
    end
    local function menu()
        local m = SG.parse_menu(rows(), ctx.obs.screen.width, ctx.obs.screen.height)
        if m and m.columns == 1 then return m end
    end
    local function menu_up() local m = menu() return m ~= nil and m.items[#m.items] == "SLINK" end
    local function overworld()
        local t, u = state.tick, state.ui
        return t ~= nil and frame() - t.frame <= 2 and (u == nil or t.seq > u.seq) and not menu_up()
    end
    local function open_menu()
        for _ = 1, 6 do
            if menu_up() then idle(20) return true end
            if overworld() then press("Start") end
            if wait(menu_up, 90) then idle(20) return true end
        end
        return menu_up()
    end
    local function to_overworld()
        for _ = 1, 8 do
            if wait(overworld, 60) then return true end
            if menu_up() then press("B") end
        end
        return wait(overworld, 120)
    end
    local function cursor_to(label)
        for _ = 1, 12 do
            local m = menu()
            if m and m.items[m.cursor] == label then return true end
            press("Up")
            wait(menu_up, 30)
        end
        return false
    end
    local function quiet() return channels_quiet() and u8(MB + P.OFF_SFX) == 0 and u8(FADE) == 0 end
    local function settle(c, buttons)
        for _ = 1, P.DEADLINE + 60 do
            if c.played and (not c.watch_fade or c.fade_end) then break end
            step(buttons and buttons() or nil)
        end
        close(c)
    end
    local obs = SG.qualify_observer(ctx)
    local maps = ctx.facts.maps
    local function map_is(point, name)
        local m = maps[name]
        return point.map_group == m.map_group and point.map_number == m.map_number
    end
    local function walking() return wram1(sf.ram.wWalkingDirection) ~= P.STANDING end

    local play_ok, play_why = pcall(function()
        check("mailbox beacon SLNK, ABI 3, caps 7, cookie $A5",
              u8(MB) == 0x53 and u8(MB + 1) == 0x4C and u8(MB + 2) == 0x4E and u8(MB + 3) == 0x4B
              and u8(MB + 4) == 3 and u8(MB + 8) == P.CAPS and u8(MB + 31) == 0xA5,
              fmt("abi=%d caps=%02X cookie=%02X", u8(MB + 4), u8(MB + 8), u8(MB + 31)))
        idle(2)
        check("the shipped binding reads the cartridge SFX-live", panel:sfx_present() == true and panel:fresh() == true)

        -- idle: the table, one code at a time in the quiet overworld
        for code = 1, 4 do
            check("quiet before idle code " .. code, wait(quiet, P.QUIET_BOUND))
            settle(arm("idle_" .. code, code))
        end

        -- movement + transition: walk Route 29 east to New Bark Town (no grass), post mid-step; the
        -- connection's FadeToMapMusic is the transition.
        check("quiet before the walk", wait(quiet, P.QUIET_BOUND))
        local R29 = maps.Route29
        local east = function(x) return x == R29.width - 1 end
        local move_case, fade_case, start_xy, crossed, crossed_at
        for _ = 1, P.WALK_BUDGET do
            local point = obs()
            if not start_xy and point.x then start_xy = {point.x, point.y} end
            if type(point.battle_mode) == "number" and point.battle_mode > 0 then error("a battle started on the walk") end
            if not fade_case and u8(FADE) ~= 0 and (type(move_case) ~= "table" or move_case.done) then
                fade_case = arm("transition", P.CODES.SUCCESS, {watch_fade=true})
            end
            if map_is(point, "NewBarkTown") then crossed, crossed_at = true, crossed_at or frame() end
            if crossed and ((fade_case and fade_case.done) or (not fade_case and frame() - crossed_at > 120)) then break end
            if fade_case and not fade_case.done and (fade_case.played and fade_case.fade_end
                or (fade_case.fade_end and frame() - fade_case.fade_end > P.DEADLINE)
                or frame() - fade_case.armed > P.DEADLINE * 3) then
                close(fade_case)
            end
            local buttons = {}
            if not crossed and point.overworld_ready and map_is(point, "Route29") then
                if east(point.x) then
                    buttons = {Right=true}
                else
                    local dir, n = P.first_step(R29, point.x, point.y, function(x) return east(x) end)
                    if not dir then error(fmt("no grass-free path east from %d,%d", point.x, point.y)) end
                    if point.can_step[dir] ~= true then error(fmt("source path %s from %d,%d is not steppable live", dir, point.x, point.y)) end
                    buttons = {[dir]=true}
                    if not move_case and n >= 3 and (point.x ~= start_xy[1] or point.y ~= start_xy[2]) then
                        move_case = "arm"
                    end
                end
            end
            if move_case == "arm" and walking() and channels_quiet() then
                move_case = arm("movement", P.CODES.FAILURE, {walking_at_post=true})
            end
            step(buttons)
            if type(move_case) == "table" and not move_case.done and (move_case.played or frame() - move_case.armed > P.DEADLINE + 30) then
                close(move_case)
            end
        end
        if type(move_case) == "table" and not move_case.done then close(move_case) end
        check("movement context exercised (posted mid-step)", type(move_case) == "table")
        check("crossed into New Bark Town with a music fade", crossed and fade_case ~= nil,
              fmt("crossed %s fade_case %s", tostring(crossed), tostring(fade_case ~= nil)))
        if fade_case and not fade_case.done then close(fade_case) end

        -- idle START menu
        check("back in the overworld in New Bark", to_overworld())
        check("START opens the menu", open_menu())
        idle(30)
        check("quiet in the START menu", wait(quiet, P.QUIET_BOUND))
        settle(arm("start_menu", P.CODES.BOO))

        -- text: START > SAVE, posted while the question prints
        check("cursor on SAVE", cursor_to("SAVE"))
        wait(quiet, P.QUIET_BOUND)
        for _ = 1, 4 do step({A=true}) end
        local text_case
        for _ = 1, P.OPEN_BOUND do
            if on_screen("Would") then
                text_case = arm("text", P.CODES.SUCCESS, {printing=not on_screen("the game?")})
                break
            end
            step()
        end
        check("the save question appeared", text_case ~= nil)
        if text_case then settle(text_case) end
        dump("text")
        check("the YES/NO box is up", wait(function() return state.ui ~= nil and state.ui.kind == "yes_no" end, P.OPEN_BOUND))
        idle(20)
        press("B")                                   -- NO: nothing is saved
        check("back to the overworld after declining the save", to_overworld())

        -- battle: back west into Route 29, onto the grass, a wild battle
        local anim_case, menu_case, ran = nil, nil, false
        on_hit.BattleAnimDelayFrame = function()
            if not anim_case and ran == false and cur == nil then anim_case = "arm" end
        end
        local here, from_tile = nil, nil
        local HOLDF, held, hold_left, release_next = 12, nil, 0, false
        local driver = {phase="west", terminal="done"}
        local function tap(b) release_next, held, hold_left = true, b, HOLDF - 1 return {[b]=true}, driver.phase end
        function driver.step(point)
            if anim_case == "arm" then anim_case = arm("battle_anim", P.CODES.SUCCESS) end
            if type(anim_case) == "table" and not anim_case.done and (anim_case.played or frame() - anim_case.armed > P.DEADLINE + 30) then
                close(anim_case)
            end
            if type(menu_case) == "table" and not menu_case.done and (menu_case.played or frame() - menu_case.armed > P.DEADLINE + 30) then
                close(menu_case)
            end
            if hold_left > 0 then hold_left = hold_left - 1 return {[held]=true}, driver.phase end
            if release_next then release_next = false return {}, driver.phase end
            if driver.phase == "done" then return {}, "done" end
            if driver.phase ~= "battle" and type(point.battle_mode) == "number" and point.battle_mode > 0 then
                driver.phase, driver.battle_from = "battle", frame()
            end
            local ui = point.ui
            if ui ~= nil then
                if point.input_ready ~= true then return {}, driver.phase end
                if driver.phase ~= "battle" then return nil, "UI outside the battle: " .. tostring(ui.kind) end
                if ui.kind == "battle_menu" then
                    if type(ui.items) ~= "table" then return {}, driver.phase end
                    if (type(anim_case) == "table" and not anim_case.done) then return {}, driver.phase end
                    if menu_case == nil then
                        menu_case = {waiting=frame()}
                    end
                    if menu_case.waiting then
                        if quiet() or frame() - menu_case.waiting > P.QUIET_BOUND then menu_case = arm("battle_menu", P.CODES.NOTIFY) end
                        return {}, driver.phase
                    end
                    if not menu_case.done then return {}, driver.phase end
                    local run
                    for i, l in ipairs(ui.items) do if l == "RUN" then run = i end end
                    if not run then return nil, "no RUN on the battle menu" end
                    ran = true
                    if run == ui.cursor then return tap("A") end
                    local tx, cx = (run - 1) % 2, (ui.cursor - 1) % 2
                    if tx ~= cx then return tap(tx > cx and "Right" or "Left") end
                    return tap(run > ui.cursor and "Down" or "Up")
                end
                if ui.kind == "text" or ui.kind == "prompt_button" or ui.kind == "wait_button" then return tap("A") end
                return nil, "UI is not valid in battle: " .. tostring(ui.kind)
            end
            if point.overworld_ready ~= true then return {}, driver.phase end
            if driver.phase == "battle" then driver.phase, driver.battle_to = "done", frame() return {}, "done" end
            if driver.phase == "west" then
                if map_is(point, "Route29") then driver.phase = "approach" else return {Left=true}, driver.phase end
            end
            local grid = R29.grid
            if driver.phase == "approach" then
                if grid[point.y * R29.width + point.x + 1] == 2 then driver.phase = "walk"
                else
                    local dir = P.first_step(R29, point.x, point.y, function(x, y) return grid[y * R29.width + x + 1] == 2 end, true)
                    if not dir then return nil, "no path to the Route 29 grass" end
                    if point.can_step[dir] ~= true then return nil, "approach step " .. dir .. " not steppable live" end
                    return {[dir]=true}, driver.phase
                end
            end
            if here and (here.x ~= point.x or here.y ~= point.y) then from_tile = here end
            here = {x=point.x, y=point.y}
            local b, w = F.walk_direction(R29, point, from_tile)
            if not b then return nil, w end
            return {[b]=true}, driver.phase
        end
        local base_obs = SG.qualify_observer(ctx)
        local function observe()
            local point = base_obs()
            if point.ui and point.ui.kind == "battle_menu" then
                local bm = SG.parse_menu(SG.screen(ctx), ctx.obs.screen.width, ctx.obs.screen.height, SG.BATTLE_MENU_GRID)
                if bm then point.ui.items, point.ui.cursor, point.ui.columns = bm.items, bm.cursor, bm.columns
                else point.input_ready = false end
            end
            return point
        end
        local diag = {log=log, frame=api.framecount, screen=rows, where=function() return fmt("PC %04X", api.register("PC")) end,
                      trace=getenv("SLINK_GEN2_TRACE") == "1"}
        local battled, outcome = F.play(host, {name="p42c-battle-" .. title, terminal="done",
            max_frames=P.BATTLE_BUDGET.max_frames, max_phase_frames=P.BATTLE_BUDGET.max_phase_frames,
            settle_frames=P.BATTLE_BUDGET.settle_frames, terminal_idle=true}, driver, observe, diag)
        on_hit.BattleAnimDelayFrame = nil
        check("a real wild battle (walk the grass, RUN) back to the overworld", battled and ran, not battled and outcome or nil)
        check("battle animation wait observed and a request posted inside it", type(anim_case) == "table")
        check("battle menu context exercised", type(menu_case) == "table" and menu_case.name == "battle_menu")
        if driver.battle_from and driver.battle_to and type(anim_case) == "table" then
            anim_case.battle_service_gap = service_gap(driver.battle_from, driver.battle_to)
            anim_case.battle_anim_frames = count_since("BattleAnimDelayFrame", driver.battle_from - 1)
            check("battle worst case: the longest no-service stretch of the whole battle is within the deadline",
                  anim_case.battle_service_gap <= P.DEADLINE,
                  fmt("%d frames (battle %d..%d, %d anim-wait frames)", anim_case.battle_service_gap, driver.battle_from,
                      driver.battle_to, anim_case.battle_anim_frames))
        else
            check("battle worst case measured", false, "no battle window")
        end
        for _, c in ipairs({anim_case, menu_case}) do if type(c) == "table" and not c.done then close(c) end end
    end)
    check("scripted play completed", play_ok, not play_ok and play_why or nil)
    if cur and not cur.done then close(cur) end

    -- ── reset: a pending request is dropped by the latch, nothing plays after reboot ───────────────
    local reset = {code=P.CODES.FAILURE}
    local reset_ok, reset_why = pcall(function()
        reset.id = SOUND[reset.code]
        to_overworld()
        check("quiet before the reset", wait(quiet, P.QUIET_BOUND))
        on_hit.Reset = function(f)
            if reset.entry then return end
            reset.entry = f
            reset.req_at_entry = u8(MB + P.OFF_SFX)
            if reset.req_at_entry == 0 then
                -- the client's own window and bytes: a host post landing during Reset (sfx.asm's latch comment)
                writes:arm("panel", panel.allow)
                local okw, why = pcall(function() writes:write_bytes(MB + P.OFF_SFX, {reset.code}) end)
                writes:disarm()
                if not okw then error(why, 0) end
                reset.client_wrote_at_entry = true
            end
            reset.pending_at_entry = u8(MB + P.OFF_SFX) == reset.code
        end
        on_hit.PlaySFX = function(f)
            if reset.entry and f >= reset.entry then
                local e = api.register("E")
                reset.after = reset.after or {}
                reset.after[#reset.after + 1] = e
                if e == reset.id then reset.played_id = f end
            end
        end
        -- Make the client's own post pending: open START (its native SFX_MENU busies ch5-8), post while the
        -- service HOLDS it, then the chord. If the service still played it first, the client writes the
        -- request at Reset's entry instead (on_hit.Reset): either way a request is pending when Reset runs.
        press("Start", 2)
        wait(function() return not channels_quiet() end, 60)
        reset.client_accepted = panel:request_sfx(reset.code)
        step()
        reset.held_before_chord = u8(MB + P.OFF_SFX) == reset.code
        client = false                               -- no further client service across the reset
        local chord = {A=true, B=true, Select=true, Start=true}
        for _ = 1, 4 do step(chord) end
        for _ = 1, P.REBOOT_WATCH do
            step()
            if reset.entry then
                local hold, req = u8(MB + P.OFF_HOLD), u8(MB + P.OFF_SFX)
                if hold == P.RESET_BLOCKED then
                    reset.latched = reset.latched or frame()
                    if req == 0 and not reset.dropped then reset.dropped = frame() end
                end
                if on_channel(reset.id) then reset.on_channel = reset.on_channel or frame() end
                if not reset.cleared and req == 0 and frame() > reset.entry then reset.cleared = frame() end
            end
        end
        on_hit.Reset, on_hit.PlaySFX = nil, nil
        check("Reset entered from the native chord", reset.entry ~= nil)
        check("a request was pending at Reset's entry", reset.pending_at_entry == true,
              fmt("req at entry %s, client wrote %s", tostring(reset.req_at_entry), tostring(reset.client_wrote_at_entry)))
        check("the reset latch ($FF at +12) was seen and dropped the request",
              reset.latched ~= nil and reset.dropped ~= nil, fmt("latched %s dropped %s", tostring(reset.latched), tostring(reset.dropped)))
        check(fmt("no PlaySFX $%02X and no channel carrying it for %d frames after the reset", reset.id, P.REBOOT_WATCH),
              reset.played_id == nil and reset.on_channel == nil,
              fmt("PlaySFX %s channel %s", tostring(reset.played_id), tostring(reset.on_channel)))
    end)
    check("reset drop completed", reset_ok, not reset_ok and reset_why or nil)
    local distinct = {}
    for _, e in ipairs(reset.after or {}) do distinct[e] = true end
    local after_ids = {}
    for e in pairs(distinct) do after_ids[#after_ids + 1] = e end
    table.sort(after_ids)
    local reset_out = {code=reset.code, id=reset.id or json.null, client_accepted=reset.client_accepted or false,
        entry=reset.entry or json.null, req_at_entry=reset.req_at_entry or json.null,
        held_before_chord=reset.held_before_chord or false,
        client_wrote_at_entry=reset.client_wrote_at_entry or false, pending_at_entry=reset.pending_at_entry or false,
        latched=reset.latched or json.null, dropped=reset.dropped or json.null,
        played_id=reset.played_id or json.null, on_channel=reset.on_channel or json.null,
        watch_frames=P.REBOOT_WATCH, playsfx_ids_after=json.array(after_ids),
        result=(reset.pending_at_entry and reset.latched and reset.dropped and not reset.played_id
                and not reset.on_channel) and "PASS" or "FAIL"}
    log("RESET " .. J(reset_out))
    check("no hook or binding-service fault", #hook_errors == 0, hook_errors[1])
    release()

    local contexts = {}
    for _, c in ipairs(cases) do
        contexts[c.name] = {code=c.code, id=c.id, posted=c.posted or json.null, consumed=c.consumed or json.null,
            played=c.played or json.null, latency=c.latency, channel=c.channel or json.null,
            service_visits=c.service_visits or json.null, anim_frames=c.anim_frames or json.null,
            fade_frames=c.fade_frames, fade_end=c.fade_end or json.null, result=c.result,
            printing=c.printing == nil and json.null or c.printing,
            battle_service_gap=c.battle_service_gap or json.null, battle_anim_frames=c.battle_anim_frames or json.null}
    end
    if failures == 0 then
        local sounds = {}
        for code, id in pairs(SOUND) do sounds[tostring(code)] = id end
        log("RECEIPT " .. J({schema=P.SCHEMA, title=title, evidence_level=evidence, result="PASS",
            overlay_sha1=ctx.overlay_sha1, base_sha1=ov.base_sha1, fixture=case.name, fixture_sha256=q.stage_fingerprint,
            qualification_attempt_id=getenv("SLINK_GEN2_QUALIFICATION_ATTEMPT") or json.null, core_mode="CGB",
            input_mode="normal_buttons", harness_write_scopes=json.array({}),
            client_write_scope="sfx (lua/gen2/panel.lua permit, mailbox +7)", deadline_frames=P.DEADLINE,
            sounds=sounds, contexts=contexts, reset=reset_out}))
    end
    return finish()
end

if SLINK_GEN2_GATE_LIBRARY then return P end

local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(ROOT, "SLINK_ROOT unset -- launch via tools/run_gb_gate.py")
local SG, F = P.scripted_gate(ROOT)
local api = SG.bizhawk()
client_screenshot = function(path) client.screenshot(path) end
live_api = api
P.main(api, os.getenv, SG, F)
api.exit()
error("slink-gate-finished", 0)   -- client.exit() is asynchronous; stop here for real
