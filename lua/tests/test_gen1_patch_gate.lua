--[[
  lua/tests/test_gen1_patch_gate.lua — does the Gen 1 companion patch actually run?

  THE SPIKE'S VERDICT. patch/gen1/ injects 42 bytes into bank $3F and rewrites three
  immediate bytes inside VBlank's `farcall TrackPlayTime` at ROM 0x2094. This decides
  whether that approach is sound, before any feature is built on it.

  What has to be true:
    1. the 'SLNK' beacon appears in WRAM at $DEE2 — the code is reached at all;
    2. the frame counter ADVANCES — it runs every frame, not once;
    3. it keeps advancing IN BATTLE and WITH A MENU OPEN — VBlank is an interrupt, so a
       hook there must fire in every context, which is the whole reason this site was
       chosen over OverworldLoop;
    4. the displaced call still happens — the patch must not have eaten TrackPlayTime;
    5. the game is otherwise unharmed — the player can still walk.

  Run against the PATCHED build (patch/gen1/build/slink_red.gb), which the runner selects
  with --rom red_patched.

  Result file: patch/build/test_gen1_patch_gate_result.txt
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("test_gen1_patch_gate")
local M = t.M
local fmt = string.format

local MAILBOX = 0xDEE2
local function beacon()
    return string.char(M.read_u8(MAILBOX), M.read_u8(MAILBOX + 1),
                       M.read_u8(MAILBOX + 2), M.read_u8(MAILBOX + 3))
end
local function counter()
    return M.read_u8(MAILBOX + 5) + M.read_u8(MAILBOX + 6) * 256
end

-- 1. Presence.
t.check("'SLNK' beacon is present at $DEE2", beacon() == "SLNK",
        fmt("got %q", beacon()))
-- ABI is asserted with the SFX checks below, which are what ABI 2 added.

-- 2. It runs every frame.
local c0 = counter()
for _ = 1, 60 do t.step(nil) end
local c1 = counter()
t.check("frame counter advances", c1 ~= c0, fmt("%d -> %d over 60 frames", c0, c1))

-- 3. It runs IN BATTLE. VBlank is an interrupt; a hook that only ticked in the overworld
--    would be useless for anything battle-related.
M.write_u8(M.BATTLE_FLAG_ADDR, 1)
local b0 = counter()
for _ = 1, 60 do t.step(nil) end
local b1 = counter()
t.check("frame counter advances while wIsInBattle is set", b1 ~= b0,
        fmt("%d -> %d", b0, b1))
M.write_u8(M.BATTLE_FLAG_ADDR, 0)

-- 4. ...and with a menu up (the START menu holds the main loop, but VBlank keeps firing).
t.hold("Start", 10, nil)
for _ = 1, 30 do t.step(nil) end
local m0 = counter()
for _ = 1, 60 do t.step(nil) end
t.check("frame counter advances with the START menu open", counter() ~= m0,
        fmt("%d -> %d", m0, counter()))
t.hold("B", 10, nil)
for _ = 1, 30 do t.step(nil) end

-- 5. The displaced code still runs. TrackPlayTime increments the play-time counters; if the
--    hook had swallowed it, the clock would be frozen — a patch that quietly breaks the
--    game it hooks is worse than no patch.
local PLAYTIME_FRAMES = 0xDA44          -- wPlayTimeFrames (pret/pokered)
local p0 = M.read_u8(PLAYTIME_FRAMES)
local moved = false
for _ = 1, 400 do
    t.step(nil)
    if M.read_u8(PLAYTIME_FRAMES) ~= p0 then moved = true break end
end
t.check("the displaced TrackPlayTime still runs (play clock advances)", moved,
        "the hook must chain to what it replaced, not replace it")

-- 6. The game still plays.
local x_addr, y_addr = M.MAP_ID_ADDR + 4, M.MAP_ID_ADDR + 3
local x0, y0 = M.read_u8(x_addr), M.read_u8(y_addr)
t.hold("Right", 30, function()
    return M.read_u8(x_addr) ~= x0 or M.read_u8(y_addr) ~= y0
end)
t.check("the player can still walk on the patched ROM",
        M.read_u8(x_addr) ~= x0 or M.read_u8(y_addr) ~= y0,
        fmt("(%d,%d) -> (%d,%d)", x0, y0, M.read_u8(x_addr), M.read_u8(y_addr)))

-- 7. The mailbox advertises what this build can actually do — and does NOT claim SFX.
--
-- This build ships PANEL ONLY. The VBlank PlaySound path that ABI 2 added is not safe, and
-- the two reasons are both measurable in the shipped ROM (see the long note at the top of
-- patch/gen1/src/slink.asm): PlaySound returns without playing whenever a music fade is
-- running, and its `.noFadeOut` arm has a window where both guard bytes are clear, so a
-- VBlank landing there re-enters a non-reentrant audio routine. Our hook IS that VBlank.
--
-- So the assertions below are the inverse of what they used to be. The old ones fired from
-- a quiescent overworld and were structurally blind to both failures: they could only ever
-- see the case that works.
local SFX_REQUEST      = MAILBOX + 7
local CHANNEL_SOUND_IDS = 0xC026
local SFX_TINK         = 0x8C   -- resolves identically in all three audio banks

t.check("ABI version byte is 3", M.read_u8(MAILBOX + 4) == 3,
        fmt("got %d", M.read_u8(MAILBOX + 4)))

-- CAPABILITIES ARE ADVERTISED, NOT INFERRED FROM THE ABI NUMBER. This build dropping SFX
-- while keeping ABI 3 is exactly the case that motivated the bits: a client reasoning
-- "ABI 3 therefore both" would drive an audio path that is not there.
local CAPS = MAILBOX + 8
local CAP_SFX, CAP_PANEL = 0x01, 0x02
t.check("the capability byte does NOT advertise SFX", M.read_u8(CAPS) & CAP_SFX == 0,
        fmt("caps=0x%02X — this build must not claim an unsafe audio path", M.read_u8(CAPS)))
t.check("the capability byte advertises the panel", M.read_u8(CAPS) & CAP_PANEL ~= 0,
        fmt("caps=0x%02X", M.read_u8(CAPS)))

-- The panel handshake byte must be CLOSED while the player is walking around. If it were
-- not, a client would paint over the map.
t.check("the panel handshake is closed outside the panel", M.read_u8(MAILBOX + 9) == 0,
        fmt("panel state is %d in the overworld", M.read_u8(MAILBOX + 9)))

local function sfx_channels()
    return fmt("%d/%d/%d/%d",
               M.read_u8(CHANNEL_SOUND_IDS + 4), M.read_u8(CHANNEL_SOUND_IDS + 5),
               M.read_u8(CHANNEL_SOUND_IDS + 6), M.read_u8(CHANNEL_SOUND_IDS + 7))
end

-- The request byte is still DRAINED, so a client that writes one leaves no stale state.
M.write_u8(SFX_REQUEST, SFX_TINK)
local consumed = false
for _ = 1, 10 do
    t.step(nil)
    if M.read_u8(SFX_REQUEST) == 0 then consumed = true break end
end
t.check("the SFX request byte is still consumed by the hook", consumed,
        fmt("still %#04x after 10 frames", M.read_u8(SFX_REQUEST)))

-- ...and it must NOT reach the audio engine. This is the assertion that would have failed
-- against the ABI-2 build, and it is the one that matters: no reachable PlaySound means no
-- re-entrancy window to land in.
local before = sfx_channels()
for _ = 1, 30 do t.step(nil) end
t.check("a drained SFX request never starts a sound", sfx_channels() == before,
        fmt("CHAN5-8 %s -> %s — the hook still reaches PlaySound", before, sfx_channels()))

-- 8. And the game still runs normally afterwards — a botched `call` from inside an interrupt
--    would corrupt the bank or the stack and the walk check below would hang or crash.
local x2, y2 = M.read_u8(x_addr), M.read_u8(y_addr)
t.hold("Left", 30, function()
    return M.read_u8(x_addr) ~= x2 or M.read_u8(y_addr) ~= y2
end)
t.check("the player can still walk after the SFX hook fired",
        M.read_u8(x_addr) ~= x2 or M.read_u8(y_addr) ~= y2,
        fmt("(%d,%d) -> (%d,%d)", x2, y2, M.read_u8(x_addr), M.read_u8(y_addr)))

t.finish(fmt("variant=%s counter=%d", t.variant, counter()))
