--[[
  lua/tests/duo/scenario_gen2_link.lua -- the gen2_new `link` scenario body + its verdict (card gen2-H1).

  One half of the first Crystal<->Crystal link (docs/gen2/reviews/P3B7_PLAN_CODEX_2026-09-23.md
  "smallest PHYSICAL milestone"): arrive by CONTINUE, hello, wait for the runner's go-file, catch one
  wild mon on Route 29 with normal buttons, let the client report it, save natively and flush. The
  server-side link (both captures -> the route_29 link) is the independent oracle's job
  (tools/gen2_duo_oracles.py); this half only reports what it observed.

  S.verdict re-reads the MARKER LINES this instance printed (duo_gen2_main.lua's header defines them)
  and is the only way to a PASS: CAUGHT needs an engine capture (the binder's capture event, emitted at
  capture_party_finalized, whose latch requires the capture_party site hit) and a sent `capture` with
  the same key; the save needs the gate's native save_completed site, the production client's
  save_completed observation and a flushed SaveRAM equal to the live CartRAM. A missing, reordered or
  duplicated marker is a FAIL.
--]]
local S = {}
S.RECEIPT_SCHEMA = "gen2-duo-link-v1"
-- ponytail: live bounds, not measured; raise if a lane needs longer.
S.HELLO_FRAMES = 3600
S.GO_FRAMES = 54000      -- 900 s at 60 fps, Gen 1's go-file bound
S.SETTLE_FRAMES = 120    -- let the client drain its socket before exit
S.CART_RAM_BYTES = 0x8000
S.KEY = "^%x%x%x%x:%x%x%x%x:%x%x$"
S.JSON_TAGS = {DUO_GEN2=true, CLIENT=true, BOOTED=true, HELLO=true, ENGINE_CAPTURE=true, CAPTURE_SENT=true,
               SAVE_WITNESS=true, RECEIPT=true}

-- h: the per-instance harness duo_gen2_main.lua builds (log/jlog, lines, arrive, party, wait, go,
-- play, witness, frames, jitter, sent.hello, json).
function S.run(h)
    h.jitter()
    local arrived, why = h.arrive()
    if not arrived then return false, "no CONTINUE arrival: " .. tostring(why) end
    h.party()
    if not h.wait(function() return h.sent.hello ~= nil end, S.HELLO_FRAMES) then
        return false, "the client never sent hello"
    end
    if not h.wait(h.go, S.GO_FRAMES) then return false, "no go-file" end
    local played, outcome = h.play()
    if not played then return false, "route failed: " .. tostring(outcome) end
    h.party()
    local witnessed, witness_why = h.witness()
    if not witnessed then return false, "save witness: " .. tostring(witness_why) end
    h.frames(S.SETTLE_FRAMES)
    local problems, receipt = S.verdict(h.lines, h.json)
    if #problems > 0 then return false, table.concat(problems, "; ") end
    h.jlog("RECEIPT", receipt)
    return true, "caught " .. receipt.key
end

local function fmt_count(tag, n)
    return n == 0 and ("missing " .. tag .. " marker") or string.format("%d %s markers (expected one)", n, tag)
end

-- Pure: the marker lines -> problems (empty = PASS) and the receipt.
function S.verdict(lines, json)
    local problems, seen = {}, {}
    local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
    for index, line in ipairs(lines) do
        local tag, body = tostring(line):match("^([%u%d_]+) (.*)$")
        if tostring(line):sub(1, 7) == "RESULT:" then need(false, "a RESULT line precedes the verdict") end
        if tag and (S.JSON_TAGS[tag] or tag == "CAUGHT") then
            local value = body
            if S.JSON_TAGS[tag] then value = json.decode(body) end
            if need(type(value) == "table" or tag == "CAUGHT", "malformed " .. tag .. " marker") then
                seen[tag] = seen[tag] or {}
                table.insert(seen[tag], {at=index, value=value})
            end
        end
    end
    local function one(tag)
        local rows = seen[tag] or {}
        need(#rows == 1, fmt_count(tag, #rows))
        return rows[1]
    end
    local head, client, booted, hello = one("DUO_GEN2"), one("CLIENT"), one("BOOTED"), one("HELLO")
    local capture, caught, save = one("ENGINE_CAPTURE"), one("CAUGHT"), one("SAVE_WITNESS")
    need(client == nil or client.value.production_admitted == true, "client is not the production graph")
    local key = capture and capture.value.key
    if capture then
        local c = capture.value
        need(c.site_id == "capture_party_finalized" and c.acquisition == "wild" and c.destination == "party",
             "engine capture is not a wild party catch at capture_party_finalized")
        need(type(key) == "string" and key:match(S.KEY) ~= nil, "engine capture key malformed")
    end
    local sent
    for _, row in ipairs(seen.CAPTURE_SENT or {}) do
        if key ~= nil and row.value.key == key then sent = row end
    end
    need(sent ~= nil, "no capture event sent for the engine capture key")
    if caught then
        need(caught.value == key, "CAUGHT names another key than the engine capture")
        need(capture ~= nil and sent ~= nil and caught.at > capture.at and caught.at > sent.at,
             "CAUGHT printed before the engine capture and its send")
    end
    if capture and sent then need(sent.value.frame >= capture.value.frame, "capture sent before the engine capture") end
    if save then
        local s = save.value
        need(s.flushed_matches == true and s.cartram_bytes == S.CART_RAM_BYTES
             and type(s.cartram_sha256) == "string" and #s.cartram_sha256 == 64 and s.cartram_sha256:match("^%x+$") ~= nil
             and type(s.saveram_path) == "string" and s.saveram_path ~= "", "save witness incomplete")
        need(type(s.gate_saves) == "number" and s.gate_saves >= 1, "native save_completed site never fired")
        need(type(s.client_saves) == "number" and s.client_saves >= 1, "production client never observed save_completed")
        need(caught ~= nil and save.at > caught.at, "save witness printed before CAUGHT")
        need(sent ~= nil and type(s.save_completed_frame) == "number" and s.save_completed_frame > sent.value.frame,
             "native save completed before the capture was sent")
    end
    if #problems > 0 then return problems, nil end
    local h = head.value
    return problems, {schema=S.RECEIPT_SCHEMA, player=h.player, scenario=h.scenario, attempt=h.attempt,
        case=h.case, title=h.title, rom_sha1=h.rom_sha1, fixture_sha256=h.fixture_sha256, key=key,
        booted=booted.value, hello=hello.value, capture=capture.value, save=save.value, client=client.value,
        input_mode="normal_buttons", harness_write_scopes=json.array({})}
end

return S
