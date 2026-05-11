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
- **Stream overlays** at `/stream` — individual overlay pages for OBS (party, links, deaths, areas, events).

### 4. Load the Lua client in each BizHawk instance

**Option A — Universal entry point (recommended):**
1. Open the BizHawk Lua Console (**Tools → Lua Console**).
2. Load `lua/slink_gen1.lua` (Gen 1), `lua/slink_gen3.lua` (Gen 3) or `lua/slink_gen4.lua` (Gen 4).
3. Edit the top of the launcher to set `SLINK_HOST`, `SLINK_PORT`, and `SLINK_PLAYER` before loading.

Alternatively, load `lua/slink.lua` directly — it auto-detects the game but uses default connection settings (`127.0.0.1:54322`, player `"a"`).

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

The status server (default port 8080) exposes these pages and endpoints:

| Path | Description |
|---|---|
| `GET /` | Main status page — live player cards, encounters, linked pairs, area states |
| `GET /memorial` | Memorial wall — tombstone cards for each dead linked pair with sprites, cause of death |
| `GET /debug` | Debug console — live SSE, link management (create/unlink/override/revive), mon key & area autofill, event injection, command queuing, state toggles, live state panel, backup rollback |
| `GET /stream` | Stream overlay index — links to individual overlay pages for OBS |
| `GET /stream/party-a` | Stream overlay — Player A party |
| `GET /stream/party-b` | Stream overlay — Player B party |
| `GET /stream/links` | Stream overlay — linked pairs |
| `GET /stream/deaths` | Stream overlay — death feed |
| `GET /stream/areas` | Stream overlay — area states |
| `GET /stream/events` | Stream overlay — recent events |
| `GET /launcher/{player}` | Download launcher Lua script (pre-configured for this run) |
| `GET /api/status` | JSON status dump (full state) |
| `GET /api/events` | SSE stream (pushes `event: status` and `event: ping` on state changes) |
| `POST /api/reset` | Wipe all state and start fresh |
| `POST /api/inject_link` | Manually create a link between two mons |
| `GET /api/debug/raw_state` | Raw links.json + live state |
| `GET /api/debug/manual_link_data` | Mon options + area data for manual link UI |
| `POST /api/debug/inject_event` | Inject a synthetic event through the state machine |
| `POST /api/debug/queue_command` | Manually queue a command for a player |
| `POST /api/debug/set_pokeballs` | Toggle pokeballs_obtained for a player |
| `POST /api/debug/set_area_state` | Override an area's state |
| `POST /api/debug/clear_pending` | Clear pending captures (all or per-area) |
| `POST /api/debug/unlink` | Remove a link entry (unlink two mons) |
| `POST /api/debug/revive` | Revive a dead/memorial link back to alive |
| `GET /api/debug/backups` | List rolling backups with state summaries |
| `POST /api/debug/rollback` | Roll back to a backup slot |

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
| Whiteout | All of A's party mons faint → all of B's linked party mons are force-fainted |
| Species clause (opt-in) | `--species-clause` — rejects links where both mons share the same evolution family (e.g. Charmander ↔ Charmeleon). Also rejects captures where the **same player** already has an alive linked mon of the same evo family (same-save duplicate prevention). Dead/memorial pairs don't block. The violating capture is force-fainted; the area stays pending for retry |
| Gender clause (opt-in) | `--gender-clause` — rejects links where both mons are the same gender (♂+♂ or ♀+♀). Genderless mons are exempt. The violating capture is force-fainted; the area stays pending for retry |
| Type clause (opt-in) | `--type-clause` — rejects links where both mons share any type (e.g. Charizard Fire/Flying ↔ Pidgey Normal/Flying — shared Flying). Uses RR type data when available; falls back to vanilla Gen I–III types. The violating capture is force-fainted; the area stays pending for retry |
| Shiny Clause (always on) | When a player catches a shiny, their partner's **next encounter** becomes the shiny's Soul Link partner (a bonus pair). The bonus pair goes through all normal Soul Link rules — lock clauses apply, faint propagation is enforced, party sync is required. The area that triggered the shiny is not consumed. If multiple shinies are caught before bonuses are claimed, bonuses queue up (FIFO). Gen 1 is naturally excluded (`is_shiny()` always returns `False`). The catching player receives a shiny sound effect and GUI prompt; the partner is notified that a bonus encounter is pending. |

---

