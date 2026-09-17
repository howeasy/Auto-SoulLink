--[[
  lua/tests/test_gen1_patch_gate.lua — does the Gen 1 companion patch actually run?

  THE SPIKE'S VERDICT, ported onto the rewritten client's harness (lua/tests/gen1_gate.lua).
  patch/gen1/ hooks VBlank and injects into bank $3F. This decides whether that approach is
  sound, independently of any feature built on it.

  What has to be true:
    1. the 'SLNK' beacon appears in WRAM at $DEE2 — the code is reached at all;
    2. the frame counter ADVANCES — it runs every frame, not once;
    3. it keeps advancing WITH A MENU OPEN — VBlank is an interrupt, so a hook there must
       fire even while the main loop is parked;
    4. the displaced call still happens — the patch must not have eaten TrackPlayTime;
    5. the mailbox advertises what this build can do, and does NOT claim SFX;
    6. the game is otherwise unharmed — the player can still walk.

  TWO DELIBERATE CHANGES FROM THE PRE-REWRITE VERSION:

  * The addresses come from the generated profile (t.parts.profile.ram) instead of
    memory_gb.lua's M.MAP_ID_ADDR / M.BATTLE_FLAG_ADDR and arithmetic on them. One source
    of truth per symbol; a relocated variant follows automatically.

  * The `wIsInBattle = 1` staging is GONE. It wrote a game-state byte to fake a battle,
    which this project no longer does anywhere: a faked battle is not a battle, and the
    engine reached states from it that no player can. The in-battle half of claim 3 is
    proven instead by the A3 scenario's PANEL_COUNTER_IN_BATTLE marker, taken inside a real
    wild battle on a real fixture.

  The SFX request byte below IS still written, and that is not the same thing. $DEE9 is the
  CLIENT'S OWN mailbox slot — the ABI under test, allocated by this patch, read by nobody
  else. Writing it is exactly what a client does; the assertion is that the hook drains it
  and that draining it reaches no audio code. Nothing in the game's own state is touched.

  Run against the PATCHED build (patch/gen1/build/slink_red.gb), which the runner selects
  with --rom red_patched.

  Result file: patch/build/test_gen1_patch_gate_result.txt
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gate.lua")
local t = G.start("test_gen1_patch_gate")
local fmt = string.format
local ram = t.parts.profile.ram
-- The mailbox layout comes from the module that owns it, not a second copy of the offsets.
local Panel = dofile(t.ROOT .. "/lua/gen1/panel.lua")
local MAILBOX = Panel.MAILBOX
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
--    wPlayTimeFrames is not a symbol the profile carries (it is not one the client reads);
--    $DA44 is pret/pokered's own address, and this gate only ever runs on Red/Blue.
local PLAYTIME_FRAMES = 0xDA44
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

-- 6. The mailbox advertises what this build can actually do — and does NOT claim SFX.
--
-- This build ships PANEL ONLY. The VBlank PlaySound path that ABI 2 added is not safe, and
-- the two reasons are both measurable in the shipped ROM (see the long note at the top of
-- patch/gen1/src/slink.asm): PlaySound returns without playing whenever a music fade is
-- running, and its `.noFadeOut` arm has a window where both guard bytes are clear, so a
-- VBlank landing there re-enters a non-reentrant audio routine. Our hook IS that VBlank.
--
-- So the assertions below are the inverse of what they used to be. The old ones fired from a
-- quiescent overworld and were structurally blind to both failures.
local CHANNEL_SOUND_IDS = 0xC026    -- wChannelSoundIDs; audio RAM the client never reads
local SFX_TINK = 0x8C               -- resolves identically in all three audio banks
local CAP_SFX, CAP_PANEL = 0x01, 0x02

t.check("ABI version byte is 3", read(ABI_BYTE) == 3, fmt("got %d", read(ABI_BYTE)))

-- CAPABILITIES ARE ADVERTISED, NOT INFERRED FROM THE ABI NUMBER. This build dropping SFX
-- while keeping ABI 3 is exactly the case that motivated the bits: a client reasoning
-- "ABI 3 therefore both" would drive an audio path that is not there.
t.check("the capability byte does NOT advertise SFX", read(Panel.CAPS) & CAP_SFX == 0,
        fmt("caps=0x%02X — this build must not claim an unsafe audio path", read(Panel.CAPS)))
t.check("the capability byte advertises the panel", read(Panel.CAPS) & CAP_PANEL ~= 0,
        fmt("caps=0x%02X", read(Panel.CAPS)))

-- The client's own reading of those same bytes. A beacon the gate can see but the shipped
-- module cannot is a patch that works and a feature that never turns on.
t.check("the panel module sees the cartridge the gate does",
        t.parts.panel:present() == true and t.parts.panel:abi() == read(ABI_BYTE),
        fmt("present=%s abi=%d", tostring(t.parts.panel:present()), t.parts.panel:abi()))

-- The panel handshake byte must be CLOSED while the player is walking around. If it were
-- not, a client would paint over the map.
t.check("the panel handshake is closed outside the panel", read(Panel.STATE) == Panel.CLOSED,
        fmt("panel state is %d in the overworld", read(Panel.STATE)))

local function sfx_channels()
    return fmt("%d/%d/%d/%d", read(CHANNEL_SOUND_IDS + 4), read(CHANNEL_SOUND_IDS + 5),
               read(CHANNEL_SOUND_IDS + 6), read(CHANNEL_SOUND_IDS + 7))
end

-- The request byte is still DRAINED, so a client that writes one leaves no stale state.
write(SFX_REQUEST, SFX_TINK)
local consumed = false
for _ = 1, 10 do
    t.step(nil)
    if read(SFX_REQUEST) == 0 then consumed = true break end
end
t.check("the SFX request byte is still consumed by the hook", consumed,
        fmt("still %#04x after 10 frames", read(SFX_REQUEST)))

-- ...and it must NOT reach the audio engine. This is the assertion that would have failed
-- against the ABI-2 build, and it is the one that matters: no reachable PlaySound means no
-- re-entrancy window to land in.
-- "Never starts" = no SFX channel that was silent becomes busy. A channel that was already
-- playing (the CONTINUE menu's own press sound, id 180, was still fading in the lab fixture)
-- is allowed to finish; string equality read that finishing as the hook playing something.
local before = sfx_channels()
local before_ids = { read(CHANNEL_SOUND_IDS + 4), read(CHANNEL_SOUND_IDS + 5),
                     read(CHANNEL_SOUND_IDS + 6), read(CHANNEL_SOUND_IDS + 7) }
local started = false
for _ = 1, 30 do
    t.step(nil)
    for i = 0, 3 do
        if before_ids[i + 1] == 0 and read(CHANNEL_SOUND_IDS + 4 + i) ~= 0 then started = true end
    end
end
t.check("a drained SFX request never starts a sound", not started,
        fmt("CHAN5-8 %s -> %s — the hook still reaches PlaySound", before, sfx_channels()))

-- 7. And the game still runs normally afterwards — a botched `call` from inside an interrupt
--    would corrupt the bank or the stack and the walk check below would hang or crash.
local x2, y2 = read(X), read(Y)
t.hold("Left", 30, function() return moved(x2, y2) end)
if not moved(x2, y2) then t.hold("Right", 30, function() return moved(x2, y2) end) end
t.check("the player can still walk after the SFX hook fired", moved(x2, y2),
        fmt("(%d,%d) -> (%d,%d)", x2, y2, read(X), read(Y)))

t.finish(fmt("title=%s counter=%d map=%d", t.title, counter(), at("wCurMap")))
