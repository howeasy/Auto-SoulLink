--[[
  lua/tests/test_gen2_scripted_gate.lua -- PHYSICAL route author: a cold Gen 2 cartridge played from
  NEW GAME to an in-game SAVE through ordinary buttons, producing a CANDIDATE fixture plus its
  played-route receipt. Reaching route-saved is never qualification: tools/gen2_fixtures.py
  (qualify_stage / validate_played_receipt / post_oracle_stage) decides that independently.

  Launched only by tools/gen2_fixtures.run_play through tools/run_gb_gate.py: cold boot, CGB, 300%,
  an isolated SaveRAM directory. Environment (all required, all validated, refusal on anything else):
    SLINK_ROOT                    repo root
    SLINK_GEN2_FIXTURE_CASE       JSON case (name, title, target, identity, title_idle_frames,
                                  attempt_id, max_frames, max_phase_frames, settle_frames)
    SLINK_GEN2_ROUTE_FACTS        JSON gen2-scripted-route-facts-v1 (tools/gen2_fixtures.route_facts)
    SLINK_GEN2_TITLE / _ROM_SHA1 / _CORE_MODE / _COLD / _SAVERAM_DIR / _SAVERAM_NAME
                                  runner-protected bindings (run_gb_gate._gen2_plan)
  Result file: patch/build/test_gen2_scripted_gate_result.txt (RESULT: PASS|FAIL, last line)
  Receipt:     $SLINK_GEN2_SAVERAM_DIR/<case>.played.json, schema gen2-played-route-v1, success only.

  Observer: every RAM address comes from data/games/gen2_<title>/profile.json (missing -> refusal);
  code sites, source constants and prompt anchors come from the route facts. UI context is the
  last-executed source UI origin (bank-checked through lua/gb_hook_binding.lua); overworld input
  readiness is OWPlayerInput executing; the native save witness is the engine save_completed site.
  O-10 (owner ruling): battle cases stage ONE Poke Ball stack into the empty Ball pocket through
  lua/write_permit.lua, bounded to the profile Ball-pocket span. Tests/validation only; never a
  natural ball-acquisition witness. Town cases record no write scope and refuse any request.

  QUALIFICATION mode (SLINK_GEN2_QUALIFY = {stage, stage_fingerprint, facts}, launched only by
  tools/gen2_fixtures.game_callbacks): a WARM boot of the candidate SaveRAM at 100%, driven by
  lua/tests/gen2_qualify.lua through CONTINUE (boot/reload) and a native START/SAVE (resave). No
  harness write of any kind. The CartRAM is hashed before the first emulated frame; the GAME witness
  ($SLINK_GEN2_SAVERAM_DIR/<case>.<stage>.witness.json, gen2-fixture-game-witness-v1) records the
  loaded map/position, the WRAM party bytes and the counted CONTINUE/RTC/overwrite code sites.
  A resave also flushes the SaveRAM. The witness is evidence for tools/gen2_fixtures, never a verdict.
--]]
local G = {}
local fmt = string.format

G.RESULT = "patch/build/test_gen2_scripted_gate_result.txt"
G.RECEIPT_SCHEMA = "gen2-played-route-v1"
G.BUTTONS = {"Up", "Down", "Left", "Right", "A", "B", "Start", "Select"}
G.CART_RAM_BYTES = 0x8000
-- docs/gen2/reviews/OMP_RTC_SOURCE_2026-09-22.md: BizHawk 2.11.1 gambatte appends 8+14 RTC bytes.
G.RTC_TRAILER_BYTES = 22
G.SPEED_PERCENT = 300
G.QUALIFY_SPEED_PERCENT = 100
G.WITNESS_SCHEMA = "gen2-fixture-game-witness-v1"
G.QUALIFY_STAGES = {boot=true, resave=true, reload=true}
G.O10_SCOPE = "O-10:BallPocket"
-- ponytail: live calibration knobs. A menu is pressed UI_SETTLE frames after its origin ran and a
-- confirm that the game did not take is re-pulsed every UI_REPULSE frames (Gen 1 gate cadence).
G.UI_SETTLE_FRAMES = 8
G.UI_REPULSE_FRAMES = 16
G.OVERWORLD_WINDOW = 2
G.MENU_KINDS = {main_menu=true, gender=true, name_choices=true, yes_no=true, start_menu=true, battle_menu=true}
-- Wait origins bound at a loop that runs once per waiting frame: a context whose loop stopped firing for
-- LOOP_WINDOW frames was answered, so it is shown but never ready (no stale re-pulse into the next UI).
-- InitClock .SetHourLoop/.SetMinutesLoop DelayFrame per idle pass too (engine/rtc/timeset.asm:66-69, SetHour/SetMinutes).
-- WaitPressAorB_BlinkCursor .loop (text) spins within a frame (home/joypad.asm:358-367): same rule.
G.LOOP_KINDS = {prompt_button=true, wait_button=true, day_picker=true, clock_hour=true, clock_minute=true, text=true,
    naming=true}   -- NamingScreenJoypadLoop: DelayFrame per pass (engine/menus/naming_screen.asm:302-311), errand only
G.LOOP_WINDOW = 2
-- A confirm here starts a map load, so a re-pulse would land in the loaded overworld before any newer
-- context exists (live attempt n2-crystal-town-a7: the re-pulsed A talked to Elm, ProfElmScript). The
-- title screen, by contrast, drops its first press and needs the re-pulse; MainMenu replaces it at once.
-- One-shot + the same-kind merge rule: a SECOND continue_confirm inside one stage would be stranded
-- (never ready again) and the stage would hang to its phase bound. Impossible today: one CONTINUE per boot.
G.ONE_SHOT_KINDS = {continue_confirm=true}
G.CONFIRM = {A=true, B=true, Start=true}
-- Charmap glyph names (data/games/gen2_<title>/charmap.lua), not byte values.
G.GLYPH = {cursor="▶", top_left="┌", bottom_left="└", side="│", space=" "}
-- The battle menu's source geometry, pinned from BattleMenuHeader (engine/battle/menu.asm:31-48):
-- menu_coords 8, 12 (left, top), dn 2, 2 (rows, columns), db 6 (spacing), labels FIGHT/<PKMN>/PACK/RUN
-- under STATICMENU_CURSOR | STATICMENU_DISABLE_B and no STATICMENU_NO_TOP_SPACING. So
-- GetMenuTextStartCoord puts the first label at (left+2, top+2) = (10, 14) 0-based (home/menu.asm:214-235),
-- Place2DMenuItemStrings steps columns by `spacing` and rows by 2 tiles (engine/menus/menu.asm:117-157),
-- and the cursor cell is one tile left of each label (engine/menus/menu.asm:159-165). <PKMN> prints as
-- <PK><MN> (home/text.asm:316,408), so each label is the glyph run the tilemap really holds.
G.BATTLE_MENU_GRID = {x=10, y=14, rows=2, columns=2, spacing=6,
    labels={{"F","I","G","H","T"}, {"<PK>","<MN>"}, {"P","A","C","K"}, {"R","U","N"}}}
