-- test_live_msgbox_route.lua — end-to-end client routing for the "msgbox" command using
-- the REAL memory_gba.isInOverworld(): when the companion patch is present AND we're in the
-- overworld, route to the native message box (SHOW_MESSAGE); else fall back to the HUD
-- overlay. Load with the PATCHED ROM + overworld savestate.

local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/msgboxroute_result.txt"
local gStringVar4 = 0x02021D18

-- mirror the client's package.path so require() finds the modules
local LUA = WT .. "/lua/"
package.path = LUA .. "?.lua;" .. LUA .. "games/?.lua;"
            .. WT .. "/data/games/gen3_frlge/?.lua;" .. package.path
for _, m in ipairs({"memory_gba","game_detect","mailbox","games.gen3_frlge"}) do package.loaded[m] = nil end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")

local ok, err = pcall(function()
  local MB = require("mailbox")
  local M  = require("memory_gba")
  local gd = require("game_detect")
  local detected = gd.detect()
  M.applyProfile(detected.profile, detected.variant)
  log("variant=" .. tostring(detected.variant))

  local function patch_present() return MB ~= nil and MB.present() end
  -- the exact gen3-client handler body for cmd == "msgbox"
  local routed
  local function handle_msgbox(c)
      if patch_present() and M.isInOverworld() then
          MB.write_message(c.text); MB.send(MB.OP_SHOW_MESSAGE, {})
          routed = "native"
      else
          routed = "hud"     -- would call hud_show(c.text, c.r, c.g, c.b, c.frames)
      end
  end

  check("in overworld (real isInOverworld)", M.isInOverworld())
  check("patch present", patch_present())

  local TEXT = "Sparky and Charchar linked!"   -- the text the server now emits on link
  handle_msgbox({ cmd = "msgbox", text = TEXT, r = 100, g = 255, b = 160, frames = 300 })
  for _=1,30 do emu.frameadvance() end

  check("routed to NATIVE box (overworld + patch)", routed == "native", "routed="..tostring(routed))
  local enc = MB.fr_encode(TEXT)
  local match = true
  for i=1,#enc do if memory.read_u8(gStringVar4 + (i-1)) ~= enc[i] then match=false; break end end
  check("native message box shows the link text", match)
  check("game still running (no crash)", MB.present())
end)
if not ok then log("FAIL: error: " .. tostring(err)) end
finish()
