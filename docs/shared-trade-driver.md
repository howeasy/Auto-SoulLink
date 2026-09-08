# Coordinator transition driver

`TradeDriver(read_transaction, advance, new_id=...)` selects ready transitions
from current committed coordinator facts. Call it within the owner's serialized
runtime lifecycle. The read callback returns `TradeCoordinator.status()` or None.

| Current phase | Selected action |
| --- | --- |
| accepted | prepare |
| both_prepared | commit |
| both_verified | finalize |
| Other valid phase or recovery_required | No action |

The advance callback receives action, transaction ID and a fresh operation ID.
It retains all private authority, current-connection, physical-proof and atomic
journal checks. It may return None to defer. Errors propagate; the driver does
not retry an uncertain effect, manufacture consent, grant frames, or resume an
interrupted native transaction. Every step rereads committed facts.

An explicitly supplied `new_id` must be callable, including when its truth value
is false. Invalid factories fail at construction before either callback runs.
Omitting it or passing None selects the secure default identifier factory.

The first caller is RBY's native runtime binding. Its driver runs after typed
trade events and verified control requests, using the existing private coordinator
entry. Other generations can supply the same two callbacks without copying that
phase selection. Tests exercise the actual SQLite coordinator through both ready
receipts, both verified results, interruption, finalization failure and retry.