## Feature Status (Alpha)

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

---

## Running Tests

### Unit tests (no emulator required)

```bash
pytest tests/unit/ -v          # all 647 tests
pytest tests/unit/test_state.py -v        # 234 state machine tests
pytest tests/unit/test_gen3_adapter.py -v  # 77 Gen 3 adapter tests
pytest tests/unit/test_gen4_adapter.py -v  # 62 Gen 4 adapter tests
pytest tests/unit/test_gen1_adapter.py -v  # 78 Gen 1 adapter tests
pytest tests/unit/test_gen2_adapter.py -v  # 127 Gen 2 adapter tests
pytest tests/unit/test_gen5_adapter.py -v  # 63 Gen 5 adapter tests
```

234 state machine tests covering: linking, dead zones, faint propagation, whiteout, party sync (including confirmation-based `sync_retrieve_done`/`sync_retrieve_failed`, PC swap event ordering), box capture stats caching, memorial box, reconnect re-queuing, illegal captures, encounter logging, AP ROM type handling, species clause (evo families), gender clause (genderless edge cases), type clause (shared types, partial overlap, monotypes), combined clauses, violation recovery, clause rule persistence, same-save species duplicate prevention, dynamic gift areas, hello resolved_areas, gift area no_catch protection, unlinked encounter quarantine, paired party sync enforcement, dead zone quarantined mon retirement, CFRU/RR species data validation (Gen 3 ID rekey, Gen 4+ cross-gen evolutions, gender ratios), battle HP cache writeback (CFRU), double-buffer party diff, frame ordering, player identity lock (OT ID per slot — first lock, wrong OT rejection, event blocking, persistence, empty party skip, per-player independence), persistent run metadata (rom_type, trainer_names), shiny bonus pairs (pending_bonus FIFO queue, pair formation, faint propagation both directions, party sync at formation, FIFO multi-bonus, lock clause violations with retry, area unresolve, persistence, key migration, no-wildcard-exemption), nature change (key_change migration), and dupes clause partner pending capture check.

### Integration tests (server required)

```bash
# Terminal 1
python -m server.server --host 127.0.0.1 --port 54321

# Terminal 2
pytest tests/unit/test_phase1_comms.py -v
```

### BizHawk live tests

See `tests/TESTING.md` for the full 9-step alpha test procedure. Load `lua/slink.lua` on both instances and run through Steps 1–9 in order.

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
| `data/games/gen3_frlge/gen3_frlge_areas.lua` | Gen 3 area lookup — `mapGroup*256+mapNum → area_id` (175 entries; `python tools/gen_area_map.py` to regenerate) |
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

## Known Issues

