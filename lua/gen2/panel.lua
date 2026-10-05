-- lua/gen2/panel.lua — the Gen 2 binder onto lua/gb_panel.lua (P4.1f): the client paints,
-- the cartridge reveals.
--
-- gb_panel.lua owns the handshake, the tile renderer and the SFX queue. This file supplies the
-- Gen 2 facts, every address from the profile's generated `overlay` block (tools/gen_gen2_profile.py
-- reads it from the pinned data/gen2/<title>_slink.sym): wSlinkMailbox, wTilemap, wAttrmap, the
-- pack's charmap and the deadline. It adds one Gen 2 policy on top: FRESHNESS. Native Reset
-- leaves the old mailbox in WRAM0 for 32 DelayFrames before Init clears it, and New Game never
-- clears it (patch/gen2/src/slink.asm tail), so a beacon alone can be last session's. The
-- mailbox counts as live only while the service's init cookie reads $A5 AND its sampled frame
-- counter has moved within STALL frames. Until then the cartridge reads ABSENT and nothing paints.
local module_dir = debug.getinfo(1, "S").source:match("^@(.+[/\\])[^/\\]+$")
local G = dofile(assert(module_dir, "gen2/panel.lua must be dofile'd by path") .. "../gb_panel.lua")
local Arbiter = dofile(module_dir .. "../sfx_arbiter.lua")
local P = {}

-- patch/gb/slink_abi.inc: version 3, the LE sampled counter at +5..6. patch/gen2/src/slink.asm:
-- SLINK_SAMPLE_VALID = mailbox + SLINK_PUBLIC_SIZE + 1 (= +31) holds SLINK_SAMPLE_COOKIE $A5,
-- written by the service's first visit after Init zeroed the mailbox.
-- tests/unit/test_gen2_panel.py pins all of these to the .inc/.asm.
P.ABI_VERSION, P.OFF_COUNTER, P.OFF_COOKIE, P.COOKIE = 3, 5, 31, 0xA5
-- Codex's panel plan (P4.1e): the panel loads SCGB_DIPLOMA's neutral palettes and paints the
-- attrmap with palette 0, and WaitBGMap2 moves attrs and tiles together. Gold/Silver run in both
-- modes, but their own ClearScreen fills wAttrmap without testing hCGB (pokegold home/text.asm
-- ClearScreen); only the VRAM push is gated on hCGB (home/map.asm .PushAttrmap). So painting the
-- buffer is mode-independent, the same as the game's own clear. Crystal is CGB-only (-C).
P.ATTR_FILL = 0
-- The patch stages for <= 90 DelayFrames and then reveals the fallback. Ours is tighter, measured
-- from the transition WE observed (the Gen 1 value).
P.DEADLINE = 60
-- The counter only moves when DelayFrame runs the service; the START menu and the panel poll call
-- it every frame. A second without movement means the service isn't running and the bytes are stale.
P.STALL = 60
-- P4.2b: the server speaks Gen 3 SE numbers (docs/protocol.md play_sound); this is the Gen 2
-- binding onto gb_panel's semantic codes. The ROM owns the native ids (patch/gen2/src/sfx.asm
-- .sounds: SUCCESS SFX_ITEM $01, FAILURE SFX_WRONG $19, BOO SFX_BUMP $24, NOTIFY SFX_READ_TEXT_2 $08).
-- Gen 1's shape: SUCCESS is the fanfare kept for nuzlocke start / shiny (95); everyday success (25)
-- is the short notify blip on a cartridge that advertises SFX_NOTIFY (sfx_code_for). An id with no
-- row here is not a Gen 2 sound: sfx_code_for answers nil and nothing is ever sent for it.
P.SE_BOO, P.SE_SUCCESS, P.SE_FAILURE, P.SE_SHINY = 22, 25, 26, 95
P.SFX_SUCCESS, P.SFX_FAILURE, P.SFX_BOO, P.SFX_NOTIFY = G.SFX_SUCCESS, G.SFX_FAILURE, G.SFX_BOO, G.SFX_NOTIFY
P.SFX_CODE_FOR_GEN3_ID = { [P.SE_SUCCESS] = P.SFX_SUCCESS, [P.SE_FAILURE] = P.SFX_FAILURE,
                           [P.SE_BOO] = P.SFX_BOO, [P.SE_SHINY] = P.SFX_SUCCESS }
-- One cue per frame (lua/sfx_arbiter.lua), ranked by semantic code: a terminal linked faint lands
-- force_faint's play_sound 26 and game_over's local 26 beside anything else in one reply; the
-- failure is the news. Unranked codes (success/notify) are generic.
P.SFX_RANKS = { [P.SFX_FAILURE] = 2, [P.SFX_BOO] = 1 }
P.BLANK = G.BLANK
P.WRAM0_LO, P.WRAM0_HI = 0xC000, 0xD000   -- hardware: WRAM0 is never banked; every panel byte is in it

