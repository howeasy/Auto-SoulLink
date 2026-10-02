# Shared NDS companion image and pin contract

NDS-1 supplies offline SOURCE/MODEL/FILE tooling, not a qualified companion,
admission decision, allocator, native ABI implementation, or emulator receipt.
Game-specific addresses, records and policy belong to per-title bindings. This
card neither relocates tables nor appends overlays. Nothing here writes a ROM or
save file. Production admission and independent review remain coordinator gates.

## Image ownership and ndspy

`tools/nds_image.py` opens paths with `rb` and a read-only mmap. Bytes inputs must
be immutable `bytes`. Use `with NdsImage.load(path) as image:` to close mappings.
`apply()` returns `(output_bytes, manifest)`; it never saves those bytes. The
caller owns any later authorized output-file workflow. No-op bytes inputs are
returned directly; mapped inputs require one output allocation. Edited outputs
are joined from views and small replacement buffers into one output allocation.
Hashing and unchanged-range comparisons are chunked. Containers, not complete
images, are copied for decompression. Do not retain multiple retail outputs.

ndspy is allowed for reading helpers and `codeCompression` only. Never use
`NintendoDSRom.save()` or `saveToFile()` in the editor/build pipeline. The retail
counterexample test intentionally calls `save()` **in memory only** to show its
failure: ndspy 4.2.0 discards Gen 5 ARM9i/ARM7i payloads while retaining their
header pointers and unit code. A passing ndspy load is not preservation proof.

## Extent classification

`image.containers` maps stable names to `Extent(name, offset, length, kind)`.
`image.extents` is an ordered, nonoverlapping partition of every byte of the
input. Empty optional containers are absent. Intersecting physical payloads,
bad table lengths, duplicate overlay identities/file ownership, out-of-file
ranges, and inconsistent overlay file lengths fail closed. Overlapping overlay
**RAM** ranges are legal: identify an overlay by processor and ID, never RAM
address alone. FNT bytes are preserved as a container; this card does not resolve
filenames or validate every filename-tree reference.

| Name | Contents and interpretation |
|---|---|
| `header` | 0x000–0x3FF, including unit code 0x12, revision 0x1E, NTR used size 0x80, declared header size 0x84, and DSi extended fields |
| `header_reserved` | 0x400 through declared header size; preserved, never assumed free |
| `arm9`, `arm7` | ROM offsets and sizes from header, with ARM9 RAM base retained separately |
| `fnt`, `fat`, `y9`, `y7` | Original filesystem/name/allocation/overlay table bytes |
| `banner` | Sized by supported version 1, 2, 3 or 0x103; unknown versions refused |
| `overlay9:<id>`, `overlay7:<id>` | FAT payload owned by that table entry; metadata includes file ID, RAM/BSS sizes, compression flags and entry offset |
| `file:<id>` | Other nonempty FAT file |
| `dsi_arm9i`, `dsi_arm7i` | Unit-code-bit-1-gated extents at header 0x1C0/0x1CC and 0x1D0/0x1DC |
| `dsi_sector_hashes`, `dsi_block_hashes` | DSi digest table extents at 0x1F0/0x1F4 and 0x1F8/0x1FC |
| `padding_ff@<offset>`, `padding_zero@<offset>` | Unclaimed gaps uniformly FF or zero; classification alone grants no edit authority |
| `unmapped@<offset>` | Other bytes outside known containers, including opaque non-FAT data; preserved, not called free space |
| `trailing_ff` | Contiguous FF suffix after the last used extent |

DSi digest *coverage* ranges can encompass existing payloads and are not separate
physical ownership extents. Unknown/reserved areas stay in the partition and
are checked by the unchanged-byte verifier. This is not an exhaustive semantic
validator of every Nintendo header field or authentication structure.

## Explicit edit transactions

```python
with NdsImage.load(path) as image:
    image.edit(container="file:484", container_offset=4,
               expected_before=b"abcd", after=b"efgh", reason="pinned data edit")
    # Or edit(offset=absolute_file_offset, ...), but never both coordinate forms.
    output, manifest = image.apply()
    verify_only_declared_changes(image, output, manifest)
```

Physical edits are nonempty and same-length. The complete expected-before bytes
must match, the span must lie in one extent, and overlapping edits are refused.
There is no implicit resizing, repacking, alignment insertion or relocation.
Different edits may be adjacent. Reasons must be nonempty. Original bytes remain
read-only even when a later edit or apply fails. Repeated `apply()` is deterministic.

