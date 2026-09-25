-- scenario_gen3_whiteout.lua — whiteout_gen3: one whiteout, one rebuild from both PCs.
--
-- The runner links both slot-1 mons. A (battle fixture) deposits its half at the Viridian PC by
-- hand; the server mirrors box_mon to B (town fixture), whose client deposits it. Both report
-- DEPOSITED_FOR_REBUILD and the runner writes BOTH_BOXED only once the SERVER's own party_keys
-- drop both keys (assert_whiteout_both_boxed, shared with Gen 1): the rebuild picks only pairs
-- boxed on both sides (server/state.py _plan_rebuild). A then walks back to the Route 1 grass
-- with its lone starter and chooses only a no-damage move until it faints -> whiteout. The
-- client sends `whiteout`; the server answers rebuild_start + party_mon to A and party_mon to B
-- (server/state.py _queue_rebuild_commands); both clients withdraw at their checkpoints, A gets
-- rebuild_done, and both save. A whiteout during the walk itself counts: it is the same event.
--
-- A also carries G4 item 2a's receipt (docs/gen3/G4_request_draft.md; owner ruling 2026-09-23,
-- 5ecfae3b): it lands in the Viridian Center 1F, logs CENTER_STATE there (the Union Room
-- background set must be live, or the receipt proves nothing), and the rebuild's first overworld
-- write must land in that Center at the landing tile (WRITE_IN_CENTER), before any movement.
-- After the save, the negative control: A talks to the nurse and parks in her script; the runner
-- queues box_mon for the linked key, which must stay HELD (named clause, zero writes, the mon
-- still in the party) while the script is live (CONTROL_REFUSED).
local fmt = string.format

local function at(ctx, dest)
    local g, n = ctx.G.map(ctx.cp)
    local x, y = ctx.G.pos(ctx.cp)
    return g == dest.group and n == dest.num and x == dest.x and y == dest.y
end

