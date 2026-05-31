-- lua/mailbox.lua — client side of the SLink companion-patch EWRAM mailbox (ABI v1).
--
-- When the Radical Red companion patch is applied, an injected frame hook maintains a
-- mailbox at 0x0203F800 and writes the 'SLNK' signature every frame. This module lets
-- the Lua client detect that patch and dispatch native opcodes to it; callers fall back
-- to the existing RAM-poke path when MB.present() is false (plan §3-§4).
--
-- Memory access mirrors memory_gba.lua: EWRAM is addressed with the bare full address
-- and the default domain (System Bus is reserved for ROM reads).

local MB = {}

MB.BASE = 0x0203F800
MB.SIG  = 0x4B4E4C53          -- 'SLNK' little-endian (bytes 53 4C 4E 4B)
MB.ABI  = 1

-- ABI v1 field offsets (see patch/src/ADDRESSES.md)
local O_SIG, O_ABI, O_OPCODE, O_SEQ, O_STATUS, O_ACKSEQ, O_REASON, O_ARGS, O_RESULT =
      0, 4, 6, 8, 10, 12, 14, 16, 48

MB.OP_PING = 1

MB.ST_IDLE, MB.ST_BUSY, MB.ST_OK, MB.ST_FAIL = 0, 1, 2, 3

local seq = 0

-- True when the companion patch is present and the ABI matches what we speak.
function MB.present()
    if memory.read_u32_le(MB.BASE + O_SIG) ~= MB.SIG then return false end
    return memory.read_u16_le(MB.BASE + O_ABI) == MB.ABI
end

-- Post a command. `args` is an optional array of byte values written to args[].
-- Returns the seq to poll on. Non-blocking: the injected hook consumes it next frame.
function MB.send(opcode, args)
    if args then
        for i = 1, #args do memory.write_u8(MB.BASE + O_ARGS + (i - 1), args[i]) end
    end
    seq = (seq + 1) % 0x10000
    memory.write_u16_le(MB.BASE + O_STATUS, MB.ST_BUSY)
    memory.write_u16_le(MB.BASE + O_ACKSEQ, (seq + 0xFFFF) % 0x10000)  -- != seq yet
    memory.write_u16_le(MB.BASE + O_SEQ, seq)
    memory.write_u16_le(MB.BASE + O_OPCODE, opcode)   -- write opcode LAST (triggers dispatch)
    return seq
end

-- Poll a previously sent command. Returns status, reason once the hook has acked the
-- matching seq (status is ST_OK or ST_FAIL); returns nil while still pending.
function MB.poll(expect_seq)
    if memory.read_u16_le(MB.BASE + O_ACKSEQ) ~= expect_seq then return nil end
    local st = memory.read_u16_le(MB.BASE + O_STATUS)
    if st == MB.ST_OK or st == MB.ST_FAIL then
        return st, memory.read_u16_le(MB.BASE + O_REASON)
    end
    return nil
end

function MB.read_result_u8(i)  return memory.read_u8(MB.BASE + O_RESULT + i) end

return MB
