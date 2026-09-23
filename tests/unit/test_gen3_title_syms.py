"""C4-LG: lua/tests/gen3_title_syms.lua's per-title addresses against the pret .sym files.

For every entry, the address the module hands a caller for a title must be exactly the Nth
(by ascending address) occurrence of that entry's symbol in that title's .sym file, plus
`offset`, with the Thumb bit (|1) applied last when `thumb` is set. No emulator, no ROM --
the .sym files and the Lua table are the whole input.
"""
import re
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
SYMS_SCRIPT = ROOT / "lua/tests/gen3_title_syms.lua"
SYM_PATHS = {
    "firered": ROOT / "data/gen3/pret/pokefirered.sym",
    "leafgreen": ROOT / "data/gen3/pret/pokeleafgreen.sym",
}

_LINE = re.compile(r"^([0-9a-fA-F]{8}) [gl] [0-9a-fA-F]{8} (\S+)$")


def _parse_sym(path):
    """name -> [addresses...] in ascending address order (the file is already sorted, sorted()
    is just the falsifiable statement of that, not a hope)."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        addr, name = int(m.group(1), 16), m.group(2)
        out.setdefault(name, []).append(addr)
    for name in out:
        out[name].sort()
    return out


@pytest.fixture(scope="module")
def sym_tables():
    return {title: _parse_sym(p) for title, p in SYM_PATHS.items()}


@pytest.fixture(scope="module")
def entries():
    lua = LuaRuntime(unpack_returned_tuples=True)
    mod = lua.execute(f'return dofile("{SYMS_SCRIPT.as_posix()}")')
    out = {}
    for name, e in mod.entries.items():
        out[name] = {k: e[k] for k in e}
    return out


def test_every_entry_present_for_both_titles(entries):
    for name, e in entries.items():
        for title in SYM_PATHS:
            assert e.get(title) is not None, f"{name}: no {title} address"


@pytest.mark.parametrize("title", sorted(SYM_PATHS))
def test_every_entry_matches_its_symbol(entries, sym_tables, title):
    table = sym_tables[title]
    bad = []
    for name, e in entries.items():
        symbol = e["symbol"]
        addrs = table.get(symbol)
        if not addrs:
            bad.append(f"{name}: symbol {symbol} not found in {title}.sym")
            continue
        occurrence = int(e.get("occurrence", 0))
        if occurrence >= len(addrs):
            bad.append(f"{name}: symbol {symbol} has only {len(addrs)} occurrence(s) in "
                       f"{title}.sym, wanted occurrence {occurrence}")
            continue
        expected = addrs[occurrence] + int(e.get("offset", 0))
        if e.get("thumb"):
            expected |= 1
        got = int(e[title])
        if got != expected:
            bad.append(f"{name} ({title}): table has {got:#x}, symbol {symbol}"
                       f"[{occurrence}] + offset gives {expected:#x}")
    assert not bad, "\n".join(bad)


def test_for_title_returns_every_entry_by_name(entries):
    lua = LuaRuntime(unpack_returned_tuples=True)
    mod = lua.execute(f'return dofile("{SYMS_SCRIPT.as_posix()}")')
    for title in SYM_PATHS:
        out = mod.for_title(title)
        got = {k: out[k] for k in out}
        for name, e in entries.items():
            assert got[name] == e[title], f"{name}/{title}: for_title mismatch"


def test_for_title_refuses_an_unknown_title():
    lua = LuaRuntime(unpack_returned_tuples=True)
    mod = lua.execute(f'return dofile("{SYMS_SCRIPT.as_posix()}")')
    from lupa import LuaError
    with pytest.raises(LuaError):
        mod.for_title("radical_red")
    with pytest.raises(LuaError):
        mod.for_title(None)


def test_symbols_needing_occurrence_actually_have_a_duplicate(entries, sym_tables):
    """A nonzero `occurrence` is only meaningful (and only trustworthy) against a symbol name
    the .sym file really does repeat -- otherwise it is silently picking apart from nothing."""
    for name, e in entries.items():
        occ = int(e.get("occurrence", 0))
        if occ == 0:
            continue
        for title, table in sym_tables.items():
            addrs = table.get(e["symbol"], [])
            assert len(addrs) > occ, (
                f"{name}: occurrence={occ} but {e['symbol']} has only {len(addrs)} hit(s) "
                f"in {title}.sym")
