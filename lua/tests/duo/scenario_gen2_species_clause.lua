--[[
  lua/tests/duo/scenario_gen2_species_clause.lua -- the gen2_new `species_clause` scenario (D-4/D-5 species, the
  dupes reroll). Gen 1 reference: species_clause_new (duo_gen1_main.lua), ORDERED. Route 29 facts with file:line
  citations: gen2_clause.lua (on Route 29 "same family" == "same species byte": five distinct base forms, none
  evolves at L2-4).

  Server started with --species-clause.
    A   the `link` body: catch one Route 29 mon (its capture goes PENDING on the area), save natively, print
        PENDING_CAPTURE, wait for the link to form, save natively again.
    B   waits for the runner's "A_PENDING species=<n>" in its go-file (n = A's PENDING_CAPTURE species_id, written
        once /api/status shows A's pending capture), then walks into wild battles (gen2_route29_inputs.lua
        R.encounter: stop at the BattleMenu with wEnemyMonSpecies). B decides from ITS OWN cartridge:
          foe == n   RUN (R.flee). The server already queued the dupes reroll at this battle's start: the client's
                     first in_battle tick carries enemy_party (lua/gen2/client.lua send_tick :749-773) ->
                     server/server.py:2026-2044 check_dupe_on_encounter -> state.py:1843-1930 "check 2" (the
                     partner's pending capture on this area, same family) -> _dupes_reroll :1830-1841: gui_prompt
                     "Dupes clause: <Name> -- reroll!" + unresolve_area; the RUN's no_catch is then absorbed
                     (state.py:1973-1977, no dead zone). The prompt is required after the RUN (a RUN with no
                     prompt = the server missed the reroll = FAIL); the cursor is taken before the encounter.
          foe != n   catch it (R.new's route, the `link` catch + native save); the link forms.
        At most MAX_BATTLES battles; only duplicates within that budget is the game's RNG ("RNG: ..." FAIL, the
        lane retries like Gen 1's). P(first foe is A's species) is that species' Route 29 share (gen2_clause.lua:
        e.g. Pidgey 50% on Crystal day, Hoothoot 85% on G/S nite); a non-duplicate first encounter PASSes with
        path "reroll_unobserved" (the lane may retry for "reroll_observed").
  B's RUN needs no new engine site: BattleMenu RUN over the proven BATTLE_MENU_GRID, battle_end is proven.

  MARKER CONTRACT (everything `link` prints except RECEIPT; JSON after the tag):
    A   PENDING_CAPTURE {frame, key, species_id, area_id}   after CAUGHT (and the first native save)
        LINKED {frame, text}         the "<A> and <B> linked!" msgbox (RX msgbox + RX_TEXT) after PENDING_CAPTURE
    B   A_PENDING {frame, species_id}                        before any encounter
        ENCOUNTER {frame, n, species_id, dupe}               per battle, n = 1.., dupe = (species_id == A's)
        REROLL {frame, n, species_id, prompt}                after a dupe ENCOUNTER's RUN: RX gui_prompt + RX_TEXT
                                                             "Dupes clause: <Name> -- reroll!" for that species
        the last ENCOUNTER is the non-dupe B catches (ENGINE_CAPTURE species_id == it), then LINKED
    both  no RX force_faint for the own key, no "[x] Species clause"/"[x] Dup" prompt, no "... is a dead zone!"
          msgbox; SAVE_WITNESS (the final native save) after LINKED
          RECEIPT {schema "gen2-duo-species-clause-v1", role "pending"|"reroller", dupe_species, rerolls, path}
    RESULT: PASS|FAIL
  go-files: both need the go-file; B's must also carry "A_PENDING species=<n>".
--]]
local here = debug.getinfo(1, "S").source:match("^@(.*[/\\])") or ""
local K = dofile(here .. "gen2_clause.lua")
local S = {}
S.RECEIPT_SCHEMA = "gen2-duo-species-clause-v1"
-- ponytail: live bounds, not measured; raise if a lane needs longer.
S.HELLO_FRAMES = 3600
S.GO_FRAMES = 54000
S.PENDING_FRAMES = 54000   -- B: A's whole hunt before A_PENDING
S.LINK_FRAMES = 120000     -- A: B's whole reroll hunt before the link
S.PROMPT_FRAMES = 600      -- B: the dupes prompt after the RUN
S.MAX_BATTLES = 8          -- Gen 1's D-4-2 bound
S.SETTLE_FRAMES = 120

