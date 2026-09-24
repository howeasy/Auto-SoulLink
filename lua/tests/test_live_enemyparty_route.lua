-- test_live_enemyparty_route.lua — LIVE validation of OP_SET_ENEMY_PARTY, the field trade's enemy-
-- party transport, through lua/gen3/native.lua: native:transfer("enemy", {blobs_hex}) stages the
-- partner's raw 100-byte party-mon blobs in BLOB_BUF and posts the op, and the patch byte-copies them
-- into gEnemyParty + sets the count.
--
-- The point of the opcode (vs CreateMon per slot) is FAITHFULNESS: it must reproduce the partner's
-- EXACT mons (moves/IVs/EVs/PID/item), not a fresh species+level mon. So the gate stages DETERMINISTIC
-- synthetic blobs (distinct per slot) and asserts each enemy slot comes back BYTE-FOR-BYTE identical.
-- The count is set and the first unused slot's maxHP is zeroed (the CFRU scan terminator).
--
-- Savestate-free by design: a pure memcpy into the gEnemyParty EWRAM region, validated from a fresh
-- boot. (The rival swap's own opcode 28 is a separate path: native:replace_rival_team.) PATCHED ROM.
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

-- Sanity: enemy slot 0 currently differs from our blob, so a later match proves the copy wrote.
t.log("enemy-slot0-pre-differs=" .. tostring(not blob_eq(t.read_blob(ENEMY), rows[1])))

local job = t.watch(t.native:transfer("enemy", { blobs_hex = hex }))
t.check("native:transfer(enemy) queued the op", job ~= nil)
t.check("op posted to the mailbox (dispatch receipt)", t.wait_posted(job))
local r = t.wait(job, 60)
t.check("opcode acked", r ~= nil, t.receipt_str(r))
t.check("ack is ST_OK", r ~= nil and r.why == nil, t.receipt_str(r))

for i = 1, N do
    local eq, badj = blob_eq(t.read_blob(ENEMY + (i - 1) * MON), rows[i])
    t.check("enemy slot " .. (i - 1) .. " byte-identical to staged blob",
            eq, eq and "" or ("first diff @byte " .. tostring(badj)))
end
t.check("gEnemyPartyCount == N", memory.read_u8(t.ram.ENEMY_COUNT_ADDR) == N,
        "count=" .. memory.read_u8(t.ram.ENEMY_COUNT_ADDR))
t.check("trailing slot " .. N .. " maxHP zeroed (CFRU scan terminator)", maxhp(N) == 0, "maxhp=" .. maxhp(N))
t.check("beacon still present (no corruption)", t.present())
t.finish()
