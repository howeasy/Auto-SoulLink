-- lua/gen1/panel.lua — the in-game SLINK panel: the client paints, the cartridge reveals.
--
-- The companion patch owns the SCREEN (slink.asm:197-344): it whites out, draws a fallback,
-- sets +9 = AWAIT and polls for STAGED. We paint 18 rows x 20 tiles straight into wTileMap
-- while the screen is white, publish the page count, and hand it back. Nothing is stored in
-- the cartridge's own memory because there is none: Red/Blue have thirty free WRAM bytes.
--
-- All writes go through the injected writes.lua instance under its own "panel" window, so a
-- mailbox byte that happens to read 1 on an UNPATCHED cartridge cannot paint over the map:
-- present() asks the capability bits first, and only an OBSERVED transition into AWAIT arms.
local P = {}

-- slink.asm:38-66. The vanilla companion patch's mailbox; an overlay build names its own
-- through profile.trade.mailbox (PLAN A4: pureRGB's is linker-placed in the bank-1 tail,
-- $DEE2 being inside its box data). The offsets below are the shared mailbox ABI.
local MAILBOX = 0xDEE2
local BEACON  = { 0x53, 0x4C, 0x4E, 0x4B }  -- 'SLNK', rewritten every VBlank
local ABI     = MAILBOX + 4
local SFX     = MAILBOX + 7                 -- SLINK_SFX_REQUEST: client -> patch, a semantic code
local CAPS    = MAILBOX + 8                 -- SLINK_CAPS
local STATE   = MAILBOX + 9                 -- SLINK_PANEL_STATE
local PAGE    = MAILBOX + 10                -- patch -> client: page wanted
local PAGES   = MAILBOX + 11                -- client -> patch: page count (0 reads as one)
local OFF_ABI, OFF_SFX, OFF_CAPS, OFF_STATE, OFF_PAGE, OFF_PAGES = 4, 7, 8, 9, 10, 11
local CAP_SFX   = 0x01                      -- SLINK_CAP_SFX: the main-thread SFX service is built in
local CAP_PANEL = 0x02                      -- SLINK_CAP_PANEL
local CAP_SFX_NOTIFY = 0x04                 -- SLINK_CAP_SFX_NOTIFY: the ROM knows code 4
local CLOSED, AWAIT, STAGED = 0, 1, 2
-- slink.asm SlinkSfxService: what the request byte may carry. The ROM resolves the code to a
-- sound id for the audio bank loaded at play time (ids are per bank), holds it through fades
-- and busy channels, and zeroes the byte when it plays. Anything else is consumed unplayed.
local SFX_SUCCESS, SFX_FAILURE, SFX_BOO, SFX_NOTIFY = 1, 2, 3, 4
-- The server speaks Gen 3 SE numbers (docs/protocol.md play_sound); this is the Gen 1 binding.
-- SUCCESS is the long fanfare, kept for nuzlocke start / shiny (95); everyday success (25)
-- is the short notify blip on a cartridge that has it (sfx_code_for).
local SFX_CODE_FOR_GEN3_ID = { [25] = SFX_SUCCESS, [26] = SFX_FAILURE, [22] = SFX_BOO, [95] = SFX_SUCCESS }
local SFX_QUEUE_MAX = 4                     -- a burst beyond this drops the OLDEST: the newest news wins

local COLS, ROWS = 20, 18
local TILES      = COLS * ROWS              -- 360, one whole page
local MAX_PAGES  = 8                        -- 144 rows; the patch pages with A, not forever
local BLANK      = 0x7F
-- The patch polls <= 90 frames (SLINK_STAGE_TIMEOUT) and then reveals the fallback for good.
-- Ours is tighter and, unlike the patch's, is measured from the transition WE observed, so a
-- reply that lands after it is held rather than painted over a revealed fallback.
local DEADLINE = 60

