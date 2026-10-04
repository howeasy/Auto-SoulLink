# In-battle faint: the execution seam and the two-copy write (plan card C1-8, OFFLINE half)

**Status.** Authored offline, with no emulator. Nothing below is a PHYSICAL result. The row o probe
([`lua/tests/probe_gen4_battle_faint.lua`](../../../lua/tests/probe_gen4_battle_faint.lua)) is written
and model-tested but **not yet run**. This note refines [battle_faint.md](battle_faint.md) (C1-7) and
[battle_pointer.md](battle_pointer.md).

**Pins.**
- pokeheartgold @ad7a3afa (`E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold`). Every `file:line` below
  is that tree. The asm counts as source.
- HG ROM sha1 `4fcded0e…`; hge build `cb2dc435…` (fork @fc5175764, built at `.cache/gen4/hge/build-fc5175764983/`; `.cache/` is gitignored and lives in the worktree
  checkout that ran the build, so no committed path holds the exports: they are pinned by `data/gen4_sources.lock.json`
  (`hge_offsets`, `hge_rom_gen_ld`, `hge_nm_all` sha256) and by the tracked `data/games/gen4_hge/profile.json` `hge_replacements`).
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
   - The probe MEASURES, per scenario, exact hook dispatches of both seams against frame-boundary sightings of the same command
     (`poll_vs_hook`, section 11). It is a measurement, not a falsifier of this claim. **[PHYSICAL-OPEN]**
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
  0224A958 38b5     push {r3,r4,r5,lr}      ; bytes 38 b5 = halfword 0xB538: PUSH, low byte 0x38 = r3,r4,r5, +LR
                                            ; r0 = BattleSystem*, r1 = BattleContext*
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
- The old `hits_without_poll_sight` counter restated this section and could not falsify it; it is gone. Its
  replacement, `poll_vs_hook`, compares the exact dispatch count of each seam (hooks on command 11 and 12, both armed in
  every scenario) with the frames a boundary poll saw that command. `dispatches - seen_by_poll` is the number of
  dispatches the poll missed; `seen_by_poll == dispatches` over many turns would count against the claim. It is still a
  measurement of one battle's turns, not a proof about all paths. **[PHYSICAL-OPEN]**

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
- `poll_vs_hook` (§4): exact dispatches vs boundary-poll sightings, for both seams.
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
  `seam_turnend`); the hooks fired. (The `hits_without_poll_sight` counter used for that run was 0 only because it counted command 11 OR 12
  sightings; it is replaced by `poll_vs_hook`, section 11.)
- **Source fixes during the live run:** (1) the first A only wakes the D-pad cursor, so FIGHT needs a second A; (2) the
  effect must follow the write within 900 frames, because a later natural faint had satisfied the control oracle;
  (3) dense post-write screenshots; (4) `seam_ufce_bit` promoted to primary (owner ruling).
- **Still OPEN:** replacement prompt (2+ mon party), doubles/TAG/multi, NPC follower, trainer battles, Future Sight /
  Perish / switch / run as live paths, the `poll_fightmenu` exploratory scenario (not run), hge.

## 10. Live result, hge (card C1-8C, 2026-10-01; PHYSICAL, build `cb2dc435`, singles wild Pidgey L3, Cyndaquil "POOP" L5, one-mon party)

State `C:/slink/g4/route_hge/route_hge_leg5_battle_settled.State`, save copy of `hge_a_OOO_630`, lane `C:/slink/g4/faint_hge`.
Final receipts: `heartgold_hge_seam_turnend_170701`, `..._seam_ufce_bit_170839`, `..._battle_only_170750`,
`..._party_only_170813` (each `receipt.txt`); primaries also in `C:/slink/g4/faint_hge/row_o_heartgold_hge_<scenario>.txt`.

| Scenario | Status | Seam / cmd | write -> result | Result byte | Save HP at `HealParty` entry / after |
|---|---|---|---|---|---|
| `seam_turnend` | PASS | TurnEnd `0x0224A958`, cmd 12 | 1 frame | 2 | 0 / 20 |
| `seam_ufce_bit` | PASS | **cmd 9 entry `0x022494DC`** + FAINTED bit | 188 frames | 2 | 0 / 20 |
| `battle_only`, `party_only` (controls) | PASS (red) | TurnEnd | no result in 1500 frames | none | no heal |

