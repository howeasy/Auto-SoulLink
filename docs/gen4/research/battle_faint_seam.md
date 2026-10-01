# In-battle faint: the execution seam and the two-copy write (plan card C1-8, OFFLINE half)

**Status.** Authored offline, with no emulator. Nothing below is a PHYSICAL result. The row o probe
([`lua/tests/probe_gen4_battle_faint.lua`](../../../lua/tests/probe_gen4_battle_faint.lua)) is written
and model-tested but **not yet run**. This note refines [battle_faint.md](battle_faint.md) (C1-7) and
[battle_pointer.md](battle_pointer.md).

**Pins.**
- pokeheartgold @ad7a3afa (`E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold`). Every `file:line` below
  is that tree. The asm counts as source.
- HG ROM sha1 `4fcded0e…`; hge build `cb2dc435…` (fork @fc5175764, built at `.cache/gen4/hge/build-fc5175764983/`).
  Both are pinned in `data/gen4_sources.lock.json`.
- pret xMAP `.cache/gen4/xmap/heartgoldus.xMAP`.

**Tags.**
- **SOURCE**: pinned source text or asm.
- **FILE**: SOURCE-class, read from the pinned ROM bytes. Re-proved on every offline run by
  `tests/live/test_gen4_battle_faint.py::test_seam_pins_and_flow_hold_in_the_pinned_rom_bytes`.
- **MODEL**: derived reasoning or a synthetic-world test, never a game observation.
- **PHYSICAL-OPEN**: needs the live run, stated as the question.

## 0. Verdict

1. **A complete pinned seam exists for every turn that continues: the entry of `BattleControllerPlayer_TurnEnd`.**
   - HG: `0x0224A958`, ov12, Thumb. hge: **the same address, byte-identical** (FILE).
   - It runs after all damage/effect scripts and end-of-turn work, and **before** `ov12_0224DD18`, `ov12_0224D7EC`
     and `ov12_0224D540`. TurnEnd is reachable only from command 11 (§1).
   - A seam hit proves that a normal turn is complete; the hook fires per dispatch, so the double
     `BattleContext_Main` call (§3) does not hide it. **[SOURCE+FILE]**
2. **It is not complete on "immediately".**
   - A command arriving while command 5 (selection screen) is on screen waits for the player's input
     **plus** the rest of that turn. There is no bound.
   - No proven seam writes at command 5. Writing there leaves a 0-HP battler on the input screen, which the game
     never produces (§2). **[SOURCE+MODEL]**
   - D7's "immediately" therefore becomes "at the end of the current turn's resolution". PLAN line 159 requires the
     owner to accept that bound. The coordinator must obtain it.
3. **A frame-boundary poll alone is not complete.**
   - The `11 → 12 → TurnEnd` interval can fall inside one `BattleContext_Main` pair, so a boundary poll never
     sees command 11 or 12 for that turn. **[SOURCE]**
   - A poll that writes in an earlier state (command 9-11, mid-script) has ≤1-frame latency but unproven safety. **[MODEL]**
   - The probe measures how often a poll misses a real seam hit (`hits_without_poll_sight`). **[PHYSICAL-OPEN]**
4. **hge still runs the vanilla TurnEnd sweep.**
   - TurnEnd, `ov12_0224D540`, `ov12_0224D7EC`, `ov12_0224DD18`, UpdateFieldConditionExtra and `CheckIfAnyoneShouldFaint`
     are byte-identical to vanilla in the pinned build's ov12. The dispatch-table entries for commands 5, 9-12, 40
     and 44 match. **[FILE]**
   - The seam address therefore needs no per-build change. Only `BattleContext_Main` (ov130 `0x023C64F8`) and the
     script command `BtlCmd_TryFaintMon` (ov130 `0x023CEDD0`) are replaced (§5).

## 1. Command graph (SOURCE)

