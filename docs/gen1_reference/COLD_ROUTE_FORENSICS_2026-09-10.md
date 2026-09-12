# Cold-route grant-response deadline: forensics (2026-09-10)

Read-only reconstruction of the failed input-only Yellow/Yellow cold route
`.cache/cold-native-launcher-03kuvxcx` (junit
`.cache/cold-native-yellow-south-aisle-live.xml`, started 00:35:10, 504 s) for the
Codex root engineer. Artifacts used: `runtime.sqlite3` (2,232 events, 3,095
records, 828 KB snapshot), `client-data/.../{a,b}/{journal,frame-progress}.json`,
`error-{a,b}.json`, `route-{a,b}.json`, plus the instrumented rerun
`.cache/cold-native-launcher-rgw22rpm` (`server-timing.json`, `timing-{a,b}.json`).
No server log exists for the failed run; `server-timing.json` was added afterwards.

## What ended the run

Player b raised `unanswered ordinary grant requires reconciliation: response
deadline expired` (`lua/gen1_client_entry.lua:266`, thrown at
`lua/gen1_frame_client.lua:309`) at frame 13942, map 40, `wIsInBattle=2`. The
server journal shows the grant **was answered**: revision 2229 is b's
`frame_grant` seq 371 with result `frame_window{frames:60, ttl_ms:1000}` and a
server-side `pending{before:13942, limit:14002}` ledger entry. The reply never
reached b's runtime within its 0.75 s response deadline. Player a's
`frame-progress.json` records its own `response deadline expired` revocation at
a-clock 492.29 for its `frame_complete` seq 371 (14300 to 14312), which the
server never journaled (a's outbox still holds it). Both clients therefore saw
the server go silent for more than 0.75 s at the same moment; the next
journaled revisions (2230-2232) are a's `runtime_suspended`/`hello` after the
harness abort, so the server recovered rather than crashed. Player a's error is
only the paired abort (gate line 61) triggered by the harness's `abort.json`.

## Timeline (server revisions; client clocks are per-launcher stopwatches)

| When | Frame | Rev | Event |
| --- | --- | --- | --- |
| 00:35:10 | - | 1-4 | harness start; a/b HELLO |
| +3 s | 3443 / 3512 | 15 / 18 | frame enrollment; first grant requests at 2.77 s / 2.94 s |
| ... | 10430-10658 | 1320-1362 | starter begin/end engine signals; slowest cycles of the run (7, 8, 13 steps) |
| ... | 10621-10721 | 1364-1376 | inventory observations, starter settlement, link `14bcd7f4...`; paired barrier reason "committed semantic history changed" |
| ... | 11282 / 11346 | - | route phase `rival_battle` (a / b) |
| ... | 13791 | 2186 | b `battle_faint` (Pikachu, `battle_flag 2`) in seq 363, 21 steps; no death (balls not obtained) |
| ... | 13792-13922 | 2187-2223 | seven ordinary b cycles, 20-22 steps each |
| b ~491.0 | 13922 to 13942 | 2228 | b `frame_complete` seq 370 (20 steps) ACK |
| b 491.72 | 13942 | 2229 | b grant seq 371 sent in a control turn; server journals the 60-frame window; reply not received |
| a 490.50 | 14300 | 2226 | a grant seq 371 received; 12 steps to 14312; range closed ~491.5; `frame_complete` queued |
| a 492.29 | 14312 | - | a `response deadline expired` (return never processed) |
| b ~492.5 | 13942 | - | b deadline expiry, revoke, fatal error, `error-b.json` |
| <= 0.1 s | - | - | harness `raise AssertionError(error-b)`; `finally` writes `abort.json` |
| 00:43:35 | 14312 | 2230-2232 | a asserts "paired cold native route aborted"; suspend/hello/suspend; junit written |

## Deadline semantics

- Client request clock: `lua/durable_runtime.lua:246-248` sets
  `deadline = send_time + response_timeout`, with `response_timeout =
  interval(options.response_timeout, 0.75, 1)` (`:85`, default 0.75 s, hard max
  1 s). It applies to every wire request: hello, control, `frame_complete`,
  `sync`. The grant request rides inside the control request
  (`durable_runtime.lua:359-366`; server `gen1_runtime.py:372-397`
  `_control_checked` and `issue_for_control`), so a grant has the control's 0.75 s.
- Expiry: `durable_runtime.lua:318-322` `service()` checks
  `time>=state.request.deadline` **before** `transport.pump()`/`receive()`
  (`:323-336`); it revokes non-fatally, which calls
  `gen1_frame_client.lua:232-235 revoke()` and sets `close_requested`. On the
  next step, an active range with no grant is fatal (`:309`). A range that
  already has a grant merely closes and queues its return (a's case, recoverable).
- Nothing resets the clock; each request is single in-flight (`:261`).
- Window TTL is separate: `gen1_frame_client.lua:213-215,229` starts the 1000 ms
  TTL at challenge creation (before the wire send); stepping stops at
  TTL-50 ms (`:302,318`); `execution_window.lua:109-110` refuses a grant that
  arrives after the TTL. Steps per cycle are therefore a proxy for grant RTT.
- Server side: no response deadline. `gen1_frame_journal.py:355-375` requires
  both control heartbeats within `TIMEOUT=2.0` and replays an identical
  request idempotently ("never restarts a client permit's deadline"); a new
  grant while `pending` exists is refused (`frame_progress.py:125`). Requests
  run synchronously on the asyncio loop under one lock
  (`server/durable_runtime.py:356-363`), including `_publish` presentation.
- Rival-battle end does not starve anything: the client returns a range every
  1 s or less regardless of observations; b's faint was seven cycles earlier
  and the following cycles carried no inventory or signals. The timing is
  coincidental.

## Measurements from the journal

Steps per cycle (grant RTT proxy, `0.95 - steps/59.73`): a 33.1 to 25.1, b
32.8 to 22.8 between the first and last deciles; the step change is at seq
~223, immediately after starter settlement (revs 1364-1376), when per-request
audits began decoding non-empty inventories. Last b cycle: 20 steps, about
0.6 s RTT, leaving about 0.13 s under the 0.75 s deadline. The instrumented
rerun (post-cache build) measured server `process` control mean 0.133 s / max
0.255 s, `frame_complete` mean 0.130 s, `sync` 0.051 s, utilization 71.5 %
overall but 82-90 % per minute after settlement; client-observed control max
0.41 s; client loop stalls at most 0.16 s after startup. The failed run
predates the JSON-copy and inventory caches (`COLD_ROUTE_RESPONSE_TIMING.md`:
1.3-1.5x slower), which puts its post-settlement server load at or above 100 %.

## Hypotheses, ranked

1. **Single-threaded server saturation plus a hard, fatal 0.75 s client
   deadline.** Evidence: RTT trend, rerun utilization, both clients timing
   out together, server recovering afterwards. Confirm: timestamp each frame
   at decode in `handle_client` before `async with self._lock` and log queue
   wait, `process` and `_publish` per request on the failed-run build; expect
   a gap of 0.75 s or more at rev 2229. Smallest fix: on a control/grant
   deadline, re-send the identical grant request (the server replays
   `old.result`) or return the pending range with `steps=0` instead of
   `error()` at `gen1_frame_client.lua:309`; keep deadlines unchanged.
2. **Unmeasured loop-blocking work outside `process`**: `_publish(on_change)`
   inside the lock and the harness's 10 Hz synchronous
   `runtime.journal.snapshot().state` decode plus route-file reads on the same
   loop (`tests/live/test_gen1_cold_native_launcher.py:113-144`; precedent
   `CURRENT_2026-09-08.md:355`). Confirm: time both. Fix: move the poll to
   `asyncio.to_thread` at 1 Hz; time `_publish`.
3. **SQLite `synchronous=FULL` plus WAL checkpoint under a Google-Drive-synced
   path** (`server/protocol_journal.py:144-146`; every event rewrites the
   828 KB snapshot row). Confirm: time `journal.commit` and checkpoints; rerun
   with the run directory on a non-synced local path. Fix: local temp dir for
   live gates; passive checkpoints off the request path.
4. **Client deadline check ordering** (`durable_runtime.lua:322` before
   `pump()`): any client stall of 0.75 s or more expires a reply already in
   the socket buffer. Not indicated here (a also stalled), but a latent false
   positive. Confirm: log `transport.queue_status()` at revoke. Fix: pump and
   drain before checking the deadline.

## Concerns noted in passing

- `lua/gen1_frame_client.lua:309` - fatal on unanswered grant although the
  server is idempotent (`gen1_frame_journal.py:373-375`); no client replay path.
- `lua/durable_runtime.lua:322` - deadline evaluated before receive.
- `server/durable_runtime.py:356-363` - sync `process` plus `_publish` on the
  event loop under one lock; `timed_process` measures neither queueing nor
  `_publish`.
- `tests/live/test_gen1_cold_native_launcher.py:163` - `finally` overwrites
  `abort.json`, so the rerun's real end reason (frames 18638/18651,
  `pallet_north`) is lost; its junit only shows the paired abort.
- `lua/gen1_frame_client.lua:238` - `authorize()` refuses stepping when the
  last control is 1 s or older; with a 0.5 s heartbeat and ~0.4 s RTT this is
  a second latent stall source.
- `lua/tests/test_gen1_cold_native_launcher_gate.lua:62-70` - file reads and
  JSON decodes on every `emu.yield` in a Drive-synced directory.
- `RC_STATUS_AND_ESTIMATE.md` says "end of the rival battle"; b was still in
  battle (`wIsInBattle=2`) after its starter fainted, and the failure is not
  tied to the battle sequence.
- `route-*.json` `runtime.control.reason` shows the paired barrier's last
  invalidation text (`server/paired_recovery.py:152`), retained since the
  starter link; benign here, misleading in status dumps.
