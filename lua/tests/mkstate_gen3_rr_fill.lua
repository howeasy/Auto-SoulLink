-- mkstate_gen3_rr_fill.lua — make a Radical Red savestate whose party holds N mons, from an
-- existing 1-mon state, using the companion patch's native OP_CREATE_MON (the same filler the
-- duo stub uses, lua/tests/archive/gen3_old_client/duo_main.lua:57-77). A fixture-making tool: the fillers are a
-- harness write, but every PC operation the RR natural-play driver performs on them is the
-- engine's own (PLAN §5.7 natural-play source for pc_* kinds; the game refuses to deposit its
-- LAST mon, so a 1-mon state can never exercise the storage frontend).
--
-- OP_CREATE_MON is patch ABI the client never uses, so it is posted through the test-only raw poster
-- in lua/tests/gen3_gatelib.lua (t.raw: native.lua's own ABI and write window), not archive/gen3-old-client:lua/mailbox.lua
-- (card C5-6-MKSTATE).
--
-- Environment: SLINK_ROOT, SLINK_GEN3_CHECKPOINT/TITLE (gen3_boot_check helpers),
--   SLINK_STATE      source savestate (default E:/Howard/Bizhawk/GBA/State/slink_pokecenter.State)
--   SLINK_STATE_OUT  destination (default <source dir>/slink_pokecenter_full.State)
--   SLINK_FILL_TO    target party count (default 3)

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")
G.open("gen3_rr_fill")
local t = dofile(WT .. "/lua/tests/gen3_gatelib.lua").open("gen3_rr_fill")
t.log = G.log              -- one result file: gatelib checks/verdicts land in G's
t.finish = function(extra)
    G.finish(t.failures == 0, extra)
    error("slink-gate-finished", 0)     -- client.exit() is async; stop here for real
end
pcall(client.speedmode, 6399)
local cp, title = G.checkpoint()
G.phase("start", "title=" .. tostring(title))

local SRC = os.getenv("SLINK_STATE") or "E:/Howard/Bizhawk/GBA/State/slink_pokecenter.State"
local OUT = os.getenv("SLINK_STATE_OUT") or (SRC:match("(.*[/\\])") or "") .. "slink_pokecenter_full.State"
local TARGET = tonumber(os.getenv("SLINK_FILL_TO") or "") or 3
local PARTY_COUNT = 0x02024029          -- RR profile PARTY_COUNT_ADDR (lua/games/gen3_frlge.lua)

local ok = pcall(savestate.load, SRC)
if not ok then G.finish(false, "savestate load failed: " .. SRC) end
G.idle(30)
pcall(memory.usememorydomain, "System Bus")
G.idle(60)
if not t.present() then t.fail("SLNK beacon up", "not the companion ROM") end
t.boot({ native = false, beacon = false })   -- admit + the raw poster's write window; no state load
local count = memory.read_u8(PARTY_COUNT)
G.phase("before", "party=" .. count)
local FILLERS = { 1, 4, 7, 10, 13, 16 }   -- Bulbasaur, Charmander, Squirtle, Caterpie, Weedle, Pidgey
while count < TARGET do
    -- args {slot, party 0 = player, species lo, species hi, level 5, bump 1 = a real member}
    local sp = FILLERS[count + 1]
    local r = t.raw_wait("OP_CREATE_MON", { count, 0, sp & 0xFF, sp >> 8, 5, 1 }, nil, 120)
    if not t.acked_ok(r) then t.fail("OP_CREATE_MON acked OK", t.receipt_str(r)) end
    local now = memory.read_u8(PARTY_COUNT)
    if now ~= count + 1 then t.fail("party count +1 after create", string.format("%d -> %d", count, now)) end
    count = now
end
-- SLINK_GIVE_BALLS=N: put N Poke Balls in the FIRST EMPTY slot of the RR ball pocket. RR keeps
-- its bag in fixed EWRAM (radical_red profile BAG_IN_EWRAM=true, BALL_POCKET_ADDR=0x0203C354,
-- BALL_POCKET_ENC=false, 50 slots: lua/games/gen3_frlge.lua:311-314; docs/gen3/research/
-- rr_bag_layout.md: gBagPockets 0x0203988C -> ball base 0x0203C354, ItemSlot {u16 id; u16 qty},
-- quantity raw). ITEM_POKE_BALL = 4. The vanilla SaveBlock1+0x430 pocket is NOT used by RR
-- (PHYSICAL 2026-09-21: a write there never showed in the CFRU bag). Written with the bag CLOSED.
local BALLS = tonumber(os.getenv("SLINK_GIVE_BALLS") or "") or 0
if BALLS > 0 then
    local base = 0x0203C354
    local slot = nil
    for s = 0, 49 do
        local id = memory.read_u16_le(base + s * 4)
        if id == 4 or id == 0 then slot = base + s * 4; break end
    end
    assert(slot, "ball pocket full")
    memory.write_u16_le(slot, 4)
    memory.write_u16_le(slot + 2, BALLS)
    G.phase("balls", string.format("wrote item=4 qty=%d at %08X (RR ball pocket)", BALLS, slot))
end
G.idle(60)
local oks = pcall(savestate.save, OUT)
G.phase("after", string.format("party=%d saved=%s -> %s", count, tostring(oks), OUT))
G.finish(oks, oks and ("party " .. count .. " state written") or "savestate.save failed")