Each `ChangedSpan` has `offset`, `length`, `container`, `before_sha1`,
`after_sha1`, and `reason`; `to_dict()` produces its JSON-compatible form.
The manifest declares complete replacement spans (including unchanged bytes
inside a recompressed container), not just maximal byte-difference runs.
`verify_only_declared_changes(original, patched, manifest)` checks both hashes
for every nonoverlapping span, rejects resizing, and compares **all bytes outside
the manifest**. Hashing only declared spans is insufficient.
Container labels are also checked against the original extent map and allowed FF
slack; a correct byte hash cannot excuse mislabelling an edit as another container.

## ARM9 and overlay edits

```python
image.edit_arm9(ram_address, expected_before, replacement,
                arm9_compressed=True, arm9_ram_base=0x02004000, reason="site pin")
image.edit_overlay(167, ram_address, expected_before, replacement,
                   processor=9, reason="battle site pin")
```

Compression is an explicit per-title input for ARM9, not guessed. The supplied
RAM base must equal the header. Overlay compression and RAM base come from its
own table entry. Site offsets are checked against the decompressed container,
not BSS. All decoded edits to one container are verified against the original
decoded bytes, then composed and recompressed once. Physical/decoded overlap and
overlapping decoded edits are refused. A logical no-op retains original encoded
bytes even if a compressor could choose a different representation.

ARM9 uses `compress(data, isArm9=True)`; overlays use ordinary BLZ. Round-trip
decompression must equal the intended decoded bytes. Raw ARM9/overlays are edited
in place at the same size. Compressed outputs that cease to be compressed are
refused; compression-flag conversions need a future explicit contract.

The exact bound is **new_encoded_size - original_encoded_size <= FF_slack**.
Slack is contiguous FF after the original encoded extent, stopping at the first
non-FF byte or next used physical extent (including FAT payloads and metadata).
A gap alone is not usable slack. No compressed byte may overwrite another file.
The image's overall length never changes. Shrinking leaves vacated original
bytes untouched outside the shortened container; no undeclared fill is emitted.

For ARM9 growth/shrink, the editor declares the header size-field update and
recomputes the NTR header CRC16. When the NitroSDK two-word module-parameter magic
is present, it verifies and updates `compressed_static_end`; overlapping manual
edits to that managed pointer are refused. An absent magic is not fabricated;
the caller's title pins must establish any additional boot metadata. For overlay
growth/shrink it declares the FAT end and compressed-size field updates while
preserving the remaining flags, RAM/BSS size and initializer fields. Signed
overlay hashes, secure-area integrity/authentication and DSi signatures are **not
repaired** here; a container edit is not evidence that the game will execute it.

## Receipt schema and verification

`tools/nds_pins.py` exposes immutable dataclasses and strict JSON schema version
1 (unreleased, so this revision changed it in place) through
`CompanionPin.to_json/from_json/from_dict`. Unknown keys at every nesting level,
duplicate JSON keys, wrong primitive types (including bool for integer),
incomplete hashes, duplicate IDs, invalid ISA/alignment, overlapping sites and
unsupported source kinds are refused. Hashes are full lowercase hex. Every
validator failure, including image-layer errors, is a `PinError`.

- `ParentPin`: clean size, gamecode, version, unit code and SHA1/MD5/SHA256.
- `ContainerPin`: **output** raw/decompressed SHA256, overlay file ID, RAM
  base/size, a per-container `compressed` flag, and `source_provided`. Names are
  `arm9`, `itcm`, `dtcm`, or `overlay7|9:<id>` (canonical decimal id). ARM9/ITCM/
  DTCM omit `file_id`; overlays require it. Autoload blocks are raw
  (`compressed` false, raw hash == decoded hash).
- `SitePin`: a **container name** (never a bare RAM range; a name such as
  `ram:0x021E5900` is refused at the schema level) plus exactly one decoded
  offset or RAM address, ARM/Thumb, expected-before (omitted only inside a
  source-provided container) and after hex, a continuation, evidence class, an
  optional `data` flag, and optional `receipt_ref` / `evidence_ref`. Two construction
  checks go beyond schema shape. (1) For a CODE site whose `after` differs from its
  `expected_before` (or has none), the first instruction of `after` is decoded with
  `tools.nds_isa` under the declared ISA and must not be `unknown` or a `split` Thumb BL
  half; only the entry instruction is decoded because veneers carry a literal word after
  it. A site that patches a pointer/table/literal sets `data=True` to skip the decode
  (alignment still applies); an identity site (`after == expected_before`) pins existing
  bytes and is not decoded. This is a first-instruction plausibility gate, not a proof
  that the bytes are the intended instruction. (2) `continuation` is an absolute RAM
  address where execution resumes: it must be aligned, lie inside (inclusive end) some
  pinned container's RAM extent, and not fall inside the site's own `[start, start+len)`
  bytes (resuming mid-patch or at the patch itself); a replay trampoline may legitimately
  continue back in the original code. Its exact value is otherwise a title-binding
  claim, not resolved here. `receipt_ref` is **required**
  for `PHYSICAL`; for `FILE` a named `evidence_ref` is optional. Sites verify
  against the DECODED container (compressed overlays included) while the
  container records its flag.
