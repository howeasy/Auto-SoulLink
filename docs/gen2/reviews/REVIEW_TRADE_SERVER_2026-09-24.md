# Independent review: the server's native-trade state machine and uncertain-trade reconciliation

Date: 2026-09-24. Branch `codex/gen2-foundation` at `6840bd9a`. The reviewer did not write this code.
The review is read-only and used no emulator. Line numbers refer to `HEAD` unless marked otherwise.

## Scope

- `server/state.py`: `pending_trade`, `_tick_pending_trade` :581, `_handle_trade_request` / `_handle_trade_query` /
  `_handle_trade_offer` :611-675, `_handle_mon_chosen` :677, `_handle_menu_result` :737, `_execute_trade` :789,
  `_handle_trade_done` :835, `_trade_evidence` :872, `_settle_trade` :912, `_record_trade` :940,
  `trade_problem` :951, `_commit_trade` :959, and the reconciler freeze at :2602 / :2613.
- Commits 1ac09296, 9a436c95, and TRADE-HARDEN's 006910b2, 4d6524e5, 8d3325e5 and 6d3da749. All of
  TRADE-HARDEN's work had landed before this review, so it is reviewed below as committed code.
- The client trade paths: `lua/gen2/client.lua` :552-764, `lua/gen1/client.lua` :1817-1952,
  `lua/gen2/trade_overlay.lua`, and `patch/gen2/src/trade_commit.asm` (the result-2 and save ordering).
- `docs/protocol.md` §6 and `tests/unit/protocol_schema.py`.

The failure sequences below were reproduced with a scratch probe against the HEAD `server/state.py`,
using the `tests/unit/test_state.py` fixtures. The probe was not committed. They are marked **[probed]**.

---

## BLOCKER

### BLOCKER-1: `pending_trade` is not persisted, so a restart, rollback or reset during a trade leaves the soul link crossed without any warning  [probed]

- **Where:** `state.py:308` (in memory only), `_save` :3492-3565 (no `pending_trade` or `_trade_token`),
  `load` :1000. Also `server.py` `handle_rollback_api` / `handle_reset_api` (~:4380-4440), which build a
  fresh state.
- **Sequence:**
  1. The trade A:1 <-> B:2 reaches `applying`, and `apply_trade` goes to both players.
  2. The server restarts, or an admin rolls back, before both `trade_done` reports are processed. The
     clients hold their `trade_done` while disconnected and send it after the next hello.
  3. After the reload `pending_trade is None`, so `_handle_trade_done` :840 drops both reports. The link
     still reads `a=A:1, b=B:2`, but A physically holds B:2 and B holds A:1. `hello` rebuilds
     `party_keys` from the parties (:1238), so nothing looks wrong.
  4. A's B:2 faints. `_propagate_faint(a, entry)` treats `entry.a` (A:1) as A's mon. It queues
     `force_faint B:2` to **B**, which does not hold B:2, and `memorialize A:1` to **A**, which does not
     hold A:1. B's A:1, the real partner, survives.

  Probe output: B received `force_faint B:2` and `memorialize B:2`, and A received `memorialize A:1`.
  O-24 (`_repair_lost_faints`) looks mons up by key, so it eventually re-faints B's A:1. That repair
  depends only on the key, never on who holds the mon. With a trade evolution (the Haunter/Machoke/
  Kadabra/Graveler family, or a Gen 2 item evolution), the received mon's new key is in no index at all.
  Its faint is then "no alive linked entry — ignored" (:1939), and the partner stays alive for good.
- **Why it matters now:** a `conflict` shows "Trade conflict — needs admin" (`_board.html:94-104`), but no
  admin action exists (see MAJOR-3). A restart is therefore the only way to clear it, and a restart
  is the trigger for this bug.
