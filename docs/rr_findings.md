# RR baseline findings ledger

Source baseline: `adf3362d26557aefcebf7aa3b217fec70a7d0421`.
Paths below are repository-relative evidence pointers into `E:/Google Drive/SLink`.
All rows remain unresolved for release acceptance until tested against the exact candidate.
Binary/source proof and controlled-host reproductions are distinct from live gameplay proof.
The implementation baseline now includes the published shared/UI handoffs recorded in
`rr_release_plan.md`. Original line numbers below identify the audited baseline, not moving
candidate line numbers. A source finding must be reproduced before its repair is closed.

Every row applies to both required configurations (Default MGM off/off and on/on) unless
its eventual capture demonstrates a narrower scope. This is required coverage, not a claim
that the original defect was observed in both modes. All features listed below are required.

| ID | Class | Finding and evidence | Required regression |
| --- | --- | --- | --- |
| RR-N01 | Binary proof | Parameterized NPC helper leaves template gfx upper byte uninitialized; RR consumes bytes 1 and 3. `patch/src/handlers.c:1318`; engine `0x0805E830`, `0x0805E752`. | Stack-poisoned template, full gfx16, geometry/tile identity; ghost and PC NPC. |
| RR-N02 | Binary proof | Ghost overrides palette number without transferring RR refcounts; destroy decrements the current slot. `handlers.c:1239`, `lua/peer_ghost_npc.lua:155`; RR `0x09042594`. | Repeated spawn/despawn/avatar/scene cycles preserve all unrelated palette references. |
| RR-N03 | Source proof | Non-field handler writes visibility through former ghost sprite ID after possible scene reuse. `handlers.c:1809`. | Existing ghost into battle/menu, no non-owned sprite writes. |
| RR-N04 | Controlled runtime | Spawn clears staged avatar; image-only cache omits palette/animation-only updates. `peer_ghost_npc.lua:93,125`, `handlers.c:2042`. | Production spawn and respawn preserve complete coherent avatar. |
| RR-N05 | Controlled runtime | Posting queued mailbox operation erases prior unconsumed completion. `lua/mailbox.lua:488`, client `:1965`. | Completion retention under queued traffic and sequence wrap/reset. |
| RR-N06 | Controlled runtime | Shared payload buffers are written at enqueue time, overwriting an earlier operation's payload. `lua/mailbox.lua:480`. | Immutable queued payloads and leases across async scenes. |
| RR-N07 | Unresolved ownership | Retained libc allocator metadata overlaps native state. Normal gameplay reachability is unproven. Arena `0x0203F76C..0x0203FBAF`. | Call/write instrumentation and supported-path ownership evidence; any conflict blocks layout. |
| RR-N08 | Source finding; RR collision proof pending | Ghost movement updates current coordinates but leaves previous coordinates at the spawn tile. `drive_ghost` in `patch/src/handlers.c`; collision code may retain a phantom occupied tile. | Reproduce collision at old/current tiles against the RR binary, then verify coherent previous/current coordinates through motion and teardown. |
| RR-N09 | Controlled sender and native CPU proof | Camera-offset displacement freezes or invents ground movement when camera follow/pan differs from sprite motion. `docs/rr_reference/PEER_POSITION.md`. | Actual sender with fixed/panned camera, normal follow, rebases, ownership changes and recorded/live motion. |
| RR-S01 | Controlled runtime | Native deposit failure falls back by stale slot and moves another mon. client `:2495`. | Reorder before refusal; original operation cannot mutate the replacement slot. |
| RR-S02 | Controlled runtime | Memorial verification failure still emits `memorialize_done`. client `:1753..1770`, `:2528`. | Contradictory ST_OK readback remains unresolved and emits no success. |
| RR-S03 | Source proof | Withdraw/memorial native preconditions omit vacancy/expected identity/count safeguards. `handlers.c:2083,2131`. | Occupied destination, stale identity/count, last-mon refusal and canaries. |
| RR-S04 | Source proof | Storage status/timeout can substitute for full destination proof. client `:2461..2489`. | Every success proves source removal, intended destination, uniqueness and unchanged neighbors. |
| RR-B01 | Controlled runtime | Reload during already-active borrowed party exposes borrowed mons in hello/tick. client `:1915,3033`. | Active SwapState classified before admission/baseline/snapshot. |
| RR-B02 | Controlled runtime | Timer-confirmed faint fails to consume counter credit, allowing false later faint/whiteout. client `:3785`. | Delayed counter followed by transient zero HP. |
| RR-B03 | Controlled runtime | Battle-end cleanup discards a pending death before confirmation. client `:2975`. | Final KO/LOSS on same and neighboring frames. |
| RR-B04 | Controlled runtime | Debounce advances previous-party state and loses whiteout living-state edge. client `:3652,3808,4466`. | Last-mon delayed confirmation retains whiteout evidence. |
| RR-B05 | Controlled runtime | New battle overwrites prior encounter context while grace remains active. client `:2740,4084`. | Chained encounters resolve each original area once. |
| RR-B06 | Controlled runtime | Overworld predicate admits script-owned storage writes; settle timeout overrides failed predicate. `lua/memory_gba.lua:537`, client `:2608,3897`. | Per-operation ownership, long-held script/exp/evolution contexts. |
| RR-B07 | Controlled full-client proof | Explosion can use stale party/battler indexes, touch a borrowed party, reset PP/action state on duplicate delivery, or mutate a progressed turn. `docs/rr_reference/EXPLOSION_GUARDS.md`. | Unique real identity at each write; retained obligations, duplicate refusal, verified action-selection readiness and no wrong-slot/turn mutation. |
| RR-T01 | Controlled runtime | Patched native trade staging is nested inside the absent-patch branch. client `:2221`. | Real scene starts with admitted patch; no silent completion fallback. |
| RR-T02 | Controlled runtime | Watchdog commits native trade ownership without verified completion. `server/state.py:473`. | No peer or one-peer receipt cannot manufacture completed ownership. |
| RR-T03 | Controlled runtime | Trade confirmation sends stale offered blob despite newer observations. `state.py:548,634`. | Fresh paired prepare with identity and payload digest reservations. |
| RR-T04 | Controlled runtime | Same-token arbitrary keys are accepted as trade results. `state.py:646`. | Command-specific expected identity and permitted evolution readback. |
| RR-I01 | Controlled runtime | Save identity derives from the leading mon's OT and rejects valid traded lead. `state.py:872`. | Save-trainer identity independent of party order and ownership. |
| RR-D01 | Binary comparison | Reachable RR gender ratios disagree with handwritten table. `server/pokemon_data.py:291`; BaseStats `0x097B98EC`. | Every admitted species and ratio boundary; actual clause results. |
| RR-D02 | Binary comparison | Permanent evolution edges connect IDs assigned different clause families. `pokemon_data.py:360`; table `0x097CD9B0`. | All permanent edges and explicit form aliases. |
| RR-D03 | Data/source proof | Encounter generator merges physical tables and includes NONE entries. `tools/gen_rr_encounters.py:279`. | Physical table provenance and individual probability totals. |
| RR-D04 | Binary comparison | Raichu type differs; type generator writes a path runtime does not load. `tools/gen_rr_types.py:28`. | Exact-ROM type mapping and generated/runtime path agreement. |
| RR-D05 | New coverage gap | Catalog omits additional nonzero species records beyond its named domain. | Verify exact extent and identities before claiming complete species coverage. |
| RR-U01 | Controlled JS runtime | Dashboard loads CommonJS calc entry without its browser dependencies. `server/server.py:251`. | Actual browser engine initialization and calculation. |
| RR-U02 | Controlled JS runtime | Numeric move IDs are passed to a name-based calculator constructor. `server.py:3708`. | Adapter-resolved move names, known nonzero damage examples. |
| RR-U03 | Source proof | Live calculator lacks required inputs and static inference overwrites observations. `server.py:176`, `calc/src/js/slink_bridge.js:355`. | Provenance/freshness, effective battle state and observed-value precedence. |
| RR-U04 | Controlled runtime | Native panel renders memorial members as alive boxed entries. `server.py:2357`. | Authoritative link status across party absence and panel paging. |
| RR-U05 | Artifact comparison | Advertised output fingerprint differs from applied reproducible UPS bytes. `server/patcher.py:40`. | Metadata generated from exact release artifacts. |
| RR-V01 | Harness inspection | RR emulator configs/stubs/results and GBA saves are shared across runs. `tools/e2e_duo.py:300`, `tools/run_gate.py:81`. | Isolated run/player paths and exact child-process cleanup. |
| RR-V02 | Assertion inspection | Visual PASS and disappearance/dual-command cases bypass intended proof. `lua/tests/test_live_ghostshow.lua`, `lua/tests/duo/scenario_faint.lua`, `tools/e2e_duo.py:673`. | Required explicit oracles; real one-player action and partner propagation. |
| RR-R01 | Pinned host source proof | Stock rewind restores before the hold check; preframe callbacks occur after that check; a savestate load can restore core memory and then fail without a Lua load notification. `docs/rr_reference/RESET_LOAD_INTERLOCK.md`. | Stop/revoke before restored BUSY execution, including late-failed loads, Power reset, rewind and direct execution bypasses. |

