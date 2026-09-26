# SLink companion overlay for pureRGB (PLAN §6 M3)

The Red/Blue companion patch (`patch/gen1/src/`, a binary UPS written into free space by a
manifest) does not transfer to pureRGB: its RST $00 bridge would overwrite live code, its
mailbox address is inside pureRGB's box data, and every home-bank literal it carries is wrong.
So for pureRGB the same features are **linked into the pureRGB build** from source
(`overlay/*.asm`), with every pret symbol resolved by rgblink, and shipped as a UPS over each
clean pure ROM. The clean ROMs are never modified; the overlay is a distinct artifact with its
own sha1s, `.sym`/`.map`, profile block, sites, checkpoint and admission rows.

| piece | where |
|---|---|
| sources (bank $3F + three ROM0 stubs + the 14-byte WRAMX mailbox) | `overlay/` (copied to `engine/slink/` in the checkout) |
| hook edits to the pinned checkout (16, verify-then-replace) | `tools/apply_purergb_overlay.py` |
| build + publish (fresh copy of `.cache/purergb` → apply → `make` → UPS/sym/map/provenance) | `tools/build_purergb_overlay.py` |
| UPS artifacts (CRC-bound to the locked pure ROM) | `patch/dist/SLink-Pure{Red,Blue,Green}.ups` |
| symbols, map, provenance | `data/purergb/*_slink.{sym,map}`, `data/purergb/overlay_provenance.json` |
| pack files the Lua client loads for `kind == "overlay"` | `data/games/gen1_purergb/{profile,engine_signals,write_checkpoint,admission}_overlay.json` (`tools/gen_gen1_*.py --kind overlay`) |
| the A4 gate + artifact contract | `tests/unit/test_gen1_purergb_overlay.py` |

## What the overlay adds

* **VBlank hook** (`SlinkHook`): `farcall TrackPlayTime` in `home/vblank.asm` becomes
  `farcall SlinkHook`, which writes the `SLNK` ABI-3 mailbox at `wSlinkMailbox` ($DEEA, the
  WRAMX bank-1 tail after "Current Box Data") and calls `TrackPlayTime` once. It saves,
  forces to 1 and restores `rWBK`: pureRGB's palette buffer loop runs with WRAM bank 2
  selected and interrupts enabled.
* **Native sound** (`SlinkSfxService`, bank $3F): the same main-thread dispatch as the
  vanilla patch (`patch/gen1/README.md`), reached from two ROM0 stubs in `slink_home.asm`:
  DelayFrame's tail `ret` becomes `jp SlinkDelayFrameTail`, and `Joypad` gains a
  `call SlinkJoypadSite` after its `homecall _Joypad` (menu loops never reach DelayFrame).
  Every symbol is the linker's: `SFX_GET_ITEM_2`/`SFX_DENIED`/`SFX_TINK`/`SFX_LEVEL_UP`,
  `BANK(Audio1_PlaySound)`/`BANK(Audio2_PlaySound)`, and the alarm predicate is
  `wLowHealthTonePairs` bit 7 -- the WRAM0 byte pureRGB's own `WaitForSoundToFinish` tests
  (`wLowHealthAlarm` is WRAMX here). `rWBK` is forced to 1 around the service.
* **Foreground trade service** (`SlinkForeground` → `SlinkTradeService`): `farcall
  SlinkForeground` right after `rst _DelayFrame` at `OverworldLoop`, keeping the vanilla
  predicate (lease byte +10 == 1). The vanilla DelayFrame RST bridge cannot exist here.
* **START-menu panel**: `dw SlinkStartMenuEntry` appended after `CloseTextDisplay` (ITEM/SAVE
  keep indices 2/4; the row is index 7 with or without the Pokédex), menu box 14/12 → 16/14
  rows, `wMaxMenuItem` +1, `next "SLINK@"` after EXIT, `GetStartMenuPrompt` rows 15/13 → 17/15.
  The ROM0 stub `farcall`s `SlinkPanel` and `jp RedisplayStartMenu`.
* **Cable Club receptionist**: `TextScript_CableClubNPC:: jpfar SlinkReceptionist`. The
  SLINK/cancel paths set `wDoNotWaitForButtonPressAfterDisplayingText` so pureRGB's generic
  epilogue (`AfterDisplayingTextID`) does not demand a second press; the original path leaves
  it clear and `farcall`s `CableClubNPC`, so the epilogue waits exactly as unpatched pureRGB.
* **Native trade** (`SlinkTradeApply`, `SlinkPartnerPrompt`, UI helpers): the vanilla logic
  with `BANK(Music_Evolution)`, `MUSIC_EVOLUTION`, `LINK_STATE_TRADING`, `PARTYMON_STRUCT_LENGTH`,
  `MON_OTID`, `NAME_LENGTH` from pureRGB's constants; `TryEvolvingMon` is exported (`::`) and
  lives in bank $2C, resolved by the linker. The 191-entry admission table is generated from
  `species_index.json` (`obtainable`); the name-glyph table is a FOR-loop rule over pureRGB's
  charmap. The save consent, full commit save and idle-frame pickup match the vanilla patch
  (`patch/gen1/README.md`; parity in `tests/unit/test_gen1_trade_save.py`).
* **APEX refusal** (`SlinkApexGuard`): at `ItemUseMedicine.setDVs` the DV pointer is copied to
  `de` (a farcall takes `hl`), the guard scans the party, the WRAM box and, once
  `BIT_HAS_CHANGED_BOXES` is set, the other eleven SRAM boxes for a same-OT/same-species mon
  already at DVs $FFFF, and on a hit the item routine branches to its own `.alreadyUsedApex`
  text before the DV store, so the chip is not consumed. The APEX site anchors move by the
  14-byte prelude; HL is the DV pointer again at the relocated `apex_preflight`.

## ABI (unchanged from the vanilla patch, B5)

Mailbox: +0..3 `SLNK`, +4 ABI 3, +5..6 frame counter, +7 SFX request (a semantic code:
1 success, 2 failure, 3 boo; played on the main thread and zeroed), +8 caps (`$03` panel + SFX),
+9 panel state, +10 page, +11 page count, +12/+13 ROM-private SFX hold flag and frame stamp. Lease: `SLT1` v1 over the
first 16 bytes of `wSerialPartyMonsPatchList`, preimage at `wEnemyMons+44`, prompt name at
`wEnemyMons+60`, the same states/generations/results and the same timings (QUERY 30, OFFER 180,
stage 90, settle 20, apply 100 frames). What moved is carried by the profile `trade` block:
`mailbox`, `service {bank, addr}`, `receptionist_hook` + `dispatch_hex` (the pinned 7-byte
`jpfar SlinkReceptionist`), and `anchors` (vblank, foreground, start_menu_row, apex_guard).

## Rebuilding

    python tools/build_purergb_overlay.py            # needs .cache/purergb at the locked commit
    python tools/gen_gen1_profile.py --foundation purergb --kind overlay
    python tools/gen_gen1_engine_signals.py --kind overlay
    python tools/gen_gen1_write_checkpoint.py --kind overlay
    python tools/gen_gen1_admission_profiles.py --kind overlay
    python -m pytest tests/unit/test_gen1_purergb_overlay.py -q

`tools/build_purergb_overlay.py --check` rebuilds and compares every committed artifact.
