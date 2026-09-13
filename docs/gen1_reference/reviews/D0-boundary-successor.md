# D0 boundary: from the one-off enrollment controller to a reusable checked scenario interface

Card `D0-boundary-successor`, claudex task `cx-1a6dd944`. Claude Gen1-Collab2 (`4ec907e2…`), HOUNDOOM, **2026-09-13 18:24 UTC**, `gen1/rc` HEAD `d9dcf45`, product `15727ec` (+ five committed F1 fixture files). Source-only; no `.cache`/source/test writes, no journal opens, no execution. Inputs reused, not resurveyed: [R2 build](N0-enrollment-r2-build-successor.md), [R2 physical PASS](N0-enrollment-r2-physical-successor.md) (`.cache/n0-enrollment-r2.py` SHA256 `31254a40e6e56c5ead41a577e67cc82175fbcdcf073d5fd425b20c740424ca6a`), the W0 mapping in [RC_PLAN_REVIEW](RC_PLAN_REVIEW.md), the D0 catalog row, and my cx-be3d4fdb/cx-35d2ee76/cx-0d4d4a19 findings. Labels: **FACT** (source at `15727ec`), **PHYSICAL** (R2 receipt), **DESIGN** (proposed), **POLICY**.

## 1. What exists today (FACT) and why it is not yet reusable

