# RC status and planning estimate

## Current September 9 integration status

The runtime is progressing toward an RC; the complete Gen 1 release gate is
still **NO-GO**. Several independent workstreams are now active in the sweep
worktree. The earlier cutoffs below are historical evidence, not current totals.

| Area | Implemented and checked | Remaining RC qualification/work |
| --- | --- | --- |
| Cold start and initial save | Actual downloaded launchers, normal New Game receipts, paired enrollment and isolated SaveRAM readback; cold Y/Y, R/B and B/Y evidence | Include this path in the complete native/gameplay campaign |
| Ordinary execution | One bounded owner, actual network grants, durable per-step source progress, exact frame returns and held refusal; 3-case live matrix | Continuous Y/Y improved from about 11 to 28–29 FPS; full owner/transport timing and practical vanilla-speed behavior remain open |
| Starter identity | Source hooks, atomic inventory/identity pairing, cross-title runtime tests; source-qualified temporary tutorial name borrowing passes 96 focused checks; input-only Y/Y completed both Oak tutorials and linked both original starters | Cold route reached the end of the rival battle, then stopped on a grant-response deadline; Center/native round trip remains unqualified |
| Capture and scripted grants | Real source decoders and client observers; atomic frame settlement, exact source references, successful-purchase ordinals and clause handling | Full live acquisition campaigns, retirement completion and remaining rule consequences |
| Static encounters and NPC exchanges | Source-generated decoders/observers, static battle lifetime, NPC member migration; canonical NPC OT token fixed without widening nicknames/player names; all seven source kinds now staged and audited through the actual frame bundle | Live timing and full campaign checks |
| Native trade | Original native animation/save service remains in use. Composed entry shares owner/context/journal; precise renewal acceptance boundaries; atomic inventory handoff | The complete cold-start launcher → receptionist → both original animations → ordinary reentry live run |
| Linked faint and memorial | Held faint/save execution, compact deltas, preimage repair, archived proof history and held live lifecycle. Storage policy handles active grave/owned rotation and terminal last-mon disposition | Separately scoped battle instruction path is under live negative-control testing; no production enable yet. New retirement causes and storage-policy live boundaries |
| Storage, evolution and optional modes | Synchronized storage/quarantine read, apply, save, compensation, archived-member return and reserved-box birth relocation implemented; saved storage/deferred-faint attribution checked; ordinary evolution collector and runtime wired | Complete evolution migration regression, Explode and Rival Swap bindings; live storage/campaign/recovery checks |
| Reconnect/recovery | Explicit ownership loss/holds, durable obligations and same-core paths | Complete moving/native interruption and restart/reconciliation matrix; do not infer recovery from an unchanged frame |
| Packaging/UI | Reproduced cartridge selection and native launcher configuration tested; shared runtime compatibility cut published and adopted by UI task | Final producer/Manager contract, selected RC defaults, complete package and human playthrough |

Recent focused evidence must not be summed as one disjoint suite: acquisition
integration 91 cases; native accounting 41; actual composed-entry compatibility
68 (including 7 new entry cases with modeled platform/transport); collector and
native source handoff 58. The last broad sweep remains the 5,902-pass historical
cutoff below; it predates these additions and is not a current release result.

The shared compatibility cut `7810e69c48be2a2684d8abad14ea6f83044b877e`
contains only ten reusable runtime/cache/router/test/doc files, based on
`08e825b3f1e1dbcc576ce57efb28a523196f797d`. Its isolated archive passed 3,204
unit/integration cases, 15 unchanged existing skips and 11 subtests. All 21 new
cases, 230 Lua files and required Ruff checks passed. GitHub run 34304231830
passed, and the UI task adopted the cut. This does not publish Gen 1 readiness.

The prior estimate below remains a low-confidence historical planning range.
A revised completion forecast needs the composed normal-gameplay/native live
round trip and its remaining blocking findings; it should not be extended after
each individual component test.

## Earlier September 8 broad cutoff

The broad unit/integration run passes **5,902 cases**, with two existing Windows
symlink-privilege skips, in 638.98 seconds. Required bug-class Ruff checks pass;
275 Lua files parse. The final frame pending-command guard and its initial-save
fixture adjustment were additionally exercised by the 34-case frame/save run.
This is not the complete release gate: ordinary gameplay and campaign lanes are
still unqualified.

