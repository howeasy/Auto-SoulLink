"""Generate reference expansion HARNESS addresses; no admission/runtime claim.

python tools/gen_gen3_title_syms_exp.py --symbols <build>/pokeemerald.sym [--check]
The symbol artifact is hash-bound to committed compiler facts and ROM identity.
No vanilla record-internal offset is copied. Only Main.callback2 has a member
offset in the legacy harness table today, and it comes from compiler facts.
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
OUTPUT = ROOT / "lua/tests/gen3_title_syms_exp_28877d73.lua"
TITLE = "emerald_expansion_28877d73"
ROM_SHA1 = "28877d733492299599f2b8fff50493109d72653c"
SOURCE = "e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7"
SYM_SHA256 = "ac24a47c0137ab9b2233ccf37bf0cabe8b6eb08b715aa7e87f15787507a1f01e"
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


def require(condition, message):
    if not condition:
        raise ValueError(message)


def entries():
    lua = LuaRuntime()
    module = lua.execute(f"return dofile({json.dumps(TABLE.as_posix())})")
    return {name: dict(row) for name, row in module.entries.items()}


def symbols(text):
    result = {}
    for line, raw in enumerate(text.splitlines(), 1):
        match = re.fullmatch(r"([0-9a-fA-F]{8}) [gl] ([0-9a-fA-F]{8}) (\S+)", raw)
        if match:
            address, size, name = match.groups()
            result.setdefault(name, []).append({"address": int(address, 16),
                                                "size": int(size, 16), "line": line})
    for rows in result.values():
        rows.sort(key=lambda row: row["address"])
    return result


def generate(sym_path: Path, facts_path: Path = FACTS, layout_path: Path = LAYOUT):
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    require(facts["schema"] == layout["schema"] == 1, "unsupported facts/layout schema")
    require(facts["provenance"]["source_commit"] == SOURCE
            and layout["provenance"]["source_commit"] == SOURCE, "source pin mismatch")
    require(facts["provenance"]["rom_sha1"] == layout["rom_sha1"] == ROM_SHA1, "ROM pin mismatch")
    raw = sym_path.read_bytes()
    receipt = facts["provenance"]["artifacts"]["pokeemerald.sym"]
    require(hashlib.sha256(raw).hexdigest() == receipt["sha256"] == SYM_SHA256
            and len(raw) == receipt["size"], "symbol artifact hash/size mismatch")
    syms = symbols(raw.decode("utf-8"))
    legacy = entries()
    require(NILS.keys() <= legacy.keys(), "legacy table lost a documented nil entry")
    rows = {}
    for name, entry in sorted(legacy.items()):
        if name in NILS:
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
        thumb = bool(entry.get("thumb"))
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", type=Path,
                        default=ROOT / ".cache/expansion-output/reference/pokeemerald.sym")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        text = generate(args.symbols)
        if args.check:
            require(OUTPUT.is_file() and OUTPUT.read_text(encoding="utf-8") == text,
                    "generated expansion harness table missing/different")
            print("PASS: generated expansion harness table current; no files written")
        else:
            OUTPUT.write_text(text, encoding="utf-8", newline="\n")
            print(f"generated {OUTPUT}")
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, f"FAIL: {error}\n")


if __name__ == "__main__":
    main()
