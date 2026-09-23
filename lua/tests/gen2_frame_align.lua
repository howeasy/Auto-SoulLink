--[[
  lua/tests/gen2_frame_align.lua -- card gen2-U1: the Crystal engine-hook proof on the RUNNING cartridge
  (docs/gen2/GEN2_BINDING_PLAN.md P3b.4: the 5.13 frame-alignment probe, B-9, and the 5.11 engine-sequence
  proof; docs/gen2/reviews/P3B7_PLAN_CODEX_2026-09-23.md row U1).

  Result file: patch/build/gen2_frame_align_result.txt (RESULT: PASS|FAIL, last line).

  Boots crystal_battle WARM (Route 29 grass, the fixture's recorded O-10 Ball stack already in the save;
  no harness write of any kind here), arrives through the same source-qualified CONTINUE path the
  inspect gate uses, then arms EVERY engine_signals.json site through the shared lua/hook_registry.lua +
  lua/gb_hook_binding.lua (load-time expected_hex check in the ROM domain, hROMBank filter, PC == site,
  bytes re-read on the System Bus at fire time) and plays with normal buttons only:
    walk      hold a direction per frame between Route 29 grass tiles until wBattleMode != 0
    battle    BattleMenu PACK -> the Ball pocket -> POKe BALL -> USE, A through battle text, NO to the
              nickname, repeated until the catch; the battle ends natively
    save      START -> SAVE -> YES -> (overwrite text) -> YES; the native _SaveGameData completion
  Proven sites (F.EXPECT, in this order): wild_ready, capture_party, capture_party_finalized, battle_end,
  save_completed. capture_box must NOT fire (party < 6: PokeBallEffect takes the TryAddMonToParty fork).

  FRAME ALIGNMENT (5.13/B-9): every accepted hit records emu.framecount() inside the callback and the
  frame the main loop armed (framecount before the frameadvance that ran it); they must be equal. At
  capture_party (right after predef TryAddMonToParty) the callback reads wPartyCount: the main loop saw
  N before that frame, the callback sees N+1 (the RAM effect is already there) and the main loop sees
  N+1 after the frame returns. This capture RAM effect IS the frame-alignment control: it substitutes
  plan 5.13's "DMG Gen 1 pin" (coordinator-accepted, card gen2-U1b). Each accepted hit also records the
  MEASURED PC register and hROMBank byte (never the anchor echo), checked against the pinned bank/PC.
  The receipt's evidence_level is PHYSICAL only when the api is this script's own BizHawk binding.

  NEGATIVES (each with a known-positive control): a one-byte-wrong pack refuses at load (the unmutated
  pack binds on the same ROM); an arm moved onto Script_Whiteout bytecode refuses in the binder (the
  same descriptor passes the bare ROM-byte check); a decoy hook at the overworld tick PC claiming an
  unused bank fires raw every overworld frame and is never accepted.

  Environment: the inspect gate's (SLINK_ROOT, run_gb_gate._gen2_plan bindings, SLINK_GEN2_FIXTURE_CASE,
  SLINK_GEN2_ROUTE_FACTS, SLINK_GEN2_QUALIFY stage "boot") plus SLINK_GEN2_U1_FACTS from
  tests/live/test_gen2_frame_align.py: {pack_ui = {kind -> site}, decoy = {symbol, bank, addr, flat, hex},
  prompts = {catch_nickname = {anchor}}, battle_menu = F.grid_menu geometry} (PokeBallEffect asks
  _AskGiveNicknameText, item_effects.asm:574-581, not GiveANickname_YesNo's gift text). SLINK_GEN2_TRACE=1
  logs a state line (phase, UI, readiness, battle mode, PC + stack labels) every 30 frames; any play
  failure logs that line plus the visible screen.
  Printed: HIT_SUMMARY, ALIGN, DECOY, NEGATIVES, PRODUCTION, VERDICT and RECEIPT (json after the tag).
--]]
local F = {}
F.RESULT = "patch/build/gen2_frame_align_result.txt"
F.SCRIPTED_GATE = "lua/tests/test_gen2_scripted_gate.lua"
F.EXPECT = {"wild_ready", "capture_party", "capture_party_finalized", "battle_end", "save_completed"}
F.ABSENT = {"capture_box"}
F.PACK_KINDS = {"pack_items", "pack_balls", "pack_key", "pack_tmhm", "item_submenu"}
-- BattlePack pocket order (engine/items/pack.asm:627-782): items <-> balls <-> key <-> tmhm <-> items.
F.TOWARD_BALLS = {pack_items="Right", pack_key="Left", pack_tmhm="Right"}
-- ponytail: live budgets, not measured; raise if a run needs longer.
F.BUDGET = {max_frames=60000, max_phase_frames=24000, settle_frames=30}
F.MAX_UP_PRESSES = 3
F.HIT_LOG = 32
F.DIRECTIONS = {{"Up", 0, -1}, {"Left", -1, 0}, {"Down", 0, 1}, {"Right", 1, 0}}