Real downloaded launchers now observe normal New Game, enroll both players,
and complete an isolated initial SaveRAM write/readback. Five live cases cover
Y/Y, R/B, B/Y cold starts and two existing-save fixture paths. All six post-save
bedroom screenshots were inspected and are clean. Saves are scheduled after both
initial observations, avoiding a join/save ordering deadlock. Existing fixture
launchers invent neither bootstrap nor save history.

Shared frame accounting, checked event references, atomic frame source/inventory
settlement, sparse observations, and current/historical held-frame checks are
implemented and tested. The frame grant/return API remains private: no default
ordinary network authority or unified native/ordinary client loop is selected.
Authorized initial-save/faint/memorial writes still need explicit inventory
attribution before the first production frame baseline can be trusted.

Scripted-grant decoding now uses actual call B/C registers, box prepend order,
fresh HP/experience/stat experience/PP/stat checks, cross-container collision
refusal and pinned prices. Move-set/catch-byte proof and a real grant observer
remain open. The first decoder's 132 synthetic passes were not accepted as
qualification; independent review found and corrected mirrored fixture errors.

Current planning range: **25–45 active engineering/test hours, approximately
12–20 substantial work cycles**, plus the final human playthrough. This is a
low-confidence remaining-work estimate, to be revised after a normal-gameplay
to native-trade round trip works through the production launcher. Remaining
work centers on unified frame ownership/policy, battle command application and
drain, command-write attribution, remaining acquisition/storage/evolution/rule
bindings, recovery policies, final packaging, and the full release matrix.

The inventory has no missing/unclassified nodes at its stable cutoff:
5,756 unit / 148 integration / 267 live / 45 duo; 5,463 portable and 441 named
unit/integration deferrals. Unrelated stale or missing acceptance proofs remain
explicit. Shared event-reader cut `08e825b3f1e1dbcc576ce57efb28a523196f797d`
is published, with GitHub run 34287624425 passing.

## Earlier September 8 integration cutoff

The production held launcher now completes paired memorial preparation, compact
delta execution, isolated SaveRAM flush/readback, and per-player ACK closure.
Explained partial writes require fresh repair authority. Same-core transport
reconnect preserves obligations. Completed evidence is archived atomically rather
than copied into every active state snapshot; a ten-paired-death growth regression
passes. The final bounded memorial/factory matrix passes seven live cases,
including Yellow/Yellow. These cases retain an unchanged gameplay frame.

A production BizHawk launch factory now verifies the ROM and launcher, creates
separate per-player configurations and SaveRAM directories, and holds a local
launch lease. Launcher endpoints support an archive bundle. Manager's
`POST /api/runs/gen1` creates a fresh durable run before starting its server;
real Manager startup and launcher retrieval pass an integration test.

Capture source receipts and a read-only observer are implemented, but are not
yet connected to ordinary gameplay settlement. Sixty-two unit cases and three
original-engine Red/Blue/Yellow delivery cases pass. The live cases compare full
WRAM/SRAM and frame outcomes with the observer disabled and enabled, including
Yellow's boxed Kadabra behavior. Normal New Game bootstrap evidence is now in
development; it grants no execution or save authority by itself.

The latest broad run had 5,280 passes, two failures, and two existing Windows
skips. The two failures were new tests retrying a fault-latched SQL runtime;
they now reopen it and pass their focused rerun. Later integration changes
still require a new broad run. **There is no final broad-green or RC claim.**

Remaining release work is moving-frame authority and observation integration,
initial save, native receptionist/trade integration with the ordinary owner,
remaining acquisition/storage/rule settlement, terminal/full/active-box memorial
policy, new-core recovery, and the final release matrix and human playthrough.
The estimates and counts below are historical cutoffs, not current completion
percentages.

Shared publications `b23856140b8616ca21bb0d291c8cdd59ff750673` and
`9433c80c6bc0e9c43a0624521eedb67f7a886294` have passing GitHub runs
34266875074 and 34272742657 respectively. Generation-specific integration stays
in `gen1-rby-code-sweep-8d06e2` pending its own full qualification.

## Earlier evidence cutoffs

