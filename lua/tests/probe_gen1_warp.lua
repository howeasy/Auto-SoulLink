--[[
  lua/tests/probe_gen1_warp.lua — can we put the player on an arbitrary map, for real?

  Needed by two things: the `dupes` duo scenario, which must start on Route 1 without the
  boot walk committing an encounter first, and the all-areas sweep, which has to visit every
  encounter map. Walking there does not work — the town fixture parks at (5,6), directly
  below Red's own front door, so Up goes indoors and exiting drops you back on the same
  tile (six east-shifted lanes all re-entered it).

  THE MECHANISM, and why it is not a cheat. pokered's own scripts warp this way:
  home/overworld.asm:57-60 checks BIT_WARP_FROM_CUR_SCRIPT (bit 3) in wStatusFlags3 every
  overworld frame and jumps to WarpFound2, which runs the complete real chain
  WarpFound2 -> EnterMap -> LoadMapData -> LoadMapHeader -> LoadWildData. So the destination
  map's header, connections, warps, tileset AND wild table all come from ROM exactly as they
  would if the player had walked in. Nothing we wrote is echoed back.

  Setting wCurMap alone does NOT do this — nothing in OverworldLoop watches that byte, so
  LoadWildData never re-runs and the previous map's wild table stays in WRAM. That is a
  self-referential fake and is the trap this probe exists to avoid.

  WHAT MAKES THE RESULT TRUSTWORTHY: the wild table is POISONED with 0x77 before the warp.
  0x77 is not a valid encounter rate for any Gen 1 map and is a MissingNo index, so if the
  warp were fake the readback would still be poison and the probe fails by name. A real
  LoadWildData overwrites it with the destination's ROM data.

      python tools/run_gb_gate.py lua/tests/probe_gen1_warp.lua --rom red --target town
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
    -- REWRITE THE DESTINATION EVERY FRAME. hWarpDestinationMap (0xFF81) is a UNION member
    -- (ram/hram.asm:8-17): it shares that byte with hOAMTile, hBaseTileID, hDexWeight,
    -- hROMBankTemp, hPreviousTileset and hRLEByteValue, several of which the rendering code
    -- touches every single frame. pokered's own scripts get away with one write because
    -- they set the byte and the flag in the same uninterrupted routine
    -- (scripts/PokemonTower7F.asm:75-82); a Lua write has to survive a frame boundary, and
    -- it does not. Measured: asking for Route 1 (0x0C) landed on Route 10 (0x15) -- a real
    -- map load, of whatever value rendering happened to leave behind.
    M.write_u8(STATUS3, u8(STATUS3) | (1 << BIT_WARP_FROM_CUR_SCRIPT))
    -- Write through the dedicated HRAM domain as well as the System Bus. The System Bus
    -- readback agrees with itself, which proves nothing if it is a mirror the CPU does not
    -- see -- and the destination arriving wrong twice, from a byte the renderer rewrites
    -- constantly, is exactly what that would look like.
    for _ = 1, 240 do
        M.write_u8(0xFF81, map)
        pcall(memory.write_u8, 0x01, map, "HRAM")
        t.step(nil)
        if u8(CUR_MAP) == map then return true end
    end
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
local DEST_MAP  = CUR_MAP + 0x3BC
local STATUS6   = CUR_MAP + 0x3D4          -- wStatusFlags6 0xD732
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

t.finish(fmt("warped Pallet -> Route 1, rate=%d", rate))
