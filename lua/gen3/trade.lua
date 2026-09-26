-- Durable trade protocol over a cartridge transport. No writes or ABI addresses.
-- Native owns all staging/publication and proves visit/save/commit milestones.
local T = {}
local function token(v) return type(v) == "string" and v ~= "" end
local function copy(t)
    local out = {}
    for k, v in pairs(t) do out[k] = v end
    return out
end
function T.new(d)
    local native = assert(d.native)
    local active, prepared = nil, nil
    local retired, owed, uncertain_records = {}, {}, {}
    local self = {}
    local function may_commit(t)
        return t.commit_entered or (t.scene_job and (t.scene_job.posted or t.scene_job.publish_attempted))
    end
    local function emit(name, fields)
        owed[#owed + 1] = {name, fields}
    end
    local function flush()
        if not d.ready_to_send() then return end
        while owed[1] do
            local row = owed[1]
            if d.send(row[1], copy(row[2])) == false then return end
            table.remove(owed, 1)
        end
    end
    local function locate(old_key)
        local party = d.party()
        if type(party) ~= "table" or #party < 1 or #party > d.capacity then return nil end
        local found
        for _, mon in ipairs(party) do
            if d.key(mon) == old_key then
                if found then return nil end
                found = mon
            end
        end
        if not found or type(found.slot) ~= "number" or found.slot % 1 ~= 0 or found.slot < 0 or found.slot >= d.capacity
           or type(found.species) ~= "number" or found.species <= 0
           or found.is_egg == 1 or found.is_egg == true or found.is_bad_egg == 1 or found.is_bad_egg == true or found.checksum_ok == false
           or not native:trade_eligible(found) then return nil end
        return found, party
    end
    local function visit()
        if not native.trade_capable or not native:trade_capable() or not d.eligible() then return nil end
        local v = native:trade_visit()
        if not v or v.id == nil or v.accepted ~= true or v.pre_saved ~= true or v.apply_open ~= true then return nil end
        return v
    end
    local function unchanged(t)
        if retired[t.token] then return end
        if t.prepare_pending then emit("apply_ready", {token=t.token, ok=false}) end
        local result = {token=t.token, slot=t.slot, new_key=t.old_key, new_species=0}
        retired[t.token] = result
        emit("trade_done", result)
        if active == t then active = nil end
        if prepared == t then prepared = nil end
        if native.withdraw_trade then native:withdraw_trade(t.token) end
        if d.completed then d.completed(t, false) end
    end
    local function uncertain(t, why)
        if active ~= t then return end
        t.phase, t.why = "uncertain", why
        uncertain_records[t.token] = t
        if not t.declared then
            t.declared = true
            emit("trade_done", {token=t.token, uncertain=true, after_reset=true})
        end
    end
    local function result(t)
        if not (t.commit_entered and t.scene_done and t.save_success and t.final_result == "committed") then
            return uncertain(t, "native completion lacks commit/scene/save witnesses")
        end
        local party, got, old = d.party(), nil, false
        if type(party) ~= "table" or #party ~= t.party_count then
            return uncertain(t, "final party unreadable or count changed")
        end
        for _, mon in ipairs(party) do
            local k = d.key(mon)
            if k == t.partner_key then
                if got then return uncertain(t, "received identity duplicated") end
                got = mon
            end
            if k == t.old_key then old = true end
        end
        if not got or old or got.is_egg == 1 or got.is_bad_egg == 1 or got.checksum_ok == false then
            return uncertain(t, "saved result does not match received identity")
        end
        local fields = {token=t.token, slot=got.slot, new_key=d.key(got), new_species=got.species}
        retired[t.token], active = fields, nil
        emit("trade_done", fields)
        if d.completed then d.completed(t, true, party, got) end
    end
    local post_scene
    post_scene = function(t)
        if active ~= t then return end
        local mon = locate(t.old_key)
        if not mon then return unchanged(t) end
        t.slot, t.phase = mon.slot, "scene"
        t.scene_attempt = (t.scene_attempt or 0) + 1
        local attempt = t.scene_attempt
        local function progress(witness)
            if active ~= t or t.scene_attempt ~= attempt or t.phase ~= "scene" or not t.scene_job or not t.scene_job.posted then return end
            if type(witness) ~= "table" then return end
            if witness.commit_entered == true then t.commit_entered = true end
            if witness.scene_done == true then
                if not t.commit_entered then return uncertain(t, "scene milestone before commit") end
                t.scene_done = true
            end
            if witness.save_success == true then
                if not t.scene_done then return uncertain(t, "save milestone before scene") end
                t.save_success = true
            end
            if witness.final_result ~= nil then t.final_result = witness.final_result end
        end
        t.scene_job = native:transfer("scene", {slot=t.slot, token=t.token, old_key=t.old_key, visit=t.visit},
            function(why)
                if active ~= t or t.scene_attempt ~= attempt or t.phase ~= "scene" then return end
                if why == "guard:moved" then return post_scene(t) end
                if why then
                    if may_commit(t) then return uncertain(t, why) end
                    return unchanged(t)
                end
                result(t)
            end,
            function()
                if active ~= t or t.scene_attempt ~= attempt or t.phase ~= "scene" then return false, "guard:stale" end
                local v, current = visit(), locate(t.old_key)
                if not v or v.id ~= t.visit or not current or d.frame() > t.deadline then return false, "guard:lost" end
                if current.slot ~= t.slot then return false, "guard:moved" end
                return true
            end, progress)
        if not t.scene_job and active == t and t.phase == "scene" then unchanged(t) end
    end
    function self:prepare(cmd)
        if not token(cmd.token) then return end
        if not self:capable() or not d.eligible() then
            emit("apply_ready", {token=cmd.token, ok=false}); flush(); return
        end
        if prepared and prepared.token == cmd.token then
            local t = prepared
            if t.phase == "preparing" and t.old_key == cmd.old_key then return end
            local v = visit()
            local ok = t.old_key == cmd.old_key and v ~= nil and v.id == t.visit
                       and locate(t.old_key) ~= nil and t.deadline ~= nil and d.frame() <= t.deadline
            if not ok then unchanged(t) end
            emit("apply_ready", {token=cmd.token, ok=ok}); flush(); return
        end
        if native.prepare_trade then
            local mon = locate(cmd.old_key)
            if not mon or active or prepared or retired[cmd.token] or not native.trade_authorized
               or not native:trade_authorized(cmd.token, cmd.old_key) then
                emit("apply_ready", {token=cmd.token, ok=false}); flush(); return
            end
            local t = {token=cmd.token, old_key=cmd.old_key, slot=mon.slot, phase="preparing", prepare_pending=true}
            prepared = t
            t.prepare_job = native:prepare_trade({token=t.token, slot=t.slot, old_key=t.old_key}, function(why, w)
                if prepared ~= t or t.phase ~= "preparing" then return end
                if why or type(w) ~= "table" or w.accepted ~= true or w.pre_saved ~= true or w.apply_open ~= true
                   or w.id == nil or w.old_key ~= t.old_key then
                    unchanged(t); flush(); return
                end
                t.phase, t.prepare_pending, t.visit = "prepared", nil, w.id
                t.deadline = d.frame() + (d.prepare_frames or 600)
                emit("apply_ready", {token=t.token, ok=true}); flush()
            end, function()
                local current = locate(t.old_key)
                if prepared ~= t or t.phase ~= "preparing" or not d.eligible() or not current
                   or current.slot ~= t.slot then return false, "guard:stale" end
                return true
            end)
            if not t.prepare_job and prepared == t then unchanged(t); flush() end
            return
        end
        local v, mon = visit(), locate(cmd.old_key)
        local ok = v ~= nil and mon ~= nil and active == nil and retired[cmd.token] == nil
                   and (prepared == nil or prepared.token == cmd.token)
        if ok then
            prepared = {token=cmd.token, old_key=cmd.old_key, slot=mon.slot, visit=v.id, phase="prepared",
                        deadline=d.frame() + (d.prepare_frames or 600)}
        end
        emit("apply_ready", {token=cmd.token, ok=ok})
        flush()
    end
    function self:withdraw(cmd)
        if prepared and prepared.token == cmd.token then
            local t = prepared
            t.phase = "withdrawing"
            if t.prepare_job then native:cancel(t.prepare_job) end
            unchanged(t)
        end
        local t = active
        if t and t.token == cmd.token then
            if may_commit(t) then
                uncertain(t, "withdrawal after possible commit")
            else
                t.phase = "withdrawing"
                if t.stage_job then native:cancel(t.stage_job) end
                if t.scene_job then native:cancel(t.scene_job) end
                unchanged(t)
            end
        end
        flush()
    end
    function self:reset(reloaded)
        if prepared then
            local t = prepared
            t.phase = "withdrawing"
            if t.prepare_job then native:cancel(t.prepare_job) end
            unchanged(t)
        end
        local t = active
        if not t then return end
        if may_commit(t) or t.phase == "uncertain" then
            if not t.reload_seen then
                t.declared = false
                uncertain(t, "reset after possible commit")
                t.reload_seen = reloaded ~= false
            end
            if t.reload_seen then
                retired[t.token] = {token=t.token, uncertain=true, after_reset=true}
                active = nil -- hardware lease ended; token/report remains retired/owed
            end
        else
            t.phase = "withdrawing"
            if t.stage_job then native:cancel(t.stage_job) end
            if t.scene_job then native:cancel(t.scene_job) end
            unchanged(t)
        end
    end
    function self:apply(cmd)
        local t = prepared
        if retired[cmd.token] then emit("trade_done", retired[cmd.token]); flush(); return end
        if not t or t.phase ~= "prepared" or active or t.token ~= cmd.token or t.old_key ~= cmd.old_key then return end
        local v = visit()
        local mon, party = locate(t.old_key)
        if not v or v.id ~= t.visit or not mon or d.frame() > t.deadline then unchanged(t); flush(); return end
        if type(cmd.blob_hex) ~= "string" or #cmd.blob_hex ~= 2*d.mon_size or cmd.blob_hex:find("[^%x]") then
            unchanged(t); flush(); return
        end
        local function word(off)
            local n = 0
            for i=3,0,-1 do n = n*256 + tonumber(cmd.blob_hex:sub(2*(off+i)+1,2*(off+i)+2),16) end
            return n
        end
        t.partner_key = string.format("%08X:%08X", word(0), word(4))
        for _, m in ipairs(party) do
            if d.key(m) == t.partner_key then unchanged(t); flush(); return end
        end
        t.party_count = #party
        t.slot, t.blob_hex, t.phase = mon.slot, cmd.blob_hex, "wait"
        prepared, active = nil, t
    end
    function self:tick()
        flush()
        if prepared and prepared.deadline and d.frame() > prepared.deadline then unchanged(prepared); flush() end
        local t = active
        if not t or t.phase ~= "wait" or not d.eligible() or not d.clear() then return end
        if d.frame() > t.deadline then unchanged(t); flush(); return end
        t.phase = "stage"
        t.stage_job = native:transfer("enemy", {blobs_hex={t.blob_hex}}, function(why)
            if active ~= t or t.phase ~= "stage" then return end
            if why then unchanged(t) else post_scene(t) end
        end, function()
            local v = visit()
            if active ~= t or not v or v.id ~= t.visit or not locate(t.old_key) or d.frame() > t.deadline then return false, "guard:stale" end
            return true
        end)
        if not t.stage_job and active == t then unchanged(t) end
    end
    function self:hide_party() return active ~= nil and active.phase == "uncertain" and not active.reload_seen end
    function self:reloaded(t) return uncertain_records[t] and uncertain_records[t].reload_seen == true end
    function self:uncertainties() return uncertain_records end
    function self:capable() return native.trade_capable and native:trade_capable() == true end
    function self:state()
        if active then
            active.posted = (active.stage_job and active.stage_job.posted == true)
                            or (active.scene_job and active.scene_job.posted == true) or false
            active.possibly_posted = active.scene_job and active.scene_job.publish_attempted == true or false
        end
        return active, prepared
    end
    return self
end
return T
