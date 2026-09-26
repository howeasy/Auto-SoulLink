# Gen 2 in-battle faint: SOURCE facts (O-30, card gen2-inbattle-faint)

Phase 1 of the card: facts only, no code. Evidence level SOURCE. Sources are the pinned decomps:
`.cache/gen2-build/pokecrystal` @ 7a7881d and `.cache/gen2-build/pokegold` @ 656583c. Addresses
come from their `.sym` files, and the call bytes were read back from the built `.gbc` files.
Nothing here is PHYSICAL until the U1/U2 receipts in phase 4.

## 1. There is no Gen 1-style loop head in Gen 2

Gen 1's `MainInBattleLoop+0` tests `wBattleMonHP` and jumps straight to `HandlePlayerMonFainted`.
Gen 2's `BattleTurn.loop` (C 0f:412f, G/S 0f:4121) has no HP test:

- It runs `CheckContestBattleOver`, clears the per-turn flags, and calls `HandleBerserkGene`,
  `UpdateBattleMonInParty` and `AIChooseMove`.
- Then comes `CheckPlayerLockedIn`, then `BattleMenu`/`ParsePlayerAction`.

So a write of HP 0 at `BattleTurn.loop` hands the player a menu for a 0-HP mon. FIGHT would then run
the corpse's move through `DoTurn`. Nothing checks faints until the turn resolves. **`BattleTurn.loop`
is the wrong site.**

## 2. Proposed site: `call DetermineMoveOrder` inside BattleTurn

| title | site (bank:addr) | bytes |
|---|---|---|
| Crystal | 0f:4194 | `CD 14 43` (call DetermineMoveOrder) |
| Gold | 0f:4168 | `CD CB 42` |
| Silver | 0f:4168 | `CD CB 42` |

Crystal's calls around it: `ParsePlayerAction` 418a, `EnemyTriesToFlee` 418f, **`DetermineMoveOrder`
4194**, `Battle_EnemyFirst` 4199, `Battle_PlayerFirst` 419e. G/S have the same sequence at
415e/4163/**4168**/416d/4172.

What holds when execution reaches the site:

- The player has committed this turn's action (`ParsePlayerAction` returned z).
- A PKMN switch or an item has already run inside `BattleMenu`: `TryPlayerSwitch` → `PlayerSwitch` →
  `BattleMonEntrance` (core.asm:5156-5215). So `wCurBattleMon` names the mon actually on the field.
- The wild foe has had its flee roll (`EnemyTriesToFlee`) with its HP intact.
- Move order is not decided yet.

### The write set (W-2 equivalent)

1. `wBattleMonHP` := 0 (C $C63C, G/S $CB1C, WRAM0).
2. `wBattlePlayerAction` := `BATTLEPLAYERACTION_USEITEM` (1) (C $D0EC in WRAMX bank 1, G/S $CFE4).
3. Party mirror: `wPartyMon<n>HP` := 0 and Status := 0 for `n = wCurBattleMon`. This is Gen 1 parity.
   The engine would mirror it anyway (see step 5).

### Why the native faint sequence follows

1. `DetermineMoveOrder.use_move`: `wBattlePlayerAction != 0` → `.player_first` (core.asm, `jp nz, .player_first`).
2. `Battle_PlayerFirst` first runs the foe's `AI_SwitchOrTryItem`, then
   `PlayerTurn_EndOpponentProtectEndureDestinyBond` → `DoPlayerTurn`.
   - `DoPlayerTurn` returns at once because `wBattlePlayerAction != 0`
     (effect_commands.asm `DoPlayerTurn`; same in G/S). **The corpse never acts, and the foe never
     moves this turn.**
3. `HasEnemyFainted` returns nz. `HasPlayerFainted` returns z, so `jp z, HandlePlayerMonFaint`.
4. `HandlePlayerMonFaint` → `FaintYourPokemon` ("<MON> fainted!") → `UpdateFaintedPlayerMon`.
   - `UpdateFaintedPlayerMon` clears the participant flag and `wBattleMonStatus`, and calls
     `UpdateBattleMonInParty`, which copies HP 0 into the party struct (core.asm:2653-2690).
