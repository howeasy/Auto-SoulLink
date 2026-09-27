# SLink Live Testing Guide

Run these scripts in BizHawk's **Lua Console → Script → Open Script**.  
Output goes to the BizHawk **console panel**.  
Tests 1–3 are diagnostic; **Test 4 (`slink.lua` or `slink_gen3.lua`) is the production script** used for actual play. Run them in order when verifying a fresh install.

---

## Prerequisites

| Requirement | Detail |
|---|---|
| BizHawk 2.11+ | Both instances open, each with a FireRed or LeafGreen US 1.0 save loaded (vanilla, randomized, or Radical Red 4.1), or both with an Emerald (US) save loaded (Emerald pairs only with Emerald, never with FRLG/RR); `lua/slink.lua` refuses an older BizHawk on the Gen 3 route |
| LuaSocket DLL | Already committed at `lua/x64/socket-windows-5-4.dll` — nothing to install |
| Python server | `python -m server.server --host 127.0.0.1 --port 54321` (run from project root; needed from Test 4 onward — Tests 1-3 were the old client's and are removed) |
| Status page | `http://localhost:8080/` — flicker-free auto-refresh every 2 s (HTMX + idiomorph morph swap); shows player areas, gym badges, party, Pokéball counts, encounters table; battle display above party |
| Scripts in `lua/` | `slink.lua`, `gen3/`, `core/`, `connector.lua`, `socket.lua`, all files in `tests/` |
| Save states | Make a BizHawk save state before Tests 5 and 6 (they write RAM) |
| Missing inputs | The automated tests skip by name when a ROM, build or pret clone is absent, and fail when one is present but wrong — see [Absent input skips; present-but-wrong input fails](#absent-input-skips-present-but-wrong-input-fails) |

---

## Tests 1–3 — removed (old Gen 3 client)

`test_1_memory.lua`, `test_2_force_faint.lua` and `test_3_server.lua` drove the old Gen 3 client's `memory_gba.lua` and were deleted with it at C5-6 (they remain at tag `archive/gen3-old-client`). Their coverage is the headless `test_live_*` gates (`tests/live/test_lua_gates.py`) and the Gen 3 duo scenarios. Start at Test 4.

C5-6 deleted the whole old Gen 3 closure (`lua/clients/gen3_frlge_client.lua`, `lua/memory_gba.lua`,
`lua/mailbox.lua`, `lua/peer_ghost_npc.lua`). `lua/slink.lua` now routes every GBA cartridge through
`lua/gen3/entry.lua` → `lua/gen3/run.lua`, which builds `lua/gen3/client.lua` plus the
`lua/gen3/*.lua` modules over the shared `lua/core/session.lua` / `lua/core/deferred.lua` /
`lua/core/identity.lua`. The new client logs far less than the old one — no per-event `AUTO ...`
line, no `[T4]` tags — and almost all player-facing text goes through `lua/hud.lua`'s `hud.show()`/
`hud.prompt()`, driven by `hud_show`/`msgbox` commands the server sends (`server/state.py`).

---

## Test 4 — Live Play (End-to-End)

**Script:** `lua/slink.lua` (or `lua/slink_gen3.lua` for Gen 3 only)  
**Emulators:** Either one; both for the partner-visible checks below.  
**Server required:** `python -m server.server --host 127.0.0.1 --port 54321`

The BizHawk console prints one boot line on load: `[SLink-gen3] <pack>/<title> (<kind> by <admitted_by>) player a -> 127.0.0.1:54321 (rom <hash8>)`. After that it stays quiet — `lua/gen3/client.lua` over the shared `lua/core/session.lua` logs only on a state *change* (writes enabled/paused, a stuck hold, a refused write), never one line per event, and it makes no `console.*`/`print` calls at all for routine traffic. Watch the **status page** (`http://localhost:8080/`) alongside BizHawk — it is the primary way to see events land in real time.

### Events sent automatically

Every event carries `event`, `player`, `seq`. None of these print a console line on their own (`lua/gen3/client.lua` unless noted).

| Event | Trigger |
|---|---|
| `hello` | First connect or reconnect — carries party, PC boxes, area, `has_pokeballs`, `ball_count`, `ot_id`/`trainer_name` |
| `tick` | Every 30 frames (~0.5 s) while connected — area, `in_battle`, party, `ball_count`, badges |
| `area_enter` | Map (route/town/building) changes |
| `capture` | A new key appears in the party (wild catch or gift), or — if the party was full — exactly one new key appears in a PC box (`in_box=true`); more than one new boxed key in the same settle is ambiguous and reported as nothing |
| `faint` | A tracked party mon's HP goes from >0 to 0 |
| `no_catch` | A wild (non-trainer) battle ends with no new capture, the Pokéball gate is open, and the area isn't a gift area or already resolved |
| `whiteout` | Every living party mon reads HP 0 in the same settle |
| `party_to_box` | A tracked party key is later found in a PC box (a deposit) |
| `box_to_party` | A previously-boxed known key reappears in the party (a withdrawal) |
| `key_change` | An in-game NPC trade replaces a party record (`reason: "npc_trade"`) — never fired for the RR native link trade |
| `trainer_battle_start` | A trainer battle begins — carries `trainer_id`, plus `battle_id`/`session` when the client minted a battle-request nonce (needed for rival-swap) |
| `box_mon_failed`, `stats_cache`, `sync_retrieve_done`, `sync_retrieve_failed`, `memorialize_done`, `memorialize_failed` | Replies from the deferred command queue (`lua/core/deferred.lua`) after a server `box_mon`/`party_mon`/`memorialize` command runs at the next safe overworld checkpoint |

There is no `capture(battle)`/`capture(box)`/`capture(gift)` split — it is one `capture` event with `in_box`/`gift` fields.

### HUD text (`lua/hud.lua`: `hud.show` / `hud.prompt`)

| Text | Shown when |
|---|---|
| `** NEW ENCOUNTER **  <location>` (yellow) | `area_enter` into an unresolved route, Pokéball gate open, not a gift area |
| `WHITED OUT` (red) | `whiteout` |
| `Nuzlocke Start!` | `has_pokeballs` first latches true (not on a reconnect resume) |
| `!! <nickname> KO'd`, `!! <nickname> fainted`, `!! <nickname> BOOM!` (red) | The client wrote a battle faint, committed the Perish-Song active-battler faint, or committed Explode Mode's forced Explosion |
| `TRADE UNRESOLVED: <why>` (orange) | The native link-trade FSM parked without resolving |
| Any other `hud_show`/`msgbox` text | Server-driven (`server/state.py`) — wrong-save banner, dead-zone/linked/duplicate-capture notices, trade prompts, etc. Sent as plain text, not glyph-decorated |

A stuck command (a hold on the deferred queue or an in-battle write) is diagnosable **only from the BizHawk console** — one `held: ...` line when it first sticks or its reason changes (`lua/core/session.lua`), never on the HUD (owner ruling: no pending counters on-screen).

### Pokéball gate

`has_pokeballs` latches true the first time the Pokéball bag pocket reads a non-zero count (`lua/gen3/reads.lua`). Before that, `no_catch` is never sent and areas don't resolve. After Blue's sister hands over Pokéballs on Route 1, the HUD shows `Nuzlocke Start!` once and `no_catch` starts firing normally.

### Status page (http://localhost:8080/)

HTMX + idiomorph morph-swap auto-refresh — sprites and HP bars don't flicker or reload. Status markers are **inline SVG icons**, not emoji (`server/templates/_svg_icons.html`): crossed swords for "in battle", a skull for dead / dead-zone / whiteout / game-over, a check for linked/caught, an X for missing, a spark for shiny.

| What to verify | Expected |
|---|---|
| Player card | Trainer name once `hello` lands |
| Gym badges | 8 per player, earned vs. unearned, out-of-order acquisition supported |
| Nuzlocke badge | "Waiting for Pokéballs" until the gate latches, then "Nuzlocke active" (`server/board.py`) |
| Current area | Follows each `area_enter` |
| Pokéball count | Updates on `tick` |
| Battle panel | Shown above the party table while `in_battle` |
| Party table | Nickname, species, level, HP bar, gender, ability, link status |
| Pairs table | Sections for pending / linked / boxed / dead / dead-zone (`server/board.py`) |
| PC boxes | Occupied slots, nicknames/species/abilities |
| Identity error | Red banner in the player's card on a wrong-save mismatch |

### Fail conditions

| Symptom | Where to look |
|---|---|
| No `[SLink-gen3] .../... player ... -> host:port` boot line, or a `refused: ...` line instead | Server not running / wrong host:port, or `Entry.admit` refused the cartridge |
| `no_catch` after a successful catch | `settle_acquisitions` / `resolved_areas` in `lua/gen3/client.lua` |
| `no_catch` on a trainer battle | Wild/trainer detection in `lua/gen3/reads.lua` (`read_battle`) |
| `no_catch` before Pokéballs obtained | The `has_pokeballs` gate in `lua/gen3/client.lua` |
| A `party_mon`/`box_mon`/`memorialize` never lands | Console `held: ...` line for why; retry/failure rules in `lua/core/deferred.lua` |
| Ability shows "Unknown" or 0 | `BASESTATS_ADDR` in the ROM profile; `lua/tests/test_ability_diag.lua` |
| A wrong-save connection changes run state | Identity lock in `server/state.py` (`player_identity`) |

---

## Feature Checklist (End-to-End)

**Setup:** `lua/slink.lua` on **both** emulators, or `lua/slink_gen3.lua` with `SLINK_PLAYER` set to `"a"` / `"b"`. Start the server first. Keep `http://localhost:8080/` open alongside BizHawk.

### Connect, identity lock, reconnect

| Do | Expect |
|---|---|
| Load both emulators with a save, start the server | Each BizHawk console shows `[SLink] TCP connected to 127.0.0.1:54321`; server console logs a `hello` line per player; status page shows both online with trainer names |
| Stop Player A's emulator, load a **different** save, reload the script | A's console/HUD shows a red wrong-save banner; status page shows a red identity-error badge on A; every non-hello event from A is refused (server replies `noop`, `refused: "identity"`); run state (links, boxes) is untouched |
| Reload the correct save, reload the script | The banner clears and A resumes normally |
| Stop the Python server | BizHawk keeps running (connect is non-blocking); the connector retries with a backoff that starts near half a second and doubles up to a ~30 s cap |
| Restart the server | Reconnects within the current backoff window; console logs `[SLink] Reconnected to 127.0.0.1:54321` |

### Area enter + encounter HUD

Walk onto a new route on both emulators. Expect: both consoles' `tick`/`area_enter` reach the server (check `data/slink.log` or the status page's area field), the yellow `** NEW ENCOUNTER **` HUD banner fires once per player on a route not yet resolved (and never in a gift area, never before the Pokéball gate opens). Reload the script after a route resolves (capture or `no_catch`) — the `hello` reply seeds `resolved_areas`, and the banner does not re-fire for it.

### Link a capture

Catch on the same route on both players. Expect: after A's catch the area is `pending`; A's new mon is quarantined (auto-boxed) until the link forms — verify it is missing from A's party menu; after B catches, the area becomes `linked` and both mons return to their owners' parties (if both have room) or stay boxed with a HUD notice if either party is full; `data/links.json` gets one entry with both keys and `status: "alive"`; the status page's pairs table shows the pair with nicknames, species, gender and ability; a second battle on the same route no longer fires `no_catch`.

### Faint propagation

Force or take a faint on a linked mon. Expect: within one `tick` the partner's linked mon is force-fainted on the other machine (its HP is written to 0, or — where the pack supports it — the Perish-Song active-battler mechanism runs it out in-battle); `data/links.json` marks the pair `dead`; the status page shows the link and the fainted mon as dead.

### Dead zone

Have A run from/lose a wild battle on a **fresh** route (no capture) so `no_catch` fires and the area becomes a dead zone; then have B catch there. Expect: B's catch is immediately force-fainted and queued for the memorial box (it cannot be used); `data/links.json`'s `area_states` shows `dead_zone`; the pairs table shows the dead-zone row. Catching a **second** mon in an already-`linked` area behaves the same way — the extra catch is retired immediately.

### Party/box sync

With a linked pair alive in both parties: deposit A's mon at the PC. Expect: the server queues a box deposit for B's linked partner (auto-deposited on B's next safe tick); withdrawing A's mon queues a restore for B's partner (correct level/HP/moves, not level 0). If B's party is full, B's partner cannot be restored and B gets a persistent HUD notice; the server does not mark B's key as "in party" until B confirms, and reactively re-boxes A's mon if B's retrieval fails. Both mons staying boxed at 6/6 shows a HUD notice on both sides instead of a silent drop.

### Memorial box

After a faint propagates and the battle ends, both sides move the dead mon to the last PC box (Box 13 internally, "Box 14" in the in-game UI) on the next safe overworld state. `data/memorial.json` gets an entry for both mons once both sides confirm; `data/links.json` marks the pair `memorial`.

### Whiteout

Let all of Player A's party mons faint at once. Expect: B's **party** linked mons are force-fainted; anything of B's that was already boxed is left alone; memorialize is queued for every affected pair.

### Trade (Radical Red / companion patch only)

Vanilla and AP FireRed/LeafGreen have no native trade scene — server-driven trade prompts are cancelled outright on those foundations (`docs/gen3/PLAN.md`). Emerald has no companion patch either, so it cancels trade prompts the same way today; a vanilla trade duo (FR<->FR and E<->E) is planned but not yet built (`docs/gen3_emerald/REQUIREMENTS.md` ED-3). On a patched RR ROM, talking to the companion patch's Pokémon Center trade NPC (`drive_trade_npc` in `patch/src/handlers.c`; enabled while Overworld Presence is off, which it must be — see `docs/gen3/TODO.md`) sends `trade_request`; the resulting exchange runs entirely through the native mailbox (`lua/gen3/native.lua`) and ends in a `trade_done` event or a `TRADE UNRESOLVED: <why>` HUD notice if it parks. There is **no** automated trade duo on the rewritten client (the old client's `trade`/`infopanel` scenarios were retired and not rebuilt — `tools/e2e_duo.py` RR-only block comment); automated coverage is the native opcode gates (`tradescene`) and `native_absent_gen3`. This manual walkthrough is therefore the only end-to-end trade check.

---

## Test 5 — Rival Team Swap (Radical Red only, Companion Patch required)

**Scripts:** `lua/tests/test_live_enemyparty.lua` (in-battle `CREATE_MON` → enemy party + active-foe refresh) and `lua/tests/test_live_enemyparty_route.lua` (production `OP_SET_ENEMY_PARTY` routing — byte-for-byte blob faithfulness)  
**Emulators:** **One** is enough for the isolation scripts. **⚠ Requires the PATCHED ROM** (`patch/build/slink_RR.gba`) — the companion patch is a hard requirement for Rival Team Swap; the old `writeEnemyParty` RAM-poke fallback was removed. Writes only touch `gEnemyParty` (transient EWRAM), so no save corruption.

### Phase 0 — Isolation scripts (no server, no partner)

Both scripts are headless one-shot runs that write an incremental log ending in `RESULT: PASS|FAIL` to `patch/build/`, then exit. **Launch them with `tools/run_gate.py`, not by hand** — it exports `SLINK_ROOT` (BizHawk reports `debug.getinfo(...).source == "main"` for a `--lua=` script, so a gate cannot locate the repo on its own), copies the BizHawk config so back-to-back runs don't race, kills a hung emulator, and prints the verdict:

```bash
python tools/run_gate.py lua/tests/test_live_enemyparty.lua
```

Or run the whole set through pytest — `tests/live/test_lua_gates.py` walks every `test_live_*.lua` / `test_mailbox_*.lua`, picks the right ROM (patched, or the clean one for the negative controls), and skips any gate whose savestate is stale:

```bash
SLINK_LIVE=1 pytest tests/live -q
```

**`test_live_enemyparty.lua`** — loads an in-battle savestate (`slink_battle.State`), waits for the patch's mailbox beacon, then sends `OP_CREATE_MON` for Snorlax (143) and Diglett (50) at L40 into empty `gEnemyParty` slots with the enemy-count bump. Result file: `patch/build/enemyparty_result.txt`.

**Pass criteria:**
1. Beacon present (`MB.present()`); a missing beacon means an unpatched ROM.
2. Each created mon acks within 30 frames with `level == 40`, non-zero PID, and `maxhp > 0`.
3. Snorlax `maxhp` > Diglett `maxhp` (species-specific base stats reached the enemy side).
4. `gEnemyPartyCount` bumped to 3.

**`test_live_enemyparty_route.lua`** — savestate-free (pure EWRAM memcpy, validated from a fresh boot). Mirrors what the Gen 3 client's native layer (`lua/gen3/native.lua`) does on `replace_rival_team` with the patch present: stages three deterministic synthetic 100-byte party-mon blobs in the patch's blob buffer, then `MB.send(OP_SET_ENEMY_PARTY, {count})`. Result file: `patch/build/enemypartyroute_result.txt`.

**Pass criteria:**
1. Beacon appears during boot (~frame 13).
2. Each enemy slot reads back **byte-for-byte identical** to the staged blob (faithfulness — moves/IVs/EVs/PID/item preserved, which per-slot `CREATE_MON` cannot do).
3. `gEnemyPartyCount` set to the staged count; the first unused slot's `maxHP` is zeroed (the CFRU scan terminator).

### End-to-end with server + partner

Run the Feature Checklist setup (`lua/slink.lua` on both BizHawks, patched RR ROMs) with `python -m server.server --rival-team-swap`. Walk into any Rival (Terry) fight on either player. On `trainer_battle_start` the server checks the trainer id against the adapter's rival set and, if it matches and the partner has cached party blobs, queues `replace_rival_team` with the partner's cached blobs. The client (`lua/gen3/client.lua` `C.replace_rival_team`) stages it through the companion mailbox (`lua/gen3/native.lua`, `OP_SET_ENEMY_PARTY`) and acks `rival_team_replaced` with a species-id readback (or an `error` field on refusal — no crash either way). Server `data/slink.log` shows `[a] trainer_battle_start trainer_id=<id> is_rival=True session=... battle_id=...` followed by a `rival_team_replaced ack trainer_id=<id> species=[...]` line.

**Negative paths to verify:**
- **Unpatched ROM** → no `native` part is built at all (`pack=="gen3_rr"` with `artifact_kind=="companion"` is required), so the swap acks `rival_team_replaced` with `error="patch_required"`; no swap, no crash.
- Out of battle when the command arrives → ack with `error="not_in_battle"`.
- Stale/mismatched battle identity (a command queued for a battle that has since ended) → ack with `error="stale_battle_id"`.
- A failed ack shows a red `Rival Swap failed - see the SLink log` HUD banner and a `rival team swap FAILED: <error>` server log line. The banner is player-facing (HUD-PLAYER-FACING), so the `<error>` code stays in the log.
- Partner offline (B disconnected, no cached party blobs) → no swap; A fights the original rival. Server log: `auto-trigger skipped: partner 'b' has no cached party blobs`.
- Non-rival trainer → `is_rival=False`; nothing queued.
- Vanilla / AP ROM loaded → the adapter's rival-id set is empty, so it never matches (still logs `trainer_battle_start`, `is_rival=False`).
- BizHawk reset mid-battle after a swap → next battle init overwrites `gEnemyParty` itself; no save corruption (the write only ever touches transient EWRAM).

---

## Test 6 — Explode Mode (Radical Red only, RAM Write)

When `--explode-mode` is active, a linked partner's death sends `force_explode` instead of `force_faint`: if the surviving mon is the active battler in a singles battle and the pack supports the mechanism (`lua/gen3/client.lua`'s `explode_step`), its next action is coerced into Explosion instead of being silently zeroed. A boxed/benched mon, a pack without the required addresses, or doubles all fall back to a plain `force_faint`.

