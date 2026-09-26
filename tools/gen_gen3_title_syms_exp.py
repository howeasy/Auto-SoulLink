"""Generate reference expansion HARNESS addresses; no admission/runtime claim.

python tools/gen_gen3_title_syms_exp.py --symbols <build>/pokeemerald.sym --map <build>/pokeemerald.map [--check]
The symbol artifact is hash-bound to committed compiler facts and ROM identity.
No vanilla record-internal offset is copied. Only Main.callback2 has a member
offset in the legacy harness table today, and it comes from compiler facts.

--symbols/--map default to the full pinned build artifacts under .cache/ (not committed, ~4.6 MB
each); when either is absent, this script and its tests fall back to the committed hash-bound
slices (data/games/gen3_exp/28877d73/harness_rows.sym and harness_map_slice.txt), which carry only
the rows/sections generate() actually consumes. A slice is pinned by its OWN sha256 (SYM_SLICE_SHA256
/MAP_SLICE_SHA256); its header comment additionally records the full artifact's sha256 for humans.
Either source produces byte-identical output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "lua/tests/gen3_title_syms.lua"
FACTS = ROOT / "data/games/gen3_exp/28877d73/facts.json"
LAYOUT = ROOT / "data/games/gen3_exp/28877d73/layout.json"
SYM_DEFAULT = ROOT / ".cache/expansion-output/reference/pokeemerald.sym"
MAP_DEFAULT = ROOT / ".cache/expansion-output/reference/pokeemerald.map"
SYM_SLICE = ROOT / "data/games/gen3_exp/28877d73/harness_rows.sym"
MAP_SLICE = ROOT / "data/games/gen3_exp/28877d73/harness_map_slice.txt"
OUTPUT = ROOT / "lua/tests/gen3_title_syms_exp_28877d73.lua"
TITLE = "emerald_expansion_28877d73"
ROM_SHA1 = "28877d733492299599f2b8fff50493109d72653c"
SOURCE = "e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7"
SYM_SHA256 = "ac24a47c0137ab9b2233ccf37bf0cabe8b6eb08b715aa7e87f15787507a1f01e"
MAP_SHA256 = "c957564542361f56661478f1ffa6967893d5ae26bfb7e6be84bffa0899017c08"
# The committed slices are hash-bound by their OWN sha256 (not just the full artifact's, which
# their header comment records for humans) -- any hand-edit of a slice's rows must fail loudly.
SYM_SLICE_SHA256 = "1249b6d3800417f6f313b60872ed43cf0ee68fb30c3fc4d1f11ccdaf58a2ba36"
MAP_SLICE_SHA256 = "899d436c18474239c4800dc6e353c8f0b5b399cc0014291991e6b884de2a199e"
NILS = {
    "ACTIVE_BATTLER_ADDR": "src/battle_controller_player.c:234 takes enum BattlerId battler; no gActiveBattler symbol",
    "BAG_MENU_STATE_ADDR": "src/item_menu.c:579 uses struct BagMenu *gBagMenu, not vanilla gBagMenuState",
    "TASK_ANIMATE_WIN0V": "src/item_menu.c:154-158 pocket switching uses SwitchBagPocket/Task_SwitchBagPocket; no Task_AnimateWin0v symbol",
    "TASK_OAKSPEECH_GENDER_INPUT": "src/main_menu.c:128-135 Birch gender scene, no OakSpeech_HandleGenderInput symbol",
    "TASK_START_MENU_HANDLE_INPUT": "src/start_menu.c:84,605-609 uses gMenuCallback, not a Task_StartMenuHandleInput task",
    "START_CB_HANDLE_INPUT": "src/start_menu.c:627 HandleStartMenuInput has a different callback architecture; no StartCB_HandleInput",
    "START_CB_SAVE1": "src/start_menu.c:143,655 SaveGameTask/StartMenuSaveCallback, no StartCB_Save1 split",
    "START_CB_SAVE2": "src/start_menu.c:143,655 SaveGameTask/StartMenuSaveCallback, no StartCB_Save2 split",
}
# Sorted-address occurrences verified against the pinned build map (its hash is
# also in facts.provenance.artifacts), not inherited from vanilla link order.
OCCURRENCES = {
    "HANDLE_INPUT_CHOOSE_ACTION": (1, 0x3E4,
        "src/battle_controller_player.c:234; pokeemerald.map:6865 player .text [08059620,0805D25C)"),
    "PC_MENU_BASE": (0, 0xC, "src/menu.c:69 struct Menu sMenu (12 bytes), not either 4-byte pointer"),
}
# The (object file, section) each OCCURRENCES entry's chosen hit must fall inside, per the .map --
# generate() reads this from the artifact/slice rather than trusting the OCCURRENCES prose alone.
SPANS = {
    "HANDLE_INPUT_CHOOSE_ACTION": ("src/battle_controller_player.o", ".text"),
    "PC_MENU_BASE": ("src/menu.o", ".sbss"),
}
LINE_ANNOTATION = re.compile(r"-- line (\d+)")
MAP_ROW = re.compile(r"^ (\.\S+|common_data)\s+0x([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)\s+(\S+)$", re.MULTILINE)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def entries():
    lua = LuaRuntime()
    module = lua.execute(f"return dofile({json.dumps(TABLE.as_posix())})")
    return {name: dict(row) for name, row in module.entries.items()}


def resolve_or_slice(path: Path, slice_path: Path) -> Path:
    """The full artifact when present, else its committed hash-bound slice."""
    return path if path.is_file() else slice_path


def symbols(text):
    """Parse `<addr> <g|l> <size> <name>` rows. A `-- line N` comment immediately before a row
    (only present in a committed slice, never in a real .sym) overrides its recorded line number
    with N, the row's line in the FULL artifact, so a slice and the full file it was cut from
    produce identical `line` values."""
    result = {}
    pending_line = None
    for line, raw in enumerate(text.splitlines(), 1):
        annotation = LINE_ANNOTATION.fullmatch(raw)
        if annotation:
            pending_line = int(annotation.group(1))
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{8}) [gl] ([0-9a-fA-F]{8}) (\S+)", raw)
        if match:
            address, size, name = match.groups()
            result.setdefault(name, []).append({"address": int(address, 16),
                                                "size": int(size, 16),
                                                "line": pending_line if pending_line is not None else line})
        pending_line = None
    for rows in result.values():
        rows.sort(key=lambda row: row["address"])
    return result


def map_sections(text):
    """Parse ` <section> 0x<addr> 0x<size> <objfile>` linker-map section-contribution rows."""
    sections = {}
    for match in MAP_ROW.finditer(text):
        section, address, size, objfile = match.groups()
        sections[(objfile, section)] = {"address": int(address, 16), "size": int(size, 16)}
    return sections


def _load_hash_bound(path: Path, receipt: dict, pinned_sha256: str, slice_sha256: str,
                      parse, artifact_label: str):
    """Read `path`, accepting either the full artifact (whole-file hash == pinned_sha256) or the
    committed slice (whole-file hash == slice_sha256 -- its OWN pin, not just a claim its header
    text makes about the full artifact, so a hand-edited slice row fails loudly too)."""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest == receipt["sha256"] == pinned_sha256 and len(raw) == receipt["size"]:
        return parse(raw.decode("utf-8"))
    require(digest == slice_sha256, f"{artifact_label} artifact hash/size mismatch")
    return parse(raw.decode("utf-8"))


def generate(sym_path: Path, facts_path: Path = FACTS, layout_path: Path = LAYOUT, map_path: Path | None = None):
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    require(facts["schema"] == layout["schema"] == 1, "unsupported facts/layout schema")
    require(facts["provenance"]["source_commit"] == SOURCE
            and layout["provenance"]["source_commit"] == SOURCE, "source pin mismatch")
    require(facts["provenance"]["rom_sha1"] == layout["rom_sha1"] == ROM_SHA1, "ROM pin mismatch")
    sym_path = resolve_or_slice(sym_path, SYM_SLICE)
    syms = _load_hash_bound(sym_path, facts["provenance"]["artifacts"]["pokeemerald.sym"],
                             SYM_SHA256, SYM_SLICE_SHA256, symbols, "symbol")
    map_path = resolve_or_slice(map_path if map_path is not None else MAP_DEFAULT, MAP_SLICE)
    sections = _load_hash_bound(map_path, facts["provenance"]["artifacts"]["pokeemerald.map"],
                                 MAP_SHA256, MAP_SLICE_SHA256, map_sections, "map")
    legacy = entries()
    require(NILS.keys() <= legacy.keys(), "legacy table lost a documented nil entry")
    rows = {}
    for name, entry in sorted(legacy.items()):
        if name in NILS:
            symbol = entry.get("emerald_symbol", entry["symbol"])
            require(symbol not in syms,
                    f"documented-nil symbol now present in build, resolve it instead of nil: "
                    f"{name} ({symbol})")
            rows[name] = {"source": f"expansion@{SOURCE} {NILS[name]}", "status": "nil"}
            continue
        symbol = entry.get("emerald_symbol", entry["symbol"])
        offset, source = 0, ""
        if name == "PARTY_BASE":
            symbol = "gParties"
            offset = facts["constants"]["B_TRAINER_PLAYER"] * facts["constants"]["PARTY_SIZE"] * facts["structs"]["Pokemon"]["size"]
            source = "src/pokemon.c:100-110; facts.constants.B_TRAINER_PLAYER/PARTY_SIZE and structs.Pokemon.size"
        elif name == "PARTY_COUNT_ADDR":
            symbol = "gPartiesCount"
            offset = facts["constants"]["B_TRAINER_PLAYER"]
            source = "src/pokemon.c:100-110; include/pokemon.h:735-737 macro dereferences count pointer; facts.constants.B_TRAINER_PLAYER"
        elif name == "GMAIN_CALLBACK2_ADDR":
            offset = facts["structs"]["Main"]["fields"]["callback2"]["offset"]
            source = "facts.structs.Main.fields.callback2.offset (compiler-derived)"
        else:
            require(not entry.get("offset"), f"unmapped member offset: {name}")
        hits = syms.get(symbol, [])
        require(bool(hits), f"no proven expansion symbol/nil decision: {name} ({symbol})")
        occurrence = 0
        if name in OCCURRENCES:
            occurrence, size, source = OCCURRENCES[name]
            require(len(hits) == 3 and hits[occurrence]["size"] == size,
                    f"duplicate-symbol geometry changed: {name}")
        else:
            require(len(hits) == 1, f"ambiguous symbol requires explicit occurrence: {name}")
        hit = hits[occurrence]
        require(0 <= offset < hit["size"], f"offset outside symbol: {name}")
        if name in SPANS:
            objfile, section = SPANS[name]
            span_row = sections.get((objfile, section))
            require(span_row is not None, f"map section missing for span check: {name}")
            lo, hi = span_row["address"], span_row["address"] + span_row["size"]
            require(lo <= hit["address"] < hi,
                    f"chosen occurrence outside cited .map span: {name}")
        # Derive thumb from the resolved address's own memory region (ROM code, not vanilla's
        # copied column): every entry this table resolves is either RAM data or a ROM Thumb
        # function pointer, never ROM rodata, so ROM-range membership is exactly "is code".
        derived_thumb = 0x08000000 <= hit["address"] < 0x0A000000
        require(derived_thumb == bool(entry.get("thumb")),
                f"thumb bit mismatch vs .sym address range: {name}")
        thumb = derived_thumb
        value = (hit["address"] + offset) | int(thumb)
        if name in ("PARTY_BASE", "PARTY_COUNT_ADDR"):
            key = "player_party" if name == "PARTY_BASE" else "player_party_count"
            require(value == facts["derived_addresses"][key], f"compiler-address crosscheck failed: {name}")
        rows[name] = {"address": value, "symbol": symbol, "occurrence": occurrence,
                      "offset": offset, "thumb": thumb, "symbol_line": hit["line"],
                      "symbol_size": hit["size"], "status": "SOURCE",
                      "source": f"pokeemerald.sym:{hit['line']} {symbol}[{occurrence}]"
                                + (f"; expansion@{SOURCE} {source}" if source else "")}
    metadata = {"title": TITLE, "rom_sha1": ROM_SHA1, "source_commit": SOURCE,
                "symbol_sha256": SYM_SHA256,
                "facts_sha256": hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest(),
                "layout_sha256": hashlib.sha256(json.dumps(layout, sort_keys=True).encode()).hexdigest()}
    lines = ["-- GENERATED by tools/gen_gen3_title_syms_exp.py; do not edit.",
             "-- SOURCE/COMPILER addresses only. No runtime/admission claim.",
             "-- 12-char masked records still require expansion-aware harness readers.",
             "-- gDisableStructs/gStatuses3 and inlined TryStorePartyMonInBox/ReleaseMon",
             "-- are absent (facts.unavailable); they are not legacy table keys. PC_RELEASE_MON",
             "-- below names Task_ReleaseMon, NOT the inlined ReleaseMon primitive.", "return {"]
    for key, value in metadata.items():
        lines.append(f"    {key} = {json.dumps(value)},")
    lines.append("    entries = {")
    for name, row in rows.items():
        values = []
        if row["status"] == "nil":
            values.append("address = nil")
        for key, value in row.items():
            literal = (str(value).lower() if isinstance(value, bool) else
                       f"0x{value:X}" if isinstance(value, int) else json.dumps(value))
            values.append(f"{key} = {literal}")
        lines.append(f"        {name} = {{ " + ", ".join(values) + " },")
    lines += ["    },", "}", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", type=Path, default=SYM_DEFAULT)
    parser.add_argument("--map", type=Path, default=MAP_DEFAULT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        text = generate(args.symbols, map_path=args.map)
        if args.check:
            expected = text.encode("utf-8")
            actual = OUTPUT.read_bytes() if OUTPUT.is_file() else None
            require(actual == expected, "generated expansion harness table missing/different")
            print("PASS: generated expansion harness table current; no files written")
        else:
            OUTPUT.write_text(text, encoding="utf-8", newline="\n")
            print(f"generated {OUTPUT}")
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, f"FAIL: {error}\n")


if __name__ == "__main__":
    main()
