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
#   --explode-mode         (RR only) partner death → force_explode (coerced Explosion) instead of force_faint
#   --rival-team-swap      (RR only) rival battles → replace rival team with the partner's party (replace_rival_team)
#   --manager-port PORT  Manager HTTP port (enables back-link)
#   --verbose            Enable structured DEBUG logging to <data-dir>/slink.log

# Unit tests — no emulator or server required
# (14215 collected as of this writing and growing — the hand-maintained per-file sum that
#  used to live here drifted constantly; run the suite for the real number)
pytest tests/unit/test_state.py -v
pytest tests/unit/test_gen3_adapter.py -v
pytest tests/unit/test_gen4_adapter.py -v
pytest tests/unit/test_gen1_adapter_contract.py -v
pytest tests/unit/test_gen2_adapter.py -v
pytest tests/unit/test_gen5_adapter.py -v
pytest tests/unit/test_stat_stages.py -v
pytest tests/integration/test_phase1_comms.py -v
pytest tests/unit/test_obs_priority.py -v
pytest tests/unit/test_manager_launcher.py -v
# 0.2.6 — Rival Team Swap / Explode Mode / Upcoming Key Trainers:
pytest tests/unit/test_trainer_panel.py -v
pytest tests/unit/test_state_rival_battle_start.py -v
pytest tests/unit/test_state_party_blob_cache.py -v
pytest tests/unit/test_gen3_adapter_rival_ids.py -v
pytest tests/integration/test_cli_rival_team_swap.py -v
# Companion patch + per-run toggles:
pytest tests/integration/test_cli_native_toggles.py -v
pytest tests/integration/test_cli_overworld_presence.py -v
pytest tests/unit/test_patcher_routes.py -v

# Single test
pytest tests/unit/test_state.py::test_faint_queues_force_faint_for_partner -v

# Regenerate data/games/gen3_frlge/gen3_frlge_areas.lua from area_map.json (184 entries)
python tools/gen_area_map.py

# Regenerate data/games/gen2_<title>/area_map.json per title (388 Crystal, 368 Gold, 368 Silver)
python tools/gen_gen2_area_map.py

# Regenerate Gen 5 BW area maps and location tables
python tools/gen_gen5_area_map.py    # Gen 5 BW

# Regenerate the RR priority/key-trainer roster (Upcoming Key Trainers panel + calc setdex)
python tools/gen_rr_priority_trainers.py

# Lint (dev only: pip install -r requirements-dev.txt; config ruff.toml)
ruff check .
ruff check . --fix

# Syntax-check all Lua with lupa (Lua 5.5) — catches goto/bitwise errors luac 5.1 misreports
python tools/lua_syntax_check.py
```

## Project Overview

SLink automates a **Soul Link Nuzlocke** across two simultaneous Pokémon runs in [BizHawk](https://github.com/TASEmulators/BizHawk). Supported games include **Gen 1** (Red, Blue, Yellow), **Gen 2** (Crystal), **Gen 3** (FireRed, LeafGreen, Radical Red), **Gen 4** (HeartGold, SoulSilver, Platinum), and **Gen 5** (Black, White, Black 2, White 2). Each BizHawk instance runs a generation-specific Lua client (`lua/gen1/client.lua`, `lua/gen2/client.lua`, `lua/gen3/entry.lua` + `lua/gen3/run.lua`, `lua/clients/gen4_hgsspt_client.lua`, or `lua/clients/gen5_bw_client.lua`), which reads game state through its generation's read layer and sends JSON events (area_enter, capture, faint, etc.) over a persistent **TCP connection** to a central Python server. The server uses a pluggable adapter framework (`server/adapters/`) to handle game-specific logic while enforcing Soul Link rules — pairing encounters by area, propagating faints, mirroring party presence — and returns commands (e.g., `force_faint`) in the TCP response. **No BizHawk CLI flags are required.**

### Game Maturity

**Gen 1, Gen 2 and Gen 3 have live coverage; Gen 4 and 5 do not.** Gen 1 runs the original headless gates (`SLINK_LIVE=1 pytest tests/live/test_gen1_gates.py`, 11 cases) plus the rewritten client's own gates (`tests/live/test_gen1_new_gates.py`, 29 cases) and two-instance Soul Link scenarios across the Red/Blue and Yellow/Red pairings (`SLINK_E2E=1 pytest tests/e2e/test_duo_gen1_new.py`, 20 cases) — and, for the second Gen 1 foundation, `tests/e2e/test_duo_gen1_pure.py` (37 cases: PureRed↔PureBlue, PureRed↔PureGreen, and the companion-overlay pairing). The pre-rewrite `tests/e2e/test_duo_gen1.py` no longer exists. Gens 4 and 5 have Python unit tests and Lua clients but have never executed against a running game — treat them as experimental. When making changes to shared code (`server.py`, `state.py`, `adapters/base.py`), always verify Gen 3 isn't broken first, then run the other gen tests as a secondary check.

**Gen 2 is partially verified — mechanisms proven, no playthrough.** Inspect, frame-alignment and write-window gates run against real Crystal/Gold cartridges (`SLINK_LIVE=1 pytest tests/live/test_gen2_new_gates.py tests/live/test_gen2_frame_align.py tests/live/test_gen2_write_windows.py`), and two-instance link scenarios run against a real server (`SLINK_E2E=1 pytest tests/e2e/test_duo_gen2_new.py`) across the Crystal, Gold and Silver pairings. What has *never* happened on Gen 2 is unscripted play: no wild encounter, no area change, no ball thrown, so encounter linking, the dead zone and the species clause have no live Gen 2 evidence. Those three rules are enforced server-side and are generation-independent, and Gen 1's `playthrough` / `deadzone` / `dupes` scenarios cover them. Gen 2's blocker is the fixture: New Bark Town's west exit is script-locked until Elm hands over a starter, so the qualified fixtures can only park indoors and there is no grass fixture to walk.

Bringing Gen 1 to live coverage found four defects that the unit suite and the Lua syntax gate both passed: `pending_sync_cmds` declared *after* `dispatch_commands`, so every deferred `box_mon` / `party_mon` / `memorialize` bound to a nil global and killed the client on first use; a `party_to_box` debounce that could never reach its threshold, so party→box sync was silently dead (**this one was in Gen 2 as well**); a box level read from offset `+0x21`, which is past the end of the 33-byte Gen 1 box struct; and Archipelago detection probing HRAM at `0xFFDB` instead of the ROM. Static analysis cannot find any of these. If you add a generation, add gates.

Gen 2 was the better-looking of the two on paper — Gold/Silver profiles, gender ratios, item names, 179 adapter tests — and its first contact with a cartridge was worse. Gold, Silver and AP Crystal all routed to the **Gen 3** adapter; `party_blob_size()` inherited `0`, so every Gen 2 party blob was discarded; no profile declared `stats_offset`, so every box deposit dropped the stat block; the Apricorn ball IDs pointed at SUN_STONE, POLKADOT_BOW, UP_GRADE, BERRY, GOLD_BERRY and SQUIRTBOTTLE, which left the Nuzlocke gate shut for anyone carrying balls Kurt made; `retrieveBoxMon` read HP at the party offset off a **32-byte** box base, i.e. two bytes past the end of the slot, so the next boxed mon's move ids came back as an HP value; and the shared stat writer had one Special and aliased Sp.Atk onto Sp.Def. `pytest` was green throughout. Static data breadth is not maturity.

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

A "failed catch" is: left the area without capturing AND the battle/encounter ended. The `no_catch` gate lives in the client (the Gen 3 reducer sets its ball state from `reads:read_balls()`) — the server processes `no_catch` events as-received and always transitions to `DEAD_ZONE`.

### 4. Faint Linking (Two-Phase)
**Phase 1 — Battle-safe (immediate):** When HP drops to 0 for a linked mon, the server queues a `force_faint` command for the partner's game. The Gen 3 client builds the write plan from its profile-driven reads and submits it through the armed write sink; the server's own faint gate still ignores pre-Nuzlocke deaths.

**Nuzlocke gate**: Faints before `nuzlocke_active` is set (i.e., before the player has Pokéballs in their bag) are **ignored** by the server — the Soul Link death rule does not apply before the run begins. This protects starters that faint in the opening rival battle.

**Phase 2 — Memorialization (deferred):** Only once both games pass the client's pack-backed safe checkpoint (overworld, parked CPU/tasks, idle scripts/native work, and stable save pointers), move both mons to the memorial box (Box 13, internal index 13 / UI "Box 14"). Zero the source slot's BoxPokemon data after copying. Deferred commands remain queued until that checkpoint is acknowledged.

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
  lua/gen2/entry.lua + client.lua      lua/gen2/entry.lua + client.lua
  lua/gen2/reads.lua, writes.lua       lua/gen2/reads.lua, writes.lua

[BizHawk Instance A (Gen 3 GBA)]     [BizHawk Instance B (Gen 3 GBA)]
  lua/gen3/entry.lua + run.lua         lua/gen3/entry.lua + run.lua
  lua/gen3/{reads,signals,writes,safety,client,boxes,native}.lua
  data/games/{gen3_frlg,gen3_rr}/ + data/games/gen3_frlge/area_map.json

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
                   [server/adapters/]   ← gen2_gsc, gen3_frlge, gen4_hgsspt, gen5_bw
                   [data/links.json]    ← persisted link table + area states
                   [data/games/]        ← game-specific data per generation
                          |
                   [HTTP status page]  ← aiohttp on :8080  (browser only)
```

