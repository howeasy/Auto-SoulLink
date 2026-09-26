-- test_live_tradescene.lua — OP_TRADE_SCENE (the NATIVE trade animation) through lua/gen3/native.lua,
-- in the order the client's trade FSM posts it: native:transfer("enemy") stages the partner mon in
-- gEnemyParty[0] (OP_SET_ENEMY_PARTY), then native:transfer("scene", {slot = 0}) runs the FireRed
-- in-game trade scene (special DoInGameTradeScene, idx 265), which trades gPlayerParty[0] <->
-- gEnemyParty[0] and returns to the overworld. We assert slot 0 now holds the staged mon by its
-- PLAINTEXT personality + OTID (@0x00/@0x04: the received mon's identity; trade-evolution changes the
-- species but NOT these) and that slot 0 really changed.
--
-- The partner mon: the overworld savestate's spare party slots are empty and the old CREATE_MON
-- setup is not a native.lua op, so the gate re-keys a copy of the player's own slot 0. RR/CFRU keeps
-- the secure block unencrypted in fixed order with no checksum (lua/gen3/reads.lua), so a new
-- pid/otId (pid' = pid -/+ 24, otId' = otId ^ pid ^ pid') gives a valid mon with a DIFFERENT identity.
--
-- Two cases, each from a fresh state load:
--   vanilla   the copy as-is (a species inside FR's 1..411 range);
--   expanded  the copy's species set to 1324 (growth.species, secure block +0), a CFRU-expanded id,
--             as both rr_battle2 slot-1 mons;
--   fullname  1324 with a 10-glyph nickname ("Aaaaaaaaaa", as the duo fixtures), which fills the
--             field with no 0xFF terminator. This is what stomped EWRAM in the RR duo trade_gen3
--             (gPlayerPartyCount 2 -> 213 = 'a' at the end of B's animation): the patch copied the
--             raw field into gStringVar3 unterminated.
-- Every case also asserts gPlayerPartyCount is unchanged by the scene. (The fullname stomp's writer,
-- found with a bus-write watch: docs/gen3/probes/rr_tradescene_fullname_2026-09-26.txt.)
-- Needs the overworld savestate (has a party). PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("tradescene")

local EXPANDED_SPECIES = 1324

local function id4(addr, off) return string.format("%08X", memory.read_u32_le(addr + off)) end
local function put_u32(b, off, v) for i = 0, 3 do b[off + i + 1] = (v >> (8 * i)) & 0xFF end end

local function trade_case(label, species, fullname)
    t.boot({ state = "slink_overworld.State" })
    local PARTY, ENEMY, COUNT = t.ram.PARTY_BASE, t.ram.ENEMY_BASE, t.ram.PARTY_COUNT_ADDR
    local count0 = memory.read_u8(COUNT)
    local partner = t.read_blob(PARTY)
    local pid, otid = memory.read_u32_le(PARTY), memory.read_u32_le(PARTY + 4)
    local pid2 = pid >= 24 and pid - 24 or pid + 24
    put_u32(partner, 0, pid2)
    put_u32(partner, 4, otid ~ pid ~ pid2)
    if species then partner[0x21], partner[0x22] = species & 0xFF, species >> 8 end
    if fullname then   -- a 10-glyph nickname fills the field: no 0xFF terminator inside it
        partner[0x09] = 0xBB
        for i = 1, 9 do partner[0x09 + i] = 0xD5 end
    end
    local want_pid, want_otid = string.format("%08X", pid2), string.format("%08X", otid ~ pid ~ pid2)
    local want_species = partner[0x21] | (partner[0x22] << 8)
    local before_pid = id4(PARTY, 0x00)
    t.log(string.format("[%s] partner pid=%s otid=%s species=%d | slot0 pid before=%s | count=%d",
                        label, want_pid, want_otid, want_species, before_pid, count0))
    t.check(label .. ": partner mon is valid (non-zero identity)", pid ~= 0 and want_pid ~= before_pid)

    local stage = t.watch(t.native:transfer("enemy", { blobs_hex = { t.hex(partner) } }))
    t.check(label .. ": native:transfer(enemy) queued the staging op", stage ~= nil)
    t.check(label .. ": staging op posted (dispatch receipt)", t.wait_posted(stage))
    local sr = t.wait(stage, 60)
    t.check(label .. ": partner mon staged in gEnemyParty[0] (ST_OK)", sr ~= nil and sr.why == nil, t.receipt_str(sr))
    t.check(label .. ": gEnemyParty[0] holds the partner identity",
            id4(ENEMY, 0x00) == want_pid and id4(ENEMY, 0x04) == want_otid,
            "pid=" .. id4(ENEMY, 0x00) .. " otid=" .. id4(ENEMY, 0x04))

    -- Run the native trade scene on slot 0. The scene plays many frames + may prompt; press A throughout.
    local scene = t.watch(t.native:transfer("scene", { slot = 0 }))
    t.check(label .. ": native:transfer(scene) queued the op", scene ~= nil)
    if not scene then t.finish() end
    t.check(label .. ": scene op posted (dispatch receipt)", t.wait_posted(scene))
    local r = t.wait(scene, 6100, function(i) return i % 2 == 0 and { A = true } or nil end)
    t.check(label .. ": trade scene ran and returned to the overworld (acked)", r ~= nil, t.receipt_str(r))
    t.check(label .. ": ack is ST_OK", r ~= nil and r.why == nil, t.receipt_str(r))
    t.check(label .. ": gPlayerPartyCount unchanged by the scene", memory.read_u8(COUNT) == count0,
            "count " .. count0 .. " -> " .. memory.read_u8(COUNT))

    -- Slot 0 now holds the received mon (the staged partner): plaintext identity matches + changed.
    local got_pid, got_otid = id4(PARTY, 0x00), id4(PARTY, 0x04)
    t.check(label .. ": gPlayerParty[0] is now the traded-in partner mon",
            got_pid == want_pid and got_otid == want_otid,
            string.format("got pid=%s otid=%s want pid=%s otid=%s", got_pid, got_otid, want_pid, want_otid))
    t.check(label .. ": slot 0 actually changed (a real trade, not a no-op)", got_pid ~= before_pid,
            "before=" .. before_pid .. " after=" .. got_pid)
    t.check(label .. ": the received species is intact", memory.read_u16_le(PARTY + 0x20) == want_species,
            "species=" .. memory.read_u16_le(PARTY + 0x20))
    t.check(label .. ": beacon still present (no crash)", t.present())
end

trade_case("vanilla", nil)
trade_case("expanded", EXPANDED_SPECIES)
trade_case("fullname", EXPANDED_SPECIES, true)
t.finish()
