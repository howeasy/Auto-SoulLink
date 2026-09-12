"""Source/assembly oracles for the currently implemented R/B patch.

These checks validate its layout, not gameplay safety or the requested trade features.
All compiler outputs are temporary and stay inside the invoking worktree.
"""
from __future__ import annotations

import ast
import hashlib
import operator
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def flat(symbol: int) -> int:
    bank, address = symbol >> 16, symbol & 0xFFFF
    if not (0 <= bank < 64 and
            (0 <= address < 0x4000 if bank == 0 else 0x4000 <= address < 0x8000)):
        raise ValueError(f"invalid bank-qualified ROM symbol {symbol:#x}")
    return address if bank == 0 else bank * 0x4000 + address - 0x4000


def verify_anchors(rom: bytes, symbols: dict, manifest) -> str:
    spans = manifest.validated_spans(bytes(manifest.BANK_SIZE), len(rom))
    checked = 0
    for off, before, _after, why in spans:
        if rom[off:off + len(before)] != before:
            raise ValueError(f"expected-before byte mismatch at {off:#x}: {why}")
        if off == manifest.INJECT_OFFSET:
            continue
        if not any(lo <= off and off + len(before) <= hi for lo, hi in manifest.FREE_SPANS):
            if off not in manifest.SOURCE_ANCHORS:
                raise ValueError(f"missing source label for patch span {off:#x}")
            label, delta = manifest.SOURCE_ANCHORS[off]
            if flat(symbols[label]) + delta != off:
                raise ValueError(f"{label}+{delta:#x} does not resolve to {off:#x}")
        checked += 1
    # Validate the full instruction operands and their bank context, not just an address.
    play = symbols["TrackPlayTime"]
    switch = symbols["Bankswitch"]
    expected_hook = bytes([0x06, play >> 16, 0x21]) + (play & 0xFFFF).to_bytes(2, "little")
    expected_hook += b"\xcd" + flat(switch).to_bytes(2, "little")
    if expected_hook != manifest.HOOK_ORIGINAL:
        raise ValueError("VBlank displaced call disagrees with TrackPlayTime/Bankswitch")
    if rom.count(expected_hook) != 1:
        raise ValueError("VBlank hook is not unique")
    # Menu stub runs with bank 1 mapped; the trampoline runs with bank 4 mapped.
    for label, bank in (("StartMenuExitText", 1), ("StartMenu_Option", 4)):
        if symbols[label] >> 16 != bank:
            raise ValueError(f"{label} moved from caller bank {bank}")
    expected_stub = (b"\xe5\x11" + (symbols["StartMenuExitText"] & 0xFFFF).to_bytes(2, "little")
                     + b"\xcd" + flat(symbols["PlaceString"]).to_bytes(2, "little"))
    if not manifest.MENU_STUB.startswith(expected_stub):
        raise ValueError("menu stub's bank-qualified call/string operands disagree with pret")
    expected_compare = b"\xfe\x05\xca" + (symbols["StartMenu_Option"] & 0xFFFF).to_bytes(2, "little")
    if not manifest.TRAMPOLINE.startswith(expected_compare):
        raise ValueError("dispatch trampoline's bank-4 target disagrees with pret")
    for code, label in ((manifest.TRAMPOLINE, "CloseStartMenu"),
                        (manifest.PANEL_ENTRY, "RedisplayStartMenu")):
        if not code.endswith(b"\xc3" + flat(symbols[label]).to_bytes(2, "little")):
            raise ValueError(f"return jump to {label} disagrees with pret")
    return f"{checked} anchored/free spans; displaced and cross-bank calls verified"


