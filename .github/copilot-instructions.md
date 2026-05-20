<!-- Developer-facing quick reference for Copilot sessions. -->
# SLink – Pokémon Soul Link Nuzlocke Automation

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server (TCP port 54321, HTTP status port 8080)
python -m server.server
python -m server.server --host 127.0.0.1 --port 54321 --http-port 8080
python -m server.server --reset   # wipe all state and start a fresh run

# Full server CLI args:
#   --host HOST          bind host (default: 0.0.0.0)
#   --port PORT          TCP port (default: 54321)
#   --http-port PORT     HTTP status port (default: 8080)
#   --reset              Clear saved state
#   --data-dir DIR       Data directory for JSON files
#   --run-id ID          Run label for logs
#   --run-name NAME      Human-readable run name (in page title)
#   --species-clause       Reject same-evo-family links
#   --gender-clause        Reject same-gender links
#   --type-clause          Reject shared-type links
#   --manager-port PORT  Manager HTTP port (enables back-link)
#   --verbose            Enable structured DEBUG logging to <data-dir>/slink.log

# Unit tests — no emulator or server required (267 + 208 + 100 + 103 + 179 + 140 + 46 + 6 + 4 + 3 = 1056 tests)
pytest tests/unit/test_state.py -v
pytest tests/unit/test_gen3_adapter.py -v
pytest tests/unit/test_gen4_adapter.py -v
pytest tests/unit/test_gen1_adapter.py -v
pytest tests/unit/test_gen2_adapter.py -v
pytest tests/unit/test_gen5_adapter.py -v
pytest tests/unit/test_stat_stages.py -v
pytest tests/unit/test_phase1_comms.py -v
pytest tests/unit/test_obs_priority.py -v

# Single test
pytest tests/unit/test_state.py::test_faint_queues_force_faint_for_partner -v

# Regenerate data/games/gen3_frlge/gen3_frlge_areas.lua from area_map.json (184 entries)
python tools/gen_area_map.py

# Regenerate lua/gen2_crystal_areas.lua from area_map.json (124 entries)
python tools/gen_gen2_area_map.py

# Regenerate Gen 5 BW area maps and location tables
python tools/gen_gen5_area_map.py    # Gen 5 BW
```

## Project Overview

SLink automates a **Soul Link Nuzlocke** across two simultaneous Pokémon runs in [BizHawk](https://github.com/TASEmulators/BizHawk). Supported games include **Gen 1** (Red, Blue, Yellow), **Gen 2** (Crystal), **Gen 3** (FireRed, LeafGreen, Emerald, Radical Red/CFRU), **Gen 4** (HeartGold, SoulSilver, Platinum), and **Gen 5** (Black, White, Black 2, White 2). Each BizHawk instance runs a game-specific Lua client (`lua/clients/gen1_rby_client.lua`, `lua/clients/gen2_crystal_client.lua`, `lua/clients/gen3_frlge_client.lua`, `lua/clients/gen4_hgsspt_client.lua`, or `lua/clients/gen5_bw_client.lua`), which reads game RAM each frame and sends JSON events (area_enter, capture, faint, etc.) over a persistent **TCP connection** to a central Python server. The server uses a pluggable adapter framework (`server/adapters/`) to handle game-specific logic while enforcing Soul Link rules — pairing encounters by area, propagating faints, mirroring party presence — and returns commands (e.g., `force_faint`) in the TCP response. **No BizHawk CLI flags are required.**

### Game Maturity

**Only Gen 3 has been extensively tested in live gameplay.** Gen 1, 2, 4, and 5 have Python unit tests and Lua clients but limited real-world testing — treat them as experimental. When making changes to shared code (`server.py`, `state.py`, `adapters/base.py`), always verify Gen 3 isn't broken first, then run the other gen tests as a secondary check.

## Soul Link Rules (Full Specification)

All rules are enforced automatically by the system. Players cannot bypass them.

### 1. Encounter Linking
- The **first Pokémon captured in a given area** by Player A is permanently linked to the first Pokémon captured in **the same area** by Player B.
- If either player **fails to capture** on a route (KO, ran, no encounter), **both** players lose that slot — neither may use their catch from that area (dead zone).
- Static/gift Pokémon (Starter, Lapras, Eevee, fossils) are linked to the partner's encounter on the same map. Python detects them as new monKeys appearing while `in_battle == False`. No special handling beyond that edge case check.
- Egg hatches, trades, and in-game trades are out of scope unless explicitly included.

### 2. Encounter Area Identity
- Areas are identified by canonical **`area_id`** (see Area Normalization below), not raw mapGroup+mapNum.
- Multi-floor dungeons (Mt. Moon, Rock Tunnel, Silph Co.) share one area_id per building — encounters on any floor count as the same area.
- Sea routes traversed by Surf are distinct from their land counterparts.

### 3. Dead Zone Lifecycle
Each encounter area per player pair goes through these states:

```
UNSEEN → PENDING_B (A entered/captured) → PENDING_BOTH
       → PENDING_A (B entered/captured) → PENDING_BOTH
  ↓ capture from pending state          ↓ both captured
LINKED ←──────────────────────────────────────────────
  ↓ one side fails to catch
DEAD_ZONE (no capture allowed for either player on this area)
```

**PENDING_X semantics**: `PENDING_X` means "waiting for X to act" — the *other* player has already entered or captured. For example:
- A enters unseen area → `PENDING_B` (waiting for B to enter or capture)
- B captures in `PENDING_B` area → checks A's pending capture; if present → `LINKED`

A "failed catch" is: left the area without capturing AND the battle/encounter ended. The `no_catch` gate lives in Lua (`nuzlocke_active` / `M.hasPokeballs()`) — the server processes `no_catch` events as-received and always transitions to `DEAD_ZONE`.

### 4. Faint Linking (Two-Phase)
**Phase 1 — Battle-safe (immediate):** When HP drops to 0 for a linked mon, the server issues a `force_faint` command to the partner's game. The Lua client writes HP=0 to the partner mon's party slot. This happens in the same frame window.

**Nuzlocke gate**: Faints before `nuzlocke_active` is set (i.e., before the player has Pokéballs in their bag) are **ignored** by the server — the Soul Link death rule does not apply before the run begins. This protects starters that faint in the opening rival battle.

**Phase 2 — Memorialization (deferred):** Only once both games are in a **safe state** (overworld, not in a battle/menu/animation), move both mons to the memorial box (Box 13, internal index 13 / UI "Box 14"). Zero the source slot's BoxPokemon data after copying. The Lua client signals `safe_state` each frame; the server queues the memorial write until it is acknowledged.

Never zero or copy party/box data while `gBattleOutcome` is unresolved or a script is running.

### 5. Party Presence Sync
The rule is: **if one linked mon is in the party, its partner must also be in the party**. Both must be in the box together or both in the party together. Specific slot positions do not need to match.

- If Player A moves a linked mon to the PC, the server issues a `box_mon` command to Player B's game. This is deferred to the next overworld safe state.
- If Player A's party is full and they attempt to take the linked mon out of the box, the server blocks the action (or queues a party-clear step).
- The Lua client writes party-to-party sync directly to RAM during safe overworld state. Box operations require the game to be at the PC interface, so the system logs a **pending sync** and surfaces it as an on-screen HUD notice until the player manually resolves it at the PC.

### 6. Fainted Pair Retirement
- Both mons in a dead pair are moved to the **memorial box** (Box 13, 0-indexed).
- Memorial box is filled sequentially; if full, overflow to Box 12, etc.
- The server persists the memorial log (`data/memorial.json`) with personality+otId, nickname, species, area, and cause of death.
- Mons in the memorial box are never interacted with again by automation.

### 7. Whiteout
If a player whiteouts (entire party faints), all remaining party mons are treated as fainted. Their linked partners receive force-faint commands. Soul Link run ends if no usable linked pairs remain.

---

## Architecture

```
[BizHawk Instance A (Gen 2 GBC)]     [BizHawk Instance B (Gen 2 GBC)]
  lua/clients/gen2_crystal_client.lua  lua/clients/gen2_crystal_client.lua
  lua/memory_gb.lua                    lua/memory_gb.lua
  lua/gen2_crystal_areas.lua           lua/gen2_crystal_areas.lua

[BizHawk Instance A (Gen 3 GBA)]     [BizHawk Instance B (Gen 3 GBA)]
  lua/clients/gen3_frlge_client.lua    lua/clients/gen3_frlge_client.lua
  lua/memory_gba.lua                   lua/memory_gba.lua
  data/games/gen3_frlge/gen3_frlge_areas.lua

[BizHawk Instance A (Gen 4 NDS)]     [BizHawk Instance B (Gen 4 NDS)]
  lua/clients/gen4_hgsspt_client.lua   lua/clients/gen4_hgsspt_client.lua
  lua/memory_nds.lua  — NDS RAM        lua/memory_nds.lua  — NDS RAM

[BizHawk Instance A (Gen 5 NDS)]     [BizHawk Instance B (Gen 5 NDS)]
  lua/clients/gen5_bw_client.lua      lua/clients/gen5_bw_client.lua
  lua/memory_nds.lua                  lua/memory_nds.lua
         |  newline-delimited JSON (TCP)         |
         +────────────────┬──────────────────────+
                          ↓
                   [server/server.py]   ← asyncio TCP server on :54321
                   [server/state.py]    ← SoulLinkState FSM + adapters
                   [server/adapters/]   ← gen2_crystal, gen3_frlge, gen4_hgsspt, gen5_bw
                   [data/links.json]    ← persisted link table + area states
                   [data/games/]        ← game-specific data per generation
                          |
                   [HTTP status page]  ← aiohttp on :8080  (browser only)
