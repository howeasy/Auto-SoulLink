# P10 free-run live evidence: bedroom Yellow/Yellow through the real launcher

Status: LIVE PASS on 2026-09-11 (Claude peer, background agent). One new live test, one new
gate, one patch with two P10 wiring fixes found by the run. Nothing that already existed in
the sweep worktree was edited; the scratch copy (every proposal applied) carries the fixes.

- `tests/live/test_gen1_free_service.py` (new): the bootstrap launcher test shape
  (`run_bootstrap_pair`) with `create_runtime(..., free_service=True)`, two real downloaded
  launchers, cold New Game, then two free-running phases. Reads the server journal, writes
  `<result dir>/summary.json`.
- `lua/tests/test_gen1_free_service_gate.lua` (new): the ordinary launcher gate with the
  `emu.yield` hook for the held phases and an `emu.frameadvance` hook for the free phase
  (the entry never yields once the loop runs, `gen1_client_entry.lua:396-397`). Same menu
  recipe, same profile inputs (one step Right, then idle), status read every 15 frames.
- `docs/gen1_reference/proposals/P10-free-run-live.patch`: two hunks in
  `lua/gen1_client_entry.lua`, on top of `P10-free-run-server.patch` (section 5).
- Evidence: `.cache/free-service-yy-wwp2qsfl/` (summary.json, server-turns.json,
  ready-{a,b}.json, runtime.sqlite3, client-data, screenshots) and
  `.cache/junit/free_service_live.xml` (1 test, 0 failures, 26.39 s) with its log.

```bash
SLINK_LIVE=1 python -m pytest tests/live/test_gen1_free_service.py -q --junitxml=.cache/junit/free_service_live.xml
# 1 passed in 26.39s   (run from a short path, see section 6; SLINK_CREDIT_RUN names the credit run to compare)
```

## 1. The claim and the numbers

`EXECUTION_MODEL_PROPOSAL.md` phase 1 gate: bedroom Yellow/Yellow through the real launcher at
cartridge rate, receipts identical to the credit path. The credit loop was profiled with the
same gate harness (`gatelib` sets `client.speedmode(6399)`, unthrottled) at 31 FPS. The free
loop was run in two consecutive phases of 600 frames each: throttled to 100 % (the cartridge
rate, 59.7 FPS nominal) and then unthrottled, the condition the credit-loop number was taken
under. Two clocks: the emulator (`platform_clock`, per phase, from the gate) and the server
(`time.perf_counter` around every `runtime.process` turn; FPS = frames between the first and
last committed `observation` of the window / wall seconds between those commits).

| | Free loop, player a | Free loop, player b | Credit loop a | Credit loop b |
| --- | ---: | ---: | ---: | ---: |
| Frames free-running (loop start to end) | 1200 (3612 to 4812) | 1200 (3666 to 4866) | 321 | 328 |
| Wall seconds, first to last server commit | 15.588 | 15.184 | 10.339 | 10.497 |
| End-to-end FPS over both phases (server commits) | 75.06 | 75.08 | 31.05 | 31.25 |
| Throttled 100 % phase: emulator FPS (600 frames) | 53.18 (11.282 s) | 52.96 (11.330 s) | n/a | n/a |
| Throttled 100 % phase: server-commit FPS | 52.89 | 52.85 | n/a | n/a |
| Unthrottled phase: emulator FPS (600 frames) | 128.82 (4.658 s) | 131.59 (4.559 s) | 31.05 | 31.25 |
| Unthrottled phase: server-commit FPS | 127.95 | 131.03 | | |
| Observation events committed | 40 | 39 | 8 grants / 8 frame_complete | 8 / 8 |
| Heartbeat checkpoints (inventory present) | 40 | 39 | 8 (in bundles) | 8 |
| Batches without inventory, engine signals, receipts | 0, 0, 0 | 0, 0, 0 | 0 signals, 0 receipts | same |
| Sequence gaps (client sequence, server progress record) | 0 | 0 | n/a | n/a |
| Server ms per observation commit (mean) | 72.4 | 71.4 | 100.4 per frame_complete | |
| Client outbox backlog at the end of each phase | 0, 1 | 0, 1 | stop-and-wait | |
| Persist inside the loop | none per frame | none per frame | 5.9 ms per step | 5.9 ms |
| Receipt comparison against the credit run | identical (section 3) | identical | source | source |
| Screenshots | a-free-start.png, a-free-end.png | b-free-start.png, b-free-end.png | a-held-checkpoint.png, a-ordinary-refusal.png | b-... |