def verify_future_hook_anchors(title: str, rom: bytes, symbols: dict) -> str:
    """Canonical prerequisites only: this does not assert that a trade patch exists."""
    delay = flat(symbols["DelayFrame"])
    if rom[delay:delay + 11] != bytes.fromhex("3e01e0d676f0d6a720fac9"):
        raise ValueError("DelayFrame terminal return differs from home/vblank.asm")
    anchor = 0x28AF if title == "yellow" else 0x29BF
    npc = symbols["CableClubNPC"]
    call = (b"\xfe\xf6\x20\x0a\x21" + (npc & 0xFFFF).to_bytes(2, "little")
            + bytes([0x06, npc >> 16, 0xCD])
            + flat(symbols["Bankswitch"]).to_bytes(2, "little"))
    if rom[anchor:anchor + len(call)] != call or rom.count(call) != 1:
        raise ValueError("TX_SCRIPT_CABLE_CLUB_RECEPTIONIST dispatch is not unique/canonical")
    bank = 0x3B if title == "yellow" else 0x3F
    if any(rom[bank * 0x4000:(bank + 1) * 0x4000]):
        raise ValueError(f"trade handler destination bank {bank:#x} is not empty")
    return f"DelayFrame RET {delay + 10:#x}; receptionist {anchor:#x}; bank {bank:#x} free"


def verify_assembly_references(source: str, rom_symbols: dict, ram_symbols: dict) -> str:
    """Every external literal address in the assembly resolves to a pinned symbol."""
    code = re.sub(r";[^\n]*", "", source)
    patch_constants = {
        "SLINK_MAILBOX": 0xDEE2, "SLINK_ABI_VERSION": 3, "SLINK_HEARTBEAT": 0xDEE8,
        "SLINK_SFX_HEAD": 0xDEEA, "SLINK_SFX_TAIL": 0xDEEB, "SLINK_SFX_FIFO": 0xDEEC, "SLINK_SFX_OVERFLOW": 0xDEF0,
        "SLINK_CAPS": 0xDEE7, "SLINK_PANEL_STATE": 0xDEF1,
        "SLINK_PANEL_PAGE": 0xDEF2, "SLINK_PANEL_PAGES": 0xDEF3,
        "SLINK_PANEL_GEN": 0xDEF4, "SLINK_PANEL_ACK": 0xDEF5, "SLINK_PANEL_TRANSFERS": 0xDEF6,
        "SLINK_PANEL_LEASE": 0xDEF7, "SLINK_CANARY": 0xDEF8, "SLINK_CANARY_VALUE": 0xA5,
        "SLINK_CAP_SFX": 1, "SLINK_CAP_PANEL": 2, "SLINK_CAP_PC_TRADE": 4,
        "SLINK_PANEL_CLOSED": 0, "SLINK_PANEL_AWAIT": 1, "SLINK_PANEL_STAGED": 2, "SLINK_PANEL_DISPLAY": 3,
        "SCREEN_WIDTH": 20, "SLINK_STAGE_TIMEOUT": 180, "SLINK_PAD_A": 1, "SLINK_PAD_ANY": 11,
        "rBGP": 0xFF47, "rOBP0": 0xFF48, "rOBP1": 0xFF49,
    }
    constants = {}
    ops = {ast.Add: operator.add, ast.Sub: operator.sub,
           ast.LShift: operator.lshift, ast.BitOr: operator.or_}

    def value(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name) and node.id in constants:
            return constants[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](value(node.left), value(node.right))
        raise ValueError("unclassified assembly constant expression")

    for line in code.splitlines():
        if not re.match(r"\s*DEF\b", line):
            continue
        match = re.fullmatch(r"\s*DEF\s+(\w+)\s+EQU\s+(.+?)\s*", line)
        if not match:
            raise ValueError(f"unclassified assembly definition: {line.strip()}")
        name, expression = match.groups()
        if name in constants:
            raise ValueError(f"duplicate assembly definition: {name}")
        expression = re.sub(r"\$([0-9a-fA-F]+)", r"0x\1", expression)
        constants[name] = value(ast.parse(expression, mode="eval").body)
    checked = 0
    for name, actual in constants.items():
        if name in patch_constants:
            expected = patch_constants[name]
        elif name == "TrackPlayTimeBank":
            expected = rom_symbols["TrackPlayTime"] >> 16
        elif name in rom_symbols:
            expected = rom_symbols[name] & 0xFFFF
            if name != "TrackPlayTime" and rom_symbols[name] >> 16:
                raise ValueError(f"direct assembly call {name} is not in ROM0")
        elif name in ram_symbols:
            expected = ram_symbols[name]
        else:
            raise ValueError(f"assembly address {name} has no canonical symbol")
        if expected != actual:
            raise ValueError(f"assembly {name}={actual:#x}, canonical={expected:#x}")
        checked += 1
    # Don't silently stop checking a new operand because it wasn't declared as DEF.
    local_labels = set(re.findall(r"^(\w+)::?", code, re.M))
    for operand in re.findall(r"^\s*(?:call|jp)\s+([^\n]+)", code, re.M):
        parts = [part.strip() for part in operand.split(",")]
        if len(parts) > 2 or (len(parts) == 2 and parts[0] not in ("z", "nz", "c", "nc")):
            raise ValueError(f"unclassified assembly control-flow operand {operand}")
        name = parts[-1]
        if name not in constants and name not in local_labels and not re.fullmatch(r"\.\w+", name):
            raise ValueError(f"unclassified assembly control-flow target {name}")
    if re.search(r"^\s*(?:ld|ldh)\s+[^\n]*\[\s*(?:\$|%|\d)|^\s*ld\s+(?:bc|de|hl|sp),\s*(?:\$|%|\d)",
                 code, re.I | re.M):
        raise ValueError("inline assembly address requires a classified symbolic definition")
    return f"{checked} external assembly addresses/banks match canonical symbols"


