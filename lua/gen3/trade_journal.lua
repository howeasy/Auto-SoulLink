-- T3-R5: process-independent write-ahead intent. No cartridge writes or trade admission.
-- store.update(fn) serializes readers/writers and durably commits fn's new text BEFORE
-- returning its answer. The bootstrap owns that file/flush contract; this module never
-- replaces missing/corrupt storage with an empty journal. initial() is explicit provisioning.
local J = {}
local LOCK_BUSY = {} -- acquisition-only signal; never used for read/write/seal failures
local U32 = 0xFFFFFFFF
local MAGIC = "SLINK-TRADE-JOURNAL-1\n"
local MAX_BYTES = 16 * 1024 * 1024
local FINAL = {committed=true, rolled_back=true, split=true, resolved=true}
local function integer(n, low, high)
    return type(n) == "number" and n == math.floor(n) and n >= low and n <= high
end
function J.next_epoch(n)
    if not integer(n,0,U32) then return nil, "invalid trade epoch counter" end
    if n == U32 then return nil, "trade epoch exhausted" end
    return math.tointeger(n) + 1
end
local function text(v, max)
    return type(v) == "string" and #v > 0 and #v <= max and not v:find("[^ -~]")
end
local function hash(s)
    local h = 2166136261
    for i=1,#s do h = ((h ~ s:byte(i)) * 16777619) & U32 end
    return string.format("%08x", h)
end
local function exact(t, keys)
    if type(t) ~= "table" then return false end
    local set = {}
    for _, key in ipairs(keys) do set[key] = true end
    for key in pairs(t) do if not set[key] then return false end end
    for key in pairs(set) do if t[key] == nil then return false end end
    return true
end
local BINDING_KEYS = {"rom_sha1", "player", "run_id", "ot_id"}
local RECORD_KEYS = {"binding", "token", "epoch", "final"}
local function binding(b)
    return exact(b, BINDING_KEYS) and type(b.rom_sha1) == "string" and #b.rom_sha1 == 40
        and not b.rom_sha1:find("[^0-9a-f]") and (b.player == "a" or b.player == "b")
        and text(b.run_id, 256) and text(b.ot_id, 64)
end
local function same(a, b)
    if not a or not b then return false end
    for _, key in ipairs(BINDING_KEYS) do if a[key] ~= b[key] then return false end end
    return true
