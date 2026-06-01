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

MB.OP_PING        = 1
MB.OP_FORCE_FAINT = 2   -- args: {battler}
MB.OP_FORCE_MOVE  = 3   -- args: {battler, target, move_pos, 0, move_lo, move_hi}
MB.OP_CREATE_MON  = 4   -- args: {slot, party, species_lo, species_hi, level}

-- party: 0 = player party, 1 = enemy party; bump: 1 = make it a real party member (GIVE_MON)
function MB.create_mon_args(slot, species, level, party, bump)
    return {slot, party or 0, species % 256, math.floor(species / 256), level, bump or 0}
end

-- Rival Team Swap (Phase 2). Faithful enemy-party replacement: stage the partner's raw 100-byte
-- party-mon blobs in SLINK_BLOB_BUF, then OP_SET_ENEMY_PARTY tells the patch to byte-copy them into
-- gEnemyParty + set the count. Unlike CREATE_MON this preserves the partner's EXACT mons
-- (moves/IVs/EVs/PID/item). Args: {count}. The active-foe gBattleMons refresh stays in Lua
-- (M.refreshActiveEnemyBattlers) — see the client's pending_enemy_party settle.
MB.OP_SET_ENEMY_PARTY = 16
MB.BLOB_BUF = 0x0203FA00     -- patch reads count*100 raw party-mon bytes from here (matches handlers.c)

-- Stage decoded blobs (a list of 100-byte arrays) into the patch's blob buffer.
function MB.write_enemy_blobs(byte_rows)
    for i = 1, #byte_rows do
        local row, off = byte_rows[i], MB.BLOB_BUF + (i - 1) * 100
        for j = 1, 100 do memory.write_u8(off + (j - 1), row[j]) end
    end
end

-- Stage blobs + dispatch OP_SET_ENEMY_PARTY. `byte_rows` = decoded 100-byte arrays (decode hex with
-- M.hexToBytes). Returns the seq to poll, or nil if the list is empty/oversized.
function MB.set_enemy_party(byte_rows)
    local n = #byte_rows
    if n == 0 or n > 6 then return nil end
    MB.write_enemy_blobs(byte_rows)
    return MB.send(MB.OP_SET_ENEMY_PARTY, {n})
end

MB.OP_FORCE_MOVE_SLOT = 5   -- args: {battler, target, move_pos} — controller-swap driver
function MB.force_move_slot_args(battler, target, move_pos)
    return {battler, target, move_pos}
end

MB.OP_SPAWN_PEER_NPC = 6    -- args: {gfxId, localId, x_lo, x_hi, y_lo, y_hi, movement}
function MB.spawn_npc_args(gfx, localId, x, y, movement)
    return {gfx, localId, x % 256, math.floor(x/256) % 256,
            y % 256, math.floor(y/256) % 256, movement or 0}
end

MB.OP_DESPAWN_PEER_NPC = 7  -- args: {objectEventId}
MB.OP_SHOW_MESSAGE  = 8     -- text pre-written to the text buffer (see MB.write_message)
MB.OP_PLAY_FANFARE  = 9     -- args: {song_lo, song_hi}

MB.TEXT_BUF = 0x0203F900    -- patch reads FR-encoded text from here for SHOW_MESSAGE

