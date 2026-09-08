# Gen 1 module reuse and UI integration boundary

Current UI checkout: `ui-phase7b-sources`, branch `codex/ui-rework`. This map records the Gen 1 owner's published handoff, not the contents of its moving worktree. Generation-specific implementation remains with Gen 1.

Lint scope: historical "Ruff is clean" statements below refer to the approved plan's explicit `ruff check . --select E9,F6,F7,F81,F82` gate. They do not establish a clean run under every rule in `ruff.toml`. The peer-review follow-up below reports the full-config result separately.

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

## Published prerequisites reserved for the next producer handoff

Gen 1 published `6369c0b253c7a79fb232a7b513cdf8fabcf9d28c` (parent `26aee43`): exactly `server/patch_plan.py`, `tests/unit/test_patch_plan.py` and `docs/shared-patch-plan.md`. The reviewed pure `PatchSpan`/`apply_spans` helper checks fixed-size preimages, nonoverlap, protected ranges and optional bank boundaries before producing bytes. Reuse this owner module when integrating the qualified cartridge builder; do not implement another binary write-set engine in Tools. It remains unimported here because the generation builder/publisher is not yet qualified. Source identity, symbol/free-space provenance, checksum policy and semantic admission remain the caller's responsibility.

Gen 1 also reports adopting the shared runtime-lease cut `36821a1ddb3d9b9ec55ad67a988e1a3668274663` (`server/runtime_lease.py`, its tests and contract). Track that dependency in the next generation-specific handoff rather than duplicating process ownership in the UI. Neither published helper alone authorizes ordinary gameplay, native-frame authority, fixture initialization or randomized publication. The owner's combined native artifact smoke evidence is separate from those remaining gates.

## Shared-helper review, 2026-09-08

Reviewed the actual published branch objects against UI `029a42a`, preserving the active UI checkout and every generation checkout. The journal's `9d031d1` component-revision correction was already present; no duplicate import was needed. Six dependency-checked cuts applied without conflicts:

| Published cut | UI adoption | Effect and boundary |
| --- | --- | --- |
| `e1d2acf` | `831b046` | Default-no-op suspension hook after hold notice, before reading/persisting the barrier. Generation interruption policy remains external. |
| `3801f83`, formatting correction `e261d13` | `010830f`, `40608e8` | Private validated state-store cache with detached typed copies; generic trade transition driver. No automatic generation policy selection. |
| `3649e2d`, correction `cfed9be` | `6189ccc`, `4cf0f89` | ASCII JSON scanning and shared frame window/pacer. Operation budgets survive scope changes; unrepresentable clock deadlines are refused. No host execution or frame authority is supplied. |
| `77c7562` | `0342b28` | Syntax checks explicitly use Lupa Lua 5.4, matching the pinned host instead of Lupa's changing default. |

New consumer tests exercise suspension with a real SQLite journal: default behavior, hook-before-barrier ordering, preservation of an interruption commit in the next snapshot, hook/barrier failure, and unconditional session/challenge revocation. The other imported source/test files retain their published bytes. The portable inventory adds only the exact new cases; no existing case is removed or reclassified.

The following published helpers are available for the generation integration, but remain **unimported and unactivated** in this UI checkout. Reuse their frozen modules when an actual consumer and its complete dependency closure arrive:

| Published cut | Reuse responsibility |
| --- | --- |
| `36821a1` runtime lease | Exclusive runtime process ownership; read-only readers remain separate. |
| `6369c0b` patch plan; `7a5c7aa` ROM change audit | Checked byte edits and exhaustive change accounting; neither supplies cartridge semantic verification or publication. |
| `9f7f6c7` staged panel | Native page staging with owned generations; browser presentation must not duplicate the cartridge panel. |
| `ad968d3` SaveRAM; `9704623`, corrections `89ef524`/`eefcbba` staged commands | Host save adapter, remote image/receipt verification and ordered durable child stages. Host/profile/context and physical policy remain generation-owned. |
| `160412c` observations/keyed inventory | Durable checkpoint sequencing and bounded keyed comparison; key equality alone does not prove logical identity or historical events. |
| `085acbe` party grants; `6d85974` linked death | Rule staging after generation-owned evidence. Browser projections do not reimplement these rules. |
| `bc3ad9d` held-write permits | One-use scope-bound permits; no ordinary execution or frame authority. |
| `2899b53` Gambatte profile; `114f3f3` stat experience | Explicit host-profile selection and shared arithmetic; neither changes production cartridge selection implicitly. |

