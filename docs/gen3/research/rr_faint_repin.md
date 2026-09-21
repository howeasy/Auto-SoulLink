# RR faint: replaced dispatch table and proposed capture

Card gen3-P3-R3, 2026-09-21. Binary/source research only; no Python, emulator, code/pack edits or commits. Companion `patch/build/slink_RR.gba` MD5 was read and verified as **bf8e94a01c0aee0aa7eb37c7333329af**. Bytes below were read with PowerShell `[IO.File]::ReadAllBytes`, `[BitConverter]::ToUInt32/ToUInt16`, and `[Convert]::ToHexString`. ROM offset means file offset; GBA address is offset + 0x08000000. Thumb function pointers carry bit 0; hook addresses do not.

## Finding: the surviving vanilla table is not the runners' selected table

**Confirmed:** no head trampoline is needed to replace this dispatch. Three vanilla runner bodies retain their instruction sequence but load a different table through their literal pool. Source semantics are `gBattleScriptingCommandsTable[gBattlescriptCurrInstr[0]]()` (`E:/Google Drive/SLink/.cache/pret/pokefirered/src/battle_main.c:3942-3960`, checkout pinned c75f352 in `docs/gen3/research/pins.md:8-10`). Symbols: `data/gen3/pret/pokefirered.sym:1642-1643,1692`.

| Runner entry (even) | LDR instruction | Halfword | Pool ROM offset | FR word | RR companion word |
|---|---|---|---|---|---|
| RunBattleScriptCommands_PopCallbacksStack 0x08015C00 | 0x08015C50 | 0x4906 (`ldr r1,[pc,#24]`) | 0x00015C6C | 0x0825011C | **0x0903EF20** |
| RunBattleScriptCommands 0x08015C74 | 0x08015C7E | 0x4906 | 0x00015C98 | 0x0825011C | **0x0903EF20** |
| HandleAction_RunBattleScript 0x0801D030 | 0x0801D03A | 0x4906 | 0x0001D054 | 0x0825011C | **0x0903EF20** |

The LDR pool calculation was decoded as `align(instruction_address+4,4) + 4*imm8`. At 0x08015C74 the RR bytes are `00B507480068002808D10649064800680078800040180068CDF18CFF01BC0047`; the table pointer at offset 0x15C98 follows the return. This loads the script byte, multiplies it by four, indexes the selected table, loads its function pointer and calls indirectly. FR differs at the table literal, not this runner instruction sequence (read ranges: FR/RR ROM offsets 0x15C74..0x15C9F). The other two literal substitutions were checked independently at the offsets above.

Vanilla's table remains at 0x0825011C (`pokefirered.sym:26867`), and its opcode 0x19 slot at **ROM 0x00250180** still contains `AD120208` = **0x080212AD**. That reference alone did not prove execution reachability: the three runners now select another table. This is the missing edge in `docs/gen3/research/rr_site_reachability.md:18-26,76-79`'s static literal census.

### Active RR opcode entry

`0x0903EF20 + 0x19*4 = 0x0903EF84`, ROM **0x0103EF84**:

```text
BDE50909 A1150208 69E90909 41160208
```

Thus opcode **0x19 -> 0x0909E5BD**, executable entry **0x0909E5BC** (ROM **0x0109E5BC**). Opcode 0x1A still points to 0x080215A1, while 0x1B points to 0x0909E969. Entry bytes for the new 0x19 body:

```text
F0B5C44C23685E789B7885B0C24D002B
```

This is not the body at 0x080212AC, so the existing capture at 0x080213C8 cannot witness these invocations. The physical silent-faint receipt is `docs/gen3/probes/shadow_rr_play_2026-09-21.txt` (wild_faint leg and conclusion); the exact mechanism above is independently established by bytes, not inferred from silence.

## Upstream name and matching semantics

