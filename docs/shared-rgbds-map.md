# Shared RGBDS map allocation parser

`tools.rgbds_map.parse_map(text: str) -> dict` reads RGBDS v1.0.3 map allocation
evidence. It has no cartridge, game, runtime, save-format, or mailbox constants.
The Gen 2 builder is one consumer; the tracked pureRGB maps exercise reuse.
Malformed or unsupported input raises `ValueError`; line syntax errors include
the source line number. The helper does not read files or execute tools.

## Result schema (version 1)

All addresses, banks, sizes, and byte totals are JSON integers. Address intervals
are half-open: `start <= address < end_exclusive`. The source map's printed end
address is inclusive and is converted exactly once.

```json
{
  "schema_version": 1,
  "format": "rgbds-map",
  "sections": [
    {"type": "ROM0", "bank": 0, "start": 0, "end_exclusive": 4,
     "size": 4, "name": "header"}
  ],
  "banks": [
    {"type": "ROM0", "bank": 0, "start": 0, "end_exclusive": 16384,
     "size": 16384, "used": 4, "free": 16380, "bounds_status": "KNOWN"}
  ],
  "gaps": [
    {"type": "ROM0", "bank": 0, "start": 4, "end_exclusive": 16384,
     "size": 16380, "status": "CANDIDATE"}
  ],
  "evidence": "LINKER_ALLOCATION",
  "ownership": "UNKNOWN",
  "writer_exclusion": "UNKNOWN",
  "persistence": "UNKNOWN"
}
```

The type order is ROM0, ROMX, VRAM, SRAM, WRAM0, WRAMX, OAM, HRAM, matching the
pinned emitter. Banks sort numerically. Sections sort by start, size, and decoded
name, so zero-sized sections precede occupied sections at the same address.
Gaps sort by address within each bank. Zero-sized sections are retained with
`size: 0` and equal endpoints; they occupy no bytes. Symbol names, labels, and
UNION/FRAGMENT piece markers do not add allocations and are not returned.

Only banks explicitly present in the input are reported. A missing bank or type
is unknown; it is never invented as free. Complete maps and complete bank-block
excerpts without a SUMMARY are supported. `SUMMARY:` alone is a valid empty
link result; blank or arbitrary text is refused. If SUMMARY is present, its
type set, usage, free totals, and bank counts must match the bank blocks.

A bare `EMPTY` bank without a SUMMARY can leave the ROM0 or WRAM0 linker mode
ambiguous. In that case `end_exclusive`, `size`, and `free` are `null`,
`bounds_status` is `UNKNOWN`, and no candidate gap is emitted for that bank.
The fixed start address and zero usage remain known. An unambiguous SUMMARY or
section/total evidence resolves the bounds. Absent command-line metadata is not
guessed. The parser does not claim that input text establishes its producer's
version; the caller must verify actual tools and artifact provenance separately.

## Grammar and validation

The supported grammar is scoped to the pinned RGBDS emitter below. Decimal bank
numbers and SUMMARY counts are distinct from hexadecimal section addresses and
sizes. Both singular `byte` and plural `bytes` are checked against their values.
Section-name escapes are `\n`, `\r`, `\t`, `\\`, and `\"`. Symbol rows and the exact
comments `; Next union` / `; Next fragment` are accepted within a section. Symbol
addresses are not used to infer allocation: aliases and end-of-section labels
are legitimate. `-M` output with no symbols is supported.

Nonzero sections must include an inclusive end and a matching positive size.
Zero-sized sections must omit the end. Reversed, size-inconsistent, overlapping
nonzero, out-of-address-space, invalid-bank, duplicate-bank, malformed, and
unterminated bank records are refused. Unknown lines are refused instead of
silently dropped. Bank excerpts still require the emitted EMPTY rows and either
`TOTAL EMPTY` or bare `EMPTY`. Union syntax never exempts overlapping allocations.

The parser validates explicit EMPTY rows by replaying the emitter's layout.
It calculates candidate gaps from the complement of nonzero section allocations
inside verified bank bounds, rather than copying printed EMPTY ranges. This
distinction matters because `writeMapBank` resets its previous-end cursor for
zero-sized sections: a zero-sized section inside an occupied section can cause
the next printed EMPTY to overlap allocated bytes. That source-derived edge case
has a regression test; it is not represented as a free allocation. No dedicated
upstream fixture for this interior-zero case was found.

Whole banks with zero allocated bytes end in bare `EMPTY`, possibly after
zero-sized sections and preceding EMPTY rows. Other banks end in `TOTAL EMPTY`.
The latter must satisfy `allocated size + total empty == supported bank size`.
The summary independently constrains the same totals when present. VRAM and OAM
have bank entries but are intentionally absent from RGBDS's SUMMARY.

