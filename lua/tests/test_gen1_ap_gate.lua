--[[
  lua/tests/test_gen1_ap_gate.lua — headless: does SLink read an ARCHIPELAGO cartridge?

  The Archipelago builds (red_ap / blue_ap) had never been launched under an emulator. Their
  whole profile rested on static symbol matching: `alchav_pokered` in data/pret_syms.json
  says wCurMap moved +216, so lua/games/gen1_rby.lua says 0xD436. Nothing had ever checked
  that against a ROM a player could actually load, and two of the links in that chain are
  exactly the kind that pass every static check and are still wrong:

    * variant detection reads the SEED SLOT through BizHawk's "ROM" domain. That domain is
      flat FILE offsets, while 0x5F22 on the System Bus is a window onto whichever bank is
      mapped right now. An earlier version read CPU 0xFFDB — HRAM, nonzero during normal
      play — so every vanilla cartridge eventually self-identified as AP. No unit test can
      see that; only a running emulator can.
    * the symbol table is built from Alchav's fork at .cache/pret HEAD, but the ROM a player
      builds comes from the basepatch shipped inside pokemon_rb.apworld. Those are two
      different commits. If they ever diverge, every AP address is silently wrong.

  NEEDS NO BATTERY SAVE. There is no AP fixture (the fork's save block is 4 bytes longer —
  sMainDataCheckSum 0xB523 -> 0xB527 — so a vanilla .SaveRAM fails the AP checksum and the
  title screen would not even offer CONTINUE). Everything below is asserted against the ROM
  and against the intro, both of which a cold boot provides.

  SELF-CONTROLLING. Three INDEPENDENT measurements have to agree:
      (a) the seed slot, read through the "ROM" domain   -> is this an AP build?
      (b) which wCurMap operand bank 0's CODE references -> which layout does it use?
      (c) what detect_variant() / initProfile() decided  -> what SLink will actually read.
  Run it on the AP build and all three must say AP; run it on the VANILLA cartridge and all
  three must say vanilla. A detection bug cannot satisfy both directions, so the negative
  control is the same file rather than a second one someone has to remember to run.

      python tools/gen1_ap_rom.py                                  # build the ROM
      python tools/run_gen1_gate.py lua/tests/test_gen1_ap_gate.lua --rom red_ap
      python tools/run_gen1_gate.py lua/tests/test_gen1_ap_gate.lua --rom red   # control

  Result file: patch/build/test_gen1_ap_gate_result.txt
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("test_gen1_ap_gate", {no_boot = true})
local M, Game = t.M, t.G
local fmt = string.format

-- ── (a) the seed slot, through the "ROM" domain ──────────────────────────────
-- Everything in this gate is downstream of this domain existing and being flat file
-- offsets, so prove that first and stop if it is not there.
local has_rom = false
for _, d in ipairs(memory.getmemorydomainlist()) do
    if d == "ROM" then has_rom = true break end
end
t.check("BizHawk exposes a flat 'ROM' domain for the Game Boy core", has_rom,
        "detect_archipelago() cannot work without it")
if not has_rom then t.finish("no ROM domain") end

local rom_size = memory.getmemorydomainsize("ROM")
t.check("the ROM domain is the whole 1 MB cartridge, not a 32 KB bus window",
        rom_size >= 0x100000, fmt("got %d bytes", rom_size))

-- 0x5F22 lives in bank 1. On the System Bus 0x4000-0x7FFF shows whatever bank is mapped, so
-- the two reads only agree by accident. Assert they DISAGREE somewhere in the slot when the
-- mapped bank is not 1 — that is the whole reason detect_archipelago reads "ROM".
local seed_rom, seed_bus = {}, {}
for i = 0, Game.AP_SEED_LEN - 1 do
    seed_rom[i] = memory.read_u8(Game.AP_SEED_ROM_OFFSET + i, "ROM")
    seed_bus[i] = memory.read_u8(Game.AP_SEED_ROM_OFFSET + i, "System Bus")
end
local function hex(tab)
    local s = {}
    for i = 0, Game.AP_SEED_LEN - 1 do s[#s + 1] = fmt("%02X", tab[i]) end
    return table.concat(s)
end

local is_ap_rom = Game.detect_archipelago()
t.log(fmt("  seed@0x%04X  ROM=%s", Game.AP_SEED_ROM_OFFSET, hex(seed_rom)))
t.log(fmt("  seed@0x%04X  BUS=%s", Game.AP_SEED_ROM_OFFSET, hex(seed_bus)))

-- ── (b) which layout does the cartridge's own CODE use? ──────────────────────
-- `ld a,[nn]` is FA lo hi and `ld [nn],a` is EA lo hi. Bank 0 (home/*.asm) references
-- wCurMap 25 times in BOTH builds — at 0xD35E in vanilla and 0xD436 in the fork, never
-- both. Measured on the real dumps: 25/0 one way, 0/25 the other, so the two are separated
-- by the entire count rather than by a threshold anyone has to tune.
--
-- Bank 0 only (16 KB): it is enough to discriminate and cheap enough to read a byte at a
-- time. wIsInBattle, which the fork does NOT move, is the positive control — if the scan
-- itself were broken that count would collapse too, and a 0/0 result would otherwise read
-- as "the vanilla address is absent", i.e. as evidence FOR the AP build.
local BANK0 = 0x4000
local bank0 = {}
do
    local ok, arr = pcall(memory.read_bytes_as_array, 0, BANK0, "ROM")
    if ok and arr then
        for i = 1, BANK0 do bank0[i - 1] = arr[i] end
    else
        for i = 0, BANK0 - 1 do bank0[i] = memory.read_u8(i, "ROM") end
    end
end

local function operand_hits(addr)
    local lo, hi = addr % 256, math.floor(addr / 256)
    local n = 0
    for i = 0, BANK0 - 3 do
        if bank0[i + 1] == lo and bank0[i + 2] == hi
           and (bank0[i] == 0xFA or bank0[i] == 0xEA) then
            n = n + 1
        end
    end
    return n
end

local VANILLA_CUR_MAP, AP_CUR_MAP = 0xD35E, 0xD436
local IS_IN_BATTLE = 0xD057                    -- unmoved by the fork: the positive control
local hits_vanilla, hits_ap = operand_hits(VANILLA_CUR_MAP), operand_hits(AP_CUR_MAP)
local hits_control = operand_hits(IS_IN_BATTLE)

t.log(fmt("  bank0 operands: wCurMap vanilla@0x%04X=%d  ap@0x%04X=%d  control 0x%04X=%d",
          VANILLA_CUR_MAP, hits_vanilla, AP_CUR_MAP, hits_ap, IS_IN_BATTLE, hits_control))
t.check("the operand scan works at all (wIsInBattle is referenced in bank 0)",
        hits_control >= 3,
        fmt("got %d — a broken scanner would make BOTH wCurMap counts 0", hits_control))
t.check("bank 0 references exactly one of the two wCurMap addresses",
        (hits_vanilla > 0) ~= (hits_ap > 0),
        fmt("vanilla=%d ap=%d", hits_vanilla, hits_ap))
local code_says_ap = hits_ap > 0

-- ── (a) vs (b): the apworld basepatch vs .cache/pret/alchav_pokered ──────────
-- THE ASSERTION THIS GATE EXISTS FOR. The profile's addresses come from a symbol table
-- built out of Alchav's fork at whatever commit .cache/pret is pinned to; the cartridge
-- comes from the basepatch inside the installed pokemon_rb.apworld. This is the only check
-- anywhere that those two are the same build. When Archipelago ships a new pokemon_rb and
-- the fork moves WRAM again, this is what fails.
t.check("the ROM's own code agrees with the seed slot about which build this is",
        code_says_ap == is_ap_rom,
        fmt("seed says %s, bank-0 code says %s — data/pret_syms.json and the installed "
            .. "pokemon_rb.apworld are different builds of the fork",
            tostring(is_ap_rom), tostring(code_says_ap)))

-- ── (c) what SLink actually decided ──────────────────────────────────────────
local expect_variant = is_ap_rom and "_ap" or nil
t.check("detect_variant() reports the AP build as such",
        (t.variant:find("_ap") ~= nil) == is_ap_rom,
        fmt("variant=%q, is_ap=%s", t.variant, tostring(is_ap_rom)))
t.check("rom_type_for_variant() returns a server-side KEY, not a display label",
        Game.rom_type_for_variant(t.variant)
            == (is_ap_rom and t.variant or t.variant:gsub("^%l", string.upper)),
        fmt("got %q for variant %q — the server maps this through _ROM_TYPE_TO_GAME_ID "
            .. "and a label like 'Red (AP)' binds no adapter at all",
            Game.rom_type_for_variant(t.variant), t.variant))

-- initProfile has to have bound the SAME layout the cartridge's code uses. The AP block
-- inherits ~19 unchanged fields from `red` through a metatable, so a missing override does
-- not read as nil — it reads as a plausible vanilla address.
local expect = is_ap_rom
    and {MAP_ID_ADDR = 0xD436, PLAYER_ID_ADDR = 0xD431, BADGES_ADDR = 0xD42E,
         ENEMY_COUNT_ADDR = 0xD88A, ENEMY_BASE_ADDR = 0xD892, BOX_COUNT_ADDR = 0xDA8B,
         BOX_BASE_ADDR = 0xDAA1, BOX_NICKS_ADDR = 0xDE11, CURRENT_BOX_NUM_ADDR = 0xD614,
         GRASS_TILE_ADDR = 0xD58D, GRASS_RATE_ADDR = 0xD875,
         ENEMY_OT_NAMES_ADDR = 0xD99A, ENEMY_NICKS_ADDR = 0xD9DC}
    or  {MAP_ID_ADDR = 0xD35E, PLAYER_ID_ADDR = 0xD359, BADGES_ADDR = 0xD356,
         ENEMY_COUNT_ADDR = 0xD89C, ENEMY_BASE_ADDR = 0xD8A4, BOX_COUNT_ADDR = 0xDA80,
         BOX_BASE_ADDR = 0xDA96, BOX_NICKS_ADDR = 0xDE06, CURRENT_BOX_NUM_ADDR = 0xD5A0,
         GRASS_TILE_ADDR = 0xD535, GRASS_RATE_ADDR = 0xD887,
         ENEMY_OT_NAMES_ADDR = 0xD9AC, ENEMY_NICKS_ADDR = 0xD9EE}
for field, want in pairs(expect) do
    t.check(fmt("initProfile bound %s", field), M[field] == want,
            fmt("got %s, want 0x%04X", M[field] and fmt("0x%04X", M[field]) or "nil", want))
end
-- The unmoved fields must NOT have been "helpfully" shifted along with the rest.
t.check("initProfile left wPartyCount where the fork leaves it",
        M.PARTY_COUNT_ADDR == 0xD163, fmt("got 0x%04X", M.PARTY_COUNT_ADDR or 0))
t.check("initProfile left wIsInBattle where the fork leaves it",
        M.BATTLE_FLAG_ADDR == 0xD057, fmt("got 0x%04X", M.BATTLE_FLAG_ADDR or 0))

-- The memorial box is the one SRAM structure the fork could have broken silently. Its
-- geometry is unchanged (sBox1 0xA000, box_len 1122, checksum block at +0x1A4C), but the
-- flag the guard sets moved with wCurrentBoxNum, and writing bit 7 at the VANILLA address
-- on an AP cartridge lands in wEventFlags-adjacent story data.
local sram = M.profile and M.profile.sram_box_layout
t.check("the memorial SRAM guard points at the bound wCurrentBoxNum",
        sram and sram.changed_boxes_addr == M.CURRENT_BOX_NUM_ADDR,
        fmt("guard=%s bound=%s", sram and fmt("0x%04X", sram.changed_boxes_addr) or "nil",
            fmt("0x%04X", M.CURRENT_BOX_NUM_ADDR or 0)))
t.check("box geometry is unchanged by the fork (1122 bytes x 6 per bank)",
        sram and sram.box_len == 1122 and sram.boxes_per_bank == 6)

-- ── The bound address has to be LIVE, not just correct on paper ──────────────
-- Everything above is static: it would still pass on a ROM that crashes at boot. Cold-boot
-- the cartridge and wait for the game itself to write the bound wCurMap.
--
-- The intro reaches RedsHouse2F (0x26) around frame 670 on vanilla — long before either
-- naming screen, so mashing A cannot wedge in the letter grid before we are done. A press
-- every 16 frames, never held: a long hold auto-repeats past whatever appears mid-press.
local HOUSE_2F = 0x26
local live_at = nil
for i = 1, 24000 do
    if M.read_u8(M.MAP_ID_ADDR) == HOUSE_2F then live_at = i break end
    t.step((i % 16 < 2) and {A = true} or nil)
end
local other = is_ap_rom and VANILLA_CUR_MAP or AP_CUR_MAP
if live_at then
    t.check("the cartridge boots and the game writes the BOUND wCurMap", true,
            fmt("0x%04X = 0x26 at frame %d", M.MAP_ID_ADDR, live_at))
    -- And the address SLink did NOT bind must be dead, or "correct" only means "one of two
    -- bytes happened to hold 0x26".
    t.check("the OTHER build's wCurMap is not also reading a bedroom",
            M.read_u8(other) ~= HOUSE_2F,
            fmt("0x%04X = 0x%02X", other, M.read_u8(other)))
else
    client.screenshot(t.ROOT .. "/patch/build/test_gen1_ap_gate_bootfail.png")
    t.check("the cartridge boots and the game writes the BOUND wCurMap", false,
            fmt("wCurMap@0x%04X never became 0x26 (last=0x%02X); the other candidate read "
                .. "0x%02X — see test_gen1_ap_gate_bootfail.png",
                M.MAP_ID_ADDR or 0, M.read_u8(M.MAP_ID_ADDR), M.read_u8(other)))
end

t.finish(fmt("variant=%s ap=%s", t.variant, tostring(is_ap_rom)))
