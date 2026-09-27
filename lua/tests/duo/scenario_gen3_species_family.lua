-- SYNTH evolved lead / server link staging; native first encounter and RUN.
-- A non-family first foe is unobserved, never a clause PASS; the host retries.
return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local key = ctx.linked()
    if ctx.player == "a" then
        local mon = key and ctx.find(key)
        if not mon or mon.slot ~= 0 then return false, "family lead not staged" end
        local f = ctx.D.clause_facts[tostring(mon.species)]
        local cursor = ctx.rx_count()
        if not ctx.hunt("family") then return false, "no family encounter" end
        if not ctx.wild_ready("family") then return false, "family battle never reached its action menu" end
        local species = ctx.enemy_species()
        local other = species and ctx.D.clause_facts[tostring(species)]
        if not f or not other then return false, "family facts missing" end
        local related = f.family == other.family
        ctx.jlog("FAMILY_ENCOUNTER", {key=key, owned=mon.species, species=species, related=related})
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
