--[[
  lua/tests/probe_gen1_safestate.lua — WHICH byte actually means "nothing else owns the game"?

  The Gen 1 counterpart of probe_gen2_safestate.lua, and it exists for the same reason: the
  Gen 2 bring-up refused to accept a named-sounding address without measuring it, and found
  that the obvious candidate (wJoypadDisable) reads 00 both in the overworld AND with a menu
  open — it would have looked like a fix while changing nothing.

  Gen 1 never got that treatment. `M.isInOverworld()` gates EVERY deferred write —
  box_mon, party_mon, memorialize — on wJoyIgnore and wFontLoaded, and those were chosen by
  name. The repo's own writes gate admits the doubt out loud
  (lua/tests/test_gen1_writes_gate.lua:27-36): "Opening the START menu from a freshly loaded
  battery save proved unreliable to stage here (wFontLoaded stayed 0x00 through a dozen held
  Start presses)". A predicate that does not move when a menu opens is not a predicate.

  The hazard is concrete. If the gate reads "safe" while the PC box UI is up, a box_mon lands
  while Bill's PC holds its own WRAM copy of the box and writes it back over us.

  CANDIDATE THAT THE ORIGINAL CHOICE MISSED: hAutoBGTransferEnabled ($FFBA). pokered's own
  comment at home/vcopy.asm:120-126 says the transfer "is turned off when walking around the
  map, but is turned on when talking to sprites, battling, using menus, etc." — which is
  almost a definition of the thing isInOverworld() is trying to express.

      python tools/run_gb_gate.py lua/tests/probe_gen1_safestate.lua --rom red --target town

  Not a gate: it measures and prints a table. Its output is the evidence.
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("probe_gen1_safestate")
local M = t.M
local fmt = string.format

-- Everything profile-derived where a profile field exists, so Yellow's -1 shift follows.
-- hAutoBGTransferEnabled and the menu bytes are HRAM/low-WRAM and are NOT shifted.
local CAND = {
    {name = "wJoyIgnore",              addr = M.JOY_IGNORE_ADDR},
    {name = "wFontLoaded",             addr = M.FONT_LOADED_ADDR},
    {name = "hAutoBGTransferEnabled",  addr = 0xFFBA},
    {name = "wCurrentMenuItem",        addr = 0xCC26},
    {name = "wMaxMenuItem",            addr = 0xCC28},
    {name = "wMenuWatchedKeys",        addr = 0xCC29},
    {name = "wIsInBattle",             addr = M.BATTLE_FLAG_ADDR},
}

local function sample()
    local out = {}
    for i, c in ipairs(CAND) do
        out[i] = c.addr and M.read_u8(c.addr) or -1
    end
    return out
end

local rows = {}
local function record(state)
    rows[#rows + 1] = {state = state, vals = sample(), safe = M.isInOverworld()}
    local v = {}
    for i, c in ipairs(CAND) do
        v[#v + 1] = fmt("%s=%02X", c.name, rows[#rows].vals[i])
    end
    t.log(fmt("  %-22s isInOverworld=%-5s  %s",
              state, tostring(rows[#rows].safe), table.concat(v, " ")))
end

local function press(btn, hold_frames, settle)
    t.hold(btn, hold_frames or 10)
    for _ = 1, (settle or 24) do t.step(nil) end
end

t.log("[probe] candidate values per state:")

-- 1. Plain overworld, nothing pressed. The one state where a deferred write IS safe.
for _ = 1, 30 do t.step(nil) end
record("overworld idle")

-- 2. Mid-step. Walking is still the overworld, but the engine is busy moving the player;
--    a predicate that flips here would stall every write behind the player standing still.
t.hold("Right", 6)
record("overworld walking")
for _ = 1, 40 do t.step(nil) end

-- 3. START menu open. THE case the writes gate could not stage. If wFontLoaded does not
--    move here, it cannot be what gates a box write.
press("Start", 8, 40)
record("START menu open")

-- Confirm we really opened it rather than measuring a no-op: the menu box drives
-- wMaxMenuItem to the item count (6 or 7 depending on the Pokedex), and the overworld
-- leaves it at whatever the last menu set. wMenuWatchedKeys is the stronger tell — the
-- start menu sets it to PAD_DOWN|PAD_UP|PAD_START|PAD_B|PAD_A = 0xCB.
local watched = M.read_u8(0xCC29)
t.check("the START menu actually opened (wMenuWatchedKeys == 0xCB)", watched == 0xCB,
        fmt("got 0x%02X — every 'menu open' row below is suspect if this failed", watched))

-- 4. Still open, one frame later, to catch a transient.
for _ = 1, 30 do t.step(nil) end
record("START menu settled")

-- 5. Close it and confirm we return to the overworld reading.
press("B", 8, 40)
record("menu closed")

-- ── verdict ──────────────────────────────────────────────────────────────────
-- A usable predicate must be CONSTANT across the two overworld rows and DIFFERENT in both
-- menu rows. Anything that fails either half is not a safe-state gate, whatever it is named.
local idle, walking, open1, open2, closed = rows[1], rows[2], rows[3], rows[4], rows[5]
t.log("[probe] verdict per candidate:")
for i, c in ipairs(CAND) do
    local ok_overworld = (idle.vals[i] == walking.vals[i]) and (idle.vals[i] == closed.vals[i])
    local ok_menu = (open1.vals[i] ~= idle.vals[i]) and (open2.vals[i] ~= idle.vals[i])
    local verdict
    if c.addr == nil then
        verdict = "ABSENT from this profile"
    elseif ok_overworld and ok_menu then
        verdict = "DISCRIMINATES (stable in overworld, differs with the menu up)"
    elseif not ok_menu then
        verdict = "USELESS — does not move when the menu opens"
    else
        verdict = "UNSTABLE — changes within the overworld itself"
    end
    t.log(fmt("  %-24s %s", c.name, verdict))
end

-- The production gate's own answer, which is the thing under test.
t.log(fmt("[probe] M.isInOverworld(): idle=%s walking=%s menu_open=%s menu_settled=%s closed=%s",
          tostring(idle.safe), tostring(walking.safe), tostring(open1.safe),
          tostring(open2.safe), tostring(closed.safe)))
t.check("isInOverworld() is true in the plain overworld", idle.safe == true)
t.check("isInOverworld() is FALSE with the START menu open", open2.safe == false,
        "this is the claim the writes gate could never stage; a false here means a "
        .. "deferred box write can land while a menu owns the data")

t.finish("measured")
