-- lua/gen4/poll_events.lua -- the Gen 4 per-frame event reducer (owner ruling 2026-10-01: zero
-- steady-state hooks; gameplay events are detected by POLLING RAM, docs/gen4/reviews/
-- DECISIONS_2026-10-01.md).
--
-- Pure: no BizHawk API, no memory handle, no pointer kept between frames. The caller builds a
-- snapshot from lua/gen4/reads.lua every frame and calls `pe:step(snapshot)`; the result is the
-- wire events of that frame (docs/protocol.md §3.2, tests/unit/protocol_schema.py EVENTS) as
-- `{ name = "capture", data = {...} }` ready for `session:send(name, data)`, plus a second
-- return, a list of diagnostic strings (named ambiguities the reducer refused to guess).
--
-- snapshot = {
--   frame        = int, optional (an internal counter is used when absent),
--   area, loc    = area_id / loc_name strings, nil or "" = unreadable,
--   party        = core mon records (reads.party: key, species, level, hp, max_hp, slot[, is_egg,
--                  nickname, held_item, decoded]) or nil when unreadable,
--   boxes        = { gen = int (changes ONLY when the content changes; used to cache the
--                  content signature), mons = { [key] = {species_id, nickname, held_item_id,
--                  is_egg} } } or nil when unreadable. MUST be current whenever `idle` is true,
--   battle       = reads.battle() result, or nil (no chain / refused),
--   idle         = the checkpoint-idle predicate (storage/safety: no field task, no launched
--                  app, save driver idle, field live),
--   pc_active    = true while the PC application is resident (the only legal release/box path),
--   has_pokeballs, player_otid = latched facts the caller already tracks,
-- }
--
-- Trust model:
--   * set diffs (acquisitions, moves, releases, hatches, encounter end) run ONLY on a SETTLED
--     snapshot: idle, party and boxes readable, no battle, and the same party/box signature on
--     `settle_frames` consecutive frames. A one-frame flicker never produces an event.
--   * faint reads HP only (no set diff): the battle HP of the local battlers while a battle is up,
--     the party HP otherwise (poison etc.), each zero debounced over `faint_frames` frames. Party
--     HP is NOT observed from battle teardown until the first settled snapshot (the save party is
--     stale until the encounter task copies back), so a mon that fainted in battle is never
--     re-reported or revived by the stale copy.
--   * the encounter-scoped latch (`pending`: foe identities PID:OTID, outcome, btype, area) is
--     built from the battle chain, outlives it (copy-back, blackout) and is consumed exactly once.
--     It survives the FIRST settled view too (F7): a battle that ended just before the baseline is
--     learned still gets its no_catch (the baseline already holds anything it caught).
--   * whiteout (D-2026-10-01, Gen 3 semantics): the LOSE outcome latched when a NON-exempt battle ends
--     emits it at once; no area change or heal is required. The out-of-battle path (poison) stays
--     all-fainted-party + area change + heal within `whiteout_window` (PHYSICAL-OPEN).
--   * records without a string `key` (party / battle) are skipped with a note; a party that had one is
--     not settled that frame (a skipped record must never read as a release).
--   * records flagged implausible (decoded.tail_plausible / box_plausible == false, or `implausible`)
--     are never an acquisition: a note, no capture / gift (F2).
--
-- cfg.battle_enums (the pack's profile.battle_enums block) supplies outcomes / trainer_mask / no_catch_mask;
-- explicit cfg.outcomes / trainer_mask / no_catch_mask win.
local PE = {}
PE.__index = PE

local DEFAULTS = {
    settle_frames = 2,     -- consecutive agreeing idle frames before a set diff is trusted
    faint_frames = 2,      -- consecutive frames of HP 0 (and of HP > 0 to re-arm) for a faint
    end_frames = 3,        -- consecutive frames without the battle chain before the battle is over
    area_frames = 2,       -- consecutive frames naming a new area before area_enter
    whiteout_window = 1800, -- frames a loss may wait for its blackout warp + heal
    suppress_frames = 900,  -- how long an expected self-inflicted change stays masked
    pc_frames = 1800,       -- how long after the PC closes a release diff may still land (F9)
}

local function egg(m)
    return m.is_egg == true or m.is_egg == 1 or (m.decoded ~= nil and m.decoded.is_egg == true)
end

-- A record the codec flagged as a wrong/torn decode must never become an acquisition (F2).
local function implausible(m)
    local d = m.decoded
    return m.implausible == true or (d ~= nil and (d.tail_plausible == false or d.box_plausible == false))
end

local function stats_default(m)
    local s = { level = m.level, maxHP = m.max_hp }
    local d = m.decoded
    if d and d.stats then
        s.attack, s.defense, s.speed, s.spAtk, s.spDef = d.stats[1], d.stats[2], d.stats[3], d.stats[4], d.stats[5]
        for i = 1, 4 do s["pp" .. i] = d.pp and d.pp[i] or 0 end
    end
    return s
end

function PE.new(cfg)
    cfg = cfg or {}
    local self = setmetatable({ cfg = {}, notes = {} }, PE)
    for k, v in pairs(DEFAULTS) do self.cfg[k] = cfg[k] ~= nil and cfg[k] or v end
    local be = cfg.battle_enums or {}
    self.cfg.trainer_mask, self.cfg.outcomes = be.trainer_mask, be.outcomes
    self.cfg.no_catch_mask = be.no_catch_mask or be.exempt_mask
    for _, k in ipairs({ "trainer_mask", "no_catch_mask", "outcomes", "gift_area", "stats_of" }) do
        if cfg[k] ~= nil then self.cfg[k] = cfg[k] end
    end
    self.cfg.resolved = cfg.resolved or {}     -- shared with the session (session.resolved_areas)
    self:reset()
    return self
end

-- A new save / reset / reconnect: forget everything (the baseline is re-learned silently).
function PE:reset()
    self.st = { frame = 0, known = {}, eggs = {}, alive = {}, up = {}, zero = {}, commanded = {}, expect = {},
                agree = 0, area_n = 0, has_pokeballs = false, party_keys = {}, box_sig_cache = {} }
end

function PE:known(key) return self.st.known[key] == true end
function PE:armed(key) return self.st.alive[key] == true end

-- The client is about to write HP 0 itself: that zero must never become a faint (Gen 3 mark_commanded).
function PE:commanded(key)
    self.st.commanded[key], self.st.alive[key] = true, nil
end

-- The client is about to move/release `key` itself (box_mon / party_mon / memorialize executors):
-- kind = "party_to_box" | "box_to_party" | "release". The resulting diff is learned but not reported.
function PE:expect(kind, key)
    self.st.expect[kind .. ":" .. key] = self.st.frame + self.cfg.suppress_frames
end

local function note(self, text) self.notes[#self.notes + 1] = text end

local function emit(ev, name, data) ev[#ev + 1] = { name = name, data = data } end

local function expected(self, kind, key)
    local id = kind .. ":" .. key
    local until_frame = self.st.expect[id]
    if until_frame == nil then return false end
    self.st.expect[id] = nil
    return until_frame >= self.st.frame
end

-- ── faint (HP only) ──────────────────────────────────────────────────────────────────────
local function observe_hp(self, ev, key, hp, area_id)
    local st, n = self.st, self.cfg.faint_frames
    if hp == 0 then
        st.up[key] = nil
        st.zero[key] = (st.zero[key] or 0) + 1
        if st.commanded[key] then
            st.commanded[key] = nil                      -- our own zero has landed: not a faint
        elseif st.zero[key] >= n and st.alive[key] then
            st.alive[key] = nil
            emit(ev, "faint", { key = key, area_id = area_id })
        end
    else
        st.zero[key] = nil
        if not st.commanded[key] then
            st.up[key] = (st.up[key] or 0) + 1
            if st.up[key] >= n then st.alive[key] = true end
        end
    end
end

-- ── area ─────────────────────────────────────────────────────────────────────────────────
local function step_area(self, s, ev)
    local st = self.st
    if type(s.area) ~= "string" or s.area == "" then st.area_n = 0; return end
    local here = s.area .. "|" .. (s.loc or "")
    if here == st.area_cand then st.area_n = st.area_n + 1 else st.area_cand, st.area_n = here, 1 end
    if st.area_n >= self.cfg.area_frames and here ~= st.area then
        if st.area ~= nil then emit(ev, "area_enter", { area_id = s.area, loc_name = s.loc }) end
        st.area, st.area_id = here, s.area
    end
end

-- ── battle lifecycle ─────────────────────────────────────────────────────────────────────
local function end_battle(self, ev)
    local st, bt = self.st, self.st.bt
    st.bt, st.gone = nil, 0
    st.pending = { area_id = bt.area_id, outcome = bt.outcome, btype = bt.btype, foes = bt.foes, order = bt.order }
    local o, exempt_mask = self.cfg.outcomes, self.cfg.no_catch_mask
    -- whiteout = the LOSE outcome of a non-exempt battle, latched at battle end (area change / heal not required)
    if o and o.lose ~= nil and bt.outcome == o.lose
       and not (exempt_mask and bt.btype and (bt.btype & exempt_mask) ~= 0) then
        st.wo, st.wo_fired = nil, st.frame
        emit(ev, "whiteout", {})
    end
end

local function step_battle(self, s, ev)
    local st, b = self.st, s.battle
    if not b then
        if st.bt then
            st.gone = st.gone + 1
            if st.gone >= self.cfg.end_frames then end_battle(self, ev) end
        end
        return
    end
    st.gone = 0
    if st.bt and st.bt.fp ~= b.fingerprint then end_battle(self, ev) end   -- epoch change with no gap
    if not st.bt then
        if st.pending then note(self, "pending_superseded"); st.pending = nil end
        st.bt = { fp = b.fingerprint, area_id = st.area_id or "", outcome = 0, foes = {}, order = {} }
    end
    local bt = st.bt
    bt.btype = b.btype
    if b.outcome ~= 0 then bt.outcome = b.outcome end        -- latch the last non-NONE outcome
    local own = st.party_keys
    for _, m in ipairs(b.mons or {}) do
        if m.b % 2 == 1 then                                 -- the enemy side: remember its identity
            if not bt.foes[m.key] then
                bt.foes[m.key] = { key = m.key, pid = m.pid, otid = m.otid, species = m.species,
                                   level = m.level, max_hp = m.max_hp }
                bt.order[#bt.order + 1] = m.key
            end
        elseif own[m.key] then                               -- a local battler: PID:OTID owns it, not the index
            observe_hp(self, ev, m.key, m.hp, bt.area_id)
        end
    end
end

-- ── party HP outside a battle ────────────────────────────────────────────────────────────
local function step_party_hp(self, s, ev)
    local st, P = self.st, s.party
    if not P then return end
    local all_zero, any = true, false
    for _, m in ipairs(P) do
        if not egg(m) then
            any = true
            observe_hp(self, ev, m.key, m.hp, st.area_id or "")
            if m.hp ~= 0 then all_zero = false end
        end
    end
    if any and all_zero then
        st.allzero = (st.allzero or 0) + 1
        -- a loss with no battle (poison); not again for the all-fainted party a battle whiteout already reported
        local fired = st.wo_fired and st.frame - st.wo_fired <= self.cfg.whiteout_window
        if st.allzero >= self.cfg.faint_frames and not st.wo and not fired then
            st.wo = { area_id = st.area_id or "", since = st.frame }
        end
    else
        st.allzero = 0
    end
end

-- ── settle ───────────────────────────────────────────────────────────────────────────────
local function box_sig(self, B)
    local c = self.st.box_sig_cache
    if B.gen ~= nil and c.gen == B.gen then return c.sig end
    local keys = {}
    for k in pairs(B.mons or {}) do keys[#keys + 1] = k end
    table.sort(keys)
    local sig = table.concat(keys, ",")
    c.gen, c.sig = B.gen, sig
    return sig
end

local function party_sig(P)
    local t = {}
    for i, m in ipairs(P) do t[i] = m.key .. (egg(m) and "e" or "") end
    return table.concat(t, ",")
end

-- foe identity vs a new record: the same PID, and the same OTID or the player's OTID (a capture may
-- rewrite the OT to the trainer; the live receipt for which one HG keeps is open, see the card report).
local function foe_match(foes, order, key, player_otid)
    local pid = tonumber(key:sub(1, 8), 16)
    for _, fk in ipairs(order) do
        local f = foes[fk]
        if fk == key or (pid == f.pid and player_otid and key == string.format("%08X:%08X", pid, player_otid)) then
            return f
        end
    end
end

local function resolve_area(self, area_id, gift)
    local g = self.cfg.gift_area
    if area_id ~= "" and not gift and not (g and g(area_id)) then self.cfg.resolved[area_id] = true end
end

local function settled(self, s, ev)
    local st, cfg, P, B = self.st, self.cfg, s.party, s.boxes
    local pk, bk, slot_of = {}, {}, {}
    for _, m in ipairs(P) do
        if pk[m.key] then note(self, "dup_key:" .. m.key); return end
        pk[m.key] = m
    end
    for k, e in pairs(B.mons or {}) do
        if pk[k] then note(self, "dup_key:" .. k); return end
        bk[k] = e
        if e.is_egg == true or e.is_egg == 1 then st.eggs[k] = true end
    end
    for _, m in ipairs(P) do
        if egg(m) then st.eggs[m.key] = true end
        slot_of[m.key] = m.slot
    end
    local base = st.base
    if not base then                                         -- first settled view: learn it; no set diff is reported
        for k in pairs(pk) do if not st.eggs[k] then st.known[k] = true end end
        for k in pairs(bk) do if not st.eggs[k] then st.known[k] = true end end
        base = { pk = pk, bk = bk }
        -- F7: st.pending is KEPT: a battle that ended just before this baseline still owes its no_catch (the
        -- baseline already holds whatever it caught, so no capture can be double-reported)
    end
    local area_id = st.area_id or ""
    local pend = st.pending
    local stats_of = cfg.stats_of or stats_default
    local function hatch_or_new(k)
        return base.pk[k] == nil and base.bk[k] == nil
    end

    -- eggs that hatched (same key, the egg flag dropped): O-15, acquired at hatch, a daycare gift
    for k, m in pairs(pk) do
        if st.eggs[k] and not egg(m) then
            st.eggs[k] = nil
            if not st.known[k] then
                st.known[k] = true
                emit(ev, "capture", { key = k, area_id = "gift_daycare", species_id = m.species, level = m.level,
                                      hp = m.hp, maxHP = m.max_hp, nickname = m.nickname,
                                      held_item_id = m.held_item, is_egg = false, stats = stats_of(m), gift = true })
            end
        end
    end

    -- key-preserving moves
    for k, m in pairs(pk) do
        if base.pk[k] == nil and base.bk[k] ~= nil then
            local own = expected(self, "box_to_party", k)      -- consumed by the diff itself, reported or not
            if st.known[k] and not st.eggs[k] and not own then
                emit(ev, "box_to_party", { key = k, area_id = area_id, nickname = m.nickname })
            end
        end
    end
    for k, m in pairs(base.pk) do
        if pk[k] == nil and bk[k] ~= nil then
            local own = expected(self, "party_to_box", k)
            if st.known[k] and not st.eggs[k] and not own then
                emit(ev, "party_to_box", { key = k, stats = stats_of(m) })
            end
        end
    end

    -- keys out of nowhere / keys into nowhere
    local fresh_p, fresh_b, lost = {}, {}, {}
    for k, m in pairs(pk) do
        if hatch_or_new(k) then
            if implausible(m) then note(self, "implausible:" .. k) else fresh_p[#fresh_p + 1] = k end
        end
    end
    for k, e in pairs(bk) do
        if hatch_or_new(k) then
            if implausible(e) then note(self, "implausible:" .. k) else fresh_b[#fresh_b + 1] = k end
        end
    end
    for k in pairs(base.pk) do if pk[k] == nil and bk[k] == nil then lost[#lost + 1] = k end end
    for k in pairs(base.bk) do if pk[k] == nil and bk[k] == nil then lost[#lost + 1] = k end end
    table.sort(fresh_p); table.sort(fresh_b); table.sort(lost)

    -- a new record in the slot a record just left, with that record gone entirely, is an in-game NPC
    -- exchange (D11), never a capture and never a release: reported as a note for the key_change card
    local replaced = {}
    for _, k in ipairs(fresh_p) do
        for _, l in ipairs(lost) do
            if base.pk[l] and base.pk[l].slot == slot_of[k] and not replaced[l] then
                replaced[l], replaced[k] = true, true
                st.known[k] = not st.eggs[k] or nil
                note(self, "slot_replace:" .. l .. ">" .. k)
                break
            end
        end
    end

    -- captures: a new key that matches a foe of the encounter that just ended
    local caught = false
    local function take(k, in_box)
        local e = in_box and bk[k] or pk[k]
        if st.known[k] then note(self, "returned:" .. k); return end   -- a known key back (daycare), not an acquisition
        local foe = pend and foe_match(pend.foes, pend.order, k, s.player_otid)
        if st.eggs[k] then return end                        -- eggs are acquired at hatch
        st.known[k] = true
        if foe then
            caught = true
            resolve_area(self, pend.area_id, false)
            if in_box then
                emit(ev, "capture", { key = k, area_id = pend.area_id, in_box = true, species_id = e.species_id or foe.species,
                                      nickname = e.nickname, held_item_id = e.held_item_id, level = foe.level,
                                      maxHP = foe.max_hp, is_egg = false })
            else
                emit(ev, "capture", { key = k, area_id = pend.area_id, species_id = e.species, level = e.level,
                                      hp = e.hp, maxHP = e.max_hp, nickname = e.nickname, held_item_id = e.held_item,
                                      is_egg = false, stats = stats_of(e) })
                if e.hp and e.hp > 0 then st.alive[k] = true end
            end
        elseif not in_box then                               -- no encounter explains it: a gift
            resolve_area(self, area_id, true)
            emit(ev, "capture", { key = k, area_id = area_id, species_id = e.species, level = e.level, hp = e.hp,
                                  maxHP = e.max_hp, nickname = e.nickname, held_item_id = e.held_item,
                                  is_egg = false, stats = stats_of(e), gift = true })
        else
            note(self, "box_fresh_unattributed:" .. k)
        end
    end
    for _, k in ipairs(fresh_p) do if not replaced[k] then take(k, false) end end
    for _, k in ipairs(fresh_b) do take(k, true) end

    -- releases: only with the PC application observed (recently: F9), only keys that were ours
    local pc_recent = st.pc_seen and st.frame - st.pc_seen <= cfg.pc_frames
    for _, k in ipairs(lost) do
        if not replaced[k] then
            local own = expected(self, "release", k)
            if pc_recent and st.known[k] then
                st.known[k], st.alive[k] = nil, nil
                if not own then emit(ev, "release", { key = k }) end
            else
                note(self, "vanished:" .. k)
            end
        end
    end

    -- the encounter's end: no_catch unless it was caught
    if pend then
        local o = cfg.outcomes or {}
        local by_outcome = o.caught ~= nil and pend.outcome == o.caught
        if by_outcome and not caught then note(self, "caught_no_match") end
        caught = caught or by_outcome
        local foe = pend.foes[pend.order[1]]
        local trainer = cfg.trainer_mask and pend.btype and (pend.btype & cfg.trainer_mask) ~= 0
        local exempt = cfg.no_catch_mask and pend.btype and (pend.btype & cfg.no_catch_mask) ~= 0
        local g = cfg.gift_area
        -- a wild battle must be KNOWN wild (the pack names the trainer bit): never dead-zone an area on a guess
        if not caught and trainer == false and not exempt and foe and st.has_pokeballs and pend.area_id ~= ""
           and not (g and g(pend.area_id)) and not cfg.resolved[pend.area_id] then
            cfg.resolved[pend.area_id] = true
            emit(ev, "no_catch", { area_id = pend.area_id, species_id = foe.species, level = foe.level })
        end
        st.pending = nil
    end

    -- whiteout WITHOUT a battle (poison): the all-fainted party, then the blackout map change, then the heal.
    -- (A battle loss is reported at battle end, see end_battle.)
    local wo = st.wo
    if wo then
        local healed = true
        for _, m in ipairs(P) do if not egg(m) and m.hp ~= m.max_hp then healed = false end end
        if area_id ~= "" and area_id ~= wo.area_id and healed then
            st.wo = nil
            emit(ev, "whiteout", {})
        end
    end
    -- F9: pc_seen outlives the settled steps that see no set diff (the box write can land a few frames after
    -- the PC closes); only a diff, or `pc_frames` of quiet, spends it
    local changed = false
    for k in pairs(pk) do if base.pk[k] == nil then changed = true end end
    for k in pairs(bk) do if base.bk[k] == nil then changed = true end end
    for k in pairs(base.pk) do if pk[k] == nil then changed = true end end
    for k in pairs(base.bk) do if bk[k] == nil then changed = true end end
    if changed or not pc_recent then st.pc_seen = nil end
    for id, until_frame in pairs(st.expect) do               -- unconsumed expectations expire (never leak)
        if until_frame < st.frame then st.expect[id] = nil end
    end
    st.base = { pk = pk, bk = bk }
end

-- ── the frame ────────────────────────────────────────────────────────────────────────────
-- F10: a record without a string key cannot be tracked (and would throw on `t[nil] = v`): skip it with a note.
-- Returns the list unchanged when every record is keyed, else a filtered copy and true.
local function keyed(self, list, what)
    local bad
    for i, m in ipairs(list) do
        if type(m) ~= "table" or type(m.key) ~= "string" then bad = true; break end
    end
    if not bad then return list end
    local out = {}
    for i, m in ipairs(list) do
        if type(m) == "table" and type(m.key) == "string" then out[#out + 1] = m
        else note(self, "nil_key:" .. what .. i) end
    end
    return out, true
end

function PE:step(s)
    local st, cfg = self.st, self.cfg
    self.notes = {}
    local plist, bmons, dropped, bad_b
    if s.party then plist, dropped = keyed(self, s.party, "party") end
    if s.battle then bmons, bad_b = keyed(self, s.battle.mons or {}, "battler") end
    if dropped or bad_b then                                  -- copy-on-write: the common frame allocates nothing
        local sh = {}
        for k, v in pairs(s) do sh[k] = v end
        s = sh
        if dropped then s.party = plist end
        if bad_b then
            local bt = {}
            for k, v in pairs(s.battle) do bt[k] = v end
            bt.mons, s.battle = bmons, bt
        end
    end
    local ev = {}
    st.frame = s.frame or (st.frame + 1)
    if s.has_pokeballs then st.has_pokeballs = true end
    if s.pc_active then st.pc_seen = st.frame end
    if s.party then
        st.party_keys = {}
        for _, m in ipairs(s.party) do st.party_keys[m.key] = true end
    end
    step_area(self, s, ev)
    step_battle(self, s, ev)
    if st.wo and st.frame - st.wo.since > cfg.whiteout_window then
        note(self, "whiteout_unconfirmed")
        st.wo = nil
    end
    local ready = s.idle and s.party and s.boxes and not s.battle and not st.bt and not dropped   -- a skipped party record must never read as a release
    if ready then
        local sig = party_sig(s.party) .. "|" .. box_sig(self, s.boxes)
        if sig == st.sig then st.agree = st.agree + 1 else st.sig, st.agree = sig, 1 end
        if st.agree >= cfg.settle_frames and (st.base == nil or sig ~= st.base_sig or st.pending or st.wo
                                              or st.pc_seen) then
            settled(self, s, ev)
            st.base_sig = sig
        end
    else
        st.agree = 0
    end
    if not (s.battle or st.bt or st.pending) then step_party_hp(self, s, ev) end
    return ev, self.notes
end

return PE
