# R5b — paired checkpoint capture and recovery (implementation spec)

Status: accepted claim record (coordinator decision 2026-09-14, vetoable). Source: Gen1-CodexPeer
research task cx-f84ca8bb at source cut `66abc02`, read-only. Policy: see the R5 claim row in
RC_MASTER_GUIDE.md (both players roll back to the last COMPLETE PAIRED checkpoint). Envelope:
`server/paired_save_checkpoints.py` (R5a). Slices: R5b-1 server capture, R5b-2 Lua client
adapter + launcher closure, R5b-3 Manager proxy/recover/download + UI.

## (1) Capture trigger and transport

- `POST /api/runs/{id}/checkpoint` on the Manager proxies to THAT live run server's new
  `POST /api/checkpoint`. Return 202 with `request_id`/status, never "checkpoint saved".
- The run server persists the request in `components["gen1-checkpoint"]` before requesting either
  upload. The Manager never opens a running ProtocolJournal (`server/gen1_runtime.py` owns it).
- Reuse the EXISTING durable command outbox: new read-only `cmd="checkpoint_upload"`,
  body `{request_id, witness: <pinned current witness>}`, one per admitted player.
- Client returns a new typed semantic event `save_upload` carrying `command_id, request_id,
  witness, frame, context_generation, physical_instance, final_sha1, cart_hex`; handled in NEW
  `server/gen1_checkpoint_runtime.py` through the gen1_runtime typed-event dispatch
  (`gen1_runtime.py:387-405`). Commit the upload and acknowledge exactly its request command
  atomically. No invented client identity, no unauthenticated HTTP upload.
- The client appends the event to its existing durable journal and lets normal session pumping
  deliver/retry it (`lua/gen1_observation_loop.lua:120-146`; `protocol_journal.py:361-428`).
- Client reads only at its owned `isPartyWriteSafe` + verified held checkpoint, after all earlier
  observations/save-witness events have ACKed; reads CartRAM 0x0000..0x7FFF and sends EXACTLY
  65536 UPPERCASE hex characters (full 32 KiB: R5a archives a full save and `--resume-save`
  imports a complete file; `gen1_initial_observation.py:92`, `lua/gen1_held_faint.lua:33-49`,
  `server/bizhawk_launch.py:119-144`).
- Server validates hex alphabet/length BEFORE decoding, then uses EXISTING
  `gen1_run_resume.save_digest(cart_hex)` (hashes the ASCII uppercase hex suffix
  `cart_hex[0x498*2:]`, NOT raw bytes) against the referenced save_witness digest/projection;
  also retains SHA256 of the full decoded 32768 bytes (`gen1_run_resume.py:37-40`;
  `gen1_engine_signal_runtime.py:15-21`).
- Budget the event to <= 128 KiB encoded JSON and enforce that bound explicitly (the 4 MiB
  server line limit and decode_frame are not the event limiter; audit the client encoder/outbox).

## (2) Server capture

- `gen1_checkpoint_runtime.start` records request id, witness refs/digests, global rule/identity
  state digest and admitted bindings; requests only when: both latest witnesses valid, same
  cartridge/source pins, no active trade, no pending captures/memorial/rebuild/storage/native/
  death work, empty ordinary command outbox. Exempt ONLY the two exact checkpoint read commands
  from "pending" while collection is in progress (`gen1_run_resume.py:127-196`).
- Each upload must match player/session/body command and current physical binding, have a
  nondecreasing observed frame, and match the PINNED witness still current. Reject replacement /
  new save / gameplay since the request; the first player stays held after its upload until the
  paired capture commits or cancels. A byte match is not authority to mix rules revisions.
- No gameplay since EACH save: reuse the existing `_no_gameplay`/`_pure_heartbeat` policy plus
  explicitly classified checkpoint request/upload/ACK events; recheck the pinned rules/identity
  digest at finalization (`gen1_run_resume.py:86-124,181-196`). Do NOT call `audit_predecessor`
  on the live run (it requires stopped registry state and opens a directory snapshot,
  `:127-148`): extract its pure snapshot/event-policy checks into a reusable helper and query the
  owning runtime in one transaction/revision.