local function dupes_text(species)
    local mon = K.SPECIES[species]
    return mon and ("Dupes clause: " .. mon.name .. " -- reroll!")
end
local function count_prompts(h)
    local n = 0
    for _, r in ipairs(h.rec.rx) do
        if r.cmd == "gui_prompt" and type(r.text) == "string" and r.text:sub(1, 14) == "Dupes clause: " then n = n + 1 end
    end
    return n
end
local function linked_text(h)
    for _, r in ipairs(h.rec.rx) do if r.cmd == "msgbox" and K.is_link_text(r.text) then return r.text end end
end

local function hunt(h)
    if not h.wait(function() return h.file_has(h.go_file, "A_PENDING") end, S.PENDING_FRAMES) then
        return false, "runner never released B (A_PENDING)"
    end
    local f = io.open(h.go_file, "r")
    local dupe = tonumber((f and f:read("a") or ""):match("A_PENDING species=(%d+)") or "")
    if f then f:close() end
    h.jlog("A_PENDING", {frame=h.frame(), species_id=dupe})
    if not K.SPECIES[dupe] then return false, "A_PENDING carried no Route 29 species" end
    for battle = 1, S.MAX_BATTLES do
        local before = count_prompts(h)
        local met, foe = h.encounter()
        if not met then return false, "encounter: " .. tostring(foe) end
        h.jlog("ENCOUNTER", {frame=h.frame(), n=battle, species_id=foe, dupe=foe == dupe})
        if foe ~= dupe then
            local played, outcome = h.play()
            if not played then return false, "catch route failed: " .. tostring(outcome) end
            return true
        end
        local fled, why = h.flee()
        if not fled then return false, "flee: " .. tostring(why) end
        if not h.wait(function() return count_prompts(h) > before end, S.PROMPT_FRAMES) then
            return false, string.format("no dupes-clause prompt for species %d (A's)", foe)
        end
        h.jlog("REROLL", {frame=h.frame(), n=battle, species_id=foe, prompt=dupes_text(foe)})
    end
    return false, "RNG: the species hunt met only duplicates within its battle budget"
end

function S.run(h)
    h.jitter()
    local arrived, why = h.arrive()
    if not arrived then return false, "no CONTINUE arrival: " .. tostring(why) end
    h.party()
    if not h.wait(function() return h.sent.hello ~= nil end, S.HELLO_FRAMES) then return false, "the client never sent hello" end
    if not h.wait(h.go, S.GO_FRAMES) then return false, "no go-file" end
    if h.player == "a" then
        local played, outcome = h.play()
        if not played then return false, "link route failed: " .. tostring(outcome) end
        local key, cap = h.rec.caught, h.rec.capture
        if not key or not cap then return false, "no reported catch" end
        h.jlog("PENDING_CAPTURE", {frame=h.frame(), key=key, species_id=cap.species_id, area_id=cap.area_id})
    else
        local ok, hunt_why = hunt(h)
        if not ok then return false, hunt_why end
    end
    h.party()
    if not h.wait(function() return linked_text(h) ~= nil end, S.LINK_FRAMES) then return false, "the link never formed" end
    h.jlog("LINKED", {frame=h.frame(), text=linked_text(h)})
    local saved, save_why = h.save()
    if not saved then return false, "final save failed: " .. tostring(save_why) end
    local witnessed, witness_why = h.witness()
    if not witnessed then return false, "save witness: " .. tostring(witness_why) end
    h.frames(S.SETTLE_FRAMES)
    local problems, receipt = S.verdict(h.lines, h.json, dofile(h.root .. "/" .. K.LINK).verdict)
    if #problems > 0 then return false, table.concat(problems, "; ") end
    h.jlog("RECEIPT", receipt)
    return true, receipt.role == "pending" and ("A pending " .. receipt.key .. " linked")
                 or string.format("%s: B linked %s after %d reroll(s)", receipt.path, receipt.key, receipt.rerolls)
end

