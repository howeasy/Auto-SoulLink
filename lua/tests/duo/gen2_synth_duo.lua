--[[
  lua/tests/duo/gen2_synth_duo.lua -- the four DUO-WAVE-D duos that start from an O-33 synthetic setup
  (tools/gen2_synth_fixtures.py; docs/gen2/reviews/DUO_WAVE_D_FACTS_2026-09-24.md). Only the SETUP is synthetic: the
  fixture reaches the game through its base case's qualified CONTINUE (case.synth names the bytes), and everything under
  test runs natively with normal buttons against the production client and server.

  kind   fixture (A / C<->C B: <name>_ot2)   leg                                                 the link it proves
  full   <t>_synth_full   party of 6 on      the link catch (gen2_route29_inputs.lua R.new): a    route_29, box half
         Route 29 grass, Master Balls        Master Ball catch lands in the BOX (capture_box_finalized)  (S-2/S-3, D-3)
  bill   <t>_synth_bill   (U1G recipe)       poison whiteout to Goldenrod, Bill's givepoke EEVEE   the gift area
                                             (gen2_u1g_inputs.lua kind bill; gift_party_finalized)       (S-8 gifts)
  hatch  <t>_synth_hatch  lab, [Sentret,     one step: DoEggStep hatches it (hatch_finalized)      gift_daycare (S-8, O-15)
         Pidgey egg], wStepCount $7F
  trade  <t>_synth_trade  lab, [PSN Sentret, step 1 whites out to Violet City, step 2 hatches the   gift_daycare, then the
         Bellsprout egg], $7E, VIOLET_CITY   Bellsprout (linked), Kyle trades it for ONIX          key_change npc_trade
                                             (gen2_u1g_inputs.lua kind kyle, give_slot 1)          migrates it (S-5, D-1)
  MARKER CONTRACT (duo_gen2_main.lua prints them): DUO_GEN2 {..., synth}, CLIENT, BOOTED, HELLO, ENGINE_CAPTURE,
  CAPTURE_SENT, RX msgbox + RX_TEXT "<a> and <b> linked!", ENGINE_KEY_CHANGE {site_id, reason, old_key, new_key} (trade),
  TX key_change / RX key_change_ack (trade), SAVE_WITNESS; RECEIPT {schema M.SCHEMA[kind], key, capture, key_change,
  synth}. No RX force_faint|memorialize at all: the setups' poison faints come before any link (server FAINT GATE).
--]]
local M = {}
M.SCHEMA = {full="gen2-duo-boxed-capture-v1", bill="gen2-duo-gift-v1", hatch="gen2-duo-egg-hatch-v1",
            trade="gen2-duo-npc-trade-v1"}
-- the engine capture that forms each kind's link (area nil: the binder's gifts.json row area, checked non-empty)
M.EXPECT = {full={site="capture_box_finalized", acquisition="wild", destination="box", area="route_29"},
            bill={site="gift_party_finalized", acquisition="gift", destination="party"},
            hatch={site="hatch_finalized", acquisition="egg_hatch", destination="party", area="gift_daycare"},
            trade={site="hatch_finalized", acquisition="egg_hatch", destination="party", area="gift_daycare"}}
M.EGG = 0xFD   -- EGG, constants/pokemon_constants.asm
M.LINK_FRAMES = 36000   -- ponytail: the partner's whole leg; raise if a lane lags
M.ACK_FRAMES = 3600
M.HOLD = 12
M.JSON_TAGS = {DUO_GEN2=true, CLIENT=true, BOOTED=true, HELLO=true, ENGINE_CAPTURE=true, CAPTURE_SENT=true,
               RX_TEXT=true, ENGINE_KEY_CHANGE=true, SAVE_WITNESS=true}

local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

