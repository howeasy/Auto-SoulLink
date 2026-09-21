# Gen 3 release requirements

This is the release contract for Pokémon FireRed/LeafGreen (US 1.0) and Radical Red 4.1. A row
is **done** only when it carries a SOURCE proof (pret/RR-binary citation or generated-from-source
data) **and** a PHYSICAL proof (real cartridge in BizHawk, judged by an oracle that is not the
code under test). MODEL evidence (lupa/pytest against fakes) is recorded but never closes a row
on its own. The runner is `python tools/verify_gen3_release.py`; a lane that did not run did not
pass.

Nothing in `lua/clients/gen3_frlge_client.lua`, `lua/games/gen3_frlge.lua`,
`lua/memory_gba.lua`, `lua/mailbox.lua` or `lua/peer_ghost_npc.lua` (the old client and its
support files, deleted at P5) counts as evidence for a row here — see `docs/gen3/PLAN.md` §3 for
what each one is missing. This ledger is populated phase by phase against `docs/gen3/PLAN.md`
§6's gates; a row stays `·` until its phase lands a receipt.

## Pins

| What | Value |
|---|---|
| pret/pokefirered commit | `c75f352304d529f6ba92d4f74b9cf8b5c3810788` (master 2026-08-04; `.sym`/`.map` are Makefile targets) + pret/agbcc `da598c1d918402c42c0c0d7128ba14567f3175e9` (`docs/gen3/research/pins.md` §1-2; cross-checked) — **proposed for G0** |
| devkitARM / toolchain version | agbcc (git-pinned above) is the default toolchain; devkitARM is only `make modern` and is NOT reproducibly pinnable (rolling pacman) → P2 uses agbcc, else the committed-`.sym/.map`-with-provenance fallback (`pins.md` §2) — **owner decision at G0** |
| FR US 1.0 sha1 | `41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc` (pret `firered.sha1`); local dump `E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba` MATCHES (`pins_inventory.md` addendum). Rev 1 (`dd5945db…`) exists locally and is NOT admitted |
| LG US 1.0 sha1 | `574fa542ffebb14be69902d1d36f1ec0a4afd71e` (pret `leafgreen.sha1`); local dump `E:/Google Drive/SLink/Pokemon - LeafGreen Version (USA).gba` MATCHES (owner placed it at G0; `pins_inventory.md` G0 addendum) |
| RR 4.1 base md5 | `8529f3a45d32bce4da637976fcf269d4`, sha1 `964f951a0fdaf209e4ea1344883ef0d557bb3a80` (`patch/tools/build.py:90`, `server/patcher.py:71`; local base and root `rr_clean.gba` both MATCH). The "4.1" label is taken from in-tree names, not a signed statement |
| Companion patched md5 | `bf8e94a01c0aee0aa7eb37c7333329af` (sha1 `b7d1e0756fcc66575878affc8f7b95c45386bb1c`) = what the shipped `patch/dist/SLink-RR.ups` (`cd11fca`, 2026-07-25) produces over the verified base via `patch/tools/make_ups.py ups_apply`; the previous pin `8dcffce7…` in `server/patcher.py:72` / `patch/README.md:27` was stale and is corrected in this commit. **G0 ruling**: this rebuilt artifact is the admitted companion until P5 rebuilds from source and re-pins |
| BizHawk 2.11.1 mGBA + installed `EmuHawk.exe`/`mgba.dll` sha256 | tag `2.11.1` = `bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5`, mGBA submodule `94b1578f8545d8ad17bb4036dba908612d5731e2`; installed `EmuHawk.exe` `f8cdb935…`, `dll/mgba.dll` `ba398a56…`, `dll/BizHawk.Emulation.Cores.dll` `444bc157…` (`tools/gen3_pins.py`; identical to the `codex/rr-foundation` pins). Issue #3801 fixed by `9463267…`, an ancestor of 2.11.1 |
| CFRU `BPRE.ld` revision | Skeli789/Complete-Fire-Red-Upgrade `b637a27898b14e25dd24d0f69a3e302f0069deb8` (2025-01-24; flat vanilla-symbol→address linker script). RR ↔ CFRU relationship: community sources only; "RR has no public source" = negative evidence (`pins.md` §3, §5) |
| Wire contract | `docs/protocol.md` |
| Engine sites | `docs/gen3_engine_sites.md` + `data/games/gen3_{frlg,rr}/engine_signals.json` |

## Oracles (what "independent" means here)

