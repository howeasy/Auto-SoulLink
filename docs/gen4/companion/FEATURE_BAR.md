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