G.REQUIRED_RAM = {"wMapGroup", "wPartyCount", "wBattleMode", "wSavedAtLeastOnce", "wNumBalls", "wBalls",
    "wTilemap", "wObjectStructs", "wTileUp", "wTileDown", "wTileLeft", "wTileRight",
    "wPokegearFlags", "wEventFlags", "wSaveFileExists"}
G.REQUIRED_HRAM = {"hROMBank", "hCGB"}

local BUTTON = {}
for _, name in ipairs(G.BUTTONS) do BUTTON[name] = true end

local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

-- FIPS 180-4 SHA-256 over a flat byte reader (Lua 5.4 integers).
local K = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2}
function G.sha256(byte_at, n)
    assert(integer(n, 0, 2^40), "SHA-256 byte length required")
    local M = 0xFFFFFFFF
    local function ror(x, k) return ((x >> k) | (x << (32 - k))) & M end
    local H = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19}
    local total = n + 1
    while total % 64 ~= 56 do total = total + 1 end
    total = total + 8
    local bits = n * 8
    local function b(i)
        if i < n then
            local value = byte_at(i)
            assert(integer(value, 0, 255), "unavailable or invalid hashed byte")
            return value
        end
        if i == n then return 0x80 end
        if i < total - 8 then return 0 end
        return (bits >> (8 * (total - 1 - i))) & 0xFF
    end
    local w = {}
    for chunk = 0, total - 1, 64 do
        for t = 0, 15 do
            local p = chunk + t * 4
            w[t] = (b(p) << 24) | (b(p + 1) << 16) | (b(p + 2) << 8) | b(p + 3)
        end
        for t = 16, 63 do
            local s0 = ror(w[t-15], 7) ~ ror(w[t-15], 18) ~ (w[t-15] >> 3)
            local s1 = ror(w[t-2], 17) ~ ror(w[t-2], 19) ~ (w[t-2] >> 10)
            w[t] = (w[t-16] + s0 + w[t-7] + s1) & M
        end
        local a, bb, c, d, e, f, g, h = H[1], H[2], H[3], H[4], H[5], H[6], H[7], H[8]
        for t = 0, 63 do
            local t1 = (h + (ror(e, 6) ~ ror(e, 11) ~ ror(e, 25)) + ((e & f) ~ ((~e) & g)) + K[t+1] + w[t]) & M
            local t2 = ((ror(a, 2) ~ ror(a, 13) ~ ror(a, 22)) + ((a & bb) ~ (a & c) ~ (bb & c))) & M
            h, g, f, e, d, c, bb, a = g, f, e, (d + t1) & M, c, bb, a, (t1 + t2) & M
        end
        for i, v in ipairs({a, bb, c, d, e, f, g, h}) do H[i] = (H[i] + v) & M end
    end
    return fmt("%08x%08x%08x%08x%08x%08x%08x%08x", H[1], H[2], H[3], H[4], H[5], H[6], H[7], H[8])
end

-- BizHawk globals, wrapped once. API objects are userdata in EmuHawk: call, never type-check.
function G.bizhawk()
    return {
        read_u8 = function(a, d) return memory.read_u8(a, d) end,
        read_range = function(a, n, d) return memory.read_bytes_as_array(a, n, d) end,
        write_u8 = function(a, v, d) memory.write_u8(a, v, d) end,
        domain_size = function(d) return memory.getmemorydomainsize(d) end,
        advance = function() emu.frameadvance() end,
        framecount = function() return emu.framecount() end,
        set_buttons = function(b) joypad.set(b) end,
        register = function(r) return emu.getregister(r) end,
        on_bus_exec = function(fn, addr, name, domain) return event.onmemoryexecute(fn, addr, name, domain) end,
        unregister = function(h) return event.unregisterbyid(h) end,
        romhash = function() return gameinfo.getromhash() end,
        systemid = function() return emu.getsystemid() end,
        speed = function(p) client.speedmode(p) end,
        saveram = function() client.saveram() end,
        exit = function() client.exit() end,
    }
end

local function read_file(path)
    local f = assert(io.open(path, "rb"), "cannot open " .. path)
    local text = f:read("a")
    f:close()
    return text
end

-- The EXECUTED cartridge's identity (docs/gen2/OVERLAY_ADMISSION.md D5), separate from the base facts the route facts,
-- profile and charmap bind. `base` is the clean build's sha1 (SLINK_GEN2_ROM_SHA1). A clean run executes the base; an
-- overlay run executes the published overlay (SLINK_GEN2_OVERLAY_SHA1, hashed by the launcher from the staged image)
-- and must carry the execution-binding sidecar pin. Neither identity ever stands in for the other: returns
-- {kind, rom_sha1 (executed), binding_sha256} or nil, why.
function G.identity(getenv, base)
    local function value(name)
        local v = getenv(name)
        if v == nil or v == "" then return nil end
        return v
    end
    local function hex(v, n) return type(v) == "string" and #v == n and v:match("^%x+$") ~= nil end
    local kind, overlay, exec, binding = value("SLINK_GEN2_ARTIFACT_KIND"), value("SLINK_GEN2_OVERLAY_SHA1"),
                                         value("SLINK_GEN2_EXEC_SHA1"), value("SLINK_GEN2_BINDING_SHA256")
    kind = kind or (overlay and "overlay" or "clean")
    if kind == "clean" then
        if overlay or binding then return nil, "a clean run carries no overlay identity" end
        if exec and exec:lower() ~= base then return nil, "SLINK_GEN2_EXEC_SHA1 differs from the clean base on a clean run" end
        return {kind="clean", rom_sha1=base}
    end
    if kind ~= "overlay" then return nil, "unsupported SLINK_GEN2_ARTIFACT_KIND" end
    if not hex(overlay, 40) then return nil, "an overlay run requires SLINK_GEN2_OVERLAY_SHA1" end
    overlay = overlay:lower()
    if overlay == base then return nil, "the overlay sha1 equals the clean base" end
    if exec and exec:lower() ~= overlay then return nil, "SLINK_GEN2_EXEC_SHA1 differs from SLINK_GEN2_OVERLAY_SHA1" end
    if not hex(binding, 64) then
        return nil, "an overlay run requires the SLINK_GEN2_BINDING_SHA256 pin (data/games/gen2_<title>/overlay/binding.json)"
    end
    return {kind="overlay", rom_sha1=overlay, binding_sha256=binding:lower()}
end

