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
| R-4 | Title screen never validates (`wPlayerID==0 && partyCount==0` ⇒ not live); soft reset revokes writes | GAME (boot to title; A+B+Start+Select mid-run) | · | · | · |

## S — Signals (`lua/gen1/signals.lua`)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| S-1 | Scripted New Game → starter → rival on R/B/Y emits exactly `starter`, `battle_start(trainer)`, N×`faint`, `battle_end(lost)`, the map-load sequence; no spurious `capture`/`no_catch` | ENGINE sequence vs pret script order (`scripts/OaksLab.asm` 12→18) | ✓ site pinned | ✓ | ✓ `test_gen1_new_gates.py::lab_route` Red+Blue: cold NEW GAME → starter → rival by buttons; sequence == pret script order; L5 exp 135 |
| S-2 | Route 1 wild encounter: `battle_start(wild, species, level)`; caught → one `capture(party)`; ran/lost → `battle_end` + `no_catch{species_id, level}`; ball thrown detected at the item-removal site | ENGINE + SERVER | ✓ site pinned | ✓ `test_gen1_client.py` | · |
| S-3 | Party full + catch → `capture(box)` via `SendNewMonToBox`; box snapshot updated | ENGINE + PYDEC (SRAM) | ✓ site pinned | · | · |
| S-4 | Poison faint in the overworld; blackout: faint-time party bytes captured before `HealParty`; `whiteout` emitted once | ENGINE + PYDEC | ✓ site pinned | ✓ `test_gen1_client.py` | · |
| S-5 | Moon Stone evolution → `key_change{old,new}`; vanilla NPC trade → `key_change reason=npc_trade`; SLINK trade emits no `key_change` | ENGINE + GAME (new species on screen) | ✓ site pinned | ✓ `test_gen1_client.py` | · |
| S-6 | PC deposit/withdraw/release/ChangeBox → `party_to_box`/`box_to_party`; Box 12 survives ChangeBox | ENGINE + PYDEC (SRAM after) | ✓ site pinned | ✓ `test_gen1_client.py` | · |
| S-7 | Save → witness `sha256(hex(CartRAM[0x498:0x8000]))`; CONTINUE → loaded witness; New Game distinguished | ENGINE (`SaveMenu.save+3`, `TryLoadSaveFile`) | ✓ site pinned | ✓ `test_gen1_client.py` | · |
| S-8 | `area_enter` on every map load; area id from generated `area_map.json`; statics `static_<map>_<dex>`; gifts `gift_map_<id>`; fishing maps mapped | ENGINE + SERVER | ✓ site pinned | · | · |

## W — Writes (`lua/gen1/writes.lua` + `lua/gen1_write_safety.lua`)

