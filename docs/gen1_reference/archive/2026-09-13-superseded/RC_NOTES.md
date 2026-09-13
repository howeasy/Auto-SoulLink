# RC decisions and follow-up notes

The user requested RC scope, with notes for work that can wait. This list keeps
nonblocking follow-up separate from unfinished required functionality. All work
remains in gen1-rby-code-sweep-8d06e2.

## Decisions made during integration

- **Memorial proof requires the complete saved poststate:** The independent
  [memorial verifier](MEMORIAL_SAVE_PROOF.md) binds exact preimage, command,
  reservation and save file. A complete image calculation is not an atomic
  physical write. Both players' runtime ACK/save closure remains required.
  Legacy identity collisions now refuse before writing; key-only retries cannot
  be promoted to success. Reservation ownership will be journaled, not inferred
  merely from a structurally dead nonempty box.

- **One held write is not a frame grant:** Generated initial-observation clients
  now request and consume an exact one-use permit before clearing a pending
  death command's party HP. Both host and game stay held. No-op completion also
  waits for permission; receipt completion does not clear memorial/recovery holds.

- **Activation has ordered source evidence:** Successful bag delivery of a ball
  permanently activates that player. PC destinations, failed delivery and
  non-ball items do not. Pre-ball faints preserve party ownership.
- **Death ACK is narrower than death completion:** The new durable route marks
  linked rules dead and queues one verified peer faint command. Its exact HP
  receipt clears that command only; memorial and recovery holds remain. Explode
  Mode and the default launcher's write-authority selection remain unqualified.

- **Source-backed starter settlement:** A later complete inventory now joins the
  verified starter call/return to create owned logical identities and rule links.
  Both initial inventories must be pre-starter; arbitrary existing rosters stay
  unqualified. Current HP/level/stats and Yellow's post-return byte are retained.
- **Exemption is a server binding decision:** The shared staged party-grant
  operation accepts only a generation-validated exempt source. This covers
  Yellow/Yellow even with clauses enabled and emits no pointless party retrieval
  or unqualified native presentation commands. Legacy heuristic behavior is not
  used by the new starter path.

- **Record engine faints before healing:** Source-qualified battle and poison
  hooks preserve the event even if the next overworld snapshot is healed. The
  source hooks and starter append are verified in controlled original-routine
  tests. Signal batches reuse the shared journal; cartridge sites and semantics
  stay in Gen1. Rule/command settlement and ordinary per-frame publication remain
  required before release.
- **Yellow starter return is not script completion:** The original script
  changes its catch-rate compatibility byte and follower/starter state after
  `AddPartyMon` returns. Use a later stable inventory for settlement; do not write
  the birth witness back over those cartridge changes.

- **Checkpoint differences are evidence:** Shared observation sequencing and
  keyed inventory comparison now support the durable RBY observer. Additions,
  removals, storage moves and HP-zero transitions do not by themselves authorize
  acquisitions, link changes or command completion. The source-signal and rule
  bindings remain required. Full-save checkpoint size optimization can wait;
  observing battle faints before blackout healing cannot.

- **Player-scoped Gen1 rule lookups:** Matching keys in different saves are valid.
  The production rule engine now resolves the actor's actual link half and keeps
  cached stats separate. Same-save ambiguity refuses rather than selecting a mon
  to faint. Gen3/AP retain their existing selection policy.
- **Correctness before indexing optimization:** The shared player_keys resolver
  scans authoritative link halves. An unscoped legacy projection is present only
  when it has one answer. A more elaborate index can wait until measured load
  warrants it; it must preserve these ownership tests.
- **Old caches are not authority:** Ambiguous old unscoped stats are not copied to
  either player. Fresh owned observations repopulate the scoped cache. A legacy
  Gen1 file containing duplicate same-player linked keys raises an error instead
  of returning a partially loaded run.
