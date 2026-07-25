-- test_live_ghostavatar.lua — the ghost must render the PARTNER's avatar, not the local player's.
-- Post a partner avatar (live sprite images/anims ROM ptrs + a distinct 16-colour palette) and
-- assert the spawned ghost sprite ADOPTS those images/anims ptrs and renders on its OWN dedicated
-- OBJ palette slot (15, != the player's slot 0) painted with the posted colours. This proves the
-- override mechanism end to end; exact-avatar correctness is the two-instance visual gate.
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/ghostavatar_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")
local OE, OST, GS, GST = 0x02036E38, 0x24, 0x0202063C, 0x44
local function p_tx() return memory.read_s16_le(OE + 0x10) end
local function p_ty() return memory.read_s16_le(OE + 0x12) end
local function p_gfx() return memory.read_u8(OE + 0x05) end
local function p_spr() return memory.read_u8(OE + 0x04) end
local function oe_spr(i) return memory.read_u8(OE + i*OST + 0x04) end
local function spr_imgs(s) return memory.read_u32_le(GS + s*GST + 0x0C) end
local function spr_anims(s) return memory.read_u32_le(GS + s*GST + 0x08) end
local function spr_palnum(s) return (memory.read_u16_le(GS + s*GST + 0x04) >> 12) & 0x0F end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
check("patch present", MB.present()); if not MB.present() then finish(); return end

-- "Partner avatar": a valid ROM image/anim ptr (reuse the player's own — same RR build, so valid) +
-- a DISTINCT synthetic palette so we can prove it lands in the ghost's slot, untouched by the player.
local psid = p_spr()
local pimgs, panims = spr_imgs(psid), spr_anims(psid)
local pcol_t, pcol = {}, nil
for i = 0, 15 do pcol_t[#pcol_t+1] = string.format("%04X", (0x0421 * (i + 1)) & 0x7FFF) end
pcol = table.concat(pcol_t)
log(string.format("partner imgs=0x%08X anims=0x%08X", pimgs, panims))

-- spawn the stand-in ghost, place it next to the player, then post the partner avatar.
MB.ghost_set_pos((p_tx()+1)*16, p_ty()*16, 4, 0, 0)
MB.ghost_spawn(p_gfx())
local oe=16; for _=1,120 do emu.frameadvance(); oe = MB.ghost_oe(); if oe<16 then break end end
check("ghost spawned", oe < 16, "oeId="..oe); if oe>=16 then finish(); return end
local gsid = oe_spr(oe)

MB.ghost_set_avatar(pimgs, panims, pcol)
for _=1,20 do emu.frameadvance() end

check("ghost adopted the partner's images ptr", spr_imgs(gsid) == pimgs,
      string.format("0x%08X want 0x%08X", spr_imgs(gsid), pimgs))
check("ghost adopted the partner's anims ptr", spr_anims(gsid) == panims,
      string.format("0x%08X want 0x%08X", spr_anims(gsid), panims))
check("ghost uses a dedicated palette slot (15, not the player's 0)", spr_palnum(gsid) == 15,
      "palNum="..spr_palnum(gsid))
check("player's own palette slot is untouched (still 0)", spr_palnum(psid) == 0,
      "playerPalNum="..spr_palnum(psid))

-- the ghost's slot-15 palette should hold the posted colours (untinted unfaded shadow buffer)
local slot15 = 0x020373F8 + 15*0x20
local ok_pal = true
for i = 0, 15 do
  local want = (0x0421 * (i + 1)) & 0x7FFF
  if memory.read_u16_le(slot15 + i*2) ~= want then ok_pal = false end
end
check("ghost slot-15 palette holds the partner's colours", ok_pal)
MB.ghost_clear()
finish()
