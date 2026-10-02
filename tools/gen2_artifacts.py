"""Generate hash-bound Gen 2 overlay execution views; never grant runtime admission.

Source semantics remain the clean packs. Existing source assemblers are re-used
with overlay symbols/ROM, so changed operands must be explained by the pinned
instructions rather than accepted merely because they occur in a published ROM.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import gen_gen2_engine_signals as _signals
from tools.gen2_source_data import (
    ARTIFACTS,
    ROOT,
    SourceVerificationUnavailable,
    load_overlay_context,
    rom_offset,
)
from tools.gen_gen2_area_map import build_area_map
from tools.gen_gen2_engine_signals import SPEC_PATH, generate_pack, read_specs
from tools.gen_gen2_write_checkpoint import build_title

SCHEMA = "gen2-overlay-binding-v1"


def render(binding: dict) -> bytes:
    """Canonical UTF-8/LF publication bytes (also the runtime SHA-256 domain)."""
    return (json.dumps(binding, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _read(root, title, name):
    return json.loads((root / f"data/games/gen2_{title}/{name}.json").read_text(encoding="utf-8"))


def _span(ctx, bank, address, n):
    if type(n) is not int or n <= 0 or address + n > (0x4000 if bank == 0 else 0x8000):
        raise ValueError("execution span crosses ROM bank")
    offset = rom_offset(bank, address)
    if offset + n > len(ctx.rom):
        raise ValueError("execution span outside verified ROM")
    return ctx.rom[offset:offset + n]


def _pinned_hooks(ctx):
    """The two ROM0/title call substitutions, validated independently of sites."""
    records = []
    base = ctx.base
    flag = base.symbol("wVBlankOccurred")
    old = bytes((0x3E, 1, 0xEA)) + flag.address.to_bytes(2, "little")
    bridge = ctx.symbol("SlinkDelayFrameBridge")
    if bridge.bank != 0:
        raise ValueError("DelayFrame bridge must be ROM0")
    new = b"\xcd" + bridge.address.to_bytes(2, "little") + b"\0\0"
    for context, expected in ((base, old), (ctx, new)):
        point = context.symbol("DelayFrame")
        if _span(context, point.bank, point.address, len(expected)) != expected:
            raise ValueError("unexplained DelayFrame builder substitution")
    records.append({"symbol": "DelayFrame", "before_hex": old.hex(), "after_hex": new.hex(),
                    "reason": "pinned DelayFrame -> SlinkDelayFrameBridge + two nops",
                    "source": "tools/build_gen2_companion.py:176-187"})
    old_menu, new_menu = base.symbol("MainMenuJoypadLoop"), ctx.symbol("MainMenuJoypadLoop")
    setup, menu_bridge = base.symbol("SetUpMenu"), ctx.symbol("SlinkMainMenuBridge")
    if menu_bridge.bank != 0:
        raise ValueError("main menu bridge must be ROM0")
    old = b"\xcd" + setup.address.to_bytes(2, "little")
    new = b"\xcd" + menu_bridge.address.to_bytes(2, "little")
    if (_span(base, *old_menu, 3) != old or _span(ctx, *new_menu, 3) != new):
        raise ValueError("unexplained SetUpMenu builder substitution")
    records.append({"symbol": "MainMenuJoypadLoop", "before_hex": old.hex(), "after_hex": new.hex(),
                    "reason": "pinned SetUpMenu call operand -> SlinkMainMenuBridge",
                    "source": "tools/build_gen2_companion.py:140-150"})
    return records


def _byte_spans(value, prefix=""):
    """Expected-byte spans in the complete selected view, including nested guards."""
    if isinstance(value, dict):
        if isinstance(value.get("expected_hex"), str):
            yield prefix, value
        for key, item in value.items():
            yield from _byte_spans(item, f"{prefix}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _byte_spans(item, f"{prefix}/{index}")


def _operand_facts(ctx, expression, scope):
    """(kind, symbol) for one source operand, mirroring `_operand`'s own resolution order.

    "symbol"   -- resolved through ctx.symbol(...): a BANK() byte, a `sym`, or a `sym +/- n` address.
    "wildcard" -- a constant expression (1 << PSN, NAME_LENGTH, NPCTRADE_GIVEMON). `_operand` returns
                  [None] * width for these and generate_pack's `expected is not None` filter then
                  copies the ROM's own byte in, so the ROM -- not the source -- carries them. A change
                  there is unexplained by construction and must refuse.
    "literal"  -- a numeric immediate fixed by the pinned source line itself.
    """
    expression = expression.strip()
    name = scope + expression if expression.startswith(".") else expression
    if expression.startswith("BANK(") and expression.endswith(")"):
        return "symbol", expression[5:-1]
    if match := re.fullmatch(r"([A-Za-z_][\w.]*)\s*[+-]\s*[0-9]+", expression):
        return "symbol", match.group(1)
    if re.fullmatch(r"\(\s*[0-9]+\s*<<\s*[0-9]+\s*\)", expression) or \
            re.fullmatch(r"-?[0-9]+|\$[0-9a-fA-F]+|%[01]+", expression):
        return "literal", expression
    if re.fullmatch(r"[A-Z][A-Z0-9_]*(?:\s*(?:<<|>>|[+|&-])\s*(?:[0-9]+|[A-Z][A-Z0-9_]*))*"
                    r"|[0-9]+\s*<<\s*[A-Z][A-Z0-9_]*", expression):
        return "wildcard", expression
    if name in ctx.symbols:
        return "symbol", name
    raise ValueError(f"unsupported CPU operand {expression!r}")


def _site_provenance(ctx, specs, site):
    """(proved, wildcards, start, length): the source evidence behind one site's expected_hex.

    `proved` maps a byte offset in the site's instruction stream to the SYMBOL whose operand resolved
    it; `wildcards` holds the constant-expression offsets; start/length bound the published expected_hex
    window inside that stream (generate_pack's hook slice).

    Positions are recovered exactly rather than guessed. `_operand` is temporarily wrapped to return a
    unique marker string per call instead of bytes; `_instruction` only ever SPREADS an operand result
    into its pattern (or indexes it, for ldh), so every marker lands on precisely the bytes that operand
    produced, while opcode and literal positions keep their integer values and stay distinguishable.
    The wrapper is a module attribute, so it is restored in a finally and the generator stays
    single-threaded by construction.
    """
    repo = ctx.source_record()["repo"]
    specification = next(s for s in specs["sites"] if s["id"] == site)
    definition = specification["sources"][repo]
    symbol = ctx.symbol(definition["symbol"])
    scope = definition["symbol"].split(".")[0]
    hook, count = definition["hook_index"], definition["hook_count"]
    real_operand = _signals._operand
    proved, wildcards, markers, lengths = {}, set(), {}, []
    offset, address, serial = 0, symbol.address, 0
    for instruction in definition["instructions"]:

        def recording(inner, expression, width, inner_scope):
            nonlocal serial
            serial += 1
            kind, name = _operand_facts(inner, expression, inner_scope)
            tag = f"\x00operand:{serial}"
            markers[tag] = (kind, name)
            return [tag] * width

        _signals._operand = recording
        try:
            pattern = _signals._instruction(ctx, instruction, address, scope, ctx.read_source)
        finally:
            _signals._operand = real_operand
        for position, value in enumerate(pattern):
            if isinstance(value, str):
                kind, name = markers[value]
                if kind == "wildcard":
                    wildcards.add(offset + position)
                elif kind == "symbol":
                    proved[offset + position] = name
        lengths.append(len(pattern))
        offset += len(pattern)
        address += len(pattern)
    # The published window is generate_pack's hook slice of that stream (gen_gen2_engine_signals.py:412).
    return proved, wildcards, sum(lengths[:hook]), sum(lengths[hook:hook + count])


def _site_change_reasons(ctx, specs):
    """The per-site `operands` callback `_explain_spans` uses: accept a changed byte only where a
    pinned source operand PROVED it against the overlay symbols, and refuse every other changed byte
    with a message that says which kind of position it was.

    Refusal is deliberately the conservative direction. A changed byte that is neither a symbol-resolved
    operand nor a wildcard -- an opcode, a literal immediate, or a call/jp/jr target resolved through
    ctx.symbol() rather than `_operand` -- is refused too, even though generate_pack has already proved
    such a byte against the ROM. D2 requires an unexplained opcode/control-flow change to refuse, and
    proving more than asked is the safe direction: the cost is a precise refusal on a future
    republication, never a silent acceptance.
    """
    cache = {}

    def verify(path, before_hex, after_hex):
        name = path.lstrip("/")
        if "/" in name:
            raise ValueError(
                f"sites{path}: nested guard span is not a proved source operand window; it must stay "
                f"byte-identical (a changed guard prelude needs source instructions, not a repin)")
        if name not in cache:
            cache[name] = _site_provenance(ctx, specs, name)
        proved, wildcards, start, length = cache[name]
        if len(after_hex) != len(before_hex) or length * 2 != len(after_hex):
            raise ValueError(
                f"sites{path}: published window is {length} bytes but the span is "
                f"{len(after_hex) // 2}; the hook slice and the span disagree")
        before, after = bytes.fromhex(before_hex), bytes.fromhex(after_hex)
        names = []
        for index, (old, new) in enumerate(zip(before, after, strict=True)):
            if old == new:
                continue
            position = start + index
            if position in wildcards:
                raise ValueError(
                    f"sites{path}: byte {position} (span index {index}, 0x{old:02x} -> 0x{new:02x}) is a "
                    f"constant-expression operand carried by the ROM, not proved by any pinned source "
                    f"operand; a change there is unexplained")
            if position not in proved:
                raise ValueError(
                    f"sites{path}: byte {position} (span index {index}, 0x{old:02x} -> 0x{new:02x}) is not a "
                    f"symbol-resolved operand byte (it is an opcode, literal immediate, or branch target); "
                    f"an unexplained opcode/control-flow change must refuse generation")
            names.append(proved[position])
        return ("pinned source operand " + ", ".join(sorted(set(names))) +
                " re-resolved in the overlay symbol table and proved against the overlay ROM")

    return verify


def _explain_spans(old, new, ctx, label, *, operands=None, allow=None):
    """Every changed covered span must be PROVED by a source fact, byte by byte.

    `operands(path, before_hex, after_hex)` returns the reason naming what verified the change, or
    raises. It is used for engine sites, where the evidence is per byte. Spans with no per-byte source
    provenance (map headers, checkpoint anchors) use `allow(path)` as the whole test. Unassembled small
    oracle prologues must stay byte-identical: expanding their contract to a changed prologue needs
    source instructions, not repins.
    """
    previous = dict(_byte_spans(old))
    changes = []
    for path, row in _byte_spans(new):
        before = previous.pop(path)
        bank = row.get("bank")
        address = row.get("addr", row.get("address"))
        if bank is not None and address is not None:
            raw = _span(ctx, bank, address, len(row["expected_hex"]) // 2)
            if raw.hex() != row["expected_hex"].lower():
                raise ValueError(f"{label}{path}: expected bytes differ from overlay")
        if before["expected_hex"].lower() != row["expected_hex"].lower():
            if operands is not None:
                reason = operands(path, before["expected_hex"], row["expected_hex"])
            elif allow is not None and allow(path):
                reason = "pinned source instructions reassembled with overlay symbol operands"
            else:
                raise ValueError(f"unexplained changed execution bytes: {label}{path}")
            changes.append({"scope": label + path, "before_hex": before["expected_hex"],
                            "after_hex": row["expected_hex"], "reason": reason})
    if previous:
        raise ValueError(f"{label}: execution spans disappeared")
    return changes


def generate_binding(title: str, root: Path = ROOT) -> dict:
    """Generate one SOURCE execution binding from independently verified inputs."""
    root = Path(root).resolve()
    ctx = load_overlay_context(title, root=root)
    specs = read_specs(root / SPEC_PATH)
    clean_sites = _read(root, title, "engine_signals")
    clean_checkpoint = _read(root, title, "write_checkpoint")
    profile = _read(root, title, "profile")["titles"][title]
    clean_areas = _read(root, title, "area_map")
    # Refuse stale clean facts rather than derive new overlay facts from them.
    if generate_pack(ctx.base, specs) != clean_sites:
        raise ValueError("clean engine-site pack differs from pinned source generation")
    if build_title(ctx.base) != clean_checkpoint:
        raise ValueError("clean checkpoint differs from pinned source generation")
    try:
        sites = generate_pack(ctx, specs)["titles"][title]["sites"]
        checkpoint = build_title(ctx)["titles"][title]
        areas = build_area_map(ctx)
    except ValueError as exc:
        raise ValueError(f"unexplained overlay execution change: {exc}") from exc
    old_sites = clean_sites["titles"][title]["sites"]
    old_checkpoint = clean_checkpoint["titles"][title]
    if sites.keys() != old_sites.keys() or areas.keys() != clean_areas.keys():
        raise ValueError("overlay changed gameplay site/map inventory")
    changes = _explain_spans(old_sites, sites, ctx, "sites", operands=_site_change_reasons(ctx, specs))
    changes += _explain_spans(old_checkpoint, checkpoint, ctx, "checkpoint",
                             allow=lambda path: "/anchors/" in path)
    headers = []
    changed_headers = 0
    for key in sorted(areas):
        before, after = clean_areas[key], areas[key]
        if {k: v for k, v in before.items() if k != "source"} != {
                k: v for k, v in after.items() if k != "source"}:
            raise ValueError(f"overlay changed shared map semantics: {key}")
        old = bytes.fromhex(before["source"]["header_hex"])
        expected = bytearray(old)
        attrs = ctx.symbol(after["map_name"] + "_MapAttributes")
        expected[0], expected[3:5] = attrs.bank, attrs.address.to_bytes(2, "little")
        actual = bytes.fromhex(after["source"]["header_hex"])
        if actual != expected:
            raise ValueError(f"unexplained overlay map-header change: {key}")
        headers.append({"offset": after["source"]["header_flat"], "hex": actual.hex()})
        if before["source"]["header_flat"] != after["source"]["header_flat"] or old != actual:
            changed_headers += 1
            changes.append({"scope": "header/" + key, "before_hex": old.hex(), "after_hex": actual.hex(),
                            "reason": "source MapGroup/MapAttributes symbols resolved in overlay"})
    profile_rom = {}
    for name, old in profile["rom"].items():
        original = ctx.base.symbol(name)
        if (old["bank"], old["addr"], old["flat"]) != (
                *original, rom_offset(*original)):
            raise ValueError(f"clean profile ROM coordinate differs from symbol: {name}")
        point = ctx.symbol(name)
        profile_rom[name] = {"bank": point.bank, "addr": point.address, "flat": rom_offset(*point)}
    hooks = _pinned_hooks(ctx)
    identity = ctx.execution_record()
    return {"schema": SCHEMA, **identity, "sites": sites, "checkpoint": checkpoint,
            "header_anchors": headers, "profile_rom": profile_rom,
            "changes": changes, "builder_substitutions": hooks,
            "summary": {"sites": len(sites), "changed_sites": sum(sites[k] != old_sites[k] for k in sites),
                        "checkpoint_anchors": sum(len(checkpoint[k]["anchors"]) for k in ("primary", "battle_hold")),
                        "changed_checkpoint_anchors": sum(checkpoint[k]["anchors"][a] != old_checkpoint[k]["anchors"][a]
                            for k in ("primary", "battle_hold") for a in checkpoint[k]["anchors"]),
                        "header_anchors": len(headers), "changed_header_anchors": changed_headers,
                        "changed_profile_rom": sum(v != profile["rom"][k] for k, v in profile_rom.items())}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--title", choices=tuple(ARTIFACTS))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        outputs = {}
        for title in ([args.title] if args.title else ARTIFACTS):
            binding = generate_binding(title, args.root)
            path = args.root / f"data/games/gen2_{title}/overlay/binding.json"
            outputs[path] = render(binding)
            print(f"{title}: {json.dumps(binding['summary'], sort_keys=True)}; SOURCE only", flush=True)
        for path, payload in outputs.items():
            if args.check:
                if not path.is_file() or path.read_bytes().replace(b"\r\n", b"\n") != payload:
                    raise ValueError(f"binding missing or stale: {path}")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
        return 0
    except SourceVerificationUnavailable as exc:
        # Fail closed, but never as a stale artifact: the source is UNVERIFIED, not changed. Exit 2
        # separates an infrastructure outage from the exit 1 a real stale/mismatched binding produces.
        print(f"overlay binding generation HALTED (infrastructure, not a verdict): {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"overlay binding generation refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
