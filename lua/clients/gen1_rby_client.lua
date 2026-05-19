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
  │  key_change     — evolution detected (species changes, DVs+OTID invariant)
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
local function parse_command_list(raw)
    local cmds = {}
    local arr = raw:match('"commands"%s*:%s*(%b[])')
    if not arr then return cmds end
    for obj in arr:gmatch('%b{}') do
        local cmd     = obj:match('"cmd"%s*:%s*"([^"]+)"')
        local key     = obj:match('"key"%s*:%s*"([^"]+)"')
        local text    = obj:match('"text"%s*:%s*"([^"]*)"')
        local r       = tonumber(obj:match('"r"%s*:%s*(%d+)'))
        local g       = tonumber(obj:match('"g"%s*:%s*(%d+)'))
        local b       = tonumber(obj:match('"b"%s*:%s*(%d+)'))
        local frames  = tonumber(obj:match('"frames"%s*:%s*(%d+)'))
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
                cmd = cmd, key = key, text = text,
                r = r, g = g, b = b, frames = frames,
                area_id = area_id, areas = areas,
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

console.log(fmt("[SLink-RBY] Detected: %s (variant=%s) writes=%s",
    G.display_name, variant, tostring(writes_enabled)))
if not val_ok then
    console.log(fmt("[SLink-RBY] ROM validation: %s (will retry each frame)", val_err))
end

-- ── HUD overlay ───────────────────────────────────────────────────────────────
-- GB screen: 160 × 144
HUD.init({screen_w = 160, screen_h = 144, hud_x = 2, hud_y = 134, hud_right = 158,
          prompt_y = 36, prompt_h = 10, gameover_y = 50, font_size = 8})
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

