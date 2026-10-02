-- SYNTH location/near-hatch egg only. Gift receipt and hatch use ordinary inputs.
-- Facts are validated against the booted title's own ROM before launch.
return function(ctx)
    local f, kind = ctx.D.acquisition_facts, ctx.D.acquisition_kind
    if not f or (kind ~= "gift" and kind ~= "hatch" and kind ~= "gift_box" and kind ~= "egg_receive") then
        return false, "unproven gift/egg facts"
    end
    local function gift_flag()
        if f.flag_address then
            return (memory.read_u8(f.flag_address, "System Bus") & f.flag_mask) ~= 0
        end
        return ctx.game_flag(f.flag)
    end
    if not ctx.wait_go() then return false, "no go-file" end
    local before, old = ctx.party(), {}
    if not before then return false, "party unreadable before acquisition" end
    for _, mon in ipairs(before) do old[mon.key] = true end
    local egg = kind == "hatch" and before[2] or nil
    if kind == "hatch" and (not egg or egg.is_egg ~= 1 or egg.friendship ~= 0) then
        return false, "fixture lacks the disclosed near-hatch egg"
    end
    if kind == "gift" and (#before >= 6 or gift_flag() ~= false) then
        return false, "gift already received or no party slot"
    end
    if (kind == "egg_receive" and #before >= 6) or (kind == "gift_box" and #before ~= 6) then
        return false, "wrong party space for acquisition case"
    end
    local location = ctx.reader.read_location()
    local x, y = ctx.G.pos(ctx.cp)
    if not location or location.map_group ~= f.group or location.map_num ~= f.num
       or x ~= (egg and f.hatch_x or f.x) or y ~= (egg and f.hatch_y or f.y) then
        return false, "wrong native gift/egg setup tile"
    end
    ctx.jlog("ACQUISITION_BEFORE", {captures=ctx.sent("capture"), balls=ctx.balls(),
                                  count=#before, egg=egg and egg.is_egg or 0})
    if f.probes and event and event.on_bus_exec then
        for _, probe in ipairs(f.probes) do
            local id = event.on_bus_exec(function(address)
                ctx.jlog("ACQUISITION_PROBE", {name=probe.name,address=address,
                    frame=emu.framecount(),r0=emu.getregister("R0"),r1=emu.getregister("R1"),
                    r15=emu.getregister("R15"),sp=emu.getregister("R13")})
            end, probe.address, "exp-acquisition-"..probe.name, "System Bus")
            assert(id, "native acquisition diagnostic hook refused")
        end
    end
    if ctx.sent("capture") ~= 0 then return false, "egg/fixture was captured before native acquisition" end
    local signals, drain = ctx.session.signals, ctx.session.signals.drain
    signals.drain = function(self)
        local out = drain(self)
        for _, s in ipairs(out) do
            if s.kind == "mon_given" or s.kind == "hatch" then
                ctx.jlog("ACQUISITION_SIGNAL", {kind=s.kind, address=s.address, frame=s.frame,
                    callback_address=s.callback_address,raw_r15=s.raw_r15})
            end
        end
        return out
    end
    local mon, steps, scene = nil, 0, false
    if kind ~= "hatch" then
        if not ctx.face(f.face) then return false, "cannot face native gift object" end
        -- YES to the offer, then B as soon as the party grows: NO to nickname.
        if not ctx.mash_until(function()
            local party = ctx.party()
            return party and (kind == "gift_box" and gift_flag() == true or #party == #before + 1)
        end, 120, "A") then return false, "native gift never joined party" end
        if not ctx.mash_until(function()
            return gift_flag() == true and ctx.on_field() and ctx.player_idle()
                and ctx.G.pred_ok(ctx.cp, "script_context_status")
                and ctx.G.pred_ok(ctx.cp, "field_controls_locked")
        end, 120, "B") then return false, "native gift script did not finish" end
        for _, m in ipairs(ctx.party() or {}) do if not old[m.key] then mon = m end end
        if kind == "gift_box" then
            if not ctx.wait_until(function() return ctx.sent("capture") == 1 end, 60, "boxed gift capture") then
                return false, "boxed gift capture absent"
            end
            local cap = ctx.last_sent("capture")
            local at = ctx.locate(cap.key)
            if not at or at.party ~= false or not at.box then return false, "gift is not uniquely boxed" end
            local box, slot = at.box:match("^(%d+):(%d+)$")
            local mons = box and ctx.reader.read_box(tonumber(box))
            mon = mons and mons[tonumber(slot)+1]
            if mon then mon.key = ctx.reader.key(mon) end
        end
        if not mon or mon.species ~= f.species or (kind ~= "gift_box" and mon.level ~= f.level)
           or mon.is_egg ~= (kind == "egg_receive" and 1 or 0) then
            return false, "native gift record differs from own-title script"
        end
    else
        -- At most one cycle remains; the engine's own step counter is left
        -- untouched. Walk between ROM-checked adjacent interior floor tiles.
        local observed_x, observed_y = x, y
        local p = ctx.cp.predicates.callback2
        local ok = ctx.wait_until(function()
            local callback = memory.read_u32_le(p.address + p.offset, "System Bus") & ~1
            if callback == f.hatch_callback then scene = true end
            local now = ctx.find(egg.key)
            if scene and now and now.is_egg == 0 and ctx.on_field() and ctx.player_idle()
               and ctx.G.pred_ok(ctx.cp, "script_context_status")
               and ctx.G.pred_ok(ctx.cp, "field_controls_locked") then mon = now; return true end
            if ctx.in_battle() then ctx.fail("unexpected battle on indoor hatch walk") end
            if ctx.on_field() and ctx.player_idle() and ctx.G.pred_ok(ctx.cp, "script_context_status")
               and ctx.G.pred_ok(ctx.cp, "field_controls_locked") then
                local px, py = ctx.G.pos(ctx.cp)
                if py ~= f.hatch_y or (px ~= f.hatch_x and px ~= f.hatch_x + 1) then
                    ctx.fail("hatch walk left the proven two-tile corridor")
                end
                if px ~= observed_x or py ~= observed_y then
                    steps = steps + 1; observed_x, observed_y = px, py
                end
                if steps >= 600 then ctx.fail("native hatch cycle exhausted 600 walked steps") end
                ctx.G.tap(px == f.hatch_x and "Right" or "Left", 8, 20)
                local nx, ny = ctx.G.pos(ctx.cp)
                if (nx ~= observed_x or ny ~= observed_y) and ny == f.hatch_y
                   and (nx == f.hatch_x or nx == f.hatch_x + 1) then
                    steps = steps + 1; observed_x, observed_y = nx, ny
                end
            else
                -- B advances field text and declines the hatch nickname prompt.
                ctx.G.tap("B", 3, 13)
            end
        end, 600, "native walking and hatch scene")
        if not ok or not mon then return false, "native hatch never completed" end
        if mon.level ~= f.hatch_level or mon.species ~= egg.species then return false, "wrong native hatchling" end
    end
    if kind == "egg_receive" then
        if ctx.sent("capture") ~= 0 then return false, "unhatched NPC egg was captured" end
        ctx.jlog("ACQUISITION_AFTER", {key=mon.key,balls=ctx.balls(),egg=1,flag=gift_flag()})
        ctx.jlog("EGG_RECEIVED", {key=mon.key,species_id=mon.species,is_egg=true})
        if not ctx.wait_go("SAVE") then return false, "egg receipt save gate missing" end
        return ctx.save(kind)
    end
    if not ctx.wait_until(function() return ctx.sent("capture", mon.key) == 1 end, 60, "production acquisition TX") then
        return false, "native acquisition TX missing or duplicated"
    end
    local cap = ctx.last_sent("capture")
    if ctx.sent("capture") ~= 1 or not cap or cap.key ~= mon.key or cap.gift ~= true or cap.is_egg ~= false then
        return false, "acquisition is not one production non-egg gift capture"
    end
    if cap.area_id ~= (kind == "hatch" and "gift_daycare" or f.area) then return false, "wrong gift namespace" end
    ctx.jlog("ACQUISITION_AFTER", {key=mon.key, balls=ctx.balls(), egg=mon.is_egg,
                                 steps=steps, scene=scene, flag=gift_flag()})
    ctx.jlog("ACQUISITION_READY", cap)
    if not ctx.wait_go("SAVE") then return false, "native gift pair never linked" end
    return ctx.save(kind)
end
