--[[
  lua/tests/gen2_panel_gate.lua -- card P4.1g: the first PHYSICAL proof of the SLink panel on the patched
  Gen 2 ROMs (the <title>_overlay cartridge: clean build + patch/dist/SLink-<Title>.ups, staged and
  sha1-checked by tools/run_gb_gate.py). Mirrors lua/tests/test_gen1_menu_row_gate.lua.

  Boots the qualified <title>_battle fixture WARM through the fixture-qualification CONTINUE path
  (gen2_qualify.lua stage "boot", exactly the inspect / U1 gate's arrival). The scripted gate context binds the
  CLEAN facts (profile, charmap, route facts, UI origins): the overlay moves no RAM symbol and only bank-4
  code (tools/build_gen2_companion.verify_symbol_scope), and every hooked site's bytes are re-validated
  against the RUNNING overlay ROM at registration (lua/gb_hook_binding.lua), so a site the overlay moved
  refuses instead of misfiring. The running ROM hash must equal the profile overlay block's rom_sha1 and
  SLINK_GEN2_OVERLAY_SHA1 before the clean facts are bound to it.

  Normal buttons only. Menu layout from the decomp: StartMenu.MenuHeader menu_coords 10, 0 (C/G/S
  engine/menus/start_menu.asm), DrawVariableLengthMenuBox puts the bottom border at top + 2n + 1 (O-28:
  a 9th row would be 19 > 17), SLINK is the last item SetUpMenuItems appends (the visible EXIT slot).
  Every screen fact is the wTilemap read back through the pack charmap (lua/tests/test_gen2_scripted_gate.lua
  G.screen / G.parse_menu); no vision.

  Checks (per title):
    1 START menu    SLINK is the last row, exactly once; EXIT is gone; the bottom border row <= 17 and
                    == top + 2n + 1. B closes it; START closes it.
    2 panel         with the Lua client (lua/gen2/panel.lua over lua/gb_panel.lua, rows held as the
                    client's link_panel handler holds them): CLOSED -> AWAIT -> STAGED, page 1 painted;
                    A pages forward; A on the last page closes (CLOSED, page/pages zeroed, START menu
                    back); B closes; START closes. With NO client (no service): AWAIT times out to
                    CLOSED and STAYS CLOSED, "NO CLIENT" shows, A/B/START each close within a bound.
    3 fade stress   mash B/START/A across open -> fade-out -> panel -> close -> redraw fade-in -> menu exit
                    at several phase offsets, client on and off; every cycle ends in the overworld with the
                    CGB palette buffers (wBGPals1/2, wOBPals1/2) and the VRAM bank-1 BG attribute maps equal
                    to that cycle's own pre-open snapshot. Controls: the same snapshot differs while a panel
                    page shows (the probe sees change); a native OPTION round trip restores equal (the
                    probe's equality is the game's own). Presses are counted inside the FadeOutToWhite /
                    FadeInFromWhite windows. Screenshots only CONFIRM (panel page, restored overworld).
    5 minimum SP    a self-disarming bus-write witness over the whole stack span, armed right after
                    arrival: every push lands at SP-2..SP+1; the lowest such address over the menus, the
                    panel, the stress cycles and a real wild battle (walk the Route 29 grass, RUN) is the
                    low-water mark; margin = that address - wStackBottom. Known positive: the top of the
                    stack is hit in the first frames.
  (Check 4, the soft_reset re-proof, was dropped by main 2026-09-23: the reset hook moves off the anchor.)

  Environment: the inspect gate's (SLINK_ROOT, run_gb_gate._gen2_plan bindings incl. SLINK_GEN2_OVERLAY_SHA1,
  SLINK_GEN2_FIXTURE_CASE, SLINK_GEN2_ROUTE_FACTS, SLINK_GEN2_QUALIFY stage "boot") plus SLINK_GEN2_PANEL_FACTS
  from tests/live/test_gen2_panel_gate.py (sites + RAM from data/gen2/<title>_slink.sym).
  Result file: patch/build/gen2_panel_gate_result.txt. Printed: MENU, PANEL, FALLBACK, CONTROL, STRESS,
  STACK, RECEIPT (json after the tag); RESULT: PASS|FAIL last.
--]]
local P = {}
P.RESULT = "patch/build/gen2_panel_gate_result.txt"
P.SCRIPTED_GATE = "lua/tests/test_gen2_scripted_gate.lua"
P.FRAME_ALIGN = "lua/tests/gen2_frame_align.lua"
P.SCHEMA = "gen2-panel-gate-v1"
-- gb_panel mailbox ABI (patch/gb/slink_abi.inc): state/page/pages at +9/+10/+11, cookie +31.
P.CLOSED, P.AWAIT, P.STAGED = 0, 1, 2
-- Required caps bits, masked like the P4.1f binder (lua/gb_panel.lua caps_has): later bits (PHONE, TRADE) never
-- break the gate; $FF (open bus / erased) is never a grant.
P.CAPS_REQUIRED = 0x02             -- PANEL (patch/gb/slink_abi.inc SLINK_CAP_PANEL)
P.STAGE_TIMEOUT = 90               -- SlinkPanel.WaitForStage (patch/gen2/src/panel.asm)
-- ponytail: live calibration knobs, not measured yet.
P.HOLD, P.REST = 12, 8
P.OPEN_BOUND = 600                 -- frames for a menu or panel to appear after its press
P.CLOSE_BOUND = 240                -- no-soft-lock bound: a close press to the START menu redrawn
P.SETTLE = 60
P.STRESS = {                       -- {offset after the A press, mash button, client}
    {0, "B", true}, {3, "Start", true}, {6, "B", false}, {10, "A", false}, {16, "Start", false},
    {24, "B", true}, {40, "Start", true}, {60, "A", false}, {100, "B", false},
}
P.BATTLE_BUDGET = {max_frames=40000, max_phase_frames=20000, settle_frames=30}
-- Two pages (18 rows each): row 1 of each page is its marker; the held rows are uppercase + digits only.
P.ROWS = {"SLINK GATE PAGE 1", "", "PAIRS 3 OF 5", "BADGES 2 OF 8", "DEAD ZONES 1"}
for i = #P.ROWS + 1, 18 do P.ROWS[i] = "ROW " .. i end
P.ROWS[19] = "SLINK GATE PAGE 2"
for i = 20, 24 do P.ROWS[i] = "ROW " .. i end

local fmt = string.format

-- Pure: the START menu box read from decoded rows (1-based glyph grids). Column 11 (x = 10) holds the
-- left border (menu_coords 10, 0). Returns {top, bottom} 0-based, or nil.
function P.menu_box(rows, glyph)
    local top, bottom
    for y, row in ipairs(rows) do
        if row[11] == glyph.top_left and top == nil then top = y - 1 end
        if row[11] == glyph.bottom_left and top ~= nil and bottom == nil then bottom = y - 1 end
    end
    if top and bottom then return {top=top, bottom=bottom} end
end

-- Pure: O-28 verdict over a parsed START menu + its box; nil = PASS.
function P.menu_problem(menu, box)
    if not menu or not box then return "START menu not parsed from the tilemap" end
    local n, slink, exit = #menu.items, 0, 0
    for _, label in ipairs(menu.items) do
        if label == "SLINK" then slink = slink + 1 end
        if label == "EXIT" then exit = exit + 1 end
    end
    if slink ~= 1 or menu.items[n] ~= "SLINK" then return "SLINK is not the single last row" end
    if exit ~= 0 then return "EXIT is still drawn" end
    if box.bottom > 17 then return fmt("bottom border row %d > 17", box.bottom) end
    if box.bottom ~= box.top + 2 * n + 1 then
        return fmt("bottom border row %d != top %d + 2*%d + 1", box.bottom, box.top, n)
    end
end

-- Pure: are two snapshots equal? Returns true or the first differing component name.
function P.same(a, b)
    for _, key in ipairs({"bgp1", "obp1", "bgp2", "obp2", "attr"}) do
        local x, y = a[key], b[key]
        if #x ~= #y then return key end
        for i = 1, #x do if x[i] ~= y[i] then return fmt("%s[%d]", key, i - 1) end end
    end
    return true
end

-- Pure: presses (frames with the mash button down) inside [start, stop] fade windows.
function P.in_windows(frames, windows)
    local n = 0
    for _, f in ipairs(frames) do
        for _, w in ipairs(windows) do
            if f >= w[1] and f <= (w[2] or w[1]) then n = n + 1 break end
        end
    end
    return n
end

-- Pure: close [start, nil] windows with the first end hit after each start.
function P.windows(starts, ends)
    local out = {}
    for _, s in ipairs(starts) do
        local stop
        for _, e in ipairs(ends) do if e >= s then stop = e break end end
        out[#out + 1] = {s, stop}
    end
    return out
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
        log(fmt("RESULT: %s %s (%d checks failed)", failures == 0 and "PASS" or "FAIL", extra or "panel", failures))
        return failures == 0
    end
    log(fmt("[gen2_panel_gate] P4.1g %s overlay panel", tostring(getenv("SLINK_GEN2_TITLE"))))

    -- Per-frame work rides the one advance every driver calls: the client's panel service (when the
    -- client is ON), the mailbox state trace and the stack witness's disarm pass.
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
        assert(c.case.name == c.env.title .. "_battle", "the panel gate runs on <title>_battle")
        assert(c.qualify ~= nil and c.qualify.stage == "boot", "SLINK_GEN2_QUALIFY stage \"boot\" required")
        c.panel_facts = assert(c.json.decode(assert(getenv("SLINK_GEN2_PANEL_FACTS"), "SLINK_GEN2_PANEL_FACTS missing")))
        assert(c.panel_facts.overlay_sha1 == overlay_sha1, "panel facts belong to another overlay")
        c.overlay, c.overlay_sha1 = ov, overlay_sha1
        return c
    end)
    if not check("environment, clean facts and the running overlay ROM bound", ok, not ok and ctx or nil) then
        return finish("bad environment")
    end
    ctx.log = log
    local json, title, pf, ov = ctx.json, ctx.env.title, ctx.panel_facts, ctx.overlay
    local function J(value) return assert(json.encode(value)) end
    local MB = ov.ram.wSlinkMailbox
    local function u8(addr) return api.read_u8(addr, "System Bus") end
    local function wram(site, n) return api.read_range(SG.wram_offset(site.bank, site.addr, n), n, "WRAM") end
    local frame = api.framecount

    -- ── hooks: SG's UI origins + this gate's overlay sites (bytes re-validated against the overlay) ──
    local state = SG.hooks(ctx)
    local binding = ctx.Binding.new({read_u8=api.read_u8, read_range=api.read_range, register=api.register,
        framecount=api.framecount, on_bus_exec=api.on_bus_exec, unregister=api.unregister},
        {bus_domain="System Bus", rom_domain="ROM", bank_domain="System Bus", pc_register="PC", sp_register="SP",
         bank_address=ctx.profile.hram.hROMBank})
    local hits, handles, hook_errors = {}, {}, {}
    local function watch(id)
        local site = assert(pf.sites[id], "panel facts lack site " .. id)
        local valid = binding:validate({id=id, bank=site.bank, address=site.addr, expected_hex=site.hex,
                                        capture_offset=0, rom_offset=site.flat})
        hits[id] = {}
        local handle = binding:register(valid, function()
            local okc, hit = pcall(binding.context, binding, valid)
            if not okc then hook_errors[#hook_errors + 1] = tostring(hit) return end
            if hit then hits[id][#hits[id] + 1] = hit.frame end
        end, "SLink-p41g-" .. id)
        assert(binding:valid_handle(handle), id .. ": hook registration failed")
        handles[#handles + 1] = handle
    end
    local hooked, hook_why = pcall(function()
        for _, id in ipairs({"SlinkPanel", "SlinkPanel.close", "SlinkStartMenuEntry", "FadeOutToWhite",
                             "FadeInFromWhite", "EnableSpriteUpdates", "DisableSpriteUpdates"}) do watch(id) end
    end)
    local function release()
        for _, h in ipairs(handles) do pcall(api.unregister, h) end
        handles = {}
        state.release()
    end
    if not check("overlay panel/fade sites bind on the running ROM", hooked, not hooked and hook_why or nil) then
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

    -- ── the stack witness (check 5), armed from here to the end ──────────────────────────────────
    local stack = {bottom=pf.ram.wStackBottom.addr, top=pf.ram.wStackTop.addr, hit={}, min_addr=nil, min_sp=nil,
                   below_sp=0, pushes=0, armed=0, first_frame=frame()}
    local stack_handles, stack_pending = {}, {}
    for a = stack.bottom, stack.top do
        stack_handles[a] = api.on_bus_write(function()
            if stack.hit[a] then return end
            local sp = api.register("SP")
            if a < sp - 2 then stack.below_sp = stack.below_sp + 1 return end   -- not a push: below SP
            if a > sp + 1 then return end                                        -- a frame write above SP
            stack.hit[a] = {sp=sp, frame=frame()}
            stack.pushes = stack.pushes + 1
            stack_pending[#stack_pending + 1] = a
            if stack.min_addr == nil or a < stack.min_addr then stack.min_addr, stack.min_sp = a, sp end
        end, a, "SLink-p41g-sp-" .. a, "System Bus")
        stack.armed = stack.armed + 1
    end

    -- ── the client ───────────────────────────────────────────────────────────────────────────────
    local Panel = dofile(root .. "/lua/gen2/panel.lua")
    local Permit = dofile(root .. "/lua/write_permit.lua")
    local HUD = dofile(root .. "/lua/hud.lua")
    local io_ = {read_u8=function(addr) return api.read_u8(addr, "System Bus") end, framecount=api.framecount,
                 write_u8=function(addr, value, domain) api.write_u8(addr, value, domain) end}
    local panel = assert(Panel.new(ctx.profile, ctx.charmap, io_, Panel.writes(io_, Permit), HUD.sanitize))
    local client = false
    local trace, last_state = {}, nil
    local function note_state()
        local s = u8(MB + 9)
        if s ~= last_state then
            trace[#trace + 1] = {state=s, frame=frame(), page=u8(MB + 10), pages=u8(MB + 11)}
            if #trace > 400 then table.remove(trace, 1) end
            last_state = s
        end
    end
    on_frame = function()
        note_state()   -- before the client's service: an AWAIT it stages this frame is still seen
        if client then
            local served, why = panel:service()
            if not served then hook_errors[#hook_errors + 1] = "panel service: " .. tostring(why) end
        end
        note_state()
        for _, a in ipairs(stack_pending) do
            if stack_handles[a] then pcall(api.unregister, stack_handles[a]); stack_handles[a] = nil end
        end
        stack_pending = {}
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
    local function row_text(r) return table.concat(rows()[r + 1]) end
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
    local function mailbox() return u8(MB + 9), u8(MB + 10), u8(MB + 11) end
    local function open_menu()   -- up AND past its draw: an edge during the menu's load is dropped
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
    local function cursor_to_slink()
        for _ = 1, 12 do
            local m = menu()
            if m and m.items[m.cursor] == "SLINK" then return true end
            press("Up")
            wait(menu_up, 30)
        end
        return false
    end
    local function snapshot()
        local r = pf.ram
        return {bgp1=wram(r.wBGPals1, 64), obp1=wram(r.wOBPals1, 64), bgp2=wram(r.wBGPals2, 64),
                obp2=wram(r.wOBPals2, 64), attr=api.read_range(0x3800, 0x800, "VRAM")}
    end
    local function shot(name)
        local rel = fmt("patch/build/gen2_panel_gate_%s_%s.png", title, name)
        pcall(client_screenshot or function() end, root .. "/" .. rel)
        return rel
    end
    local function saw(states)   -- the trace since `from` contains `states` in order
        return function(from)
            local i = 1
            for _, e in ipairs(trace) do
                if e.frame >= from and e.state == states[i] then i = i + 1 end
                if i > #states then return true end
            end
            return false
        end
    end
    local closed_hits = function() return #hits["SlinkPanel.close"] end
    local open_hits = function() return #hits["SlinkPanel"] end

    local play_ok, play_why = pcall(function()
        -- 0. the mailbox is live on the overlay
        local s0, _, _ = mailbox()
        local beacon = string.char(u8(MB), u8(MB + 1), u8(MB + 2), u8(MB + 3))
        local c0 = u8(MB + 5) + 256 * u8(MB + 6)
        idle(60)
        local c1 = u8(MB + 5) + 256 * u8(MB + 6)
        local caps = u8(MB + 8)
        check("mailbox beacon SLNK, ABI 3, caps has PANEL, cookie $A5",
              beacon == "SLNK" and u8(MB + 4) == 3 and caps ~= 0xFF and caps & P.CAPS_REQUIRED == P.CAPS_REQUIRED
              and u8(MB + 31) == 0xA5,
              fmt("beacon=%q abi=%d caps=%02X cookie=%02X", beacon, u8(MB + 4), u8(MB + 8), u8(MB + 31)))
        check("the sampled counter advances in the overworld", c1 ~= c0, fmt("%d -> %d over 60 frames", c0, c1))
        client = true
        idle(2)
        check("the shipped panel module reads the cartridge live", panel:present() == true and panel:fresh() == true,
              fmt("present=%s fresh=%s", tostring(panel:present()), tostring(panel:fresh())))
        client = false
        check("panel state is CLOSED in the overworld", s0 == P.CLOSED, "state " .. tostring(s0))

        -- 1. the START menu (O-28)
        local base = snapshot()
        check("START opens the menu", open_menu())
        idle(P.REST)
        local m, box = menu(), P.menu_box(rows(), SG.GLYPH)
        dump("menu")
        local why = P.menu_problem(m, box)
        check("SLINK replaces EXIT as the last row; bottom border <= 17 = top + 2n + 1", why == nil, why)
        log("MENU " .. J({items=json.array(m and m.items or {}), top=box and box.top or json.null,
                                    bottom=box and box.bottom or json.null}))
        press("B")
        check("B closes the START menu", wait(overworld, 120))
        to_overworld()
        check("START opens it again", open_menu())
        press("Start")
        check("START closes the START menu", wait(overworld, 120) and not menu_up())
        idle(P.SETTLE)
        -- Native, not the panel: the FIRST START menu after CONTINUE leaves wBGPals1 pal 7 changed (Crystal
        -- live run 2, bgp1[57]); every later cycle is compared against its own pre-open snapshot.
        local menu_trip = P.same(base, snapshot())
        log("  [note] first START menu round trip vs arrival: " .. tostring(menu_trip))

        -- CONTROL: a native full-screen submenu (OPTION) round trip restores the snapshot exactly.
        base = snapshot()
        open_menu()
        local labels = menu().items
        local option
        for i, l in ipairs(labels) do if l == "OPTION" then option = i end end
        for _ = 1, 12 do
            local mm = menu()
            if not option or (mm and mm.cursor == option) then break end
            press("Up")
            wait(menu_up, 30)
        end
        press("A")
        wait(function() return not menu_up() end, P.OPEN_BOUND)
        idle(60)
        press("B")
        wait(menu_up, P.OPEN_BOUND)
        press("B")
        to_overworld()
        idle(P.SETTLE)
        local native = P.same(base, snapshot())
        check("CONTROL: a native OPTION round trip restores the snapshot", native == true, native)
        log("CONTROL " .. J({native_option=native == true and "restored" or native,
                             first_start_trip=menu_trip == true and "restored" or menu_trip}))

        -- 2. the panel with the client
        client = true
        assert(panel:hold(P.ROWS))
        base = snapshot()
        local function open_panel()
            if not open_menu() or not cursor_to_slink() then return false end
            local from = frame()
            press("A")
            return wait(function() return open_hits() > 0 and hits["SlinkPanel"][#hits["SlinkPanel"]] >= from end,
                        P.OPEN_BOUND), from
        end
        local pre_state = mailbox()
        local opened, from = open_panel()
        check("SLINK opens the panel (SlinkPanel entered)", opened)
        local staged = wait(function() return on_screen("SLINK GATE PAGE 1") and mailbox() == P.STAGED end, P.OPEN_BOUND)
        idle(20)
        check("CLOSED -> AWAIT -> STAGED; the client painted page 1", staged and pre_state == P.CLOSED and saw({P.AWAIT, P.STAGED})(from))
        local st, pg, pgs = mailbox()
        check("page 0 of 2 published", st == P.STAGED and pg == 0 and pgs == 2, fmt("state %d page %d pages %d", st, pg, pgs))
        check("page 2 is not on screen yet and the fallback is painted over",
              not on_screen("SLINK GATE PAGE 2") and not on_screen("NO CLIENT"))
        local attr_ok = true
        for _, v in ipairs(wram({bank=0, addr=ov.ram.wAttrmap}, 360)) do attr_ok = attr_ok and v == Panel.ATTR_FILL end
        check("the attrmap buffer holds the panel fill", attr_ok)
        local during = P.same(base, snapshot())
        check("CONTROL: the snapshot differs while a panel page shows", during ~= true, during == true and "identical" or nil)
        local page1_shot = shot("page1")
        dump("page1")
        local turn = frame()
        press("A")
        local paged = wait(function() return on_screen("SLINK GATE PAGE 2") and mailbox() == P.STAGED end, P.OPEN_BOUND)
        idle(20)
        st, pg, pgs = mailbox()
        check("A pages forward: STAGED -> AWAIT -> STAGED, page 1 of 2",
              paged and saw({P.AWAIT, P.STAGED})(turn) and pg == 1 and pgs == 2 and not on_screen("SLINK GATE PAGE 1"),
              fmt("state %d page %d pages %d", st, pg, pgs))
        local close_from = closed_hits()
        press("A")
        local back = wait(function() return menu_up() and closed_hits() > close_from end, P.CLOSE_BOUND)
        st, pg, pgs = mailbox()
        check("A on the last page closes: CLOSED, page/pages 0, START menu redrawn",
              back and st == P.CLOSED and pg == 0 and pgs == 0, fmt("state %d page %d pages %d", st, pg, pgs))
        press("B")
        to_overworld()
        idle(P.SETTLE)
        local after = P.same(base, snapshot())
        check("the panel round trip restores palettes/attrs (native SCGB)", after == true, after)
        local restored_shot = shot("restored")
        for _, button in ipairs({"B", "Start"}) do
            opened = open_panel()
            staged = opened and wait(function() return mailbox() == P.STAGED end, P.OPEN_BOUND)
            idle(20)
            close_from = closed_hits()
            press(button)
            back = wait(function() return menu_up() and closed_hits() > close_from end, P.CLOSE_BOUND)
            check(button .. " closes the client panel", staged and back and mailbox() == P.CLOSED)
            press("B")
            to_overworld()
        end
        log("PANEL " .. J({pre_state=pre_state, trace=json.array((function()
            local out = {}
            for _, e in ipairs(trace) do if e.frame >= from then out[#out + 1] = e end end
            return out end)()), screenshots=json.array({page1_shot, restored_shot})}))

        -- 2b. no client: the fallback
        client = false
        panel:clear()
        local fallback = {}
        for _, button in ipairs({"A", "B", "Start"}) do
            local ok_open, f0 = open_panel()
            local shown = ok_open and wait(function() return on_screen("NO CLIENT") and mailbox() == P.CLOSED
                                                            and saw({P.AWAIT, P.CLOSED})(f0) end, P.OPEN_BOUND)
            local await_at, closed_at
            for _, e in ipairs(trace) do
                if e.frame >= f0 and e.state == P.AWAIT and not await_at then await_at = e.frame end
                if await_at and e.frame > await_at and e.state == P.CLOSED and not closed_at then closed_at = e.frame end
            end
            local stays = true
            for _ = 1, 60 do step() stays = stays and mailbox() == P.CLOSED end
            close_from = closed_hits()
            local pressed_at = frame()
            press(button)
            back = wait(function() return menu_up() and closed_hits() > close_from end, P.CLOSE_BOUND)
            local took = frame() - pressed_at
            fallback[#fallback + 1] = {button=button, await=await_at, timeout=closed_at and await_at and closed_at - await_at,
                                       close_frames=took, stayed_closed=stays}
            check("no client: AWAIT times out to CLOSED, NO CLIENT shows and stays CLOSED",
                  shown and stays and closed_at ~= nil and closed_at - await_at <= P.STAGE_TIMEOUT + 10,
                  fmt("await %s closed %s", tostring(await_at), tostring(closed_at)))
            check("no client: " .. button .. " closes the fallback within the bound (no soft-lock)",
                  back and mailbox() == P.CLOSED, fmt("%d frames", took))
            press("B")
            to_overworld()
        end
        log("FALLBACK " .. J(fallback))

        -- 3. CGB fade stress
        local stress, in_out, in_in, all_restored = {}, 0, 0, true
        for i, spec in ipairs(P.STRESS) do
            local offset, button, with_client = spec[1], spec[2], spec[3]
            client = with_client
            panel:clear()
            if with_client then assert(panel:hold(P.ROWS)) end
            to_overworld()
            idle(P.SETTLE)
            local before = snapshot()
            local c_from, o_from = closed_hits(), open_hits()
            local f_start = frame()
            local ok_menu = open_menu() and cursor_to_slink()
            -- Hold A until SlinkStartMenuEntry runs (FadeToMenu starts there), so offset 0 is the fade-out.
            local entries = #hits.SlinkStartMenuEntry
            for _ = 1, P.HOLD do
                step({A=true})
                if #hits.SlinkStartMenuEntry > entries then break end
            end
            idle(offset)
            local mashed = {}
            local down = false
            for _ = 1, P.OPEN_BOUND do
                if closed_hits() > c_from and (button ~= "B" or overworld()) then break end
                down = not down
                if down then mashed[#mashed + 1] = frame() end
                step(down and {[button]=true} or {})
            end
            idle(P.REST)
            to_overworld()
            idle(P.SETTLE)
            local same = P.same(before, snapshot())
            all_restored = all_restored and same == true
            local fades_out = P.windows((function() local o = {} for _, f in ipairs(hits.FadeOutToWhite) do if f >= f_start then o[#o + 1] = f end end return o end)(),
                                        hits.DisableSpriteUpdates)
            local fades_in = P.windows((function() local o = {} for _, f in ipairs(hits.FadeInFromWhite) do if f >= f_start then o[#o + 1] = f end end return o end)(),
                                       hits.EnableSpriteUpdates)
            local n_out, n_in = P.in_windows(mashed, fades_out), P.in_windows(mashed, fades_in)
            in_out, in_in = in_out + n_out, in_in + n_in
            stress[#stress + 1] = {cycle=i, offset=offset, button=button, client=with_client, menu=ok_menu,
                                   opened=open_hits() > o_from, closed=closed_hits() > c_from, presses=#mashed,
                                   in_fade_out=n_out, in_fade_in=n_in, restored=same == true and true or same}
            check(fmt("stress %d (%s +%d, client %s): opened, closed, restored", i, button, offset, tostring(with_client)),
                  open_hits() > o_from and closed_hits() > c_from and same == true and mailbox() == P.CLOSED,
                  same ~= true and same or nil)
        end
        client = false
        check("stress presses landed inside FadeOutToWhite and FadeInFromWhite windows", in_out > 0 and in_in > 0,
              fmt("out %d in %d", in_out, in_in))
        log("STRESS " .. J({cycles=json.array(stress), in_fade_out=in_out, in_fade_in=in_in,
                                      all_restored=all_restored}))

        -- 5. a real wild battle for the stack witness: walk the grass, RUN, back to the overworld.
        local map = ctx.facts.maps.Route29
        local here, from_tile, ran = nil, nil, false
        local HOLD, held, hold_left, release_next = 12, nil, 0, false
        local driver = {phase="walk", terminal="done"}
        local function tap(b) release_next, held, hold_left = true, b, HOLD - 1 return {[b]=true}, driver.phase end
        function driver.step(point)
            if hold_left > 0 then hold_left = hold_left - 1 return {[held]=true}, driver.phase end
            if release_next then release_next = false return {}, driver.phase end
            if driver.phase == "done" then return {}, "done" end
            if driver.phase == "walk" and type(point.battle_mode) == "number" and point.battle_mode > 0 then driver.phase = "battle" end
            local ui = point.ui
            if ui ~= nil then
                if point.input_ready ~= true then return {}, driver.phase end
                if driver.phase ~= "battle" then return nil, "UI outside the battle: " .. tostring(ui.kind) end
                if ui.kind == "battle_menu" then
                    if type(ui.items) ~= "table" then return {}, driver.phase end
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
            if driver.phase == "battle" then driver.phase = "done" return {}, "done" end
            if here and (here.x ~= point.x or here.y ~= point.y) then from_tile = here end
            here = {x=point.x, y=point.y}
            local b, w = F.walk_direction(map, point, from_tile)
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
        local battled, outcome = F.play(host, {name="p41g-battle-" .. title, terminal="done",
            max_frames=P.BATTLE_BUDGET.max_frames, max_phase_frames=P.BATTLE_BUDGET.max_phase_frames,
            settle_frames=P.BATTLE_BUDGET.settle_frames, terminal_idle=true}, driver, observe, diag)
        check("a real wild battle (walk the grass, RUN) back to the overworld", battled and ran, not battled and outcome or nil)
    end)
    check("scripted play completed", play_ok, not play_ok and play_why or nil)
    client = false
    local stack_rows = {}
    for a = stack.bottom, stack.top do if stack_handles[a] then pcall(api.unregister, stack_handles[a]) end end
    -- Known positive: the live call chain's own pushes are seen in the first frames after arming.
    local early = 0
    for _, h in pairs(stack.hit) do if h.frame <= stack.first_frame + 10 then early = early + 1 end end
    local margin = stack.min_addr and stack.min_addr - stack.bottom or json.null
    local stack_out = {bottom=stack.bottom, top=stack.top, armed=stack.armed, pushes_seen=stack.pushes,
                       low_water_addr=stack.min_addr or json.null, low_water_sp=stack.min_sp or json.null,
                       low_water_frame=stack.min_addr and stack.hit[stack.min_addr].frame or json.null,
                       margin_bytes=margin, below_sp_writes=stack.below_sp, early_hits=early,
                       span_frames=frame() - stack.first_frame}
    log("STACK " .. J(stack_out))
    check("stack witness known positive: pushes seen within 10 frames of arming", early >= 8,
          fmt("%d distinct stack bytes", early))
    check("stack witness: a low-water mark with a positive margin", type(margin) == "number" and margin > 0,
          tostring(margin))
    check("no hook or panel-service fault", #hook_errors == 0, hook_errors[1])
    release()
    local q_attempt = getenv("SLINK_GEN2_QUALIFICATION_ATTEMPT")
    if failures == 0 then
        log("RECEIPT " .. J({schema=P.SCHEMA, title=title, evidence_level=evidence, result="PASS",
            overlay_sha1=ctx.overlay_sha1, base_sha1=ov.base_sha1, fixture=case.name, fixture_sha256=q.stage_fingerprint,
            qualification_attempt_id=q_attempt or json.null, core_mode="CGB", input_mode="normal_buttons",
            harness_write_scopes=json.array({}), client_write_scope="panel (lua/gen2/panel.lua permit, WRAM0 tilemap/attrmap/mailbox)",
            checks={menu=true, panel=true, fallback=true, fade_stress=true}, minimum_sp=stack_out}))
    end
    return finish()
end

if SLINK_GEN2_GATE_LIBRARY then return P end

local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(ROOT, "SLINK_ROOT unset -- launch via tools/run_gb_gate.py")
local SG, F = P.scripted_gate(ROOT)
local api = SG.bizhawk()
api.on_bus_write = function(fn, addr, name, domain) return event.onmemorywrite(fn, addr, name, domain) end
client_screenshot = function(path) client.screenshot(path) end
live_api = api
P.main(api, os.getenv, SG, F)
api.exit()
error("slink-gate-finished", 0)   -- client.exit() is asynchronous; stop here for real
