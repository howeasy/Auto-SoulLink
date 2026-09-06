# Private execution-adapter verification

The actual `lua/platform_execution.lua` bytes with SHA256
`1186f83364c8e2366c94cdf06fd1665e11ba19471ecafe46a0ebd4bcec4a907c`
were exercised on the pinned BizHawk2.11.1/mGBA host. This validates the stated
private actuator and cooperative lease cases. It does not select a production
client or establish reset/load/rewind/debugger barriers or paired execution.

Every run booted a new private copy of frozen companion candidate03 and the
independently observed Viridian City battery checkpoint. ROM SHA256:
`3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301`.
The original save and configuration hashes remained unchanged. The host/core
identities were read from each running process and compared with the fixture
evidence; every successful process exited normally.

## Observations

| Run | Actual result |
|---|---|
| `execution_lifecycle_21` | Initially unpaused. Two successful claims and12 refusals across primary ownership, held state and released-but-owned state. Distinct/replayed owner tokens and two module instances ran on UI thread1. Sixteen held yields over252.6503ms kept frame1657 constant. Healthy close permitted replacement; a stale closed owner could not change its flag. Ordinary frame1658 followed close. |
| `execution_paused_23` | The same ownership/lifecycle cases passed with the private host initially paused. Sixteen held yields over261.0146ms, then16 observer yields over258.5948ms after close, kept frame1657 and user pause. No unpause or paused frame-advance request occurred. |
| `execution_external_clear_24` | A separately labeled deliberate private flag clear was detected. Failure remained latched, the lease stayed owned, and emergency hold readback succeeded. Release and close were refused. Eighteen observer yields over259.4628ms kept frame1657 stopped. Process exit bounded the failed owner; no release authority was invented. No frame escaped in this particular synchronous fault. |
| `execution_stopped_reload_29` | A separate actual LuaFile claimed/held the adapter on UI thread1. Its own exit callback ran when the observer removed that exact private file. Heartbeat tick4 then stopped;18 observer yields over251.4801ms retained frame1657 and the flag. Reloading that file with a different owner token refused the pre-existing hold. Process exit bounded the abandoned hold. |

The stopped-held-script case does not prove semaphore/GC behavior after losing an
unheld owner. Held contender construction refuses the pre-existing flag; the
unheld cases independently demonstrate the retained semaphore exclusion.
Real post-setter exceptions and unverified emergency setters remain modeled
cases, distinct from the actual external-clear experiment above.

## Preserved unsuccessful attempts

Runs25–27 reached queued helper-load submission and then their65-second private
process deadlines without a helper acknowledgement or completed result. Their
exact PIDs were terminated. The explicit CLR `object[]` argument form was
replaced by `BeginInvoke(delegate, privatePath)`; the scalar params form allowed
the helper to execute. No modal-dialog cause was independently observed.

Run28 loaded and held the helper, then failed its bounded observer wait. Its
IPC serializer accidentally expanded the second return value of a final
`string.gsub`, emitting10 fields instead of9. A focused regression now checks
the exact field count. These failed runs remain separate from run29's evidence.
Run21's successful constructor trace included a cosmetic table-address reason;
that original artifact is retained and later probes omit absent success reasons.

## Reproduction contract

Select `lua/tests/rr/platform_execution_probe.lua` through `tools.rr.native_gate`.
The explicit options are `mode`, boolean `initial_paused`, bounded `hold_ms`
(100–1000), distinct32-hex `owner_id`/`contender_id`, complete `expected_host`
pins from the reviewed [adapter contract](../platform-execution-contract.md), and
the exact `adapter_sha256`. Required source dependencies are:

- `lua/platform_execution.lua`
- `lua/platform_clock.lua`
- `lua/tests/rr/host_identity.lua`
- `lua/tests/rr/platform_execution_owner_helper.lua` for `stopped_reload`

The runner supplies the helper's contained private path. Callers cannot select
another script to remove. Actual LuaFile load/removal uses direct .NET delegates
queued through WinForms; synchronous calls from a running observer would modify
`ResumeScripts`' live enumeration. Independent helper heartbeats/exit records
establish progress before `EndInvoke`, and all waits have outer process bounds.
Neither the probe nor helper releases an abandoned or failed hold as cleanup.

Retain the normal ROM/core/fixture assertions, `descriptor_matches_bound_rom`,
`execution_initial_pause`, `execution_initial_flag`,
`execution_distinct_module_instances`, `execution_probe_frame_budget`, and the
selected completion ID: `execution_lifecycle_complete`,
`execution_external_clear_complete`, or `execution_stopped_reload_complete`.
Other structural failures still invalidate the complete result.

Original artifacts are beneath the explicitly selected private run root
`C:/Users/howar/AppData/Local/Temp/slink-rr-native-probes-01a072f9/runs/`.
`platform_execution_observations.json` records result/execution/source hashes;
no ROM, battery or savestate bytes are included in repository evidence.

```powershell
python -m pytest tests/unit/test_rr_native_gate.py tests/unit/test_platform_execution.py -q
python -m ruff check tools/rr/native_gate.py tests/unit/test_rr_native_gate.py
```
