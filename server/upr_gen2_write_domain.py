"""The write-domain audit for Manager-randomized Gold / Silver / Crystal -- the Gen 2 counterpart
of server/upr_gen3_write_domain.py (docs/gen2/RANDOMIZER.md).

Gen 2 randomizes the companion OVERLAY (the UPS is applied first, then UPR runs over it), so
the one thing that must never happen is UPR writing into the overlay. R0 measured that the pinned
fork never does, on any title, category or tweak; this module re-proves it on every output by
diffing the overlay input against UPR's output and intersecting the changed bytes with

    ups      the bytes the overlay changed (hunks decoded from patch/dist/SLink-<Title>.ups)
    slink    every ROM SECTION named "SLink ..." in data/gen2/<title>_slink.map
    header   the cartridge header 0x134-0x14F (UPR never writes it)

Any hit refuses the output. What UPR writes elsewhere (its tables, the free space BW EXP and
the Crystal tutor menu use) is not refused here: the rule tables are `_check_content_gen2`'s.
tools/upr_gen2_write_domain.py (R0's matrix runner) imports its geometry from here.
"""
from __future__ import annotations

import bisect
import functools
import hashlib
import json
import re
from pathlib import Path

from patch.tools.make_ups import _ups_decode

REPO = Path(__file__).resolve().parent.parent
# title -> (lock / provenance key, UPR settings rom name)
TITLES = {"crystal": ("pokecrystal", "Pokemon Crystal (U)"),
          "gold": ("pokegold", "Pokemon Gold (U)"),
          "silver": ("pokesilver", "Pokemon Silver (U)")}
HEADER = range(0x134, 0x150)   # cartridge header: UPR's own checksum fix-up would land here


# ── ROM geometry ─────────────────────────────────────────────────────────────────────────
def flat(bank: int, addr: int) -> int:
    return addr if bank == 0 else bank * 0x4000 + (addr - 0x4000)


def bank_addr(off: int) -> str:
    bank = off // 0x4000
    return f"{bank:02X}:{off if bank == 0 else 0x4000 + off % 0x4000:04X}"


def ups_spans(patch: bytes) -> list[tuple[int, int]]:
    """[start, end) runs of bytes the UPS changes (a hunk is a run of non-zero XOR bytes)."""
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
        # the terminating 0 XOR is an unchanged byte; a hunk running to EOF has none
        out.append((start, i - 1 if x == 0 else i))
    return out


def map_sections(map_path: Path) -> list[tuple[int, int, str]]:
    """[start, end) flat ROM ranges of every section in an rgblink .map (ROM0/ROMX only)."""
    out, bank = [], None
    for line in map_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if m := re.match(r"^(ROM0|ROMX) bank #(\d+):", line):
            bank = int(m.group(2))
        elif re.match(r"^\S", line):
            bank = None                                   # WRAM / SRAM / HRAM ...
        elif bank is not None and (m := re.search(r'SECTION: \$([0-9a-f]+)(?:-\$([0-9a-f]+))? .*\["(.*)"\]', line)):
            lo = int(m.group(1), 16)
            hi = int(m.group(2), 16) if m.group(2) else lo
            out.append((flat(bank, lo), flat(bank, hi) + 1, m.group(3)))
    return sorted(out)


def sym_labels(sym_path: Path) -> tuple[list[int], list[str]]:
    offs, names = [], []
    for line in sym_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^([0-9a-f]{2}):([0-9a-f]{4}) (\S+)", line)
        if m and (int(m.group(2), 16) < 0x8000):
            offs.append(flat(int(m.group(1), 16), int(m.group(2), 16)))
            names.append(m.group(3))
    order = sorted(range(len(offs)), key=offs.__getitem__)
    return [offs[i] for i in order], [names[i] for i in order]


def _merge(offsets, gap: int = 1) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for o in sorted(offsets):
        if out and o - out[-1][1] <= gap:
            out[-1][1] = o + 1
        else:
            out.append([o, o + 1])
    return [tuple(r) for r in out]