## Platform bounds

| Type | Bank numbers | Start | Exclusive end |
| --- | --- | --- | --- |
| ROM0 | 0 | `$0000` | `$4000`, or `$8000` in expanded mode |
| ROMX | 1–65535 | `$4000` | `$8000` |
| VRAM | 0–1 | `$8000` | `$a000` |
| SRAM | 0–255 | `$a000` | `$c000` |
| WRAM0 | 0 | `$c000` | `$d000`, or `$e000` in expanded mode |
| WRAMX | 1–7 | `$d000` | `$e000` |
| OAM | 0 | `$fe00` | `$fea0` |
| HRAM | 0 | `$ff80` | `$ffff` |

These are toolchain/platform bounds, not promises of installed cartridge RAM or
hardware bank-switching capability. Expanded ROM0 cannot coexist with ROMX;
expanded WRAM0 cannot coexist with WRAMX in a supported map. A zero-size label
may sit exactly at its bank's exclusive endpoint.

## Evidence limits

`gaps` means only that no nonzero linked section in this map occupies those bytes.
Every gap is a **CANDIDATE**. A map does not prove writer exclusion, runtime
ownership, safe lifetime, save persistence, cartridge availability, overlays,
ROM fill-byte content, or whether code writes through aliases or bulk clears.
Those properties remain **UNKNOWN** and require their own source and physical
evidence. Neither a successful parse nor unit tests admit a runtime binding or
close an emulator/physical release gate. Map and source hashes belong to the
consumer's build provenance, not an inferred parser claim.

## Pinned source and regression evidence

RGBDS v1.0.3 resolves to `gbdev/rgbds@307846b03ea89ee57bf75f179d5f8051175ac60d`.

- [output.cpp:46](https://github.com/gbdev/rgbds/blob/307846b03ea89ee57bf75f179d5f8051175ac60d/src/link/output.cpp#L46): output type order.
- [output.cpp:378](https://github.com/gbdev/rgbds/blob/307846b03ea89ee57bf75f179d5f8051175ac60d/src/link/output.cpp#L378): EMPTY syntax and section-name escaping.
- [output.cpp:435](https://github.com/gbdev/rgbds/blob/307846b03ea89ee57bf75f179d5f8051175ac60d/src/link/output.cpp#L435): UNION/FRAGMENT symbol pieces and map bank emission through line 504.
- [output.cpp:508](https://github.com/gbdev/rgbds/blob/307846b03ea89ee57bf75f179d5f8051175ac60d/src/link/output.cpp#L508): SUMMARY arithmetic and VRAM/OAM omission through line 543.
- [linkdefs.cpp:12](https://github.com/gbdev/rgbds/blob/307846b03ea89ee57bf75f179d5f8051175ac60d/src/linkdefs.cpp#L12) and [main.cpp:423](https://github.com/gbdev/rgbds/blob/307846b03ea89ee57bf75f179d5f8051175ac60d/src/link/main.cpp#L423): platform bounds and mode adjustments.
- [section.cpp:139](https://github.com/gbdev/rgbds/blob/307846b03ea89ee57bf75f179d5f8051175ac60d/src/link/section.cpp#L139): aggregate UNION maximum and FRAGMENT sum; [section.cpp:207](https://github.com/gbdev/rgbds/blob/307846b03ea89ee57bf75f179d5f8051175ac60d/src/link/section.cpp#L207): expanded-mode conversions.
- [test/link/map-file/ref.out.map:9](https://github.com/gbdev/rgbds/blob/307846b03ea89ee57bf75f179d5f8051175ac60d/test/link/map-file/ref.out.map#L9): actual pinned zero-size, escaped-name, and one-past-end-symbol fixture, excerpted in the tests.
- [test/link/load-fragment/section-fragment/ref.out.map:5](https://github.com/gbdev/rgbds/blob/307846b03ea89ee57bf75f179d5f8051175ac60d/test/link/load-fragment/section-fragment/ref.out.map#L5): actual fragment-piece fixture.

The tests parse all six required tracked `data/purergb/*.map` files, with no
missing-file skips. Clean and SLink maps independently pin the changed WRAMX
gap next to `Stack`; the overlay occupies 14 of the clean map's 22 bytes. The
observed clean `pokered.map` SHA-256 at implementation was
`455f8f0269350397db53bbe80a884cc1df0ef3ece3eebdb43dea0bfc6775a1ca`.
That fixture hash identifies the observation; it is not a runtime admission pin.

Run `python -B -m pytest tests/unit/test_rgbds_map.py -q -p no:cacheprovider` from
the worktree. These tests are MODEL evidence for the parser, while their pinned
emitter and tracked map inputs provide bounded SOURCE evidence.
