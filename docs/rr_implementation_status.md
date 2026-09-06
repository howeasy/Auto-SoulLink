# RR implementation checkpoint

This records completed implementation slices and their evidence limits. The full
release plan is still in progress. No RR release candidate has passed the required
inventory, and no player distribution is approved by this checkpoint.

Work is isolated in `codex/rr-foundation`. Root/UI and Gen1 worktrees were not edited.

## Committed slices

| Commit | Result |
| --- | --- |
| `5765ce4` | Shared atomic publication of all frame observations and detector baseline |
| `a6148a1` | Trusted save identity independent of party OT; rejected HELLO preserves queued work |
| `0e727db`, `a0f9354` | RR plan, findings/severity ledger, exact-ROM reference and 228-case release inventory |
| `de16474` | RR build/companion/mode/SaveBlock2 metadata admission provider and server policy |
| `a5c1f07` | Shared paired reconciliation, monotonic liveness and execution-hold policy |
| `b1049d4` | Trusted command metadata and nonterminal armed native operation handling |
| `8937ddb` | Guarded native mailbox/storage, ghost resource ownership, RR context and temporal observations |
| `dd2f0e8` | Coherent ghost current/previous collision coordinates across visible/hidden paths |
| `4a88acd` | Independent withdrawal oracle, actual native CPU comparison and captured RR payload persistence |
| `644584d` | Explicit form/region catalog review and strict inactive catalog reader |
| `e95902e` | Private native harness, host/fixture/resource probes and exact-address instrumentation |
| `f9b52b2` | Game-heap reset/ownership/reservation research and CPU checks |
| `231bf78` | Shared stable logical identities, acquisition deduplication and replay-validated migration bookkeeping |

The shared contributions were sent as separate dependency-closed handoffs to Gen1.
They do not activate the production RR or Gen1 durable runtime by their existence.

## Verified at this checkpoint

- Unit/integration compatibility: **2,476 passed, 15 existing skips, 11 subtests**.
  Those skips do not count as RR release evidence. Full Ruff passes.
- Required explicit RR helper lanes: **138 runtime/reference tests** and **106
  native CPU/build tests** passed without skips or xfails. These counts are not the
  228 release scenarios.
- The withdrawal comparison executed **2,820 unstubbed RR conversion calls**:
  705 distinct compressed records, two MGM flag states and base/candidate03 ROMs.
  All 100 resulting bytes matched the independent oracle. Source and neighbor
  canaries held; the native auxiliary HP-delta byte is documented separately.
- Actual BizHawk 2.11.1/mGBA host holds worked while initially unpaused and already
  paused. Frames stayed constant through wall-clock `emu.yield` servicing; release
  preserved user pause. This does not prove reset/load/rewind/debugger interlocks.
- A private battery copy reached the named Viridian City field checkpoint on
  candidate03 with verified own save/party, Default/MGM-on settings and actual
  core assembly/native DLL hashes. Original save/configuration hashes were unchanged.
- Actual ghost resource run18 completed **three** production spawn/avatar/clear
  cycles. Palette references and tile allocations returned to baseline. Seven
  screenshots were reviewed, with the source player's pixels preserved. This was
  a synthetic single-cartridge peer in a quiet field, not movement/battle/duo proof.
- Actual callback capability run19 demonstrated exact-address read/write/execute
  hooks and their overlap duplication. Wildcard registrations returned zero GUIDs
  and were correctly rejected before measurement.

Frozen candidate03: ROM SHA-256
`3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301`,
native build ID
`a568a586fee86a54150bd09d148f78eb7e85f6b521b58a2d56a043a5dd8d101c`.
Its generated manifest and UPS are under `patch/build/ghost-probe-03/`.
Earlier candidates01/02 and failed probe artifacts remain retained separately.

Private capture root on the validation host:
`C:/Users/howar/AppData/Local/Temp/slink-rr-native-probes-01a072f9/`.
Important captures are `fixture_host_09`, `fixture_paused_11`,
`fixture_candidate03_12`, `ghost_resource_18`, and `callback_capability_19`.
Each has its own player directory, immutable inputs, result and provenance.
The failed harness/oracle runs were retained; they were not relabeled as passes.

## Explicit remaining gates

1. **Native memory ownership.** The fixed arena overlaps retained libc metadata.
   An ordinary game-heap allocation is unsuitable because normal battle/field
   returns reset the heap. A reserved tail is a researched candidate, not an
   approved relocation; raw access, capacity, resets and receipt lifetimes remain.
2. **Production runtime integration.** Shared primitives still need actual RR
   bootstrap/scheduler selection, coherent full detector-baseline journaling,
   server staged publication, physical receipt validation and paired recovery.
   Host reset/load/rollback interlocks must precede restored native execution.
3. **Storage acceptance.** The exact oracle is not yet selected by storage receipts.
   Real native withdrawal/deposit/memorial tests in both MGM modes and contention
   scenarios remain mandatory. A completed live-memory effect is not battery-save
   persistence.
4. **Trades and remaining features.** Serializable coordinated native trade/evolution,
   verified ownership, death priority, rival epoch/freshness, acquisition source
   coverage, native UI/audio contention and full toggle interactions remain.
5. **Ghost movement and scenes.** Running/battle transitions, measured bike cadence,
   stationary fishing phases/offsets, surf-child resource ownership, sample expiry
   and stress still require implementation/validation beyond the quiet-field gate.
6. **RR data policy.** The user selected cosmetic/battle-form grouping with regional
   lineages separate. The inactive catalog implements that review policy but refuses
   final generation for unresolved IDs1038/1214/1224. Existing runs/tables are not
   silently changed. Legacy policy migration and source legality remain explicit.
7. **UI integration and distribution.** UI accepted the restricted Gen1 read-side
   handoff and owns its Phase0/Phase3 work. RR must consume its frozen projection;
   calculator, overlays, package closure and extracted-package startup remain.
8. **Release evidence.** Timing repetitions, both two-hour normal-speed soaks,
   paired campaigns through credits/postgame, recordings, migration/rollback and
   complete no-skip release verification remain uncompleted.

Use `rr_findings.md` and the executable inventory to track closure. Passing a helper,
CPU test or narrow component probe never closes an unrelated gameplay requirement.