The pinned CFRU function is **`atk19_tryfaintmon`**, in [src/general_bs_commands.c:1172-1283](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/general_bs_commands.c#L1172-L1283), not `src/battle_script_commands.c` (that URL returned 404). Its normal branch checks present battler and zero HP, records faint state, then applies player/tag-battle qualification before incrementing the saturating player counter and adjusting friendship ([lines 1224-1239](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/general_bs_commands.c#L1224-L1239)). The opposite branch updates the opponent counter. Upstream source is the semantic map; **RR address 0x0909E5BC is established by its binary table, not by BPRE.ld**. CFRU source pin/linker provenance: `docs/gen3/research/pins.md:124-146`.

The old vanilla capture contract is after the player counter increment, including its saturated path (`docs/gen3_engine_sites.md:118-136`). Do not hook the new function entry and call every invocation a faint: opcode argument/HP/side paths can return without such a transition.

## Exact proposed re-pin (SOURCE/BINARY candidate; LIVE OPEN)

Choose the common **player-only post-counter join at 0x0909E6EC**, not the increment-only tail at 0x0909E8C6. The latter would miss saturation.

### Decoded branch evidence

Halfwords and literals below are read from the RR companion ROM; instruction addresses minus 0x08000000 are their file offsets.

```text
0909E6C4 4B83   ldr r3,[pc,...]       ; literal 0109E8D4 = 02023BC4 (gActiveBattler)
0909E6C6 4F92   ldr r7,[pc,...]       ; literal 0109E910 = 03004F90 (gBattleResults)
0909E6C8 9302   str r3,[sp,#8]
... player qualification branches precede the following hit-marker/counter block ...
0909E6DA 2380   movs r3,#128
0909E6DC 6832   ldr r2,[r6]
0909E6DE 03DB   lsls r3,r3,#15
0909E6E0 4313   orrs r3,r2
0909E6E2 6033   str r3,[r6]
0909E6E4 783B   ldrb r3,[r7]         ; player counter offset 0
0909E6E6 2BFF   cmp r3,#255
0909E6E8 D000   beq 0909E6EC         ; saturated: skip increment
0909E6EA E0EA   b   0909E8C2
0909E6EC 9B02   ldr r3,[sp,#8]       ; CAPTURE HERE, both player paths join
0909E6EE 7818   ldrb r0,[r3]         ; active battler for friendship call
0909E6F0 4B88   ldr r3,[pc,...]       ; literal 0109E914 = 0802E229
0909E6F2 F006   BL prefix            ; indirect-call helper follows
0909E6F4 F915   BL suffix
...
0909E896 787B   ldrb r3,[r7,#1]      ; separate opponent-counter branch
0909E898 2BFF   cmp r3,#255
0909E89A D001   beq 0909E8A0
0909E89C 3301   adds r3,#1
0909E89E 707B   strb r3,[r7,#1]
...
0909E8C2 3301   adds r3,#1           ; player increment tail
0909E8C4 703B   strb r3,[r7]
0909E8C6 E711   b   0909E6EC
```

RAM-symbol corroboration: `data/gen3/pret/pokefirered.sym:77` gives gActiveBattler=0x02023BC4; `:800` gives gBattleResults=0x03004F90; RR profile confirms BATTLE_RESULTS_ADDR (`lua/games/gen3_frlge.lua:375-376`). The body also loads gBattleMons=0x02023BE4 from pool offset 0x0109E908; halfword 0x8D1B at 0x0909E694 reads HP at +0x28 after battler*0x58 addressing, followed by the zero test/early-out (ROM 0x0109E688..0x0109E69A). RR party/battler layout fact: `lua/games/gen3_frlge.lua:208-210`.

Proposed record fields (using the existing site-anchor-plus-offset convention):

```json
{
  "address": "0x0909E6E4",
  "capture_offset": 8,
  "rom_offset": "0x0109E6E4",
  "expected_hex": "3B78FF2B00D0EAE0029B1878884B06F0",
  "mode": "thumb",
  "point": ["R0", "R3", "R6", "R7", "R13"],
  "entry_address": "0x0909E5BC",
  "entry_expected_hex": "F0B5C44C23685E789B7885B0C24D002B"
}
```

Numbers are displayed as hex strings for review; the generator's numeric schema must be used when implementing. Function-relative capture offset is **0x130** (=0x0909E6EC-0x0909E5BC). If selecting capture itself as anchor, use address 0x0909E6EC, capture_offset=0, rom_offset=0x0109E6EC and these independently read 16 bytes:

```text
029B1878884B06F015F9039B1D68029B
```

Capture contract: player-qualified, present battler, battle HP zero; hit marker and player counter already committed (or counter already saturated). Snapshot active battler from **memory at gActiveBattler**, not R0 before its load at 0x0909E6EE; R7 points to gBattleResults and `[R13+8]` holds the active-battler address. Do not assert that party HP/status cleanup, animation, or battle return is complete. Keep consumer identity deduplication. Validate real opponent faints do not fire this player join and player counter 255 still does. Branch/capture decoding is manual Thumb decoding, not a Capstone or live receipt.

Clean RR cross-check: `E:/Google Drive/SLink/Pokemon - Radical Red.gba` has identical 16-byte samples at ROM offsets **0x15C98, 0x103EF84, 0x109E5BC, 0x109E6EC**. This checks those samples only, not a full independently requalified clean-ROM site pack.

## Coordinator exec census: eight function-start candidates

All addresses even; no interior capture point is mislabeled as a function start. Vanilla names/starts come from `data/gen3/pret/pokefirered.sym:1562,1641-1643,1692,1735`; RR replacement starts come from active table slots at ROM 0x0103EF84/0x0103EF8C and prologues.

| Function | Address | Purpose |
|---|---|---|
| BattleMainCB2 | 0x08011100 | Battle-running control |
| RunBattleScriptCommands_PopCallbacksStack | 0x08015C00 | First switched-table dispatcher |
| RunBattleScriptCommands | 0x08015C74 | Second switched-table dispatcher |
| HandleAction_RunBattleScript | 0x0801D030 | Third switched-table dispatcher |
| vanilla Cmd_tryfaintmon | 0x080212AC | Old-target comparison; do not require zero globally |
| RR atk19_tryfaintmon | 0x0909E5BC | Active opcode-0x19 target |
| RR opcode 0x1B replacement | 0x0909E968 | Adjacent faint-cleanup target; upstream name atk1B_cleareffectsonfaint at general_bs_commands.c:1302 |
| ReturnFromBattleToOverworld | 0x08015B58 | Completed-return control |

Run the function-start census from slink_prebattle.State with the real wild_faint input sequence. Merely mashing the initial loaded battle to a victory need not faint a player. The <=12 encounter budget is a scenario bound, not a guarantee of a loss on every fixture (`lua/tests/gen3_rr_scripted_play.lua:215-257`). Separately register **0x0909E6EC** (common join), **0x0909E8C4** (counter store), and old **0x080213C8**, with active-battler/side/HP/counter snapshots. Record callback address and raw R15 separately, including the store's pre/post semantics.

## Verification and NOT VERIFIED

* Companion MD5 and exact byte/literal reads above are verified. No request for the coordinator to recover expected_hex is necessary: PowerShell can read ROM bytes without Python. Re-read the two proposed slices independently before changing the generator.
* LIVE OPEN: new-body delivery, common-join delivery, player/opponent qualification, duplicate behavior, counter saturation, and RR special battle exclusions. The earlier physical result only establishes the old site was silent while other pins fired (`docs/gen3/probes/shadow_rr_play_2026-09-21.txt`, conclusion).
* No full RR function-size symbol exists here. Do not use the next embedded pool or arbitrary next push as a proven boundary. Candidate capture 0x130 is within the traced body; entry reaches its counter branch and tail returns to the join (ROM ranges above).
* No claim of byte-for-byte identity between the whole RR body and upstream CFRU. Source names/semantics are corroborative; binary dispatch and branch evidence are authoritative for this ROM. Shell network access failed and web fetched the exact pinned general_bs_commands.c instead; no downloaded source file was written.
* Outside lease: re-audit other battle-opcode site bindings against **0x0903EF20**, not the surviving vanilla table. Do not infer any particular other opcode is wrong without reading its selected target. Amend rr_site_reachability.md's blanket active-caller inference; no edits made to it or the packs.

## R5 follow-up: the missing route is extended opcode FF/23 (2026-09-21)

This section supersedes any inference above that opcode 0x19 is the sole RR player-faint source. It does not retract the verified table binding or byte decoding. New physical evidence: `docs/gen3/probes/census_rr_faint_2026-09-21.txt:1-15` records 0x1B entry 14 hits, 0x19 entry/interior/store zero, and active script runners over seven returns. **14 entry hits are not proof of 14 distinct faints or one entry per faint**: the cleanup routine is a re-entered state machine (source below). Companion MD5 rechecked: bf8e94a01c0aee0aa7eb37c7333329af.

### Entry address versus actual execution

ROM 0x0109E5BC still begins `F0B5C44C23685E789B7885B0C24D002B`: ordinary Thumb `push {r4-r7,lr}`, then literal load and field reads. Table pointer 0x0909E5BD means entry **0x0909E5BC**, not entry+4 or a location after a pool. The earlier runner instructions load the table entry and call it indirectly; they do not add an entry offset (ROM 0x00015C74..0x00015C9F; previous dispatcher table). This proves the selected address if opcode 19 executes, not that any observed battle script uses opcode 19. No evidence supports blindly moving the hook a halfword forward to fix the zero count. Delivery at adjacent extended-ROM cleanup body 0x0909E968 weakens a blanket 0x09-region callback-failure hypothesis, but cannot prove delivery at every individual address (census :2-3).

### Pinned upstream bytecode and RR secondary dispatch

Pinned source fetched directly over HTTPS in memory from `Skeli789/Complete-Fire-Red-Upgrade` revision b637a27898b14e25dd24d0f69a3e302f0069deb8 (no downloaded files):

* [battle_script_macros.s:296-312](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/battle_script_macros.s#L296-L312): `faintpokemon` remains opcode **19**; animation **1A**, cleanup **1B**.
* [battle_script_macros.s:1630-1633](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/battle_script_macros.s#L1630-L1633): `faintpokemonaftermove` emits **FF 23 00 00**. This is extended-table dispatch, **not callasm**; callasm is F8 at :1405-1408.
* [assembly/battle_scripts/general_attack_battle_scripts.s:1983-1994](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/assembly/battle_scripts/general_attack_battle_scripts.s#L1983-L1994): EerieSpell's damage path ends in prefaint effects, faintpokemonaftermove, move end. Lines 155-166 show an attacker-specific opcode19 check followed by FF23. These two mechanisms coexist; not every attack must enter 19.
* [src/new_bs_commands.c:127-135,1150-1184](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/new_bs_commands.c#L1150-L1184): `atkFF_callsecondarytable` selects the extension; **atkFF23_faintpokemonaftermove** establishes the target battler and updates the player/opponent faint counter on qualified HP-zero paths.

Binary resolution (all offsets directly read):

| Link | ROM offset | Word / decoded effect |
|---|---|---|
| primary table FF slot, 0903EF20 + FF*4 | **0103F31C** | **19D90A09**, target **090AD919**, executable **090AD918** |
| FF dispatch's secondary-table literal | **010AD934** | **20F30309** = **0903F320** |
| secondary slot 23, 0903F320 + 23*4 | **0103F3AC** | **E5EE0A09**, target **090AEEE5**, executable **090AEEE4** |
| replacement native FF23 entry | **010AEEE4** | **F0B58A4B1A788A4987B08A4D04939300** |

FF dispatch at 090AD918 loads script-pointer variable via pool 010AD930=02023D74, increments that pointer by one (to the subopcode), loads the original script's byte+1, scales by four and indexes the secondary table (halfwords at 090AD91C..090AD928: `681A 1C51 6019 7852 4B03 0092 58D3`). It calls the selected pointer via BL at 090AD92A. Thus FF/23 is a concrete alternate native faint function with a binary-resolved RR address, not speculation about callnative or a BPRE.ld guessed replacement.

**[INFERENCE, strong SOURCE/BINARY; LIVE still OPEN]** FF23 explains the observed ordinary target-faint counter changes without entering 19. The exact bytecode stream of the observed battles was not captured; confirm FF23 entry plus the interior below during a real faint before claiming that physical causal chain closed.

### Better semantic candidate: FF23 post-player-counter join

The RR FF23 body has its own player-counter commit. Literal at ROM **010AF140=03004F90** is gBattleResults; **010AF118=02023BC4** is gActiveBattler (same RAM symbols as R3). Decoded halfwords:

```text
090AEF9A 4A69    ldr r2,[pc,...]    ; gBattleResults
090AEF9C 6023    str r3,[r4]        ; player-fainted hit marker
090AEF9E 7813    ldrb r3,[r2]       ; player counter
090AEFA0 2BFF    cmp r3,#255
090AEFA2 D000    beq 090AEFA6       ; saturated path
090AEFA4 E0AB    b   090AF0FE
090AEFA6 7828    ldrb r0,[r5]       ; COMMON POST-COUNTER CAPTURE
...
090AF0FE 3301    adds r3,#1
090AF100 7013    strb r3,[r2]
090AF102 E750    b   090AEFA6
```

Proposed **additional** source, not a claim all opcode19 special cases disappear:

```text
address = 0x090AEFA6
capture_offset = 0
rom_offset = 0x010AEFA6
expected_hex = 2878664B00F0F9FF2878059B3E6800F0
entry_address = 0x090AEEE4
entry_expected_hex = F0B58A4B1A788A4987B08A4D04939300
function_relative_capture = 0xC2
mode = thumb
```

R5 points at gActiveBattler at this join; read RAM 0x02023BC4 for identity, not the not-yet-loaded R0. Keep present-battler/side qualification and identity deduplication. This matches the earlier counter-commit semantics more closely than waiting for all cleanup effects; verify counter saturation and opponent exclusion physically. Raw counter-store-only candidate is **0x090AF100**, but it misses saturation.

### Evaluate opcode1B cleanup as a second, later witness

Its primary-table slot ROM **0103EF8C** selects **0909E969 -> 0909E968**. [src/general_bs_commands.c:1392-1433](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/general_bs_commands.c#L1392-L1433) derives the active battler from the script argument and processes cleanup stages; [lines 1694-1698](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/general_bs_commands.c#L1694-L1698) reset its state and advance the script after completion. Entry can recur while buffers/effects are pending; **do not emit faint on every entry or assume 14 hits = one per faint**.

Binary identity assignment occurs at **0909E980:7033**, `strb r3,[r6]`; R6 is loaded at E97C from pool **0109EC58=02023BC4**. At entry, gActiveBattler may still name another operation; sample after this assignment, or at completion. gBattlerFainted=02023D6D (`data/gen3/pret/pokefirered.sym:100`) is not interchangeable for every script argument. Upstream faint scripts select attacker/target, while scripting-bank variants explicitly copy to FAINTED_BANK ([assembly/battle_scripts/fainting_battle_scripts.s:23-28,44-49,60-67](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/assembly/battle_scripts/fainting_battle_scripts.s#L60-L67)). These RAM names are symbol/binary evidence; they are not currently explicit gActiveBattler/gBattlerFainted fields in the RR generated profile. Integration needs a pinned field rather than a literal in production signals.

Candidate **after full cleanup's state reset and script advance**, not generic function return:

```text
0909EEC2 6823    ldr r3,[r4]
0909EEC4 33D0    adds r3,#0xD0
0909EEC6 701A    strb r2,[r3]       ; faintEffectsState reset
0909EEC8 697B    ldr r3,[r7,#20]   ; saved script-pointer-variable address
0909EECA 681B    ldr r3,[r3]
0909EECC 697A    ldr r2,[r7,#20]
0909EECE 3302    adds r3,#2
0909EED0 6013    str r3,[r2]       ; command complete, cursor advanced
0909EED2 E6BC    b epilogue        ; CAPTURE after store
```

Record: address **0909EEC2**, capture_offset **16**, rom_offset **0109EEC2**. Use **32 bytes** if runtime validation must cover the effective hook; for the requested exact 16-byte capture slice instead choose **address=0909EED2**, offset=0, rom_offset=0109EED2, expected_hex=**BCE638E00302C5510708E95107084A3D**. Entry anchor at 0909E968 is **F0B5BA4B8BB002AF7B611B685878D4F7**; entry-relative capture is **0x56A**. This is a manually decoded candidate, LIVE OPEN. Some of the 16-byte slice following the branch is adjacent code/pool data; it is an integrity anchor, not sixteen bytes of sequentially executed instructions.

Filter the sampled active battler through its position/side: gBattlerPositions=02023BD6 (`pokefirered.sym:81`), not merely battler index==0, and preserve RR tag/borrowed-party policy. Resolve current party index using the already-profiled BATTLER_PARTY_INDEXES_ADDR (`lua/games/gen3_frlge.lua:209`). Cleanup is later than faint commitment and can include abilities/form changes; it is a fallback/lifecycle witness with explicit semantics, not automatically an equivalent replacement for counter-commit capture.

### Revised discriminating census: 10 starts plus separate interiors

| Even function start | Identity / source |
|---|---|
| 090AD918 | primary FF secondary-table dispatcher, table FF slot ROM0103F31C |
| **090AEEE4** | **atkFF23_faintpokemonaftermove**, secondary23 slot ROM0103F3AC |
| 0909E5BC | original opcode19 target, compare special-case activity |
| 0909E968 | opcode1B cleanup, established physical positive control |
| **080215A0** | opcode1A animation; RR slot ROM0103EF88 = 080215A1; sym:1736 |
| 08018F90 | vanilla HandleFaintedMonActions **trampoline**, sym:1682 |
| **09093044** | RR HandleFaintedMonActions replacement: ROM00018F90 bytes `0048004745300909` load/bx target09093045; entry ROM01093044 bytes `8022F0B5BE4B85B002931B68134000D0` |
| 0801D030 | known-live HandleAction_RunBattleScript dispatcher |
| 08015C00 | known-live PopCallbacksStack dispatcher |
| 08015B58 | battle-return control |

The HandleFaintedMonActions upstream implementation is in pinned `src/end_turn.c:2081` onward. Its RR address above is derived from the binary trampoline, not assigned from source ordering. Separately sample **090AEFA6** (FF23 common commit), **090AF100** (counter store), **0909E982** (cleanup after battler assignment), **0909EED2** (cleanup complete), and old19 capture **0909E6EC**. Track player/opponent identity, script cursor/opcode, HP, counter before/after, and occurrence order; do not combine these interiors into a purported function-start list.

### Remaining unknowns and evidence correction

The plausible contradiction is now resolved at SOURCE/BINARY level: RR has two faint-command mechanisms, and the extended FF23 body independently commits the counter. It is NOT yet resolved by a physical FF23 fire. Opcode19 remains meaningful for other attacker/scripted faint paths; do not delete it merely because seven ordinary battles missed it. The source macro encoding contradicts the suggestion that FF always means generic callasm: FF is secondary dispatch, F8 is callasm (pinned macro lines above).

This follow-up used direct pinned raw-source HTTP reads for line numbers; earlier web-rendered/raw cache views returned different line positions for the same URL. The URLs and **direct-fetch line ranges in this R5 section** are the current citation basis. No source downloads were saved. No tests/emulator/Python or commits were run, and no file beyond this appended note was edited.