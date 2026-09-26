# Gen 2 Gold, Silver and Crystal rewrite specification

Status: ready-for-agent
Execution status: P0 specification prepared and substantially executed since. The Gen 2 overlays
(native trade/panel/sound), engine sites and duo/live gates are BUILT with real live evidence
(98/98 sweep cells pinned at CODE_DIGEST `e8ca0067`; RC milestone tag `gen2-rc-evidence-2026-09-25`),
but no gate in `PLAN.md` §6.1 carries an owner signature yet, including G4 — see that ledger for
the authoritative per-gate state. BUILT is not ADMITTED: `tools/gen_gen2_admission.py --promote-overlays`
still gates the overlay rows on the owner's G4.
Planning source: `9c7e7acfef1a5c2e1dc7111e8dfdb0c71610b043`, reviewed 2026-09-22.

## Problem Statement

Players need Gold, Silver and Crystal Soul Links to obey the same verified rules and recovery
contracts as the Gen 1 rewrite. The existing Gen 2 client relies on polling, unqualified writes,
a staged fixture and client-reported verdicts. Those artifacts provide hypotheses to investigate,
not evidence that the replacement works. Native trade, the START-menu panel and native sound
must be present in the first release candidate.

## Solution

Replace the legacy Gen 2 binding with a source-pinned, profile-driven binding to the shared
Soul Link engine. Admit all three US titles, qualify Crystal first within each applicable phase,
and complete Gold and Silver before signing that phase. Preserve one Manager family,
"Gold · Silver · Crystal", and every Gen 2 title pairing.

The replacement uses byte-verified engine observations, independently qualified reads, one armed
write gate, played fixtures and saved-state oracles. Reusable lifecycle, transport, state and
presentation behavior belongs in shared modules; game binders supply cartridge facts and policy.
The release ledger remains the authority for applicability and evidence. This specification
defines behavior and acceptance; tickets and the sole coordinator checkpoint grant exact files.

## User Stories

1. As a player, I want Gold, Silver and Crystal supported, so either partner can choose a title.
2. As a player, I want any two admitted Gen 2 titles to pair, so mixed-title runs use one family.
3. As a player, I want unsupported cartridges refused, so the client never writes using guessed facts.
4. As a player, I want wrong-save reconnects refused without changing the run, so identities stay intact.
5. As a player, I want party and PC captures observed correctly, so a full party does not hide a catch.
6. As a player, I want the Ball-pocket gate respected, so the rules begin at the declared point.
7. As a player, I want species, gender and type clauses and shiny bonuses applied consistently.
8. As a player, I want my partner's faint propagated to active and benched members safely.
9. As a player, I want poison and whiteout recorded before healing erases their evidence.
10. As a player, I want PC transfers and ChangeBox synchronized without mistaking them for acquisitions.
11. As a player, I want memorials preserved across saving, so Box 14 remains consistent with the run.
12. As a player, I want evolution and NPC trades to preserve identity or refuse ambiguity explicitly.
13. As a player, I want a hatch treated as a daycare gift using the hatchling's identity.
14. As a player, I want roaming legends to be extra catches without consuming the map encounter.
15. As a player, I want the Bug-Catching Contest to have its own capture zone.
16. As a player, I want native Trade Center menus and animations, including a reliable decline path.
17. As a player, I want valid held items carried through trades and invalid payloads refused before commit.
18. As a player, I want a reloaded save to contain the exact traded record, including its held item.
19. As a player, I want readable HUD and native panel text and bounded native sound delivery.
20. As a player, I want reset and reconnect to preserve valid queued work without replaying stale identity.
21. As a maintainer, I want independent oracles and reproducible artifacts before claiming a feature passed.
22. As a maintainer, I want shared changes to preserve Gen 1 behavior and remain bindable by future games.
23. As a release owner, I want runnable gate evidence, explicit limits and a recoverable cutover.
24. As a player, I want peer presence added after RC without allowing a ghost object to enter my save.

