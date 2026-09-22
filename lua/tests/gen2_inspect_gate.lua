--[[
  lua/tests/gen2_inspect_gate.lua -- P3b.3a PHYSICAL: lua/gen2/reads.lua qualified on the RUNNING
  cartridge (docs/gen2/GEN2_BINDING_PLAN.md P3b.3a; docs/gen2/gen2_requirements.md R-1, R-3, R-5g).

  Boots WARM from a qualified fixture (tests/fixtures/gen2/<title>_<town|battle>[_ot2].SaveRAM,
  staged by tools/run_gb_gate.py's _gen2_plan through tools/run_gb_gate.run_gate), settles to a
  live overworld checkpoint, then takes ONE same-frame raw dump: the party WRAM block and the
  full CartRAM domain (the active box and all 14 storage boxes live inside it). The dump's frame,
  domain and byte ranges are recorded and printed so tests/live/test_gen2_new_gates.py can decode
  the SAME bytes independently with server/adapters/gen2_codec.py (PYDEC) -- fixture-only
  agreement never closes R-1; only a same-frame Lua/PYDEC disagreement test does.

  lua/gen2/reads.lua is the ONLY production decoder used here; this file supplies nothing but the
  emulator IO binding (System Bus -> WRAM through the profile's bank map; CartRAM passthrough) and
  orchestration. No emulator global (memory/emu/joypad/client/gameinfo) is called anywhere except
  inside G.bizhawk(), so every other function here takes an injected `api`/`getenv` and is
  lupa-testable with a fake one -- see tests/unit/test_gen2_inspect_gate.py, which sets the global
  SLINK_GEN2_GATE_LIBRARY (the same flag lua/tests/test_gen2_scripted_gate.lua uses) before
  dofile()-ing this script, so the trailer below returns G instead of auto-running.

  R-3 SCOPE NOTE: the RAW_* lines below are a SECOND, independent Lua reader of the same
  profile-declared WRAM addresses (bypassing lua/gen2/reads.lua entirely), not an OCR of the
  game's own rendered Trainer Card / party status / PC box screens. Closing R-3 against the
  literal on-screen text (docs/gen2/GEN2_BINDING_PLAN.md P3b.3a's "GAME" oracle) needs UI
  navigation this card's eight town/battle fixtures cannot reach (no trainer, PC or badge is in
  range of the scripted route) and is left as a live-only follow-up for the coordinator.

  Environment (all required; run_gb_gate._gen2_plan sets these for a WARM Gen 2 launch):
    SLINK_ROOT, SLINK_GEN2_TITLE, SLINK_GEN2_ROM_SHA1, SLINK_GEN2_CORE_MODE (must be CGB),
    SLINK_GEN2_COLD (must be "0" -- this gate only ever boots warm, from a fixture),
    SLINK_GEN2_SAVERAM_DIR, SLINK_GEN2_SAVERAM_NAME.

  Result file: patch/build/gen2_inspect_gate_result.txt (RESULT: PASS|FAIL, last line).
  Printed lines (each a single JSON value after its tag, lua/json_codec.lua encoding):
    DUMP          {frame, party:{domain,bank,address,length,hex}, cartram:{domain,address,length,hex}}
    PARTY_LUA     lua/gen2/reads.lua read_party() result
    ACTIVE_BOX_LUA / BOX_LUA_<0..13>   read_active_box() / read_storage_box(i) results
    BADGES_LUA / PLAYER_LUA / BATTLE_LUA   the matching reads.lua accessor result
    RAW_BADGES / RAW_BATTLE / RAW_BOXNUM   the independent hand-rolled second reader (see above)
    GENDER_SHINY  per party slot, {gender, shiny} derived from dv_word alone (engine/gfx/color.asm
                  + engine/pokemon/mon_stats.asm GetGender), independent of lua/gen2/reads.lua
    CHECKPOINT    "reached" once the party+box dump is stable across an idle frame gap
--]]
local G = {}
G.RESULT = "patch/build/gen2_inspect_gate_result.txt"
G.CART_RAM_BYTES = 0x8000
-- ponytail: bounded press-through-title budget and idle-stability window, not a measured
-- native timing; raise if a live run shows the title/CONTINUE sequence needs longer.
G.BOOT_SETTLE_FRAMES = 1800
G.STABILITY_IDLE_FRAMES = 60

local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

-- BizHawk globals, wrapped once. API objects are userdata in EmuHawk: call, never type-check
-- (docs reference_bizhawk_api_userdata.md).
function G.bizhawk()
    return {
        read_u8 = function(a, d) return memory.read_u8(a, d) end,
        read_range = function(a, n, d) return memory.read_bytes_as_array(a, n, d) end,
        domain_size = function(d) return memory.getmemorydomainsize(d) end,
        advance = function() emu.frameadvance() end,
        framecount = function() return emu.framecount() end,
        set_buttons = function(b) joypad.set(b) end,
        romhash = function() return gameinfo.getromhash() end,
        systemid = function() return emu.getsystemid() end,
        speed = function(p) client.speedmode(p) end,
        exit = function() client.exit() end,
    }
end

-- Runner-protected bindings only (run_gb_gate._gen2_plan); no route/case JSON here, unlike the
-- scripted-play gate -- this gate drives no scenario, it only reads a fixture that already exists.
function G.inputs(getenv)
    local function need(name)
        local value = getenv(name)
        assert(type(value) == "string" and value ~= "", "missing environment " .. name)
        return value
    end
    local env = {root = need("SLINK_ROOT"), title = need("SLINK_GEN2_TITLE"),
                 rom_sha1 = need("SLINK_GEN2_ROM_SHA1"):lower()}
    assert(({crystal = true, gold = true, silver = true})[env.title], "unsupported SLINK_GEN2_TITLE")
    assert(#env.rom_sha1 == 40 and env.rom_sha1:match("^%x+$"), "malformed SLINK_GEN2_ROM_SHA1")
    assert(need("SLINK_GEN2_CORE_MODE") == "CGB", "the inspect gate requires the CGB core")
    assert(need("SLINK_GEN2_COLD") == "0", "the inspect gate boots WARM from a qualified fixture")
    return env
end

-- CGB WRAM geometry (Pan Docs): $C000-$CFFF bank 0, $D000-$DFFF the selected bank 1-7. BizHawk's
-- flat WRAM domain holds bank n at n*$1000, so a named bank is read without trusting the live
-- SVBK -- the same formula test_gen2_scripted_gate.lua uses (no shared lua/gb_sram_addr.lua
-- exists yet; that extraction is P3b.5's, docs/gen2/GEN2_BINDING_PLAN.md P3b.5 row).
function G.wram_offset(bank, addr, n)
    if bank == 0 and addr >= 0xC000 and addr + n <= 0xD000 then return addr - 0xC000 end
    if integer(bank, 1, 7) and addr >= 0xD000 and addr + n <= 0xE000 then return bank * 0x1000 + addr - 0xD000 end
    error(string.format("WRAM range $%X+%d outside its bank %s window", addr, n, tostring(bank)), 0)
end

function G.load_pack(env, load)
    local json = load("lua/json_codec.lua")
    local function read_json(rel)
        local f = assert(io.open(env.root .. "/" .. rel, "rb"), "cannot open " .. rel)
        local text = f:read("a")
        f:close()
        return assert(json.decode(text))
    end
    local wrapper = read_json("data/games/gen2_" .. env.title .. "/profile.json")
    local profile = wrapper.titles and wrapper.titles[env.title]
    assert(wrapper.schema == "gen2-profile-v1" and type(profile) == "table" and profile.title == env.title
           and profile.rom_sha1 == env.rom_sha1, "profile belongs to another ROM or title")
    local species_wrapper = read_json("data/games/gen2_" .. env.title .. "/species_index.json")
    assert(type(species_wrapper.species) == "table", "species index missing its species table")
    return {profile = profile, species = species_wrapper.species, json = json}
end

-- The reads.lua IO binding: System Bus -> WRAM through the bank map every profile symbol
-- carries; CartRAM is BizHawk's own flat SRAM domain and needs no translation.
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

-- One same-frame raw capture: the party WRAM block (exact reads.lua geometry, recomputed
-- against the profile's own literal wPartyMonNicknamesEnd symbol) and the full CartRAM domain,
-- with frame/domain/address/length recorded for the PYDEC side.
function G.dump(api, profile, io_)
    local a, bank = profile.ram, profile.ram_bank.wPartyCount
    local length = a.wPartyMonNicknamesEnd - a.wPartyCount
    local party_bytes = io_.read_range(a.wPartyCount, length, "System Bus")
    local cart_bytes = io_.read_range(0, G.CART_RAM_BYTES, "CartRAM")
    return {
        frame = api.framecount(),
        party = {domain = "System Bus", bank = bank, address = a.wPartyCount, length = length, hex = hex(party_bytes)},
        cartram = {domain = "CartRAM", address = 0, length = G.CART_RAM_BYTES, hex = hex(cart_bytes)},
    }
end

-- Independent second reader for R-3: the same profile-declared addresses, read directly through
-- io_ rather than through lua/gen2/reads.lua's accessors. See the R-3 SCOPE NOTE at the top of
-- this file for what this does and does not close.
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

-- Bounded press-through-title loop: CONTINUE from a warm fixture still shows the title screen
-- first (gatelib.lua's Lib.prove_booted measured the same on Gen 1/Crystal). "A" advances the
-- attract loop/title/CONTINUE prompt; a successful reads.read_party() is the settle condition,
-- mirroring lua/tests/test_gen1_inspect_gate.lua's boot-then-decode shape.
function G.settle(api, reads)
    for frame = 1, G.BOOT_SETTLE_FRAMES do
        local party = reads.read_party()
        if party then return true, frame end
        if frame % 6 == 0 then api.set_buttons({A = true}) else api.set_buttons({}) end
        api.advance()
    end
    return false, G.BOOT_SETTLE_FRAMES
end

-- CHECKPOINT/liveness proxy: the SAME dump taken twice across an idle gap must be byte-identical
-- (a mid-transition or loader-writing screen would not hold still) and the frame counter must
-- have actually advanced. This is a liveness proof, not lua/gen2_write_safety.lua's eventual
-- armed-checkpoint predicate (P3b.5, not yet built); it only proves the game reached a STABLE,
-- running overworld/battle state before the dump this gate certifies is taken.
function G.stable_dump(api, profile, io_)
    local before_frame = api.framecount()
    local first = G.dump(api, profile, io_)
    for _ = 1, G.STABILITY_IDLE_FRAMES do
        api.set_buttons({})
        api.advance()
    end
    local second = G.dump(api, profile, io_)
    local stable = first.party.hex == second.party.hex and first.cartram.hex == second.cartram.hex
    local advanced = second.frame > before_frame
    return stable and advanced, second, second.frame - before_frame
end

function G.main(api, getenv)
    local lines, failures = {}, 0
    local function log(s)
        lines[#lines + 1] = s
        local f = io.open(G.RESULT, "w")
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

    local ok, env = pcall(G.inputs, getenv)
    if not check("environment bindings present and consistent", ok, env) then return finish("bad environment") end

    local function load(rel) return dofile(env.root .. "/" .. rel) end
    local pack
    ok, pack = pcall(G.load_pack, env, load)
    if not check("selected profile/species pack loaded and matches the running ROM", ok, pack) then
        return finish("bad pack")
    end
    local profile, species, json = pack.profile, pack.species, pack.json

    local hash = api.romhash()
    if not check("running ROM sha1 matches the selected title", type(hash) == "string" and hash:lower() == env.rom_sha1,
                string.format("got %s want %s", tostring(hash), env.rom_sha1)) then return finish("wrong ROM") end
    if not check("running core is CGB", api.systemid() == "GBC", api.systemid()) then return finish("wrong core") end

    local Reads = load("lua/gen2/reads.lua")
    local io_ = G.io(api, profile)
    local reads, why = Reads.new(profile, io_)
    if not check("lua/gen2/reads.lua accepts the selected profile", reads ~= nil, why) then return finish("reads.new refused") end

    local settled, settle_frame = G.settle(api, reads)
    if not check("party decodes within the settle budget", settled, "stuck at frame " .. tostring(settle_frame)) then
        return finish("boot settle failed")
    end
    log("[gen2_inspect_gate] settled at frame " .. settle_frame)

    local live_ok, dump, gap = G.stable_dump(api, profile, io_)
    check("dump is byte-stable across an idle frame gap (checkpoint/liveness)", live_ok, "gap=" .. tostring(gap))
    log("CHECKPOINT " .. (live_ok and "reached" or "not reached"))
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

    local battle, battle_why = reads.read_battle()
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

    return finish()
end

if SLINK_GEN2_GATE_LIBRARY then return G end

local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(ROOT, "SLINK_ROOT unset -- launch via tools/run_gb_gate.py")
local api = G.bizhawk()
api.speed(6399)
G.main(api, os.getenv)
api.exit()
error("slink-gate-finished", 0)   -- client.exit() is asynchronous; stop here for real
