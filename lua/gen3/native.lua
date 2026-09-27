-- RR companion ABI v1, injected and single-owner. No emulator globals.
-- ABI offsets/statuses: patch/src/ADDRESSES.md:366ff; handlers.c Mailbox/ack.
-- Absolute addresses/opcodes come only from the full pack's profile.native.
-- N.new(pack, {io, writes, reads, send(event, fields), in_battle,
--             artifact_kind, panel_closed(),
--             array(table)?, timeout_frames?, initial_seq?}).
-- The rival swap needs no gBattleMons refresh: OP_RIVAL_SWAP lands before the engine's selection.
-- panel_closed returns (closed, result) for the start-menu-driven panel. Its
-- caller binds field/script/result facts; no legacy literal address is imported.
--
-- DISPATCH RECEIPT (C5-7): the job table is the handle. enqueue/transfer return it, and
-- service() sets `job.posted = true` on it exactly when that job's opcode is published --
-- the last byte written, after every stage has landed. A refused, guarded-off, failed or
-- merely queued job never carries the flag, and a stage-only job (config) has no opcode to
-- publish, so it carries no receipt either. Callers must read "did my op reach the mailbox"
-- from this flag, never from a sink byte count: a completion callback (e.g. the rival swap's
-- readback) or a panel/NPC callback can write through the same sink in the same
-- service() call while the caller's own job is refused at its guard.
local N = {}
local O = {abi=4, opcode=6, seq=8, status=10, ack=12, reason=14, args=16, result=48}
local BUSY, OK, FAIL = 1, 2, 3
-- ST_FAIL reason words (patch/src/handlers.c owns the numbering; ADDRESSES.md lists both sides).
-- Only the named ones matter to Lua: an unknown word stays unnamed rather than being guessed.
local FAIL_REASONS = {[1] = "script_context", [2] = "bad_args", [3] = "not_on_field",
                      [8] = "window_closed"}
local function integer(v, maximum)
    return type(v) == "number" and v % 1 == 0 and v >= 0 and v <= maximum
end
local function clone(t)
    local out = {}
    for k, v in pairs(t) do out[k] = type(v) == "table" and clone(v) or v end
    return out
end

