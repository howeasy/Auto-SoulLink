--[[
  lua/tests/test_rival_team_swap_inject.lua — PHASE 0 ISOLATION HARNESS
                                                for Rival Team Swap feature.

  Tests M.readPartyBlob + M.writeEnemyParty entirely from a SINGLE BizHawk
  instance — no Soul Link server, no partner instance, no live multiplayer.
  Lets you prove the gEnemyParty write primitive works before any of the
  TCP/state/adapter/dashboard plumbing exists.

  ⚠  WRITES TO RAM — save a BizHawk state before testing so you can restore.
     Only affects gEnemyParty (transient EWRAM) — no save corruption possible.

  Controls:
    F5 → Snapshot.       Read gPlayerParty, hex-encode each occupied 100-byte
                         slot, write the list to lua/tests/output/last_party_
                         snapshot.json.  Proves readPartyBlob round-trips
                         losslessly (file is a valid JSON object).
    F6 → Inject self.    Take the last F5 snapshot (or live gPlayerParty if no
                         snapshot exists) and call M.writeEnemyParty(blobs).
                         Use ONLY while in any battle (wild or trainer).
                         Demo: enter wild battle, press F6 → enemy sprite/HP
                         switch to a copy of your own lead within one frame.
    F7 → Inject synthetic. Build a deterministic 6-mon team (Charizard L50,
                         Blastoise L50, Venusaur L50, Pikachu L50, Snorlax L50,
                         Mewtwo L50) entirely in-Lua and inject.  Same demo as
                         F6 but the species are unmistakable.
    F8 → Readback diff.  Call M.readEnemyParty and compare against the species
                         IDs of the last injection.  Prints PASS/FAIL to the
                         BizHawk Lua console.
    F9 → Auto-trigger toggle.  Default ON.  Each frame, the script checks for
                         a rival fight via TRAINER_OPPONENT_ADDR + 2-frame
                         stability gate + the hardcoded RIVAL_IDS set (27
                         Terry IDs).  On a rival match it auto-injects your
                         most recent F5 snapshot (or live gPlayerParty if you
                         never snapshotted).  Single-instance simulation of
                         the full Phase 3 server flow — no server or partner
                         BizHawk needed.  One-shot per battle; resets on
                         battle end.

  ┌─ TESTING CRITERIA ─────────────────────────────────────────────────────────
  │  A. Snapshot round-trip (no battle required)
  │     → In the overworld with at least 1 party mon, press F5.
  │     → Console: "[T-RS] snapshot: N mons, written to <path>"
  │     → File at lua/tests/output/last_party_snapshot.json exists and contains
  │       one entry per occupied slot, each with a 200-character hex blob.
  │     → PASS: file written, blob lengths all exactly 200.
  │
  │  B. Inject self (in any battle)
  │     → Press F5 first to capture a snapshot.
  │     → Walk into a wild Pidgey/Rattata.  Press F6.
  │     → Console: "[T-RS] injected N mons: species=[..]"
  │     → Wild enemy mon's sprite/level/HP visibly switches to your lead's
  │       species within 1 frame.  Press F8 → "[T-RS] readback PASS".
  │     → PASS: visual swap + readback match.
  │
  │  C. Inject synthetic (in any battle)
  │     → Press F7 while in a wild battle.
  │     → Console: "[T-RS] injected 6 synthetic mons: species=[6,9,3,25,143,150]"
  │     → Wild mon switches to Charizard L50 within 1 frame.
  │     → Press F8 → "[T-RS] readback PASS (species=[6,9,3,25,143,150])".
  │     → PASS: deterministic swap, readback matches the 6 synthetic species.
  │
  │  D. Out-of-battle inject (negative case)
  │     → Press F6 or F7 in the overworld.
  │     → Console: "[T-RS] not in battle — write skipped" (writes refused).
  │     → PASS: no crash, no save corruption.
  │
  │  E. Wrong profile (negative case)
  │     → Load this on vanilla FRLG (not RR).  Press F7 in a wild battle.
  │     → Behaviour is undefined — vanilla uses encrypted substructs while the
  │       synthetic blob is built CFRU-style.  Expect garbled species/level.
  │     → INTENDED: this script is RR-only; symptoms here confirm encryption
  │       differs and the MVP scope-gate is correct.
  │
  │  FAIL: F5 writes 0 entries        → party is empty OR slotOccupied bug.
  │  FAIL: F6 visual swap doesn't fire → ENEMY_BASE wrong for current profile.
  │  FAIL: F8 readback mismatch       → CFRU_NO_ENCRYPT not true OR substruct
  │                                     order rotated by PID — confirm RR.
  └─────────────────────────────────────────────────────────────────────────────
--]]

