-- lua/nds/residency_contract.lua -- the shared NDS overlay-residency strategy contract.
--
-- Pure and geometry-free: this module knows the SHAPE of a residency strategy and the SAFETY RULE for
-- arming a hook from one, never where any game keeps its table. HGSS (a static 3 x 8 x 8 B array) and
-- Gen 5 (a heap block behind a pointer global, per-region counts) each implement the contract in their
-- own lane; docs/shared-nds-residency.md has the two reference geometries.
--
-- Strategy (plain table of plain functions, no `self`):
--   entries(read)  -> array of { id = integer, active = boolean, region = integer }, EVERY slot of
--                     EVERY region (stale slots, active = false, included). `read` is the caller's memory
--                     reader (opaque here: the strategy and its caller agree on it; this module never
--                     calls it, only forwards it).
--   resident(id)   -> boolean. True iff the MAIN region (region 0) currently shows `id` active; an active
--                     entry for the same id in another region does not count (the loaders only place
--                     code through the main list; ITCM/DTCM entries are not hook sites). This is a
--                     HINT: the active flag is set BEFORE the load is known to have succeeded (a failed
--                     load leaves it active) and is cleared on unload while the stale id stays, so a flag
--                     can lead the real code. It must never be the only thing that arms a hook.
--   epoch()        -> integer that CHANGES whenever the table could have changed; equal epochs mean "no
--                     load/unload, no relocation, no boot happened in between". COST: at most a few
--                     reads (it sits on the arming path), so build it from a heap/table pointer, a
--                     loader-call counter and a boot/save GENERATION counter, not by hashing every slot.
--                     It must change on soft reset and on Continue / New Game even if the heap hands back
--                     the SAME addresses with the same-looking words. Side-effect free; may over-report.
--   geometry()     -> optional; a plain table describing the layout for diagnostics (never consumed by
--                     the contract helpers).
--
-- Site (what the hook binder passes; only the fields below are read here):
--   { id = non-empty string, overlay_id = nil for a static ARM9 site | integer for an overlay site }
--
-- REQUIRED per-site pin hook, supplied by the binder (NOT the strategy, which knows no code bytes):
--   site_confirmed(site) -> true  iff the site's expected bytes (its full registration pin / fire word)
--   are RE-READ from memory NOW and match. Strictly `true`; anything else, or an error, is a refusal.
--   may_arm and may_fire both call it; a residency flag alone never arms or fires anything.
--
-- PURE CHECKS. may_arm / may_fire / snapshot / validate_* hold no state of their own, never write to the
-- strategy, the site or any shared table, and never consume anything: the caller's own single-shot lease
-- (Gen 4 D7: battle_write renews, pre_pump clears, the callback consumes) stays the ONLY state. Calling a
-- check twice gives the same answer for the same memory.
--
-- A refusal is a VISIBLE FAULT, not "no site": the caller latches/counts it in its phase layer and retries
-- arming on the next phase/poll. The caller's own `accept` filter runs BEFORE may_fire and is not part of
-- this contract; the contract predicate is only residency + pin/fire-word. See docs/shared-nds-residency.md.
local M = {}

M.REASONS = {
    "bad_strategy", "bad_site", "no_pin_check", "epoch_required", "stale_epoch",
    "not_resident", "pin_mismatch", "pin_error",
}

-- ponytail: userdata counts (BizHawk exposes host callables as userdata), same as the Gen 4 binder.
local function is_fn(v) return type(v) == "function" or type(v) == "userdata" end
local function is_int(v) return math.type(v) == "integer" end

-- Static shape check. Returns true | false, reason.
local function check_shape(s)
    if type(s) ~= "table" then return false, "strategy must be a table" end
    for _, name in ipairs({ "entries", "resident", "epoch" }) do
        if not is_fn(s[name]) then return false, "strategy." .. name .. " must be a function" end
    end
    if s.geometry ~= nil and not is_fn(s.geometry) then return false, "strategy.geometry must be a function" end
    return true
end

local function check_entry(e, i)
    if type(e) ~= "table" then return false, "entry " .. i .. " must be a table" end
    if not is_int(e.id) then return false, "entry " .. i .. ".id must be an integer" end
    if type(e.active) ~= "boolean" then return false, "entry " .. i .. ".active must be a boolean" end
    -- integer only: the residency predicate compares region to integer 0, so a string region would be silently vacuous
    if not is_int(e.region) then return false, "entry " .. i .. ".region must be an integer" end
    return true
