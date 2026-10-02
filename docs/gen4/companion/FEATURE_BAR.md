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

**START panel (item 3). Corrections:** the entry is a `StartMenuAction` row in `src/start_menu.c` (overlay 1), not a script. The Gen 4 UI APIs are `bg_window.h` (`AddWindow`), `render_window.h` (`DrawFrameAndWindow1/2`), `font_types_def.h` (`TextPrinter`), `render_text.h` (`RenderText`) and `list_menu.h` (`ListMenuInit`), not Gen 3 names.
- **Smallest patch:** rows `START_MENU_ACTION_7` and `RETIRE` are permanently inhibited (`:305-306`). Clear one bit and repoint that row's `.func`/`.ident` in `sStartMenuActions` (`:174-188`). There is no table growth and no icon.
- **Hazard:** `ACTION_9`/`_10` sit at fixed display slots 7/8 (`:517-518`). Never append rows above them.
- **The panel is its own overlay,** cloned from the trainer card's OverlayManager shape (`src/overlay_trainer_card.c:29-36`), launched through the start menu's fade → app → return chain (`:1120-1127`).
- **hge does not source or hook the start menu.** It is vanilla binary, so one site serves both. Re-prove it against the hge sha1.

**Receptionist trade (item 4). Corrections:**
- HGSS has no link-trade receptionist. `npc_trade.c` is the scripted NPC/loan trade.
- The PC nurse is `CallStd std_nurse_joy` from 25 Pokémon Center scripts. Per the reachability generator's CallStd resolution (`3745647c`, `sScriptBankMapping`), that is ONE std script in common-script member 3, so the branch point is likely one patch site. Confirm the dispatch before building.
- **Commit primitive:** `Party_SafeCopyMonToSlot_ResetAprijuiceModifiers` (`src/party.c:97-105`) is a raw 0xEC copy plus an aprijuice clear and a count fix. It does NO encryption and NO checksum, because it expects an already-encrypted record.
- **So the Gen 3 shape fits:** the host stages the encrypted blob that `lua/gen4/pk4.lua` `encrypt_party` already produces, and the ROM op only copies it in. Never re-implement the cipher in the patch.
- `ScrCmd_GiveLoanMon` (`src/scrcmd_c.c:3485`) is a synchronous give-mon precedent.
- **Open:** the box-delivery path, and whether a new ScrCmd is needed versus a std-script branch.