- **Fix:**
  1. In `_save`, persist `pending_trade` when its phase is `applying`, `uncertain` or `conflict`. Store the
     link as its index in `self.links`, not as the object. Also persist `_trade_token`.
  2. In `load`, restore that trade. Map phase `applying` to `uncertain`, set every `None` verdict to
     `"await"`, and journal it once. The post-restart hello already feeds `_trade_evidence`.
  3. Call `_save()` at the end of `_execute_trade`, before `apply_trade` can leave, and when
     `_settle_trade` rolls back or conflicts, so that the persisted trade is cleared.
  4. The `menu`, `choosing` and `confirming` phases may still be dropped on restart, because nothing has
     been applied yet.
- **Red test:** drive to `applying`, `_save()`, `SoulLinkState.load()`, then send both `trade_done`
  reports. Assert that the link swapped, or that it is surfaced as uncertain. Neither happens today.

---

## MAJOR

### MAJOR-1: `apply_trade` goes to both cartridges at once, so a failure on one side after the other commits duplicates a mon  [probed for the server half]

- **Where:** `_execute_trade` :815-826 queues both `apply_trade` commands in one step.
  `_handle_menu_result` :767-777 honours an initiator withdrawal only while the phase is `confirming`.
- **Sequences.** Each one ends with one side committed (and saved by `SaveAfterLinkTrade`) and the other
  side unchanged. The result is a duplicated mon plus a lost mon, and the server correctly reports
  `conflict`.
  1. **Withdrawal race.** B answers YES while A's `SLINK_TRADE_APPLY_FRAMES` (3600) wait is expiring.
     B's `menu_result{1}` arrives first, the phase becomes `applying`, and A's withdrawal (4d6524e5) is
     then ignored (probe: `phase applying, verdict {a: None, b: None}`). A's client has already cleared
     its visit, so `trade_apply` returns `nothing_changed` and A's verdict is `none`. B picks up its
     APPLY and commits, so B's verdict is `traded`.
  2. **Responder drops out between YES and APPLY.** B resets, the link drops, or B presses B during the
     silent WaitApply. The asm review MINOR-3 notes that a player may press B because the map is frozen
     and silent. B's `trade_forget` owes nothing (st=nil, and the responder visit has no
     `server_token`), and a later `apply_trade` finds B closed. A commits anyway.
  3. **Asymmetric precommit refusal.** Each cartridge validates only its incoming mon at APPLY
     (`SlinkTradeCheckIncoming`). A refusal on one side after the other side commits has the same
     outcome.
- **Fix:** add a prepare round that needs only client and server changes, no asm:
  1. The server enters `preparing` and sends `apply_prepare{token, old_key, slot}` to both sides.
  2. Each client replies `apply_ready{token, ok}`. It is ok only if the visit is accepted,
     `slot == visit.slot`, and `not trade:closed()`. These are the checks `trade_apply` already makes,
     moved ahead of either commit.
  3. The server sends `apply_trade` to both sides only when both answered ok. Otherwise it cancels both,
     and nothing has been staged.
  4. The one remaining window is a single delivery latency, well inside the 3600-frame wait.
  5. Separately, record an initiator withdrawal that arrives in `applying` as that side's verdict
     `none` (see MINOR-7).
- **Test gap:** `test_only_the_initiator_can_withdraw_and_only_with_the_offer_token` asserts that the
  withdrawal is ignored once the phase is `applying`. It pins down the race rather than guarding against
  it.

### MAJOR-2: faint and box events that name a pending-trade key go to the wrong player while the trade is one-sided  [probed]

- **Where:** `_handle_faint` :1924, `_handle_party_to_box` :2296 and `_handle_box_to_party` :2344 choose
  the half by `player_id`, but the link is only swapped at `_commit_trade`. `_commit_trade` :959 never
  checks `entry.status`.
