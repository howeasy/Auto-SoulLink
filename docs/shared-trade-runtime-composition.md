# Atomic trade/runtime composition

This additive shared cut extends the existing coordinator, durable server and
journal. Existing callers that omit the extension retain their previous behavior.
No cartridge, launcher, native-execution or host authority is selected by this cut.

`TradeCoordinator(..., compose_components=callback)` calls the optional callback
with detached `(state, trade, commands, acknowledgements)` after policy validation
and before the one journal commit. The state/trade describe the proposed result;
commands are both proposed outboxes; acknowledgements are policy-validated rows.
The callback returns a JSON component dictionary. It can replace only components,
not the coordinator's rules, identities, trade record, commands or ACK evidence.
The binding must preserve unrelated components and validate its complete result.
It must not perform external writes, send packets, grant frames or repair history.
Read-only journal queries must describe the original snapshot revision; the commit
still uses that revision's compare-and-swap check. Callback failure, invalid output
or SQL failure publishes nothing. Exact journal replay does not call it again.

`DurableRuntime._dispatch_semantic(player, message, owner)` is an overridable
generation seam after private ownership, session replay, expiry and control checks.
Its default calls the existing dispatcher unchanged. An override must persist the
semantic event or validate its existing journal replay before returning. HELLO and
control retain their original separate paths. The outer runtime still constructs
the response and owns connection failure/revocation. This hook is not a public
server-control event and grants no native execution authority.

`ProtocolJournal.pending_ids(player)` returns every pending command ID for one
player in sequence order, bounded to the journal's 4096-command maximum. Read the
checked body using `command(player, id)`. Unlike `pending()`, this index is not
truncated to a delivery count/byte budget. Recovery must not infer completion from
one transport batch. This accessor performs no ACK, repair or state update, and
adds no schema/migration requirement.

The portable shared tests cover detached-input isolation, default compatibility,
replay, callback/output/SQL refusal and obligations beyond both delivery bounds.
RBY additionally composes phase/evidence/outbox obligations into its recovery
history, permits an offered partner to reach a prompt after reconciliation, and
blocks ordinary reconciliation from acceptance through both verified closures.
Those cartridge lifecycle choices are in `gen1_trade_recovery.py`, not shared code.

The configured RBY server can route typed trade events to an explicitly supplied
complete policy. Its tests use full rule/identity/recovery documents and actual TCP;
native receipts and host authority are declared fixtures. The default held-service
launcher supplies no trade policy and remains unable to execute a trade. The actual
native receptionist/partner/execution adapters still require end-to-end binding.
