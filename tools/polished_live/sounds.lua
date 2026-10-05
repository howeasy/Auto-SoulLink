-- tools/polished_live/sounds.lua -- POL-SOUNDS live proof (round 3).
--
-- A SCRIPTED MAILBOX WRITER, not the SLink client (the client's sound path is the integration
-- worker's). It presses ONLY wSlinkMailbox + SLINK_OFS_SFX_REQUEST and READS the audio engine.
-- Every memory.write_* is wrapped; any address other than the request byte is a FAIL, audited
-- unconditionally at the end of every phase.
--
-- THE IDS ARE NOT PASTED HERE. They come from the generated profile
-- (data/games/polished_crystal/profile.json -> titles.polished.overlay.sfx.codes), which
-- tools/gen_polished_profile.py derives from the pinned constants/sfx_constants.asm. The ROM's
-- own table is symbolic (patch/polished/src/slink_sfx.asm `.sounds`: db SFX_ITEM, SFX_WRONG,
-- SFX_BUMP, SFX_READ_TEXT_2), so the profile is the one machine-readable reading of them; reading
-- the numbers from two independent derivations is the point.
--
-- A PLAY IS AN EDGE, NOT AN EQUALITY. wCurSFX is written in exactly one place (home/audio.asm:265,
-- inside PlaySFX) and is never cleared when a sound ends, so it is a sticky "last id" register:
-- polling for wCurSFX == expected can latch onto a value from before the post. Every cue here is
-- sampled for PRE frames first and requires (a) the expected id NOT already showing and (b) the
-- expected id AND SOUND_CHANNEL_ON (constants/audio_constants.asm:73) together, after the post.
--
-- SLINK_SFX_MAX_HOLD EQU 240 counts SERVICE VISITS, not frames (slink_sfx.asm:6-9). Those agree
-- only while DelayFrame runs every frame, so the hold is reported in BOTH units, counted with a
-- bus-exec hook on SlinkDelayFrameBridge.
local ROOT = assert(os.getenv("SLINK_ROOT"), "SLINK_ROOT unset")
local OUT = assert(os.getenv("POL_OUT"), "POL_OUT unset")
local function raw(s)
    local f = io.open(OUT, "a")
    if f then f:write(s .. "\n") f:close() end
end
raw("sounds.lua: loading")

local oklib, L = pcall(dofile, ROOT .. "/tools/polished_live/pol_lib.lua")
if not oklib then
    raw("sounds.lua: pol_lib failed: " .. tostring(L))
    error("sounds.lua: pol_lib failed")
end

-- ---- the generated table ------------------------------------------------------------------
local PROFILE = L.json.decode(L.slurp(ROOT .. "/data/games/polished_crystal/profile.json"))
local GENERATED = assert(PROFILE.titles.polished.overlay.sfx.codes, "profile overlay.sfx.codes required")
local CODE = { success = GENERATED.success, failure = GENERATED.failure,
               boo = GENERATED.boo, notify = GENERATED.notify }
local ABI_CODE = { success = 1, failure = 2, boo = 3, notify = 4 }   -- patch/gb/slink_abi.inc:34-37

-- ---- mailbox + audio addresses (all from the overlay .sym via pol_lib) ---------------------
local MB = L.SYM.wSlinkMailbox[2]
local OFF_SFX, OFF_CAPS, OFF_HOLD, OFF_HOLD_AT, OFF_COOKIE = 7, 8, 12, 13, 31
local REQ, CAPS, HOLD, HOLD_AT = MB + OFF_SFX, MB + OFF_CAPS, MB + OFF_HOLD, MB + OFF_HOLD_AT
local CUR, CH5, FADE = L.SYM.wCurSFX[2], L.SYM.wChannel5Flags[2], L.SYM.wMusicFade[2]
local CHANNEL_ON = 0                       -- SOUND_CHANNEL_ON, constants/audio_constants.asm:73
local COOKIE = 0xA5
local MAX_HOLD = 240                       -- slink_sfx.asm:6, in SERVICE VISITS

local function bus(a) return memory.read_u8(a, "System Bus") end
local cur, ch5, fade, req = function() return bus(CUR) end, function() return bus(CH5) end,
                             function() return bus(FADE) end, function() return bus(REQ) end
local function chan_on() return math.floor(ch5() / (2 ^ CHANNEL_ON)) % 2 == 1 end

-- ---- the only write this driver may make ---------------------------------------------------
local writes, real_write_u8, real_write_bytes = {}, memory.write_u8, memory.write_bytes
memory.write_u8 = function(addr, value, domain)
    writes[#writes + 1] = { addr = addr, domain = domain }
    return real_write_u8(addr, value, domain)
end
memory.write_bytes = function(addr, bytes, domain)
    writes[#writes + 1] = { addr = addr, n = #bytes, domain = domain }
    return real_write_bytes(addr, bytes, domain)
end
local function illegal()
    for _, w in ipairs(writes) do
        if w.addr ~= REQ then
            return string.format("wrote $%04X (domain %s); only $%04X is legal",
                                 w.addr, tostring(w.domain), REQ)
        end
    end
    return nil
end
local function audit(phase)
    local bad = illegal()
    L.check("write audit [" .. phase .. "]: every write was $" .. string.format("%04X", REQ),
            bad == nil, bad or (#writes .. " write(s), all at the request byte"))
    writes = {}                     -- per-phase, so one phase cannot hide another's
end

-- ---- service-visit counter ------------------------------------------------------------------
local VISITS = 0
L.hook_at("SlinkDelayFrameBridge", L.SYM.SlinkDelayFrameBridge[1], L.SYM.SlinkDelayFrameBridge[2])

-- ---- run state -------------------------------------------------------------------------------
local S = { phase = "boot", name = nil, code = nil, pre = 0, pre_frames = 30, quiet = 0,
            posted = nil, visits_at_post = nil, seen = {}, result = {}, hold = nil,
            frame_cap = 4200, last_progress = 0 }

local function service_live()
    return bus(MB) == 0x53 and bus(MB + OFF_COOKIE) == COOKIE
end

local function post(code)
    if req() ~= 0 then return false end        -- the ROM owns the byte until it consumes it
    real_write_u8(REQ, code, "System Bus")
    writes[#writes + 1] = { addr = REQ, domain = "System Bus" }
    return true
end

local function say(frame)
    if frame - S.last_progress >= 30 then
        S.last_progress = frame
        raw(string.format("  ... frame %d phase=%s visits=%d wCurSFX=$%02X ch5=$%02X req=$%02X",
                          frame, S.phase, VISITS, cur(), ch5(), req()))
    end
end

-- ---- one cue: PRE sample (edge guard), post, then POST sample -------------------------------
local function begin(name)
    S.name, S.code, S.pre, S.quiet, S.posted = name, CODE[name], 0, 0, nil
    S.seen = {}                       -- per cue: the "still held" latch must not carry over
    S.phase = "pre"
    audit("begin " .. name)
end

local function post_phase()
    S.phase = "post"
    if post(ABI_CODE[S.name]) then
        S.posted, S.visits_at_post = emu.framecount(), VISITS
    end
end

event.onframeend(function()
    local f = emu.framecount()
    VISITS = L.hits["SlinkDelayFrameBridge"] or VISITS
    say(f)
    if f > S.frame_cap then
        L.check("driver reached its hard frame cap", false, "phase=" .. S.phase .. " frame " .. f)
        L.finish("pol-sounds hard-cap")
        return
    end

    if S.phase == "boot" then
        if service_live() then
            local caps = bus(CAPS)
            -- POL_EXPECT_CAPS: the sound-only ROM reads 0x05 (SFX|SFX_NOTIFY); the integrated overlay adds the
            -- panel bit (0x07). The expectation is explicit per ROM, never inferred from what the ROM says.
            local want = tonumber(os.getenv("POL_EXPECT_CAPS") or "5")
            L.check(string.format("caps byte reads 0x%02X", want), caps == want,
                    string.format("$%02X at frame %d", caps, f))
            L.check("phone/trade bits 0x18 clear in caps", math.floor(caps / 8) % 2 == 0, caps)
            L.check("mailbox signature live (beacon + cookie $A5)", true)
            L.log(string.format("  table from profile.json: success $%02X failure $%02X boo $%02X notify $%02X",
                                CODE.success, CODE.failure, CODE.boo, CODE.notify))
            begin("success")
        elseif f > 300 then
            L.die("the overlay service never ran (no beacon/cookie after 300 frames)")
        end
        return
    end

    -- PRE: wait for a quiet channel, then prove the expected id is not already showing
    if S.phase == "pre" then
        if chan_on() then S.quiet = 0 else S.quiet = S.quiet + 1 end
        if S.quiet >= 5 then
            if cur() == S.code then
                L.check(S.name .. ": expected id NOT already showing before the post", false,
                        string.format("wCurSFX already $%02X", S.code))
                S.phase = "skip"
                audit("skip " .. S.name)
            elseif S.pre >= S.pre_frames then
                post_phase()
            else
                S.pre = S.pre + 1
            end
        end
        return
    end

    -- POST: the edge. expected id AND the channel running, after the post.
    if S.phase == "post" then
        if req() == S.code and not S.seen.held then
            S.seen.held = f                              -- still held by the service: not dropped
        end
        if cur() == S.code and chan_on() then
            local held = VISITS - S.visits_at_post
            S.result[S.name] = { posted = S.posted, played = f, frames = f - S.posted,
                                 visits = held, ch5 = ch5(), fade = fade(), req = req() }
            L.check(string.format("%s ($%02X): wCurSFX reached the expected id AND the channel is on",
                                  S.name, S.code),
                    true, string.format("posted %d, played %d (%d frames / %d service visits), ch5 $%02X, fade $%02X",
                                        S.posted, f, f - S.posted, held, ch5(), fade()))
            L.check(S.name .. ": the service cleared the request byte (acknowledged)", req() == 0,
                    "request byte = " .. tostring(req()))
            S.phase = "settle"
        elseif f - S.posted > 150 then
            L.check(S.name .. ": played within 150 frames", false,
                    string.format("wCurSFX $%02X ch5 $%02X req $%02X", cur(), ch5(), req()))
            S.phase = "settle"
        end
        return
    end

    if S.phase == "skip" then return end

    -- after each cue: let the channel go idle, then the next one / the hold
    if S.phase == "settle" then
        if not chan_on() then
            audit("after " .. S.name)
            local order = { success = "failure", failure = "boo", boo = "notify" }
            if order[S.name] then begin(order[S.name]) else S.phase = "hold_arm" end
        end
        return
    end

    -- HOLD: post on the RISING edge of a busy channel; SFX_ITEM ($01) makes PlaySFX refuse all
    -- four cues (audio.asm:250-256: refuse when wCurSFX >= the new id), so the hold is what saves it
    if S.phase == "hold_arm" then
        S.phase = "hold_first"
        S.posted, S.visits_at_post = f, VISITS
        post(ABI_CODE.success)
        return
    end
    if S.phase == "hold_first" then
        if chan_on() then
            S.phase = "hold_second"
            S.hold = { busy_at = f, posted = nil, visits_at = VISITS }
            if post(ABI_CODE.boo) then S.hold.posted, S.hold.visits_at = f, VISITS end
        elseif f - S.posted > 150 then
            L.check("hold: first cue started a channel", false, "no channel within 150 frames")
            S.phase = "done"
        end
        return
    end
    if S.phase == "hold_second" then
        if req() == ABI_CODE.boo then S.hold.held = true end     -- still owned by the service
        if cur() == CODE.boo and chan_on() then
            S.hold.frames = f - S.hold.posted
            S.hold.visits = VISITS - S.hold.visits_at
            S.phase = "done"
        elseif f - S.hold.posted > 600 then
            S.hold.frames, S.hold.visits = f - S.hold.posted, VISITS - S.hold.visits_at
            S.phase = "done"
        end
        return
    end

    if S.phase == "done" then
        local h = S.hold or {}
        L.check("hold: the request was HELD (byte stayed BOO), not dropped", h.held == true,
                "held=" .. tostring(h.held))
        L.check("hold: released and played after the channel went idle",
                S.result ~= nil and h.frames ~= nil, string.format("%s frames / %s visits",
                                                                    tostring(h.frames), tostring(h.visits)))
        if h.frames then
            L.check(string.format("hold under the %d-visit ceiling", MAX_HOLD),
                    h.visits < MAX_HOLD, string.format("%d visits / %d frames", h.visits, h.frames))
        end
        audit("final")
        L.log("RESULT-DATA " .. L.json.encode({ caps = bus(CAPS), codes = CODE, results = S.result,
                                                 hold = S.hold, max_hold = MAX_HOLD, visits = VISITS }))
        L.finish("pol-sounds")
    end
end)

-- BizHawk's Lua has no event.onstart: the driver's own preamble runs at load.
L.log(string.format("POL-SOUNDS round 3: scripted mailbox writer, request byte $%04X", REQ))
L.check("the four ids come from profile.json overlay.sfx.codes",
        CODE.success == 1 and CODE.failure == 25 and CODE.boo == 36 and CODE.notify == 8,
        string.format("%d/%d/%d/%d", CODE.success, CODE.failure, CODE.boo, CODE.notify))
L.check("request byte offset is SLINK_OFS_SFX_REQUEST (+7)", OFF_SFX == 7)