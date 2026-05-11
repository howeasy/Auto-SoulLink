# SLink Live Testing Guide

Run these scripts in BizHawk's **Lua Console → Script → Open Script**.  
Output goes to the BizHawk **console panel**.  
Tests 1–3 are diagnostic; **Test 4 (`slink.lua` or `slink_gen3.lua`) is the alpha production script** used for actual play. Run them in order when verifying a fresh install.

---

## Prerequisites

| Requirement | Detail |
|---|---|
| BizHawk 2.9+ | Both instances open, each with a FireRed or LeafGreen US 1.0 save loaded (vanilla, randomized, AP-patched, or Radical Red 4.1) |
| LuaSocket DLL | Copy `socket-windows-5-4.dll` from your Archipelago install into `lua/x64/` (see `lua/x64/README.md`) |
| Python server | `python -m server.server --host 127.0.0.1 --port 54321` (run from project root; needed from Test 3 onward) |
| Status page | `http://localhost:8080/` — flicker-free auto-refresh every 5 s (DOM morphing); shows player areas, gym badges, party, Pokéball counts, encounters table; battle display above party |
| Scripts in `lua/` | `memory_gba.lua`, `connector.lua`, `socket.lua`, `slink.lua`, all files in `tests/` |
| Save states | Make a BizHawk save state before Test 2 (it writes RAM) |

---

## Test 1 — Memory Reader

**Script:** `lua/tests/test_1_memory.lua`  
**Emulators:** Either one. **No server. No writes. Safe on any save.**

Load the script and play normally. A live overlay appears showing party data, map info, and battle state.

### Pass Criteria

| # | What to check | Expected |
|---|---|---|
| 1 | ROM validation line | `ROM: firered OK` or `ROM: leafgreen OK` (or `firered_ap` / `leafgreen_ap` for AP ROMs, `radical_red` for RR/CFRU ROMs) |
| 2 | Party count | Matches the number of Pokémon in your in-game party menu |
| 3 | HP / MaxHP for each slot | Matches the HP bar shown in the party menu |
| 4 | Level for each slot | Matches the level shown in the party menu |
| 5 | Map field | Changes (e.g. `3:5` → `4:1`) when you walk across a route boundary |
| 6 | Area ID field | Shows a recognisable name (e.g. `route_1`) where mapped; `""` for unmapped interiors is acceptable |
| 7 | In-battle flag | Shows `true` when a wild or trainer battle starts; `false` in the overworld |

**PASS:** All 7 criteria hold while playing normally.  
**FAIL:** Any value looks wrong — note which slot/field and paste the console output.

---

## Test 2 — Force Faint (RAM Write)

**Script:** `lua/tests/test_2_force_faint.lua`  
**Emulators:** Either one. **⚠ Writes to RAM — save a BizHawk state first.**

### Controls

| Key | Action |
|---|---|
| F1 | Force-faint party slot 0 |
| F2 | Force-faint party slot 1 |
| F3 | Force-faint party slot 2 |
| F4 | **Restore all HP to maxHP** (undo — use this to reset between tests) |
| F5 | Force-faint the **last living** party mon (whiteout trigger) |
| F6 | Force-faint **all** party mons simultaneously |
| F7 | **Immediate whiteout** (in-battle only) — skips faint animation, jumps straight to blackout |

### Pass Criteria

| # | What to do | Expected |
|---|---|---|
| 1 | Press F1 | Slot 0 HP drops to 0 on the same frame |
| 2 | Press F1 **during a battle** | The mon plays its faint animation; whiteout fires when all party mons are at 0 HP |
| 3 | Press F1 **in the overworld** | HP bar shows 0 in the party menu |
| 4 | Press F4 after any faint | All slots restored to maxHP |
| 5 | Press F5 in battle with one mon alive | Faint animation plays, then whiteout — player teleports to Pokémon Center |
| 6 | Press F7 during any battle | Whiteout screen appears within 1–2 frames (no animation) |
| 7 | Press F6 in the overworld | All party mons set to 0 HP; console: `ALL PARTY FAINTED (overworld — no automatic whiteout)` |

**PASS:** HP changes instantly on the correct slot; game reacts correctly in battle.  
**FAIL:** HP does not change → check `Writes: ON` in the overlay. If it says `OFF`, validation failed — load a save first.  
**FAIL:** F7 freezes or glitches → reload the save state and retry from a quieter battle state (not mid-animation).

---

## Test 3 — Server Connectivity + Auto Event Detection

**Script:** `lua/tests/test_3_server.lua`  
**Emulators:** Either one.  
**Server required:** `python -m server.server --host 127.0.0.1 --port 54321`

Edit `SERVER_HOST` / `SERVER_PORT` / `PLAYER_ID` at the top of the file if needed.  
All output goes to the Lua **console panel** — no GUI overlay.  
The script auto-detects all event types and logs them as they happen.

### Controls

| Key | Action |
|---|---|
| F1 | Manual `area_enter` — current map area_id |
| F2 | Manual `capture` — party slot 0 (real key, level, HP, area) |
| F3 | Manual `faint` — party slot 0 key |
| F4 | Manual `no_catch` — current area_id |
| F5 | Manual `whiteout` |
| F6 | Manual `safe` |
| F7 | Manual `tick` |

### Auto-Detection Criteria

