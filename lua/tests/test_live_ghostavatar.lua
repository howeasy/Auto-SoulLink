-- test_live_ghostavatar.lua — the ghost must render the PARTNER's avatar, not the local player's.
-- Post a partner avatar (live sprite images/anims ROM ptrs + a distinct 16-colour palette) and
-- assert the spawned ghost sprite ADOPTS those images/anims ptrs and renders on its OWN dedicated
-- OBJ palette slot (15, != the player's slot 0) painted with the posted colours. This proves the
-- override mechanism end to end; exact-avatar correctness is the two-instance visual gate.
-- DEFERRED (peer ghost is post-RC): opt-in via SLINK_GATES_DEFERRED=1. Ghost ops go through
-- lua/tests/gen3_gatelib.lua's test-only raw poster (C5-4c). Overworld savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("ghostavatar")
t.boot({ state = "slink_overworld.State", native = false })

local OE, OST, GS, GST = t.P.OBJECT_EVENTS_BASE, 0x24, t.P.SPRITES_BASE, 0x44
local function p_tx() return memory.read_s16_le(OE + 0x10) end
local function p_ty() return memory.read_s16_le(OE + 0x12) end
local function p_gfx() return memory.read_u8(OE + 0x05) end
local function p_spr() return memory.read_u8(OE + 0x04) end
local function oe_spr(i) return memory.read_u8(OE + i*OST + 0x04) end
local function spr_imgs(s) return memory.read_u32_le(GS + s*GST + 0x0C) end
local function spr_anims(s) return memory.read_u32_le(GS + s*GST + 0x08) end
local function spr_palnum(s) return (memory.read_u16_le(GS + s*GST + 0x04) >> 12) & 0x0F end

-- "Partner avatar": a valid ROM image/anim ptr (reuse the player's own — same RR build, so valid) +
-- a DISTINCT synthetic palette so we can prove it lands in the ghost's slot, untouched by the player.
local psid = p_spr()
local pimgs, panims = spr_imgs(psid), spr_anims(psid)
local pcol_t = {}
for i = 0, 15 do pcol_t[#pcol_t+1] = string.format("%04X", (0x0421 * (i + 1)) & 0x7FFF) end
local pcol = table.concat(pcol_t)
t.log(string.format("partner imgs=0x%08X anims=0x%08X", pimgs, panims))

-- spawn the stand-in ghost, place it next to the player, then post the partner avatar.
t.ghost_set_pos((p_tx()+1)*16, p_ty()*16, 4, 0, 0)
t.ghost_spawn(p_gfx())
local oe = 16
for _ = 1, 120 do oe = t.ghost_oe(); if oe < 16 then break end; t.step(nil) end
t.check("ghost spawned", oe < 16, "oeId=" .. oe); if oe >= 16 then t.finish() end
local gsid = oe_spr(oe)

t.ghost_set_avatar(pimgs, panims, pcol)
t.idle(20)

t.check("ghost adopted the partner's images ptr", spr_imgs(gsid) == pimgs,
        string.format("0x%08X want 0x%08X", spr_imgs(gsid), pimgs))
t.check("ghost adopted the partner's anims ptr", spr_anims(gsid) == panims,
        string.format("0x%08X want 0x%08X", spr_anims(gsid), panims))
t.check("ghost uses a dedicated palette slot (15, not the player's 0)", spr_palnum(gsid) == 15,
        "palNum=" .. spr_palnum(gsid))
t.check("player's own palette slot is untouched (still 0)", spr_palnum(psid) == 0,
        "playerPalNum=" .. spr_palnum(psid))

-- the ghost's slot-15 palette should hold the posted colours (untinted unfaded shadow buffer)
local slot15 = 0x020373F8 + 15*0x20
local ok_pal = true
for i = 0, 15 do
    if memory.read_u16_le(slot15 + i*2) ~= (0x0421 * (i + 1)) & 0x7FFF then ok_pal = false end
end
t.check("ghost slot-15 palette holds the partner's colours", ok_pal)
t.ghost_clear()
t.finish()