-- Pure point -> buttons, phase: the hatch leg. Steps onto a free tile (Elm's lab has no wild tiles), A through the
-- hatch text, NO to "Give a nickname to" (the catch_nickname anchor, _BreedAskNicknameText); terminal once the party
-- holds no egg and the overworld is back.
function M.hatch_driver()
    local self = {terminal="hatched", phase="step"}
    local held, hold_left, release = nil, 0, false
    local function press(button)
        release, held, hold_left = true, button, M.HOLD - 1
        return {[button]=true}, self.phase
    end
    function self.step(point)
        if type(point) ~= "table" then return nil, "observation missing" end
        if hold_left > 0 then hold_left = hold_left - 1; return {[held]=true}, self.phase end
        if release then release = false; return {}, self.phase end
        if self.phase == self.terminal then return {}, self.phase end
        if integer(point.battle_mode, 1, 255) then return nil, "a battle started on the hatch leg" end
        local ui = point.ui
        if ui ~= nil then
            if point.input_ready ~= true then return {}, self.phase end
            if ui.kind == "yes_no" then
                if type(ui.items) ~= "table" or not integer(ui.cursor, 1, #ui.items) then return {}, self.phase end
                if ui.prompt ~= "catch_nickname" then return nil, "unmapped yes/no on the hatch leg" end
                if tostring(ui.items[ui.cursor]):upper() == "NO" then return press("A") end
                return press(ui.cursor == 1 and "Down" or "Up")
            end
            if ui.kind == "text" or ui.kind == "prompt_button" or ui.kind == "wait_button" then return press("A") end
            return nil, "UI is not valid on the hatch leg: " .. tostring(ui.kind)
        end
        if point.overworld_ready ~= true then return {}, self.phase end
        local party = type(point.party) == "table" and point.party or {count=0, species={}}
        local egg = false
        for i = 1, party.count do egg = egg or party.species[i] == M.EGG end
        if not egg and party.count >= 1 then self.phase = self.terminal return {}, self.phase end
        for _, d in ipairs({{"Down", 0, 1}, {"Left", -1, 0}, {"Right", 1, 0}, {"Up", 0, -1}}) do
            local free = type(point.can_step) == "table" and point.can_step[d[1]] == true
            for _, object in ipairs(point.blocked or {}) do
                if object.x == point.x + d[2] and object.y == point.y + d[3] then free = false end
            end
            if free then return {[d[1]]=true}, self.phase end
        end
        return {}, self.phase
    end
    return self
end

local function linked(h)
    for _, r in ipairs(h.rec.rx) do
        if r.cmd == "msgbox" and type(r.text) == "string" and r.text:sub(-8) == " linked!" then return true end
    end
    return false
end
local function acked(h)
    for _, r in ipairs(h.rec.rx) do if r.cmd == "key_change_ack" then return true end end
    return false
end

function M.new(kind)
    assert(M.SCHEMA[kind], "unknown synth duo kind " .. tostring(kind))
    local S = {SYNTH=kind, RECEIPT_SCHEMA=M.SCHEMA[kind], LINK="lua/tests/duo/scenario_gen2_link.lua"}
    function S.run(h)
        local link = dofile(h.root .. "/" .. S.LINK)
        h.jitter()
        local arrived, why = h.arrive()
        if not arrived then return false, "no CONTINUE arrival: " .. tostring(why) end
        h.party()
        if not h.wait(function() return h.sent.hello ~= nil end, link.HELLO_FRAMES) then
            return false, "the client never sent hello"
        end
        if not h.wait(h.go, link.GO_FRAMES) then return false, "no go-file" end
        if kind == "full" then
            local played, outcome = h.play({settled=h.link_settled})   -- catch, report, link settled, native save
            if not played then return false, "box catch failed: " .. tostring(outcome) end
        else
            local ok, leg_why = h.synth_leg(kind == "hatch" and M.hatch_driver() or nil)
            if not ok then return false, kind .. " leg failed: " .. tostring(leg_why) end
            if kind == "trade" and not h.wait(function() return acked(h) end, M.ACK_FRAMES) then
                return false, "the server never acked the npc_trade key_change"
            end
            if not h.wait(function() return linked(h) and h.box_idle() end, M.LINK_FRAMES) then
                return false, "the pair never linked"
            end
            local saved, save_why = h.save()
            if not saved then return false, "native save failed: " .. tostring(save_why) end
        end
        h.party()
        local witnessed, witness_why = h.witness()
        if not witnessed then return false, "save witness: " .. tostring(witness_why) end
        h.frames(link.SETTLE_FRAMES)
        local problems, receipt = S.verdict(h.lines, h.json)
        if #problems > 0 then return false, table.concat(problems, "; ") end
        h.jlog("RECEIPT", receipt)
        return true, kind .. " linked " .. receipt.key
    end

    -- Pure: marker lines -> problems (empty = PASS) and the receipt.
    function S.verdict(lines, json)
        local problems, seen, tx, rx = {}, {}, {}, {}
        local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
        for index, line in ipairs(lines) do
            line = tostring(line)
            if line:sub(1, 7) == "RESULT:" then need(false, "a RESULT line precedes the verdict") end
            local tag, body = line:match("^([%u%d_]+) (.*)$")
            if tag and M.JSON_TAGS[tag] then
                local value = json.decode(body)
                if need(type(value) == "table", "malformed " .. tag .. " marker") then
                    seen[tag] = seen[tag] or {}
                    table.insert(seen[tag], {at=index, value=value})
                end
            elseif tag == "TX" then
                tx[#tx + 1] = {at=index, event=body:match('"event"%s*:%s*"([%w_]+)"')}
            elseif tag == "RX" then
                rx[#rx + 1] = {at=index, cmd=body:match("^(%S+)")}
            end
        end
        local function one(tag)
            local rows = seen[tag] or {}
            need(#rows == 1, string.format("%d %s markers (expected one)", #rows, tag))
            return rows[1]
        end
        local head, client, save = one("DUO_GEN2"), one("CLIENT"), one("SAVE_WITNESS")
        one("BOOTED")
        need(head == nil or type(head.value.synth) == "string" and head.value.synth ~= "", "DUO_GEN2 names no synthetic setup")
        need(client == nil or client.value.production_admitted == true, "client is not the production graph")
        local want, capture = M.EXPECT[kind], nil
        for _, row in ipairs(seen.ENGINE_CAPTURE or {}) do
            local c = row.value
            if c.site_id == want.site and c.acquisition == want.acquisition and c.destination == want.destination then
                need(capture == nil, "two " .. want.site .. " captures")
                capture = capture or row
            end
        end
        local key = capture and capture.value.key
        if need(capture ~= nil, "no " .. want.site .. " " .. want.acquisition .. " capture") then
            local area = capture.value.area_id
            need(want.area == nil and type(area) == "string" and area ~= "" and area ~= "nil" or area == want.area,
                 "the capture's area is not " .. tostring(want.area or "a gift area"))
        end
        local sent
        for _, row in ipairs(seen.CAPTURE_SENT or {}) do
            if key ~= nil and row.value.key == key and row.at > capture.at then sent = sent or row end
        end
        need(sent ~= nil, "no capture event sent for the engine capture key")
        local link_at
        for _, row in ipairs(seen.RX_TEXT or {}) do
            local text = tostring(row.value.text)
            if row.value.cmd == "msgbox" and text:sub(-8) == " linked!" and sent and row.at > sent.at then
                link_at = link_at or row.at
            end
        end
        need(link_at ~= nil, "the server never announced the link")
        local change
        if kind == "trade" then
            for _, row in ipairs(seen.ENGINE_KEY_CHANGE or {}) do
                local v = row.value
                if v.reason == "npc_trade" and v.site_id == "npc_trade_finalized" and v.old_key == key and capture
                   and row.at > capture.at then change = change or row end
            end
            if need(change ~= nil, "no npc_trade key_change of the linked hatchling") then
                local tx_at, ack_at
                for _, t in ipairs(tx) do if t.event == "key_change" and t.at > change.at then tx_at = tx_at or t.at end end
                for _, r in ipairs(rx) do if r.cmd == "key_change_ack" and tx_at and r.at > tx_at then ack_at = ack_at or r.at end end
                need(tx_at ~= nil and ack_at ~= nil, "the key_change was not sent and acked")
            end
        else
            need((seen.ENGINE_KEY_CHANGE or {})[1] == nil, "an unexpected key_change")
        end
        for _, r in ipairs(rx) do
            need(r.cmd ~= "force_faint" and r.cmd ~= "memorialize", "a death command arrived: " .. tostring(r.cmd))
        end
        if save then
            local s = save.value
            need(s.flushed_matches == true and type(s.gate_saves) == "number" and s.gate_saves >= 1
                 and type(s.client_saves) == "number" and s.client_saves >= 1, "save witness incomplete")
            need(link_at ~= nil and save.at > link_at and (change == nil or save.at > change.at),
                 "the save came before the link or the trade")
        end
        if #problems > 0 then return problems, nil end
        local h = head.value
        return problems, {schema=M.SCHEMA[kind], player=h.player, scenario=h.scenario, attempt=h.attempt, case=h.case,
            synth=h.synth, title=h.title, rom_sha1=h.rom_sha1, fixture_sha256=h.fixture_sha256,
            key=change and change.value.new_key or key, capture=capture.value, key_change=change and change.value or nil,
            save=save.value, client=client.value, input_mode="normal_buttons", harness_write_scopes=json.array({})}
    end
    return S
end

return M
