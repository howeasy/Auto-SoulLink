# Battle force-faint window (Gen 1 R/B/Y)

**Authority answer: NO.** There is no between-frames wait inside the Gen 1
battle loop at which zeroing the partner's HP is semantically a faint. The one
instruction where a zero *is* a faint (`MainInBattleLoop+0`) is never a waiting
point; reaching it needs a PC breakpoint or bus-exec hook, which fires inside a
running frame. The existing hold model (`platform_execution` stop between
frames + `held_write_permit`) therefore cannot enforce a battle force-faint, and
nothing here prototypes one. Only this document and a source-fact pinning test
(`tests/unit/test_battle_force_window_analysis.py`) are delivered.

Every claim below is labelled **source-cited** (pinned pret text),
**ROM-byte-verified** (clean-ROM bytes at the `.sym` address), or **inferred**.
Sources: `.cache/pret/pokered` @ `405b6246` (Red; Blue is the same source with
`pokeblue.sym`), `.cache/pret/pokeyellow` @ `0a085154`; pins in
`data/pret_sources.lock.json`. Line numbers are for those commits. No emulator
was run; nothing below is live-observed.

## 1. What the loop head does (the only place a zero is a faint)

`engine/battle/core.asm` (Red 280-285 / Yellow 289-294), **source-cited** and
**ROM-byte-verified** (`cd <ReadPlayerMonCurHPAndStatus> 21 <wBattleMonHP> 2a b6
ca <HandlePlayerMonFainted>` at `0F:4233` R/B, `0F:4249` Y):

```
MainInBattleLoop:
	call ReadPlayerMonCurHPAndStatus   ; battle struct -> party struct
	ld hl, wBattleMonHP
	ld a, [hli]
	or [hl]                            ; is battle mon HP 0?
	jp z, HandlePlayerMonFainted
```

`ReadPlayerMonCurHPAndStatus` (Red 1800-1809 / Yellow 1875-1884, bytes
`fa <wPlayerMonNumber> 21 <wPartyMon1HP> 01 2c 00 cd <AddNTimes> 54 5d 21
<wBattleMonHP> 01 04 00 c3 <CopyData>`) copies **from `wBattleMonHP` to the
party slot `wPlayerMonNumber`**, `MON_STATUS + 1 - MON_HP` = 4 bytes: HP (2),
party position / box level (1), status (1)
(`constants/pokemon_data_constants.asm:28-31`, `PARTYMON_STRUCT_LENGTH` = $2c at
:56). The battle struct is contiguous the same way (`wBattleMonHP`,
`wBattleMonPartyPos` = +2, `wBattleMonStatus` = +3; `.sym`).

So during a battle the **battle struct is authoritative for the active mon and
the party struct is a derived copy**. A zero written into the party slot alone
is overwritten by the copy at the very next loop head; a zero written into
`wBattleMonHP` at the loop head is copied down and then taken as a faint.

The faint path then owns its own bookkeeping (**source-cited**,
`HandlePlayerMonFainted` Red 969-1000 / Y 981-1012, `RemoveFaintedPlayerMon`
Red 1003-1044 / Y 1015-1083): clears the slot's `wPartyGainExpFlags` bit
(1004-1008), resets `ATTACKING_MULTIPLE_TIMES` on the enemy, silences the
low-health alarm, zeroes `wEnemyBideAccumulatedDamage`, **zeroes
`wBattleMonStatus` itself** (Red 1022 / Y 1035), re-runs
`ReadPlayerMonCurHPAndStatus` (1023 / 1036), slides the pic, sets
`wBattleResult` = 1 (1030-1031 / 1043-1044), plays the cry and prints
`PlayerMonFaintedText`. It then either blacks out (`AnyPartyAlive`), asks for
the next mon (wild) or forces `ChooseNextMon` (trainer) and jumps back to
`MainInBattleLoop` (992-1000 / 1004-1012).

Yellow adds, inside `RemoveFaintedPlayerMon` (1054-1083): the Pikachu cry via
`IsThisPartyMonStarterPikachu`, and a **happiness deduction**
(`PIKAHAPPY_FAINTED`, or `PIKAHAPPY_CARELESSTRAINER` when the enemy is >= 30
levels higher). Both are engine-side effects of the genuine path; a forced faint
that takes this path gets them for free, and one that does not (an overworld
force-faint) does not. Yellow's loop head, copy routine and faint check are
otherwise byte-identical in shape (only addresses differ).

