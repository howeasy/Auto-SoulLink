# Restricted runtime handoff, revision 1

This is an integration boundary for UI guard rails, equivalent extraction and
board work. It is not RBY release approval. The production bindings retain their
current transport and rule behavior; shared durable primitives are not silently
selected. The UI owner must inspect the integrated commit and evidence before
opening Phase0.

## Stable read-only interfaces

`SLinkServer.read_rule_state()` returns a detached `slink-runtime-boundary-v1`
envelope with `source: live_memory`, the current rule `document`, and
`committed_revision: null`. It never dispatches, saves, admits, drains queues or
claims that an in-memory transition reached durable storage.

`SLinkServer.read_runtime_facts(now=None)` returns these stable inputs:

| Field | Meaning |
| --- | --- |
| `players[pid].bound_save_identity` | Persisted slot identity, separate from a traded Pokemon's OT |
| `players[pid].admission` | The current backend admission state/reason |
| `players[pid].expected_cartridge` | The backend's currently adopted per-player contract |
| `players[pid].declared_cartridge` | Legacy client declarations; not a verified content profile |
| `players[pid].verified_cartridge` | Active, admitted RBY profile, including exact final hash/codec/patch capabilities; null without that evidence |
| `players[pid].session` | Active admitted RBY epoch/session, otherwise null |
| `players[pid].adapter` | Per-player configured adapter facts; null for an unadmitted RBY slot |
| `players[pid].feature_gates` | Existing backend configuration/cartridge gates; not permission for a particular physical write |
| `players[pid].feature_readiness` | Null until a binding supplies authoritative per-feature readiness |
| `players[pid].observation` | Connection declaration, last received event/time, freshly computed age and its clock basis |
| `requested_rules` | Unmodified requested settings from rule state |
| `persistence` | Explicit legacy-file mode/error; no committed revision is asserted |
| `operations` | Explicit volatile delivery, actual legacy queue counts and enforced HTTP availability |
| `recovery`, `liveness` | Null while these controllers are unbound; never inferred from queues, connection or HTTP responsiveness |
| `randomization` | Actual publisher availability/refusal; catalog and publisher evidence remain null |
| `provenance` | Adopted contract and its schema; complete randomizer hash-chain evidence remains null |

All returned containers are detached. Reads do not refresh the contract, renew
leases, reconcile parties, execute queued commands or alter requested options.
The current observation age uses the server's wall-clock receipt timestamp. It
is explicitly not the future paired monotonic liveness authority. The optional
`now` argument permits deterministic tests, not permission calculations.

Feature gates remain separate: panel uses the backend panel gate, Explode uses
its own adapter/rule gate, and Rival Swap uses its own trainer/rule gate. The
absence of a gate/readiness verdict stays null. RBY native trade is false in this
baseline; importing the tested engine does not enable its capability.

`RunManager.read_saved_run(run_id)` and
`server.runtime_boundary.read_saved_run(data_dir)` read a stopped legacy
`links.json` without starting or restoring a server. They return the actual
validated document, not a reconstruction from party absence. Missing, malformed,
duplicate-key, over-limit or incomplete files return `available: false` with a
reason. No repair or empty-state fallback occurs. A SQLite state file causes an
explicit unavailable result rather than fallback to potentially stale JSON;
the future journal owner must supply its reviewed stopped-state reader.

The read interfaces do not restore anything. Legacy Gen3 restore/lifecycle
handlers retain their existing behavior and checks. RBY restore/reset mutation
controls are blocked as described below. UI code must call operation handlers
only for user actions, never from render/hydration/polling paths.

## Enforced restrictions and deferred work

RBY HTTP reset, rollback, manual link/injection, debug mutations and attempts
editing return409 with `rby_operation_interface_unavailable` before request
processing or mutation. This applies to a clean RBY contract before HELLO as well
as an active vanilla RBY run. Existing Gen3 and AP handlers retain their behavior.
Automatic, already-implemented RBY client/rule processing is unchanged; this
baseline does not certify its full release scope or durable recovery.

Manager RBY randomization publication returns409 with
`rby_provenance_publisher_unavailable`. Requested settings and existing records
remain intact; no Java invocation, new ROM output or contract publication occurs.
Legacy scanner/subprocess component tests remain useful but cannot authorize
publication. Clean per-player cartridge binding remains available and immutable.

UPR's complete executable catalog, semantic scan, authoritative provenance and
final-output admission remain a separate Phase8 gate. Native receptionist
selection, paired trade coordination, safe host control, verified two-player
recovery and the full RBY release matrix also remain deferred. Unpatched RBY
profiles do not advertise native panel, generic SFX or trade support. Yellow's
eventual companion remains trade-only, and Yellow/Yellow remains mandatory.

The isolated native trade component has real cartridge tests for removal/append,
original animation/music, evolution, save/return and reset behavior. It is not
connected to a production command or receptionist and must not be presented as
an available player feature.

## Ownership and forward integration

UI Phase3 owns the normalized additive `/api/status` projection and all renderer
extraction. This handoff creates no competing endpoint or renderer. Preserve
existing status keys/types and legacy overlay URLs. The UI's
`docs/ui_projection_contract.md` remains the consumer agreement.

Runtime owners own `server/runtime_boundary.py`, protocol/journal/recovery
modules, cartridge admission, core rules, native patch/build and Lua clients.
Future integration must preserve these accessor names, established field types,
null-as-unavailable semantics and the requested/effective distinction. New
authoritative facts may populate previously null fields through a reviewed
binding change. Breaking changes require a new boundary revision.

After UI extraction starts, runtime work must stay out of UI-owned templates,
status/overlay rendering and normalized projection code. Necessary call-site
changes are coordinated with UI. Within `server/server.py`, TCP/admission/runtime
dispatch remain runtime-owned; presentation builders and template/overlay
contexts are UI-owned. RBY native work must not hold equivalent board extraction
behind unfinished gameplay details once this restricted boundary is accepted.

Shared recovery inputs are frozen separately in `docs/shared-recovery-contract.md`:
`RecoveryBarrier.status()` and `ControlService.status()` are detached presentation
facts, not fresh effect authority. They remain unbound here; their availability
does not assert host hold, rewind/reset interlock or native recovery proof.
