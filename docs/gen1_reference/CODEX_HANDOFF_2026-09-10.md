# Gen 1 RC: tightened session plan and handoff for root (`codex:Gen1`)

Written 2026-09-10 by the Claude peer after the owner confirmed the decisions in section 0.
Every path is relative to the sweep worktree
`E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`; line numbers were read
today. Companion documents: `GEN3_STANDARD_COMPARISON.md` (the row-by-row evidence),
`EXECUTION_MODEL_PROPOSAL.md` (the loop), `SCOPE_CONTROL_PROPOSAL.md` (manifest, rules,
budgets), `COLD_ROUTE_FORENSICS_2026-09-10.md`, `INTERIM_LEDGER_2026-09-10.md`.

## 0. Decisions confirmed by the owner

Gen 3 Radical Red is the gameplay standard. The framework makes that standard durable; each
generation is an adapter. For every place the RC changed a rule's behaviour:

| Behaviour | Decision |
| --- | --- |
| Link timing | **Revert**: link at the catch. The stable inventory checkpoint verifies afterwards and may raise a blocker; it never gates the link. |
| Clause violation | **Revert**: force-faint the offender, memorialize, reopen the area, retry (`server/state.py:1597-1630`). No run-halting blocker. |
| Dead zone | **Revert the mechanism, keep the evidence**: the standard's `force_faint` + `memorialize` commands, closed by receipts. No separate retirement command for dead zones. |
| Failed memorialize | **Adopt** blocking with repair, for every generation. |
| Memorial box | **Revert**: `adapter.memorial_box_index()`. |
| Dashboard mutations | **Revert** as journaled operations. |
| Persistence | **Adopt** the SQLite journal for every generation; same `to_document()` shape. |
| Physical command closure | **Adopt** receipt-verified closure for every generation; each adapter supplies its safe-state predicate and readback. |
| ROM admission | **Adopt** complete-hash admission for every generation. |
| Execution loop | **Revert** to free-run. |
| Starters and the clauses | **Revert** to the standard (owner, 2026-09-11): starters are under the clauses in every generation. Gen 1 exempts Yellow/Yellow only, where both starters are Pikachu by script (`proposals/P14-starters-under-clauses.md`). |

Implied work, not decisions: fold the parallel rule modules back into `SoulLinkState`, and
implement the standard behaviours the RC lacks on that single path.

## 1. Read this, nothing else, before starting

`docs/gen1_reference/RC_CHECKLIST.md` (created in item 1 from `verify_gen1_release.py
--list`), `CLAUDE.md`, and this file. Open other documents only when an item names them.

## 2. Work items, in order

Each item: files, exact change, a code sample where it shortens the work, tests, the gate
that closes it, and a token budget across root, peer and workers. Do not start an item
before the previous one is committed.

### Item 1. Commit, checklist, archive (60M)

1. Commit the sweep worktree as it stands (63 modified, 604 untracked; `docs/gen1_reference/`
   is entirely untracked). Message: "wip(gen1): sweep worktree as of 2026-09-10; no
   qualification claimed". The snapshot in `E:/Google Drive/SLink/.cache/snapshots/gen1-sweep-2026-09-10/`
   is the only other copy.
2. `python tools/verify_gen1_release.py --list > .cache/junit/release_list.txt` and render it
   as `docs/gen1_reference/RC_CHECKLIST.md` (one row per requirement, registered or missing).
   Today: 187 registered, 201 missing.
3. Move every "earlier cutoff" section and every dated proof document that the checklist does
   not cite into `docs/gen1_reference/archive/`. One commit.

Gate: commit exists; checklist regenerates from the tool.

### Item 2. One engine: fold the parallel rules back (500M)

**Why this is mechanical, not a redesign.** The durable path already runs the shared engine
atomically: `DurableDispatcher.dispatch` restores the staged state, calls
`staged.handle_event(...)`, drains `staged.take_commands(...)` and commits state and both
outboxes in one journal transaction (`server/durable_dispatch.py:37-77`, `staged_state.py:159-167`).
Two things keep it unreachable in production: `open_runtime` installs
`validate_event=no_new_observations`, which raises for every gameplay event
(`server/gen1_run_config.py:84-87`), and `Gen1Runtime._dispatch_semantic` routes every typed
event to a parallel runtime before the fallthrough (`server/gen1_runtime.py:274-346`).

