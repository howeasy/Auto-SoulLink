"""Gen 2 SLink mailbox writer-exclusion census (O-27 / card P4.1b; scope widened per the
OMP P4.1a/P4.1b independent review, docs/gen2/reviews/OMP_P41AB_REVIEW_2026-09-23.md F1-F4).

Proves, per title, from the pinned pokecrystal/pokegold decomps (data/gen2_sources.lock.json)
and their built .map/.sym, that nothing in the source writes the SLink mailbox span:

    W1  the span is EMPTY in the linker .map (no symbol/section overlaps it)
    W2  no hard-coded literal address, or symbol+/-offset arithmetic, resolves into the span
        anywhere in the tracked asm/inc source
    W3  every region-wide (STARTOF/SIZEOF/ENDOF-anchored) WRAM fill either misses the span or
        is the one accepted lifecycle event (Init's full WRAM0 clear)
    W4  every symbol-anchored bulk write is proven clear of the span: `ld hl,<sym>` / `ld de,<sym>`
        into ByteFill, CopyBytes, CopyData, ClearBytes, FarCopyBytes, FarCopyWRAM,
        FarCopyBytesDouble_DoubleBankSwitch, SwapBytes (both hl and de), InitString/InitName, and
        CopyDataUntil's until-address form; the exact inline ByteFill idiom (a label, then the
        fill/advance/decrement/branch loop, used by Init); and every OTHER standalone
        `ld [hli], a` store not already covered by that idiom, whose enclosing loop's length is
        never assumed. The write's length is resolved exactly when the source expresses it as a
        symbol difference, a region constant, a literal, or (CopyDataUntil) an address difference;
        otherwise, since these are already-shipped, byte-matched decomp titles (not
        arbitrary/adversarial code), the write is bounded by its own declared allocation, exclusive
        of any further sibling field beyond the next declared WRAM0 symbol: the gap to that symbol
        after its destination. A write whose destination resolves into WRAM0 but whose length
        can't be resolved by either method (e.g. loaded from a register, a bare `ld [hli], a` of
        unknown trip count, or split byte-by-byte) is reported UNPROVEN, never silently passed.
        A destination this census cannot resolve to a compile-time address at all (a computed
        pointer) is out of its scope by construction, counted per callee in the report's
        `out_of_scope_by_callee`, and left to PLAN_2026-09-23.md's W6 live write-watch, never
        silently treated as proven safe.
    W5  the span's immediate lower map-neighbour symbols are single-byte stores only: they never
        appear as a W4 bulk-write destination, and are never the target of a 16-bit `ld [sym], sp`.

W4's "declared allocation" reasoning is a SOURCE-level argument specific to decompiled, byte-exact
titles; it is not a general claim that arbitrary code cannot overrun a buffer, and the bound it
uses is exclusive of any sibling field beyond the immediate next declared symbol (a write that
deliberately continues past that symbol into further declared fields is bounded only up to the
first one). The residual risk of a computed-pointer overrun, or of such a multi-field continuation,
untouched by any of W1-W5, is the same one the plan already names, and PLAN_2026-09-23.md's W6 (a
live write-watch) is its tripwire, not a proof.

See docs/gen2/reviews/P4_PLAN_2026-09-23.md section 1.4 and docs/gen2/REVIEW_RECORD.md O-27.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

if __package__:
    from .gen2_source_data import ARTIFACTS, ROOT, load_context
    from .rgbds_map import parse_map
    from .rgbds_symbols import Symbol
else:
    from gen2_source_data import ARTIFACTS, ROOT, load_context
    from rgbds_map import parse_map
    from rgbds_symbols import Symbol

# Owner ruling O-27 / plan section 1.2: end address is exclusive.
MAILBOX_SPANS = {
    "crystal": (0xCFD8, 0xD000),
    "gold": (0xC1D9, 0xC200),
    "silver": (0xC1D9, 0xC200),
}
_SOURCE_EXTS = (".asm", ".inc")
_CONTROL_FLOW = re.compile(r"^(call|jp|jr|ret|reti|rst)\b")
_LABEL = re.compile(r"^[.\w]+:{1,2}$")
_OPERAND_REGISTERS = ("hl", "de", "bc", "c")
_LD_REG16 = {reg: re.compile(rf"^ld\s+{reg}\s*,\s*(.+)$") for reg in _OPERAND_REGISTERS}

# Register conventions for every WRAM-writing helper this census tracks (home/copy.asm,
# home/gfx.asm, home/string.asm, engine/gfx/color.asm), each confirmed by reading the body:
# which register(s) receive a write destination, which register holds the byte count, and any
# multiplier applied to that count (FarCopyBytesDouble_DoubleBankSwitch doubles each byte).
_CALLEE_SPECS = {
    "ByteFill": {"dest": ("hl",), "length_reg": "bc"},
    "CopyBytes": {"dest": ("de",), "length_reg": "bc"},
    "CopyData": {"dest": ("de",), "length_reg": "bc"},
    "ClearBytes": {"dest": ("de",), "length_reg": "bc"},
    "FarCopyBytes": {"dest": ("de",), "length_reg": "bc"},
    "FarCopyWRAM": {"dest": ("de",), "length_reg": "bc"},
    "FarCopyBytesDouble_DoubleBankSwitch": {"dest": ("de",), "length_reg": "bc", "length_multiplier": 2},
    "SwapBytes": {"dest": ("hl", "de"), "length_reg": "bc"},  # writes both operands, home/copy.asm:17
    "InitString": {"dest": ("hl",), "length_reg": "c"},
    "InitName": {"dest": ("hl",), "length_reg": "c"},
}
# CopyDataUntil (home/print_text.asm:83) copies [hl..bc) to de: `bc` is a terminal SOURCE
# address, not a byte count, so its length is an address difference, not a register value.
_UNTIL_CALLEES = {"CopyDataUntil": {"dest": "de", "src": "hl", "length_reg": "bc"}}
_ALL_CALLEES = {**_CALLEE_SPECS, **_UNTIL_CALLEES}
_CALLEE_PATTERN = re.compile(r"\bcall\s+(" + "|".join(re.escape(name) for name in _ALL_CALLEES) + r")\b")
_GENERIC_HLI_STORE = re.compile(r"^ld \[hli\], .+$")
_INT = re.compile(r"^\$([0-9a-fA-F]+)$|^%([01]+)$|^(\d+)$")
_HEX_LITERAL = re.compile(r"\$([0-9a-fA-F]{4})\b")
_SYM_ARITH = re.compile(r"\b([A-Za-z_][\w.]*)\s*([+-])\s*(\$[0-9a-fA-F]+|\d+)\b")
_STARTOF = re.compile(r"^(STARTOF|ENDOF)\(([A-Z0-9]+)\)$")
_SIZEOF = re.compile(r"^SIZEOF\(([A-Z0-9]+)\)$")
_SIZEOF_SUM = re.compile(r"^SIZEOF\(([A-Z0-9]+)\)\s*\+\s*SIZEOF\(([A-Z0-9]+)\)$")
_SYM_DIFF = re.compile(r"^([A-Za-z_][\w.]*)\s*-\s*([A-Za-z_][\w.]*)(?:\s*\+\s*(\d+))?$")
# The exact inline ByteFill-style loop used by both titles' Init (home/init.asm), matched as one
# unit: a label, then the 6-instruction fill/advance/decrement/branch idiom that jumps back to it.
_INLINE_FILL = re.compile(
    r"^(?P<label>[.\w]+):[ \t]*\n"
    r"[ \t]*ld \[hl\], .+\n"
    r"[ \t]*inc hl\n"
    r"[ \t]*dec bc\n"
    r"[ \t]*ld a, b\n"
    r"[ \t]*or c\n"
    r"[ \t]*jr nz, (?P=label)[ \t]*$",
    re.MULTILINE,
)


def _int_literal(token):
    match = _INT.fullmatch(token.strip())
    if not match:
        return None
    hexs, bins, decs = match.groups()
    return int(hexs, 16) if hexs is not None else int(bins, 2) if bins is not None else int(decs)


def region_bounds(map_result: dict) -> dict[str, tuple[int, int]]:
    """{'WRAM0': (start, size), ...} for regions with a single known size, from a parsed .map."""
    bounds: dict[str, tuple[int, int]] = {}
    ambiguous = set()
    for bank in map_result["banks"]:
        if bank["size"] is None:
            continue
        value = (bank["start"], bank["size"])
        if bank["type"] in bounds and bounds[bank["type"]] != value:
            ambiguous.add(bank["type"])
        bounds[bank["type"]] = value
    return {kind: value for kind, value in bounds.items() if kind not in ambiguous}


def _resolve_address(expr: str, symbols: dict[str, Symbol], bounds: dict[str, tuple[int, int]]):
    expr = expr.strip()
    literal = _int_literal(expr)
    if literal is not None:
        return literal
    if match := _STARTOF.fullmatch(expr):
        region = bounds.get(match[2])
        if region is None:
            return None
        return region[0] if match[1] == "STARTOF" else region[0] + region[1]
    if match := re.fullmatch(r"([A-Za-z_][\w.]*)\s*([+-])\s*(\$[0-9a-fA-F]+|\d+)", expr):
        symbol = symbols.get(match[1])
        offset = _int_literal(match[3])
        if symbol is None or offset is None:
            return None
        return symbol.address + offset if match[2] == "+" else symbol.address - offset
    symbol = symbols.get(expr)
    return symbol.address if symbol is not None else None


def _resolve_length(expr: str, symbols: dict[str, Symbol], bounds: dict[str, tuple[int, int]]):
    expr = expr.strip()
    literal = _int_literal(expr)
    if literal is not None:
        return literal, "EXACT_LITERAL"
    if match := _SIZEOF_SUM.fullmatch(expr):
        a, b = bounds.get(match[1]), bounds.get(match[2])
        return (a[1] + b[1], "EXACT_REGION") if a and b else (None, None)
    if match := _SIZEOF.fullmatch(expr):
        region = bounds.get(match[1])
        return (region[1], "EXACT_REGION") if region else (None, None)
    if match := _SYM_DIFF.fullmatch(expr):
        left = _resolve_address(match[1], symbols, bounds)
        right = _resolve_address(match[2], symbols, bounds)
        if left is None or right is None:
            return None, None
        return left - right + (int(match[3]) if match[3] else 0), "EXACT_SYMBOL_DIFF"
    return None, None


def _strip_comment(line: str) -> str:
    return line.split(";", 1)[0].rstrip()


def _scan_operands(lines: list[str], call_index: int) -> dict[str, str | None]:
    """Walk backward from a bulk-write call/loop for its most recent register loads."""
    found: dict[str, str | None] = dict.fromkeys(_OPERAND_REGISTERS)
    steps = 0
    index = call_index - 1
    while index >= 0 and steps < 8:
        stripped = lines[index].strip()
        if stripped:
            if _LABEL.match(stripped) or _CONTROL_FLOW.match(stripped):
                break
            for register, pattern in _LD_REG16.items():
                if found[register] is None and (match := pattern.match(stripped)):
                    found[register] = match[1].strip()
            steps += 1
        index -= 1
    return found


def _bulk_write_sites(text: str):
    """Yield one dict per destination write site: {line, callee, dest_expr, length_expr,
    length_multiplier, src_expr}. Covers the whole WRAM-writing helper family
    (`_CALLEE_SPECS`/`_UNTIL_CALLEES`), the exact inline Init ByteFill idiom, and every other
    standalone `ld [hli], a` store (whose enclosing loop's trip count is never assumed)."""
    clean = [_strip_comment(line) for line in text.splitlines()]
    idiom_store_lines = set()

    for match in _INLINE_FILL.finditer(text):
        label_line = text.count("\n", 0, match.start()) + 1
        idiom_store_lines.add(label_line + 1)  # the idiom's own `ld [hl], V` line
        operands = _scan_operands(clean, label_line - 1)
        yield {"line": label_line, "callee": "InlineFill", "dest_expr": operands["hl"],
               "length_expr": operands["bc"], "length_multiplier": 1}

    for index, line in enumerate(clean):
        if not (match := _CALLEE_PATTERN.search(line)):
            continue
        callee = match[1]
        operands = _scan_operands(clean, index)
        if callee in _UNTIL_CALLEES:
            spec = _UNTIL_CALLEES[callee]
            yield {"line": index + 1, "callee": callee, "dest_expr": operands[spec["dest"]],
                   "length_expr": operands[spec["length_reg"]], "src_expr": operands[spec["src"]],
                   "length_multiplier": 1}
            continue
        spec = _CALLEE_SPECS[callee]
        length_expr = operands[spec["length_reg"]]
        for dest_reg in spec["dest"]:
            yield {"line": index + 1, "callee": callee, "dest_expr": operands[dest_reg],
                   "length_expr": length_expr, "length_multiplier": spec.get("length_multiplier", 1)}

    for index, line in enumerate(clean):
        if index + 1 in idiom_store_lines or not _GENERIC_HLI_STORE.match(line.strip()):
            continue
        operands = _scan_operands(clean, index)
        # A bare store-and-increment: its enclosing loop's trip count is not this census's to
        # infer, so no length operand is offered here even if a `ld bc,`/`ld a,` happens to sit
        # nearby for an unrelated reason - `_classify` falls back to the structural bound.
        yield {"line": index + 1, "callee": "InlineHliStore", "dest_expr": operands["hl"],
               "length_expr": None, "length_multiplier": 1}


def _next_wram0_symbol_gap(dest: int, symbols: dict[str, Symbol], wram0: tuple[int, int]) -> int:
    """Bytes from `dest` to the next-higher WRAM0 symbol (or the end of the bank)."""
    higher = [s.address for s in symbols.values() if s.bank == 0 and dest < s.address <= wram0[1]]
    return (min(higher) if higher else wram0[1]) - dest


# Plan section 1.2/1.4: the only routine allowed to clear the whole of WRAM0 (which
# necessarily clears the span too) is the power-on/soft-reset lifecycle event.
_ACCEPTED_LIFECYCLE_CLEAR_FILES = {"home/init.asm"}


def _resolve_write_length(site, symbols, bounds):
    """The write's byte count: exact where the source expresses it that way, else None."""
    callee = site["callee"]
    if callee in _UNTIL_CALLEES:
        src_expr, until_expr = site.get("src_expr"), site.get("length_expr")
        if src_expr is None or until_expr is None:
            return None, None
        src = _resolve_address(src_expr, symbols, bounds)
        until = _resolve_address(until_expr, symbols, bounds)
        if src is None or until is None or until < src:
            return None, None
        return until - src, "EXACT_UNTIL_ADDRESS_DIFF"
    length_expr = site.get("length_expr")
    if length_expr is None:
        return None, None
    length, method = _resolve_length(length_expr, symbols, bounds)
    if length is None:
        return None, None
    return length * site.get("length_multiplier", 1), method


def _classify(path, site, symbols, bounds, wram0, span):
    callee, dest_expr = site["callee"], site["dest_expr"]
    if dest_expr is None:
        return {"callee": callee, "verdict": "OUT_OF_SCOPE",
                "reason": "no destination operand found near this call/store"}
    dest = _resolve_address(dest_expr, symbols, bounds)
    if dest is None:
        return {"callee": callee, "verdict": "OUT_OF_SCOPE", "dest_expr": dest_expr,
                "reason": "destination is a computed pointer, not a compile-time address (W6's concern)"}
    wram0_start, wram0_end = wram0
    if not wram0_start <= dest < wram0_end:
        return {"callee": callee, "verdict": "OUT_OF_SCOPE", "dest_expr": dest_expr,
                "reason": "destination resolves outside WRAM0"}
    record = {"line": site["line"], "callee": callee, "dest_expr": dest_expr, "dest": dest,
              "length_expr": site.get("length_expr"),
              "region_anchored": bool(_STARTOF.fullmatch(dest_expr.strip()))}
    length, method = _resolve_write_length(site, symbols, bounds)
    if length is None:
        # No length is resolvable via .sym/region/literal/address-difference (e.g. a named EQU
        # constant, bc set outside the scan window, or a bare `ld [hli], a` of unknown trip
        # count). This is a decompiled, byte-matched title, not arbitrary code: bound the write
        # by its own declared allocation, i.e. the gap to the next WRAM0 symbol after its
        # destination (exclusive of any further sibling field past that symbol). This is an
        # upper bound, never an exact value, so an overlap found this way is reported UNPROVEN
        # below rather than VIOLATION.
        length = _next_wram0_symbol_gap(dest, symbols, wram0)
        method = "STRUCTURAL_NEXT_SYMBOL_BOUND"
    record["length"], record["length_method"] = length, method
    end = dest + length
    overlaps = not (end <= span[0] or dest >= span[1])
    if not overlaps:
        record["verdict"] = "SAFE"
        return record
    full_wram0_clear = (record["region_anchored"] and dest == wram0_start
                         and length >= wram0_end - wram0_start
                         and path in _ACCEPTED_LIFECYCLE_CLEAR_FILES)
    if full_wram0_clear:
        record["verdict"] = "ACCEPTED_LIFECYCLE_CLEAR"
        return record
    if method == "STRUCTURAL_NEXT_SYMBOL_BOUND":
        # An upper bound reaches the span, but the write's true length is unresolved: this is
        # the "counted write with a runtime-variable length that could reach the span" case.
        record["verdict"] = "UNPROVEN"
        record["reason"] = "only an upper-bound length is available, and it reaches the span"
        return record
    record["verdict"] = "VIOLATION"
    return record


def literal_hits(path: str, text: str, span: int, symbols: dict[str, Symbol]):
    """W2: hex literals and symbol+/-offset arithmetic that resolve into the span."""
    hits = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw)
        for match in _HEX_LITERAL.finditer(line):
            value = int(match[1], 16)
            if span[0] <= value < span[1]:
                hits.append({"file": path, "line": number, "kind": "LITERAL", "value": hex(value),
                             "text": line.strip()})
        for match in _SYM_ARITH.finditer(line):
            symbol = symbols.get(match[1])
            if symbol is None:
                continue
            offset = _int_literal(match[3])
            if offset is None:
                continue
            value = symbol.address + offset if match[2] == "+" else symbol.address - offset
            if span[0] <= value < span[1]:
                hits.append({"file": path, "line": number, "kind": "SYMBOL_ARITHMETIC",
                             "value": hex(value), "text": line.strip()})
    return hits


