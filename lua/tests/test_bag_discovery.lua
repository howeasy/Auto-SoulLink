--[[
  test_bag_discovery.lua — Finds the Pokéball bag pocket offset in SaveBlock1.
  
  Run in BizHawk with a save loaded that has Pokéballs in the bag.
  Scans ALL of SB1 for ItemSlot entries containing Poké Ball (itemId=4).
  
  Usage: Load in BizHawk Lua Console. Results print immediately.
]]

local M = {}

-- ── Detect profile ──────────────────────────────────────────────────────────
local rom_name_bytes = {}
for i = 0, 31 do
    local b = memory.read_u8(0x08000108 + i, "System Bus")
    if b == 0 then break end
    rom_name_bytes[#rom_name_bytes + 1] = string.char(b)
end
local rom_name = table.concat(rom_name_bytes):lower()

local is_ap = rom_name:find("pokemon red version") or rom_name:find("pokemon green version")
local SB1_PTR, SB2_PTR
if is_ap then
    SB1_PTR = 0x03004F58
    SB2_PTR = 0x03004F5C
    console.log("Detected: AP ROM")
else
    SB1_PTR = 0x03005008
    SB2_PTR = 0x0300500C
    console.log("Detected: Vanilla ROM")
end

local sb1 = memory.read_u32_le(SB1_PTR)
local sb2 = memory.read_u32_le(SB2_PTR)
console.log(string.format("SB1 = 0x%08X, SB2 = 0x%08X", sb1, sb2))

-- ── Encryption key ──────────────────────────────────────────────────────────
console.log("")
console.log("=== Encryption key ===")
for _, off in ipairs({0x0F20, 0x0F2A, 0x0F28, 0x0F2C}) do
    local key = memory.read_u32_le(sb2 + off)
    console.log(string.format("  SB2+0x%04X: 0x%08X  lo16=0x%04X",
        off, key, key & 0xFFFF))
end

-- ── Scan SB1 for Poké Ball (itemId=4) ───────────────────────────────────────
-- ItemSlot = {u16 itemId, u16 quantity}, 4 bytes aligned.
-- Scan from offset 0x0000 to 0x4000 in 2-byte steps (ItemSlots are 4-byte
-- aligned, but search u16 values to find any hit).
console.log("")
console.log("=== Scanning SB1 for u16 == 4 (ITEM_POKE_BALL) on 4-byte boundaries ===")

local pokeball_hits = {}
for offset = 0x0000, 0x3FFC, 4 do
    local val = memory.read_u16_le(sb1 + offset)
    if val == 4 then
        local qty_raw = memory.read_u16_le(sb1 + offset + 2)
        table.insert(pokeball_hits, {offset=offset, qty=qty_raw})
        console.log(string.format("  SB1+0x%04X: itemId=4 (Poke Ball)  rawQty=%d (0x%04X)",
            offset, qty_raw, qty_raw))
    end
end
if #pokeball_hits == 0 then
    console.log("  (no hits — Poké Ball not found with itemId=4 on 4-byte boundaries)")
    console.log("  Trying 2-byte alignment...")
    for offset = 0x0000, 0x3FFE, 2 do
        local val = memory.read_u16_le(sb1 + offset)
        if val == 4 then
            local next_val = memory.read_u16_le(sb1 + offset + 2)
            if next_val > 0 and next_val < 200 then  -- plausible quantity
                console.log(string.format("  SB1+0x%04X: u16=4, next u16=%d",
                    offset, next_val))
            end
        end
    end
end

-- ── Scan for ALL ball IDs (1–12) in wider range ─────────────────────────────
console.log("")
console.log("=== All ball-type ItemSlots (id 1-12) in SB1 0x0000-0x4000 ===")

local BALL_NAMES = {
    [1]="Master Ball", [2]="Ultra Ball", [3]="Great Ball", [4]="Poke Ball",
    [5]="Safari Ball", [6]="Net Ball", [7]="Dive Ball", [8]="Nest Ball",
    [9]="Repeat Ball", [10]="Timer Ball", [11]="Luxury Ball", [12]="Premier Ball"
}

for offset = 0x0000, 0x3FFC, 4 do
    local itemId = memory.read_u16_le(sb1 + offset)
    if itemId >= 1 and itemId <= 12 then
        local qty_raw = memory.read_u16_le(sb1 + offset + 2)
        -- Filter: only show if qty looks plausible (0-999) 
        if qty_raw < 1000 then
            console.log(string.format("  SB1+0x%04X: id=%2d %-12s  rawQty=%d",
                offset, itemId, BALL_NAMES[itemId] or "?", qty_raw))
        end
    end
end

-- ── Dump region around expected pocket locations ────────────────────────────
console.log("")
console.log("=== Raw dump at key offsets (16 ItemSlots each) ===")

local check_offsets = {0x0430, 0x0560, 0x0680, 0x0530, 0x05E0, 0x0680, 0x0700}
for _, pocket_off in ipairs(check_offsets) do
    local has_data = false
    for i = 0, 15 do
        local id = memory.read_u16_le(sb1 + pocket_off + i * 4)
        if id ~= 0 and id <= 500 then has_data = true; break end
    end
    if has_data then
        console.log(string.format("  --- SB1+0x%04X ---", pocket_off))
        for i = 0, 15 do
            local id = memory.read_u16_le(sb1 + pocket_off + i * 4)
            local qty = memory.read_u16_le(sb1 + pocket_off + i * 4 + 2)
            if id ~= 0 then
                console.log(string.format("    [%2d] id=%3d  qty=%d", i, id, qty))
            end
        end
    end
end

console.log("")
console.log("=== Done ===")