local function a_side(ctx, linked)
    ctx.walk_to_pc("whiteout a")
    local gone, why = ctx.pc_deposit("whiteout a deposit")
    if gone ~= linked then return false, "the deposit moved " .. tostring(gone or why) .. ", not " .. linked end
    if not ctx.observe_boxed(linked) then return false, linked .. " was never read back boxed after the deposit" end
    ctx.log("DEPOSITED_FOR_REBUILD " .. linked)
    if not ctx.wait_go("BOTH_BOXED", 1800) then return false, "the runner never wrote BOTH_BOXED" end
    -- (1)+(2) armed BEFORE the walk: the lone starter can faint in an incidental battle ON the
    -- walk, and playlib then fights, whites out, mashes through the heal script (the rebuild
    -- lands) and only then raises -- live gen3_lgfr r6: the three rebuild writes at frame 16729,
    -- the whiteout raised at 16793, the hook armed after both. Both watchers run every frame
    -- whoever drives it. The landing sample needs the whiteout already SENT (the walk out of the
    -- Center crosses (7,4) too), which is also strictly before the write: the rebuild's
    -- party_mon only answers that whiteout.
    local dest = ctx.SP.whiteout_destination(ctx.cp)    -- lastHealLocation -> Center 5.4 (7,4)
    if not dest then return false, "no whiteout destination" end
    local function overworld_writes()
        local n = 0
        for _, w in ipairs(ctx.write_lines()) do if w.reason == "overworld" then n = n + 1 end end
        return n
    end
    local ow0 = overworld_writes()
    local land                                          -- { line, missing, snap, ow }
    ctx.watch(function()
        if ctx.sent("whiteout") == 0 or not at(ctx, dest) then return false end
        local line, missing, snap = ctx.center_state()
        if #missing > 0 then return false end
        land = { line = line, missing = missing, snap = snap, ow = overworld_writes() }
        return true
    end)
    local wline, wmissing, wat
    ctx.on_write("overworld", function() wline, wmissing, wat = ctx.center_state() end)
    local ok, err = ctx.try(function()
        ctx.walk_pc_to_grass("whiteout a")
        if not ctx.hunt("whiteout a") then error("no wild encounter", 0) end
        local lead = (ctx.party() or {})[1]
        if not lead then error("party unreadable in battle", 0) end
        local fainted, lwhy = ctx.lose_active(lead.key, "whiteout a")
        if not fainted then error("the lone starter did not faint: " .. tostring(lwhy), 0) end
    end)
    if not ok and not (type(err) == "table" and err.whiteout) then
        return false, "the whiteout run: " .. tostring(err)
    end
    if not ctx.mash_until(function() return ctx.sent("whiteout") > 0 end, 180, "A") then
        return false, "the client never sent whiteout"
    end
    ctx.wait_until(function() return land end, 30, "the Center landing with the Union Room background set")
    if not land then
        local _, missing = ctx.center_state()
        return false, fmt("the Union Room background set is absent at the Center landing %d.%d (%d,%d) "
                          .. "after the whiteout (missing now: %s): this receipt would not prove the "
                          .. "widened allow-list", dest.group, dest.num, dest.x, dest.y,
                          table.concat(missing, ","))
    end
    ctx.log(fmt("CENTER_STATE %s overworld_writes_before=%d", land.line, land.ow - ow0))
    for _, b in ipairs(land.snap.bad) do
        if b:find("^pointer:") then return false, "CENTER_STATE: insane " .. b end
    end
    if land.ow ~= ow0 then return false, "a write landed before CENTER_STATE was taken" end
    ctx.play.wait_scene_settled(ctx.cp, 6000)          -- the heal-location landing and its text
    ctx.log("WHITED_OUT at " .. ctx.play.where(ctx.cp))
    if not ctx.wait_received("party_mon", linked, 900) then return false, "no rebuild party_mon" end
    if not ctx.wait_sent("sync_retrieve_done", linked, 600) then return false, "the rebuild withdraw was not acknowledged" end
    local ack_line = ctx.center_state()
    local mon, base = ctx.find(linked), ctx.party_base()
    -- the KEYED mutation: boxes.lua withdraw writes the whole party record at party_base +
    -- slot * 100 (Reads.PARTY_MON_SIZE) in that frame; the slot is where the key reads back now
    local target = mon and base and base + mon.slot * 100
    local keyed
    for _, w in ipairs(ctx.write_lines()) do
        if wat and w.reason == "overworld" and w.frame == wat.frame and w.address == target and w.len == 100 then
            keyed = w
        end
    end
    ctx.log(fmt("WRITE_IN_CENTER %s | keyed %s slot=%s record=%s | ack %s", tostring(wline), linked,
                mon and tostring(mon.slot) or "absent",
                keyed and fmt("0x%08X+%d@%d", keyed.address, keyed.len, keyed.frame) or "none", ack_line))
    if #ctx.write_hook_errors() > 0 then return false, "the write-frame read failed: " .. ctx.write_hook_errors()[1] end
    if not wline then return false, "sync_retrieve_done sent, but no overworld write line was seen" end
    if not (wat.group == dest.group and wat.num == dest.num and wat.x == dest.x and wat.y == dest.y) then
        return false, "the rebuild write landed outside the Center landing tile"
    end
    if #wmissing > 0 then return false, "the Union Room set was gone when the write landed" end
    if #wat.bad > 0 then return false, "the write landed off the checkpoint: " .. table.concat(wat.bad, ",") end
    for name, v in pairs(land.snap.ptrs) do
        if wat.ptrs[name] ~= v then return false, "pointer moved between the landing and the write: " .. name end
    end
    if not at(ctx, dest) then return false, "the player moved before the ACK" end
    if not mon then return false, linked .. " is not in the party at the ACK" end
    if not keyed then return false, "no write of " .. linked .. "'s party record in the write frame" end
    if not ctx.wait_received("rebuild_done", nil, 300) then return false, "no rebuild_done" end
    if not ctx.observe_returned(linked) then return false, linked .. " was never read back in the party (and out of every box)" end
    return true, dest
end