`ctx->command` is a u32 at `ctx+8` (`include/battle/battle.h`; hge `server_seq_no`, `include/battle.h:1283`; the
TurnEnd asm reads `[ctx,#8]`, FILE). It is dispatched through `sPlayerBattleCommands` at `battle_controller_player.c:97-146`.

```
 5 SELECTION_SCREEN_INPUT  (:264-633; stays until every local battler has chosen: advance at :621-625)
 6 CALC_EXECUTION_ORDER -> 7 BEFORE_TURN (:724-776) -> 8 (ov12_02249460, :778-801; per-battler action dispatch)
 8 -> 13 FIGHT_INPUT | 14 ITEM | 15 POKEMON | 16 RUN | 17-21 safari/contest -> ... -> 40 (ov12_0224D368, :3318-3361) -> 8
 8 -> 9 UPDATE_FIELD_CONDITION       (:799; TryFaintMon :828, EXP :831, win/lose sweep D7EC :834; -> 10 at :1139)
 10 UPDATE_MON_CONDITION             (:1173; TryFaintMon :1181, D7EC :1189;                     -> 11 at :1559)
 11 UPDATE_FIELD_CONDITION_EXTRA     (:1571-1656; TryFaintMon :1575; Future Sight :1581-1609 (script 121 :1601);
                                       Perish Song :1610-1636 (script 102 :1629); Trick Room :1637-1648;  -> 12 at :1655)
 12 TURN_END                         (:1658-1677; DD18 :1659, D7EC :1663, D540 :1667, then TRAINER_MESSAGE :1676)
```

- **TurnEnd is entered from exactly one place.** `CONTROLLER_COMMAND_TURN_END` is assigned only at `:1655`, in
  command 11 (grep over the tree). **[SOURCE]**
- **Every non-terminal turn passes 8 → 9 → 10 → 11 → 12.**
  - Each of the four jumps (`:799`, `:1139`, `:1559`, `:1655`) is the sole assignment of its target.
  - Terminal exits bypass TurnEnd: a successful run (`RunInput` → script → command 44, `:1793`, `:1800`), a capture, and the
    outcome override in `BattleContext_Main` (`:160-164`, command 42). **[SOURCE]**
- **TurnEnd is re-entered within a turn.** When `ov12_0224D540` starts a replacement script it sets
  `commandNext = cmd` (`:3447`, `:3470`), where `cmd` is TURN_END. After the script, TurnEnd runs again. A hook
  must therefore be single-shot per write. **[SOURCE]**
- **The sweeps read the party copy.**
  - `ov12_0224D7EC` (`:3495-`) and `ov12_0224D540` (`:3416-3493`) test `ctx->battleMons[b].hp == 0` first.
  - They then sum `GetMonData(mon, MON_DATA_HP)` over the party (`:3436-3458`, `:3517-3541`).
  - So both HP copies must be zero (battle_faint.md §3). **[SOURCE]**
- **Disassembly of the seam (FILE, both ROMs):**

  ```
  0224A958 38b5     push {r3,r4,r5,lr}      ; r0 = BattleSystem*, r1 = BattleContext*
  0224A964 03f0d8f9 bl   0224DD18           ; EXP-gain script check
  0224A970 02f03cff bl   0224D7EC           ; win/lose sweep
  0224A97C 02f0e0fd bl   0224D540           ; replacement sweep
  0224A9A8 0220 / a060  movs r0,#2 ; str r0,[r4,#8]   ; command = TRAINER_MESSAGE
  ```

  The seam is the first instruction. r0/r1 at the hook equal `bs`/`ctx`, which the probe checks against the
  zero-hook chain. The hook word is `38b50c1c` (LE u32 `0x1C0CB538`).

## 2. Coverage matrix (HG; hge identical, §5)

S1 = hook at the TurnEnd entry `0x0224A958`. S2 = hook at the UpdateFieldConditionExtra entry `0x0224A70C`
(command 11), which would also let the writer set the FAINTED bit before `TryFaintMon` (`:1575`). Poll = a
frame-boundary read-then-write.

