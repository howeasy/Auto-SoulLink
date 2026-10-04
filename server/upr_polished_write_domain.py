"""The write-domain audit for Manager-randomized Polished Crystal -- the Polished counterpart of the
Gen 2 audit (server/upr_gen2_write_domain.py on claude/gen2-randomizer).

Polished randomizes the companion OVERLAY (patch/dist/SLink-Polished.ups applied first, then UPR
runs over it), so UPR must never write a byte the overlay owns. Every output is diffed against the
overlay input and the changed bytes are intersected with

    ups      the bytes the overlay changed (hunks decoded from the UPS: ROM0 $0070, the DelayFrame
             lead-in, bank $7E code, the header checksum)
    bank7e   the whole SLink service bank $7E (data/polished/overlay_provenance.json service_bank)
    header   the cartridge header 0x134-0x14F

Any hit refuses the output. What UPR writes elsewhere (its wild tables, the catch-rate bytes) is
`_check_content_polished`'s business, not this module's.
"""
from __future__ import annotations

import functools
import hashlib
import json
from pathlib import Path

from patch.tools.make_ups import _ups_decode

REPO = Path(__file__).resolve().parent.parent
HEADER = range(0x134, 0x150)
BANK_7E = range(0x7E * 0x4000, 0x7F * 0x4000)


def ups_spans(patch: bytes) -> list[tuple[int, int]]:
    """[start, end) runs of bytes the UPS changes (a hunk is a run of non-zero XOR bytes).
    ponytail: same decode as upr_gen2_write_domain.ups_spans, which is not on this branch yet;
    import it from there once claude/gen2-randomizer lands and delete this copy."""
    pos, out, i, end = 4, [], 0, len(patch) - 12
    _, pos = _ups_decode(patch, pos)
    _, pos = _ups_decode(patch, pos)
    while pos < end:
        rel, pos = _ups_decode(patch, pos)
        i += rel
        start, x = i, None
        while pos < end:
            x = patch[pos]
            pos += 1
            i += 1
            if x == 0:
                break
        out.append((start, i - 1 if x == 0 else i))     # the terminating 0 XOR is an unchanged byte
    return out


@functools.cache
def geometry() -> dict:
    """The pinned overlay's sha1 and the byte sets it owns (one pinned UPS, read once)."""
    prov = json.loads((REPO / "data" / "polished" / "overlay_provenance.json").read_text(encoding="utf-8"))["output"]
    ups = frozenset(i for a, b in ups_spans((REPO / prov["ups"]["file"]).read_bytes()) for i in range(a, b))
    return {"sha1": prov["sha1"], "ups": ups}


def audit(overlay: bytes, output: bytes) -> dict:
    if len(overlay) != len(output):
        raise ValueError(f"size changed {len(overlay)} -> {len(output)}")
    ups = geometry()["ups"]
    changed = [i for i, (x, y) in enumerate(zip(overlay, output, strict=True)) if x != y]
    return {"changed": len(changed),
            "header": [i for i in changed if i in HEADER],
            "ups_hits": [i for i in changed if i in ups and i not in HEADER],
            "bank7e_hits": [i for i in changed if i in BANK_7E]}


def check_output(source_rom: str, output_rom: str) -> dict:
    """prepare_pair's one call: refuse the output if UPR wrote a byte of the overlay, of bank $7E or
    of the header. ``source_rom`` must be the pinned overlay (the spans mean nothing elsewhere)."""
    from server.upr_pipeline import UprPipelineError
    try:
        overlay, out = Path(source_rom).read_bytes(), Path(output_rom).read_bytes()
        geo = geometry()
        if hashlib.sha1(overlay).hexdigest() != geo["sha1"]:
            raise ValueError(f"{source_rom} is not the pinned Polished Crystal companion overlay ({geo['sha1']})")
        r = audit(overlay, out)
    except (OSError, ValueError, KeyError) as exc:
        raise UprPipelineError(f"write-domain audit could not run: {exc}") from exc
    hits = [(what, r[key]) for what, key in (("companion overlay", "ups_hits"), ("SLink bank $7E", "bank7e_hits"),
                                             ("cartridge header", "header")) if r[key]]
    if hits:
        raise UprPipelineError(
            "the randomizer wrote into the " + "; ".join(
                f"{what} ({len(at)} byte(s), first {', '.join(f'0x{i:06X}' for i in at[:4])})" for what, at in hits)
            + " -- the output is refused")
    return {"changed": r["changed"], "ups_bytes": len(geo["ups"])}
