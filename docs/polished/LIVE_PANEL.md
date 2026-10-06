# LIVE_PANEL — the SLink panel behind the Phone card, on a cartridge

**Card POL-PANEL round 2. Append-only; `LIVE_RESULTS.md` is not edited here.**

Lane `F:/slink-work/lanes/pol-panel2` (private). ROM staged from the **committed** UPS, not rebuilt:

```
F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc
  + patch/dist/SLink-Polished.ups
  -> F:/slink-work/lanes/pol-panel2/rom/pol_overlay.gbc
     sha1 9c60bc8fb26ac13c52705b8086f8a5fb91d7bd93   (== data/polished/overlay_provenance.json)
```
(`tools/polished_live/run_pol_panel.py:34-49`.)

Driver `tools/polished_live/pol_panel.lua`; runner `tools/polished_live/run_pol_panel.py`.
Evidence: `F:/slink-work/lanes/pol-panel2/run/result.txt`, `panel.json`, `panel_*.png`.

**Who publishes the pages:** a **scripted mailbox writer inside the driver**
(`pol_panel.lua:88-108`, installed on `L.on_frame`), *not* a real SLinkServer. It speaks the shared
GB panel protocol verbatim — watch `PANEL_STATE` (+9) for `AWAIT`, write the page's charmap codes into
`wSlinkPanelText` at `SLINK_PANEL_STRIDE`, publish `PANEL_PAGES` (+11), then `PANEL_STATE = STAGED`
(+9) last — exactly the order `lua/gb_panel.lua:218-235` uses. So this run exercises the **ROM half**
(`SlinkPanel`, the `PrintText` render, paging, the close) against a host that obeys the ABI; the Lua
host half remains covered by the 448-test unit slice, not by this file.

## Result

**ABORTED at the boot gate. One EmuHawk, own PID only (`pol-live EmuHawk pid 22824 … rc=0`).**

| # | check | result | evidence |
|---|---|---|---|
| C0 | ROM staged from the committed UPS, sha1 pinned | **PASS** | `run_pol_panel.py:40-43`; `result.txt` line 1 (`rom 9C60BC8F…`) |
| C0 | EmuHawk boots the overlay and the SLink service runs | **PASS** | `result.txt:2` — the client booted and logged its rom hash |
| C1 | `PANEL` cap advertised; mailbox span 69 bytes | **NOT REACHED** | the run aborted before the Phone card opened |
| C2 | fallback page renders, then page 1 | **NOT REACHED** | ” |
| C3 | A advances to page 2 | **NOT REACHED** | ” |
| C4 | B closes, cursor intact, no call placed | **NOT REACHED** | ” |
| C5 | every client write inside the mailbox span | **NOT REACHED** | ” |

### The failure, precisely

```
[panel] boot frame 1 rom 9C60BC8FB26AC13C52705B8086F8A5FB91D7BD93
[panel] boot map 255:255 wMapStatus FF saved 255 version 0
[panel] boot map 0:0 wMapStatus 00 saved 0 version 0
[panel] boot probe done: map 0:0 ow_idle=false frame 1801
  [FAIL] CONTINUE did not reach ROUTE_29
RESULT: FAIL aborted (1 checks failed) frame 9802
```