## Implementation Decisions

### Authority and sequence

The latest owner rulings, the plan's shared-module decisions and the reviewed binding steps take
precedence over historical annex prose. Research marked resolved establishes only its stated
source conclusion; it never grants implementation, live qualification or release authority.

The approved base recipe is local master plus `80261f3`, `959c578` and `910dbdd` from the Gen 3
lane. The coordinator records the actual integrated commit, merge-base/cherry-pick evidence,
Gen 1 regression receipts and Gen 3 drift baseline before G0. The integration is not certified
by this specification. Each later gate records the current Gen 3 tip and a shared-surface drift
decision. Spec preparation and ticket drafting do not imply G0 is signed.

| Phase | Completion shown to the owner | Gate |
|---|---|---|
| P0 | Verified integrated base, spec, complete substep tickets and ledger/register entries | G0 authorizes implementation |
| P1 | Reproducible local/CI builds, source lock, artifact matrix and linker-slack report | G1 signs pins and matrix |
| P2 | All three packs, byte-pinned sites, two-path readers, complete coverage map and fail-closed runner skeleton | G2 signs game facts and zero UNMAPPED |
| P3a | Generic pairing binding and complete alias/order/refusal matrix with independent review | G3a signs shared change or verified no-change disposition |
| P3b | Oracle, eight fixtures, live reads/signals/writes, client/duos, packaged and verified cutover | G3 is an internal rules milestone |
| P4 | Native panel, sound and trade; patched-artifact receipts reopened and closed | G4 is the first RC-eligible gate |
| P6 | Full frozen-cut verdict, distribution boots, Manager review and two-person attestation | G6 authorizes owner tag/shipment |
| P5 | Signed ghost design and lifecycle, then qualified ghost artifact | G5 occurs after shipped G6 |

Each implementation dispatch records exact exclusive files, source cut, prerequisite, first
falsifier, exit evidence, reuse decision and independent reviewer, and requires acknowledgment.
An extraction has its own shared-file and consumer leases. One writer owns each shared file;
the coordinator owns the emulator lane, evidence ledger and integration. ROM, patch or site
changes reopen affected receipts. No gate, push, merge or release claim is inferred from a pass.

### Titles, builds, artifacts and pairing

Pin pokecrystal to `7a7881d0d62e0ddbd82dcf10e7116807487ac651` and pokegold to
`656583c939d30f920a316177311a502dd222b57c`. P1 pins the assembler and output symbol/map hashes.
Build Gold, Silver and both Crystal revisions reproducibly; admit Gold, Silver and only the
Crystal revision identified by the local dump. The other Crystal build proves reproducibility,
not runtime admission. Every address and expected instruction byte comes from the pinned build.

Artifact rows distinguish PLANNED, BUILT and ADMITTED. PLANNED overlay/ghost slots carry no hash
and grant no admission. BUILT/ADMITTED rows require actual hashes; native overlays become ADMITTED
only when their reopened obligations close. Unknown hashes default to refusal. Randomized,
Archipelago, unknown-revision and corrupt artifacts gain no admission from a recognizable title.

Use one Gen 2 foundation and one rules adapter with title-specific packs. Enumerate G↔G, G↔S,
S↔S, C↔C, C↔G and C↔S symmetrically, including title-cased/lowercase aliases, arrival order,
reconnect and persisted runs. Gen 2 never pairs with another generation. Artifact compatibility
uses the adopted generic foundation/pairing-kind contract and adapter data; the matrix explicitly
records allowed and refused artifact-kind combinations rather than inferring them from title
compatibility. Native trade requires the qualified native capabilities on both halves.
Unknown or contradictory hello data is refused without changing state, caches or disk.

C↔C and G↔S are the representative duo lanes; a C↔G link scenario separately proves cross-title
admission. Each same-cartridge instance has isolated SaveRAM and attempt directories. All titles
pin CGB mode; runtime domain sizes, bank mapping and hook/frame alignment require live receipts.

