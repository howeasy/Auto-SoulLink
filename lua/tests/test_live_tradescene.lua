-- test_live_tradescene.lua — RR-DURABLE: the durable native trade (the shared FR/LG producer run by
-- patch/src/rr_trade_relay.h), driven through the ABI1 mailbox exactly as native.lua's durable
-- descriptor posts it: the session epoch into the shadow block (profile native.TRADE_BASE + 0x44),
-- OP_TRADE_PREPARE (29) -> the native "save the game?" dialog (A = YES) -> READY, then
-- OP_TRADE_SCENE (21) with the incoming record staged in BLOB_BUF -> the in-game trade scene
-- (DoInGameTradeScene) -> the native post-save -> a witnessed COMMITTED. The old raw v1 scene
-- (OP_SET_ENEMY_PARTY + a bare OP_TRADE_SCENE ack) is gone; a bare 21 without READY is refused.
--
-- Asserted per case: the shadow witness (all five milestones, save OK, COMMITTED, received PID/OT),
-- the producer phases (PRE_SAVE -> READY -> SCENE -> DONE), gSaveCounter advanced by both native
-- saves, gPlayerParty[0] now the partner by its PLAINTEXT personality + OTID (trade evolution changes
-- the species, never these), the species intact, and gPlayerPartyCount unchanged.
--
-- The partner mon: the overworld savestate's spare party slots are empty, so the gate re-keys a copy
-- of the player's own slot 0. RR/CFRU keeps the secure block unencrypted in fixed order with no
-- checksum (lua/gen3/reads.lua), so a new pid/otId (pid' = pid -/+ 24, otId' = otId ^ pid ^ pid')
-- gives a valid mon with a DIFFERENT identity.
--
-- Cases, each from a fresh state load:
--   vanilla   the copy as-is (a species inside FR's 1..411 range);
--   expanded  the copy's species set to 1324 (growth.species, secure block +0), a CFRU-expanded id;
--   fullname  1324 with a 10-glyph nickname ("Aaaaaaaaaa"), which fills the field with no 0xFF
--             terminator: the RR duo EWRAM stomp (docs/gen3/probes/rr_tradescene_fullname_2026-09-26.txt).
--   bare21    a SCENE with no READY PREPARE: refused (identity 12), nothing traded, no save.
-- Needs the overworld savestate (has a party). PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("tradescene")

local EXPANDED_SPECIES = 1324
local SAVE_COUNTER = 0x03005390           -- gSaveCounter (trade_journal RELOAD_LAYOUTS.firered_rr)
local EPOCH = 0x5A5A0001

local function id4(addr, off) return string.format("%08X", memory.read_u32_le(addr + off)) end
local function put_u32(b, off, v) for i = 0, 3 do b[off + i + 1] = (v >> (8 * i)) & 0xFF end end
local function le32(v) local b = {}; put_u32(b, 0, v); return b end

local function trade_case(label, species, fullname, bare)
    t.boot({ state = "slink_overworld.State", native = false })
    local TB = assert(t.P.TRADE_BASE, "profile.native.TRADE_BASE (the durable block)")
    local function phase() return memory.read_u32_le(TB + 0x48) end
    local W = TB + 0x50                                   -- SlinkTradeWitnessV2
    local PARTY, COUNT = t.ram.PARTY_BASE, t.ram.PARTY_COUNT_ADDR
    local count0, saves0 = memory.read_u8(COUNT), memory.read_u32_le(SAVE_COUNTER)
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
    t.log(string.format("[%s] partner pid=%s otid=%s species=%d | slot0 pid before=%s | count=%d saves=%d",
                        label, want_pid, want_otid, want_species, before_pid, count0, saves0))
    t.check(label .. ": producer idle and capability advertised",
            phase() == 0 and memory.read_u32_le(TB + 0x40) == 1, "phase=" .. phase())
    t.check(label .. ": epoch staged in the shadow block", t.raw_stage({ { TB + 0x44, le32(EPOCH) } }))

    -- trade args: slot 0, role 0, reserved, old PID/OT, visit 1, a 16-byte opaque token
    local args = { 0, 0, 0, 0 }
    for _, b in ipairs(le32(pid)) do args[#args + 1] = b end
    for _, b in ipairs(le32(otid)) do args[#args + 1] = b end
    for _, b in ipairs(le32(1)) do args[#args + 1] = b end
    for i = 1, 16 do args[#args + 1] = 0x40 + i end
    local press = function(want)
        return function(i) return phase() == want and i % 16 < 2 and { A = true } or nil end
    end

    if bare then
        local r = t.raw_wait("OP_TRADE_SCENE", args, { { t.P.BLOB_BUF, partner } }, 120)
        t.check(label .. ": a SCENE without a READY PREPARE is refused", r ~= nil and r.why ~= nil, t.receipt_str(r))
        t.check(label .. ": refused as identity (12)", r ~= nil and r.reason == 12, t.receipt_str(r))
        t.check(label .. ": nothing traded", id4(PARTY, 0x00) == before_pid)
        t.check(label .. ": no native save", memory.read_u32_le(SAVE_COUNTER) == saves0)
        return
    end

    local prep = t.raw("OP_TRADE_PREPARE", args)
    t.check(label .. ": PREPARE posted", t.wait_posted(prep))
    local r = t.wait(prep, 1500, press(1))
    t.check(label .. ": PREPARE acked READY after the native pre-save", t.acked_ok(r), t.receipt_str(r))
    t.check(label .. ": producer READY", phase() == 2, "phase=" .. phase())
    t.check(label .. ": pre-save witnessed (milestone 0, save OK, accepted+consent)",
            memory.read_u32_le(W + 0x1C) == 1 and memory.read_u8(W + 0x2B) == 1 and memory.read_u16_le(W + 0x1A) == 3,
            string.format("milestones=%d save=%d flags=%d", memory.read_u32_le(W + 0x1C),
                          memory.read_u8(W + 0x2B), memory.read_u16_le(W + 0x1A)))
    local saves1 = memory.read_u32_le(SAVE_COUNTER)
    t.check(label .. ": the pre-save wrote flash (gSaveCounter advanced)", saves1 > saves0,
            saves0 .. " -> " .. saves1)

    local scene = t.raw("OP_TRADE_SCENE", args, { { t.P.BLOB_BUF, partner } })
    scene.deadline = t.frame + 7000                        -- the animation outlasts the raw default
    t.check(label .. ": SCENE posted", t.wait_posted(scene))
    r = t.wait(scene, 6500, press(3))
    t.check(label .. ": SCENE acked COMMITTED", t.acked_ok(r), t.receipt_str(r))
    t.check(label .. ": producer DONE", phase() == 4, "phase=" .. phase())
    t.check(label .. ": witness: five milestones, save OK, COMMITTED",
            memory.read_u32_le(W + 0x1C) == 0x1F and memory.read_u8(W + 0x2B) == 1 and memory.read_u8(W + 0x2A) == 1,
            string.format("milestones=0x%X save=%d final=%d", memory.read_u32_le(W + 0x1C),
                          memory.read_u8(W + 0x2B), memory.read_u8(W + 0x2A)))
    t.check(label .. ": witness received identity is the partner",
            id4(W, 0x48) == want_pid and id4(W, 0x4C) == want_otid, id4(W, 0x48) .. ":" .. id4(W, 0x4C))
    t.check(label .. ": the post-save wrote flash", memory.read_u32_le(SAVE_COUNTER) > saves1,
            saves1 .. " -> " .. memory.read_u32_le(SAVE_COUNTER))
    t.check(label .. ": gPlayerPartyCount unchanged by the scene", memory.read_u8(COUNT) == count0,
            "count " .. count0 .. " -> " .. memory.read_u8(COUNT))
    local got_pid, got_otid = id4(PARTY, 0x00), id4(PARTY, 0x04)
    t.check(label .. ": gPlayerParty[0] is now the traded-in partner mon",
            got_pid == want_pid and got_otid == want_otid,
            string.format("got pid=%s otid=%s want pid=%s otid=%s", got_pid, got_otid, want_pid, want_otid))
    t.check(label .. ": the received species is intact", memory.read_u16_le(PARTY + 0x20) == want_species,
            "species=" .. memory.read_u16_le(PARTY + 0x20))
    t.check(label .. ": beacon still present (no crash)", t.present())
end

trade_case("vanilla", nil)
trade_case("expanded", EXPANDED_SPECIES)
trade_case("fullname", EXPANDED_SPECIES, true)
trade_case("bare21", nil, false, true)
t.finish()