| Concern | Where it lives now | Reusable as-is? |
| --- | --- | --- |
| Run creation + bundle download through the real Manager handlers | `tests/live/test_gen1_native_selected_fresh.py::selected_manager:82-120` (aiohttp `TestClient` over `manager.handle_create_gen1` / `handle_launcher`, `server/manager.py:755,707-740`) | yes; imported by R2 (`n0-enrollment-r2.py:284,292`) |
| Actual product CLI launch with private config/SaveRAM and the process lease | `tools/launch_bizhawk.py:38-45` → `server/bizhawk_launch.py::prepare/launch` | yes; R2 spawns it unchanged (`:360-365`) |
| Owned TCP lifecycle: real `Gen1Runtime` + `SLinkServer.handle_client` on an owned listener, registry port patch, handler tracking, bounded drain before `runtime.close()` | R2 `main():292-320`, `drain_owned_handlers:121-143` (fixes the first run's `close runtime connections before closing their journal`) | only inside R2 |
| Checked evidence APIs | `runtime.journal.snapshot()/event_snapshot()/pending_ids()` (`server/protocol_journal.py:303,326,516`), `runtime.state()` audit (`server/gen1_runtime.py:279-343`), `event_reference.resolve` (`server/event_reference.py:28-35`), `gen1_initial_save_runtime.prepared` (`:38-42`) | yes |
| Idle-enrollment readiness and the six-field audit (native released/clean, initial, bootstrap, save receipt, empty queues, `service_current`, file bytes == prepared image, process identity) | R2 `enrollment_ready:161-168`, `observation_sequence:170-176`, `audit_enrollment:190-252`, `private_receipt:254-278` | only inside R2; fused with Y/Y and `.cache` paths (`:25-26,292,339`) |
| Process identity/cleanup census | R2 `stamp/matching/observe/cleanup_*:36-120` | only inside R2 |
| Browser-download boundary | `?bundle=1` zip bytes from `manager.handle_launcher` (`server/manager.py:738-742`); R2 checks members/hashes (`:325-346`) via HTTP client, not a browser | the real-browser claim stays with E10 |
| Receipt | `.cache/n0-enrollment-r2-summary.json` (audited document, event stream, file receipts, process identities, cleanup, source/config hashes) | format is good; location is not registrable |

**The concrete missing behavior (FACT):** a manifest proof cites a `source` path with its SHA256 under `proof_hash_policy`, and only `protected_globs` paths are pinned by the release runner (`tests/gen1_release_requirements.json`: `tests/**/*.py`, `tools/**/*.py`, `server/**/*.py`, …). `.cache/*.py` is outside every protected glob, so **no scenario receipt produced by the current controller can be registered against a pinned source**, however good the run. The reusable interface must therefore be a tracked test module; nothing else about R2 needs to change to become that module.

## 2. Smallest reusable interface (DESIGN, one module + one scenario)

`tests/live/gen1_selected_scenario.py` — a lift of R2 with three seams and no new behavior:

- `SelectedRun(root, variants, *, emulator, base_config, limit)`: `start()` = `selected_manager` + `open_runtime` + owned listener/handler tracking + registry port + bundle download/verification + CLI launch + identity stamps (R2 `:280-400`); `wait(ready, *, poll=0.25)` polls `runtime.journal.snapshot().state["components"]` and `pending_ids` (cheap, never the audited `state()` in the loop — cx-35d2ee76) and writes `progress.json`; `audit(extra)` = R2 `audit_enrollment` + `private_receipt` on one audited `runtime.state()`; `finish()` = R2 drain/cleanup/HOLD classification and summary write.
- `Scenario` = `{name, variants, ready(components, pending) -> bool, audit(runtime, document, rows) -> dict, claims: tuple[str, ...]}`. A scenario adds only what it can prove; the run object owns launch, TCP, cleanup and the summary.
- Receipt: `.cache/<scenario>-<run_id>/summary.json` with `source_files` hashes of the module and its imports (R2 `:470-476` already does this for seven files) and the scenario's `claims`; that is the object a later registration cites, with the module as `source`.
- **First scenario** `tests/live/test_gen1_selected_idle.py::idle_enrollment`: `ready` = R2 `enrollment_ready` (zero observations valid, per `lua/gen1_observation_loop.lua:56-60,103-104`), `audit` = R2's six fields plus `observation_sequence` when any exist, `variants=("yellow","yellow")`, human New Game only. Its physical result is expected to equal the R2 receipt field-for-field.

Deliberately absent: any new status API (the summary JSON is the report), route automation, recovery/resume, native trade, FPS, multi-title matrices, browser automation, and any edit to `test_gen1_native_selected_fresh.py`, `test_gen1_free_service.py`, `server/**` or `tools/**`.

## 3. Proposed portable nine-part implementation claim (for the coordinator to record; no self-grant)

1. **Requirement and behavior:** supports `manager.yellow.yellow.same-hash` *partially* (independent SaveRAM/config/session directories for identical ROM hashes and distinct process ownership are audited; reset/reload and the cross-write sentinel are **not** and remain D26/D27) and provides the interface every `gameplay.yellow.*` row will cite; closes no row by itself. **POLICY:** the coordinator decides whether a partial registration is recorded or the row stays empty until D27.
2. **Current source:** the tracked helpers and APIs in §1 at `15727ec`; the untracked controller `31254a40…`; PHYSICAL receipt R2 (`summary` SHA256 `45d452c2…931d8d08`).
3. **Missing behavior:** no tracked, protected-glob module produces a registrable scenario receipt; readiness/audit/launch/cleanup are fused in a Y/Y-only `.cache` script.
4. **Hypothesis:** lifting R2 into the two files of §2 without behavior change reproduces the R2 receipt on a fresh Y/Y run, and a second scenario needs only a `ready`/`audit` pair.
5. **Falsifiers:** *modeled* (no emulator): the module's `enrollment_ready`/`observation_sequence`/file audit refuse pending commands, an unacknowledged save, a non-contiguous or non-ACKed observation stream, a file whose bytes differ from `prepared(...)["after"]["cart_hex"]`, and a wrong `--rom` (`bizhawk_launch.py:77-78`) — the `.cache/n0-enrollment-idle-check.py` cases re-expressed against the tracked module; *positive physical:* one fresh Y/Y human New Game run whose six audited fields, file hashes-vs-image and cleanup census match R2; *refusal physical:* the already pinned duplicate/wrong-input CLI refusals rerun through the module's launch path.
6. **Exclusive files:** new `tests/live/gen1_selected_scenario.py`, new `tests/live/test_gen1_selected_idle.py`; owner Sol; no other path.
7. **Prerequisites:** N0 R2 PROVED (done); owner go-ahead for D0 (guide W1); independent Standards/Spec review of the lift; one sole live-lane grant for the physical rerun; `.cache/n0-enrollment-r2*` preserved untouched.
8. **Evidence levels and exits:** module = MODEL (modeled refusals green, `lua-parse`/`unit` unaffected); first scenario = PHYSICAL on the rerun with summary SHA256 recorded; any HOLD keeps artifacts and names the failed field. If the hypothesis fails (receipt differs from R2), the difference is reported and the module is not registered.
9. **READY decision:** the coordinator's, after verifying §1 citations; this report grants nothing.

## Unknown / unverified

Whether `tests/live` collection under the frozen `live-gates` check would import the new module (it is not in that check's argv; adding it is a later manifest decision, out of scope). Whether the R2 field names are stable enough to freeze as the interface before a second scenario exists — settled only by writing that second scenario.
