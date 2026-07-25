-- test_live_enemyparty_route.lua — LIVE validation of the PRODUCTION Rival-Team-Swap routing on a
-- patched ROM.  Mirrors what gen3_frlge_client.lua now does when it receives `replace_rival_team`
-- with the companion patch present: stage the partner's raw 100-byte party-mon blobs in the patch's
-- blob buffer, then MB.send(OP_SET_ENEMY_PARTY, {count}) so the patch byte-copies them into
-- gEnemyParty + sets the count.
--
-- The point of the new opcode (vs the existing CreateMon-per-slot path) is FAITHFULNESS: it must
-- reproduce the partner's EXACT mons (moves/IVs/EVs/PID/item), not a fresh species+level mon.  So the
-- test stages DETERMINISTIC synthetic 100-byte blobs (distinct per slot) and asserts each enemy slot
-- comes back BYTE-FOR-BYTE identical — something CreateMon fundamentally cannot do (it derives the
-- bytes from species+level).  The count is set and the first unused slot's maxHP is zeroed (the
-- CFRU scan terminator).
--
-- Savestate-free by design: the opcode is a pure memcpy into the gEnemyParty EWRAM region, so it is
-- validated from a fresh boot (no battle context needed, and no fragile savestate/ROM-build coupling).
-- The Lua-side active-foe gBattleMons refresh (M.refreshEnemyPartyNative -> refreshActiveEnemyBattlers)
-- is existing, separately-covered code and is exercised by test_live_enemyparty.lua in a real battle.
-- Load with the PATCHED ROM:  EmuHawk.exe --lua=<this> patch/build/slink_RR.gba

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/enemypartyroute_result.txt"
local MB  = dofile(WT .. "/lua/mailbox.lua")

local MON = 100
local gEnemyParty = 0x0202402C
local gEnemyCount = 0x0202402A
local function read_blob(addr)
    local t = {}; for j = 1, MON do t[j] = memory.read_u8(addr + (j - 1)) end; return t
end
local function blob_eq(a, b)
    for j = 1, MON do if a[j] ~= b[j] then return false, j end end
    return true
end
local function maxhp(slot) return memory.read_u16_le(gEnemyParty + slot * MON + 0x58) end

local lines, fails = {}, 0
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function check(n, c, e) if not c then fails = fails + 1 end
    log(string.format("  [%s] %s%s", c and "PASS" or "FAIL", n, e and "  " .. e or "")) end
local function finish() log(fails == 0 and "RESULT: PASS" or ("RESULT: FAIL (" .. fails .. ")"))
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit() end

pcall(function() client.speedmode(400) end)
pcall(memory.usememorydomain, "System Bus")
-- Boot until the patch's beacon is up (appears ~frame 13, during the boot logos — well before any
-- title demo touches gEnemyParty).
local up = false
for _ = 1, 600 do emu.frameadvance(); if MB.present() then up = true; break end end
if not up then log("FAIL: beacon never appeared (unpatched ROM?)"); finish(); return end
log("beacon up")

-- Deterministic synthetic partner blobs: distinct per slot, non-zero maxHP so they look populated.
local N = 3
local rows = {}
for i = 1, N do
    local b = {}
    for j = 1, MON do b[j] = (i * 37 + j * 7 + 0x11) % 256 end
    b[0x58 + 1] = 0x90; b[0x59 + 1] = 0x01      -- maxHP = 0x0190 (offset 0x58, u16) — clearly non-zero
    rows[i] = b
end

-- Sanity: enemy slot 0 currently differs from our blob, so a later match proves the copy wrote.
log("enemy-slot0-pre-differs=" .. tostring(not blob_eq(read_blob(gEnemyParty), rows[1])))

-- Production routing: stage blobs into the patch buffer + dispatch OP_SET_ENEMY_PARTY.
local seq = MB.set_enemy_party(rows)
check("MB.set_enemy_party returned a seq", seq ~= nil, "seq=" .. tostring(seq))
local acked, st = false, nil
if seq then
    for _ = 1, 60 do emu.frameadvance(); st = MB.poll(seq); if st then acked = true; break end end
end
check("opcode acked", acked, "status=" .. tostring(st))
check("ack is ST_OK", st == MB.ST_OK)

-- Faithful copy: every injected enemy slot is byte-identical to the staged blob.
for i = 1, N do
    local got = read_blob(gEnemyParty + (i - 1) * MON)
    local eq, badj = blob_eq(got, rows[i])
    check("enemy slot " .. (i - 1) .. " byte-identical to staged blob",
          eq, eq and "" or ("first diff @byte " .. tostring(badj)))
end

check("gEnemyPartyCount == N", memory.read_u8(gEnemyCount) == N,
      "count=" .. memory.read_u8(gEnemyCount))
check("trailing slot " .. N .. " maxHP zeroed (CFRU scan terminator)", maxhp(N) == 0,
      "maxhp=" .. maxhp(N))
check("beacon still present (no corruption)", MB.present())
finish()
