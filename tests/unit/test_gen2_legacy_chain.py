"""Guard known import/load spellings of the retired Gen 2 harness chain.

This is a source guard, not a proof about arbitrary computed module names.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RETIRED = {
    "memory_gb", "games.gen2_crystal", "gen2_crystal_client",
    "slink_gen2", "gen2_playthrough",
}
LUA_TOKEN = re.compile(
    r"--\[(?P<eq>=*)\[.*?\](?P=eq)\]|--[^\n]*|"
    r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"",
    re.DOTALL,
)
LUA_LOAD = re.compile(
    r"\b(?:require|dofile|loadfile|load)\s*(?:\([^)]*|['\"][^\n]*)"
    r"|\b(?:module|client|play)\s*=\s*['\"][^\n]*"
)
STRING = re.compile(r"(['\"])(.*?)\1")


def retired_name(name):
    name = name.replace("\\", "/").removesuffix(".lua").removesuffix(".py")
    dotted = name.strip("/").replace("/", ".")
    return any(dotted == old or dotted.endswith("." + old) for old in RETIRED)


def runtime_imports(source, suffix):
    """Return line-numbered known runtime dependencies; ignore prose/comments."""
    hits = []
    if suffix == ".py":
        for node in ast.walk(ast.parse(source)):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
                names += [(node.module or "") + "." + alias.name for alias in node.names]
            elif isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if (name in {"import_module", "__import__"} and node.args
                        and isinstance(node.args[0], ast.Constant)):
                    names = [node.args[0].value]
                elif (isinstance(func, ast.Attribute) and name in {"execute", "eval"}
                      and node.args and isinstance(node.args[0], ast.Constant)
                      and isinstance(node.args[0].value, str)):
                    hits.extend((node.lineno + line - 1, imported)
                                for line, imported in runtime_imports(node.args[0].value, ".lua"))
            elif isinstance(node, ast.Dict):
                # e2e_duo resolves the play descriptor through import_module.
                names = [value.value for key, value in zip(node.keys, node.values, strict=True)
                         if isinstance(key, ast.Constant) and key.value == "play"
                         and isinstance(value, ast.Constant)]
            hits.extend((node.lineno, name) for name in names
                        if isinstance(name, str) and retired_name(name))
    else:
        source = LUA_TOKEN.sub(
            lambda m: re.sub(r"[^\n]", " ", m[0]) if m[0].startswith("--") else m[0],
            source,
        )
        for match in LUA_LOAD.finditer(source):
            for literal in STRING.finditer(match[0]):
                if retired_name(literal[2]):
                    hits.append((source.count("\n", 0, match.start()) + 1, literal[2]))
    return hits


@pytest.mark.parametrize("source,suffix", [
    ("import gen2_playthrough as play", ".py"),
    ("from games import gen2_crystal", ".py"),
    ("from gen2_playthrough import build", ".py"),
    ('importlib.import_module("gen2_playthrough")', ".py"),
    ('__import__("gen2_playthrough")', ".py"),
    ('''lua.execute('require("memory_gb")')''', ".py"),
    ('''lua.eval('require("games.gen2_crystal")')''', ".py"),
    ('GAMES = {"gen2": {"play": "gen2_playthrough"}}', ".py"),
    ('local M = require("memory_gb")', ".lua"),
    ('local M = require "games.gen2_crystal"', ".lua"),
    ('dofile(ROOT .. "/lua/clients/gen2_crystal_client.lua")', ".lua"),
    ('dofile(\n ROOT ..\n "/lua/slink_gen2.lua"\n)', ".lua"),
    ('loadfile(ROOT .. "/lua/slink_gen2.lua")()', ".lua"),
    ('load("slink_gen2")', ".lua"),
    ('module = "games.gen2_crystal",', ".lua"),
])
def test_guard_detects_runtime_import(source, suffix):
    assert runtime_imports(source, suffix)


@pytest.mark.parametrize("source,suffix", [
    ('# import gen2_playthrough\n"historical import gen2_playthrough"', ".py"),
    ('"""from gen2_playthrough import build"""', ".py"),
    ('''lua.execute('-- require("memory_gb")')''', ".py"),
    ('''lua.eval('require("memory_gba")')''', ".py"),
    ('import memory_gba', ".py"),
    ('-- require("memory_gb")\nlocal M = require("memory_gba")', ".lua"),
    ('--[=[\nrequire("memory_gb")\n]=]\nrequire("memory_gba")', ".lua"),
    ('local path = "data/games/gen2_crystal/profile.json"', ".lua"),
])
def test_guard_ignores_history_and_gen3(source, suffix):
    assert runtime_imports(source, suffix) == []


def test_no_legacy_gen2_runtime_imports():
    hits = []
    for directory in ("tools", "tests", "lua"):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.suffix not in {".py", ".lua"}:
                continue
            for line, name in runtime_imports(path.read_text(encoding="utf-8-sig"), path.suffix):
                hits.append(f"{path.relative_to(ROOT).as_posix()}:{line}: {name}")
    assert not hits, "Retired Gen 2 runtime dependencies:\n" + "\n".join(hits)
