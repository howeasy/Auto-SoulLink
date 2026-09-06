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
| `3d4a2bf` | Read-only route/terrain observation and grounded natural-battle probe preparation |
| `e03ddcb` | Inactive pinned host actuator with explicit Lua ownership and emergency hold handling |
| `1722487`, `fa4f8bd`, `fb2d948` | Explicit v2 withdrawal readback with pinned complete reconstruction, opaque host generation and final physical/admission rechecks |
| `0f01893` | Inactive heap-tail entry guard, conditional raw-transfer counterexamples and scoped mGBA source evidence |
| `1d1c913` | Exact reset/load ordering and a private late-load-failure fixture builder |
| `4ece9fc` | Actual pinned-host ownership/pause/emergency/stopped-script evidence and retained probe failures |
| `080f3bd`, `5dc8201` | Controlled BUSY-PING load probes, strict experiment artifacts and future raw-false preservation |
| `0647310` | Grounded running route and required contiguous frame capture |
| `73313c7` | RR-only peer-position sampling independent of camera movement, with recorded replay and native CPU evidence |
| `e0b611e` | Explosion identity, ownership, battle-lifetime, duplicate and action-selection guards; original mechanism retained |
| `aa29fe6`, `75a1a81` | Bounded actual DPCM decoder interpretation of the extended-ROM arena-looking word |

The shared contributions were sent as separate dependency-closed handoffs to Gen1.
They do not activate the production RR or Gen1 durable runtime by their existence.

## Verified at this checkpoint

- Unit/integration compatibility: **2,615 passed, 15 existing skips, 11 subtests**.
  Those skips do not count as RR release evidence. Full Ruff passes.
- Required explicit RR helper lanes: **209 runtime/reference tests** and **174
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
- Actual arena run20 installed and removed all **2,199 exact write-start hooks and
  11 execution hooks**, measuring exactly one frame. Setup and cleanup holds were
  verified, with no trace drops or outside-window callbacks. Its nine raw rows
  include overlapping callback duplicates. Zero allocator-entry hits in that
  single frame do not establish ownership; read/mirror/host-write coverage and
  definitive DMA/source attribution remain outside that lane.
- Gen1 reused the identity primitive unchanged: its 52 shared tests plus 13
  additional RBY ownership/evolution/pending-death contract cases passed.
- The reusable host adapter passes31 modeled component tests. Actual new-adapter
  runs21/23 refused12 competing owner/token/module claims each, proved healthy
  release/close/replacement, and serviced16 held yields at constant frame1657.
  The holds lasted252.6503ms unpaused and261.01ms paused; a further258.59ms after
  close preserved the user's pause. Run24 deliberately cleared the private host
  flag: verification failed, emergency hold succeeded, failure stayed latched,
  and release/close refused. Its independent observation retained frame1657 over
  18 yields/259.46ms. No production, Gambatte or reset/load authority follows.
  Actual stopped-script run29 retained its hold through the owner LuaFile's exit,
  then refused a reloaded owner. Frame1657 remained constant across18 observer
  yields/251.4801ms. This does not prove unheld-owner garbage-collection behavior.
- The explicitly selected v2 storage participant passes39 new tests. Independent
  review reproduced and then verified rejection of corrupt rebuilt records,
  hash-time stale physical context, and admission/mode changes at final readback.
  Legacy v1 remains selected until admitted loader/native coordinator integration.
- Route observation22 captured3402 grid cells,1024 metatile attributes, player/
  actor state and a new reviewed Viridian PNG. It establishes a route-planning
  checkpoint, not running, natural battle, ghost motion or duo acceptance.
- The inactive heap entry wrapper passed33 new CPU/static cases alongside20
  existing heap cases. Conditional GameCube receive/copy paths really can cross
  the proposed tail; they are not governed by InitHeap. Pinned standalone mGBA
  source identifies no ordinary JOYBUS producer. Scope/admission, remaining raw
  consumers and live capacity checks still prevent relocation approval.