```

**Communication model — TCP, event-driven:**
- **Lua = TCP client** — The client script connects via LuaSocket (persistent connection) and sends newline-delimited JSON events whenever something changes (area, capture, faint). No polling.
- **Python = TCP server** — `server/server.py` uses `asyncio.start_server` on port 54321. One connection per BizHawk instance. Game-specific logic is delegated to adapters (`server/adapters/`).
- Commands flow back in the TCP response as a newline-delimited JSON object: `{"commands": [{"cmd": "force_faint", "key": "..."}]}`.
- Lua parses the response and executes commands directly (e.g., writes HP=0 to RAM).
- A **separate aiohttp HTTP server** on port 8080 serves the live status page — it is never touched by Lua.

```lua
-- client.lua: event sent whenever something changes
send_event({event="faint", player="a", seq=42, key="AABBCCDD:11223344", area_id="route_1"})
-- server returns on the same TCP connection:
-- {"commands":[{"cmd":"force_faint","key":"EEFF0011:22334455"}]}
-- client immediately writes HP=0 to that party slot
```

**Key files:**

### Directory Layout

```
SLink-RR/
├── lua/                         # BizHawk Lua scripts (loaded by emulator)
│   ├── slink.lua                # Universal entry point (auto-detects game)
│   ├── slink_gen3.lua           # Gen 3 loader (loads gen3_frlge_client)
│   ├── slink_gen4.lua           # Gen 4 loader (loads gen4_hgsspt_client)
│   ├── slink_gen5.lua           # Gen 5 loader (loads gen5_bw_client)
│   ├── clients/                 # Per-game production clients (one per supported game)
│   │   ├── gen2_crystal_client.lua
│   │   ├── gen3_frlge_client.lua
│   │   ├── gen4_hgsspt_client.lua
│   │   └── gen5_bw_client.lua
│   ├── games/                   # Per-game adapter configs (address tables, constants)
│   │   ├── gen2_crystal.lua
│   │   ├── gen3_frlge.lua
│   │   ├── gen4_hgsspt.lua
│   │   ├── gen1_rby.lua         # Stub (future)
│   │   ├── gen2_gsc.lua         # Stub (future)
│   │   └── gen5_bw.lua          # Gen 5 game module
│   ├── memory_gba.lua           # GBA memory read/write helpers (Gen 3)
│   ├── memory_gb.lua            # GB/GBC memory read/write helpers (Gen 1 & Gen 2)
│   ├── memory_nds.lua           # NDS memory read/write helpers (Gen 4 & Gen 5)
│   ├── hud.lua                  # Shared HUD overlay module
│   ├── connector.lua            # LuaSocket TCP wrapper (non-blocking)
│   ├── game_detect.lua          # ROM header game detection
│   ├── socket.lua               # LuaSocket shim (loads DLL)
│   ├── gen2_crystal_areas.lua   # Area lookup table (Gen 2, 124 entries)
│   ├── gen2_crystal_locations.lua # Location name lookup (Gen 2, 81 areas)
│   ├── tests/                   # BizHawk test scripts (run manually in emulator)
│   └── x64/                     # LuaSocket binary DLL
├── server/                      # Python server (TCP + HTTP)
│   ├── server.py                # Main TCP/HTTP server (asyncio + aiohttp)
│   ├── state.py                 # SoulLinkState FSM (game-agnostic)
│   ├── obs_controller.py        # OBS WebSocket controller (simpleobsws, per-player queues)
│   ├── pokemon_data.py          # Species names, evo families, types, abilities
│   ├── move_data.py             # Move names and properties (Gen 3 RR + vanilla)
│   ├── manager.py               # Run Manager (multi-run orchestration)
│   └── adapters/                # Per-game server adapters
│       ├── base.py              # Abstract base adapter
│       ├── gen1_rby.py          # Gen 1 adapter
│       ├── gen2_crystal.py      # Gen 2 adapter
│       ├── gen3_frlge.py        # Gen 3 adapter
│       ├── gen4_hgsspt.py       # Gen 4 adapter
│       └── gen5_bw.py           # Gen 5 adapter
├── data/                        # Runtime data (persisted state + game data)
│   ├── links.json               # Active run state (auto-generated, not committed)
│   ├── memorial.json            # Death log (auto-generated)
│   ├── runs/                    # Run Manager named runs (each has own links.json)
│   └── games/                   # Per-game static data
│       ├── gen3_frlge/          # FRLG/RR items, types, sprites, area maps + gen3_frlge_areas.lua
│       ├── gen4_hgsspt/         # HGSS/Pt area maps + gen4_hgsspt_areas.lua
│       ├── gen2_crystal/        # Crystal species, types, items, area maps
│       ├── gen1_rby/            # Placeholder
│       ├── gen2_gsc/            # Placeholder
│       └── gen5_bw/             # Gen 5 area maps and location data
├── tools/                       # Code generation scripts (run manually)
│   ├── gen_pokemon_data.py      # Generates pokemon_data.py tables
│   ├── gen_ability_names.py     # Generates ability name table
│   ├── gen_rr_types.py          # Generates RR type data
│   ├── gen_gen2_area_map.py     # Generates gen2_crystal_areas.lua + gen2_crystal_locations.lua
│   ├── gen_gen5_area_map.py     # Generates Gen 5 BW/BW2 area maps
│   └── ...                      # Other generators
├── tests/                       # Python test suite
│   ├── unit/                    # Unit tests (pytest, no emulator needed)
│   │   └── test_gen5_adapter.py # Gen 5 adapter tests
│   ├── integration/             # Integration tests
│   ├── fixtures/                # Test fixtures
│   └── TESTING.md              # Test documentation
├── tools/                        # Generator scripts (area maps, ability data, species data)
├── requirements.txt             # Python dependencies
└── README.md                    # User-facing documentation
```

**File placement rules:**
- **New game client** → `lua/clients/<gen>_<game>_client.lua`
- **New game adapter (Lua)** → `lua/games/<gen>_<game>.lua`
- **New game adapter (Python)** → `server/adapters/<gen>_<game>.py`
- **New game static data** → `data/games/<gen>_<game>/`
- **New memory module** → `lua/memory_<platform>.lua` (shared across games on same hardware)
- **New area table** → `lua/<gen>_<game>_areas.lua`
- **New code generator** → `tools/`
- **Shared Lua modules** → `lua/` root (e.g., `hud.lua`, `connector.lua`)
- **Never** place game-specific files in the root or in another game's directory

*Gen 3 Lua (GBA — FRLG / Emerald / Radical Red):*
- **`lua/slink.lua`** — Universal entry point: auto-detects game via game_detect.lua and loads the correct client.
- **`lua/slink_gen3.lua`** — Gen 3 launcher script (configure host/port/player, loads gen3_frlge_client.lua).
- **`lua/clients/gen3_frlge_client.lua`** — **Gen 3 production script**: ROM validation, event detection, TCP transport, command dispatch, party-sync writes, battle HP cache with frame-ordered writeback (CFRU), double-buffer `index_party()` with per-buffer entry pools, F-key manual overrides, nature change detection (personality-changed key migration via otId+species+level+nickname signature matching), borrowed battle rolling gift capture buffer (3+ gifts in 45 frames triggers freeze), encounter GUI prompts. Party compaction after memorialize uses **swap-to-end** (last slot moves into vacated slot, no sequential shift) to preserve surviving mons' slot indices.
- **`lua/memory_gba.lua`** — FRLG address constants and read/write helpers (including `M.hasPokeballs()`, `M.countPokeballs()`). Contains `PROFILES` table with vanilla, AP, and Radical Red/CFRU address profiles. `M.initProfile()` auto-detects ROM type and applies the correct profile. Extended `_CHARSET` with `/` (0xBA), `,` (0xB9), `$` (0xB8), `♂` (0xB5), `♀` (0xB6), `'` (0xB3), `'` (0xB4), `·` (0xAF), `…` (0xB0), `«` (0xB1), `»` (0xB2).
- **`data/games/gen3_frlge/gen3_frlge_areas.lua`** — Generated lookup: `mapGroup*256+mapNum → area_id` (184 entries). Regenerate with `python tools/gen_area_map.py`.

*Gen 2 Lua (GBC — Crystal):*
- **`lua/slink_gen2.lua`** — Gen 2 launcher script (configure host/port/player, loads gen2_crystal_client.lua).
- **`lua/clients/gen2_crystal_client.lua`** — **Crystal production client**: 2-byte map addressing (mapGroup+mapNumber), 48-byte party / 32-byte box structs, held item tracking, Apricorn ball detection for nuzlocke gate, sequential NatDex species (no index lookup needed). DV-based gender and shiny detection.
- **`lua/memory_gb.lua`** — GB/GBC memory read/write helpers (shared with Gen 1). Extended with Crystal profile: wPartyCount, wPartyMon1, wMapGroup/wMapNumber, wBattleMode, wPlayerID addresses. `M.hasPokeballs()` scans ball pocket for Poké/Great/Ultra/Master balls and Apricorn balls (Level, Lure, Moon, Friend, Fast, Heavy, Love).
- **`lua/games/gen2_crystal.lua`** — Crystal game module: ROM detection via `PM_CRYSTAL` title at GB header `0x0134` + GBC flag `0x0143 == 0x80`, single memory profile (no ASLR), gift areas (new_bark_town, goldenrod_city, olivine_city, dragons_den, route_34), area resolution via `mapGroup*256+mapNumber`.
- **`lua/gen2_crystal_areas.lua`** — Generated lookup: `mapGroup*256+mapNumber → area_id` (124 entries). Regenerate with `python tools/gen_gen2_area_map.py`.
- **`lua/gen2_crystal_locations.lua`** — Area display names (81 unique areas).

*Gen 4 Lua (NDS — HGSS / Platinum):*
- **`lua/slink_gen4.lua`** — Gen 4 launcher script (configure host/port/player, loads gen4_hgsspt_client.lua).
- **`lua/clients/gen4_hgsspt_client.lua`** — Gen 4 NDS client: HeartGold/SoulSilver. Ported from SLink-HGSS prototype. LCRNG-aware, HP debounce, zone-based area detection. Uses memory_nds.lua for NDS RAM access.
- **`lua/memory_nds.lua`** — Shared Gen 4/5 NDS memory helpers (730 lines): 2-level pointer chain resolution, LCRNG encryption/decryption, party/box/battle reads, HP debounce (2-frame filter), Pokéball counting, trainer name reading. Game-specific addresses from variant profile.
- **`lua/games/gen4_hgsspt.lua`** — Gen 4 game module: HGSS/Platinum detection via NDS ROM codes (IPKE/IPGE/CPUE), per-variant memory profiles, gift areas (new_bark_town, route_30, ruins_of_alph, dragons_den), area resolution via zone IDs.
- **`data/games/gen4_hgsspt/gen4_hgsspt_areas.lua`** — Generated lookup: `zoneId → area_id` (195 entries). Source: data/games/gen4_hgsspt/area_map_hgss.json.

*Gen 5 Lua (NDS — Black / White / Black 2 / White 2):*
- **`lua/slink_gen5.lua`** — Gen 5 launcher script (configure host/port/player, loads gen5_bw_client.lua).
- **`lua/clients/gen5_bw_client.lua`** — Gen 5 NDS client: Black, White, Black 2, and White 2. Uses PID:OTID keys, 220-byte PKM structs, and the shared memory_nds.lua helpers.
- **`lua/games/gen5_bw.lua`** — Gen 5 game module: Black/White/BW2 detection via NDS ROM codes, per-variant memory profiles, BW1/BW2 gift areas, and zone-based area resolution.
- **`data/games/gen5_bw/gen5_bw_areas.lua`** — Generated lookup: `zoneId → area_id` for Black/White/BW2. Regenerate with `python tools/gen_gen5_area_map.py`.

*Shared Lua:*
- **`lua/connector.lua`** — LuaSocket wrapper with fully non-blocking connect (zero stutter), exponential backoff (2s → 30s cap), pending-connect probe via zero-byte send: `C.init()`, `C.send()`, `C.receive()`.
- **`lua/socket.lua`** — LuaSocket shim; requires `lua/x64/socket-windows-5-4.dll` (from Archipelago install).
- **`lua/game_detect.lua`** — Shared game detection framework: scans ROM header to identify the game family (Gen 2 GBC, Gen 3 GBA, Gen 4 NDS, or Gen 5 NDS), returns the matching game module.

*Server:*
- **`server/state.py`** — `SoulLinkState` FSM: processes event dicts, queues commands for each player, persists state. Includes `_check_link_violation()` for species/gender/type clause rules.
- **`server/server.py`** — asyncio TCP coordinator + aiohttp status page. Routes events to the FSM. Tracks per-player area, ball count, and party snapshots for the status page. Dynamic page titles via `_page_title()` method (shows "Pokémon Soul Link Tracker — \<variant\> — \<run name\>" with Pokéball SVG icon). `_resolve_level()` provides multi-source level fallback for manual links and PC box mons. Commits `rom_type` and `trainer_names` on first hello (set-once). Memorial wall page at `/memorial` (SSE live updates, tombstone cards with server-side `_sprite_img_html()` for correct CFRU→NatDex sprite conversion). Debug page at `/debug` (manual linking/unlinking, event injection, command queuing, state toggles, backup rollback, raw state — all panels live-updating via SSE). OBS page at `/obs` (per-player connection management, draggable priority trigger rules). Launcher script download at `/launcher/{player}` (host from HTTP Host header). Accepts `--manager-port` CLI arg for Run Manager back-link. Accepts `--verbose` CLI flag: enables `_configure_logging()` which adds a `RotatingFileHandler` (10 MB × 5) to `<data_dir>/slink.log` with structured DEBUG tags for every accepted event, command flush, FSM transitions, party/faint/clause/reconcile/shiny lifecycle events, and adapter init. RR item names loaded from `data/games/gen3_frlge/rr_items.json`. TCP port displayed on status page. Rolling backups of `links.json` **and `events.json`** every 5 min when both players connected (6 slots with rotation; rollback restores both files atomically). `_cache_mon_info()` backfills stale link entry nicknames from live party data. Capture events populate `mon_stats` directly (fallback from top-level `hp`/`maxHP`/`level` fields). `sprite_html` field in party_details and killfeed JSON APIs. Enemy battle type badges and held items in status page.
- **`server/obs_controller.py`** — `OBSController`: per-player `simpleobsws` WebSocket connections (obs-websocket v5, port 4455), per-player coalescing `asyncio.Queue` + worker tasks, reconnect loop with exponential backoff (5 s → 60 s cap). `submit_fired(fired_list)` priority-resolves a list of `(event_name, src_player, metadata)` tuples in one pass — iterates rules in list order, first match per target player wins. Config persisted at `data/obs_config.json` (global, not per-run). Passwords never returned in GET responses.
- **`server/pokemon_data.py`** — Shared Pokémon data module: `SPECIES_NAMES`, `GENDER_RATIO`, `gender_from_key_species()`, `EVO_FAMILY` (Gen I–IX evolution families including CFRU/RR extended IDs), `base_form()`.
- **`server/adapters/base.py`** — GameAdapter ABC: GameRulesAdapter (10 methods) + GamePresentationAdapter (9 methods). All game-specific server logic flows through adapter interfaces.
- **`server/adapters/gen3_frlge.py`** — Gen 3 adapter: GBA PID:OTID key format, FRLG+Emerald gift areas, Gen 1-3 species data, RR variant support.
- **`server/adapters/gen2_crystal.py`** — Gen 2 adapter: DV-based gender/shiny, 251 sequential species (NatDex 1-251), 17 types (Dark+Steel added), Crystal item names, PokeAPI sprites. Data from `data/games/gen2_crystal/`.
- **`server/adapters/gen4_hgsspt.py`** — Gen 4 adapter: PID:OTID key format, HGSS gift areas, Gen 1-4 species (NatDex 1-493).
- **`server/adapters/gen5_bw.py`** — Gen 5 adapter: PID:OTID key format, BW/BW2 gift areas, Gen 1-5 species (NatDex 1-649).
- **`server/adapters/__init__.py`** — Adapter registry: get_adapter(game_id) with backward-compat aliases.
- **`server/manager.py`** — Run Manager (port 8090): creates/starts/stops/archives named runs, each a `server.py` subprocess. Supports per-run lock rule configuration. Passes `--run-name` from run registry to spawned subprocess. Dynamic launcher script endpoints (`GET /api/runs/<id>/launcher/<player>`). Passes `--manager-port` when spawning subprocesses. Verbose Logging checkbox in New Run form; `--verbose` forwarded to spawned subprocess; badge shown on run card.

*Data:*
- **`data/links.json`** — Link table + area states + pokeballs_obtained flags + lock rules, written on every state change.
- **`data/obs_config.json`** — OBS WebSocket config (host, port, password per player, enabled flag, trigger rules list). Written by `OBSController.save_config()`. Not per-run — shared across all server instances. Passwords stored in plaintext locally; never returned in HTTP responses.
- **`data/games/gen3_frlge/rr_items.json`** — 746 RR item ID → name mappings (generated by `lua/tests/test_item_discovery.lua`). Loaded at server startup; used when `_is_rr` is True.
- **`tools/gen_area_map.py`** — Generates `data/games/gen3_frlge/gen3_frlge_areas.lua` and `data/games/gen3_frlge/gen3_frlge_locations.lua` from `data/games/gen3_frlge/area_map.json`.
- **`tools/gen_gen2_area_map.py`** — Generates `lua/gen2_crystal_areas.lua` and `lua/gen2_crystal_locations.lua` from `data/games/gen2_crystal/area_map.json`.
- **`tools/gen_gen5_area_map.py`** — Generates `data/games/gen5_bw/gen5_bw_areas.lua` and `data/games/gen5_bw/gen5_bw_locations.lua` from the Gen 5 BW/BW2 area maps.

*Tests:*
- **`lua/tests/test_*.lua`** — Standalone BizHawk test scripts (see `tests/TESTING.md`).
- **`lua/tests/test_bag_discovery.lua`** — Diagnostic script: scans SaveBlock1 for ball item IDs and tests encryption key candidates. Used to discover AP bag pocket offsets.
- **`lua/tests/test_sound_discovery.lua`** — Diagnostic script: scans ROM for gSongTable and reports SE song header addresses for the current ROM profile.
- **`lua/tests/test_ability_diag.lua`** — Diagnostic script: auto-detects ROM profile, validates gBaseStats address, shows party ability data per slot.
- **`lua/tests/test_item_discovery.lua`** — ROM scanner for RR/CFRU gItems table. Uses CFRU probe scoring (IDs 52-62) and itemId field validation to find the correct table. Outputs JSON to `rr_items.json`.
- **`tests/unit/test_state.py`** — 267 pytest unit tests for the state machine.
- **`tests/unit/test_gen1_adapter.py`** — 103 tests for the Gen 1 adapter.
- **`tests/unit/test_gen2_adapter.py`** — 179 tests for the Gen 2 adapter.
- **`tests/unit/test_gen3_adapter.py`** — 208 tests for the Gen 3 adapter.
- **`tests/unit/test_gen4_adapter.py`** — 100 tests for the Gen 4 adapter.
- **`tests/unit/test_gen5_adapter.py`** — 140 tests for the Gen 5 adapter.
- **`tests/unit/test_stat_stages.py`** — 46 tests for stat stage calculations.
- **`tests/unit/test_obs_priority.py`** — 4 tests for OBS priority-based trigger resolution (`submit_fired` — first-match-wins, per-player independence, area filter).
- **`tests/unit/test_phase1_comms.py`** — 6 TCP integration tests.
- **`tests/unit/test_profile_addresses.py`** — 3 tests verifying every Gen 1/2 profile address matches the pret decomp .sym output (CI gate after `tools/build_pret_syms.py`).

---

## Multi-Game Adapter Framework

The server uses a pluggable adapter pattern for game-specific behavior. All game-specific logic flows through adapter interfaces defined in `server/adapters/base.py`:

- **`GameRulesAdapter`** (10 methods) — key format parsing, gift area definitions, species/evo/gender/type data, mon key extraction from events.
- **`GamePresentationAdapter`** (9 methods) — sprite HTML generation, species names, ability names/descriptions, item names, area display names, trainer info, type names.

Each game family has its own adapter module:
- **`server/adapters/gen1_rby.py`** — Gen 1 (Red, Blue, Yellow)
- **`server/adapters/gen2_crystal.py`** — Gen 2 (Crystal)
- **`server/adapters/gen3_frlge.py`** — Gen 3 (FRLG, Emerald, Radical Red/CFRU)
- **`server/adapters/gen4_hgsspt.py`** — Gen 4 (HeartGold, SoulSilver, Platinum)
- **`server/adapters/gen5_bw.py`** — Gen 5 (Black, White, Black 2, White 2)

The state machine (`state.py`) calls adapter methods instead of hardcoded game logic. The adapter is selected based on the `game_id` field in the first `hello` event and persisted in `links.json`.

**Adding a new game:** Create an adapter in `server/adapters/`, a Lua game module in `lua/games/`, a Lua client in `lua/clients/`, and game data files in `data/games/`.

---

## Adapter Isolation Rules (CRITICAL — Prevents Cross-Gen Breakage)

### The Problem

`server.py` has **legacy Gen 3 coupling** that causes regressions when modifying shared code:
- 61+ uses of `self._is_rr` (Gen 3-specific state in shared server code)
- 4 standalone functions that duplicate adapter methods (`_item_name`, `_sprite_img_html`, `_type_badges_html`, `_area_display_name`)
- 6 Gen 3-specific JSON data files loaded at module level in server.py
- `_get_sprite_html()` has a hardcoded `game_id != "gen3_frlge"` check

### Rules for ALL Future Changes

1. **NEVER add `is_rr` parameters to new functions.** If logic depends on the game, it belongs in the adapter.

2. **NEVER add game-specific data to `server.py`.** Data files belong in `data/games/<gen>/` and are loaded by the adapter, not the server.

3. **NEVER import from `server.server` inside an adapter.** This creates circular dependencies. If an adapter needs shared data, embed it or load it independently (see gen4_hgsspt.py as the model adapter).

4. **ALWAYS use `self.adapter.<method>()` for display logic.** Never call standalone `_item_name()`, `_sprite_img_html()`, etc. — these are legacy functions that will be removed.

5. **NEVER special-case a `game_id` in server.py.** If behavior differs between games, add a method to the adapter base class and implement it per-game.

6. **Test ALL active games after ANY change to:**
   - `server/server.py` (shared HTTP/TCP server)
   - `server/state.py` (shared state machine)
   - `server/adapters/base.py` (adapter interface)
   - `server/pokemon_data.py` (shared species data)

### Model Adapter: gen4_hgsspt.py

The Gen 4 adapter is the **cleanest implementation** — use it as the template for new adapters:
- ✅ Zero circular dependencies
- ✅ All item names hardcoded in adapter (no lazy imports)
- ✅ All data loaded independently from `data/games/gen4_hgsspt/`
- ✅ No references to server.py internals

### Known Technical Debt (DO NOT Extend)

**server.py is now fully game-agnostic.** All game-specific data and logic routes through the adapter pattern. The only `pokemon_data` import remaining is `GENDER_SYMBOL` (a universal `{0: "♂", 1: "♀", 2: "—"}` mapping).

No legacy patterns remain.

### Completed Refactoring

| Item | What was done |
|---|---|
| ✅ `self._is_rr` property | **Eliminated entirely** — all 50+ calls replaced with `self.adapter.*()` |
| ✅ `_species_name_fn()` | Replaced with `self.adapter.species_name()` |
| ✅ `_gender_from_key_species()` | Replaced with `self.adapter.gender_from_key()` |
| ✅ `_ability_name()` | Replaced with `self.adapter.ability_name()` |
| ✅ `_ability_description()` | New adapter method; replaced all standalone calls |
| ✅ `_area_display_name()` | Deleted; replaced with `self.adapter.area_display_name()` |
| ✅ `_AREA_DISPLAY` / `_AREA_DISPLAY_RR_OVERRIDES` | Moved to gen3 adapter |
| ✅ `_type_badges_html()` | Accepts required `adapter=` param; dead fallback removed |
| ✅ `_sprite_img_html()` | Deleted (dead code since adapter handles sprites) |
| ✅ `_item_name()` / `ITEM_NAMES` | Deleted from server.py (adapter has own data) |
| ✅ `_RR_SPRITE_FILE` stub | Deleted |
| ✅ `_RR_TYPES` | Deleted (was dead code) |
| ✅ `RR_ITEM_NAMES` | Deleted (adapter loads its own) |
| ✅ Circular import | Removed `from server.server import ITEM_NAMES` |
| ✅ Gen3 sprite logic | Full funnotbun+fallback in `Gen3Adapter.sprite_html()` |
| ✅ `game_id` special-case | Removed from `_get_sprite_html()`; all games route through adapter |
| ✅ `GIFT_AREAS` / `_is_gift_area()` | Removed from state.py |
| ✅ Reset/rollback adapter sync | `self.adapter` re-synced after state replacement |
| ✅ Unused imports | Removed `species_types`, `TYPE_NAMES` + 7 dead imports |
| ✅ `_RR_TRAINERS` / `_RR_TRAINER_CLASS` | Moved to gen3 adapter with `trainer_info()` method |
| ✅ Trainer call site | Simplified to `self.adapter.trainer_info(tid)` |

---

## BizHawk Lua Communication

**No CLI flags required.** Load the appropriate launcher script in each BizHawk Lua Console:
- **Universal:** Load `lua/slink.lua` — auto-detects the ROM and loads the correct client. Uses default connection settings.
- **Gen 3 (GBA):** Load `lua/slink_gen3.lua` (or `lua/clients/gen3_frlge_client.lua` directly). Edit `SLINK_HOST`, `SLINK_PORT`, and `SLINK_PLAYER` at the top.
- **Gen 4 (NDS):** Load `lua/slink_gen4.lua` (or `lua/clients/gen4_hgsspt_client.lua` directly). Edit `SLINK_HOST`, `SLINK_PORT`, and `SLINK_PLAYER` at the top.
- **Gen 5 (NDS):** Load `lua/slink_gen5.lua` (or `lua/clients/gen5_bw_client.lua` directly). Edit `SLINK_HOST`, `SLINK_PORT`, and `SLINK_PLAYER` at the top.
- **Downloaded launcher:** Launcher files from the status page/manager prompt for the project root folder, cache it in `slink_path.cfg`, and auto-detect the game.

```lua
-- launcher script startup (excerpt)
SLINK_HOST   = "127.0.0.1"  -- IP of the machine running server/server.py
SLINK_PORT   = 54321
SLINK_PLAYER = "a"           -- "a" or "b"
```

**TCP transport (LuaSocket):**
- `lua/connector.lua` wraps LuaSocket with non-blocking send/receive.
- Requires `lua/x64/socket-windows-5-4.dll` — copy from your Archipelago installation.
- One persistent TCP connection per BizHawk instance. Reconnects automatically if dropped.

**Event format (Lua → Python):**
```json
{"event": "capture", "player": "a", "seq": 42,
 "key": "AABBCCDD:11223344", "level": 12, "area_id": "route_3"}