--- ASCII -> Gen 2 tile id over the pack's generated charmap (data/games/gen2_*/charmap.lua
--- `encoding`). A tile write shows a glyph only for the font block ($7F space .. $FF); a code
--- below it ('@' terminator, '#' the POKé control) is text-engine control, never a tile, so it
--- and anything unmapped become spaces rather than guesses.
function P.tile_for(charmap)
    local enc = assert(charmap and charmap.encoding, "Gen 2 charmap.encoding required")
    return function(ch)
        local b = enc[ch]
        if type(b) == "number" and b >= G.BLANK and b <= 0xFF then return b end
        return G.BLANK
    end
end

--- The panel's own write window: a shared write_permit, armed by gb_panel with its allow()
--- predicate. It never shares a permit with the party/box writers.
--- narrow (optional) = {base, size}: an ADDITIONAL hard bound, for a cartridge whose panel
--- writes only its own mailbox (Polished stages text, never pixels, so nothing outside the
--- mailbox is ever legitimate). When absent the permit keeps its WRAM0-wide shape, which is what
--- the tile-staging titles need.
function P.writes(io, Permit, narrow)
    assert(Permit and Permit.new, "shared write permit factory required")
    if narrow ~= nil then
        assert(type(narrow) == "table" and type(narrow.base) == "number" and type(narrow.size) == "number"
               and narrow.base % 1 == 0 and narrow.size > 0,
               "narrow panel region needs base and size")
    end
    local permit = Permit.new({
        write_u8 = function(addr, value, domain) return io.write_u8(addr, value, domain) end,
        domains = { ["System Bus"] = {
            bounds = function(addr, n, reason)
                -- P4.5c: lua/gen2/phone.lua posts one byte (+32 PHONE_REQUEST) under "phone"
                -- `narrow`, when given, is the ONLY range this permit may ever touch: every
                -- interval is checked whole, so a span that starts inside and runs out is refused.
                if reason ~= "panel" and not (reason == "phone" and n == 1) then return false end
                if narrow then
                    return addr >= narrow.base and addr + n <= narrow.base + narrow.size
                       and addr >= P.WRAM0_LO and addr + n <= P.WRAM0_HI
                end
                return addr >= P.WRAM0_LO and addr + n <= P.WRAM0_HI
            end,
            mapped = function() return true end,          -- WRAM0: no bank to check
            pointer_stable = function() return true end,  -- concrete addresses from the profile
        } },
        -- gb_panel arms and disarms around each page inside one frame's service().
        lifetime = { capture = function() return {} end, valid = function() return true end },
        provenance = function(domain, addr, n, reason)
            return { addr = addr, n = n, why = reason, domain = domain, frame = io.framecount() }
        end,
    })
    local arm, write = permit.arm, permit.write_bytes
    return {
        log = permit.log,
        arm = function(_, reason, allow)
            return arm(permit, reason, allow and function(domain, addr, n)
                return domain == "System Bus" and allow(addr, n)
            end or nil)
        end,
        disarm = function() permit:disarm() end,
        write_bytes = function(_, addr, bytes) return write(permit, "System Bus", addr, bytes) end,
    }
end