-- Pure: marker lines -> problems (empty = PASS) and the receipt. link_verdict = scenario_gen2_link's S.verdict.
function S.verdict(lines, json, link_verdict)
    local problems, link_receipt = link_verdict(lines, json)
    local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
    local TAGS = {DUO_GEN2=true, ENGINE_CAPTURE=true, SAVE_WITNESS=true, RX_TEXT=true, PENDING_CAPTURE=true, LINKED=true,
                  A_PENDING=true, ENCOUNTER=true, REROLL=true}
    local seen, ff = {}, {}
    for index, line in ipairs(lines) do
        local tag, body = tostring(line):match("^([%u%d_]+) (.*)$")
        if tag == "RX" then
            local k = body:match("^force_faint key=(%S+)")
            if k then ff[k] = true end
        elseif tag and TAGS[tag] then
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
    local head, capture, save = rows("DUO_GEN2")[1], rows("ENGINE_CAPTURE")[1], rows("SAVE_WITNESS")[1]
    local key = capture and capture.value.key
    local species = capture and capture.value.species_id
    need(K.SPECIES[species] ~= nil, "the catch is not a Route 29 species")
    need(key == nil or not ff[key], "the own catch was force-fainted")
    for _, r in ipairs(rows("RX_TEXT")) do
        local t = tostring(r.value.text)
        need(not (r.value.cmd == "gui_prompt" and (t:find("[x] Species clause", 1, true) == 1 or t:find("[x] Dup ", 1, true) == 1)),
             "a species-clause rejection prompt: " .. t)
        need(not (r.value.cmd == "msgbox" and t:find(" is a dead zone!", 1, true)), "the area became a dead zone")
    end
    local linked = one("LINKED")
    if linked then
        need(K.is_link_text(linked.value.text), "LINKED carries no link msgbox text")
        need(capture ~= nil and linked.at > capture.at, "LINKED before the catch")
        need(save ~= nil and save.at > linked.at, "the final save precedes the link")
    end
    local role, dupe, rerolls = nil, nil, 0
    if head and head.value.player == "a" then
        role = "pending"
        for _, tag in ipairs({"A_PENDING", "ENCOUNTER", "REROLL"}) do need(#rows(tag) == 0, "the pending half printed " .. tag) end
        local p = one("PENDING_CAPTURE")
        if p then
            need(p.value.key == key and p.value.species_id == species, "PENDING_CAPTURE names another catch")
            need(capture ~= nil and p.at > capture.at and (linked == nil or linked.at > p.at), "PENDING_CAPTURE out of order")
        end
    elseif head and head.value.player == "b" then
        role = "reroller"
        need(#rows("PENDING_CAPTURE") == 0, "the reroller printed PENDING_CAPTURE")
        local ap = one("A_PENDING")
        dupe = ap and ap.value.species_id
        need(K.SPECIES[dupe] ~= nil, "A_PENDING carries no Route 29 species")
        local enc, rr = rows("ENCOUNTER"), rows("REROLL")
        need(#enc >= 1, "no ENCOUNTER")
        for i, e in ipairs(enc) do
            local v, last = e.value, i == #enc
            need(v.n == i and ap ~= nil and e.at > ap.at, "ENCOUNTER out of order")
            need(v.dupe == (v.species_id == dupe) and v.dupe == not last,
                 last and "the caught encounter is A's species" or "a non-duplicate encounter was not caught")
            if not last then
                local r = rr[i]
                if need(r ~= nil and r.value.n == i and r.value.species_id == v.species_id and r.at > e.at
                        and r.at < enc[i + 1].at, "no REROLL after duplicate encounter " .. i) then
                    need(r.value.prompt == dupes_text(v.species_id), "REROLL names another prompt")
                    local got
                    for _, t in ipairs(rows("RX_TEXT")) do
                        if t.value.cmd == "gui_prompt" and t.value.text == r.value.prompt and t.at > e.at and t.at < r.at then got = true end
                    end
                    need(got, "no RX dupes-clause prompt behind REROLL " .. i)
                end
            end
        end
        need(#rr == #enc - 1, "REROLL count differs from the duplicate encounters")
        rerolls = #rr
        local last = enc[#enc]
        if last then
            need(capture ~= nil and capture.at > last.at and species == last.value.species_id, "the catch is not the last encounter")
        end
    else
        need(false, "DUO_GEN2 names no player a|b")
    end
    if #problems > 0 then return problems, nil end
    local receipt = link_receipt
    receipt.schema, receipt.role, receipt.species_id = S.RECEIPT_SCHEMA, role, species
    receipt.dupe_species, receipt.rerolls = dupe, rerolls
    receipt.path = role == "reroller" and (rerolls > 0 and "reroll_observed" or "reroll_unobserved") or "pending"
    receipt.linked = linked.value
    return problems, receipt
end

return S
