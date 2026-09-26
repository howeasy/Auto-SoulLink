# Patched-trade binding candidates (T1, 2026-09-26)

Read-only measurements, not hook/arena qualification. No patch, build or emulator
was run. Addresses are hexadecimal bus addresses unless explicitly ROM offsets;
ranges are half-open. Every allocation/detour below is **CANDIDATE**, not approved.

## 1. Inputs and provenance

- R: SLink `4f9f30c5df2a11dc2d3c64b8d21f8610010f7b2d`.
- G: Gen 3 `bfadb7e30b377b38061668bc585e9aea5f35c871` for RR comparisons.
- F: pret/pokefirered `c75f352304d529f6ba92d4f74b9cf8b5c3810788` (both FR/LG).
- E: pret/pokeemerald `c65e93f20a5275ab03b07d6f6411096a82a60ffd`.
- C: CFRU `b637a27898b14e25dd24d0f69a3e302f0069deb8`, a reference implementation,
  not assumed to be byte-identical to RR.

Local upstream HEADs matched F/E and the inspected files had no git diff. Source
citations below refer to those pins, not mutable upstream master. Symbols are
`data/gen3/pret/{pokefirered,pokeleafgreen,pokeemerald}.sym`; table cells identify
that file's line. FR/LG source/ROM locks are `data/gen3_sources.lock.json:3-25`;
Emerald published-symbol provenance is `data/gen3/pret/pokeemerald_provenance.json:1-21`
(symbols branch `dba968c67d85caf9595abe12a51ff739d4dc5937`).

Owner ROMs were read from `E:/Google Drive/SLink/` under the exact filenames below.
No ROM bytes are redistributed; short byte anchors identify proposed bindings.

| Title / file | Header / revision | Bytes | SHA1 | MD5 |
|---|---|---:|---|---|
| FR: `Pokemon - FireRed Version (USA).gba` | `BPRE` / 0 | 16777216 | `41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc` | `e26ee0d44e809351c8ce2d73c7400cdd` |
| LG: `Pokemon - LeafGreen Version (USA).gba` | `BPGE` / 0 | 16777216 | `574fa542ffebb14be69902d1d36f1ec0a4afd71e` | `612ca9473451fa42b51d1711031ed5f6` |
| E: `Pokemon - Emerald Version (USA, Europe).gba` | `BPEE` / 0 | 16777216 | `f3ae088181bf583e55daf962a92bb46f4f1d07b7` | `605b89b67018abcea91e693a4dd25be3` |

| Symbol file | SHA256 (raw file bytes) |
|---|---|
| `pokefirered.sym` | `6f9d2929b78d0b723180653082c9a115b4b876657af8ab1c0493b4d14151f7b0` |
| `pokeleafgreen.sym` | `6a48f1b3f3cabea043074d5d94f16cdf8b727cb529f8eced142beaa410a9ebae` |
| `pokeemerald.sym` | `a0a134789ca3dda4ae677a91a10fbe5f0d72008b83382ed56a5713d4131807cc` |

## 2. ROM payload space: exact trailing runs

Scan from EOF backwards while the byte equals the final byte. All three final
bytes are FF, not 00. The entire range below was checked as a single repeated
byte; the preceding 16 bytes show its exact boundary. Homogeneous data alone does
not establish unused ownership. Linker/source and all target-ROM references must
still be checked in T2.

| Title | ROM offset range | Bus range | Length / exact contents | Previous 16 bytes |
|---|---|---|---|---|
| FR | `0x00EB0B20..0x01000000` | `0x08EB0B20..0x09000000` | `0x14F4E0` bytes, **FF repeated exactly that many times** | `01dc64db6084d001ec64eb60d0010000` |
| LG | `0x00EB0E14..0x01000000` | `0x08EB0E14..0x09000000` | `0x14F1EC` bytes, **FF repeated exactly that many times** | `01dc64db6084d001ec64eb60d0010000` |
| E | `0x00E3CF64..0x01000000` | `0x08E3CF64..0x09000000` | `0x1C309C` bytes, **FF repeated exactly that many times** | `00000000000000000000000000000000` |