**The shape.** Each `gen1_*_runtime` module stops deciding and starts translating: a decoded
receipt becomes the semantic event the shared engine already understands, dispatched through
`staged.handle_event`; the commands the engine returns go to the outboxes and are executed by
the existing held executors with receipts. The receipt decoders, identity registry, death
records and evidence tracking stay; the decision code goes.

**Event mapping** (engine handler on the right; the message fields it reads are cited):

| Receipt / signal | Semantic event | Engine handler |
| --- | --- | --- |
| `capture` fact (delivery witnessed) | `{"event":"capture","key","area_id","species_id","level","nickname","gift":<scripted grant or fixed-species static>,"in_box":<destination=="box">}` | `_handle_capture` (`state.py:1212-1240`) |
| `wild_end` with no capture and no exclusion | `{"event":"no_catch","area_id","species_id","level"}` | `_handle_no_catch` (`:1841`) |
| engine signal `faint` (battle or poison) | `{"event":"faint","key","_level":mon.level}` | `_handle_faint` (`:1704`) → `_propagate_faint` (`:2685`) |
| post-battle checkpoint with every party HP 0 | `{"event":"whiteout","area_id"}` | `_handle_whiteout` (`:1992`) |
| checkpoint diff: key left party, present in box | `{"event":"party_to_box","key","stats"}` | `_handle_party_to_box` (`:2076`) |
| checkpoint diff: known key back in party | `{"event":"box_to_party","key"}` | `_handle_box_to_party` (`:2124`) |
| `evolution` / `npc_exchange` fact | `{"event":"key_change","old_key","new_key","new_species","new_nickname","reason"}` | `_handle_key_change` (`:2475`) |
| trainer battle begin (`wCurOpponent` > 200, stable 3 frames) | `{"event":"trainer_battle_start","trainer_id"}` | `_handle_trainer_battle_start` (`:2957`) |
| memorial executor ACK | `{"event":"memorialize_done","key"}` | `_handle_memorialize_done` (`:2822`) |
| `bag_received` signal | keep: sets `stage.rules.pokeballs_obtained[player]` directly (`gen1_faint_runtime.py:111-120`) | n/a |

**Sample: the capture translator** replacing `gen1_acquisition_runtime.py:251-266`.

```python
# server/gen1_acquisition_runtime.py  (inside the per-fact loop; `stable` becomes a verifier, not a gate)
event = {
    "event": "capture", "key": fact["key"], "area_id": area,
    "species_id": mon.species_id, "level": mon.level, "nickname": mon.nickname or "",
    "gift": fact["kind"] == "scripted_grant" or (fact["kind"] == "static_origin" and fixed_species(fact)),
    "in_box": fact["destination"] == "box",
}
immediate = stage.rules.handle_event(player, event)          # shared decision; may queue force_faint/box_mon/party_mon/memorialize
settled["rule"] = "engine"; settled["commands"] = immediate   # evidence only; no parallel outcome field
# later, when the stable checkpoint arrives:
if stable is not None and stable["blob"] != expected_blob(fact):
    raise_blocker(stage, constraint_id(player, acquisition_id), "delivered member differs from its receipt")
```

Delete after the translator lands: the `CONSTRAINT_REASON` blocker for violations
(`:258-265`), `acquisition_disposition_rules.py`, `capture_rules.py`, `party_grant_rules.py`,
`no_catch_rules.py`, `linked_death_rules.py`, `member_identity_rules.py`, their tests, and the
five acquisition tests that assert `boxed_deferred`/`exempt_grant`
(`tests/unit/test_gen1_acquisition_runtime.py:180` and `test_gen1_frame_acquisitions.py`).
Starter settlement (`gen1_starter_settlement.py:12,126`) becomes a `capture` with
`gift=true` and `area_id="intro"`, which is exactly what Gen 3 sends (`gen3_frlge_client.lua:3621-3633`).

**Sample: the faint translator** replacing `gen1_faint_runtime.py:126-160`.

```python
# delete lines 126-127 (the Explode refusal); _propagate_faint already picks force_explode
# when explode_mode is on and adapter.supports_explode_mode() (state.py:2699-2704; Gen 1 adapter returns True,
# server/adapters/gen1_rby.py:301-305).
immediate = stage.rules.handle_event(player, {"event": "faint", "key": row["key"], "_level": mon.level})
peer_cmds = [c for c in stage.rules.queued_commands[partner] if c.get("cmd") in ("force_faint", "force_explode")]
# keep the death record as the evidence tracker of that ONE command:
component["deaths"][death_id] = {..., "command": peer_cmds[-1], "phase": "pending_faint", "receipt_event": None}
```

