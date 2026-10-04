# hge PCStorage redirects and keyboard-withdraw observers

FILE/SOURCE inventory, 2026-10-03, implementation cut `de5ab39fb973f5fab9ad98c31cd0ccc3f7044dab`.
This document was authored on `claude/gen4-withdraw-docs`. It contains no new PHYSICAL
qualification. No emulator was run. The known D4 withdrawal remains OPEN.

## Inputs and citation keys

- **P**: `E:\Howard\hgss_archipelago-master\.tooling\pokeheartgold`, pinned pret `ad7a3afa0cfc144fe6837c410cb95b2727217f54`.
- **H**: `E:\Howard\HGEngine_ROMHack\hg-engine`, pinned hge `fc517576498305ecb5f5e1de44681c6e3822361b`.
- XH/XS are the published `40eab3c65e0e4f46f6edd90540709aa9950ca07e` map revision
  (`tools/gen4_pins.py:30-34`), separate from the P source-citation checkout.
  Addresses were validated against the pinned ROM, not inferred from a fresh rebuild.
- **XH**: `E:\Google Drive\SLink\.claude\worktrees\gen4-support-framework-dfd5e2\.cache\gen4\xmap\heartgoldus.xMAP`; **XS**: `E:\Google Drive\SLink\.claude\worktrees\gen4-support-framework-dfd5e2\.cache\gen4\xmap\soulsilverus.xMAP` (published xMAPs).
- **N**: `E:\Google Drive\SLink\.claude\worktrees\gen4-support-framework-dfd5e2\.cache\gen4\hge\nm_all.txt`. `build/linked.o` resolves to ov129.
- **O**: `E:\Google Drive\SLink\.claude\worktrees\gen4-support-framework-dfd5e2\.cache\gen4\hge\offsets.ini`; **L**: `E:\Google Drive\SLink\.claude\worktrees\gen4-support-framework-dfd5e2\.cache\gen4\hge\rom_gen.ld`.
- Repository-relative references below are to this Gen4 implementation cut. The docs
  worktree has no `.cache/gen4`; the existing main-worktree cache above was read only.

ROM inputs are the pinned `tools/gen4_pins.py:24-29,64-89` locations:
HG SHA1 `4fcded0e2713dc03929845de631d0932ea2b5a37`,
SS `f8dc38ea20c17541a43b58c5e6d18c1732c7e582`,
hge `cb2dc435196d09c8c9209bf037240ed834f4cea1`.
Both xMAP SHA256/size pins and the O/N/L export SHA256/size pins were checked against
`data/gen4_sources.lock.json`. H source files used here matched their pinned Git blobs.

### Caller and proof labels

**D** = native scripted PC deposit; **W** = native keyboard withdraw into a party with
room, from box 0 slot 0, with no box navigation, summary, marking, wallpaper change or
release. **I** = native delete-by-index operation; **R** = declared native RELEASE
caller, currently unrouted/OPEN. Opening and closing the PC and its native SAVE suffix
are explicitly labelled where they are included. `Proved` means a SOURCE call-chain
plus FILE target proof, **not** a live execution count. `Not proved` is not proof of
absence; a listed optional/conditional caller must not become a required observer hit.

SLink caller citations shared by the table:

- **[route]**: `tools/gen4_routes.py:1092,1183-1201,1508-1535` selects the PC route and
  its preconditions; `lua/tests/gen4_route_play.lua:576-684,713-880` drives D/W natively.
- **[deposit]**: `tools/gen4_routes.py:1092` (`pc` target),
  `lua/tests/gen4_route_play.lua:576-684`; P/asm/overlay_14.s:1289-1329 calls
  `PCStorage_PlaceMonInBoxFirstEmptySlot` then removes the source PARTY mon. Ordinary
  party-to-empty-box deposit does **not** require a PC delete event.
- **[withdraw]**: `tools/gen4_routes.py:1203-1256` observes party +1, boxed slot zero,
  mon identity and native SAVE/reload; `lua/tests/gen4_route_play.lua:704-710,826-874`.
- **[delete]**: `tools/gen_gen4_pack.py:1156-1164,1293-1310` declares the delete site
  and remaining I/W/R caller scope. R is declared at :1007, not implemented as a
  `tools/gen4_routes.py` release target. A W delete hit does not qualify RELEASE.
- **[layout]**: `tools/gen4_routes.py:965-1000` supplies title PC geometry to routes;
  `lua/gen4/client.lua:805-809,897-907,930-975,982-1024,1061-1063` uses the RAM
  representation for deferred deposit/withdraw/memorial moves.