| Path where the command can arrive | S1 (TurnEnd entry) | S2 (UFCE entry) | Poll |
|---|---|---|---|
| **Selection screen, command 5 idle** (`:264-633`) | **Not covered while idle.** Held until the turn ends. Latency = player idle time + turn. **[SOURCE]** | Same | A write at command 5 is possible but unsafe: the game guarantees `hp > 0` at command 5 (TurnEnd replaces fainted battlers before TRAINER_MESSAGE → … → 5, `:1671-1676`). No HP-0 attacker guard was found in FightInput → command 23 (`:1679-1708`, `:2647-2713`; negative grep, **MODEL**). The first win/lose re-check is command 40 after the first action (`:3332`), and the replacement sweep only in TurnEnd. The dead mon would act. **[SOURCE+MODEL]** |
| **Future Sight / Perish Song** in UFCE (`:1581-1636`) | **Covered.** TurnEnd runs only after the state machine finishes (`:1655`). If the effect KOs the target, HP is already 0: no-op (resolve returns `noop`). **[SOURCE]** | Covered; re-enters after each script (`commandNext = command`, `:1602`, `:1630`) | Intervals can be sub-frame |
| **Switch** (`:1770-1778` → script → command 41 `:3364-3368` → 40 → 8) | **Covered** for turns that continue. The write target is chosen at the hook by `selectedMonIndex`, so a benched or just-withdrawn mon is "not active", handled by the checkpoint path. **[SOURCE]** | Covered | n/a |
| **Run** (`:1780-1807`) | **Failed run: covered** (→ 40 → … → 12). **Successful run: not covered**: the battle ends via command 44 and TurnEnd never runs. The held command is "interrupted D7" (PLAN line 162). **[SOURCE]** | Same | n/a |
| **Double `BattleContext_Main` per update** (`asm/overlay_12_022378C0.s:702-814`; calls at `:721` link, `:745` + `:781` non-link) | **Covered.** The hook fires on entry to TurnEnd regardless of which call dispatches it. **[SOURCE]** | Same | **Not covered.** The non-link path calls Main, runs the clients, and calls Main again iff the first call did not end the battle (`:745-:781`, guards `[bs+0x23FC]`, `[bs+0x23FE]`). A turn can therefore run command 11 and TurnEnd inside one update, and a boundary poll sees neither. **[SOURCE]** |
| **Enemy KO / win before TurnEnd** | Not reached: win/lose is decided at 9 / 10 / 40 (`:834`, `:1189`, `:3332`). The held command is unfulfilled/interrupted. **[SOURCE]** | Same | n/a |
| **Link, multi, tag** | Out of scope (resolve refuses `battleType & 0x1C`). **[MODEL]** | | |

- **Two properties the seam must keep**, both implemented in the probe's hook callback:
  1. Drop wrong-overlay hits first. The even address is shared by other images (profile `collides_with`; ov2 is
     mapped at `0x02245B80`). The probe compares the in-RAM bytes with the pin, `r0 == bs`, `r1 == ctx` and
     `ctx.command == 12` before it acts.
  2. Do not write at S1 with the FAINTED bit set. `TryFaintMon` (`:3658-3682`) is never called from TurnEnd, so the
     bit would stay set into the next turn. The faint-bit variant therefore uses S2 only (scenario
     `seam_ufce_bit`).
- **What S1 gives up versus S2** **[MODEL]**: the normal faint script (animation, message, EXP flag) is skipped.
  Whether the sweeps alone produce an acceptable replacement/loss presentation is a **PHYSICAL-OPEN** question
  (D12 list below).

## 3. The double call, stated precisely (SOURCE)

`ov12_02238358` (`0x02238358`, 0xE4 bytes) loads `battleType` (`[bs+0x2C] & 4`, LINK).
- Link: one `bl BattleContext_Main` (`:721`).
- Non-link: `bl BattleContext_Main` (`:745`) → `ov12_02258E54` and `ov12_022621C4` per client → a second `bl BattleContext_Main`
  (`:781`) when `[bs+0x23FE] == 0` → clients again.

