-- lua/gen2/phone.lua — the Soul Link phone calls (O-29, an easter egg), the host half.
--
-- docs/gen2/reviews/P4_5_PHONE_CALLS_PLAN_2026-09-23.md §2-§3. The server tags three existing
-- commands with "phone" (fallen / dead_zone / first_link); this binder turns a tag into one byte
-- at mailbox +32 PHONE_REQUEST. The ROM (P4.5b) acks by zeroing +32, holds the accepted id at
-- +33 PHONE_ARMED, and its call script zeroes +33 once the Pokégear has rung (= delivered).
-- A clean ROM has no beacon, and a build without SLINK_CAP_PHONE never gets a byte.
local Phone = {}

Phone.OFF_REQUEST, Phone.OFF_ARMED = 32, 33   -- plan §2.1 (Gen 2-only offsets, P4.5b's slink source)
Phone.CAP = 0x08                              -- plan §6: SLINK_CAP_PHONE = 1 << 3 (patch/gb/slink_abi.inc)
-- The call ids double as the priority: a lower id outranks a higher one.
Phone.IDS = { fallen = 1, dead_zone = 2, first_link = 3 }
Phone.FIRST_LINK = 3
-- ~3 minutes at 60 fps, counted in BizHawk frames, never the mailbox counter (OMP F3).
Phone.MIN_GAP = 10800

--- panel: lua/gen2/panel.lua (fresh/caps_has/mailbox, already serviced this frame).
--- io: read_u8/framecount. writes: panel.lua P.writes(...), which accepts reason "phone".
function Phone.new(panel, io, writes, log)
    local REQ, ARMED = panel.mailbox + Phone.OFF_REQUEST, panel.mailbox + Phone.OFF_ARMED
    log = log or function() end
    local queued, inflight, seen, delivered_at, rang_first_link = nil, nil, false, nil, false
    local self = {}

    local function live() return panel:fresh() and panel:caps_has(Phone.CAP) end
    local function u8(addr)
        local v = io.read_u8(addr)
        return type(v) == "number" and math.floor(v) % 256 or nil
    end
    local function allow(addr, n) return addr == REQ and n == 1 end

    --- A command's "phone" tag. Dropped unless this cartridge is a live phone build.
    function self:request(name)
        local id = Phone.IDS[name]
        if not id or not live() then return false end
        if id == Phone.FIRST_LINK and rang_first_link then return false end
        if queued == nil or id < queued then queued = id end
        return true
    end

    --- Once a frame, after panel:service() refreshed freshness.
    function self:service()
        if not live() then
            -- a reset (or no phone build): the call is lost, never replayed, and no gap starts
            queued, inflight, seen = nil, nil, false
            return
        end
        local req, armed, now = u8(REQ), u8(ARMED), io.framecount()
        if req == nil or armed == nil then return end
        if inflight then
            if armed == inflight then
                seen = true
            elseif req == 0 and armed == 0 then
                if seen then
                    delivered_at = now
                    log("[SLink-gen2] phone: call " .. inflight .. " delivered")
                end
                inflight, seen = nil, false   -- unseen = the ROM dropped it: no gap
            end
            return
        end
        if not queued or req ~= 0 or armed ~= 0 then return end
        -- `now < delivered_at`: a savestate load went back past the last call
        if delivered_at and now >= delivered_at and now - delivered_at < Phone.MIN_GAP then return end
        writes:arm("phone", allow)
        local ok, err = pcall(function() writes:write_bytes(REQ, { queued }) end)
        writes:disarm()
        if not ok then error(err, 0) end
        log("[SLink-gen2] phone: call " .. queued .. " posted")
        if queued == Phone.FIRST_LINK then rang_first_link = true end
        inflight, queued = queued, nil
    end
    return self
end

return Phone