## 2. Where the battle loop waits, and why none of it is pre-check

The loop head check is followed (Red 290-337 / Y 299-346) by `DisplayBattleMenu`
(305 / 314), then `MoveSelectionMenu` (332 / 341), then `SelectEnemyMove` and
the turn (338-468 / 347-477). Every place the engine blocks for the player is
**after** the check and **before** the action:

| Wait | Where | Halted? | Continuation |
|---|---|---|---|
| Battle menu | `DisplayBattleMenu` -> `HandleMenuInput` (Red 2092, 2126 / Y 2178, 2212) -> `HandleMenuInput_.loop2` (`home/window.asm:19-38`) | **No** (busy loop) | player's choice |
| 3 frames after each cursor placement | `HandleMenuInput_.loop1` -> `Delay3` (`home/window.asm:17-18`) -> `DelayFrames` -> `DelayFrame` | Yes, 3 frames | back into `.loop2` |
| Move menu | `MoveSelectionMenu` -> `HandleMenuInput` | No (same loop) | A: move executes; B: `jr nz, MainInBattleLoop` (Red 337 / Y 346) |
| Party / bag menus | `PartyMenuOrRockOrRun`, `BagWasSelected` | No (same loop / list menu) | switch, item, or back to `DisplayBattleMenu` |
| Mid-turn text and animations | `PrintText`, `DelayFrames`, HP-bar animation | Yes, transient | rest of the turn, then `jp MainInBattleLoop` |

**Source-cited:** `HandleMenuInput_.loop2` calls only `AnimatePartyMon` (party
menus), `JoypadLowSensitivity`, `HandleDownArrowBlinkTiming` and re-reads
`wMenuJoypadPollCount` (`home/window.asm:19-38`, identical in Yellow).
`JoypadLowSensitivity` (`home/joypad2.asm:16-53`) -> `Joypad`
(`home/joypad.asm:33-38`, `homecall _Joypad`) -> `_Joypad`
(`engine/joypad.asm:1-48` Red / 34-83 Y) contain no `DelayFrame`, `Delay3`,
`DelayFrames` or `halt`; the only `DelayFrame` in that file is `TrySoftReset`
(Red 50-51 / Y 84-85), reached only when A+B+Start+Select are held. The VBlank
handler polls the pad itself (`home/vblank.asm`, `call z, ReadJoypad`), which is
why the spin loop still sees input.

Consequences:

1. **The battle menu is not a halt.** The overworld checkpoint pins a single
   return address (`DelayFrame+5`, i.e. the byte after `halt`) because
   `OverworldLoop` is halted when VBlank fires. A VBlank that interrupts
   `.loop2` returns to *any* instruction boundary in the loop's call graph,
   including inside the `homecall` bank switch (`hLoadedROMBank` = 3 mid-swap).
   There is no single `(pc, [sp])` pair to pin; a verifier would need a
   PC-range/boundary model that does not exist in `gen1_held_faint`.
   **Inferred:** whether Gambatte's frame boundary even lands at the IRQ vector
   (`pc == 0x40`) for a non-halted CPU is unverified; the live evidence for
   `pc == 0x40` exists only for the halted overworld case.