- **[census]**: `lua/tests/gen4_route_play.lua:397-414` and
  `lua/gen4/client.lua:897-907` count/decode RAM records themselves, rather than
  invoking native PCStorage count functions.
- **[dirty]**: `lua/gen4/client.lua:758-769,862-869` mirrors the per-box dirty-bit
  semantics; `tools/gen4_routes.py:1203-1226` judges the native route's flag witnesses.
- **[save]**: `tools/gen4_routes.py:1231-1256,1622-1649` and
  `lua/tests/gen4_route_play.lua:857-880` require native SAVE/battery/cold reload;
  the native successful-SAVE chain uses P/src/save.c:674-684,1220,1354-1357 and
  P/src/save_arrays.c:409-421.

**Direct-RAM executor distinction:** `lua/gen4/client.lua:758-769,921-928,982-1024`
prevalidates, writes and reads back RAM plans. Those writes do not call the game's
PCStorage functions. Native function-pin observers are appropriate for button-driven
routes, not as proof that SLink's own direct-RAM deposit/withdraw executor ran.
There is no production `release` executor at this cut (`client.lua:1061-1063` exposes
deposit, withdraw and memorialize); R below stays declared/open.

## Redirect inventory (29 storage entries plus 3 display/form patches)

All addresses below are **even instruction/site addresses** for exec observers.
Stored Thumb function pointers have bit 0 set. Every original-entry redirect was
decoded from the pinned hge ROM and matched against O and N; the table is not merely
an export-name census. ov129 is labelled resident-from-boot by the SOURCE pack
(`tools/gen_gen4_pack.py:1012`); that is not a new residency observation here.

