--[[
  lua/slink.lua — Universal SLink Entry Point
  ============================================
  Auto-detects the loaded ROM and starts the appropriate game client.
  The launcher sets SLINK_HOST, SLINK_PORT, SLINK_PLAYER as globals before
  running this file — those are consumed by whichever client gets loaded.
--]]

local _dir = debug.getinfo(1, "S").source:match([=[@(.+[/\])]=]) or ""
package.path = _dir .. "?.lua;" .. _dir .. "?/init.lua;" .. package.path

-- ── Console tee ──────────────────────────────────────────────────────────────
-- BizHawk's Lua console scrolls and drops old lines, so when something logs
-- a lot at startup (BizHawk's "Unable to find domain" warnings, our diagnostic
-- output, etc.) the user can't scroll back far enough to copy it. Mirror every
-- console.log() call to slink_lua.log in the project root for post-mortem.
-- The log is truncated on each run so old content doesn't accumulate.
do
    local log_path = _dir .. "../slink_lua.log"
    -- Close any handle left open by a previous script-load so reloads don't leak.
    if _G.__slink_log_fh then
        pcall(function() _G.__slink_log_fh:close() end)
        _G.__slink_log_fh = nil
    end
    -- Open once for the lifetime of this run (truncate-at-boot via "w").
    -- Keeping the handle open avoids per-call open/close, which is several ms
    -- per log line on Drive-synced paths and a primary source of event-frame stutter.
    local fh = io.open(log_path, "w")
    if fh then
        fh:write(string.format("=== SLink Lua boot %s ===\n", os.date()))
        fh:flush()
        _G.__slink_log_fh = fh
        local orig_log = console.log
        console.log = function(...)
            local h = _G.__slink_log_fh
            if h then
                local parts = {...}
                for i = 1, select("#", ...) do
                    parts[i] = tostring(parts[i])
                end
                local ok = pcall(function()
                    h:write(table.concat(parts, "\t") .. "\n")
                    h:flush()
                end)
                if not ok then
                    -- Drop the handle on first write failure so we don't
                    -- hot-loop reopening; reload the script to recover.
                    pcall(function() h:close() end)
                    _G.__slink_log_fh = nil
                end
            end
            orig_log(...)
        end
        console.log("[SLink] Console tee -> " .. log_path)
    end
end

-- ── Gen 1 route ──────────────────────────────────────────────────────────────
-- Red/Blue/Yellow run the rewritten client under lua/gen1/, which owns its own
-- cartridge detection (entry.lua Entry.detect_title). It is checked before the
-- game_detect registry so the Gen 1 entry is never decided in two places; Gen 2-5
-- fall through unchanged. emu is indexed inside the pcall because a broken/absent
-- core would otherwise error before the guard could refuse.
do
    local sys_ok, sys = pcall(function() return emu.getsystemid() end)
    -- "SGB" is what EmuHawk reports when GbAsSgb is on (Gambatte in Super Game Boy mode,
    -- opt-in, off in the stock config); the cartridge is the same Gen 1 ROM.
    if sys_ok and (sys == "GB" or sys == "GBC" or sys == "SGB") then
        local Entry = dofile(_dir .. "gen1/entry.lua")
        if Entry.detect_title(function(addr) return memory.read_u8(addr, "ROM") end) then
            -- The engine hooks (gen1/signals.lua) are only proven on 2.11.x; on 2.9.1 they
            -- latched a failure and every capture/battle went unreported (live run 2026-09-22).
            local ver = tostring(client.getversion and client.getversion() or "?")
            local maj, min = ver:match("^(%d+)%.(%d+)")
            if not maj or tonumber(maj) * 100 + tonumber(min) < 211 then
                error("[SLink] BizHawk " .. ver .. " is too old for Gen 1 -- install BizHawk 2.11 or newer", 0)
            end
            dofile(_dir .. "gen1/run.lua")
            return
        end
    end
end

-- ── Gen 2 route ──────────────────────────────────────────────────────────────
-- Crystal, Gold and Silver all run the rewritten client under lua/gen2/, which owns its
-- own cartridge detection (entry.lua Entry.detect_title) -- routed by TITLE, not by
-- per-title admission: run.lua itself admits or refuses through Entry.build (Entry.admit
-- is sha1-first, never by header), so a recognised title always reaches it and an
-- unadmitted build (a PENDING revision, or any unknown hash) is refused there with no
-- fallback (O-22/O-23, docs/gen2/reviews/OMP_U5_CUTOVER_FACTS_2026-09-23.md).
--
-- Every other Game Boy cartridge is REFUSED here, by name, before game_detect: the legacy
-- Gen 2 client that used to catch them is gone (P3b.8), and game_detect holds no Game Boy
-- module any more. The Archipelago fork's header ("AP_CRYSTAL") gets its own message:
-- owner ruling O-25 refuses Archipelago Crystal (docs/gen2/REVIEW_RECORD.md).
do
    local sys_ok, sys = pcall(function() return emu.getsystemid() end)
    if sys_ok and (sys == "GB" or sys == "GBC" or sys == "SGB") then
        local Entry = dofile(_dir .. "gen2/entry.lua")
        local title, header = Entry.detect_title(function(addr) return memory.read_u8(addr, "ROM") end)
        if title then
            dofile(_dir .. "gen2/run.lua")
            return
        end
        header = header or ""
        if header:sub(1, 10) == "AP_CRYSTAL" then
            error("[SLink] Archipelago Crystal is not supported (O-25) -- load a vanilla "
                  .. "Gold, Silver or Crystal cartridge", 0)
        end
        error("[SLink] Unsupported Game Boy cartridge " .. string.format("%q", header)
              .. " -- SLink runs Red, Blue, Yellow, Gold, Silver and Crystal", 0)
    end
