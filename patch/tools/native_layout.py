#!/usr/bin/env python3
"""Generate/check the retained RR companion layout; never allocate or relocate RAM."""
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("patch/layout/rr_v2.json")
OUTPUTS = (Path("patch/src/native_layout_generated.h"), Path("lua/rr/native_layout.lua"),
           Path("patch/src/slink.ld"))
WIDTHS = {"u8": 1, "char": 1, "u16": 2, "s16": 2, "u32": 4, "s32": 4}
# These are revision-one consumer obligations, not a second address map. They
# prevent a malformed schema from hiding an actual C member as padding or
# detaching a typed region from the assertions covering its implementation.
V1_MEMBER_ORDER = {
    "Mailbox": "signature abi_version opcode seq status ack_seq reason args result",
    "SwapState": "active seq diverged _pad real_pid",
    "GhostState": "active oeId gfxId curGfx localId flags wx wy face mv pmapGroup pmapNum snap an run avatarDirty gfxHi curGfxHi imgs anims dispx dispy cx cy leadpx paletteSlot ownedSprite lifecycle",
    "ArmedMove": "armed battler move_pos target seq frames",
    "SlinkState": "_rsvd0 pi_armed pi_oe pi_count",
    "TradeNpcState": "enable oeId mapG mapN",
    "UiState": "pending kind seq frames phase _pad fieldCb",
    "BattleNotif": "active win task phase frames _pad2",
    "EvRing": "wr rd overflow inb pfc ofc prim pcnt ev spc",
    "SlinkInfo": "enable opened drawn lines page pages gen fadephase line",
    "NativeDescriptor": "magic descriptor_version abi size capability_mask mailbox_address mailbox_size storage_guard build_id layout_sha256",
}
V1_REGION_TYPES = {
    "mailbox": "Mailbox", "swap": "SwapState", "ghost": "GhostState", "armed_move": "ArmedMove",
    "peer_interact": "SlinkState", "trade_npc": "TradeNpcState", "ui": "UiState",
    "battle_notif": "BattleNotif", "events": "EvRing", "info": "SlinkInfo",
    "calc_off": None, "script": None, "text": None, "blob": None, "ghost_palette": None, "choices": None,
}
# Buffer extents/alignment are frozen for this extraction revision: scripts,
# bulk-mon operations and palette uploads still have fixed consumer shapes.
V1_RAW_BUFFERS = {"calc_off": (1, 1), "script": (32, 1), "text": (256, 1),
                  "blob": (600, 4), "ghost_palette": (32, 2), "choices": (112, 1)}


class LayoutError(ValueError):
    pass


def require(test, message):
    if not test:
        raise LayoutError(message)


def keys(value, expected, where):
    require(isinstance(value, dict) and set(value) == set(expected.split()), f"{where}: unexpected/missing keys")


def integer(value, low, high, where):
    require(type(value) is int and low <= value <= high, f"{where}: invalid integer")