### Phase 0 — archived

The single-instance harness `test_force_explosion.lua` drove the old client (tag `archive/gen3-old-client`) and is archived in `lua/tests/archive/gen3_old_client/` (C5-6). The explode plumbing is gated headlessly by `test_live_forcemove.lua` and `test_live_explode_route.lua`.

### Phase 1 — End-to-end with server + partner

Run `python -m server.server --explode-mode` with both BizHawks connected (the Feature Checklist setup) on Radical Red. Mid-battle, let one linked mon faint. If its partner is the **active** battler in a singles fight, the client commits Explosion for it (HUD: `!! <nickname> BOOM!`, red) instead of writing HP 0 directly; a boxed/benched partner instead gets a plain `force_faint` (HUD: `!! <nickname> KO'd`). Omit `--explode-mode` → partner death always falls back to `force_faint`.

---

## Test layout

| Directory | Needs | Command |
|---|---|---|
| `tests/unit/` | nothing | `pytest tests/unit -q` |
| `tests/integration/` | a server subprocess on a loopback port | `pytest tests/integration -q` |
| `tests/live/` | EmuHawk + the patched ROM + a current savestate | `SLINK_LIVE=1 pytest tests/live -q` |
| `tests/e2e/` | TWO EmuHawk instances + a throwaway server | `SLINK_E2E=1 pytest tests/e2e -q` |

