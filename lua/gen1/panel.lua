-- lua/gen1/panel.lua — the Gen 1 binder onto lua/gb_panel.lua (P4.1d): the client paints,
-- the cartridge reveals.
--
-- The companion patch owns the SCREEN (slink.asm:197-344); gb_panel.lua owns the handshake,
-- the tile renderer and the SFX queue. This file supplies the Gen 1 facts: the vanilla
-- mailbox, wTileMap, no CGB attrmap, the Gen 1 charmap, the Gen 3 SE -> Gen 1 code map and
-- the deadline. Red/Blue have thirty free WRAM bytes, so nothing is stored cartridge-side.
local module_dir = debug.getinfo(1, "S").source:match("^@(.+[/\\])[^/\\]+$")
local G = dofile(assert(module_dir, "gen1/panel.lua must be dofile'd by path") .. "../gb_panel.lua")
local P = {}

-- slink.asm:38-66. The vanilla companion patch's mailbox; an overlay build names its own
-- through profile.trade.mailbox (PLAN A4: pureRGB's is linker-placed in the bank-1 tail,
-- $DEE2 being inside its box data). The offsets are the shared ABI (patch/gb/slink_abi.inc).
local MAILBOX = 0xDEE2
local SFX_SUCCESS, SFX_FAILURE, SFX_BOO, SFX_NOTIFY = G.SFX_SUCCESS, G.SFX_FAILURE, G.SFX_BOO, G.SFX_NOTIFY
-- The server speaks Gen 3 SE numbers (docs/protocol.md play_sound); this is the Gen 1 binding.
-- SUCCESS is the long fanfare, kept for nuzlocke start / shiny (95); everyday success (25)
-- is the short notify blip on a cartridge that has it (sfx_code_for).
local SFX_CODE_FOR_GEN3_ID = { [25] = SFX_SUCCESS, [26] = SFX_FAILURE, [22] = SFX_BOO, [95] = SFX_SUCCESS }
local BLANK = G.BLANK
-- The patch polls <= 90 frames (SLINK_STAGE_TIMEOUT) and then reveals the fallback for good.
-- Ours is tighter and, unlike the patch's, is measured from the transition WE observed, so a
-- reply that lands after it is held rather than painted over a revealed fallback.
local DEADLINE = 60

P.MAILBOX, P.BEACON = MAILBOX, G.BEACON
P.ABI, P.SFX, P.CAPS = MAILBOX + G.OFF_ABI, MAILBOX + G.OFF_SFX, MAILBOX + G.OFF_CAPS
P.STATE, P.PAGE, P.PAGES = MAILBOX + G.OFF_STATE, MAILBOX + G.OFF_PAGE, MAILBOX + G.OFF_PAGES
P.CAP_SFX, P.CAP_PANEL, P.CAP_SFX_NOTIFY = G.CAP_SFX, G.CAP_PANEL, G.CAP_SFX_NOTIFY
P.CLOSED, P.AWAIT, P.STAGED = G.CLOSED, G.AWAIT, G.STAGED
P.SFX_SUCCESS, P.SFX_FAILURE, P.SFX_BOO, P.SFX_NOTIFY = SFX_SUCCESS, SFX_FAILURE, SFX_BOO, SFX_NOTIFY
P.SFX_CODE_FOR_GEN3_ID, P.SFX_QUEUE_MAX = SFX_CODE_FOR_GEN3_ID, G.SFX_QUEUE_MAX
P.ROWS, P.COLS, P.MAX_PAGES, P.DEADLINE = G.ROWS, G.COLS, G.MAX_PAGES, DEADLINE

--- ASCII -> Gen 1 tile id (ported verbatim from the old shared memory_gb.lua, since removed).
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
    assert(type(profile) == "table" and type(profile.ram) == "table", "Gen 1 title profile required")
    local self = G.new({
        -- the mailbox per cartridge build (module default = vanilla patch)
        mailbox  = profile.trade and profile.trade.mailbox or MAILBOX,
        tilemap  = assert(profile.ram.wTileMap, "profile.ram.wTileMap required"),
        attrmap  = false,                               -- DMG: no attribute map
        charmap  = P.tile_for_charmap(profile.charmap),
        se_map   = SFX_CODE_FOR_GEN3_ID,
        deadline = DEADLINE,
    }, io, writes, sanitize)

    --- The Gen 1 code for a server `play_sound` id, or nil for ids Gen 1 has no sound for.
    local base_code_for = self.sfx_code_for
    function self:sfx_code_for(sound_id)
        -- an older cartridge drops code 4 unplayed: it keeps the fanfare instead
        if sound_id == 25 and self:caps_has(G.CAP_SFX_NOTIFY) then return SFX_NOTIFY end
        return base_code_for(self, sound_id)
    end
    return self
end

return P