- **Historical key reuse is conservative for the RC:** A key still associated
  with a dead/memorial rule entry requires physical reconciliation before reuse.
  Automatic clearance based only on a dead status is deferred. No ambiguous
  duplicate is automatically killed to make room.
- **Full rule document now participates in trade:** Gen1TradeRules validates
  selection against the actual staged state and registry, then updates exact
  party blobs, stats and both halves after both results verify. It retains the
  original acquisition area, encounter history, rules and memorial data.
- **Canonical proof JSON:** Native preparation hashes must use the server's
  ASCII JSON representation. The shared journal_document helper handles Unicode,
  surrogate pairs, literal escapes and controls for integer JSON documents.
  Transport and local-store encoding are unchanged. Arbitrary floating-point
  canonicalization is outside this proof contract and is deferred.
- **Durable command envelopes:** The shared pump strips wire fields such as
  player/seq. A durable command must travel as {cmd, body: exact journal body}
  under that envelope, then be validated and unwrapped once by the Gen1 adapter.
  This preserves coordinator body hashes. RR adopted the same binding rule.

- **Configured durable route is implemented:** Gen1 has separate metadata-only
  admission, complete staged state/recovery composition, shared server/client
  pumps and exact nested body delivery. Actual Yellow/Yellow and Red/Blue hosts
  service journals and TCP under verified holds without frames or WRAM changes.
  Prepared-run launchers now select the owned held-service entry; ordinary runs
  and the old gen1_rby_client retain their prior path until gameplay qualification.
- **HELLO cannot drain old queues:** A Gen1 runtime bootstrap/snapshot with
  unpublished legacy queues refuses. Existing obligations must already be
  committed in the journal before this runtime is opened.
- **Shared server reuse is delivered:** acc3005 is published and RR adopted it
  unchanged, replacing duplicated server plumbing. Gen1 and RR still own their
  own admission, bootstrap and physical/recovery policies.

## Nonblocking follow-up

- Optimize the scoped link resolver only if profiling shows a need.
- Improve user-facing diagnostics for ambiguous imported legacy history; retain
  the current refusal and recovery requirement.
- After a default-name trade evolution, the rule cache uses the canonical species
  label until the next owned live name refresh. Native cartridge name bytes are
  already checked independently and are not rewritten by the rule binding.
- Broader cross-generation adoption of player-key helpers and SaveRAM persistence
  needs each generation's own tests. Shared code availability is not qualification.

## Required RC work still open

Default-launcher/observation-loop selection of the implemented durable service,
qualified cartridge command adapters, native receptionist
offer and partner-decision binding, qualified paired host recovery, final
clean/approved-UPR companions and provenance, browser patcher E2E, and the required
gameplay/release gates remain blockers. The nine paired cartridge integration
cases use real native results and files plus the complete rule document, but
offer/control inputs are still explicit test fixtures. Do not label them as
complete production receptionist-to-trade or Manager proof.

Trade recovery composition is now implemented: state, record, both outboxes,
validated ACKs and recovery history publish together. Offers do not own parties;
acceptance through both native closure receipts blocks ordinary reconciliation.
Configured runtime trade routing requires an explicit complete generation policy;
native UI/host evidence in the new routing tests is still modeled. The default
held-service launcher supplies no trade policy. Stopped prepared Gen1 runs now have a read-only journal path; unknown SQLite
files still do not fall back to stale links.json.

## Launcher continuation

- Prepared runs use an immutable journal/run/contract descriptor, and both server
  and Manager download run-bound, file-checked held-service launchers. This mode
  remains explicitly unable to grant ordinary frames or execute physical commands.
- Default local journal paths are per run/player in local application data, with
  a controlled portable/test root override. Network reconnect never resets them.
- The Gen1-only HELLO now requires run_id. Old unselected development journals
  whose admission records lack that field require explicit migration/rebind; no
  automatic deletion or empty-state fallback is performed.
- Shared stat arithmetic and checked-launcher/reader cuts are published for Gen2
  and Gen3 reuse; each generation must qualify its own native semantics.
