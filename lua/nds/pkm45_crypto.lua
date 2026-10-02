-- lua/nds/pkm45_crypto.lua -- shared Gen 4 / Gen 5 stored-Pokemon cipher core.
--
-- Pure and size-agnostic: byte strings or dense 1-based byte arrays in, fresh 1-based byte arrays out; no
-- BizHawk API, no RAM access, no globals, no per-game field map beyond the identity words. The PK4
-- stored record and the PK5 stored record are the same 0x88-byte cipher (FILE: the games' own
-- Decrypt/Encrypt/GetParamBlock code is identical in HGSS/Pt and BW/B2W2; SOURCE: PKHeX PokeCrypto,
-- BULB-IV). The party tail length is a PARAMETER (Gen 4: 0xEC, Gen 5: 0xDC), never a constant here.
--
-- INPUT CONTRACT. A record is a string, or a dense 1-based array of integers 0..255 (no holes, no
-- non-integers: that is a caller error and is not diagnosed). Lengths are checked ("size"), contents
-- are not. Results are fresh arrays; inputs are never mutated or aliased.
--
-- Record = u32 PID | u16 flags | u16 checksum | 0x80 bytes (four 0x20 blocks A,B,C,D, shuffled and
-- XOR-encrypted with an LCRNG seeded by the checksum) [| party tail, XOR-encrypted, seeded by the PID].
-- Plain form (what decrypt_* return): header unchanged, blocks in LOGICAL order A,B,C,D, tail decrypted.
-- Offsets are 0-based struct offsets; arrays are 1-based (as lua/gen3/reads.lua, lua/gen4/pk4.lua).
--
-- FLAGS WORD (+0x04, u16).
--   bit 2 = bad egg: a legitimate STORED state. It is never an error and never repaired; decrypt reports
--     it as info.bad_egg and encrypt preserves it.
--   bits 0-1 = the game's own "decrypted" marker. FILE (docs/gen5/research/rom_code_anchors.md:66 and :214):
--     Decrypt() sets bits 0-1 and XORs body and tail but does NOT reorder the blocks (they stay shuffled);
--     Encrypt() tests bit 0, clears bits 0-1, recomputes the checksum and re-XORs. Whether LIVE RAM party
--     records are at rest plaintext or ciphertext is OPEN (needs RAM): a reader must key on the flag.
--     Default: a record with bits 0-1 set is refused ("locked"). With opts.allow_decrypted = true the body
--     and tail are taken as already XOR-plain (still shuffled), only un-shuffled, and info.decrypted = true;
--     the stored checksum is then REPORTED (info.checksum_ok), not enforced, because the game only
--     recomputes it in Encrypt. encrypt_* always clear bits 0-1.
--
-- Errors are (nil, reason) with the Gen 4 oracle's tokens: "size" | "locked" | "checksum" | "party_len".
local M = {}

local HEADER, BLOCK, BODY_END = 8, 0x20, 0x88 -- BODY_END = stored record size (header + 4 blocks)
local BODY_LEN = BODY_END - HEADER

-- Row = (pid >> 13) & 31 (the games index a 32-row table; rows 24-31 repeat rows 0-7, == % 24).
-- Column = logical block A..D, value = stored byte offset of that block inside the 0x80 body.
-- FILE: equals the cartridge's own table (BW/B2W2 arm9, 128 bytes) and PKHeX BlockPosition x 0x20.
local SHUFFLE = {
    { 0x00, 0x20, 0x40, 0x60 }, { 0x00, 0x20, 0x60, 0x40 }, { 0x00, 0x40, 0x20, 0x60 },
    { 0x00, 0x60, 0x20, 0x40 }, { 0x00, 0x40, 0x60, 0x20 }, { 0x00, 0x60, 0x40, 0x20 },
    { 0x20, 0x00, 0x40, 0x60 }, { 0x20, 0x00, 0x60, 0x40 }, { 0x40, 0x00, 0x20, 0x60 },
    { 0x60, 0x00, 0x20, 0x40 }, { 0x40, 0x00, 0x60, 0x20 }, { 0x60, 0x00, 0x40, 0x20 },
    { 0x20, 0x40, 0x00, 0x60 }, { 0x20, 0x60, 0x00, 0x40 }, { 0x40, 0x20, 0x00, 0x60 },
    { 0x60, 0x20, 0x00, 0x40 }, { 0x40, 0x60, 0x00, 0x20 }, { 0x60, 0x40, 0x00, 0x20 },
    { 0x20, 0x40, 0x60, 0x00 }, { 0x20, 0x60, 0x40, 0x00 }, { 0x40, 0x20, 0x60, 0x00 },
    { 0x60, 0x20, 0x40, 0x00 }, { 0x40, 0x60, 0x20, 0x00 }, { 0x60, 0x40, 0x20, 0x00 },
}

