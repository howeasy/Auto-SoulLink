# Independent review: O-30 in-battle faint (Gen 2, with Gen 1 parity)

> **Historical record.** Findings below are against commit `a78f9b56`. At least MAJOR-1/MAJOR-2
> (a death queued before the battle starts / Battle Tower revival) have since been fixed — see the
> "O-30 review MAJOR-1/2" comment at `lua/gen2/client.lua:1425`. Check current `lua/gen2/client.lua`
> and `lua/gen1/client.lua` before treating any GAP row here as still open.

Reviewer: Claude (Opus), not an author of the reviewed code. Read-only review of the COMMITTED code at
`a78f9b56` (`git show HEAD:<path>`). Commits under review: e0442e96 (evolution fallback), a8e93be7
(battle hold + W-2), ade01a6e (U2 `battle_faint` PHYSICAL), 7af546cd/45195b35 (REVIEW_RECORD O-30).
Game facts come from the pinned decomps `.cache/gen2-build/pokecrystal` @7a7881d (C) and
`.cache/gen2-build/pokegold` @656583c (G). No emulator was run.

Line numbers: `client.lua` = `lua/gen2/client.lua` at HEAD, `gen1` = `lua/gen1/client.lua` at HEAD,
`core.asm` = `engine/battle/core.asm`, `state.py` = `server/state.py` at HEAD.

Working tree: the uncommitted hunks in `lua/gen2/client.lua` and `lua/gen1/client.lua` touch only the
trade path (`trade_uncertain`, `withdraw_offer`, `trade_forget`, `trade_owed`). None of them touches the
faint path (handle_command force_faint, at_battle_hold, battle_end, run_deferred, on_event faint).

## Findings (ranked)

### MAJOR-1: a death queued before the battle starts is held to battle end (both gens)

- Where: `client.lua:444` and `:464` put a force_faint into `self.deferred` whenever the command arrives
  out of battle (or with the party unreadable). `run_deferred` (`:744-800`) runs only inside the
  overworld hold. `at_battle_hold` (`:1184-1243`) drains only `pending_battle_writes`. Nothing moves a
  deferred death into `pending_battle_writes` when a battle starts. Gen 1 has the same hole
  (`gen1:520-523`, `:563`; `on_battle_loop_head` `:1465-1515` reads only `pending_battle_writes`).
- Failure scenario: the partner's mon dies while this player reads a gym leader's pre-battle text, or
  while a trainer's sight walk-up runs, or during a wild battle's transition (`wBattleMode` is still 0).
  The primary hold refuses all of these (`wScriptRunning` and the other 14 predicates), so the entry sits
  in `deferred`. The battle starts and the linked mon fights the WHOLE battle alive. It can KO foes, gain
  exp and evolve. The server's O-24 repair does not help. The original is in `death_inflight`, which
  only counts down out of battle (`state.py:2508-2512`, `_has_pending_command` `:2472`).
- Why it matters: this breaks O-30 ("never held to battle end") and the a8e93be7 commit message's own
  claim. Trainer and gym battles almost always start from a script window, so the gap is common.
- Fix (one place per gen): at the top of `at_battle_hold` (and Gen 1 `on_battle_loop_head`), move every
  `deferred` entry with `cmd` force_faint/force_explode whose key resolves to a party slot into
  `pending_battle_writes`. Keep its `arrival`. The same pass then lands them. Or do the move at
  `wild_ready`/`trainer_ready`.
- Red test: `world.checkpoint_ok = False`, reply force_faint with `wBattleMode = 0`, then `in_battle(...)`
  + `battle_hold(world)`. Assert `battle_hp == 0` and `action == 1`. It fails today.

### MAJOR-2: Battle Tower: the dead mon is revived and fights the rest of the challenge

- Where: `RunBattleTowerTrainer` (C `engine/events/battle_tower/battle_tower.asm:214-236`) runs
  `HealParty` → `StartBattle` → `LoadPokemonData` → `HealParty` for every battle. `LoadPokemonData`
  copies the whole `wPokemonData` back from `sPokemonData` (C `engine/menus/save.asm:756-764`).
  `Script_BattleRoomLoop` (`maps/BattleTowerBattleRoom.asm:17-60`) chains up to 7 battles inside one
  script. The heal, the "next opponent?" yes/no and the next battle are all scripted, so the player
  never gets an overworld hold.
- Failure scenario: a death lands in tower battle 1 (the write is correct). The reload revives the
  mon at full HP. The quiet re-zero that `at_battle_hold` queued (`client.lua:1236`) waits in
  `deferred` for an overworld checkpoint that only comes after the challenge. So the dead mon fights
  battles 2..7. The O-24 re-issue is throttled as in MAJOR-1: 120 out-of-battle passes, budget 3
  (`state.py:79-86`).