`pytest -q` alone runs everything; `live` and `e2e` skip unless their env var is set, and each
skips with a specific reason (missing EmuHawk, missing ROM, stale savestate) rather than hanging.
Markers `live` / `e2e` / `slow` are registered in `pytest.ini`, which also sets `--strict-markers`.

### Absent input skips; present-but-wrong input fails

One rule governs every test that needs an artifact this repo does not commit — a cartridge dump, a
decomp clone, a built ROM, a randomizer jar, a savestate:

- **The artifact is ABSENT** → `pytest.skip` with a reason that NAMES the artifact and its path.
  Never raise, and never raise at import: an exception while a module is being imported aborts
  collection for the WHOLE suite, so one unprovisioned input takes every other generation's tests
  down with it.
- **The artifact is PRESENT but wrong** — wrong commit, dirty tree, unpinned build, hash mismatch
  → **FAIL**. Loudly, by name. This is the half that matters: "absent" means this box cannot run
  the check, while "wrong" means the check ran against something nobody verified, and collapsing
  the two is how a tampered or stale artifact reads as green.

Consequences worth knowing before you write the skip:

- **Reason strings are load-bearing.** `tools/verify_gen1_release.py` (and its Gen 2/Gen 3
  siblings) treat a skip as a lane failure unless its reason matches an `ALLOWED_SKIPS` fragment.
  Reuse an existing fragment — `"<repo> not cloned: <path>"` — rather than inventing wording; a new
  fragment silently reds another generation's gate until its owner adds it.
