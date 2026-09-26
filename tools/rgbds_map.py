"""Parse RGBDS v1.0.3 map allocation evidence; no cartridge/runtime semantics.

See docs/shared-rgbds-map.md for the schema, source pins, and evidence limits.
"""

import re
from dataclasses import dataclass, field

# rgbds@307846b03ea89ee57bf75f179d5f8051175ac60d, src/linkdefs.cpp:12-68
# and src/link/main.cpp:423-434. ROM0/WRAM0 have two supported linker modes.
_TYPES = {
    "ROM0": (0x0000, (0x4000, 0x8000), 0, 0),
    "ROMX": (0x4000, (0x4000,), 1, 65535),
    "VRAM": (0x8000, (0x2000,), 0, 1),
    "SRAM": (0xA000, (0x2000,), 0, 255),
    "WRAM0": (0xC000, (0x1000, 0x2000), 0, 0),
    "WRAMX": (0xD000, (0x1000,), 1, 7),
    "OAM": (0xFE00, (0xA0,), 0, 0),
    "HRAM": (0xFF80, (0x7F,), 0, 0),
}
_ORDER = {kind: index for index, kind in enumerate(_TYPES)}
_HEADER = re.compile(r"([A-Z0-9]+) bank #([0-9]+):")
_SUMMARY = re.compile(
    r"([A-Z0-9]+): ([0-9]+) byte(s?) used / ([0-9]+) free(?: in ([0-9]+) bank(s?))?"
)
_SECTION = re.compile(
    r'SECTION: \$([0-9a-fA-F]{4})(?:-\$([0-9a-fA-F]{4}))? '
    r'\(\$([0-9a-fA-F]{4}) byte(s?)\) \["((?:[^"\\]|\\[nrt"\\])*)"\]'
)
_EMPTY = re.compile(
    r"EMPTY: \$([0-9a-fA-F]{4})-\$([0-9a-fA-F]{4}) \(\$([0-9a-fA-F]{4}) byte(s?)\)"
)
_TOTAL = re.compile(r"TOTAL EMPTY: \$([0-9a-fA-F]{4}) byte(s?)")
_SYMBOL = re.compile(r"\$[0-9a-fA-F]{4} = \S+")
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


@dataclass
class _Bank:
    kind: str
    number: int
    sections: list[dict] = field(default_factory=list)
    layout: list[tuple[str, int, int]] = field(default_factory=list)
    total: int | None = None
    empty: bool = False

    @property
    def closed(self):
        return self.empty or self.total is not None


def _check_plural(value, suffix):
    if (suffix == "") != (value == 1):
        raise ValueError("incorrect singular/plural in map")


def _interval(start, last, size, suffix):
    start, size = int(start, 16), int(size, 16)
    end = start if last is None else int(last, 16) + 1
    if (last is None) != (size == 0) or end < start or end - start != size:
        raise ValueError("reversed or inconsistent interval")
    _check_plural(size, suffix)
    return start, end, size


def _range(kind, bank, start, end):
    return {"type": kind, "bank": bank, "start": start, "end_exclusive": end,
            "size": end - start}


def _read(text):
    banks, summaries = {}, {}
    current = None
    has_summary = False
    in_section = False
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            if line == "SUMMARY:":
                if has_summary or banks:
                    raise ValueError("misplaced SUMMARY")
                has_summary = True
                continue
            if match := _SUMMARY.fullmatch(line):
                kind, used, plural, free, count, bank_plural = match.groups()
                if not has_summary or banks or kind not in _TYPES or kind in {"VRAM", "OAM"}:
                    raise ValueError("unexpected summary row")
                if kind in summaries:
                    raise ValueError("duplicate summary type")
                used, free = int(used), int(free)
                _check_plural(used, plural)
                if count is not None:
                    _check_plural(int(count), bank_plural)
                summaries[kind] = (used, free, int(count) if count is not None else 1)
                continue
            if match := _HEADER.fullmatch(line):
                if current is not None and not current.closed:
                    raise ValueError("bank has no EMPTY/TOTAL EMPTY terminator")
                kind, number = match.groups()
                number = int(number)
                if kind not in _TYPES or not _TYPES[kind][2] <= number <= _TYPES[kind][3]:
                    raise ValueError("unknown type or invalid bank number")
                if (kind, number) in banks:
                    raise ValueError("duplicate bank")
                current = banks[kind, number] = _Bank(kind, number)
                in_section = False
                continue
            if current is None or current.closed:
                raise ValueError("content outside an open bank")
            if match := _SECTION.fullmatch(line):
                start, end, size = _interval(*match.groups()[:4])
                name = re.sub(r'\\([nrt"\\])', lambda m: _ESCAPES[m[1]], match[5])
                current.sections.append({**_range(current.kind, current.number, start, end),
                                         "name": name})
                current.layout.append(("SECTION", start, end))
                in_section = True
            elif match := _EMPTY.fullmatch(line):
                start, end, _ = _interval(*match.groups())
                current.layout.append(("EMPTY", start, end))
                in_section = False
            elif match := _TOTAL.fullmatch(line):
                current.total = int(match[1], 16)
                _check_plural(current.total, match[2])
            elif line == "EMPTY":
                current.empty = True
            elif in_section and (
                _SYMBOL.fullmatch(line) or line in {"; Next union", "; Next fragment"}
            ):
                # Labels/piece markers do not allocate bytes, and labels at the
                # section end or repeated UNION addresses are valid.
                continue
            else:
                raise ValueError("unsupported or malformed map line")
        except ValueError as error:
            raise ValueError(f"line {line_number}: {error}") from error
    if current is not None and not current.closed:
        raise ValueError("bank has no EMPTY/TOTAL EMPTY terminator")
    if not banks and not has_summary:
        raise ValueError("no RGBDS map content")
    if has_summary and set(summaries) != {kind for kind, _ in banks} - {"VRAM", "OAM"}:
        raise ValueError("SUMMARY types do not match bank entries")
    return banks, summaries


