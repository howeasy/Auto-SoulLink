# NDS image editor contract (`tools/nds_image.py`)

Editor-specific companion to `shared-nds-companion.md` (which owns the pin schema and
the overall boundary). Nothing here writes a ROM: `apply()` returns bytes in memory.
Evidence labels: MODEL = synthetic fixtures, FILE = measured on the four local Gen 5 ROMs.

## Refusals are all `ImageError`

Malformed geometry, ambiguous ownership, unauthorized edits **and** the formerly leaky
cases are one type: a 0-byte file, a non-ASCII gamecode, any use of a closed image
(`apply`, `read`, `edit`, `edit_arm9`, `edit_overlay`, `decoded`), and a non-`bytes`
`expected_before`/`after`. Missing files still raise `FileNotFoundError` (an OS error).
The one deliberate exception is a wrong argument **type**: `NdsImage.load()` takes only an
immutable `bytes` or a `str`/`Path` and raises `TypeError` for anything else (including a
`bytearray`). `verify_only_declared_changes(original, patched, manifest)` takes an
`NdsImage`, any bytes-like object (`bytes`, `bytearray`, `memoryview`: a mutable buffer is
wrapped read-only and never copied) or a `str`/`Path` (mapped read-only, closed on return)
for either image; any other type is an `ImageError`.

## Table parsing

- All-zero 32-byte `y9`/`y7` entries are table padding and are skipped, not parsed as
  overlays. A real entry cannot be all zero (it has a RAM base and a file size).
- **Aliased FAT entries cannot be opened.** Two FAT ids that overlap (or one range
  shared by an overlay and a plain file) make `load()` raise `overlapping extents`.
  The partition is a strict one-owner-per-byte model; aliasing is not supported.

## ARM9 compressed_static_end (NitroSDK module params)

The module-params struct is seven u32 words followed by the doubled magic
`21 06 c0 de de c0 06 21` (so it starts 0x1C before the magic):
`autoload_list_start, autoload_list_end, autoload_start, static_bss_start,
static_bss_end, compressed_static_end, sdk_version`.
FILE: on Black, White, Black 2 and White 2 the magic occurs **exactly once** in the
decompressed ARM9, at 0xFCC; `compressed_static_end` (0xFC4) equals
`arm9_ram_base + compressed ARM9 file length` (0x02073898, 0x020738A4, 0x020776A4,
0x020776CC); the SDK word is 0x0503757C. The retail tests assert all of this.

- Present: the editor updates the pointer to the new encoded length (verified
  against the original first); a manual edit overlapping the pointer is refused.
- **Absent and the encoded length changed: refused** with
  `unmanaged ARM9 compressed_static_end`, because the boot metadata would silently go
  stale. Opt in only for a title that genuinely has no module params:
  `image.apply(arm9_lacks_module_params=True)`. A same-length result needs no pointer
  and is never refused for this.

## Size-bearing fields the editor maintains

Exactly three, and only when the encoded ARM9 length changes (or, for CRC16, whenever a
header byte below 0x15E changes): (1) the NDS header ARM9 size at **0x2C**; (2) the
NitroSDK module-params **`compressed_static_end` = ram_base + encoded length** (inside the
decoded ARM9, re-compressed with it); (3) the header **CRC16** at 0x15E. For overlays the
FAT end word and the y-table compressed-size field are updated instead. MEASURED (FILE): on
all four retail ROMs the first three words of the decoded ARM9 are the `0xE7FFDEFF`
secure-area filler, so the verbatim 16 KiB prefix carries **no size fields**; the module
params are the only in-ARM9 size to keep consistent (asserted by the retail test).

## Header CRC16

