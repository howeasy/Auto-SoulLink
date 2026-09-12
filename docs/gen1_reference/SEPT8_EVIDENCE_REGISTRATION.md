# September 8 evidence registration cutoff

This is a reviewed collection and proof-registration update, **not an RC verdict**.
The final cutoff collected 5,904 unit/integration nodes. It added 607 previously
unclassified nodes across this bookkeeping task and 15 explicit live nodes,
with 32 new requirements named
`sept8.*`. Every new proof pins its assertion file and listed supporting sources
using the release runner's `proof_sha256` convention. No older requirement's
source pins were refreshed merely because its dependency changed.

## Registered scope

| Component | New unit/integration nodes | Evidence boundary |
| --- | ---: | --- |
| Admission context | 12 | Synthetic metadata; permits transport rebinding only, preserving all physical/context dimensions. |
| BizHawk launch factory | 13 | Private filesystem/configuration and hash checks; no emulator in these unit cases. |
| Shared frame progress | 24 | Bounded accounting with explicit typed eligibility fixtures; no production permission. |
| Bootstrap observer | 10 | Real Lua observer, modeled memory/CPU callbacks. |
| Bootstrap producer | 8 | Real Lua observer and journal; modeled host and initial ACK. |
| Bootstrap receipt | 23 | Synthetic source projections; one separately classified canonical regeneration test. |
| Bootstrap enrollment | 34 | Nine ordered title pairs, atomic receipt/restore and same-core reconnect; synthetic physical enrollment. |
| Capture delivery receipt | 62 | Exact party/box facts and Yellow Kadabra override; one canonical regeneration test. Does not settle acquisition clauses. |
| Force-faint FIFO | 1 | Older pending command prevents out-of-order ACK. |
| Frame journal | 7 | Atomic ledger/event persistence, replay and SQL corruption; eligibility remains a fixture. |
| RBY frame binding | 14 | Consumed-range source/host checks; post-return settlement remains mandatory. |
| Launcher archive endpoints | 2 | Bound API output and unchanged journal; no browser/install flow. |
| Memorial initialization | 2 | Saved/live initialization flag disagreement refuses before mutation. |
| Memorial archive growth | 1 | Ten paired deaths, compact active state, twenty archive records, corruption after cache warmup; physical receipts are fixtures. |
| New gate address guard | 3 | Static Yellow-shifted-address checks; does not execute the gates. |
| Manager preparation | 3 | Unit ordering/rules checks with mocked admission and spawn. |
| Shared operation callbacks | 6 | Actual Lua callback guards with modeled transport/host. |
| Manager real process | 1 | Staged clean ROM inspection and actual server spawn; registry/port allocation isolated. No emulator or UI. |
| Shared event audit | 43 | Read-only detached event snapshots validate canonical request/result, digests, revisions and original command IDs. Audit lookup is distinct from semantic replay or authority. |
| Retained frame provenance | 21 | Completed ranges retain their original immutable grant and checked event; deletion, rehashed substitutions and malformed return evidence refuse. Real SQLite with synthetic eligibility. |
| Observation staging | 8 | Engine/inventory evidence composes on a caller-owned detached stage without publication; existing wrappers retain one-commit and replay behavior. Does not implement combined frame settlement. |
| Shared event reference | 16 | Compact checked references resolve the exact stored request/result without writes or authority. |
| Atomic frame settlement | 6 | One SQLite transaction settles starter/source/inventory identity or faint plus partner command; validation and SQL failures roll back all proposals. Eligibility remains a test fixture. |
| Scripted grant receipts | 161 | Registers, fresh party/prepended-box delivery, title-neutral logical events and exact Game Corner payment; one canonical source/ROM census case. No original-engine grant interaction is claimed. |
| Initial-save kernel | 49 | Source-defined save image, unchanged WRAM, full-preimage refusal, partial repair and separate save permit using actual Lua writer with modeled host/file. |
| Initial-save lifecycle | 29 | Nine ordered cartridge pairs, peer enrollment ordering, exact file ACK, fixed-frame permits, reconnect and atomic rollback with synthetic physical/file evidence. |
| Compound observation provenance | 22 | Semantic source/inventory views retain their one frame event's revision, commands, closed bundle and exact result. Forged or invented semantics refuse. |
| Sparse frame observation | 26 | Held boundaries bind physical owner and consumed frames while preserving unavailable inventory as absent. No implied gameplay permission. |

The portable policy now accounts for all 5,904 nodes at the cutoff on both Linux
and Windows: **5,463 selected, 441 explicitly deferred**. The new deferrals are:

- Capture, bootstrap and scripted-grant site regeneration require
  `gen1-canonical-build-provenance`, which includes legal root ROMs, pinned source
  checkouts, builds, symbols and tool hashes. Merely having generated JSON is not
  sufficient for these three assertions.
