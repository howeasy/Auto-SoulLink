"""Syntax-check every lua/**/*.lua file using lupa's Lua 5.4 runtime.

Pinned BizHawk 2.11.1 loads lua54.dll; the system `luac` may be older and
lupa's default runtime may be newer. Select the actual target explicitly to
parse-load every file (no execution) and reports any errors.

Exit 0 on clean, 1 on any syntax error.
"""
from __future__ import annotations

import sys
from pathlib import Path

from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parent.parent
LUA_DIR = ROOT / "lua"


def main() -> int:
    runtime = LuaRuntime(unpack_returned_tuples=True)
    check = runtime.eval(
        "function(code, name)\n"
        "  local fn, err = load(code, name)\n"
        "  if fn then return true, '' else return false, err end\n"
        "end"
    )
    files = sorted(LUA_DIR.rglob("*.lua"))
    errors: list[str] = []
    for path in files:
        code = path.read_text(encoding="utf-8-sig")
        ok, err = check(code, str(path.relative_to(ROOT)))
        if not ok:
            errors.append(f"{path.relative_to(ROOT)}: {err}")
    if errors:
        for e in errors:
            print(e)
        print(f"\n{len(errors)} file(s) with syntax errors "
              f"({len(files)} checked)")
        return 1
    print(f"OK: {len(files)} Lua files parsed cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
