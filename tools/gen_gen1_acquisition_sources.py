"""Generate a source/ROM-verified RBY acquisition census, not runtime admission.

Every script grant, monster object and reachable NPC exchange is classified.
Runtime transaction predicates/ordinals must still be qualified independently;
this artifact cannot turn an observed party change into an exempt grant by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from gen_gen1_codec_data import digest
from gen_gen1_encounters import parse_pokemon_constants
from verify_canonical_sources import verify

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/games/gen1_rby/acquisition_sources.json"
TITLES = {"red": ("pokered", "pokered"), "blue": ("pokered", "pokeblue"), "yellow": ("pokeyellow", "pokeyellow")}
# Reviewed identity/group metadata; species and machine addresses are derived.
GRANTS = {
    "scripts/CeladonMansionRoofHouse.asm": ("eevee", "CELADON_MANSION_ROOF_HOUSE", 1),
    "scripts/CinnabarLabFossilRoom.asm": ("fossil_revival", "CINNABAR_LAB_FOSSIL_ROOM", 1),
    "scripts/FightingDojo.asm": ("dojo_choice", "FIGHTING_DOJO", 2),
    "scripts/MtMoonPokecenter.asm": ("magikarp_salesman", "MT_MOON_POKECENTER", 1),
    "scripts/MtMoonPokecenter_2.asm": ("magikarp_salesman", "MT_MOON_POKECENTER", 1),
    "scripts/OaksLab.asm": ("starter", "OAKS_LAB", 1),
    "scripts/SilphCo7F.asm": ("lapras", "SILPH_CO_7F", 1),
    "engine/events/prize_menu.asm": ("game_corner_purchase", "GAME_CORNER_PRIZE_ROOM", 1),
    "scripts/CeruleanMelaniesHouse.asm": ("yellow_bulbasaur", "CERULEAN_MELANIES_HOUSE", 1),
    "scripts/Route24.asm": ("yellow_charmander", "ROUTE_24", 1),
    "scripts/VermilionCity_2.asm": ("yellow_squirtle", "VERMILION_CITY", 1),
}
CALL = re.compile(r"\s*call (GivePokemon|AddPartyMon|AddEnemyMonToPlayerParty)\s*(?:;.*)?$")


def flat(symbol: tuple[int, int]) -> int:
    bank, address = symbol
    if bank == 0 and 0 <= address < 0x4000:
        return address
    if bank > 0 and 0x4000 <= address < 0x8000:
        return bank * 0x4000 + address - 0x4000
    raise ValueError(f"not a bank-qualified ROM address: {symbol}")


def symbols(path: Path) -> dict[str, tuple[int, int]]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if match := re.fullmatch(r"([\da-fA-F]+):([\da-fA-F]+) (\S+)", line):
            name, value = match[3], (int(match[1], 16), int(match[2], 16))
            if name in out and out[name] != value:
                raise ValueError(f"conflicting symbol: {name}")
            out[name] = value
    return out


def address(symbol: tuple[int, int]) -> dict:
    return {"bank": symbol[0], "address": symbol[1], "rom_offset": flat(symbol)}


def source_scopes(lines: list[str], syms: dict) -> list[tuple[int, str]]:
    scopes, current_global = [], None
    for line_number, raw in enumerate(lines):
        code = raw.split(";", 1)[0].strip()
        match = re.fullmatch(r"([.\w]+)(?:::?)?", code)
        if raw and not raw[0].isspace() and match:
            name = match[1]
            if name.startswith("."):
                name = (current_global or "") + name
            elif name in syms:
                current_global = name
            if name in syms:
                scopes.append((line_number, name))
    return scopes


def instruction_site(lines: list[str], scopes: list, syms: dict, rom: bytes,
                     line_number: int, pattern: bytes) -> tuple[str, tuple[int, int]]:
    previous = [name for n, name in scopes if n < line_number]
    if not previous:
        raise ValueError("instruction has no compiled source scope")
    label = previous[-1]
    bank, _ = syms[label]
    start = flat(syms[label])
    end = next((flat(syms[name]) for n, name in scopes if n > line_number
                and syms[name][0] == bank and flat(syms[name]) > start), (bank + 1) * 0x4000)
    hits = [offset for offset in range(start, end - len(pattern) + 1) if rom[offset:offset + len(pattern)] == pattern]
    if len(hits) != 1:
        raise ValueError(f"missing/ambiguous {pattern.hex()} instruction in {label}: {hits}")
    offset = hits[0]
    cpu = offset if bank == 0 else 0x4000 + offset % 0x4000
    return label, (bank, cpu)


def call_sites(file: Path, syms: dict, rom: bytes) -> list[dict]:
    lines = file.read_text(encoding="utf-8").splitlines()
    scopes = source_scopes(lines, syms)
    out = []
    for line_number, raw in enumerate(lines):
        if not (match := CALL.fullmatch(raw)):
            continue
        target = match[1]
        if syms[target][0] != 0:
            raise ValueError("acquisition helper is no longer a ROM0 call")
        operand = syms[target][1]
        pattern = bytes((0xCD, operand & 255, operand >> 8))
        label, (bank, cpu) = instruction_site(lines, scopes, syms, rom, line_number, pattern)
        out.append({"source_line": line_number + 1, "scope_symbol": label, "target_symbol": target,
                    "call": address((bank, cpu)), "return_address": cpu + 3,
                    "expected_call_hex": pattern.hex()})
    return out


def scripted_battles(repo: Path, syms: dict, rom: bytes, maps: dict, pokemon: dict) -> list:
    kinds = {
        "Route12": ("static:route12_snorlax", "catchable_static", "SNORLAX"),
        "Route16": ("static:route16_snorlax", "catchable_static", "SNORLAX"),
        "PokemonTower6F": ("script-battle:ghost-marowak", "uncatchable_script_battle", "RESTLESS_SOUL"),
        "ViridianCity": ("script-battle:old-man-tutorial", "uncatchable_script_battle", None),
        "PalletTown": ("script-battle:oak-pikachu", "uncatchable_script_battle", "STARTER_PIKACHU"),
    }
    out, found = [], set()
    for file in sorted((repo / "scripts").glob("*.asm")):
        lines = file.read_text(encoding="utf-8").splitlines()
        text = re.sub(r";[^\n]*", "", "\n".join(lines))
        pattern = re.compile(r"ld a,\s*(\w+)\s+ld \[wCurOpponent\], a")
        matches = list(pattern.finditer(text))
        if len(matches) != len(re.findall(r"ld \[wCurOpponent\], a", text)):
            raise ValueError(f"unknown scripted battle assignment: {file}")
        for match in matches:
            value = match[1]
            if value.startswith("OPP_"):
                continue  # trainer battle, not an acquisition source
            if file.stem not in kinds:
                raise ValueError(f"unclassified scripted wild battle: {file}: {value}")
            identity, kind, expected = kinds[file.stem]
            if expected and value != expected:
                raise ValueError(f"scripted battle species changed: {file}")
            if identity in found:
                raise ValueError(f"duplicate scripted battle source: {identity}")
            found.add(identity)
            species = pokemon[value]
            addr = syms["wCurOpponent"][1]
            machine = bytes((0x3E, species, 0xEA, addr & 255, addr >> 8))
            # Count lines in comment-stripped source (newlines are retained).
            line_number = text.count("\n", 0, match.start())
            scope, location = instruction_site(lines, source_scopes(lines, syms), syms, rom, line_number, machine)
            constant = map_name(repo, file.stem)
            out.append({"source_id": identity, "kind": kind, "source_file": file.relative_to(repo).as_posix(),
                        "source_line": line_number + 1, "scope_symbol": scope, "entry": address(location),
                        "map": constant, "map_id": maps[constant], "species_index": species,
                        "opponent_species_rom_offset": flat(location) + 1, "expected_assignment_hex": machine.hex()})
    required = {row[0] for name, row in kinds.items() if name != "PalletTown" or repo.name == "pokeyellow"}
    if found != required:
        raise ValueError(f"scripted battle inventory differs: {found ^ required}")
    return out


def map_ids(repo: Path, syms: dict, rom: bytes) -> dict[str, int]:
    names = re.findall(r"^\s*map_const\s+(\w+),", (repo / "constants/map_constants.asm").read_text(), re.M)
    pointers = re.findall(r"^\s*dw\s+(\w+)(?:\s*;[^\n]*)?\s*$",
                          (repo / "data/maps/map_header_pointers.asm").read_text(), re.M)
    bank_rows = re.findall(r"^\s*db\s+(BANK\(\w+\)|\$[\da-fA-F]+)(?:\s*;[^\n]*)?\s*$",
                           (repo / "data/maps/map_header_banks.asm").read_text(), re.M)
    if len(names) != len(pointers) or len(names) != len(bank_rows) or len(set(names)) != len(names):
        raise ValueError("map constants/header pointer inventory differs")
    pointer_base, bank_base = flat(syms["MapHeaderPointers"]), flat(syms["MapHeaderBanks"])
    for index, label in enumerate(pointers):
        _, cpu = syms[label]
        bank = int(bank_rows[index][1:], 16) if bank_rows[index].startswith("$") else syms[bank_rows[index][5:-1]][0]
        actual = int.from_bytes(rom[pointer_base + index * 2:pointer_base + index * 2 + 2], "little")
        if actual != cpu or rom[bank_base + index] != bank:
            raise ValueError(f"map header bytes differ: {names[index]}")
    return dict(zip(names, range(len(names)), strict=True))


def map_name(repo: Path, stem: str) -> str:
    header = repo / "data/maps/headers" / (stem + ".asm")
    match = re.search(r"map_header\s+\w+,\s*(\w+),", header.read_text())
    if not match:
        raise ValueError(f"unrecognized map header: {header}")
    return match[1]


def monster_objects(repo: Path, syms: dict, rom: bytes, maps: dict, pokemon: dict, valid_species: set) -> list:
    out = []
    for file in sorted((repo / "data/maps/objects").glob("*.asm")):
        text = file.read_text(encoding="utf-8")
        rows = [line.split(";", 1)[0].strip()[len("object_event "):].split(",")
                for line in text.splitlines() if line.strip().startswith("object_event ")]
        if not rows:
            continue
        label = re.search(r"^(\w+_Object):", text, re.M)
        if not label:
            raise ValueError(f"object header has no label: {file}")
        start = flat(syms[label[1]])
        pos = start + 1  # border
        pos += 1 + rom[pos] * 4  # warps
        pos += 1 + rom[pos] * 3  # signs
        if rom[pos] != len(rows):
            raise ValueError(f"source/ROM object count differs: {file}")
        pos += 1
        for index, row in enumerate(rows, 1):
            row = [part.strip() for part in row]
            size = len(row)
            if size not in (6, 7, 8) or rom[pos + 1] != int(row[1]) + 4 or rom[pos + 2] != int(row[0]) + 4:
                raise ValueError(f"source/ROM object geometry differs: {file}:{index}")
            flags = rom[pos + 5]
            if bool(flags & 64) != (size == 8) or bool(flags & 128) != (size == 7):
                raise ValueError(f"source/ROM object kind differs: {file}:{index}")
            if size == 8 and rom[pos + 6] < 200:
                species, level = rom[pos + 6:pos + 8]
                if species not in valid_species or pokemon.get(row[6]) != species or int(row[7]) != level or not 1 <= level <= 100:
                    raise ValueError(f"invalid static monster record: {file}:{index}")
                map_constant = map_name(repo, file.stem)
                out.append({"source_id": "static:" + row[5].removeprefix("TEXT_").lower(),
                            "kind": "catchable_static", "map_id": maps[map_constant], "map": map_constant,
                            "object_index": index, "x": int(row[0]), "y": int(row[1]),
                            "source_file": file.relative_to(repo).as_posix(), "object_symbol": label[1],
                            "species_index": species, "level": level, "species_rom_offset": pos + 6,
                            "level_rom_offset": pos + 7})
            pos += size
    return out


def npc_exchanges(repo: Path, syms: dict, rom: bytes, maps: dict, pokemon: dict) -> tuple[list, list]:
    trade_names = re.findall(r"^\s*const\s+(TRADE_FOR_\w+)", (repo / "constants/script_constants.asm").read_text(), re.M)
    rows = re.findall(r'^\s*npctrade\s+(\w+),\s*(\w+),\s*(\w+),\s*"([^"\n]+)"',
                      (repo / "data/events/trades.asm").read_text(), re.M)
    if len(trade_names) != len(rows) or len(rows) != 10:
        raise ValueError("NPC trade table inventory differs")
    base = flat(syms["TradeMons"])
    for index, (wanted, received, _dialog, _name) in enumerate(rows):
        record = rom[base + index * 14:base + (index + 1) * 14]
        if len(record) != 14 or record[0] != pokemon[wanted] or record[1] != pokemon[received] or 0x50 not in record[3:]:
            raise ValueError(f"NPC trade record bytes differ: {trade_names[index]}")
    sources, used = [], set()
    pattern = re.compile(r"(?:ld a,\s*(?P<trade>TRADE_FOR_\w+)|xor a)\s+ld \[wWhichTrade\], a")
    for file in sorted((repo / "scripts").glob("*.asm")):
        text = re.sub(r";[^\n]*", "", file.read_text())
        matches = list(pattern.finditer(text))
        calls = {match.start() for match in re.finditer(r"\bpredef DoInGameTradeDialogue\b", text)}
        assignments = re.findall(r"ld \[wWhichTrade\], a", text)
        if len(matches) != len(assignments):
            raise ValueError(f"unclassified NPC trade selector: {file}")
        reached = set()
        for match in matches:
            # Most scripts fall through immediately; the Cinnabar room shares
            # one dialogue tail between two independently selected trade rows.
            pos, visited = match.end(), set()
            for _ in range(16):
                if pos in visited:
                    raise ValueError(f"cyclic NPC trade selector: {file}")
                visited.add(pos)
                tail = text[pos:]
                whitespace = len(tail) - len(tail.lstrip())
                pos += whitespace
                tail = text[pos:]
                if tail.startswith("predef DoInGameTradeDialogue"):
                    reached.add(pos)
                    break
                if jump := re.match(r"(?:jr|jp) (\w+)\s*\n", tail):
                    label = re.search(rf"^{jump[1]}::?\s*\n", text, re.M)
                    if not label:
                        raise ValueError(f"unknown NPC trade jump: {file}")
                    pos = label.end()
                elif label := re.match(r"\w+::?\s*\n", tail):
                    pos += label.end()
                else:
                    raise ValueError(f"unsupported NPC trade selector path: {file}: {tail[:80]}")
            else:
                raise ValueError(f"NPC trade selector path is unbounded: {file}")
            index = trade_names.index(match["trade"]) if match["trade"] else 0
            if index in used:
                raise ValueError(f"NPC trade index has multiple sources: {index}")
            used.add(index)
            constant = map_name(repo, file.stem)
            sources.append({"source_id": "npc:" + constant.lower() + ":" + str(index), "kind": "npc_exchange",
                            "source_file": file.relative_to(repo).as_posix(), "map": constant, "map_id": maps[constant],
                            "trade_index": index, "trade_constant": trade_names[index],
                            "wanted_species_index": pokemon[rows[index][0]], "received_species_index": pokemon[rows[index][1]],
                            "record_rom_offset": base + index * 14,
                            "completion_note": "completion flag is set BEFORE animation and party replacement; flag alone is not delivery proof"})
        if reached != calls:
            raise ValueError(f"unclassified NPC trade dialogue call: {file}")
    unused = [{"index": index, "constant": name, "reason": "no map script invokes this trade index"}
              for index, name in enumerate(trade_names) if index not in used]
    return sources, unused


def build() -> dict:
    checked = verify(rom_dir=ROOT)
    if checked["status"] != "pass":
        raise ValueError("canonical sources failed: " + "; ".join(checked["failures"]))
    lock = json.loads((ROOT / "data/pret_sources.lock.json").read_text())
    codec = json.loads((ROOT / "data/games/gen1_rby/party_codec.json").read_text())
    result = {"schema": "gen1-rby-acquisition-sources-v1", "runtime_ready": False,
              "limitation": "Source census only. Transaction predicates, settlement, pairing policy and durable ordinals still require runtime proof.", "titles": {}}
    for title, (source, target) in TITLES.items():
        repo = ROOT / ".cache/pret" / source
        symbol_path = repo / (target + ".sym")
        syms = symbols(symbol_path)
        pin = lock["clean_roms"][target]
        rom = (ROOT / pin["filename"]).read_bytes()
        maps = map_ids(repo, syms, rom)
        pokemon = parse_pokemon_constants(str(repo / "constants/pokemon_constants.asm"))
        for file in (repo / "constants").glob("*.asm"):
            for name, target_name in re.findall(r"^DEF (\w+) EQU (\w+)\s*(?:;[^\n]*)?$", file.read_text(encoding='utf-8'), re.M):
                if target_name in pokemon:
                    pokemon[name] = pokemon[target_name]
        valid_species = {int(key) for key in codec["titles"][title]["species"]}
        sources, found = [], {}
        for file in [*sorted((repo / "scripts").glob("*.asm")), repo / "engine/events/prize_menu.asm"]:
            sites = call_sites(file, syms, rom)
            if not sites:
                continue
            name = file.relative_to(repo).as_posix()
            if name not in GRANTS:
                raise ValueError(f"unclassified script acquisition: {title}/{name}")
            group, map_constant, expected_count = GRANTS[name]
            if len(sites) != expected_count:
                raise ValueError(f"grant call count changed: {title}/{name}")
            found[name] = len(sites)
            for index, site in enumerate(sites):
                sources.append({"source_id": f"grant:{group}:{index}", "kind": "scripted_grant",
                                "source_file": name, "group": group, "map": map_constant, "map_id": maps[map_constant],
                                "yellow_only": group.startswith("yellow_"), **site})
        expected = {name for name in GRANTS if (repo / name).is_file()}
        # Red's Route24/Vermilion scripts exist too, but those Yellow-only grant
        # locations must not be mistaken for a requirement that Red grant them.
        if title != "yellow":
            expected -= {name for name, (group, _, _) in GRANTS.items() if group.startswith("yellow_")}
        else:
            expected.discard("scripts/MtMoonPokecenter.asm")  # Yellow moved this helper to _2.asm.
        if set(found) != expected:
            raise ValueError(f"missing grant source: {title}: {sorted(expected - set(found))}")
        sources.extend(monster_objects(repo, syms, rom, maps, pokemon, valid_species))
        sources.extend(scripted_battles(repo, syms, rom, maps, pokemon))
        trades, unused = npc_exchanges(repo, syms, rom, maps, pokemon)
        sources.extend(trades)
        sources.extend([
            {"source_id": "script-battle:unidentified-tower-ghost", "kind": "uncatchable_script_battle",
             "map_ids": [maps[f"POKEMON_TOWER_{floor}F"] for floor in range(1, 8)],
             "entry": address(syms["IsGhostBattle"]), "condition": "random wild battle in the Tower without the Silph Scope",
             "exclude_source_ids": ["script-battle:ghost-marowak"]},
        ])
        ids = [entry["source_id"] for entry in sources]
        if len(ids) != len(set(ids)):
            raise ValueError("source identities overlap")
        result["titles"][title] = {"sources": sorted(sources, key=lambda row: row["source_id"]), "unused_trade_rows": unused,
            "provenance": {"source_commit": lock["sources"][source]["commit"], "clean_sha1": pin["sha1"],
                           "full_symbols_sha256": hashlib.sha256(symbol_path.read_bytes()).hexdigest()},
            "grant_call_inventory": found}
    result["content_sha256"] = digest(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = build()
    content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != content:
            raise ValueError("acquisition source census differs; regenerate and review")
    else:
        OUTPUT.write_text(content, encoding="utf-8")
    counts = {title: len(row["sources"]) for title, row in data["titles"].items()}
    print(f"OK: acquisition source census {counts}; runtime predicates remain unqualified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