**Communication model — TCP, event-driven:**
- **Lua = TCP client** — The client script connects via LuaSocket (persistent connection) and sends newline-delimited JSON events whenever something changes (area, capture, faint). No polling.
- **Python = TCP server** — `server/server.py` uses `asyncio.start_server` on port 54321. One connection per BizHawk instance. Game-specific logic is delegated to adapters (`server/adapters/`).
- Commands flow back in the TCP response as a newline-delimited JSON object: `{"commands": [{"cmd": "force_faint", "key": "..."}]}`.
- Lua parses the response and dispatches each command through its client seam. Gen 3 routes mutations through `lua/gen3/writes.lua` and its pack-backed safety policy; legacy clients keep their generation-specific command paths.
- A **separate aiohttp HTTP server** on port 8080 serves the live status page — it is never touched by Lua.

```lua
-- client.lua: event sent whenever something changes
send_event({event="faint", player="a", seq=42, key="AABBCCDD:11223344", area_id="route_1"})
-- server returns on the same TCP connection:
-- {"commands":[{"cmd":"force_faint","key":"EEFF0011:22334455"}]}
-- client dispatches the command through its generation-specific write path
```

**Key files:**

### Directory Layout

```
SLink-RR/
├── lua/                         # BizHawk Lua scripts (loaded by emulator)
│   ├── slink.lua                # Universal entry point (auto-detects game)
│   ├── slink_gen3.lua           # Gen 3 launcher wrapper (dofiles slink.lua)
│   ├── slink_gen4.lua           # Gen 4 loader (loads gen4_hgsspt_client)
│   ├── slink_gen5.lua           # Gen 5 loader (loads gen5_bw_client)
│   ├── clients/                 # Legacy single-file production clients
│   │   ├── gen4_hgsspt_client.lua
│   │   └── gen5_bw_client.lua
│   ├── gen3/                    # Gen 3 composition root and production client
│   │   ├── entry.lua
│   │   ├── run.lua
│   │   ├── client.lua
│   │   ├── reads.lua
│   │   ├── signals.lua
│   │   ├── writes.lua
│   │   ├── safety.lua
│   │   ├── boxes.lua
│   │   └── native.lua           # Optional RR companion ABI
│   ├── gen1/                    # Gen 1 client (R/B/Y, + AP variants): entry.lua, client.lua,
│   │   └── ...                  # reads.lua, writes.lua, signals.lua, boxes.lua, rom.lua, panel.lua
│   ├── gen2/                    # Gen 2 client (Crystal/Gold/Silver): entry.lua, client.lua,
│   │   └── ...                  # reads.lua, writes.lua, boxes.lua, signals.lua, rom.lua, run.lua
│   ├── games/                   # Legacy Lua game modules
│   │   ├── gen4_hgsspt.lua
│   │   └── gen5_bw.lua          # Gen 5 game module
│   ├── memory_nds.lua           # NDS memory read/write helpers (Gen 4 & Gen 5)
│   ├── hud.lua                  # Shared HUD overlay module
│   ├── connector.lua            # LuaSocket TCP wrapper (non-blocking)
│   ├── game_detect.lua          # ROM header game detection
│   ├── socket.lua               # LuaSocket shim (loads DLL)
│   ├── tests/                   # BizHawk test scripts (run manually in emulator)
│   └── x64/                     # LuaSocket binary DLL
├── server/                      # Python server (TCP + HTTP)
│   ├── server.py                # Main TCP/HTTP server (asyncio + aiohttp)
│   ├── state.py                 # SoulLinkState FSM (game-agnostic)
│   ├── obs_controller.py        # OBS WebSocket controller (simpleobsws, per-player queues)
│   ├── pokemon_data.py          # Species names, evo families, types, abilities
│   ├── data/moves/             # Move names and properties (gen3_rr.py, gen3_vanilla.py)
│   ├── manager.py               # Run Manager (multi-run orchestration)
│   └── adapters/                # Per-game server adapters
│       ├── base.py              # Abstract base adapter
│       ├── gen1_rby.py          # Gen 1 adapter (Red/Blue/Yellow + Archipelago)
│       ├── gen1_purergb.py      # Gen 1 pureRGB adapter (PureRed/PureBlue/PureGreen)
│       ├── gen2_gsc.py          # Gen 2 adapter (Crystal/Gold/Silver)
│       ├── gen3_frlge.py        # Gen 3 adapter
│       ├── gen4_hgsspt.py       # Gen 4 adapter
│       └── gen5_bw.py           # Gen 5 adapter
├── data/                        # Runtime data (persisted state + game data)
│   ├── links.json               # Active run state (auto-generated, not committed)
│   ├── memorial.json            # Death log (auto-generated)
│   ├── runs/                    # Run Manager named runs (each has own links.json)
│   └── games/                   # Per-game static data
│       ├── gen3_frlge/          # Shared Gen 3 area map/locations and server-side inputs
│       ├── gen3_frlg/           # FireRed/LeafGreen profile, sites and checkpoint
│       ├── gen3_rr/             # Radical Red profile, sites and checkpoint
│       ├── gen4_hgsspt/         # HGSS/Pt area maps + gen4_hgsspt_areas.lua
│       ├── gen2_crystal/        # Crystal species, types, items, area maps
│       ├── gen2_gold/, gen2_silver/  # Same shape as gen2_crystal/, per title
│       ├── gen1_rby/            # Profile, area map, engine signals, trainers, species/moves/evolutions (pret-derived)
│       ├── gen1_purergb/        # pureRGB's own species/types/area map + trade-overlay variants (pinned build v2.7.6)
│       ├── gen2_gsc/            # calc_names.json only — per-title Gen 2 data still lives in gen2_crystal/gold/silver
│       └── gen5_bw/             # Gen 5 area maps and location data
├── tools/                       # Code generation scripts (run manually)
│   ├── gen_pokemon_data.py      # Generates pokemon_data.py tables
│   ├── gen_ability_names.py     # Generates ability name table
│   ├── gen_rr_types.py          # Generates RR type data
│   ├── gen_gen2_area_map.py     # Generates data/games/gen2_<title>/area_map.json
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
- **New rewritten client** → a generation-owned directory such as `lua/gen3/`; legacy single-file clients remain under `lua/clients/`
- **New game adapter (Lua)** → `lua/games/<gen>_<game>.lua`
- **New game adapter (Python)** → `server/adapters/<gen>_<game>.py`
- **New game static data** → `data/games/<gen>_<game>/`
- **New memory module** → `lua/memory_<platform>.lua` (shared across games on same hardware)
- **New area table** → `lua/<gen>_<game>_areas.lua`
- **New code generator** → `tools/`
- **Shared Lua modules** → `lua/` root (e.g., `hud.lua`, `connector.lua`)
- **Never** place game-specific files in the root or in another game's directory

*Gen 3 Lua (GBA — FireRed / LeafGreen / Radical Red):*
- **`lua/slink.lua`** — Routes an admitted GBA cartridge through `Entry.admit` before the legacy game detector; FireRed, LeafGreen, and Radical Red are admitted, while Emerald, Archipelago-FRLG, and unknown/header-only GBA builds are refused by name.
- **`lua/slink_gen3.lua`** — Thin launcher wrapper that configures `SLINK_HOST`, `SLINK_PORT`, and `SLINK_PLAYER`, then loads `slink.lua`; the admission and build graph stay in `lua/gen3/`.
- **`lua/gen3/entry.lua`** — Composition root. It defines the `gen3_frlg` and `gen3_rr` packs, literal pack-file paths, hash/anchor/header admission, and `Entry.build(deps)`; injected `io`/`ev` tables keep the production graph independent of BizHawk globals.
- **`lua/gen3/run.lua`** — BizHawk bootstrap. It supplies GBA memory/event adapters, the connector and HUD, calls `Entry.admit`, builds the production session, and drives guarded frame/exit callbacks.
- **`lua/gen3/reads.lua`** — Profile-driven record decoder for party, boxes, trainer, bag, map, and battle state. It dereferences the live SaveBlock pointers and uses injected read-only I/O; FRLG and Radical Red differ by pack data and record rules, not a title branch.
- **`lua/gen3/signals.lua`** — Converts pack `engine_signals.json` sites into `on_bus_exec` hooks, checks expected ROM bytes at load and fire, verifies callback identity, and bounds the signal queue.
- **`lua/gen3/writes.lua` + `lua/gen3/safety.lua`** — The sole write sink and fail-closed checkpoint policy. A reason-specific arm validates its range and pack predicates before bytes are written; `boxes.lua` uses the same sink.
- **`lua/gen3/boxes.lua`** — Profile-aware party/PC/memorial moves, including FRLG's relocated storage and Radical Red's compressed-box format, with optional native executor seams.
- **`lua/gen3/client.lua`** — Pack-neutral state machine over `lua/core`: hello gating, signal-to-event reduction, keyed/deferred commands, PC sync, battle writes, and HUD prompts. It receives `native` only for an admitted Radical Red companion artifact.
- **`lua/gen3/native.lua`** — Optional single-owner Radical Red companion mailbox part. It owns staging, publishes opcodes through the armed write sink, polls acknowledgements, and reads back native results; its addresses and opcodes come from `profile.native`.
- **`data/games/gen3_frlg/`, `data/games/gen3_rr/`, and `data/games/gen3_frlge/`** — Per-pack profiles, engine signals, checkpoints, and the shared FRLG/RR area map and locations.

*Gen 2 Lua (GBC — Crystal):*
- **`lua/gen2/entry.lua`** — Gen 2 composition root (Crystal/Gold/Silver): builds the candidate and
  production graphs the way `lua/gen1/entry.lua` does, over `lua/gen2/{client,reads,writes,boxes,
  signals,rom,run}.lua`. 2-byte map addressing (mapGroup+mapNumber), 48-byte party / 32-byte box
  structs, held item tracking, Apricorn ball detection for nuzlocke gate, sequential NatDex species
  (no index lookup needed), DV-based gender and shiny detection.

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
- **`lua/game_detect.lua`** — Shared ROM-header detection for the legacy Gen 2/4/5 clients; the Gen 3 route is admitted before this registry and does not delegate GBA admission to it.

*Server:*
- **`server/state.py`** — `SoulLinkState` FSM: processes event dicts, queues commands for each player, persists state. Includes `_check_link_violation()` for species/gender/type clause rules.
- **`server/server.py`** — asyncio TCP coordinator + aiohttp status page. Routes events to the FSM. Tracks per-player area, ball count, and party snapshots for the status page. Dynamic page titles via `_page_title()` method (shows "Pokémon Soul Link Tracker — \<variant\> — \<run name\>" with Pokéball SVG icon). `_resolve_level()` provides multi-source level fallback for manual links and PC box mons. Commits `rom_type` and `trainer_names` on first hello (set-once). Memorial wall page at `/memorial` (HTMX morph-swap refresh, tombstone cards with server-side `_sprite_img_html()` for correct CFRU→NatDex sprite conversion). Debug page at `/debug` (manual linking/unlinking, event injection, command queuing, state toggles, backup rollback, raw state — all panels live-updating via HTMX polling). OBS page at `/obs` (per-player connection management, draggable priority trigger rules). Launcher script download at `/launcher/{player}` (host from HTTP Host header). Accepts `--manager-port` CLI arg for Run Manager back-link. Accepts `--verbose` CLI flag: enables `_configure_logging()` which adds a `RotatingFileHandler` (10 MB × 5) to `<data_dir>/slink.log` with structured DEBUG tags for every accepted event, command flush, FSM transitions, party/faint/clause/reconcile/shiny lifecycle events, and adapter init. RR item names loaded from `data/games/gen3_frlge/rr_items.json`. TCP port displayed on status page. Rolling backups of `links.json` **and `events.json`** every 5 min when both players connected (6 slots with rotation; rollback restores both files atomically). `_cache_mon_info()` backfills stale link entry nicknames from live party data. Capture events populate `mon_stats` directly (fallback from top-level `hp`/`maxHP`/`level` fields). `sprite_html` field in party_details and killfeed JSON APIs. Enemy battle type badges and held items in status page.
- **`server/obs_controller.py`** — `OBSController`: per-player `simpleobsws` WebSocket connections (obs-websocket v5, port 4455), per-player coalescing `asyncio.Queue` + worker tasks, reconnect loop with exponential backoff (5 s → 60 s cap). `submit_fired(fired_list)` priority-resolves a list of `(event_name, src_player, metadata)` tuples in one pass — iterates rules in list order, first match per target player wins. Config persisted at `data/obs_config.json` (global, not per-run). Passwords never returned in GET responses.
- **`server/pokemon_data.py`** — Shared Pokémon data module: `SPECIES_NAMES`, `GENDER_RATIO`, `gender_from_key_species()`, `EVO_FAMILY` (Gen I–IX evolution families including CFRU/RR extended IDs), `base_form()`.
- **`server/adapters/base.py`** — GameAdapter ABC: GameRulesAdapter + GamePresentationAdapter. All game-specific server logic flows through adapter interfaces. 0.2.6 added `gift_link_area`, `rival_trainer_ids` (rules) and `trainers_for_area` / `trainer_party` / `trainer_brief` (presentation) as inert-default stubs.
- **`server/adapters/gen3_frlge.py`** — Gen 3 server adapter: GBA PID:OTID key format, FRLG/RR presentation data, and RR trainer/rival metadata. Legacy Emerald gift-area entries remain server-side compatibility data, but the current launcher admits only FireRed, LeafGreen, and Radical Red. RR overrides `rival_trainer_ids()` (27 "Terry" IDs), the Upcoming-Key-Trainers methods (`trainers_for_area` / `trainer_party` / `trainer_brief` / `milestone_cap_for_fight_label`) from `rr_priority_trainers.json`, and `gift_link_area`.
- **`server/adapters/gen2_gsc.py`** — `Gen2GSCAdapter`, Gen 2 adapter: DV-based gender/shiny, 251 sequential species (NatDex 1-251), 17 types (Dark+Steel added), per-title item names, PokeAPI sprites. Data from `data/games/gen2_<title>/` (Crystal, Gold, Silver).
- **`server/adapters/gen4_hgsspt.py`** — Gen 4 adapter: PID:OTID key format, HGSS gift areas, Gen 1-4 species (NatDex 1-493).
- **`server/adapters/gen5_bw.py`** — Gen 5 adapter: PID:OTID key format, BW/BW2 gift areas, Gen 1-5 species (NatDex 1-649).
- **`server/adapters/__init__.py`** — Adapter registry: get_adapter(game_id) with backward-compat aliases.
- **`server/manager.py`** — Run Manager (port 8090): creates/starts/stops/archives named runs, each a `server.py` subprocess. Supports per-run lock rule configuration. Passes `--run-name` from run registry to spawned subprocess. Dynamic launcher script endpoints (`GET /api/runs/<id>/launcher/<player>`). Passes `--manager-port` when spawning subprocesses. Verbose Logging checkbox in New Run form; `--verbose` forwarded to spawned subprocess; badge shown on run card. Per-run augmentations (`--explode-mode`, `--rival-team-swap`) persisted in the run registry and forwarded on launch. The Manager is the UI: `/runs/{id}` shows a run's board (live, or persisted once stopped) on the Manager's own origin; `/new` is the run creator (game family first, options greyed with reasons from `OPTION_SUPPORT`); `/broadcast`, `/tools`, `/runs/{id}/randomizer`. Run options live in one table, `RUN_FLAGS`. The randomizer's cartridges come from `GET /api/roms` (`ROM_DIRS`: the repo, `roms/`, `patch/build/`, `.cache/purergb*`; each described by `upr_pipeline.describe_rom` with its family) or `POST /api/roms` (the browser's file dialog, streamed into `roms/`); `GAME_FAMILY` maps a Gen 1 game key to its randomizer family and `handle_randomize` refuses a pair from the other family. Randomizer presets are named specs in `data/runs/presets.json` (`/api/presets`); the settings interchange file is UPR's `.rnqs` (`/api/randomizer/settings/{export,import}`, admitted by `upr_pipeline.admit_settings` — the same gates `prepare_pair` uses). A Gen 1 run's cartridges are made by `server/cartridges.py::provision` (`POST /api/runs/{id}/cartridges`; the older `/randomize` implies randomizing): vanilla randomize→structural inject, pureRGB overlay→randomize, contract with the final sha1, no contract when not randomized; the run records `cartridges` (and `randomizer`), downloads read `cartridges.players[p].output`. Area ids nothing names fall back to `adapters.base.humanize_area_id` ("route8" → "Route 8"). See `docs/ui_migration_plan.md`.

*Data:*
- **`data/links.json`** — Link table + area states + pokeballs_obtained flags + lock rules (species/gender/type + `explode_mode`), written on every state change. (`rival_team_swap` is supplied per-launch from the Manager run registry, not persisted here.)
- **`data/obs_config.json`** — OBS WebSocket config (host, port, password per player, enabled flag, trigger rules list). Written by `OBSController.save_config()`. Not per-run — shared across all server instances. Passwords stored in plaintext locally; never returned in HTTP responses.
- **`data/games/gen3_frlge/rr_items.json`** — 746 RR item ID → name mappings (generated by `lua/tests/test_item_discovery.lua`). Loaded at server startup; used when `_is_rr` is True.
- **`tools/gen_area_map.py`** — Generates `data/games/gen3_frlge/gen3_frlge_areas.lua` and `data/games/gen3_frlge/gen3_frlge_locations.lua` from `data/games/gen3_frlge/area_map.json`.
- **`tools/gen_gen2_area_map.py`** — Generates each title's `data/games/gen2_<title>/area_map.json` (388 Crystal, 368 Gold, 368 Silver). It writes the JSON pack only; there is no generated `*_areas.lua` for Gen 2.
- **`tools/gen_gen5_area_map.py`** — Generates `data/games/gen5_bw/gen5_bw_areas.lua` and `data/games/gen5_bw/gen5_bw_locations.lua` from the Gen 5 BW/BW2 area maps.

*Tests:*
- **`lua/tests/test_*.lua`** — Standalone BizHawk test scripts (see `tests/TESTING.md`).
- **`lua/tests/test_bag_discovery.lua`** — Diagnostic script: scans SaveBlock1 for ball item IDs and tests encryption key candidates. Used to discover AP bag pocket offsets.
- **`lua/tests/test_sound_discovery.lua`** — Diagnostic script: scans ROM for gSongTable and reports SE song header addresses for the current ROM profile.
- **`lua/tests/test_ability_diag.lua`** — Diagnostic script: auto-detects ROM profile, validates gBaseStats address, shows party ability data per slot.
- **`lua/tests/test_item_discovery.lua`** — ROM scanner for RR/CFRU gItems table. Uses CFRU probe scoring (IDs 52-62) and itemId field validation to find the correct table. Outputs JSON to `rr_items.json`.
- **`tests/unit/test_state.py`** — 318 pytest unit tests for the state machine.
- **`tests/unit/test_gen1_adapter_contract.py`** — 10 tests checking the Gen 1 adapter against pret source directly, independently of the shipped JSON data (supersedes the old `test_gen1_adapter.py`, which no longer exists). Live coverage lives in `tests/live/test_gen1_gates.py` (11 cases, the original gates) and `tests/live/test_gen1_new_gates.py` (29 cases, the rewritten client), plus `tests/e2e/test_duo_gen1_new.py` (20 cases, Red/Blue and Yellow/Red pairings) and `tests/e2e/test_duo_gen1_pure.py` (37 cases, the pureRGB pairings). The pre-rewrite `tests/e2e/test_duo_gen1.py` no longer exists.
- **`tests/unit/test_gen2_adapter.py`** — 59 tests for `Gen2GSCAdapter`. Live coverage lives in `tests/live/test_gen2_new_gates.py` / `test_gen2_frame_align.py` / `test_gen2_write_windows.py` (inspect, frame-align, write windows; Crystal + Gold, Silver shares Gold's receipt) and `tests/e2e/test_duo_gen2_new.py` (two-instance link scenarios, one real server).
- **`tests/unit/test_gen3_adapter.py`** — 218 tests for the Gen 3 adapter.
- **`tests/unit/test_gen4_adapter.py`** — 101 tests for the Gen 4 adapter.
- **`tests/unit/test_gen5_adapter.py`** — 140 tests for the Gen 5 adapter.
- **`tests/unit/test_stat_stages.py`** — 48 tests for stat stage calculations.
- **`tests/unit/test_obs_priority.py`** — 7 tests for OBS priority-based trigger resolution (`submit_fired` — first-match-wins, per-player independence, exact area + area-group filters).
- **`tests/integration/test_phase1_comms.py`** — 6 TCP integration tests.
- **`tests/unit/test_trainer_panel.py`** — 14 tests for the Upcoming Key Trainers panel (`trainers_for_area` / `trainer_party` / `trainer_brief`, base no-op defaults).
- **`tests/unit/test_state_rival_battle_start.py`** — 34 tests for the Rival Team Swap auto-trigger (adapter gate, toggle matrix, `queue_rival_team_swap`, `rival_team_replaced` ack).
- **`tests/unit/test_state_party_blob_cache.py`** — 10 tests for the `blob_hex` party-blob cache (ingest, length/hex validation, per-player isolation).
- **`tests/unit/test_gen3_adapter_rival_ids.py`** — 8 tests for `rival_trainer_ids()` (set size 27, known-ID anchors, vanilla empty, mutation safety).
- **`tests/integration/test_cli_rival_team_swap.py`** — 4 tests for the `--rival-team-swap` CLI flag (help, store_true, default false, explicit true).
- **`tests/integration/test_cli_native_toggles.py`** — 9 tests for the companion-patch per-run toggles (`--native-messages`, `--native-sounds`, `--no-battle-calc`, `--no-pc-trade-npc`).
- **`tests/integration/test_cli_overworld_presence.py`** — 4 tests for the `--overworld-presence` CLI flag.
- **`tests/unit/test_patcher_routes.py`** — the `/patcher` page + a `/companion/{name}` route per target. `server/patcher.py` holds a TARGETS registry (Radical Red, Pokemon Red, Pokemon Blue), because a UPS embeds the CRC32 of the exact dump it was diffed against and one shared file would refuse every user but one. Includes a real apply path: each shipped patch reproduces its recorded md5, the result carries the `SLNK` beacon, and applying Red's patch to a Blue dump raises. Asserts NO Yellow artifact is shipped — Yellow has no free WRAM for the mailbox, so no build exists.

---

## Multi-Game Adapter Framework

The server uses a pluggable adapter pattern for game-specific behavior. All game-specific logic flows through adapter interfaces defined in `server/adapters/base.py`:

- **`GameRulesAdapter`** — key format parsing, gift/egg area policy (incl. `gift_link_area` → `gift_<area>` namespace), species/evo/gender/type data, mon-key extraction from events, and `rival_trainer_ids()` (Rival Team Swap gate).
- **`GamePresentationAdapter`** — sprite HTML generation, species/ability/item/move/area names, trainer info, type names, and the Upcoming-Key-Trainers methods (`trainers_for_area` / `trainer_party` / `trainer_brief`).

Each game family has its own adapter module:
- **`server/adapters/gen1_rby.py`** — Gen 1 (Red, Blue, Yellow, + Archipelago Red/Blue)
- **`server/adapters/gen1_purergb.py`** — Gen 1 pureRGB (PureRed, PureBlue, PureGreen — a second Gen 1 foundation, not a vanilla variant)
- **`server/adapters/gen2_gsc.py`** — Gen 2 (Crystal, Gold, Silver)
- **`server/adapters/gen3_frlge.py`** — Gen 3 server adapter: GBA PID:OTID key format, FRLG/RR presentation data, and RR trainer/rival metadata. The Lua launcher admits FireRed, LeafGreen, and Radical Red only; Emerald and Archipelago-FRLG are refused before the adapter is used.
- **`server/adapters/gen4_hgsspt.py`** — Gen 4 (HeartGold, SoulSilver, Platinum)
- **`server/adapters/gen5_bw.py`** — Gen 5 (Black, White, Black 2, White 2)

The state machine (`state.py`) calls adapter methods instead of hardcoded game logic. The adapter is selected based on the `game_id` field in the first `hello` event and persisted in `links.json`.

**Adding a new game:** Create a server adapter in `server/adapters/` and its static data under `data/games/`. A rewritten client uses a generation-owned composition root (as Gen 3 does under `lua/gen3/`); legacy single-file clients use `lua/clients/` and their existing `lua/games/` module.

---

## Adapter Isolation Rules (CRITICAL — Prevents Cross-Gen Breakage)

### The Problem

`server.py` **used to** carry Gen 3 coupling that caused regressions when modifying shared code — all since eliminated (see [Completed Refactoring](#completed-refactoring)). The rules below exist to keep it from creeping back. The original offenders were:
- 61+ uses of `self._is_rr` (Gen 3-specific state in shared server code)
- 4 standalone functions that duplicated adapter methods (`_item_name`, `_sprite_img_html`, `_type_badges_html`, `_area_display_name`)
- 6 Gen 3-specific JSON data files loaded at module level in server.py
- `_get_sprite_html()` with a hardcoded `game_id != "gen3_frlge"` check

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

**server.py is now fully game-agnostic.** All game-specific data and logic routes through the adapter pattern — `server.py` imports nothing from `pokemon_data` at all. `GENDER_SYMBOL` still lives there (`server/pokemon_data.py:353`), keyed by name rather than index — `{"male": "♂", "female": "♀", "genderless": ""}` — and is imported by the Gen 3/4/5 adapters, not by the server.

Remaining back-compat shims (leave them, don't extend them): the `"frlg"` rom_type alias in `adapters/__init__.py`, the accepted-but-ignored `is_rr` parameter on three `pokemon_data.py` functions, and the legacy theme-name aliases in `templating.py`.

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
| ✅ 0.2.6 ruff lint | `ruff.toml` (E/F/W/I/UP/B/C4/SIM, ignore E501) + `requirements-dev.txt` pinning ruff 0.15.15 |
| ✅ 0.2.6 sprite URL dedup | `_funnotbun_url` / `_pokeapi_url` / `_frlg_url` helpers; named `_MAX_NATDEX` (1025) / `_GEN3_DEX_CAP` (386) / `_SPECIES_EGG` |
| ✅ 0.2.6 gift namespace | `gift_link_area()` → `gift_<area>` standalone-pair namespace (rules adapter, no `game_id` branch) |
| ✅ 0.2.6 Rival Team Swap / Explode Mode | `rival_trainer_ids()` adapter gate + `partner_blobs` cache; `force_explode` / `replace_rival_team` route through the adapter |
| ✅ 0.2.6 Upcoming Key Trainers | `trainers_for_area` / `trainer_party` / `trainer_brief` adapter methods feed `_trainer_panel_html`; `milestone_cap_for_fight_label` called via `hasattr` guard |

---

## BizHawk Lua Communication

**No CLI flags required.** Load the appropriate launcher script in each BizHawk Lua Console:
- **Universal:** Load `lua/slink.lua` — auto-detects the ROM and loads the correct client. Uses default connection settings.
- **Gen 3 (GBA):** Load `lua/slink_gen3.lua` (or `lua/slink.lua`); the launcher admits FireRed, LeafGreen, or Radical Red and then loads `lua/gen3/run.lua`. Edit `SLINK_HOST`, `SLINK_PORT`, and `SLINK_PLAYER` at the top.
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

**Duplicate-event guard:** each client sends a monotonic `seq`. The server drops `seq ≤ last_seen_seq` **on the same TCP connection** — `last_seq` is a local of `handle_client` (`server/server.py:1095-1101`, guard at `:1243-1254`), so it is born and dies with the socket and a reconnecting client counting from 1 again is never read as a duplicate. A connection is also ignored until it says `hello`: any other event on a connection with no accepted hello is answered `noop` (`:1230-1241`). The old "except when seq resets to 0/1 after a restart" rule was a `seq <= 1 and last > 10` heuristic; it was **retired 2026-09-17 (`0629736`)** after it dropped a real reconnect's hello, and the harness constraint it implied (never reuse a server across client restarts) no longer exists.

**Nuzlocke gate (Lua-side):** The Gen 3 client latches its ball state when `reads:read_balls()` reports a positive count; until then, `no_catch` events and `resolved_areas` bookkeeping are suppressed. The server has no corresponding gate — it trusts the client not to send `no_catch` prematurely.

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
- Memorialize deposits to a dedicated memorial box: **Box 12**, via `M.depositMemorialMon`
  (falls back to `depositPartyMon` if Box 12 is full). This previously read "current active
  box, no dedicated memorial box" — that contradicted the code, `data/games/gen1_rby/README.md`
  and `server/adapters/gen1_rby.py`, all three of which agree on Box 12.

### What Gen 1 gets for free that Gen 3 needed a ROM patch for

Gen 3 needed the native companion patch for Rival Team Swap because `gEnemyParty` is
encrypted and checksummed. **Gen 1 has neither**, so both RR-style augmentations are plain
RAM writes and work on unmodified cartridges.

**Rival Team Swap** — one contiguous ~404-byte write, Red/Blue (Yellow is −1 except where
noted):

| Region | Red/Blue | Size |
|--------|----------|------|
| wEnemyPartyCount | 0xD89C | 1 |
| wEnemyPartySpecies | 0xD89D | 6 + 0xFF terminator |
| wEnemyMons | 0xD8A4 | 6 × 44 |
| wEnemyMonOT | 0xD9AC | 6 × 11 |
| wEnemyMonNicks | 0xD9EE | 6 × 11 |

The OT names and nicknames live in **parallel arrays**, not inside the mon struct — which is
why `party_blob_size()` returns **66** for Gen 1 (44 + 11 + 11 assembled by
`M.readPartyBlob`) rather than the struct size. Rival detection is `wIsInBattle == 2` and
`wTrainerClass` ∈ {0x19, 0x2A, 0x2B} → OPP {225, 242, 243} (`OPP_ID_OFFSET = 200`).

**Write window matters.** `LoadEnemyMonData` re-derives the active mon from the party arrays
when a mon is sent out, so the swap must land *before* the first send-out. The client writes
on `trainer_battle_start`, which is gated on three stable frames of `wIsInBattle == 2`.

**Explode Mode** — `EXPLOSION = 153` into `wBattleMonMoves` (0xD01C) slot 0 with PP at
`wBattleMonPP` (0xD02D), mirrored into the party struct (+0x08 / +0x1D so the move survives
a switch), plus `wPlayerMoveListIndex` (0xCC2E) and `wPlayerSelectedMove` (0xCCDC). Falls
back to `force_faint` when the target is benched.

### Safe-state gate

`M.isInOverworld()` is `wIsInBattle == 0` **and** `wJoyIgnore == 0` (0xCD6B — nonzero while a
script owns the joypad) **and** `wFontLoaded` bit 0 clear (0xCFC4 — a text box is up). A bare
`not in_battle` is also true in the PC box UI, the party menu, the naming screen and the
title screen, all of which are unsafe write windows. Deferred `box_mon` is additionally
refused while `wCurrentBoxNum` (0xD5A0, low 7 bits) is the memorial box.

### PP-Up encoding

Gen 1 packs the PP-Up count in the **top two bits** of each PP byte (`PP_UP_MASK`), same as
Gen 2 — `pp_encoding = "ppup_packed"`. The claim in an earlier revision of
`data/games/gen1_rby/README.md` that Gen 1 has no PP-Up encoding was wrong.

### Archipelago (Alchav/pokered)

Detected by reading the **ROM domain** at `0x5F22` (`Title_Seed`, 20 bytes in the Gen 1
charset), not HRAM. `rom_type` is `red_ap` / `blue_ap`, registered in `_ROM_TYPE_TO_GAME_ID`.
The AP fork relocates WRAM, so `red_ap` is a **full literal profile** in `M.PROFILES` with 11
changed addresses — not an inherited copy with a couple of overrides.

### SFX needs the companion patch — Gen 1 has no RAM sound trigger

`SFX_DISPATCH_ADDR` is `nil` on an unpatched cartridge, and that is permanent, not pending.
It used to be `0xD35B` (`wMapMusicSoundID`, the stored map music id), so every capture and
faint corrupted the map's BGM. **`wNewSoundID` (`0xC0EE`) is not the fix** — it looks like a
mailbox and is not: `PlaySound` takes the id in register `a` and only uses that address as
internal scratch (`home/audio.asm:140`), and nothing polls it. No address works; the id has
to reach a `call`.

The companion patch supplies one — a request byte at mailbox+7 consumed each VBlank, at a
point where the game has already switched to `wAudioROMBank` and run `Audio1_UpdateMusic`
(`home/vblank.asm:53-71`), so it is audio-bank context by construction. `PlaySound` parks the
caller's bank in `hSavedROMBank` (`$FFB9`), which the hook saves and restores because the main
thread may itself be mid-`PlaySound` when the interrupt fires.

**Sound ids are bank-relative.** The same number is a different sound depending on which audio
bank is loaded (overworld = Audio1, battle = Audio2). 128 shared SFX are id-aligned across
banks 1 and 2, but only 64 exist in all three — the profile defaults use only those, so an
event fired mid-battle cannot play the wrong sound. Ids are derived, not guessed:
`id = (SFX_X - SFX_Headers_N) / 3` over the header labels in `data/pret_rom_syms.json`.

`M.detectCompanionPatch()` reads the `'SLNK'` beacon at runtime and only raises
`SFX_DISPATCH_ADDR` at ABI ≥ 2, so unpatched ROMs, Yellow (no free WRAM to patch) and AP
builds all stay a clean no-op.

### The memorial box must claim the SRAM banks first

`ChangeBox` opens with `bit BIT_HAS_CHANGED_BOXES, [hl]` (bit 7 of `wCurrentBoxNum`) followed
by `call z, EmptyAllSRAMBoxes` (`engine/menus/save.asm:366`; same in pokeyellow and the AP
fork). The first time a player ever picks "CHANGE BOX", the game marks **every** SRAM box
empty as a one-time init — including box 12, the memorial. A run that buried a pair before the
player first opened the box menu would lose it silently.

**Historical (pre-rewrite Gen 1 client, deleted in `21ff0d7`):** that client's `M.protectSramBoxes()`
ran the init itself and set the bit, so the game's wipe never fired; it also recomputed the
box-bank checksums with `M.refreshSramBoxChecksums` (a red herring in the decomp — nothing ever
reads them — but kept for self-consistency). Neither helper exists any more; `lua/memory_gb.lua`
was trimmed to what the Gen 2 client still called (`9969845`), then removed outright once that
legacy client itself was replaced by `lua/gen2/` (P3b.8b).

**The rewritten Gen 1 client takes the opposite approach.** `lua/gen1/boxes.lua` never forces the
init: it refuses to write an SRAM box until the game's own `ChangeBox` has initialised it
("saved boxes not initialized"), so there is no window in which SLink's own pre-init could race
the game's wipe. This is a documented limit, not a regression — see
`docs/gen1_gen2_runtime_checks.md`'s "Gen 1 — documented limits" section. All of this is
profile-keyed on `sram_box_layout`, which only Gen 1 declares — Gen 2's box banks differ.

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
| wMapGroup | 0xDCB5 | Current map group |
| wMapNumber | 0xDCB6 | Current map number |
| wBattleMode | 0xD22D | 0=overworld, 1=wild, 2=trainer |
| wPlayerID | 0xD47B | 2-byte OT ID (big-endian) |
| wCurBox | 0xDB72 | Active PC box index, 0-based (0–13). Plain index — no "changed boxes" bit 7, unlike Gen 1 |
| wScriptRunning | 0xD438 | Safe-state predicate. Nonzero while a script or full-screen menu owns the game |
| sBoxCount | 0xAD10 | Active box mon count. **SRAM**, not WRAM — the `s` prefix is pret's; `wBoxCount` is a *Gen 1* symbol. System Bus view, read through the **CartRAM** domain |
| sBoxMons | 0xAD26 | Active box struct base (20 × 32 bytes), same SRAM/CartRAM caveat |

The safe-state predicate the Crystal profile uses is `wScriptRunning`, not a `wJoypadDisable`
analogue — that was **measured** on real Crystal, not picked by name (the one-off discovery
probe that measured it is retired; the finding lives here and in the profile data now).
`wJoypadDisable` reads `00` both in the overworld and with the START menu open;
`wTextboxFlags` is text-*speed* config. Gating writes on `not in_battle` alone is what this
replaces: that is also true inside the PC box UI, the party menu and the naming screen, where
the open UI holds its own copy of the data and writes it back over ours.

Every address above is exercised on a running cartridge by `lua/tests/gen2_inspect_gate.lua`
(`tests/live/test_gen2_new_gates.py`) — the map pair resolves PLAYERS_HOUSE_2F to group 24 /
number 7, `wBattleMode` reads out-of-battle in the town fixture, and the box reads return a
real count and a sane 0–13 active index. A correct address read through the wrong *domain*
still produces plausible-looking bytes, which is exactly why a static check against pret alone
would not be enough.

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
- 14 boxes × 20 mons per box. The **active** box is the only one with a struct base in the profile (SRAM bank 1, via CartRAM); the rest are reached by flat CartRAM offset
- No abilities, no ASLR, no encryption — plaintext data
- Apricorn balls (Level, Lure, Moon, Friend, Fast, Heavy, Love) for nuzlocke gate detection
- Memorial box is **Box 14** (`MEMORIAL_BOX_INDEX = 13`, 0-indexed), written straight to SRAM at flat CartRAM `0x79E0` — proven by the `memorialize` duo scenario, not just by the write gate

### Gift/static encounter area_ids

| area_id | Encounter |
|---------|-----------|
| `new_bark_town` | Starter Pokémon |
| `goldenrod_city` | Eevee (Bill), Odd Egg |
| `olivine_city` | Shuckie (Shuckle) |
| `dragons_den` | Dratini (elder gift) |
| `route_34` | Odd Egg (Day Care) |

### Known Limitations (Gen 2 Crystal)

These are what is *actually* open. The addresses and the memorial box are no longer among them
— see the gate note above.

- **No grass fixture, so nothing has ever been caught.** New Bark Town's west exit is
  script-locked until Elm hands over a starter, so every title's `town` fixture parks indoors —
  there is no `town` target with grass to walk. That is why `playthrough`,
  `deadzone` and `dupes` do not run on Gen 2. Those rules live server-side and are
  generation-independent, and Gen 1 runs all three — buying a Gen 2 grass fixture would buy a
  second copy of coverage that already exists.
- **AP Crystal has no dump to run against, and is refused outright (O-25).** Gold and Silver
  now have qualified fixtures and run the same three live gates as Crystal (Silver shares
  Gold's engine-sites receipt, O-23). AP Crystal is worse off for a different reason: the fork
  has no public repo, only five of its addresses are provable, and its profile stays flagged
  unverified — moot now that it is refused rather than routed.
- **`sram_box_layout` is deliberately absent for Gen 2.** That is correct, not a gap: Gen 2's box banks sit outside the save checksum
  (`SaveChecksum` / `VerifyChecksum` cover `sGameData..sGameDataEnd` only), and
  `ChangeBoxSaveGame` does `SaveBox`/`LoadBox` with no `EmptyAllSRAMBoxes` equivalent — there is
  no one-time wipe to defend the memorial against. `tests/live/test_gen2_write_windows.py`
  (`lua/tests/gen2_write_windows.lua`) proves the burial survives without it. Do not "fix" this
  by giving Gen 2 a layout; Gen 1's banks differ.
- Gold/Silver ship as variant profiles (`lua/gen2/entry.PACKS`, pret-authoritative addresses via `tools/build_pret_syms.py`); title detection returns them

---

## Gen 3 (FRLG + Radical Red) Memory Map

All multi-byte values are little-endian. FRLG record geometry is verified against [pret/pokefirered](https://github.com/pret/pokefirered) (`include/pokemon.h`, `src/load_save.c`, `include/pokemon_storage_system.h`); Radical Red changes are carried by its pack rather than by a client-side address table.

### Admission and ROM identification

`lua/gen3/entry.lua` is hash-first: `gameinfo.getromhash()` is matched against the packs' admission data, then the engine-site anchors, then a header-named fallback. The launcher accepts only `gen3_frlg` (FireRed/LeafGreen) and `gen3_rr` (Radical Red). Emerald, Archipelago-FRLG, unknown hacks, and a header-only BPRE/BPGE match are refused by name. There is no pure-Lua ROM rehash; the anchor pass is the byte-level proof. Missing or mismatched pack data fails before hooks or writes are armed.

### Stable EWRAM globals (FireRed US 1.0)

**FRLG profile addresses** (pinned US 1.0 artifacts; randomized FRLG is not admitted):

| Symbol              | Address      | Type          | Notes |
|---------------------|--------------|---------------|-------|
| `gPlayerPartyCount` | `0x02024029` | u8            | Live count (0–6) |
| `gPlayerParty`      | `0x02024284` | Pokemon[6]    | 600 bytes (6 × 100) |
| `gEnemyPartyCount`  | `0x0202402A` | u8            | Wild/trainer enemy |
| `gEnemyParty`       | `0x0202402C` | Pokemon[6]    | Immediately follows gEnemyPartyCount |

The FRLG addresses above are data in `data/games/gen3_frlg/profile.json`; `reads.lua` receives them through the injected I/O and never hardcodes them. Radical Red uses its own pack fields. Archipelago FRLG is unadmitted, so its former address shifts are not active client profiles.

### SaveBlock ASLR — map, PC storage, and bag pockets

FRLG relocates `gSaveBlock1Ptr`, `gSaveBlock2Ptr`, and `gPokemonStoragePtr` whenever `SetSaveBlocksPointers()` runs. `reads.lua` dereferences the live pointer addresses supplied by `write_checkpoint.json` on each read and bounds the relocation window; no target address is cached. `client.lua` uses the read facade rather than calling `memory.*` directly.

```lua
local location = reads:read_location()  -- map group and number
local storage  = reads:read_storage()   -- live PokemonStorage pointer
local balls    = reads:read_balls()     -- profile-derived ball pocket
```

For the admitted FRLG pack, the SaveBlock1 bag fields are the pret-verified offsets below. The active decoder obtains the offsets, slot count, and quantity rules from the pack; there is no active AP-FRLG branch.

| Offset | Field | Size | Notes |
|--------|-------|------|-------|
| `+0x0310` | `bagPocket_Items[42]` | 168 B | Normal items |
| `+0x03B8` | `bagPocket_KeyItems[30]` | 120 B | Key items |
| `+0x0430` | `bagPocket_PokeBalls[16]` | 64 B | Pokéball pocket |
| `+0x0464` | `bagPocket_TMHM[58]` | 232 B | TMs/HMs |

`reads:read_balls()` returns the decoded count and `has_pokeballs`; `client.lua` uses that fact to latch the Nuzlocke gate and publish the ball count.

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

**HP, status, and level are outside the encrypted region.** Read them through the profile-driven read facade; any write still goes through the armed `writes.lua` sink. Never write inside `+0x20`–`+0x4F` without re-encrypting and recomputing the checksum — doing so creates Bad Eggs.

### Pokémon identity and party reads

Use `personality .. ":" .. otId` as the stable identity string for a mon. `reads.key(mon)` returns the uppercase `PERSONALITY:OTID` form used on the wire; it survives slot moves, box deposits, evolutions, and reconnects. The client reads party records through `reads:read_party()` (or its occupied-slot form) and takes HP, level, and status from the decoded profile record, rather than reading a fixed party base itself.

```lua
local party = reads:read_party(true)
for _, mon in ipairs(party) do
    local key = reads.key(mon)
    -- use mon.hp, mon.max_hp, mon.level, ...
