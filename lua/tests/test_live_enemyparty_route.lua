-- test_live_enemyparty_route.lua — RR-DURABLE: OP_SET_ENEMY_PARTY (16), the OLD raw field-trade
-- staging, through lua/gen3/native.lua's v1 transport (native:transfer("enemy")). On the durable
-- companion it is a trade bypass (Codex Emerald ruling P1): the patch must ACK ST_FAIL with
-- REASON_DURABLE_ONLY (9) and leave gEnemyParty and its count untouched. The durable trade stages
-- the incoming record itself (patch/src/rr_trade_relay.h). The rival swap has its own opcode 28.
--
-- Savestate-free by design: a would-be memcpy into the gEnemyParty EWRAM region, checked from a
-- fresh boot. PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("enemypartyroute")
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
local ENEMY = t.ram.ENEMY_BASE
local function blob_eq(a, b)
    for j = 1, MON do if a[j] ~= b[j] then return false, j end end
    return true
end
local function maxhp(slot) return memory.read_u16_le(ENEMY + slot * MON + 0x58) end

-- Deterministic synthetic partner blobs: distinct per slot, non-zero maxHP so they look populated.
local N = 3
local rows, hex = {}, {}
for i = 1, N do
    local b = {}
    for j = 1, MON do b[j] = (i * 37 + j * 7 + 0x11) % 256 end
    b[0x58 + 1] = 0x90; b[0x59 + 1] = 0x01      -- maxHP = 0x0190 (offset 0x58, u16) — clearly non-zero
    rows[i], hex[i] = b, t.hex(b)
end

local before = {}
for i = 1, N do before[i] = t.read_blob(ENEMY + (i - 1) * MON) end
local count0 = memory.read_u8(t.ram.ENEMY_COUNT_ADDR)

local job = t.watch(t.native:transfer("enemy", { blobs_hex = hex }))
t.check("native:transfer(enemy) queued the op", job ~= nil)
t.check("op posted to the mailbox (dispatch receipt)", t.wait_posted(job))
local r = t.wait(job, 60)
t.check("opcode acked", r ~= nil, t.receipt_str(r))
t.check("ack is ST_FAIL (a refused trade bypass)", r ~= nil and r.why == "native refused", t.receipt_str(r))
t.check("reason is REASON_DURABLE_ONLY (9)", memory.read_u16_le(t.P.BASE + 14) == 9,
        "reason=" .. memory.read_u16_le(t.P.BASE + 14))
for i = 1, N do
    local eq, badj = blob_eq(t.read_blob(ENEMY + (i - 1) * MON), before[i])
    t.check("enemy slot " .. (i - 1) .. " untouched", eq, eq and "" or ("first diff @byte " .. tostring(badj)))
end
t.check("gEnemyPartyCount untouched", memory.read_u8(t.ram.ENEMY_COUNT_ADDR) == count0,
        "count " .. count0 .. " -> " .. memory.read_u8(t.ram.ENEMY_COUNT_ADDR))
t.check("beacon still present (no corruption)", t.present())
t.finish()
