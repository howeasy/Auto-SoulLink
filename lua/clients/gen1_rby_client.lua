--[[
  lua/clients/gen1_rby_client.lua — SLink Gen 1 Client (Production Script)
  ========================================================================
  Supports Pokemon Red, Blue, and Yellow (US English) in BizHawk.
  Variant is auto-detected from the ROM header title.

  Significantly simpler than the Gen 3 client due to Gen 1's lack of
  encryption, ASLR, borrowed battles, and complex battle mechanics.
  All party/box data is plaintext. Stats are big-endian.

  Run server first:
      python -m server.server --host 127.0.0.1 --port 54321

  ┌─ EVENTS DETECTED AUTOMATICALLY ───────────────────────────────────────
  │  hello          — on TCP connect / reconnect (party snapshot)
  │  area_enter     — map ID changes to a mapped encounter zone
  │  capture        — (battle) new monKey in party/box during/after battle
  │  capture        — (gift)   new monKey in party outside battle context
  │  faint          — party mon HP transitions from > 0 to 0
  │  no_catch       — wild battle ends, no capture in grace window
  │  whiteout       — all living party mons transition to HP = 0
  │  party_to_box   — party monKey disappears (deposited at PC)
  │  box_to_party   — previously known monKey returns to party from box
  │  key_change     — evolution (species changes, DVs+OTID invariant), or an
  │                   in-game NPC trade (all three change) — the link MIGRATES
  │  tick           — automatic every 30 frames; carries ball_count
  └────────────────────────────────────────────────────────────────────────

  ┌─ COMMANDS DISPATCHED ──────────────────────────────────────────────────
  │  force_faint    — write HP = 0 to matching party slot (immediate)
  │  box_mon        — deposit partner's linked mon to PC (deferred: safe state)
  │  party_mon      — restore partner's linked mon to party (deferred: safe state)
  │  memorialize    — move dead mon to PC box as graveyard (deferred: safe state)
  │  hud_show       — display text on the BizHawk HUD overlay
  │  noop           — no action
  └────────────────────────────────────────────────────────────────────────

  Manual F keys:
    F1  → area_enter        (current area_id)
    F2  → capture           (party slot 0)
    F3  → faint             (party slot 0)
    F4  → no_catch          (current area_id)
    F5  → whiteout
    F6  → tick              (includes ball_count)
--]]

