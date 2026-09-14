# R5b — paired checkpoint joint protocol (authoritative contract)

Status: accepted contract (coordinator, 2026-09-14). Source: Gen1-CodexPeer audit cx-f42accec at
`b773cfe` (server 551e7b4, client 2829675). Binding on R5b-1 (server), R5b-2 (client) and R5b-3b
(Manager) round 3. "ACK" = SERVER-confirmed retirement, distinct from local completion.

## State pairs (server × one player's client) → required actions

| Pair / trigger | Server | Client |
| --- | --- | --- |
| collecting × discovered-unsafe | one owned upload command; timer/pins retained | start the 90 s deadline at DISCOVERY; movement toward a safe point allowed; zero sample reads |
| collecting × held-sampling | accept only the owned pinned completion | continuous physical hold; at most 3 samples; mismatch attempts are non-fatal durable PENDING, then a typed refusal (never a raise into the runtime's fatal path) |
| collecting × uploaded-awaiting-ack | validate image/pins, ACK the exact upload; first upload leaves the request collecting | persist the SAME image/event; keep the hold; retransmit the same operation; never resample after intent |
| collecting × refused-awaiting-ack | ACK the valid refusal and atomically become abandoned | persist the refusal as a successful typed completion; keep the hold awaiting the matching release |
| preparing × uploaded-awaiting-ack / awaiting-release | second upload ACK + complete intent in ONE commit; publish, then confirm/abandon | hold through ACK and publishing; no frames |
| confirmed × awaiting-release | emit exactly one confirmed release per player | process only own request; ACK the release durably; stay held until its completion retires |
| abandoned × any pre-release client state | accept the exact outstanding upload/refusal completion AS ABANDONED (ACK of receipt, never capture); queue the release behind it | finish the bounded upload/refusal protocol, then consume the release; hold once sampling/refusal began |
| confirmed/abandoned × released | release ACK recorded; terminal result immutable | clear hold/status only when the matching release sequence is confirmed retired; no resampling |
| any other pair | refuse/hold as protocol inconsistency | no inferred success, no frame release |

Triggers: upload OK A/B (first ACK → collecting; second ACK + intent → preparing → terminal);
refusal A before B's upload (abandoned; ACK A; still accept/retire B's exact upload/refusal as
discarded; both releases reachable; no forged receipt); collect timeout (serialized timer → abandoned
at 120 s even without semantic traffic; same drain rule; client 90 s unsafe deadline → zero-read
refusal; a disconnected client stays recoverably held); finalize failure / source drift (terminal
abandoned + bounded reason; prior confirmed checkpoint preserved); server restart/reconcile
(preparing: FULL durable intent matches the archive → confirmed, else abandoned; collecting resumes
the original deadline or abandons; client replays the pending event, never a new request/image; no
duplicate releases); client reopen, same owner (server keeps the request; client reconstructs
lifecycle, upload/release sequences, intent and deadline from the journal BEFORE frames); client
replacement (normal session gate refuses old physical authority; request abandoned through the server
lifecycle; never borrow the old intent; paired recovery); duplicate delivery/ACK (original operation
returns the original result; changed body under the same id refuses; exact floor/sequence retirement
only); stale/wrong-request release (no mutation, never clears the current hold; report recovery-needed
on queue inconsistency); second request (refused until the previous request is terminal AND both
releases retired; lifetime id uniqueness); Manager Recover while open (see §3).

## (1) Ordering invariant (makes the queue-block impossible)

For each player U(request) precedes R(request). The server permits the exact U completion in
`collecting` OR `abandoned` — abandoned means ACK-of-receipt/discarded, NOT capture. R may be enqueued
behind U, but U must remain completable after abandonment; R is deliverable/ACKable only once U
retired. Never require R to bypass the oldest command; never invent a U ACK. The client records
request_id + U.sequence + R.sequence durably and clears the hold only when `command_floor >= R.sequence`
with the exact R binding previously validated; unrelated floor movement never counts
(`lua/client_journal.lua:274-278`). The hold persists across 2 s pump slices — a bounded pump is not
permission to advance frames (`gen1_client_entry.lua:489-496`); missing transport/peer never releases
it silently.