`take_commands` then carries the peer command, the sound, and both memorializes to the
outboxes in the same transaction; the held executors and their receipts are unchanged.

**Where the events enter.** In `Gen1Runtime._dispatch_semantic`, each translator ends with a
call into the dispatcher instead of returning its own settlement; `open_runtime` replaces
`no_new_observations` with a validator that accepts the semantic events above from an admitted
session. The `frame_complete` bundle consumer (`gen1_frame_journal.returned`) keeps decoding
receipts; it just calls translators. When item 3 lands, the same translators consume the
`observation` batch instead.

**Standard changes made once, in `state.py`, for every generation.**
- `_handle_memorialize_failed` (`:2847-2872`) no longer completes the pair; it re-queues
  `memorialize` and records the failure. Adopted from the RC.
- `_handle_capture`, `_handle_no_catch`, `_propagate_faint` gain no Gen 1 branches. If an
  adapter needs something, it is an adapter method with an inert default (`adapters/base.py`
  already does this for `supports_explode_mode`, `memorial_box_index`, `rival_trainer_ids`).

Tests: `tests/unit/test_state.py` is the rule oracle and stays untouched. Add one translation
test per receipt kind asserting the emitted event and the engine's resulting commands. Delete
the parallel rule tests with their modules.

Gate: broad suite green with the deletions; `ruff check . --select E9,F6,F7,F81,F82` and the
Lua parse gate green; `verify_gen1_release.py --list` unchanged or better.

### Item 3. Free-run loop (execution model phases 1 to 3) (500M)

Replace the credit loop with the loop every other generation has. Client sketch, target under
120 lines in a new `lua/gen1_observation_loop.lua`:

```lua
-- lua/gen1_observation_loop.lua (sketch)
local M = {}
function M.run(ctx)  -- ctx: engine (gen1_engine_signals), observers (gen1_acquisition_observers), inventory(), journal, session, writer
    local seq = ctx.journal:last_observation_sequence() or 0
    while true do
        emu.frameadvance()
        local frame = emu.framecount()
        local signals = ctx.engine:peek()
        local rows = ctx.observers:prepare(ctx.state)
        local heartbeat = frame % 30 == 0
        if #signals > 0 or #rows.receipts > 0 or heartbeat then
            seq = seq + 1
            ctx.journal:append({event = "observation", frame = frame, sequence = seq,
                signals = signals, acquisitions = rows.receipts,
                inventory = heartbeat and ctx.inventory() or JSON.null}, ctx.baseline)
            ctx.engine:drain(signals); ctx.observers:drain(rows)
        end
        if ctx.journal:pending_write_command() then ctx.writer:service() end   -- takes and releases the hold (item 4)
        ctx.session:pump()   -- send outbox, receive ACKs and commands; never blocks the frame
    end
end
return M
```

Note `engine:peek()`/`drain()` and `observers:prepare()`/`drain()` assert `held()==true` today
(`lua/gen1_engine_signals.lua:73-79`, `lua/gen1_acquisition_observers.lua`). Relax that
assertion to "called between frames from the main loop" (a frame-boundary flag the loop sets),
not to "hold taken". The hooks themselves fire synchronously inside emulation and need no hold.

Server: an `observation` event handler that validates sequence contiguity per player, checks
ROM hash and `context_generation`, decodes `acquisitions` with the existing
`gen1_source_receipts.decode`, records signals with `gen1_engine_signal_runtime.record`, and
feeds the item-2 translators. It replaces `gen1_frame_journal.returned`.

Delete: `server/frame_progress.py`, `execution_window.py`, `gen1_frame_control.py`,
`gen1_frame_journal.py`, `gen1_frame_runtime.py`, `gen1_native_frame_accounting.py`,
`lua/execution_window.lua`, `frame_pacer.lua`, `gen1_frame_client.lua`,
`gen1_native_frame_client.lua`, the `frame_grant`/`frame_complete` events, the four
`shared-*` contracts named in the proposal, and their tests (about 35 files under
`tests/unit/`). No other branch references these modules (`git grep` on
`codex/gen2-production` and `codex/ui-rework`, 2026-09-10).