These tails are **outside the ±4 MiB Thumb BL displacement** used by the existing
RR hook builder. Its explicit bound is R `patch/tools/build.py:117-128`; RR links
at `0x08378F70` (`patch/src/slink.ld:6`). No contiguous FF run of at least 4096 bytes
was found in ROM offsets `[0,0x400500)` on any of FR/LG/E. This does not rule out
smaller veneers or source-proven unused non-FF space. T2 must choose and prove a
near veneer or a correctly relocated entry detour; changing only CODE_BASE fails.
Do not transplant RR's Battle Calc/CFRU hook list (`patch/tools/build.py:58-95`).

## 3. EWRAM: candidates and a concrete RR-layout collision

| Title | Highest named nonempty object end | CANDIDATE tail | Size | Symbol evidence |
|---|---|---|---|---|
| FR | `0x0203FBB0` after `__malloc_current_mallinfo` | `0x0203FBB0..0x02040000` | `0x450` | `pokefirered.sym:609` |
| LG | `0x0203FBB0` after `__malloc_current_mallinfo` | `0x0203FBB0..0x02040000` | `0x450` | `pokeleafgreen.sym:609` |
| E | `0x0203CF64` after `sRayScene` | `0x0203CF64..0x02040000` | `0x309C` | `pokeemerald.sym:708` |

FR/LG's `__malloc_av_` occupies `0x0203F76C..0x0203FB74` (`*.sym:603`).
RR's mailbox starts at `0x0203F800` (G `patch/src/handlers.c:14`): direct reuse
**overlaps that allocator object**. Its 600-byte blob buffer starts at
`0x0203FA00` (G same file, `SLINK_BLOB_BUF` definition), also overlapping. Do not
reuse the full RR arena in FR/LG. A smaller transaction ABI, proven reservation,
or controlled native allocation needs a separate T2 ownership decision.

E's nominal tail is larger, but neither its symbol gap nor RR's historical paint
probe establishes E's lifecycle/DMA safety. E heap is `0x02000000+0x1C000`
(`pokeemerald.sym:1`; E `include/malloc.h:13`). Candidates require reset/init,
menu/scene/heap/interrupt ownership and canary/stack proof before admission.

## 4. Execution addresses, signatures and ROM byte anchors

Function addresses are **even code addresses**; Thumb call pointers use address|1.
A symbol's presence is SOURCE, not permission to enter it in an arbitrary state.
Each cell gives address, function size, first 16 ROM bytes, then `.sym` line.
The ROM hashes in §1 bind these bytes; no runtime call was made.

