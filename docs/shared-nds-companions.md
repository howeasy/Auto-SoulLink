# Shared NDS companion composer (NDS-6)

`tools/nds_companions.py` composes an explicitly pinned **byte-patched** image
using the committed `nds_image`, `nds_pins` and `nds_isa` modules. It has no CLI,
ROM/save output path, emulator, linker, allocator, source-build invocation,
randomizer or production-admission switch. Outputs are returned in memory.

Gen 4's HG/SS pret rebuilds and hg-engine in-fork builds are `source_built`:
**compose refuses them**, even if an image and valid source receipt are supplied.
This composer must never become an accidental post-patch step over those builds.
The separate shared pin validators still describe/verify source-built outputs.

## Public contract

```python
manifest = load_manifest(path_or_dict)
output, changed_spans, receipt = compose(base_bytes_or_path, manifest, payload_blobs)
check(output, receipt, base_bytes_or_path)
```

`load_manifest` accepts a JSON path, dictionary or `PatchManifest`. It validates
the complete nested `CompanionPin` through the shared strict schema, refuses
unknown/duplicate keys, and copies mutable inputs into frozen dataclasses/tuples.
Each manifest selects one title/artifact and one fully pinned parent. Selection
among title manifests belongs to a future registry/Manager caller.

`payload_blobs` is an exact dictionary of declared names to immutable bytes;
there is no implicit file loading from payload names. Every size and SHA256 must
match. Missing, extra, unused or changed blobs refuse composition.

`CompositionReceipt.to_dict()` returns a JSON-compatible receipt. `check` accepts
the receipt object or its dictionary round trip. It needs the **actual parent**,
not only its hash; there is no self-checked no-touch fallback. It verifies the
recipe/artifact binding, complete parent identity, site preimages, output pins,
declared-diff coverage, no-touch ranges, header/DSi invariants and a fresh replay
of the distributed artifact through `verify_distribution`.

Policy and validation refusals use `ComposeError.reason` plus explanatory detail.
Filesystem I/O failures retain their underlying OS exception; no missing file is
treated as a successful composition.
Examples: `source_built:refused`, `base:not_pinned`, `compression:mismatch`,
`site:before`, `site:reserved`, `isa:detour`, `isa:mode`, `isa:replay`,
`isa:continuation`, `site:after_plan`, `image:growth`, `header:crc16`,
`header:invariant`, `dsi:payload`, `determinism:mismatch`, `payload:hash`,
`receipt:artifact_binding`, and `output:verification`. Lower-layer pin/image
refusals are retained as detail. A stricter shared schema may reject a malformed
plan at `manifest:pins` before it reaches the corresponding composition step.

## Manifest shape

Required top-level fields (schema version 1):

| Field | Meaning |
|---|---|
| `schema_version` | Integer 1 |
| `pins` | Full shared `CompanionPin`, including expected output, containers, sites, no-touch spans, provenance and `Distribution` |
| `base_arm9_compressed` | Explicit boolean; must equal the pinned output format, since this composer does not convert storage format |
| `operations` | Exactly one operation per pinned site; no hidden writes |
| `payloads` | `{name, size, sha256}` entries for supplied payload bytes |
| `reserved_sites` | Unique even plain RAM addresses that planned site windows must not overlap |

Addresses refer to an explicitly named pinned container: `arm9`, `itcm`, `dtcm`
or `overlay9:<id>`. The ARMv5TE ISA helpers target ARM9; overlay7 sites are refused.
ARM9 and overlay editing go through the shared decoded-container editor. ITCM/
DTCM use `autoload_block` to map the runtime address to its **file data inside
decoded ARM9**, then edit ARM9 normally. BSS is not a file payload and is never
implicitly created. Autoload metadata must expose its pinned base/offset.

Raw ARM9 follows `base_arm9_compressed=False` and the shared raw edit path.
Decompression/recompression is skipped; no byte sniffing overrides the declaration.
The manifest/pin format declarations must agree, and identity/site/container pins
remain mandatory. A true declaration must actually decode as BLZ. These are
pinned build facts, not a heuristic that proves what the game's loader executes.

