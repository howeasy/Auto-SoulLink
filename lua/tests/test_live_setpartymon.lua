-- test_live_setpartymon.lua — RR-DURABLE: OP_SET_PARTY_MON (18), the OLD raw 100-byte record
-- replacement, through lua/gen3/native.lua's v1 transport (native:transfer("party")). On the durable
-- companion raw record replacement is never a trade path (Codex Emerald ruling P1): the patch must
-- ACK ST_FAIL with REASON_DURABLE_ONLY (9) and leave gPlayerParty[slot] and the count untouched.
--
-- Savestate-free by design: a would-be memcpy into the gPlayerParty EWRAM region, checked from a
-- fresh boot. PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("setpartymon")
t.boot()
-- COLD BOOT (G5-GATES-LIVE 2026-09-24): the beacon is up by frame ~12, before the game has set its save
-- pointers, and writes:arm refuses until they are live ("safety.lua: invalid pointer: gPokemonStoragePtr").
-- The client never arms that early (it waits for the server hello), so step until an arm would succeed.
-- Idle alone never gets there (3000 frames, run 2); RR sets them when the main menu loads the save
-- (lua/tests/mkstate.lua:38-46), so pulse Start through the intro/title (probe: armable ~8 frames
-- after the first Start at the title). The field is never entered: no A, no CONTINUE.
do
    local never = function() return false end
    local ready = false
    for _ = 1, 3000 do
        ready = pcall(function() t.writes:arm("native", never) end)
        t.writes:disarm()
        if ready then break end
        t.step((_ % 32 == 0) and { Start = true } or nil)
    end
    if not ready then t.fail("save pointers live (native arm possible)", "frame " .. t.frame) end
    t.log(string.format("native arm possible at frame %d", t.frame))
    -- The pointers go live during the title -> main-menu transition, and the companion hook then
    -- lags past a 20-frame ack wait (mailbox_battle, live 731cf9b3: FORCE_FAINT posted, no ack in
    -- 20 frames; with this settle it acks). Let the menu come up before the first post.
    for _ = 1, 120 do t.step(nil) end
end

local MON = 100
local PARTY = t.ram.PARTY_BASE
local function blob_eq(a, b)
    for j = 1, MON do if a[j] ~= b[j] then return false, j end end
    return true
end

-- Deterministic synthetic partner half (distinct, non-zero maxHP so it looks populated).
local SLOT = 1
local blob = {}
for j = 1, MON do blob[j] = (SLOT * 53 + j * 11 + 0x23) % 256 end
blob[0x58 + 1] = 0x2C; blob[0x59 + 1] = 0x01      -- maxHP = 0x012C (offset 0x58, u16) — non-zero

local before = t.read_blob(PARTY + SLOT * MON)
local count0 = memory.read_u8(t.ram.PARTY_COUNT_ADDR)

local job = t.watch(t.native:transfer("party", { slot = SLOT, blob_hex = t.hex(blob), bump = true }))
t.check("native:transfer(party) queued the op", job ~= nil)
t.check("op posted to the mailbox (dispatch receipt)", t.wait_posted(job))
local r = t.wait(job, 60)
t.check("opcode acked", r ~= nil, t.receipt_str(r))
t.check("ack is ST_FAIL (raw record replacement refused)", r ~= nil and r.why == "native refused", t.receipt_str(r))
t.check("reason is REASON_DURABLE_ONLY (9)", memory.read_u16_le(t.P.BASE + 14) == 9,
        "reason=" .. memory.read_u16_le(t.P.BASE + 14))
local eq, badj = blob_eq(t.read_blob(PARTY + SLOT * MON), before)
t.check("gPlayerParty[" .. SLOT .. "] untouched", eq, eq and "" or ("first diff @byte " .. tostring(badj)))
t.check("party count untouched", memory.read_u8(t.ram.PARTY_COUNT_ADDR) == count0,
        "count " .. count0 .. " -> " .. memory.read_u8(t.ram.PARTY_COUNT_ADDR))
t.check("beacon still present (no corruption)", t.present())
t.finish()
