"""docs/polished/RAM.md: every address cell in it must agree with the symbol files it cites.

RAM.md is prose maintained by hand, so its tables drift. This pins the mechanical part: for every
row that names a symbol in BOTH a vanilla and a Polished column, the two `bank:addr` cells must
equal what the cited symbol files say, and the stated verdict must follow from the two addresses and
the two names.

Sources, as RAM.md's own `## Sources` section declares them (`:9`-`:13`):
  * Polished — `data/polished/polishedcrystal.sym` (the in-repo copy of the release `.sym`), rgblink
    `BB:AAAA Name`.
  * vanilla — `data/games/gen2_crystal/profile.json` -> `titles.crystal.{ram, ram_bank, hram}`,
    which hold ABSOLUTE addresses; the bank is derived by RAM.md's own rule (`:18`): WRAM0
    `$C000-$CFFF` is bank `00`, WRAMX `$D000-$DFFF` is bank `01`, HRAM `$FFxx` is bank `00`.

Bank numbering, which RAM.md warns is NOT the same between the games (`:20`-`:22`), is why the
vanilla side is checked through the profile's absolute addresses rather than through a sym.

The struct-offset tables (§2.1 `party_struct`, §2.3 `battle_struct`, §2.6 `savemon_struct`) use
`+N` offsets rather than `bank:addr`; they are checked against
`server/adapters/polished_codec.py`'s PARTY/SAVEMON maps and
`data/games/polished_crystal/profile.json` `structs.battle` instead.

The parsed-row count is PINNED, so a future edit that breaks the parser fails loudly instead of
silently checking nothing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RAM_MD = ROOT / "docs" / "polished" / "RAM.md"
POLISHED_SYM = ROOT / "data" / "polished" / "polishedcrystal.sym"
VANILLA_PROFILE = ROOT / "data" / "games" / "gen2_crystal" / "profile.json"
VANILLA_SYM = ROOT / "data" / "gen2" / "crystal_slink.sym"      # RAM.md Sources :12
VANILLA_SYM_RAW = ROOT / "data" / "gen2" / "pokecrystal.sym"   # the clean pret build
POLISHED_PROFILE = ROOT / "data" / "games" / "polished_crystal" / "profile.json"

ADDR = re.compile(r"^[0-9a-fA-F]{2}:[0-9a-fA-F]{4}$")
# The main symbol tables are | name | vanilla addr | Polished name | Polished addr | verdict | note |
NAME_COL, VAN_COL, POL_NAME_COL, POL_COL, VERDICT_COL = 0, 1, 2, 3, 4

#: Rows of the shape | name | vanilla addr | ... | Polished addr | verdict | ... | that this test
#: must parse. Pinned so a broken parser is a failure, not a silent pass.
PINNED_ROWS = 30

#: Polished names RAM.md asserts that the Polished sym does NOT contain. RAM.md:75 names
#: `wNumKeyItems` at `01:D7FF`, but Polished has no such symbol and `$01:D7FF` is unlabelled space
#: (between `wPokemonJournalsEnd` $01:D7F5 and `wKeyItems` $01:D800). Pinned so the exception cannot
#: grow silently; clearing it needs a source read, not a doc edit.
KNOWN_UNRESOLVABLE_POLISHED = {("RAM.md:75", "wNumKeyItems")}

#: Rows with two address cells that are NOT a vanilla/Polished symbol pair (the §2.4 enemy-party
#: block table gives one block's two addresses). Counted and excluded, so they cannot be mistaken
#: for coverage.
EXPECTED_NON_SYMBOL_ROWS = 4


def _clean(cell: str) -> str:
    return cell.strip().strip("`").strip()


def _polished_symbols() -> dict[str, str]:
    out = {}
    for line in POLISHED_SYM.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.fullmatch(r"([0-9a-fA-F]{2}):([0-9a-fA-F]{4})\s+(\S+)", line.strip())
        if m:
            out.setdefault(m.group(3), f"{m.group(1).lower()}:{m.group(2).lower()}")
    return out


def _vanilla_bank(address: int) -> str:
    """RAM.md:18 -- WRAM0 $C000-$CFFF is bank 00, WRAMX $D000-$DFFF is bank 01, HRAM is bank 00."""
    if address >= 0xFF80:
        return "00"
    if address >= 0xD000:
        return "01"
    return "00"


def _sym_symbols(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.fullmatch(r"([0-9a-fA-F]{2}):([0-9a-fA-F]{4})\s+(\S+)", line.strip())
        if m:
            out.setdefault(m.group(3), f"{m.group(1).lower()}:{m.group(2).lower()}")
    return out


def _vanilla_symbols() -> dict[str, str]:
    """RAM.md `## Sources` (`:9`,`:12`) names TWO vanilla sources: the crystal `profile.json` (which
    holds absolute addresses) and `data/gen2/pokecrystal.sym` (which holds member symbols such as
    `wPartyMon1*` that the profile omits). Merge both; the sym wins where both have the name."""
    table = _sym_symbols(VANILLA_SYM_RAW)
    table.update(_sym_symbols(VANILLA_SYM))   # the shipped overlay sym wins
    crystal = json.loads(VANILLA_PROFILE.read_text(encoding="utf-8"))["titles"]["crystal"]
    profile_table: dict[str, str] = {}
    for group in ("ram", "ram_bank", "hram"):
        for name, address in crystal.get(group, {}).items():
            if isinstance(address, int) and not isinstance(address, bool):
                profile_table.setdefault(name, f"{_vanilla_bank(address)}:{address & 0xFFFF:04x}")
    for name, value in profile_table.items():
        table.setdefault(name, value)      # the sym wins where both have the name
    return table


def _symbol_candidates(cell: str) -> list[str]:
    """A name cell may hold one symbol, two joined by `/`, or a symbol plus a parenthetical."""
    head = cell.replace("`", "").split("(")[0]
    return [tok.strip() for tok in head.split("/") if tok.strip()]


def _resolve(cell: str, table: dict[str, str]) -> str | None:
    """The first candidate that the symbol file knows, or None."""
    for name in _symbol_candidates(cell):
        if name in table:
            return table[name]
    return None


def _offset(text: str) -> int | None:
    """`+7` or `+0x07` -> 7."""
    m = re.fullmatch(r"\+((?:0x)?[0-9a-fA-F]+)", text)
    if not m:
        return None
    raw = m.group(1)
    return int(raw, 16) if raw.lower().startswith("0x") else int(raw, 10)


def _leading_token(cell: str) -> str:
    r"""`Happiness (\`EggCycles\` alias)` -> `Happiness`. Exact match only, so `HP` never
    matches inside `MaxHP` and `PP` never matches inside `Happiness`."""
    head = re.split(r"[ (`]", cell.strip(), maxsplit=1)[0].strip()
    return head.lower()


def _rows():
    """Every markdown table row in RAM.md, as (line_no, cells)."""
    lines = RAM_MD.read_text(encoding="utf-8").splitlines()
    out = []
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|")):
            continue
        cells = [_clean(c) for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        out.append((n, cells))
    return out


def symbol_rows() -> list[tuple[int, list[str]]]:
    """Rows whose address cells are exactly at columns VAN_COL and POL_COL."""
    found = []
    for n, cells in _rows():
        if len(cells) < 5:
            continue
        if (ADDR.fullmatch(cells[VAN_COL]) and ADDR.fullmatch(cells[POL_COL])
                and ADDR.fullmatch(cells[POL_NAME_COL]) is None):
            found.append((n, cells))
    return found


@pytest.fixture(scope="module")
def polished() -> dict[str, str]:
    if not POLISHED_SYM.is_file():
        pytest.skip(f"Polished symbol file absent: {POLISHED_SYM}")
    return _polished_symbols()


@pytest.fixture(scope="module")
def vanilla() -> dict[str, str]:
    return _vanilla_symbols()


# ------------------------------------------------------------------ parser liveness

def test_the_parser_finds_the_pinned_number_of_symbol_rows():
    """The pin. If a future edit changes the table shape and this drops, the tests below are vacuous.

    MUTATION: change the table header's column order, or delete a `bank:addr` cell from any row --
    the count drops and this goes red instead of the suite quietly checking nothing.
    """
    rows = symbol_rows()
    assert len(rows) == PINNED_ROWS, (
        f"RAM.md symbol rows parsed {len(rows)}, pinned at {PINNED_ROWS}; "
        "update the pin and re-read the table shape if this is intentional")


def test_the_two_address_cell_rows_that_are_not_symbol_pairs_are_counted():
    """The §2.4 enemy-party block table has two address cells that are not a vanilla/Polished pair.

    MUTATION: convert one of them into a vanilla/Polished pair-shaped row -- the total two-address
    count changes and this goes red, so the exclusion stays deliberate.
    """
    two = sum(1 for _, cells in _rows() if sum(1 for c in cells if ADDR.fullmatch(c)) == 2)
    non_symbol = two - len(symbol_rows())
    assert non_symbol == EXPECTED_NON_SYMBOL_ROWS, (
        f"expected {EXPECTED_NON_SYMBOL_ROWS} two-address rows that are NOT symbol pairs, "
        f"found {non_symbol} ({two} two-address rows, {len(symbol_rows())} symbol pairs)")


# ------------------------------------------------------------------ the cells themselves

def test_every_polished_address_matches_the_polished_symbol_file(polished):
    """Each Polished `bank:addr` must be that symbol's line in polishedcrystal.sym.

    MUTATION: change one Polished cell in RAM.md by a single hex digit -- this goes red.
    """
    bad = []
    for n, cells in symbol_rows():
        name, stated = cells[POL_NAME_COL], cells[POL_COL].lower()
        real = _resolve(name, polished)
        if real is None:
            continue                      # reported by test_every_named_symbol_exists
        if real != stated:
            bad.append(f"RAM.md:{n}: {name} stated {stated}, sym says {real}")
    assert not bad, "\n".join(bad)


def test_every_vanilla_address_matches_the_vanilla_profile(vanilla):
    """Each vanilla `bank:addr` must be that symbol's absolute address in the crystal profile.

    Settled 2026-10-04: data/gen2/pokecrystal.sym, crystal_slink.sym and profile.json agree with each other
    (e.g. wCurBox 01:db72); RAM.md's vanilla column had ten wrong cells, now corrected.

    MUTATION: change one vanilla cell in RAM.md -- this goes red.
    """
    bad = []
    for n, cells in symbol_rows():
        name, stated = cells[NAME_COL], cells[VAN_COL].lower()
        real = _resolve(name, vanilla)
        if real is None:
            continue                      # reported by test_every_named_symbol_exists
        if real != stated:
            bad.append(f"RAM.md:{n}: {name} stated {stated}, profile says {real}")
    assert not bad, "\n".join(bad)


# ------------------------------------------------------------------ the verdict column

_VERDICT_RULES = {
    # same name in both columns and the same address -> 'same'; same name, different address ->
    # 'moved'; different name -> never 'same'/'moved'.
    "same": lambda vn, pn, va, pa: vn == pn and va == pa,
    "moved": lambda vn, pn, va, pa: vn == pn and va != pa,
    "renamed": lambda vn, pn, va, pa: vn != pn,
}


def test_each_verdict_is_consistent_with_the_two_names_and_two_addresses():
    """A verdict must not contradict the cells beside it.

    'same' with different addresses, or 'moved' with identical addresses, is the failure this
    catches -- exactly the shape of the wTextboxFlags defect corrected on 2026-10-04.

    MUTATION: flip one row's verdict cell from 'moved' to 'same' (or the reverse) -- this goes red.
    """
    bad = []
    for n, cells in symbol_rows():
        verdict = cells[VERDICT_COL].lower().replace("`", "")
        rule = _VERDICT_RULES.get(verdict)
        if rule is None:
            continue                      # 'different', 'different-layout', prose verdicts
        vn = _symbol_candidates(cells[NAME_COL])[0]
        pn = _symbol_candidates(cells[POL_NAME_COL])[0]
        va, pa = cells[VAN_COL].lower(), cells[POL_COL].lower()
        if not rule(vn, pn, va, pa):
            bad.append(f"RAM.md:{n}: verdict {verdict!r} contradicts {vn} {va} -> {pn} {pa}")
    assert not bad, "\n".join(bad)


def test_every_named_symbol_exists_in_its_symbol_file(polished, vanilla):
    """Every symbol a row NAMES must exist in the file that file claims to be the source.

    MUTATION: rename a Polished cell to a symbol Polished does not have -- this goes red. It is
    separate from the address tests because a missing symbol makes the adjacent address
    UNCHECKABLE, which must not read as "checked and fine".
    """
    bad = []
    for n, cells in symbol_rows():
        name = cells[POL_NAME_COL]
        if _resolve(name, polished) is None and (f"RAM.md:{n}", name) not in KNOWN_UNRESOLVABLE_POLISHED:
            bad.append(f"RAM.md:{n}: Polished name {name!r} is not in {POLISHED_SYM.name} "
                       "(add it to KNOWN_UNRESOLVABLE_POLISHED only with a source read)")
        if _resolve(cells[NAME_COL], vanilla) is None:
            bad.append(f"RAM.md:{n}: vanilla name {cells[NAME_COL]!r} is not in "
                       f"the vanilla sources")
    assert not bad, "\n".join(bad)


# ------------------------------------------------------------------ struct offsets

def test_the_party_struct_offsets_match_the_codec():
    """RAM.md §2.1's Polished column must be `polished_codec.PARTY`'s offsets, field for field.

    MUTATION: change one `+N` in RAM.md §2.1 -- this goes red.
    """
    from server.adapters import polished_codec

    codec = {name: polished_codec.PARTY[name] for name in polished_codec.PARTY}
    lines = RAM_MD.read_text(encoding="utf-8").splitlines()
    checked, bad = 0, []
    in_section = False
    for n, line in enumerate(lines, 1):
        if line.startswith("### 2.1"):
            in_section = True
        elif line.startswith("### 2.2"):
            in_section = False
        if not in_section or not line.strip().startswith("|"):
            continue
        cells = [_clean(c) for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        stated = _offset(cells[2])
        if stated is None:
            continue
        token = _leading_token(cells[0])
        key = next((k for k in codec if k.lower() == token), None)
        if key is None:
            continue
        checked += 1
        if codec[key] != stated:
            bad.append(f"RAM.md:{n}: {cells[1]!r} states +{stated}, codec says +{codec[key]}")
    assert checked, "no party_struct offset cells parsed -- the parser is broken"
    assert not bad, "\n".join(bad)


def test_the_savemon_struct_offsets_match_the_codec():
    """RAM.md §2.6 must agree with `polished_codec.SAVEMON`.

    MUTATION: change one `+N` in RAM.md §2.6 -- this goes red.
    """
    from server.adapters import polished_codec

    codec = polished_codec.SAVEMON
    lines = RAM_MD.read_text(encoding="utf-8").splitlines()
    checked, bad = 0, []
    in_section = False
    for n, line in enumerate(lines, 1):
        if line.startswith("### 2.6"):
            in_section = True
        elif line.startswith("## 3."):
            in_section = False
        if not in_section or not line.strip().startswith("|"):
            continue
        cells = [_clean(c) for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        stated = _offset(cells[0])
        if stated is None:
            continue
        token = _leading_token(cells[1])
        key = next((k for k in codec if k.lower() == token), None)
        if key is None:
            continue
        checked += 1
        if codec[key] != stated:
            bad.append(f"RAM.md:{n}: {cells[0]!r} states +{stated}, codec says +{codec[key]}")
    assert checked, "no savemon_struct offset cells parsed -- the parser is broken"
    assert not bad, "\n".join(bad)


def test_the_battle_struct_offsets_match_the_profile():
    """RAM.md 2.3's Polished offset column must equal `structs.battle` in the polished profile.

    The profile stores a flat field->offset map (no `size` key), so the offsets themselves are
    what gets pinned, not a byte count.

    MUTATION: change one Polished offset cell in RAM.md 2.3 -- this goes red.
    """
    profile = json.loads(POLISHED_PROFILE.read_text(encoding="utf-8"))
    titles = profile["titles"]
    title = titles["polished_crystal"] if "polished_crystal" in titles else titles[sorted(titles)[0]]
    battle = {k: v for k, v in title["structs"]["battle"].items() if isinstance(v, int)}
    assert battle, "polished profile has no structs.battle offsets"
    section = RAM_MD.read_text(encoding="utf-8").split("### 2.3", 1)[1].split("### 2.4", 1)[0]
    checked, bad = 0, []
    for line in section.splitlines():
        row = line.strip()
        if not (row.startswith("|") and row.endswith("|")):
            continue
        cells = [_clean(c) for c in row.strip("|").split("|")]
        if len(cells) < 3:
            continue
        stated = _offset(cells[2])
        if stated is None:
            continue
        token = _leading_token(cells[0])
        key = next((k for k in battle if k.lower() == token), None)
        if key is None:
            continue
        checked += 1
        if battle[key] != stated:
            bad.append(f"RAM.md 2.3: {cells[0]!r} states +{stated}, profile says +{battle[key]}")
    assert checked, "no battle_struct offset cells parsed -- the parser is broken"
    assert not bad, "\n".join(bad)