- After both accepted uploads: `rules = canonical_json(stage.rules.document()).encode()`,
  `identity = canonical_json(known_keys(document, stage.rules.document())).encode()` (keep
  `rules.memorial`; checkpoint-era known_keys, `gen1_run_resume.py:59-83`;
  `staged_state.py:100-145`).
- Store root = `runtime.data_dir` (`PairedCheckpointStore(root)` appends `/checkpoints`).
  `contract_fingerprint = digest(runtime.contract)`. Provenance (flat scalars):
  `{run_id, registry_run_id, journal_revision, request_id, witness_a_op, witness_a_index,
  witness_b_op, witness_b_index}`. Pass both decoded saves and the five-field witnesses unchanged.
- `source_fingerprint`: no existing witness field holds the frozen source identity. Reuse the
  launch configuration's files list from `runtime_launcher.file_bundle` (paths, normalized byte
  hashes, encoding) bound to a NEW startup server-source manifest recorded by the runtime:
  `digest({client_files: <pinned list>, server_files: <pinned path/hash list>})`; refuse absent or
  drifted pins. Never the launcher ZIP/script hash alone (embeds run identity;
  `runtime_launcher.py:26-40,45-68`).
- Serialize publication per run. Before `store.capture`, journal a prepared checkpoint/export
  intent with upload refs and frozen fingerprints; keep both clients held. Publish the archive,
  then journal the resulting checkpoint_id/manifest digest and mark the request complete; only a
  journal-confirmed id is downloadable/recoverable. On a crash between archive publication and
  journal commit, reconcile the durable intent against the exact archive or retain the previous
  confirmed checkpoint — CURRENT alone is not the cross-store commit.

## (3) Recover

- `POST /api/runs/{id}/recover {"checkpoint_id": <id>}`; omitted id selects the LAST
  JOURNAL-CONFIRMED complete checkpoint (never a bare CURRENT pointer). Explicit confirmed UI
  action stating BOTH players lose progress after the checkpoint time. Stop/retire the old runtime,
  revoke old-client authority; refuse an active/pending native trade (`gen1_run_resume.py:151,
  170-175`; that lane belongs to N3).
- Load and verify full payloads, provenance/run identity, unchanged source and cartridge contract.
  Build the EXACT existing resume shape `{from_run, required: {a: {digest, projection,
  witness_index: index, operation_id}, b: {...}}, rules: <decoded archived rules>,
  contract_hash: <checkpoint.contract_fingerprint>, identities: <decoded archived identity>}`; do
  not add checkpoint_id to that strict dict (`gen1_run_resume.py:211-239`).
- Create a NEW successor via `gen1_run_config.create_runtime(..., resume=validated_record)` and
  the existing native/prepared cartridge construction, through an internal validated-checkpoint
  branch of Manager creation — NOT ordinary `resume_from`'s audit of the predecessor's newer state
  (`gen1_run_config.py:129-151`; `gen1_run_resume.py:181-207`). Lineage in a separately validated
  recovery component / registry metadata: `successor.recovered_from = {run_id, checkpoint_id,
  checkpoint_revision, discarded_through_revision}`, `predecessor.recovered_by = <successor>`;
  prevent old restart/replay; preserve the abandoned journal/files. Never label a rollback as a
  completed trade; never clear a pending native transaction to pass the refusal.
- REMOTE FILES: the Manager cannot write B's SaveRAM on B's machine. Keep archived bytes on the
  host; expose per-player authorized downloads `GET /api/runs/{successor}/recovery-save/{player}`
  restricted to that confirmed checkpoint/player, bounded attachment `<player>.SaveRAM` with
  full-file hash. No filesystem-path endpoint. Each player downloads their own file and starts the
  NEW successor bundle with `--resume-save <local file>` (launcher file picker as fallback).
  `launch.json` carries the expected resume digest/projection, not a remote path
  (`tools/launch_bizhawk.py:37-55`; `bizhawk_launch.py:119-144`). `prepare` copies/verifies the
  local save into its OWN `root/<new run_id>/<player>/SaveRAM` under its lease.
