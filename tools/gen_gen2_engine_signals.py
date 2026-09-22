"""Generate source-qualified Gen 2 CPU-site candidates; never arm runtime hooks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

if __package__:
    from .gen2_source_data import ARTIFACTS, ROOT, load_context, rom_offset
else:
    from gen2_source_data import ARTIFACTS, ROOT, load_context, rom_offset

REQUIRED_SIGNALS = (
    "wild_battle_start", "trainer_battle_start", "battle_end_result", "capture_party",
    "capture_box", "player_faint", "poison_faint", "whiteout", "evolution_species",
    "npc_trade", "link_trade", "pc_deposit", "pc_withdraw", "pc_release", "change_box",
    "map_load", "bag_ball_received", "save_completed", "continue_loaded", "new_game",
    "soft_reset", "egg_hatch", "gift_static", "roamer_capture", "contest_capture",
)
SPEC_PATH = Path("data/gen2/engine_site_specs.json")
_R8 = {name: index for index, name in enumerate(("b", "c", "d", "e", "h", "l", "[hl]", "a"))}
_R16 = {"bc": 0, "de": 1, "hl": 2, "sp": 3}


def encoded_json(value):
    return (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def read_specs(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate specification key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text("utf-8"), object_pairs_hook=unique)


def _clean(line):
    return re.sub(r"\s+", " ", line.split(";", 1)[0].strip())


def _source_prefix(text, symbol, count):
    """Resolve source labels with RGBDS local scope, then require a literal prefix."""
    scope, start = "", None
    lines = text.splitlines()
    for number, raw in enumerate(lines):
        line = _clean(raw)
        if raw[:1].isspace() or not re.fullmatch(r"[A-Za-z_][\w#@]*:{1,2}|\.[\w#@]+:??", line):
            continue
        label = line.rstrip(":")
        if not label.startswith("."):
            scope = label
        full = scope + label if label.startswith(".") else label
        if full == symbol:
            if start is not None:
                raise ValueError(f"ambiguous source label {symbol}")
            start = number
    if start is None:
        raise ValueError(f"source label {symbol} missing")
    found = []
    for number in range(start + 1, len(lines)):
        line = _clean(lines[number])
        if not line:
            continue
        if not lines[number][:1].isspace():
            # Branch-local labels do not emit bytes, but never walk into a new
            # global routine or data declaration to satisfy a short prefix.
            if re.fullmatch(r"\.[\w#@]+:??", line):
                continue
            raise ValueError(f"source instructions cross a global boundary at {number + 1}")
        found.append((number + 1, line))
        if len(found) == count:
            return start + 1, found
    raise ValueError(f"incomplete source instructions for {symbol}")


def _operand(ctx, expression, width, scope):
    expression = expression.strip()
    name = scope + expression if expression.startswith(".") else expression
    if expression.startswith("BANK(") and expression.endswith(")"):
        target = expression[5:-1]
        target = scope + target if target.startswith(".") else target
        value = ctx.symbol(target).bank
    elif match := re.fullmatch(r"([A-Za-z_][\w.]*)\s*([+-])\s*([0-9]+)", expression):
        value = ctx.symbol(match[1]).address + int(match[3]) * (1 if match[2] == "+" else -1)
    elif match := re.fullmatch(r"\(([0-9]+) << ([0-9]+)\)", expression):
        value = int(match[1]) << int(match[2])
    elif name in ctx.symbols:
        value = ctx.symbol(name).address
    elif re.fullmatch(r"-?[0-9]+|\$[0-9a-fA-F]+|%[01]+", expression):
        value = int(expression[1:], 16 if expression.startswith("$") else 2) if expression[:1] in {"$", "%"} else int(expression)
    elif re.fullmatch(r"[A-Z][A-Z0-9_]*(?:\s*(?:<<|>>|[+|&-])\s*(?:[0-9]+|[A-Z][A-Z0-9_]*))*|[0-9]+\s*<<\s*[A-Z][A-Z0-9_]*", expression):
        # Constant-expression operands are carried by the independently pinned
        # ROM, not evaluated as an invented assembler/constants implementation.
        return [None] * width
    else:
        raise ValueError(f"unsupported CPU operand {expression!r}")
    if not -(1 << (width * 8 - 1)) <= value < (1 << (width * 8)):
        raise ValueError(f"CPU operand does not fit: {expression}")
    return list((value % (1 << (width * 8))).to_bytes(width, "little"))


def _instruction(ctx, text, address, scope, read):
    """Bounded SM83 opcode/length validation; deliberately refuses script macros."""
    op, _, operands = text.partition(" ")
    args = [part.strip() for part in operands.split(",")]
    if op == "lb" and len(args) == 3 and args[0] in _R16:
        if r"ld \1, ((\2) & $ff) << 8 | ((\3) & $ff)" not in read("macros/code.asm"):
            raise ValueError("lb macro source changed")
        return [0x01 + 0x10 * _R16[args[0]], *_operand(ctx, args[2], 1, scope),
                *_operand(ctx, args[1], 1, scope)]
    if op in {"farcall", "callfar", "predef"}:
        target = args[0]
        if op == "predef":
            macro = read("macros/predef.asm")
            for required in ("ld a, (\\1Predef - PredefPointers) / 3", "lda_predef \\1", "call Predef"):
                if required not in macro:
                    raise ValueError("predef macro source changed")
            pointer, base = ctx.symbol(target + "Predef"), ctx.symbol("PredefPointers")
            delta = pointer.address - base.address
            if pointer.bank != base.bank or delta < 0 or delta % 3 or delta // 3 > 255:
                raise ValueError("invalid predef index")
            return [0x3E, delta // 3, 0xCD, *_operand(ctx, "Predef", 2, scope)]
        macro = read("macros/farcall.asm")
        required = ("ld a, BANK(\\1)", "ld hl, \\1", "rst FarCall")
        if not all(part in macro for part in required):
            raise ValueError("farcall macro source changed")
        load_bank = [0x3E, *_operand(ctx, f"BANK({target})", 1, scope)]
        load_addr = [0x21, *_operand(ctx, target, 2, scope)]
        rst = ctx.symbol("FarCall").address
        if rst not in range(0, 0x39, 8):
            raise ValueError("FarCall is not an RST vector")
        return (load_bank + load_addr if op == "farcall" else load_addr + load_bank) + [0xC7 + rst]
    if op == "ld" and len(args) == 2:
        left, right = args
        pairs = {("a", "[bc]"): 0x0A, ("a", "[de]"): 0x1A,
                 ("[bc]", "a"): 0x02, ("[de]", "a"): 0x12,
                 ("a", "[hli]"): 0x2A, ("a", "[hld]"): 0x3A,
                 ("[hli]", "a"): 0x22, ("[hld]", "a"): 0x32}
        if (left, right) in pairs:
            return [pairs[left, right]]
        if left in _R8 and right in _R8:
            return [0x40 + 8 * _R8[left] + _R8[right]]
        if left == "a" and right.startswith("[") and right.endswith("]"):
            return [0xFA, *_operand(ctx, right[1:-1], 2, scope)]
        if left.startswith("[") and left.endswith("]") and left != "[hl]" and right == "a":
            return [0xEA, *_operand(ctx, left[1:-1], 2, scope)]
        if left in _R8:
            return [0x06 + 8 * _R8[left], *_operand(ctx, right, 1, scope)]
        if left in _R16:
            return [0x01 + 0x10 * _R16[left], *_operand(ctx, right, 2, scope)]
    if op == "ldh" and len(args) == 2:
        left, right = args
        operand = right if left == "a" else left
        if not operand.startswith("[") or not operand.endswith("]"):
            raise ValueError("unsupported ldh operand")
        value = _operand(ctx, operand[1:-1], 2, scope)
        return [0xF0 if left == "a" else 0xE0, value[0]]
    if op in {"inc", "dec"}:
        if operands in _R16:
            return [(0x03 if op == "inc" else 0x0B) + 0x10 * _R16[operands]]
        if operands in _R8:
            return [(0x04 if op == "inc" else 0x05) + 8 * _R8[operands]]
    if op in {"push", "pop"} and operands in {"bc", "de", "hl", "af"}:
        return [(0xC5 if op == "push" else 0xC1) + 0x10 * ("bc", "de", "hl", "af").index(operands)]
    if op == "add" and args[0] == "hl" and args[-1] in _R16:
        return [0x09 + 0x10 * _R16[args[-1]]]
    if op in {"and", "or", "xor", "cp", "add", "sub", "adc", "sbc"}:
        register, immediate = {"and": (0xA0, 0xE6), "or": (0xB0, 0xF6),
                               "xor": (0xA8, 0xEE), "cp": (0xB8, 0xFE),
                               "add": (0x80, 0xC6), "sub": (0x90, 0xD6),
                               "adc": (0x88, 0xCE), "sbc": (0x98, 0xDE)}[op]
        if operands in _R8:
            return [register + _R8[operands]]
        return [immediate, *_operand(ctx, operands, 1, scope)]
    conditions = {"nz": 0, "z": 1, "nc": 2, "c": 3}
    if op in {"call", "jp", "jr"}:
        target = args[-1]
        target = scope + target if target.startswith(".") else target
        destination = ctx.symbol(target)
        if op == "jr":
            relative = destination.address - address - 2
            if not -128 <= relative <= 127:
                raise ValueError("relative branch out of range")
            opcode = 0x18 if len(args) == 1 else 0x20 + 8 * conditions[args[0]]
            return [opcode, relative & 255]
        opcode = (0xCD if op == "call" else 0xC3) if len(args) == 1 else (
            (0xC4 if op == "call" else 0xC2) + 8 * conditions[args[0]])
        return [opcode, *destination.address.to_bytes(2, "little")]
    if op == "ret":
        return [0xC9 if not operands else 0xC0 + 8 * conditions[operands]]
    if op == "rst":
        target = ctx.symbol(operands).address
        if target not in range(0, 0x39, 8):
            raise ValueError("invalid RST instruction target")
        return [0xC7 + target]
    if text in {"di", "ei", "scf", "nop"}:
        return [{"di": 0xF3, "ei": 0xFB, "scf": 0x37, "nop": 0x00}[text]]
    raise ValueError(f"unsupported CPU instruction (script bytecode is forbidden): {text}")


def _citation(ctx, path, text, first, last):
    repo = ctx.source_record()["repo"]
    return {"repo": repo, "commit": ctx.source_commit, "file": path,
            "line_start": first, "line_end": last,
            "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "url": f"https://github.com/pret/{repo}/blob/{ctx.source_commit}/{path}#L{first}"}


def _enum_value(read, path, prefix, first_name, name):
    lines = [_clean(line) for line in read(path).splitlines()]
    lines = [line for line in lines if line]
    start = lines.index("const " + first_name)
    if lines[start - 1] != "const_def":
        raise ValueError(f"{prefix} enumeration no longer starts at zero")
    values = []
    for line in lines[start:]:
        if not re.fullmatch(r"const " + re.escape(prefix) + r"[A-Z_]+", line):
            break
        values.append(line.removeprefix("const "))
    if name not in values:
        raise ValueError(f"unknown source enum member: {name}")
    return values.index(name)


def _whiteout_guards(ctx, read):
    """The hook is CPU Special; the script position is a context guard only."""
    script = read("engine/events/whiteout.asm")
    required = ["writetext .WhitedOutText", "waitbutton", "special FadeOutToWhite",
                "pause 40", "special HealParty"]
    _, prefix = _source_prefix(script, "Script_Whiteout", len(required))
    if [line for _, line in prefix] != required:
        raise ValueError("whiteout script sequence changed")
    macros = read("macros/scripts/events.asm")
    # Evaluate this source's linear command enumeration; verify the exact four
    # expansion bodies separately. Never treat these bytes as execution sites.
    commands = re.findall(r"^\s*const (\w+_command)\b", macros, re.MULTILINE)
    if macros.count("const_def") != 1:
        raise ValueError("unsupported script command enumeration")
    def opcode(name):
        return commands.index(name + "_command")
    special_base = ctx.symbol("SpecialsPointers")
    def special_index(name):
        pointer = ctx.symbol(name + "Special")
        delta = pointer.address - special_base.address
        if pointer.bank != special_base.bank or delta < 0 or delta % 3:
            raise ValueError("invalid special pointer index")
        return delta // 3
    expected = bytes([opcode("writetext")]) + ctx.symbol("Script_Whiteout.WhitedOutText").address.to_bytes(2, "little")
    expected += bytes([opcode("waitbutton"), opcode("special")])
    expected += special_index("FadeOutToWhite").to_bytes(2, "little")
    expected += bytes([opcode("pause"), 40, opcode("special")])
    expected += special_index("HealParty").to_bytes(2, "little")
    symbol = ctx.symbol("Script_Whiteout")
    flat = rom_offset(*symbol)
    if ctx.rom[flat:flat + len(expected)] != expected:
        raise ValueError("whiteout script context bytes differ")
    heal, pointer = ctx.symbol("HealParty"), ctx.symbol("HealPartySpecial")
    actual = ctx.rom[rom_offset(*pointer):rom_offset(*pointer) + 3]
    if actual != bytes([heal.bank]) + heal.address.to_bytes(2, "little"):
        raise ValueError("HealParty special pointer differs")

    def return_after_prefix(path, name, count):
        _, rows = _source_prefix(read(path), name, count)
        symbol = ctx.symbol(name)
        cursor = symbol.address
        for _, instruction in rows:
            pattern = _instruction(ctx, instruction, cursor, name, read)
            offset = rom_offset(symbol.bank, cursor)
            actual = ctx.rom[offset:offset + len(pattern)]
            if len(actual) != len(pattern) or any(
                expected is not None and expected != observed
                for expected, observed in zip(pattern, actual, strict=True)
            ):
                raise ValueError("whiteout CPU caller prefix differs")
            cursor += len(pattern)
        return cursor

    script_return = return_after_prefix("engine/overworld/scripting.asm", "Script_special", 5)
    farcall_return = return_after_prefix("home/farcall.asm", "FarCall_hl", 6)
    return {"required": True, "combine": "ALL", "registers": {"DE": special_index("HealParty")},
            "stack_words_equals": [
                {"sp_offset": 0, "width": 2, "byte_order": "little", "value": farcall_return,
                 "meaning": "FarCall_hl call FarCall_JumpToHL return address"},
                {"sp_offset": 4, "width": 2, "byte_order": "little", "value": script_return,
                 "meaning": "Script_special farcall return after saved AF word"}],
            "memory_equals": [
                {"symbol": "wScriptBank", "bank": ctx.symbol("wScriptBank").bank,
                 "addr": ctx.symbol("wScriptBank").address, "width": 1, "value": symbol.bank},
                {"symbol": "wScriptPos", "bank": ctx.symbol("wScriptPos").bank,
                 "addr": ctx.symbol("wScriptPos").address, "width": 2,
                 "byte_order": "little", "value": symbol.address + len(expected)}],
            "script_context": {"symbol": "Script_Whiteout", "bank": symbol.bank,
                               "addr": symbol.address, "expected_hex": expected.hex()},
            "runtime_guard_qualification": "OPEN"}


def generate_pack(ctx, specs):
    if specs.get("schema") != "gen2-engine-site-specs-v1":
        raise ValueError("unsupported site specifications schema")
    if set(specs.get("inventory", {})) != set(REQUIRED_SIGNALS):
        raise ValueError("required signal inventory is incomplete or unknown")
    repo = ctx.source_record()["repo"]
    if specs.get("source_commits", {}).get(repo) != ctx.source_commit:
        raise ValueError("site specifications source commit differs")
    cache = {}
    def read(path):
        if path not in cache:
            cache[path] = ctx.read_source(path)
        return cache[path]
    sites = {}
    for specification in specs["sites"]:
        site_id = specification["id"]
        if site_id in sites or specification["signal"] not in REQUIRED_SIGNALS:
            raise ValueError("duplicate site or unknown signal")
        role = specification.get("event_role", "OBSERVATION")
        if role not in {"OBSERVATION", "CLASSIFICATION_ONLY"}:
            raise ValueError("unknown source observation role")
        definition = specification["sources"][repo]
        text = read(definition["file"])
        if hashlib.sha256(text.encode()).hexdigest() != definition["source_sha256"]:
            raise ValueError(f"{site_id}: source hash differs")
        instructions = definition["instructions"]
        first, lines = _source_prefix(text, definition["symbol"], len(instructions))
        if [line for _, line in lines] != instructions:
            raise ValueError(f"{site_id}: source instructions differ")
        hook, count = definition["hook_index"], definition["hook_count"]
        if not 0 <= hook < hook + count <= len(instructions):
            raise ValueError("invalid instruction selection")
        symbol = ctx.symbol(definition["symbol"])
        base = rom_offset(*symbol)
        chunks, offset = [], 0
        for instruction in instructions:
            pattern = _instruction(ctx, instruction, symbol.address + offset,
                                   definition["symbol"].split(".")[0], read)
            actual = ctx.rom[base + offset:base + offset + len(pattern)]
            if len(actual) != len(pattern) or any(expected is not None and expected != observed
                                                for expected, observed in zip(pattern, actual, strict=True)):
                raise ValueError(f"{site_id}: instruction bytes differ at {instruction}")
            chunks.append(actual)
            offset += len(pattern)
        before = sum(map(len, chunks[:hook]))
        expected = b"".join(chunks[hook:hook + count])
        address = symbol.address + before
        if rom_offset(symbol.bank, address + len(expected) - 1) != base + before + len(expected) - 1:
            raise ValueError("site crosses ROM bank boundary")
        evidence = [_citation(ctx, definition["file"], text, first, lines[-1][0])]
        for proof in definition["evidence"]:
            proof_text = read(proof["file"])
            if proof_text.count(proof["excerpt"]) != 1:
                raise ValueError(f"{site_id}: source caller/semantic evidence missing or ambiguous")
            line = proof_text[:proof_text.index(proof["excerpt"])].count("\n") + 1
            evidence.append(_citation(ctx, proof["file"], proof_text, line,
                                      line + proof["excerpt"].count("\n")))
        guards = {}
        condition = specification.get("conditions", {})
        allowed = {"register_symbols", "register_values", "flags", "requires_prior",
                   "memory_battle_type", "memory_link_mode"}
        if set(condition) - allowed:
            raise ValueError("unknown site condition")
        if condition:
            guards = {"required": True, "combine": "ALL", "runtime_guard_qualification": "OPEN"}
            for register, value in condition.get("register_values", {}).items():
                width = 16 if register in {"BC", "DE", "HL", "SP"} else 8
                if register not in {"A", "B", "C", "D", "E", "H", "L", "BC", "DE", "HL", "SP"} or type(value) is not int or not 0 <= value < (1 << width):
                    raise ValueError("invalid CPU register guard")
            if any(register not in {"BC", "DE", "HL", "SP"}
                   for register in condition.get("register_symbols", {})):
                raise ValueError("symbol-address guard requires a 16-bit CPU register")
            if any(flag not in {"Z", "C"} or type(value) is not int or value not in {0, 1}
                   for flag, value in condition.get("flags", {}).items()):
                raise ValueError("invalid CPU flag guard")
            if condition.get("register_symbols"):
                guards["registers"] = {register: ctx.symbol(name).address
                                       for register, name in condition["register_symbols"].items()}
            if condition.get("register_values"):
                guards.setdefault("registers", {}).update(condition["register_values"])
            if condition.get("flags"):
                guards["flags"] = condition["flags"]
            if condition.get("requires_prior"):
                guards["requires_prior"] = {
                    **condition["requires_prior"], "mode": "ANY", "scope": "current_operation",
                    "invalidate_on": ["failure", "cancel", "reset", "reload", "source_change"],
                }
            for key, symbol_name, path, prefix, first_name in (
                ("memory_battle_type", "wBattleType", "constants/battle_constants.asm",
                 "BATTLETYPE_", "BATTLETYPE_NORMAL"),
                ("memory_link_mode", "wLinkMode", "constants/serial_constants.asm",
                 "LINK_", "LINK_NULL"),
            ):
                if condition.get(key):
                    target = ctx.symbol(symbol_name)
                    guards.setdefault("memory_equals", []).append({
                        "symbol": symbol_name, "bank": target.bank, "addr": target.address,
                        "width": 1, "value": _enum_value(read, path, prefix, first_name, condition[key]),
                    })
        if specification["signal"] == "whiteout":
            if definition["symbol"] != "Special" or hook != 0:
                raise ValueError("whiteout requires the guarded CPU Special entry")
            guards = _whiteout_guards(ctx, read)
        sites[site_id] = {
            "signal": specification["signal"], "kind": "CPU_INSTRUCTION",
            "symbol": definition["symbol"], "symbol_offset": before,
            "bank": symbol.bank, "addr": address, "rom_offset": base + before,
            "expected_hex": expected.hex(), "instructions": instructions[hook:hook + count],
            "phase": specification["phase"], "semantics": specification["semantics"],
            "event_role": role,
            "maturity": "SOURCE_CANDIDATE", "physical_firing": "OPEN",
            "runtime_enabled": False, "guards": guards,
            "point_symbols": {name: {"bank": ctx.symbol(name).bank, "addr": ctx.symbol(name).address}
                              for name in specification["point_symbols"]},
            "rom_bank_guard": {"symbol": "hROMBank", "addr": ctx.symbol("hROMBank").address,
                               "expected": symbol.bank, "required": symbol.bank != 0},
            "source_evidence": evidence,
        }
    for signal, obligation in specs["inventory"].items():
        actual = {name for name, site in sites.items() if site["signal"] == signal}
        if actual != set(obligation["sites"]) or not obligation["remaining"]:
            raise ValueError(f"{signal}: inventory does not match candidate sites or lacks open obligation")
    for site in sites.values():
        prior = site["guards"].get("requires_prior")
        if prior and (not prior.get("site_ids") or set(prior["site_ids"]) - set(sites)
                      or prior.get("consume_once") is not True):
            raise ValueError("missing or invalid prior-site lifecycle guard")
    inventory = {signal: {**obligation,
                         "source_status": "CANDIDATE" if obligation["sites"] else "OPEN",
                         "physical_status": "OPEN"}
                 for signal, obligation in specs["inventory"].items()}
    return {"schema": "gen2-engine-signals-v1", "generator": "tools/gen_gen2_engine_signals.py",
            "source": ctx.source_record(), "specs_sha256": hashlib.sha256(encoded_json(specs)).hexdigest(),
            "evidence_level": "SOURCE", "runtime_admission": "NOT_GRANTED", "f3_complete": False,
            "titles": {ctx.title: {"sites": sites, "inventory": inventory}},
            "source_files": {path: hashlib.sha256(value.encode()).hexdigest()
                             for path, value in sorted(cache.items())}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        specs = read_specs(args.root / SPEC_PATH)
        outputs = {args.root / f"data/games/gen2_{title}/engine_signals.json":
                   encoded_json(generate_pack(load_context(title, root=args.root), specs))
                   for title in ARTIFACTS}
        if args.check:
            for path, data in outputs.items():
                if path.read_bytes() != data:
                    raise ValueError(f"stale engine-site pack: {path}")
        else:
            for path, data in outputs.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        print(f"Gen 2 engine sites: {len(outputs)} packs {'checked' if args.check else 'generated'}; runtime/F3 OPEN")
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"engine-site generation refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