Latest [memorial/save proof](MEMORIAL_SAVE_PROOF.md): independent complete-image
verification, command/file binding and legacy collision refusal are implemented.
108 new focused tests and six live tests pass, including 17 original-save image
comparisons and Yellow happiness/mood engine checks. Durable reservation,
prepared execution and paired death closure still need production integration.
No new ordinary execution permission or UI producer handoff is implied.

Latest broad cutoff: 5,200 unit/integration passes with two existing Windows
symlink skips; separate randomized final-cartridge and bounded-host matrices are
described below. It is not release approval. Work stays in gen1-rby-code-sweep-8d06e2.
The memorial turn's final 108-case focused run covers the subsequent full-grave
test and codec-error normalization; the broad cutoff preceded that last test.

Latest [held faint authority](HELD_FAINT_AUTHORITY.md): downloaded launchers now
execute only a server-permitted, pending death's faint write under an unchanged
overworld frame hold. All ten real launcher cases pass, including Y/Y and mixed
titles plus withheld-permission refusal. Broad5,073/2existing skips;85 final
focused/compatibility passes;4,638 portable passes/437 declared deferrals. Four
later generic UI suspension tests pass separately. Shared permit bc3ad9de has
green GitHub CI. Ordinary gameplay remains held; memorial/save/recovery,
controlled startup and remaining acquisition policies remain required.

Earlier [ball/death settlement](BALL_AND_FAINT_SETTLEMENT.md): ordered successful
bag delivery activates a player; validated active faints mark the linked pair
dead and publish one peer command. Exact HP receipts close that command while
memorial/recovery holds remain. The broad run passes 5,040/2 existing skips;
final shared-lookup correction passes 50 focused checks. Fifteen live source,
physical-kernel and launcher regressions pass, including Yellow/Yellow.
That cut preceded the now-qualified held-overworld faint adapter. Other command
authority, memorial/recovery and ordinary gameplay remain unfinished.

Earlier [starter settlement](STARTER_SETTLEMENT.md): proved starter sources now
join stable inventories to create logical acquisitions, pending rule captures
and one paired rule/identity link. All nine cartridge pairings and both arrival
orders are covered, including Yellow/Yellow with clauses enabled. The broad
run passes 4,997/2 existing skips; the final peer-inventory correction passes
43 focused and three original-script pair cases. Shared helper 085acbe has green
GitHub CI. Ordinary gameplay, other acquisition/activation/faint bindings and
physical recovery remain unfinished.

Earlier [engine signal binding](ENGINE_SIGNALS.md): read-only battle/poison faint
and starter call/return hooks now publish through the held client/server journal.
The full suite passes 4,956 tests with two existing Windows skips in 268.50s;
57 focused checks, nine live checks and a stronger three-title observer-on/off
differential pass. Complete WRAM/SRAM and frame outcomes match with and without
the observer. All 261 Lua files parse under Lua 5.4. These are controlled engine
and held-launcher checks: stable inventory-to-rule/identity settlement and the
ordinary frame/recovery lifecycle remain required.

Earlier [temporal inventory evidence](TEMPORAL_INVENTORY.md): ordered checkpoint
publication, complete inventory differences and atomic replay/audit storage.
The broad run took 250.81s; a subsequent shared callback guard passes the final
95 focused checks and six real launcher regressions. All 259 Lua files parse
under Lua 5.4. Shared helpers are published at 160412c with green GitHub CI.
The initial-history blocker stays: battle/source predicates, rule/identity
settlement, command closure and ordinary execution are still required.

Earlier [initial inventory enrollment](INITIAL_ENROLLMENT.md): production empty-run
creation and real client inventory enrollment pass all nine pairings in unit
checks and actual Y/Y,R/B,B/Y launcher cases. Six launcher regressions pass with
unchanged frames/WRAM/SRAM. Full4833passes/2skips took219.75s;258Lua5.4 parses and
required Ruff pass. Initial evidence binds context only and retains a gameplay
blocker; it does not infer captures, links, clause credits or history.