## Verified mechanisms to retain

- All 25 compressed-box pointers match the clean and current patched RR ROMs.
- The 58-byte storage conversion agrees with inspected RR conversion instructions; represented
  fields and boundary canaries passed 250 deterministic cases. Some party fields are reconstructed.
- Both RR shiny palette paths and the predicate classify XOR <= 7; retain the < 8 classifier.
- The existing Lua Explosion mechanism remains the production mechanism; the previously problematic
  native controller path is not a rewrite target.

No row may be closed solely by a passing helper test or a historical standalone result file.

## Severity, feature ownership and implementation disposition

P0 blocks release because it risks mutation loss/duplication, false death, divergent
ownership or unproven native memory. P1 blocks a required feature or reliable normal play.
P2 is presentation correctness; it still blocks this release's complete feature inventory.
The original failure and the required regression in each row form its reproduction target.
Actual reproduction traces belong to that row's exact candidate/run manifest.

| Findings | Severity | Affected features | Current implementation disposition | Regression location |
| --- | --- | --- | --- | --- |
| N01-N04 | P1 | Ghost, PC NPC, battle/menu graphics | Resource repair implemented; private live validation in progress, no visual acceptance | `tests/unit/test_rr_mailbox_v2.py`, `tests/rr/native/`, release ghost/native inventory |
| N05-N06 | P0 | All queued native operations and buffers | ABI2 retention and payload leases implemented; native scene contention pending | `tests/unit/test_rr_mailbox_v2.py`, release native/storage/trade inventory |
| N07 | P0 | Entire native companion | Open; layout has not expanded and zero observed allocator calls cannot close it | `tools/rr/arena.py`, `lua/tests/rr/arena_probe.lua` |
| N08 | P1 | Ghost collision and motion | Reproduction and RR collision-contract verification required | Release ghost collision/motion inventory |
| N09 | P1 | Ghost ground position | RR-only sender correction implemented; actual normal trace retained, corrected-client fixed/panned scenes pending | `tests/unit/test_rr_peer_position.py`, `tests/rr/native/test_peer_position_cpu.py` |
| S01-S03 | P0 | Deposit, withdrawal, memorialization | Lua context/readback and native guards implemented; physical gameplay proof pending | `tests/rr/runtime/test_storage_context.py`, release storage inventory |
| S04 | P0 | Complete native withdrawal acceptance | Legacy v1 reproduced accepting corrupt PP/status/attack. Explicit v2 readback uses pinned full100-byte oracle; local loader/native coordinator and production selection remain pending | `tests/rr/runtime/test_withdrawal_evidence.py`, `docs/rr_reference/WITHDRAWAL_EVIDENCE.md`, live storage inventory |
| B01-B06 | P0 | Party ownership, death/whiteout, chained acquisition | Context/temporal repairs implemented; durable runtime binding and live evidence pending | `tests/rr/runtime/test_temporal_observations.py`, `test_rr_regressions.py` |
| B07 | P0 | Explosion target and turn ownership | Local guards and exact selection-state proof implemented; existing Variant-3 unchanged, durable settlement/live duo gates pending | `tests/rr/runtime/test_explosion_guards.py`, `tests/rr/reference/test_explosion_selection.py` |
| T01-T04 | P0 | Native trade/evolution and member ownership | Serializable native transaction and independently validated receipts still required | Release interactive trade, contention, restart and evolution inventory |
| I01 | P1 | Save admission with a traded leading Pokémon | Shared SaveIdentity seam and RR SaveBlock2 provider tested; new RR runtime still needs selection | `tests/unit/test_rr_admission.py`, shared SaveIdentity/state/dispatcher tests |
| D01-D02 | P1 | Gender/species clauses and identity migration | Exact-ROM reference extracted; runtime tables and explicit form-policy migration pending | `tests/rr/reference/`, acquisition/clauses inventory |
| D03 | P2 | Encounter guidance | Physical encounter-table/probability repair pending | Release encounter guidance inventory |
| D04-D05 | P1 | RR types, species domain, calculator | Exact1376-record extent and35 name corrections reviewed; inactive catalog refuses unresolved IDs1038/1214/1224. Runtime adoption remains pending | `tests/rr/reference/`, `docs/rr_reference/RR_CATALOG.md`, calculator and clauses inventory |
| U01-U03 | P1 | Calculator execution/provenance | Waits for reviewed UI producer and RR observed-battle binding | Release presentation/calculator inventory |
| U04 | P2 | Memorial panel/board styling | UI contract frozen; authoritative RR presentation integration pending | Release memorial/panel presentation inventory |
| U05 | P1 | Browser patching/distribution | Candidate build emits exact fingerprints; final patcher/package metadata adoption pending | `tests/rr/native/`, distribution inventory |
| V01-V02 | P0 | Trustworthiness of all release evidence | Isolated runner and strict expected inventory implemented; old weak assertions cannot count | `tests/unit/test_rr_native_gate.py`, `test_rr_release_gate.py`, full release verifier |
| R01 | P0 | Reset/load/rollback and paired execution | Held/unheld ownership component tests do not close restoration bypasses; no general interlock or production capability activated | `docs/rr_reference/RESET_LOAD_INTERLOCK.md`, recovery inventory |

Identifiers in this table use the `RR-` prefix from the detailed rows. Component passes
are progress, not a release disposition of fixed. The executable release inventory remains
uncompleted; no required campaign, soak or visual result is inferred from this ledger.