Each call dispatches **one** command through the table (`battle_controller_player.c:166`). Consequences:
- Two commands can execute within one emulated frame (for example 11 then 12).
- A frame-end reader has no guarantee of seeing either.
- An execution hook at the command function does not have this problem, because it fires on each dispatch.

## 4. Polling alternative and its latency (MODEL, with the measurement named)

If the hook path is rejected, the only other writer is a per-frame poll that writes when `ctx.command ∈ {9, 10, 11, 12}`.

- **Latency** is ≤ 1 frame after the poll sees the state.
- **Not complete** (§3): it can see none of them for a turn.
- **Safety is unproven in the scripts.** With `command == 22` (RUN_SCRIPT) during Future Sight/Perish/poison, a script
  may be mid-arithmetic on `battleMons[b].hp` (for example `hpCalc = hp * -1`, `:1622`).
- The probe's `hits_without_poll_sight` field counts seam hits for which the poll never saw command 11/12 within ±1
  frame. A non-zero count is the physical refutation. **[PHYSICAL-OPEN]**

**Recommendation.** Use the S1 execution hook as the writer and the frame poll only as the arming, residency and
disposition logic.
- Register the hook only while ov12 is resident (phase `battle`).
- Take one of the production battle phase's 3 handles (`profile.phases.battle.cap`). The probe itself arms up to 4 (seam,
  TurnEnd observer, `HealParty`, `Task_Blackout`), the C1-1 instrumentation budget.
- Report `interrupted/unfulfilled` when the battle ends without a seam hit.

## 5. hge (pinned build `cb2dc435`, FILE unless stated)

- **Unchanged in ov12 (byte-identical extents):**
  - `BattleControllerPlayer_TurnEnd` `0x0224A958`+0x56 and UpdateFieldConditionExtra `0x0224A70C`+0x24C;
  - `ov12_0224D540`+0x2AC, `ov12_0224D7EC`+0x378 and `ov12_0224DD18`+0x5A;
  - `CheckIfAnyoneShouldFaint` (vanilla `TryFaintMon`) `0x0224DC74`+0xA4 and `CopyBattleMonToPartyMon` `0x02250C40`+0x30;
  - `ov12_02238358`+0xE4 (the double-call site).
- **Dispatch table** `sPlayerBattleCommands = 0x0226CA90` (`rom.ld:710`): entries 5, 9, 10, 11, 12, 40 and 44 equal the vanilla
  values (`…8849`, `…94dd`, `…9cc5`, `…a70d`, `…a959`, `…d369`, `…d505`).
- **Replaced (the seam is not among them):**
  - `BattleContext_Main` `0x022486B0` is an 8-byte trampoline to ov130 `0x023C64F8` (`hooks`: `0012 BattleContext_Main 022486B0 2`;
    `.cache/gen4/hge/offsets.ini:51`). The C still dispatches `sPlayerBattleCommands[ctx->server_seq_no]`
    (`src/battle/battle_controller_player.c:89`), so TurnEnd is reached exactly as in vanilla. The
    `DEBUG_BATTLE_SCENARIOS` blocks are compiled out in the default build (`Makefile:126-130`).
  - `BtlCmd_TryFaintMon` → ov130 `0x023CEDD0` (`hooks:150`; `battle_script_commands.c:5286-5313`). It adds a spread-move
    guard and writes the FAINTED bit into `server_status_flag`. The bit position (`<< 24`) and the consuming
    `CheckIfAnyoneShouldFaint` bytes are unchanged.
  - Command 9 (`ServerFieldConditionCheck`, `hooks:376`) and command 40 (`BattleController_MoveEnd`, `hooks:494`) are
    replaced by C. They still call `CheckIfAnyoneShouldFaint` (`0x0224DC74`: `ServerFieldConditionCheck.c:127`,
    `ServerDoPostMoveEffects.c:349`, `battle_item.c:153`), `ServerGetExpCheck` (`0x0224DD18`) and `ServerZenmetsuCheck`
    (`0x0224D7EC`) (`BattleController_MoveEnd.c:43-46`).
  - Command 10 differs by one byte at `0x0224A112` (`0x10` → `0x08`, cause not analysed); UpdateFieldConditionExtra and TurnEnd are untouched.
