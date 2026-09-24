--[[
  lua/tests/duo/scenario_gen2_whiteout_rebuild.lua -- the gen2_new `whiteout_rebuild` scenario (D-7: the whiteout
  REBUILD). Gen 1 reference: whiteout_new (duo_gen1_main.lua). Owner ruling 2026-09-24 option (c).

  Both halves play the `link` scenario and save it (scenario_gen2_faint.lua S.link_prelude, LINK_SAVE), then:
    A  waits for B's LINK_SAVE, walks to the Cherrygrove #MON CENTER PC and DEPOSITs its linked catch
       (party_to_box; the server mirrors box_mon to B, state.py _handle_party_to_box). A waits for B's
       PARTNER_BOXED (B's half physically boxed), walks back to Route 29 grass, and lets its starter -- now its
       only party mon -- faint: the whiteout (whiteout_before_heal, party [starter] at HP 0). No linked half is in
       a party, so _handle_whiteout retires nothing; it plans the rebuild from the alive boxed pair
       (_alive_pc_mons/_plan_rebuild) and queues party_mon to both halves plus rebuild_start to A; rebuild_done
       follows A's sync_retrieve_done (_maybe_finish_rebuild). A's production client withdraws its half at the
       checkpoint; A saves natively.
    B  idles in the overworld: box_mon (its half boxed, PARTNER_BOXED), then the rebuild's party_mon (its half back
       in the party, REBUILT), then saves natively.
  No death anywhere: no force_faint, memorialize or game_over on either side; the pair stays ALIVE.

  MARKER CONTRACT (duo_gen2_main.lua prints them; JSON after the tag). Everything the `link` scenario prints plus
  LINK_SAVE (scenario_gen2_faint.lua's contract). Added:
    A: ENGINE_PC {kind "party_to_box", key}           the hand deposit
       ENGINE_FAINT {site_id battle_faint, key=<starter>}   the only faint
       ENGINE_WHITEOUT {site_id "whiteout_before_heal", party=[{key=<starter>, hp=0}]}
       RX rebuild_start / RX party_mon key=<key> / RX rebuild_done
    B: RX box_mon key=<key>, PARTNER_BOXED {frame, key, party_count, box_count}, RX party_mon key=<key>
    both: REBUILT {frame, key, slot, hp, party_count, box_count}   the linked half back in the party
          SAVE_WITNESS (newer than LINK_SAVE), RECEIPT {schema "gen2-duo-whiteout-rebuild-v1"}
  TX: exactly one `"event":"whiteout"` (A), none on B; one party_to_box (A), none on B.
--]]
local S = {}
S.RECEIPT_SCHEMA = "gen2-duo-whiteout-rebuild-v1"
S.FAINT_INPUTS = true
S.PC_INPUTS = true
S.FAINT = "lua/tests/duo/scenario_gen2_faint.lua"
S.LINK = "lua/tests/duo/scenario_gen2_link.lua"
S.MAX_BATTLES = 12       -- ponytail: the lone starter may win battles before it falls; raise if a lane needs more
S.SYNC_FRAMES = 36000    -- one mirrored/rebuild command (the partner's walk to the PC included)
S.PARTNER_FRAMES = 54000
S.SITES = {"battle_faint", "whiteout_before_heal", "pc_deposit_begin", "pc_deposit_complete"}
S.JSON_TAGS = {LINK_SAVE=true, ENGINE_PC=true, ENGINE_FAINT=true, ENGINE_WHITEOUT=true, PARTNER_BOXED=true,
               REBUILT=true, SAVE_WITNESS=true, ENGINE_CAPTURE=true, DUO_GEN2=true, CLIENT=true}

local function has(list, value)
    for _, v in ipairs(list or {}) do if v == value then return true end end
    return false
end

function S.run(h)
    local FS = dofile(h.root .. "/" .. S.FAINT)
    local link = dofile(h.root .. "/" .. S.LINK)
    if h.player == "a" then
        for _, site in ipairs(S.SITES) do
            if not has(h.registered, site) then return false, "production signals lack " .. site end
        end
    end
    local key, why = FS.link_prelude(h)
    if not key then return false, why end
    local rx0 = #h.rec.rx   -- the link's own quarantine moves are already in the log
    local function got(cmd)
        for i = rx0 + 1, #h.rec.rx do
            local r = h.rec.rx[i]
            if r.cmd == cmd and (r.key == key or r.key == nil) then return true end
        end
        return false
    end
    local function state()
        local slot, mon = h.slot_of(key)
        return {frame=h.frame(), key=key, slot=slot, hp=mon and mon.hp, party_count=h.sym("wPartyCount")[1],
                box_count=h.box_count()}
    end
    local function idle() return #(h.client.deferred or {}) == 0 end
    if h.player == "b" then
        if not h.wait(function() return got("box_mon") and idle() and h.slot_of(key) == nil end, S.PARTNER_FRAMES) then
            return false, "the mirrored box_mon never boxed " .. key
        end
        h.jlog("PARTNER_BOXED", state())
    else
        if not FS.await_partner_link(h) then return false, "B never printed LINK_SAVE" end
        local slot = h.slot_of(key)
        if slot ~= 1 or h.sym("wPartyCount")[1] ~= 2 then return false, "A's party is not [starter, linked catch]" end
        local ok, pc_why = h.pc({{op="deposit", slot=slot}})
        if not ok then return false, "PC deposit: " .. tostring(pc_why) end
        if not h.wait(function() return h.partner_has("PARTNER_BOXED") end, S.PARTNER_FRAMES) then
            return false, "B never printed PARTNER_BOXED"
        end
        local grass, grass_why = h.to_grass()
        if not grass then return false, "back to the grass: " .. tostring(grass_why) end
        local starter = 0
        local starter_key
        for _, line in ipairs(h.lines) do
            local s, k = tostring(line):match("^MYKEY (%d+) (%S+)$")
            if s and tonumber(s) == starter then starter_key = k end
        end
        if starter_key == nil or starter_key == key then return false, "the starter's key is unknown" end
        local fought, fight_why = h.sacrifice({target=starter, max_battles=S.MAX_BATTLES,
            fainted=function() return h.rec.faint_keys[starter_key] ~= nil and h.rec.whiteout ~= nil end})
        if not fought then return false, "starter faint route failed: " .. tostring(fight_why) end
        if not h.wait(function() return got("rebuild_start") end, S.SYNC_FRAMES) then return false, "no rebuild_start" end
    end
    if not h.wait(function()
        return got("party_mon") and idle() and h.slot_of(key) ~= nil and (h.player == "b" or got("rebuild_done"))
    end, S.SYNC_FRAMES) then return false, "the rebuild never brought " .. key .. " back" end
    h.jlog("REBUILT", state())
    local saved, save_why = h.save()
    if not saved then return false, "final save failed: " .. tostring(save_why) end
    local witnessed, witness_why = h.witness()
    if not witnessed then return false, "save witness: " .. tostring(witness_why) end
    h.frames(FS.SETTLE_FRAMES)
    local problems, receipt = S.verdict(h.lines, h.json, link.verdict)
    if #problems > 0 then return false, table.concat(problems, "; ") end
    h.jlog("RECEIPT", receipt)
    return true, (h.player == "a" and "whited out and rebuilt " or "rebuilt with the partner: ") .. key
end

-- Pure: marker lines -> problems (empty = PASS) and the receipt. link_verdict = scenario_gen2_link's S.verdict.
function S.verdict(lines, json, link_verdict)
    local problems, link_receipt = link_verdict(lines, json)
    local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
    local seen, rx, tx = {}, {}, {}
    for index, line in ipairs(lines) do
        line = tostring(line)
        local tag, body = line:match("^([%u%d_]+) (.*)$")
        if tag and S.JSON_TAGS[tag] then
            local value = json.decode(body)
            if need(type(value) == "table", "malformed " .. tag .. " marker") then
                seen[tag] = seen[tag] or {}
                table.insert(seen[tag], {at=index, value=value})
            end
        elseif tag == "RX" then
            local cmd, key = body:match("^(%S+) key=(%S+)$")
            cmd = cmd or body:match("^(%S+)$")
            rx[#rx + 1] = {at=index, cmd=cmd, key=key}
        elseif tag == "TX" then
            local event = body:match('"event":"([%w_]+)"')
            if event == "party_to_box" or event == "box_to_party" or event == "whiteout" then
                tx[#tx + 1] = {at=index, event=event}
            end
        end
    end
    local function rows(tag) return seen[tag] or {} end
    local function one(tag)
        local r = rows(tag)
        need(#r == 1, #r == 0 and ("missing " .. tag .. " marker") or string.format("%d %s markers (expected one)", #r, tag))
        return r[1]
    end
    local head, client, capture = rows("DUO_GEN2")[1], rows("CLIENT")[1], rows("ENGINE_CAPTURE")[1]
    local key, player = capture and capture.value.key, head and head.value.player
    local link, rebuilt, save = one("LINK_SAVE"), one("REBUILT"), one("SAVE_WITNESS")
    need(link ~= nil and type(key) == "string" and link.value.key == key, "LINK_SAVE names another key than the catch")
    local after = {}
    for _, r in ipairs(rx) do if link and r.at > link.at then after[#after + 1] = r end end
    local function first(cmd, from)
        for _, r in ipairs(after) do
            if r.cmd == cmd and (r.key == nil or r.key == key) and r.at > (from or 0) then return r end
        end
    end
    for _, r in ipairs(after) do
        need(r.cmd ~= "force_faint" and r.cmd ~= "memorialize" and r.cmd ~= "game_over",
             "a death command reached " .. tostring(player) .. " (" .. tostring(r.cmd) .. ")")
    end
    local count = function(event) local n = 0 for _, t in ipairs(tx) do if t.event == event then n = n + 1 end end return n end
    if rebuilt then
        local v = rebuilt.value
        need(v.key == key and type(v.slot) == "number" and type(v.hp) == "number" and v.hp > 0 and v.party_count == 2,
             "REBUILT does not show the linked half alive in a two-mon party")
        need(save ~= nil and save.at > rebuilt.at, "the final save precedes REBUILT")
    end
    if link and save then
        need(type(save.value.gate_saves) == "number" and save.value.gate_saves > link.value.gate_saves,
             "no native save after LINK_SAVE")
    end
    local detail = {}
    if player == "a" then
        for _, site in ipairs(S.SITES) do
            need(client ~= nil and has(client.value.registered_sites, site), "production signals lack " .. site)
        end
        local pc, faint, whiteout = one("ENGINE_PC"), one("ENGINE_FAINT"), one("ENGINE_WHITEOUT")
        need(pc == nil or (pc.value.kind == "party_to_box" and pc.value.key == key), "the hand deposit is not the linked key")
        need(count("party_to_box") == 1 and count("box_to_party") == 0 and count("whiteout") == 1,
             "A's sends are not one party_to_box and one whiteout")
        if faint then
            need(faint.value.site_id == "battle_faint" and faint.value.key ~= key, "the only faint is not the starter's")
            need(pc ~= nil and faint.at > pc.at, "the starter fainted before the deposit")
        end
        if whiteout then
            local party = whiteout.value.party
            need(whiteout.value.site_id == "whiteout_before_heal" and type(party) == "table" and #party == 1
                 and party[1].hp == 0 and faint ~= nil and party[1].key == faint.value.key,
                 "the pre-heal whiteout party is not the starter alone at HP 0")
            need(faint ~= nil and whiteout.at > faint.at, "the whiteout precedes the faint")
        end
        local start = first("rebuild_start", whiteout and whiteout.at)
        local withdraw = first("party_mon", start and start.at)
        local done = first("rebuild_done", withdraw and withdraw.at)
        need(start ~= nil and withdraw ~= nil and done ~= nil, "no rebuild_start, party_mon, rebuild_done after the whiteout")
        need(done == nil or rebuilt == nil or rebuilt.at > done.at, "REBUILT precedes rebuild_done")
        detail = {whiteout=whiteout and whiteout.value}
    elseif player == "b" then
        need(#rows("ENGINE_PC") == 0 and #rows("ENGINE_FAINT") == 0 and #rows("ENGINE_WHITEOUT") == 0,
             "B's own PC ran or B's own mon fainted")
        need(#tx == 0, "B sent a storage or whiteout event of its own")
        local boxed = one("PARTNER_BOXED")
        local box = first("box_mon")
        local withdraw = first("party_mon", boxed and boxed.at)
        need(box ~= nil and boxed ~= nil and boxed.at > box.at and boxed.value.key == key and boxed.value.slot == nil,
             "B's half was not boxed by the mirrored box_mon")
        need(first("rebuild_start") == nil, "B received rebuild_start")
        need(withdraw ~= nil and rebuilt ~= nil and rebuilt.at > withdraw.at, "no rebuild party_mon before REBUILT")
    else
        need(false, "DUO_GEN2 names no player a|b")
    end
    if #problems > 0 then return problems, nil end
    local receipt = link_receipt
    receipt.schema, receipt.link_save, receipt.rebuilt = S.RECEIPT_SCHEMA, link.value, rebuilt.value
    for k, v in pairs(detail) do receipt[k] = v end
    return problems, receipt
end

return S