- Consumed Gen2's03bbcda formatting-only overlay after verifying AST equality.
- Consumed UI's0a391c7 shared duo isolation closure and4f6a832 visible keep-alive
  follow-up, then cc539c0 for the reproduced Popen/PID-registration race.53 focused harness cases pass. UI's actual Gen1 E2E cutoff is15 natural
  cases passed and30 failed on the guarded /api/debug/set_pokeballs initializer.
  Keep those30 required cases outstanding; do not bypass the operation guard.
  Existing sync_retrieve_failed/orphan memorial diagnostics remain storage inputs.

Imported shared harness code retains upstream I001/E731 style findings in tools/e2e_duo.py. Its exact behavior/ownership cut is preserved; style-only cleanup is deferred to the shared owner and is not treated as a physical correctness result.

## Atomic trade/runtime continuation

- Shared optional component composition and semantic routing seams preserve
  existing unconfigured callers. The RBY binding validates current private owners
  and physical contexts and refuses generic command ACKs for native trade work.
- Recovery retains terminal abort/release obligations until both clients supply
  independently validated closure receipts. Finalization alone grants no frames.
- Added a complete read-only pending-command ID index. Delivery pagination must
  never be used to infer that all physical obligations have completed.
- The configured policy tests cover all nine ordered RBY pairs and both
  initiation directions, one-sided completion/reopen, atomic SQL rollback,
  context changes and private-control refusal. Two actual TCP cases cover
  offer/prompt-delivery/decision publication. Native and host evidence is modeled.
- Remaining immediate work: bind actual receptionist/partner receipts, select
  the qualified native/save adapters and controller, and admit the final artifacts.
  Held-service startup still cannot grant ordinary or native recovery frames.

## Native UI continuation

The actual receptionist and native partner prompt are now client adapters feeding
durable offers and typed decisions to the coordinator. A shared journal extension
retains exact terminal event identity and acknowledged detector baselines. The
RBY save composition sends native-applied evidence once, requires the existing
owned SaveRAM flush/readback, and then emits the terminal file-verified receipt.
All nine ordered pairs pass from real UI through both original animations and
both verified files; the previous nine paired cases also pass. See
[NATIVE_UI_CLIENT.md](NATIVE_UI_CLIENT.md) for evidence and boundaries.

The first integrated Yellow/Yellow run exposed a collision between intermediate
applied evidence and terminal verification for the same command. Exact persisted
completion operation IDs now distinguish them; an explicit regression covers it.
Only terminal acknowledgement can retire the inbox command.

Still required: ordinary-runtime/artifact selection, real network timing and
preparation authority, native abort/closure scheduling and recovery. The new test
driver deliberately pauses emulated frames while waiting for its file transport.
It does not qualify a scheduler or host hold. Existing native No/B/refusal engine
coverage and new receipt-policy checks remain separate from a full production
cancellation/recovery flow. Optional presentation polish stays deferred.

Trade/runtime verification cutoff:4,187 unit/integration tests passed with2 existing Windows symlink skips;14 actual native-pair/held-network/launcher cases passed in120.00 seconds. Evidence:.cache/trade-runtime-full.xml and.cache/trade-runtime-live.xml. Shared72b91aca302a15272df5aadfc2b68beab652357f is published and sent to Gen2/Gen3/UI.

After that cutoff, consumed owner-published ea5a550 capture_spawn and9aac348 runner delegation after exact preimage comparison. This removes duplicate PID/handle checks.69 focused shared harness tests pass (.cache/trade-shared-harness.xml); the full suite was not repeated for this separately tested adoption.

Native UI cutoff:4,230 unit/integration tests passed with2 existing Windows symlink skips (81.19s);18 actual paired trade cases passed (180.73s), and5 actual held-network/launcher cases passed (20.75s). Parsed238 current Lua files plus the frozen v1 reader fixture. Evidence:.cache/native-ui-full.xml,.cache/native-ui-pairs.xml,.cache/native-ui-held.xml. Shared client-journal26aee4348a27e799b95a8f6ba9b0eaeb7ad0395c is published and handed to Gen2/Gen3/UI. No default gameplay/trade activation is claimed.

