-- test_live_ghostlayer.lua — VISUAL: does the ghost layer correctly (behind the player when north,
-- in front when south)? Geometry only, so a single-instance recoloured ghost is representative.
-- A screenshot capture (patch/build/ghostlayer_*.png), not an automated oracle: it asserts only that
-- the ghost spawned and the shots were taken.
-- DEFERRED (peer ghost is post-RC): opt-in via SLINK_GATES_DEFERRED=1. Ghost ops go through
-- lua/tests/gen3_gatelib.lua's test-only raw poster (C5-4c). Overworld savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("ghostlayer")
local SHOT = t.ROOT .. "/patch/build/ghostlayer_"
t.boot({ state = "slink_overworld.State", native = false, speed = 100 })

local GS, GST = t.P.SPRITES_BASE, 0x44
local function p_tx() return memory.read_s16_le(t.player_oe() + 0x10) end
local function p_ty() return memory.read_s16_le(t.player_oe() + 0x12) end
local function p_spr() return memory.read_u8(t.player_oe() + 0x04) end
local function shot(n) pcall(function() client.screenshot(SHOT .. n .. ".png") end); t.log("shot " .. n) end

-- recolour the player's palette (swap R<->B) so the ghost is a clearly different colour
local sid = p_spr()
local pcol = {}
for i = 0, 15 do
    local c = memory.read_u16_le(0x020373F8 + i*2)
    if i == 0 then pcol[#pcol+1] = string.format("%04X", c)
    else local r, g, b = c & 0x1F, (c >> 5) & 0x1F, (c >> 10) & 0x1F
        pcol[#pcol+1] = string.format("%04X", (r << 10) | (g << 5) | b) end
end
pcol = table.concat(pcol)
local pimgs = memory.read_u32_le(GS + sid*GST + 0x0C)
local panims = memory.read_u32_le(GS + sid*GST + 0x08)

-- spawn + give it the distinct avatar
t.ghost_set_pos(p_tx()*16, (p_ty()-1)*16, 1, 0, 0)
t.ghost_spawn(0)
for _ = 1, 90 do if t.ghost_oe() < 16 then break end; t.step(nil) end
t.check("ghost spawned", t.ghost_oe() < 16, "oeId=" .. t.ghost_oe())
t.ghost_set_avatar(pimgs, panims, pcol)

-- Position the ghost ONE TILE NORTH of the player (overlapping from above) -> should draw BEHIND.
for _ = 1, 40 do t.ghost_set_pos(p_tx()*16, (p_ty()-1)*16, 1, 0, 0); t.step(nil) end
shot("1_north_behind")
-- Position it ONE TILE SOUTH (overlapping from below) -> should draw IN FRONT.
for _ = 1, 40 do t.ghost_set_pos(p_tx()*16, (p_ty()+1)*16, 2, 0, 0); t.step(nil) end
shot("2_south_front")
t.ghost_clear()
t.finish()