- **The TurnEnd seam fires on hge** (the claim of section 5 holds physically): 1 hit, 0 wrong-image/stale/bad-state;
  the replaced `BattleContext_Main` still dispatches command 12 to the vanilla TurnEnd. HG-identical oracle values.
- **hge difference: commands 10 and 11 are never dispatched.** The live trace goes `40 -> 9 -> 12` (and `9 -> 22 -> 9`
  inside a turn). hge's command 9 (`ServerFieldConditionCheck`, `hooks:376`, address from the ROM table entry 9 =
  `0x022494DC`, a trampoline) runs all end-of-turn effects, calls `CheckIfAnyoneShouldFaint` at its loop top
  (`ServerFieldConditionCheck.c:127`) and ends in TURN_END (`:1944`). The HG S2 address (`0x0224A70C`) therefore never
  fires on hge (live run 170420: 0 hits, OPEN, not a pass); the S2 seam on hge is **command 9 entry**, derived by the wrapper
  from the ROM dispatch table (`UFCE_CMD`), with the pin read from the ROM, never typed in. The write there precedes the
  end-of-turn effects of that turn (weather etc.), a slightly earlier point than HG's.
- **The FAINTED bit still drives the normal faint on hge** (`BtlCmd_TryFaintMon` replacement does not matter: the
  consumer `CheckIfAnyoneShouldFaint` is byte-identical): bit consumed within 2 frames (command 22), sprite gone, HP bar
  gone, "POOP fainted!" (`seam_ufce_bit_w146.png` in the 170540 run, same behaviour in 170839). S1 on hge, as on HG,
  leaves the sprite and a stale 17/20 bar and prints "You have no more Pokemon that can fight" (`seam_turnend_w60/w144.png`,
  run 170247).
- **`HealParty` (`0x02090C1C`) and `Task_Blackout` (`0x02052858`) are kept in hge**: identical arm9 bytes (FILE),
  and the observers fired live (blackout heal at save HP 0, nurse heal at 20).
- **hge differences handled by the pack, not by constants in the probe:** the SaveData header table is at `0x2F014`
  (pack `array_headers_off`; HG `0x23014`); `cfg.pack` feeds it and the battle offsets to the probe (`M.configure`). The
  first hge run (170202) failed `save_party` for exactly that reason before the fix.
- **Counter fix:** `hits_without_poll_sight` now looks for the seam's own command (11 HG, 9 hge) or 12.
- **Foreign EmuHawk PIDs** seen before the first hge boot: 53068 and 52416 (a gen3 duo run, `patch/build/duo_*`); untouched.

## 11. Card C1-8D (offline): review cx-fd56a73d, the 2-mon replacement path, hardened controls

**Review outcome.** The adversarial review could not break the offsets, crypto, seam ordering, FAINTED-bit/EXP separation,
hge byte identity or oracle independence. Findings and what was done:

| Finding | Disposition |
|---|---|
| BLOCKER: row o only on a ONE-mon whiteout; with 2+ mons the write takes the D540 replacement branch | New PRIMARY scenarios `seam_ufce_bit_p2` and `seam_turnend_p2` on a SYNTH 2-mon party (below). The one-mon runs are now `secondary`. |
| MAJOR: `battle_only` could PASS on a hung game | The control now needs game-side liveness AND the specific wrong outcome (below). |
| MAJOR: `emu.getregister` in `on_bus_exec` may classify every hit stale | Evidence plus a visible failure mode (below). |
| MAJOR: `hits_without_poll_sight` cannot falsify | Replaced by `poll_vs_hook`, a measurement (section 4). |
| MINOR: "38b5 = push {r0,r2,r4,r5,lr}" | **The review's finding was wrong, and the follow-up review cx-f2913238 conceded it.** The bytes are little-endian: `38 b5` is the halfword `0xB538`; PUSH is `0xB4xx`/`0xB5xx` (bit 8 = LR) and the register list is the LOW byte `0x38` = bits 3,4,5 = r3,r4,r5. Capstone agrees. The FILE test decodes the halfword. The note's text was clarified, not changed. |
| MINOR: `.cache/gen4/hge/...` citations point at a directory missing from the worktree | Header now says `.cache/` is gitignored, lives in the checkout that ran the build, and names the tracked pins. |