```

**Tick event (sent every 30 frames, ~0.5s):**
```json
{"event": "tick", "player": "a", "seq": 43, "ball_count": 5}
```

**Hello event (sent on connect/reconnect):**
```json
{"event": "hello", "player": "a", "seq": 1,
 "rom_type": "firered", "area_id": "route_1",
 "has_pokeballs": true, "ball_count": 10,
 "party": [{"key": "AABBCCDD:11223344", "hp": 45, "maxHP": 50, "level": 12}]}
```

**Response format (Python → Lua):**
```json
{"commands": [{"cmd": "force_faint", "key": "EEFF0011:22334455"}]}
```
A `noop` command means no action needed. The Lua client executes each command immediately in `dispatch_commands()`.

**Duplicate-event guard:** each client sends a monotonic `seq`. The server drops `seq ≤ last_seen_seq` (except when seq resets to 0/1 after a restart).

**Nuzlocke gate (Lua-side):** `nuzlocke_active` is only set to `true` once `M.hasPokeballs()` returns true (reads the actual bag pocket from RAM). Until then, `no_catch` events and `resolved_areas` bookkeeping are suppressed in Lua. The server has no corresponding gate — it trusts Lua not to send `no_catch` prematurely.

**Frame budget:** 60fps (GBA). Target Python round-trip < 50ms on localhost; < 100ms over LAN.

---

## Gen 1 (RBY) Memory Map

All multi-byte values are **big-endian**. Verified against [pret/pokered](https://github.com/pret/pokered) (`wram.asm`, `macros/ram.asm`).

### ROM identification

Read the ROM title from GB header at `0x0134` (16 bytes ASCII). Values: `POKEMON RED`, `POKEMON BLUE`, `POKEMON YELLOW`.

### Key Addresses (Red/Blue — Yellow is shifted -1 on most)

| Symbol | Red/Blue | Yellow | Description |
|--------|----------|--------|-------------|
| wPartyCount | 0xD163 | 0xD162 | Party size (0-6) |
| wPartySpecies | 0xD164 | 0xD163 | Species list (6 + 0xFF terminator) |
| wPartyMon1 | 0xD16B | 0xD16A | Party struct base (6 × 44 bytes) |
| wCurrentBoxCount | 0xDA80 | 0xDA7F | Active box mon count |
| wCurrentBoxMons | 0xDA96 | 0xDA95 | Active box struct base (20 × 33 bytes) |
| wIsInBattle | 0xD057 | 0xD056 | 0=overworld, 1=wild, 2=trainer |
| wEnemyMon | 0xCFE5 | 0xCFE4 | Active enemy battle struct |
| wCurMap | 0xD35E | 0xD35D | Current map ID (single byte) |
| wObtainedBadges | 0xD356 | 0xD355 | Badge bitfield (8 badges) |
| wPlayerID | 0xD359 | 0xD358 | 2-byte OT ID (big-endian) |

### Party struct (44 bytes)

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 1 | Internal species index |
| +0x01 | 2 | Current HP (BE) |
| +0x03 | 1 | Level (box level in box struct) |
| +0x0C | 2 | Original Trainer ID (BE) |
| +0x1B | 1 | Attack/Defense DVs |
| +0x1C | 1 | Speed/Special DVs |
| +0x21 | 1 | Level (party-calculated) |
| +0x22 | 2 | Max HP (BE) |

### Battle struct (wEnemyMon, 29 bytes active)

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 1 | Species |
| +0x01 | 2 | HP (BE) |
| +0x03 | 1 | PartyPos (which slot in trainer team is active) |
| +0x0E | 1 | Level |
| +0x0F | 2 | Max HP (BE) |

### Mon Key Format: `DDDD:TTTT:II`

- `DDDD` = 4 hex chars from 2 DV bytes (Attack/Def + Speed/Special)
- `TTTT` = 4 hex chars from 2-byte OT ID
- `II` = 2 hex chars from internal species index
- Evolution changes species → key changes → `key_change` event

### Gen 1 Limitations vs Gen 3/4

- No personality value (composite key from DVs:OTID:species)
- No abilities, no held items, no gender, no shinies
- No ASLR — fixed WRAM addresses
- No encryption — plaintext party/box data
- Only 1 box active in RAM at a time (12 boxes total, rest in SRAM)
- 151 species with non-sequential internal indices (INDEX_TO_NATDEX lookup required)
- Memorialize deposits to current active box (no dedicated memorial box number like Gen 3's Box 13)

---

## Gen 2 (Crystal) Memory Map

All multi-byte values are **big-endian**. Verified against [pret/pokecrystal](https://github.com/pret/pokecrystal) (`ram/wram.asm`, `macros/ram.asm`).

### ROM identification

Read the ROM title from GB header at `0x0134` (16 bytes ASCII). Value: `PM_CRYSTAL`. Additionally check GBC flag at `0x0143 == 0x80` (GBC-compatible).

### Key Addresses (Crystal)

| Symbol | Address | Description |
|--------|---------|-------------|
| wPartyCount | 0xDCD7 | Party size (0-6) |
| wPartySpecies | 0xDCD8 | Species list (6 + 0xFF terminator) |
| wPartyMon1 | 0xDCDF | Party struct base (6 × 48 bytes) |
| wMapGroup | 0xDCB5 | Current map group (needs verification) |
| wMapNumber | 0xDCB6 | Current map number (needs verification) |
| wBattleMode | 0xD22D | 0=overworld, 1=wild, 2=trainer (needs verification) |
| wPlayerID | 0xD47B | 2-byte OT ID (big-endian) |
| wCurrentBoxCount | — | Active box mon count (needs verification) |
| wCurrentBoxMons | — | Active box struct base (20 × 32 bytes, needs verification) |

### Party struct (48 bytes)

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 1 | Species |
| +0x01 | 1 | Held item |
| +0x02 | 1 | Move 1 |
| +0x06 | 2 | Original Trainer ID (BE) |
| +0x09 | 1 | Level (box level) |
| +0x15 | 1 | Attack/Defense DVs |
| +0x16 | 1 | Speed/Special DVs |
| +0x1F | 1 | Level (party-calculated) |
| +0x22 | 2 | Current HP (BE) |
| +0x24 | 2 | Max HP (BE) |

### Box struct (32 bytes)

Same as party struct through +0x16 (DVs), but no stats section (no HP/MaxHP/level in box). Level must be inferred from party data or cached.

### Mon Key Format: `DDDD:TTTT:SS`

- `DDDD` = 4 hex chars from 2 DV bytes (Attack/Def + Speed/Special)
- `TTTT` = 4 hex chars from 2-byte OT ID
- `SS` = 2 hex chars from species ID (NatDex, not internal index)
- Same format as Gen 1, but species is sequential NatDex (no INDEX_TO_NATDEX lookup)
- Evolution changes species → key changes → `key_change` event

### Gender (DV-based)

Gender is determined by `Attack DV` vs species-specific threshold from `GENDER_RATIO`:
- Attack DV >= threshold → male; Attack DV < threshold → female
- Genderless species (ratio 255) are exempt

### Shiny (DV-based)

A mon is shiny if: Defense DV = 10, Speed DV = 10, Special DV = 10, and Attack DV ∈ {2, 3, 6, 7, 10, 11, 14, 15}.

### Gen 2 Differences vs Gen 1

- 251 species with **sequential NatDex IDs** (species ID = NatDex number, no lookup table)
- Held items (Gen 1 has none)
- 2-byte map addressing: `mapGroup + mapNumber` (Gen 1 uses single `wCurMap`)
- 48-byte party struct / 32-byte box struct (Gen 1: 44/33)
- Gender and shiny determined by DVs
- 17 types (Dark + Steel added over Gen 1's 15)
- 14 boxes × 20 mons per box, only active box in WRAM (similar to Gen 1)
- No abilities, no ASLR, no encryption — plaintext data
- Apricorn balls (Level, Lure, Moon, Friend, Fast, Heavy, Love) for nuzlocke gate detection
- Memorial box support deferred (active box only in WRAM)

### Gift/static encounter area_ids

| area_id | Encounter |
|---------|-----------|
| `new_bark_town` | Starter Pokémon |
| `goldenrod_city` | Eevee (Bill), Odd Egg |
| `olivine_city` | Shuckie (Shuckle) |
| `dragons_den` | Dratini (elder gift) |
| `route_34` | Odd Egg (Day Care) |

### Known Limitations (Gen 2 Crystal)

- Some WRAM addresses (wMapGroup, wMapNumber, wBattleMode, box addresses) need BizHawk verification
- Box storage: only active box in WRAM; memorial box support deferred
- Crystal-only — Gold/Silver can be added later as variant profiles in `gen2_crystal.lua`

---

## FRLG Memory Map

All values are little-endian. Verified against [pret/pokefirered](https://github.com/pret/pokefirered) (`include/pokemon.h`, `src/load_save.c`, `include/pokemon_storage_system.h`).

### ROM identification (check at Lua startup)

Read the 4-byte ASCII game code from the GBA ROM header via the system bus — this is preserved by all major Pokémon randomizers (Universal Pokemon Randomizer, etc.) because randomizers only modify ROM data sections (encounter tables, trainer Pokémon, species stats), never the cartridge header.

```lua
-- GBA ROM header: game code at offset 0xAC from ROM start (0x08000000 on system bus)
local function readGameCode()
    local bytes = {}
    for i = 0, 3 do
        bytes[i+1] = string.char(memory.read_u8(0x080000AC + i, "System Bus"))
    end
    return table.concat(bytes)
