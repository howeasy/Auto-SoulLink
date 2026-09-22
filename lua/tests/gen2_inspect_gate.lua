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
  profile-declared WRAM addresses (bypassing lua/gen2/reads.lua entirely), not an OCR of the
  game's own rendered Trainer Card / party status / PC box screens. R-3 against the on-screen text
  (GEN2_BINDING_PLAN P3b.3a's "GAME" oracle) needs UI navigation the eight town/battle fixtures
  cannot reach, and stays OPEN.
  R-5g SCOPE NOTE: GENDER_SHINY is a DV-formula cross-check (this file vs an independent Python
  reimplementation). It is NOT the game's own status-screen gender symbol or shiny palette, which is
  what R-5g requires; R-5g stays OPEN.

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
--]]
local G = {}
G.RESULT = "patch/build/gen2_inspect_gate_result.txt"
G.CART_RAM_BYTES = 0x8000
G.SCRIPTED_GATE = "lua/tests/test_gen2_scripted_gate.lua"
-- ponytail: idle-stability window, not a measured native timing; raise if a live run needs longer.
G.STABILITY_IDLE_FRAMES = 60

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
