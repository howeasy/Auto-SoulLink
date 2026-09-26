-- lua/tests/gen3_battle_window_rows.lua -- G4 2b battle-window matrix: read-only samples, row
-- witnesses and receipt lines (card 2B-OBS; docs/gen3/research/g4_2b_matrix_plan_2026-09-23.md).
-- Pure module: no emulator calls, no writes, no inputs. The caller (probe/duo integration) owns
-- state loading, joypad and the frame loop; it calls ctx:sample() once per witnessed frame and
-- feeds every sample to each row accumulator it runs.
--
-- Verdicts: the permit answer and the sorted failing-clause list come from lua/gen3/safety.lua
-- (safety:check + last_clauses), never from a second predicate here. Addresses come from the pack
-- (write_checkpoint.json battle block, predicates, tasks), gen3_title_syms.lua and
-- gen3_battle_window_syms.lua (the object-span-disambiguated controller symbols).
--
-- Row model: arm(s) opens a window on a qualifying sample; while open, done(s) closes it with the
-- row's required terminal and hold(s) (default: arm) keeps it open. Every sample inside a window is
-- judged: it must be refused, and every clause in must_fail must be among safety's failures.
-- Zero qualifying samples, a floor not met, or a required terminal never seen => UNREACHED;
-- an admitted or misattributed sample, or a pack missing any of the seven clauses => FAIL.
local R = {}

-- §1 aliases, in plan order: every sample carries all seven.
R.ALIASES = {
    {"M", "battle_main_func"}, {"C", "battle_comm_0"}, {"F", "battle_exec_flags_input"},
    {"P", "battle_input_controller"}, {"L", "battle_not_link"}, {"H", "battle_engine_loaded"},
    {"O", "battle_outcome_open"},
}

-- pret c75f3523 constants.
R.K = {
    BATTLE_TYPE_OLD_MAN_TUTORIAL = 0x200,     -- include/constants/battle.h:56 (bit 9)
    BATTLE_TYPE_POKEDUDE = 0x10000,           -- include/constants/battle.h:64 (bit 16)
    B_ACTION_USE_ITEM = 1, B_ACTION_SWITCH = 2, B_ACTION_RUN = 3,   -- include/battle.h:34-37
    B_OUTCOME_RAN = 4,                        -- include/constants/battle.h:79
    PARTY_SIZE = 6,
    -- include/battle_controllers.h:140-175 enum (CONTROLLER_GETMONDATA = 0)
    CONTROLLER_TWORETURNVALUES = 33, CONTROLLER_CHOSENMONRETURNVALUE = 34, CONTROLLER_ONERETURNVALUE = 35,
    PARTY_MENU_TYPE_IN_BATTLE = 1,            -- include/constants/party_menu.h:56
    PARTY_ACTION_CHOOSE_MON = 0,              -- include/constants/party_menu.h:68 (SEND_OUT = 1)
    ITEMMENULOCATION_BATTLE = 5,              -- include/constants/item_menu.h:14
}
local K = R.K

-- struct offsets (pret include/party_menu.h:8-20, include/item_menu.h:12-20)
local PM_TYPE, PM_SLOT, PM_ACTION = 8, 9, 11      -- menuType:4 is the low nibble of byte 8
local BAG_LOCATION = 4
local PARTY_MON_SIZE = 100

