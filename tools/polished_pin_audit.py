"""Audit overlay-derived executable pins; never rewrite historical receipts.

Run ``python tools/polished_pin_audit.py`` after rebuilding the overlay. Exit 1
means stale executable pins; exit 2 means missing/unreadable audit inputs. Use
--scan-root for a scratch source tree while --root supplies facts and git history.

Hashes and UPS sizes come from provenance and its git log -p history. Counts and
bank-$7E symbols require the pack/symbol history (provenance has neither). Unknown
hashes, synthetic addresses and unrecognised expressions are not proof of drift:
UNCLASSIFIED rows require human review. This is a literal audit, not data-flow
analysis: computed/imported pins, aliases for count expressions, and standalone
addresses without a bank or symbol cannot be attributed reliably. Comments and
docstrings are not executable; receipt files never fail the gate. FIXTURE-IDENTITY
marks non-admission SHA1 metadata in modules that verify a fixture's SHA256.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = "data/polished/overlay_provenance.json"
PACK = "data/games/polished_crystal/engine_signals.json"
SYMBOLS = "data/polished/polished_slink.sym"
PACKS = ("profile.json", "engine_signals.json", "write_checkpoint.json", "overlay/beacon.json")
PATTERNS = ("tests/unit/test_polished_*.py", "tests/unit/test_gen_polished_*.py",
            "tests/unit/test_upr_polished_*.py", "tools/polished_live/*.py",
            "tools/build_polished_companion.py")
RECEIPTS = "tests/fixtures/polished/receipts"
HASH = re.compile(r"(?<![0-9a-fA-F])(?:[0-9a-fA-F]{64}|[0-9a-fA-F]{40})(?![0-9a-fA-F])")
SYM = re.compile(r"^7[eE]:([0-9a-fA-F]{4})\s+(\S+)", re.MULTILINE)
COUNTS = ("site_count", "resolved_count", "unresolved_count")


@dataclass(frozen=True)
class Pin:
    file: str
    line: int
    status: str
    kind: str
    value: str


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout


def history(root: Path, path: str) -> str:
    diff = git(root, "log", "-p", "--format=", "--", path)
    return "\n".join(line[1:] for line in diff.splitlines()
                     if line[:1] in ("+", "-", " ") and not line.startswith(("+++", "---")))


def symbol_values(text: str) -> dict[str, int]:
    return {name: int(addr, 16) for addr, name in SYM.findall(text)}


class Facts:
    def __init__(self, root: Path):
        provenance_text = (root / PROVENANCE).read_text(encoding="utf-8")
        provenance = json.loads(provenance_text)
        old = history(root, PROVENANCE)
        pack_texts = [(root / "data/games/polished_crystal" / p).read_text(encoding="utf-8")
                      for p in PACKS]
        self.hashes = {m.lower() for text in [provenance_text, *pack_texts] for m in HASH.findall(text)}
        self.old_hashes = {m.lower() for m in HASH.findall(old)}
        self.ups_size = provenance["output"]["ups"]["size"]
        self.old_sizes = {int(n) for block in re.findall(r'"ups":\s*\{([^}]+)', old)
                          for n in re.findall(r'"size":\s*(\d+)', block)}
        pack = json.loads((root / PACK).read_text(encoding="utf-8"))
        self.counts = {key: pack[key] for key in COUNTS}
        self.counts["companion_overlay_spans"] = len(pack["companion_overlay_spans"])
        self.old_counts = {key: set() for key in self.counts}
        # Reconstruct JSON snapshots: counting diff lines cannot recover array lengths.
        for revision in git(root, "log", "--format=%H", "--", PACK).splitlines():
            previous = json.loads(git(root, "show", f"{revision}:{PACK}"))
            for key in COUNTS:
                if key in previous:
                    self.old_counts[key].add(previous[key])
            if "companion_overlay_spans" in previous:
                self.old_counts["companion_overlay_spans"].add(len(previous["companion_overlay_spans"]))
        self.symbols = symbol_values((root / SYMBOLS).read_text(encoding="utf-8"))
        self.old_symbols: dict[str, set[int]] = {}
        for addr, name in SYM.findall(history(root, SYMBOLS)):
            self.old_symbols.setdefault(name, set()).add(int(addr, 16))

    def classify(self, kind: str, value: str | int, symbol: str | None = None) -> str:
        if kind == "hash":
            current, old = self.hashes, self.old_hashes
        elif kind == "ups_size":
            current, old = {self.ups_size}, self.old_sizes
        elif kind == "bank:addr":
            current = {self.symbols[symbol]} if symbol in self.symbols else set(self.symbols.values())
            old = self.old_symbols.get(symbol, set()) if symbol else set().union(*self.old_symbols.values())
        else:
            current, old = {self.counts[kind]}, self.old_counts[kind]
        return "CURRENT" if value in current else "STALE" if value in old else "UNCLASSIFIED"


def literal(node: ast.AST):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def count_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Subscript) and literal(node.slice) in COUNTS:
        return literal(node.slice)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "len" and len(node.args) == 1
            and isinstance(node.args[0], ast.Subscript)
            and literal(node.args[0].slice) == "companion_overlay_spans"):
        return "companion_overlay_spans"
    return None


def fixture_identities(tree: ast.Module, nodes: list[ast.AST]) -> set[ast.AST]:
    """Conservatively recognise fixture checks and unused/diagnostic SHA1 metadata.

    Follow only unique simple assignments; ambiguous names are not exemptions.
    A SHA1 used in a comparison, returned, passed to a function, or aliased is
    never exempted. Fixture path and SHA256 comparison must be visible in AST.
    """
    def bindings_for(statements):
        bindings: dict[str, list[ast.AST]] = {}
        for statement in statements:
            if isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        bindings.setdefault(target.id, []).append(statement.value)
        return bindings

    assignments = bindings_for(nodes)
    globals_ = bindings_for(tree.body)
    parents = {child: node for node in nodes for child in ast.iter_child_nodes(node)}

    def expanded(node, bindings, seen=frozenset()):
        yield node
        if isinstance(node, ast.Name) and node.id not in seen:
            values = bindings.get(node.id, [])
            if len(values) == 1:
                yield from expanded(values[0], bindings, seen | {node.id})
        for child in ast.iter_child_nodes(node):
            yield from expanded(child, bindings, seen)

    fixture_verified = False
    for node in nodes:
        if not isinstance(node, ast.Compare):
            continue
        scope = node
        while scope in parents and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = parents[scope]
        bindings = dict(globals_)
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bindings.update(bindings_for(ast.walk(scope)))
        parts = list(expanded(node, bindings))
        strings = [part.value for part in parts if isinstance(part, ast.Constant)
                   and isinstance(part.value, str)]
        path = "/".join(strings).replace("\\", "/")
        digest = any(re.fullmatch(r"[0-9a-fA-F]{64}", value) for value in strings)
        sha256 = any(isinstance(part, ast.Attribute) and part.attr == "sha256" for part in parts)
        if "tests/fixtures/" in path and digest and sha256:
            fixture_verified = True
            break
    if not fixture_verified:
        return set()
    identities = set()
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target, value = statement.targets[0], statement.value
        if not (isinstance(target, ast.Name) and isinstance(value, ast.Constant)
                and isinstance(value.value, str) and re.fullmatch(r"[0-9a-fA-F]{40}", value.value)):
            continue
        if len(assignments[target.id]) != 1:
            continue
        uses = [node for node in nodes if isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load) and node.id == target.id]
        diagnostic = True
        for use in uses:
            parent = parents.get(use)
            if not isinstance(parent, ast.FormattedValue):
                diagnostic = False
                break
            while parent in parents and not isinstance(parent, (ast.Call, ast.Compare, ast.Assign, ast.Return)):
                parent = parents[parent]
            if not (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute)
                    and isinstance(parent.func.value, ast.Name) and parent.func.value.id == "pytest"
                    and parent.func.attr in ("skip", "fail")):
                diagnostic = False
                break
        if diagnostic:
            identities.add(value)
    return identities


def scan_python(path: Path, relative: str, facts: Facts) -> list[Pin]:
    text = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(text, filename=str(path))
    rows: set[Pin] = set()
    nodes = list(ast.walk(tree))
    identities = fixture_identities(tree, nodes)
    dictionary_values = {value for node in nodes if isinstance(node, ast.Dict) for value in node.values}
    docstrings = set()
    for node in nodes:
        if (isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.body and isinstance(node.body[0], ast.Expr)):
            value = node.body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                docstrings.add(value)

    def emit(node, kind, value, symbol=None):
        status = facts.classify(kind, value, symbol)
        if kind == "hash" and node in identities:
            status = "FIXTURE-IDENTITY"
        rendered = f"7e:{value:04x}" if kind == "bank:addr" else str(value)
        if symbol:
            rendered += f" ({symbol})"
        rows.add(Pin(relative, node.lineno, status, kind, rendered))

    def comparison(left, right):
        if isinstance(left, (ast.Tuple, ast.List)) and isinstance(right, (ast.Tuple, ast.List)):
            for a, b in zip(left.elts, right.elts, strict=False):
                comparison(a, b)
        key, value = count_key(left), literal(right)
        if key and type(value) is int:
            emit(right, key, value)
        expression = ast.get_source_segment(text, left) or ""
        if type(value) is int and "ups" in expression.lower() and (
                "size" in expression.lower() or expression.startswith("len(")):
            emit(right, "ups_size", value)

    for node in nodes:
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in docstrings:
            for match in HASH.finditer(node.value):
                emit(node, "hash", match.group().lower())
        elif isinstance(node, ast.Compare):
            for left, op, right in zip([node.left, *node.comparators], node.ops, node.comparators, strict=False):
                if isinstance(op, ast.Eq):
                    comparison(left, right)
                    comparison(right, left)
        elif isinstance(node, ast.Dict):
            values = {literal(k): v for k, v in zip(node.keys, node.values, strict=True) if k is not None
                      and isinstance(literal(k), (str, int))}
            if literal(values.get("bank", ast.Constant(None))) == 0x7E and "addr" in values:
                addr = literal(values["addr"])
                if type(addr) is int:
                    symbol = literal(values.get("symbol", ast.Constant(None)))
                    emit(values["addr"], "bank:addr", addr, symbol)
            for key, value in zip(node.keys, node.values, strict=True):
                pair = literal(value)
                if isinstance(pair, tuple) and len(pair) == 2 and pair[0] == 0x7E and type(pair[1]) is int:
                    emit(value, "bank:addr", pair[1], literal(key) if key else None)
        elif isinstance(node, ast.Tuple):
            pair = literal(node)
            # Named dictionary entries are handled above, preserving symbol identity.
            if (isinstance(pair, tuple) and len(pair) == 2 and pair[0] == 0x7E
                    and type(pair[1]) is int and node not in dictionary_values):
                emit(node, "bank:addr", pair[1])
    return sorted(rows, key=lambda r: (r.file, r.line, r.kind, r.value))


def audit(root: Path = ROOT, scan_root: Path | None = None) -> list[Pin]:
    facts = Facts(root)
    source = scan_root or root
    rows = []
    for path in sorted({p for pattern in PATTERNS for p in source.glob(pattern)}):
        rows.extend(scan_python(path, path.relative_to(source).as_posix(), facts))
    for path in sorted((source / RECEIPTS).rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        for line, content in enumerate(text.splitlines(), 1):
            for value in HASH.findall(content):
                rows.append(Pin(path.relative_to(source).as_posix(), line,
                                "HISTORICAL-RECEIPT", "hash", value.lower()))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="authoritative checkout and git history")
    parser.add_argument("--scan-root", type=Path, help="optional scratch source tree")
    args = parser.parse_args(argv)
    try:
        rows = audit(args.root, args.scan_root)
    except (OSError, ValueError, KeyError, SyntaxError, subprocess.CalledProcessError) as exc:
        print(f"Audit inputs unavailable: {exc}")
        return 2
    print("STATUS | FILE:LINE | KIND | VALUE")
    for row in rows:
        print(f"{row.status} | {row.file}:{row.line} | {row.kind} | {row.value}")
    stale = sum(row.status == "STALE" for row in rows)
    print(f"{len(rows)} pins; {stale} STALE executable pins")
    return int(stale > 0)


if __name__ == "__main__":
    raise SystemExit(main())
