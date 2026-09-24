-- test_live_ghostshow.lua — VISUAL proof. Spawn the peer ghost next to the player, give it a
-- DISTINCT recoloured avatar (proving it renders on its own palette slot, not the player's), and
-- walk it across via the sub-pixel LERP driver, capturing screenshots so the ghost is visible
-- standing beside you and mid-walk (patch/build/ghostshow_*.png). Not an automated oracle beyond
-- "the ghost spawned".
-- DEFERRED (peer ghost is post-RC): opt-in via SLINK_GATES_DEFERRED=1. Ghost ops go through
-- lua/tests/gen3_gatelib.lua's test-only raw poster (C5-4c). Overworld savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("ghostshow")
local SHOT = t.ROOT .. "/patch/build/ghostshow_"
t.boot({ state = "slink_overworld.State", native = false, speed = 100 })

local OE, GS, GST = t.P.OBJECT_EVENTS_BASE, t.P.SPRITES_BASE, 0x44
local function p_tx() return memory.read_s16_le(OE + 0x10) end
local function p_ty() return memory.read_s16_le(OE + 0x12) end
local function p_gfx() return memory.read_u8(OE + 0x05) end
local function p_spr() return memory.read_u8(OE + 0x04) end
local function shot(n) pcall(function() client.screenshot(SHOT .. n .. ".png") end); t.log("shot " .. n) end

local px, py, gfx = p_tx(), p_ty(), p_gfx()
local sid = p_spr()
local pimgs = memory.read_u32_le(GS + sid*GST + 0x0C)
local panims = memory.read_u32_le(GS + sid*GST + 0x08)
-- Recolour the player's real palette into a clearly DIFFERENT trainer (swap R<->B 5-bit channels),
-- so the ghost is visibly its own character on its own palette slot.
local cols = {}
for i = 0, 15 do
    local c = memory.read_u16_le(0x020373F8 + i*2)   -- player OBJ slot 0, colour i
    if i == 0 then cols[#cols+1] = string.format("%04X", c)   -- keep transparent index
    else
        local r, g, b = c & 0x1F, (c >> 5) & 0x1F, (c >> 10) & 0x1F
        cols[#cols+1] = string.format("%04X", (r << 10) | (g << 5) | b)   -- swap red<->blue
    end
end
local pcol = table.concat(cols)

-- spawn 2 tiles east of the player, then apply the distinct avatar
local wy = py * 16
t.ghost_set_pos((px+2)*16, wy, 3, 0, 0)
t.ghost_spawn(gfx)
for _ = 1, 90 do if t.ghost_oe() < 16 then break end; t.step(nil) end
t.check("ghost spawned", t.ghost_oe() < 16, "oeId=" .. t.ghost_oe())
t.ghost_set_avatar(pimgs, panims, pcol)
t.idle(40)
shot("1_standing")               -- ghost (recoloured) stands east of the player

-- walk the ghost WEST across in front of the player, capturing mid-stride
local wx = (px+2)*16
for step = 1, 64 do
    wx = wx - 1
    if step % 3 == 0 then t.ghost_set_pos(wx, wy, 3, 1, 6) end   -- facing west, walking, walk anim
    t.step(nil)
    if step == 24 then shot("2_walking") end
    if step == 48 then shot("3_walking") end
end
t.ghost_set_pos(wx, wy, 3, 0, 2)
t.idle(20)
shot("4_arrived")
t.ghost_clear()
t.finish()