end
-- Returns "BPRE" (FireRed) or "BPGE" (LeafGreen) for any vanilla or randomized US 1.0 ROM.
```

| Game                              | Game Code |
|-----------------------------------|-----------|
| FireRed US 1.0 and 1.1 (any randomization) | `BPRE` |
| LeafGreen US 1.0 and 1.1 (any randomization) | `BPGE` |

**Randomizer compatibility:** All RAM addresses in this document are determined by the game's compiled code (not ROM data) and are identical for vanilla and data-randomized FireRed/LeafGreen US 1.0 ROMs. Only engine-level hacks that recompile the game binary could move these addresses. After detecting the game code, `memory.lua` runs runtime sanity checks (`validateROM()`) — party count in 0–6 range, both IWRAM pointers in EWRAM range, mapGroup/mapNum within known bounds — before enabling any memory writes.

### Stable EWRAM globals (FireRed US 1.0)

**Vanilla addresses** (data-only randomizers use identical addresses):

| Symbol              | Address      | Type          | Notes |
|---------------------|--------------|---------------|-------|
| `gPlayerPartyCount` | `0x02024029` | u8            | Live count (0–6) |
| `gPlayerParty`      | `0x02024284` | Pokemon[6]    | 600 bytes (6 × 100) |
| `gEnemyPartyCount`  | `0x0202402A` | u8            | Wild/trainer enemy |
| `gEnemyParty`       | `0x0202402C` | Pokemon[6]    | Immediately follows gEnemyPartyCount |

**AP addresses** (EWRAM globals shifted +0x14):

| Symbol              | Address      | Type          | Notes |
|---------------------|--------------|---------------|-------|
| `gPlayerPartyCount` | `0x0202403D` | u8            | Live count (0–6) |
| `gPlayerParty`      | `0x02024298` | Pokemon[6]    | 600 bytes (6 × 100) |
| `gEnemyPartyCount`  | `0x0202403E` | u8            | Wild/trainer enemy |
| `gEnemyParty`       | `0x02024040` | Pokemon[6]    | Immediately follows gEnemyPartyCount |

These are **not** behind the SaveBlock ASLR — they are direct EWRAM globals.

### SaveBlock ASLR — map location, PC storage, and bag pockets

`gSaveBlock1Ptr` and `gPokemonStoragePtr` are re-randomized on each call to `SetSaveBlocksPointers()` (boot, load, and certain save events). Their targets shift 0–124 bytes (4-byte aligned) from the base EWRAM address of their respective structs. **Never hardcode the target address — always dereference the pointer.**

```lua
-- Read current mapGroup and mapNum via the pointer chain
-- Vanilla: SB1_PTR_ADDR = 0x03005008; AP: SB1_PTR_ADDR = 0x03004F58
local function getCurrentArea()
    local sb1 = memory.read_u32_le(M.SB1_PTR_ADDR)
    -- SaveBlock1.location is at struct offset +0x0004
    -- WarpData: mapGroup (u8 +0), mapNum (u8 +1)
    local mapGroup = memory.read_u8(sb1 + 0x0004)
    local mapNum   = memory.read_u8(sb1 + 0x0005)
    return mapGroup, mapNum
