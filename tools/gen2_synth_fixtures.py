"""O-33 synthetic SETUP fixtures for Gen 2 (docs/gen2/REVIEW_RECORD.md O-33): a qualified played save with a few
saved fields rewritten from pinned-decomp facts, so a live gate starts right before the behaviour under test.

build(title, base_bytes, edits) -> (bytes, disclosure). The edit writes the WRAM image of a saved field into BOTH save
copies (the gen2_codec layout regions: SavePlayerData/SavePokemonData/SaveCurMapData and their backups, C/G
engine/menus/save.asm), then restores both checksums (Checksum over [sGameData, sGameDataEnd) and the backup spans).
Everything else, including the 22-byte BizHawk RTC trailer, is copied verbatim. The disclosure lists every changed
field with its old and new bytes: oracles must never treat those bytes as evidence (O-33).

edits (all optional):
  party        [{species, level, moves, exp?, dvs?, hp?, status?, happiness?, egg?, nickname?}]: replaces the whole
               party. Stats come from gen2_codec.calc_stats over the species_index base stats (stat exp 0), PP from
               moves.json, OT id/name from the base save. An egg is the EGG marker in wPartySpecies, nickname "EGG",
               its hatch counter in the happiness byte (GiveEgg, C engine/pokemon/move_mon.asm; DoEggStep,
               engine/pokemon/breeding.asm:174-196).
  balls        [[item_const, quantity]]: replaces the Ball pocket (wNumBalls, wBalls).
  last_spawn   map_const: wLastSpawnMapGroup/Number, the whiteout destination (GetWhiteoutSpawn, engine/events/
               whiteout.asm:61-73; it must be a spawn point, data/maps/spawn_points.asm).
  step_count   wStepCount (DoEggStep runs when it reaches $80, engine/overworld/events.asm:880-900).
  poison_step  wPoisonStepCount (DoPoisonStep runs when it reaches 4, same routine).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

if __package__:
    from .gen2_source_data import ROOT, load_context
    from .gen_gen2_area_map import build_area_map
    from .gen_gen2_charmap import encode, parse_charmap
else:
    from gen2_source_data import ROOT, load_context
    from gen_gen2_area_map import build_area_map
    from gen_gen2_charmap import encode, parse_charmap

SCHEMA = "gen2-synth-disclosure-v1"
BUILDER = "tools/gen2_synth_fixtures.py"
CART = 0x8000
EGG_LEVEL = 5   # constants/pokemon_data_constants.asm EGG_LEVEL
DEFAULT_HAPPINESS = 70   # BASE_HAPPINESS, constants/pokemon_data_constants.asm
PSN = 1 << 3   # constants/battle_constants.asm PSN


def _codec():
    import sys
    if str(ROOT) not in sys.path:   # run as a script from tools/
        sys.path.insert(0, str(ROOT))
    from server.adapters import gen2_codec
    return gen2_codec


def _pack(root, title, name):
    return json.loads((Path(root) / "data/games" / f"gen2_{title}" / f"{name}.json").read_text(encoding="utf-8"))


class _Save:
    """The CartRAM image plus the WRAM -> (primary, backup) offset map of every saved region."""

    def __init__(self, raw, layout):
        self.raw, self.layout, self.fields = bytearray(raw), layout, []
        starts = {"player": "wPlayerData", "player1": "wPlayerData1", "player2": "wPlayerData2",
                  "player3": "wPlayerData3", "map": "wCurMapData", "pokemon": "wPokemonData"}
        self.spans = [(layout.addresses[starts[r.name]], r) for r in layout.regions]

    def _locate(self, address, size):
        for start, region in self.spans:
            if start <= address and address + size <= start + region.length:
                return region.primary + address - start, region.backup + address - start
        raise ValueError(f"WRAM {address:#06x}+{size} is not inside one saved region")

    def read(self, symbol, size, offset=0):
        primary, _ = self._locate(self.layout.addresses[symbol] + offset, size)
        return bytes(self.raw[primary:primary + size])

    def write(self, symbol, data, offset=0):
        data = bytes(data)
        address = self.layout.addresses[symbol] + offset
        primary, backup = self._locate(address, len(data))
        old = bytes(self.raw[primary:primary + len(data)])
        if old == data:
            return
        self.raw[primary:primary + len(data)] = data
        self.raw[backup:backup + len(data)] = data
        self.fields.append({"symbol": symbol, "offset": offset, "wram": address, "size": len(data),
                            "primary": primary, "backup": backup, "old_hex": old.hex(), "new_hex": data.hex()})

    def restore_checksums(self):
        codec = _codec()
        for copy_name in ("primary", "backup"):
            at = self.layout.checksum_offsets[copy_name]
            self.raw[at:at + 2] = codec.sav_checksum(bytes(self.raw[:CART]), self.layout, copy_name).to_bytes(2, "little")


def _name(text, charmap, size):
    raw = encode(text, charmap) + b"\x50"
    if len(raw) > size:
        raise ValueError(f"name too long: {text!r}")
    return raw + b"\x50" * (size - len(raw))


def party_mon(spec, *, layout, species, moves, ot_id):
    """One party_struct from a spec; returns (record bytes, species-list marker)."""
    codec = _codec()
    row = species[spec["species"]]
    egg = bool(spec.get("egg"))
    level = EGG_LEVEL if egg else spec["level"]
    dv_word = spec.get("dvs", 0xFFFF)
    dvs = codec.decode_dvs(dv_word)
    stats = codec.calc_stats(row["base_stats"], dvs, dict.fromkeys(codec.EXP_NAMES, 0), level)
    ids = [moves[name]["id"] for name in spec["moves"]]
    if not 1 <= len(ids) <= 4:
        raise ValueError("one to four moves required")
    ids += [0] * (4 - len(ids))
    pp = [moves[name]["pp"] for name in spec["moves"]] + [0] * (4 - len(spec["moves"]))
    exp = spec.get("exp", codec.exp_for_level(level, row["growth_rate"]))
    if codec.level_from_exp(exp, row["growth_rate"]) != level:
        raise ValueError(f"{spec['species']}: exp {exp} is not level {level}")
    hp = stats["hp"] if spec.get("hp") is None else spec["hp"]
    if not 0 <= hp <= stats["hp"]:
        raise ValueError("hp above max")
    mon = {"raw_hex": "00" * layout.party_size, "species_id": row["index"], "held_item": 0,
           "happiness": spec.get("happiness", DEFAULT_HAPPINESS), "pokerus": 0, "level": level, "ot_id": ot_id,
           "exp": exp, "dv_word": dv_word, "dvs": dvs, "stat_exp": dict.fromkeys(codec.EXP_NAMES, 0),
           "moves": ids, "pp": pp, "pp_ups": [0] * 4, "aux_bytes_hex": "0000", "status": spec.get("status", 0),
           "hp": hp, "max_hp": stats["hp"], "stats": {k: stats[k] for k in codec.STAT_NAMES[1:]}}
    return codec.encode_party_mon(mon, layout), layout.constants["EGG"] if egg else row["index"]


def build(title, base_bytes, edits, *, root=ROOT, base_name=None):
    codec = _codec()
    root = Path(root)
    if len(base_bytes) < CART:
        raise ValueError("base save shorter than CartRAM")
    layout = codec.for_foundation(title, root=root)
    if not codec.strict_checksum_witness(bytes(base_bytes[:CART]), layout)["valid"]:
        raise ValueError("base save copies/checksums are not valid")
    ctx = load_context(title, root=root)
    save = _Save(base_bytes[:CART], layout)
    facts = []
    if "party" in edits:
        index = _pack(root, title, "species_index")["species"]
        species = {row["const"]: dict(row, index=int(i)) for i, row in index.items()}
        moves = {m["constant"]: m for m in _pack(root, title, "moves")["moves"]}
        charmap = parse_charmap(ctx.read_source("constants/charmap.asm"))["encoding"]
        party = edits["party"]
        if not 1 <= len(party) <= 6:
            raise ValueError("party of 1..6 required")
        ot_id = int.from_bytes(save.read("wPlayerID", 2), "big")
        ot_name = save.read("wPlayerName", layout.name_size)
        records, markers, nicks = b"", [], b""
        for spec in party:
            record, marker = party_mon(spec, layout=layout, species=species, moves=moves, ot_id=ot_id)
            records += record
            markers.append(marker)
            text = "EGG" if spec.get("egg") else spec.get("nickname", species[spec["species"]]["name"])
            nicks += _name(text, charmap, layout.nickname_size)
        empty = 6 - len(party)
        save.write("wPartyCount", bytes([len(party)]))
        save.write("wPartySpecies", bytes(markers) + b"\xff" + b"\x00" * empty)
        save.write("wPartyMon1", records + b"\x00" * (layout.party_size * empty))
        save.write("wPartyMonOTs", ot_name * len(party) + b"\x00" * (layout.name_size * empty))
        save.write("wPartyMonNicknames", nicks + b"\x00" * (layout.nickname_size * empty))
        facts += ["data/games/gen2_<title>/species_index.json base stats/growth", "data/games/gen2_<title>/moves.json PP",
                  "constants/charmap.asm names", "macros/ram.asm party_struct"]
    if "balls" in edits:
        ids = {row["constant"]: int(i) for i, row in _pack(root, title, "items")["items"].items()}
        pocket = edits["balls"]
        size = layout.addresses["wNumPCItems"] - layout.addresses["wBalls"]
        body = b"".join(bytes([ids[name], qty]) for name, qty in pocket) + b"\xff"
        if len(body) > size:
            raise ValueError("Ball pocket overflow")
        save.write("wNumBalls", bytes([len(pocket)]))
        save.write("wBalls", body + b"\x00" * (size - len(body)))
        facts.append("data/games/gen2_<title>/items.json ids; engine/items/items.asm pocket layout")
    if "last_spawn" in edits:
        rows = {row["map_const"]: row for row in build_area_map(ctx).values()}
        row = rows[edits["last_spawn"]]
        spawns = ctx.read_source("data/maps/spawn_points.asm")
        if f"spawn {edits['last_spawn']}," not in spawns:
            raise ValueError("last_spawn is not a spawn point")
        save.write("wLastSpawnMapGroup", bytes([row["map_group"], row["map_number"]]))
        facts.append("data/maps/spawn_points.asm; engine/events/whiteout.asm GetWhiteoutSpawn")
    for key, symbol in (("step_count", "wStepCount"), ("poison_step", "wPoisonStepCount")):
        if key in edits:
            save.write(symbol, bytes([edits[key]]))
            facts.append("engine/overworld/events.asm CountStep")
    save.restore_checksums()
    raw = bytes(save.raw) + bytes(base_bytes[CART:])
    if not codec.strict_checksum_witness(raw[:CART], layout)["valid"]:
        raise ValueError("built save failed the strict checksum witness")
    disclosure = {"schema": SCHEMA, "builder": BUILDER, "title": title, "base_fixture": base_name,
                  "base_sha256": hashlib.sha256(bytes(base_bytes)).hexdigest(),
                  "sha256": hashlib.sha256(raw).hexdigest(), "edits": edits, "fields": save.fields,
                  "source_facts": sorted(set(facts)), "checksums": "restored (primary + backup)"}
    return raw, disclosure


# The U1G setup recipes (card U1G; the same bytes serve the DUO-WAVE-D duos). Name -> (base fixture, edits); a
# recipe is title-neutral, every constant resolves per title. Facts:
#   grass  Route 29 grass (the battle fixture's own position): Caterpie L6 one exp short of L7 (EVOLVE_LEVEL 7,
#          data/pokemon/evos_attacks.asm CaterpieEvosAttacks; GROWTH_MEDIUM_FAST L7 = 343), a Pidgey egg on its last
#          hatch cycle with wStepCount $7F (the next step runs DoEggStep), three fillers (party 5: one catch fills
#          it, the next goes to the box, PokeBallEffect .SendToPC), Master Balls (a certain native catch).
#   kyle   the town fixture (Elm's lab floor), a lone poisoned Bellsprout at 1 HP with wPoisonStepCount 3: the first
#          step faints it (DoPoisonStep, engine/events/poisonstep.asm) and whites out natively (OverworldWhiteoutScript)
#          to wLastSpawnMap = VIOLET_CITY, whose map objects then load natively (a CONTINUE would keep the base
#          map's object structs, data/maps/setup_scripts.asm MapSetupScript_Continue). NPC_TRADE_KYLE asks for a
#          BELLSPROUT (data/events/npc_trades.asm; maps/VioletKylesHouse.asm).
#   bill   the same whiteout to GOLDENROD_CITY, party of one (< PARTY_LENGTH, BillScript .NoRoom), EVENT_GOT_EEVEE
#          and EVENT_MET_BILL clear in the base (maps/BillsFamilysHouse.asm: Bill is home, givepoke EEVEE, 20).
SYNTH_RECIPES = {
    "grass": ("battle", {"party": [
        {"species": "CATERPIE", "level": 6, "exp": 342, "moves": ["TACKLE", "STRING_SHOT"], "dvs": 0x9A61},
        {"species": "PIDGEY", "egg": True, "happiness": 1, "moves": ["TACKLE"], "dvs": 0x5B72},
        {"species": "RATTATA", "level": 5, "moves": ["TACKLE", "TAIL_WHIP"], "dvs": 0x3C83},
        {"species": "SENTRET", "level": 5, "moves": ["SCRATCH", "DEFENSE_CURL"], "dvs": 0x7D94},
        {"species": "HOOTHOOT", "level": 5, "moves": ["TACKLE", "GROWL"], "dvs": 0x2EA5}],
        "balls": [["MASTER_BALL", 5]], "step_count": 0x7F}),
    "kyle": ("town", {"party": [{"species": "BELLSPROUT", "level": 10, "moves": ["VINE_WHIP", "GROWTH"],
                                 "dvs": 0x6B38, "hp": 1, "status": PSN}],
                      "poison_step": 3, "last_spawn": "VIOLET_CITY"}),
    "bill": ("town", {"party": [{"species": "SENTRET", "level": 5, "moves": ["SCRATCH", "DEFENSE_CURL"],
                                 "dvs": 0x4C29, "hp": 1, "status": PSN}],
                      "poison_step": 3, "last_spawn": "GOLDENROD_CITY"}),
}
SYNTH_FIXTURES = tuple(f"{title}_synth_{kind}" for title in ("crystal", "gold", "silver") for kind in SYNTH_RECIPES)


def build_named(name, *, root=ROOT):
    """(bytes, disclosure) for a SYNTH_FIXTURES name, from its committed base fixture."""
    title, _, kind = name.split("_", 2)
    target, edits = SYNTH_RECIPES[kind]
    base = f"{title}_{target}"
    raw = (Path(root) / "tests/fixtures/gen2" / f"{base}.SaveRAM").read_bytes()
    return build(title, raw, edits, root=root, base_name=base)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("names", nargs="*", default=list(SYNTH_FIXTURES))
    args = parser.parse_args(argv)
    out = Path(ROOT) / "tests/fixtures/gen2"
    for name in args.names:
        raw, disclosure = build_named(name)
        (out / f"{name}.SaveRAM").write_bytes(raw)
        (out / f"{name}.synth.json").write_text(json.dumps(disclosure, indent=1, sort_keys=True) + "\n",
                                                               encoding="utf-8")
        print(name, disclosure["sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