def verify_generated_payload(manifest) -> str:
    from tools._build_tools_bootstrap import CACHE_DIR, RGBDS_VERSION

    rgbds = Path(CACHE_DIR)
    exe = ".exe" if (rgbds / "rgbasm.exe").exists() else ""
    for tool in ("rgbasm", "rgblink"):
        binary = rgbds / f"{tool}{exe}"
        if not binary.is_file():
            raise FileNotFoundError(f"missing pinned tool prerequisite: {binary}")
        version = subprocess.run([str(binary), "--version"], check=True,
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        if version != f"{tool} {RGBDS_VERSION}":
            raise ValueError(f"unexpected toolchain version: {version}")
    source = ROOT / "patch/gen1/src/slink.asm"
    build_dir = ROOT / "patch/build"
    build_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="verify-gen1-asm-", dir=build_dir) as directory:
        work = Path(directory)
        obj, image, sym = work / "slink.o", work / "slink.gb", work / "slink.sym"
        for cmd in ([str(rgbds / f"rgbasm{exe}"), "-o", str(obj), str(source)],
                    [str(rgbds / f"rgblink{exe}"), "-p", "0x00", "-o", str(image),
                     "-n", str(sym), str(obj)]):
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        data = image.read_bytes()
        if len(data) != manifest.INJECT_OFFSET + manifest.BANK_SIZE:
            raise ValueError("linked companion image has unexpected size")
        payload = data[manifest.INJECT_OFFSET:]
        published = (ROOT / "patch/gen1/dist/slink_bank3f.bin").read_bytes()
        if not published or len(published) > manifest.BANK_SIZE:
            raise ValueError("published companion payload is empty/oversized")
        if published != payload.rstrip(b"\x00"):
            raise ValueError("published companion payload differs from freshly assembled source")
        linked = {name: (int(bank, 16), int(addr, 16)) for bank, addr, name in re.findall(
            r"^([0-9a-fA-F]+):([0-9a-fA-F]+) (\S+)$", sym.read_text(), re.M)}
        for label, addr in (("SlinkHook", manifest.HOOK_TARGET),
                            ("SlinkPanel", manifest.SLINK_PANEL_ADDR)):
            if linked.get(label) != (manifest.HOOK_BANK, addr):
                raise ValueError(f"linked {label} disagrees with manifest destination")
    return f"fresh RGBDS assembly; payload sha256={hashlib.sha256(published).hexdigest()}"