- Controlled producer30 saved a BUSY PING state under a verified hold. Actual
  consumers31/32 restored frame1660 and its exact64-byte BUSY record under an
  existing hold, without restored native dispatch or frame callbacks. The late
  failure returnedfalse with no success notification despite restoring the core.
  Both old owners remained failed/held. These are controlled entry cases, not
  general reset/load interception. Original32 recordsfalse in its structural
  assertion; the omitted duplicate raw field is fixed only in future probes.
- Running33 completed six tiles west with48 consecutive native running frames and
  47 ghost-running frames. All61 contiguous PNGs were visually inspected and their
  hashes checked; the lossless video was verified against every decoded source
  frame. No obvious sprite corruption was seen in this short clip. Tracked ghost
  OE2/sprite3 disappeared, tiles32..47 freed, and palette3 became unreferenced.
  Ordinary NPC/reflection resources changed with camera movement; full resource,
  repeated, paired and battle/bike/surf acceptance remain open. Party bytes were
  unchanged. This probe did not select the later corrected production sender.
- The corrected peer-position sender reproduces proper ground movement with fixed
  or independently panning camera inputs, preserves all65 recorded normal-route
  positions, and has33 actual-RR movement/camera CPU cases. Physical corrected-
  client fixed-camera/panning scenes remain untested; a viewport clamp was not
  demonstrated by the ordinary running route.
- Explosion guards close31 focused full-client cases plus an exact-ROM selection
  reference. Wrong-slot/switch, borrowed-party, duplicate and progressed-turn
  failures were reproduced before repair. Arming/reinforcement/timed active
  settlement now require the verified action-selection context. The original
  Variant-3 write routine remains unchanged; local guards are not durable recovery.

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
The exact write-only arena measurement is `arena_exact_20`.
The actual adapter cases are `execution_lifecycle_21`, `execution_paused_23`,
and `execution_external_clear_24`; route capture is `route_observation_22`.
Stopped-script probe plumbing failures25–28 are retained separately and cannot
be counted as successful stopped-script/GC evidence. The corrected narrow case
is `execution_stopped_reload_29`; it does not relabel those failed attempts.
Additional cases are `controlled_producer_30`, `controlled_valid_31`,
`controlled_late_failure_32` and `running_component_33`. Hash-bound metadata and
the independent scoped visual review are in
`rr_reference/controlled_load_running_observations.json` and
`rr_reference/running33_visual_review.json`.
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
3. **Storage acceptance.** The explicit v2 receipt path now uses the exact oracle,
   but the admitted production loader/native coordinator does not yet select it.
   Real native withdrawal/deposit/memorial tests in both MGM modes and contention
   scenarios remain mandatory. A completed live-memory effect is not battery-save
   persistence.
4. **Trades and remaining features.** Serializable coordinated native trade/evolution,
   verified ownership, death priority, rival epoch/freshness, acquisition source
   coverage, native UI/audio contention and full toggle interactions remain.
5. **Ghost movement and scenes.** Additional running contexts and battle transitions, measured bike cadence,
   stationary fishing phases/offsets, surf-child resource ownership, sample expiry
   and stress still require implementation/validation beyond the quiet-field and
   one short running component gate. The corrected sender needs physical paired
   validation as well as its recorded normal-route replay.
6. **RR data policy.** The user selected cosmetic/battle-form grouping with regional
   lineages separate. The inactive catalog implements that review policy but refuses
   final generation for unresolved IDs1038/1214/1224. Existing runs/tables are not
   silently changed. Legacy policy migration and source legality remain explicit.
7. **UI integration and distribution.** UI published its tested Phase3 projection
   at5817e26; PR6/PR9 were independently checked green/open. That stack remains
   outside this RR branch pending dependency integration. RR must consume it;
   calculator, overlays, package closure and extracted-package startup remain.
8. **Release evidence.** Timing repetitions, both two-hour normal-speed soaks,
   paired campaigns through credits/postgame, recordings, migration/rollback and
   complete no-skip release verification remain uncompleted.

Use `rr_findings.md` and the executable inventory to track closure. Passing a helper,
CPU test or narrow component probe never closes an unrelated gameplay requirement.