The NTR header CRC16 at 0x15E covers `data[:0x15E]` (poly 0xA001 reflected, init
0xFFFF) and is recomputed whenever a header byte changes (e.g. ARM9 size at 0x2C).
FILE: the real ROM header is the oracle; `[:0x160]` or init 0 do not match it.
The CRC is derived data: `edit()` refuses any span overlapping `[0x15E, 0x160)` (only
`apply()`'s own recomputation writes it), and `verify_only_declared_changes` refuses an
output whose header CRC16 disagrees with the CRC16 of `output[:0x15E]` whenever any
declared row touches the header `[0, 0x160)`. It is not checked on header-untouched
manifests so an input whose own CRC was never valid can still be no-op verified.

## Shrinking

A smaller re-encoding shortens the container in place and updates the size metadata
(ARM9: header 0x2C; overlay: FAT end and the y-table compressed-size field). The
image length never changes and **nothing is zero-filled**: the vacated bytes keep
their original values (tested). On reparse the vacated bytes plus the old FF slack
form one gap that is classified **`unmapped`** (mixed bytes), not `padding_ff`, and it
no longer counts as slack because its first byte is generally not FF. It reclassifies
as `padding_ff` only if every vacated byte happened to be FF. Consequence: a second
pass over a shrunk output cannot regrow in place even though the bytes are reserved.

## Verifier versus editor on slack

`verify_only_declared_changes` accepts a manifest row that **starts at a container's
first byte and extends into its FF slack** (legitimate recompression growth). The
editor never stages such a row through `edit()`: a physical edit crossing the
container end is refused as crossing an extent boundary; slack is consumed only by
the recompression path. A manifest from another producer may therefore claim slack
rows the editor could not have produced; the verifier still checks both hashes and all
bytes outside the rows. (Both directions are tested.) `ChangedSpan` has no flag for
this because its schema is fixed; this paragraph is the contract.

## Compression refusal mode

ndspy `compress(isArm9=True)` may normalize the ARM9 first byte, so a title whose ARM9
does not round-trip fails with **`no longer has valid BLZ compression`** (the message
now names this). All four Gen 5 ROMs round-trip (FILE). Gen 4 HG/SS compressed ARM9 is
in scope but **unmeasured** for this mode. Overlays use ordinary BLZ and the same check.

## Autoload blocks

`image.autoload_block(kind, *, arm9_compressed=None)` for `kind` in `'itcm'`/`'dtcm'`
returns the autoload **data bytes** (bss excluded) as an `AutoloadBlock` (a `bytes`
subclass, so `bytes(block)` is the data) with `.ram_address`, `.size`, `.bss_size`,
`.offset` (data offset inside the **decoded** ARM9), `.kind`, `.index` and
`.as_tuple() == (ram_address, size, bss_size, offset)`. It returns `None` when that
kind is absent (including an empty table) and raises `ImageError` when the module
params are absent, the kind is unknown, or two entries claim one kind.
`image.autoload_blocks()` returns every table entry in list order (`kind` is `None`
for non-TCM blocks). Autoload data runs contiguously from `autoload_start` in list order.

- Classification by RAM base: ITCM `0x01FF8000..0x02000000`; DTCM
  `0x027E0000`(Gen 4) or `0x02FE0000`(Gen 5), 16 KiB. Both DTCM bases and the 12-byte
  row width are exercised by synthetic fixtures (`test_gen4_12_byte_rows_classify_itcm_and_dtcm_at_the_gen4_bases`).
- **Row width is not fixed.** FILE: the Gen 4 SDK (SoulSilver, hg-engine) uses 12-byte
  rows `{ram, size, bss}`; the Gen 5 SDK uses **16-byte** rows `{ram, size, ram-again,
  bss}` (the third word equals the RAM base in all four ROMs, meaning unknown; the proof is indirect: the 16-byte width is only accepted when it holds, `nds_image.py` width selection, and the four-ROM retail test tiles with it; the research names it `sinit`, a name that is not established). The
  width is chosen by requiring the entry sizes to sum to `autoload_list_start -
  autoload_start`; an ambiguous or non-tiling table is refused (`entry_size=` overrides).
- Row sanity (refused, `ImageError`): a row with RAM address 0 or size 0, and a 16-byte
  row whose third word is not equal to its RAM address (the measured Gen 5 invariant). The
  12/16 width ambiguity refusal is unchanged; an explicit `entry_size=` is held to the same rules.
- **`arm9_compressed=None` has a precondition: the NitroSDK module-params magic must be in
  the STORED ARM9 bytes.** Inference reads `compressed_static_end` (0 means raw, RAM base +
  stored length means compressed, anything else is refused) from the stored bytes, so on a
  BLZ ARM9 it only works while the struct sits in the uncompressed literal prefix (retail
  ROMs measured: it does, at decoded 0xFCC). When the magic is not found there (compressed
  past the prefix, or no module params at all) it raises the named `ImageError` "ARM9 module
  parameters absent or not in the stored bytes; pass arm9_compressed explicitly". Every
  caller that cannot guarantee the prefix (any new title) must pass `arm9_compressed=`
  explicitly; the explicit path then needs the magic in the DECODED ARM9 instead. Tests:
  `test_compression_inference_needs_module_params_in_the_stored_bytes` (magic past the
  literal prefix, and 12-byte rows with module params absent).
- Read path only; writes to an autoload go through the normal decoded-ARM9 edit machinery.

FILE (decoded ARM9 offsets), all four ROMs share the DTCM/other rows:

| ROM | autoload_start | rows (ram, size, bss) |
|---|---|---|
| Black | 0xA5E80 | ITCM 0x01FF8000 0x820 0; DTCM 0x02FE0000 0xA0 0x20; 0x02400000 0x20 0; 0x06898000 0x20 0 |
| White | 0xA5EA0 | same as Black |
| Black 2 / White 2 | 0x99740 / 0x99780 | same but ITCM size 0x13A0 |

For the Gen 4 mailbox-arena candidate: SoulSilver/hg-engine ITCM is 0x01FF8000 size
0x620 (DTCM 0x027E0000 size 0x60 bss 0x20), consistent with an ITCM tail
0x01FF8620..0x02000000 (Gen 4 coordinator measurement, census W1-W3, commit 29febbf3 on claude/gen4-support-framework-dfd5e2; read-only; not requalified in this worktree, no test here asserts 0x620).

## Tests and memory

`python -m pytest tests/unit/test_nds_image.py -q -rs -p no:cacheprovider`. Retail
cases skip with `NDS_RETAIL_INPUT_ABSENT` when ROMs are absent (override the directory
with `SLINK_NDS_ROMS`) and fail on a wrong hash. Memory: the editor maps one image
read-only plus one output allocation (about 1x the ROM, 256 or 512 MiB). The ndspy
counterexample test additionally serializes a second copy in memory and costs about
**3x the ROM size** at peak on 512 MiB images: run one retail case at a time. The real
edit-path test drives `edit_arm9` + `apply()` on Black and Black 2 in memory only and
includes a mutation control that flips `isArm9` in a temp copy of the module. The retail
shrink test zeroes 0x20000 bytes of Black 2 code and asserts the header 0x2C,
`compressed_static_end`, the header CRC16 (against the real header oracle), redecode
equality and that growth never exceeds the FF slack; it passes on real data (no named refusal).
