-- mkstate_gen3_rr_fill.lua — make a Radical Red savestate whose party holds N mons, from an
-- existing 1-mon state, using the companion patch's native OP_CREATE_MON (the same filler the
-- duo stub uses, lua/tests/duo/duo_main.lua:57-77). A fixture-making tool: the fillers are a
-- harness write, but every PC operation the RR natural-play driver performs on them is the
-- engine's own (PLAN §5.7 natural-play source for pc_* kinds; the game refuses to deposit its
-- LAST mon, so a 1-mon state can never exercise the storage frontend).
--
-- Environment: SLINK_ROOT, SLINK_GEN3_CHECKPOINT/TITLE (gen3_boot_check helpers),
--   SLINK_STATE      source savestate (default E:/Howard/Bizhawk/GBA/State/slink_pokecenter.State)
--   SLINK_STATE_OUT  destination (default <source dir>/slink_pokecenter_full.State)
--   SLINK_FILL_TO    target party count (default 3)

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")
G.open("gen3_rr_fill")
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
local MB = dofile(WT .. "/lua/mailbox.lua")
G.idle(60)
if not MB.present() then G.finish(false, "no SLNK beacon: not the companion ROM") end
local count = memory.read_u8(PARTY_COUNT)
G.phase("before", "party=" .. count)
local FILLERS = { 1, 4, 7, 10, 13, 16 }   -- Bulbasaur, Charmander, Squirtle, Caterpie, Weedle, Pidgey
while count < TARGET do
    local seq = MB.send(MB.OP_CREATE_MON, MB.create_mon_args(count, FILLERS[count + 1], 5, 0, 1))
    local st
    for _ = 1, 120 do G.advance(); st = MB.poll(seq); if st then break end end
    if st ~= MB.ST_OK then G.finish(false, "OP_CREATE_MON failed: " .. tostring(st)) end
    local now = memory.read_u8(PARTY_COUNT)
    if now ~= count + 1 then G.finish(false, string.format("party count %d -> %d after create", count, now)) end
    count = now
end
-- SLINK_GIVE_BALLS=N: put N Poke Balls in bag pocket slot 0 (SaveBlock1 + 0x430, pret
-- include/global.h:780 bagPocket_PokeBalls; struct ItemSlot {u16 itemId; u16 quantity};
-- quantity is XORed with SaveBlock2.encryptionKey (global.h, u32 at SaveBlock2 + 0xF20) by the
-- bag code). A fixture write, so the RR driver's wild_catch leg has something to throw.
local BALLS = tonumber(os.getenv("SLINK_GIVE_BALLS") or "") or 0
if BALLS > 0 then
    local sb1 = memory.read_u32_le(0x03005008)   -- gSaveBlock1Ptr (pokefirered.sym; RR profile SB1 pointer)
    local sb2 = memory.read_u32_le(0x0300500C)   -- gSaveBlock2Ptr
    local key = memory.read_u32_le(sb2 + 0xF20)
    local slot = sb1 + 0x430
    memory.write_u16_le(slot, 4)                              -- ITEM_POKE_BALL (items.h:8)
    memory.write_u16_le(slot + 2, (BALLS ~ key) & 0xFFFF)     -- quantity ^ key (low 16 bits)
    G.phase("balls", string.format("sb1=%08X sb2=%08X key=%08X wrote item=4 qty=%d at %08X", sb1, sb2, key, BALLS, slot))
end
G.idle(60)
local oks = pcall(savestate.save, OUT)
G.phase("after", string.format("party=%d saved=%s -> %s", count, tostring(oks), OUT))
G.finish(oks, oks and ("party " .. count .. " state written") or "savestate.save failed")
