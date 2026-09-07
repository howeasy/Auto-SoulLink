# Gen 1 module reuse and UI integration boundary

Current UI checkout: `ui-phase7b-sources`, branch `codex/ui-rework`. This map records the Gen 1 owner's published handoff, not the contents of its moving worktree. Generation-specific implementation remains with Gen 1.

## Adopted shared modules

| Capability | Owner's frozen cut | Reused files | Selection boundary |
|---|---|---|---|
| Checked launcher and file closure | `31821e195985722893fd3717c31aaa8880fb40cf` | `server/runtime_launcher.py`, `server/journal_reader.py` | Generic only. The owner supplies the generation descriptor and complete client-file closure. Do not substitute this launcher for ordinary clients yet. |
| Canonical proof encoding | `0d042f6` | `lua/journal_document.lua` | Opt-in integer proof encoding, not a replacement for transport/local-state JSON. |
| Atomic component records | `8fd729f1fd4f4ece5f146ca66481f1c7f6de9021` then `e14b22d4eb3ad00782ebbbff5a64a48d824a8f90` | `server/protocol_journal.py` | Shared storage capability; generation state validation and activation remain separate. |
| Prepared native command handling | `b1049d4caf1e1baee348c41d5f6d33ecda162287` | `lua/command_executor.lua` | Armed/PENDING is not a terminal receipt or frame permission. |
| Shared server composition | `acc3005` | `server/durable_runtime.py` | Needs the generation's staged state, admission, event/receipt/recovery callbacks and authoritative initialization. |
| Shared client composition | `317e848` | `lua/durable_runtime.lua` | Needs the matching journal/executor/session/connector plus qualified generation/host bindings. |

The publisher's exact launcher dependency `server/lua_literals.py` was already present (Git blob `47376f7e730a5f8886cbbc33dce5bfb3a2cacfc8`). The final executor matches blob `1404c407fa0755ccc192dbc4e2205c45308cccca`; the journal matches `d8a2fd9c3d2ff676c6f01fc98694bf063edfda4a`. Existing executor/state-store test helpers also match the frozen client cut. The owner tests and contracts were reused with the code; no competing implementation was written.

## Still owned and moving in Gen 1

- `server/gen1_launcher.py`, `server/gen1_run_config.py`, runtime run-ID HELLO binding, `lua/gen1_client_entry.lua`, universal `lua/slink.lua` selection, and manager/server/runtime-boundary wiring. The current owner implementation selects **held_service** only. Its ordinary gameplay and physical adapters are not selected, and its full generation-specific closure is not frozen for UI adoption.
- Generation admission, staged runtime state, host qualification, prepared-run descriptor validation, stopped configured-journal decoding and authoritative fixture initialization. The UI must call the published generation wrappers when ready, rather than recreate them around the generic primitives.
- The operation/fixture initializer is not published. Configuring an already bootstrapped runtime is not an initializer. Keep the existing RBY HTTP mutation guard; do not reopen live mutations to make the 30 blocked E2E cases pass.
- The verified randomizer catalog, semantic verifier, structural injector, provenance publisher, recovery/publication lifecycle and authoritative job progress have no new qualified handoff. The UI may provide the approved presentation/HTTP wrapper once those contracts exist; it must not infer successful verification from subprocess completion or build a competing publisher.

## UI responsibilities and integration checks

The UI owns presentation projections, templates, manager routing, saved broadcast configuration, the shared duo harness and UI tests. It retains existing ordinary launchers and strict stopped-run behavior until the generation-specific selection is qualified. Merely importing `read_journal` must not enable SQLite-to-board conversion: its generic checksum/identity validation does not validate a generation's rule document. No fallback to stale `links.json` is allowed for a journal-backed run.

Before activating a new producer, obtain its exact commit and generation file closure; verify dependency hashes and current ownership/dirty state; preserve all existing status fields and unknown lifecycle values; then test Gen 3 compatibility before Gen 1 behavior. Held-service execution, read-only snapshots and prepared launchers must never be presented as ordinary gameplay or completed recovery.

The full Gen 1 E2E cutoff remains 15 natural-case passes and 30 guarded fixture-initialization failures, with no skips/deselections. Gen 3 still needs an owner-qualified ROM/savestate provenance pair. These shared imports do not change either release-evidence boundary.

## Validation of shared adoption

Critical dependency blobs match the owner handoff. The owner-supplied shared tests were added to the reviewed portable inventory: 69 new cases. Full unit/integration: **3976 passed, 2 skipped**. Portable selection: **3670 passed, 308 explicit deferrals**. Ruff is clean, **218 Lua files** parse, and **103 canonical-source checks** pass. Shared server/client modules load successfully; generation-specific selection and qualification remain unchanged.

RR owns the shared emulator-isolation primitives. `capture_spawn` and its standalone tests are frozen in `ea5a5501e2e6d9495317c972f9afe09c917699bc`; UI consumes that helper rather than retaining another PID-registration implementation. Generation-specific probe wrappers remain with their owners.

## Additive shared trade/runtime closure

Adopted the owner-specified final nine files from `72b91aca302a15272df5aadfc2b68beab652357f`, including the previously absent shared identity registry (unchanged base `231bf78`), its tests/contract, and the complete coordinator contract. All supplied source/test fingerprints match. The initial patch-only import was aborted when its missing base was detected; no partial merge remains.

The optional component-composition callback and semantic dispatch hook preserve default behavior. `pending_ids(player)` supplies the complete bounded obligation index; a limited delivery batch must never be used to infer completion. Shared identity witnesses and typed policy inputs are declarations that generation code must independently validate, not physical evidence by themselves.

The Gen 1-specific recovery composition (`gen1_trade_recovery.py`), typed routing, native/host adapters and activation remain with Gen 1. Its moving physical-policy test suite was not copied into UI; only the self-contained shared identity and six composition tests were adopted. The default held-service launcher still has no trade policy and ordinary gameplay/fixture-initialization/randomizer gates remain unchanged.

Complete closure validation: **4043 full-suite passes, 2 skips**; **3737 portable passes, 308 explicit deferrals**; Ruff is clean. Shared identity and composition tests add 58 reviewed portable cases. No generation-specific activation changed.

## Typed client journal composition

Reused the exact four-file cut `26aee4348a27e799b95a8f6ba9b0eaeb7ad0395c`: `lua/client_journal.lua`, its 11 shared composition tests, frozen v1 reader fixture and contract. The journal fingerprint matches the owner handoff; existing shared test helpers already match the parent.

Default two-argument callers retain v1 behavior. Only composed writes promote to v2; opening does not migrate a journal, and the old reader refuses v2. Terminal event identity/payload, receipt and outbox publish together; intermediate evidence cannot retire a command. These optional callbacks do not activate a generation policy or physical authority.

Gen 1 retains its native in-game UI/event/SaveRAM adapters: `gen1_trade_events.lua`, `gen1_receptionist_client.lua`, `gen1_partner_prompt_executor.lua` and `gen1_saved_trade_executor.lua`. They were not copied into the browser UI task. Runtime/artifact/network/recovery qualification remains separate from the owner's native file-transport tests.

Typed client-journal validation: **4054 full-suite passes, 2 skips**; **3748 portable passes, 308 explicit deferrals**; Ruff is clean and 218 production Lua files parse.
