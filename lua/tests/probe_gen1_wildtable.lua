--[[
  probe_gen1_wildtable.lua — is wGrassMons where we think it is?

  The dead-zone and species-clause scenarios force the wild table so both instances meet a
  chosen species. The write lands (a readback confirms it) and the encounter still produces
  Route 1's real slot 0. That is the signature of a wrong address agreeing with itself: the
  write and the readback use the same expression, so they concur whether or not the game
  reads those bytes.

  So verify against something the GAME put there, not something we wrote. Route 1's ROM data
  (data/wild/maps/Route1.asm) is:
      def_grass_wildmons 25      ; encounter rate
      db  3, PIDGEY              ; slot 0
      db  3, RATTATA             ; slot 1
      db  3, RATTATA
      db  2, RATTATA
      db  2, PIDGEY
      db  3, PIDGEY
  If wGrassRate reads 25 and slot 0 reads (3, PIDGEY), the address is right and the problem is
  timing. If it does not, the address is wrong and every "the write took" readback is worthless.

  Run against the BATTLE fixture (Route 1).
  Result file: patch/build/probe_gen1_wildtable_result.txt
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("probe_gen1_wildtable")
local M = t.M
local fmt = string.format

local PIDGEY, RATTATA, MAGIKARP = 0x24, 0xA5, 0x85
local rate_addr = M.GRASS_RATE_ADDR
local mons_addr = rate_addr and (rate_addr + 1)

t.check("the profile exposes GRASS_RATE_ADDR", rate_addr ~= nil,
        fmt("variant=%s", t.variant))
if not rate_addr then t.finish("no address") return end

t.log(fmt("wGrassRate=%#06x wGrassMons=%#06x map=0x%02X",
          rate_addr, mons_addr, M.read_u8(M.MAP_ID_ADDR)))

-- 1. The rate byte the GAME loaded. Route 1 is 25.
local rate = M.read_u8(rate_addr)
t.check("wGrassRate reads Route 1's ROM value (25)", rate == 25,
        fmt("got %d — if this is wrong, the address is wrong and every readback lies", rate))

-- 2. The slot table the GAME loaded, dumped so a wrong stride is visible too.
local dump = {}
for slot = 0, 9 do
    dump[#dump + 1] = fmt("%d:(%d,0x%02X)", slot,
                          M.read_u8(mons_addr + slot * 2),
                          M.read_u8(mons_addr + slot * 2 + 1))
end
t.log("slots " .. table.concat(dump, " "))

t.check("slot 0 is Route 1's (level 3, PIDGEY)",
        M.read_u8(mons_addr) == 3 and M.read_u8(mons_addr + 1) == PIDGEY,
        fmt("got (%d, 0x%02X) want (3, 0x%02X)",
            M.read_u8(mons_addr), M.read_u8(mons_addr + 1), PIDGEY))
t.check("slot 1 is Route 1's (level 3, RATTATA)",
        M.read_u8(mons_addr + 2) == 3 and M.read_u8(mons_addr + 3) == RATTATA,
        fmt("got (%d, 0x%02X) want (3, 0x%02X)",
            M.read_u8(mons_addr + 2), M.read_u8(mons_addr + 3), RATTATA))

-- 3. Now force it, and walk until an encounter. This is the real question: does a write the
--    game can see actually change what we meet?
for slot = 0, 9 do
    M.write_u8(mons_addr + slot * 2, 5)
    M.write_u8(mons_addr + slot * 2 + 1, MAGIKARP)
end
t.check("the forced table reads back as MAGIKARP", M.read_u8(mons_addr + 1) == MAGIKARP,
        fmt("got 0x%02X", M.read_u8(mons_addr + 1)))

local IN_BATTLE = M.BATTLE_FLAG_ADDR
local ENEMY_SP  = M.ENEMY_MON_SPECIES_ADDR
local entered = false
for i = 1, 400 do
    t.hold(({"Left", "Right"})[(i % 2) + 1], 12,
           function() return M.read_u8(IN_BATTLE) ~= 0 end)
    if M.read_u8(IN_BATTLE) ~= 0 then entered = true break end
end
t.check("an encounter happened", entered, fmt("in_battle=%d", M.read_u8(IN_BATTLE)))

if entered then
    local met = M.read_u8(ENEMY_SP)
    t.log(fmt("met 0x%02X; table now reads slot0=(%d,0x%02X) rate=%d",
              met, M.read_u8(mons_addr), M.read_u8(mons_addr + 1), M.read_u8(rate_addr)))
    t.check("the forced species is what we actually met", met == MAGIKARP,
            fmt("met 0x%02X, forced 0x%02X — if the table still reads MAGIKARP here, the "
                .. "game is not reading these bytes; if it reads PIDGEY again, something "
                .. "reloaded it between the write and the encounter", met, MAGIKARP))
end

t.finish(fmt("variant=%s", t.variant))
