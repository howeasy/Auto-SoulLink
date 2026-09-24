-- Gen 2 checkpoint policy over the shared GB evaluator. inspect_candidate() is SOURCE/MODEL
-- evidence and never authority. check(kind) authorizes ONLY behind a PHYSICAL write-window receipt
-- (M.qualified: schema gen2-write-window-receipt-v2, assembled by tests/live/test_gen2_write_windows.py
-- from the run records lua/tests/gen2_write_windows.lua printed on the running cartridge) and ONLY
-- for the write kinds that receipt proved (M.WRITE_KINDS: party HP, current-box deposit).
-- M.qualified never trusts a verdict: it recomputes every control from each run's raw records
-- (M.run_problem) and binds title, ROM, pack commit, fixture bytes, attempt ids, CGB, normal buttons
-- and the harness write scopes. evidence_level PHYSICAL comes only from the gate's own BizHawk
-- entry; a lupa/synthetic run is MODEL and can never authorize.
-- SCOPE: the pack's physical.status stays OPEN (source evidence for ALL of required_controls);
-- a receipt covers only M.COVERED_CONTROLS, and M.qualified returns the uncovered ones so U3 cannot
-- over-read it. Crystal and Gold carry their own receipts; Silver's pack rows equal Gold's (primary
-- is byte-identical), so a receipt from Gold's pinned ROM covers Silver ONLY while those rows stay
-- identical. Authorization is not admission: admission stays with admission.json / entry.lua (O-22, U3).
local M = {}
M.RECEIPT_SCHEMA = "gen2-write-window-receipt-v2"
M.RUN_SCHEMA = "gen2-write-window-run-v1"
-- title -> the title whose PHYSICAL receipt may authorize it (rows must still be identical).
M.RECEIPT_TITLE = {crystal="crystal", gold="gold", silver="gold"}
-- A receipt covering another title must come from this pinned ROM (that pack names only its own).
M.OWNER_ROM_SHA1 = {gold="d8b8a3600a465308c9953dfa04f0081c05bdcb94"}
M.WRITE_KINDS = {party_hp=true, box_deposit=true}
-- Card BOX: the kinds a receipt adds only with its three passed box runs (boxes, boxes_reset, boxes_reload):
-- the whole party block, an active sBox removal, and any non-current sBoxN (the memorial Box 14).
M.BOX_KINDS = {party_collection=true, box_withdraw=true, backing_box=true}
M.BOX_MODES = {"boxes", "boxes_reset", "boxes_reload"}
-- pack physical.required_controls a receipt may declare covered (every run below is required anyway).
M.COVERED_CONTROLS = {["idle reacquisition"]=true, ["warp/Continue"]=true}
M.RUNS = {town="_town", reload="_town", battle="_battle",
          boxes="_battle", boxes_reset="_battle", boxes_reload="_battle"}
-- The only harness scopes that may write bytes, per run (sorted).
M.TEST_SCOPES = {town={"u2-test-box-write", "u2-test-party-write"}, reload={}, battle={},
                 boxes={"u2-box-ops"}, boxes_reset={"u2-box-ops"}, boxes_reload={}}