- **Sequence:**
  1. A reports `traded` (A now holds B:2), and B declares `uncertain` or stays silent. The window can
     last 17 minutes or more. It lasts indefinitely if B does not reconnect.
  2. A's B:2 faints. B receives `force_faint B:2` (a key it does not hold) and A receives
     `memorialize A:1` (probe Q2).
  3. A deposits B:2, and B receives `box_mon B:2` (probe Q1).
  4. With a trade evolution, A's received mon has the key B:3. Its faint is ignored as unlinked. After
     B settles, the link commits as ALIVE with the fainted B:3 in it. O-24 skips ALIVE links, so the
     partner never dies (probe P6: `ALIVE B:3 A:1`).
- **Fix:** while a trade is in `applying`, `uncertain` or `conflict`, buffer the events that name
  `a_key`, `b_key`, `new[*]`, or an unindexed key with the partner's OT on a side whose verdict is
  `traded`. Store them in `pt["held_events"]` and replay them through `handle_event` after the trade
  commits or rolls back. Also refuse to commit into a link that is no longer ALIVE without first
  re-deriving its death owners. In practice, replaying the buffered faint after the swap does this.

### MAJOR-3: a `conflict`, or an `uncertain` side that never reports, blocks trading for the rest of the run, and nobody can resolve it  [probed]

- **Where:** `_tick_pending_trade` :585 returns early for `uncertain` and `conflict`.
  `_handle_trade_request` :614, `_handle_trade_query` :639 and `_handle_trade_offer` :648 all need
  `pending_trade is None`. No server endpoint clears the trade. `_board.html:103` says "needs admin".
- **Sequence:** any conflict, such as one from MAJOR-1. After 10,000 more events the trade is still in
  `conflict`, every `trade_query` is answered `mask 0`, and trading is disabled for the rest of the run.
  The two trade keys also stay frozen from drift reconciliation for good (:2615).
- **Fix:** add a token-guarded admin action, `POST /api/trade/resolve {token, action}`. It supports:
  - `rollback`: clear the slot and leave the link alone.
  - `commit`: swap using the evidence keys.
  - `adopt`: re-point the halves to whichever player's party now holds each key.

  Each action journals `trade_resolved`. Together with BLOCKER-1, a restart then stops being the escape
  hatch.

### MAJOR-4 (Gen 1): an APPLY that has been armed but not picked up can commit after the server has already settled the trade  [probed for the server half]

- **Where:** `lua/gen1/client.lua` `trade_apply` :1850-1869 and `trade_tick` :1892-1900 have no pickup
  timeout and no withdrawal. The Gen 1 cartridge picks up APPLY on any overworld frame
  (`patch/gen1/src/trade_service.asm` `SlinkForeground`). The server watchdog (:588-603) and
  `_trade_evidence` treat a snapshot taken before pickup as final.
- **Sequence:**
  1. Both `apply_trade` commands are armed. A sits in the START menu or a long battle, and B idles.
  2. Neither side has picked up after 4,000 events, about 17 minutes. The watchdog sets both verdicts to
     `await`.
  3. The next ticks show each side still holding its own mon, so both verdicts are `none` and the trade
     is `rolled_back`. `pending_trade` becomes None and both players see "Trade did not go through."
  4. Both players return to the overworld, and their cartridges pick up the still-armed APPLY and trade.
  5. The `trade_done` reports are ignored because the trade is None (probe P3: the link is still
     `A:1 B:2`). The link is now crossed exactly as in BLOCKER-1, and no warning is shown.
- **Fix:** gen-neutral. When the watchdog fires, it should not set a verdict to `await` by itself.
  Instead:
  1. It queues `withdraw_trade{token}` to each silent side.
  2. That client withdraws an unpicked lease and answers `trade_done` with the old key, which is a
     definite `none`.
  3. If the client is past its commit latch, it answers `trade_done{uncertain}`.
  4. Only a client that stays silent after the withdrawal gets `await`.
  5. Gen 1 also needs the withdrawal handler. Gen 2 already bounds pickup with `TRADE_PICKUP_FRAMES`.

