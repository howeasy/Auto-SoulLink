--[[
  lua/clients/gen3_frlge_client.lua — SLink Gen 3 Client (Production Script)
  ==========================================================================
  Supports all three ROM profiles: vanilla FRLG, Archipelago (AP), and
  Radical Red 4.1 (CFRU/DPE). Profile is auto-detected by memory_gba.lua.

  Detects every SLink event type automatically, sends each to the Python
  server via TCP, and logs server responses to the Lua console.
  No GUI overlay.  Verbose logging for all commands and sync operations.

  Run server first:
      python -m server.server --host 127.0.0.1 --port 54321

  ┌─ EVENTS DETECTED AUTOMATICALLY ───────────────────────────────────────
  │  hello          — on TCP connect / reconnect (party snapshot)
  │  area_enter     — mapGroup+mapNum changes to a mapped encounter zone
  │  capture        — (battle) new monKey in party/PC box during/after battle
  │  capture        — (gift)   new monKey in party outside battle context
  │  box_to_party   — previously known monKey returns to party from PC box
  │  party_to_box   — party monKey disappears without fainting (deposited at PC)
  │  faint          — party mon HP transitions from > 0 to 0
  │  no_catch       — wild battle ends, no capture in grace window
  │                   gated by: wild-only + resolved_areas + gBattleOutcome
  │  whiteout       — all living party mons transition to HP = 0
  │  safe           — first overworld frame after a battle ends
  │  tick           — automatic every 60 frames; carries ball_count + party snapshot
  └────────────────────────────────────────────────────────────────────────

  ┌─ COMMANDS DISPATCHED ──────────────────────────────────────────────────
  │  force_faint    — write HP = 0 to matching party slot (immediate)
  │  box_mon        — deposit partner's linked mon to PC (deferred: safe state)
  │  party_mon      — restore partner's linked mon to party (deferred: safe state)
  │  memorialize    — move dead mon to Box 13 (deferred: safe state)
  │  pending_sync   — HUD notice: manual PC sync required
  └────────────────────────────────────────────────────────────────────────

  Manual F keys:
    F1  → area_enter        (current area_id)
    F2  → capture           (party slot 0)
    F3  → faint             (party slot 0)
    F4  → no_catch          (current area_id)
    F5  → whiteout
    F6  → safe
    F7  → tick              (includes ball_count + party snapshot)
    F8  → party_to_box      (party slot 0, if HP > 0)
    F9  → memorialize       (direct Lua write — party slot 0 → Box 13, no server)

  ┌─ TESTING CRITERIA ────────────────────────────────────────────────────
  │  ✓ Startup: TCP connected, hello sent, Writes: ON
  │  ✓ Walk into route → AUTO area_enter:route_N → noop
  │  ✓ Battle start/end logged with wild/trainer flag
  │  ✓ Catch (party not full) → AUTO capture(battle):key → noop
  │  ✓ Catch (party full=6)   → AUTO capture(box):key   → noop
  │  ✓ Gift/starter appear    → AUTO capture(gift):key  → noop
  │  ✓ Deposit mon at PC      → AUTO party_to_box:key   → box_mon queued for partner
  │  ✓ Retrieve mon from PC   → AUTO box_to_party:key   → party_mon queued for partner
  │  ✓ Trainer battle end     → NO no_catch fired
  │  ✓ Wild battle, run/KO    → AUTO no_catch:route_N   → noop/dead_zone
  │  ✓ Second battle same area → NO second no_catch
  │  ✓ Party mon HP→0         → AUTO faint:key
  │  ✓ All party fainted      → AUTO whiteout
  │  ✓ Return to overworld    → AUTO safe
  │  ✓ Faint → memorialize queued for both mons → Box 13 after safe state
  │  ✓ F9 → direct memorialize write; "✓ memorialize: <key> → box13 s0"
  └───────────────────────────────────────────────────────────────────────
--]]

-- ── CONFIGURE ─────────────────────────────────────────────────────────────────
-- Launcher scripts set SLINK_* globals before dofile("clients/gen3_frlge_client.lua").
-- Direct loading uses the defaults below.
local SERVER_HOST = SLINK_HOST   or "127.0.0.1"
local SERVER_PORT = SLINK_PORT   or 54321
local PLAYER_ID   = SLINK_PLAYER or "a"   -- "a" = FireRed, "b" = LeafGreen
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
           .. _proj_root .. "data/games/gen3_frlge/?.lua;"
           .. package.path

package.loaded["memory_gba"]        = nil
package.loaded["gen3_frlge_areas"]  = nil
package.loaded["connector"] = nil
package.loaded["socket"]    = nil
package.loaded["game_detect"]      = nil
package.loaded["games.gen3_frlge"] = nil
package.loaded["gen3_frlge_locations"] = nil
package.loaded["hud"]               = nil
package.loaded["mailbox"]           = nil
package.loaded["peer_ghost_npc"]    = nil

local M     = require("memory_gba")
local C     = require("connector")
local HUD   = require("hud")
-- Optional companion-patch mailbox (native in-game UI etc.). Absent on unpatched ROMs.
local ok_mb, MB = pcall(require, "mailbox")
if not ok_mb then MB = nil end
-- Presence is memoised per frame: ~10 call sites run every frame and each MB.present() costs
-- two BizHawk memory reads. NOT a permanent latch — a soft reset clears EWRAM, so the beacon
-- must be re-read (its loss/return drives the config re-assert in on_frame). One table, not
-- separate locals: the main chunk is at Lua's 200-local limit.
local PP = { frame = nil, val = false, was = nil, calc = true }
local function patch_present()
    local f = emu.framecount()
    if f ~= PP.frame then
        PP.frame = f
        PP.val = MB ~= nil and MB.present()
    end
    return PP.val
end

