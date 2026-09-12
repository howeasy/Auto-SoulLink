# Gen 1 durable HUD feedback and terminal state

The server half (`server/gen1_hud_feedback.py`, commit `ffd0868`) turns explicitly classified
engine presentation commands into strict `hud_notice` durable commands and verifies one exact
no-write receipt per notice. Terminal `game_over` is a separate, versioned `hud_state`
command: it is not time-limited and remains in the bound local journal after ACK.
This page covers how a command at the head of the durable inbox is drawn or expired,
receipted, replayed and rendered, without any
memory module, RAM write, write permit, physical hold, native patch or sound.

## Contract recap

| Direction | Schema | Fields |
| --- | --- | --- |
| Command body | `slink-gen1-hud-notice-v1` | `cmd=hud_notice`, `schema`, `kind` (`link_pending`, `link_formed`, `violation`, `clause_retry`), `surface` (`hud`, `prompt`), `text` (1..30 printable ASCII), `r`,`g`,`b` (0..255), `frames` (1..600), `issued_at`, `expires_at` (wall seconds, `issued <= expires <= issued+120`; the server issues a 30 s TTL) |
| Receipt | `slink-gen1-hud-receipt-v1` | `command_id`, `command_sequence`, `body_digest` (sha256 of the canonical body, `server/protocol.digest`), `disposition` (`drawn` or `expired`), `frame` (draw frame `>= 0`, or `-1` when expired) |
| Terminal body | `slink-gen1-hud-state-v1` | Exact `cmd=hud_state`, `schema`, `mode=game_over`, `text=""`. Rebuild and sound modes are refused. |
| Terminal receipt | `slink-gen1-hud-state-receipt-v1` | Same identity/digest fields; `disposition=applied`, `frame` of an actual GUI draw. |

The server does not compare its own wall clock on an expired receipt: the client owns the
expiry decision, and either disposition settles the command.

## Composition

`lua/gen1_client_entry.lua` composes one `command_service_router` for every launch:

- `lua/gen1_hud_service.lua` claims `cmd == "hud_notice" or "hud_state"`. It takes the client journal and
  the overlay only (`memory`, `host`, `holds` are never passed and never read).
- `lua/gen1_held_faint.lua` claims every physical command as before and now exposes
  `handles` for the router. It is composed only when initial observations are enrolled.

The router's `adapter`, `ready` and `operations` are what `gen1_runtime.new` receives as
`executor_adapter`, `operation_ready` and `operation_execution`, so the shared
`durable_runtime` executes a notice through the same journal, `command_executor` and
readiness path as a physical command. Exactly one service may claim a body; two claimants
are a construction fault, not a silent choice.

The launcher closure carries the pieces on every launch: `command_service_router.lua`,
`gen1_hud_service.lua`, `hud.lua` and `journal_document.lua` moved into the base `FILES` of
`server/gen1_launcher.py` (the router left `NATIVE_FILES`), so the checked launcher hashes
them and the in-process reload in `lua/slink.lua` evicts them with the rest.

`writer_pending` in the free loop is unchanged and physical-only: it asks the held faint
service alone, and a notice at the head never makes it true, so no hold is ever taken for a
notice.

## Settlement of one notice

1. **Head only.** The service acts on the head of `journal:pending_commands()` and refuses
   anything else (`ready=false`, `prepare` errors). A notice behind a physical command
   waits; a physical command behind a settled notice becomes the head on the next step.
2. **Validate.** `gen1_hud_service.validate` mirrors the server's `validate_body` exactly
   (field set, kinds, surfaces, text, channels, frames, expiry window). A malformed body is
   refused in `prepare` before any intent or draw; the executor reports a retryable NACK
   and the shared runtime applies its ordinary fail-closed policy.
3. **Intent.** `rby-hud-notice-intent-v1` (`command_id`, `body_digest`, `surface`,
   `frames`) is persisted before any effect. Replay checks the digest against the body.
4. **Classify.** Drawn in this VM: `after` with the recorded draw frame. Otherwise, if the
   client wall clock (`os.time()`) is past `expires_at`: `after`, expired. Otherwise
   `before`.
5. **Apply.** `hud.present(notice)` performs the first actual `gui.drawBox`/`gui.drawText`
   call for this notice now and only then appends its remaining frame budget to its surface queue. The
   draw frame is `emu.framecount()` at that moment. A notice that expired between
   classify and apply is not drawn and settles as expired on readback.
6. **Receipt.** The exact receipt above is persisted with `journal:complete_command`, which
   also stages the generic `command_ack` the server's `Gen1ReceiptPolicy` verifies.

Readiness needs nothing but the head: no `operation_held`, no permit, no memory. The shared
runtime still requires an admitted binding and a fresh control roundtrip, both of which hold
while lifecycle-held, so a notice settles during held recovery. That matters because service
continuity requires an idle journal: a notice at the head must be able to drain while held.

