--[[
  lua/tests/duo/scenario_gen2_soft_reset.lua -- the gen2_new `soft_reset` scenario (C-2 WRAM clear, R-4, W-6).

  Gen 1 reference: soft_reset_new (duo_gen1_main.lua scenarios.soft_reset_new, e2e_duo.py assert_soft_reset_saved).
  A soft-resets a LIVE, already-helloed cartridge with the native chord; B idles as the witness.

  Game facts (pinned decomps, identical in both repos except where noted):
    UpdateJoypad (VBlank) jumps to Reset the frame hJoypadDown holds all of PAD_BUTTONS (A+B+SELECT+START; the
      d-pad is masked off): C home/joypad.asm:99-102, G :99-102. No hSoftReset countdown (Gen 1 had 16 polls).
      The chord is ignored while wJoypadDisable's mask bits or wGameLogicPaused (a save) are set (:30-37 both).
    Reset: C home/init.asm:1-19 / G :1-14 -- sets the SGB-transfer joypad-disable bit (no re-trigger), DelayFrames
      32, jr Init. Init clears WRAM: C :66-75 (WRAM0) + :93 ClearWRAM (bank 1 only, the documented bug :186-189);
      G :58-67 ($C000-$DFFF). wPlayerID and wPartyCount read 0 afterwards -> RESET_SEEN ~33 frames after the chord.
    Then the intro/title and CONTINUE, exactly the fixture boot path (lua/tests/gen2_qualify.lua stage boot).
  Client (lua/gen2/client.lua): validate() every VALIDATE_EVERY=60 frames; OT 0 with an empty party is
  "pre-game" -> boundary("reset") drops the hello; the MAX_INVALID=5th invalid validation pauses writes
  (gate_revoked); a live validation after CONTINUE re-enables them; the hello session re-hellos the same OT.
  No `soft_reset` engine site is needed: this is the client's WRAM-clear path. (A PHYSICAL soft_reset site
  receipt, C 00:0150 / G/S 00:05b0, would add the coverage map's independent ENGINE occurrence.)

  MARKER CONTRACT (duo_gen2_main.lua prints the shared ones; JSON after the tag):
    both    DUO_GEN2 CLIENT BOOTED MYKEY.. HELLO     (no ENGINE_CAPTURE: nothing is caught)
    A       HELLO_AT_CHECKPOINT {frame, ot_id, hellos=1, writes_enabled=true}   after the go-file
            CHORD_GATE {frame}                     the runner created <go_file>.chord (its links baseline exists)
            CHORD {frame, frames}                  A+B+SELECT+START held `frames` frames from `frame`, normal buttons
            RESET_SEEN {frame, delta}              the gate decoder reads OT 0 + party 0; delta from CHORD.frame,
                                                   S.RESET_DELTA (30..60)
            HELLO_CLEARED {frame, delta}           client.hello_sent false; delta <= S.HELLO_CLEARED_MAX (180)
            WRITES_PAUSED {frame, delta}           client.gate_revoked and not writes_enabled; S.PAUSE_DELTA (180..420)
            REBOOTED {frame, map_group, map_number, x, y, party_count}   the second CONTINUE arrival (BOOTED's shape)
            WRITES_RESUMED {frame, delta}          first observation after REBOOTED of writes re-enabled
            HELLO_AGAIN {frame, ot_id, n=2}        (main) the re-hello on the wire, after WRITES_PAUSED
            REHELLO {frame, ot_id, hellos=2}       same ot_id as HELLO; after REBOOTED
            NO_WRITES_IN_WINDOW {writes=0}         production permit-log rows added between CHORD and REHELLO
            SAVE_WITNESS                           the native save after the reset; save_completed_frame > REHELLO.frame
    B       IDLE_PARTNER {frame, hellos=1}         after A's REHELLO appeared in A's result file; no HELLO_AGAIN
            SAVE_WITNESS                           after IDLE_PARTNER
    both    RECEIPT {schema "gen2-duo-soft-reset-v1", ...}   PASS only;  RESULT: PASS|FAIL last line
  Runner: the go-file once both hellos are held; A's <go_file>.chord once the pre-reset links/events baseline
  is snapshotted (Gen 1 H-6). Pair/links byte-identity across the reset is the lane oracle's.
  S.verdict re-reads these lines and is the only way to a PASS.
--]]
local S = {}
S.RECEIPT_SCHEMA = "gen2-duo-soft-reset-v1"
S.CHORD = {A=true, B=true, Select=true, Start=true}
-- ponytail: live calibration knobs, not measured yet; the bounds follow the facts in the header.
S.CHORD_FRAMES = 4            -- Reset fires on the first; its joypad-disable bit blocks a re-trigger
S.HELLO_FRAMES = 3600
S.GO_FRAMES = 54000
S.ENABLED_FRAMES = 240        -- writes enabled before the chord (the first live validations)
S.CHORD_GATE_FRAMES = 3600
S.RESET_FRAMES = 120
S.RESET_DELTA = {30, 60}      -- DelayFrames 32 + Init, from the chord's first frame; measured 38 (C<->C f0ccabf2, C<->G 89013a4d)
S.WITHHOLD_FRAMES = 600       -- no input while the client withdraws the hello and pauses writes
S.HELLO_CLEARED_MAX = 180
S.PAUSE_DELTA = {180, 420}    -- MAX_INVALID validations, 60 frames apart; measured 321 / 317 after the reset (C<->C / C<->G)
-- measured, not bounded: re-hello (HELLO_AGAIN) 3298 and REBOOTED/WRITES_RESUMED 3328 frames after the reset (both pairs)
S.RESUME_FRAMES = 600
S.REHELLO_FRAMES = 1200
S.PARTNER_FRAMES = 54000
S.SETTLE_FRAMES = 120
S.CART_RAM_BYTES = 0x8000
S.JSON_TAGS = {}
for _, tag in ipairs({"DUO_GEN2", "CLIENT", "BOOTED", "HELLO", "HELLO_AGAIN", "ENGINE_CAPTURE", "SAVE_WITNESS",
                      "HELLO_AT_CHECKPOINT", "CHORD_GATE", "CHORD", "RESET_SEEN", "HELLO_CLEARED", "WRITES_PAUSED",
                      "REBOOTED", "WRITES_RESUMED", "REHELLO", "NO_WRITES_IN_WINDOW", "IDLE_PARTNER"}) do
    S.JSON_TAGS[tag] = true
end
S.A_ONLY = {"HELLO_AT_CHECKPOINT", "CHORD_GATE", "CHORD", "RESET_SEEN", "HELLO_CLEARED", "WRITES_PAUSED", "REBOOTED",
            "WRITES_RESUMED", "REHELLO", "NO_WRITES_IN_WINDOW"}

local function save(h)
    local saved, why = h.save()
    if not saved then return false, "save failed: " .. tostring(why) end
    local witnessed, witness_why = h.witness()
    if not witnessed then return false, "save witness: " .. tostring(witness_why) end
    return true
end

local function reset(h)
    local c = h.client
    if not h.wait(function() return c.writes_enabled == true and c.hello_sent == true end, S.ENABLED_FRAMES) then
        return false, "A is not helloed with writes enabled before the reset"
    end
    local ot0 = h.sent.hello.ot_id
    h.jlog("HELLO_AT_CHECKPOINT", {frame=h.frame(), ot_id=ot0, hellos=#h.rec.hellos, writes_enabled=c.writes_enabled})
    if not h.wait(function() return h.file_has(h.go_file .. ".chord", "") end, S.CHORD_GATE_FRAMES) then
        return false, "chord gate never released"
    end
    h.jlog("CHORD_GATE", {frame=h.frame()})
    local writes_before, hellos_before, chord = h.write_count(), #h.rec.hellos, h.frame()
    h.hold(S.CHORD, S.CHORD_FRAMES)
    h.jlog("CHORD", {frame=chord, frames=S.CHORD_FRAMES})
    if not h.wait(function()
        local id = h.identity()
        return id ~= nil and id.ot_id == 0 and id.party_count == 0
    end, S.RESET_FRAMES) then return false, "the soft reset chord did not clear WRAM" end
    local reset_at = h.frame()
    h.jlog("RESET_SEEN", {frame=reset_at, delta=reset_at - chord})
    local cleared, paused
    h.wait(function()
        if not cleared and c.hello_sent ~= true then
            cleared = h.frame()
            h.jlog("HELLO_CLEARED", {frame=cleared, delta=cleared - reset_at})
        end
        if not paused and c.gate_revoked == true and c.writes_enabled ~= true then
            paused = h.frame()
            h.jlog("WRITES_PAUSED", {frame=paused, delta=paused - reset_at})
        end
        return cleared ~= nil and paused ~= nil
    end, S.WITHHOLD_FRAMES)
    if not cleared then return false, "the client kept its hello across a cleared WRAM" end
    if not paused then return false, "writes were never paused by the cleared WRAM" end
    local arrived, why = h.arrive("REBOOTED")
    if not arrived then return false, "no CONTINUE after the reset: " .. tostring(why) end
    if not h.wait(function() return c.writes_enabled == true and c.gate_revoked ~= true end, S.RESUME_FRAMES) then
        return false, "writes stayed paused after CONTINUE"
    end
    h.jlog("WRITES_RESUMED", {frame=h.frame(), delta=h.frame() - reset_at})
    if not h.wait(function() return #h.rec.hellos > hellos_before end, S.REHELLO_FRAMES) then
        return false, "the reloaded save never re-helloed"
    end
    local again = h.rec.hellos[#h.rec.hellos]
    h.jlog("REHELLO", {frame=h.frame(), ot_id=again.ot_id, hellos=#h.rec.hellos})
    h.jlog("NO_WRITES_IN_WINDOW", {writes=h.write_count() - writes_before})
    h.party()
    return true
end

function S.run(h)
    h.jitter()
    local arrived, why = h.arrive()
    if not arrived then return false, "no CONTINUE arrival: " .. tostring(why) end
    h.party()
    if not h.wait(function() return h.sent.hello ~= nil end, S.HELLO_FRAMES) then return false, "the client never sent hello" end
    if not h.wait(h.go, S.GO_FRAMES) then return false, "no go-file" end
    if h.player == "a" then
        local ok, reset_why = reset(h)
        if not ok then return false, reset_why end
    else
        if not h.wait(function() return h.partner_has("REHELLO") end, S.PARTNER_FRAMES) then
            return false, "A never re-helloed after its soft reset"
        end
        h.jlog("IDLE_PARTNER", {frame=h.frame(), hellos=#h.rec.hellos})
    end
    local saved, save_why = save(h)
    if not saved then return false, save_why end
    h.frames(S.SETTLE_FRAMES)
    local problems, receipt = S.verdict(h.lines, h.json)
    if #problems > 0 then return false, table.concat(problems, "; ") end
    h.jlog("RECEIPT", receipt)
    return true, h.player == "a" and "same-save soft reset: one re-hello, no writes in the cleared window"
                 or "idled at the checkpoint across the partner reset"
end

local function within(v, range) return type(v) == "number" and v >= range[1] and v <= range[2] end

-- Pure: marker lines -> problems (empty = PASS) and the receipt.
function S.verdict(lines, json)
    local problems, seen = {}, {}
    local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
    for index, line in ipairs(lines) do
        line = tostring(line)
        if line:sub(1, 7) == "RESULT:" then need(false, "a RESULT line precedes the verdict") end
        local tag, body = line:match("^([%u%d_]+) (.*)$")
        if tag and S.JSON_TAGS[tag] then
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
    local function after(a, b, what) need(a ~= nil and b ~= nil and a.at > b.at, what) end
    local head, client, booted, hello, save = one("DUO_GEN2"), one("CLIENT"), one("BOOTED"), one("HELLO"), one("SAVE_WITNESS")
    need(client == nil or client.value.production_admitted == true, "client is not the production graph")
    need(#rows("ENGINE_CAPTURE") == 0, "a mon was caught during the soft-reset scenario")
    if save then
        local s = save.value
        need(s.flushed_matches == true and s.cartram_bytes == S.CART_RAM_BYTES and type(s.cartram_sha256) == "string"
             and #s.cartram_sha256 == 64, "save witness incomplete")
        need(type(s.gate_saves) == "number" and s.gate_saves >= 1 and type(s.client_saves) == "number"
             and s.client_saves >= 1, "native save not observed by both the gate and the client")
    end
    local player = head and head.value.player
    local detail = {}
    if player == "a" then
        local at, gate, chord = one("HELLO_AT_CHECKPOINT"), one("CHORD_GATE"), one("CHORD")
        local reset, cleared, paused = one("RESET_SEEN"), one("HELLO_CLEARED"), one("WRITES_PAUSED")
        local rebooted, resumed, again, rehello = one("REBOOTED"), one("WRITES_RESUMED"), one("HELLO_AGAIN"), one("REHELLO")
        local nowrite = one("NO_WRITES_IN_WINDOW")
        if at then
            need(at.value.writes_enabled == true and at.value.hellos == 1, "the reset did not start helloed with writes enabled")
            after(at, hello, "HELLO_AT_CHECKPOINT before the hello")
        end
        after(gate, at, "CHORD_GATE before HELLO_AT_CHECKPOINT")
        after(chord, gate, "CHORD before the chord gate")
        if chord then need(type(chord.value.frames) == "number" and chord.value.frames >= 1, "CHORD held no frame") end
        if reset then
            after(reset, chord, "RESET_SEEN before the chord")
            need(within(reset.value.delta, S.RESET_DELTA), "WRAM clear outside the chord's DelayFrames window")
        end
        if cleared then
            after(cleared, reset, "HELLO_CLEARED before RESET_SEEN")
            need(within(cleared.value.delta, {0, S.HELLO_CLEARED_MAX}), "hello withdrawn too late after the reset")
        end
        if paused then
            after(paused, reset, "WRITES_PAUSED before RESET_SEEN")
            need(within(paused.value.delta, S.PAUSE_DELTA), "writes paused outside the MAX_INVALID window")
        end
        after(rebooted, paused, "REBOOTED before writes paused")
        after(rebooted, cleared, "REBOOTED before the hello was withdrawn")
        after(resumed, rebooted, "WRITES_RESUMED before REBOOTED")
        if again then
            after(again, paused, "the re-hello went out before writes paused")
            need(again.value.n == 2 and hello ~= nil and again.value.ot_id == hello.value.ot_id,
                 "the re-hello is not the second hello with the pre-reset OT")
        end
        if rehello then
            after(rehello, rebooted, "REHELLO before REBOOTED")
            need(rehello.value.hellos == 2 and hello ~= nil and rehello.value.ot_id == hello.value.ot_id,
                 "REHELLO carries another OT or hello count")
        end
        if nowrite then
            need(nowrite.value.writes == 0, "a write landed on the cleared window")
            after(nowrite, rehello, "NO_WRITES_IN_WINDOW before REHELLO")
        end
        if save then
            after(save, nowrite, "save witness before the reset window closed")
            need(rehello ~= nil and type(save.value.save_completed_frame) == "number"
                 and save.value.save_completed_frame > rehello.value.frame, "native save completed before the re-hello")
        end
        detail = {reset=reset and reset.value, paused=paused and paused.value, rehello=rehello and rehello.value}
    elseif player == "b" then
        for _, tag in ipairs(S.A_ONLY) do need(#rows(tag) == 0, "the idle partner printed " .. tag) end
        need(#rows("HELLO_AGAIN") == 0, "the idle partner helloed more than once")
        local idle = one("IDLE_PARTNER")
        if idle then need(idle.value.hellos == 1, "the idle partner helloed more than once") end
        after(idle, hello, "IDLE_PARTNER before the hello")
        after(save, idle, "save witness before IDLE_PARTNER")
        detail = {idle=idle and idle.value}
    else
        need(false, "DUO_GEN2 names no player a|b")
    end
    if #problems > 0 then return problems, nil end
    local h = head.value
    local receipt = {schema=S.RECEIPT_SCHEMA, player=h.player, scenario=h.scenario, attempt=h.attempt, case=h.case,
                     title=h.title, rom_sha1=h.rom_sha1, fixture_sha256=h.fixture_sha256, booted=booted.value,
                     hello=hello.value, save=save.value, client=client.value, input_mode="normal_buttons",
                     harness_write_scopes=json.array({})}
    for k, v in pairs(detail) do receipt[k] = v end
    return problems, receipt
end

return S