| Vanilla symbol/site | HG/SS even address and xMAP cite | hge ov129 address and export/hook cite | ROM redirect | On fixed keyboard W path? | SLink caller dependence |
|---|---|---|---|---|---|
| `PCStorage_sizeof` | `0x02073B20` (XH:36610; XS:36610) | `0x023DB9DC` (N:144; H/hooks:433) | `ldr_bx_trampoline` | Not proved for W; P/src/save_arrays.c:307 | D/W/I/R valid save-array geometry only; [layout] |
| `PCStorage_InitializeBoxes` | `0x02073B28` (XH:36613; XS:36613) | `0x023DB9E4` (N:145; H/hooks:434) | `ldr_bx_trampoline` | Not proved for W; P/src/pokemon_storage_system.c:14-23 | D/W/I/R depend on existing storage, not a new initialization event; [layout] |
| `PCStorage_PlaceMonInFirstEmptySlotInAnyBox` | `0x02073BB8` (XH:36615; XS:36615) | `0x023DC148` (N:169; H/hooks:435) | `ldr_bx_trampoline` | Not proved for W; P/src/pokemon_storage_system.c:58 is a placement/gift caller | D empty-search/placement counterpart, outside fixed PC-deposit caller; [layout] |
| `PCStorage_PlaceMonInBoxFirstEmptySlot` | `0x02073BFC` (XH:36617; XS:36617) | `0x023DC0C0` (N:168; H/hooks:436) | `ldr_bx_trampoline` | Not proved for W; D call is P/asm/overlay_14.s:1319 | D ordinary PC placement; W not required; [deposit] |
| `PCStorage_PlaceMonInBoxByIndexPair` | `0x02073C6C` (XH:36619; XS:36619) | `0x023DC052` (N:167; H/hooks:437) | `bl_stub` | Not proved for fixed empty-party W; conditional swap calls P/asm/overlay_14.s:1092,1152 | D / native box moves and occupied-destination swap variants; not fixed keyboard W; [layout], [withdraw] |
| `PCStorage_SwapMonsInBoxByIndexPair` | `0x02073CC0` (XH:36621; XS:36621) | `0x023DC008` (N:166; H/hooks:438) | `bl_stub` | Not proved for W into empty party slot; conditional box-box swap P/asm/overlay_14.s:1381 | D box-to-box counterpart; not ordinary empty-party W; [layout] |
| `PCStorage_DeleteBoxMonByIndexPair` | `0x02073D10` (XH:36623; XS:36623) | `0x023DBFAC` (N:165; H/hooks:439) | `ldr_bx_trampoline` | Proved, transfer: P/asm/overlay_14.s:17099-17100 -> :1371-1403 -> :1119 -> :1046 | W + native I; R declared OPEN; D only box-move/swap caller, not ordinary party deposit; [withdraw], [delete] |
| `PCStorage_GetActiveBox` | `0x02073D4C` (XH:36625; XS:36625) | `0x023DBA98` (N:146; H/hooks:440) | `ldr_bx_trampoline` | Proved, app entry: P/asm/overlay_14.s:31 | D, W, R (PC launch); [layout] |
| `PCStorage_FindFirstBoxWithEmptySlot` | `0x02073D54` (XH:36627; XS:36627) | `0x023DBAC4` (N:147; H/hooks:441) | `ldr_bx_trampoline` | Not proved for W; P/src/battle/battle_command.c:7014; not the fixed W UI path | D free-box search counterpart, not an observed W call; [layout] |
| `PCStorage_FindFirstEmptySlot` | `0x02073D9C` (XH:36629; XS:36629) | `0x023DBB4C` (N:148; H/hooks:442) | `ldr_bx_trampoline` | Not proved for W; deposit/move callback P/asm/overlay_14.s:7590 | D free-slot counterpart; [layout], [deposit] |
| `PCStorage_CountEmptySpotsInAllBoxes` | `0x02073DFC` (XH:36631; XS:36631) | `0x023DBBD0` (N:149; H/hooks:443) | `ldr_bx_trampoline` | Not proved for W; P/src/application/pokegear/phone/scripts/phone_scripts_bill.c:44 | D free-capacity counterpart; no direct SLink native call; [layout] |
| `PCStorage_CountEmptySpotsInBox` | `0x02073E40` (XH:36633; XS:36633) | `0x023DBC14` (N:150; H/hooks:444) | `ldr_bx_trampoline` | Not proved for W; optional capacity callers P/asm/overlay_14.s:21957,23930 | D capacity counterpart; no direct SLink call; [layout] |
| `PCStorage_SetActiveBox` | `0x02073E84` (XH:36635; XS:36635) | `0x023DBC74` (N:151; H/hooks:445) | `ldr_bx_trampoline` | Proved, app exit: P/asm/overlay_14.s:82 | D, W, R (exit); [route] |
| `PCStorage_GetBoxWallpaper` | `0x02073E98` (XH:36638; XS:36638) | `0x023DBC92` (N:152; H/hooks:446) | `ldr_bx_trampoline` | Proved, app-start background: P/asm/overlay_14.s:11460 -> :4184 | D, W, R display only; [route] |
| `PCStorage_IsValidWallpaperId` | `0x02073EB4` (XH:36640; XS:36640) | `0x023DBCA8` (N:153; H/hooks:447) | `ldr_bx_trampoline` | Not proved for W; P/src/pokemon_storage_system.c:223-232 | No D/I/W/R storage oracle depends on wallpaper validity; [route] |
| `PCStorage_SetBoxWallpaper` | `0x02073EC8` (XH:36643; XS:36643) | `0x023DBCC0` (N:154; H/hooks:448) | `ldr_bx_trampoline` | Not proved for W; wallpaper-setting handler P/asm/overlay_14.s:16464,16469 | None of D/I/W/R mutations requires wallpaper change; [route] |
| `PCStorage_GetBoxName` | `0x02073F00` (XH:36646; XS:36646) | `0x023DBD14` (N:155; H/hooks:449) | `ldr_bx_trampoline` | Not proved here for fixed W; display callers P/asm/overlay_14.s:32106,32161 | D/W/R display only; no storage oracle depends on its text; [route] |
| `PCStorage_SetBoxName` | `0x02073F34` (XH:36649; XS:36649) | `0x023DBD68` (N:156; H/hooks:450) | `ldr_bx_trampoline` | Not proved for W; rename helper P/asm/overlay_14.s:6742 | None of D/I/W/R mutations requires renaming; [route] |
| `PCStorage_CountMonsAndEggsInBox` | `0x02073F64` (XH:36651; XS:36651) | `0x023DBDBC` (N:157; H/hooks:451) | `ldr_bx_trampoline` | Not proved unconditional for W; conditional move check P/asm/overlay_14.s:2089 and display :32200 | D/W/I/R census counterpart; [census] |
| `PCStorage_CountMonsInBox` | `0x02073FA8` (XH:36653; XS:36653) | `0x023DBE20` (N:158; H/hooks:452) | `ldr_bx_trampoline` | Not proved for W; optional PC caller P/asm/overlay_14.s:21794 | D/W/I/R census counterpart; [census] |
| `PCStorage_CountMonsInAllBoxes` | `0x02073FF8` (XH:36655; XS:36655) | `0x023DBE90` (N:159; H/hooks:453) | `ldr_bx_trampoline` | Not proved for W; P/src/scrcmd_party.c:384 | D/W/I/R census counterpart only; [census] |
| `PCStorage_GetMonDataByIndexPair` | `0x02074014` (XH:36657; XS:36657) | `0x023DBEAC` (N:160; H/hooks:454) | `bl_stub` | Not proved for fixed W; UI box-refresh caller P/asm/overlay_14.s:26852 | D/W/R optional box-refresh; representation counterpart, not a required W hit; [layout] |
| `PCStorage_GetMonByIndexPair` | `0x02074058` (XH:36659; XS:36659) | `0x023DBEFC` (N:161; H/hooks:455) | `ldr_bx_trampoline` | Proved, box selection: P/asm/overlay_14.s:3715 -> :1036; transfer :1110 | D, W, I, R record-location counterpart; [layout], [withdraw] |
| `PCStorage_UnlockBonusWallpaper` | `0x02074094` (XH:36662; XS:36662) | `0x023DBF3C` (N:162; H/hooks:456) | `ldr_bx_trampoline` | Not proved for W; P/src/scrcmd_c.c:3596 | No D/I/W/R storage oracle requires unlocking wallpaper; [route] |
| `PCStorage_IsBonusWallpaperUnlocked` | `0x020740B4` (XH:36665; XS:36665) | `0x023DBF50` (N:163; H/hooks:457) | `ldr_bx_trampoline` | Not proved for W; optional wallpaper/UI checks P/asm/overlay_14.s:23446,30009 | No D/I/W/R storage oracle depends on bonus wallpaper; [route] |
| `PCStorage_SetBoxModified` | `0x020740D8` (XH:36668; XS:36668) | `0x023DBF60` (N:164; H/hooks:458) | `ldr_bx_trampoline` | Proved, delete calls it: H/src/pokemon_storage_system.c:136-142; FILE ov129:+0x3FF2 | D, W, I, R dirty-bit counterpart; [dirty] |
| `PCStorage_SetAllBoxesModified` | `0x020740F8` (XH:36671; XS:36671) | `0x023DC1C8` (N:170; H/hooks:459) | `ldr_bx_trampoline` | Not proved for ordinary successful W; recovery fallback P/src/save.c:1226-1231 | D/W/I/R conditional SAVE recovery; [save] |
| `PCStorage_ResetBoxModifiedFlags` | `0x02074108` (XH:36674; XS:36674) | `0x023DC1E0` (N:171; H/hooks:460) | `ldr_bx_trampoline` | Proved only in successful native SAVE suffix: P/src/save.c:674-684 -> P/src/save_arrays.c:416 | D, W, I, R persistence counterpart; [save] |
| `PCStorage_GetBoxModifiedFlags` | `0x02074114` (XH:36677; XS:36677) | `0x023DC1F4` (N:172; H/hooks:461) | `ldr_bx_trampoline` | Proved only in native SAVE suffix: P/src/save.c:1220,1357 -> P/src/save_arrays.c:411 | D, W, I, R persistence counterpart; [save] |
| `ov14_021E64D0` | `0x021E64D0` (XH:89565; XS:89565; H/hooks:216 pins entry site) | `0x023DA3D0` (N:101; H/hooks:216) | `ldr_bx_trampoline` | Not proved on ordinary keyboard W; broader PC callers P/asm/overlay_14.s:12892,19257,25047,25147. **Not** an E7588/E7358 callee. | D/W/R special-form handling is a broader PC feature; no fixed-keyboard hit claimed; [route] |
| `ov14_021E7358` `+0x58` | `0x021E73B0` (XH:89732; XS:89732; H/hooks:218 pins interior displacement) | `0x023DDCF0` (N:312; H/hooks:218) | `ldr_bx_trampoline` | Proved in first box selection: E7588 calls E7358 (P/asm/overlay_14.s:3721), patched interior site +0x58. | D/W/R selected-mon display, not the transfer oracle; [route] |
| `ov14_021F528C` `+0x22` | `0x021F52AE` (XH:94567; XS:94567; H/hooks:219 pins interior displacement) | `0x023DDD04` (N:313; H/hooks:219) | `ldr_bx_trampoline` | Not independently proved unconditional for fixed W; ability-display patch within F528C, not a menu dispatcher. | D/W/R ability display only; do not require it as a transfer witness; [route] |

