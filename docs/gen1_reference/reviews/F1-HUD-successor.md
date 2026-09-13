# F1-HUD-fixtures: authorized-inventory and memorial-policy fixture repair

Card `F1-HUD-fixtures`, claudex task `cx-89a2da38`. Implementer: Claude Gen1-Collab2 (transport `4ec907e2-58e4-4495-8aba-87fc96ff233c`), host HOUNDOOM. **2026-09-13 14:41–14:54 UTC**, canonical `gen1/rc`, HEAD `607d342` at freeze (production source `15727ec`; later commits docs-only). Exclusive files: `tests/unit/test_gen1_authorized_inventory.py`, `tests/unit/test_gen1_memorial_policy.py`. No production, shared-helper, Lua, data or manifest edit; no commit. Obligations: `protocol.unit`; `memory.{red,blue,yellow}.storage` registrations on memorial-policy assertions preserved. Evidence level: **MODEL ONLY** (unit fixtures on the real `Gen1Runtime`), released for independent Standards/Spec review.

## Red (before any edit)

`python -m pytest tests/unit/test_gen1_authorized_inventory.py tests/unit/test_gen1_memorial_policy.py -q -p no:cacheprovider --junitxml=.cache/f1-hud-red.xml` → **10 failed, 102 passed** (`.cache/f1-hud-red.txt` SHA256 `89c23aab…6d4e41`, `.xml` `d1419fcf…ef9e8a`), the same ten ids as `.cache/f1-unit-successor.txt:1270-1280`.

Two failure shapes (FACT, from the tracebacks and a read-only queue probe on a scratch runtime):

1. Nine cases raise `complete matching Gen 1 HUD receipt required` from `server/gen1_hud_feedback.py:396` via `gen1_command_receipts.py:128`. The fixture selects `runtime.journal.pending_ids(player)[0]` expecting the next typed physical command (`memorial_observe`), but the head of the queue is a `hud_notice`/`hud_state` command appended by the death/whiteout feedback (`append_after_physical`, physical-before-HUD ordering, `gen1_hud_feedback.py:337`). Actual queues: after the peer faint `b = [force_faint, hud_notice]`; after B's force-faint ACK `b = [hud_notice, memorial_observe]`; in the terminal (whiteout) start `a = b = [hud_notice, hud_state, hud_notice, memorial_observe]`. Memorial/faint ACKs require the oldest pending id (`gen1_memorial_runtime.py:202-204`, `gen1_faint_runtime.py:267-269`), so the HUD entries must be settled on their own lane first.
2. `test_unapplied_command_arriving_mid_batch_defers_only_the_heartbeat_checkpoint` asserts `len(pending) == 1`; the queue is `[force_faint, hud_notice, hud_notice]` (one physical command plus two no-write notices).

The shared helpers already model this: `tests/unit/test_gen1_memorial_runtime.py::start:34` calls `acknowledge_hud(runtime)` after the physical ACK ("the transient death/whiteout HUD precedes the memorial reads"), and `tests/unit/test_gen1_faint_runtime.py::paired:36` does the same. The two failing files predate that lane.

## Change (fixture only)

- `test_gen1_authorized_inventory.py`: import `acknowledge_hud`; add `queue()` and `physical_head(runtime, player, expected)`, which asserts the **exact** FIFO command list, settles only HUD entries through the existing `acknowledge_hud` helper, asserts the exact remaining physical list, and returns the head command. `receiver_memorial` asserts `["force_faint", "hud_notice"]` before the faint ACK and uses `physical_head(..., ["hud_notice", "memorial_observe"])` before the memorial read; `complete_memorial` does the same for the peer. The mid-batch test asserts `["force_faint", "hud_notice", "hud_notice"]` instead of a count of one; its later `pending_ids("b") == pending` equality and the frame-115/114 deferral oracles are unchanged.
- `test_gen1_memorial_policy.py`: import `acknowledge_hud`; `terminal_start` asserts the ACKed command is `force_faint`, asserts both players' queues are exactly `["hud_notice", "hud_state", "hud_notice", "memorial_observe"]`, calls `acknowledge_hud(runtime)`, and asserts both queues are exactly `["memorial_observe"]`, mirroring the shared `start()` helper.

Unchanged oracles: same-frame ordered attribution (`["force_faint", "memorialize"]`, revision order, no movements/HP-zero), heartbeat deferral (`inventory_deferred`, frame 110 retained, evidence frame 115 accepted / 114 refused), terminal last-party retention (`retained-dead-party`, `saved False`, `memorial_complete False`, rules/blockers unchanged, no ticket, link DEAD, reopen), tamper/refusal (`physically fainted`, point-digest restore refusal, deleted read event refusal). No `acknowledge_hud` call skips a non-HUD command silently: every call site asserts the full queue before and after.

## Green and checks

- Two files: `python -m pytest tests/unit/test_gen1_authorized_inventory.py tests/unit/test_gen1_memorial_policy.py -q -p no:cacheprovider -rA --junitxml=.cache/f1-hud-successor.xml` → **112 passed, 0 failed, 0 errors, 0 skipped**, 50.71 s; `.cache/f1-hud-successor.txt` SHA256 `29a09e382bcaa9e295e806eefa34993fb4e302eb3212f4f946dbc829a3572d51`, `.xml` `5a6e0627feb8772ccc0617eb3cd7fb0044f54e2387a6dacec288ad28335aefae`; junit counts `tests=112 failures=0 errors=0 skipped=0`.
- Helper suites the two files import from, unchanged by this card: `test_gen1_hud_feedback.py test_gen1_faint_runtime.py test_gen1_memorial_runtime.py test_gen1_memorial.py test_gen1_held_faint.py test_gen1_inventory_observation.py test_gen1_observation_runtime.py` → **332 passed, 0 skipped**, 208.5 s (`.cache/f1-hud-helpers.txt` `92202de1…acc96c`).
- Revert-test: with `acknowledge_hud(runtime)` in `terminal_start` replaced by `pass`, the six memorial-policy cases fail again (`6 failed, 92 deselected` under `-k`), so the new assertions cannot pass without the settlement.
- `ruff check` on both files: `test_gen1_memorial_policy.py` clean; `test_gen1_authorized_inventory.py` carries one pre-existing `I001` import-order finding also present at HEAD (`git show HEAD:… | ruff --stdin-filename`), left untouched to avoid unrelated churn.
- Frozen file hashes: `tests/unit/test_gen1_authorized_inventory.py` `4b301f9c502b008272408dcef34b63fafc01a273bcdd3a5aa3fcb77426ebb144`; `tests/unit/test_gen1_memorial_policy.py` `cc37e5eb41917b11d7fb4f159a0e4bdabca9a0728d24cbeeb8b9811c7726465c`.

## Boundaries

- No product defect found; the HUD verifier, FIFO guards and memorial/faint ACK ownership behaved as documented. No shared helper needed a change.
- The working tree also carries other owners' uncommitted files (Sol: `test_gen1_control_view.py`, `test_gen1_no_catch_retirement_flow.py`, `test_runtime_fairness.py`, their review files; N0: `N0-CLI-successor.md`). Not touched, not part of these receipts; the two-file runs above import none of them.
- MODEL ONLY: nothing here is a physical HUD or memorial receipt.

## Next owner / action

Coordinator: independent Standards/Spec review of the frozen diff (`git diff -- tests/unit/test_gen1_authorized_inventory.py tests/unit/test_gen1_memorial_policy.py`), then integrate. Writer released.