**2-mon setup (SYNTH, disclosed).** `tools/gen4_synth_save.py party2` clones party slot 0 into slot 1 (new PID, same species, level and
OTID, nickname `SYNTH`) and writes `<out>.synth.json`. Saves made offline:
`C:/slink/g4/saves/hg_base_26310_party2.SaveRAM` (sidecar sha256 `66f657ce...`) and
`C:/slink/g4/saves/hge_a_OOO_630_party2.SaveRAM` (sidecar sha256 `ad57f5b7...`). Receipts carry `setup: SYNTH` and the
sidecar sha256; the wrapper refuses a sidecar that does not describe the save file. The clone's identical species and OTID also make the
PID:OTID discrimination real (same-species slots), which the one-mon runs could not exercise.

**New primary scenarios** (HG: cmd 11 + FAINTED bit `seam_ufce_bit_p2`, TurnEnd `seam_turnend_p2`; hge uses cmd 9 for the first):
1. Write both HP copies of slot 0 at the seam (unchanged contract).
2. Faint text advances with A. The oracle for the replacement branch is the game's own D540 flag `u32[ctx+0x13C+4*b] & 1` (FILE: D540
   clears then sets it, `movs r1,#0x4f; lsls r1,r1,#2`), with no result byte `2` and no `HealParty`/`Task_Blackout` hit.
3. Drive the party screen with normal input (Down, A, A, repeated up to 10 cycles with a screenshot per cycle) until
   `selectedMonIndex[0] == 1` **and** the BattleMon PID equals slot 1's PID (index alone is not accepted).
4. Fight on with A until the battle ends; then read the SAVE array party: slot 0 must be 0, slot 1 alive, map unchanged.
- PASS needs all of it; a LOSE byte, a heal, a whiteout warp or a slot-0 copy-back not at 0 is FAIL; anything not reached is OPEN with the reason.
- **Open input risk (cannot be tested offline):** the party-screen key sequence. Whether Down + A + A selects and confirms slot 1 in the
  REPLACE/PARTY screen is unknown; the cycles and `shot("p2_c<N>")` exist so the first live run shows it. If the sequence is wrong the run is OPEN
  ("slot 1 never sent in"), never a false PASS.

**Controls.** `battle_only` PASS now needs: readback red, game liveness (`gSystem.vblankCounter` advanced >= 90% of the elapsed frames,
`newKeys` showed our A at least 3 times; offsets from the pack's `profile.system` and pret `system.h`), AND the specific wrong outcome:
the D540 replacement flag set while the party copy was still alive. `party_only` needs the game restoring the party-copy HP. "No LOSE"
alone, which a hung game also produces, is OPEN. Revert checks: removing the liveness, the specific-outcome, the whiteout or the copy-back checks
each turns a model test red; a slot-1 index without its PID turns one red.

**Registers in the hook.** The classification reads `ARM9 r0/r1` (BattleSystem*, BattleContext*) and requires them to equal the chain-derived
pointers. Evidence they are read correctly: in every earlier live receipt (HG and hge) every counted hit passed that equality (hits > 0, `stale = 0`) and the
wrote; a wrong read could not match both pointers by accident. The receipt now also records the FIRST hit's raw `r0, r1, r15` and the chain pointers,
reports "ALL seam hits classified stale" if the read is ever suspect, and `cfg.regs=false` is a recorded fallback (chain + command + pin only,
`regs_mode: chain_only`). Both paths are exercised by the model tests.

**Plan for the lane (not run).**
1. Route to a 2-mon battle state per title on the SYNTH save, in lane `C:/slink/g4/faint2`: `python tools/gen4_routes.py run --save
   C:/slink/g4/saves/hg_base_26310_party2.SaveRAM --lane faint2 --tag p2hg` (hge: `--game hge --errand pokegear --save ..._party2.SaveRAM --tag p2hge`).
2. `SLINK_LIVE=1 pytest tests/live/test_gen4_battle_faint.py -m live -k "p2 and heartgold and not hge"`, then hge; then the hardened controls and
   one regression of the two secondary one-mon scenarios per title.
3. Estimate (not measured): route 5-10 min per title, each p2 run 1-3 min (more if the party-screen sequence needs a second attempt).

## 12. Card C1-8D live, HG (lane faint2) - STOPPED after two navigation failures (2026-10-01)

SYNTH party2 route states made with the C1-9 route tool: `C:/slink/g4/faint2/p2hg_leg2_battle_settled.State` (HG, Pidgey L2, Cyndaquil
slot 0 + SYNTH clone slot 1) and `p2hge_leg5_battle_settled.State` (hge, Pidgey L3). Runs `heartgold_seam_ufce_bit_p2_201013` and `_201104`
(both OPEN, setup SYNTH, callback_errors 0):

- **The production path is reached.** Write at cmd 11 (FAINTED bit): both copies read back 0; the faint script ran one frame later (command
  22); the D540 replacement flag `ctx+0x13C` bit0 was set 155 frames after the write; no LOSE byte, no `HealParty`, no whiteout. The
  game's own replacement prompt appeared: **"Use next Pokemon?" with the buttons "Use next Pokemon" / "Flee"**
  (`seam_ufce_bit_p2_p2_c1.png`, run 201104; also `..._201013/..._p2_c1.png`).
- **Navigation failed twice (my input script, not the mechanism):** run 201013 pressed Down at the prompt and picked Flee ("Got away safely!",
  outcome 5); run 201104's first A only finished the typing of the prompt text and the next Down again picked Flee. Fix applied offline (not
  run): the replacement phase is now A (finish text), A (accept "Use next Pokemon", opens the party screen), then Down/A/A cycles for
  slot 1 (`cfg.p2_prefix`, default 2). Per the card rule the live run stopped here.