- **ENGINE** — a `bus_exec` hook at the callback address for a pinned site fired (or did not), with expected bytes verified in ROM at load and rechecked on the bus at fire.
- **PYDEC** — `server/adapters/gen3_codec.py` decodes the same raw EWRAM/IWRAM/flash bytes; Lua and Python must agree.
- **GAME** — the game itself: the flash save reloads with the expected party/box contents; native RR screens (mailbox panel, trade scene, storage) show the expected text/state.
- **SERVER** — `links.json` / server status, read by pytest, not by the client.
- **CONTROL** — a known-positive control: recompute a value two ways and require equality (e.g. codec round-trip on a fixture, flash-layout sector rotation).

## Status legend

`S` SOURCE, `M` MODEL, `P` PHYSICAL. `·` = not yet, `✓` = done with receipt path, `◐` = partial
(named sub-clause open), `†UNVERIFIED` = asserted somewhere but not pinned to a source or receipt
in this tree.

---

## F — Facts (no emulator; P2 SOURCE work)

| id | Requirement | SOURCE | Oracle | S | M | P |
|---|---|---|---|---|---|---|
| F-1 | Every address in the generated `gen3_frlg`/`gen3_rr` profiles names a pinned symbol or RR binary anchor; profile diff == 0 vs today's client literals (`R4`, `docs/gen3/PLAN.md` §3 R4, §6 P2) | `tools/gen_gen3_profile.py --check` | n/a | · | · | — |
| F-2 | Every engine-site record's `expected_hex` is present at `rom_offset` in FR, LG, RR-clean and RR-companion (`R3`, §5.8) | `tools/pin_gen3_site.py` + `tools/gen_gen3_engine_signals.py` + `engine_signals.json` | lane vs four ROM dumps | · | · | · |
| F-3 | Site table complete: per-kind caller/mutation/return inventory from pinned source, RR additionally binary cross-referenced (`battle_begin`/`battle_end`, `faint`, `capture_wild`, `mon_given`, `pc_move`, `whiteout`, `map_load`, `evolve_species_store`, `trade_done`, `save`, `poison_faint`, `borrowed_party` begin/end, `nature_change`) — see §5.8's table; each candidate stays a candidate until byte-pinned and receipted per branch | pret pokefirered source + RR binary anchors, per §5.8 | S-kind differential gate | · | · | · |
| F-4 | Writer inventory (every code path that mutates party/PC/SaveBlock pointers/flash/mailbox arena) + `allowed_overworld_tasks` allow-list census, feeding the checkpoint predicate (`R6`, §5.3) | pret pokefirered source, RR relocation notes (`BR:docs/rr_reference/GAME_HEAP_RESERVATION.md:46-55`) | frame-end R15/CPSR census (overworld/menu/battle/save) | · | · | — |
| F-5 | Flash layout spec: sector map (14 sectors × 2 slots + Hall of Fame), sector footer (id/checksum/security/counter), slot-selection algorithm incl. counter wrap and partial/full write states; RR extensions cross-checked against the RR binary (§5.5) | upstream `save.c` algorithm + RR binary | CONTROL (torn/mixed/duplicate/missing sector controls) | · | · | — |
| F-6 | Fixtures re-qualified: each `tests/fixtures/gen3/*.sav` (+ `_b` variants) passes the codec's own qualify (`--qualify`) and a real cold boot → CONTINUE → re-save → reload (`--boot-check`) (§5.5) | derivation documented in `tools/gen3_fixtures.py` | GAME + PYDEC | — | · | · |
| F-7 | RR species/types/sprites/natdex facts generated at pinned tool revisions (`tools/gen_rr_{species,types,sprites,natdex}.py`), output paths fixed (§6 P2) | pinned tool revisions | n/a | · | · | — |
| F-8 | Admission profiles: `gen3_frlg` kinds `clean` (FR/LG US 1.0 sha1) and `named` (BPRE/BPGE header fallback, refused by site check on byte mismatch); `gen3_rr` kinds `clean` (RR 4.1 base md5) and `companion` (SLink-RR.ups applied) (`R7`, §5.1) | `admission.json` per pack | ENGINE + SERVER | · | · | · |