--- Bind addresses for one title. deps is the same {io, regs, frame} object safety.new takes.
function R.bind(pack, title, deps, root)
    local T = dofile(root .. "/lua/tests/gen3_title_syms.lua").for_title(title)
    local W = dofile(root .. "/lua/tests/gen3_battle_window_syms.lua").for_title(title)
    local battle = pack.battle or {}
    local ctx = {pack = pack, title = title, deps = deps, T = T, W = W, clause = {}, missing = {}}
    for _, c in ipairs(battle.clauses or {}) do ctx.clause[c.name] = c end
    for _, a in ipairs(R.ALIASES) do
        if not ctx.clause[a[2]] then ctx.missing[#ctx.missing + 1] = a[1] end
    end
    local L = ctx.clause.battle_not_link
    ctx.type_addr = L and L.address + (L.offset or 0)          -- raw gBattleTypeFlags, unmasked
    ctx.comm_addr = battle.commit_guard and battle.commit_guard.address
    -- controller pointer -> receipt name (the player's own spellings + the tutorial ones)
    ctx.names = {
        [T.HANDLE_INPUT_CHOOSE_ACTION] = "player:HandleInputChooseAction",
        [W.PLAYER_ACTION_AFTER_DMA3] = "player:HandleChooseActionAfterDma3",
        [W.PLAYER_BUFFER_RUN_COMMAND] = "player:PlayerBufferRunCommand",
        [W.PLAYER_CHOOSE_TARGET] = "player:HandleInputChooseTarget",
        [W.OLDMAN_INPUT_CHOOSE_ACTION] = "oak_old_man:HandleInputChooseAction",
        [W.POKEDUDE_INPUT_CHOOSE_ACTION] = "pokedude:HandleInputChooseAction",
    }
    return setmetatable(ctx, {__index = R})
end

local function rd(ctx, addr, width)
    if addr == nil then return nil end
    local names = {[1] = "read_u8", [2] = "read_u16_le", [4] = "read_u32_le"}
    local v = ctx.deps.io[names[width]](addr, "System Bus")
    assert(type(v) == "number", string.format("unreadable %d-byte word at 0x%08X", width, addr))
    return v
end

local function masked(ctx, spec)
    local v = rd(ctx, spec.address + (spec.offset or 0), spec.width)
    if spec.mask then v = v & spec.mask end
    return v
end

--- One witnessed frame: safety's verdict for `reason` plus every field §5 rule 1 names.
--- extra = {map=, pos=} from the caller's own position reader (recorded, never interpreted).
function R.sample(ctx, safety, reason, args, extra)
    reason = reason or "battle_faint"
    local ok, why = safety:check(nil, reason, args)
    local failed = {}
    for _, key in ipairs(safety.last_clauses or {}) do failed[#failed + 1] = key end
    local fset = {}
    for _, key in ipairs(failed) do fset[key] = true end
    local regs = ctx.deps.regs and ctx.deps.regs() or {}
    local s = {reason = reason, ok = ok == true, why = tostring(why), failed = failed, fset = fset,
               v = {}, t = {}, frame = ctx.deps.frame and ctx.deps.frame() or nil,
               r15 = regs.R15, cpsr = regs.CPSR, map = extra and extra.map, pos = extra and extra.pos,
               extra = extra or {}}
    -- the tuple: raw (masked) value per clause; truth = present and not in safety's failures
    for _, a in ipairs(R.ALIASES) do
        local spec = ctx.clause[a[2]]
        if spec then
            s.v[a[1]] = masked(ctx, spec)
            s.t[a[1]] = not fset[a[2]] and not fset.pack
        end
    end
    local T, W, p = ctx.T, ctx.W, ctx.pack
    s.type = rd(ctx, ctx.type_addr, 4)
    s.trainer = rd(ctx, W.TRAINER_OPPONENT_A_ADDR, 2)
    s.outcome = rd(ctx, T.BATTLE_OUTCOME_ADDR, 1)
    s.ctrl, s.comm, s.party, s.ret = {}, {}, {}, {}
    for i = 0, 3 do
        s.ctrl[i] = rd(ctx, T.BATTLER_CTRL_ADDR + 4 * i, 4)
        s.comm[i] = rd(ctx, ctx.comm_addr and ctx.comm_addr + i, 1)
        s.party[i] = rd(ctx, W.BATTLER_PARTY_INDEXES_ADDR + 2 * i, 2)
        s.ret[i] = rd(ctx, W.BATTLE_BUFFER_B_ADDR + i, 1)       -- battler 0's return values
    end
    s.chosen0 = rd(ctx, W.CHOSEN_ACTION_ADDR, 1)
    s.cb2 = rd(ctx, T.GMAIN_CALLBACK2_ADDR, 4)
    s.in_battle = masked(ctx, p.predicates.in_battle) ~= 0
    s.fade = masked(ctx, p.predicates.palette_fade_active) ~= 0
    s.pm_type = rd(ctx, T.PARTY_MENU_ADDR + PM_TYPE, 1) & 0x0F
    s.pm_slot = rd(ctx, T.PARTY_MENU_ADDR + PM_SLOT, 1)
    s.pm_action = rd(ctx, T.PARTY_MENU_ADDR + PM_ACTION, 1)
    s.bag_location = rd(ctx, T.BAG_MENU_STATE_ADDR + BAG_LOCATION, 1)
    s.tasks = {}
    local t = p.tasks
    for i = 0, t.count - 1 do
        local base = t.address + i * t.struct_size
        if rd(ctx, base + t.is_active_offset, 1) ~= 0 then s.tasks[rd(ctx, base + t.func_offset, 4)] = true end
    end
    if s.pm_slot < K.PARTY_SIZE then     -- the key of the mon the party menu/summary points at
        -- personality:otId, struct BoxPokemon +0/+4 (pret include/pokemon.h:105-108)
        local base = T.PARTY_BASE + s.pm_slot * PARTY_MON_SIZE
        s.slot_key = string.format("%08X:%08X", rd(ctx, base, 4), rd(ctx, base + 4, 4))
    end
    return s
end

-- ── rows ─────────────────────────────────────────────────────────────────────────────────────
local function in_span(ptr, span)
    return ptr ~= nil and span ~= nil and (ptr & ~1) >= span[1] and (ptr & ~1) < span[2]
end
local function reopened(s, c)   -- battler 0's action menu is being offered again
    return s.ctrl[0] == c.T.HANDLE_INPUT_CHOOSE_ACTION or s.ctrl[0] == c.W.PLAYER_ACTION_AFTER_DMA3
end
local function always() return true end
-- A commit arms only on a FRESH return: the previous fed sample had battler 0 on the row's menu
-- controller, or gBattleBufferB[0][0..1] changed since it. A stale buffer (state loaded mid-turn,
-- the return of an earlier choice) never arms. The controller edge is needed as well as the byte
-- change: RUN after a failed escape rewrites identical bytes (0x21, 3).
local function fresh(s, prev, menu)
    return prev ~= nil and (prev.ctrl[0] == menu or prev.ret[0] ~= s.ret[0] or prev.ret[1] ~= s.ret[1])
end

R.ROWS = {
    {name = "N1", note = "action-menu DMA/draw controller, then the distinct input controller",
        must_fail = {"battle_input_controller"}, floor = 1,
        arm = function(s, _, c) return s.ctrl[0] == c.W.PLAYER_ACTION_AFTER_DMA3 end,
        done = function(s, _, c) return s.ctrl[0] == c.T.HANDLE_INPUT_CHOOSE_ACTION end},
    {name = "N3", note = "target submenu (player HandleInputChooseTarget)",
        must_fail = {"battle_comm_0", "battle_input_controller"}, floor = 60,
        arm = function(s, _, c) return s.ctrl[0] == c.W.PLAYER_CHOOSE_TARGET end},
    {name = "N4", note = "battle BAG: CB2_BagMenuRun + input task, fade settled, battle location",
        must_fail = {"battle_comm_0", "battle_input_controller"}, floor = 60,
        arm = function(s, _, c)
            return s.cb2 == c.T.CB2_BAG_MENU_RUN and s.tasks[c.T.TASK_BAG_MENU_HANDLE_INPUT] == true
                and not s.tasks[c.T.TASK_ANIMATE_WIN0V] and not s.fade and s.in_battle
                and s.bag_location == K.ITEMMENULOCATION_BATTLE and s.chosen0 == K.B_ACTION_USE_ITEM
        end},
    -- Forced routes excluded: the faint send-out is PARTY_ACTION_SEND_OUT, and the faint-replacement
    -- choice emits CHOOSE_MON with gChosenActionByBattler = B_ACTION_NOTHING_FAINTED (13), which the
    -- chosen0 == SWITCH conjunct refuses (pret battle_main.c:3117, :3214-3218).
    {name = "N5", note = "voluntary party menu (CHOOSE_MON, chosen SWITCH, not the forced routes); "
            .. "counts list-waiting frames only: the selection window reassigns the task (party_menu.c:3113)",
        must_fail = {"battle_comm_0", "battle_input_controller"}, floor = 60,
        arm = function(s, _, c)
            return s.cb2 == c.T.CB2_UPDATE_PARTY_MENU and s.tasks[c.T.TASK_CHOOSE_MON] == true
                and s.in_battle and s.pm_type == K.PARTY_MENU_TYPE_IN_BATTLE
                and s.pm_action == K.PARTY_ACTION_CHOOSE_MON and s.chosen0 == K.B_ACTION_SWITCH
        end},
    {name = "N6", note = "summary opened from the battle party menu",
        must_fail = {"battle_comm_0", "battle_input_controller"}, floor = 60,
        arm = function(s, _, c)
            return s.cb2 == c.W.CB2_RUN_SUMMARY_SCREEN and s.in_battle
                and s.pm_type == K.PARTY_MENU_TYPE_IN_BATTLE and s.pm_action == K.PARTY_ACTION_CHOOSE_MON
                and s.chosen0 == K.B_ACTION_SWITCH and s.slot_key ~= nil
        end},
    {name = "N7", note = "switch committed (CHOSENMONRETURNVALUE) until the replacement is active",
        must_fail = {"battle_input_controller"}, floor = 1,
        arm = function(s, st, c, prev)
            if fresh(s, prev, c.W.PLAYER_WAIT_FOR_MON_SELECTION)
                and s.chosen0 == K.B_ACTION_SWITCH and s.ret[0] == K.CONTROLLER_CHOSENMONRETURNVALUE
                and s.ret[1] < K.PARTY_SIZE and s.ctrl[0] == c.W.PLAYER_BUFFER_RUN_COMMAND
                and s.party[0] ~= s.ret[1] then
                st.selected, st.from = s.ret[1], s.party[0]
                return true
            end
            return false
        end,
        hold = function(s, _, c) return s.outcome == 0 and not reopened(s, c) end,
        done = function(s, st) return s.party[0] == st.selected end},
    {name = "N8", note = "item committed (ONERETURNVALUE, nonzero item) until outcome or reopen",
        must_fail = {"battle_input_controller"}, floor = 1,
        arm = function(s, st, c, prev)
            local item = s.ret[1] | (s.ret[2] << 8)
            if fresh(s, prev, c.W.PLAYER_COMPLETE_WHEN_CHOSE_ITEM) and s.chosen0 == K.B_ACTION_USE_ITEM and s.ret[0] == K.CONTROLLER_ONERETURNVALUE and item ~= 0
                and s.ctrl[0] == c.W.PLAYER_BUFFER_RUN_COMMAND then
                st.item = item
                return true
            end
            return false
        end,
        hold = always,
        done = function(s, st, c)
            if s.outcome ~= 0 then st.ended = "outcome=" .. s.outcome
            elseif reopened(s, c) then st.ended = "reopened"
            else return false end
            return true
        end,
        -- the quantity comes from the caller (sample extra.balls: the ball pocket count it read);
        -- baseline = the first sample this row was fed, so the bag must be sampled before the throw
        receipt_fields = function(acc, s)
            local before, now = acc.fed_first and acc.fed_first.extra.balls, s.extra.balls
            local delta = (before and now) and tostring(now - before) or "unknown"
            return {"balls_before=" .. tostring(before), "balls_now=" .. tostring(now), "ball_delta=" .. delta}
        end},
    {name = "N9", note = "RUN committed until gBattleOutcome == B_OUTCOME_RAN",
        must_fail = {"battle_input_controller"}, floor = 1,
        arm = function(s, _, c, prev)
            return fresh(s, prev, c.T.HANDLE_INPUT_CHOOSE_ACTION)
                and s.ret[0] == K.CONTROLLER_TWORETURNVALUES and s.ret[1] == K.B_ACTION_RUN
                and s.ctrl[0] == c.W.PLAYER_BUFFER_RUN_COMMAND and s.outcome == 0
        end,
        hold = function(s, _, c) return not reopened(s, c) end,   -- a failed escape reopens
        done = function(s) return s.outcome == K.B_OUTCOME_RAN end},
    {name = "U1", note = "old-man tutorial: OLD_MAN bit9 + controller in the oak_old_man object",
        must_fail = {"battle_input_controller"}, floor = 1,
        arm = function(s, _, c)
            return (s.type or 0) & K.BATTLE_TYPE_OLD_MAN_TUTORIAL ~= 0 and in_span(s.ctrl[0], c.W.spans.oak_old_man)
        end},
    {name = "U2", note = "Pokedude: POKEDUDE bit16 + controller in the pokedude object",
        must_fail = {"battle_input_controller"}, floor = 1,
        arm = function(s, _, c)
            return (s.type or 0) & K.BATTLE_TYPE_POKEDUDE ~= 0 and in_span(s.ctrl[0], c.W.spans.pokedude)
        end},
}
R.by_name = {}
for _, spec in ipairs(R.ROWS) do spec.reason = spec.reason or "battle_faint"; R.by_name[spec.name] = spec end

function R.row(ctx, name)
    return {spec = assert(R.by_name[name], "unknown battle-window row " .. tostring(name)), ctx = ctx,
            st = {}, open = false, samples = 0, admitted = 0, misattributed = 0, wrong_reason = 0,
            windows = 0, terminals = 0}
end

local function judge(acc, s)
    acc.samples = acc.samples + 1
    acc.first = acc.first or s
    acc.last = s
    if s.reason ~= acc.spec.reason then acc.wrong_reason = acc.wrong_reason + 1 end
    if s.ok then acc.admitted = acc.admitted + 1; acc.bad = acc.bad or s; return end
    for _, key in ipairs(acc.spec.must_fail) do
        if not s.fset[key] then
            acc.misattributed = acc.misattributed + 1
            acc.miss = acc.miss or key
            acc.bad = acc.bad or s
            return
        end
    end
end

--- Feed one sample. Returns "qualified", "done", "closed" or nil (not this row's state).
local function step(acc, s, prev)
    local spec, st, c = acc.spec, acc.st, acc.ctx
    if acc.open then
        if spec.done and spec.done(s, st, c) then
            acc.open, acc.terminals, acc.terminal = false, acc.terminals + 1, s
            return "done"
        end
        if not (spec.hold or spec.arm)(s, st, c, prev) then acc.open = false; return "closed" end
    elseif spec.arm(s, st, c, prev) then
        acc.open, acc.windows = true, acc.windows + 1
    else
        return nil
    end
    judge(acc, s)
    return "qualified"
end

function R.feed(acc, s)
    acc.fed_first = acc.fed_first or s
    local prev = acc.prev
    acc.prev = s
    return step(acc, s, prev)
end

--- "PASS" | "FAIL" | "UNREACHED", why. Never PASS on zero qualifying samples (§5 rule 4).
function R.verdict(acc)
    local spec, ctx = acc.spec, acc.ctx
    if #ctx.missing > 0 then return "FAIL", "pack lacks clause(s) " .. table.concat(ctx.missing, ",") end
    if acc.admitted > 0 then return "FAIL", acc.admitted .. " qualifying samples admitted" end
    if acc.misattributed > 0 then
        return "FAIL", string.format("%d qualifying samples where %s did not fail", acc.misattributed, acc.miss)
    end
    if acc.wrong_reason > 0 then return "FAIL", acc.wrong_reason .. " samples not taken for " .. spec.reason end
    if acc.samples == 0 then return "UNREACHED", "no qualifying sample" end
    if acc.samples < spec.floor then
        return "UNREACHED", string.format("samples %d < floor %d", acc.samples, spec.floor)
    end
    if spec.done and acc.terminals == 0 then return "UNREACHED", "terminal never observed after a qualifying sample" end
    return "PASS", "-"
end

-- ── receipts (§5 rule 1) ─────────────────────────────────────────────────────────────────────
local WIDTH = {M = 8, C = 2, F = 8, P = 8, L = 8, H = 4, O = 2}
local function hex(v, digits)
    if v == nil then return "nil" end
    return string.format("0x%0" .. (digits or 8) .. "X", v)
end

function R.ctrl_name(ctx, ptr)
    if ptr == nil then return "nil" end
    local name = ctx.names[ptr]
    if not name then
        for obj, span in pairs(ctx.W.spans) do
            if in_span(ptr, span) then name = obj; break end
        end
    end
    return hex(ptr) .. "[" .. (name or "?") .. "]"
end

local HASHES = {"rom", "fixture", "pack", "source", "state"}

--- One sample as a full receipt line. meta = {row=, hashes={rom,fixture,pack,source,state},
--- state_path=, prep=}; a missing hash is an error, never a blank field. With the row's
--- accumulator, the row's own receipt_fields(acc, s) are appended (N8: the ball-count delta).
function R.receipt(ctx, s, meta, acc)
    local parts = {"BWSAMPLE", tostring(meta.row), "title=" .. ctx.title, "reason=" .. s.reason}
    for _, h in ipairs(HASHES) do
        local v = meta.hashes and meta.hashes[h]
        assert(type(v) == "string" and v ~= "", "receipt needs the " .. h .. " hash")
        parts[#parts + 1] = h .. "=" .. v
    end
    local function add(k, v) parts[#parts + 1] = k .. "=" .. tostring(v) end
    add("state_path", meta.state_path or "-"); add("prep", meta.prep or "-")
    add("map", s.map or "-"); add("pos", s.pos or "-"); add("frame", s.frame)
    add("R15", hex(s.r15)); add("CPSR", hex(s.cpsr))
    for _, a in ipairs(R.ALIASES) do
        local k = a[1]
        add(k, s.v[k] == nil and "absent" or (hex(s.v[k], WIDTH[k]) .. ":" .. (s.t[k] and "T" or "F")))
    end
    add("permit", s.ok)
    add("failed", #s.failed > 0 and table.concat(s.failed, ",") or "-")
    add("type", hex(s.type)); add("trainer", s.trainer)
    local ctrl, comm, party, ret = {}, {}, {}, {}
    for i = 0, 3 do
        ctrl[#ctrl + 1] = R.ctrl_name(ctx, s.ctrl[i])
        comm[#comm + 1] = tostring(s.comm[i]); party[#party + 1] = tostring(s.party[i])
        ret[#ret + 1] = string.format("%02X", s.ret[i])
    end
    add("ctrl", table.concat(ctrl, ",")); add("comm", table.concat(comm, ","))
    add("party", table.concat(party, ",")); add("outcome", s.outcome)
    add("chosen0", s.chosen0); add("bufB0", table.concat(ret, ","))
    add("cb2", hex(s.cb2)); add("in_battle", s.in_battle); add("slot_key", s.slot_key or "-")
    if acc and acc.spec.receipt_fields then
        for _, field in ipairs(acc.spec.receipt_fields(acc, s)) do parts[#parts + 1] = field end
    end
    return table.concat(parts, " ")
end

--- The row's verdict line: counts, floor, terminal and state notes (N7 from/selected, N8 item/end).
function R.verdict_line(acc)
    local status, why = R.verdict(acc)
    local st = acc.st
    local extra = ""
    if st.selected then extra = extra .. string.format(" from=%d selected=%d", st.from, st.selected) end
    if st.item then extra = extra .. " item=" .. st.item end
    if st.ended then extra = extra .. " ended=" .. st.ended end
    return string.format("BWROW %s %s samples=%d windows=%d terminals=%d admitted=%d misattributed=%d floor=%d%s why=%s note=%s",
        acc.spec.name, status, acc.samples, acc.windows, acc.terminals, acc.admitted, acc.misattributed,
        acc.spec.floor, extra, why, acc.spec.note), status
end

return R
