# Ordinary evolution source and identity migration

The ordinary source lane observes the cartridge; it writes neither ROM nor RAM
and creates no acquisition. It is separate from the existing native Soul Link
trade executor and the NPC in-game exchange receipt.

## Reused mechanisms

`TradeResultRules.from_rom` reads the admitted cartridge's complete evolution,
learnset, HM and species-name tables. Its new `evolution_outcomes` helper exposes
one existing stat/HP/default-name/move-learning transformation; native trade
outcomes use that same helper and retain their existing behavior. `PartyCodec`
checks complete 66-byte records, party species lists and typed fields.

`IdentityRegistry.migrate_many` and its existing witnesses retain one logical
member while changing its physical species key. Shared
`member_identity_rules.rekey` preserves the rule's original link or pending area
and copies every `MonInfo` field. NPC migration retains its compatibility alias
to this helper. The generation caller controls usability; the shared helper
does not make a pending or quarantined member usable.

## Original source witnesses

`tools/gen_gen1_evolution_sites.py` verifies the pinned source trees, symbols and
original ROMs before producing the server rule data and lightweight Lua site
projection. The only evolving containers in `Evolution_PartyMonLoop` are party
slots: it loops `wPartyCount`/`wPartySpecies` and forces `wMonDataLocation=0`.
Current-box data is captured as an unchanged/collision witness. There is no
invented direct boxed-evolution path.

The before hook is `Evolution_PartyMonLoop.doEvolution`, after the cartridge has
selected an eligible table entry and before animation. It retains the actual HL
target-entry pointer and A level register. The successful after hook follows
the final species-list write and balanced `push hl`; stat, HP, nickname, move,
type and Pokédex writes are complete. The cancellation hook follows the `pop hl`
inside `CancelledEvolution`, giving the same stack depth as the before hook.

Receipts retain every party byte, every current-box byte, both Pokédex bitfields,
save identity and the slot/map/battle context. Successful results must match an
exact allowed outcome; other members and unused party/box bytes cannot change.
Cancellation requires unchanged party/dex and a clear force-evolution flag.
The observer skips link state `$32` before reading the ordinary owner identity:
native Soul Link and NPC trade evolution stay owned by their existing receipts.

The server checks actual admitted ROM table bytes for UPR cartridges; it cannot
substitute clean requirements for a changed level/item/method. Canonical clean
and canonical companion identities can use the generated original table facts.
Red/Blue's verified in-battle item-evolution bug remains allowed where its source
condition is met; Yellow's fix and following-starter stone refusal are retained.

## Runtime integration

Wire kind: `evolution`. Receipt schema: `rby-evolution-receipt-v1`, with
`outcome=evolved|cancelled`, `before`, and `after`. Completed facts use
`call_frame`/`return_frame`. The generic source decoder keeps original mixed-list
indices, and the standard frame verifier checks every witness against consumed
authority, including retained earlier windows.

`stage_evolutions(runtime, stage, document, player, operation, facts,
frame_origin=..., frame_request=..., rom=...)` stages only nonempty evolution
facts. It returns `entry/result/commands/records`; `evolution_digest` binds the
containing frame result. `verify_state` and `verify_journal` check identity and
source provenance on ordinary state reads and reopen. An unchanged later frame
does not create another evolution record.

Migration occurs at the complete source publication, even if the emulator has
not yet returned to a safe overworld inventory checkpoint. This avoids treating
a transient species-list write as a capture or requiring a grace timer. Full
inactive storage remains covered by normal inventory validation and the logical
registry's collision checks. Original acquisition records, member/link IDs and
ordinals remain unchanged. Pending captures retain their original area and their
unusable mask. Cancelled attempts produce no identity migration.

## RC limits and evidence boundary

Direct box evolution does not exist in the supported source. A patched table
that repeatedly evolves the same party slot through several targets in one
original-table pass is explicitly refused; ordinary source validation requires
the table species to match that attempt's complete before record. Invalid or
ambiguous keys and evolution of a member already awaiting memorial require
reconciliation. No new acquisition is invented to repair an unknown identity.

Tests cover all R/B/Y result kernels and the actual frame, journal, identity,
quarantine/release and subsequent inventory handlers for Yellow/Yellow and
Red/Blue. Modelled source and file receipts are not an emulator campaign. Live
ordinary evolution qualification remains separate; the existing old evolution
gate is supporting engine research, not evidence that this newly wired lane ran.