def _bank_result(bank, summary_size):
    kind, number = bank.kind, bank.number
    base, possible_sizes, _, _ = _TYPES[kind]
    used = sum(section["size"] for section in bank.sections)
    if bank.empty != (used == 0):
        raise ValueError(f"{kind} bank {number}: inconsistent EMPTY terminator")

    # Reject overlap before using total usage to select an address-space mode.
    occupied = sorted((s for s in bank.sections if s["size"]), key=lambda s: s["start"])
    cursor = base
    for section in occupied:
        if section["start"] < cursor:
            raise ValueError(f"{kind} bank {number}: overlapping or out-of-bounds allocation")
        cursor = section["end_exclusive"]

    sizes = set(possible_sizes)
    if bank.total is not None:
        sizes &= {used + bank.total}
    if summary_size is not None:
        sizes &= {summary_size}
    for section in bank.sections:
        sizes = {size for size in sizes
                 if base <= section["start"] <= section["end_exclusive"] <= base + size}
    if not sizes:
        raise ValueError(f"{kind} bank {number}: invalid bank bounds or total size")
    size = next(iter(sizes)) if len(sizes) == 1 else None
    end = None if size is None else base + size

    # Replay the pinned emitter, including zero-size sections resetting prevEnd.
    # Printed EMPTY rows are not directly trusted as free ranges (see docs).
    expected, previous_start, previous_end = [], base, base
    for section in bank.sections:
        start, stop = section["start"], section["end_exclusive"]
        if start < previous_start:
            raise ValueError(f"{kind} bank {number}: sections out of address order")
        if previous_end < start:
            expected.append(("EMPTY", previous_end, start))
        expected.append(("SECTION", start, stop))
        previous_start, previous_end = start, stop
    if used and previous_end < end:
        expected.append(("EMPTY", previous_end, end))
    if bank.layout != expected:
        raise ValueError(f"{kind} bank {number}: EMPTY layout contradicts section allocations")

    gaps = []
    if end is not None:
        cursor = base
        for section in occupied:
            if cursor < section["start"]:
                gaps.append(_range(kind, number, cursor, section["start"]))
            cursor = section["end_exclusive"]
        if cursor < end:
            gaps.append(_range(kind, number, cursor, end))
    for gap in gaps:
        gap["status"] = "CANDIDATE"
    result = {"type": kind, "bank": number, "start": base, "end_exclusive": end,
              "size": size, "used": used, "free": None if size is None else size - used,
              "bounds_status": "UNKNOWN" if size is None else "KNOWN"}
    return result, gaps


def parse_map(text: str) -> dict:
    """Return deterministic sections, banks, and free candidates; refuse via ValueError.

    Complete v1.0.3 maps and complete bank-block excerpts are supported. Missing
    banks are not inferred. See docs/shared-rgbds-map.md for nullable bounds.
    """
    banks, summaries = _read(text)
    sizes = {}
    for kind, (used, free, count) in summaries.items():
        selected = [bank for bank in banks.values() if bank.kind == kind]
        observed_used = sum(s["size"] for bank in selected for s in bank.sections)
        if count != len(selected) or used != observed_used or count == 0:
            raise ValueError(f"{kind}: SUMMARY usage or bank count mismatch")
        size, remainder = divmod(used + free, count)
        if remainder or size not in _TYPES[kind][1]:
            raise ValueError(f"{kind}: SUMMARY has invalid bank size")
        sizes[kind] = size

    result = {"schema_version": 1, "format": "rgbds-map", "sections": [], "banks": [],
              "gaps": [], "evidence": "LINKER_ALLOCATION", "ownership": "UNKNOWN",
              "writer_exclusion": "UNKNOWN", "persistence": "UNKNOWN"}
    for key in sorted(banks, key=lambda key: (_ORDER[key[0]], key[1])):
        bank = banks[key]
        entry, gaps = _bank_result(bank, sizes.get(bank.kind))
        result["banks"].append(entry)
        result["gaps"].extend(gaps)
        result["sections"].extend(sorted(
            bank.sections, key=lambda section: (section["start"], section["size"], section["name"])
        ))
    # Expanded modes merge the switchable address space into bank zero.
    for fixed, switched, expanded in (("ROM0", "ROMX", 0x8000), ("WRAM0", "WRAMX", 0x2000)):
        if any(b["type"] == fixed and b["size"] == expanded for b in result["banks"]) and any(
            b["type"] == switched for b in result["banks"]
        ):
            raise ValueError(f"expanded {fixed} mode cannot also contain {switched} banks")
    return result
