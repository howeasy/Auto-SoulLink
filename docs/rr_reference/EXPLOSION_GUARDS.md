# RR Explosion ownership guards

This bounded repair preserves `memory_gba.forceExplodeBattler` and its existing
Variant-3 menu-skip write sequence. The native forced-move/controller path stays
inactive. `rr/explosion.lua` provides local request deduplication, identity/context
prerequisites, guarded reinforcement and deferred linked-death settlement. It
does not activate durable execution or the paired host barrier.

## Reproduced defects before repair

The first five tests in `tests/rr/runtime/test_explosion_guards.py` were run before
any production edit. All five failed against the unchanged full client loaded
by `RRHarness`. Baseline client Git blob:
`2a21e558f88583c0509c3ca101c9597381b42b59`; unchanged memory helper blob:
`f9c6ebe0695251f673f7c5d51fc53eb8c9a02a1a`.

| Full-client fixture | Observed before repair | Required behavior now tested |
|---|---|---|
| Incoming party index names333 while outgoing BattlePokemon still names111; command targets333 | All four outgoing111 moves become153 | No write until raw battler identity and index both resolve333 |
| After arming111 in slot0, party reorders333 into slot0 and111 into slot1 | Settlement zeros333's HP in old slot0 | Re-resolve111 uniquely;333 stays unchanged |
| Repeated command after PP drops5→4 and controller progresses3→4 | PP resets4→5 and controller regresses4→3 | Existing local obligation is retained without resetting either |
| Native borrowed-party state is active, with a matching key in borrowed RAM | Borrowed battler's moves become153 | Refuse borrowed ownership and retain the real obligation |
| Doubles target moves from player battler0 to2;333 now owns0 | Reinforcement overwrites battler0's selected move with153 | Never reinforce the old battler after ownership changes |

These are modeled engine transitions through the actual production client,
memory helper, context reader and connector boundary. They are concrete Lua
regressions, not actual-emulator Explosion execution evidence.

Follow-up review also reproduced unsafe **first** requests: state3 still had its
moves overwritten, states4/5/6 regressed to3, and a low stale state with a
non-selection battle-main pointer still armed. These five cases failed before
the timing guard was added; duplicate-request protection alone was insufficient.

## Current prerequisites and lifetime

Every mutation re-samples RR context, requires a complete uniquely identified
real party, resolves the current key again, and rejects a pending storage,
memorial or trade mutation. Every current player battler must have an initialized
BattlePokemon with a unique matching party record and an agreeing party index.
This is deliberately stricter than the read-only transitional HP projection:
an outgoing HP observation does not authorize writing an incoming battler.

An active target also requires an aligned EWRAM battle-structure pointer whose
written fields fit within EWRAM. The original battler and allocation must still
belong to that request before reinforcement or its600-frame fallback. Initial
arming, reinforcement and the elapsed fallback also require the exact RR action-
selection battle main `0x08014041` and a selection state0/1/2; state2 additionally
requires the selected action to be USE_MOVE. Item/switch selections, turn execution,
standby, confirmed actions and selection scripts retain the request without those
writes. Elapsed time never overrides this operation-specific readiness. A coherent
switch to the bench can settle the same keyed death obligation; the replacement
battler's HP and lock are left alone. An observed battle or borrowed-party boundary
prevents carrying the original coercion into a later battle. Field settlement
waits for the existing active post-battle writer and settled-field prerequisites.
No timeout bypasses those prerequisites.

Borrowed cleanup and battle-end cleanup retain unresolved RR Explosion requests.
A missing mon is not success. A later uniquely matching return can settle the
original obligation. The existing heuristic PID/nature migration cannot retarget
these requests: changing their identity requires explicit reconciliation. Changed
save fingerprints, missing/reappearing patch continuity and observed host-frame
rewinds invalidate the local continuity token; pending requests stay unresolved.

Primary and doubles positive cases verify the exact four153 moves, four5 PP,
chosen action0, chosen move153, STANDBY3, chosen slot0 and target1 writes. Party
records and the foe are canaries while arming. Reinforcement retains the existing
`controller<3` and `PP>=5` conditions and does not reset progressed engine state.
The original600-frame fallback remains a requested linked-death policy; neither
the timer nor a PP drop proves an actual Explosion animation or battle outcome.

`tests/rr/reference/test_explosion_selection.py` requires the exact base-ROM hash
and checks the unredirected `HandleTurnActionSelectionState` entry, comm dispatch
and seven-entry jump table at `0x0801409C`: state0→`0x080140B8`,1→`0x080141DC`,
2→`0x08014764`,3→`0x08014AA0`,4→`0x08014B44`,5→`0x08014B88`,6→`0x08014C20`.
The binary state1 reads the controller action into `gChosenAction`, state2
dispatches that action, and state4 increments the confirmed count. Once all
battlers confirm, the tail writes `0x080150A9` into `gBattleMainFunc`, switching
to turn-order work. The ROM's extended turn-start also contains `0x08014041`.
These match `patch/vendor/pokefirered/src/battle_main.c:3086`'s enum0..6 and
`patch/vendor/cfru/src/battle_start_turn_start.c:656`'s pointer assignment. Older
`patch/src/ADDRESSES.md` narrative claiming a1..4 protocol is inconsistent with
these exact ROM bytes; it is not the readiness oracle used here.

## Validation and limits

Thirty-one focused full-client cases cover the reproduced bugs, valid primary/
doubles coercion, replacement HP/lock canaries, borrowed return, active writer
delays, absent/duplicate/vacant identities, invalid/replaced allocations, duplicate
deadline preservation, first-request/selection timing, turn-execution fallback
deferral, chained battles, changed saves and observed rewinds. One additional
exact-ROM reference case pins the selection-state evidence.
The existing temporal Explosion/counter test now supplies a valid allocated
battle-structure and selection-main fixture instead of null/stale pointers; production source is never
rewritten or replaced to satisfy a case.

```powershell
python -m pytest tests/rr/runtime/test_explosion_guards.py --rr-repo . -q
python -m pytest tests/rr/runtime tests/rr/reference -q -p no:cacheprovider --rr-repo . --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba'
python -m ruff check tests/rr/runtime/test_explosion_guards.py tests/rr/runtime/test_temporal_observations.py tests/rr/reference/test_explosion_selection.py
```

The local table is not a durable semantic-command ledger. Script reloads,
unobserved reset/load transitions, arbitrary external writers, allocation
ownership and atomic rollback remain outside this proof. The independent
controlled-load probes do not activate a production interlock here. Actual
two-player battle execution, switch timing, doubles, Damp and post-battle
settlement still require the reviewed live release gates.