| Function | FR | LG | E |
|---|---|---|---|
| `CallCallbacks` | `08000510` / `0x34` / `10b5f4f001fe00280fd13bf1a9f90006` / `pokefirered.sym:946` | `08000510` / `0x34` / `10b5f4f0edfd00280fd13bf195f90006` / `pokeleafgreen.sym:946` | `0800051C` / `0x24` / `10b5074c2068002801d0e6f2d3fd6068` / `pokeemerald.sym:1100` |
| `DoInGameTradeScene` | `08054440` / `0x30` / `00b581b015f07cfa08480a2122f0e6ff` / `pokefirered.sym:2835` | `08054440` / `0x30` / `00b581b015f07cfa08480a2122f0e6ff` / `pokeleafgreen.sym:2835` | `0807F0E4` / `0x2C` / `00b581b019f0b4fe07480a2129f05eff` / `pokeemerald.sym:4255` |
| `TradeMons` | `0805080C` / `0xE8` / `f0b54f464646c0b481b00c1c0006000e` / `pokefirered.sym:2810` | `0805080C` / `0xE8` / `f0b54f464646c0b481b00c1c0006000e` / `pokeleafgreen.sym:2810` | `0807B4D0` / `0xE8` / `f0b54f464646c0b481b00c1c0006000e` / `pokeemerald.sym:4230` |
| `GetEvolutionTargetSpecies` | `08042EC4` / `0x2F0` / `f0b557464e464546e0b485b080460906` / `pokefirered.sym:2422` | `08042EC4` / `0x2F0` / `f0b557464e464546e0b485b080460906` / `pokeleafgreen.sym:2422` | `0806D098` / `0x328` / `f0b557464e464546e0b485b080460906` / `pokeemerald.sym:3818` |
| `TradeEvolutionScene` | `080CE540` / `0x1D0` / `f0b557464e464546e0b486b0041c0d1c` / `pokefirered.sym:8398` | `080CE514` / `0x1D0` / `f0b557464e464546e0b486b0041c0d1c` / `pokeleafgreen.sym:8400` | `0813E1D4` / `0x1D0` / `f0b557464e464546e0b486b0041c0d1c` / `pokeemerald.sym:11880` |
| `TrySavingData` | `080DA364` / `0x48` / `30b50006050e09480468012c09d1281c` / `pokefirered.sym:8717` | `080DA338` / `0x48` / `30b50006050e09480468012c09d1281c` / `pokeleafgreen.sym:8719` | `08153338` / `0x48` / `30b50006050e09480468012c09d1281c` / `pokeemerald.sym:12429` |
| `ChoosePartyMonByMenuType` | `081283A8` / `0x3C` / `00b583b00006000e084a094911600021` / `pokefirered.sym:11344` | `08128380` / `0x3C` / `00b583b00006000e084a094911600021` / `pokeleafgreen.sym:11346` | `081B9354` / `0x3C` / `00b583b00006000e084a094911600021` / `pokeemerald.sym:15512` |
| `CB2_FadeFromPartyMenu` | `081283E4` / `0x18` / `00b555f70bfc03480a214ff715f80120` / `pokefirered.sym:11345` | `081283BC` / `0x18` / `00b555f709fc03480a214ff729f80120` / `pokeleafgreen.sym:11347` | `081B93C8` / `0x18` / `00b5f5f669fe03480a21eff6edfd0120` / `pokeemerald.sym:15514` |
| `Task_PartyMenuWaitForFade` | `081283FC` / `0x24` / `10b50006040e52f735fb0006002806d0` / `pokefirered.sym:11346` | `081283D4` / `0x24` / `10b50006040e52f733fb0006002806d0` / `pokeleafgreen.sym:11348` | `081B93E0` / `0x24` / `10b50006040ef2f609fd0006002806d0` / `pokeemerald.sym:15515` |
| `ScriptContext_SetupScript` | `08069AE4` / `0x44` / `30b5051cfff786fffff76cfffff73eff` / `pokefirered.sym:4492` | `08069AE4` / `0x44` / `30b5051cfff786fffff76cfffff73eff` / `pokeleafgreen.sym:4492` | `08098EF8` / `0x38` / `30b5051c084c0949094a201cfff7d8fe` / `pokeemerald.sym:5921` |
| `Task_InGameTrade` | `08054470` / `0x3C` / `10b50006040e0948c179802008400028` / `pokefirered.sym:2836` | `08054470` / `0x3C` / `10b50006040e0948c179802008400028` / `pokeleafgreen.sym:2836` | `0807F110` / `0x3C` / `10b50006040e0948c179802008400028` / `pokeemerald.sym:4256` |
| `CB2_InitInGameTrade` | `080505CC` / `0x1D4` / `30b583b006488721c900401800780c28` / `pokefirered.sym:2807` | `080505CC` / `0x1D4` / `30b583b006488721c900401800780c28` / `pokeleafgreen.sym:2807` | `0807B270` / `0x1F4` / `70b5464640b483b006488721c9004018` / `pokeemerald.sym:4227` |
| `CB2_InGameTrade` | `08050948` / `0x1E` / `00b500f0e3fa26f013feb2f749fab6f7` / `pokefirered.sym:2812` | `08050948` / `0x1E` / `00b500f0e3fa26f013feb2f749fab6f7` / `pokeleafgreen.sym:2812` | `0807B60C` / `0x1E` / `00b500f0dbfa2df07bfd89f7aff88bf7` / `pokeemerald.sym:4232` |
| `CB2_Overworld` | `080565B4` / `0x2C` / `10b50948c079c009041c002c02d00020` / `pokefirered.sym:2971` | `080565B4` / `0x2C` / `10b50948c079c009041c002c02d00020` / `pokeleafgreen.sym:2971` | `08085E5C` / `0x2C` / `10b50948c079c009041c002c02d00020` / `pokeemerald.sym:4471` |
| `CB2_ReturnToField` | `080567DC` / `0x2C` / `00b5fff725fe012806d10248a9f7acfe` / `pokefirered.sym:2980` | `080567DC` / `0x2C` / `00b5fff725fe012806d10248a9f7acfe` / `pokeleafgreen.sym:2980` | `080860C8` / `0x2C` / `00b5fff75ffe012806d102487af734fa` / `pokeemerald.sym:4482` |

