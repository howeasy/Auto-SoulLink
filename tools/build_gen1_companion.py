"""Compose canonical R/B panel+trade and Yellow trade-only companion artifacts.

Only exact canonical inputs are supported here. UPR/structural publication and
ordinary runtime/host qualification remain separate release requirements.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from patch.gen1.tools import build as panel_build, manifest as panel_manifest  # noqa: E402
from patch.tools.make_ups import ups_apply, ups_create  # noqa: E402
from server.lua_literals import lua_string  # noqa: E402
from server.patch_plan import PatchSpan, apply_spans  # noqa: E402
from server.protocol import canonical_json, digest  # noqa: E402
from tools.build_gen1_native_trade import (  # noqa: E402
    TARGETS,
    build as native_build,
    read_symbols,  # noqa: E402
)
from tools.gen1_patch_validation import verify_anchors, verify_assembly_references  # noqa: E402
from tools.verify_canonical_sources import verify  # noqa: E402

CATALOG = ROOT / "data/games/gen1_rby/companion_profiles.json"
LUA_CATALOG = CATALOG.with_name("gen1_companion_profiles.lua")


def _native_spans(base, native, info):
    bank = info["entry"]["bank"]
    ranges = [
        (info["entry"]["address"], info["size"], "native trade"),
        (info["foreground"]["service"]["address"], 0x300, "foreground service reservation"),
        (info["receptionist"]["entry"]["address"], info["receptionist"]["size"], "receptionist"),
    ]
    for key in ("ui", "partner_prompt"):
        section = info["receptionist"][key]
        ranges.append((section["address"], section["size"], key))
    spans = []
    for address, size, label in ranges:
        offset = bank * 0x4000 + address - 0x4000
        spans.append(
            PatchSpan(offset, base[offset : offset + size], native[offset : offset + size], label)
        )
    fg, ui = info["foreground"], info["receptionist"]
    for offset, size, label in (
        (fg["bridge"]["start"], fg["bridge"]["end"] - fg["bridge"]["start"], "DelayFrame bridge"),
        (fg["hook"], 3, "DelayFrame hook"),
        (ui["dispatch"], 10, "existing receptionist dispatch"),
    ):
        spans.append(
            PatchSpan(offset, base[offset : offset + size], native[offset : offset + size], label)
        )
    if apply_spans(base, spans, protected=((0x100, 0x150),), bank_size=0x4000) != native:
        raise ValueError("native artifact contains edits outside its source-declared sections")
    return spans


def build(variant, *, verified=False):
    if variant not in TARGETS:
        raise ValueError("RBY variant required")
    if not verified:
        result = verify()
        if result["failures"]:
            raise ValueError("canonical prerequisite failure: " + repr(result["failures"]))
    lock = json.loads((ROOT / "data/pret_sources.lock.json").read_text())
    pin = lock["clean_roms"][TARGETS[variant]]
    base = (ROOT / pin["filename"]).read_bytes()
    native_info = native_build(variant, receptionist=True, verified=True)
    native = (ROOT / native_info["output"]).read_bytes()
    spans = _native_spans(base, native, native_info)
    panel = None
    if variant != "yellow":
        symbols = json.loads((ROOT / "data/pret_rom_syms.json").read_text())[TARGETS[variant]][
            "symbols"
        ]
        ram = json.loads((ROOT / "data/pret_syms.json").read_text())["pokered"]
        verify_anchors(base, symbols, panel_manifest)
        verify_assembly_references(
            (ROOT / "patch/gen1/src/slink.asm").read_text(encoding="utf-8"), symbols, ram
        )
        payload = panel_build.assemble(native_trade=True)
        length = panel_build.code_length(payload)
        if not 0 < length <= 0x500 or any(payload[0x500:]):
            raise ValueError("panel escaped its section before the native service")
        # This is one source-reserved prefix, not a scan authorizing arbitrary free space.
        for offset, before, after, label in panel_manifest.validated_spans(payload):
            if offset == panel_manifest.INJECT_OFFSET:
                before, after = before[:0x500], after[:0x500]
            spans.append(PatchSpan(offset, before, after, label))
        panel = {
            "bank": panel_manifest.HOOK_BANK,
            "entry": panel_manifest.SLINK_PANEL_ADDR,
            "mailbox": ram["wBoxDataEnd"],
            "abi": 3,
            "capability_byte": 6,
            "protocol": "slink-gen1-panel-generation-v1",
            "reveal": read_symbols(Path(panel_build.BUILD) / "slink.sym")["SlinkPanel.reveal"][1],
            "bg_transfer": symbols["AutoBgMapTransfer"] & 0xFFFF,
            "bg_enabled": ram["hAutoBGTransferEnabled"],
            "bg_portion": ram["hAutoBGTransferPortion"],
            "bg_destination": ram["hAutoBGTransferDest"],
            "controls": {
                "state": 15,
                "page": 16,
                "pages": 17,
                "generation": 18,
                "ack": 19,
                "transfers": 20,
                "lease": 21,
                "canary": 22,
            },
            "source_sha256": hashlib.sha256(
                (ROOT / "patch/gen1/src/slink.asm").read_text(encoding="utf-8").encode()
            ).hexdigest(),
        }
        if panel["mailbox"] != 0xDEE2:
            raise ValueError("R/B panel mailbox no longer begins at canonical free WRAM")
    final = apply_spans(base, spans, protected=((0x100, 0x150),), bank_size=0x4000)
    patch = ups_create(base, final)
    if (
        ups_apply(base, patch) != final
        or len(final) != len(base)
        or final[0x100:0x150] != base[0x100:0x150]
    ):
        raise ValueError("companion patch did not round-trip without changing the header/size")
    directory = ROOT / "patch/gen1/build" / ("companion_" + variant)
    directory.mkdir(exist_ok=True)
    output = directory / ("slink_" + variant + ".gb")
    output.write_bytes(final)
    if output.read_bytes() != final:
        raise ValueError("companion file readback differs")
    patch_path = directory / ("SLink-" + variant.capitalize() + ".ups")
    patch_path.write_bytes(patch)
    if patch_path.read_bytes() != patch:
        raise ValueError("companion UPS readback differs")
    info = copy.deepcopy(native_info)
    info.update(
        final_sha1=hashlib.sha1(final).hexdigest(), output=output.relative_to(ROOT).as_posix()
    )
    info["companion"] = {
        "schema": "gen1-canonical-companion-v1",
        "panel": panel,
        "abi": 3,
        "kind": "yellow-trade-only" if variant == "yellow" else "rb-panel-trade",
        "runtime_ready": False,
        "base_sha256": hashlib.sha256(base).hexdigest(),
        "final_sha256": hashlib.sha256(final).hexdigest(),
        "ups": patch_path.relative_to(ROOT).as_posix(),
        "ups_sha256": hashlib.sha256(patch).hexdigest(),
        "spans": [
            {
                "offset": row.offset,
                "before_hex": row.before.hex(),
                "after_hex": row.after.hex(),
                "label": row.label,
            }
            for row in sorted(spans, key=lambda item: item.offset)
        ],
    }
    (directory / "manifest.json").write_text(json.dumps(info, indent=2, sort_keys=True) + "\n")
    return info


def catalog():
    result = verify()
    if result["failures"]:
        raise ValueError("canonical prerequisite failure: " + repr(result["failures"]))
    clean = json.loads((ROOT / "data/games/gen1_rby/admission_profiles.json").read_text())[
        "profiles"
    ]
    profiles = {}
    for variant in TARGETS:
        manifest = build(variant, verified=True)
        profile = {
            "schema": "gen1-rby-canonical-companion-content-v1",
            "variant": variant,
            "final_rom_sha1": manifest["final_sha1"],
            "rom_sha256": manifest["companion"]["final_sha256"],
            "base_sha1": clean[variant]["final_rom_sha1"],
            "source_commit": clean[variant]["source_commit"],
            "party_codec": clean[variant]["party_codec"],
            "codec_data_sha256": clean[variant]["codec_data_sha256"],
            "patch_version": 3,
            "capabilities": {"panel": variant != "yellow", "sfx": False, "pc_trade": True},
            "provenance": "canonical-whole-rom-plus-checked-companion",
            "manifest": manifest,
            "manifest_sha256": digest(manifest),
        }
        profile["content_profile_hash"] = digest(profile)
        profiles[variant] = profile
    return {"schema": "gen1-rby-canonical-companion-catalog-v1", "profiles": profiles}


def outputs(data):
    return {
        CATALOG: json.dumps(data, indent=2, sort_keys=True) + "\n",
        LUA_CATALOG: "-- Generated by tools/build_gen1_companion.py; no ordinary execution authority.\n"
        "local JSON=require('json_codec')\nreturn assert(JSON.decode("
        + lua_string(canonical_json(data))
        + "))\n",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    for path, text in outputs(catalog()).items():
        if options.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                raise SystemExit("companion catalog drift: " + str(path))
        else:
            path.write_text(text, encoding="utf-8", newline="\n")
    print("Canonical companion profiles: PASS (R/B panel+trade; Yellow trade-only; SFX disabled)")


if __name__ == "__main__":
    main()
