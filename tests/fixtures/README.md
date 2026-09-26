# Test fixtures

## What is in here

**Battery saves only.** The files under `gen1/`, `gen2/` and `gen3/` are cartridge save data —
`.SaveRAM` (BizHawk's name for a GB/GBC/GBA battery image) and `.sav`. They are 32 KB for GB/GBC
and 128 KB for GBA, which is the size of the cartridge's save chip.

They contain what a cartridge writes while you play: the party, the boxes, event flags, the
trainer name and ID, and species *indices*. They contain **no game code** — species names, text,
graphics and logic all live in the ROM, which is between 1 MB (GB) and 32 MB (GBA). Every one of
these files was produced by playing a game and letting it save.

## What is NOT in here, deliberately

- **No ROMs.** No `.gb`, `.gbc`, `.gba` or `.nds` file is tracked anywhere in this repository. You
  must supply your own dumps of games you own. Every gate and duo scenario skips with a named
  reason when a ROM is absent (see [TESTING.md](../TESTING.md)).
- **No savestates.** No `.State` file is tracked. A savestate is a full emulator memory dump —
  working RAM, VRAM, registers and ROM-derived data — and is a different kind of artifact from a
  battery save. Nothing here is one.

## Why they are committed rather than generated

Gen 1 and Gen 2 boot their live gates and duo scenarios from these battery saves **on purpose**.
The alternative, savestates, is version-locked: a state written by one BizHawk build stops a
different build on a modal dialog, so every emulator upgrade silently invalidates the suite. A
battery save is just save data — it loads on any build, and on real hardware.

Rebuilding them is rare and scripted (`tools/gen1_playthrough.py`, and the Gen 2 equivalents), and
every file is qualified by `tools/gen1_fixtures.py --qualify` — the `fixtures` release lane fails if
any committed save is not a state the codec can decode.

## Receipts

`gen2/receipts/` holds the committed evidence of live duo and gate runs: the saves each cell
produced, alongside the run's own record. They are pinned artifacts, not logs — a receipt that
cannot be re-checked is not a receipt.
