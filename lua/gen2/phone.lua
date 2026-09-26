-- lua/gen2/phone.lua — the Soul Link phone calls (O-29, an easter egg), the host half.
--
-- docs/gen2/reviews/P4_5_PHONE_CALLS_PLAN_2026-09-23.md §2-§3. The server tags three existing
-- commands with "phone" (fallen / dead_zone / first_link); this binder turns a tag into one byte
-- at mailbox +32 PHONE_REQUEST. The ROM (P4.5b) acks by zeroing +32, holds the accepted id at
-- +33 PHONE_ARMED, and its call script zeroes +33 once the Pokégear has rung (= delivered).
-- A clean ROM has no beacon, and a build without SLINK_CAP_PHONE never gets a byte.
local Phone = {}

Phone.OFF_REQUEST, Phone.OFF_ARMED = 32, 33   -- patch/gb/slink_abi.inc SLINK_OFS_PHONE_REQUEST/ARMED
Phone.CAP = 0x08                              -- plan §6: SLINK_CAP_PHONE = 1 << 3 (patch/gb/slink_abi.inc)
-- The call ids double as the priority: a lower id outranks a higher one.
Phone.IDS = { fallen = 1, dead_zone = 2, first_link = 3 }
Phone.FIRST_LINK = 3
-- ~3 minutes at 60 fps, counted in BizHawk frames, never the mailbox counter (OMP F3).
Phone.MIN_GAP = 10800
-- PHONE-NAMES (docs/gen2/POST_RC_CARDS.md): the 24-byte record in wUnusedMapBuffer, cookie LAST.
-- +0 event, +1 caller species, +2 receiver species, +3 trainer (7+$50), +11 caller nickname
-- (10+$50), +22 the request's nonce, +23 cookie. patch/gen2/src/phone.asm SlinkPhoneCheckRecord owns
-- the ROM half. Every post writes the record, then the same nonce at mailbox +35, then +32; the ROM
-- moves +35 at the ack, so a record from any other request (or a bare post) never matches, and it
-- zeroes the cookie when the call is prepared (single use). HandleNewMap wipes the buffer, so the
-- binder re-stages while the call is ARMED: once, after at most RESTAGE_TRIES attempts.
Phone.STAGE_SIZE, Phone.COOKIE, Phone.TERMINATOR = 24, 0xA6, 0x50
Phone.OFF_TRAINER, Phone.OFF_NICK, Phone.OFF_NONCE, Phone.OFF_COOKIE = 3, 11, 22, 23
Phone.OFF_MAILBOX_NONCE = 35   -- patch/gen2/src/phone.asm SLINK_OFS_PHONE_NONCE
Phone.RESTAGE_TRIES = 3

local function int(v) return type(v) == "number" and math.tointeger(v) or nil end
local function species(mon)
    local id = type(mon) == "table" and int(mon.species_id)
    return id and id >= 1 and id <= 251 and id or 0
end

--- The staged bytes for call `id`, or 24 zeros (which also clears a stale cookie) when `data`
--- names no encodable trainer. encode: trade_overlay.lua T.encode_name(charmap, text, n).
function Phone.record(id, data, encode, charmap)
    local rec = {}
    for i = 1, Phone.STAGE_SIZE do rec[i] = 0 end
    if type(data) ~= "table" or not encode then return rec end
    local trainer = encode(charmap, data.trainer_name, 8)
    if not trainer then return rec end
    local caller = type(data.caller_mon) == "table" and data.caller_mon or nil
    -- the caller's mon by nickname; an empty nickname makes the ROM print the species name
    local nick = caller and encode(charmap, caller.nickname, 11) or {}
    rec[1], rec[2], rec[3] = id, species(caller), species(data.receiver_mon)
    for i = 1, 8 do rec[Phone.OFF_TRAINER + i] = trainer[i] end
    for i = 1, 11 do rec[Phone.OFF_NICK + i] = nick[i] or Phone.TERMINATOR end
    rec[Phone.OFF_COOKIE + 1] = Phone.COOKIE
    return rec
end