| id | Requirement | Design fact (RC PHYSICAL) | Oracle | S | M | P |
|---|---|---|---|---|---|---|
| W-1 | `force_faint` on a benched mon (overworld): party HP `0000` + status `00` only at the write-safe checkpoint | `write_checkpoint.json` | GAME (`FNT` in party menu) + PYDEC | ✓ | ✓ `test_gen1_client.py` bench faint at the checkpoint | · |
| W-2 | `force_faint` on the active battler: at `MainInBattleLoop+0` (`0F:4233` RB / `0F:4249` Y) write `wBattleMonHP=0` + `wPlayerSelectedMove=$FF`; guards `wIsInBattle∈{1,2}`, `wBattleType==0`, `wLinkState≠4`, member match, Transform exception | no held window exists; party HP alone is silently undone | GAME (faint text plays; `wBattleResult`) | ✓ | ✓ `test_gen1_client.py` loop-head faint | · |
| W-3 | `force_explode`: all four move/PP slots, battle struct + party mirror | slot-0-only was escapable | GAME (move menu) | ✓ | ✓ `test_gen1_writes.py` | · |
| W-4 | `replace_rival_team`: every blob validated (66 B, count 1–6) before any write; atomic | — | GAME (rival team on screen) | ✓ | ✓ `test_gen1_writes.py` atomic validation | · |
| W-5 | `box_mon`/`party_mon`/`memorialize`: SRAM box write + `CalcIndividualBoxCheckSums`/`SAVCheckSum`; memorial = BOX12 (index 11); refuse when party ≤ 1; full memorial box → `memorialize_failed` (never the open box); withdraw rebuilds stats (never zeros) | pret `engine/menus/save.asm` | GAME (save reloads, Bill's PC lists it) + PYDEC | ✓ save.asm cited in `boxes.lua` | ✓ `test_gen1_boxes.py` (27); NOTE the game checks only sMainDataCheckSum on load | · |
| W-6 | Writes gate is revocable (5 consecutive validation failures ⇒ off, pending cleared); every give-up path NACKs (`box_mon_failed`) | — | GAME (soft reset) + SERVER | — | ✓ `test_gen1_client.py` revoke after 5 invalid | · |
| W-7 | No write lands outside `write_safety.check()` or the W-2 site | assert in `writes.lua` | lupa fake-io + RC write-safety gates | ✓ | ✓ armed-window refusal (`test_gen1_writes.py`, `test_gen1_boxes.py`) | ✓ checkpoint reached idle on all three titles (inspect gate) |

## C — Client and adapter (`lua/gen1/client.lua`, `server/adapters/gen1_rby.py`)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| C-0 | `tests/unit/test_protocol_conformance.py` passes against the Gen 3 client AND the new Gen 1 client | MODEL (proves the suite tests the contract) | — | ✓ `protocol_schema.py` pinned to the server + 17 client scenarios validated | — |
| C-1 | Hello identity: `ot_id` = `wPlayerID`; a save with a different OT ⇒ `WRONG SAVE`, zero state mutation | SERVER (`links.json` unchanged) | · | · | · |
| C-2 | Reconnect: kill EmuHawk mid-run, relaunch same save ⇒ links intact, party re-synced, no duplicate captures | SERVER | · | · | · |
| C-3 | Dashboard renders Gen 1 correctly: 8-bit sprites (`mon-sprite`, `data-species`), status pill, stat stages (SPC, no SDEF), trainer name, badges, box counts, encounter panel from the player's own cartridge | browser + `test_sprite_html_contract.py` | · | · | · |
| C-4 | Client never wedges: malformed command ⇒ NACK + continue; a raise in the executor is logged once | lupa fault injection | — | ✓ malformed/unknown commands, handler errors contained | — |

## D — Rules engine under Gen 1 (duo lane; `server/state.py` is proven, not rewritten)

Pairings Red/Blue and Yellow/Red; post-conditions read by PYDEC + SERVER.

| id | Rule × mechanism | Oracle | S | M | P |
|---|---|---|---|---|---|
| D-1 | Encounter link by area from real play (Route 1) | SERVER + PYDEC | · | · | · |
| D-2 | Ball gate: nothing links or dies before `pokeballs_obtained` (per player, from the bag site) | SERVER (lab loss propagates nothing) | · | · | · |
| D-3 | Dead zone: A fails Route 1 ⇒ B's Route 1 catch retired (`paired_no_catch`) | SERVER + PYDEC | · | · | · |
| D-4 | Species (dupes) clause reroll fires on Gen 1 | SERVER | · | · | · |
| D-5 | Type clause; gender clause inert (Gen 1 has no gender) | SERVER | · | · | · |
| D-6 | Linked faint ⇒ partner `force_faint`, partner in overworld (W-1) and mid-battle (W-2) | GAME + PYDEC | · | · | · |
| D-7 | Whiteout ⇒ `rebuild_start`/`rebuild_done` via shared `_handle_whiteout`; known limit: blackout heal of a logically dead mon before the checkpoint | SERVER + PYDEC | · | · | · |
| D-8 | Memorial into Box 12 on both sides; last-mon retention intentional | PYDEC | · | · | · |
| D-9 | PC sync both ways (`box_mon`/`party_mon`) | GAME + PYDEC | · | · | · |
| D-10 | Evolution and NPC-trade key migration keeps the link | SERVER | · | · | · |
| D-11 | Rival swap + Explode Mode | GAME | · | · | · |
| D-12 | Game over on single-pair loss | SERVER + HUD | · | · | · |
| D-13 | Key non-uniqueness (`DVs:OTID:species` collides) never kills the wrong mon | SERVER + PYDEC | · | · | · |
| D-14 | Session reconnect mid-duo (C-2 under rules) | SERVER | · | · | · |

## T — In-game trade (Red/Blue; companion patch)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| T-1 | Receptionist menu at all 12 Centers + Indigo; CABLE CLUB/CANCEL fall through to vanilla | GAME (tilemap) | ✓ RC asm verbatim; 133 DEFs vs .sym; 3 ROM0 spans re-derived | ✓ `test_gen1_trade_patch.py` (10 tests); Red/Blue banks identical; NOTE the shipped `.ups` + `server/patcher.py` md5s are still the panel-only build until dist is regenerated | ◐ panel gates pass on the trade-carrying build; receptionist menu not yet driven live |
| T-2 | Ineligible offer refused in-game ("Trade unavailable."); eligible = one ALIVE pair, both halves in party | SERVER + GAME | · | · | · |
| T-3 | Partner prompt YES/NO/B; screen restored | GAME | · | · | · |
| T-4 | Apply: animation, evolution, `SavePartyAndDexData`; both sides decode swapped mons; link halves swapped; received mon in the LAST party slot | PYDEC + GAME (save reloads) + SERVER | · | · | · |
| T-5 | Crash mid-trade ⇒ existing watchdog abandons or force-commits; documented limit | MODEL | — | · | — |

---

## Not in this release (recorded so nobody infers otherwise)

Durable runtime / paired checkpoints / recover; whiteout-rebuild rewrite (D-7 proves the shared path instead); Manager holds UI; HUD lifecycle notices; UPR fastest-text option; Yellow trade (bank `$3B`); internet/NAT play; Archipelago variants beyond profile generation; the two-human attestation (first post-tag activity).

## Assets taken from `gen1/rc` (verified, not trusted blindly)

`data/games/gen1_rby/{engine_signals,continue_sites,write_checkpoint,wild_encounter_sites}.json`, `lua/gen1_write_safety.lua`, `lua/json_codec.lua`, `lua/tests/{gen1_rb_ball_gate_inputs,gen1_rb_parcel_inputs,gen1_rb_save_inputs,gen1_battle_driver,gen1_map_fixture,gen1_cold_trade_inputs}.lua`, `tools/verify_gen1_release.py` (as of `79d5172`), the five `patch/gen1/src/trade_*.asm` + `native_trade.asm` (Phase 7). Each is re-verified in the F lane before anything downstream relies on it. The scripted-chain host (`gen1_scripted_new_game.lua` + `tests/live/gen1_scripted_host.py`) depends on RC-runtime modules and is ported in Phase 6, not copied.