## Overnight continuation: panel, bounded host, UPR

Final browser/admission cutoff: `.cache/browser-full.xml` has 4,538 passes and
two existing Windows symlink skips in174.01s. Actual browser cases cover31
clean/combined-UPR scenarios with exact downloaded hashes and no uploads. A
subsequent review found grant resurrection if revocation occurred inside the
private verifier; the window now requires its same pending request after the
callback. `.cache/window-revocation-final.xml`:37 focused passes. Lua5.4 parses
247 files; CI correctness lint passes. The real index remains empty and HEAD is
79d5172; all intended changes remain in this worktree. Shared7a5c7aa is published.

RC activation is still blocked by the production physical verifier/router and
ordinary observation lifecycle. Native cancellation/recovery, full campaigns,
packaging and the final human session remain. These are tracked requirements,
not optional polish. Current launchers stay held and no fixture authority is
selected for real gameplay. Other workstreams were told the exact scope.

Following the broad cutoff below, the host now invalidates normal same-frame and
older savestate loads and queued native/controller resets before another frame
(12 actual R/B/Y cases). Command-window codecs, private issuer checks, Lua/Python
interoperability and real TCP replay/peer-loss tests pass (54 focused cases).
The generation-specific physical verifier remains unselected. Eight actual held
runtime/launcher/window cases pass after the shared pump changes. Cartridge-rate
pacing also passes, including a complete randomized Yellow/Yellow native trade
with both animations and files verified. See [shared-execution-window.md](../shared-execution-window.md).

UPR follow-up found a concrete Yellow TM48 text overflow for long move names.
The adapter preserves the neighboring dialogue and the scanner now enforces
canonical symbol boundaries for all TM/starter text. This targeted fix is tested
with a real seed selecting THUNDER WAVE. Existing UPR category tests are rerun
on the revised bridge. Optional style cleanup stays deferred.

The broader panel matrix passed 12 actual cases, each with 12 native protocol
scenarios: R/B x Viridian Center/Indigo lobby/Safari Center x Pokédex absent/present.
Evidence `.cache/panel-map-matrix.xml`: 144 scenarios, 12 passes in 89.58 seconds.
Fixtures derive map geometry, objects and Pokédex flags from pinned source/ROM.

Bounded host mechanism evidence now includes six R/B/Y pause/hold cases and three
complete native trade pairs, including Y/Y. See
[shared-bounded-execution.md](../shared-bounded-execution.md) for the exact scope.
Operation-specific authority, reset/load rebind and production selection remain
required. The unchanged hold actuator is reused; this is not an ordinary ticket
or a recovery bypass.

The complete UPR settings catalog, exact-seed external bridge, sequential pair
producer and strict provenance are implemented. Actual repeated JAR output and
pair tests pass. Source review identified implicit ghost/trainer-move side effects;
the generation-owned adapter preserves the locked behavior without modifying the
JAR. See [UPR_RC_PIPELINE.md](UPR_RC_PIPELINE.md). Full semantic scanning, final
patching/admission/publication and the final release gate remain open.

Overnight cutoff: 4,440 unit/integration passes and the two existing Windows
symlink skips in 129.04 seconds (`.cache/overnight-full.xml`). Separate actual
UPR final-cartridge matrix: 13 passes, including both original animations and
changed evolution methods; producer publication: four passes. CI correctness
lint passes. The release inventory now collects 4,311 unit, 131 integration,
186 live and 45 duo nodes; collection is not execution evidence. Registration
checks passed 70 tests. The full release gate and its no-skip requirement remain
open. No completion percentage is inferred.

## Canonical companion and admission continuation