- The owner's tower ruling ("kill in battle + checkpoint re-zero", RESUME.md:298-299) assumed a
  checkpoint between battles. There is none.
- The unit test `test_a_battle_death_is_re_zeroed_at_the_checkpoint_after_a_revive[tower_reload]`
  (`tests/unit/test_gen2_client.py:579-599`) passes only because it models a checkpoint after the
  battle.
- Fix: the MAJOR-1 fix covers this if it also lifts QUIET deferred entries whose mon reads HP > 0 into
  the battle hold. The revived mon then dies again at the first hold of the next tower battle, whether
  it is active or on the bench. Add a two-battle test with no checkpoint between the battles.

### MINOR-3: contest mask windows drop a hidden mon's death on receipt

- Where: `client.lua:445-448` drops a force_faint ("key not in party") unless `contest_masked()`.
  `contest_masked()` is the `ENGINE_BUG_CONTEST_TIMER` bit (`wStatusFlags2` $D84D bit 2).
- The mask and the flag are not set and cleared together:
  - **Entry:** `special ContestDropOffMons` (C and G `maps/Route35NationalParkGate.asm:140`) masks the
    party to count 1 two text boxes BEFORE `setflag ENGINE_BUG_CONTEST_TIMER` (`:99`).
  - **Exit:** `BugContestResultsScript` clears the flag first (C `engine/events/std_scripts.asm:318`,
    G `:276`). `special ContestReturnMons` comes later (C `:352`, G `:310`), after the judging text.
- Failure scenario: a force_faint for a hidden mon that arrives in either window is dropped. O-24
  re-issues it once the returned mon shows HP > 0, so the death comes late (after the contest), not
  never.
- Fix: in handle_command, defer "key not in party" instead of dropping it. The checkpoint already
  drops a truly departed key with a log (`:770-775`), and the contest re-queue (`:761-769`) holds it
  during the contest.

### MINOR-4: a bench death waits for the hold, while Gen 1 lands it on receipt

