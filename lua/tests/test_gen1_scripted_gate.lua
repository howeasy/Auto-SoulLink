--[[
  lua/tests/test_gen1_scripted_gate.lua — PHYSICAL: scripted NEW GAME play on a cold Red/Blue
  cartridge with the new modules observing.

  Cold boot (no battery save) -> NEW GAME -> bedroom -> Oak's Lab -> starter -> rival battle
  (lost, as the lab script heals) -> optional parcel / save chains, all through ordinary
  buttons. While the route runs, the new signals layer is armed, so the receipt records the
  engine-site sequence a real New Game produces (S-1) and the raw party bytes at the end.

  Environment: SLINK_SCRIPT_CHAIN = "lab" | "lab,parcel" | "lab,save" | "lab,parcel,save"
               SLINK_SCRIPT_PLAYER = "a" (Bulbasaur) | "b" (Charmander)
               SLINK_SCRIPT_FLUSH = "1" to flush SaveRAM at the end (fixture building)
  Result file: patch/build/test_gen1_scripted_gate_result.txt
--]]
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gate.lua")
local t = G.start("test_gen1_scripted_gate", { no_boot = true })
local fmt = string.format
local P = dofile(t.ROOT .. "/lua/tests/gen1_scripted_play.lua")
local json = t.parts.json
local ram = t.parts.profile.ram

local chain = {}
for name in (os.getenv("SLINK_SCRIPT_CHAIN") or "lab"):gmatch("[^,]+") do chain[#chain + 1] = name end
local player = os.getenv("SLINK_SCRIPT_PLAYER") or "a"

-- arm the new signals layer first: the receipt lists every engine site the route crossed
local ok, err = pcall(function() t.client:start() end)
t.check("signals arm on the cold cartridge", ok, err)
local sequence = {}
local function drain()
    for _, sig in ipairs(t.client.signals:drain()) do
        sequence[#sequence + 1] = fmt("%s@%d", sig.kind, sig.frame)
    end
end
local function step(buttons)
    t.step(buttons)
    drain()
end

local safety = dofile(t.ROOT .. "/lua/gen1_write_safety.lua")
local ws = json.decode(assert(io.open(t.ROOT .. "/data/games/gen1_rby/write_checkpoint.json", "rb")):read("*a"))[t.title]
local function overworld_ok() return safety.check(ws, t.deps) == true end

local play = P.new(t.ROOT, t.title, player, { log = t.log })
local bok, berr = pcall(function() return play.boot(step, overworld_ok) end)
t.check("NEW GAME reached the bedroom", bok, berr)
if not bok then t.finish("boot failed") end

local rok, rerr = pcall(function()
    return play.run(step, chain, function(name, phase, frame)
        t.log(fmt("  phase %s: %s @%d", name, phase, frame))
    end)
end)
t.check("route chain reached its terminals: " .. table.concat(chain, ","), rok, rerr)
if not rok then
    client.screenshot(t.ROOT .. "/patch/build/test_gen1_scripted_gate_fail.png")
    t.log("POINT " .. json.encode(play.point()))
end

local party = t.parts.reads.read_party()
t.check("party decodes after the route", party ~= nil)
if party then
    t.check("one starter in the party", #party == 1, fmt("got %d", #party))
    local expect = player == "a" and 0x99 or 0xB0 -- Bulbasaur / Charmander internal indices
    t.check("starter species matches the player", party[1] and party[1].species == expect,
            fmt("got %s", party[1] and party[1].species))
    t.check("starter is level 5 with exp consistent (a real game state)", party[1] and party[1].level == 5 and party[1].exp > 0,
            party[1] and fmt("L%d exp %d", party[1].level, party[1].exp))
end
local function hex(addr, n)
    local out = {}
    for i = 0, n - 1 do out[#out + 1] = fmt("%02X", memory.read_u8(addr + i, "System Bus")) end
    return table.concat(out)
end
t.log("PARTY_RAW " .. hex(ram.wPartyCount, 404))
t.log("MAP " .. json.encode(t.parts.reads.read_map()))
t.log("BAG " .. json.encode(t.parts.reads.read_bag() or {}))
t.log("SIGNALS " .. table.concat(sequence, " "))
t.log(fmt("SIGNAL_STATUS %s", json.encode(t.client.signals:status())))

if os.getenv("SLINK_SCRIPT_FLUSH") == "1" then
    local fok, ferr = pcall(client.saveram)
    t.check("SaveRAM flushed", fok, ferr)
end
t.finish()
