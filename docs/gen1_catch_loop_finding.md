# Gen 1 catch loop — root cause found, fix half-applied

Status: **deadzone (B half) and dupes are xfail.** This is the note for whoever picks them up.

## What is broken

The catch loop reports every throw as a failure, then flails and ends the battle.

Symptom as seen from outside: over 18 hunts the B instance spent 33 balls and caught
nothing — about 1.8 balls per battle against a per-battle cap of 30. It looks exactly like
bad catch luck. It is not.

## Root cause

`H.throw()` (`lua/tests/duo/gen1_hunt.lua`) presses A twice to use the ball, then polls for
the bag count to drop **while pressing nothing**.

Gen 1 blocks on the "Aww! It appeared to be caught!" text box waiting for input, and only
decrements the bag in `RemoveItemFromInventory` at the *end* of the ball routine. With the
poll idle, the game never advances past that text, so the count never drops inside the
window. It drops later — when the **caller's** corrective `B` presses dismiss the text.

So each attempt was finishing the *previous* attempt's throw. `throw()` returned false every
time, the caller treated a success as a failure and fired corrective presses, and the menu
cursor eventually landed on RUN — ending the battle with both mons alive.

## The evidence that settled it

A single-instance probe logging state after every attempt:

```
attempt 1: throw() false — in_battle=1 ourHP=20/20 enemyHP=15 balls=60
attempt 2: throw() false — in_battle=1 ourHP=17/20 enemyHP=15 balls=59
attempt 3: throw() false — in_battle=1 ourHP=14/20 enemyHP=15 balls=58
attempt 4: throw() false — in_battle=1 ourHP=11/20 enemyHP=15 balls=57
```

Balls fall **exactly one per attempt**. Our HP falls 3 per attempt (the wild mon is taking
its turn). Enemy HP never moves (we never attack). That combination is only possible if the
throws are landing and the detection is missing them.

## The fix, and the trap

**Do:** press `B` inside `throw()`'s wait loop instead of idling, and return as soon as
`BAG_QTY0` drops. This took detected throws from **0 to 2** — the first time any were
counted.

**Do not:** stop the over-pressing by gating the loop on `wMaxMenuItem == 1`. That variant
regressed to **0 throws**, because `wMaxMenuItem` reads 1 in states other than an
interactive battle menu, so the loop bails before the ball is consumed.

The open question is what still ends the battle after ~2 throws once detection works.

## Rebuilding the probe

The probe was scratch and is not committed (a bad string-replace corrupted it and it was
deleted). It is worth recreating, because one dump is what cracked this after several rounds
of guessing:

1. Boot the `battle` fixture (Route 1) via `gen1_gatelib`.
2. `M.write_u8(M.BAG_ITEMS_ADDR + 1, 60)` so the loop is never ball-limited.
3. Walk east-west until `wIsInBattle ~= 0` (never north-south: Route 1's ledges are one-way
   and drop you into Pallet Town, which has grass tiles but encounter rate 0).
4. Run the catch loop, and after **every** attempt log
   `in_battle / our HP / enemy HP / balls / wMaxMenuItem / wCurrentMenuItem`.
5. Classify the ending: our HP 0 = we fainted; enemy HP 0 = we KO'd it; both alive = fled or
   ran.

## Related, already fixed

* `wait_for_menu` must test **before** pressing — an A at a live battle menu confirms FIGHT,
  and a level-5 starter one-shots a level-3 wild mon.
* Never press a direction unless `wIsInBattle` is nonzero — outside battle they are movement.
* Species forcing via `wGrassMons` does not work and four hypotheses for why are recorded
  dead in the commit history. Neither scenario needs it; Route 1 holds only PIDGEY and
  RATTATA, so both sides converge on a shared species naturally.