### MAJOR-5 (Gen 2): a native result 2 settles from the RAM party before any save, even though the reset that follows restores the save

- **Where:** `lua/gen2/client.lua:719-724` declares `trade_uncertain` right away on `done.result == 2`.
  `patch/gen2/src/trade_commit.asm` jumps to `.uncertain` only before `farcall SaveAfterLinkTrade`, and
  the asm review MINOR-2 says the result-2 hold never exits, so a reset is required.
  `_trade_evidence` :872 reads the next tick's party.
- **Sequence:**
  1. B's append fails the species check, so the cartridge returns result 2 without saving.
  2. The declaration arrives, and the next tick, taken while the cartridge is still soft-locked, shows
     RAM after RemoveMon. Either both mons are missing (a sticky "holds NEITHER" conflict) or a mismatched
     appended mon is present. The family fallback can accept that mon, which gives verdict `traded`.
  3. The player resets. The save still holds the pre-trade party, so B has kept B:2, but the server has
     already committed or conflicted from a RAM state that was never saved.
  4. Both sides failing the same way should be a clean `rolled_back`, and is not.
- **Fix:** on result 2, do not declare. Show the "reset" text and let the reset boundary's
  `trade_forget` (:674-679, where `committing` is already true) owe the uncertain report after the
  post-reset hello. Alternatively, have the client send `uncertain:true, hold:true`. The server would
  journal it but take evidence only from the next `hello`. Gen 1 result 2 (`.unreachableAppendFailure`)
  needs the same treatment.

---

## MINOR

- **MINOR-1: `trade_done.new_key` is taken on trust** (:865-869, :971-982) **[probed].** Any key that
  differs from the side's own old key is committed and indexed as-is. A report that carries another
  live link's key (A:9) overwrites `_key_index["A:9"]`, which then points at the traded link (probe P2).
  **Fix:** accept `new_key` only if it equals `gets`, or if it is an unindexed key with the same OT and
  family as `gets` (the rule `_trade_evidence` already uses). Anything else becomes a conflict reason.
- **MINOR-2: a forget before the commit reports nothing, so the trade waits out the 17-minute
  watchdog.** Gen 2's `trade_forget` :674-679, for an APPLY that is armed and uncommitted at a reset or
  reload, and Gen 1's `trade_forget` :1882-1886 both clear their state without sending anything. A
  `trade_done` that was held while offline and then dropped by `drop_held` at a boundary is lost too.
  Until the watchdog fires, the phase stays `applying`, which turns off `_reconcile_party_keys`,
  including O-24 faint repair (:2602), for **both** players. **Fix:** a forget before the commit sends
  `trade_done` with the old key (certain `none`), and a held `trade_done` that gets dropped becomes an
  owed `uncertain`.
- **MINOR-3: the withdrawal reuses `menu_result` choice 0, which in the `menu` phase means TRADE**
  (:769-777) **[probed].** In the Gen 3 server-driven flow, a duplicate or replayed initiator
  `menu_result{choice 0}` that arrives during `confirming` now cancels the offer (probe P5). The
  per-connection seq guard (`server.py:1456-1467`) does not cover a resend across a reconnect.
  **Fix:** accept the withdrawal only when `self.adapter.native_trade_ui()`, or use a separate field
  (`withdraw: true`).
- **MINOR-4: trade tokens start again at `t1` after a restart** (:309, :616). The `trade_<outcome>`
  journal is keyed by token (`server.py:_journal_trade`), so it gets duplicate keys across restarts. An
  owed Gen 2 withdrawal from before the restart (`trade_owed`) could also cancel a new `t1` that is
  still `confirming`. **Fix:** persist `_trade_token` (BLOCKER-1), or prefix tokens with a nonce taken
  at startup.
