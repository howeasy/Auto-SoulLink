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

-- 7. The SFX request byte actually plays a sound (ABI 2).
--
-- This is the ONLY thing the patch does that a player can perceive, and the reason it exists:
-- Gen 1 has no RAM-writable sound trigger at all. wNewSoundID ($C0EE) is PlaySound's internal
-- scratch, not a polled mailbox, so writing it from Lua does nothing — the id has to reach a
-- `call`, which is what the VBlank hook does.
--
-- Asserting on wChannelSoundIDs, not on the request byte: the request byte clearing only
-- proves our own code ran. The SFX channels changing proves the game's audio engine actually
-- accepted the sound. CHAN5-8 are the SFX channels (pret wChannelSoundIDs = $C026).
local SFX_REQUEST      = MAILBOX + 7
local CHANNEL_SOUND_IDS = 0xC026
local SFX_TINK         = 0x8C   -- resolves identically in all three audio banks

t.check("ABI version byte is 2 (SFX support)", M.read_u8(MAILBOX + 4) == 2,
        fmt("got %d", M.read_u8(MAILBOX + 4)))

local function sfx_channels()
    return fmt("%d/%d/%d/%d",
               M.read_u8(CHANNEL_SOUND_IDS + 4), M.read_u8(CHANNEL_SOUND_IDS + 5),
               M.read_u8(CHANNEL_SOUND_IDS + 6), M.read_u8(CHANNEL_SOUND_IDS + 7))
end

local before = sfx_channels()
M.write_u8(SFX_REQUEST, SFX_TINK)

-- The hook consumes the request on the next VBlank.
local consumed = false
for _ = 1, 10 do
    t.step(nil)
    if M.read_u8(SFX_REQUEST) == 0 then consumed = true break end
end
t.check("the SFX request byte is consumed by the hook", consumed,
        fmt("still %#04x after 10 frames", M.read_u8(SFX_REQUEST)))

local changed = false
for _ = 1, 20 do
    t.step(nil)
    if sfx_channels() ~= before then changed = true break end
end
t.check("writing an SFX id actually starts a sound (wChannelSoundIDs changes)", changed,
        fmt("CHAN5-8 %s -> %s", before, sfx_channels()))

-- A zero request must stay a no-op, or every frame would retrigger the last sound.
M.write_u8(SFX_REQUEST, 0)
for _ = 1, 30 do t.step(nil) end
local idle = sfx_channels()
for _ = 1, 30 do t.step(nil) end
t.check("a zero request does not retrigger anything", sfx_channels() == idle,
        fmt("%s -> %s", idle, sfx_channels()))

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