function N.new(profile, deps)
    local p = assert(profile.native, "profile.native required")
    assert(p.ABI == 1 or p.ABI == 2, "unsupported native ABI")
    local v2 = p.ABI == 2 and assert(p.abi_v2, "generated v2 ABI required") or nil
    local offsets, fail_reasons = clone(O), clone(FAIL_REASONS)
    if v2 then
        local c = assert(v2.constants, "v2 constants required")
        assert(c.SLINK_ABI_VERSION == p.ABI and c.SLINK_SIGNATURE == p.SIG, "v2 identity mismatch")
        local fields = assert(v2.structs.SlinkMailboxV2.fields, "v2 mailbox layout required")
        for alias, spec in pairs({abi={"abi_version",2,1}, opcode={"opcode",2,1},
            seq={"seq",2,1}, status={"status",2,1}, ack={"ack_seq",2,1}, reason={"reason",2,1},
            args={"args",1,32}, result={"result",1,16},
            capabilities={"capabilities",4,1}, session_epoch={"session_epoch",4,1}}) do
            local field = assert(fields[spec[1]], "missing v2 mailbox field")
            assert(integer(field.offset, v2.structs.SlinkMailboxV2.size - field.width * field.count)
                   and field.width == spec[2] and field.count == spec[3], "invalid v2 mailbox field")
            offsets[alias] = field.offset
        end
        -- These words have different legacy RR meanings. Name them only for v2.
        for symbol, name in pairs({SLINK_REASON_UNCERTAIN="uncertain",
            SLINK_REASON_IDENTITY="identity", SLINK_REASON_CLIENT_TOO_OLD="client_too_old"}) do
            fail_reasons[assert(c[symbol], "missing v2 failure reason")] = name
        end
    end
    local O = offsets
    local session_epoch = 0
    local io, writes = assert(deps.io), assert(deps.writes)
    local send = assert(deps.send, "send(event, fields) required")
    local array = deps.array or function(t) return t end
    local reads = assert(deps.reads, "Gen 3 read facade required")
    local queue, pending, poisoned, posting = {}, nil, nil, false
    -- post-conditions awaited after an ACK (the rival swap's engine snapshot)
    local watches, SNAPSHOT_FRAMES = {}, 600
    local seq = deps.initial_seq or 0
    assert(integer(seq, 65535), "invalid initial sequence")
    local last_frame, was_present, npc_count, panel_drawn
    local npc_enabled, sounds_enabled = false, true
    local panel_rows, panel_page, panel_showing = {}, 0, false
    -- Per-op ACK deadlines, each LONGER than the patch's own timeout for that op so the patch's
    -- ST_FAIL normally wins the race (patch/src/handlers.c drive_ui :1030-1072):
    --   sync ops (acked the frame they run)              1800
    --   UI kind 1 SHOW_MENU/SHOW_CHOICES/SHOW_INFO        60 start + 1800 answer -> 2400
    --   UI kind 2 CHOOSE_PARTY_MON                        1800 -> 2400
    --   UI kind 3 TRADE_SCENE                             180 start + 5400 scene -> 6000
    -- deps.timeout_frames (a harness knob) overrides every op with one value.
    local SYNC_TIMEOUT = 1800
    local op_timeout = {}
    for name, frames in pairs({OP_SHOW_MENU = 2400, OP_SHOW_CHOICES = 2400, OP_SHOW_INFO = 2400,
                               OP_CHOOSE_PARTY_MON = 2400, OP_TRADE_SCENE = 6000}) do
        if p[name] then op_timeout[p[name]] = frames end
    end
    local function timeout_for(op) return deps.timeout_frames or op_timeout[op] or SYNC_TIMEOUT end
    local self = {}

    local function present()
        if (not v2 and profile.pack ~= "gen3_rr") or deps.artifact_kind ~= "companion" then return false end
        local ok, value = pcall(function()
            return io.read_u32(p.BASE) == p.SIG and io.read_u16(p.BASE + O.abi) == p.ABI
        end)
        return ok and value == true
    end
    function self:mailbox()
        if not present() then return nil, "native absent" end
        local fields = {abi=p.ABI, opcode=io.read_u16(p.BASE + O.opcode),
            seq=io.read_u16(p.BASE + O.seq), status=io.read_u16(p.BASE + O.status),
            ack_seq=io.read_u16(p.BASE + O.ack), reason=io.read_u16(p.BASE + O.reason)}
        fields.reason_name = fail_reasons[fields.reason]
        if v2 then
            fields.capabilities = io.read_u32(p.BASE + O.capabilities)
            fields.session_epoch = io.read_u32(p.BASE + O.session_epoch)
        end
        return fields
    end
    function self:idle()
        if poisoned or pending or panel_showing then return false end
        if not present() then return true end -- absence is safe for the Lua fallback
        local ok, value = pcall(function()
            return io.read_u16(p.BASE + O.opcode) == 0
                   and (posting or io.read_u16(p.BASE + O.status) ~= BUSY)
                   and (v2 ~= nil or io.read_u8(p.INFO + 1) == io.read_u8(p.INFO + 2))
        end)
        return ok and value == true
    end
    function self:trade_active() return false end -- apply_trade belongs to the trade card
    function self:hello_fields() return {} end -- no invented wire capability fields
    -- V1 has no epoch/visit-bound save witness and must not advertise durable trade.
    -- The v2 binding replaces this only when all witness checks are implemented.
    function self:trade_capable() return false end
    -- Typed unavailable adapter until a qualified v2 binding supplies coherent witnesses.
    function self:trade_visit() return nil, "durable_trade_unavailable" end
    function self:trade_eligible(_mon) return false end
    function self:trade_authorized(_token, _old_key) return false end
    function self:prepare_trade(_cmd, done, _valid)
        if done then done("durable_trade_unavailable") end
        return nil, "durable_trade_unavailable"
    end
    function self:withdraw_trade(_token) return nil, "durable_trade_unavailable" end
    local function finish(job, why, result, reason)
        if job.done then job.done(why, result, reason) end
    end
    function self:cancel(handle)
        for i, job in ipairs(queue) do
            if job == handle then
                table.remove(queue, i)
                job.cancelled = true
                finish(job, "guard:stale")
                return true
            end
        end
        return false -- published operations belong to the cartridge; never erase one
    end

    local function abort(why)
        local active, waiting = pending, queue
        pending, queue = nil, {}
        if active then finish(active, why) end
        for _, job in ipairs(waiting) do finish(job, why) end
    end
    local function enqueue(job)
        if not present() then finish(job, "native absent"); return nil, "native absent" end
        if poisoned then finish(job, poisoned); return nil, poisoned end
        if v2 and not job.handshake and session_epoch == 0 then
            finish(job, "client_too_old"); return nil, "client_too_old"
        end
        if #queue >= 64 then finish(job, "native queue full"); return nil, "native queue full" end
        queue[#queue + 1] = job
        -- the job IS the handle: `job.posted` is this job's dispatch receipt (see the header)
        return job
    end
    function self:set_session_epoch(value)
        if not v2 then return nil, "unsupported native ABI" end
        if not integer(value, 0xFFFFFFFF) or value == 0 then return nil, "invalid session epoch" end
        if pending or #queue > 0 or not self:idle() then return nil, "native busy" end
        local bytes = {}
        for i=0,3 do bytes[i+1] = (value >> (8*i)) & 0xFF end
        return enqueue({handshake=true, stages={{p.BASE + O.session_epoch, bytes}},
            done=function(why) if not why then session_epoch=value end end})
    end
    local function encode(text, limit)
        local out = {}
        -- The shared read facade is the sole character map, including multi-byte glyphs.
        local codes = reads.charmap.codes
        for _, codepoint in utf8.codes(tostring(text or "")) do
            if #out >= limit - 1 then break end
            local glyph = utf8.char(codepoint)
            out[#out + 1] = glyph == "\n" and 0xFE or codes[glyph] or 0
        end
        out[#out + 1] = reads.charmap.terminator
        return out
    end
    local function allow_for(job)
        local ranges = {{p.BASE + O.opcode, p.BASE + O.result}}
        for _, stage in ipairs(job.stages or {}) do
            ranges[#ranges + 1] = {stage[1], stage[1] + #stage[2]}
        end
        return function(addr, n)
            for _, range in ipairs(ranges) do
                if addr >= range[1] and addr + n <= range[2] then return true end
            end
            return false
        end
    end
    local function stage_intact(job)
        for _, stage in ipairs(job.stages or {}) do
            local bytes = io.read_bytes(stage[1], #stage[2])
            for i, b in ipairs(stage[2]) do if bytes[i] ~= b then return false end end
        end
        for i, b in ipairs(job.args or {}) do
            if io.read_u8(p.BASE + O.args + i - 1) ~= b then return false end
        end
        return true
    end
    local function dispatch(job)
        -- No caller can touch staging before owning the idle mailbox. Snapshots
        -- are copied on enqueue and staged only here, never in a command method.
        if job.panel then
            job.stages[#job.stages][2][1] = (io.read_u8(p.INFO + 6) + 1) % 256
        end
        local armed, why = pcall(function() writes:arm("native", allow_for(job)) end)
        if not armed then return nil, "native arm refused: " .. tostring(why) end
        posting = true
        local ok, err = pcall(function()
            assert(present() and io.read_u16(p.BASE + O.opcode) == 0,
                   "native changed before dispatch")
            for _, stage in ipairs(job.stages or {}) do writes:write_bytes(stage[1], stage[2]) end
            if job.op then
                seq = (seq + 1) % 65536
                job.seq = seq
                if #job.args > 0 then writes:write_bytes(p.BASE + O.args, job.args) end
                -- No Lua-side status=BUSY: the patch sets MB->status itself on every ack (OK/FAIL,
                -- and ST_BUSY for the async ops), and ack_seq = seq-1 below already keeps a stale
                -- OK of the previous op from reading as this op's completion (completion needs
                -- ack == seq). Writing BUSY here also made writes.lua's per-byte recheck of the
                -- native_idle clause (status ~= busy) refuse the rest of the post.
                writes:write_u16(p.BASE + O.ack, (seq + 65535) % 65536)
                writes:write_u16(p.BASE + O.seq, seq)
                job.publish_attempted = true -- a sink failure can leave a valid low-byte opcode
                writes:write_u16(p.BASE + O.opcode, job.op) -- publish last
                -- ... and the receipt is the publish's own witness: nothing after it can fail
                job.posted = true
            end
        end)
        posting = false
        writes:disarm()
        if not ok then
            poisoned = "native dispatch interrupted"
            finish(job, poisoned)
            return false, tostring(err)
        end
        if job.op then job.started = io.framecount(); pending = job
        else finish(job) end
        return true
    end

    function self:play_sound(id)
        if not sounds_enabled then return true end
        if not integer(id, 65535) then return nil, "invalid sound" end
        return enqueue({op=assert(p.OP_PLAY_SE), args={id & 255, id >> 8}})
    end
    function self:show_menu(cmd)
        local token = cmd.token
        return enqueue({op=assert(p.OP_SHOW_MENU), args={},
            stages={{p.TEXT_BUF, encode(cmd.text, 256)}},
            done=function(why, result)
                send("menu_result", {token=token, choice=not why and result or 0})
            end})
    end
    function self:show_choices(cmd)
        local options, bytes = cmd.options or {}, {}
        if #options < 1 or #options > 8 then
            send("menu_result", {token=cmd.token, choice=127}); return nil, "invalid choices"
        end
        bytes[1] = #options
        for _, option in ipairs(options) do
            for _, b in ipairs(encode(option, 113)) do bytes[#bytes + 1] = b end
        end
        if #bytes > 112 then
            send("menu_result", {token=cmd.token, choice=127}); return nil, "choices too long"
        end
        local stages = {{p.MENU_BUF, bytes}}
        local with_text = cmd.text and cmd.text ~= "" and 1 or 0
        if with_text == 1 then stages[#stages + 1] = {p.TEXT_BUF, encode(cmd.text, 256)} end
        local token = cmd.token
        return enqueue({op=assert(p.OP_SHOW_CHOICES), args={with_text}, stages=stages,
            done=function(why, result)
                send("menu_result", {token=token, choice=not why and result or 127})
            end})
    end
    function self:choose_mon(cmd)
        local token = cmd.token
        return enqueue({op=assert(p.OP_CHOOSE_PARTY_MON), args={}, done=function(why, result)
            send("mon_chosen", {token=token, slot=not why and result or 7})
        end})
    end
    -- Transport primitives for the later trade FSM. These do not expose
    -- apply_trade to client.lua, choose a target, or implement fallback policy.
    -- The FSM owns identity/preflight and reads back the party after completion.
    -- transfer("enemy", {blobs_hex={...}}, done): OP_SET_ENEMY_PARTY + BLOB_BUF.
    -- transfer("party", {slot, blob_hex, bump?}, done): OP_SET_PARTY_MON + BLOB_BUF.
    -- transfer("scene", {slot}, done): OP_TRADE_SCENE, no staging.
    -- valid (optional): a dispatch-time guard, called by service() immediately before this job is
    -- dispatched (same frame-end callback, CPU stopped); false, why drops the job with done(why).
    -- The trade FSM uses it to re-locate the offered mon at the moment a slot op actually posts.
    function self:transfer(step, cmd, done, valid, progress)
        -- Direct scene probes exercise the legacy transport without claiming
        -- durable completion. The FSM's milestone path still requires capability.
        if step == "scene" and progress ~= nil and not self:trade_capable() then
            if done then done("durable_trade_unavailable") end
            return nil, "durable_trade_unavailable"
        end
        local op, args, stages = nil, {}, {}
        if step == "scene" or step == "party" then
            if not integer(cmd.slot, 5) then return nil, "invalid party slot" end
            args = {cmd.slot}
        end
        if step == "scene" then op = assert(p.OP_TRADE_SCENE)
        elseif step == "party" or step == "enemy" then
            local rows = step == "party" and {cmd.blob_hex} or cmd.blobs_hex
            if type(rows) ~= "table" or #rows < 1 or #rows > 6 then
                return nil, "invalid blobs"
            end
            local bytes = {}
            local mon_size = reads.PARTY_MON_SIZE
            if not integer(mon_size, 600) or mon_size == 0 then return nil, "invalid mon size" end
            for _, hex in ipairs(rows) do
                if type(hex) ~= "string" or #hex ~= 2 * mon_size or hex:find("[^%x]") then
                    return nil, "invalid blobs"
                end
                for i = 1, 2 * mon_size, 2 do bytes[#bytes + 1] = tonumber(hex:sub(i, i + 1), 16) end
            end
            stages = {{p.BLOB_BUF, bytes}}
            if step == "party" then
                op, args = assert(p.OP_SET_PARTY_MON), {cmd.slot, cmd.bump and 1 or 0}
            else op, args = assert(p.OP_SET_ENEMY_PARTY), {#rows} end
        else return nil, "unsupported transfer step" end
        return enqueue({op=op, args=args, stages=stages, done=done, valid=valid, progress=progress})
    end
    -- G5-RR-RIVAL: the patch's rival-swap window W1 (docs/gen3/research/rival_swap_refresh_window.md
    -- §5), mirrored from patch/src/handlers.c's OP_RIVAL_SWAP check (OMP F4): gBattleCommunication[0]
    -- < 15, gBattleMainFunc == BeginBattleIntroDummy and not a LINK battle here; the trainer id in
    -- the caller's guard (gTrainerBattleOpponent_A == the epoch's). The fifth clause, callback2 ==
    -- CB2_HandleStartBattle (RV_CB2_START_BATTLE), has no pack word, so it stays the patch's alone
    -- (a refusal there is REASON_WINDOW_CLOSED, never a write). A post read open at this frame end
    -- is consumed by the next frame's slink_hook, before the callbacks run (§5.2).
    local rr = profile.titles and profile.titles.radical_red
    function self:rival_window_open()
        local ram, rom, der = rr and rr.ram, rr and rr.rom, rr and rr.derived
        if not (ram and rom and der and ram.BATTLE_MAIN_FUNC_ADDR and ram.BATTLE_COMM_ADDR
                and ram.BATTLE_TYPE_ADDR and der.BATTLE_TYPE_LINK_MASK
                and rom.BEGIN_BATTLE_INTRO_DUMMY_ADDR) then
            return false
        end
        return io.read_u8(ram.BATTLE_COMM_ADDR) < 15
               and io.read_u32(ram.BATTLE_MAIN_FUNC_ADDR) == rom.BEGIN_BATTLE_INTRO_DUMMY_ADDR
               and (io.read_u32(ram.BATTLE_TYPE_ADDR) & der.BATTLE_TYPE_LINK_MASK) == 0
    end
    -- guard(epoch): the caller's live epoch check, run at dispatch. hold(epoch) (optional): true
    -- while a PRE-announced swap should wait in the queue for the window -- the job is STAGED, not
    -- posted, and other jobs pass it; once the window opens (or the hold ends) it dispatches.
    function self:replace_rival_team(cmd, guard, hold)
        local trainer = cmd.trainer_id or 0
        local function reply(why, species, reason)
            local fields = {trainer_id=trainer, species_ids=array(species or {}), error=why}
            if reason then fields.reason = reason end
            send("rival_team_replaced", fields)
        end
        local epoch = {session = cmd.session, battle_id = cmd.battle_id, trainer_id = cmd.trainer_id}
        local function in_battle() return deps.in_battle and deps.in_battle() or false end
        local function holding() return hold ~= nil and hold(epoch) == true end
        if not in_battle() and not holding() and not self:rival_window_open() then
            reply("not_in_battle"); return true
        end
        local rows, bytes = cmd.blobs_hex or {}, {}
        if #rows < 1 or #rows > 6 then reply("invalid_blobs"); return true end
        for _, hex in ipairs(rows) do
            if type(hex) ~= "string" or #hex ~= 200 or hex:find("[^%x]") then
                reply("invalid_blobs"); return true
            end
            for i = 1, 200, 2 do bytes[#bytes + 1] = tonumber(hex:sub(i, i + 1), 16) end
        end
        local count = #rows
        return enqueue({op=assert(p.OP_RIVAL_SWAP), args={count, trainer & 255, trainer >> 8},
            ready=function() return self:rival_window_open() or not holding() end,
            valid=function()
                -- C5-11a: the guard runs at DISPATCH, immediately before posting, and every part
                -- is re-evaluated there -- never at enqueue. `guard` is the caller's live epoch
                -- check (client.lua), which owns the identity; this file adds its own in-battle
                -- and interval checks so a job can never post outside them. OMP F3: while the
                -- caller's hold still lasts, a failed check is a read that is NOT READY yet (the
                -- third return keeps the job queued); only an ended hold makes it a refusal.
                local ok, why = true, nil
                if not in_battle() and not self:rival_window_open() then ok, why = false, "not_in_battle"
                elseif guard then ok, why = guard(epoch) end
                if not ok then return false, why, holding() end
                return true
            end,
            stages={{p.BLOB_BUF, bytes}}, done=function(why, _result, reason)
                -- the patch's own ST_FAIL reason is the error (review F3): window_closed,
                -- bad_args, ...; an unnamed word stays "native_refused", never a guess
                if why then
                    reply(why == "native refused" and (reason or "native_refused") or why, nil, reason)
                    return
                end
                local ram = assert(profile.titles.radical_red.ram)
                local actual = io.read_bytes(ram.ENEMY_BASE, #bytes)
                for i, b in ipairs(bytes) do
                    if actual[i] ~= b then reply("enemy_readback_failed"); return end
                end
                if io.read_u8(ram.ENEMY_COUNT_ADDR) ~= count then
                    reply("enemy_readback_failed"); return
                end
                -- No gBattleMons refresh (G5-RR-RIVAL): OP_RIVAL_SWAP is consumed only inside W1,
                -- BEFORE the engine selects and snapshots the enemy lead, so the engine's own
                -- converter builds gBattleMons from the swapped party (window doc §5 "What ends up
                -- correct"). The readback above is the whole success condition.
                local species = {}
                for i = 0, count - 1 do
                    local raw = {}
                    for j = 1, 100 do raw[j] = actual[i * 100 + j] end
                    local mon = reads.decode_party_mon(raw)
                    if not mon then reply("enemy_readback_failed"); return end
                    species[#species + 1] = mon.species
                end
                -- OMP F2 post-condition: the engine builds gBattleMons[1] from the swapped party
                -- (BattleIntroDrawTrainersOrMonsSprites); success waits, bounded, for its
                -- personality to be one of the staged mons', else enemy_snapshot_stale.
                -- ponytail: a value that is ALREADY a staged PID at the ack (a rematch against the
                -- same team) cannot be told from the new write, so it is accepted at once.
                local pids = {}
                for i = 0, count - 1 do
                    local o = i * 100
                    pids[actual[o + 1] | actual[o + 2] << 8 | actual[o + 3] << 16 | actual[o + 4] << 24] = true
                end
                local lead_pid = ram.BATTLE_MONS_ADDR + 0x58 + 0x48   -- gBattleMons[1].personality
                watches[#watches + 1] = {deadline = io.framecount() + SNAPSHOT_FRAMES,
                    check = function() return pids[io.read_u32(lead_pid)] == true end,
                    ok = function() reply(nil, species) end,
                    fail = function() reply("enemy_snapshot_stale") end}
            end})
    end

    local function panel_job(open)
        local pages = math.max(1, math.ceil(#panel_rows / p.INFO_MAXLINES))
        panel_page = panel_page % pages
        local rows = {}
        for i = panel_page * p.INFO_MAXLINES + 1,
                math.min(#panel_rows, (panel_page + 1) * p.INFO_MAXLINES) do
            rows[#rows + 1] = panel_rows[i]:gsub("|", "\n")
        end
        if #rows == 0 then rows[1] = "No run data yet" end
        local stages = {{p.INFO, {1}}}
        for i, row in ipairs(rows) do
            stages[#stages + 1] = {p.INFO + 8 + (i - 1) * p.INFO_LINEW, encode(row, p.INFO_LINEW)}
        end
        stages[#stages + 1] = {p.INFO + 8 + p.INFO_PAGESLOT * p.INFO_LINEW,
            encode(string.format("PAGE %d/%d", panel_page + 1, pages), p.INFO_LINEW)}
        stages[#stages + 1] = {p.INFO + 4, {panel_page, pages}}
        stages[#stages + 1] = {p.INFO + 3, {#rows}} -- publish lines after all strings
        stages[#stages + 1] = {p.INFO + 6, {(io.read_u8(p.INFO + 6) + 1) % 256}}
        return {op=open and assert(p.OP_SHOW_INFO) or nil, args={panel_page}, stages=stages, panel=true,
            done=function(why, result)
                if open and not why and result == 0 and pages > 1 then
                    panel_page = (panel_page + 1) % pages
                    enqueue(panel_job(true))
                elseif open and not why then
                    panel_page = 0
                    enqueue(panel_job(false))
                end
            end}
    end
    function self:link_panel(cmd)
        if v2 then return nil, "v2 panel binding unavailable" end
        panel_rows, panel_page = clone(cmd.rows or {}), 0
        return enqueue(panel_job(false))
    end
    function self:config(cmd)
        if cmd.native_sounds ~= nil then sounds_enabled = cmd.native_sounds == true end
        if v2 then return nil, "v2 control binding unavailable" end
        local stages = {}
        if cmd.overworld_presence ~= nil or cmd.pc_trade_npc ~= nil then
            npc_enabled = cmd.overworld_presence ~= true and cmd.pc_trade_npc ~= false
            stages[#stages + 1] = {p.TN_ENABLE, {npc_enabled and 1 or 0}}
        end
        if cmd.battle_calc ~= nil then
            stages[#stages + 1] = {p.CALC_OFF, {cmd.battle_calc and 0 or 1}}
        end
        if #stages == 0 then return true end
        return enqueue({stages=stages})
    end

    function self:service()
        local frame, here = io.framecount(), present()
        local owned_panel = pending and pending.panel
        if (last_frame and frame < last_frame) or (was_present and not here) then
            abort("native reset")
            poisoned, npc_count, panel_drawn, panel_showing = nil, nil, nil, false
            session_epoch = 0
        end
        last_frame, was_present = frame, here
        if not here then return nil, "native absent" end
        if v2 and session_epoch ~= 0 and io.read_u32(p.BASE + O.session_epoch) ~= session_epoch then
            poisoned = "native epoch changed"
            abort(poisoned)
        end
        if pending then
            local job = pending
            local opcode = io.read_u16(p.BASE + O.opcode)
            if io.read_u16(p.BASE + O.seq) ~= job.seq or (opcode ~= 0 and opcode ~= job.op) then
                poisoned = "native sequence overwritten"; abort(poisoned)
            elseif not stage_intact(job) then
                poisoned = "native staging overwritten"; abort(poisoned)
            elseif io.read_u16(p.BASE + O.ack) == job.seq
                and (io.read_u16(p.BASE + O.status) == OK or io.read_u16(p.BASE + O.status) == FAIL) then
                local status, result = io.read_u16(p.BASE + O.status), io.read_u8(p.BASE + O.result)
                local reason = status == FAIL and io.read_u16(p.BASE + O.reason) or nil
                pending = nil -- consume receipt BEFORE any next post can rewrite it
                finish(job, status == FAIL and "native refused" or nil, result,
                       reason and fail_reasons[reason] or nil)
            elseif frame - job.started >= timeout_for(job.op) then
                -- Never reuse a timed-out slot: opcode==0 can mean an async handler
                -- still owns it. A reset/absent beacon is the recovery boundary.
                -- Poison blocks further posts. Durable trade treats a possibly committed
                -- operation as uncertain; neither raw replacement nor RAM readback repairs it.
                poisoned = "native timeout"; abort(poisoned)
            end
        end
        if poisoned then return nil, poisoned end
        for i = #watches, 1, -1 do
            local wt = watches[i]
            if wt.check() then table.remove(watches, i); wt.ok()
            elseif io.framecount() >= wt.deadline then table.remove(watches, i); wt.fail() end
        end
        if not v2 then -- v1 NPC/panel offsets are never inherited by a v2 mailbox
            local counter = io.read_u8(p.PI_COUNT)
            if npc_count ~= nil and counter > npc_count and npc_enabled and not pending then
                send("trade_request", {})
            end
            npc_count = counter -- backwards counters re-latch; never synthesize an interaction
            local drawn = io.read_u8(p.INFO + 2)
            if panel_drawn ~= nil and drawn ~= panel_drawn and not owned_panel then
                panel_showing = true
            end
            panel_drawn = drawn
            if panel_showing and deps.panel_closed then
                local closed, result = deps.panel_closed()
                if closed then
                    panel_showing = false
                    if not pending then
                        panel_page = result == 0 and panel_page + 1 or 0
                        enqueue(panel_job(result == 0 and #panel_rows > p.INFO_MAXLINES))
                    end
                end
            end
        end
        if not self:idle() or #queue == 0 then return true end
        -- a job whose `ready` says "not yet" (a staged rival swap waiting for its window) stays
        -- queued and does not block the jobs behind it
        local at = 1
        while queue[at] and queue[at].ready and not queue[at].ready() do at = at + 1 end
        local job = queue[at]
        if not job then return true end
        if job.valid then
            local valid, why, retry = job.valid()
            if not valid and retry then return true end         -- not ready yet: stays queued
            if not valid then table.remove(queue, at); finish(job, why); return nil, why end
        end
        local ok, why = dispatch(job)
        if ok ~= nil then table.remove(queue, at) end
        if ok == false then abort(poisoned) end
        return ok, why
    end
    return self
end
return N
