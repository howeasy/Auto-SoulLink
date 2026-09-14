# N3 — crash during a native trade: pretrade checkpoint + paired rollback (implementation spec)

Status: accepted claim record (coordinator decision 2026-09-14, vetoable). Source: Gen1-CodexPeer
research task cx-fc6b3995 at source cut `29b8542`, read-only. Policy: N3 claim row in
RC_MASTER_GUIDE.md. Depends on R5a (`server/paired_save_checkpoints.py`) and R5b-1
(`server/gen1_checkpoint_runtime.py`, in progress) — N3 reuses the R5b-1 finalizer; it never adds a
second capture path. Forward one-sided recovery is a separate later claim.

## (1) Pretrade capture without a new upload

- Both full images already exist: `NativeTradePolicy.ready` verifies prompt/save/ready and caches
  the complete save receipt (`gen1_native_policy.py:89-105`);
  `components["gen1-native-preparation"][transaction_id][player]["save"]["image_hex"]` retains it in
  the `trade_ready` commit (`gen1_native_preparation.py:26-71,97-114`). The image is exactly
  0x8000 bytes (not a digest): `image()` starts from a 0x8000 CartRAM image and writes
  source-defined copies/checksum; `verify_receipt` compares it with the owned save window and
  ready checkpoint, then verifies the file (`gen1_full_save.py:40-53,107-129`).
- After both ready ACKs commit, the Gen 1 adapter loads the retained entries and calls the SAME
  R5b-1 finalizer with the decoded images, the rules/known-identity export, contract/source
  fingerprints and transaction-scoped evidence. Do not call the upload request path.
- Witness variant (tagged union in the envelope; legacy START witness unchanged):
  `{witness_kind: "native_pretrade", digest: <projection digest>, projection:
  "cartram-0498-8000-v1", transaction_id, command_id, command_sequence, context_generation,
  ready_operation_id, checkpoint_digest, save_receipt_digest}`. `ready_operation_id` resolves from
  the actual acknowledged journal event; a frame, if retained, comes from verified progress/file
  evidence, not the save point (`gen1_full_save.py:108,117-129`). Never invent an engine-signal
  index or write a `gen1-save-witness` record.
- Provenance (flat): `{witness_kind: "native_pretrade", transaction_id, proposal_digest,
  ready_a_command, ready_b_command, ready_a_digest, ready_b_digest, trade_phase:
  "both_prepared", journal_revision}`; refs resolve to retained preparation and committed command
  ACKs (`gen1_native_preparation.py:97-114`).

## (2) COMMIT prerequisite

- In `TradeCoordinator.control("commit")`, immediately after both_prepared validation and BEFORE
  `policy.commit` / `commit_persisted` / command creation, require the policy's journal-confirmed
  pretrade checkpoint reference matching transaction, proposal and both ready digests
  (`trade_coordinator.py:465-475`). The shared coordinator enforces only the policy prerequisite
  (no game_id branch); the native policy resolves/verifies the reference through
  `gen1_checkpoint_runtime`. A directory/CURRENT alone is insufficient; missing/corrupt/unconfirmed
  → `JournalError`, no COMMIT published.
- Capture outside the journal mutation, then confirm via revision/state compare-and-swap; retry
  idempotently for this transaction; pin the checkpoint id (not latest CURRENT); COMMIT reloads the
  confirmed evidence.
- Narrow native-pretrade audit permits exactly THIS active both_prepared transaction: two ACKed
  prepare commands, no COMMIT/applied/verified results, no unrelated pending commands/captures/
  memorials, no run_over, unchanged rules/identities since each saved-ready point, both exclusive
  preparations still owned; preparation-related blockers matched explicitly, not ignored globally.
  Generic resume stays strict (`gen1_run_resume.py:151-175`); native receipt verification is the
  separate save authority (`gen1_full_save.py:107-129`).

## (3) Recover before trade

