--[[
  lua/tests/gen2_inspect_gate.lua -- P3b.3a PHYSICAL: lua/gen2/reads.lua qualified on the RUNNING
  cartridge (docs/gen2/GEN2_BINDING_PLAN.md P3b.3a; docs/gen2/gen2_requirements.md R-1, R-3, R-5g).

  Boots WARM from a qualified fixture (tests/fixtures/gen2/<title>_<town|battle>[_ot2].SaveRAM,
  staged by tools/run_gb_gate.py's _gen2_plan through tools/run_gb_gate.run_gate), reaches the
  overworld through the SAME source-qualified CONTINUE path fixture qualification uses, then takes
  ONE raw capture: the party WRAM block and the full CartRAM domain (the active box and all 14
  storage boxes live inside it). The capture's frame, physical domain/offset, logical bus
  address/bank and lengths are printed so tests/live/test_gen2_new_gates.py can decode the SAME
  bytes independently with server/adapters/gen2_codec.py (PYDEC) -- fixture-only agreement never
  closes R-1; only a same-frame Lua/PYDEC disagreement test does.

  CHECKPOINT (R4 #4): valid party bytes alone prove nothing -- TryLoadSaveFile loads the party
  before the CONTINUE confirmation (C engine/menus/save.asm:596-601, intro_menu.asm:338-348,429-437;
  G save.asm:538-543, intro_menu.asm:251-260,313-321). Arrival is decided by lua/tests/gen2_qualify.lua's
  "boot" stage over lua/tests/test_gen2_scripted_gate.lua's bank-checked hooks: the Continue,
  .Check1Pass, .Check2Pass and FinishContinueFunction sites ran (RestartClock/ErasePreviousSave did
  not), then OWPlayerInput ran with no newer UI context and wBattleMode 0. CHECKPOINT is "reached"
  only after that arrival, a byte-stable capture across an idle gap, and OWPlayerInput still
  running inside the gap. It is a liveness proof, not P3b.5's armed write-checkpoint predicate.

  lua/gen2/reads.lua is the ONLY production decoder used here; this file supplies the emulator IO
  binding (named-bank WRAM through the profile's bank map; CartRAM passthrough) and orchestration.
  After the capture no frame advances, so every *_LUA line is decoded at the capture frame, and
  DECODE_FRAME records it. The Python side binds each Lua decode's own raw_hex to the captured bytes.

  R-3 SCOPE NOTE: the RAW_* lines below are a SECOND, independent Lua reader of the same
  profile-declared WRAM addresses (bypassing lua/gen2/reads.lua entirely). The tilemap half of R-3
  IS now closed by the scripted display pass further down: GAME_TRAINER_CARD reads the game's own
  rendered Trainer Card (wPlayerID at (5,4) and wPlayerName at (7,2)) after navigating START ->
  Status with normal buttons. The badge half of R-3 stays OPEN: Johto/Kanto badges are VRAM tiles
  animated as OAM (TrainerCard_JohtoBadgesOAM, engine/menus/trainer_card.asm:149-158,197-207), which
  a wTilemap oracle cannot see -- it needs an OAM/VRAM witness. The PC box header is OUT OF SCOPE:
  Elm's lab has no PC, so no town/battle fixture can reach it (docs/gen2/reviews/
  OMP_R3_R5G_DISPLAY_FACTS_2026-09-23.md).
  R-5g SCOPE NOTE: GENDER_SHINY is a DV-formula cross-check (this file vs an independent Python
  reimplementation). The display half of R-5g IS now closed by GAME_STATS_HEAD: after navigating
  START -> #MON -> the lead party mon's STATS screen, the (18,0) gender glyph and (19,0) shiny
  marker are read from wTilemap and compared against this file's own G.gender_and_shiny over the
  same DVs, with the blank tile taken from the title's charmap.

  Environment (all required): SLINK_ROOT; run_gb_gate._gen2_plan's SLINK_GEN2_TITLE/_ROM_SHA1/
  _CORE_MODE (CGB)/_COLD ("0")/_SAVERAM_DIR/_SAVERAM_NAME; and, from tests/live/test_gen2_new_gates.py
  (tools/gen2_fixtures.route_facts / qualify_facts), SLINK_GEN2_FIXTURE_CASE, SLINK_GEN2_ROUTE_FACTS and
  SLINK_GEN2_QUALIFY with stage "boot". Validation is test_gen2_scripted_gate.lua's G.context.
  Speed is the runner's (run_gb_gate writes SpeedPercent=100); this gate never overrides it.

  Result file: $SLINK_ROOT/patch/build/gen2_inspect_gate_result.txt (RESULT: PASS|FAIL, last line).
  Printed lines (each a single JSON value after its tag, lua/json_codec.lua encoding):
    CHECKPOINT    "reached" | "not reached" (see above)
    DUMP          {frame, party:{domain="WRAM", offset, bus_domain="System Bus", bank, address, length, hex},
                   cartram:{domain="CartRAM", address=0, length=32768, hex}}
    PARTY_LUA     lua/gen2/reads.lua read_party() result
    ACTIVE_BOX_LUA / BOX_LUA_<0..13>   read_active_box() / read_storage_box(i) results
    BADGES_LUA / PLAYER_LUA / BATTLE_LUA   the matching reads.lua accessor result
    RAW_BADGES / RAW_BATTLE / RAW_BOXNUM   the independent hand-rolled second reader (see above)
    GENDER_SHINY  per party slot, {gender, shiny} from dv_word alone (formula cross-check only)
    DECODE_FRAME  the frame counter after every decode above (must equal DUMP.frame)

  Display oracle lines (normal-button navigation; see the R-3/R-5g SCOPE notes):
    GAME_TRAINER_CARD  {frame, id_digits_hex, id_text, expected_id_text, player_id_hex, name_row,
                        name_col, name_length, name_bytes_hex, name_text, expected_name,
                        player_name_hex, blank_byte}
    GAME_STATS_HEAD    {frame, gender_byte, gender_expected, gender_glyph, shiny_byte,
                        shiny_expected, shiny_glyph, blank_byte, species_id, dv_word, gender, shiny}
    GAME_STATS_ITEM    {frame, item_row, item_col, label_text, held_item, item_bytes_hex, item_text,
                        item_expected}
--]]
local G = {}
G.RESULT = "patch/build/gen2_inspect_gate_result.txt"
G.CART_RAM_BYTES = 0x8000
G.SCRIPTED_GATE = "lua/tests/test_gen2_scripted_gate.lua"
-- ponytail: idle-stability window, not a measured native timing; raise if a live run needs longer.
G.STABILITY_IDLE_FRAMES = 60
-- ponytail: scripted-display calibration knobs, not measured native timings. HOLD is the route's
-- proven 12 frames (lua/tests/gen2_scripted_play.lua HOLD): Crystal menus sample the joypad once per
-- loop after WaitBGMap's DelayFrames, so a 2-frame press on the START menu was never seen (live
-- inspect run 2026-09-23: display-card stalled in card_wait with the cursor on the Status entry).
-- Stays < 15 so a held menu direction never auto-repeats. The GAP keeps a second press out of the
-- frame the first is still being consumed in.
G.DISPLAY_HOLD = 12
G.DISPLAY_GAP = 12
-- Frames a screen's tilemap is left to finish drawing after its per-frame joypad state is reached.
G.DISPLAY_SETTLE = 8
-- Per-phase and whole-pass frame bounds: a wait that never advances fails through the host, no hang.
G.DISPLAY_PHASE_FRAMES = 900
G.DISPLAY_FRAMES = 8000
-- The overworld input tick window, as lua/tests/test_gen2_scripted_gate.lua's G.OVERWORLD_WINDOW.
G.DISPLAY_OVERWORLD_WINDOW = 2

local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

-- The played-route gate as a library: its validated context, bank-checked hooks, qualification
-- observer and button step are the ones fixture qualification already runs on.
function G.scripted_gate(root)
    local previous = SLINK_GEN2_GATE_LIBRARY
    SLINK_GEN2_GATE_LIBRARY = true
    local ok, SG = pcall(dofile, root .. "/" .. G.SCRIPTED_GATE)
    SLINK_GEN2_GATE_LIBRARY = previous
    assert(ok and type(SG) == "table", "cannot load " .. G.SCRIPTED_GATE .. ": " .. tostring(SG))
    return SG
end

-- CGB WRAM geometry (Pan Docs): $C000-$CFFF bank 0, $D000-$DFFF the selected bank 1-7. BizHawk's
-- flat WRAM domain holds bank n at n*$1000, so a named bank is read without trusting the live SVBK.
function G.wram_offset(bank, addr, n)
    if bank == 0 and addr >= 0xC000 and addr + n <= 0xD000 then return addr - 0xC000 end
    if integer(bank, 1, 7) and addr >= 0xD000 and addr + n <= 0xE000 then return bank * 0x1000 + addr - 0xD000 end
    error(string.format("WRAM range $%X+%d outside its bank %s window", addr, n, tostring(bank)), 0)
end

function G.species(ctx)
    local rel = "data/games/gen2_" .. ctx.env.title .. "/species_index.json"
    local f = assert(io.open(ctx.root .. "/" .. rel, "rb"), "cannot open " .. rel)
    local text = f:read("a")
    f:close()
    local wrapper = assert(ctx.json.decode(text))
    assert(type(wrapper.species) == "table", "species index missing its species table")
    return wrapper.species
end

-- The reads.lua IO binding: a profile symbol's logical System Bus address -> its named WRAM bank in
-- the flat WRAM domain; CartRAM is BizHawk's own flat SRAM domain and needs no translation.
function G.io(api, profile)
    local bank_of = {}
    for name, addr in pairs(profile.ram) do
        local bank = profile.ram_bank[name]
        if bank ~= nil then bank_of[addr] = (bank_of[addr] == nil or bank_of[addr] == bank) and bank or false end
    end
    local io_ = {cart_ram_linear = true, bank_of = bank_of}
    function io_.read_range(addr, n, domain)
        if domain == "CartRAM" then return api.read_range(addr, n, "CartRAM") end
        assert(domain == "System Bus" and type(bank_of[addr]) == "number", "read outside a profile symbol")
        return api.read_range(G.wram_offset(bank_of[addr], addr, n), n, "WRAM")
    end
    function io_.bank_valid(bank, addr, n)
        return bank_of[addr] == bank and (pcall(G.wram_offset, bank, addr, n))
    end
    function io_.domain_size(domain) return api.domain_size(domain) end
    return io_
end

local function hex(bytes)
    local out = {}
    for i = 1, #bytes do out[i] = string.format("%02x", bytes[i]) end
    return table.concat(out)
end

-- One raw capture, read from exactly the physical domain/offset it records: the party block
-- (wPartyCount..wPartyMonNicknamesEnd, the profile's own symbols) and the full CartRAM domain.
function G.dump(api, profile)
    local a, bank = profile.ram, profile.ram_bank.wPartyCount
    local length = a.wPartyMonNicknamesEnd - a.wPartyCount
    local offset = G.wram_offset(bank, a.wPartyCount, length)
    local party_bytes = api.read_range(offset, length, "WRAM")
    local cart_bytes = api.read_range(0, G.CART_RAM_BYTES, "CartRAM")
    assert(type(party_bytes) == "table" and #party_bytes == length, "party WRAM read failed")
    assert(type(cart_bytes) == "table" and #cart_bytes == G.CART_RAM_BYTES, "CartRAM read failed")
    return {
        frame = api.framecount(),
        party = {domain = "WRAM", offset = offset, bus_domain = "System Bus", bank = bank,
                 address = a.wPartyCount, length = length, hex = hex(party_bytes)},
        cartram = {domain = "CartRAM", address = 0, length = G.CART_RAM_BYTES, hex = hex(cart_bytes)},
    }
end

-- Independent second reader for R-3: the same profile-declared addresses, read directly through
-- io_ rather than through lua/gen2/reads.lua's accessors. See the R-3 SCOPE NOTE above.
function G.raw_fields(profile, io_)
    local a = profile.ram
    local badges = io_.read_range(a.wJohtoBadges, 2, "System Bus")
    local boxnum = io_.read_range(a.wCurBox, 1, "System Bus")
    local mode = io_.read_range(a.wBattleMode, 1, "System Bus")
    local battle = {mode = mode[1]}
    if mode[1] ~= 0 then
        local class = io_.read_range(a.wOtherTrainerClass, 1, "System Bus")
        local id = io_.read_range(a.wOtherTrainerID, 1, "System Bus")
        battle.trainer_class, battle.trainer_id = class[1], id[1]
    end
    return {badges = {johto = badges[1], kanto = badges[2]}, boxnum = boxnum[1], battle = battle}
end

-- GetGender/shiny (engine/pokemon/mon_stats.asm; engine/gfx/color.asm): independent of
-- lua/gen2/reads.lua and of server/adapters/gen2_gsc.py -- reimplemented from the DV word alone.
function G.gender_and_shiny(dv_word, gender_ratio)
    local attack = math.floor(dv_word / 4096)
    local defense = math.floor(dv_word / 256) % 16
    local speed = math.floor(dv_word / 16) % 16
    local special = dv_word % 16
    local shiny = math.floor(attack / 2) % 2 == 1 and defense == 10 and speed == 10 and special == 10
    local gender
    if gender_ratio == 255 then gender = "genderless"
    elseif gender_ratio == 254 then gender = "female"
    elseif gender_ratio == 0 then gender = "male"
    else gender = (attack * 16 + speed <= gender_ratio) and "female" or "male" end
    return gender, shiny
end

-- ================================================================================================
-- Display oracle (R-3 tilemap half, R-5g display half): the game's OWN rendered Trainer Card and
-- party status screens, read out of wTilemap after ordinary-button navigation. See the SCOPE notes.
-- ================================================================================================

-- wTilemap is SCREEN_WIDTH cells wide and ClearTilemap fills every cell with ' ' (home/text.asm:22-32):
-- cell (x, y) is wTilemap + y*width + x. Coordinates here are 0-based, as hlcoord's are.
function G.tile_offset(x, y, width) return y * width + x end

-- A byte's readable glyph name, or nil when the charmap only names it as a raw byte ("<$XX>") --
-- a nameless tile is not rendered text and is refused, never compared as if it were.
local function charmap_glyph(glyphs, byte)
    local name = glyphs[byte]
    if name == nil or name:match("^<%$%x%x>$") then return nil end
    return name
end

-- A run of tilemap bytes through a title's charmap (charmap.glyphs: byte -> glyph name). A byte the
-- charmap does not name is refused, never silently masked.
function G.decode_cells(glyphs, bytes)
    local out = {}
    for i = 1, #bytes do
        local name = charmap_glyph(glyphs, bytes[i])
        if name == nil then
            return nil, string.format("tilemap byte $%02X has no glyph in the title charmap", bytes[i])
        end
        out[#out + 1] = name
    end
    return table.concat(out)
end

-- A run of tilemap bytes decoded up to a string terminator (names end at the '@' tile).
function G.decode_cells_terminated(glyphs, terminator, bytes)
    local out = {}
    for i = 1, #bytes do
        if bytes[i] == terminator then break end
        local name = charmap_glyph(glyphs, bytes[i])
        if name == nil then
            return nil, string.format("name byte $%02X has no glyph in the title charmap", bytes[i])
        end
        out[#out + 1] = name
    end
    return table.concat(out)
end

-- The Trainer Card prints wPlayerID as a 5-digit zero-padded number (PRINTNUM_LEADINGZEROS | 2, 5):
-- C engine/menus/trainer_card.asm:238-240, G :236-238.
function G.id_text(ot_id) return string.format("%05d", ot_id) end

-- Glyph names keyed by the gender the DV derivation reports; PINK/GREEN/BLUE pages all draw it.
G.GENDER_GLYPH = {male = "♂", female = "♀", genderless = ""}
G.SHINY_GLYPH = "⁂"

-- Fold accents so the start menu's "POKéMON" (its "#MON@" string expands through PlacePOKe to the
-- characters POKé) and an item pack's "Poké Ball" compare alike.
function G.normalize_text(text) return (text:gsub("é", "E"):gsub("É", "E")):upper() end

-- Index of the one menu item whose folded text is `wanted`, or nil (no match, or an ambiguous pair).
function G.find_menu_item(items, wanted)
    local target
    for i, item in ipairs(items) do
        if type(item) == "string" and G.normalize_text(item) == wanted then
            if target then return nil end
            target = i
        end
    end
    return target
end

-- The stats head's expected (18,0) gender and (19,0) shiny bytes in a title's charmap. A genderless
-- mon writes no gender char (C stats_screen.asm:474-486) and a non-shiny mon writes no shiny icon
-- (:522-526): both leave ClearTilemap's blank cell untouched, so a stale byte there is never the glyph.
function G.stats_head_expected(encoding, gender, shiny)
    local blank = assert(encoding[" "], "charmap lacks the blank tile")
    local gender_byte = blank
    if gender ~= "genderless" then
        local glyph = assert(G.GENDER_GLYPH[gender], "unknown gender " .. tostring(gender))
        gender_byte = assert(encoding[glyph], "charmap lacks " .. glyph)
    end
    local shiny_byte = blank
    if shiny then shiny_byte = assert(encoding[G.SHINY_GLYPH], "charmap lacks " .. G.SHINY_GLYPH) end
    return {blank_byte = blank, gender_byte = gender_byte, shiny_byte = shiny_byte}
end

-- The stats screen's GREEN page prints .Item ("ITEM") at (0,8) and the name after it: at (8,8) in
-- Crystal (engine/pokemon/stats_screen.asm:726-733) but at (6,8) in Gold/Silver (:567-577). With no
-- item .GetItemName returns .ThreeDashes "---" (C :755-757, G :610-614).
G.ITEM_COLUMN = {crystal = 8, gold = 6, silver = 6}
G.NO_ITEM_TEXT = "---"
function G.item_column(title)
    local column = G.ITEM_COLUMN[title]
    assert(column, "no item column for title " .. tostring(title))
    return column
end

-- The expected item-line text: the game's own no-item text, or the title pack's name for `held`
-- (folded on both sides before comparison). nil when the pack has no such id.
function G.item_expected(pack, held_item)
    if held_item == 0 then return G.NO_ITEM_TEXT end
    local name = pack[tostring(held_item)]
    if type(name) ~= "string" then return nil end
    return G.normalize_text(name)
end

function G.item_names(ctx)
    local rel = "data/games/gen2_" .. ctx.env.title .. "/item_names.json"
    local f = assert(io.open(ctx.root .. "/" .. rel, "rb"), "cannot open " .. rel)
    local text = f:read("a")
    f:close()
    local wrapper = assert(ctx.json.decode(text), rel .. " is malformed")
    assert(type(wrapper) == "table", rel .. " is not an id table")
    return wrapper
end

-- The two joypad-state code sites the display pass waits on are not among the route facts'
-- ui_origins; they are resolved from the SAME rgbds symbol artifact the facts' sites come from
-- (data/gen2/<artifact>.sym, the plain `BB:AAAA Name` rows tools/rgbds_symbols.py parses), and the
-- expected ROM byte is read from the running ROM at the site's flat offset, exactly as the scripted
-- gate's hooks do. The shared gate file is not touched.
G.SYM_ARTIFACT = {crystal = "pokecrystal", gold = "pokegold", silver = "pokesilver"}
-- The stats screen's per-frame joypad wait, entered after the page is drawn: Crystal MonStatsJoypad
-- (C engine/pokemon/stats_screen.asm:117,120); Gold/Silver have no such label, their loop is
-- StatsScreen_LoadPage.joypad_loop after `jp hl` draws the page (G stats_screen.asm:58-92), with the
-- same RIGHT/A page advance and A-on-BLUE_PAGE exit (review gen2-O6).
G.STATS_JOYPAD = {crystal = "MonStatsJoypad", gold = "StatsScreen_LoadPage.joypad_loop",
                  silver = "StatsScreen_LoadPage.joypad_loop"}
function G.sym_site(ctx, label)
    local artifact = assert(G.SYM_ARTIFACT[ctx.env.title], "unsupported title " .. tostring(ctx.env.title))
    local path = ctx.root .. "/data/gen2/" .. artifact .. ".sym"
    local f = assert(io.open(path, "rb"), "cannot open " .. path)
    local text = f:read("a")
    f:close()
    local bank, address
    for line in text:gmatch("[^\r\n]+") do
        local b, a, name = line:match("^%s*([0-9a-fA-F]+):([0-9a-fA-F]+)%s+(%S+)")
        if name == label then
            assert(bank == nil, "duplicate symbol " .. label)
            bank, address = tonumber(b, 16), tonumber(a, 16)
        end
    end
    assert(bank ~= nil, "symbol not found in " .. artifact .. ".sym: " .. label)
    local flat = (bank == 0) and address or (bank * 0x4000 + address - 0x4000)
    local want = ctx.api.read_range(flat, 1, "ROM")
    assert(type(want) == "table" and #want == 1, "ROM read failed for " .. label)
    return {id = label, bank = bank, addr = address, flat = flat, hex = string.format("%02x", want[1])}
end

-- The display pass's own bank/byte-checked hooks (the shared G.hooks knows only the facts'
-- ui_origins): the Trainer Card page-1 joypad state, the stats joypad state and the overworld tick.
function G.display_hooks(ctx)
    local api, obs = ctx.api, ctx.obs
    local binding = ctx.Binding.new({read_u8 = api.read_u8, read_range = api.read_range, register = api.register,
        framecount = api.framecount, on_bus_exec = api.on_bus_exec, unregister = api.unregister},
        {bus_domain = "System Bus", rom_domain = "ROM", bank_domain = "System Bus", pc_register = "PC",
         sp_register = "SP", bank_address = ctx.profile.hram.hROMBank})
    local state = {errors = {}, handles = {}, card = {hits = 0}, stats = {hits = 0}, tick = nil}
    local function watch(id, site, on_hit)
        local valid = binding:validate({id = id, bank = site.bank, address = site.addr,
            expected_hex = site.hex, capture_offset = 0, rom_offset = site.flat})
        local handle = binding:register(valid, function()
            local ok, hit = pcall(binding.context, binding, valid)
            if not ok then state.errors[#state.errors + 1] = tostring(hit) return end
            if hit then on_hit(hit.frame) end
        end, "SLink-gen2-display-" .. id)
        assert(binding:valid_handle(handle), id .. ": hook registration failed")
        state.handles[#state.handles + 1] = handle
    end
    watch("trainer_card", G.sym_site(ctx, "TrainerCard_Page1_Joypad"), function(frame)
        state.card.hits, state.card.frame = state.card.hits + 1, frame
    end)
    watch("mon_stats", G.sym_site(ctx, G.STATS_JOYPAD[ctx.env.title]), function(frame)
        state.stats.hits, state.stats.frame = state.stats.hits + 1, frame
    end)
    watch("overworld_tick", obs.overworld_tick, function(frame) state.tick = frame end)
    function state.release()
        for _, handle in ipairs(state.handles) do pcall(binding.unregister, binding, handle) end
        state.handles = {}
    end
    return state
end

-- One bounded navigation stage over the shared host: `machine` returns (buttons, phase) and the host
-- returns once a terminal phase has settled. A wait that never advances trips the phase bound.
local function display_stage(ctx, SG, name, terminal, machine)
    local idle = {}
    for _, button in ipairs(SG.BUTTONS) do idle[button] = false end
    local host = ctx.Host.new({step = SG.button_step(ctx), frame = ctx.api.framecount, idle = idle})
    return pcall(host.run, {name = name, terminal = terminal, max_frames = G.DISPLAY_FRAMES,
        max_phase_frames = G.DISPLAY_PHASE_FRAMES, settle_frames = G.DISPLAY_SETTLE, terminal_idle = true}, machine)
end

-- A press held for G.DISPLAY_HOLD frames, then G.DISPLAY_GAP idle frames before the next decision.
local function navigator()
    local nav = {hold = 0, gap = 0, button = nil}
    function nav.press(button)
        nav.button, nav.hold, nav.gap = button, G.DISPLAY_HOLD - 1, G.DISPLAY_GAP
        return {[button] = true}
    end
    function nav.step()
        if nav.hold > 0 then nav.hold = nav.hold - 1 return {[nav.button] = true} end
        if nav.gap > 0 then nav.gap = nav.gap - 1 return {} end
        return nil
    end
    return nav
end

-- The whole display pass: Trainer Card -> back to the overworld -> party status head -> GREEN page.
-- Every coordinate, byte and expectation is logged so tests/live/test_gen2_new_gates.py can derive
-- the same values independently. Returns nothing; each observation is checked through `check`.
function G.display_pass(ctx, SG, log, check, reads, species)
    local api, obs, json = ctx.api, ctx.obs, ctx.json
    local encoding, glyphs = ctx.charmap.encoding, ctx.charmap.glyphs
    local blank = assert(encoding[" "], "charmap lacks the blank tile")
    local function cells(x, y, n) return ctx.sym("wTilemap", G.tile_offset(x, y, obs.screen.width), n) end
    local function hex(bytes)
        local out = {}
        for i = 1, #bytes do out[i] = string.format("%02x", bytes[i]) end
        return table.concat(out)
    end
    local function screen()
        return SG.parse_menu(SG.screen(ctx), obs.screen.width, obs.screen.height)
    end
    local hooks = G.display_hooks(ctx)
    local failed = 0
    local function fail(what, detail)
        failed = failed + 1
        log(string.format("  [FAIL] %s  -- %s", what, tostring(detail)))
        local ok, rows = pcall(SG.screen, ctx)
        if ok then
            for y, row in ipairs(rows) do log(string.format("  screen %02d |%s|", y, table.concat(row))) end
        end
    end
    local function run(name, terminal, machine)
        local ok, result = display_stage(ctx, SG, name, terminal, machine)
        if not ok then fail(name, result) end
        return ok
    end

    local id_raw = ctx.sym("wPlayerID", 0, 2)
    local player_id = id_raw[1] * 256 + id_raw[2]
    local name_raw = ctx.sym("wPlayerName", 0, ctx.profile.constants.NAME_LENGTH)
    local player_name, name_why = G.decode_cells_terminated(glyphs, encoding["@"], name_raw)
    local party = reads.read_party()
    if not check("display pass has wPlayerName and a party mon to read", player_name ~= nil and party ~= nil
                 and party.count >= 1, name_why or (party == nil and "no party")) then
        hooks.release()
        return
    end
    local lead = party.mons[1]

    -- 1. Trainer Card page 1 via START -> the Status entry (the entry labelled with the player name).
    local nav, phase = navigator(), "overworld"
    local function overworld_ready()
        local battle = reads.read_battle()
        return hooks.tick ~= nil and api.framecount() - hooks.tick <= G.DISPLAY_OVERWORLD_WINDOW
            and battle ~= nil and battle.mode == 0
    end
    if run("display-card", "card", function()
        local buttons = nav.step()
        if buttons then return buttons, phase end
        if phase == "overworld" then
            if not overworld_ready() then return {}, phase end
            phase = "start_menu"
            return nav.press("Start"), phase
        end
        if phase == "start_menu" then
            local m = screen()
            if not m then return {}, phase end
            local target = G.find_menu_item(m.items, G.normalize_text(player_name))
            if not target then return {}, phase end
            if target == m.cursor then phase = "card_wait" return nav.press("A"), phase end
            return nav.press(target > m.cursor and "Down" or "Up"), phase
        end
        if phase == "card_wait" then
            if hooks.card.hits > 0 then phase = "card" return {}, phase end
            return {}, phase
        end
        return {}, phase   -- terminal "card": the host settles the tilemap
    end) then
        local id_cells = cells(5, 4, 5)
        local id_digits, id_why = G.decode_cells(glyphs, id_cells)
        local expected_id = G.id_text(player_id)
        local name_cells = cells(7, 2, #player_name)
        local name_text, card_why = G.decode_cells(glyphs, name_cells)
        log("GAME_TRAINER_CARD " .. json.encode({frame = api.framecount(),
            id_digits_hex = hex(id_cells), id_text = id_digits, expected_id_text = expected_id,
            player_id_hex = hex(id_raw), name_row = 2, name_col = 7, name_length = #player_name,
            name_bytes_hex = hex(name_cells), name_text = name_text, expected_name = player_name,
            player_name_hex = hex(name_raw), blank_byte = blank}))
        check("Trainer Card (5,4) five digits render wPlayerID",
              id_digits ~= nil and id_digits == expected_id, id_digits or id_why)
        check("Trainer Card (7,2) renders wPlayerName",
              name_text ~= nil and name_text == player_name, name_text or card_why)
    end

    -- 2. B out of the card and the start menu, back to the overworld.
    nav, phase = navigator(), "exit"
    run("display-exit", "overworld", function()
        local buttons = nav.step()
        if buttons then return buttons, phase end
        if overworld_ready() then phase = "overworld" return {}, phase end
        return nav.press("B"), phase
    end)

    -- 3. Stats screen head via START -> #MON -> the lead mon -> the mon submenu -> STATS.
    nav, phase = navigator(), "overworld"
    if run("display-stats", "stats", function()
        local buttons = nav.step()
        if buttons then return buttons, phase end
        if phase == "overworld" then
            if not overworld_ready() then return {}, phase end
            phase = "start_menu"
            return nav.press("Start"), phase
        end
        if phase == "start_menu" then
            local m = screen()
            if not m then return {}, phase end
            -- ".PartyString: #MON@" (C/G engine/menus/start_menu.asm:190): the `#` control code expands
            -- through PlacePOKe to the characters "POKé" (C home/text.asm:224,313,404; G :211,371), so
            -- the tilemap reads POKéMON, never a `#` glyph (live inspect run 2026-09-23 stalled here).
            local target = G.find_menu_item(m.items, G.normalize_text("POKéMON"))
            if not target then return {}, phase end
            if target == m.cursor then phase = "party" return nav.press("A"), phase end
            return nav.press(target > m.cursor and "Down" or "Up"), phase
        end
        if phase == "party" then
            if hooks.stats.hits > 0 then phase = "stats" return {}, phase end
            local m = screen()
            if m and G.find_menu_item(m.items, "STATS") then phase = "submenu" return {}, phase end
            return nav.press("A"), phase   -- select the lead mon; a stray re-press only re-selects #MON
        end
        if phase == "submenu" then
            if hooks.stats.hits > 0 then phase = "stats" return {}, phase end
            local m = screen()
            if not m then return {}, phase end
            local target = G.find_menu_item(m.items, "STATS")
            if not target then return {}, phase end
            if target == m.cursor then phase = "stats_wait" return nav.press("A"), phase end
            return nav.press(target > m.cursor and "Down" or "Up"), phase
        end
        if phase == "stats_wait" then
            if hooks.stats.hits > 0 then phase = "stats" return {}, phase end
            return {}, phase
        end
        return {}, phase   -- terminal "stats"
    end) then
        local gender_byte = cells(18, 0, 1)[1]
        local shiny_byte = cells(19, 0, 1)[1]
        local row = species[tostring(lead.species_id)]
        local gender, shiny = G.gender_and_shiny(lead.dv_word, row.gender_ratio)
        local expected = G.stats_head_expected(encoding, gender, shiny)
        log("GAME_STATS_HEAD " .. json.encode({frame = api.framecount(), gender_byte = gender_byte,
            gender_expected = expected.gender_byte, gender_glyph = G.GENDER_GLYPH[gender],
            shiny_byte = shiny_byte, shiny_expected = expected.shiny_byte,
            shiny_glyph = shiny and G.SHINY_GLYPH or "", blank_byte = expected.blank_byte,
            species_id = lead.species_id, dv_word = lead.dv_word, gender = gender, shiny = shiny}))
        check("stats screen (18,0) gender glyph matches the DVs",
              gender_byte == expected.gender_byte, string.format("$%02X != $%02X", gender_byte, expected.gender_byte))
        check("stats screen (19,0) shiny marker matches the DVs",
              shiny_byte == expected.shiny_byte, string.format("$%02X != $%02X", shiny_byte, expected.shiny_byte))

        -- 4. RIGHT to the GREEN page, then the item line.
        nav, phase = navigator(), "right"
        local function item_line()
            local label = G.decode_cells(glyphs, cells(0, 8, 4))
            return label == "ITEM"
        end
        run("display-green", "green", function()
            local buttons = nav.step()
            if buttons then return buttons, phase end
            if item_line() then phase = "green" return {}, phase end
            return nav.press("Right"), phase   -- Cycles Pink->Green->Blue->Pink; stop at the ITEM label.
        end)
        local item_col = G.item_column(ctx.env.title)
        local expected_item = G.item_expected(G.item_names(ctx), lead.held_item)
        local label_text = G.decode_cells(glyphs, cells(0, 8, 4))
        local length = expected_item and #expected_item or 3
        local item_cells = cells(item_col, 8, length)
        local item_text = G.decode_cells(glyphs, item_cells)
        log("GAME_STATS_ITEM " .. json.encode({frame = api.framecount(), item_row = 8, item_col = item_col,
            label_text = label_text, held_item = lead.held_item, item_bytes_hex = hex(item_cells),
            item_text = item_text, item_expected = expected_item}))
        check("stats GREEN page (0,8) carries the ITEM label", label_text == "ITEM", label_text)
        check("stats GREEN page item line matches the expected item text",
              item_text ~= nil and expected_item ~= nil
              and G.normalize_text(item_text) == G.normalize_text(expected_item) and #item_text == length,
              string.format("%s != %s", tostring(item_text), tostring(expected_item)))
        -- 5. B out of the stats screen, the submenu and the start menu.
        nav, phase = navigator(), "exit"
        run("display-stats-exit", "overworld", function()
            local buttons = nav.step()
            if buttons then return buttons, phase end
            if overworld_ready() then phase = "overworld" return {}, phase end
            return nav.press("B"), phase
        end)
    end
    hooks.release()
end

-- The post-CONTINUE overworld arrival: gen2_qualify.lua's "boot" stage (terminal "loaded"), driven
-- through the scripted gate's hooks and observer. Returns ok, detail, the live hook state (the
-- caller releases it after the capture window).
function G.arrive(ctx, SG)
    local hooked, state = pcall(SG.hooks, ctx)
    if not hooked then return false, "code-site hooks refused: " .. tostring(state), {release = function() end} end
    local idle = {}
    for _, name in ipairs(SG.BUTTONS) do idle[name] = false end
    local host = ctx.Host.new({step = SG.button_step(ctx), frame = ctx.api.framecount, idle = idle})
    local case, q = ctx.case, ctx.qualify
    local ok, result = pcall(ctx.Qualify.run, host, SG.qualify_observer(ctx), ctx.facts, q.facts,
        {name = case.name, title = case.title, attempt_id = case.attempt_id, stage = "boot",
         stage_fingerprint = q.stage_fingerprint, max_frames = case.max_frames,
         max_phase_frames = case.max_phase_frames, settle_frames = case.settle_frames})
    if not ok then return false, tostring(result), state end
    local hits = state.hits
    local native = hits.continue >= 1 and hits.continue_loaded >= 1 and hits.rtc_ok >= 1
        and hits.finish_continue >= 1 and hits.restart_clock == 0 and hits.erase_save == 0
    if not native then return false, "overworld reached without the native CONTINUE/RTC path", state end
    return true, "loaded @" .. tostring(result.end_frame), state
end

-- The capture twice across an idle gap: byte-identical (a mid-transition or loader-writing screen
-- would not hold still), the frame counter advanced, and OWPlayerInput ran inside the gap with no
-- newer UI context (still in the overworld when the certified capture is taken).
function G.stable_dump(api, profile, state)
    local first = G.dump(api, profile)
    for _ = 1, G.STABILITY_IDLE_FRAMES do
        api.set_buttons({})
        api.advance()
    end
    local second = G.dump(api, profile)
    local stable = first.party.hex == second.party.hex and first.cartram.hex == second.cartram.hex
    local tick = state.tick
    local overworld = #state.errors == 0 and tick ~= nil and tick.frame > first.frame
        and (state.ui == nil or state.ui.seq < tick.seq)
    return stable and second.frame > first.frame, overworld, second
end

function G.main(api, getenv, SG)
    local root = getenv("SLINK_ROOT") or SLINK_ROOT or "."
    local lines, failures = {}, 0
    local function log(s)
        lines[#lines + 1] = s
        local f = io.open(root .. "/" .. G.RESULT, "w")
        if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    end
    local function check(what, ok, detail)
        if not ok then failures = failures + 1 end
        log(string.format("  [%s] %s%s", ok and "ok" or "FAIL", what, detail and ("  -- " .. tostring(detail)) or ""))
        return ok
    end
    local function finish(extra)
        log(string.format("RESULT: %s %s (%d checks failed)", failures == 0 and "PASS" or "FAIL", extra or "inspect", failures))
        return failures == 0
    end

    local ok, ctx = pcall(function()
        SG = SG or G.scripted_gate(root)
        local c = SG.context(api, getenv)
        assert(c.qualify ~= nil and c.qualify.stage == "boot", "SLINK_GEN2_QUALIFY stage \"boot\" required")
        return c
    end)
    if not check("environment, facts, profile and running ROM/CGB bound (scripted-gate context)", ok, not ok and ctx or nil) then
        return finish("bad environment")
    end
    local species
    ok, species = pcall(G.species, ctx)
    if not check("selected species index loaded", ok, species) then return finish("bad pack") end
    local profile, json = ctx.profile, ctx.json

    local io_ = G.io(api, profile)
    local reads, why = dofile(ctx.root .. "/lua/gen2/reads.lua").new(profile, io_)
    if not check("lua/gen2/reads.lua accepts the selected profile", reads ~= nil, why) then return finish("reads.new refused") end

    local arrived, detail, state = G.arrive(ctx, SG)
    if not check("post-CONTINUE overworld arrival (gen2_qualify boot: CONTINUE/RTC/FinishContinue sites, then OWPlayerInput)",
                 arrived, detail) then
        state.release()
        log("CHECKPOINT not reached")
        return finish("no qualified overworld arrival")
    end
    log("[gen2_inspect_gate] arrived " .. detail)

    local captured, stable, overworld, dump = pcall(G.stable_dump, api, profile, state)
    state.release()
    if not check("raw capture read from its recorded domains", captured, not captured and stable or nil) then
        log("CHECKPOINT not reached")
        return finish("capture failed")
    end
    local battle, battle_why = reads.read_battle()
    check("capture is byte-stable across an idle frame gap", stable)
    check("OWPlayerInput ran inside the gap with no newer UI context", overworld)
    check("no battle at the checkpoint", battle ~= nil and battle.mode == 0, battle and battle.mode or battle_why)
    local reached = stable and overworld and battle ~= nil and battle.mode == 0
    log("CHECKPOINT " .. (reached and "reached" or "not reached"))
    log("DUMP " .. json.encode(dump))

    local party = reads.read_party()
    check("party has 1..6 mons", party ~= nil and party.count >= 1 and party.count <= 6, party and party.count)
    log("PARTY_LUA " .. json.encode(party))

    local gender_shiny = {}
    if party then
        for _, mon in ipairs(party.mons) do
            local row = species[tostring(mon.species_id)]
            if row and type(row.gender_ratio) == "number" then
                local gender, shiny = G.gender_and_shiny(mon.dv_word, row.gender_ratio)
                gender_shiny[#gender_shiny + 1] = {slot = mon.slot, species_id = mon.species_id,
                    dv_word = mon.dv_word, gender = gender, shiny = shiny}
            end
        end
    end
    log("GENDER_SHINY " .. json.encode(gender_shiny))

    local active_box, active_why = reads.read_active_box()
    check("active box decodes", active_box ~= nil, active_why)
    log("ACTIVE_BOX_LUA " .. json.encode(active_box))

    for index = 0, 13 do
        local box, box_why = reads.read_storage_box(index)
        check("storage box " .. index .. " decodes", box ~= nil, box_why)
        log("BOX_LUA_" .. index .. " " .. json.encode(box))
    end

    local badges, badges_why = reads.read_badges()
    check("badges decode", badges ~= nil, badges_why)
    log("BADGES_LUA " .. json.encode(badges))

    local player, player_why = reads.read_player()
    check("player identity decodes", player ~= nil, player_why)
    log("PLAYER_LUA " .. json.encode(player))

    check("battle context decodes", battle ~= nil, battle_why)
    log("BATTLE_LUA " .. json.encode(battle))

    local raw = G.raw_fields(profile, io_)
    log("RAW_BADGES " .. json.encode(raw.badges))
    log("RAW_BOXNUM " .. json.encode(raw.boxnum))
    log("RAW_BATTLE " .. json.encode(raw.battle))
    check("independent badge re-read agrees with reads.lua", badges ~= nil
          and badges.johto == raw.badges.johto and badges.kanto == raw.badges.kanto, "differential")
    check("independent current-box re-read agrees with reads.lua",
          reads.read_current_box_num() == raw.boxnum, "differential")
    check("independent battle re-read agrees with reads.lua",
          battle ~= nil and battle.mode == raw.battle.mode, "differential")

    local decode_frame = api.framecount()
    check("every decode ran at the capture frame", decode_frame == dump.frame, decode_frame)
    log("DECODE_FRAME " .. json.encode(decode_frame))
    local displayed, display_why = pcall(G.display_pass, ctx, SG, log, check, reads, species)
    if not displayed then
        check("display oracle ran (normal-button navigation and wTilemap reads)", false, display_why)
    end
    return finish()
end

if SLINK_GEN2_GATE_LIBRARY then return G end

-- Top level: the runner's speed (run_gb_gate: SpeedPercent=100) stands; no speed override here.
local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(ROOT, "SLINK_ROOT unset -- launch via tools/run_gb_gate.py")
local SG = G.scripted_gate(ROOT)
local api = SG.bizhawk()
G.main(api, os.getenv, SG)
api.exit()
error("slink-gate-finished", 0)   -- client.exit() is asynchronous; stop here for real