- **Poll measurement (HG, 2 turns):** cmd 11 dispatches 2, seen by the boundary poll 2; TurnEnd (cmd 12) dispatches 2, seen by the poll 0.
- Foreign EmuHawk PIDs seen (Gen 3 duo runs): 6912, 22596, 7716, 3824; untouched.

## 13. Card C1-8D live, 2026-10-01 (lane faint2, re-granted after the p2_prefix fix): PASS on HG and hge

All receipts `C:/slink/g4/faint2/<dir>/receipt.txt`; setup SYNTH (party2 saves + sidecar sha256) for the p2 rows; 0 callback errors.

| Row | Receipt dir | Status | write -> LOSE/WIN byte | repl flag after write | slot 1 in (frame) | Final saved party |
|---|---|---|---|---|---|---|
| HG `seam_ufce_bit_p2` (cmd 11 + bit) | heartgold_seam_ufce_bit_p2_201242 | PASS | WIN (1) at +2392 | +155 | 7176 | slot 0 = 0, slot 1 = 17 |
| HG `seam_turnend_p2` | heartgold_seam_turnend_p2_201327 | PASS | WIN (1) at +2266 | +1 | 7050 | 0 / 17 |
| hge `seam_turnend_p2` | heartgold_hge_seam_turnend_p2_201400 | PASS | WIN (1) at +3007 | +1 | 11127 | 0 / 14 |
| hge `seam_ufce_bit_p2` (cmd 9 + bit) | heartgold_hge_seam_ufce_bit_p2_201513 | PASS | WIN (1) at +3219 | +193 | 11337 | 0 / 14 |

- No LOSE byte, no `HealParty`, no `Task_Blackout`, map unchanged, in all four. The party screen showed `FUCM FNT 0/20` beside `SYNTH 20/20`, then "Go! SYNTH!"
  (`seam_ufce_bit_p2_p2_c3.png`, `..._p2_c5.png`, run 201242). The game's own prompt "Use next Pokemon? / Flee" is `..._p2_c1.png` / `p2_prompt.png`.
- With the S2 (FAINTED bit) seam the faint animation plays first, then the prompt (repl flag +155 HG / +193 hge frames); with S1 the replacement branch is
  entered one frame after the write and the faint animation is skipped as before.
- Controls (hardened: liveness + the specific wrong outcome) PASS on both titles: `battle_only` (repl flag set with the party copy alive, game alive:
  vblank 1587/1602 frames, A seen 74 times) and `party_only` (the game restored the party-copy HP). Receipts: heartgold_battle_only_201936,
  heartgold_hge_battle_only_201958, heartgold_party_only_202021, heartgold_hge_party_only_202044.
- One-mon secondaries (regression of the current source) PASS on both titles: heartgold_seam_turnend_201610, heartgold_hge_seam_turnend_201700,
  heartgold_seam_ufce_bit_201750, heartgold_hge_seam_ufce_bit_201841 (write -> LOSE 1/1/157/188 frames; heal at save HP 0 then 20).
- Navigation: the first run of the new cut (prefix A, A, then Down/A/A) passed on HG; no navigation failure in this grant.
- Still OPEN: doubles/TAG/multi, NPC follower, trainer battles, win/status-turn as separate rows, Future Sight/Perish/switch/run as live paths. The 2-mon setup is SYNTH, disclosed.