local fmt = string.format
local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

-- Pure: the next grass tile to walk to, preferring the tile just left (oscillate in the grass).
function F.walk_direction(map, point, from)
    if not integer(point.x, 0, map.width - 1) or not integer(point.y, 0, map.height - 1) then
        return nil, "player coordinate outside the source map"
    end
    if type(point.can_step) ~= "table" then return nil, "live collision observation missing" end
    local blocked = {}
    for _, object in ipairs(point.blocked or {}) do blocked[object.y * map.width + object.x] = true end
    local best
    for _, d in ipairs(F.DIRECTIONS) do
        local x, y = point.x + d[2], point.y + d[3]
        if x >= 0 and x < map.width and y >= 0 and y < map.height and map.grid[y * map.width + x + 1] == 2
           and point.can_step[d[1]] == true and not blocked[y * map.width + x] then
            if from and from.x == x and from.y == y then return d[1] end
            best = best or d[1]
        end
    end
    if best then return best end
    return nil, fmt("no steppable grass tile next to %d,%d", point.x, point.y)
end

-- Pure: the Ball-pocket cursor row (the ▶ followed by an item name) -> "ball" | "cancel" | nil.
function F.ball_cursor(rows)
    for _, row in ipairs(rows) do
        for x = 1, #row do
            if row[x] == "▶" then
                local rest = table.concat(row, "", x + 1)
                if rest:find("BALL", 1, true) then return "ball" end
                if rest:find("CANCEL", 1, true) then return "cancel" end
            end
        end
    end
    return nil
end

-- Pure: the battle menu read at its SOURCE geometry, not by the scripted gate's parse_menu. That parser
-- joins single-space runs into one item ("POKé BALL"), so with the cursor on FIGHT the row reads
-- "FIGHT <PK><MN>" (the empty column-2 cursor cell is one space) and choose() steered Right/Left forever:
-- the U1 live "phase made no bounded progress: battle". g (tests/live/test_gen2_frame_align.py, from
-- BattleMenuHeader engine/battle/menu.asm:31-48): 0-based first-label cell x,y, rows, columns, spacing
-- and each label's glyphs; the cursor cell is one tile left of each label (engine/menus/menu.asm:159-165).
function F.grid_menu(rows, g)
    local items, cursor = {}, nil
    for r = 0, g.rows - 1 do
        local row = rows[g.y + 2 * r + 1]   -- Place2DMenuItemStrings: rows 2 tiles apart (:117-157)
        if type(row) ~= "table" then return nil end
        for c = 0, g.columns - 1 do
            local index, x = r * g.columns + c + 1, g.x + c * g.spacing + 1
            local glyphs = g.labels[index]
            for i, glyph in ipairs(glyphs) do
                if row[x + i - 1] ~= glyph then return nil end
            end
            if row[x - 1] == "▶" then
                if cursor then return nil end
                cursor = index
            end
            items[index] = table.concat(glyphs)
        end
    end
    if not cursor then return nil end
    return {items=items, cursor=cursor, columns=g.columns}
end

-- Pure: nearest ROM label at or below addr (bank 0 for home), from rgblink .sym text; diagnostics only.
function F.symbols(text)
    local banks = {}
    for bank, addr, name in text:gmatch("(%x%x):(%x%x%x%x) (%S+)") do
        local b, a = tonumber(bank, 16), tonumber(addr, 16)
        if a < 0x8000 then
            banks[b] = banks[b] or {}
            table.insert(banks[b], {a, name})
        end
    end
    return function(bank, addr)
        local list = banks[addr < 0x4000 and 0 or bank] or {}
        local best
        for _, s in ipairs(list) do
            if s[1] <= addr and (best == nil or s[1] > best[1]) then best = s end
        end
        return best and fmt("%s+%d", best[2], addr - best[1]) or fmt("%02X:%04X", bank, addr)
    end
end

-- Pure: one diagnostic line for a trace or a stall; never an oracle.
function F.state_line(tag, frame, phase, point, where)
    local ui = type(point) == "table" and point.ui or nil
    point = type(point) == "table" and point or {}
    return fmt("  %s @%s phase=%s ui=%s prompt=%s ready=%s battle_mode=%s ow=%s items=%s cursor=%s at=%s",
        tag, tostring(frame), tostring(phase), ui and tostring(ui.kind) or "-", ui and tostring(ui.prompt) or "-",
        tostring(point.input_ready), tostring(point.battle_mode), tostring(point.overworld_ready),
        ui and type(ui.items) == "table" and table.concat(ui.items, "|") or "-",
        ui and tostring(ui.cursor) or "-", tostring(where))
