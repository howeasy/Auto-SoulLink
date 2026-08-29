--[[
  lua/tests/probe_gen1_panel.lua — why does selecting SLINK not open the panel?

  Every byte of the patch is verifiably in the ROM (the build reads them back) and the
  Bankswitch calling convention is the one home/bankswitch.asm documents, so the remaining
  question is behavioural: what does the game actually DO when the row is chosen. This
  watches the mailbox and the screen frame by frame instead of reasoning about it.

      python tools/run_gb_gate.py lua/tests/probe_gen1_panel.lua --rom red_patched --target town

  Not a gate: it prints a trace.
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("probe_gen1_panel")
local M = t.M
local fmt = string.format

local TILEMAP, SCREEN_W = 0xC3A0, 20
local CUR_MENU, WATCHED = 0xCC26, 0xCC29
local MAILBOX = 0xDEE2
local ABI, CAPS, PANEL_STATE = MAILBOX + 4, MAILBOX + 8, MAILBOX + 9

local function decode(b)
    if b >= 0x80 and b <= 0x99 then return string.char(b - 0x80 + 65) end
    if b == 0x7F then return " " end
    return "."
end

local function row_text(r)
    local o = {}
    for c = 0, SCREEN_W - 1 do o[#o + 1] = decode(M.read_u8(TILEMAP + r * SCREEN_W + c)) end
    return table.concat(o)
end

local function screen_has(needle)
    for r = 0, 17 do if row_text(r):find(needle, 1, true) then return r end end
    return nil
end

t.log(fmt("[probe] ABI=%d caps=0x%02X panel_state=%d",
          M.read_u8(ABI), M.read_u8(CAPS), M.read_u8(PANEL_STATE)))
t.check("the patch reports ABI 3", M.read_u8(ABI) == 3, fmt("got %d", M.read_u8(ABI)))
t.check("it advertises the panel capability", M.read_u8(CAPS) & 0x02 ~= 0,
        fmt("caps=0x%02X", M.read_u8(CAPS)))

-- Open the menu and walk to the last row.
for _ = 1, 40 do t.step(nil) end
t.hold("Start", 8)
for _ = 1, 40 do t.step(nil) end
t.log(fmt("[probe] menu open: watched=0x%02X maxMenu=%d",
          M.read_u8(WATCHED), M.read_u8(0xCC28)))

local last = M.read_u8(0xCC28) - 1
for _ = 1, 12 do
    if M.read_u8(CUR_MENU) == last then break end
    t.hold("Down", 6)
    for _ = 1, 10 do t.step(nil) end
end
t.log(fmt("[probe] cursor at %d (want %d), row: |%s|",
          M.read_u8(CUR_MENU), last, row_text(14)))

-- Press A and watch. Report the FIRST frame anything moves, so a panel that opens and is
-- immediately torn down is distinguishable from one that never opens.
t.hold("A", 8)
local first_state, first_title = nil, nil
for f = 1, 400 do
    t.step(nil)
    if not first_state and M.read_u8(PANEL_STATE) ~= 0 then first_state = f end
    if not first_title and screen_has("SOUL LINK") then first_title = f end
    if f % 40 == 0 then
        t.log(fmt("[probe] f=%3d state=%d watched=0x%02X row2=|%s| row5=|%s|",
                  f, M.read_u8(PANEL_STATE), M.read_u8(WATCHED),
                  row_text(2), row_text(5)))
    end
end
t.log(fmt("[probe] first non-zero panel_state at frame %s", tostring(first_state)))
t.log(fmt("[probe] first 'SOUL LINK' on screen at frame %s", tostring(first_title)))
t.log(fmt("[probe] final screen:"))
for r = 0, 17 do t.log(fmt("[probe]   %2d |%s|", r, row_text(r))) end

t.finish(fmt("state_first=%s title_first=%s", tostring(first_state), tostring(first_title)))
