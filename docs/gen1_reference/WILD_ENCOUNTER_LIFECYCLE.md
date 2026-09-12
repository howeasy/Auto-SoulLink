# Wild encounter and no-catch lifecycle

This slice binds the existing shared no-catch policy to Gen 1 source receipts.
It does not infer failure from a missing party member or a grace timer. The
new source/runtime tests use modeled memory and real journal handlers; they
do not qualify emulator gameplay.

## Source boundaries

`tools/gen_gen1_wild_encounter_sites.py` reuses the independently verified
static-battle generator's `InitWildBattle+5` and `EndOfBattle` anchors. Generation
verifies the pinned source trees, symbols and original ROM bytes. Its output is
`wild_encounter_sites.json` plus the corresponding Lua table.

At `InitWildBattle+5`, `wIsInBattle` is already 1 and `LoadEnemyMonData` has not
run. The observer reads `wEnemyMonSpecies2` and `wCurEnemyLevel`; the enemy battle
struct would still contain stale data. `InitBattleVariables` has already set
Safari battle type for the Safari map range. The generator pins that source
predicate too.

At `EndOfBattle` entry, the battle result is final, while battle species/type/map
remain intact. The existing generator proves the sole call follows `StartBattle`
and precedes reset/evolution. KO, loss, flee, capture and wild flight reach this
boundary; a failed ball throw alone does not.

The observer emits only normal/Safari wild battle types. Trainer battles,
old-man tutorials, Oak's Pikachu battle and other non-delivering battle types
produce no encounter rows. Server decoding additionally records exclusions for
unidentified Tower ghosts (bag lacks Silph Scope) and the scripted Tower 6F ghost.
The latter is identified without assuming its clean species operand, which UPR
may rewrite. Ordinary identified Tower encounters remain eligible. Fishing is
not rejected merely because `wCurOpponent` is nonzero. A matched source-qualified
static origin routes its own lifecycle rather than spending the normal map area.

## Integration API

`gen1_wild_encounter_observer.new(options)` has the same private owner/held
callbacks and `peek`, `acknowledge`, `status`, `close` surface as other source
observers. Append its receipts to the single compound source list as
`{kind='wild_begin'|'wild_end', receipt=...}`. The receipt has
`schema='rby-wild-encounter-receipt-v1'`, `kind='begin'|'end'`, and one
`witness.frame`. Persist the combined list before acknowledging any observer.
No new execution owner, transport, clock or frame permission is created.

`gen1_wild_encounter_receipt.validate(...)` accepts the same exact admitted
variant, save identity, generation, physical instance and ROM arguments as the
other generation receipt decoders. Root's shared source dispatcher and returned
frame coverage must validate every witness before staging effects.

Call `gen1_wild_encounter_runtime.stage(runtime, state, document, player,
operation, message, frame_origin=..., frame_request=...)` after source acquisition
staging. It returns `result`, `commands`, and `records` for the same atomic frame
commit. Include inventory-only frames when a prior encounter awaits peer
settlement. Frames with no relevant receipts or deferred end return `None` and
do not create idle-frame history. Root must register `verify_state(stage)` and
`verify_journal(journal, stage)` in normal state/reopen audits. The standalone
`record` helper is for the existing unframed source API; it rejects a framed
participant without a proved compound origin.

Delivery consumes the open encounter immediately, before stable inventory or
identity settlement. Same-frame capture rows are processed before an end row
while preserving their original raw source indices. An earlier pending own
capture also suppresses a later spurious no-catch. A peer's unstable capture on
the same area, or a potentially conflicting family elsewhere, defers the decision
until its actual source settles. Missing begins, overlapping battles, backwards
frames and mismatched species/map/type fail without publishing effects.

`server/no_catch_rules.py` is generation-independent staged bookkeeping. Its
gift/resolved-area, own capture, either-player retry, already-notified dupes,
alive-family and partner pending-family behavior is checked against
`SoulLinkState._handle_no_catch`. It queues no UI or memory commands. Ball
activation additionally requires the verified Gen 1 ball source at or before
the encounter start.

## Physical retirement

A dead zone with a captured counterpart installs a distinct `paired_no_catch`
obligation and hold in `gen1-wild-encounters`, carrying the exact failed encounter
end reference and the counterpart's acquisition/member/current key. It calls
`gen1_retirement_runtime.schedule_job(..., cause={kind:'paired_no_catch',
obligation_id:...})`; it never pretends to be a Yellow-only grant.

The retirement adapter calls `retirement_source(document, player, obligation_id)`
for `{acquisition_id,key,member_id,reason,hold_id,hold_reason}` and invokes
`complete_retirement(stage, document, player, obligation_id, receipt_ref)` only
after its verified image/file ACK. The latter returns the updated component's
atomic journal record, which the caller must include. Shared scheduling revisits
pending no-catch jobs after a busy memorial/retirement closes. All unrelated holds
remain intact. A proved boxed counterpart participates in the same species and
retirement policy through an optional shared rule view derived from its settled
capture identity. Physical retirement also clears that exact boxed acquisition's
constraint; it does not clear any other pending acquisition.

## Remaining qualification

The root-owned compound source dispatcher/collector registration and actual
emulator no-catch/retirement campaign remain integration qualifications. A source
shape or unit count is not live evidence. Existing physical retirement recovery
restrictions remain in force, including its explicit active-grave restriction
where no source-specific birth proof exists. Clause-rejected peer acquisitions
defer no-catch while their existing acquisition constraint needs resolution; this
slice does not invent a replacement clause policy.