end
```

Likewise for PC storage writes:
```lua
-- Vanilla: PSP_PTR_ADDR = 0x03005010; AP: PSP_PTR_ADDR = 0x03004F60
local function getBoxMonAddr(boxIdx, slotIdx)  -- both 0-indexed
    local psp = memory.read_u32_le(PSP_PTR_ADDR)
    -- struct PokemonStorage: u8 currentBox (+0x0000), then boxes[14][30] of BoxPokemon (80 bytes each)
    return psp + 0x0001 + (boxIdx * 30 + slotIdx) * 80
end
```

**SaveBlock1 bag pocket offsets (pret/pokefirered `include/global.h`):**

Vanilla offsets shown; AP shifts all bag pockets by +0x0250 (592 bytes) due to expanded item tables (ITEMS_COUNT = 450 vs vanilla 375).

| Offset (vanilla) | Offset (AP) | Field | Size | Notes |
|--------|--------|-------|------|-------|
| `+0x0310` | `+0x0560` | `bagPocket_Items[42]` | 168 B | Normal items |
| `+0x03B8` | `+0x0608` | `bagPocket_KeyItems[30]` | 120 B | Key items |
| `+0x0430` | `+0x0680` | `bagPocket_PokeBalls[16]` | 64 B | **Pokéball pocket** |
| `+0x0464` | `+0x06B4` | `bagPocket_TMHM[58]` | 232 B | TMs/HMs |

Each `ItemSlot` is `{u16 itemId, u16 quantity}` (4 bytes). `itemId == 0` means empty.

```lua
-- Check if player has any Pokéballs (used for nuzlocke gate in client.lua)
-- M.SB1_BALL_POCKET_OFFSET and M.SB1_BALL_POCKET_COUNT are set by initProfile()
-- Vanilla: offset=0x0430, AP: offset=0x0680

function M.hasPokeballs()
    local sb1  = memory.read_u32_le(M.SB1_PTR_ADDR)
    local base = sb1 + M.SB1_BALL_POCKET_OFFSET
    for i = 0, M.SB1_BALL_POCKET_COUNT - 1 do
        local itemId = memory.read_u16_le(base + i * 4)
        local qty    = memory.read_u16_le(base + i * 4 + 2)
        if itemId ~= 0 and qty > 0 then return true end
    end
    return false
end

function M.countPokeballs()  -- returns total count across all 16 slots
    local sb1  = memory.read_u32_le(M.SB1_PTR_ADDR)
    local base = sb1 + M.SB1_BALL_POCKET_OFFSET
    -- AP encrypts quantities: actual = stored XOR (encryptionKey & 0xFFFF)
    -- encryptionKey read from SB2+0x0F2C (AP) or SB2+0x0F20 (vanilla)
    local total = 0
    for i = 0, M.SB1_BALL_POCKET_COUNT - 1 do
        local itemId = memory.read_u16_le(base + i * 4)
        if itemId ~= 0 then
            total = total + memory.read_u16_le(base + i * 4 + 2)
        end
    end
    return total
end
```

### `struct Pokemon` layout (100 bytes per slot)

From `include/pokemon.h`:

| Offset  | Size | Field             | Encrypted? |
|---------|------|-------------------|------------|
| `+0x00` | 4 B  | `personality`     | No |
| `+0x04` | 4 B  | `otId`            | No |
| `+0x08` | 10 B | `nickname`        | No |
| `+0x13` | 1 B  | misc flags (isBadEgg, hasSpecies, isEgg) | No |
| `+0x14` | 7 B  | `otName`          | No |
| `+0x1C` | 2 B  | `checksum`        | — |
| `+0x20` | 48 B | substructs (species, moves, EVs, IVs...) | **Yes** |
| `+0x50` | 4 B  | `status`          | No |
| `+0x54` | 1 B  | `level`           | No |
| `+0x56` | 2 B  | `hp` (current)    | No |
| `+0x58` | 2 B  | `maxHP`           | No |

**HP, status, and level are outside the encrypted region.** Read/write them directly. Never write inside `+0x20`–`+0x4F` without re-encrypting and recomputing the checksum — doing so creates Bad Eggs.

### Pokémon identity key

Use `personality .. ":" .. otId` as the stable identity string for a mon. This survives slot moves, box deposits, evolutions, and server reconnects. **Never use party slot index as identity.** Note: RR's Nature Changer NPC modifies personality (nature = personality % 25), which changes monKey — see Nature Change Detection below.

```lua
local function monKey(base)
    return memory.read_u32_le(base) .. ":" .. memory.read_u32_le(base + 4)
end
```

### Reading a party slot

```lua
local PARTY_BASE = 0x02024284
local MON_SIZE   = 0x64  -- 100 bytes

local function readPartySlot(slot)
    local base = PARTY_BASE + slot * MON_SIZE
    return {
        key     = monKey(base),             -- stable identity
        hp      = memory.read_u16_le(base + 0x56),
        maxHP   = memory.read_u16_le(base + 0x58),
        level   = memory.read_u8(base + 0x54),
        personality = memory.read_u32_le(base),
        otId        = memory.read_u32_le(base + 4),
    }
end
```

### Detecting a new capture

Captures go to the PC if the party is full — check both party and current box.

```lua
-- Poll every frame; diff against prev_known_keys (set of monKey strings)
local function detectNewMons(prev_known_keys)
    local found = {}
    local count = memory.read_u8(0x02024029)
    for slot = 0, count - 1 do
        local s = readPartySlot(slot)
        if s.maxHP > 0 and not prev_known_keys[s.key] then
            table.insert(found, s)
        end
    end
    -- For full-party captures: scan the active PC box for new keys
    return found
end
```

For full-party captures, `client.lua` snapshots the active box at battle start and diffs at battle end, disambiguating via `gBattleOutcome == CAUGHT` as a fallback.

### Decrypting species from substruct data

The 48-byte data section is split into four 12-byte substructs. Order is `personality % 24` (see [permutation table](https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_data_substructures_(Generation_III))). Substruct 0 contains `species` at offset `+0x00` (u16).

Decryption key = `personality XOR otId`. XOR each u32 of the 48-byte section.

### PC Storage layout

From `include/pokemon_storage_system.h`:
- 14 boxes × 30 slots per box = 420 slots total
- Each slot is a `BoxPokemon` (80 bytes)
- `struct PokemonStorage`: `u8 currentBox` at `+0x0000`, then `boxes[14][30]` at `+0x0001`
- **Memorial box**: internal index **13** (UI shows as "Box 14"). Reserve this box permanently. Auto-renamed to "THE DEAD" at startup by `client.lua`.

### Force-faint (battle-safe write)

```lua
local function forceFaint(partySlot)
    local base = PARTY_BASE + partySlot * MON_SIZE
    memory.write_u16_le(base + 0x56, 0)  -- set hp = 0
end
```

Do not zero the entire slot during battle. Deferred memorialization happens post-battle.

### Area Normalization

Raw `mapGroup:mapNum` maps to a canonical `area_id` via a lookup table in `data/games/gen3_frlge/gen3_frlge_areas.lua`. **184 entries** generated from `data/games/gen3_frlge/area_map.json` by `python tools/gen_area_map.py`. Key decisions:

- Multi-floor dungeons share one area_id (e.g., all Mt. Moon floors → `"mt_moon"`)
- Building interiors with wild encounters (Safari Zone areas) each get their own area_id
- Routes and towns with no wild encounters are not in the map (produce `area_id = ""`)
- Naval Rock (Lugia/Ho-Oh), Birth Island (Deoxys), and Sevault Canyon are included
- Legendary/static battles use `isWildBattle()` — non-trainer-flag battles are wild — so they use the area_id of their map like any other encounter

**Gift/static encounter area_ids** (Pokémon obtained here before Pokéballs are possible):

| area_id | Encounter |
|---------|-----------|
| `oaks_lab` | Starter Pokémon (vanilla) |
| `intro` | AP intro sequence area (mapGroup=0, mapNum=0) |
| `gift` | Fallback for gift Pokémon in unmapped areas (AP randomized start locations) |
| `cinnabar_lab` | Fossil revives |
| `celadon_hotel` | Eevee |
| `silph_co_7f` | Lapras |
| `saffron_dojo` | Hitmonlee / Hitmonchan |

Captures in these areas do NOT activate `pokeballs_obtained` on the server. Faints here (before the nuzlocke is active) are also ignored. The `gift` fallback is used when `area_id` is empty (unmapped location) and a new mon appears outside battle — this ensures AP starters link correctly regardless of randomized starting location.

---

## Server State Machine

The server (`server/state.py`) tracks per-area and per-mon state.

### Link table schema (`data/links.json`)

```json
{
  "links": [
    {
      "area_id": "route_1",
      "a": { "key": "12345678:87654321", "nickname": "PIDGEY", "species": 16 },
      "b": { "key": "11111111:22222222", "nickname": "RATTATA", "species": 19 },
      "status": "alive"
    }
  ],
  "area_states": {
    "route_1": "linked",
    "route_2": "pending_b"
  },
  "pokeballs_obtained": { "a": true, "b": false },
  "rom_type": "radical_red",
  "trainer_names": { "a": "RED", "b": "BLUE" }
}
```

`status` values: `"alive"` | `"dead"` | `"memorial"`

`area_states` values: `"unseen"` | `"pending_a"` | `"pending_b"` | `"pending_both"` | `"linked"` | `"dead_zone"`

`pending_a` = waiting for A; `pending_b` = waiting for B.

### How events are detected (Lua-side, frame diff)

`client.lua` diffs consecutive RAM reads every frame and sends events only on changes:

| Event | Detection condition |
|---|---|
| `area_enter` | `area_id` changes between frames (only when `nuzlocke_active` OR gift area) |
| `capture` | New monKey appears in party OR in current box after a `CAUGHT` battle outcome |
| `faint` | Known monKey HP drops from > 0 to 0 (detected via double-buffer party diff with per-buffer entry pools) |
| `no_catch` | Wild battle ends (15-frame grace), no new capture detected; suppressed if `!nuzlocke_active` |
| `whiteout` | All living party mons reach HP=0 simultaneously |
| `party_to_box` | Known monKey disappears from party outside of battle |
| `box_to_party` | Known monKey reappears in party from box |
| `tick` | Every 30 frames (~0.5 s) — flushes queued commands; includes `ball_count` |
| `key_change` | Nature Changer NPC modified personality — old_key → new_key migration (see Nature Change Detection) |

**`nuzlocke_active` gate (Lua-side only):** set to `true` when `M.hasPokeballs()` returns true (reads `SaveBlock1.bagPocket_PokeBalls` at profile-dependent offset: `+0x0430` vanilla, `+0x0680` AP). Until then, `no_catch` events and `resolved_areas` tracking are suppressed in Lua. The server does **not** duplicate this gate.

For **static/gift encounters** (Starter, Lapras, Eevee, fossils), a new monKey appears while `in_battle == false`. The Lua client labels these `capture(gift)` events; the server processes them identically to battle captures.

### Commands (Python → Lua via TCP response)

| Command | Lua action |
|---|---|
| `force_faint` | Find party slot with matching monKey; write HP=0 via `M.forceFaint(slot)` |
| `box_mon` | Deposit the named mon from party to the first available PC box slot |
| `party_mon` | Retrieve the named mon from a PC box to the first available party slot; writes stats from server cache |
| `memorialize` | Move dead mon from party/box to Box 13 ("THE DEAD"); deferred to safe state |
| `hud_show` | Display a text message on the BizHawk HUD overlay with custom RGB color and duration |
| `noop` | No action; returned when there is nothing to do |

### pokeballs_obtained tracking (server-side)

The server tracks `pokeballs_obtained` per player for:
1. **Faint gating**: Faints (and `hello` reconnect reconciliation) are ignored until `pokeballs_obtained[player_id] == True`.
2. **Status page display**: Shown as "Nuzlocke active" / "Waiting for Pokéballs".
3. **Persistence**: Saved in `data/links.json`.

Activation sources (in order of preference):
1. `hello` event with `has_pokeballs: true` — set directly from Lua's `M.hasPokeballs()`.
2. `hello` event with no `has_pokeballs` field and non-empty `party` — old-client heuristic.
3. `capture` event in a non-gift area — belt-and-suspenders.
4. Explicit `has_pokeballs: false` in `hello` — overrides the heuristic even with a non-empty party.

### Safe-state definition

**Vanilla:** `safe_state = True` when Python observes:
- `in_battle == False` (`gMain.inBattle` bit = 0, i.e. `(mem[0x03003529] & 0x02) == 0`)
- `in_overworld == True` (`gMain.state` at `0x03003528` is in a known overworld state)

`gMain` base address for vanilla FireRed US 1.0: `0x030030F0` (confirmed from pret/pokefirered symbols branch). `gMain.state = 0x030030F0 + 0x438 = 0x03003528`; `gMain.inBattle` flag byte `= 0x03003529` (bit 1, mask `0x02`).

**AP:** Uses a different detection model. `gMain` base is `0x03003040`.
- `isInOverworld()`: `gMain+0x038 == 1`
- `isInBattle()`: `gMain+0x038 != 1` AND `gBattleTypeFlags != 0` AND `gBattleOutcome == 0`

The three-condition battle check is required because in AP:
1. `gMain+0x038` alone cannot distinguish battle from menu/transitions (all are "not overworld")
2. `gBattleTypeFlags` remains stale (non-zero) after battle ends — it is NOT zeroed by AP's `FreeRestoreBattleData`
3. `gBattleOutcome` reliably distinguishes active battle (== 0, `B_OUTCOME_NONE`) from post-battle state (!= 0)

This correctly handles: active battles (true), party menus during battle (true — outcome still 0), party menus from start menu after battle (false — outcome set), and pre-battle states (false — type flags 0).

**CFRU / Radical Red:** Uses `gBattleOutcome`-based detection ("battle_outcome" mode). `gMain` is unreliable in CFRU.
- `isInBattle()`: `gBattleOutcome == 0` AND battle context active (gBattleMons[0].maxHP > 0)
- `isInOverworld()`: NOT `isInBattle()`
- Safe state additionally requires `post_battle_frames == 0` (30-frame cooldown + 90-frame grace period after battle end)

---

## HTTP Status Page

The server exposes a live status page at `http://localhost:8080/` (configurable via `--http-port`). Page title is dynamic: "Pokémon Soul Link Tracker — \<Game Variant\> — \<Run Name\>" (populated from persistent `rom_type` and `--run-name` CLI arg, with Pokéball SVG icon).