end
```

### Detecting a new capture

`signals.lua` observes the pack's engine sites; `client.lua` drains those signals and settles the party/box snapshot once on a signaled frame. Acquisition signals such as `capture_wild`, `mon_given`, and `pc_move` mark a diff against the learned-key baseline, while a full-party capture is found in the box cache. The reducer emits the capture and its stats/blob from the decoded records; there is no legacy every-frame polling helper.

### Decrypting species from substruct data

For FRLG, the 48-byte data section is split into four 12-byte substructs in the `personality % 24` order; the secure block is XORed with `personality XOR otId`. `reads.lua` applies this rule. Radical Red's pack sets its fixed-order/no-encryption mode instead.

### PC Storage layout

From `include/pokemon_storage_system.h`:
- FRLG keeps 14 boxes × 30 slots of 80-byte `BoxPokemon` records behind the relocated `gPokemonStoragePtr`; Radical Red's pack describes its own compressed box layout.
- The memorial target is the last box in the active profile's `BOXES_PER_STORE`; `boxes.lua` addresses that index for deposit, withdraw, and memorialization.
- Storage operations arm the same `writes.lua` sink used by the rest of the Gen 3 client.

### Force-faint (battle-safe write)

The client builds a profile-derived plan containing the party HP address (and the battle-mon HP address when applicable), then arms the `battle_faint` reason through `writes.lua`. `safety.lua` checks the pack's battle clauses before the first byte; a refusal holds the command. Bench faints use the immediate HP plan, while an active battler follows the pack-proven engine path (Perish where the pack proves it). No Gen 3 production module calls a raw `memory.write_*` sink.

### Explode Mode (Radical Red — optional per-run rule)

When `--explode-mode` is active, `client.lua` handles `force_explode`. A pack must supply the required battle fields before the client builds Explosion move/PP/action/commit rows; those rows go through `writes:arm("battle_commit", ...)` and `safety.lua` checks the battle clause set and any proven controller hand-off. The engine's move/action state is the witness for commit, execution, and failure. A surviving active battler is held until it leaves the battle or the battle ends, then the force-faint path applies. The client contains no Radical Red address literals.

> **Native battle path:** the companion patch's old battle-control opcodes remain reserved; the production `force_explode` path is the Lua Variant-3 write plan described above, not a mailbox command.

### Rival Team Swap (Radical Red — optional per-run rule)

When `--rival-team-swap` is active, the server sends `replace_rival_team` with the partner's validated party blobs and battle identity. `client.lua` checks the session nonce, battle epoch, trainer, and selectable-team prefilter before calling `native:replace_rival_team`. `lua/gen3/native.lua` owns blob staging, the armed `native` mailbox post, acknowledgement, and enemy-party readback; it uses the pack's native opcode data rather than old memory helpers. A missing companion is reported as `patch_required`; a missing qualified refresh window is reported by name rather than bypassed. The rival path uses its own companion opcode, while the trade transport remains separate.

**Blob transport (server):** `hello`, `tick`, and safe snapshots carry validated per-slot `blob_hex`; the server caches them in `partner_blobs[player_id]` and drops malformed entries before a command is queued.

**Trigger pipeline (`server/state.py`):** `_handle_trainer_battle_start` queues the swap only when the trainer is in `adapter.rival_trainer_ids()`, the toggle is on, and the partner has valid cached blobs. The client acknowledges with `rival_team_replaced` and the native readback result.

### Companion Patch (Radical Red only — code-injection ROM patch)

The `patch/` directory holds a UPS companion for Radical Red. The current Gen 3 release uses it for native trade, the info panel, sounds, and the rival-swap opcode. `boxes.lua` has an optional native-executor seam for deposit/withdraw/memorialize (`io.native_executor`), but production never wires it, so PC and memorial moves go through the armed Lua write sink (`writes.lua`, reason `overworld`) on every title, including Radical Red; the patch's `OP_MEMORIALIZE` opcode is reserved in the ABI but unused by this client. Native message text and the peer-ghost feature are not part of the current Gen 3 client release; do not infer them from the archived client.

- **Mailbox protocol:** `lua/gen3/native.lua` is the client-side owner and `patch/src/handlers.c` is the in-ROM dispatcher. It stages args/blobs under an armed `native` write, publishes the opcode last, and polls the acknowledgement through injected I/O.
- **ABI data:** the authoritative opcode/status definitions live in `patch/src/handlers.c` and `patch/src/ADDRESSES.md`; `native.lua` consumes the matching values from `profile.native` and does not duplicate a legacy opcode table.
- **Build & distribution:** `patch/tools/build.py` (gcc → ld → objcopy → inject → UPS/IPS, round-trip self-checked). `server/patcher.py` serves the in-browser patcher page at `GET /patcher` (`?game=` selects a target) and each built patch at `GET /companion/{name}`, mounted on both the per-run server (8080) and the Manager (8090). Gen 1 has its own toolchain: `patch/gen1/tools/build.py` builds from the two pinned CLEAN dumps, `patch/gen1/tools/inject.py` applies the SAME manifest structurally to a ROM whose hash cannot be known in advance (a randomized cartridge), and `patch/gen1/tools/manifest.py` is the single description both read so they cannot drift.
- **Per-run toggles:** Manager/CLI flags are delivered through the hello configuration; they do not change Soul Link rules. Unpatched or clean artifacts use the Lua storage/write paths where the pack supports them.

### Area Normalization

Raw `mapGroup:mapNum` maps to a canonical `area_id` through `data/games/gen3_frlge/area_map.json`, which both admitted Gen 3 packs load; `gen3_frlge_locations.lua` supplies display names. The generated `gen3_frlge_areas.lua` remains a server-side compatibility table, not a dependency of the rewritten client. The 184-entry map is generated from `area_map.json` by `python tools/gen_area_map.py`. Key decisions:

- Multi-floor dungeons share one area_id (e.g., all Mt. Moon floors → `"mt_moon"`)
- Building interiors with wild encounters (Safari Zone areas) each get their own area_id
- Routes and towns with no wild encounters are not in the map (produce `area_id = ""`)
- Naval Rock (Lugia/Ho-Oh), Birth Island (Deoxys), and Sevault Canyon are included
- Legendary/static battles use the pack's wild/trainer facts and use the area_id of their map like any other encounter

**Gift/static encounter area_ids** (Pokémon obtained here before Pokéballs are possible):

| area_id | Encounter |
|---------|-----------|
| `oaks_lab` | Starter Pokémon (vanilla) |
| `intro` | Generic intro/unmapped-area fallback |
| `gift` | Fallback for gift Pokémon in unmapped areas |
| `cinnabar_lab` | Fossil revives |
| `celadon_hotel` | Eevee |
| `silph_co_7f` | Lapras |
| `saffron_dojo` | Hitmonlee / Hitmonchan |

Captures in these areas do not activate `pokeballs_obtained` on the server. Faints before the ball gate are also ignored. The `gift` fallback keeps a static acquisition out of a wild encounter slot when the map has no area_id.

**Gift/egg `gift_<area>` namespace remap (`gift_link_area`).** A gift or egg received in a real (non-gift) encounter area must not consume or lock that area's single wild-encounter slot. The adapter remaps such captures into the **`gift_<area>`** namespace (`gift_link_area` in `adapters/base.py`): gifts already in a gift area, and daycare-bred eggs, keep their `area_id`; everything else becomes `gift_<area_id>`. The `gift_` prefix is recognized by `is_gift_area` downstream, so a remapped capture forms a standalone gift pair that bypasses dead-zone/linked-wild quarantine, skips quarantine, and never satisfies the Pokéball gate. The Gen 3 reducer tags these captures with `gift=true`.

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

### How events are detected (Gen 3 signals + reducer)

`lua/gen3/signals.lua` turns the admitted pack's `engine_signals.json` sites into bounded, fail-closed hooks. `lua/gen3/client.lua` drains those signals and settles the decoded party/box snapshot once on a signaled frame; the wire event is the result, not a raw per-frame RAM diff.

| Event | Detection condition |
|---|---|
| `area_enter` | A map/location signal or decoded `map_group:map_num` change; new-encounter prompts are suppressed in gift areas and before the ball gate |
| `capture` | An acquisition signal (`capture_wild`, `mon_given`, or `pc_move`) followed by a new key in the party/box baseline; carries `gift=true` for a gift/egg |
| `faint` | A faint/battle-end signal followed by a known key's HP transition to zero |
| `no_catch` | A known wild battle ends without a caught acquisition, outside the exempted battle types, and after the ball gate |
| `whiteout` | The whiteout engine signal is reduced after the party snapshot |
| `party_to_box` | A known key leaves the party and is subsequently observed in the box cache |
| `box_to_party` | A known box key reappears in the occupied party snapshot |
| `tick` | Periodic client tick carrying the current ball count, area, battle facts, and party/box snapshot |
| `key_change` | An NPC trade changes the PID:OTID key; the client sends `old_key`, `new_key`, and `reason` for server migration |
| `trainer_battle_start` | A trainer battle signal carries the trainer ID and, when available, the session/battle identity used by Rival Team Swap |
| `rival_team_replaced` | Native command acknowledgement with the readback species list or a named refusal |

The ball gate is client-owned: `reads:read_balls()` reports the profile-derived count, and the reducer suppresses `no_catch`/encounter bookkeeping until that count is positive. The server has no corresponding gate — it trusts the client not to send `no_catch` prematurely.

### Commands (Python → Lua via TCP response)

| Command | Gen 3 client action |
|---|---|
| `force_faint` | Locate the key in the decoded party and submit the pack-backed HP plan through `writes.lua`; an active battler uses the proven battle path |
| `force_explode` | When the pack proves the battle fields, submit the Explosion move/PP/commit plan through `battle_commit`; otherwise hold or use the force-faint path |
| `box_mon` | `boxes.lua` deposits the named mon through the armed storage plan |
| `party_mon` | `boxes.lua` withdraws the named box mon and writes the server-supplied stats through the same sink |
| `memorialize` | Move the dead mon to the profile's memorial box through `boxes.lua`, deferred to a safe checkpoint |
| `replace_rival_team` | Validate session/battle identity, then let `native:replace_rival_team` stage and post the Radical Red companion operation; missing native support is a named refusal |
| `hud_show` | Display a text message on the BizHawk HUD overlay with custom RGB color and duration |
| `noop` | No action; returned when there is nothing to do |

### pokeballs_obtained tracking (server-side)

The server tracks `pokeballs_obtained` per player for:
1. **Faint gating**: Faints (and `hello` reconnect reconciliation) are ignored until `pokeballs_obtained[player_id] == True`.
2. **Status page display**: Shown as "Nuzlocke active" / "Waiting for Pokéballs".
3. **Persistence**: Saved in `data/links.json`.

Activation sources (in order of preference):
1. `hello` event with `has_pokeballs: true` — set directly from the client's decoded ball state.
2. `hello` event with no `has_pokeballs` field and non-empty `party` — compatibility heuristic for older clients.
3. `capture` event in a non-gift area — belt-and-suspenders.
4. Explicit `has_pokeballs: false` in `hello` — overrides the heuristic even with a non-empty party.

### Safe-state definition

Gen 3 does not use a single `not in_battle` test for writes. `lua/gen3/safety.lua` evaluates the active pack's `write_checkpoint.json` and `lua/gen3/writes.lua` revalidates the selected reason before the first byte:

- **`overworld`**: ROM anchors, callback/script context, palette/save/link state, the active-task allow-list, parked CPU mode/PC, an idle native mailbox, and stable SaveBlock/storage pointers.
- **`battle_faint` / `battle_commit`**: the pack's complete battle clause set, commit guard, and any proven controller hand-off; an unreadable or incomplete pack is refused.
- **`native`**: companion signature/ABI and mailbox-idle checks; clean FRLG/RR artifacts have no native block and cannot arm native writes.
- **`sound`** (when enabled): the pack's sound block and initialized m4a state.

An unknown reason, missing anchor, failed predicate, or unreadable input returns a refusal. The client holds the deferred command; it never falls back to a direct RAM poke. Archipelago FRLG and Emerald are refused during admission, so their former AP/CFRU-specific battle branches are not part of the active client.

---

## HTTP Status Page

The server exposes a live status page at `http://localhost:8080/` (configurable via `--http-port`). Page title is dynamic: "Pokémon Soul Link Tracker — \<Game Variant\> — \<Run Name\>" (populated from persistent `rom_type` and `--run-name` CLI arg, with Pokéball SVG icon).

