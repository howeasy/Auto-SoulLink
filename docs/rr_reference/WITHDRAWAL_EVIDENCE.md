# Explicit RR withdrawal evidence binding

`lua/rr/withdrawal_evidence.lua` connects the independently tested reconstruction
oracle to an explicitly selected v2 storage readback participant. The legacy
client still selects v1. **Production selection, loader attestation, native
reservation recovery, and live storage release acceptance are not established by
this component.** Do not enable it by treating matching instruction anchors as
cartridge admission.

## Reproduced predicate failure

Against `fd23f85`, a modeled native withdrawal using the actual v1 `storage.lua`
returned `rr-storage-receipt-v1` after its destination was changed to attack999,
PP1 and poison status8. The represented58 bytes, positive stats, full HP and
count checks still matched. The native ARM routine was not executed in that
reproduction: this demonstrates the client accepting contradictory game-memory
evidence, independently of what caused that evidence.

The v2 participant derives and records the exact100-byte expected destination
before native submission. Full-party comparison now includes that expected
record; status, PP, mail, builder marker and cleared padding cannot escape the
readback check. Source removal, destination count and unaffected party records
retain the existing checks. No timeout or native status can replace the result.

## Local selection boundary

An admitted loader constructs the read-only evidence object, then passes it to:

```lua
local evidence, reason = require("rr.withdrawal_evidence").new(local_io, native_manifest)
local participant, problem = require("rr.storage").new_verified(M, MB, memory, context, evidence)
```

`new_verified` refuses missing/incomplete evidence. Its intents/receipts use v2;
it refuses legacy v1 intents and cannot silently downgrade their acceptance
predicate. This constructor strengthens physical readback. Its existing volatile
mailbox submission is not the completed durable/native coordinator: production
bootstrap must still bind trusted command IDs, persisted native preparations,
armed classification, receipt retention and reconciliation before selection.

The immutable native manifest must supply ABI2, the exact admitted RR base SHA256,
candidate ROM SHA1/SHA256, native build ID and layout hash. The caller must have
validated the local manifest against the actual file and immutable descriptor;
this module does not manufacture that attestation from a JSON document.

Every service in `local_io` is a trusted local host/loader dependency:

| Service | Required behavior |
|---|---|
| `read_region(address, length)` | Exact binary bytes from the selected local ROM; no network or repository fallback. |
| `read_u8(address)` | Current RR mode flags from the owned emulator. Errors/missing bytes refuse evidence. |
| `sha256(binary_string)` | SHA256 of the actual bytes, returned as lowercase hex. Do not UTF8-reencode binary data. |
| `getromhash()` | Current host-reported cartridge SHA1, compared with the locally admitted manifest. |
| `verified_binding()` | Current locally verified ROM/build/layout identity, binding digest and positive u32 context generation; nil when revoked. |

`verified_binding` returns `rom_sha1`, `rom_sha256`, `build_id`, `layout_sha256`,
`binding_digest` and `context_generation`. These are not fields to copy from a
server command. Reset/load or admission revocation must invalidate that service
before ordinary execution; constructing this object does not implement such an
interlock.

The constructor hashes15 complete selected code/data regions against the pinned
RR binary and copies the table bytes into private immutable strings. It checks
the local binding and loaded cartridge both before and after loading. These
region checks support the withdrawal formula; they are not a substitute for the
whole-ROM/native manifest check. Constructor IO must run under the loader's
verified hold if it yields. The cache assumes admitted ROM memory remains
immutable; out-of-band ROM writes invalidate this scope.

## Prepare and verify

`evidence.prepare(source58_hex)` samples actual Default/MGM/randomizer and
frontier flags, chooses the species growth row and four move PP entries from its
pinned tables, and derives the exact destination using the pure oracle. It
samples context again after derivation and hashing. Active frontier, unsupported
modes/randomizers, unreadable flags, invalid source/domain, or epoch changes
refuse preparation. Level0 and levels above100 are refused for campaign use;
the underlying oracle's accurate native0..250 behavior is preserved.

The plain-JSON proof records source and expected-party SHA256, expected100 bytes,
ROM/build/layout identity, binding digest/generation, and sampled mode/frontier
context. The storage intent also records the source58 bytes, expected party,
save fingerprint, borrowed-party epoch, source/destination and counts. No
mutable table bytes or cached server stats are accepted from a command body.

Verification re-derives from the **persisted pre-operation source** and private
pinned tables, comparing the complete proof and context. It never derives a new
expectation from the emptied source box or the post-operation party. Changing an
expected byte or digest in the serialized intent cannot turn a corrupt record
into success. A receipt copies its proof so subsequent mutation of the caller's
intent cannot alter that receipt. Its durability remains `live_ram_only`.

An epoch change requires reconciliation and a fresh binding. It cannot silently
retarget an old intent. This narrow component does not resolve that reconciliation,
prove current physical ownership of an orphaned BUSY mailbox, validate every
possible species/move's acquisition legality, or prove battery-save persistence.

## Verification

`tests/rr/runtime/test_withdrawal_evidence.py` loads the actual RR data and real
Lua oracle/context/storage with modeled host IO and explicit engine boundaries.
It uses an independent Python reconstruction as the native-output fixture.
Both MGM values, complete JSON evidence, corrupt status/PP/stat/mail/marker/padding,
changed ROM/epoch/build/mode/frontier, revoked binding, changed derivation regions,
legacy-intent refusal and modified proof fields are covered. These are component
tests, not emulator, process-restart, paired, or save-persistence evidence.

```powershell
python -m pytest tests/rr/runtime/test_withdrawal_evidence.py -q --rr-repo . --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba'
```

The previous2820 unstubbed CPU comparisons remain independent supporting evidence
for the pure reconstruction formula. S04 remains open pending complete native
participation, actual mGBA source/destination/readback in both MGM pairings, and
the full release inventory.