- **Layout (SOURCE)**, same as vanilla for every offset this contract uses:
  - `bsys->sp` (the ctx) `+0x30` (`include/battle.h:1587`).
  - `trainerParty[4]` `+0x68`.
  - `sel_mons_no` `+0x219C`; `battlemon[]` `+0x2D40`, stride 0xC0.
  - `hp` s32 `+0x4C` (`:905`), `personal_rnd` `+0x68`, `id_no` `+0x74`.
  - Party tail `hp` u16 at `0x8E`; `party_lock`/`box_lock` bits at record `+4` (`include/pokemon.h:304-305`, `:341-359`).
- **hge differences that do not touch the write:**
  - The battler **ability** is a u16 at `0x7A` (vanilla u8 `0x27`, dead in hge). The contract never reads it.
  - The ctx grows past vanilla's 0x3158 (`hg_engine.md` §4b).
- **PHYSICAL-OPEN for hge.**
  - The `man+0x0C == 12` chain validation (hge allocates its own `BattleStruct` in `ServerInit`, `hooks:387`).
  - Live hook residency (ov130 is auto-loaded with ov12).
  - The write effect itself.
  - No hge battle state exists; the `hge` rows of the live wrapper are named skips until one is produced by a genuine route.

## 6. The two-copy write contract (both ROMs; PIDs/offsets SOURCE, hge identical)

```
fs   = u32[0x021D4158]; sub0 = u32[fs]; man = u32[sub0+4];  require u32[man+0x0C] == 12   (ov12 resident)
bs   = u32[man+0x1C];   ctx  = u32[bs+0x30];    btype = u32[bs+0x2C]   (refuse link|multi|tag: btype & 0x1C)
b in {0,1} (singles) or {0..3} (doubles); owner(b) = b (singles) | b&1 (doubles); local iff owner(b) == 0
slot = u8[ctx+0x219C+b]   (6 = no mon on field: never writable)       mon = ctx+0x2D40+0xC0*b
party = u32[bs+0x68+4*owner]; count = u32[party+4] in 1..6; slot < count; rec = party+8+0xEC*slot
```

**Identity (all must agree; species equality is never used):**
- PID = `u32[rec]` and OTID from the box-decrypted block A (box seed = `u16[rec+6]`, 64 words, checksum must equal;
  block A offset from the PID shuffle row `(pid & 0x3E000) >> 13`; OTID = block A `+4`).
- The same PID `u32[mon+0x68]` and OTID `u32[mon+0x74]` in the **BattleMon**.
- The linked key. The probe derives it from the live **save-array party**, an independent source:
  `SaveData` (`[0x021D2228]`) `+0x10 + u32[SaveData+0x23014+2*16+8]`, party id 2. The production writer takes the
  server's key.

**Lock state (refuse, never XOR a plaintext record):**
- `u16[rec+4]` bit0 `partyDecrypted`, bit1 `boxDecrypted` (`include/pokemon_types_def.h:157-158`).
- Either bit set means plaintext representation: refuse and retry at the next hook.

**Spans (prevalidated together; no rollback):**

| Span | Address | Width | Value written |
|---|---|---|---|
| battle HP | `mon+0x4C` | **4 bytes, s32** | `0` |
| party HP | `rec+0x8E` | 2 bytes, u16, PID-stream encrypted | `0 ^ ks3`, where ks3 = keystream word 3 (the 4th LCG output, `seed = pid`, `*0x41C64E6D+0x6073`, `>>16`) |