-- ── path setup ────────────────────────────────────────────────────────────────
local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
package.path = _src .. "?.lua;" .. _lua_root .. "?.lua;" .. package.path

package.loaded["memory_gba"] = nil
local M = require("memory_gba")

-- ── startup ───────────────────────────────────────────────────────────────────
M.initProfile()
local ok, err = M.validateROM()
console.clear()
console.log(string.format("[T-RS] ROM validation: %s", ok and "OK" or ("FAIL – " .. tostring(err))))
console.log(string.format("[T-RS] profile: PARTY_BASE=0x%08X ENEMY_BASE=0x%08X CFRU_NO_ENCRYPT=%s",
    M.PARTY_BASE or 0, M.ENEMY_BASE or 0, tostring(M.CFRU_NO_ENCRYPT)))
console.log("[T-RS] Controls:")
console.log("[T-RS]   F5 = snapshot gPlayerParty to JSON   (works in overworld)")
console.log("[T-RS]   F6 = inject snapshot (or live party) into gEnemyParty (battle only)")
console.log("[T-RS]   F7 = inject synthetic 6-mon team into gEnemyParty (battle only)")
console.log("[T-RS]   F8 = readback PASS/FAIL — after F6/F7 vs inject, or after F5 vs snapshot")
console.log("[T-RS]   F9 = toggle auto-trigger on rival fights (default ON)")

-- ── output dir / file paths ───────────────────────────────────────────────────
local OUT_DIR  = _lua_root .. "tests/output"
local OUT_FILE = OUT_DIR .. "/last_party_snapshot.json"

-- ensure_out_dir runs ONCE at script load (line below), not per F5 press.
-- os.execute spawns cmd.exe on Windows (~500 ms freeze per call), which would
-- block the emulation thread on every snapshot otherwise.  Failures are
-- non-fatal — io.open below logs the error and bails.
local _out_dir_ensured = false
local function ensure_out_dir()
    if _out_dir_ensured then return end
    _out_dir_ensured = true
    local sep = package.config:sub(1, 1)
    if sep == "\\" then
        os.execute('if not exist "' .. OUT_DIR:gsub("/", "\\") .. '" mkdir "' .. OUT_DIR:gsub("/", "\\") .. '"')
    else
        os.execute('mkdir -p "' .. OUT_DIR .. '"')
    end
end
ensure_out_dir()