| What to do | Expected console output |
|---|---|
| Walk into a route | `AUTO area_enter:route_N → noop` |
| Catch a wild Pokémon (party not full) | `AUTO capture:<key8chars> → noop` |
| Catch with a full party (6/6) | `AUTO capture:<key8chars>(box) → noop` (from PC box) |
| Battle start | `[T3] Battle: overworld → IN BATTLE  wild=true  area=route_N` |
| Battle end | `[T3] Battle: IN BATTLE → overworld (grace window started)` |
| Trainer battle end | No `no_catch` fired (trainer battles excluded by `gBattleTypeFlags`) |
| Wild battle — run away or KO | After 15-frame grace: `AUTO no_catch:route_N → noop` |
| **Second battle in same area** | No second `no_catch` — area already resolved |
| Party mon HP → 0 | `AUTO faint:<key8chars>` |
| All party mons fainted | `AUTO whiteout → noop` |
| Return to overworld | `AUTO safe → noop` |

### Additional Checks

| Check | Expected |
|---|---|
| Startup | `[T3] TCP: connected to 127.0.0.1:54321` |
| Writes enabled | `Writes: ON` — ROM validated |
| Response format | Every response contains `"commands"` JSON |
| `force_faint` dispatched | `↳ DISPATCHED force_faint slot=N key=...` when server sends one |
| No `no_catch` after successful catch | Catching on a route suppresses `no_catch` for that route for the rest of the session |

**PASS:** All auto-detection events fire correctly; no false `no_catch` after successful catches or on repeated battles in the same area.  
**FAIL:** `NOT CONNECTED` repeated in console → server not running or wrong host/port.  
**FAIL:** `no_catch` fires after a successful catch → `resolved_areas` bug; check `gen3_frlge_client.lua`.  
**FAIL:** `no_catch` fires after trainer battle → `isWildBattle()` bug; check `memory_gba.lua`.

---

## Test 4 — Full Event Detection (End-to-End)

**Script:** `lua/slink.lua` (or `lua/slink_gen3.lua` for Gen 3 only)  
**Emulators:** Either one.  
**Server required:** `python -m server.server --host 127.0.0.1 --port 54321`

All events are detected automatically and sent end-to-end to the server. Responses appear in the console. All event types are covered. Check the **status page** (`http://localhost:8080/`) in a browser alongside this test — it should update in real time.

### Events Detected Automatically