- **Prevalidation** refuses: battle HP outside `0..maxHp`, party HP outside `0..partyMax` (word 4), `maxHp` outside
  1..999, one copy 0 and the other not (incoherent), more than one matching battler (ambiguous), no match.
- **Not written:** the party-tail checksum (the tail is outside the box checksum), `status`, the FAINTED bit
  (`ctx+0x213C`, S2 variant only), `battlerIdFainted`, `totalTimesFainted`.
- **Readback** must read all four battle-HP bytes `{0,0,0,0}` and `party_plain == 0`, with the record's PID and lock
  bits undisturbed. A 2-byte battle write leaves a stale high half that this catches.
- **Partial emission** means mutated memory with a failed verify. Report `fatal/partial`, revoke further writes, never
  emit success.

## 7. What the live run proves

The probe starts from the C1-9 FIGHT-menu state (Pidgey L2 wild, Cyndaquil battler 0, one-mon party, singles).

**Instrument controls (shadow memory of the real live bytes, no game write). Each can go red:**
- wrong PID, wrong OTID, wrong slot, sentinel slot 6, locked flag: all refused;
- battle-only write, party-only write, and a 2-byte battle write over a stale high half: all caught by readback;
- positive controls: the true key resolves and a full write verifies.

The model test proves they go red: disabling `identity`, `slot`, `locked`, `verify_party` or `verify_high` each turns
`judge_controls` red with the named failure. The same fault is available live (`SLINK_GEN4_FAINT_FAULT`), and the
wrapper asserts the run FAILs before any write.

**Scenarios (one emulator boot each):**

| Scenario | Kind | Writes | Oracle / what is recorded |
|---|---|---|---|
| `seam_turnend` | **primary** | both copies at S1 | game result byte `bs+0x2420 == 2` (LOSE); save-array party HP read at `HealParty` entry (`0x02090C1C`) must be 0 (copy-back carried the zero, **pre-heal**); post-heal HP = max; seam hits; latency; map before/after (whiteout warp) |
| `battle_only`, `party_only` | control | one copy at S1 | readback must go red, and the full-write oracle must be red: a single-copy write must not reach the save as zero + LOSE |
| `seam_ufce_bit` | exploratory | both + FAINTED bit at S2 | does the normal faint subscript (animation, message) run; does the hook at S2 cover the turn; no gate |
| `poll_fightmenu` | exploratory | both at command 5, frame boundary | what the game does with a 0-HP battler on the input screen (idle effect, then an input-driven turn); no gate |

**Per run it records:**
- Hook and observer hits: `hits`, `wrong_image`, `stale`, `bad_state`, and the frames of each hit.
- `hits_without_poll_sight` (§4).
- Latency: `cmd_to_write`, `input_frames` and `write_to_effect`, in frames, from the state load.
- The `HealParty` and `Task_Blackout` hit frames.
- A change-log trace of command, result byte, battle HP, party HP, selected slot and saved HP.
- Screenshots: pre, move list, after the write, final.

The receipt is `PROBE o <status>` + `RESULT:`, in the grammar `row_o()` in `test_gen4_probe_gates.py` consumes. PASS requires
`oracle` and `negative_control`; the primary scenario's receipt is copied to `C:/slink/g4/faint/row_o_<title>.txt`.

**What stays OPEN after a green HG run:**
- the replacement prompt, which needs a 2+ mon natural party (no such state; do not stage one);
- doubles, TAG and multi ownership, NPC follower, trainer battles, win/status-turn separately, and Future Sight/Perish/
  switch/run as live paths (the matrix rows are SOURCE only);
- hge physical (no state), and the owner's acceptance of the end-of-turn latency bound;
- the presentation question: does the HP bar and faint animation read acceptably when the faint script is skipped?
  Screenshots are evidence, not a verdict.

**Assumptions the first live run may break (it would show up as OPEN, not a false PASS):**
- D-pad + A navigates the HGSS battle menu (FIGHT → move 2 = Leer, chosen so the turn never KOs the wild Pidgey).
- `event.on_bus_exec` fires at an overlay Thumb address under melonDS with JIT off (C1-1 rows a/b are the independent evidence).

