# Gen1 configured durable runtime

Gen1 now has a configured server route and a client binding around the shared
durable pumps. This connects actual transport, admission, journals and committed
rule delivery. Prepared runs now select an owned held-service client through the launcher;
ordinary gameplay/native recovery authority is still unqualified.

## Implementation

- server/durable_runtime.py owns reusable connection/session, journal, dispatcher,
  control, expiry and socket handling. Shared handoff:acc3005046e3c714672da8bf63cc298abe1dbfaf.
- server/gen1_runtime_admission.py validates metadata-only
  slink-gen1-durable-v1 HELLO against each player's verified clean-ROM contract.
  Trainer ID/name and distinct physical instances are checked independently of
  party keys. Legacy party/box/Pokeball fields are rejected at this boundary.
- server/gen1_runtime_state.py composes complete StagedGen1State, IdentityRegistry
  and RecoveryBarrier in the shared coordinated journal schema. HELLO records
  admission only; it neither calls the old rule HELLO nor changes party caches,
  Pokeball state, captures or queued gameplay effects.
- server/gen1_runtime.py supplies that policy/stage to the shared server core.
- SLinkServer(gen1_runtime=runtime) uses the journal route before its legacy
  dispatcher. An unconfigured durable protocol is rejected before legacy slot
  ownership or rule state changes. The configured server's UI reads committed
  facts; unbound launch and mutation routes refuse.
- lua/gen1_runtime.lua supplies fixed RBY protocol/hold identifiers, current
  owned metadata and validated exact-body unwrapping to the frozen shared client
  pump. It does not initialize an unqualified host or silently select itself.

The client stages {cmd, body: exact journal body} beneath the wire envelope.
This preserves body.player, body.seq, body.operation_id and body.protocol when
they are part of a durable command. Generation adapters unwrap once and use the
trusted separate command ID/sequence supplied by the executor.

## Evidence

-39 focused runtime cases passed: all nine cartridge contracts in both HELLO
  orders, unchanged HELLO gameplay state, owner isolation, durable reconnect
  replay, exact body preservation, validated receipt confirmation, typed control
  proof refusal, idle expiry, unexpected callback failure, committed read-only
  facts, HTTP/legacy-route guards and refusal of unpublished legacy bootstrap queues.
- Two actual-host cases passed on Yellow/Yellow and Red/Blue, with separate
  Gambatte processes and SaveRAM directories. Actual LuaSocket/TCP, flushed local
  journals and the configured SLinkServer route delivered a semantic operation
  and its partner command while independent execution holds kept both frame
  counts and all WRAM unchanged.
- The live test's faint event is an explicit transport-test input. It does not
  prove natural faint detection or a physical force-faint. Its cartridge executor
  is intentionally unselected and performs zero writes. The separate unit
  interoperability test checks a complete RBY receipt using modeled after-state.
- The latest broad unit/integration run passed4,092 tests with the same two
  Windows symlink privilege skips; later focused checks include the two additional
  callback/HTTP cases.231 Lua files parse and changed Python files pass lint.

Reproduce with SLINK_LIVE=1:

    python -m pytest tests/live/test_gen1_durable_runtime.py -q

Live evidence is in .cache/runtime-host-final.xml and the per-run
.cache/gen1-runtime-live-*/verified.json documents. Test configuration disables
rewind only in each private test config, matching the qualified hold profile;
the user's emulator configuration and saves are not changed.

## Remaining RC binding work

1. Select this service/client from the real launcher using authoritative bootstrap,
   complete artifact/profile ownership and an opened run journal.
2. Connect existing observation generators to atomic observation/baseline batches,
   and select qualified cartridge executors and receipt policies.
3. Bind actual native receptionist offers and partner decisions to the now-routed
   coordinator. Phase-specific recovery updates are atomic with trade transitions;
   the configured server still requires an explicit qualified native policy.
4. Qualify ordinary execution, disconnect/reset/load/rewind and forward recovery.
   A held-service proof is not permission to release a host for gameplay.
5. Complete final companion/approved-UPR admission, publisher and browser evidence.

Stopped prepared Gen1 runs now use the shared read-only journal reader. No legacy-file fallback or migration is
performed. Native trade/provenance feature gates remain closed in the published
runtime facts until their full bindings qualify.

See LAUNCHER_SELECTION.md for the run-ID HELLO addition, checked launcher/file closure, prepared descriptor, CLI/Manager selection and actual launcher evidence.

## Trade routing and recovery composition

`Gen1Runtime(trade_policy=...)` installs typed offer/cancel/decision/ready/applied/
verified/closure routing after private connection admission. It never dispatches
network `trade_control` or accepts generic `command_ack` for a native trade command.
`trade_control(...)` is a server-only serialized entry with separate authority and
paired liveness checks; persistence uncertainty revokes both sessions.

The `gen1-trade` component pins each unsettled transaction's record digest, phase
and complete pending commands. The coordinator's optional component callback
updates it and RecoveryBarrier in the same SQL transaction as rules, identities,
the trade record, both outboxes and validated ACKs. Restoring a runtime cross-checks
these facts against the journal. Uncoordinated command retirement refuses.

Offers invalidate old reconciliation but add no party-ownership blocker. This
allows the partner to reach a safe native prompt after fresh ordinary evidence.
Acceptance blocks ordinary reconciliation. Cancel/decline/finalization retain that
blocker until every old prompt/prepare and abort/release command has a validated
closure receipt. Both closures still require fresh paired reconciliation before
ordinary play. No transition itself grants native recovery or gameplay frames.

Tests cover all ordered RBY pairs and both initiators on full rule documents,
including matching Yellow keys/bytes, one-sided completion/reopen, rollback and
two actual TCP offer/decision routes. Native and host evidence in these routing
tests is explicitly modeled. The existing nine paired emulator tests qualify
the separate native COMMIT-to-file-to-migration slice. Their combination is not
yet a complete receptionist-to-trade production proof.
