--[[
  lua/tests/duo/scenario_gen2_faint_active.lua -- the gen2_new `gen2_faint_active` scenario (roadmap row 7,
  linked_faint_active; closes D-6 active and W-2 on the duo). B's linked mon is B's ACTIVE battler in a wild
  battle when A's linked mon dies; the production client kills it IN battle at the battle hold (O-30:
  write_checkpoint.json battle_hold, before `call DetermineMoveOrder`; lua/gen2/writes.lua faint_active_battler:
  battle HP 0, the party mirror, wBattlePlayerAction = USEITEM last).

  Both halves first play the `link` scenario unchanged and print LINK_SAVE (scenario_gen2_faint.lua), then:
    B  walks into the Route 29 grass, switches the linked catch in (gen2_faint_inputs.lua, PKMN -> SWITCH; the
       party is starter + catch, so the catch is never the last mon and the death is no whiteout), prints
       LINKED_ACTIVE and IDLES at the battle menu (no turn is committed: the foe never moves while B waits).
       Once force_faint arrived and the client queued it for the battle hold, B commits one turn (a status
       move, else any move: the write lands before DetermineMoveOrder, so the move never runs). The hold
       writes, HandlePlayerMonFaint runs in the same frame, "Use next #MON?" -> YES -> the starter -> RUN.
       B reads the record back, waits for its memorial and saves natively.
    A  the gen2_faint sacrifice, started only once the runner wrote B_ACTIVE into A's go-file.
  RUNNER ORDERING: B prints LINKED_ACTIVE -> the runner writes a line "B_ACTIVE" into A's go-file (A_PENDING
  style) -> A starts its faint battle.

  MARKER CONTRACT (duo_gen2_main.lua prints them; JSON after the tag unless noted). A: everything
  scenario_gen2_faint.lua's A half prints, plus
    B_ACTIVE {frame}             A read "B_ACTIVE" in its go-file; after LINK_SAVE, before ENGINE_FAINT
  B: everything the link scenario prints, LINK_SAVE, then
    LINKED_ACTIVE {frame, key, slot, cur_battle_mon, battle_mon_species, battle_mode=1, battle_type,
                   link_mode=0}  engine-read (wCurBattleMon/wBattleMonSpecies/...) once the catch is the
                                 active battler; after LINK_SAVE; B idles at the battle menu from here
    RX force_faint key=<key>     (plain text) after LINKED_ACTIVE
    BATTLE_HOLD_WRITE {frame, seq, key, slot, active_slot, kind="battle_faint", ok, error, pc, hrom_bank,
                   battle_hp_before_hex, battle_hp_after_hex, hp_before_hex, hp_after_hex, status_after_hex,
                   action_before_hex, action_after_hex, log=[the 4 permit spans]}
                                 around the PRODUCTION faint_active_battler call, inside the client's battle
                                 hold; exactly one; after = "0000"/"0000"/"00" and action "01" (USEITEM)
    BATTLE_TRACE {seq, what=faint|enemy_turn|lost, frame}
                                 observation-only hooks at the pack's battle_hold.oracles (HandlePlayerMonFaint,
                                 EnemyTurn_EndOpponentProtectEndureDestinyBond, LostBattle; in-bank + expected
                                 bytes), from LINKED_ACTIVE to the end of that battle; seq shares one counter
                                 with BATTLE_HOLD_WRITE. The first row after the write is `faint` in the SAME
                                 frame (no foe move in between); no `lost` row (no whiteout).
    BATTLE_TRACE {seq, what="enemy_faint", frame, battle_mode, species, hp_before, hp_after, title}
                                 TRAINER-FAINT-LIVE-TURN (post-RC, OMP cx-4ece9985): an independent engine read
                                 of wEnemyMonHP/wEnemyMonSpecies (never the production wire), S.TRAINER only,
                                 sampled only after BATTLE_HOLD_WRITE while battle_mode == 2. hp_before is the
                                 latest positive-HP reading for the SAME species (a fresh baseline on every
                                 species change, so a switch is never a witness); hp_after == 0 is the very next
                                 reading of that species at zero (no baseline, i.e. a first read already 0, is
                                 never a witness either). The alternative "live turn" witness to `enemy_turn`
                                 when the replacement crit-KOs the foe before it ever moves; S.verdict/the Python
                                 oracle require it strictly after REPLACED by frame, never by line position, and
                                 the wild scenario (not S.TRAINER) must never emit one.
    ENGINE_FAINT                 allowed (the binder's battle_faint for the key, after the write); FAINT_SENT
                                 never (the commanded death's echo is dropped, O-30)
    NEXT_MON {frame}             the "Use next #MON?" yes/no, after the native faint
    REPLACED {frame, active_slot, hp}   another living mon is the active battler, after NEXT_MON
    LINKED_HP_STATUS <hp %04X> <status %02X>   (plain text) the record read back after the battle: "0000 00"
    PARTY_HP_WRITE               only an idempotent checkpoint repeat (O-24), before == after
    MEMORIAL_PREIMAGE / MEMORIAL_ACK / SAVE_WITNESS   as scenario_gen2_faint.lua (preimage after the write)
    RECEIPT {schema "gen2-duo-faint-active-v1", ...}  PASS only;  RESULT: PASS|FAIL  last line
  S.verdict re-reads these lines and is the only way to PASS.

  S.TRAINER (scenario_gen2_faint_active_trainer.lua, O-30 review MINOR-5): B's battle is a TRAINER battle instead.
  After LINK_SAVE B walks Route 29 -> Cherrygrove -> Route 30 until a Youngster engages (duo_gen2_main.lua
  h.to_trainer), switches the catch in and idles exactly as above. The hold write, HandlePlayerMonFaint, then
  ForcePlayerMonChoice with NO "Use next #MON?" (AskUseNextPokemon returns at wBattleMode 2, C engine/battle/
  core.asm:2695-2701) -> the starter, which FIGHTs until the trainer is beaten (no RUN from a trainer). Changes:
    LINKED_ACTIVE  battle_mode=2, plus other_trainer_class / other_trainer_id (wOtherTrainerClass/wOtherTrainerID)
    NEXT_MON       never printed
    REPLACED       after the native faint (the party pick is forced)
    BATTLE_TRACE   at least one `enemy_turn` OR `enemy_faint` after REPLACED: a live turn with the replacement
                   (a crit-KO before the foe ever moves is still a live turn); still no `lost`
    RECEIPT        schema "gen2-duo-faint-active-trainer-v1", receipt.trainer = {class, id}
--]]
local S = {}
S.RECEIPT_SCHEMA = "gen2-duo-faint-active-v1"
S.FAINT_INPUTS = true    -- duo_gen2_main.lua prepares gen2_faint_inputs.lua's UI origins before its hooks
S.BATTLE_TRACE = true    -- duo_gen2_main.lua wraps faint_active_battler and hooks the battle_hold oracles
-- ponytail: live bounds, not measured; raise if a lane needs longer.
S.HELLO_FRAMES = 3600
S.GO_FRAMES = 54000
S.ACTIVE_FRAMES = 54000    -- A waits this long for the runner's B_ACTIVE
S.HOLD_FRAMES = 90000      -- B's battle phase: the switch, A's whole faint battle, the kill, RUN
S.SEND_FRAMES = 600
S.MEMORIAL_FRAMES = 1800
S.MEMORIAL_BOX = 13
S.SETTLE_FRAMES = 120
S.SAVERAM_BYTES = 0x8000 + 22
S.KEY = "^%x%x%x%x:%x%x%x%x:%x%x$"
S.USEITEM = "01"
S.LINK = "lua/tests/duo/scenario_gen2_link.lua"
S.FAINT = "lua/tests/duo/scenario_gen2_faint.lua"
S.JSON_TAGS = {LINK_SAVE=true, ENGINE_FAINT=true, FAINT_SENT=true, PARTY_HP_WRITE=true, CLIENT=true, DUO_GEN2=true,
               SAVE_WITNESS=true, ENGINE_CAPTURE=true, MEMORIAL_PREIMAGE=true, MEMORIAL_ACK=true, B_ACTIVE=true,
               LINKED_ACTIVE=true, BATTLE_HOLD_WRITE=true, BATTLE_TRACE=true, NEXT_MON=true, REPLACED=true}

