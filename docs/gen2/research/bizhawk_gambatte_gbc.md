# BizHawk 2.11.1 / Gambatte core for GBC — memory domains, bus-exec hooks, mode selection

Retrieved 2026-09-21 unless noted. BizHawk tag `2.11.1` = commit
`bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5`
(https://github.com/TASEmulators/BizHawk/releases/tag/2.11.1, retrieved 2026-09-21). The
Gambatte core in BizHawk is a C# wrapper (`src/BizHawk.Emulation.Cores/Consoles/Nintendo/Gameboy/`)
around a native C++ library vendored as git submodule `submodules/gambatte`, pinned in the
BizHawk repo at commit `d49b895375689f7cd05778f2c13ab4cbc5d8f7c3` in the fork
`pokemon-speedrunning/gambatte-core` (`.gitmodules` at BizHawk `2.11.1`,
https://github.com/TASEmulators/BizHawk/blob/2.11.1/.gitmodules, retrieved 2026-09-21).

## Pins

- BizHawk `2.11.1` = commit `bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5`
- `submodules/gambatte` at that tag = `pokemon-speedrunning/gambatte-core@d49b895375689f7cd05778f2c13ab4cbc5d8f7c3`
- BizHawk C# core files cited below all live under
  `src/BizHawk.Emulation.Cores/Consoles/Nintendo/Gameboy/` at ref `2.11.1`
- Gambatte C++ files cited below all live under `libgambatte/src/` in the pinned gambatte-core commit

## 1. Memory domains Gambatte exposes for a GBC cartridge

Domain creation is in `Gambatte.IMemoryDomains.cs`
(https://github.com/TASEmulators/BizHawk/blob/2.11.1/src/BizHawk.Emulation.Cores/Consoles/Nintendo/Gameboy/Gambatte.IMemoryDomains.cs,
retrieved 2026-09-21). `InitMemoryDomains()` registers, in this order:

| Domain name | Source | Backing | Notes |
|---|---|---|---|
| `WRAM` | `LibGambatte.MemoryAreas.wram` | native pointer, size = allocation | see §1a size formula |
| `ROM` | `LibGambatte.MemoryAreas.rom` | native pointer | full loaded ROM image |
| `VRAM` | `LibGambatte.MemoryAreas.vram` | native pointer | |
| `OAM` | `LibGambatte.MemoryAreas.oam` | native pointer, fixed 160 bytes | `Memory::getMemoryArea` case 4, `&ioamhram_[0]`, length 160 (`libgambatte/src/memory.cpp:1462-1465`, pokemon-speedrunning/gambatte-core@d49b895, https://github.com/pokemon-speedrunning/gambatte-core/blob/d49b895375689f7cd05778f2c13ab4cbc5d8f7c3/libgambatte/src/memory.cpp) |
| `HRAM` | `LibGambatte.MemoryAreas.hram` | native pointer, fixed 127 bytes | `Memory::getMemoryArea` case 5, `&ioamhram_[384]`, length 127 (same file/lines as above) |
| `System Bus` | none (delegate) | `MemoryDomainDelegate`, 65536 bytes | calls `gambatte_cpuread`/`gambatte_cpuwrite` per access — the CPU's own 16-bit address space, banking-aware because it goes through the core, not a raw buffer |
| `CartRAM` | `LibGambatte.MemoryAreas.cartram` | native pointer, size = `rambanks * 0x2000` | registered LAST, after `System Bus`; see §1a for bank layout |

Order and code from `Gambatte.IMemoryDomains.cs` lines ~28-46 (same URL as above, retrieved
2026-09-21):
```
CreateMemoryDomain(LibGambatte.MemoryAreas.wram, "WRAM");
CreateMemoryDomain(LibGambatte.MemoryAreas.rom, "ROM");
CreateMemoryDomain(LibGambatte.MemoryAreas.vram, "VRAM");
CreateMemoryDomain(LibGambatte.MemoryAreas.oam, "OAM");
CreateMemoryDomain(LibGambatte.MemoryAreas.hram, "HRAM");
// also add a special memory domain for the system bus, ...
_memoryDomains.Add(new MemoryDomainDelegate("System Bus", 65536, ...));
CreateMemoryDomain(LibGambatte.MemoryAreas.cartram, "CartRAM");
```
`CreateMemoryDomain` calls `LibGambatte.gambatte_getmemoryarea(GambatteState, which, ref data, ref length)`
and skips registering a domain if `length == 0` ("usually rambank on some carts" — i.e. a
cartridge with no SRAM would have no `CartRAM` domain at all; comment in the same file).

The separate `MemoryCallbackSystem` used for read/write/exec **breakpoint scopes** (not the
raw-buffer domains above) is constructed with a different, narrower name list:
`new MemoryCallbackSystem(new[] { "System Bus", "ROM", "VRAM", "SRAM", "WRAM", "OAM", "HRAM" })`
(`Gambatte.IDebuggable.cs`,
https://github.com/TASEmulators/BizHawk/blob/2.11.1/src/BizHawk.Emulation.Cores/Consoles/Nintendo/Gameboy/Gambatte.IDebuggable.cs,
retrieved 2026-09-21) — note this scope list says `SRAM`, not `CartRAM`; see §2 for how a
bus-exec hit is remapped into this scope.

### 1a. CartRAM layout — flat, not the current 8 KB bank window

`Cartridge::getMemoryArea` (case 3, cartram) returns
`data = memptrs_.rambankdata()`, `length = memptrs_.rambankdataend() - memptrs_.rambankdata()`
(`libgambatte/src/mem/cartridge.cpp:606-609`, pokemon-speedrunning/gambatte-core@d49b895,
https://github.com/pokemon-speedrunning/gambatte-core/blob/d49b895375689f7cd05778f2c13ab4cbc5d8f7c3/libgambatte/src/mem/cartridge.cpp).
`MemPtrs::reset(rombanks, rambanks, wrambanks)` allocates one contiguous block and sets
`rambankdata_ = romdata_[0] + rombanks*rombank_size() + max_num_vrambanks*vrambank_size()` and
`wramdata_[0] = rambankdata_ + rambanks * rambank_size()`, with `rambank_size() == 0x2000`
(`libgambatte/src/mem/memptrs.cpp:89-102`, `memptrs.h:48`, same repo/commit,
https://github.com/pokemon-speedrunning/gambatte-core/blob/d49b895375689f7cd05778f2c13ab4cbc5d8f7c3/libgambatte/src/mem/memptrs.cpp,
https://github.com/pokemon-speedrunning/gambatte-core/blob/d49b895375689f7cd05778f2c13ab4cbc5d8f7c3/libgambatte/src/mem/memptrs.h).

So: **`CartRAM` in BizHawk's memory-domain list is the FULL cartridge SRAM as one flat buffer —
every bank concatenated back-to-back (bank 0 at offset 0, bank 1 at offset 0x2000, ...), size
`rambanks * 0x2000`**, not a single bank-switched 8 KB window. To read a specific SRAM bank at
a given moment you either index `CartRAM` at `bank*0x2000 + offset` (needs to already know the
active bank), or read through `System Bus` at `0xA000+offset`, which the core resolves through
the active bank automatically. Gold/Silver/Crystal's cartridge is MBC3+TIMER+RAM+BATTERY with 4
SRAM banks of 0x2000 each (pret Makefile flags, §Gen 2's `roms.sha1` note below), so `CartRAM`
there should be 0x8000 (32768) bytes total — **derived from the formula above, not independently
confirmed against a live BizHawk memory-domain listing** (†UNVERIFIED, no BizHawk instance run
during this research pass; see Open questions).

The Lua-visible domain/read API (`memory.read_u8`, `memory.getmemorydomainlist`,
`memory.usememorydomain`) is documented at
https://tasvideos.org/Bizhawk/LuaFunctions (retrieved 2026-09-21):
`memory.read_u8(long addr, [string domain = nil])`,
`memory.getmemorydomainlist()` → newline-delimited domain name list,
`memory.usememorydomain(string domain)` → sets the default domain for subsequent no-domain reads.

## 2. `event.on_bus_exec` / `on_bus_read` / `on_bus_write` support

**Gambatte implements `IDebuggable`** and constructs a `MemoryCallbackSystem`
(`Gambatte.IDebuggable.cs`, URL above, `_memorycallbacks = new(new[] { "System Bus", "ROM",
"VRAM", "SRAM", "WRAM", "OAM", "HRAM" })`), so `event.on_bus_exec`/`on_bus_read`/`on_bus_write`
are supported for the Gambatte core in 2.11.1.

Lua API signatures (https://tasvideos.org/Bizhawk/LuaFunctions, retrieved 2026-09-21):
```
string event.on_bus_exec(nluafunc luaf, uint address, [string name=nil], [string scope=nil])
string event.on_bus_read(nluafunc luaf, [uint? address=nil], [string name=nil], [string scope=nil])
string event.on_bus_write(nluafunc luaf, [uint? address=nil], [string name=nil], [string scope=nil])
```
`scope` picks a name from `event.availableScopes()`; passing no scope is legal (see
`lua/gen1/entry.lua:403-404` in this worktree, which always passes a domain and defaults it to
`"System Bus"` — `local function dom(d) return d or "System Bus" end` /
`on_bus_exec = function(fn, addr, name, d) return event.on_bus_exec(fn, addr, name, dom(d)) end`).

**Callback address IS the CPU-bus (System Bus) address, and it is bank-ambiguous by itself.**
`CreateCallback` in `Gambatte.IDebuggable.cs` fires `MemoryCallbacks.CallMemoryCallbacks(address,
0, rawFlags, which + "System Bus")` first — always, regardless of scope filter — then computes
`var bank = LibGambatte.gambatte_getaddrbank(GambatteState, (ushort)address)` and re-dispatches a
SECOND, bank-resolved call into a narrower scope:
- `addr < 0x4000` → `address += bank*0x4000`, scope `"ROM"` (ROM0 fixed bank, but the code still
  adds a bank offset "some mbcs might have this at a different rom bank" per the inline comment)
- `0x4000 <= addr < 0x8000` → `address += bank*0x4000 - 0x4000`, scope `"ROM"` (switchable ROMX)
- `0x8000 <= addr < 0xA000` → VRAM, bank-adjusted only `if (IsCGBMode && !IsCGBDMGMode)`, scope `"VRAM"`
- `0xA000 <= addr < 0xC000` → `address += bank*0x2000 - 0xA000`, scope `"SRAM"` (this is the
  bank-resolved cart-RAM address — note the scope name is `"SRAM"` here, not `"CartRAM"`; the
  `CartRAM` name is only the raw-buffer memory-domain name from §1, a different naming than the
  callback-scope list)
- `0xC000 <= addr < 0xD000` → WRAM bank 0, scope `"WRAM"`
- `0xD000 <= addr < 0xE000` → WRAM bank X, bank-adjusted only in CGB (non-DMG-compat) mode, scope `"WRAM"`
- echo RAM / OAM+0xFE00-0xFEA0 (`"OAM"`) / mmio / HRAM 0xFF80-0xFFFF (`"HRAM"`) / IE reg — per
  the same `switch`

(All of the above: `Gambatte.IDebuggable.cs`, `CreateCallback`, URL above, retrieved 2026-09-21.)

So: **a hook armed with no scope (or scope `"System Bus"`) receives the raw un-banked CPU
address**, exactly as `lua/gen1/signals.lua:11-13` describes for Gen 1 ("PC == site +
capture_offset, bytes re-read on the System Bus at fire time") — the client itself must check
`hLoadedROMBank` (or the Gen 2 equivalent) to disambiguate a switchable-bank hit, which is what
`lua/gen1/signals.lua:11` documents as the proven pattern ("bank check via hLoadedROMBank").
BizHawk *can* hand you the already-bank-resolved address for free by arming on scope `"ROM"` /
`"SRAM"` / `"WRAM"` instead of `"System Bus"`, at the cost of losing the always-fired raw-address
call (both fire; you choose which scope you filter for on registration, or register two hooks).

## 3. Frame alignment inside `on_bus_exec`

`docs/gen1_requirements.md:21` (this worktree) pins: "BizHawk 2.11.1 (Gambatte core); inside
`event.on_bus_exec` `emu.framecount()` equals the frame the step was armed for." I found no
BizHawk/Gambatte source comment that states this explicitly as a frame-counter/bus-exec
interaction (the source shows *that* exec callbacks fire synchronously inside the core's step
loop before the addressed instruction executes, consistent with the pin, but does not itself
assert the framecount equality — that is a runtime behavior, not something visible in the C#/C++
call graph alone). `lua/gen1/signals.lua:11-13` states the same claim was "proven live on
gen1/rc" for Gen 1 DMG-mode titles (Red/Blue/Yellow) under this exact BizHawk/Gambatte version.

I found nothing in the BizHawk source (searched `Gambatte.cs`, `Gambatte.IDebuggable.cs`,
`Gambatte.IEmulator.cs` at `2.11.1`) that special-cases CGB double-speed mode or CGB mode for
callback/frame timing relative to DMG — the callback dispatch code in `CreateCallback` is
identical in shape for DMG and CGB; the only per-mode branches inside it govern VRAM/WRAM
*address* bank-offsetting (`IsCGBMode && !IsCGBDMGMode`, §2), not timing or frame counting. Given
that, and the absence of a primary source contradicting or extending the pin for GBC/CGB:
**unverified for GBC; the Gen 1 pin holds for DMG under the same core, and nothing found
suggests CGB/double-speed changes the bus-exec-vs-framecount relationship, but this was not
independently confirmed for a GBC-mode title in this pass.**

## 4. DMG vs CGB mode selection (`ConsoleMode`)

Sync setting class: `Gambatte.ISettable.cs`, `GambatteSyncSettings.ConsoleModeType` enum =
`{ Auto, GB, GBC, GBA, SGB2 }`, property `ConsoleMode`
(https://github.com/TASEmulators/BizHawk/blob/2.11.1/src/BizHawk.Emulation.Cores/Consoles/Nintendo/Gameboy/Gambatte.ISettable.cs,
retrieved 2026-09-21).

Mode resolution at load, `Gambatte.cs` constructor
(https://github.com/TASEmulators/BizHawk/blob/2.11.1/src/BizHawk.Emulation.Cores/Consoles/Nintendo/Gameboy/Gambatte.cs,
retrieved 2026-09-21):
```
switch (game.System is VSystemID.Raw.SGB ? ConsoleModeType.SGB2 : _syncSettings.ConsoleMode)
{
    case GB:   break;                                              // DMG mode, no flag
    case GBC:  flags |= CGB_MODE;                                  // forced CGB
    case GBA:  flags |= CGB_MODE | GBA_FLAG;                       // CGB-in-GBA timing
    case SGB2: flags |= SGB_MODE; IsSgb = true;
    case Auto: if (game.System == VSystemID.Raw.GBC) flags |= CGB_MODE;   // see below
}
IsCgb = (flags & CGB_MODE) == CGB_MODE;
```
**`Auto` (the default) sets CGB mode purely from `game.System == "GBC"`** — i.e. from whatever
BizHawk's ROM loader / gamedb classified the platform as, not from re-inspecting the cartridge's
own CGB-compatibility header byte itself at this point. A GBC-compatible dual-mode cartridge
(Gold/Silver, header byte 0x143 = 0x80 "CGB compatible, works on DMG too") loaded by BizHawk's
ROM loader as system `"GBC"` will run in CGB mode under `Auto`; running it in DMG mode requires
explicitly setting `ConsoleMode = GB`. Crystal (header byte 0x143 = 0xC0, GBC-only) has no DMG
mode at all — no primary source needed beyond the header byte convention itself, which pret's
Makefile encodes as `-C` in `rgbfix` flags (see `rom_hashes.md` §Pins in this same directory for
the exact `rgbfix` invocation lines).

`IsCGBMode` returns `IsCgb` (the flag computed above); `IsCGBDMGMode` re-reads the cartridge
header at runtime — `gambatte_cpuread(GambatteState, 0x143)` — and returns true when
`(headerCgbCompat & 0x80) == 0 || (headerCgbCompat & 0x84) == 0x84` (`Gambatte.cs`, same URL,
"IsCGBDMGMode" property, retrieved 2026-09-21). This is the flag that gates the VRAM/WRAM
bank-offset branches in §2's `CreateCallback` switch — i.e. "is this cartridge running in the
DMG-compatibility sub-mode of a CGB core" independent of the sync-setting `ConsoleMode`.

## 5. SaveRAM file naming — gamedb hash, not launch path

`docs/gen1_gen2_runtime_checks.md:186-187` (this worktree) claims: "BizHawk names its SaveRAM
file from the gamedb entry (ROM hash, not launch path), so two instances of one cartridge
resolve to a single file and stamp on each other." **Confirmed by BizHawk source:**

- `MainForm.FlushSaveRAM`/`LoadSaveRam` call
  `Config.PathEntries.SaveRamAbsolutePath(Game, MovieSession.Movie)`
  (`src/BizHawk.Client.EmuHawk/MainForm.cs:1881-1882,1958`, ref `2.11.1`,
  https://github.com/TASEmulators/BizHawk/blob/2.11.1/src/BizHawk.Client.EmuHawk/MainForm.cs,
  retrieved 2026-09-21).
- `SaveRamAbsolutePath` builds the filename from `game.FilesystemSafeName()` (plus a
  movie-filename suffix only when a movie is active) —
  `$"{Path.Combine(AbsolutePathFor(...), name)}.SaveRAM"`
  (`src/BizHawk.Client.Common/config/PathEntryCollectionExtensions.cs:233-244`, ref `2.11.1`,
  https://github.com/TASEmulators/BizHawk/blob/2.11.1/src/BizHawk.Client.Common/config/PathEntryCollectionExtensions.cs,
  retrieved 2026-09-21). No launch-path component feeds into the name at all (no ROM file path,
  no directory).
- `game.Name` (what `FilesystemSafeName()` sanitizes) is populated by
  `Database.GetGameInfo(romData, fileName)`: it SHA-1-hashes the ROM bytes, looks the hash up in
  the in-memory gamedb dictionary, and on a hit returns `new GameInfo(cgi)` where `cgi.Name` is
  the gamedb's `Name` field for that hash — falling back to MD5 then CRC32 before finally
  building a `NotInDatabase = true` `GameInfo` (with `Hash = hashSHA1`) only if none of the three
  match (`src/BizHawk.Emulation.Common/Database/Database.cs:270-307`, ref `2.11.1`,
  https://github.com/TASEmulators/BizHawk/blob/2.11.1/src/BizHawk.Emulation.Common/Database/Database.cs,
  retrieved 2026-09-21).

So the runtime-checks doc's claim is confirmed for the common case (ROM hash present in
gamedb): the SaveRAM filename is derived from the ROM's content hash via the gamedb `Name`
field, identical for any two BizHawk instances loading byte-identical ROMs regardless of the
path each was launched from — which is exactly the collision `docs/gen1_gen2_runtime_checks.md`
describes and which `saveram_dir` (a per-instance `Config.PathEntries` base override) works
around, per that same doc.

## 6. What Gen 1's client already does (for Gen 2 to match)

- Hooks are armed through an injected `io` table, never `event.on_bus_exec` directly from
  signal/read code: `lua/gen1/entry.lua:403` defaults the domain to `"System Bus"`
  (`local function dom(d) return d or "System Bus" end`), and
  `lua/gen1/entry.lua:413` wraps it: `on_bus_exec = function(fn, addr, name, d) return
  event.on_bus_exec(fn, addr, name, dom(d)) end`.
- `expected_hex` (the bytes at a hook site, generated ahead of time from the pret build) is
  verified at load, not at fire time: `lua/gen1/entry.lua:187-191` calls `slice_ok(site.rom_offset,
  site.expected_hex)` for the site and its optional `prelude`, refusing to start on a mismatch —
  this is the "hooking the wrong bytes reports the wrong game" guard documented at
  `lua/gen1/signals.lua:6-9`.
- `lua/gen1/reads.lua` never takes a domain argument from its callers — every read in
  `R.decode_party_mon`/`wram_collection`/etc. goes through the injected `io.read_u8`/`io.read_range`
  (e.g. `lua/gen1/reads.lua:147-150`), and the concrete domain binding happens one layer up in
  `lua/gen1/signals.lua`, where every `io.read_u8(ram.wX, "System Bus")` call names `"System Bus"`
  explicitly (checked at `lua/gen1/signals.lua:63-149` — every read in that file's `S.KINDS` point
  functions is `"System Bus"`, never `"WRAM"`/`"CartRAM"` directly). This matches §2 above: reading
  through `System Bus` lets the core resolve the active bank for you, at the cost of the read
  being a live/synchronous core call rather than an async raw-buffer read.
- The frame is stamped at signal build time, not read back later: `lua/gen1/signals.lua:351`
  and `lua/gen1/client.lua:1781` both call `io.framecount()` (never `emu.framecount()` directly)
  to timestamp a fired signal, consistent with the injected-`io` boundary in §3 above.

## Open questions

- Whether the `CartRAM` domain for a live Gold/Silver/Crystal savestate in BizHawk 2.11.1 is
  exactly 0x8000 (32768) bytes was not confirmed by actually loading a ROM/observing
  `memory.getmemorydomainlist()` output — only derived from the `rambanks * 0x2000` formula in
  `libgambatte/src/mem/memptrs.cpp:89-102` plus the pret Makefile's `MBC3+TIMER+RAM+BATTERY`
  cart-type flag implying 4 RAM banks. No 2.11.1 BizHawk instance was run in this research pass.
- Whether GBC double-speed mode changes anything about `on_bus_exec` callback timing or its
  relationship to `emu.framecount()` was not found stated anywhere in the BizHawk/Gambatte
  source reviewed (`Gambatte.cs`, `Gambatte.IDebuggable.cs`, `Gambatte.IEmulator.cs` at
  `2.11.1`); treat as unverified rather than assumed safe.
- Whether `docs/gen1_requirements.md:21`'s framecount-equals-armed-frame claim itself (for DMG
  titles) has a BizHawk source citation beyond the Gen 1 pin file and
  `lua/gen1/signals.lua:11-13`'s "proven live on gen1/rc" note was not independently re-derived
  here — this note treats it as an established prior finding, not a fact re-verified from BizHawk
  source in this pass.
- Whether BizHawk's ROM loader classifies a Gold/Silver ROM as `game.System == "GBC"` (which
  would make `ConsoleMode = Auto` boot it in CGB mode) was inferred from the `Auto` case's
  logic and the header's dual-mode compatibility byte, not confirmed against BizHawk's actual
  gamedb text entry for Gold/Silver's SHA-1 (the relevant gamedb file,
  `Assets/gamedb/gamedb_gbx.txt` or similar, was not fetched in this pass).
