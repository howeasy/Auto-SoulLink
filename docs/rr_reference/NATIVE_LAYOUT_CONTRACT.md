# Generated RR companion memory contract

`patch/layout/rr_v2.json` is now the authoritative definition for the retained
companion memory layout. This is an incremental extraction, **not relocation or
an exclusive-ownership approval**. The arena remains `0203F800..02040000`:
16 used regions consume1501 bytes, and8 reserved/unassigned intervals account for
the other547 bytes. Reserved does not mean free. The retained libc overlap,
possible replacement arena, and host reset/load/reconciliation gates remain open.

The schema defines11 structures and98 fields, including signedness, alignment,
counts, multidimensional array shape, every field offset, and trailing struct
padding. It includes the ROM injection range, ABI/descriptor values, capabilities,
and mailbox argument/context/reservation partitions. Ordinary game-engine RAM,
OAM, palette records, and function addresses remain separate RR reverse-engineered
profile facts; this generator does not claim to own those resources.

## Generation and enforcement

```powershell
python patch/tools/native_layout.py
python patch/tools/native_layout.py --check
```

The generator deterministically emits:

- `patch/src/native_layout_generated.h`: C address/size constants and compile-time
  assertions for sizeof, alignment, offsetof, signed type and full array shape.
  Every actual shared C struct invokes its generated assertion macro.
- `lua/rr/native_layout.lua`: inert Lua tables for regions, fields and fingerprints.
  `lua/mailbox.lua` consumes them and exposes `MB.LAYOUT` and `MB.OPCODE_ADDR`.
- `patch/src/slink.ld`: the existing code origin/length, with code-range checks
  and the existing prohibition on implicit mutable `.data`, `.bss` and COMMON.

Unknown/missing fields, invalid types/counts/dimensions/alignment, overlapping
regions, unaccounted arena bytes and unsupported arena/ROM moves are rejected.
Revision-one consumer obligations also fix the complete member order, region-to-C
type bindings, and raw-buffer extents/alignment. A schema cannot omit
`GhostState.lifecycle` as alleged trailing padding, shrink/detach a typed region,
or turn part of the choices buffer into a reserved gap. The C menu reader uses
the generated choices size. These independent obligations validate the declared
contract; they do not provide a second runtime address map.
The build checks generated outputs before creating its output directory. The
canonical JSON fingerprint covers the entire contract. Changing only ghost fields,
for example, can no longer leave the old mailbox-header-only layout hash unchanged.
Generated text is stable across JSON key order and LF/CRLF checkouts. Native build
identity still binds all native source inputs under the documented LF policy;
raw byte hashes remain provenance. Schema, generator and generated outputs are
included in the build input manifest, and canonical `native_layout.json` is emitted
beside the candidate ROM and UPS.

The immutable descriptor remains156 bytes at the same location in the extraction
build. Before writing a ROM, the build verifies every descriptor byte against the
selected schema and build ID, including null terminators and padding, and requires
the descriptor to lie within the injected ROM range. ABI2 and the current address
and payload behavior remain unchanged. The *meaning* of new `layout_sha256` values
is explicit in `layout_fingerprint_kind=canonical_complete_layout_json_v1`; old
manifests used the canonical `native_mailbox.h` hash.

## Selected-layout probe binding

Current resource/running probes load the generated table from their exact private
source directory and require its fingerprint to equal the selected descriptor's
embedded layout string before any native requests. They do not infer compatibility
from ABI2 or a familiar address. `native_gate` additionally requires manifests
declaring `layout_contract_schema=slink-rr-native-layout-v1` to select both files:

```text
--source-file lua/rr/native_layout.lua
--source-file patch/layout/rr_v2.json
```

Their raw and canonical hashes must match the selected build manifest under its
explicit EOL policy. The gate regenerates Lua from the selected JSON and verifies
the full ROM descriptor. Historical manifests without this schema are unchanged;
they do not silently acquire the new contract or its acceptance.
Manifests referencing new generated inputs cannot omit the schema to downgrade
themselves to that historical path. Both raw and canonical maps are checked for
the schema, generated Lua, generated C header and generator, with path aliases
normalized. Explicit null schema/fingerprint-kind metadata is rejected too.
The linker and old mailbox header alone are not new-era indicators because they
were already present in historical manifests.

Frozen01/02/03 ROMs and their already-copied source closures remain untouched.
The existing reviewed Viridian route artifact and fixtures are explicitly bound
to03. A **new current-source running run therefore needs a newly reviewed candidate
fixture and route/ROM binding**; substituting04 into03's fixture identity is forbidden.
Validation's natural-battle work intentionally uses its frozen03 copies of the
old resource/mailbox code. The current resource/running programs refuse an old or
foreign descriptor fingerprint rather than guessing an equivalent layout.

## Evidence and remaining extraction boundary

The permanent native test compares the entire32MiB diagnostic candidate against
the pinned03 SHA256 `3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301`.
It permits differences only in the64 ASCII bytes at descriptor offsets24 and89.
Null terminators, padding, hook instructions, code, ROM assets and all other bytes
must match exactly. Code remains12336 bytes; descriptor address remains`0837BF04`.
Compiler-negative tests independently swap equal-width fields, change signedness,
and change8×32 to4×64 while keeping total size; all must be rejected.

Unit tests cover malformed schemas, stale/missing generation, cross-language
offsets, raw/canonical hash drift, selected-source closure omissions, descriptor
byte drift and refusal of a foreign layout before probe requests. Native tests
cover the source manifest, complete layout binding, descriptor, linker, UPS
roundtrip, exact masked diff and the existing selected CPU instruction suites.
Source-to-UPS reproducibility uses `build.py --output-dir <owned-candidate> --check`;
the compared UPS is in that candidate directory, never the original workspace's
dist directory. These are structural/CPU checks, not live relocation acceptance.

Historical fixed-build research programs remain explicit exceptions requiring a
separate migration before any relocated validation: `arena_probe.lua`,
`callback_capability_probe.lua`, `controlled_load_probe.lua`, and the comparison
range in `tools/rr/arena.py`. The controlled-load experiment is deliberately pinned
to03's exact ROM, legacy layout hash and hook addresses. Older `lua/tests/` scripts
outside the RR release harness also contain historical hardcoded addresses. They
are not accepted as current/relocated evidence by this extraction. No relocation
may proceed while any selected runtime or evidence consumer lacks an explicitly
matched contract, and none of these checks establishes that the arena is free.

After functional native edits, set `SLINK_RR_LAYOUT_EQUIVALENCE_OUTPUT` to the
preserved `layout-contract-05-review` artifact for the historical extraction
comparison and `SLINK_RR_NATIVE_BASELINE` to frozen03. `SLINK_RR_NATIVE_OUTPUT`
selects the current functional candidate for all other artifact/CPU checks.
The equivalence test pins both historical ROM hashes and still compares every
byte after only the two original fingerprint masks; it never relabels changed
native code as an equivalent layout-only extraction.