### Shared mechanisms and game facts

Bind the existing rule engine, adapter boundary, connector, JSON codec, HUD sanitizer, sound
arbiter, GB gate harness and release-lane core. Preserve generic compatibility and event handling;
game-specific needs enter through adapter methods with inert defaults, never generation branches.

Generic client lifecycle is shared: connection-edge handling, hello-first scheduling, validation
pause/resume, deferred-queue ownership and dispatch, bounded retries, error containment, identity
invalidation and presentation lifecycle. Required binder inputs supply observations, readiness,
event translation, write policy and native ABI actions. Calling a client game-specific is not
permission to clone reconnect, queue or presentation behavior. Extract bounded interfaces from
existing consumers; a renamed whole client is not a reusable interface.

| Mechanism | Shared boundary | Required game/platform inputs |
|---|---|---|
| Hook registry | Registration ownership, all-site validation, ordered bounded queue, error latch, cleanup | Sites, filters and snapshots; GB bank/CPU mapping in a GB binding |
| Write permit | Scoped ownership, range narrowing, complete payload validation, provenance, guaranteed disarm | Domain, bounds, bank/pointer stability and explicit lifetime; operation builders per game |
| Checkpoint evaluator | GB anchor revalidation, bounded stack reads and caller/resume evaluation | Independently qualified state/ownership predicate and anchors |
| Admission | Actual-byte hashing, candidate evaluation, unique match, immutable result and explicit refusal | Catalog, ROM acquisition, anchors and permitted modes; unknown fallback off |
| Storage/receipt support | GB bank-to-flat conversion; validated-span executor only where both consumers need it; receipt transport | Box edits, active-shadow ownership, save kinds, checksums and durability oracle per game |
| Panel/mailbox | Versioned GB ownership, observed AWAIT transition, sanitized pagination and publish-before-state | Address, ABI/capabilities, offsets, tiles, deadlines, charmap and sound mapping |
| Qualifiers and charmap scanning | Bounded token scanning, fixture enumeration, provenance and report orchestration | Independent game decoders, checksums, stat controls and boot chains |
| Coverage validator | Neutral completeness, artifact/evidence joins, receipt provenance and fail-closed accounting | Per-game manifests, exceptions, applicability and oracle semantics |
| Duo witness/oracle pipeline | Required stages, attempt/artifact/fixture/source provenance and missing-stage refusal | Registered independent validators; no client RESULT verdict |
| Scripted-play harness | Input-step execution, timeout and evidence capture | Played route and game-state observations, never another game's oracle |

Each extraction states platform assumptions, both consumers, permitted behavior changes, affected
artifacts/lanes and rollback. Rebind Gen 1 in the same cut and retain independently reviewed Gen 1
physical regression receipts. Shared source transfers no evidence to Gen 2. The neutral coverage
validator is the explicit first-consumer exception: Gen 2 introduces it with unchanged reusable
contract tests; a fabricated Gen 1 consumer is unnecessary. The historical durable framework is
vocabulary, not an additional dependency list for this rewrite.

Gen 2 owns ROM/site tables, 48-byte party and 32-byte box layouts, names and 70-byte party blobs,
held items, split Special, 14×20 storage, Box 14 memorial semantics, save layouts, acquisition
namespaces, DV-derived gender/shininess, trainer and encounter data, native ABI and checkpoint
policy. Gold/Silver share proven layout facts but retain separate encounters/admission/site bytes.
Time of day changes encounters within a map rather than creating another area. Keys retain
the DV:OT:species shape; Unown form is display information. Hatch publishes `gift_daycare` with
the hatchling's key, roamers publish standalone `legend_<species>` pairs without consuming the
map, and contest captures use `national_park_contest`.

### Reads, observations, identity and writes

