# T3-BIND-FR: FireRed ABI2 consumer

This card binds the existing client trade journal/protocol to native FireRed
trade evidence. It is **MODEL evidence only**. It does not qualify the heap
clamp, native UI, save persistence, reload, or a live duo. READY remains zero;
no cartridge manifest, profile, producer source, or UPS changes here.

Base: `4af7feaf9ced253567ef387ab726ea20e3a41441`, branch
`codex/gen3-t3-bind-fr`. Producer contract:
`f4b740f60b4a017ad37c2784293389426d9d95c0:docs/gen3/research/fr_native_trade_abi.md`.
Immutable producer: `2133349d2ef359dad4a002441994267d3c762651`.
The producer/contract objects are on `claude/gen3-emerald-t2`; their files are
not copied into this consumer branch.

## Production boundary

`entry.lua` rejects an artifact explicitly marked `production: false` on the
hash, anchor, and production-construction paths. A FireRed companion additionally
requires **explicit** `production: true`. Its full profile must carry ABI2.
LeafGreen, Emerald, clean FireRed, and RR v1 cannot acquire this trade capability.
There is no new admitted artifact and no runtime READY word.

`native.lua` requires the cartridge's durable-trade bit, the admitted production
identity, the T2-R1 producer-phase schema, and a bound nonzero epoch. An older
ABI2 profile without producer_phase keeps its other behavior but cannot trade.
The private candidate's `production: false` receipt is not production admission,
even though the candidate advertises bit 1. The model explicitly supplies a
production identity and a capability-advertising cartridge double.

Entry derives the native epoch from the persisted boot nonce (first word of a
16-hex-digit nonce, or the entire nonce when at most 8 digits). Binding waits
for a ready, unhidden journal, an idle producer, and the normal serialized
native write policy. Epoch writes are rechecked at dispatch. They are field
writes, not native acceptance or reconciliation. Capability changes request a
new hello so a late epoch bind is visible to the server. `client.lua` is untouched.

## Consumed ABI

The profile remains the source of addresses and opcode values. The consumer
validates the generated field widths/offsets and relevant constants before use.

| Field / operation | Consumption |
| --- | --- |
| Signature / ABI at mailbox +0/+4 | SLNK + ABI2 beacon, never consent |
| Opcode, seq, status, ack_seq, reason | Single queue; opcode published last; ACK alone cannot complete trade |
| args[32] | Slot, role, zero reserved bytes, outgoing PID/OT, visit, opaque token |
| capabilities +0x40 | Requires durable-trade bit; rejects unknown advertised bits |
| session_epoch +0x44 | Serialized nonzero write, readback and witness binding |
| producer_phase +0x48 | Native-only IDLE/PRE_SAVE/READY/SCENE/DONE/UNCERTAIN; never written by Lua |
| witness +0x50, 80 bytes | Equal nonzero even revision before/copy/after; copied revision must agree |
| witness identity | Epoch, visit, all 16 token bytes, outgoing PID and OTID |
| flags, milestone bits and five sequences | Acceptance+consent+pre-save before apply; PREPARE sequence for bit 0, SCENE sequence for bits 1–4 |
| final_result, save_status, received PID/OTID | Committed success mirrors the C durable predicate, including both incoming identity words |
| milestone frames | No ordering/clock inference; equal native frames are valid |
| blob staging | Exactly one 100-byte record; copied again by the owned SCENE job |
| PREPARE 29 / SCENE 21 / WITHDRAW 30 | PREPARE drives UI/pre-save; SCENE owns mutation; WITHDRAW needs its own bound UNCHANGED witness |
| reason 14 | Named withdraw_too_late; never treated as unchanged or as the original transaction's outcome |

The opaque token is a consumer-owned mapping: a domain marker, native epoch,
monotonic visit serial and complement. The complete server token stays in the
owned context; it is neither truncated nor derived from Pokémon identity.
Counter exhaustion refuses preparation. Local outgoing eligibility checks
unique identity, slot, checksum, species, egg/bad-egg, mail, and safe field state.
FR mail items 121–132 and MAIL_NONE=255 come from pinned pret
`c75f352304d529f6ba92d4f74b9cf8b5c3810788`, `include/constants/items.h:125–136,451`.
The server command path remains responsible for server authorization.

## Completion and recovery

`transfer("enemy")` is staging-only for FireRed ABI2. No legacy opcode 16 or 18
is used. SCENE revalidates the local identity/field state and the caller's
authorization/deadline/journal guard. It owns its own immutable staging copy.