P.MAILBOX, P.CAPS, P.STATE, P.PAGE, P.PAGES, P.SFX = MAILBOX, CAPS, STATE, PAGE, PAGES, SFX
P.CLOSED, P.AWAIT, P.STAGED = CLOSED, AWAIT, STAGED
P.SFX_SUCCESS, P.SFX_FAILURE, P.SFX_BOO, P.SFX_NOTIFY = SFX_SUCCESS, SFX_FAILURE, SFX_BOO, SFX_NOTIFY
P.SFX_CODE_FOR_GEN3_ID, P.SFX_QUEUE_MAX = SFX_CODE_FOR_GEN3_ID, SFX_QUEUE_MAX
P.ROWS, P.COLS, P.MAX_PAGES, P.DEADLINE = ROWS, COLS, MAX_PAGES, DEADLINE

--- ASCII -> Gen 1 tile id (memory_gb.lua:1555-1568, verbatim).
--- Verified against the ROM: "POK<e>DEX@" is 8F 8E 8A BA 83 84 97 50, so 'A' is $80; $7F is
--- the space the menu rows are padded with; digits are the $F6-$FF block. Unmapped characters
--- become spaces rather than guesses — a wrong tile is a glyph the player has to interpret.
--- The whitelist and the server's payload generator have to agree: '-' was missing here while
--- server.py emitted dead-zone rows as "-" .. area, so every one of them lost its dash.
local function _tile_for(ch)
    local b = string.byte(ch)
    if b >= 65 and b <= 90  then return 0x80 + (b - 65) end   -- A-Z
    if b >= 97 and b <= 122 then return 0xA0 + (b - 97) end   -- a-z
    if b >= 48 and b <= 57  then return 0xF6 + (b - 48) end   -- 0-9
    if b == 47 then return 0xF3 end                           -- '/'
    if b == 45 then return 0xE3 end                           -- '-' (charmap.asm:163)
    return BLANK                                              -- space, and anything unknown
end
P.tile_for = _tile_for

--- The same whitelist over the foundation's ONE charmap object (reads.lua R.charmap): letters,
--- digits, '/' and '-' by their glyph codes, everything else BLANK. On vanilla this yields
--- exactly _tile_for's bytes; on pureRGB it follows the pack's charmap.lua.
function P.tile_for_charmap(cm)
    local codes = cm and cm.codes
    if not codes then return _tile_for end
    return function(ch)
        if ch:match("^[A-Za-z0-9/%-]$") then return codes[ch] or BLANK end
        return BLANK
    end
end

