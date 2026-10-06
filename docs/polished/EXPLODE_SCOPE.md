# Polished Explode Mode: what the five-byte replacement does and does not guarantee (DESIGN OF RECORD, NOT IMPLEMENTED)

Source: headless Codex review cx-cb6edf42 (2026-10-06); the client behaviour re-read by the coordinator at `lua/gen2/client.lua:1585-1640` and
`server/state.py:4303-4308`. Engine rows are SOURCE analysis (Polished pin 3fa43192), not live proof. `supports_explode_mode()` stays **False**.

## Three different claims
1. *Explosion attempted* (the five bytes: selected battle move, its PP = 1, the party move and PP, then `wCurPlayerMove` last; `polished_writes.lua:166-185`).
2. *Death enforced* (the mon is actually at HP 0).
3. *Every death visibly explodes* (bench and committed actions too).
The existing server contract is (1) with a plain faint for the rest: `state.py:4303-4308` allows an immediate faint for bench mons, vanilla Gen 2 faints
plainly after an item/switch, Gen 3 holds Damp/move-locked cases. Polished satisfies neither (2) nor (3) completely.

## The defect in the current path
A landed writer call is treated as a finished KO: the client sets `commanded`, `mark_dead`, shows "KO'd" and queues a deferred plain `force_faint`
(`client.lua:1618-1629`). Nothing observes that Explosion executed. On Polished the deferred faint is the ACTIVE faint, which refuses in battle
(`polished_explode.lua:183-186`), so a blocked Explosion leaves a usable mon until the overworld checkpoint, and the server already counts it dead.

## Situations (engine behaviour for the injected move; not guaranteed death unless stated)
Active free action: Explosion reached unless blocked; the opponent may act first. Item committed / switch committed: the five bytes do not cancel the item
or the deferred switch (`core.asm:4389-4400`, `4645-4653`; `effect_commands.asm:107-116`): refuses, retried only on a later USEMOVE hold. Bench: the
writer rejects non-active targets (`polished_writes.lua:171`); no immediate bench faint exists. Choice lock/Encore: slot-based, the selected slot keeps
the lock (inference). Disable can stop execution. Taunt: unimplemented in this pin. Struggle: needs a valid retained index 0-3. **Opponent Damp:** `selfdestruct`
returns before zeroing HP (`explosion.asm:1-4`): NOT a death. User Damp alone does not block. Transform: the vanilla exception is omitted, a different-species
transform stays queued, same-species passes the species check. Last mon: no exclusion, native whiteout path. Sleep/freeze/paralysis/recharge/flinch/confusion/
attraction, **disobedience** (the move script begins with an obedience check) and **opponent already fainted** (`hastarget` precedes `selfdestruct`) can all
end the turn before the self-KO. Stale cache: `ParsePlayerAction` refreshes move data BEFORE the hold, `CheckTurn`/`VerifyChosenMove` read the cached
original move (Sleep Talk and thaw exceptions, Disable) before `DoTurn` refreshes it, so "sleep always blocks" and "Disable always blocks" are both too simple.

## Recommended bounded contract (needs your ruling)
**Explosion for an eligible active selected-move action; a guaranteed plain faint for every other case and for a failed attempt.** That matches the existing
server semantics and is far smaller than forcing every bench or committed death to animate. It needs, in order: (a) execution settlement (observe the actual
move or the HP 0 and clear the KO claim when the mon survives); (b) a Polished active-faint transaction (suppress the action, settle a pending switch, keep the
party identity, reach native faint/whiteout) and (c) a bench faint with a frame/PC gate and selection-race check; (d) a switch-in fallback at a post-copy,
pre-action boundary if bench targets must die before they can act. All need live proof (ordinary success, blocked execution, committed item/switch, bench
race, transformed identity, last mon). If universal visible Explosion is required it is a separate feature (bench presentation and committed-action
cancellation first). A boolean capability cannot express per-action eligibility: the client enforces it.
Do not use `EXPLODE_RIVAL.md` sections 1-2 as authority (section 6 retracts the dispatch claim); `UpdateBattleMonInParty` copies level/status/HP, not moves/PP
(`home/battle.asm:230-239`), so the party move write only affects a later party-to-battle load.

## Plain-faint design review (2026-10-06, Polished peer cx-aa6e438b; coordinator-checked in part)
STATUS: design-of-record. Nothing here is built; capability `supports_explode_mode` stays off until the matrix closes. Source-checked by the coordinator so
far: `HasPlayerFainted` is a bare two-byte HP OR (`home/battle.asm:613-618`) and `wWhichMonFaintedFirst` is consumed by ResolveFaints (`engine/battle/core.asm:715,753,815`).
Everything else below is the peer's reading and is OPEN until its own oracle card (F0) runs on the SM83 machine.
* A zero HP alone is not a full faint contract. PerformMove tests HasUserFainted before DoTurn, so a zero-HP player skips its own turn; ResolveFaints runs the
  native faint presentation only when `wWhichMonFaintedFirst` is non-zero, then copies battle to party. Never pre-set the FAINTED substatus (FaintUserPokemon
  returns early and skips presentation). The existing copyback observation at 0F:44CA is after that dispatch, so it cannot trigger a missed presentation.
* Do NOT port the vanilla USEITEM-last recipe: an item already spent in BattlePack stays spent, ParsePlayerAction has already consumed the selection, and a
  committed switch target persists (`wPlayerSwitchTarget`, shared `wDeferredSwitch` flags: never clear them wholesale, that can cancel an enemy switch).
* Bounded first candidate (active target, USEMOVE action, no pending switch, no Transform): at the qualified 0F:416A hold write battle status 0, party status 0,
  party HP 0/0, battle HP 0/0, then `wWhichMonFaintedFirst`=1 LAST only when it was 0 (preserve 1/2); read back all six bytes plus the order byte; keep the command
  pending until native faint/copyback is observed. Refuse (stay pending, no false "not changed") on switch target, deferred switch, Transform bit (SUBSTATUS2 bit 4,
  also same-species Transform), link mode, wrong PC/bank, or a changed target key. Last mon uses the native loss/draw logic (link must be refused; draws count as losses
  only outside link/Battle Tower): do not hardcode loss.
* Bench target: party Status 0 and HP 0/0 only, never the active battle mirror; reject the slot named by `wPlayerSwitchTarget-1` (selection race: HP is validated
  at selection, materialised later). A post-copy pre-action hook is a separate qualification.
* Cards (each <= 3 files, one writer per Polished facade): F0 engine-consumption oracle on the SM83 machine (`tests/unit/test_polished_plain_faint_engine.py`);
  F1 bounded active writer (`polished_explode.lua`, `polished_writes.lua`); F2 client settlement (`client.lua`, `entry.lua`); F3 live probe; F4 committed-switch / bench race
  (source pin first). Live matrix: free action, opponent first, Damp / locked / status-blocked then fallback, item already used, queued switch, bench before/after selection,
  Transform incl. same species, last mon wild/trainer, simultaneous enemy faint, readback failure. Needs a granted played fixture (Route 29 save); no SYNTH trainer/story staging implied.
* Ordering limit: this does not guarantee death before an enemy priority move; that needs a separate pre-action native faint-resolution seam.
Owner decision still open: explode scope (this bounded contract vs universal visible Explosion).