- Gen 1 kills a benched mon the frame the command arrives (`gen1:535-555`, owner 2026-09-22: "so it
  can never be switched in"). Gen 2 queues it for the next battle hold (`client.lua:450-455`).
- Failure scenario: the doomed bench mon is still selectable in `BattleMenu`. `TryPlayerSwitch`
  (C `core.asm:5156`) switches it in. At the hold it is now the active slot and dies through W-2. The
  USEITEM path then skips the foe's move (`Battle_PlayerFirst`, C `core.asm:912-930`). The result is a
  free switch: the doomed mon is "spent" instead of the next mon taking a hit.
- This is justified today: the U2 receipt proves only the battle hold. It should be recorded as a Gen 1
  divergence, or qualified with a receipt-time bench write.

### MINOR-5: PHYSICAL coverage is one path, and the kind is granted for all of them

- ade01a6e proves one path only:
  - a wild NORMAL battle
  - the player committed FIGHT with a status move
  - the killed mon was the last able mon, so `LostBattle` followed
  - on C and G (S by O-23)
- `M.qualified` grants `battle_faint` for every non-link battle. These paths are SOURCE-only:
  - **Trainer, next mon:** `HandlePlayerMonFaint.switch` → `ForcePlayerMonChoice` / `HandleEnemySwitch`
    / `DoubleSwitch` (C `core.asm:2643-2654`, `:2723`; G `:2618`).
  - **Wild, not the last mon:** `AskUseNextPokemon` (C `:2695`), including NO → `TryToRunAwayFromBattle`.
  - **CANLOSE:** `LostBattle` (C `:2926-2940`).
  - **Contest:** a count-1 `LostBattle`, then `Script_Whiteout .bug_contest`.
  - **Tower:** `LostBattle .battle_tower`.
  - **Switch-, item- or recharge-committed turns:** `CheckPlayerLockedIn` (C `:581-602`) →
    `ParsePlayerAction .locked_in`.
- Suggest one more physical row: a trainer battle where the killed active mon is NOT the last mon
  (next-mon prompt, then a live turn after it).

### NIT-6: `commanded` outlives the battle

- `self.commanded` is cleared only in `boundary()`/`abandon_timeline()` (`client.lua:300`, `:317`), not
  at `battle_end` (`:923-944`).
- If the echo never arrives, the flag silently eats the next `faint` event for that key. That happens
  when the binder refuses the observation: `signals.lua` `faint_event` `need(party ...)`.
- It is harmless on the server today (the key's link is already DEAD, see Verified OK), but it is a
  latent trap. Fix: clear `commanded` at `battle_end`.

### NIT-7: landing on a mon already at HP 0 still announces a KO

- `at_battle_hold` writes, shows "!! X KO'd" and queues another quiet re-zero (`client.lua:1231-1236`),
  even when the target bench mon already fainted natively.
- Gen 1 skips a landed bench write at HP 0 (`gen1:1500`). Skip the write and the HUD line when
  `mon.hp == 0` and the target is not the active battler.

### NIT-8: the exceptions are not in REVIEW_RECORD

- The O-30 row says "any other exclusion needs an owner ruling". Three rulings live only in
  `docs/gen2/RESUME.md:298-299` and in code comments ("ruling (a)"):
  - contest ruling (a): a hidden mon dies at `ContestReturnMons`
  - the tower ruling
  - the tutorial-battle exclusion (`DoBattle .tutorial_debug`, C `core.asm:57-59,115`, `jp BattleMenu`,
    never reaches `BattleTurn`, so the death lands at the checkpoint)
- Record all three with the owner's quotes.

### NIT-9: "the foe never moves this turn" overstates

- `Battle_PlayerFirst` runs `AI_SwitchOrTryItem` before the player's no-op turn (C `core.asm:913-916`;
  G `:860-864`), so a trainer can still switch or use an item on the kill turn.
- Its move does not run. The wording in the facts doc §2 and the writes.lua header should say
  "the foe does not use a move".

## Verified OK

- **Site.**
  - The hold is before `call DetermineMoveOrder` in `BattleTurn`: C 0f:4194 (`core.asm:205`), G/S 0f:4168
    (G `core.asm:181`; `pokegold.sym` 0f:4121 `BattleTurn`).
  - It is reached on every committed turn:
    - after `ParsePlayerAction` returns z, including locked-in and recharge turns (`.skip_iteration` →
      `.locked_in`, C `core.asm:186-199`, `:606-608`, `:679-688`)
    - after a switch has already executed inside `BattleMenu` (`TryPlayerSwitch` → `BattleMonEntrance`
      with `PursuitSwitch`, C `:5156-5280`)
  - Sleep does not skip the menu.
  - The production client guards the hold three ways: the other-bank hit (`hROMBank` check,
    `client.lua:1187`), the StartBattle caller word and `wLinkMode == 0` (pack `battle_hold`,
    `gen2_write_safety` HOLDS `battle_hold`).
- **The native faint follows.**
  - `wBattlePlayerAction != 0` → `DetermineMoveOrder.use_move` `jp nz, .player_first` (C `core.asm:480`).
  - `DoPlayerTurn` returns (C/G `effect_commands.asm:1-7`).
  - `HasEnemyFainted` (foe HP intact) → `HasPlayerFainted` → `jp z, HandlePlayerMonFaint`
    (C `core.asm:923-926`, G `:871-874`).
  - The engine itself stores USEITEM in `HandlePlayerMonFaint.switch` (C `:2650-2651`).
  - The last mon goes `CheckPlayerPartyForFitMon` d=0 → `LostBattle` (C `:2615-2617`). This is PHYSICAL
    on C and G, and the whiteout is correct.
- **Atomicity (Q1).**
  - The write runs inside the synchronous bus-exec callback. `write_permit.lua:111-148` snapshots and
    preflights every span (bounds, window, mapped bank, pointer) before the first byte. So an unmapped
    Crystal WRAMX (SVBK ≠ 1) refuses the whole batch with nothing written, and `keep` retries at the
    next hold (`client.lua:1237-1239`).
  - The action byte is written LAST (`writes.lua:187-192`).
  - Only an `emit()` exception mid-batch could split the write. That is theoretical, and even then the
    engine faints a 0-HP battler at the turn's end.
  - The U2 run writes through the same `writes.lua`, the same `arm("battle_hold")` and the same pack
    `battle_hold.write` targets at the same PC and caller evaluation (`gen2_write_windows.lua:1108-1152`,
    `:1164-1183`). The receipt covers the window that production uses.
- **States (Q2).**
  - **Link and Time Capsule:** refused three times (the pack predicate `wLinkMode == 0`, the client's
    `link ~= 0` return, and the writes.lua asserts). The death is handed to the checkpoint at
    `battle_end` (`client.lua:938-941`).
  - **Tutorial:** no hold, so the death goes to the checkpoint.
  - **Transform:** the guard accepts transformed battlers (`client.lua:1211-1219`).
  - **Destiny Bond:** it acts only inside move damage (`effect_commands.asm:2353`), and the foe's bond
    is cleared on our no-op turn (`EndOpponentProtectEndureDestinyBond`, C `core.asm:973-981`).
  - **Perish Song, trapped:** native, and `ForcePlayerMonChoice` ignores trapping after a faint.
  - **Catch or RUN before the hold:** the battle ends in `BattleMenu` (`jr c, .quit`), and `battle_end`
    defers the death to the checkpoint (non-quiet, so it is not lost).
- **Echo suppression (Q3).**
  - The echo is keyed by the physical key (`mon_key(mon)`, `client.lua:1233`), the same key that
    `signals.lua` `faint_event` stamps from the party struct. It cannot swallow a different mon's faint.
  - Dropping it is harmless server-side:
    - Every force_faint issuer pre-marks the link DEAD or targets an unlinked capture, and discards
      `party_keys` before sending (`state.py:1529,1634,1655,1679,1733,1809,2179,2238,2548,2947`).
    - `_handle_faint` ignores non-ALIVE keys (`state.py:1918-1922`).
  - This diverges from Gen 1, which forwards the echo. The divergence is harmless but undocumented
    outside the facts doc.
- **Checkpoint re-zero (Q4).**
  - It is quiet and writes only when the mon reads HP > 0 (`client.lua:778`).
  - It keeps the landed command's arrival, so it runs before that key's memorialize (`defer_held`
    `:142-151`).
  - Under O-24 "dead stays dead" there is no legitimate revive to wrongly kill.
  - A duplicate with an O-24 server re-issue is idempotent: HP 0 over 0, plus one extra "KO'd" HUD line
    from the non-quiet copy.
  - The whiteout `HealParty` revival (C and G `engine/events/whiteout.asm:14`) is re-zeroed at the post-warp
    checkpoint.
- **Contest (ruling a).**
  - A hidden mon's death is re-queued at the tail while the timer flag is set (`client.lua:761-769`).
  - The contest lead is the active battler, and its death ends the contest natively
    (`LostBattle` → `Script_Whiteout` → `.bug_contest`).
  - Note: `ContestDropOffMons` refuses a fainted lead (C/G `contest_2.asm:75-80`).
- **Gen 1 parity / shared framework (Q5).**
  - a8e93be7 and ade01a6e change no shared Lua (`lua/write_permit.lua`, `lua/hook_registry.lua` are
    untouched).
  - `gen2_write_safety` gives the battle hold its own anchors and predicate count, and leaves the
    primary's 15 predicates unchanged.
  - The divergences are: the site (no Gen 2 loop-head HP test), USEITEM vs CANNOT_MOVE, the quiet
    re-zero after every landed write (no evolution key_change in Gen 2), the echo drop, and MINOR-4.
    All are deliberate. MINOR-4 and the echo drop should be recorded.
  - MAJOR-1 is shared: fix both gens.

## Test coverage (Q6)

| concern | red-capable test | status |
|---|---|---|
| active death at the hold, action byte last | `test_an_active_battler_death_lands_at_the_battle_hold`, `test_active_faint_writes_battle_hp_party_mirror_and_the_action_byte_last` | covered |
| bench death in a special battle | `test_a_bench_death_lands_at_the_battle_hold_in_a_special_battle` | covered |
| link refused, checkpoint later | `test_a_link_battle_death_never_writes_in_battle_and_lands_at_the_checkpoint` | covered |
| Transform / foreign struct waits | `test_a_transformed_battler_still_dies_and_a_foreign_struct_waits` | covered |
| echo dropped | `test_the_engine_faint_echo_of_a_commanded_death_is_not_reported` | covered |
| re-zero after evolve / reload | `test_a_battle_death_is_re_zeroed_at_the_checkpoint_after_a_revive` | covered (checkpoint between battles only) |
| contest hidden mon | `test_a_contest_hidden_mon_dies_when_the_contest_returns_it` | covered (mask and flag set together only) |
| production hold only (caller word) | `test_production_active_death_lands_only_inside_the_battle_hold` | covered |
| engine order (foe control, faint, LostBattle) | `test_battle_faint_problem_recomputes_the_engine_order` + U2 PHYSICAL | covered |
| death queued before the battle starts (MAJOR-1) | none | GAP (fails today) |
| tower multi-battle revival (MAJOR-2) | none | GAP (fails today) |
| contest drop-off / results windows (MINOR-3) | none | GAP |
| unmapped WRAMX at the hold keeps the write | none seen | GAP |
| stale `commanded` after battle end (NIT-6) | none | GAP |
| trainer next-mon / wild "Use next?" PHYSICAL (MINOR-5) | none | GAP |
