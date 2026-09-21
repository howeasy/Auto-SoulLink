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