The later [shared helper correction](SHARED_HELPER_CORRECTIONS.md) closes malformed
host identifiers, callback-time context crossings and sparse/converter stage
configuration gaps. Current broad4803passes/2skips took201.25s;112 explicitLua5.4
shared checks and two actual Y/Y/R/B saved-receptionist consumers pass. Latest
shared head77c7562 is green in GitHub34183965202. The16-case live matrix below is
the preceding integration cutoff, not a rerun of every lane for this narrow fix.

Readback-bound preparation, actual trainer names, typed native release and durable
disconnect/watchdog/reopen interruption are now implemented. All9 ordered native
pairs and3 release-receipt fault/reopen cases pass. See
[the preparation evidence](NATIVE_PREPARATION_RC.md). The subsequent
[native runtime wiring cut](NATIVE_RUNTIME_WIRING.md) connects the admitted-ROM
verifier, real TCP command router, save-image policy and automatic coordinator.
The [receptionist/save runtime](RECEPTIONIST_SAVE_RUNTIME.md) now passes16 live
cases:13 native TCP scenarios and3 original SaveGameData differentials. Actual
receptionist flow is covered for R/B,B/Y,Y/Y and reproduced-UPR Y/Y, with full save
files verified before COMMIT and both original animations retained. Cancel,
CABLE CLUB, decline, answered-after-expiry and transport faults are included.
Current blockers are ordinary observation/bootstrap
selection, ordinary walk-to-query integration, interrupted/idle-expiry cancellation and recovery,
natural rule/storage/campaign qualification, packaging and the final human gate.
Generated launchers still deliberately select held-service mode. The current
native network tests use production execution authority, with explicitly supplied
linked-run/map bootstrap and physical entry to the original query. Receptionist
query/menu/offer/return, partner consent and saves use production executors.
Normal application trade activation
still depends on the remaining UI/observation/launch bindings.

Current evidence: `.cache/receptionist-save-full.xml` (4770passes/2skips,202.57s),
`.cache/receptionist-save-live.xml` (16passes,663.97s),257 Lua5.4 parses and the
exact workflow bug-class Ruff rules. Shared frame correctioncfed9be is published
with GitHub34168470179green. Shared staged-command/file-image helpers97046232 are
published with exact GitHub34182490380green; their isolated tree passes3019 tests
with15 baseline environment/fixture skips and226 Lua5.4 parses. The earlier push
approval block was resolved by the user's explicit authorization.

The engine and shared foundations are well advanced. Production runtime integration,
host/recovery authority, UPR and release qualification remain substantial work.
The earlier planning baseline was 25–40 substantial implementation/test turns,45–80 active
engineering/test hours, approximately6–10 full working days if work is continuous.
These are low-confidence planning ranges, not a promised calendar date. Waiting
for inputs and the human session is additional. Host recovery and UPR carry the
largest uncertainty; significant defects could push the estimate higher. Revisit
after the first qualified production-runtime trade. The UPR component pipeline has
now passed generation, semantic, structural and native final-cartridge checks.
The earlier range has not been reissued as a new estimate. Status-only replies do not
count as implementation turns.