5. `UpdateFaintedPlayerMon` is also where the existing `battle_faint` U1 site sits. The client's own
   faint latch therefore fires and a `faint` for the linked key reaches the server. Gen 1 does the
   same after W-2, so the server must treat it as a repeat of a death it already knows.
6. What follows is native:
   - `CheckPlayerPartyForFitMon`. When none is fit: `LostBattle`.
   - Otherwise, in a wild battle, `AskUseNextPokemon` ("Use next #MON?"). In a trainer battle,
     `ForcePlayerMonChoice`.
   - `HandlePlayerMonFaint.switch` stores this same `BATTLEPLAYERACTION_USEITEM` itself before
     `DoubleSwitch`. So a USEITEM value that skips the player's move is engine precedent, not invented.

**`CANNOT_MOVE` is not needed.** Gen 2 does have it: `BattleCommand_CheckTurn` sends
`BATTLE_VARS_MOVE == $FF` to `EndTurn`. But `DoTurn` is never reached here. Using `CANNOT_MOVE`
*instead of* the action byte would be worse:

- `CompareMovePriority` would read the priority of move $FF.
- The foe would move first. Foe-first opens a revive window: an enemy Present can heal the target,
  and Pain Split averages HP.

### The last mon

The native whiteout runs:

- `HandlePlayerMonFaint` → `CheckPlayerPartyForFitMon` d=0 → `LostBattle`.
  `LostBattle` sets `wBattleEnded`, and `wBattleResult` becomes LOSE in `UpdateFaintedPlayerMon`.
- The map script's `reloadmapafterbattle` sees LOSE and runs `Script_BattleWhiteout`
  (engine/overworld/scripting.asm:1174).
- **Trap (pre-existing, not new):** `Script_Whiteout` runs `special HealParty`
  (engine/events/whiteout.asm). It revives every party mon, dead linked mons included. The server's
  whiteout handling has to re-kill them; it already has to for any Gen 2 whiteout today.
- `BATTLETYPE_CANLOSE` (rival battles): `LostBattle` returns early, before `.not_canlose`
  (core.asm:2915-2940). The CANLOSE script path decides what happens next (home/trainers.asm:232).
  Native, and not verified further here.

### Bench faint at the same site

- Writing a non-active slot's party HP 0 and Status 0 is safe between turns. The engine holds no
  pointer into a bench struct at this point, and `UpdateBattleMonInParty` copies only
  `wCurBattleMon`.
- Afterwards, `CheckIfCurPartyMonIsFitToFight` refuses to switch the mon in.
- `GiveExperiencePoints` skips HP 0 (core.asm `GiveExperiencePoints.loop`, `jp z, .next_mon ; fainted`).
- Beat Up skips HP 0 as well.

### Traps at the site

- **SVBK (Crystal only).** `wBattlePlayerAction` $D0EC and every `wPartyMon` field are WRAMX bank 1.
  The write must prove the SVBK bank is 1 (`io.bank_valid`, the recent hello fix). If it isn't,
  skip and retry at the next turn.
  - pokegold uses no `rSVBK` in its `engine/`/`home/` sources, and its WRAMX is fixed bank 1.
- **Battle ends without reaching the site.** A successful RUN, a catch, the foe fleeing, Roar or
  Whirlwind (`wForcedSwitch`), or a KO that ends the battle, all before the player's next committed
  action. The command must then fall to the overworld checkpoint, as in Gen 1 (`battle_end` →
  `defer_held`).
  - The only way to avoid a commit is to end the battle from the menu, so nothing is "held to
    battle end" except by the player leaving.