### 13a. Corrections after follow-up review cx-f2913238 (offline, 2026-10-01)

The review accepts the four p2 PHYSICAL rows above; its findings were applied to the judge and the receipt-shape checks (no live re-run needed):

- **F3 (MAJOR), effect window.** `judge_p2` now requires `repl_flag_frame - write.frame <= M.EFFECT_WINDOW` (900 frames) or the row is OPEN,
  the same reasoning as the one-mon `party_only` run 163725 (a later, unrelated replacement is not the write's effect). The four shipped rows
  satisfy it: +155 (HG cmd 11), +1 (HG TurnEnd), +1 (hge TurnEnd), +193 (hge cmd 9). Model tests: +900 passes, +901 and +5000 are OPEN.
- **F4, WIN required.** The p2 PASS needs `outcome_final == 1`; Flee (5), caught (4) or any other ending after a valid switch-in is OPEN (LOSE stays FAIL).
  The column "write -> battle result" in the table above is therefore a WIN column for all four rows (result byte 1 in each receipt).
- **F5, receipt shape.** `check_seam_first` (wrapper, run on every live receipt that wrote, and on the shipped receipts offline) requires
  `observation.seams.<seam>.first`, `r0 == bs`, `r1 == ctx`, `r15` inside the ov12 window `[0x022378C0, +226176)` and `r15 == seam addr + 4`.
  Note: `r15` reads EVEN (the Thumb pipeline PC, addr + 4); the Thumb state is in CPSR, so "odd" is not the right test (the dispatch-table words
  are odd). Actual values from the four shipped rows:

| Receipt | seam | seam addr | first r15 | r0 = bs | r1 = ctx |
|---|---|---|---|---|---|
| heartgold_seam_ufce_bit_p2_201242 | cmd 11 | 0x0224A70C | 0x0224A710 | 0x022C020C | 0x022C32D8 |
| (same) | TurnEnd | 0x0224A958 | 0x0224A95C | 0x022C020C | 0x022C32D8 |
| heartgold_seam_turnend_p2_201327 | TurnEnd | 0x0224A958 | 0x0224A95C | 0x022C020C | 0x022C32D8 |
| (same) | cmd 11 | 0x0224A70C | 0x0224A710 | 0x022C020C | 0x022C32D8 |
| heartgold_hge_seam_turnend_p2_201400 | TurnEnd | 0x0224A958 | 0x0224A95C | 0x022D0228 | 0x022D38A4 |
| (same) | cmd 9 | 0x022494DC | 0x022494E0 | 0x022D0228 | 0x022D38A4 |
| heartgold_hge_seam_ufce_bit_p2_201513 | cmd 9 | 0x022494DC | 0x022494E0 | 0x022D0228 | 0x022D38A4 |
| (same) | TurnEnd | 0x0224A958 | 0x0224A95C | 0x022D0228 | 0x022D38A4 |

- **F6, poll-vs-hook figures (exact hook dispatches vs. frames a boundary poll saw that command, +-1 frame), from the shipped receipts.** A
  measurement of these battles' turns, not a proof about all paths:

| Receipt | cmd 11 / cmd 9 dispatches : seen by poll | TurnEnd (12) dispatches : seen by poll |
|---|---|---|
| HG seam_ufce_bit_p2_201242 | cmd 11: 3 : 2 | 4 : 2 |
| HG seam_turnend_p2_201327 | cmd 11: 2 : 1 | 3 : 2 |
| hge seam_turnend_p2_201400 | cmd 9: 3 : 3 | 4 : 4 |
| hge seam_ufce_bit_p2_201513 | cmd 9: 5 : 5 | 4 : 3 |

  On HG the boundary poll missed 1 to 2 dispatches per run, never all of them; on hge it missed at most one. It supports "a poll can miss", it does not bound
  how often.
- **F8, the load-bearing pair.** What makes the p2 PASS an independent proof of the production path is two game-side facts together: (1) the game's own
  D540 flag `u32[ctx+0x13C+4*b] & 1` set after the write (the replacement branch was taken, not a LOSE), and (2) the **PID-matched switch-in**:
  `selectedMonIndex[0] == 1` AND the BattleMon PID equals slot 1's PID read from the save array (index alone is not accepted; the clone shares species and
  OTID with slot 0). The remaining witnesses (no LOSE byte, no `HealParty`, WIN, final save slot 0 at 0 / slot 1 alive, same map, liveness) bound
  them but neither pair member can be dropped without the claim weakening.
