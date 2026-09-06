# RR precursor construction evidence

**The three catalog identities remain unresolved.** Actual RR construction
accepts explicitly supplied IDs1038,1214,1224 and preserves them. That does not
prove that campaign acquisition supplies those IDs, establish a lineage, or
justify calling them unobtainable. No catalog, generator or runtime selection
changes in this slice.

`tests/rr/native/test_precursor_creation_cpu.py` reuses the existing
`PrecursorsCPU` and pinned-ROM fixture. All evidence uses base ROM SHA-256
`679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f`.
Unicorn2.1.4 executes the actual ROM routines. No routine is stubbed, replaced,
given a fabricated result or skipped by changing the PC. The ROM is mapped
read/execute-only; all writes occur in synthetic CPU RAM. There is no game
emulator, cartridge-file write, party acquisition or PPU/frame simulation.

## Actual metadata differences

All six BaseStats records are nonzero. The tests compare their full28 bytes.

| Normal / unresolved record | Complete byte differences |
|---|---|
| Cubone104 / Cubone_A1038 | `+0x17: 4 → 31` |
| Koffing109 / Koffing_G1214 | `+0x17: 74 → 0`; `+0x1A: 202 → 1` |
| Mime Jr.492 / Mime_Jr_G1224 | None |

These offsets occupy declared ability slots in available CFRU's BaseStats
structure. Neither a matching record nor a difference in those bytes determines
the adopted cosmetic/shared versus regional/separate family policy.

## Verified creation path and candidate pools

The actual chain is:

```text
CreateMon0803DA54
  BL at0803DA96 → CreateBoxMon0803DAC4
  hook0803DAD2 → 09044B18
  BL at09044B2A → RR constructor09078512
  BL at09078530 → species selector09078218
  selected species written through setter at090785C0..090785C9
```

The hook bytes are `014800470000194b0409`. The26-byte hook body has SHA-256
`65836e7c3e0eab6d6d94ef99583ac38a262f5770e405868dc596fdae34357ba9`.
The774-byte constructor region has SHA-256
`a1753678bef888b9a772ac6f8fa16028dae89e02019369d501c1990182590d37`;
the744-byte selector region has SHA-256
`46fd5e4a5e0ed15f5db220728d94c0710bf0fd71205ad6c2143b2f5f4c59ada7`.

The selector's actual literals identify these pools. Their complete byte ranges,
counts, literal references and hashes are pinned by the tests.

| Pool address | Format / count | Normal104/109/492 | Unresolved1038/1214/1224 |
|---|---|---|---|
| `09163B98` | Count prefix,1032 | Once each | Absent |
| `091643AA` | Count prefix,979 | Once each | Absent |
| `09164B52` | Count prefix,927 | Once each | Absent |
| `09165292` | Count prefix,904 | Once each | Absent |
| `091659A4` | Count prefix,569 | Once each | Absent |
| `09165E18` | Count prefix,330 | Once each | Absent |
| `09163658` | `FEFE` terminator,42 | Absent | Absent |
| `091636EA` | `FEFE` terminator,339 | Once each | Absent |
| `09163994` | `FEFE` terminator,257 | Once each | Absent |

For every terminated pool, the actual membership routine at`090C1884` recognizes
its first member and rejects all three unresolved IDs. Its calls write nothing.
These facts cover the reviewed candidate domains, not all gifts, trades, scripts,
breeding or other acquisition paths.

With all flags clear, actual selector execution preserves each of the six input
IDs. Exact non-ROM reads are asserted; all writes remain in its48-byte stack
frame at`03007DD0..03007DFF`. Adjacent input canaries remain unchanged.

Available CFRU commit`b637a27898b14e25dd24d0f69a3e302f0069deb8` is source support,
not an exact RR numeric map: its Koffing_G/Mime_Jr_G constants are1218/1228. Its
purported randomizer export at`0801D87C` is ordinary battle code in the selected
RR ROM. The tests pin that discrepancy; they do not execute the mislabeled entry.

## Actual constructor experiment

The constructor was safe to exercise within a closed CPU contract. Its zeroing
and RNG paths are real ROM instructions, with no BIOS/HLE service substitute.
Each call uses:

- An80-byte destination at`02010000`, initialized to`CC`, with32-byte canaries;
- Synthetic SaveBlock1/2 at`02020000`/`02026000`, selected through the actual
  pointer slots`03005008`/`0300500C`;
- Clear mode/randomizer flags, map3/1, a synthetic one-letter OT name and gender0;
- Level5, fixed IV31, fixed PID1 and `OT_ID_RANDOM_NO_SHINY=2`;
- Initial RNG state0, with the real RNG making two calls and ending at`E97E7B6A`.

Map inputs are tied to the actual lookup: ROM map-group table`083526A8`, group3
table`083522F4`, map3/1 header`08350634`, and section byte89. The map helper reads
the synthetic SaveBlock1 location bytes rather than receiving a patched return.

All six constructors return within the200,000-instruction/two-second bounds,
using17,382–23,732 instructions. Required entry observations include the original
entry, RR hook, selector, zeroing, setter/getter, map lookup, RNG and initial-move
routine. Execution outside ROM or an access outside the explicit RAM contract
fails the attempt. Constructor writes are limited to the80-byte destination,
its bounded stack and RNG word`03005000`; save metadata, flags and canaries stay
unchanged.

Each normal/unresolved output pair differs **only** in the two species bytes at
`+0x20`. Full80-byte golden outputs are asserted. Header bytes`+0x1C..+0x1F`
remain zero; the native species accessor returns the exact supplied ID. This
proves that this path does not normalize the three records to their normal IDs.
It remains synthetic construction, not proof of player obtainability.

The accessor is not read-only: at`0803F908` and`0803F90E` it stores each payload
word twice. RR replaced the XOR instructions at`0803F906`/`0803F90C` with NOPs
but retained these stores. The test verifies all24 stores, their addresses,
values and instruction PCs, and requires the complete output to remain unchanged.
The initial stack-only accessor assumption failed; its result is retained in
`patch/build/precursor-creation-cpu-review.xml`. The corrected test uses this
exact observed ROM behavior, without changing the routine or the shared harness.

## Reproduction and remaining question

```powershell
$env:PYTHONPATH = (Resolve-Path patch/build/native-cpu-deps).Path
python -m pytest -p no:faulthandler tests/rr/native/test_precursor_creation_cpu.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/patch/build/rr_clean.gba' -q -o junit_family=xunit1 --junitxml=patch/build/precursor-creation-root-review-next.xml
python -m ruff check tests/rr/native/test_precursor_creation_cpu.py
```

Result: **22 passed**, Ruff clean. JUnit properties include classification, ROM
hash, constructor instruction counts, full constructed records and output hashes.
Use a new evidence filename for subsequent attempts; preserve previous results.

The next useful bound is an acquisition-caller audit: identify actual script
give-mon, gift/egg and NPC-trade tables/callers that can feed these species IDs
into this constructor, then prove either a reachable example or exclusion from
each explicitly supported source domain. A raw search for integer bytes, these
pool exclusions, or successful construction of caller-supplied IDs cannot settle
the whole acquisition domain or the biological lineage. Catalog generation
remains blocked as described in`REGIONAL_PRECURSOR_UNKNOWNS.md` and`RR_CATALOG.md`.
