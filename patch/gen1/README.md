# Gen 1 companion patch — one feature, and one deliberately dropped

**Status: shipping. It carries the in-game SLINK panel, and it does NOT play sound.**

This started as a spike answering *can SLink inject code into Pokémon Red/Blue cleanly?*
The answer was yes. What it grew into is a START-menu row that opens a full-screen Soul
Link panel the player can read without leaving the game. ~450 bytes of SM83. It enforces
no Soul Link rule and the Lua client does not require it.

## Why so little

Unlike Gen 3, **Gen 1 needs no patch for correctness**. Radical Red required the native
patch for Rival Team Swap because `gEnemyParty` is encrypted and checksummed. Gen 1's enemy
party is plaintext at a fixed address, so the swap, Explode Mode, memorialize and party
sync are all plain RAM writes on an unmodified cartridge — and they are live-tested that
way (`tests/e2e/test_duo_gen1.py`).

So the patch buys **zero additional rules**. What it buys is a screen: pairs, badges and
dead zones, on the Game Boy, paged with A and closed with B.

## Why there is no sound

Earlier builds (ABI 2) played SFX from the VBlank hook. That was removed, not deferred,
and the capability byte says so — a client asks the bits what this build can do rather
than inferring it from the ABI number.

Two failure modes, both measurable in the shipped ROM by disassembling `PlaySound`
(`$23B1`):

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

Playing sound safely needs a main-thread dispatch point with its own displaced bytes and
queue-drain timing. Until one exists and passes a full state matrix, this build ships
panel-only. The request byte is still drained so a client leaves no stale state in the
mailbox; it simply never becomes a sound.

## Distribution

| | Base ROM md5 | Patched md5 |
|---|---|---|
| Red  | `3d45c1ee9abd5738df46d2bdda8b57dc` | `123cfcdff9f1ee5b5e53621874e22332` |
| Blue | `50927e843568814f7ed45ec4f944bd8b` | `c3edad823f9a425edc129a187233758e` |

`patch/dist/SLink-RB-Red.ups` and `-Blue.ups`, generated from the built ROMs:

```bash
python patch/tools/make_ups.py create patch/build/gen1_red.gb  patch/gen1/build/slink_red.gb  patch/dist/SLink-RB-Red
python patch/tools/make_ups.py create patch/build/gen1_blue.gb patch/gen1/build/slink_blue.gb patch/dist/SLink-RB-Blue
```

Both are served by the in-browser patcher (`/patcher?game=rb-red`), applied client-side —
no ROM is ever uploaded. **No Yellow patch is built or shipped**, and
`tests/unit/test_patcher_routes.py` asserts its absence rather than leaving it to be
noticed.

## Build and verify

```bash
python patch/gen1/tools/build.py                      # → build/slink_{red,blue}.gb
python patch/gen1/tools/build.py --verify-only        # check the base ROMs, build nothing
SLINK_LIVE=1 pytest tests/live/test_gen1_gates.py -k companion -q
```

Needs no toolchain install — `rgbasm`/`rgblink` come from the same pinned RGBDS download the
symbol pipeline already uses. Both base ROMs are checked by SHA-1 and every write is
verify-then-write, so a ROM that is not the exact expected dump fails loudly instead of
being silently corrupted.

## What the mailbox carries

Mailbox `+7` is a sound-request byte, kept for compatibility and **drained without being
played** — see "Why there is no sound" above. `+8` is the capability byte a client reads to
learn what this build can actually do, rather than inferring it from the ABI number; `+9`,
`+10` and `+11` are the panel handshake, the page the patch wants painted, and the page count
the client publishes back.

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

## What the gate asserts

`lua/tests/test_gen1_patch_gate.lua`, on both patched ROMs:

| Check | Last run |
|---|---|
| `'SLNK'` beacon at `$DEE2` | `"SLNK"` |
| counter advances | 863 → 923 over 60 frames |
| …in battle (`wIsInBattle` set) | 923 → 983 |
| …with the START menu open | 1024 → 1084 |
| displaced `TrackPlayTime` still runs | play clock advances |
| the game still plays | `(4,6)` → `(5,6)` |
| ABI version byte | `3` |
| capability bits **do not** claim SFX | `caps = 0x02`, panel only |
| capability bits claim the panel | `caps & 0x02` |
| the SFX request byte is still drained | cleared within 10 frames |
| **a drained request never starts a sound** | `wChannelSoundIDs` unchanged over 30 frames |
| the panel handshake is closed in the overworld | `0` |
| the game still plays afterwards | `(5,6)` → `(4,6)` |

The sound rows are the **inverse** of what they used to assert, and deliberately so. The
old ones fired from a quiescent overworld — never during a music fade, never probing the
instruction window inside `PlaySound` — so they were structurally blind to both ways the
audio path failed, and could only ever observe the case that happens to work. What is
asserted now is that no reachable `PlaySound` call remains: there is no window left to land
in. `call PlaySound` (`CD B1 23`) does not appear anywhere in bank `$3F` of either build.

The menu-row gate (`lua/tests/test_gen1_menu_row_gate.lua`) covers the panel itself on both
ROMs: the SLINK row draws and is reachable, selecting it opens the panel, the client's
staged rows are what appear on screen, **A turns to page 2**, **B closes from a page**, the
page byte resets, EXIT still closes the menu at its original index, and the player can still
walk afterwards.

The "still plays" rows exist because a patch that quietly breaks what it hooks is worse than
no patch.

## If this ever gets more features

The next one is `OP_SHOW_MESSAGE`, and it is genuinely cheap — Gen 1's text engine
has a `TX_RAM` command that prints a `$50`-terminated string from any RAM address, so it is
a 6-byte ROM script plus `call PrintText`, with the text staged into free SRAM at `$B858`
(~1,960 bytes, same address in all three games). It needs a **second hook** on the main
thread (`OverworldLoop`, `00:03FF`) because you cannot draw a text box from inside an
interrupt.

Stop there unless it demonstrably improves a run.

**Not** a candidate: the peer ghost. Gen 1 has 16 sprite slots, but the binding constraint
is VRAM sprite-set allocation (~11 pictures per map, assigned at map load), and on
sprite-dense maps neither a slot nor a picture is free. Separately, Gen 1's sprite struct is
a flat unencrypted 16-byte record — so if a ghost were ever built, it would be driven
entirely from Lua and this patch would not be the vehicle.