def neighbours(symbols: dict[str, Symbol], wram0: tuple[int, int], span_start: int) -> list[str]:
    """W5: the names sharing the highest WRAM0 address strictly below the span."""
    below = [s.address for s in symbols.values() if s.bank == 0 and wram0[0] <= s.address < span_start]
    if not below:
        return []
    boundary = max(below)
    return sorted(name for name, sym in symbols.items() if sym.bank == 0 and sym.address == boundary)


def sixteen_bit_store_hits(path: str, text: str, names: set[str]):
    if not names:
        return []
    pattern = re.compile(r"\bld\s+\[(" + "|".join(re.escape(n) for n in names) + r")\]\s*,\s*sp\b")
    return [{"file": path, "line": number, "symbol": match[1]}
            for number, raw in enumerate(text.splitlines(), 1)
            for match in [pattern.search(_strip_comment(raw))] if match]


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "--no-replace-objects", "-C", str(root), *args],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(f"git {' '.join(args)} failed in {root}: {result.stderr.strip()}")
    return result.stdout


def read_sources(root: Path) -> dict[str, str]:
    """All tracked .asm/.inc text, from a pinned git checkout or a plain (e.g. temp) directory.

    A git checkout is read via `cat-file --batch` at HEAD, tamper-evident and independent of
    what happens to be sitting in the working tree. A plain directory (the control's patched
    copy) is read straight off disk: it carries no git history to authenticate against.
    """
    if (root / ".git").exists():
        if _git(root, "status", "--porcelain", "--untracked-files=all").strip():
            raise ValueError(f"source tree is dirty: {root}")
        commit = _git(root, "rev-parse", "HEAD").strip()
        paths = [line for line in _git(root, "ls-tree", "-r", "--name-only", commit).splitlines()
                 if line.lower().endswith(_SOURCE_EXTS)]
        if not paths:
            raise ValueError(f"no tracked asm/inc source under {root}")
        batch_input = "".join(f"{commit}:{path}\n" for path in paths).encode("utf-8")
        result = subprocess.run(["git", "--no-replace-objects", "-C", str(root), "cat-file",
                                 "--batch"], input=batch_input, capture_output=True, check=False)
        if result.returncode:
            raise ValueError(f"git cat-file --batch failed: {result.stderr.decode(errors='replace')}")
        data, offset, texts = result.stdout, 0, {}
        for path in paths:
            header_end = data.index(b"\n", offset)
            _, _, size = data[offset:header_end].split(b" ")
            start = header_end + 1
            texts[path] = data[start:start + int(size)].decode("utf-8", errors="replace")
            offset = start + int(size) + 1
        return texts
    paths = sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*")
                   if p.is_file() and p.suffix.lower() in _SOURCE_EXTS)
    if not paths:
        raise ValueError(f"no tracked asm/inc source under {root}")
    return {path: (root / path).read_text("utf-8", errors="replace") for path in paths}