-- ── tiny inline JSON encoder (mirrors the gen3_frlge_client.lua helper) ──────
local function json_encode(val)
    local t = type(val)
    if t == "nil" or val == nil then return "null"
    elseif t == "boolean" then return val and "true" or "false"
    elseif t == "number" then
        if val ~= val or val == math.huge or val == -math.huge then return "null" end
        if val == math.floor(val) then return string.format("%d", val) end
        return string.format("%.17g", val)
    elseif t == "string" then
        return '"' .. val:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\r', '\\r'):gsub('\t', '\\t') .. '"'
    elseif t == "table" then
        local n = 0
        for k in pairs(val) do
            if type(k) ~= "number" then n = -1; break end
            n = n + 1
        end
        if n >= 0 then
            local parts = {}
            for i = 1, n do parts[i] = json_encode(val[i]) end
            return "[" .. table.concat(parts, ",") .. "]"
        else
            local parts = {}
            for k, v in pairs(val) do
                parts[#parts + 1] = '"' .. tostring(k) .. '":' .. json_encode(v)
            end
            return "{" .. table.concat(parts, ",") .. "}"
        end
    end
    return "null"
end

-- ── helpers ───────────────────────────────────────────────────────────────────
local last_snapshot     = nil  -- list of {slot, blob_hex, species_id, level}
local last_inject_species = nil  -- list of species_ids from the most recent inject

local function log(msg) console.log("[T-RS] " .. msg) end

local function read_live_party()
    local snapshot = {}
    for slot = 0, 5 do
        local bytes = M.readPartyBlob(slot)
        if not bytes then break end
        local base  = M.PARTY_BASE + slot * M.MON_SIZE
        local sid   = 0
        do local ok2, s = pcall(M.decryptSpecies, base); if ok2 and s then sid = s end end
        snapshot[#snapshot + 1] = {
            slot       = slot,
            species_id = sid,
            level      = memory.read_u8(base + M.OFF_LEVEL),
            blob_hex   = M.bytesToHex(bytes),
        }
    end
    return snapshot
end

-- Builds a synthetic 6-mon team by CLONING the user's current slot-0 party mon
-- and overriding only (species_id, level, PID).  All other engine-required
-- fields — sanity byte, substruct order, IVs, EVs, ability bits, nickname,
-- OT name, moves, PP, stats, checksum — stay valid because they come from a
-- real, engine-blessed mon.  Building a mon from scratch corrupts the team
-- because some of those fields (status2 lock bits, stat values, ability slot
-- selectors, sanity flags) have non-obvious dependencies the engine reads at
-- render time.
--
-- Tradeoff: stats (atk/def/spd/spA/spD/maxHP at 0x58..0x65) are the SLOT-0
-- species' values, not the injected species' — so an injected Mewtwo with
-- Pidgey base stats will look weak.  This is fine for visual verification of
-- the swap (the sprite/level/species name all change correctly) and matches
-- the AS-IS partner-team policy: the partner's mons go in with their own
-- already-computed stats, not freshly rolled ones.
local function build_synthetic_mon(template_bytes, species_id, level, pid_seed)
    local b = {}
    for i = 1, M.MON_SIZE do b[i] = template_bytes[i] end
    -- Personality (u32 LE) at offset 0x00..0x03 — give each mon a unique PID
    -- so its monKey doesn't collide with the source mon.  Cheap LCG.
    local pid = ((pid_seed * 0x9E3779B1) + 0xDEAD0001) & 0xFFFFFFFF
    b[0x00 + 1] =  pid        & 0xFF
    b[0x00 + 2] = (pid >>  8) & 0xFF
    b[0x00 + 3] = (pid >> 16) & 0xFF
    b[0x00 + 4] = (pid >> 24) & 0xFF
    -- Substruct 0 (Growth) at OFF_SUBSTRUCT = 0x20, species u16 at +0x00.
    -- CFRU_NO_ENCRYPT: written unencrypted in fixed G/A/E/M order, so this
    -- single 2-byte write changes the species correctly.
    b[0x20 + 1] =  species_id        & 0xFF
    b[0x20 + 2] = (species_id >> 8) & 0xFF
    -- Level at OFF_LEVEL = 0x54.  HP at 0x56 stays whatever the template had;
    -- if the source mon was at full HP, the injected mon will be too.
    b[0x54 + 1] = level & 0xFF
    return b
end

-- 6 deterministic species so the visual swap is unmistakable:
--   6 Charizard · 9 Blastoise · 3 Venusaur · 25 Pikachu · 143 Snorlax · 150 Mewtwo
local SYNTHETIC_SPECIES = {6, 9, 3, 25, 143, 150}
local SYNTHETIC_LEVEL   = 50

local function build_synthetic_team()
    local template = M.readPartyBlob(0)
    if not template then return nil, "party slot 0 is empty — catch a starter first, then press F7" end
    local team = {}
    for i, sid in ipairs(SYNTHETIC_SPECIES) do
        team[i] = build_synthetic_mon(template, sid, SYNTHETIC_LEVEL, i)
    end
    return team
end

-- ── hotkey handlers ───────────────────────────────────────────────────────────

local function do_snapshot()
    local snap = read_live_party()
    if #snap == 0 then
        log("snapshot: party is EMPTY — nothing to capture")
        return
    end
    -- Validate every blob is exactly MON_SIZE bytes → 2*MON_SIZE hex chars.
    for _, e in ipairs(snap) do
        if #e.blob_hex ~= M.MON_SIZE * 2 then
            log(string.format("snapshot: FAIL slot %d blob_hex length=%d (expected %d)",
                e.slot, #e.blob_hex, M.MON_SIZE * 2))
            return
        end
    end
    ensure_out_dir()
    local f, ferr = io.open(OUT_FILE, "w")
    if not f then
        log("snapshot: FAIL — cannot open " .. OUT_FILE .. " (" .. tostring(ferr) .. ")")
        return
    end
    f:write(json_encode({
        rom_profile = (M.CFRU_NO_ENCRYPT and "radical_red") or "vanilla_or_ap",
        party_base  = string.format("0x%08X", M.PARTY_BASE or 0),
        mon_size    = M.MON_SIZE,
        slots       = snap,
    }))
    f:close()
    last_snapshot = snap
    log(string.format("snapshot: %d mons, written to %s (blob_hex length per mon = %d)",
        #snap, OUT_FILE, M.MON_SIZE * 2))
    for _, e in ipairs(snap) do
        log(string.format("  slot %d  species=%-4d  level=%-3d", e.slot, e.species_id, e.level))
    end
end

local function do_inject(label, blobs)
    if not M.isInBattle() then
        log(label .. ": not in battle — write skipped (gEnemyParty unsafe outside battle)")
        return
    end
    if M.isBorrowedBattle and M.isBorrowedBattle() then
        log(label .. ": borrowed-party battle (Poké Dude / mock) — write skipped")
        return
    end
    local species, werr = M.writeEnemyParty(blobs)
    if not species then
        log(label .. ": writeEnemyParty FAILED — " .. tostring(werr))
        return
    end
    last_inject_species = species
    log(string.format("%s: injected %d mons: species=[%s]",
        label, #species, table.concat(species, ",")))
end

local function do_inject_self()
    local snap = last_snapshot or read_live_party()
    if #snap == 0 then
        log("inject_self: party is EMPTY — nothing to inject")
        return
    end
    local blobs = {}
    for i, e in ipairs(snap) do blobs[i] = e.blob_hex end  -- hex strings auto-decoded
    do_inject("inject_self", blobs)
end

local function do_inject_synthetic()
    local team, terr = build_synthetic_team()
    if not team then
        log("inject_synthetic: " .. tostring(terr))
        return
    end
    do_inject("inject_synthetic", team)
end

local function do_readback_diff()
    -- After an inject (F6/F7): compare gEnemyParty species against what we
    -- told writeEnemyParty to put there.  Cheap end-to-end check that the
    -- write reached the engine and the engine accepted it.
    if last_inject_species then
        local read = M.readEnemyParty()
        local got = {}
        for i = 1, #read do got[i] = read[i].species_id end
        local pass = (#got == #last_inject_species)
        if pass then
            for i = 1, #got do
                if got[i] ~= last_inject_species[i] then pass = false; break end
            end
        end
        log(string.format("readback (inject) %s  sent=[%s] got=[%s]",
            pass and "PASS" or "FAIL",
            table.concat(last_inject_species, ","),
            table.concat(got, ",")))
        return
    end
    -- After F5 only: verify the snapshot file round-trips against gPlayerParty.
    -- Re-read every byte of every saved slot from RAM and confirm the saved
    -- hex matches.  Proves readPartyBlob + bytesToHex + hexToBytes are lossless.
    if last_snapshot then
        local fail_at = nil
        for _, e in ipairs(last_snapshot) do
            local now = M.readPartyBlob(e.slot)
            if not now then fail_at = string.format("slot %d empty", e.slot); break end
            local now_hex = M.bytesToHex(now)
            if now_hex ~= e.blob_hex then
                fail_at = string.format("slot %d hex differs (party changed since F5?)", e.slot)
                break
            end
        end
        if fail_at then
            log("readback (snapshot) FAIL — " .. fail_at)
        else
            log(string.format("readback (snapshot) PASS  %d slot(s) round-trip cleanly",
                #last_snapshot))
        end
        return
    end
    log("readback: no prior snapshot or injection — press F5, F6, or F7 first")
end

-- ── Auto-trigger: mirror the production client's rival-detection loop ───────
-- Hardcoded RR Terry rival IDs (27 entries: classes 81/89/90 in rr_trainers.json).
-- Source of truth on the server side is server/adapters/gen3_frlge.py
-- (_RR_RIVAL_TRAINER_IDS); keep this list in sync if a future RR patch adds IDs.
local RIVAL_IDS = {
    [325]=true,[326]=true,[327]=true,[328]=true,[329]=true,[330]=true,[331]=true,
    [332]=true,[333]=true,[425]=true,[426]=true,[427]=true,[428]=true,[429]=true,
    [430]=true,[431]=true,[432]=true,[433]=true,[434]=true,[435]=true,[436]=true,
    [437]=true,[438]=true,[439]=true,[738]=true,[739]=true,[740]=true,
}

local auto_enabled         = true
local TRAINER_STABLE_GATE  = 2  -- frames; matches gen3_frlge_client.lua
local trainer_last_id      = 0
local trainer_stable       = 0
local trainer_battle_sent  = false  -- one-shot per battle
local prev_in_battle_auto  = false

-- Picks the blob list to auto-inject: prefer the most recent F5 snapshot so
-- the user can curate what the rival fights with; fall back to a fresh live
-- read of gPlayerParty if they never snapshotted (simulates "partner sends
-- their party on hello").
local function auto_blobs()
    if last_snapshot and #last_snapshot > 0 then
        local b = {}
        for i, e in ipairs(last_snapshot) do b[i] = e.blob_hex end
        return b, "snapshot"
    end
    local live = read_live_party()
    if #live == 0 then return nil, nil end
    local b = {}
    for i, e in ipairs(live) do b[i] = e.blob_hex end
    return b, "live"
end

local function auto_trigger_check(in_battle)
    -- Reset one-shot on battle-end transition (mirrors client's battle_just_ended).
    if prev_in_battle_auto and not in_battle then
        trainer_battle_sent = false
        trainer_last_id     = 0
        trainer_stable      = 0
    end
    prev_in_battle_auto = in_battle
    if not auto_enabled or not in_battle or trainer_battle_sent then return end
    if not M.TRAINER_OPPONENT_ADDR or M.TRAINER_OPPONENT_ADDR == 0 then return end
    local tid = M.readTrainerOpponentId()
    if not tid or tid <= 0 then return end
    -- Filter wild battles + borrowed-party battles (Poké Dude / mock).
    if M.isWildBattle() == true then return end
    if M.isBorrowedBattle and M.isBorrowedBattle() then return end
    -- 2-frame stability gate: gTrainerBattleOpponent_A is written in stages
    -- during CFRU battle init; wait until it stops moving.
    if tid == trainer_last_id then
        trainer_stable = trainer_stable + 1
    else
        trainer_last_id = tid
        trainer_stable  = 1
    end
    if trainer_stable < TRAINER_STABLE_GATE then return end
    trainer_battle_sent = true
    if not RIVAL_IDS[tid] then
        log(string.format("auto-trigger: trainer_id=%d is_rival=false → no inject", tid))
        return
    end
    local blobs, src = auto_blobs()
    if not blobs then
        log(string.format("auto-trigger: trainer_id=%d is_rival=true but party EMPTY — no inject", tid))
        return
    end
    log(string.format("auto-trigger: trainer_id=%d is_rival=true → injecting %d mons from %s",
        tid, #blobs, src))
    do_inject("auto", blobs)
end

-- ── edge-triggered key polling (Mirrors test_2_force_faint.lua style) ────────
local prev_keys = {}
local function key_pressed(name)
    local keys = input.get()
    local now  = keys[name] and true or false
    local was  = prev_keys[name] or false
    prev_keys[name] = now
    return now and not was
end

while true do
    if key_pressed("F5") then do_snapshot() end
    if key_pressed("F6") then do_inject_self() end
    if key_pressed("F7") then do_inject_synthetic() end
    if key_pressed("F8") then do_readback_diff() end
    if key_pressed("F9") then
        auto_enabled = not auto_enabled
        log("auto-trigger " .. (auto_enabled and "ENABLED" or "DISABLED"))
    end
    -- Per-frame auto-detect: cheap reads; bails on first failed gate.
    local ok_ib, in_battle = pcall(M.isInBattle)
    auto_trigger_check(ok_ib and in_battle or false)
    emu.frameadvance()
end
