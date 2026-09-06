-- lua/mailbox.lua — client side of the SLink companion-patch EWRAM mailbox (ABI v2).
--
-- When the Radical Red companion patch is applied, an injected frame hook maintains a
-- mailbox at 0x0203F800 and writes the 'SLNK' signature every frame. This module lets
-- the Lua client detect that patch and dispatch native opcodes to it. RR requires
-- the supported companion; absence is not permission for storage RAM fallback.
--
-- Memory access mirrors memory_gba.lua: EWRAM is addressed with the bare full address
-- and the default domain (System Bus is reserved for ROM reads).

-- Resolve generated layout even when a private probe uses dofile(). No RAM reads.
do
    local dir = debug.getinfo(1, "S").source:match("^@(.*[/\\])")
    if dir then package.path = dir .. "?.lua;" .. package.path end
end
local L = require("rr.native_layout")
local R, F = L.regions, L.structures
local MB = {LAYOUT=L}
-- Lua owns immutable pending payloads; staging never touches a live native buffer.
local staged = {text = {}, menu = {}, blob = {}}
local function copy_bytes(t) local r = {}; for i = 1, #t do r[i] = t[i] end; return r end

MB.BASE = R.mailbox.address
MB.SIG  = L.constants.signature
MB.ABI  = L.constants.abi

-- ABI v2 field offsets (see patch/src/ADDRESSES.md)
local O = F.Mailbox.offsets
local O_SIG, O_ABI, O_OPCODE, O_SEQ, O_STATUS, O_ACKSEQ, O_REASON, O_ARGS, O_RESULT =
      O.signature, O.abi_version, O.opcode, O.seq, O.status, O.ack_seq, O.reason, O.args, O.result
MB.OPCODE_ADDR = MB.BASE + O_OPCODE

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
MB.BLOB_BUF = R.blob.address     -- patch reads count*100 raw party-mon bytes from here (matches handlers.c)