- **Evolution after the battle REVIVES a fainted mon.**
  - `EvolveAfterBattle` runs from `ExitBattle.HandleEndOfBattle` when the result is WIN. It has no
    HP gate (engine/pokemon/evolve.asm).
  - It adds `newMaxHP - oldMaxHP` to the current HP (evolve.asm:259-289, `wTempMonHP += delta`).
  - So a mon that levelled earlier in the battle (`wEvolvableFlags`) and was then force-fainted
    in that battle comes back with HP > 0 under a NEW key. Gen 2 sends no `key_change` for
    evolution (U1 OPEN).
  - **Every in-battle faint must therefore leave a quiet checkpoint re-zero behind** (Gen 1's
    backstop shape, gen1/client.lua:1083-1087). That re-zero needs the evolution fallback
    (DV+OT → unique descendant). This is phase 2 of the card, and it is now load-bearing.
  - pokered has the same HP-delta add (engine/pokemon/evos_moves.asm:186-198). Gen 1 is covered
    because its proven evolution site sends `key_change`, and `state.py` `_handle_key_change`
    re-queues force_faint + memorialize under the new key for a buried link (A2, ~:2829).
- **Destiny Bond / Perish Song / Spikes.** No trap:
  - Destiny Bond triggers only inside damage application when its user is KO'd by a move. Our
    write is not a move.
  - Perish counters are the engine's own.
  - `CheckFaint_*`'s documented "0 HP and not faint" bug (Perish/Spikes) is a native bug. It is
    not reachable through this site, because the faint check here is `Battle_PlayerFirst`'s
    `HasPlayerFainted`, not `CheckFaint_*`.
- **Transform.** `wBattleMonSpecies` is the foe's species while `SUBSTATUS_TRANSFORMED`
  (`wPlayerSubStatus5`) is set. The slot is still ours. The guard should accept
  "battle species == party species OR transformed", as Gen 1's `active_faint_guard` does. This is
  not an exclusion.
- **Locked-in moves** (Rollout, Outrage, charge, recharge). `CheckPlayerLockedIn` skips only
  `BattleMenu`. `ParsePlayerAction` and the site still run, and the action byte stops the
  locked move.

## 3. Battle kinds (wBattleType; `constants/battle_constants.asm:91-103`)