C signatures / source anchors:

| Function | Signature and source |
|---|---|
| CallCallbacks | `static void(void)`; F `src/main.c:241-250`, E `src/main.c:188-195`. |
| DoInGameTradeScene | `void(void)`; F `src/trade_scene.c:2774-2789`, E `src/trade.c:4845-4858`. |
| TradeMons | `static void(u8 playerPartyIdx, u8 partnerPartyIdx)`; F `src/trade_scene.c:1054`, E `src/trade.c:3102`. It is record swap, not final evolution/save. |
| GetEvolutionTargetSpecies | `u16(struct Pokemon *, u8 mode, u16 evolutionItem)`; F `src/pokemon.c:5025`, E `src/pokemon.c:5503`. |
| TradeEvolutionScene | `void(struct Pokemon *, u16 postEvoSpecies, u8 preEvoSpriteId, u8 partyId)`; F `src/evolution_scene.c:470`, E `src/evolution_scene.c:468`. |
| TrySavingData | `u8(u8 saveType)`; F `src/save.c:701`, E `src/save.c:765`. `SAVE_NORMAL=0`: F `include/save.h:45-53`, E `include/save.h:53-61`. Native context and result verification remain T2 work. |
| ChoosePartyMonByMenuType | `void(u8 menuType)` F `src/party_menu.c:6321-6341`; E is `static void UNUSED(u8)` at `src/party_menu.c:6202-6205`, but retained in the pinned binary. Do not require an exported C symbol when injecting; source-overlay builds need a deliberate wrapper. |
| ScriptContext_SetupScript | `void(const u8 *ptr)`; F `src/script.c:347`, E `src/script.c:241`. RR calls this interface by the older name ScriptContext1_SetupScript (G handlers.c:526-531). |
| callback functions | `void(void)` except `CB2_FadeFromPartyMenu` is `bool8(void)` (F `party_menu.c:6327`, E `party_menu.c:6217`); Task functions are `void(u8 taskId)` (F `trade_scene.c:2782`, E `trade.c:4852`). |

`PARTY_MENU_TYPE_CHOOSE_SINGLE_MON=3` is the F constant
(F `include/constants/party_menu.h:58`); E independently defines
`PARTY_MENU_TYPE_CHOOSE_MON=3` (E `include/constants/party_menu.h:57`). The chooser
sets `gFieldCallback2` and native fade-return re-enables script execution; calling
InitPartyMenu directly lost that lifecycle in RR (G handlers.c:1030-1057).