-- tools/fixture_qualification.py FULL_CHAIN: the stages a full-scope qualification report ran.
M.FULL_CHAIN = {"qualify", "boot", "resave", "post_oracle"}
-- Negative windows per run: minimum frames (at least frames-1 of them open at both edges), the
-- predicates of which one must fail on EVERY window frame, and whether the anchor must stay silent.
-- START menu: CheckMenuOW -> CallScript sets wScriptRunning (C home/map.asm:925-935) and PlayerEvents
-- .ok sets wScriptMode (C engine/overworld/events.asm:271-276); the menu loop never reaches OWPlayerInput.
-- Save: SaveMenu PauseGameLogic spans 62+ frames (C engine/menus/save.asm:12-14,239-264; G :13,134-141).
M.WINDOWS = {
    town = {
        {name="start_menu", frames=30, stated={wScriptRunning=true, wScriptMode=true}, anchor_silent=true},
        {name="script_text", frames=30, stated={wScriptRunning=true, wScriptMode=true, wScriptFlags=true}},
        {name="save_paused", frames=2, stated={wGameLogicPaused=true}},
        {name="mid_warp", frames=2, stated={wMapStatus=true}},
    },
    reload = {},
    battle = {{name="battle", frames=30, stated={wBattleMode=true}}},
    boxes = {}, boxes_reset = {}, boxes_reload = {},
}
-- Idle reacquisition: the phase entered after each window saw a NEW accepted hold (driver order).
M.REACQUIRE = {
    town = {{"idle", "start_menu"}, {"face", "talk"}, {"to_save", "save"}, {"post_save", "exit"}, {"post_warp", "done"}},
    reload = {{"idle", "done"}},
    battle = {{"idle", "walk"}, {"post_battle", "done"}},
    boxes = {{"idle", "walk"}, {"post_save", "ops"}},
    boxes_reset = {{"idle", "ops"}, {"post_save", "done"}},
    boxes_reload = {{"idle", "done"}},
}
-- The box runs: production-executor ops, one per accepted hold, on the two scripted catches (key 1, key 2).
-- written = the permit kinds in write order (deposit/memorial: box first; withdraw: party first); party =
-- the party-count change; box = the ONE region whose bytes change ("active" sBox or the "memorial" sBox14)
-- and its count change. boxes ends with an unsaved active edit (C1 in sBox) and a backing edit (C2 in
-- sBox14): its CartRAM is flushed WITHOUT a save and cold-booted as boxes_reset, the reset-before-save
-- control. boxes_reset runs three stages (gen2-box-deferral-live): (1) the memorial completes party-only
-- (full-record match), a DEFERRED withdraw from sBox14 writes the party only (the box copy stays: a
-- duplicate), box_mon; native SAVE. (2) the settle drops the sBox14 copy (party untouched), memorialize
-- again; native SAVE. (3) a deferred withdraw from sBox14, then the CartRAM is flushed WITHOUT a save:
-- boxes_reload cold-boots it and must find the mon exactly once, back in sBox14.
M.BOX_OPS = {
    boxes = {
        {op="deposit", key=1, written={"box_deposit", "party_collection"}, party=-1, box="active", count=1},
        {op="withdraw", key=1, written={"party_collection", "box_withdraw"}, party=1, box="active", count=-1},
        {op="memorialize", key=2, written={"backing_box", "party_collection"}, party=-1, box="memorial", count=1},
        {op="deposit", key=1, written={"box_deposit", "party_collection"}, party=-1, box="active", count=1},
    },
    boxes_reset = {
        {op="memorialize", key=2, stage=1, written={"party_collection"}, party=-1},
        {op="withdraw", key=2, stage=1, defer=true, written={"party_collection"}, party=1},
        {op="deposit", key=1, stage=1, written={"box_deposit", "party_collection"}, party=-1, box="active", count=1},
        {op="settle", key=2, stage=2, written={"backing_box"}, party=0, box="memorial", count=-1},
        {op="memorialize", key=2, stage=2, written={"backing_box", "party_collection"}, party=-1, box="memorial", count=1},
        {op="withdraw", key=2, stage=3, defer=true, written={"party_collection"}, party=1},
    },
}
M.PARTY_BLOCK, M.BOX_COPY = 428, 1102
local COUNT = 9007199254740991
-- O-30 in-battle faint (docs/gen2/reviews/INBATTLE_FAINT_FACTS_2026-09-23.md): a write kind held at the
-- pack's battle_hold (before `call DetermineMoveOrder` in BattleTurn), never at the overworld primary. A
-- receipt adds it only with its own passed battle run (phase 4); until then check() refuses it.
M.BATTLE_KINDS = {battle_faint=true}
local REQUIRED = {
    wMapStatus=true, wMapEventStatus=true, wScriptRunning=true, wScriptMode=true,
    wScriptFlags=true, wScriptStackSize=true, wJoypadDisable=true, wGameLogicPaused=true,
    wInputType=true, wBattleMode=true, wStateFlags=true, hMapEntryMethod=true,
    wLinkMode=true, hSerialConnectionStatus=true, wSavedAtLeastOnce=true,
}
local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end
local function masked(value, mask)
    local result, place = 0, 1
    for _ = 1, 8 do
        if value % 2 == 1 and mask % 2 == 1 then result = result + place end
        value, mask, place = math.floor(value / 2), math.floor(mask / 2), place * 2
    end
    return result
end
local function same(a, b)
    if type(a) ~= type(b) then return false end
    if type(a) ~= "table" then return a == b end
    for key, value in pairs(a) do if not same(value, b[key]) then return false end end
    for key in pairs(b) do if a[key] == nil then return false end end
    return true
