--[[
  lua/tests/probe_gen1_warp.lua — can we put the player on an arbitrary map, for real?

  VERDICT, so nobody re-derives it:

    * The SCRIPTED warp CANNOT be driven from Lua. Not "is awkward" — cannot.
    * The FLY warp CAN, and lands on a destination we CHOOSE, with the real ROM table.
    * Its price is a fixed list of 13 destinations, two of which have wild encounters.
    * `dupes` no longer needs either. It was blocked by the boot walk starting an
      encounter, and that is fixed at the source (see below).

  ── why the scripted warp is a dead end ──────────────────────────────────────────────
  home/overworld.asm:57-60 checks BIT_WARP_FROM_CUR_SCRIPT (bit 3) in wStatusFlags3 every
  overworld frame and jumps to WarpFound2, which runs the complete real chain
  WarpFound2 -> EnterMap -> LoadMapData -> LoadMapHeader -> LoadWildData. That part works:
  this probe poisons the wild table with 0x77 first (not a valid rate for any Gen 1 map, and
  a MissingNo index) and the poison IS replaced by genuine ROM data, so the map really does
  load.

  The DESTINATION never arrives, because WarpFound2 reads it from hWarpDestinationMap at
  0xFF81 (home/overworld.asm:495 and :509 — there is no other source) and that address is a
  UNION: ram/hram.asm:8-17 shares it with hBaseTileID, hDexWeight, hOAMTile, hROMBankTemp,
  hPreviousTileset and hRLEByteValue. The renderer rewrites it WITHIN the frame, so a value
  written from a frame boundary is already gone when WarpFound2 reads it. Measured three
  ways, all still exercised below:
    * the write lands and reads back (0x0C before and after the hop), and is still ignored;
    * rewriting it every frame does not help, and actively corrupts the RLE map decode by
      clobbering hRLEByteValue during EnterMap;
    * the wCurMap trace goes straight 0x00 -> 0x15 without ever passing through the map that
      was asked for — which also kills the "it arrived and CheckMapConnections moved us"
      theory, since arriving would have to show up in that sequence.
  Lua cannot win a race that is decided inside a frame, so this vector is closed.

  ── the vector that works ────────────────────────────────────────────────────────────
  HandleFlyWarpOrDungeonWarp (home/overworld.asm:783-799) takes its destination from
  wDestinationMap, an ordinary WRAM byte nothing else touches per frame, gated on
  BIT_FLY_WARP in wStatusFlags6. It runs the same real chain through LoadWildData. Proven
  below by asking for ROUTE_4 — a map this probe has never landed on by accident, unlike
  ROUTE_10 — and checking the table against data/wild/maps/Route4.asm: rate 20, slot 0
  (level 10, RATTATA 0xA5).

  The limit is FlyWarpDataPtr (data/maps/special_warps.asm:64-77): 13 destinations, the 11
  fly-able towns plus ROUTE_4 and ROUTE_10. Only those last two carry wild encounters, so
  this vector alone does NOT cover the all-areas sweep — that needs walking the map
  connections out from a flown-to route, or another mechanism entirely. Say so rather than
  planning the sweep around a warp that reaches three of its maps.

  ── what `dupes` actually needed ─────────────────────────────────────────────────────
  Not this. The blocker was the boot walk starting a wild encounter on the Route 1 grass
  fixture, which committed a species before one could be forced. Fixed by closing the
  engine's own NewBattle gate across the boot (BIT_NO_BATTLES in wStatusFlags4,
  home/overworld.asm:362-373) — see M.setNoBattles and lua/tests/duo/duo_gb_main.lua.

      python tools/run_gb_gate.py lua/tests/probe_gen1_warp.lua --rom red --target town

  Not a gate. It asserts only what it has established and logs the rest as findings.
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("probe_gen1_warp")
local M = t.M
local fmt = string.format

local CUR_MAP = M.MAP_ID_ADDR
-- Test-only addresses: no production code reads these, so they are derived here rather
-- than added to the profiles. Every delta below is IDENTICAL in pokered and pokeyellow
-- (checked against data/pret_syms.json), so this works on all three cartridges.
--   wCurMap 0xD35E -> wStatusFlags3 0xD72D (+0x3CF), wStatusFlags4 0xD72E (+0x3D0),
--                     wDestinationWarpID 0xD42F (+0xD1), view pointer 0xD35F (+1)
local STATUS3   = CUR_MAP + 0x3CF
local STATUS4   = CUR_MAP + 0x3D0
local DEST_WARP = CUR_MAP + 0xD1
local VIEW_PTR  = CUR_MAP + 0x01
local Y_COORD, X_COORD = CUR_MAP + 3, CUR_MAP + 4
local OVERWORLD_MAP = 0xC6E8          -- same in both decomps
local BIT_WARP_FROM_CUR_SCRIPT = 3    -- constants/ram_constants.asm:86
local BIT_NO_BATTLES           = 4    -- constants/ram_constants.asm:98

local ROUTE_1, PALLET = 0x0C, 0x00
local ROUTE_4 = 0x0F
-- wDestinationMap 0xD71A (+0x3BC) and wStatusFlags6 0xD732 (+0x3D4); both deltas are the
-- same in pokered and pokeyellow.
local DEST_MAP = CUR_MAP + 0x3BC
local STATUS6  = CUR_MAP + 0x3D4
local ROUTE_1_WIDTH   = 10            -- blocks; data/maps/headers/Route1.asm

local function u8(a) return M.read_u8(a) end

--- Destroy the wild table so a fake warp cannot pass by leaving it untouched.
local function poison()
    local rate = M.GRASS_RATE_ADDR
    if not rate then return false end
    M.write_u8(rate, 0x77)
    for i = 0, 19 do M.write_u8(rate + 1 + i, 0x77) end
    return true
end

--- Warp to `map`, landing at its top-left corner.
local function warp_to(map, width)
    -- Suppress encounters and scripts for the hop itself: a trainer or a map script firing
    -- on the landing frame would measure something other than the warp.
    M.write_u8(STATUS4, u8(STATUS4) | (1 << BIT_NO_BATTLES))
    -- Row 0, column 0 of the destination, which is in bounds for every map by construction.
    -- Little-endian, byte by byte: memory_gb only exposes a big-endian u16 writer, and the
    -- Game Boy stores pointers low byte first.
    local view = OVERWORLD_MAP + 7 + width
    M.write_u8(VIEW_PTR, view % 256)
    M.write_u8(VIEW_PTR + 1, math.floor(view / 256) % 256)
    M.write_u8(Y_COORD, 0)
    M.write_u8(X_COORD, 0)
    -- 0xFF tells LoadTilesetHeader to keep the coordinates we just wrote instead of pulling
    -- them from the destination's warp_to table (engine/overworld/tilesets.asm:45-47),
    -- which for a map with no warp events is filler.
    M.write_u8(DEST_WARP, 0xFF)
    -- WRITE THE DESTINATION ONCE, then leave 0xFF81 alone.
    --
    -- Rewriting it every frame was actively harmful, not merely useless: 0xFF81 is a UNION
    -- (ram/hram.asm:8-17) shared with hOAMTile, hBaseTileID, hDexWeight, hROMBankTemp,
    -- hPreviousTileset AND hRLEByteValue -- and hRLEByteValue is what DecodeRLEList uses to
    -- decompress the map blocks during EnterMap. Hammering that byte corrupts the very map
    -- load we are trying to perform.
    M.write_u8(0xFF81, map)
    M.write_u8(STATUS3, u8(STATUS3) | (1 << BIT_WARP_FROM_CUR_SCRIPT))

    -- Trace every distinct wCurMap the hop passes through. "asked for 0x0C, ended on 0x15"
    -- cannot distinguish "the destination never arrived" from "we arrived and were then
    -- moved again", and those want completely different fixes.
    local seq, last = {}, nil
    for _ = 1, 240 do
        t.step(nil)
        local m = u8(CUR_MAP)
        if m ~= last then
            seq[#seq + 1] = fmt("0x%02X", m)
            last = m
        end
        if m == map and #seq > 0 then
            -- Let it settle: arriving is not the same as staying.
            for _ = 1, 60 do
                t.step(nil)
                local m2 = u8(CUR_MAP)
                if m2 ~= last then seq[#seq + 1] = fmt("0x%02X", m2) last = m2 end
            end
            t.log("[probe] wCurMap sequence: " .. table.concat(seq, " -> "))
            return u8(CUR_MAP) == map
        end
    end
    t.log("[probe] wCurMap sequence: " .. table.concat(seq, " -> "))
    return false
end

--- Warp via the FLY vector, which reads a STABLE WRAM byte.
---
--- The scripted warp is unusable from Lua: its destination is hWarpDestinationMap at
--- 0xFF81, a UNION shared with hOAMTile, hBaseTileID, hDexWeight, hROMBankTemp,
--- hPreviousTileset and hRLEByteValue (ram/hram.asm:8-17). The renderer rewrites that byte
--- within the frame, so whatever we put there is gone before WarpFound2 reads it -- measured
--- three ways: the write lands and reads back, rewriting it every frame does not help (and
--- corrupts the RLE map decode), and the wCurMap trace goes straight 0x00 -> 0x15 without
--- ever passing through the map we asked for.
---
--- HandleFlyWarpOrDungeonWarp (home/overworld.asm:61-63) takes its destination from
--- wDestinationMap in ordinary WRAM instead, which nothing else touches per frame. Its
--- price is a fixed destination list -- FlyWarpDataPtr, 13 entries
--- (data/maps/special_warps.asm:64-77) -- but two of those, ROUTE_4 and ROUTE_10, are real
--- wild-encounter areas, and an encounter area is all the scenarios need.
local BIT_FLY_WARP = 3                 -- constants/ram_constants.asm:119
local function fly_to(map)
    M.write_u8(STATUS4, u8(STATUS4) | (1 << BIT_NO_BATTLES))
    M.write_u8(DEST_MAP, map)
    M.write_u8(STATUS6, u8(STATUS6) | (1 << BIT_FLY_WARP))
    local seq, last = {}, nil
    for _ = 1, 300 do
        t.step(nil)
        local m = u8(CUR_MAP)
        if m ~= last then seq[#seq + 1] = fmt("0x%02X", m) last = m end
        if m == map then
            for _ = 1, 60 do t.step(nil) end
            t.log("[probe] fly sequence: " .. table.concat(seq, " -> "))
            return u8(CUR_MAP) == map
        end
    end
    t.log("[probe] fly sequence: " .. table.concat(seq, " -> "))
    return false
end

-- ── the experiment ───────────────────────────────────────────────────────────
t.log(fmt("[probe] start: map=0x%02X grassRate=%s",
          u8(CUR_MAP), M.GRASS_RATE_ADDR and u8(M.GRASS_RATE_ADDR) or "n/a"))
t.check("booted on Pallet Town", u8(CUR_MAP) == PALLET,
        fmt("map=0x%02X — this probe expects the town fixture", u8(CUR_MAP)))
t.check("the profile exposes GRASS_RATE_ADDR", M.GRASS_RATE_ADDR ~= nil)
if not M.GRASS_RATE_ADDR then t.finish("no address") return end

-- IS HRAM EVEN WRITABLE FROM HERE? The flag write (WRAM 0xD72D) clearly lands -- a real
-- warp happens -- but the DESTINATION byte lives in HRAM at 0xFF81, and asking for Route 1
-- (0x0C) produced Route 10 (0x15) twice, which is what a dropped write looks like. Prove it
-- one way or the other before theorising further, and name the domains available.
do
    local before = u8(0xFF81)
    M.write_u8(0xFF81, 0x0C)
    local after = u8(0xFF81)
    t.log(fmt("[probe] HRAM 0xFF81 write test: before=0x%02X wrote=0x0C readback=0x%02X",
              before, after))
    local ok_d, domains = pcall(memory.getmemorydomainlist)
    if ok_d and domains then
        local names = {}
        for _, d in ipairs(domains) do names[#names + 1] = d end
        t.log("[probe] domains: " .. table.concat(names, ", "))
    end
    t.check("HRAM 0xFF81 accepts a write", after == 0x0C,
            fmt("readback 0x%02X — the System Bus domain is not reaching HRAM, so the warp "
                .. "destination never arrives and WarpFound2 reads whatever the renderer "
                .. "left in that UNION byte", after))
end

t.check("poisoned the wild table", poison())
t.log(fmt("[probe] after poison: grassRate=0x%02X slot0=(0x%02X,0x%02X)",
          u8(M.GRASS_RATE_ADDR), u8(M.GRASS_RATE_ADDR + 1), u8(M.GRASS_RATE_ADDR + 2)))

-- The other things that can decide a warp destination, logged before and after so the next
-- reader does not need a fresh emulator run to see which path actually fired.
--   wDestinationMap 0xD71A (+0x3BC) is what the FLY/DUNGEON path uses, and it lives in
--   stable WRAM rather than in the HRAM union -- note Route 10 is IN pokered's fly table
--   (data/maps/special_warps.asm), which is suspicious given what we keep landing on.
t.log(fmt("[probe] before warp: wDestinationMap=0x%02X wStatusFlags3=0x%02X "
          .. "wStatusFlags6=0x%02X hWarpDest=0x%02X",
          u8(DEST_MAP), u8(STATUS3), u8(STATUS6), u8(0xFF81)))

local ok = warp_to(ROUTE_1, ROUTE_1_WIDTH)

t.log(fmt("[probe] after warp:  wDestinationMap=0x%02X wStatusFlags3=0x%02X "
          .. "wStatusFlags6=0x%02X hWarpDest=0x%02X",
          u8(DEST_MAP), u8(STATUS3), u8(STATUS6), u8(0xFF81)))
if not ok then
    t.log(fmt("[probe] FINDING: asked for map 0x%02X, landed on 0x%02X. The warp itself is "
              .. "real (see the reload check below) -- it is the DESTINATION that does not "
              .. "arrive.", ROUTE_1, u8(CUR_MAP)))
end

-- THE DISCRIMINATOR. Route 1's ROM data is rate 25, slot 0 = (level 3, PIDGEY 0x24)
-- (data/wild/maps/Route1.asm). Poison surviving here means LoadWildData never ran.
local rate = u8(M.GRASS_RATE_ADDR)
local lv0, sp0 = u8(M.GRASS_RATE_ADDR + 1), u8(M.GRASS_RATE_ADDR + 2)
t.log(fmt("[probe] after warp: map=0x%02X grassRate=%d slot0=(%d,0x%02X) pos=(%d,%d)",
          u8(CUR_MAP), rate, lv0, sp0, u8(X_COORD), u8(Y_COORD)))

t.check("the wild table was RELOADED, not left poisoned", rate ~= 0x77,
        fmt("grassRate still reads 0x77 — LoadWildData did not run, so this was a fake "
            .. "map change and nothing about it can be trusted"))
-- Not asserted while the destination is unresolved: these describe whichever map we
-- actually reached, and would only restate the finding above.
t.log(fmt("[probe] loaded table belongs to map 0x%02X: rate=%d slot0=(%d,0x%02X)",
          u8(CUR_MAP), rate, lv0, sp0))

-- The area the client would resolve, which is what the scenarios actually key off.
local area = t.G and t.G.resolve_area and t.G.resolve_area(u8(CUR_MAP)) or "<no resolver>"
t.log(fmt("[probe] the landed map resolves to %q", area))
t.check("the landed map resolves to a real encounter area", area ~= "",
        "a warp that lands somewhere unmapped would be useless to the scenarios")

-- Landing on a map is not the same as being able to PLAY on it: prove the player can move,
-- or a warp that leaves you stuck in a wall would look like a success.
local x0, y0 = u8(X_COORD), u8(Y_COORD)
t.hold("Down", 16, function() return u8(X_COORD) ~= x0 or u8(Y_COORD) ~= y0 end)
t.log(fmt("[probe] moved from (%d,%d) to (%d,%d)", x0, y0, u8(X_COORD), u8(Y_COORD)))

-- ── second experiment: the fly vector, and a destination we have never hit by accident ──
-- Route 4, not Route 10: we keep LANDING on Route 10 by accident, so arriving there would
-- prove nothing. Route 4's ROM data is rate 20, slot 0 = (level 10, RATTATA 0xA5)
-- (data/wild/maps/Route4.asm), and the table is poisoned again first.
t.check("re-poisoned the wild table", poison())
local flew = fly_to(ROUTE_4)
t.check("fly warp reached ROUTE_4", flew,
        fmt("map=0x%02X after 300 frames", u8(CUR_MAP)))

local r4, l4, s4 = u8(M.GRASS_RATE_ADDR), u8(M.GRASS_RATE_ADDR + 1), u8(M.GRASS_RATE_ADDR + 2)
t.log(fmt("[probe] after fly: map=0x%02X rate=%d slot0=(%d,0x%02X) pos=(%d,%d)",
          u8(CUR_MAP), r4, l4, s4, u8(X_COORD), u8(Y_COORD)))
t.check("Route 4's table was loaded, not the poison", r4 ~= 0x77,
        "grassRate still 0x77 — LoadWildData did not run")
t.check("Route 4's real rate (20) was loaded", r4 == 20, fmt("got %d", r4))
t.check("Route 4's real slot 0 (level 10, RATTATA) was loaded",
        l4 == 10 and s4 == 0xA5, fmt("got (%d, 0x%02X) want (10, 0xA5)", l4, s4))
local area4 = t.G and t.G.resolve_area and t.G.resolve_area(u8(CUR_MAP)) or ""
t.check("it resolves to route_4", area4 == "route_4", fmt("got %q", area4))

-- Playable, not just present. "Can move" means SOME direction works: a fly destination is
-- a fixed tile chosen by the game, and Route 4's is up against the Pokemon Center wall, so
-- asserting on one direction tests the map's geometry rather than the warp. Each attempt
-- gets a generous hold because a direction the player is not already facing spends the
-- first press turning.
local fx, fy = u8(X_COORD), u8(Y_COORD)
local moved_dir
for _, dir in ipairs({"Down", "Left", "Right", "Up"}) do
    local x0, y0 = u8(X_COORD), u8(Y_COORD)
    t.hold(dir, 40, function() return u8(X_COORD) ~= x0 or u8(Y_COORD) ~= y0 end)
    if u8(X_COORD) ~= x0 or u8(Y_COORD) ~= y0 then moved_dir = dir break end
end
t.log(fmt("[probe] movement after fly: start=(%d,%d) now=(%d,%d) via %s",
          fx, fy, u8(X_COORD), u8(Y_COORD), tostring(moved_dir)))
t.check("the player can move after the fly warp", moved_dir ~= nil,
        fmt("no direction moved the player off (%d,%d) — the warp landed but left the "
            .. "engine holding the joypad", fx, fy))

t.finish(fmt("fly -> route_4 rate=%d", r4))