**Updates via Server-Sent Events (SSE).** The `/api/events` SSE endpoint pushes two named event types:
- `event: status` — full JSON status dict (consumed directly by stream overlays)
- `event: ping` — empty data (triggers fetch+morph on main status page)

SSE uses coalescing queues (maxsize=1, latest wins) to prevent backpressure. Heartbeat comments (`: heartbeat`) are sent every 15s to detect dead clients. The browser reconnects automatically (server sends `retry: 3000`). A fallback timer polls every 10s if SSE disconnects.

Endpoints:

| Endpoint | Description |
|---|---|
| `GET /` | HTML status page |
| `GET /memorial` | Memorial wall page — tombstone cards for dead pairs |
| `GET /obs` | OBS scene trigger configuration page |
| `GET /debug` | Debug console — manual link, event injection, state manipulation |
| `GET /stream` | Stream overlay index |
| `GET /stream/party-a` | Stream overlay — Player A party |
| `GET /stream/party-b` | Stream overlay — Player B party |
| `GET /stream/links` | Stream overlay — linked pairs |
| `GET /stream/deaths` | Stream overlay — death feed |
| `GET /stream/areas` | Stream overlay — area states |
| `GET /stream/events` | Stream overlay — recent events |
| `GET /launcher/{player}` | Download pre-configured launcher Lua script |
| `GET /api/status` | JSON status dump |
| `GET /api/events` | SSE stream — pushes `event: status` and `event: ping` on state changes |
| `POST /api/reset` | Wipe all state (links.json deleted, fresh run) |
| `POST /api/inject_link` | Manually create a link between two mons |
| `GET /api/debug/raw_state` | Raw links.json + live state |
| `GET /api/debug/manual_link_data` | Mon options + area data for manual link UI |
| `POST /api/debug/inject_event` | Inject synthetic event through state machine |
| `POST /api/debug/queue_command` | Queue a command for a player |
| `POST /api/debug/set_pokeballs` | Toggle pokeballs_obtained |
| `POST /api/debug/set_area_state` | Override area state |
| `POST /api/debug/clear_pending` | Clear pending captures |
| `POST /api/debug/unlink` | Remove an existing link by area_id |
| `GET /api/debug/backups` | List rolling backup slots with metadata |
| `POST /api/debug/rollback` | Restore state from a backup slot (saves pre-rollback as `links.pre_rollback.json` and `events.pre_rollback.json`) |
| `GET /api/obs/status` | OBS connection status + trigger rules (passwords redacted) |
| `POST /api/obs/config` | Save OBS config and hot-reload connections |
| `POST /api/obs/connect` | Connect one OBS player |
| `POST /api/obs/disconnect` | Disconnect one OBS player |
| `GET /api/obs/scenes/{player}` | List available scenes from a connected OBS instance |
| `POST /api/obs/test` | Test a scene switch for a player |

**Player cards** (side-by-side) show for each player:
- Connection status (online/offline badge)
- Nuzlocke status (active / waiting for Pokéballs)
- Current area (last `area_enter` or `hello` area_id)
- Pokéball count (from most recent `tick` or `hello`)
- Last event + timestamp
- Party table: key (8 chars), level, linked partner key, link status (fainted rows in red)

Below the cards:
- **Linked Pairs** table: area, A key + level, B key + level, status (alive=green, dead=red)
- **Area States** table: area name, human-readable state ("waiting for &lt;trainer name&gt;", "both entered", "linked", "dead zone") — the pending labels use the in-game trainer name received from each player's `hello` event, falling back to "A"/"B" if not yet known
- **Pending Captures** table: areas where only one player has captured

---

## Reconnect and Savestate Policy

- **Savestates and rewind are disabled during a live run.** Document this requirement in the setup instructions for players.
- On reconnect, the Lua client sends a `hello` event with the full current party snapshot and `has_pokeballs` flag. The server reconciles against persisted `links.json` using `personality+otId` keys to detect any deaths that occurred offline — but **only if `pokeballs_obtained` was already true** (faints before the nuzlocke started are not retroactively applied).
- Each event carries a monotonic `seq` integer. The server ignores events with `seq ≤ last_seen_seq[player]` to prevent duplicate processing after reconnect.

---

## Testing

### Unit tests — no emulator or server required

```bash
pytest tests/unit/ -v   # 1056 tests
pytest tests/unit/test_state.py -v          # 267 tests
pytest tests/unit/test_gen1_adapter.py -v   # 103 tests
pytest tests/unit/test_gen2_adapter.py -v   # 179 tests
pytest tests/unit/test_gen3_adapter.py -v   # 208 tests
pytest tests/unit/test_gen4_adapter.py -v   # 100 tests
pytest tests/unit/test_gen5_adapter.py -v   # 140 tests
pytest tests/unit/test_stat_stages.py -v    # 46 tests
pytest tests/unit/test_phase1_comms.py -v   # 6 tests
pytest tests/unit/test_obs_priority.py -v   # 4 tests
pytest tests/unit/test_profile_addresses.py -v  # 3 tests (pret address verification)
```

Feed event dicts directly to `SoulLinkState.handle_event()`. Use `monkeypatch` to redirect `LINKS_PATH` to `tmp_path`. Helper `make_state_with_link()` creates a pre-linked pair with `pokeballs_obtained = {"a": True, "b": True}`.

```python
from server.state import SoulLinkState, LinkEntry, MonInfo, LinkStatus

def test_faint_propagates(tmp_path, monkeypatch):
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = make_state_with_link()
    state.handle_event("a", {"event": "faint", "key": "A:1"})
    cmds = state.handle_event("b", {"event": "tick"})
    assert any(c["cmd"] == "force_faint" and c["key"] == "B:2" for c in cmds)
```

Test coverage includes: faint propagation, encounter linking, dead zones, whiteout, area state PENDING transitions, pokéball gate (Lua-trusted), pre-nuzlocke faint immunity, party sync (box_mon / party_mon), hello reconciliation, save/load roundtrip, illegal capture display preservation, species clause (evo families), gender clause (genderless edge cases), type clause (shared types, partial overlap, monotypes), combined clauses, violation recovery, clause rule persistence, same-save species duplicate prevention, dynamic gift areas, hello resolved_areas, gift area no_catch protection, unlinked encounter quarantine, paired party sync enforcement, dead zone quarantined mon retirement, CFRU/RR species data validation, player identity lock (OT ID per slot — first lock, wrong OT rejection, event blocking, persistence, empty party skip, per-player independence), persistent run metadata (rom_type, trainer_names), shiny bonus pairs (pending_bonus FIFO queue, pair formation, faint propagation both directions, party sync at formation, FIFO multi-bonus, lock clause violations with retry, area unresolve, persistence across save/load, key migration, no-wildcard-exemption), nature change (key_change migration of links, pending captures, party keys, mon stats, bonus keys, pending_bonus, and queued commands), dupes clause partner pending capture check, and charset encoding.

### Lua tests (manual, in BizHawk)

Run `lua/tests/test_1_memory.lua` through `lua/tests/test_5_soullink.lua` in order. See `tests/TESTING.md` for pass criteria and controls (F1–F7 keys) for each test script.

---

## Key Implementation Constraints

- **Mon identity**: Always use `personality .. ":" .. otId` (`monKey`) as the stable identifier. Never use party slot index — it changes when mons are rearranged.
- **Commands are queued, not pushed**: When player A's event triggers a command for player B, it is queued in `SoulLinkState.queued_commands["b"]` and delivered on B's next TCP message. This is why `tick` events are sent periodically.
- **State is fully serialized on every change**: `SoulLinkState._save()` writes `data/links.json` after every event that mutates state. No in-memory-only state should be load-bearing.
- **No writes during battle**: Never zero or copy party/box data while `gBattleOutcome` is unresolved. `force_faint` (HP=0 write) is battle-safe; full slot memorialization is deferred to `safe_state`.
- **Encrypted substruct writes**: Never write to `BoxPokemon +0x20`–`+0x4F` without re-encrypting (key = personality XOR otId) and recomputing the checksum. Bad Eggs result from invalid checksums.
- **Party compaction**: When zeroing a party slot, write 100 zero bytes, shift higher slots down, then decrement `gPlayerPartyCount` at `0x02024029`. The game does not compact automatically.
- **SaveBlock ASLR**: `gSaveBlock1Ptr` (0x03005008) and `gPokemonStoragePtr` (0x03005010) are re-randomized on each `SetSaveBlocksPointers()` call. Always dereference the pointer; never hardcode the target.
- **Nuzlocke gate is in Lua**: The server trusts that Lua will not send `no_catch` before `nuzlocke_active`. The server's only faint-related gate is `pokeballs_obtained` — faints arriving before that flag is true are silently ignored.
- **Randomizer compatibility**: All linking uses `personality+otId` and `area_id`, never species ID. RAM addresses are in compiled code, not ROM data — they are the same for vanilla and randomized US 1.0 ROMs.
- **AP struct shifts**: AP recompiles the binary, shifting EWRAM globals (+0x14), IWRAM pointers (−0xB0), bag pockets (+0x250), and the SB2 encryption key (+0x0C). All profile-dependent values are stored in the `PROFILES` table in `memory.lua` and applied at startup. Never hardcode vanilla addresses for use with AP ROMs.
- **AP battle detection**: In AP, `gBattleTypeFlags` and `gBattleMainFunc` both stay stale (non-zero) after battles end. Only `gBattleOutcome == 0` reliably indicates an active battle. The `isInBattle()` function uses a three-condition check for AP: `gMain+0x038 != 1 AND gBattleTypeFlags != 0 AND gBattleOutcome == 0`.
- **AP item quantity encryption**: Item IDs in bag pockets are NOT encrypted. Quantities are XOR'd with `encryptionKey & 0xFFFF` from `SB2+0x0F2C` (AP) or `SB2+0x0F20` (vanilla). The AP client.py reads `SB2+0x0F2A` as a "save loaded" check (non-zero test) — this is NOT the encryption key itself.
- **PSP_PTR_ADDR correction**: The confirmed IWRAM address for `gPokemonStoragePtr` is `0x03005010` (not `0x0300500C` as in some older references).
- **Borrowed-party battles (CFRU)**: Detected via two methods: (1) `M.isBorrowedBattle()` checks `gBattleTypeFlags & BATTLE_TYPE_BORROWED_MASK` (`0x1010000` = Poké Dude | Mock Battle); (2) rolling gift capture buffer freezes if 3+ gift captures within 45 frames (~0.75s). When triggered, client.lua freezes party tracking and restores the real party after battle. Tag battles (`INGAME_PARTNER = 0x400000`) are NOT borrowed — NPC mons use separate battler slots. `isBorrowedBattle()` returns false when `BATTLE_TYPE_ADDR` is unavailable (vanilla/AP safe).
- **Persistent run metadata**: `rom_type` and `trainer_names` in `SoulLinkState` are set-once — committed on first hello, never overwritten. Read by `_page_title()`, `_is_rr`, and `trainer_name` dict seeding.

