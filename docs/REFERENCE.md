# SLink — Soul Link Nuzlocke Automation

SLink automates a **Soul Link Nuzlocke** across two simultaneous Pokémon runs in [BizHawk](https://github.com/TASEmulators/BizHawk). Each emulator runs a Lua client that reads game RAM every frame and sends JSON events (area entered, capture, faint, etc.) to a central Python server over TCP. The server enforces Soul Link rules — linking encounters by area, propagating faints, syncing party/box state, moving dead pairs to a memorial box — and returns commands back to the Lua clients in the same response.

**Supported Games:**
- **Gen 3** — FireRed, LeafGreen, Emerald (vanilla, randomized, Archipelago, Radical Red/CFRU) — **✅ stable**
- **Gen 1** — Red, Blue, Yellow (US English) — ⚠️ experimental
- **Gen 2** — Crystal (GBC) — ⚠️ experimental
- **Gen 4** — HeartGold, SoulSilver, Platinum — ⚠️ experimental
- **Gen 5** — Black, White, Black 2, White 2 — ⚠️ experimental

> **Note:** Only Gen 3 has been extensively tested in live gameplay. Gen 1, 2, 4, and 5 have unit tests and Lua clients but limited real-world testing.

---

## Prerequisites

| Requirement | Detail |
|---|---|
| BizHawk 2.9+ | **Gen 1:** Two instances with US Red/Blue/Yellow ROMs (Gambatte core). **Gen 3:** Two instances with US 1.0 FRLG/Emerald ROMs. **Gen 4:** Two instances with US HGSS ROMs |
| ROMs | **Gen 1:** Red/Blue/Yellow (US). **Gen 3:** Vanilla, randomized (UPR), Archipelago, or Radical Red 4.1. **Gen 4:** HeartGold/SoulSilver US |
| Python 3.10+ | `pip install -r requirements.txt` |
| Scripts in `lua/` | `slink.lua` (universal entry point), `memory_gba.lua`, `connector.lua`, `socket.lua` |
| LuaSocket DLL | Copy `socket-windows-5-4.dll` from an Archipelago install into `lua/x64/` (see `lua/x64/README.md`) |
| Network | Both BizHawk instances must reach the Python server (localhost or LAN) |

---

## Quick Start

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the server

```bash
python -m server.server --host 127.0.0.1 --port 54321
```

The server writes state to `data/links.json` and `data/memorial.json`. Pass `--reset` to wipe state and start a fresh run.

### 3. Open the status page

Navigate to `http://localhost:8080/` in a browser. The page title dynamically shows "Pokémon Soul Link Tracker — \<Game Variant\> — \<Run Name\>" (e.g., "Pokémon Soul Link Tracker — Radical Red — MyRun") with a Pokéball favicon. Updates are pushed in near-real-time via **Server-Sent Events (SSE)** — no manual refresh needed. The page shows:
- Both players' trainer name, connection status, gym badges (8 badge icons per player), current area, Pokéball count, TCP port, and live party (with nicknames, species, levels, **ability names** with description tooltips, **held items**)
- Battle display panel ("⚔ IN BATTLE" with enemy party table including abilities) rendered **above** each player's party table for immediate visibility
- Consolidated Encounters table with progress icons: ✅ (linked/alive), 💀 (dead/memorial), ⏳ (pending), ☠️ (dead zone) — each row shows area, Player A's mon (sprite/nickname/species/level), status icon, Player B's mon
- Per-player PC box summary (occupied slots with nicknames/species/abilities)
- Per-area encounter state (waiting for &lt;trainer name&gt; / linked / dead zone)
- Identity error banner (red) when a player connects with the wrong save file
- Flicker-free auto-refresh via DOM morphing — sprites, HP bars, and table structure are preserved across updates; only changed text/values are patched in-place

Additional pages:
- **Memorial wall** at `/memorial` — tombstone cards for each dead linked pair with species-accurate sprites (CFRU→NatDex conversion), RR sprite background removal, nicknames, species, cause of death. Live updates via SSE.
- **Debug console** at `/debug` — live SSE updates, status banner (connections/areas/link counts/queued commands), link management (create/unlink/override/revive with live table), mon key autofill (datalist from party/link/pending data), area ID autofill (183+ areas annotated with state), event injection, command queuing, state toggles, live state panel (lock rules, player identity, party keys, bonus keys, pending bonus queue), backup rollback (clickable slot rows, restores both `links.json` and `events.json`).
- **Stream overlays** at `/stream` — individual overlay pages for OBS (party, links, deaths, areas, events, focus cards, encounter table, and more).

### 4. Load the Lua client in each BizHawk instance

**Option A — Universal entry point (recommended):**
1. Open the BizHawk Lua Console (**Tools → Lua Console**).
2. Load `lua/slink_gen1.lua` (Gen 1), `lua/slink_gen3.lua` (Gen 3) or `lua/slink_gen4.lua` (Gen 4).
3. Edit the top of the launcher to set `SLINK_HOST`, `SLINK_PORT`, and `SLINK_PLAYER` before loading.

Alternatively, load `lua/slink.lua` directly — it auto-detects the game but uses default connection settings (`127.0.0.1:54321`, player `"a"`).

**Option B — Direct client load:**
1. Open the BizHawk Lua Console.
2. Load `lua/clients/gen3_frlge_client.lua` (Gen 3) or `lua/clients/gen4_hgsspt_client.lua` (Gen 4).
3. At the top of the script, set:
   ```lua
   local SERVER_HOST = "127.0.0.1"   -- IP of the machine running server.py
   local SERVER_PORT = 54321          -- Gen 3 default; Gen 4 uses 54322
   local PLAYER_ID   = "a"           -- "a" for one game, "b" for the other
   ```
4. The console shows `TCP: connected to 127.0.0.1:54321` and `hello sent` within a second or two.

**Option C — Web download:** Open the Run Manager (port 8090) or status page and click the download button for Player A or B. The downloaded `.lua` file prompts for the SLink project root folder (the folder containing `lua/` and `server/`), validates by checking for `lua/slink.lua`, caches the path in `slink_path.cfg` next to the script, and auto-detects the game. Host, port, and player ID are pre-configured.

> **Important:** Load the Lua script **after** loading your save file in BizHawk.The script validates SaveBlock pointers at startup; if the save isn't loaded yet, writes will be disabled until the validation passes (it re-checks automatically each frame and enables writes as soon as the game is ready).

---

## Architecture

```
[BizHawk – Gen 1 (GB)]             [BizHawk – Gen 1 (GB)]
  lua/clients/gen1_rby_client.lua    lua/clients/gen1_rby_client.lua
  lua/memory_gb.lua                  lua/memory_gb.lua
  lua/games/gen1_rby.lua             lua/games/gen1_rby.lua

[BizHawk – Gen 3 (GBA)]            [BizHawk – Gen 3 (GBA)]
  lua/clients/gen3_frlge_client.lua    lua/clients/gen3_frlge_client.lua
  lua/memory_gba.lua                   lua/memory_gba.lua
  data/games/gen3_frlge/gen3_frlge_areas.lua

[BizHawk – Gen 4 (NDS)]            [BizHawk – Gen 4 (NDS)]
  lua/clients/gen4_hgsspt_client.lua
  lua/memory_nds.lua
  data/games/gen4_hgsspt/gen4_hgsspt_areas.lua

[BizHawk – Gen 5 (NDS)]            [BizHawk – Gen 5 (NDS)]
  lua/clients/gen5_bw_client.lua     lua/clients/gen5_bw_client.lua
  lua/memory_nds.lua                 lua/memory_nds.lua
  data/games/gen5_bw/gen5_bw_areas.lua
         |  TCP JSON event                  |
         +-────────────────────────────────-+
                       ↓
              [server/server.py]   aiohttp HTTP + TCP listener :54321
              [server/state.py]    SoulLinkState FSM
              [server/adapters/]   Game-specific adapters (gen1_rby, gen3_frlge, gen4_hgsspt, gen5_bw)
              [data/links.json]    persisted link table
              [data/memorial.json] persisted memorial log
              [data/games/]        game-specific data (area maps, RR data)
                       ↓
              :8080/              status page
              :8080/memorial      memorial wall
              :8080/debug         debug console
              :8080/stream/*      OBS overlays

       [server/manager.py]        Run Manager :8090
         creates/starts/stops server.py subprocesses
```

**Communication model:**
- Lua clients read RAM every frame but only send a JSON event when state changes (area, capture, faint, party move, etc.)
- The server returns commands in the TCP response: `{"commands": [{"cmd": "force_faint", "key": "..."}]}`
- Lua dispatches commands immediately (for `force_faint`, `play_sound`) or defers to the next overworld safe state (for `box_mon`, `party_mon`, `memorialize`). Safe-state checks use a fresh `isInOverworld()` call at execution time to avoid stale cached values.
- A `tick` event is sent every ~60 frames as a heartbeat to flush queued cross-player commands and update the status page with current party data. During the intro (before save data is valid), ticks omit party/box/enemy data to prevent garbage on the status page.
- **TCP connector** uses fully non-blocking connect (`settimeout(0)`) — zero emulator stutter when the server is down. Pending connects are probed via zero-byte send. Reconnect uses **exponential backoff**: 2s → 4s → 8s → 16s → 30s cap, resetting on success.

---

## HTTP Pages & API

The status server (default port 8080) exposes these pages and endpoints.

### Quick Reference

| Path | Method | Description |
|---|---|---|
| `/` | GET | Main status page |
| `/memorial` | GET | Memorial wall — dead pairs |
| `/obs` | GET | OBS scene trigger configuration |
| `/debug` | GET | Debug console |
| `/twitch` | GET | Twitch bot configuration and activity log |
| `/stream` | GET | Stream overlay index |
| `/stream/party-a` | GET | Overlay — Player A party |
| `/stream/party-b` | GET | Overlay — Player B party |
| `/stream/links` | GET | Overlay — linked pairs |
| `/stream/linked-party` | GET | Overlay — both players' linked mons side-by-side |
| `/stream/boxed-links` | GET | Overlay — boxed linked pairs |
| `/stream/deaths` | GET | Overlay — death feed |
| `/stream/attempts` | GET | Overlay — attempts counter |
| `/stream/areas` | GET | Overlay — area states |
| `/stream/events` | GET | Overlay — recent events log |
| `/stream/badges-a` | GET | Overlay — Player A gym badges |
| `/stream/badges-b` | GET | Overlay — Player B gym badges |
| `/stream/encounters` | GET | Overlay — all encounter areas and states |
| `/stream/stream-memorial` | GET | Overlay — memorial wall |
| `/stream/ticker` | GET | Overlay — scrolling text ticker |
| `/stream/focus-a` | GET | Overlay — Player A focused mon view |
| `/stream/focus-b` | GET | Overlay — Player B focused mon view |
| `/stream/enemy-focus-a` | GET | Overlay — Player A active enemy mon(s), focus-style |
| `/stream/enemy-focus-b` | GET | Overlay — Player B active enemy mon(s), focus-style |
| `/stream/enemy-trainer-a` | GET | Overlay — Player A enemy trainer team, party-style autoscroll |
| `/stream/enemy-trainer-b` | GET | Overlay — Player B enemy trainer team, party-style autoscroll |
| `/stream/area-encounter` | GET | Overlay — Soul Link status for the current area |
| `/stream/enc-table-a` | GET | Overlay — wild encounter rates for Player A's current area |
| `/stream/enc-table-b` | GET | Overlay — wild encounter rates for Player B's current area |
| `/launcher/{player}` | GET | Download pre-configured launcher Lua script |
| `/calc/` | GET | Damage calculator |
| `/api/status` | GET | Full state JSON dump |
| `/api/events` | GET | SSE event stream |
| `/api/calc/mons` | GET | Live party + enemy data for calc bridge |
| `/api/bot/status` | GET | Bot status, config, and recent activity log |
| `/api/bot/config` | POST | Save non-sensitive bot config (channel, client_id, prefix, etc.) |
| `/api/bot/reload` | POST | Cancel and restart the bot connection |
| `/api/bot/enable` | POST | Enable the bot and restart |
| `/api/bot/disable` | POST | Disable the bot and cancel the task |
| `/api/bot/preview` | POST | Preview what a command would reply (without sending to Twitch) |
| `/obs` | GET | OBS scene trigger configuration page |
| `/api/obs/status` | GET | OBS connection status + trigger rules (passwords redacted) |
| `/api/obs/config` | POST | Save OBS config and hot-reload connections |
| `/api/obs/connect` | POST | Connect one or both OBS players |
| `/api/obs/disconnect` | POST | Disconnect one or both OBS players |
| `/api/obs/scenes/{player}` | GET | List available scenes from a connected OBS instance |
| `/api/obs/test` | POST | Test a scene switch for a player |
| `/api/reset` | POST | Wipe all state and start fresh |
| `/api/inject_link` | POST | Manually link two mons by key |
| `/api/inject_link_by_slot` | POST | Manually link two mons by party slot index |
| `/api/attempts` | POST | Set manual attempts counter |
| `/api/debug/raw_state` | GET | Raw JSON state (links.json + live fields) |
| `/api/debug/manual_link_data` | GET | Mon keys and area IDs for link UI |
| `/api/debug/backups` | GET | List rolling backup slots |
| `/api/debug/inject_event` | POST | Inject synthetic event through state machine |
| `/api/debug/queue_command` | POST | Queue a command for a player |
| `/api/debug/set_pokeballs` | POST | Set pokeballs_obtained for a player |
| `/api/debug/set_area_state` | POST | Override an area's state |
| `/api/debug/clear_pending` | POST | Clear pending captures |
| `/api/debug/unlink` | POST | Remove a link entry |
| `/api/debug/revive` | POST | Revive a dead/memorial link |
| `/api/debug/rollback` | POST | Restore state from a backup slot |

### Pages

All pages update live via SSE — no manual refresh needed.

**`GET /`** — Main status page showing both player cards with party, current area, ball count, linked pair table, area state table, and killfeed.

**`GET /memorial`** — Tombstone cards for every dead linked pair with greyscale sprites, nicknames, species, level, cause of death, and killer details.

**`GET /debug`** — Full debug console with panels for manual linking, event injection, command queuing, state toggles, raw state viewer, and backup rollback. Prefer this UI over raw curl calls for one-off corrections.

**`GET /stream`** — Index listing all available OBS overlays with browser source URLs.

### Stream Overlays

All overlays are designed as OBS browser sources. Each polls `/api/status` every 2 s and updates automatically. Add them in OBS via **Sources → Browser** and paste the URL.

URL parameters supported by all overlays:
- `?theme=dark` (default) / `?theme=light` / `?theme=transparent`
- `?layout=h` / `?layout=thin-h` / `?layout=thin-v` (party overlays only)

Scrolling overlays additionally accept:
- `?speed=1` (default) — multiplier from `0.25`–`3.0`. Values on the index page's speed pill buttons update the URL automatically.
- `?pause=2` (default, in seconds) — pause-after-loop on `enemy-trainer-{a,b}` when the doubled list overflows its mask. Range `0`–`10`. Values on the index page's pause pill buttons update the URL automatically.

| Overlay | URL | Use |
|---|---|---|
| Player A party | `/stream/party-a` | Player A's live party |
| Player B party | `/stream/party-b` | Player B's live party |
| Linked pairs | `/stream/links` | All linked pairs and their status |
| Linked party | `/stream/linked-party` | Both players' linked party mons side-by-side |
| Boxed links | `/stream/boxed-links` | Linked pairs currently in the PC box |
| Death feed | `/stream/deaths` | Scrolling log of deaths with cause and killer |
| Attempts counter | `/stream/attempts` | Current run attempt count (set via `POST /api/attempts`) |
| Area states | `/stream/areas` | All encounter areas and their current state |
| Events log | `/stream/events` | Recent game events (captures, faints, area changes) |
| Player A badges | `/stream/badges-a` | Player A's earned gym badges |
| Player B badges | `/stream/badges-b` | Player B's earned gym badges |
| Encounters | `/stream/encounters` | All encounter areas and their current state |
| Memorial wall | `/stream/stream-memorial` | Scrolling memorial for dead pairs |
| Ticker | `/stream/ticker` | Scrolling text ticker |
| Player A focus | `/stream/focus-a` | Player A focused mon view |
| Player B focus | `/stream/focus-b` | Player B focused mon view |
| Enemy focus A | `/stream/enemy-focus-a` | Player A's active enemy mon(s). Combines old `enemy-wild` and trainer-active overlays into one widget. Title shows "WILD ENCOUNTER" or trainer class/name; shows card + moves grid with live PP. In Gen 3 doubles, both active foes side-by-side. |
| Enemy focus B | `/stream/enemy-focus-b` | Same for Player B. |
| Enemy trainer A | `/stream/enemy-trainer-a` | Player A's enemy trainer's full team as a PARTY-style autoscrolling list (sprite, name, HP bar, status, Lv; active mons highlighted with stat-stage icons). Supports `?speed=` (0.25–3, default 1) and `?pause=` (0–10s, default 2). |
| Enemy trainer B | `/stream/enemy-trainer-b` | Same for Player B. |
| Area encounter | `/stream/area-encounter` | Soul Link status for the most-active area — linked pair, pending captures, or dead zone. Auto-follows the area with the most recent action. |
| Wild encounters A | `/stream/enc-table-a` | Wild Pokémon encounter rates for Player A's current area (Radical Red only). Shows each method — Walking, Surfing, Fishing — with sprite, species, rate %, and level range. Auto-scrolls when the list is taller than the overlay; supports `?speed=` multiplier. |
| Wild encounters B | `/stream/enc-table-b` | Wild Pokémon encounter rates for Player B's current area (Radical Red only). Same as above for Player B. |

### Launcher Script

**`GET /launcher/{player}`** — Returns a pre-configured `.lua` launcher script for the given player (`a` or `b`). The embedded server IP is taken from the HTTP `Host` header so the script works for LAN connections without editing.

```bash
# Download Player A launcher
curl http://localhost:8080/launcher/a -o slink_a.lua

# Download Player B launcher
curl http://localhost:8080/launcher/b -o slink_b.lua
```

### JSON API

---

**`GET /api/status`** — Returns the full current state as JSON.

```bash
curl http://localhost:8080/api/status
```

Example response (abbreviated):
```json
{
  "players": {
    "a": { "connected": true, "area": "route_3", "ball_count": 12, "party": [...],
           "encounter_table": {"Day": [{"species_id": 16, "name": "Pidgey", "rate": 45, "min_level": 3, "max_level": 5}]} },
    "b": { "connected": true, "area": "mt_moon", "ball_count": 8,  "party": [...],
           "encounter_table": null }
  },
  "links": [
    {
      "area_id": "route_1",
      "a": { "key": "12345678:87654321", "nickname": "PIDGEY",  "species": 16, "level": 12 },
      "b": { "key": "11111111:22222222", "nickname": "RATTATA", "species": 19, "level": 12 },
      "status": "alive"
    }
  ],
  "area_states": { "route_1": "linked", "route_3": "pending_b" },
  "pokeballs_obtained": { "a": true, "b": true }
}
```

---

**`GET /api/events`** — SSE stream. Pushes `event: ping` on every state change (triggers the status page to re-fetch) and `event: status` with the full JSON payload for direct consumers such as stream overlays and the calc bridge.

```bash
curl -N http://localhost:8080/api/events
# event: ping
# data:
#
# event: status
# data: {"players": {...}, "links": [...], ...}
```

---

**`GET /api/calc/mons`** — Returns live party and enemy data formatted for the calc bridge panel. Includes Showdown pastes, sprites, HP percentages, and matched trainer moves.

```bash
curl http://localhost:8080/api/calc/mons
```

```json
{
  "a": {
    "party": [
      {
        "key": "12345678:87654321",
        "species_name": "Charizard",
        "nickname": "CHAR",
        "level": 50,
        "ability_name": "Blaze",
        "item_name": "Charcoal",
        "hp_pct": 85,
        "showdown_paste": "Charizard @ Charcoal\nAbility: Blaze\nLevel: 50\n...",
        "sprite_html": "<img ...>",
        "moves": ["Flamethrower", "Air Slash", "Dragon Pulse", "Roost"]
      }
    ],
    "enemy": [...],
    "matched_set": "Leader Blaine"
  },
  "b": { "..." : "..." }
}
```

---

**`POST /api/reset`** — Deletes `data/links.json` and resets all in-memory state. Irreversible unless a backup exists.

```bash
curl -X POST http://localhost:8080/api/reset
# {"ok": true}
```

---

**`POST /api/inject_link`** — Manually create a linked pair. Resolves mon info from current party, box, and pending captures.

```bash
curl -X POST http://localhost:8080/api/inject_link \
  -H "Content-Type: application/json" \
  -d '{"a_key": "12345678:87654321", "b_key": "11111111:22222222", "area_id": "route_1"}'
```

If a mon already has a pending capture on a different area, the server returns `requires_force: true`. Add `"force": true` to override:

```bash
curl -X POST http://localhost:8080/api/inject_link \
  -H "Content-Type: application/json" \
  -d '{"a_key": "12345678:87654321", "b_key": "11111111:22222222", "area_id": "route_1", "force": true}'
# {"ok": true}
```

---

**`POST /api/inject_link_by_slot`** — Create a linked pair using party slot indices instead of mon keys. The keys are resolved server-side from the current party snapshot. Slots are 0-indexed.

```bash
# Link Player A's slot 0 to Player B's slot 0 on Route 1
curl -X POST http://localhost:8080/api/inject_link_by_slot \
  -H "Content-Type: application/json" \
  -d '{"a_slot": 0, "b_slot": 0, "area_id": "route_1"}'
# {"ok": true, "a_key": "12345678:87654321", "b_key": "11111111:22222222"}
```

---

**`POST /api/attempts`** — Set the run attempts counter shown on the `/stream/attempts` overlay. The value persists in `links.json`.

```bash
curl -X POST http://localhost:8080/api/attempts \
  -H "Content-Type: application/json" \
  -d '{"count": 7}'
# {"ok": true, "count": 7}
```

### Debug API

> All debug endpoints are also accessible through the `/debug` page UI. Prefer the UI for one-off corrections; use these endpoints for scripted or automated workflows.

---

**`GET /api/debug/raw_state`** — Returns the raw `links.json` contents plus any live-only fields not written to disk.

```bash
curl http://localhost:8080/api/debug/raw_state
```

---

**`GET /api/debug/manual_link_data`** — Returns all known mon keys (from party, box, and pending captures) and all area IDs. Used to populate the manual link form on the debug page.

```bash
curl http://localhost:8080/api/debug/manual_link_data
# {"a_mons": [{"key": "...", "display": "PIDGEY Lv12"}], "b_mons": [...], "areas": ["route_1", ...]}
```

---

**`GET /api/debug/backups`** — Lists rolling backup slots with timestamps and link/death counts. Up to 6 slots, oldest overwritten first.

```bash
curl http://localhost:8080/api/debug/backups
# {"backups": [{"slot": 1, "ts": "2025-05-01T12:00:00", "links": 14, "deaths": 2}, ...]}
```

---

**`POST /api/debug/inject_event`** — Send any synthetic event through the state machine exactly as if a Lua client had sent it. Returns any commands that were generated.

```bash
# Simulate Player A capturing a Pidgey on Route 1
curl -X POST http://localhost:8080/api/debug/inject_event \
  -H "Content-Type: application/json" \
  -d '{"player": "a", "event": "capture", "key": "12345678:87654321", "area_id": "route_1", "level": 12}'

# Simulate a faint
curl -X POST http://localhost:8080/api/debug/inject_event \
  -H "Content-Type: application/json" \
  -d '{"player": "a", "event": "faint", "key": "12345678:87654321"}'
# {"ok": true, "commands": [{"cmd": "force_faint", "key": "11111111:22222222"}]}
```

---

**`POST /api/debug/queue_command`** — Manually queue a command to be delivered to a player on their next TCP tick.

```bash
# Queue a force_faint for Player B
curl -X POST http://localhost:8080/api/debug/queue_command \
  -H "Content-Type: application/json" \
  -d '{"player": "b", "cmd": "force_faint", "key": "11111111:22222222"}'

# Queue a HUD message for Player A
curl -X POST http://localhost:8080/api/debug/queue_command \
  -H "Content-Type: application/json" \
  -d '{"player": "a", "cmd": "hud_show", "message": "Route 3 is dead zone!", "color": "255,80,80", "duration": 180}'
```

---

**`POST /api/debug/set_pokeballs`** — Set `pokeballs_obtained` for a player. Use to manually activate the nuzlocke gate without waiting for the game to detect a ball in the bag.

```bash
# Activate nuzlocke gate for Player A
curl -X POST http://localhost:8080/api/debug/set_pokeballs \
  -H "Content-Type: application/json" \
  -d '{"player": "a", "value": true}'

# Deactivate (reset gate)
curl -X POST http://localhost:8080/api/debug/set_pokeballs \
  -H "Content-Type: application/json" \
  -d '{"player": "a", "value": false}'
```

---

**`POST /api/debug/set_area_state`** — Manually override an area's state. Valid states: `unseen`, `pending_a`, `pending_b`, `pending_both`, `linked`, `dead_zone`.

```bash
curl -X POST http://localhost:8080/api/debug/set_area_state \
  -H "Content-Type: application/json" \
  -d '{"area_id": "route_3", "state": "dead_zone"}'
# {"ok": true, "area_id": "route_3", "state": "dead_zone"}
```

---

**`POST /api/debug/clear_pending`** — Remove pending captures. Omit `area_id` to clear all; include it to clear only that area.

```bash
# Clear all pending captures
curl -X POST http://localhost:8080/api/debug/clear_pending \
  -H "Content-Type: application/json" \
  -d '{}'

# Clear a specific area
curl -X POST http://localhost:8080/api/debug/clear_pending \
  -H "Content-Type: application/json" \
  -d '{"area_id": "route_3"}'
```

---

**`POST /api/debug/unlink`** — Remove a link entry and reset the area state to `unseen`. Use `index` (0-based) as a tiebreaker if multiple links share the same area.

```bash
curl -X POST http://localhost:8080/api/debug/unlink \
  -H "Content-Type: application/json" \
  -d '{"area_id": "route_1"}'
# {"ok": true}
```

---

**`POST /api/debug/revive`** — Revive a dead or memorial pair back to alive status. Clears death metadata, removes from `pending_memorials`, and re-adds keys to `party_keys`. **You must manually restore the mons in-game** — the server only updates its own records.

```bash
curl -X POST http://localhost:8080/api/debug/revive \
  -H "Content-Type: application/json" \
  -d '{"area_id": "route_1"}'
# {"ok": true, "area_id": "route_1", "message": "Link revived to alive"}
```

---

**`POST /api/debug/rollback`** — Restore `links.json` and `events.json` from a rolling backup slot (1–6). The current state is saved as `links.pre_rollback.json` and `events.pre_rollback.json` before restoring.

```bash
# List available backups first
curl http://localhost:8080/api/debug/backups

# Roll back to slot 2
curl -X POST http://localhost:8080/api/debug/rollback \
  -H "Content-Type: application/json" \
  -d '{"slot": 2}'
# {"ok": true, "slot": 2, "message": "Rolled back to backup 2"}
```

---

## Soul Link Rules Enforced

| Rule | Description |
|---|---|
| Encounter linking | First capture in an area by Player A links to the first capture in the same area by Player B |
| Dead zone | If either player fails to catch (runs, KOs, no encounter), neither player may use their catch from that area; the wild Pokémon's species and level are recorded for display |
| Illegal capture | A capture in an already-linked or dead-zone area is force-fainted and immediately queued for the memorial box — it cannot be used; the original missed-catch display is preserved |
| Faint propagation | When a linked mon faints, its partner immediately receives a `force_faint` command |
| Unlinked encounter quarantine | A capture in a pending area (partner hasn't caught yet) is auto-deposited to the PC — the mon cannot be used until linked |
| Party/box sync | If A's linked mon is in the party, B's partner must also be in the party — automatic deposit/retrieval. Paired sync enforcement: retrieval requires both players to have party room; otherwise both stay boxed |
| Memorial box | Both mons from a dead pair are moved to Box 13 ("Box 14" in-game) after the battle ends |
| Nuzlocke gate | Dead zone and faint propagation are inactive until the player obtains Pokéballs |
| Gift capture detection | Captures classified as gifts when (a) the area is a configured gift area (`is_gift_area()`) or (b) the captured mon is an egg in a non-daycare encounter area (NPC egg-gifts like Route 5 Togepi). The Lua client reads `is_egg` from `OFF_FLAGS` bit 2 and forwards it; `_is_gift_capture(area_id, is_egg)` in `server/state.py` combines this with `is_daycare_area()` so daycare-bred eggs (Route 5/Four Island day cares in Gen 3) remain normal captures. Gifts bypass the Pokéball gate and aren't subject to wild-catch quarantine. |
| Whiteout | All of A's party mons faint → all of B's linked party mons are force-fainted |
| Species clause (opt-in) | `--species-clause` — rejects links where both mons share the same evolution family (e.g. Charmander ↔ Charmeleon). Also rejects captures where the **same player** already has an alive linked mon of the same evo family (same-save duplicate prevention). Dead/memorial pairs don't block. The violating capture is force-fainted; the area stays pending for retry |
| Gender clause (opt-in) | `--gender-clause` — rejects links where both mons are the same gender (♂+♂ or ♀+♀). Genderless mons are exempt. The violating capture is force-fainted; the area stays pending for retry |
| Type clause (opt-in) | `--type-clause` — rejects links where both mons share any type (e.g. Charizard Fire/Flying ↔ Pidgey Normal/Flying — shared Flying). Uses RR type data when available; falls back to vanilla Gen I–III types. The violating capture is force-fainted; the area stays pending for retry |
| Shiny Clause (always on) | When a player catches a shiny, their partner's **next encounter** becomes the shiny's Soul Link partner (a bonus pair). The bonus pair goes through all normal Soul Link rules — lock clauses apply, faint propagation is enforced, party sync is required. The area that triggered the shiny is not consumed. If multiple shinies are caught before bonuses are claimed, bonuses queue up (FIFO). Gen 1 is naturally excluded (`is_shiny()` always returns `False`). The catching player receives a shiny sound effect and GUI prompt; the partner is notified that a bonus encounter is pending. |

---

## Feature Status

| Feature | Status |
|---|---|
| TCP transport (LuaSocket) | ✅ Working |
| ROM validation (FireRed/LeafGreen US 1.0) | ✅ Working |
| Archipelago (AP) patched ROM support | ✅ Working |
| Radical Red 4.1 (CFRU) support | ✅ Working |
| Area mapping (all FRLG routes/dungeons/locations) | ✅ Working |
| Encounter linking | ✅ Working |
| Nuzlocke gate (Pokéball check) | ✅ Working |
| Dead zone | ✅ Working |
| Dead zone encounter logging (species + level of fled/KO'd wild mon) | ✅ Working |
| Illegal capture → immediate force_faint + memorialize | ✅ Working |
| Faint propagation (`force_faint`) | ✅ Working |
| Gift/static Pokémon detection | ✅ Working |
| PC box capture (full party) with stats caching | ✅ Working |
| Whiteout detection + propagation | ✅ Working |
| Battle HP frame ordering (CFRU same-frame gBattleOutcome) | ✅ Working |
| Double-buffer party diff (independent entry pools) | ✅ Working |
| Memorial box (Box 13 write + `memorial.json`) | ✅ Working |
| Memorial box auto-named "THE DEAD" | ✅ Working |
| Party/box sync (`box_mon` / `party_mon`) | ✅ Working |
| Party sync — confirmation-based (`sync_retrieve_done` / `sync_retrieve_failed`) | ✅ Working |
| Party event debounce (3-frame, glitch-resistant) | ✅ Working |
| Status page — trainer names, Pokémon nicknames/species | ✅ Working |
| Status page — Pokémon gender symbols (♂/♀) | ✅ Working |
| Status page — linked pairs with human-readable names | ✅ Working |
| Status page — dead zone encounters shown (species + level) | ✅ Working |
| Status page — live PC box summary | ✅ Working |
| Status page — location names for all in-game locations | ✅ Working |
| Status page — live party HP bars (green/yellow/red) | ✅ Working |
| Status page — Pokémon type badges (party and PC box) | ✅ Working |
| Status page — battle display above party (in battle, Wild vs Trainer label, enemy types) | ✅ Working |
| Status page — live updates via Server-Sent Events (SSE) with fallback polling | ✅ Working |
| Status page — flicker-free DOM morphing (sprites/HP bars preserved across refresh) | ✅ Working |
| Status page — human-friendly location names | ✅ Working |
| In-game sound effects (link formed, dead zone, force faint, whiteout) | ✅ Working |
| In-game HUD overlay (deaths, party swap events) | ✅ Working |
| In-game HUD — new encounter notification | ✅ Working |
| Link management (debug page — link/unlink/override) | ✅ Working |
| Species clause (opt-in `--species-clause`) | ✅ Working |
| Gender clause (opt-in `--gender-clause`) | ✅ Working |
| Type clause (opt-in `--type-clause`) | ✅ Working |
| Shiny Clause (always on — bonus pairs) | ✅ Working |
| State persistence (`links.json`) | ✅ Working |
| Reconnect resilience (seq dedup + re-queue) | ✅ Working |
| Status page — pending captures with trainer names/sprites | ✅ Working |
| Status page — auto-refresh pause (on error) | ✅ Working |
| Safari Zone safe-state race condition fix | ✅ Fixed |
| Intro garbage data suppression (pre-save guard) | ✅ Working |
| Status page — gym badge bitmask display (8 badges per player) | ✅ Working |
| Status page — consolidated Encounters table (linked + pending + dead zones) | ✅ Working |
| Dynamic gift area IDs (`gift_<mapGroup>_<mapNum>`) | ✅ Working |
| Resolved areas on reconnect (`resolved_areas` command) | ✅ Working |
| Species clause — same-save duplicate prevention | ✅ Working |
| Gift area `no_catch` protection | ✅ Working |
| Unlinked encounter quarantine (pending → box until linked) | ✅ Working |
| Paired party sync — retrieval requires both players have room | ✅ Working |
| Lua client performance optimization (localized functions, display cache, frame-cached state) | ✅ Working |
| Status page — Pokémon sprites (PokeAPI + RR custom forms) | ✅ Working |
| Stream overlay — area encounter (Soul Link status for current area, SSE live updates) | ✅ Working |
| Stream overlay — wild encounter table per player (Radical Red; autoscroll; speed control) | ✅ Working |
| Stream overlay — correct CFRU species sprites (server-side NatDex conversion) | ✅ Working |
| Status page — Pokémon ability names (party, PC box, enemy) | ✅ Working |
| Status page — enemy held item display (inline with name, Gen 3 + Gen 4) | ✅ Working |
| Status page — ability description tooltips (hover for details, RR + vanilla) | ✅ Working |
| Duplicate capture in pending area → force_faint + memorialize | ✅ Working |
| Battle HP cache (CFRU writeback) | ✅ Working |
| Player identity lock (OT ID per slot — prevents wrong-save connections) | ✅ Working |
| Non-blocking TCP connector (zero stutter on reconnect) | ✅ Working |
| Run Manager (multi-run orchestration on port 8090) | ✅ Working |
| Borrowed-party battle protection (CFRU Poké Dude / mock battles) | ✅ Working |
| Persistent run metadata (rom_type, trainer_names — set-once) | ✅ Working |
| Nature change detection (RR Nature Changer NPC — monKey migration) | ✅ Working |
| Dynamic page titles (Pokémon Soul Link Tracker — variant — run name) | ✅ Working |
| PC box level resolution (multi-source fallback chain) | ✅ Working |
| RR item name display (profile-aware, 746 items from ROM scan) | ✅ Working |
| Memorial wall page (`/memorial` — SSE live updates, tombstone cards, CFRU→NatDex sprite fix) | ✅ Working |
| Dynamic URLs (external/LAN access — no hardcoded localhost) | ✅ Working |
| Launcher script download (HTTP-served, auto-configured host/port/player) | ✅ Working |
| Debug page (`/debug` — live SSE, link/unlink/override, mon key & area autofill, backup rollback) | ✅ Working |
| RR item ROM scanner (`lua/test_item_discovery.lua`) | ✅ Working |
| Manager back-link on status page (`--manager-port`) | ✅ Working |
| TCP port display on status page | ✅ Working |
| Character encoding — extended charset (/, ♂, ♀, «, », etc.) + nickname backfill | ✅ Working |
| Dupes clause — partner pending capture cross-check | ✅ Working |
| Doubles battle detection (Gen 3) — DOUBLES chip + side-by-side overlays | ✅ Working |
| Enemy moves and live PP detection in battle (Gen 3) | ✅ Working |
| Egg-gift classification (NPC eggs like Route 5 Togepi treated as gifts) | ✅ Working |
| Combined Enemy Focus + party-style Enemy Trainer overlays | ✅ Working |
| Auto-generated per-species ability name overrides (RR, from funnotbun) | ✅ Working |
| Damage calc form-name normalization (Lycanroc-Dusk, Necrozma fusions, etc.) | ✅ Working |
| Party compaction guard (PC deposit/withdrawal no longer triggers freeze) | ✅ Working |
| Rolling backups (5-min auto-save, 6 slots, restores `links.json` + `events.json`, rollback via debug page) | ✅ Working |
| Battle faint cascade prevention (monKey-indexed HP cache + force_fainted_keys guard) | ✅ Working |
| Item integrity protection (snapshot/verify during party sync — prevents CFRU item swaps) | ✅ Working |
| Debug page — revive dead/memorial links | ✅ Working |
| Debug page — live state panel (lock rules, identity, party keys, bonus keys, pending bonus queue) | ✅ Working |
| PP preservation on box sync (cache on deposit, restore on retrieve) | ✅ Working |
| RR town encounter areas (all towns mapped for Radical Red) | ✅ Working |
| **Damage Calculator Integration** | |
| Damage calculator — RR fork of Smogon calc embedded at `/calc/` | ✅ Working |
| SLink bridge panel — live party/linked/enemy data from server injected into calc | ✅ Working |
| Trainer set matching — enemy party auto-matched against Normal/Hardcore Radical Red sets | ✅ Working |
| One-click load — clicking any party row loads that mon into the calc attacker/defender slot | ✅ Working |
| Party panel — HP bars, status, active mon highlight, auto-scroll on battle start | ✅ Working |
| EV display suppressed in calc result — always assumed max, not shown in output string | ✅ Working |
| Calc search — full substring matching (Pokémon name, trainer/set name, moves) | ✅ Working |
| Calc search — match highlighting in dropdown results (accent-colour mark around matched terms) | ✅ Working |
| Twitch chat bot (twitchio 3.x EventSub WebSocket) | ✅ Working |
| OBS scene trigger integration (simpleobsws v5 async) | ✅ Working |
| OBS priority-based trigger resolution (draggable rules list) | ✅ Working |

---

## Running Tests

### Unit tests (no emulator required)

```bash
pytest tests/unit/ -v          # all 800 tests
pytest tests/unit/test_state.py -v        # 236 state machine tests
pytest tests/unit/test_gen3_adapter.py -v  # 182 Gen 3 adapter tests
pytest tests/unit/test_gen4_adapter.py -v  # 62 Gen 4 adapter tests
pytest tests/unit/test_gen1_adapter.py -v  # 78 Gen 1 adapter tests
pytest tests/unit/test_gen2_adapter.py -v  # 127 Gen 2 adapter tests
pytest tests/unit/test_gen5_adapter.py -v  # 63 Gen 5 adapter tests
pytest tests/unit/test_stat_stages.py -v   # 42 stat stage tests
pytest tests/unit/test_obs_priority.py -v  # 4 OBS priority tests
```

236 state machine tests covering: linking, dead zones, faint propagation, whiteout, party sync (including confirmation-based `sync_retrieve_done`/`sync_retrieve_failed`, PC swap event ordering), box capture stats caching, memorial box, reconnect re-queuing, illegal captures, encounter logging, AP ROM type handling, species clause (evo families), gender clause (genderless edge cases), type clause (shared types, partial overlap, monotypes), combined clauses, violation recovery, clause rule persistence, same-save species duplicate prevention, dynamic gift areas, hello resolved_areas, gift area no_catch protection, unlinked encounter quarantine, paired party sync enforcement, dead zone quarantined mon retirement, CFRU/RR species data validation (Gen 3 ID rekey, Gen 4+ cross-gen evolutions, gender ratios), battle HP cache writeback (CFRU), double-buffer party diff, frame ordering, player identity lock (OT ID per slot — first lock, wrong OT rejection, event blocking, persistence, empty party skip, per-player independence), persistent run metadata (rom_type, trainer_names), shiny bonus pairs (pending_bonus FIFO queue, pair formation, faint propagation both directions, party sync at formation, FIFO multi-bonus, lock clause violations with retry, area unresolve, persistence, key migration, no-wildcard-exemption), nature change (key_change migration), and dupes clause partner pending capture check.

4 OBS priority tests covering: highest-priority rule wins when multiple events fire simultaneously, lower-priority fallback when high-priority event didn't fire, independent per-player resolution, and area_id filter matching.

### Integration tests (server required)

```bash
# Terminal 1
python -m server.server --host 127.0.0.1 --port 54321

# Terminal 2
pytest tests/unit/test_phase1_comms.py -v
```

### BizHawk live tests

See `tests/TESTING.md` for the full 9-step end-to-end test procedure. Load `lua/slink.lua` on both instances and run through Steps 1–9 in order.

---

## Key Files

| File | Purpose |
|---|---|
| `lua/slink.lua` | **Universal entry point** — auto-detects game and loads correct client |
| `lua/slink_gen3.lua` | **Gen 3 launcher** — configure host/port/player, load in BizHawk |
| `lua/slink_gen4.lua` | **Gen 4 launcher** — configure host/port/player, load in BizHawk |
| `lua/slink_gen5.lua` | **Gen 5 launcher** — configure host/port/player, load in BizHawk |
| `lua/clients/gen3_frlge_client.lua` | Gen 3 production client — FRLG/Emerald/Radical Red. Localized BizHawk memory functions, display data cache, battle/overworld state cached once per frame. |
| `lua/clients/gen4_hgsspt_client.lua` | Gen 4 production client — HeartGold/SoulSilver. NDS memory model, LCRNG-aware, HP debounce. |
| `lua/clients/gen5_bw_client.lua` | Gen 5 production client — Black, White, Black 2, White 2. PID:OTID keys, 220-byte PKM structs, shared NDS helpers. |
| `lua/memory_gba.lua` | Gen 3 GBA RAM helpers — auto-detecting profiles (vanilla, AP, CFRU/RR), read/write, force-faint, box/party transfer, memorial write, SE playback via m4a engine |
| `lua/memory_nds.lua` | Gen 4/5 NDS RAM helpers — LCRNG encryption/decryption, 2-level pointer chain, HP debounce, party/box/battle reads |
| `data/games/gen3_frlge/gen3_frlge_areas.lua` | Gen 3 area lookup — `mapGroup*256+mapNum → area_id` (184 entries; `python tools/gen_area_map.py` to regenerate) |
| `data/games/gen4_hgsspt/gen4_hgsspt_areas.lua` | Gen 4 area lookup — `zoneId → area_id` (195 entries, auto-generated) |
| `lua/connector.lua` | Shared TCP connector — fully non-blocking connect, exponential backoff (2s → 30s cap) |
| `lua/game_detect.lua` | Shared game detection framework — scans ROM header to identify game family |
| `lua/games/gen3_frlge.lua` | Gen 3 game module — ROM detection, profiles, gift areas, area resolution |
| `lua/games/gen4_hgsspt.lua` | Gen 4 game module — NDS ROM detection, HGSS profiles, gift areas, area resolution |
| `lua/games/gen5_bw.lua` | Gen 5 game module — Black/White/BW2 detection, per-variant NDS profiles, gift areas, area resolution |
| `server/state.py` | `SoulLinkState` FSM — all Soul Link rule enforcement, adapter-driven |
| `server/server.py` | aiohttp coordinator + status page (flicker-free DOM morphing, battle display) |
| `server/adapters/gen1_rby.py` | Gen 1 adapter — DVs:OTID:species keys, RBY gift areas, Gen 1 sprites |
| `server/adapters/gen3_frlge.py` | Gen 3 adapter — GBA key format, FRLG+Emerald gift areas, Gen 1-3 species |
| `server/adapters/gen4_hgsspt.py` | Gen 4 adapter — PID:OTID keys, HGSS gift areas, Gen 1-4 species |
| `server/adapters/gen5_bw.py` | Gen 5 adapter — PID:OTID keys, BW/BW2 gift areas, Gen 1-5 species |
| `server/adapters/base.py` | Adapter ABC — GameRulesAdapter + GamePresentationAdapter interfaces |
| `data/games/gen1_rby/` | Gen 1 game data — area/location mappings |
| `data/games/gen3_frlge/` | Gen 3 game data — area maps, RR items/sprites/types/species/trainers |
| `data/games/gen4_hgsspt/` | Gen 4 game data — HGSS area map |
| `data/games/gen5_bw/` | Gen 5 game data — BW/BW2 area maps and location tables |
| `data/links.json` | Persisted link table — written after every state change |
| `data/memorial.json` | Persisted memorial log |
| `server/manager.py` | Run Manager — creates/starts/stops/archives named runs on port 8090 |
| `server/obs_controller.py` | OBS Controller — per-player `simpleobsws` connections, coalescing queue workers, priority-based `submit_fired()` resolver, config I/O at `data/obs_config.json` |
| `server/twitch_bot.py` | Twitch chat bot — twitchio 3.x EventSub, command handling, activity log |
| `lua/tests/` | BizHawk test scripts (memory, force-faint, server comms, ability diag, etc.) |
| `tools/` | Generator scripts — ability descriptions, ability names, form data, species data, RR data, sprites, types |
| `tests/TESTING.md` | Live BizHawk test guide |
| **Damage Calculator** | |
| `calc/src/normal.template.html` | Normal-difficulty calc page template (compiled → `dist/normal.html`) |
| `calc/src/hardcore.template.html` | Hardcore-difficulty calc page template (compiled → `dist/hardcore.html`) |
| `calc/src/js/slink_bridge.js` | SLink bridge panel — injects floating party panel into calc, SSE-driven live updates, one-click mon import |
| `calc/src/js/moveset_import.js` | Showdown paste importer — parses mon showdown paste and populates all calc fields |
| `calc/src/js/shared_controls.js` | Core calc UI logic — set/move dropdowns, search (substring matching + match highlighting), trainer set matching |
| `calc/src/js/index_randoms_controls.js` | Mode switching (Normal/Hardcore), trainer set matching bridge |
| `calc/src/js/data/sets/normal.js` | Normal-mode trainer sets data (SETDEX_SV for all RR trainers) |
| `calc/src/js/data/sets/hardcore.js` | Hardcore-mode trainer sets data |
| `calc/calc/src/desc.ts` | Result description string builder — EV display suppressed (always assumed max, not shown) |
| `calc/build` | Build script — compiles TypeScript, copies assets, hashes HTML; runs `node build` (full) or `node build view` (HTML-only) |

---

## Player Identity Lock

SLink prevents accidental wrong-save connections from corrupting a run. On the first `hello` event with a non-empty party, the server records the **OT ID** (from the first party mon's `personality:otId` key) and **trainer name** per player slot. All subsequent connections to that slot must present the same OT ID.

**How it works:**
- On first hello with party: OT ID and trainer name are locked for that slot (persisted in `links.json` under `"player_identity"`)
- On subsequent hellos: if the OT ID doesn't match, the connection is **rejected** — a red HUD message appears in BizHawk ("⚠ Wrong save! Expected [name] (OT: ...)" for 10 minutes) and all further events from that connection return `noop`
- The status page shows a **red error banner** in the player card when an identity mismatch is active
- Empty-party hellos (pre-game, title screen) are not checked and don't lock
- Each player slot (`a` and `b`) is locked independently
- The error clears automatically when a correct hello is received (e.g., the player reloads the right save)

**Why OT ID:** All mons from the same trainer share the same `otId` field — it's a stable identifier that survives party changes, evolutions, and reconnects. Unlike trainer name (which could theoretically collide), OT ID is a 32-bit value unique to each save file.

---

## Pokémon Ability Display

The status page displays ability names for party mons, PC box mons, and enemy/wild mons during battle. Abilities are resolved from `gBaseStats` in the ROM using the mon's species ID and ability bit (from the encrypted substruct data).

**How abilities are read:**
1. **Primary method:** `memory_gba.lua` decrypts the species ID and ability bit from the party/box mon's substruct, then looks up `gBaseStats[species].ability1` or `ability2` based on the bit
2. **Fallback (gBattleMons cache):** During battle, ability IDs are read directly from `gBattleMons[battler].ability` (offset `+0x20`). These are cached in `_ability_cache` keyed by monKey and used as a fallback when substruct decryption fails or returns 0
3. **Server-side:** `pokemon_data.py` provides `ability_name(ability_id, is_rr)` and `ability_description(ability_id, is_rr)`. For RR/CFRU (`is_rr=True`), uses a 255-entry table with RR-specific ability names and descriptions (sourced from funnotbun's RR Dex). For vanilla/Gen 4 (`is_rr=False`), uses a complete 165-entry vanilla table (Gen III–V, IDs 1-165) with correct standard ability names and descriptions. Hovering ability names on the status page shows a tooltip with the description.

**Per-species ability name overrides (RR/CFRU).** Some abilities have species-specific renames in Radical Red (e.g. Mightyena's "Intimidate" displays as "Strong Jaws"). `pokemon_data.CFRU_ABILITY_NAME_OVERRIDES` is a merge of two layers:

- `CFRU_ABILITY_NAME_OVERRIDES_GENERATED` — auto-built from funnotbun's `data/abilities/duplicate_abilities.h` by `tools/gen_ability_name_overrides_rr.py`. Output is written to `server/rr_ability_overrides.py` (regenerate by running the script; ~87 entries covering Shell Armor on Slowbro-Mega, Vital Spirit on Mankey/Primeape, Air Lock on Rayquaza, etc.).
- `CFRU_ABILITY_NAME_OVERRIDES_MANUAL` — hand-curated entries for species not yet in funnotbun's upstream file. Shadows GENERATED on key conflict, so locally-observed renames always win.

Override keys are `(ability_id, natdex_base_form)`. Form collisions (e.g. Kyurem-Black "Teravolt" and Kyurem-White "Turboblaze" both mapping to NatDex 646 with `ABILITY_MOLDBREAKER`) are detected by the generator and emit a warning; both entries are dropped so neither shadows the wrong form.

**Profile-specific gBaseStats addresses:**
| Profile | gBaseStats address | Source |
|---|---|---|
| Vanilla | `0x08254784` | Hardcoded from pret/pokefirered |
| AP | `0x0825634C` | Shifted from vanilla (AP recompiles from source) |
| RR/CFRU | Pointer at `0x080001BC` → actual address | Dynamic via CFRU function pointer |

---

## Archipelago (AP) Support

SLink auto-detects AP-patched ROMs and adjusts all memory addresses automatically. No manual configuration needed.

**How it works:**
- AP recompiles the FRLG binary, shifting all EWRAM globals (+0x14) and IWRAM pointers (−0xB0)
- `memory_gba.lua` reads a signature string at ROM offset 0x108 to detect AP ROMs ("pokemon red version" / "pokemon green version")
- All profile-dependent addresses are stored in a `PROFILES` table and applied at startup via `M.initProfile()`
- The status page shows "FireRed (AP)" or "LeafGreen (AP)" for AP clients

**AP address profile (complete):**

| Symbol | Vanilla | AP | Shift |
|---|---|---|---|
| `gMain` | `0x030030F0` | `0x03003040` | −0xB0 (IWRAM) |
| `gSaveBlock1Ptr` | `0x03005008` | `0x03004F58` | −0xB0 |
| `gSaveBlock2Ptr` | `0x0300500C` | `0x03004F5C` | −0xB0 |
| `gPokemonStoragePtr` | `0x03005010` | `0x03004F60` | −0xB0 |
| `gPlayerParty` | `0x02024284` | `0x02024298` | +0x14 (EWRAM) |
| `gBattleTypeFlags` | `0x02022B4C` | `0x02022B60` | +0x14 |
| `gBattleOutcome` | `0x02023E8A` | `0x02023E9E` | +0x14 |
| SB1 Pokéball pocket | `+0x0430` | `+0x0680` | +0x250 (struct) |
| SB2 `encryptionKey` | `+0x0F20` | `+0x0F2C` | +0x0C (struct) |
| `gBaseStats` | `0x08254784` | `0x0825634C` | +0xEBC8 (ROM) |

**AP-specific behavior:**

- **Overworld detection**: AP uses a custom `gMain+0x038` field (1 = overworld, anything else = not overworld) instead of the vanilla `gMain+0x439` inBattle bit
- **Battle detection**: Three-condition check prevents false triggers from menus: `gMain+0x038 != 1` AND `gBattleTypeFlags != 0` AND `gBattleOutcome == 0`. The `gBattleOutcome` check is necessary because `gBattleTypeFlags` stays stale (non-zero) after battles end in AP.
- **Item tracking**: AP expands bag pocket structs by 592 bytes (0x250). Item IDs are not encrypted; quantities are XOR'd with `encryptionKey & 0xFFFF` from `SB2+0x0F2C`. The AP encryption key is at a +0x0C shift from vanilla. `M.hasPokeballs()` and `M.countPokeballs()` use profile-dependent offsets automatically.
- **Battle redirect**: `forceImmediateWhiteout()` cannot redirect to `ReturnFromBattleToOverworld` in AP mode (ROM function address unknown); it zeros party HP only
- **Sound effects**: In-game SE playback works on AP ROMs. Song header addresses are discovered per-ROM via `lua/test_sound_discovery.lua` and stored in the AP profile's `SE_SONG_HEADERS` table.
- **Starter/gift linking**: AP supports randomized starting locations. If a gift/static Pokémon appears before `nuzlocke_active` is set, the client uses `"intro"` as the area_id so both players' starters link regardless of randomized start location. Post-nuzlocke gifts (Eevee, Lapras, fossils) use their real area_id. The server treats `"intro"` and `"gift"` as gift areas (no `pokeballs_obtained` activation, pre-nuzlocke faint immunity).
- **Menu/script state protection**: AP's `isInOverworld()` returns false during menus (bag, PC, Repel use). The `party_diff_ok` gate freezes all party change detection during non-overworld/non-battle states, preventing false `box_to_party`/`party_to_box` events from memory read glitches during BizHawk window resize or in-game menus.
- **Coexistence**: SLink runs alongside the AP BizHawk client — both use different memory write targets (AP writes item flags; SLink writes HP/party data)
- **Gym badge bitmask**: Badges are read from `SaveBlock1.flags[0x104]` as a raw bitmask (each bit = one badge). AP can grant badges out of order, so the status page renders each badge independently via `badge_mask & (1 << i)` — no assumption of sequential acquisition

---

## Radical Red (CFRU) Support

SLink fully supports **Pokémon Radical Red 4.1** and other [CFRU-based](https://github.com/Skeli789/Complete-Fire-Red-Upgrade) ROM hacks via the `radical_red` profile in `memory_gba.lua`. All core features — encounter linking, faint propagation, party/box sync, memorial box, species/gender/type clause — work identically to vanilla and AP.

**Auto-detection:** The ROM is identified by scanning for CFRU signature bytes in the ROM binary. `memory_gba.lua` calls `M._detectCFRU()` during `initProfile()`, which checks for known CFRU function signatures. If detected, the `radical_red` profile is applied automatically — no manual configuration needed. The status page shows "FireRed (Radical Red)" for RR clients.

### Key architectural differences from vanilla/AP

| Feature | Vanilla / AP | Radical Red (CFRU) |
|---|---|---|
| **Substruct encryption** | XOR-encrypted with `personality ^ otId`; permuted order based on `personality % 24` | **Unencrypted**; fixed order: Growth / Attacks / EVs / Misc |
| **PC box storage** | 80-byte `BoxPokemon` × 30 slots × 14 boxes (contiguous after `PokemonStorage+0x01`) | **58-byte `CompressedPokemon`** × 30 slots × **25 boxes** in **4 non-contiguous EWRAM regions** |
| **Party struct in battle** | Live — HP/level updated in real-time in `gPlayerParty` | **Stale during battle** — live HP/level only in `gBattleMons`; battle HP cache handles writeback to party struct on battle end |
| **Bag location** | Inside `SaveBlock1` (SB1 pointer + offset); AP encrypts quantities | **EWRAM at fixed address** (`0x0203C354` for ball pocket); not inside SB1; **not encrypted** |
| **Battle outcome (caught)** | `B_OUTCOME_CAUGHT = 6` | `B_OUTCOME_CAUGHT = 7` (`B_OUTCOME_MON_FLED = 6` inserted before it) |
| **Battle detection** | Vanilla: `gMain+0x439` inBattle bit. AP: `gMain+0x038` overworld + three-condition check | **`gBattleOutcome`-based** ("battle_outcome" detection mode) — `gMain` is unreliable in CFRU |
| **Species IDs** | National Pokédex (1–386) | Extended to ~1293 (Gen 1–8 + forms); IDs diverge from NatDex after Gen 2 |
| **Ball pocket slots** | 13 (vanilla) / 16 (AP) | **50 slots**; 27 ball item types (IDs up to 631) |

### Confirmed Radical Red addresses

| Symbol | Address | Notes |
|---|---|---|
| `gPlayerParty` | `0x02024284` | Same as vanilla EWRAM — **live** copy (stale during battle) |
| `gPlayerPartyCount` | `0x02024029` | EWRAM global |
| `SB1_PTR_ADDR` | `0x03003840` | IWRAM |
| `SB2_PTR_ADDR` | `0x03003838` | IWRAM |
| `PokemonStorage` base | `0x02029314` | EWRAM — first of 4 non-contiguous box regions |
| `gBattleMons` | `0x02023BE4` | EWRAM — live HP/level/status during battle |
| `gBattleOutcome` | `0x02023E8A` | EWRAM — same address as vanilla |
| Ball pocket | `0x0203C354` | EWRAM, 50 slots × 4 bytes, not encrypted |

### Battle HP cache (CFRU writeback)

In CFRU, `gPlayerParty` is **not updated during battle** — the game engine copies party data to `gBattleMons` at battle start and only writes back on battle end. This means faint detection during battle must read from `gBattleMons`, not `gPlayerParty`. The Lua client maintains a **battle HP cache** keyed by **monKey** (not slot index) that:

1. Reads HP from `gBattleMons` every frame during battle (mapping battler personality → monKey)
2. Detects faints (HP 0) in real-time from the battle struct — guards against re-reporting server-initiated force_faints via `force_fainted_keys` set
3. Writes back final HP values to `gPlayerParty` when battle ends — scans party by monKey to find the correct slot, ensuring writeback targets survive mon switches mid-battle

**Frame execution order (critical for CFRU):** CFRU can set `gBattleOutcome` on the **same frame** as the last mon's HP→0. The Lua client executes in this strict order each frame:

1. Battle start detection (clears cache)
2. Battle HP cache update from `gBattleMons` — gated on `in_battle OR battle_just_ended` to capture the final frame
3. Battle end writeback (writes cache to party struct, then clears cache)
4. `index_party()` — reads party struct with cache overlay if in battle
5. Party diff (faint/whiteout detection)

**Double-buffer party diff:** `index_party()` uses two independent entry pools (one per buffer frame) to compare previous and current party state. Each buffer owns its own pre-allocated entry tables so that writing current-frame HP never overwrites previous-frame data — this is essential for detecting HP transitions (alive → fainted).

### Doubles battle detection (Gen 3)

`is_doubles` is set on the battle state when `gBattlersCount >= 4` (`M.isDoubleBattle()` in `lua/memory_gba.lua`, `BATTLE_TYPE_DOUBLE_MASK` constant; works on all profiles including RR). Active battlers are read from `gBattlerPartyIndexes`: players are battlers 0+2, enemies are battlers 1+3. The status page renders a DOUBLES chip in the battle panel header; the `enemy-focus` overlay renders both active foes side-by-side via `.focus-mons.doubles`; the player `focus` overlay does the same when two party mons are active.

Singles also use `gBattlerPartyIndexes[0]`/`[1]` as the primary active-detection path, with species+level match against `gBattleMons` as a fallback when the index read is stale (`idx >= 6`, e.g. CFRU address drift). Gen 4/5 clients emit `evt.is_doubles=false` stubs for now.

### Enemy moves and live PP (Gen 3)

Each foe row in the status battle panel has a collapsible "Moves (N)" table. For active enemy battlers, moves and PP come from `gBattleMons[1]` (and `gBattleMons[3]` in doubles) at the following offsets:

- `+0x0C` — moves (4 × `uint16`)
- `+0x24` — current PP (4 × `uint8`)
- `+0x3A` — PP-Up bonuses (packed in one `uint8`)

The Lua client overlays these onto the matching enemy party entry so post-use PP shows immediately. CFRU's `battle_seen_enemies` accumulator and the player party snapshot also forward `pp_bonuses`. For full party slots (not just active battlers), `M.decryptMoves` and `M.decryptPpBonuses` in `memory_gba.lua` decode moves/PP/ppBonuses from substructs (CFRU unencrypted layout and vanilla/AP encrypted substruct both supported).

Server enrichment (`_enrich_party` / `_enrich_battle_state` in `server/server.py`) resolves raw move IDs via `adapter.move_data()`, attaches `current_pp` from `raw_pp[]`, and applies the PP-Up multiplier:

```
max_pp = base_pp + (base_pp * pp_ups) // 5
```

Without this multiplier, RR trainer mons with PP-Ups would show e.g. `56/35` instead of `56/56`. The formula is guarded by `if base_pp:` so unknown moves (base_pp = 0) don't divide-by-zero. The status page row uses a `data-key` so morphDOM preserves the user-toggled `<details open>` state across SSE refreshes.

---

## ROM Profiles

SLink supports three ROM profiles, auto-detected at startup by `memory_gba.lua`. All profile-dependent addresses are stored in the `PROFILES` table and applied via `M.initProfile()`.

| Profile | ROM type | Detection method | Battle detection | Box format | Substructs |
|---|---|---|---|---|---|
| **`vanilla`** | Standard FRLG US 1.0 + data-only randomizers (UPR, etc.) | Default — no AP or CFRU signature found | `gMain+0x439` inBattle bit (bit 1, mask `0x02`) | 80-byte `BoxPokemon` × 30 × 14 boxes | Encrypted (XOR `personality ^ otId`); permuted order (`personality % 24`) |
| **`ap`** | Archipelago-patched FRLG | ASCII string at ROM offset `0x108` ("pokemon red/green version") | `gMain+0x038` overworld check + three-condition battle check (`gMain+0x038 != 1` AND `gBattleTypeFlags != 0` AND `gBattleOutcome == 0`) | 80-byte `BoxPokemon` × 30 × 14 boxes | Encrypted (same scheme as vanilla) |
| **`radical_red`** | Radical Red 4.1 / CFRU-based hacks | CFRU signature bytes in ROM binary | `gBattleOutcome`-based ("battle_outcome" mode) — `gMain` unreliable in CFRU | 58-byte `CompressedPokemon` × 30 × 25 boxes (4 EWRAM regions) | **Unencrypted**; fixed order: Growth / Attacks / EVs / Misc |

For full address tables, see the [AP Support](#archipelago-ap-support) and [RR Support](#radical-red-cfru-support) sections above. All vanilla addresses in the FRLG Memory Map section below apply only to the `vanilla` profile — AP and RR use different addresses as documented in their respective profiles in `lua/memory_gba.lua`.

---

---

## Sync Timing Architecture

Sync commands (`box_mon`, `party_mon`, `memorialize`) are **deferred to safe state** to avoid corrupting party/box data during battle or transition animations.

**Safe state requirements (all must be true):**
1. **Overworld** — player is in the overworld (not in battle, menu, script, or animation)
2. **Sync cooldown expired** — a per-command cooldown prevents rapid-fire writes
3. **Not `battle_just_ended`** — the battle-end transition must fully complete
4. **`post_battle_frames == 0`** — a 30-frame cooldown after battle ends, plus a 90-frame post-battle grace period (~2 seconds total at 60fps)

**Execution model:**
- Commands execute **one per frame** to avoid party corruption from concurrent slot compaction (e.g., two `memorialize` commands zeroing adjacent slots simultaneously would corrupt the shift-down logic)
- The ~2-second post-battle buffer ensures the game engine has fully written back battle results to the party struct before SLink modifies it
- During the grace period, the Lua client suppresses party diff detection to avoid false `box_to_party` / `party_to_box` events from engine writeback

**PP preservation (CFRU):** The 58-byte compressed box format does not store PP. On deposit, the client caches PP values (read from party struct `+0x34..+0x37`) in `mon_stats_cache`. On retrieval via `retrieveBoxMon`, PP is restored from the cache (or defaults to 35 for non-zero moves as a fallback for legacy entries).

**Item integrity protection (CFRU):** CFRU's game engine may react to party modifications between frames and inadvertently swap held items. The client implements a defensive snapshot/verify system:
1. Before any sync operation (`box_mon`, `party_mon`, `memorialize`), `snapshot_party_items()` records every party mon's held item keyed by monKey
2. Immediately after the operation completes, `verify_party_items()` checks each mon's item against the snapshot and writes back any that changed unexpectedly
3. Verification continues for 5 frames after sync to catch between-frame engine interference
4. The snapshot stays current during normal gameplay (updated each `build_party_snapshot` call) so legitimate item changes (e.g., player equipping items) are never falsely reverted

---

## Configuration

Edit the top of your launcher (`lua/slink_gen3.lua` or `lua/slink_gen4.lua`) before loading:

```lua
local SLINK_HOST  = "192.168.1.100"  -- IP running server/server.py
local SLINK_PORT  = 54321
local SLINK_PLAYER = "a"             -- "a" for one game, "b" for the other
```

Server flags:

```bash
python -m server.server --help
# --host HOST         bind host (default: 0.0.0.0)
# --port PORT         TCP port (default: 54321)
# --http-port PORT    HTTP status port (default: 8080)
# --data-dir DIR      data directory for links/memorial JSON (default: data/)
# --run-id ID         optional run label (used in log output)
# --run-name NAME     display name for this run (shown in page titles)
# --manager-port PORT manager HTTP port (enables 'Run Manager' link on status page)
# --reset             delete links.json and memorial.json on startup
# --species-clause      reject links where both mons share the same evolution family
# --gender-clause       reject links where both mons share the same gender
# --type-clause         reject links where both mons share any type
```

---

---

## Twitch Bot

The built-in Twitch chat bot lets viewers query Soul Link run state in real time.

> **Requires twitchio 3.x** — the old IRC-based integration is discontinued by Twitch. This uses EventSub WebSocket.

### Bot Account Options

You have two setups to choose from:

**Option A — Broadcaster account as bot** (simpler)
The bot posts messages as your own channel account. Easiest to start with.

**Option B — Separate bot account** (recommended for stream)
Create a second Twitch account (e.g. "MySLinkBot"). The bot posts as that account so viewers see a distinct bot name. Both options use the exact same code — the only difference is which account you authorize when generating tokens.

### One-Time App Registration

Register a Twitch Developer app (on your own account) at [dev.twitch.tv/console](https://dev.twitch.tv/console):
- **Register Your Application** → Name: anything, Category: Chat Bot, Client Type: Confidential
- **OAuth Redirect URL: `https://twitchtokengenerator.com/`** ← required so twitchtokengenerator can complete the OAuth flow with your Client ID
- Copy your **Client ID**. Click **New Secret** and copy the **Client Secret**.

### Token Setup

**Required OAuth scopes** (twitchio 3.x EventSub — completely different from old IRC scopes):
- `user:read:chat` — receive messages from chat
- `user:write:chat` — send messages to chat
- `user:bot` — identify this account as a bot
- `channel:bot` — allow the bot in the broadcaster's channel

**Get tokens for the BOT account:** Visit [twitchtokengenerator.com](https://twitchtokengenerator.com):
1. **Option A:** stay logged in as your normal account.
   **Option B:** open an incognito window and log in as the bot account first.
2. Select **Custom Scope Token**
3. Paste your **Client ID** (from dev.twitch.tv — same for both options)
4. Enable the four scopes listed above
5. Click Generate Token, authorize **as the bot account**, and copy the **Access Token** and **Refresh Token**

Set environment variables **before** starting the server or manager:

```cmd
:: Windows cmd.exe — no spaces around =, no quotes
set TWITCH_ACCESS_TOKEN=bot_access_token        ← from twitchtokengenerator (bot account)
set TWITCH_REFRESH_TOKEN=bot_refresh_token      ← from twitchtokengenerator (bot account)
set TWITCH_CLIENT_SECRET=your_client_secret     ← from dev.twitch.tv/console → your app → New Secret
python -m server.manager
```

```powershell
# PowerShell
$env:TWITCH_ACCESS_TOKEN = "bot_access_token"   # from twitchtokengenerator (bot account)
$env:TWITCH_REFRESH_TOKEN = "bot_refresh_token" # from twitchtokengenerator (bot account)
$env:TWITCH_CLIENT_SECRET = "your_client_secret" # from dev.twitch.tv/console → your app → New Secret
python -m server.manager
```

Tokens are never written to disk or logged.

> **Note:** twitchio may create a `.tio.tokens.json` file in the project root as a local token cache. This file is safe to delete and is already listed in `.gitignore`.

The `/twitch` page shows **✓ Access Token set** and **✓ Client ID set** badges when detected. Connection errors appear in a red error box.

### Configuration

Non-sensitive settings live in `data/twitch_bot.json` (created from `data/twitch_bot.example.json`):

```json
{
  "channel": "your_broadcaster_channel",
  "nick": "your_bot_account_name",
  "client_id": "your_client_id_from_dev_twitch_tv",
  "prefix": "!",
  "command_cooldown_sec": 5,
  "enabled": true
}
```

- **`channel`**: your broadcaster channel name where viewers type commands (not the bot account name)
- **`nick`**: the bot account's username (for display only)
- **`client_id`**: not sensitive — safe to store here

These can also be edited live from the `/twitch` page without restarting the server.

### Commands

| Command | Argument | Description |
|---------|----------|-------------|
| `!soullink` | — | Plain-English Soul Link rules for new viewers |
| `!clauses` | — | Active clause rules (species / gender / type) |
| `!rip` | — | Most recent death with killer detail |
| `!runstats` | — | Attempt #, alive/dead counts, shinies, oldest pair |
| `!alltime` | — | Cross-run aggregate: attempts, deaths, shinies, best run |
| `!lastrun` | — | How the previous run ended |
| `!attempts` | — | Current attempt number |
| `!partner` | `<name>` | Look up a mon's Soul Link partner by nickname |
| `!area` | `<name>` | Look up an area's link status |

---

## OBS Scene Trigger Integration

SLink can automatically switch OBS scenes in response to game events, with independent control of each player's OBS instance.

### Setup

1. Enable **OBS WebSocket** in OBS Studio (`Tools → WebSocket Server Settings`) — default port 4455.
2. Navigate to `http://localhost:8080/obs`.
3. Enter the host, port, and password for each player's OBS instance and click **Save Config**.
4. Click **Connect** for each player. Status badges show `connected` when the WebSocket handshake succeeds.

Config is persisted at `data/obs_config.json` (global, not per-run). Passwords are write-only — they are never returned in GET responses.

### Trigger Rules

Create rules on the `/obs` page. Each rule maps a game event to a scene name:

| Field | Values | Description |
|---|---|---|
| Event | See table below | The game event that fires the rule |
| Player Filter | `any`, `a`, `b` | Only fire when this player triggers the event |
| Target OBS | `own`, `a`, `b`, `both` | Which OBS instance receives the scene change |
| Scene Name | any string | The scene to switch to (datalist populated from connected OBS) |
| Area Filter | `area_id` string | *(area_enter only)* restrict to a specific area |

### Supported Events

| Event | Fires when |
|---|---|
| `battle_start` | Any battle begins |
| `wild_battle_start` | A wild Pokémon battle begins |
| `trainer_battle_start` | A trainer battle begins |
| `battle_end` | A battle ends |
| `battle_start_new` | Battle starts in an area that still has an open encounter slot |
| `area_enter` | Player enters any area (with optional area_id filter) |
| `area_enter_new` | Player enters an area with an open encounter slot |
| `faint` | A player's own mon faints |
| `link_death` | A partner mon receives a `force_faint` command (linked death) |
| `whiteout` | A player blacks out |
| `capture` | A mon is caught |
| `shiny` | A shiny mon is caught (bonus pair trigger) |
| `linked` | An encounter area transitions to `linked` state |
| `dead_zone` | An encounter area transitions to `dead_zone` state |
| `party_to_box` | A mon is deposited from party to PC |
| `box_to_party` | A mon is retrieved from PC to party |
| `memorialize_done` | A dead pair is moved to the memorial box |
| `run_over` | The Soul Link run ends |

### Priority Resolution

Multiple events can fire in the same dispatch cycle (e.g., entering battle in a new encounter area fires `battle_start`, `wild_battle_start`, and `battle_start_new` simultaneously). Rules are evaluated **top-to-bottom** — for each OBS instance (player A or B), only the **first** matching rule wins.

Reorder rules by dragging the ⠿ handle. Click **💾 Save Config** after reordering.

### Implementation Details

- **Library:** `simpleobsws>=1.4` (fully async, obs-websocket v5). URL must be `ws://HOST:4455` — default v4 port (4444) is wrong.
- **Per-player coalescing queue:** each OBS player has an `asyncio.Queue(maxsize=1)` + dedicated worker task. If OBS is slow, only the latest desired scene is sent.
- **Reconnect loop:** exponential backoff 5 s → 60 s cap. OBS failures are fully isolated — they never affect game server operation.
- **`submit_fired(fired_list)`** — priority resolver called once per dispatch cycle with all `(event_name, src_player, metadata)` tuples; iterates rules in list order, sets winners dict (first match per target player wins).
- **`_emit_obs_triggers()`** in `server.py` collects all fired events for a dispatch cycle into a list and calls `obs.submit_fired(fired)` once at the end.

---

## Run Manager

The Run Manager provides multi-run orchestration from a single web interface on port 8090.

```bash
python -m server.manager --host 0.0.0.0
```

**Features:**
- Create, start, stop, and archive named runs — each run is a separate `server.py` subprocess with its own TCP port, HTTP port, and data directory
- Per-run clause rule configuration (species clause, gender clause, type clause) via UI checkboxes
- Launcher script downloads — generates pre-configured `slink_<player>.lua` files with the correct host IP, TCP port, and player ID based on the URL used to access the manager
- Direct links to each run's status page

**Endpoints:**

| Endpoint | Description |
|---|---|
| `GET /` | Manager dashboard |
| `GET /api/runs` | List all runs (JSON) |
| `GET /api/runs/cards` | HTML run cards (used internally by dashboard SSE) |
| `POST /api/runs/new` | Create a new run |
| `POST /api/runs/<id>/start` | Start a run |
| `POST /api/runs/<id>/stop` | Stop a run |
| `POST /api/runs/<id>/archive` | Archive a run |
| `POST /api/runs/<id>/delete` | Delete a run |
| `GET /api/runs/<id>/launcher/<player>` | Download launcher script (`player` = `"a"` or `"b"`) |

**Examples:**

```bash
# List all runs
curl http://localhost:8090/api/runs
# [{"id": "my-run", "name": "RR Season 3", "status": "running", "tcp_port": 54321, "http_port": 8080}, ...]

# Create a new run (species clause + type clause enabled)
curl -X POST http://localhost:8090/api/runs/new \
  -H "Content-Type: application/json" \
  -d '{"name": "RR Season 3", "species_clause": true, "gender_clause": false, "type_clause": true}'
# {"ok": true, "id": "rr-season-3"}

# Start a run
curl -X POST http://localhost:8090/api/runs/rr-season-3/start
# {"ok": true}

# Stop a run
curl -X POST http://localhost:8090/api/runs/rr-season-3/stop
# {"ok": true}

# Download Player A launcher script for a specific run
curl http://localhost:8090/api/runs/rr-season-3/launcher/a -o slink_a.lua
```

---

## Damage Calculator Integration

SLink embeds a fork of the [RadicalRedShowdown damage calculator](https://github.com/RadicalRedShowdown/damage-calc) directly into the HTTP server. It is accessible at `/calc/` (served as `normal.html` or `hardcore.html`) and includes a live **SLink Bridge Panel** that injects party data from the server into the calc UI.

### Pages

Only two pages are active in this fork:

| Page | URL | Description |
|---|---|---|
| Normal | `/calc/normal.html` | Normal-difficulty Radical Red trainer sets |
| Hardcore | `/calc/hardcore.html` | Hardcore-difficulty Radical Red trainer sets |

All other upstream calc pages (`randoms`, `index`, `honkalculate`, `oms`) have been removed — they are unreachable from the server and were unused.

### SLink Bridge Panel

A floating, draggable panel injected by `calc/src/js/slink_bridge.js` connects to the SLink server over SSE and displays:

- **Player A / Player B tabs** — each showing the active party, enemy battle mons, and linked mons
- **Prep tab** — searchable trainer index built from SETDEX data; select any trainer to view their full party with one-click import into the defender (`p2`) slot for pre-battle planning. Supports Normal and Hardcore modes with a toggle, multi-encounter trainers (Set 1 / Set 2 / Base sub-toggle sorted by average level), and multi-word search with token highlighting
- **Party rows** — sprite (32×32), nickname/species, level, nature, ability, held item, HP bar
- **Enemy rows** — matched trainer set moves with Normal/Hardcore difficulty badge
- **Active mon highlight** — orange left border + faint orange background on the currently active battler
- **One-click import** — clicking any row loads that mon's full Showdown paste into the calc attacker (`p1`) or defender (`p2`) slot automatically

The panel saves its position, collapsed state, and Prep tab selections (mode, trainer, encounter) in `localStorage`. It reconnects automatically via SSE on disconnect (3-second retry). Pings arriving while the user is interacting with the panel are deferred until `mouseup` to prevent DOM rebuilds mid-interaction.

**Server endpoint:** `GET /api/calc/mons` — returns per-player party, linked pairs, and enemy battle data in calc-friendly JSON format including `showdown_paste`, `sprite_html`, `hp_pct`, `ability_name`, `item_name`, and matched `moves`. See [JSON API](#json-api) for the full response shape.

**Species form normalization for calc.** The server emits species form names as `"Species (Form)"` or `"Species Form"` (e.g. `"Lycanroc (Dusk)"`, `"Necrozma (Dusk Mane)"`, `"Deoxys Attack"`), but Smogon's calc pokedex is keyed on hyphenated names (`"Lycanroc-Dusk"`, `"Necrozma-Dusk-Mane"`, `"Deoxys-Attack"`). `_normalizeSpeciesForCalc()` in `calc/src/js/slink_bridge.js` tries the name as-is, then `"Species (Form)"` → `"Species-Form"` (internal spaces in the form word also hyphenated), then plain space → hyphen. An override map exists for cases the rules can't catch. This covers Wormadam, Rotom, Burmy, Arceus, Silvally, Mega forms, Necrozma fusion forms, Pumpkaboo/Gourgeist sizes, Deoxys, and Lycanroc Dusk in one shot. Lookups that still miss surface a toast with the original (user-friendly) name.

### Trainer Set Matching

The bridge automatically detects which trainer set matches the current enemy party. It compares enemy mon species and levels against `SETDEX_HC` (hardcore) and `SETDEX_SV` (normal) simultaneously:

- Matching is fuzzy: species + level ± 2 must match ≥ 2 mons
- Hardcore is preferred if both match
- A difficulty badge (`HC ✓ 4/6` or `Normal`) appears on the player tab
- Matched trainer moves populate the enemy mon rows for quick calc import

### Search

The set/move/Pokémon dropdowns use full **substring search** — not starts-with. Any search term matches anywhere within the Pokémon name or trainer/set name:

- `"zard"` → finds Charizard
- `"Blue"` → finds all sets belonging to trainer Rival Blue
- `"bolt"` → finds Thunderbolt in move search

Results show the full `"Pokémon (Trainer Set Name)"` string so it is always clear what each result is. Matching characters are highlighted in the calc's accent colour (`#e94560`) using `<mark>` elements.

### Result Display

The calc result description line (e.g., `"Lvl 50 Charizard Flamethrower vs. Lvl 50 Blastoise: 45-53%"`) suppresses EV investment amounts. Since all mons in our runs are assumed to have maximum EVs, the original `"252 SpA"` / `"0 HP / 0 SpD"` text was always `0` (uninformative) and has been removed from `desc.ts`.

### Building the Calc

```bash
# Full build (TypeScript compile + bundle + HTML hash) — required after any .ts changes
cd calc && npm run build

# HTML/JS-only rebuild (faster — use after changes to src/ files only, no .ts)
cd calc && node build view
```

The build output goes to `calc/dist/`. Only `normal.html` and `hardcore.html` are generated. The build script no longer references the removed pages.

---

## Regenerate Area Map

If you add new map entries or fix area IDs:

```bash
python tools/gen_area_map.py
# Writes: data/games/gen3_frlge/gen3_frlge_areas.lua  (Lua lookup table)
```

---

## Development Guidelines

### Adapter Isolation (Preventing Cross-Gen Breakage)

The adapter pattern (`server/adapters/`) isolates game-specific logic. **All display and rule logic must flow through `self.adapter.<method>()`**, never through standalone functions with `is_rr` parameters.

**Key rules:**
1. Never add game-specific data or `is_rr` checks to `server.py` — use the adapter
2. Never import from `server.server` inside an adapter (circular dependency)
3. Use `gen4_hgsspt.py` as the template for new adapters (cleanest: zero deps, all data embedded)
4. Test ALL active games after changing `server.py`, `state.py`, or `adapters/base.py`

See `.github/copilot-instructions.md` → "Adapter Isolation Rules" for the full interface contract.

### Adding a New Game

1. **Lua game module** → `lua/games/<gen>_<game>.lua` (address profiles, game detection)
2. **Lua memory module** → `lua/memory_<platform>.lua` (if new hardware platform)
3. **Lua client** → `lua/clients/<gen>_<game>_client.lua` (event detection, command dispatch)
4. **Python adapter** → `server/adapters/<gen>_<game>.py` (implement `GameAdapter` ABC)
5. **Game data** → `data/games/<gen>_<game>/` (area maps, species data, items)
6. **Register** in `server/adapters/__init__.py`
7. **Tests** → `tests/unit/test_<gen>_adapter.py`

---

## Reference

- [pret/pokered](https://github.com/pret/pokered) — Gen 1 Red/Blue decomp; WRAM addresses and data structures
- [pret/pokeyellow](https://github.com/pret/pokeyellow) — Gen 1 Yellow decomp (shifted addresses)
- [pret/pokefirered](https://github.com/pret/pokefirered) — FRLG decomp; source for all RAM addresses and struct layouts
- [Skeli789/Complete-Fire-Red-Upgrade](https://github.com/Skeli789/Complete-Fire-Red-Upgrade) — CFRU source (Radical Red's engine base); defines CompressedPokemon, EWRAM bag, extended species IDs
- [BizHawk Lua Functions](https://tasvideos.org/BizHawk/LuaFunctions)
- [Archipelago connector_bizhawk_generic.lua](https://github.com/ArchipelagoMW/Archipelago/blob/main/data/lua/connector_bizhawk_generic.lua) — LuaSocket TCP technique
- [Gen III Pokémon data structure](https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_data_structure_(Generation_III))
- [Gen I Save Data Structure](https://bulbapedia.bulbagarden.net/wiki/Save_data_structure_(Generation_I)) — Gen 1 save layout, party/box addresses
- [Data Crystal RBY RAM Map](https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Red_and_Blue/RAM_map) — verified Gen 1 WRAM addresses
- [funnotbun RR Pokédex](https://funnotbun.github.io/) — Radical Red species data source for types, sprite filenames, and ability descriptions