The production composition root is also the MODEL test graph. Reads are profile-driven and
agree with an independently derived Python codec on the same raw bytes. Derive codec arithmetic
and serialization directly from both pinned pret sources; research pseudocode and legacy values
are hypotheses. In particular, rederive CalcMonStats integer order, square-root rounding/cap,
Special-stat reuse and final clamp before selecting known-positive and discriminating controls.
Sharing token scanning or test orchestration must not make the oracle share production parsing.

Validate CPU sites and expected bytes at load and fire, with bank/caller context. Script-bytecode
labels are not execution sites. Capture attribution retains the acquisition through naming and
settling, distinguishes party insertion from box insertion and tests non-final/twentieth slots.
Capture faint-time bytes before HealParty; mask battle-result flags and never infer whiteout from
a transient LOSE. Observe deposit/withdraw/release/ChangeBox without inventing a release wire event.
Evolution and NPC trade use verified final identity; native link trade reports final identity
through trade completion and emits no duplicate capture, PC move or key-change event.

Hello carries actual ROM hash, player OT, foundation and artifact kind, and waits for a live
save plus qualified checkpoint or running battle. Title screens do not validate. Reset, departure
and reconnect invalidate stale evidence and aliases. Ambiguous full keys refuse writes on every
lookup path. Same-OT/different-full-key controls follow the explicit identity policy.

Every cartridge byte passes through a scoped armed gate with complete validation before the
first write and observable provenance. Active faint uses the verified battle-loop window;
ordinary deferred mutations use the qualified checkpoint. Preserve queue work during temporary
invalidity; tail retries apply only to the declared party-full/last-party-mon cases. Refusals and
completion use the shared command contract, including a failed-deposit response.

Ordinary current-box deposit/withdraw must succeed under the source-derived active-shadow and
backing-store ownership contract. The Box 14 memorial backing write refuses when that box is
active; qualify copyback/reassertion across a subsequent SAVE. Also refuse unsafe first-save and
New Game overwrite windows. The saved-at-least-once flag alone does not establish erase safety.
A boxed memorial has no HP/status field: prove placement and shared memorial state instead.

### Save durability, fixtures and native features

Distinguish a save attempt, success-only cartridge save completion, flushed host SaveRAM and
cold-boot reload. Witnesses bind attempt, ROM/source identity, frame, memory domain, ranges and
exact bytes. Reject absent, stale, torn or mismatched witnesses; assert expected scenario deltas
and untouched-region preservation. Model game recovery separately from strict witness validation.
Qualify Crystal primary/backup and Gold/Silver primary plus all five backup spans. RTC-tail
format and normalization require authoritative derivation and live evidence, not a guessed slice.

Produce eight saves: town and battle for each title, plus a second-OT Crystal town/battle pair.
Play New Game, naming, Mom, Elm's lab, starter selection and the route using scripted normal
inputs. Town is inside Elm's lab on encounter-free ground; battle is Route 29 grass. Injected
Poké Balls in the Ball pocket are the sole staging exception, asserted by the bag reader before
capture scenarios; neither the starter nor route is staged, and the Mr. Pokémon errand is not run.
Each fixture passes checksum/codec controls and cold boot → CONTINUE → re-save → reload with
GAME/PYDEC agreement. Qualify all eight before any read/write gate and requalify every lane use.

The native mailbox requires a proved allocation, banking/ownership/lifecycle contract and complete
writer exclusion. Linker slack alone does not qualify it; a failed feasibility gate stops P4.
Panel capability comes from the running artifact. Only a timely observed request grants painting;
publish content before STAGED and measure transient display receipts.

Native sound uses regenerated semantic mappings and the shared arbiter, with service qualified
separately for movement, idle START menu, text, battle and transitions. GetJoypad is conditional,
not a universal every-tick service point. Prove caller/context ABI, register/bank preservation,
bounded latency, busy/consumption and reset behavior; unqualified IRQ game-code execution is refused.