`TrySavingData` returns `SAVE_STATUS_OK=1` only after the native saving path reports
no damaged sectors; missing flash/failure returns `SAVE_STATUS_ERROR=0xFF`
(F `src/save.c:701-719`; E `src/save.c:765-783`; both `include/save.h:35-38`).
The return value must be checked; this does not by itself qualify the caller,
saved evolved-party contents or cold reload.

### CallCallbacks hook equivalence is not byte equivalence

RR G uses `HOOK_SITE=0x0800051A` in FR's CallCallbacks, substituting the help-system
call (G `patch/tools/build.py:63`; F `src/main.c:243`). On **FR** the original BL
bytes at ROM `0x51A` are `3bf1a9f9`; **LG** has `3bf195f9`. Preserve the original
save-failure/help guards and register/result semantics; LG's original callee is
not FR's numerical address. Check the complete instruction span, not just BL.

**E** has no RunSaveFailedScreen/RunHelpSystemCallback calls in CallCallbacks
(E `src/main.c:188-195`). Candidate unconditional detour is the function entry
`0x0800051C`, bytes `10b5074c20680028`; the prologue includes PC-relative loading.
A detour must relocate/replay it correctly and preserve both callbacks. This is
NOT a four-byte drop-in replacement for RR's `0x0800051A`. No hook is approved yet.

RR comparison: DoInGameTradeScene=0x08054440 and chooser=0x081283A8 happen to match
FR here (G handlers.c:464,1039); do not infer that other calls or LG match.
Its GetEvolutionTargetSpecies entry is redirected (see §6). The RR patch has no
native-save tail in its trade scene; field return ACK is not save completion
(G handlers.c:1119-1141). Do not transplant link-save callbacks as a normal save:
E `src/trade.c:4676-4695` waits on a link handshake.

## 5. Party, special-variable and callback data symbols

Cells: address / size / exact symbol-file line. RAM values were not sampled.
`gMain.callback1/+0`, `callback2/+4`, `savedCallback/+8` are declared in
F `include/main.h:12-17` and E `include/main.h:8-13`.

