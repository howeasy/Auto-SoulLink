"""Generate hash-bound Gen 2 overlay execution views; never grant runtime admission.

Source semantics remain the clean packs. Existing source assemblers are re-used
with overlay symbols/ROM, so changed operands must be explained by the pinned
instructions rather than accepted merely because they occur in a published ROM.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.gen2_source_data import ARTIFACTS, ROOT, load_overlay_context, rom_offset
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


def _explain_spans(old, new, ctx, label, *, assembled):
    """Every changed covered span gets source reassembly or exact symbol evidence.

    Unassembled small oracle prologues must remain byte-identical. Expanding
    their contract to a changed prologue needs source instructions, not repins.
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
            if not assembled(path):
                raise ValueError(f"unexplained changed execution bytes: {label}{path}")
            changes.append({"scope": label + path, "before_hex": before["expected_hex"],
                            "after_hex": row["expected_hex"],
                            "reason": "pinned source instructions reassembled with overlay symbol operands"})
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
    changes = _explain_spans(old_sites, sites, ctx, "sites", assembled=lambda _path: True)
    changes += _explain_spans(old_checkpoint, checkpoint, ctx, "checkpoint",
                             assembled=lambda path: "/anchors/" in path)
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
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"overlay binding generation refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