2. **Even a perfectly pinned menu checkpoint is post-check.** A zero written
   while the menu waits meets one of these fates, decided by the player's next
   input, not by the command:
   - **FIGHT + move:** `ExecutePlayerMove` (Red 3073-3100 / Y 3244-3271) has no
     HP gate; it checks only `wPlayerSelectedMove`, `wActionResultOrTookBattleTurn`,
     ghost text, status and disobedience. Bytes `af e0 f3 fa dc cc 3c ca
     <ExecutePlayerMoveDone>` **ROM-byte-verified**. The 0-HP mon attacks. The
     faint is only caught afterwards: by `HandlePoisonBurnLeechSeed`'s
     `ret nz` (Red 524-532 / Y 533-541, `xor a; ret` only when HP is 0, and only
     if poisoned/burned/seeded), by the enemy move's tail `ld hl, wBattleMonHP;
     ld a, [hli]; ld b, [hl]; or b; ret z` (Red 5638-5642 / Y 5820-5824) after
     `ApplyDamageToPlayerPokemon` clamps an underflow to 0 (Red 4822-4835 /
     Y 4993-5006), or by the next loop head. The enemy visibly hits a corpse.
   - **ITEM + Potion on the active mon:** `ItemUseMedicine.updateInBattleData`
     copies **party HP over `wBattleMonHP`** (`engine/items/item_effects.asm`
     Red 1160-1171 / Y 1280-1291). The party copy was taken at the loop head,
     before the write, so the zero is silently **lost**.
   - **PKMN + switch:** `.switchMon`/`.notAlreadyOut` (Red 2396-2418 / Y
     2502-2524) sets `wActionResultOrTookBattleTurn` = 1 and falls into
     `SwitchPlayerMon` (Red 2419-2439 / Y 2525-2546), which **does not** call
     `ReadPlayerMonCurHPAndStatus` before `LoadBattleMonFromParty` (2434 / 2540)
     overwrites `wBattleMonHP` with the new mon. The zero is **lost** and the
     outgoing mon keeps its pre-write party HP.
   - **FIGHT then B:** `jr nz, MainInBattleLoop` (Red 337 / Y 346) re-runs the
     head check and the faint is genuine. This is the only benign outcome, and
     it depends on the player cancelling.
   - **RUN:** `BattleMenu_RunWasSelected`; success ends the battle with the
     zero copied nowhere (end-of-battle copy semantics not analysed here).
3. **The transient `Delay3` halt is pinnable but useless.** Its stack chain is
   `[DelayFrame+5][DelayFrames+3][HandleMenuInput_+0x17 = .loop2][DisplayBattleMenu
   return][MainInBattleLoop return]` (**inferred** from the bytes; not
   live-observed). It lasts exactly three frames after each cursor placement and
   returns into the same post-check menu wait, so it inherits every fate above.
4. **Mid-turn waits are downstream of the action and upstream of a fixed
   `jp MainInBattleLoop`** (Red 440, 468 / Y 449, 477) but which text/animation
   is the *last* wait of a turn depends on the move, its effect, status damage,
   Rage, multi-hit, and link state. There is no single instruction window to pin,
   and the write would still race the very code that reads HP (`HandlePoisonBurnLeechSeed`,
   `DrawHUDsAndHPBars`).

`MainInBattleLoop` has exactly seven control-flow references in each source
(entry `jr` from `StartBattle`, the `jr nz` cancel, four `jp`, one `jp nz` from
`HandlePlayerMonFainted`); the pinning test asserts that set so a new re-entry
site cannot appear silently.

## 3. The exact instruction window (for the record)

The only instruction window where zeroing is a faint by construction is
**`MainInBattleLoop+0`** (`0F:4233` R/B, `0F:4249` Y) **before**
`ReadPlayerMonCurHPAndStatus` runs, with bank $0F mapped. From that PC the next
eleven bytes copy HP down and jump to `HandlePlayerMonFainted` with no
intervening read of anything a force-faint would touch. The window closes at
`MainInBattleLoop+3` (after the `call`), because from there the party copy has
already been taken and the check reads only the battle struct (still a faint if
`wBattleMonHP` is 0, but the party slot would now be stale until
`RemoveFaintedPlayerMon` re-copies at 1023 / 1036, which it does, so strictly the
window is `MainInBattleLoop+0 .. +6` inclusive of the `ld hl` -- **inferred**).

This PC is never a waiting point. The CPU passes through it once per turn and
once per menu cancel, always in the middle of a frame, and never halts there.

## 4. Mutation set a controlled-CPU gate would write (NOT implemented)

If, and only if, execution were stopped at `MainInBattleLoop+0` with bank $0F
mapped:

| Write | Bytes | Why |
|---|---|---|
| `wBattleMonHP` (R/B `D015`, Y `D014`) | 2, `00 00` (big-endian HP) | authoritative copy; loop head copies it to the party slot and takes the faint |

Nothing else. Explicitly **must not** be touched, because the genuine path
writes them itself and a pre-write would either be overwritten or change which
branch the engine takes:

- party slot HP (`wPartyMon1HP + 44 * wPlayerMonNumber`): overwritten by the
  copy at +0; writing it *instead of* `wBattleMonHP` is silently undone;
- `wBattleMonStatus` / party status: zeroed by `RemoveFaintedPlayerMon`
  (Red 1022 / Y 1035); pre-zeroing changes `CheckPlayerStatusConditions`
  outcomes if the write is ever mis-timed;
- `wPlayerMonNumber`: selects the slot for both the copy and the exp-flag
  clear; the linked slot must already be the active one;
- `wPartyGainExpFlags`, `wBattleResult`, `wLowHealthAlarm`,
  `wEnemyBideAccumulatedDamage`, `wInHandlePlayerMonFainted`: engine-owned;
- `wActionResultOrTookBattleTurn`, `wPlayerBattleStatus1/2`,
  `wEnemyBattleStatus1`, `wPlayerNumAttacksLeft`: turn state that
  `CheckNumAttacksLeft` (Red 683-697) and the faint path reset on their own;
- `wPlayerSubstituteHP`, `wBattleMonMaxHP`, DVs/stats/moves/PP: not part of a
  faint.

Preconditions such a gate would assert (all **inferred** from the code paths
above, none live-verified): `pc == MainInBattleLoop` and `hLoadedROMBank == $0F`;
`wIsInBattle` in {1 wild, 2 trainer} (`HandlePlayerMonFainted` branches on it,
983-985 / 995-997); `wLinkState != LINK_STATE_BATTLING` (a unilateral faint
desyncs a link battle); `wBattleType` not Safari/old-man (no player mon in play);
`wPlayerMonNumber == linked slot`; `wBattleMonHP != 0` (else no-op ACK);
`[sp]` chain proving the arrival edge (one of the seven references above), and a
stack window as the overworld profile uses.

**Whether the write lands as a faint does not depend on the linked slot's party
struct at all** -- only on `wBattleMonHP`. That is the inverse of the overworld
model, where the party slot is the only copy.

## 5. Why this is not a held write

`platform_execution.set_held` stops the core between frames; `held_write_permit`
is a one-use, <= 1000 ms permission with no frame authority; `gen1_held_faint`
proves the stopped CPU is at a *known idle* (`pc == irq_vector`, `[sp] ==
DelayFrame+5`, caller in `OverworldLoop`). All three assume the main thread is
parked somewhere that reads the target only after the hold releases and reads it
consistently. Section 2 shows the battle loop has no such park for the active
mon: its idle points are post-check and their continuation is chosen by the
player. Section 3 shows the one consistent point is mid-frame. A bus-exec hook or
PC breakpoint at `MainInBattleLoop` would fire inside `step_one`'s released frame
(`platform_bounded_execution`), where the permit cannot be consumed because the
frame is running, not held. Treating that frame as held would be the bypass the
brief forbids; it is not proposed.

## 6. Benched linked slot (open gap, not a recommendation)

If the linked mon is **not** the active battle mon, its party slot is its only
copy during the battle (`LoadBattleMonFromParty` reads it only on send-out, Red
1626-1644 / Y 1667-1685; `HasMonFainted` reads it to refuse a switch, Red
1473-1480 / Y 1512-1519; `AnyPartyAlive` counts it). "Benched mon at 0 HP" is a
natural Gen 1 state (a mon that fainted earlier this battle), so a zero there
is self-consistent. But the checkpoint problem in section 2.1 is unchanged (the
menu is a busy loop with no pinnable return), the party menu would show the
change without a cause, and the black-out edge (`AnyPartyAlive` returning 0
after the active mon later faints) has not been traced. Not pursued.

## 7. What was NOT verified

- No live CPU state was captured; every `[sp]` chain is inferred from bytes.
- Gambatte's frame-boundary PC for a non-halted CPU is unknown.
- End-of-battle copy semantics (`wBattleMonHP` vs party after RUN/win/loss)
  were not traced.
- Link-battle (`wLinkState == LINK_STATE_BATTLING`) serial ordering was not
  traced beyond noting it would desync.
- Old-man tutorial and Safari `wBattleType` paths were not traced beyond the
  menu template selection (Red 2003-2022).

## 8. Seams (describe only; no existing file was edited)

- `server/gen1_held_faint.verify` currently requires `intent['before']['battle_flag'] == 0`;
  that is the correct guard and should stay. A battle-time faint would need a
  new verifier module with a controlled-CPU evidence schema, not a relaxation.
- `data/games/gen1_rby/write_checkpoint.json` `BATTLE_FLAG_ADDR` equals
  `wIsInBattle` and `write_safe.delay_frame` equals `DelayFrame` in each
  `.sym`; the analysis test cross-checks both so this document and the
  overworld checkpoint rot together or not at all.
- If a controlled-CPU authority is ever designed, the data this document pins
  (`MainInBattleLoop`, `ReadPlayerMonCurHPAndStatus`, `HandlePlayerMonFainted`,
  `wBattleMonHP`, `wPlayerMonNumber`, `wIsInBattle`, the seven re-entry
  sites) is the generator input; the mutation set is the single two-byte
  write in section 4.

## Address table (ROM-byte-verified at these `.sym` addresses)

| Symbol | Red/Blue | Yellow |
|---|---|---|
| `MainInBattleLoop` | `0F:4233` | `0F:4249` |
| `ReadPlayerMonCurHPAndStatus` | `0F:4D43` | `0F:4E08` |
| `HandlePlayerMonFainted` | `0F:4700` | `0F:471D` |
| `RemoveFaintedPlayerMon` | `0F:4741` | `0F:475E` |
| `DisplayBattleMenu` | `0F:4EB3` | `0F:4F78` |
| `ExecutePlayerMove` | `0F:565E` | `0F:57D0` |
| `SwitchPlayerMon` | `0F:51BA` | `0F:52C1` |
| `LoadBattleMonFromParty` | `0F:4BA6` | `0F:4C10` |
| `HandleMenuInput_` / `.loop2` | `00:3AC2` / `+0x17` | `00:3AAF` / `+0x17` |
| `JoypadLowSensitivity` | `00:3831` | `00:381E` |
| `DelayFrame` (`3e 01 e0 d6 76 f0 d6 a7 20 fa c9`) | `00:20AF` | `00:1E64` |
| `wBattleMonHP` / `PartyPos` / `Status` | `D015` / `D017` / `D018` | `D014` / `D016` / `D017` |
| `wPartyMon1HP` | `D16C` | `D16B` |
| `wPlayerMonNumber` | `CC2F` | `CC2F` |
| `wIsInBattle` | `D057` | `D056` |
| `wBattleType` | `D05A` | `D059` |
| `wLinkState` | `D12B` | `D12A` |
| `wActionResultOrTookBattleTurn` | `CD6A` | `CD6A` |

## 9. Instruction-operation authority (prototype; separate from the held write)

Sections 1-5 stand: there is no *held* battle window. What follows is the minimal
authority that does not need one. It is split, per the cross-generation rule, into a
generic lifecycle and an R/B/Y binding, none of it wired into the client; root owns
whether it may exist.

| Layer | Files | Owns |
|---|---|---|
| generic | `server/instruction_authority.py`, `lua/instruction_executor.lua` | one `(owner_id, frame, step)` of the single bounded owner; one-use challenge; monotonic steps; hold verified at arm and finish; exactly one frame between them; `held: false` at the hook (a hook while held latches); pinned PC + bank + bytes; pinned caller checked from `[sp]` BEFORE any write; exact byte footprint vs the decided write set; fail-safe on the unmeasured hook-frame convention |
| R/B/Y binding | `server/battle_force_authority.py`, `lua/battle_force_authority.lua` | the two sites, the 16-field snapshot, `decide()` (identical order in Python and Lua), `prepare()` from the pending death + the command's physical key |
| tests | `tests/unit/test_battle_force_authority.py`, `tests/live/test_gen1_battle_force.py` + `lua/tests/test_gen1_battle_force_gate.lua` | source pins, envelope, decision, executor, live qualification |

**Ownership.** The bounded owner (`platform_bounded_execution.step_one`) releases the
physical hold for exactly one frame under a per-step authority; the instruction authority
is a field of that step. The server issues it for one `(owner_id, frame, step)`; the
client arms it immediately before that `step_one` (hold verified, frame == current, step
> last finished, challenge unused), the first pinned PC reached inside the frame consumes
it, and `finish()` right after `step_one` (hold verified, framecount == frame + 1) returns
the evidence. It never reuses `held_write_permit`.

**Sites** (bank $0F; ROM bytes pinned in `ANCHORS` and checked against `.sym` + clean ROM):

| Site | PC (R/B, Y) | Why it is a faint |
|---|---|---|
| `loop_head` | `MainInBattleLoop+0` `4233`, `4249` | section 1: `wBattleMonHP` copied down, then `jp z, HandlePlayerMonFainted` |
| `player_action` | `ExecutePlayerMove+0` `565E`, `57D0` | `wPlayerSelectedMove = $FF` is `CANNOT_MOVE`, the engine's own skip (`inc a; jp z, ExecutePlayerMoveDone`, Red 3076-3079 / Y 3247-3250; `ExecutePlayerMoveDone` sets `b = 1`, Red 3275-3279). Both callers (Red 429, 442 / Y 438, 451) then run `HandlePoisonBurnLeechSeed` on the player's turn, whose tail `ld a,[hli]; or [hl]; ret nz` (`.notLeechSeeded`, bytes `2a b6 c0 ... af c9` at `0F:4421` / `0F:4437`) returns Z on zero HP, and `jp z, HandlePlayerMonFainted` (Red 437, 450 / Y 446, 459). The caller is part of the pin: `[sp]` must be `4364`/`4380` (`437A`/`4396`). |

**Decision** (`decide(state, member, variant, site)`; the server re-derives it from the
client's own snapshot, so a refusal must match the bytes and a write may not follow a
refusable state):

1. `wIsInBattle` in {1, 2}; `wBattleType == 0` (old man, Safari, Yellow RUN / PIKACHU
   have no player mon); `wLinkState != 4`.
2. The party slot's species, DVs AND OT id equal the member. The member is parsed from
   the command's physical key `DVs:OTID:species` (`PartyCodec.validate_blob`); a slot
   holding the same species and DVs under another OT is refused. Nothing is written.
3. **Benched** (`wPlayerMonNumber != slot`): the party slot is the only copy during a
   battle (section 6). Write party HP `00 00` and party status `00` for that slot -- the
   state `RemoveFaintedPlayerMon` leaves a genuinely fainted mon in (Red 1022-1023).
   `HasMonFainted` (Red 1473-1480) then refuses to send it out. Nothing in the battle
   struct is touched. Outcome `benched`.
4. **Active**: the battle struct's species and DVs must equal the member UNLESS
   `TRANSFORMED` (`wPlayerBattleStatus3` bit 3) is set, because `TransformEffect_` copies
   the enemy's species and DVs into the battle struct (move_effects/transform.asm:57-88)
   while HP is skipped (":90"). Then `wBattleMonHP != 0`, `wEnemyMonHP != 0`. Write
   `wBattleMonHP = 00 00` (+ `wPlayerSelectedMove = $FF` at `player_action`). Outcome
   `fainted`.

**Menu / no-menu, and what bypasses the sites.** A death learned mid-turn is enforced at
the next `loop_head`. In the busy battle menu no pinned PC executes: every step returns
`not_reached`, nothing is written, the server re-issues for the next step. When the
player commits FIGHT the move is skipped and the faint taken before the mon acts. ITEM
and PKMN take effect in the menu (`wActionResultOrTookBattleTurn` documents that the
item / switch already happened) and then still reach `ExecutePlayerMove`: an item on the
dead mon is followed by the faint; a switch away makes the linked mon benched, branch 3.
A successful RUN or Poke Doll (`DisplayBattleMenu` then `ret c` / `ret nz`, Red 305-309)
and a capture (`.returnAfterCapturingMon`, `scf; ret`) leave the battle loop before any
site: the mon leaves the battle alive without acting, and the existing overworld held
faint (`gen1_held_faint`) settles the death at the next overworld checkpoint. A failed
RUN sets `wActionResultOrTookBattleTurn` and reaches `player_action`.

**Evidence** (`slink-instruction-evidence-v1`): challenge, owner, frame, step,
`held: false`, site, PC, bank, SP, 4 stack bytes, `hook_frame`, the 16-field snapshot,
the exact write list with before/after bytes, refusal. Outcomes `fainted`, `benched`,
`refused`, `not_reached`. Any other address, value, PC, bank, caller, frame, step,
owner, hold claim or write-set size is a `JournalError`.

**Fail-safe.** `HOOK_FRAME_OFFSET` (the `emu.framecount()` a bus-exec hook observes
minus the frame armed for) is a host convention. Until the live gate pins it, the
constant is `None` and `verify_evidence` refuses every reached row; `not_reached` rows
need no convention because nothing was written.

**Still open.** Transform could not be exercised live (no Ditto on Route 1); the
benched write is not enforced until a `loop_head`/`player_action` is reached with the
target benched (i.e. only during a battle); end-of-battle copy semantics and Yellow
happiness follow the genuine faint path (section 1) and were not re-traced.

## 10. Live qualification (2026-09-08, BizHawk 2.11.1 Gambatte, original engine)

`tests/live/test_gen1_battle_force.py` drives `lua/tests/test_gen1_battle_force_gate.lua`
from `tests/fixtures/gen1/<title>_battle.SaveRAM` (Route 1, one Squirtle, isolated SaveRAM
dir, rewind disabled as the bounded gate requires). One disclosed harness precondition: the
fixtures ship with `BIT_NO_BATTLES` set in `wStatusFlags4` (saved byte `0x10`), so the gate
clears it and logs both bytes; no other WRAM is written outside the executor's footprint.
After two harness-only measurements every frame is one `platform_bounded_execution.step_one`
under a real bounded owner. Result directories: `.cache/battle-force-{red-ickxc95g,
blue-qj663tiu, yellow-71bedde1}` (+ `red-cv5tyugs`, `red-_bpy7fg2`), each with
`result.json`, `summary.json`, `gate.log` and screenshots.

Measured on red, blue and yellow alike:

- Hook-frame convention: `emu.framecount()` inside a bus-exec hook equals the frame armed
  for, under `emu.frameadvance` and under `step_one` (`HOOK_FRAME_OFFSET = 0`, pinned).
- `joypad.set` input reaches the core inside `step_one` (player walks; battles start).
- Menu state: with the linked member armed for 30 consecutive steps in the battle menu,
  every step returned `not_reached`, nothing written.
- `loop_head` faint under the bounded owner: `MainInBattleLoop+0` hook fired
  (red 21426 / blue 9863 / yellow 14787), wrote `wBattleMonHP 00 14 -> 00 00`, the party
  copy read `0000` before the frame ended, the engine took the faint and the black-out
  followed (whited out to Pallet Town, party healed to 20 HP), SRAM byte-identical. The
  server verified every row (`fainted`; earlier rows for a non-linked member `refused`,
  zero writes). Screenshots after the row: `fight_after_hook.png`, `fight_later.png`.
- Negative controls (fresh executors): replay of a finished challenge refused;
  non-advancing step refused; other-frame authority refused; arming while unheld refused;
  a shifted-PC authority never writes; a wrong-caller `player_action` latches before any
  write (unit test); SRAM unchanged across every run.
- `player_action` (`ExecutePlayerMove+0`) was reached and written only under the harness
  owner (`red-wityf_me`, frame 35570, after an ITEM turn: `wActionResultOrTookBattleTurn`
  = 1, writes `00 00 ff`, faint and black-out followed). Under the bounded owner the FIGHT
  commit did not produce a turn in any run (both sides' HP unchanged at the next loop
  head), so the site was never reached there: a limitation of the gate's menu driving,
  not of the hook. Unresolved live: `player_action` under `step_one`, the benched branch
  (no second mon was caught in any run), Transform (no Ditto on Route 1).


## 11. Live qualification, round 2 (2026-09-09): benched, Transform, ExecutePlayerMove under step_one

Two host facts had to be measured before the remaining branches could be exercised, both
with disclosed probes in `lua/tests/`:

- `probe_input_latency.lua`: under `platform_bounded_execution.step_one`, `joypad.set` is
  STICKY — a button stays held until another `joypad.set` replaces it, whereas
  `emu.frameadvance` auto-releases. Every earlier "A press" in bounded mode was therefore a
  permanently held A, which never yields a new press edge (`_Joypad` edges are relative to
  the game's last poll), so the wild-intro `prompt` never advanced. The gate now sets all
  eight buttons explicitly every frame.
- `probe_battle_exec.lua` / `probe_exec_callbacks.lua`: bus-exec callbacks fire for call
  targets, jump targets and linear addresses alike, in bank 0 and in switchable banks;
  `ExecutePlayerMove` was never reached in the earlier runs because no turn had been
  committed (the move-menu A press followed the FIGHT press too closely: the engine's
  `hJoyLast` edge rule, pinned by `tests/unit/test_gen1_battle_driver_pins.py`).

Fixture: `tools/gen1_battle_fixture.py` builds `.cache/battle-fixtures/<title>_battle.SaveRAM`
(disclosed fixture, not campaign proof; manifest alongside): the committed one-mon save plus
a Ditto L5 with TRANSFORM and one POTION, checksum recomputed per `save.asm` CalcCheckSum,
originals untouched. Menus are driven by `lua/tests/gen1_battle_driver.lua` from the source
state machine (`DisplayBattleMenu` columns, 1-based move cursor, `wMaxMenuItem = moves+1`).

Measured on red (`.cache/battle-force-red-kb2kcysz`), blue (`blue-4dbbf4d8`) and yellow (`yellow-izinj1z6`), every
frame one `step_one`, every row server-verified, SRAM byte-identical, hook_frame == frame:

- **benched**: PKMN switch to Ditto with Squirtle linked; `ExecutePlayerMove+0` reached on
  the switch turn (`wActionResultOrTookBattleTurn` = 1) with `wPlayerMonNumber` = 1 → the
  executor wrote party slot 0 HP `00 14 → 00 00` and status `00` only (3 bytes; the battle
  struct untouched, Ditto kept fighting). Server outcome `benched`. The engine then refused
  to send Squirtle back out (party menu, `HasMonFainted`), screenshot
  `benched_switch_back_refused.png`; a later `loop_head` for the same member was refused
  `already fainted` with zero writes.
- **Transform**: Ditto (not linked) committed TRANSFORM through the move menu;
  `wPlayerBattleStatus3` bit 3 set, `wBattleMonSpecies` = the wild species (Pidgey 36 /
  Rattata 165); the non-linked `player_action` row on that turn was refused with zero writes.
- **transformed linked mon**: with the transformed Ditto linked, 30 menu steps →
  `not_reached` only; the next `loop_head` wrote `wBattleMonHP 00 0c → 00 00` (decision
  accepted the party-slot identity despite the foreign battle struct), the engine fainted
  Ditto, both mons were down, black-out, whited out to Pallet with the party healed
  (`after_battle.png`). Server outcome `fainted`.

Not closed in round 2: the ACTIVE-branch write at `ExecutePlayerMove+0` under `step_one`
(proven only under the harness owner in round 1, `red-wityf_me`); in every bounded run the
site fired only on switch/non-linked turns and the transformed faint landed at `loop_head`.
Nothing in the source distinguishes the two sites for the write itself (§9), but the live
row is still owed. Everything else the prototype claims has now been observed on the original
engine under the bounded owner.

## 12. Round 3 live: the active branch closed (2026-09-10)

Measured on red (`.cache/battle-force-red-_szi2_ql`), blue (`blue-aw5pdf5q`) and yellow
(`yellow-jrkjd73j`) with the separate `fight_first` scenario (`scenarios=['fight_first']`:
linked Squirtle active, no switch, no Transform), every frame one `step_one`, every row
server-verified with the measured `hook_frame_offset` 0, SRAM byte-identical, hook_frame == frame:

- **fight_first**: FIGHT → first move → `ExecutePlayerMove+0` fired at frame 1819 / 3985 / 5188
  with `wPlayerMonNumber` = 0 and `wPlayerBattleStatus3` bit 3 clear; the executor wrote
  `wBattleMonHP 00 14 → 00 00` (R/B `D015/D016`, Y `D014/D015`) and `wPlayerSelectedMove
  21 → ff` (`CCDC`, Tackle → CANNOT_MOVE), nothing else. Server outcome `fainted`. The
  original engine printed "<nick> fainted!" in the next text box (`fight_first_fainted.png`)
  and offered the next party member; the driver took RUN. `fight_first_after_write.png` is
  the frame after the write, `fight_first_later.png` the settled HP bar.
- Other-branch rows kept their honest results: the `battle_entry` `loop_head` row (and on
  blue/yellow the `controls_cleanup` row) was refused `party slot is not the linked mon` with
  zero writes.
- Gate times 68 / 70 / 76 s. JUnit `.cache/junit/fight_first_{red,blue,yellow}.xml`, one
  test each, 0 failures. Test: `tests/live/test_gen1_battle_force.py::
  test_active_linked_mon_faints_at_execute_player_move_under_bounded_owner`.

With this, every branch the prototype claims (§9) has been observed on the original engine
under the bounded owner: `loop_head` (round 1), benched write plus `HasMonFainted` refusal,
Transform recognition and the transformed linked mon (round 2), and the ACTIVE-branch write at
`ExecutePlayerMove+0` (round 3). The production path stays disabled. Where this fits if the
free-run model is adopted: `EXECUTION_MODEL_PROPOSAL.md` §3, principle 5 (a short hold that
arms this authority only while a death is pending in battle).