end

-- The bounded play; on ANY failure (phase bound, driver refusal) it logs the last point, where the CPU
-- is and the visible screen. diag = {log, frame, screen, where, trace}; trace (SLINK_GEN2_TRACE=1) adds
-- one state line per 30 frames. Budgets stay the host's (max_phase_frames).
F.TRACE_EVERY = 30
function F.play(host, spec, driver, observe, diag)
    local last
    local function locate()
        local placed, where = pcall(diag.where)
        return placed and where or "?"
    end
    local ok, outcome = pcall(host.run, spec, function(frame)
        local point = observe()
        last = point
        local buttons, phase = driver.step(point)
        if buttons == nil then error(phase, 0) end
        if diag.trace and frame % F.TRACE_EVERY == 0 then
            diag.log(F.state_line("trace", frame, phase, point, locate()))
        end
        return buttons, phase, point
    end, function(_, phase, frame) diag.log(fmt("  phase %s @%d", phase, frame)) end)
    if not ok then
        diag.log(F.state_line("stall", diag.frame(), driver.phase, last, locate()))
        local shown, rows = pcall(diag.screen)
        if shown then
            for y, row in ipairs(rows) do diag.log(fmt("  screen %02d |%s|", y, table.concat(row))) end
        end
    end
    return ok, outcome
end