**Templating + refresh model.** HTML is rendered by Jinja2 (`aiohttp-jinja2`) from `server/templates/`. The page boots with full markup, then HTMX (`server/static/vendor/htmx.min.js`) polls each root fragment (`#content`, `#enc-table-root`, `#focus-root`, …) every 2 s and swaps them in via **idiomorph** (`idiomorph-ext.min.js`). A `beforeAttributeUpdated` hook preserves `<details open>`, scroll position, and table-search focus across swaps. Small UI widgets (theme picker, run filter, OBS trigger editor) are Alpine.js components. The dashboard does not subscribe to SSE.

`/api/events` still exists for external consumers (the SLink calc bridge uses it). It pushes two named event types — `event: status` (full JSON) and `event: ping` (state-change signal). Coalescing queues (`maxsize=1`, latest wins) prevent backpressure; heartbeat comments every 15 s detect dead clients; the browser reconnects automatically (`retry: 3000`).

**Static assets** are served from `server/static/`. A small aiohttp middleware in `server/templating.py` stamps `Cache-Control: no-cache` on every `/static/` response — combined with the existing `ETag`, browsers cache the asset but revalidate every request (matching ETag → 304, ~150 bytes). This stops the heuristic-cache staleness that used to require hard refreshes after CSS/JS edits.

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
pytest tests/unit/ -v   # 14215 tests collected
pytest tests/unit/test_state.py -v          # 319 tests (incl. tick reconciliation + Explode Mode)
pytest tests/unit/test_gen1_adapter_contract.py -v  # 10 tests (checked against pret source, not shipped JSON)
pytest tests/unit/test_gen2_adapter.py -v   # 59 tests (Gen2GSCAdapter)
pytest tests/unit/test_gen3_adapter.py -v   # 218 tests
pytest tests/unit/test_gen4_adapter.py -v   # 101 tests
pytest tests/unit/test_gen5_adapter.py -v   # 140 tests
pytest tests/unit/test_stat_stages.py -v    # 48 tests
pytest tests/integration/test_phase1_comms.py -v   # 6 tests
pytest tests/unit/test_obs_priority.py -v   # 7 tests (priority + area-group filters)
pytest tests/unit/test_manager_launcher.py -v   # 4 tests (BizHawk launcher Lua syntax)
# 0.2.6 — Rival Team Swap / Upcoming Key Trainers:
pytest tests/unit/test_trainer_panel.py -v             # 14 tests (Upcoming Key Trainers panel)
pytest tests/unit/test_state_rival_battle_start.py -v  # 34 tests (rival-swap auto-trigger)
pytest tests/unit/test_state_party_blob_cache.py -v    # 10 tests (blob_hex cache)
pytest tests/unit/test_gen3_adapter_rival_ids.py -v    # 8 tests (rival trainer IDs)
pytest tests/integration/test_cli_rival_team_swap.py -v       # 4 tests (--rival-team-swap CLI)
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