## (2) Wire shapes and bounds (shared constants on BOTH sides)

- `request_id`: ASCII `[A-Za-z0-9_.-]{1,64}`. `operation_id`/`command_id`: 32 lowercase hex.
  `command_sequence`: integer 1..2^53-1, never bool. `frame`: integer 0..2^53-1.
- `context_generation`/`physical_instance`: exact admitted 32-hex identifiers; `final_sha1`: 40
  lowercase hex; `digest`: 64 lowercase hex. Exact field sets enforced before decode/persist.
- Upload command body `{cmd: "checkpoint_upload", request_id, witness}`; success receipt
  `{request_id, witness, frame, context_generation, physical_instance, final_sha1, cart_hex}`.
- Refusal receipt `{request_id, witness, refused: {code, reason}}`; code ∈
  {identity_changed, unsafe_timeout, digest_mismatch}; reason printable ASCII 1..256.
- Release body `{cmd: "checkpoint_release", request_id, outcome, reason}`; outcome ∈
  {confirmed, abandoned}; reason printable ASCII 0..256, `""` on success, NEVER null.
  Release receipt `{request_id, outcome}`.
- Typed completion `{event: "save_upload"|"checkpoint_release", command_id, command_sequence,
  receipt}`; owner/session/seq/operation_id stay in the existing transport envelope.
- Upload witness: exact pinned `{frame, digest, projection, index, operation_id}`; index nonnegative
  integer; projection `"cartram-0498-8000-v1"`. No native_pretrade UPLOAD variant (native receipts are
  internal finalizer input with explicit tag/transaction refs, no synthetic index).
- `cart_hex`: exactly 65536 uppercase `[0-9A-F]`; verify SHA256 of the ASCII suffix
  `cart_hex[0x498*2:]` before `bytes.fromhex`.
- Known disagreements to fix in round 3: request_id bound server 63 vs client 25; release reason
  server None/500 vs client string ≤256.

## (3) Manager while a request is open

While collecting/preparing, refuse ordinary Recover until the Manager owns a stop/recovery
reservation, has revoked/stopped the predecessor and re-read the journal; block concurrent
Start/Resume/Recover. Resolve/abandon the request without pretending disconnected commands were
physically ACKed. Select ONLY an earlier journal-confirmed, payload/source/contract-verified
checkpoint; refuse if none, or if the pending-native-trade policy forbids rollback. A partial
upload/preparing directory is never recovery authority. Create the successor once, import BOTH
archived saves/rules/identities, mark the predecessor superseded with the discarded interval, require
both humans to reload. A prior confirmed checkpoint stays usable even if the latest request was
abandoned — the Manager's status==confirmed-only filter must not lose it (GAP in 1c2701b
`_confirmed_entry`/`handle_recover`).

## (4) Required joint tests (real server journal + production Lua router/durable_runtime/entry hold)

1. Success: server U bytes → Lua validator → both completion bytes → `record()`; delayed B/ACK across
   many pumps; zero intervening frames; success R with reason `""` accepted; release floor clears once.
2. Refusal/timeout: A mismatch or 90 s unsafe refusal while B's U is outstanding; 120 s no-traffic
   server expiry; B's late U accepted-as-abandoned; both R ACKed; the next request succeeds.
3. Failure/restart: second-U atomic commit; raw disk/source failure; server reopen with exact vs
   mismatched archive; same-owner client reopen at intent / U-ACK / R-intent; no resample, no
   duplicate release.
4. Adversarial wire/replay: wrong owner/request/witness, lowercase/short image, null/257-char release
   reason, bool sequence, duplicate operation, stale release / unrelated floor — all refuse without
   releasing another request.
5. Manager lifecycle: Recover racing Start while collecting; no prior confirmed checkpoint; previous
   confirmed + latest abandoned; pending trade; exactly one successor; both clients must reload.