local function has(list, value)
    for _, v in ipairs(list or {}) do if v == value then return true end end
    return false
end

-- Engine read of the battle context (by symbol, never production's reads).
function S.engine_battle(h)
    local function b(name) return h.sym(name)[1] end
    return {cur_battle_mon=b("wCurBattleMon"), battle_mon_species=b("wBattleMonSpecies"), battle_mode=b("wBattleMode"),
            battle_type=b("wBattleType"), link_mode=b("wLinkMode")}
end

-- The first BATTLE_TRACE row after the landed battle write (rec.trace/rec.battle_write in duo_gen2_main.lua).
function S.after_write(rec)
    local w = rec.battle_write
    if not w then return nil end
    for _, row in ipairs(rec.trace or {}) do if row.seq > w.seq then return row end end
end

-- TRAINER-FAINT-LIVE-TURN (post-RC, OMP cx-4ece9985): pure per-frame sampler for the "enemy_faint" witness --
-- `h.sym` is its only IO, so this drives directly under a stubbed h.sym (Crystal's or Gold's real symbol
-- table), independent of the driving loop below. `gate` is the caller's S.TRAINER and h.rec.battle_write ~= nil
-- (never sampled in the wild scenario, never before the battle hold has written). `baseline` is the caller's
-- {species=, hp=} table or nil ("no witnessable baseline yet": a first read already at 0 is never a witness).
-- Returns the next baseline and, on a witnessed positive-to-zero transition of the SAME species (a switch
-- replaces the baseline instead of firing), a BATTLE_TRACE row -- never both: a witness always clears the
-- baseline it fired from, so a later switch has to arm a fresh one before it can witness again.
function S.sample_enemy_faint(h, gate, baseline, battle_mode, seq)
    if not (gate and battle_mode == 2) then return baseline, nil end
    local species = h.sym("wEnemyMonSpecies")[1]
    if species < 1 or species > 251 then return baseline, nil end
    local hp_bytes = h.sym("wEnemyMonHP", 0, 2)
    local hp = hp_bytes[1] * 256 + hp_bytes[2]
    if hp > 0 then
        if baseline and baseline.species == species then
            baseline.hp = hp
            return baseline, nil
        end
        return {species=species, hp=hp}, nil
    end
    if baseline and baseline.species == species then
        return nil, {seq=seq, what="enemy_faint", frame=h.frame(), battle_mode=battle_mode, species=species,
                      hp_before=baseline.hp, hp_after=hp, title=h.parts.title}
    end
    return baseline, nil
end

local function run_b(h, key, faint)
    local slot, mon = h.slot_of(key)
    if slot == nil then return false, "the linked mon left the party" end
    local active, next_mon, replaced
    local enemy_baseline   -- {species=, hp=}: the latest positive-HP reading for the currently tracked foe
                           -- (TRAINER-FAINT-LIVE-TURN); nil means "no witnessable baseline yet"
    local mode = S.TRAINER and 2 or 1
    if S.TRAINER then
        local walked, walk_why = h.to_trainer()
        if not walked then return false, "trainer walk failed: " .. tostring(walk_why) end
    end
    local function forced()
        for _, r in ipairs(h.rec.rx) do if r.cmd == "force_faint" and r.key == key then return true end end
        return false
    end
    local function queued()   -- the production client holds it for the battle hold (not the checkpoint)
        for _, w in ipairs(h.client.pending_battle_writes or {}) do if w.key == key then return true end end
        return false
    end
    local fought, why = h.sacrifice({target=slot, any_move=true, max_phase_frames=S.HOLD_FRAMES, trainer=S.TRAINER,
        hold=function()
            if not active then
                local e = S.engine_battle(h)
                if e.cur_battle_mon == slot and e.battle_mon_species == mon.species_id and e.battle_mode == mode
                   and e.link_mode == 0 then
                    e.frame, e.key, e.slot = h.frame(), key, slot
                    if S.TRAINER then
                        e.other_trainer_class, e.other_trainer_id = h.sym("wOtherTrainerClass")[1], h.sym("wOtherTrainerID")[1]
                    end
                    active = e
                    h.rec.trace_on = true
                    h.jlog("LINKED_ACTIVE", e)
                end
                return true
            end
            return not (forced() and queued())
        end,
        fainted=function() local row = S.after_write(h.rec) return row ~= nil and row.what == "faint" end,
        observed=function(point)
            if not h.rec.battle_write then return end
            if not next_mon and point.ui and point.ui.kind == "yes_no" and point.ui.prompt == "next_mon" then
                next_mon = {frame=h.frame()}
                h.jlog("NEXT_MON", next_mon)
            end
            local hp = point.active_slot ~= nil and point.party_hp[point.active_slot] or nil
            local forced_pick = S.TRAINER and S.after_write(h.rec) ~= nil   -- ForcePlayerMonChoice, no prompt
            if (next_mon or forced_pick) and not replaced and point.battle_mode ~= 0 and point.active_slot ~= slot and type(hp) == "number"
               and hp > 0 then
                replaced = {frame=h.frame(), active_slot=point.active_slot, hp=hp}
                h.jlog("REPLACED", replaced)
            end
            -- TRAINER-FAINT-LIVE-TURN: sampled only AFTER REPLACED (OMP cx-6387febc F2), so the witness is the
            -- replacement's KO of its foe; a pre-replacement enemy zero never arms a row both verdicts would refuse
            if h.rec.trace_on then
                local row
                enemy_baseline, row = S.sample_enemy_faint(h, S.TRAINER and replaced ~= nil, enemy_baseline,
                                                            point.battle_mode, h.rec.seq + 1)
                if row then
                    h.rec.seq = row.seq
                    h.rec.trace[#h.rec.trace + 1] = row
                    h.jlog("BATTLE_TRACE", row)
                end
            end
        end})
    h.rec.trace_on = false
    if not fought then return false, "active faint route failed: " .. tostring(why) end
    local hp, status, source = faint.bench_record(h, key)
    if hp == nil then return false, source end
    h.log(string.format("LINKED_HP_STATUS %04X %02X", hp, status))
    if hp ~= 0 or status ~= 0 then return false, "the active faint did not zero HP/status (" .. source .. ")" end
    return true
end

function S.run(h)
    local link, faint = dofile(h.root .. "/" .. S.LINK), dofile(h.root .. "/" .. S.FAINT)
    if not has(h.registered, "battle_faint") then return false, "production signals lack battle_faint" end
    h.jitter()
    local arrived, why = h.arrive()
    if not arrived then return false, "no CONTINUE arrival: " .. tostring(why) end
    h.party()
    if not h.wait(function() return h.sent.hello ~= nil end, S.HELLO_FRAMES) then return false, "the client never sent hello" end
    if not h.wait(h.go, S.GO_FRAMES) then return false, "no go-file" end
    local played, outcome = h.play({settled=h.link_settled})
    if not played then return false, "link route failed: " .. tostring(outcome) end
    h.party()
    local key = h.rec.caught
    if not key then return false, "no linked catch" end
    local saved, save_why = h.link_save(key)
    if not saved then return false, "link save: " .. tostring(save_why) end

    if h.player == "a" then
        if not h.wait(function() return h.file_has(h.go_file, "B_ACTIVE") end, S.ACTIVE_FRAMES) then
            return false, "runner never released A (B_ACTIVE)"
        end
        h.jlog("B_ACTIVE", {frame=h.frame()})
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
        local ok, b_why = run_b(h, key, faint)
        if not ok then return false, b_why end
    end
    if not h.wait(function() return h.rec.memorial[key] ~= nil end, S.MEMORIAL_FRAMES) then
        return false, "no memorialize ack for " .. key
    end
    local ack = h.rec.memorial[key]
    if ack.event ~= "memorialize_done" then return false, "memorialize failed: " .. tostring(ack.reason) end
    local resaved, resave_why = h.save()
    if not resaved then return false, "final save failed: " .. tostring(resave_why) end
    local witnessed, witness_why = h.witness()
    if not witnessed then return false, "save witness: " .. tostring(witness_why) end
    h.frames(S.SETTLE_FRAMES)
    local problems, receipt = S.verdict(h.lines, h.json, link.verdict, faint.verdict)
    if #problems > 0 then return false, table.concat(problems, "; ") end
    h.jlog("RECEIPT", receipt)
    return true, (h.player == "a" and "fainted " or "killed the active battler ") .. key
end

-- Pure: marker lines -> problems (empty = PASS) and the receipt. link_verdict / faint_verdict = the link and
-- faint scenarios' S.verdict (A's half IS the faint scenario's A half plus B_ACTIVE).
function S.verdict(lines, json, link_verdict, faint_verdict)
    local seen, rx, readback = {}, {}, {}
    local problems = {}
    local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
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
        elseif tag == "LINKED_HP_STATUS" then
            readback[#readback + 1] = {at=index, value=body}
        end
    end
    local function rows(tag) return seen[tag] or {} end
    local function one(tag)
        local r = rows(tag)
        need(#r == 1, #r == 0 and ("missing " .. tag .. " marker") or string.format("%d %s markers (expected one)", #r, tag))
        return r[1]
    end
    local head = rows("DUO_GEN2")[1]
    local player = head and head.value.player
    if player == "a" then
        local faint_problems, receipt = faint_verdict(lines, json, link_verdict)
        for _, p in ipairs(faint_problems) do problems[#problems + 1] = p end
        local go, link, faint = one("B_ACTIVE"), rows("LINK_SAVE")[1], rows("ENGINE_FAINT")[1]
        if go then
            need(link ~= nil and go.at > link.at, "B_ACTIVE before LINK_SAVE")
            need(faint ~= nil and go.at < faint.at and type(go.value.frame) == "number"
                 and go.value.frame <= faint.value.frame, "A's faint did not wait for B_ACTIVE")
        end
        if #problems > 0 then return problems, nil end
        receipt.schema, receipt.b_active = S.RECEIPT_SCHEMA, go.value
        return problems, receipt
    elseif player ~= "b" then
        need(false, "DUO_GEN2 names no player a|b")
        return problems, nil
    end

    local link_problems, link_receipt = link_verdict(lines, json)
    for _, p in ipairs(link_problems) do problems[#problems + 1] = p end
    local client, capture, save = rows("CLIENT")[1], rows("ENGINE_CAPTURE")[1], rows("SAVE_WITNESS")[1]
    local key = capture and capture.value.key
    need(client ~= nil and has(client.value.registered_sites, "battle_faint"), "production signals lack battle_faint")
    local link = one("LINK_SAVE")
    if link then
        local l = link.value
        need(l.key == key and type(key) == "string" and key:match(S.KEY) ~= nil, "LINK_SAVE names another key than the catch")
        need(l.saveram_bytes == S.SAVERAM_BYTES and l.cartram_bytes == 0x8000 and type(l.cartram_sha256) == "string"
             and #l.cartram_sha256 == 64, "LINK_SAVE incomplete")
        need(capture ~= nil and link.at > capture.at, "LINK_SAVE printed before the catch")
        if save then
            local s = save.value
            need(type(s.gate_saves) == "number" and type(l.gate_saves) == "number" and s.gate_saves > l.gate_saves
                 and type(s.client_saves) == "number" and type(l.client_saves) == "number" and s.client_saves > l.client_saves,
                 "no native save after LINK_SAVE")
        end
    end
    local active = one("LINKED_ACTIVE")
    if active then
        local a = active.value
        need(a.key == key and a.cur_battle_mon == a.slot and a.battle_mode == (S.TRAINER and 2 or 1) and a.link_mode == 0
             and capture ~= nil and a.battle_mon_species == capture.value.species_id,
             "LINKED_ACTIVE is not the linked catch as the active " .. (S.TRAINER and "trainer-battle" or "wild") .. " battler")
        if S.TRAINER then
            need(type(a.other_trainer_class) == "number" and a.other_trainer_class > 0 and type(a.other_trainer_id) == "number",
                 "LINKED_ACTIVE names no opposing trainer")
        end
        need(link ~= nil and active.at > link.at, "LINKED_ACTIVE before LINK_SAVE")
    end
    local got
    for _, r in ipairs(rx) do if r.key == key and got == nil then got = r end end
    need(got ~= nil, "no RX force_faint for B's linked key")
    need(got == nil or (active ~= nil and got.at > active.at), "force_faint arrived before LINKED_ACTIVE")
    local write = one("BATTLE_HOLD_WRITE")
    local w = write and write.value
    if w then
        need(w.ok == true and w.kind == "battle_faint" and w.key == key, "the battle hold write failed or hit another mon")
        need(active ~= nil and w.slot == active.value.slot and w.active_slot == w.slot, "the battle write missed the active slot")
        need(w.battle_hp_before_hex ~= "0000" and w.battle_hp_after_hex == "0000" and w.hp_after_hex == "0000"
             and w.status_after_hex == "00", "the battle write did not zero battle HP, party HP and status")
        need(w.action_after_hex == S.USEITEM, "wBattlePlayerAction is not USEITEM after the write")
        need(type(w.log) == "table" and #w.log == 4, "the write left no four-span permit receipt")
        need(got ~= nil and write.at > got.at, "the battle write precedes force_faint")
    end
    local replaced = one("REPLACED")
    -- the engine order: the first oracle hit after the write is HandlePlayerMonFaint, same frame; no whiteout
    local first
    for _, r in ipairs(rows("BATTLE_TRACE")) do
        need(r.value.what ~= "lost", "LostBattle ran (a whiteout)")
        if r.value.what == "enemy_faint" then
            -- TRAINER-FAINT-LIVE-TURN (post-RC, OMP cx-4ece9985): the SAME schema and chronology the Python
            -- oracle enforces, checked once here so the trainer branch below only tests "any row survived".
            need(S.TRAINER, "enemy_faint row in a wild scenario")
            need(r.value.battle_mode == 2, "enemy_faint row outside a trainer battle")
            need(type(r.value.species) == "number" and r.value.species >= 1 and r.value.species <= 251,
                 "enemy_faint row names no valid species")
            need(type(r.value.hp_before) == "number" and r.value.hp_before > 0, "enemy_faint row has no positive HP baseline")
            need(r.value.hp_after == 0, "enemy_faint row did not zero the foe")
            need(head ~= nil and r.value.title == head.value.title, "enemy_faint row names another title")
            need(type(r.value.frame) == "number" and type(r.value.seq) == "number", "enemy_faint row has a malformed seq/frame")
            need(replaced ~= nil and type(replaced.value.frame) == "number" and type(r.value.frame) == "number"
                 and r.value.frame > replaced.value.frame, "enemy_faint row is not strictly after the replacement")
        end
        if w and first == nil and type(r.value.seq) == "number" and r.value.seq > w.seq then first = r end
    end
    need(first ~= nil and first.value.what == "faint", "the first engine event after the write is not HandlePlayerMonFaint")
    if first and w then
        need(first.value.frame == w.frame and first.at > write.at, "HandlePlayerMonFaint not in the write's frame")
    end
    need(#rows("FAINT_SENT") == 0, "B sent a faint (the commanded echo must be dropped)")
    for _, r in ipairs(rows("ENGINE_FAINT")) do
        need(r.value.key == key and write ~= nil and r.at > write.at, "B's engine faint is not the commanded kill")
    end
    for _, r in ipairs(rows("PARTY_HP_WRITE")) do
        need(r.value.ok == true and r.value.before_party_hex == r.value.after_party_hex, "a checkpoint write changed B's party")
    end
    local next_mon
    if S.TRAINER then   -- ForcePlayerMonChoice with no prompt; then a live turn against the replacement: an
        -- enemy_turn, or a witnessed enemy_faint (both already schema/chronology-checked above).
        need(#rows("NEXT_MON") == 0, "NEXT_MON in a trainer battle")
        next_mon = first
        local live = false
        if replaced and type(replaced.value.frame) == "number" then
            for _, r in ipairs(rows("BATTLE_TRACE")) do
                live = live or ((r.value.what == "enemy_turn" or r.value.what == "enemy_faint")
                                and type(r.value.frame) == "number" and r.value.frame > replaced.value.frame)
            end
        end
        need(live, "no live enemy turn or witnessed enemy faint against the replacement")
    else
        next_mon = one("NEXT_MON")
    end
    if next_mon then need(first ~= nil and next_mon.at >= first.at, "NEXT_MON before the native faint") end
    if replaced then
        need(next_mon ~= nil and replaced.at > next_mon.at and active ~= nil
             and replaced.value.active_slot ~= active.value.slot and (tonumber(replaced.value.hp) or 0) > 0,
             "no living replacement after NEXT_MON")
    end
    need(#readback == 1, #readback == 0 and "missing LINKED_HP_STATUS marker" or "LINKED_HP_STATUS repeated")
    if readback[1] then
        need(readback[1].value == "0000 00", "linked record not at HP 0000 / status 00")
        need(replaced ~= nil and readback[1].at > replaced.at, "LINKED_HP_STATUS before the replacement")
    end
    local pre
    for _, r in ipairs(rows("MEMORIAL_PREIMAGE")) do if r.value.key == key then need(pre == nil, "MEMORIAL_PREIMAGE repeated"); pre = pre or r end end
    need(pre ~= nil and type(pre.value.raw_hex) == "string" and #pre.value.raw_hex == 96, "missing MEMORIAL_PREIMAGE for the linked key")
    local done
    for _, r in ipairs(rows("MEMORIAL_ACK")) do
        if r.value.key == key and r.value.event == "memorialize_done" and r.value.box == S.MEMORIAL_BOX then done = done or r end
    end
    need(done ~= nil, "no memorialize_done (box " .. S.MEMORIAL_BOX .. ") for the linked key")
    if pre and done then
        need(write ~= nil and pre.at > write.at and pre.at < done.at and save ~= nil and done.at < save.at,
             "memorial out of order (write < preimage < ack < final save)")
    end
    if w and save then
        need(type(save.value.save_completed_frame) == "number" and save.value.save_completed_frame > w.frame,
             "final save completed before the write")
    end
    if #problems > 0 then return problems, nil end
    local receipt = link_receipt
    receipt.schema, receipt.link_save, receipt.linked_active = S.RECEIPT_SCHEMA, link.value, active.value
    receipt.force_faint_key = got.key
    receipt.battle_write = {frame=w.frame, seq=w.seq, slot=w.slot, pc=w.pc, hrom_bank=w.hrom_bank,
                            battle_hp_before_hex=w.battle_hp_before_hex, action_after_hex=w.action_after_hex}
    receipt.native_faint, receipt.replaced = first.value, replaced.value
    if S.TRAINER then receipt.trainer = {class=active.value.other_trainer_class, id=active.value.other_trainer_id} end
    receipt.memorial = {preimage_frame=pre.value.frame, ack=done.value}
    return problems, receipt
end

return S
