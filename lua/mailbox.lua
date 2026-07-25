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

-- This table mirrors the FULL opcode ABI implemented by patch/src/handlers.c — keep the two
-- in sync (patch/src/ADDRESSES.md is the reference).  Several opcodes have no production
-- caller; their consumers are the headless gates in lua/tests (run via tests/live/), which
-- are what prove the ROM side still works.  Don't prune a constant just because the client
-- doesn't send it — check lua/tests first.
--
-- OP_FORCE_FAINT (2) and OP_FORCE_MOVE_SLOT (5) are gate-only ON PURPOSE: the native
-- controller swap softlocked in real play, so the Lua Variant-3 path is production.
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
-- Errors loudly on a short row: writing row[j]=nil would throw mid-stage with a half-written
-- buffer already in EWRAM (callers validate length, this is the last line of defense).
function MB.write_enemy_blobs(byte_rows)
    for i = 1, #byte_rows do
        local row, off = byte_rows[i], MB.BLOB_BUF + (i - 1) * 100
        if #row < 100 then error(string.format("write_enemy_blobs: row %d is %d bytes (want 100)", i, #row)) end
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

-- Trade (talk-to-partner actions). Faithful single-mon write into gPlayerParty[slot] — the same raw
-- 100-byte-blob basis as set_enemy_party but for the PLAYER party, so the partner's traded half is
-- reproduced exactly (species/moves/IVs/EVs/PID/item). `blob_row` = a decoded 100-byte array
-- (M.hexToBytes). `bump` ensures the party count covers the slot (a trade replaces an existing slot,
-- so normally false). Returns the seq to poll, or nil if the blob is malformed.
MB.OP_SET_PARTY_MON = 18
function MB.set_party_mon(slot, blob_row, bump)
    if not blob_row or #blob_row < 100 then return nil end
    for j = 1, 100 do memory.write_u8(MB.BLOB_BUF + (j - 1), blob_row[j]) end
    return MB.send(MB.OP_SET_PARTY_MON, {slot, bump and 1 or 0})
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
MB.OP_PLAY_FANFARE  = 9     -- args: {song_lo, song_hi} (jingle: link-formed / trade-complete)
MB.OP_SHOW_MENU     = 17    -- native YES/NO menu over the text buffer; ASYNC (poll, then menu_result)
MB.OP_PLAY_SE       = 19    -- native sound effect via PlaySE: args {song_lo, song_hi}

MB.TEXT_BUF = 0x0203F900    -- patch reads FR-encoded text from here for SHOW_MESSAGE

-- ASCII -> FireRed charmap, 0xFF-terminated. Uses memory_gba's exported CHARSET_REV as the
-- single source of truth (a hand-rolled second copy here once drifted on 0xB8/0xB9).
-- "\n" maps to the FR line-break control (0xFE) so message-box text can span two lines;
-- unknown characters encode as space (0x00) — the encode path must never error.
-- Self-locate: test scripts dofile() this module without the client's package.path, so
-- seed the path from this file's own directory before requiring (require caches, so the
-- client's later require("memory_gba") shares the same instance).
do
    local dir = debug.getinfo(1, "S").source:match("^@(.*[/\\])")
    if dir then package.path = dir .. "?.lua;" .. package.path end
