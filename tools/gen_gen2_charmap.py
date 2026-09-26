"""Pinned Gen 2 native text facts; this is not a HUD sanitizer or identity codec.

Encoding aliases are retained with their font/language context. `glyphs` uses the
first English declaration, never a last-writer override from another font/kana.
Crystal's explicitly named Unown/ASCII charmaps are outside the default text map.
The small source/table helpers here are shared by the four text-pack generators.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import operator
import re
import sys
from pathlib import Path

if __package__:
    from .gen2_source_data import ROOT, load_context, rom_offset
else:
    from gen2_source_data import ROOT, load_context, rom_offset

TITLES = ("crystal", "gold", "silver")


def code(line: str) -> str:
    """Remove ASM comments, respecting semicolons inside string literals."""
    quoted = escaped = False
    for i, char in enumerate(line):
        if char == '"' and not escaped:
            quoted = not quoted
        if char == ";" and not quoted:
            return line[:i].strip()
        escaped = char == "\\" and not escaped
    return line.strip()


def source_lines(text: str) -> list[str]:
    lines, macro = [], False
    for raw in text.splitlines():
        line = code(raw)
        if re.match(r"MACRO\??\s", line):
            if macro:
                raise ValueError("nested source macro")
            macro = True
        elif line == "ENDM":
            if not macro:
                raise ValueError("unmatched ENDM")
            macro = False
        elif line and not macro:
            lines.append(line)
    if macro:
        raise ValueError("unterminated source macro")
    return lines


def integer(expression: str, values: dict[str, int] | None = None) -> int:
    expression = re.sub(r"\$([0-9a-fA-F]+)", r"0x\1", expression)
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                  ast.Div: operator.floordiv, ast.FloorDiv: operator.floordiv,
                  ast.BitOr: operator.or_, ast.BitAnd: operator.and_, ast.LShift: operator.lshift}

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name) and node.id in (values or {}):
            return values[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return (-1 if isinstance(node.op, ast.USub) else 1) * visit(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            return operations[type(node.op)](visit(node.left), visit(node.right))
        raise ValueError(f"unsupported source integer: {expression}")

    try:
        return visit(ast.parse(expression, mode="eval").body)
    except (SyntaxError, ZeroDivisionError) as exc:
        raise ValueError(f"invalid source integer: {expression}") from exc


def constants(text: str) -> dict[str, int]:
    """Strict const/rs integer subset used by the pinned text-table constants."""
    values, current, step, offset = {}, 0, 1, 0
    for line in source_lines(text):
        env = {**values, "const_value": current, "_RS": offset}
        op, _, rest = line.partition(" ")
        if op == "const_def":
            parts = [part.strip() for part in rest.split(",")] if rest else ["0"]
            current = integer(parts[0], env)
            step = integer(parts[1], env) if len(parts) == 2 else 1
        elif op == "const_next":
            current = integer(rest, env)
        elif op == "const_skip":
            current += step * integer(rest or "1", env)
        elif op in ("const", "shift_const"):
            if rest in values or not re.fullmatch(r"\w+", rest):
                raise ValueError(f"duplicate/invalid constant: {rest}")
            values[rest] = current if op == "const" else 1 << current
            current += step
        elif line == "rsreset":
            offset = 0
        elif op == "rsset":
            offset = integer(rest, env)
        elif match := re.fullmatch(r"DEF\s+(\w+)\s+(rb|rw)", line):
            values[match[1]] = offset
            offset += 1 if match[2] == "rb" else 2
        elif match := re.fullmatch(r"DEF\s+(\w+)\s+(?:EQU|=)\s+(.+)", line):
            values[match[1]] = integer(match[2], env)
        else:
            raise ValueError(f"unsupported constants source: {line}")
    return values


def parse_charmap(text: str) -> dict:
    aliases, encoding, primary = {}, {}, {}
    context, named, excluded = "english_controls", False, []
    for number, raw in enumerate(text.splitlines(), 1):
        if raw.startswith("; Japanese control"):
            context = "japanese_controls"
        elif raw.startswith("; Japanese kana"):
            context = "japanese_kana"
        elif raw.startswith("; Actual characters"):
            context = raw.removeprefix("; Actual characters ").strip()
        line = code(raw)
        if line == "pushc":
            if named:
                raise ValueError("nested named charmap")
            named = True
            continue
        if line == "popc":
            if not named:
                raise ValueError("unmatched popc")
            named = False
            continue
        if named:
            if line.startswith("newcharmap "):
                excluded.append(line.split()[1])
            continue
        if not line:
            continue
        match = re.fullmatch(r'charmap\s+("(?:\\.|[^"\\])*")\s*,\s*(\$[0-9a-fA-F]+|\d+)', line)
        if not match:
            raise ValueError(f"unsupported default charmap line {number}: {line}")
        token, value = json.loads(match[1]), integer(match[2])
        if not token or not 0 <= value <= 255 or token in encoding:
            raise ValueError(f"invalid/duplicate charmap token on line {number}")
        encoding[token] = value
        aliases.setdefault(value, []).append({"text": token, "context": context, "line": number})
        if not context.startswith("japanese"):
            primary.setdefault(value, token)
    if named or encoding.get("@") != 0x50:
        raise ValueError("default text terminator missing/changed or unclosed charmap")
    return {"terminator": 0x50, "encoding": encoding,
            "glyphs": {i: primary.get(i, f"<${i:02X}>") for i in range(256)},
            "aliases": aliases, "excluded_named_charmaps": excluded,
            "context_dependent_bytes": sorted(i for i, rows in aliases.items() if len(rows) > 1)}


def encode(text: str, encoding: dict[str, int]) -> bytes:
    tokens, output = sorted(encoding, key=lambda token: (-len(token), token)), bytearray()
    while text:
        token = next((token for token in tokens if text.startswith(token)), None)
        if token is None:
            raise ValueError(f"unmapped native text near {text!r}")
        output.append(encoding[token])
        text = text[len(token):]
    return bytes(output)


def table_bytes(ctx, symbol: str, size: int) -> tuple[int, bytes]:
    bank, address = ctx.symbol(symbol)
    offset = rom_offset(bank, address)
    bank_end = 0x4000 if bank == 0 else 0x8000
    if size < 0 or address + size > bank_end or offset + size > len(ctx.rom):
        raise ValueError(f"{symbol}: table crosses ROM bank/file bounds")
    return offset, ctx.rom[offset:offset + size]


def verify_table(ctx, symbol: str, expected: bytes) -> int:
    offset, actual = table_bytes(ctx, symbol, len(expected))
    if actual != expected:
        raise ValueError(f"{symbol}: source/ROM byte mismatch")
    return offset


def name_list(ctx, path: str, symbol: str, length_constant: str, count: int) -> tuple[list[str], dict]:
    chars = parse_charmap(ctx.read_source("constants/charmap.asm"))
    lengths = constants(ctx.read_source("constants/text_constants.asm").split("; GetName types")[0])
    limit = lengths[length_constant] - 1
    names = []
    for line in source_lines(ctx.read_source(path)):
        if line == symbol + "::" or line == f"list_start {length_constant} - 1":
            continue
        if line.startswith("assert_list_length "):
            continue
        match = re.fullmatch(r'li\s+("(?:\\.|[^"\\])*")', line)
        if not match:
            raise ValueError(f"unsupported {symbol} source: {line}")
        value = json.loads(match[1])
        encoded = encode(value, chars["encoding"])
        if not encoded or len(encoded) > limit or chars["terminator"] in encoded:
            raise ValueError(f"{symbol}: invalid name length/terminator")
        names.append(value)
    if len(names) != count:
        raise ValueError(f"{symbol}: {len(names)} rows != {count}")
    raw = b"".join(encode(name + "@", chars["encoding"]) for name in names)
    offset = verify_table(ctx, symbol, raw)
    return names, {"symbol": symbol, "offset": offset, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def json_bytes(document: dict) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def run_cli(argv, build, filename: str, renderer=json_bytes) -> int:
    parser = argparse.ArgumentParser(description=build.__doc__)
    parser.add_argument("--title", choices=TITLES, action="append")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        outputs = {args.root / "data/games" / f"gen2_{title}" / filename:
                   renderer(build(load_context(title, root=args.root)))
                   for title in dict.fromkeys(args.title or TITLES)}
        if args.check:
            for path, expected in outputs.items():
                if not path.is_file() or path.read_bytes() != expected:
                    raise ValueError(f"generated pack differs/missing: {path}")
        else:
            for path, data in outputs.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        print(f"{filename}: {len(outputs)} title(s) {'verified' if args.check else 'generated'}")
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def build(ctx) -> dict:
    """Generate contextual default-charmap facts from the verified Gen 2 source."""
    document = parse_charmap(ctx.read_source("constants/charmap.asm"))
    lengths = constants(ctx.read_source("constants/text_constants.asm").split("; GetName types")[0])
    return {"schema": "gen2-charmap-v1", "generator": "tools/gen_gen2_charmap.py",
            "source": ctx.source_record(), "title": ctx.title,
            "scope": "native default text encoding; font/language aliases retained; no HUD policy",
            **document, "lengths": {key.lower(): value for key, value in lengths.items()}}


def render_lua(document: dict) -> bytes:
    def render(value, depth=0):
        if isinstance(value, dict):
            entries = [(f"[{key}]" if type(key) is int else f"[{json.dumps(key, ensure_ascii=False)}]", val)
                       for key, val in value.items()]
        elif isinstance(value, list):
            entries = [(f"[{i}]", val) for i, val in enumerate(value, 1)]
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif value is None:
            return "nil"
        else:
            return json.dumps(value, ensure_ascii=False)
        indent = "  " * (depth + 1)
        return "{\n" + "".join(f"{indent}{key} = {render(val, depth + 1)},\n" for key, val in entries) + "  " * depth + "}"
    return ("-- GENERATED native text facts; raw bytes remain authoritative.\nreturn " + render(document) + "\n").encode("utf-8")


def main(argv=None) -> int:
    return run_cli(argv, build, "charmap.lua", render_lua)


if __name__ == "__main__":
    raise SystemExit(main())