end
local function hex64(value) return type(value) == "string" and #value == 64 and value:match("^%x+$") ~= nil end
local function hexbytes(value, n)
    return type(value) == "string" and #value > 0 and #value % 2 == 0 and value:match("^%x+$") ~= nil
        and (n == nil or #value == 2 * n)
end
local function named(value) return type(value) == "string" and value ~= "" end
local function plain_array(value)
    if type(value) ~= "table" then return false end
    local count = 0
    for _ in pairs(value) do count = count + 1 end
    return count == #value
end

-- Symbols of the pack's state predicates that `read` refuses, in pack order. Pure.
function M.failing_predicates(primary, read)
    local failed = {}
    for _, condition in ipairs(primary.state_predicates) do
        if masked(read(condition.address, condition.read_domain), condition.mask) ~= condition.value then
            failed[#failed + 1] = condition.symbol
        end
    end
    return failed
end

local function window_problem(mode, want, w)
    local name = want.name
    if type(w) ~= "table" or not integer(w.frames, want.frames, COUNT) then
        return name .. " window not observed for " .. want.frames .. " frames"
    end
    if not integer(w.both_edges, want.frames - 1, w.frames - 1) or not integer(w.raw, 0, COUNT) or w.accepted ~= 0 then
        return name .. ": no accepted checkpoint hold inside the window"
    end
    if want.anchor_silent and w.raw ~= 0 then
        return name .. ": the OWPlayerInput anchor fired inside the window"
    end
    local frames = 0
    for _, set in ipairs(type(w.failing_sets) == "table" and w.failing_sets or {}) do
        local hit = false
        for _, symbol in ipairs(type(set) == "table" and type(set.symbols) == "table" and set.symbols or {}) do
            if want.stated[symbol] and REQUIRED[symbol] then hit = true end
        end
        if not hit or not integer(set.frames, 1, COUNT) then break end
        frames = frames + set.frames
    end
    if frames ~= w.frames then return name .. ": the stated predicate refuses every window frame" end
    local write = w.write
    if type(write) ~= "table" or write.refused ~= true or not hexbytes(write.before_hex, 2)
       or write.after_hex ~= write.before_hex then
        return name .. ": a party write attempt is refused and reads back unchanged"
    end
    if mode == "battle" and write.faint_refused ~= true then
        return name .. ": faint_party_slot refuses the active slot"
    end
end

-- nil, or why the raw measurements of one gate run (`mode`) do not prove its controls. Pure; ignores
-- evidence_level/result/bindings (M.qualified checks those). The gate calls it for its own verdict.
function M.run_problem(run, mode, primary)
    if type(run) ~= "table" or not M.RUNS[mode] then return "run record missing" end
    local pc, bank = primary.execution_before.pc, primary.execution_before.bank
    local live = run.liveness
    if type(live) ~= "table" or not integer(live.accepted, 1, COUNT) or type(live.hits) ~= "table"
       or type(live.hits[1]) ~= "table" then
        return "no accepted checkpoint hold"
    end
    for _, hit in ipairs(live.hits) do
        if type(hit) ~= "table" or hit.pc ~= pc or hit.bank ~= bank then
            return "an accepted hold ran at a measured PC/hROMBank other than the checkpoint"
        end
    end
    local at = {}
    for _, entry in ipairs(type(run.phases) == "table" and run.phases or {}) do
        if type(entry) ~= "table" or not named(entry.phase) then return "a phase entry names no phase" end
        if at[entry.phase] == nil then at[entry.phase] = entry.accepted end
    end
    for _, pair in ipairs(M.REACQUIRE[mode]) do
        local before, after = at[pair[1]], at[pair[2]]
        if not integer(before, 0, COUNT) or not integer(after, 0, COUNT) or after <= before then
            return "no fresh accepted hold between phases " .. pair[1] .. " and " .. pair[2]
        end
    end
    for _, want in ipairs(M.WINDOWS[mode]) do
        local problem = window_problem(mode, want, type(run.windows) == "table" and run.windows[want.name])
        if problem then return problem end
    end
    if mode == "town" then
        local w = type(run.write) == "table" and run.write or {}
        local p, b, save = w.party, w.box, run.save
        if type(p) ~= "table" or not hexbytes(p.before_hex, 2) or tonumber(p.before_hex, 16) < 2
           or p.written_hex ~= string.format("%04x", tonumber(p.before_hex, 16) - 1) or p.readback_hex ~= p.written_hex then
            return "idle hold party write is not a read-back HP-1"
        end
        if type(b) ~= "table" or b.owner ~= "active" or not hexbytes(b.before_hex)
           or not hexbytes(b.after_hex, #b.before_hex // 2) or b.readback_hex ~= b.after_hex
           or tonumber(b.after_hex:sub(1, 2), 16) ~= tonumber(b.before_hex:sub(1, 2), 16) + 1 then
            return "idle hold deposit is not a read-back count+1 write to the authoritative sBox"
        end
        if not hexbytes(b.backing_before_hex, #b.after_hex // 2) or b.backing_before_hex == b.after_hex then
            return "the backing box slot already held the deposit before the save"
        end
        if type(save) ~= "table" or save.flushed ~= true or not hex64(save.cartram_sha256) then
            return "native save not flushed"
        end
    elseif M.BOX_OPS[mode] then
        local problem = M.box_ops_problem(run, mode)
        if problem then return problem end
        local save = run.save
        if type(save) ~= "table" or save.flushed ~= true or not hex64(save.cartram_sha256) then
            return "native save not flushed"
        end
        local last = mode == "boxes" and save or run.save2
        if type(last) ~= "table" or last.flushed ~= true or not hex64(last.cartram_sha256) then
            return "second native save not flushed"
        end
        local reset = run.reset
        if type(reset) ~= "table" or reset.flushed ~= true or not hex64(reset.cartram_sha256) then
            return "the unsaved post-op CartRAM was not flushed for the reset control"
        end
        -- boxes ends with unsaved sBox/sBox14 edits, so its SRAM differs from the save. boxes_reset ends
        -- with a DEFERRED withdraw, a WRAM-only write: its op record changed no box region (box_ops_problem).
        -- No whole-image equality there: Gold/Silver rewrite sScratch (the window stack) after a save
        -- (live Gold box run: 279 bytes, all sScratch), so the hashes differ without any SLink write.
        if mode == "boxes" and reset.cartram_sha256 == last.cartram_sha256 then
            return "the unsaved post-op CartRAM was not flushed for the reset control"
        end
        if mode == "boxes" then
            local catch = run.catch
            if type(catch) ~= "table" or not integer(catch.party_before, 1, 4) or catch.party_after ~= catch.party_before + 2 then
                return "the two scripted catches did not land in the party"
            end
        else
            local k = run.control
            if not hex64(run.boot_cartram_sha256) or type(k) ~= "table" or not hexbytes(k.party_hex, M.PARTY_BLOCK)
               or not hexbytes(k.active_hex, M.BOX_COPY) or not hexbytes(k.backing_hex, M.BOX_COPY)
               or not hexbytes(k.memorial_hex, M.BOX_COPY) then
                return "reset control lacks the booted CartRAM hash or the post-CONTINUE bytes"
            end
        end
    elseif mode == "boxes_reload" then
        local keep = run.persist
        if not hex64(run.boot_cartram_sha256) or type(keep) ~= "table" or not hexbytes(keep.party_hex, M.PARTY_BLOCK)
           or not hexbytes(keep.active_hex, M.BOX_COPY) or not hexbytes(keep.backing_hex, M.BOX_COPY)
           or not hexbytes(keep.memorial_hex, M.BOX_COPY) then
            return "box reload lacks the booted CartRAM hash or the persisted bytes"
        end
    elseif mode == "reload" then
        local keep = run.persist
        if not hex64(run.boot_cartram_sha256) or type(keep) ~= "table" or not hexbytes(keep.party_hp_hex, 2)
           or not hexbytes(keep.active_box_hex) or keep.backing_box_hex ~= keep.active_box_hex then
            return "reload lacks the booted CartRAM hash or the persisted bytes"
        end
    end
    return nil
end

-- nil, or why a box run's ops do not prove M.BOX_OPS[mode]: each op ok, written in the stated kind order,
-- the party count moved by its delta, exactly its one box region changed (count moved), ops chained (each
-- op's party preimage is the previous op's readback) and the two catch keys distinct. Pure.
function M.box_ops_problem(run, mode)
    local want, layout, ops = M.BOX_OPS[mode], run.layout, run.ops
    if type(layout) ~= "table" or not integer(layout.active_flat, 0, 32768 - M.BOX_COPY)
       or not integer(layout.memorial_flat, 0, 32768 - M.BOX_COPY) or layout.active_flat == layout.memorial_flat
       or not integer(layout.current_box, 0, 12) then
        return "box layout missing, or the memorial box is the current box"
    end
    if not plain_array(ops) or #ops ~= #want then return "box ops are not the stated sequence" end
    local keys = {}
    for i, w in ipairs(want) do
        local op = ops[i]
        local name = "op " .. i .. " " .. w.op
        if type(op) ~= "table" or op.op ~= w.op or op.ok ~= true or not named(op.key) then return name .. " did not succeed" end
        keys[w.key] = keys[w.key] or op.key
        if keys[w.key] ~= op.key then return name .. " targets another key" end
        local written = op.written
        local exact = plain_array(written) and #written == #w.written
        for j, kind in ipairs(w.written) do exact = exact and written[j] == kind end
        if not exact then return name .. " wrote other kinds than " .. table.concat(w.written, "+") end
        if (op.stage or 1) ~= (w.stage or 1) or (op.deferred == true) ~= (w.defer == true) then
            return name .. " ran in another stage or without its deferral"
        end
        if not hexbytes(op.party_before_hex, M.PARTY_BLOCK) or not hexbytes(op.party_after_hex, M.PARTY_BLOCK)
           or tonumber(op.party_after_hex:sub(1, 2), 16) ~= tonumber(op.party_before_hex:sub(1, 2), 16) + w.party then
            return name .. " did not move the party count by " .. w.party
        end
        if i > 1 and op.party_before_hex ~= ops[i - 1].party_after_hex then return name .. " party changed between ops" end
        local changed = op.changed
        if not plain_array(changed) or #changed ~= (w.box and 1 or 0) then return name .. " changed other box regions" end
        if w.box then
            local c = changed[1]
            if type(c) ~= "table" or c.flat ~= layout[w.box .. "_flat"] or not hexbytes(c.before_hex, M.BOX_COPY)
               or not hexbytes(c.after_hex, M.BOX_COPY)
               or tonumber(c.after_hex:sub(1, 2), 16) ~= tonumber(c.before_hex:sub(1, 2), 16) + w.count then
                return name .. " did not move the " .. w.box .. " box count by " .. w.count
            end
        end
    end
    if keys[1] == keys[2] then return "the two catch keys are not distinct" end
    return nil
end

-- scope, or nil,why: `receipt` is a PHYSICAL write-window receipt that may authorize `title`.
-- scope = {kinds=M.WRITE_KINDS, covered={declared, proven}, uncovered={pack controls still OPEN}}.
function M.qualified(pack, title, receipt)
    local owner = M.RECEIPT_TITLE[title]
    if not owner then return nil, "no PHYSICAL write-window receipt path for " .. tostring(title) end
    if type(receipt) ~= "table" or receipt.schema ~= M.RECEIPT_SCHEMA or type(receipt.runs) ~= "table" then
        return nil, "PHYSICAL write-window receipt required"
    end
    local data = type(pack) == "table" and type(pack.titles) == "table" and pack.titles[title]
    if type(data) ~= "table" or type(pack.source) ~= "table" or type(data.physical) ~= "table"
       or type(data.physical.required_controls) ~= "table" then
        return nil, "write-window receipt needs this title's checkpoint pack"
    end
    local rom = owner == title and pack.source.rom_sha1 or M.OWNER_ROM_SHA1[owner]
    if receipt.title ~= owner or receipt.rom_sha1 ~= rom or receipt.pack_commit ~= pack.source.commit then
        return nil, "write-window receipt belongs to another title, ROM or pack"
    end
    if not same(receipt.checkpoint, data.primary) then
        return nil, "write-window receipt proved other checkpoint rows than this pack's"
    end
    local runs, ids = receipt.runs, {}
    local function bound(mode)
        local run = runs[mode]
        if type(run) ~= "table" or run.schema ~= M.RUN_SCHEMA or run.mode ~= mode
           or run.evidence_level ~= "PHYSICAL" or run.result ~= "PASS" then
            return "write-window receipt " .. mode .. " run is not a passed PHYSICAL gate run"
        end
        if run.title ~= owner or run.rom_sha1 ~= rom or run.pack_commit ~= pack.source.commit
           or run.fixture ~= owner .. M.RUNS[mode] or run.core_mode ~= "CGB" or run.input_mode ~= "normal_buttons"
           or not hex64(run.fixture_sha256) or not named(run.attempt_id) or ids[run.attempt_id]
           or not named(run.qualification_attempt_id) then
            return "write-window receipt " .. mode .. " run is not bound to this title, ROM, pack and qualified "
                .. "fixture as a normal-button CGB run with its own attempt"
        end
        ids[run.attempt_id] = true
        local scopes, want = run.harness_write_scopes, M.TEST_SCOPES[mode]
        local exact = plain_array(scopes) and #scopes == #want
        for i, scope in ipairs(want) do exact = exact and scopes[i] == scope end
        if not exact then
            return "write-window receipt " .. mode .. " run wrote outside the declared test scopes"
        end
        local problem = M.run_problem(run, mode, data.primary)
        if problem then return "write-window receipt " .. mode .. " run: " .. problem end
    end
    for _, mode in ipairs({"town", "reload", "battle"}) do
        local problem = bound(mode)
        if problem then return nil, problem end
    end
    local town, reload = runs.town, runs.reload
    local box, keep = town.write.box, reload.persist
    if reload.qualification_attempt_id ~= town.qualification_attempt_id or reload.fixture_sha256 == town.fixture_sha256
       or reload.boot_cartram_sha256 ~= town.save.cartram_sha256 then
        return nil, "write-window receipt reload did not cold-boot the town run's flushed save"
    end
    if keep.current_box ~= box.current_box or keep.party_hp_hex ~= town.write.party.written_hex
       or keep.active_box_hex ~= box.after_hex then
        return nil, "write-window receipt lacks the save/reload persistence proof"
    end
    local required, covered, list, uncovered = {}, {}, {}, {}
    for _, control in ipairs(data.physical.required_controls) do required[control] = true end
    for _, control in ipairs(type(receipt.covered_controls) == "table" and receipt.covered_controls or {}) do
        if not M.COVERED_CONTROLS[control] or not required[control] or covered[control] then
            return nil, "write-window receipt declares a control it did not prove: " .. tostring(control)
        end
        covered[control], list[#list + 1] = true, control
    end
    for _, control in ipairs(data.physical.required_controls) do
        if not covered[control] then uncovered[#uncovered + 1] = control end
    end
    table.sort(list)
    local kinds = {}
    for kind in pairs(M.WRITE_KINDS) do kinds[kind] = true end
    if runs.boxes ~= nil or runs.boxes_reset ~= nil or runs.boxes_reload ~= nil then
        -- All three or the receipt refuses: a partial box proof never falls back to the base kinds.
        for _, mode in ipairs(M.BOX_MODES) do
            local problem = bound(mode)
            if problem then return nil, problem end
        end
        local problem = M.box_chain_problem(runs.boxes, runs.boxes_reset, runs.boxes_reload)
        if problem then return nil, "write-window receipt box runs: " .. problem end
        for kind in pairs(M.BOX_KINDS) do kinds[kind] = true end
    end
    return {kinds=kinds, covered=list, uncovered=uncovered}
end

-- nil, or why the three box runs are not ONE chain: the reset control cold-booted the unsaved post-op
-- CartRAM of boxes (active edit gone: party = the saved one, active sBox = its backing slot = the pre-op
-- bytes; backing edit kept: sBox14 = the memorialize readback), and the reload cold-booted the reset
-- run's flushed SAVE with exactly its final party, active sBox (= backing slot, SaveBox) and sBox14. Pure.
function M.box_chain_problem(boxes, reset, reload)
    local a, b = boxes.ops, reset.ops
    for _, run in ipairs({reset, reload}) do
        for _, key in ipairs({"active_flat", "memorial_flat", "current_box"}) do
            if type(run.layout) ~= "table" or run.layout[key] ~= boxes.layout[key] then
                return "the runs disagree on the box layout"
            end
        end
        if run.qualification_attempt_id ~= boxes.qualification_attempt_id then return "the runs name other qualifications" end
    end
    if reset.boot_cartram_sha256 ~= boxes.reset.cartram_sha256 or reset.fixture_sha256 == boxes.fixture_sha256 then
        return "the reset control did not cold-boot the unsaved post-op CartRAM"
    end
    local k = reset.control
    if k.party_hex ~= a[1].party_before_hex then return "reset control: the party is not the saved one" end
    if k.active_hex ~= k.backing_hex or k.active_hex ~= a[1].changed[1].before_hex then
        return "reset control: the active sBox is not its backing slot's saved bytes"
    end
    if k.active_hex == a[4].changed[1].after_hex then return "reset control: the unsaved active edit is indistinguishable" end
    if k.memorial_hex ~= a[3].changed[1].after_hex or k.memorial_hex == a[3].changed[1].before_hex then
        return "reset control: the backing (memorial) edit did not survive the reset"
    end
    if b[1].party_before_hex ~= k.party_hex then return "reset ops did not start from the control party" end
    -- the deferred withdraw left the durable copy untouched through the SAVE until the settle
    if b[4].changed[1].before_hex ~= k.memorial_hex then
        return "the deferred withdraw removed the sBox14 copy before the save witness"
    end
    if reload.boot_cartram_sha256 ~= reset.reset.cartram_sha256 or reload.fixture_sha256 == reset.fixture_sha256 then
        return "the reload did not cold-boot the reset run's unsaved final CartRAM"
    end
    local keep = reload.persist
    if keep.party_hex ~= b[5].party_after_hex or keep.active_hex ~= b[3].changed[1].after_hex
       or keep.backing_hex ~= keep.active_hex then
        return "the reload lacks the saved party or active/backing box bytes"
    end
    -- a reset after a deferred withdraw: the mon is back in sBox14 only (never lost, never twice)
    if keep.memorial_hex ~= b[5].changed[1].after_hex or keep.party_hex == b[6].party_after_hex then
        return "the reset after a deferred withdraw did not leave the mon exactly once, in sBox14"
    end
    return nil
end

-- U3 binding: true when the receipt's town and battle runs ran on exactly the fixture bytes a passed
-- full-chain qualification report (tests/fixtures/gen2/receipts/<fixture>.qualification.json, decoded
-- by the caller into reports[<fixture>]) recorded, from that report's attempt; else nil,why. Pure.
function M.bind_fixture_qualification(receipt, reports)
    if type(receipt) ~= "table" or type(receipt.runs) ~= "table" or type(reports) ~= "table" then
        return nil, "receipt and qualification reports required"
    end
    for _, mode in ipairs({"town", "battle", "boxes"}) do
        local run = receipt.runs[mode]
        if mode == "boxes" and run == nil then break end
        local report = type(run) == "table" and reports[run.fixture]
        if type(report) ~= "table" or report.schema ~= "fixture-qualification-v1" or report.passed ~= true
           or type(report.errors) ~= "table" or next(report.errors) ~= nil then
            return nil, mode .. ": fixture qualification report did not pass"
        end
        local stages = report.required_stages
        local full = report.scope == "full" and plain_array(stages) and #stages == #M.FULL_CHAIN
        for i, stage in ipairs(M.FULL_CHAIN) do full = full and stages[i] == stage end
        if not full then return nil, mode .. ": fixture qualification report is not a full-chain report" end
        if not named(report.attempt_id) or report.attempt_id ~= run.qualification_attempt_id then
            return nil, mode .. ": run names another qualification attempt"
        end
        local rows = report.fixtures
        local row = type(rows) == "table" and #rows == 1 and rows[1]
        local artifact = type(row) == "table" and type(row.artifacts) == "table" and row.artifacts.fixture
        local provenance = type(row) == "table" and row.provenance
        if type(artifact) ~= "table" or type(provenance) ~= "table" or row.passed ~= true or row.name ~= run.fixture
           or provenance.title ~= run.title or provenance.rom_sha1 ~= run.rom_sha1 then
            return nil, mode .. ": qualification report has no passed row for the run's fixture, title and ROM"
        end
        if not hex64(run.fixture_sha256) or artifact.sha256 ~= run.fixture_sha256 then
            return nil, mode .. ": run ran on other fixture bytes than the qualified ones"
        end
    end
    return true
end

function M.new(pack, title, io, evaluator, ownership, receipt)
    assert(type(evaluator) == "table" and type(evaluator.check) == "function", "shared GB evaluator required")
    assert(type(ownership) == "table", "explicit host ownership observations required")
    for _, name in ipairs({"capture", "valid", "admitted", "no_conflicting_owner",
                           "mapped_rom_bank", "effective_wram_bank"}) do
        assert(ownership[name] ~= nil, name .. " observation required")
    end
    local self = {}
    local evaluate
    local scope, unqualified
    if receipt == nil then
        unqualified = "Gen 2 checkpoint is SOURCE_CANDIDATE; runtime qualification is OPEN"
    else
        local ok, result, why = pcall(M.qualified, pack, title, receipt)
        if ok then scope, unqualified = result, why
        else unqualified = "malformed write-window receipt: " .. tostring(result) end
    end
    -- The runtime authority for one write kind: the same held evaluation inspect_candidate reports,
    -- but only behind the PHYSICAL receipt and only for a kind it proved. Must run inside the
    -- synchronous CPU hold at the checkpoint PC.
    function self:check(kind)
        if not scope then return false, unqualified end
        if not scope.kinds[kind] then return false, "write kind not covered by the PHYSICAL receipt: " .. tostring(kind) end
        local ok, matches, why = pcall(evaluate, M.BATTLE_KINDS[kind] and "battle_hold" or "primary")
        if not ok then return false, "checkpoint evidence unavailable: " .. tostring(matches) end
        return matches == true, why
    end
    -- Whether the receipt proved `kind` at all (no checkpoint evaluation): a command needing an unproven
    -- kind is refused outright instead of waiting for a hold that can never authorize it.
    function self:covers(kind) return scope ~= nil and scope.kinds[kind] == true end
    function self:inspect_candidate(hold)
        local ok, matches, why = pcall(evaluate, hold or "primary")
        return {candidate_match=ok and matches == true, runtime_authorized=false,
            evidence_level="SOURCE_MODEL", physical_status="OPEN",
            reason=ok and why or ("checkpoint evidence unavailable: " .. tostring(matches))}
    end
    -- hold: "primary" (the overworld checkpoint) or "battle_hold" (O-30); each names its own anchors
    -- and predicate set, the rest of the held-execution contract is shared.
    local HOLDS = {
        primary = {anchors={"ow_player_input", "player_events_caller"}, required=REQUIRED, count=15},
        battle_hold = {anchors={"battle_turn", "start_battle_caller"}, required={wLinkMode=true}, count=1},
    }
    function evaluate(which)
        local shape = assert(HOLDS[which], "unknown checkpoint hold")
        do
            assert(type(pack) == "table" and pack.schema == "gen2-write-checkpoint-v1", "unsupported Gen 2 checkpoint pack")
            assert(type(title) == "string" and type(pack.titles) == "table", "selected title required")
            local count = 0
            for key in pairs(pack.titles) do count = count + 1; assert(key == title, "checkpoint title mismatch") end
            assert(count == 1, "exactly one selected checkpoint title required")
            local data = assert(pack.titles[title], "checkpoint title missing")
            -- The pack stays SOURCE_CANDIDATE/OPEN even behind a receipt: the receipt authorizes only
            -- its proven write kinds and leaves scope.uncovered OPEN (see the header).
            assert(data.runtime_authorized == false and data.maturity == "SOURCE_CANDIDATE"
                and data.physical.status == "OPEN", "source-candidate authorization metadata differs")
            local primary = assert(data[which], "source checkpoint unavailable")
            assert(primary.acceptance == "ALL_REQUIRED_SAME_HELD_EXECUTION", "held execution contract required")
            local owner = assert(primary.ownership_requirements, "game ownership facts required")
            assert(owner.cached_frame_acceptance_allowed == false and owner.mapped_rom_bank_must_equal_shadow == true,
                "fresh bank/ownership policy required")
            local held = ownership.capture()
            assert(held ~= nil and ownership.valid(held) == true, "synchronous CPU hold unavailable")
            assert(ownership.admitted(title, pack.source.rom_sha1) == true, "exact admitted identity unavailable")
            assert(ownership.no_conflicting_owner() == true, "another writer, save or trade owns the game")
            local function banks_match()
                return ownership.mapped_rom_bank() == owner.mapped_rom_bank
                    and ownership.effective_wram_bank() == owner.effective_wram_bank
            end
            assert(banks_match(), "mapped bank evidence differs")
            assert(primary.execution_before.bank == owner.mapped_rom_bank, "checkpoint bank facts differ")
            local rom_size = io.domain_size("ROM")
            assert(integer(rom_size, 1, 0x800000), "actual ROM domain size unavailable")
            local anchors = {}
            for _, name in ipairs(shape.anchors) do
                local anchor = assert(primary.anchors[name], "required source anchor missing")
                assert(anchor.bank == owner.mapped_rom_bank and anchor.instruction_set == "SM83", "anchor bank/instruction set differs")
                anchors[#anchors + 1] = {domain="ROM", address=anchor.rom_offset, expected_hex=anchor.expected_hex}
                anchors[#anchors + 1] = {domain="System Bus", address=anchor.address, expected_hex=anchor.expected_hex}
            end
            local stack = primary.caller_stack
            assert(stack.search_for_return_address == false and stack.must_fit_entire_read == true
                and stack.read_domain == "System Bus", "bounded source caller contract required")
            assert(type(stack.required_words) == "table" and getmetatable(stack.required_words) == nil,
                "caller words require a plain array")
            local word_count, last_word = 0, 0
            for key in next, stack.required_words do
                assert(integer(key, 1, 65536), "caller words have an invalid index")
                word_count, last_word = word_count + 1, math.max(last_word, key)
            end
            assert(word_count > 0 and word_count == last_word, "caller words are empty or sparse")
            local words = {}
            for _, word in ipairs(stack.required_words) do
                assert(word.endianness == "little", "source caller is not little-endian")
                words[#words + 1] = {offset=word.offset_from_sp, values={word.value}}
            end
            local seen, count_predicates = {}, 0
            for key, condition in pairs(primary.state_predicates) do
                assert(integer(key, 1, 15) and type(condition) == "table" and shape.required[condition.symbol]
                    and not seen[condition.symbol], "missing, duplicate or unknown game predicate")
                seen[condition.symbol], count_predicates = true, count_predicates + 1
                assert(condition.width == 1 and condition.operator == "masked_equal"
                    and condition.read_domain == "System Bus" and integer(condition.mask, 1, 255)
                    and integer(condition.value, 0, 255), "unsupported game predicate")
            end
            assert(count_predicates == shape.count, "complete Gen 2 state predicate required")
            local spec = {
                domains={ROM={first=0, limit=rom_size}, ["System Bus"]={first=0, limit=0x10000}},
                anchors=anchors, pc=primary.execution_before.pc,
                stack={domain=stack.read_domain, minimum_sp=stack.minimum_sp,
                    exclusive_end=stack.exclusive_stack_end, read_bytes=stack.required_read_bytes, words=words},
            }
            local accepted, reason = evaluator.check(spec, io, function(read)
                local shadow = owner.rom_bank_shadow
                if read(shadow.address, "System Bus") ~= shadow.equals then return false, "ROM bank shadow differs" end
                local bank = read(owner.wram_bank_register.address, "System Bus") % 8
                if bank == 0 then bank = 1 end
                if bank ~= owner.effective_wram_bank then return false, "effective WRAM bank differs" end
                local serial = owner.serial_control
                if masked(read(serial.address, "System Bus"), serial.mask) ~= serial.value then
                    return false, "serial transfer owns the game"
                end
                local failed = M.failing_predicates(primary, read)
                if failed[1] then return false, failed[1] .. " predicate refused" end
                if not banks_match() or ownership.valid(held) ~= true
                    or ownership.admitted(title, pack.source.rom_sha1) ~= true
                    or ownership.no_conflicting_owner() ~= true then
                    return false, "held identity, bank or ownership changed"
                end
                return true
            end)
            return accepted, reason
        end
    end
    return self
end
return M