| Symbol | FR | LG | E |
|---|---|---|---|
| `gMain` | `030030F0` / `0x43C` / `pokefirered.sym:745` | `030030F0` / `0x43C` / `pokeleafgreen.sym:745` | `030022C0` / `0x43C` / `pokeemerald.sym:894` |
| `gFieldCallback` | `03005020` / `0x4` / `pokefirered.sym:815` | `03005020` / `0x4` / `pokeleafgreen.sym:815` | `03005DAC` / `0x4` / `pokeemerald.sym:969` |
| `gFieldCallback2` | `03005024` / `0x4` / `pokefirered.sym:816` | `03005024` / `0x4` / `pokeleafgreen.sym:816` | `03005DB0` / `0x4` / `pokeemerald.sym:970` |
| `gCB2_AfterEvolution` | `0300537C` / `0x4` / `pokefirered.sym:843` | `0300537C` / `0x4` / `pokeleafgreen.sym:843` | `030061E8` / `0x4` / `pokeemerald.sym:1009` |
| `gSelectedTradeMonPositions` | `02031DA4` / `0x2` / `pokefirered.sym:180` | `02031DA4` / `0x2` / `pokeleafgreen.sym:180` | `02032298` / `0x2` / `pokeemerald.sym:221` |
| `gSpecialVar_0x8004` | `020370C0` / `0x2` / `pokefirered.sym:223` | `020370C0` / `0x2` / `pokeleafgreen.sym:223` | `020375E0` / `0x2` / `pokeemerald.sym:266` |
| `gSpecialVar_0x8005` | `020370C2` / `0x2` / `pokefirered.sym:224` | `020370C2` / `0x2` / `pokeleafgreen.sym:224` | `020375E2` / `0x2` / `pokeemerald.sym:267` |
| `gSpecialVar_Result` | `020370D0` / `0x2` / `pokefirered.sym:231` | `020370D0` / `0x2` / `pokeleafgreen.sym:231` | `020375F0` / `0x2` / `pokeemerald.sym:274` |
| `gPlayerParty` | `02024284` / `0x258` / `pokefirered.sym:161` | `02024284` / `0x258` / `pokeleafgreen.sym:161` | `020244EC` / `0x258` / `pokeemerald.sym:202` |
| `gPlayerPartyCount` | `02024029` / `0x1` / `pokefirered.sym:158` | `02024029` / `0x1` / `pokeleafgreen.sym:158` | `020244E9` / `0x1` / `pokeemerald.sym:200` |
| `gEnemyParty` | `0202402C` / `0x258` / `pokefirered.sym:160` | `0202402C` / `0x258` / `pokeleafgreen.sym:160` | `02024744` / `0x258` / `pokeemerald.sym:203` |
| `gEnemyPartyCount` | `0202402A` / `0x1` / `pokefirered.sym:159` | `0202402A` / `0x1` / `pokeleafgreen.sym:159` | `020244EA` / `0x1` / `pokeemerald.sym:201` |
| `gStringVar1` | `02021CD0` / `0x20` / `pokefirered.sym:27` | `02021CD0` / `0x20` / `pokeleafgreen.sym:27` | `02021CC4` / `0x100` / `pokeemerald.sym:24` |
| `gStringVar2` | `02021CF0` / `0x14` / `pokefirered.sym:28` | `02021CF0` / `0x14` / `pokeleafgreen.sym:28` | `02021DC4` / `0x100` / `pokeemerald.sym:25` |
| `gStringVar3` | `02021D04` / `0x14` / `pokefirered.sym:29` | `02021D04` / `0x14` / `pokeleafgreen.sym:29` | `02021EC4` / `0x100` / `pokeemerald.sym:26` |
| `gStringVar4` | `02021D18` / `0x3E8` / `pokefirered.sym:30` | `02021D18` / `0x3E8` / `pokeleafgreen.sym:30` | `02021FC4` / `0x3E8` / `pokeemerald.sym:27` |
| `gTasks` | `03005090` / `0x280` / `pokefirered.sym:829` | `03005090` / `0x280` / `pokeleafgreen.sym:829` | `03005E00` / `0x280` / `pokeemerald.sym:980` |
| `gSaveBlock1Ptr` | `03005008` / `0x4` / `pokefirered.sym:809` | `03005008` / `0x4` / `pokeleafgreen.sym:809` | `03005D8C` / `0x4` / `pokeemerald.sym:961` |
| `gSaveBlock2Ptr` | `0300500C` / `0x4` / `pokefirered.sym:810` | `0300500C` / `0x4` / `pokeleafgreen.sym:810` | `03005D90` / `0x4` / `pokeemerald.sym:962` |
| `sGlobalScriptContextStatus` | `03000EA8` / `0x1` / `pokefirered.sym:663` | `03000EA8` / `0x1` / `pokeleafgreen.sym:663` | `03000E38` / `0x1` / `pokeemerald.sym:782` |

RR uses FR-like party/special-var addresses (G handlers.c:351-355,445-451),
100-byte plaintext CFRU records and a 10-char nickname / 7-char OT cap.
Do not read encrypted vanilla records with RR plaintext offsets. Use native
GetMonData or the title codec. Bound the source field AND destination: FR/LG/RR
Var1=32 and Var3=20; E's Var1/2/3 are 256 each (symbol sizes above).
Terminate even a completely full nickname before StringExpandPlaceholders;
G handlers.c:1127-1140 documents the actual RR overrun and fix. Test every title
with the fullname case in `lua/tests/test_live_tradescene.lua` before enabling it.

## 6. RR trade evolutions: binary evidence, not FR inference

Owner `Pokemon - Radical Red.gba`: 32 MiB, SHA1
`964f951a0fdaf209e4ea1344883ef0d557bb3a80`, MD5
`8529f3a45d32bce4da637976fcf269d4`. It retains trade evolution data and a dispatch
for methods 5/6. This proves SOURCE availability, not a played receipt/evolution.

