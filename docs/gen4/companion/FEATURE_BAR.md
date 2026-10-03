# Gen 4 companion patch: the "Gen 1/2 feature bar" (2026-10-02)

**Owner ruling (`DECISIONS_2026-10-01.md`, `c62fa9dd`):** the ROM companion patch is REQUIRED for the first Gen 4 RC, at the "Gen 1/2 feature set" bar.

**Source:** OMP cx-cdf9288b's inventory of the existing Gen 1/2 companions. It is coordinator-reviewed; the citations are to repo files. Status: a plan input. Nothing is built yet.

## The bar: what Gen 1 AND Gen 2 both ship (shared ABI `patch/gb/slink_abi.inc`, host `lua/gb_panel.lua` + `lua/gb_trade_lease.lua`)

| # | Feature | Gen 1/2 mechanism | Gen 4 expectation |
|---|---|---|---|
| 1 | **Beacon + ABI + capability handshake**, with liveness | A mailbox in proven-free WRAM (Gen 1 `$DEE2`, Gen 2 `$CFD8`/`$C1D9`), rewritten every service visit; capability byte; Gen 2 adds a cookie + moving counter, because a stale beacon survives New Game | No GB-style free WRAM. Needs a proven-free NDS span reachable from a fixed address, plus Gen 2's cookie + counter liveness. Everything else depends on it |
| 2 | **Native sound codes** (semantic codes, capability-gated) | ROM service behind a main-thread bridge, bounded hold, reset/fade guards (`patch/gen2/src/sfx.asm`) | The cleanest port: a semantic-code table plus one service on a recurring main-loop/field-task callback |
| 3 | **START-menu SLINK row + natively drawn info panel** (capability-gated) | Gen 2 relabels EXIT and farcalls a panel drawn with engine primitives (`panel_start.asm`, `panel.asm`); host renderer in `gb_panel.lua` | The real work is the NDS window/text system (top screen plus touch screen); the start-menu entry is an overlay script |
| 4 | **Receptionist trade** (always on for Gen 1/2, `server/manager.py:203-207`) | The receptionist script pointer is replaced; the SLT1 trade lease (`gb_trade_lease.lua`) | The dominant cost. Gen 4 records are encrypted, so follow the Gen 3 shape: the host stages blobs and the ROM commits |

## Not in the bar under current rulings (owner may reinstate)

- **Gen 2 only:** phone-call names (HGSS has no special-call surface; the panel is the proposed substitute); the title/menu version string (small; optional).
- **Out by existing rulings:**
  - peer ghost (Gen 3 only; post-RC per the 2026-09-22 ruling);
  - native message boxes (disabled for this release everywhere, `server/manager.py:189`);
  - battle calc (Gen 3 RR only).
- **Not a companion feature:** the checkpoint/safe-write evaluator is host-side on every generation. Gen 4 has `lua/gen4/safety.lua` plus the client's write plans.

## Shared NDS stack

Coordinated with the Gen 5 session (`DECISIONS_2026-10-01.md`): `patch/src/nds/common/` + `tools/nds_*`, with Gen 5 leading the first cards. Card 1 is the byte-preserving writer + pin/receipt schema. The Gen 4 constraints given to Gen 5:
- HG/SS are NOT DSi-enhanced;
- HG/SS ARM9 is BLZ-compressed, while hge's is raw;
- the hook sites are mostly in overlays;
- hge is post-patched, keyed on the pinned sha1 `cb2dc435`.

## Open questions for the owner, before the build plan

1. Trade (item 4) is the largest build. Confirm it is in the Gen 4 minimum; it is always-on for Gen 1/2.
2. Distribution: UPS against the pinned vanilla HG/SS dumps, plus a post-build patch on the pinned hge build. Two artifacts, or one?
3. Do the existing peer-ghost / native-messages deferrals carry over to Gen 4?
4. **Another lane's issue, flagged:** the Gen 1 build never advertises `CAP_TRADE` (`patch/gen1/src/slink.asm:163-164`) although it links and ships the trade. That is a contract inconsistency Gen 4 must not copy.

## Feasibility research, items 1-2 (OMP cx-408e065e, coordinator-reconciled)