The new canonical builder composes checked R/B panel+trade and Yellow trade-only
candidates and reproduces both generated profiles and local UPS files exactly.
The durable metadata path admits those exact installed artifacts; legacy admission
stays clean-only. Generated held launchers pin the expanded27-file closure and
continue to withhold ordinary/native-recovery execution. The unchanged shared
RuntimeLease36821a1 now excludes a second Gen1 server writer before journal mutation.
See [COMPANION_ADMISSION.md](COMPANION_ADMISSION.md).

All9combined-cartridge trade pairings passed, plus2held launcher pairs and2R/B
panel smoke cases. This does not finish the locked final ABI-3 panel work: the
existing compatibility layout, A-page behavior and fallback are still present.
Generation/ACK staging, A wrap,180-frame missing-data closure and canary/recovery
requirements remain required RC work, not optional polish. SFX stays false under
the specification's explicit fallback. Approved UPR and browser publication remain
closed. Existing RGBDS STRSUB deprecation warnings are retained as cleanup notes.

Companion/admission cutoff:4,280 unit/integration tests passed with2 existing Windows symlink skips in98.66s; 13 combined-artifact live cases passed (9native pairs,2held launcher pairs,2panel smoke cases), followed by5 held-launcher regressions on the final entry/lease code (including the2companion pairs). Parsed240 project Lua files plus the frozen v1 reader fixture. Evidence:.cache/companion-final.xml,.cache/companion-live.xml,.cache/companion-panel2.xml,.cache/companion-held-final.xml. Shared patch-plan6369c0b is published; RuntimeLease36821a1 is reused unchanged. Both participants must expose native trade and the canonical codec; unpatched participants refuse. Final panel ABI behavior, ordinary/bounded native authority and UPR/publication remain open.

Panel ABI-3 continuation: implemented locked mailbox controls, odd/even staging, three actual BG portions before reveal/ACK, A wrap, B/START close,180-frame missing-data/lease closure, changed-generation refusal and persistent canary detection. R/B each passed12 native protocol scenarios; the full13 combined-artifact cases and7legacy menu/launcher cases passed. Broad unit/integration:4,288passed/2existing Windows symlink skips; subsequent focused manifest/publisher/panel/rebuild checks:102passed. Parsed241 project Lua files plus the old-reader fixture. Evidence:.cache/panel-full-first.xml,.cache/panel-final-companions.xml,.cache/panel-legacy-live.xml,.cache/panel-final-targets.xml. Shared staged_panel9f7f6c7 is published. Remaining: broader panel maps/Pokedex and controller/reset qualification, then host/native authority and production runtime integration.
# September 7: native preparation and durable interruption

See [native preparation and suspension](NATIVE_PREPARATION_RC.md) for the current
readback-bound preparation and automatic lifecycle interruption slice. All nine
ordered native pairs and four UPR/paced cases passed. Reconnection alone no longer
silently treats a persisted native COMMIT as uninterrupted. Production physical
verification/router, native cancellation/recovery and ordinary observations remain
RC blockers. No default launcher activation is included.

Final cutoff for this continuation:4,604 unit/integration passes and2 existing
Windows symlink skips;12 paired native/release-receipt-fault cases;9 original
native/fault regressions;4 final combined-UPR/paced closure cases. All selected
emulator cases passed with no skips or deselection.248 Lua files parse under
Lua5.4 and the project error-level Ruff check passes. The native lease retains
its intent after inbox pruning, and typed release receipts now retire both server
outbox obligations. Shared suspension hook e1d2acf is published; the worktree HEAD
and actual index remain unchanged. Full RC approval still requires the open gates.

The later [native runtime cut](NATIVE_RUNTIME_WIRING.md) wires actual TCP,
admitted-ROM frame authority, production save-image validation and automatic
coordinator transitions. Its final six live cases pass (366.86s), including
delayed replies, real socket loss and reproduced combined-UPR Yellow/Yellow.
Default launchers remain held because ordinary observations, natural native UI
scheduling/cancellation, full pre-trade save freshness and controlled recovery
are not yet qualified together. The [CI correction](CI_CORRECTION_2026-09-07.md)
records all thirteen repaired shared branch heads and their successful runs.