-- A fresh dense array copy of a string or array.
local function arr(b)
    local out = {}
    if type(b) == "string" then
        for i = 1, #b do out[i] = b:byte(i) end
    else
        for i = 1, #b do out[i] = b[i] end
    end
    return out
end

-- Little-endian unsigned read at 0-based `off`; works on strings and arrays without copying.
local function u(b, off, size)
    local value = 0
    if type(b) == "string" then
        for i = size - 1, 0, -1 do value = (value << 8) | b:byte(off + i + 1) end
    else
        for i = size - 1, 0, -1 do value = (value << 8) | b[off + i + 1] end
    end
    return value
end

-- XOR each u16 from 0-based `off` to the end with the next LCRNG output; symmetric.
local function lcg_xor(b, off, seed)
    for i = off + 1, #b - 1, 2 do
        seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        local x = (b[i] | (b[i + 1] << 8)) ~ (seed >> 16)
        b[i], b[i + 1] = x & 0xFF, x >> 8
    end
end

-- The shuffle row index (0-31) for a PID.
function M.shuffle_row(pid) return (pid >> 13) & 31 end

-- Stored byte offsets (inside the 0x80 body) of logical blocks A, B, C, D for `pid`. Fresh table.
function M.block_order(pid)
    local row = SHUFFLE[M.shuffle_row(pid) % 24 + 1]
    return { row[1], row[2], row[3], row[4] }
end

-- Plain 16-bit sum of the little-endian u16 words of `body` (string or array; the stored body is 0x80
-- bytes). Order-independent, so shuffled or logical order give the same value. An ODD length is refused
-- (nil, "size"), exactly as the Python oracle raises PkmError("size").
function M.checksum(body)
    local n = #body
    if n % 2 ~= 0 then return nil, "size" end
    local total = 0
    for i = 0, n - 2, 2 do total = total + u(body, i, 2) end
    return total & 0xFFFF
end

-- Move the four blocks of the 0x80 body between stored and logical order (header copied as is).
-- `order` is block_order(pid), computed once by the caller.
local function reorder(b, order, to_stored)
    local out = {}
    for i = 1, BODY_END do out[i] = 0 end -- fill 1..n in order: a pure array, no hash part
    for i = 1, HEADER do out[i] = b[i] end
    for which = 0, 3 do
        local logical, stored = HEADER + which * BLOCK, HEADER + order[which + 1]
        local from, to = logical, stored
        if not to_stored then from, to = stored, logical end
        for i = 1, BLOCK do out[to + i] = b[from + i] end
    end
    return out
end

local function slice(b, off, len)
    local out = {}
    for i = 1, len do out[i] = b[off + i] end
    return out
end

local function allow_decrypted(opts) return type(opts) == "table" and opts.allow_decrypted == true end

