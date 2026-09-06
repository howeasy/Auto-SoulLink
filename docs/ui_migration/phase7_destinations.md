# Phase 7 — shared destinations and manager OBS ownership

Run, Broadcast, and Tools now share the application rail and Debug drawer.
Broadcast contains overlay previews, manager OBS automation, and the explicitly
selected run's Twitch controls. Tools combines cartridge-specific companion
patching with the verified randomizer's current availability. The latter remains
closed until Gen 1 publishes its complete verified interface.

`/obs`, `/twitch`, `/stream`, `/stream/`, `/patcher`, `/debug`, and `/memorial`
redirect to their new destinations while retaining query controls and the
appropriate fragment. The memorial macro smoke harness remains directly usable
at `/memorial?_smoke=1`. Overlay pages and fragments keep their existing URLs.
Selected/current states and label associations are explicit. Component styles
are scoped, including readable Twitch setup/status text across light and dark
themes. Cartridge copy no longer presents Radical Red features as Red/Blue
guarantees or claims that an unavailable build is release-ready.

Application pages use one serial polling coordinator. It waits for registered
reads before scheduling the next cycle and resumes after browser back-cache
restoration. The Run board retains its existing single HTMX coordinator; each
overlay preview is a separate source document with its own coordinator. Debug
uses the page's status and frozen operation decisions, without adding a timer
or SSE connection. Calc keeps its selected run URL and real SSE stream.

## OBS configuration and execution

The manager persists a versioned `obs_manager.json` separately from run state.
Each rule names a source run, player filter, target, scene, and optional area
filter. Rule order selects one winner per normalized host/port endpoint in an
event batch. Accepted batches enter FIFO endpoint queues; pending scenes are
not coalesced. Manual scene tests use those same queues. Duplicate batch IDs do
not replay an earlier scene during a manager session.

Legacy rules are imported unassigned and disabled; their original file is kept.
No run is guessed from a folder, current selection, or stream pin. An empty
startup creates no settings file. Invalid storage and stale configuration
revisions produce visible errors rather than replacing the original document.
Connection passwords are omitted from public responses and remain unchanged
when omitted from an update.

Managed runs start without loading or executing legacy global rules. They
forward existing event batches to the manager, while retaining actual OBS
WebSocket connections and execution. Private `/_internal/obs/{action}` routes
require a managed run, a local operator request, and the correct target run ID;
they are excluded from the public run proxy. A run checks configuration revision
and rejects a reused revision with different settings. Same-decision retries do
not repeat scene execution during that run process's lifetime.

The manager checks that every running server can accept its configuration before
issuing scenes. Older managed processes require a restart with this version;
configuration/application failures stay visible. Newer configuration supersedes
queued old decisions with explicit failed outcomes. Unconfirmed scene results
block further changes on that endpoint until the operator checks OBS and resumes
it. These acknowledgements are OBS presentation state, not Gen 1 durable operation
receipts. Scene history, duplicate suppression, and endpoint holds are currently
process-local; this does not claim recovery of accepted scenes across a manager
restart.

## Evidence

Gen 3 was tested first, followed by the complete unit/integration suite:
**3875 passed, 3 skipped**. The same three local prerequisite skips remain:
optional Red companion component and two Windows file-symlink privilege cases.
Portable CI selects **3570 passing cases** with **308 named deferrals**, no
selected skips/xfails, and no release approval. Its inventory adds 24 reviewed
portable nodes without changing existing resource classifications.

Required Ruff passes; 216 Lua files parse; canonical input verification passes
103 checks. The actual Calc bundle builds and eight Node checks pass. A new
loopback integration test uses real manager/run HTTP and real WebSocket client
connections against an isolated MessagePack OBS protocol fixture. It confirms
cross-run FIFO scene ordering, shared-endpoint serialization, duplicate handling,
and visible negative acknowledgements. No OBS installation or Twitch account was
controlled by these tests.

That test exposed an inconsistent local installation: `simpleobsws 1.4.3` was
paired with `websockets 13.1`, despite requiring 14 or newer. Project requirements
now state the compatible API floor explicitly. Testing passed in a worktree-only
virtual environment with both WebSocket 14.2 and 17.0.1; other agents' environments
were untouched. The relevant API rename is documented in the
[WebSocket upgrade guide](https://websockets.readthedocs.io/en/stable/howto/upgrade.html).
The fixture follows the official
[OBS WebSocket protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md).

Browser artifacts in `tests/fixtures/ui/review/phase7/` cover Gen 3 and Gen 1
OBS pages at 700/1100/1600 px in default, light, and Funtastic Grape, plus Twitch,
Tools, and gallery examples. The matrix reports no page overflow. The existing
Phase 6 matrix retains board-composition evidence. Keyboard review confirms
run-specific navigation, form labels/focus, readable unassigned-rule reasons,
and the shared Gen 1 Debug focus trap/restoration with 19 restricted controls.
Browser actions also confirm a rule can target Gen 1 while the selected page is
Gen 3, and a scene test reports both applied and rejected results from the local
protocol fixture. Twitch setup links to its official
[authentication guide](https://dev.twitch.tv/docs/authentication/).

Saved reusable broadcast sources, the complete common preset system, the
verified publisher workflow, and emulator E2E evidence remain later work. Gen 1
has explicitly confirmed that its durable coordinator and verified UPR publisher
are not yet a complete adoptable handoff. Their gates remain closed.