- **Gen 1's own inputs stay unexcused** in the Gen 1 gate, by design: a missing Gen 1 dump or
  fixture IS a gate failure, because the gate's job is to refuse to certify from a box that cannot
  verify. Other generations' inputs are excused there, since they are out of that gate's scope.
- **A skip guard needs a revert-check.** Widen the caught exception and the test must go red. The
  Gen 2 lane found its first version of exactly such a test passing with a deliberately-broken
  handler, because the verifier called the loader more than once and a swallowed skip was masked by
  a fresh one from the next call.

Learned the hard way on 2026-09-26, when Gen 1, Gen 2 and Gen 3 first shared one unit suite: an
import-time raise on an uncloned decomp aborted all 14k tests, and stale local artifacts produced
27 failures that looked like a merge regression and were not. Re-verify every local artifact
against its pin file after any cross-lane merge — pins move when another lane rebuilds an overlay.

## Unit + integration tests (pytest — no emulator required)

```bash
pytest tests/unit tests/integration -q            # ~1370 tests, a few seconds
pytest tests/unit/test_state.py -q                # the SoulLinkState FSM
pytest tests/unit/test_routes_smoke.py -q         # every registered GET route renders
pytest tests/unit/test_explode_mode_gate.py -q    # explode-mode adapter gate + death predicate
pytest tests/unit/test_overlay_catalog.py -q      # catalogue slugs vs real routes
pytest tests/unit/test_backup_rotation.py -q      # rolling backup slots
pytest tests/unit/test_manager_spawn_flags.py -q  # registry keys reach the server CLI
pytest tests/unit/test_gen{1,2,3,4,5}_adapter.py -q
```

