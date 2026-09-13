# Architecture candidates 1 and 2: bounded closeout

Status: **both refactors integrated in source commit `19edbb26d25406106323288427f61127b2bb9859`**, 2026-09-13. PROVED at MODEL ONLY level, not release approval. Current authority remains [the master guide](../RC_MASTER_GUIDE.md).

## Scope and source basis

Owner explicitly approved both behavior-preserving refactors, then agent closeout. Base: `d9757bd56841eef7d41ad8d3a524f6d15364bf52`, canonical `gen1/rc`. No recovery capability, command protocol, release requirement, threshold, route harness or gameplay feature is added.

1. Native lifecycle: move the three executor terminal-phase vocabularies, pending-command/query checks and embedded pump/hold/slice ordering from `gen1_client_entry.lua` into the existing `gen1_native_runtime.lua`. The entry retains ordinary/faint priority and supplies the single shared runtime pump. The regression basis is already-fixed `abc0f64`, `10a500a`, `df38453`; this work does not claim another live defect.
2. Coherent capture: one `gen1_inventory_checkpoint.lua` owns full/fingerprint capture, writer-hold cleanup, exact-frame native pairing and absent/null distinctions. Inventory remains the first return, fingerprint/dirty keep their existing positions, and the native observation travels in the same return rather than a mutable slot and later callback. Observation sequencing, durable publication and command servicing stay in the loop. `00843b9` is the same-frame invariant's existing source basis.

Deletion test: both modules own real ordering and state invariants; removing them would return that knowledge to their callers. No new generic framework or pass-through module is justified. [Domain terms](../../../CONTEXT.md) distinguish a native command lease from its command acknowledgment, and an inventory checkpoint from its native party observation.

## Ownership and review

- Coordinator/reviewer: Codex task `01a06d9c-4200-7023-a822-7663ed2ea1dd`; docs, baseline, combined verification and independent source/diff review only.
- ARCH-1 implementer: `/root/architecture_lifecycle_impl`, native runtime and its injection test only. No SLink live Claude peer was reachable; a fresh headless Claude request failed to start (`PEER_FAILED`, exit 1), returned no acknowledgment and made no source edits. That grant was released before Codex fallback acknowledgment and edits; no Claude job remains in flight.
- ARCH-2 implementer: `/root/architecture_capture_impl`, checkpoint module, entry/loop/launcher integration and assigned tests only.
- Shared entry edits have one writer: ARCH-2. No emulator lane granted. Root `master`, parked experiments and other games remain untouched.

## Verification ledger

| Cut/check | Result | Evidence |
| --- | --- | --- |
| Base five-file focused regression | 91 passed, 0 failed, 0 skipped | `.cache/architecture-baseline.xml` |
| ARCH-1 real-runtime lifecycle interface | 39 passed, 0 failed, 0 skipped | Worker command: `python -m pytest tests/unit/test_gen1_native_runtime_injection.py -q` |
| ARCH-2 real-reader capture and integration | 96 passed, 0 failed, 0 skipped | Worker command: `python -m pytest tests/unit/test_gen1_inventory_checkpoint.py tests/unit/test_gen1_native_entry.py tests/unit/test_gen1_native_reattach_integration.py tests/unit/test_gen1_launcher.py -q` |
| Frozen combined affected-subsystem regression | **640 passed, 0 failures/errors/skips, 155.34s** | `.cache/architecture-combined.xml`, SHA256 `DB31E3D887A1A76429A7CB92DD7A4BD4AD2D06FAD68ADBFFA9CCE5EEC78BB3AC` |

Both first-falsifier runs failed as expected before their interfaces existed (missing `pending()` / missing capture module); these were exploratory tests, not qualification runs. ARCH-1's targeted first run deliberately deselected 37 tests. One intermediate fixture expectation was corrected: an unreadable receptionist store raises in the existing native pump before the shared pump, while the host remains held; production behavior was not loosened to make the test pass.

## Independent diff review

The coordinator authored no production/test changes and independently checked the frozen implementation against base source and existing tests. No production regression was found. One test-fixture issue was corrected by ARCH-2 before freeze: an absent CartRAM byte must not fall back to System Bus at the same numeric address. Checked launcher closure includes the new module; entry preserves faint priority and exactly one shared pump. Tests exercise actual inventory/fingerprint/native-party readers across all three titles, including 17 bulk reads for seed/quiet checkpoints, 24 for changed/forced checkpoints, no quiet native read, stale native refusal and writer-hold release on capture error. Native tests use the real runtime and journal with modeled host/memory, covering three lease types, ACK/prune, unreadable states, oldest-command ordering and failed-host/no-window refusal.