-- Stage decoded blobs (a list of 100-byte arrays) into the patch's blob buffer.
-- Errors loudly on a short row: writing row[j]=nil would throw mid-stage with a half-written
-- buffer already in EWRAM (callers validate length, this is the last line of defense).
function MB.write_enemy_blobs(byte_rows)
    local bytes = {}
    for i = 1, #byte_rows do
        local row = byte_rows[i]
        if #row ~= 100 then error("write_enemy_blobs: each row must be exactly 100 bytes") end
        for j = 1, 100 do bytes[#bytes + 1] = row[j] end
    end
    staged.blob = bytes
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
    if not blob_row or #blob_row ~= 100 then return nil end
    staged.blob = copy_bytes(blob_row)
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

MB.TEXT_BUF = R.text.address    -- patch reads FR-encoded text from here for SHOW_MESSAGE

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
    local limit = R.text.size - 1 - (color and 3 or 0)
    if #text > limit then text = text:sub(1, limit) end
    local bytes = MB.fr_encode(text)
    local out = {}
    if color then out = {0xFC, 0x01, color} end
    for i = 1, #bytes do out[#out + 1] = bytes[i] end
    staged.text = out
end

function MB.fanfare_args(song) return {song % 256, math.floor(song / 256) % 256} end

-- Native sound effect (PlaySE). Same packing as a fanfare; the patch plays it on the SE track.
function MB.play_se(song) return MB.send(MB.OP_PLAY_SE, MB.fanfare_args(song), false) end

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
MB.MENU_BUF = R.choices.address
function MB.show_choices(options, prompt)
    if not MB.present() then return nil end
    local n = #options
    if n == 0 or n > 8 then return nil end
    -- MENU_BUF is 112 bytes (BattleNotif at +0x70, the faint-event ring right after): refuse
    -- an over-long option list rather than corrupt those — a mangled event ring can decode as
    -- a phantom EV_PLAYER_FAINT and force-faint the partner's linked mon.
    local total = 1
    for i = 1, n do total = total + #options[i] + 1 end   -- fr_encode is 1 byte/char + 0xFF
    if total > R.choices.size then return nil end
    local out = {n}
    for i = 1, n do
        local bytes = MB.fr_encode(options[i])
        for j = 1, #bytes do out[#out + 1] = bytes[j] end
    end
    staged.menu = out
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
MB.BATTLE_NOTIF = R.battle_notif.address   -- BattleNotif struct: active@0, win@1, flags@2, frames(u16)@4
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
local function guarded_storage(op, a, b, c, guard, extra, prepare_only)
    if type(guard) ~= "table" then return nil, "storage guard required" end
    local limits = op == MB.OP_WITHDRAW_MON and {24, 29, 5}
                or op == MB.OP_MOVE_BOX_MON and {24, 29, 24} or {5, 24, 29}
    local values = {a, b, c}
    for i = 1, 3 do
        local value = values[i]
        if type(value) ~= "number" or value % 1 ~= 0 or value < 0 or value > limits[i] then
            return nil, "invalid storage location"
        end
    end
    if extra ~= nil and (type(extra) ~= "number" or extra % 1 ~= 0 or extra < 0 or extra > 29) then
        return nil, "invalid destination box slot"
    end
    for _, name in ipairs({"pid", "otid", "count"}) do
        local v = guard[name]
        local max = name == "count" and 6 or 0xFFFFFFFF
        if type(v) ~= "number" or v % 1 ~= 0 or v < 0 or v > max then
            return nil, "invalid storage guard " .. name
        end
    end
    local args = {a, b, c, L.constants.storage_guard}
    for _, value in ipairs({guard.pid, guard.otid}) do
        for i = 0, 3 do args[#args + 1] = (value >> (i * 8)) & 255 end
    end
    args[#args + 1] = guard.count
    if extra ~= nil then args[#args + 1] = extra end
    if prepare_only then return MB.prepare(op, args, guard.native_id) end
    return MB.send(op, args, nil, guard.native_id)
end
function MB.deposit_mon(party_slot, box_id, box_pos, guard)
    return guarded_storage(MB.OP_DEPOSIT_MON, party_slot, box_id, box_pos, guard)
end
function MB.withdraw_mon(box_id, box_pos, party_slot, guard)
    return guarded_storage(MB.OP_WITHDRAW_MON, box_id, box_pos, party_slot, guard)
end
function MB.memorialize_mon(party_slot, box_id, box_pos, guard)
    return guarded_storage(MB.OP_MEMORIALIZE, party_slot, box_id, box_pos, guard)
end

MB.OP_MOVE_BOX_MON = 28
function MB.move_box_mon(src_box, src_pos, dst_box, dst_pos, guard)
    if dst_pos == nil then return nil, "destination box slot required" end
    return guarded_storage(MB.OP_MOVE_BOX_MON, src_box, src_pos, dst_box, guard, dst_pos)
end

function MB.prepare_deposit_mon(party_slot, box_id, box_pos, guard)
    return guarded_storage(MB.OP_DEPOSIT_MON, party_slot, box_id, box_pos, guard, nil, true)
end
function MB.prepare_withdraw_mon(box_id, box_pos, party_slot, guard)
    return guarded_storage(MB.OP_WITHDRAW_MON, box_id, box_pos, party_slot, guard, nil, true)
end
function MB.prepare_memorialize_mon(party_slot, box_id, box_pos, guard)
    return guarded_storage(MB.OP_MEMORIALIZE, party_slot, box_id, box_pos, guard, nil, true)
end
function MB.prepare_move_box_mon(src_box, src_pos, dst_box, dst_pos, guard)
    if dst_pos == nil then return nil, "destination box slot required" end
    return guarded_storage(MB.OP_MOVE_BOX_MON, src_box, src_pos, dst_box, guard, dst_pos, true)
end

-- Event-push ring (native -> Lua; EvRing in handlers.c @ 0x0203FD10). The patch's frame hook pushes
-- battle edges (faint-settled via the gBattleResults counters, end-of-battle outcome); Lua drains
-- them here instead of re-deriving the same facts by polling. events_init() resyncs the read index
-- on (re)load so stale events from before a Lua restart are skipped.
MB.EVR        = R.events.address
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
MB.EVR_PRIM = MB.EVR + F.EvRing.offsets.prim
-- Legacy reset drops queued events; durable bootstrap must reconcile before using it.
function MB.events_init()
    if not MB.present() then return false end
    memory.write_u8(MB.EVR + F.EvRing.offsets.rd, memory.read_u8(MB.EVR))   -- rd = wr (drop anything stale)
    memory.write_u8(MB.EVR + F.EvRing.offsets.overflow, 0)                        -- clear overflow
    return true
end
-- Drain all pending events. Returns a list of {type=, a=, b=} (possibly empty) plus an overflow
-- bool (true = the ring dropped at least one event since the last drain; flag is cleared).
function MB.events_drain()
    if not MB.present() then return {}, false end
    local out = {}
    local wr, rd = memory.read_u8(MB.EVR), memory.read_u8(MB.EVR + F.EvRing.offsets.rd)
    while rd ~= wr and #out < F.EvRing.bytes.ev // 4 do
        local v = memory.read_u32_le(MB.EVR + F.EvRing.offsets.ev + (rd % (F.EvRing.bytes.ev // 4)) * 4)
        out[#out + 1] = { type = v & 0xFF, a = (v >> 8) & 0xFF, b = (v >> 16) & 0xFFFF }
        rd = (rd + 1) % 256
    end
    memory.write_u8(MB.EVR + F.EvRing.offsets.rd, rd)
    local ovf = memory.read_u8(MB.EVR + F.EvRing.offsets.overflow) ~= 0
    if ovf then memory.write_u8(MB.EVR + F.EvRing.offsets.overflow, 0) end
    return out, ovf
end

-- opcodes 10 OP_APPLY_DAMAGE, 11 OP_CURE_STATUS, 12 OP_SET_RULES REMOVED (RR-redundant / dropped
-- features). Numbers stay reserved; the patch acks ST_FAIL for them. Do not reuse without a rebuild.
MB.OP_ARM_PEER_INTERACT = 13  -- talk-to-ghost: args {ghost_oeId, armed} (legacy; ghost auto-arms now)
MB.OP_GHOST_SPAWN = 14        -- engine-driven peer ghost: args {gfxId, localId}; hook spawns+drives
MB.OP_GHOST_CLEAR = 15        -- hook cleanly removes the ghost
-- SlinkState struct @ 0x0203F8D0: _rsvd0 (was enforce_rules), pi_armed, pi_oe, pi_count
MB.PI_COUNT = R.peer_interact.address + F.SlinkState.offsets.pi_count
function MB.peer_interact_count() return memory.read_u8(MB.PI_COUNT) end

-- TradeNpcState struct @ 0x0203F8D4 (patch's drive_trade_npc): enable, oeId, mapG, mapN.
-- The patch spawns/arms/despawns a Pokémon-Center trade NPC whenever `enable`=1 (set by the client
-- when overworld presence is OFF). Mutually exclusive with the peer ghost (which owns pi_oe when ON).
MB.TN_ENABLE = R.trade_npc.address
function MB.set_pc_npc(enable)
    if not MB.present() then return false end
    memory.write_u8(MB.TN_ENABLE, enable and 1 or 0)
    return true
end

-- Battle-Calc display kill switch (one byte after TradeNpcState; matches handlers.c SLINK_CALC_OFF).
-- INVERTED: 0 (EWRAM boot default — no Lua/config) = calc SHOWN; 1 = the battletext shim skips the
-- calc trampoline so the damage display never draws. Writes require the ABI2 beacon.
MB.CALC_OFF = R.calc_off.address
function MB.set_battle_calc(enable)
    if not MB.present() then return false end
    memory.write_u8(MB.CALC_OFF, enable and 0 or 1)
    return true
end

-- SlinkInfo @ 0x0203FD44 — the §6 SOULLINK start-menu entry (patch struct of the same name).
-- Plain EWRAM writes rather than opcodes, same as set_pc_npc / set_battle_calc above: the menu
-- row is a config bit, not a command, and staging text through the single-slot mailbox would
-- contend with ghost/trade/msgbox traffic for nothing.
-- Boot default 0 = no SOULLINK row and the displaced row behaves as stock, so an unpatched-Lua
-- session is indistinguishable from today. Writes require the ABI2 beacon.
MB.INFO        = R.info.address
MB.INFO_ENABLE = MB.INFO + F.SlinkInfo.offsets.enable   -- u8: 1 = splice the SOULLINK row into the START menu
MB.INFO_OPENED = MB.INFO + F.SlinkInfo.offsets.opened   -- u8: patch ++ when the row is chosen (poll for the edge)
MB.INFO_DRAWN  = MB.INFO + F.SlinkInfo.offsets.drawn   -- u8: patch's ack of OPENED
MB.INFO_LINES  = MB.INFO + F.SlinkInfo.offsets.lines   -- u8: populated line count, 0..8 (0 = the screen refuses to open)
MB.INFO_LINE   = MB.INFO + F.SlinkInfo.offsets.line   -- u8[8][32]: FR-encoded, 0xFF-terminated
MB.OP_SHOW_INFO  = 27
MB.INFO_MAXLINES = 6    -- body rows that fit at the panel's 13px pitch; the title is a ROM const
MB.INFO_LINEW    = F.SlinkInfo.dimensions.line[2] -- bytes per slot, including terminator
MB.INFO_PAGESLOT = 7    -- the header's page indicator; `lines` never counts it
function MB.set_info_enable(enable)
    if not MB.present() then return false end
    memory.write_u8(MB.INFO_ENABLE, enable and 1 or 0)
    return true
end
function MB.info_opened() return memory.read_u8(MB.INFO_OPENED) end

-- Row builders. The patch decides a row's KIND from how many "\n"-separated fields it has, so
-- these three helpers are the whole layout vocabulary: 5 fields = a party-menu-style mon row,
-- 2 = a label/value row, 1 (a plain string) = full-width text.
--
-- Lua does the HP->pixels division because the patch has no libgcc and cannot divide at runtime.
-- barpx 0 is what renders the name and HP in red, so it IS the fainted signal — pass 0 for a dead
-- mon even if you have no HP numbers for it.
MB.INFO_BAR_W = 38
function MB.info_bar(cur, max)
    if not cur or not max or max <= 0 or cur <= 0 then return 0 end
    local px = math.floor(cur * MB.INFO_BAR_W / max + 0.5)
    if px < 1 then px = 1 end                  -- a live mon must never render as an empty bar
    return math.min(MB.INFO_BAR_W, px)
end
-- label <=4 chars (an area tag), name <=10 (the engine's own gSpeciesNames stride-11 limit).
-- `state` is optional: "B" = boxed (alive, but out of the party so it has no live HP — drawn in
-- normal colours with an empty bar). Anything else keeps the default rule, where an empty bar means
-- dead and the row goes red. Boxed must NOT read as dead: telling a player their mon died when it
-- is sitting in a box is the one mistake this screen cannot make.
function MB.info_mon(label, name, level, hptext, barpx, state, status)
    return table.concat({ tostring(label):sub(1, 4), tostring(name):sub(1, 10),
                          tostring(level), tostring(hptext),
                          tostring(math.max(0, math.min(MB.INFO_BAR_W, math.floor(barpx or 0)))),
                          state or "", (status or ""):sub(1, 3) }, "\n")
end
function MB.info_stat(label, value) return tostring(label) .. "\n" .. tostring(value) end

-- Append a linked PAIR as its two rows: yours on top, your partner's below. The second row carries
-- an EMPTY label, which is exactly what the patch keys the tie bracket off — so pairing is never
-- left to the reader inferring it from two adjacent rows sharing an area tag. Always append both
-- rows together; a lone continuation row would draw an orphan with no bracket and no area.
-- `mine`/`theirs` are { name=, level=, hp=, bar= } (bar via MB.info_bar, or 0 for fainted).
function MB.info_pair(rows, label, mine, theirs)
    rows[#rows + 1] = MB.info_mon(label, mine.name, mine.level, mine.hp, mine.bar,
                                  mine.state, mine.status)
    rows[#rows + 1] = MB.info_mon("", theirs.name, theirs.level, theirs.hp, theirs.bar,
                                  theirs.state, theirs.status)
    return rows
end

-- Stage the panel. `lines` is a list of plain ASCII strings (a GBA panel is ~26 usable chars, so
-- format for that before calling). Truncates rather than spilling: the patch rejects any slot
-- without a 0xFF inside its 32 bytes, so an over-long line would blank the whole screen instead of
-- just itself. Extra lines past the 8th are dropped, and `pages` lets the caller say so on screen.
function MB.write_info(lines, page, pages)
    if not MB.present() then return false end
    local n = math.min(#lines, MB.INFO_MAXLINES)
    for i = 1, n do
        local bytes = MB.fr_encode(tostring(lines[i]):sub(1, MB.INFO_LINEW - 1))
        local off = MB.INFO_LINE + (i - 1) * MB.INFO_LINEW
        for j = 1, #bytes do memory.write_u8(off + (j - 1), bytes[j]) end
    end
    memory.write_u8(MB.INFO + F.SlinkInfo.offsets.page, page or 0)
    memory.write_u8(MB.INFO + F.SlinkInfo.offsets.pages, pages or 1)
    -- The page indicator goes in slot 7, which `lines` never counts and the row loop never reads —
    -- the patch draws it right-aligned in the header. Staging it as a slot rather than a new struct
    -- field keeps the EWRAM contract untouched, and an older Lua that never writes it simply leaves
    -- the header without an indicator instead of breaking.
    local pg = MB.fr_encode(string.format("PAGE %d/%d", (page or 0) + 1, pages or 1))
    local pgoff = MB.INFO_LINE + MB.INFO_PAGESLOT * MB.INFO_LINEW
    for j = 1, math.min(#pg, MB.INFO_LINEW) do memory.write_u8(pgoff + (j - 1), pg[j]) end
    -- lines LAST: it is the patch's "this panel is ready" gate, so publishing it before the text
    -- would let a frame-hook open race a half-written page.
    memory.write_u8(MB.INFO_LINES, n)
    memory.write_u8(MB.INFO + F.SlinkInfo.offsets.gen, (memory.read_u8(MB.INFO + F.SlinkInfo.offsets.gen) + 1) % 256)   -- gen++
    return n
end

-- Open the staged panel. ASYNC like SHOW_MENU/SHOW_CHOICES: poll MB.poll(seq), then read
-- MB.info_result() — 0 = A (advance a page), 0x7F = B (close). That difference is the whole
-- pagination protocol; there is no separate "next page" opcode.
MB.INFO_ADVANCE, MB.INFO_CLOSE = 0, 0x7F
function MB.show_info(page) return MB.send(MB.OP_SHOW_INFO, { page or 0 }) end
function MB.info_result() return MB.read_result_u8(0) end

-- GhostState @ 0x0203F850 (shared with the patch's drive_ghost). Lua writes target/gfx each tick;
-- the frame hook walks a real object-event toward it natively. Offsets match handlers.c.
MB.GH        = R.ghost.address
MB.GH_OEID   = MB.GH + F.GhostState.offsets.oeId   -- u8: hook-owned object-event id (0xFF = not spawned)
MB.GH_GFX    = MB.GH + F.GhostState.offsets.gfxId   -- u8: stand-in graphicsId (avatar overridden after spawn)
MB.GH_WX     = MB.GH + F.GhostState.offsets.wx   -- s16: partner WORLD-PIXEL x (sub-pixel target; patch LERPs to it)
MB.GH_WY     = MB.GH + F.GhostState.offsets.wy   -- s16: partner WORLD-PIXEL y
MB.GH_FACE   = MB.GH + F.GhostState.offsets.face  -- u8: partner facing 1=S 2=N 3=W 4=E (idle anim)
MB.GH_MV     = MB.GH + F.GhostState.offsets.mv  -- u8: 1 = partner moving (play walk/run anim), 0 = idle
MB.GH_SNAP   = MB.GH + F.GhostState.offsets.snap  -- u8: Lua sets 1 -> patch jumps the ghost straight to (wx,wy)
MB.GH_AN     = MB.GH + F.GhostState.offsets.an  -- u8: partner's live animNum (exact animation)
MB.GH_RUN    = MB.GH + F.GhostState.offsets.run  -- u8: partner running/biking (1 px/frame walk, 2 px/frame run)
MB.GH_AVATARDIRTY = MB.GH + F.GhostState.offsets.avatarDirty  -- u8: Lua sets when imgs/anims/palette changed; patch applies
MB.GH_IMGS   = MB.GH + F.GhostState.offsets.imgs  -- u32: partner's live gSprites[sid].images ROM ptr
MB.GH_ANIMS  = MB.GH + F.GhostState.offsets.anims  -- u32: partner's live gSprites[sid].anims  ROM ptr
MB.GHOST_PAL_BUF   = R.ghost_palette.address  -- u16[16] BGR555: partner's true OBJ palette (decoded from pcol)
MB.LOCALID   = 0xF0
-- The player is NOT always object-event slot 0; its slot is gPlayerAvatar.objectEventId.
MB.GPLAYER_AVATAR = 0x02037078   -- CFRU; objectEventId @ +0x05
function MB.player_oe()
    local id = memory.read_u8(MB.GPLAYER_AVATAR + 0x05)
    if id >= 16 then id = 0 end
    return 0x02036E38 + id * 0x24
end
-- Request the engine-driven ghost (idempotent; safe to call once).
function MB.ghost_spawn(gfx)
    gfx = gfx or 0
    if type(gfx) ~= "number" or gfx % 1 ~= 0 or gfx < 0 or gfx > 65535 then return nil, "invalid gfx16" end
    return MB.send(MB.OP_GHOST_SPAWN, {gfx & 255, MB.LOCALID, (gfx >> 8) & 255}, false)
end
function MB.ghost_clear() return MB.send(MB.OP_GHOST_CLEAR, {}, false) end
function MB.ghost_oe() return memory.read_u8(MB.GH_OEID) end   -- 0xFF until spawned
-- Per-tick update: post the partner's WORLD-PIXEL position + facing + moving + live animNum. The
-- patch LERPs the ghost sprite toward (wx,wy) so motion is continuous + sub-pixel. Plain EWRAM
-- writes; no opcode/ack churn. face 1-4, mv 0/1, an = partner's animNum.
function MB.ghost_set_pos(wx, wy, face, mv, an, run)
    if not MB.present() then return false end
    memory.write_s16_le(MB.GH_WX, wx)
    memory.write_s16_le(MB.GH_WY, wy)
    memory.write_u8(MB.GH_FACE, (face and face >= 1 and face <= 4) and face or 1)
    memory.write_u8(MB.GH_MV, mv and 1 or 0)
    memory.write_u8(MB.GH_AN, an and (an & 0xFF) or 0)
    memory.write_u8(MB.GH_RUN, run and 1 or 0)
    return true
end

-- Jump the ghost straight to the currently-posted (wx,wy) — first frame on a map / warp / big
-- desync. Post the position with ghost_set_pos first, then call this.
function MB.ghost_snap()
    if not MB.present() then return false end
    memory.write_u8(MB.GH_SNAP, 1)
    return true
end

-- Set the partner's avatar: their live sprite images/anims ROM ptrs (valid on this copy of the same
-- RR build) + their true 16-colour OBJ palette (pcol_hex = 64 hex chars = 16 BGR555 LE u16). The
-- patch points the ghost sprite at these ptrs and stamps the colours into the ghost's own slot.
function MB.ghost_set_avatar(imgs, anims, pcol_hex)
    if not MB.present() then return false end
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
    return true
end

-- SwapState @ 0x0203F840 (published read-only by the patch: slink_backup_wrap sets begin,
-- drive_swap_state clears end). Authoritative borrowed-party ("Party Freeze") signal: active=1
-- while the engine has gPlayerParty swapped for a borrowed/preset party (Battle-Tower preset
-- battles, Poke Dude, partner/mock); seq increments on each BEGIN edge — the frame CFRU backs the
-- real party up, which is frame-exact and threshold-free (replaces the client's >=3-PID-change
-- overworld heuristic). real_pid = gPlayerParty[0]'s PID at begin (cross-check). Returns nil when the
-- patch/beacon is absent so the caller falls back to the PID heuristic. Offsets match handlers.c.
MB.SW = R.swap.address
function MB.read_swap_state()
    if not MB.present() then return nil end
    return {
        active   = memory.read_u8(MB.SW + F.SwapState.offsets.active),
        seq      = memory.read_u8(MB.SW + F.SwapState.offsets.seq),
        real_pid = memory.read_u32_le(MB.SW + F.SwapState.offsets.real_pid),
    }
end

MB.ST_IDLE, MB.ST_BUSY, MB.ST_OK, MB.ST_FAIL = 0, 1, 2, 3

-- Helper: build the FORCE_MOVE arg array (move_id is u16 at aligned args offset 4).
function MB.force_move_args(battler, target, move_pos, move_id)
    return {battler, target, move_pos, 0, move_id % 256, math.floor(move_id / 256)}
end

-- One native owner. The bridge copies a receipt before acknowledging its retirement;
-- callers poll the saved copy, so pumping the next command cannot erase its result.
local next_token, inflight = 0, nil
local outbox, receipts = {}, {}
local receipt_count, fault, last_completion, last_polled = 0, nil, nil, nil
local prepared_entries, durable_ids, prepared_count, durable_count, context_generation = {}, {}, 0, 0, nil
local function deep_copy(value)
    if type(value) ~= "table" then return value end
    local copy = {}; for k, v in pairs(value) do copy[k] = deep_copy(v) end; return copy
end
local function same(a, b)
    if type(a) ~= type(b) then return false end
    if type(a) ~= "table" then return a == b end
    for k, v in pairs(a) do if not same(v, b[k]) then return false end end
    for k in pairs(b) do if a[k] == nil then return false end end
    return true
end
local function current_context()
    local player_id = memory.read_u8(MB.GPLAYER_AVATAR + 5)
    local map = require("rr.peer_position").current_map(memory)
    if not map then return nil end
    return {generation=context_generation, callback2=memory.read_u32_le(0x030030F4),
            script_lock=memory.read_u8(0x03000F9C), swap_active=memory.read_u8(MB.SW + F.SwapState.offsets.active),
            map_group=map.mg, map_num=map.mn, saveblock1=map.saveblock1, layout=map.layout,
            player_id=player_id}
end
function MB.set_context_generation(value)
    if type(value) ~= "string" or value == "" then return false, "context generation must be a string" end
    context_generation = value; return true
end
local MAX_QUEUED, MAX_RECEIPTS = 128, 128
local UI_STATE, SCRIPT_LOCK = R.ui.address, 0x03000F9C
function MB.present()
    local readable, signature = pcall(memory.read_u32_le, MB.BASE + O_SIG)
    if not readable or signature ~= MB.SIG then return false end
    local abi_readable, abi = pcall(memory.read_u16_le, MB.BASE + O_ABI)
    return abi_readable and abi == MB.ABI
end
local function capture()
    if not MB.present() then
        if inflight or #outbox > 0 or prepared_count > 0 then fault = "native_session_changed" end
        return
    end
    local st = memory.read_u16_le(MB.BASE + O_STATUS)
    if inflight then
        -- Match the prepared host generation, not callback2: a legitimate native
        -- trade/UI operation changes scenes while retaining this reservation.
        if inflight.context and inflight.context.generation ~= context_generation then
            fault = "native_context_generation_changed"; return
        end
        if not MB.present() or memory.read_u16_le(MB.BASE + O_SEQ) ~= inflight.wire then
            fault = "native_session_changed"; return
        end
        for i = 0, L.constants.reservation_bytes - 1 do
            local expected = tonumber(inflight.native_id:sub(i * 2 + 1, i * 2 + 2), 16)
            if memory.read_u8(MB.BASE + O_ARGS + L.constants.reservation_offset + i) ~= expected then
                fault = "native_reservation_changed"; return
            end
        end
        if st == MB.ST_IDLE then fault = "native_owner_lost"; return end
        if st ~= MB.ST_OK and st ~= MB.ST_FAIL then return end
        if memory.read_u16_le(MB.BASE + O_ACKSEQ) ~= inflight.wire then
            fault = "native_receipt_mismatch"; return
        end
        for i = 0, L.constants.reservation_bytes - 1 do
            local expected = tonumber(inflight.native_id:sub(i * 2 + 1, i * 2 + 2), 16)
            if memory.read_u8(MB.BASE + O_RESULT + L.constants.receipt_reservation_offset + i) ~= expected then
                fault = "native_reservation_receipt_mismatch"; return
            end
        end
        if inflight.keep and receipt_count >= MAX_RECEIPTS then fault = "receipt_cache_full"; return end
        local r = {token=inflight.token, native_id=inflight.native_id,
                   context_generation=inflight.context and inflight.context.generation or nil, status=st,
                   reason=memory.read_u16_le(MB.BASE + O_REASON), result={}}
        for i = 0, F.Mailbox.bytes.result - 1 do r.result[i + 1] = memory.read_u8(MB.BASE + O_RESULT + i) end
        if inflight.keep then receipts[inflight.token] = r; receipt_count = receipt_count + 1 end
        last_completion = r
        if durable_ids[inflight.native_id] then durable_ids[inflight.native_id].phase = "completed" end
        inflight = nil
        memory.write_u16_le(MB.BASE + O_STATUS, MB.ST_IDLE) -- explicit receipt retirement LAST
    elseif MB.present() and (st ~= MB.ST_IDLE or memory.read_u16_le(MB.BASE + O_OPCODE) ~= 0) then
        fault = "unowned_native_operation" -- Lua reload/reset requires reconciliation, not overwrite
    end
end
local function slot_free()
    return not fault and not inflight and memory.read_u16_le(MB.BASE + O_OPCODE) == 0
       and memory.read_u16_le(MB.BASE + O_STATUS) == MB.ST_IDLE
end
local function payload_free(payload)
    local ui = memory.read_u8(UI_STATE) ~= 0
    local script = memory.read_u8(SCRIPT_LOCK) ~= 0
    if payload.text and (ui or script or memory.read_u8(MB.BATTLE_NOTIF) ~= 0) then return false end
    if payload.menu and (ui or script) then return false end
    return true
end
local function snapshot_payload(op)
    local p = {}
    if op == MB.OP_SHOW_MESSAGE or op == MB.OP_SHOW_MENU or op == MB.OP_SHOW_CHOICES
       or op == MB.OP_SHOW_BATTLE_MESSAGE then p.text = copy_bytes(staged.text) end
    if op == MB.OP_SHOW_CHOICES then p.menu = copy_bytes(staged.menu) end
    if op == MB.OP_SET_PARTY_MON or op == MB.OP_SET_ENEMY_PARTY then p.blob = copy_bytes(staged.blob) end
    return p
end
local function post(e)
    if e.context and not same(e.context, current_context()) then
        fault = "native_context_changed"; return false
    end
    for name, bytes in pairs(e.payload) do
        local base = name == "text" and MB.TEXT_BUF or name == "menu" and MB.MENU_BUF or MB.BLOB_BUF
        for i = 1, #bytes do memory.write_u8(base + i - 1, bytes[i]) end
    end
    for i = 0, F.Mailbox.bytes.args - 1 do memory.write_u8(MB.BASE + O_ARGS + i, e.args[i + 1] or 0) end
    if e.context then
        local c = e.context
        memory.write_u8(MB.BASE + O_ARGS + L.context_fields.map_group, c.map_group)
        memory.write_u8(MB.BASE + O_ARGS + L.context_fields.map_num, c.map_num)
        memory.write_u32_le(MB.BASE + O_ARGS + L.context_fields.callback2, c.callback2)
        memory.write_u8(MB.BASE + O_ARGS + L.context_fields.script_lock, c.script_lock)
        memory.write_u8(MB.BASE + O_ARGS + L.context_fields.swap_active, c.swap_active)
        memory.write_u8(MB.BASE + O_ARGS + L.context_fields.player_id, c.player_id)
        memory.write_u8(MB.BASE + O_ARGS + L.context_fields.guard, L.constants.context_guard_tag)
    end
    for i = 0, L.constants.reservation_bytes - 1 do
        memory.write_u8(MB.BASE + O_ARGS + L.constants.reservation_offset + i, tonumber(e.native_id:sub(i * 2 + 1, i * 2 + 2), 16))
    end
    for i = 0, F.Mailbox.bytes.result - 1 do memory.write_u8(MB.BASE + O_RESULT + i, 0) end
    memory.write_u16_le(MB.BASE + O_ACKSEQ, (e.wire + 0xFFFF) % 0x10000)
    memory.write_u16_le(MB.BASE + O_REASON, 0)
    memory.write_u16_le(MB.BASE + O_SEQ, e.wire)
    memory.write_u16_le(MB.BASE + O_STATUS, MB.ST_BUSY)
    inflight = e
    memory.write_u16_le(MB.BASE + O_OPCODE, e.op) -- publish after complete payload and args
    if durable_ids[e.native_id] then durable_ids[e.native_id].phase = "submitted" end
    return true
end
local function prepare(opcode, args, native_id, keep_receipt, durable)
    if not MB.present() then return nil, "companion ABI2 absent" end
    if type(opcode) ~= "number" or opcode % 1 ~= 0 or opcode < 1 or opcode > 65535 then
        return nil, "invalid native opcode"
    end
    if fault then return nil, fault end
    args = args or {}
    if #args > L.constants.argument_bytes then return nil, "too many native arguments" end
    for i = 1, #args do
        if type(args[i]) ~= "number" or args[i] % 1 ~= 0 or args[i] < 0 or args[i] > 255 then
            return nil, "native arguments must be bytes"
        end
    end
    local payload = snapshot_payload(opcode)
    for name, bytes in pairs(payload) do
        local limit = name == "text" and R.text.size or name == "menu" and R.choices.size or R.blob.size
        if #bytes > limit then return nil, "oversized native " .. name .. " payload" end
        for i = 1, #bytes do
            local value = bytes[i]
            if type(value) ~= "number" or value % 1 ~= 0 or value < 0 or value > 255 then
                return nil, "native payload must contain bytes"
            end
        end
    end
    if type(native_id) ~= "string" or #native_id ~= 16 or not native_id:match("^[0-9a-f]+$") then
        return nil, "native reservation must be 16 lowercase hex characters"
    end
    if durable and not context_generation then return nil, "context generation required" end
    if prepared_count >= MAX_QUEUED then return nil, "preparation capacity exhausted" end
    if durable_ids[native_id] then return nil, "native_reservation_conflict" end
    if durable and durable_count >= MAX_RECEIPTS then return nil, "reservation_registry_full" end
    local context = durable and current_context() or nil
    if durable and not context then return nil, "native_context_unavailable" end
    next_token = next_token + 1
    local e = {op=opcode, args=copy_bytes(args), token=next_token, wire=next_token % 65536,
               native_id=native_id, keep=keep_receipt ~= false, payload=payload,
               context=context}
    prepared_entries[e.token] = e; prepared_count = prepared_count + 1
    if durable then durable_ids[native_id] = {phase="prepared", entry=e}; durable_count = durable_count + 1 end
    return deep_copy(e)
end
-- No EWRAM writes: persist this exact serializable preparation before submit.
function MB.prepare(opcode, args, native_id, keep_receipt)
    return prepare(opcode, args, native_id, keep_receipt, true)
end
function MB.submit(reservation)
    if not MB.present() then
        if inflight or #outbox > 0 or prepared_count > 0 then fault = "native_session_changed" end
        return nil, fault or "companion ABI2 absent"
    end
    local token = type(reservation) == "table" and reservation.token
    local e = token and prepared_entries[token]
    if not e or not same(e, reservation) then return nil, "unknown_or_changed_preparation" end
    capture()
    if fault then return nil, fault end
    if e.context and not same(e.context, current_context()) then return nil, "native_context_changed" end
    if #outbox >= MAX_QUEUED then fault = "native_queue_full"; return nil, fault end
    prepared_entries[token] = nil; prepared_count = prepared_count - 1
    if #outbox == 0 and slot_free() and payload_free(e.payload) then
        if not post(e) then return nil, fault end
    else outbox[#outbox + 1] = e end
    return e.token
end
-- Compatibility convenience only: volatile sends do not establish a durable intent.
-- The coordinator uses prepare/persist/submit with a never-conflicting opaque ID.
function MB.send(opcode, args, keep_receipt, native_id)
    capture()
    local reservation, why = prepare(opcode, args, native_id or string.format("%016x", next_token + 1),
                                      keep_receipt, native_id ~= nil)
    if not reservation then return nil, why end
    return MB.submit(reservation)
end
-- Only after the durable receipt and full readback have been persisted. Historical
-- token reuse must still be rejected by the authoritative durable command ledger.
function MB.release_reservation(native_id)
    local e = durable_ids[native_id]
    if not e or e.phase ~= "completed" then return false end
    durable_ids[native_id] = nil; durable_count = durable_count - 1; return true
end

function MB.pump()
    capture()
    if not MB.present() then return false end
    if #outbox == 0 or not slot_free() or not payload_free(outbox[1].payload) then return end
    if post(outbox[1]) then table.remove(outbox, 1) end
end
function MB.poll(token)
    capture()
    if not MB.present() then return nil, fault or "companion ABI2 absent" end
    local r = receipts[token] or (last_completion and last_completion.token == token and last_completion)
    if not r then return nil, fault end
    if r.context_generation and r.context_generation ~= context_generation then
        fault = "native_context_generation_changed"; return nil, fault
    end
    last_polled = r
    if receipts[token] then receipts[token] = nil; receipt_count = receipt_count - 1 end
    return r.status, r.reason
end
-- Detached historical evidence only; this does not capture or retire native state.
function MB.get_saved_receipt(token)
    local r = receipts[token] or (last_completion and last_completion.token == token and last_completion)
    return r and deep_copy(r) or nil
end
function MB.read_result_u8(i)
    return last_polled and last_polled.result[i + 1] or 0
end
function MB.session_error() return fault end
-- Explicit recovery seam: caller must reconcile game state first. Never interrupt an
-- engine operation or UI reader merely to make the mailbox available.
function MB.reset_after_reconcile()
    if not MB.present() or memory.read_u16_le(MB.BASE + O_OPCODE) ~= 0
       or memory.read_u16_le(MB.BASE + O_STATUS) == MB.ST_BUSY
       or memory.read_u8(UI_STATE) ~= 0 or memory.read_u8(SCRIPT_LOCK) ~= 0
       or memory.read_u8(MB.BATTLE_NOTIF) ~= 0 then return false, "native owner still active" end
    outbox, receipts, prepared_entries, durable_ids = {}, {}, {}, {}; receipt_count = 0; prepared_count = 0; durable_count = 0; context_generation = nil
    inflight, fault, last_completion, last_polled = nil, nil, nil, nil
    memory.write_u16_le(MB.BASE + O_STATUS, MB.ST_IDLE)
    return true
end
function MB.read_descriptor(token)
    local status, reason = MB.poll(token)
    if status ~= MB.ST_OK then return nil, reason or "pending" end
    local ptr = 0
    for i = 0, 3 do ptr = ptr | (MB.read_result_u8(i) << (8 * i)) end
    local D, DO = F.NativeDescriptor, F.NativeDescriptor.offsets
    if ptr < L.rom.base or ptr + D.size > L.rom.limit then return nil, "invalid descriptor pointer" end
    local function u16(off) return memory.read_u16_le(ptr + off, "System Bus") end
    local function u32(off) return memory.read_u32_le(ptr + off, "System Bus") end
    local function hexstr(off)
        local t = {}
        for i = 0, 63 do t[#t + 1] = string.char(memory.read_u8(ptr + off + i, "System Bus")) end
        local value = table.concat(t)
        if not value:match("^[0-9a-f]+$") or memory.read_u8(ptr + off + 64, "System Bus") ~= 0 then return nil end
        return value
    end
    if u32(DO.magic) ~= L.constants.descriptor_magic or u16(DO.descriptor_version) ~= L.constants.descriptor_version
       or u16(DO.abi) ~= MB.ABI or u32(DO.size) ~= D.size or u32(DO.mailbox_address) ~= MB.BASE
       or u16(DO.mailbox_size) ~= R.mailbox.size or u16(DO.storage_guard) ~= L.constants.storage_guard then
        return nil, "descriptor contract mismatch"
    end
    local build, layout = hexstr(DO.build_id), hexstr(DO.layout_sha256)
    if not build or not layout then return nil, "invalid descriptor fingerprint" end
    local caps, capabilities = u32(DO.capability_mask), {}
    for name, bit in pairs(L.capabilities) do capabilities[name] = (caps & bit) ~= 0 end
    return {magic="SLD2", descriptor_version=L.constants.descriptor_version, abi=u16(DO.abi), build_id=build, layout_sha256=layout,
            capability_mask=caps, mailbox_address=u32(DO.mailbox_address), mailbox_size=u16(DO.mailbox_size),
            storage_guard=u16(DO.storage_guard), capabilities=capabilities}
end
return MB
