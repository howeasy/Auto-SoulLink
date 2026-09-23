--[[
  lua/tests/duo/scenario_gen2_reconnect.lua -- the gen2_new `reconnect` scenario (C-2, D-14, C-6g reconnect).

  Gen 1 reference: reconnect_new (duo_gen1_main.lua scenarios.reconnect_new, e2e_duo.py assert_reconnect_new /
  assert_reconnect_saved). Three legs, told apart by SLINK_DUO.phase:
    initial     both halves play the `link` scenario body unchanged (CONTINUE, hello, go-file, one Route 29
                catch, native save + flush), then print RECONNECT_READY. A then idles until the runner KILLS
                its EmuHawk (never a RESULT line; a missed kill ends in the scenario timeout = FAIL). B stays
                online until the runner appends B_DONE to B's go-file, and must have sent no second hello and
                received no force_faint/box_mon since RECONNECT_READY.
    same_save   A relaunched on its OWN flushed link save (SLINK_DUO.expected_key = A's linked key): CONTINUE,
                one hello, the linked key is in the party, then the runner appends A_DONE_SAME.
    wrong_save  A relaunched on another OT's battle save (qualified input: crystal_battle_ot2, F-6's wrong-save
                control): CONTINUE, one hello, the server's "[x] WRONG SAVE: slot A" hud text arrives after
                it, the linked key is absent, then the runner appends A_DONE_WRONG.
  Every relaunch is a normal warm boot of the staged save: the runner stages it into the instance's
  SLINK_GEN2_SAVERAM_DIR and passes a SLINK_GEN2_QUALIFY stage "boot" whose stage_fingerprint is that save's
  sha256 and a <title>_battle fixture case (fresh attempt_id); the driver itself never writes a byte.

  MARKER CONTRACT (duo_gen2_main.lua prints the shared ones; JSON after the tag unless noted):
    initial     everything `link` prints except RECEIPT, in its order (DUO_GEN2 CLIENT BOOTED MYKEY HELLO
                ENGINE_CAPTURE CAPTURE_SENT CAUGHT SAVE_WITNESS), then
                RECONNECT_READY {frame, phase="initial", player, key}   key = CAUGHT key; after SAVE_WITNESS
                B only: B_STAYED {frame, hellos, force_faint, box_mon}   after B_DONE; hellos=1 (the initial
                        one, no HELLO_AGAIN ever), force_faint=box_mon=0 counted over RX since RECONNECT_READY
                B only: RECEIPT {schema "gen2-duo-reconnect-v1", phase "initial", ...link receipt fields}
    relaunch    DUO_GEN2 CLIENT BOOTED MYKEY.. HELLO (exactly one; no HELLO_AGAIN), then
                RECONNECT_HELLO {frame, phase, hellos, ot_id, expected_key, linked}   linked = expected_key is in
                        the party (same_save: true; wrong_save: false)
                wrong_save only: RX hud_show, RX_TEXT {cmd "hud_show", text "[x] WRONG SAVE: slot A"} after HELLO,
                        then WRONG_SAVE_HUD {frame, text}
                no RX force_faint / RX box_mon line at all
                RECEIPT {schema "gen2-duo-reconnect-v1", phase, expected_key, linked, ot_id, ...}
    RESULT: PASS|FAIL   last line (never printed by A's killed initial leg)
  go-file markers the runner appends: B_DONE (B's file), A_DONE_SAME / A_DONE_WRONG (A's relaunch file).
  links.json / events / identity invariants across the kill and both relaunches are the lane oracle's.
  S.verdict re-reads these lines and is the only way to a PASS.
--]]
local S = {}
S.RECEIPT_SCHEMA = "gen2-duo-reconnect-v1"
-- ponytail: live bounds, not measured; raise if a lane needs longer.
S.HELLO_FRAMES = 3600
S.GO_FRAMES = 54000
S.PARTNER_FRAMES = 216000  -- B: both A relaunches (boot + CONTINUE + runner checks) before B_DONE
S.DONE_FRAMES = 18000      -- relaunch: the runner's server checks before A_DONE_*
S.HUD_FRAMES = 600         -- wrong_save: hello -> the WRONG SAVE hud
S.SETTLE_FRAMES = 120
S.KEY = "^%x%x%x%x:%x%x%x%x:%x%x$"
S.LINK = "lua/tests/duo/scenario_gen2_link.lua"
S.PHASES = {initial=true, same_save=true, wrong_save=true}
S.DONE = {same_save="A_DONE_SAME", wrong_save="A_DONE_WRONG"}
S.JSON_TAGS = {DUO_GEN2=true, CLIENT=true, BOOTED=true, HELLO=true, HELLO_AGAIN=true, ENGINE_CAPTURE=true,
               SAVE_WITNESS=true, RECONNECT_READY=true, B_STAYED=true, RECONNECT_HELLO=true, RX_TEXT=true,
               WRONG_SAVE_HUD=true}
S.WRONG_SAVE = "[x] WRONG SAVE: slot A"

local function count_rx(h, from, cmd)
    local n = 0
    for i = from + 1, #h.rec.rx do if h.rec.rx[i].cmd == cmd then n = n + 1 end end
    return n
end

local function relaunch(h)
    local phase, key = h.phase, h.expected_key
    if type(key) ~= "string" or not key:match(S.KEY) then return false, "relaunch needs SLINK_DUO.expected_key" end
    h.jitter()
    local arrived, why = h.arrive()
    if not arrived then return false, "no CONTINUE arrival: " .. tostring(why) end
    h.party()
    if not h.wait(function() return h.sent.hello ~= nil end, S.HELLO_FRAMES) then
        return false, "relaunch did not hello from a live save"
    end
    local linked = h.slot_of(key) ~= nil
    h.jlog("RECONNECT_HELLO", {frame=h.frame(), phase=phase, hellos=#h.rec.hellos, ot_id=h.sent.hello.ot_id,
                               expected_key=key, linked=linked})
    if phase == "same_save" and not linked then return false, "same-save relaunch lost the linked key" end
    if phase == "wrong_save" then
        if linked then return false, "the wrong save holds the linked key" end
        local hud
        if not h.wait(function()
            for i = #h.lines, 1, -1 do
                local body = h.lines[i]:match("^RX_TEXT (.*)$")
                local v = body and h.json.decode(body)
                if v and v.text and v.text:find("WRONG SAVE", 1, true) then hud = v return true end
            end
            return false
        end, S.HUD_FRAMES) then return false, "wrong-save relaunch did not receive the WRONG SAVE hud" end
        h.jlog("WRONG_SAVE_HUD", {frame=h.frame(), text=hud.text})
    end
    if not h.wait(function() return h.file_has(h.go_file, S.DONE[phase]) end, S.DONE_FRAMES) then
        return false, "runner did not finish reconnect phase " .. phase
    end
    h.frames(S.SETTLE_FRAMES)
    return true
end

function S.run(h)
    if not S.PHASES[h.phase] then return false, "unknown reconnect phase " .. tostring(h.phase) end
    local link = dofile(h.root .. "/" .. S.LINK)
    if h.phase ~= "initial" then
        if h.player ~= "a" then return false, "only A relaunches" end
        local ok, why = relaunch(h)
        if not ok then return false, why end
    else
        h.jitter()
        local arrived, why = h.arrive()
        if not arrived then return false, "no CONTINUE arrival: " .. tostring(why) end
        h.party()
        if not h.wait(function() return h.sent.hello ~= nil end, S.HELLO_FRAMES) then return false, "the client never sent hello" end
        if not h.wait(h.go, S.GO_FRAMES) then return false, "no go-file" end
        local played, outcome = h.play({settled=h.link_settled})
        if not played then return false, "link route failed: " .. tostring(outcome) end
        h.party()
        local witnessed, witness_why = h.witness()
        if not witnessed then return false, "save witness: " .. tostring(witness_why) end
        local problems = link.verdict(h.lines, h.json)
        if #problems > 0 then return false, "link prerequisite failed: " .. table.concat(problems, "; ") end
        local key, mark = h.rec.caught, #h.rec.rx
        h.jlog("RECONNECT_READY", {frame=h.frame(), phase="initial", player=h.player, key=key})
        if h.player == "a" then
            while true do h.frames(60) end   -- the runner kills ONLY this EmuHawk
        end
        if not h.wait(function() return h.file_has(h.go_file, "B_DONE") end, S.PARTNER_FRAMES) then
            return false, "B never got reconnect completion"
        end
        h.jlog("B_STAYED", {frame=h.frame(), hellos=#h.rec.hellos, force_faint=count_rx(h, mark, "force_faint"),
                            box_mon=count_rx(h, mark, "box_mon")})
    end
    local problems, receipt = S.verdict(h.lines, h.json, link.verdict)
    if #problems > 0 then return false, table.concat(problems, "; ") end
    h.jlog("RECEIPT", receipt)
    return true, h.phase == "initial" and "B remained online through both A relaunches"
                 or (h.phase .. " hello observed once")
end

-- Pure: marker lines -> problems (empty = PASS) and the receipt. link_verdict = scenario_gen2_link's S.verdict.
function S.verdict(lines, json, link_verdict)
    local problems, seen, rx = {}, {}, {}
    local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
    for index, line in ipairs(lines) do
        line = tostring(line)
        local tag, body = line:match("^([%u%d_]+) (.*)$")
        if tag == "RX" then
            rx[#rx + 1] = {at=index, cmd=body:match("^(%S+)")}
        elseif tag and S.JSON_TAGS[tag] then
            local value = json.decode(body)
            if need(type(value) == "table", "malformed " .. tag .. " marker") then
                seen[tag] = seen[tag] or {}
                table.insert(seen[tag], {at=index, value=value})
            end
        end
    end
    local function rows(tag) return seen[tag] or {} end
    local function one(tag)
        local r = rows(tag)
        need(#r == 1, #r == 0 and ("missing " .. tag .. " marker") or string.format("%d %s markers (expected one)", #r, tag))
        return r[1]
    end
    local function rx_after(at, cmd)
        local n = 0
        for _, r in ipairs(rx) do if r.at > at and r.cmd == cmd then n = n + 1 end end
        return n
    end
    need(#rows("HELLO_AGAIN") == 0, "a second hello went out")
    local receipt
    if #rows("RECONNECT_HELLO") > 0 then
        for _, line in ipairs(lines) do
            if tostring(line):sub(1, 7) == "RESULT:" then need(false, "a RESULT line precedes the verdict") end
        end
        local head, client, hello, back = one("DUO_GEN2"), one("CLIENT"), one("HELLO"), one("RECONNECT_HELLO")
        one("BOOTED")
        need(client == nil or client.value.production_admitted == true, "client is not the production graph")
        need(#rows("ENGINE_CAPTURE") == 0 and #rows("RECONNECT_READY") == 0, "a relaunch played the link leg")
        need(rx_after(0, "force_faint") == 0 and rx_after(0, "box_mon") == 0, "A relaunch received force_faint/box_mon")
        local detail = {}
        if back then
            local b = back.value
            need(head ~= nil and head.value.player == "a", "only A relaunches")
            need(type(b.expected_key) == "string" and b.expected_key:match(S.KEY) ~= nil, "relaunch names no expected key")
            need(b.hellos == 1 and hello ~= nil and back.at > hello.at, "RECONNECT_HELLO is not after the one hello")
            if b.phase == "same_save" then
                need(b.linked == true, "same-save relaunch lost the linked key")
                need(#rows("WRONG_SAVE_HUD") == 0, "the same save was refused")
            elseif b.phase == "wrong_save" then
                need(b.linked == false, "the wrong save holds the linked key")
                local hud = one("WRONG_SAVE_HUD")
                local wrong
                for _, r in ipairs(rows("RX_TEXT")) do
                    if r.value.cmd == "hud_show" and r.value.text == S.WRONG_SAVE then wrong = wrong or r end
                end
                need(wrong ~= nil and hello ~= nil and wrong.at > hello.at, "no WRONG SAVE hud after the hello")
                need(hud ~= nil and hud.value.text == S.WRONG_SAVE and hud.at > back.at, "WRONG_SAVE_HUD missing or early")
            else
                need(false, "unknown relaunch phase " .. tostring(b.phase))
            end
            detail = {phase=b.phase, expected_key=b.expected_key, linked=b.linked, ot_id=b.ot_id}
        end
        if #problems > 0 then return problems, nil end
        local h = head.value
        receipt = {schema=S.RECEIPT_SCHEMA, player=h.player, scenario=h.scenario, attempt=h.attempt, case=h.case,
                   title=h.title, rom_sha1=h.rom_sha1, fixture_sha256=h.fixture_sha256, hello=hello.value,
                   client=client.value, input_mode="normal_buttons", harness_write_scopes=json.array({})}
        for k, v in pairs(detail) do receipt[k] = v end
        return problems, receipt
    end
    local link_problems, link_receipt = link_verdict(lines, json)
    for _, p in ipairs(link_problems) do problems[#problems + 1] = p end
    local capture, save, ready = rows("ENGINE_CAPTURE")[1], rows("SAVE_WITNESS")[1], one("RECONNECT_READY")
    if ready then
        need(capture ~= nil and ready.value.key == capture.value.key, "RECONNECT_READY names another key than the catch")
        need(save ~= nil and ready.at > save.at, "RECONNECT_READY before the link save")
    end
    local head = rows("DUO_GEN2")[1]
    if head and head.value.player == "b" then
        local stayed = one("B_STAYED")
        if stayed then
            local s = stayed.value
            need(ready ~= nil and stayed.at > ready.at, "B_STAYED before RECONNECT_READY")
            need(s.hellos == 1, "B helloed more than once")
            need(s.force_faint == 0 and s.box_mon == 0 and ready ~= nil and rx_after(ready.at, "force_faint") == 0
                 and rx_after(ready.at, "box_mon") == 0, "B received force_faint/box_mon across A's reconnect")
        end
    end
    if #problems > 0 then return problems, nil end
    receipt = link_receipt
    receipt.schema, receipt.phase, receipt.ready = S.RECEIPT_SCHEMA, "initial", ready.value
    return problems, receipt
end

return S