The same coherent snapshot supplies progress and completion. Cumulative flags
reach `trade.lua` in commit → scene → save → final order, including a single
native frame containing all milestones. Host SaveRAM flush precedes journal
`native_saved` and `trade_done`; a failed flush keeps the journal hidden.

A stable, correctly bound terminal UNCHANGED is positive pre-mutation proof.
Failure reason zero, missing COMMIT, or an ACK alone is not. The consumer has
no new reason-only allowlist. Regressing milestone bits and wrong received
identity refuse completion. Native DONE is reusable only after consuming and
reconciling its terminal result; this is distinct from mailbox-idle.

Epoch/capability/beacon loss or frame rollback during an owned transaction
blocks further trade work. Restoring RAM fields cannot rearm it. A fresh binding
after real game reset and independent journal/save reconciliation is required;
this card does not implement a reconciliation opcode or qualify reload proof.
Native READY lease expiry, outgoing eligibility in the producer, chooser
lifecycle, heap ownership, and physical persistence remain the producer's open
qualification gates.

## Verification

Red controls first reproduced the unavailable capability, non-production
admission, missing FireRed construction, and missing capability re-advertisement.
The final focused run covers real `reads.lua`, `writes.lua`, `native.lua`,
`trade.lua`, and `trade_journal.lua` under Lua 5.4 with a deterministic native
cartridge double. The new controls include corrupt identity/seq/flags/phase,
odd/zero/torn revisions, stage overwrite, epoch races, reset/capability loss,
declared production status, mail/egg/checksum/duplicate eligibility, bound
withdrawal, full completion, UNCHANGED, and host-flush failure.

```text
python -m pytest tests/unit/test_gen3_entry_trade.py tests/unit/test_gen3_native_trade.py tests/unit/test_gen3_native.py tests/unit/test_gen3_trade.py tests/unit/test_gen3_entry.py -q -p no:randomly --tb=short
318 passed in 6.95s
python -m ruff check tests/unit/test_gen3_native_trade.py tests/unit/test_gen3_entry_trade.py
All checks passed!
python tools/lua_syntax_check.py
OK: 303 Lua files parsed cleanly
```

Full-suite receipt will be appended after the committed implementation is run
with `C:/slink-wt/g3-env.sh`.

Follow-up control: a torn/unreadable journal after a proved UNCHANGED result
already kept the protocol closed, but initially released native DONE ownership.
The red control reproduced that gap. Native reconciliation now also requires
`journal:precommit_unchanged(...) == true`. The final focused suite is **319
passed in 7.00s**. The first full-suite attempt was interrupted at 10% to add
this guard; it is not counted as a completed verification run.


## Completion receipt — 2026-09-27

Implementation: `69c811d7141b9bf8ba0eb4bbdf94df7ba471577e`; journal ownership
follow-up: `d1dd6c51c55d69f4347b0918856de8700041226c`.
Source stayed at the latter commit throughout the completed full run.

```text
source /c/slink-wt/g3-env.sh
python -m pytest tests/unit -q -p no:randomly -n 2 --dist=loadfile --maxfail=1
14889 passed, 1521 skipped in 1193.78s (0:19:53)
Exit code: 0
```

The run used process-local `TEMP`, `TMP`, and `TMPDIR` set to
`D:/slink-wt/g3-t3-bind-fr-test-temp`, with pytest's default temporary-directory
management (no `--basetemp`). Two earlier attempts on C: were invalidated by
ENOSPC and are not counted as verification. The source worktree stayed at
`C:/slink-wt/g3-t3-bind-fr`; no branch/worktree move occurred. The independent
client regression also passed **204 tests in 8.43s** after disk recovery.

The parallel runner loaded pytest-xdist from the then-existing per-lane cache
`C:/slink-wt/g3-rfix/.cache/rf1-test-deps` via `PYTHONPATH`. Owner cleanup removed
that old worktree after the workers started; reproduction requires pytest-xdist
in the test environment. The coordinator subsequently directed
`-o tmp_path_retention_policy=failed` for future invocations; it arrived during
this already-running gate and was not retroactively applied.

Full output: `.cache/t3-bind-fr-full-unit.txt`; SHA-256
`1503b5d1620572987a545c9b38760b17ff96fd00cd466e5f347ccc514fb8f043`.
The two new test files contain **94 controls**. The final focused run passed
**319 tests**. Skips remain skips; none of these results qualifies a live trade,
a physical save/reload, arena safety, or production READY. No producer,
`client.lua`, profile, manifest, or master changes were made.
