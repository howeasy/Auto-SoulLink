-- RR ground position observation. Read-only and ephemeral: this is neither a
-- durable scene epoch nor admission. See docs/rr_reference/PEER_POSITION.md.
local Position = {}
local OBJECTS, SPRITES = 0x02036E38, 0x0202063C

local function delta16(now, before)
    return ((now - before + 32768) % 65536) - 32768
end

function Position.new(io)
    local self, anchor = {}, nil
    function self.reset() anchor = nil end

    function self.sample(oe, field)
        if not field or type(oe) ~= "number" or oe < OBJECTS or oe >= OBJECTS + 16 * 36
            or (oe - OBJECTS) % 36 ~= 0 then
            self.reset(); return nil
        end
        local flags, sid = io.read_u8(oe), io.read_u8(oe + 4)
        if (flags & 1) == 0 or sid >= 64 then self.reset(); return nil end
        local sprite = SPRITES + sid * 68
        if (io.read_u8(sprite + 62) & 3) ~= 3
            or io.read_u16_le(sprite + 46) ~= (oe - OBJECTS) // 36 then
            self.reset(); return nil
        end
        local p = {
            oe=oe, sid=sid, mg=io.read_u8(oe + 10), mn=io.read_u8(oe + 9),
            layout=io.read_u32_le(0x02036DFC),
            gfx=io.read_u8(oe + 5) | (io.read_u8(oe + 35) << 8),
            imgs=io.read_u32_le(sprite + 12), anims=io.read_u32_le(sprite + 8),
            x=io.read_s16_le(oe + 16), y=io.read_s16_le(oe + 18),
            previous_x=io.read_s16_le(oe + 20), previous_y=io.read_s16_le(oe + 22),
            px=io.read_s16_le(sprite + 32), py=io.read_s16_le(sprite + 34),
            idle=(flags & 0x80) ~= 0,
        }
        if anchor and (anchor.oe ~= p.oe or anchor.sid ~= p.sid or anchor.mg ~= p.mg
            or anchor.mn ~= p.mn or anchor.layout ~= p.layout or anchor.gfx ~= p.gfx
            or anchor.imgs ~= p.imgs or anchor.anims ~= p.anims) then self.reset() end
        -- currentCoords is the destination during a step, so never calibrate an
        -- unobserved midstep from it. Sprite.pos2 is a render effect, not ground motion.
        if p.idle and p.x == p.previous_x and p.y == p.previous_y then anchor = p end
        if not anchor then return nil end
        p.wx = anchor.x * 16 + delta16(p.px, anchor.px)
        p.wy = anchor.y * 16 + delta16(p.py, anchor.py)
        -- A camera connection/hard placement can rebase tiles independently of
        -- pos1. Suppress an inconsistent sample until the next aligned anchor.
        if p.wx < math.min(p.x, p.previous_x) * 16 or p.wx > math.max(p.x, p.previous_x) * 16
            or p.wy < math.min(p.y, p.previous_y) * 16 or p.wy > math.max(p.y, p.previous_y) * 16
            or p.wx < -32768 or p.wx > 32767 or p.wy < -32768 or p.wy > 32767 then
            self.reset(); return nil
        end
        return p
    end
    return self
end

return Position