## Behaviour and scope changes relevant to a test

- The pack's “25 PC functions” note is stale: H/hooks:433-461 has 29 distinct
  PCStorage redirects, and N:144-172 has the same 29 entries. All 29 actual ROM
  targets matched O/N. This is FILE coverage, not 29 PHYSICAL caller receipts.
- hge storage access/delete uses 30 boxes versus vanilla 18, stride `0x1000` and
  mon stride `0x88` unchanged. `curBox` is `0x1E000`, dirty flags `0x1E004`, versus
  vanilla `0x12000`/`0x12004` (`server/adapters/gen4_codec.py:175-184`;
  H/include/constants/save.h:26-27; H/include/pokemon_storage_system.h:50-59).
  H/src/pokemon_storage_system.c:136-146 clears with `BoxMonInit` then marks the box;
  :338-361 supplies expanded-box access; :374-380 sets that flag. The normal W
  party limit remains six; its FILE checked branch is ov14:+0xBAC0/+0xBAC4.
- The first keyboard A selects the mon and opens WITHDRAW/SUMMARY/MARKING/RELEASE.
  The default action cursor is `0x22`; a second fresh A selects WITHDRAW. No third A
  or guessed destination-choice menu is in that success path. P/asm/overlay_14.s:
  16968-16998,16730-16745,23504-23547,7527-7563,17023-17113. Descriptors at
  ov14:+0x1242C are `45000000 41000000 43000000 44000000` in HG/SS/hge;
  P/files/msgdata/msg/msg_0024.gmm:274-293 supplies the four labels.