def census(title: str, span: tuple[int, int], symbols: dict[str, Symbol],
           map_result: dict, sources: dict[str, str]) -> dict:
    """Pure census over an already-loaded symbol table, parsed .map, and source corpus."""
    bounds = region_bounds(map_result)
    if "WRAM0" not in bounds:
        raise ValueError(f"{title}: WRAM0 bank size not resolvable from the .map")
    wram0 = bounds["WRAM0"][0], bounds["WRAM0"][0] + bounds["WRAM0"][1]
    if not wram0[0] <= span[0] < span[1] <= wram0[1]:
        raise ValueError(f"{title}: mailbox span is not inside WRAM0 ({hex(wram0[0])}-{hex(wram0[1])})")

    w1_gap = any(gap["type"] == "WRAM0" and gap["start"] <= span[0] and span[1] <= gap["end_exclusive"]
                 for gap in map_result["gaps"])

    w2_hits = [hit for path, text in sources.items() for hit in literal_hits(path, text, span, symbols)]

    region_writers, symbol_writers = [], []
    out_of_scope_by_callee: dict[str, int] = {}
    for path, text in sources.items():
        for site in _bulk_write_sites(text):
            record = _classify(path, site, symbols, bounds, wram0, span)
            if record["verdict"] == "OUT_OF_SCOPE":
                out_of_scope_by_callee[record["callee"]] = out_of_scope_by_callee.get(record["callee"], 0) + 1
                continue
            record["file"] = path
            (region_writers if record["region_anchored"] else symbol_writers).append(record)

    boundary_names = set(neighbours(symbols, wram0, span[0]))
    w5_bulk_hits = [w for w in symbol_writers if w["dest_expr"].strip() in boundary_names]
    w5_wide_stores = [hit for path, text in sources.items()
                      for hit in sixteen_bit_store_hits(path, text, boundary_names)]

    unproven = [w for w in region_writers + symbol_writers if w["verdict"] == "UNPROVEN"]
    violations = [w for w in region_writers + symbol_writers if w["verdict"] == "VIOLATION"]
    w5_ok = not w5_bulk_hits and not w5_wide_stores
    proven = w1_gap and not w2_hits and not unproven and not violations and w5_ok

    return {
        "title": title, "span": {"start": hex(span[0]), "end_exclusive": hex(span[1])},
        "w1_span_empty_in_map": w1_gap,
        "w2_literal_or_arithmetic_hits": w2_hits,
        "w3_region_writers": region_writers,
        "w4_symbol_writers": symbol_writers,
        "out_of_scope_by_callee": dict(sorted(out_of_scope_by_callee.items())),
        "w5_neighbours": sorted(boundary_names),
        "w5_neighbour_bulk_hits": w5_bulk_hits,
        "w5_neighbour_wide_store_hits": w5_wide_stores,
        "unproven_writers": unproven,
        "violations": violations,
        "verdict": "PROVEN" if proven else "UNPROVEN",
    }