class Geometry:
    def __init__(self, title: str):
        key = TITLES[title][0]
        stem = {"pokecrystal": "crystal", "pokegold": "gold", "pokesilver": "silver"}[key]
        prov = json.loads((REPO / "data" / "gen2" / "overlay_provenance.json").read_text())["outputs"][key]
        self.prov = prov
        self.spans = ups_spans((REPO / prov["ups"]["file"]).read_bytes())
        self.ups_bytes = {i for a, b in self.spans for i in range(a, b)}
        self.sections = map_sections(REPO / "data" / "gen2" / f"{stem}_slink.map")
        self._starts = [s[0] for s in self.sections]
        self.slink = [s for s in self.sections if s[2].lower().startswith("slink")]
        self.slink_bytes = {i for a, b, _ in self.slink for i in range(a, b)}
        self.touched = sorted({s for s in self.sections if any(i in self.ups_bytes for i in range(s[0], s[1]))})
        self.touched_bytes = {i for a, b, _ in self.touched for i in range(a, b)}
        self.label_offs, self.label_names = sym_labels(REPO / "data" / "gen2" / f"{stem}_slink.sym")

    def section_of(self, off: int) -> str:
        k = bisect.bisect_right(self._starts, off) - 1
        if k >= 0 and self.sections[k][0] <= off < self.sections[k][1]:
            return self.sections[k][2]
        return "(unmapped)"

    def label_of(self, off: int) -> str:
        k = bisect.bisect_right(self.label_offs, off) - 1
        return f"{self.label_names[k]}+{off - self.label_offs[k]:#x}" if k >= 0 else "?"


@functools.cache
def geometry(title: str) -> Geometry:
    """One Geometry per title per process: the overlay, map and sym are pinned files."""
    return Geometry(title)


def regions(geo: Geometry, offsets) -> list[dict]:
    """Changed bytes merged into runs (gap <= 16) and attributed to their map section."""
    out = []
    for a, b in _merge(offsets, 16):
        out.append({"start": bank_addr(a), "end": bank_addr(b - 1), "flat": [a, b],
                    "section": geo.section_of(a), "label": geo.label_of(a),
                    "changed": sum(1 for o in offsets if a <= o < b) if len(offsets) < 200000 else None})
    return out


def audit(title: str, overlay: bytes, output: bytes, geo: Geometry | None = None) -> dict:
    geo = geo or geometry(title)
    if len(overlay) != len(output):
        raise ValueError(f"size changed {len(overlay)} -> {len(output)}")
    changed = [i for i, (x, y) in enumerate(zip(overlay, output, strict=True)) if x != y]
    ch = set(changed)
    return {
        "changed": len(changed),
        "header": [bank_addr(i) for i in changed if i in HEADER],
        "ups_hits": [bank_addr(i) for i in sorted(ch & geo.ups_bytes) if i not in HEADER],
        "slink_hits": [bank_addr(i) for i in sorted(ch & geo.slink_bytes)],
        "touched_section_hits": sorted({geo.section_of(i) for i in ch & geo.touched_bytes if i not in HEADER}),
        "regions": regions(geo, changed),
        "_changed": changed,
    }


def check_output(source_rom: str, output_rom: str, title: str) -> dict:
    """The pipeline's one call (Gen 2 branch of prepare_pair): refuse the output if UPR wrote a
    byte of the overlay, of an SLink section or of the header. ``source_rom`` must be the pinned
    overlay of ``title`` (the spans are only meaningful against those exact bytes)."""
    from server.upr_pipeline import UprPipelineError
    try:
        overlay, out = Path(source_rom).read_bytes(), Path(output_rom).read_bytes()
        geo = geometry(title)
        if hashlib.sha1(overlay).hexdigest() != geo.prov["sha1"]:
            raise ValueError(f"{source_rom} is not the pinned {title} companion overlay ({geo.prov['sha1']})")
        r = audit(title, overlay, out, geo)
    except (OSError, ValueError, KeyError) as exc:
        raise UprPipelineError(f"write-domain audit could not run: {exc}") from exc
    hits = [(what, r[key]) for what, key in (("companion overlay", "ups_hits"),
                                             ("SLink section", "slink_hits"), ("cartridge header", "header"))
            if r[key]]
    if hits:
        raise UprPipelineError(
            "the randomizer wrote into the " + "; ".join(f"{what} ({len(at)} byte(s), first {', '.join(at[:4])})"
                                                          for what, at in hits)
            + " -- the output is refused")
    return {"changed": r["changed"], "ups_bytes": len(geo.ups_bytes), "slink_bytes": len(geo.slink_bytes)}