- `NoTouchSpan` (field `no_touch_spans`): absolute offset/length and expected
  SHA256 of image bytes this transaction must not change **or overlap with any
  declared manifest span**, even where the bytes happen to be equal.
- `Distribution`: `format` (`ups|bps|xdelta|custom`), `artifact_sha256`,
  `input_sha1`, `output_sha1`, `roundtrip_verified`. Required for `byte_patched`.
- `NativeArena` (`native_arena`): informational `{image, address, size}` naming
  where the companion arena/mailbox lives (for example the ITCM tail candidate
  `itcm 0x01FF8620..0x02000000`, a Gen 4 coordinator candidate, not measured here).
  Never verified, and see "Arena reality" below before treating a value as a hosting claim.
- Full output hashes, named generator/source SHA256s, native ABI and capability
  bits, `dsi_preserved` (plus `dsi_preserved_reason`), `sites_reason`.

**Names.** `no_touch_spans` means "this transaction does not touch these bytes".
It is **not** Gen 3 `randomizer_exclusion_spans`, which is the set of spans the
companion *did* overwrite and a later randomizer must therefore skip. That set is
reserved under the name `randomizer_exclusion_spans`, to be generated from the
final patch manifest by the future randomizer-integration card; it is not
implemented or accepted by this schema (an unknown key today). The old
`protected_spans` and `arm9_compressed` names are likewise rejected.

### What is verified, and what is only recorded

Verified (given actual image objects): parent identity and ARM9 base; output
hashes; each container raw/decoded SHA256, decoded size and (for overlays) file
ID, RAM base/size and compression flag; site before-bytes (parent) and
after-bytes (output) in the decoded container; address-form sites resolve against
the PINNED base and both the parent and the output must agree with it (ARM9, and
per address-form overlay site); declared-diff completeness (`verify_output` with
a parent); no-touch spans; DSi preservation; and, via `verify_distribution`, that
an injected apply callable turns the base into the pinned output.

Recorded only (schema-checked, never proven by this module): `title`, `isa` beyond
the first-instruction decode, `evidence_class` and the refs, `continuation` (alignment,
in-extent and not-inside-the-site checked, never resolved to an instruction),
generator/source hashes, every `SourceBuild` field (repo, commit,
toolchain, patch set, vanilla reproduction, tracked inputs, dirty-tree flag),
`native_abi`, `capabilities`, `native_arena`, `roundtrip_verified`, and any
`*_reason` text. Capability bits and the ABI integer stay opaque to
verification; `CAPABILITY_BITS` / `NATIVE_ABI_VERSION` document the vocabulary
and a test compares them with `patch/src/nds/common/abi.h`.

`verify_parent(image, table)` verifies the entire parent identity.
`verify_sites_before(image, table)` returns **`(verified_ids, omitted_ids)`**:
sites in source-provided containers have no preimage and are listed as omitted,
so `verified == ()` means "nothing was checked", never a before-byte pass.

`verify_output(output_image, table, manifest, parent=parent_image,
reference=reference_image)` checks the above. A table with `no_touch_spans` needs a
comparison base (`parent=` or `reference=`); with neither, the output would be checked
against itself, so it is a `PinError`. A no-touch span inside a container that the edit
recompresses is unsatisfiable by construction: the container re-encodes as one declared
manifest row, which the span would overlap. **Byte-patched output requires the
actual parent bytes**: parent hashes alone cannot prove absence of undeclared
changes. Manifest rows may be `ChangedSpan` or its dict form; anything else is a
`PinError`. DSi preservation checks the extended header and the original DSi
payload/table locations and content. A source-built DSi artifact cannot claim
preservation without a comparison parent. `dsi_preserved=False` is not a silent
opt-out: a `byte_patched` table whose parent has the DSi unit-code bit must carry
a nonempty `dsi_preserved_reason`.

`verify_distribution(base, artifact_bytes, apply_callable, table)` checks the base
SHA1 and the artifact SHA256, calls `apply_callable(base_data, artifact_bytes)`
and compares the result SHA1 with the record and the pinned output. No UPS/BPS/
xdelta code lives here; `roundtrip_verified` is a recorded claim of the build
pipeline. The signature carries `artifact_bytes` explicitly (the card sketch left
the artifact source implicit).