-- Native-enhancement toggles (server `config` on hello; see state.py). Pre-config defaults match the
-- server's: messages/sounds OFF (Lua HUD/m4a paths until the native paths win the A/B test), calc ON
-- (the EWRAM byte's boot default already shows it — nothing to write until config says otherwise).
-- Declared HERE (before safe_native_box) so the gates below close over the real locals.
local native_msgs_enabled = false   -- field msgbox + in-battle notifications via the patch
local native_sfx_enabled  = false   -- notification sounds via the patch's PlaySE

-- A native field box is a BLOCKING dialogue (lockall + A-to-dismiss), so it must only open in a genuinely
-- SAFE state: patched, in the overworld, AND no field script/box already running. isInOverworld() is still
-- true mid-dialogue / mid-cutscene, where OP_SHOW_MESSAGE is REFUSED (it guards on sScriptContext2Enabled)
-- and — without this check — the notification was silently DROPPED. When this returns false the caller
-- falls back to a Lua overlay (center-prompt / HUD) instead of losing the message. 0x03000F9C =
-- sScriptContext2Enabled (same address the trade state machine uses for "field clear").
local function safe_native_box()
    return native_msgs_enabled and patch_present() and M.isInOverworld()
       and memory.read_u8(0x03000F9C) == 0
end
local patch_logged = false   -- latch: log patch presence/absence once (beacon appears ~frame 13)
-- PP.was (above) holds the previous frame's beacon state (nil = never sampled); it drives the
-- config-byte re-assert when the beacon comes (back) up post-reset.
local pg_send_logged = false -- one-shot: confirm we're broadcasting our overworld position
-- world-pixel calibration (sub-pixel position via the coordOffset delta, captured while idle)
local pg_align_tx, pg_align_ty, pg_coff_ax, pg_coff_ay = nil, nil, 0, 0
local pg_last_sent_wx, pg_last_sent_wy = nil, nil  -- last broadcast world-px (mv = advancing?)
-- Engine-NPC peer ghost (companion-patch path; no-ops without the patch).
local ok_pg, PG = pcall(require, "peer_ghost_npc")
if ok_pg then
    PG.init()
else
    console.log("[SLink-FRLGE] peer-ghost receiver FAILED to load: " .. tostring(PG))
    PG = nil
end
-- Disable the patch's PC trade-NPC until the server's `config` command resolves the presence rule, so a
-- stale/garbage EWRAM enable byte can't spawn the NPC before we know the run is presence-OFF. Plain EWRAM
-- write — safe even before the patch beacon is up.
if MB then MB.set_pc_npc(false) end
-- Resync the event ring's read index (drop events from before this Lua load) — plain EWRAM writes,
-- safe before the patch beacon is up. See MB.events_drain in on_frame.
if MB then MB.events_init() end

-- Game module detection — provides game-specific area/gift classification
-- and profile data for memory.lua initialization
local game_detect = require("game_detect")
local detected    = game_detect.detect()
local game_module = detected.module

-- ── Localized hot-path globals ────────────────────────────────────────────────
local mem_u8   = memory.read_u8
local mem_u16  = memory.read_u16_le
local mem_u32  = memory.read_u32_le

-- ── Utility helpers ───────────────────────────────────────────────────────────
-- ONE local: this file is at Lua's 200-locals-per-function ceiling.
-- Native SOULLINK panel (§6). `panel` is the server's last link_panel payload; the rest is the
-- little state machine that pages through it. `rows` is the server's last link_panel payload:
-- flat, pre-formatted row strings.
local INFO = { rows = nil, page = 0, pages = 1, enabled = false, drawn = nil, showing = false }

-- Stage INFO.page into the patch's EWRAM panel. The server sends rows pre-formatted and flat
-- (`field|field|...`), because this client has no JSON decoder — parse_command_list is a pattern
-- scraper, so a nested payload would never reach here. All this does is chunk them into pages and
-- turn the separator back into the newline the encoder maps to the FR field separator.
-- 6 rows per page, and a pair is always 2 rows starting at an even index, so a pair can never
-- straddle a page boundary.
function info_stage()
    if not (MB and INFO.rows) then return 0 end
    local n = #INFO.rows
    INFO.pages = math.max(1, math.ceil(n / 6))
    if INFO.page >= INFO.pages then INFO.page = 0 end
    local rows = {}
    for i = INFO.page * 6 + 1, math.min(n, (INFO.page + 1) * 6) do
        rows[#rows + 1] = (INFO.rows[i]:gsub("|", "\n"))
    end
    if #rows == 0 then rows[1] = "No run data yet" end
    MB.write_info(rows, INFO.page, INFO.pages)
    return INFO.pages
end

local function area_display(id)
    return id:gsub("_", " "):gsub("(%a)([%w]*)", function(a, b) return a:upper()..b end)
end

-- ── JSON encoder ──────────────────────────────────────────────────────────────
-- Optimised: O(n) array check, pre-built format strings, minimal allocations.
local _json_esc = {['\\']='\\\\', ['"']='\\"', ['\n']='\\n', ['\r']='\\r', ['\t']='\\t'}
local function json_encode(val)
    local t = type(val)
    if val == nil         then return "null"
    elseif t == "boolean" then return val and "true" or "false"
    elseif t == "number"  then
        -- integer fast path (avoids ".0" suffix from tostring for whole numbers)
        if val == val and val % 1 == 0 and val >= -2147483648 and val <= 2147483647 then
            return string.format("%d", val)
        end
        return tostring(val)
    elseif t == "string"  then
        return '"' .. val:gsub('[\\"\n\r\t]', _json_esc) .. '"'
    elseif t == "table" then
        -- O(n) array detection: true if sequential integer keys 1..#val with no holes
        local n = #val
        local is_arr = (n > 0)
        if is_arr then
            -- Only verify there are no extra non-integer keys
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
    else return '"['..t..']"' end
end

-- ── Response parsing ──────────────────────────────────────────────────────────
local function parse_command_list(raw)
    local cmds = {}
    -- JSON boolean -> Lua boolean (nil when the field is absent; dispatch treats nil as "not sent")
    local function jbool(obj, field)
        local v = obj:match('"' .. field .. '"%s*:%s*(%a+)')
        if v == "true" then return true elseif v == "false" then return false end
        return nil
    end
    local arr = raw:match('"commands"%s*:%s*(%b[])')
    if not arr then return cmds end
    for obj in arr:gmatch('%b{}') do
        local cmd = obj:match('"cmd"%s*:%s*"([^"]+)"')
        local key = obj:match('"key"%s*:%s*"([^"]+)"')
        local msg = obj:match('"message"%s*:%s*"([^"]*)"')
        -- link_panel rows: a flat JSON array of strings. Safe to scrape with a naive quoted-string
        -- pattern because the server emits only names, digits and '|' -- never a quote or backslash.
        local rows = nil
        local rowsj = obj:match('"rows"%s*:%s*(%b[])')
        if rowsj then
            rows = {}
            for r in rowsj:gmatch('"([^"]*)"') do rows[#rows + 1] = r end
        end
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
        -- hud_show / msgbox fields
        local text    = obj:match('"text"%s*:%s*"([^"]*)"')
        if text then text = text:gsub("\\n", "\n") end   -- JSON-escaped newline -> real (FR line break)
        local fb      = obj:match('"fb"%s*:%s*"([^"]*)"')   -- msgbox fallback style: "prompt" or hud
        -- ghost_pos (peer ghost) fields — x,y are TILE coords now; the patch interpolates.
        local gmg  = tonumber(obj:match('"mg"%s*:%s*(%-?%d+)'))
        local gmn  = tonumber(obj:match('"mn"%s*:%s*(%-?%d+)'))
        local ggx  = tonumber(obj:match('"x"%s*:%s*(%-?%d+)'))
        local ggy  = tonumber(obj:match('"y"%s*:%s*(%-?%d+)'))
        local ggf  = tonumber(obj:match('"f"%s*:%s*(%-?%d+)'))
        local ggfx = tonumber(obj:match('"gfx"%s*:%s*(%-?%d+)'))
        local gmv  = tonumber(obj:match('"mv"%s*:%s*(%-?%d+)'))
        local grun = tonumber(obj:match('"run"%s*:%s*(%-?%d+)'))
        local gan  = tonumber(obj:match('"an"%s*:%s*(%-?%d+)'))   -- partner live animNum
        -- partner avatar: live sprite images/anims ROM ptrs (u32) + true 16-colour palette (64 hex)
        local gimgs = tonumber(obj:match('"imgs"%s*:%s*(%-?%d+)'))
        local ganim = tonumber(obj:match('"anim"%s*:%s*(%-?%d+)'))
        local gpcol = obj:match('"pcol"%s*:%s*"([0-9A-Fa-f]*)"')
        local r       = tonumber(obj:match('"r"%s*:%s*(%d+)'))
        local g       = tonumber(obj:match('"g"%s*:%s*(%d+)'))
        local b       = tonumber(obj:match('"b"%s*:%s*(%d+)'))
        local frames  = tonumber(obj:match('"frames"%s*:%s*(%d+)'))
        -- play_sound field
        local sound   = tonumber(obj:match('"sound"%s*:%s*(%d+)'))
        -- unresolve_area field
        local area_id = obj:match('"area_id"%s*:%s*"([^"]*)"')
        -- resolved_areas: parse "areas" array of strings
        local areas   = nil
        local areas_raw = obj:match('"areas"%s*:%s*(%b[])')
        if areas_raw then
            areas = {}
            for a in areas_raw:gmatch('"([^"]+)"') do
                areas[#areas + 1] = a
            end
        end
        -- replace_rival_team fields
        local trainer_id = tonumber(obj:match('"trainer_id"%s*:%s*(%-?%d+)'))
        local blobs_hex = nil
        local bh_raw = obj:match('"blobs_hex"%s*:%s*(%b[])')
        if bh_raw then
            blobs_hex = {}
            for s in bh_raw:gmatch('"([^"]+)"') do
                blobs_hex[#blobs_hex + 1] = s
            end
        end
        -- talk-to-partner menu / trade fields
        local token    = obj:match('"token"%s*:%s*"([^"]*)"')        -- show_menu/show_choices round-trip id
        local slot     = tonumber(obj:match('"slot"%s*:%s*(%-?%d+)')) -- apply_trade party slot
        local blob_hex = obj:match('"blob_hex"%s*:%s*"([0-9A-Fa-f]*)"') -- apply_trade single 100-byte mon
        local old_key  = obj:match('"old_key"%s*:%s*"([^"]*)"')       -- apply_trade: key the slot SHOULD hold
        local options  = nil                                          -- show_choices option labels
        local opt_raw  = obj:match('"options"%s*:%s*(%b[])')
        if opt_raw then
            options = {}
            for s in opt_raw:gmatch('"([^"]*)"') do options[#options + 1] = s end
        end
        -- config (per-run patch-feature toggles) — JSON booleans, nil when absent
        local overworld_presence = jbool(obj, "overworld_presence")
        local native_messages    = jbool(obj, "native_messages")
        local native_sounds      = jbool(obj, "native_sounds")
        local battle_calc        = jbool(obj, "battle_calc")
        local pc_trade_npc       = jbool(obj, "pc_trade_npc")
        if cmd then
            cmds[#cmds+1] = {
                cmd=cmd, key=key, message=msg, stats=stats, rows=rows,
                text=text, fb=fb, r=r, g=g, b=b, frames=frames,
                gmg=gmg, gmn=gmn, ggx=ggx, ggy=ggy, ggf=ggf, ggfx=ggfx, gmv=gmv, grun=grun, gan=gan,
                gimgs=gimgs, ganim=ganim, gpcol=gpcol,
                sound=sound, area_id=area_id, areas=areas,
                trainer_id=trainer_id, blobs_hex=blobs_hex,
                token=token, slot=slot, blob_hex=blob_hex, old_key=old_key, options=options,
                overworld_presence=overworld_presence, native_messages=native_messages,
                native_sounds=native_sounds, battle_calc=battle_calc, pc_trade_npc=pc_trade_npc,
            }
        end
    end
    return cmds
end
local function format_cmds(cmds)
    if #cmds == 0 then return "???" end
    local p = {}
    for _, c in ipairs(cmds) do
        if c.cmd == "pending_sync" then
            p[#p+1] = "pending_sync"
        elseif c.key then
            p[#p+1] = c.cmd.."("..c.key:sub(1,8).."...)"
        else
            p[#p+1] = c.cmd
        end
    end
    return table.concat(p, ", ")
end

-- ── ROM profile detection and validation ─────────────────────────────────────
M.applyProfile(detected.profile, detected.variant)
local rom_type        = detected.module.rom_type_for_variant(detected.variant)
local IS_RR           = (detected.variant == "radical_red")  -- peer ghost is RR-only
local val_ok, val_err = M.validateROM()
local writes_enabled  = val_ok
-- Re-validated each frame when false (save may not be loaded at script start).
local memorial_box_renamed = false  -- one-shot: rename Box 13 to "THE DEAD"
local memorial_overflow_renamed = {} -- overflow boxes already renamed

-- ── Deferred sync state (declared before dispatch_commands uses them) ─────────
local pending_sync_cmds = {}  -- deferred box_mon / party_mon commands
local sync_written_keys = {}  -- keys written by auto-sync this frame (suppress re-fire)
local nick_cache        = {}  -- key → display label (updated from party snapshots)

-- ── Party integrity protection ────────────────────────────────────────────────
-- CFRU's game engine may react to party modifications (deposit/compact/retrieve)
-- between frames and inadvertently swap substruct data (species, held items)
-- between party mons. When species is corrupted, the engine recalculates the
-- entire stat block (HP, maxHP, attack, …) from wrong base stats.
-- We snapshot critical fields before sync ops and verify/restore after.

-- Forward-declare variables used by dispatch_commands but initialized later
local resolved_areas        = {}
local resolved_areas_seeded = false
local pending_hud_area      = nil


-- Pokémon-Center trade NPC (presence-OFF trade entry point). The companion patch spawns/arms/despawns
-- the NPC; the client only (a) tells the patch when to do so via MB.set_pc_npc (presence OFF) and
-- (b) relays the talk (pi_count bump -> trade_request). `pc_npc_enabled` is set from the server's
-- `config` command on hello; `pc_npc_pi_last` tracks the interact counter delta.
local pc_npc_enabled = false
local pc_npc_pi_last = nil
-- PP.calc (above) holds the Battle Calc kill-switch state from the server config, kept so both
-- patch bytes (TN_ENABLE, CALC_OFF) can be RE-asserted when the patch beacon comes (back) up —
-- a soft reset clears EWRAM while the TCP connection (and the one-shot config) does not recur.

-- ── HUD overlay ───────────────────────────────────────────────────────────────
-- Minimal on-screen display shown during deaths and party swaps only.
-- GBA screen: 240 × 160. HUD appears at the bottom.
-- ── HUD overlay (shared module) ───────────────────────────────────────────────
HUD.init({screen_w = 240, screen_h = 160, hud_x = 3, hud_y = 146, hud_right = 237,
          prompt_y = 44, prompt_h = 14, gameover_y = 60})
local hud_show     = HUD.show
local hud_render   = HUD.render
local prompt_show  = HUD.prompt

-- In-battle notification presentation. The native FIELD message box can't open in battle, so notifications
-- that fire IN battle used the BizHawk Lua HUD overlay. With the companion patch we instead draw NATIVE text
-- into the Battle Calc's move-info area (top-left, window 0xD) via the in-context BattlePutTextOnWindow hook
-- (OP_SHOW_BATTLE_MESSAGE) — no emulator overlay, and it shows even outside the FIGHT menu (the patch draws
-- it reentrantly whenever the engine redraws a window). Falls back to the BizHawk overlay when unpatched or
-- not in battle (out-of-battle + unpatched unchanged). Text must be FR-charmap-safe (A-Z/a-z/0-9/space/!?.-,/:).
local NATIVE_BATTLE_FRAMES = 180   -- how long to hold the native notification once first shown (~3s; tunable)
local NATIVE_BATTLE_WIN    = 0x0D  -- the Battle Calc's move-info area (top-left) — see slink_battletext_hook
-- Window 0xD clips visually at ~28 chars ("…Squirtle linke|"); truncate per line like hud.lua's fit_hud
-- so a long notification ends in ".." instead of being cut mid-glyph. FR-safe ('.' is in the charmap).
local NATIVE_BATTLE_MAXCHARS = 28
local function fit_battle_text(text)
    local out = {}
    for line in (text .. "\n"):gmatch("([^\n]*)\n") do
        local fitted = line
        if #fitted > NATIVE_BATTLE_MAXCHARS then
            fitted = fitted:sub(1, NATIVE_BATTLE_MAXCHARS - 2) .. ".."
        end
        out[#out + 1] = fitted
    end
    return table.concat(out, "\n")
end
-- Map the HUD's event color (r,g,b — the same convention the overlay uses) to an FR battle-text color id
-- (battle move-info palette: 1=red, 4=gold, 5=green, 10=white) so the native text is themed like the HUD:
-- red = KO/BOOM/dead-zone, gold = shiny, green = link/trade/positive, white = neutral.
local function fr_battle_color(r, g, b)
    r, g, b = r or 255, g or 255, b or 255
    if r >= 180 and g >= 150 and b < 130 then return 4        -- gold/yellow (shiny)
    elseif g > r and g >= 150 then return 5                   -- green (link / trade / positive)
    elseif r >= 170 and g < 150 then return 1                 -- red (KO / BOOM / dead-zone)
    else return 10 end                                        -- white (neutral)
end
-- Pending native in-battle notifications. show_fallback QUEUES (never sends inline): the same dispatch
-- pass may have just sent another opcode (a storage/memorialize/trade op) and the single-slot
-- mailbox would CLOBBER it — losing the in-flight native action.
-- The on_frame drain sends ONE per frame, only when the mailbox slot is idle AND no notification is
-- currently showing (so stacked messages display sequentially, each for its full duration).
local pending_battle_msgs = {}
local function show_fallback(text, fb, r, g, b, frames)
    if patch_present() and M.isInBattle() then
        -- native in-battle text, themed to the event (the SOUND comes from the server's separate play_sound,
        -- routed to the Lua m4a path in battle so it can't clobber the text opcode — see play_sound dispatch).
        pending_battle_msgs[#pending_battle_msgs + 1] =
            { text = text, color = fr_battle_color(r, g, b), fb = fb, r = r, g = g, b = b, frames = frames }
    elseif fb == "prompt" then
        prompt_show(text, r, g, b, frames or 300)
    else
        hud_show(text, r, g, b, frames or 300)
    end
end
local game_over_flag   = false  -- set by game_over command; persistent HUD
local rebuild_active   = false  -- true between rebuild_start and rebuild_done

local function nick_label(key)
    return nick_cache[key] or key:sub(1, 8)
end

-- Battle-persistent cache: gBattleMons HP/maxHP/level keyed by monKey.
-- Keyed by identity (not slot) to prevent stale-index issues when switching mons.
-- Declared before dispatch_commands so force_faint can update it.
local _battle_hp_cache = {}  -- [monKey] → {hp, maxHP, level}
local _ability_cache   = {}  -- [monKey] → ability_id (persists across battles)

-- Deferred battle faints: keys that need force_faint but are the active battler.
-- Applied once the mon is no longer the active battler (switched out or battle ends).
local pending_battle_faints = {}  -- [monKey] → true

-- Coerced-Explosion state: keys whose battler had all 4 move slots overwritten
-- with Explosion in response to a partner-link force_faint. Settled when the
-- mon faints from Explosion, switches out, battle ends, or the fallback timer
-- elapses (in which case M.forceFaint is invoked as a safety net — covers the
-- Damp ability, type immunities that no-op the move, or player stalling).
local EXPLOSION_FALLBACK_FRAMES = 600  -- ~10s @ 60fps
local pending_explosions = {}          -- [monKey] → {slot, battler, start_frame}

-- NOTE — there is deliberately NO native battle-control path here.  The patch's
-- OP_FORCE_MOVE_SLOT controller-pointer swap failed in real two-sided play: the swap did not
-- fire, so the move was never forced, and the Explosion written into gBattleMons.moves[0] was
-- left in an OPEN FIGHT menu — selecting it SOFTLOCKED.  (The headless one-sided savestate
-- gate only proved the move COMMITS via a PP drop; it cannot exercise real turn execution.)
-- The Lua paths below skip the menu entirely — Variant-3 menu-skip for explode via canonical
-- CFRU addresses, deferred-faint for force_faint — and are the single production mechanism.
-- OP_FORCE_FAINT / OP_FORCE_MOVE_SLOT remain in the ROM (built and headless-validated) but
-- nothing drives them; see patch/ROADMAP.md §2 for what re-enabling would require.

-- Native-patch Rival-Team-Swap state.  The RR companion patch + OP_SET_ENEMY_PARTY are a HARD
-- REQUIREMENT — the old writeEnemyParty RAM-poke fallback was removed once rival swap was confirmed
-- functional.  Dispatch copies the partner's exact 100-byte blobs into gEnemyParty natively; settled
-- here: ST_OK → refresh the active foe's gBattleMons in Lua (no clean engine fn) + ack; ST_FAIL or
-- timeout → error ack (no fallback).  The handler is synchronous (one-frame memcpy), short timeout.
-- NB this is unrelated to the kill switch above — rival swap is a pure party-data memcpy, not the
-- forced-move controller swap that softlocked, so it stays native-only.
local ENEMY_PARTY_TIMEOUT = 120        -- frames before assuming the opcode was dropped → error ack
local pending_enemy_party = nil        -- {seq, trainer_id, blobs_hex, start_frame} (one in flight)

-- Native PC box⇄party storage (OP_DEPOSIT_MON / OP_WITHDRAW_MON). The opcode acks NEXT frame (the hook
-- runs between Lua callbacks), so a deposit/withdraw is async: exec_box_mon/exec_party_mon fire the
-- opcode + register this, and a poll in on_frame (§4a-quinque) does the success bookkeeping or — on
-- ST_FAIL/timeout — the Lua RAM-poke fallback (so a patched-but-failed op never strands the sync).
-- {mode="deposit"|"withdraw", key, slot, box, pos, stats, seq, start_frame}. One at a time.
local STORAGE_OP_TIMEOUT = 120
local pending_storage = nil
-- One in-flight native OP_MEMORIALIZE (mirrors pending_storage): {key, box, slot, pre_count, seq,
-- start_frame}. The §4a-sexies poll finishes it (verify + HUD + memorialize_done + rename) or falls
-- back to the Lua path. If the native opcode ever fails, native memorialize is disabled for the
-- session (the proven Lua path takes over for the rest of the run).
local pending_memorialize = nil
local memorialize_native_disabled = false

-- Talk-to-partner native UI (show_menu / choose_mon commands). One at a time; polled in on_frame, then
-- the result is reported back keyed by the server's token: kind="menu" -> menu_result{choice}, "choose"
-- -> mon_chosen{slot}.
local pending_ui = nil                 -- {seq, token, kind, start_frame}
local MENU_TIMEOUT = 1860              -- frames before giving up on a menu (patch's own ~1800 + slack)
-- A native notification box we sent + are CONFIRMING opened (OP_SHOW_MESSAGE returns result[0]=1 shown /
-- 0 refused). If refused (a field script/box slipped in after our safe-area check, the 1-frame race), the
-- on_frame poll falls back to the Lua overlay so the notification is never dropped. {seq, fb, text, r,g,b,
-- frames, start_frame}; fb = "prompt" (center) or "hud" (status line) for the fallback presentation.
local pending_msgbox = nil
local MSGBOX_CONFIRM_TIMEOUT = 12      -- frames; patch acks in ~1, so a lost ack -> assume shown (no double)
-- Native trade-scene apply (apply_trade command): a 2-step async state machine — stage the partner mon
-- into gEnemyParty[0], then run the native trade scene; on failure fall back to the silent party write.
local pending_trade_apply = nil        -- {slot, blob, old_key, phase="pending"|"stage"|"scene", seq, start_frame}
local TRADE_STAGE_TIMEOUT = 120        -- frames to stage gEnemyParty[0]
-- Backstop only — the patch's drive_ui (kind 3) is the source of truth for scene completion and acks
-- ST_OK/ST_FAIL when the scene returns to the field. This client-side cap is LONGER than the patch's
-- own ~5400-frame scene timeout so the patch normally wins the race; if the patch ack is ever lost we
-- reconcile from the slot (NEVER a silent swap on top of a possibly-running scene — that double-write
-- was the "pairs break if you wait too long" corruption).
local TRADE_SCENE_BACKSTOP = 6000      -- > patch scene timeout (5400); ~100 s
-- A trade replaces a party slot with the partner's mon = a KEY CHANGE. Hand it to the same key-
-- migration path the Nature-Changer uses (suppress the spurious capture/box diff for old+new), so
-- the per-frame party-sync handlers don't fire phantom events. {old=<traded-away key>, new=<received>}.
local pending_trade_migration = nil
-- Periodic self-status (badge count) so the server can show the partner's progress in-game.
local last_status_badges = -1          -- last badge count we sent (only resend on change)
local status_cooldown = 0              -- frames until the next status send is allowed

-- Frame counter — declared here (not lower down) so dispatch_commands, which records
-- start_frame for the pending_* tables, captures the SAME upvalue the on_frame settle
-- loops read. (Previously declared after dispatch_commands, so its start_frame writes
-- silently referenced a nil global → the fallback-timeout arithmetic could fault.)
local frame_count     = 0

-- Keys that have been force-fainted by server command during THIS BATTLE.
-- Prevents re-reporting the HP=0 as a new faint event back to the server.
-- Persists for the entire battle (cleared at battle start and battle end)
-- so that gBattleMons cache updates never overwrite HP=0.
local force_fainted_keys = {}  -- [monKey] → true

-- In-battle faint debounce: CFRU battle scripts process damage in multi-step
-- sequences within a single game frame.  Between steps, gBattleMons may show
-- transient HP=0 before abilities (Sturdy, Focus Sash, Endure) restore HP=1.
-- We require HP to stay at 0 for FAINT_DEBOUNCE_FRAMES before confirming.
--
-- Fast-path: profiles with M.BATTLE_RESULTS_ADDR (vanilla + CFRU) can confirm
-- via gBattleResults.playerFaintCounter delta, which only increments after
-- protection (Sturdy/Focus Sash/Endure) resolves.  AP has no address yet and
-- falls through to the 3-frame timer.
local FAINT_DEBOUNCE_FRAMES = 3
local pending_faint_debounce = {}  -- [monKey] → frames_remaining
local battle_start_player_faints  = nil  -- gBattleResults snapshot at battle start
local confirmed_real_player_faints = 0   -- count we've already credited via counter
-- EvRing fast-path (patched ROMs, ROADMAP §3): the patch pushes a frame-granular
-- EV_PLAYER_FAINT once protection (Sturdy/Sash/Endure) has resolved, and EV_OUTCOME on the
-- end-of-battle edge. These ACCELERATE the detectors below (skip the debounce timer / declare
-- whiteout on the engine's own LOSS edge); the per-frame polls stay as the unpatched fallback.
-- Boot/unpatched defaults (0/false) reproduce today's behavior exactly.
local ev_faint_credit = 0      -- unconsumed EV_PLAYER_FAINT events; any confirmed faint eats one
local ev_outcome_loss = false  -- EV_OUTCOME==2 (LOSS) seen this battle; consumed by whiteout
-- EV_PARTY_ADD / EV_EVOLVE cross-check. These two events do NOT drive behaviour: index_party
-- already runs every frame, so the Lua diff sees the same change on the same frame, and RR is
-- NO_ENCRYPT so there is no per-frame decryption for them to save. What they ARE good for is
-- proving the ring agrees with the proven path before ROADMAP §3's authority swap deletes that
-- path. Every event is matched against what Lua independently observed; a disagreement is
-- logged loudly and counted, so a soak reports itself instead of relying on someone noticing.
-- ONE local: this file is at Lua's 200-locals-per-function ceiling.
--   add/evolve  events awaiting a Lua-side match
--   pendingN    cheap "is anything pending" guard for the per-frame settle
--   dirty/dirtyN per-slot stats invalidation pushed by the ring
--   owns        true once the patch is present: the ring OWNS species-change detection and
--               index_party stops reading species per frame (that read is not free — it pushed
--               the ghost duo's worst behind-stall from 2 frames to 5-7)
local EV = { agree = 0, disagree = 0, pendingN = 0, add = {}, evolve = {},
             dirty = {}, dirtyN = 0, owns = false }
local function ev_expect(tbl, key, want, label)
    if tbl[key] == nil then EV.pendingN = EV.pendingN + 1 end
    tbl[key] = { want = want, frame = frame_count, label = label }
end

-- Called from index_party's caller once the Lua view has been rebuilt. Returns immediately on
-- the overwhelmingly common path (nothing pending) — a per-frame pairs() walk here is exactly
-- the kind of cost that showed up as ghost stutter in the duo metric.
local function ev_settle_xchecks(curr_count)
    if EV.pendingN == 0 then return end
    for slot, e in pairs(EV.evolve) do
        local base = M.PARTY_BASE + slot * M.MON_SIZE
        local got  = M.CFRU_NO_ENCRYPT and mem_u16(base + 0x20) or 0
        if got == e.want then
            EV.agree = EV.agree + 1
        elseif frame_count - e.frame > 30 then
            EV.disagree = EV.disagree + 1
            console.log(string.format(
                "[SLink-FRLGE] [ev] ⚠ RING/LUA DISAGREE on %s slot=%d: ring said species=%d, "
                .. "Lua reads %d (disagreements=%d)", e.label, slot, e.want, got, EV.disagree))
        else
            goto continue          -- still settling; re-check next frame
        end
        EV.evolve[slot] = nil; EV.pendingN = EV.pendingN - 1
        ::continue::
    end
    for i = #EV.add, 1, -1 do
        local e = EV.add[i]
        if curr_count >= e.want then
            EV.agree = EV.agree + 1
            table.remove(EV.add, i); EV.pendingN = EV.pendingN - 1
        elseif frame_count - e.frame > 30 then
            EV.disagree = EV.disagree + 1
            console.log(string.format(
                "[SLink-FRLGE] [ev] ⚠ RING/LUA DISAGREE on party_add: ring said count=%d, "
                .. "Lua reads %d (disagreements=%d)", e.want, curr_count, EV.disagree))
            table.remove(EV.add, i); EV.pendingN = EV.pendingN - 1
        end
    end
end

-- Forward declaration: dispatch_commands (below) sends rival_team_replaced before send() is
-- defined further down; without this the calls hit a nil global and crash the handler.
local send

-- After a trade (native scene OR silent fallback) finishes, read our post-trade party slot — which now
-- holds the partner's mon, possibly trade-EVOLVED — and (1) report its key + species so the server can
-- reconcile the link half, and (2) register the old->new KEY CHANGE so the local party-sync handlers
-- treat it as a migration (no phantom capture/box). Declared here (after `local send`) because it
-- calls send(). `old_key` is the key that occupied the slot BEFORE the trade (captured at trade start).
local function emit_trade_done(slot, old_key, token)
    local base = (M.PARTY_BASE or 0x02024284) + slot * (M.MON_SIZE or 0x64)
    local ok_k, key     = pcall(M.monKey, base)
    local ok_s, species = pcall(M.decryptSpecies, base)
    local new_key = (ok_k and key) or ""
    if old_key and old_key ~= "" and new_key ~= "" and old_key ~= new_key then
        pending_trade_migration = { old = old_key, new = new_key }
    end
    -- token ties this report to the trade the server dispatched (a stale report from an
    -- earlier aborted trade must not count toward the current one).
    send({ event = "trade_done", slot = slot, token = token or "",
           new_key = new_key, new_species = (ok_s and species) or 0 },
         "trade_done", true, false)
end

-- The apply_trade slot index is a snapshot from mon_chosen; the player free-roams until the
-- apply actually runs and may have reordered their party. Re-locate the offered mon by key
-- and fix p.slot in place. If the key is nowhere in the party (boxed in the apply window —
-- the server re-validates at confirm, so this is a seconds-wide race), keep the original
-- slot and log loudly. ponytail: last-resort slot write can still hit a bystander mon in
-- that race; a full fix needs client-side abort + server-side one-sided rollback.
local function relocate_trade_slot(p)
    if not p.old_key or p.old_key == "" then return end
    local ok_c, count = pcall(memory.read_u8, M.PARTY_COUNT_ADDR)
    if not ok_c then return end
    for slot = 0, math.min(count, 6) - 1 do
        local ok_k, k = pcall(M.monKey, (M.PARTY_BASE or 0x02024284) + slot * (M.MON_SIZE or 0x64))
        if ok_k and k == p.old_key then
            if slot ~= p.slot then
                console.log("[SLink-FRLGE]   ↳ trade: party reordered — mon moved slot " ..
                            tostring(p.slot) .. " -> " .. tostring(slot))
                p.slot = slot
            end
            return
        end
    end
    console.log("[SLink-FRLGE]   ↳ trade: WARNING old_key not in party — applying to original slot " ..
                tostring(p.slot))
end

-- ── Command dispatcher ────────────────────────────────────────────────────────
local function dispatch_commands(cmds)
    -- At most ONE native field box per dispatch pass — only one box can be on screen, so a second
    -- msgbox/gui_prompt in the same batch would be refused + lost. The rest fall back to a Lua overlay.
    local native_box_used = false
    -- Shared by the msgbox and gui_prompt branches: a NATIVE field box only in a safe area
    -- (patched, overworld, no field script/box up, none used this pass, none awaiting confirm),
    -- CONFIRMED by the on_frame poll with a Lua-overlay fallback — never dropped.
    local function try_native_box(text, fb, label, r, g, b, frames)
        if safe_native_box() and not native_box_used and pending_msgbox == nil then
            MB.write_message(text)
            local s = MB.send(MB.OP_SHOW_MESSAGE, {})
            native_box_used = true
            pending_msgbox = { seq = s, fb = fb, text = text, r = r or 255, g = g or 255,
                               b = b or 255, frames = frames or 300, start_frame = frame_count }
            console.log("[SLink-FRLGE]   ↳ " .. label .. " (native): " .. text)
        else
            -- Not a safe overworld box: native BATTLE message box when patched + in battle (the
            -- BizHawk-HUD-in-battle replacement), else the Lua overlay (center-prompt / HUD).
            show_fallback(text, fb, r or 255, g or 255, b or 255, frames or 300)
            console.log("[SLink-FRLGE]   ↳ " .. label .. ": " .. text)
        end
    end
    for _, c in ipairs(cmds) do
        if c.cmd == "play_sound" and c.sound then
            -- Native SE via the companion patch (PlaySE) when present — retires the fragile Lua m4a
            -- SE1 RAM-poke (M.playSE / profile SE_SONG_HEADERS). Fallback keeps unpatched ROMs working.
            -- IN BATTLE, use the Lua m4a path instead: a native in-battle notification (OP_SHOW_BATTLE_MESSAGE)
            -- may be sent the same frame, and the single-slot mailbox would otherwise clobber one opcode.
            if native_sfx_enabled and patch_present() and not M.isInBattle() then MB.play_se(c.sound)
            else M.playSE(c.sound) end
        elseif (c.cmd == "force_faint" or c.cmd == "force_explode") and c.key then
            -- Populate nick_cache from server-provided nickname (for mons not in our party yet).
            if c.nickname and c.nickname ~= "" then
                nick_cache[c.key] = c.nickname
            end
            -- `force_explode` is the Explode-Mode variant (server-side run rule):
            -- when the linked mon is the active battler, coerce it into auto-
            -- Exploding via the Variant-3 menu-skip writes (gActionForBanks /
            -- gChosenMovesByBanks / gBattleCommunication / gBattleStruct fields).
            -- `force_faint` is the legacy path: defer until the mon switches out
            -- or the battle ends, then write HP=0 silently.  Bench-mon handling
            -- is identical for both commands (immediate M.forceFaint).
            local is_explode = (c.cmd == "force_explode")
            if writes_enabled then
                local currently_in_battle = M.isInBattle()
                local count = memory.read_u8(M.PARTY_COUNT_ADDR)
                for slot = 0, count - 1 do
                    local base = M.PARTY_BASE + slot * M.MON_SIZE
                    if M.monKey(base) == c.key then
                        -- Check if this mon is an active battler (battler 0 or battler 2 in doubles).
                        local is_active_battler = false
                        if currently_in_battle and M.BATTLER_PARTY_INDEXES_ADDR then
                            is_active_battler = memory.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR) == slot
                            if not is_active_battler
                               and M.BATTLERS_COUNT_ADDR
                               and mem_u8(M.BATTLERS_COUNT_ADDR) >= 4 then
                                -- Doubles: battler 2 is the player's second active mon.
                                is_active_battler = memory.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR + 4) == slot
                            end
                        end
                        if is_active_battler and is_explode then
                            -- Explode Mode (RR only): the active linked mon auto-Explodes.
                            local battler = M.getBattlerForPartySlot(slot)
                            if M.forceExplodeBattler and battler >= 0 and M.forceExplodeBattler(battler) then
                                -- Variant-3 menu-skip RAM writes pre-fill the engine's action-commit
                                -- state so the FIGHT/BAG/POKEMON/RUN menu is skipped and Explosion
                                -- fires next turn.  This is the production path on patched and
                                -- unpatched ROMs alike — see the note by pending_explosions.
                                pending_explosions[c.key] = {
                                    slot = slot, battler = battler, start_frame = frame_count,
                                }
                                M.playSE(M.SE_LINKED_KO)
                                show_fallback("!! " .. nick_label(c.key) .. " BOOM!", "hud", 255, 80, 80, 360)
                                console.log(string.format(
                                    "[SLink-FRLGE]   ↳ force_explode → menu skip coerced slot=%d battler=%d key=%s",
                                    slot, battler, c.key))
                            else
                                pending_battle_faints[c.key] = true
                                console.log(string.format(
                                    "[SLink-FRLGE]   ↳ force_explode DEFERRED (helper refused — non-RR profile?) slot=%d key=%s",
                                    slot, c.key))
                                show_fallback("!! " .. nick_label(c.key) .. " KO pending", "hud", 255, 80, 80, 360)
                            end
                        elseif is_active_battler then
                            -- force_faint, active battler: defer the HP=0 write until the mon
                            -- switches out or the battle ends (the engine continuously refreshes
                            -- gBattleMons, so a direct write races it).
                            pending_battle_faints[c.key] = true
                            console.log(string.format(
                                "[SLink-FRLGE]   ↳ force_faint DEFERRED (active battler) slot=%d key=%s",
                                slot, c.key))
                            show_fallback("!! " .. nick_label(c.key) .. " KO pending", "hud", 255, 80, 80, 360)
                        else
                            -- Bench mon (or out of battle): immediate HP=0 write.
                            -- Identical handling for force_faint and force_explode.
                            M.forceFaint(slot)
                            _battle_hp_cache[c.key] = {hp = 0, maxHP = mem_u16(base + M.OFF_MAX_HP), level = mem_u8(base + M.OFF_LEVEL)}
                            force_fainted_keys[c.key] = true
                            M.playSE(M.SE_LINKED_KO)
                            console.log(string.format("[SLink-FRLGE]   ↳ DISPATCHED %s slot=%d key=%s in_battle=%s", c.cmd, slot, c.key, tostring(currently_in_battle)))
                            hud_show("!! " .. nick_label(c.key) .. " KO'd", 255, 80, 80, 360)
                        end
                        break
                    end
                end
            else
                console.log("[SLink-FRLGE]   ↳ "..c.cmd.." skipped (writes off) key="..tostring(c.key))
            end
        elseif c.cmd == "replace_rival_team" and c.blobs_hex then
            -- Rival Team Swap: overwrite gEnemyParty with the partner's cached
            -- party blobs (one 100-byte mon per slot, hex-encoded).  Must be in
            -- a battle for the write to affect anything visible — out-of-battle
            -- writes are harmless (next battle init clobbers gEnemyParty) but
            -- the readback ack would be against stale data, so we skip them.
            if not M.isInBattle() then
                console.log("[SLink-FRLGE]   ↳ replace_rival_team: not in battle, skipping")
                send({event = "rival_team_replaced", trainer_id = c.trainer_id or 0,
                      species_ids = {}, error = "not_in_battle"},
                     "rival_team_replaced", true)
            elseif not writes_enabled then
                console.log("[SLink-FRLGE]   ↳ replace_rival_team: writes disabled")
            elseif not patch_present() then
                -- The RR companion patch is a HARD REQUIREMENT for rival swap — the writeEnemyParty
                -- RAM-poke fallback was removed.  Surface an error ack so the server/UI knows the
                -- swap did not happen (and why).
                console.log("[SLink-FRLGE]   ↳ replace_rival_team: companion patch ABSENT — required, skipping")
                send({event = "rival_team_replaced", trainer_id = c.trainer_id or 0,
                      species_ids = {}, error = "patch_required"},
                     "rival_team_replaced", true)
            else
                -- NATIVE (companion patch): byte-copy the partner's EXACT team into gEnemyParty via
                -- OP_SET_ENEMY_PARTY (preserves moves/IVs/EVs/item), settled in on_frame (§4a-quater).
                -- Decode hex here; a malformed blob errors the ack (no RAM-poke fallback).
                local rows, derr = {}, nil
                for i = 1, #c.blobs_hex do
                    local arr, e = M.hexToBytes(c.blobs_hex[i])
                    if not arr then derr = e or "decode"; break end
                    if #arr ~= 100 then  -- short blob would nil-write mid-stage; long = malformed server data
                        derr = string.format("blob %d length %d (want 100)", i, #arr); break
                    end
                    rows[i] = arr
                end
                local seq = (not derr) and MB.set_enemy_party(rows) or nil
                if seq then
                    pending_enemy_party = {seq = seq, trainer_id = c.trainer_id,
                                           blobs_hex = c.blobs_hex, start_frame = frame_count}
                    console.log(string.format(
                        "[SLink-FRLGE]   ↳ replace_rival_team → native OP_SET_ENEMY_PARTY armed n=%d trainer=%s seq=%d",
                        #rows, tostring(c.trainer_id or "?"), seq))
                else
                    console.log("[SLink-FRLGE]   ↳ replace_rival_team native stage FAILED ("
                        .. tostring(derr or "send") .. ") — no fallback")
                    send({event = "rival_team_replaced", trainer_id = c.trainer_id or 0,
                          species_ids = {}, error = derr or "stage_failed"},
                         "rival_team_replaced", true)
                end
            end
        elseif c.cmd == "pending_sync" then
            console.log("[SLink-FRLGE]   ↳ ⚠ SYNC REQUIRED: "..(c.message or "check partner at PC"))
        elseif c.cmd == "box_mon" and c.key then
            -- Cancel any pending party_mon for the same key (opposing commands = net no-op).
            local filtered = {}
            for _, p in ipairs(pending_sync_cmds) do
                if not (p.key == c.key and p.cmd == "party_mon") then
                    filtered[#filtered + 1] = p
                end
            end
            pending_sync_cmds = filtered
            table.insert(pending_sync_cmds, {cmd="box_mon", key=c.key})
            console.log("[SLink-FRLGE]   ↳ box_mon queued: "..c.key:sub(1,8))
        elseif c.cmd == "party_mon" and c.key then
            -- Populate nick_cache from server-provided nickname before any HUD display.
            if c.nickname and c.nickname ~= "" then
                nick_cache[c.key] = c.nickname
            end
            -- Cancel any pending box_mon for the same key (opposing commands = net no-op).
            local filtered = {}
            for _, p in ipairs(pending_sync_cmds) do
                if not (p.key == c.key and p.cmd == "box_mon") then
                    filtered[#filtered + 1] = p
                end
            end
            pending_sync_cmds = filtered
            table.insert(pending_sync_cmds, {cmd="party_mon", key=c.key, stats=c.stats})
            console.log("[SLink-FRLGE]   ↳ party_mon queued: "..c.key:sub(1,8))
        elseif c.cmd == "memorialize" and c.key then
            -- Deduplicate: skip if this key already has a pending memorialize
            local already_queued = false
            for _, p in ipairs(pending_sync_cmds) do
                if p.cmd == "memorialize" and p.key == c.key then
                    already_queued = true; break
                end
            end
            if not already_queued then
                table.insert(pending_sync_cmds, {cmd="memorialize", key=c.key})
                console.log("[SLink-FRLGE]   ↳ memorialize queued: "..c.key:sub(1,8))
            else
                console.log("[SLink-FRLGE]   ↳ memorialize deduped: "..c.key:sub(1,8))
            end
        elseif c.cmd == "msgbox" and c.text then
            -- Lua-overlay fallback style: center-prompt for fb="prompt", else the HUD line.
            try_native_box(c.text, (c.fb == "prompt") and "prompt" or "hud", "msgbox",
                           c.r, c.g, c.b, c.frames)
        elseif c.cmd == "show_menu" and c.text and c.token then
            -- Talk-to-partner action menu (native YES/NO). Async: register + poll in on_frame, then
            -- emit menu_result{token,choice}. Unpatched or out-of-overworld can't show a native menu,
            -- so auto-decline (choice 0) immediately — the server treats that as "no".
            if patch_present() and M.isInOverworld() and not pending_ui then
                local seq = MB.show_menu(c.text)
                if seq then
                    -- cancel: what a failed/timed-out poll reports. Yes/no menu: 0 = declined.
                    pending_ui = { seq = seq, token = c.token, kind = "menu", cancel = 0,
                                   start_frame = frame_count }
                else
                    send({ event = "menu_result", token = c.token, choice = 0 }, "menu_result", true, false)
                end
            else
                send({ event = "menu_result", token = c.token, choice = 0 }, "menu_result", true, false)
            end
        elseif c.cmd == "show_choices" and c.options and c.token then
            -- Native multichoice list (e.g. Trade / Say hey). Async: register + poll, then emit
            -- menu_result{token, choice=index} (0-based, or 127 = cancel). Unpatched / out-of-overworld
            -- can't show a native menu -> report cancel so the server aborts the flow cleanly.
            if patch_present() and M.isInOverworld() and not pending_ui then
                local seq = MB.show_choices(c.options, c.text)   -- c.text = the talk-NPC's spoken line
                if seq then
                    -- cancel: multichoice index 0 is a REAL option ("Trade"), so a failed/timed-out
                    -- poll must report the cancel sentinel 127, never 0.
                    pending_ui = { seq = seq, token = c.token, kind = "menu", cancel = 127,
                                   start_frame = frame_count }
                else
                    send({ event = "menu_result", token = c.token, choice = 127 }, "menu_result", true, false)
                end
            else
                send({ event = "menu_result", token = c.token, choice = 127 }, "menu_result", true, false)
            end
        elseif c.cmd == "choose_mon" and c.token then
            -- Pick which linked mon to trade via the native party menu. Async: register + poll, then
            -- emit mon_chosen{token,slot} (0-5, or 7=cancel). Unpatched/out-of-overworld -> cancel.
            if patch_present() and M.isInOverworld() and not pending_ui then
                local seq = MB.choose_party_mon()
                if seq then
                    pending_ui = { seq = seq, token = c.token, kind = "choose", start_frame = frame_count }
                else
                    send({ event = "mon_chosen", token = c.token, slot = 7 }, "mon_chosen", true, false)
                end
            else
                send({ event = "mon_chosen", token = c.token, slot = 7 }, "mon_chosen", true, false)
            end
        elseif c.cmd == "apply_trade" and c.blob_hex and c.slot ~= nil then
            -- Trade: BUFFER the request (decode the blob now); the on_frame state machine waits until the
            -- field is clear, stages the partner mon into gEnemyParty[0], runs the NATIVE trade scene
            -- (animation + trade-evolution), and falls back to a silent party write on failure. Buffering
            -- (vs acting here) means a not-yet-overworld / mid-dialogue arrival is never silently dropped.
            local arr = M.hexToBytes(c.blob_hex)
            if arr and #arr >= 100 then
                -- Capture the key currently in the slot (the mon we're trading AWAY) BEFORE the swap,
                -- so trade completion can register old->new as a key migration. Prefer the
                -- server-sent old_key (authoritative — the slot index is a stale snapshot and
                -- the player may have reordered their party since mon_chosen).
                local ok_ok, slot_key = pcall(M.monKey, (M.PARTY_BASE or 0x02024284) + c.slot * (M.MON_SIZE or 0x64))
                local old_key = (c.old_key and c.old_key ~= "" and c.old_key) or (ok_ok and slot_key) or nil
                pending_trade_apply = { slot = c.slot, blob = arr, old_key = old_key, token = c.token,
                                        phase = "pending", start_frame = frame_count }
                console.log("[SLink-FRLGE]   ↳ apply_trade received (slot " .. tostring(c.slot) ..
                            ") — queued for native trade")
            else
                console.log("[SLink-FRLGE]   ↳ apply_trade: bad blob_hex, skipped")
            end
        elseif c.cmd == "ghost_pos" then
            if PG then PG.on_ghost_pos({ mg=c.gmg, mn=c.gmn, x=c.ggx, y=c.ggy, f=c.ggf,
                                         gfx=c.ggfx, mv=c.gmv, run=c.grun, an=c.gan,
                                         imgs=c.gimgs, anim=c.ganim, pcol=c.gpcol }) end
        elseif c.cmd == "hud_show" and c.text then
            hud_show(c.text, c.r or 255, c.g or 255, c.b or 255, c.frames or 300)
        elseif c.cmd == "gui_prompt" and c.text then
            -- Same routing as msgbox (the pre-stated requirement): a NATIVE in-game field box only in a
            -- safe area (patched, overworld, no field script/box already up, one box per pass), else the
            -- center-prompt overlay. gui_prompts are momentous overworld decisions (dupe / clause reroll),
            -- so the native box is the right in-game presentation; unpatched / in-battle / mid-dialogue
            -- falls back to the center prompt — never dropped.
            try_native_box(c.text, "prompt", "gui_prompt", c.r, c.g, c.b, c.frames)
        elseif c.cmd == "link_panel" and c.rows then
            -- The server sends this only when its content changed. Keep it and re-stage page 0, so
            -- the panel is always ready in EWRAM and opening the START-menu row needs no round-trip
            -- (that is the whole reason the patch opens it from the frame hook).
            INFO.rows = c.rows
            INFO.page = 0
            info_stage()
            console.log(string.format("[SLink-FRLGE]   link_panel: %d rows, %d page(s)",
                                      #c.rows, INFO.pages))
        elseif c.cmd == "resolved_areas" and c.areas then
            for _, a in ipairs(c.areas) do resolved_areas[a] = true end
            resolved_areas_seeded = true
            console.log(string.format("[SLink-FRLGE]   ↳ resolved_areas: %d areas seeded", #c.areas))
            -- Fire deferred encounter HUD if area_enter happened before seeding arrived.
            if pending_hud_area and not resolved_areas[pending_hud_area] then
                local disp = area_display(pending_hud_area)
                hud_show(">> New encounter: " .. disp, 80, 255, 120, 180)
            end
            pending_hud_area = nil
        elseif c.cmd == "config" then
            -- Per-run patch-feature config. overworld_presence OFF -> the patch's Pokémon-Center trade
            -- NPC is the trade entry point (gated by its own pc_trade_npc toggle); ON -> trades go
            -- through the peer ghost. native_messages / native_sounds pick the patch path over the Lua
            -- fallback; battle_calc drives the patch's calc kill-switch byte.
            if c.overworld_presence ~= nil then
                pc_npc_enabled = (c.overworld_presence == false) and (c.pc_trade_npc ~= false)
                -- Plain EWRAM write, safe pre-beacon (same as the boot-time set_pc_npc(false)):
                -- gating on patch_present() here dropped the enable when the config command
                -- raced the patch beacon (~frame 13). Also re-asserted on beacon return.
                if MB then MB.set_pc_npc(pc_npc_enabled) end
            end
            if c.native_messages ~= nil then native_msgs_enabled = (c.native_messages == true) end
            if c.native_sounds ~= nil then native_sfx_enabled = (c.native_sounds == true) end
            if c.battle_calc ~= nil then
                PP.calc = (c.battle_calc == true)
                if MB then MB.set_battle_calc(PP.calc) end
            end
            console.log(string.format(
                "[SLink-FRLGE]   ↳ config: presence=%s pc_npc=%s native_msgs=%s native_sfx=%s calc=%s",
                tostring(c.overworld_presence), tostring(pc_npc_enabled),
                tostring(native_msgs_enabled), tostring(native_sfx_enabled), tostring(c.battle_calc)))
        elseif c.cmd == "unresolve_area" and c.area_id then
            resolved_areas[c.area_id] = nil
            console.log("[SLink-FRLGE]   ↳ unresolve_area: "..c.area_id.." (species clause reroll)")
        elseif c.cmd == "game_over" then
            game_over_flag = true
            if M.playSE then M.playSE(M.SE_GAME_OVER) end
            HUD.set_game_over()
            console.log("[SLink-FRLGE]   ↳ GAME OVER — SOUL LINK")
        elseif c.cmd == "rebuild_start" then
            rebuild_active = true
            HUD.set_rebuilding(c.text or "REBUILDING TEAM")
            console.log("[SLink-FRLGE]   ↳ rebuild_start: "..tostring(c.text))
        elseif c.cmd == "rebuild_done" then
            rebuild_active = false
            HUD.clear_rebuilding()
            console.log("[SLink-FRLGE]   ↳ rebuild_done")
        elseif c.cmd ~= "noop" then
            console.log("[SLink-FRLGE]   ↳ cmd: "..tostring(c.cmd))
        end
    end
end

-- ── Send / receive ────────────────────────────────────────────────────────────
local seq            = 0
local pending_labels = {}

send = function(evt, label, is_auto, is_silent)
    if not C.connected() then
        console.log("[SLink-FRLGE] NOT CONNECTED — dropped: "..(label or evt.event))
        return
    end
    seq = seq + 1; evt.seq = seq; evt.player = PLAYER_ID
    C.send(json_encode(evt))
    local prefix = is_auto and "AUTO" or "MANUAL"
    local lbl    = (is_silent and "SILENT:" or "")..(prefix.." "..seq..": "..(label or evt.event))
    pending_labels[#pending_labels+1] = lbl
    if not is_silent then
        console.log(string.format("[SLink-FRLGE] [→] seq=%d  %s: %s", seq, prefix, label or evt.event))
    end
end

-- ── Per-frame helpers ─────────────────────────────────────────────────────────

-- Party-struct FLAGS byte (OFF_FLAGS) bits used by this client.
local FLAG_OCCUPIED = 0x02   -- slot holds a real mon (paired with maxHP > 0)
local FLAG_EGG      = 0x04   -- mon is an egg (NPC gifts + daycare)

-- Merged map lookup: one SB1 dereference for both area_id and loc_name.
local function current_area_loc()
    local g, n = M.getCurrentMap()
    return game_module.resolve_area(g, n), game_module.resolve_location(g, n)
end

-- Per-slot monKey cache: avoids string.format on every frame for unchanged slots.
local _mk_pers, _mk_otid, _mk_str = {}, {}, {}
-- Delta-based stats cache: only re-read stats when slot identity or level changes.
local _sc_key   = {}  -- [slot] → previous monKey string at this slot
local _sc_species = {}   -- per-slot species latch; see the invalidation gate in index_party
local _sc_level = {}  -- [slot] → previous level byte at this slot
local mon_stats_cache  = {}   -- key → {level, maxHP, attack, defense, speed, spAtk, spDef}
local function cachedMonKey(slot)
    local base = M.PARTY_BASE + slot * M.MON_SIZE
    local p = mem_u32(base + M.OFF_PERSONALITY)
    local o = mem_u32(base + M.OFF_OTID)
    if p == _mk_pers[slot] and o == _mk_otid[slot] then return _mk_str[slot] end
    local key = string.format("%08X:%08X", p, o)
    _mk_pers[slot] = p; _mk_otid[slot] = o; _mk_str[slot] = key
    return key
end

-- Double-buffer pool for index_party: avoids allocating new tables every frame.
-- Each buffer is a table of {hp, maxHP, level, slot} entries keyed by monKey.
-- CRITICAL: each buffer has its OWN entry pool so prev_party entries are not
-- overwritten when index_party populates curr_party.  Shared pooled entries
-- would make prev_info == curr_info (same object), breaking faint detection.
local _ip_buf = {{}, {}}
local _ip_idx = 1
local _ip_entry_pool = {{}, {}}
for _buf = 1, 2 do
    for _pi = 0, 5 do _ip_entry_pool[_buf][_pi] = {hp=0, maxHP=0, level=0, slot=0} end
end

local function index_party(battle_active)
    -- Swap buffers: current becomes the write target, previous is the read target
    _ip_idx = (_ip_idx == 1) and 2 or 1
    local t = _ip_buf[_ip_idx]
    local pool = _ip_entry_pool[_ip_idx]
    for k in pairs(t) do t[k] = nil end  -- clear reused buffer
    if M.PARTY_IN_SB1 and M.PARTY_BASE == 0 then return t, 0 end
    local count = mem_u8(M.PARTY_COUNT_ADDR)
    for i = 0, count - 1 do
        local base  = M.PARTY_BASE + i * M.MON_SIZE
        local flags = mem_u8(base + M.OFF_FLAGS)
        local maxHP = mem_u16(base + M.OFF_MAX_HP)
        if (flags & FLAG_OCCUPIED) ~= 0 and maxHP > 0 then
            local k  = cachedMonKey(i)
            local lv = mem_u8(base + M.OFF_LEVEL)
            local hp = mem_u16(base + M.OFF_HP)
            -- During battle, party struct HP is stale (game updates gBattleMons, not party).
            -- Use the persistent battle cache (survives mon switches).
            if battle_active then
                local bc = _battle_hp_cache[k]
                if bc then
                    hp    = bc.hp
                    maxHP = bc.maxHP
                    lv    = bc.level
                end
            end
            -- Reuse pooled entry table (per-buffer) to avoid per-frame allocation
            local entry = pool[i]
            entry.hp = hp; entry.maxHP = maxHP; entry.level = lv; entry.slot = i
            t[k] = entry
            -- Inline delta stats cache: only re-read combat stats when identity or level changes.
            -- Saves a separate 6-slot loop with redundant personality/otid/level reads.
            -- PP is read every frame because it changes on every move use, not just level-up.
            local st = mon_stats_cache[k]
            if not st then st = {}; mon_stats_cache[k] = st end
            -- Cache move PP every frame (4 bytes at Attacks substruct +8, i.e. data+0x2C+8=data+0x34)
            -- For CFRU (unencrypted fixed-order): directly at base+0x34
            -- For vanilla/AP: PP is inside encrypted substruct — skip (retrieveBoxMon handles it)
            if M.CFRU_NO_ENCRYPT then
                st.pp1 = mem_u8(base + 0x34)
                st.pp2 = mem_u8(base + 0x35)
                st.pp3 = mem_u8(base + 0x36)
                st.pp4 = mem_u8(base + 0x37)
            end
            -- Species is part of the invalidation key, not just identity + level. An evolution
            -- keeps the SAME key (personality/OT are untouched in Gen 3), and a stone or trade
            -- evolution does not change the level either — so gating on key+level alone left
            -- the cached Atk/Def/Spe/SpA/SpD at their pre-evolution values indefinitely.
            --
            -- WHERE the species change comes from depends on the ROM. On a patched ROM the
            -- EvRing pushes EV_EVOLVE and we read nothing here; unpatched, we read the species
            -- ourselves. This is the one place the ring genuinely REPLACES per-frame polling —
            -- and it has to, because per-frame Lua work in this client is not free: a 6-slot
            -- species read pushed the ghost duo's worst behind-stall from 2 frames to 5-7.
            local sp = _sc_species[i]
            if not EV.owns then sp = M.CFRU_NO_ENCRYPT and mem_u16(base + 0x20) or 0 end
            local dirty = EV.dirty[i]
            if dirty then EV.dirty[i] = nil; EV.dirtyN = EV.dirtyN - 1 end
            if dirty or k ~= _sc_key[i] or lv ~= _sc_level[i] or sp ~= _sc_species[i] then
                _sc_key[i] = k; _sc_level[i] = lv
                _sc_species[i] = EV.owns and mem_u16(base + 0x20) or sp
                st.level = lv; st.maxHP = maxHP
                st.attack  = mem_u16(base + 0x5A)
                st.defense = mem_u16(base + 0x5C)
                st.speed   = mem_u16(base + 0x5E)
                st.spAtk   = mem_u16(base + 0x60)
                st.spDef   = mem_u16(base + 0x62)
            end
        end
    end
    for slot = count, 5 do
        _sc_key[slot] = nil; _sc_level[slot] = nil; _sc_species[slot] = nil
    end
    return t, count
end

-- Per-monKey display data cache: full decrypt on first sight, then cheap
-- per-tick re-reads for fields that can change without a key_change:
-- species (evolution), nickname (Name Rater), held_item (give/take), and
-- ability (RR Ability Patch flips the hidden-ability bit in the encrypted
-- Misc substruct without touching personality).
local _display_cache = {}  -- key → {nickname, species_id, held_item_id, ability_id}

local function build_party_snapshot(battle_active)
    if M.PARTY_IN_SB1 and M.PARTY_BASE == 0 then return {} end
    -- Active battler detection (singles & doubles): primary path is gBattlerPartyIndexes
    -- via getBattlerForPartySlot(). Species+level match against gBattleMons[0] is kept
    -- as a fallback for when the index read is stale (e.g. CFRU address drift).
    local player_species, player_level, player_status = 0, 0, 0
    if battle_active and M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0 then
        player_species = mem_u16(M.BATTLE_MONS_ADDR + 0x00)
        player_level   = mem_u8(M.BATTLE_MONS_ADDR + 0x2A)
        -- Read live status from gBattleMons[0] — party struct status is stale during battle.
        player_status  = memory.read_u32_le(M.BATTLE_MONS_ADDR + M.BATTLE_MON_STATUS_OFF)
    end
    local is_doubles_battle = battle_active and M.isDoubleBattle()
    -- Bounds check on gBattlerPartyIndexes[0]: valid party slots are 0–5. A value
    -- ≥ 6 means the address is stale/wrong, in which case the species+level fallback
    -- is allowed to fire below.
    local indexes_trustworthy = false
    if battle_active and M.BATTLER_PARTY_INDEXES_ADDR then
        local idx0 = memory.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR)
        if idx0 < 6 then indexes_trustworthy = true end
    end
    local count = mem_u8(M.PARTY_COUNT_ADDR)
    local snap  = {}
    for i = 0, count - 1 do
        local base = M.PARTY_BASE + i * M.MON_SIZE
        if M.slotOccupied(base) then
            local k     = cachedMonKey(i)
            local hp    = mem_u16(base + M.OFF_HP)
            local maxHP = mem_u16(base + M.OFF_MAX_HP)
            local level = mem_u8(base + M.OFF_LEVEL)
            -- During battle, party struct HP is stale; use gBattleMons cache for live HP.
            if battle_active then
                local bc = _battle_hp_cache[k]
                if bc then
                    hp    = bc.hp
                    maxHP = bc.maxHP
                    level = bc.level
                end
            end
            -- Use cached display data; only full-decrypt if key is new or not cached.
            -- Always re-read held_item_id (cheap single-word decrypt) so give/take updates immediately.
            local dc = _display_cache[k]
            if not dc then
                local ok_ps, ps = pcall(M.readPartySlot, i)
                dc = {
                    nickname     = (ok_ps and ps and ps.nickname)     or "",
                    species_id   = (ok_ps and ps and ps.species_id)  or 0,
                    held_item_id = (ok_ps and ps and ps.held_item_id) or 0,
                    ability_id   = (ok_ps and ps and ps.ability_id)  or 0,
                }
                _display_cache[k] = dc
            else
                local ok_i, iid = pcall(M.decryptHeldItem, base)
                if ok_i then
                    dc.held_item_id = iid
                end
                -- Re-read species: changes on evolution (key stays the same in Gen 3).
                local ok_s, sid = pcall(M.decryptSpecies, base)
                if ok_s and sid and sid > 0 then dc.species_id = sid end
                -- Re-read nickname: it's unencrypted and cheap, and changes
                -- when the player uses the Name Rater or nicknames on capture.
                local ok_n, nick = pcall(M.readNickname, base)
                if ok_n and nick ~= "" then dc.nickname = nick end
                -- Re-read ability: RR's Ability Patch flips the hidden-ability
                -- bit without changing personality, so key_change never fires.
                local ok_a, aid = pcall(M.getAbilityId, base)
                if ok_a and aid and aid > 0 then dc.ability_id = aid end
            end
            -- Resolve ability: prefer gBaseStats, fall back to gBattleMons cache
            local final_aid = dc.ability_id
            if (not final_aid or final_aid == 0) and _ability_cache[k] then
                final_aid = _ability_cache[k]
            end
            -- Active battler detection (unified singles & doubles).
            -- Primary: getBattlerForPartySlot reads gBattlerPartyIndexes[0/2] — unambiguous.
            -- Fallback: species+level match against gBattleMons[0] when the index read
            -- appears stale (idx0 ≥ 6, e.g. CFRU address drift), preserving prior singles
            -- behaviour on profiles where gBattlerPartyIndexes can't be trusted.
            local active_battler_idx = nil
            if battle_active then
                local b = M.getBattlerForPartySlot(i)
                if b >= 0 then
                    active_battler_idx = b
                elseif not indexes_trustworthy and dc.species_id > 0
                        and dc.species_id == player_species and level == player_level then
                    active_battler_idx = 0
                end
            end
            local is_active = active_battler_idx ~= nil and dc.species_id > 0
            -- Status: use live gBattleMons value for the active battler; party struct otherwise.
            local status_cond = mem_u32(base + M.OFF_STATUS)
            if active_battler_idx == 0 and player_status ~= 0 then
                status_cond = player_status
            elseif active_battler_idx == 2
                    and M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0 then
                local b2s = memory.read_u32_le(
                    M.BATTLE_MONS_ADDR + 2 * M.BATTLE_MON_SIZE + M.BATTLE_MON_STATUS_OFF)
                if b2s ~= 0 then status_cond = b2s end
            end
            local stat_stages = active_battler_idx ~= nil
                                 and M.readStatStages(active_battler_idx) or nil
            -- Raw 100-byte party-mon blob hex-encoded for the Rival Team Swap
            -- feature.  Server caches the partner's blobs and forwards them on
            -- a rival fight via replace_rival_team for byte-copy into
            -- gEnemyParty.  Included on every snapshot (hello/tick/safe) — one
            -- channel instead of a parallel party_blob_sync event.
            local blob = M.readPartyBlob(i)
            local blob_hex = blob and M.bytesToHex(blob) or ""
            snap[#snap+1] = {key=k, hp=hp, maxHP=maxHP, level=level,
                             slot=i, active=is_active,
                             nickname=dc.nickname, species_id=dc.species_id,
                             held_item_id=dc.held_item_id, ability_id=final_aid or 0,
                             status_cond=status_cond, stat_stages=stat_stages,
                             blob_hex=blob_hex}
            -- Read moves + PP (cheap, re-read every tick for level-up/TM changes)
            local ok_mv, mv, pp = pcall(M.decryptMoves, base)
            if ok_mv and mv then
                snap[#snap].moves = mv
                snap[#snap].pp    = pp
            end
            local ok_pb, ppb = pcall(M.decryptPpBonuses, base)
            snap[#snap].pp_bonuses = (ok_pb and ppb) or 0
            if dc.nickname ~= "" or dc.species_id ~= 0 then
                nick_cache[k] = dc.nickname ~= "" and dc.nickname or ("#"..dc.species_id)
            end
        end
    end
    return snap
end

-- ── Incremental box scanner ──────────────────────────────────────────────────
-- Scans ceil(BOXES_PER_STORE / 7) boxes per tick, targeting a ~3.5 s full cycle
-- regardless of storage size (14 boxes → 2/tick; 25 boxes → 4/tick).
-- Accumulates results client-side; always sends full cache to server.
local _box_cache        = {}
local _box_next         = 0
local _boxes_per_tick   = math.max(2, math.ceil((M.BOXES_PER_STORE or 14) / 7))

-- Read the personality (PID, first 4 bytes) of each party slot 0..5.
-- Empty slots return 0.  No decryption needed — PID is the first u32 of the
-- struct and is never encrypted.
local function _read_party_pids()
    local p = {}
    for slot = 0, 5 do
        local ok, pid = pcall(memory.read_u32_le, M.PARTY_BASE + slot * M.MON_SIZE)
        p[slot] = ok and pid or 0
    end
    return p
end

local function _pids_diff_count(a, b)
    local n = 0
    for i = 0, 5 do
        if (a[i] or 0) ~= (b[i] or 0) then n = n + 1 end
    end
    return n
end

local function _pids_all_match(a, b)
    for i = 0, 5 do
        if (a[i] or 0) ~= (b[i] or 0) then return false end
    end
    return true
end

-- Returns true if the diff between curr and stable is explainable by a normal
-- party compaction (deposit, withdrawal, or party-menu reorder).
--
-- Phase B: returns the set-symmetric-difference rule (added<=1 and removed<=1).
-- Legacy rule is computed alongside for diagnostic logging — disagreements
-- surface in the console for surveillance.  Empirically the new rule rejects
-- mid-swap intermediate frames (added=0, removed>=3) that the legacy rule
-- accepts, eliminating the BUG-2 baseline corruption pattern.
local function _is_compaction_shift(curr, stable)
    local stable_set, curr_set = {}, {}
    for i = 0, 5 do
        local p = stable[i] or 0
        if p ~= 0 then stable_set[p] = true end
        local q = curr[i] or 0
        if q ~= 0 then curr_set[q] = true end
    end
    local old_result = true
    for p in pairs(curr_set) do
        if not stable_set[p] then old_result = false; break end
    end
    local added, removed = 0, 0
    for p in pairs(curr_set) do
        if not stable_set[p] then added = added + 1 end
    end
    for p in pairs(stable_set) do
        if not curr_set[p] then removed = removed + 1 end
    end
    local new_result = (added <= 1 and removed <= 1)
    if old_result ~= new_result then
        console.log(string.format(
            "[SLink-FRLGE] [DIAG] _is_compaction_shift reclassification: "
            .. "old=%s new=%s added=%d removed=%d",
            tostring(old_result), tostring(new_result), added, removed))
    end
    return new_result
end

-- Validate that box storage is accessible and currentBox is in range.
-- Returns true if safe to scan; false during transitions/menus.
local function _box_ptr_valid()
    if M.CFRU_BOX_BASES then
        -- CFRU: static EWRAM addresses, just validate currentBox range
        local cur_box = memory.read_u8(M.POKEMON_STORAGE_BASE)
        return cur_box < M.BOXES_PER_STORE
    end
    if M.BOX_SB1_OFFSET then
        -- DPE legacy: SB1-relative boxes
        local sb1 = memory.read_u32_le(M.SB1_PTR_ADDR)
        return sb1 >= 0x02000000 and sb1 < 0x02040000
    end
    if not M.PSP_PTR_ADDR or M.PSP_PTR_ADDR == 0 then return false end
    local psp = memory.read_u32_le(M.PSP_PTR_ADDR)
    if psp < 0x02000000 or psp >= 0x02040000 then return false end
    local cur_box = memory.read_u8(psp)
    if cur_box >= M.BOXES_PER_STORE then return false end
    return true
end

local function scan_next_boxes()
    -- Guard: skip scan when the storage pointer is invalid (save not loaded,
    -- title screen, or mid-transition garbage) — mirrors party_diff_ok gate.
    if not _box_ptr_valid() then return _box_cache end
    for _ = 1, _boxes_per_tick do
        local boxIdx = _box_next
        -- Remove stale entries for this box (in-place to avoid table allocation)
        local j = 1
        for i = 1, #_box_cache do
            if _box_cache[i].box ~= boxIdx then
                _box_cache[j] = _box_cache[i]; j = j + 1
            end
        end
        for i = j, #_box_cache do _box_cache[i] = nil end
        -- Scan this box
        for slotIdx = 0, M.MONS_PER_BOX - 1 do
            local addr = M.boxMonAddr(boxIdx, slotIdx)
            if M.boxSlotOccupied(addr) then
                local k = M.monKey(addr)
                -- Use display cache; only full-decrypt if key is new or not cached.
                -- Always re-read held_item_id so give/take updates immediately.
                local dc = _display_cache[k]
                if not dc then
                    local nick, sid, iid = M.readBoxSlotDisplay(addr, true)
                    local ok_a, aid = pcall(M.getBoxAbilityId, addr)
                    dc = {nickname=nick, species_id=sid, held_item_id=iid,
                          ability_id=(ok_a and aid) or 0}
                    _display_cache[k] = dc
                else
                    local ok_i, iid = pcall(M.decryptBoxHeldItem, addr)
                    if ok_i then dc.held_item_id = iid end
                    local ok_n, nick = pcall(M.readNickname, addr)
                    if ok_n and nick ~= "" then dc.nickname = nick end
                    -- Re-read ability: RR's Ability Patch flips the hidden-
                    -- ability bit without changing personality.
                    local ok_a, aid = pcall(M.getBoxAbilityId, addr)
                    if ok_a and aid and aid > 0 then dc.ability_id = aid end
                end
                local box_aid = dc.ability_id
                if (not box_aid or box_aid == 0) and _ability_cache[k] then
                    box_aid = _ability_cache[k]
                end
                _box_cache[#_box_cache + 1] = {
                    box = boxIdx, slot = slotIdx, key = k,
                    nickname = dc.nickname, species_id = dc.species_id,
                    held_item_id = dc.held_item_id, ability_id = box_aid or 0,
                }
                -- Read moves from box slot (no PP for CFRU CompressedPokemon)
                local ok_bm, bm = pcall(M.decryptBoxMoves, addr)
                if ok_bm and bm then
                    _box_cache[#_box_cache].moves = bm
                end
            end
        end
        _box_next = _box_next + 1
        if _box_next >= M.BOXES_PER_STORE then _box_next = 0 end
    end
    return _box_cache
end

-- ── Per-frame state ───────────────────────────────────────────────────────────
local initialized     = false
local was_connected   = false
local prev_area, prev_loc = current_area_loc()
local prev_party      = index_party()
local prev_in_battle  = M.isInBattle()
local prev_keys       = {}

local TICK_INTERVAL    = 30   -- auto tick every 30 frames (~0.5 s)


-- Battle-scoped capture / no_catch tracking:
local battle_area_id       = nil
local battle_is_wild       = false
local captured_this_battle = false

-- Rival Team Swap: trainer_battle_start emitter state.  Reset on battle end.
-- gTrainerBattleOpponent_A is set in stages during CFRU battle init, so we
-- require the same trainer ID to read back identically for TRAINER_STABLE_GATE
-- consecutive frames before emitting.  Send exactly once per battle.
local trainer_battle_sent   = false
local trainer_last_id       = 0
local trainer_stable_frames = 0
local TRAINER_STABLE_GATE   = 2
local battle_box_index     = nil
local battle_box_snapshot  = {}   -- {[slotIdx] = true} occupied slots at battle start
local battle_box_slot_count = 0   -- number of occupied slots at battle start
local post_battle_frames   = 0
local pending_safe         = false
local POST_BATTLE_GRACE    = 90  -- 1.5s; CFRU needs longer for catch/exp/level-up animations
-- Extra cooldown before memorialize is allowed to run after a battle.
-- CFRU may continue writing party data (HP restoration, party sync from gBattleParty)
-- for several frames after the general post_battle_frames window expires.
-- Without this guard, the swap-to-end in memorializeMon can fire while the engine
-- is still writing, causing the moved mon to inherit the dead mon's item/data.
local memorialize_battle_cooldown = 0
local MEMORIALIZE_POST_BATTLE_COOLDOWN = 180  -- 3s at 60fps
-- Safety cap before any sync write is allowed after EOB-clear.
-- The primary gate is M.isPostBattleSettled() (gTasks + gMain.callback2);
-- this counter is a "predicate should have fired by now" backstop in case
-- the profile lacks the new addresses (Task_GiveExpToMon needs runtime
-- discovery on each CFRU build — see test_post_eob_settle_discovery.lua)
-- or a discovered address is wrong. 10 s at 60fps. Hit means the
-- discovery values for the active profile need attention.
local post_eob_frames     = 0
local POST_EOB_SAFETY_CAP = 600  -- 10s at 60fps; was 180 (3s) prior to gTasks gate
-- Accumulates enemy mons seen during the current trainer battle.
-- Keyed by "species_id:level" to deduplicate.  Reset on battle start.
local battle_seen_enemies  = {}  -- key → {species_id, level, hp, maxHP}
-- Borrowed-party protection: true while the game has replaced gPlayerParty with
-- another trainer's mons (Poké Dude, in-game partner, mock battles).  All party
-- diffing, capture, faint, and sync detection is frozen until the battle ends.
local borrowed_battle      = false
local pre_borrowed_party   = nil  -- snapshot of real party before the swap

-- Borrowed-party swap detection.
-- Primary signal: PID-based detector below.  Watches the first 4 bytes
-- (personality value) of each party slot every frame; triggers when N slots
-- differ from the "stable" snapshot (party that's been unchanged for
-- PID_STABILITY_WINDOW frames).  Auto-releases when ALL slots revert to the
-- pre-swap snapshot — covers both mid-overworld menu backouts and the
-- engine's post-battle party restore.
--
-- Discovered via lua/tests/test_battle_facility_flag_discovery.lua on RR
-- scripted-trainer-preset-party battles: gBattleTypeFlags shows only
-- TRAINER|IS_MASTER (0x0C) and no SaveBlock1 flag fires, so the
-- party-PID mass change is the only authoritative signal.
--
-- The gift_capture_buffer below remains as a 45-frame DELIVERY DELAY for
-- normal captures (so events can be cancelled if a swap retroactively
-- starts).  The buffer no longer triggers freeze on its own.
local party_frozen          = false
local freeze_frames_left    = 0

local FREEZE_TIMEOUT_FRAMES = 3600 -- 60s failsafe
local POST_UNFREEZE_SETTLE  = 15   -- ~0.25s for game to restore real party after unfreeze
local post_unfreeze_frames  = 0    -- countdown: suppress party diffs while settling
local pending_freeze_release = false  -- trigger condition met; waiting for eob_clear
local freeze_release_reason  = nil   -- reason string for unfreeze log
local gift_capture_buffer   = {}   -- buffered captures: {key,hp,maxHP,level,area,nickname,species_id,held_item_id,frame}
local GIFT_BUFFER_WINDOW    = 45   -- hold captures for ~0.75s so a late swap can cancel them

-- Buffered party_to_box events.  The PID detector fires within 2-3 frames of
-- a borrowed-party swap starting, but the per-key diff loop can see slot-0's
-- previous mon "disappear" on frame 1 of the swap (slot rewrite) and would
-- otherwise emit a spurious party_to_box.  Holding for PARTY_TO_BOX_BUFFER_WINDOW
-- frames lets the PID detector catch up and discard the buffer before it flushes.
-- Also protects against transient 1-frame party RAM glitches (CFRU animation
-- write-backs, DMA, script engine states) that cause mons to briefly "disappear."
local party_to_box_buffer   = {}   -- buffered deposits: {key, stats, frame}
local PARTY_TO_BOX_BUFFER_WINDOW = 5  -- ~83ms — long enough for PID detector to fire

-- Buffered box_to_party events.  Mirrors party_to_box_buffer: a known key must
-- remain present in the party for BOX_TO_PARTY_BUFFER_WINDOW consecutive frames
-- before the event is sent.  Prevents false "withdrawal" events from 1-frame
-- party RAM glitches where mons transiently appear then vanish.
local box_to_party_buffer    = {}   -- buffered withdrawals: {key, frame}
local BOX_TO_PARTY_BUFFER_WINDOW = 5  -- ~83ms — matches party_to_box window

-- PID-based swap detector state
local PID_SWAP_THRESHOLD     = 3   -- ≥N slots changed since stable = swap
local PID_STABILITY_WINDOW   = 30  -- frames of no PID change before re-snapshot
local _last_party_pids       = {[0]=0,[1]=0,[2]=0,[3]=0,[4]=0,[5]=0}
local _last_pid_change_frame = 0
local _stable_party_pids     = {[0]=0,[1]=0,[2]=0,[3]=0,[4]=0,[5]=0}
local pre_swap_pids          = nil -- pre-swap snapshot used for revert detection
-- CFRU/RR real-party backup buffer (M.REAL_PARTY_BACKUP_ADDR).  Only used
-- for REVERT detection during an active freeze — the engine saves the real
-- party here before a borrowed-party swap, so "live == backup" is the
-- authoritative unfreeze signal.  NOT used for freeze triggering (it goes
-- stale between swaps; _stable_party_pids is the freeze baseline).
local _backup_trusted        = false
-- Authoritative borrowed-party signal from the companion patch (SwapState @ 0x0203F840).
-- When the patch is present it flags the EXACT frame CFRU backs up the real party (a swap
-- begin) by bumping `seq`, and clears `active` on restore — frame-exact and threshold-free.
-- On RR-with-patch this REPLACES the ≥3-PID-change trigger above (which false-positives on
-- compaction); the PID heuristic stays as the fallback for vanilla/AP and unpatched ROMs.
-- `_last_swap_seq` is lazily seeded so the first observation never counts as a begin edge.
local _last_swap_seq         = nil

-- Per-session:
local all_known_keys   = {}   -- all keys ever seen in party or box
local sync_cooldown        = 0
local SYNC_COOLDOWN_FRAMES = 30
local GIFT_COOLDOWN_FRAMES = 1800 -- 30s for naming dialog after gift/starter
local _sync_blocked_logged = false  -- one-shot: log once when entering blocked state
-- Pokéball gate: no_catch suppressed until player enters a non-gift encounter area.
-- Gift area classification now handled by game_module.is_gift_area()
local nuzlocke_active = false


-- ── Sync write helpers ─────────────────────────────────────────────────────────
local function exec_box_mon(key)
    local count = memory.read_u8(M.PARTY_COUNT_ADDR)
    -- Never deposit the last party mon — game crashes with 0 party mons.
    if count <= 1 then
        console.log("[SLink-FRLGE] ✗ box_mon skipped: " .. key:sub(1,8) .. " (last mon in party)")
        hud_show("! Only mon!", 255, 200, 60, 240)
        return
    end
    for slot = 0, count - 1 do
        local base = M.PARTY_BASE + slot * M.MON_SIZE
        if M.slotOccupied(base) and M.monKey(base) == key then
            -- Read stats before depositing; party-only bytes are zeroed by depositPartyMon.
            local stats = {
                level   = memory.read_u8(base + M.OFF_LEVEL),
                maxHP   = memory.read_u16_le(base + M.OFF_MAX_HP),
                attack  = memory.read_u16_le(base + 0x5A),
                defense = memory.read_u16_le(base + 0x5C),
                speed   = memory.read_u16_le(base + 0x5E),
                spAtk   = memory.read_u16_le(base + 0x60),
                spDef   = memory.read_u16_le(base + 0x62),
            }
            -- Capture move PP so retrieval can restore it (CFRU compressed box loses PP)
            if M.CFRU_NO_ENCRYPT then
                stats.pp1 = memory.read_u8(base + 0x34)
                stats.pp2 = memory.read_u8(base + 0x35)
                stats.pp3 = memory.read_u8(base + 0x36)
                stats.pp4 = memory.read_u8(base + 0x37)
            end
            -- Cache stats on the server so an UNPATCHED partner's Lua withdraw can restore them
            -- (the native withdraw recomputes everything, so it ignores these). Sent for both paths.
            send({event="stats_cache", key=key, stats=stats},
                 "stats_cache:"..key:sub(1,8), true, true)
            -- NATIVE deposit (companion patch preferred): the patch does the compressed write; Lua only
            -- locates a free box slot. Async — settled in on_frame §4a-quinque (Lua fallback on failure).
            if patch_present() then
                local bx, px = M.findEmptyBoxSlot()
                if bx then
                    sync_written_keys[key] = true
                    local seq = MB.deposit_mon(slot, bx, px)
                    if seq then
                        pending_storage = {mode = "deposit", key = key, slot = slot, box = bx,
                                           pos = px, stats = stats, seq = seq, start_frame = frame_count}
                        return "pending"
                    end
                end
                -- no free slot / send failed → fall through to the proven Lua path
            end
            local bi, si, err = M.depositPartyMon(slot)
            if bi then
                console.log(string.format("[SLink-FRLGE] ✓ box_mon: %s → box%d s%d", key:sub(1,8), bi, si))
                sync_written_keys[key] = true
                hud_show("↓ " .. nick_label(key) .. " boxed", 100, 180, 255, 200)
            else
                console.log("[SLink-FRLGE] ✗ box_mon failed: "..(err or "?").."  key="..key:sub(1,8))
                hud_show("X Box fail: " .. nick_label(key), 255, 80, 80, 240)
            end
            return
        end
    end
    -- Not in party — check if already in a box (desired state already met).
    local bi, si = M.scanBoxForKey(key)
    if bi then
        console.log(string.format("[SLink-FRLGE] box_mon: %s already in box%d s%d — skipping", key:sub(1,8), bi, si))
        sync_written_keys[key] = true
    else
        console.log("[SLink-FRLGE] box_mon: "..key:sub(1,8).." not found in party or boxes")
    end
end

local function exec_party_mon(key, stats)
    -- If the mon is already in the party, the desired state is already met.
    local count = memory.read_u8(M.PARTY_COUNT_ADDR)
    for slot = 0, count - 1 do
        local base = M.PARTY_BASE + slot * M.MON_SIZE
        if M.slotOccupied(base) and M.monKey(base) == key then
            console.log("[SLink-FRLGE] party_mon: "..key:sub(1,8).." already in party — skipping")
            sync_written_keys[key] = true
            -- Still confirm retrieval so server updates party_keys.
            send({event="sync_retrieve_done", key=key},
                 "sync_retrieve_done:"..key:sub(1,8), true, true)
            return
        end
    end
    -- NATIVE withdraw (companion patch preferred): the engine recomputes level/stats/PP, so it works
    -- even without server-cached stats. Lua only locates the box slot holding the key. Async — settled
    -- in on_frame §4a-quinque (Lua fallback on failure).
    if patch_present() then
        local count = memory.read_u8(M.PARTY_COUNT_ADDR)
        local bx, px = M.scanBoxForKey(key)
        if bx and count < 6 then
            sync_written_keys[key] = true
            all_known_keys[key]    = true
            local seq = MB.withdraw_mon(bx, px, count)
            if seq then
                pending_storage = {mode = "withdraw", key = key, slot = count, box = bx,
                                   pos = px, stats = stats, seq = seq, start_frame = frame_count}
                return "pending"
            end
        end
        -- not in a box / party full / send failed → fall through to the proven Lua path
    end
    -- Fail closed: refuse to retrieve without valid stats (prevents zero-stat crash).
    if not stats or not stats.level or stats.level <= 0
       or not stats.maxHP or stats.maxHP <= 0 then
        console.log("[SLink-FRLGE] ✗ party_mon: no valid stats for "..key:sub(1,8).." — manual retrieval needed")
        hud_show("! Unbox " .. nick_label(key), 255, 200, 60, 600)
        send({event="sync_retrieve_failed", key=key},
             "sync_retrieve_failed:"..key:sub(1,8), true, true)
        return
    end
    if count >= 6 then
        -- Party full — a preceding box_mon should free a slot. Re-queue to retry
        -- (up to 3 attempts) instead of giving up immediately.
        local retries = stats and stats._retries or 0
        if retries < 3 then
            local retry_stats = {}
            for k, v in pairs(stats) do retry_stats[k] = v end
            retry_stats._retries = retries + 1
            table.insert(pending_sync_cmds, {cmd="party_mon", key=key, stats=retry_stats})
            console.log("[SLink-FRLGE] party_mon: party full for "..key:sub(1,8).." — re-queued (attempt "..(retries+1).."/3)")
            return
        end
        -- Exhausted retries — genuine full party, notify server.
        console.log("[SLink-FRLGE] ✗ party_mon: party still full after 3 retries for "..key:sub(1,8))
        hud_show("! Unbox " .. nick_label(key), 255, 200, 60, 600)
        send({event="sync_retrieve_failed", key=key},
             "sync_retrieve_failed:"..key:sub(1,8), true, true)
        return
    end
    local ok, err = M.retrieveBoxMon(key, stats)
    if ok then
        console.log("[SLink-FRLGE] ✓ party_mon: "..key:sub(1,8).." added to party (full heal)")
        sync_written_keys[key] = true
        all_known_keys[key]    = true  -- prevent false gift-capture on subsequent frames
        -- Populate nick_cache from the retrieved mon's actual nickname in RAM
        local ok_n, nick = pcall(M.readNickname, ret_base)
        if ok_n and nick and nick ~= "" then nick_cache[key] = nick end
        hud_show("↑ " .. nick_label(key) .. " unboxed", 100, 255, 160, 200)
        -- Notify server so it can update its party_keys for this player.
        send({event="sync_retrieve_done", key=key},
             "sync_retrieve_done:"..key:sub(1,8), true, true)
    else
        console.log("[SLink-FRLGE] ✗ party_mon failed: "..(err or "?").."  key="..key:sub(1,8))
        hud_show("! Unbox " .. nick_label(key), 255, 200, 60, 600)
        send({event="sync_retrieve_failed", key=key},
             "sync_retrieve_failed:"..key:sub(1,8), true, true)
    end
end

-- Shared memorialize epilogue (both the Lua RAM-poke path and the native OP_MEMORIALIZE poll land
-- here): verify the move, notify the HUD + server, rename overflow boxes.
local function memorialize_finish(key, bi, si, pre_count)
    local post_count = memory.read_u8(M.PARTY_COUNT_ADDR)
    local still_in_party = false
    for slot = 0, post_count - 1 do
        local base = M.PARTY_BASE + slot * M.MON_SIZE
        if M.monKey(base) == key then still_in_party = true; break end
    end
    local in_memorial = M.boxMonKey(bi, si) == key

    console.log(string.format("[SLink-FRLGE] ✓ memorialize: %s → box%d s%d  count=%d→%d  gone=%s  in_box=%s",
        key:sub(1, 8), bi, si, pre_count, post_count,
        tostring(not still_in_party), tostring(in_memorial)))

    if still_in_party then
        console.log("[SLink-FRLGE] ⚠ memorialize VERIFY FAIL: key still in party after memorialize!")
    end

    hud_show("† " .. nick_label(key) .. " buried", 255, 140, 40, 300)
    send({event="memorialize_done", key=key, box=bi}, "memorialize_done:"..key:sub(1,8), true)
    -- Rename overflow boxes (Box 12 → "DEAD 2", Box 11 → "DEAD 3", etc.)
    if bi ~= M.MEMORIAL_BOX and not memorial_overflow_renamed[bi] then
        local n = M.MEMORIAL_BOX - bi + 1  -- Box 12→2, Box 11→3, ...
        pcall(M.renameBox, bi, "DEAD " .. n)
        memorial_overflow_renamed[bi] = true
        console.log(string.format("[SLink-FRLGE] Overflow box %d renamed to 'DEAD %d'", bi, n))
    end
    return not still_in_party and in_memorial
end

local function exec_memorialize(key)
    -- Drain any stale box_mon/party_mon for this key from the queue
    local filtered = {}
    for _, c in ipairs(pending_sync_cmds) do
        if not (c.key == key and (c.cmd == "box_mon" or c.cmd == "party_mon")) then
            filtered[#filtered + 1] = c
        end
    end
    pending_sync_cmds = filtered

    -- Log pre-state for diagnostics
    local pre_count = memory.read_u8(M.PARTY_COUNT_ADDR)
    console.log(string.format("[SLink-FRLGE] memorialize: key=%s partyCount=%d", key:sub(1,8), pre_count))

    -- NATIVE fast path (companion patch, party-resident mon only): OP_MEMORIALIZE does the
    -- compress + zero + swap-with-last in one frame-hook pass — no multi-frame Lua RAM-poke window
    -- for CFRU's deferred writes to race. ASYNC like deposit/withdraw: return "pending"; the
    -- §4a-sexies poll runs memorialize_finish (or falls back to the Lua path below on failure).
    -- Box-resident mons (died while boxed) always take the Lua path — it scans boxes too.
    if patch_present() and not memorialize_native_disabled
       and not pending_storage and not pending_memorialize then
        local count = memory.read_u8(M.PARTY_COUNT_ADDR)
        local pslot = nil
        for slot = 0, count - 1 do
            if M.monKey(M.PARTY_BASE + slot * M.MON_SIZE) == key then pslot = slot; break end
        end
        if pslot then
            local bi, si = M.findFreeMemorialSlot()
            if bi then
                local seq = MB.memorialize_mon(pslot, bi, si)
                if seq then
                    pending_memorialize = {key = key, box = bi, slot = si, pre_count = count,
                                           seq = seq, start_frame = frame_count}
                    console.log(string.format(
                        "[SLink-FRLGE]   ↳ native OP_MEMORIALIZE armed: slot=%d → box%d s%d seq=%d",
                        pslot, bi, si, seq))
                    return "pending"
                end
            end
        end
    end

    local bi, si = M.memorializeMon(key)
    if bi then
        memorialize_finish(key, bi, si, pre_count)
    else
        console.log("[SLink-FRLGE] ✗ memorialize failed: "..tostring(si).."  key="..key:sub(1,8))
        hud_show("X Mem fail: " .. nick_label(key), 255, 80, 80, 300)
        send({event="memorialize_failed", key=key, reason=si},
             "memorialize_failed:"..key:sub(1,8), true)
    end
end

-- ── Main frame handler ────────────────────────────────────────────────────────
-- Seed all_known_keys from every non-memorial PC box, so mons withdrawn while
-- the client was offline are recognized as box_to_party rather than false gift
-- captures. Memorial/overflow boxes are skipped — dead mons must never block a
-- future same-PID capture. Shared by the connect handler and the startup seed.
local function seed_known_keys_from_boxes()
    for boxIdx = 0, (M.BOXES_PER_STORE or 14) - 1 do
        if boxIdx ~= M.MEMORIAL_BOX and not memorial_overflow_renamed[boxIdx] then
            for slotIdx = 0, M.MONS_PER_BOX - 1 do
                local bk = M.boxMonKey(boxIdx, slotIdx)
                if bk and bk ~= "0:0" then
                    all_known_keys[bk] = true
                end
            end
        end
    end
end

local function on_frame()
    frame_count = frame_count + 1

    -- 0a. Refresh ASLR-dependent party addresses (no-op for vanilla/AP)
    M.refreshPartyAddrs()

    -- 0b. Re-validate writes if previously disabled (save may load after script start)
    if not writes_enabled then
        local ok, err = M.validateROM()
        if ok then
            writes_enabled = true
            console.log("[SLink-FRLGE] ✓ ROM validation passed — writes enabled")
        end
    end

    -- Rename memorial box once after writes are first enabled
    if writes_enabled and not memorial_box_renamed then
        local ok, err = pcall(M.renameBox, M.MEMORIAL_BOX, "THE DEAD")
        if ok then
            memorial_box_renamed = true
            console.log("[SLink-FRLGE] Memorial box renamed to 'THE DEAD'")
        end
    end

    -- 0c. Drain the patch's event ring (faint-settled / battle-outcome edges pushed natively each
    -- frame) into the fast-path credits consumed by the faint debounce + whiteout detectors below
    -- (ROADMAP §3). The per-frame Lua polls remain the unpatched fallback / safety net.
    if patch_present() then
        local evs, ovf = MB.events_drain()
        for _, e in ipairs(evs) do
            if e.type == MB.EV_PLAYER_FAINT then
                ev_faint_credit = ev_faint_credit + 1
                console.log("[SLink-FRLGE] [ev] player faint settled (counter=" .. e.a ..
                            ", credit=" .. ev_faint_credit .. ")")
            elseif e.type == MB.EV_FOE_FAINT then
                console.log("[SLink-FRLGE] [ev] foe faint settled (counter=" .. e.a .. ")")
            elseif e.type == MB.EV_OUTCOME then
                if e.a == 2 then ev_outcome_loss = true end
                console.log("[SLink-FRLGE] [ev] battle outcome=" .. e.a ..
                            (e.a == 2 and " (LOSS/whiteout)" or ""))
            elseif e.type == MB.EV_PARTY_ADD then
                local slot = e.a - 1                      -- a = the NEW count; the slot that appeared
                if slot >= 0 and slot <= 5 and not EV.dirty[slot] then
                    EV.dirty[slot] = true; EV.dirtyN = EV.dirtyN + 1
                end
                EV.add[#EV.add + 1] =
                    { want = e.a, frame = frame_count, label = "party_add" }
                EV.pendingN = EV.pendingN + 1
                console.log("[SLink-FRLGE] [ev] party grew to " .. e.a .. " (species=" .. e.b .. ")")
            elseif e.type == MB.EV_EVOLVE then
                if e.a <= 5 and not EV.dirty[e.a] then
                    EV.dirty[e.a] = true; EV.dirtyN = EV.dirtyN + 1
                end
                ev_expect(EV.evolve, e.a, e.b, "evolve")
                console.log("[SLink-FRLGE] [ev] slot " .. e.a .. " evolved to species " .. e.b)
            end
        end
        if ovf then console.log("[SLink-FRLGE] [ev] ⚠ event ring overflowed (events dropped)") end
    end

    -- 1. Drive TCP pump
    C.pump()

    -- 2. Connection state change → send hello on (re)connect
    local now_connected = C.connected()
    if now_connected ~= was_connected then
        if now_connected then
            console.log("[SLink-FRLGE] [TCP] connected to "..SERVER_HOST..":"..SERVER_PORT)
            -- Mid-run reconnect: check actual bag contents to determine nuzlocke gate.
            -- Must run BEFORE building the party snapshot so reconnects include real data.
            if M.hasPokeballs() then
                nuzlocke_active = true
                console.log("[SLink-FRLGE] nuzlocke ACTIVE (pokeballs already in bag at startup)")
            end
            -- Only build a real party snapshot when save data looks valid.
            -- During intro (title screen, cutscenes), gPlayerPartyCount may be garbage (>6).
            -- Skip snapshot during borrowed-party battles (RR mock/Poké Dude) — the party in
            -- RAM belongs to the NPC, not the player. Sending it would corrupt identity lock.
            local raw_count = memory.read_u8(M.PARTY_COUNT_ADDR)
            local save_loaded = raw_count >= 0 and raw_count <= 6
            local snap = (save_loaded and not borrowed_battle) and build_party_snapshot(false) or {}
            -- Seed all_known_keys from current party on connect
            for k in pairs(prev_party) do all_known_keys[k] = true end
            -- Seed all_known_keys from PC boxes so withdrawn mons are recognized
            -- as box_to_party, not false gift captures.
            seed_known_keys_from_boxes()
            local h_area, h_loc = current_area_loc()
            send({event="hello", area_id=h_area, loc_name=h_loc,
                  rom_type=rom_type,
                  writes_enabled=writes_enabled, has_pokeballs=M.hasPokeballs(),
                  ball_count=M.countPokeballs(),
                  badges=(function() local ok,n,bm=pcall(M.readBadges); return ok and bm or 0 end)(),
                  trainer_name=(function() local ok,v=pcall(M.readTrainerName); return ok and v or "" end)(),
                  party=snap}, "hello", true)
            -- Log party keys so they can be used with inject_link_by_slot or inject_link
            if #snap > 0 then
                for i, m in ipairs(snap) do
                    console.log(string.format("[SLink-FRLGE] party[%d] key=%s level=%d maxHP=%d",
                        i-1, m.key or "?", m.level or 0, m.maxHP or 0))
                end
            else
                console.log("[SLink-FRLGE] party: empty (no mons with maxHP>0)")
            end
            initialized = true
        else
            console.log("[SLink-FRLGE] [TCP] disconnected — reconnecting…")
        end
        was_connected = now_connected
    end

    -- 3a-bis. Drain the mailbox outbox: the single-slot mailbox takes one opcode per frame,
    -- extra sends from a batched dispatch queue in mailbox.lua and are posted here as the
    -- hook frees the slot (pump BEFORE dispatch so last frame's consumption is seen first).
    if MB then MB.pump() end

    -- 3b. Dispatch received responses (may enqueue sync cmds)
    while true do
        local line = C.receive()
        if not line then break end
        local label = table.remove(pending_labels, 1) or "?"
        local cmds  = parse_command_list(line)
        if label:sub(1,7) ~= "SILENT:" then
            console.log("[SLink-FRLGE] [←] "..label.." → "..format_cmds(cmds))
        end
        dispatch_commands(cmds)
    end

    if not initialized then return end

    -- One-shot companion-patch detection log (RR only — the patch is RR-specific). The
    -- native beacon at 0x0203F800 appears a few frames after boot, so latch on the first
    -- positive detection; if still absent after a grace window, announce fallback once.
    -- Native SOULLINK panel. The row is turned on only once the patch is actually present (an
    -- unpatched ROM has no menu to splice into), and only once there is something to show — a row
    -- that opens an empty box is worse than no row.
    if IS_RR and MB and patch_present() then
        if not INFO.enabled and INFO.rows then
            MB.set_info_enable(true); INFO.enabled = true
            console.log("[SLink-FRLGE] SOULLINK menu row enabled")
        end
        -- Pagination. The patch publishes A (0) / B (0x7F) into gSpecialVar_Result when the panel
        -- closes, and drive_info re-opens on an `opened` bump — so paging is: notice the panel
        -- closed, and if it closed with A and there is another page, stage it and bump `opened`.
        local drawn = memory.read_u8(MB.INFO_DRAWN)
        if INFO.drawn == nil then INFO.drawn = drawn end
        if drawn ~= INFO.drawn then INFO.drawn = drawn; INFO.showing = true end
        if INFO.showing and memory.read_u8(0x03000F9C) == 0 then
            INFO.showing = false
            if memory.read_u16_le(0x020370D0) == 0 and INFO.pages > 1 then   -- A = next page
                INFO.page = (INFO.page + 1) % INFO.pages
                info_stage()
                -- Re-arm the patch's frame-hook open by bumping the counter it watches.
                memory.write_u8(MB.INFO_OPENED, (memory.read_u8(MB.INFO_OPENED) + 1) % 256)
            else
                INFO.page = 0
                info_stage()      -- closed with B: next open starts at page 1 again
            end
        end
    end

    if IS_RR and not patch_logged then
        if patch_present() then
            console.log("[SLink-FRLGE] companion patch: PRESENT — native features enabled")
            patch_logged = true
        elseif frame_count > 180 then
            console.log("[SLink-FRLGE] companion patch: absent — RAM-poke fallback (unpatched ROM)")
            patch_logged = true
        end
    end
    -- Re-assert the config-driven patch bytes whenever the beacon comes (back) up: a soft
    -- reset clears EWRAM (TN_ENABLE -> 0, CALC_OFF -> 0) while the TCP connection — and thus
    -- the one-shot `config` command — survives, so without this the PC trade NPC stays dead
    -- and a --no-battle-calc run silently re-enables the calc for the rest of the session.
    if IS_RR then
        local pp = patch_present()
        if pp and not PP.was then
            if MB then MB.set_pc_npc(pc_npc_enabled); MB.set_battle_calc(PP.calc) end
            if PP.was == false then
                console.log("[SLink-FRLGE] patch beacon returned (reset?) — config bytes re-asserted")
            end
        end
        PP.was = pp
    end

    -- 4. Read current state — cache battle/overworld state once per frame.
    -- Within a single on_frame() callback the GBA CPU is frozen, so these
    -- values cannot change between uses.  Read BEFORE sync flush so the
    -- cached overworld state gates writes correctly.
    -- Capture the raw (group, num) too — what current_area_loc() discards — so
    -- the cold gift-fallback branches below can rebuild "gift_<g>_<n>" without a
    -- second getCurrentMap() read on the same frozen frame.
    local frame_map_g, frame_map_n = M.getCurrentMap()
    local area = game_module.resolve_area(frame_map_g, frame_map_n)
    local loc  = game_module.resolve_location(frame_map_g, frame_map_n)
    local in_battle    = M.isInBattle()
    local is_overworld = M.isInOverworld()

    -- A battle or warp mid-trade strands the in-flight apply: the trade state machine below is gated on
    -- is_overworld, so a battle freezes it (its opcode seq rots), and the partner has ALREADY committed
    -- their half — leaving us without their mon. Resolve it safely the instant we leave the field or the
    -- map changes: silent-swap the partner's mon in if our slot still holds the PRE-trade mon (the scene
    -- never swapped), else just reconcile from the slot (the same rule the scene-FAIL branch uses, so we
    -- never double-write a slot the native scene already swapped -> no corrupted keys / pairs-break).
    if pending_trade_apply and (in_battle or area ~= prev_area or loc ~= prev_loc) then
        local p = pending_trade_apply
        relocate_trade_slot(p)
        local cur
        local ok_k, k = pcall(M.monKey, (M.PARTY_BASE or 0x02024284) + p.slot * (M.MON_SIZE or 0x64))
        if ok_k then cur = k end
        if (cur == nil or cur == p.old_key) and patch_present() then
            console.log("[SLink-FRLGE]   ↳ trade: interrupted (battle/warp) before swap -> silent swap")
            MB.set_party_mon(p.slot, p.blob, false)
        else
            console.log("[SLink-FRLGE]   ↳ trade: interrupted (battle/warp) after swap -> reconcile from slot")
        end
        emit_trade_done(p.slot, p.old_key, p.token)
        pending_trade_apply = nil
    end

    -- Confirm a native notification box actually OPENED. OP_SHOW_MESSAGE returns result[0]=0 when the patch
    -- refused it (a field script/box slipped in after our safe-area check — the 1-frame race); in that case
    -- fall back to the Lua overlay so the notification is NEVER dropped. The patch acks within ~1 frame; on
    -- a lost ack (timeout) assume it showed, to avoid a double box.
    if pending_msgbox then
        local pm = pending_msgbox
        local st = MB.poll(pm.seq)
        if st ~= nil then
            if MB.read_result_u8(0) == 0 then           -- 0 = box was REFUSED (field busy), never shown
                if pm.fb == "prompt" then prompt_show(pm.text, pm.r, pm.g, pm.b, pm.frames)
                else hud_show(pm.text, pm.r, pm.g, pm.b, pm.frames) end
                console.log("[SLink-FRLGE]   ↳ native box refused (field busy) — fell back: "..pm.text)
            end
            pending_msgbox = nil
        elseif frame_count - pm.start_frame > MSGBOX_CONFIRM_TIMEOUT then
            pending_msgbox = nil
        end
    end

    -- Drain pending native in-battle notifications: ONE per frame, only when the mailbox opcode slot is
    -- IDLE (so we never clobber a force_faint / force-move arm sent earlier the same frame) and no
    -- notification is currently on screen (BattleNotif.active — stacked messages show sequentially).
    -- If the battle ended before a queued message showed, flush it to the BizHawk overlay instead so the
    -- notification is never lost.
    if #pending_battle_msgs > 0 then
        if not (native_msgs_enabled and patch_present() and M.isInBattle()) then
            local m = table.remove(pending_battle_msgs, 1)
            if m.fb == "prompt" then prompt_show(m.text, m.r, m.g, m.b, m.frames or 300)
            else hud_show(m.text, m.r, m.g, m.b, m.frames or 300) end
        elseif memory.read_u16_le(0x0203F806) == 0           -- mailbox opcode slot idle (MB.BASE+6)
           and memory.read_u8(MB.BATTLE_NOTIF) == 0 then     -- no notification currently showing
            local m = table.remove(pending_battle_msgs, 1)
            MB.show_battle_message(fit_battle_text(m.text), NATIVE_BATTLE_FRAMES, NATIVE_BATTLE_WIN, m.color)
        end
    end

    -- Peer ghost (RR + companion patch): broadcast our overworld WORLD-PIXEL position (sub-pixel) +
    -- facing + moving + live animNum ~20 Hz, plus our AVATAR (live sprite images/anims ROM ptrs +
    -- true 16-colour palette) so the partner sees US as ourselves, moving exactly as we move. The
    -- partner's patch LERPs the ghost to our position + plays our animation. No-ops without the patch.
    if IS_RR and is_overworld and patch_present() then
        local OE = MB.player_oe()   -- the player's ACTUAL object-event (not always slot 0)
        -- Calibrate sub-pixel: while the player is tile-aligned (idle), snapshot (tile, coordOffset);
        -- world-px = alignTile*16 + (coffAtAlign - coffNow) tracks the smooth scroll between tiles.
        local coffx = memory.read_s16_le(0x02021BC8)
        local coffy = memory.read_s16_le(0x02021BCA)
        local idle  = (memory.read_u8(OE + 0x00) & 0x80) ~= 0   -- heldMovementFinished set
        if idle or pg_align_tx == nil then
            pg_align_tx = memory.read_s16_le(OE + 0x10); pg_align_ty = memory.read_s16_le(OE + 0x12)
            pg_coff_ax = coffx; pg_coff_ay = coffy
        end
        -- 30 Hz while moving (fresher targets shrink the patch's lead-extrapolation window),
        -- 20 Hz idle (nothing changes; don't double the idle chatter).
        if frame_count % (idle and 3 or 2) == 0 then
            local f = memory.read_u8(OE + 0x18) & 0x0F
            if f < 1 or f > 4 then f = 1 end
            local sid  = memory.read_u8(OE + 0x04)
            local anim = (sid < 64) and memory.read_u8(0x0202063C + sid * 0x44 + 0x2A) or 0
            local wx = pg_align_tx * 16 + (pg_coff_ax - coffx)   -- sub-pixel world position
            local wy = pg_align_ty * 16 + (pg_coff_ay - coffy)
            -- mv means "position actually ADVANCING", not "walk animation playing": a wall bump
            -- is a held movement (not idle) that never moves us, and broadcasting mv=1 for it
            -- makes the partner's ghost lead-extrapolate past us and hold there (the driver
            -- refuses backward steps while mv=1). The ghost's animation comes from `an`, so a
            -- bump still animates; only the motion model sees us as stationary.
            local moving = (not idle) and (wx ~= pg_last_sent_wx or wy ~= pg_last_sent_wy)
            pg_last_sent_wx, pg_last_sent_wy = wx, wy
            -- Our avatar: live sprite images(+0x0C)/anims(+0x08) ROM ptrs + the true (untinted) 16
            -- colours from the player's OBJ palette slot in the Unfaded shadow buffer.
            local imgs, anim_ptr, pcol = 0, 0, nil
            if sid < 64 then
                local sa = 0x0202063C + sid * 0x44
                imgs     = memory.read_u32_le(sa + 0x0C)
                anim_ptr = memory.read_u32_le(sa + 0x08)
                local pslot = (memory.read_u16_le(sa + 0x04) >> 12) & 0x0F
                local base = 0x020373F8 + pslot * 0x20   -- gPlttBufferUnfaded OBJ slot
                local t = {}
                for i = 0, 15 do t[#t + 1] = string.format("%04X", memory.read_u16_le(base + i * 2)) end
                pcol = table.concat(t)
            end
            send({ event = "ghost_pos",
                   mg = memory.read_u8(OE + 0x0A), mn = memory.read_u8(OE + 0x09),  -- group, num
                   x  = wx, y = wy,                  -- WORLD PIXELS (sub-pixel)
                   f  = f, mv = (moving and 1 or 0),
                   an = anim,                        -- live animNum (exact animation)
                   run = (anim >= 8 and 1 or 0),
                   gfx = memory.read_u8(OE + 0x05),
                   imgs = imgs, anim = anim_ptr, pcol = pcol }, "ghost_pos", true, true)
            if not pg_send_logged then
                pg_send_logged = true
                console.log(string.format("[peer-ghost] broadcasting our position: map(%d,%d) worldpx(%d,%d)",
                    memory.read_u8(OE + 0x0A), memory.read_u8(OE + 0x09), wx, wy))
            end
        end
        if PG then
            PG.on_frame()
            if PG.consume_interact() and not pending_ui and not pending_trade_apply then
                -- Talk-to-partner opens the action menu (Trade / Say hey) — but only if no menu/trade is
                -- already in flight, so mashing A near the ghost can't stack requests.
                send({ event = "trade_request" }, "trade_request", true, false)
            end
        end

        -- Pokémon-Center trade NPC (presence-OFF mode): the patch spawns/arms the NPC and bumps pi_count
        -- on talk; here we just relay it as the SAME trade_request, with the SAME in-flight guard. The
        -- ghost path is dormant when presence is OFF (server starves ghost_pos), so pi_count has a single
        -- consumer at a time — the two paths never both fire.
        if patch_present() and pc_npc_enabled then
            local cnt = MB.peer_interact_count()
            if pc_npc_pi_last == nil then pc_npc_pi_last = cnt end
            if cnt < pc_npc_pi_last then
                -- counter went BACKWARDS: savestate load / soft reset rewound EWRAM. Re-latch
                -- silently — treating the delta as a talk fired phantom trade_requests.
                pc_npc_pi_last = cnt
            elseif cnt ~= pc_npc_pi_last then
                pc_npc_pi_last = cnt
                if not pending_ui and not pending_trade_apply then
                    send({ event = "trade_request" }, "trade_request", true, false)
                end
            end
        end

        -- Poll an in-flight native UI op (show_menu / choose_mon); report the result to the server.
        if pending_ui then
            local st = MB.poll(pending_ui.seq)
            local timed_out = frame_count - pending_ui.start_frame > MENU_TIMEOUT
            if st ~= nil or timed_out then
                if pending_ui.kind == "menu" then
                    local choice = (st == MB.ST_OK) and MB.menu_result() or (pending_ui.cancel or 0)
                    send({ event = "menu_result", token = pending_ui.token, choice = choice },
                         "menu_result", true, false)
                else  -- "choose"
                    local slot = (st == MB.ST_OK) and MB.choose_result() or 7
                    send({ event = "mon_chosen", token = pending_ui.token, slot = slot },
                         "mon_chosen", true, false)
                end
                pending_ui = nil
            end
        end

        -- Drive the native trade-scene apply: wait for a clear field -> stage gEnemyParty[0] -> run the
        -- trade scene -> trade_done. Falls back to a silent party write (OP_SET_PARTY_MON) on any failure
        -- so a trade never strands. (Reaches here only while in the overworld — the enclosing gate.)
        if pending_trade_apply then
            local p = pending_trade_apply
            local function fallback(why)
                console.log("[SLink-FRLGE]   ↳ trade: " .. why .. " -> silent swap fallback")
                relocate_trade_slot(p)
                MB.set_party_mon(p.slot, p.blob, false); emit_trade_done(p.slot, p.old_key, p.token); pending_trade_apply = nil
            end
            if p.phase == "pending" then
                if not patch_present() then
                    -- The "silent swap" fallback is itself an OPCODE (OP_SET_PARTY_MON), so on an
                    -- unpatched ROM it writes into EWRAM nobody reads and the old emit_trade_done
                    -- reported a trade that never happened.  Unreachable in practice — the trade
                    -- flow only starts by talking to the peer ghost, which requires the patch —
                    -- but fail loudly rather than lie about it.
                    console.log("[SLink-FRLGE]   ↳ trade ABORTED: companion patch not present " ..
                                "(the trade flow requires it); no swap performed")
                    pending_trade_apply = nil
                    relocate_trade_slot(p)                                       -- party may have been reordered
                    local sseq = MB.set_enemy_party({ p.blob })                  -- stage the partner mon
                    if sseq then
                        p.phase = "stage"; p.seq = sseq; p.start_frame = frame_count
                        console.log("[SLink-FRLGE]   ↳ trade: staging partner mon -> gEnemyParty[0]")
                    else
                        fallback("stage send failed")
                    end
                elseif frame_count - p.start_frame > 1800 then
                    fallback("field never cleared")
                end
            elseif p.phase == "stage" then
                local st = MB.poll(p.seq)
                if st == MB.ST_OK then
                    local tseq = MB.trade_scene(p.slot)
                    if tseq then
                        p.phase = "scene"; p.seq = tseq; p.start_frame = frame_count
                        console.log("[SLink-FRLGE]   ↳ trade: running native trade scene (slot " ..
                                    tostring(p.slot) .. ")")
                    else
                        fallback("trade_scene send failed")
                    end
                elseif st == MB.ST_FAIL or frame_count - p.start_frame > TRADE_STAGE_TIMEOUT then
                    fallback("stage failed/timeout")
                end
            else  -- "scene"
                local st = MB.poll(p.seq)
                if st == MB.ST_OK then
                    console.log("[SLink-FRLGE]   ↳ trade: native scene complete")
                    emit_trade_done(p.slot, p.old_key, p.token); pending_trade_apply = nil   -- (maybe evolved) report new mon
                elseif st == MB.ST_FAIL then
                    -- The native scene reported failure. It may or may not have ALREADY swapped the slot.
                    -- A silent OP_SET_PARTY_MON on top of a scene that DID swap is a double-write (corrupted
                    -- keys → "pairs break"). So only fall back to the faithful silent swap if the slot still
                    -- holds our PRE-trade mon (scene never swapped); otherwise reconcile from the slot.
                    local cur
                    local ok_k, k = pcall(M.monKey, (M.PARTY_BASE or 0x02024284) + p.slot * (M.MON_SIZE or 0x64))
                    if ok_k then cur = k end
                    if cur == nil or cur == p.old_key then
                        fallback("scene failed before swap")
                    else
                        console.log("[SLink-FRLGE]   ↳ trade: scene FAIL after swap — reconciling from slot (no overwrite)")
                        emit_trade_done(p.slot, p.old_key, p.token); pending_trade_apply = nil
                    end
                elseif frame_count - p.start_frame > TRADE_SCENE_BACKSTOP then
                    -- Patch ack lost (the scene almost certainly completed the swap natively). Do NOT
                    -- silent-swap — just reconcile from whatever is in the slot so the party diff un-freezes.
                    console.log("[SLink-FRLGE]   ↳ trade: scene ack lost — reconciling from slot (no overwrite)")
                    emit_trade_done(p.slot, p.old_key, p.token); pending_trade_apply = nil
                end
            end
        end

        -- Periodic self-status: badge count, so the server can surface the PARTNER's progress in-game
        -- (folded into the talk-to-partner box). Only resend when it changes (rate-limited).
        if status_cooldown > 0 then status_cooldown = status_cooldown - 1 end
        if status_cooldown == 0 then
            local badges = M.readBadges()
            if badges ~= last_status_badges then
                send({ event = "status", badges = badges }, "status", true, false)
                last_status_badges = badges
            end
            status_cooldown = 300   -- ~5 s between checks (badge changes are rare)
        end
    end

    -- 4a. Update sync_cooldown BEFORE sync flush to prevent executing sync
    -- commands on the battle-end transition frame.  The game is still doing
    -- post-battle processing (HP writeback, exp, evolution) on that frame.
    local battle_just_ended = prev_in_battle and not in_battle
    if battle_just_ended then
        sync_cooldown = SYNC_COOLDOWN_FRAMES
        -- Arm the EOB gate HERE, before the hardware gate check below, so that on the
        -- battle-end frame the hardware check sees cooldown > 0 and defers eob_clear.
        -- (The battle_just_ended handler at step 6 also sets this — same value, no harm.)
        memorialize_battle_cooldown = MEMORIALIZE_POST_BATTLE_COOLDOWN
        post_eob_frames             = POST_EOB_SAFETY_CAP
        -- Rival Team Swap: reset trainer-battle-start one-shot for the next battle.
        trainer_battle_sent   = false
        trainer_last_id       = 0
        trainer_stable_frames = 0
    elseif sync_cooldown > 0 then
        sync_cooldown = sync_cooldown - 1
    end

    -- ── Rival Team Swap: emit trainer_battle_start once per trainer battle ───
    -- Stability gate: same non-zero ID for TRAINER_STABLE_GATE consecutive
    -- frames before firing.  Filters borrowed-party battles (Poké Dude/mock)
    -- and wild encounters.  No-op when TRAINER_OPPONENT_ADDR isn't set
    -- (non-RR profiles where we don't support the feature yet).
    if in_battle and not trainer_battle_sent
       and M.TRAINER_OPPONENT_ADDR and M.TRAINER_OPPONENT_ADDR ~= 0 then
        local tid = M.readTrainerOpponentId()
        if tid ~= nil and tid > 0 then
            local is_wild = M.isWildBattle()  -- nil if profile can't tell
            local is_borrowed = false
            if M.isBorrowedBattle then is_borrowed = M.isBorrowedBattle() end
            if is_wild ~= true and not is_borrowed then
                if tid == trainer_last_id then
                    trainer_stable_frames = trainer_stable_frames + 1
                else
                    trainer_last_id       = tid
                    trainer_stable_frames = 1
                end
                if trainer_stable_frames >= TRAINER_STABLE_GATE then
                    trainer_battle_sent = true
                    send({event = "trainer_battle_start", trainer_id = tid},
                         "trainer_battle_start", true)
                end
            end
        end
    end

    -- 4a-bis. Settle coerced-Explosion entries.
    --   • If the mon's gBattleMons HP has reached 0, Explosion did its job — write
    --     party HP=0 too (idempotent), mark force_fainted_keys to suppress echo.
    --   • If the mon switched out or the battle ended before exploding (cannot really
    --     happen mid-turn but covers teardown races), settle via M.forceFaint.
    --   • If the fallback timer elapsed and HP is still > 0 (Damp ability, type
    --     immunity, player stalling), fall back to the legacy deferred-faint path.
    if next(pending_explosions) and writes_enabled then
        local active_slot  = -1
        local active_slot2 = -1
        if in_battle and M.BATTLER_PARTY_INDEXES_ADDR then
            active_slot = memory.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR)
            if M.BATTLERS_COUNT_ADDR and mem_u8(M.BATTLERS_COUNT_ADDR) >= 4 then
                active_slot2 = memory.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR + 4)
            end
        end
        -- Clear our lock state on the battle mon and gLockedMoves to avoid the
        -- engine carrying stale rampage data into the post-Explosion send-out.
        local function clear_lock_state(st)
            if M.LOCKED_MOVES_ADDR then
                memory.write_u16_le(M.LOCKED_MOVES_ADDR + st.battler * 2, 0)
            end
        end
        for key, st in pairs(pending_explosions) do
            local base       = M.PARTY_BASE + st.slot * M.MON_SIZE
            local bmon_base  = M.BATTLE_MONS_ADDR + st.battler * M.BATTLE_MON_SIZE
            local bhp, bpp0  = 0, 5
            if in_battle and M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0 then
                bhp  = memory.read_u16_le(bmon_base + M.BATTLE_MON_HP_OFF)
                bpp0 = memory.read_u8   (bmon_base + M.BATTLE_MON_PP_OFF)
            end
            local still_active = in_battle and (st.slot == active_slot or st.slot == active_slot2)
            local pp_dropped   = (bpp0 < 5)
            -- Reinforce Variant-3 menu-skip writes every frame until the engine
            -- commits (PP drops).  Engine resets gBattleCommunication[battler]
            -- to 0/1 at turn start; we overwrite with 3 (STANDBY) ONLY if the
            -- engine hasn't progressed past 3 already — otherwise we'd lock the
            -- engine in state 3 and softlock the game.  We also re-write
            -- gActionForBanks, gChosenMovesByBanks, and the gBattleStruct
            -- sub-fields so the engine sees a coherent committed-action state.
            if still_active and not pp_dropped and M.BATTLE_COMM_ADDR
               and M.CHOSEN_ACTION_ADDR and M.CHOSEN_MOVE_ADDR then
                local cur_state = memory.read_u8(M.BATTLE_COMM_ADDR + st.battler)
                if cur_state < 3 then
                    memory.write_u8 (M.CHOSEN_ACTION_ADDR + st.battler,     0)
                    memory.write_u16_le(M.CHOSEN_MOVE_ADDR + st.battler * 2, M.MOVE_EXPLOSION)
                    memory.write_u8 (M.BATTLE_COMM_ADDR + st.battler,        3)
                    if M.BATTLE_STRUCT_PTR_ADDR then
                        local bs = memory.read_u32_le(M.BATTLE_STRUCT_PTR_ADDR)
                        if bs ~= 0 then
                            if M.BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF then
                                memory.write_u8(bs + M.BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF + st.battler, 0)
                            end
                            if M.BATTLE_STRUCT_MOVE_TARGET_OFF then
                                memory.write_u8(bs + M.BATTLE_STRUCT_MOVE_TARGET_OFF + st.battler, 1)
                            end
                        end
                    end
                end
            end
            if (in_battle and bhp == 0) or not in_battle or not still_active then
                -- Settle: Explosion landed, switched out, or battle ended.
                clear_lock_state(st)
                M.forceFaint(st.slot)
                _battle_hp_cache[key] = {hp = 0, maxHP = mem_u16(base + M.OFF_MAX_HP), level = mem_u8(base + M.OFF_LEVEL)}
                force_fainted_keys[key] = true
                pending_explosions[key] = nil
                console.log(string.format(
                    "[SLink-FRLGE]   ↳ EXPLOSION settled slot=%d battler=%d key=%s in_battle=%s",
                    st.slot, st.battler, key, tostring(in_battle)))
            elseif (frame_count - st.start_frame) >= EXPLOSION_FALLBACK_FRAMES then
                -- Fallback: Explosion never connected — apply HP=0 directly.
                clear_lock_state(st)
                M.forceFaint(st.slot)
                _battle_hp_cache[key] = {hp = 0, maxHP = mem_u16(base + M.OFF_MAX_HP), level = mem_u8(base + M.OFF_LEVEL)}
                force_fainted_keys[key] = true
                pending_explosions[key] = nil
                show_fallback("!! " .. nick_label(key) .. " KO! (fb)", "hud", 255, 80, 80, 360)
                console.log(string.format(
                    "[SLink-FRLGE]   ↳ EXPLOSION FALLBACK fired slot=%d battler=%d key=%s",
                    st.slot, st.battler, key))
            end
        end
    end

    -- 4a-quater. Settle the native Rival Team Swap (OP_SET_ENEMY_PARTY).  The patch's blob copy is
    -- synchronous (one-frame memcpy), so this normally acks ST_OK within a couple frames: on ST_OK we
    -- do the Lua-side active-foe gBattleMons refresh (no clean engine fn) + ack the server.  On ST_FAIL
    -- or timeout we error the ack — the patch is required, there is no RAM-poke fallback.
    if pending_enemy_party then
        local ep = pending_enemy_party
        local status = MB.poll(ep.seq)
        if status == MB.ST_OK then
            pending_enemy_party = nil
            local species = M.refreshEnemyPartyNative(#ep.blobs_hex)
            console.log(string.format(
                "[SLink-FRLGE]   ↳ replace_rival_team OK (native) trainer=%s species=[%s]",
                tostring(ep.trainer_id or "?"), table.concat(species, ",")))
            send({event = "rival_team_replaced", trainer_id = ep.trainer_id or 0,
                  species_ids = species}, "rival_team_replaced", true)
        elseif status == MB.ST_FAIL or (frame_count - ep.start_frame) >= ENEMY_PARTY_TIMEOUT then
            pending_enemy_party = nil
            local why = (status == MB.ST_FAIL) and "patch_failed" or "patch_timeout"
            console.log("[SLink-FRLGE]   ↳ native OP_SET_ENEMY_PARTY "
                .. (status == MB.ST_FAIL and "FAILED" or "timed out") .. " — no fallback (patch required)")
            send({event = "rival_team_replaced", trainer_id = ep.trainer_id or 0,
                  species_ids = {}, error = why}, "rival_team_replaced", true)
        end
    end

    -- 4a-quinque. Settle the native PC box⇄party storage op (OP_DEPOSIT_MON / OP_WITHDRAW_MON). Async:
    -- the opcode acks next frame. ST_OK → success bookkeeping; ST_FAIL → Lua fallback; timeout → re-check
    -- the real party/box state (a lost ack on a SUCCEEDED op must not double-run through the fallback).
    if pending_storage then
        local ps = pending_storage
        local status = MB.poll(ps.seq)
        local outcome  -- "ok" | "fallback" | nil (keep waiting)
        if status == MB.ST_OK then
            outcome = "ok"
        elseif status == MB.ST_FAIL then
            outcome = "fallback"
        elseif (frame_count - ps.start_frame) >= STORAGE_OP_TIMEOUT then
            -- Lost ack: decide from real state so a succeeded-but-unacked op isn't re-run.
            local in_party, pc = false, memory.read_u8(M.PARTY_COUNT_ADDR)
            for s = 0, pc - 1 do
                local b = M.PARTY_BASE + s * M.MON_SIZE
                if M.slotOccupied(b) and M.monKey(b) == ps.key then in_party = true; break end
            end
            if ps.mode == "deposit" then
                outcome = in_party and "fallback" or "ok"   -- still in party → never ran → fall back
            else
                outcome = in_party and "ok" or "fallback"   -- now in party → ran → done
            end
            console.log(string.format("[SLink-FRLGE] storage %s timeout: in_party=%s → %s",
                ps.mode, tostring(in_party), outcome))
        end
        if outcome == "ok" then
            sync_written_keys[ps.key] = true
            if ps.mode == "deposit" then
                console.log(string.format("[SLink-FRLGE] ✓ box_mon (native): %s → box%d s%d", ps.key:sub(1,8), ps.box, ps.pos))
                hud_show("↓ " .. nick_label(ps.key) .. " boxed", 100, 180, 255, 200)
            else
                all_known_keys[ps.key] = true
                console.log(string.format("[SLink-FRLGE] ✓ party_mon (native): %s ← box%d s%d", ps.key:sub(1,8), ps.box, ps.pos))
                hud_show("↑ " .. nick_label(ps.key) .. " unboxed", 100, 255, 160, 200)
                send({event = "sync_retrieve_done", key = ps.key}, "sync_retrieve_done:"..ps.key:sub(1,8), true, true)
            end
        elseif outcome == "fallback" then
            console.log(string.format("[SLink-FRLGE] native %s %s — Lua fallback (key=%s)",
                ps.mode, (status == MB.ST_FAIL and "FAILED" or "timed out/unrun"), ps.key:sub(1,8)))
            if ps.mode == "deposit" then
                local bi, _si, err = M.depositPartyMon(ps.slot)
                if bi then sync_written_keys[ps.key] = true
                    hud_show("↓ " .. nick_label(ps.key) .. " boxed", 100, 180, 255, 200)
                else console.log("[SLink-FRLGE] ✗ box_mon fallback failed: "..(err or "?"))
                    hud_show("X Box fail: " .. nick_label(ps.key), 255, 80, 80, 240) end
            else
                local ok, err = M.retrieveBoxMon(ps.key, ps.stats)
                if ok then sync_written_keys[ps.key] = true; all_known_keys[ps.key] = true
                    hud_show("↑ " .. nick_label(ps.key) .. " unboxed", 100, 255, 160, 200)
                    send({event = "sync_retrieve_done", key = ps.key}, "sync_retrieve_done:"..ps.key:sub(1,8), true, true)
                else console.log("[SLink-FRLGE] ✗ party_mon fallback failed: "..(err or "?"))
                    hud_show("! Unbox " .. nick_label(ps.key), 255, 200, 60, 600)
                    send({event = "sync_retrieve_failed", key = ps.key}, "sync_retrieve_failed:"..ps.key:sub(1,8), true, true) end
            end
        end
        if outcome then
            -- Refresh the borrowed-party detector baseline to the now-modified party (like the sync loop).
            local _post = _read_party_pids()
            for i = 0, 5 do _stable_party_pids[i] = _post[i]; _last_party_pids[i] = _post[i] end
            _last_pid_change_frame = frame_count
            post_unfreeze_frames = POST_UNFREEZE_SETTLE
            pending_storage = nil
        end
    end

    -- 4a-sexies. Settle the native memorialize (OP_MEMORIALIZE). On ST_OK run the shared epilogue
    -- (verify + HUD + memorialize_done + overflow rename); on failure/timeout disable the native
    -- path for the session and re-queue the command so the proven Lua RAM-poke path takes over.
    if pending_memorialize then
        local pm = pending_memorialize
        local st = MB.poll(pm.seq)
        local timed_out = frame_count - pm.start_frame > 120
        if st == MB.ST_OK then
            memorialize_finish(pm.key, pm.box, pm.slot, pm.pre_count)
            local _post = _read_party_pids()
            for i = 0, 5 do _stable_party_pids[i] = _post[i]; _last_party_pids[i] = _post[i] end
            _last_pid_change_frame = frame_count
            pending_memorialize = nil
        elseif st == MB.ST_FAIL or timed_out then
            console.log(string.format(
                "[SLink-FRLGE] ✗ native memorialize %s (key=%s) — Lua path takes over for this run",
                timed_out and "TIMED OUT" or "FAILED", pm.key:sub(1, 8)))
            memorialize_native_disabled = true
            pending_memorialize = nil
            table.insert(pending_sync_cmds, 1, {cmd = "memorialize", key = pm.key})
        end
    end

    -- 4b. Flush deferred battle faints: apply force_faint to mons that are no longer
    -- the active battler (switched out) or when battle has ended.
    if next(pending_battle_faints) and writes_enabled then
        local count = memory.read_u8(M.PARTY_COUNT_ADDR)
        local active_slot  = -1
        local active_slot2 = -1
        if in_battle and M.BATTLER_PARTY_INDEXES_ADDR then
            active_slot = memory.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR)
            if M.BATTLERS_COUNT_ADDR and mem_u8(M.BATTLERS_COUNT_ADDR) >= 4 then
                active_slot2 = memory.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR + 4)
            end
        end
        for key, _ in pairs(pending_battle_faints) do
            local found_slot = false
            for slot = 0, count - 1 do
                local base = M.PARTY_BASE + slot * M.MON_SIZE
                if M.monKey(base) == key then
                    found_slot = true
                    if not in_battle or (slot ~= active_slot and slot ~= active_slot2) then
                        -- Mon is no longer active (or battle ended) — safe to faint.
                        M.forceFaint(slot)
                        _battle_hp_cache[key] = {hp = 0, maxHP = mem_u16(base + M.OFF_MAX_HP), level = mem_u8(base + M.OFF_LEVEL)}
                        force_fainted_keys[key] = true
                        pending_battle_faints[key] = nil
                        M.playSE(M.SE_LINKED_KO)
                        console.log(string.format("[SLink-FRLGE]   ↳ DEFERRED force_faint applied slot=%d key=%s", slot, key))
                        show_fallback("!! " .. nick_label(key) .. " KO!", "hud", 255, 80, 80, 360)
                    end
                    break
                end
            end
            -- Mon is no longer in party (compacted out after fainting naturally).
            -- Treat as if force_faint succeeded — it's already gone.
            if not found_slot and not in_battle then
                force_fainted_keys[key] = true
                pending_battle_faints[key] = nil
                console.log(string.format("[SLink-FRLGE]   ↳ DEFERRED force_faint: key=%s gone from party (compacted); treating as fainted", key:sub(1,8)))
            end
        end
    end

    -- 5. Flush one deferred sync cmd if safe (BEFORE party diff so writes are clean)
    -- Pre-advance the EndOfBattleThings hardware gate (CFRU profiles with known addresses).
    -- While the post-battle window is armed (memorialize_battle_cooldown > 0), check
    -- gBattleMainFunc every frame.  The moment EndOfBattleThings completes (gBattleMainFunc
    -- transitions to RETURN_FROM_BATTLE_ADDR), clear the cooldown — unblocking ALL sync
    -- commands (box_mon, party_mon, memorialize).  The cooldown serves as the armed-window
    -- guard so this read is a no-op in the overworld where the cooldown is already 0.
    if memorialize_battle_cooldown > 0
            and M.BATTLE_MAIN_FUNC_ADDR and M.RETURN_FROM_BATTLE_ADDR then
        if mem_u32(M.BATTLE_MAIN_FUNC_ADDR) == M.RETURN_FROM_BATTLE_ADDR then
            memorialize_battle_cooldown = 0  -- signal fired; all sync commands unblocked
        end
    end
    -- Gate on: overworld, cooldown expired, post-battle grace window finished, and
    -- (when BATTLE_MAIN_FUNC_ADDR is known) EndOfBattleThings completed.
    -- Vanilla FRLG and CFRU/RR both have known addresses and use the hardware gate.
    -- AP has RETURN_FROM_BATTLE_ADDR = nil (unknown), so eob_clear is always true
    -- for AP and the 90-frame post_battle_frames guard is used instead.
    local eob_clear = not (M.BATTLE_MAIN_FUNC_ADDR and M.RETURN_FROM_BATTLE_ADDR)
                      or memorialize_battle_cooldown == 0
    -- Post-EOB write window: prefer the authoritative gTasks/CB2 predicate
    -- when available (M.isPostBattleSettled). The post_eob_frames counter is
    -- a safety cap that backs the predicate up when a profile lacks the
    -- discovery values or one of them is wrong.
    local post_eob_clear = post_eob_frames == 0 or M.isPostBattleSettled()
    local safe_now = is_overworld and sync_cooldown == 0 and not party_frozen
                     and post_battle_frames == 0 and eob_clear and post_eob_clear
    if #pending_sync_cmds > 0 then
        if not safe_now or not writes_enabled then
            if not _sync_blocked_logged then
                _sync_blocked_logged = true
                local eob_note = ""
                if not eob_clear and M.BATTLE_MAIN_FUNC_ADDR then
                    eob_note = string.format("  eob=0x%08X(not done)", mem_u32(M.BATTLE_MAIN_FUNC_ADDR))
                end
                console.log(string.format("[SLink-FRLGE] SYNC BLOCKED: safe=%s writes=%s cooldown=%d pbf=%d peof=%d cmd=%s (%d queued)%s",
                    tostring(safe_now), tostring(writes_enabled), sync_cooldown,
                    post_battle_frames, post_eob_frames, pending_sync_cmds[1].cmd, #pending_sync_cmds, eob_note))
            end
        else
            _sync_blocked_logged = false
        end
    end
    -- DEFER all box/party sync writes while a native trade is mid-flight (staging → scene). The server
    -- can queue a party_mon/box_mon for a trading mon ("Unbox") that would otherwise execute on top of
    -- the trade scene rewriting the party slot — the user's "unbox race". The trade owns the party until
    -- it completes; the migration block then purges the now-stale commands for the swapped keys.
    -- `not pending_storage` / `not pending_memorialize`: only one native party-mutating op in flight
    -- at a time — the next sync cmd waits until the §4a-quinque/-sexies poll resolves it (or falls back).
    if safe_now and #pending_sync_cmds > 0 and writes_enabled and not pending_trade_apply
       and not pending_storage and not pending_memorialize then
        local cmd = pending_sync_cmds[1]  -- peek before removing
        -- Safety gate: if target party slot is in mid-copy quarantine, defer one frame.
        local blocked = false
        if (cmd.cmd == "box_mon" or cmd.cmd == "memorialize") and cmd.key then
            local q_count = memory.read_u8(M.PARTY_COUNT_ADDR)
            for q_s = 0, q_count - 1 do
                if M.monKey(M.PARTY_BASE + q_s * M.MON_SIZE) == cmd.key then
                    -- Never memorialize the last party mon — emptying the party
                    -- softlocks the Pokémon Center healing animation after whiteout.
                    if cmd.cmd == "memorialize" and q_count <= 1 and not blocked then
                        if game_over_flag then
                            -- No replacements exist. Drop the command.
                            table.remove(pending_sync_cmds, 1)
                            blocked = true
                            console.log("[SLink-FRLGE] memorialize dropped (game over, last party mon): "..cmd.key:sub(1,8))
                        else
                            -- Block the memorialize — the party must never be
                            -- empty (Pokémon Center heal softlock). Normally
                            -- party_mon arrives before this memorialize and
                            -- lifts the block automatically. But when the
                            -- party was full at whiteout, party_mon retried
                            -- to the end of the queue past all the
                            -- memorializes. Rescue the deadlock: find the
                            -- first party_mon in the remaining queue and
                            -- promote it to front so it runs next frame.
                            blocked = true
                            for look = 2, #pending_sync_cmds do
                                if pending_sync_cmds[look].cmd == "party_mon" then
                                    local pm = table.remove(pending_sync_cmds, look)
                                    table.insert(pending_sync_cmds, 1, pm)
                                    console.log("[SLink-FRLGE] memorialize blocked: promoted party_mon to front ("..pm.key:sub(1,8)..")")
                                    break
                                end
                            end
                        end
                    end
                    break
                end
            end
        end
        if not blocked then
            table.remove(pending_sync_cmds, 1)
            local exec_ok, exec_err = true, nil
            if cmd.cmd == "box_mon" then
                exec_ok, exec_err = pcall(exec_box_mon, cmd.key)
            elseif cmd.cmd == "party_mon" then
                exec_ok, exec_err = pcall(exec_party_mon, cmd.key, cmd.stats)
            elseif cmd.cmd == "memorialize" then
                exec_ok, exec_err = pcall(exec_memorialize, cmd.key)
            end
            if exec_ok and exec_err == "pending" then
                -- Async native storage op fired (OP_DEPOSIT_MON/WITHDRAW_MON): the party isn't modified
                -- until the opcode runs next frame. The §4a-quinque poll updates the baseline on
                -- completion; pending_storage gates this loop meanwhile so nothing races the change.
                -- (intentionally no baseline update here — deferred to the poll)
            elseif exec_ok then
                -- Sync command modified party slots — immediately update the
                -- PID swap detector's stable baseline so rapid back-to-back
                -- commands (e.g. 3× box_mon) don't accumulate diffs and
                -- falsely trigger a borrowed-party freeze.
                local _post = _read_party_pids()
                for i = 0, 5 do
                    _stable_party_pids[i] = _post[i]
                    _last_party_pids[i]   = _post[i]
                end
                _last_pid_change_frame = frame_count
            else
                console.log(string.format("[SLink-FRLGE] ✗ SYNC CMD ERROR (%s key=%s): %s",
                    cmd.cmd, (cmd.key or "?"):sub(1,8), tostring(exec_err)))
                -- Re-queue with a retry counter to avoid infinite loops.
                cmd._retries = (cmd._retries or 0) + 1
                if cmd._retries <= 3 then
                    table.insert(pending_sync_cmds, 1, cmd)
                    console.log(string.format("[SLink-FRLGE]   ↳ re-queued (attempt %d/3)", cmd._retries))
                else
                    console.log("[SLink-FRLGE]   ↳ DROPPED after 3 retries")
                    hud_show("X " .. cmd.cmd .. " fail: " .. nick_label(cmd.key or ""), 255, 80, 80, 600)
                end
            end
        end
    end

    -- ── area_enter / loc_enter ────────────────────────────────────────────────
    -- Fire on any map change (encounter zones get area_id; towns/buildings get loc_name only).
    if loc ~= prev_loc then
        send({event="area_enter", area_id=area, loc_name=loc},
             "area_enter:"..(area ~= "" and area or loc), true)
        -- Notify the player when entering an area with a new encounter available.
        -- Exclude gift/intro areas — those aren't "wild encounter" areas.
        if nuzlocke_active and area ~= "" and not game_module.is_gift_area(area) then
            if resolved_areas_seeded then
                if not resolved_areas[area] then
                    local disp = area_display(area)
                    hud_show("** NEW ENCOUNTER **  " .. disp, 255, 220, 60, 240)
                    M.playSE(M.SE_SUCCESS)
                end
            else
                -- Hello response hasn't arrived yet — defer HUD until resolved_areas seeds.
                pending_hud_area = area
            end
        end
    end

    -- ── battle start ─────────────────────────────────────────────────────────
    if not prev_in_battle and in_battle then
        battle_area_id       = area
        captured_this_battle = false
        battle_is_wild       = M.isWildBattle()
        battle_seen_enemies  = {}
        _battle_hp_cache     = {}  -- fresh cache for this battle
        force_fainted_keys   = {}  -- fresh guard set for this battle
        pending_faint_debounce = {}  -- clear any stale debounce state
        post_eob_frames      = 0   -- clear any leftover post-EOB delay
        -- Snapshot gBattleResults.playerFaintCounter so debounce ticks can
        -- fast-confirm via counter delta on profiles that expose it.
        battle_start_player_faints  = (M.readFaintCounters())
        confirmed_real_player_faints = 0
        ev_faint_credit = 0; ev_outcome_loss = false  -- battle-scoped EvRing credits
        -- Detect borrowed-party battles (CFRU/RR only).
        local ok_bb, is_bb = pcall(M.isBorrowedBattle)
        borrowed_battle = ok_bb and is_bb or false
        if borrowed_battle then
            -- Snapshot the real party BEFORE the game swaps it out.
            -- prev_party still holds the last-frame (real) party here.
            pre_borrowed_party = {}
            for k, v in pairs(prev_party) do
                pre_borrowed_party[k] = {hp=v.hp, maxHP=v.maxHP, level=v.level, slot=v.slot}
            end
            -- Discard any buffered gift captures — they're borrowed mons, not real gifts.
            if #gift_capture_buffer > 0 then
                console.log(string.format("[SLink-FRLGE] [battle] ★ discarding %d buffered gift captures (borrowed)",
                    #gift_capture_buffer))
                gift_capture_buffer = {}
            end
            console.log("[SLink-FRLGE] [battle] ★ BORROWED PARTY detected — freezing party diff")
        end
        if mem_u8(M.PARTY_COUNT_ADDR) == 6 then
            -- Snapshot occupied SLOTS (not keys) so detection works even when
            -- a caught mon has the same PID as a dead mon already in the box.
            local boxIdx
            if M.POKEMON_STORAGE_BASE then
                boxIdx = memory.read_u8(M.POKEMON_STORAGE_BASE)
            elseif M.BOX_SB1_OFFSET then
                local sb1 = memory.read_u32_le(M.SB1_PTR_ADDR)
                boxIdx = memory.read_u8(sb1 + M.BOX_SB1_OFFSET - M.BOX_DATA_OFFSET)
            elseif M.PSP_PTR_ADDR and M.PSP_PTR_ADDR ~= 0 then
                local psp = memory.read_u32_le(M.PSP_PTR_ADDR)
                boxIdx = memory.read_u8(psp)
            end
            -- If currentBox points to a memorial/overflow box, redirect to the first
            -- non-memorial box with space so catches don't land among dead mons.
            if boxIdx and (boxIdx == M.MEMORIAL_BOX or memorial_overflow_renamed[boxIdx]) then
                local redirected = false
                for bi = 0, (M.BOXES_PER_STORE or 14) - 1 do
                    if bi ~= M.MEMORIAL_BOX and not memorial_overflow_renamed[bi] then
                        -- Count occupied slots in this box
                        local occ = 0
                        for si = 0, M.MONS_PER_BOX - 1 do
                            local a = M.boxMonAddr(bi, si)
                            if a and M.boxSlotOccupied(a) then occ = occ + 1 end
                        end
                        if occ < M.MONS_PER_BOX then
                            -- Write the new currentBox index
                            if M.POKEMON_STORAGE_BASE then
                                memory.write_u8(M.POKEMON_STORAGE_BASE, bi)
                            elseif M.BOX_SB1_OFFSET then
                                local sb1 = memory.read_u32_le(M.SB1_PTR_ADDR)
                                memory.write_u8(sb1 + M.BOX_SB1_OFFSET - M.BOX_DATA_OFFSET, bi)
                            elseif M.PSP_PTR_ADDR and M.PSP_PTR_ADDR ~= 0 then
                                local psp = memory.read_u32_le(M.PSP_PTR_ADDR)
                                memory.write_u8(psp, bi)
                            end
                            boxIdx = bi
                            redirected = true
                            console.log(string.format(
                                "[SLink-FRLGE] currentBox was memorial (box %d) — redirected to box %d",
                                M.MEMORIAL_BOX, bi))
                            break
                        end
                    end
                end
                if not redirected then
                    console.log("[SLink-FRLGE] WARNING: all non-memorial boxes full, cannot redirect currentBox")
                end
            end
            if boxIdx and boxIdx < (M.BOXES_PER_STORE or 14) then
                battle_box_index = boxIdx
                battle_box_snapshot = {}
                battle_box_slot_count = 0
                for slot = 0, M.MONS_PER_BOX - 1 do
                    local addr = M.boxMonAddr(boxIdx, slot)
                    if addr and M.boxSlotOccupied(addr) then
                        battle_box_snapshot[slot] = true
                        battle_box_slot_count = battle_box_slot_count + 1
                    end
                end
            else
                battle_box_index = nil
                battle_box_snapshot = {}
                battle_box_slot_count = 0
            end
        else
            battle_box_index    = nil
            battle_box_snapshot = {}
            battle_box_slot_count = 0
        end
        console.log(string.format("[SLink-FRLGE] [battle] start  wild=%s  borrowed=%s  area=%s",
            tostring(battle_is_wild), tostring(borrowed_battle), battle_area_id or "(none)"))
        -- Show encounter prompt when a wild battle starts in an unresolved area.
        if battle_is_wild and nuzlocke_active and battle_area_id and battle_area_id ~= ""
                and not resolved_areas[battle_area_id] and not game_module.is_gift_area(battle_area_id) then
            local disp = area_display(battle_area_id)
            hud_show("** NEW ENCOUNTER **  " .. disp, 255, 220, 60, 360)
            M.playSE(M.SE_SUCCESS)
        end
    end

    -- ── gBattleMons cache update (every frame while in battle + transition) ──
    -- CFRU does NOT copy battle HP/level back to the party struct during battle.
    -- Cache gBattleMons values for all player-side battlers each frame so that
    -- index_party/build_party_snapshot can use them (survives mon switches).
    -- Also fire on battle_just_ended to capture the FINAL HP state — CFRU may
    -- set gBattleOutcome on the same frame as the last faint, so a cache update
    -- gated only on in_battle would miss the final HP=0.
    if (in_battle or battle_just_ended) and M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0
       and M.BATTLER_PARTY_INDEXES_ADDR then
        -- Update cache for battler 0 (always the player's primary mon)
        local idx0 = mem_u16(M.BATTLER_PARTY_INDEXES_ADDR)
        if idx0 < 6 then
            local base0 = M.PARTY_BASE + idx0 * M.MON_SIZE
            if M.slotOccupied(base0) then
                local k0 = M.monKey(base0)
                local bmon = M.BATTLE_MONS_ADDR + 0 * M.BATTLE_MON_SIZE
                local bmon_hp    = mem_u16(bmon + M.BATTLE_MON_HP_OFF)
                local bmon_maxHP = mem_u16(bmon + 0x2C)
                local bmon_level = mem_u8(bmon + 0x2A)
                -- Identity cross-check: verify gBattleMons[0] actually belongs to the
                -- mon at gBattlerPartyIndexes[0].  During mon switches, the battle engine
                -- updates gBattlerPartyIndexes BEFORE refreshing gBattleMons, so for
                -- several frames the new key maps to stale data (including hp=0 from
                -- the fainted outgoing mon).  Comparing personality:otId catches this:
                -- the outgoing mon's identity ≠ incoming mon's identity.
                local bmon_pers = mem_u32(bmon + M.BATTLE_MON_PERS_OFF)
                local bmon_otid = mem_u32(bmon + M.BATTLE_MON_OTID_OFF)
                local party_pers = mem_u32(base0)
                local party_otid = mem_u32(base0 + 4)
                local bmon_fresh = (bmon_pers == party_pers and bmon_otid == party_otid)
                -- Only update cache if gBattleMons has valid data (maxHP > 0) AND
                -- the identity matches (not stale from a previous battler).
                if bmon_maxHP > 0 and bmon_fresh then
                    local bc = _battle_hp_cache[k0]
                    if bc then
                        -- Existing entry: update normally.
                        -- Guard: don't overwrite hp=0 committed by a force_faint applied
                        -- this same frame (step 4b). Without this, the CFRU writeback at
                        -- battle end would restore the surviving HP and silently undo the faint.
                        if not force_fainted_keys[k0] then
                            bc.hp = bmon_hp
                        end
                        bc.maxHP = bmon_maxHP
                        bc.level = bmon_level
                    elseif bmon_hp > 0 then
                        -- New entry: only create when HP is positive.
                        _battle_hp_cache[k0] = {hp=bmon_hp, maxHP=bmon_maxHP, level=bmon_level}
                    end
                end
                -- Cache resolved ability keyed by monKey (persists across battles;
                -- essential fallback for AP where gBaseStats address is unknown).
                -- Only cache when gBattleMons identity matches to avoid wrong ability.
                if bmon_fresh then
                    local aid0 = memory.read_u8(bmon + 0x20)
                    if aid0 > 0 then _ability_cache[k0] = aid0 end
                end
            end
        end
        -- Double battles: battler 2 is the player's second mon
        if M.BATTLERS_COUNT_ADDR and mem_u8(M.BATTLERS_COUNT_ADDR) >= 4 then
            local idx2 = mem_u16(M.BATTLER_PARTY_INDEXES_ADDR + 4)
            if idx2 < 6 then
                local base2 = M.PARTY_BASE + idx2 * M.MON_SIZE
                if M.slotOccupied(base2) then
                    local k2 = M.monKey(base2)
                    local bmon2 = M.BATTLE_MONS_ADDR + 2 * M.BATTLE_MON_SIZE
                    local bmon2_hp    = mem_u16(bmon2 + M.BATTLE_MON_HP_OFF)
                    local bmon2_maxHP = mem_u16(bmon2 + 0x2C)
                    local bmon2_level = mem_u8(bmon2 + 0x2A)
                    -- Same identity cross-check as battler 0.
                    local bmon2_pers = mem_u32(bmon2 + M.BATTLE_MON_PERS_OFF)
                    local bmon2_otid = mem_u32(bmon2 + M.BATTLE_MON_OTID_OFF)
                    local party2_pers = mem_u32(base2)
                    local party2_otid = mem_u32(base2 + 4)
                    local bmon2_fresh = (bmon2_pers == party2_pers and bmon2_otid == party2_otid)
                    if bmon2_maxHP > 0 and bmon2_fresh then
                        local bc2 = _battle_hp_cache[k2]
                        if bc2 then
                            if not force_fainted_keys[k2] then
                                bc2.hp = bmon2_hp
                            end
                            bc2.maxHP = bmon2_maxHP
                            bc2.level = bmon2_level
                        elseif bmon2_hp > 0 then
                            _battle_hp_cache[k2] = {hp=bmon2_hp, maxHP=bmon2_maxHP, level=bmon2_level}
                        end
                    end
                    if bmon2_fresh then
                        local aid2 = memory.read_u8(bmon2 + 0x20)
                        if aid2 > 0 then _ability_cache[k2] = aid2 end
                    end
                end
            end
        end
    end

    -- ── battle end ───────────────────────────────────────────────────────────
    if battle_just_ended then
        -- Borrowed-party cleanup: restore the real party snapshot and skip
        -- HP writeback (the cached HP belongs to the borrowed mons, not ours).
        if borrowed_battle then
            console.log("[SLink-FRLGE] [battle] ★ borrowed battle ended — restoring real party snapshot")
            if pre_borrowed_party then
                prev_party = pre_borrowed_party
            end
            pre_borrowed_party = nil
            borrowed_battle    = false
            _battle_hp_cache   = {}  -- discard borrowed mon HP
            pending_battle_faints = {}  -- discard any deferred faints from borrowed battle
            pending_explosions    = {}  -- discard any coerced-Explosion state
            force_fainted_keys    = {}  -- clear battle-scoped guard
            pending_faint_debounce = {}  -- clear any debounce state
            battle_start_player_faints  = nil
            confirmed_real_player_faints = 0
            ev_faint_credit = 0; ev_outcome_loss = false  -- drop battle-scoped EvRing credits
            post_battle_frames = POST_BATTLE_GRACE
            memorialize_battle_cooldown = MEMORIALIZE_POST_BATTLE_COOLDOWN
            post_eob_frames    = POST_EOB_SAFETY_CAP
            pending_safe       = true
        else
        _battle_hp_cache   = {}  -- clear cache
        pending_battle_faints = {}  -- all deferred faints should be flushed by now
        pending_explosions    = {}  -- all coerced-Explosion entries settled by now
        force_fainted_keys    = {}  -- clear battle-scoped guard
        pending_faint_debounce = {}  -- clear any debounce state
        battle_start_player_faints  = nil
        confirmed_real_player_faints = 0
        ev_faint_credit = 0; ev_outcome_loss = false  -- drop battle-scoped EvRing credits
        post_battle_frames = POST_BATTLE_GRACE
        memorialize_battle_cooldown = MEMORIALIZE_POST_BATTLE_COOLDOWN
        post_eob_frames    = POST_EOB_SAFETY_CAP
        pending_safe       = true
        console.log("[SLink-FRLGE] [battle] end  grace window started")
        console.log(string.format(
            "[SLink-FRLGE] [battle] end: wild=%s captured=%s outcome=%d count=%d box=%s eob=%s",
            tostring(battle_is_wild), tostring(captured_this_battle),
            M.getBattleOutcome(), mem_u8(M.PARTY_COUNT_ADDR),
            battle_box_index ~= nil and tostring(battle_box_index) or "nil",
            tostring(eob_clear)))
        end -- not borrowed_battle
    end

    -- 6. Read party; diff sees correct HP (game writes back gBattleMons→party on battle end).
    -- Stats cache is merged into index_party() — no separate pass needed.
    local curr_party, party_count = index_party(in_battle)
    -- Now that Lua has its own view of the party, resolve any ring events waiting on it.
    if patch_present() then
        EV.owns = true          -- the ring now owns species-change detection
        ev_settle_xchecks(party_count)
    end

    -- ── PID-based borrowed-party detector ──────────────────────────────────
    -- Frame-accurate borrowed-party trigger.  Two sources of "real party
    -- PIDs" depending on profile:
    --   (a) CFRU/RR real-party backup buffer (M.REAL_PARTY_BACKUP_ADDR) —
    --       a live mirror that the engine maintains; authoritative.  Used
    --       when _backup_trusted (verified at startup that backup == live).
    --   (b) Path A snapshot: _stable_party_pids, updated after
    --       PID_STABILITY_WINDOW frames of no live changes.  Used for
    --       vanilla/AP profiles and as a safety fallback.
    -- Swap detection: ≥PID_SWAP_THRESHOLD slots in gPlayerParty differ
    -- from the reference.  Revert: all slots match the reference again.
    local _curr_pids = _read_party_pids()
    local _slot_changed = false
    for slot = 0, 5 do
        if _curr_pids[slot] ~= _last_party_pids[slot] then
            _slot_changed = true
            _last_party_pids[slot] = _curr_pids[slot]
        end
    end
    if _slot_changed then _last_pid_change_frame = frame_count end

    -- Authoritative borrowed-party signal from the companion patch (preferred over the
    -- PID heuristic when present).  `_auth_begin_edge` = the patch bumped `seq` this frame
    -- (CFRU just backed up the real party → a swap is beginning).  `_swap.active` reflects
    -- the live swap window.  Absent (nil) on unpatched ROMs / vanilla / AP — the PID
    -- heuristic below then drives the freeze exactly as before.
    local _swap = (MB ~= nil) and MB.read_swap_state() or nil
    local use_authoritative_swap = _swap ~= nil
    local _auth_begin_edge = false
    if _swap then
        if _last_swap_seq == nil then
            _last_swap_seq = _swap.seq          -- seed; never an edge on first observation
        elseif _swap.seq ~= _last_swap_seq then
            _last_swap_seq = _swap.seq
            _auth_begin_edge = true
        end
    end

    -- Bootstrap: if the profile has a real-party backup address, trust it
    -- the first time we observe (live party == backup) with a non-empty
    -- party.  This means we caught the engine in a quiet overworld state
    -- where the backup is correctly mirroring gPlayerParty.  After this
    -- point the detector uses the backup as the authoritative reference.
    if M.REAL_PARTY_BACKUP_ADDR and not _backup_trusted and _curr_pids[0] ~= 0 then
        local _bp = M.readBackupPartyPids()
        if _bp and _pids_all_match(_curr_pids, _bp) then
            _backup_trusted = true
            -- Seed the stable baseline so the cross-check has valid data
            -- from the moment backup trust is established.
            for i = 0, 5 do _stable_party_pids[i] = _curr_pids[i] end
            _last_pid_change_frame = frame_count
            console.log(string.format(
                "[SLink-FRLGE] real-party backup verified @ 0x%08X — using as authoritative reference",
                M.REAL_PARTY_BACKUP_ADDR))
        end
    end

    -- Always maintain stable baseline — tracks gradual party changes (catches,
    -- deposits) so the freeze detector never triggers on normal gameplay.
    -- Guarded by `not party_frozen` so the borrowed party never contaminates it.
    if not party_frozen and frame_count - _last_pid_change_frame >= PID_STABILITY_WINDOW then
        for i = 0, 5 do _stable_party_pids[i] = _curr_pids[i] end
    end

    -- Freeze detection always uses the stable baseline (tracks the real party
    -- through normal catches/deposits).  The backup buffer is NOT used here —
    -- it only updates before borrowed-party battles and goes stale otherwise.
    -- Gated on `not in_battle`: CFRU can cause transient PID glitches during
    -- battle (animation writebacks etc.) that resolve within 1-2 frames.
    -- Borrowed-party battles are already caught by isBorrowedBattle() at
    -- battle start; the PID detector is only needed for overworld transitions.
    local _pid_reverted = false
    if not party_frozen and not in_battle then
        -- Trigger source: authoritative patch signal (preferred) or the PID heuristic.
        local _do_freeze, _freeze_log = false, nil
        if use_authoritative_swap then
            -- The patch flagged the real-party backup this frame — a borrowed swap is
            -- beginning.  Threshold-free and false-positive-free: no compaction guard is
            -- needed because the engine genuinely backed the party up (vs. the heuristic,
            -- which can't tell a swap from a deposit-driven slot compaction).
            if _auth_begin_edge then
                _do_freeze  = true
                _freeze_log = "patch swap-begin (authoritative)"
            end
        else
            local diff = _pids_diff_count(_curr_pids, _stable_party_pids)
            if diff >= PID_SWAP_THRESHOLD then
                if _is_compaction_shift(_curr_pids, _stable_party_pids) then
                    -- All new PIDs are from the existing party — normal deposit or
                    -- withdrawal caused slot compaction.  Update stable baseline
                    -- immediately so subsequent frames don't re-trigger.
                    for i = 0, 5 do _stable_party_pids[i] = _curr_pids[i] end
                    _last_pid_change_frame = frame_count
                    console.log(string.format(
                        "[SLink-FRLGE] PID shift: %d/6 slots moved (party compaction, not a swap)",
                        diff))
                else
                    _do_freeze  = true
                    _freeze_log = string.format(
                        "PID SWAP: %d/6 slots differ from stable baseline", diff)
                end
            end
        end
        if _do_freeze then
            party_frozen           = true
            freeze_frames_left     = FREEZE_TIMEOUT_FRAMES
            pending_freeze_release = false
            pre_swap_pids          = {}
            for i = 0, 5 do pre_swap_pids[i] = _stable_party_pids[i] end
            pending_faint_debounce = {}
            gift_capture_buffer    = {}
            -- Discard any buffered party_to_box events — the "missing" keys
            -- were the real party that just got swapped out, not deposits.
            if #party_to_box_buffer > 0 then
                console.log(string.format(
                    "[SLink-FRLGE]   ↳ discarding %d buffered party_to_box (borrowed-party swap)",
                    #party_to_box_buffer))
                party_to_box_buffer = {}
            end
            -- Discard buffered box_to_party events (same reasoning — transient
            -- keys from the borrowed party are not real withdrawals).
            box_to_party_buffer = {}
            console.log("[SLink-FRLGE] ★ " .. _freeze_log .. "; freezing party diff")
        end
    else
        -- While frozen: revert = "live party matches the real party again".
        -- When backup is trusted, the engine saved the real party there before
        -- the swap — use it as the authoritative revert signal.
        -- Otherwise fall back to pre_swap_pids (stable baseline at freeze time).
        if _backup_trusted then
            local _bp = M.readBackupPartyPids()
            if _bp and _pids_all_match(_curr_pids, _bp) then
                _pid_reverted = true
            end
        elseif pre_swap_pids and _pids_all_match(_curr_pids, pre_swap_pids) then
            _pid_reverted = true
        end
    end

    -- ── party freeze: unfreeze check ───────────────────────────────────────────
    if party_frozen then
        -- Only count down timeout when NOT in battle — borrowed battles can
        -- last much longer than the timeout window.
        if not in_battle then
            freeze_frames_left = freeze_frames_left - 1
        end
        -- battle_just_ended is NOT a release trigger when backup is trusted:
        -- it fires before the engine restores gPlayerParty from the backup,
        -- causing a spurious "release then immediately re-freeze" cycle.
        -- The PID revert signal is authoritative and fires the moment the
        -- engine completes the restore.
        if not _backup_trusted
           and not pending_freeze_release and battle_just_ended then
            pending_freeze_release = true
            freeze_release_reason  = "battle ended"
        end
        -- Unfreeze immediately when PID revert is observed.  Covers two
        -- cases: (1) mid-overworld backout of a preview menu, (2) engine
        -- restores the real party after a borrowed-party battle ends.
        if _pid_reverted and not pending_freeze_release then
            pending_freeze_release = true
            freeze_release_reason  = "PID revert"
        end
        -- Authoritative end: the patch cleared `active` once gPlayerParty was restored
        -- from the backup (after the borrowed party diverged) — as authoritative as a PID
        -- revert, so release immediately (set _pid_reverted to bypass the eob gate below).
        if use_authoritative_swap and _swap.active == 0 then
            _pid_reverted = true
            if not pending_freeze_release then
                pending_freeze_release = true
                freeze_release_reason  = "patch swap-end (authoritative)"
            end
        end
        -- Release when: (a) trigger fired AND eob_clear, OR (b) trigger
        -- fired via PID revert (bypass eob gate — revert is authoritative),
        -- OR (c) timeout backstop.
        local force_timeout = freeze_frames_left <= 0
        if (pending_freeze_release and (eob_clear or _pid_reverted)) or force_timeout then
            local reason = force_timeout and "timeout"
                or freeze_release_reason or "unknown"
            console.log("[SLink-FRLGE] ★ PARTY UNFREEZE: " .. reason)
            party_frozen           = false
            pending_freeze_release = false
            freeze_release_reason  = nil
            pending_faint_debounce = {}  -- clear stale debounce state

            -- ── freeze-period catch recovery ────────────────────────────────────
            -- Catches that happened while frozen never fired their capture event
            -- (party_diff_ok was false).  Scan party + last-deposited box slot
            -- for unknown keys and emit recovery captures.
            --
            -- Party scan is gated on diff<=1 to avoid surfacing borrowed mons as
            -- fake captures when the engine restore is incomplete.  Box scan
            -- runs unconditionally whenever the recent outcome was CAUGHT —
            -- readLastPCDeposit() returns a specific engine-written slot, so
            -- false-positive risk is minimal, and this closes the case where
            -- pre_swap_pids was corrupted before the freeze triggered.
            do
                local ref_pids = pre_swap_pids or _stable_party_pids
                local recover_diff = _pids_diff_count(_curr_pids, ref_pids)
                local pre_swap_set = {}
                for i = 0, 5 do
                    local p = ref_pids[i] or 0
                    if p ~= 0 then pre_swap_set[p] = true end
                end
                local outcome = M.getBattleOutcome()
                local recent_caught_battle =
                    (outcome == M.OUTCOME_CAUGHT) and (battle_area_id ~= nil)
                local n_recovered = 0

                -- 2a — party scan (gated on diff<=1 to avoid borrowed mons)
                if recover_diff > 1 then
                    console.log(string.format(
                        "[SLink-FRLGE] party scan skipped: diff=%d > 1 (party may still hold borrowed mons)",
                        recover_diff))
                else
                    for k, info in pairs(curr_party) do
                        if not all_known_keys[k] and not sync_written_keys[k] then
                            local pid = tonumber((k:match("^(%x+):")) or "", 16)
                            if not (pid and pre_swap_set[pid]) then
                                local ok_ps, ps = pcall(M.readPartySlot, info.slot)
                                local cap_nick = ok_ps and ps and ps.nickname     or ""
                                local cap_sid  = ok_ps and ps and ps.species_id   or 0
                                local cap_iid  = ok_ps and ps and ps.held_item_id or 0
                                local cap_aid  = ok_ps and ps and ps.ability_id   or 0
                                local cap_flags = mem_u8(M.PARTY_BASE + info.slot * M.MON_SIZE + M.OFF_FLAGS)
                                local cap_is_egg = (cap_flags & FLAG_EGG) ~= 0
                                _display_cache[k] = {nickname=cap_nick, species_id=cap_sid,
                                                     held_item_id=cap_iid, ability_id=cap_aid}
                                if cap_nick ~= "" or cap_sid ~= 0 then
                                    nick_cache[k] = cap_nick ~= "" and cap_nick or ("#"..cap_sid)
                                end
                                local evt_area, recover_kind
                                if recent_caught_battle then
                                    evt_area     = battle_area_id
                                    recover_kind = "battle"
                                elseif in_battle then
                                    evt_area     = battle_area_id or area
                                    recover_kind = "battle"
                                else
                                    local gift_area
                                    if not nuzlocke_active then
                                        gift_area = "intro"
                                    elseif area ~= "" then
                                        gift_area = area
                                    else
                                        gift_area = "gift_" .. frame_map_g .. "_" .. frame_map_n
                                    end
                                    evt_area     = gift_area
                                    recover_kind = "gift"
                                end
                                all_known_keys[k] = true
                                if recover_kind == "battle" then
                                    captured_this_battle    = true
                                    resolved_areas[evt_area] = true
                                end
                                send({event="capture", key=k, hp=info.hp, maxHP=info.maxHP,
                                      level=info.level, area_id=evt_area,
                                      nickname=cap_nick, species_id=cap_sid,
                                      held_item_id=cap_iid, is_egg=cap_is_egg,
                                      gift=(recover_kind == "gift")},
                                     "capture(recovered-"..recover_kind.."):"..k:sub(1,8), true)
                                n_recovered = n_recovered + 1
                            end
                        end
                    end
                end  -- end party scan diff gate

                -- 2b — box scan (catch went to box because party was full).
                -- Runs unconditionally on OUTCOME_CAUGHT — readLastPCDeposit()
                -- returns a specific engine-written slot so the pre_swap_set +
                -- all_known_keys filters are enough to avoid false positives,
                -- and we don't need to rely on the diff gate (which can fail
                -- when pre_swap_pids was corrupted before the freeze fired).
                if recent_caught_battle and not captured_this_battle then
                    local dep_box, dep_slot = M.readLastPCDeposit()
                    if dep_box == nil or dep_box == M.MEMORIAL_BOX then
                        console.log("[SLink-FRLGE] recovery: box scan skipped (no PC deposit info)")
                    else
                        local slots_to_check
                        if dep_slot ~= nil then
                            slots_to_check = {dep_slot}
                        else
                            slots_to_check = {}
                            for si = 0, M.MONS_PER_BOX - 1 do
                                slots_to_check[#slots_to_check + 1] = si
                            end
                        end
                        for _, si in ipairs(slots_to_check) do
                            local baddr = M.boxMonAddr(dep_box, si)
                            if baddr and M.boxSlotOccupied(baddr) then
                                local k = M.monKey(baddr)
                                if k and not all_known_keys[k] and not sync_written_keys[k] then
                                    local pid = tonumber((k:match("^(%x+):")) or "", 16)
                                    if not (pid and pre_swap_set[pid]) then
                                        local bnick, bsid, biid = M.readBoxSlotDisplay(baddr, true)
                                        if bnick ~= "" or bsid ~= 0 then
                                            nick_cache[k] = bnick ~= "" and bnick or ("#"..bsid)
                                        end
                                        -- Stats from gBattleMons[1] (mirrors lines 2278-2309).
                                        -- Sanity-check maxHP >= level so a partially-cleared
                                        -- struct doesn't ship nonsense stats to the server.
                                        local box_stats, box_lv, box_maxHP = nil, 0, 0
                                        if M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0 then
                                            local foe_base = M.BATTLE_MONS_ADDR + 1 * M.BATTLE_MON_SIZE
                                            local ok_lv, elv = pcall(memory.read_u8,     foe_base + 0x2A)
                                            local ok_mh, emh = pcall(memory.read_u16_le, foe_base + 0x2C)
                                            local ok_at, eat = pcall(memory.read_u16_le, foe_base + 0x02)
                                            local ok_de, ede = pcall(memory.read_u16_le, foe_base + 0x04)
                                            local ok_sp, esp = pcall(memory.read_u16_le, foe_base + 0x06)
                                            local ok_sa, esa = pcall(memory.read_u16_le, foe_base + 0x08)
                                            local ok_sd, esd = pcall(memory.read_u16_le, foe_base + 0x0A)
                                            box_lv    = (ok_lv and elv and elv > 0) and elv or 0
                                            local mhp = (ok_mh and emh and emh > 0) and emh or 0
                                            -- gBattleMons[1] may be partly cleared post-catch;
                                            -- only ship stats when maxHP is plausible (>= level).
                                            if box_lv > 0 and mhp >= box_lv then
                                                box_maxHP = mhp
                                                box_stats = {
                                                    level   = box_lv,
                                                    maxHP   = mhp,
                                                    attack  = ok_at and eat or 0,
                                                    defense = ok_de and ede or 0,
                                                    speed   = ok_sp and esp or 0,
                                                    spAtk   = ok_sa and esa or 0,
                                                    spDef   = ok_sd and esd or 0,
                                                }
                                            end
                                            if bsid == 0 then
                                                local ok_es, esid = pcall(memory.read_u16_le, foe_base + 0x00)
                                                bsid = (ok_es and esid and esid > 0) and esid or 0
                                            end
                                        end
                                        all_known_keys[k] = true
                                        captured_this_battle     = true
                                        resolved_areas[battle_area_id] = true
                                        send({event="capture", key=k, area_id=battle_area_id,
                                              in_box=true, level=box_lv, maxHP=box_maxHP,
                                              nickname=bnick, species_id=bsid,
                                              held_item_id=biid, stats=box_stats},
                                             "capture(recovered-box):"..k:sub(1,8), true)
                                        n_recovered = n_recovered + 1
                                        break  -- one box catch per battle
                                    end
                                end
                            end
                        end
                    end
                end

                if n_recovered > 0 then
                    console.log(string.format(
                        "[SLink-FRLGE] recovered %d capture(s) on unfreeze (diff=%d, in_battle=%s, outcome=%d)",
                        n_recovered, recover_diff, tostring(in_battle), outcome))
                end
            end

            -- Reset PID detector state so the next swap re-baselines cleanly.
            pre_swap_pids            = nil
            for i = 0, 5 do _stable_party_pids[i] = _curr_pids[i] end
            _last_pid_change_frame   = frame_count
            -- Start settle period: keep prev_party synced for a few frames
            -- before allowing party diffs, so the game has time to restore
            -- the real party after a borrowed-party battle.
            post_unfreeze_frames = POST_UNFREEZE_SETTLE
            -- Resync baseline so the next diff doesn't compare stale prev_party
            -- against the current (possibly changed) party.
            prev_party = curr_party
            gift_capture_buffer  = {}
            party_to_box_buffer  = {}  -- any pre-freeze deposits are no longer trustworthy
            box_to_party_buffer  = {}  -- any pre-freeze withdrawals are no longer trustworthy
        end
    end

    -- ── party diff gate ─────────────────────────────────────────────────────
    -- Only diff party keys when in a trustworthy game state.  During menus
    -- (bag / Repel / etc.) BizHawk memory reads can return transient garbage,
    -- producing phantom party changes.  We freeze prev_party and skip all
    -- party-change detection while in those states.
    -- For vanilla ROMs isInOverworld() == not isInBattle(), so this is always true.
    -- Borrowed-party battles: completely freeze party diff — the party RAM
    -- contains another trainer's mons and must not trigger any events.
    -- Post-unfreeze settle: suppress diffs while game restores real party.
    if post_unfreeze_frames > 0 then
        post_unfreeze_frames = post_unfreeze_frames - 1
    end
    local party_diff_ok = not borrowed_battle and not party_frozen
        and post_unfreeze_frames == 0
        and not pending_trade_apply         -- freeze the diff for the whole trade (party swaps mid-scene)
        and not pending_storage             -- freeze the diff while a native deposit/withdraw is in flight
        and (in_battle or post_battle_frames > 0 or is_overworld)

    if party_diff_ok then

    -- ── nature change detection (RR Nature Changer NPC) ──────────────────────
    -- In Radical Red, changing a mon's nature modifies the personality value,
    -- which changes the monKey.  Detect this by matching disappeared/appeared
    -- keys on otId + species + level + nickname (all unchanged by nature edit).
    -- Must run BEFORE capture/faint diff so false events are suppressed.
    -- Suppressed while gift buffer has entries — mass party swaps produce false
    -- signature matches that corrupt local state.
    local key_migrated = {}  -- old_key → true AND new_key → true (skip downstream diff loops)
    -- A completed TRADE is a known key change: suppress the swap's capture/box diff for both keys (the
    -- server already reconciled the link via trade_done; do NOT emit a key_change here — that path is
    -- for same-mon PID changes, and the cross-player swap is handled server-side). Drop the traded-away
    -- mon's caches; the received mon's are repopulated by the normal party read.
    if pending_trade_migration then
        local old_k, new_k = pending_trade_migration.old, pending_trade_migration.new
        key_migrated[old_k] = true
        key_migrated[new_k] = true
        all_known_keys[old_k] = nil; all_known_keys[new_k] = true
        sync_written_keys[new_k] = true
        _display_cache[old_k] = nil; nick_cache[old_k] = nil; _ability_cache[old_k] = nil
        mon_stats_cache[old_k] = nil
        console.log(string.format("[SLink-FRLGE] trade key migration: %s -> %s", old_k:sub(1,8), new_k:sub(1,8)))
        pending_trade_migration = nil
        -- Purge any box/party sync commands the server queued for the swapped keys during the trade
        -- (deferred, not executed, while pending_trade_apply was set) — they're stale now that the mon
        -- has moved players, and would otherwise fail ("key not found in any box") or move the wrong mon.
        do
            local kept = {}
            for _, p in ipairs(pending_sync_cmds) do
                if p.key ~= old_k and p.key ~= new_k then kept[#kept + 1] = p end
            end
            pending_sync_cmds = kept
        end
        -- Settle window: the native trade scene just rewrote a party slot. Baseline the received mon
        -- into prev_party RIGHT NOW (so the disappeared/appeared loops below see no change this frame)
        -- and freeze diffs for a few more frames while the game finishes settling the party — otherwise
        -- the traded-in mon (a brand-new key) gets mis-read as a fresh capture and triggers the box /
        -- "Unbox this POKeMON?" prompt the user saw mid-trade.
        prev_party = curr_party
        post_unfreeze_frames = POST_UNFREEZE_SETTLE
    end
    if #gift_capture_buffer == 0 then
    do
        local disappeared, appeared = {}, {}
        for k, _ in pairs(prev_party) do
            if not curr_party[k] then disappeared[#disappeared+1] = k end
        end
        for k, info in pairs(curr_party) do
            if not prev_party[k] and not sync_written_keys[k] then
                appeared[#appeared+1] = {key=k, slot=info.slot}
            end
        end
        if #disappeared > 0 and #appeared > 0 then
            -- Build signature for each disappeared key from cached data.
            -- Signature: otId .. ":" .. species_id .. ":" .. level .. ":" .. nickname
            local dis_sigs = {}  -- sig → old_key (only unique sigs)
            local dis_dups = {}  -- sig → true if seen more than once
            for _, old_k in ipairs(disappeared) do
                local parts = old_k:match(":(.+)")  -- otId portion of "personality:otId"
                local dc = _display_cache[old_k]
                local prev_info = prev_party[old_k]
                if parts and dc and prev_info then
                    local sig = parts..":"
                              ..(dc.species_id or 0)..":"
                              ..(prev_info.level or 0)..":"
                              ..(dc.nickname or "")
                    if dis_sigs[sig] then
                        dis_dups[sig] = true  -- ambiguous: two mons share this sig
                    else
                        dis_sigs[sig] = old_k
                    end
                end
            end
            -- Match each appeared key against disappeared signatures.
            for _, app in ipairs(appeared) do
                local new_k = app.key
                local new_parts = new_k:match(":(.+)")
                -- Fresh read for the new key (personality changed, so re-read everything).
                local ok_ps, ps = pcall(M.readPartySlot, app.slot)
                if new_parts and ok_ps and ps then
                    local new_info = curr_party[new_k]
                    local sig = new_parts..":"
                              ..(ps.species_id or 0)..":"
                              ..(new_info and new_info.level or 0)..":"
                              ..(ps.nickname or "")
                    local old_k = dis_sigs[sig]
                    if old_k and not dis_dups[sig] then
                        -- 1:1 match — this is a nature change, not a new capture.
                        console.log(string.format("[SLink-FRLGE] nature change detected: %s → %s", old_k:sub(1,8), new_k:sub(1,8)))
                        key_migrated[old_k] = true
                        key_migrated[new_k] = true

                        -- Migrate tracking state: old key → new key
                        all_known_keys[old_k] = nil
                        all_known_keys[new_k] = true

                        -- Fresh display cache from readPartySlot (don't clone old —
                        -- ability may change since it depends on personality).
                        _display_cache[old_k] = nil
                        _display_cache[new_k] = {
                            nickname     = ps.nickname     or "",
                            species_id   = ps.species_id   or 0,
                            held_item_id = ps.held_item_id or 0,
                            ability_id   = ps.ability_id   or 0,
                        }

                        -- Nick cache
                        nick_cache[new_k] = nick_cache[old_k]
                        nick_cache[old_k] = nil

                        -- Ability cache (clear — may have changed with personality)
                        _ability_cache[old_k] = nil

                        -- Stats cache
                        mon_stats_cache[new_k] = mon_stats_cache[old_k]
                        mon_stats_cache[old_k] = nil

                        -- Sync written keys
                        if sync_written_keys[old_k] then
                            sync_written_keys[old_k] = nil
                            sync_written_keys[new_k] = true
                        end

                        -- Faint debounce / force-faint / battle caches
                        if pending_faint_debounce[old_k] then
                            pending_faint_debounce[new_k] = pending_faint_debounce[old_k]
                            pending_faint_debounce[old_k] = nil
                        end
                        if force_fainted_keys[old_k] then
                            force_fainted_keys[new_k] = true
                            force_fainted_keys[old_k] = nil
                        end
                        if _battle_hp_cache[old_k] then
                            _battle_hp_cache[new_k] = _battle_hp_cache[old_k]
                            _battle_hp_cache[old_k] = nil
                        end
                        if pending_battle_faints[old_k] then
                            pending_battle_faints[new_k] = true
                            pending_battle_faints[old_k] = nil
                        end
                        if pending_explosions[old_k] then
                            pending_explosions[new_k] = pending_explosions[old_k]
                            pending_explosions[old_k] = nil
                        end

                        -- Pending sync commands referencing old key
                        for _, sc in ipairs(pending_sync_cmds) do
                            if sc.key == old_k then sc.key = new_k end
                        end

                        -- Buffered box_to_party/party_to_box referencing old key
                        for _, buf in ipairs(box_to_party_buffer) do
                            if buf.key == old_k then buf.key = new_k end
                        end
                        for _, buf in ipairs(party_to_box_buffer) do
                            if buf.key == old_k then buf.key = new_k end
                        end

                        -- Notify server
                        send({event="key_change", old_key=old_k, new_key=new_k},
                             "key_change:"..old_k:sub(1,8).."->"..new_k:sub(1,8), true)
                    end
                end
            end
        end

    end
    end -- #gift_capture_buffer == 0

    -- ── capture (party, battle-scoped or gift/box) ────────────────────────────
    for k, info in pairs(curr_party) do
        if not prev_party[k] and not sync_written_keys[k] and not key_migrated[k] then
            -- Read display data for this party slot (pcall-guarded).
            local ok_ps, ps = pcall(M.readPartySlot, info.slot)
            local cap_nick = ok_ps and ps and ps.nickname      or ""
            local cap_sid  = ok_ps and ps and ps.species_id    or 0
            local cap_iid  = ok_ps and ps and ps.held_item_id  or 0
            local cap_aid  = ok_ps and ps and ps.ability_id    or 0
            -- isEgg = FLAGS bit 2 — definitive egg detection (NPC gifts + daycare).
            local cap_flags  = mem_u8(M.PARTY_BASE + info.slot * M.MON_SIZE + M.OFF_FLAGS)
            local cap_is_egg = (cap_flags & FLAG_EGG) ~= 0
            -- Populate display + nick caches so snapshot/HUD use fresh data.
            _display_cache[k] = {nickname=cap_nick, species_id=cap_sid,
                                 held_item_id=cap_iid, ability_id=cap_aid}
            if cap_nick ~= "" or cap_sid ~= 0 then
                nick_cache[k] = cap_nick ~= "" and cap_nick or ("#"..cap_sid)
            end
            if (in_battle or post_battle_frames > 0) and not all_known_keys[k] then
                local evt_area = battle_area_id or area
                captured_this_battle     = true
                resolved_areas[evt_area] = true
                all_known_keys[k]        = true
                send({event="capture", key=k, hp=info.hp, maxHP=info.maxHP,
                      level=info.level, area_id=evt_area,
                      nickname=cap_nick, species_id=cap_sid, held_item_id=cap_iid,
                      is_egg=cap_is_egg},
                     "capture(battle):"..k:sub(1,8), true)
            elseif all_known_keys[k] then
                -- Previously seen key reappeared → buffer for confirmation.
                -- Cross-cancel any pending party_to_box for this key (flicker protection).
                for pi = #party_to_box_buffer, 1, -1 do
                    if party_to_box_buffer[pi].key == k then
                        table.remove(party_to_box_buffer, pi)
                    end
                end
                -- Dedup: skip if already buffered.
                local already_buffered = false
                for _, buf in ipairs(box_to_party_buffer) do
                    if buf.key == k then already_buffered = true; break end
                end
                if not already_buffered then
                    box_to_party_buffer[#box_to_party_buffer + 1] = {
                        key = k, frame = frame_count
                    }
                end
            else
                -- New key outside battle → gift/starter/trade
                -- Before nuzlocke_active (no Pokéballs), this is always the starter —
                -- use "intro" so both players link regardless of randomized start location.
                -- Post-nuzlocke gifts (Eevee, Lapras, fossils) use their real area_id.
                -- If the map isn't in areas.lua, use "gift_<group>_<num>" so each
                -- unmapped gift location gets a unique area_id (prevents collisions).
                local gift_area
                if not nuzlocke_active then
                    gift_area = "intro"
                else
                    if area ~= "" then
                        gift_area = area
                    else
                        gift_area = "gift_" .. frame_map_g .. "_" .. frame_map_n
                    end
                end
                -- Don't set all_known_keys yet — deferred to buffer flush so we
                -- can cleanly discard borrowed-party gifts without rollback.
                -- Dedup: skip if already in the buffer (e.g. prev_party wasn't updated).
                local already_buffered = false
                for _, buf in ipairs(gift_capture_buffer) do
                    if buf.key == k then already_buffered = true; break end
                end
                if not already_buffered then
                    gift_capture_buffer[#gift_capture_buffer + 1] = {
                        key=k, hp=info.hp, maxHP=info.maxHP, level=info.level,
                        area=gift_area, nickname=cap_nick, species_id=cap_sid,
                        held_item_id=cap_iid, is_egg=cap_is_egg, frame=frame_count
                    }
                    -- Note: borrowed-party detection no longer keys off
                    -- buffer length; the PID detector fires earlier and
                    -- on a more authoritative signal.  Buffer remains
                    -- a 45-frame delivery delay so a late-arriving swap
                    -- can retroactively cancel pending captures.
                end
            end
        end
    end

    -- ── faint + party_to_box ─────────────────────────────────────────────────
    local had_alive = false
    local all_zero  = true
    local real_faint_occurred = false  -- track if any non-force faint happened
    for k, prev_info in pairs(prev_party) do
        local curr_info = curr_party[k]
        if key_migrated[k] then
            -- Key migrated (nature change): old key vanished but handled — not a real disappearance.
            all_zero = false
        elseif curr_info then
            -- Key still in party
            if prev_info.hp > 0 then had_alive = true end
            if prev_info.hp > 0 and curr_info.hp == 0 and not party_frozen then
                -- Don't re-report faints that we caused via force_faint command,
                -- or that are pending deferral (active battler awaiting switch-out).
                if force_fainted_keys[k] then
                    console.log("[SLink-FRLGE]   ↳ faint suppressed (force_fainted) key="..k:sub(1,8))
                elseif pending_battle_faints[k] then
                    console.log("[SLink-FRLGE]   ↳ faint suppressed (pending_battle_faint) key="..k:sub(1,8))
                elseif pending_explosions[k] then
                    console.log("[SLink-FRLGE]   ↳ faint suppressed (exploding) key="..k:sub(1,8))
                elseif in_battle then
                    -- In-battle: start debounce instead of sending immediately.
                    -- CFRU may show transient HP=0 before abilities (Sturdy, Focus Sash)
                    -- restore HP on the next frame.
                    if not pending_faint_debounce[k] then
                        pending_faint_debounce[k] = FAINT_DEBOUNCE_FRAMES
                        console.log("[SLink-FRLGE]   ↳ faint debounce started key="..k:sub(1,8).." frames="..FAINT_DEBOUNCE_FRAMES)
                    end
                else
                    -- Overworld: party struct is authoritative, send immediately.
                    send({event="faint", key=k, area_id=area},
                         "faint:"..k:sub(1,8), true)
                    real_faint_occurred = true
                end
            end
            -- If HP recovered, cancel any pending debounce (Sturdy/Endure/Focus Sash).
            if curr_info and curr_info.hp > 0 then
                if pending_faint_debounce[k] then
                    console.log("[SLink-FRLGE]   ↳ faint debounce CANCELLED (HP recovered) key="..k:sub(1,8))
                    pending_faint_debounce[k] = nil
                end
                all_zero = false
            end
        else
            -- Key disappeared from party → party_to_box.
            -- Key-based tracking means only genuine deposits hit this path
            -- (party reorders keep both keys present in curr_party).
            -- BUFFERED for PARTY_TO_BOX_BUFFER_WINDOW frames so a borrowed-party
            -- swap that starts on this frame can trigger the PID detector and
            -- cancel the event before it goes out.  Without this buffer, the
            -- first slot rewrite of a swap fires a spurious party_to_box for
            -- whatever was in slot 0 (e.g. Charmander).
            -- Cross-cancel any pending box_to_party for this key (flicker protection).
            for pi = #box_to_party_buffer, 1, -1 do
                if box_to_party_buffer[pi].key == k then
                    table.remove(box_to_party_buffer, pi)
                end
            end
            if not in_battle and prev_info.hp > 0 and not sync_written_keys[k]
               and not party_frozen then
                local already_buffered = false
                for _, buf in ipairs(party_to_box_buffer) do
                    if buf.key == k then already_buffered = true; break end
                end
                if not already_buffered then
                    local st = mon_stats_cache[k]
                    local stats_tbl = st and {level=st.level, maxHP=st.maxHP,
                        attack=st.attack, defense=st.defense, speed=st.speed,
                        spAtk=st.spAtk, spDef=st.spDef,
                        pp1=st.pp1, pp2=st.pp2, pp3=st.pp3, pp4=st.pp4} or nil
                    party_to_box_buffer[#party_to_box_buffer + 1] = {
                        key = k, stats = stats_tbl, frame = frame_count
                    }
                end
            end
            all_zero = false  -- gone from party, can't be all-zero anymore
        end
    end

    -- ── debounce: in-battle faint confirmation ──────────────────────────────
    -- Keys must remain at HP=0 for FAINT_DEBOUNCE_FRAMES before confirming,
    -- UNLESS gBattleResults.playerFaintCounter has already incremented past
    -- the count we've credited — that's an authoritative "Cmd_tryfaintmon
    -- committed a faint" signal (post-Sturdy/Focus-Sash/Endure resolution),
    -- so we can skip the timer.
    --
    -- Fast-path safety: only fire when EXACTLY ONE key is pending. With
    -- multiple pending we can't safely pick which one to credit (pairs()
    -- order is undefined) — fall through to the timer, which gives time
    -- for transient HP=0 to recover.
    local n_pending = 0
    for _ in pairs(pending_faint_debounce) do n_pending = n_pending + 1 end
    local curr_pfc = nil
    if n_pending == 1 and battle_start_player_faints then
        curr_pfc = (M.readFaintCounters())
    end

    for k, frames_left in pairs(pending_faint_debounce) do
        local ci = curr_party[k]
        if not ci or ci.hp > 0 then
            -- HP recovered or mon left party — cancel debounce.
            if ci and ci.hp > 0 then
                console.log("[SLink-FRLGE]   ↳ faint debounce CANCELLED (HP recovered) key="..k:sub(1,8))
            end
            pending_faint_debounce[k] = nil
        elseif force_fainted_keys[k] or pending_battle_faints[k] or pending_explosions[k] then
            -- Server already force-fainted this mon, faint is pending deferral
            -- (active battler awaiting switch-out), or the mon was coerced into
            -- Exploding — don't double-report.
            pending_faint_debounce[k] = nil
        elseif ev_faint_credit > 0 and n_pending == 1 then
            -- Fast-path (EvRing, patched): the patch pushed a settled EV_PLAYER_FAINT —
            -- the engine committed the faint after protection resolved. Same single-pending
            -- safety rule as the counter path (the ring doesn't say WHICH key). Bump the
            -- counter credit too so the polled fast-path can't double-fire for this faint.
            pending_faint_debounce[k] = nil
            ev_faint_credit = ev_faint_credit - 1
            confirmed_real_player_faints = confirmed_real_player_faints + 1
            console.log("[SLink-FRLGE]   ↳ faint CONFIRMED via EvRing event key="..k:sub(1,8))
            send({event="faint", key=k, area_id=area},
                 "faint:"..k:sub(1,8), true)
            real_faint_occurred = true
        elseif curr_pfc
               and (curr_pfc - battle_start_player_faints) > confirmed_real_player_faints then
            -- Fast-path: counter delta exceeds the count we've already credited.
            pending_faint_debounce[k] = nil
            confirmed_real_player_faints = confirmed_real_player_faints + 1
            -- The ring pushed an event for this same faint; eat it so it can't go stale.
            if ev_faint_credit > 0 then ev_faint_credit = ev_faint_credit - 1 end
            console.log("[SLink-FRLGE]   ↳ faint CONFIRMED via gBattleResults delta key="..k:sub(1,8))
            send({event="faint", key=k, area_id=area},
                 "faint:"..k:sub(1,8), true)
            real_faint_occurred = true
        else
            frames_left = frames_left - 1
            if frames_left <= 0 then
                -- Confirmed via timer fallback.
                pending_faint_debounce[k] = nil
                -- A real faint also pushed a ring event; consume it so it can't go stale.
                if ev_faint_credit > 0 then ev_faint_credit = ev_faint_credit - 1 end
                console.log("[SLink-FRLGE]   ↳ faint debounce CONFIRMED key="..k:sub(1,8))
                send({event="faint", key=k, area_id=area},
                     "faint:"..k:sub(1,8), true)
                real_faint_occurred = true
            else
                pending_faint_debounce[k] = frames_left
            end
        end
    end

    -- ── whiteout ─────────────────────────────────────────────────────────────
    -- Don't declare whiteout while faint debounce is in progress — some of
    -- those HP=0 readings may be transient (Sturdy/Focus Sash recovery).
    -- EvRing fast-path: the engine's own EV_OUTCOME==2 (LOSS) edge also qualifies —
    -- it can land a frame after the last faint was confirmed, when
    -- real_faint_occurred is no longer set this pass. One-shot (consumed on send).
    if had_alive and all_zero and not party_frozen
       and (real_faint_occurred or ev_outcome_loss)
       and not next(pending_faint_debounce) then
        ev_outcome_loss = false
        M.playSE(M.SE_BOO)
        send({event="whiteout"}, "whiteout", true)
    end

    end -- party_diff_ok

    -- ── party_to_box buffer: flush confirmed deposits ───────────────────────
    -- Entries older than PARTY_TO_BOX_BUFFER_WINDOW are confirmed real (no
    -- swap triggered) and sent.  If party_frozen was triggered, the buffer
    -- was already cleared by the PID detector.
    -- Presence validation: only fire if key is STILL absent from curr_party.
    if #party_to_box_buffer > 0 and not party_frozen and not borrowed_battle then
        local i = 1
        while i <= #party_to_box_buffer do
            local buf = party_to_box_buffer[i]
            if frame_count - buf.frame >= PARTY_TO_BOX_BUFFER_WINDOW then
                if not curr_party[buf.key] then
                    send({event="party_to_box", key=buf.key, stats=buf.stats},
                         "party_to_box:"..buf.key:sub(1,8), true)
                end
                table.remove(party_to_box_buffer, i)
            else
                i = i + 1
            end
        end
    end

    -- ── box_to_party buffer: flush confirmed withdrawals ─────────────────────
    -- Entries older than BOX_TO_PARTY_BUFFER_WINDOW are confirmed real and sent.
    -- Presence validation: only fire if key is STILL in curr_party.
    if #box_to_party_buffer > 0 and not party_frozen and not borrowed_battle then
        local i = 1
        while i <= #box_to_party_buffer do
            local buf = box_to_party_buffer[i]
            if frame_count - buf.frame >= BOX_TO_PARTY_BUFFER_WINDOW then
                if curr_party[buf.key] then
                    send({event="box_to_party", key=buf.key, area_id=area},
                         "box_to_party:"..buf.key:sub(1,8), true)
                end
                table.remove(box_to_party_buffer, i)
            else
                i = i + 1
            end
        end
    end

    -- ── gift capture buffer: flush confirmed gifts ──────────────────────────
    -- Entries older than GIFT_BUFFER_WINDOW are confirmed real and sent.
    -- If party_frozen was triggered, the buffer was already cleared.
    if #gift_capture_buffer > 0 and not party_frozen and not borrowed_battle then
        local i = 1
        while i <= #gift_capture_buffer do
            local buf = gift_capture_buffer[i]
            if frame_count - buf.frame >= GIFT_BUFFER_WINDOW then
                all_known_keys[buf.key] = true
                sync_cooldown = math.max(sync_cooldown, GIFT_COOLDOWN_FRAMES)
                send({event="capture", key=buf.key, hp=buf.hp, maxHP=buf.maxHP,
                      level=buf.level, area_id=buf.area,
                      nickname=buf.nickname, species_id=buf.species_id,
                      held_item_id=buf.held_item_id, is_egg=buf.is_egg, gift=true},
                     "capture(gift):"..buf.key:sub(1,8), true)
                table.remove(gift_capture_buffer, i)
            else
                i = i + 1
            end
        end
    end

    -- ── post-battle grace window ──────────────────────────────────────────────
    if memorialize_battle_cooldown > 0 then
        memorialize_battle_cooldown = memorialize_battle_cooldown - 1
    end
    if post_eob_frames > 0 then
        -- Only count down once the engine has actually transitioned to the
        -- "return from battle" function (gBattleMainFunc == RETURN_FROM_BATTLE_ADDR).
        -- Otherwise the cap exhausts on player input timing: slow post-battle
        -- dialog clicking keeps gBattleMainFunc stuck in the dialog handler,
        -- and the bridge would falsely warn while EOB hasn't even started.
        -- Profiles without these addresses (AP) fall through and count down
        -- normally (no engine-state gate available).
        local engine_eob_done = true
        if M.BATTLE_MAIN_FUNC_ADDR and M.RETURN_FROM_BATTLE_ADDR then
            local ok, v = pcall(memory.read_u32_le, M.BATTLE_MAIN_FUNC_ADDR)
            engine_eob_done = ok and v == M.RETURN_FROM_BATTLE_ADDR
        end
        if engine_eob_done then
            post_eob_frames = post_eob_frames - 1
            if post_eob_frames == 0 and not M.isPostBattleSettled() then
                console.log("[SLink-FRLGE] post-EOB safety cap exhausted; isPostBattleSettled still false. "
                    .. "Sync writes will proceed; if a corruption follows, the profile's "
                    .. "POST_BATTLE_WRITER_TASKS set likely needs another discovery run "
                    .. "(test_post_eob_settle_discovery.lua) on the battle type that just happened.")
            end
        end
    end
    if post_battle_frames > 0 then
        post_battle_frames = post_battle_frames - 1

        if battle_box_index ~= nil and not captured_this_battle then
            -- Slot-based detection: find newly occupied slots since battle start.
            -- This works even when the caught mon has the same PID as a dead mon
            -- already in the box (key-based diff would miss it).
            local new_slots = {}
            for slot = 0, M.MONS_PER_BOX - 1 do
                if not battle_box_snapshot[slot] then
                    local addr = M.boxMonAddr(battle_box_index, slot)
                    if addr and M.boxSlotOccupied(addr) then
                        new_slots[#new_slots + 1] = {slot = slot, addr = addr}
                    end
                end
            end
            if #new_slots == 1 then
                local ns = new_slots[1]
                local k = M.monKey(ns.addr)
                local evt_area = battle_area_id or area
                captured_this_battle     = true
                resolved_areas[evt_area] = true
                all_known_keys[k]        = true
                -- Get display data directly from the new slot address.
                local bnick, bsid, biid = M.readBoxSlotDisplay(ns.addr, true)
                if bnick ~= "" or bsid ~= 0 then
                    nick_cache[k] = bnick ~= "" and bnick or ("#"..bsid)
                end
                -- Read stats from gBattleMons[1] which persists in EWRAM post-battle.
                local box_stats = nil
                local box_lv = 0
                local box_maxHP = 0
                if M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0 then
                    local foe_base = M.BATTLE_MONS_ADDR + 1 * M.BATTLE_MON_SIZE
                    local ok_lv, elv   = pcall(memory.read_u8,     foe_base + 0x2A)
                    local ok_mh, emh   = pcall(memory.read_u16_le, foe_base + 0x2C)
                    local ok_at, eat   = pcall(memory.read_u16_le, foe_base + 0x02)
                    local ok_de, ede   = pcall(memory.read_u16_le, foe_base + 0x04)
                    local ok_sp, esp   = pcall(memory.read_u16_le, foe_base + 0x06)
                    local ok_sa, esa   = pcall(memory.read_u16_le, foe_base + 0x08)
                    local ok_sd, esd   = pcall(memory.read_u16_le, foe_base + 0x0A)
                    box_lv = (ok_lv and elv and elv > 0) and elv or 0
                    box_maxHP = (ok_mh and emh and emh > 0) and emh or 0
                    if box_lv > 0 and box_maxHP > 0 then
                        box_stats = {
                            level   = box_lv,
                            maxHP   = box_maxHP,
                            attack  = ok_at and eat or 0,
                            defense = ok_de and ede or 0,
                            speed   = ok_sp and esp or 0,
                            spAtk   = ok_sa and esa or 0,
                            spDef   = ok_sd and esd or 0,
                        }
                    end
                    -- Fallback species from gBattleMons if box decrypt failed.
                    if bsid == 0 then
                        local ok_es, esid = pcall(memory.read_u16_le, foe_base + 0x00)
                        bsid = (ok_es and esid and esid > 0) and esid or 0
                    end
                end
                -- Always send level and maxHP as top-level fields so the server
                -- can cache them even when full box_stats is unavailable.
                send({event="capture", key=k, area_id=evt_area, in_box=true,
                      level=box_lv, maxHP=box_maxHP, nickname=bnick,
                      species_id=bsid, held_item_id=biid, stats=box_stats},
                     "capture(box):"..k:sub(1,8), true)
            elseif #new_slots > 1 then
                captured_this_battle = true
                console.log(string.format("[SLink-FRLGE] box: %d new slots — ambiguous, no_catch suppressed", #new_slots))
            else
                -- No new slot in the battle-start box. The game auto-advanced to a
                -- different box after the catch (box was full). Use the engine's own
                -- deposit bookkeeping to locate the slot without a full-box scan.
                if M.getBattleOutcome() == M.OUTCOME_CAUGHT then
                    -- Three-tier approach using the engine's own deposit bookkeeping:
                    --   Tier 1 — EWRAM gSpecialVar_MonBoxId + MonBoxPos (vanilla/CFRU): O(1)
                    --   Tier 2 — SaveBlock1 VAR_PC_BOX_TO_SEND_MON (all profiles):     O(30)
                    --   Tier 3 — full scan across all boxes (Emerald / no info):        O(750)
                    -- Tier 3 also runs if Tier 2 finds nothing (guards against stale vars).
                    local new_key, found_count = nil, 0
                    local dep_box, dep_slot = M.readLastPCDeposit()

                    -- Tier 1: exact slot known — single direct read.
                    if dep_box ~= nil and dep_box ~= M.MEMORIAL_BOX and dep_slot ~= nil then
                        local k = M.boxMonKey(dep_box, dep_slot)
                        if k and not all_known_keys[k] then
                            found_count, new_key = 1, k
                        else
                            -- EWRAM special vars stale: box and slot are written as a pair
                            -- by SendMonToPC, so distrust both.  Re-read box from the
                            -- persistent SB1 var (VAR_PC_BOX_TO_SEND_MON) instead.
                            console.log("[SLink-FRLGE] box: EWRAM deposit vars stale, re-reading box from SB1")
                            dep_box  = M.readSB1Var(M.VAR_PC_BOX_TO_SEND_MON)
                            dep_slot = nil
                            if dep_box and (dep_box >= M.BOXES_PER_STORE or dep_box == M.MEMORIAL_BOX) then
                                dep_box = nil  -- out of range; will trigger Tier 3
                            end
                        end
                    end

                    -- Tier 2: box known, slot unknown — scan just that box.
                    if new_key == nil and dep_box ~= nil and dep_box ~= M.MEMORIAL_BOX then
                        for si = 0, M.MONS_PER_BOX - 1 do
                            local k = M.boxMonKey(dep_box, si)
                            if k and not all_known_keys[k] then
                                found_count = found_count + 1
                                new_key = k
                            end
                        end
                    end

                    -- Tier 3: no deposit info, or Tier 2 found nothing (var may be stale).
                    if new_key == nil and found_count == 0 then
                        console.log("[SLink-FRLGE] box: deposit VAR miss; full scan fallback")
                        for bi = 0, M.BOXES_PER_STORE - 1 do
                            if bi ~= M.MEMORIAL_BOX then
                                for si = 0, M.MONS_PER_BOX - 1 do
                                    local k = M.boxMonKey(bi, si)
                                    if k and not all_known_keys[k] then
                                        found_count = found_count + 1
                                        new_key = k
                                    end
                                end
                            end
                        end
                    end

                    if found_count == 1 then
                        local evt_area = battle_area_id or area
                        captured_this_battle    = true
                        all_known_keys[new_key] = true
                        resolved_areas[evt_area] = true
                        local _, _, baddr = M.scanBoxForKey(new_key)
                        local bnick, bsid, biid = baddr and M.readBoxSlotDisplay(baddr, true) or "", 0, 0
                        if bnick ~= "" or bsid ~= 0 then
                            nick_cache[new_key] = bnick ~= "" and bnick or ("#"..bsid)
                        end
                        local box_lv, box_stats = 0, nil
                        if M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0 then
                            local foe_base = M.BATTLE_MONS_ADDR + 1 * M.BATTLE_MON_SIZE
                            local ok_lv, elv = pcall(memory.read_u8,     foe_base + 0x2A)
                            local ok_mh, emh = pcall(memory.read_u16_le, foe_base + 0x2C)
                            local ok_at, eat = pcall(memory.read_u16_le, foe_base + 0x02)
                            local ok_de, ede = pcall(memory.read_u16_le, foe_base + 0x04)
                            local ok_sp, esp = pcall(memory.read_u16_le, foe_base + 0x06)
                            local ok_sa, esa = pcall(memory.read_u16_le, foe_base + 0x08)
                            local ok_sd, esd = pcall(memory.read_u16_le, foe_base + 0x0A)
                            box_lv = (ok_lv and elv and elv > 0) and elv or 0
                            local mhp = (ok_mh and emh and emh > 0) and emh or 0
                            if box_lv > 0 and mhp > 0 then
                                box_stats = {
                                    level   = box_lv,
                                    maxHP   = mhp,
                                    attack  = ok_at and eat or 0,
                                    defense = ok_de and ede or 0,
                                    speed   = ok_sp and esp or 0,
                                    spAtk   = ok_sa and esa or 0,
                                    spDef   = ok_sd and esd or 0,
                                }
                            end
                            if bsid == 0 then
                                local ok_es, esid = pcall(memory.read_u16_le, foe_base + 0x00)
                                bsid = (ok_es and esid and esid > 0) and esid or 0
                            end
                        end
                        send({event="capture", key=new_key, area_id=evt_area, in_box=true,
                              level=box_lv, nickname=bnick, species_id=bsid, held_item_id=biid,
                              stats=box_stats},
                             "capture(box/switched):"..new_key:sub(1,8), true)
                    else
                        captured_this_battle = true
                        console.log(string.format("[SLink-FRLGE] box: switched+CAUGHT; %d new keys — no_catch suppressed", found_count))
                    end
                end
            end
        end

        if post_battle_frames == 0 then
            local outcome_caught = (M.getBattleOutcome() == M.OUTCOME_CAUGHT)
            if nuzlocke_active and battle_is_wild and not captured_this_battle and not outcome_caught
                    and battle_area_id and battle_area_id ~= ""
                    and not resolved_areas[battle_area_id]
                    and not game_module.is_gift_area(battle_area_id) then
                resolved_areas[battle_area_id] = true
                -- Read the wild Pokémon's species and level from gBattleMons[1].
                -- gBattleMons data persists in EWRAM after battle ends.
                local enc_sid   = 0
                local enc_level = 0
                if M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0 then
                    local foe_base = M.BATTLE_MONS_ADDR + 1 * M.BATTLE_MON_SIZE
                    local ok_s, sid = pcall(memory.read_u16_le, foe_base + 0x00)
                    if ok_s and sid and sid > 0 then enc_sid = sid end
                    local ok_l, lv = pcall(memory.read_u8, foe_base + 0x2A)
                    if ok_l and lv then enc_level = lv end
                end
                send({event="no_catch", area_id=battle_area_id,
                      species_id=enc_sid, level=enc_level},
                     "no_catch:"..battle_area_id, true)
            end
            captured_this_battle = false
        end
    end

    -- ── activate nuzlocke once the player has Pokéballs in their bag ─────────────
    -- Throttled to every 15 frames (~0.25s) to avoid 14 bag reads per frame.
    if not nuzlocke_active and frame_count % 15 == 0 and M.hasPokeballs() then
        nuzlocke_active = true
        console.log("[SLink-FRLGE] nuzlocke ACTIVE (pokeballs in bag)")
        HUD.nuzlocke_start("Nuzlocke Start!")
        if M.playSE then M.playSE(M.SE_NUZLOCKE_START) end
    end

    -- ── safe ─────────────────────────────────────────────────────────────────
    if pending_safe and is_overworld then
        pending_safe = false
        send({event="safe"}, "safe", true)
    end

    -- ── auto tick ────────────────────────────────────────────────────────────
    if frame_count % TICK_INTERVAL == 0 then
        local ok_t, tname = pcall(M.readTrainerName)
        local ok_b2, badge_n, badge_bm = pcall(M.readBadges)
        local evt = {event="tick", ball_count=M.countPokeballs(), has_pokeballs=nuzlocke_active,
                     area_id=area, loc_name=loc,
                     in_battle=in_battle, is_doubles=false,
                     badges=ok_b2 and badge_bm or 0,
                     trainer_name=ok_t and tname or ""}
        -- Only include party/box/enemy data once save data looks valid.
        -- During title screen / intro cutscenes, RAM may contain uninitialized garbage.
        -- gPlayerPartyCount in 0–6 is the sanity check for "save is loaded".
        local raw_count = memory.read_u8(M.PARTY_COUNT_ADDR)
        if raw_count >= 0 and raw_count <= 6 then
            -- During borrowed-party battles or party freeze (pre-battle swap),
            -- don't send the borrowed mons as our party — omit party data
            -- so the server keeps the real snapshot.
            if not borrowed_battle and not party_frozen then
                evt.party = build_party_snapshot(in_battle)
            end
            -- Include enemy party when in battle; send empty table when not (clears stale data).
            if in_battle then
                if M.BATTLE_TYPE_ADDR and M.BATTLE_TYPE_ADDR ~= 0 then
                    local flags = memory.read_u32_le(M.BATTLE_TYPE_ADDR)
                    evt.is_trainer_battle = (flags & M.BATTLE_TYPE_TRAINER_MASK) ~= 0
                                         or (flags & M.BATTLE_TYPE_FIRST_MASK)   ~= 0
                end
                -- Send trainer index for name resolution on the server
                if evt.is_trainer_battle then
                    local tid = M.readTrainerOpponentId()
                    if tid > 0 then evt.trainer_id = tid end
                end
                local enemy_party = {}
                -- Detect doubles: gBattlersCount=4 in 2v2, 2 in singles.
                local is_doubles_battle = M.isDoubleBattle()
                evt.is_doubles = is_doubles_battle
                -- Read active foe from gBattleMons[1] (battler 1 = enemy left, always valid during battle).
                -- BattlePokemon: species +0x00, moves +0x0C, ability +0x20, pp +0x24,
                -- hp +0x28, level +0x2A, maxHP +0x2C, item +0x2E, status1 +0x4C
                local foe_species, foe_level, foe_hp, foe_maxHP, foe_ability, foe_item, foe_status = 0, 0, 0, 0, 0, 0, 0
                local foe_stat_stages = nil
                local foe_moves, foe_pp, foe_pp_bonuses = nil, nil, 0
                if M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0 then
                    local foe_base = M.BATTLE_MONS_ADDR + 1 * M.BATTLE_MON_SIZE
                    foe_species = memory.read_u16_le(foe_base + 0x00)
                    foe_level   = memory.read_u8(foe_base + 0x2A)
                    foe_hp      = memory.read_u16_le(foe_base + M.BATTLE_MON_HP_OFF)
                    foe_maxHP   = memory.read_u16_le(foe_base + 0x2C)
                    foe_ability = memory.read_u8(foe_base + 0x20)
                    foe_status  = memory.read_u32_le(foe_base + M.BATTLE_MON_STATUS_OFF)
                    foe_stat_stages = M.readStatStages(1)
                    -- Live moves/PP from gBattleMons (unencrypted, reflects post-use PP immediately).
                    foe_moves = {
                        memory.read_u16_le(foe_base + 0x0C),
                        memory.read_u16_le(foe_base + 0x0E),
                        memory.read_u16_le(foe_base + 0x10),
                        memory.read_u16_le(foe_base + 0x12),
                    }
                    foe_pp = {
                        memory.read_u8(foe_base + 0x24),
                        memory.read_u8(foe_base + 0x25),
                        memory.read_u8(foe_base + 0x26),
                        memory.read_u8(foe_base + 0x27),
                    }
                    -- ppBonuses byte at +0x3A: 2 bits per move slot (0–3 PP-Ups).
                    foe_pp_bonuses = memory.read_u8(foe_base + 0x3A)
                    -- BattlePokemon.item is at +0x2E (confirmed from pret/pokefirered and CFRU
                    -- pokemon.h: struct BattlePokemon { ... /*0x2E*/ u16 item; ... }).
                    -- Skip for wild battles: wild mons in CFRU/RR have item=0 in gBattleMons.
                    if evt.is_trainer_battle then
                        foe_item = memory.read_u16_le(foe_base + 0x2E)
                    end
                end
                -- Doubles: read gBattleMons[3] (battler 3 = enemy right). Same field layout.
                local foe2_species, foe2_level, foe2_hp, foe2_maxHP = 0, 0, 0, 0
                local foe2_ability, foe2_item, foe2_status = 0, 0, 0
                local foe2_stat_stages = nil
                local foe2_moves, foe2_pp, foe2_pp_bonuses = nil, nil, 0
                if is_doubles_battle and M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0 then
                    local b3 = M.BATTLE_MONS_ADDR + 3 * M.BATTLE_MON_SIZE
                    foe2_species     = memory.read_u16_le(b3 + 0x00)
                    foe2_level       = memory.read_u8(b3 + 0x2A)
                    foe2_hp          = memory.read_u16_le(b3 + M.BATTLE_MON_HP_OFF)
                    foe2_maxHP       = memory.read_u16_le(b3 + 0x2C)
                    foe2_ability     = memory.read_u8(b3 + 0x20)
                    foe2_status      = memory.read_u32_le(b3 + M.BATTLE_MON_STATUS_OFF)
                    foe2_stat_stages = M.readStatStages(3)
                    foe2_moves = {
                        memory.read_u16_le(b3 + 0x0C),
                        memory.read_u16_le(b3 + 0x0E),
                        memory.read_u16_le(b3 + 0x10),
                        memory.read_u16_le(b3 + 0x12),
                    }
                    foe2_pp = {
                        memory.read_u8(b3 + 0x24),
                        memory.read_u8(b3 + 0x25),
                        memory.read_u8(b3 + 0x26),
                        memory.read_u8(b3 + 0x27),
                    }
                    foe2_pp_bonuses = memory.read_u8(b3 + 0x3A)
                    if evt.is_trainer_battle then
                        foe2_item = memory.read_u16_le(b3 + 0x2E)
                    end
                end
                -- Primary: read full team from gEnemyParty if count is valid (vanilla/AP).
                local ok_ep, full_team = pcall(M.readEnemyParty)
                if ok_ep and full_team and #full_team > 1 then
                    -- Active detection (unified singles & doubles): gBattlerPartyIndexes[1/3]
                    -- is primary; species+level matching against gBattleMons[1] is the
                    -- fallback when the index read is stale (≥ 6 → CFRU address drift).
                    -- gBattlerPartyIndexes is u16[4]; battler N → BATTLER_PARTY_INDEXES_ADDR + N*2.
                    -- battler 3 (foe2) is only read in doubles.
                    local ep_idx1 = M.BATTLER_PARTY_INDEXES_ADDR
                        and memory.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR + 2)   -- battler 1 party slot
                    local ep_idx3 = (is_doubles_battle and M.BATTLER_PARTY_INDEXES_ADDR)
                        and memory.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR + 6)   -- battler 3 party slot
                    -- Bounds guard: valid party slot is 0-5. Values ≥ 6 mean the
                    -- address is stale or wrong (e.g. CFRU address drift), so nil
                    -- out and fall through to the species+level fallback below.
                    if ep_idx1 and ep_idx1 >= 6 then ep_idx1 = nil end
                    if ep_idx3 and ep_idx3 >= 6 then ep_idx3 = nil end
                    for idx, mon in ipairs(full_team) do
                        local slot = idx - 1   -- 0-indexed party slot
                        local is_foe1, is_foe2 = false, false
                        if ep_idx1 ~= nil then
                            is_foe1 = (slot == ep_idx1)
                        else
                            -- Fallback when gBattlerPartyIndexes unavailable/stale
                            is_foe1 = (mon.species_id == foe_species and mon.level == foe_level)
                        end
                        if is_doubles_battle and ep_idx3 ~= nil then
                            is_foe2 = (slot == ep_idx3)
                        end
                        mon.active = is_foe1 or is_foe2
                        if is_foe1 then
                            if foe_ability > 0  then mon.ability_id = foe_ability  end
                            mon.status_cond = foe_status
                            mon.stat_stages = foe_stat_stages
                            -- Overlay live moves/PP from gBattleMons over the gEnemyParty decrypt.
                            if foe_moves then mon.moves = foe_moves end
                            if foe_pp    then mon.pp    = foe_pp    end
                            mon.pp_bonuses = foe_pp_bonuses
                            if evt.is_trainer_battle and foe_item  > 0 then
                                mon.held_item_id = foe_item
                            end
                        elseif is_foe2 then
                            if foe2_ability > 0 then mon.ability_id = foe2_ability end
                            mon.status_cond = foe2_status
                            mon.stat_stages = foe2_stat_stages
                            if foe2_moves then mon.moves = foe2_moves end
                            if foe2_pp    then mon.pp    = foe2_pp    end
                            mon.pp_bonuses = foe2_pp_bonuses
                            if evt.is_trainer_battle and foe2_item > 0 then
                                mon.held_item_id = foe2_item
                            end
                        end
                        -- Item field unreliable for wild mons in CFRU/RR
                        if not evt.is_trainer_battle then mon.held_item_id = 0 end
                        enemy_party[idx] = mon
                    end
                elseif foe_species > 0 and foe_maxHP > 0 then
                    -- Fallback: accumulate foes seen via gBattleMons[1] (CFRU/RR).
                    local foe_key = foe_species .. ":" .. foe_level
                    battle_seen_enemies[foe_key] = {
                        species_id   = foe_species,
                        level        = foe_level,
                        hp           = foe_hp,
                        maxHP        = foe_maxHP,
                        ability_id   = foe_ability,
                        held_item_id = foe_item,
                        status_cond  = foe_status,
                        stat_stages  = foe_stat_stages,
                        moves        = foe_moves,
                        pp           = foe_pp,
                        pp_bonuses   = foe_pp_bonuses,
                    }
                    -- Doubles: also seed foe2 into the accumulator.
                    local foe2_key = (is_doubles_battle and foe2_species > 0 and foe2_maxHP > 0)
                                     and (foe2_species .. ":" .. foe2_level) or nil
                    if foe2_key then
                        battle_seen_enemies[foe2_key] = {
                            species_id   = foe2_species,
                            level        = foe2_level,
                            hp           = foe2_hp,
                            maxHP        = foe2_maxHP,
                            ability_id   = foe2_ability,
                            held_item_id = foe2_item,
                            status_cond  = foe2_status,
                            stat_stages  = foe2_stat_stages,
                            moves        = foe2_moves,
                            pp           = foe2_pp,
                            pp_bonuses   = foe2_pp_bonuses,
                        }
                    end
                    for k, mon in pairs(battle_seen_enemies) do
                        local is_f1 = (k == foe_key)
                        local is_f2 = (is_doubles_battle and k == foe2_key)
                        enemy_party[#enemy_party + 1] = {
                            species_id   = mon.species_id,
                            level        = mon.level,
                            hp           = is_f1 and foe_hp  or (is_f2 and foe2_hp  or mon.hp),
                            maxHP        = mon.maxHP,
                            ability_id   = is_f1 and foe_ability  or (is_f2 and foe2_ability  or mon.ability_id),
                            held_item_id = (not evt.is_trainer_battle) and 0 or
                                           (is_f1 and foe_item or (is_f2 and foe2_item or mon.held_item_id)),
                            status_cond  = is_f1 and foe_status  or (is_f2 and foe2_status  or (mon.status_cond or 0)),
                            stat_stages  = is_f1 and foe_stat_stages or (is_f2 and foe2_stat_stages or nil),
                            moves        = is_f1 and foe_moves or (is_f2 and foe2_moves or mon.moves),
                            pp           = is_f1 and foe_pp    or (is_f2 and foe2_pp    or mon.pp),
                            pp_bonuses   = is_f1 and foe_pp_bonuses or (is_f2 and foe2_pp_bonuses or (mon.pp_bonuses or 0)),
                            active       = is_f1 or is_f2,
                        }
                    end
                end
                evt.enemy_party = enemy_party
            else
                evt.enemy_party = {}
            end
            -- Incremental box scan: 2 boxes per tick instead of all 13 at once.
            -- Only scan when in a trustworthy state (mirrors party_diff_ok gate).
            if party_diff_ok then
                local ok_b, boxes = pcall(scan_next_boxes)
                if ok_b then
                    evt.pc_boxes = boxes
                    -- Seed all_known_keys from the scanned results when in overworld
                    -- and outside any post-battle grace window.  This heals the case
                    -- where the startup/connect box scans ran before the save file was
                    -- loaded (empty EWRAM → no keys found), leaving pre-existing box
                    -- mons unknown and causing them to fire as capture(gift) on withdraw.
                    -- Guard: skip during/after battles so the post-battle box-capture
                    -- fallback scan (which checks `not all_known_keys[k]`) still works.
                    if is_overworld and post_battle_frames == 0 then
                        for _, entry in ipairs(boxes) do
                            -- Skip memorial/overflow boxes: dead mons must not block
                            -- future same-PID captures (CFRU reuses personalities).
                            if entry.key and not all_known_keys[entry.key]
                               and entry.box ~= M.MEMORIAL_BOX
                               and not memorial_overflow_renamed[entry.box] then
                                all_known_keys[entry.key] = true
                            end
                        end
                    end
                end
            end
        end
        send(evt, "tick(auto)", true, true)
    end

    -- ── manual F keys ────────────────────────────────────────────────────────
    local keys = input.get()
    local function pressed(k) return keys[k] and not prev_keys[k] end

    if pressed("F1") then
        send({event="area_enter", area_id=area},
             "area_enter:"..(area~="" and area or "(none)"), false)
    end
    if pressed("F2") then
        if M.slotOccupied(M.PARTY_BASE) then
            local k  = M.monKey(M.PARTY_BASE)
            local lv = memory.read_u8(M.PARTY_BASE + M.OFF_LEVEL)
            local hp = memory.read_u16_le(M.PARTY_BASE + M.OFF_HP)
            local mx = memory.read_u16_le(M.PARTY_BASE + M.OFF_MAX_HP)
            local nick, sid, iid = M.readBoxSlotDisplay(M.PARTY_BASE, false)
            send({event="capture", key=k, level=lv, hp=hp, maxHP=mx, area_id=area,
                  nickname=nick, species_id=sid, held_item_id=iid},
                 "capture(manual):"..k:sub(1,8), false)
        else console.log("[SLink-FRLGE] F2: slot 0 empty") end
    end
    if pressed("F3") then
        if M.slotOccupied(M.PARTY_BASE) then
            local k = M.monKey(M.PARTY_BASE)
            send({event="faint", key=k, area_id=area}, "faint:"..k:sub(1,8), false)
        else console.log("[SLink-FRLGE] F3: slot 0 empty") end
    end
    if pressed("F4") then
        local f4_sid, f4_lv = 0, 0
        if M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0 then
            local foe_base = M.BATTLE_MONS_ADDR + 1 * M.BATTLE_MON_SIZE
            local ok_s4, sid4 = pcall(memory.read_u16_le, foe_base + 0x00)
            if ok_s4 and sid4 and sid4 > 0 then f4_sid = sid4 end
            local ok_l4, lv4 = pcall(memory.read_u8, foe_base + 0x2A)
            if ok_l4 and lv4 then f4_lv = lv4 end
        end
        send({event="no_catch", area_id=area, species_id=f4_sid, level=f4_lv},
             "no_catch:"..(area~="" and area or "(none)"), false)
    end
    if pressed("F5") then send({event="whiteout"},    "whiteout",    false) end
    if pressed("F6") then send({event="safe"},         "safe",        false) end
    if pressed("F7") then
        local ok_t, tname = pcall(M.readTrainerName)
        local ok_b, boxes = pcall(M.readBoxSummary)
        send({event="tick", ball_count=M.countPokeballs(), has_pokeballs=nuzlocke_active,
              area_id=area, loc_name=loc,
              trainer_name=ok_t and tname or "",
              pc_boxes=ok_b and boxes or {},
              party=build_party_snapshot(in_battle)}, "tick", false)
    end
    if pressed("F8") then
        if M.slotOccupied(M.PARTY_BASE) then
            local base = M.PARTY_BASE
            local k  = M.monKey(base)
            local hp = memory.read_u16_le(base + M.OFF_HP)
            if hp > 0 then
                local st = mon_stats_cache[k]
                local stats_tbl = st and {level=st.level, maxHP=st.maxHP,
                    attack=st.attack, defense=st.defense, speed=st.speed,
                    spAtk=st.spAtk, spDef=st.spDef,
                    pp1=st.pp1, pp2=st.pp2, pp3=st.pp3, pp4=st.pp4} or nil
                send({event="party_to_box", key=k, stats=stats_tbl},
                     "party_to_box:"..k:sub(1,8), false)
            else
                console.log("[SLink-FRLGE] F8: slot 0 HP=0, use only for living mons")
            end
        else console.log("[SLink-FRLGE] F8: slot 0 empty") end
    end
    if pressed("F9") then
        -- Manual: directly memorialize party slot 0 (skips server — tests Lua write)
        local f9_count = memory.read_u8(M.PARTY_COUNT_ADDR)
        if f9_count <= 1 then
            console.log("[SLink-FRLGE] F9: blocked — would empty party")
        elseif M.slotOccupied(M.PARTY_BASE) or M.monKey(M.PARTY_BASE) ~= "00000000:00000000" then
            local k = M.monKey(M.PARTY_BASE)
            console.log("[SLink-FRLGE] F9: manually memorializing "..k:sub(1,8))
            exec_memorialize(k)
        else
            console.log("[SLink-FRLGE] F9: slot 0 empty")
        end
    end
    prev_keys = keys

    -- (sync_cooldown is now updated at step 4a, before the sync flush)

    -- ── HUD overlay (draw last so it appears on top) ──────────────────────────
    hud_render()

    -- ── clear per-frame write guard ───────────────────────────────────────────
    sync_written_keys = {}

    -- ── advance prev state ────────────────────────────────────────────────────
    -- Freeze prev_party during menu/script states so garbage reads don't
    -- accumulate into the baseline used for diff detection.
    if party_diff_ok then
        prev_party     = curr_party
    elseif post_unfreeze_frames > 0 then
        -- During post-unfreeze settle, keep baseline synced so diffs are clean
        -- when the settle period ends (game may still be restoring real party).
        prev_party = curr_party
    end
    prev_area      = area
    prev_loc       = loc
    prev_in_battle = in_battle
end

local function on_frame_safe()
    local ok, err = pcall(on_frame)
    if not ok then console.log("[SLink-FRLGE] ERROR (handler kept alive): " .. tostring(err)) end
end

-- ── Startup ───────────────────────────────────────────────────────────────────
console.clear()
C.init(SERVER_HOST, SERVER_PORT)
console.log(string.format("[SLink-FRLGE] ROM: %s  Validation: %s  Writes: %s",
    rom_type, val_ok and "OK" or ("FAIL – "..tostring(val_err)),
    writes_enabled and "ON" or "OFF (will re-validate each frame)"))
if M.CFRU_NO_ENCRYPT then
    console.log("[SLink-FRLGE] ⚠ CFRU/RR: Load this script AFTER entering the game (not at title screen)")
end
console.log(string.format("[SLink-FRLGE] TCP: %s:%d  Player: %s", SERVER_HOST, SERVER_PORT, PLAYER_ID))
console.log("[SLink-FRLGE] Auto: hello area_enter capture(battle/box/gift) box_to_party party_to_box faint no_catch(wild) whiteout safe tick")
console.log("[SLink-FRLGE] F1=area_enter F2=capture(s0) F3=faint(s0) F4=no_catch F5=whiteout F6=safe F7=tick F8=party_to_box(s0)")
console.log("[SLink-FRLGE] F9=memorialize(s0)")
console.log("[SLink-FRLGE] --- monitoring started ---")
-- Seed all_known_keys from current party before monitoring begins
for k in pairs(prev_party) do all_known_keys[k] = true end
-- Detect memorial overflow boxes: walk down from memorial box;
-- if a box is full (30 mons), it's an overflow memorial box.
do
    local bi = M.MEMORIAL_BOX - 1
    while bi >= 0 do
        local occ = 0
        for si = 0, M.MONS_PER_BOX - 1 do
            local a = M.boxMonAddr(bi, si)
            if a and M.boxSlotOccupied(a) then occ = occ + 1 end
        end
        if occ >= M.MONS_PER_BOX then
            memorial_overflow_renamed[bi] = true
            bi = bi - 1
        else
            break
        end
    end
    if next(memorial_overflow_renamed) then
        console.log(string.format("[SLink-FRLGE] Detected %d memorial overflow box(es)",
            (function() local n=0; for _ in pairs(memorial_overflow_renamed) do n=n+1 end; return n end)()))
    end
end
-- Seed all_known_keys from PC boxes to prevent false gift captures when
-- withdrawing mons after a script reload (memorial/overflow boxes skipped).
seed_known_keys_from_boxes()

event.onframeend(on_frame_safe, "t4_events")
console.log("[SLink-FRLGE] Running — play normally to trigger events…")