- **Overworld whiteout:** The game engine doesn't provide a hook for auto-whiteout from the overworld. SLink detects it via a party snapshot diff on the next tick but cannot force the game to teleport the player. The player must walk to a Pokémon Center manually.
- **Savestates and rewind:** Must be disabled during a live run. Rewinding can create duplicate capture events or ghost HP values. Use BizHawk's save state only before a test session, never during.
- **Party HP (tick-based):** The status page shows HP from the most recent `tick` event (~0.5s interval), not a per-frame stream. HP bars update twice per second during gameplay. Fainted mons are shown in red at 0 HP immediately when the faint event fires.
- **HUD overlay:** The in-game HUD displays event notifications (force faint, deposit, retrieve, memorialize, new encounter areas) at the bottom of the GBA screen. It is minimal by design — it only appears during Soul Link events, not during normal gameplay. The new encounter notification ("★ New encounter: Route 3") excludes gift areas (oaks_lab, intro, cinnabar_lab, etc.) and only shows once per area.
- **Party sync (full party):** If the partner's party is full when a `party_mon` command arrives, the retrieval fails gracefully — the client shows a persistent HUD notice ("⚠ Make room & retrieve [name] from PC") and sends `sync_retrieve_failed` to the server. Paired sync enforcement then kicks in: if one player successfully retrieved but the partner failed, the server finds the first player's linked mon and queues `box_mon` to re-box it — maintaining the invariant that both linked mons are always in the same place (both in party or both in box). When a new link forms (un-quarantine), retrieval is only attempted if **both** players have `party_size < 6`; otherwise both mons stay in the box with a HUD notification. Manual withdrawal of a linked mon is also blocked if the partner's party is full — the mon is re-deposited with a HUD warning.
- **Script load order:** If the script is loaded before a save file is open in BizHawk, writes will be initially disabled (SaveBlock pointers aren't valid yet). The script re-validates every frame and enables writes automatically once the save is loaded — you'll see `✓ ROM validation passed — writes enabled` in the Lua console.
- **Pre-save garbage data:** During the title screen, intro cutscene, and Oak's speech (before a save is loaded), RAM contains uninitialized data. The Lua client gates party/box/enemy data in hello and tick events behind a `gPlayerPartyCount` sanity check (0–6 range). Ticks during this period send only connection metadata (area, trainer name, ball count) without party snapshots, preventing garbage from appearing on the status page.
- **Gym badge bitmask:** Badges are sent as a raw bitmask from `SaveBlock1.flags[0x104]`, not a sequential count. This supports Archipelago's out-of-order badge acquisition (e.g. getting Badge 5 before Badge 2). The status page renders each badge independently with `badge_mask & (1 << i)`.
- **CFRU battle timing (gBattleOutcome same-frame):** In CFRU/Radical Red, the game engine can set `gBattleOutcome` on the same frame as the last mon's HP drops to 0. The Lua client handles this via a `battle_just_ended` gate on the HP cache update, ensuring the final `gBattleMons` state is captured even when `isInBattle()` returns false on the transition frame. This is transparent to the user but important for contributors modifying the battle detection code.
- **Borrowed-party battles (CFRU):** Radical Red has battles that completely replace the player's party (Poké Dude tutorial, mock/scripted battles) and tag battles where an NPC partner fights alongside you. Two detection methods are used: (1) `M.isBorrowedBattle()` checks `gBattleTypeFlags` for `BATTLE_TYPE_POKE_DUDE | BATTLE_TYPE_MOCK_BATTLE` mask `0x1010000`, and (2) a **rolling gift capture buffer** — if 3+ gift captures arrive within 45 frames, party tracking freezes until originals return or battle ends. The buffer approach catches RR scripted battles where `gBattleTypeFlags` isn't set until after the party swap. When frozen, `party_diff_ok` is set to false, tick events omit party data, and battle-end logic restores the pre-borrowed party snapshot instead of writing back battle HP. Tag battles (`BATTLE_TYPE_INGAME_PARTNER = 0x400000`) are NOT frozen — NPC partners use separate battler slots and don't affect the player's party.
- **Persistent run metadata:** The game variant (`rom_type`) and trainer names are committed on the first `hello` event and never overwritten. This ensures page titles and display labels remain stable after server restarts. Both are persisted in `links.json` under `"rom_type"` and `"trainer_names"` keys.
- **PC box level resolution:** Box mons in RAM store EXP, not level. For manual links or mons that were never in a party during the session, the server uses a multi-source fallback: MonInfo.level (from link entry) → `mon_stats` cache (from deposit events) → `party_details` from either player's most recent tick/hello. When a tick provides party data with a level, any linked MonInfo with `level=0` is permanently backfilled and saved.

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
| `POST /api/runs` | Create a new run |
| `POST /api/runs/<id>/start` | Start a run |
| `POST /api/runs/<id>/stop` | Stop a run |
| `POST /api/runs/<id>/archive` | Archive a run |
| `DELETE /api/runs/<id>` | Delete a run |
| `GET /api/runs/<id>/launcher/<player>` | Download launcher script (player = "a" or "b") |

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
- **Party rows** — sprite (32×32), nickname/species, level, nature, ability, held item, HP bar
- **Enemy rows** — matched trainer set moves with Normal/Hardcore difficulty badge
- **Active mon highlight** — orange left border + faint orange background on the currently active battler
- **One-click import** — clicking any row loads that mon's full Showdown paste into the calc attacker (`p1`) or defender (`p2`) slot automatically

The panel saves its position and collapsed state in `localStorage`. It reconnects automatically via SSE on disconnect (3-second retry). Pings arriving while the user is interacting with the panel are deferred until `mouseup` to prevent DOM rebuilds mid-interaction.

**Server endpoint:** `GET /api/calc/mons` — returns per-player party, linked pairs, and enemy battle data in calc-friendly JSON format including `showdown_paste`, `sprite_html`, `hp_pct`, `ability_name`, `item_name`, and matched `moves`.

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

See `.github/copilot-instructions.md` → "Adapter Isolation Rules" for the complete technical debt inventory and refactoring roadmap.

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
