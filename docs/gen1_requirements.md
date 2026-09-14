# Gen 1 release requirements

This is the release contract for Pokémon Red/Blue/Yellow (US). A row is **done** only when it
carries a SOURCE proof (pret citation or generated-from-pret data) **and** a PHYSICAL proof
(real cartridge in BizHawk, judged by an oracle that is not the code under test). MODEL
evidence (lupa/pytest against fakes) is recorded but never closes a row on its own. The
runner is `python tools/verify_gen1_release.py`; a lane that did not run did not pass.

Nothing in the pre-rewrite Gen 1 code, data, fixtures, tests or docs counts as evidence.
Where this file and `docs/REFERENCE.md` disagree, this file wins until REFERENCE is regenerated
from it in Phase 8.

## Pins

| What | Value |
|---|---|
| pret/pokered | `405b6246372d7e5a2cb029cbb65219b13286b8c9` (`.cache/pret/pokered`, `pokered.sym`/`pokeblue.sym` built from it) |
| pret/pokeyellow | `0a08515` (`.cache/pret/pokeyellow`, `pokeyellow.sym`) |
| Archipelago fork | Alchav `pokered` (`.cache/pret/alchav_pokered`) — profile generation only in this release |
| Clean ROM SHA-1 | Red `ea9bcae617fdf159b045185467ae58b2e4a48b9a`, Blue `d7037c83e1ae5b39bde3c30787637ba1d4c48ce2`, Yellow `cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1` (`data/pret_rom_syms.json`) |
| Emulator | BizHawk 2.11.1 (Gambatte core); inside `event.on_bus_exec` `emu.framecount()` equals the frame the step was armed for |
| Assembler | RGBDS v1.0.1 (`tools/build_pret_syms.py`) |
| Wire contract | `docs/protocol.md` (extracted from the Gen 3 client + `server/state.py`) |
| Engine sites | `docs/gen1_engine_sites.md` + `data/games/gen1_rby/engine_signals.json` (expected bytes per clean ROM) |

## Oracles (what "independent" means here)

- **ENGINE** — a `bus_exec` hook at a pret routine fired (or did not), with expected bytes verified at load.
- **PYDEC** — `server/adapters/gen1_codec.py` decodes the same raw WRAM/SRAM bytes; Lua and Python must agree.
- **GAME** — the game itself: `TryLoadSaveFile` returns 2 after our SRAM write; the party menu tilemap shows `FNT`/level/HP; the Mart/PC/receptionist screen shows the expected text.
- **SERVER** — `links.json` / server status, read by pytest, not by the client.
- **CONTROL** — a known-positive control: recompute a value two ways and require equality (stat rebuild from DVs).

## Status legend

`S` SOURCE, `M` MODEL, `P` PHYSICAL. `·` = not yet, `✓` = done with receipt path.

Audit 2026-09-14 (HEAD 48f09ef): 3 cells corrected — S-4 M downgraded (poison leg untested), C-0 M and C-4 M now name their tests. Two artefacts the audit could not fix in place: C-0's requirement text named `tests/unit/test_protocol_conformance.py`, which does not exist — **fixed in the C-0 row on 2026-09-14** (the work lives in `test_protocol_schema.py` + `test_gen1_client.py`) — and three sub-clauses no unit test covers — S-2's ball-thrown detection, S-5's "SLINK trade emits no `key_change`", S-7's CONTINUE/New-Game distinction. Update 2026-09-14 (HEAD 1a5941f): D-1/D-3 PHYSICAL from the duo harness; W-6/R-4 reworded to pause-not-drop after DUO-1's receipts showed a revoke inside the AskName window; S-2/S-5/S-7 downgraded under the strict rule. Update 2026-09-14 (HEAD 3650ace): T-2 PHYSICAL, T-1 ◐ (one Center) from the live receptionist gate; lane live-trade-gates green (2 passed). Update (HEAD e7c93e3+): T-3/T-4 PHYSICAL from `trade_new` (first live run PASS a+b); receipts for D-1/D-3/T-1..T-4 are committed under tests/fixtures/gen1/receipts/. Update (HEAD be88062): receipts mined for S-2, S-8, D-8, D-9, W-1, C-4 (◐ where the client's own reads are the only readback; PYDEC card open).