Credit-loop columns: `ORDINARY_FRAME_TURNOVER_PROFILE.md`, refresh 2026-09-10, source run
`.cache/gen1-bootstrap-launcher-ehtld3qv`. Both endpoints kept their admitted session for the
whole run (`runtime.gate.sessions == {a, b}` checked before the clients were stopped; the
client status at the end reports `connected`, `session_state=admitted`, `host.held=false`,
no `frame_progress`). The run reopens after the servers stop: `open_runtime` restores
`free_service=True`, every verifier (including P10 `verify_journal`) passes, and every
evidence component equals the pre-close document (only `gen1-runtime` moves, since close and
reopen commit `runtime_suspended` / `runtime_opened`).

Reading: unthrottled, the free loop runs 4.2 times the credit loop under the same harness,
and the server keeps up (backlog 0 to 1 event). Throttled, it holds 53 FPS against the 59.7
nominal: 89 %. Section 2 shows where the missing 11 % goes; it is the heartbeat, not the
protocol.

## 2. Where the time goes (loop iteration cost, from the gate)

One loop iteration is the frame advance plus the tick that observed the new frame
(`M.run`: `service:step()` then `emu.frameadvance()`). The gate timed every iteration and
bucketed the one whose tick fell on a heartbeat frame (`frame % 30 == 0`).

| Phase | Bucket | n (a / b) | mean ms (a / b) | max ms | share of phase |
| --- | --- | ---: | ---: | ---: | ---: |
| throttled 100 % | ordinary frame | 579 / 579 | 16.23 / 16.27 | 67.6 / 57.3 | 0.833 / 0.831 |
| throttled 100 % | heartbeat frame | 20 / 20 | 94.2 / 95.5 | 103.0 / 100.4 | 0.167 / 0.169 |
| unthrottled | ordinary frame | 579 / 579 | 4.30 / 4.33 | 69.8 / 57.8 | 0.535 / 0.550 |
| unthrottled | heartbeat frame | 20 / 20 | 108.2 / 102.5 | 145.1 / 151.4 | 0.464 / 0.450 |

- An ordinary iteration under throttle is exactly the cartridge period: the loop is not the
  bottleneck between heartbeats. Unthrottled it is 4.3 ms (emulation plus peek/prepare over
  the seven read-only sources, two `host.status()` reads, the pump).
- A heartbeat iteration costs 95 to 108 ms, about 5.7 frame periods, not the 28 ms capture
  P4 section 1 budgeted from the credit-loop profile. The rest is the momentary hold
  (`set_held` twice with host verification), JSON encoding of the checkpoint (`cart_hex` is
  64 KiB of hex plus the WRAM fields), the durable append (the client journal file is
  rewritten atomically with the event in its outbox) and the send. BizHawk does not catch up
  a late frame, so each heartbeat costs about 4.6 frame periods over the one it owns: 20
  heartbeats at 78 ms excess is 1.55 s, less the 0.3 s the ordinary iterations recover by
  running 0.5 ms under the period, which is the 1.24 s by which the 600-frame phase exceeds
  its nominal 10.04 s.
- Options, for the owner (P4 left the period to root): heartbeat 60 halves the loss (about
  94 % of cartridge rate); a checkpoint without `cart_hex` (the server compares `fields` and
  `save_status`; the SRAM image is only needed for the initial-save and memorial image
  commands, which run under their own hold) would cut the encode and persist most of the
  way; both together should put the loop within a frame period of 59.7. Neither was tried
  here; the loop and the server were run as proposed.
- Server side, an observation commit costs 72 ms (P10 `record`: `runtime.state()` audit
  plus one commit; max 117 ms), a control turn 54 ms, a sync 30 ms. At cartridge rate with two players that is about
  60 % of one core; at the unthrottled rate the outbox grew by one event per phase, so the
  server was the ceiling there, not the loop.

## 3. Receipts: the bedroom route never reaches the starter

The scripted inputs are the profile inputs: one step Right after the loop starts, then idle.
Neither run leaves the bedroom, so there is no starter receipt to compare (the credit run
recorded 0 acquisitions too; `ORDINARY_FRAME_TURNOVER_PROFILE.md` says the same). What was
compared instead, per player, is the last heartbeat checkpoint of the free run against the
last `frame_complete` bundle inventory of the credit run, and the `gen1-inventory-observations`
transition records:

| Compared | Result |
| --- | --- |
| `source.fields.party` (404 bytes) and `source.fields.box` (1122 bytes) | byte-identical |
| `source.fields.name` (player and rival names) | identical |
| `source.save_status` | 2 in both (the initial save completed in both models) |
| acquisition receipt kinds settled | `[]` in both |
| `transition` (added, changed, movements, party_hp_zero, removed) | identical, all empty |
| `source.fields.main` | differs, as it must: trainer id and play time |

The free run recorded 40 / 39 checkpoints where the credit run recorded 8 / 8, every one
chained to its predecessor through the batch operation and none deferred: the P10
`inventory_deferred` path never fired because the initial save (the only held write on this
route) had completed before the loop started (section 5, defect 2).

## 4. The held phase under free_service, as run