The numbered `lua/tests/test_1_memory.lua` … `test_5_soullink.lua` scripts are gone — they belonged to the removed Gen 3 client, and `tests/TESTING.md` records Tests 1–3 as removed for that reason. See `tests/TESTING.md` for the current walkthrough and its pass criteria; the per-generation gate scripts now live in `lua/tests/` under their own names (`gen1_gate.lua`, `gen2_*`, `gen3_*`).

---

## Key Implementation Constraints

- **Mon identity**: Always use `personality .. ":" .. otId` (`monKey`) as the stable identifier. Never use party slot index — it changes when mons are rearranged.
- **Commands are queued, not pushed**: When player A's event triggers a command for player B, it is queued in `SoulLinkState.queued_commands["b"]` and delivered on B's next TCP message. This is why `tick` events are sent periodically.
- **State is fully serialized on every change**: `SoulLinkState._save()` writes `data/links.json` after every event that mutates state. No in-memory-only state should be load-bearing.
- **No writes during battle**: Never zero or copy party/box data outside a qualified Gen 3 write plan. `force_faint` uses the `battle_faint` checkpoint; full-slot memorialization is deferred to the pack-backed `overworld` checkpoint.
- **Encrypted substruct writes**: Never write to `BoxPokemon +0x20`–`+0x4F` without re-encrypting (key = personality XOR otId) and recomputing the checksum. Bad Eggs result from invalid checksums; `boxes.lua` owns the FRLG encode path.
- **Party compaction**: Deposit/withdraw/memorial plans update the profile-derived party count and records atomically through `boxes.lua`; do not hardcode `0x02024029` in a new client path.
- **SaveBlock ASLR**: The pointer addresses and relocation bounds come from the active pack/checkpoint. `reads.lua` dereferences them on each call; never cache or hardcode the live target.
- **Nuzlocke gate is in Lua**: The server trusts that the client will not send `no_catch` before its decoded ball count is positive. The server's own faint-related gate remains `pokeballs_obtained`.
- **Admission is fail-closed**: `Entry.admit` admits only pinned FireRed, LeafGreen, and Radical Red artifacts; Emerald and Archipelago-FRLG are refused before the client graph is built.
- **Profile-driven reads**: FRLG and Radical Red share the composition root but differ in pack data and record rules. Do not add a title branch or a client-side address database.
- **Borrowed-party battles (Radical Red)**: At `battle_begin`, the client snapshots the known party keys. If the live party has no overlap with that baseline, the reducer freezes party learning and omits party data from ticks until the own party returns; queued battle writes remain held.
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