---

## F — Facts (no emulator; lanes 1–5 of the runner)

| id | Requirement | SOURCE | Oracle | S | M | P |
|---|---|---|---|---|---|---|
| F-1 | Every address in the generated profile names a pret symbol; R/B/Y differ exactly where pret differs (Yellow −1 WRAM shift) | `tools/verify_profile_addresses.py` resolves 100% | n/a | ✓ `test_gen1_profile.py` | ✓ | — |
| F-2 | Every hook site's expected bytes are present in each clean ROM at bank:addr | `engine_signals.json` + `tools/verify_gen1_rom_layout.py` | lane 2 vs the three dumps | ✓ `test_gen1_engine_sites.py` (17 sites) | ✓ | ✓ inspect gate: sites present on the running cartridge |
| F-3 | Site table complete (see `docs/gen1_engine_sites.md`): battle start (wild/trainer), battle end + result, capture→party vs →box, player faint, poison faint, blackout (HealParty ordering), evolution species rewrite, in-game trade, PC deposit/withdraw/release/ChangeBox, map load, bag item received/removed, save, CONTINUE, New Game, soft reset | pret `405b624` per row; RC-verified rows cite `engine_signals.json` | S-1 differential gate | ✓ `docs/gen1_engine_sites.md`; 17 pinned | · | · (S-1 differential gate pending) |
| F-4 | Wild/fishing tables and base stats: Lua ROM reader == Python `gen1_rom_scan.py`, byte-equal, all 59 tables; statics excluded; Pokémon Tower `$8E–$94` uncatchable without Silph Scope `$48` | two-path equality test | n/a | ✓ `test_gen1_rom_tables.py` (Lua ROM reader == scanner, 151 dex × 3 titles) | ✓ | — |
| F-5 | Evolution families from pret `evos_moves.asm` (Gen 1 only); item ids from pret; internal index ↔ national dex from pret dex order | generators + `gen1_codec.internal_to_natdex` | n/a | ✓ codec dex table == ROM PokedexOrder; growth byte pinned | ✓ | — |
| F-6 | Fixtures re-qualified: each `tests/fixtures/gen1/*.SaveRAM` passes the game's own checksums (`SAVCheckSum`, box checksums), loads with `TryLoadSaveFile`==2, PYDEC party matches the party-menu tilemap; `town` fixtures on encounter-free tiles; `battle` fixtures in grass with `BIT_NO_BATTLES` | pret `engine/menus/save.asm` | GAME + PYDEC | ✓ main checksums valid | ✓ `--qualify`: R/B 4 OK; Yellow 2 LEGACY (old tool bytes, pinned by name) | ✓ R/B: `tools/gen1_fixtures.py` from scripted play (town = Oak's Lab after the rival; battle = Route 1 (10,35) + one Poké Ball); Yellow open (needs its own route or an owner-made save) |

## R — Reads (`lua/gen1/reads.lua`)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| R-1 | Party/box/name decode == PYDEC on raw dumps from all three titles | PYDEC | ✓ | ✓ 12k records + fixtures (`test_gen1_reads.py`) | ✓ inspect gate 6/6: Lua-on-hardware == Python on the dumped bytes |
| R-2 | Stats pass the known-positive control (recompute from DVs/stat-exp/base stats == stored) | CONTROL (`test_gen1_stat_rebuild.lua`) | ✓ | ✓ stats leg (`test_gen1_stat_control.py`); level leg blocked by F-6 | · |
| R-3 | Trainer class/name from `wCurOpponent` (200+ form), badges as bitmask, PP-Ups preserved, active box index reported | GAME (trainer name tilemap at battle start) | · | · | · |
| R-4 | Title screen never validates (`wPlayerID==0 && partyCount==0` ⇒ not live); soft reset pauses writes (home/init.asm zero-fills WRAM until MainMenu -> TryLoadSaveFile reloads the save); hello waits for a live game | GAME (boot to title; A+B+Start+Select mid-run) | · | ✓ test_gen1_client.py::test_hello_waits_for_a_live_game_after_the_init_wram_clear | · |