Several shared branch tips only add Pillow for their native test dependencies. Do not replace the UI's split requirements wholesale with a provider branch's older manifest. Adopt the dependency when importing tests that actually need it.

Gen 1's reported initial enrollment (`initial_observation: queued/acknowledged`) is not gameplay history or ordinary readiness. Its browser patcher, producer, bootstrap/observation and recovery activation remain generation-owned pending a bounded frozen handoff. The full Gen 1/Gen 3 E2E and verified randomizer completion gaps recorded above remain outstanding; shared helper tests do not close them.

Gen 1 reconfirmed the production frame/syntax corrections; the initial review missed the separately published test-only normalization `9b3e1fd`, now adopted as `90b55e8`. Its moving held-service launcher can now authorize an exact pending faint write under a one-use permit and fixed-frame proof; ordinary execution remains false and this generation binding is not published for UI adoption. Frozen presentation facts remain unchanged.

Validation: **4126 unit/integration passes, 2 existing skips** (86.06 seconds); **3820 portable passes, 308 explicit deferrals** (57.02 seconds); **16 JavaScript passes**, **220 Lua 5.4 parses**, **103 canonical-source checks**, and clean Ruff E9/F6/F7/F81/F82. Seven production/tool blobs match the exact published corrected cuts. The focused shared regression selection is 104 cases, of which 72 are new portable inventory entries.

## Peer-review reconciliation

Claude's `UI-Codex Collab` review identified the missed test-formatting cut and a gap in suspension containment coverage. The exact two-file `9b3e1fd4f92d36ef10493d57f678e385c44830fa` cut is adopted; frame test IDs are unchanged. Four additional tests use the real runtime constructor, recovery barrier, session gate and SQLite journal with a portable generation document binding. They verify refusal after a hook failure, actual TCP NACK/EOF for both `JournalError` and `RuntimeError`, and invalidation of the persisted recovery ticket on reopen. The original four ordering tests remain intact.

Full-config Ruff with the pinned UI environment reported **73 findings before normalization, 59 afterward**. All 59 remaining findings are in 29 files unchanged from `029a42a`; the 14 introduced frame-test findings are removed. The approved fatal-error subset passes separately. The peer's 28/14 whole-tree counts were not reproducible here, so they are not used as validation evidence. No broad formatting sweep or rule suppression is included in this follow-up.

The connection loop already catches arbitrary callback exceptions and closes its writer in `finally`; no exception-type production change was needed. Gen 1 owns the reported `TradeDriver.new_id` validation and pacing-contract clarifications. The alleged execution-window reason overwrite is not supported by the reviewed control flow: missing scope clears the grant before `live()` checks it and returns.

RR explicitly reconfirmed the frozen three-file RuntimeLease handoff `36821a1ddb3d9b9ec55ad67a988e1a3668274663`, with unchanged file contents and no superseding cut. A `codex/shared-*` branch is a discovery convention, not the freeze authority. Pin the owner-published commit and file closure; do not import the moving RR branch head. The lease remains unimported in UI pending a real lifecycle consumer.

Follow-up validation: **4130 unit/integration passes, two existing skips** (71.15 seconds); **3824 portable passes, 308 explicit deferrals** (48.07 seconds); all 64 focused frame/suspension tests pass. The changed test files pass full-config Ruff; the required repository subset passes; 220 Lua files parse under 5.4. Existing whole-tree full-config findings remain explicitly outstanding above.

### Admitted-session follow-up