- Reuse the R5b Manager recovery orchestration, selecting the journal-confirmed checkpoint bound to
  THAT transaction/proposal (never `current()` blindly). Stop/revoke the predecessor, reread durable
  state, validate archive + fingerprints, create one idempotent successor from archived rules/
  identities and BOTH saves.
- Record an immutable disposition `{kind: "abandoned-by-paired-rollback", transaction_id,
  checkpoint_id, successor_run_id, prior_phase}` in a shared recovery component; preserve original
  trade history/ACKs; never fabricate finalization or native ACKs; disable all predecessor delivery.
- Refuse when both verified entries already exist or the phase is both_verified/link_committed —
  finish normal closure first; "then normal resume applies" is conditional because finalize emits
  pending release commands and generic resume rejects pending commands
  (`trade_coordinator.py:438-439,485-499`; `gen1_run_resume.py:170-172`).
- Pre-COMMIT cancellation is `control("interrupt", ..., details={reason})` → `_cancel`, which emits
  `native_trade_abort` (`trade_coordinator.py:286-295,504-514`); cancellation is not proof that a
  crashed client's obligations vanished.
- The successor records predecessor/checkpoint/transaction/discarded interval, imports only archived
  rules/identity state, starts fresh enrollment. Extend `validate_required` with tagged checkpoint
  evidence rather than a forged `witness_index`; keep Continue/projection admission checks
  (`gen1_run_resume.py:211-238`; `gen1_initial_observation.py:181-197`).

## (4) UI

Recover dialog when the selected checkpoint is a pretrade one: "Recover both players to before this
trade. Both players must close the old games and reload the successor launcher. This trade and all
progress after the checkpoint will be discarded." Show transaction, checkpoint time and both-save
availability; disable unrelated/latest-checkpoint substitution.

## (5) Tests (unit, old-code-failing first)

- both_prepared without a confirmed checkpoint cannot queue `native_trade_commit`
  (today only ready checks exist, `trade_coordinator.py:466-475`).
- retained save round-trip supplies both 32768-byte images without upload; native witness union
  preserves kind/refs and never adds engine signals; wrong transaction/proposal/ready-ref or corrupt
  image refuses; capture success + journal-confirmation failure cannot COMMIT; duplicate capture/
  commit/recover idempotent.
- unrelated pending work refuses the narrow audit; paired rollback restores pretrade species/
  identities after one/both physical applications; both_verified refuses rollback; generic
  clean-resume audit stays strict; pre-COMMIT interrupt still emits abort.

## (6) Files

Gen 1: `server/gen1_checkpoint_runtime.py` (finalizer + native evidence adapter),
`server/gen1_native_policy.py`, `server/gen1_run_resume.py` (tagged required evidence).
Shared: `server/paired_save_checkpoints.py` (witness union — folded into R5b-1),
`server/trade_coordinator.py` (prerequisite/disposition contract only), small new
`server/trade_recovery.py` (rollback disposition/lifecycle, delegating image semantics to
`gen1_checkpoint_runtime`), the R5b Manager recovery seam + template, unit tests. No second
storage/capture implementation; `gen1_native_preparation.py` needs no retention change.

## (7) Falsifier

Any COMMIT command persisted before a payload-validated, journal-confirmed matching checkpoint; or a
reload accepting a different transaction's saves. Exercise journal/archive failure boundaries around
the COMMIT seam.

## (8) Risks

The R5b-1 finalizer signature and tagged-evidence ownership must be coordinated before coding
(done: message to the R5b-1 worker 2026-09-14). Retained evidence alone does not prove no
intervening gameplay: pin/recheck rules and identity projections from both preparation points.
Recovery of both_verified-but-unreleased stays outside this slice.

## (9) Decision

READY WAIT(R5b-1 integrated). Implementation order after R5b-1: N3-1 capture + COMMIT prerequisite
(gen1_native_policy / trade_coordinator / gen1_checkpoint_runtime adapter), then N3-2 recover
disposition (trade_recovery.py + Manager seam, together with R5b-3).
