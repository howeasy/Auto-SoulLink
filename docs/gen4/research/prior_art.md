# Prior art: legacy Gen 4 code, archived melonDS probe, the owner's AP HGSS injection

## 1. Legacy Gen 4 code in this repo (Claude Explore audit)

- **Architecture.** The old polling client runs `lua/slink.lua:134` → `game_detect.detect()` → `_CLIENT_MAP.gen4_hgsspt` → `lua/clients/gen4_hgsspt_client.lua`, which requires `memory_nds`, `games/gen4_hgsspt`, `connector` and `hud`.
  - It uses **none** of `lua/core/*`, `hello_session`, `hook_registry`, `reply_dispatch`, `write_permit` or `admission`.
  - It does no ROM-hash admission. `games/gen4_hgsspt.lua:170-172` accepts any NDS ROM, and the variant comes from the filename.
- **Still reachable.** The Manager's New-run form hides Gen 4, but the server maps `heartgold`, `soulsilver`, `platinum`, `hgss` and `renegade_platinum` to `gen4_hgsspt` (`server/adapters/__init__.py:42-44, 215-217`). `_ROM_TYPE_TO_FOUNDATION` has no Gen 4 rows, so HG could pair with Platinum. It never ran on a real game (tag `archive/gen4-gen5`).
- **Salvage:**
  - The PKM crypto in `lua/memory_nds.lua:35-441` is correct: LCRNG, the 24-permutation block table, the checksum-seeded blocks and the PID-seeded party extension.
  - The charmap.
  - The adapter's presentation data.
  - The `gen_gen4_*` data tools, once re-pointed at pret.
- **Discard:**
  - The client, which has a scoping bug (`sync_written_keys`/`all_known_keys` are used before their `local` declaration), dead egg handling, and PID-only keys that fail `is_valid_mon_key`.
  - Filename detection.
  - Raw writes with no permit or checkpoint. `force_faint` never touches the active battler.
  - The hand-seeded encounter and trainer JSON.
  - The sparse, mis-numbered `items/gen4.py`.
  - The Gen 3 physical/special split for moves 1-354.
- **Leads only (verify before use):**
  - The legacy HGSS profile offsets: party 0xA4/0xA8 are confirmed by FILE, see [pk4_and_save.md](pk4_and_save.md).
  - The Ironmon-sourced battle-heap offsets.
  - The Platinum profile. Its box stride of 0x1000 contradicts its own comment, and its PC offsets are marked "verify".
- `lua/memory_nds.lua` is shared with the Gen 5 legacy client (`lua/clients/gen5_bw_client.lua:67`).

## 2. Archived melonDS platform probe

The probe is on tag `archive/claude/gen4-prep-planning`:
- `docs/gen4/platform_probe.md`
- `lua/tests/probe_gen4_platform.lua`

It measured, on BizHawk 2.11.1 / melonDS / HG:

| Measured | Result |
|---|---|
| melonDS module | a **waterbox** guest (`dll/melonDS.wbx.zst`), so it never appears in `Process.Modules`. The old `platform_execution.lua` identity scheme cannot work; pin the core by **file hash**. |
| Memory domains | `Main RAM` 4 MiB (0-based) and `ARM9 System Bus` (same bytes at 0x02000000+). Also `ROM` (128 MiB), `SRAM` 512 KiB, TCMs, BIOS, Firmware. |
| Registers | `emu.getregisters()` gives `"ARM9 r0".."ARM9 r15"` plus ARM7; `emu.setregister` round-trips |
| Events | `event.on_bus_exec` present; `memory.registerexec` absent; `event.onloadstate`/`onsavestate` present |

**Error in that probe:** the "pointer chain = sSaveDataPtr 0x02111880" claim is wrong about the symbol. See [sources_and_symbols.md](sources_and_symbols.md).

**Not measured:** exec hooks on overlay code, JIT, per-hook overhead, `gameinfo.getromhash()` on NDS, write persistence. These are the G1 probe rows.

## 3. The owner's Archipelago HGSS injection (Claude Explore study)

Trees: `E:/Howard/hgss_archipelago-{vanilla,hgengine,master}` and `E:/Howard/Archipelago-0.6.4/worlds/pokemon_hgss`.

**Warning:** several of those docs and scripts contain build-box credentials in plaintext. Never copy them. The SLink lanes use the fork's key-based `hgbox` ssh alias only.

### Proven mechanism: a persistent RAM struct on retail HG (and on hge)

- **Resident synthetic overlay 129** at **0x023D8000**. Vanilla overlays end at 0x0226EC40.
  - Loaded by a `Main()` once-hook at **0x02000CD0** (`bl load_ap`; restore `r0=0, r1=3`).
  - The loader lives in the transient boot window 0x02110334..0x021103A0 and calls `HandleLoadOverlay` through the 0x02007000|1 re-entry.
- **Per-frame refresh:** the vanilla path hooked `bl sub_020183B0` at 0x02000E0C. **Don't reuse that `ap_perframe` stub:** its `pop {r0-r2,lr}` assembled as `pop {r0-r2,pc}`, so the tail-call never ran. The later master used `CreateSysTask` on the main loop.
  - Anything that loads files or allocates must run in a main-loop task, not in VBlank; `Bag_AddItem` froze the game when called from VBlank.
- **ROM rewrite:**
  - arm9 is BLZ-compressed: decompress it and zero the word at 0xBB4 to disable the boot decompressor.
  - Append the overarm9 entry `(129, 0x023D8000, size, 0,0,0, 129, 0)`.
  - Rename the header and recompute its CRC16 (reflected 0xA001, init 0xFFFF, over [0:0x15E]).
  - Ship as a bsdiff4 patch with a round-trip check.
  - `apnds` (in the master tree) can unpack/repack NDS, handle BLZ/LZ10 and NARC, and edit module params. `ndspy` and `bsdiff4` are installed locally.
- **Address stability on hge:** linker addresses move per build. The fix was a first-placed `.ap_ptr` section that pins the pointer slot at 0x023D8060.
- **Free resident RAM on hge:** none above 0x023DEE6C.

### BizHawk-side lessons

- **Domains:** use `ARM9 System Bus` for absolute addresses; `ROM` is readable, and writable on melonDS.
- **The SaveData address changes on every boot**, so re-read it every tick.
- **Pointer vs save load:** the pointer is non-zero after about frame 134, which happens before "Continue". A non-zero pointer does not mean the save is loaded; validate it with the page signature.
- **Savestates** must come from the exact build under test.
- **Battery save attach:** copy the save to `<rom basename>.SaveRAM`, boot, and press A/Start only (never the D-pad) to reach Continue.
- **The "touch needed" stall** on hge came from loading a **vanilla** save into hg-engine, whose save layout is incompatible. It is not evidence that touch is required (owner, 2026-09-26: no touch needed).

**Relevance to SLink:** no companion patch is needed for the first release (D-defaults in [../PLAN.md](../PLAN.md)). This mechanism is the documented seam if a native mailbox is ever needed.