`tests/conftest.py` repoints `DATA_DIR` / `LINKS_PATH` / `MEMORIAL_PATH` at a per-test tmp dir for
**every** test, so a test cannot write over live run state (three used to write over
`data/memorial.json`). No server, no emulator, no network.

### test_state.py — State Machine Tests (318 tests)

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
| Explode Mode | 4 | Default-off, save/load round-trip, off → force_faint, on → force_explode |
| PC movement races | 4 | Triple swap, stale party_size, simultaneous deposits, queue depth |
| Reconnect half-complete | 4 | Mid-swap disconnect, pending memorials, party_keys reconciliation |
| Faint timing conflicts | 4 | Faint during box_mon/party_mon, simultaneous faints, post-retrieve faint |
| Party size accounting | 3 | Adjusted size with pending box_mons, tick updates, full-party block |
| Memorial done/failed | 3 | DEAD→MEMORIAL transition, failure handling, save/load round-trip |
| Bonus pair edge cases | 3 | Shiny faint before pairing, FIFO ordering, clause violation retry |
| Command queue ordering | 3 | Deposit→withdraw cancellation, mixed sync+HUD delivery |

> Rival Team Swap state coverage lives in `test_state_rival_battle_start.py` (auto-trigger matrix, `queue_rival_team_swap`, `rival_team_replaced` ack) and `test_state_party_blob_cache.py` (`blob_hex` ingest + validation).

## Automated Two-Instance E2E (Gen 3, companion patch)

