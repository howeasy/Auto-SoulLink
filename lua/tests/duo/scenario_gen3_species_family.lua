-- SYNTH evolved lead / server link staging; native first encounter and RUN.
-- A non-family first foe is unobserved, never a clause PASS; the host retries.
return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local key = ctx.linked()
    if ctx.player == "a" then
        local mon = key and ctx.find(key)
        if not mon or mon.slot ~= 0 then return false, "family lead not staged" end
        local members = ctx.go_value("FAMILY_LINKS")
        if not members or #members ~= 2 or members[1].player ~= "a" or members[1].key ~= key
           or members[1].species ~= mon.species or members[2].player ~= "b" then
            return false, "family linked records missing or mismatched"
        end
        local cursor = ctx.rx_count()
        if not ctx.hunt("family") then return false, "no family encounter" end
        if not ctx.wild_ready("family") then return false, "family battle never reached its action menu" end
        local species = ctx.enemy_species()
        local other = species and ctx.D.clause_facts[tostring(species)]
        if not other then return false, "family encounter facts missing" end
        local matched
        for _, member in ipairs(members) do
            local f = ctx.D.clause_facts[tostring(member.species)]
            if not f then return false, "family linked facts missing" end
            if not matched and f.family == other.family then matched = member end
        end
        local related = matched ~= nil
        local owner = matched or members[1]
        local x, y = ctx.G.pos(ctx.cp)
        ctx.jlog("FAMILY_ENCOUNTER", {key=owner.key, owned=owner.species, player=owner.player,
                                     species=species, related=related,
                                     map=ctx.play.map(ctx.cp), x=x, y=y})
        local ok, why = ctx.run_away("family")
        if not ok then return false, why end
        if related then
            local r = ctx.wait_until(function() return ctx.rx_after(cursor, function(v)
                return v.cmd == "gui_prompt" and type(v.text) == "string" and v.text:match("^Dupes clause: .+ %-%- reroll!$")
            end) end, 30, "family reroll prompt")
            if not r then return false, "no native family reroll prompt" end
            ctx.jlog("CLAUSE_REROLL", {species=species, prompt=r.text})
        end
        ctx.log("FAMILY_READY " .. key)
    end
    if not ctx.wait_go("SAVE") then return false, "no family SAVE release" end
    return ctx.save("family")
end
