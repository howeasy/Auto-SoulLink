--[[
  lua/tests/duo/scenario_gen2_faint.lua -- the gen2_new `gen2_faint` scenario: faint propagation (card gen2-H1c).

  The first PHYSICAL proof of the Gen 2 production WRITE path. Both halves first play the `link` scenario
  unchanged (CONTINUE, hello, go-file, catch one Route 29 wild mon, report it, native save), then:
    A  waits for B's LINK_SAVE, walks back into the grass, switches the linked catch in and lets it faint
       (lua/tests/duo/gen2_faint_inputs.lua); the production binder's battle_faint event -> the client's
       `faint` -> the server queues force_faint for B's linked key. A saves natively.
    B  stands still in the overworld (the client's checkpoint holds every idle frame) until force_faint
       arrives; the PRODUCTION client runs it at the U2 write-window checkpoint (client.lua run_deferred
       from at_checkpoint -> writes.lua faint_party_slot, the only admitted write, party_faint ->
       party_hp). B reads the record back and saves natively.
  A may only start once its production binder registered battle_faint (a receipt-proven site): without it
  the client can never emit `faint`, so A FAILs before any input.

  MARKER CONTRACT (agreed with the lane/oracle owner, Codex Gen2-Part2; duo_gen2_main.lua prints them;
  JSON after the tag unless noted). Everything the `link` scenario prints, in the same order, except that
  its SAVE_WITNESS is the FINAL save here. Added:
    CLIENT.registered_sites   the production binder's status().registered_sites (A needs battle_faint)
    LINK_SAVE {frame, saveram_path, saveram_bytes=32790, cartram_sha256, cartram_bytes=32768, gate_saves,
               client_saves, save_completed_frame, key}       both; after CAUGHT, the linked save copied
               once to <result minus _result.txt>_link_save.SaveRAM (flush proven like SAVE_WITNESS)
    A: ENGINE_FAINT {frame, site_id="battle_faint", cause="battle", key, slot}   the binder's faint event
       FAINT_SENT {frame, key, seq}                                the client sent `faint` for that key
    B: RX force_faint key=<key>                                    (plain text, the driver's RX line)
       PARTY_HP_WRITE {frame, key, slot, kind="party_hp", ok, error, before_party_hex, after_party_hex,
                       log=[the permit receipts the call added], checkpoint={pc, sp, hrom_bank, svbk, sc,
                       stack_hex, anchor_hex, state={symbol: raw value}}}   around the production call
       BENCH_HP_STATUS <hp %04X> <status %02X>        (plain text, Gen 1's name) the record read back
    SAVE_WITNESS              the final native save, strictly newer than LINK_SAVE (more gate + client saves)
    RECEIPT {schema "gen2-duo-faint-v1", ...}  PASS only;  RESULT: PASS|FAIL  last line
  S.verdict re-reads these lines (plus the link verdict over the same lines) and is the only way to PASS.
--]]
local S = {}
S.RECEIPT_SCHEMA = "gen2-duo-faint-v1"
S.FAINT_INPUTS = true    -- duo_gen2_main.lua prepares gen2_faint_inputs.lua's UI origins before its hooks
-- ponytail: live bounds, not measured; raise if a lane needs longer.
S.HELLO_FRAMES = 3600
S.GO_FRAMES = 54000
S.PARTNER_FRAMES = 54000   -- A waits this long for B's LINK_SAVE
S.FORCE_FRAMES = 120000    -- B waits this long for force_faint (A's link + faint battle)
S.SEND_FRAMES = 600        -- A: engine faint -> `faint` on the wire
S.WRITE_FRAMES = 1800      -- B: force_faint -> the checkpoint write
S.SETTLE_FRAMES = 120
S.SAVERAM_BYTES = 0x8000 + 22
S.KEY = "^%x%x%x%x:%x%x%x%x:%x%x$"
S.LINK = "lua/tests/duo/scenario_gen2_link.lua"
S.JSON_TAGS = {LINK_SAVE=true, ENGINE_FAINT=true, FAINT_SENT=true, PARTY_HP_WRITE=true, CLIENT=true,
               DUO_GEN2=true, SAVE_WITNESS=true, ENGINE_CAPTURE=true}

local function has(list, value)
    for _, v in ipairs(list or {}) do if v == value then return true end end
    return false
end

function S.run(h)
    local link = dofile(h.root .. "/" .. S.LINK)
    if h.player == "a" and not has(h.registered, "battle_faint") then
        return false, "production signals lack battle_faint"
    end
    h.jitter()
    local arrived, why = h.arrive()
    if not arrived then return false, "no CONTINUE arrival: " .. tostring(why) end
    h.party()
    if not h.wait(function() return h.sent.hello ~= nil end, S.HELLO_FRAMES) then return false, "the client never sent hello" end
    if not h.wait(h.go, S.GO_FRAMES) then return false, "no go-file" end
    local played, outcome = h.play()
    if not played then return false, "link route failed: " .. tostring(outcome) end
    h.party()
    local key = h.rec.caught
    if not key then return false, "no linked catch" end
    local saved, save_why = h.link_save(key)
    if not saved then return false, "link save: " .. tostring(save_why) end

    if h.player == "a" then
        if not h.wait(function() return h.partner_has("LINK_SAVE") end, S.PARTNER_FRAMES) then
            return false, "B never printed LINK_SAVE"
        end
        local slot = h.slot_of(key)
        if slot == nil then return false, "the linked mon left the party" end
        local fought, fight_why = h.sacrifice({target=slot, fainted=function()
            return h.rec.faint ~= nil and h.rec.faint.key == key
        end})
        if not fought then return false, "faint route failed: " .. tostring(fight_why) end
        if not h.wait(function() return h.rec.faint_sent ~= nil end, S.SEND_FRAMES) then
            return false, "the client never sent faint for the engine faint"
        end
    else
        if not h.wait(function()
            for _, r in ipairs(h.rec.rx) do if r.cmd == "force_faint" and r.key == key then return true end end
            return false
        end, S.FORCE_FRAMES) then return false, "force_faint never arrived for " .. key end
        if not h.wait(function() return h.rec.hp_write ~= nil end, S.WRITE_FRAMES) then
            return false, "the production client never wrote the bench faint"
        end
        local _, mon = h.slot_of(key)
        if not mon then return false, "the linked mon left the party" end
        h.log(string.format("BENCH_HP_STATUS %04X %02X", mon.hp, mon.status))
        if mon.hp ~= 0 or mon.status ~= 0 then return false, "the bench faint did not zero HP/status" end
    end

    local resaved, resave_why = h.save()
    if not resaved then return false, "final save failed: " .. tostring(resave_why) end
    local witnessed, witness_why = h.witness()
    if not witnessed then return false, "save witness: " .. tostring(witness_why) end
    h.frames(S.SETTLE_FRAMES)
    local problems, receipt = S.verdict(h.lines, h.json, link.verdict)
    if #problems > 0 then return false, table.concat(problems, "; ") end
    h.jlog("RECEIPT", receipt)
    return true, (h.player == "a" and "fainted " or "force_faint applied to ") .. key
end

-- Pure: marker lines -> problems (empty = PASS) and the receipt. link_verdict = scenario_gen2_link's S.verdict.
function S.verdict(lines, json, link_verdict)
    local problems, link_receipt = link_verdict(lines, json)
    local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
    local seen, rx, bench = {}, {}, {}
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
        elseif tag == "BENCH_HP_STATUS" then
            bench[#bench + 1] = {at=index, value=body}
        end
    end
    local function rows(tag) return seen[tag] or {} end
    local function one(tag)
        local r = rows(tag)
        need(#r == 1, #r == 0 and ("missing " .. tag .. " marker") or string.format("%d %s markers (expected one)", #r, tag))
        return r[1]
    end
    local head, client, capture, save = rows("DUO_GEN2")[1], rows("CLIENT")[1], rows("ENGINE_CAPTURE")[1], rows("SAVE_WITNESS")[1]
    local key = capture and capture.value.key
    local player = head and head.value.player
    local link = one("LINK_SAVE")
    if link then
        local l = link.value
        need(l.key == key and type(key) == "string" and key:match(S.KEY) ~= nil, "LINK_SAVE names another key than the catch")
        need(l.saveram_bytes == S.SAVERAM_BYTES and l.cartram_bytes == 0x8000 and type(l.cartram_sha256) == "string"
             and #l.cartram_sha256 == 64 and type(l.saveram_path) == "string" and l.saveram_path ~= "",
             "LINK_SAVE incomplete")
        need(capture ~= nil and link.at > capture.at, "LINK_SAVE printed before the catch")
        if save then
            local s = save.value
            need(save.at > link.at, "the final save witness precedes LINK_SAVE")
            need(type(s.gate_saves) == "number" and type(l.gate_saves) == "number" and s.gate_saves > l.gate_saves
                 and type(s.client_saves) == "number" and type(l.client_saves) == "number" and s.client_saves > l.client_saves,
                 "no native save after LINK_SAVE")
        end
    end
    local detail = {}
    if player == "a" then
        need(client ~= nil and has(client.value.registered_sites, "battle_faint"), "production signals lack battle_faint")
        need(#rows("PARTY_HP_WRITE") == 0, "A's party was written")
        local faint, sent = one("ENGINE_FAINT"), one("FAINT_SENT")
        if faint then
            local f = faint.value
            need(f.site_id == "battle_faint" and f.cause == "battle", "engine faint is not battle_faint/battle")
            need(f.key == key, "the engine faint names another mon than the linked catch")
            need(link ~= nil and faint.at > link.at, "engine faint before LINK_SAVE")
        end
        if faint and sent then
            need(sent.value.key == key and sent.at > faint.at and sent.value.frame >= faint.value.frame,
                 "faint sent before the engine faint or for another key")
            need(save ~= nil and save.at > sent.at and type(save.value.save_completed_frame) == "number"
                 and save.value.save_completed_frame > sent.value.frame, "final save completed before the faint was sent")
        end
        detail = {faint=faint and faint.value, faint_sent=sent and sent.value}
    elseif player == "b" then
        need(#rows("ENGINE_FAINT") == 0, "B's own mon fainted in the engine")
        local got
        for _, r in ipairs(rx) do if r.key == key and got == nil then got = r end end
        need(got ~= nil, "no RX force_faint for B's linked key")
        need(got == nil or (link ~= nil and got.at > link.at), "force_faint arrived before LINK_SAVE")
        -- O-24 (6e9bff5b): the server may re-issue force_faint once for a dead link still showing HP > 0, so
        -- one idempotent repeat is allowed: its before AND after bytes equal the first write's after bytes.
        local writes = rows("PARTY_HP_WRITE")
        need(#writes == 1 or #writes == 2, #writes == 0 and "missing PARTY_HP_WRITE marker"
             or string.format("%d PARTY_HP_WRITE markers (expected one, or one idempotent repeat)", #writes))
        local write = writes[1]
        for _, row in ipairs(writes) do
            local w = row.value
            need(w.ok == true and w.kind == "party_hp" and w.key == key, "the checkpoint write failed or hit another mon")
            need(type(w.before_party_hex) == "string" and type(w.after_party_hex) == "string"
                 and #w.before_party_hex == #w.after_party_hex and #w.after_party_hex == 2 * 6 * 48, "party bytes missing")
            need(type(w.log) == "table" and #w.log == 2, "the write left no two-span permit receipt")
            need(type(w.checkpoint) == "table" and w.checkpoint.error == nil and type(w.checkpoint.pc) == "number",
                 "checkpoint evidence missing")
        end
        if write then need(got ~= nil and write.at > got.at, "the write precedes force_faint") end
        if writes[2] and write then
            local first, again = write.value, writes[2].value
            need(again.before_party_hex == first.after_party_hex and again.after_party_hex == first.after_party_hex,
                 "the repeated write is not idempotent")
        end
        need(#bench == 1, #bench == 0 and "missing BENCH_HP_STATUS marker" or "BENCH_HP_STATUS repeated")
        if bench[1] then
            need(bench[1].value == "0000 00", "bench record not at HP 0000 / status 00")
            need(write ~= nil and bench[1].at > write.at, "BENCH_HP_STATUS before the write")
            need(save ~= nil and save.at > bench[1].at, "final save witness before BENCH_HP_STATUS")
        end
        if write and save then
            need(type(save.value.save_completed_frame) == "number" and save.value.save_completed_frame > write.value.frame,
                 "final save completed before the write")
        end
        detail = {force_faint_key=got and got.key,
                  write=write and {frame=write.value.frame, key=write.value.key, slot=write.value.slot,
                                   pc=write.value.checkpoint and write.value.checkpoint.pc}}
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