-- ── CONFIGURE ─────────────────────────────────────────────────────────────────
-- Launcher scripts set SLINK_* globals before dofile("clients/gen1_rby_client.lua").
-- Direct loading uses the defaults below.
local SERVER_HOST = SLINK_HOST   or "127.0.0.1"
local SERVER_PORT = SLINK_PORT   or 54321
local PLAYER_ID   = SLINK_PLAYER or "a"
-- Clear globals so they don't leak across reloads
SLINK_HOST = nil; SLINK_PORT = nil; SLINK_PLAYER = nil
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Module loading ────────────────────────────────────────────────────────────
local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])clients[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _lua_root .. "games/?.lua;"
           .. _proj_root .. "data/games/gen1_rby/?.lua;"
           .. package.path

-- Force fresh module loads on script restart
package.loaded["memory_gb"]            = nil
package.loaded["connector"]            = nil
package.loaded["socket"]               = nil
package.loaded["hud"]                  = nil
package.loaded["games.gen1_rby"]       = nil
package.loaded["games.gen1_rby_trainers"] = nil
package.loaded["gen1_rby_areas"]       = nil

local M   = require("memory_gb")
local C   = require("connector")
local HUD = require("hud")
local G   = require("games.gen1_rby")
local TRAINERS = require("games.gen1_rby_trainers")

-- ── Localized hot-path globals ────────────────────────────────────────────────
local fmt    = string.format
local mem_r8 = memory.read_u8

-- ── JSON encoder ──────────────────────────────────────────────────────────────
local _json_esc = {['\\']='\\\\', ['"']='\\"', ['\n']='\\n', ['\r']='\\r', ['\t']='\\t'}
local function json_encode(val)
    local t = type(val)
    if val == nil         then return "null"
    elseif t == "boolean" then return val and "true" or "false"
    elseif t == "number"  then
        if val == val and val % 1 == 0 and val >= -2147483648 and val <= 2147483647 then
            return string.format("%d", val)
        end
        return tostring(val)
    elseif t == "string"  then
        return '"' .. val:gsub('[\\"\n\r\t]', _json_esc) .. '"'
    elseif t == "table" then
        local n = #val
        local is_arr = (n > 0)
        if is_arr then
            local cnt = 0
            for _ in pairs(val) do cnt = cnt + 1; if cnt > n then is_arr = false; break end end
            if cnt ~= n then is_arr = false end
        end
        local p, pn = {}, 0
        if is_arr then
            for i = 1, n do pn = pn + 1; p[pn] = json_encode(val[i]) end
            return "[" .. table.concat(p, ",") .. "]"
        else
            for k, v in pairs(val) do
                pn = pn + 1
                p[pn] = '"' .. tostring(k) .. '":' .. json_encode(v)
            end
            return "{" .. table.concat(p, ",") .. "}"
        end
    else return "null" end
end

-- ── Response parsing ──────────────────────────────────────────────────────────
-- Last link_panel payload. The panel is opened from the START menu by the player, which may
-- be long after the rows arrived, so they are kept rather than drawn on receipt.
local panel_rows = nil

local function parse_command_list(raw)
    local cmds = {}
    local arr = raw:match('"commands"%s*:%s*(%b[])')
    if not arr then return cmds end
    for obj in arr:gmatch('%b{}') do
        local cmd     = obj:match('"cmd"%s*:%s*"([^"]+)"')
        local key     = obj:match('"key"%s*:%s*"([^"]+)"')
        local text    = obj:match('"text"%s*:%s*"([^"]*)"')
        -- link_panel rows: a flat JSON array of strings. A naive quoted-string scrape is
        -- safe here because the compact rows the server builds for a 20-column screen carry
        -- only letters, digits, spaces and '-' — never a quote or a backslash.
        local rows = nil
        local rowsj = obj:match('"rows"%s*:%s*(%b[])')
        if rowsj then
            rows = {}
            for r_ in rowsj:gmatch('"([^"]*)"') do rows[#rows + 1] = r_ end
        end
        local r       = tonumber(obj:match('"r"%s*:%s*(%d+)'))
        local g       = tonumber(obj:match('"g"%s*:%s*(%d+)'))
        local b       = tonumber(obj:match('"b"%s*:%s*(%d+)'))
        local frames  = tonumber(obj:match('"frames"%s*:%s*(%d+)'))
        local fb      = obj:match('"fb"%s*:%s*"([^"]*)"')   -- msgbox fallback style (prompt/hud)
        -- Numeric Gen 3 SE id (the server emits `"sound": 25`), mapped to a semantic
        -- event name by playSfxFromGen3Id. Unquoted, so match digits — not a string.
        local sound   = tonumber(obj:match('"sound"%s*:%s*(%d+)'))
        -- Attached to force_faint by the server so the toast can name a mon we have
        -- never held (state.py queues it in four places).
        local nickname = obj:match('"nickname"%s*:%s*"([^"]*)"')
        -- Cached party-only stats attached to party_mon. Gen 1's box struct drops level,
        -- maxHP and the computed stats, so without these a withdrawn mon comes back
        -- with maxHP equal to whatever HP it had when deposited.
        local stats = nil
        local sj = obj:match('"stats"%s*:%s*(%b{})')
        if sj then
            stats = {
                level   = tonumber(sj:match('"level"%s*:%s*(%d+)')),
                maxHP   = tonumber(sj:match('"maxHP"%s*:%s*(%d+)')),
                attack  = tonumber(sj:match('"attack"%s*:%s*(%d+)')),
                defense = tonumber(sj:match('"defense"%s*:%s*(%d+)')),
                speed   = tonumber(sj:match('"speed"%s*:%s*(%d+)')),
                spAtk   = tonumber(sj:match('"spAtk"%s*:%s*(%d+)')),
                spDef   = tonumber(sj:match('"spDef"%s*:%s*(%d+)')),
            }
        end
        -- replace_rival_team carries the partner's team as an array of hex blobs.
        local blobs_hex = nil
        local blobs_raw = obj:match('"blobs_hex"%s*:%s*(%b[])')
        if blobs_raw then
            blobs_hex = {}
            for h in blobs_raw:gmatch('"([0-9A-Fa-f]*)"') do blobs_hex[#blobs_hex + 1] = h end
        end
        local area_id = obj:match('"area_id"%s*:%s*"([^"]*)"')
        local areas   = nil
        local areas_raw = obj:match('"areas"%s*:%s*(%b[])')
        if areas_raw then
            areas = {}
            for a in areas_raw:gmatch('"([^"]+)"') do
                areas[#areas + 1] = a
            end
        end
        if cmd then
            cmds[#cmds + 1] = {
                cmd = cmd, key = key, text = text, fb = fb, sound = sound,
                nickname = nickname, stats = stats, blobs_hex = blobs_hex,
                r = r, g = g, b = b, frames = frames,
                area_id = area_id, areas = areas, rows = rows,
            }
        end
    end
    return cmds
end

-- ── ROM profile detection and validation ─────────────────────────────────────
local variant = G.detect_variant()
if not variant then
    error("Gen 1 RBY client: ROM not detected as Red, Blue, or Yellow")
end
M.initProfile(G, variant)
local rom_type        = G.rom_type_for_variant(variant)
local val_ok, val_err = M.validateROM()
local writes_enabled  = val_ok

-- THE GATE HAS TO BE REVOCABLE, not just deferred.
-- `writes_enabled` was only ever flipped ON: nothing set it back. Soft-reset the console
-- mid-run (A+B+Start+Select) and WRAM zeroes -- but M.isInOverworld() reads TRUE on all-zero
-- memory (not in battle, no joypad ignore, font not loaded), so the deferred-sync executor
-- kept running and wrote party structs and box SRAM against the title screen. Gen 2 has had
-- the revoke since it shipped (gen2_crystal_client.lua:1082-1100); this is the same shape.
-- The threshold is there because a single frame's read can glitch while menus open.
local validate_fail_count = 0
local VALIDATE_FAIL_THRESHOLD = 5

-- Optional companion patch (vanilla Red/Blue only). Its one player-visible feature is sound:
-- Gen 1 has no RAM-writable audio trigger, so an unpatched cartridge stays silent and every
-- playSfx call is a no-op. Detection reads the beacon, so a wrong or absent patch is inert.
local patch_abi = M.detectCompanionPatch()  -- re-read on revalidate/reconnect, see redetect_patch

console.log(fmt("[SLink-RBY] Detected: %s (variant=%s) writes=%s patch=%s",
    G.display_name, variant, tostring(writes_enabled),
    patch_abi and ("ABI " .. patch_abi) or "none (SFX disabled)"))
if not val_ok then
    console.log(fmt("[SLink-RBY] ROM validation: %s (will retry each frame)", val_err))
end

-- ── HUD overlay ───────────────────────────────────────────────────────────────
-- GB screen: 160 × 144
HUD.init({screen_w = 160, screen_h = 144, hud_x = 2, hud_y = 134, hud_right = 158,
          prompt_y = 36, prompt_h = 10, gameover_y = 50, font_size = 8, char_width = 5})
local hud_show    = HUD.show
local hud_render  = HUD.render
local prompt_show = HUD.prompt

-- ── Nick cache for HUD display ────────────────────────────────────────────────
local nick_cache = {}
local function nick_label(key)
    return nick_cache[key] or (key and key:sub(1, 9) or "???")
end

-- ── Send / receive ────────────────────────────────────────────────────────────
local seq            = 0
local pending_labels = {}

local function send(evt, label, is_auto)
    if not C.connected() then
        console.log("[SLink-RBY] NOT CONNECTED — dropped: " .. (label or evt.event))
        return
    end
    seq = seq + 1; evt.seq = seq; evt.player = PLAYER_ID
    C.send(json_encode(evt))
    local prefix = is_auto and "AUTO" or "MANUAL"
    pending_labels[#pending_labels + 1] = prefix .. " " .. seq .. ": " .. (label or evt.event)
    if label ~= "tick" then
        console.log(fmt("[SLink-RBY] [→] seq=%d  %s: %s", seq, prefix, label or evt.event))
    end
end

-- ── Command dispatcher ────────────────────────────────────────────────────────
local resolved_areas        = {}
local resolved_areas_seeded = false
local rebuild_active        = false  -- true between rebuild_start and rebuild_done

-- Sync command queue (box_mon / party_mon / memorialize — deferred until safe).
-- MUST be declared before dispatch_commands: a local declared after a function is
-- not in that function's scope, so the queue reads below would bind to a nil global
-- and `ipairs(nil)` would kill the client on the first deferred command.
-- Every other gen's client declares these before its dispatcher for the same reason.
local pending_sync_cmds = {}
local sync_written_keys = {}  -- keys recently written to avoid re-triggering events

local function dispatch_commands(cmds)
    for _, c in ipairs(cmds) do
        -- ONE MALFORMED COMMAND MUST NOT TAKE OUT THE BATCH. Gen 1 has more raise
        -- surface here than Gen 2 (gen2_crystal_client.lua:255 wraps the same loop):
        -- it also handles force_explode and replace_rival_team, and the latter runs
        -- M.hexToBytes over a server-supplied string before writing it into
        -- wEnemyMons. Unwrapped, a bad payload aborted the remaining commands in the
        -- batch AND the rest of the frame.
        local cmd_ok, cmd_err = pcall(function()
        if c.cmd == "force_faint" and c.key then
            -- Seed the nickname cache from the server, which attaches it precisely so the
            -- toast can name a mon we have never held. Without this nick_label falls back
            -- to the raw key.
            if c.nickname and c.nickname ~= "" then
                nick_cache[c.key] = c.nickname
            end
            if writes_enabled then
                local count = M.getPartyCount()
                for slot = 0, count - 1 do
                    local mon = M.readPartySlot(slot)
                    if mon and mon.key == c.key then
                        M.forceFaint(slot)
                        console.log(fmt("[SLink-RBY]   ↳ DISPATCHED force_faint slot=%d key=%s", slot, c.key))
                        hud_show("!! " .. nick_label(c.key) .. " DIED!", 255, 80, 80, 360)
                        break
                    end
                end
            else
                console.log("[SLink-RBY]   ↳ force_faint skipped (writes off) key=" .. tostring(c.key))
            end
        elseif c.cmd == "force_explode" and c.key then
            -- Explode Mode: coerce the surviving partner into Explosion instead of the
            -- deferred force_faint. Gen 1 needs no ROM patch — the engine reads the chosen
            -- move from wPlayerSelectedMove. Only meaningful for the ACTIVE battler; a
            -- benched mon falls back to the plain faint so the rule still lands.
            local done = false
            if writes_enabled and M.isInBattle() then
                local count = M.getPartyCount()
                -- wPlayerMonNumber holds the party slot that is actually out; defaulting to
                -- slot 0 would arm the wrong mon whenever the player has switched.
                local active = M.getActivePartySlot and M.getActivePartySlot() or 0
                for slot = 0, count - 1 do
                    local mon = M.readPartySlot(slot)
                    if mon and mon.key == c.key then
                        if slot == active then
                            local ok = M.forceExplode(slot)
                            if ok then
                                done = true
                                console.log("[SLink-RBY]   ↳ force_explode armed: " .. c.key:sub(1, 8))
                                hud_show("!! " .. nick_label(c.key) .. " EXPLODES!", 255, 140, 40, 300)
                            end
                        end
                        break
                    end
                end
            end
            if not done then
                -- Benched, not in battle, or writes off — fall back to the normal faint.
                if writes_enabled then
                    local count = M.getPartyCount()
                    for slot = 0, count - 1 do
                        local mon = M.readPartySlot(slot)
                        if mon and mon.key == c.key then
                            M.forceFaint(slot)
                            hud_show("!! " .. nick_label(c.key) .. " DIED!", 255, 80, 80, 360)
                            break
                        end
                    end
                end
                console.log("[SLink-RBY]   ↳ force_explode fell back to force_faint")
            end
        elseif c.cmd == "replace_rival_team" and c.blobs_hex then
            -- Rival Team Swap: byte-copy the partner's live party over the rival's.
            -- Gen 1's enemy party is plaintext at a fixed address, so unlike Gen 3 this
            -- needs no companion patch.
            local ok, err = false, "writes disabled"
            if writes_enabled then
                local blobs = {}
                for _, h in ipairs(c.blobs_hex) do
                    local b = M.hexToBytes and M.hexToBytes(h)
                    if b then blobs[#blobs + 1] = b end
                end
                if #blobs > 0 then
                    ok, err = M.writeEnemyParty(blobs)
                else
                    ok, err = false, "no decodable blobs"
                end
            end
            if ok then
                console.log(fmt("[SLink-RBY]   ↳ replace_rival_team OK (%s mons)", tostring(err)))
                hud_show("** RIVAL TEAM SWAP **", 255, 120, 255, 300)
                send({event = "rival_team_replaced", n = err}, "rival_team_replaced", true)
            else
                console.log("[SLink-RBY]   ↳ replace_rival_team FAIL: " .. tostring(err))
                send({event = "rival_team_replaced", error = tostring(err)},
                     "rival_team_replaced", true)
            end
        elseif c.cmd == "hud_show" and c.text then
            hud_show(c.text, c.r or 255, c.g or 255, c.b or 255, c.frames or 300)
        elseif c.cmd == "gui_prompt" and c.text then
            prompt_show(c.text, c.r or 255, c.g or 255, c.b or 255, c.frames or 300)
            console.log("[SLink-RBY]   ↳ gui_prompt: " .. c.text)
        elseif c.cmd == "msgbox" and c.text then
            -- Gen 3's native message-box command (link-formed / dead-zone / shiny notices are
            -- sent as msgbox to every gen) — render via the Lua overlay here.
            if c.fb == "hud" then
                hud_show(c.text, c.r or 255, c.g or 255, c.b or 255, c.frames or 300)
            else
                prompt_show(c.text, c.r or 255, c.g or 255, c.b or 255, c.frames or 300)
            end
            console.log("[SLink-RBY]   ↳ msgbox: " .. c.text)
        elseif c.cmd == "play_sound" and c.sound then
            -- Gen 3 emits m4a SE_* IDs (95=SHINY, 26=FAILURE, 25=SUCCESS, 22=BOO).
            -- Translated to semantic event names; profile sfx_ids resolves to a
            -- ROM-specific SFX ID. No-op until Phase 7 SFX_DISPATCH_ADDR is set.
            M.playSfxFromGen3Id(c.sound)
        elseif c.cmd == "box_mon" and c.key then
            -- Cancel any pending party_mon for the same key
            local filtered = {}
            for _, p in ipairs(pending_sync_cmds) do
                if not (p.key == c.key and p.cmd == "party_mon") then
                    filtered[#filtered + 1] = p
                end
            end
            pending_sync_cmds = filtered
            pending_sync_cmds[#pending_sync_cmds + 1] = {cmd = "box_mon", key = c.key}
            console.log("[SLink-RBY]   ↳ box_mon QUEUED: " .. c.key:sub(1, 8))
        elseif c.cmd == "party_mon" and c.key then
            -- Cancel any pending box_mon for the same key
            local filtered = {}
            for _, p in ipairs(pending_sync_cmds) do
                if not (p.key == c.key and p.cmd == "box_mon") then
                    filtered[#filtered + 1] = p
                end
            end
            pending_sync_cmds = filtered
            -- CARRY c.stats THROUGH. This enqueued only {cmd, key}, so the `cmd.stats` the
            -- executor reads was ALWAYS nil and the server's mon_stats block never reached
            -- retrieveBoxMon. The box struct does not carry maxHP or the five stats, so the
            -- only surviving source was the in-process _party_tail_cache — which dies with
            -- the client. Since retrieveBoxMon now refuses rather than returning a zeroed
            -- mon, that made party_mon fail outright after any restart.
            pending_sync_cmds[#pending_sync_cmds + 1] =
                {cmd = "party_mon", key = c.key, stats = c.stats}
            console.log(fmt("[SLink-RBY]   ↳ party_mon QUEUED: %s (stats=%s)",
                            c.key:sub(1, 8), c.stats and "yes" or "no"))
        elseif c.cmd == "memorialize" and c.key then
            -- Deduplicate: skip if already queued
            local already_queued = false
            for _, p in ipairs(pending_sync_cmds) do
                if p.cmd == "memorialize" and p.key == c.key then
                    already_queued = true; break
                end
            end
            if not already_queued then
                -- Cancel any stale box_mon/party_mon for the same key
                local filtered = {}
                for _, p in ipairs(pending_sync_cmds) do
                    if not (p.key == c.key and (p.cmd == "box_mon" or p.cmd == "party_mon")) then
                        filtered[#filtered + 1] = p
                    end
                end
                pending_sync_cmds = filtered
                pending_sync_cmds[#pending_sync_cmds + 1] = {cmd = "memorialize", key = c.key}
                console.log("[SLink-RBY]   ↳ memorialize QUEUED: " .. c.key:sub(1, 8))
            else
                console.log("[SLink-RBY]   ↳ memorialize deduped: " .. c.key:sub(1, 8))
            end
        elseif c.cmd == "resolved_areas" and c.areas then
            for _, a in ipairs(c.areas) do resolved_areas[a] = true end
            resolved_areas_seeded = true
            console.log(fmt("[SLink-RBY]   ↳ resolved_areas: %d areas seeded", #c.areas))
        elseif c.cmd == "unresolve_area" and c.area_id then
            resolved_areas[c.area_id] = nil
            console.log("[SLink-RBY]   ↳ unresolve_area: " .. c.area_id)
        elseif c.cmd == "game_over" then
            if M.playSE then M.playSE(M.SE_GAME_OVER) end
            HUD.set_game_over()
            console.log("[SLink-RBY]   ↳ GAME OVER — SOUL LINK")
        elseif c.cmd == "link_panel" and c.rows then
            -- Held, not drawn. The panel is only allowed to touch the tile map while the
            -- ROM patch says the screen is free; painting on arrival would scribble over
            -- whatever the player is looking at.
            panel_rows = c.rows
            console.log(string.format("[SLink-RBY]   ↳ link_panel: %d rows held", #c.rows))
        elseif c.cmd == "rebuild_start" then
            rebuild_active = true
            HUD.set_rebuilding(c.text or "REBUILDING TEAM")
            console.log("[SLink-RBY]   ↳ rebuild_start: " .. tostring(c.text))
        elseif c.cmd == "rebuild_done" then
            rebuild_active = false
            HUD.clear_rebuilding()
            console.log("[SLink-RBY]   ↳ rebuild_done")
        elseif c.cmd ~= "noop" then
            console.log("[SLink-RBY]   ↳ cmd: " .. tostring(c.cmd))
        end
        end)
        if not cmd_ok then
            console.log("[SLink-RBY]   ↳ cmd ERROR (" .. tostring(c.cmd) .. "): "
                        .. tostring(cmd_err))
        end
    end
end

-- ── Per-frame state ───────────────────────────────────────────────────────────
local initialized       = false
local was_connected     = false
local frame_count       = 0

-- Battle tracking
local in_battle           = false
local prev_in_battle      = false
-- Set when a battle ends; cleared on the first genuinely-overworld frame, which is when
-- the `safe` event fires. The server treats `safe` like a tick that also means "deferred
-- commands can run now", so it must not be sent while a menu or script still owns input.
local pending_safe        = false
-- Rival Team Swap: trainer_battle_start fires once per trainer battle, and only after the
-- opponent id has held steady. wCurOpponent is written during the battle-init sequence, so
-- a single-frame read can catch it mid-update.
local trainer_battle_sent   = false
local trainer_last_id       = nil
local trainer_stable_frames = 0
local TRAINER_STABLE_GATE   = 3
local battle_is_wild      = false
local battle_area_id      = ""
local battle_wild_species = nil   -- what the wild battle was, for no_catch
local battle_wild_level   = nil
local battle_uncatchable  = false -- the engine refuses capture (Tower ghosts, pre-Scope)
local battle_static_area  = nil   -- a scripted encounter's own area, not the route's
local captured_this_battle = false
local post_battle_frames  = 0
local POST_BATTLE_GRACE   = 15  -- frames to wait after battle before no_catch

-- Area tracking
local last_area_id = ""
local last_map_id  = -1

-- Nuzlocke gate
local nuzlocke_active = false

-- (pending_sync_cmds / sync_written_keys are declared above dispatch_commands)

-- ── Party snapshot builder ────────────────────────────────────────────────────
local function build_party_snapshot()
    local count = M.getPartyCount()
    local snap = {}
    -- wPlayerMonNumber (0xCC2F) is the party slot currently on the field, so the
    -- stat-stage badges follow a mid-battle switch instead of staying pinned to slot 0.
    local in_b = in_battle and M.isInBattle()
    local active_slot = in_b and (M.getActivePartySlot and M.getActivePartySlot() or 0) or nil
    local player_stages = in_b and M.readPlayerStatStages() or nil
    for slot = 0, count - 1 do
        local mon = M.readPartySlot(slot)
        if mon and mon.maxHP > 0 then
            local nick = M.readPartyNickname(slot)
            local entry = {
                key = mon.key,
                hp = mon.hp,
                maxHP = mon.maxHP,
                level = mon.level,
                slot = slot,
                species_id = G.toNatDex(mon.species_index),
                nickname = nick,
                status_cond = mon.status_cond or 0,
            }
            -- Raw bytes for the partner's rival-team swap. Rides the existing snapshot
            -- (hello/tick/safe) rather than adding a parallel sync event, matching gen3.
            local blob = M.readPartyBlob(slot)
            if blob then entry.blob_hex = M.bytesToHex(blob) end
            -- Phase 3: moves + PP from party struct. Server enriches into move_details.
            -- PP UPS ARE REAL IN GEN 1. pokered/constants/pokemon_data_constants.asm:100
            -- gives PP_UP_MASK %11000000 / PP_MASK %00111111 under the "PP in box_struct"
            -- header, and the engine masks with PP_MASK everywhere it reads PP. The profile
            -- already declares pp_encoding="ppup_packed" and readMovesAndPP already decodes
            -- it -- the client simply threw the result away and hardcoded 0, so a move with
            -- three PP Ups reported its packed byte as the current PP (33 became 97) and the
            -- maximum was rendered from the unmodified base.
            local party_base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
            local mp = M.readMovesAndPP(party_base, nil)
            if mp then
                entry.moves  = mp.moves
                entry.pp     = mp.pp
                entry.pp_ups = mp.pp_ups     -- server accepts a list (gen4 shape)
            end
            if slot == active_slot and player_stages then
                entry.active = true
                entry.stat_stages = player_stages
            end
            snap[#snap + 1] = entry
            if nick ~= "" then nick_cache[mon.key] = nick end
        end
    end
    return snap
end

-- ── Enemy party snapshot (for battle display) ────────────────────────────────
local function build_enemy_snapshot()
    local enemy = {}
    if not in_battle then return enemy end

    -- For wild battles: single active mon from wEnemyMon (battle struct)
    -- For trainer battles: species list + active mon for HP/level at correct slot
    local active = M.readActiveBattleMon()
    if not active then return enemy end

    local enemy_stages = M.readEnemyStatStages()
    local enemy_moves = M.readEnemyBattleMovesAndPP()
    -- Trainer class/name is emitted by send_hello and send_tick, not from here —
    -- this function only builds the enemy party. Two locals used to be read into
    -- every frame of every trainer battle and then never assigned into any entry.
    if battle_is_wild then
        -- Wild: just the one active mon
        enemy[1] = {
            species_id = G.toNatDex(active.species_index),
            level = active.level,
            hp = active.hp,
            maxHP = active.maxHP,
            active = true,
            status_cond = active.status_cond or 0,
            stat_stages = enemy_stages,
            moves = enemy_moves and enemy_moves.moves or nil,
            pp = enemy_moves and enemy_moves.pp or nil,
            pp_ups = enemy_moves and enemy_moves.pp_ups or nil,
        }
    else
        -- Trainer: read species list for full team; use party_pos to mark active slot
        local species_list = M.getEnemySpeciesList()
        local ecount = M.getEnemyCount()
        local active_slot = active.party_pos or 0  -- 0-indexed slot from battle_struct +0x03
        for i = 1, ecount do
            local sp_idx = species_list[i]
            if sp_idx and sp_idx ~= 0 and sp_idx ~= 0xFF then
                if (i - 1) == active_slot then
                    -- This is the active mon — use battle struct for live HP/level/status
                    enemy[#enemy + 1] = {
                        species_id = G.toNatDex(active.species_index),
                        level = active.level,
                        hp = active.hp,
                        maxHP = active.maxHP,
                        active = true,
                        status_cond = active.status_cond or 0,
                        stat_stages = enemy_stages,
                        moves = enemy_moves and enemy_moves.moves or nil,
                        pp = enemy_moves and enemy_moves.pp or nil,
                        pp_ups = enemy_moves and enemy_moves.pp_ups or nil,
                    }
                else
                    -- Bench mons — only species known from list
                    enemy[#enemy + 1] = {
                        species_id = G.toNatDex(sp_idx),
                        level = 0,
                        hp = 0,
                        maxHP = 0,
                        active = false,
                    }
                end
            end
        end
    end
    return enemy
end

-- ── PC box snapshot ───────────────────────────────────────────────────────────
-- Emits both the currently-active box (read from WRAM) and the dedicated
-- memorial box (read from its fixed SRAM offset, regardless of which box is
-- active). The memorial box gets box=11 (Gen 1 Box 12, 0-indexed) so the
-- server's memorial_box_index filter in handle_debug_raw_state picks it up.
local MEMORIAL_BOX_INDEX = 11  -- Gen 1: Box 12 (last box), 0-indexed

local function build_box_snapshot()
    local entries = {}
    -- Active box (in WRAM). Fall back to 0 only if the profile cannot tell us which box is
    -- open -- a wrong-but-stable index is still better than crashing the snapshot.
    local ok_box, cur_box = pcall(M.getCurrentBoxNum)
    local active_box = (ok_box and cur_box) or 0
    local ok, bcount = pcall(M.getBoxCount)
    if ok and bcount and bcount <= M.BOX_MAX_MONS then
        for i = 0, bcount - 1 do
            local ok2, slot = pcall(M.readBoxSlot, i)
            if ok2 and slot and slot.key then
                local natdex = G.toNatDex(slot.species_index)
                if natdex > 0 then
                    local nick = ""
                    local ok3, n = pcall(M.readBoxNickname, i)
                    if ok3 and n then nick = n end
                    entries[#entries + 1] = {
                        -- The ACTIVE box index, not a constant 0. Gen 1 mirrors only one
                        -- box in WRAM, but it knows which one -- getCurrentBoxNum() masks
                        -- BIT_HAS_CHANGED_BOXES off wCurrentBoxNum and this file already
                        -- uses it for the memorial-box safety check. Reporting 0 made the
                        -- dashboard label every boxed mon "Box 1", and worse: when the
                        -- player made Box 12 active, its mons were reported BOTH as box 0
                        -- here and as box 11 by the memorial read below, so the server saw
                        -- dead keys sitting in a regular box and re-queued memorialize
                        -- every tick.
                        box          = active_box,
                        slot         = i,
                        key          = slot.key,
                        nickname     = nick,
                        species_id   = natdex,
                        held_item_id = 0,  -- Gen 1 has no held items
                        ability_id   = 0,  -- Gen 1 has no abilities
                    }
                end
            end
        end
    end
    -- Memorial box (Box 12, in SRAM at fixed offset)
    local ok_m, mcount = pcall(M.getMemorialBoxCount)
    if ok_m and mcount and mcount > 0 then
        for i = 0, mcount - 1 do
            local ok2, slot = pcall(M.readMemorialBoxSlot, i)
            if ok2 and slot and slot.key then
                local natdex = G.toNatDex(slot.species_index)
                if natdex > 0 then
                    entries[#entries + 1] = {
                        box          = MEMORIAL_BOX_INDEX,
                        slot         = i,
                        key          = slot.key,
                        nickname     = slot.nickname or "",
                        species_id   = natdex,
                        held_item_id = 0,
                        ability_id   = 0,
                    }
                end
            end
        end
    end
    return entries
end

-- ── Hello event ───────────────────────────────────────────────────────────────
local function send_hello()
    local cur_map = M.getCurrentMap()
    local area_id = G.resolve_area(cur_map)
    -- GATE THE SNAPSHOT ON A SANE PARTY COUNT. Every other caller in this file does
    -- (diff_party, send_tick, the `safe` event, the connect seeder); hello was the one
    -- that did not, and it is the worst place to skip it. The server locks
    -- player_identity[pid].ot_id from party[0]'s key on the FIRST hello, so loading the
    -- script at the title screen — the normal thing to do — can read uninitialised WRAM,
    -- latch a garbage OT, and then reject every subsequent hello as "WRONG SAVE" until
    -- someone hand-edits links.json. An empty party is a legitimate state here (a fresh
    -- save), so the guard is on the count being IMPOSSIBLE, not on it being zero.
    local raw_count = M.getPartyCount()
    local snap = (raw_count >= 0 and raw_count <= 6) and build_party_snapshot() or {}
    local cur_in_battle = M.isInBattle()

    local evt = {
        event = "hello",
        rom_type = rom_type,
        area_id = area_id,
        has_pokeballs = M.hasPokeballs(),
        ball_count = M.countPokeballs(),
        -- A BITMASK, not a count. Every other generation sends the raw byte
        -- (gen2 readJohtoBadges, gen3 readBadges' bm, gen4/5 readBadges1) and the
        -- server decodes it bit by bit -- server.py:3772 for the dashboard strip and
        -- :5627 for /stream/badges-*. Sending readBadgeCount() here meant three badges
        -- lit Boulder+Cascade and eight lit only Rainbow, wrong on stream all run.
        badges = M.readBadgeMask(),
        in_battle = cur_in_battle,
        is_trainer_battle = M.isTrainerBattle(),
        party = snap,
        trainer_name = M.readPlayerName(),
        -- THE REAL TRAINER ID, not one inferred from a mon.
        -- The server locks player_identity from party[0]'s key when nothing better is
        -- offered, which makes the lock depend on WHICH MON happens to be in slot 0 --
        -- so an in-game-trade mon (a different OT by definition) in the lead slot locks
        -- the run to the wrong trainer, permanently, and every later hello is rejected as
        -- WRONG SAVE until someone hand-edits links.json. wPlayerID is the cartridge's own
        -- answer and cannot be confused by what is in the party.
        -- Formatted as four hex digits to match parse_ot_id's slice of the mon key, so the
        -- two agree for a mon the player caught themselves.
        ot_id = fmt("%04X", M.readPlayerId()),
    }
    -- WHAT THIS CARTRIDGE ACTUALLY HOLDS. A run may be played on ROMs randomized with UPR
    -- ZX -- same settings, different seeds -- so the encounter tables SLink ships, which
    -- describe retail, are simply wrong for this player. Read them out of the ROM instead.
    -- Sent once with hello because it cannot change while the ROM is loaded.
    --
    -- pcall because this is an optional enrichment: a BizHawk build without a flat "ROM"
    -- domain, or a ROM whose tables do not parse, must not stop the client connecting. The
    -- server treats a missing payload as "no ROM data" and says so, rather than showing
    -- retail species beside a randomized cartridge.
    -- Panel capability is per CARTRIDGE, not per generation: a patched and an unpatched ROM
    -- can sit in the same run, so the server must be told which this is rather than assume
    -- from the game. Reported from the mailbox's capability bits rather than the ABI number,
    -- because a build may ship the panel without SFX or the reverse.
    if M.panelSupported then
        local ok_p, supported = pcall(M.panelSupported)
        if ok_p then
            evt.panel = supported and true or false
            evt.panel_abi = M.panelAbi and select(2, pcall(M.panelAbi)) or 0
        end
    end

    local ok_rc, rc = pcall(G.readRomContent, variant)
    if ok_rc and rc then
        evt.rom_content = rc
    else
        -- No payload at all is different from a payload the server cannot read: with
        -- nothing reported there is no evidence this ROM is unusual, so the server
        -- keeps using the shipped tables. A payload it REJECTS marks the data
        -- unavailable instead.
        log("rom_content unavailable — the server keeps the shipped tables")
    end
    if cur_in_battle then
        local ep = build_enemy_snapshot()
        if #ep > 0 then evt.enemy_party = ep end
        -- CLASS COMES FROM wCurOpponent, NOT wTrainerClass. pokered stores the
        -- class into wTrainerClass only AFTER subtracting OPP_ID_OFFSET:
        --     ld a, [wEnemyMonSpecies2] / sub OPP_ID_OFFSET
        --     jp c, InitWildBattle      / ld [wTrainerClass], a
        -- (engine/battle/core.asm:6673-6677; identical in pokeyellow
        -- engine/battle/init_battle.asm:33-36), so that byte holds the RAW const
        -- $00-$2F. TRAINERS.CLASS_NAMES is keyed 200-247, so every lookup missed
        -- and resolve() returned ("","") for every trainer in the game — no
        -- opponent name or class ever reached the server.
        -- wCurOpponent keeps the +200 form (home/trainers.asm:233-237 stores
        -- wEngagedTrainerClass and compares it against OPP_ID_OFFSET to decide
        -- trainer-vs-wild), which is why rival_trainer_ids() already worked.
        -- wTrainerNo stays as-is: it is the 1-based index WITHIN the class.
        if not battle_is_wild and M.CUR_OPPONENT_ADDR then
            local class_id = M.read_u8(M.CUR_OPPONENT_ADDR)
            local trainer_id = M.read_u8(M.TRAINER_ID_ADDR)
            evt.trainer_class_id = class_id
            evt.trainer_id = trainer_id
            local class_name, trainer_name = TRAINERS.resolve(class_id, trainer_id)
            if class_name ~= "" then evt.opponent_class = class_name end
            if trainer_name ~= "" then evt.opponent_name = trainer_name end
        end
    end
    local ok_b, boxes = pcall(build_box_snapshot)
    if ok_b and boxes then evt.pc_boxes = boxes end
    send(evt, "hello", true)

    -- Log party keys for diagnostics
    if #snap > 0 then
        for i, m in ipairs(snap) do
            console.log(fmt("[SLink-RBY] party[%d] key=%s lv=%d hp=%d/%d",
                i - 1, m.key, m.level or 0, m.hp or 0, m.maxHP or 0))
        end
    else
        console.log("[SLink-RBY] party: empty")
    end
end

-- ── Tick event ────────────────────────────────────────────────────────────────
local function send_tick()
    local evt = {
        event = "tick",
        ball_count = M.countPokeballs(),
        -- A BITMASK, not a count. Every other generation sends the raw byte
        -- (gen2 readJohtoBadges, gen3 readBadges' bm, gen4/5 readBadges1) and the
        -- server decodes it bit by bit -- server.py:3772 for the dashboard strip and
        -- :5627 for /stream/badges-*. Sending readBadgeCount() here meant three badges
        -- lit Boulder+Cascade and eight lit only Rainbow, wrong on stream all run.
        badges = M.readBadgeMask(),
        has_pokeballs = nuzlocke_active,
        in_battle = in_battle,
        is_trainer_battle = not battle_is_wild and in_battle,
        area_id = last_area_id,
    }
    -- Include party snapshot for live HP/level updates on status page
    local raw_count = M.getPartyCount()
    if raw_count >= 1 and raw_count <= 6 then
        evt.party = build_party_snapshot()
    end
    -- Enemy party during battle
    if in_battle then
        local ep = build_enemy_snapshot()
        if #ep > 0 then evt.enemy_party = ep end
        -- Phase 5: emit trainer info for non-wild battles. Server populates
        -- battle_state.opponent_class / opponent_name from these fields (server
        -- fallback path widened in phase 5).
        -- CLASS COMES FROM wCurOpponent, NOT wTrainerClass. pokered stores the
        -- class into wTrainerClass only AFTER subtracting OPP_ID_OFFSET:
        --     ld a, [wEnemyMonSpecies2] / sub OPP_ID_OFFSET
        --     jp c, InitWildBattle      / ld [wTrainerClass], a
        -- (engine/battle/core.asm:6673-6677; identical in pokeyellow
        -- engine/battle/init_battle.asm:33-36), so that byte holds the RAW const
        -- $00-$2F. TRAINERS.CLASS_NAMES is keyed 200-247, so every lookup missed
        -- and resolve() returned ("","") for every trainer in the game — no
        -- opponent name or class ever reached the server.
        -- wCurOpponent keeps the +200 form (home/trainers.asm:233-237 stores
        -- wEngagedTrainerClass and compares it against OPP_ID_OFFSET to decide
        -- trainer-vs-wild), which is why rival_trainer_ids() already worked.
        -- wTrainerNo stays as-is: it is the 1-based index WITHIN the class.
        if not battle_is_wild and M.CUR_OPPONENT_ADDR then
            local class_id = M.read_u8(M.CUR_OPPONENT_ADDR)
            local trainer_id = M.read_u8(M.TRAINER_ID_ADDR)
            evt.trainer_class_id = class_id
            evt.trainer_id = trainer_id
            local class_name, trainer_name = TRAINERS.resolve(class_id, trainer_id)
            if class_name ~= "" then evt.opponent_class = class_name end
            if trainer_name ~= "" then evt.opponent_name = trainer_name end
        end
    end
    local ok_b, boxes = pcall(build_box_snapshot)
    if ok_b and boxes then evt.pc_boxes = boxes end
    send(evt, "tick", true)
end

-- ── Tick counter ──────────────────────────────────────────────────────────────

-- Party tracking
local all_known_keys = {}  -- set of all monKeys ever seen

--- Seed all_known_keys from the live box AND all twelve stored ones.
-- The stored copy of the open box is stale (the live one is WRAM), so both are read.
local function seed_all_boxes()
    local box_count = M.getBoxCount()
    for i = 0, math.min(box_count, M.BOX_MAX_MONS) - 1 do
        local bmon = M.readBoxSlot(i)
        if bmon then all_known_keys[bmon.key] = true end
    end
    local stored = M.storedBoxKeys and M.storedBoxKeys()
    if stored then
        for k in pairs(stored) do all_known_keys[k] = true end
    end
end
local prev_party     = {}  -- slot → {key, hp, maxHP, level, species_index}

-- Tick timing
local TICK_INTERVAL = 30
local tick_counter  = 0

-- Whiteout detection
local whiteout_sent = false

-- Party transition debounce (3-frame safeguard against memory read glitches)
local deposit_debounce  = {}   -- key -> frame_count (consecutive absent frames)
local withdraw_debounce = {}   -- key -> frame_count (consecutive present frames)
local DEBOUNCE_FRAMES   = 3

-- ── Capture detection ─────────────────────────────────────────────────────────
local function on_new_mon(mon, slot, is_gift)
    all_known_keys[mon.key] = true
    local natdex = G.toNatDex(mon.species_index)
    local nickname = M.readPartyNickname(slot)
    if nickname ~= "" then nick_cache[mon.key] = nickname end

    -- A SCRIPTED encounter is caught in its OWN area, not the route's. The pair must be
    -- consistent on both halves of the rule: if failing to catch Snorlax resolves
    -- static_71_143 rather than route_12, then catching it has to link static_71_143 too --
    -- otherwise catching it would consume Route 12's encounter, which is the very thing
    -- this exists to prevent, just in the other direction.
    local area = battle_static_area or last_area_id
    if is_gift and area == "" then
        -- PER-MAP, NOT A SHARED CONSTANT. This used to fall back to the literal
        -- "gift", so every scripted grant on a map that area_map.json did not
        -- cover landed in ONE area and paired with unrelated events — the
        -- Magikarp salesman and the Celadon Eevee formed a link with each other.
        -- Both of those maps are mapped now, but the fallback itself was the bug:
        -- any future unmapped grant map would collapse the same way. Keying on the
        -- map id keeps distinct events distinct without needing a table entry,
        -- while two grants on the SAME map (the Dojo pair, the fossils) still
        -- share an id, which is correct — those are one logical event where each
        -- player picks one.
        local mid = M.getCurrentMap and M.getCurrentMap()
        area = mid and string.format("gift_map_%d", mid) or "gift"
    end

    local evt = {
        event = "capture",
        key = mon.key,
        area_id = area,
        species_id = natdex,
        level = mon.level,
        hp = mon.hp,
        maxHP = mon.maxHP,
        nickname = nickname,
    }
    if is_gift then evt.gift = true end

    send(evt, "capture(" .. (is_gift and "gift" or "battle") .. "):" .. mon.key:sub(1, 9), true)
    captured_this_battle = true
    -- DO NOT self-terminate the battle state here. The removed lines set
    -- `in_battle = false` / `battle_is_wild = false` on the theory that wIsInBattle
    -- "can linger at 0xFF after a successful catch". It does not: ItemUseBall never
    -- touches wIsInBattle (pokered engine/items/item_effects.asm), the flag is cleared
    -- in engine/battle/end_of_battle.asm:50 after the whole caught-it sequence, and
    -- 0xFF is written only by the blackout path (home/overworld.asm:355-356).
    --
    -- Clearing it early did two things, both measured in a live duo run:
    --   * the next frame saw cur_in_battle=1 with in_battle=false and re-fired
    --     "Battle START", which resets captured_this_battle and replays the NEW ENC
    --     banner -- and then emitted a bogus no_catch for an area we had just caught in;
    --   * isInOverworld() started returning true WHILE THE BATTLE WAS STILL UP, so the
    --     deferred queue ran mid-battle. In a dead zone that executed the memorialize
    --     immediately, writing box SRAM during a battle and removing the mon before the
    --     battle had ended.
    -- The real battle end is detected from wIsInBattle by step 5 as it always was.
    -- Phase 7: optional SFX play. No-op until profile.SFX_DISPATCH_ADDR is set.
    M.playSfx(is_gift and "gift" or "capture")
end

-- ── Box capture detection (full-party catch) ──────────────────────────────────
local function scan_current_box()
    local box_count = M.getBoxCount()
    for i = 0, math.min(box_count, M.BOX_MAX_MONS) - 1 do
        local bmon = M.readBoxSlot(i)
        if bmon and not all_known_keys[bmon.key] then
            all_known_keys[bmon.key] = true
            local natdex = G.toNatDex(bmon.species_index)
            local nickname = M.readBoxNickname(i)
            if nickname ~= "" then nick_cache[bmon.key] = nickname end

            -- in_box, because this mon is IN THE BOX. scan_current_box only ever runs on
            -- the box, so every capture it reports is a full-party catch that GivePokemon
            -- delivered straight to storage. Without the flag state.py accounted it as an
            -- in-party capture -- wrong party_size, and it could queue a box_mon quarantine
            -- for a mon that was already boxed. Gen 3 has always sent it.
            send({
                event = "capture",
                key = bmon.key,
                area_id = last_area_id,
                species_id = natdex,
                nickname = nickname,
                in_box = true,
            }, "capture(box):" .. bmon.key:sub(1, 9), true)
            captured_this_battle = true
        end
    end
end

-- ── Faint detection ───────────────────────────────────────────────────────────
local function on_faint(mon)
    if not nuzlocke_active then return end
    send({
        event = "faint",
        key = mon.key,
        area_id = last_area_id,
    }, "faint:" .. mon.key:sub(1, 9), true)
    M.playSfx("faint")  -- Phase 7: no-op until profile.SFX_DISPATCH_ADDR set
end

-- ── In-game trade ─────────────────────────────────────────────────────────────
--- The NPC took one of our mons and gave us another; the Soul Link pair MIGRATES.
---
--- A vanilla in-game trade removes a mon from the party and puts a different one in the
--- same slot. If the outgoing mon was half of a link, the link has to follow the player --
--- not be orphaned while the incoming mon is treated as a fresh wild catch. Read as a
--- capture it would also consume the current route's encounter, for a mon the route never
--- offered.
---
--- The server already migrates everything on a `key_change` -- the link, the key index,
--- pending captures, party keys, the stats cache, bonus keys, pending memorials -- so all
--- that was missing was noticing the trade at all.
local function on_npc_trade(old_key, new_key, new_species_index, slot)
    local natdex = G.toNatDex(new_species_index)
    local nickname = M.readPartyNickname(slot)
    all_known_keys[old_key] = nil
    all_known_keys[new_key] = true
    if nick_cache[old_key] then nick_cache[old_key] = nil end
    if nickname ~= "" then nick_cache[new_key] = nickname end
    send({
        event = "key_change",
        old_key = old_key,
        new_key = new_key,
        new_species = natdex,
        new_nickname = nickname,
        reason = "npc_trade",
    }, "npc_trade:" .. old_key:sub(1, 9) .. "→" .. new_key:sub(1, 9), true)
    console.log(fmt("[SLink-RBY] in-game trade: %s -> %s (link migrates)",
                    old_key, new_key))
end

-- ── Evolution detection ───────────────────────────────────────────────────────
local function on_evolution(old_key, new_key, new_species_index, slot)
    local natdex = G.toNatDex(new_species_index)
    local nickname = M.readPartyNickname(slot)
    -- Update tracking
    all_known_keys[old_key] = nil
    all_known_keys[new_key] = true
    if nick_cache[old_key] then
        nick_cache[new_key] = nick_cache[old_key]
        nick_cache[old_key] = nil
    end
    -- Send key_change event
    send({
        event = "key_change",
        old_key = old_key,
        new_key = new_key,
        new_species = natdex,
        new_nickname = nickname,
    }, "key_change:" .. old_key:sub(1, 9) .. "→" .. new_key:sub(1, 9), true)
end

-- ── Whiteout detection ────────────────────────────────────────────────────────
local function check_whiteout(cur_party, count)
    if not nuzlocke_active then return end
    if count == 0 then return end
    if whiteout_sent then return end

    for slot = 0, count - 1 do
        local mon = cur_party[slot]
        if mon and mon.hp > 0 then return end
    end
    -- All mons fainted
    whiteout_sent = true
    send({event = "whiteout", area_id = last_area_id}, "whiteout", true)
    M.playSfx("whiteout")  -- Phase 7: no-op until profile.SFX_DISPATCH_ADDR set
end

-- ── Party diff (core detection logic) ─────────────────────────────────────────
local function diff_party()
    local count = M.getPartyCount()
    if count > 6 then return end  -- Invalid data, skip

    local cur_party = {}
    local cur_keys = {}

    for slot = 0, count - 1 do
        local mon = M.readPartySlot(slot)
        if mon and mon.species_index ~= 0 then
            cur_party[slot] = mon
            cur_keys[mon.key] = slot
        end
    end

    -- ── Slot occupant changed: evolution, or an in-game trade
    -- Key format is DDDD:TTTT:II -- DVs, OT id, species index. Evolution keeps DVs and OT
    -- and changes only the species, so the first nine characters are invariant. A trade
    -- changes all three, because the mon is a different mon with a different original
    -- trainer -- which is also how it is told apart from anything SLink itself wrote into
    -- the slot (those keep our own OT id).
    local my_ot = fmt("%04X", M.readPlayerId())
    for slot, cur in pairs(cur_party) do
        local prev = prev_party[slot]
        if prev and prev.key ~= cur.key and not all_known_keys[cur.key] then
            local prev_inv = prev.key:sub(1, 9)
            local cur_inv  = cur.key:sub(1, 9)
            if prev_inv == cur_inv then
                on_evolution(prev.key, cur.key, cur.species_index, slot)
            elseif cur.key:sub(6, 9) ~= my_ot and not sync_written_keys[cur.key] then
                -- Someone else's mon appeared where ours was standing, and the server did
                -- not put it there. That is an in-game trade.
                on_npc_trade(prev.key, cur.key, cur.species_index, slot)
            end
        end
    end

    -- ── New mon detection (captures)
    for slot, mon in pairs(cur_party) do
        if not all_known_keys[mon.key] and mon.maxHP > 0 then
            local is_gift = not in_battle
            on_new_mon(mon, slot, is_gift)
        end
    end

    -- ── Box scan for full-party captures (grace window after battle)
    if not in_battle and post_battle_frames > 0 and not captured_this_battle then
        scan_current_box()
    end

    -- ── Faint detection: HP drops from > 0 to 0
    if nuzlocke_active then
        for slot, cur in pairs(cur_party) do
            local prev = prev_party[slot]
            if prev and prev.key == cur.key and prev.hp > 0 and cur.hp == 0 then
                on_faint(cur)
            end
        end
        -- Cross-slot faint: mon moved slots but HP dropped
        for key, _ in pairs(all_known_keys) do
            if cur_keys[key] then
                local cur_slot = cur_keys[key]
                local cur = cur_party[cur_slot]
                if cur and cur.hp == 0 then
                    -- Was this mon alive in prev_party?
                    local was_alive = false
                    for _, prev in pairs(prev_party) do
                        if prev.key == key and prev.hp > 0 then
                            was_alive = true
                            break
                        end
                    end
                    -- Only fire if not already fired via same-slot detection
                    if was_alive then
                        local same_slot_prev = prev_party[cur_slot]
                        if not same_slot_prev or same_slot_prev.key ~= key then
                            on_faint(cur)
                        end
                    end
                end
            end
        end
    end

    -- ── party_to_box: key disappeared from party outside battle (debounced)
    if not in_battle and post_battle_frames == 0 then
        for key, _ in pairs(all_known_keys) do
            if not cur_keys[key] then
                -- Skip if we just wrote this key via sync command
                if sync_written_keys[key] then
                    sync_written_keys[key] = nil
                    deposit_debounce[key] = nil
                else
                    -- Was it in prev_party?
                    local was_in_party = false
                    for _, prev in pairs(prev_party) do
                        if prev.key == key then was_in_party = true; break end
                    end
                    -- `or deposit_debounce[key]`: prev_party is overwritten with the
                    -- CURRENT party at the end of every diff_party, so the key is only
                    -- "in prev_party" on the single frame it vanishes. Without the second
                    -- clause the counter reaches 1 and stops, DEBOUNCE_FRAMES is 3, and
                    -- party_to_box can never fire — party/box sync was dead in both Gen 1
                    -- and Gen 2. Once debouncing has started, keep counting.
                    if was_in_party or deposit_debounce[key] then
                        deposit_debounce[key] = (deposit_debounce[key] or 0) + 1
                        if deposit_debounce[key] >= DEBOUNCE_FRAMES then
                            -- Verify it's actually in the box
                            local in_box = false
                            local box_count = M.getBoxCount()
                            for i = 0, math.min(box_count, M.BOX_MAX_MONS) - 1 do
                                local bmon = M.readBoxSlot(i)
                                if bmon and bmon.key == key then
                                    in_box = true
                                    break
                                end
                            end
                            if in_box then
                                send({event = "party_to_box", key = key},
                                     "party_to_box:" .. key:sub(1, 9), true)
                            end
                            deposit_debounce[key] = nil
                        end
                    end
                end
            else
                -- Key reappeared in party — reset debounce
                deposit_debounce[key] = nil
            end
        end
    end

    -- ── box_to_party: key appeared that was previously known (debounced)
    for slot, mon in pairs(cur_party) do
        if all_known_keys[mon.key] then
            -- Skip if we just wrote this key via sync command
            if sync_written_keys[mon.key] then
                sync_written_keys[mon.key] = nil
                withdraw_debounce[mon.key] = nil
            else
                local was_in_prev = false
                for _, prev in pairs(prev_party) do
                    if prev.key == mon.key then was_in_prev = true; break end
                end
                if not was_in_prev then
                    -- Not an evolution, not a new capture — it came from the box
                    local is_evo = false
                    for _, prev in pairs(prev_party) do
                        if prev.key:sub(1, 9) == mon.key:sub(1, 9) and prev.key ~= mon.key then
                            is_evo = true; break
                        end
                    end
                    if not is_evo and not in_battle then
                        withdraw_debounce[mon.key] = (withdraw_debounce[mon.key] or 0) + 1
                        if withdraw_debounce[mon.key] >= DEBOUNCE_FRAMES then
                            send({event = "box_to_party", key = mon.key},
                                 "box_to_party:" .. mon.key:sub(1, 9), true)
                            withdraw_debounce[mon.key] = nil
                        end
                    end
                end
            end
        end
    end
    -- Clear withdraw debounce for keys that disappeared from party again
    for key, _ in pairs(withdraw_debounce) do
        if not cur_keys[key] then
            withdraw_debounce[key] = nil
        end
    end

    -- ── no_catch detection (on grace period expiry)
    if post_battle_frames == 1 and not captured_this_battle and battle_is_wild then
        -- A scripted battle resolves ITS OWN area, never the route's -- otherwise failing
        -- to catch Snorlax dead-zoned Route 12 and spent the route's only encounter on a
        -- mon the route does not offer.
        local battle_area_id = battle_static_area or battle_area_id
        if nuzlocke_active and battle_area_id ~= "" and not resolved_areas[battle_area_id]
                -- A battle the engine would not let us catch is not a failed encounter.
                -- Without this, every pre-Silph-Scope ghost in Pokemon Tower -- and there
                -- is no way through the Tower without meeting one -- dead-zoned the whole
                -- area for both players.
                and not battle_uncatchable then
            if not G.is_gift_area(battle_area_id) then
                send({event = "no_catch", area_id = battle_area_id,
                      species_id = battle_wild_species, level = battle_wild_level},
                     "no_catch:" .. battle_area_id, true)
                resolved_areas[battle_area_id] = true
            end
        end
    end

    -- ── Whiteout check
    check_whiteout(cur_party, count)

    prev_party = cur_party
end

-- ── F-key manual overrides ────────────────────────────────────────────────────
local function check_fkeys()
    -- F1: area_enter
    if joypad then
        -- BizHawk doesn't expose F-keys through joypad; use input.get() instead
    end
    local keys = input and input.get() or {}

    if keys["F1"] then
        local area = G.resolve_area(M.getCurrentMap())
        if area ~= "" then
            send({event = "area_enter", area_id = area}, "area_enter:" .. area, false)
        end
    end
    if keys["F2"] then
        local mon = M.readPartySlot(0)
        if mon then
            local nick = M.readPartyNickname(0)
            send({
                -- species_id, not species: server.py reads msg["species_id"], so the old
                -- key logged "Caught ? Lv12", stored species 0 and evaluated every clause
                -- against species 0.
                event = "capture", key = mon.key, area_id = last_area_id,
                species_id = G.toNatDex(mon.species_index), level = mon.level,
                hp = mon.hp, maxHP = mon.maxHP, nickname = nick,
            }, "capture(manual):" .. mon.key:sub(1, 9), false)
        end
    end
    if keys["F3"] then
        local mon = M.readPartySlot(0)
        if mon then
            send({event = "faint", key = mon.key, area_id = last_area_id},
                 "faint(manual):" .. mon.key:sub(1, 9), false)
        end
    end
    if keys["F4"] then
        if last_area_id ~= "" then
            send({event = "no_catch", area_id = last_area_id,
                  species_id = battle_wild_species, level = battle_wild_level},
                 "no_catch(manual):" .. last_area_id, false)
        end
    end
    if keys["F5"] then
        send({event = "whiteout", area_id = last_area_id}, "whiteout(manual)", false)
    end
    if keys["F6"] then
        send_tick()
    end
end

-- Track F-key press/release to avoid repeat fires
local prev_fkeys = {}
local function check_fkeys_debounced()
    local keys = input and input.get() or {}
    local fkey_names = {"F1", "F2", "F3", "F4", "F5", "F6"}
    local any_pressed = false
    for _, fk in ipairs(fkey_names) do
        if keys[fk] and not prev_fkeys[fk] then
            any_pressed = true
            break
        end
    end
    if any_pressed then check_fkeys() end
    for _, fk in ipairs(fkey_names) do
        prev_fkeys[fk] = keys[fk]
    end
end

-- ── Main frame handler ────────────────────────────────────────────────────────
--- Paint the native panel when the ROM patch asks for it.
---
--- The handshake is the patch's: it blanks the screen, draws its own fallback, sets AWAIT,
--- and waits. Painting only in that window is what makes a torn page impossible -- the
--- display is white for all of it. Doing nothing here is a valid outcome: the patch times
--- out and the player sees "NO CLIENT", which is the truth.
local panel_supported = nil   -- resolved from the capability bits; cleared by redetect

--- Re-read the companion patch and forget anything cached about it.
---
--- detectCompanionPatch ran ONCE at load while validateROM retried every frame, so the
--- two disagreed the moment anything changed underneath: reset the console, or load a
--- different ROM in the same BizHawk session, and the client kept the capabilities of a
--- cartridge that is no longer in the slot. It clears M.SFX_DISPATCH_ADDR itself; the
--- panel flag is ours, so it is cleared here.
local function redetect_patch()
    panel_supported = nil
    return M.detectCompanionPatch()
end

local function service_panel()
    -- ASK WHETHER THIS CARTRIDGE HAS A PANEL AT ALL, not just whether the byte says AWAIT.
    -- On an unpatched ROM $DEEB is ordinary unallocated WRAM; if it ever happened to read 1
    -- this would paint 360 tiles over whatever the player was looking at.
    if panel_supported == nil then
        panel_supported = (M.panelSupported and M.panelSupported()) or false
    end
    if not panel_supported then return end
    if not M.panelIsAwaitingStage or not M.panelIsAwaitingStage() then return end
    if not panel_rows or #panel_rows == 0 then return end
    M.panelStage(panel_rows)
end

local function on_frame()
    frame_count = frame_count + 1
    service_panel()

    -- Re-validate writes if previously disabled (save may load after script start)
    if not writes_enabled then
        local ok, _ = M.validateROM()
        if ok then
            writes_enabled = true
            -- A game that has just become valid may be a DIFFERENT cartridge from the one
            -- detected at load, so the patch is re-read rather than assumed.
            patch_abi = redetect_patch()
            console.log(fmt("[SLink-RBY] ✓ ROM validation passed — writes enabled, patch=%s",
                            patch_abi and ("ABI " .. patch_abi) or "none"))
        end
    elseif frame_count % 60 == 0 then
        -- ...and revoke it if the game goes away underneath us. See the declaration above.
        local ok, reason = M.validateROM()
        if not ok then
            validate_fail_count = validate_fail_count + 1
            if validate_fail_count >= VALIDATE_FAIL_THRESHOLD then
                console.log(fmt("[SLink-RBY] validateROM FAILED x%d: %s — writes disabled",
                                validate_fail_count, tostring(reason)))
                writes_enabled, initialized = false, false
                in_battle, prev_in_battle, nuzlocke_active = false, false, false
                captured_this_battle = false
                -- The cartridge is gone; so are its capabilities. Holding a stale
                -- SFX/panel address across a ROM swap is how a client ends up painting
                -- into a layout that is no longer there.
                panel_supported, patch_abi = nil, nil
                M.SFX_DISPATCH_ADDR = nil
                validate_fail_count = 0
                -- Deferred writes were queued against a save that is no longer loaded.
                pending_sync_cmds = {}
            end
            return
        end
        validate_fail_count = 0
    end

    -- 1. Drive TCP pump
    C.pump()

    -- 2. Connection state change → send hello on (re)connect
    local now_connected = C.connected()
    if now_connected ~= was_connected then
        if now_connected then
            console.log("[SLink-RBY] [TCP] connected to " .. SERVER_HOST .. ":" .. SERVER_PORT)
            -- Check nuzlocke gate on connect
            if M.hasPokeballs() then
                nuzlocke_active = true
            end
            -- Seed all_known_keys from current party
            local count = M.getPartyCount()
            if count <= 6 then
                for slot = 0, count - 1 do
                    local mon = M.readPartySlot(slot)
                    if mon then all_known_keys[mon.key] = true end
                end
            end
            -- Re-read the companion patch on every (re)connect: the server records the
            -- capability from this hello, so a downgrade -- the player reloading an
            -- unpatched ROM mid-run -- has to be visible here or the server keeps sending
            -- panel payloads to a cartridge with no mailbox.
            patch_abi = redetect_patch()
            -- Seed all_known_keys from EVERY box, not just the open one.
            -- Seeding the active box alone made the keyset depend on which box the player
            -- happened to have selected: switch to a box filled in an earlier session and
            -- the next lost battle emitted a `capture` for every mon in it, stamped with
            -- the current route. See M.storedBoxKeys.
            seed_all_boxes()
            -- Read current area
            local cur_map = M.getCurrentMap()
            last_map_id = cur_map
            last_area_id = G.resolve_area(cur_map)
            -- Send hello
            send_hello()
            initialized = true
        else
            console.log("[SLink-RBY] [TCP] disconnected — reconnecting…")
        end
        was_connected = now_connected
    end

    -- 3. Dispatch received responses
    while true do
        local line = C.receive()
        if not line then break end
        local label = table.remove(pending_labels, 1) or "?"
        local cmds = parse_command_list(line)
        local resp_cmd = #cmds > 0 and cmds[1].cmd or "noop"
        if not (label:find("tick") and resp_cmd == "noop") then
            console.log("[SLink-RBY] [←] " .. label .. " → " .. resp_cmd)
        end
        dispatch_commands(cmds)
    end

    if not initialized then return end

    -- 4. Read current game state
    local cur_map = M.getCurrentMap()
    local cur_area_id = G.resolve_area(cur_map)
    local cur_in_battle = M.isInBattle()

    -- 5. Battle transition detection
    if cur_in_battle and not in_battle then
        -- Battle started
        battle_area_id = cur_area_id ~= "" and cur_area_id or last_area_id
        battle_is_wild = M.isWildBattle()
        -- Remember WHAT got away, for no_catch. The event carried only an area id, so the
        -- dashboard could say a route was dead-zoned but never which encounter did it --
        -- and a Safari-Zone assertion has nothing to assert on. Read at battle START
        -- because by the time the grace period expires the battle struct is gone.
        battle_wild_species, battle_wild_level = nil, nil
        -- Is this a battle the ENGINE refuses to let us catch? Read once at battle start,
        -- because both inputs (the map and the bag) can change before it ends. See
        -- G.is_uncatchable_battle -- it is IsGhostBattle, transcribed.
        battle_uncatchable = battle_is_wild and G.is_uncatchable_battle
            and G.is_uncatchable_battle(cur_map, M.hasBagItem(G.ITEM_SILPH_SCOPE)) or false
        -- A SCRIPTED encounter belongs to itself, not to the route it stands on. Read at
        -- battle START because wCurOpponent is zeroed the moment the battle ends.
        battle_static_area = nil
        if battle_is_wild and G.is_static_battle and M.CUR_OPPONENT_ADDR then
            local opp = M.read_u8(M.CUR_OPPONENT_ADDR)
            if G.is_static_battle(opp) then
                battle_static_area = G.static_area_id(cur_map, G.toNatDex(opp))
            end
        end
        captured_this_battle = false
        whiteout_sent = false
        console.log(fmt("[SLink-RBY] Battle START (%s) area=%s",
            battle_is_wild and "wild" or "trainer", battle_area_id))
        -- NEW ENCOUNTER banner: wild battle in an unresolved, non-gift area.
        -- Shortened text for GBC's 160×144 screen (~22-char HUD bar limit).
        if battle_is_wild and nuzlocke_active and battle_area_id ~= ""
                and not resolved_areas[battle_area_id]
                and not battle_uncatchable
                and not G.is_gift_area(battle_area_id) then
            local short = battle_area_id:gsub("route_", "R"):gsub("_", " ")
                                        :gsub("(%a)([%w]*)", function(a, b) return a:upper() .. b end)
            short = string.sub(short, 1, 8)
            hud_show("** NEW ENC ** " .. short, 255, 220, 60, 360)
        end
    elseif cur_in_battle and battle_is_wild and not battle_wild_species then
        -- Remember WHAT got away, for no_catch. The event carried only an area id, so the
        -- server's species-clause reroll (state.py reads msg["species_id"]) could never
        -- fire on Gen 1, and the dashboard could say a route was dead-zoned without ever
        -- saying by what. Read on the first frame the battle struct is actually populated
        -- rather than on the transition frame, where it may not be yet -- and read it
        -- during the battle, because by the time the grace period expires it is gone.
        local foe = M.readActiveBattleMon and M.readActiveBattleMon()
        if foe then
            battle_wild_species = G.toNatDex(foe.species_index)
            battle_wild_level = foe.level
        end
    elseif not cur_in_battle and in_battle then
        -- Battle ended
        post_battle_frames = POST_BATTLE_GRACE
        pending_safe = true
        trainer_battle_sent = false
        trainer_stable_frames = 0
        console.log(fmt("[SLink-RBY] Battle END captured=%s", tostring(captured_this_battle)))
    end
    prev_in_battle = in_battle
    in_battle = cur_in_battle

    -- 6. Post-battle grace countdown
    if post_battle_frames > 0 then
        post_battle_frames = post_battle_frames - 1
    end

    -- 7. Area change detection (only outside battle)
    if not in_battle and cur_area_id ~= "" and cur_area_id ~= last_area_id then
        last_area_id = cur_area_id
        last_map_id = cur_map
        send({event = "area_enter", area_id = cur_area_id},
             "area_enter:" .. cur_area_id, true)
        -- HUD: notify new encounter area
        if nuzlocke_active and not G.is_gift_area(cur_area_id) then
            if resolved_areas_seeded and not resolved_areas[cur_area_id] then
                local disp = cur_area_id:gsub("_", " "):gsub("(%a)([%w]*)", function(a, b) return a:upper() .. b end)
                hud_show(">> " .. disp, 80, 255, 120, 180)
            end
        end
    elseif not in_battle and cur_map ~= last_map_id then
        -- Map changed but no encounter area (town/building)
        last_map_id = cur_map
        if cur_area_id ~= last_area_id then
            last_area_id = cur_area_id
        end
    end

    -- 8. Pokéball gate
    if not nuzlocke_active and M.hasPokeballs() then
        nuzlocke_active = true
        console.log("[SLink-RBY] nuzlocke ACTIVE (Pokéballs obtained)")
        HUD.nuzlocke_start("Nuzlocke Start!")
        if M.playSE then M.playSE(M.SE_NUZLOCKE_START) end
    end

    -- 9. Party diff (capture, faint, evolution, sync detection)
    diff_party()

    -- 9b. Execute pending sync commands (box_mon / party_mon / memorialize) when safe.
    -- `not in_battle` alone was too permissive: it is also true in the PC box UI, the party
    -- menu and the naming screen, where the open UI writes its own copy back over ours.
    -- PEEK rather than pop — the command is only dropped once it has actually been handled,
    -- so a mid-write error retries next frame instead of losing the deposit. See keep_queued
    -- below for which paths requeue and their bounds.
    -- Defer every box operation while the MEMORIAL box is the active one. Two distinct
    -- hazards: a normal box_mon would deposit a live mon into the graveyard, and
    -- memorialize writes Box 12's SRAM directly while the game holds a WRAM copy of the
    -- active box that it would write back over us. Staying queued means the command simply
    -- runs once the player switches boxes.
    local active_box = M.getCurrentBoxNum and M.getCurrentBoxNum()
    local box_safe = (active_box == nil) or (active_box ~= MEMORIAL_BOX_INDEX)

    -- AND ONLY WHILE WE CAN STILL ANSWER. `send` drops silently when the socket is down,
    -- so running the executor mid-disconnect meant a command could fail, consume its
    -- NACK into the void, and be removed from the queue -- the log-and-drop shape these
    -- NACKs exist to avoid, narrowed to the reconnect window. The commands are already
    -- queued; they simply wait.
    if writes_enabled and box_safe and C.connected() and M.isInOverworld() and #pending_sync_cmds > 0 then
        local cmd = pending_sync_cmds[1]
        local handled = true
        local ok, err

        -- Bounded requeue. `handled` starts true and the peek-before-remove above is only
        -- meaningful if some path clears it — for a long time none did, so the "retries next
        -- frame" the comment promised did not exist and every failure was dropped silently.
        -- That matters most where the branch reports NOTHING to the server: the server keeps
        -- believing the command is in flight, and the pair desyncs permanently.
        -- Returns true while the command should stay queued.
        local function keep_queued(limit)
            local n = (cmd._retries or 0) + 1
            cmd._retries = n
            if n <= limit then
                handled = false
                return true
            end
            return false
        end
        -- FAULT CONTAINMENT. Everything below writes real party/box/SRAM memory, and a
        -- raise here does not merely lose one command: it escapes on_frame, so the
        -- `table.remove` at the bottom never runs, the same command re-raises on the very
        -- next frame, and every step after this one — trainer_battle_start, the `safe`
        -- event, send_tick, the F-keys, the HUD — stops for the rest of the session.
        -- on_frame_safe's pcall keeps the process alive, which is exactly what makes the
        -- failure silent: the client stays connected and simply goes quiet.
        --
        -- Gen 2 already wraps the identical block (gen2_crystal_client.lua:1270) but only
        -- logs and drops. We NACK first, because a dropped command the server still
        -- believes is in flight desyncs the pair permanently — the hazard this file's own
        -- comment names a few lines above.
        --
        -- The body is left at its original indentation on purpose: re-indenting ~185 lines
        -- would bury the actual change in an unreviewable diff.
        local exec_ok, exec_err = pcall(function()
        if cmd.cmd == "box_mon" then
            local count = M.getPartyCount()
            local found_slot = nil
            for s = 0, count - 1 do
                local mon = M.readPartySlot(s)
                if mon and mon.key == cmd.key then
                    found_slot = s
                    break
                end
            end
            if not found_slot then
                -- Already boxed or not found — that's fine
                console.log("[SLink-RBY]   ↳ box_mon: " .. cmd.key:sub(1, 8) .. " not in party (OK)")
                sync_written_keys[cmd.key] = true
            elseif count <= 1 then
                -- The party can gain a mon later, so stay queued instead of dropping a
                -- deposit the server still thinks is in flight. Bounded so it cannot spin
                -- forever if the player never catches anything again.
                if keep_queued(600) then
                    if cmd._retries == 1 then
                        console.log("[SLink-RBY]   ↳ box_mon deferred: last mon in party")
                        hud_show("! Only mon!", 255, 200, 60, 240)
                    end
                else
                    console.log("[SLink-RBY]   ↳ box_mon DROPPED: still the last mon after "
                                .. "600 safe frames")
                    hud_show("X Deposit failed!", 255, 80, 80, 240)
                    -- NACK. The server discarded this key from party_keys and decremented
                    -- party_size when it queued the command; without this it believes the
                    -- deposit landed and its party model is permanently wrong.
                    send({event = "box_mon_failed", key = cmd.key, reason = "last_mon"},
                         "box_mon_failed:" .. cmd.key:sub(1, 8), true)
                end
            else
                -- Read the party-only stats BEFORE depositing — the box struct drops
                -- level/maxHP/Atk/Def/Spd/Spc, so the server has to hold them for us until
                -- this mon is withdrawn again (possibly in a later session).
                local pre_stats = M.readPartyStats(found_slot)
                ok, err = M.depositPartyMon(found_slot)
                if ok then
                    sync_written_keys[cmd.key] = true
                    if pre_stats then
                        send({event = "stats_cache", key = cmd.key, stats = pre_stats},
                             "stats_cache:" .. cmd.key:sub(1, 8), true)
                    end
                    console.log("[SLink-RBY]   ↳ box_mon OK: " .. cmd.key:sub(1, 8))
                    hud_show("v " .. nick_label(cmd.key) .. " boxed", 100, 180, 255, 200)
                elseif keep_queued(3) then
                    console.log(fmt("[SLink-RBY]   ↳ box_mon retry %d/3: %s",
                                    cmd._retries, err or "?"))
                else
                    console.log("[SLink-RBY]   ↳ box_mon FAIL (giving up): " .. (err or "?"))
                    hud_show("X Deposit failed!", 255, 80, 80, 240)
                    send({event = "box_mon_failed", key = cmd.key, reason = err or "deposit failed"},
                         "box_mon_failed:" .. cmd.key:sub(1, 8), true)
                end
            end
        elseif cmd.cmd == "party_mon" then
            -- DO NOT WITHDRAW INTO A PARTY THAT IS ENTIRELY FAINTED.
            --
            -- That is the exact window in which the cartridge is deciding whether to black
            -- out, and handing it a living mon cancels the decision. Measured on the duo
            -- whiteout scenario: A's last mon died of poison, the client emitted `whiteout`,
            -- the server answered with the auto-rebuild's party_mon, the withdraw landed
            -- while the "fainted!" text box was between frames, AnyPartyAlive then returned
            -- nonzero and HandleBlackOut never ran. No blackout, no money loss, no warp.
            --
            -- The scenario had been PASSING on the bug this guard now covers: party_mon
            -- dropped its stats block, retrieveBoxMon refused, and the party stayed dead by
            -- accident. Fixing the drop is what exposed the race.
            --
            -- IT WAITS OUT THE RACE, THEN PROCEEDS — it never refuses. HandleBlackOut ends
            -- in HealParty, so a machine that IS blacking out revives within a few frames
            -- and the withdraw lands immediately after, in the order it was always meant to
            -- happen in. But the PARTNER machine reaches the same all-fainted state by
            -- force_faint, where nothing will ever resolve it: the cartridge never noticed
            -- the HP write, so no blackout runs. A guard that refused would strand exactly
            -- the mon the rebuild exists to restore — measured, as B failing this same
            -- scenario from the other side.
            --
            -- Its own counter, not keep_queued's: the retry budget below belongs to "party
            -- full", and sharing one would let a long blackout eat the other's attempts.
            local function party_all_fainted()
                local n = M.getPartyCount()
                if n < 1 or n > 6 then return false end
                for s = 0, n - 1 do
                    local m = M.readPartySlot(s)
                    if m and m.hp and m.hp > 0 then return false end
                end
                return true
            end
            local BLACKOUT_WAIT = 300      -- ~5s at 60fps; a blackout resolves in far less
            if party_all_fainted() and (cmd._blackout_waits or 0) < BLACKOUT_WAIT then
                cmd._blackout_waits = (cmd._blackout_waits or 0) + 1
                handled = false
                if cmd._blackout_waits == 1 then
                    console.log("[SLink-RBY]   ↳ party_mon deferred: whole party is fainted, "
                                .. "letting the blackout resolve first")
                end
                goto party_mon_done
            end
            local count = M.getPartyCount()
            -- Check if already in party
            local already = false
            for s = 0, count - 1 do
                local mon = M.readPartySlot(s)
                if mon and mon.key == cmd.key then
                    already = true
                    break
                end
            end
            if already then
                console.log("[SLink-RBY]   ↳ party_mon: " .. cmd.key:sub(1, 8) .. " already in party")
                sync_written_keys[cmd.key] = true
                send({event = "sync_retrieve_done", key = cmd.key},
                     "sync_retrieve_done:" .. cmd.key:sub(1, 8), true)
            elseif count >= 6 then
                local retries = cmd._retries or 0
                if retries < 3 then
                    cmd._retries = retries + 1
                    pending_sync_cmds[#pending_sync_cmds + 1] = cmd
                    console.log(fmt("[SLink-RBY]   ↳ party_mon re-queued (attempt %d/3)", retries + 1))
                else
                    console.log("[SLink-RBY]   ↳ party_mon DROPPED: party full after 3 retries")
                    hud_show("! Unbox " .. nick_label(cmd.key), 255, 200, 60, 600)
                    send({event = "sync_retrieve_failed", key = cmd.key},
                         "sync_retrieve_failed:" .. cmd.key:sub(1, 8), true)
                end
            else
                -- cmd.stats is the block cached at deposit time (server mon_stats); without
                -- it the mon returns with maxHP = its stored HP and zeroed stats.
                ok, err = M.retrieveBoxMon(cmd.key, cmd.stats)
                if ok then
                    sync_written_keys[cmd.key] = true
                    all_known_keys[cmd.key] = true
                    console.log("[SLink-RBY]   ↳ party_mon OK: " .. cmd.key:sub(1, 8))
                    hud_show("^ " .. nick_label(cmd.key) .. " unboxed", 100, 255, 160, 200)
                    send({event = "sync_retrieve_done", key = cmd.key},
                         "sync_retrieve_done:" .. cmd.key:sub(1, 8), true)
                else
                    console.log("[SLink-RBY]   ↳ party_mon FAIL: " .. (err or "?"))
                    hud_show("! Unbox " .. nick_label(cmd.key), 255, 200, 60, 600)
                    send({event = "sync_retrieve_failed", key = cmd.key},
                         "sync_retrieve_failed:" .. cmd.key:sub(1, 8), true)
                end
            end
            ::party_mon_done::
        elseif cmd.cmd == "memorialize" then
            -- Memorialize: deposit dead mon to current box (Gen 1 graveyard)
            local count = M.getPartyCount()
            local found_slot = nil
            for s = 0, count - 1 do
                local mon = M.readPartySlot(s)
                if mon and mon.key == cmd.key then
                    found_slot = s
                    break
                end
            end
            if not found_slot then
                -- Not in party — already deposited or gone. Treat as success.
                console.log("[SLink-RBY]   ↳ memorialize: " .. cmd.key:sub(1, 8) .. " not in party (OK)")
                send({event = "memorialize_done", key = cmd.key},
                     "memorialize_done:" .. cmd.key:sub(1, 8), true)
                sync_written_keys[cmd.key] = true
            elseif count <= 1 then
                -- Can't deposit last mon — report failure
                console.log("[SLink-RBY]   ↳ memorialize skipped: last mon in party")
                hud_show("! Only mon!", 255, 200, 60, 240)
                send({event = "memorialize_failed", key = cmd.key, reason = "last_mon"},
                     "memorialize_failed:" .. cmd.key:sub(1, 8), true)
            else
                -- Memorialize = deposit to dedicated memorial box (Gen 1: Box 12, CartRAM
                -- offset 0x75EA). depositMemorialMon falls back to depositPartyMon if the
                -- memorial box is full or unconfigured.
                ok, err = M.depositMemorialMon(found_slot)
                if ok then
                    sync_written_keys[cmd.key] = true
                    console.log("[SLink-RBY]   ↳ memorialize OK: " .. cmd.key:sub(1, 8))
                    hud_show("+ " .. nick_label(cmd.key) .. " buried", 255, 140, 40, 300)
                    send({event = "memorialize_done", key = cmd.key},
                         "memorialize_done:" .. cmd.key:sub(1, 8), true)
                elseif keep_queued(3) then
                    console.log(fmt("[SLink-RBY]   ↳ memorialize retry %d/3: %s",
                                    cmd._retries, err or "?"))
                else
                    console.log("[SLink-RBY]   ↳ memorialize FAIL (giving up): " .. (err or "?"))
                    hud_show("X Memorial failed!", 255, 80, 80, 300)
                    send({event = "memorialize_failed", key = cmd.key, reason = err or "unknown"},
                         "memorialize_failed:" .. cmd.key:sub(1, 8), true)
                end
            end
        end
        end)
        if not exec_ok then
            local why = tostring(exec_err)
            console.log("[SLink-RBY]   ↳ sync cmd ERROR (" .. tostring(cmd.cmd) .. "): " .. why)
            hud_show("X Sync op failed", 255, 100, 100, 300)
            -- Tell the server BEFORE dropping it. A raised error is not retryable — the
            -- next frame would raise identically — but silence is worse than failure:
            -- the server would keep the command in flight forever.
            if cmd.cmd == "party_mon" then
                send({event = "sync_retrieve_failed", key = cmd.key, reason = why},
                     "sync_retrieve_failed:" .. cmd.key:sub(1, 8), true)
            elseif cmd.cmd == "box_mon" then
                send({event = "box_mon_failed", key = cmd.key, reason = why},
                     "box_mon_failed:" .. cmd.key:sub(1, 8), true)
            elseif cmd.cmd == "memorialize" then
                send({event = "memorialize_failed", key = cmd.key, reason = why},
                     "memorialize_failed:" .. cmd.key:sub(1, 8), true)
            end
            sync_written_keys[cmd.key] = true
            handled = true
        end
        if handled then table.remove(pending_sync_cmds, 1) end
    end

    -- 9b-bis. Rival Team Swap: announce a TRAINER battle once its opponent id is stable.
    -- The server decides whether this id is a rival (adapter.rival_trainer_ids) and whether
    -- the run has the rule on, then answers with replace_rival_team.
    if in_battle and not trainer_battle_sent and not battle_is_wild then
        local tid = M.readTrainerOpponentId and M.readTrainerOpponentId()
        if tid and tid > 0 then
            if tid == trainer_last_id then
                trainer_stable_frames = trainer_stable_frames + 1
            else
                trainer_last_id = tid
                trainer_stable_frames = 1
            end
            if trainer_stable_frames >= TRAINER_STABLE_GATE then
                trainer_battle_sent = true
                send({event = "trainer_battle_start", trainer_id = tid},
                     "trainer_battle_start", true)
            end
        end
    end

    -- 9c. safe — the first genuinely-overworld frame after a battle ends. The server
    -- treats it as a tick that also means "deferred writes can run now", so it waits for
    -- isInOverworld rather than just "not in battle": the post-battle frames still have a
    -- text box up and a script holding the joypad.
    if pending_safe and M.isInOverworld() and post_battle_frames == 0 then
        pending_safe = false
        if C.connected() then
            local evt = {event = "safe", has_pokeballs = nuzlocke_active, area_id = last_area_id}
            local raw_count = M.getPartyCount()
            if raw_count >= 1 and raw_count <= 6 then evt.party = build_party_snapshot() end
            send(evt, "safe", true)
        end
    end

    -- 10. Tick event
    tick_counter = tick_counter + 1
    if tick_counter >= TICK_INTERVAL then
        tick_counter = 0
        if C.connected() then
            send_tick()
        end
    end

    -- 11. F-key overrides
    check_fkeys_debounced()

    -- 12. HUD render
    hud_render()
end

-- ── Initialize TCP connection ─────────────────────────────────────────────────
C.init(SERVER_HOST, SERVER_PORT)
console.log(fmt("[SLink-RBY] Started — player=%s target=%s:%d", PLAYER_ID, SERVER_HOST, SERVER_PORT))

-- ── Initialize prev_party ─────────────────────────────────────────────────────
local init_count = M.getPartyCount()
if init_count <= 6 then
    for slot = 0, init_count - 1 do
        local mon = M.readPartySlot(slot)
        if mon then
            prev_party[slot] = mon
            all_known_keys[mon.key] = true
        end
    end
end
-- ...and from the boxes. Startup seeded the PARTY only -- not even the open box -- so a
-- client started with mons already stored saw every one of them as a fresh capture the
-- first time anything triggered a box scan.
seed_all_boxes()

-- An unguarded read during a screen transition would otherwise take the whole
-- client down rather than dropping a single frame. Mirrors gen3's on_frame_safe.
local function on_frame_safe()
    local ok, err = pcall(on_frame)
    if not ok then console.log("[SLink-RBY] ERROR (handler kept alive): " .. tostring(err)) end
end

-- ── Main loop ─────────────────────────────────────────────────────────────────
-- A frame CALLBACK, not `while true do ... emu.frameadvance() end`.
--
-- Gen 3, 4 and 5 all register a callback; Gen 1 and 2 were the outliers. The blocking loop
-- never returns, so anything that dofile()s this client hangs forever — which is exactly
-- what the two-instance duo harness has to do (it loads the REAL production client and
-- drives a scenario coroutine alongside it). Behaviour per frame is unchanged.
event.onframeend(on_frame_safe, "slink_gen1")
console.log("[SLink-RBY] Running — play normally to trigger events…")
