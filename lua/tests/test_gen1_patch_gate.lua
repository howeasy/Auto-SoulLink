--[[
  lua/tests/test_gen1_patch_gate.lua — does the Gen 1 companion patch actually run?

  THE SPIKE'S VERDICT, ported onto the rewritten client's harness (lua/tests/gen1_gate.lua).
  patch/gen1/ hooks VBlank and injects into bank $3F. This decides whether that approach is
  sound, independently of any feature built on it.

  What has to be true:
    1. the 'SLNK' beacon appears in WRAM at the cartridge's mailbox (profile.trade.mailbox —
       vanilla $DEE2, the pureRGB overlay's own address per PLAN A4/M3) — the code is reached at all;
    2. the frame counter ADVANCES — it runs every frame, not once;
    3. it keeps advancing WITH A MENU OPEN — VBlank is an interrupt, so a hook there must
       fire even while the main loop is parked;
    4. the displaced call still happens — the patch must not have eaten TrackPlayTime;
    5. the mailbox advertises what this build can do: panel AND SFX;
    6. the game is otherwise unharmed — the player can still walk;
    7. a semantic SFX request written to the mailbox becomes the right sound for the audio
       bank that is loaded, on the main thread, and the byte is consumed by the play.

  TWO DELIBERATE CHANGES FROM THE PRE-REWRITE VERSION:

  * The addresses come from the generated profile (t.parts.profile.ram) instead of
    memory_gb.lua's M.MAP_ID_ADDR / M.BATTLE_FLAG_ADDR and arithmetic on them. One source
    of truth per symbol; a relocated variant follows automatically.

  * The `wIsInBattle = 1` staging is GONE. It wrote a game-state byte to fake a battle,
    which this project no longer does anywhere: a faked battle is not a battle, and the
    engine reached states from it that no player can. The in-battle half of claim 3 is
    proven instead by the A3 scenario's PANEL_COUNTER_IN_BATTLE marker, taken inside a real
    wild battle on a real fixture.

  The SFX request byte below IS written, and that is not the same thing. $DEE9 is the
  CLIENT'S OWN mailbox slot — the ABI under test, allocated by this patch, read by nobody
  else. Writing it is exactly what a client does; the assertion is that the main-thread
  service turns it into the expected sound id on CHAN5 and clears it. Nothing in the game's
  own state is touched — the sound engine is asked through its own entry point, PlaySound.

  Run against the PATCHED build (patch/gen1/build/slink_red.gb), which the runner selects
  with --rom red_patched.

  Result file: patch/build/test_gen1_patch_gate_result.txt
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gate.lua")
local t = G.start("test_gen1_patch_gate")
local fmt = string.format
local ram = t.parts.profile.ram
-- The mailbox layout comes from the module that owns it, not a second copy of the offsets. On
-- an overlay-admitted cartridge the mailbox itself moves (profile.trade.mailbox, PLAN A4/M3);
-- Panel.MAILBOX is only the vanilla companion-patch default panel.lua falls back to.
local Panel = dofile(t.ROOT .. "/lua/gen1/panel.lua")
local MAILBOX = t.parts.profile.trade and t.parts.profile.trade.mailbox or Panel.MAILBOX
-- STATE/CAPS are mailbox-relative ABI offsets (+8/+9); derive the delta from Panel's own
-- exported vanilla constants rather than a second copy of the offset numbers.
local STATE = MAILBOX + (Panel.STATE - Panel.MAILBOX)
local CAPS  = MAILBOX + (Panel.CAPS - Panel.MAILBOX)
local ABI_BYTE = MAILBOX + 4          -- slink.asm:38-66 (panel.lua keeps this one private)
local SFX_REQUEST = MAILBOX + 7

local function read(addr) return memory.read_u8(addr, "System Bus") end
local function at(symbol) return read(assert(ram[symbol], symbol .. " missing from profile")) end
local function write(addr, value) t.deps.write_u8(addr, value) end

local function beacon()
    return string.char(read(MAILBOX), read(MAILBOX + 1), read(MAILBOX + 2), read(MAILBOX + 3))
end
local function counter()
    return read(MAILBOX + 5) + read(MAILBOX + 6) * 256
end

-- 1. Presence.
t.check("'SLNK' beacon is present at $DEE2", beacon() == "SLNK", fmt("got %q", beacon()))
-- ABI is asserted with the SFX checks below, which are what ABI 2 added.

-- 2. It runs every frame.
local c0 = counter()
t.idle(60)
local c1 = counter()
t.check("frame counter advances", c1 ~= c0, fmt("%d -> %d over 60 frames", c0, c1))

-- 3. ...and with a menu up (the START menu holds the main loop, but VBlank keeps firing).
--    The in-battle case is the A3 scenario's PANEL_COUNTER_IN_BATTLE marker: it needs a real
--    battle, and a battle is not something a gate is allowed to fake into WRAM.
t.hold("Start", 10)
t.idle(30)
local m0 = counter()
t.idle(60)
t.check("frame counter advances with the START menu open", counter() ~= m0,
        fmt("%d -> %d", m0, counter()))
t.hold("B", 10)
t.idle(30)

-- 4. The displaced code still runs. TrackPlayTime increments the play-time counters; if the
--    hook had swallowed it, the clock would be frozen — a patch that quietly breaks the game
--    it hooks is worse than no patch.
--    wPlayTimeFrames is not a symbol the profile carries (it is not one the client reads), so
--    its address is a driver-facts literal (F.COMPANION.playtime_frames_addr): pret/pokered's
--    $DA44 on a vanilla/patched cartridge, data/purergb/pokered.sym's $DA4D on an
--    overlay-admitted one (the overlay's linked WRAM0 layout shifts it 9 bytes).
local PLAYTIME_FRAMES = t.facts.COMPANION.playtime_frames_addr
local p0 = read(PLAYTIME_FRAMES)
local ticked = false
for _ = 1, 400 do
    t.step(nil)
    if read(PLAYTIME_FRAMES) ~= p0 then ticked = true break end
end
t.check("the displaced TrackPlayTime still runs (play clock advances)", ticked,
        "the hook must chain to what it replaced, not replace it")

-- 5. The game still plays.
local X, Y = assert(ram.wXCoord), assert(ram.wYCoord)
local x0, y0 = read(X), read(Y)
local function moved(x, y) return read(X) ~= x or read(Y) ~= y end
-- Right, then Left: the regenerated town fixtures stand in Oak's Lab, where the tile to the
-- right of the parking spot is furniture; the claim is only that the game still moves.
t.hold("Right", 30, function() return moved(x0, y0) end)
if not moved(x0, y0) then t.hold("Left", 30, function() return moved(x0, y0) end) end
t.check("the player can still walk on the patched ROM", moved(x0, y0),
        fmt("(%d,%d) -> (%d,%d)", x0, y0, read(X), read(Y)))

-- 6. The mailbox advertises what this build can actually do — panel AND SFX.
--
-- ABI 3 shipped panel-only: the ABI-2 build played sound from the VBlank hook, which drops
-- requests during fades and re-enters PlaySound (patch/gen1/src/slink.asm has the note).
-- The dispatch now runs on the MAIN THREAD, from the DelayFrame bridge, and holds the
-- request while a fade runs or an SFX channel is busy. The request byte carries a
-- SEMANTIC code (1 success, 2 failure, 3 boo) that the ROM resolves against the audio bank
-- loaded at play time, because sound ids are per bank. So every assertion below names the
-- exact id it expects on CHAN5 for the bank it observed — a known positive, not "something
-- started playing".
local CHANNEL_SOUND_IDS = t.facts.COMPANION.channel_sound_ids_addr  -- wChannelSoundIDs; audio RAM the client never reads (SAME on both foundations, sourced from the facts table like PLAYTIME_FRAMES)
local AUDIO_ROM_BANK    = t.facts.COMPANION.audio_rom_bank_addr     -- wAudioROMBank: which header table the ids index
local CHAN5 = CHANNEL_SOUND_IDS + 4
local CAP_SFX, CAP_PANEL = 0x01, 0x02
-- slink.asm SlinkSfxService table, per audio bank: (header address - SFX_Headers_N) / 3 from the .sym.
local TABLE = {
    [0x02] = { 0x89, 0xA5, 0x8C },   -- GET_ITEM_2, DENIED, TINK
    [0x08] = { 0x86, 0x8C, 0x8C },   -- LEVEL_UP, TINK, TINK (no buzzer in the battle bank)
    [0x1F] = { 0x89, 0xA5, 0x8C },   -- GET_ITEM_2, DENIED, TINK
}

t.check("ABI version byte is 3", read(ABI_BYTE) == 3, fmt("got %d", read(ABI_BYTE)))

-- CAPABILITIES ARE ADVERTISED, NOT INFERRED FROM THE ABI NUMBER: ABI 3 once shipped without
-- SFX and now ships with it, and a client must read the bit, not the number.
t.check("the capability byte advertises SFX", read(CAPS) & CAP_SFX ~= 0,
        fmt("caps=0x%02X — the main-thread sound path is present and must be claimed", read(CAPS)))
t.check("the capability byte advertises the panel", read(CAPS) & CAP_PANEL ~= 0,
        fmt("caps=0x%02X", read(CAPS)))

-- The client's own reading of those same bytes. A beacon the gate can see but the shipped
-- module cannot is a patch that works and a feature that never turns on.
t.check("the panel module sees the cartridge the gate does",
        t.parts.panel:present() == true and t.parts.panel:abi() == read(ABI_BYTE),
        fmt("present=%s abi=%d", tostring(t.parts.panel:present()), t.parts.panel:abi()))
t.check("the panel module sees the SFX capability the gate does",
        t.parts.panel.sfx_present ~= nil and t.parts.panel:sfx_present() == true,
        "panel.lua must read SLINK_CAP_SFX from the same caps byte")

-- The panel handshake byte must be CLOSED while the player is walking around. If it were
-- not, a client would paint over the map.
t.check("the panel handshake is closed outside the panel", read(STATE) == Panel.CLOSED,
        fmt("panel state is %d in the overworld", read(STATE)))

local function sfx_channels()
    return fmt("%d/%d/%d/%d", read(CHANNEL_SOUND_IDS + 4), read(CHANNEL_SOUND_IDS + 5),
               read(CHANNEL_SOUND_IDS + 6), read(CHANNEL_SOUND_IDS + 7))
end
-- Let whatever is playing (the CONTINUE menu's own press sound was still fading in the lab
-- fixture) finish, so the service is not merely HOLDING when a case starts.
local function wait_quiet(limit)
    for _ = 1, limit or 300 do
        if read(CHAN5) == 0 and read(CHANNEL_SOUND_IDS + 5) == 0 and read(CHANNEL_SOUND_IDS + 7) == 0 then return true end
        t.step(nil)
    end
    return false
end
-- Write a request, then watch up to `limit` frames for the byte to clear; report the first
-- CHAN5 id seen after it cleared (the id the engine accepted), or nil.
local function request(code, limit)
    write(SFX_REQUEST, code)
    local consumed_at, seen = nil, nil
    for f = 1, limit or 10 do
        t.step(nil)
        if read(SFX_REQUEST) == 0 then
            consumed_at = f
            seen = read(CHAN5)
            break
        end
    end
    return consumed_at, seen
end

-- The fixture's bank is a fact of where it stands (Oak's Lab is Audio3, $1F; Pallet Town is
-- $02); the receipt names the row it proved rather than assuming one.
local bank = read(AUDIO_ROM_BANK)
local row = TABLE[bank]
t.check("the audio bank is one the table has a row for", row ~= nil,
        fmt("wAudioROMBank=$%02X (expected $02, $08 or $1F)", bank))
row = row or TABLE[0x1F]

t.check("the SFX channels went quiet before the requests", wait_quiet(),
        fmt("CHAN5-8 still %s after 300 frames", sfx_channels()))

-- (a) success: consumed within a few frames AND the row's success id is what CHAN5 plays.
local at1, id1 = request(1)
t.check("code 1 (success) is consumed by the main-thread service", at1 ~= nil,
        fmt("still %#04x after 10 frames", read(SFX_REQUEST)))
t.check(fmt("code 1 plays the bank $%02X success id $%02X on CHAN5", bank, row[1]), id1 == row[1],
        fmt("CHAN5 read $%02X (channels %s) — the request reached PlaySound with the wrong id, or none",
            id1 or 0, sfx_channels()))
t.check("the SFX channels went quiet after code 1", wait_quiet(), sfx_channels())

-- (b) an unknown code is consumed and starts nothing.
local before_ids = { read(CHANNEL_SOUND_IDS + 4), read(CHANNEL_SOUND_IDS + 5),
                     read(CHANNEL_SOUND_IDS + 6), read(CHANNEL_SOUND_IDS + 7) }
local at9 = request(9)
local started = false
for _ = 1, 30 do
    t.step(nil)
    for i = 0, 3 do
        if before_ids[i + 1] == 0 and read(CHANNEL_SOUND_IDS + 4 + i) ~= 0 then started = true end
    end
end
t.check("an unknown code is consumed without reaching the audio engine", at9 ~= nil and not started,
        fmt("consumed=%s channels %s", tostring(at9 ~= nil), sfx_channels()))

-- (c) failure: the row's failure id (DENIED outside the battle bank).
local at2, id2 = request(2)
t.check(fmt("code 2 plays the bank $%02X failure id $%02X on CHAN5", bank, row[2]),
        at2 ~= nil and id2 == row[2],
        fmt("consumed=%s CHAN5 read $%02X (channels %s)", tostring(at2 ~= nil), id2 or 0, sfx_channels()))
t.check("the SFX channels went quiet after code 2", wait_quiet(), sfx_channels())

-- 7. And the game still runs normally afterwards — a botched farcall from the bridge would
--    corrupt the bank or the stack and the walk check below would hang or crash.
local x2, y2 = read(X), read(Y)
t.hold("Left", 30, function() return moved(x2, y2) end)
if not moved(x2, y2) then t.hold("Right", 30, function() return moved(x2, y2) end) end
t.check("the player can still walk after the SFX hook fired", moved(x2, y2),
        fmt("(%d,%d) -> (%d,%d)", x2, y2, read(X), read(Y)))

t.finish(fmt("title=%s counter=%d map=%d", t.title, counter(), at("wCurMap")))