- **MINOR-5: the watchdog measures events, not time** (:576, :587). With both players connected, 4,000
  events is about 17 minutes (ticks every 30 frames). With one player connected it is about 33 minutes,
  and Gen 3 `ghost_pos` traffic shortens it. For `applying` this never produces a false commit: the
  watchdog only moves to `uncertain`, and evidence is read from the party in the message itself. The
  only stale-evidence routes are MAJOR-4 and MAJOR-5. The cost is the long window in which
  reconciliation is suppressed (MINOR-2). **Fix:** use `time.monotonic()` with the event count kept as
  a floor. About 3 minutes is enough once MAJOR-4's withdrawal exists.
- **MINOR-6: `_commit_trade` leaves some per-key bookkeeping on the old player.** `bonus_keys`
  (shiny-pair dedup), `mon_stats` under a pre-evolution key, and `pending_bonus` stay attached to the
  old side. `partner_blobs` is fixed by the next tick. Evolution keys also skip the loud collision log
  in `_index_entry`, because :981-982 write `_key_index` directly.
- **MINOR-7: an initiator withdrawal during `applying` is discarded.** `_handle_menu_result` :767 only
  handles `confirming`. The Gen 2 client withdraws only when it never armed an APPLY (`not st and
  visit.server_token and closed`, :742-745), so the message is a definite A=`none`. Recording it lets
  the server report the resulting conflict at once instead of after the watchdog.

## NIT

- `docs/protocol.md:343` and `:395`, and the `_execute_trade` docstring at `state.py:795`, still say the
  watchdog "force-completes" or "force-commit"s. Since 1ac09296 it moves the trade to `uncertain`.
- `_handle_trade_done` :845 accepts an empty token "for compat". The Gen 1 and Gen 2 clients always
  echo the token, but Gen 3 sends `token or ""` (`gen3_frlge_client.lua:681`). A stale Gen 3 report
  with no token would therefore count toward whatever trade is in flight. Make Gen 3 always echo the
  token, then remove the compat path.
- `trade_owed` is a single slot in both clients (`lua/gen2/client.lua:605,672`,
  `lua/gen1/client.lua:1878`), so a second owed message overwrites the first.
- The `_trade_evidence` descendant fallback matches on OT and family. If both players happen to share
  an OT ID (about 1 in 65,536), an unlinked mon of the same family makes a trade that did happen read
  as "several candidates", which is a conflict. That is acceptable, but worth noting.
- The trade state machine allows a C<->G trade. That matches vanilla, but only the C<->C and G<->S trade
  lanes have receipts (O-16). Record it as a known limit or add a receipt.

## WIP (working tree at review time)

`git diff -- server/state.py lua/gen1/client.lua` is empty, because TRADE-HARDEN's work is committed and
is reviewed above. The remaining `lua/gen2/client.lua` diff belongs to FAINT-FIX (O-30 battle-hold and
faint work) and touches no trade code. One interaction matters: that diff now **defers** a
`force_faint` whose key is not in the party instead of dropping it. A trade-key death sent to the wrong
player under MAJOR-2 (`force_faint B:2` to B, which does not hold it) therefore stays in B's deferred
queue until the checkpoint drops it, instead of disappearing at once. That is harmless on its own, but
it is another reason to buffer those events on the server (the MAJOR-2 fix). The WIP makes no BLOCKER
worse, so TRADE-HARDEN was not messaged.

## Verified OK

- The link is changed only in `_commit_trade`, only after both verdicts are `traded`. Both `none` rolls
  back, and anything else is a sticky conflict. No path guesses the outcome.
- The `applying` watchdog never invents an outcome. It moves only silent sides to `await` and journals
  only when it moves one, so a side that declared itself is not journaled twice (006910b2).
- Token checks: a `trade_done` with a wrong token is ignored, a repeated report after a side's verdict
  is set is ignored, and reports after commit or rollback are ignored.
- A single trade slot prevents two trades running at once. A second offer while one is pending gets
  `ok:false`, and the query mask is 0 while busy.
