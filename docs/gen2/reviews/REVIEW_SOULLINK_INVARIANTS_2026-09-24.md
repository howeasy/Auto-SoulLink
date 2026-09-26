# Independent review: Soul Link invariants end to end (asm, Lua clients, server)

> **Historical record — the three MAJOR findings were fixed.** MAJOR-1 in `15f1e786` ("post-DONE
> trade reports are owed until the server answers them") and `7e9e5543` (release-ZIP follow-up),
> MAJOR-2 in `3b5b5a5a` ("a hello's hp==0 faint of a trade key waits for the trade"), MAJOR-3 in
> `779c73c2` ("resolve_trade keeps each side's known outcome; adopt + split"). The MINOR/NIT items
> were not individually re-verified in this sweep — check `git log` for the relevant `state.py`/
> `client.lua` regions before treating any of them as still open.

Reviewer: Claude (Fable 5.1), not an author of any of the reviewed code. Read-only. No emulator was run
and no vision was used. Branch `codex/gen2-foundation`, HEAD `5fbb3c77` plus the O-32 working tree
(`lua/gen2/client.lua` `land_bench_deaths`, `lua/gen2_write_safety.lua` `evaluate_frame`). Game facts
come only from the pinned decomps: `.cache/gen2-build/pokecrystal` @7a7881d (cited `C`) and
`.cache/gen2-build/pokegold` @656583c (cited `G`). Line numbers are the working tree at review time.

Scenarios marked **[reproduced]** were run with a throwaway probe against `server/state.py` on the
`tests/unit/test_state_trade_uncertain.py` fixtures (Gen 1 adapter; the trade FSM is gen-neutral).
The probe was not committed. Lua-side findings are traced, not run.

Method: for each invariant I enumerated the cross-component interleavings (a death in the trade
window, a whiteout in it, a restart with commands in flight, a reset between the forced save and the
commit, the tower and contest against the faint path, O-24 against memorialize ordering, the deferred
lift against the checkpoint re-zero) and traced them asm -> Lua -> wire -> `state.py` -> back. The
three earlier reviews' findings are not re-reported; section 2 says whether their fixes close them.

---

## 1. Findings (ranked)

### MAJOR-1 (I1, I2): the DONE-path `trade_done` is dropped when the socket is down, and nothing re-sends it

- **Where:** `lua/gen2/client.lua:108-136` (`send` returns false and DROPS when `net.connected()` is
  false; it holds only when connected-but-not-ready), `:795-799` (the post-DONE report), `:603-606`
  (`nothing_changed`). `lua/gen1/client.lua:176-187`, `:1987-1993` (same shape). `lua/connector.lua:275-281`
  (`disconnect` empties `_send_queue`, by design). Only `trade_uncertain` and `withdraw_offer` go through
  `self.trade_owed` (`client.lua:707-714`, `:621-625`), which is flushed once the hello is ready.
- **Interleaving:** a network blip (no server restart) between the cartridge's DONE and the frame the
  client reports it. The cartridge has committed and saved. The report is gone. The server stays
  `applying` for `TRADE_WATCHDOG_EVENTS` (4000 events, ~17 min at two 30-frame tickers,
  `state.py:610`), then asks `withdraw_trade` (`:629-636`), which the client ignores because its
  `trade_state` is already nil (`client.lua:734-742`), then 4000 more events before the phase becomes
  `uncertain` and party evidence may settle it (`:641-651`). For ~35 minutes: the link is crossed on the
  server while the mons have physically swapped, `_reconcile_party_keys` (drift AND the O-24 repair) is
  off for BOTH players (`state.py:2824-2825`), and a whiteout on either side kills by the unswapped
  halves (MINOR-5). Not reproduced (Lua); traced.
- **Fix:** route every post-DONE report (`trade_done` with the received key, `nothing_changed`) through
  `self.trade_owed` in both clients, as `trade_uncertain` already is. Server side, the reconnect hello
  of an `applying` side whose `done[pid]` is False is already carried to `_trade_evidence` but ignored
  because the verdict is `None`, not `await` (`:1019`); treat a post-hello snapshot from an
  undecided `applying` side as evidence too (or move the watchdog to monotonic time, review MINOR-5).

### MAJOR-2 (I1, I4): the hello's hp==0 faint detection ignores the pending trade and runs before the evidence

- **Where:** `state.py:1487-1509` (`_handle_hello` propagates a faint for every party key at hp 0 whose
  link is ALIVE, by `player_id`), `:342-348` (`_hold_for_trade` covers only `faint`/`party_to_box`/
  `box_to_party` events; the hello runs, then `_trade_evidence(from_hello=True)`).
- **Interleaving [reproduced, probe P1b]:** A committed and holds B's mon (`1234:5678:15`); B is
  `await` (silent, or reset). A's received mon faints; A's `faint` event was lost (MAJOR-1 class) or A
  simply reconnects with it at hp 0. The hello kills the link through the UNSWAPPED halves:
  `force_faint 1234:5678:15` -> B (B does not hold it: Gen 2 defers it then drops it at the checkpoint,
  Gen 1 drops it on receipt), `memorialize ABCD:1234:26` -> A (A does not hold it: `memorialize_failed`
  -> MEMORIAL). Then B's evidence commits the swap. B's real partner (`ABCD:1234:26`, alive in B's
  party) dies only through O-24, and only after the 12 post-trade settle ticks (`:2826-2828`), at tick
  11 in the probe; it is never memorialized without another hello (`pending_memorials` sits on the
  wrong players; 200 further ticks queued nothing for B).
- **Fix:** in `_handle_hello`, for a key `_hold_for_trade` would hold, append a synthetic
  `{"event": "faint", "key": k}` to `pt["held_events"]` instead of propagating; and run
  `_trade_evidence(from_hello=True)` BEFORE the hp==0 loop so a hello that settles the trade also routes
  its own deaths by the swapped link.

### MAJOR-3 (I1): a faint of a trade key during `conflict` is held until an admin acts, and `rollback` cannot kill the copy a one-sided commit left

- **Where:** `state.py:666-683` (held during `applying`, `uncertain`, `conflict`), `:1051-1081`
  (a conflict is sticky), `:1148-1167` (`resolve_trade` offers `commit`/`rollback` only; the review's
  `adopt` was not implemented), `:2775-2777` (O-24 matches the half by key).
- **Interleaving [reproduced, probes P4, P7b, P7c]:** B refuses (or its cartridge left) and A commits:
  A holds a COPY of B's mon, A's own mon is gone from every party (conflict `a: traded; b: none`). B's
  real mon faints: the event is held; 5000 events later the link is still ALIVE and nothing has died.
  Admin `commit`: the swap makes `entry.a` = B's key, the replay sends `force_faint` for it to A, the
  copy dies (correct). Admin `rollback`: the replay kills `ABCD:1234:26` on A, which A does not hold;
  A's copy of B's mon lives at full HP for the rest of the run, the link is DEAD, and O-24 never matches
  it (`half.key != key`). The board shows the verdicts but not which action matches the physical
  parties.
- **Fix:** (1) surface the held events on the trade banner next to the resolve buttons; (2) add
  `adopt` (re-point each half to whichever party snapshot holds the key, then replay); (3) on
  `rollback`, for a side whose verdict was `traded`, also queue `force_faint` for the partner key it
  holds when a held faint names that key. Until then, record "rollback after a one-sided commit leaves
  the copy alive" as an operator rule.

### MINOR-4 (I1): a whiteout during the trade window kills by the unswapped link

- **Where:** `state.py:2468-2487` (`_handle_whiteout` walks ALIVE links by `party_keys`, which the
  commit alone updates, `:1187-1190`); `whiteout` is not in `TRADE_HELD_EVENTS` (`:663-664`).
- **Interleaving [reproduced, probe P2b]:** A traded, B `await`; A whites out: `force_faint` for B's
  old key goes to B (not held there), `memorialize` for A's old key goes to A (not held). After B's
  evidence commits, A's received mon (healed by `HealParty`, C `engine/events/whiteout.asm:14`) is
  re-killed by O-24 only while `run_over` is False (`:2762`); in the probe the whiteout also ended the
  run, so nothing re-killed it. Same shape for P7 (whiteout on the side that refused while the other
  committed: conflict, the copy lives).
- **Fix:** in `_handle_whiteout`, hold the per-link kill for a link the pending trade names (push a
  synthetic `faint` into `held_events`), and let the replay route it after the swap.

### MINOR-5 (I1): the O-24 repair is switched off by the rebuild gate and the `applying` gate

- **Where:** `state.py:2815-2816` (`rebuild_pending` returns before `_repair_lost_faints`),
  `:2824-2825` (`applying`), `:2762` (`run_over`).
- **Interleaving [reproduced, probe P8]:** A whites out with one boxed alive pair: the rebuild's
  `party_mon` is queued before A's own `memorialize` (correct order for the last-party-mon rule), A's
  party is `HealParty`-revived, the link is DEAD. While the rebuild is pending (its `sync_retrieve_*`
  answer can be lost exactly as in MAJOR-1, and only the next hello re-arms it, `:1597-1620`), 130
  ticks with the dead lead alive queued nothing. During `applying` the same holds for both players for
  the whole watchdog period (MAJOR-1).
- **Fix:** call `_repair_lost_faints` before the rebuild/trade early returns; it is keyed by link
  status and `death_inflight`, not by the party bookkeeping those gates protect.

### MINOR-6 (I1 "stays dead", ordering): a restart loses a queued `force_faint`; the hello then buries the mon alive

- **Where:** `queued_commands` and `death_inflight` are not persisted (`_save` `:3716-3796`); the
  hello re-memorializes a dead key found in the party (`:1520-1534`) but queues no `force_faint`; the
  first tick's O-24 re-issue (`:2788`) lands one arrival later.
- **Interleaving [reproduced, probe P3b]:** B's queue holds `force_faint`+`memorialize` for its dead
  mon; the server restarts before B polls. After reload: B's hello gets `memorialize` only; B's first
  tick gets `force_faint`. The client runs them in arrival order: `memorialize` first (`run_box`, the
  mon at full HP goes to the memorial box), then `force_faint` finds "key not in party" and is dropped
  (`client.lua:857-862`). Result: a mon at full HP in the grave. The server treats it as dead and a
  withdraw is re-memorialized (`:2609-2619`), so the invariant holds in effect, not in the bytes.
- **Fix:** in the hello's re-memorialize loop, queue `force_faint` before `memorialize` when the key
  reads hp > 0 (dedupe against `_has_pending_command`); or persist `queued_commands`.

### MINOR-7 (I1, both gens): a landed death leaves no durable re-zero, so a heal before burial revives it

- **Where:** `run_deferred` drops a quiet entry at the first checkpoint where HP reads 0
  (`client.lua:864`), and the checkpoint's own non-quiet kill leaves no quiet entry at all (`:870-880`).
  Gen 1's loop-head lift has the same lifetime (`gen1/client.lua:1468-1483`).
- **Interleaving:** the death lands at the checkpoint; before `memorialize` runs (it needs another
  hold, and is refused "last party mon" until a `party_mon` lands, `:944-947`) the player heals at a
  Pokémon Center, or walks the dead mon into the Battle Tower, whose `RunBattleTowerTrainer` runs
  `HealParty` before battle 1 (C `engine/events/battle_tower/battle_tower.asm:226-228`) and whose
  rules never check HP (C `rules.asm:27-53`). The mon fights until O-24 re-issues, which
  `death_inflight` suppresses for up to 120 out-of-battle passes after the original delivery
  (`state.py:79`, `:2778`). The 4e6aea39/00c9373c tower fix covers only a revival with no checkpoint
  in between (inside one `Script_BattleRoomLoop`), not a dead mon carried into the tower.
- **Fix:** the client keeps a `dead_keys` set from every landed kill until `memorialize_done` or the
  key leaves the party, and both the checkpoint and the battle hold/bench pass re-zero any member
  that reads HP > 0; no server change.

### MINOR-8 (I2): `_commit_trade` uses trade keys a `key_change` may have migrated

- **Where:** `state.py:3172-3177` rewrites `pt["a_key"]/["b_key"]` on a key change; `_commit_trade`
  then discards the NEW key from the giver's `party_keys` (`:1187-1190`) and moves `bonus_keys`/
  `mon_stats` by it (`:1193-1200`).
- **Interleaving [reproduced, probe P6]:** a `key_change` for the received mon's evolution arrives
  during `applying` (Gen 2's binder refuses it under `wLinkMode != 0`, `signals.lua:658`, so this is
  a Gen 1/Gen 3 shape). After the commit `party_keys["a"]` still holds the giver's old key as a ghost
  until the drift reconciler discards it after the 12 settle ticks; a shiny-bonus flag under the old
  key would not follow the mon.
- **Fix:** remember the original keys (`pt["a_key0"]`) at `_execute_trade` and discard/move both.

### MINOR-9 (I5): Gen 1 drops a `force_faint` whose key is not in the party; Gen 2 defers it

- **Where:** `lua/gen1/client.lua:528` vs `lua/gen2/client.lua:458-461` (4e6aea39 MINOR-3 fix).
- A Gen 1 target in the Day-Care or a box is repaired by O-24 only when it re-enters the party (the
  snapshot is the only evidence). Harmless, but an undocumented divergence. Record it, or port the
  deferral (the Gen 1 checkpoint already drops a departed key with a log).

### NIT-10 (O-32 WIP, I4): the "never mid party-menu/switch copy" clause of O-32 is argued, not gated

- `evaluate_frame` (`gen2_write_safety.lua:678-706`) checks identity, SVBK, serial, the battle hold's
  predicates (`wLinkMode`) and `wBattleMode != 0`. Safety of a frame-end bench write against a switch
  rests on source order: `PlayerSwitch` sets `wCurBattleMon` before `BattleMonEntrance` copies the
  party struct (C `core.asm:5195`, `:5249-5271`), so the incoming mon is "active" (skipped) before its
  bytes are read, and `UpdateBattleMonInParty` only writes the active slot. That is sound; the U2
  `battle_bench` validator's `what == "switch"` refusal (`gen2_write_safety.lua:430`) is the right
  physical check. The tutorial battle (real party, no mon sent out, C `core.asm:55-59`) is a legal
  bench target and needs no exclusion.

### NIT-11: reports in the `uncertain` phase are dropped, including MAJOR-5's `after_reset` flag

- `state.py:962` returns for any phase but `applying`. After a BLOCKER-1 restore, a result-2
  declaration is dropped and `hello_only` never set **[reproduced, probe P5]**: a tick from the
  soft-locked RAM party gives `holds NEITHER`. Unreachable in practice: both clients gate the hello on
  the checkpoint (`client.lua:1159`, `gen1/client.lua:1718`), which the result-2 hold never reaches,
  so no tick can flow before the reset. Keep the flag anyway: accept `uncertain`/`after_reset` for a
  side still `await`.

### NIT-12: game over turns O-24 off

- `state.py:2762`. After `run_over` nothing re-kills a revived dead mon (owner ruling (a), 4aa1ad5c:
  burial is the assertion). Note only.

---

## 2. Per-commit verdicts

| commit | closes its findings? | note |
|---|---|---|
| 00c9373c Gen 1 lift | **yes** (O-30 MAJOR-1/2) | the lifted quiet entry lives until the next checkpoint reads HP 0; a dead mon carried into a multi-battle script is O-24-only (MINOR-7) |
| 4e6aea39 Gen 2 hold lift, MINOR-3, NIT-6/7 | **yes** | same caveat; the contest windows are closed because no `OWPlayerInput` sits between `ContestDropOffMons`/`setflag` or `BugContestResultsScript`'s clear/`ContestReturnMons` |
| 9805ac1c trade asm | **yes** | BLOCKER-1: `SlinkTradeCheckParty` (contest bit + `$FF` terminator at count) runs from `SlinkTradeEntry` and from every `SlinkTradeCheckOwnSlot`, i.e. before any UI on both roles. BLOCKER-2: proposer `Text_MustSaveGame`/`TryQuickSave` in the receptionist script, responder `Link_SaveGame` after YES, `SlinkTradeCheckSaved` (`wSavedAtLeastOnce`, set by `_SaveGameData` C `save.asm:374`). MAJOR-1: `PLAYERSTEP_CONTINUE_F` clear + `MAPEVENTS_ON` in the dispatcher. MINOR-1: `LINK_TRADECENTER` around `RemoveMonFromPartyOrBox` (C `move_mon.asm:1335-1337` skips the mail shift) and `.ShiftMail` immediately before `SaveAfterLinkTrade` (residual window: a few frames). MINOR-2/3 texts, NIT-2 `BackupGSBallFlag`. The party-count checks after each native step are correct |
| 67143736 waits | **yes** | |
| 61a693c4 / 6a4269d8 Gen 1 forced save | **yes by diff** | both roles save, the commit ends in `SaveGameData`, idle-frame pickup; MODEL-tested, not re-audited at the asm level here |
| 006910b2 withdraw + journal | **yes** | |
| 4d6524e5 Gen 2 uncertain/withdraw | **yes** | the DONE-path report still goes through `send` (MAJOR-1) |
| 8d3325e5 Gen 1 mirror | **yes** | same caveat |
| 690d6050 hold/replay (MAJOR-2 of the server review) | **partially** | faint/box events are held and replayed correctly (`test_state_trade_hardening.py:68-119`); the hello path (MAJOR-2 here) and the whiteout (MINOR-4) are not held; a conflict holds forever (MAJOR-3) |
| 7de364f0 persist + tokens | **yes** | `held_events` and `hello_only` ride in the persisted dict |
| 4fc4a6c6 watchdog withdraw, result-2 hello_only | **yes** | NIT-11 gap is unreachable |
| ebdd6d6d / a3e1f33d prepare round | **yes** | the remaining one-delivery window is real and accepted; its consequence is the MAJOR-3 admin rule |
| 08f7175a new_key rule, ef7ae792 sanity, 206d68aa forget-before-commit, b3a21459 owed list, 2676c2f9 contest | **yes** | |
| e5a03933 bookkeeping moves with the mon | **partially** | not after a key_change in the window (MINOR-8) |
| 97ada0fa admin resolve | **partially** | no `adopt`; `rollback` after a one-sided commit leaves the copy alive (MAJOR-3) |
| O-32 working tree (`land_bench_deaths`, `battle_bench` kind) | sound by source | production-gated behind a `battle_bench` receipt that also requires `battle_faint`; see NIT-10 |

---

## 3. Verified OK

- **I3, the forced save and the commit save.** `SaveAfterLinkTrade` writes `wPokemonData` primary then
  backup with a checksum after each (C/G `save.asm:26-37`); a reset between a data write and its
  checksum loads the other copy. Both copies of the rest of `sGameData` come from the forced full save
  minutes earlier and neither role roams in between (the proposer is held from the receptionist, the
  responder saves inside the held PROMPT). `BackupPartyMonMail` runs after `.ShiftMail`. The mailbox
  and lease are WRAM0 outside `sGameData` on both titles; the staged `wOTParty*` scratch is inside
  `wPokemonData` on G/S and is harmless stale data, as vanilla trainer parties are.
- **I3, GS Ball.** `BackupGSBallFlag` after the trade save on Crystal only.
- **I4, no wrong kill.** Every in-battle write path refuses `wLinkMode != 0` three times (client
  `:1302`, `:1379`; `writes.lua:143`; the pack predicate), and Gen 1 refuses `link_state == 4`. The
  death resolver matches the exact key or the DV/OT identity plus a descendant species, and refuses two
  answering slots. The server's `_propagate_faint`/O-24 target only the half whose key matches.
- **I1, the deferred lift and the checkpoint re-zero.** A quiet entry keeps the original arrival, so it
  never falls behind that key's memorialize; the lift takes it into the hold only while HP > 0; a bench
  entry the O-32 pass landed is dropped at the hold when HP reads 0 and settled by W-2 when it was
  switched in. The echo drop is keyed by the physical key and every server death issuer pre-marks the
  link, so a dropped echo cannot lose a death.
- **I1, evolution of a dead key.** `key_change` on a buried link re-queues `force_faint` and
  `memorialize` under the new key **[reproduced, probe P10]**.
- **I1 during the trade window.** A `faint` of a trade key is held during `applying`/`uncertain` and
  replayed against the swapped link; a rolled-back trade replays against the unswapped one
  (`test_state_trade_hardening.py`). The Gen 2 binder refuses the trade-evolution `key_change` under
  `wLinkMode`, so the evolved key reaches the server only through `trade_done`/evidence.
- **I2, restart.** `applying` is restored as `uncertain` with both undecided sides `await`; `preparing`
  and earlier are dropped safely (nothing armed). Tokens persist. A `trade_done` that arrives after
  the restore is dropped but the same evidence rule settles the side. The hello gate keeps a mid-scene
  party from becoming evidence on both gens.
- **I2, the contest.** `trade_blocked` on every tick makes no pair eligible; `trade_prompt` and the asm
  refuse a masked party; the responder cannot enter the contest while held.
- **I4, the contest whiteout.** The lead's `LostBattle` in the contest goes through `Script_Whiteout`
  with the party masked to one; that one has already fainted natively, so `_handle_whiteout` finds no
  ALIVE link in `party_keys` for it, and the hidden five were discarded from `party_keys` by the ghost-
  party reconcile during the contest, so they are neither killed nor rebuilt into the party.
- **I5.** Recorded divergences hold: Gen 2's hold site and USEITEM, the quiet re-zero, the echo drop,
  O-32's receipt gate (Gen 1 lands bench deaths on receipt unconditionally). MINOR-9 is the one
  unrecorded divergence found.

---

## 4. Top 5 missing red-capable tests

1. **Lua (Gen 1 + Gen 2):** DONE polled while `net.up = false`; assert the report is owed and reaches
   the server right after the reconnect hello (MAJOR-1). Fails today: `send` drops it.
2. **Server:** A traded, B `await`; A's hello carries the received key at hp 0. Assert the death is
   held and, after B's evidence, `force_faint`+`memorialize` go to B for A's old key and nothing to the
   wrong holders (MAJOR-2). Fails today.
3. **Server:** same window, A sends `whiteout`. Assert the pending-trade link's kill is routed after the
   swap (MINOR-4). Fails today.
4. **Server:** `rebuild_pending` (or `applying`) set, a party snapshot shows a DEAD key at hp > 0.
   Assert `force_faint` is re-issued within one tick (MINOR-5). Fails today.
5. **Lua (Gen 2, then Gen 1):** a checkpoint-landed death, the party healed by a native `HealParty`
   with no checkpoint in between (tower entry), the next battle hold. Assert HP 0 again with one KO
   line (MINOR-7). Fails today.

Also worth pinning: a restart with a queued `force_faint`, asserting the client-visible order after
the hello is `force_faint` before `memorialize` (MINOR-6); and `resolve_trade("rollback")` after
`a: traded; b: none` with a held faint of B's key, asserting A's copy dies (MAJOR-3).
