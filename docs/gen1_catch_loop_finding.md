# Gen 1 catch loop — solved

**Note (P8-6b):** `lua/tests/probe_gen1_catchloop.lua` and `lua/tests/probe_gen1_wildtable.lua`,
referenced below, were one-off discovery probes deleted once their findings landed here
(`9aa7989`, per `lua/tests/README.md`'s "one-off discovery probes are DELETED once their
findings land" convention). The finding this file documents still stands; the runnable
equivalent today is the rewritten client's `gen1_new` duo scenarios
(`tools/e2e_duo.py --game gen1_new`), which exercise the same catch loop end to end.

Status: **root-caused and fixed.** Four separate bugs, each hiding the next. All four
were found by instrumentation, not by hypothesis — the probe that found them is committed
at `lua/tests/probe_gen1_catchloop.lua` so the next person does not have to rebuild it.

Symptom as seen from outside: over 18 hunts the B instance spent 33 balls and caught
nothing — about 1.8 balls per battle against a per-battle cap of 30. It looked exactly like
bad catch luck. It was four bugs.

## Bug 1 — the throw was never detected

`H.throw()` pressed A twice to use the ball, then polled for the bag count to drop **while
pressing nothing**.

Gen 1 blocks on the "Aww! It appeared to be caught!" text box waiting for input, and only
decrements the bag in `RemoveItemFromInventory` at the *end* of the ball routine. With the
poll idle the game never advanced past that text, so the count never dropped inside the
window. It dropped later, when the **caller's** corrective `B` presses dismissed the text.

So each attempt was finishing the *previous* attempt's throw. `throw()` returned false every
time and the caller treated a success as a failure.

**Fix:** press `B` inside the wait loop. Detected throws went 0 → 7.

## Bug 2 — half of every attempt budget was discarded

`H.left_column(row)` was a blind `Left / Up / (Down)` that assumed `Up` always lands on
row 0. Each column is a **two-item wrapping menu**: `Up` from row 0 wraps to row 1, and the
following `Down` wraps straight back to row 0. So whenever the cursor already sat on the row
we wanted, it returned the *other* row while reporting success.

In the probe this showed as a perfect alternation — attempts 1, 3, 5, 7… threw a ball, and
2, 4, 6, 8… failed with "could not reach ITEM", every failing attempt logging `curMenu=0`.

**This is worse than wasteful in `kill` mode.** `H.fight()` calls `left_column(0)`, so a
cursor starting on ITEM ends on ITEM and the following `A` opens the bag. A ball leaving the
bag during a kill hunt is exactly what the dead-zone scenario must never do, and what its
own guard exists to catch.

**Fix:** drive the cursor by *reading* `wCurrentMenuItem` instead of counting presses.

## Bug 3 — our mon faints, and the loop never notices

This is the one that produced the "1.8 balls per battle" number.

The fixture carries a level-5 starter with 20 max HP. A Route 1 Pidgey does ~3 damage a
turn. 20 / 3 ≈ 7 turns — and the probe measured exactly that:

```
attempt 11 post   our=5/20  balls=54
attempt 13 post   our=2/20  balls=53
attempt 15 post   our=0/20  balls=53   result 0x00 -> 0x01
```

After HP hits 0 the battle menu never returns, every remaining attempt fails to reach ITEM,
and the loop burns its whole budget on a dead mon. `wNumRunAttempts` and
`wEscapedFromBattle` both stayed **0** throughout, which is what finally ruled out the
long-standing "the cursor lands on RUN" suspicion.

The earlier round had this evidence and did not use it — its own dump recorded "our HP falls
3 per attempt" without connecting it to the 20 HP total.

**Fix:** `H.keep_alive()` tops the active battler up during a catch hunt. This is
scaffolding of the same kind as `H.stock_balls()` — the rules under test are the dead zone
and the species clause, not whether a Squirtle can outlast a Pidgey.

It **must write the battle struct**, not the party struct. `MainInBattleLoop` opens every
turn with `ReadPlayerMonCurHPAndStatus`, which copies `wBattleMonHP` *into* the party struct
(`pokered engine/battle/core.asm:280`, `:1798-1809`), so a party-only write is erased before
the next turn. This is the same reason `force_faint` had to move to the battle struct.

## Bug 4 — the cursor was pressed at a text box, forever

Fixing bugs 1-3 made Red catch in two throws and left **Blue** throwing exactly one ball
and then failing 59 consecutive times with "could not reach ITEM". Same code, same item
(0x04), different cartridge — which is what made it look cartridge-specific.

It is not. `wait_for_menu` accepts `wMaxMenuItem == 1`, and that reads 1 in states which
are **not an interactive battle menu** — the file already said so. So after a throw the
game can still be holding a text box, and a text box ignores `Down` entirely. `left_column`
pressed `Down` at it forever. Red happened to slip past the window; Blue did not.

**Fix:** verify the cursor actually moved. If `Down` does not change `wCurrentMenuItem`,
we are not on a live menu — press `B` to advance the text, then retry.

Measured on Blue, before and after:

```
before   1 throw  / 60 attempts   (59 x "could not reach ITEM")
after    4 throws /  4 attempts   -> CAUGHT IT
```

## Result

With all four applied, the probe catches a Pidgey in **3 attempts / 2 throws**:

```
[probe] VERDICT: CAUGHT IT after 3 attempts / 2 detected throws
final   in_battle=0 our=16/20 enemy=15 balls=58 party=2 result=0x02
```

## Rebuilding or extending the probe

```bash
python tools/run_gb_gate.py lua/tests/probe_gen1_catchloop.lua --rom red --target battle
```

It boots the `battle` fixture, stocks 60 balls, walks Route 1 east-west until a wild battle
starts, then logs `in_battle / our HP / enemy HP / balls / party / maxMenu / curMenu /
wNumRunAttempts / wEscapedFromBattle / wBattleResult` **after every attempt** and classifies
the ending. It is deliberately not a gate: it asserts almost nothing and always finishes
PASS. Its output is the dump.

Walk east-west only. Route 1's ledges are one-way and run horizontally, so Up/Down pacing
eventually hops one southward into Pallet Town, which has grass tiles and encounter rate 0 —
that reads as endless bad luck rather than as a bug.

## Related, already fixed

* `wait_for_menu` must test **before** pressing — an A at a live battle menu confirms FIGHT,
  and a level-5 starter one-shots a level-3 wild mon.
* Never press a direction unless `wIsInBattle` is nonzero — outside battle they are movement.
* Species forcing via `wGrassMons` **does** work — see `lua/tests/probe_gen1_wildtable.lua`.
  It was believed broken for four rounds because that probe cleared a pre-existing battle by
  mashing `B`, and `B` does not flee a wild battle in Gen 1. Its clear silently failed, so
  every measurement described a species latched before the write. One of the four hypotheses
  it recorded dead was literally "leftover boot battle", which was the right answer.

## Resolved: the duo `deadzone` B half

The catch loop itself is fixed and proven — standalone, the probe catches on both
cartridges. The duo B half still fails, and the cause is now **measured rather than
suspected**, which is the part worth writing down.

B *is* catching. Per run: 11–13 `capture(battle)` events sent, each answered by the
server with `force_faint`, and the hunt's own watcher reports

```
max_party_seen=3, party_now=2      x22 of 24 hunts
```

So the party genuinely gains the mon and is back to its original size before
`H.throw()` even returns. The dead-zone rule is working *correctly* — the server
force-faints the illegal capture and memorialises it — and the harness reports that
correct enforcement as "it got away".

**Why every latch so far has missed it.** Two independent windows, both short:

* `wPartyCount` is incremented **before** the mon's struct is written, so a read taken
  on the frame the count rises returns nil or a zeroed struct. This file already knew
  that — it is why the post-battle path waits for the overworld before reading.
* By the time `throw()` returns, the server round-trip has completed and the mon is
  gone.

**The recommendation is to stop polling RAM for this.** The harness is trying to
observe a transient that the server is designed to erase, and every fix in that
direction is a race with a shrinking window. The scenario already has a
non-racy source of truth: the **server**. `H.wait_retired()` and
`assert_dead_zone_refusal` already query it. B's success signal should be "the server
recorded a capture for B in route_1 and then retired it", not "did the party grow".

That is a change to `scenario_gen1_deadzone.lua`, not to `gen1_hunt.lua` — and it is
what fixed it.

**The fix: assert on the durable consequence, not the transient.** A retired capture
ends up in the memorial box, and the memorial box does not un-grow. A ball leaving the
bag proves a real throw happened; the memorial box growing proves the server took the
catch away. Together that is exactly the rule under test, and neither signal can be
raced.

`deadzone` now passes, both halves, twice in a row:

```
A  RESULT: PASS (failed the encounter in route_1)
B  THREW 40 ball(s) in a DEAD area (max_party_seen=3)
B  REFUSED <retired before we could read it> (memorialized)
B  RESULT: PASS (dead-zone refusal via memorialized)
```

Note what B's log says: it never managed to read the mon it caught. That is fine, and
it is the point — the scenario no longer needs to.

`dupes` passes now too. It was `xfail` here for an unrelated reason, and the three things
that actually blocked it — a fixture standing in grass, a `BIT_NO_BATTLES` write that had to
be re-asserted every frame, and a `prove_booted` whose two round trips set off in opposite
directions into a wall — are written up in `tests/e2e/test_duo_gen1.py` beside the (now
empty) `KNOWN_FAILING` table.