---

## Link Clause Rules (Optional)

All clauses are **disabled by default** and enabled independently via CLI flags or the Run Manager UI.

### Species Clause (`--species-clause`)

Rejects a link if both mons belong to the same evolution family. Uses `base_form()` from `server/pokemon_data.py` which maps every Gen I–III species to its base-form ID via the `EVO_FAMILY` table. Example: Eevee (133) and Vaporeon (134) both map to base form 133 → **rejected**. Charmander (4) and Charmeleon (5) both map to base form 4 → **rejected**. Single-stage mons map to themselves.

### Gender Clause (`--gender-clause`)

Rejects a link if both mons are the same binary gender (♂+♂ or ♀+♀). Gender is derived server-side from `personality & 0xFF` vs the species' `GENDER_RATIO` threshold. **Genderless mons are exempt** — genderless + genderless or genderless + gendered never triggers a violation.

### Type Clause (`--type-clause`)

Rejects a link if both mons share **any** type. Uses `species_types()` from `server/pokemon_data.py` which resolves types via a three-tier lookup: RR-specific types (`data/games/gen3_frlge/rr_types.json`, 1328 entries) → CFRU alt-form types → NatDex fallback (Gen I–III, 386 species). Both monotypes and dual types are handled — the check computes the set intersection of each mon's types and rejects if non-empty. Example: Charizard (Fire/Flying) ↔ Pidgey (Normal/Flying) → **rejected** (shared Flying). Charmander (Fire) ↔ Squirtle (Water) → **allowed**.

### Violation Handling

When a violation is detected at link formation time:
1. The **second** capture (violating player) is force-fainted and queued for memorialize.
2. The **first** capture (partner) remains in `pending_captures` — the area stays in `PENDING_X` state.
3. SE_FAILURE (sound 26) plays for the violating player; SE_BOO (sound 22) for the partner.
4. A HUD message explains the violation (e.g., "Type clause: shared Fire — catch again!").
5. The violating player can retry with a different catch on the same route.

### Persistence

Lock rules are persisted in `links.json` under the `"rules"` key:
```json
{"rules": {"species_lock": true, "gender_lock": false, "type_lock": true}, "links": [...]}
```
CLI flags set the initial value; saved rules take precedence on reload to ensure mid-run restarts honor the original config.

### Key Files

| File | Role |
|---|---|
| `server/pokemon_data.py` | Shared module: `SPECIES_NAMES`, `GENDER_RATIO`, `gender_from_key_species()`, `EVO_FAMILY`, `base_form()`, `species_types()`, `type_name()`, `TYPE_NAMES` |
| `server/state.py` | `_check_link_violation()` — species, gender, and type checks; violation handling in `_handle_capture()` |
| `server/server.py` | `--species-clause` / `--gender-clause` / `--type-clause` CLI flags; clause rules badges on status page |
| `server/manager.py` | Per-run clause config: registry stores booleans, forwarded as CLI flags to spawned subprocess; UI checkboxes + badges |

---

## Player Identity Lock

Prevents wrong-save connections from corrupting run state. On the first `hello` with a non-empty party, the server locks the player slot's **OT ID** (from `monKey` → `otId`) and **trainer name**. Subsequent hellos with a different OT ID are rejected.

- **Rejection**: `hud_show` command (red, 600s duration) displays "⚠ Wrong save! Expected [name] (OT: ...)"; all further events return `noop` until a correct hello arrives
- **Status page**: Red error banner in the player card when identity mismatch is active
- **Persistence**: `player_identity` dict saved in `links.json` under `"player_identity"` key
- **Empty party**: Pre-game hellos (party count 0) are not checked and do not lock
- **Per-player**: Slots `a` and `b` are locked independently
- **Identity error field**: `identity_error` in JSON status API response

### Link table schema addition

```json
{
  "player_identity": {
    "a": {"ot_id": "87654321", "trainer_name": "RED"},
    "b": {"ot_id": "12345678", "trainer_name": "BLUE"}
  }
}
```

---

## Pokémon Ability Display

Abilities are shown on the status page for party mons, PC box mons, and enemy/wild mons. Hovering over an ability name shows a tooltip description. Descriptions are sourced from funnotbun's RR Dex (for RR/CFRU) with vanilla pret/pokefirered fallbacks for non-RR profiles. The `ability_description(id, is_rr)` function in `server/pokemon_data.py` handles the lookup. Generator script: `tools/gen_ability_descriptions.py`.

### Borrowed-Party Battle Protection (CFRU)

Radical Red has battles that replace the player's party (Poké Dude tutorial, mock/scripted battles). The Lua client uses two complementary detection methods:

**Method 1 — `M.isBorrowedBattle()`**: Checks `gBattleTypeFlags & BATTLE_TYPE_BORROWED_MASK` (`0x1010000` = Poké Dude | Mock Battle). When true, immediately freezes party tracking.

**Method 2 — Rolling gift capture buffer**: If 3+ gift captures appear within 45 frames (~0.75s), party tracking freezes. This catches RR scripted battles where the borrowed flag isn't set until after the party swap has already occurred. Key details:
- `all_known_keys` writes are deferred to buffer flush (not committed during freeze)
- `pre_freeze_keys` filtered by `all_known_keys` to exclude borrowed mons
- Timeout countdown paused during battle
- `battle_just_ended` is an explicit unfreeze trigger
- ALL party events (capture, faint, party_to_box, box_to_party) gated on `not party_frozen`

**Freeze/unfreeze lifecycle**:
- **At battle start**: If borrowed (either method), snapshot real `prev_party`, freeze `party_diff_ok = false`
- **During battle**: Tick events omit party data to prevent false mon tracking
- **At battle end**: Restore pre-borrowed party snapshot, discard battle HP cache, skip HP writeback
- **Tag battles** (`BATTLE_TYPE_INGAME_PARTNER = 0x400000`) are NOT frozen — NPC partners use separate battler slots

### Persistent Run Metadata (Set-Once)

`rom_type` (string) and `trainer_names` (dict) are committed to `SoulLinkState` on the first `hello` and never overwritten. Persisted in `links.json`. Used by:
- `_page_title()` for dynamic page titles ("Pokémon Soul Link Tracker — Radical Red — MyRun")
- `_is_rr` property for profile-dependent behavior
- `trainer_name` dict initialization on server start

### PC Box Level Resolution

`_resolve_level(link, side)` provides a multi-source fallback chain for level display:
1. `MonInfo.level` from the link entry (populated on capture)
2. `mon_stats` cache (populated from deposit events)
3. `party_details` from either player's most recent tick/hello

`_cache_mon_info()` permanently backfills `MonInfo.level=0` entries when a tick provides party data with level, then saves. It also backfills stale link entry nicknames from live party data (not just level=0 entries).

### How abilities are read (Lua → Server)

1. **Primary**: `memory.lua` decrypts species ID + ability bit from substruct data, looks up `gBaseStats[species].ability1/ability2`
2. **Fallback**: `_ability_cache` in `client.lua` — keyed by monKey, populated from `gBattleMons[battler].ability` (offset `+0x20`) during battle. Used when substruct decryption returns 0.
3. **Server**: `pokemon_data.py` `ability_name(ability_id, is_rr)` and `ability_description(ability_id, is_rr)` — 255-entry RR table + 165-entry vanilla table. Vanilla uses `_VANILLA_ABILITY_NAMES` and `_VANILLA_ABILITY_DESCRIPTIONS` (complete Gen III–V). RR descriptions from funnotbun's Radical Red Dex.

### gBaseStats addresses by profile

| Profile | Address | Notes |
|---|---|---|
| Vanilla | `0x08254784` | Hardcoded from pret/pokefirered |
| AP | `0x0825634C` | AP recompiles from source; shifted from vanilla |
| RR/CFRU | `ptr @ 0x080001BC` | Dynamic — CFRU stores function pointer, dereferenced at runtime |

---

## Nature Change Detection

RR's Nature Changer NPC modifies a mon's personality value (nature = personality % 25), which changes the monKey identity. The system detects and migrates this transparently.

**Lua-side detection** (`client.lua`): Before processing capture/faint diffs each frame, match disappeared keys against appeared keys using an `otId + species + level + nickname` signature. Strict 1:1 matching only — if multiple candidates share the same signature, no migration occurs. On match:
- Fresh `readPartySlot()` for the new key (ability changes with personality)
- Migrates all caches: `all_known_keys`, `_display_cache`, `_ability_cache`, `_mk_*` slot caches, and in-flight state (`captured_this_battle`, battle HP cache)
- Sends `key_change` event: `{"event": "key_change", "old_key": "...", "new_key": "...", "player": "a"}`