- Generic state 5 waits for work+4 to clear, then invokes the handler indexed by
  data+0x30 directly (P/asm/overlay_14.s:11617-11631). Thus a continuation can
  execute without appearing as a full-frame global proc_state. The keyboard
  transfer commits in continuation 0x55; continuation 0x57 belongs to touch-grab.
  Both reach `ov14_021E637C` / `ov14_021E6184` / `Party_AddMon`, but an observer or
  MODEL must not manufacture global state 0x57 as keyboard evidence. Existing
  party/key/boxed-slot/SAVE/reload oracles stay intact. A mandatory literal-0x57
  owner criterion needs explicit clarification before implementation.
- The corrected form-hook claim is deliberately narrow: `HandleBoxPokemonFormeChanges`
  is a real broader PC replacement (H/src/pokemon.c:728-751), not proved on the
  ordinary keyboard W chain. The proved first-selection patch is
  `BoxDisplayMon_StoreAbility` in E7358 called by E7588 (P/asm/overlay_14.s:3721).
  It preserves a u16 ability scratch value, and `BoxDisplayMon_GrabAbility`
  reads it for display (H/asm/other_hook.s:803-829). Neither relocates the requested
  grid/app/manager witness offsets or changes the action cursor.

## observer pins for hge physical runs

A function observer uses the **replacement entry in ov129** on hge, with full
pack/build registration pins and residency checks. An original ARM9 entry may
be observed as a distinct **trampoline site**; it must never be labelled the old
vanilla function body. HG and SS use the original ARM9 function entry. UI
continuation observers remain ov14 in all three titles. Addresses below must
be resolved from the pack/xMAP at launch rather than pasted into runtime code.