Same New Game path as the bootstrap launcher test: 6308 menu frames driven for both
players, hold at the first visible write-safe overworld frame (3612 / 3666), initial
observation, bootstrap observation, the `initial_save` command executed under that hold and
acknowledged (`command_ack`, file receipt in `gen1-initial-save`), then the loop released the
hold and free-ran from the very frame the hold was taken on (`loop_started.frame ==
held_frame`). Server turns for the whole run: 79 observation, 64 control, 30 sync, 2 hello,
2 initial_observation, 2 bootstrap_observation, 2 command_ack. No `frame_grant`,
`frame_enrollment` or `frame_complete` anywhere in the journal.

## 5. P10 defects found by the run (both fixed in the patch)

Both are in the P10 hunks of `lua/gen1_client_entry.lua`; line numbers are the P10-applied
file before this patch.

1. **The held-faint executor asserts the hold on every control turn.**
   `gen1_client_entry.lua:128-130` constructs `gen1_held_faint` with `owned=owned`, the
   hold-asserting reader (`:117-119` under free-run: `held physical context required`).
   `gen1_held_faint.operations.request` (`lua/gen1_held_faint.lua:131-133`) runs on every
   control turn (`lua/durable_runtime.lua:361`, every 0.5 s) and its first predicate is
   `safe()` (`:40-44`), whose first statement is `owned()`. `ready` (`:115-116`) reaches the
   same `safe()` through `readable` (`:45-48`) as soon as a command is in the inbox. Under
   free-run the control turn is unheld, so the first control turn after `start_loop`
   raised, the durable runtime revoked, `session.pump` failed and the entry stopped
   (result dir `free-service-yy-f6j0ojt5`, player b: `gen1_client_entry.lua:281:
   ...:118: held physical context required`). Fix: `owned=free and source_owned or owned`,
   the same choice P10 made for `read_context` (`:256`). `safe()` already answers false
   without the hold, so unheld reads defer and every write still requires the writer hold.
2. **The loop can start while an image command is pending.** `loop_ready()`
   (`:262-267`) waited for the initial inventory, the bootstrap and the binding, not for the
   `initial_save` command the bootstrap acknowledgement delivers in the same response. The
   P10 writer then serviced it under a later hold, and `gen1_held_save_image.classify`
   (`lua/gen1_held_save_image.lua:76-88`) refused: the image is prepared from the enrollment
   checkpoint (`before_digest`) and the core had moved (result dir `free-service-yy-7derxw3a`,
   player a: `gen1_client_entry.lua:303: command classify: partial memorial contains foreign
   data`). Fix: `loop_ready()` also requires an empty command inbox and an empty event outbox
   (`client_journal.lua:91-102`), which is the credit-path order (`command_ack` before
   `frame_enrollment`). General form of this finding, for items 4 and 5: an image command
   (initial_save, memorialize, acquisition_retire, storage_apply) prepared from a checkpoint
   cannot execute at a later frame; under free-run the server must prepare it from a
   checkpoint the writer takes under its own hold, or the writer must hold at the frame the
   server prepared from.

Not a defect, recorded so nobody re-diagnoses it: the first run (`free-service-yy-vggdlazx`)
failed in `Store.open` with a .NET exception from `lua/platform_storage.lua:74`. That is the
Windows 260-character path limit: the scratch copy sits 157 characters deep, and the atomic
temporary `journal.json.tmp-<32 hex>` under `client-data/<run>/<player>/` is 281. A junction
does not help the test itself (`ROOT = Path(__file__).resolve()` expands junctions back to
the long path), so the scratch copy was mirrored with robocopy to `C:\Users\howar\slink-free`
(1982 files, identical closure, the same `.cache` junctions) and the passing run came from
there. `tools.verify_canonical_sources.verify()` additionally needs `.cache/pret-build` and
the seven hashed `.cache/build-tools` binaries under the tree root (the toolchain check
resolves paths and refuses a junction), so those were junctioned and copied respectively.

## 6. What this does and does not prove

Proven live: the P4 loop plus the P10 server settle 79 observation batches through the real
launcher, the durable client and the atomic journal, in sequence, with the heartbeat
checkpoint chaining through `gen1-inventory-observations` exactly as the compound path did,
at 4.2 times the credit-loop throughput unthrottled and at 89 % of cartridge rate throttled,
with the entire shortfall attributable to the 30-frame heartbeat cost. The free launch ships
no frame client and records no frame ledger. Both clients stayed admitted and the run reopens.

Not proven here: the starter route (no receipts fired; the acquisition, engine-signal and
faint paths through `observation` batches remain unit-tested only, `P10-free-run-server.md`
section 5); anything after a reconnect (P10 section 6, the equality comparison in the
standalone stagers); writes other than the pre-loop initial save (items 4 and 5); the
heartbeat-60 or lighter-checkpoint variants of section 2.