Cost: containers are decoded once per `(image, container, compression)` within a
verification call (memoised and held until the call returns, so memory is the sum
of the decoded pinned containers, tens of MiB for a code-heavy title, not the
image). Hashing and the unchanged-byte comparison are chunked passes over the
whole image. `Hashes.of` is **three** hashing passes (sha1, md5, sha256) per
identity and is not memoised; one `verify_output` call runs it for the output, for the
parent (`verify_parent`) and for a supplied reference (three identities = nine passes
on a 512 MiB image), plus one whole-image unchanged-byte compare for a declared diff,
per-row span hashes and per-pinned-container hashes. `verify_distribution` is one sha1 of
the base and one of the output (the output is hashed once) and one sha256 of the artifact.
No whole-image copy is made for mmapped inputs. Decompression cost scales with the pinned containers only.

## Source kinds and title mapping

For `byte_patched` the parent's ARM9 compression is assumed equal to the output's
(`output_arm9_compressed` decodes both): a compression-flag conversion between parent and
output is out of contract and surfaces as an expected-before mismatch, not a distinct error.

`byte_patched` requires a complete parent and a `Distribution` whose input is that
parent; its verification uses the declared same-size diff, all preimages and
output pins. `source_provided` is allowed on a `byte_patched` container **iff the
container name does not exist in the parent extent map**, and only then may its
sites omit `expected_before` (the Black 2 / White 2 appended-overlay shape: sites
in pre-existing containers are pinned with preimages; sites in the appended
overlay are after-only). `verify_output` fails if the parent already has a
container marked `source_provided`, or lacks one that is not. ARM9/ITCM/DTCM can
never be source-provided there. B2W2 maps to this mode with compressed ARM9,
separate per-title identities/data and distinct output hashes. Code and schema
contain no B2W2 addresses or ROM allowlist.

`source_built` requires `SourceBuild`: source **repo**, full commit, toolchain
identity string, toolchain binary SHA256, **base ROM SHA1**, a `patch_set`
`{slink_repo_commit, patch_tree_sha256}` (the SLink-side change set, distinct from
the upstream commit; for hge, whose fork already contains the SLink changes, the
SLink commit the snapshot came from), and exactly one of a
`vanilla_reproduction` receipt `{base_sha1, rebuilt_sha1, toolchain_id,
toolchain_sha256, notes_ref}` (same commit and toolchain with no SLink patch
rebuild the base byte-identically; `rebuilt_sha1 == base_sha1` is checked) or a
nonempty `vanilla_reproduction_waived` reason. A dirty tree must say so
(`dirty_tree`) and hash every tracked build input in `tracked_inputs` (for hge:
its bytereplacement and hooks files). `base_arm9_compressed` must be explicit for
ARM9 preimages: the output flag is `CompanionPin.output_arm9_compressed` and the
base flag is `SourceBuild.base_arm9_compressed`; one never silently describes
the other.

A source-built table needs no byte parent or patch. Optional named parents:
`parent` (diff base for preimages; must match `base_rom_sha1`), `distribution_base`
(the ROM the distributed artifact applies to; for hge the vanilla HG ROM) and
`reference_build` (a prior build used as the no-touch reference; for hge
cb2dc435...). `verify_output(..., reference=...)` checks the reference identity
and compares no-touch spans against it; a table that declares `reference_build` and is
verified without `reference=` is refused (`declared reference_build needs actual
reference bytes`). `distribution_base` is byte-checked only when passed as `parent=`;
`verify_distribution` binds only its sha1. Resized rebuild diffs need a future
format and are not smuggled through the same-size verifier. Any claimed site
preimage requires actual parent bytes at output verification.

A table with zero sites is refused unless it is `source_built` and carries a
nonempty `sites_reason`.

ITCM/DTCM containers (ARM9 autoload blocks, for example ITCM at 0x01FF8000) are
accepted in the schema. Verification asks the image object for
`autoload_block(kind, *, arm9_compressed)`; without that accessor it raises
`PinError("autoload blocks unsupported by this image object")`. The accessor must
return an `nds_image.AutoloadBlock` (it carries `ram_address`); plain bytes cannot bind
the RAM base that the container and any address-form site assert, so they are refused
by name, and an `AutoloadBlock` at a different base is refused too. For a `source_built`
table, a site with a preimage in `arm9`, `itcm` or `dtcm` (all live in the decoded ARM9)
requires an explicit `SourceBuild.base_arm9_compressed`.