def run_title(root: Path, title: str) -> dict:
    context = load_context(title, root=root)
    map_text = (root / f"data/gen2/{context.artifact}.map").read_text("utf-8")
    sources = read_sources(context.source_dir)
    result = census(title, MAILBOX_SPANS[title], context.symbols, parse_map(map_text), sources)
    result["source"] = context.source_record()
    return result


REPORT_PATH = Path("data/gen2/mailbox_census.json")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="verify the committed report is current")
    parser.add_argument("--write", action="store_true", help="(re)write the committed report")
    args = parser.parse_args(argv)
    try:
        results = {title: run_title(args.root, title) for title in ARTIFACTS}
        report = {"schema": "gen2-mailbox-census-v1", "generator": "tools/gen2_mailbox_census.py",
                  "titles": results}
        encoded = (json.dumps(report, indent=2, sort_keys=False) + "\n").encode("utf-8")
        path = args.root / REPORT_PATH
        if args.check and path.read_bytes() != encoded:
            raise ValueError(f"stale census report: {path}")
        if args.write:
            path.write_bytes(encoded)
        for title, result in results.items():
            print(f"{title}: {result['verdict']} "
                  f"(unproven={len(result['unproven_writers'])}, violations={len(result['violations'])})")
        return 0 if all(r["verdict"] == "PROVEN" for r in results.values()) else 1
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Gen 2 mailbox census refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
