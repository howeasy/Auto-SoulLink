"""Pure, checked composition of fixed-size binary edits; no cartridge policy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PatchSpan:
    offset: int
    before: bytes
    after: bytes
    label: str


def apply_spans(source: bytes, spans, *, protected=(), bank_size=None):
    """Validate every preimage/ownership range before constructing a changed copy.

    Ranges use exclusive ends. Callers own source identity, symbol provenance,
    free-space reservations and semantic qualification. No resizing is allowed.
    """
    if not isinstance(source, bytes) or not source:
        raise ValueError("nonempty immutable source bytes required")
    if bank_size is not None and (type(bank_size) is not int or bank_size < 1):
        raise ValueError("positive bank geometry required")
    regions = tuple(protected)
    for region in regions:
        if (
            not isinstance(region, (tuple, list))
            or len(region) != 2
            or any(type(value) is not int for value in region)
            or not 0 <= region[0] < region[1] <= len(source)
        ):
            raise ValueError("invalid protected range")
    edits = list(spans)
    if not edits or len(edits) > 4096 or any(not isinstance(row, PatchSpan) for row in edits):
        raise ValueError("bounded typed patch spans required")
    for row in edits:
        if (
            type(row.offset) is not int
            or row.offset < 0
            or not isinstance(row.before, bytes)
            or not row.before
            or not isinstance(row.after, bytes)
            or len(row.before) != len(row.after)
            or not isinstance(row.label, str)
            or not row.label.strip()
        ):
            raise ValueError("invalid or resizing patch span")
    end = 0
    for row in sorted(edits, key=lambda item: item.offset):
        stop = row.offset + len(row.before)
        if row.offset < end or stop > len(source):
            raise ValueError("overlapping or out-of-range patch spans: " + row.label)
        if any(row.offset < hi and stop > lo for lo, hi in regions):
            raise ValueError("patch intersects protected range: " + row.label)
        if bank_size and row.offset // bank_size != (stop - 1) // bank_size:
            raise ValueError("patch crosses bank boundary: " + row.label)
        if source[row.offset : stop] != row.before:
            raise ValueError("patch preimage differs: " + row.label)
        end = stop
    output = bytearray(source)
    for row in edits:
        output[row.offset : row.offset + len(row.after)] = row.after
    return bytes(output)
