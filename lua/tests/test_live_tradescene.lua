-- test_live_tradescene.lua — OP_TRADE_SCENE (the NATIVE trade animation) through lua/gen3/native.lua,
-- in the order the client's trade FSM posts it: native:transfer("enemy") stages the partner mon in
-- gEnemyParty[0] (OP_SET_ENEMY_PARTY), then native:transfer("scene", {slot = 0}) runs the FireRed
-- in-game trade scene (special DoInGameTradeScene, idx 265), which trades gPlayerParty[0] <->
-- gEnemyParty[0] and returns to the overworld. We assert slot 0 now holds the staged mon by its
-- PLAINTEXT personality + OTID (@0x00/@0x04: the received mon's identity; trade-evolution changes the
-- encrypted species but NOT these) and that slot 0 really changed.
--
-- The partner mon: the overworld savestate's spare party slots are empty and the old CREATE_MON
-- setup is not a native.lua op, so the gate re-keys a copy of the player's own slot 0. Gen 3 party
-- data is encrypted with personality ^ otId and its substructure order is personality % 24, so
-- pid' = pid -/+ 24 with otId' = otId ^ pid ^ pid' keeps both: the copy is a valid, decryptable mon
-- (same checksum) with a DIFFERENT identity, which is exactly what the oracle needs.
-- Needs the overworld savestate (has a party). PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("tradescene")
t.boot({ state = "slink_overworld.State" })

local PARTY, ENEMY = t.ram.PARTY_BASE, t.ram.ENEMY_BASE
local function id4(addr, off) return string.format("%08X", memory.read_u32_le(addr + off)) end
local function put_u32(b, off, v) for i = 0, 3 do b[off + i + 1] = (v >> (8 * i)) & 0xFF end end

local partner = t.read_blob(PARTY)
local pid, otid = memory.read_u32_le(PARTY), memory.read_u32_le(PARTY + 4)
local pid2 = pid >= 24 and pid - 24 or pid + 24
put_u32(partner, 0, pid2)
put_u32(partner, 4, otid ~ pid ~ pid2)
local want_pid, want_otid = string.format("%08X", pid2), string.format("%08X", otid ~ pid ~ pid2)
local before_pid = id4(PARTY, 0x00)
t.log("partner mon: pid=" .. want_pid .. " otid=" .. want_otid .. " | player slot0 pid before=" .. before_pid)
t.check("partner mon is valid (non-zero identity)", pid ~= 0 and want_pid ~= before_pid)

local stage = t.watch(t.native:transfer("enemy", { blobs_hex = { t.hex(partner) } }))
t.check("native:transfer(enemy) queued the staging op", stage ~= nil)
t.check("staging op posted (dispatch receipt)", t.wait_posted(stage))
local sr = t.wait(stage, 60)
t.check("partner mon staged in gEnemyParty[0] (ST_OK)", sr ~= nil and sr.why == nil, t.receipt_str(sr))
t.check("gEnemyParty[0] holds the partner identity",
        id4(ENEMY, 0x00) == want_pid and id4(ENEMY, 0x04) == want_otid,
        "pid=" .. id4(ENEMY, 0x00) .. " otid=" .. id4(ENEMY, 0x04))

-- Run the native trade scene on slot 0. The scene plays many frames + may prompt; press A throughout.
local scene = t.watch(t.native:transfer("scene", { slot = 0 }))
t.check("native:transfer(scene) queued the op", scene ~= nil)
if not scene then t.finish() end
t.check("scene op posted (dispatch receipt)", t.wait_posted(scene))
local r = t.wait(scene, 6100, function(i) return i % 2 == 0 and { A = true } or nil end)
t.check("trade scene ran and returned to the overworld (acked)", r ~= nil, t.receipt_str(r))
t.check("ack is ST_OK", r ~= nil and r.why == nil, t.receipt_str(r))

-- Slot 0 now holds the received mon (the staged partner): plaintext identity matches + changed.
local got_pid, got_otid = id4(PARTY, 0x00), id4(PARTY, 0x04)
t.check("gPlayerParty[0] is now the traded-in partner mon", got_pid == want_pid and got_otid == want_otid,
        string.format("got pid=%s otid=%s want pid=%s otid=%s", got_pid, got_otid, want_pid, want_otid))
t.check("slot 0 actually changed (a real trade, not a no-op)", got_pid ~= before_pid,
        "before=" .. before_pid .. " after=" .. got_pid)
t.check("beacon still present (no crash)", t.present())
t.finish()