Reserved addresses apply to the whole planned window, including replay/payload
destinations and identity probes, not just its first byte. For example an hge
manifest must reserve `0x02000CD0`, its Main-to-load_arm9_expansion call, whenever
that artifact is used as a raw byte-patching input. A `source_built` target is
still refused regardless of this additional reservation.

## Operations and replay provenance

Every operation names `site`, whose `SitePin` owns the container, ISA, exact
before/after bytes, address/offset, continuation and evidence references.

| Kind | Additional fields | Meaning |
|---|---|---|
| `identity` | None | A no-op instruction window. Replay planning at the same address must succeed and reproduce the original bytes exactly. |
| `payload` | `payload` name | Place the exact blob at that pinned existing site; bytes must equal the site's after pin. No free-space/RAM-ownership inference is made. |
| `detour` | `target` code pointer, `form`, optional `cond` | Generate with the shared ARM/Thumb encoder and decode the result under the declared ISA. Exactly one replay operation must refer to this site. |
| `replay` | `replay_of` detour site ID, `form` = `b` or `veneer` | Replay the detour's verified base instructions at this separately pinned destination, followed by an encoded return to the original continuation. |

`target` is a code pointer: bit 0 denotes Thumb, while ARM pointers are word
aligned. Modes, ranges and branch forms are validated by `nds_isa`. Veneer
validation decodes its instructions and checks its literal target as **data**;
it does not misinterpret the target word as another instruction.

Displaced bytes are derived from the original decoded base after checking their
pin, never from post-edit bytes or an unverified caller buffer. The original
continuation must equal `site_address + exact_displaced_length`. Replay ISA must
match the displaced ISA, and its continuation must equal the original site's
continuation. The replay destination has its own full before/after pin, including
the appended return branch. Every generated byte must match the expected after
pin; knowing the source bytes alone cannot authorize arbitrary replay bytes.

No `pic_offsets` escape hatch is exposed. A refused shared replay plan stays a
refusal. There is no new instruction decoder or substitute relocator here.
The manifest describes where native payload code is expected; the composer does
not prove that the payload reaches its replay path or preserves registers/LR/
flags/stack semantics. Thumb veneers clobber r3, and relocated calls change LR;
those remain engine-binding design and later execution-gate obligations.

## Determinism, preservation and distribution

Composition runs the recipe twice. It compares the complete output SHA256 and
the exact changed-span tuple. The first composition and its audit image live
inside one helper (`_first_pass`); when it returns, only that result's SHA256 and
spans survive, so the first output buffer and the audit `NdsImage` that referenced
it are both released before the second composition allocates. The second output is
then the one retained result. `check` is run on it, and that call performs a third
composition (the distribution replay) plus the audit's transient state while the
second result is still held. Peak is therefore one retained result plus one
in-flight composition/audit, not two retained results; it is not a lower bound
beyond that. The shared distribution verifier executes the serialized artifact
against actual base bytes; no cached output is used as the apply callback.

Cost: `compose` performs three full compositions and roughly a dozen full-image
hash passes per call on retail-size images.

The NTR header CRC16 must be valid on input and output. File length, unit code,
0x80 NTR used size, 0x84 header size, 0x210 DSi total size, ARM9i/ARM7i offsets
and sizes (including 0x1CC/0x1DC) are preserved. DSi extended-header bytes,
payloads and digest-table locations/content remain identical regardless of a
pin table's opt-out reason. A generic DSi-dropping policy cannot weaken this
composer's stricter preservation contract. The shared editor declares its ARM9
compressed-size/SDK-pointer/header-CRC or overlay FAT/y9 size updates.

Recompression uses `isArm9=True` through the editor, with growth bounded by
contiguous FF slack before the next used extent. No table relocation, overlay
append or image resizing is implemented. `source_provided` containers are refused
here even though the pin schema can describe them for other build pipelines.

