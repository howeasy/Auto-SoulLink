# P3 shared modules + Gen 1 rebind: adversarial review (gen2-R1)

Reviewer: gen2-R1 (did not author this code). Lease: worktree `gen2-foundation`, branch
`codex/gen2-foundation`, reviewed committed HEAD `0a1aa79` against master `8f6a986`. The only
file written is this review. No repo file was edited, nothing committed, no emulator run.

## Method

- Read every shared module in scope, its `docs/shared-*.md` contract and PLAN §5.15/§5.15a-j.
- Diffed the Gen 1 rebind (`git diff 8f6a986 HEAD -- lua/gen1/ lua/gen1_write_safety.lua
  lua/tests/gen1_scripted_play.lua tools/gen1_fixtures.py tools/make_release.py`).
- Differential probes: a `git archive 8f6a986` snapshot was extracted to a scratch directory
  outside the repo, and the same Python/lupa harnesses (`World` from `test_gen1_client.py`,
  `Harness` from `test_gen1_signals.py`) were driven against master and HEAD side by side.
  Probe scripts (scratchpad, not committed): `probe_signals.py`, `probe_client.py`,
  `probe_send_hello.py`, `probe_pending.py`, `probe_admit.py`, `probe_checkpoint.py`, `mutate.py`.
- Baseline at HEAD: Gen 1 + shared unit subset `1791 passed, 58 skipped` (test_gen1_trade_patch
  deselected; Gen 2 files excluded because another worker has them modified in the tree).
- CONFIRMED = reproduced by a scratch probe; PLAUSIBLE = code reading only.

## 1. The 13 declared behaviour differences