**Server-side handling** (`state.py`): `_handle_key_change()` migrates the old key to the new key across all state:
- `links` (MonInfo key field in LinkEntry)
- `_key_index` (fast key→link lookup)
- `pending_captures`
- `party_keys`
- `mon_stats`
- `bonus_keys`
- `pending_bonus` (shiny key references in the partner's queue)
- `pending_memorials`
- `queued_commands` (rewrites key field in pending force_faint/memorialize commands)

---

## Stream Overlay Sprites

Stream overlays (`/stream/links`, `/stream/party-a`, `/stream/party-b`) now use `sprite_html` from the JSON API response (with fallback to the old client-side `spriteTag()` function). The `sprite_html` field is also included in `party_details` in the `/api/status` response. Server-side `_sprite_img_html()` handles CFRU→NatDex species ID conversion for correct sprite URLs.

---

## Rolling Backups

A background asyncio task copies `links.json` **and `events.json`** every 5 minutes when both players are connected. 6 rolling backup slots with rotation (oldest slot overwritten). Backups are stored in a `backups/` subdirectory alongside `links.json`. Rollback is atomic — both files are restored together. Backup rollback is available via the debug page API:
- `GET /api/debug/backups` — list backup slots with timestamps and metadata
- `POST /api/debug/rollback` — restore state from a specific backup slot; pre-rollback state is saved as `links.pre_rollback.json` and `events.pre_rollback.json`. If no `events.backup.{slot}.json` exists for a slot (e.g. backups taken before this feature), the events ring buffer is cleared.

---

## Capture Stats Caching

Capture events now populate `mon_stats` directly. When processing a capture, the server reads `hp`, `maxHP`, and `level` from top-level event fields as a fallback when the nested `stats` dict is absent. This ensures PC box mons have stats available for `party_mon` commands even if the client sends a minimal capture event.

---

## Dupes Clause

The dupes clause prevents linking two mons from the same evolution family. The `_dupes_reroll()` helper method performs two checks:
1. **Check 1**: Whether the capturing player already has an alive link with the same base form
2. **Check 2**: Whether the **partner's pending capture** on the same area shares the same base form — this prevents a link that would immediately be a duplicate even before it's fully formed

If either check fails, the capture is treated as a violation (force-faint + retry).

---

## Shiny Bonus Pair

When a player catches a shiny Pokémon, their partner's **next encounter** becomes the shiny's Soul Link partner — forming a **bonus pair** outside the normal area-slot system.

### How it works

1. **Shiny caught by A** → shiny key added to `bonus_keys["a"]` (dedup guard), shiny key appended to `pending_bonus["b"]` (FIFO queue). Shiny remains in A's party as an unlinked mon while pending. A gets a shiny sound + GUI prompt; B is notified that a bonus encounter is pending.

2. **B's next non-shiny capture** → before normal area processing, `_handle_capture` peeks `pending_bonus["b"][0]`. Lock clauses (`_check_link_violation`) are applied. On success: queue is popped, shiny removed from `bonus_keys["a"]`, and a `LinkEntry` is created with synthetic `area_id = f"_bonus_{shiny_key[:8]}"`. `unresolve_area` is sent for B's normal area so that area slot is not consumed. Party sync is enforced at formation time (same four-combo logic as normal links).

3. **On violation** (species/gender/type clause): B's capture is force-fainted and queued for memorial, the `pending_bonus` queue is left intact so B can retry. A's shiny stays in `bonus_keys` during this window.

4. **FIFO multi-bonus**: Multiple shinies can queue up. Each of B's subsequent encounters pops one off the front of `pending_bonus["b"]`.

### State fields

- **`bonus_keys[player]`**: Set of shiny keys for `player`. Used for dedup (prevent replay on reconnect), exclusion from `_linked_party_size` (shiny doesn't count as a linked slot until the pair forms), and key_change migration. Cleared when the pair forms.
- **`pending_bonus[partner]`**: `deque[str]` of shiny keys waiting for a bonus catch from `partner`. Saved to `links.json` under `"pending_bonus"`. Loaded with `deque(saved.get("a", []))` so missing key defaults to empty.

### Bonus pair area_id

`f"_bonus_{shiny_key[:8]}"` — the leading underscore distinguishes these from real game areas. The `_area_display()` helper in `server.py` maps any `_bonus_*` area to `"✦ Bonus Pair"` for display. The Encounters table renders bonus pair rows with a gold `.bonus-pair-row` CSS class.

### Gen 1 exclusion

`Gen1Adapter.is_shiny()` always returns `False` — the shiny clause never fires and `pending_bonus` is never populated for Gen 1 runs.

### Upgrade compatibility (existing runs)

- **No shinies caught**: zero impact — `pending_bonus` defaults to empty deques on load.
- **Shiny in `bonus_keys` but partner hasn't caught bonus yet** (mid-pending on old code): `pending_bonus` is absent from the old JSON, so it defaults to `[]`. The bonus is silently dropped; the shiny stays as a permanent unlinked orphan. Use `/api/inject_link` on the debug page to form the pair manually.

---

## Enemy Battle Type Badges

The status page party tables now display enemy battle type badges (Wild, Trainer, etc.) alongside enemy mon data during active battles. Enemy held items are shown inline with the species name (e.g., "Pidgey @ Oran Berry"), matching player party display style. Items are read from `gEnemyParty` (vanilla/AP) or `gBattleMons` offset `+0x02` (CFRU/RR fallback).

---

## TCP Connector Optimization

`lua/connector.lua` uses fully non-blocking TCP connects to prevent BizHawk stutter when the server is down.

- **Non-blocking connect**: `settimeout(0)` — connect returns immediately with "timeout" or "Operation already in progress"
- **Pending connect detection**: Zero-byte send probe each frame — success = connected, "timeout" = still connecting, other = failed
- **Exponential backoff**: 120 frames (2s) → 240 → 480 → 960 → 1800 cap (30s); resets on successful connect or explicit disconnect
- **On loopback**: Non-blocking connect typically succeeds immediately when the server is running — zero added latency

---

## Lua Performance Optimizations

- **Localized BizHawk functions**: `memory.read_u8` → `mem_u8`, `memory.read_u16_le` → `mem_u16`, etc. — ~10-15% hot-loop speedup
- **`monKey` caching**: Per-slot personality/otId cache (`_mk_pers`, `_mk_otid`, `_mk_str`) — only recomputes `string.format` when values change
- **Display data cache** (`_display_cache`): Species, nickname, held item, ability cached per monKey — avoids redundant decryption across ticks
- **JSON encoder**: O(n) array detection (compare `#t` vs pair count), integer fast-path (avoids float formatting), pre-built escape map
- **Grace window box scan**: Skipped once `captured_this_battle` is set — avoids scanning 30 box slots every frame for remaining grace frames
- **Frame-cached state**: `in_battle` and `is_overworld` read once per frame, reused across all detection paths
- **Incremental box scan**: 2 boxes per tick (not all 13), cycling through all boxes over ~6.5 seconds

---

## Run Manager

`server/manager.py` provides multi-run orchestration on port 8090 (`python -m server.manager --host 0.0.0.0`). Creates/starts/stops/archives named runs, each a `server.py` subprocess with its own TCP port, HTTP port, and data directory. Features:
- Per-run clause rule configuration (species clause, gender clause, type clause)
- Dynamic launcher script downloads — generates `slink_<player>.lua` with correct host/port/player based on the HTTP Host header
- Links to each run's status page
- Passes `--manager-port` to spawned subprocesses for back-link navigation

---

## Memorial Wall

`/memorial` — a dedicated solemn page showing tombstone cards for each dead linked pair. Displays greyscale Pokémon sprites, nicknames, species, levels, area of death, cause of death, and killer details (if applicable). Updates live via SSE. Data sourced from the killfeed in `/api/status`. Sprites use server-side `_sprite_img_html()` for correct CFRU→NatDex species conversion. RR sprites from funnotbun have solid backgrounds — canvas-based transparent background processing removes them client-side. `a_sprite_html` and `b_sprite_html` fields are included in the killfeed JSON API.

---

## Debug Page

`/debug` — debug console for manual state manipulation during development and troubleshooting. All panels update live via SSE. Features a live status banner showing connection state, link/area counts, and queued commands. Panels:
- **Manual Link** — create links between mons, unlink existing links, or override existing links. Mon key and area ID fields use datalist autofill from live server data (fetches from `/api/debug/manual_link_data`)
- **Inject Event** — send synthetic events (capture, faint, area_enter, etc.) through the state machine
- **Queue Command** — manually queue commands (force_faint, box_mon, etc.) for a player
- **State Toggles** — toggle `pokeballs_obtained`, set area states directly
- **Danger Zone** — reset run, clear pending captures
- **Raw State** — view `links.json` + live server state
- **Backup Rollback** — view rolling backup slots with clickable slot table, restore any backup via `/api/debug/rollback`

---

## OBS Scene Trigger Integration

SLink can automatically switch OBS scenes in response to game events via `server/obs_controller.py`.

### Architecture

- **Library:** `simpleobsws>=1.4` — fully async obs-websocket v5 client. URL must be `ws://HOST:4455` (obs-websocket v5 port; do NOT use the v4 default 4444).
- **Per-player workers:** each player slot (`a`, `b`) has an `asyncio.Queue(maxsize=1)` and a dedicated `_worker()` coroutine. The worker is connected to a `_reconnect_loop()` that retries with exponential backoff (5 s → 60 s cap) whenever OBS disconnects.
- **Coalescing:** if OBS is slow, the queue only keeps the most-recent desired scene (drain + put). This prevents stale scene commands from stacking up.
- **Isolation:** all OBS I/O is in the worker tasks — failures never raise into the game server event loop.

### Config (`data/obs_config.json`)

```json
{
  "enabled": true,
  "connections": {
    "a": {"host": "127.0.0.1", "port": 4455, "password": "..."},
    "b": {"host": "",          "port": 4455, "password": ""}
  },
  "triggers": [
    {"id": "t1", "event": "battle_start_new", "player_filter": "any",
     "target": "own", "scene": "NEW ENCOUNTER", "area_id_filter": ""},
    {"id": "t2", "event": "wild_battle_start", "player_filter": "any",
     "target": "own", "scene": "WILD BATTLE",   "area_id_filter": ""},
    {"id": "t3", "event": "battle_start",      "player_filter": "any",
     "target": "own", "scene": "BATTLE",        "area_id_filter": ""}
  ]
}
```

Config is **global** (not per-run). Empty host (`""`) = disabled for that player. Passwords never returned in HTTP GET responses.

### Priority Resolution (`submit_fired`)

`_emit_obs_triggers()` in `server.py` collects all `(event_name, src_player, metadata)` tuples that fire during a single `_dispatch()` call and passes them to `obs.submit_fired(fired)` once at the end.

`submit_fired` iterates rules in list order. For each rule it scans the `fired` list for a match. When a match is found it records `winners[target_player] = scene` — only if that player hasn't already been claimed by a higher-priority rule. Once both players have a winner the loop exits early.

```
fired = [("battle_start", "a"), ("wild_battle_start", "a"), ("battle_start_new", "a")]
rules = [battle_start_new → "NEW ENCOUNTER", wild_battle_start → "WILD BATTLE", battle_start → "BATTLE"]
→ player a gets "NEW ENCOUNTER"  (first rule, first match)
```

### 18 Supported Trigger Events

`battle_start`, `wild_battle_start`, `trainer_battle_start`, `battle_end`, `battle_start_new` (open encounter slot), `area_enter` (with optional area_id filter), `area_enter_new` (open slot), `faint`, `link_death`, `whiteout`, `capture`, `shiny`, `linked`, `dead_zone`, `party_to_box`, `box_to_party`, `run_over`, `memorialize_done`.

### UI (`/obs`)

- Connection status badges per player, host/port/password fields, Save Config + Connect/Disconnect/Test buttons.
- Trigger rules table: drag ⠿ handle to reorder (HTML5 drag-and-drop, reorders `triggers[]` JS array in-place, re-renders priority badges #1/#2/…). Click 💾 Save Config to persist.
- Scene name `<datalist>` populated from connected OBS instance.

---

## Reference Sources

- [pret/pokered](https://github.com/pret/pokered) — authoritative Gen 1 Red/Blue decomp; `wram.asm`, `macros/ram.asm`, `data/pokemon/`
- [pret/pokeyellow](https://github.com/pret/pokeyellow) — authoritative Gen 1 Yellow decomp (shifted addresses)
- [pret/pokecrystal](https://github.com/pret/pokecrystal) — authoritative Gen 2 Crystal decomp; `ram/wram.asm`, `data/pokemon/`, `data/maps/`
- [Gen II Pokémon data structure](https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_data_structure_(Generation_II)) — 48-byte party / 32-byte box layout
- [Gen II Save Data Structure](https://bulbapedia.bulbagarden.net/wiki/Save_data_structure_(Generation_II)) — save layout, party/box addresses
- [Gen I Save Data Structure](https://bulbapedia.bulbagarden.net/wiki/Save_data_structure_(Generation_I)) — save layout, party/box addresses
- [Gen I RAM Map (Data Crystal)](https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Red_and_Blue/RAM_map) — verified WRAM addresses
- [Archipelago connector_bizhawk_generic.lua](https://github.com/ArchipelagoMW/Archipelago/blob/main/data/lua/connector_bizhawk_generic.lua) — LuaSocket TCP server protocol (source for `lua/connector.lua`)
- [Archipelago FRLG client.py](https://github.com/vyneras/Archipelago/blob/frlg-stable/worlds/pokemon_frlg/client.py) — FRLG memory read patterns (SaveBlock guard, overworld check, map coords)
- [pret/pokefirered](https://github.com/pret/pokefirered) — authoritative FRLG decomp; `include/pokemon.h`, `include/pokemon_storage_system.h`, `src/load_save.c`, `include/global.h` (bag offsets), `data/maps/`
- [BizHawk Lua Functions](https://tasvideos.org/BizHawk/LuaFunctions) — `comm.*`, `memory.*`, `emu.*`, `event.*` API reference
- [Gen III Pokémon data structure](https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_data_structure_(Generation_III)) — 100-byte layout, encryption
- [Gen III data substructures](https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_data_substructures_(Generation_III)) — permutation table for species decryption
- [Gen III save data structure](https://bulbapedia.bulbagarden.net/wiki/Save_data_structure_(Generation_III)) — save layout, checksum algorithm
- [Ironmon-Tracker](https://github.com/besteon/Ironmon-Tracker) — FRLG memory reference