Native trade covers receptionist wait, room payload exchange, confirmation, both animations,
post-trade serial synchronization and save acknowledgment. Preserve the engine commit/evolution
sequence. Validate held items before commit and read them back on both sides. Decline, cancel,
timeout, disconnect, reset, save failure and illegal payload receive explicit controls.
SaveAfterLinkTrade is a partial Pokémon-data save; it never substitutes for the subsequent
scenario save, host durability witness or reload of the exact traded record.

## Testing Decisions

Test externally observable behavior through the production composition root, actual wire contract,
same-frame raw cartridge observations and independent save/server oracles. Prefer the established
Gen 1/GB harness seams. Every regression has a fast red-capable replay of the complete bounded
sequence before a fix; a live failure is not rerun unchanged.

P2 maps every requirement and every normative protocol assertion to stimulus, admitted artifact,
positive/refusal controls, oracle, receipt marker and lane. Separate natural-engine tests from
command-executor tests. Zero UNMAPPED proves completeness, not physical execution. Missing stages,
receipts, artifacts, prerequisites, skips, xfails, xpasses, deselections and errors fail closed.
Quick or selected lanes never yield release readiness. A shared server change additionally needs
adapter-boundary review and an independent nonauthor review; frozen implementation cuts receive
independent review before integration.

SOURCE proves pinned facts; MODEL exercises fakes or controlled logic; PHYSICAL uses the running
cartridge with an independent oracle. ENGINE firing proves a site, not behavior or durability.
PYDEC reads independent raw bytes; GAME reads the game's result; SERVER reads persistent/status
state externally; CONTROL tests independently derived known outcomes. Live inspect uses the same
frame/domain/ranges for Lua and PYDEC on all titles, with GAME controls for trainer, both badge
regions, held item, active box, gender and shininess. Temporal write safety needs observed sink
provenance and forbidden-state controls, not merely equal final saves.

### Requirement applicability: 53 rows, no evidence pre-filled

`SP` requires SOURCE plus PHYSICAL with recorded MODEL checks; `S` is SOURCE-only with its
declared generation/model checks; `M` is MODEL-only by design. `conditional` requires an explicit
enabling ruling or signed disabled/deferred disposition; `post-RC` is excluded until its gate.
An exclusion or limit is a disposition, never a behavior pass. The authoritative ledger retains
the detailed oracle and per-layer cells; this index preserves every row's applicability.

| Row | Obligation | Applicability |
|---|---|---|
| F-1 | Generated addresses and title layout differences | S |
| F-2 | Hook bytes on admitted artifacts | SP |
| F-3 | Complete lifecycle site table | SP |
| F-4 | Independent ROM-reader equality per title/time | S |
| F-5 | Species, item and evolution facts; egg sentinel distinct | S |
| F-6 | Eight played and reload-qualified fixtures | SP |
| F-7g | Separate Gold/Silver admission and data | S |
| R-1 | Same-frame live party/box/name differential | SP |
| R-2 | Source-derived stat CONTROL qualified against the game | SP |
| R-3 | Trainer, both badge regions, item and active-box GAME controls | SP |
| R-4 | Live-save/hello/checkpoint/reset validity | SP |
| R-5g | DV gender and shiny GAME controls | SP |
| S-1 | Runtime site timing and title differential | SP |
| S-2 | Party/box capture attribution and Ball-pocket consumption | SP |
| S-3 | Non-final and twentieth-slot box insertion controls | SP |
| S-4 | Battle/poison faint bytes before healing | SP |
| S-5 | Evolution and NPC-trade identity publication | SP |
| S-6 | PC operations and explicit release observation limit | SP |
| S-7 | Success-only save witness; CONTINUE/New Game distinction | SP |
| S-8 | Gifts/statics and hatch under gift_daycare | SP |
| S-9g | Roamer extra catch and map non-consumption | SP |
| S-10g | Separate contest capture zone | SP |
| W-1 | Armed/validated temporal write provenance | SP |
| W-2 | Battle-loop faint and bounded tail retries | SP |
| W-3 | Explode Mode | conditional; default disabled |
| W-4 | Rival team swap | conditional; default disabled |
| W-5 | Box 14 memorial ownership and save survival | SP |
| W-6 | First-save/overwrite refusal | SP |
| W-7 | Shared whiteout rebuild | SP |
| C-0 | Protocol conformance on production graph | M |
| C-1 | Explicit identity/hash and fail-closed admission | SP |
| C-2 | Same-save/wrong-save/WRAM-clear reconnect | SP |
| C-3 | Shared sanitized HUD and native panel rows | SP |
| C-4 | Fault injection | M |
| C-5 | Randomized admission | conditional; deferred pending owner ruling |
| C-6g | Complete title/alias/pairing/refusal matrix | SP |
| D-1 | Bilateral encounter link | SP |
| D-2 | Ball gate | SP |
| D-3 | Party/box sync and ChangeBox | SP |
| D-5 | Species/gender/type clauses and shiny bonuses | SP |
| D-6 | Linked faint, bench and active | SP |
| D-7 | Whiteout rebuild | SP |
| D-11 | Rival swap/explode duo behavior | conditional; follows W-3/W-4 |
| D-12 | Game-over transient HUD | SP or explicit signed recorded limit |
| D-13 | Refuse ambiguous full keys without writes | M |
| D-14 | Reconnect preserves links | SP |
| T-1 | Qualified Trade Center receptionist entry | SP |
| T-2 | Native confirmation/decline with unchanged saves | SP |
| T-3 | Bilateral apply/evolution/item validation and readback | SP |
| T-4 | Reload exact traded record and item | SP |
| N-1 | START-menu panel with transient receipt | SP |
| N-2 | Qualified bounded native sound and reset | SP |
| N-3 | Peer ghost and save exclusion | post-RC; SP at G5 |

