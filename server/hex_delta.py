"""Bounded, same-length byte deltas. No addresses, ownership or write authority."""

import re

from server.protocol_journal import JournalError


def _raw(value):
    if (
        not isinstance(value, str)
        or len(value) % 2
        or len(value) > 2 * 1024 * 1024
        or not re.fullmatch("[0-9A-F]+", value)
    ):
        raise JournalError("bounded canonical hex image required")
    return bytes.fromhex(value)


def between(before, after):
    old, new = _raw(before), _raw(after)
    if len(old) != len(new):
        raise JournalError("byte delta cannot resize an image")
    runs = []
    start = None
    for index in range(len(old) + 1):
        changed = index < len(old) and old[index] != new[index]
        if changed and start is None:
            start = index
        elif not changed and start is not None:
            runs.append(
                {
                    "offset": start,
                    "before": old[start:index].hex().upper(),
                    "after": new[start:index].hex().upper(),
                }
            )
            start = None
    return {"length": len(old), "runs": runs}


def apply(before, delta):
    raw = bytearray(_raw(before))
    end = 0
    if (
        not isinstance(delta, dict)
        or set(delta) != {"length", "runs"}
        or type(delta["length"]) is not int
        or delta["length"] != len(raw)
        or not isinstance(delta["runs"], list)
    ):
        raise JournalError("exact byte delta geometry required")
    for run in delta["runs"]:
        if not isinstance(run, dict) or set(run) != {"offset", "before", "after"}:
            raise JournalError("exact byte delta run required")
        offset = run["offset"]
        old, new = _raw(run["before"]), _raw(run["after"])
        if (
            type(offset) is not int
            or offset < end
            or len(old) != len(new)
            or offset + len(old) > len(raw)
            or raw[offset : offset + len(old)] != old
        ):
            raise JournalError("byte delta overlaps or differs from its preimage")
        raw[offset : offset + len(new)] = new
        end = offset + len(new)
    return raw.hex().upper()


def recover_before(current, delta):
    """Normalize only exact old/new bytes; callers verify the whole preimage hash."""
    raw = bytearray(_raw(current))
    if not isinstance(delta, dict) or not isinstance(delta.get("runs"), list):
        raise JournalError("exact recovery delta required")
    end = 0
    for run in delta["runs"]:
        if not isinstance(run, dict) or set(run) != {"offset", "before", "after"}:
            raise JournalError("exact recovery run required")
        old, new = _raw(run["before"]), _raw(run["after"])
        offset = run["offset"]
        if (
            type(offset) is not int
            or offset < end
            or offset + len(old) > len(raw)
            or len(old) != len(new)
        ):
            raise JournalError("invalid recovery run geometry")
        if any(
            value not in (a, b)
            for value, a, b in zip(raw[offset : offset + len(old)], old, new, strict=True)
        ):
            raise JournalError("partial image contains foreign bytes")
        raw[offset : offset + len(old)] = old
        end = offset + len(old)
    result = raw.hex().upper()
    apply(result, delta)  # Complete shape and length validation stays identical.
    return result
