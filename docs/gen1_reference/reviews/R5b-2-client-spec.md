# R5b-2 — Lua client side of paired checkpoint capture (implementation spec)

Status: accepted (coordinator, 2026-09-14). Source: Gen1-CodexPeer task cx-68c1908a at `26ad8d3`,
read-only. Server counterpart: R5b-1 (`server/gen1_checkpoint_runtime.py`, in progress).

## (1) Registration and routing
- Register NEW `gen1_checkpoint_client.new(...)` in `lua/gen1_client_entry.lua`'s services array beside
  HUD/faint, BEFORE `command_service_router.new` (`:234-274`). The router requires `handles(body)`,
  `ready(body)`, `adapter={prepare,classify,apply,receipt}`, `operations={request,accept,
  authorize_apply,revoke,status}`; exactly one service may claim a command
  (`lua/command_service_router.lua:4-53`).
- Handles only `checkpoint_upload`; unwrap with the existing Gen 1 wrapper; require the owned head
  command and exact `{request_id, witness}` shape. `operations` requests no write permit, accepts only
  nil, never writes cartridge memory. `ready=false` leaves the command pending; the executor supports
  explicit armed/PENDING and durable replay (`lua/command_executor.lua:15-24,38-58`).
- WIRE SHAPE (protocol constraint): the typed completion validator requires `command_sequence` and a
  `receipt` equal to the stored command receipt (`lua/client_journal.lua:42-50`). Emit
  `{event: "save_upload", command_id, command_sequence, receipt: {request_id, witness, frame,
  context_generation, physical_instance, final_sha1, cart_hex}}` via `complete_command`
  (`client_journal.lua:295-320`), which stores outcome/receipt + the typed completion in the outbox
  atomically; the session pump transmits it (`lua/gen1_observation_loop.lua:145`). No separate
  `command_ack`, no `journal:append`.
- Compose the checkpoint `completion_event` with the existing callbacks BEFORE `Journal.open`,
  preserving native/observation fallthrough (`gen1_client_entry.lua:189-212`;
  `lua/gen1_native_runtime.lua:20`).

## (2) Safe read point
- Wait unheld for `mem.isPartyWriteSafe()`; then acquire a DEDICATED checkpoint hold, verify
  `host.status().physical_stop_verified == true`, recheck safety/identity, sample. Use the safety
  conditions, not the faint executor (`lua/gen1_held_faint.lua:33-49`;
  `lua/gen1_write_safety.lua:44-67`).
- A new service registration alone does NOT acquire a hold: `writer_pending` considers only
  faint/native (`gen1_client_entry.lua:433-434,457-473`) — add checkpoint readiness/hold servicing
  there; do not classify it as a cartridge write or request a write permit.
- Require `#journal:pending_events() == 0` before sampling (NOT zero pending_commands — the
  checkpoint command itself is pending). Invoke after the observation step (observation_loop persists
  current signals/observations before servicing/pumping, `:120-145`). While held, keep pumping prior
  events until acknowledged; recheck pinned witness/ownership; abort on lifecycle changes; never
  block the ACK pump. Pattern: initial continuity's durable pending query (`gen1_client_entry.lua:342-352`).

## (3) Read and hash
- `memory_gb.sram_read_u8` is bank-selected, NOT a flat reader (`lua/memory_gb.lua:58-65`). Use the
  bulk pattern of `lua/gen1_full_save.lua:12-40`: `memory.read_bytes_as_binary_string(0, 0x8000,
  "CartRAM")`, exact length check, uppercase HEX lookup + `table.concat` (array/scalar fallbacks there
  are reusable). One coherent sample under continuous hold; never split across advancing frames.
- Local digest: `journal.store.backend.sha256(cart_hex:sub(0x498*2+1))` compared to
  `command.witness.digest` and the named projection, exactly as save_witness does
  (`lua/gen1_engine_signals.lua:25-30`). Do not hash decoded bytes.
- Persist the sampled upload in `adapter.prepare`'s intent; `classify` = completed read; `receipt`
  returns those SAME bytes/metadata; `apply` never writes. On retry never resample a different frame
  into the same completion (`command_executor.lua:38-58`).

## (4) Sizes and limits
- 32768 bytes → 65536 hex chars ≈ 65 KB JSON. Client codec: 4 MiB frame / 1 MiB string
  (`lua/json_codec.lua:206-218`); journal: 128 events / 256 commands (`client_journal.lua:7`);
  connector: 4 MiB line, 8 MiB queue, 128 lines, 65536 bytes per pump with partial sends across
  pumps (`lua/connector.lua:54-58,297-324`); no smaller cap in `lua/socket.lua:1-35`.

## (5) Retirement
- The locally completed command stays represented by its durable pending upload until the server
  ACK; retire only through normal event acknowledgement (`client_journal.lua:270-293`). Duplicate
  `command_id` returns the stored result; a conflicting completion receipt refuses; replay the original
  payload/operation id, never reread CartRAM (`command_executor.lua:38-42`;
  `client_journal.lua:305-320`). A replacement physical identity must not regenerate the upload.

## (6) Files
- NEW `lua/gen1_checkpoint_client.lua`; `lua/gen1_client_entry.lua` (registration, callback
  composition, dedicated hold integration); NO `gen1_held_faint.lua` edit (router is in entry).
- `server/gen1_launcher.py` OBSERVATION_FILES if construction is Observation-gated (`:21-28,67-69`);
  `runtime_launcher.file_bundle` hashes every shipped file automatically (`:25-40`). The selected
  scenario's `source_files` does not enumerate client Lua (`gen1_selected_scenario.py:411-421,
  498-514`).
- NEW `tests/unit/test_gen1_checkpoint_client.py` with the lupa.lua54 model setup
  (`tests/unit/test_shared_hud_transients.py:5-11`); test real router/journal callback composition
  as well as adapter behaviour.

## (7) Falsifiers / tests
Unknown-command routing today; a bare typed payload fails the completion validator; unsafe/unheld/
undrained state performs ZERO CartRAM reads; wrong digest/identity refuses; exact 65536 uppercase hex
survives real codec/journal reload; duplicate delivery retains the original frame/image; partial send
+ ACK retires once; launcher closure includes the new file.

## (8) Risks
No per-byte string growth; bounded hold timeout with a visible refusal, never an indefinite wait;
read cost and latency unmeasured (no emulator in this card).