### Borrowed-party handling (Radical Red)

At `battle_begin`, `client.lua` snapshots the keys in the pre-battle party. On each party read, `update_frozen()` compares the live keys with that baseline. A party with no overlap is treated as borrowed: the reducer does not settle captures, faints, or PC moves, and `tick` omits party data. When the own-party keys overlap again, the client rebaselines and resumes normal reduction. Queued battle writes remain held until the real party is restored. The legacy rolling-gift detector is not part of the new client.

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

### How abilities are read (Gen 3 → Server)

1. **Client decode:** `lua/gen3/reads.lua` decrypts the Gen III record and exposes the ability bit (`ability_num`) alongside the rest of the party/box record. The client has no separate ability cache or `gBaseStats` address path.
2. **Wire/server boundary:** when a party detail carries an `ability_id`, the server's Gen 3 adapter and `pokemon_data.py` resolve the display name and description, including Radical Red overrides.
3. **Refresh rule:** the new client publishes decoded party/box records through its normal hello/tick/settle paths; a hidden-ability change is not assumed to produce a PID:OTID `key_change`.

### Ability data boundary

`gBaseStats` is not a Gen 3 client dependency in the rewritten architecture. Species/ability tables and Radical Red overrides are server presentation data; the client supplies decoded records and pack-backed capability facts.