-- ASCII -> FireRed charmap (letters, digits, space, common punctuation), 0xFF-terminated.
function MB.fr_encode(s)
    local out = {}
    for i = 1, #s do
        local c = s:sub(i, i); local b = c:byte(); local v
        if c == " " then v = 0x00
        elseif b >= 48 and b <= 57 then v = 0xA1 + (b - 48)   -- 0-9
        elseif b >= 65 and b <= 90 then v = 0xBB + (b - 65)   -- A-Z
        elseif b >= 97 and b <= 122 then v = 0xD5 + (b - 97)  -- a-z
        elseif c == "!" then v = 0xAB elseif c == "?" then v = 0xAC
        elseif c == "." then v = 0xAD elseif c == "-" then v = 0xAE
        elseif c == "," then v = 0xB8 elseif c == "/" then v = 0xBA
        elseif c == ":" then v = 0xF0
        else v = 0x00 end
        out[#out + 1] = v
    end
    out[#out + 1] = 0xFF
    return out
end

-- write FR-encoded text into the patch's text buffer (call before sending SHOW_MESSAGE)
function MB.write_message(text)
    local bytes = MB.fr_encode(text)
    for i = 1, #bytes do memory.write_u8(MB.TEXT_BUF + (i - 1), bytes[i]) end
end

function MB.fanfare_args(song) return {song % 256, math.floor(song / 256) % 256} end

MB.OP_APPLY_DAMAGE = 10     -- linked HP / chip: args {battler, amt_lo, amt_hi}; result[0..1]=new hp
MB.OP_CURE_STATUS  = 11     -- link-cured status: args {battler}
function MB.apply_damage_args(battler, amount)
    return {battler, amount % 256, math.floor(amount / 256) % 256}
end

MB.OP_SET_RULES = 12          -- ROM-enforced nuzlocke: args {enforce}
MB.OP_ARM_PEER_INTERACT = 13  -- talk-to-ghost: args {ghost_oeId, armed} (legacy; ghost auto-arms now)
MB.OP_GHOST_SPAWN = 14        -- engine-driven peer ghost: args {gfxId, localId}; hook spawns+drives
MB.OP_GHOST_CLEAR = 15        -- hook cleanly removes the ghost
-- SlinkState struct @ 0x0203F8D0: enforce_rules, pi_armed, pi_oe, pi_count
MB.PI_COUNT = 0x0203F8D3
function MB.peer_interact_count() return memory.read_u8(MB.PI_COUNT) end

-- GhostState @ 0x0203F850 (shared with the patch's drive_ghost). Lua writes target/gfx each tick;
-- the frame hook walks a real object-event toward it natively. Offsets match handlers.c.
MB.GH        = 0x0203F850
MB.GH_OEID   = MB.GH + 1   -- u8: hook-owned object-event id (0xFF = not spawned)
MB.GH_GFX    = MB.GH + 2   -- u8: graphicsId Lua wants (change => re-spawn for bike/surf/fish)
MB.GH_TX     = MB.GH + 6   -- s16: target tile x
MB.GH_TY     = MB.GH + 8   -- s16: target tile y
MB.GH_TFACE  = MB.GH + 10  -- u8: target facing 1=S 2=N 3=W 4=E
MB.GH_RUN    = MB.GH + 11  -- u8: 1 = partner dashing -> ghost runs to keep up
MB.LOCALID   = 0xF0
-- The player is NOT always object-event slot 0; its slot is gPlayerAvatar.objectEventId.
MB.GPLAYER_AVATAR = 0x02037078   -- CFRU; objectEventId @ +0x05
function MB.player_oe()
    local id = memory.read_u8(MB.GPLAYER_AVATAR + 0x05)
    if id >= 16 then id = 0 end
    return 0x02036E38 + id * 0x24
end
-- Request the engine-driven ghost (idempotent; safe to call once).
function MB.ghost_spawn(gfx) return MB.send(MB.OP_GHOST_SPAWN, {gfx or 0, MB.LOCALID}) end
function MB.ghost_clear() return MB.send(MB.OP_GHOST_CLEAR, {}) end
function MB.ghost_oe() return memory.read_u8(MB.GH_OEID) end   -- 0xFF until spawned
-- Per-tick target update (plain EWRAM writes; no opcode/ack churn). face 1-4, run 0/1.
function MB.ghost_set_target(tx, ty, face, run, gfx)
    memory.write_s16_le(MB.GH_TX, tx)
    memory.write_s16_le(MB.GH_TY, ty)
    memory.write_u8(MB.GH_TFACE, (face and face >= 1 and face <= 4) and face or 1)
    memory.write_u8(MB.GH_RUN, run and 1 or 0)
    if gfx then memory.write_u8(MB.GH_GFX, gfx) end
end

MB.ST_IDLE, MB.ST_BUSY, MB.ST_OK, MB.ST_FAIL = 0, 1, 2, 3

-- Helper: build the FORCE_MOVE arg array (move_id is u16 at aligned args offset 4).
function MB.force_move_args(battler, target, move_pos, move_id)
    return {battler, target, move_pos, 0, move_id % 256, math.floor(move_id / 256)}
end

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
