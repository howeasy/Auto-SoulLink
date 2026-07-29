--[[
  probe_gen2_safestate.lua — which Crystal address means "it is safe to write RAM"?

  The Gen 2 client gates deferred writes on `not in_battle`. Gen 1 learned that is far too
  permissive: it is also true in the PC box UI, the party menu and the naming screen, where
  the open UI holds its own copy of the data and writes it back over ours. Gen 1 gates on
  isInOverworld(), which additionally requires wJoyIgnore == 0 and wFontLoaded bit 0 clear.

  Crystal has no wFontLoaded, and its wTextboxFlags is text-SPEED configuration
  (FAST_TEXT_DELAY_F / TEXT_DELAY_F), not "a box is open" — so the obvious-looking name is
  the wrong signal, and picking it by name is how this gets silently wrong.

  So measure. Sample every candidate in three states the fixture can actually reach:

      A. plain overworld, player free to walk
      B. START menu open  (the stand-in for every full-screen UI: PACK, party, PC)
      C. overworld again, menu closed

  A predicate is usable only if it DIFFERS between A and B and returns in C. Anything equal
  in all three is useless no matter how promising its name.

  Candidates, with what pret says they are:
    wBattleMode      0xD22D  0 = not in battle
    wJoypadDisable   0xCFBE  nonzero while something else owns the pad (Gen 1's wJoyIgnore)
    wTextboxFlags    0xCFCF  text-speed bits — expected to be a red herring
    wMapEventStatus  0xD433  MAPEVENTS_ON(0) / MAPEVENTS_OFF(1)
    wScriptRunning   0xD438  nonzero while a map script runs
    wMenuSelection   0xCF74  last-highlighted START menu item id

  Result file: patch/build/probe_gen2_safestate_result.txt
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gatelib.lua")
local t = G.start("probe_gen2_safestate", {game = "gen2_crystal"})
local M = t.M
local fmt = string.format

local ADDR = {
    {"wBattleMode", 0xD22D},
    {"wJoypadDisable", 0xCFBE},
    {"wTextboxFlags", 0xCFCF},
    {"wMapEventStatus", 0xD433},
    {"wScriptRunning", 0xD438},
    {"wMenuSelection", 0xCF74},
}

local function sample()
    local out = {}
    for _, a in ipairs(ADDR) do out[a[1]] = M.read_u8(a[2]) end
    return out
end

--- Can the player walk RIGHT NOW? The only assertion about screen state that cannot be
--- faked by WRAM contents — and the CONTINUE preview loads save data into the very WRAM the
--- party and coordinates live in, so every cheaper check agrees with a live game.
local function walkable()
    local x0, y0 = M.read_u8(t.x_addr), M.read_u8(t.y_addr)
    t.hold("Left", 20, function()
        return M.read_u8(t.x_addr) ~= x0 or M.read_u8(t.y_addr) ~= y0
    end)
    local moved = (M.read_u8(t.x_addr) ~= x0 or M.read_u8(t.y_addr) ~= y0)
    if moved then t.hold("Right", 20, nil) end     -- walk back
    return moved
end

local function show(label, s)
    local parts = {}
    for _, a in ipairs(ADDR) do parts[#parts + 1] = fmt("%s=%02X", a[1], s[a[1]]) end
    client.screenshot(t.ROOT .. "/patch/build/probe_gen2_safestate_" .. label .. ".png")
    t.log(fmt("  [%-10s f=%5d] %s  isInOverworld=%s pos=(%d,%d)", label, t.frame,
              table.concat(parts, " "), tostring(M.isInOverworld()),
              M.read_u8(t.x_addr), M.read_u8(t.y_addr)))
end

-- A. Plain overworld. Re-prove walkability HERE rather than trusting the boot: if the
-- emulator is sitting on the CONTINUE preview, every RAM read below describes the save file
-- instead of a running game, and the whole probe is measuring nothing.
local A = sample()
show("overworld", A)
t.check("the player can actually walk at sample A", walkable(),
        "the emulator is not in a live overworld, so B and C measure nothing")

-- B. START menu. Proven live by requiring the cursor to MOVE — wMenuSelection keeps its last
-- value after the menu closes, so a nonzero read is not evidence a menu is up.
local opened = false
for _ = 1, 15 do
    t.hold("Start", 10)
    for _ = 1, 24 do t.step(nil) end
    local before = M.read_u8(0xCF74)
    t.hold("Down", 6)
    for _ = 1, 10 do t.step(nil) end
    if M.read_u8(0xCF74) ~= before then opened = true break end
end
t.check("the START menu could be opened (otherwise B proves nothing)", opened)
local B = sample()
show("startmenu", B)
client.screenshot(t.ROOT .. "/patch/build/probe_gen2_safestate_menu.png")

-- C. Close it and confirm the state returns.
for _ = 1, 8 do
    t.hold("B", 6)
    for _ = 1, 20 do t.step(nil) end
end
local C = sample()
show("closed", C)

-- Verdict per candidate.
t.log("")
t.log("  candidate         A(over)  B(menu)  C(over)   usable?")
local usable = {}
for _, a in ipairs(ADDR) do
    local n = a[1]
    local differs = (A[n] ~= B[n])
    local returns = (C[n] == A[n])
    local ok = differs and returns
    if ok then usable[#usable + 1] = n end
    t.log(fmt("  %-16s  %02X       %02X       %02X        %s", n, A[n], B[n], C[n],
              ok and "YES" or (differs and "differs but does not return"
                               or "no — same in the overworld and the menu")))
end
t.log("")
t.check("at least one address distinguishes an open menu from the overworld",
        #usable > 0,
        "if this fails, the Gen 2 client has no safe-state predicate to gate writes on and "
        .. "`not in_battle` is the best available — which is what Gen 1 proved insufficient")
t.log("  USABLE: " .. (next(usable) and table.concat(usable, ", ") or "(none)"))

t.finish(fmt("variant=%s usable=%d", t.variant, #usable))