end
local FR_REV = require("memory_gba").CHARSET_REV   -- memory_gba's module scope is inert (no reads)
function MB.fr_encode(s)
    local out = {}
    for i = 1, #s do
        local c = s:sub(i, i)
        out[#out + 1] = (c == "\n") and 0xFE or FR_REV[c] or 0x00
    end
    out[#out + 1] = 0xFF
    return out
end

-- write FR-encoded text into the patch's text buffer (call before sending SHOW_MESSAGE). `color` (optional)
-- prepends the FR foreground-color control code `0xFC 0x01 <id>` (battle text palette: 1=red, 4=gold,
-- 5=green, 7=blue, 10=white) — used to theme the in-battle notification to the event (HUD conventions).
function MB.write_message(text, color)
    -- TEXT_BUF is 256 bytes (BLOB_BUF starts at +0x100): truncate rather than spill encoded
    -- text into the staged trade/rival mon blobs. Room = 256 - terminator - color prefix.
    local limit = 255 - (color and 3 or 0)
    if #text > limit then text = text:sub(1, limit) end
    local bytes = MB.fr_encode(text)
    local off = MB.TEXT_BUF
    if color then
        memory.write_u8(off, 0xFC); memory.write_u8(off + 1, 0x01); memory.write_u8(off + 2, color)
        off = off + 3
    end
    for i = 1, #bytes do memory.write_u8(off + (i - 1), bytes[i]) end
end

function MB.fanfare_args(song) return {song % 256, math.floor(song / 256) % 256} end

-- Native sound effect (PlaySE). Same packing as a fanfare; the patch plays it on the SE track.
function MB.play_se(song) return MB.send(MB.OP_PLAY_SE, MB.fanfare_args(song)) end

-- Native YES/NO menu over `prompt` (the menuing foundation for talk-to-partner actions). ASYNC: the
-- field script runs over many frames, so poll the returned seq with MB.poll; on ST_OK read the choice
-- with MB.menu_result() (1 = YES, 0 = NO / B-press). Returns the seq, or nil if the patch is absent.
function MB.show_menu(prompt)
    if not MB.present() then return nil end
    MB.write_message(prompt or "")
    return MB.send(MB.OP_SHOW_MENU, {})
end
function MB.menu_result() return MB.read_result_u8(0) end

-- Native multichoice list (a PROPER menu with custom option labels, e.g. {"Trade","Say hey"}). Stages
-- [count][FR str 0xFF-term]... into MENU_BUF, then opens the menu. `prompt` (optional) is spoken in a
-- message box that STAYS OPEN under the floating list (the talk-NPC's line) and closes after the pick.
-- ASYNC like show_menu: poll the seq; on ST_OK read the chosen index with MB.menu_result()
-- (0..n-1, or 127 = B-press/cancel). nil if absent.
MB.OP_SHOW_CHOICES = 22
MB.MENU_BUF = 0x0203FC90
function MB.show_choices(options, prompt)
    if not MB.present() then return nil end
    local n = #options
    if n == 0 or n > 8 then return nil end
    -- MENU_BUF is 112 bytes (BattleNotif at +0x70, the faint-event ring right after): refuse
    -- an over-long option list rather than corrupt those — a mangled event ring can decode as
    -- a phantom EV_PLAYER_FAINT and force-faint the partner's linked mon.
    local total = 1
    for i = 1, n do total = total + #options[i] + 1 end   -- fr_encode is 1 byte/char + 0xFF
    if total > 112 then return nil end
    memory.write_u8(MB.MENU_BUF, n)
    local off = MB.MENU_BUF + 1
    for i = 1, n do
        local bytes = MB.fr_encode(options[i])   -- FR-encoded, already 0xFF-terminated
        for j = 1, #bytes do memory.write_u8(off, bytes[j]); off = off + 1 end
    end
    local with_text = (prompt ~= nil and prompt ~= "") and 1 or 0
    if with_text == 1 then MB.write_message(prompt) end
    return MB.send(MB.OP_SHOW_CHOICES, {with_text})
end

-- Native "Choose a POKeMON" party menu (pick WHICH linked mon to trade). ASYNC like show_menu: poll
-- the seq; on ST_OK read the chosen slot with MB.choose_result() (0-5, or 7 = cancel/B). nil if absent.
MB.OP_CHOOSE_PARTY_MON = 20
function MB.choose_party_mon()
    if not MB.present() then return nil end
    return MB.send(MB.OP_CHOOSE_PARTY_MON, {})
end
function MB.choose_result() return MB.read_result_u8(0) end

-- Native in-game TRADE scene (animation + trade-evolution): trades gPlayerParty[slot] with the mon
-- staged in gEnemyParty[0]. Caller must stage that mon first (MB.set_enemy_party({blob})). ASYNC:
-- poll the seq; ST_OK once the scene returns to the overworld. nil if the patch is absent.
MB.OP_TRADE_SCENE = 21
function MB.trade_scene(slot)
    if not MB.present() then return nil end
    return MB.send(MB.OP_TRADE_SCENE, {slot})
end

-- Native IN-BATTLE notification text (the BizHawk-HUD-in-battle replacement). The field message box can't
-- open during battle, so this draws FR-encoded text via the engine's BattlePutTextOnWindow (the same
-- primitive the bundled Battle Calc hooks), re-asserted by the patch every frame for `frames`. Only valid
-- in battle (the patch acks ST_FAIL otherwise). `win` = battle window id (the spike sweeps this; production
-- bakes the chosen default); `flags` ORs into the window arg (0x80 = don't clear the background). Sync ack.
-- Returns the seq, or nil if the patch is absent.
MB.OP_SHOW_BATTLE_MESSAGE = 23
MB.BATTLE_NOTIF = 0x0203FD00   -- BattleNotif struct: active@0, win@1, flags@2, frames(u16)@4
function MB.show_battle_message(text, frames, win, color)
    if not MB.present() then return nil end
    MB.write_message(text, color)               -- `color` = FR text color id (themes the text to the event)
    frames = frames or 240
    return MB.send(MB.OP_SHOW_BATTLE_MESSAGE,
                   { frames % 256, math.floor(frames / 256) % 256, win or 0, 0 })
end

-- PC box ⇄ party storage (Phase-1 migration of depositPartyMon / retrieveBoxMon off the Lua RAM-poke).
-- Lua does the READ (scan the box for a key / find an empty slot — see memory_gba scanBoxForKey /
-- the deposit slot scan) and passes the located box slot; the patch does the WRITE via CFRU's own
-- compressed-box conversion (CompressedMonToMon / CreateCompressedMonFromBoxMon), so the mon is
-- compressed/decompressed faithfully and a withdrawn mon comes back fully formed (level/stats/PP
-- recomputed by the engine — no server-cached stats needed). boxId 0-24, boxPos 0-29, partySlot 0-5.
MB.OP_DEPOSIT_MON  = 24
MB.OP_WITHDRAW_MON = 25
MB.OP_MEMORIALIZE  = 26
function MB.deposit_mon(party_slot, box_id, box_pos)   -- party[slot] -> box[box_id][box_pos]
    return MB.send(MB.OP_DEPOSIT_MON, {party_slot, box_id, box_pos})
end
function MB.withdraw_mon(box_id, box_pos, party_slot)  -- box[box_id][box_pos] -> party[slot]
    return MB.send(MB.OP_WITHDRAW_MON, {box_id, box_pos, party_slot})
end
-- party[slot] -> memorial box[box_id][box_pos]. Same conversion as deposit_mon but the party removal
-- is zero + swap-with-last (NOT shift) so survivors keep their slot indices (CFRU deferred battle
-- writes target slots — mirrors M.memorializeMon). Lua picks the free slot + renames the box.
function MB.memorialize_mon(party_slot, box_id, box_pos)
    return MB.send(MB.OP_MEMORIALIZE, {party_slot, box_id, box_pos})
end

-- Event-push ring (native -> Lua; EvRing in handlers.c @ 0x0203FD10). The patch's frame hook pushes
-- battle edges (faint-settled via the gBattleResults counters, end-of-battle outcome); Lua drains
-- them here instead of re-deriving the same facts by polling. events_init() resyncs the read index
-- on (re)load so stale events from before a Lua restart are skipped.
MB.EVR        = 0x0203FD10
MB.EV_PLAYER_FAINT = 1   -- a = playerFaintCounter after the bump
MB.EV_FOE_FAINT    = 2   -- a = foeFaintCounter after the bump
MB.EV_OUTCOME      = 3   -- a = gBattleOutcome on the end-of-battle edge (1 won, 2 lost/whiteout, ...)
MB.EV_PARTY_ADD    = 4   -- a = new party count, b = species of the slot that appeared
MB.EV_EVOLVE       = 5   -- a = party slot, b = the NEW species (in-place change; both sides nonzero)
MB.EV_NAMES = { [1] = "player_faint", [2] = "foe_faint", [3] = "outcome",
                [4] = "party_add",    [5] = "evolve" }
-- Producer latches live inside the ring struct (the ROM blob has no .data/.bss). `prim` (+6) is the
-- "party latches primed" flag: 0 makes the next frame LATCH ONLY, which is what makes the boot
-- default (all-zero EWRAM) reproduce the pre-producer behaviour instead of firing a burst of
-- spurious party events. Clearing it is how you force a re-prime (the patch does this itself while
-- a borrowed party is installed).
MB.EVR_PRIM = 0x0203FD16
function MB.events_init()
    memory.write_u8(MB.EVR + 1, memory.read_u8(MB.EVR))   -- rd = wr (drop anything stale)
    memory.write_u8(MB.EVR + 2, 0)                        -- clear overflow
end
-- Drain all pending events. Returns a list of {type=, a=, b=} (possibly empty) plus an overflow
-- bool (true = the ring dropped at least one event since the last drain; flag is cleared).
function MB.events_drain()
    local out = {}
    local wr, rd = memory.read_u8(MB.EVR), memory.read_u8(MB.EVR + 1)
    while rd ~= wr and #out < 8 do
        local v = memory.read_u32_le(MB.EVR + 8 + (rd % 8) * 4)
        out[#out + 1] = { type = v & 0xFF, a = (v >> 8) & 0xFF, b = (v >> 16) & 0xFFFF }
        rd = (rd + 1) % 256
    end
    memory.write_u8(MB.EVR + 1, rd)
    local ovf = memory.read_u8(MB.EVR + 2) ~= 0
    if ovf then memory.write_u8(MB.EVR + 2, 0) end
    return out, ovf
end

-- opcodes 10 OP_APPLY_DAMAGE, 11 OP_CURE_STATUS, 12 OP_SET_RULES REMOVED (RR-redundant / dropped
-- features). Numbers stay reserved; the patch acks ST_FAIL for them. Do not reuse without a rebuild.
MB.OP_ARM_PEER_INTERACT = 13  -- talk-to-ghost: args {ghost_oeId, armed} (legacy; ghost auto-arms now)
MB.OP_GHOST_SPAWN = 14        -- engine-driven peer ghost: args {gfxId, localId}; hook spawns+drives
MB.OP_GHOST_CLEAR = 15        -- hook cleanly removes the ghost
-- SlinkState struct @ 0x0203F8D0: _rsvd0 (was enforce_rules), pi_armed, pi_oe, pi_count
MB.PI_COUNT = 0x0203F8D3
function MB.peer_interact_count() return memory.read_u8(MB.PI_COUNT) end

-- TradeNpcState struct @ 0x0203F8D4 (patch's drive_trade_npc): enable, oeId, mapG, mapN.
-- The patch spawns/arms/despawns a Pokémon-Center trade NPC whenever `enable`=1 (set by the client
-- when overworld presence is OFF). Mutually exclusive with the peer ghost (which owns pi_oe when ON).
MB.TN_ENABLE = 0x0203F8D4
function MB.set_pc_npc(enable) memory.write_u8(MB.TN_ENABLE, enable and 1 or 0) end

-- Battle-Calc display kill switch (one byte after TradeNpcState; matches handlers.c SLINK_CALC_OFF).
-- INVERTED: 0 (EWRAM boot default — no Lua/config) = calc SHOWN; 1 = the battletext shim skips the
-- calc trampoline so the damage display never draws. Plain EWRAM write, safe before the beacon.
MB.CALC_OFF = 0x0203F8D8
function MB.set_battle_calc(enable) memory.write_u8(MB.CALC_OFF, enable and 0 or 1) end

-- SlinkInfo @ 0x0203FD44 — the §6 SOULLINK start-menu entry (patch struct of the same name).
-- Plain EWRAM writes rather than opcodes, same as set_pc_npc / set_battle_calc above: the menu
-- row is a config bit, not a command, and staging text through the single-slot mailbox would
-- contend with ghost/trade/msgbox traffic for nothing.
-- Boot default 0 = no SOULLINK row and the displaced row behaves as stock, so an unpatched-Lua
-- session is indistinguishable from today. Safe to write before the beacon.
MB.INFO        = 0x0203FD44
MB.INFO_ENABLE = MB.INFO + 0   -- u8: 1 = splice the SOULLINK row into the START menu
MB.INFO_OPENED = MB.INFO + 1   -- u8: patch ++ when the row is chosen (poll for the edge)
MB.INFO_DRAWN  = MB.INFO + 2   -- u8: patch's ack of OPENED
MB.INFO_LINES  = MB.INFO + 3   -- u8: populated line count, 0..8 (0 = the screen refuses to open)
MB.INFO_LINE   = MB.INFO + 8   -- u8[8][32]: FR-encoded, 0xFF-terminated
function MB.set_info_enable(enable) memory.write_u8(MB.INFO_ENABLE, enable and 1 or 0) end
function MB.info_opened() return memory.read_u8(MB.INFO_OPENED) end

-- GhostState @ 0x0203F850 (shared with the patch's drive_ghost). Lua writes target/gfx each tick;
-- the frame hook walks a real object-event toward it natively. Offsets match handlers.c.
MB.GH        = 0x0203F850
MB.GH_OEID   = MB.GH + 1   -- u8: hook-owned object-event id (0xFF = not spawned)
MB.GH_GFX    = MB.GH + 2   -- u8: stand-in graphicsId (avatar overridden after spawn)
MB.GH_WX     = MB.GH + 6   -- s16: partner WORLD-PIXEL x (sub-pixel target; patch LERPs to it)
MB.GH_WY     = MB.GH + 8   -- s16: partner WORLD-PIXEL y
MB.GH_FACE   = MB.GH + 10  -- u8: partner facing 1=S 2=N 3=W 4=E (idle anim)
MB.GH_MV     = MB.GH + 11  -- u8: 1 = partner moving (play walk/run anim), 0 = idle
MB.GH_SNAP   = MB.GH + 14  -- u8: Lua sets 1 -> patch jumps the ghost straight to (wx,wy)
MB.GH_AN     = MB.GH + 15  -- u8: partner's live animNum (exact animation)
MB.GH_RUN    = MB.GH + 16  -- u8: partner running/biking (1 px/frame walk, 2 px/frame run)
MB.GH_AVATARDIRTY = MB.GH + 17  -- u8: Lua sets when imgs/anims/palette changed; patch applies
MB.GH_IMGS   = MB.GH + 20  -- u32: partner's live gSprites[sid].images ROM ptr
MB.GH_ANIMS  = MB.GH + 24  -- u32: partner's live gSprites[sid].anims  ROM ptr
MB.GHOST_PAL_BUF   = 0x0203FC60  -- u16[16] BGR555: partner's true OBJ palette (decoded from pcol)
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
-- Per-tick update: post the partner's WORLD-PIXEL position + facing + moving + live animNum. The
-- patch LERPs the ghost sprite toward (wx,wy) so motion is continuous + sub-pixel. Plain EWRAM
-- writes; no opcode/ack churn. face 1-4, mv 0/1, an = partner's animNum.
function MB.ghost_set_pos(wx, wy, face, mv, an, run)
    memory.write_s16_le(MB.GH_WX, wx)
    memory.write_s16_le(MB.GH_WY, wy)
    memory.write_u8(MB.GH_FACE, (face and face >= 1 and face <= 4) and face or 1)
    memory.write_u8(MB.GH_MV, mv and 1 or 0)
    memory.write_u8(MB.GH_AN, an and (an & 0xFF) or 0)
    memory.write_u8(MB.GH_RUN, run and 1 or 0)
end

-- Jump the ghost straight to the currently-posted (wx,wy) — first frame on a map / warp / big
-- desync. Post the position with ghost_set_pos first, then call this.
function MB.ghost_snap() memory.write_u8(MB.GH_SNAP, 1) end

-- Set the partner's avatar: their live sprite images/anims ROM ptrs (valid on this copy of the same
-- RR build) + their true 16-colour OBJ palette (pcol_hex = 64 hex chars = 16 BGR555 LE u16). The
-- patch points the ghost sprite at these ptrs and stamps the colours into the ghost's own slot.
function MB.ghost_set_avatar(imgs, anims, pcol_hex)
    memory.write_u32_le(MB.GH_IMGS, imgs or 0)
    memory.write_u32_le(MB.GH_ANIMS, anims or 0)
    if pcol_hex and #pcol_hex >= 64 then
        -- pcol = 16 colours, each the BGR555 u16 as 4 hex chars ("%04X"); parse straight back.
        for i = 0, 15 do
            local v = tonumber(pcol_hex:sub(i * 4 + 1, i * 4 + 4), 16) or 0
            memory.write_u16_le(MB.GHOST_PAL_BUF + i * 2, v & 0xFFFF)
        end
    end
    memory.write_u8(MB.GH_AVATARDIRTY, 1)
end

-- SwapState @ 0x0203F840 (published read-only by the patch: slink_backup_wrap sets begin,
-- drive_swap_state clears end). Authoritative borrowed-party ("Party Freeze") signal: active=1
-- while the engine has gPlayerParty swapped for a borrowed/preset party (Battle-Tower preset
-- battles, Poke Dude, partner/mock); seq increments on each BEGIN edge — the frame CFRU backs the
-- real party up, which is frame-exact and threshold-free (replaces the client's >=3-PID-change
-- overworld heuristic). real_pid = gPlayerParty[0]'s PID at begin (cross-check). Returns nil when the
-- patch/beacon is absent so the caller falls back to the PID heuristic. Offsets match handlers.c.
MB.SW = 0x0203F840
function MB.read_swap_state()
    if not MB.present() then return nil end
    return {
        active   = memory.read_u8(MB.SW + 0),
        seq      = memory.read_u8(MB.SW + 1),
        real_pid = memory.read_u32_le(MB.SW + 4),
    }
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

-- The mailbox is SINGLE-SLOT: the injected hook consumes one opcode per frame, clearing
-- O_OPCODE. Two sends in the same frame would clobber each other (the server routinely
-- batches e.g. play_sound + msgbox in one TCP response), so a send while the slot is still
-- occupied queues in a Lua-side outbox that MB.pump() (called once per frame by the client)
-- drains as the slot frees. ponytail: payload BUFFERS (TEXT_BUF/MENU_BUF/BLOB_BUF) are still
-- staged at call time, so two QUEUED ops targeting the same buffer would collide — the
-- client's one-native-box-per-dispatch guard is what keeps that from happening today.
local outbox = {}
local function slot_free()
    return memory.read_u16_le(MB.BASE + O_OPCODE) == 0
end
local function post(opcode, args, s)
    if args then
        for i = 1, #args do memory.write_u8(MB.BASE + O_ARGS + (i - 1), args[i]) end
    end
    memory.write_u16_le(MB.BASE + O_STATUS, MB.ST_BUSY)
    memory.write_u16_le(MB.BASE + O_ACKSEQ, (s + 0xFFFF) % 0x10000)  -- != seq yet
    memory.write_u16_le(MB.BASE + O_SEQ, s)
    memory.write_u16_le(MB.BASE + O_OPCODE, opcode)   -- write opcode LAST (triggers dispatch)
end

-- Post a command. `args` is an optional array of byte values written to args[].
-- Returns the seq to poll on. Non-blocking: the injected hook consumes it next frame
-- (or, if the slot is occupied, the op is queued and posted by a later MB.pump()).
function MB.send(opcode, args)
    seq = (seq + 1) % 0x10000
    if #outbox > 0 or not slot_free() then
        outbox[#outbox + 1] = {op = opcode, args = args, seq = seq}
        return seq
    end
    post(opcode, args, seq)
    return seq
end

-- Drain one queued op per frame once the hook has consumed the previous one. Call once per
-- frame from the client's on_frame.
function MB.pump()
    if #outbox == 0 or not slot_free() then return end
    local e = table.remove(outbox, 1)
    post(e.op, e.args, e.seq)
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