-- Pure point -> buttons, phase. Phases walk -> battle -> save -> saved (terminal).
function F.driver(map)
    local self = {terminal="saved", phase="walk"}
    local HOLD, held, hold_left, release = 12, nil, 0, false
    local here, from, save_counter, confirmed, ups = nil, nil, nil, false, 0
    local function press(button)
        release, held, hold_left = true, button, HOLD - 1
        return {[button]=true}, self.phase
    end
    local function choose(ui, wanted, columns)
        if type(ui.items) ~= "table" or not integer(ui.cursor, 1, #ui.items) or ui.columns ~= columns then
            return nil, "source menu geometry unavailable"
        end
        local target
        for index, label in ipairs(ui.items) do
            if type(label) == "string" and label:upper() == wanted then
                if target then return nil, "ambiguous menu label" end
                target = index
            end
        end
        if not target then return nil, "required native menu item missing: " .. wanted end
        if target == ui.cursor then return press("A") end
        local tx, cx = (target - 1) % columns, (ui.cursor - 1) % columns
        if tx ~= cx then return press(tx > cx and "Right" or "Left") end
        return press(target > ui.cursor and "Down" or "Up")
    end
    function self.step(point)
        if type(point) ~= "table" then return nil, "observation missing" end
        if hold_left > 0 then hold_left = hold_left - 1; return {[held]=true}, self.phase end
        if release then release = false; return {}, self.phase end
        if self.phase == self.terminal then return {}, self.phase end
        local ui = point.ui
        if self.phase == "walk" and integer(point.battle_mode, 1, 255) then self.phase = "battle" end
        if self.phase == "save" and save_counter and point.save_success_counter > save_counter then
            self.phase = self.terminal
            return {}, self.phase
        end
        if ui ~= nil then
            if point.input_ready ~= true then return {}, self.phase end
            if self.phase == "battle" then
                if ui.kind == "battle_menu" then
                    if point.battle_mode ~= 1 then return nil, "battle menu outside a wild battle" end
                    return choose(ui, "PACK", 2)
                end
                if F.TOWARD_BALLS[ui.kind] then return press(F.TOWARD_BALLS[ui.kind]) end
                if ui.kind == "pack_balls" then
                    if point.ball_cursor == "ball" then ups = 0; return press("A") end
                    if point.ball_cursor == "cancel" then
                        ups = ups + 1
                        if ups > F.MAX_UP_PRESSES then return nil, "no Poke Ball left in the pocket" end
                        return press("Up")
                    end
                    return {}, self.phase
                end
                if ui.kind == "item_submenu" then return choose(ui, "USE", 1) end
                if ui.kind == "yes_no" then
                    if ui.prompt ~= "catch_nickname" then return nil, "unmapped battle yes/no prompt" end
                    return choose(ui, "NO", 1)
                end
                if ui.kind == "text" or ui.kind == "prompt_button" or ui.kind == "wait_button" then return press("A") end
                return nil, "UI is not valid in battle: " .. tostring(ui.kind)
            end
            if self.phase == "save" then
                if ui.kind == "start_menu" then return choose(ui, "SAVE", 1) end
                if ui.kind == "yes_no" and ui.prompt == "save_confirm" then
                    confirmed = true
                    return choose(ui, "YES", 1)
                end
                if ui.kind == "yes_no" and ui.prompt == "save_overwrite" then
                    if point.hits.same_save_file < 1 then return nil, "overwrite prompt is not the same-player branch" end
                    return choose(ui, "YES", 1)
                end
                if ui.kind == "prompt_button" and confirmed and ui.prompt == "save_overwrite_text" then return press("A") end
            end
            return nil, "UI is not valid in phase " .. self.phase .. ": " .. tostring(ui.kind)
        end
        if point.hits.erase_save > 0 then return nil, "ErasePreviousSave ran" end
        if point.overworld_ready ~= true then return {}, self.phase end
        if self.phase == "battle" then
            if point.probe_hits.capture_party < 1 then return nil, "the battle ended without a catch" end
            self.phase = "save"
        end
        if self.phase == "save" then
            save_counter = save_counter or point.save_success_counter
            return press("Start")
        end
        if here and (here.x ~= point.x or here.y ~= point.y) then from = here end
        here = {x=point.x, y=point.y}
        local button, why = F.walk_direction(map, point, from)
        if not button then return nil, why end
        return {[button]=true}, self.phase
    end
    return self
end

-- Pure verdict over the probe record: problems (empty = PASS) and the proven site list.
function F.verdict(record)
    local problems = {}
    local function need(ok, what) if not ok then problems[#problems + 1] = what end end
    need(record.registry_failed == nil, "hook registry latched a failure: " .. tostring(record.registry_failed))
    need(record.accept_errors == 0, "binder accept faults")
    need(record.aligned >= 1 and record.misaligned == 0,
         fmt("callback frame != armed frame on %d of %d hits", record.misaligned, record.aligned + record.misaligned))
    local a = record.align
    need(a ~= nil and a.callback == a.armed and integer(a.pre_party, 0, 5) and a.callback_party == a.pre_party + 1
         and a.post_party == a.callback_party, "capture_party RAM effect is not aligned to the callback frame")
    local sites, previous = record.sites, 0
    for _, name in ipairs(F.EXPECT) do
        local site, found = sites[name], nil
        for _, hit in ipairs(site and site.log or {}) do
            if hit.seq > previous then found = hit break end
        end
        need(found ~= nil, name .. " did not fire after the previous expected site")
        if found then previous = found.seq end
        need(site ~= nil and site.pc == site.addr and site.hit_bank == site.bank and site.off_pin == 0,
             name .. " hit off its pinned bank/PC (measured)")
    end
    need(sites.capture_party and sites.capture_party.hits == 1, "capture_party must fire exactly once")
    for _, name in ipairs(F.ABSENT) do need(sites[name] and sites[name].hits == 0, name .. " fired on a party < 6 catch") end
    need(record.decoy.raw >= 1 and record.decoy.accepted == 0 and record.decoy.bank_rejects == record.decoy.raw,
         "wrong-bank decoy: no raw fire, an accepted hit, or a hit not rejected by bank")
    for _, name in ipairs({"wrong_pack_byte", "script_bytecode_arm", "wrong_bank_hit"}) do
        need(record.negatives[name] == "refused", "negative control not refused: " .. name)
    end
    return problems, #problems == 0 and {table.unpack(F.EXPECT)} or {}
end

local function read_json(ctx, rel)
    local f = assert(io.open(ctx.root .. "/" .. rel, "rb"), "cannot open " .. rel)
    local text = f:read("a")
    f:close()
    return assert(ctx.json.decode(text, {items=1000000}), rel .. " malformed")
end

local function copy(value)
    if type(value) ~= "table" then return value end
    local out = {}
    for k, v in pairs(value) do out[k] = copy(v) end
    return out
end

local function binding(ctx)
    local api = ctx.api
    return ctx.Binding.new({read_u8=api.read_u8, read_range=api.read_range, register=api.register,
        framecount=api.framecount, on_bus_exec=api.on_bus_exec, unregister=api.unregister},
        {bus_domain="System Bus", rom_domain="ROM", bank_domain="System Bus", pc_register="PC", sp_register="SP",
         bank_address=ctx.profile.hram.hROMBank})
end

-- Arm every pack site (grouped by bank:PC like lua/gen2/signals.lua) plus the wrong-bank decoy.
function F.probe(ctx, pack, decoy_site)
    local Registry = dofile(ctx.root .. "/lua/hook_registry.lua")
    local B = binding(ctx)
    local sites = pack.titles.crystal.sites
    local record = {sites={}, aligned=0, misaligned=0, accept_errors=0, seq=0,
                    decoy={raw=0, accepted=0, bank_rejects=0}, negatives={}}
    local groups, descriptors = {}, {}
    local logged = {}
    for _, name in ipairs(F.EXPECT) do logged[name] = true end
    for _, name in ipairs(F.ABSENT) do logged[name] = true end
    local names = {}
    for name in pairs(sites) do names[#names + 1] = name end
    table.sort(names)
    for _, name in ipairs(names) do
        local site = sites[name]
        record.sites[name] = {bank=site.bank, addr=site.addr, expected_hex=site.expected_hex, symbol=site.symbol,
                              raw=0, bank_rejects=0, hits=0, off_pin=0, log={}}
        local id = fmt("bank%03d_pc%04X", site.bank, site.addr)
        if not groups[id] then
            groups[id] = {id=id, members={}}
            descriptors[#descriptors + 1] = groups[id]
        end
        table.insert(groups[id].members, name)
    end
    descriptors[#descriptors + 1] = {id="decoy_wrong_bank", members={}, decoy=true}
    local probe = {record=record}
    local service, why = Registry.new({owner="gen2-u1-probe", max_pending=1, sites=descriptors,
        validate=function(group)
            local out = {id=group.id, members=group.members, decoy=group.decoy}
            if group.decoy then
                out.anchor = B:validate({id="decoy_wrong_bank", bank=decoy_site.bank, address=decoy_site.addr,
                    capture_offset=0, rom_offset=decoy_site.flat, expected_hex=decoy_site.hex})
                return out
            end
            for _, name in ipairs(group.members) do
                local site = sites[name]
                local checked = B:validate({id=name, bank=site.bank, address=site.addr, capture_offset=0,
                    rom_offset=site.rom_offset, expected_hex=site.expected_hex})
                if not out.anchor or #checked.expected > #out.anchor.expected then out.anchor = checked end
            end
            return out
        end,
        register=function(prepared, callback, name) return B:register(prepared.anchor, callback, name) end,
        unregister=function(handle) return B:unregister(handle) end,
        valid_handle=function(handle) return B:valid_handle(handle) end,
        capture=function(prepared)
            if prepared.decoy then
                record.decoy.raw = record.decoy.raw + 1
                if B:context(prepared.anchor) then record.decoy.accepted = record.decoy.accepted + 1
                else record.decoy.bank_rejects = record.decoy.bank_rejects + 1 end
                return nil
            end
            for _, name in ipairs(prepared.members) do record.sites[name].raw = record.sites[name].raw + 1 end
            local hit = B:context(prepared.anchor)
            if not hit then
                for _, name in ipairs(prepared.members) do
                    record.sites[name].bank_rejects = record.sites[name].bank_rejects + 1
                end
                return nil
            end
            -- Measured, not the binder's anchor echo: the live PC register and the hROMBank byte.
            local pc, bank = ctx.api.register("PC"), ctx.api.read_u8(ctx.profile.hram.hROMBank, "System Bus")
            if probe.armed == hit.frame then record.aligned = record.aligned + 1
            else record.misaligned = record.misaligned + 1 end
            record.seq = record.seq + 1
            for _, name in ipairs(prepared.members) do
                local s = record.sites[name]
                s.hits = s.hits + 1
                if pc ~= s.addr or bank ~= s.bank then s.off_pin = s.off_pin + 1 end
                if s.first_frame == nil then s.first_frame, s.pc, s.hit_bank = hit.frame, pc, bank end
                if logged[name] and #s.log < F.HIT_LOG then
                    s.log[#s.log + 1] = {seq=record.seq, frame=hit.frame, armed=probe.armed}
                end
                if name == "capture_party" and record.align == nil then
                    record.align = {armed=probe.armed, callback=hit.frame, pre_party=probe.pre_party,
                                    callback_party=ctx.sym("wPartyCount")[1]}
                end
            end
            return nil
        end})
    assert(service, "engine-site probe refused to arm: " .. tostring(why))
    -- The main loop's frameadvance, wrapped: the armed frame and wPartyCount either side of it.
    local api = ctx.api
    local advance = api.advance
    function api.advance()
        probe.armed, probe.pre_party = api.framecount(), ctx.sym("wPartyCount")[1]
        advance()
        probe.armed = nil
        if record.align and record.align.post_party == nil then record.align.post_party = ctx.sym("wPartyCount")[1] end
    end
    function probe.release()
        api.advance = advance
        local status = service:status()
        record.registry_failed = status.failed
        record.accept_errors = B:status().accept_errors
        service:close()
    end
    return probe
end

-- Live binder options (MODEL for the negatives, PHYSICAL_RUNTIME for the production check).
local function binder_options(ctx, wrapper, pack, owner, physical)
    local api = ctx.api
    local io_ = {model_only=not physical or nil, read_u8=api.read_u8, read_range=api.read_range,
        register=api.register, framecount=api.framecount, on_bus_exec=api.on_bus_exec, unregister=api.unregister,
        bank_valid=function() return false end, stack_valid=function() return false end}
    local authority = {kind=physical and "PHYSICAL_RUNTIME" or "MODEL_PROBE", allow_model_registration=not physical or nil,
        capture=function() return {generation=1, operation="u1-probe"} end, valid=function() return false end}
    return {title=ctx.env.title, profile=wrapper, pack=pack, io=io_, authority=authority, reads=ctx.reads,
            Registry=dofile(ctx.root .. "/lua/hook_registry.lua"), GB=dofile(ctx.root .. "/lua/gb_hook_binding.lua"),
            owner=owner, max_pending=8}
end

-- The load-time refusals, each beside its known-positive control on the same live ROM.
function F.negatives(ctx, Signals, wrapper, pack)
    local out, detail = {}, {}
    local control, why = Signals.new_model(binder_options(ctx, wrapper, pack, "gen2-u1-control"))
    detail.control = control and "bound" or tostring(why)
    if control then control:close() end

    local bad = copy(pack)
    local site = bad.titles.crystal.sites.capture_party
    site.expected_hex = fmt("%02x", (tonumber(site.expected_hex:sub(1, 2), 16) + 1) % 256) .. site.expected_hex:sub(3)
    local refused, reason = Signals.new_model(binder_options(ctx, wrapper, bad, "gen2-u1-bad-byte"))
    if refused then refused:close() end
    detail.wrong_pack_byte = tostring(reason)
    out.wrong_pack_byte = (control and not refused and tostring(reason):find("differ from the ROM", 1, true))
        and "refused" or "NOT refused"

    local script = copy(pack)
    local sites = script.titles.crystal.sites
    local ctx_script = sites.whiteout_before_heal.guards.script_context
    local arm = sites.capture_party
    arm.bank, arm.addr, arm.expected_hex = ctx_script.bank, ctx_script.addr, ctx_script.expected_hex
    arm.rom_offset = ctx_script.bank * 0x4000 + ctx_script.addr - 0x4000
    -- Known positive: the moved descriptor's bytes ARE the ROM's, so only the binder rule can refuse it.
    local bytes_ok = pcall(function()
        binding(ctx):validate({id="script_arm", bank=arm.bank, address=arm.addr, capture_offset=0,
                               rom_offset=arm.rom_offset, expected_hex=arm.expected_hex})
    end)
    refused, reason = Signals.new_model(binder_options(ctx, wrapper, script, "gen2-u1-script-arm"))
    if refused then refused:close() end
    detail.script_bytecode_arm = tostring(reason)
    out.script_bytecode_arm = (bytes_ok and not refused and tostring(reason):find("script bytecode", 1, true))
        and "refused" or "NOT refused"
    return out, detail
end

local live_api   -- set only by this file's own BizHawk entry below; a library caller cannot claim it

function F.main(api, getenv, SG)
    local evidence = (live_api ~= nil and api == live_api) and "PHYSICAL" or "MODEL"
    local root = getenv("SLINK_ROOT") or SLINK_ROOT or "."
    local lines, failures = {}, 0
    local function log(s)
        lines[#lines + 1] = s
        local f = io.open(root .. "/" .. F.RESULT, "w")
        if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    end
    local function check(what, ok, detail)
        if not ok then failures = failures + 1 end
        log(fmt("  [%s] %s%s", ok and "ok" or "FAIL", what, detail and ("  -- " .. tostring(detail)) or ""))
        return ok
    end
    local function finish(extra)
        log(fmt("RESULT: %s %s (%d checks failed)", failures == 0 and "PASS" or "FAIL", extra or "u1", failures))
        return failures == 0
    end
    log("[gen2_frame_align] U1 Crystal engine-hook proof + frame-alignment probe")

    local ok, ctx = pcall(function()
        SG = SG or F.scripted_gate(root)
        local c = SG.context(api, getenv)
        assert(c.env.title == "crystal" and c.case.name == "crystal_battle", "U1 runs on crystal_battle only")
        assert(c.qualify ~= nil and c.qualify.stage == "boot", "SLINK_GEN2_QUALIFY stage \"boot\" required")
        c.u1 = assert(c.json.decode(assert(getenv("SLINK_GEN2_U1_FACTS"), "SLINK_GEN2_U1_FACTS missing")))
        assert(type(c.u1.battle_menu) == "table", "U1 facts lack the battle menu geometry")
        return c
    end)
    if not check("environment, facts, profile and running ROM/CGB bound", ok, not ok and ctx or nil) then
        return finish("bad environment")
    end
    ctx.log = log
    local json = ctx.json
    local wrapper = read_json(ctx, "data/games/gen2_crystal/profile.json")
    local pack = read_json(ctx, "data/games/gen2_crystal/engine_signals.json")
    local Signals = dofile(ctx.root .. "/lua/gen2/signals.lua")

    -- The pack-UI origins and the item submenu join the scripted gate's UI context (this gate's own
    -- in-memory copy of the facts; the shared driver and its facts file are not changed).
    for _, kind in ipairs(F.PACK_KINDS) do
        ctx.facts.ui_origins[kind] = assert(ctx.u1.pack_ui[kind], "U1 facts lack " .. kind)
    end
    SG.MENU_KINDS.item_submenu = true
    local prompts = {}
    for k, v in pairs(ctx.obs.prompts) do prompts[k] = v end
    for k, v in pairs(ctx.prompts) do prompts[k] = v end
    for k, v in pairs(ctx.u1.prompts) do prompts[k] = v end
    ctx.prompts = prompts

    local negatives, detail = F.negatives(ctx, Signals, wrapper, pack)
    log("NEGATIVES " .. json.encode(detail))

    -- Arrival: gen2_qualify.lua "boot" over the scripted gate hooks (the inspect gate's path).
    local state = SG.hooks(ctx)
    local idle = {}
    for _, name in ipairs(SG.BUTTONS) do idle[name] = false end
    local host = ctx.Host.new({step=SG.button_step(ctx), frame=api.framecount, idle=idle})
    local case, q = ctx.case, ctx.qualify
    local arrived, result = pcall(ctx.Qualify.run, host, SG.qualify_observer(ctx), ctx.facts, q.facts,
        {name=case.name, title=case.title, attempt_id=case.attempt_id, stage="boot",
         stage_fingerprint=q.stage_fingerprint, max_frames=case.max_frames,
         max_phase_frames=case.max_phase_frames, settle_frames=case.settle_frames})
    if not check("post-CONTINUE overworld arrival", arrived, not arrived and result or nil) then
        state.release()
        return finish("no arrival")
    end

    local probe = F.probe(ctx, pack, ctx.u1.decoy)
    local base = SG.qualify_observer(ctx)
    local function observe()
        local point = base()
        point.probe_hits = {capture_party=probe.record.sites.capture_party.hits}
        if point.ui and point.ui.kind == "pack_balls" then point.ball_cursor = F.ball_cursor(SG.screen(ctx)) end
        if point.ui and point.ui.kind == "battle_menu" then
            local menu = F.grid_menu(SG.screen(ctx), ctx.u1.battle_menu)
            if menu then point.ui.items, point.ui.cursor, point.ui.columns = menu.items, menu.cursor, menu.columns
            else point.input_ready = false end
        end
        return point
    end
    local symbol_at
    local function where()   -- PC and the ROM words on the stack, as bank-guessed labels (diagnostics only)
        if symbol_at == nil then
            local f = assert(io.open(ctx.root .. "/data/gen2/pokecrystal.sym", "rb"))
            symbol_at = F.symbols(f:read("a"))
            f:close()
        end
        local bank, sp = api.read_u8(ctx.profile.hram.hROMBank, "System Bus"), api.register("SP")
        local out = {symbol_at(bank, api.register("PC"))}
        for i = 0, 7 do
            local word = api.read_u8(sp + 2 * i, "System Bus") + 256 * api.read_u8(sp + 2 * i + 1, "System Bus")
            if word >= 0x0100 and word < 0x8000 then out[#out + 1] = symbol_at(bank, word) end
        end
        return table.concat(out, "<")
    end
    local driver = F.driver(ctx.facts.maps.Route29)
    local played, outcome = F.play(host, {name="u1-crystal", terminal=driver.terminal,
        max_frames=F.BUDGET.max_frames, max_phase_frames=F.BUDGET.max_phase_frames,
        settle_frames=F.BUDGET.settle_frames, terminal_idle=true}, driver, observe,
        {log=log, frame=api.framecount, screen=function() return SG.screen(ctx) end, where=where,
         trace=getenv("SLINK_GEN2_TRACE") == "1"})
    probe.release()
    state.release()
    local record = probe.record
    record.negatives = negatives
    record.negatives.wrong_bank_hit = (record.decoy.raw >= 1 and record.decoy.accepted == 0) and "refused" or "NOT refused"
    check("walk -> wild encounter -> Poke Ball catch -> native save", played, not played and outcome or nil)

    local summary = {}
    for name, s in pairs(record.sites) do
        if s.raw > 0 then
            summary[name] = {hits=s.hits, raw=s.raw, bank_rejects=s.bank_rejects, first_frame=s.first_frame,
                             pc=s.pc, bank=s.hit_bank, off_pin=s.off_pin, log=s.log}
        end
    end
    log("HIT_SUMMARY " .. json.encode(json.object(summary)))
    log("ALIGN " .. json.encode({align=record.align or json.null, aligned=record.aligned, misaligned=record.misaligned}))
    log("DECOY " .. json.encode({site=ctx.u1.decoy, raw=record.decoy.raw, accepted=record.decoy.accepted,
                                  bank_rejects=record.decoy.bank_rejects}))
    local problems, proven = F.verdict(record)
    log("VERDICT " .. json.encode(json.object({problems=json.array(problems), proven=json.array(proven)})))
    for _, problem in ipairs(problems) do check(problem, false) end
    if not played or #problems > 0 then return finish("no receipt") end

    local sites = {}
    for _, name in ipairs(F.EXPECT) do
        local s = record.sites[name]
        sites[name] = {bank=s.bank, addr=s.addr, pc=s.pc, expected_hex=s.expected_hex, symbol=s.symbol,
                       hits=s.hits, raw=s.raw, bank_rejects=s.bank_rejects, first_frame=s.first_frame}
    end
    for _, name in ipairs(F.ABSENT) do
        local s = record.sites[name]
        sites[name] = {bank=s.bank, addr=s.addr, expected_hex=s.expected_hex, symbol=s.symbol, hits=0, raw=s.raw}
    end
    local a = record.align
    local receipt = {schema=Signals.RECEIPT_SCHEMA, title="crystal", evidence_level=evidence, result="PASS",
        rom_sha1=pack.source.rom_sha1, pack_commit=pack.source.commit, pack_specs_sha256=pack.specs_sha256,
        fixture=case.name, attempt_id=case.attempt_id, core_mode="CGB", input_mode="normal_buttons",
        fixture_sha256=q.stage_fingerprint, qualification_attempt_id=ctx.u1.qualification_attempt_id,
        harness_write_scopes=json.array({}), bank_check="live",
        frame_alignment={passed=true, rule="callback emu.framecount() == the frame being emulated (armed); "
            .. "the site's RAM effect is visible inside the callback and to the main loop at armed+1",
            armed=a.armed, callback=a.callback, pre_party=a.pre_party, callback_party=a.callback_party,
            post_party=a.post_party, aligned_hits=record.aligned, misaligned_hits=record.misaligned},
        negatives=record.negatives, decoy={bank=ctx.u1.decoy.bank, addr=ctx.u1.decoy.addr, raw=record.decoy.raw,
            accepted=record.decoy.accepted, bank_rejects=record.decoy.bank_rejects},
        sites=sites, proven=json.array(proven), absent=json.array(F.ABSENT)}

    -- The production gate on this very ROM: the receipt registers exactly the proven sites; Gold refuses.
    local options = binder_options(ctx, wrapper, pack, "gen2-u1-production", true)
    options.runtime_qualification = receipt
    local service, why = Signals.new(options)
    local registered = service and service:status().registered_sites or {}
    if service then service:close() end
    table.sort(proven)
    check("production Signals.new registers exactly the receipted sites",
          service ~= nil and table.concat(registered, ",") == table.concat(proven, ","),
          service and table.concat(registered, ",") or why)
    options.title, options.owner = "gold", "gen2-u1-production-gold"
    local gold, gold_why = Signals.new(options)
    if gold then gold:close() end
    check("production Signals.new refuses Gold", gold == nil, gold_why)
    log("PRODUCTION " .. json.encode({registered=json.array(registered), gold_refusal=tostring(gold_why)}))
    if failures == 0 then log("RECEIPT " .. json.encode(receipt)) end
    return finish()
end

function F.scripted_gate(root)
    local previous = SLINK_GEN2_GATE_LIBRARY
    SLINK_GEN2_GATE_LIBRARY = true
    local ok, SG = pcall(dofile, root .. "/" .. F.SCRIPTED_GATE)
    SLINK_GEN2_GATE_LIBRARY = previous
    assert(ok and type(SG) == "table", "cannot load " .. F.SCRIPTED_GATE .. ": " .. tostring(SG))
    return SG
end

if SLINK_GEN2_GATE_LIBRARY then return F end

local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(ROOT, "SLINK_ROOT unset -- launch via tools/run_gb_gate.py")
local SG = F.scripted_gate(ROOT)
local api = SG.bizhawk()
live_api = api
F.main(api, os.getenv, SG)
api.exit()
error("slink-gate-finished", 0)   -- client.exit() is asynchronous; stop here for real
