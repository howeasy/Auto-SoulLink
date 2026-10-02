--[[
  lua/tests/gen2_phone_gate.lua -- card P4.5d: the PHYSICAL Soul Link phone gate on the patched Gen 2 ROMs (the
  <title>_overlay cartridge, staged and sha1-checked by tools/run_gb_gate.py). The frame of lua/tests/gen2_sfx_gate.lua:
  boot the qualified <title>_battle fixture warm (gen2_qualify.lua stage "boot"), bind the CLEAN facts to the verified
  overlay, then drive normal buttons only. docs/gen2/reviews/P4_5_PHONE_CALLS_PLAN_2026-09-23.md row P4.5d and
  docs/gen2/reviews/P45_PHONE_SAVE_CENSUS_2026-09-23.md.

  Requests reach mailbox +32 through the client's own permit (lua/gen2/panel.lua P.writes, reason "phone"): the
  first through the shipped binder (lua/gen2/phone.lua request("fallen") + service()), the rest as the binder's own
  one-byte post (its 3-minute MIN_GAP and once-per-session first_link are host policy, not under test here).
  A RING is RingTwice_StartCall executing (engine/phone/phone.asm, the call screen). A counted STEP is a completed
  overworld tile move (the qualify observer's map x/y). Every fact is RAM, the exec hooks, or the wTilemap read back
  through the pack charmap; no vision.

  Cases (per title), in play order:
    battle      Route 29 grass: post while wBattleMode != 0. The id must read 0 for the whole battle and nothing
                rings; after RUN, nothing rings before a completed step; then it rings (P4.5d row 2)
    town        New Bark Town, standing: post; REQ acks to 0, ARMED = id, wSpecialPhoneCallID = 9, and nothing
                rings while standing still; one step rings. The call screen: wCurCaller == 0, "----------" and
                the id's first text row in wTilemap; after the call ARMED -> 0 and the id -> 0 (row 1)
    start_menu  START open, post: the id reads 0 while the menu is up; closed, nothing rings standing; a step
                rings (row 3)
    save        post, START > SAVE > YES with ARMED != 0: the id reads 0 through the save script, and after the save
                the CartRAM primary and backup copies of wSpecialPhoneCallID read 0; a step then rings (row 5)
    native      harness seeds wSpecialPhoneCallID = SPECIALCALL_ROBBED (the only harness write, recorded), then
                posts: the id stays ROBBED (never overwritten) while ARMED holds; the first step rings Elm
                (wCurCaller != 0), and after his script clears the id a later step rings SLink (row 4)
    PHONE-NAMES (v2, docs/gen2/POST_RC_CARDS.md), each through a fresh shipped binder built as entry.lua builds it
    (the profile's overlay.phone stage, T.encode_name, the pack charmap), so its MIN_GAP never gates the case:
    named_map_change  at New Bark Town's west edge, post "fallen" with max-length names (a 7-glyph trainer, a
                10-glyph nickname); the crossing into Route 29 runs ClearUnusedMapBuffer (hooked: the wipe) and
                the binder re-stages; the call header shows the trainer name (no "----------") and the body the
                nickname, and the record read at the ring equals the posted one (the re-stage)
    named_fallback  post "first_link" naming only the trainer (no mons): the header names the trainer, the body
                is the fixed first-link text (the ROM's species check falls back)

  Environment: the panel gate's, plus SLINK_GEN2_PHONE_FACTS from tests/live/test_gen2_phone_gate.py.
  Result file: patch/build/gen2_phone_gate_result.txt. Printed: CASE (one per case), RECEIPT; RESULT last.
--]]
local P = {}
P.RESULT = "patch/build/gen2_phone_gate_result.txt"
P.SCRIPTED_GATE = "lua/tests/test_gen2_scripted_gate.lua"
P.FRAME_ALIGN = "lua/tests/gen2_frame_align.lua"
P.SCHEMA = "gen2-phone-gate-v2"
-- PHONE-NAMES max-length names (7 and 10 glyphs, lua/gen2/phone.lua), and two in-range species
P.NAMED = {trainer_name="PARTNER", caller_mon={species_id=16, nickname="LONGNAMEXY"}, receiver_mon={species_id=19}}
P.COOKIE = 0xA6
P.CAP_PHONE = 0x08                 -- patch/gb/slink_abi.inc SLINK_CAP_PHONE
P.OFF_REQ, P.OFF_ARMED = 32, 33    -- SLINK_OFS_PHONE_REQUEST / _ARMED
P.SPECIALCALL_SLINK = 9            -- patch/gen2/src/phone.asm
P.PHONE_CARD = 0x04                -- POKEGEAR_PHONE_CARD_F = 2 (constants/ram_constants.asm)
P.HOLD, P.REST = 12, 8
P.OPEN_BOUND = 600
P.STILL = 180                      -- frames standing still after a post: nothing may ring
P.RING_BOUND = 240                 -- a completed step to RingTwice_StartCall (the call script's pause 30 + ring)
P.CALL_BOUND = 3000                -- a ring to the overworld again (texts answered with A)
P.WALK_BUDGET = 6000
P.BATTLE_BUDGET = {max_frames=40000, max_phase_frames=20000, settle_frames=30}

local fmt = string.format
P.DIRS = {{"Up", 0, -1}, {"Left", -1, 0}, {"Down", 0, 1}, {"Right", 1, 0}}

-- Pure: BFS over a source grid (0 wall, 1 floor, 2 grass) to the first tile goal(x, y) accepts, never through grass
-- unless grass_ok. Returns the first direction name and the path length, or nil. (lua/tests/gen2_sfx_gate.lua's.)
function P.first_step(map, x, y, goal, grass_ok)
    local w, h = map.width, map.height
    local seen, queue, head = {[y * w + x] = true}, {{x, y, nil, 0}}, 1
    while queue[head] do
        local cx, cy, first, n = queue[head][1], queue[head][2], queue[head][3], queue[head][4]
        head = head + 1
        if n > 0 and goal(cx, cy) then return first, n end
        for _, d in ipairs(P.DIRS) do
            local nx, ny = cx + d[2], cy + d[3]
            if nx >= 0 and nx < w and ny >= 0 and ny < h and not seen[ny * w + nx] then
                local c = map.grid[ny * w + nx + 1]
                if c == 1 or (c == 2 and grass_ok) then
                    seen[ny * w + nx] = true
                    queue[#queue + 1] = {nx, ny, first or d[1], n + 1}
                end
            end
        end
    end
end

-- Pure: the verdict of one ring case; nil = PASS. c.rings = {{frame, caller}}, c.steps = completed-step frames.
function P.problem(c)
    if not c.posted then return "the request never reached +32" end
    if not c.acked then return "+32 was never acknowledged (zeroed) by the ROM" end
    if c.armed_id ~= c.id then return fmt("ARMED read %s, not the posted id %d", tostring(c.armed_id), c.id) end
    if c.early_ring then return fmt("rang at frame %d before the qualifying step", c.early_ring) end
    if c.id_visible then return fmt("wSpecialPhoneCallID read %d at frame %d where it must read 0", c.id_visible[2], c.id_visible[1]) end
    if not c.step_at then return "no qualifying step was completed" end
    local ring = c.slink_ring
    if not ring then return "SLink never rang after the step" end
    if ring.frame < c.step_at then return "SLink rang before the step" end
    if ring.frame - c.step_at > P.RING_BOUND then return fmt("rang %d frames after the step", ring.frame - c.step_at) end
    if ring.caller ~= 0 then return fmt("wCurCaller %d on the SLink ring, not PHONE_00", ring.caller) end
    if not c.screen_caller then return "the call screen never showed ----------" end
    if not c.screen_text then return "the call screen never showed the id's first text row" end
    if c.after_armed ~= 0 or c.after_id ~= 0 then
        return fmt("after the call ARMED %s id %s, not 0/0", tostring(c.after_armed), tostring(c.after_id))
    end
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
        log(fmt("RESULT: %s %s (%d checks failed)", failures == 0 and "PASS" or "FAIL", extra or "phone", failures))
        return failures == 0
    end
    log(fmt("[gen2_phone_gate] P4.5d %s overlay phone", tostring(getenv("SLINK_GEN2_TITLE"))))

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
        -- The honest context: the scripted gate binds the overlay's own sha1 (SLINK_GEN2_OVERLAY_SHA1, hashed by the
        -- launcher) against the RUNNING ROM and keeps the clean build only as the facts' base. No clean-hash alias.
        local c = SG.context(api, getenv)
        assert(c.artifact.kind == "overlay" and c.artifact.rom_sha1 == overlay_sha1 and c.artifact.base_sha1 == ov.base_sha1,
               "the scripted context did not bind the staged overlay")
        assert(c.case.name == c.env.title .. "_battle", "the phone gate runs on <title>_battle")
        assert(c.qualify ~= nil and c.qualify.stage == "boot", "SLINK_GEN2_QUALIFY stage \"boot\" required")
        c.phone_facts = assert(c.json.decode(assert(getenv("SLINK_GEN2_PHONE_FACTS"), "SLINK_GEN2_PHONE_FACTS missing")))
        assert(c.phone_facts.overlay_sha1 == overlay_sha1, "phone facts belong to another overlay")
        c.overlay, c.overlay_sha1 = ov, overlay_sha1
        return c
    end)
    if not check("environment, clean facts and the running overlay ROM bound", ok, not ok and ctx or nil) then
        return finish("bad environment")
    end
    ctx.log = log
    local json, title, pf, ov = ctx.json, ctx.env.title, ctx.phone_facts, ctx.overlay
    local function J(value) return assert(json.encode(value)) end
    local MB = ov.ram.wSlinkMailbox
    local REQ, ARMED = MB + P.OFF_REQ, MB + P.OFF_ARMED
    local function u8(addr) return api.read_u8(addr, "System Bus") end
    local function wram(site, i) return api.read_range(SG.wram_offset(site.bank, site.addr + (i or 0), 1), 1, "WRAM")[1] end
    local function phone_id() return wram(pf.ram.wSpecialPhoneCallID) end
    local frame = api.framecount

    -- ── hooks: SG's UI origins + the phone sites (bytes re-validated against the overlay) ────────────
    local state = SG.hooks(ctx)
    local binding = ctx.Binding.new({read_u8=api.read_u8, read_range=api.read_range, register=api.register,
        framecount=api.framecount, on_bus_exec=api.on_bus_exec, unregister=api.unregister},
        {bus_domain="System Bus", rom_domain="ROM", bank_domain="System Bus", pc_register="PC", sp_register="SP",
         bank_address=ctx.profile.hram.hROMBank})
    local rings, saves, wipes, handles, hook_errors = {}, {}, {}, {}, {}
    local STAGE = assert(ov.phone and ov.phone.stage, "profile overlay.phone.stage missing (PHONE-NAMES build)")
    local function stage_bytes()
        local out = {}
        for i = 0, 23 do out[#out + 1] = u8(STAGE + i) end
        return out
    end
    local function watch(id, fn)
        local site = assert(pf.sites[id], "phone facts lack site " .. id)
        local valid = binding:validate({id=id, bank=site.bank, address=site.addr, expected_hex=site.hex,
                                        capture_offset=0, rom_offset=site.flat})
        local handle = binding:register(valid, function()
            local okc, hit = pcall(binding.context, binding, valid)
            if not okc then hook_errors[#hook_errors + 1] = tostring(hit) return end
            if hit then
                local okh, why = pcall(fn, hit.frame)
                if not okh then hook_errors[#hook_errors + 1] = id .. ": " .. tostring(why) end
            end
        end, "SLink-p45d-" .. id)
        assert(binding:valid_handle(handle), id .. ": hook registration failed")
        handles[#handles + 1] = handle
    end
    local hooked, hook_why = pcall(function()
        watch("RingTwice_StartCall", function(f)
            rings[#rings + 1] = {frame=f, caller=wram(pf.ram.wCurCaller), id=phone_id(), armed=u8(ARMED),
                                 stage=stage_bytes()}
        end)
        watch("save_completed", function(f) saves[#saves + 1] = f end)
        watch("ClearUnusedMapBuffer", function(f) wipes[#wipes + 1] = f end)
    end)
    local function release()
        for _, h in ipairs(handles) do pcall(api.unregister, h) end
        handles = {}
        state.release()
    end
    if not check("overlay phone sites bind on the running ROM", hooked, not hooked and hook_why or nil) then
        release()
        return finish("no hooks")
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

    -- ── the client: panel + the shipped phone binder, serviced every frame; the case monitor ─────────
    local Panel = dofile(root .. "/lua/gen2/panel.lua")
    local Phone = dofile(root .. "/lua/gen2/phone.lua")
    local Permit = dofile(root .. "/lua/write_permit.lua")
    local HUD = dofile(root .. "/lua/hud.lua")
    local io_ = {read_u8=function(addr) return api.read_u8(addr, "System Bus") end, framecount=api.framecount,
                 write_u8=function(addr, value, domain) api.write_u8(addr, value, domain) end}
    local writes = Panel.writes(io_, Permit)
    local panel = assert(Panel.new(ctx.profile, ctx.charmap, io_, writes, HUD.sanitize))
    -- PHONE-NAMES: built as lua/gen2/entry.lua builds it
    local T = dofile(root .. "/lua/gen2/trade_overlay.lua")
    local function new_phone()
        return Phone.new(panel, io_, writes, log, {stage=STAGE, charmap=ctx.charmap, encode=T.encode_name})
    end
    local phone = new_phone()
    local cases, cur = {}, nil
    local obs = SG.qualify_observer(ctx)
    local last_xy
    on_frame = function()
        local served, why = panel:service()
        if not served then hook_errors[#hook_errors + 1] = "panel service: " .. tostring(why) end
        phone:service()
        local c = cur
        if not c then return end
        local f, req, armed, id = frame(), u8(REQ), u8(ARMED), phone_id()
        if not c.posted and req == c.id then c.posted = f end
        if c.posted and not c.acked and req == 0 then c.acked, c.armed_id = f, armed end
        if c.hidden and c.hidden() and id ~= 0 and not c.id_visible then c.id_visible = {f, id} end
        local m = ctx.reads.read_map()
        if m then
            local xy = fmt("%d:%d:%d,%d", m.group, m.number, m.x, m.y)
            if last_xy and xy ~= last_xy and c.stepping and not c.step_at then c.step_at = f end
            last_xy = xy
        end
    end
    local function rows() return SG.screen(ctx) end
    local function on_screen(needle)
        for _, row in ipairs(rows()) do if table.concat(row):find(needle, 1, true) then return true end end
        return false
    end
    local function dump(tag)
        for y, row in ipairs(rows()) do log(fmt("  %s %02d |%s|", tag, y - 1, table.concat(row))) end
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
    local function to_overworld(button)
        for _ = 1, 40 do
            if wait(overworld, 45) then return true end
            press(button or "B")
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
    local maps = ctx.facts.maps
    local function map_is(point, name)
        local m = maps[name]
        return point.map_group == m.map_group and point.map_number == m.map_number
    end
    local function here_map()
        local point = obs()
        for name, m in pairs(maps) do
            if point.map_group == m.map_group and point.map_number == m.map_number then return name, m, point end
        end
    end
    -- One completed step onto a floor tile (never grass): hold the direction until the tile changes.
    local function one_step()
        local _, m, point = here_map()
        assert(m and point.overworld_ready, "one_step outside a known overworld map")
        local warp = {}
        for _, w in ipairs(m.warps or {}) do warp[w.y * m.width + w.x] = true end
        local dir
        for _, d in ipairs(P.DIRS) do   -- in-map only: a connection crossing is not a counted step
            local nx, ny = point.x + d[2], point.y + d[3]
            if nx >= 0 and ny >= 0 and nx < m.width and ny < m.height and m.grid[ny * m.width + nx + 1] == 1
               and not warp[ny * m.width + nx] and point.can_step[d[1]] == true then dir = d[1] break end
        end
        if not dir then
            dir = P.first_step(m, point.x, point.y, function(x, y) return m.grid[y * m.width + x + 1] == 1 end)
        end
        assert(dir, fmt("no floor step from %d,%d", point.x, point.y))
        local from = {point.x, point.y}
        log(fmt("  step %s from %d,%d @%d", dir, point.x, point.y, frame()))
        for _ = 1, 48 do
            local p = obs()
            if p.x ~= from[1] or p.y ~= from[2] then break end
            step({[dir]=true})
        end
        idle(2)
    end
    local function post(c, via, no_wait)   -- no_wait: inside a scripted_inputs driver, which owns the frames
        c.via = via
        if via == "binder" then
            c.accepted = phone:request(c.name_id, c.data)
        else   -- the binder's own one-byte post through the same permit
            writes:arm("phone", function(addr, n) return addr == REQ and n == 1 end)
            local okw, why = pcall(function() writes:write_bytes(REQ, {c.id}) end)
            writes:disarm()
            if not okw then error(why, 0) end
            c.accepted = true
            -- the service acks within the next frame, so +32 is never seen holding the id afterwards
            if u8(REQ) == c.id then c.posted = frame() end
        end
        if not no_wait then wait(function() return c.acked ~= nil end, 60) end
    end
    local function arm(name, id, name_id)
        local c = {name=name, id=id, name_id=name_id, armed=frame(), rings_from=#rings + 1}
        cases[#cases + 1], cur = c, c
        return c
    end
    local function rings_since(c, from_frame)
        local out = {}
        for i = c.rings_from, #rings do if rings[i].frame >= (from_frame or 0) then out[#out + 1] = rings[i] end end
        return out
    end
    -- After a ring: read the call screen, answer every text with A, back to the overworld.
    local function take_call(c, ring)
        local needle = pf.texts[tostring(c.id)]
        wait(function()
            if c.named then   -- PHONE-NAMES: the header row names the trainer; "----------" never shows
                local header = rows()[2] and table.concat(rows()[2]) or ""
                if on_screen("----------") then c.saw_dashes = true end
                if header:find(c.named.header, 1, true) then c.screen_caller = true end
                if on_screen(c.named.body) then c.screen_text = true end
            else
                if on_screen("----------") then c.screen_caller = true end
                if on_screen(needle) then c.screen_text = true end
            end
            return c.screen_caller and c.screen_text
        end, P.OPEN_BOUND)
        if c.saw_dashes then c.screen_caller = false end
        if not (c.screen_caller and c.screen_text) then dump("call-" .. c.name) end
        to_overworld("A")
        idle(10)
        c.after_armed, c.after_id = u8(ARMED), phone_id()
    end
    -- Stand still P.STILL frames (nothing may ring), then one step; the ring must follow it.
    local function step_and_ring(c)
        local still_from = frame()
        idle(P.STILL)
        if #rings_since(c, still_from) > 0 then c.early_ring = rings_since(c, still_from)[1].frame end
        c.pending_id = phone_id()
        c.stepping = true
        one_step()
        wait(function() return #rings_since(c, c.step_at or math.huge) > 0 end, P.RING_BOUND)
        c.stepping = false
        for _, r in ipairs(rings_since(c, c.step_at or math.huge)) do
            if r.caller == 0 and not c.slink_ring then c.slink_ring = r end
        end
        if c.slink_ring then take_call(c, c.slink_ring) end
    end
    local function close(c)
        c.done = true
        if cur == c then cur = nil end
        local why = P.problem(c)
        check(fmt("%s: request %d rings on the step after, call screen, ARMED/id cleared", c.name, c.id), why == nil, why)
        c.result, c.problem = why == nil and "PASS" or "FAIL", why
        log("CASE " .. J({case=c.name, id=c.id, via=c.via or json.null, posted=c.posted or json.null,
            acked=c.acked or json.null, armed_id=c.armed_id or json.null, pending_id=c.pending_id or json.null,
            step_at=c.step_at or json.null, early_ring=c.early_ring or json.null,
            id_visible=c.id_visible and json.array(c.id_visible) or json.null,
            slink_ring=c.slink_ring or json.null, screen_caller=c.screen_caller or false,
            screen_text=c.screen_text or false, after_armed=c.after_armed or json.null,
            after_id=c.after_id or json.null, extra=c.extra or json.null, result=c.result, problem=why or json.null}))
    end

    local harness_writes = {}
    local play_ok, play_why = pcall(function()
        local caps = u8(MB + 8)
        check("mailbox beacon SLNK, ABI 3, caps has PHONE, cookie $A5",
              u8(MB) == 0x53 and u8(MB + 1) == 0x4C and u8(MB + 2) == 0x4E and u8(MB + 3) == 0x4B
              and u8(MB + 4) == 3 and caps ~= 0xFF and caps & P.CAP_PHONE ~= 0 and u8(MB + 31) == 0xA5,
              fmt("abi=%d caps=%02X cookie=%02X", u8(MB + 4), caps, u8(MB + 31)))
        check("the phone card is set (POKEGEAR_PHONE_CARD_F)", wram(pf.ram.wPokegearFlags) & P.PHONE_CARD ~= 0)
        check("idle: REQ, ARMED and the id all 0", u8(REQ) == 0 and u8(ARMED) == 0 and phone_id() == 0,
              fmt("req %d armed %d id %d", u8(REQ), u8(ARMED), phone_id()))

        -- battle (row 2): Route 29 grass, post while wBattleMode != 0, RUN, then a floor step rings
        local R29 = maps.Route29
        local grid = R29.grid
        local bc = arm("battle", 2, "dead_zone")
        local in_battle = false
        bc.hidden = function() return in_battle end
        local here, from_tile = nil, nil
        local HOLDF, held, hold_left, release_next = 12, nil, 0, false
        local driver = {phase="approach", terminal="done"}
        local function tap(b) release_next, held, hold_left = true, b, HOLDF - 1 return {[b]=true}, driver.phase end
        function driver.step(point)
            in_battle = type(point.battle_mode) == "number" and point.battle_mode > 0
            if hold_left > 0 then hold_left = hold_left - 1 return {[held]=true}, driver.phase end
            if release_next then release_next = false return {}, driver.phase end
            if driver.phase == "done" then return {}, "done" end
            if driver.phase ~= "battle" and in_battle then driver.phase, driver.battle_from = "battle", frame() end
            local ui = point.ui
            if ui ~= nil then
                if point.input_ready ~= true then return {}, driver.phase end
                if driver.phase ~= "battle" then return nil, "UI outside the battle: " .. tostring(ui.kind) end
                if ui.kind == "battle_menu" then
                    if type(ui.items) ~= "table" then return {}, driver.phase end
                    if not bc.via then post(bc, "permit", true) bc.posted_in_battle = in_battle return {}, driver.phase end
                    if not bc.posted or frame() - bc.posted < P.STILL then return {}, driver.phase end
                    local run
                    for i, l in ipairs(ui.items) do if l == "RUN" then run = i end end
                    if not run then return nil, "no RUN on the battle menu" end
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
            if driver.phase == "approach" then
                if grid[point.y * R29.width + point.x + 1] == 2 then driver.phase = "walk"
                else
                    local dir = P.first_step(R29, point.x, point.y, function(x, y) return grid[y * R29.width + x + 1] == 2 end, true)
                    if not dir then return nil, "no path to the Route 29 grass" end
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
        local battled, outcome = F.play(host, {name="p45d-battle-" .. title, terminal="done",
            max_frames=P.BATTLE_BUDGET.max_frames, max_phase_frames=P.BATTLE_BUDGET.max_phase_frames,
            settle_frames=P.BATTLE_BUDGET.settle_frames, terminal_idle=true}, driver, observe, diag)
        in_battle = false
        check("a real wild battle (walk the grass, post, RUN) back to the overworld", battled and bc.posted_in_battle == true,
              not battled and outcome or nil)
        local during = rings_since(bc, bc.posted or 0)
        bc.extra = {battle_from=driver.battle_from or json.null, battle_to=driver.battle_to or json.null,
                    rings_in_battle=#during}
        if #during > 0 then bc.early_ring = during[1].frame end
        step_and_ring(bc)
        close(bc)

        -- walk east to New Bark Town (grass-free), the town cases there
        for _ = 1, P.WALK_BUDGET do
            local point = obs()
            if map_is(point, "NewBarkTown") and point.overworld_ready then break end
            if type(point.battle_mode) == "number" and point.battle_mode > 0 then error("a battle started on the walk") end
            local buttons = {}
            if point.overworld_ready and map_is(point, "Route29") then
                if point.x == R29.width - 1 then buttons = {Right=true}
                else
                    local dir = P.first_step(R29, point.x, point.y, function(x) return x == R29.width - 1 end)
                    if not dir then error(fmt("no grass-free path east from %d,%d", point.x, point.y)) end
                    buttons = {[dir]=true}
                end
            end
            step(buttons)
        end
        check("in New Bark Town", map_is(obs(), "NewBarkTown"))
        to_overworld()
        idle(60)

        -- town (row 1): the shipped binder posts "fallen"
        local tc = arm("town", 1, "fallen")
        post(tc, "binder")
        check("the binder accepted fallen on the phone build", tc.accepted == true)
        idle(30)
        tc.extra = {id_while_standing=phone_id(), armed_while_standing=u8(ARMED), req_while_standing=u8(REQ)}
        step_and_ring(tc)
        close(tc)

        -- start_menu (row 3)
        to_overworld()
        idle(60)
        local mc = arm("start_menu", 3, "first_link")
        check("START opens the menu", open_menu())
        local menu_open = true
        mc.hidden = function() return menu_open end
        post(mc, "permit")
        idle(P.STILL)
        mc.extra = {armed_in_menu=u8(ARMED), id_in_menu=phone_id()}
        menu_open = false                                   -- the window ends at the close press
        press("B")
        check("START menu closed", to_overworld())
        step_and_ring(mc)
        close(mc)

        -- save (row 5): ARMED != 0 through a native START > SAVE > YES
        to_overworld()
        idle(60)
        local sc = arm("save", 2, "dead_zone")
        post(sc, "permit")
        idle(30)
        local saving = false
        sc.hidden = function() return saving end
        local cart_before = api.read_range(0, 0x8000, "CartRAM")
        check("START opens the menu for SAVE", open_menu())
        saving = true
        check("cursor on SAVE", cursor_to("SAVE"))
        press("A")
        local answered, armed_at_save, saves_from, kinds = 0, nil, #saves, {}
        for _ = 1, 4000 do
            local ui = state.ui
            if #saves > saves_from then break end            -- _SaveGameData.ok's RET (engine site save_completed)
            if ui and kinds[#kinds] ~= ui.kind .. "#" .. ui.seq then kinds[#kinds + 1] = ui.kind .. "#" .. ui.seq end
            if ui and ui.kind == "yes_no" and ui.seq ~= answered then
                answered = ui.seq
                armed_at_save = armed_at_save or u8(ARMED)
                idle(10)
                press("A")                                   -- YES (the save, then the overwrite question)
            elseif ui and (ui.kind == "prompt_button" or ui.kind == "text" or ui.kind == "wait_button")
                   and ui.seq ~= answered then
                answered = ui.seq                            -- "There is already a save file." waits for A
                idle(10)
                press("A")
            else
                step()
            end
        end
        saving = false                                       -- the save script still runs: the id stays 0 anyway
        local saved = #saves > saves_from
        if not saved then dump("save") end
        idle(60)
        local cart_after, changed = api.read_range(0, 0x8000, "CartRAM"), 0
        for i = 1, #cart_after do if cart_before[i] ~= cart_after[i] then changed = changed + 1 end end   -- 1-based arrays
        check("the native save completed (save_completed fired, CartRAM rewritten)", saved and changed > 0,
              fmt("site hits %d, %d CartRAM bytes changed, ui %s", #saves - saves_from, changed, table.concat(kinds, " ")))
        local primary = api.read_u8(pf.sram.primary, "CartRAM")
        local backup = api.read_u8(pf.sram.backup, "CartRAM")
        to_overworld()
        saving = false
        sc.extra = {armed_at_save=armed_at_save or json.null, sram_primary=primary, sram_backup=backup,
                    sram_changed_bytes=changed, save_site_frame=saves[saves_from + 1] or json.null}
        check("ARMED was nonzero at the save", type(armed_at_save) == "number" and armed_at_save ~= 0, tostring(armed_at_save))
        check("the saved wSpecialPhoneCallID reads 0 (primary and backup CartRAM copies)", primary == 0 and backup == 0,
              fmt("primary $%04X=%d backup $%04X=%d", pf.sram.primary, primary, pf.sram.backup, backup))
        step_and_ring(sc)
        close(sc)

        -- native (row 4): a pending ROBBED keeps precedence; Elm rings first, SLink on a later step
        to_overworld()
        idle(60)
        local nc = arm("native", 1, "fallen")
        local seed = pf.robbed
        do   -- the gate's only harness write: seed the native story id (test-only, recorded)
            local site = pf.ram.wSpecialPhoneCallID
            api.write_u8(SG.wram_offset(site.bank, site.addr, 1), seed, "WRAM")
            harness_writes[#harness_writes + 1] = {what="wSpecialPhoneCallID = SPECIALCALL_ROBBED", value=seed, frame=frame()}
        end
        post(nc, "permit")
        idle(P.STILL)
        local held_id = phone_id()
        check("a pending native id is never overwritten: the id stays ROBBED while ARMED holds",
              held_id == seed and u8(ARMED) == nc.id, fmt("id %d armed %d", held_id, u8(ARMED)))
        -- first step: Elm's call
        local elm_from = frame()
        nc.stepping = true
        one_step()
        wait(function() return #rings_since(nc, elm_from) > 0 end, P.RING_BOUND)
        nc.stepping = false
        local elm = rings_since(nc, elm_from)[1]
        check("the first step rings the NATIVE call (wCurCaller != 0)", elm ~= nil and elm.caller ~= 0,
              elm and fmt("caller %d id %d", elm.caller, elm.id) or "no ring")
        to_overworld("A")
        idle(10)
        check("Elm's script cleared the native id; SLink re-armed (id 9, ARMED held)",
              phone_id() == P.SPECIALCALL_SLINK and u8(ARMED) == nc.id, fmt("id %d armed %d", phone_id(), u8(ARMED)))
        nc.step_at, nc.early_ring = nil, nil
        nc.rings_from = #rings + 1
        nc.extra = {native_ring=elm or json.null}
        step_and_ring(nc)
        close(nc)

        -- PHONE-NAMES named_map_change: the record survives a map change between arming and ringing
        to_overworld()
        local NBT = maps.NewBarkTown
        for _ = 1, P.WALK_BUDGET do
            local point = obs()
            if map_is(point, "NewBarkTown") and point.overworld_ready and point.x == 0 then break end
            if type(point.battle_mode) == "number" and point.battle_mode > 0 then error("a battle started on the walk") end
            local buttons = {}
            if point.overworld_ready and map_is(point, "NewBarkTown") then
                local dir = P.first_step(NBT, point.x, point.y, function(x) return x == 0 end)
                if not dir then error(fmt("no path to the west edge from %d,%d", point.x, point.y)) end
                buttons = {[dir]=true}
            end
            step(buttons)
        end
        check("at New Bark Town's west edge", map_is(obs(), "NewBarkTown") and obs().x == 0)
        to_overworld()
        idle(60)
        phone = new_phone()
        local xc = arm("named_map_change", 1, "fallen")
        xc.data, xc.named = P.NAMED, {header=P.NAMED.trainer_name, body=P.NAMED.caller_mon.nickname}
        local expected = Phone.record(1, P.NAMED, T.encode_name, ctx.charmap)
        local wipes_from = #wipes
        post(xc, "binder")
        idle(30)
        -- the binder's record: P.NAMED's bytes, its request nonce (+22, nonzero) and the cookie
        local posted_record = stage_bytes()
        local staged_ok = posted_record[23] ~= 0 and posted_record[24] == P.COOKIE
        for i = 1, 22 do staged_ok = staged_ok and posted_record[i] == expected[i] end
        xc.stepping = true
        local crossed
        for _ = 1, 96 do
            local point = obs()
            if map_is(point, "Route29") then crossed = frame() break end
            step({Left=true})
        end
        idle(2)
        check("the crossing into Route 29 ran ClearUnusedMapBuffer", crossed ~= nil and #wipes > wipes_from,
              fmt("crossed %s wipes %d", tostring(crossed), #wipes - wipes_from))
        wait(function() return #rings_since(xc, xc.step_at or math.huge) > 0 end, P.RING_BOUND)
        if #rings_since(xc, xc.step_at or math.huge) == 0 then   -- the crossing is not a ringing step here
            xc.step_at = nil
            one_step()
            wait(function() return #rings_since(xc, xc.step_at or math.huge) > 0 end, P.RING_BOUND)
        end
        xc.stepping = false
        for _, r in ipairs(rings_since(xc, xc.step_at or math.huge)) do
            if r.caller == 0 and not xc.slink_ring then xc.slink_ring = r end
        end
        local at_ring = xc.slink_ring and table.concat(xc.slink_ring.stage, ",")
        xc.extra = {staged_before_crossing=staged_ok, wipes=#wipes - wipes_from, crossed=crossed or json.null,
                    restaged=at_ring == table.concat(posted_record, ",")}
        if xc.slink_ring then take_call(xc, xc.slink_ring) end
        check("named_map_change: staged, wiped by the crossing, re-staged by the ring",
              staged_ok and #wipes > wipes_from and xc.extra.restaged, J(xc.extra))
        close(xc)

        -- PHONE-NAMES named_fallback: a trainer without mons -> named header, fixed body
        to_overworld()
        idle(60)
        phone = new_phone()
        local fc = arm("named_fallback", 3, "first_link")
        fc.data = {trainer_name=P.NAMED.trainer_name}
        fc.named = {header=P.NAMED.trainer_name, body=pf.texts["3"]}
        post(fc, "binder")
        idle(30)
        local fstage = stage_bytes()
        fc.extra = {species={fstage[2], fstage[3]}, cookie=fstage[24]}
        check("named_fallback staged a valid record with no species", fstage[1] == 3 and fstage[2] == 0
              and fstage[3] == 0 and fstage[24] == P.COOKIE, J(fc.extra))
        step_and_ring(fc)
        close(fc)
    end)
    check("scripted play completed", play_ok, not play_ok and play_why or nil)
    if cur and not cur.done then close(cur) end
    check("no hook or client-service fault", #hook_errors == 0, hook_errors[1])
    release()

    local out = {}
    for _, c in ipairs(cases) do
        local ring = c.slink_ring and {frame=c.slink_ring.frame, caller=c.slink_ring.caller} or json.null
        out[c.name] = {id=c.id, via=c.via or json.null, result=c.result or "FAIL", step_at=c.step_at or json.null,
                       ring=ring, extra=c.extra or json.null}
    end
    if failures == 0 then
        log("RECEIPT " .. J({schema=P.SCHEMA, title=title, evidence_level=evidence, result="PASS",
            overlay_sha1=ctx.overlay_sha1, base_sha1=ov.base_sha1, fixture=case.name, fixture_sha256=q.stage_fingerprint,
            qualification_attempt_id=getenv("SLINK_GEN2_QUALIFICATION_ATTEMPT") or json.null, core_mode="CGB",
            input_mode="normal_buttons", harness_write_scopes=json.array(harness_writes),
            client_write_scope="phone (lua/gen2/panel.lua permit reason phone, mailbox +32, the wUnusedMapBuffer stage)",
            cases=out, sram=pf.sram}))
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
