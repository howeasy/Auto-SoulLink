--[[
  lua/tests/duo/gen2_clause.lua -- the gen2_new clause scenarios' shared Route 29 facts, their link-formation
  body (type_clause, gender_clause) and its pure verdict. scenario_gen2_type_clause.lua and
  scenario_gen2_gender_clause.lua are K.scenario("type"|"gender"); scenario_gen2_species_clause.lua uses K's facts.

  ROUTE 29 FACTS (pinned decomps: C = pokecrystal 7a7881d, G = pokegold 656583c, which builds Gold AND Silver;
  derived by SCN from source, not measured):
    grass table   C data/wild/johto_grass.asm:1237-1263; G :1573-1599 (no IF DEF(_GOLD) inside the Route 29
                  block, so Gold == Silver). Seven slots per time of day, GrassMonProbTable 30/30/20/10/5/4/1 %
                  (data/wild/probabilities.asm:6-14, both):
                    C morn/day  L2 PIDGEY, L2 SENTRET, L3 PIDGEY, L3 SENTRET, L2 RATTATA, L3 HOPPIP, L3 HOPPIP
                                -> Pidgey 50%, Sentret 40%, Rattata 5%, Hoppip 5%
                    C nite      L2 HOOTHOOT, L2 RATTATA, L3 HOOTHOOT, L3 RATTATA, L2 RATTATA, L3 HOOTHOOT, L3 HOOTHOOT
                                -> Hoothoot 55%, Rattata 45%
                    G/S morn/day L2 PIDGEY, L3 SENTRET, L3 PIDGEY, L2 SENTRET, L4 RATTATA, L4 PIDGEY, L4 PIDGEY
                                -> Pidgey 55%, Sentret 40%, Rattata 5%
                    G/S nite    L2 HOOTHOOT, L3 HOOTHOOT, L3 HOOTHOOT, L2 RATTATA, L4 RATTATA, L4 HOOTHOOT, L4 HOOTHOOT
                                -> Hoothoot 85%, Rattata 15%
    species ids   PIDGEY 16, RATTATA 19, SENTRET 161, HOOTHOOT 163, HOPPIP 187 (C constants/pokemon_constants.asm
                  :37,40,183,185,209; G :32,35,178,180,204)
    types         data/pokemon/base_stats/<mon>.asm:6, both: Pidgey NORMAL/FLYING, Rattata NORMAL, Sentret NORMAL,
                  Hoothoot NORMAL/FLYING, Hoppip GRASS/FLYING (a monotype repeats its type; the server's set)
    families      every one is its line's base form and none evolves on this table (Pidgey L18, Rattata L20,
                  Sentret L15, Hoothoot L20, Hoppip L18: C data/pokemon/evos_attacks.asm:224,267,2192,2217,2522;
                  G :224,267,2190,2215,2520), so "same family" == "same species byte" on Route 29
    gender        all five GENDER_F50 (base_stats/<mon>.asm:10) = 50 percent = 50 * $ff / 100 = 127 (macros/data.asm
                  :23, constants/pokemon_data_constants.asm:38, both). GetGender (C engine/pokemon/mon_stats.asm:124-
                  230, G :126-232): b = AttackDV << 4 | SpeedDV; `cp b; jr c, .Male` (C :222, G :224) -> FEMALE iff
                  b <= 127, i.e. Attack DV <= 7. Server: Gen2GSCAdapter.gender_from_key (server/adapters/gen2_gsc.py
                  :258-272), the same rule off the key's DV word. No Route 29 mon is genderless.
  CONSEQUENCES
    type clause   every G/S Route 29 species carries NORMAL, so a G<->S (or G/S-only) pair ALWAYS shares a type.
                  Only Crystal morn/day Hoppip (GRASS/FLYING) can pair clean, and only with Sentret or Rattata
                  (NORMAL). Pidgey and Hoothoot share a type with every Route 29 species.
    gender clause 50/50 per catch: a clause verdict needs both catches on the same side of Attack DV 7/8.
    species       duplicates are the same species byte (see families).

  SERVER (server/state.py), --type-clause / --gender-clause at link formation (the second capture in the area):
    _check_link_violation :2946-2963  "Gender clause: both are ♂|♀" / "Type clause: shared <names, sorted, ', '>"
    rejection :1696-1722  the LATER capturer: force_faint <its key> (+nickname), memorialize <key>
                          (_queue_memorialize :3058-3069 also drops its stale box_mon), play_sound 26,
                          gui_prompt "[x] <violation>", unresolve_area <area>; its partner: play_sound 22 (SE_BOO,
                          queued at this one site only)
    no violation :1741-1752  both: play_sound 25 + msgbox "<A label> and <B label> linked!"
  GEN 2 CLIENT (lua/gen2/client.lua): force_faint runs at the held checkpoint through writes:faint_party_slot
  (the harness's PARTY_HP_WRITE); memorialize runs the box executor (run_box :502-524): memorialize_done {key,
  box = boxes.memorial_box = NUM_BOXES-1 = 13, sBox14, lua/gen2/boxes.lua:287,518} once the box writer is
  composed, memorialize_failed {key, reason} (the Gen 2 NACK) until then. BOTH endings are accepted (owner:
  the proven DEAD->MEMORIAL transition, Codex 3a64b0e3 / e7fcd7b6, as gen2_faint's dead|memorial):
    dead      memorialize_failed and the mon stays in the party at HP 0 (the server finishes the pair)
    memorial  memorialize_done box 13 and the mon has left the party (the flushed save's sBox14 is the oracle's)
--]]
local K = {}
K.LINK = "lua/tests/duo/scenario_gen2_link.lua"
K.KEY = "^%x%x%x%x:%x%x%x%x:%x%x$"
K.MEMORIAL_BOX = 13
K.GENDER_RATIO = 127
K.SPECIES = {
    [16] = {name="Pidgey", types={"Normal", "Flying"}},
    [19] = {name="Rattata", types={"Normal"}},
    [161] = {name="Sentret", types={"Normal"}},
    [163] = {name="Hoothoot", types={"Normal", "Flying"}},
    [187] = {name="Hoppip", types={"Grass", "Flying"}},
}
K.SE_BOO, K.SE_FAILURE = 22, 26

-- The server's gender_from_key over a Route 29 key (all GENDER_F50): "male" | "female" | nil (malformed).
function K.gender(key)
    if type(key) ~= "string" or not key:match(K.KEY) then return nil end
    local dv = tonumber(key:sub(1, 4), 16)
    local b = ((dv >> 8) & 0xF0) | ((dv >> 4) & 0x0F)
    return b <= K.GENDER_RATIO and "female" or "male"
end
K.SYMBOL = {male="♂", female="♀"}

local function set_of(list)
    local s = {}
    for _, v in ipairs(list or {}) do s[v] = true end
    return s
end
-- True when some Route 29 species shares no type with `species` (the type clause may then link cleanly).
function K.clean_type_partner(species)
    local own = set_of((K.SPECIES[species] or {}).types)
    for _, other in pairs(K.SPECIES) do
        local shared = false
        for _, t in ipairs(other.types) do if own[t] then shared = true end end
        if not shared then return true end
    end
    return false
end

-- The first clause verdict on the wire for `key`, from the harness's RX records.
function K.verdict_of(rx, key, is_link_text)
    for _, r in ipairs(rx) do
        if r.cmd == "force_faint" and r.key == key then return "rejected" end
        if r.cmd == "play_sound" and r.sound == K.SE_BOO then return "partner_rejected" end
        if r.cmd == "msgbox" and is_link_text(r.text) then return "linked" end
    end
end
function K.is_link_text(text) return type(text) == "string" and text:sub(-8) == " linked!" end

function K.scenario(kind)
    assert(kind == "type" or kind == "gender", "clause kind type|gender")
    local S = {KIND=kind}
    S.RECEIPT_SCHEMA = "gen2-duo-" .. kind .. "-clause-v1"
    S.LABEL = kind == "type" and "Type clause: " or "Gender clause: "
    -- ponytail: live bounds, not measured; raise if a lane needs longer.
    S.HELLO_FRAMES = 3600
    S.GO_FRAMES = 54000
    S.VERDICT_FRAMES = 120000   -- spans the partner's whole hunt (the server compares once both captured)
    S.REJECT_FRAMES = 1800      -- the rejection's commands + the checkpoint's write and memorialize reply
    S.SETTLE_FRAMES = 120

    local function rejection_missing(h, key, area)
        local got = {}
        for _, r in ipairs(h.rec.rx) do
            if r.cmd == "memorialize" and r.key == key then got.memorialize = true end
            if r.cmd == "play_sound" and r.sound == K.SE_FAILURE then got.sound26 = true end
            if r.cmd == "unresolve_area" and r.area_id == area then got.unresolve_area = true end
            if r.cmd == "gui_prompt" and type(r.text) == "string" and r.text:sub(1, 4 + #S.LABEL) == "[x] " .. S.LABEL then
                got.prompt = true
            end
        end
        got.party_hp_write = h.rec.hp_write ~= nil and h.rec.hp_write.key == key
        got.memorial_ack = h.rec.memorial[key] ~= nil
        for _, need in ipairs({"prompt", "memorialize", "sound26", "unresolve_area", "party_hp_write", "memorial_ack"}) do
            if not got[need] then return need end
        end
    end

    function S.run(h)
        h.jitter()
        local arrived, why = h.arrive()
        if not arrived then return false, "no CONTINUE arrival: " .. tostring(why) end
        h.party()
        if not h.wait(function() return h.sent.hello ~= nil end, S.HELLO_FRAMES) then return false, "the client never sent hello" end
        if not h.wait(h.go, S.GO_FRAMES) then return false, "no go-file" end
        local played, outcome = h.play()
        if not played then return false, "link route failed: " .. tostring(outcome) end
        h.party()
        local key, cap = h.rec.caught, h.rec.capture
        if not key or not cap then return false, "no reported catch" end
        local mon = K.SPECIES[cap.species_id]
        if not mon then return false, "not a Route 29 species: " .. tostring(cap.species_id) end
        h.jlog("CLAUSE_CAPTURE", {frame=h.frame(), key=key, species_id=cap.species_id, area_id=cap.area_id,
                                  types=h.json.array(mon.types), gender=K.gender(key)})
        local verdict
        if not h.wait(function()
            verdict = K.verdict_of(h.rec.rx, key, K.is_link_text)
            return verdict ~= nil
        end, S.VERDICT_FRAMES) then return false, "no " .. kind .. "-clause verdict" end
        h.jlog("CLAUSE_VERDICT", {frame=h.frame(), verdict=verdict})
        if verdict == "rejected" then
            local missing
            h.wait(function() missing = rejection_missing(h, key, cap.area_id) return missing == nil end, S.REJECT_FRAMES)
            if missing then return false, "incomplete rejection: no " .. missing end
            local ack = h.rec.memorial[key]
            local slot, m = h.slot_of(key)
            if ack.event == "memorialize_done" then
                h.jlog("REJECTED_MON", {frame=h.frame(), key=key, ending="memorial", box=ack.box, in_party=m ~= nil})
                if m then return false, "the memorialized mon is still in the party" end
            else
                h.jlog("REJECTED_MON", {frame=h.frame(), key=key, ending="dead", in_party=m ~= nil, slot=slot,
                                        hp=m and m.hp, status=m and m.status})
                if not m then return false, "the NACKed rejected mon left the party" end
                if m.hp ~= 0 then return false, "the rejected mon was not fainted" end
            end
        end
        local saved, save_why = h.save()
        if not saved then return false, "final save failed: " .. tostring(save_why) end
        local witnessed, witness_why = h.witness()
        if not witnessed then return false, "save witness: " .. tostring(witness_why) end
        h.frames(S.SETTLE_FRAMES)
        local problems, receipt = S.verdict(h.lines, h.json, dofile(h.root .. "/" .. K.LINK).verdict)
        if #problems > 0 then return false, table.concat(problems, "; ") end
        h.jlog("RECEIPT", receipt)
        return true, string.format("%s clause %s %s (%s)", kind, verdict, key, receipt.path)
    end

    -- Pure: marker lines -> problems (empty = PASS) and the receipt. link_verdict = scenario_gen2_link's S.verdict.
    function S.verdict(lines, json, link_verdict)
        local problems, link_receipt = link_verdict(lines, json)
        local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
        local seen, rx = {}, {}
        local TAGS = {CLAUSE_CAPTURE=true, CLAUSE_VERDICT=true, REJECTED_MON=true, MEMORIAL_ACK=true, RX_TEXT=true,
                      PARTY_HP_WRITE=true, ENGINE_CAPTURE=true, CAPTURE_SENT=true, SAVE_WITNESS=true}
        for index, line in ipairs(lines) do
            local tag, body = tostring(line):match("^([%u%d_]+) (.*)$")
            if tag == "RX" then
                local row = {at=index, cmd=body:match("^(%S+)")}
                for k, v in body:gmatch("([%w_]+)=(%S+)") do row[k] = v end
                rx[#rx + 1] = row
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
        local function first(test) for _, r in ipairs(rx) do if test(r) then return r end end end
        local function texts(cmd, test)
            for _, r in ipairs(rows("RX_TEXT")) do if r.value.cmd == cmd and test(r.value.text) then return r end end
        end
        local capture, save = rows("ENGINE_CAPTURE")[1], rows("SAVE_WITNESS")[1]
        local key = capture and capture.value.key
        local area = capture and capture.value.area_id
        local cc, cv = one("CLAUSE_CAPTURE"), one("CLAUSE_VERDICT")
        local sent
        for _, r in ipairs(rows("CAPTURE_SENT")) do if r.value.key == key then sent = sent or r end end
        local species, mon, gender = nil, nil, K.gender(key)
        if cc then
            local c = cc.value
            species, mon = c.species_id, K.SPECIES[c.species_id]
            need(c.key == key, "CLAUSE_CAPTURE names another key than the engine capture")
            need(mon ~= nil and capture ~= nil and capture.value.species_id == species, "the catch is not a Route 29 species")
            need(mon == nil or (type(c.types) == "table" and table.concat(c.types, "/") == table.concat(mon.types, "/")),
                 "CLAUSE_CAPTURE types disagree with the source base stats")
            need(c.gender == gender, "CLAUSE_CAPTURE gender disagrees with the key's Attack DV")
        end
        local verdict = cv and cv.value.verdict
        local ff = key and first(function(r) return r.cmd == "force_faint" and r.key == key end)
        local boo = first(function(r) return r.cmd == "play_sound" and tonumber(r.sound) == K.SE_BOO end)
        local linked = texts("msgbox", K.is_link_text)
        local prompt = texts("gui_prompt", function(t) return type(t) == "string" and t:sub(1, 4 + #S.LABEL) == "[x] " .. S.LABEL end)
        local rejected_mon = rows("REJECTED_MON")[1]
        if cv then
            need(cc ~= nil and cv.at > cc.at, "CLAUSE_VERDICT before CLAUSE_CAPTURE")
            local cause = ({rejected=ff, partner_rejected=boo, linked=linked})[verdict]
            need(cause ~= nil, "CLAUSE_VERDICT " .. tostring(verdict) .. " has no wire cause")
            if cause then
                need(sent ~= nil and cause.at > sent.at, "the clause verdict arrived before the capture was sent")
                need(cause.at < cv.at, "CLAUSE_VERDICT printed before its wire cause")
            end
            if verdict ~= "rejected" then
                need(ff == nil and prompt == nil and rejected_mon == nil, "a " .. tostring(verdict) .. " half was rejected")
            end
            if verdict ~= "partner_rejected" then need(boo == nil, "the " .. tostring(verdict) .. " half heard SE_BOO") end
        end
        local ending
        if verdict == "rejected" then
            need(boo == nil and linked == nil, "the rejected half also saw its partner's verdict")
            need(first(function(r) return r.cmd == "memorialize" and r.key == key end) ~= nil, "no memorialize for the rejected key")
            need(first(function(r) return r.cmd == "play_sound" and tonumber(r.sound) == K.SE_FAILURE end) ~= nil, "no play_sound 26")
            need(first(function(r) return r.cmd == "unresolve_area" and r.area_id == area end) ~= nil, "no unresolve_area for the catch's area")
            if need(prompt ~= nil, "no [x] " .. S.LABEL .. "prompt") and mon then
                local rest = prompt.value.text:sub(5 + #S.LABEL)
                if kind == "type" then
                    local own, names = set_of(mon.types), 0
                    local list = rest:match("^shared (.+)$")
                    for t in ((list or "") .. ", "):gmatch("(.-), ") do
                        if t ~= "" then names = names + 1; need(own[t], "prompt names a type the catch lacks: " .. t) end
                    end
                    need(names > 0, "type-clause prompt names no shared type")
                else
                    need(rest == "both are " .. tostring(K.SYMBOL[gender]), "gender-clause prompt names the other gender")
                end
            end
            local hp
            for _, r in ipairs(rows("PARTY_HP_WRITE")) do if r.value.key == key and r.value.ok == true then hp = hp or r end end
            need(hp ~= nil, "no production PARTY_HP_WRITE for the rejected key")
            local ack
            for _, r in ipairs(rows("MEMORIAL_ACK")) do if r.value.key == key then ack = ack or r end end
            if need(ack ~= nil, "no MEMORIAL_ACK for the rejected key") and need(rejected_mon ~= nil, "missing REJECTED_MON marker") then
                local a, m = ack.value, rejected_mon.value
                need(#rows("REJECTED_MON") == 1 and m.key == key, "REJECTED_MON names another key")
                need(rejected_mon.at > ack.at and (hp == nil or rejected_mon.at > hp.at), "REJECTED_MON before the checkpoint replies")
                if a.event == "memorialize_failed" then
                    ending = "dead"
                    need(m.ending == "dead" and m.in_party == true and m.hp == 0, "a NACKed rejection did not leave the mon dead in the party")
                elseif a.event == "memorialize_done" then
                    ending = "memorial"
                    need(a.box == K.MEMORIAL_BOX and m.ending == "memorial" and m.box == K.MEMORIAL_BOX and m.in_party == false,
                         "a memorialized rejection is not out of the party into sBox14")
                else
                    need(false, "MEMORIAL_ACK is neither memorialize_done nor memorialize_failed")
                end
                need(save ~= nil and save.at > rejected_mon.at, "the final save precedes the rejected mon's ending")
            end
        elseif verdict == "linked" and kind == "type" and species then
            need(K.clean_type_partner(species), K.SPECIES[species] and (K.SPECIES[species].name
                 .. " shares a type with every Route 29 species, yet linked") or "linked off Route 29")
        end
        if cv then need(save ~= nil and save.at > cv.at, "the final save precedes the clause verdict") end
        if #problems > 0 then return problems, nil end
        local receipt = link_receipt
        receipt.schema, receipt.clause, receipt.verdict, receipt.ending = S.RECEIPT_SCHEMA, kind, verdict, ending
        receipt.path = verdict == "linked" and "clause_unobserved" or "clause_observed"
        receipt.species_id, receipt.types, receipt.gender = species, json.array(mon.types), gender
        return problems, receipt
    end
    return S
end

return K
