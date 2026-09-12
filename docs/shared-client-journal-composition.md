# Atomic typed client receipts

`Journal.open(store, new_id, options)` accepts two optional, pure callbacks.
Existing two-argument callers retain their v1 document and generic command ACK
behavior. The shared executor and durable pump APIs are unchanged.

`completion_event(entry, outcome, receipt)` returns a typed semantic payload or
nil for the existing `command_ack` payload. Inputs are detached. A custom payload
must retain the exact command ID, sequence and receipt; any outcome field must
match. HELLO, control, sync and transport envelope fields are refused. The mapper
cannot replace the command body, intent, outcome or physical receipt.

The inbox outcome, receipt, exact completion payload, completion operation ID and
outbox event publish together. Repeated completion uses those persisted facts;
it does not call the mapper again. The exact operation ID identifies the terminal
event. Earlier evidence for the same command (for example native application
before save-file verification) may be acknowledged without retiring that command.
Only the terminal event's exact persisted payload can confirm it and advance the
contiguous inbox floor.

`acknowledge_event(payload, operation_id, observation)` receives the exact oldest
event being acknowledged and a detached detector baseline. It may return a new
baseline object or nil for no change. The returned baseline publishes atomically
with event removal, command delivery and any receipt confirmation. Failure leaves
all of those pending. The generation must preserve unrelated detector fields and
keep the baseline bounded. Neither callback may perform external effects.

Typed completion or an acknowledged-baseline change promotes that document to
`slink-client-journal-v2`. The new reader accepts v1 and v2. The frozen v1 reader
refuses v2, preventing an older client from silently treating typed completion as
an ordinary observation. Opening a journal does not upgrade it. A v2 document
does not require the original mapper to replay/confirm an already stored terminal
payload. Newly produced events still require the correct generation callbacks.
Mixed already-open old/new writers remain unsupported under the existing store
ownership contract.

The shared test closure uses the frozen v1 reader in
`tests/fixtures/client_journal_v1.lua`, copied exactly from72b91ac. It contains no
ROM, local installation lookup or required Git history. Existing shared fixture
helpers are `test_client_journal.py` and `test_client_state_store.py`.

RBY owns `gen1_trade_events.lua`, `gen1_receptionist_client.lua`,
`gen1_partner_prompt_executor.lua` and `gen1_saved_trade_executor.lua`. They bind
native UI, phase events and the existing SaveRAM provider. They do not change
this shared journal into a physical authority or automatically enable gameplay.
