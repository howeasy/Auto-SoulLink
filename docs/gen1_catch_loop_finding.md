# Gen 1 catch loop — solved

Status: **root-caused and fixed.** Four separate bugs, each hiding the next. All three
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
* Species forcing via `wGrassMons` does not work and four hypotheses for why are recorded
  dead in `lua/tests/probe_gen1_wildtable.lua`. Neither scenario needs it; Route 1 holds only
  PIDGEY and RATTATA, so both sides converge on a shared species naturally.