-- Case, route facts and runner bindings. Anything missing or malformed refuses the run.
function G.inputs(getenv, json)
    local function need(name)
        local value = getenv(name)
        assert(type(value) == "string" and value ~= "", "missing environment " .. name)
        return value
    end
    local function decode(name)
        local value, why = json.decode(need(name))
        assert(json.kind(value) == "object", "malformed " .. name .. ": " .. tostring(why))
        return value
    end
    local env = {root=need("SLINK_ROOT"), title=need("SLINK_GEN2_TITLE"), rom_sha1=need("SLINK_GEN2_ROM_SHA1"):lower(),
                 dir=need("SLINK_GEN2_SAVERAM_DIR"), saveram=need("SLINK_GEN2_SAVERAM_NAME")}
    assert(({crystal=true, gold=true, silver=true})[env.title], "unsupported SLINK_GEN2_TITLE")
    assert(#env.rom_sha1 == 40 and env.rom_sha1:match("^%x+$"), "malformed SLINK_GEN2_ROM_SHA1")
    -- rom_sha1 stays the clean base the facts bind (route facts, profile, charmap); exec_sha1 is what actually runs.
    local identity, why = G.identity(getenv, env.rom_sha1)
    assert(identity, why)
    env.base_sha1, env.kind, env.exec_sha1, env.binding_sha256 = env.rom_sha1, identity.kind, identity.rom_sha1, identity.binding_sha256
    assert(need("SLINK_GEN2_CORE_MODE") == "CGB", "played fixtures require the CGB core")
    local qualify = getenv("SLINK_GEN2_QUALIFY")
    if qualify == nil or qualify == "" then
        assert(need("SLINK_GEN2_COLD") == "1", "played fixtures start from a cold boot")
    else
        assert(need("SLINK_GEN2_COLD") == "0", "qualification boots the candidate SaveRAM (warm descriptor)")
    end
    assert(not env.saveram:find("[/\\]"), "SaveRAM name must be a bare file name")
    local case, facts = decode("SLINK_GEN2_FIXTURE_CASE"), decode("SLINK_GEN2_ROUTE_FACTS")
    assert(case.title == env.title and (case.target == "town" or case.target == "battle")
           and (case.identity == "default" or case.identity == "ot2"), "fixture case differs from the selected title")
    -- An errand fixture (tools/gen2_fixtures.ERRAND_FIXTURES) is named by its facts: only errand facts carry
    -- the errand events, so a plain battle case can never run the errand route or vice versa.
    local errand = type(facts.observer) == "table" and facts.observer.errand_events ~= nil
    -- The one exception: the gen2_ball_gate duo (case.ball_gate) plays the errand from a zero-Ball town fixture
    -- (docs/gen2/reviews/DUO_WAVE_D_FACTS_2026-09-24.md), so its case keeps the town fixture's name.
    local town_errand = errand and case.target == "town" and case.ball_gate == true
    assert(case.name == env.title .. "_" .. case.target .. (case.identity == "ot2" and "_ot2" or "")
           .. ((errand and not town_errand) and "_errand" or ""), "fixture case name mismatch")
    assert(not errand or case.target == "battle" or town_errand, "the errand ends as a battle fixture")
    assert(type(case.attempt_id) == "string" and #case.attempt_id <= 80 and case.attempt_id:match("^[%w_%-]+$"),
           "bounded attempt ID required")
    assert(integer(case.max_frames, 1, 1000000) and integer(case.max_phase_frames, 1, case.max_frames)
           and integer(case.settle_frames, 1, case.max_frames) and integer(case.title_idle_frames, 0, 40000),
           "bounded frame budgets required")
    assert(facts.schema == "gen2-scripted-route-facts-v1" and facts.title == env.title
           and facts.rom_sha1 == env.rom_sha1 and facts.core_mode == "CGB", "route facts differ from the selected ROM")
    assert(type(facts.fingerprint) == "string" and #facts.fingerprint == 64 and facts.fingerprint:match("^%x+$"),
           "route facts fingerprint required")
    for _, key in ipairs({"maps", "ui_origins", "balls", "starter", "observer"}) do
        assert(json.kind(facts[key]) == "object", "route facts missing " .. key)
    end
    for _, key in ipairs({"overworld_tick", "save_completed", "facing", "screen", "scene_symbols", "prompts",
                          "object", "passable_collision", "pokegear_obtained_bit", "got_starter_event"}) do
        assert(facts.observer[key] ~= nil, "route facts observer missing " .. key)
    end
    -- Optional SLINK_GEN2_ROUTE_LEDGES {map name -> {{x, y, dirs}}} (tools/gen2_fixtures.route_ledges): the HOP_*
    -- tiles the shared step rule (lua/tests/gen2_walk.lua) hops. A separate field: the fingerprinted grid keeps
    -- ledges as walls, so attaching them here never changes facts.fingerprint.
    local ledges = getenv("SLINK_GEN2_ROUTE_LEDGES")
    if ledges ~= nil and ledges ~= "" then
        local HOP = {Up=true, Down=true, Left=true, Right=true}
        for name, list in pairs(decode("SLINK_GEN2_ROUTE_LEDGES")) do
            local map = facts.maps[name]
            assert(json.kind(map) == "object" and json.kind(list) == "array", "route ledges name an unknown map")
            for _, ledge in ipairs(list) do
                assert(integer(ledge.x, 0, map.width - 1) and integer(ledge.y, 0, map.height - 1)
                       and json.kind(ledge.dirs) == "array" and #ledge.dirs >= 1, "malformed route ledge")
                for _, d in ipairs(ledge.dirs) do assert(HOP[d], "malformed route ledge direction") end
            end
            map.ledges = list
        end
    end
    if qualify ~= nil and qualify ~= "" then
        local q = decode("SLINK_GEN2_QUALIFY")
        assert(G.QUALIFY_STAGES[q.stage] == true and type(q.stage_fingerprint) == "string"
               and #q.stage_fingerprint == 64 and q.stage_fingerprint:match("^%x+$"), "qualification stage binding required")
        local qf = q.facts
        assert(json.kind(qf) == "object" and qf.schema == "gen2-qualify-facts-v1" and qf.title == env.title
               and qf.rom_sha1 == env.rom_sha1 and qf.route_facts_fingerprint == facts.fingerprint
               and qf.speed_percent == G.QUALIFY_SPEED_PERCENT, "qualification facts differ from the selected ROM or route")
        for _, key in ipairs({"ui_origins", "sites", "prompts"}) do
            assert(json.kind(qf[key]) == "object", "qualification facts missing " .. key)
        end
        env.qualify = q
    end
    env.case, env.facts = case, facts
    return env
end

-- Selected generated profile; every observer RAM address must be present in it.
function G.profile(env, json)
    local wrapper = assert(json.decode(read_file(env.root .. "/data/games/gen2_" .. env.title .. "/profile.json"),
                                       {items=1000000}), "profile JSON malformed")
    local profile = wrapper.titles and wrapper.titles[env.title]
    assert(wrapper.schema == "gen2-profile-v1" and type(profile) == "table" and profile.title == env.title
           and profile.rom_sha1 == env.rom_sha1 and (wrapper.source or {}).rom_sha1 == env.rom_sha1,
           "profile belongs to another ROM or title")
    local missing = {}
    local names = {}
    for _, name in ipairs(G.REQUIRED_RAM) do names[#names + 1] = name end
    for _, name in pairs(env.facts.observer.scene_symbols) do names[#names + 1] = name end
    for _, name in ipairs(names) do
        if not integer((profile.ram or {})[name], 0xC000, 0xDFFF) or not integer((profile.ram_bank or {})[name], 0, 7) then
            missing[#missing + 1] = name
        end
    end
    for _, name in ipairs(G.REQUIRED_HRAM) do
        if not integer((profile.hram or {})[name], 0xFF80, 0xFFFE) then missing[#missing + 1] = name end
    end
    table.sort(missing)
    assert(#missing == 0, "profile facts missing: " .. table.concat(missing, ","))
    return profile
end

-- The executed-artifact view (lua/gen2/artifact.lua, D3): {kind, rom_sha1, base_sha1, binding_sha256, sites, checkpoint,
-- anchors, profile_rom}. A clean run's view carries identity only (its sites/checkpoint are the pack's own, which every
-- clean caller already reads). An overlay run's view comes from the generated execution binding, checked against the
-- launcher's sidecar pin and the hashed overlay sha1; there is no fallback to the clean sites.
function G.artifact(root, json, env)
    if env.kind == "clean" then
        return {kind="clean", rom_sha1=env.exec_sha1, base_sha1=env.base_sha1}
    end
    local function read(rel)
        return assert(json.decode(read_file(root .. "/data/games/gen2_" .. env.title .. "/" .. rel), {items=1000000}),
                      rel .. " malformed")
    end
    local data = {sites=read("engine_signals.json"), checkpoint=read("write_checkpoint.json"), profile=read("profile.json")}
    local Artifact = dofile(root .. "/lua/gen2/artifact.lua")
    local view, why = Artifact.view(root, json, data, env.title, {kind="overlay", sha1=env.exec_sha1,
        base_sha1=env.base_sha1, binding_sha256=env.binding_sha256})
    assert(view, "overlay execution view refused: " .. tostring(why))
    assert(view.kind == "overlay" and view.rom_sha1 == env.exec_sha1 and view.base_sha1 == env.base_sha1,
           "overlay execution view differs from the staged identity")
    return view
end

-- The fields every overlay receipt carries on the receipt and on each run (stream A's validators): empty for clean,
-- whose committed receipts keep their shape.
function G.artifact_fields(view)
    if view == nil or view.kind == "clean" then return {} end
    return {artifact_kind="overlay", binding_sha256=view.binding_sha256, base_sha1=view.base_sha1}
end

-- CGB WRAM geometry (Pan Docs): $C000-$CFFF bank 0, $D000-$DFFF the selected bank 1-7. BizHawk's flat
-- WRAM domain holds bank n at n*$1000, so a named bank is read without trusting the live SVBK.
function G.wram_offset(bank, addr, n)
    if bank == 0 and addr >= 0xC000 and addr + n <= 0xD000 then return addr - 0xC000 end
    if integer(bank, 1, 7) and addr >= 0xD000 and addr + n <= 0xE000 then return bank * 0x1000 + addr - 0xD000 end
    error(fmt("WRAM range $%X+%d outside its bank %s window", addr, n, tostring(bank)), 0)
end

-- Every loaded module and pack file, the emulator identity checks, and the reads IO.
function G.context(api, getenv)
    local root = getenv("SLINK_ROOT")
    assert(type(root) == "string" and root ~= "", "missing environment SLINK_ROOT")
    local L = function(rel) return dofile(root .. "/" .. rel) end
    local json = L("lua/json_codec.lua")
    local env = G.inputs(getenv, json)
    local profile = G.profile(env, json)
    local charmap = L("data/games/gen2_" .. env.title .. "/charmap.lua")
    assert(type(charmap) == "table" and (charmap.source or {}).rom_sha1 == env.rom_sha1
           and type(charmap.glyphs) == "table" and type(charmap.encoding) == "table", "charmap belongs to another ROM")
    for _, glyph in pairs(G.GLYPH) do assert(charmap.encoding[glyph] ~= nil, "charmap lacks glyph " .. glyph) end
    -- The grid's labels are matched against the decoded tilemap, so an unencodable glyph would read as a
    -- menu that never matches instead of refusing: same authoring check as G.GLYPH above.
    for _, glyphs in ipairs(G.BATTLE_MENU_GRID.labels) do
        for _, glyph in ipairs(glyphs) do assert(charmap.encoding[glyph] ~= nil, "charmap lacks glyph " .. glyph) end
    end
    local hash = api.romhash()
    assert(type(hash) == "string" and hash:lower() == env.exec_sha1,
           "running ROM differs from the selected SHA1 (" .. env.kind .. " artifact " .. env.exec_sha1 .. ")")
    assert(api.systemid() == "GBC", "running core is not in CGB mode")
    local ctx = {api=api, env=env, case=env.case, facts=env.facts, obs=env.facts.observer, profile=profile,
                 json=json, charmap=charmap, root=root, scopes={}, log=function() end,
                 Permit=L("lua/write_permit.lua"), Host=L("lua/scripted_inputs.lua"),
                 Play=L("lua/tests/gen2_scripted_play.lua"), Binding=L("lua/gb_hook_binding.lua"),
                 qualify=env.qualify, prompts=env.facts.observer.prompts}
    ctx.artifact = G.artifact(root, json, env)
    ctx.ident = G.artifact_fields(ctx.artifact)   -- {} on clean; {artifact_kind, binding_sha256, base_sha1} on an overlay
    if env.qualify then
        ctx.Qualify, ctx.prompts = L("lua/tests/gen2_qualify.lua"), env.qualify.facts.prompts
        local ram = profile.ram
        assert(integer(ram.wPartyMonNicknamesEnd, 0xC000, 0xDFFF) and ram.wPartyMonNicknamesEnd > ram.wPartyCount,
               "profile facts missing: wPartyMonNicknamesEnd")
    end
    local bank_of = {}
    for name, addr in pairs(profile.ram) do
        local bank = profile.ram_bank[name]
        if bank ~= nil then bank_of[addr] = (bank_of[addr] == nil or bank_of[addr] == bank) and bank or false end
    end
    ctx.bank_of = bank_of
    local io_ = {}
    function io_.read_range(addr, n, domain)
        assert(domain == "System Bus" and type(bank_of[addr]) == "number", "read outside a profile symbol")
        return api.read_range(G.wram_offset(bank_of[addr], addr, n), n, "WRAM")
    end
    function io_.bank_valid(bank, addr, n)
        return bank_of[addr] == bank and (pcall(G.wram_offset, bank, addr, n))
    end
    ctx.reads = assert(L("lua/gen2/reads.lua").new(profile, io_))
    function ctx.sym(name, offset, n)
        local addr = profile.ram[name] + (offset or 0)
        local bytes = api.read_range(G.wram_offset(profile.ram_bank[name], addr, n or 1), n or 1, "WRAM")
        assert(type(bytes) == "table" and #bytes == (n or 1), "WRAM read failed: " .. name)
        return bytes
    end
    return ctx
end

-- Pure screen parsing over a decoded tilemap (rows of charmap glyph names). Without a grid this is the
-- single-column read, unchanged. With one (a source geometry, G.BATTLE_MENU_GRID) every label's full
-- glyph run must sit at its derived cell and the cursor must sit one tile left of exactly one of them:
-- a menu of any other shape is refused, never silently re-read as this one.
function G.parse_menu(rows, width, height, grid)
    local g = G.GLYPH
    if grid then
        local items, cursor = {}, nil
        for r = 0, grid.rows - 1 do
            local row = rows[grid.y + 2 * r + 1]
            if type(row) ~= "table" then return nil end
            for c = 0, grid.columns - 1 do
                local index, x = r * grid.columns + c + 1, grid.x + c * grid.spacing + 1
                local glyphs = grid.labels[index]
                for i, glyph in ipairs(glyphs) do
                    if row[x + i - 1] ~= glyph then return nil end
                end
                if row[x - 1] == g.cursor then
                    if cursor then return nil end
                    cursor = index
                end
                items[index] = table.concat(glyphs)
            end
        end
        if not cursor then return nil end
        return {items=items, cursor=cursor, columns=grid.columns}
    end
    local cx, cy
    for y = 1, height do
        for x = 1, width do
            if rows[y][x] == g.cursor then
                if cx then return nil end
                cx, cy = x, y
            end
        end
    end
    if not cx then return nil end
    local left, right, top, bottom
    for x = cx - 1, 1, -1 do if rows[cy][x] == g.side then left = x break end end
    for x = cx + 1, width do if rows[cy][x] == g.side then right = x break end end
    if not left or not right then return nil end
    for y = cy - 1, 1, -1 do if rows[y][left] == g.top_left then top = y break end end
    for y = cy + 1, height do if rows[y][left] == g.bottom_left then bottom = y break end end
    if not top or not bottom then return nil end
    local items, starts, columns, cursor = {}, {}, 0, nil
    for y = top + 1, bottom - 1 do
        local x = left + 1
        while x < right do
            local cell = rows[y][x]
            if cell == g.space or cell == g.cursor or cell == "▷" then
                x = x + 1
            else
                local start, text = x, {}
                while x < right do
                    cell = rows[y][x]
                    local nxt = rows[y][x + 1]
                    if cell == g.cursor or cell == "▷" then break end
                    if cell == g.space and (x + 1 >= right or nxt == g.space or nxt == g.cursor or nxt == "▷") then break end
                    text[#text + 1] = cell
                    x = x + 1
                end
                items[#items + 1] = table.concat(text)
                if y == cy and start == cx + 1 then cursor = #items end
                if not starts[start] then starts[start], columns = true, columns + 1 end
            end
        end
    end
    if not cursor or #items == 0 then return nil end
    return {items=items, cursor=cursor, columns=columns}
end

function G.classify_prompt(rows, prompts)
    local found
    for prompt, anchors in pairs(prompts) do
        for _, anchor in ipairs(anchors) do
            for _, row in ipairs(rows) do
                if table.concat(row):find(anchor, 1, true) then
                    if found and found ~= prompt then return nil end
                    found = prompt
                end
            end
        end
    end
    return found
end

-- Code-site hooks: UI origins, the overworld input tick and the native save completion.
function G.hooks(ctx)
    local api, obs = ctx.api, ctx.obs
    local binding = ctx.Binding.new({read_u8=api.read_u8, read_range=api.read_range, register=api.register,
        framecount=api.framecount, on_bus_exec=api.on_bus_exec, unregister=api.unregister},
        {bus_domain="System Bus", rom_domain="ROM", bank_domain="System Bus", pc_register="PC", sp_register="SP",
         bank_address=ctx.profile.hram.hROMBank})
    local state = {seq=0, ui=nil, tick=nil, saves=0, errors={}, handles={}}
    ctx.state = state
    local function watch(id, site, on_hit)
        local valid = binding:validate({id=id, bank=site.bank, address=site.addr, expected_hex=site.hex,
                                        capture_offset=0, rom_offset=site.flat})
        local handle = binding:register(valid, function()
            local ok, hit = pcall(binding.context, binding, valid)
            if not ok then state.errors[#state.errors + 1] = tostring(hit) return end
            if hit then
                state.seq = state.seq + 1
                on_hit(hit.frame, state.seq)
            end
        end, "SLink-gen2-gate-" .. id)
        assert(binding:valid_handle(handle), id .. ": hook registration failed")
        state.handles[#state.handles + 1] = handle
    end
    local origins = {}
    for kind, site in pairs(ctx.facts.ui_origins) do origins[kind] = site end
    for kind, site in pairs(ctx.qualify and ctx.qualify.facts.ui_origins or {}) do origins[kind] = site end
    for kind, site in pairs(origins) do
        watch(kind, site, function(frame, seq)
            local ui = state.ui
            -- A looping origin (InitClock.SetHourLoop) re-fires every frame: one context, first and last frame kept.
            if ui and ui.kind == kind and ui.seq == seq - 1 then ui.seq, ui.last = seq, frame
            else state.ui = {kind=kind, origin=site.symbol, frame=frame, last=frame, seq=seq} end
        end)
    end
    watch("overworld_tick", obs.overworld_tick, function(frame, seq) state.tick = {frame=frame, seq=seq} end)
    watch("save_completed", obs.save_completed, function() state.saves = state.saves + 1 end)
    -- Qualification: counted source sites (CONTINUE path, RTC acceptance, overwrite branch).
    state.hits = {}
    for id, site in pairs(ctx.qualify and ctx.qualify.facts.sites or {}) do
        state.hits[id] = 0
        watch(id, site, function() state.hits[id] = state.hits[id] + 1 end)
    end
    function state.release()
        for _, handle in ipairs(state.handles) do pcall(binding.unregister, binding, handle) end
        state.handles = {}
    end
    return state
end

function G.screen(ctx)
    local w, h = ctx.obs.screen.width, ctx.obs.screen.height
    local bytes = ctx.sym("wTilemap", 0, w * h)
    local rows = {}
    for y = 1, h do
        rows[y] = {}
        for x = 1, w do
            local byte = bytes[(y - 1) * w + x]
            rows[y][x] = ctx.charmap.glyphs[byte] or fmt("<$%02X>", byte)
        end
    end
    return rows
end

-- The qualified game observer: one source-bound point per frame for gen2_scripted_play.
function G.observer(ctx)
    local api, obs, facts, case, reads, state = ctx.api, ctx.obs, ctx.facts, ctx.case, ctx.reads, ctx.state
    local passable, facing = {}, {}
    for _, code in ipairs(obs.passable_collision) do passable[code] = true end
    for name, value in pairs(obs.facing) do facing[value] = name end
    local o = obs.object
    -- ponytail: opt-in live diagnostics (SLINK_GEN2_TRACE=1): one line per 120 frames, never per frame
    local trace = os and os.getenv and os.getenv("SLINK_GEN2_TRACE") == "1"
    return function()
        assert(#state.errors == 0, "code-site hook refused: " .. tostring(state.errors[1]))
        local frame = api.framecount()
        -- GameInit loads wSaveFileExists before any UI origin runs (C engine/menus/intro_menu.asm:1329-1330,
        -- G :1140-1142); MainMenu_GetWhichMenu offers CONTINUE on it (C engine/menus/main_menu.asm:191-199).
        local point = {title=ctx.env.title, rom_sha1=facts.rom_sha1, core_mode="CGB", attempt_id=case.attempt_id,
                       facts_fingerprint=facts.fingerprint,
                       has_existing_save=state.ui ~= nil and ctx.sym("wSaveFileExists")[1] ~= 0,
                       save_success_counter=state.saves}
        local u = state.ui
        if u and (state.tick == nil or u.seq > state.tick.seq) then
            local view = {kind=u.kind, origin=u.origin}
            local ready = frame - u.frame >= G.UI_SETTLE_FRAMES
                and (u.consumed == nil or (not G.ONE_SHOT_KINDS[u.kind] and frame - u.consumed >= G.UI_REPULSE_FRAMES))
                and (not G.LOOP_KINDS[u.kind] or frame - u.last <= G.LOOP_WINDOW)
            if G.MENU_KINDS[u.kind] then
                local rows = G.screen(ctx)
                local menu = G.parse_menu(rows, obs.screen.width, obs.screen.height,
                    u.kind == "battle_menu" and G.BATTLE_MENU_GRID or nil)
                if menu then view.items, view.cursor, view.columns = menu.items, menu.cursor, menu.columns
                else ready = false end
                if u.kind == "yes_no" then view.prompt = G.classify_prompt(rows, ctx.prompts) end
            elseif u.kind == "prompt_button" then
                view.prompt = G.classify_prompt(G.screen(ctx), ctx.prompts)   -- which text is waiting
            elseif u.kind == "move_menu" then
                -- The errand's rival battle: the move list by its source geometry (the U1d faint leg's reader).
                ctx.move_list = ctx.move_list or dofile(ctx.root .. "/lua/tests/duo/gen2_faint_inputs.lua").move_list
                local list = ctx.move_list(G.screen(ctx))
                if list then view.items, view.cursor, view.columns = list.items, list.cursor, list.columns
                else ready = false end
            end
            point.ui, point.input_ready = view, ready
        end
        if trace and frame % 30 == 0 and ctx.log then
            local s = state.ui
            ctx.log(fmt("  trace @%d ui=%s seq=%s age=%s last=%s consumed=%s tick=%s ready=%s items=%s cursor=%s", frame,
                s and s.kind or "-", s and s.seq or "-", s and frame - s.frame or "-", s and frame - s.last or "-", s and s.consumed and frame - s.consumed or "-",
                state.tick and state.tick.seq or "-", tostring(point.input_ready),
                point.ui and point.ui.items and table.concat(point.ui.items, "|") or "-", point.ui and point.ui.cursor or "-"))
        end
        local map = reads.read_map()
        if map then point.map_group, point.map_number, point.x, point.y = map.group, map.number, map.x, map.y end
        local party = reads.read_party()
        if party then
            point.party_count = party.count
            if party.mons[1] then point.starter_species, point.starter_level = party.mons[1].species_id, party.mons[1].level end
        end
        local battle = reads.read_battle()
        if battle then point.battle_mode = battle.mode end
        -- OWPlayerInput ran within the window, no UI context is newer, and no battle is starting.
        point.overworld_ready = point.ui == nil and state.tick ~= nil and point.battle_mode == 0
            and frame - state.tick.frame <= G.OVERWORLD_WINDOW
        local admission = reads.read_admission_facts()
        if admission then point.saved_at_least_once = admission.saved_at_least_once end
        local pocket = reads.read_pocket("balls")
        if pocket then
            local items = {}
            for i, entry in ipairs(pocket.entries) do items[i] = {id=entry.id, quantity=entry.quantity} end
            point.ball_pocket = {count=pocket.count, items=items, terminator=255}
        end
        point.mom_scene = ctx.sym(obs.scene_symbols.PlayersHouse1F)[1]
        point.lab_scene = ctx.sym(obs.scene_symbols.ElmsLab)[1]
        point.new_bark_scene = ctx.sym(obs.scene_symbols.NewBarkTown)[1]
        point.pokegear_obtained = (ctx.sym("wPokegearFlags")[1] >> obs.pokegear_obtained_bit) & 1 == 1
        local event = obs.got_starter_event
        point.got_starter = (ctx.sym("wEventFlags", event // 8)[1] >> (event % 8)) & 1 == 1
        if obs.errand_events then
            local function flag(id) return (ctx.sym("wEventFlags", id // 8)[1] >> (id % 8)) & 1 == 1 end
            point.got_egg = flag(obs.errand_events.EVENT_GOT_MYSTERY_EGG_FROM_MR_POKEMON)
            point.gave_egg = flag(obs.errand_events.EVENT_GAVE_MYSTERY_EGG_TO_ELM)
        end
        point.can_step = {Up=passable[ctx.sym("wTileUp")[1]] == true, Down=passable[ctx.sym("wTileDown")[1]] == true,
                          Left=passable[ctx.sym("wTileLeft")[1]] == true, Right=passable[ctx.sym("wTileRight")[1]] == true}
        local structs = ctx.sym("wObjectStructs", 0, o.length * o.count)
        local function field(index, offset) return structs[index * o.length + offset + 1] end
        point.facing = facing[field(0, o.direction)]
        point.blocked = {}
        if map then
            -- Object struct coords are map coords + 4 (engine/overworld/player_object.asm: wXCoord/wYCoord
            -- add 4; NPC spawns write the same OBJECT_MAP_X/Y bias, engine/overworld/map_objects.asm). Not player-relative: mid-step the player struct already holds its destination while
            -- wXCoord/wYCoord lag, which shifted every NPC by one tile (live attempt n2-crystal-town-a6).
            local dx, dy = 4, 4
            for index = 1, o.count - 1 do
                if field(index, o.sprite) ~= 0 then
                    point.blocked[#point.blocked + 1] = {x=field(index, o.map_x) - dx, y=field(index, o.map_y) - dy}
                    if trace and ctx.log and frame % 30 == 0 then
                        ctx.log(fmt("  trace-obj @%d player struct %d,%d wXY %d,%d obj%d struct %d,%d -> %d,%d", frame,
                            field(0, o.map_x), field(0, o.map_y), map.x, map.y, index, field(index, o.map_x),
                            field(index, o.map_y), field(index, o.map_x) - dx, field(index, o.map_y) - dy))
                    end
                end
            end
        end
        return point
    end
end

-- O-10 Ball-pocket staging: the only harness write, bounded to the profile Ball-pocket span.
function G.o10_handler(ctx)
    local api, profile, facts, case, reads = ctx.api, ctx.profile, ctx.facts, ctx.case, ctx.reads
    local ram, banks, capacity = profile.ram, profile.ram_bank, profile.derived.ball_capacity
    local lo, bank = ram.wNumBalls, banks.wNumBalls
    assert(integer(capacity, 1, 99) and ram.wBalls == lo + 1 and banks.wBalls == bank, "profile Ball pocket geometry")
    local hi = ram.wBalls + capacity * 2 + 1   -- exclusive: count, (id, quantity) x capacity, terminator
    local balls = facts.balls
    assert(balls.count_address == lo and balls.data_address == ram.wBalls and balls.bank == bank
           and balls.capacity == capacity, "route facts Ball pocket disagrees with the profile")
    local function inside(addr, n) return integer(addr, 0, 0xFFFF) and addr >= lo and addr + n <= hi end
    local permit = ctx.Permit.new({
        write_u8 = function(addr, value) api.write_u8(G.wram_offset(bank, addr, 1), value, "WRAM") end,
        domains = {["System Bus"] = {bounds=inside,
            mapped=function(addr, n) return (pcall(G.wram_offset, bank, addr, n)) end,
            pointer_stable=function() return true end}},
        lifetime = {capture=function() return api.framecount() end,
                    valid=function(token) return api.framecount() == token end},
        provenance = function(domain, addr, n, reason)
            return {scope=reason, exception="O-10", natural_acquisition=false, domain=domain, addr=addr, n=n}
        end,
    })
    ctx.permit = permit
    return function(request)
        assert(case.target == "battle", "town fixture refuses every harness write (O-10 is battle-only)")
        assert(#ctx.scopes == 0, "O-10 staging already recorded")
        assert(type(request) == "table" and request.kind == "o10-ball-pocket" and request.exception == "O-10"
               and request.natural_acquisition == false and request.attempt_id == case.attempt_id
               and request.facts_fingerprint == facts.fingerprint and request.bank == bank
               and type(request.expected) == "table" and type(request.writes) == "table", "malformed O-10 request")
        for _, row in ipairs(request.expected) do
            assert(type(row) == "table" and inside(row.address, 1), "O-10 preimage outside the Ball pocket")
            assert(api.read_range(G.wram_offset(bank, row.address, 1), 1, "WRAM")[1] == row.value, "O-10 preimage differs")
        end
        local spans = {}
        for i, row in ipairs(request.writes) do
            assert(type(row) == "table" and integer(row.value, 0, 255), "O-10 write value invalid")
            spans[i] = {domain="System Bus", addr=row.address, bytes={row.value}}
        end
        assert(#spans > 0, "O-10 request carries no writes")
        permit:scope(G.O10_SCOPE, function(domain, addr, n) return domain == "System Bus" and inside(addr, n) end,
                     function() permit:write_batch(spans) end)
        local pocket = reads.read_pocket("balls")
        assert(pocket and pocket.count == 1 and pocket.entries[1].id == balls.item
               and pocket.entries[1].quantity == balls.quantity, "O-10 Ball pocket did not read back")
        ctx.scopes[#ctx.scopes + 1] = G.O10_SCOPE
        ctx.log(fmt("  O-10 staged %d Poke Ball(s) (tests/validation only; not natural acquisition)", balls.quantity))
        return true
    end
end

-- Normal buttons only; a confirm while a UI context is shown consumes that context.
function G.button_step(ctx)
    return function(buttons)
        assert(type(buttons) == "table", "button table required")
        local confirm = false
        for key, value in pairs(buttons) do
            assert(BUTTON[key] == true and type(value) == "boolean", "non-button input refused: " .. tostring(key))
            confirm = confirm or (value and G.CONFIRM[key] == true)
        end
        local state = ctx.state
        if confirm and state and state.ui and (state.tick == nil or state.ui.seq > state.tick.seq) then
            state.ui.consumed = ctx.api.framecount()
        end
        ctx.api.set_buttons(buttons)
        ctx.api.advance()
    end
end

-- SHA-256 of the 32 KiB CartRAM; the emulator RTC trailer is never hashed.
function G.cart_digest(api)
    local size = api.domain_size("CartRAM")
    assert(integer(size, G.CART_RAM_BYTES, 2^24), "CartRAM domain smaller than 32 KiB")
    local cart = api.read_range(0, G.CART_RAM_BYTES, "CartRAM")
    assert(type(cart) == "table" and #cart == G.CART_RAM_BYTES, "CartRAM read failed")
    return G.sha256(function(i) return cart[i + 1] end, G.CART_RAM_BYTES)
end

-- Flush the SaveRAM and prove the file is exactly the live CartRAM plus the RTC trailer.
function G.flush(ctx, digest)
    ctx.api.saveram()
    local saved = read_file(ctx.env.dir .. "/" .. ctx.env.saveram)
    assert(#saved == G.CART_RAM_BYTES + G.RTC_TRAILER_BYTES,
           fmt("flushed SaveRAM is %d bytes, expected CartRAM + %d-byte RTC trailer", #saved, G.RTC_TRAILER_BYTES))
    assert(G.sha256(function(i) return saved:byte(i + 1) end, G.CART_RAM_BYTES) == digest,
           "flushed SaveRAM differs from the live CartRAM")
    return saved
end

local function idle_buttons()
    local idle = {}
    for _, name in ipairs(G.BUTTONS) do idle[name] = false end
    return idle
end

-- On a failed live stage, the visible screen text (wTilemap through the charmap): the one
-- fact a failure message cannot carry. Diagnostics only; never an oracle.
local function log_screen(ctx)
    local ok, rows = pcall(G.screen, ctx)
    if not ok or not ctx.log then return end
    for y, row in ipairs(rows) do ctx.log(fmt("  screen %02d |%s|", y, table.concat(row))) end
end

-- The route, the native save witness, the CartRAM hash and the receipt.
function G.play(ctx)
    local api, case, facts, env = ctx.api, ctx.case, ctx.facts, ctx.env
    local receipt_path = env.dir .. "/" .. case.name .. ".played.json"
    os.remove(receipt_path)   -- a stale receipt must never describe this attempt
    api.speed(G.SPEED_PERCENT)
    local state = G.hooks(ctx)
    local host = ctx.Host.new({step=G.button_step(ctx), frame=api.framecount, idle=idle_buttons()})
    local on_request = G.o10_handler(ctx)
    local ok, result = pcall(ctx.Play.run, host, G.observer(ctx), facts, case,
        function(_, phase, frame) ctx.log(fmt("  phase %s @%d", phase, frame)) end, on_request)
    state.release()
    if not ok then log_screen(ctx) end
    assert(ok, "route failed: " .. tostring(result))
    assert(state.saves >= 1, "native save completion was not observed")
    assert(#ctx.scopes == (case.target == "battle" and 1 or 0), "harness write scopes differ from the case")
    local cgb = api.read_u8(ctx.profile.hram.hCGB, "System Bus")
    assert(integer(cgb, 1, 255), "the game did not report CGB hardware (hCGB)")
    local digest = G.cart_digest(api)
    local saved = G.flush(ctx, digest)
    local json, phases = ctx.json, {}
    for i, row in ipairs(result.trace) do phases[i] = json.object({phase=row.phase, frame=row.frame}) end
    local body = assert(json.encode(json.object({
        schema=G.RECEIPT_SCHEMA, case=case.name, attempt_id=case.attempt_id, title=env.title, target=case.target,
        facts_fingerprint=facts.fingerprint, rom_sha1=facts.rom_sha1, cartram_sha256=digest,
        cartram_bytes=G.CART_RAM_BYTES, saveram_bytes=#saved, core_mode="CGB", hcgb=cgb,
        speed_percent=G.SPEED_PERCENT, input_mode="normal_buttons", phases=json.array(phases),
        harness_write_scopes=json.array(ctx.scopes), save_success_counter=state.saves,
        natural_ball_acquisition=false, qualified=false})))
    local f = assert(io.open(receipt_path, "wb"), "cannot write " .. receipt_path)
    f:write(body)
    f:close()
    ctx.log("RECEIPT " .. receipt_path)
    return fmt("%s route-saved cartram_sha256=%s (candidate only)", case.name, digest)
end

-- The qualification observer: the route point plus the stage binding and the counted code sites.
function G.qualify_observer(ctx)
    local base, state, q = G.observer(ctx), ctx.state, ctx.qualify
    return function()
        local point = base()
        point.stage_fingerprint = q.stage_fingerprint
        local hits = {}
        for id, n in pairs(state.hits) do hits[id] = n end
        point.hits = hits
        return point
    end
end

-- One qualification stage: warm boot -> CONTINUE -> overworld (-> native re-save), then the GAME witness.
function G.qualify(ctx)
    local api, case, facts, env, q, json = ctx.api, ctx.case, ctx.facts, ctx.env, ctx.qualify, ctx.json
    local out = env.dir .. "/" .. case.name .. "." .. q.stage .. ".witness.json"
    os.remove(out)   -- a stale witness must never describe this attempt
    -- The booted battery bytes, hashed before the first emulated frame can rewrite any of them.
    local booted = G.cart_digest(api)
    api.speed(G.QUALIFY_SPEED_PERCENT)
    local state = G.hooks(ctx)
    local host = ctx.Host.new({step=G.button_step(ctx), frame=api.framecount, idle=idle_buttons()})
    local stage_case = {name=case.name, title=case.title, attempt_id=case.attempt_id, stage=q.stage,
                        stage_fingerprint=q.stage_fingerprint, max_frames=case.max_frames,
                        max_phase_frames=case.max_phase_frames, settle_frames=case.settle_frames}
    local ok, result = pcall(ctx.Qualify.run, host, G.qualify_observer(ctx), facts, q.facts, stage_case,
        function(_, phase, frame) ctx.log(fmt("  phase %s @%d", phase, frame)) end)
    state.release()
    if not ok then log_screen(ctx) end
    assert(ok, "qualification " .. q.stage .. " failed: " .. tostring(result))
    local hits = state.hits
    local continue_selected = hits.continue >= 1 and hits.continue_loaded >= 1
    local rtc_validated = hits.rtc_ok >= 1 and hits.restart_clock == 0
    local native_load_completed = continue_selected and hits.finish_continue >= 1
    assert(continue_selected and rtc_validated and native_load_completed, "native CONTINUE/RTC path was not observed")
    assert(hits.erase_save == 0, "ErasePreviousSave ran")
    local cgb = api.read_u8(ctx.profile.hram.hCGB, "System Bus")
    assert(integer(cgb, 1, 255), "the game did not report CGB hardware (hCGB)")
    local map = assert(ctx.reads.read_map(), "loaded map is unreadable")
    local ram = ctx.profile.ram
    local party, hex = ctx.sym("wPartyCount", 0, ram.wPartyMonNicknamesEnd - ram.wPartyCount), {}
    for i, byte in ipairs(party) do hex[i] = fmt("%02x", byte) end
    local resaved = nil
    if q.stage == "resave" then
        assert(state.saves >= 1, "native save completion was not observed")
        assert(hits.same_save_file >= 1, "the re-save did not take the same-player overwrite branch")
        resaved = G.cart_digest(api)
        G.flush(ctx, resaved)
    else
        assert(state.saves == 0, "a boot/reload stage must not save")
    end
    local phases = {}
    for i, row in ipairs(result.trace) do phases[i] = json.object({phase=row.phase, frame=row.frame}) end
    local body = assert(json.encode(json.object({
        schema=G.WITNESS_SCHEMA, case=case.name, attempt_id=case.attempt_id, stage=q.stage,
        stage_fingerprint=q.stage_fingerprint, title=env.title, rom_sha1=env.exec_sha1, artifact_kind=env.kind,
        facts_fingerprint=facts.fingerprint, qualify_facts_fingerprint=q.facts.fingerprint,
        cartram_sha256=booted, resave_cartram_sha256=resaved, core_mode="CGB", hcgb=cgb,
        speed_percent=G.QUALIFY_SPEED_PERCENT, input_mode="normal_buttons", observer="independent_GAME",
        continue_selected=continue_selected, native_load_completed=native_load_completed,
        rtc_validated=rtc_validated, location=json.array({map.group, map.number}), position=json.array({map.x, map.y}),
        party_raw_hex=table.concat(hex), save_success_counter=state.saves, site_hits=json.object(hits),
        phases=json.array(phases), harness_write_scopes=json.array({}), qualified=false})))
    local f = assert(io.open(out, "wb"), "cannot write " .. out)
    f:write(body)
    f:close()
    ctx.log("WITNESS " .. out)
    return fmt("%s %s witness cartram_sha256=%s (evidence only)", case.name, q.stage, booted)
end

function G.main(api, getenv)
    local root = getenv("SLINK_ROOT") or SLINK_ROOT or "."
    local out, lines = root .. "/" .. G.RESULT, {}
    local function log(s)
        lines[#lines + 1] = s
        local f = io.open(out, "w")
        if f then f:write(table.concat(lines, "\n") .. "\n") f:close() end
    end
    log("[test_gen2_scripted_gate] played-route candidate / fixture qualification stage")
    local ok, why = pcall(function()
        local ctx = G.context(api, getenv)
        ctx.log = log
        log(fmt("  case %s attempt %s facts %s", ctx.case.name, ctx.case.attempt_id, ctx.facts.fingerprint:sub(1, 12)))
        if ctx.qualify then return G.qualify(ctx) end
        return G.play(ctx)
    end)
    log(fmt("RESULT: %s %s", ok and "PASS" or "FAIL", tostring(why)))
    api.exit()
    error("slink-gate-finished", 0)   -- client.exit() is asynchronous
end

if SLINK_GEN2_GATE_LIBRARY then return G end
G.main(G.bizhawk(), os.getenv)