local function dispatch_commands(cmds)
    for _, c in ipairs(cmds) do
        if c.cmd == "force_faint" and c.key then
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
        elseif c.cmd == "hud_show" and c.text then
            hud_show(c.text, c.r or 255, c.g or 255, c.b or 255, c.frames or 300)
        elseif c.cmd == "gui_prompt" and c.text then
            prompt_show(c.text, c.r or 255, c.g or 255, c.b or 255, c.frames or 300)
            console.log("[SLink-RBY]   ↳ gui_prompt: " .. c.text)
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
            pending_sync_cmds[#pending_sync_cmds + 1] = {cmd = "party_mon", key = c.key}
            console.log("[SLink-RBY]   ↳ party_mon QUEUED: " .. c.key:sub(1, 8))
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
            HUD.set_game_over()
            console.log("[SLink-RBY]   ↳ GAME OVER — SOUL LINK")
        elseif c.cmd ~= "noop" then
            console.log("[SLink-RBY]   ↳ cmd: " .. tostring(c.cmd))
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
local battle_is_wild      = false
local battle_area_id      = ""
local captured_this_battle = false
local post_battle_frames  = 0
local POST_BATTLE_GRACE   = 15  -- frames to wait after battle before no_catch

-- Area tracking
local last_area_id = ""
local last_map_id  = -1

-- Nuzlocke gate
local nuzlocke_active = false

-- Sync command queue (box_mon / party_mon — deferred until safe)
local pending_sync_cmds = {}
local sync_written_keys = {}  -- keys recently written to avoid re-triggering events

-- ── Party snapshot builder ────────────────────────────────────────────────────
local function build_party_snapshot()
    local count = M.getPartyCount()
    local snap = {}
    -- Gen 1 doesn't track an "active party slot" pointer; the battle struct
    -- (wBattleMon) holds the active mon's live stats. For the status page's
    -- stat-stage badges, mark slot 0 as active when in battle (Gen 1 nuzlocke
    -- runs typically don't switch mid-battle; switching would shift the badges
    -- to the wrong slot until the user reports a fix is needed).
    local in_b = in_battle and M.isInBattle()
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
                species_id = G.toNatDex(mon.species_index),
                nickname = nick,
                status_cond = mon.status_cond or 0,
            }
            -- Phase 3: moves + PP from party struct. Server enriches into move_details.
            -- Gen 1 has no PP-Up encoding; pp_bonuses stays 0.
            local party_base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
            local mp = M.readMovesAndPP(party_base, nil)
            if mp then
                entry.moves = mp.moves
                entry.pp    = mp.pp
                entry.pp_bonuses = 0
            end
            if slot == 0 and player_stages then
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
    -- Phase 5: trainer class + name lookup for non-wild battles. The Lua-side
    -- lookup avoids needing a server-adapter call (Gen 1 trainer_id alone is
    -- ambiguous without the class context).
    local trainer_class_id, trainer_id_within_class = 0, 0
    if not battle_is_wild and M.TRAINER_CLASS_ADDR and M.TRAINER_ID_ADDR then
        trainer_class_id = M.read_u8(M.TRAINER_CLASS_ADDR)
        trainer_id_within_class = M.read_u8(M.TRAINER_ID_ADDR)
    end
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
            pp_bonuses = 0,
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
                        pp_bonuses = 0,
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
    -- Active box (in WRAM)
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
                        box          = 0,  -- active box (Gen 1 only knows active box index)
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
    local snap = build_party_snapshot()
    local cur_in_battle = M.isInBattle()

    local evt = {
        event = "hello",
        rom_type = rom_type,
        area_id = area_id,
        has_pokeballs = M.hasPokeballs(),
        ball_count = M.countPokeballs(),
        badges = M.readBadgeCount(),
        in_battle = cur_in_battle,
        is_trainer_battle = M.isTrainerBattle(),
        party = snap,
        trainer_name = M.readPlayerName(),
    }
    if cur_in_battle then
        local ep = build_enemy_snapshot()
        if #ep > 0 then evt.enemy_party = ep end
        if not battle_is_wild and M.TRAINER_CLASS_ADDR then
            local class_id = M.read_u8(M.TRAINER_CLASS_ADDR)
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
        badges = M.readBadgeCount(),
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
        if not battle_is_wild and M.TRAINER_CLASS_ADDR then
            local class_id = M.read_u8(M.TRAINER_CLASS_ADDR)
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

    local area = last_area_id
    if is_gift and area == "" then area = "gift" end

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

            send({
                event = "capture",
                key = bmon.key,
                area_id = last_area_id,
                species_id = natdex,
                nickname = nickname,
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

    -- ── Evolution detection: same slot, different key, same DVs+OTID invariant
    for slot, cur in pairs(cur_party) do
        local prev = prev_party[slot]
        if prev and prev.key ~= cur.key then
            -- Compare invariant portion: "DDDD:TTTT" (first 9 chars)
            local prev_inv = prev.key:sub(1, 9)
            local cur_inv  = cur.key:sub(1, 9)
            if prev_inv == cur_inv and not all_known_keys[cur.key] then
                on_evolution(prev.key, cur.key, cur.species_index, slot)
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
                    if was_in_party then
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
        if nuzlocke_active and battle_area_id ~= "" and not resolved_areas[battle_area_id] then
            if not G.is_gift_area(battle_area_id) then
                send({event = "no_catch", area_id = battle_area_id},
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
                event = "capture", key = mon.key, area_id = last_area_id,
                species = G.toNatDex(mon.species_index), level = mon.level,
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
            send({event = "no_catch", area_id = last_area_id},
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
local function on_frame()
    frame_count = frame_count + 1

    -- Re-validate writes if previously disabled (save may load after script start)
    if not writes_enabled then
        local ok, _ = M.validateROM()
        if ok then
            writes_enabled = true
            console.log("[SLink-RBY] ✓ ROM validation passed — writes enabled")
        end
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
            -- Seed all_known_keys from current box
            local box_count = M.getBoxCount()
            for i = 0, math.min(box_count, M.BOX_MAX_MONS) - 1 do
                local bmon = M.readBoxSlot(i)
                if bmon then all_known_keys[bmon.key] = true end
            end
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
        captured_this_battle = false
        whiteout_sent = false
        console.log(fmt("[SLink-RBY] Battle START (%s) area=%s",
            battle_is_wild and "wild" or "trainer", battle_area_id))
    elseif not cur_in_battle and in_battle then
        -- Battle ended
        post_battle_frames = POST_BATTLE_GRACE
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
                hud_show("★ " .. disp, 80, 255, 120, 180)
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
    end

    -- 9. Party diff (capture, faint, evolution, sync detection)
    diff_party()

    -- 9b. Execute pending sync commands (box_mon / party_mon) when safe
    if writes_enabled and not in_battle and #pending_sync_cmds > 0 then
        local cmd = table.remove(pending_sync_cmds, 1)
        local ok, err
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
                console.log("[SLink-RBY]   ↳ box_mon skipped: last mon in party")
                hud_show("! Can't deposit -- only mon!", 255, 200, 60, 240)
            else
                ok, err = M.depositPartyMon(found_slot)
                if ok then
                    sync_written_keys[cmd.key] = true
                    console.log("[SLink-RBY]   ↳ box_mon OK: " .. cmd.key:sub(1, 8))
                    hud_show("v " .. nick_label(cmd.key) .. " deposited", 100, 180, 255, 200)
                else
                    console.log("[SLink-RBY]   ↳ box_mon FAIL: " .. (err or "?"))
                    hud_show("X Deposit failed!", 255, 80, 80, 240)
                end
            end
        elseif cmd.cmd == "party_mon" then
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
                    hud_show("! Make room & get " .. nick_label(cmd.key), 255, 200, 60, 600)
                    send({event = "sync_retrieve_failed", key = cmd.key},
                         "sync_retrieve_failed:" .. cmd.key:sub(1, 8), true)
                end
            else
                ok, err = M.retrieveBoxMon(cmd.key)
                if ok then
                    sync_written_keys[cmd.key] = true
                    all_known_keys[cmd.key] = true
                    console.log("[SLink-RBY]   ↳ party_mon OK: " .. cmd.key:sub(1, 8))
                    hud_show("^ " .. nick_label(cmd.key) .. " retrieved", 100, 255, 160, 200)
                    send({event = "sync_retrieve_done", key = cmd.key},
                         "sync_retrieve_done:" .. cmd.key:sub(1, 8), true)
                else
                    console.log("[SLink-RBY]   ↳ party_mon FAIL: " .. (err or "?"))
                    hud_show("! Retrieve " .. nick_label(cmd.key) .. " from PC", 255, 200, 60, 600)
                    send({event = "sync_retrieve_failed", key = cmd.key},
                         "sync_retrieve_failed:" .. cmd.key:sub(1, 8), true)
                end
            end
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
                hud_show("! Can't memorialize -- only mon!", 255, 200, 60, 240)
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
                    hud_show("X " .. nick_label(cmd.key) .. " memorialized", 255, 140, 40, 300)
                    send({event = "memorialize_done", key = cmd.key},
                         "memorialize_done:" .. cmd.key:sub(1, 8), true)
                else
                    console.log("[SLink-RBY]   ↳ memorialize FAIL: " .. (err or "?"))
                    hud_show("X Memorial failed!", 255, 80, 80, 300)
                    send({event = "memorialize_failed", key = cmd.key, reason = err or "unknown"},
                         "memorialize_failed:" .. cmd.key:sub(1, 8), true)
                end
            end
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

-- ── Main loop ─────────────────────────────────────────────────────────────────
while true do
    on_frame()
    emu.frameadvance()
end