---

## Key-change handling

The current Gen 3 client emits `key_change` when an NPC trade changes the PID:OTID identity in the decoded party; it sends the old/new keys and `reason="npc_trade"` to the shared identity/session layer. The server still accepts the protocol's generic `key_change` event, but the new client does not claim the archived signature-based personality scan or a Radical Red Nature Changer detector.

**Server-side handling** (`state.py`): `_handle_key_change()` migrates the old key to the new key across links, indexes, pending captures, party/stat caches, bonus state, memorials, and queued commands.

---

## Stream Overlay Sprites

Stream overlays (`/stream/links`, `/stream/party-a`, `/stream/party-b`) use `sprite_html` from the JSON API response as the source of truth; older overlays may retain a client-side fallback. The `sprite_html` field is also included in `party_details` in `/api/status`, and server-side sprite generation handles CFRU→NatDex species conversion.

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

The status page party tables now display enemy battle type badges (Wild, Trainer, etc.) alongside enemy mon data during active battles. Enemy held items are shown inline with the species name (e.g., "Pidgey @ Oran Berry"), matching player party display style. The active Gen 3 client reads enemy-party/item fields through its pack-backed read layer; the server presentation layer supplies the battle badge and item name.

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

`/memorial` — a dedicated solemn page showing tombstone cards for each dead linked pair. Displays greyscale Pokémon sprites, nicknames, species, levels, area of death, cause of death, and killer details (if applicable). Renders from `server/templates/memorial.html`, refreshed via HTMX (idiomorph). Data sourced from the killfeed in `/api/status`. Sprites use server-side `_sprite_img_html()` for correct CFRU→NatDex species conversion. RR sprites from funnotbun have solid backgrounds — canvas-based transparent background processing removes them client-side. `a_sprite_html` and `b_sprite_html` fields are included in the killfeed JSON API.

---

## Debug Page

`/debug` — debug console for manual state manipulation during development and troubleshooting. All panels refresh in-place via HTMX (2 s poll, idiomorph swap). Features a live status banner showing connection state, link/area counts, and queued commands. Panels:
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


