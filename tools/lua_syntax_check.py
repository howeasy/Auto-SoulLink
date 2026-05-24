"""Syntax-check every lua/**/*.lua file using lupa (Lua 5.5 runtime).

SLink's BizHawk Lua targets 5.5; the system `luac` on this box is 5.1 and
rejects 5.5-only syntax. This script uses lupa's embedded 5.5 runtime to
parse-load every file (no execution) and reports any errors.

Exit 0 on clean, 1 on any syntax error.
"""
from __future__ import annotations
import sys
from pathlib import Path

import lupa

ROOT = Path(__file__).resolve().parent.parent
LUA_DIR = ROOT / "lua"


def main() -> int:
    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
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