end
local function record_id(r) return tostring(r.epoch) .. ":" .. r.token end
local function valid(s)
    if not exact(s, {"schema", "revision", "counter", "records"}) or s.schema ~= 1
       or not integer(s.revision, 0, U32) or not integer(s.counter, 0, U32)
       or type(s.records) ~= "table" then return false end
    local seen = {}
    for k in pairs(s.records) do if not integer(k, 1, #s.records) then return false end end
    for _, r in ipairs(s.records) do
        if not exact(r, RECORD_KEYS) or not binding(r.binding) or not text(r.token, 256)
           or not integer(r.epoch, 1, s.counter) or (r.final ~= "" and not FINAL[r.final]) then return false end
        local id = record_id(r)
        if seen[id] then return false end
        seen[id] = true
    end
    return true
end
-- Canonical scalar/key order also makes duplicate JSON keys, arbitrary reordering and
-- noncanonical numeric spellings corruption, rather than silently overwriting an intent.
local function encode(json, s)
    local function quote(v) return assert(json.encode(v)) end
    local records = {}
    for i,r in ipairs(s.records) do
        local b, fields = r.binding, {}
        for _, k in ipairs(BINDING_KEYS) do fields[#fields+1] = quote(k) .. ":" .. quote(b[k]) end
        records[i] = '{"binding":{' .. table.concat(fields, ",") .. '},"token":' .. quote(r.token)
            .. ',"epoch":' .. quote(r.epoch) .. ',"final":' .. quote(r.final) .. '}'
    end
    return '{"schema":1,"revision":' .. quote(s.revision) .. ',"counter":' .. quote(s.counter)
        .. ',"records":[' .. table.concat(records, ",") .. ']}'
end
local function frame(body) return tostring(#body) .. ":" .. hash(body) .. ":" .. body .. "\n" end
function J.initial(json)
    return MAGIC .. frame(encode(json, {schema=1, revision=0, counter=0, records={}}))
end
local function decode(json, bytes)
    assert(type(bytes) == "string" and #bytes <= MAX_BYTES and bytes:sub(1,#MAGIC) == MAGIC,
           "missing or invalid trade journal")
    local pos, previous = #MAGIC + 1, nil
    while pos <= #bytes do
        local start, finish, n, digest = bytes:find("(%d+):([0-9a-f]+):", pos)
        assert(start == pos and #digest == 8, "torn journal frame")
        n = tonumber(n)
        assert(integer(n, 1, MAX_BYTES) and tostring(n) == bytes:sub(start, start + #tostring(n) - 1), "invalid journal length")
        local body = bytes:sub(finish + 1, finish + n)
        assert(#body == n and bytes:sub(finish+n+1, finish+n+1) == "\n" and hash(body) == digest,
               "torn journal payload")
        local s = json.decode(body)
        assert(valid(s) and encode(json,s) == body, "corrupt or ambiguous journal state")
        if previous then
            assert(s.revision == previous.revision + 1 and s.counter >= previous.counter
                   and s.counter <= previous.counter + 1, "journal sequence rollback")
        else
            assert(s.revision == 0 and s.counter == 0 and #s.records == 0, "missing journal genesis")
        end
        previous, pos = s, finish + n + 2
    end
    assert(previous, "empty journal")
    return previous
end
J.decode = decode

-- Two durable files, one OS-exclusive guard handle. The append-only log is committed
-- before its guard seal, and BOTH are flushed before an intent/epoch is returned.
-- A partial append, lost guard/log, or mismatched rollback is therefore ambiguous
-- and refused. Restoring a mutually consistent older log+guard pair is not detectable
-- without an external freshness authority. Never delete the guard to "repair" an
-- installation. Removing every artifact is outside the automatic recovery contract.
function J.file_store(d)
    local fs, path, json = assert(d.fs), assert(d.path), assert(d.json)
    local function seal(bytes) return MAGIC .. tostring(#bytes) .. ":" .. hash(bytes) .. "\n" end
    local function locked(transform)
        local guard, fresh, why = fs.lock(path .. ".guard")
        if not guard then
            if why == "busy" then error(LOCK_BUSY) end
            error("trade journal lock unavailable: " .. tostring(why))
        end
        local ok, answer = pcall(function()
            local bytes = fs.read_file(path .. ".log")
            if fresh then
                assert(bytes == nil, "journal guard missing beside an existing log")
                bytes = J.initial(json)
                assert(fs.create_file(path .. ".log", bytes) == true, "journal genesis not durable")
                assert(fs.write_handle(guard,seal(bytes)) == true, "journal guard not durable")
            end
            assert(type(bytes) == "string" and fs.read_handle(guard) == seal(bytes),
                   "missing, torn or rolled-back trade journal")
            decode(json,bytes)
            if not transform then return bytes end
            local output, value = transform(bytes)
            assert(type(output) == "string" and output:sub(1,#bytes) == bytes, "journal update is not an append")
            if output == bytes then return value end
            decode(json,output)
            assert(fs.append_file(path .. ".log",output:sub(#bytes+1)) == true, "journal append not durable")
            assert(fs.read_file(path .. ".log") == output, "journal append readback mismatch")
            assert(fs.write_handle(guard,seal(output)) == true, "journal seal not durable")
            assert(fs.read_handle(guard) == seal(output), "journal seal readback mismatch")
            return value
        end)
        local closed, close_result = pcall(fs.close,guard)
        assert(closed and close_result == true, "journal lock close failed")
        if not ok then error(answer) end
        return answer
    end
    return {read=function() return locked() end, update=function(fn) return locked(fn) end}
end

-- SOURCE: pokefirered c75f3523 / pokeemerald c65e93f2 save.c, GFRomHeader,
-- and the independent Python oracle server/adapters/gen3_codec.py:539-638.
-- RR is keyed by its wire rom_type and never borrows FR's layout: CFRU's 0xFF0 chunk
-- (docs/gen3/research/rr_save_layout.md sec 1), gSaveCounter from RR's own CFRU save
-- bodies' pool words (0x090B8C70/0x090B8DC4), SaveBlock pointers from the write
-- checkpoint's ROM-read SetSaveBlocksPointers pool (the profile's SB1_PTR_ADDR is legacy).
J.RELOAD_LAYOUTS = {
    firered_rr={counter=0x03005390, sb2_size=0xF24, sb1_size=0x3D68, count_offset=0x34, party_offset=0x38,
                chunk=0xFF0, sb1_ptr=0x03005008, sb2_ptr=0x0300500C},
    firered={counter=0x03005390, sb2_size=0xF24, sb1_size=0x3D68, count_offset=0x34, party_offset=0x38},
    leafgreen={counter=0x03005390, sb2_size=0xF24, sb1_size=0x3D68, count_offset=0x34, party_offset=0x38},
    emerald={counter=0x03006200, sb2_size=0xF2C, sb1_size=0x3D88, count_offset=0x234, party_offset=0x238},
}
local PROOF = {}
local function word(bytes, offset, n)
    local v = 0
    for i=0,n-1 do v = v | (assert(bytes:byte(offset+i+1), "short save data") << (8*i)) end
    return v
end
local function flash_slot(bytes, first, layout)
    local sections, counter, signatures = {}, nil, 0
    for slot=first,first+13 do
        local at = slot * 0x1000
        if word(bytes,at+0xFF8,4) == 0x08012025 then
            signatures = signatures + 1
            local id = word(bytes,at+0xFF4,2)
            if id > 13 or sections[id] then return nil, "duplicate/invalid save section" end
            local size, chunk = nil, layout.chunk or 0xF80
            if id == 0 then size = layout.sb2_size
            elseif id <= 4 then size = math.min(chunk,layout.sb1_size-(id-1)*chunk)
            else size = math.min(chunk,0x83D0-(id-5)*chunk) end
            local sum = 0
            for p=0,size-4,4 do sum = (sum + word(bytes,at+p,4)) & U32 end
            if ((sum >> 16) + sum) & 0xFFFF ~= word(bytes,at+0xFF6,2) then return nil, "save checksum mismatch" end
            local current = word(bytes,at+0xFFC,4)
            if counter ~= nil and counter ~= current then return nil, "mixed save counters" end
            counter, sections[id] = current, bytes:sub(at+1,at+size)
        end
    end
    if signatures == 0 then return false end -- erased/never-used other slot
    if signatures ~= 14 then return nil, "incomplete save slot" end
    return {counter=counter, sb2=sections[0], sb1=table.concat({sections[1],sections[2],sections[3],sections[4]})}
end
function J.verify_reload(request)
    local ok, result = pcall(function()
        local layout = assert(J.RELOAD_LAYOUTS[request.title], "reload layout unqualified for this title")
        assert(type(request.rom_sha1) == "string" and #request.rom_sha1 == 40
               and not request.rom_sha1:find("[^0-9a-f]"), "reload cartridge identity missing")
        assert(request.boot_seen == true, "no observed cleared boot state")
        local bytes = request.flash_before
        assert(type(bytes) == "string" and (#bytes == 0x20000 or #bytes == 0x20010), "invalid battery length")
        assert(bytes == request.flash_after, "battery changed during verification")
        local a, why_a = flash_slot(bytes,0,layout)
        local b, why_b = flash_slot(bytes,14,layout)
        assert(a ~= nil and b ~= nil, why_a or why_b or "invalid save slot")
        assert(a or b, "no valid save slot")
        local saved = a or b
        if a and b then
            if a.counter == b.counter then
                assert(a.sb1 == b.sb1 and a.sb2 == b.sb2, "ambiguous equal-counter saves")
            elseif a.counter == U32 and b.counter == 0 then saved = b
            elseif b.counter == U32 and a.counter == 0 then saved = a
            elseif b.counter > a.counter then saved = b end
        end
        local before, after = request.ram_before, request.ram_after
        assert(type(before) == "table" and type(after) == "table", "live save snapshot missing")
        for _, key in ipairs({"counter", "ot_id", "party_count", "party", "sb1", "sb2"}) do
            assert(before[key] ~= nil and before[key] == after[key], "live save snapshot changed: " .. key)
        end
        for _, key in ipairs({"sb1", "sb2"}) do
            assert(integer(before[key],0x02000000,0x0203FFFF) and before[key] % 4 == 0, "invalid live save block")
        end
        local count = word(saved.sb1,layout.count_offset,4)
        assert(integer(count,1,6) and before.party_count == count, "saved/live party count mismatch")
        assert(before.counter == saved.counter, "saved/live counter mismatch")
        assert(before.ot_id == word(saved.sb2,10,4), "saved/live trainer mismatch")
        assert(before.party == saved.sb1:sub(layout.party_offset+1,layout.party_offset+count*100),
               "saved/live party bytes mismatch")
        return {seal=PROOF, counter=saved.counter, ot_id=string.format("%08X",before.ot_id), rom_sha1=request.rom_sha1}
    end)
    if not ok then return nil, tostring(result) end
    return result
end

function J.new(d)
    local json, store = assert(d.json), assert(d.store)
    local self = {allowed={}, qualified={}}
    local context
    local function failed(why)
        if not self.failure then
            self.failure = "trade journal: " .. tostring(why)
            if d.log then pcall(d.log,self.failure) end -- console diagnostics only; never HUD text
        end
        return nil, self.failure
    end
    local cache_frame, busy_frame
    local function read(fresh)
        if self.failure then return nil end
        local now = d.frame and d.frame()
        if self.busy and now ~= nil and busy_frame == now then return nil end
        if not fresh and now ~= nil and cache_frame == now and self.state then return self.state end
        local ok, state = pcall(function() return decode(json, store.read()) end)
        if not ok then
            if state == LOCK_BUSY then
                self.busy, busy_frame, cache_frame = true, now, nil
            else failed(state) end
            return nil
        end
        self.busy, busy_frame = nil, nil
        self.state = state
        cache_frame = now
        return state
    end
    local function update(fn)
        if self.failure then return nil, self.failure end
        local now = d.frame and d.frame()
        if self.busy and now ~= nil and busy_frame == now then return nil, "trade journal lock busy" end
        local ok, answer = pcall(function()
            return store.update(function(bytes)
                local s = decode(json, bytes)
                assert(s.revision < U32, "journal revisions exhausted")
                local before = encode(json,s)
                local value = fn(s)
                if encode(json,s) == before then self.state=s; return bytes,value end
                s.revision = s.revision + 1
                assert(valid(s), "invalid journal mutation")
                local output = bytes .. frame(encode(json,s))
                assert(#output <= MAX_BYTES, "trade journal full")
                self.state = s
                cache_frame = nil
                return output, value
            end)
        end)
        if not ok then
            if answer == LOCK_BUSY then
                self.busy, busy_frame, cache_frame = true, now, nil
                return nil, "trade journal lock busy"
            end
            return failed(answer)
        end
        self.busy, busy_frame = nil, nil
        return answer
    end
    function self:bind(run_id, ot_id)
        self.qualified = {} -- a newly accepted connection needs fresh local reload evidence
        if not text(run_id,256) then return nil, "run_id must be nonempty printable ASCII (max 256 bytes)" end
        local b = {rom_sha1=d.rom_sha1, player=d.player, run_id=run_id, ot_id=ot_id}
        if not binding(b) then return nil, "invalid cartridge/player/run binding" end
        if context and not same(context,b) then self.allowed = {} end
        context = b
        return true
    end
    function self:ready()
        if self.busy then read(true) end
        if self.failure or self.busy or not context then return false end
        for _, r in ipairs((self.state or {}).records or {}) do
            if r.binding.rom_sha1 == d.rom_sha1 and r.binding.player == d.player and not same(r.binding,context) then
                return false
            end
        end
        return true
    end
    function self:unbind() context = nil; self.allowed, self.qualified = {}, {} end
    function self:lease_open(value, epoch)
        local s = read(true)
        if not s then return false end
        for _, r in ipairs(s.records) do
            if same(r.binding,context) and r.token == value and r.epoch == epoch then return r.final == "" end
        end
        return false
    end
    function self:allocate()
        if not self:ready() then return nil, self.failure or "run identity not bound" end
        return update(function(s)
            local next_value, why = J.next_epoch(s.counter)
            assert(next_value,why)
            s.counter = next_value
            return s.counter
        end)
    end
    function self:arm(value, epoch)
        if not text(value,256) then return nil, "token must be nonempty printable ASCII (max 256 bytes)" end
        if not self:ready() or not integer(epoch,1,U32) then
            return nil, self.failure or "invalid write-ahead lease"
        end
        epoch = math.tointeger(epoch)
        return update(function(s)
            assert(epoch <= s.counter, "unallocated trade epoch")
            for _, r in ipairs(s.records) do
                if r.token == value and r.epoch == epoch and same(r.binding,context) then return true end
                -- Recheck under the storage lock: another process may have armed a
                -- different run after this instance's cached readiness/prepare.
                assert(r.binding.rom_sha1 ~= d.rom_sha1 or r.binding.player ~= d.player,
                       "unsettled lease already exists for this cartridge/player")
            end
            s.records[#s.records+1] = {binding=context, token=value, epoch=epoch, final=""}
            return true
        end)
    end
    function self:outstanding()
        local out, s = json.array(), read()
        if not s then return nil, self.failure end
        for _, r in ipairs(s.records) do
            if same(r.binding,context) and not self.allowed[record_id(r)] then
                out[#out+1] = {token=r.token, epoch=r.epoch}
            end
        end
        return out
    end
    function self:has_entries()
        local s = read()
        if not s then return true end
        for _, r in ipairs(s.records) do
            if r.binding.rom_sha1 == d.rom_sha1 and r.binding.player == d.player then return true end
        end
        return false
    end
    function self:hidden()
        local s = read()
        if not s then return true end
        for _, r in ipairs(s.records) do
            if r.binding.rom_sha1 == d.rom_sha1 and r.binding.player == d.player
               and not self.allowed[record_id(r)] then return true end
        end
        return false
    end
    function self:final(value, epoch, verdict)
        if not context or not text(value,256) or not FINAL[verdict]
           or (epoch ~= nil and not integer(epoch,1,U32)) then return nil, "invalid terminal notification" end
        return update(function(s)
            local candidates = {}
            for i,r in ipairs(s.records) do
                if same(r.binding,context) and r.token == value and (epoch == nil or r.epoch == epoch) then
                    candidates[#candidates+1] = i
                end
            end
            assert(#candidates <= 1, "ambiguous terminal epoch")
            if #candidates == 0 then return false end
            local i = candidates[1]
            local r = s.records[i]
            assert(r.final == "" or r.final == verdict, "conflicting terminal verdict")
            r.final = verdict
            -- Server bookkeeping never establishes local durability.
            if self.allowed[record_id(r)] then table.remove(s.records,i) end
            return true
        end)
    end
    local function allow(value, epoch)
        local s = read()
        if not s then return nil, self.failure or (self.busy and "trade journal lock busy") end
        for _, r in ipairs(s.records) do
            if same(r.binding,context) and r.token == value and r.epoch == epoch then
                local id = record_id(r)
                if r.final ~= "" then
                    -- The terminal write may contend after this read. Do not expose the party
                    -- until that retirement is durably committed under its own guard hold.
                    local was_allowed = self.allowed[id]
                    self.allowed[id] = true
                    local ok, why = self:final(value,epoch,r.final)
                    if ok ~= true then self.allowed[id] = was_allowed; return ok, why end
                    return true
                end
                self.allowed[id] = true
                return true
            end
        end
        return nil, "unknown journal lease"
    end
    function self:native_saved(value, epoch)
        -- Called after every native milestone AND a successful host SaveRAM flush.
        return allow(value,epoch)
    end
    function self:precommit_unchanged(value, epoch)
        -- No scene publication (or an explicitly qualified native precommit refusal).
        return allow(value,epoch)
    end
    function self:qualify(proof)
        if type(proof) ~= "table" or proof.seal ~= PROOF or not context or proof.ot_id ~= context.ot_id
           or proof.rom_sha1 ~= context.rom_sha1 then
            return nil, "unqualified reload proof or wrong trainer"
        end
        local s = read()
        if not s then return nil, self.failure end
        for _, r in ipairs(s.records) do
            if same(r.binding,context) then self.qualified[record_id(r)] = true end
        end
        return true
    end
    function self:declared(value, epoch)
        if not integer(epoch,1,U32) then return nil, "invalid recovery declaration epoch" end
        local id = tostring(math.tointeger(epoch)) .. ":" .. tostring(value)
        if not self.qualified[id] then return nil, "reload proof still required" end
        return allow(value,epoch)
    end
    function self:qualified_records()
        local out, s = json.array(), read()
        if not s then return nil, self.failure end
        for _, r in ipairs(s.records) do
            if same(r.binding,context) and self.qualified[record_id(r)] and not self.allowed[record_id(r)] then
                out[#out+1] = {token=r.token,epoch=r.epoch}
            end
        end
        return out
    end
    function self:discontinuity() self.allowed, self.qualified = {}, {} end
    read()
    return self
end
return J
