--[[
  lua/tests/duo/scenario_gen2_admit_wrong_rom.lua -- the gen2_new `admit_wrong_rom` scenario (C-1, C-6g).

  One half runs an ADMITTED cartridge, the other an UNADMITTED one. Gen 1 reference: admit_randomized_new.
    admitted half   (SLINK_DUO.expect_admission absent or "admitted") the normal battle fixture: CONTINUE,
                    hello, go-file, hold HOLD_FRAMES in the overworld, then a native save.
    refused half    (SLINK_DUO.expect_admission == "refused") the lane launches a ROM that lua/gen2/run.lua
                    must refuse by sha1 -- first input: .cache/gen2-build/pokecrystal/pokecrystal11.gbc (Crystal
                    1.1, built, unselected; run.lua header). No route facts exist for an unadmitted ROM, so this
                    half builds no gate context and presses nothing: it loads the production entry, proves no
                    client came up, stays silent on the wire through the partner's admission and leaves its
                    CartRAM unchanged. Admission is decided before any frame runs (Entry.build), so the refused
                    half never needs to reach the overworld.

  MARKER CONTRACT (duo_gen2_main.lua prints the shared ones; JSON after the tag):
    admitted half   DUO_GEN2, CLIENT (production_admitted=true), BOOTED, MYKEY.., HELLO, [HELLO_AGAIN never],
                    HOLD {frame, frames, hellos}          the overworld hold after the go-file
                    SAVE_WITNESS                          the native save after HOLD
                    RECEIPT {schema "gen2-duo-admit-wrong-rom-v1", expect_admission "admitted", ...}
    refused half    DUO_GEN2 {player, scenario, attempt, title (SLINK_GEN2_TITLE), rom_sha1 (the RUNNING ROM's
                              hash, lower-case), expect_admission="refused"}     no CLIENT, BOOTED or HELLO ever
                    ADMISSION_REFUSED {frame, rom_sha1, client=false, console}    console = run.lua's refusal
                              line ("... refused (production admission): ..." or "not a Gen 2 cartridge ...")
                    NO_TRAFFIC {frame, frames, tx=0}      after the go-file + HOLD_FRAMES: nothing was ever sent
                    CARTRAM_UNCHANGED {before, after}     sha256 of CartRAM[0:0x8000] at start and end, equal
                    RECEIPT {schema "gen2-duo-admit-wrong-rom-v1", expect_admission "refused", ...}
    RESULT: PASS|FAIL                                     last line (both halves)
  go-file: the runner writes it once the server holds the ADMITTED half's hello (the refused half never
  hellos, so "both hellos" cannot be the trigger here). The server-side refusal (no player row, no
  identity lock, links.json/events unchanged for the refused slot) is the lane oracle's job.
  S.verdict re-reads these lines and is the only way to a PASS.
--]]
local S = {}
S.RECEIPT_SCHEMA = "gen2-duo-admit-wrong-rom-v1"
-- ponytail: live bounds, not measured; raise if a lane needs longer.
S.HELLO_FRAMES = 3600
S.GO_FRAMES = 54000
S.HOLD_FRAMES = 600      -- Gen 1's 600-frame passive hold
S.SETTLE_FRAMES = 120
S.CART_RAM_BYTES = 0x8000
S.JSON_TAGS = {DUO_GEN2=true, CLIENT=true, BOOTED=true, HELLO=true, HELLO_AGAIN=true, HOLD=true, SAVE_WITNESS=true,
               ADMISSION_REFUSED=true, NO_TRAFFIC=true, CARTRAM_UNCHANGED=true}