`tools/e2e_duo.py` runs a throwaway SLink server plus **two** concurrent headless EmuHawk instances (players a/b, both on the patched ROM `patch/build/slink_RR.gba`, savestates from the same save with instance B's party OTIDs mutated pre-hello to avoid key collisions), orchestrates a scenario via the server's debug HTTP API, and waits for both instances' result files (`patch/build/e2e_<scenario>_{a,b}_result.txt`, final line `RESULT: PASS|FAIL`):

```bash
python tools/e2e_duo.py --scenario faint      # one scenario
python tools/e2e_duo.py --scenario all        # all six that apply to the default game
python tools/e2e_duo.py --list                # print exactly what `all` would run, then exit
```

`--scenario all` means "all scenarios that apply to `--game`", not "every key in `SCENARIOS`" —
the dict now holds Gen 1 and Gen 2 entries too. `scenarios_for()` in `tools/e2e_duo.py` is the
single source of truth for that question (a scenario with no `games` key applies to every title),
and `tests/e2e/test_duo.py` imports it rather than hand-rolling a second copy — the two answers
had drifted apart when it did. `all` **names** what it filtered out rather than silently
narrowing, because "all passed" over an empty selection is the worst way to report no coverage.

Scenarios: `faint`, `boxsync`, `trade`, `ghost` (runs with `--overworld-presence`), `explode` (runs with `--explode-mode`), `infopanel` (three injected pairs, then drives the native SOULLINK menu end to end: the `link_panel` payload crosses the wire, renders as pairs, opens from the START menu, pages on A and closes on B). Each instance loads a generated stub (`patch/build/duo_{a,b}.lua`) that runs the **real production client** plus a scenario coroutine from `lua/tests/duo/`. Windows-only; needs `E:/Howard/Bizhawk` and the patched ROM.

The pytest wrapper `tests/e2e/test_duo.py` parametrizes the same six scenarios (it derives them from `scenarios_for("gen3_rr")`, so the list cannot drift from the runner's) but is skipped unless explicitly requested (each takes minutes and spawns EmuHawk twice):

```bash
SLINK_E2E=1 pytest tests/e2e/test_duo.py -q   # Gen 3 only; `tests/e2e/` also picks up Gen 1 + Gen 2
```

### Desync safeguards (Gen 3)

What the current client and server do about the same handful of failure modes the old client's audit covered. Mechanisms changed with the rewrite; the risks did not.

| Risk | Current mitigation |
|---|---|
| A battle write to HP being undone by the engine's own next `datahpupdate`, or read back as a fresh faint | `battle_write` (`lua/gen3/client.lua`) holds an active battler's write until it switches out or the battle ends rather than poking HP mid-turn; `mark_commanded`/`st.commanded` mark a key as "we just zeroed this" so the client's own write is never re-reported as an observed faint (`observe_hp`) |
| A corrupt or mid-write party/box record being trusted | Non-RR (FR/LG) records carry a `BoxPokemon` checksum; `boxes.lua` refuses a deposit/withdraw/memorialize when `checksum_ok ~= true` rather than risk a wrong decode. RR/CFRU records skip that checksum by design (`reads.lua`) and are not checked this way |
| `party_size` lag causing a false "party full" | The server subtracts commands it has already queued (pending `box_mon`) from the count it uses to decide party room; `sync_retrieve_failed` reactively catches whatever a stale count let through (re-boxes the partner's mon) |
| Command loss on crash/disconnect | On `hello`, the server re-quarantines pending unlinked captures still sitting in the reported party and re-propagates any HP-0 mon it hadn't already marked dead (`server/state.py`) |
| A borrowed party in RAM (RR multi/tag battles copy a partner's party in) polluting capture/faint/PC detection | `update_frozen` (`lua/gen3/client.lua`) checks whether the current party shares any key with the pre-battle snapshot; no overlap freezes all party-diff reducers (`st.frozen`) until the real party returns or the battle ends. Held battle writes are kept, not dropped, across the freeze |
| A key split by an in-game NPC trade (nature/species changes but the record is "the same mon") | `lua/core/identity.lua` matches the new record against nickname bytes + move IDs frozen at the trade; an ambiguous or lost match is latched, never silently guessed. Server-side, `_handle_key_change` (`server/state.py`) migrates the key across every state container that references it |

**Known residual risk:** an in-game trade signature collision (two party mons with identical nickname bytes and move IDs at the moment of the trade) is not distinguishable — the identity module latches it as ambiguous, the old key is orphaned, and the new key is treated as unknown until fixed manually.

---

## Automated Game Boy Verification — Gen 1 and Gen 2 (no manual steps, no patch)

Everything above for Gen 3 is a human clicking through BizHawk. The Game Boy generations are
not — there is nothing to run by hand.

```bash
SLINK_LIVE=1 pytest tests/live/test_gen1_gates.py -q   # 5 cases: patch + menu-row + the randomized panel
python tools/verify_gen1_release.py                    # ALL of it, fail-closed (a skip is a failure)
SLINK_LIVE=1 pytest tests/live/test_gen2_new_gates.py tests/live/test_gen2_frame_align.py tests/live/test_gen2_write_windows.py -q   # inspect, frame-align, write windows
SLINK_E2E=1  pytest tests/e2e/test_duo_gen1_new.py -q  # 18 cases: 9 scenarios × 2 pairings
SLINK_E2E=1  pytest tests/e2e/test_duo_gen2_new.py -q  # link scenarios, Crystal/Gold/Silver pairings
```

The same runs can be driven directly. `--scenario all` is filtered by `--game`, so it will not
try to run Gen 3's savestate scenarios on a Game Boy cartridge — check what you are about to get
with `--list` first, and note that a single scenario that does not apply fails immediately with
the reason rather than after two emulators have booted:

```bash
python tools/e2e_duo.py --game gen2_new --list          # link, gen2_faint
python tools/e2e_duo.py --game gen2_new --scenario link
python tools/e2e_duo.py --game gen1_new --scenario all
```

### Gen 1 gates

`tests/live/test_gen1_gates.py` — each boots a fixture, asserts against the running game, and
writes `RESULT: PASS|FAIL`:

| Gate | Runs on | Covers |
|---|---|---|
| `test_gen1_patch_gate.lua` | red, blue (patched) | the companion patch's VBlank hook and mailbox, and that it does **not** reach `PlaySound` — see [patch/gen1/README.md](../patch/gen1/README.md) |
| `test_gen1_menu_row_gate.lua` | red, blue (patched) | the START-menu SLINK row and the panel it opens: the row draws and is reachable, the client's staged rows are what appears, **A turns to page 2**, **B closes**, EXIT keeps its original index, and the player can still walk |
| the panel on a randomized cartridge | red (randomized + injected) | the structural injector's only real question — a ROM that patches "successfully" and then does not boot is a failure no hash comparison can see, so the whole panel gate runs on one |

The pre-rewrite cartridge gates (memory, writes, box round trip, evolution, stat rebuild) and
the Archipelago gate were retired with their Lua in Phase 8. What they covered is carried by
`tests/live/test_gen1_new_gates.py`, `test_gen1_trade_gates.py` and the duo pairs, which are
parametrised over all three cartridges for the same reason those were: **Yellow shifts nearly
every WRAM address by −1**, so a Red-only run would never exercise the profile most likely to
be wrong.

### Gen 2 gates

Three files, one per concern, each parametrised over the titles with a qualified fixture
(Crystal and Gold today; Silver shares Gold's receipt, O-23):

| Gate | Runs | Covers |
|---|---|---|
| `tests/live/test_gen2_new_gates.py` (`lua/tests/gen2_inspect_gate.lua`) | per title, warm boot | party/box/name decode (R-1) cross-checked against `server/adapters/gen2_codec.py`, and an independent stat recomputation (R-2) |
| `tests/live/test_gen2_frame_align.py` (`lua/tests/gen2_frame_align.lua`) | per title, battle fixture | the engine-hook sites in `engine_signals.json` and frame-alignment (route to a wild encounter, catch, native save) |
| `tests/live/test_gen2_write_windows.py` (`lua/tests/gen2_write_windows.lua`) | per title, town + battle fixtures | write-window liveness and persistence: party write, box deposit, native save/reload, a refused mid-battle write |

Archipelago Crystal is refused outright (O-25, `docs/gen2/REVIEW_RECORD.md`), not gated.

Every address in the Gen 2 profile had already been checked against pret. What that cannot see is
whether the numbers mean anything on a running cartridge: a correct address read through the
wrong *domain*, or a struct offset applied to the wrong base, still returns plausible-looking
bytes. That gap is where every bug Gen 1's live bring-up found was hiding, and Gen 2's was no
different — Gold/Silver/AP Crystal routing to the Gen 3 adapter, `party_blob_size()` inheriting
`0`, no `stats_offset` so every deposit dropped the stat block, Apricorn ball IDs pointing at
SUN_STONE and friends, and a box HP read landing two bytes past the end of the 32-byte slot.
`pytest` was green throughout.

### Duo scenarios

Two emulators, a real server, the real production client on both sides. `lua/tests/duo/` splits
by what is actually shared:

| Files | Used by | Scenarios |
|---|---|---|
| `duo_gen2_main.lua`, `scenario_gen2_{link,faint}.lua` | Gen 2 (Crystal/Gold/Silver) | `link`, `gen2_faint` |
| `duo_gen1_main.lua`, `scenarios.<name>()` (no prefix lookup) | Gen 1 (rewritten client) | 18 `gen1_new` scenarios — `link_new`, `deadzone_new`, `linked_faint_bench_new`, `linked_faint_active_new`, `reconnect_new`, `ball_gate_new`, `trade_new`, `soft_reset_new`, `trade_decline_new`, `explode_new`, `pc_ops_new`, `changebox_new`, `whiteout_new`, `type_clause_new`, `species_clause_new`, `poison_new`, `rival_swap_new`, `admit_randomized_new` |

The old `scenario_gen1_{whiteout,playthrough,deadzone,dupes,rivalswap,explode_g1}.lua` prefix
files and the `gen1`/`gen1_yellow` duo titles they drove no longer exist — deleted in the
harness deletion sweep (`2395145`/`832d499`), separately from the legacy client's own deletion
(`21ff0d7`). The legacy Gen 2 duo chain (`duo_gb_main.lua`, `scenario_gb_{faint,boxsync,
memorialize}.lua`, `gatelib.lua`) is likewise retired, replaced by `duo_gen2_main.lua` above.

**Gen 1** runs all eighteen `gen1_new` scenarios, Red as player A against Blue as player B —
there is no Yellow pairing in this harness (Yellow's −1 WRAM shift is instead exercised by the
non-duo `tests/live/test_gen1_new_gates.py`, which runs on all three cartridges individually).
Unlike Gen 3, none of this needs a patched ROM for the rules themselves — Gen 1's enemy party is
plaintext, so the rival swap and Explode Mode run on stock cartridges (the duo harness still
boots the companion-patched builds by default; `trade_new`/`trade_decline_new` use the
trade-carrying build for the SLINK TRADE receptionist).

**Gen 2** runs three, and the choice is deliberate rather than "what happened to work":

| Scenario | Why it is the one that matters |
|---|---|
| `faint` | the core Soul Link rule. One linked mon dies; the partner's must die on the other machine, through the real server |
| `boxsync` | party sync with **nothing injected** — A deposits its half and the server must mirror `box_mon` to B, so a broken rule cannot be masked by the harness doing the work itself. Exercises the 32-byte box struct with no HP field and a withdraw that needs the server's cached stats block |
| `memorialize` | both halves die and the pair is buried in **Box 14** (`sBox14`, flat CartRAM `0x79E0`), which lives outside Gen 2's save checksum |

**Not run on Gen 2, and stated rather than silently absent:** `playthrough`, `deadzone` and
`dupes`. Those need tall grass, and Gen 2's fixture parks indoors (see Fixtures below). The rules
they cover — encounter linking, the dead zone, the species clause — are enforced server-side and
are generation-independent, and Gen 1 runs all three. A Gen 2 grass fixture would buy a second
copy of coverage that already exists.

**Two Crystals share one cartridge dump.** BizHawk names a SaveRAM file from its own gamedb
entry, keyed on ROM hash rather than the path launched, so two instances of one dump resolve to a
single file and stamp on each other. Gen 1 sidesteps that by pairing Red with Blue — a constraint
on which cartridges can be tested together, not a fix. `write_run_config(saveram_dir=…)` gives
each instance its own directory, and since there is exactly one Crystal dump, that is the only
reason this pairing is possible at all.

### Fixtures

Committed, both generations:

| Fixture | Rebuild |
|---|---|
| `tests/fixtures/gen1/{red,blue,yellow}_{town,battle}.SaveRAM` | `python tools/gen1_playthrough.py --rom red --target town` |
| `tests/fixtures/gen2/{crystal,gold,silver}_{town,battle}.SaveRAM` | no one-shot CLI today. `tools/gen2_playthrough.py` (the old single-title, town-only builder) is retired along with the legacy duo chain; `tools/gen2_fixtures.py` is the read-only plan/qualification side (`fixture_manifest`, `run_play`, `qualify`) that a played-and-qualified rebuild is composed from, orchestrated per session through `tools/run_gb_gate.py` |

These are **battery saves, not savestates**. A `.SaveRAM` is plain SRAM and is not
version-locked, so unlike the Gen 3 `.State` files they never rot when BizHawk is upgraded —
`tools/mkstates.py` exists precisely because the Gen 3 ones do.

Gen 1 has two targets because the overworld gates need encounter-free ground (a town) and the
battle gates need tall grass. **Gen 2 has only `town`**: New Bark Town's west exit is
script-locked until Elm hands over a starter, so the bootstrapper cannot reach grass at all.
Everything Gen 2 does not test traces back to that one fact.

Every gate skips — never hangs — when EmuHawk, a cartridge dump (gitignored) or a fixture is
missing.

---

## The Gen 1 release gate — a skip is a failure

`python tools/verify_gen1_release.py` runs seven lanes in one command and refuses to call a
lane that did not RUN a lane that PASSED.

That rule is not pedantry. This generation kept shipping green suites that were not running:
fifteen randomized-ROM proofs disabled by a missing UPR jar, nine duo scenarios disabled by an
unset `SLINK_E2E`, three more disabled by a code comment that turned out to be false, and
seven encounter areas dropped by a test filtering on exact method names. Every one of those
looked like a pass.

So skips, xfails, xpasses, deselections and errors all fail the gate. Ten skips are allowed,
each argued for **by name** in `ALLOWED_SKIPS` with its reason — Gen 2 decomps, template
partials, an optional overlay, and the deferred Archipelago ROMs. Anything not on that list
fails and is printed.

| Lane | What it proves |
|---|---|
| `unit` | the source oracles, the rules, and every table generated from the decomps |
| `rom-layout` | every flat ROM offset and companion-patch span, against the real dumps |
| `lua-parse` | every Lua file parses under the runtime the clients actually use |
| `patch-build` | the clean dumps still hold what the manifest expects to displace |
| `live-gates` | real engine behaviour on real cartridges, including the panel on a randomized+injected ROM |
| `duo-pairs` | every scenario on both pairings, through the real server |

`--quick` stops before the emulator lanes and says plainly that its result is not a release
verdict. `--list` shows the lanes.

**Give it the machine.** The emulator lanes wait on real frame counts, so running anything
heavy alongside them does not merely slow the gate down — it fails it. A `deadzone` run that
finishes in 65 seconds idle has been observed timing out at its 1500-second budget with a
unit-test run competing for the same cores. That is the emulator being starved, not a defect,
and the gate cannot tell the two apart.

There is a second verifier the gate calls directly: `tools/verify_gen1_rom_layout.py`. It
runs 29 checks across all three dumps, and a ROM that is absent is reported rather than
counted as a pass.

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
| Pokéball count updates at tick rate | Sent with each tick event | Brief lag between bag change and status page update (~1 s) |
| Party sync executes on next safe state tick (**unpatched ROMs** — patched ROMs run box/party sync natively via the companion patch's `DEPOSIT_MON`/`WITHDRAW_MON` opcodes) | Sync writes deferred until fresh `isInOverworld()` check at execution point | Up to ~0.5 s delay after a party/box action before partner's game updates |
| Party sync may require manual PC action | `party_mon` fails closed if partner's party is full or stats are missing | Player sees persistent HUD notice and must manually withdraw from PC |
| Memorial box write requires safe state (**unpatched ROMs** — patched ROMs memorialize natively via the companion patch's `MEMORIALIZE` opcode) | `memorialize` command deferred until overworld | Brief delay between faint confirmation and Box 13 move; mon may still appear at 0 HP in party during that window |
| AP starter location varies | AP randomized start puts player in random town | Starter capture uses `"intro"` area_id — both players link even if they start in different towns |
| Quarantine enforcement on reconnect | Server re-quarantines pending keys from hello party snapshot | Brief window (~1 tick) where quarantined mon may be in party before re-deposit |
| `party_size` tracking ~1s stale | Updated from tick events, not real-time | Reactive `sync_retrieve_failed` catches cases where stale data caused incorrect proactive decisions |

### Gen 1 specifically

| Behaviour | Reason | Impact |
|---|---|---|
| Live play covers Route 1 only | The scripted warp is undrivable from Lua — `hWarpDestinationMap` at `$FF81` is shared HRAM the renderer overwrites within the frame (measured three ways before the probe was retired) — and the fly warp reaches thirteen destinations, two with encounters | The other 38 areas rest on the generated oracle and the ROM scanner, which agree via two independent paths. Area *resolution* elsewhere is untested by play |
| No fishing rod has ever been cast in-engine | Rods are scanned from ROM on all three titles, including Yellow's distinct super-rod format, but never used | A rod encounter's area resolution is unproven live |
| Stat rebuild has no stat-exp coverage on hardware | Every fixture is a level-5 mon that has never fought, so `ceil(sqrt(stat_exp))` is always 0 | The formula is verified in Python against `CalcStat` over levels 1-100 and the stat-exp boundaries; what is untested live is the Lua reading a trained mon's bytes |
| The memorial box IS Box 12 | Gen 1 has no spare box — SRAM `0x75EA` decodes to exactly `sBox12` | Anything you ever stored there reads as contamination and logs an advisory warning (deduped per key). Nothing is corrupted; the checks do not act on it |
| Whiteout and the gender/type clauses are injected, not played | The duo scenarios set the condition rather than losing a real battle into it | The rules are unit-tested and generation-independent; what is unproven is the client noticing the real engine transition |
| Externally-randomized ROMs have no provenance tier | There is no import flow; a run with no `rom_contract.json` adopts client-reported tables unlabelled | A Manager-built pair is fully verified. An imported ROM is trusted structurally with nothing saying so in the UI |
| `blue --target battle` cannot rebuild its fixture | The certification's Right leg moves 10 → 11 and the return never completes — `tiles_moved=1`, nothing blocking, reproducible. Red and Yellow certify and return on the same tile of the same map | The committed `blue_battle.SaveRAM` is correct and verified; it just has to be rebuilt from Red or Yellow's side |