function P.new(profile, io, writes, sanitize)
    -- Presence, not type(...) == "function": under lupa the injected io/sanitize may be
    -- Python callables, which Lua sees as userdata (trade_overlay.lua gets Lua wrappers
    -- built in entry.lua and can afford the stricter check; this module is handed deps.io).
    assert(type(profile) == "table" and type(profile.ram) == "table", "Gen 1 title profile required")
    assert(type(io) == "table" and io.read_u8 and io.framecount,
           "injected io with read_u8/framecount required")
    assert(type(writes) == "table" and writes.arm and writes.disarm and writes.write_bytes,
           "writes.lua instance required")
    assert(sanitize, "injected sanitize required (hud.lua)")
    local tilemap = assert(profile.ram.wTileMap, "profile.ram.wTileMap required")
    -- the mailbox and its ABI bytes, per cartridge build (module defaults = vanilla patch)
    local MAILBOX = profile.trade and profile.trade.mailbox or MAILBOX
    local ABI, CAPS, STATE = MAILBOX + OFF_ABI, MAILBOX + OFF_CAPS, MAILBOX + OFF_STATE
    local PAGE, PAGES, SFX = MAILBOX + OFF_PAGE, MAILBOX + OFF_PAGES, MAILBOX + OFF_SFX
    local tile_for = P.tile_for_charmap(profile.charmap)

    -- The only bytes this window may ever touch. write_bytes is expected to check the FULL
    -- interval; the predicate takes an optional length so it answers for either convention.
    local function allow(addr, n)
        if type(addr) ~= "number" then return false end
        local last = addr + (n or 1) - 1
        if addr >= tilemap and last < tilemap + TILES then return true end
        return (addr == STATE or addr == PAGES or addr == SFX) and last == addr
    end

    -- `mailbox` is read by the harness (duo VBlank-counter probe) so it never hard-codes vanilla's.
    local self = { pages = nil, tiles = nil, last_state = nil, await_frame = nil, armed = false, mailbox = MAILBOX,
                   sfx_queue = {} }

    local function u8(addr)
        local v = io.read_u8(addr)
        if type(v) ~= "number" then return nil end
        return math.floor(v) % 256
    end

    --- Does THIS cartridge have the panel? Asked of the capability bits rather than inferred
    --- from the ABI number, because a build may ship one feature without the other.
    function self:present()
        for i = 1, 4 do
            if u8(MAILBOX + i - 1) ~= BEACON[i] then return false end
        end
        local caps = u8(CAPS)
        return caps ~= nil and caps ~= 0xFF and (caps & CAP_PANEL) ~= 0
    end

    function self:abi() return u8(ABI) or 0 end

    --- The Gen 1 code for a server `play_sound` id, or nil for ids Gen 1 has no sound for.
    function self:sfx_code_for(sound_id)
        if sound_id == 25 then
            -- an older cartridge drops code 4 unplayed: it keeps the fanfare instead
            local caps = u8(CAPS)
            if caps ~= nil and caps ~= 0xFF and (caps & CAP_SFX_NOTIFY) ~= 0 then return SFX_NOTIFY end
        end
        return SFX_CODE_FOR_GEN3_ID[sound_id]
    end

    --- Does THIS cartridge play sound? Same beacon, the SFX bit of the same caps byte.
    function self:sfx_present()
        for i = 1, 4 do
            if u8(MAILBOX + i - 1) ~= BEACON[i] then return false end
        end
        local caps = u8(CAPS)
        return caps ~= nil and caps ~= 0xFF and (caps & CAP_SFX) ~= 0
    end

    --- Write one code to the request byte, through the armed window like every other
    --- mailbox write, so the receipts log shows it. Only when the byte reads 0: the ROM
    --- clears it when it plays, and overwriting a request it is still HOLDING (fade, busy
    --- channel) would lose that one. Returns true when written.
    local function post_sfx(code)
        if u8(SFX) ~= 0 then return false end
        writes:arm("panel", allow)
        local ok, err = pcall(function() writes:write_bytes(SFX, { code }) end)
        writes:disarm()
        if not ok then error(err, 0) end
        return true
    end

    --- Ask the cartridge to play a notification. `code` is one of P.SFX_*; a Gen 3 SE id
    --- from a `play_sound` command is mapped through P.SFX_CODE_FOR_GEN3_ID by the caller.
    --- Posted now if the request byte is free, else queued and drained by service().
    function self:request_sfx(code)
        if code ~= SFX_SUCCESS and code ~= SFX_FAILURE and code ~= SFX_BOO and code ~= SFX_NOTIFY then return false end
        if not self:sfx_present() then return false end
        if #self.sfx_queue == 0 and post_sfx(code) then return true end
        if #self.sfx_queue >= SFX_QUEUE_MAX then table.remove(self.sfx_queue, 1) end
        self.sfx_queue[#self.sfx_queue + 1] = code
        return true
    end

    function self:awaiting() return u8(STATE) == AWAIT end

    --- Forget the held rows and any queued sounds (WRAM clear / rejected hello — the caller
    --- owns that policy).
    function self:clear() self.pages, self.tiles, self.sfx_queue = nil, nil, {} end

    --- Drop queued sounds only: the run switched native sounds off, so nothing accepted
    --- under the old setting may still post after it.
    function self:clear_sfx() self.sfx_queue = {} end

    --- Validate, sanitize and PRE-RENDER every page. Nothing is computed inside the armed
    --- window, and a rejected payload leaves the previous one untouched rather than half-held.
    function self:hold(rows)
        if type(rows) ~= "table" then return nil, "panel rows must be a list" end
        local n = #rows
        if n > ROWS * MAX_PAGES then
            return nil, "panel rows exceed " .. (ROWS * MAX_PAGES) .. " (" .. MAX_PAGES .. " pages)"
        end
        local clean = {}
        for i = 1, n do
            if type(rows[i]) ~= "string" then return nil, "panel row " .. i .. " is not a string" end
            local s = sanitize(rows[i])
            if type(s) ~= "string" then return nil, "panel row " .. i .. " did not sanitize to a string" end
            clean[i] = s
        end
        if n == 0 then self:clear() return true end   -- nothing to show; never open on blanks

        local pages = math.ceil(n / ROWS)
        local tiles = {}
        for p = 1, pages do
            local page = {}
            for r = 0, ROWS - 1 do
                local text = clean[(p - 1) * ROWS + r + 1] or ""
                for c = 1, COLS do
                    local ch = text:sub(c, c)               -- pad AND truncate to 20
                    page[r * COLS + c] = ch == "" and BLANK or tile_for(ch)
                end
            end
            tiles[p] = page
        end
        self.pages, self.tiles = pages, tiles
        return true
    end

    --- Paint the page the patch asked for and hand the screen back. Requires an armed window.
    function self:stage()
        assert(self.tiles, "panel has no held rows")
        local page = u8(PAGE) or 0
        if page >= self.pages then page = self.pages - 1 end   -- never index past the end
        writes:write_bytes(tilemap, self.tiles[page + 1])
        writes:write_bytes(PAGES, { math.min(self.pages, 255) })
        writes:write_bytes(STATE, { STAGED })                  -- published last
        return page
    end

    local function tick()
        local frame = io.framecount()
        -- One queued sound per frame, only once the ROM has consumed the previous request.
        if #self.sfx_queue > 0 then
            if not self:sfx_present() then
                self.sfx_queue = {}                       -- the cartridge changed under us
            elseif post_sfx(self.sfx_queue[1]) then
                table.remove(self.sfx_queue, 1)
            end
        end
        if not self:present() then
            -- Unpatched or gone: $DEEB is ordinary WRAM, so nothing it says is a transition.
            self.last_state, self.await_frame = nil, nil
            return
        end
        local state, prev = u8(STATE), self.last_state
        self.last_state = state
        if state ~= AWAIT then
            self.await_frame = nil
        elseif prev ~= nil and prev ~= AWAIT then
            -- CLOSED->AWAIT on open, STAGED->AWAIT on a page turn (slink.asm:236-237,248-276).
            -- Each gets its own fresh deadline; an AWAIT that merely PERSISTS keeps the old
            -- one, and an AWAIT that was already there at first sight (prev == nil) is of
            -- unknown age, so that open shows the fallback and we never paint it.
            self.await_frame = frame
        end
        if state ~= AWAIT or not self.tiles or not self.await_frame then return end
        if type(frame) ~= "number" or frame - self.await_frame > DEADLINE then return end

        self.armed = true
        writes:arm("panel", allow)
        local ok, err = pcall(function() return self:stage() end)
        writes:disarm()
        self.armed = false
        if not ok then error(err, 0) end
        -- WE wrote STAGED, so record it rather than waiting to observe it: a client that
        -- misses frames must still see the patch's next AWAIT as a page turn, not a persist.
        self.last_state = STAGED
    end

    --- Called every frame, before anything else arms a window: the player may be sitting in
    --- the START menu with the overworld checkpoint long behind them.
    function self:service()
        local ok, err = pcall(tick)
        if not ok then
            -- Only if tick died with the window still open; the normal path closed it itself
            -- and a second disarm would clobber whatever the caller arms next.
            if self.armed then
                pcall(function() writes:disarm() end)
                self.armed = false
            end
            return nil, tostring(err)
        end
        return true
    end

    self.allow = allow
    return self
end

return P