Gate: Yellow/Yellow bedroom through the real launcher at cartridge rate (59.7 FPS, versus 31
today, `ORDINARY_FRAME_TURNOVER_PROFILE.md`); the starter route's acquisition receipts
byte-identical to the credit-path bundle for the same inputs; net lines negative.

### Item 4. Writes on hold from the free loop, and the command executor map (300M)

`control_service` takes the hold when a write command is pending (`lua/control_service.lua`
already owns hold policy; `platform_execution` is proven from an unpaused core,
`GAMBATTE_EXECUTION_HOLD.md`). The executors are the ones that exist; what is new is the map
from the engine's command names to them:

| Engine command | Executor | Notes |
| --- | --- | --- |
| `force_faint` (overworld) | `lua/gen1_held_faint.lua` + `server/gen1_held_faint.py` | unchanged |
| `force_faint` (in battle) | item 5 | benched and active |
| `force_explode` | new, small: `M.forceExplode(slot)` (`lua/memory_gb.lua:836-853`) under a short hold while in battle and the target is `wPlayerMonNumber`; else fall through to `force_faint` exactly as `gen1_rby_client.lua:290-334` does | Gen 1 needs no patch; four move slots plus `wPlayerSelectedMove` |
| `box_mon` / `party_mon` | `gen1_held_storage` jobs as the executor (`gen1_storage_runtime.py`) | the job stays; the rule that emitted it is the engine's |
| `memorialize` | `gen1_held_memorial` | unchanged; ACK becomes `memorialize_done`; failure re-queues |
| `replace_rival_team` | new, small: `M.writeEnemyParty(blobs)` (`gen1_rby_client.lua:340-371`, `lua/games/gen1_rby.lua:449`) under a short hold at trainer-battle start | plaintext `wEnemyMons`, no patch |
| `play_sound`, `msgbox`, `hud_show`, `gui_prompt` | overlay HUD; `sfx` stays false | as today |
| `game_over` | HUD + run_over | emitted by `_check_game_over` once folded |

Gate: the ten held-faint and seven memorial launcher cases pass launched from the free loop;
a duo `explode` and a duo `rivalswap` scenario pass on Red/Blue through the production loop.

### Item 5. In-battle faint as a short hold (250M)

Everything in `BATTLE_FORCE_INTEGRATION.md` §1 to §3 applies except its §4 blockers 0 and 1,
which the free loop removes. Client side, when a `force_faint` is pending and `wIsInBattle` is
non-zero:

```lua
-- inside writer:service(), battle branch
local authority = ctx.session:request_instruction_authority(command_id)   -- server: battle_force_authority.prepare/issue
if authority then
    ctx.hold()                                            -- control_service
    local exec = require("battle_force_authority").new{owner_id = instance, held = ctx.held}
    local rows = {}
    for _ = 1, authority.frames and authority.frames.count or 1 do
        exec.arm(authority)                               -- lua/instruction_executor.lua:68 (same challenge, next frame)
        assert(owner.step_one({}))                        -- one released frame; the bus-exec hook fires inside it
        local row = exec.finish()                         -- :97
        rows[#rows+1] = row
        if row.site ~= JSON.null then break end           -- fainted or benched written, or refused
    end
    ctx.release()
    ctx.journal:append({event = "instruction_window", command_id = command_id, rows = rows}, ctx.baseline)
end
```

Server side: issue the authority from `battle_force_authority.prepare(...)` when the pending
command's death is `pending_faint` and the last checkpoint shows `battle_flag ~= 0`; verify the
returned rows with `instruction_authority.verify_window(authority, rows, verify_row=battle_force_authority.verify_evidence)`
(`server/instruction_authority.py:141-159`); on `fainted` or `benched`, record
`death["enforcement"]` and let the overworld executor's no-op ACK close the death, as §3.5 of
the integration proposal describes. Live evidence already exists for every branch
(`BATTLE_FORCE_FAINT_WINDOW.md` §10-§12, all three titles, 2026-09-10).

Gate: `tests/live/test_gen1_battle_force.py` both tests pass from the production loop; a duo
scenario in which the death is delivered while the peer is mid-battle faints the active mon in
the original engine (this exceeds the Gen 3 standard, which defers the active battler).

### Item 6. Fix the standard's regression: Gen 3 trade scene (30M)

`lua/clients/gen3_frlge_client.lua:2221-2241`. On a patched ROM the `pending` phase can only
time out into the silent swap. Restore the staging branch outside the not-patched branch:

```lua
if p.phase == "pending" then
    if not patch_present() then
        console.log("[SLink-FRLGE]   ↳ trade ABORTED: companion patch not present; no swap performed")
        pending_trade_apply = nil
    elseif memory.read_u8(0x03000F9C) == 0 and not pending_ui then   -- sScriptContext2Enabled clear, no native box up (the gate 134f007 dropped)
        relocate_trade_slot(p)
        local sseq = MB.set_enemy_party({ p.blob })
        if sseq then p.phase = "stage"; p.seq = sseq; p.start_frame = frame_count
        else fallback("stage send failed") end
    elseif frame_count - p.start_frame > 1800 then
        fallback("field never cleared")
    end
```

Confirm the exact gate with `git log -L 2221,2242:lua/clients/gen3_frlge_client.lua` before
editing; `pending_ui` is the name the pre-`134f007` code used for the native-box-in-flight
flag. Gate: `lua/tests/test_live_tradescene.lua` and the duo `trade` scenario show the
animation phase reached (`phase == "scene"` in the log), not the fallback.

### Item 7. Manifest closure on the new loop (2.0B, parallelizable after item 5)

| # | Rows | Driver | Budget |
| --- | --- | --- | ---: |
| 7a | single-player 60 (20 axes x 3 titles) | natural-play drivers: `playthrough`, `deadzone`, `dupes`, `whiteout`, evolution, storage, encounters, safari, game corner, statics, Yellow retirement, Explode, Rival Swap | 700M |
| 7b | live-duos 5, ordered-contracts 18, manager-isolation 2 | existing duo runner on the production loop; the 18 HELLO-order contracts are one parametrized test | 250M |
| 7c | trade-receptionist 55 | the nine-pair live matrix already passes; register per title; add busy-queued and recovery rows | 400M |
| 7d | patch-browser 40 | UPR categories per title, browser E2E (`npm install playwright` first: the four integration tests fail on that alone), panel and SFX gates | 300M |
| 7e | canonical 3, unit-protocol 7, live-memory 10 | umbrella registrations | 100M |
| 7f | Gen 3 binding plan, one page per `FRAMEWORK.md` row | the check that the boundaries are right | 60M |
| 7g | full gate run, staged human session, defect loop | `verify_gen1_release.py` green then `--complete-human` | 400M |

Reserve 30%: about 1.2B. Session total about 5.1B. The honest gap to "a few billion" is
7a: sixty rows with zero proof today. Three workers on 7a, 7c and 7d in parallel after item 5
converts tokens into wall-clock and review load, not scope.

### Item 8. Gen 3 onto the durable layer (next session, 400M)

Adapter work only, because the engine stays shared: journal persistence for the Gen 3 run,
receipt-verified closure using `safe_now` (`gen3_frlge_client.lua:2584-2589`) as the predicate
and `exec_box_mon`/`exec_party_mon`/`OP_MEMORIALIZE` (`:1601`, `:1670`, `:1781-1836`) as the
executors, hash admission through `Gen3Adapter.rom_content_fingerprint` (today unimplemented,
`adapters/base.py:360-372`, `server.py:1763`), and the blocking `memorialize_failed`. Read
section 4 before touching the Gen 3 client.

## 3. Easy code wins, ready to apply

1. Item 6 above.
2. Late grant reply: replace `error("unanswered ordinary grant requires reconciliation: ...")`
   at `lua/gen1_frame_client.lua:309-310` with a re-send of the identical request; the server's
   grant is idempotent (`server/gen1_frame_journal.py:373-375`). Moot once item 3 lands; worth
   doing first if any cold-route run is attempted before then.
3. The five stale acquisition tests (item 2 deletes them; until then they fail).
4. `npm install playwright` in `tests/browser/` (four integration failures, environment only).
5. `server/gen1_memorial_policy.py:20`: `GRAVE_BOX = adapter.memorial_box_index()`.
6. `server/gen1_faint_runtime.py:126-127`: delete the Explode refusal (item 2 does this).

## 4. Gen 3 context root does not have

From the Claude peer's memory of the Gen 3 Radical Red work (May to July 2026), each verified
at the time and still true in this tree unless noted:

- **`gen3_frlge_client.lua` is at Lua's 200-local limit.** New file-scope state must go into
  an existing table (the client uses `PP` for that); a new top-level `local` fails to load.