- The Manager real-process integration requires `gen1-clean-staged-roms`.

All other newly classified unit cases use checked repository artifacts, synthetic
fixtures, installed dependencies and private temporary files. Deferral in portable
CI is not permission to skip these tests in the strict release lane.

## Explicit live lane additions

`live-gates` now includes all four files below, retaining `SLINK_LIVE=1` and the
strict runner's no-skip/no-xfail/no-deselection interpretation:

| File | Nodes | Assertion scope |
| --- | ---: | --- |
| `tests/live/test_gen1_bootstrap.py` | 6 | Normal menu/button cold boot in R/B/Y, original observer on/off memory and screenshot comparison, walkable bedroom; bounded variants use an explicit test authority token. |
| `tests/live/test_gen1_capture_delivery.py` | 3 | Original capture delivery calls and nickname UI, party/active-box facts and observer differential, including Yellow boxed Kadabra. CPU/data setup and routine stop remain test fixtures. |
| `tests/live/test_gen1_launch_factory.py` | 1 | Isolated production factory paths and saved Yellow/Yellow memorial closure with fixture enrollment/faint setup. |
| `tests/live/test_gen1_bootstrap_launcher.py` | 5 | Downloaded launcher/server bootstrap and exact initial SaveRAM completion for Y/Y, R/B and B/Y; legacy Y/Y and R/B launches must retain holds without inventing bootstrap history. |

Registering these nodes does not assert they passed. This bookkeeping task ran no
emulator gate and did not approve their screenshots. The withdrawn injected
startup probes must not be reused as normal startup evidence. Bootstrap movement
under a test token does not qualify server-authorized ordinary gameplay or the
remaining rules lifecycle. The later five-case launcher report separately proves
initial SaveRAM persistence, as described below; reload is not qualified.

## Validation and remaining bookkeeping

- `load_inventory`, `select_nodes` for both supported platforms, and
  `validate_manifest` passed against the cutoff.
- `tests/unit/test_portable_ci.py` and `tests/unit/test_gen1_release_gate.py`:
  **70 passed** after the final inventory update; report
  `.cache/registration-stable-validator.xml`. The 43 shared event audit cases
  were independently rerun here and passed in 0.65 seconds.
- The initial 5,523-node cutoff was extended after the parallel agents released
  their files. Event audit parameter IDs were shortened before registration.
  Later grant, initial-save and frame integration added another 309 reviewed
  cases. The final 5,904-node collection has **zero unclassified or missing nodes**.
- `tests/gen1_release_inventory.json` was refreshed after the task's scope was
  explicitly widened: unit **5,756**, integration **148**, live gates **267**,
  duo pairs **45**. All previously registered nodes remain present.
- Two standard `--write-inventory` attempts collected successfully but refused
  publication because the globally hashed implementation tree changed during
  parallel work. The authorized alternative used the same strict runner's
  `run_check(..., collect_only=True)` protocol and report validation, while
  verifying that every Python test file, the manifest/inventory and dynamically
  discovered Lua gate filenames stayed unchanged during the six-second cutoff.
  It did not waive global implementation drift for execution or release proof.
  The final cutoff used the standard `--write-inventory` command successfully
  after files were released, including its global source-stability checks.
- Current scoped proof pins were refreshed only where the focused report
  contained each assertion-bearing node and all listed implementation files
  predated that report: bootstrap enrollment/launcher, frame journal/provenance,
  memorial executor, hex delta and memorial initialization. The older full
  memorial-save proof remains stale because its initial-observation dependency
  changed after that focused report. Unrelated legacy requirements were untouched.
- `.cache/initial-save-launcher-live.xml` records five passing current launcher
  cases; `.cache/initial-save-lifecycle-result.json` records source hashes and six
  reviewed completion screenshots. Cold Y/Y, R/B and B/Y files are separate,
  read back equal to their verified receipt images and leave WRAM unchanged.
  No gameplay holds clear, no ordinary permission is granted and new-game reload
  remains explicitly unqualified. This bookkeeping task did not rerun those gates.
- `.cache/frame-save-integration.xml` records 34 passing atomic-frame, frame-journal
  and retained-provenance cases. These use real journal transactions with synthetic
  physical eligibility; they do not establish live ordinary frame permission.
- Earlier empty requirements and stale historic pins remain visible. None were
  silently promoted by these registrations. A final broad run, actual gate
  results, paired gameplay and the human session remain separate release work.

Final standard collection evidence is
`.cache/gen1-release/20260908T234534Z-10a8be8a/`;
its summary is `.cache/registration-stable-final.json`. Scoped refresh decisions
are recorded in `.cache/registration-feature-summary.json`. Earlier scratch reports
retain their superseded cutoffs. These are local collection artifacts, not
immutable published release evidence or a new emulator pass. The separately
running full regression has no verdict asserted by this document.
