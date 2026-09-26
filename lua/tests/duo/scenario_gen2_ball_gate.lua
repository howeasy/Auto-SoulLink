--[[
  lua/tests/duo/scenario_gen2_ball_gate.lua -- the gen2_new `ball_gate` scenario (D-2). Gen 1 reference: ball_gate_new
  (duo_gen1_main.lua). Facts: docs/gen2/reviews/DUO_WAVE_D_FACTS_2026-09-24.md section 1.

  Both halves boot a ZERO-Ball town fixture (C<->C crystal_town + crystal_town_ot2, G<->S gold_town + silver_town;
  Elm's lab after the starter) with the errand route facts, and play with normal buttons only (no O-10, no harness
  write, no SYNTH field):
    pre    lab -> Route 29 grass (gen2_ball_gate_inputs.lua "pre"), one wild encounter, RUN  -> BALL_PRE
           (the client withholds no_catch without Balls: route_29 must stay open on the server)
    post   the errand (gen2_scripted_play.lua): Mr. Pokemon, the unavoidable Cherrygrove rival lost on purpose
           (BATTLETYPE_CANLOSE: a natural pre-Ball faint the server must suppress, state.py FAINT GATE), Elm, the
           aide's natural 5 Poke Balls, back to Route 29 grass                                    -> BALL_FLIP
           once the production client's has_pokeballs flipped (its Ball-pocket read; bag_ball_received is not a
           proven site)
    link   the `link` catch on Route 29 (the first post-Ball encounter), the link settles, native save.
  MARKER CONTRACT: everything scenario_gen2_link.lua checks, plus
    HELLO {frame, ot_id, has_pokeballs, ball_count}            the first hello: has_pokeballs=false, ball_count=0
    BALL_PRE {frame, foe, area_id, has_pokeballs, ball_count}  after the pre-Ball RUN: false / 0 / "route_29"
    ENGINE_FAINT + FAINT_SENT for the starter key (the rival loss), both before BALL_FLIP
    BALL_FLIP {frame, has_pokeballs, ball_count}              true / 1..5 (the aide's stack only), before the catch
    no TX no_catch|capture before BALL_FLIP, no RX force_faint|memorialize at all
    RECEIPT {schema "gen2-duo-ball-gate-v1", ...link receipt, pre_ball, faint, flip, synth=[]}
  The server half (pokeballs_obtained, the route_29 pair, the suppressed faint) is tools/gen2_duo_oracles.py
  ball_gate_oracle's job.
--]]
local S = {}
S.RECEIPT_SCHEMA = "gen2-duo-ball-gate-v1"
S.TOWN = true        -- duo_gen2_main.lua: this scenario boots a <title>_town fixture
S.BALL_GATE = true   -- duo_gen2_main.lua: h.ball_gate_leg
S.LINK = "lua/tests/duo/scenario_gen2_link.lua"
S.AIDE_BALLS = 5
S.FLIP_FRAMES = 600  -- ponytail: the tick after the aide's giveitem; raise if a lane lags
S.JSON_TAGS = {HELLO=true, BALL_PRE=true, BALL_FLIP=true, ENGINE_FAINT=true, FAINT_SENT=true, ENGINE_CAPTURE=true}

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
    local ok, leg_why = h.ball_gate_leg("pre")
    if not ok then return false, "pre-Ball leg: " .. tostring(leg_why) end
    local met, foe = h.encounter()
    if not met then return false, "pre-Ball encounter: " .. tostring(foe) end
    local fled, flee_why = h.flee()
    if not fled then return false, "pre-Ball flee: " .. tostring(flee_why) end
    h.jlog("BALL_PRE", {frame=h.frame(), foe=foe, area_id=h.rec.wild_area, has_pokeballs=h.client.has_pokeballs == true,
                        ball_count=h.ball_count()})
    ok, leg_why = h.ball_gate_leg("post")
    if not ok then return false, "errand leg: " .. tostring(leg_why) end
    if not h.wait(function() return h.client.has_pokeballs == true end, S.FLIP_FRAMES) then
        return false, "the client never activated after the aide's Balls"
    end
    h.jlog("BALL_FLIP", {frame=h.frame(), has_pokeballs=true, ball_count=h.ball_count()})
    -- fsw-sweep3/-rr1/-rr2: the aide's five natural Balls are a hard floor (no weakening, full-HP throws only)
    -- against a fully deterministic committed fixture and script -- neither cross-player jitter nor a
    -- different pinned RTC minute changes the outcome, so a losing ~13% five-miss streak reproduces on every
    -- retry. weaken (F.driver's proven U1f-gate fix, gen2_frame_align.lua) lands one damaging hit on the still
    -- full-HP foe first: PokeBallEffect's catch rate rises as the foe's HP falls (engine/items/item_effects.asm).
    -- the weaken hit must not itself be a status move (gen2_faint_inputs.lua's proven passive list)
    local passive = dofile(h.root .. "/lua/tests/duo/gen2_faint_inputs.lua").PASSIVE_MOVES
    local played, outcome = h.play({settled=h.link_settled, weaken=true, passive=passive})
    if not played then return false, "link catch failed: " .. tostring(outcome) end
    h.party()
    local witnessed, witness_why = h.witness()
    if not witnessed then return false, "save witness: " .. tostring(witness_why) end
    h.frames(link.SETTLE_FRAMES)
    local problems, receipt = S.verdict(h.lines, h.json, link.verdict)
    if #problems > 0 then return false, table.concat(problems, "; ") end
    h.jlog("RECEIPT", receipt)
    return true, "pre-Ball encounter and faint withheld; aide's Balls opened the gate; caught " .. receipt.key
end

-- Pure: marker lines -> problems (empty = PASS) and the receipt. link_verdict = scenario_gen2_link's S.verdict.
function S.verdict(lines, json, link_verdict)
    local problems, link_receipt = link_verdict(lines, json)
    local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
    local seen, tx, rx, starter = {}, {}, {}, nil
    for index, line in ipairs(lines) do
        line = tostring(line)
        local tag, body = line:match("^([%u%d_]+) (.*)$")
        if tag and S.JSON_TAGS[tag] then
            local value = json.decode(body)
            if need(type(value) == "table", "malformed " .. tag .. " marker") then
                seen[tag] = seen[tag] or {}
                table.insert(seen[tag], {at=index, value=value})
            end
        elseif tag == "TX" then
            tx[#tx + 1] = {at=index, event=body:match('"event"%s*:%s*"([%w_]+)"')}
        elseif tag == "RX" then
            rx[#rx + 1] = {at=index, cmd=body:match("^(%S+)")}
        elseif tag == "MYKEY" and starter == nil then
            starter = body:match("^0 (%S+)$")
        end
    end
    local function one(tag)
        local rows = seen[tag] or {}
        need(#rows == 1, string.format("%d %s markers (expected one)", #rows, tag))
        return rows[1]
    end
    local hello = (seen.HELLO or {})[1]
    local pre, flip = one("BALL_PRE"), one("BALL_FLIP")
    local capture = (seen.ENGINE_CAPTURE or {})[1]
    if hello then
        need(hello.value.has_pokeballs == false and hello.value.ball_count == 0, "the first hello already had Poke Balls")
    end
    if pre then
        local p = pre.value
        need(p.has_pokeballs == false and p.ball_count == 0 and p.area_id == "route_29"
             and type(p.foe) == "number" and p.foe >= 1 and p.foe <= 251,
             "pre-Ball encounter is not a zero-Ball route_29 wild battle")
        need(hello ~= nil and pre.at > hello.at, "pre-Ball encounter before the hello")
    end
    if flip then
        local f = flip.value
        need(f.has_pokeballs == true and type(f.ball_count) == "number" and f.ball_count >= 1
             and f.ball_count <= S.AIDE_BALLS, "Ball flip is not the aide's natural stack")
        need(pre ~= nil and flip.at > pre.at, "Ball flip before the pre-Ball encounter")
        need(capture ~= nil and capture.at > flip.at, "the catch came before the Ball flip")
        for _, t in ipairs(tx) do
            need(not (t.at < flip.at and (t.event == "no_catch" or t.event == "capture")),
                 "the client sent " .. tostring(t.event) .. " before the first Ball")
        end
    end
    -- the natural pre-Ball faint (the Cherrygrove rival loss): engine faint + its send, both before the flip
    local faint
    for _, row in ipairs(seen.ENGINE_FAINT or {}) do
        local v = row.value
        if v.site_id == "battle_faint" and v.cause == "battle" and v.key == starter and flip and row.at < flip.at
           and v.frame < flip.value.frame then faint = faint or row end
    end
    local sent
    for _, row in ipairs(seen.FAINT_SENT or {}) do
        if faint and row.value.key == starter and row.at > faint.at and flip and row.at < flip.at then sent = sent or row end
    end
    need(faint ~= nil and sent ~= nil, "no pre-Ball faint of the starter reached the wire")
    for _, r in ipairs(rx) do
        need(r.cmd ~= "force_faint" and r.cmd ~= "memorialize", "a death command arrived: " .. tostring(r.cmd))
    end
    if #problems > 0 then return problems, nil end
    local receipt = {}
    for k, v in pairs(link_receipt) do receipt[k] = v end
    receipt.schema, receipt.pre_ball, receipt.flip, receipt.faint = S.RECEIPT_SCHEMA, pre.value, flip.value, faint.value
    receipt.synth = json.array({})   -- O-33: no synthetic setup field in this scenario
    return problems, receipt
end

return S