## S — Signals (`lua/gen1/signals.lua`)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| S-1 | Scripted New Game → starter → rival on R/B/Y emits exactly `starter`, `battle_start(trainer)`, N×`faint`, `battle_end(lost)`, the map-load sequence; no spurious `capture`/`no_catch` | ENGINE sequence vs pret script order (`scripts/OaksLab.asm` 12→18) | ✓ site pinned | ✓ tests/unit/test_gen1_signal_receipts.py (lab-route sequence pinned from a physical receipt) | ✓ `test_gen1_new_gates.py::lab_route` Red+Blue: cold NEW GAME → starter → rival by buttons; sequence == pret script order; L5 exp 135 |
| S-2 | Route 1 wild encounter: `battle_start(wild, species, level)`; caught → one `capture(party)`; ran/lost → `battle_end` + `no_catch{species_id, level}`; ball thrown detected at the item-removal site | ENGINE + SERVER | ✓ site pinned | · `test_gen1_client.py` covers capture/no_catch; the ball-thrown-at-the-item-removal-site clause has no test | ✓ link_new a/b: TX capture{"area_id":"route_1","key":"5D86:4190:A5","species_id":165,"level":3,"nickname":"RATTATA"} after a real wild battle whose ball was thrown in-game (tests/fixtures/gen1/receipts/e2e_link_new_a_result.txt:30, throw at :29); deadzone_new a: TX no_catch{"area_id":"route_1","species_id":36,"level":2} after a RUN (e2e_deadzone_new_a_result.txt:21); the server acted on both — it paired the two captures (assert_link_new: one alive link on route_1 whose halves are the two cartridge keys, tools/e2e_duo.py:761-776) and locked route_1 on the no_catch (assert_dead_zone_new: area_states dead_zone + a links.json DEAD entry with cause dead_zone, tools/e2e_duo.py:923-940). The ball-thrown site itself is not separately observable in these logs. |
| S-3 | Party full + catch → `capture(box)` via `SendNewMonToBox`; box snapshot updated | ENGINE + PYDEC (SRAM) | ✓ site pinned | · | · |
| S-4 | Poison faint in the overworld; blackout: faint-time party bytes captured before `HealParty`; `whiteout` emitted once | ENGINE + PYDEC | ✓ site pinned | ✓ `test_gen1_client.py` (blackout + `whiteout` once; poison leg `test_poison_faint_in_the_overworld_names_the_slot_from_wWhichPokemon`, revert-falsified) | · |
| S-5 | Moon Stone evolution → `key_change{old,new}`; vanilla NPC trade → `key_change reason=npc_trade`; SLINK trade emits no `key_change` | ENGINE + GAME (new species on screen) | ✓ site pinned | ✓ `test_gen1_client.py` (evolution + npc_trade key_change; `test_slink_trade_reports_trade_done_and_never_key_change`) | · |
| S-6 | PC deposit/withdraw/release/ChangeBox → `party_to_box`/`box_to_party`; Box 12 survives ChangeBox | ENGINE + PYDEC (SRAM after) | ✓ site pinned | ✓ `test_gen1_client.py` | · |
| S-7 | Save → witness `sha256(hex(CartRAM[0x498:0x8000]))`; CONTINUE vs New Game are told apart by hello identity, not a witness (MainMenu → `TryLoadSaveFile` reloads the save before any hello; New Game gets a fresh `wPlayerID` → C-1) | ENGINE (`SaveMenu.save+3`) + hello `ot_id` | ✓ site pinned; decision 2026-09-14: no CONTINUE site (a loaded witness would duplicate R-4's live-game hello) | ✓ `test_gen1_client.py` covers the save-witness flush and the live-game hello (R-4) | · |
| S-8 | `area_enter` on every map load; area id from generated `area_map.json`; statics `static_<map>_<dex>`; gifts `gift_map_<id>`; fishing maps mapped | ENGINE + SERVER | ✓ site pinned | · | ✓ a later map load emits area_enter (e2e_trade_new_a_result.txt:64 map_1 → area_id "" — the area_map no-encounter case) and the post-boot hello carries area_id route_1 with loc_name "Route 1" (e2e_trade_new_{a,b}_result.txt:8); the capture carries area_id route_1 (e2e_link_new_a_result.txt:30); the server's own state is keyed on it (area_states.route_1 == linked, assert_link_new tools/e2e_duo.py:774; == dead_zone, assert_dead_zone_new :929). The boot area emits no area_enter (lua/gen1/client.lua:643 last_area ~= nil guard) — hello.area_id is the boot-time source; statics/gift/fishing maps are not exercised by these receipts. |

## W — Writes (`lua/gen1/writes.lua` + `lua/gen1_write_safety.lua`)

| id | Requirement | Design fact (RC PHYSICAL) | Oracle | S | M | P |
|---|---|---|---|---|---|---|
| W-1 | `force_faint` on a benched mon (overworld): party HP `0000` + status `00` only at the write-safe checkpoint | `write_checkpoint.json` | GAME (`FNT` in party menu) + PYDEC | ✓ | ✓ `test_gen1_client.py` bench faint at the checkpoint | ◐ deadzone_new b: RX force_faint key=E9E0:AFB9:A5 → FAINTED E9E0:AFB9:A5 hp=0 in party slot 1 (tests/fixtures/gen1/receipts/e2e_deadzone_new_b_result.txt:35, 50) on the mon just caught, so it is not and never was the active battler; the write lands at the overworld checkpoint after the catch battle ends (:38-40 battle_over, :49 writes re-enabled, then :50 FAINTED). The runner waits on that line before checking the server side (tools/e2e_duo.py:920-921). The status-byte-00 half of the requirement is not shown by the readback. ◐ — live read by the harness; tilemap FNT / PYDEC pending. |
| W-2 | `force_faint` on the active battler: at `MainInBattleLoop+0` (`0F:4233` RB / `0F:4249` Y) write `wBattleMonHP=0` + `wPlayerSelectedMove=$FF`; guards `wIsInBattle∈{1,2}`, `wBattleType==0`, `wLinkState≠4`, member match, Transform exception | no held window exists; party HP alone is silently undone | GAME (faint text plays; `wBattleResult`) | ✓ | ✓ `test_gen1_client.py` loop-head faint | · |
| W-3 | `force_explode`: all four move/PP slots, battle struct + party mirror | slot-0-only was escapable | GAME (move menu) | ✓ | ✓ `test_gen1_writes.py` | · |
| W-4 | `replace_rival_team`: every blob validated (66 B, count 1–6) before any write; atomic | — | GAME (rival team on screen) | ✓ | ✓ `test_gen1_writes.py` atomic validation | · |
| W-5 | `box_mon`/`party_mon`/`memorialize`: SRAM box write + `CalcIndividualBoxCheckSums`/`SAVCheckSum`; memorial = BOX12 (index 11); refuse when party ≤ 1; full memorial box → `memorialize_failed` (never the open box); withdraw rebuilds stats (never zeros) | pret `engine/menus/save.asm` | GAME (save reloads, Bill's PC lists it) + PYDEC | ✓ save.asm cited in `boxes.lua` | ✓ `test_gen1_boxes.py` (27); NOTE the game checks only sMainDataCheckSum on load | · |
| W-6 | Writes gate pauses after 5 consecutive validation failures (queue kept — an unreadable party is an engine transient, AddPartyMon's AskName window); every give-up path NACKs (`box_mon_failed`) | — | GAME (soft reset) + SERVER | — | ✓ test_gen1_client.py::test_writes_pause_after_five_invalid_validations_and_the_queue_survives | · |
| W-7 | No write lands outside `write_safety.check()` or the W-2 site | assert in `writes.lua` | lupa fake-io + RC write-safety gates | ✓ | ✓ armed-window refusal (`test_gen1_writes.py`, `test_gen1_boxes.py`) | ✓ checkpoint reached idle on all three titles (inspect gate) |

## C — Client and adapter (`lua/gen1/client.lua`, `server/adapters/gen1_rby.py`)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| C-0 | `tests/unit/test_protocol_schema.py` + `tests/unit/test_gen1_client.py` passes against the Gen 3 client AND the new Gen 1 client | MODEL (proves the suite tests the contract) | — | ✓ `tests/unit/test_protocol_schema.py` pins the table to the server; `tests/unit/test_gen1_client.py` validates every line it sends (`assert_all_conform`) | — |
| C-1 | Hello identity: `ot_id` = `wPlayerID`; a save with a different OT ⇒ `WRONG SAVE`, zero state mutation | SERVER (`links.json` unchanged) | · | · | · |
| C-2 | Reconnect: kill EmuHawk mid-run, relaunch same save ⇒ links intact, party re-synced, no duplicate captures | SERVER | · | · | · |
| C-3 | Dashboard renders Gen 1 correctly: 8-bit sprites (`mon-sprite`, `data-species`), status pill, stat stages (SPC, no SDEF), trainer name, badges, box counts, encounter panel from the player's own cartridge | browser + `test_sprite_html_contract.py` | · | · | · |
| C-4 | Client never wedges: malformed command ⇒ NACK + continue; a raise in the executor is logged once | lupa fault injection | — | ✓ `tests/unit/test_gen1_client.py` (malformed/unknown commands do not wedge; handler errors contained) | ◐ every hunt run kept operating across the unreadable-party window: the client logged writes REVOKED (older build — tests/fixtures/gen1/receipts/e2e_link_new_a_result.txt:29, e2e_deadzone_new_b_result.txt:31) or writes PAUSED (e2e_trade_new_a_result.txt:32, e2e_trade_new_b_result.txt:29), kept receiving commands through the window (e2e_trade_new_b_result.txt:32 RX box_mon while still paused), ran the queued work once writes re-enabled (e2e_link_new_a_result.txt:34, deposit observed at :46), and every run reached its RESULT: PASS; the client's own connected bit stayed true at every heartbeat (e2e_deadzone_new_a_result.txt:33-35 f=3600/7200/10800; e2e_trade_new_b_result.txt:23-75 f=3600..18000). The "RX noop flood" clause is NOT evidenced by these receipts: the harness filters noop out of its log (lua/tests/duo/duo_gen1_main.lua:83-84), so an RX noop line cannot appear. ◐ — the heartbeat flag is the client's own socket view, and the results are the scenario's client-side checks. |

## D — Rules engine under Gen 1 (duo lane; `server/state.py` is proven, not rewritten)

Pairings Red/Blue and Yellow/Red; post-conditions read by PYDEC + SERVER.

| id | Rule × mechanism | Oracle | S | M | P |
|---|---|---|---|---|---|
| D-1 | Encounter link by area from real play (Route 1) | SERVER + PYDEC | · | · | ✓ link_new PASS live (Red x2 through the real server; receipts patch/build/e2e_link_new_{a,b}_result.txt; commit c210b4f; oracle = links.json + CartRAM decode, never the client) |
| D-2 | Ball gate: nothing links or dies before `pokeballs_obtained` (per player, from the bag site) | SERVER (lab loss propagates nothing) | · | · | · — the hellos that carry the gate fields in these runs are pre-live (has_pokeballs:false, ball_count:0, party [], e2e_link_new_{a,b}_result.txt:5 and e2e_deadzone_new_{a,b}_result.txt:5) and no line shows a flip before the capture: no bag_received event, no later hello or tick with has_pokeballs:true in those runs (the only true hello is e2e_trade_new_a_result.txt:8, a scenario that boots with balls already). Missing: a receipt for the gate window itself — a pre-ball faint that propagates nothing (the lab rival loss) or any line showing pokeballs_obtained flipping before the first capture. |
| D-3 | Dead zone: A fails Route 1 ⇒ B's Route 1 catch retired (`paired_no_catch`) | SERVER + PYDEC | · | · | ✓ deadzone_new PASS live (Red x2 through the real server; receipts patch/build/e2e_deadzone_new_{a,b}_result.txt; commit c210b4f; oracle = links.json + CartRAM decode, never the client) |
| D-4 | Species (dupes) clause reroll fires on Gen 1 | SERVER | · | · | · |
| D-5 | Type clause; gender clause inert (Gen 1 has no gender) | SERVER | · | · | · |
| D-6 | Linked faint ⇒ partner `force_faint`, partner in overworld (W-1) and mid-battle (W-2) | GAME + PYDEC | · | · | · |
| D-7 | Whiteout ⇒ `rebuild_start`/`rebuild_done` via shared `_handle_whiteout`; known limit: blackout heal of a logically dead mon before the checkpoint | SERVER + PYDEC | · | · | · |
| D-8 | Memorial into Box 12 on both sides; last-mon retention intentional | PYDEC | · | · | ◐ deadzone_new b: RX memorialize key=E9E0:AFB9:A5 → TX memorialize_done{"box":11,…} → RETIRED E9E0:AFB9:A5 left the party → MEMORIAL E9E0:AFB9:A5 in box 12: true (tests/fixtures/gen1/receipts/e2e_deadzone_new_b_result.txt:36, 51, 53, 54; SEEN memorialize_done=1 memorialize_failed=0 at :57). The server half is independent — the runner requires links.json to hold the DEAD entry with cause dead_zone (assert_dead_zone_new, tools/e2e_duo.py:935). ◐ because the Box 12 placement is a live System Bus read by the harness, not a SaveRAM decode (PYDEC readback in a card now). |
| D-9 | PC sync both ways (`box_mon`/`party_mon`) | GAME + PYDEC | · | · | ◐ link_new a works both directions: RX box_mon key=5D86:4190:A5 → PARTY_COUNT 2 -> 1 @5857 (deposit) → RX party_mon key=5D86:4190:A5 → TX sync_retrieve_done seq 176 → PARTY_COUNT 1 -> 2 @6271 (withdraw) (tests/fixtures/gen1/receipts/e2e_link_new_a_result.txt:33, 46, 49, 50, 51; SEEN box_mon=1 party_mon=1 sync_retrieve_failed=0 box_mon_failed=0 at :56); b takes the retrieve half only (e2e_link_new_b_result.txt:34 RX party_mon → :47 sync_retrieve_done) because its catch was never quarantined. The server counts the mon as party-resident only after the ack (server/state.py:302 party_keys add on sync_retrieve_done; :2215 "Don't add to party_keys yet"). ◐ — the counts are the harness's live WRAM reads, not the SaveRAM (PYDEC readback in a card now). |
| D-10 | Evolution and NPC-trade key migration keeps the link | SERVER | · | · | · |
| D-11 | Rival swap + Explode Mode | GAME | · | · | · |
| D-12 | Game over on single-pair loss | SERVER + HUD | · | · | · |
| D-13 | Key non-uniqueness (`DVs:OTID:species` collides) never kills the wrong mon | SERVER + PYDEC | · | · | · |
| D-14 | Session reconnect mid-duo (C-2 under rules) | SERVER | · | · | · |

## T — In-game trade (Red/Blue; companion patch)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| T-1 | Receptionist menu at all 12 Centers + Indigo; CABLE CLUB/CANCEL fall through to vanilla | GAME (tilemap) | ✓ RC asm verbatim; 133 DEFs vs .sym; 3 ROM0 spans re-derived | ✓ `test_gen1_trade_patch.py` (10 tests); Red/Blue banks identical; dist regenerated 76ba1ff (apply round-trip verified) | ◐ receptionist gate PASS Red+Blue (3650ace): normal-button walk Oak's Lab -> Viridian Center, talk -> trade_query in 21 frames, "SLINK TRADE / CABLE CLUB / CANCEL" drawn with cursor on SLINK TRADE, picker "TRADE WHICH?" shown; ONE Center only, CABLE CLUB/CANCEL fall-through not yet driven (why still ◐) |
| T-2 | Ineligible offer refused in-game ("Trade unavailable."); eligible = one ALIVE pair, both halves in party | SERVER + GAME | · | · | ✓ receptionist gate Red+Blue (3650ace): offer of slot 0 with trade_offer_ack ok=false -> native "Trade unavailable."; ok=true -> "Trade offer sent."; both return to the overworld; every wire line validates, seq contiguous (patch/build/test_gen1_receptionist_gate_result.txt) |
| T-3 | Partner prompt YES/NO/B; screen restored | GAME | · | · | ✓ `trade_new` PASS Red×Blue (receipt `tests/fixtures/gen1/receipts/e2e_trade_new_b_result.txt`): native "Trade RATTATA / for RATTATA?" YES/NO drawn on B after A's offer returned; YES with normal buttons; screen restored; one trade_done per side |
| T-4 | Apply: animation, evolution, `SavePartyAndDexData`; both sides decode swapped mons; link halves swapped; received mon in the LAST party slot | PYDEC + GAME (save reloads) + SERVER | · | · | ✓ `trade_new` PASS Red×Blue (receipts `e2e_trade_new_{a,b}_result.txt`): after the native apply each per-instance SaveRAM party decodes (PYDEC) to two mons with the partner's former DV:OTID:species in the LAST slot and the partner's OT name; links.json halves swapped (a=ED92:AFB9:A5, b=EE8F:4190:A5); trade_done valid both sides; assertions read only links.json + CartRAM, never the client |
| T-5 | Crash mid-trade ⇒ existing watchdog abandons or force-commits; documented limit | MODEL | — | · | — |

---

## Not in this release (recorded so nobody infers otherwise)

Durable runtime / paired checkpoints / recover; whiteout-rebuild rewrite (D-7 proves the shared path instead); Manager holds UI; HUD lifecycle notices; UPR fastest-text option; Yellow trade (bank `$3B`); internet/NAT play; Archipelago variants beyond profile generation; the two-human attestation (first post-tag activity).

## Assets taken from `gen1/rc` (verified, not trusted blindly)

`data/games/gen1_rby/{engine_signals,continue_sites,write_checkpoint,wild_encounter_sites}.json`, `lua/gen1_write_safety.lua`, `lua/json_codec.lua`, `lua/tests/{gen1_rb_ball_gate_inputs,gen1_rb_parcel_inputs,gen1_rb_save_inputs,gen1_battle_driver,gen1_map_fixture,gen1_cold_trade_inputs}.lua`, `tools/verify_gen1_release.py` (as of `79d5172`), the five `patch/gen1/src/trade_*.asm` + `native_trade.asm` (Phase 7). Each is re-verified in the F lane before anything downstream relies on it. The scripted-chain host (`gen1_scripted_new_game.lua` + `tests/live/gen1_scripted_host.py`) depends on RC-runtime modules and is ported in Phase 6, not copied.
