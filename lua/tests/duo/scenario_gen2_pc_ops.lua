--[[
  lua/tests/duo/scenario_gen2_pc_ops.lua -- the gen2_new `pc_ops` scenario (S-6, D-3/D-9 PC sync, W-5 listing).
  Gen 1 reference: pc_ops_new (duo_gen1_main.lua). Bill's PC by play: lua/tests/gen2_pc_inputs.lua (opts.steps).

  Both halves play the `link` scenario and save it (scenario_gen2_faint.lua S.link_prelude, LINK_SAVE), then:
    A  waits for B's LINK_SAVE, walks Route 29 -> Cherrygrove -> the #MON CENTER PC (party [starter, catch]):
         session 1  DEPOSIT the linked catch, WITHDRAW it          -> party_to_box, box_to_party on the wire
         waits for B's PC_PARTNER_2 (B's partner is back in B's party, so the server has B's key in party again)
         session 2  DEPOSIT it again, RELEASE it from the box       -> party_to_box, then release{key} (owner ruling
                    O-35, client 149b38e2): the server kills the pair and memorializes B's partner (state.py
                    _handle_release -> _propagate_faint cause "release"); A's released half gets no memorial
       then saves natively.
    B  idles in the overworld. The server mirrors each move onto B's linked mon (state.py _handle_party_to_box ->
       box_mon, _handle_box_to_party -> party_mon); the production client runs each at its checkpoint. B prints
       PC_PARTNER_<n> once the command n ran physically. After A's release: force_faint (dropped: the partner is
       boxed, a box record has no HP) and memorialize (its boxed half into Box 14, MEMORIAL_ACK), then saves.

  MARKER CONTRACT (duo_gen2_main.lua prints them; JSON after the tag). Everything the `link` scenario prints plus
  LINK_SAVE (scenario_gen2_faint.lua's contract). Added:
    A: ENGINE_PC {kind, site_id, key, collection, box_index, ...}  the binder's PC events, in order: party_to_box,
         box_to_party, party_to_box, pc_release (collection "box") -- all for the linked key
       PC_STATE {frame, phase "deposit-withdraw"|"deposit-release", party_count, box_count, cur_box}   after each session
    B: RX box_mon|party_mon key=<key>                                 (plain text, the driver's RX line)
       PC_PARTNER_1 / _2 / _3 {frame, cmd, key, in_party, party_count, box_count}   after box_mon, party_mon, box_mon ran
       RX force_faint key=<key>, RX memorialize key=<key>, MEMORIAL_ACK {event memorialize_done, box 13}   after PC_PARTNER_3
    A: TX release {key}   after the box release's ENGINE_PC; A receives no death command
    both: SAVE_WITNESS (the final save, newer than LINK_SAVE), RECEIPT {schema "gen2-duo-pc-ops-v2"}
--]]
local S = {}
S.RECEIPT_SCHEMA = "gen2-duo-pc-ops-v2"
S.PC_INPUTS = true
S.FAINT = "lua/tests/duo/scenario_gen2_faint.lua"
S.LINK = "lua/tests/duo/scenario_gen2_link.lua"
S.PARTNER_FRAMES = 54000
S.SYNC_FRAMES = 36000     -- B: one mirrored PC command (A's walk to the PC included)
S.SITES = {"pc_deposit_begin", "pc_deposit_complete", "pc_withdraw_begin", "pc_withdraw_complete",
           "pc_release_box_begin", "pc_release_box_complete"}
S.PARTNER = {"box_mon", "party_mon", "box_mon"}   -- B's mirrored commands, in order
S.ENGINE = {{"party_to_box"}, {"box_to_party"}, {"party_to_box"}, {"pc_release", "box"}}
S.JSON_TAGS = {LINK_SAVE=true, ENGINE_PC=true, PC_STATE=true, PC_PARTNER_1=true, PC_PARTNER_2=true, PC_PARTNER_3=true,
               SAVE_WITNESS=true, ENGINE_CAPTURE=true, DUO_GEN2=true, CLIENT=true, MEMORIAL_ACK=true}

local function has(list, value)
    for _, v in ipairs(list or {}) do if v == value then return true end end
    return false
end

local function state(h, phase)
    return {frame=h.frame(), phase=phase, party_count=h.sym("wPartyCount")[1], box_count=h.box_count(),
            cur_box=h.sym("wCurBox")[1]}
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
    local rx0 = #h.rec.rx   -- the link's own quarantine box_mon/party_mon are already in the log; count past them
    local function verdict(lines, json) return S.verdict(lines, json, link.verdict) end

    if h.player == "b" then
        for n, cmd in ipairs(S.PARTNER) do
            local want_party = cmd == "party_mon"
            if not h.wait(function()
                local got = 0
                for i = rx0 + 1, #h.rec.rx do
                    local r = h.rec.rx[i]
                    if r.cmd == cmd and r.key == key then got = got + 1 end
                end
                local needed = cmd == "box_mon" and (n == 1 and 1 or 2) or 1
                return got >= needed and #(h.client.deferred or {}) == 0 and (h.slot_of(key) ~= nil) == want_party
            end, S.SYNC_FRAMES) then return false, string.format("partner command %d (%s) never ran for %s", n, cmd, key) end
            local row = state(h, cmd)
            row.phase, row.cmd, row.key, row.in_party = nil, cmd, key, want_party
            h.jlog("PC_PARTNER_" .. n, row)
        end
        -- O-35: A's release kills the pair; B's boxed partner is memorialized into Box 14
        if not h.wait(function() return h.rec.memorial[key] ~= nil end, S.SYNC_FRAMES) then
            return false, "no memorialize ack for the released partner " .. key
        end
        if h.rec.memorial[key].event ~= "memorialize_done" then
            return false, "the partner's memorial failed: " .. tostring(h.rec.memorial[key].reason)
        end
    else
        if not FS.await_partner_link(h) then return false, "B never printed LINK_SAVE" end
        local slot = h.slot_of(key)
        if slot ~= 1 or h.sym("wPartyCount")[1] ~= 2 then return false, "A's party is not [starter, linked catch]" end
        local ok, pc_why = h.pc({{op="deposit", slot=slot}, {op="withdraw"}})
        if not ok then return false, "PC deposit/withdraw: " .. tostring(pc_why) end
        h.jlog("PC_STATE", state(h, "deposit-withdraw"))
        if not h.wait(function() return h.partner_has("PC_PARTNER_2") end, S.PARTNER_FRAMES) then
            return false, "B never printed PC_PARTNER_2"
        end
        ok, pc_why = h.pc({{op="deposit", slot=slot}, {op="release_box"}})
        if not ok then return false, "PC deposit/release: " .. tostring(pc_why) end
        h.jlog("PC_STATE", state(h, "deposit-release"))
    end
    if not h.wait(h.box_idle, S.SYNC_FRAMES) then return false, "box commands still pending before the save" end
    local saved, save_why = h.save()
    if not saved then return false, "final save failed: " .. tostring(save_why) end
    local witnessed, witness_why = h.witness()
    if not witnessed then return false, "save witness: " .. tostring(witness_why) end
    h.frames(FS.SETTLE_FRAMES)
    local problems, receipt = verdict(h.lines, h.json)
    if #problems > 0 then return false, table.concat(problems, "; ") end
    h.jlog("RECEIPT", receipt)
    return true, h.player == "a" and ("deposited, withdrew, deposited and released " .. key)
        or ("followed the partner's PC moves with " .. key)
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
            if cmd == "box_mon" or cmd == "party_mon" or cmd == "force_faint" or cmd == "memorialize" then
                rx[#rx + 1] = {at=index, cmd=cmd, key=key}
            end
        elseif tag == "TX" then
            local event = body:match('"event":"([%w_]+)"')
            if event == "party_to_box" or event == "box_to_party" or event == "faint" or event == "release" then
                tx[#tx + 1] = {at=index, event=event, key=body:match('"key":"([^"]+)"')}
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
    local link, save = one("LINK_SAVE"), one("SAVE_WITNESS")
    -- only traffic after the linked save counts (the link's quarantine moves come before it)
    local function after_link(list)
        local out = {}
        for _, r in ipairs(list) do if link ~= nil and r.at > link.at then out[#out + 1] = r end end
        return out
    end
    rx, tx = after_link(rx), after_link(tx)
    need(link ~= nil and type(key) == "string" and link.value.key == key, "LINK_SAVE names another key than the catch")
    if link and save then
        need(save.at > link.at and type(save.value.gate_saves) == "number" and save.value.gate_saves > link.value.gate_saves,
             "no native save after LINK_SAVE")
    end
    if player == "a" then
        for _, r in ipairs(rx) do
            need(r.cmd ~= "force_faint" and r.cmd ~= "memorialize", "a death command reached a (" .. r.cmd .. ")")
        end
    end
    local detail = {}
    if player == "a" then
        for _, site in ipairs(S.SITES) do
            need(client ~= nil and has(client.value.registered_sites, site), "production signals lack " .. site)
        end
        local pc = rows("ENGINE_PC")
        need(#pc == #S.ENGINE, string.format("%d ENGINE_PC markers (expected %d)", #pc, #S.ENGINE))
        for i, want in ipairs(S.ENGINE) do
            local r = pc[i]
            if r then
                need(r.value.kind == want[1] and r.value.key == key and (want[2] == nil or r.value.collection == want[2]),
                     string.format("PC event %d is not %s for the linked key", i, want[1] .. (want[2] and ("/" .. want[2]) or "")))
                need(link ~= nil and r.at > link.at and (save == nil or r.at < save.at), "a PC event outside LINK_SAVE..save")
                need(pc[i - 1] == nil or r.at > pc[i - 1].at, "PC events out of order")
            end
        end
        -- the wire: party_to_box, box_to_party, party_to_box for the key, each after its engine event; the
        -- box release sends nothing (S-6 gap)
        need(#tx == 4 and tx[1].event == "party_to_box" and tx[2].event == "box_to_party" and tx[3].event == "party_to_box"
             and tx[4].event == "release", "A's sends are not party_to_box, box_to_party, party_to_box, release")
        for i = 1, math.min(#tx, 3) do
            need(tx[i].key == key and pc[i] ~= nil and tx[i].at > pc[i].at, "storage send " .. i .. " precedes its engine event or names another key")
        end
        need(pc[4] == nil or tx[3] == nil or pc[4].at > tx[3].at, "the release precedes the third storage send")
        need(pc[4] == nil or tx[4] == nil or (tx[4].key == key and tx[4].at > pc[4].at),
             "release{key} was not sent for the linked key after the box release")
        local states = rows("PC_STATE")
        need(#states == 2, string.format("%d PC_STATE markers (expected two)", #states))
        if states[1] then
            local s = states[1].value
            need(s.phase == "deposit-withdraw" and s.party_count == 2 and s.box_count == 0, "session 1 did not end with the catch back in the party")
        end
        if states[2] then
            local s = states[2].value
            need(s.phase == "deposit-release" and s.party_count == 1 and s.box_count == 0 and s.cur_box == states[1].value.cur_box,
                 "session 2 did not end with the starter alone and the box empty")
            need(save ~= nil and save.at > states[2].at, "the final save precedes the PC session")
        end
        detail = {pc_events=#pc, sessions=#states}
    elseif player == "b" then
        need(#rows("ENGINE_PC") == 0, "B's own PC ran")
        need(#tx == 0, "B sent a storage event of its own")
        local boxed = {}
        for n, cmd in ipairs(S.PARTNER) do
            local p = one("PC_PARTNER_" .. n)
            local got
            for _, r in ipairs(rx) do
                if r.cmd == cmd and r.key == key and not boxed[r.at] and (got == nil) then got = r end
            end
            if got then boxed[got.at] = true end
            need(got ~= nil and link ~= nil and got.at > link.at, "no RX " .. cmd .. " for B's linked key after LINK_SAVE")
            if p then
                local v = p.value
                need(v.cmd == cmd and v.key == key and v.in_party == (cmd == "party_mon"), "PC_PARTNER_" .. n .. " state differs")
                need(got ~= nil and p.at > got.at, "PC_PARTNER_" .. n .. " precedes its command")
                need(v.party_count == (cmd == "party_mon" and 2 or 1), "PC_PARTNER_" .. n .. " party count differs")
                need(save ~= nil and p.at < save.at, "the final save precedes PC_PARTNER_" .. n)
                local prev = rows("PC_PARTNER_" .. (n - 1))[1]
                need(prev == nil or p.at > prev.at, "PC_PARTNER markers out of order")
            end
        end
        -- O-35: after the third mirror, the death (force_faint, memorialize) and its Box 14 ack, before the save
        local third = rows("PC_PARTNER_3")[1]
        local kill, bury
        for _, r in ipairs(rx) do
            if third and r.at > third.at and r.key == key then
                if r.cmd == "force_faint" then kill = kill or r elseif r.cmd == "memorialize" then bury = bury or r end
            end
        end
        need(kill ~= nil and bury ~= nil, "no force_faint and memorialize for B's partner after the release")
        local ack
        for _, r in ipairs(rows("MEMORIAL_ACK")) do
            if r.value.key == key and r.value.event == "memorialize_done" and r.value.box == 13 then ack = ack or r end
        end
        need(ack ~= nil and bury ~= nil and ack.at > bury.at and save ~= nil and save.at > ack.at,
             "no memorialize_done (box 13) for B's partner before the final save")
        detail = {partner_commands=S.PARTNER, partner_memorial=ack and ack.value}
    else
        need(false, "DUO_GEN2 names no player a|b")
    end
    if #problems > 0 then return problems, nil end
    local receipt = link_receipt
    receipt.schema, receipt.link_save = S.RECEIPT_SCHEMA, link.value
    for k, v in pairs(detail) do receipt[k] = v end
    return problems, receipt
end

return S
