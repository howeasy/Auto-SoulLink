# OMP RTC source lookup: Gen 2 SaveRAM tail (2026-09-22)

Card `gen2-omp-rtc-source`, OMP live session `Gen2-Base`, task `cx-cb547279`. The owner told OMP to
hold its reply to Codex; that hold is untouched. The coordinator (Claude, after the handover)
transcribed the findings from the OMP transcript and re-checked the fixture length locally.
Evidence level: **SOURCE only**. No emulator was launched.

## Findings

- **Emulator build.** Local `E:/Howard/Bizhawk/EmuHawk.exe` reports FileVersion `2.11.1.0`,
  ProductVersion `2.11.1+bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5`: the pinned 2.11.1 build
  (file metadata only).
- **Clone/store chain (BizHawk 2.11.1).** `Gambatte.ISaveRam.cs:10-22` `CloneSaveRam` sizes the
  buffer with `gambatte_getsavedatalength()` and fills it with `gambatte_savesavedata`;
  `:24-36` `StoreSaveRam` throws `Size of saveram data does not match expected!` on any length
  mismatch. C glue: `libgambatte/src/cinterface.cpp:184-193`.
- **Length.** `libgambatte cartridge.cpp:368-377`: SRAM bytes (rambanks x 0x2000), plus
  `8 + (isHuC3 ? 0x104 : 14)` when the header declares an RTC. Gold, Silver and Crystal carry
  header byte `0x147 = 0x10` (MBC3+TIMER+RAM+BATTERY), 4 RAM banks:
  **32768 + 8 + 14 = 32790 bytes**.
- **Tail layout.** Save `:504-535`, load `:547-580`: 8-byte big-endian `std::time(0)` base time;
  then `dh & 0xC1`, `dl`, `h & 0x1F`, `m & 0x3F`, `s & 0x3F`, a 4-byte big-endian cycle
  counter; then the latched copies `dh, dl, h, m, s`. That is 14 bytes after the base time.
- **What it depends on.** `hasRtc` (`:136-145`) reads only the ROM header byte (0x0F/0x10 MBC3
  timer, 0xFE HuC3). CGB versus DMG core mode changes neither length nor layout.
- **What it is not.** The 22 bytes are an emulator trailer appended after the 32 KiB SRAM. The
  game's own clock data lives inside SRAM and is covered by the game's save checksum.

## Local corroboration (coordinator)

`tests/fixtures/gen2/crystal_town.SaveRAM` is 32790 bytes, matching the source-derived length.
That file is the legacy staged fixture, so this corroborates length only, not content.

## Consequences for fixture and save oracles

- A fixture or save oracle compares SRAM as the first 32768 bytes. It treats the 22-byte tail
  as emulator state: the base time changes on every save, so the tail can never be a
  byte-identity target.
- A file whose length is not 32790 is refused before any compare, mirroring `StoreSaveRam`.
