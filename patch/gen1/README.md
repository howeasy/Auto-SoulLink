# Gen 1 companion patch — the panel, and the SLINK TRADE receptionist

**Status: shipping. It carries the in-game SLINK panel and the SLINK TRADE receptionist, and
it does NOT play sound.**

> **pureRGB:** this binary patch does not apply to pureRGB (ROM0 is full, the RST vectors are live
> code, `$DEE2` is inside pureRGB's box data). The same panel, receptionist and an APEX collision
> guard are linked into the pureRGB build from source instead — see `purergb/README.md` and
> `patch/dist/SLink-Pure{Red,Blue,Green}.ups`. The mailbox ABI (3) and the `SLT1` lease are shared,
> so `lua/gen1/panel.lua` / `trade_overlay.lua` drive both builds from the profile's `trade` block.

This started as a spike answering *can SLink inject code into Pokémon Red/Blue cleanly?*
The answer was yes. What it grew into is a START-menu row that opens a full-screen Soul Link
panel the player can read without leaving the game, and a Cable Club receptionist that runs
the in-game trade. It enforces no Soul Link rule on its own and the Lua client does not
require it.

## What it carries

One manifest, `patch/gen1/tools/manifest.py` — 15 spans, Red and Blue byte-identical:

* **The START-menu row and the panel.** A `SLINK` row appended after EXIT (so every existing
  index keeps its position), a ROM0 stub that draws it, and a bank-`$3F` entry that opens the
  panel and returns to the menu. Pairs, badges and dead zones, paged with A and closed with B.
* **The SLINK TRADE receptionist.** The Cable Club receptionist in every Pokémon Center now
  opens a `SLINK TRADE` menu (`trade_receptionist.asm`), fed by a foreground service that runs
  from the `DelayFrame` bridge in the reserved RST padding (`trade_service.asm`). Three
  intercept spans: the bridge at `0x0001`, the `DelayFrame` tail redirect at `0x20B7`, and the
  receptionist dispatch at `0x29C3`; five linked routines share bank `$3F`.

**The receptionist has not yet been driven on a running cartridge.** The panel gates pass on
this trade-carrying build; launching the menu itself is open (requirements row T-1, `P` ◐).

## Why so little

Unlike Gen 3, **Gen 1 needs no patch for correctness**. Radical Red required the native
patch for Rival Team Swap because `gEnemyParty` is encrypted and checksummed. Gen 1's enemy
party is plaintext at a fixed address, so the swap, Explode Mode, memorialize and party
sync are all plain RAM writes on an unmodified cartridge — and they are live-tested that
way (`tests/e2e/test_duo_gen1.py`).

So the patch buys **zero additional rules**. What it buys is what the cartridge's screen can
show: the panel, and a trade that happens with the game's own UI.

## How sound is played (and why not from VBlank)

The request byte at mailbox `+7` carries a **semantic code** — 1 success, 2 failure,
3 boo — and the capability byte advertises `SLINK_CAP_SFX` (`$01`; caps read `$03` with the
panel). The code is consumed on the **main thread** at two idempotent sites: DelayFrame's
tail jumps to the ROM0 bridge (`$0001`, shared with the trade lease), which farcalls
`SlinkForeground` in bank `$3F` when a request is pending or a lease is armed; and
`Joypad`'s `call _Joypad` (`$01A4`) is pointed at `SlinkJoypadStub` (`$3FBE`, the free ROM0
tail), because a menu waiting for input spins in `HandleMenuInput_` on `JoypadLowSensitivity`
and never reaches DelayFrame (measured: a request written with the START menu open sat
unplayed for 300 frames on the bridge alone). Both call `SlinkSfxService` (`slink.asm`),
which resolves the code against the audio bank loaded *at play time*
(`wAudioROMBank` — sound ids are per bank, and a request held across a battle fade spans a
bank change): success = `GET_ITEM_2 $89` (`LEVEL_UP $86` in the battle bank, which survives
the low-health alarm), failure = `DENIED $A5` (`TINK $8C` in the battle bank, which has no
buzzer), boo = `TINK $8C`. It **holds** the request while `wAudioFadeOutControl` is nonzero
(PlaySound would drop it) and while CHAN5/6/8 are busy (the engine drops a higher id on a
busy channel — the same test as `WaitForSoundToFinish`, with its low-health-alarm bypass;
while the alarm owns CHAN5 it re-marks it `$86` every tick and the engine rejects any higher
id there, so every code plays LEVEL_UP (`$86`, the one id that channel accepts) until the
alarm ends — the way the vanilla level-up jingle survives it), and after 240 held **frames** (counted against the mailbox's own VBlank counter, stamped in
`+12`/`+13`, ROM-private — GET_ITEM_2 alone owns CHAN5 for ~180) plays regardless. Unknown
codes are consumed unplayed; `Init` zero-fills WRAM so a fresh cartridge never sees a stray
request. `lua/tests/test_gen1_patch_gate.lua` asserts the exact id that lands on CHAN5 in
the quiet overworld; `lua/tests/test_gen1_sfx_gate.lua` is the state matrix (client path,
busy-channel hold, START menu, lab-door fade with its `$1F -> $02` bank change, a real wild
battle's `$08` row, and a request held through the battle-end fade that plays in `$02`).

Earlier builds (ABI 2) played SFX from the VBlank hook. That was removed, and ABI 3 shipped
panel-only until the main-thread path above existed. The two failure modes, both measurable
in the shipped ROM by disassembling `PlaySound` (`$23B1`), are why the call is not in VBlank:

* **Swallowed during fades.** `PlaySound` opens
  `ld a,[wAudioFadeOutControl] / and a / jr z,.noFadeOut` then
  `ld a,[wNewSoundID] / and a / jr z,.done`. The patch passes the id in `a` and never sets
  `wNewSoundID`, which is 0 in steady state — so during any fade the call returns without
  playing, and the request byte was already cleared, so the event is simply lost. Fades run
  ~56–70 frames on map change and on battle start/end: exactly when capture, faint and
  whiteout fire.
* **Re-entrancy, in the ordinary case.** `.noFadeOut` does `xor a / ld [wNewSoundID], a`
  and calls the audio engine several instructions later. A VBlank landing anywhere in that
  window sees **both** guard bytes clear, passes the guard, and re-enters a non-reentrant
  routine — corrupting `wChannelSoundIDs` and stamping the SFX id into
  `wLastMusicSoundID`. Our hook **is** that VBlank, so no guard on our side can close it.

Both are closed by construction on the main thread: PlaySound is only ever entered from
the bridge (never from an interrupt), and the fade case is held rather than dropped.

## Distribution

| | Base ROM md5 | Patched md5 (current build) |
|---|---|---|
| Red  | `3d45c1ee9abd5738df46d2bdda8b57dc` | `eb8c79d45007b9e22f72ada3560a001d` |
| Blue | `50927e843568814f7ed45ec4f944bd8b` | `068b59eebc5d8fc573a23e9dfe1376bf` |

`patch/dist/SLink-RB-Red.ups` and `-Blue.ups`, generated from the built ROMs:

```bash
python patch/tools/make_ups.py create patch/build/gen1_red.gb  patch/gen1/build/slink_red.gb  patch/dist/SLink-RB-Red
python patch/tools/make_ups.py create patch/build/gen1_blue.gb patch/gen1/build/slink_blue.gb patch/dist/SLink-RB-Blue
```

The committed `.ups` files are regenerated from the trade-carrying build (destination md5s
above; `tests/unit/test_patcher_routes.py` applies the shipped bytes). Both are served by the in-browser patcher (`/patcher?game=rb-red`), applied client-side —
no ROM is ever uploaded. **No Yellow patch is built or shipped**, and
`tests/unit/test_patcher_routes.py` asserts its absence rather than leaving it to be
noticed.

## Build and verify

```bash
python patch/gen1/tools/build.py                      # → build/slink_{red,blue}.gb
python patch/gen1/tools/build.py --verify-only        # check the base ROMs; no writes to them
pytest tests/unit/test_gen1_trade_patch.py -q         # clean-byte admission, spans, trade bank
```

`--verify-only` reports the hook site, the target bank and all 15 spans as expected on both
dumps. The pytest suite is what admits the trade sources: the five asm files are compared
against the sources they were ported from, the clean dumps are checked for the three exact
before-patterns, the linked symbol sizes and the bridge/dispatch bytes are pinned, only the
declared spans may have changed, and the panel payload must be bit-identical to the
panel-only link.

Needs no toolchain install — `rgbasm`/`rgblink` come from the same pinned RGBDS download the
symbol pipeline already uses. Both base ROMs are checked by SHA-1 and every write is
verify-then-write, so a ROM that is not the exact expected dump fails loudly instead of
being silently corrupted.

## What the mailbox carries

Mailbox `+7` is a sound-request byte, kept for compatibility and **drained without being
played** — see "Why there is no sound" above. `+8` is the capability byte a client reads to
learn what this build can actually do, rather than inferring it from the ABI number; `+9`,
`+10` and `+11` are the panel handshake, the page the patch wants painted, and the page count
the client publishes back. The trade runs over its own lease (16 bytes at
`wSerialPartyMonsPatchList`), not the mailbox.

The client asks the capability bits, not the version: a build may ship one feature without
another, and this one does exactly that.

## How it hooks

`VBlank` (home, `00:2024`) contains `farcall TrackPlayTime`, which assembles to

```
ld b, BANK(TrackPlayTime)   ; 06 06
ld hl, TrackPlayTime        ; 21 EE 4D
call Bankswitch             ; CD D6 35
```

That 8-byte pattern occurs **exactly once** in the Red dump, at ROM `0x2094`. Rewriting
three immediate bytes vectors it into bank `$3F`; the module then re-issues the original
`farcall` and returns. Cost: **zero home-bank space** — which matters, because Red/Blue have
only 156 free bytes in ROM0.

It is safe to call back out because `Bankswitch` saves the current bank on the *stack*, so
it is re-entrant: this code, already running in `$3F` via `Bankswitch`, can farcall
`TrackPlayTime` and the nested call restores `$3F` before returning.

VBlank is an interrupt, which is the other reason that site was chosen — it fires in every
context. The gate proves the counter advances in the overworld, **in battle**, and **with
the START menu open**.

Bank `$3F` is one of nineteen entirely unused banks (`$2D`–`$3F`, ~311 KB of `0x00`
padding). The mailbox at `$DEE2` is the *only* free WRAM in Red/Blue: pret's linker map
reports `WRAM0: TOTAL EMPTY: $001E` — thirty bytes, between `wBoxDataEnd` and the stack.

## Red and Blue only

Yellow's map reads `WRAM0: TOTAL EMPTY: $0000`. There is nowhere to put a mailbox, and 21
free home bytes against Red/Blue's 156 — the CGB palette section took Red's gap and the
stack was shortened `$100` → `$EB` (`pokeyellow/ram/wram.asm`). Yellow is Lua-only: the
core Soul Link rules are unaffected, it simply has no in-game panel.

Archipelago ROMs are also unpatched — the AP fork relocates WRAM and rebuilds the ROM, so
the offsets here do not hold. AP gets full RAM-only support instead.
