"""C4-LG/C4-LG2/E2-SYMS: lua/tests/gen3_title_syms.lua's per-title addresses.

For firered/leafgreen, the address the module hands a caller must be exactly the Nth (by
ascending address) occurrence of that entry's symbol in that title's .sym file, plus `offset`,
with the Thumb bit (|1) applied last when `thumb` is set. radical_red has no .sym file (RR is a
hand-patched hack of the FR ROM, not a separate pret source tree), so instead every entry that
carries a radical_red value must carry a non-empty `rr_source` citation, and for_title must
never error for a missing entry -- it must omit it, so a caller sees a plain nil rather than a
load-time crash (card C4-LG2: the exact failure a live RR duo hit). No emulator, no ROM -- the
.sym files and the Lua table are the whole input.

emerald (E2-SYMS) DOES have its own pret .sym (a separate decomp, not a patched FR ROM), so
every `emerald` value is checked the same way firered/leafgreen are -- via `emerald_symbol`/
`emerald_occurrence` when an entry sets them (a rename or a shifted duplicate-symbol index),
else falling back to `symbol`/`occurrence`. An entry with `emerald = nil` (no Emerald equivalent)
is asserted against an explicit expected list, not merely tolerated.
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
    "emerald": ROOT / "data/gen3/pret/pokeemerald.sym",
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


FR_LG_TITLES = ("firered", "leafgreen")


def test_every_entry_present_for_firered_and_leafgreen(entries):
    """Unlike emerald, FR/LG never carries a deliberate nil -- both are the same pret source
    tree, so a title-invariant name difference should not happen."""
    for name, e in entries.items():
        for title in FR_LG_TITLES:
            assert e.get(title) is not None, f"{name}: no {title} address"


@pytest.mark.parametrize("title", sorted(SYM_PATHS))
def test_every_entry_matches_its_symbol(entries, sym_tables, title):
    """emerald uses `emerald_symbol`/`emerald_occurrence` when an entry sets them (a rename, or a
    duplicate-symbol index that shifted because Emerald's link order differs), else falls back to
    `symbol`/`occurrence` -- and an entry with no emerald value (nil) is skipped here, not failed;
    test_every_emerald_nil_is_the_expected_list is the falsifier for exactly which ones are nil."""
    table = sym_tables[title]
    bad = []
    for name, e in entries.items():
        if title not in e or e[title] is None:
            continue
        symbol = e.get(f"{title}_symbol") or e["symbol"]
        addrs = table.get(symbol)
        if not addrs:
            bad.append(f"{name}: symbol {symbol} not found in {title}.sym")
            continue
        occurrence = int(e.get(f"{title}_occurrence", e.get("occurrence", 0)))
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
            value = e.get(title)
            if value is None:
                assert name not in got, f"{name}/{title}: unproven but present in for_title output"
            else:
                assert got[name] == value, f"{name}/{title}: for_title mismatch"


def test_for_title_refuses_an_unknown_title():
    lua = LuaRuntime(unpack_returned_tuples=True)
    mod = lua.execute(f'return dofile("{SYMS_SCRIPT.as_posix()}")')
    from lupa import LuaError
    with pytest.raises(LuaError):
        mod.for_title("ruby")   # a real Gen 3 title, but not one this module knows
    with pytest.raises(LuaError):
        mod.for_title(None)


# ── radical_red (card C4-LG2): no .sym file, proof by citation, missing entries OMITTED ────────


def test_for_title_never_errors_for_radical_red(entries):
    """The exact failure a live RR duo hit: gen3_scripted_play.lua dofiles this module with
    SLINK_GEN3_TITLE="radical_red" and must not die before writing a single log line."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    mod = lua.execute(f'return dofile("{SYMS_SCRIPT.as_posix()}")')
    out = mod.for_title("radical_red")
    got = {k: out[k] for k in out}
    proven = {name: e["radical_red"] for name, e in entries.items() if e.get("radical_red") is not None}
    assert proven, "no radical_red entries at all -- something regressed the citations below"
    assert got == proven, "for_title('radical_red') must return exactly the proven entries"
    # every OTHER entry (no radical_red value) must be silently absent, not nil-in-the-table.
    for name in entries:
        if name not in proven:
            assert name not in got, f"{name}: unproven for RR but present in for_title output"


def test_every_radical_red_value_has_a_citation(entries):
    for name, e in entries.items():
        rr = e.get("radical_red")
        if rr is None:
            assert not e.get("rr_source"), f"{name}: rr_source set but no radical_red value"
            continue
        source = e.get("rr_source")
        assert isinstance(source, str) and source.strip(), f"{name}: radical_red set but no rr_source"
        assert any(source.startswith(p) for p in (
            "old-client RR (production-tested):", "docs/gen3/research/", "ROM byte anchor",
        )), f"{name}: rr_source does not look like one of the card's evidence tiers: {source!r}"


def test_no_radical_red_value_cites_this_table_itself(entries):
    """G5-RR-BATTERY-2 (OMP review of 156a521f): an rr_source naming gen3_title_syms.lua is the
    table vouching for itself. The evidence must live in a committed note or a production-tested
    file; this rejects any self-citation."""
    for name, e in entries.items():
        source = e.get("rr_source") or ""
        assert "gen3_title_syms" not in source, f"{name}: rr_source cites the table itself: {source!r}"


def test_radical_red_citations_point_at_real_files(entries):
    """Every rr_source names a file that exists in this repo (a citation to a file that was
    never committed is not evidence)."""
    for name, e in entries.items():
        source = e.get("rr_source")
        if not source:
            continue
        m = re.search(r"(lua/[\w./]+\.lua|docs/[\w./-]+\.md)", source)
        assert m, f"{name}: rr_source names no lua/ or docs/ file: {source!r}"
        assert (ROOT / m.group(1)).is_file(), f"{name}: rr_source file does not exist: {m.group(1)}"


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


# ── emerald (card E2-SYMS): has its own .sym, so every value is checked, and nils are exact ────

# Genuinely no Emerald equivalent (a rewritten subsystem, or an FR/LG-only intro concept), each
# with a comment in the Lua table citing the pret source that shows there is no 1:1 symbol.
EXPECTED_EMERALD_NILS = {
    "BAG_MENU_STATE_ADDR",          # gBagMenu is a differently-typed heap pointer, not a rename
    "TASK_ANIMATE_WIN0V",           # pocket-switch scroll runs inline, no sub-task spawned
    "TASK_OAKSPEECH_GENDER_INPUT",  # Emerald's intro is Birch's speech, not Oak's
    "TASK_START_MENU_HANDLE_INPUT", # gMenuCallback function-pointer design, not gTasks-based
    "START_CB_HANDLE_INPUT",        # same gMenuCallback design
    "START_CB_SAVE1",               # same gMenuCallback design
    "START_CB_SAVE2",               # same gMenuCallback design
}

# Renamed (SendMonToPC -> CopyMonToPC style): same function/variable, different pret name.
EXPECTED_EMERALD_RENAMES = {
    "PC_STORAGE_PTR": "sStorage",                       # gStorage -> sStorage
    "PC_MULTICHOICE": "Task_HandleMultichoiceInput",    # Task_MultichoiceMenu_HandleInput -> ...
    "TASK_YES_NO_MENU": "Task_HandleYesNoInput",        # Task_YesNoMenu_HandleInput -> ...
}


def test_every_emerald_nil_is_the_expected_list(entries):
    """card E2-SYMS: 'the test asserts the explicit nil list' -- not just tolerates nils, pins
    exactly which entries have none and (by omission) that every other entry DOES have one."""
    actual_nils = {name for name, e in entries.items() if e.get("emerald") is None}
    assert actual_nils == EXPECTED_EMERALD_NILS


def test_emerald_renames_are_declared_and_differ_from_the_fr_symbol(entries):
    for name, expected_symbol in EXPECTED_EMERALD_RENAMES.items():
        e = entries[name]
        assert e.get("emerald_symbol") == expected_symbol, name
        assert e["emerald"] is not None, f"{name}: renamed but has no emerald address"
        assert e["emerald_symbol"] != e["symbol"], f"{name}: emerald_symbol equals symbol, not a rename"


def test_no_other_entry_sets_an_emerald_symbol_or_occurrence_override(entries):
    """Overrides are the exception (a rename or a shifted duplicate index), not the default: every
    entry outside the two known exception sets uses the plain `symbol`/`occurrence` for emerald
    too, exactly like firered/leafgreen do."""
    exceptions_symbol = set(EXPECTED_EMERALD_RENAMES)
    exceptions_occurrence = {"PC_MENU_BASE"}
    for name, e in entries.items():
        if name not in exceptions_symbol:
            assert e.get("emerald_symbol") is None, f"{name}: unexpected emerald_symbol override"
        if name not in exceptions_occurrence:
            assert e.get("emerald_occurrence") is None, f"{name}: unexpected emerald_occurrence override"


def test_pc_menu_base_emerald_occurrence_is_pinned(entries, sym_tables):
    """pokeemerald.sym has one more static `sMenu` than FR/LG (data/gen3/pret/pokeemerald.sym has
    3 hits, sizes 4/4/0xC -- only the 0xC one is menu.c's struct Menu, matching FR/LG's
    occurrence-1 symbol by SIZE as well as by address), so plain `occurrence=1` would silently
    pick the wrong static var for Emerald without the override."""
    e = entries["PC_MENU_BASE"]
    assert e.get("emerald_occurrence") == 2
    addrs = sym_tables["emerald"]["sMenu"]
    assert len(addrs) == 3
    assert addrs[1] != int(e["emerald"]), "occurrence=1 (FR/LG's index) must NOT match emerald's value"
    assert addrs[2] == int(e["emerald"])