end

-- Validate a strategy. With `read`, also exercise it: entries well-formed, epoch an integer, and resident(id)
-- consistent with the entries (true exactly for ids that have an active entry in region 0). Returns
-- true | false, reason.
function M.validate_strategy(s, read)
    local ok, why = check_shape(s)
    if not ok then return false, why end
    if read == nil then return true end
    local e = s.epoch()
    if not is_int(e) then return false, "strategy.epoch() must return an integer" end
    local list = s.entries(read)
    if type(list) ~= "table" then return false, "strategy.entries(read) must return an array" end
    local active, seen = {}, {}
    for i, entry in ipairs(list) do
        local eok, ewhy = check_entry(entry, i)
        if not eok then return false, ewhy end
        seen[entry.id] = true
        if entry.active and entry.region == 0 then active[entry.id] = true end
    end
    for id in pairs(seen) do
        local r = s.resident(id)
        if type(r) ~= "boolean" then return false, "strategy.resident(id) must return a boolean" end
        if r ~= (active[id] == true) then return false, "strategy.resident(" .. id .. ") disagrees with entries" end
    end
    if s.resident(-1) ~= false then return false, "strategy.resident(unknown id) must be false" end
    if s.epoch() ~= e then return false, "strategy.epoch() changed with no table change" end
    return true
end

-- Raise on a malformed strategy; return it otherwise (so it can wrap a constructor call).
function M.assert_strategy(s, read)
    local ok, why = M.validate_strategy(s, read)
    if not ok then error("invalid residency strategy: " .. why, 2) end
    return s
end

-- One consistent view: epoch first, then the entries, so a table change DURING the read can only make
-- the view look stale (a refusal), never fresh. `read` is forwarded to assert_strategy, so the behavioural
-- validation runs when a binder chooses to snapshot per attempt (optional: Gen 4 validates once at
-- construction and relies on may_arm's live pin re-read). Returns { epoch = n, entries = array }.
function M.snapshot(s, read)
    M.assert_strategy(s, read)
    local e = s.epoch()
    assert(is_int(e), "strategy.epoch() must return an integer")
    return { epoch = e, entries = s.entries(read) }
end

local function check_site(site)
    if type(site) ~= "table" or type(site.id) ~= "string" or site.id == "" then return false end
    return site.overlay_id == nil or is_int(site.overlay_id)
end

-- The pin check, guarded. Returns true | false, "pin_mismatch" | "pin_error".
local function pin_ok(site, site_confirmed)
    local ok, res = pcall(site_confirmed, site)
    if not ok then return false, "pin_error" end
    if res ~= true then return false, "pin_mismatch" end
    return true
end

-- May a hook be ARMED (registered) for `site` now? Returns true | false, reason (see M.REASONS).
--   `epoch` is the epoch of the residency view the caller decided from (M.snapshot(...).epoch); REQUIRED
--   for an overlay site, ignored for a static one. Overlay residency is only a necessary condition; the
--   site's bytes are re-read through site_confirmed in EVERY case, so a flag that leads its load
--   (active, code not copied yet) is refused until the pin matches.
function M.may_arm(strategy, site, site_confirmed, epoch)
    if not check_shape(strategy) then return false, "bad_strategy" end
    if not check_site(site) then return false, "bad_site" end
    if not is_fn(site_confirmed) then return false, "no_pin_check" end
    if site.overlay_id ~= nil then
        if epoch == nil then return false, "epoch_required" end
        if epoch ~= strategy.epoch() then return false, "stale_epoch" end
        if strategy.resident(site.overlay_id) ~= true then return false, "not_resident" end
    end
    return pin_ok(site, site_confirmed)
end

-- May an armed hook FIRE for `site` right now (call at fire time; no epoch: the check is live)?
-- Order mirrors the Gen 4 binder: the owning overlay must be resident (else a quiet "not_resident":
-- another overlay may share the RAM), then the pin is re-read ("pin_mismatch" while resident is a
-- fault the caller should surface, never a silent drop).
function M.may_fire(strategy, site, site_confirmed)
    if not check_shape(strategy) then return false, "bad_strategy" end
    if not check_site(site) then return false, "bad_site" end
    if not is_fn(site_confirmed) then return false, "no_pin_check" end
    if site.overlay_id ~= nil and strategy.resident(site.overlay_id) ~= true then return false, "not_resident" end
    return pin_ok(site, site_confirmed)
end

return M