- ROM `0x42EC4`: `004b184755380909` redirects the vanilla evolution entry to
  Thumb `0x09093855` (code `0x09093854`).
- RR's trade-scene region calls that entry at bus `0x0805225C`, `0x080536B8`
  and `0x080537D0`, each after setting R1=1 and R2=0. F names mode 1
  `EVO_MODE_TRADE` (`include/constants/pokemon.h:285`); the active RR redirect
  and table, rather than that F name alone, establish the binary connection.
- That routine's literal at bus `0x09093B48` contains `0x08042F6C`; ROM
  `0x42F6C` contains table pointer `0x097CD9B0`.
- Code `0x09093886` shifts species by 7, `0x0909388A` shifts entry by 3;
  `0x09093D30` compares entry count with 16: 128 bytes/species, 16×8-byte records.
- Code `0x09093D24..0x09093D36` loads method, compares 5 then 6, and for 5 loads
  target at +4. C `include/pokemon.h:582-591` names 5=EVO_TRADE, 6=EVO_TRADE_ITEM,
  7=EVO_ITEM; C `src/evolution.c:330-338` implements the trade-mode cases.
- C's default EVOS_PER_MON=5 is NOT RR's row stride; binary geometry above wins
  (C `src/config.h:141`). Do not read the obsolete BPRE.ld table address as RR data.

| Species | First two records ROM offset | Exact 16 bytes | Decoded (method,param,target,extra) |
|---|---|---|---|
| 64 Kadabra | `0x17CF9B0` | `07005700410000000500000041000000` | `(7, 87, 65, 0)`, `(5, 0, 65, 0)` |
| 67 Machoke | `0x17CFB30` | `07005700440000000500000044000000` | `(7, 87, 68, 0)`, `(5, 0, 68, 0)` |
| 75 Graveler | `0x17CFF30` | `070057004c000000050000004c000000` | `(7, 87, 76, 0)`, `(5, 0, 76, 0)` |
| 93 Haunter | `0x17D0830` | `070057005e000000050000005e000000` | `(7, 87, 94, 0)`, `(5, 0, 94, 0)` |

These records retain method 5 alongside method 7/parameter 87. Do not disable
RR receipt evolution merely because item alternatives exist. Other species/form
rules remain cartridge-owned; no assertion of universal trade evolutions follows.
Use an eligible table-proven mon in the future RR native evolution/save/reload test.
Species IDs are C `include/constants/species.h:69,72,80,98`.

## 7. Reproduction and limits

The measurements use Python `Path.read_bytes()`, `hashlib.sha1/md5/sha256`, symbol
rows split as `address binding size name`, and `struct.unpack_from('<4H', ...)`.
For each ROM: `end=len(rom); start=end`, decrement start while
`rom[start-1]==rom[-1]`; verify `rom[start:end] == bytes([rom[-1]])*(end-start)`.
ROM address conversion is `offset = bus - 0x08000000`. Function anchors are
`rom[offset:offset+16]`. Compare all hashes in §1 before reusing results.

Disassembly command (read-only; use the existing ARM objdump):

```powershell
& 'E:/Google Drive/SLink/patch/vendor/armgcc/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin/arm-none-eabi-objdump.exe' -D -b binary -m arm -M force-thumb --adjust-vma=0x08000000 --start-address=0x09093854 --stop-address=0x09093DB0 'E:/Google Drive/SLink/Pokemon - Radical Red.gba'
```

No fixed arena, veneer, save-entry context or runtime completion oracle is approved
by this appendix. T2 must still prove free-space ownership, payload fit, instruction
relocation, function calling conventions/context, normal-save return handling,
full-name bounds, and clean versus companion admission. No code/build/emulator run
was performed in T1; no ROM or binary artifact is committed.