- The offer guard refuses a trade if either player would receive a key it already holds, which matters
  for Gen 1 DV:OT:species keys. `_execute_trade` checks again that the link is ALIVE and each key is in
  its owner's party, and for the native path that neither key is in the other player's party.
- Reconciler: it is off during `applying`, the two trade keys are frozen during `uncertain` and
  `conflict`, and 12 settle ticks follow a commit.
- A `key_change` during a pending trade moves the trade's `a_key` / `b_key`, updates the correct half by
  key rather than by side, and `_key_refs` counts `pending_trade`.
- Evidence: an empty party is ignored, and only a snapshot after a side is declared counts (a mid-scene
  tick is not evidence). A descendant must share the OT and family, be unindexed, and be the only
  candidate. The Gen 2 trade and item evolutions (Politoed, Slowking, Steelix, Kingdra, Scizor,
  Porygon2, Alakazam, Machamp, Golem, Gengar) map to their base family in `Gen2Adapter.evo_family`
  (checked directly).
- Initiator withdrawal before the YES (006910b2): it cancels the offer and tells both players, only the
  initiator can do it, it needs the offer token, and the initiator cannot accept its own offer.
- Gen 2 client:
  - APPLY is refused unless the visit was accepted, the slot matches the visit, and the cartridge has
    not closed.
  - An APPLY that is never picked up is withdrawn after 1,800 frames and reported with the old key.
  - The `SlinkTradeCommit` latch separates a refusal before the commit from an uncertain commit.
  - Reset, reload and savestate load all go through `trade_forget`.
- Gen 1 client: the commit latch is set on RemovePokemon after every `.refused` check (8d3325e5), and
  WRAM clear goes through `trade_forget`. Gen 1 needs no offer withdrawal because its proposer picks up
  APPLY while roaming, so ignoring the ack token is correct.
- O-24 repair is keyed by mon, not by player, so it partly repairs an unevolved death sent to the wrong
  player after the fact. It does not cover evolved keys (MAJOR-2).
- The dupes clause checks both halves of each link, so the swap cannot open a clause hole.
- `protocol_schema.py` accepts the uncertain `trade_done` shape and the ack `token`, matching the
  clients.

## Test coverage per question

| Question | Test that can go red today | Gap |
|---|---|---|
| Mon in both parties or neither | `test_duplicate_is_a_sticky_surfaced_conflict`, `test_neither_half_present_is_a_conflict`, `test_one_side_refused_other_traded_is_a_conflict_not_a_commit` | Nothing prevents the duplicate (MAJOR-1); no prepare-round test |
| Restart mid-trade | none | BLOCKER-1: save, load, report |
| Watchdog | `test_watchdog_never_fabricates_...`, `test_state_trade_watchdog.py` | Armed APPLY picked up after rollback (MAJOR-4); time vs events |
| Stale evidence | `test_declared_uncertain_side_is_settled_by_its_next_snapshot` (mid-scene tick ignored) | Result-2 RAM before the save (MAJOR-5) |
| Key collision / evolution | `test_offer_refuses_incoming_key_collision_without_mutation`, `test_gen1_trade_evolution_is_recognised_from_the_snapshot`, `test_gen1_unrelated_new_mon_is_not_a_descendant` | `trade_done` carrying an arbitrary key (MINOR-1); no Gen 2 evolution-by-evidence case |
| Soul Link during a pending trade | `test_uncertain_trade_freezes_reconcile_for_its_keys` | Faint or deposit of a trade key during the one-sided window (MAJOR-2) |
| Duplicate or reordered events | `test_late_duplicate_trade_done_is_not_hidden_...` (oracle), replay guards | Gen 3 duplicate `menu_result{0}` in `confirming` (MINOR-3) |
| Conflict recovery | none | MAJOR-3: no action exists to test |
| Gen 1 parity | `test_state_gen1_trade.py` (8 cases) | Gen 1 pickup timeout and withdrawal (MAJOR-4) |