| Event | Trigger | Expected console |
|---|---|---|
| `hello` | TCP connect or reconnect | `AUTO hello → noop` — sends party snapshot, `has_pokeballs`, and `ball_count` |
| `area_enter` | Walk to a new mapped route | `AUTO area_enter:route_N → noop` |
| `capture (battle)` | Catch during battle (party not full) | `AUTO capture(battle):<key8> → noop` |
| `capture (box)` | Catch with party=6 (goes to PC box) | `AUTO capture(box):<key8> → noop` |
| `capture (gift)` | New party mon appears outside battle | `AUTO capture(gift):<key8> → noop` |
| `faint` | Party mon HP transitions 1+ → 0 | `AUTO faint:<key8>` |
| `no_catch` | Wild battle ends, no capture in 15-frame grace | `AUTO no_catch:route_N → noop` (includes wild mon's species_id and level) |
| `whiteout` | All living party mons reach HP=0 | `AUTO whiteout → noop` |
| `party_to_box` | Known party mon deposited to PC | `AUTO party_to_box:<key8> → noop` |
| `box_to_party` | Known PC mon withdrawn to party | `AUTO box_to_party:<key8> → noop` |
| `tick` | Every 60 frames — includes `ball_count` + party snapshot | `AUTO tick(auto) → noop` |
| `memorialize_done` | After `memorialize` write confirmed | `✓ memorialize: <key> → box13 sN` |
| `sync_retrieve_done` | After `party_mon` write confirmed (silent) | Silent — updates server's `party_keys` |
| `sync_retrieve_failed` | After `party_mon` fails (party full, no stats) | HUD: "⚠ Make room & retrieve [name] from PC" — server discards from `party_keys` |
| `stats_cache` | After `box_mon` write (silent) | Silent — caches stats for later `party_mon` restore |
| `quarantine (auto box_mon)` | Pending capture auto-deposited to PC | `↳ box_mon queued (quarantine): <key8>` — mon boxed until partner captures |
| `un-quarantine (party_mon)` | Link formed, pending capture returned to party | `↳ party_mon queued (un-quarantine): <key8>` — both mons retrieved |

### Nuzlocke Gate Behavior

The `nuzlocke_active` flag activates when `M.hasPokeballs()` returns true (reads the actual Pokéball bag pocket from RAM — offset varies by profile: `SB1+0x0430` vanilla, `SB1+0x0680` AP, fixed EWRAM `0x0203C354` for RR/CFRU). **Until then:**
- `no_catch` events are **not sent** to the server
- `resolved_areas` is not updated

**Verify:**
- Before getting Pokéballs: walk routes, start and end wild battles → no `no_catch` in console
- After Blue's sister gives Pokéballs on Route 1: `[T4] nuzlocke ACTIVE (pokeballs in bag)` appears in console
- Subsequent `no_catch` events fire normally

### Battle State Logging

| Log line | Meaning |
|---|---|
| `[battle] start  wild=true  area=route_N` | Wild battle started — box snapshotted if party=6 |
| `[battle] start  wild=false  area=...` | Trainer battle started — `no_catch` will NOT fire |
| `[battle] end  grace window started` | Battle ended — 15-frame window begins |

**CFRU Battle HP Cache Logging:**

| Log line | Meaning |
|---|---|
| `[battle] cache update: slot N hp=X→Y` | HP change detected in gBattleMons during battle |
| `[battle] wrote back cached HP/level to party struct` | Battle ended — cache values written to gPlayerParty |
| `[battle] cache cleared` | Cache reset (battle start or post-writeback) |

**CFRU Borrowed-Party Battle Logging:**

| Log line | Meaning |
|---|---|
| `[battle] BORROWED battle detected — party tracking frozen` | Poké Dude or mock battle started — party diff suppressed |
| `[battle] BORROWED ended — real party restored` | Borrowed battle ended — pre-battle party snapshot restored |

### Status Page Checks (http://localhost:8080/)

The status page uses **flicker-free DOM morphing** (`morphDOM()`) — sprites, HP bars, and table structure are preserved across auto-refreshes. Only changed text/values are patched in-place via `nodeValue` updates; `<img>` elements are never recreated (only `src`/`alt` updated if changed).

| What to verify | Expected |
|---|---|
| Player card header | Shows in-game trainer name (e.g. "RED") next to connection status; page title shows "Soul Link Tracker — \<variant\> — \<run name\>" |
| Gym badges | 8 badge icons per player — colored circle for earned badges, grey for unearned; supports out-of-order acquisition (AP bitmask) |
| Nuzlocke active badge | "Waiting for Pokéballs" until Pokéballs obtained; then "Nuzlocke active" |
| Current area | Updates to current route/map name on each `area_enter` |
| Pokéball count | Updates every ~1 s from `tick` events |
| Battle display | "⚔ IN BATTLE" panel with enemy party table appears **above** the player's party table (not below) — immediately visible without scrolling |
| Party table | Shows each party mon's nickname and species (e.g. "CHAR (Charmander)"), level, HP bar, gender symbol (♂/♀), **ability name**, and linked partner key with link status |
| Encounters table | Consolidated table showing all encounters with progress icons: ✅ (linked/alive), 💀 (dead/memorial), ⏳ (pending), ☠️ (dead zone). Each row: area name, Player A's mon (sprite/nickname/species/level), status icon, Player B's mon. Dead zones show the wild mon's species + level |
| PC Box section | Shows occupied slot counts and nicknames/species/**abilities** for all 13 active boxes, updated every ~5 s |
| Identity error | When wrong save connected: **red error banner** in player card with OT mismatch message |
| Auto-refresh stability | Sprites and HP bars do NOT flicker or reload on 5-second refresh — DOM morphing preserves elements |

### Negative Cases (events that must NOT fire)

| Scenario | Expected |
|---|---|
| Trainer battle ends | No `no_catch` fired |
| Second battle in same area (after capture or no_catch) | No second `no_catch` fired |
| Same mon HP stays at 0 across frames | `faint` fires once, not repeatedly |
| Whiteout while party is already all-zero | `whiteout` fires once |
| Ambiguous box diff (>1 new key) | `no_catch` suppressed; logged as ambiguous |
| `gBattleOutcome == CAUGHT` even if box scan failed | `no_catch` suppressed via outcome fallback |
| Wild battle before Pokéballs obtained | No `no_catch` fired |
| Faint before nuzlocke active | `faint` sent; server marks DEAD only if pair existed AND nuzlocke was active when the pair was created |
| Whiteout before nuzlocke active | `whiteout` sent; no force_faint commands (no dead pairs) |
| CFRU battle ends same frame as last faint | `faint` + `whiteout` both fire correctly — `battle_just_ended` gate captures final HP |
| Borrowed-party battle (Poké Dude / mock) | No false captures, no false faints — party tracking frozen; real party restored after battle |
| Tag battle with NPC partner | Normal tracking — NPC mons in separate battler slots; no party corruption |
| Capture in already-linked area | `force_faint` + `memorialize` queued — mon cannot be used |
| Capture in dead-zone area | `force_faint` + `memorialize` queued — mon cannot be used |
| BizHawk window resize during gameplay | No false `box_to_party` or `party_to_box` — 3-frame debounce filters glitches |
| Repel use (bag menu) | No false party events — `party_diff_ok` gate freezes detection during menus |
| `party_mon` with partner's party full | `sync_retrieve_failed` sent; no infinite retry loop; HUD notice shown |
| `party_mon` without cached stats | Fails closed — refuses to write; HUD notice shown; `sync_retrieve_failed` sent |
| New encounter HUD on gift area (oaks_lab, intro, gift_*) | HUD does NOT appear |
| Pre-save title screen / intro cutscene | No party/box data in tick/hello — only metadata sent |
| Safari Zone encounter while sync pending | No crash — fresh `isInOverworld()` check at execution point |
| Manual withdrawal of quarantined mon | `box_to_party` blocked — mon re-deposited with HUD warning |
| Link forms but both parties full | Both mons stay in box — HUD notification "★ Linked! Both players need party room to retrieve" shown |
| One player retrieves, partner fails | First player re-boxed to maintain sync (`sync_retrieve_failed` triggers re-box) |
| Wrong save connected (identity lock) | All events return `noop`; red HUD and status page banner; run state unchanged |
| Server down — BizHawk stutter | No stutter — non-blocking connect; reconnect backs off exponentially |

### Manual F-Keys

| Key | Action |
|---|---|
| F1 | `area_enter` — current area_id |
| F2 | `capture` — party slot 0 |
| F3 | `faint` — party slot 0 |
| F4 | `no_catch` — current area_id |
| F5 | `whiteout` |
| F6 | `safe` |
| F7 | `tick` (includes ball_count + party snapshot) |
| F8 | `party_to_box` — party slot 0 |
| F9 | Direct Lua write: move party slot 0 → Box 13 (no server) |

**PASS:** All event types fire correctly; negative cases are silent; `force_faint`, `memorialize`, `box_mon`, and `party_mon` commands dispatched when received; illegal captures (dead zone or extra capture in linked area) are force-fainted and sent to Box 13; status page gender symbols, abilities, and dead zone encounter species display correctly; party_mon fails gracefully on party-full or missing stats (no infinite loop); identity lock rejects wrong saves cleanly; borrowed-party battles (CFRU) produce no false events.  
**FAIL:** `NOT CONNECTED` in console → server not running or wrong host/port.  
**FAIL:** `no_catch` after successful catch → `resolved_areas` bug in `gen3_frlge_client.lua`.  
**FAIL:** `no_catch` fires on trainer battle → `isWildBattle()` bug in `memory_gba.lua`.  
**FAIL:** `Writes: OFF` → ROM validation failed; load a save first.  
**FAIL:** `no_catch` fires before Pokéballs obtained → `nuzlocke_active` gate bug in `gen3_frlge_client.lua`.  
**FAIL:** `party_mon failed: party full` loops endlessly → `exec_party_mon` retry bug.  
**FAIL:** Ability shows "Unknown" or 0 → check `BASESTATS_ADDR` in the ROM profile; run `lua/test_ability_diag.lua` to diagnose.  
**FAIL:** Wrong-save connection modifies state → identity lock bug in `server/state.py`.

---

## Alpha End-to-End (Steps 1–9)

**Script:** `lua/slink.lua` on **both** emulators.  
Set `SLINK_PLAYER = "a"` on FireRed, `SLINK_PLAYER = "b"` on LeafGreen (via `lua/slink_gen3.lua` or the downloaded launcher).  
**Server required:** `python -m server.server --host 127.0.0.1 --port 54321`  
**Status page:** Open `http://localhost:8080/` in a browser.

Run through the steps below **in order**. Each step depends on the previous.

### Step 1 — Connection

**Action:** Load both emulators with a save. Start the server.

| Check | Expected |
|---|---|
| Both consoles show `TCP: connected to 127.0.0.1:54321` | ✓ |
| Server console prints `[a] hello` and `[b] hello` | ✓ |
| `Validation: OK` and `Writes: ON` on both | ✓ |
| Status page shows both players "online" with trainer names | ✓ |

**Identity lock — first connection:** After the first hello with a non-empty party, `links.json` contains a `player_identity` entry with the OT ID and trainer name for each slot. This is automatic.

**Identity lock — wrong save test:**

| Action | Expected |
|---|---|
| Stop Player A's emulator. Load a **different** save file. Reload the script | ✓ |
| A console shows red HUD: "⚠ Wrong save! Expected [name] (OT: ...)" | ✓ |
| Status page: red error banner in A's player card | ✓ |
| All events from A return `noop` — no state changes | ✓ |
| Reload the correct save. Reload the script | Error clears; normal operation resumes |

**Reconnect stutter test:**

| Action | Expected |
|---|---|
| Stop the Python server. Observe BizHawk console | ✓ — reconnect messages appear |
| BizHawk emulation does NOT stutter or freeze | ✓ — non-blocking connect |
| Wait 30+ seconds | Backoff increases: 2s → 4s → 8s → 16s → 30s cap |
| Restart the server | Connection re-established within 1–2 seconds |

---

### Step 2 — Pokéball Gate

**Action:** Start on a fresh save (no Pokéballs yet). Walk to Route 22 (reachable before Route 1 Pokéball gift). Have a wild battle and run away.

| Check | Expected |
|---|---|
| No `nuzlocke ACTIVE` message | ✓ — gate hasn't fired |
| No `no_catch` sent | ✓ — gate suppresses it |
| Status page: "Waiting for Pokéballs" badge on both players | ✓ |

**Action:** Walk to Route 1 and receive Pokéballs from Blue's sister.

| Check | Expected |
|---|---|
| Console: `[T4] nuzlocke ACTIVE (pokeballs in bag)` | ✓ |
| Status page: "Nuzlocke active" badge appears | ✓ |

---

### Step 3 — Area Enter + Encounter HUD

**Action:** Walk onto a named route (e.g. Route 1) on both emulators.

| Check | Expected |
|---|---|
| Console: `AUTO area_enter:route_1 → noop` on both | ✓ |
| Server log: `[a] area_enter → 'route_1'` and `[b] area_enter → 'route_1'` | ✓ |
| Status page area field shows `route_1` for both players | ✓ |
| In-game HUD: "★ New encounter: Route 1" appears in green (~3 seconds) | ✓ |
| HUD does NOT appear for gift areas (oaks_lab, intro, etc.) | ✓ |
| HUD does NOT appear before `nuzlocke_active` (before Pokéballs obtained) | ✓ |
| HUD does NOT appear for already-resolved areas (revisiting Route 1 after catch/no_catch) | ✓ |

**Resolved areas on reconnect test:** After capturing on a route (so the area is resolved), close and reload the script in BizHawk (or disconnect/reconnect TCP). The `hello` response includes a `resolved_areas` command that seeds the Lua client's `resolved_areas` table. Verify:

| Check | Expected |
|---|---|
| After script reload, the "★ New encounter" HUD does NOT re-fire for already-resolved areas | ✓ |
| Console shows `resolved_areas` command received in hello response | ✓ |

---

### Step 4 — Capture Linking (happy path)

**Action:** Catch any wild Pokémon on Route 1 on **Player A's** emulator, then catch any on the same route on **Player B's** emulator.

| Check | Expected |
|---|---|
| After A catches: area state shows `pending_b` (waiting for B's trainer name) | ✓ |
| After A catches: A's mon is **quarantined** — auto-deposited to PC via `box_mon` | ✓ |
| A console: `↳ box_mon queued (quarantine): <key8>` | ✓ |
| A's quarantined mon is NOT in A's party (verify in party menu) | ✓ |
| After B catches: area state shows `linked` | ✓ |
| After B catches: both mons are **un-quarantined** — `party_mon` queued for both (if both have party room) | ✓ |
| `data/links.json` has one entry with `a.key`, `b.key`, `status: "alive"` | ✓ |
| Status page Encounters table shows the new pair with **both mons' nicknames, species, and gender symbols** (e.g. "PIDGEY ♂ (Pidgey) ↔ RATTATA ♀ (Rattata)") with a ✅ status icon | ✓ |
| Status page party table shows **ability names** for both mons (e.g. "Keen Eye", "Run Away") | ✓ |
| A second battle on the same route fires no `no_catch` | ✓ |

**Ability display checks:**

| Check | Expected |
|---|---|
| Party mons in status page show ability names (not "Unknown" or blank) | ✓ |
| PC box mons in status page show ability names | ✓ |
| During battle: enemy party table shows enemy ability names | ✓ |
| Ability names are correct for the species (verify against Bulbapedia or RR Pokédex) | ✓ |
| For AP ROMs: abilities display correctly (gBaseStats at `0x0825634C`) | ✓ |
| For RR/CFRU ROMs: abilities display correctly (gBaseStats via CFRU pointer) | ✓ |

**Quarantine behavior — reconnect test:**

| Action | Expected |
|---|---|
| A captures on a route (mon quarantined). Disconnect/reconnect A's client (`hello` sent with party snapshot) | If quarantined mon is in A's party snapshot, server re-quarantines it — `box_mon` queued again |
| Verify A's quarantined mon is deposited to PC after reconnect | ✓ |

**Quarantine behavior — manual withdrawal blocked:**

| Action | Expected |
|---|---|
| A captures on a route (mon quarantined). A manually withdraws the quarantined mon from PC | `box_to_party` blocked — mon re-deposited with HUD warning "⚠ Cannot use [name] until linked" |
| Verify mon returns to PC box | ✓ |

**Quarantine behavior — dead zone retirement:**

| Action | Expected |
|---|---|
| A captures on a route (mon quarantined). B sends `no_catch` for the same route (dead zone forms) | A's quarantined mon is force-fainted and memorialized directly from the box |
| `memorializeMon` searches both party and boxes 0-12 to find the mon | ✓ |

**Species lock — same-save duplicate test (requires `--species-lock`):**

| Action | Expected |
|---|---|
| Player A has an alive linked Pidgey from Route 1. Player A catches another Pidgey (or Pidgeotto/Pidgeot) on Route 2. | Capture is rejected — force-fainted; area stays pending for retry |
| Player A catches a non-duplicate species on Route 2 instead | Link forms normally |
| Player A's original Pidgey pair is dead/memorial. Player A catches a new Pidgey on Route 3 | Link forms — dead pairs don't block |

---

### Step 5 — Faint Propagation

**Action:** Let Player A's linked mon faint in battle. (Use Test 2's F1 to force-faint if needed.)

| Check | Expected |
|---|---|
| A console: `AUTO faint:<key>` | ✓ |
| Within ~100 ms (next tick): B's partner mon HP drops to 0 | ✓ |
| B console: `↳ DISPATCHED force_faint slot=N key=...` | ✓ |
| `data/links.json` shows `status: "dead"` for that pair | ✓ |
| Status page: link shows as dead (red); party table shows fainted mon in red | ✓ |

---

### Step 6 — Dead Zone

**Action:** On a **fresh route**, have Player A enter a wild battle and run away or KO. Then have Player B catch on that route.

| Check | Expected |
|---|---|
| After A's battle grace window: server log `no_catch → dead zone for <route>` | ✓ |
| Status page Encounters table: A's side shows the wild Pokémon's species + "(fled/KO)" (e.g. "Rattata *(fled/KO)*") with a ☠️ status icon | ✓ |
| When B catches: B's newly-caught mon immediately receives `force_faint` **and** `memorialize` | ✓ |
| B console: `↳ DISPATCHED force_faint` then `↳ memorialize queued` for that mon | ✓ |
| After safe state: `✓ memorialize: <key> → box13 sN` | B's illegal catch moved to memorial box |
| `data/links.json` area_states shows `"dead_zone"` for that route | ✓ |
| Status page Area States shows "dead zone" in red | ✓ |
| Status page Encounters table: both sides shown — A shows species (fled/KO), B shows "— no catch" (the display is NOT updated by B's illegal catch) | ✓ |

**Also verify — capture in already-linked area:**

| Action | Expected |
|---|---|
| On a route that already has a `linked` area state, catch a second mon | Console: `[T4] extra capture in already-linked area … retiring immediately` |
| `force_faint` + `memorialize` queued for the illegal catch | Mon is fainted and moved to Box 13 — it cannot be used |

---

### Step 7 — Party/Box Sync

**Prerequisites:** Steps 3–4 completed; at least one linked pair is alive and in both parties.

**How it works:** When Player A deposits a linked mon at the PC, the server automatically queues a `box_mon` command for Player B. On B's next tick, B's linked partner is deposited to B's box. The client sends a silent `stats_cache` event so the server records the stats. When A withdraws, the server queues `party_mon` for B — B's partner is restored with the correct stats (level, HP, moves). After retrieval, B's client sends a silent `sync_retrieve_done` event so the server keeps its `party_keys` accurate. The server does NOT add the partner's key to `party_keys` until `sync_retrieve_done` is confirmed — if retrieval fails (party full, no cached stats), the client sends `sync_retrieve_failed` instead, and the server removes the key. Conflicting commands (a `box_mon` that arrives while a `party_mon` is already pending for the same mon, or vice versa) are automatically cancelled — the most recent command wins.

**Quarantine and paired sync:** Unlinked captures are quarantined (auto-boxed) until the link forms. When a link forms, both mons are un-quarantined — but only if **both** players have `party_size < 6`. If either party is full, both mons stay in the box with a HUD notification ("★ Linked! Both players need party room to retrieve"). Manual withdrawal of a linked mon is blocked if the partner's `party_size >= 6` — the mon is re-deposited with a HUD warning. If one player's retrieval succeeds but the partner's fails (`sync_retrieve_failed`), the server re-boxes the first player's mon to maintain the invariant that both linked mons are always in the same place. `party_size` is tracked from `hello` (`len(party)`) and `tick` events with ~1s update frequency.

**Action:** Player A deposits their linked mon into the PC box.

| Check | Expected |
|---|---|
| A console: `AUTO party_to_box:<key8> → ...` | Server received deposit |
| B console: `↳ box_mon queued: <key8>` then `✓ box_mon: <key8> → box0 s0` | B's linked partner auto-deposited |

---

## Unit Tests (pytest — no emulator required)

```bash
pytest tests/unit/test_state.py -v          # 228 tests
pytest tests/unit/test_gen3_adapter.py -v   # 50 tests
pytest tests/unit/test_gen4_adapter.py -v   # 62 tests (incl. species/evo/gender data)
pytest tests/unit/test_gen1_adapter.py -v   # 78 tests
pytest tests/unit/test_gen2_adapter.py -v   # 127 tests
```

All tests use `tmp_path` + `monkeypatch` fixtures for isolated file I/O. No server, no emulator, no network.

### test_state.py — State Machine Tests (228 tests)

Covers the core `SoulLinkState` FSM in `server/state.py`. Key helper: `make_state_with_link()` creates a pre-linked pair with `pokeballs_obtained` active and party size 2.

| Category | Count | What's covered |
|---|---|---|
| Faint propagation | ~20 | Linked faint → partner force_faint, pre-nuzlocke immunity, whiteout |
| Encounter linking | ~25 | Area state transitions (UNSEEN→PENDING→LINKED), dead zones, gift areas |
| Party sync | ~20 | party_to_box → box_mon, box_to_party → party_mon, quarantine, paired sync |
| Link clause rules | ~30 | Species clause (evo families), gender clause (genderless edge cases), type clause, combined clauses |
| Player identity lock | ~15 | OT ID lock, wrong-save rejection, per-player independence |
| Shiny bonus pairs | ~15 | pending_bonus FIFO, pair formation, faint propagation, clause violations |
| Nature change (key_change) | ~10 | Key migration across links, pending captures, party keys, commands |
| Hello reconciliation | ~15 | Reconnect with hp=0, re-quarantine, re-queue memorials, resolved_areas |
| Save/load round-trip | ~5 | Persistence of all state fields through links.json |
| PC movement races | 4 | Triple swap, stale party_size, simultaneous deposits, queue depth |
| Reconnect half-complete | 4 | Mid-swap disconnect, pending memorials, party_keys reconciliation |
| Faint timing conflicts | 4 | Faint during box_mon/party_mon, simultaneous faints, post-retrieve faint |
| Party size accounting | 3 | Adjusted size with pending box_mons, tick updates, full-party block |
| Memorial done/failed | 3 | DEAD→MEMORIAL transition, failure handling, save/load round-trip |
| Bonus pair edge cases | 3 | Shiny faint before pairing, FIFO ordering, clause violation retry |
| Command queue ordering | 3 | Deposit→withdraw cancellation, mixed sync+HUD delivery |

### Desync Audit Findings (Gen 3)

A comprehensive audit of the Gen 3 sync codebase verified that all high-risk desync scenarios are mitigated. Summary of findings:

#### Confirmed Mitigations (no action needed)

| Risk | Mitigation |
|---|---|
| **HP resurrection during battle** | 5-layer defense: `force_fainted_keys` set, `pending_battle_faints` queue, `verify_party_fields` guard, battle HP cache writeback skip, battle-end clear |
| **Double-buffer identity confusion** | Independent `_ip_entry_pool` per buffer in `index_party()` — slots are never shared across buffers |
| **CFRU substruct corruption** | Snapshot-before + verify-after cycle with 8-frame retry window in `decryptSubstruct()` |
| **`party_size` lag causing false full-party** | `_linked_party_size()` subtracts pending `box_mon` commands (`adjusted_party_size`); reactive `sync_retrieve_failed` catches remaining edge cases |
| **Command loss on crash/disconnect** | Hello reconciliation re-queues memorials, re-quarantines pending captures, and re-propagates hp=0 faints from the party snapshot |
| **Borrowed-party battle pollution** | Two-layer detection: `isBorrowedBattle()` flag check + rolling gift capture buffer (3+ gifts in 45 frames triggers freeze); all party events gated on `not party_frozen` |
| **Nature change key split** | `otId+species+level+nickname` signature matching in Lua; server-side `_handle_key_change()` migrates key across all 7 state containers |

#### Known Residual Risks (extremely rare, accepted)

| Risk | Likelihood | Impact |
|---|---|---|
| Nature change signature collision (two mons with identical otId:species:level:nickname) | Near-zero (requires same OT, same species, same level, same nickname in party simultaneously) | No migration occurs — old key orphaned, new key treated as unknown. Manual fix via debug page. |
| `party_size` 1-tick stale window after a box action | Every box action (~1s window) | `sync_retrieve_failed` callback catches this reactively — partner's mon re-boxed if retrieval couldn't execute. No permanent desync. |
| B console: `party_to_box(stats_cache)` sent (silent) | B's stats cached on server for retrieval |
| Both mons absent from in-game party (verify in party menu) | ✓ |
| Status page party tables: both mons removed from party display | ✓ |

**Action:** Player A withdraws the linked mon back to the party.

| Check | Expected |
|---|---|
| A console: `AUTO box_to_party:<key8>` | Server received retrieval |
| B console: `↳ party_mon queued: <key8>` then `✓ party_mon: <key8> added to party (full heal)` | B's partner auto-retrieved at full HP |
| B's partner has correct level and maxHP in party menu (not level 0) | Stats were cached correctly |
| Status page party tables: both mons back in party | ✓ |

**Action (party full scenario):** With B's party at 6/6, have Player A withdraw a linked mon.

| Check | Expected |
|---|---|
| B console: `✗ party_mon: party full for <key8> — manual retrieval needed` | ✓ — does NOT loop endlessly |
| B in-game HUD: "⚠ Make room & retrieve [name]" (persistent) | ✓ |
| B console: `sync_retrieve_failed:<key8>` sent to server | ✓ |
| Server does NOT mark B's mon as in-party | ✓ — `party_keys` stays accurate |
| B manually withdraws from PC → `box_to_party` event fires normally | ✓ |

**Action (paired sync — partner full on withdraw):** With B's party at 6/6, have Player A withdraw a linked mon that A successfully retrieves.

| Check | Expected |
|---|---|
| A retrieves successfully; B's `sync_retrieve_failed` fires | ✓ |
| Server queues `box_mon` for A to re-box A's linked mon | ✓ — maintains paired sync invariant |
| A console: `↳ box_mon queued: <key8>` (re-box to maintain sync) | ✓ |
| Both mons end up in the box (neither in party) | ✓ |

**Action (paired sync — link forms, both parties full):** With both parties at 6/6, have A and B each capture on a new route (both captures go to box via quarantine or box capture).

| Check | Expected |
|---|---|
| Link forms — both mons stay in box (no `party_mon` queued) | ✓ — both `party_size >= 6` |
| HUD notification on both: "★ Linked! Both players need party room to retrieve" | ✓ |
| Neither mon appears in either player's party | ✓ |

**Action (paired sync — manual withdrawal blocked):** B's party is 6/6. A manually withdraws a linked mon from the PC.

| Check | Expected |
|---|---|
| Server detects B's `party_size >= 6` | ✓ |
| A's withdrawal is blocked — mon re-deposited with HUD warning | ✓ |
| A console: HUD "⚠ Cannot withdraw — partner's party is full" | ✓ |

**Action (box capture linking):** With both parties at 6/6, catch on the same route from both players.

| Check | Expected |
|---|---|
| A console: `AUTO capture(box):<key8>` with `in_box=true` and stats | ✓ |
| B console: `AUTO capture(box):<key8>` | Link forms |
| Neither mon added to either player's party (both stay in box) | ✓ |
| Status page: Encounters table shows the new pair with sprites and species | ✓ |
| No `box_mon` sync commands issued (both already in box) | ✓ |

---

### Step 8 — Whiteout

**Action:** Let **all** of Player A's party mons faint (full whiteout).

| Check | Expected |
|---|---|
| A console: `AUTO whiteout → ...` | ✓ |
| All of B's linked **party** mons receive `force_faint` | ✓ |
| Mons that were **boxed** on B's side are **not** force-fainted | ✓ |
| `memorialize` commands queued for all affected pairs | ✓ |

---

### Step 9 — Memorial Box

**Prerequisites:** Step 5 completed (at least one dead linked pair).

**How it works:** After a faint propagates, the server queues `memorialize` commands for both sides. On the next safe state (overworld, post-battle), each client moves the dead mon to Box 13 ("Box 14" in-game UI) using `M.memorializeMon()`, then sends a `memorialize_done` event. The server marks the pair `MEMORIAL` and writes `data/memorial.json` when both sides confirm.

**Action:** Let a linked mon faint in battle and wait for the battle to end.

| Check | Expected |
|---|---|
| A (faint side) console: `↳ memorialize queued: <key>` | ✓ |
| A console: `✓ memorialize: <key> → box13 sN` after safe state flush | ✓ |
| B (partner side) console: same queued line then confirm line | ✓ |
| `data/memorial.json` written with both mons' personality+otId, species, area | ✓ |
| `data/links.json` shows `status: "memorial"` for that pair | ✓ |
| Box 13 ("Box 14") in-game: both fainted mons appear in sequential slots | ✓ |
| Neither mon's source slot (party or box 0-12) remains | ✓ |

**Manual F9 test (single instance, no server):**

| Action | Expected |
|---|---|
| Press F9 with any mon in party slot 0 | `✓ memorialize: <key> → box13 s0` in console |
| Party slot 0 is cleared and compacted | Slot removed; party count decremented |
| Box 13 slot 0 contains the moved mon | Verify in BizHawk RAM watch |

---

## State Reset

To start a fresh run without restarting the server:

```
POST http://localhost:8080/api/reset
```

Or restart the server with `--reset`:

```bash
python -m server.server --host 127.0.0.1 --reset
```

This deletes `data/links.json` and clears all in-memory state. The Lua clients will reconnect and send `hello` events automatically.

---

## Known Limitations (not test failures)

| Behaviour | Reason | Impact |
|---|---|---|
| Overworld full-party wipe does not auto-whiteout | No game engine hook for this without a ROM patch | Server detects it via snapshot diff; player must manually visit Pokémon Center |
| Party HP values on status page not live | Server only receives HP on faint or hello — no per-frame HP stream | Shows 0 for fainted mons; non-zero for others reflects last-seen value, not current |
| Party levels are live | Level included in every tick event's party snapshot | Levels update at tick rate (~1 s) |
| Pokéball count updates at tick rate | Sent with each tick event | Brief lag between bag change and status page update (~1 s) |
| Party sync executes on next safe state tick | Sync writes deferred until fresh `isInOverworld()` check at execution point | Up to ~0.5 s delay after a party/box action before partner's game updates |
| Party sync may require manual PC action | `party_mon` fails closed if partner's party is full or stats are missing | Player sees persistent HUD notice and must manually withdraw from PC |
| Memorial box write requires safe state | `memorialize` command deferred until overworld | Brief delay between faint confirmation and Box 13 move; mon may still appear at 0 HP in party during that window |
| Dead zone encounter species missing for old sessions | `species_id`/`level` on `no_catch` events added in current alpha | Status page shows "— no catch" for encounters from sessions before this fix; new sessions always show species |
| AP starter location varies | AP randomized start puts player in random town | Starter capture uses `"intro"` area_id — both players link even if they start in different towns |
| AP party menu false battle trigger | `gBattleTypeFlags` stays stale in AP after battle | Three-condition `isInBattle()` check prevents this (gMain+0x038 + gBattleTypeFlags + gBattleOutcome) |
| Memorial box name | Box 13 is auto-renamed to "THE DEAD" at startup | Name write happens once, on first frame with writes enabled |
| Pre-save garbage data | During title screen/intro, RAM is uninitialized | Tick/hello events gate party data behind `gPlayerPartyCount` sanity check (0–6 range); no garbage on status page |
| Party event debounce | Memory reads can glitch during BizHawk window resize | 3-frame debounce on box_to_party and party_to_box; `party_diff_ok` gate freezes detection during menus |
| Gift area mapping | Eevee room corrected from `celadon_hotel` (10:19) to `celadon_condominiums` (10:11); area_map.json now has 150 entries | Regenerate with `python tools/gen_area_map.py` if editing area mappings |
| Dynamic gift area IDs | Gift captures in unmapped rooms use `gift_<mapGroup>_<mapNum>` (e.g. `gift_10_11`) | Prevents collisions when multiple gift locations shared the old generic `"gift"` area_id; server's `_is_gift_area()` matches both static names and `gift_*` prefix |
| Resolved areas on reconnect | Server sends `resolved_areas` command in hello response | Lua client seeds its `resolved_areas` table from this, preventing the "New Encounter" HUD from re-firing after script reload |
| Gift area `no_catch` protection | `no_catch` events in gift areas (static + dynamic `gift_*`) are silently ignored | Prevents false dead zones in gift/static encounter areas |
| Quarantine enforcement on reconnect | Server re-quarantines pending keys from hello party snapshot | Brief window (~1 tick) where quarantined mon may be in party before re-deposit |
| `party_size` tracking ~1s stale | Updated from tick events, not real-time | Reactive `sync_retrieve_failed` catches cases where stale data caused incorrect proactive decisions |