## 8. Reproduce the FILE claims

```
python -m pytest tests/live/test_gen4_battle_faint.py -m 'not live' -q    # pins, the BL targets, dispatch table, both ROMs
python -m pytest tests/unit/test_gen4_battle_faint_model.py -q              # crypto vs gen4_codec, guards, controls, judge
```

Byte comparison used for §5: ov12 of the HG ROM vs the hge build at `0x0224A958`, `0x0224A70C`, `0x0224D540`,
`0x0224D7EC`, `0x0224DC74`, `0x0224DD18`, `0x02238358`, `0x02250C40`, and the table at `0x0226CA90` (via ndspy
`loadArm9Overlays()[12]`). `BattleContext_Main` differs (trampoline) and `0x0224A112` differs by one byte.

## 9. Live result, HG (card C1-8B, 2026-10-01; PHYSICAL, singles wild Pidgey L2, one-mon party)

Receipts: `C:/slink/g4/faint/heartgold_<scenario>_<hhmmss>/receipt.txt` (final runs 163846 `seam_turnend`, 164008
`seam_ufce_bit`, 163929 `battle_only`, 163948 `party_only`); primary receipts copied to
`C:/slink/g4/faint/row_o_heartgold_<scenario>.txt`.

| Scenario | Status | Write cmd / frame latency | Game result byte `bs+0x2420` | Save-array HP at `HealParty` entry / after |
|---|---|---|---|---|
| `seam_turnend` (S1, HP only) | PASS | cmd 12; write -> result 1 frame | 2 (LOSE) | 0 / 20 |
| `seam_ufce_bit` (S2 + FAINTED bit) | PASS | cmd 11; write -> result 157 frames | 2 (LOSE) | 0 / 20 |
| `battle_only` (control) | PASS (red as required) | no result in 1500 frames | none | no heal |
| `party_only` (control) | PASS (red as required) | no result in 1500 frames | none | no heal |

- **Which seam gives the normal faint:** only **S2 with the FAINTED bit**. `TryFaintMon` consumed the bit at the next
  dispatch (command 22 one frame after the write): the player sprite slid out, the HP bar was removed, the faint
  message printed, then the loss message. S1 (HP only) skips all of that: the sprite and the stale `17/20` HP bar stay,
  and the game goes straight to "is out of usable Pokemon!". Screenshots: `seam_ufce_bit_w73/w157/w241.png` vs
  `seam_turnend_w71/w155.png`. Both seams reach the loss, and the zero reaches the save party before the heal; the native
  heal then restores it (`HealParty` hit 2 = the nurse).
- **Single-copy writes:** battle-only leaves the game on the party-switch screen ("already in battle") with the mon
  still alive in the party copy; readback names `party_hp_nonzero`. Party-only is undone: the game's next
  battle-to-party copy restored the HP and the battle played on (the later natural LOSE is outside the 900-frame
  effect window, so the control correctly stays red).
- **Poll coverage:** in both primary runs command 11 was never seen at a frame boundary (trace jumps 10 -> 12 in
  `seam_turnend`); the hooks fired. `hits_without_poll_sight` is 0 because it counts only command 11/12 sightings
  within +-1 frame of a hit; command 12 was seen at +-1 there.
- **Source fixes during the live run:** (1) the first A only wakes the D-pad cursor, so FIGHT needs a second A; (2) the
  effect must follow the write within 900 frames, because a later natural faint had satisfied the control oracle;
  (3) dense post-write screenshots; (4) `seam_ufce_bit` promoted to primary (owner ruling).
- **Still OPEN:** replacement prompt (2+ mon party), doubles/TAG/multi, NPC follower, trainer battles, Future Sight /
  Perish / switch / run as live paths, the `poll_fightmenu` exploratory scenario (not run), hge.
