-- test_live_startmenu_shapes.lua — the SOULLINK row across RR's real START-menu shapes.
--
-- test_live_soullinkmenu.lua only ever saw the pre-Pokedex menu [1 2 3 4 5 6]. RR's SetUpStartMenu
-- (0x090BE178, disassembled in handlers.c) adds POKEDEX (id 0) once FLAG_SYS_POKEDEX_GET (0x829) is
-- set, so every player past Oak's parcel has 7 rows, and the old count==6 splice silently skipped
-- them (duo infopanel_gen3 on rr_battle2: "no SOULLINK row in the START menu (count 7)").
--
-- SYNTH setup (disclosed): the town savestate predates the Pokedex, so the gate sets the flag bits
-- in SaveBlock1.flags itself (pret FR: flags[] at +0xEE0; the profile's SB1_FLAGS_OFFSET). Only the
-- menu build under test runs natively.
--   dex      FLAG_SYS_POKEDEX_GET -> [0 1 2 3 4 5 8 6], and the row still fires its callback
--   safari   + FLAG_SYS_SAFARI_MODE (0x800) -> RR builds the Safari menu; no SOULLINK row
--   disabled enable=0 -> stock 7 rows
--   tools    + 0x91E (RR's DexNav/PC page; a CFRU flag: 0x090B8FB0 maps 0x900..0x18FF to 0x0203B174): the main page ends in EXIT id 11 ("Exit"
--            + the R hint). RIGHT flips to the tools page (no row), LEFT flips back through RR's
--            0x090BE30C rebuild, a DIRECT bl that bypassed the setup wrapper until build.py repointed
--            its callback literal: SOULLINK must be back.
--
--   python tools/run_gate.py lua/tests/test_live_startmenu_shapes.lua --timeout 300
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("startmenu_shapes")

local COUNT, ORDER = 0x020370F5, 0x020370F6   -- sNumStartMenuActions / sStartMenuOrder
local SI = 0x0203FD44                          -- SlinkInfo: +0 enable, +1 opened
local FLAG_POKEDEX, FLAG_SAFARI, FLAG_TOOLS = 0x829, 0x800, 0x91E
local PAGE = 0x0203E054                        -- RR's START page byte (1 = tools)

local function set_flag(flag)
    local a
    if flag >= 0x900 then
        a = 0x0203B174 + ((flag - 0x900) >> 3)          -- CFRU's expanded flag block
    else
        a = memory.read_u32_le(t.ram.SB1_PTR_ADDR) + 0xEE0 + (flag >> 3)
    end
    memory.write_u8(a, memory.read_u8(a) | (1 << (flag & 7)))
end
local function boot(enable, flags)
    t.boot({ state = "slink_overworld.State", beacon = 240 })
    for _, f in ipairs(flags) do set_flag(f) end
    memory.write_u8(SI, enable and 1 or 0)
    memory.write_u8(SI + 1, 0)
end
local function menu()
    t.tap("Start", 90)
    local n, o = memory.read_u8(COUNT), {}
    for i = 0, math.max(n, 1) - 1 do o[#o + 1] = memory.read_u8(ORDER + i) end
    return n, o
end
local function has(o, id) for _, v in ipairs(o) do if v == id then return true end end end
local function str(o) return "[" .. table.concat(o, " ") .. "]" end

-- disabled: the stock with-Pokedex menu (proves the synth flag took: POKEDEX is row 0)
boot(false, { FLAG_POKEDEX })
local n0, o0 = menu()
t.log("dex, disabled: count=" .. n0 .. " order=" .. str(o0))
t.check("the synth Pokedex flag gives RR's 7-row menu with POKEDEX first", n0 == 7 and o0[1] == 0, str(o0))
t.check("enable=0 adds no row", not has(o0, 8))

-- enabled, with the Pokedex: SOULLINK spliced right before EXIT
boot(true, { FLAG_POKEDEX })
local n1, o1 = menu()
t.log("dex, enabled:  count=" .. n1 .. " order=" .. str(o1))
local exit = o0[#o0]
t.check("8 rows with the Pokedex and the feature enabled", n1 == 8, "count=" .. n1)
t.check("SOULLINK sits right before EXIT, which stays last", o1[7] == 8 and o1[8] == exit, str(o1))

-- the row the gate thinks is SOULLINK fires the callback (index 6 on this shape)
boot(true, { FLAG_POKEDEX })
t.tap("Start", 90)
for _ = 1, 6 do t.tap("Down", 12) end
t.tap("A", 60)
t.check("row 6 of the with-Pokedex menu fires slink_startmenu_cb", memory.read_u8(SI + 1) == 1,
        "opened=" .. memory.read_u8(SI + 1))

-- Safari: RR builds its own menu (RETIRE first); the patch must leave it alone
boot(true, { FLAG_POKEDEX, FLAG_SAFARI })
local n2, o2 = menu()
t.log("safari, enabled: count=" .. n2 .. " order=" .. str(o2))
t.check("the synth Safari flag gives RR's Safari menu (RETIRE first)", o2[1] == 7, str(o2))
t.check("no SOULLINK row in the Safari menu", not has(o2, 8), str(o2))

-- the tools page: EXIT becomes id 11, and a page round trip must keep the row
boot(true, { FLAG_POKEDEX, FLAG_TOOLS })
local n3, o3 = menu()
t.log("tools, enabled: count=" .. n3 .. " order=" .. str(o3))
t.check("the synth tools flag gives the main page's EXIT id 11", o3[#o3] == 11, str(o3))
t.check("SOULLINK sits right before EXIT id 11", n3 == 8 and o3[7] == 8, str(o3))
t.tap("Right", 60)
local n4 = memory.read_u8(COUNT)
local o4 = {}
for i = 0, math.max(n4, 1) - 1 do o4[#o4 + 1] = memory.read_u8(ORDER + i) end
t.log("tools page:      page=" .. memory.read_u8(PAGE) .. " count=" .. n4 .. " order=" .. str(o4))
t.check("RIGHT flips to the tools page", memory.read_u8(PAGE) == 1, "page=" .. memory.read_u8(PAGE))
t.check("no SOULLINK row on the tools page", not has(o4, 8), str(o4))
t.tap("Left", 60)
local n5 = memory.read_u8(COUNT)
local o5 = {}
for i = 0, math.max(n5, 1) - 1 do o5[#o5 + 1] = memory.read_u8(ORDER + i) end
t.log("back, main page: page=" .. memory.read_u8(PAGE) .. " count=" .. n5 .. " order=" .. str(o5))
t.check("LEFT flips back to the main page", memory.read_u8(PAGE) == 0, "page=" .. memory.read_u8(PAGE))
t.check("SOULLINK is back after the page round trip", n5 == 8 and o5[7] == 8 and o5[8] == 11, str(o5))
t.finish()
