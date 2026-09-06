# Shared-profile actuator: RR compatibility evidence

RR adopted Gen1's five-file profile-only commit
`2899b53c8fad2a09f831173023487f911abd7a0e` as `e7391b0`. The shared module adds
explicit Gambatte selection while retaining the exact mGBA default and six pin
fields. The broader Gen1 runtime/harness tree was not imported.

Independent review found the ownership/hold/emergency/cleanup implementation
unchanged. It verified the complete18-case Gambatte matrix and its artifact
hashes against the separately published reproduction tree `0465438`. Both hosted
checks for that tree were successful. The original31 model cases pass both
versions; the adopted42 adapter and72 combined control cases pass locally.

Actual mGBA compatibility was then rerun on the **new exact Lua bytes**, SHA256
`14e981d42872294e555a09d603fdb74afb55cdb9aa3cea7d7eb665dbe47b1fea`.
These runs use the omitted/default profile, the same frozen03 ROM and observed
Viridian Default/MGM-on battery checkpoint, fresh private configurations, copies,
owners, outputs and processes. No old physical verdict was transferred to new
source bytes.

| Run | Observed result |
|---|---|
| `profile_mgba_unpaused_34` | Owner/token/module contenders refused;16 yields/255.293ms at frame1657. Healthy release/close/replacement succeeded and ordinary frame progress resumed. |
| `profile_mgba_paused_35` |16 held yields/257.8469ms at frame1657; after close another16 yields/260.1494ms preserved the user's pause and frame. |
| `profile_mgba_clear_36` | Deliberate flag clear triggered failure and verified emergency hold; release/close refused. Failed owner retained frame1657 through18 observer yields/258.5415ms. |
| `profile_mgba_stopreload_37` | Separate LuaFile stopped while held;18 yields/254.7059ms retained frame1657. Reloaded owner refused the abandoned hold. |

All four structural results and immutable source/input bindings were independently
validated. Every process exited normally; original SaveRAM/configuration hashes
were unchanged. A worker capacity error after launching34 affected orchestration
only:34 completed normally, and root ran35–37 sequentially using the same reviewed
runner and65-second process limits. No timed-out case was relabeled.

[The observation index](shared_profile_mgba_observations.json) records exact
result/execution/log hashes, source and fixture identities, claims, statuses and
held periods. Older mGBA evidence for source hash `1186f833…907c` remains separately preserved in
`4ece9fc` (`docs/rr_reference/PLATFORM_EXECUTION_PROBE.md`). The existing native
gate and execution probe reproduce the new cases by selecting this exact adapter
hash with the original mGBA pins and fresh run/owner identifiers.

This qualifies the shared cooperative between-frame actuator for the stated
pinned profiles. Production selection, cartridge admission, general reset/load/
rewind/debugger interception, unheld-owner GC, native recovery and complete paired
execution safety remain unavailable. The older controlled-load experiments were
not repeated by this profile-only compatibility run and retain their own source
identities. Full RR readiness and campaign/resource gates remain open.