def unique_pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def canonical(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def fingerprint(document):
    return hashlib.sha256(canonical(document)).hexdigest()


def validate(d):
    keys(d, "schema revision profile arena rom constants capabilities structures regions context_fields reserved_intervals", "layout")
    require(d["schema"] == "slink-rr-native-layout-v1" and type(d["revision"]) is int and d["revision"] == 1
            and d["profile"] == "rr4.1-default", "unsupported layout schema/profile")
    a, rom, c = d["arena"], d["rom"], d["constants"]
    keys(a, "address size ownership", "arena")
    # This extraction is deliberately not a relocation switch. A changed address
    # needs a separate reviewed ownership contract and validator revision.
    require(a["address"] == 0x0203F800 and a["size"] == 0x800, "retained arena must not move or grow")
    require(isinstance(a["ownership"], str) and a["ownership"].startswith("UNRESOLVED:"), "ownership gate must remain unresolved")
    keys(rom, "base limit code_base code_size", "rom")
    require(rom == {"base": 0x08000000, "limit": 0x0A000000, "code_base": 0x08378F70, "code_size": 0x14000},
            "unreviewed ROM link range")
    keys(c, "abi signature descriptor_magic descriptor_version storage_guard context_guard_tag argument_bytes context_offset reservation_offset receipt_reservation_offset reservation_bytes", "constants")
    for name, value in c.items():
        integer(value, 0, 0xFFFFFFFF, name)
    require(c["abi"] == 2 and c["descriptor_version"] == 1, "unsupported native ABI/descriptor")
    require(c["argument_bytes"] == c["context_offset"] == 14 and c["reservation_offset"] == 24
            and c["reservation_bytes"] == 8 and c["receipt_reservation_offset"] == 8,
            "transport partitions changed")
    require(isinstance(d["capabilities"], dict) and d["capabilities"], "missing capabilities")
    bits = []
    for name, bit in d["capabilities"].items():
        require(re.fullmatch(r"[a-z][a-z0-9_]*", name), "invalid capability name")
        integer(bit, 1, 0x80000000, "capability bit")
        require(bit & (bit - 1) == 0 and bit not in bits, "capability bit duplicated/not single")
        bits.append(bit)
    require(isinstance(d["structures"], dict) and d["structures"], "missing structures")
    require(set(d["structures"]) == V1_MEMBER_ORDER.keys(),
            "missing/unknown v1 structure")
    for name, struct in d["structures"].items():
        require(re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", name), "invalid struct name")
        keys(struct, "size alignment fields", name)
        integer(struct["size"], 1, 2048, name)
        require(type(struct["alignment"]) is int and struct["alignment"] in (1, 2, 4), "invalid alignment")
        require(isinstance(struct["fields"], list) and struct["fields"], "missing fields")
        end, names, natural_alignment, member_order = 0, set(), 1, []
        for field in struct["fields"]:
            keys(field, "name type offset count dimensions", name + " field")
            require(isinstance(field["name"], str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field["name"])
                    and field["name"] not in names, "invalid/duplicate field")
            names.add(field["name"])
            member_order.append(field["name"])
            require(isinstance(field["type"], str) and field["type"] in WIDTHS, "unsupported native field type")
            width = WIDTHS[field["type"]]
            natural_alignment = max(natural_alignment, width)
            integer(field["count"], 1, 2048, "field count")
            require(isinstance(field["dimensions"], list) and len(field["dimensions"]) <= 2, "invalid array dimensions")
            count = 1
            for dimension in field["dimensions"]:
                integer(dimension, 1, 2048, "array dimension")
                count *= dimension
            require(count == field["count"], "array dimensions/count disagree")
            integer(field["offset"], 0, struct["size"] - 1, "field offset")
            require(field["offset"] == (end + width - 1) // width * width, "field overlap/hole/alignment drift")
            end = field["offset"] + width * field["count"]
        require(" ".join(member_order) == V1_MEMBER_ORDER[name], f"{name}: retained v1 member order/completeness changed")
        require(struct["alignment"] == natural_alignment and struct["size"] == (end + natural_alignment - 1) // natural_alignment * natural_alignment,
                "struct size/alignment drift")
    require(isinstance(d["regions"], list) and d["regions"], "missing regions")
    names, spans = set(), []
    for region in d["regions"]:
        keys(region, "name offset size struct alignment", "region")
        name = region["name"]
        require(isinstance(name, str) and name in V1_REGION_TYPES and name not in names,
                "invalid/duplicate region name")
        names.add(name)
        integer(region["offset"], 0, a["size"] - 1, "region offset")
        integer(region["size"], 1, a["size"], "region size")
        require(type(region["alignment"]) is int and region["alignment"] in (1, 2, 4)
                and region["offset"] % region["alignment"] == 0, "region alignment drift")
        require(region["struct"] == V1_REGION_TYPES[name], f"{name}: retained v1 region/type binding changed")
        if name in V1_RAW_BUFFERS:
            require((region["size"], region["alignment"]) == V1_RAW_BUFFERS[name],
                    f"{name}: retained v1 raw-buffer extent/alignment changed")
        if region["struct"] is not None:
            require(isinstance(region["struct"], str) and region["struct"] in d["structures"], "unknown region struct")
            struct = d["structures"][region["struct"]]
            require(region["size"] == struct["size"] and region["alignment"] == struct["alignment"],
                    "region struct does not fit/alignment drift")
        spans.append((region["offset"], region["offset"] + region["size"]))
    require(names == V1_REGION_TYPES.keys(),
            "missing/unknown v1 region")
    require(isinstance(d["reserved_intervals"], list), "reserved intervals missing")
    for row in d["reserved_intervals"]:
        require(isinstance(row, list) and len(row) == 2, "invalid reserved interval")
        integer(row[0], 0, a["size"] - 1, "reserved offset")
        integer(row[1], 1, a["size"], "reserved size")
        spans.append((row[0], row[0] + row[1]))
    end = 0
    for start, stop in sorted(spans):
        require(start == end and stop <= a["size"], "arena overlap, unaccounted gap or overflow")
        end = stop
    require(end == a["size"], "arena partition incomplete")
    require(d["context_fields"] == {"map_group": 14, "map_num": 15, "callback2": 16, "script_lock": 20,
                                     "swap_active": 21, "player_id": 22, "guard": 23}, "context partition changed")
    return d


def load(path=ROOT / SOURCE):
    return validate(json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_pairs))


def verify_descriptor(rom, address, build_id, d):
    """Bind every descriptor byte, including terminators/padding, inside injected ROM."""
    integer(address, d["rom"]["code_base"], d["rom"]["code_base"] + d["rom"]["code_size"] - 1, "descriptor address")
    require(address % 4 == 0 and re.fullmatch(r"[0-9a-f]{64}", build_id), "invalid descriptor alignment/build identity")
    v, c = view(d), d["constants"]
    struct = d["structures"]["NativeDescriptor"]
    require(address + struct["size"] <= d["rom"]["code_base"] + d["rom"]["code_size"], "descriptor extends beyond native ROM")
    values = {"magic": c["descriptor_magic"], "descriptor_version": c["descriptor_version"], "abi": c["abi"],
              "size": struct["size"], "capability_mask": v["capability_mask"],
              "mailbox_address": v["regions"]["mailbox"]["address"], "mailbox_size": v["regions"]["mailbox"]["size"],
              "storage_guard": c["storage_guard"], "build_id": build_id, "layout_sha256": fingerprint(d)}
    expected = bytearray(struct["size"])
    for f in struct["fields"]:
        value = values[f["name"]]
        raw = value.encode() + b"\0" if isinstance(value, str) else value.to_bytes(WIDTHS[f["type"]], "little")
        require(len(raw) == WIDTHS[f["type"]] * f["count"], "descriptor field width mismatch")
        expected[f["offset"]:f["offset"] + len(raw)] = raw
    offset = address - d["rom"]["base"]
    require(rom[offset:offset + struct["size"]] == expected, "ROM descriptor differs from generated layout/build contract")


def macro(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()


def view(d):
    return {**{key: d[key] for key in ("schema", "revision", "profile", "arena", "rom", "constants", "capabilities", "context_fields")},
            "sha256": fingerprint(d), "capability_mask": sum(d["capabilities"].values()),
            "regions": {r["name"]: {**r, "address": d["arena"]["address"] + r["offset"]} for r in d["regions"]},
            "structures": {name: {**s, "offsets": {f["name"]: f["offset"] for f in s["fields"]},
                                   "bytes": {f["name"]: f["count"] * WIDTHS[f["type"]] for f in s["fields"]},
                                   "dimensions": {f["name"]: f["dimensions"] for f in s["fields"]}}
                           for name, s in d["structures"].items()}}


def lua(value):
    if isinstance(value, dict):
        return "{\n" + ",\n".join("[" + json.dumps(k) + "]=" + lua(v) for k, v in value.items()) + "\n}"
    if isinstance(value, list):
        return "{" + ",".join(lua(v) for v in value) + "}"
    if value is None:
        return "nil"
    return json.dumps(value)


def render(d):
    d = json.loads(canonical(d))  # key order/formatting cannot change generated bytes
    v = view(d)
    lines = ["/* Generated by patch/tools/native_layout.py. Do not edit. Ownership UNRESOLVED. */",
             "#ifndef SLINK_NATIVE_LAYOUT_GENERATED_H", "#define SLINK_NATIVE_LAYOUT_GENERATED_H", "#include <stddef.h>",
             '#define SLINK_NATIVE_LAYOUT_SHA256 "' + v["sha256"] + '"']
    values = {"ARENA_ADDR": d["arena"]["address"], "ARENA_SIZE": d["arena"]["size"],
              "CODE_BASE": d["rom"]["code_base"], "CODE_SIZE": d["rom"]["code_size"],
              "CAPABILITY_MASK": v["capability_mask"]}
    values.update({k.upper(): val for k, val in d["constants"].items()})
    values.update({"CONTEXT_" + k.upper() + "_OFFSET": val for k, val in d["context_fields"].items()})
    for name, region in v["regions"].items():
        values.update({name.upper() + "_ADDR": region["address"], name.upper() + "_SIZE": region["size"]})
    for name, value in values.items():
        lines.append(f"#define SLINK_{name} 0x{value:X}")
    for name, struct in d["structures"].items():
        m = macro(name)
        assertions = [f'_Static_assert(sizeof(T) == {struct["size"]}, "{name} size drift")',
                      f'_Static_assert(_Alignof(T) == {struct["alignment"]}, "{name} alignment drift")']
        for f in struct["fields"]:
            c_type = f["type"] + "".join(f"[{n}]" for n in f["dimensions"])
            assertions += [f'_Static_assert(offsetof(T, {f["name"]}) == {f["offset"]}, "{name}.{f["name"]} offset drift")',
                           f'_Static_assert(sizeof(((T *)0)->{f["name"]}) == {WIDTHS[f["type"]] * f["count"]}, "{name}.{f["name"]} width drift")',
                           f'_Static_assert(__builtin_types_compatible_p(__typeof__(((T *)0)->{f["name"]}), volatile {c_type}), "{name}.{f["name"]} type/shape drift")']
        lines.append(f"#define SLINK_ASSERT_{m}(T) \\\n" + "; \\\n".join(assertions))
    lines += ["#define SLINK_STRINGIFY_(x) #x", "#define SLINK_STRINGIFY(x) SLINK_STRINGIFY_(x)", "#endif", ""]
    linker = f'''/* Generated by patch/tools/native_layout.py. No mutable implicit native storage. */
MEMORY {{ rom (rx) : ORIGIN = 0x{d['rom']['code_base']:08X}, LENGTH = 0x{d['rom']['code_size']:X} }}
SECTIONS
{{
  .text ORIGIN(rom) : {{ KEEP(*(.text.entry)) *(.text*) *(.rodata*) }} > rom
  .data : {{ *(.data*) }} > rom
  .bss (NOLOAD) : {{ *(.bss*) *(COMMON) }} > rom
  ASSERT(SIZEOF(.data) == 0, "SLink native .data is forbidden: use explicit verified state")
  ASSERT(SIZEOF(.bss) == 0, "SLink native .bss/COMMON is forbidden: use explicit verified state")
  ASSERT(ADDR(.text) == ORIGIN(rom), "native entry placement drift")
  ASSERT(SIZEOF(.text) <= LENGTH(rom), "native code exceeds verified ROM range")
  /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.attributes) *(.comment) *(.note*) }}
}}
'''
    return dict(zip(OUTPUTS, ["\n".join(lines), "-- Generated by patch/tools/native_layout.py. Ownership UNRESOLVED.\nreturn " + lua(v) + "\n", linker], strict=True))


def generate(root=ROOT, *, check=False):
    d = load(root / SOURCE)
    for path, expected in render(d).items():
        target = root / path
        if check:
            require(target.is_file() and target.read_text(encoding="utf-8") == expected, f"stale generated layout: {path}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(expected, encoding="utf-8", newline="\n")
    return d


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        d = generate(check=args.check)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"native layout: {exc}\n")
    print(f"native layout {fingerprint(d)}: {len(d['regions'])} regions; ownership UNRESOLVED")


if __name__ == "__main__":
    main()
