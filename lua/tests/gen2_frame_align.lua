--[[
  lua/tests/gen2_frame_align.lua -- card gen2-U1 (Crystal) / gen2-U1-GS (Gold, Silver): the engine-hook
  proof on the RUNNING cartridge (docs/gen2/GEN2_BINDING_PLAN.md P3b.4: the 5.13 frame-alignment probe,
  B-9, and the 5.11 engine-sequence proof; docs/gen2/reviews/P3B7_PLAN_CODEX_2026-09-23.md row U1).

  PER TITLE (SLINK_GEN2_TITLE; the fixture is <title>_battle): the title's own profile, engine_signals
  pack rows and .sym, and its own route facts' UI origins (battle_menu = BattleMenu, C 0f:6139, G/S
  0f:5f9a; the menu is read by G.BATTLE_MENU_GRID, valid for G/S per N17). Silver's capture rows sit 2
  bytes below Gold's (docs/gen2/reviews/OMP_U1_BATTLE_FACTS_2026-09-23.md O10), so no title borrows
  another's rows and each writes its own <title>.engine_sites.json. G/S capture_party is the
  `ld a, [wCurItem]` right after predef TryAddMonToParty (pokegold engine/items/item_effects.asm:556-558),
  the same point as Crystal's `farcall SetCaughtData`, so the frame-alignment rule below is unchanged.

  Result file: patch/build/gen2_frame_align_result.txt (RESULT: PASS|FAIL, last line).

  Boots <title>_battle WARM (Route 29 grass, the fixture's recorded O-10 Ball stack already in the save;
  no harness write of any kind here), arrives through the same source-qualified CONTINUE path the
  inspect gate uses, then arms EVERY engine_signals.json site through the shared lua/hook_registry.lua +
  lua/gb_hook_binding.lua (load-time expected_hex check in the ROM domain, hROMBank filter, PC == site,
  bytes re-read on the System Bus at fire time) and plays with normal buttons only:
    walk      hold a direction per frame between Route 29 grass tiles until wBattleMode != 0
    battle    BattleMenu PACK -> the Ball pocket -> POKe BALL -> USE, A through battle text, NO to the
              nickname, repeated until the catch; the battle ends natively
    save      START -> SAVE -> YES -> (overwrite text) -> YES; the native _SaveGameData completion
    faint     (card gen2-U1d; lua/tests/duo/gen2_faint_inputs.lua, shared with the H1c faint duo) walk into a
              second wild battle; the lead (party = [starter, catch]) uses a status move until it faints; NO
              to "Use next #MON?", out to the overworld (no second save)
  Proven sites (F.EXPECT, in this order): wild_ready, capture_party, capture_party_finalized, battle_end,
  save_completed, battle_faint. capture_box must NOT fire (party < 6: PokeBallEffect takes the TryAddMonToParty
  fork). battle_faint's own alignment rule is F.faint_snapshot / F.faint_problem (receipt faint_alignment).

  FRAME ALIGNMENT (5.13/B-9): every accepted hit records emu.framecount() inside the callback and the
  frame the main loop armed (framecount before the frameadvance that ran it); they must be equal. At
  capture_party (right after predef TryAddMonToParty) the callback reads wPartyCount: N at the wild_ready
  hit (battle_party), N+1 inside the callback (the RAM effect is already there) and N+1 to the main loop
  after the frame returns. TryAddMonToParty increments wPartyCount in its first instructions and then runs
  GeneratePartyMonStats (move_mon.asm:3-19, :94-264), so the increment may land frames BEFORE the callback
  (live U1 rerun: pre_party == callback_party; pokegold move_mon.asm:3-19 is the same code). The main
  loop samples wPartyCount after every frame and records the first frame it changed (party_changed <=
  callback; the receipt states the distance). This capture RAM effect IS the frame-alignment control: it
  substitutes plan 5.13's "DMG Gen 1 pin" (coordinator-accepted, card gen2-U1b). Each accepted hit also records the
  MEASURED PC register and hROMBank byte (never the anchor echo), checked against the pinned bank/PC.
  The receipt's evidence_level is PHYSICAL only when the api is this script's own BizHawk binding.

  NEGATIVES (each with a known-positive control): a one-byte-wrong pack refuses at load (the unmutated
  pack binds on the same ROM); an arm moved onto Script_Whiteout bytecode refuses in the binder (the
  same descriptor passes the bare ROM-byte check); a decoy hook at the overworld tick PC claiming an
  unused bank fires raw every overworld frame and is never accepted.

  Environment: the inspect gate's (SLINK_ROOT, run_gb_gate._gen2_plan bindings, SLINK_GEN2_FIXTURE_CASE,
  SLINK_GEN2_ROUTE_FACTS, SLINK_GEN2_QUALIFY stage "boot") plus SLINK_GEN2_U1_FACTS from
  tests/live/test_gen2_frame_align.py: {pack_ui = {kind -> site}, decoy = {symbol, bank, addr, flat, hex},
  prompts = {catch_nickname = {anchor}}} (PokeBallEffect asks _AskGiveNicknameText, C item_effects.asm:
  574-581, G :572-578, not GiveANickname_YesNo's gift text). The battle menu is read through the
  shared gate's G.parse_menu + G.BATTLE_MENU_GRID (the N17 constant, pinned to BattleMenuHeader by
  tests/unit/test_gen2_scripted_gate.py), never a local geometry. SLINK_GEN2_TRACE=1
  logs a state line (phase, UI, readiness, battle mode, PC + stack labels) every 30 frames; any play
  failure logs that line plus the visible screen.
  Printed: HIT_SUMMARY, ALIGN, DECOY, NEGATIVES, PRODUCTION, VERDICT and RECEIPT (json after the tag).
--]]
local F = {}
F.RESULT = "patch/build/gen2_frame_align_result.txt"
F.SCRIPTED_GATE = "lua/tests/test_gen2_scripted_gate.lua"
F.EXPECT = {"wild_ready", "capture_party", "capture_party_finalized", "battle_end", "save_completed", "battle_faint"}
F.FAINT_INPUTS = "lua/tests/duo/gen2_faint_inputs.lua"
-- card gen2-u1e-poison: with SLINK_GEN2_U1_FACTS.poison the play gains a poison leg between the save and the
-- faint leg (lua/tests/gen2_poison_inputs.lua), poison_faint joins the expected sites before battle_faint, and
-- the faint leg runs on the poison leg's hunt map (the catch, last mon standing, faints there).
F.POISON_INPUTS = "lua/tests/gen2_poison_inputs.lua"
-- Crystal day Route 30: Weedle is 5%; 1 - 0.95^59 = 95.15% candidate coverage
-- under independent rolls (poisoning still needs its own successful hit).
-- Observed ~20 encounters/60000 hunt frames -> 59*3000=177000, plus 33000
-- for travel/healing/poison ticks. Equal phase/total caps remove the old
-- 60000-frame hunt cutoff; this estimates coverage, not an RNG guarantee.
F.POISON_BUDGET = {max_frames=210000, max_phase_frames=210000}
F.POISON_FAINT_BATTLES = 12   -- ponytail: the catch fights to its faint; damage carries between battles
-- card gen2-u1f-pc: with SLINK_GEN2_U1_FACTS.pc, after the chain's closing whiteout a second catch and Bill's PC
-- (lua/tests/gen2_pc_inputs.lua) prove the PC sites, in this order; whiteout_before_heal is proven by its own
-- guard-matching record (F.whiteout_problem), never by the hit log (`Special` is a hot shared site).
F.PC_INPUTS = "lua/tests/gen2_pc_inputs.lua"
F.U1F_SITES = {"pc_deposit_begin", "pc_deposit_complete", "pc_withdraw_begin", "pc_withdraw_complete",
               "change_box_begin", "change_box_loaded", "pc_release_box_begin", "pc_release_box_complete",
               "pc_release_party_begin", "pc_release_party_complete"}