The second peer review correctly distinguished first-frame rejection from revoking an admitted writer. Three new cases now complete a real HELLO and control exchange, assert a registered session/writer and recorded challenge, and expire the heartbeat at exactly `TIMEOUT`. The real stream queues a hold before the hook runs and delivers that hold before its NACK; queueing is not claimed as proof of peer receipt at hook entry. Tests cover hook failure, successful interruption plus barrier commits (exactly two revisions), and SQLite refusal of the barrier commit while preserving the interruption revision. Session, challenge, heartbeat and writer cleanup, plus the live-writer close guard, are asserted.

The earlier tests now verify both first-error and subsequent "requires reopen" NACK reasons and traceback logging only for unexpected exceptions. The frozen wire still reports `contract_pending` for a latched failure; consumers must not interpret that state alone as proof retry can recover or as authority to resume. Gen 1 agrees that a distinct machine-readable reopen code requires a later protocol change.

Disposable in-memory mutation runs confirmed the admitted-writer test fails if session clearing is removed or the hold notice is moved after the hook. Production files were not changed for these runs. The remaining whole-tree lint findings are unrelated to this correction.

Adopted Gen 1's published `20b80e31c32d6902084dd8201df14e90866486ac` as `198dae4`: `TradeDriver` now rejects explicit noncallable identifier factories and retains falsey callable factories. Eight owner tests cover those boundaries. The shared pacing contract now explicitly describes permission/pause resets and distinguishes cadence from finite execution budgets. Production frame-window/pacer code is unchanged; the normalized frame test files already match the cut.

Completed validation: **4141 full-suite passes, two existing skips** (80.08 seconds); **3835 portable passes, 308 explicit deferrals** (56.41 seconds); 81 focused cases pass, including all 11 suspension cases. Changed Python files pass full-config Ruff; the required repository subset passes and 220 Lua files parse under 5.4. The six shared-cut files match `20b80e3` exactly. The previously recorded whole-tree lint backlog remains separate from these passes.

## Held-client fairness and optional operation binding

The first memorial-primitives cut `b23856140b8616ca21bb0d291c8cdd59ff750673` included an optional operation-authority binding as well as scheduling changes. Adoption of its runtime was deferred until Gen 1 supplied the corrected, independently tested `9433c80c6bc0e9c43a0624521eedb67f7a886294` closure. That follow-up checks metadata, admission and control freshness again after the generation authorization callback returns.

Selectively adopted the full `lua/durable_runtime.lua`, `lua/state_store.lua`, `tests/unit/test_runtime_operation_binding.py`, `tests/unit/test_runtime_fairness.py`, `tests/unit/test_client_state_store.py` and `docs/shared-held-runtime-latency.md` from `9433c80`. Eight pre-existing dependency files match the published cut exactly: client journal, JSON codec, client session, control service, command executor, wire protocol, platform identity and the Python client-journal test helper. The state-store test fixture now explicitly runs Lua 5.4. Two imported Python test files had four E702 findings; splitting their semicolon statements preserves their published ASTs and adds no test behavior.

Without `operation_execution`, applying a command still requires ordinary execution authority. With it, the generation must explicitly supply all command-proof callbacks; the shared service rejects late authorization, changed context and revoked ownership before reaching the adapter. Six self-contained tests cover default/deny/allow/late/context/revoke. The fairness test proves that slow but timely control responses cannot starve a queued durable receipt while the host stays held. Summary status omits large execution receipts; neither summary status nor `is_bound()` is completion or recovery proof. The state-store revision token remains an in-memory committed revision, not an on-disk integrity check.

No `platform_saveram`, linked-death/memorial helpers, generation adapters, launcher bundles or Manager launch setup are imported by this cut. Those published or moving components remain with their owners until a real UI consumer and frozen integration closure are available. Ordinary gameplay and verified-randomizer completion gates remain unchanged.

Validation: **4149 full-suite passes, two existing skips** (76.23 seconds); **3843 portable passes, 308 explicit deferrals** (54.75 seconds); 76 focused shared-client cases pass. Required Ruff and full-config Ruff on the imported tests pass; 220 production Lua files parse under 5.4. The two production Lua files match the frozen owner cut exactly. Eight new portable test IDs were registered without removing or changing existing IDs.
