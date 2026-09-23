-- RR companion ABI v1, injected and single-owner. No emulator globals.
-- ABI offsets/statuses: patch/src/ADDRESSES.md:366ff; handlers.c Mailbox/ack.
-- Absolute addresses/opcodes come only from the full pack's profile.native.
-- N.new(pack, {io, writes, reads, send(event, fields), in_battle,
--             artifact_kind, refresh_enemy(count), panel_closed(),
--             array(table)?, timeout_frames?, initial_seq?}).
-- refresh_enemy must refresh active gBattleMons through a qualified write window;
-- OP_SET_ENEMY_PARTY only copies gEnemyParty (handlers.c:1867-1888).
-- panel_closed returns (closed, result) for the start-menu-driven panel. Its
-- caller binds field/script/result facts; no legacy literal address is imported.
local N = {}
local O = {abi=4, opcode=6, seq=8, status=10, ack=12, reason=14, args=16, result=48}
local BUSY, OK, FAIL = 1, 2, 3
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
    local io, writes = assert(deps.io), assert(deps.writes)
    local send = assert(deps.send, "send(event, fields) required")
    local array = deps.array or function(t) return t end
    local reads = assert(deps.reads, "Gen 3 read facade required")
    local queue, pending, poisoned, posting = {}, nil, nil, false
    local seq = deps.initial_seq or 0
    assert(integer(seq, 65535), "invalid initial sequence")
    local last_frame, was_present, npc_count, panel_drawn
    local npc_enabled, sounds_enabled = false, true
    local panel_rows, panel_page, panel_showing = {}, 0, false
    local timeout = deps.timeout_frames or 1800
    local self = {}

    local function present()
        if profile.pack ~= "gen3_rr" or deps.artifact_kind ~= "companion" then return false end
        local ok, value = pcall(function()
            return io.read_u32(p.BASE) == p.SIG and io.read_u16(p.BASE + O.abi) == p.ABI
        end)
        return ok and value == true
    end
    function self:idle()
        if poisoned or pending or panel_showing then return false end
        if not present() then return true end -- absence is safe for the Lua fallback
        local ok, value = pcall(function()
            return io.read_u16(p.BASE + O.opcode) == 0
                   and (posting or io.read_u16(p.BASE + O.status) ~= BUSY)
                   and io.read_u8(p.INFO + 1) == io.read_u8(p.INFO + 2)
        end)
        return ok and value == true
    end
    function self:trade_active() return false end -- apply_trade belongs to the trade card
    function self:hello_fields() return {} end -- no invented wire capability fields

    local function finish(job, why, result)
        if job.done then job.done(why, result) end
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
        if #queue >= 64 then finish(job, "native queue full"); return nil, "native queue full" end
        queue[#queue + 1] = job
        return true
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
                writes:write_u16(p.BASE + O.status, BUSY)
                writes:write_u16(p.BASE + O.ack, (seq + 65535) % 65536)
                writes:write_u16(p.BASE + O.seq, seq)
                writes:write_u16(p.BASE + O.opcode, job.op) -- publish last
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
    function self:transfer(step, cmd, done)
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
            for _, hex in ipairs(rows) do
                if type(hex) ~= "string" or #hex ~= 200 or hex:find("[^%x]") then
                    return nil, "invalid blobs"
                end
                for i = 1, 200, 2 do bytes[#bytes + 1] = tonumber(hex:sub(i, i + 1), 16) end
            end
            stages = {{p.BLOB_BUF, bytes}}
            if step == "party" then
                op, args = assert(p.OP_SET_PARTY_MON), {cmd.slot, cmd.bump and 1 or 0}
            else op, args = assert(p.OP_SET_ENEMY_PARTY), {#rows} end
        else return nil, "unsupported transfer step" end
        return enqueue({op=op, args=args, stages=stages, done=done})
    end
    function self:replace_rival_team(cmd)
        local trainer = cmd.trainer_id or 0
        local function reply(why, species)
            send("rival_team_replaced", {trainer_id=trainer, species_ids=array(species or {}), error=why})
        end
        if not deps.in_battle or not deps.in_battle() then reply("not_in_battle"); return true end
        if not deps.refresh_enemy then reply("refresh_required"); return true end
        local rows, bytes = cmd.blobs_hex or {}, {}
        if #rows < 1 or #rows > 6 then reply("invalid_blobs"); return true end
        for _, hex in ipairs(rows) do
            if type(hex) ~= "string" or #hex ~= 200 or hex:find("[^%x]") then
                reply("invalid_blobs"); return true
            end
            for i = 1, 200, 2 do bytes[#bytes + 1] = tonumber(hex:sub(i, i + 1), 16) end
        end
        local count = #rows
        return enqueue({op=assert(p.OP_SET_ENEMY_PARTY), args={count},
            valid=function() return deps.in_battle(), "not_in_battle" end,
            stages={{p.BLOB_BUF, bytes}}, done=function(why)
                if why then reply(why); return end
                local ram = assert(profile.titles.radical_red.ram)
                local actual = io.read_bytes(ram.ENEMY_BASE, #bytes)
                for i, b in ipairs(bytes) do
                    if actual[i] ~= b then reply("enemy_readback_failed"); return end
                end
                if io.read_u8(ram.ENEMY_COUNT_ADDR) ~= count then
                    reply("enemy_readback_failed"); return
                end
                local refreshed, refresh_ok = pcall(deps.refresh_enemy, count)
                if not refreshed or refresh_ok ~= true then reply("refresh_failed"); return end
                local species = {}
                for i = 0, count - 1 do
                    local raw = {}
                    for j = 1, 100 do raw[j] = actual[i * 100 + j] end
                    local mon = reads.decode_party_mon(raw)
                    if not mon then reply("enemy_readback_failed"); return end
                    species[#species + 1] = mon.species
                end
                reply(nil, species)
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
        panel_rows, panel_page = clone(cmd.rows or {}), 0
        return enqueue(panel_job(false))
    end
    function self:config(cmd)
        if cmd.native_sounds ~= nil then sounds_enabled = cmd.native_sounds == true end
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
        end
        last_frame, was_present = frame, here
        if not here then return nil, "native absent" end
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
                pending = nil -- consume receipt BEFORE any next post can rewrite it
                finish(job, status == FAIL and "native refused" or nil, result)
            elseif frame - job.started >= timeout then
                -- Never reuse a timed-out slot: opcode==0 can mean an async handler
                -- still owns it. A reset/absent beacon is the recovery boundary.
                poisoned = "native timeout"; abort(poisoned)
            end
        end
        if poisoned then return nil, poisoned end
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
        if not self:idle() or #queue == 0 then return true end
        local job = queue[1]
        if job.valid then
            local valid, why = job.valid()
            if not valid then table.remove(queue, 1); finish(job, why); return nil, why end
        end
        local ok, why = dispatch(job)
        if ok ~= nil then table.remove(queue, 1) end
        if ok == false then abort(poisoned) end
        return ok, why
    end
    return self
end
return N
