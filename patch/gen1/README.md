# Gen 1 companion patch — the spike, and its verdict

**Status: the approach works, and it now carries exactly one feature — sound.**

This started as a two-day spike answering *can SLink inject code into Pokémon Red/Blue
cleanly?* The answer was yes, so it grew the one capability that genuinely cannot be done
any other way. 62 bytes of SM83. It enforces no Soul Link rule and the Lua client does not
require it.

## Why so little

Unlike Gen 3, **Gen 1 needs no patch for correctness**. Radical Red required the native
patch for Rival Team Swap because `gEnemyParty` is encrypted and checksummed. Gen 1's enemy
party is plaintext at a fixed address, so the swap, Explode Mode, memorialize and party
sync are all plain RAM writes on an unmodified cartridge — and they are live-tested that
way (`tests/e2e/test_duo_gen1.py`).

So the patch buys **zero additional rules**. What it does buy is the one thing Lua cannot
reach at all: **sound**.

`wNewSoundID` (`$C0EE`) looks like a sound mailbox and is not. `PlaySound` takes the id in
register `a` and only uses that address as internal scratch (`home/audio.asm:140`), and
nothing in the game loop polls it. There is no address you can write from Lua that makes
Gen 1 play a sound — the id has to reach a `call`. That is the patch's entire justification,
and it is why the feature list stops there.

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

## The SFX hook

Mailbox `+7` is a request byte. Lua writes a sound id; the next VBlank consumes it, zeroes the
byte and calls `PlaySound`. One-shot by construction — the byte is cleared *before* the call,
so a request can never fire twice.

The placement is free rather than clever: by the time VBlank reaches our hook it has already
switched to `wAudioROMBank` and run `Audio1_UpdateMusic` (`home/vblank.asm:53-71`), so we are
in audio-bank context immediately after the engine's own per-frame audio work. The one hazard
is that `PlaySound` parks the caller's bank in `hSavedROMBank` (`$FFB9`, measured from the ROM
rather than inferred from `hram.asm` ordering) and the main thread may itself be mid-`PlaySound`
when the interrupt fires — so the hook saves and restores that byte.

**Sound ids are bank-relative.** The same number means a different sound depending on which
audio bank is loaded. The profile defaults use only the 64 SFX that resolve identically in all
three banks, so a capture or a faint fired mid-battle cannot play the wrong thing. Ids are
derived from header label offsets in `data/pret_rom_syms.json`
(`id = (SFX_X - SFX_Headers_N) / 3`), not guessed.

`M.detectCompanionPatch()` reads the beacon and only enables SFX at ABI ≥ 2, so an unpatched
cartridge is a clean no-op instead of a stray write.

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
free home bytes against Red/Blue's 156. Yellow is Lua-only and loses nothing by it.

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
| ABI version byte | `2` (SFX support) |
| the SFX request byte is consumed | cleared within 10 frames |
| **a sound actually starts** | `wChannelSoundIDs` CHAN5-8 `0/0/0/0` → `140/0/0/0` |
| a zero request does not retrigger | `0/0/0/0` → `0/0/0/0` |
| the game still plays *after* the SFX hook fired | `(5,6)` → `(4,6)` |

The sound check asserts on `wChannelSoundIDs`, not on the request byte clearing — the byte
clearing only proves our own code ran, whereas the channel changing proves the game's audio
engine accepted the sound. `140` is `0x8C`, exactly the `SFX_TINK` id requested.

The two "still plays" rows are there for the same reason: a patch that quietly breaks what it
hooks is worse than no patch, and calling `PlaySound` from inside an interrupt is exactly the
kind of thing that corrupts a bank or a stack without any other visible symptom.

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
