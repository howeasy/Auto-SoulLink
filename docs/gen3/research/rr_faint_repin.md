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