## R — Reads (`lua/gen3/reads.lua`)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| R-1 | Vanilla party/box decode (100 B party record, 80 B box record, decrypt + permute + checksum) == PYDEC on raw dumps (`R4`/`R10`) | PYDEC | · | · | · |
| R-2 | RR fixed-order party decode (`CFRU_NO_ENCRYPT`, unencrypted) + compressed 0x3A box decode == PYDEC, checksum field left zero per CFRU's own behaviour (§5.6) | PYDEC | · | · | · |
| R-3 | SaveBlock pointer deref with snapshot-at-arm-time/revalidate-before-each-write rules (RR relocation) (§5.3) | GAME (no corruption after a relocating event) | · | · | · |
| R-4 | Bag/badges/map/battle/trainer reads decode correctly; FR charmap is the one glyph table (`R4`) | PYDEC | · | · | · |
| R-5 | No leaked addresses under `lua/gen3/`: every address used by `reads.lua`/`native.lua`/`ghost.lua` comes from the profile, none hardcoded (leak guard extending `test_gen1_no_hardcoded_addresses.py`'s pattern; `R4`) | static scan | ✓ (design) | · | — |

## S — Signals (`lua/gen3/signals.lua`)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| S-1 | Signal contract: site record carries `address`/`capture_offset`/`expected_hex`/`rom_offset`/`point`/`mode`; at fire, the **callback address** (not raw R15) equals `address + capture_offset`; `raw_r15`/`cpsr` (mode, T-bit)/`frame`/`sp` recorded separately (§5.2) | ENGINE (P1 probe matrix, positive + negative per site) | · | · | · |
| S-2 | `battle_begin`/`battle_end`: `CB2_InitBattle`; end = the pinned return site `0x08015B59` (completion, not entry) (§5.8) | ENGINE | · | · | · |
| S-3 | `faint` (`Cmd_tryfaintmon`): player-side filter, double-battle identity; two stimuli — `faint_cmd` (server-command/persistence-only) and `linked_faint_active`/`linked_faint_bench` (natural engine faint via scripted battle input) (§5.5) | ENGINE + PYDEC | · | · | · |
| S-4 | `capture_wild` (`Cmd_givecaughtmon` → `GiveMonToPlayer` return): snapshot destination AFTER assignment, not at ball-throw success; `mon_given` result-code qualification (script gift vs caught) (§5.8) | ENGINE + PYDEC | · | · | · |
| S-5 | `pc_move`: storage-system party↔box copy/release points, release vs deposit distinguished (`boxsync` scenario) (§5.8) | ENGINE + PYDEC | · | · | · |
| S-6 | `whiteout`: `CB2_WhiteOut` **completion** state (it is a repeating state machine at entry), emitted once-only (§5.8) | ENGINE | · | · | · |
| S-7 | `map_load`: end of `CB2_LoadMap`, not entry; area id after load (§5.8) | ENGINE + SERVER | · | · | · |
| S-8 | `evolve_species_store`: evolution scene species publish; RR's `CB2` check is dormant today and must be proven or left OPEN (§5.8) | ENGINE + GAME | · | · | · |
| S-9 | `trade_done`: `DoInGameTrade` completion (NPC) + link trade completion, distinguished by context; vanilla FRLG has no trade executor and emits none (§0, §5.6) | ENGINE + GAME | · | · | · |
| S-10 | `save`: successful full-save completion (return of the sector-write loop with status OK, not routine entry) — the witness site (§5.5) | ENGINE | · | · | · |
| S-11 | `poison_faint`: field poison step faint (new kind, no Gen 1 precedent) (§5.8) | ENGINE | · | · | · |
| S-12 | `borrowed_party` begin/end (RR mock-battle party swap/restore) and `nature_change` (RR nature-changer special) — RR-only kinds (§5.8) | ENGINE + GAME | · | · | · |
| S-13 | Callback-parameter availability (`addr`/`val`/`flags`) on this host recorded in the probe receipt, not assumed (§5.2) | ENGINE (P1 probe) | · | — | · |

## W — Writes (`lua/gen3/writes.lua` + `lua/gen3/safety.lua`)

| id | Requirement | Design fact | Oracle | S | M | P |
|---|---|---|---|---|---|---|
| W-1 | One armed write gate: `arm(reason, allow)` / `write_bytes\|u16\|u32`, validate-before-first-byte, provenance log; reasons `overworld`, `battle_faint`, `battle_commit`, `native`, `memorial_rename` (`R5`, §4) | no held window outside the arm | lupa fake-io | · | · | — |
| W-2 | Checkpoint predicate re-verifies ROM anchors (`CB2_Overworld`, `VBlankIntr`, save routine) every call, fail-closed on any unreadable input; forbidden states (script running, save in progress, PC menu open, evolution, link, native op staged, mid-relocation) each drive it `false` with an empty write log (§5.3, `R6`) | `write_checkpoint.json` (ROM anchors + writer-exclusion predicates + `allowed_overworld_tasks`) | GAME (live negative controls at G3) | · | · | · |
| W-3 | `force_faint` on a benched mon (overworld): deferred to the checkpoint, lands within one checkpoint frame in ordinary play (§5.6 item 33-35) | `write_checkpoint.json` | GAME + PYDEC | · | · | · |
| W-4 | `force_faint` on the active battler: armed at the battle-loop-head equivalent, guarded like Gen 1's W-2 (member match, in-battle state) | no held window; party HP alone is silently undone | GAME (faint text plays) + PYDEC | · | · | · |
| W-5 | `box_mon`/`party_mon`/`memorialize` via `lua/gen3/boxes.lua`: vanilla encrypted 80 B write + checksum recompute; RR native op (opcodes 24/25/26) preferred with Lua fallback (§3 feature-dependency note) | flash layout spec (F-5) | GAME (save reloads) + PYDEC | · | · | · |
| W-6 | Writes pause after repeated validation failures (queue kept, an unreadable party/pointer is an engine transient); every give-up path NACKs (`box_mon_failed`, which the new client sends unlike the old one — §5.6 "three documented disagreements") | — | GAME (soft reset / relocation) + SERVER | — | · | · |
| W-7 | No write lands outside `writes.lua`'s gate: static leak test (no `memory.write*` outside `lua/gen3/writes.lua` under `lua/gen3/`) + a lupa run of the production client with every io mutation sink intercepted and asserted reachable only through `writes` (§5.7, §6 P4/P5) | assert in `writes.lua` | static scan + lupa fake-io | ✓ (design) | · | · |

## C — Client and adapter (`lua/gen3/client.lua`, `server/adapters/gen3_frlge.py`)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| C-0 | `tests/unit/test_protocol_conformance.py` (§9, item-level evidence map) passes against the new Gen 3 client for every item it tags World; golden P1 transcripts are characterization evidence only (§5.6) | MODEL (proves the suite tests the contract) | — | · | — |
| C-1 | Hello carries `rom_sha1`/`ot_id`/`artifact_kind`/`foundation`/capabilities; admission is sha1 → anchors → named-family fallback, same shape as Gen 1's `Entry.admit` (`R7`, §5.1) | SERVER (`/api/status` admission + `events.json`) | · | · | · |
| C-2 | Reconnect: same-save ⇒ links intact, party re-synced, no duplicate captures; wrong-save ⇒ refused, zero state mutation (`reconnect --wrong-save` scenario) | SERVER (`links.json` unchanged on refusal) | · | · | · |
| C-3 | Dashboard renders Gen 3 correctly (sprites, status pill, stat stages, trainer name, badges, box counts) | browser + `test_sprite_html_contract.py` | · | · | · |
| C-4 | Client never wedges: malformed command ⇒ NACK + continue; a raise in the executor is logged once (lupa fault injection, MODEL by construction like Gen 1's C-4) | lupa fault injection | — | · | ◐ (incidental evidence only, by recorded limit) |
| C-5 | Mixed-foundation pairing refused before adapter reselection: `foundation_for_rom_type` derived (never trusted), `pairing_kind` hook (`companion → clean` for `gen3_rr`), forged/missing/mismatched `foundation` refused, saved-run restart re-derives the lock (§5.1, P3a) | SERVER (`links.json` bytes + presentation caches unchanged on refusal) | · | · | · |
| C-6 | Deferred commands are idempotent under the shipped `SYNC_INFLIGHT_RECONCILES` re-issue window: `party_mon` for an already-in-party key acks, `box_mon` for an already-boxed key acks, duplicate `memorialize` deduped; `stats_cache` carries the pre-deposit snapshot (§5.4) | lupa (hold beyond six reconciler passes, inject the opposite command, both execution orders + reconnect) | — | · | · |

## D — Rules engine under Gen 3 (duo lane; `server/state.py` is proven, not rewritten)

Pairings: `gen3_frlg` FR=A/LG=B (clean); `gen3_rr` companion both sides, plus RR-clean coverage
per §6 P5. Post-conditions read by PYDEC + SERVER, per §5.5's scenario matrix (7 `gen3_frlg`, 9
`gen3_rr`).

| id | Scenario | Rule × mechanism | Oracle | S | M | P |
|---|---|---|---|---|---|---|
| D-1 | `link` | Encounter link by area from natural play | SERVER + PYDEC | · | · | · |
| D-2 | `deadzone` | Dead zone: one side's failed encounter retires the partner's pending capture, area → `DEAD_ZONE` | SERVER + PYDEC | · | · | · |
| D-3 | `linked_faint_active` / (bench half via `faint_cmd`) | Linked faint ⇒ partner `force_faint`, both the overworld (W-3) and mid-battle (W-4) windows | GAME + PYDEC | · | · | · |
| D-4 | `faint_cmd` | Server-injected faint via debug API: propagation, `force_faint`, save — persistence-only, proves nothing about the engine hook (§5.5) | SERVER + PYDEC | — | · | · |
| D-5 | `boxsync` | PC sync both ways (`box_mon`/`party_mon`), idempotent under the reconciler window (C-6) | GAME + PYDEC | · | · | · |
| D-6 | `whiteout` | Whiteout ⇒ rebuild via shared `_handle_whiteout` (unchanged `server/state.py` path, S-6's completion signal) | SERVER + PYDEC | · | · | · |
| D-7 | `reconnect` (`--wrong-save`) | Session reconnect mid-duo under the rules engine (C-2 under rules) | SERVER | · | · | · |

## N — Native companion (RR only; `lua/gen3/native.lua`, `lua/gen3/ghost.lua`, `patch/`)

| id | Scenario | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|---|
| N-1 | (all RR-companion scenarios) | Mailbox ABI as an injected part; the queue OWNS its staging buffers (fixes the old client's `mailbox.lua:480-486` gap) (`R12`) | ENGINE + GAME | · | · | · |
| N-2 | `ghost` | Engine-NPC peer ghost over native; stall metric measured directly (transient claim, not the ack) (§5.5) | GAME (stutter metric) | · | · | · |
| N-3 | `trade` | RR native trade ported behaviour-for-behaviour from the old client: blob ≥ 100 B staged, `old_key` located at apply time, scene → `trade_done` from readback, scene failure → silent `OP_SET_PARTY_MON` swap, no patch → logged abort with no write and no completion (§5.6); a `trade_abort` control asserts no write/no completion and matches today's watchdog outcome | PYDEC + GAME (save reloads) + SERVER | · | · | · |
| N-4 | `infopanel` | Info-panel screen/page/close, direct measurement (transient claim) (§5.5) | GAME (screen readback) | · | · | · |
| N-5 | `explode` | Explode Mode resolves `gBattleOutcome`; behaves like Gen 1's `force_explode` bench rule where applicable | ENGINE (faint site) + PYDEC | · | · | · |
| N-6 | `rival_swap` | RR rival team replace + readback of the enemy party species/moves during the fight, not the ack | GAME (enemy party RAM readback) | · | · | · |
| N-7 | `native_absent` | Clean RR beside companion RR: native refused cleanly, PC storage falls back to the Lua path (W-5) | SERVER + GAME | · | · | · |
| N-8 | (release gate) | Companion patch rebuild: `handlers.c` guards land, `patch/dist/SLink-RR.ups`, `server/patcher.py` md5 updated, README md5 test; P2 anchors/admission re-run for the rebuilt companion kind (§6 P5) | CONTROL (md5 match) | · | · | — |

## X — Per-artifact required coverage

| Artifact | Required site kinds | Checkpoint liveness | Scenarios | Status |
|---|---|---|---|---|
| FR clean | S-1..S-11 (vanilla kinds; no N rows) | ≤ 120 frames standing still in ordinary overworld play (§5.5 liveness bound) | `gen3_frlg` seven: `faint_cmd`, `linked_faint_active`, `boxsync`, `whiteout`, `link`, `deadzone`, `reconnect` | · |
| LG clean | S-1..S-11 (vanilla kinds; no N rows) | same bound | `gen3_frlg` seven (same set, driven on LG) | · |
| RR clean | S-1..S-11 (no native/mailbox kinds; no companion observations exist there) | same bound | `native_absent` (clean RR beside companion RR: native refused cleanly, storage via Lua fallback) plus the `gen3_rr` base run on the clean side of that pair | · |
| RR companion | S-1..S-13 + N-1..N-8 | same bound | `gen3_rr` nine (PLAN §5.5): `faint_cmd`, `linked_faint_active`, `boxsync`, `trade`, `ghost`, `infopanel`, `explode`, `rival_swap`, `native_absent` | · |

A required row that is OPEN/UNCOVERED blocks that artifact's cutover (§5.5). A receipt shared
across artifacts needs an explicit equivalence proof (same bytes at the same offsets **and** the
same reachability context), never bytes alone.

## Not in this release

Archipelago FRLG (title `firered_ap` kept unadmitted, `†UNVERIFIED` "TODO VERIFY" fields carried
from `games/gen3_frlge.lua:154-170`); Emerald (title `emerald` kept unadmitted, needs its own
`gen3_emerald` pack — today it silently resolves FireRed area ids, an encounter-rule bug, not
just a label bug); vanilla FRLG trade (no native trade scene exists today either; the new client
cancels server-driven prompts outside the receptionist flow exactly as Gen 1's client does for
Yellow, `docs/gen1_requirements.md:154`); randomized FRLG admission / UPR for Gen 3; moving
`data/games/gen3_frlge/rr_*.json` into `gen3_rr/` (cosmetic); the parked `codex/rr-foundation`
branch (not merged; its `docs/rr_reference/*` are reference inputs only).

## Receipts (running)

- 2026-09-21 P1 census on RR `slink_overworld.State`: `docs/gen3/probes/census_rr_overworld_2026-09-21.txt` (R15 parked at BIOS `0x1C4`, System/ARM, one idle task set) — PHYSICAL input to W-2 (checkpoint) and S-13 (register names).

- 2026-09-21 P1 hook probe on FR clean + RR companion: `docs/gen3/probes/hooks_*_2026-09-21.txt` — PHYSICAL input to S-1 (callback-address contract), S-13 (params/register names), F-5/W (flash domain = SRAM 0x20000); a-return and b-interior OPEN.

- 2026-09-21 P2 codec differential finding: `lua/memory_gba.lua:622` substruct permutation rows 3/4 were swapped vs pret `src/pokemon.c` `SUBSTRUCT_CASE(3,0,3,1,2)/(4,0,2,3,1)` (vanilla FRLG only, PID%24 in {3,4}: wrong moves/ability substruct; species unaffected). Fixed by the coordinator (two rows) with `tests/unit/test_gen3_lua_vs_codec.py` as the standing differential.

- 2026-09-21 P1 baseline: the six RR duo scenarios (`faint`, `boxsync`, `trade`, `ghost`, `infopanel`, `explode`) re-run on the OLD client at cut 91c7025 with the wire-log tap: all PASS (attempt 1 of 1 each), 17,286 transcript lines captured; transcripts are provisional (t = seq) until C1-3b lands and the capture is repeated — characterization input to C-0 and D rows, not a Gen 3 verdict.

- 2026-09-21 P2 boot-check on RR companion: `docs/gen3/probes/bootcheck_rr_town_2026-09-21.txt` — PHYSICAL: `tests/fixtures/gen3/rr_town.sav` cold boot → CONTINUE → START/SAVE, counter 2→3, 14/14 sectors of the new slot written, flushed battery re-qualifies with the party unchanged (F-6 RR half). Two instrument findings fixed on the way: BizHawk files the battery as `gen3 slink RR.SaveRAM` (underscores → spaces; seed under that name), and the counter appears ~950 frames before the sector loop ends under mGBA flash timing (~66 frames/sector), so the driver now waits for all 14 sectors instead of a fixed 600 frames — a flush at the counter alone yields a torn slot (11/14 sectors, status ERROR).

- 2026-09-21 P2 independent spot-check (Haiku, read-only, before reading the site doc): FR rows `battle_end`/`capture_wild`/`save` resolve in `pokefirered.sym` at the pinned addresses and their bytes match the FR US 1.0 dump (sha1 `41cb23d8…`); RR rows `battle_end`/`mon_given`/`pc_move` bytes match the RR base (md5 `8529f3a4…`); `rom_offset == address - 0x08000000` on all six. Input to F-3/S rows; companion-kind bytes were not part of this check (pinned by the generator's own test on `bf8e94a0…`).

- 2026-09-21 P2 FR fixture: `tests/fixtures/gen3/firered_town.sav` made by scripted NEW GAME with the walk-out PINNED from pret/pokefirered c75f352 (spawn `src/new_game.c:84` (6,6); warps from `data/maps/PalletTown_PlayersHouse_{2F,1F}/map.json`; path = BFS over `data/layouts/*/map.bin` collision bits; FRLG stairs/doors are arrow warps entered by a held press) — receipts `docs/gen3/probes/{makefr,bootcheck}_firered_town_2026-09-21.txt`: counter −1→1 then 1→2, 14/14 sectors, party empty (pre-starter). F-6 FR half. The intro legs stay timed (verified by outcome only). pret/pokefirered is now cloned at the pinned commit under `E:/Google Drive/SLink/.cache/pret/pokefirered`.

- 2026-09-21 P2 RR `_b` fixture: `tests/fixtures/gen3/rr_town_b.sav` (sha256 `13da0f15…`) derived through the pinned RR chunk/extension mapping (Codex cx-288ff3e9; 20 unit tests incl. a 750-slot owned/foreign box population, RTC preservation, corrupted-chunk refusal) and boot-checked on the lane: counter 2→3, 14/14 sectors, identity `BB` #3559012160 distinct from A. F-6 RR `_b` half. `saveram_name()` now defaults to BizHawk's underscore→space rule; gamedb-known cartridges (vanilla FR) still need `--saveram-name`.

- 2026-09-21 P3 first semantic fire, vanilla FR: `docs/gen3/probes/shadow_fr_play_2026-09-21.txt` — the shadow observer (lua/gen3/shadow_run.lua over the real Entry.build, admitted by hash) registered 21 sites, rejected 0, dropped 0, and `map_load` fired exactly once at frame 1058 as the scripted walk entered Oak's lab (callback_address == site 0x0805xxxx, raw_r15 = +2, thumb); frame_control counted 1789 over the run. PHYSICAL positive for S-1 on FR `map_load`; RR companion duos (six, all PASS with the observer) show 19 registered and only frame_control (reachability scan R2 in flight). The play leg itself failed by design of the game: the starter needs the Route 1 Oak intercept first (leg reorder queued).

- 2026-09-21 P3 RR battle census: `docs/gen3/probes/census_rr_battle_2026-09-21.txt` — from `slink_prebattle.State` the pinned RR `battle_end` hook (0x08015BD0, inside ReturnFromBattleToOverworld) fired exactly once at frame 2484, the frame the function entry fired in the entry-hook run; exec hooks deliver at every tested ROM address on RR; `docs/gen3/research/rr_site_reachability.md` shows all pins reachable. PHYSICAL positive for S-1 on RR `battle_end`. The six RR duos observe only frame_control because they never reach the semantic sites (explode exits at the outcome byte; faint/boxsync/trade are commanded/native). Consequence for G3: RR coverage needs natural-play sources (scripted RR play), not re-pinning.

- 2026-09-21 P3 RR natural play: `docs/gen3/probes/shadow_rr_play_2026-09-21.txt` — with the observer beside `gen3_rr_scripted_play.lua`, PHYSICAL fires on RR companion: `battle_begin` x4, `battle_end` x5, `whiteout` x1, `map_load` x1, `save` x1 (positives for S-1 on those kinds, pending the differential). NEGATIVE: a real player faint (battler HP 0, outcome lost) produced no `faint` fire at the vanilla Cmd_tryfaintmon pin 0x080213C8 -> RR `faint` must be re-pinned to the CFRU battle-engine body (OPEN, P3). Driver defects (Codex cx-378ce251) queued to the authors; the fires stand.

- 2026-09-21 P3 FR natural play run 11: `docs/gen3/probes/shadow_fr_play_run11_2026-09-21.txt` — vanilla FR, observer beside `gen3_scripted_play.lua`: `map_load` (lab entry), `mon_given` (the starter, party 0->1), `battle_begin` and `battle_end` (the rival battle, won) each fired exactly once with callback == site. PHYSICAL positives for S-1 on those FR kinds (differential pending). Next stall: the lab exit walk after the rival leaves (map never changed).

- 2026-09-21 P3 RR faint capture + catch pin: `docs/gen3/probes/census_rr_faint_v3b_catch_2026-09-21.txt` — the CFRU cleanup-completion point 0x0909EED2 fires once per faint with gActiveBattler = the fainted battler (player faint: 0, counter 0->1), so RR `faint` re-pins there (side = gActiveBattler parity); the vanilla Cmd_tryfaintmon pin is dead on RR (replaced command table). RR catch input sequence pinned physically (Right, A, Right, Right, A, A from the action menu -> "Zigzagoon was caught!"), balls via the EWRAM pocket 0x0203C354.

- 2026-09-21 P3 RR `faint` PHYSICAL: `docs/gen3/probes/shadow_rr_faint_2026-09-21.txt` — after the re-pin (8eb2717, CFRU cleareffectsonfaint completion 0x0909EED2) the observer records `faint` once per faint through the RR wild_faint leg (5 fires incl. the player faint witnessed by HP positive->0 and playerFaintCounter 0->1), callback == site. RR coverage now: battle_begin, battle_end, faint, whiteout, map_load, save.

### Old-client characterization (P1)

`tests/unit/test_protocol_conformance.py` replayed against the twelve `*_old_client.jsonl`
transcripts (C1-3b format, six scenarios x 2 players). Every item the transcript-level
checkers flagged, with the evidence and the resolution now encoded in `conformance_map.py`:

- **Items 1 and 14** (`check_line_shape`, `check_tick_shape`) — flagged on every one of the 12
  transcripts. The old client's hand JSON encoder emits `{}` for an empty Lua table on
  `tick.enemy_party`/`tick.pc_boxes` instead of `[]`
  (`tests/fixtures/gen3/wire/infopanel_a_old_client.jsonl:2`, e.g. `"enemy_party": {}` outside
  battle). **Genuine deviation, harmless** — `server/server.py:1858-1860` iterates
  `msg["pc_boxes"]` (zero iterations either way when empty) and `server/server.py:1876-1877`
  reads it back through `bs.get("enemy_party") or []`, which folds a falsy `{}` to `[]`; no
  code path was found that distinguishes `{}` from `[]` while the value is empty. Encoded as
  the `disagreement`/`resolution` pair on conformance_map items `"1"`/`"14"`; resolution for
  the new client is "always send `[]`". Not yet a row in `docs/protocol.md` Appendix A
  (out of this card's lease) — flagged as a follow-up below.

- **Item 29** (`check_keyed_replies`, `party_mon`) — flagged in `boxsync_{a,b}` and
  `trade_{a,b}`. Two different causes, both **checker over-assertions (fixed)**:
  - `trade_a_old_client.jsonl` t=4185: the server issues `party_mon` for key
    `EBEF11DA:2BD6C8BF`. That key is exactly the pre-trade key of the incoming mon —
    recoverable from the `apply_trade` command's `blob_hex` at t=157 (first 8 bytes are
    PID+OT, each little-endian; byte-reversed they reproduce the key) — so it is one of
    protocol.md item 42's ("Prompts and trade") "two traded keys", for which the client is
    *required* to discard queued sync commands, not answer them. `check_keyed_replies` now
    computes `_traded_keys()` from `apply_trade`/`trade_done` and skips the reply requirement
    for a `party_mon` on one of them.
  - `boxsync_a_old_client.jsonl` t=501: the server issues `party_mon` for key
    `32A55077:2BDDC8BF` and the connection's very next record (t=502) is `_disconnect` — no
    trailing `tick`/`safe` at all. `party_mon` is a deferred, safe-state-only command (item
    31); the capture simply ended before the client had any frame to act on it, which proves
    nothing about whether it would have replied. `check_keyed_replies` now only counts a
    missing reply as a violation once `_had_safe_opportunity()` finds a later `tick`/`safe`
    with `in_battle` false for that player (a duplicate reply is still always a violation,
    since that is positive evidence rather than an absence).

- **Item 30** (`check_keyed_replies`, `memorialize`) — flagged in `explode_{a,b}` and
  `faint_{a,b}`. **Same checker over-assertion as boxsync's item 29, confirmed by the client
  source**: `explode_b_old_client.jsonl` t=29 issues `memorialize`, and every `tick` through
  the disconnect at t=62 still reads `in_battle: true` — the client never reaches the safe,
  out-of-battle frame that `exec_memorialize`
  (`lua/clients/gen3_frlge_client.lua:1781` `local function exec_memorialize(key)`) requires
  before it runs; its native path (`lua/clients/gen3_frlge_client.lua:1799-1815`, the
  companion-patch `OP_MEMORIALIZE`) is additionally async (`memorialize_finish` at
  `:1751-1775` lands the ack on a later poll). The capture ends mid-battle-end sequence
  before any of that can happen. Same `_had_safe_opportunity()` gate as item 29 resolves it.

- **Item 28** (`box_mon_failed`, A2) stays a real, source-cited disagreement in
  `conformance_map.py` but is **not** in `EXPECTED_VIOLATIONS["old_client"]`: none of P1's six
  scenarios ever drives `box_mon` on a key that is, at that moment, the target player's only
  party mon (checked directly: both `boxsync_{a,b}` `box_mon` calls target a party of three).
  Declaring it evidenced here would be an unevidenced claim; a dedicated "box the last mon"
  capture is needed to put it on the wire. `test_old_client_transcripts_together_reproduce_
  every_disagreement` (new; asserts the union of all old_client transcripts covers
  `EXPECTED_VIOLATIONS`, replacing a too-strict per-file check that demanded every scenario
  reproduce every disagreement) will start failing the day a scenario like that gets added
  without also updating `EXPECTED_VIOLATIONS` — that is the intended drift catch.

Follow-up (outside this card's lease): `docs/protocol.md` Appendix A has no row yet for the
`{}`-vs-`[]` empty-list encoding (items 1/14) — the existing rows stop at A18; add one
(`docs/protocol.md`, not touched by this card).

Fixture sizes and the `.jsonl.gz` recommendation are in
`tests/fixtures/gen3/wire/README.md` ("Sizes and compression"); total for the 12
`*_old_client.jsonl` captures is 4,632,435 bytes (~4.4 MiB).

## Recorded limits

- **Keyed sync-command re-issue window.** `SYNC_INFLIGHT_RECONCILES = 6` is a re-issue
  suppression window, not an ack deadline; a hold longer than six reconciler passes can produce
  re-issue churn and, because the reconciler may then issue the opposite command to the partner,
  a pair can transiently sit in opposite locations or a user deposit can be undone. Convergence
  without record loss is the claim; "never corruption" is not asserted (§5.4).
- **RR trade abort without completion** is force-committed by the watchdog with inferred keys,
  same as today; this migration neither widens the conditions that reach it nor adds a rollback
  protocol (§5.6).
- **Disabled-foundation write guard.** On `gen3_frlg` an unsolicited or stale `apply_trade`
  writes nothing because the `writes` gate has no `trade` reason on that pack — asserted in the
  P4 lupa suite, not by cancelling prompts alone (§10).
- **C-4 fault injection is MODEL by construction**, same recorded limit as Gen 1's C-4: a running
  cartridge has no way to make the executor raise on demand.
- **Exec-hook timing (#3801)** — the historical BizHawk GBA exec-callback timing caveat is
  external/web-sourced, not in-tree; the P1 probe matrix is what settles it on this host, not the
  issue report itself (§3 mGBA hook feasibility note).
- **Deaths 33-35 normative resolution**: benched `force_faint` is deferred to the checkpoint (as
  Gen 1 does), not delivered same-frame; item 33 is rewritten in P6 rather than left contradicting
  shipped behaviour (§5.6).