-- Encrypted 0x88 record -> (plain 0x88 array, info) or (nil, reason). Refuses a checksum mismatch and a
-- record carrying the "decrypted" marker (see FLAGS WORD; opts.allow_decrypted = true opts in).
-- The header (pid, flags, checksum) is kept as stored.
-- info = { pid, flags, checksum, checksum_ok, row, order, bad_egg, decrypted }.
function M.decrypt_stored(raw, opts)
    local b = arr(raw)
    if #b ~= BODY_END then return nil, "size" end
    local pid, flags, stored_sum = u(b, 0, 4), u(b, 4, 2), u(b, 6, 2)
    local decrypted = flags & 0x3 ~= 0
    if decrypted and not allow_decrypted(opts) then return nil, "locked" end
    local body = slice(b, HEADER, BODY_LEN)
    if not decrypted then lcg_xor(body, 0, stored_sum) end
    local checksum_ok = M.checksum(body) == stored_sum
    if not checksum_ok and not decrypted then return nil, "checksum" end
    for i = 1, BODY_LEN do b[HEADER + i] = body[i] end
    local order = M.block_order(pid)
    return reorder(b, order, false), {
        pid = pid, flags = flags, checksum = stored_sum, checksum_ok = checksum_ok,
        row = M.shuffle_row(pid), order = order, bad_egg = flags & 0x4 ~= 0, decrypted = decrypted,
    }
end

-- Inverse of decrypt_stored: recomputes the checksum from the plain blocks and CLEARS flags bits 0-1
-- (the record is ciphertext again); every other flag bit, bad egg included, is preserved.
function M.encrypt_stored(plain)
    local p = arr(plain)
    if #p ~= BODY_END then return nil, "size" end
    local b = reorder(p, M.block_order(u(p, 0, 4)), true)
    local body = slice(b, HEADER, BODY_LEN)
    local csum = M.checksum(body)
    lcg_xor(body, 0, csum)
    for i = 1, BODY_LEN do b[HEADER + i] = body[i] end
    b[5] = b[5] & 0xFC
    b[7], b[8] = csum & 0xFF, csum >> 8
    return b
end

local function party_ok(party_len)
    return math.type(party_len) == "integer" and party_len > BODY_END and (party_len - BODY_END) % 2 == 0
end

-- Encrypted party record of exactly `party_len` bytes (Gen 4 0xEC, Gen 5 0xDC) -> (plain, info).
-- The tail (+0x88..) has no checksum and is keyed by the PID; with opts.allow_decrypted and the marker set
-- the tail is taken as already plain too (the game decrypts body and tail together).
function M.decrypt_party(raw, party_len, opts)
    if not party_ok(party_len) then return nil, "party_len" end
    local b = arr(raw)
    if #b ~= party_len then return nil, "size" end
    local head, info = M.decrypt_stored(slice(b, 0, BODY_END), opts)
    if not head then return nil, info end
    local tail = slice(b, BODY_END, party_len - BODY_END)
    if not info.decrypted then lcg_xor(tail, 0, info.pid) end
    for i = 1, #tail do head[BODY_END + i] = tail[i] end
    return head, info
end

function M.encrypt_party(plain, party_len)
    if not party_ok(party_len) then return nil, "party_len" end
    local p = arr(plain)
    if #p ~= party_len then return nil, "size" end
    local head = M.encrypt_stored(slice(p, 0, BODY_END))
    local tail = slice(p, BODY_END, party_len - BODY_END)
    lcg_xor(tail, 0, u(p, 0, 4))
    for i = 1, #tail do head[BODY_END + i] = tail[i] end
    return head
end

-- Identity accessors: read the PLAIN (decrypted, unshuffled) record, header + logical block A only, with
-- no copy of the record. TID/SID are the two u16 at +0x0C/+0x0E; OTID is the combined u32
-- (TID | SID << 16). Everything else (species, ability, 0x41/0x42/0x85 ...) differs per game and stays
-- out of this module. A record shorter than 0x10 bytes is (nil, "size").
local function ident(plain, off, size)
    if #plain < 0x10 then return nil, "size" end
    return u(plain, off, size)
end
function M.pid(plain) return ident(plain, 0, 4) end
function M.tid(plain) return ident(plain, 0x0C, 2) end
function M.sid(plain) return ident(plain, 0x0E, 2) end
function M.otid(plain) return ident(plain, 0x0C, 4) end
function M.mon_key(plain)
    local pid, otid = M.pid(plain), M.otid(plain)
    if not pid then return nil, "size" end
    return string.format("%08X:%08X", pid, otid)
end

return M