`no_touch_spans` means this transaction must neither change nor overlap those
bytes, including a broad compressed-container replacement that happens to retain
some original bytes. It is not Gen 3's different set of post-patch randomizer
exclusions. No randomizer integration or server file is changed by NDS-6.

The distribution format is `custom`: canonical ASCII JSON containing the recipe
and payload hex. The embedded recipe omits only the `Distribution` record to
avoid a self-hashing cycle. `distribution_artifact(manifest, payload_blobs)`
builds these bytes before the final artifact SHA256 is filled into the pin table;
the expected output/container/site hashes must already be known from the build.
`compose` refuses a wrong artifact digest. UPS/BPS/xdelta are schema vocabulary,
not codecs implemented by this composer; their manifests are refused here.

Receipt booleans record what this composition observed; they are not signatures,
production admission or proof of repeated execution on another machine. The
caller must trust/pin the manifest and toolchain provenance separately. The custom
recipe carries data only; it does not deserialize executable code or run commands.

The composer currently uses two existing shared helper entry points:
`nds_image._crc16` and `NdsImage._from_data` (a borrowed read-only buffer with no
mapping ownership transfer). These avoid duplicating CRC logic or copying a
512-MiB input for distribution replay. A future public alias could stabilize this
API; no existing shared module was changed for this card.

## Verification and boundaries

```text
python -m pytest tests/unit/test_nds_companions.py -q -p no:cacheprovider
python -m ruff check tools/nds_companions.py tests/unit/test_nds_companions.py
```

Core tests use synthetic images and the real shared modules: ARM/Thumb detours
and pinned trampolines, compressed/raw ARM9, autoload payloads, missing/changed
base/site/blob, reserved addresses, no-touch overlap, header/DSi corruption,
replay refusal, wrong displaced bytes, mode mismatch and nondeterminism.
Two guard-is-load-bearing tests prove the reservation guard and the replay
relocation step are what produce their refusals: with the guard neutered the
`site:reserved` / `isa:replay` refusal disappears. For the replay mutant the
mis-relocated image then composes silently, because the fixture reference output
is itself the unrelocated form; no independently-correct pin rejects it. These
tests show the guards are exercised, not that every wrong image is caught.
A `dsi=False` (unit code 0, no DSi payload containers, the HG/SS profile)
parametrization composes, checks, and keeps the 0x210/0x1CC/0x1DC fields equal.
`load_manifest` rejects a non-`al` `cond` on a Thumb detour other than `bcond`
rather than dropping it. `check` refuses a receipt whose `changed_spans` were
emptied for a non-no-op composition.

Optional retail tests locate Black 2 and White 2 through `SLINK_NDS_ROMS`
(default `E:/Google Drive/SLink`) and enforce the full research SHA1s. Absent
inputs skip with `NDS_COMPANION_RETAIL_ABSENT`; present wrong hashes fail.
The eight-byte identity window is `0x0200C2D4` (MOV / complete BL / MOV).
Starting eight bytes at exactly `0x0200C2D6` cuts the next BL and is retained as
a refusal control. These are vanilla-byte sources near the requested AddPkm
area, not behavior claims or native code execution. The no-op result remains
byte-identical; it does not install a runnable companion.

Retail checks also route the `0x0200C2D6` control through `compose`: an identity
pinned there refuses with `isa:replay`, in addition to the direct `plan_replay`
assertion. Retail checks compare every original FAT payload through ndspy reading, enforce
the measured 348/308-byte sequel ARM9 slack, and keep ndspy's in-memory `save()`
DSi-loss counterexample refused. No generated ROM is written. Unit tests are
MODEL; retail artifact observations are FILE. Boot, memory reservation, original
instruction semantics, cache maintenance, native calls, save durability and
release readiness remain unverified. Per-game/server adoption is outside this
lease.

Not enforced by the composer: `Operation.target` ownership and containment. The pin
layer enforces continuation containment, but nothing enforces that a detour target
lands in code the title owns; target reach is checked only by `nds_isa` encoding.
The pinned `after` hex remains the truth. Whether to add a schema constraint is a
per-title decision.