| # | Declared difference | Verdict | Reason |
|---|---|---|---|
| 1 | clock rewind forces a new hello and clears the panel | **RISK** | CONFIRMED: master 1 hello, HEAD 2 hellos after a backward frame jump. Every backward savestate load by a player now clears the in-game panel rows and re-hellos (server reconnect path). Player-visible; needs a physical duo reconnect/savestate receipt. |
| 2 | wPlayerID/version change re-hellos, clears aliases + pending_change | KEEP | Master already cleared these on WRAM clear. The identity now also includes pureRGB `wGameInternalVersion`, so a stamp change drops a pending acquisition. Acceptable; note it for the pureRGB duo. |
| 3 | panel cleared on every invalidation | KEEP (bounded by 1 and 6) | Master already cleared on disconnect and on WRAM clear. The new clear reasons are exactly rewind (#1), transport error (#6) and callback error. |
| 4 | unreadable save version or battle state holds the hello | **RISK** | CONFIRMED: `wIsInBattle = $FF` is a real engine state (pokered `home/overworld.asm:355-356`, `.allPokemonFainted`; `ram/wram.asm:1236` "lost battle, this is -1"), not an unreadable one. `client.lua:1569-1571` holds the hello; master sent it. A first hello or a reconnect during a blackout waits for the overworld checkpoint. Accept `$FF` as in-battle, or document the hold. |
| 5 | no hello while party unreadable | KEEP | A fix: master could send an empty party. It retries next frame. |
| 6 | hello callback / net.pump errors logged and retried | **RISK** | CONFIRMED: a single `net.pump` error now runs `invalidate("transport_error")` (`client.lua:1867-1872`), which clears the panel and sends a second hello even though the socket may still be up (probe: 2 hellos). Master propagated the error and kept the session. Suggest invalidating only when `connected()` is false afterwards. |
| 7 | send returns false on explicit transport false | KEEP | `connector.send` (`lua/connector.lua:140-142`) returns nil, so production behaviour is unchanged. |
| 8 | admission always rehashes actual ROM bytes | KEEP semantics, **RISK** cost | Catalog check: no duplicate or upper-case hash across the 9 Gen 1 candidates, so there is no new ambiguity. The cost is CONFIRMED (U5): the ROM is read in full twice. |
| 9 | second concurrent start raises "owner namespace already active" | KEEP | Production starts once per Lua load, and each `dofile` of entry.lua gets a fresh registry. |
| 10 | sparse/keyed reply command list refused whole | KEEP | JSON arrays only become sparse through `null` elements; refusing the whole list is safer. |
| 11 | errors raised by the error reporter are contained | KEEP | |
| 12 | start() releases old hooks; failed release aborts | KEEP (see U7) | |
| 13 | dispatch budget math.huge keeps drain-every-line | KEEP | Verified: `connector.receive` returns nil when empty, so the loop cannot run forever. |

## 2. Unlisted Gen 1 differences (ranked)

**U1 [HIGH, CONFIRMED] One on_fire handler error silently kills every later engine signal.**
`lua/hook_registry.lua:67` drops every callback once `state.handler_error` is set. Master
(`8f6a986:lua/gen1/signals.lua:340,359`) only checked `closed`/`failure`, so a handler error was
recorded and later signals kept queuing. Probe (`probe_signals.py`, real Red ROM): master
`later: ['battle_loop_head', 'move_mon']`, HEAD `later: []`, and `failed` stays nil. The client
level shows the same (`probe_client.py` S2: master (1,1), HEAD (1,0)). The client never reads
`signals:status()`, so nothing is logged.

Trigger: `on_battle_loop_head` has no pcall (`client.lua:1381-1417`). A W-10 WRAM-bank refusal
inside `faint_active_battler` (master documented this path as "the caller retries next frame"), or
any read error, raises through it. After that, captures, faints, whiteout, save witness, trade
service and evolution are all lost until restart.

Fix: do not gate the queue on `handler_error`; keep it a status field, as master did. Or make the
latch an explicit binder policy and have Gen 1 opt out. Add a test that fires a second signal after
a handler error.

**U2 [HIGH, CONFIRMED] The Gen 1 duo save-witness tee now throws before the real hook runs.**
`lua/tests/duo/duo_gen1_main.lua:161-169` reads `SLINK_GEN1_CLIENT.signals.pending`. The registry
service keeps its queue in a closure, so `pending` is nil and `#sigs.pending` raises inside the
`SLink-gen1-save_witness` bus-exec wrapper, before `fire()` is called. `probe_pending.py`: master
returns `true 0`; HEAD raises `attempt to get length of a nil value (field 'pending')`. The
save_witness signal is never queued and `SAVE_WITNESS_DUMP` is never logged. Every gen1_new duo
scenario that saves therefore fails the mandatory witness stage (`tools/e2e_duo.py:679-683, 4049`),
which breaks the duo-pairs and duo-pairs-purergb lanes.

Fix: expose a read-only pending count or queue peek on the service, or move the tee onto
`drain()`/`status().pending`.

**U3 [HIGH, CONFIRMED] Gates that call `send_hello()` directly no longer send anything.**
`client.lua:1511-1513` refuses a nil `expected_identity`. `lua/tests/test_gen1_inspect_gate.lua:66`
calls `t.client:send_hello()` and immediately logs `t.sent[#t.sent]`. That gate never calls
`frame_end`, so the session never sends a hello either. `probe_send_hello.py`: master sends 1
hello; HEAD returns `(False, 'hello identity changed or unavailable')` and sends 0.
`tests/live/test_gen1_new_gates.py:127` then cannot parse `HELLO`, so the inspect lanes go red
(live-new-gates inspect, inspect-purergb, inspect-purergb-overlay).

`test_gen1_apex_gate.lua:103` and `test_gen1_apex_refusal_gate.lua:163` should survive only because
their `settle()` runs `frame_end` (PLAUSIBLE).

Fix: give `send_hello()` an explicit "current identity" path for harness use, or have the gates
step the session.

**U4 [MEDIUM, CONFIRMED] `wIsInBattle = $FF` holds the hello.** The detail is under #4 above. It
is recorded here as well because the commit describes the state as "unreadable".

**U5 [MEDIUM, CONFIRMED cost / PLAUSIBLE player impact] Boot reads the whole ROM twice.**
`admission.lua:143` acquires every byte, and `:189` acquires all of them again to detect a change.
`probe_admit.py` on the 1 MiB Red ROM:

| | ROM byte reads per boot |
|---|---|
| master, non-database hash hit (the pureRGB case) | 0 |
| master, database ROM | 1,048,576 |
| HEAD, every boot | 2,097,152 |

In BizHawk each read is an NLua `memory.read_u8` call, so a pureRGB boot gains about 2M interop
calls and a vanilla boot about 1M. Suggest one bulk read, or a second hash instead of a second full
string build.

**U6 [LOW, PLAUSIBLE] Fire-time check order changed.** `gb_hook_binding.lua:185-196` (`context`)
asserts PC and bytes before the per-kind filter (`signals.lua:343-347`); master ran the filter
first. A PC mismatch on a hit that master would have filtered away now latches `failure`, which
stops all signals. Filter errors are now latched too, where master let them escape uncaught. This
is unlikely on Gambatte.

**U7 [LOW, PLAUSIBLE] Re-arm depends on `event.unregisterbyid` returning true.** The registry
treats `false` as a cleanup failure (`hook_registry.lua:51`), and BizHawk returns false for an
unknown id. `client.lua:1853` then aborts `start()`, and `factory.failed_service` blocks later
builds. Master ignored the return value.

**U8 [INFO] Error receipts in `writes.log`.** `writes.log` now also receives `status="error"`
receipts when `write_u8` throws mid-span (`write_permit.lua:145-148`). The duo counts
`#parts.writes.log` (`duo_gen1_main.lua:2077`), so this only matters on I/O errors.

**U9 [INFO] Admission refusal text changed.** `entry.lua` now appends `": " .. why`. This is
console text only. The `run.lua` named-family fallback is unaffected (verified: gen1_rby candidates
carry no header, so an unknown vanilla hash is still refused and falls back as before).

Unlisted differences that are fixes (KEEP):
- `check_slot` runs before the first byte in `faint_active_battler` and `explode_active_battler`
  (`writes.lua:138,148`). Master wrote `wBattleMonHP` and `wPlayerSelectedMove` before the slot
  assertion, which was a partial write.
- Any write error disarms the permit (`guard`). Master left "battle_loop_head" armed after a throw
  inside the hook.
- A soft reset clears `hello_sent` in the same frame as the identity change, not at the next
  validate. The duo check `HELLO_CLEARED <= 120` still holds.
- A frame whose `validate()` invalidates the session no longer sends a tick or safe event.
- New System Bus and CartRAM interval bounds, and sequence checks on DV, blob and name payloads.

## 3. Other findings (ranked)

- **O1 [LOW, rule]** `lua/scripted_inputs.lua` has no `docs/shared-scripted-inputs.md` contract,
  although §5.15 requires one per shared module. `gb_hook_binding` is covered in
  `docs/shared-hook-registry.md`.
- **O2 [LOW]** `Entry.admission_table` and `Entry.anchor_matches` (`entry.lua:109,170`) are no
  longer on the admit path, which uses `admission_candidates` at `:201`. But
  `test_gen1_purergb_{client,profile,rom_scan}.py` still use them as oracles, so the tested catalog
  and the production catalog can drift apart. `anchor_matches` also now raises on an out-of-range
  anchor, where master returned false.
- **O3 [LOW]** The registry's duplicate-handle refusal (`hook_registry.lua:115`) leaves that
  backend registration unowned. This is deliberate, since the handle may belong to someone else,
  but the contract does not say so.
- **O4 [INFO]** `gen1_write_safety.check`, the legacy global path used by the gates and the duo,
  now depends on `debug.getinfo` self-location (`gen1_write_safety.lua:8-13`). There is master
  precedent for this (`run.lua:9`).

## 4. Safety paths checked

- **Write permit.** Unarmed, narrowed, wrong-WRAM-bank, sparse, metatable, non-byte, overflowing
  (2^53) and empty payloads are all refused before the first byte. Provenance and policy errors
  emit nothing. An I/O error mid-span disarms the permit and reports `completed`/`attempted`; no
  rollback is claimed, and the contract says so (`shared-write-permit.md:94-95`). Descriptors and
  payloads are snapshotted before any callback runs. Clean; the existing 26 tests cover these cases.
- **Checkpoint.** A randomized differential (`probe_checkpoint.py`) ran 3000 trials over Red and
  Yellow, mutating PC, SP bounds, stack words, WRAM predicates and ROM anchors. Master accepted 1815
  states, with **0 mismatches**. The stack-bound equivalence (`sp+3 <= stack_end` versus
  exclusive_end + read_bytes) was checked by hand, and all 9 Gen 1 checkpoint anchors fit the new
  ROM0 `[0,0x4000)` bound.
- **Admission.** The reported hash is never trusted; the ROM is always rehashed. The decision is
  frozen, and a ROM that changes during admission is refused. Duplicate catalog hashes would be
  refused as ambiguous; the data has none.
- **Hook registry.** Validation precedes registration. A failure rolls back the owned handles and
  releases the owner and names only when cleanup succeeds. Overflow latches `failure`, so it is not
  a silent success, but the Gen 1 client never reads that status (same as master). All 3 Gen 1 site
  packs pass the new GB validation (`rom_offset == flat`, `capture_offset` inside the anchor, bank
  window).
- **Scripted inputs.** Boot and run receipts and bounds match master. Every caller's `step`
  advances exactly one frame (`gen1_gate.lua:40-44`, and the duo `yield_frame` gets one
  `frameadvance` per resume).

## 5. Fixture qualification revert probe

A copy of HEAD `tools/fixture_qualification.py` was placed in a scratch root outside the repo.
`mutate.py` deleted the end-of-run revalidation block (lines 231-245, from "A later callback may
overwrite another case's output" through the `final_artifacts` refusal). HEAD
`tests/unit/test_fixture_qualification.py` was then run against each copy with
`python -m pytest -p no:cacheprovider`:

| Copy | Result |
|---|---|
| control (unmodified) | 13 passed |
| mutant (block removed) | **1 failed, 12 passed**: `test_later_output_collision_cannot_leave_earlier_row_qualified` (`assert True is False`, line 195) |

The test detects the revert. Separately, `tools/gen1_fixtures.py --qualify` at HEAD reports Red and
Yellow OK, and the pureRGB rows report NO-ROM, as on master. `LEGACY` is empty, so the new rule
that legacy fixtures refuse changes nothing today.

## 6. Rule compliance

None of the nine Lua modules or two Python modules contains a `game_id` branch, a game name or a
Gen 1 default. GB-only mechanics are named `gb_*`. The Gen 1 facts are all injected by `entry.lua`,
`writes.lua`, `signals.lua` and `client.lua`: System Bus/ROM domain names, hLoadedROMBank, the
`$D000-$DFFF` bank policy, charmap, catalogs, anchors, retry delay and dispatch budget. The only gap
is the missing contract doc (O1).

## 7. Areas checked and found clean

- `reply_dispatch`: command order, per-command isolation, whole-line validation, re-entry refusal, termination only on nil.
- `hello_session`: generation guard, identity re-check after send, retry pacing, hold on cleanup failure.
- `token_scanner` vs master `decode_name`: identical output for fixed-size reads; unknown-glyph formatting unchanged.
- `write_cart_bytes`: the panel refusal is preserved (`CartRAM.bounds` asserts reason ~= "panel", and the narrowed allow refuses anything outside System Bus).
- The panel allow predicate still sees only System Bus `(addr, n)`.
- `make_release.py`: all 8 new root modules are in `_LUA_ROOT`.
- `gen1_fixtures.py`: orchestration only; the `qualify()` oracle is unchanged, and scanner caches are restored in `finally`.
- `coverage_map.py`: contains no game names.
- Admission catalog: 9 candidates, all hashes lower-case, none shared.

## Closure (gen2-R1, HEAD e0b38b7)

Read-only re-check of the fixes by gen2-W8. At `e0b38b7`, `lua/` and the new test file match HEAD
in the tree. The new and updated tests pass: `test_gen1_rebind_regressions.py`,
`test_hook_registry.py`, `test_hello_session.py` and `test_gb_hook_binding.py` give 60 passed. I
reran my original master-vs-HEAD probes and added `probe_closure.py`.

| Item | Status | Evidence |
|---|---|---|
| U1 handler error kills signals | CLOSED | `hook_registry.lua:71` no longer gates on `handler_error`. The probe now matches master: `later: ['battle_loop_head','move_mon']`, `failed: None`. |
| U2 duo tee reads `pending` | CLOSED | The tee uses `#sigs:peek()`. `test_u2_*` runs the real tee chunk for both the dump and skip cases. |
| U3 no-arg `send_hello` | CLOSED | HEAD returns `(True, nil)` with 1 hello (master: 1 hello), and 40 later frames add none. |
| Diff 1 rewind | CLOSED | `clock_rewind="keep"`. Probe S3 gives master (1,1), HEAD (1,1), with no panel clear. |
| Diff 4 `$FF` blackout | CLOSED | Probe S1 gives master 1 hello, HEAD 1 hello. |
| Diff 6 pump error | CLOSED | `net.pump` is unprotected again. HEAD raises `LuaError` and sends 1 hello in total, with no clear. |
| U6 check order | PARTIAL | The order is restored (bank, filter, then PC/bytes), and a wrong-PC filtered hit latches nothing. A filter that throws is still a difference; see N1. |
| O1 scripted-inputs doc | CLOSED | `docs/shared-scripted-inputs.md` exists. |
| O3 duplicate handle | CLOSED | Documented in `docs/shared-hook-registry.md:34-38`. |

Attack results:
- (a) `send_now` keeps the connection and identity checks around send and skips only `ready` and
  pacing. Master's direct call skipped the same gates, so nothing master checked is bypassed.
  Offline, HEAD returns `(false,'disconnected')` and master sends nothing, so they are equivalent.
  Two direct calls produce 2 hellos on both.
- (b) The filter-error regression is real; it is listed as N1.
- (c) `peek()` is a deep copy. Mutating a nested `point.party[1]`, or adding a field through the
  view, leaves the drained event unchanged, and each call returns a fresh table.
- (d) The save_reset tolerance is honestly scoped. It collapses runs of consecutive clears on
  both traces, only in that scenario, and `clear` is idempotent when no sent line falls between
  two clears. However, the trace records only sent lines, panel clears and frame errors: no
  replies, panel rows, writes or signals. None of the 8 scenarios exercises commands, captures or
  writes. So "master-equivalent" holds for hello/panel scheduling only, not for the whole client.

New findings (ranked):
- **N1 [LOW-MED, CONFIRMED]** A filter that throws now latches `failure` and silently drops all
  later signals. The accept callback runs inside the registry's capture pcall
  (`signals.lua:346`, `gb_hook_binding.lua:60`). On master the error escaped that one hit and
  later signals continued. Probe: a missing `F` register on `bag_received` gives master
  `later: ['move_mon'], failed: None` and HEAD `later: [], failed: 'no F register'`. This is latent
  (the only filter reads H, L, F and `wCurItem`, all proven live), but it is an unlisted
  kill-switch of the same class as U1. Either treat a throwing filter as a dropped hit and record
  it, or list it as an intended difference.
- **N2 [LOW, CONFIRMED]** A direct `send_hello()` with an unreadable party now refuses
  (`'hello party snapshot unavailable'`, 0 hellos). Master sent a hello with an empty party. This
  falls within listed diff #5 but now applies to the gate path too.
