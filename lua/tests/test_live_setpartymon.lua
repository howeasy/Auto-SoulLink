-- test_live_setpartymon.lua — LIVE validation of OP_SET_PARTY_MON (the TRADE primitive). Mirrors what
-- the client does to apply a trade: stage ONE 100-byte party-mon blob (the partner's traded half) in
-- the patch blob buffer, then MB.set_party_mon(slot, blob) so the patch byte-copies it into
-- gPlayerParty[slot]. Asserts the slot comes back BYTE-FOR-BYTE identical (faithful — preserves
-- species/moves/IVs/EVs/PID/item), exactly as OP_SET_ENEMY_PARTY does for the enemy party.
--
-- Savestate-free by design: the opcode is a pure memcpy into the gPlayerParty EWRAM region, so it is
-- validated from a fresh boot (no party context needed). Load with the PATCHED ROM:
--   EmuHawk.exe --lua=<this> patch/build/slink_RR.gba
local WT  = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/setpartymon_result.txt"
local MB  = dofile(WT .. "/lua/mailbox.lua")

local MON = 100
local gPlayerParty = 0x02024284
local function read_blob(addr)
    local t = {}; for j = 1, MON do t[j] = memory.read_u8(addr + (j - 1)) end; return t
end
local function blob_eq(a, b)
    for j = 1, MON do if a[j] ~= b[j] then return false, j end end
    return true
end

local lines, fails = {}, 0
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function check(n, c, e) if not c then fails = fails + 1 end
    log(string.format("  [%s] %s%s", c and "PASS" or "FAIL", n, e and "  " .. e or "")) end
local function finish() log(fails == 0 and "RESULT: PASS" or ("RESULT: FAIL (" .. fails .. ")"))
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit() end

pcall(function() client.speedmode(400) end)
pcall(memory.usememorydomain, "System Bus")
local up = false
for _ = 1, 600 do emu.frameadvance(); if MB.present() then up = true; break end end
if not up then log("FAIL: beacon never appeared (unpatched ROM?)"); finish(); return end
log("beacon up")

-- Deterministic synthetic partner half (distinct, non-zero maxHP so it looks populated).
local SLOT = 1
local blob = {}
for j = 1, MON do blob[j] = (SLOT * 53 + j * 11 + 0x23) % 256 end
blob[0x58 + 1] = 0x2C; blob[0x59 + 1] = 0x01      -- maxHP = 0x012C (offset 0x58, u16) — non-zero

log("slot-pre-differs=" .. tostring(not blob_eq(read_blob(gPlayerParty + SLOT * MON), blob)))

local seq = MB.set_party_mon(SLOT, blob, true)
check("MB.set_party_mon returned a seq", seq ~= nil, "seq=" .. tostring(seq))
local acked, st = false, nil
if seq then
    for _ = 1, 60 do emu.frameadvance(); st = MB.poll(seq); if st then acked = true; break end end
end
check("opcode acked", acked, "status=" .. tostring(st))
check("ack is ST_OK", st == MB.ST_OK)

local got = read_blob(gPlayerParty + SLOT * MON)
local eq, badj = blob_eq(got, blob)
check("gPlayerParty[" .. SLOT .. "] byte-identical to staged blob (faithful trade)",
      eq, eq and "" or ("first diff @byte " .. tostring(badj)))
check("party count covers the slot (bump)", memory.read_u8(0x02024029) >= SLOT + 1,
      "count=" .. memory.read_u8(0x02024029))
check("beacon still present (no corruption)", MB.present())
finish()