**Sound (item 2): feasible from source.**
- Entry: `PlaySE(u16)` (`include/unk_02005D10.h:6`); the SE ids are flat `#define`s from 1500 (`include/constants/sndseq.h:498`).
- Four dedicated SE handles exist (`include/sound.h:19-25`, in `sSoundWork` @0x02111958). The companion reserves one and polls it with `NNS_SndPlayerReadDriverTrackInfo`, the game's own pattern at `src/sound.c:123`.
- Service tick: the field task frame (FieldSystem.taskman +0x10), which is PHYSICAL-proven to run.
- Carry over the GB hold and reset-latch discipline.
- Open: which SEQ_SE ids map to success/failure/boo/notify (a content choice).

**Mailbox (item 1): candidates only, nothing is proven.**
- **Candidates:** 15 linker gaps of 64+ bytes in the ARM9 static `.bss/.data` (largest 0x021d43b8..0x021e1618, 53856 B), plus a whole discarded `.bss` input section (`battle_arcade_game_board_data.o`, address/size only in the pinned ELF).
- **Coordinator correction:** the heaps bump-allocate from the MAIN arena low pointer (`src/heap.c:46-80`). That arena starts AFTER the static image, so gaps between static `.bss` symbols are not heap. The real risk is unlisted, symbol-less statics occupying a "gap" (a 53 KB gap before the SDK's `os_irq` data is suspicious), plus hge's heap and BSS changes.
- **Rule:** no mailbox address is accepted without (a) the pinned ELF section headers or the arena-Lo value, AND (b) a live write-watch over boot, field, battle, menus and SAVE on HG, SS AND hge proving zero foreign writes.
- **Companion code:** it lives in an overlay or the hge armips build. The HG/SS ARM9 is LZ-compressed (`rom.rsf:4`), so adding ARM9 code means recompression; this goes to the shared writer card.

## Where companion code lives (OMP cx-b95aa145, coordinator-reconciled)

**hg-engine: a source build, and the companion goes inside it.**
- hge patches out ARM9 decompression (`armips/asm/patchoutarm9compression.s:6-10`).
- Its ARM9 expansion stub is only 36 B; real code goes in overlay 129 (`armips/asm/syntheticoverlay.s:8-38`).
- New overlays are a directory drop (`overlays.mk:7,26,34`). Hooks are a flat text table (`hooks`), plus raw byte replacements (`bytereplacement`).
- Correction: `rom.ld` is an armips symbol include, not a memory layout.
- **Plan shape:** a `src/slink/` overlay module plus one `hooks` line, built by the fork's own make. No post-build patch.
- **Owner question:** this means committing to the owner's hg-engine fork (or a SLink branch of it), then a new pinned hge build.

**Vanilla HG/SS: no slack; patch the source and rebuild.**
- All 129 overlays have ramSize == file size, and 43 share the load address 0x021e5900 (ROM table via ndspy), so appended overlay code is unsafe. Of the 129 overlays, 127 are compressed, and the ARM9 is LZ.
- **Plan shape:** the Gen 2 model (`patch/gen2`: a pret source overlay). Patch the PINNED pret pokeheartgold source with a new overlay plus hooks, rebuild matching HG/SS, then diff against the pinned dumps into a distributable patch.
- One `make` of the pinned tree also yields `main.elf`, which closes the mailbox questions: the discarded `.bss`, the real gap occupancy and the arena. Not yet run; duration unknown.

**Therefore two artifacts** (the answer to open question 2, pending the owner's yes):
- the hge companion, built in the fork;
- an HG/SS patch from the pret source build.

The shared NDS stack (with Gen 5) supplies the ABI, producers, pins and receipts, and the byte-preserving writer where needed.

## Items 3-4 mechanics (OMP cx-543d1b7b, coordinator-reconciled; pinned pret + hge fork)

**START panel (item 3). Corrections:** the entry is a `StartMenuAction` row in `src/start_menu.c` (static ARM9 `start_menu.o`, 0x0203BC10.., not overlay 1; see below), not a script. The Gen 4 UI APIs are `bg_window.h` (`AddWindow`), `render_window.h` (`DrawFrameAndWindow1/2`), `font_types_def.h` (`TextPrinter`), `render_text.h` (`RenderText`) and `list_menu.h` (`ListMenuInit`), not Gen 3 names.
- **Smallest patch:** rows `START_MENU_ACTION_7` and `RETIRE` are permanently inhibited (`:303`). Clear one bit and repoint that row's `.func`/`.ident` in `sStartMenuActions` (`:174-188`). There is no table growth and no icon.
- **Hazard:** `ACTION_9`/`_10` sit at fixed display slots 7/8 (`:518-519`). Never append rows above them.
- **The panel is its own overlay,** cloned from the trainer card's OverlayManager shape (`src/overlay_trainer_card.c:29-36`), launched through the start menu's fade → app → return chain (`:1114-1122`).
- **hge does not source or hook the start menu.** It is vanilla binary, so one site serves both. Re-prove it against the hge sha1.

**Receptionist trade (item 4). Corrections:**
- HGSS has no link-trade receptionist. `npc_trade.c` is the scripted NPC/loan trade.
- The PC nurse is `CallStd std_nurse_joy` from 25 Pokémon Center scripts. Per the reachability generator's CallStd resolution (`3745647c`, `sScriptBankMapping`), that is ONE std script in common-script member 3, so the branch point is likely one patch site. Confirm the dispatch before building.
- **Commit primitive:** `Party_SafeCopyMonToSlot_ResetAprijuiceModifiers` (`src/party.c:97-105`) is a raw 0xEC copy plus an aprijuice clear and a count fix. It does NO encryption and NO checksum, because it expects an already-encrypted record.
- **So the Gen 3 shape fits:** the host stages the encrypted blob that `lua/gen4/pk4.lua` `encrypt_party` already produces, and the ROM op only copies it in. Never re-implement the cipher in the patch.
- `ScrCmd_GiveLoanMon` (`src/scrcmd_c.c:3485`) is a synchronous give-mon precedent.
- **Open:** the box-delivery path, and whether a new ScrCmd is needed versus a std-script branch.

## Trade branch point and box path, settled (OMP cx-df6d0337, pinned pret)

**One nurse script.** `std_nurse_joy` = 2002 (`include/constants/std_script.h:17`) resolves via `sScriptBankMapping` (`src/fieldmap.c:33-64,194-202`, first-match, descending) to `scr_seq_0003` member 2 (`files/fielddata/script/scr_seq/scr_seq_0003.s:83-407`). That is ONE patch site for all 25 Pokémon Centers, exactly as the acquisition generator models it.

**The nurse menu is message data.** It uses `NonNPCMsgVar` + `GetMenuChoice` (`msg_0040`). A named third option would mean a message-bank edit.
- Cheapest gate: `ScrCmd_YesNo` (`src/scrcmd_c.c:947-973`; 0 = yes, 1 = no). It is native, with no message or graphics edit.
- Correction: `ScrCmd_379` is `Field_GetTimeOfDay`, not a menu builder.

**Two commit arms over one blob, both a raw copy with no crypto:**

| Destination | Call | Input |
|---|---|---|
| Party | `Party_SafeCopyMonToSlot_ResetAprijuiceModifiers` (`src/party.c:97`) | 0xEC `Pokemon` |
| Box | `PCStorage_PlaceMonInFirstEmptySlotInAnyBox` (`src/pokemon_storage_system.c:54-68`) | 0x88 `BoxPokemon` |

- The box primitive calls `RestoreBoxMonPP`, which MUTATES the buffer, so it needs a writable 0x88 scratch it owns.
- It sets the same per-box dirty bit the Lua client writes.

**Script command for the ROM routine.** No CallNative exists. The opcode is u16 (`src/script.c:75`), and `gScriptCmdTable[486]` (`src/data/fieldmap/script_cmd_table.h:1343`) is a spare `ScrCmd_Dummy` (an empty no-op).
- Overwriting that one pointer gives a companion `ScrCmd` with no table growth. This matters for hge, whose script NARCs come from the base ROM.
- The HG/SS source build could simply append to the table.
- Gate: prove opcode 486 is unused in the compiled `scr_seq` NARCs.

**Open:**
- whether `scr_seq_0003` can grow;
- the full-party decision point of the existing NPC trade (inferred, not traced);
- ~~the hge overlay-1 identity~~ settled below.

## hge identity of the patch sites (coordinator, 2026-10-02; HG `4fcded0e` vs hge `cb2dc435`, pinned xMAP)

- **The START menu is static ARM9, not an overlay.** All 74 `start_menu.o` symbols in the xMAP have `image=arm9`. These are byte-identical in HG (BLZ-decompressed) and hge (raw ARM9):
  - `sStartMenuActions` @0x020FA0F4 (104 B);
  - `FieldSystem_GetStartMenuButtonInhibitFlags_Normal` @0x0203BE60;
  - the other 72.
  So one site serves both. The HG/SS edit lands in the source rebuild, which recompresses the ARM9; on hge it is a `hooks` line.
- **`gScriptCmdTable` @0x020FAD00:** exactly one of 853 entries differs in hge, #208.
  - #486 is `0x02040895` in both, the same function as #1 (`ScrCmd_Dummy`).
  - ~~Repointing #486 does not collide~~ SUPERSEDED: #486 is USED by scripts (see the next section). Use #1.
  - Opcode-486 USE in the compiled `scr_seq` NARCs is still unproven (OMP card).
- **Overlay 1 does differ** (77 bytes: Rock Smash item drop, move tutor, the Togepi egg, object-event gfx). None of it is a companion site.

## C0 result and the mailbox consequence (Sonnet C0 card; coordinator re-hashed both ROMs on hgbox, 2026-10-02)

- **The pinned pret `ad7a3afa` rebuilds byte-identical.**
  - HG `4fcded0e`, SS `f8dc38ea`.
  - Toolchain: mwccarm 2.0/sp2p2 + NitroSDK **3.2** (the devcontainer archive; INSTALL.md's 4.2 is not needed) under wine 9.0, in a private prefix.
  - Wall time 2m42 cold / 1m02 warm.
  - Provenance is in `data/gen4/pret_build_provenance.json`. The ELF, xMAP, nm and gap analyses are in `C:/slink-cache/gen4-pret/{heartgold,soulsilver}/`.
- **There is no free static RAM.**
  - All 15 "gaps" are fully occupied by named objects with size-0 labels (SDK wifi/VCT/nnsys/gx, MSL, `unk_*`). Only 0-0x10 B of alignment pad is left.
  - The discarded `.bss` belongs to overlay OVY_84 (0x20 B) and is not static.
  - `SDK_STATIC_BSS_END` = 0x021E5900 (the overlay load base). The linker `SDK_SECTION_ARENA_START` = 0x0226EC40.
  - **The "proven-free static span" mailbox route is dead.**
- **C1 must allocate the mailbox; it cannot find one.** Adding a static `.bss` symbol in the HG/SS rebuild would move 0x021E5900, and with it every overlay address and every pinned hook site. So the options for C1 are:
  - (a) the ITCM/DTCM arena tails (`SDK_SECTION_ARENA_ITCM_START` 0x01FF8620, `_DTCM_START` 0x027E0080), if a live write-watch proves them unused;
  - (b) a main-arena allocation at companion init, found once per boot by a cookie scan (the Gen 2 cookie + counter pattern);
  - (c) a companion-overlay `.bss` reachable by a fixed pointer.
  - The pick goes to the C1 card, decided by measurement.

## Script command slot: use opcode 1, NOT 486 (OMP cx-00760b09, coordinator-verified at pinned pret `ad7a3afa`)

- **Opcode 486 is executed by vanilla scripts.** Its only emitter is the `Dummy486` macro (`asm/macros/script.inc:2776-2778`). It is used at three sites:
  - `scr_seq_0938_T29.s:439-440`, inside the straight-line entry `_0597` (`:426-442`; no branch can skip it);
  - `scr_seq_0748_T02R0302.s:32`, on the `FLAG_UNK_176`-clear fall-through.
  - hge rebuilds only `scr_seq_00003_commonscript.s` and `scr_seq_00953_trainerscript.s`, so it inherits these sites from the base ROM.
  - Repointing #486 would run companion code in those map scripts. **Rejected.**
- **Opcode 1 (`Dummy`, `script.inc:22-24`; table entry #1 == #486 == `ScrCmd_Dummy` in both HG and hge) is emitted by NO script:**
  - zero `Dummy` macro uses in `files/fielddata/script`;
  - zero `dummy` uses in hge's `armips/scr_seq`.
  - It is the companion slot.
- **Opcode-1 gate: PASSED by composition (coordinator, 2026-10-02). No bytecode walker is needed** (OMP cx-414f5133's walker stayed red: `scrcmd.json` lacks the script-argument widths).
  - HG/SS: C0 rebuilds the ROMs byte-identical from the pinned source, so the field-script NARC (ROM path `a/0/1/2`, `filesystem.mk:406`, 965 members) IS the assembled `scr_seq/*.s`, which has zero `Dummy` uses.
  - hge: its `a/0/1/2` is member-for-member identical to HG except member 3, which hge rebuilds from `armips/scr_seq/scr_seq_00003_commonscript.s` (zero `dummy` uses, no raw opcode-1 halfword).
  - Re-run this check (C0 sha1 + NARC member diff) on any new hge or pret pin.
- **hge nurse route is a source edit.** hge rebuilds the common-script bank (`armips/scr_seq/scr_seq_00003_commonscript.s:17-26` declares `scr_seq_0003_000..006`, including the nurse entry 002). On hge the trade branch is a fork source edit, not a bytecode patch.

## Sound code mapping (OMP cx-23a2453d, coordinator-verified; pinned pret `ad7a3afa`)

The four shared semantic codes (`patch/gb/slink_abi.inc:33-36`; Gen 2 table `patch/gen2/src/sfx.asm:96`) are all SE, with no jingle:

| Code | Gen 2 | HGSS pick | Status |
|---|---|---|---|
| 1 SUCCESS | `SFX_ITEM` | `SEQ_SE_DP_DECIDE` 1501 (`sndseq.h:499`; called at `view_photo.c:209`, `view_rankings.c:779`) | accepted |
| 2 FAILURE | `SFX_WRONG` | **none.** HGSS has no error-buzzer SE with a call site | OPEN: an owner content choice, or reuse a shape (e.g. `SEQ_SE_DP_DECIDE2` 1694) as a recorded substitution |
| 3 BOO | `SFX_BUMP` | `SEQ_SE_DP_WALL_HIT` 1536 (`sndseq.h:534`; no C caller) | provisional, needs a listen test at C3 PHYSICAL |
| 4 NOTIFY | `SFX_READ_TEXT_2` | `SEQ_SE_DP_SELECT` 1500 (`yes_no_prompt.c:156`, `main_menu.c:229`) | accepted |

- **Host behaviours to carry over:**
  - FAILURE ranks above BOO in the drop-oldest queue (`lua/gen2/panel.lua:47`);
  - NOTIFY is capability-gated (`:155`).
- **hge is sound-compatible. OMP's "hge replaces the sound module" is REJECTED.**
  - hge hooks only `GF_Snd_LoadSeq` and `GF_Snd_LoadSeqEx` (`hooks:290-291`).
  - Its own `include/sound.h:46-50` declares the same `SND_WORK` with the `unk_BEB78` handle array, which its `src/sound.c` uses.
  - The SE id table is value-identical across 1373 shared ids. So the vanilla handle poll plan stands for all three artifacts.

## Full-party decision (OMP cx-f329e1ef, coordinator-verified; pinned pret + hge fork)

- **Vanilla never routes a received mon to the PC.**
  - `GiveMon` returns `Party_AddMon`'s BOOL, which is FALSE on a full party, with no box fallback (`src/script_pokemon_util.c:38-45`, `src/party.c:46-49`).
  - hge's own `GiveMon` (`hg-engine/src/pokemon.c:1357-1400`) is the same: `PokeParty_Add`, no fallback. hge widens the script retvar to u16 (`armips/asm/abilities.s:44`), so a companion that reads it handles it per title.
  - The starter gift refuses up front on `GetPartyCount == 6` with one message (`scr_seq_0740_T01R0301.s:602-605,691-697`).
  - The only script-reachable box deposit is Pal Park, which `GF_ASSERT`s the placement (`src/scrcmd_12.c:68`).
- **The native trade shape is slot overwrite.**
  - The NPC trade picks a party slot with `GetPartySelection` (255 = cancel) and overwrites it via `Party_SafeCopyMonToSlot_ResetAprijuiceModifiers` (`src/npc_trade.c:153-156`). A full party cannot arise.
  - That is also the Gen 1/2 link-trade shape (send one, receive into that slot). **The companion trade copies it: choose a slot, the party arm overwrites, no capacity question.**
- **The box arm is NEW behaviour, not mimicry.** If C5 keeps it (e.g. deliver-to-box with no outgoing mon):
  - copy the only native room-anywhere ordering, `CountPCEmptySpace` then `GetPartyCount == 6` (`scr_seq_0119_D47R0101.s:580-586`);
  - handle a FALSE from `PCStorage_PlaceMonInFirstEmptySlotInAnyBox` as a message, never an assert;
  - use a writable 0x88 scratch.
  - Whether C5 needs a box arm at all is a C5 design decision. Open.

## Companion service tick (OMP cx-a34a43a8, coordinator-verified; pinned pret `ad7a3afa`)

- **Site: one SysTask on `gSystem.mainTaskQueue`** (`SysTask_CreateOnMainQueue`, `src/sys_task_api.c:8-10`).
  - It drains every frame in `NitroMain` right after the active app (`src/main.c:109-111`). It is app-independent, so the field, START-menu apps and battle are all covered by one site. This is not Gen 1's two-site problem.
  - The queues are arena-allocated (`src/system.c:123-126`), so the task survives app and overlay switches.
  - It does NOT survive a soft reset (`DoSoftReset`, called at `src/main.c:103` -> `OS_ResetSystem` at `:182`). Register it on every boot.
- **The `if (sub_02036144())` guard** (`main.c:106`) is the wireless/link frame-sync gate (`asm/unk_02035900.s`).
  - With no comm session (`[_021D4140+8] == 0`) it branches straight out, so single-player always drains.
  - Insurance, if a link state matters: `gSystem.vwaitTaskQueue`, which drains outside the guard at `main.c:131`.
- **Forbidden:** the vblank queue (IRQ context, `src/system.c:20-25`) and `gSystem.vBlankIntr` (`main.c:127-128`). Never `PlaySE` there.
- **hge:**
  - It hooks none of `NitroMain`, `SysTaskQueue_RunTasks`, `Task_RunScripts` or the VBlank callbacks.
  - It ships no `main.c`, `system.c` or `sys_task.c` source, so registration is a `hooks` row or rides hge's own boot path (`load_arm9_expansion`, called from Main at frame 9; profile.json:380).
- **C2 falsifier:** a per-state tick counter inside the task must advance in field, every START-menu app, battle, SAVE, a fade, an overlay load and after a soft reset.

## C4 panel placement (OMP cx-94fb3ec1 + coordinator ROM overlay-table read, 2026-10-02)

- **Launch chain** (verified):
  - `start_menu.c:1120-1127` -> `sub_0203D1CC` (`:1104-1112`) -> `TrainerCard_LaunchApp` (`launch_application.c:1143-1150`, a static `OverlayManagerTemplate` with `FS_OVERLAY_ID(trainer_card)`) -> `FieldSystem_LaunchApplication` (`field_system.c:127-133`; the manager is on `HEAP_ID_FIELD2`, and the app makes its own heap, `overlay_trainer_card.c:39`).
  - Return: `sub_0203D218` -> `FieldSystem_LoadFieldOverlay` -> `HandleLoadOverlay(FS_OVERLAY_ID(field))` (`field_system.c:89-96`).
- **Correction to OMP F2** ("the field overlay stays resident"): in the HG ROM overlay table, `field` (ov1) and `trainer_card` (ov50) BOTH load at 0x021E5900. Loading the app overlay evicts the field overlay by region conflict, which is why the return path reloads it. While the panel runs, only static ARM9 is resident; that is fine, because `start_menu.o` is static.
- **HG/SS:** append one `Overlay slink_panel { After main; Object ... }` group to `main.lsf`.
  - Overlay groups carry no `Address`, and ids are name-keyed (`FS_OVERLAY_ID(<name>)`).
  - The panel then loads at 0x021E5900, mutually exclusive with field and the trainer card.
  - Constraint: the largest overlay end equals the linker arena start (ov12 ends at 0x0226EC40 == `SDK_SECTION_ARENA_START`). A panel far smaller than ov1 (0x60280) cannot move the arena.
- **hge:** a new overlay is a directory drop (`overlays.mk:7,21-26`).
  - Measured in the hge ROM table: hge's own overlays load in a reserved top-of-RAM window: ov129 0x023D8000, ov130 0x023C4000, ov131 0x023C8000, and most of 133-149 at 0x023C0400. Two load at 0x021E5900.
  - The panel overlay can take the shared 0x023C0400 app slot (mutually exclusive with the others there) or 0x021E5900 like vanilla. C6 decides, measured against the hge linker scripts.
- **Clone target:** `src/overlay_trainer_card.c` (124 lines), single-overlay; drop the signature child. The B-exit binding is unverified; trace it at C4.

## C4/C6 follow-up (OMP cx-352fb685, coordinator-reconciled)

- **The trainer card is a LIFECYCLE template only.**
  - `overlay_trainer_card.c` (124 lines) has no input code. The UI, including the exit, is hand-written asm: `asm/overlay_trainer_card_main.s`, 4367 lines.
  - The exit behaviour to copy: B (`gSystem+0x48` bit 1) or touch-cancel -> `PlaySE(SEQ_SE_GS_GEARCANCEL)` -> palette fade -> the child returns TRUE -> `TRAINERCARD_RUN_EXIT` (`ov51_021E6A54` `:1867-1904`; `TrainerCardMainApp_Main` `:393-412`).
  - The panel writes its B-exit in C from that behaviour.
- **hge overlay origins:**
  - ov129 = `hg-engine/src/linker.ld:5-6` (0x023D8000+0x60, resident from boot);
  - ov130 = `src/battle/linker.ld:5-6` (0x023C4000, len 0x14000, ending at ov129's base);
  - ov131's origin file was not found.
  - hge has NO ArenaHi lowering: its only `OS_SetArenaHi` restores the initial value (`src/save.c:738`). Nothing proven keeps the main arena out of 0x023C0000-0x023E0000.
  - **Decision: the hge panel overlay takes the vanilla-style slot 0x021E5900** (an app slot exclusive with field, as hge's own ov142/147 do), not the unproven top window.
- **0x02000CD0:** hge's `bl load_arm9_expansion` from Main. Our pack already uses it as the hge-discriminating admission anchor (`hge_differs`, profile.json:65), so it is not a collision. The companion's hge registration must NOT hook this site; use a `hooks` row or ride `load_arm9_expansion`.

## C2 beacon layout direction (OMP cx-7fd901a6, coordinator-reconciled; shared ABI @ Gen 5 `4cd04812`)

- **The shared ABI arena is 4 KiB (`abi.h` `SLINK_ARENA_SIZE 0x1000`). Gen 4 takes a 4 KiB span and uses the ABI UNMODIFIED.** No per-title arena fork.
  - The C1 census default span is now 0x01FFEC00..0x01FFFC00 (ITCM offset 0x6C00, 4 KiB).
  - All W rows PASS on HG, SS and hge after classifying the nine MSL `0x01A56E1F` mirror-alias hits. They are the high word of the double 0x01A56E1FC2F8F359, loaded as r0:r1 for `_dmul` (`MSL_DPMath_s_ldexp.s:59-61`): data, in an exact path:line table (`DATA_ALIASES`), so a moved literal goes red again.
- **OMP's "the span is inside the ITCM arena, nothing proves it free": SOURCE half already closed.** C1 W2 finds no `OS_ARENA_ITCM` allocation in pret or hge. The PHYSICAL half (computed-pointer writes) is the live canary, still pending a free lane.
- **Gen 4 additions over the ABI, ROM-only:**
  - a boot generation (map it to `SlinkMailboxV2.reserved` @0x4C, ROM-owned, zero bytes added);
  - a liveness pair: a private per-boot cookie plus an engine-clock delta. This is the Gen 2 rule (`patch/gen2/src/slink.asm:88-110`) and is MORE necessary here, because ITCM survives soft reset.
  - The cookie answers "is this boot"; the generation answers "which boot". Both are kept.
- **No GB byte fields are lifted.** Sound is `SLINK_OP_PLAY_SE`; the panel is `SlinkInfoV2`; the trade is `SlinkRecordStageV1` with `SLINK_BIND_GEN4_PK4`, raw-encrypted, `COMMIT_MUTATES_INPUT`.
- **Single-writer rule per field** (OMP F6 table): the ROM owns signature/version/caps/status/witness/boot/liveness; the host owns opcode/args/stage/info request fields. This goes into the C2 card as the review checklist.

## Owner rulings (2026-10-02 late; record: `docs/gen4/reviews/DECISIONS_2026-10-02_companion.md`)
- **The trade is party-only** (slot overwrite). The box arm is dropped; this closes the "whether C5 keeps a box arm" question.
- **The FAILURE sound is pending** (owner deferral). It is not decided and must not be filled with a guess.