September7 partner-runtime continuation: actual native consent now flows through
the production TCP policy, replacing the consent fixture. ACK-bound native return
precedes preparation; B decline and YES received after coordinator expiry retire
both obligations without trade/save effects. Stable eight-case native matrix
passes432.37s, including Y/Y and reproduced UPR Y/Y. Shared JSON span scanning,
flat checked frame scopes and one-second empty sync polls restore playback within
the unchanged timing limits. Full unit/integration:4711 passes,2 existing Windows
symlink skips,199.83s.252 Lua5.4 parses and exact workflow bug-class Ruff pass.
See [partner runtime evidence](NATIVE_PARTNER_RUNTIME.md) and
[the verified full-save boundary](PRETRADE_SAVE_NEXT.md).

The user approved shared publication. Frame primitives3649e2d and the follow-up
budget/clock correctioncfed9be are pushed, with exact green GitHub runs34167236628
and34168470179. Phase/digest/context/binding changes no longer refund the same
operation's frame budget inside a service; unrepresentable frame deadlines fail
before scheduling. Whole-service replacement still needs generation recovery
accounting. The working HEAD/index remain unchanged.

September7 receptionist/full-save cutoff: [the runtime flow](RECEPTIONIST_SAVE_RUNTIME.md)
now owns an actual original query through native menu, durable offer and return,
then both full save files before paired COMMIT. Both vanilla animations and final
file/return proofs remain required.16 selected live cases passed in663.97s;
4770 unit/integration tests passed with2 existing Windows symlink skips in202.57s.
257 Lua5.4 parses and the exact workflow bug-class Ruff rules pass.24 full32KiB
comparisons match original R/B/Y SaveGameData. Ordinary bootstrap/walk/default
launch activation, controlled interruption recovery and final rule/storage/campaign/
packaging/human qualification remain RC work.

Reusable staged_command and save_file_receipt helpers are published as97046232f4b17e883a7dfe9f19c5e3bb2f52bfb3,
codex/shared-staged-command-v1, parentcfed9be. Exact candidate3019passes with15
baseline environment/fixture skips and11 subtests,226 Lua5.4 parses; GitHub34182490380green.
Both Gen2 and Gen3 consumers have the handoff. No shared helper grants physical
authority or imports RBY cartridge semantics into those generations.

Subsequent independent boundary review produced [shared helper corrections](SHARED_HELPER_CORRECTIONS.md).
Host-shape child89ef524, context/configuration child eefcbba and explicitLua5.4
syntax child77c7562 are published; final GitHub34183965202green. Full current
Gen1 regression4803passes/2unchangedWindows skips,112 explicitLua5.4 shared checks,
two actual saved-receptionist native consumers and257Lua parses pass. Sparse
stages and failed converter results can no longer silently drop obligations;
context-changing callbacks cannot carry effects/progression/ACK across generations.

September8 initial-enrollment continuation: production create_runtime starts with
empty rules/identities and emits checked held launchers. A coherent owned initial
inventory and detector baseline publish atomically over the durable route. Exact
party/current/inactive box evidence, duplicate keys, save identity, immutable
admission context and persisted-record integrity are checked. No Pokémon members,
captures, links or Pokéball credit are inferred; ordinary execution remains held.
Thirty unit cases, six actual launcher cases and4833broad passes/2existing Windows
symlink skips pass.258Lua5.4 parses and requiredRuff pass. See INITIAL_ENROLLMENT.md.
The old held-only test save contained inconsistent XP; the enrollment test fixes
the physical fixture before boot and keeps server bootstrap empty. Production
codec validation and transport limits remain unchanged. Optional Claude review
could not start through the connector, so no independent review result is claimed.