| Area | Done | Remaining for RC |
| --- | --- | --- |
| Canonical sources/layout | Pinned R/B/Y builds, symbols, source/ROM guards | Final artifact revalidation and remaining generated-data comparisons |
| Codecs/identity | Exact66-byte RBY codec; shared logical registry and player-scoped keys/stats | Complete acquisition/evolution/NPC exchange and physical reconciliation bindings |
| Core rules | Faint battle-HP, Explode moves, snapshots and several rule corrections | Natural-game clauses, whiteout/rebuild, Rival Swap, Explode, pending-operation coverage |
| PC/boxes/memorials | Native differentials, active box, stat reconstruction, save/readback components | Synchronized storage, capacity/slot limits, reconciliation and persistence matrix |
| Yellow | Verified cartridge PC policy; native Pikachu trade handling | Complete synchronized PC, follower/save/campaign and recovery behavior |
| Trade engine | Original animations, evolution/learning, append; admitted-ROM bounded authority; both full world/current-box saves and files verified before COMMIT | Controlled reset/load recovery and full campaign integration |
| Receptionist/partner | Existing NPC query/menu/offer/ACK/return over TCP, native consent, saved preparation; canonical/UPR Y/Y and mixed titles; cancel/Cable Club | Ordinary entry lifecycle, busy delivery, automatic idle expiry and interrupted retirement |
| Coordinator | Atomic COMMIT/outboxes, both verifications before migration, both typed release ACKs, receipt failure/reopen; automatic verified-phase driver, actual consent and pre-COMMIT closure receipts | Interrupted cancellation lifecycle and physical recovery policy |
| Durable runtime | Shared sessions/journals/stages, native trade/save, starter/ball/death settlement, exact faint ACK and permitted held-overworld writes in generated launchers | Remaining acquisition/initial-history policies, other command authority, memorial/recovery and controlled ordinary stepping |
| Host control | Independent hold, source-qualified bounded frames, normal load/reset invalidation, exact native server grants, pacer and writer lease | Controlled reset/load/rewind/debugger recovery and ordinary resumption |
| Companion artifacts | Deterministic clean and scanned UPR R/B panel+trade and Yellow trade-only candidates; checked spans, UPS, native final-ROM tests, browser downloads and reproduced held-run adoption | Packaging and full final acceptance |
| Panel/SFX | ABI-3 generation/ACK/3BG protocol, wrap/timeout/canary, maps/Pokédex matrix and randomized final ROMs; SFX=false under allowed fallback | Controller/reset/rebind and final combined release matrix |
| Manager/UI | Read-only fact boundary, checked held launchers, shared cut adoption | Production lifecycle/feature facts, same-hash launch workflow, verified publisher |
| UPR | Complete catalog, exact-seed JVM pairs, Gen1 adapter, whole-ROM audit, final patch/rescan/native tests, browser E2E, reproduction-backed held launchers | Manager generation UI/API, ordinary runtime activation, imports and distribution |
| Browser/distribution | Current R/B/Y targets, full fingerprints, clean/combined-UPR real browser downloads/refusals and native final-ROM tests | Final packaging/asset manifest and integrated release validation |
| Release | Extensive component evidence and strict gate | Complete campaign/duo/recovery checks, refreshed proofs, docs and human session |

The older gameplay E2E cutoff is15passed/30failed; the30 fail on the guarded debug
fixture initializer. Add proper pre-run setup rather than bypass that guard.
There are346 acceptance requirements:36 current source-pin registrations,109 stale,
201 without registered proof. This is evidence accounting, not percent complete.

The following table is the historical planning baseline, retained for context.
Panel ABI-3, UPR production components and browser E2E have since advanced as
described above. It must not be added up as a current remaining-work estimate.

| Historical phase | Substantial turns | Active effort |
| --- | --- | --- |
| Final panel ABI-3 | 2–3 | 3–5h |
| Host execution/recovery | 4–7 | 8–16h |
| Ordinary runtime/bootstrap/adapters | 4–6 | 8–14h |
| Core rules/acquisitions/storage | 4–6 | 8–14h |
| UPR catalog/scan/provenance | 4–6 | 8–14h |
| Manager/browser/packaging | 2–4 | 4–8h |
| Final gates/repairs/docs/human session | 3–5 | 6–10h |

Shared mechanisms already cover protocol, journals, execution, trade coordination,
identity, recovery barriers, holds, save-file persistence, launchers, inspection,
writer leases, patch composition and stat arithmetic. Cartridge addresses, rules
and evidence stay in generation adapters. Other generations have adopted shared
cuts. Optional SFX, presentation polish, optimization and speculative refactoring
stay deferred. Full required correctness and release evidence are not deferred.

Panel ABI-3 continuation: implemented locked mailbox controls, odd/even staging, three actual BG portions before reveal/ACK, A wrap, B/START close,180-frame missing-data/lease closure, changed-generation refusal and persistent canary detection. R/B each passed12 native protocol scenarios; the full13 combined-artifact cases and7legacy menu/launcher cases passed. Broad unit/integration:4,288passed/2existing Windows symlink skips; subsequent focused manifest/publisher/panel/rebuild checks:102passed. Parsed241 project Lua files plus the old-reader fixture. Evidence:.cache/panel-full-first.xml,.cache/panel-final-companions.xml,.cache/panel-legacy-live.xml,.cache/panel-final-targets.xml. Shared staged_panel9f7f6c7 is published. Remaining: broader panel maps/Pokedex and controller/reset qualification, then host/native authority and production runtime integration.
