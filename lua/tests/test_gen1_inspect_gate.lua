--[[
  lua/tests/test_gen1_inspect_gate.lua — PHYSICAL: the new Gen 1 modules on a real cartridge.

  Proves, on a booted battery save (tests/fixtures/gen1/<rom>_<target>.SaveRAM):
    R-1  reads.read_party decodes the live party; the RAW party bytes are dumped so the Python
         codec can decode the same bytes and disagree (tests/live/test_gen1_new_gates.py).
    S    signals.new accepts the real ROM (every pinned site's bytes are where the JSON says)
         and registers its hooks without a failure.
    W-7  gen1_write_safety.check() reaches "verified overworld checkpoint" while the player
         stands still, i.e. the write window exists on real hardware.
    F-6  the fixture is a live game (player id set, party readable, box-initialised flag read).

  Result file: patch/build/test_gen1_inspect_gate_result.txt
--]]
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gate.lua")
local t = G.start("test_gen1_inspect_gate")
local fmt = string.format
local ram, d = t.parts.profile.ram, t.parts.profile.derived
local reads, json = t.parts.reads, t.parts.json

local function hex(addr, n, domain)
    local out = {}
    for i = 0, n - 1 do out[#out + 1] = fmt("%02X", memory.read_u8(addr + i, domain or "System Bus")) end
    return table.concat(out)
end

-- F-6 / R-1
local pid = reads.read_player_id()
t.check("player id is set", pid ~= 0, fmt("got %d", pid))
local party, why = reads.read_party()
t.check("party decodes", party ~= nil, why)
if party then
    t.check("party has 1..6 mons", #party >= 1 and #party <= 6, fmt("got %d", #party))
    for _, m in ipairs(party) do
        t.check(fmt("slot %d key has the DDDD:OOOO:SS shape", m.slot), #reads.key(m) == 12, reads.key(m))
        t.check(fmt("slot %d level and HP plausible", m.slot), m.level >= 1 and m.level <= 100 and m.hp <= m.max_hp,
                fmt("L%d %d/%d", m.level, m.hp, m.max_hp))
    end
end
t.log("PARTY_RAW " .. hex(ram.wPartyCount, 404))
t.log("PARTY_LUA " .. json.encode(party or {}))
local box = reads.read_current_box_num()
t.log(fmt("BOXNUM index=%d initialized=%s", box and box.index or -1, tostring(box and box.initialized)))
t.log("BAG " .. json.encode(reads.read_bag() or {}))
t.log(fmt("MAP %s", json.encode(reads.read_map())))

-- S: the real ROM carries every pinned site; hooks register
local ok, err = pcall(function() t.client:start() end)
t.check("signals arm on the real cartridge", ok, err)
if ok then
    local st = t.client.signals:status()
    t.check("no signal failure after arming", st.failed == nil, tostring(st.failed))
end

-- W-7: the verified overworld checkpoint is reachable while idle
local safety = dofile(t.ROOT .. "/lua/gen1_write_safety.lua")
local ws = dofile(t.ROOT .. "/lua/json_codec.lua").decode(
    assert(io.open(t.ROOT .. "/data/games/gen1_rby/write_checkpoint.json", "rb")):read("*a"))[t.title]
local hit, reason, hit_frame = false, nil, nil
for i = 1, 600 do
    local safe, r = safety.check(ws, t.deps)
    reason = r
    if safe then hit, hit_frame = true, t.frame break end
    t.step(nil)
end
t.check("write-safe overworld checkpoint reached while idle", hit, hit and fmt("frame %d", hit_frame) or reason)

-- Tick shape: what the client would send to the server on this cartridge
t.online = true
t.client:send_hello()
t.log("HELLO " .. tostring(t.sent[#t.sent]))
t.finish()