The fixture save **is** staged (32790 B, `F:/slink-work/lanes/pol-panel2/sram_overlay/pol overlay.SaveRAM`,
byte-size identical to `pol-phone`'s), but after 9802 frames of scripted `A`/`B` the game is still at
map `0:0` with `wMapStatus = 0` and never reaches `OWPlayerInput` at `(24,3)`.

**Two readings in that log are not evidence and should not be quoted as such:** `sSaveVersion` is an
**SRAM** symbol read through `L.rw`, which is the *WRAM* domain (`pol_lib.lua:48`) — so `version 0`
and `saved 0` prove nothing about the save. `map 0:0` / `wMapStatus 0` is the real signal, and it is
the main menu, not the overworld.

**Not yet established:** whether this is (a) the panel overlay's mailbox claim, (b) the
`pol-phone` fixture being specific to that lane's *progressed* SRAM rather than to the pristine
fixture, or (c) a driver difference. `pol-phone/drv/run_phone.py` copies the same fixture file over
its SRAM and works, so (a) is the worrying one and it is **UNRESOLVED**. It is, however, bounded:
the mailbox is WRAM0 `$C60B-$C64F`, the save lives in CartRAM, and no overlay byte touches SRAM —
but "should be" is not "measured".

### What the next run must do

1. Copy `F:/slink-work/lanes/pol-phone/sram_overlay/pol overlay.SaveRAM` (the lane's *live*, post-setup
   save) instead of `fixture/polished_overlay_warp.SaveRAM`, and re-run unchanged. That isolates (b).
2. Read the save with `L.rc("sSaveVersion")` (CartRAM), not `L.rw`.
3. Log `wJumptableIndex` while pulsing, to prove the main menu was actually reached and which row is
   under the cursor — that is what distinguishes (c).
4. Only if all three still land at `0:0`: bisect by running `pol-phone/drv/phone.lua` on **my** lane
   with the Stage-1 ROM. That isolates (a) — the panel overlay breaking boot — in one run.

## SYNTH writes, disclosed

`pol_panel.lua:106-113`, each logged at runtime:

* `wPokegearFlags = $87` (Pokégear + map/radio/phone obtained) — identical to `pol-phone`.
* `wPhoneList = 00 00 00 00 00` (no native contact, so the virtual SLink row is row 0).
* the fixture save itself is SYNTH (`POL_POSMODE=warp` — the engine's own `Script_warp`-equivalent
  reload; **no bare `wMapGroup`/`wXCoord` pokes**).

**Every write the driver makes is audited at `pol_panel.lua:70-79`**: `memory.write_u8` is wrapped
before anything else loads, and each call is counted and range-checked against
`[wSlinkMailbox, wSlinkMailboxEnd)`. C5 asserts the count, the observed low/high and that the
outside-list is empty. That audit did not run in this aborted pass.

---

## Round 3 (2026-10-04, append)

### Step 4 — isolation: the panel overlay does NOT break boot

Same lane, same fixture (`g2int-live/pol/fixture/polished_overlay_warp.SaveRAM`), same driver
(`phone.lua`), same emulator config. Only the ROM differs.

| run | ROM | result |
|---|---|---|
| A | Stage-1, `34942315…` (`git show c9f1ad14:patch/dist/SLink-Polished.ups`, 262 B) | boots, reaches the Phone card, `SLink:` renders, submenu shows Call/Cancel — **identical behaviour** |
| B | panel, `9c60bc8f…` | **identical behaviour** |

**Conclusion: the round-2 abort was NOT the panel overlay.** Runner
`tools/polished_live/run_phone_ab.py`; results `…/ab_stage1/result.txt`, `…/ab_panel/result.txt`.

Two real causes of the round-2 abort, both mine, both now fixed:
1. **Wrong fixture.** `run_pol_panel.py` hardcoded `pol-phone`'s fixture; `POL_FIXTURE` was
   ignored. The `g2int-live` one is the save whose phone run passed 75/75.
2. **A boot probe I added to diagnose the failure caused it.** Round 2's `pol_panel.lua` pulsed
   `A` and `B` for 1800 frames *before* `to_overworld`. On the main menu `B` moves down, so the
   later CONTINUE press landed on another row. Removed; the comment now says it must never press
   there.

### The defect fix (panel.asm)

`SlinkPanelFallback` ended in `prompt`, so `ButtonSound` blocked on a keypress **before** `AWAIT`
was ever published: the host was never asked until the player pressed, and every page cost two
presses. Now:

**Current-source correction (2026-10-06).** The Round 3 run below remains historical evidence from
2026-10-04 on overlay `48d6ec699b9267c5b0d2d348fc57b7bf7140c630`; the bullets that follow describe that
build, and their line numbers and `SlinkPanelScript` are stale. In the current `patch/polished/src/panel.asm`
the fallback (`SlinkPanelFallback`, line 149) ends in `done` (line 152); on the staged path both mailbox
rows are `@`-terminated and painted by separate `rst PlaceString` calls (lines 65-73); `SlinkPanelScript` no
longer exists (`tests/unit/test_polished_panel.py` line 157 asserts its absence); and both the staged and the
timeout path reach `.WaitForButton` (call at line 88, routine at line 132). This correction does not
re-qualify the panel: DEV evidence only.

* `SlinkPanelFallback` ends in `done` — `panel.asm:125`, so `AWAIT` is the first thing the panel
  waits on.
* `SlinkPanelScript` ends in `<PROMPT>` — `panel.asm:136` — the staged page is what waits for the
  player.
* The no-host path gained `.WaitForButton` (`panel.asm:102-117`, `patch/gen2/src/panel.asm`'s own
  release-then-press loop), because with no prompt the `A` that chose "Call" would otherwise close
  the panel immediately.

Rebuilt with the isolated root: **overlay `48d6ec699b9267c5b0d2d348fc57b7bf7140c630`, UPS 422 B**,
`moved clean symbols: none`.

**UPR patch-0020 signature — byte-identical, verified by diffing the two overlay ROMs:**

```
bridge $0070..88   IDENTICAL  f044e0d7afe08ff5c5e5f087f53e7ecfcd0040f1cfe1c1f1c9
DelayFrame $0DA8..AE IDENTICAL  cd700000000000
$7E:4000 +16       IDENTICAL  210bc63e53223e4c223e4e223e4b223e
$7E:4010 +16       IDENTICAL  03773e02ea13c6f08e47fa2ac6fea528
total changed bytes: 135, range 0x14e - 0x1f80f2   (header checksums + the panel body)
```

### Step 3 — live rerun: STILL ABORTED at the boot gate

| # | check | result | evidence |
|---|---|---|---|
| C1-C5 | all | **NOT REACHED** | `…/run/result.txt`: `CONTINUE did not reach ROUTE_29`, `frame 8002` |

With the correct fixture and the probe removed, `pol_panel.lua` still fails the boot gate on
`48d6ec69…`, while `phone.lua` on the **same lane, same fixture, same ROM source** boots. The
remaining difference between the two drivers is therefore mine and is **UNRESOLVED**: the extra
`L.hook` registrations and the `L.on_frame` mailbox writer installed before `to_overworld`.
`phone.lua` reaches overworld with no `L.on_frame` installed and hooks only what it needs.

**Nothing about the panel itself is disproved by this** — steps A and B show the ROM boots and the
Phone card is fully functional on this overlay. But the panel flow is still **unproven on
hardware**, and I am not claiming otherwise.