| Function/site | HG/SS observer | hge observer | Expected role |
|---|---|---|---|
| `PCStorage_PlaceMonInBoxFirstEmptySlot` | `0x02073BFC` (XH:36617; XS:36617) | `0x023DC0C0` (N:168) | D ordinary placement; not W |
| `PCStorage_PlaceMonInBoxByIndexPair` | `0x02073C6C` (XH:36619; XS:36619) | `0x023DC052` (N:167) | D targeted/move or occupied-destination swap variant; not fixed keyboard W |
| `PCStorage_PlaceMonInFirstEmptySlotInAnyBox` | `0x02073BB8` (XH:36615; XS:36615) | `0x023DC148` (N:169) | D/gift any-box variant; not ordinary fixed-box PC deposit |
| `PCStorage_DeleteBoxMonByIndexPair` | `0x02073D10` (XH:36623; XS:36623) | `0x023DBFAC` (N:165) | W/I and future R; not required for ordinary D |
| `PCStorage_GetMonByIndexPair` | `0x02074058` (XH:36659; XS:36659) | `0x023DBEFC` (N:161) | D/W selected boxed-record access |
| `PCStorage_GetMonDataByIndexPair` | `0x02074014` (XH:36657; XS:36657) | `0x023DBEAC` (N:160) | Optional box refresh only; not a mandatory W hit |
| `PCStorage_SetBoxModified` | `0x020740D8` (XH:36668; XS:36668) | `0x023DBF60` (N:164) | D/W native dirty-bit side effect |
| `PCStorage_GetBoxModifiedFlags` | `0x02074114` (XH:36677; XS:36677) | `0x023DC1F4` (N:172) | D/W native SAVE suffix |
| `PCStorage_ResetBoxModifiedFlags` | `0x02074108` (XH:36674; XS:36674) | `0x023DC1E0` (N:171) | D/W successful SAVE suffix |
| `CopyBoxPokemonToPokemon` | `0x02071780` (XH:36375; XS:36375) | `0x02071780` (XH:36375; XS:36375; FILE identical whole span) | W conversion body (unchanged, no redirect) |
| `Party_AddMon` | `0x02074524` (XH:36731; XS:36731) | `0x02074524` (XH:36731; XS:36731; FILE identical whole span) | W party append body (unchanged, no redirect) |
| `Party_RemoveMon` | `0x0207456C` (XH:36734; XS:36734) | `0x0207456C` (XH:36734; XS:36734; FILE identical whole span) | D party removal body (unchanged, no redirect) |
| `ov14_021EDE88` | `0x021EDE88` (XH:91950; XS:91950) | `0x021EDE88` (XH:91950; XS:91950; FILE identical whole span) | Keyboard W commit continuation 0x55; do not demand global state 0x55 be sampled |
| `ov14_021EDF28` | `0x021EDF28` (XH:91967; XS:91967) | `0x021EDF28` (XH:91967; XS:91967; FILE identical whole span) | Touch-grab continuation 0x57; not the normal keyboard W path |

This is a location catalogue, not a request to register all 14 sites at once.
A minimal W observer pair is `Party_AddMon` plus `PCStorage_DeleteBoxMonByIndexPair`;
a minimal D pair is `PCStorage_PlaceMonInBoxFirstEmptySlot` plus `Party_RemoveMon`
(addresses and citations above). Dirty-bit/mon-key/SAVE witnesses can be read from
RAM. Any extra probes must respect the existing per-phase handle budget and include
every owned registration in close/drain accounting; they do not qualify R by sharing
its delete-site address.

For deposit, hge's optional static ARM9 trampoline observer is `0x02073BFC`
(XH/XS address citation in the placement row above; H/hooks:436), while the actual
placement body observer is `0x023DC0C0` (N:168). The committed pack separates these
as `sites.pc_place_arm9_entry` and `sites.pc_place_first_in_box`; generation:
`tools/gen_gen4_pack.py:2935-2959`. ov129 must not be labelled static ARM9.
For withdraw/delete, the analogous original trampoline is `0x02073D10` (the
address citation in the delete row), while hge's function body is `0x023DBFAC`
(N:165; H/hooks:439). Do not conflate the two observations or double-count
one native call without a PHYSICAL call-chain witness.

Successful transfer observers should correlate the copied mon key, party count,
box deletion and SAVE/reload witnesses, not infer operation from a delete-site hit:
that site has other declared callers. R and delete-by-index variants remain OPEN
under `tools/gen_gen4_pack.py:1307-1310` until their own required cells run.
No hge/SS two-A native withdraw success is claimed by this FILE inventory.

### Reproduction and independent checks

Read the pinned ROMs with `tools.gen_gen4_pack.load_images` (hge raw ARM9), parse
XH/XS with `XMap`, O/N with `parse_offsets_ini`/`parse_nm`, and decode each entry
with `decode_redirect`. Assert 29 targets equal their ov129 exports; assert all
three additional interior/form sites equal their exports. Compare the entire
SS ov14 image to HG (SHA256
`d515fb04f06371d854ae5ecaed717ceb8338afde422f497bb3dc8590cc81ead5`), and compare
hge's individual handler spans rather than claiming whole-overlay equality.
hge ov14 has 48 different bytes in 22 spans; its SHA256 is
`60056c284ac062708a4e0b90699af085214df7ef9b94c6d6111c1528e3b80305`.
The dispatcher literal is ov14:+`0x56A8` (RAM `0x021EAFA8`), table at
ov14:+`0x1249C` (RAM `0x021F7D9C`), derived from the xMAP-named
`ov14_021EAF8C` body, P/asm/overlay_14.s:11369-11386. It is not an invented
xMAP data symbol. Negative FILE controls should mutate a redirect target,
context-cursor immediate, dispatch entry or modelled title geometry and fail.
This document introduces no code/test changes or runtime configuration.