### Arena reality (what `NativeArena` does and does not say)

`NativeArena` is declared, never verified, and nothing in this module checks that an
arena fits anywhere. The facts a title binding must respect: `SLINK_ARENA_SIZE` is
**0x1000**, a Gen 3 heap carve-out size; the Gen 4 HG/SS and hg-engine ITCM autoload
block is **0x620** bytes and the Gen 5 Black/White ITCM block is **0x820** (Black 2 /
White 2 **0x13A0**), so a `NativeArena` window smaller than 0x1000 cannot host the ABI
arena inside the autoloaded part. The Gen 5 plan hosts the arena in the payload
overlay's BSS; where Gen 4 hosts it is that title's own design decision. The test
receipt `NativeArena('itcm', 0x01FF8620, 0x79E0)` is a schema fixture reproducing an
earlier candidate string, not a hosting claim, and is not evidence that the space is
free or large enough.

### Worked pin examples (synthetic, labelled)

No `CompanionPin` exists yet for HG/SS, hg-engine or B2W2. The tests build one
SYNTHETIC table per target shape (tiny in-memory images, MODEL evidence only;
none of these are real pins) and run each through the validators:

| Test | Shape |
|---|---|
| `test_worked_example_hgss` | `source_built`, compressed ARM9 and overlays, vanilla reproduction receipt, two overlays sharing one load address, address-form sites by container name, ITCM `native_arena` |
| `test_worked_example_hge_two_named_parents` | `source_built`, raw ARM9, dirty tree with tracked inputs, vanilla waiver, `distribution_base` + `reference_build`, xdelta `Distribution`, source-provided overlay site, no byte parent |
| `test_worked_example_b2w2_appended_overlay` | `byte_patched`, overlay9:1 absent from the parent's extent map (`source_provided`, after-only sites), declared y9-table/header diff. **This is a y9 table-visibility flip, not a real append:** the payload bytes already exist in the parent as `file:1` and only the parent's y9 length differs. |

The B2W2 example therefore models only the container-naming rule, not payload appending.
Container names (including those in a manifest row's `container` label) resolve against
the PARENT extent map, so a genuinely new payload, whose bytes occupy a parent gap, must be
labelled with that gap's synthesized extent name (`padding_ff@<offset>` or
`unmapped@<offset>`); only the output pin then calls it `overlay9:<id>`. A real append
(new payload plus y9/FAT growth) remains a later card and is not exercised here.

Measured facts (FILE, from NDS-1): only SoulSilver (129 overlays, compressed ARM9)
and the local hg-engine image (150 overlays, raw ARM9) were parsed. HeartGold was
not measured here; the "127/129 compressed overlays, zero slack" figure is the
Gen 4 coordinator report and is not requalified.

Gen 4 coordinator inputs (not requalified):

| Target | Contract mapping |
|---|---|
| HG/SS | pret source rebuild, compressed ARM9; hooks mostly in overlays; do not assume in-place appending works. Record the **full** pokeheartgold commit for ad7a3afa and the clean base SHA1; the vanilla reproduction model is `data/gen4/pret_build_provenance.json` on the Gen 4 branch (HG 4fcded0e..., SS f8dc38ea...). |
| hg-engine | In-fork source-built companion, raw ARM9; fork repo/commit/toolchain, vanilla HG base (`distribution_base`), cb2dc435... as `reference_build` (a candidate observation, not an admission hash), final output hashes. |
| B2W2 | Compressed ARM9, byte-patched parent; appended overlay as above; complete span manifest and per-title provenance. |

## Extension boundary and checks

Table relocation, appending an overlay/FAT/FNT record, heap reservation, code
linking and ROM publication are later cards. They must explicitly declare new
geometry, all pointer/size changes, preservation of non-FAT data and verification
of boot/integrity behavior. `source_provided` describes what the build/patch
produced; it does not authorize the editor to append anything.

Run from the shared worktree with Python 3.12 and ndspy 4.2.0 already installed:

```text
python -m pytest tests/unit/test_nds_image.py tests/unit/test_nds_pins.py -q
```

Core cases synthesize tiny images entirely in memory, including raw/compressed
ARM9, aliased overlays, optional DSi payloads, tables, banner and opaque bytes.
Optional retail cases run one image at a time, defaulting to
`E:/Google Drive/SLink`; `SLINK_NDS_ROMS` overrides that directory. Missing inputs
skip with `NDS_RETAIL_INPUT_ABSENT`; present wrong hashes fail. Missing retail
evidence is not qualification. No tests write ROM/save outputs or invoke an
emulator. Synthetic checks are MODEL; retail no-op/compression facts are FILE.