function S.run(h)
    h.jitter()
    local arrived, why = h.arrive()
    if not arrived then return false, "no CONTINUE arrival: " .. tostring(why) end
    h.party()
    if not h.wait(function() return h.sent.hello ~= nil end, S.HELLO_FRAMES) then return false, "the client never sent hello" end
    if not h.wait(h.go, S.GO_FRAMES) then return false, "no go-file" end
    h.frames(S.HOLD_FRAMES)
    h.jlog("HOLD", {frame=h.frame(), frames=S.HOLD_FRAMES, hellos=#h.rec.hellos})
    local saved, save_why = h.save()
    if not saved then return false, "save failed: " .. tostring(save_why) end
    local witnessed, witness_why = h.witness()
    if not witnessed then return false, "save witness: " .. tostring(witness_why) end
    h.frames(S.SETTLE_FRAMES)
    local problems, receipt = S.verdict(h.lines, h.json)
    if #problems > 0 then return false, table.concat(problems, "; ") end
    h.jlog("RECEIPT", receipt)
    return true, "admitted and held"
end

function S.run_refused(r)
    local before = r.SG.cart_digest(r.api)
    local ok, client, console = r.start()
    if not ok then return false, "run.lua raised instead of refusing: " .. tostring(client) end
    if client ~= nil or SLINK_GEN2_CLIENT ~= nil then return false, "the unadmitted ROM started a client" end
    local reason = ""
    for _, line in ipairs(console) do
        if line:find("refused", 1, true) or line:find("not a Gen 2 cartridge", 1, true) then reason = line end
    end
    r.jlog("ADMISSION_REFUSED", {frame=r.api.framecount(), rom_sha1=tostring(r.api.romhash()):lower(), client=false,
                                 console=reason})
    if reason == "" then return false, "run.lua printed no refusal line" end
    if not r.wait(r.go, S.GO_FRAMES) then return false, "no go-file" end
    r.frames(S.HOLD_FRAMES)
    r.jlog("NO_TRAFFIC", {frame=r.api.framecount(), frames=S.HOLD_FRAMES, tx=r.rec.tx})
    r.jlog("CARTRAM_UNCHANGED", {before=before, after=r.SG.cart_digest(r.api)})
    local problems, receipt = S.verdict(r.lines, r.json)
    if #problems > 0 then return false, table.concat(problems, "; ") end
    r.jlog("RECEIPT", receipt)
    return true, "refused, silent, CartRAM unchanged"
end

local function hex64(s) return type(s) == "string" and #s == 64 and s:match("^%x+$") ~= nil end

-- Pure: marker lines -> problems (empty = PASS) and the receipt.
function S.verdict(lines, json)
    local problems, seen, tx = {}, {}, 0
    local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
    for index, line in ipairs(lines) do
        line = tostring(line)
        if line:sub(1, 7) == "RESULT:" then need(false, "a RESULT line precedes the verdict") end
        local tag, body = line:match("^([%u%d_]+) (.*)$")
        if tag == "TX" then tx = tx + 1
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
    local head = one("DUO_GEN2")
    local refused = head ~= nil and head.value.expect_admission == "refused"
    local detail
    if refused then
        for _, tag in ipairs({"CLIENT", "BOOTED", "HELLO", "HELLO_AGAIN", "HOLD", "SAVE_WITNESS"}) do
            need(#rows(tag) == 0, "the refused half printed " .. tag)
        end
        need(tx == 0, "the refused half sent on the wire")
        local refusal, quiet, cart = one("ADMISSION_REFUSED"), one("NO_TRAFFIC"), one("CARTRAM_UNCHANGED")
        if refusal then
            need(refusal.value.client == false and type(refusal.value.console) == "string" and refusal.value.console ~= "",
                 "admission refusal carries no refusal line")
            need(refusal.value.rom_sha1 == head.value.rom_sha1, "the refusal names another ROM than DUO_GEN2")
        end
        if quiet then
            need(quiet.value.tx == 0, "the refused half sent on the wire")
            need(refusal ~= nil and quiet.at > refusal.at, "NO_TRAFFIC before the refusal")
        end
        if cart then
            need(hex64(cart.value.before) and cart.value.before == cart.value.after, "the refused half changed its CartRAM")
            need(quiet ~= nil and cart.at > quiet.at, "CARTRAM_UNCHANGED before the hold ended")
        end
        detail = {refusal=refusal and refusal.value, cartram_sha256=cart and cart.value.after}
    elseif head then
        local client, booted, hello, hold, save = one("CLIENT"), one("BOOTED"), one("HELLO"), one("HOLD"), one("SAVE_WITNESS")
        need(#rows("HELLO_AGAIN") == 0, "the admitted half helloed more than once")
        need(client == nil or client.value.production_admitted == true, "client is not the production graph")
        need(#rows("ADMISSION_REFUSED") == 0, "the admitted half printed a refusal")
        if hold then need(hello ~= nil and hold.at > hello.at, "HOLD before the hello") end
        if save then
            local s = save.value
            need(s.flushed_matches == true and s.cartram_bytes == S.CART_RAM_BYTES and hex64(s.cartram_sha256),
                 "save witness incomplete")
            need(type(s.gate_saves) == "number" and s.gate_saves >= 1 and type(s.client_saves) == "number"
                 and s.client_saves >= 1, "native save not observed by both the gate and the client")
            need(hold ~= nil and save.at > hold.at, "save witness before HOLD")
        end
        detail = {client=client and client.value, booted=booted and booted.value, hello=hello and hello.value,
                  save=save and save.value}
    end
    if #problems > 0 then return problems, nil end
    local h = head.value
    local receipt = {schema=S.RECEIPT_SCHEMA, player=h.player, scenario=h.scenario, attempt=h.attempt, title=h.title,
                     rom_sha1=h.rom_sha1, case=h.case, fixture_sha256=h.fixture_sha256,
                     expect_admission=refused and "refused" or "admitted", input_mode="normal_buttons",
                     harness_write_scopes=json.array({})}
    for k, v in pairs(detail) do receipt[k] = v end
    return problems, receipt
end

return S