end

-- ── Gen 3 route ──────────────────────────────────────────────────────────────
-- FireRed/LeafGreen (pack gen3_frlg) and Radical Red (pack gen3_rr) admitted by HASH or
-- ANCHORS run under lua/gen3/, the rewritten client. The old Gen 3 client was archived at
-- C5-6 (tag archive/gen3-old-client, owner ruling 24): every other GBA cartridge -- Emerald,
-- the Archipelago FireRed/LeafGreen builds, a header-only admission (an unpinned hack or a
-- bad dump that merely says BPRE/BPGE) -- is refused here by name, never handed to
-- game_detect. RR carries FireRed's header code, so a header-only admission is refused rather
-- than routed: the new client's site check would refuse it anyway, less legibly.
--
-- The routed set lives in entry.lua (Entry.ROUTED); the launcher keeps no copy of it.
do
    local sys_ok, sys = pcall(function() return emu.getsystemid() end)
    -- Fail closed: an unidentifiable system must never fall through to game_detect (the
    -- Gen 2/4/5 registry), which could silently misroute a GBA cartridge that briefly failed
    -- to identify itself. GB/GBC/SGB (Gen 1 and Gen 2, handled above) and NDS (Gen 4/5) are the only
    -- known non-GBA systems game_detect is ever asked to route.
    if not sys_ok then
        error("[SLink] could not determine the loaded system (emu.getsystemid failed): "
              .. tostring(sys), 0)
    elseif sys ~= "GBA" and sys ~= "GB" and sys ~= "GBC" and sys ~= "SGB" and sys ~= "NDS" then
        error("[SLink] could not determine the loaded system: emu.getsystemid() returned "
              .. tostring(sys) .. " (expected GB, GBC, SGB, GBA or NDS)", 0)
    end
    if sys == "GBA" then
        -- Admission itself is isolated in a pcall so an admission error becomes a named
        -- refusal. The BizHawk-version guard below is deliberately OUTSIDE this pcall so it
        -- propagates like the Gen 1 route's does.
        local header_code = "?"
        local admit_ok, Entry, admitted, why = pcall(function()
            local E = dofile(_dir .. "gen3/entry.lua")
            assert(E, "lua/gen3/entry.lua did not load")
            local function rom_read(off, n)
                local t = {}
                for i = 1, n do t[i] = memory.read_u8(off + i - 1, "ROM") end
                return t
            end
            local hash = gameinfo and gameinfo.getromhash and gameinfo.getromhash() or ""
            local ok_hc, hc = pcall(E.header_code, rom_read)
            header_code = ok_hc and hc or ""
            local a, reason = E.admit({ root = _dir .. "..", json = dofile(_dir .. "json_codec.lua"),
                                        rom_hash = hash, rom_read = rom_read,
                                        header_code = header_code })
            return E, a, reason
        end)
        if admit_ok and Entry and admitted and Entry.ROUTED[admitted.pack]
           and admitted.admitted_by ~= "header" then
            -- The engine hooks are only proven on 2.11.x (same guard as the Gen 1 route,
            -- slink.lua Gen 1 block above).
            local ver = tostring(client.getversion and client.getversion() or "?")
            local maj, min = ver:match("^(%d+)%.(%d+)")
            if not maj or tonumber(maj) * 100 + tonumber(min) < 211 then
                error("[SLink] BizHawk " .. ver .. " is too old for Gen 3 -- install BizHawk 2.11 or newer", 0)
            end
            dofile(_dir .. "gen3/run.lua")
            return
        end
        local what
        if header_code == "BPEE" then
            what = "Pokemon Emerald is not supported yet"
        elseif admit_ok and admitted and admitted.admitted_by == "header" then
            what = "this " .. tostring(admitted.title) .. " build (header " .. header_code
                   .. ") is not a pinned cartridge -- Archipelago builds and unknown hacks are not supported yet"
        elseif not admit_ok then
            what = "admission failed (" .. tostring(Entry) .. ")"
        else
            what = "this cartridge (header " .. tostring(header_code) .. ") is not supported ("
                   .. tostring(why) .. ")"
        end
        error("[SLink] Unsupported Gen 3 cartridge: " .. what
              .. ". Supported: FireRed, LeafGreen and Radical Red.", 0)
    end
end

-- Detect which game is loaded
package.loaded["game_detect"]       = nil
local game_detect = require("game_detect")
local detected    = game_detect.detect()

-- Map game_id to client script path
-- No Game Boy or GBA rows: the Gen 1, Gen 2 and Gen 3 routes above return or refuse for every
-- GB/GBC/SGB/GBA core before this table is reached (the legacy gen2_crystal row went with P3b.8,
-- the old gen3_frlge row with C5-6).
local _CLIENT_MAP = {
    gen4_hgsspt   = "clients/gen4_hgsspt_client.lua",
    gen5_bw       = "clients/gen5_bw_client.lua",
}

local client_path = _CLIENT_MAP[detected.game_id]
if not client_path then
    error("[SLink] No client available for detected game: " .. detected.game_id
          .. " (" .. detected.module.display_name .. ")")
end

dofile(_dir .. client_path)