--- (4) The negative control, after the save: pret ViridianCity_PokemonCenter_1F/map.json puts
--- the nurse at (7,2) across the counter (7,3) (MB_COUNTER 0x80: tools/gba_map.py --map 5.4
--- --find-behaviour 0x80), and CB2_WhiteOut faces the player north, so A at the landing talks
--- to her through it (field_control_avatar.c:412-415). On FR/LG her script waits on its first
--- message: it stays live, and the runner's box_mon probe must stay held for as long as it is
--- (ctx.hold_probe: fresh keyed RX, the exact queued entry, zero attempted bytes, unchanged
--- party and PC bytes, a failing clause named).
---
--- RR's nurse is a different script (her ObjectEvent.script, local_id=1 on map 5.4, is
--- 0x0904c64b in patch/build/slink_RR.gba, not FR's shared EventScript_PkmnCenterNurse):
--- decoding it against gScriptCmdTable (data/gen3/pret/pokefirered.sym) gives lock, faceplayer,
--- special, compare/call_if into a branch of playse/fadescreen/applymovement/waitmovement,
--- copyvar, release, end -- a silent quick-heal cutscene with NO message/waitmessage/
--- multichoice/waitbuttonpress anywhere in it (a ROM fact, not a screenshot). It always finishes
--- on its own a few hundred frames after the tap (confirmed live, G5-RR-NURSE: script_context_
--- status returns idle at frame 285 of the hold with nothing else pressed), so it is never a
--- genuine refusing state on RR. Open the START menu instead: it swings gMain.callback2 off
--- CB2_Overworld (the pack's own `callback2` predicate, already pinned for every title) for as
--- long as it stays up, with no RR-specific symbol pin needed.
local function nurse_control(ctx, linked, dest)
    if not at(ctx, dest) then return false, "control: not at the Center landing" end
    if ctx.rr then
        local G, cp = ctx.G, ctx.cp
        local function live() return not G.pred_ok(cp, "callback2") end
        local function field_free() return G.pred_ok(cp, "callback2") and G.pred_ok(cp, "field_controls_locked") end
        if not ctx.wait_until(field_free, 10, "the field free before START") then
            return false, "control: the field was never free to open START"
        end
        G.tap("Start", 3, 0)
        if not ctx.wait_until(live, 10, "the START menu") then
            return false, "control: the START menu never opened"
        end
        ctx.frames(60)
        local clause, why = ctx.hold_probe("nurse", "box_mon", linked, live, 600)
        if not clause then return false, "control: " .. tostring(why) end
        G.tap("B", 3, 13)
        if not ctx.wait_until(field_free, 10, "the field free after B closed START") then
            return false, "control: the field never freed after closing START"
        end
        return true
    end
    ctx.G.tap("A", 3, 13)
    local function live() return not ctx.G.pred_ok(ctx.cp, "script_context_status") end
    if not ctx.wait_until(live, 10, "the nurse's script") then
        return false, "control: the nurse's script never started"
    end
    ctx.frames(60)
    local clause, why = ctx.hold_probe("nurse", "box_mon", linked, live, 600)
    if not clause then return false, "control: " .. tostring(why) end
    return true
end

local function b_side(ctx, linked)
    if not ctx.wait_received("box_mon", linked, 1800) then return false, "no mirrored box_mon" end
    if not ctx.wait_sent("stats_cache", linked, 300) then return false, "the mirrored deposit was not acknowledged" end
    -- the ACK is the client's word; the cartridge must show it (Codex C4-6b finding 2)
    if not ctx.observe_boxed(linked) then return false, "stats_cache sent but " .. linked .. " was never read back boxed" end
    ctx.log("MIRROR_DEPOSITED " .. linked)
    ctx.log("DEPOSITED_FOR_REBUILD " .. linked)
    if not ctx.wait_go("BOTH_BOXED", 1800) then return false, "the runner never wrote BOTH_BOXED" end
    if not ctx.wait_received("party_mon", linked, 1800) then return false, "no rebuild party_mon" end
    if not ctx.wait_sent("sync_retrieve_done", linked, 600) then return false, "the rebuild withdraw was not acknowledged" end
    if not ctx.observe_returned(linked) then return false, "sync_retrieve_done sent but " .. linked .. " was never read back in the party" end
    ctx.log("MIRROR_WITHDRAWN " .. linked)
    return true
end

return function(ctx)
    if not ctx.wait_go() then return false, "no go-file" end
    local linked = ctx.linked()
    local mon = linked and ctx.find(linked)
    if not mon or mon.slot ~= 1 then return false, "the LINKED key must be party slot 1" end
    local ok, why
    if ctx.player == "a" then ok, why = a_side(ctx, linked) else ok, why = b_side(ctx, linked) end
    if not ok then return false, why end
    local dest = ctx.player == "a" and why or nil
    ctx.frames(60)
    ok, why = ctx.save("whiteout")
    if not ok then return false, why end
    if dest then
        ok, why = nurse_control(ctx, linked, dest)
        if not ok then return false, why end
    end
    return true, "pair " .. linked .. " rebuilt after the whiteout" .. (dest and "; the write landed in the Center" or "")
end