| kind | BattleTurn runs? | site safe + native faint? | notes |
|---|---|---|---|
| NORMAL (wild / trainer) | yes | **yes** | trainer: forced next-mon choice; wild: "Use next?" |
| CANLOSE (rival) | yes | **yes** | last mon: LostBattle without whiteout (native) |
| FISH, TREE, ROAMING, FORCESHINY, FORCEITEM, TRAP, CELEBI, SUICUNE | yes | **yes** | TRAP/CELEBI only forbid running |
| CONTEST (Bug-Catching) | yes (`ContestBattleMenu` in `BattleMenu`) | **yes** for the lead | see contest trap below |
| TUTORIAL (Dude catch demo) | **no**: `DoBattle.tutorial_debug` jumps to `BattleMenu` and never enters `BattleTurn` | no site | player's party is not on the field (the Dude throws the ball under auto input). Exception candidate: land at the checkpoint seconds later |
| DEBUG | no (same jump) | n/a | not reachable in retail |
| Safari | none in Gen 2 | n/a | |
| Link / Time Capsule (`wLinkMode != 0`) | yes | **REFUSE** | a write desyncs the other Game Boy (the owner's principled exception) |
| Battle Tower (Crystal, `wInBattleTowerBattle` bit) | yes | write lands but **does not persist** | see below |

### Bug-Catching Contest trap (affects the whole contest, not only battles)

- `ContestDropOffMons` (engine/events/bug_contest/contest_2.asm:75) masks the party to count 1 and
  terminates the species list after slot 0 for the whole ~20 minutes. `ContestReturnMons` restores it.
- `reads.read_party` decodes by `wPartyCount`, so slots 2..6 are invisible. A death command for a
  hidden mon is dropped today ("key not in party"), at the checkpoint too.
- The hidden structs stay intact in `wPartyMon2..6`, so a raw-slot write would persist through
  `ContestReturnMons`.
- The lead's last-mon faint → `LostBattle` → `Script_Whiteout` → `.bug_contest` →
  `BugContestResultsWarpScript` (plus `HealParty`).
- **Owner ruling needed:** hold hidden-mon deaths until `ContestReturnMons`, or write the hidden
  struct directly.

### Battle Tower trap (Crystal)

- `RunBattleTowerTrainer` (engine/events/battle_tower/battle_tower.asm:214-236) runs `HealParty`,
  then `StartBattle`, then `LoadPokemonData`, then `HealParty`. The party is reloaded from the save
  after every tower battle.
- So any in-battle death is reverted. Natively the tower is a no-death zone.
- **Owner ruling needed:** refuse in the tower and keep the command for the checkpoint after
  `LoadPokemonData`, or write in battle AND keep a checkpoint re-zero.

## 4. Gen 1's remaining exclusions (report only; not changed in this card)

From `lua/gen1/client.lua` / `lua/gen1/writes.lua`:

1. **Bench faint on receipt** (client.lua:535-555) requires all of:
   - `writes_enabled`
   - `in_battle` 1 or 2
   - `battle_type == 0`
   - `link_state ~= 4`
   - `slot ~= wPlayerMonNumber`

   Otherwise the write waits for the loop head.
2. **Loop-head active faint** runs only when `W.active_faint_guard` (writes.lua:39-49) passes. It refuses:
   - "not in a battle"
   - `battle.type ~= 0` ("special battle type (old man / safari)")
   - `link_state == 4`
   - "target is not the active battler"
   - battle species ≠ party species unless transformed (transformed is allowed)

   A refused write stays in `pending_battle_writes` (`keep`). At `battle_end` it becomes a quiet
   checkpoint `defer_held` (client.lua:1083-1089).
3. **Loop-head bench faint** (client.lua:1492-1504) needs `battle_type == 0 and link_state ~= 4`.
   Otherwise `defer_held` to the checkpoint: special/link battles hold the bench to battle end.
4. An unreadable party at the loop head keeps the queue (client.lua:1463-1464).
5. pureRGB's `battle_loop_no_move` re-entry covers the MOVE-cancel path (client.lua:1512-1523).

Under the owner's rule, exclusions 2 (type ≠ 0) and 3 are candidates:

- Old man: the player's party is not on the field, so a bench write is harmless.
- Safari: the player's mons never enter the field, so every party mon is "bench" and a party-HP
  write is harmless.
- Link stays refused.

## 5. What this means for phases 2-4

- **Phase 2** (evolution fallback) is required, not optional: it is the backstop behind
  in-battle faints (§2 evolution trap).
- **Phase 3:**
  - Add a Gen 2 `battle_loop_head` site at the `call DetermineMoveOrder` address per title.
  - Add `pending_battle_writes` plus `on_battle_loop_head` mirroring Gen 1.
  - `writes.faint_active_battler(slot)` becomes the write set above, armed only at that hook.
  - Bench faint lands at the same hook.
  - Link and tutorial are refused. The contest and the tower wait for the rulings.
  - Every landed battle write also queues a quiet checkpoint re-zero.
- **Phase 4:**
  - A U1 receipt proving the site fires once per committed turn on C/G/S (U1d pattern).
  - A U2 receipt for a new write kind (e.g. `battle_active_faint`) covering `wBattleMonHP`,
    `wBattlePlayerAction` and the party HP/Status span in that frame.
  - A physical proof that "<MON> fainted!" follows, then the next-mon prompt or the whiteout.

## 6. Mechanism P (Gen 3's Perish-flag route) versus the USEITEM route

The owner asked for this comparison. Gen 3's "mechanism P" doc lives on branch
`claude/gen3-migration-planning-5d8e45`, at `docs/gen3/research/active_faint_in_battle_scope_2026-09-23.md`.

### The decisive question: is the USEITEM route's faint fully native?

**Yes.** `Battle_PlayerFirst` reaches `call HasPlayerFainted` / `jp z, HandlePlayerMonFaint`. That is
the same instruction a natural KO takes when the foe's move drops our mon to 0 in the player-first
order. What follows is byte-for-byte a natural faint:

- `FaintYourPokemon` (core.asm): `StopDangerSound`, the cry (`PlayStereoCry` of
  `wBattleMonSpecies`), `PlayerMonFaintedAnimation`, then `BattleText_MonFainted` ("<MON> fainted!").
- `UpdateFaintedPlayerMon`: the party copy-back, the happiness hit and `wBattleResult` LOSE.
- `CheckPlayerPartyForFitMon`, then `LostBattle` for the whiteout, or `AskUseNextPokemon`
  ("Use next #MON?", wild only) and `ForcePlayerMonChoice`.

Gen 3 chose P because FRLG's HP write is silent. That reason does not exist on Gen 2.

### Gen 2's Perish mechanics

`HandlePerishSong` (core.asm) is called from `HandleBetweenTurnEffects` after FutureSight, Weather
and Wrap, each followed by `CheckFaint_*`. It:

1. Tests `SUBSTATUS_PERISH` in `wPlayerSubStatus1`.
2. Runs `dec [wPlayerPerishCount]` and prints `PerishCountText`.
3. Only if the result is 0: clears the flag and **writes `wBattleMonHP` = 0 and the party HP = 0
   itself**. There is no drain animation; it is a direct engine HP write.
4. The next `CheckFaint_PlayerThenEnemy` → `HandlePlayerMonFaint` is the same native faint as above.

The count must be set to **1**. A count of 0 decrements to 255 and never KOs.

### What goes wrong under P that USEITEM avoids

- **The corpse still needs a no-op action.** Otherwise it uses its selected move: it can KO the foe,
  win, gain exp, level and evolve. Gen 2's no-op commit is exactly `wBattlePlayerAction` =
  USEITEM (`DoPlayerTurn` returns). So P = USEITEM + flag + count, one byte *more* than it saves.
- **The foe acts, because the KO lands at the END of the turn.** Each case:

| foe action under P | effect on us |
|---|---|
| a KO | harmless, the mon is dead either way |
| Present / Pain Split | harmless, Perish zeroes HP regardless |
| Destiny Bond, Mean Look | no effect |
| Teleport or Whirlwind / Roar in a wild battle | **ends the battle** before `HandleBetweenTurnEffects`: no Perish KO, the mon escapes until the checkpoint |
| Roar / Whirlwind in a trainer battle | sets `wForcedSwitch`: `BattleTurn` quits the turn before `HandleBetweenTurnEffects`, and the switched-out mon loses its substatus. It needs a bench write anyway |

- Baton Pass can't come from us, since our action is the no-op.
- Under USEITEM the foe never acts that turn: `Battle_PlayerFirst` jumps to `HandlePlayerMonFaint`
  before `EnemyTurn_*`.
- **Text.** P adds "<MON>'s PERISH count fell to 0!". That's a false cause on screen, since no
  Perish Song was used. USEITEM shows only the faint.
- **Battle kinds.** No kind breaks one route and not the other:
  - Contest, Tower, trainer, CANLOSE and the last mon behave the same once `HandlePlayerMonFaint`
    runs.
  - The routes differ only in *whether* it runs this turn. P can miss it (above); USEITEM can't
    once the site fires.
- **Write count.** Party HP/Status need the Crystal SVBK check under both routes.

| route | writes |
|---|---|
| USEITEM | `wBattleMonHP` (2) + `wBattlePlayerAction` (1) + party HP/Status mirror (3). Could drop to 3: the engine's `UpdateFaintedPlayerMon` mirrors it, but keep it for Gen 1 parity |
| P | `wPlayerSubStatus1` read-modify-write (1) + `wPlayerPerishCount` (1) + `wBattlePlayerAction` (1) |

**Recommendation: keep USEITEM.** It is native, it is immediate, the foe never acts, and there are
fewer escape paths.

### Gen 3 lessons folded into phase 3

- **(a) Write at a parked, committed state proven by engine reads.** The hook runs synchronously
  on the bus-exec callback *before* `call DetermineMoveOrder` executes. The CPU is stopped for the
  whole callback, so no frame boundary can split the write set (lesson e).
  - Engine-read preconditions: `wBattleMode ≠ 0`, `wLinkMode == 0`, `wCurBattleMon` == the slot,
    battle species == party species (or `SUBSTATUS_TRANSFORMED`), and the WRAMX bank mapped.
  - The action byte is written LAST.
- **(b) Echo.** The native faint fires the existing `battle_faint` site, and the client reports a
  `faint` for the key. Gen 1 does not suppress this. The server's `_handle_faint` (state.py:1811)
  ignores a key whose link is not ALIVE, which covers a partner death and identity_lost.
  - A clause-rejection kill of an ALIVE or unlinked key would be reported as a real faint.
  - Phase 3 marks landed keys as commanded, so the client drops that one echo, and adds a test.
- **(c) Oracles for the physical proof are engine reads, not acks:**
  - `wBattleMonHP` == 0
  - `UpdateFaintedPlayerMon` executed once for that slot
  - the foe's move not executed that turn (`wEnemyMoveStruct` animation / `hBattleTurn` trace)
  - no `faint` sent for the key
- **(d) Copy directions,** each verified above:
  - `UpdateBattleMonInParty` copies battle → party for `wCurBattleMon` only. It runs at
    `BattleTurn.loop`, at the end of `HandleBetweenTurnEffects` and in `UpdateFaintedPlayerMon`.
  - `HandlePerishSong` writes both HP copies.
  - Nothing copies party → battle mid-battle except a switch-in (`InitBattleMon`).
  - So a bench write is never overwritten, and the active mirror is overwritten only with the same 0.

## 7. Phase 4: PHYSICAL proof (U2 `battle_faint` run, 2026-09-23)

`SLINK_LIVE=1 pytest tests/live/test_gen2_write_windows.py -k battle_faint_run` ran
`lua/tests/gen2_write_windows.lua` mode `battle_faint` on `<title>_battle`:

1. One scripted catch.
2. A second Route 29 wild battle, fought with a status move.
3. The first accepted battle hold kills the bench mon (the catch).
4. The next accepted hold kills the active lead, which is now the last able mon.

The engine order comes from observation-only hooks at the pack oracles, as `seq` values below. Silver
follows Gold under O-23 (the `battle_hold` rows are identical), and the Silver pack qualifies from Gold's
receipt.

### Crystal

- **Battle hold:** PC $4194, bank $0F. 7 holds accepted and 473 hits in other banks rejected.
- **Bench write (seq 6):**
  - party HP 000f → 0000
  - battle HP 0013 unchanged
  - action byte unchanged
- **The foe moves (seq 7):** the known-positive control.
- **Active write (seq 8):**
  - battle HP 0011 → 0000
  - party HP 0011 → 0000
  - action 00 → 01 (USEITEM)
- **HandlePlayerMonFaint (seq 9):** same frame as the write (13575). No foe turn came in between.
- **LostBattle (seq 10):** the native whiteout, followed by a fresh overworld hold after the warp.

### Gold

- **Battle hold:** PC $4168, bank $0F. 3 holds accepted and 28 hits in other banks rejected.
- **Bench write (seq 2):** party HP 0010 → 0000, battle HP 0011 unchanged.
- **The foe moves (seq 3).**
- **Active write (seq 4):**
  - battle HP 000e → 0000
  - party HP 000e → 0000
  - action 00 → 01
- **HandlePlayerMonFaint (seq 5), then LostBattle (seq 6).**

### What changed

- Receipts: `tests/fixtures/gen2/receipts/{crystal,gold}.write_window.json` gain `runs.battle_faint` and the
  pack's `battle_hold` rows. The shipped copies are synced and the release pins are re-pinned (`--new-gates`
  green).
- `M.qualified` now adds the `battle_faint` kind. Production composes the battle hold on Crystal, Gold and
  Silver.