F.U1F_BUDGET = {max_frames=60000, max_phase_frames=24000}
-- card EVO-U1: with SLINK_GEN2_U1_FACTS.evolution, after the PC leg a third catch (a Caterpie/Weedle on Route 30) is
-- switch-trained to L7 and evolves natively (lua/tests/gen2_evolution_inputs.lua); evolution_species_published joins
-- the expected sites last, with its own same-frame record (F.evolution_problem) and MODEL key_change.
F.EVOLUTION_INPUTS = "lua/tests/gen2_evolution_inputs.lua"
F.U1G_INPUTS = "lua/tests/gen2_u1g_inputs.lua"   -- card U1G: the synthetic-fixture runs (receipt v2)
F.EVOLUTION_SITE = "evolution_species_published"
F.EVOLUTION_BUDGET = {max_frames=600000, max_phase_frames=30000}   -- ponytail: ~25 wins + heals, not measured
function F.expect(poison, pc, evolution)
    local out = {}
    for _, name in ipairs(F.EXPECT) do
        if poison and name == "battle_faint" then out[#out + 1] = "poison_faint" end
        out[#out + 1] = name
    end
    if pc then
        for _, name in ipairs(F.U1F_SITES) do out[#out + 1] = name end
        out[#out + 1] = "whiteout_before_heal"   -- proven by its own record (F.whiteout_problem), not the log order
    end
    if evolution then out[#out + 1] = F.EVOLUTION_SITE end
    return out
end
F.ABSENT = {"capture_box"}
F.PACK_KINDS = {"pack_items", "pack_balls", "pack_key", "pack_tmhm", "item_submenu"}
-- BattlePack pocket order (engine/items/pack.asm:627-782): items <-> balls <-> key <-> tmhm <-> items.
F.TOWARD_BALLS = {pack_items="Right", pack_key="Left", pack_tmhm="Right"}
-- ponytail: live budgets, not measured; raise if a run needs longer.
F.BUDGET = {max_frames=60000, max_phase_frames=24000, settle_frames=30}
F.MAX_UP_PRESSES = 3
F.HIT_LOG = 32
-- the one shared step rule (ledges from the separate map.ledges field), from beside this file
local W = (function(dir)   -- beside this file, else $SLINK_ROOT/lua/tests (a copy run from elsewhere)
    local f = io.open(dir .. "gen2_walk.lua", "rb")
    if f then f:close() else dir = (os.getenv("SLINK_ROOT") or ".") .. "/lua/tests/" end
    return dofile(dir .. "gen2_walk.lua")
end)(debug.getinfo(1, "S").source:match("^@(.-)[^/\\]*$") or "lua/tests/")
F.DIRECTIONS = W.DIRECTIONS
-- Per title: the rgblink .sym (diagnostics) and the title whose production binder must refuse this
-- title's receipt (Crystal keeps its original Gold refusal; Gold and Silver refuse each other).
F.SYM = {crystal="pokecrystal", gold="pokegold", silver="pokesilver"}
-- The symbol table of the EXECUTED cartridge (diagnostics): the clean rgblink .sym, or for an overlay its own
-- data/gen2/<title>_slink.sym (bank 4 labels may have moved; the clean table is never read for it).
function F.sym_file(ctx)
    local name = (ctx.artifact and ctx.artifact.kind == "overlay") and (ctx.env.title .. "_slink") or F.SYM[ctx.env.title]
    return ctx.root .. "/data/gen2/" .. name .. ".sym"
end
F.REFUSE = {crystal="gold", gold="silver", silver="gold"}
F.NAMES = {crystal="Crystal", gold="Gold", silver="Silver"}
F.U1_FIXTURES = {crystal_battle="crystal", gold_battle="gold", gold_battle_errand="gold", silver_battle="silver"}

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
    local step = W.stepper(map, point.can_step)   -- gen2_walk.lua: off a ledge onto grass is a hop
    for _, d in ipairs(F.DIRECTIONS) do
        local x, y, tile = step(point.x, point.y, d, true)
        if tile == 2 and not blocked[y * map.width + x] then
            if from and from.x == x and from.y == y then return d[1] end
            best = best or d[1]
        end
    end
    if best then return best end
    return nil, fmt("no steppable grass tile next to %d,%d", point.x, point.y)
end

-- Pure: the Ball-pocket cursor row (the ▶ followed by an item name) -> "ball" | "cancel" | nil, then, when the
-- cursor is on another Ball and a MASTER BALL row is on screen, the press toward it ("Up" | "Down"): a Master Ball
-- never misses (PokeBallEffect, engine/items/item_effects.asm; gen2_trade_evolve's A seed, TRADE-EVOLVE-CATCH).
function F.ball_cursor(rows)
    local kind, at, master
    for y, row in ipairs(rows) do
        if not master and table.concat(row, ""):find("MASTER BALL", 1, true) then master = y end
        for x = 1, #row do
            if not kind and row[x] == "▶" then
                local rest = table.concat(row, "", x + 1)
                if rest:find("BALL", 1, true) then kind, at = "ball", y
                elseif rest:find("CANCEL", 1, true) then kind, at = "cancel", y end
            end
        end
    end
    if kind == "ball" and master and master ~= at then return kind, master < at and "Up" or "Down" end
    return kind
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
    local steps = {}
    for _, d in ipairs(F.DIRECTIONS) do
        if type(point.can_step) == "table" then steps[#steps + 1] = d[1]:sub(1, 1) .. (point.can_step[d[1]] and "1" or "0") end
    end
    return fmt("  %s @%s phase=%s ui=%s prompt=%s ready=%s battle_mode=%s ow=%s items=%s cursor=%s map=%s:%s xy=%s,%s step=%s at=%s",
        tag, tostring(frame), tostring(phase), ui and tostring(ui.kind) or "-", ui and tostring(ui.prompt) or "-",
        tostring(point.input_ready), tostring(point.battle_mode), tostring(point.overworld_ready),
        ui and type(ui.items) == "table" and table.concat(ui.items, "|") or "-",
        ui and tostring(ui.cursor) or "-", tostring(point.map_group), tostring(point.map_number),
        tostring(point.x), tostring(point.y), table.concat(steps), tostring(where))
end

-- The bounded play; on ANY failure (phase bound, driver refusal) it logs the last point, where the CPU
-- is and the visible screen. diag = {log, frame, screen, where, trace}; trace (SLINK_GEN2_TRACE=1) adds
-- one state line per 30 frames. Budgets stay the host's (max_phase_frames).
-- Every leg first SETTLES: it idles until the overworld tick is back or a battle is up. A leg that starts
-- right after a save would otherwise see the save's overwrite yes_no as the newest UI: save_completed fires
-- at _SaveGameData, then SavedTheGame idles 32 frames + text + SFX + 30 frames with no UI origin and no
-- overworld tick (C engine/menus/save.asm:241-264; U1d live run 1, the C<->G faint duo's RED run 2).
F.TRACE_EVERY = 30
-- All walkers share this interruption path, including the wrapped trade/synth
-- drivers. phone_call comes ONLY from the scripted observer's bank/byte-checked
-- RingTwice_StartCall hook; a pending special-call ID is not an active call.
-- Keep the route's state and budgets, pulse A at ready text, release between
-- pulses, and let the original driver reject every other unexpected UI.
function F.phone_handler()
    local down = false
    return function(point)
        if point.phone_call ~= true or point.battle_mode ~= 0 then down = false return nil end
        local ui = point.ui
        if ui and ui.kind ~= "text" and ui.kind ~= "prompt_button" and ui.kind ~= "wait_button" then
            down = false
            return nil
        end
        if down then down = false return {} end
        if ui and point.input_ready == true then down = true return {A=true} end
        return {}
    end
end

function F.play(host, spec, driver, observe, diag)
    local last, settled = nil, false
    local phone, route_phase = F.phone_handler(), driver.phase or "settle"
    local function locate()
        local placed, where = pcall(diag.where)
        return placed and where or "?"
    end
    local ok, outcome = pcall(host.run, spec, function(frame)
        local point = observe()
        last = point
        -- A new leg can start while a call is already up, before its first OW tick.
        local answer = phone(point)
        if answer then return answer, route_phase, point end
        settled = settled or point.overworld_ready == true or integer(point.battle_mode, 1, 255)
        if not settled then return {}, "settle", point end
        local buttons, phase = driver.step(point)
        if buttons == nil then error(phase, 0) end
        route_phase = phase
        if diag.trace and frame % F.TRACE_EVERY == 0 then
            diag.log(F.state_line("trace", frame, phase, point, locate()))
        end
        return buttons, phase, point
    end, function(_, phase, frame)
        diag.log(fmt("  phase %s @%d xy=%s,%s", phase, frame, tostring(last and last.x), tostring(last and last.y)))
    end)
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
function F.driver(map, opts)
    opts = opts or {}
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
                    -- opts.weaken (the U1f second catch, Crystal U1f run 1 ran out of its ten O-10 Balls): one
                    -- damaging hit on a foe still at full HP first; a Poke Ball's odds rise as the foe's HP falls
                    -- (PokeBallEffect, engine/items/item_effects.asm: (3*maxHP - 2*HP) * rate / (3*maxHP))
                    if opts.weaken and point.foe_full == true then return choose(ui, "FIGHT", 2) end
                    return choose(ui, "PACK", 2)
                end
                if ui.kind == "move_menu" and opts.weaken then
                    if point.foe_full ~= true or type(ui.items) ~= "table" then return press("B") end
                    for _, label in ipairs(ui.items) do
                        local passive = false
                        for _, name in ipairs(opts.passive or {}) do if label:upper() == name then passive = true end end
                        if not passive then return choose(ui, label:upper(), 1) end
                    end
                    return press("B")
                end
                if F.TOWARD_BALLS[ui.kind] then return press(F.TOWARD_BALLS[ui.kind]) end
                if ui.kind == "pack_balls" then
                    if point.ball_cursor == "ball" then
                        if point.ball_toward then return press(point.ball_toward) end   -- a Master Ball first
                        ups = 0; return press("A")
                    end
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
function F.verdict(record, expect, pc)
    expect = expect or F.EXPECT
    local evolution = false
    for _, name in ipairs(expect) do if name == F.EVOLUTION_SITE then evolution = true end end
    local problems = {}
    local function need(ok, what) if not ok then problems[#problems + 1] = what end end
    need(record.registry_failed == nil, "hook registry latched a failure: " .. tostring(record.registry_failed))
    need(record.accept_errors == 0, "binder accept faults")
    need(record.aligned >= 1 and record.misaligned == 0,
         fmt("callback frame != armed frame on %d of %d hits", record.misaligned, record.aligned + record.misaligned))
    local a = record.align
    need(a ~= nil and a.callback == a.armed and integer(a.battle_party, 0, 5) and a.callback_party == a.battle_party + 1
         and a.post_party == a.callback_party and integer(a.party_changed, 0, 2^53) and a.party_changed <= a.callback,
         "capture_party RAM effect is not aligned to the callback frame")
    local sites, previous = record.sites, 0
    for _, name in ipairs(expect) do
        if name ~= "whiteout_before_heal" then
            local site, found = sites[name], nil
            for _, hit in ipairs(site and site.log or {}) do
                if hit.seq > previous then found = hit break end
            end
            need(found ~= nil, name .. " did not fire after the previous expected site")
            if found then previous = found.seq end
            need(site ~= nil and site.pc == site.addr and site.hit_bank == site.bank and site.off_pin == 0,
                 name .. " hit off its pinned bank/PC (measured)")
        end
    end
    if pc then
        -- the U1f second catch: exactly two captures, the second after the chain's closing whiteout
        local cp, w = sites.capture_party, record.whiteout
        need(cp and cp.hits == (evolution and 3 or 2) and cp.log[2] and w and cp.log[2].seq > (w.seq or math.huge),
             "capture_party must fire once before the closing whiteout and once after it"
             .. (evolution and " (and once for the evolution leg)" or ""))
        local faint_log = sites.battle_faint and sites.battle_faint.log or {}
        local why = F.whiteout_problem(w, F.closing_faint_seq(faint_log, w and w.seq))
        need(why == nil, tostring(why))
        local deposit = sites.pc_deposit_begin and sites.pc_deposit_begin.log[1]
        need(deposit and w and deposit.seq > (w.seq or math.huge), "the PC operations did not follow the whiteout")
        why = F.u1f_emission_problem(record.u1f_model)
        need(why == nil, tostring(why))
    else
        need(sites.capture_party and sites.capture_party.hits == 1, "capture_party must fire exactly once")
    end
    local faint = F.faint_problem(record.faint)
    need(faint == nil, tostring(faint))
    for _, name in ipairs(expect) do
        if name == "poison_faint" then
            local why = F.poison_problem(record.poison, record.psn_mask)
            need(why == nil, tostring(why))
            why = F.poison_emission_problem(record.poison_model, record.poison)
            need(why == nil, tostring(why))
        end
    end
    if evolution then
        local why = F.evolution_problem(record.evolution, record.old_species_by_new)
        need(why == nil, tostring(why))
        why = F.evolution_emission_problem(record.evolution_model, record.evolution, record.old_species_by_new)
        need(why == nil, tostring(why))
        local cp, hit = sites.capture_party, sites[F.EVOLUTION_SITE] and sites[F.EVOLUTION_SITE].log[1]
        need(cp and cp.log[3] and hit and hit.seq > cp.log[3].seq, "the evolution did not follow the evolution leg's catch")
    end
    for _, name in ipairs(F.ABSENT) do need(sites[name] and sites[name].hits == 0, name .. " fired on a party < 6 catch") end
    need(record.decoy.raw >= 1 and record.decoy.accepted == 0 and record.decoy.bank_rejects == record.decoy.raw,
         "wrong-bank decoy: no raw fire, an accepted hit, or a hit not rejected by bank")
    for _, name in ipairs({"wrong_pack_byte", "script_bytecode_arm", "wrong_bank_hit"}) do
        need(record.negatives[name] == "refused", "negative control not refused: " .. name)
    end
    return problems, #problems == 0 and {table.unpack(expect)} or {}
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

-- The pack this gate arms and binds. A clean run uses engine_signals.json as read. An overlay run swaps in the
-- sites of its execution binding (D2): same schema, overlay-resolved offsets and bytes; every other pack field
-- (source lineage, specs hash, point symbols' RAM) is the shared clean lineage. No fallback to the clean sites.
function F.exec_pack(ctx, pack)
    local view = ctx.artifact   -- nil = a caller with no artifact context: the clean pack, as before
    if not view or view.kind ~= "overlay" then return pack end
    local executed = copy(pack)
    executed.titles[ctx.env.title].sites = copy(assert(view.sites, "overlay execution view carries no sites"))
    return executed
end

local function binding(ctx)
    local api = ctx.api
    return ctx.Binding.new({read_u8=api.read_u8, read_range=api.read_range, register=api.register,
        framecount=api.framecount, on_bus_exec=api.on_bus_exec, unregister=api.unregister},
        {bus_domain="System Bus", rom_domain="ROM", bank_domain="System Bus", pc_register="PC", sp_register="SP",
         bank_address=ctx.profile.hram.hROMBank})
end

-- battle_faint (UpdateFaintedPlayerMon entry, C core.asm:2656-2670, G/S :2551-2565): wCurBattleMon names the
-- party slot the production faint_event reads (lua/gen2/signals.lua faint_event). The battle copy already reads
-- HP 0; the party record still holds the last end-of-turn copy (UpdateBattleMonInParty in .NoMoreFaintingConditions,
-- C core.asm:286-294, G/S :241-249) and reads HP 0 only once this routine's own UpdateBattleMonInParty ran, with
-- no DelayFrame in between: same frame, or the next when the frame boundary splits the routine. That party
-- HP 0 is what the client's faint latch settles on (lua/gen2/client.lua settle_faints).
local function word(bytes) return bytes[1] * 256 + bytes[2] end
local function party_offset(ctx, slot) return slot * (ctx.profile.ram.wPartyMon2 - ctx.profile.ram.wPartyMon1) end
function F.party_hp(ctx, slot) return word(ctx.sym("wPartyMon1HP", party_offset(ctx, slot), 2)) end
function F.faint_snapshot(ctx, armed, callback)
    local slot = ctx.sym("wCurBattleMon")[1]
    local off = party_offset(ctx, math.min(slot, 5))
    return {armed=armed, callback=callback, slot=slot, party_count=ctx.sym("wPartyCount")[1],
            battle_hp=word(ctx.sym("wBattleMonHP", 0, 2)), battle_species=ctx.sym("wBattleMonSpecies")[1],
            battle_dvs=word(ctx.sym("wBattleMonDVs", 0, 2)), party_species=ctx.sym("wPartyMon1Species", off)[1],
            party_dvs=word(ctx.sym("wPartyMon1DVs", off, 2)), callback_party_hp=word(ctx.sym("wPartyMon1HP", off, 2))}
end

-- Pure: the faint record's frame-alignment rule (nil = aligned, else why).
function F.faint_problem(f)
    if type(f) ~= "table" then return "battle_faint recorded no same-frame snapshot" end
    if not integer(f.armed, 0, 2^53) or f.callback ~= f.armed then return "battle_faint callback frame != armed frame" end
    if not integer(f.party_count, 1, 6) or not integer(f.slot, 0, f.party_count - 1) then return "wCurBattleMon is not a party slot" end
    if f.battle_hp ~= 0 then return "the battle mon is not at 0 HP inside the battle_faint callback" end
    if not integer(f.battle_species, 1, 251) or f.party_species ~= f.battle_species or f.party_dvs ~= f.battle_dvs then
        return "the wCurBattleMon party record is not the fainting battle mon"
    end
    if not integer(f.callback_party_hp, 1, 999) then return "the party record was already copied back at the callback" end
    if not integer(f.hp_zero_frame, 0, 2^53) or f.hp_zero_frame < f.callback or f.hp_zero_frame > f.callback + 1 then
        return "the party record did not read HP 0 on the callback frame or the next"
    end
    return nil
end

-- poison_faint (DoPoisonStep.DamageMonIfPoisoned +27, C engine/events/poisonstep.asm:88-90, G the same lines):
-- `ld a, MON_STATUS / call GetPartyParamLocation / ld [hl], 0` right after the 1-HP tick stored HP 0. Inside the
-- callback the wCurPartyMon record (the index signals.lua faint_event reads) reads HP 0 with PSN still set; the
-- main loop saw HP 1 before the armed frame (0 only if the frame boundary split the dec from the site), and the
-- status reads 0 on the callback frame or the next. Overworld only: wBattleMode 0.
function F.poison_snapshot(ctx, armed, callback, pre_hp)
    local slot = ctx.sym("wCurPartyMon")[1]
    local off = party_offset(ctx, math.min(slot, 5))
    return {armed=armed, callback=callback, slot=slot, party_count=ctx.sym("wPartyCount")[1],
            battle_mode=ctx.sym("wBattleMode")[1], species=ctx.sym("wPartyMon1Species", off)[1],
            dvs=word(ctx.sym("wPartyMon1DVs", off, 2)), callback_hp=word(ctx.sym("wPartyMon1HP", off, 2)),
            callback_status=ctx.sym("wPartyMon1Status", off)[1], pre_hp=pre_hp and pre_hp[slot] or nil}
end
function F.party_status(ctx, slot) return ctx.sym("wPartyMon1Status", party_offset(ctx, slot))[1] end

-- Pure: the poison record's rule (nil = aligned, else why). psn_mask = 1 << PSN (constants/battle_constants.asm).
function F.poison_problem(p, psn_mask)
    if type(p) ~= "table" then return "poison_faint recorded no same-frame snapshot" end
    if not integer(p.armed, 0, 2^53) or p.callback ~= p.armed then return "poison_faint callback frame != armed frame" end
    if not integer(p.party_count, 1, 6) or not integer(p.slot, 0, p.party_count - 1) then return "wCurPartyMon is not a party slot" end
    if p.battle_mode ~= 0 then return "poison_faint fired inside a battle" end
    if not integer(p.species, 1, 251) then return "the wCurPartyMon record is not a mon" end
    if p.callback_hp ~= 0 then return "the poisoned record is not at 0 HP inside the callback" end
    if not integer(psn_mask, 1, 128) or not integer(p.callback_status, 0, 255) or (p.callback_status // psn_mask) % 2 ~= 1 then
        return "the record's PSN bit was already cleared at the callback"
    end
    if p.pre_hp ~= 1 and p.pre_hp ~= 0 then return "the record did not read 1 HP (or 0) before the armed frame" end
    if not integer(p.status_zero_frame, 0, 2^53) or p.status_zero_frame < p.callback or p.status_zero_frame > p.callback + 1 then
        return "the record's status did not read 0 on the callback frame or the next"
    end
    return nil
end

-- whiteout_before_heal (the `Special` CPU dispatch entry, C/G engine/events/specials.asm:1-13, with the pack's guards:
-- DE = 27 = HealPartySpecial's index, wScriptBank/wScriptPos = Script_Whiteout's `special HealParty`, the two
-- FarCall/Script_special return words on the stack). The probe records the first hit whose guards hold: every party
-- record reads HP 0 inside it (before the heal), and the heal lands on a later frame.
function F.guard_holds(ctx, g)
    local api = ctx.api
    if type(g) ~= "table" then return false end
    local function reg(name)
        if #name == 2 then return api.register(name:sub(1, 1)) * 256 + api.register(name:sub(2, 2)) end
        return api.register(name)
    end
    local function word(addr, width)
        local v = 0
        for i = width - 1, 0, -1 do v = v * 256 + api.read_u8(addr + i, "System Bus") end
        return v
    end
    for name, value in pairs(g.registers or {}) do if reg(name) ~= value then return false end end
    for _, m in ipairs(g.memory_equals or {}) do if word(m.addr, m.width) ~= m.value then return false end end
    local sp = api.register("SP")
    for _, w in ipairs(g.stack_words_equals or {}) do if word(sp + w.sp_offset, w.width) ~= w.value then return false end end
    return true
end
function F.whiteout_snapshot(ctx, armed, callback, seq)
    local hp = {}
    for slot = 0, math.min(ctx.sym("wPartyCount")[1], 6) - 1 do hp[#hp + 1] = F.party_hp(ctx, slot) end
    return {armed=armed, callback=callback, seq=seq, de=ctx.api.register("D") * 256 + ctx.api.register("E"),
            party_count=ctx.sym("wPartyCount")[1], party_hp=hp}
end

-- Pure: the closing battle faint is the LAST battle_faint hit BEFORE the whiteout, not the run's last one: a
-- later leg (the evolution grind) may faint again after the whiteout (overlay sweep ca9b564f: faints 157/207/241
-- around whiteout 158 read as "the whiteout did not follow the closing battle faint"). nil when none precedes it.
function F.closing_faint_seq(faint_log, whiteout_seq)
    local found
    for _, hit in ipairs(faint_log or {}) do
        if integer(hit.seq, 1, 2^53) and integer(whiteout_seq, 1, 2^53) and hit.seq < whiteout_seq then found = hit.seq end
    end
    return found
end

-- Pure: the whiteout record's rule (nil = holds, else why). faint_seq: the battle_faint hit it must follow.
function F.whiteout_problem(w, faint_seq)
    if type(w) ~= "table" then return "whiteout_before_heal recorded no guard-matching hit" end
    if not integer(w.armed, 0, 2^53) or w.callback ~= w.armed then return "whiteout_before_heal callback frame != armed frame" end
    if w.de ~= 27 then return "the whiteout hit is not HealPartySpecial (DE != 27)" end
    if not integer(w.party_count, 1, 6) or type(w.party_hp) ~= "table" or #w.party_hp ~= w.party_count then
        return "the whiteout record has no party snapshot"
    end
    for _, hp in ipairs(w.party_hp) do if hp ~= 0 then return "a party mon had HP inside the pre-heal whiteout" end end
    -- HealParty runs in the same frame right after the dispatch (live U1f Crystal run 1: healed_frame == callback)
    if not integer(w.healed_frame, 0, 2^53) or w.healed_frame < w.callback then return "the whiteout heal was not observed after the hit" end
    if not integer(faint_seq, 1, 2^53) or not integer(w.seq, 1, 2^53) or w.seq <= faint_seq then
        return "the whiteout did not follow the closing battle faint"
    end
    return nil
end

-- Pure: the U1f MODEL decoder's events: exactly one whiteout, two party-to-box deposits, one box-to-party
-- withdraw, one box change to BOX1 + 1, one box release and one party release. m.events = {{kind, site_id, ...}}.
F.U1F_EVENTS = {whiteout=1, party_to_box=2, box_to_party=1, box_change=1, pc_release_box=1, pc_release_party=1}
function F.u1f_emission_problem(m)
    if type(m) ~= "table" or type(m.events) ~= "table" then return "the U1f model binder recorded nothing" end
    local counts = {}
    for _, e in ipairs(m.events) do
        local k = e.kind == "pc_release" and ("pc_release_" .. tostring(e.collection)) or tostring(e.kind)
        counts[k] = (counts[k] or 0) + 1
    end
    for k, n in pairs(F.U1F_EVENTS) do
        if counts[k] ~= n then return fmt("the U1f model emitted %s %s events, not %d", tostring(counts[k] or 0), k, n) end
    end
    for k in pairs(counts) do if not F.U1F_EVENTS[k] then return "the U1f model emitted an unexpected " .. k .. " event" end end
    return nil
end

-- Pure: the MODEL binder, armed on this very hook during the leg, emitted ONE faint event (cause poison) naming
-- the snapshot's slot and mon. m = {events = {{kind, cause, slot, species, dvs}}, refusals = {...}}.
function F.poison_emission_problem(m, p)
    if type(m) ~= "table" or type(m.events) ~= "table" then return "the model binder recorded nothing" end
    if #m.events ~= 1 then return fmt("the model binder emitted %d poison faint events, not 1", #m.events) end
    local e = m.events[1]
    if e.kind ~= "faint" or e.cause ~= "poison" or e.site_id ~= "poison_faint" then return "the model event is not a poison faint" end
    if type(p) ~= "table" or e.slot ~= p.slot or e.species ~= p.species or e.dvs ~= p.dvs then
        return "the model event names another record than the callback snapshot"
    end
    return nil
end

-- evolution_species_published (EvolveAfterBattle_MasterLoop.skip_unown +6, C engine/pokemon/evolve.asm:312-317, G/S
-- :313-318): the `push hl` right after `ld [hl], a` stored the new species (A) at wPartySpecies + wCurPartyMon, after
-- the struct copy (:291-293) and LearnLevelMoves (:299). Inside the callback A, the species-list byte and the party
-- struct's species are the new species and HL is that list byte; the main loop read the list byte as the generated
-- unique pre-evolution (the pack's identity_migration.old_species_by_new) at the end of the frame before the armed
-- one. wLinkMode 0: not a trade evolution. Still inside ExitBattle (wBattleMode not yet cleared, core.asm:8266-8298).
function F.evolution_snapshot(ctx, armed, callback, pre)
    local api = ctx.api
    local slot = ctx.sym("wCurPartyMon")[1]
    local at = math.min(slot, 5)
    local off = party_offset(ctx, at)
    return {armed=armed, callback=callback, slot=slot, party_count=ctx.sym("wPartyCount")[1],
            a=api.register("A"), hl=api.register("H") * 256 + api.register("L"),
            list_addr=ctx.profile.ram.wPartySpecies + at, list_species=ctx.sym("wPartySpecies", at)[1],
            struct_species=ctx.sym("wPartyMon1Species", off)[1], dvs=word(ctx.sym("wPartyMon1DVs", off, 2)),
            ot=word(ctx.sym("wPartyMon1ID", off, 2)), link_mode=ctx.sym("wLinkMode")[1],
            battle_mode=ctx.sym("wBattleMode")[1], pre_list_species=pre and pre[slot] or nil}
end

-- Pure: the evolution record's rule (nil = holds, else why). old_by_new: the pack's old_species_by_new table.
function F.evolution_problem(e, old_by_new)
    if type(e) ~= "table" then return "evolution_species_published recorded no same-frame snapshot" end
    if not integer(e.armed, 0, 2^53) or e.callback ~= e.armed then return "evolution callback frame != armed frame" end
    if not integer(e.party_count, 1, 6) or not integer(e.slot, 0, e.party_count - 1) then return "wCurPartyMon is not a party slot" end
    if e.link_mode ~= 0 then return "the evolution ran in a link (trade) context" end
    if not integer(e.a, 1, 251) or e.list_species ~= e.a or e.struct_species ~= e.a then
        return "A, the species-list byte and the party struct do not all carry the published species"
    end
    if e.hl ~= e.list_addr then return "HL is not wPartySpecies + wCurPartyMon" end
    local old = type(old_by_new) == "table" and old_by_new[tostring(e.a)]
    if not integer(old, 1, 251) then return "the published species has no generated pre-evolution" end
    if e.pre_list_species ~= old then return "the species list did not read the pre-evolution before the armed frame" end
    return nil
end

-- Pure: the MODEL binder, armed on this very hook during the leg, emitted ONE key_change (reason evolution) whose
-- keys are the snapshot mon's DVs/OT with the pre-evolution and the published species (signals.lua key()).
function F.evolution_emission_problem(m, e, old_by_new)
    if type(m) ~= "table" or type(m.events) ~= "table" then return "the evolution model binder recorded nothing" end
    if #m.events ~= 1 then return fmt("the model binder emitted %d evolution events, not 1", #m.events) end
    local k = m.events[1]
    if k.kind ~= "key_change" or k.reason ~= "evolution" or k.site_id ~= F.EVOLUTION_SITE then
        return "the model event is not an evolution key_change"
    end
    local old = type(e) == "table" and type(old_by_new) == "table" and old_by_new[tostring(e.a)]
    if not integer(old, 1, 251) or k.slot ~= e.slot
       or k.old_key ~= fmt("%04X:%04X:%02X", e.dvs, e.ot, old) or k.new_key ~= fmt("%04X:%04X:%02X", e.dvs, e.ot, e.a) then
        return "the model key_change names another mon than the callback snapshot"
    end
    return nil
end

-- Arm every pack site (grouped by bank:PC like lua/gen2/signals.lua) plus the wrong-bank decoy.
function F.probe(ctx, pack, decoy_site, expect)
    local Registry = dofile(ctx.root .. "/lua/hook_registry.lua")
    local B = binding(ctx)
    local sites = pack.titles[ctx.env.title].sites
    local record = {sites={}, aligned=0, misaligned=0, accept_errors=0, seq=0,
                    decoy={raw=0, accepted=0, bank_rejects=0}, negatives={}}
    local groups, descriptors = {}, {}
    local logged = {}
    for _, name in ipairs(expect or F.EXPECT) do logged[name] = true end
    for _, name in ipairs(F.ABSENT) do logged[name] = true end
    logged.poison_faint = true
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
                if probe.on_hit then probe.on_hit(name, hit.frame, probe.armed) end   -- card U1G: live effect reads
                if name == "wild_ready" and record.battle_party == nil then
                    record.battle_party = ctx.sym("wPartyCount")[1]   -- the party before any capture
                end
                if name == "battle_faint" and record.faint == nil then record.faint = F.faint_snapshot(ctx, probe.armed, hit.frame) end
                if name == "whiteout_before_heal" and probe.watch_whiteout and record.whiteout == nil
                   and F.guard_holds(ctx, sites[name].guards) then
                    record.whiteout = F.whiteout_snapshot(ctx, probe.armed, hit.frame, record.seq)
                end
                if name == F.EVOLUTION_SITE and probe.watch_evolution and record.evolution == nil then
                    record.evolution = F.evolution_snapshot(ctx, probe.armed, hit.frame, probe.species_list)
                end
                if name == "poison_faint" and record.poison == nil then
                    record.poison = F.poison_snapshot(ctx, probe.armed, hit.frame, probe.party_hp)
                end
                if name == "capture_party" and record.align == nil then
                    record.align = {armed=probe.armed, callback=hit.frame, pre_party=probe.pre_party,
                                    battle_party=record.battle_party, callback_party=ctx.sym("wPartyCount")[1]}
                end
            end
            return nil
        end})
    assert(service, "engine-site probe refused to arm: " .. tostring(why))
    -- The main loop's frameadvance, wrapped: the armed frame, wPartyCount either side of it, and the
    -- first frame after wild_ready whose end shows a different wPartyCount (the capture's RAM effect).
    local api = ctx.api
    local advance = api.advance
    function api.advance()
        local frame = api.framecount()
        probe.armed, probe.pre_party = frame, ctx.sym("wPartyCount")[1]
        advance()
        probe.armed = nil
        local party = ctx.sym("wPartyCount")[1]
        if record.battle_party ~= nil and record.party_changed == nil and party ~= record.battle_party then
            record.party_changed = frame
        end
        if record.align and record.align.post_party == nil then
            record.align.post_party, record.align.party_changed = party, record.party_changed
        end
        local faint = record.faint
        if faint and faint.hp_zero_frame == nil and integer(faint.slot, 0, 5) then
            local hp = F.party_hp(ctx, faint.slot)
            faint.post_party_hp = faint.post_party_hp or hp
            if hp == 0 then faint.hp_zero_frame = frame end
        end
        -- poison: every party HP at the end of each frame (the pre-armed read) until the hit, then the status clear.
        local w = record.whiteout
        if w and w.healed_frame == nil then
            local healed = true
            for slot = 0, math.min(ctx.sym("wPartyCount")[1], 6) - 1 do
                if F.party_hp(ctx, slot) == 0 then healed = false end
            end
            if healed then w.healed_frame = frame end
        end
        if probe.watch_evolution and record.evolution == nil then   -- the species list at the end of every frame
            probe.species_list = {}
            for slot = 0, math.min(party, 6) - 1 do probe.species_list[slot] = ctx.sym("wPartySpecies", slot)[1] end
        end
        if probe.watch_poison then
            local poison = record.poison
            if poison == nil then
                probe.party_hp = {}
                for slot = 0, math.min(party, 6) - 1 do probe.party_hp[slot] = F.party_hp(ctx, slot) end
            elseif poison.status_zero_frame == nil and integer(poison.slot, 0, 5) then
                poison.post_status = poison.post_status or F.party_status(ctx, poison.slot)
                if F.party_status(ctx, poison.slot) == 0 then poison.status_zero_frame = frame end
            end
        end
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
    local options = {title=ctx.env.title, profile=wrapper, pack=pack, io=io_, authority=authority, reads=ctx.reads,
            Registry=dofile(ctx.root .. "/lua/hook_registry.lua"), GB=dofile(ctx.root .. "/lua/gb_hook_binding.lua"),
            owner=owner, max_pending=8}
    if ctx.artifact and ctx.artifact.kind == "overlay" then
        -- The binder validates against the view's sites; carry the sites of THIS pack (a negative's mutated copy
        -- included), so a one-byte-wrong overlay row is what refuses, not the clean pack.
        local view = {}
        for key, value in pairs(ctx.artifact) do view[key] = value end
        view.sites = pack.titles[ctx.env.title].sites
        options.view = view
    end
    return options
end

-- The production decoder (lua/gen2/signals.lua faint_event) on the live hook, as a MODEL instance holding only the
-- poison_faint row: model_only IO whose bank check is the live hROMBank byte. Not PHYSICAL authority.
function F.poison_model(ctx, Signals, wrapper, pack, names, reads, extra)
    local api, title = ctx.api, ctx.env.title
    local only = copy(pack)
    local keep = {}
    for _, name in ipairs(names or {"poison_faint"}) do keep[name] = only.titles[title].sites[name] end
    only.titles[title].sites = keep
    local options = binder_options(ctx, wrapper, only, "gen2-u1-model-" .. (names and "u1f" or "poison"))
    options.reads = reads or options.reads
    for key, value in pairs(extra or {}) do options[key] = value end   -- card U1G: areas/encounters/gifts packs
    -- The production mapping (lua/gen2/run.lua bank_valid): ROM0/WRAM0/HRAM bank 0, ROMX the hROMBank shadow,
    -- WRAMX the SVBK bank (0 selects 1). Live run 2: a ROM-only check refused the WRAM guard reads.
    local function wram_bank()
        local svbk = api.read_u8(0xFF70, "System Bus") % 8
        return svbk == 0 and 1 or svbk
    end
    local function bank_valid(bank, addr, n)
        local last = addr + n - 1
        if last < 0x4000 or (addr >= 0xC000 and last < 0xD000) or (addr >= 0xFF80 and last < 0xFFFF) then return bank == 0 end
        if addr >= 0x4000 and last < 0x8000 then return bank == api.read_u8(ctx.profile.hram.hROMBank, "System Bus") end
        if addr >= 0xD000 and last < 0xE000 then return bank == wram_bank() end
        return false
    end
    options.io.bank_valid = bank_valid
    options.io.stack_valid = function(sp, n) return bank_valid(sp < 0xD000 and 0 or wram_bank(), sp, n) end
    options.authority.valid = function() return true end
    local model, why = Signals.new_model(options)
    assert(model, "model binder refused: " .. tostring(why))
    local out = {events={}, bank_valid=bank_valid}
    function out.drain()
        for _, batch in ipairs(model:drain()) do
            for _, e in ipairs(batch.events) do
                out.events[#out.events + 1] = {kind=e.kind, cause=e.cause, site_id=e.site_id, slot=e.slot,
                    species=e.mon and e.mon.species_id, dvs=e.mon and e.mon.dv_word, collection=e.collection,
                    old_box=e.old_box, new_box=e.new_box, box_index=e.box_index, reason=e.reason, old_key=e.old_key,
                    new_key=e.new_key, acquisition=e.acquisition, destination=e.destination, area_id=e.area_id}
            end
        end
    end
    function out.close()
        out.drain()
        local status = model:status()
        out.refusals, out.failed = status.refusals, status.failed
        model:close()
    end
    return out
end

-- The load-time refusals, each beside its known-positive control on the same live ROM.
function F.negatives(ctx, Signals, wrapper, pack)
    local out, detail = {}, {}
    local control, why = Signals.new_model(binder_options(ctx, wrapper, pack, "gen2-u1-control"))
    detail.control = control and "bound" or tostring(why)
    if control then control:close() end

    local bad = copy(pack)
    local site = bad.titles[ctx.env.title].sites.capture_party
    site.expected_hex = fmt("%02x", (tonumber(site.expected_hex:sub(1, 2), 16) + 1) % 256) .. site.expected_hex:sub(3)
    local refused, reason = Signals.new_model(binder_options(ctx, wrapper, bad, "gen2-u1-bad-byte"))
    if refused then refused:close() end
    detail.wrong_pack_byte = tostring(reason)
    out.wrong_pack_byte = (control and not refused and tostring(reason):find("differ from the ROM", 1, true))
        and "refused" or "NOT refused"

    local script = copy(pack)
    local sites = script.titles[ctx.env.title].sites
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
    log(fmt("[gen2_frame_align] U1 %s engine-hook proof + frame-alignment probe",
            F.NAMES[getenv("SLINK_GEN2_TITLE")] or tostring(getenv("SLINK_GEN2_TITLE"))))

    local ok, ctx = pcall(function()
        SG = SG or F.scripted_gate(root)
        local c = SG.context(api, getenv)
        -- the per-title U1 fixtures (lua/gen2/signals.lua S.U1_FIXTURES; gold_battle_errand: card gen2-u1e-poison)
        assert(c.qualify ~= nil and c.qualify.stage == "boot", "SLINK_GEN2_QUALIFY stage \"boot\" required")
        c.u1 = assert(c.json.decode(assert(getenv("SLINK_GEN2_U1_FACTS"), "SLINK_GEN2_U1_FACTS missing")))
        -- card U1G: a synthetic fixture arrives through its base's case (the shared gate names cases by their base);
        -- case.synth names the bytes actually staged, one of this title's lua/gen2/signals.lua S.SYNTH_FIXTURES.
        local synth = c.case.synth
        assert(F.SYM[c.env.title] and (synth == nil and F.U1_FIXTURES[c.case.name] == c.env.title
            or c.u1.u1g ~= nil and type(synth) == "string" and synth:match("^" .. c.env.title .. "_synth_%l+$") ~= nil),
            "U1 runs on a listed U1 fixture only")
        return c
    end)
    if not check("environment, facts, profile and running ROM/CGB bound", ok, not ok and ctx or nil) then
        return finish("bad environment")
    end
    ctx.log = log
    local json = ctx.json
    local title = ctx.env.title
    local wrapper = read_json(ctx, "data/games/gen2_" .. title .. "/profile.json")
    local pack = F.exec_pack(ctx, read_json(ctx, "data/games/gen2_" .. title .. "/engine_signals.json"))
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
    local FI = dofile(ctx.root .. "/" .. F.FAINT_INPUTS)
    FI.prepare(ctx, SG, ctx.u1)   -- before SG.hooks: the move/party UI origins join the watched origins
    if ctx.u1.pc then dofile(ctx.root .. "/" .. F.PC_INPUTS).prepare(ctx, SG, ctx.u1) end
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
    -- card U1G: an O-33 synthetic fixture runs its own short leg (lua/tests/gen2_u1g_inputs.lua) and prints one v2 run.
    if ctx.u1.u1g then
        return dofile(ctx.root .. "/" .. F.U1G_INPUTS).run(F, ctx, SG, {api=api, host=host, state=state,
            wrapper=wrapper, pack=pack, Signals=Signals, negatives=negatives, log=log, check=check, finish=finish,
            FI=FI, read_json=function(rel) return read_json(ctx, rel) end, evidence=evidence})
    end

    local poison = ctx.u1.poison ~= nil
    local pcmode = ctx.u1.pc ~= nil
    local evolution = ctx.u1.evolution ~= nil
    local expect = F.expect(poison, pcmode, evolution)
    local probe = F.probe(ctx, pack, ctx.u1.decoy, expect)
    probe.watch_poison, probe.watch_whiteout = poison, pcmode
    local base = SG.qualify_observer(ctx)
    local function observe()
        local point = base()
        point.probe_hits = {capture_party=probe.record.sites.capture_party.hits}
        if point.ui and point.ui.kind == "pack_balls" then point.ball_cursor, point.ball_toward = F.ball_cursor(SG.screen(ctx)) end
        if point.ui and point.ui.kind == "battle_menu" then
            local menu = SG.parse_menu(SG.screen(ctx), ctx.obs.screen.width, ctx.obs.screen.height,
                                       SG.BATTLE_MENU_GRID)
            if menu then point.ui.items, point.ui.cursor, point.ui.columns = menu.items, menu.cursor, menu.columns
            else point.input_ready = false end
        end
        return point
    end
    local symbol_at
    local function where()   -- PC and the ROM words on the stack, as bank-guessed labels (diagnostics only)
        if symbol_at == nil then
            local f = assert(io.open(F.sym_file(ctx), "rb"))
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
    local diag = {log=log, frame=api.framecount, screen=function() return SG.screen(ctx) end, where=where,
                  trace=getenv("SLINK_GEN2_TRACE") == "1"}
    local played, outcome = F.play(host, {name="u1-" .. title, terminal=driver.terminal,
        max_frames=F.BUDGET.max_frames, max_phase_frames=F.BUDGET.max_phase_frames,
        settle_frames=F.BUDGET.settle_frames, terminal_idle=true}, driver, observe, diag)
    -- The faint leg (the shared H1c inputs): back into the grass, the lead (party [starter, catch]) takes
    -- the wild mon's hits behind a status move until it faints; NO to "Use next", out to the overworld.
    -- card gen2-u1e-poison: the lead meets a POISON_STING foe on the hunt map, is poisoned, and faints to
    -- DoPoisonStep on the park tiles; the production decoder (MODEL instance) rides the same hook.
    local model, fopts = nil, {fainted=function() return probe.record.sites.battle_faint.hits >= 1 end}
    -- card gen2-u1f-pc: the production decoder (MODEL) on the whiteout and PC hooks from here on, reading
    -- through a live Reads (lua/gen2/reads.lua over CartRAM too: the active box lives in SRAM bank 1).
    local u1f_model
    if played and pcmode then
        local names = {"whiteout_before_heal"}
        for _, name in ipairs(F.U1F_SITES) do names[#names + 1] = name end
        local probe_model = F.poison_model(ctx, Signals, wrapper, pack, {"poison_faint"})
        local live = {cart_ram_linear=true, read_u8=api.read_u8, domain_size=api.domain_size,
                      read_range=function(addr, n, domain) return api.read_range(addr, n, domain) end,
                      bank_valid=probe_model.bank_valid}
        probe_model.close()
        local reads = assert(dofile(ctx.root .. "/lua/gen2/reads.lua").new(ctx.profile, live))
        u1f_model = F.poison_model(ctx, Signals, wrapper, pack, names, reads)
    end
    if played and poison then
        local PI = dofile(ctx.root .. "/" .. F.POISON_INPUTS)
        model = F.poison_model(ctx, Signals, wrapper, pack)
        local pdriver, pobserve, pspec = PI.new(ctx, SG, F, FI, {
            fainted=function() return probe.record.sites.poison_faint.hits >= 1 end,
            max_frames=F.POISON_BUDGET.max_frames, max_phase_frames=F.POISON_BUDGET.max_phase_frames})
        played, outcome = F.play(host, pspec, pdriver, pobserve, diag)
        probe.record.poison_hunt = pdriver.hunt_summary()
        -- Emit even when the hunt timed out; later sites/receipt may never exist.
        log("POISON_HUNT " .. json.encode(probe.record.poison_hunt))
        model.close()
        probe.record.poison_model, probe.record.psn_mask = model, ctx.u1.poison.psn_mask
        fopts.map, fopts.max_battles = ctx.u1.poison.maps[ctx.u1.poison.hunt_map], F.POISON_FAINT_BATTLES
        -- The faint target is the living mon, named up front: at battle start wCurBattleMon still reads the
        -- poison-fainted lead's slot, and FI would try to switch that 0-HP mon back in (Crystal live run 5).
        local party = ctx.reads.read_party()
        for _, m in ipairs(party and party.mons or {}) do
            if m.hp > 0 and fopts.target == nil then fopts.target = m.slot end
        end
    end
    if played then
        local fdriver, fobserve, fspec = FI.new(ctx, SG, F, fopts)
        -- F.play settles the stale save UI first (live U1d run 1).
        played, outcome = F.play(host, fspec, fdriver, fobserve, diag)
    end
    -- card gen2-u1f-pc: to Route 29 grass, the second catch (F.driver, capture counted from here), Bill's PC.
    if played and pcmode then
        local PC = dofile(ctx.root .. "/" .. F.PC_INPUTS)
        local PI = dofile(ctx.root .. "/" .. F.POISON_INPUTS)
        local gdriver, gobserve, gspec = PC.new(ctx, SG, F, PI, {mode="grass",
            max_frames=F.U1F_BUDGET.max_frames, max_phase_frames=F.U1F_BUDGET.max_phase_frames})
        played, outcome = F.play(host, gspec, gdriver, gobserve, diag)
        if played then
            local caught = probe.record.sites.capture_party.hits
            local cdriver = F.driver(ctx.facts.maps.Route29, {weaken=true, passive=FI.PASSIVE_MOVES})
            local function cobserve()
                local point = observe()
                point.probe_hits.capture_party = probe.record.sites.capture_party.hits - caught
                local battle = ctx.reads.read_battle()
                local foe = battle and battle.mode ~= 0 and ctx.reads.read_battle_mon("enemy") or nil
                point.foe_full = foe ~= nil and foe.hp == foe.max_hp
                if point.ui and point.ui.kind == "move_menu" then
                    local list = FI.move_list(SG.screen(ctx))
                    if list then point.ui.items, point.ui.cursor, point.ui.columns = list.items, list.cursor, list.columns
                    else point.input_ready = false end
                end
                return point
            end
            played, outcome = F.play(host, {name="u1f-catch-" .. title, terminal=cdriver.terminal,
                max_frames=F.BUDGET.max_frames, max_phase_frames=F.BUDGET.max_phase_frames,
                settle_frames=F.BUDGET.settle_frames, terminal_idle=true}, cdriver, cobserve, diag)
        end
        if played then
            local pdriver, pobserve, pspec = PC.new(ctx, SG, F, PI, {mode="pc",
                max_frames=F.U1F_BUDGET.max_frames, max_phase_frames=F.U1F_BUDGET.max_phase_frames})
            played, outcome = F.play(host, pspec, pdriver, pobserve, diag)
        end
    end
    if u1f_model then
        u1f_model.close()
        probe.record.u1f_model = u1f_model
    end
    -- card EVO-U1: from the Cherrygrove #MON CENTER (the PC leg's end), a Route 30 Caterpie/Weedle is caught and
    -- switch-trained to L7; it evolves after its last battle. The production decoder (MODEL) rides the evolution hook.
    local evo_model
    if played and evolution then
        local EV = dofile(ctx.root .. "/" .. F.EVOLUTION_INPUTS)
        local PI = dofile(ctx.root .. "/" .. F.POISON_INPUTS)
        evo_model = F.poison_model(ctx, Signals, wrapper, pack, {F.EVOLUTION_SITE})
        probe.watch_evolution = true
        local edriver, eobserve, espec = EV.new(ctx, SG, F, PI, FI, {observe=observe,
            max_frames=F.EVOLUTION_BUDGET.max_frames, max_phase_frames=F.EVOLUTION_BUDGET.max_phase_frames})
        played, outcome = F.play(host, espec, edriver, eobserve, diag)
        evo_model.close()
        probe.record.evolution_model = evo_model
        probe.record.old_species_by_new = pack.titles[title].sites[F.EVOLUTION_SITE].identity_migration.old_species_by_new
    end
    probe.release()
    state.release()
    local record = probe.record
    record.negatives = negatives
    record.negatives.wrong_bank_hit = (record.decoy.raw >= 1 and record.decoy.accepted == 0) and "refused" or "NOT refused"
    check("walk -> wild encounter -> Poke Ball catch -> native save -> " .. (poison and "poisoned lead faints on the overworld -> " or "")
          .. "walk -> a mon faints in battle", played,
          not played and outcome or nil)

    local summary = {}
    for name, s in pairs(record.sites) do
        if s.raw > 0 then
            summary[name] = {hits=s.hits, raw=s.raw, bank_rejects=s.bank_rejects, first_frame=s.first_frame,
                             pc=s.pc, bank=s.hit_bank, off_pin=s.off_pin, log=s.log}
        end
    end
    log("HIT_SUMMARY " .. json.encode(json.object(summary)))
    log("ALIGN " .. json.encode({align=record.align or json.null, aligned=record.aligned, misaligned=record.misaligned}))
    log("FAINT " .. json.encode(record.faint or json.null))
    if pcmode then
        log("WHITEOUT " .. json.encode(record.whiteout or json.null))
        log("U1F_MODEL " .. json.encode(u1f_model and {events=json.array(u1f_model.events),
            refusals=json.object(u1f_model.refusals or {}), failed=u1f_model.failed or json.null} or json.null))
    end
    if evolution then
        log("EVOLUTION " .. json.encode(record.evolution or json.null))
        log("EVOLUTION_MODEL " .. json.encode(evo_model and {events=json.array(evo_model.events),
            refusals=json.object(evo_model.refusals or {}), failed=evo_model.failed or json.null} or json.null))
    end
    if poison then
        log("POISON " .. json.encode(record.poison or json.null))
        log("POISON_MODEL " .. json.encode(model and {events=json.array(model.events), refusals=json.object(model.refusals or {}),
                                                       failed=model.failed or json.null} or json.null))
    end
    log("DECOY " .. json.encode({site=ctx.u1.decoy, raw=record.decoy.raw, accepted=record.decoy.accepted,
                                  bank_rejects=record.decoy.bank_rejects}))
    local problems, proven = F.verdict(record, expect, pcmode)
    log("VERDICT " .. json.encode(json.object({problems=json.array(problems), proven=json.array(proven)})))
    for _, problem in ipairs(problems) do check(problem, false) end
    if not played or #problems > 0 then return finish("no receipt") end

    local sites = {}
    for _, name in ipairs(expect) do
        local s = record.sites[name]
        sites[name] = {bank=s.bank, addr=s.addr, pc=s.pc, expected_hex=s.expected_hex, symbol=s.symbol,
                       hits=s.hits, raw=s.raw, bank_rejects=s.bank_rejects, first_frame=s.first_frame}
    end
    for _, name in ipairs(F.ABSENT) do
        local s = record.sites[name]
        sites[name] = {bank=s.bank, addr=s.addr, expected_hex=s.expected_hex, symbol=s.symbol, hits=0, raw=s.raw}
    end
    local a = record.align
    local receipt = {schema=Signals.RECEIPT_SCHEMA, title=title, evidence_level=evidence, result="PASS",
        rom_sha1=ctx.env.exec_sha1, artifact_kind=ctx.ident.artifact_kind, binding_sha256=ctx.ident.binding_sha256,
        base_sha1=ctx.ident.base_sha1, pack_commit=pack.source.commit, pack_specs_sha256=pack.specs_sha256,
        fixture=case.name, attempt_id=case.attempt_id, core_mode="CGB", input_mode="normal_buttons",
        fixture_sha256=q.stage_fingerprint, qualification_attempt_id=ctx.u1.qualification_attempt_id,
        harness_write_scopes=json.array({}), bank_check="live",
        frame_alignment={passed=true, rule="callback emu.framecount() == the frame being emulated (armed); "
            .. "wPartyCount is battle_party at wild_ready, battle_party+1 inside the capture_party callback and "
            .. "to the main loop at armed+1; it first changed at party_changed <= callback",
            armed=a.armed, callback=a.callback, pre_party=a.pre_party, battle_party=a.battle_party,
            callback_party=a.callback_party, post_party=a.post_party, party_changed=a.party_changed,
            effect_to_callback_frames=a.callback - a.party_changed,
            aligned_hits=record.aligned, misaligned_hits=record.misaligned},
        faint_alignment={passed=true, rule="battle_faint callback frame == armed; wCurBattleMon is a party slot; "
            .. "the battle mon reads HP 0 and the slot's party record is that mon (species, DVs) with HP > 0 inside "
            .. "the callback (before copy-back); the party record reads HP 0 on the callback frame or the next",
            armed=record.faint.armed, callback=record.faint.callback, slot=record.faint.slot,
            party_count=record.faint.party_count, battle_hp=record.faint.battle_hp,
            battle_species=record.faint.battle_species, battle_dvs=record.faint.battle_dvs,
            party_species=record.faint.party_species, party_dvs=record.faint.party_dvs,
            callback_party_hp=record.faint.callback_party_hp, post_party_hp=record.faint.post_party_hp,
            hp_zero_frame=record.faint.hp_zero_frame, copyback_frames=record.faint.hp_zero_frame - record.faint.callback},
        negatives=record.negatives, decoy={bank=ctx.u1.decoy.bank, addr=ctx.u1.decoy.addr, raw=record.decoy.raw,
            accepted=record.decoy.accepted, bank_rejects=record.decoy.bank_rejects},
        sites=sites, proven=json.array(proven), absent=json.array(F.ABSENT)}
    if pcmode then
        local w = record.whiteout
        receipt.whiteout_alignment = {passed=true, rule="the first `Special` hit whose pack guards hold (DE 27 = "
            .. "HealPartySpecial, wScriptBank/wScriptPos at Script_Whiteout's special, the FarCall/Script_special stack "
            .. "words): callback frame == armed, every party record at HP 0 inside it, the heal observed on a later "
            .. "frame, after the closing battle_faint; the MODEL decoder emitted exactly one whiteout",
            armed=w.armed, callback=w.callback, seq=w.seq, de=w.de, party_count=w.party_count,
            party_hp=json.array(w.party_hp), healed_frame=w.healed_frame}
        local counts = {}
        for _, e in ipairs(u1f_model.events) do
            local k = e.kind == "pc_release" and ("pc_release_" .. tostring(e.collection)) or tostring(e.kind)
            counts[k] = (counts[k] or 0) + 1
        end
        receipt.pc_alignment = {passed=true, rule="after the whiteout: a second catch, then Bill's PC deposit, "
            .. "withdraw, CHANGE BOX, deposit, box release, party release, each closed by its RAM effect; the MODEL "
            .. "decoder emitted exactly the listed operation events", model_events=counts,
            capture_party_hits=record.sites.capture_party.hits}
    end
    if evolution then
        local e = record.evolution
        receipt.evolution_alignment = {passed=true, rule="evolution_species_published callback frame == armed; "
            .. "wLinkMode 0; wCurPartyMon is a party slot; inside the callback A, the wPartySpecies byte and the party "
            .. "struct species are the published species and HL is that list byte; the list byte read the pack's "
            .. "pre-evolution at the end of the frame before; the production decoder (MODEL instance on the same hook) "
            .. "emitted one key_change (reason evolution) with that mon's old and new keys",
            armed=e.armed, callback=e.callback, slot=e.slot, party_count=e.party_count, a=e.a, hl=e.hl,
            list_addr=e.list_addr, list_species=e.list_species, struct_species=e.struct_species, dvs=e.dvs, ot=e.ot,
            link_mode=e.link_mode, battle_mode=e.battle_mode, pre_list_species=e.pre_list_species,
            old_species=record.old_species_by_new[tostring(e.a)], model_event=evo_model.events[1],
            capture_party_hits=record.sites.capture_party.hits}
    end
    if poison then
        local p = record.poison
        receipt.poison_alignment = {passed=true, rule="poison_faint callback frame == armed; overworld (wBattleMode 0); "
            .. "wCurPartyMon is a party slot whose record reads HP 0 with PSN still set inside the callback, read HP 1 "
            .. "(0 if the frame boundary split the tick) before the armed frame, and reads status 0 on the callback "
            .. "frame or the next; the production faint decoder (MODEL instance on the same hook) emitted one poison "
            .. "faint naming that slot, species and DVs",
            armed=p.armed, callback=p.callback, slot=p.slot, party_count=p.party_count, battle_mode=p.battle_mode,
            species=p.species, dvs=p.dvs, callback_hp=p.callback_hp, callback_status=p.callback_status,
            psn_mask=record.psn_mask, pre_hp=p.pre_hp, post_status=p.post_status, status_zero_frame=p.status_zero_frame,
            clear_frames=p.status_zero_frame - p.callback, model_event=model.events[1]}
    end

    -- The production gate on this very ROM: the receipt registers exactly the proven sites; the other
    -- title (F.REFUSE, with its own pack) refuses it.
    local options = binder_options(ctx, wrapper, pack, "gen2-u1-production", true)
    options.runtime_qualification = receipt
    local service, why = Signals.new(options)
    local registered = service and service:status().registered_sites or {}
    if service then service:close() end
    table.sort(proven)
    check("production Signals.new registers exactly the receipted sites",
          service ~= nil and table.concat(registered, ",") == table.concat(proven, ","),
          service and table.concat(registered, ",") or why)
    local other = F.REFUSE[title]
    options.title, options.owner = other, "gen2-u1-production-" .. other
    options.pack = read_json(ctx, "data/games/gen2_" .. other .. "/engine_signals.json")
    local refused, refused_why = Signals.new(options)
    if refused then refused:close() end
    check("production Signals.new refuses " .. F.NAMES[other], refused == nil, refused_why)
    log("PRODUCTION " .. json.encode({registered=json.array(registered), refused_title=other,
                                      refusal=tostring(refused_why)}))
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