--- panel: lua/gen2/panel.lua (fresh/caps_has/mailbox, already serviced this frame).
--- io: read_u8/framecount. writes: panel.lua P.writes(...), which accepts reason "phone".
--- names (optional): {stage = profile overlay.phone.stage, encode = T.encode_name, charmap}; without
--- it every call rings the fixed text, exactly as before PHONE-NAMES.
function Phone.new(panel, io, writes, log, names)
    local REQ, ARMED = panel.mailbox + Phone.OFF_REQUEST, panel.mailbox + Phone.OFF_ARMED
    local NONCE = panel.mailbox + Phone.OFF_MAILBOX_NONCE
    local STAGE = type(names) == "table" and int(names.stage) or nil
    log = log or function() end
    local queued, inflight, seen, delivered_at, rang_first_link = nil, nil, false, nil, false
    local queued_rec, inflight_rec, restaged, restage_tries, nonce = nil, nil, false, 0, 0
    local self = {}

    local function live() return panel:fresh() and panel:caps_has(Phone.CAP) end
    local function u8(addr)
        local v = io.read_u8(addr)
        return type(v) == "number" and math.floor(v) % 256 or nil
    end
    local function allow(addr, n)
        return n == 1 and (addr == REQ or STAGE ~= nil and (addr == NONCE
                                                           or addr >= STAGE and addr < STAGE + Phone.STAGE_SIZE))
    end
    -- one byte per write: the panel permit's "phone" window is n == 1; the cookie lands last
    local function stage(rec)
        for i = 1, Phone.STAGE_SIZE do writes:write_bytes(STAGE + i - 1, { rec[i] }) end
    end

    --- A command's "phone" tag (+ its optional phone_data). Dropped unless this is a live phone build.
    function self:request(name, data)
        local id = Phone.IDS[name]
        if not id or not live() then return false end
        if id == Phone.FIRST_LINK and rang_first_link then return false end
        if queued == nil or id <= queued then   -- the newest of equal priority wins, with its record
            queued = id
            queued_rec = STAGE and Phone.record(id, data, names.encode, names.charmap) or nil
        end
        return true
    end

    --- Once a frame, after panel:service() refreshed freshness.
    function self:service()
        if not live() then
            -- a reset (or no phone build): the call is lost, never replayed, and no gap starts
            queued, inflight, seen, queued_rec, inflight_rec = nil, nil, false, nil, nil
            return
        end
        local req, armed, now = u8(REQ), u8(ARMED), io.framecount()
        if req == nil or armed == nil then return end
        if inflight then
            if armed == inflight then
                seen = true
                -- a map change (ClearUnusedMapBuffer) wiped a named record: put it back, ONCE
                if inflight_rec and inflight_rec[Phone.OFF_COOKIE + 1] == Phone.COOKIE and not restaged
                        and (u8(STAGE + Phone.OFF_COOKIE) ~= Phone.COOKIE or u8(STAGE) ~= inflight) then
                    writes:arm("phone", allow)
                    local ok, err = pcall(stage, inflight_rec)
                    restage_tries = restage_tries + 1
                    if ok then
                        restaged = true
                        log("[SLink-gen2] phone: call " .. inflight .. " re-staged")
                    elseif restage_tries >= Phone.RESTAGE_TRIES then
                        -- fail closed: no cookie, so the ROM rings the fixed text
                        restaged = true
                        pcall(function() writes:write_bytes(STAGE + Phone.OFF_COOKIE, { 0 }) end)
                        log("[SLink-gen2] phone: call " .. inflight .. " re-stage failed, fixed text: " .. tostring(err))
                    else
                        log("[SLink-gen2] phone: call " .. inflight .. " re-stage retry: " .. tostring(err))
                    end
                    writes:disarm()
                end
            elseif req == 0 and armed == 0 then
                if seen then
                    delivered_at = now
                    log("[SLink-gen2] phone: call " .. inflight .. " delivered")
                end
                inflight, seen, inflight_rec = nil, false, nil   -- unseen = the ROM dropped it: no gap
            end
            return
        end
        if not queued or req ~= 0 or armed ~= 0 then return end
        -- `now < delivered_at`: a savestate load went back past the last call
        if delivered_at and now >= delivered_at and now - delivered_at < Phone.MIN_GAP then return end
        if queued_rec then
            nonce = nonce % 255 + 1                    -- 1..255, never 0 (the ROM's "bare post")
            if queued_rec[Phone.OFF_COOKIE + 1] == Phone.COOKIE then queued_rec[Phone.OFF_NONCE + 1] = nonce end
        end
        writes:arm("phone", allow)
        local ok, err = pcall(function()
            if queued_rec then                         -- a failed stage write never posts the request
                stage(queued_rec)
                writes:write_bytes(NONCE, { nonce })
            end
            writes:write_bytes(REQ, { queued })
        end)
        writes:disarm()
        if not ok then error(err, 0) end
        log("[SLink-gen2] phone: call " .. queued .. " posted")
        if queued == Phone.FIRST_LINK then rang_first_link = true end
        inflight, queued, inflight_rec, queued_rec, restaged, restage_tries = queued, nil, queued_rec, nil, false, 0
    end
    return self
end

return Phone
