-- lua/gen2/polished_sounds.lua — the Polished Crystal sound writer (POL-SOUNDS).
--
-- WHAT THIS IS. The overlay's sound service (patch/polished/src/slink_sfx.asm) is reached only
-- through the DelayFrame bridge's foreground service and plays the shared semantic codes through
-- the cartridge's own PlaySFX. This module owns the HOST half of that one byte: it decides when
-- a code may be posted, and it is the only thing here that can write.
--
-- WHY IT IS SEPARATE FROM compose_polished. lua/gen2/entry.lua compose_polished hands the panel
-- a REFUSE-ALL writer (hardening H1, tests/unit/test_polished_hardening.py): the composition has
-- no Polished write receipt, so nothing may reach io.write_u8. Turning the SFX bit into a grant
-- therefore cannot be a one-line flip of that object. This file does not edit that composition;
-- it supplies the narrow permit and the guard the coordinator can wire, and its own tests build
-- the permit themselves.
--
-- THE PERMIT IS MAILBOX-ONLY. Not "WRAM0", not "the panel window": exactly one address, the SFX
-- request byte (patch/gb/slink_abi.inc SLINK_OFS_SFX_REQUEST), one byte at a time. wTilemap,
-- wAttrmap and the panel state/page bytes are ordinary WRAM0 on this cartridge and stay out of
-- reach, so a code path that tries to paint raises instead of writing.
--
-- THE NATIVE IDS ARE NOT HERE. They belong to the ROM: profile.overlay.sfx.codes carries the
-- semantic-code -> native-id table that tools/gen_polished_profile.py reads out of the pinned
-- constants/sfx_constants.asm, and the overlay resolves it in .sounds. This module only ever
-- handles the four semantic codes.
local module_dir = debug.getinfo(1, "S").source:match("^@(.+[/\\])[^/\\]+$")
local Panel = dofile(assert(module_dir, "gen2/polished_sounds.lua must be dofile'd by path") .. "panel.lua")
local Permit = dofile(module_dir .. "../write_permit.lua")
local G = dofile(module_dir .. "../gb_panel.lua")
local S = {}

S.OFF_SFX = G.OFF_SFX
S.CAP_SFX = G.CAP_SFX
S.CAP_SFX_NOTIFY = G.CAP_SFX_NOTIFY
S.SFX_SUCCESS, S.SFX_FAILURE, S.SFX_BOO, S.SFX_NOTIFY =
    G.SFX_SUCCESS, G.SFX_FAILURE, G.SFX_BOO, G.SFX_NOTIFY
S.CODES = { success = S.SFX_SUCCESS, failure = S.SFX_FAILURE, boo = S.SFX_BOO, notify = S.SFX_NOTIFY }
S.WRAM0_LO, S.WRAM0_HI = 0xC000, 0xD000   -- hardware: WRAM0 is never banked

--- The sound writer's write window: the shared permit, narrowed to the request byte alone.
--- io: read_u8/write_u8/framecount. Permit: the shared lua/write_permit.lua module.
--- mailbox: wSlinkMailbox from profile.overlay.ram.
--- The `allow` handed to arm() is gb_panel's own (tilemap/attrmap/state/page/request); the
--- domain bounds below are the authority and refuse everything that is not the request byte, so
--- a panel paint fails here rather than in a policy nobody re-reads.
function S.writes(io, Permit, mailbox)
    assert(type(io) == "table" and io.write_u8 and io.read_u8, "sound writer needs explicit io")
    assert(Permit and Permit.new, "shared write permit factory required")
    assert(type(mailbox) == "number", "mailbox address required")
    local request = mailbox + S.OFF_SFX
    local permit = Permit.new({
        write_u8 = function(addr, value, domain) return io.write_u8(addr, value, domain) end,
        domains = { ["System Bus"] = {
            bounds = function(addr, n, reason)
                -- ONE byte, at ONE address: the request. The tilemap, the attrmap and every other
                -- mailbox byte are refused whatever the reason.
                return reason == "sfx" and n == 1 and addr == request
            end,
            mapped = function() return true end,          -- WRAM0: no bank to check
            pointer_stable = function() return true end,  -- a fixed address from the profile
        } },
        -- gb_panel posts inside one frame's service() and disarms immediately after.
        lifetime = { capture = function() return {} end, valid = function() return true end },
        provenance = function(domain, addr, n, reason)
            return { addr = addr, n = n, why = reason, domain = domain, frame = io.framecount() }
        end,
    })
    local arm, write = permit.arm, permit.write_bytes
    return {
        log = permit.log,
        address = request,
        arm = function(_, reason, allow)
            -- The permit's own bounds are the window; gb_panel's allow is accepted only so its
            -- arm/disarm protocol works, and it can widen nothing.
            return arm(permit, "sfx", nil)
        end,
        disarm = function() permit:disarm() end,
        write_bytes = function(_, addr, bytes) return write(permit, "System Bus", addr, bytes) end,
    }
end

--- The semantic-code -> native-id table the overlay will resolve, or nil, why. It is read, never
--- assumed: a profile generated before the sound service has no `sfx` block, and this refuses.
function S.sfx_codes(profile)
    local ov = type(profile) == "table" and profile.overlay
    local block = type(ov) == "table" and ov.sfx
    if type(block) ~= "table" or type(block.codes) ~= "table" then
        return nil, "profile.overlay.sfx.codes required (overlay with no sound service)"
    end
    local out = {}
    for name, code in pairs(S.CODES) do
        local id = block.codes[name]
        if type(id) ~= "number" or id % 1 ~= 0 or id < 0 or id > 255 then
            return nil, "profile.overlay.sfx.codes." .. name .. " is not a native SFX id"
        end
        if code < 1 or code > 255 then return nil, "semantic code out of range" end
        out[name] = id
    end
    return out
end

--- The sound client for a Polished overlay: the Gen 2 panel binder (freshness, the SFX queue, the
--- one-cue-per-frame arbiter, the shared mailbox offsets) with the Polished sound facts required
--- up front. profile: the generated polished title profile; charmap: the pack's charmap.lua;
--- io: read_u8/framecount/write_u8; writes: S.writes(...) or another armed writer; sanitize.
--- Returns nil, why when the profile carries no sound table (the overlay advertises no SFX bit).
function S.new(profile, charmap, io, writes, sanitize)
    local codes, why = S.sfx_codes(profile)
    if not codes then return nil, why end
    local self, err = Panel.new(profile, charmap, io, writes, sanitize)
    if not self then return nil, err end
    self.sfx_native_ids = codes
    return self
end

return S