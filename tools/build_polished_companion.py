"""Build the SLink companion overlay for Polished Crystal v3.2.3 (P5a core, Stage 1 phone, Stage 2 panel).

    tools/build_polished_syms.py build_rom_syms(check=True)  -- the clean pinned build must reproduce
        data/polished_sources.lock.json's sha1 (and the committed .sym/.map) or nothing is built
      -> export the pinned commit again, apply POLISHED_EDITS (anchored verify-then-replace-once),
         copy patch/polished/src/* + patch/gb/slink_abi.inc into engine/slink/
      -> make (same pinned RGBDS v1.0.3 + w64devkit, CFLAGS=-O2, space-free build dir)
      -> verify: no clean symbol moved, DelayFrame changed only its 7-byte lead-in, every changed
         byte inside the intended spans; UPS round trip (and onto the release ROM if cached)
      -> patch/dist/SLink-Polished.ups, data/polished/polished_slink.{sym,map} (LF),
         data/polished/overlay_provenance.json

Placement (docs/polished/HOOKS.md): layout.link pins named sections to banks; a section it does
not name is placed by its own SECTION attributes. slink.asm's fixed ROM0[$0070] bridge sits in the
free gap between "High Home" ($005b-$006f) and "Header" ($0100); its fixed BANK[$7E] service sits
in a bank the clean ROM leaves wholly empty. The mailbox takes Polished's own
SECTION "Unused", WRAM0 span ($C60B-$C64F, 69 bytes) without changing its size: the first 40 are the
Stage-0 core and the panel's staged page is the rest. The Phone card's virtual SLink contact
(docs/polished/PHONE_SLOT.md) is a fixed ROM0[$3F34] bridge (the last free ROM0 gap) plus five
same-size `call` operand rewrites in bank $24 (PHONE_HOOKS, each verified opcode + both operands).

    python tools/build_polished_companion.py            # build + publish
    python tools/build_polished_companion.py --check    # build + verify, publish nothing

Native notification sounds (POL-SOUNDS) add the reset-sound latch and the one foreground service
(patch/polished/src/slink_sfx.asm, INCLUDEd from slink.asm): a same-size rewrite of SoftReset's
`call DelayFrames` in home/init.asm, a ROM0[$0089] bridge in the same free gap as the DelayFrame
bridge, and ~120 bytes of bank $7E after the core service. The overlay now advertises
SLINK_CAP_SFX | SLINK_CAP_SFX_NOTIFY.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
from datetime import UTC, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _build_tools_bootstrap import ensure_rgbds, ensure_w64devkit  # noqa: E402
from build_gen2_companion import (  # noqa: E402
    _replace_once,
    _sha256,
    _symbols,
    rom_facts,
    source_sha256,
    ups_apply,
    ups_create,
    verify_symbol_scope,
)
from build_polished_syms import (  # noqa: E402
    _binary_name,
    _lf,
    build_rom_syms,
    export_source,
    load_lock,
)
from slink_space import work_root  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "patch" / "tools"))
import rom_identity  # noqa: E402  (version-masked canonical identity, T8 ruling)
SRC_DIR = ROOT / "patch" / "polished" / "src"
ABI = ROOT / "patch" / "gb" / "slink_abi.inc"
OUT_DIR = ROOT / "data" / "polished"
UPS_PATH = ROOT / "patch" / "dist" / "SLink-Polished.ups"
PROVENANCE_PATH = OUT_DIR / "overlay_provenance.json"
PROVENANCE_SCHEMA = "polished-overlay-provenance-v1"
ABI_VERSION = 3          # patch/gb/slink_abi.inc SLINK_ABI_VERSION (checked against the file below)
MAILBOX = 0xC60B
SERVICE_BANK = 0x7E

# (file, anchor, replacement) -- each anchor must occur exactly once in the pinned source.
POLISHED_EDITS = (
    ("ram/wram0.asm",
     "SECTION \"Unused\", WRAM0\n\n\tds 69 ; it's free real estate\n",
     "SECTION \"Unused\", WRAM0\n\nINCLUDE \"engine/slink/slink_mailbox.asm\" ; SLink overlay: same 69 bytes\n"),
    ("home/delay.asm",
     "DelayFrame::\n; Wait for one frame\n\tldh a, [rLY]\n\tldh [hDelayFrameLY], a\n"
     "\txor a ; ld a, FALSE\n\tldh [hVBlankOccurred], a\n",
     "DelayFrame::\n; Wait for one frame\n"
     "\tcall SlinkDelayFrameBridge ; SLink overlay: the 7-byte lead-in moved into the bridge\n"
     "\tnop\n\tnop\n\tnop\n\tnop\n"),
    # POL-SOUNDS: SoftReset's `call DelayFrames` (home/init.asm) becomes the reset-sound bridge --
    # 3 bytes either way, C preserved, so InitSound/ClearPalettes are untouched and _Init's WRAM0
    # clear still runs after. Same size class as the DelayFrame lead-in rewrite above.
    ("home/init.asm",
     "\tld c, 3\n\tcall DelayFrames\n\n\tjr Init\n",
     "\tld c, 3\n\tcall SlinkResetSoundBridge ; SLink overlay: latch the SFX hold across the reset\n\n\tjr Init\n"),
    # TITLE-VERSION: the 3-byte `call MainMenu_PrintCurrentTimeAndDay` inside
    # MainMenuJoypadLoop's .loop (main_menu.asm:106-107, flat 0x483CD, bytes cd ed 43).
    # The `.loop` anchor makes it unique -- the identical call at :11 is preceded by
    # `ld [wWhichIndexSet], a`.
    ("engine/menus/main_menu.asm", ".loop\n\tcall MainMenu_PrintCurrentTimeAndDay\n",
     ".loop\n\tcall SlinkMainMenuLoopBridge ; SLink overlay: version line\n"),
    # TRADE slice 2a: re-point SpecialsPointers entries 2 and 3 at the bank-$7E gates (trade_gate.asm).
    # The labels keep their names, so the `special` script macro still resolves; nothing in bank $24 changes.
    ("data/events/special_pointers.asm",
     "\tadd_special Special_WaitForLinkedFriend\n\tadd_special Special_CheckLinkTimeout\n",
     "Special_WaitForLinkedFriendSpecial:: ; SLink overlay: bank-$7E gate (trade request skips the cable wait)\n"
     "\tdba SlinkTradeWaitGate\n"
     "Special_CheckLinkTimeoutSpecial:: ; SLink overlay: bank-$7E gate\n"
     "\tdba SlinkTradeTimeoutGate\n"),
    ("main.asm",
     "SECTION \"LureMenu\", ROMX\n\nINCLUDE \"engine/menus/lure_menu.asm\"\n",
     "SECTION \"LureMenu\", ROMX\n\nINCLUDE \"engine/menus/lure_menu.asm\"\n\n"
     "; SLink companion overlay (tools/build_polished_companion.py)\nINCLUDE \"engine/slink/slink.asm\"\n"),
) + tuple(
    # docs/polished/PHONE_SLOT.md Stage 1: the Phone card's virtual SLink contact. Each is a same-size
    # `call` operand rewrite in bank $24; verify_overlay checks the opcode and both operands (PHONE_HOOKS).
    ("engine/pokegear/phone.asm", f"{anchor}\tcall {native}\n", f"{anchor}\tcall {bridge} ; SLink overlay\n")
    for anchor, native, bridge in (
        ("\tinc e\n", "PokegearPhone_CountSetBits", "SlinkPhone_CountSetBits"),
        ("\tinc c\n", "CheckCellNum", "SlinkPhone_CheckCellNum"),
        ("\tld e, l\n", "GetCallerClassAndName", "SlinkPhone_CallerName"),
        ("\tcall PokegearPhone_GetCellNumber\n", "CheckCanDeletePhoneNumber", "SlinkPhone_CanDelete"),
        ("PokegearPhone_MakePhoneCall:\n", "GetMapPhoneService", "SlinkPhone_CallGate"),
    )
)
# (routine holding the call, native callee, ROM0 bridge) -- the only bank-$24 bytes the overlay changes
PHONE_HOOKS = (
    ("PokegearPhone_GetCellNumberFromE", "PokegearPhone_CountSetBits", "SlinkPhone_CountSetBits"),
    ("PokegearPhone_GetCellNumberFromE", "CheckCellNum", "SlinkPhone_CheckCellNum"),
    ("PokegearPhone_UpdateDisplayList", "GetCallerClassAndName", "SlinkPhone_CallerName"),
    ("PokegearPhoneContactSubmenu", "CheckCanDeletePhoneNumber", "SlinkPhone_CanDelete"),
    ("PokegearPhone_MakePhoneCall", "GetMapPhoneService", "SlinkPhone_CallGate"),
)
# (routine holding the call, native callee, ROM0 bridge) -- the one home/init.asm call the overlay rewrites
RESET_HOOKS = (
    ("SoftReset", "DelayFrames", "SlinkResetSoundBridge"),
)
RESET_HOOK_WINDOW = 0x20  # SoftReset's four instructions before the hooked call
PHONE_HOOK_WINDOW = 0x40  # each hooked call lies within this many bytes of its routine's label
# (native special, the bank-$7E gate its SpecialsPointers entry now names): trade slice 2a
TRADE_GATES = (("Special_WaitForLinkedFriend", "SlinkTradeWaitGate"),
               ("Special_CheckLinkTimeout", "SlinkTradeTimeoutGate"))
# the bare `endtext` the timeout gate points the script at (maps/Route26DayofWeekSiblingsHouse.asm .End)
SCRIPT_END_LABEL = "DayOfWeekSiblingsHousePokedexScript.End"
ENDTEXT_OPCODE = 0xC0
DELAY_NATIVE = bytes.fromhex("f044e0d7afe08f")  # ldh a,[rLY] / ldh [hDelayFrameLY],a / xor a / ldh [hVBlankOccurred],a
HEADER_CHECKSUMS = range(0x14D, 0x150)
TITLE_HOOK_FLAT = 0x483CD     # docs/polished/TITLE.md 8.4; ROM bytes `cd ed 43`          # rgbfix header + global checksum


def apply_overlay(tree: pathlib.Path, version: str | None = None) -> list[str]:
    texts: dict[pathlib.Path, str] = {}
    for rel, old, new in POLISHED_EDITS:       # verify every anchor before any write; edits to one file chain
        path = tree / rel
        texts[path] = _replace_once(texts.get(path) or path.read_text(encoding="utf-8"), old, new, rel)
    dst = tree / "engine" / "slink"
    dst.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC_DIR.glob("*.asm")) + [ABI]
    if version is not None:
        # the define patch/polished/src/version.asm INCLUDEs; same shape as the
        # `DEF SLINK_BUILD_VERSION EQUS "..."` build_gen2_companion.py:431 emits
        (dst / "slink_version.inc").write_text(f'DEF SLINK_BUILD_VERSION EQUS "{version}"\n',
                                              encoding="utf-8", newline="\n")
    for src in files:
        (dst / src.name).write_bytes(src.read_bytes())
    for path, text in texts.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    return [f.name for f in files]


def _flat(bank: int, addr: int) -> int:
    return addr if bank == 0 else bank * 0x4000 + addr - 0x4000


def diff_spans(a: bytes, b: bytes) -> list[tuple[int, int]]:
    spans, i = [], 0
    while i < len(a):
        if a[i] != b[i]:
            j = i
            while j < len(a) and a[j] != b[j]:
                j += 1
            spans.append((i, j))
            i = j
        else:
            i += 1
    return spans


def verify_overlay(base: bytes, data: bytes, old: dict, new: dict) -> list[str]:
    """DelayFrame changes only its lead-in; every changed byte lies in an intended range."""
    if len(base) != len(data):
        raise RuntimeError("overlay ROM size differs from the clean ROM")
    if new.get("wSlinkMailbox") != (0, MAILBOX):
        raise RuntimeError(f"wSlinkMailbox at {new.get('wSlinkMailbox')}, want 00:{MAILBOX:04x}")
    delay = _flat(*old["DelayFrame"])
    bridge = new["SlinkDelayFrameBridge"][1]
    if base[delay:delay + 7] != DELAY_NATIVE:
        raise RuntimeError("clean DelayFrame lead-in differs from the pinned bytes")
    if data[delay:delay + 7] != b"\xcd" + bridge.to_bytes(2, "little") + bytes(4):
        raise RuntimeError("DelayFrame lead-in is not `call SlinkDelayFrameBridge` + 4 nop")
    if data[bridge:bridge + 7] != DELAY_NATIVE:
        raise RuntimeError("the bridge does not start with DelayFrame's native lead-in")
    # Both ROM0 bridges live in the same free gap and link adjacently, so ONE changed run covers
    # both: the allowed range is their union, and the union is proven $FF in the clean ROM.
    reset_hi = new["SlinkResetSoundBridgeEnd"][1]
    if new["SlinkResetSoundBridge"][1] != new["SlinkDelayFrameBridgeEnd"][1] \
            or base[bridge:reset_hi] != b"\xff" * (reset_hi - bridge):
        raise RuntimeError("the ROM0 bridges must sit adjacently in the free gap above the DelayFrame bridge")
    svc_bank, svc = new["SlinkService"]
    empty = base[_flat(SERVICE_BANK, 0x4000):_flat(SERVICE_BANK, 0x8000)] == b"\xff" * 0x4000
    if svc_bank != SERVICE_BANK or not empty:
        raise RuntimeError(f"service must link in bank ${SERVICE_BANK:02X}, which must be empty in the clean ROM")
    sfx_lo, sfx_hi = new["SlinkSfxService"], new["SlinkSfxServiceEnd"]
    if sfx_lo[0] != SERVICE_BANK or sfx_hi[0] != SERVICE_BANK \
            or sfx_lo[1] < new["SlinkServiceEnd"][1] or sfx_hi[1] > 0x8000:
        raise RuntimeError("the sound service must link in bank $7E, after the core service")
    allowed = [(delay, delay + 7, "DelayFrame lead-in"),
               (bridge, reset_hi, "ROM0 delay + reset bridges"),
               # The core service, the Stage-2 panel and the sound service are contiguous in the same
               # wholly-empty bank, and diff_spans reports one run across them, so they are allowed
               # as one span (the bank is proven $FF throughout in the clean ROM above).
               (_flat(svc_bank, svc), _flat(svc_bank, max(new["SlinkPanelEnd"][1],
                                                sfx_hi[1], new["SlinkVersionFieldEnd"][1],
                                new["SlinkTradeAllowedItemsEnd"][1], new["SlinkTradeGatesEnd"][1])),
                f"bank ${SERVICE_BANK:02X} service + panel + sound + version + trade frame/items/gates"),
               (HEADER_CHECKSUMS.start, HEADER_CHECKSUMS.stop, "header checksums")]
    # TRADE slice 1: the inert frame + item-policy code links after the version field, in the same bank
    if any(new[n][0] != SERVICE_BANK or new[n][1] < new["SlinkVersionFieldEnd"][1] or new[n][1] > 0x8000
           for n in ("SlinkTradeCheckHeader", "SlinkTradeFrameEnd", "SlinkTradeItemAllowed", "SlinkTradeAllowedItemsEnd",
                 "SlinkTradeWaitGate", "SlinkTradeTimeoutGate", "SlinkTradeEntry", "SlinkTradeGatesEnd")):
        raise RuntimeError("the trade frame/item/gate code must link in bank $7E, after the version field")
    panel_bank, panel = new["SlinkPanel"]
    if panel_bank != SERVICE_BANK or panel < new["SlinkServiceEnd"][1]:
        raise RuntimeError(f"the panel must link in bank ${SERVICE_BANK:02X} after the service")
    phone_lo, phone_hi = new["SlinkPhone_CountSetBits"][1], new["SlinkPhoneBridgeEnd"][1]
    if new["SlinkPhone_CountSetBits"][0] != 0 or base[phone_lo:phone_hi] != b"\xff" * (phone_hi - phone_lo):
        raise RuntimeError("the phone bridge must link into ROM0 bytes the clean ROM leaves free ($FF)")
    # The title bridge sits in the SAME trailing ROM0 gap as the phone bridge and may be adjacent to
    # it, so diff_spans can report one run across both -- allow them as ONE span (two overlapping
    # spans cannot contain a single run).
    t_lo, t_hi = new["SlinkMainMenuLoopBridge"][1], new["SlinkMainMenuLoopBridgeEnd"][1]
    if base[t_lo:t_hi] != b"\xff" * (t_hi - t_lo):
        raise RuntimeError("the title bridge must link into ROM0 bytes the clean ROM leaves free ($FF)")
    allowed += [(min(phone_lo, t_lo), max(phone_hi, t_hi), "ROM0 phone + title bridges"),
                *phone_hook_spans(base, data, old, new)]
    allowed += reset_hook_spans(base, data, old, new)
    allowed.append(gate_table_span(base, data, old, new))
    # TITLE-VERSION: the 3-byte same-size hook on MainMenuJoypadLoop's .loop (main_menu.asm:107).
    # Prove opcode + both operands first -- our own operand change trips "unexpected change" otherwise.
    hook = TITLE_HOOK_FLAT
    tgt = new["SlinkMainMenuLoopBridge"][1]
    if base[hook:hook + 3] != b"\xcd\xed\x43" or data[hook:hook + 3] != b"\xcd" + tgt.to_bytes(2, "little"):
        raise RuntimeError("the main-menu hook is not `call MainMenu_PrintCurrentTimeAndDay` -> `call SlinkMainMenuLoopBridge`")
    allowed.append((hook, hook + 3, "main-menu version hook"))
    report = []
    for start, end in diff_spans(base, data):
        owner = next((name for lo, hi, name in allowed if lo <= start and end <= hi), None)
        if owner is None:
            raise RuntimeError(f"unexpected change at {start:#07x}-{end - 1:#07x}")
        report.append(f"bank ${start // 0x4000:02X} {start:#07x}-{end - 1:#07x} ({end - start:>3} B) {owner}")
    return report


def phone_hook_spans(base: bytes, data: bytes, old: dict, new: dict) -> list[tuple[int, int, str]]:
    """Each PHONE_HOOKS call is exactly one `call native` in the clean routine and now reads `call bridge`."""
    spans = []
    for routine, native, bridge in PHONE_HOOKS:
        bank, addr = old[routine]
        if old[native][0] not in (0, bank) or new[bridge][0] != 0:
            raise RuntimeError(f"{native} must be reachable from bank ${bank:02X} and {bridge} must be ROM0")
        start = _flat(bank, addr)
        want = b"\xcd" + old[native][1].to_bytes(2, "little")
        window = base[start:start + PHONE_HOOK_WINDOW]
        if window.count(want) != 1:
            raise RuntimeError(f"{routine}: expected exactly one `call {native}`, found {window.count(want)}")
        at = start + window.index(want)
        if data[at:at + 3] != b"\xcd" + new[bridge][1].to_bytes(2, "little"):
            raise RuntimeError(f"{routine}: `call {native}` at {at:#07x} is not `call {bridge}`")
        spans.append((at + 1, at + 3, f"{routine}: call {native} -> {bridge}"))
    return spans

def gate_table_span(base: bytes, data: bytes, old: dict, new: dict) -> tuple[int, int, str]:
    """The two re-pointed SpecialsPointers entries (3 bytes each: bank, addr lo, addr hi) and nothing else.

    The old bytes are DERIVED from the clean sym of the native specials and must be what the clean ROM
    holds; the new bytes are the `dba` of the gates from the overlay sym. The script's redirect target must
    be the clean ROM's bare `endtext`.
    """
    ats = []
    for native, gate in TRADE_GATES:
        entry = old[native + "Special"]
        if new[native + "Special"] != entry or entry[0] == 0:
            raise RuntimeError(f"{native}Special moved or is in ROM0")
        at = _flat(*entry)
        was = bytes([old[native][0]]) + old[native][1].to_bytes(2, "little")
        now = bytes([new[gate][0]]) + new[gate][1].to_bytes(2, "little")
        if new[gate][0] != SERVICE_BANK or base[at:at + 3] != was or data[at:at + 3] != now:
            raise RuntimeError(f"{native}Special at {at:#07x}: want {was.hex()} -> {now.hex()}, "
                               f"have {base[at:at + 3].hex()} -> {data[at:at + 3].hex()}")
        ats.append(at)
    if ats != [ats[0] + 3 * i for i in range(len(ats))]:
        raise RuntimeError("the gated SpecialsPointers entries are not adjacent")
    end = old[SCRIPT_END_LABEL]
    if new[SCRIPT_END_LABEL] != end or base[_flat(*end)] != ENDTEXT_OPCODE:
        raise RuntimeError(f"{SCRIPT_END_LABEL} is not a bare `endtext` ({ENDTEXT_OPCODE:#04x}) at {end}")
    return ats[0], ats[0] + 3 * len(ats), "SpecialsPointers entries -> trade gates"


def reset_hook_spans(base: bytes, data: bytes, old: dict, new: dict) -> list[tuple[int, int, str]]:
    """Each RESET_HOOKS call is exactly one `call native` in the clean routine and now reads `call bridge`."""
    spans = []
    for routine, native, bridge in RESET_HOOKS:
        bank, addr = old[routine]
        if old[native][0] != 0 or new[bridge][0] != 0:
            raise RuntimeError(f"{native} must be ROM0 and {bridge} must be ROM0")
        start = _flat(bank, addr)
        window = base[start:start + RESET_HOOK_WINDOW]
        want = b"\xcd" + old[native][1].to_bytes(2, "little")
        if window.count(want) != 1:
            raise RuntimeError(f"{routine}: expected exactly one `call {native}`, found {window.count(want)}")
        at = start + window.index(want)
        if data[at:at + 3] != b"\xcd" + new[bridge][1].to_bytes(2, "little"):
            raise RuntimeError(f"{routine}: `call {native}` at {at:#07x} is not `call {bridge}`")
        spans.append((at + 1, at + 3, f"{routine}: call {native} -> {bridge}"))
    return spans


def moved_symbols(old: dict, new: dict) -> list[str]:
    return [f"{n}: {old[n]} -> {new.get(n)}" for n in old if new.get(n) != old[n]]


def build(*, check: bool = False, version: str | None = None,
          rgbds_bin: pathlib.Path | None = None,
          w64devkit_bin: pathlib.Path | None = None, repo_dir: pathlib.Path | None = None) -> int:
    lock = load_lock()
    spec = lock["outputs"]["polishedcrystal"]
    abi_line = f"DEF SLINK_ABI_VERSION EQU {ABI_VERSION}"
    if abi_line not in ABI.read_text(encoding="utf-8").splitlines():
        raise RuntimeError(f"{ABI.name} no longer declares `{abi_line}`")
    rgbds_bin = rgbds_bin or ensure_rgbds(lock["rgbds_version"])
    devkit_bin = w64devkit_bin or ensure_w64devkit()
    cache = work_root("cache") / "polished"

    # 1. the clean build must reproduce the lock first (raises on a sha1 mismatch)
    clean_dir = cache / "companion-clean"
    if build_rom_syms(repo_dir=repo_dir, build_dir=clean_dir, rgbds_bin=rgbds_bin,
                      w64devkit_bin=devkit_bin, check=True) != 0:
        raise RuntimeError("clean build does not reproduce the committed data/polished/ sym/map -- refusing")
    stem = spec["filename"].removesuffix(".gbc")
    base = (clean_dir / spec["filename"]).read_bytes()
    if hashlib.sha1(base).hexdigest() != spec["sha1"]:
        raise RuntimeError("clean ROM does not match the lock -- refusing")

    # 2. overlay build on a fresh export of the same commit
    tree = cache / "companion-overlay"
    export_source(repo_dir or cache / "src", lock["source"]["commit"], tree)
    applied = apply_overlay(tree, version)
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(rgbds_bin), str(devkit_bin), env.get("PATH", "")])
    cmd = [str(devkit_bin / _binary_name("make")), "-j4", *lock["make_args"], *lock["make_targets"]]
    print(f"[polished-companion] {' '.join(cmd)}  (cwd={tree})", file=sys.stderr)
    result = subprocess.run(cmd, cwd=str(tree), env=env, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout[-6000:] + result.stderr[-6000:])
        raise RuntimeError(f"overlay make failed with exit code {result.returncode}")
    data = (tree / spec["filename"]).read_bytes()

    # 3. verify
    old, new = _symbols(clean_dir / f"{stem}.sym"), _symbols(tree / f"{stem}.sym")
    moved = moved_symbols(old, new)
    verify_symbol_scope(clean_dir / f"{stem}.sym", tree / f"{stem}.sym", panel=False)
    spans = verify_overlay(base, data, old, new)
    ups = ups_create(base, data)
    if ups_apply(base, ups) != data:
        raise RuntimeError("UPS round trip failed")
    release = cache / "release" / spec["filename"]
    release_check = "release ROM not cached"
    if release.exists():
        if hashlib.sha1(ups_apply(release.read_bytes(), ups)).hexdigest() != hashlib.sha1(data).hexdigest():
            raise RuntimeError("UPS applied to the release ROM does not yield the overlay")
        release_check = "UPS applied to the release ROM yields the overlay sha1"

    version_slot = rom_identity.slot_from_sym(
        (tree / f"{stem}.sym").read_text(encoding="utf-8"), "SlinkVersionText")
    canonical = rom_identity.canonical_sha1(data, [version_slot], gb=True)
    # Publish the EXACT masked ranges so the Lua gate masks the same bytes. rom_identity's narrow
    # mask keeps the "SoulLink " prefix IN the identity and only masks off+PREFIX..off+FIELD; a Lua
    # that masked all 20 bytes would compute a different digest and refuse its own overlay.
    canonical_spans = [{"offset": a, "length": b - a}
                       for a, b in rom_identity._spans(len(data), [version_slot], True, True)]
    print(f"[polished-companion] version field {version_slot}  canonical sha1 {canonical[:12]}  "
          f"stamped sha1 {hashlib.sha1(data).hexdigest()[:12]}", file=sys.stderr)

    files = {UPS_PATH: ups,
             OUT_DIR / "polished_slink.sym": _lf((tree / f"{stem}.sym").read_bytes()),
             OUT_DIR / "polished_slink.map": _lf((tree / f"{stem}.map").read_bytes())}
    provenance = {
        "schema": PROVENANCE_SCHEMA,
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": lock["source"],
        "base_sha1": spec["sha1"],
        "abi_version": ABI_VERSION,
        "overlay": {
            "src_dir": SRC_DIR.relative_to(ROOT).as_posix(),
            "applied": applied,
            "edits": list(dict.fromkeys(rel for rel, _old, _new in POLISHED_EDITS)),
            "sources_sha256": {p.relative_to(ROOT).as_posix(): source_sha256(p)
                               for p in sorted(SRC_DIR.glob("*.asm")) + [ABI]},
            "mailbox": f"WRAM0 ${MAILBOX:04X} (69 bytes)",
            "service_bank": f"${SERVICE_BANK:02X}",
        },
        "command": " ".join(["make", "-j4", *lock["make_args"], *lock["make_targets"]]),
        "output": {**rom_facts(data), "identical_to_clean": data == base,
                   "canonical_sha1": canonical,
                   "version_slot": version_slot, "canonical_spans": canonical_spans,
                   "ups": {"file": UPS_PATH.relative_to(ROOT).as_posix(), "size": len(ups), "sha256": _sha256(ups)}},
        "symbols": {p.name: _sha256(b) for p, b in files.items() if p.parent == OUT_DIR},
    }

    print(f"[polished-companion] clean sha1 {spec['sha1']} reproduced", file=sys.stderr)
    print(f"[polished-companion] overlay sha1 {provenance['output']['sha1']}  ups {len(ups)} B  ({release_check})",
          file=sys.stderr)
    print(f"[polished-companion] wSlinkMailbox = {new['wSlinkMailbox'][0]:02x}:{new['wSlinkMailbox'][1]:04x}",
          file=sys.stderr)
    print("[polished-companion] changed spans:\n  " + "\n  ".join(spans), file=sys.stderr)
    print(f"[polished-companion] moved clean symbols: {moved or 'none'}; "
          f"new symbols: {sorted(set(new) - set(old))}", file=sys.stderr)

    if check:
        drift = [str(p.relative_to(ROOT)) for p, b in files.items() if not p.exists() or p.read_bytes() != b]
        committed = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8")) if PROVENANCE_PATH.exists() else {}
        committed.pop("generated", None)
        if committed != {k: v for k, v in provenance.items() if k != "generated"}:
            drift.append(str(PROVENANCE_PATH.relative_to(ROOT)))
        print(f"[polished-companion] --check: {'drift ' + str(drift) if drift else 'reproduces every artifact'}",
              file=sys.stderr)
        return 1 if drift else 0
    for path, blob in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    PROVENANCE_PATH.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"[polished-companion] published {len(files)} files + {PROVENANCE_PATH.relative_to(ROOT)}", file=sys.stderr)
    return 0


def _selfcheck() -> None:
    assert diff_spans(b"abcdef", b"abXdYY") == [(2, 3), (4, 6)]
    assert diff_spans(b"ab", b"ab") == []
    assert moved_symbols({"A": (0, 1), "B": (1, 2)}, {"A": (0, 1), "B": (1, 3)}) == ["B: (1, 2) -> (1, 3)"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="build and verify, publish nothing")
    ap.add_argument("--repo-dir", type=pathlib.Path, default=None)
    ap.add_argument("--rgbds-bin", type=pathlib.Path, default=None)
    ap.add_argument("--w64devkit-bin", type=pathlib.Path, default=None)
    ap.add_argument("--version", default=None,
                    help="stamp into the main-menu version line (20-byte fixed field)")
    ap.add_argument("--selfcheck", action="store_true", help="run the pure-function asserts only")
    args = ap.parse_args()
    if args.selfcheck:
        _selfcheck()
        print("selfcheck ok")
        return 0
    try:
        return build(check=args.check, rgbds_bin=args.rgbds_bin, w64devkit_bin=args.w64devkit_bin,
                     repo_dir=args.repo_dir, version=args.version)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