Lint of changed Python files found **no new diagnostics**. `test_gen1_native_reattach_integration.py` has four pre-existing findings, reproduced with `git show d9757bd:tests/unit/test_gen1_native_reattach_integration.py | python -m ruff check --stdin-filename tests/unit/test_gen1_native_reattach_integration.py -`: unused top-level `Path`, unused `TILES`, unused local `json`, and local `Path` redefinition. Other changed Python files pass. These are not represented as a clean whole-repo lint verdict; any later hygiene cleanup is confined to those imports and is not an RC gameplay blocker added by this task.

Frozen production SHA256 values, verified against both implementers' receipts (raw local bytes; EOL-sensitive, use the source commit for cross-checkout comparison):

```text
0BB4A964CD1A0BF935DC55C4A7F3F96677399387A38CCF3A2EA018D671576DBE lua/gen1_inventory_checkpoint.lua
35E7B05F67BEA8380704A9F0F87705FB5738F4544E8D2471E515524EC78E97B5 lua/gen1_client_entry.lua
83AA70DCB52CA6A70F3568EADFC2677E701965CE4D6DCA9668E3E1EA187E9237 lua/gen1_observation_loop.lua
D402BF4BCA8C4B0426F509A183A3860D2297C88C207330354CC9A590E6B73F2F lua/gen1_native_runtime.lua
4C2C9CA4306D79DB6C0DF8F4F73401B30DE634C84BDAFB509493C79716F8AD69 server/gen1_launcher.py
```

Baseline command (canonical checkout):

```powershell
python -m pytest -q tests/unit/test_gen1_native_runtime_injection.py tests/unit/test_gen1_native_entry.py tests/unit/test_gen1_observation_loop.py tests/unit/test_gen1_native_reattach_integration.py tests/unit/test_gen1_launcher.py -o addopts= --junitxml=.cache/architecture-baseline.xml
```

Combined command (canonical checkout, all collected tests in these file selections; no `-k`, `-m`, deselection or skips):

```powershell
$architectureTests = @(rg --files tests/unit -g 'test_gen1_native*.py' -g 'test_gen1_inventory*.py' -g 'test_gen1_observation*.py' -g 'test_gen1_initial_observation*.py' -g 'test_gen1_runtime_client.py' -g 'test_gen1_runtime_server.py' -g 'test_gen1_service_continuity.py' -g 'test_gen1_launcher.py' -g 'test_gen1_held_faint_client.py' -g 'test_gen1_hud_client.py' -g 'test_gen1_free_service*.py')
python -m pytest -q @architectureTests -o addopts= --junitxml=.cache/architecture-combined.xml
```

`git diff --check` passed. Receipts in `.cache` are ignored local evidence and do not travel automatically with a clone/worktree. Source commit includes ten production/test files; the glossary, guide, register and this record are a separate documentation-only closeout commit.

## Closed assignments and handoff

Both implementers acknowledged base/exclusive paths before editing and released ownership before the combined test. Coordinator approved these owner-requested refactor claims, authored no production/tests, independently reviewed and accepted both. Their first falsifiers establish new interfaces absent on the base, not undiscovered gameplay failures. ARCH-1 supplies the native module seam; ARCH-2 alone edits its entry caller, so there was no overlapping file writer.

| Closed claim | Exclusive files | Evidence context, not new proof registrations |
| --- | --- | --- |
| ARCH-1 | `lua/gen1_native_runtime.lua`; `tests/unit/test_gen1_native_runtime_injection.py` | Existing `trade.red.offer-lifecycle` and R/B/Y counterparts; native lease/ACK separation preserved |
| ARCH-2 | `lua/gen1_inventory_checkpoint.lua`, `lua/gen1_client_entry.lua`, `lua/gen1_observation_loop.lua`, `server/gen1_launcher.py`; `tests/unit/test_gen1_inventory_checkpoint.py`, `test_gen1_native_entry.py`, `test_gen1_native_reattach_integration.py`, `test_gen1_launcher.py` | Existing `trade.yellow.blob-fidelity`; coherent party observation preserved, not a completed trade |

Closeout check 2026-09-13 12:40 UTC: both workers and prior scan worker complete, no delegated/Claude request awaiting completion, and no EmuHawk/Python/Java job. The canonical source is `19edbb2`, with only the named closeout documents pending their final commit at this check. Root `master` remains clean at `adf3362`; no worktree was created, deleted, moved or cleaned. No push or merge to `master` occurred. After the documentation commit the coordinator verifies clean Git and stops.

Next owner/action is the fresh user-assigned coordinator's P0 input/static preflight against this source cut (or verified docs-only descendant), using the existing prepared brief. No architecture task remains ACTIVE; do not rerun the completed survey/refactors. No private state, active worker or reply from this session is needed to resume.

## Evidence limits and next work

Modeled hold/memory/clock tests can qualify these interfaces and their composition, not physical native trade, actual bundle launch, SaveRAM persistence, resumed gameplay or FPS. Existing physical receipts remain tied to their original source cuts. The remaining N/R/C/D/E/F/H plan stays in the master guide and static catalog, not in this record.