The default first-G6 count is 41 REQUIRED physical obligations, four SOURCE-only, three MODEL-only,
four conditional and one deferred ghost row. Derive the count again from signed applicability at
each gate. Every applicable P row needs its declared independent evidence; the validator cannot
invent exemptions. Quote any accepted limit explicitly, including a D-12 disposition if used.

## Out of Scope

Archipelago support is documented post-RC backlog and excluded from implementation ticketing.
Peer ghost is ticketed only for post-G6 work. Time Capsule, mail, the unselected Crystal revision,
non-US/Virtual Console builds, Battle Tower and Mobile Adapter are excluded. The closed Gen 2
playthrough/deadzone/dupes scenario decision remains closed. UPR, Explode Mode and rival swap
remain conditional rather than silently enabled. Boxed linked RELEASE has no wire event and is
recorded as a shared-protocol limit. Fixture ball injection qualifies the bag state, not ball acquisition.

## Further Notes

Cutover first freezes the previous runnable bundle and untouched fixture/per-attempt saves.
Build packaging before the reference/import/launcher/test census. Distinguish paths removed from
paths replaced in place; replacement content must remain present at its expected hash. Rebuild
and boot extracted distributions per admitted title/pairing, then repeat fixture qualification
and required checks on the post-deletion tree. Rollback restores artifacts and saves together.

Remaining evidence work includes reproducible builds/assembler pin, exact local Crystal revision,
mailbox allocation, CGB frame/domain/bank qualification, RTC-tail contract, complete source-derived
acquisition/stat controls, native takeover/service windows and all physical receipts. No unresolved
fact is filled by a legacy implementation or research label. Post-RC ghost design additionally
needs free-slot ownership, collision safety and save-exclusion/restore across SAVE and CONTINUE.

References: [owner decisions and reviews](REVIEW_RECORD.md), [approved plan and shared decisions](PLAN.md),
[reviewed phase/substep bindings](GEN2_BINDING_PLAN.md#5-binding-steps-in-order),
[authoritative requirements and evidence cells](gen2_requirements.md),
[open factual obligations](OPEN_QUESTIONS.md), [wire contract](../protocol.md),
[shared-runtime boundaries](../shared_runtime.md), [local tracker rules](../agents/issue-tracker.md).