- **`patch/handlers.c` changes are source-only until the ROM is rebuilt** with
  `patch/tools/build.py`, which needs the base ROM. The shipped `dist/SLink-RR.ups` and the
  patcher md5s match the 2026-06-11 build (base `8529f3a4…`, patched `8dcffce7…`, build
  `d45485d4…`). The mailbox is single-slot with an outbox pump; same-frame opcodes clobbered
  each other before that fix.
- **The peer ghost is a real engine object-event**, shipped 2026-07-10. Talking to it is the
  trade entry point when presence is on; the Center NPC is the entry when it is off
  (`gen3_frlge_client.lua:2167-2192`). The corruption saga ended by overwriting the cloned
  sprite's callback (`struct Sprite +0x1C`) with an inert thumb `bx lr` (`0x4770`); never
  clone a sprite without doing that. Gate everything on `gMain.callback2 == CB2_Overworld`
  (`0x030030F4 == 0x080565B5`); never touch `gSprites` during battle teardown; scan free
  sprites high to low and exclude slot 0 and the player's sprite; suspend by clearing the
  backing object-event's flags only.
- **RR EWRAM and ROM facts** (RR 4.1, base md5 `8529f3a4…`): `gObjectEvents 0x02036E38`
  stride `0x24`; `gSprites 0x0202063C` stride `0x44` (x/y at +0x20/+0x22, animNum +0x2A,
  callback +0x1C); `gSpriteCoordOffsetX/Y 0x02021BC8/0x02021BCA`; `gSpriteTileAllocBitmap
  0x02017D9C`; `gPlttBufferUnfaded` OBJ `0x020373F8`, faded `0x020377F8` (write the shadow
  buffers, never palette RAM); `SB1_PTR 0x03003840` on RR versus `0x03004F58` on AP;
  `sScriptContext2Enabled 0x03000F9C`. Object-event map fields lag a warp; use the SaveBlock1
  chain.
- **START-menu row.** RR cannot take a 14th action id (description and action tables abut);
  the patch takes over id 8 with four ROM word writes; `sNumStartMenuActions 0x020370F5`,
  `sStartMenuOrder 0x020370F6`. The patch's free EWRAM tail is `0x0203FD44` to `0x0203FFFF`,
  runtime-proven and watched by `lua/tests/test_live_ewramtail.lua`; do not re-derive it
  statically.
- **Savestates rot across BizHawk versions.** `tools/mkstates.py` rebuilds them from the
  battery save. Overworld states need encounter-free ground (a town save in front of a Center
  door); battle states need tall grass. A grass-derived overworld state makes walking gates
  flaky. `client.exitCode(n)` exits in 2.11.1; `client.exit(n)` does not.
- **Duo harness facts.** Instance B XORs party OT ids with `0x000B0000` after the savestate
  load so keys do not collide; the runner posts `/api/debug/set_pokeballs` for both players;
  io paths inside Lua must be absolute (EmuHawk resolves relative to its exe directory);
  links are injected with `/api/inject_link`.
- **RR type data is not vanilla** (Tepig is Fire/Fighting in RR). Never use
  `data/games/gen3_frlge/rr_types.json` for another ROM.
- **A latent bug class in the Gen 3 client:** a `local function send` declared after a
  dispatcher that calls it bound `send` to a nil global inside the dispatcher. Forward-declare
  file-scope functions above their first use.
- **EvRing fast paths** (`EV_PLAYER_FAINT`, `EV_OUTCOME`, `EV_EVOLVE`) accelerate the faint
  debounce, whiteout and stats refresh on patched ROMs; the polls remain as the unpatched
  fallback. Do not remove the polls while unpatched vanilla FRLG is supported.

## 5. Division of work

Root owns every file the sweep reserved (`server/gen1_runtime.py`, `durable_runtime.py`,
`gen1_frame_*`, `gen1_runtime_state.py`, `gen1_observation_provenance.py`, the native
runtime, `gen1_launcher.py`, `identity_registry.py`, `staged_state.py`, `state.py`,
`gen1_held_faint.py`, `held_write_permit.py`, the reserved Lua entries). The peer can take,
without escalation: item 6, the translation tests for item 2, the observation-loop Lua for
item 3 as a proposal file, the executor map entries for `force_explode` and
`replace_rival_team` as proposal files, every live gate run, and the checklist rendering.