- No Continue-gate relaxation: resumed initial observation already recomputes `save_digest`,
  requires `continue_witness`, validates cartridge/physical/context/frame
  (`gen1_initial_observation.py:175-185`); wait for BOTH enrollments before gameplay
  (`gen1_run_resume.py:242-254`; `gen1_runtime.py:235-253`).

## (4) Manager UI

- Checkpoint (enabled on a selected running Gen 1 run with no request busy) and Recover (explicit
  confirmation; a complete confirmed checkpoint; no native pending state) beside the run detail /
  Resume actions; classes `mgr-btn`, `mgr-new-disclosure`, `mgr-rand-note`, `mgr-rand-error`;
  inline `x-text` status. State `checkpoint = {busy, status, error}`, `recovery = {busy, error,
  checkpoint_id}`. "Checkpoint requested: waiting for A/B" → "Last checkpoint: <time>, both
  players" ONLY after journal confirmation. Recovery result shows successor launcher links plus
  A/B save downloads; never show a server-local path to the remote player.

## (5) Tests (unit, no emulator)

- start: missing/unpaired/stale witnesses, pending trade/work → refused.
- upload: wrong command/player/binding/ROM/size/non-hex/digest, gameplay since save → refused;
  duplicate upload idempotent; one upload never publishes; both valid → publish with matching full
  files/rules/identity/provenance.
- cross-store failures: before both uploads, archive-before-journal, journal commit failure, stale
  completion retry, concurrent requests, restart reconciliation → last confirmed checkpoint kept;
  CURRENT advancing without journal linkage cannot enable recovery.
- recover: validated checkpoint → exact validate_resume-compatible record; later rules/keys
  excluded; two fresh Continue enrollments required; wrong checkpoint/run/source/player/file and
  active native trade → refused. Launcher: simulated remote download into a distinct local root,
  full 32768-byte copy/projection validated, predecessor files preserved.

## (6) Files

Dependency (not edited here): `server/paired_save_checkpoints.py`; reuse
`runtime_launcher.file_bundle`, the protocol journal/outbox and the existing save-import APIs.
Gen 1 / product: NEW `server/gen1_checkpoint_runtime.py`; NEW `lua/gen1_checkpoint_client.lua`;
`server/gen1_runtime.py`; `server/gen1_runtime_state.py` (component validation);
`server/gen1_run_resume.py` (pure audit reuse/classification); `server/server.py` (live checkpoint
endpoint); `server/manager.py` (proxy/recover/download/ownership); `server/templates/manager.html`;
`lua/gen1_client_entry.lua`; `lua/gen1_held_faint.lua` (read-command adapter/routing);
`server/gen1_launcher.py` (new Lua file closure); NEW tests
`tests/unit/test_gen1_checkpoint_runtime.py`, `tests/unit/test_gen1_checkpoint_client.py`,
`tests/unit/test_manager_checkpoint_recovery.py`, `tests/unit/test_gen1_checkpoint_save_download.py`.
`--resume-save`, Continue and `validate_resume` stay unchanged unless a seam test shows a concrete
incompatibility; never widen `validate_resume` to accept extra fields.

## (7) Falsifier

At `66abc02` no Manager checkpoint route and no `save_upload` event kind exist; two valid
simulated upload events must produce one journal-confirmed checkpoint with both exact files. The
compact save_witness carries no save bytes and cannot satisfy this.

## (8) Risks / bounds

Retrospective recovery is impossible without a previously captured complete checkpoint; clients
may keep playing after saving, so abort on changed semantic state rather than best-effort pairing.
Stale lock / store corruption / cross-store interruption fail visibly; no fallback when source pins
are absent. R5a durability and manual-lock ceilings remain explicit. A pending native trade belongs
to N3, not this rollback action.

## (9) Decision

READY by the coordinator: R5b-1 (server capture) first on an isolated worker after R5a round 3
lands; R5b-2 (Lua client + launcher closure) next; R5b-3 (Manager proxy/recover/download + UI)
last. Live proof is deferred to the human session.
