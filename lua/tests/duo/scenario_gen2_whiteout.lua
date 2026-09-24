--[[
  lua/tests/duo/scenario_gen2_whiteout.lua -- the gen2_new `whiteout` scenario (D-7/W-7, O-24: dead stays dead).

  Both halves play the `link` scenario and save it (scenario_gen2_faint.lua S.link_prelude, LINK_SAVE), then:
    A  waits for B's LINK_SAVE, then loses its whole party in the grass, the linked catch LAST
       (lua/tests/duo/gen2_faint_inputs.lua twice): the starter faints first (YES to "Use next", the catch comes in
       and RUNs), then the catch fights alone until it faints. The engine faint -> `faint` -> the pair dies,
       force_faint to B and memorialize to both are queued. With nobody left standing the game whites out:
       whiteout_before_heal (the pre-heal party, every mon HP 0) -> HealParty revives the DEAD linked mon ->
       the warp home. The server sees the dead key at HP > 0 in A's party snapshot and re-issues force_faint
       (O-24, state.py _repair_lost_faints). The memorial takes the key to Box 14. A saves natively.
    B  is scenario_gen2_faint.lua's B half unchanged (bench force_faint at the checkpoint, memorial, save):
       the whiteout itself changes nothing on B (the pair was already dead; _handle_whiteout retires only
       ALIVE links).

  MARKER CONTRACT (duo_gen2_main.lua prints them; JSON after the tag). Everything scenario_gen2_faint.lua lists,
  for B identically. A differs:
    ENGINE_FAINT x2                 the starter's (first), then the linked key's, both battle_faint/battle
    FAINT_SENT                      the client sent `faint` (the last one names the linked key)
    ENGINE_WHITEOUT {frame, site_id="whiteout_before_heal", party=[{key, hp=0}...]}   after the linked faint
    REVIVED {frame, key, slot, hp}  the linked key back at HP > 0 after the heal (the harness's own party read)
    RX force_faint key=<key>        the O-24 re-issue for A's own dead key, after REVIVED
    PARTY_HP_WRITE                  0 or 1: the re-issued force_faint zeroes the revived mon at the checkpoint
                                    when it runs before the memorial; otherwise the memorial boxed it first
                                    and the command is dropped (client.lua run_deferred, "key not in party")
    MEMORIAL_PREIMAGE / MEMORIAL_ACK (box 13) / SAVE_WITNESS / RECEIPT {schema "gen2-duo-whiteout-v1"}
  TX: exactly one `"event":"whiteout"` on A, none on B.
--]]
local S = {}
S.RECEIPT_SCHEMA = "gen2-duo-whiteout-v1"
S.FAINT_INPUTS = true
S.FAINT = "lua/tests/duo/scenario_gen2_faint.lua"
S.LINK = "lua/tests/duo/scenario_gen2_link.lua"
S.MAX_BATTLES = 12       -- ponytail: the lone Tackle-only catch may win battles before it falls; raise if a lane needs more
S.REPAIR_FRAMES = 3600   -- A: REVIVED -> the O-24 force_faint (one reconciler pass per tick, 30 frames)
S.SITES = {"battle_faint", "whiteout_before_heal"}
S.JSON_TAGS = {ENGINE_FAINT=true, FAINT_SENT=true, ENGINE_WHITEOUT=true, REVIVED=true, PARTY_HP_WRITE=true,
               MEMORIAL_PREIMAGE=true, MEMORIAL_ACK=true, SAVE_WITNESS=true, LINK_SAVE=true, ENGINE_CAPTURE=true,
               DUO_GEN2=true, CLIENT=true}

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
    if h.player == "b" then
        local ok, bench_why = FS.bench_half(h, key)
        if not ok then return false, bench_why end
        FS.RECEIPT_SCHEMA = S.RECEIPT_SCHEMA
        return FS.close(h, key, function(lines, json) return FS.verdict(lines, json, link.verdict) end,
                        "force_faint applied to " .. key .. "; the partner's whiteout changed nothing")
    end

    if not FS.await_partner_link(h) then return false, "B never printed LINK_SAVE" end
    local slot = h.slot_of(key)
    if slot == nil then return false, "the linked mon left the party" end
    local starter
    local party = h.sym("wPartyCount")[1]
    for s = 0, party - 1 do if s ~= slot then starter = starter or s end end
    if starter == nil or party ~= 2 then return false, "A's party is not [starter, linked catch]" end
    local starter_key   -- the last MYKEY for the starter's slot (h.party() after the route)
    for _, line in ipairs(h.lines) do
        local s, k = tostring(line):match("^MYKEY (%d+) (%S+)$")
        if s and tonumber(s) == starter then starter_key = k end
    end
    if starter_key == nil or starter_key == key then return false, "the starter's key is unknown" end
    -- 1. the starter falls (not linked: the server ignores its faint); the catch comes in and RUNs
    local fought, fight_why = h.sacrifice({target=starter, max_battles=S.MAX_BATTLES,
        fainted=function() return h.rec.faint_keys[starter_key] ~= nil end})
    if not fought then return false, "starter faint route failed: " .. tostring(fight_why) end
    -- 2. the linked catch falls last: the whiteout, then the heal revives it (REVIVED, seen on any observation)
    local revived
    local function watch()
        if revived or not h.rec.whiteout then return end
        local rslot, mon = h.slot_of(key)
        if mon and mon.hp > 0 then
            revived = {frame=h.frame(), key=key, slot=rslot, hp=mon.hp}
            h.jlog("REVIVED", revived)
        end
    end
    fought, fight_why = h.sacrifice({target=slot, max_battles=S.MAX_BATTLES, observed=watch,
        fainted=function() return h.rec.faint_keys[key] ~= nil end})
    if not fought then return false, "linked faint route failed: " .. tostring(fight_why) end
    if not h.wait(function() watch(); return revived ~= nil or h.rec.memorial[key] ~= nil end, S.REPAIR_FRAMES) then
        return false, "no whiteout heal observed for " .. key
    end
    if not revived then return false, "the linked mon left the party before the heal was observed" end
    if not h.wait(function()
        for _, r in ipairs(h.rec.rx) do if r.cmd == "force_faint" and r.key == key then return true end end
        return false
    end, S.REPAIR_FRAMES) then return false, "the server never re-issued force_faint for the revived " .. key end
    return FS.close(h, key, function(lines, json) return S.verdict(lines, json, link.verdict) end,
                    "whited out; " .. key .. " revived, re-killed and buried")
end

-- Pure (A's half): marker lines -> problems (empty = PASS) and the receipt. link_verdict = scenario_gen2_link's.
function S.verdict(lines, json, link_verdict)
    local problems, link_receipt = link_verdict(lines, json)
    local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
    local seen, rx, tx_whiteout = {}, {}, 0
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
            if cmd == "force_faint" then rx[#rx + 1] = {at=index, key=key} end
        elseif tag == "TX" and body:find('"event":"whiteout"', 1, true) then
            tx_whiteout = tx_whiteout + 1
        end
    end
    local function rows(tag) return seen[tag] or {} end
    local function one(tag)
        local r = rows(tag)
        need(#r == 1, #r == 0 and ("missing " .. tag .. " marker") or string.format("%d %s markers (expected one)", #r, tag))
        return r[1]
    end
    local head, client, capture = rows("DUO_GEN2")[1], rows("CLIENT")[1], rows("ENGINE_CAPTURE")[1]
    local key = capture and capture.value.key
    need(head ~= nil and head.value.player == "a", "the whiteout verdict is A's half")
    for _, site in ipairs(S.SITES) do
        need(client ~= nil and has(client.value.registered_sites, site), "production signals lack " .. site)
    end
    local link, whiteout, revived = one("LINK_SAVE"), one("ENGINE_WHITEOUT"), one("REVIVED")
    local save = one("SAVE_WITNESS")
    need(link ~= nil and link.value.key == key and type(key) == "string", "LINK_SAVE names another key than the catch")
    local faints = rows("ENGINE_FAINT")
    need(#faints == 2, string.format("%d ENGINE_FAINT markers (expected the starter's, then the linked key's)", #faints))
    local first, last = faints[1], faints[2]
    for _, f in ipairs(faints) do
        need(f.value.site_id == "battle_faint" and f.value.cause == "battle", "an engine faint is not battle_faint/battle")
        need(link ~= nil and f.at > link.at, "an engine faint precedes LINK_SAVE")
    end
    if first and last then
        need(first.value.key ~= key and last.value.key == key, "the linked catch did not faint last")
    end
    local sent
    for _, r in ipairs(rows("FAINT_SENT")) do if r.value.key == key then sent = sent or r end end
    need(sent ~= nil and last ~= nil and sent.at > last.at, "no faint sent for the linked key after its engine faint")
    if whiteout then
        local w = whiteout.value
        need(w.site_id == "whiteout_before_heal", "the whiteout is not whiteout_before_heal")
        local listed = false
        for _, m in ipairs(type(w.party) == "table" and w.party or {}) do
            need(m.hp == 0, "a pre-heal whiteout party mon had HP")
            listed = listed or m.key == key
        end
        need(listed and #w.party == 2, "the pre-heal party is not [starter, linked catch]")
        need(last ~= nil and whiteout.at > last.at, "the whiteout precedes the linked faint")
    end
    need(tx_whiteout == 1, string.format("%d whiteout events sent (expected exactly one)", tx_whiteout))
    if revived then
        local r = revived.value
        need(r.key == key and type(r.hp) == "number" and r.hp > 0, "REVIVED does not show the linked key alive")
        need(whiteout ~= nil and revived.at > whiteout.at, "REVIVED precedes the whiteout")
    end
    local repair
    for _, r in ipairs(rx) do if r.key == key and revived and r.at > revived.at then repair = repair or r end end
    need(repair ~= nil, "no O-24 force_faint re-issued for the revived linked key")
    local writes = rows("PARTY_HP_WRITE")
    need(#writes <= 1, string.format("%d PARTY_HP_WRITE markers (expected at most one)", #writes))
    local pre, done
    for _, r in ipairs(rows("MEMORIAL_PREIMAGE")) do if r.value.key == key then pre = pre or r end end
    for _, r in ipairs(rows("MEMORIAL_ACK")) do
        if r.value.key == key and r.value.event == "memorialize_done" and r.value.box == 13 then done = done or r end
    end
    need(pre ~= nil and done ~= nil and pre.at < done.at, "no memorial (preimage, then memorialize_done box 13)")
    local outcome = "memorial_first"
    if writes[1] then
        local w = writes[1]
        need(w.value.ok == true and w.value.key == key and w.value.kind == "party_hp", "the repair write failed or hit another mon")
        need(repair ~= nil and w.at > repair.at, "the repair write precedes the re-issued force_faint")
        need(pre ~= nil and w.at < pre.at, "the repair write follows the memorial preimage")
        outcome = "written"
    end
    if save and done then need(save.at > done.at, "the final save precedes the memorial") end
    if link and save then
        need(type(save.value.gate_saves) == "number" and save.value.gate_saves > link.value.gate_saves,
             "no native save after LINK_SAVE")
    end
    if #problems > 0 then return problems, nil end
    local receipt = link_receipt
    receipt.schema, receipt.link_save = S.RECEIPT_SCHEMA, link.value
    receipt.starter_faint, receipt.faint = first.value, last.value
    receipt.whiteout, receipt.revived = whiteout.value, revived.value
    receipt.repair = {outcome=outcome, force_faint_key=key}
    receipt.memorial = {preimage_frame=pre.value.frame, ack=done.value}
    return problems, receipt
end

return S