--- profile: the selected title profile (entry.lua); its `overlay` block names the addresses.
--- charmap: the pack's charmap.lua. io: read_u8/framecount. writes: P.writes(...). sanitize: hud.lua's.
--- Returns nil, why when the profile has no overlay block (no SLink build exists for it).
function P.new(profile, charmap, io, writes, sanitize)
    local ov = type(profile) == "table" and profile.overlay
    if type(ov) ~= "table" or type(ov.ram) ~= "table" then
        return nil, "profile has no overlay block: no SLink cartridge build for this title"
    end
    local ram = ov.ram
    local MAILBOX = assert(ram.wSlinkMailbox, "overlay.ram.wSlinkMailbox required")
    -- A cartridge whose overlay stages TEXT (Polished: native PrintText pages, no graphics lease
    -- -- docs/polished/PANEL.md E7) publishes profile.overlay.panel. A tile-staging build has no
    -- such block and the tile path is byte-for-byte unchanged. Every number here is a generated
    -- overlay fact, not a constant in this file.
    local pan = ov.panel
    if pan ~= nil then
        assert(type(pan) == "table" and pan.base == ram.wSlinkPanelText,
               "overlay.panel.base must be the overlay sym's wSlinkPanelText")
    end
    local self = G.new({
        mailbox  = MAILBOX,
        tilemap  = assert(ram.wTilemap, "overlay.ram.wTilemap required"),
        attrmap  = pan and false or { base = assert(ram.wAttrmap, "overlay.ram.wAttrmap required"),
                                       fill = P.ATTR_FILL },
        charmap  = P.tile_for(charmap),
        se_map   = P.SFX_CODE_FOR_GEN3_ID,
        deadline = P.DEADLINE,
        rows_per_page = pan and pan.lines or nil,
        text     = pan and { base = pan.base, stride = pan.stride, lines = pan.lines,
                             line_max = pan.line_max, terminator = pan.terminator } or nil,
    }, io, writes, sanitize)

    local function u8(addr)
        local v = io.read_u8(addr)
        return type(v) == "number" and math.floor(v) % 256 or nil
    end
    local last_counter, moved_at, fresh = nil, nil, false

    --- The overlay's own mailbox signature: beacon + this build's ABI byte + the service's init cookie.
    local function signature_ok()
        return u8(MAILBOX) == G.BEACON[1] and u8(MAILBOX + 1) == G.BEACON[2]
               and u8(MAILBOX + 2) == G.BEACON[3] and u8(MAILBOX + 3) == G.BEACON[4]
               and u8(MAILBOX + G.OFF_ABI) == P.ABI_VERSION and u8(MAILBOX + P.OFF_COOKIE) == P.COOKIE
    end

    --- One observation per frame: live = beacon + version 3 + cookie, with the counter moving.
    local function observe()
        local frame = io.framecount()
        local ok = signature_ok()
        local lo, hi = u8(MAILBOX + P.OFF_COUNTER), u8(MAILBOX + P.OFF_COUNTER + 1)
        if not ok or lo == nil or hi == nil or type(frame) ~= "number" then
            last_counter, moved_at, fresh = nil, nil, false
            return
        end
        local counter = lo + hi * 256
        if last_counter ~= nil and counter ~= last_counter then
            moved_at, fresh = frame, true
        elseif moved_at == nil or frame - moved_at > P.STALL then
            fresh = false   -- never seen moving, or stalled: last session's bytes or no service
        end
        last_counter = counter
    end

    function self:fresh() return fresh end

    --- The mailbox ABI for the server's companion evidence, or nil: read from the cartridge's own RAM right now,
    --- exactly like Gen 3's companion_live (signature + ABI, no counter). A clean cartridge has no SLNK service, so
    --- the beacon, the version byte and the init cookie do not all read right and the evidence is ABSENT.
    --- Deliberately NOT tied to `fresh`: the hello is final (a refusal is never retried), and `fresh` needs two
    --- observations of a moving counter, which a script loaded mid-game or a battle text prompt (no DelayFrame, so
    --- no service tick) would not have yet. The counter guard stays on what PAINTS, not on what this cartridge IS.
    function self:companion_abi()
        if signature_ok() then return u8(MAILBOX + G.OFF_ABI) end
        return nil
    end

    local base_present, base_sfx_present, base_service = self.present, self.sfx_present, self.service
    local base_request, base_clear, base_clear_sfx, base_code_for =
        self.request_sfx, self.clear, self.clear_sfx, self.sfx_code_for
    local arbiter = Arbiter.new(P.SFX_RANKS)
    local function drop() arbiter.flush(function() end) end
    function self:present() return fresh and base_present(self) end
    function self:sfx_present() return fresh and base_sfx_present(self) end

    --- The code for a server play_sound id on THIS cartridge, or nil (dropped, never sent).
    function self:sfx_code_for(sound_id)
        if sound_id == P.SE_SUCCESS and self:caps_has(G.CAP_SFX_NOTIFY) then return P.SFX_NOTIFY end
        return base_code_for(self, sound_id)
    end

    --- Record a semantic code for this frame; service() posts the frame's one winner through
    --- gb_panel's queue. Only the four codes, only on a live SFX cartridge.
    function self:request_sfx(code)
        if code ~= P.SFX_SUCCESS and code ~= P.SFX_FAILURE and code ~= P.SFX_BOO and code ~= P.SFX_NOTIFY then
            return false
        end
        if not self:sfx_present() then return false end
        arbiter.request(code)
        return true
    end
    function self:clear() drop() return base_clear(self) end
    function self:clear_sfx() drop() return base_clear_sfx(self) end

    function self:service()
        local ok, err = pcall(observe)
        if not ok then fresh = false return nil, tostring(err) end
        ok, err = pcall(arbiter.flush, function(code) base_request(self, code) end)
        if not ok then return nil, tostring(err) end
        return base_service(self)
    end
    return self
end

return P
