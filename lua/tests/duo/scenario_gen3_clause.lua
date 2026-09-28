-- Accepted Gen 1 ordered pending/reroll and Gen 2 gender/type carrier.
-- No writes: hunt/RUN/BAG/SAVE are ordinary input. Facts come from the booted ROM.
local function fact(ctx, species)
    return (ctx.D.clause_facts or {})[tostring(species)]
end
local function prompt(ctx, after)
    return ctx.rx_after(after, function(r)
        return r.cmd == "gui_prompt" and type(r.text) == "string"
            and r.text:match("^Dupes clause: .+ %-%- reroll!$") ~= nil
    end)
end
return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local kind, pending = ctx.D.rule_kind
    if ctx.player == "b" then
        pending = ctx.wait_until(function() return ctx.go_value("A_PENDING") or (ctx.partner_done() and "gone") end, 1800, "A_PENDING")
        if type(pending) ~= "table" then return false, "runner never released B (A_PENDING)" end
        ctx.jlog("A_PENDING", pending)
    end
    local key, why, rerolls = nil, nil, 0
    for n = 1, ((kind == "species" or kind == "type") and ctx.player == "b" and 8 or 1) do
        local cursor = ctx.rx_count()
        if not ctx.hunt("clause") then return false, "hunt ended no wild encounter" end
        if not ctx.wild_ready("clause") then return false, "wild battle never reached its action menu" end
        local species, error = ctx.enemy_species()
        local f = species and fact(ctx, species)
        if not f then return false, "unproven wild species: " .. tostring(error or species) end
        local other = pending and fact(ctx, pending.species_id)
        if pending and not other then return false, "unproven pending species" end
        local dupe = kind == "species" and other and f.family == other.family or false
        local type_overlap = false
        if kind == "type" and pending then
            if type(f.types) ~= "table" or type(other.types) ~= "table" then
                return false, "unproven wild/pending types"
            end
            for _, a in ipairs(f.types) do
                for _, b in ipairs(other.types) do if a == b then type_overlap = true end end
            end
        end
        local encounter = {n=n, species=species, dupe=dupe}
        if kind == "type" and pending then encounter.type_overlap = type_overlap end
        ctx.jlog("CLAUSE_ENCOUNTER", encounter)
        if dupe then
            local fled, flee_why = ctx.run_away("duplicate")
            if not fled then return false, "duplicate RUN: " .. tostring(flee_why) end
            local received = ctx.wait_until(function() return prompt(ctx, cursor) end, 30, "duplication prompt")
            if not received then return false, "no dupes-clause prompt after RUN" end
            ctx.jlog("CLAUSE_REROLL", {n=n, species=species, prompt=received.text})
            rerolls = rerolls + 1
        elseif kind == "type" and ctx.player == "b" and not type_overlap then
            local fled, flee_why = ctx.run_away("type nonoverlap")
            if not fled then return false, "type nonoverlap RUN: " .. tostring(flee_why) end
            ctx.jlog("CLAUSE_TYPE_RUN", {n=n, species=species})
        else
            key, why = ctx.catch("clause", true)
            if not key then return false, "hunt ended " .. tostring(why) end
            break
        end
    end
    if not key then
        if kind == "type" then return false, "RNG: no type overlap in 8 natural encounters" end
        return false, "RNG: the species hunt met only duplicates within its battle budget"
    end
    ctx.log("CAUGHT " .. key)
    local cap = ctx.last_sent("capture")
    if not cap or cap.key ~= key then return false, "native capture has no production TX" end
    if ctx.player == "a" then ctx.jlog("PENDING_CAPTURE", cap) end
    local verdict = ctx.wait_until(function()
        if ctx.received("force_faint", key) > 0 then return "rejected" end
        if ctx.rx_after(0, function(r) return r.cmd == "play_sound" and r.sound == 22 end) then return "accepted" end
        if ctx.rx_after(0, function(r) return r.cmd == "msgbox" and type(r.text) == "string" and r.text:match(" linked!$") end) then return "linked" end
        if ctx.partner_done() then return "partner_gone" end
    end, 1800, "the clause disposition")
    if not verdict or verdict == "partner_gone" then return false, "no " .. kind .. "-clause verdict (partner-gone)" end
    if verdict == "rejected" then
        if not ctx.wait_sent("memorialize_done", key, 300) then return false, "rejection has no memorialize_done" end
        if not ctx.hp0(key) then return false, "rejection has no HP-0 witness" end
        if not ctx.observe_boxed(key) then return false, "rejection not read back boxed" end
    elseif verdict == "accepted" then
        if not ctx.observe_boxed(key) then return false, "pending catch not read back quarantined" end
    else
        if ctx.received("box_mon", key) > 0 and not ctx.wait_sent("sync_retrieve_done", key, 300) then
            return false, "linked catch not retrieved"
        end
        if not ctx.observe_returned(key) then return false, "linked catch not read back in party" end
    end
    ctx.jlog("CLAUSE_VERDICT", {key=key, verdict=verdict, rerolls=rerolls})
    ctx.log("CLAUSE_READY " .. key)
    if not ctx.wait_go("SAVE") then return false, "no final SAVE release" end
    return ctx.save("clause")
end