## Death, whiteout and terminal run-over

The server drains both the caller's immediate commands and the peer queue in the same
staged transaction. It retains exactly one selected physical faint command, then classifies
death/whiteout display feedback for both players. `play_sound` and legacy physical commands
are never projected as HUD writes. A whiteout emits a transient `!! WHITEOUT!` notice;
the `game_over` engine transition emits persistent `hud_state` for each recipient. If the
second player activates the Pokeball rule after the last link died, the direct run-over
update also issues each terminal state exactly once. The commit partitions physical
commands ahead of all HUD commands per recipient; the Lua router can settle HUD only
when it reaches the FIFO head.

The shared engine may select boxed survivors and queue `rebuild_start`. This HUD lane
shows only `REBUILD PENDING - PC available`, not the engine's persistent `REBUILDING`
banner, and refuses a `rebuild_done` projection. A separate, not-yet-consolidated typed
storage lane is being validated for the paired physical writes; its final saved ACK can
precede the dead-member memorial ACKs.
No `REBUILD COMPLETE` notice is claimed until both classes of obligation close.
The partner's premature legacy `>> Rebuilt N` HUD is likewise replaced with
`REBUILD PENDING` while those obligations are open.

For terminal state, the client draws `GAME OVER!` immediately, then atomically commits
`slink-client-journal-v3` with an exact `slink-gen1-hud-client-state-v1` record on the
run/player/cartridge/save-bound `state_store`. The receipt is persisted only after this
state commit. The record survives server ACK and inbox retirement. A fresh Lua VM
validates and visibly redraws it before the pending command can be receipted again;
the in-process reload and `service:close()` erase the previous overlay pixels through
`hud.clear()`. Unknown modes, fields, or a downgraded journal version fail closed.

## Crash points

| Crash after | Journal on restart | Behaviour |
| --- | --- | --- |
| intent persisted, before the draw | intent, no receipt | draws once, receipts the new frame |
| the draw, before the local receipt, same VM | intent, no receipt | no redraw; the receipt carries the original draw frame |
| the draw, before the local receipt, VM lost | intent, no receipt | redraws once if the TTL has not passed, else receipts `expired` (`frame=-1`) without a draw |
| the local receipt, before the server ACK | receipt, `command_ack` in the outbox | replays the identical receipt; no draw |
| server ACK confirmed | entry retired below the command floor | nothing to do |

For terminal game-over, a lost receipt after the local state commit reuses that exact
draw frame on retry. Reload first erases the old overlay and visibly restores from the
bound local state; it never depends on the retired inbox entry to remember game-over.

"Drawn" therefore means an actual gui draw call happened for that notice. A crash between
the draw and the receipt may show the same notice twice, bounded by the server TTL.

## Rendering

`gen1_client_entry.step` calls `hud.render()` once per new emulated frame and never while
the frame count stands still (held), so retained notices count emulated frames. The immediate
`present` draw consumes the first requested frame; a notice is therefore drawn exactly `frames`
times when uninterrupted, not `frames + 1`. Retained notices preserve the overlay's existing
FIFO order and are never silently evicted after their receipt. Legacy `hud.show`/`hud.prompt`
callers keep the same order. Text passes through the overlay's
`sanitize` and fit functions as before.

## Status

`gen1_client_entry:status().hud` and `runtime.operation_execution[1]` report
`rby-hud-service-status-v1`: `pending` (notices in the inbox without an outcome),
`retained` (entries still rendering across both surfaces), `drawn` and `expired` (receipts
produced in this VM).

## Evidence

`tests/unit/test_gen1_hud_client.py` runs the real `client_journal`, `command_executor`,
`command_service_router`, `gen1_hud_service` and `hud.lua` (recording `gui`/`emu`) and
checks the receipt with the server's `verify_receipt`: exact schema and digest, seventeen
malformed-body refusals, FIFO head ownership against a physical fixture service, a second
claimant refused by the router, expiry at the TTL boundary, the four crash points above,
same-VM reload, no memory/hold/permit access under the held recovery control shape, the
real `gen1_held_faint` beside the HUD service (`writer_pending` false on a notice head),
`gen1_client_entry` composition with per-frame rendering, and one end-to-end case where
the real `durable_runtime`/`gen1_runtime` client settles a server-committed notice while
held and the real Python runtime acknowledges the receipt.
`tests/unit/test_gen1_launcher.py` pins the closure membership.

Not covered here: live BizHawk rendering of the notice or game-over (the overlay surface persistence the
legacy clients rely on is unchanged), physical auto-rebuild, and classification of the new test nodes in
`tests/portable_ci_inventory.json`, which this branch already lacks for the server-side
HUD and continuity suites.
