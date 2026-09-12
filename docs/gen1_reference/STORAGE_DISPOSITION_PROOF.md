# Gen 1 storage disposition: RC implementation boundary

This implementation uses source-derived container transforms and actual protocol
journals. The new tests model physical memory and SaveRAM receipts; they are not
a claim that a new live PC campaign or manual session has passed.

## Mechanisms

- `server/gen1_storage.py` owns RBY geometry: six party slots, twelve boxes,
  twenty members per box, 44/33-byte structures and separate eleven-byte names.
  Party removal and box removal follow pinned `_RemovePokemon`; append and box
  level handling follow `_MoveMon` in `engine/pokemon/add_mon.asm`.
- Withdrawal derives level from XP and stats from canonical species data, DVs
  and stat experience (`home/move_mon.asm`, `CalcStats`/`CalcStat`). Approved UPR
  options cannot alter these base stats, growth curves or types. HP/status,
  moves/PP and names are preserved; malformed data is refused before a write.
- `server/acquisition_disposition_rules.py` separates shared clause/link
  bookkeeping from the usable-party mask. Boxed receipts remain 55-byte box
  witnesses. They do not manufacture an observed 66-byte party record.
- `server/issued_command.py` is a shared exact issuing-event/command lookup.
  Event references, command journals, compact deltas, held write permits and
  saved-file verification reuse existing modules.
- `server/gen1_storage_runtime.py` records synchronized jobs. Both participants
  are read under their exact closed frame authority before paired writes are
  issued. Another pending command cannot be overtaken. Every mutating side
  completes with its exact postimage and qualified SaveRAM file receipt.
- `lua/gen1_held_storage.lua` delegates writes/repair/flush to
  `gen1_held_save_image`. Read-only refusal evidence uses
  `gen1_storage_checkpoint.lua`: actual bounded CPU/ROM/system bytes, without
  pretending an unsafe checkpoint is write-safe. All writes retain the strict
  checkpoint and one-use permit requirements.

## Physical policies

New boxed captures and scripted grants settle normal clauses/exemptions,
pairing and ordinals. Nongift pending party captures are quarantined when
another party member remains. Scripted grants retain their exemption. Linking
retrieves both members only if both parties have room; otherwise both stay boxed.
Usability is published only by the proved physical disposition.

An observed PC move is checked against the canonical complete roster projection.
If the partner cannot deposit or withdraw, the initiator receives the opposite
canonical operation, including appended retrieval and recomputed stats. Last
member, full box, Yellow's verified following-disabled restriction and unsafe
peer context have explicit refusal outcomes. An unsafe peer receives no write.
An invalid box selector is never saved: the initiator is restored and the
corrupt participant retains a specific recovery hold.

Quarantine uses the current legal box first, then deterministic nonreserved
capacity. Existing occupied members are preserved. Uninitialized inactive SRAM
may receive canonical headers/initialized-bit changes only after its complete
box bytes prove empty. If no legal capacity can be proved, the job records
`no-proved-storage-capacity` and keeps its hold without mutating either image.

A source-qualified acquisition born in Box12 is relocated directly as a boxed
record to legal storage, so a full party cannot deadlock its eviction. The exact
capture/grant birth preimage and complete current box must agree. An existing
grave reservation must match the birth's prior bytes; an unowned grave is never
adopted by the relocation.

Manual withdrawal of a dead/memorial member, or a completed nonlinked retirement,
creates an archive-return job tied to that observed movement. The member returns
to its original archive box, remains unusable and retains its existing logical
death/retirement identity. No second death is fabricated.

Reserved Box12 compensation updates the shared grave head only after the exact
saved ACK. Canonical removal of slot19 leaves its unused structure/nickname and
writes `$FF` to its OT prefix. Those bytes are preserved during undo. An exact
previously verified reservation can subsequently overwrite an unused tail;
occupied live members still refuse, and initial/unowned reservation still
requires the entire box to be empty. Box count determines physical membership.

## Interleaving and recovery

A same-pair death observed before both storage reads changes the plan to restore
party disposition before issuing writes. Both read hosts and command queues are
rechecked at issuance. With both frame ledgers closed and storage holding new
frames, a later unaccounted death cannot be admitted as a normal event. Deferred
faint commands retain their original engine evidence and their separate actual
issuing event, and locate the member after compensation/compaction.

Completed writes are attributed by the next inventory transition rather than
reported as another manual PC move. Subsequent disposition jobs can start in the
same saved ACK transaction, using the exact preceding saved postimage; they do
not require an unsafe ordinary-frame gap.

Historical `boxed_deferred` rows are deliberately retained as their original
audited recovery cases. New acquisitions no longer enter that placeholder. No
old acquisition ID, source receipt or successful-purchase ordinal is rewritten.

## Evidence files

Focused test artifacts during this slice include `.cache/storage-kernel.xml`,
`.cache/storage-source-current2.xml`, `.cache/storage-reserved-kernel.xml`,
`.cache/storage-archive-chain.xml`, `.cache/storage-quarantine-capacity2.xml`,
`.cache/storage-reserved-birth.xml`, and the consolidated
`.cache/storage-rc-consolidated.xml`. Consult their actual completed outcomes;
an artifact path alone is not a passed gate. Live storage campaign, reset/reload,
and paired manual acceptance remain release qualification work.
