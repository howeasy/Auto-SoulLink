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
  events       {"set": [EVENT_*], "clear": [EVENT_*]}: bits of wEventFlags (constants/event_flags.asm; an
               object_event's flag hides the object while set, e.g. EVENT_MET_BILL, set at new game by
               engine/events/std_scripts.asm InitializeEventsScript, cleared when Bill leaves Ecruteak).
  party_status {slot, status, hp}: rewrites ONE existing party slot's MON_STATUS/MON_HP bytes in place
               (constants/pokemon_data_constants.asm; macros/ram.asm party_struct), decoding/re-encoding the
               record through the same codec as `party` so every other field (species, moves, DVs, stat exp,
               nickname, OT) is carried over verbatim. Every other party slot is untouched. hp must be 1..the
               record's own MON_MAXHP (a synthetic faint is never handed to the game pre-fainted).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

if __package__:
    from .gen2_source_data import ROOT, load_context
    from .gen_gen2_area_map import build_area_map, source_lines
    from .gen_gen2_charmap import encode, parse_charmap
else:
    from gen2_source_data import ROOT, load_context
    from gen_gen2_area_map import build_area_map, source_lines
    from gen_gen2_charmap import encode, parse_charmap

SCHEMA = "gen2-synth-disclosure-v1"
BUILDER = "tools/gen2_synth_fixtures.py"
CART = 0x8000
SAVERAM = CART + 22   # the BizHawk 2.11.1 gambatte RTC trailer (tools/gen2_fixtures.SAVERAM_BYTES)
EDIT_KEYS = frozenset({"party", "balls", "last_spawn", "step_count", "poison_step", "events", "party_status"})
MAX_ITEM_STACK = 99   # MAX_ITEM_STACK, constants/item_constants.asm
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
        """SaveChecksum/SaveBackupChecksum (C/G engine/menus/save.asm): disclosed like any other field."""
        codec = _codec()
        for copy_name, symbol in (("primary", "sChecksum"), ("backup", "sBackupChecksum")):
            at = self.layout.checksum_offsets[copy_name]
            old = bytes(self.raw[at:at + 2])
            new = codec.sav_checksum(bytes(self.raw[:CART]), self.layout, copy_name).to_bytes(2, "little")
            self.raw[at:at + 2] = new
            if new != old:
                self.fields.append({"symbol": symbol, "offset": 0, "wram": None, "size": 2, "cart": at,
                                    "old_hex": old.hex(), "new_hex": new.hex()})


def event_ids(ctx, title):
    """EVENT_* -> bit index from constants/event_flags.asm: const_def, const, const_skip [n] and const_next n
    (rgbds macros/const.asm), over the title's conditional lines."""
    ids, value = {}, 0
    for _, line in source_lines(ctx.read_source("constants/event_flags.asm"), title):
        words = line.split()
        if not words:
            continue
        if words[0] == "const_def":
            value = int(words[1].replace("$", "0x"), 0) if len(words) > 1 else 0
        elif words[0] == "const_skip":
            value += int(words[1].replace("$", "0x"), 0) if len(words) > 1 else 1
        elif words[0] == "const_next":
            target = int(words[1].replace("$", "0x"), 0)
            if target < value:
                raise ValueError("const_next moves backwards")
            value = target
        elif words[0] == "const" and len(words) == 2:
            ids[words[1]] = value
            value += 1
    return ids


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
    # An egg may carry more exp than its level: HatchEggs keeps the struct level (EGG_LEVEL feeds CalcMonStats) and
    # never touches the exp (C engine/pokemon/breeding.asm HatchEggs), so the hatchling levels up on its first exp gain
    # (the gen2_evolution setup). Never below the level's floor; a non-egg's exp must match its level exactly.
    if egg and "exp" in spec:
        if exp < codec.exp_for_level(level, row["growth_rate"]):
            raise ValueError(f"{spec['species']}: egg exp {exp} is below level {level}")
    elif codec.level_from_exp(exp, row["growth_rate"]) != level:
        raise ValueError(f"{spec['species']}: exp {exp} is not level {level}")
    if egg and spec.get("hp") is not None:
        raise ValueError("an egg's HP is set by GiveEgg, not the spec")
    # GiveEgg zeroes an egg's current HP (C engine/pokemon/move_mon.asm:1210-1215)
    hp = 0 if egg else stats["hp"] if spec.get("hp") is None else spec["hp"]
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
    if len(base_bytes) != SAVERAM:
        raise ValueError(f"base save must be exactly {SAVERAM} bytes (CartRAM + RTC trailer)")
    unknown = set(edits) - EDIT_KEYS
    if unknown:
        # No direct map relocation: CONTINUE keeps the saved object structs and skips LoadMapObjects
        # (data/maps/setup_scripts.asm MapSetupScript_Continue), so a rewritten map would carry the base map's
        # NPCs. A recipe moves the player natively instead (last_spawn + a poison whiteout, SYNTH_RECIPES).
        raise ValueError(f"unsupported edit keys: {sorted(unknown)}")
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
        items = _pack(root, title, "items")["items"]
        ids = {row["constant"]: int(i) for i, row in items.items() if row.get("pocket") == "BALL"}
        pocket = edits["balls"]
        names = [name for name, _ in pocket]
        if len(set(names)) != len(names) or any(name not in ids for name in names)                 or any(not 1 <= qty <= MAX_ITEM_STACK for _, qty in pocket):
            raise ValueError("Ball pocket entries must be unique BALL-pocket items with 1..99 each")
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
    if "events" in edits:
        ids = event_ids(ctx, title)
        unknown = set(edits["events"]) - {"set", "clear"}
        if unknown:
            raise ValueError(f"unsupported events keys: {sorted(unknown)}")
        for op, names in sorted(edits["events"].items()):
            for name in names:
                index = ids[name]   # EventFlagAction: byte index // 8, bit index % 8 (home/flag.asm)
                byte = save.read("wEventFlags", 1, index // 8)[0]
                byte = byte | 1 << index % 8 if op == "set" else byte & ~(1 << index % 8) & 0xFF
                save.write("wEventFlags", bytes([byte]), index // 8)
        facts.append("constants/event_flags.asm; engine/events/std_scripts.asm InitializeEventsScript")
    for key, symbol in (("step_count", "wStepCount"), ("poison_step", "wPoisonStepCount")):
        if key in edits:
            save.write(symbol, bytes([edits[key]]))
            facts.append("engine/overworld/events.asm CountStep")
    if "party_status" in edits:
        spec = edits["party_status"]
        unknown = set(spec) - {"slot", "status", "hp"}
        if unknown:
            raise ValueError(f"unsupported party_status keys: {sorted(unknown)}")
        count = save.read("wPartyCount", 1)[0]
        slot = spec["slot"]
        if not isinstance(slot, int) or not 0 <= slot < count:
            raise ValueError("party_status slot outside the saved party")
        marker = save.read("wPartySpecies", 1, offset=slot)[0]
        record = save.read("wPartyMon1", layout.party_size, offset=slot * layout.party_size)
        mon = codec.decode_party_mon(record, layout, species_marker=marker)
        if not isinstance(spec["hp"], int) or not 0 < spec["hp"] <= mon["max_hp"]:
            raise ValueError("party_status hp must be 1..the slot's own MON_MAXHP")
        mon["status"], mon["hp"] = spec["status"], spec["hp"]
        save.write("wPartyMon1", codec.encode_party_mon(mon, layout), offset=slot * layout.party_size)
        facts.append("constants/pokemon_data_constants.asm MON_STATUS/MON_HP; macros/ram.asm party_struct")
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
#   bill   the same whiteout to GOLDENROD_CITY, party of one (< PARTY_LENGTH, BillScript .NoRoom); EVENT_MET_BILL
#          cleared (set at new game, it hides Bill at home until he leaves Ecruteak Pokecenter,
#          maps/EcruteakPokecenter1F.asm clearevent) and EVENT_GOT_EEVEE clear: givepoke EEVEE, 20.
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
                      "poison_step": 3, "last_spawn": "GOLDENROD_CITY",
                      # Bill is home only after he leaves Ecruteak (EcruteakPokecenter1F clears the flag)
                      "events": {"clear": ["EVENT_MET_BILL", "EVENT_GOT_EEVEE"]}}),
}
SYNTH_FIXTURES = tuple(f"{title}_synth_{kind}" for title in ("crystal", "gold", "silver") for kind in SYNTH_RECIPES)

# The DUO-WAVE-D duo setups (docs/gen2/reviews/DUO_WAVE_D_FACTS_2026-09-24.md; O-33). Same builder, same rules; the U1G
# `bill` recipe serves gen2_gift as is. The duo's B side on C<->C boots the <name>_ot2 copy, built the same way from the
# other-OT base (crystal_<target>_ot2).
#   full   Route 29 grass with a FULL party of six (no egg) and Master Balls: the first wild catch is a box catch
#          (PokeBallEffect .SendToPC, C engine/items/item_effects.asm:609-618), linked as route_29's first encounter.
#   hatch  Elm's lab (no wild tiles), [Sentret, a Pidgey egg on its last cycle], wStepCount $7F: the first step runs
#          DoEggStep (C engine/overworld/events.asm:894-898) and HatchEggs publishes the hatchling (gift_daycare, O-15).
#   trade  the kyle whiteout to VIOLET_CITY with the Bellsprout as an EGG in slot 2 and wStepCount $7E: step 1 in the
#          lab faints the poisoned Sentret (DoPoisonStep; the egg has HP 0, so CheckPlayerPartyForFitMon whites out),
#          step 2 in Violet City hatches the Bellsprout (a native gift_daycare link on both sides), and Kyle then trades
#          that LINKED mon (NPC_TRADE_KYLE wants BELLSPROUT, C/G data/events/npc_trades.asm:15).
DUO_RECIPES = {
    "full": ("battle", {"party": [
        {"species": "PIDGEY", "level": 5, "moves": ["TACKLE"], "dvs": 0x1A2B},
        {"species": "RATTATA", "level": 5, "moves": ["TACKLE", "TAIL_WHIP"], "dvs": 0x2B3C},
        {"species": "SENTRET", "level": 5, "moves": ["SCRATCH", "DEFENSE_CURL"], "dvs": 0x3C4D},
        {"species": "HOOTHOOT", "level": 5, "moves": ["TACKLE", "GROWL"], "dvs": 0x4D5E},
        {"species": "SPEAROW", "level": 5, "moves": ["PECK", "GROWL"], "dvs": 0x5E6F},
        {"species": "CATERPIE", "level": 5, "moves": ["TACKLE", "STRING_SHOT"], "dvs": 0x6F70}],
        "balls": [["MASTER_BALL", 5]]}),
    "hatch": ("town", {"party": [
        {"species": "SENTRET", "level": 5, "moves": ["SCRATCH", "DEFENSE_CURL"], "dvs": 0x4C29},
        {"species": "PIDGEY", "egg": True, "happiness": 1, "moves": ["TACKLE"], "dvs": 0x5B72}],
        "step_count": 0x7F}),
    "trade": ("town", {"party": [
        {"species": "SENTRET", "level": 5, "moves": ["SCRATCH", "DEFENSE_CURL"], "dvs": 0x4C29, "hp": 1, "status": PSN},
        {"species": "BELLSPROUT", "egg": True, "happiness": 1, "moves": ["VINE_WHIP", "GROWTH"], "dvs": 0x6B38}],
        "poison_step": 3, "step_count": 0x7E, "last_spawn": "VIOLET_CITY"}),
    # evolve  Route 29 grass, [a one-cycle Caterpie EGG at 342 exp (L7 = 343, GROWTH_MEDIUM_FAST; EVOLVE_LEVEL 7,
    #         data/pokemon/evos_attacks.asm CaterpieEvosAttacks), a filler], wStepCount $7F, an EMPTY Ball pocket: the
    #         first step hatches it (a native gift_daycare link), the next wild battle's exp lifts the hatchling to L7
    #         and EvolveAfterBattle publishes METAPOD (evolution_species_published). No Balls: no wild catch can
    #         form a second link, and the client's no_catch stays withheld.
    "evolve": ("battle", {"party": [
        {"species": "CATERPIE", "egg": True, "happiness": 1, "exp": 342, "moves": ["TACKLE", "STRING_SHOT"],
         "dvs": 0x9A61},
        {"species": "RATTATA", "level": 5, "moves": ["TACKLE", "TAIL_WHIP"], "dvs": 0x3C83}],
        "balls": [], "step_count": 0x7F}),
}
# gen2_gift reuses the U1G bill recipe; its C<->C B side needs the ot2 copy too.
DUO_FIXTURES = tuple(f"{title}_synth_{kind}" for title in ("crystal", "gold", "silver") for kind in DUO_RECIPES) + tuple(
    f"crystal_synth_{kind}_ot2" for kind in (*DUO_RECIPES, "bill"))

# gen2_faint_active_trainer's B seed (O-30 review MINOR-5; the final sweep's C-C run whited out when Youngster Joey's L4
# Rattata beat the native L5 starter after the forced party pick). The errand base (the only aisle to the Route 30
# trainers is open after the errand) with its starter at L10: Totodile's natural moves below L13 are SCRATCH, LEER and
# RAGE (C/G data/pokemon/evos_attacks.asm TotodileEvosAttacks). Only the lead's strength is synthetic; the link, the
# commanded death at the battle hold, the forced pick and the live turns stay native. The base keeps its OT, so the
# C-C B seed stays the second OT: crystal_battle_ot2_errand; G-S B is silver_battle_errand.
TRAINER_RECIPES = {
    "trainer": ("battle{ot2}_errand", {"party": [
        {"species": "TOTODILE", "level": 10, "moves": ["SCRATCH", "LEER", "RAGE"]}]}),
}
TRAINER_FIXTURES = ("crystal_synth_trainer_ot2", "silver_synth_trainer")

# gen2_trade_evolve's A seed (post-RC card TRADE-EVOLVE-CATCH; the RC sweep failed 4 of 6 link catches: the O-31 plant
# makes the first Route 29 wild mon a HAUNTER, catch rate 90, and the L5 Totodile's SCRATCH/LEER cannot touch a Ghost).
# The errand base with its Ball pocket replaced by Master Balls (PokeBallEffect skips the catch roll for MASTER_BALL,
# engine/items/item_effects.asm). Only the Ball pocket is synthetic; the plant, the catch, the link, the trade and B's
# evolution stay native. A is crystal_battle_errand on C-C and C-G, gold_battle_errand on G-S.
TRADE_RECIPES = {
    "trade_evolve": ("battle_errand", {"balls": [["MASTER_BALL", 5]]}),
}
TRADE_FIXTURES = ("crystal_synth_trade_evolve", "gold_synth_trade_evolve")

# card gen2-u1e-poison (O-33 fallback, owner-approved 2026-09-25): the Gold engine_sites U1 leg's own dice --
# walking to Route 31 and fighting Bug Catcher Wade (4 mons) until Poison Sting poisons a party mon -- is a
# proven, deterministic LOSS with today's driver (fsw-postrc-rr9/rr10: both party mons end up PSN and the
# second faints mid-walk, stalling on its own "fainted!" text box; getting poisoned is SETUP, not the behaviour
# under test). The errand base's own party is a lone Totodile (20/20 HP, unpoisoned, wPoisonStepCount already 3
# per the committed save -- DoPoisonStep ticks on the very first overworld step, engine/overworld/events.asm
# CountStep): party_status pins its MON_STATUS to PSN and its MON_HP to 12 (safely above the ~5-8 ticks the
# fsw-postrc-rr9 log shows elapse -- 276 frames -- before the leg's own Route 29 catch reaches "save_completed";
# far below its own 20 MON_MAXHP, so it faints a handful of ticks into the dedicated tick phase). The lead still
# fights the Route29 catch battle unpoisoned in effect (no overworld steps tick during a battle), and the
# caught second mon is never touched, so the later battle_faint leg still has a healthy, unpoisoned survivor.
PSN_RECIPES = {
    "psn": ("battle_errand", {"party_status": {"slot": 0, "status": PSN, "hp": 12}}),
}
PSN_FIXTURES = ("gold_synth_psn",)


CLOCK_SCHEMA = "gen2-clock-setup-v1"


def start_time(raw, title):
    """(wStartHour, wStartMinute, wStartSecond) from the save: the in-game time set at new game, which FixTime
    adds to the RTC (pokegold/pokecrystal home/time.asm FixTime). The played fixtures carry 09:58:5x, not a
    round 10:00."""
    save = _Save(bytes(raw[:CART]), _codec().for_foundation(title, root=ROOT))
    _day, hour, minute, second = save.read("wStartDay", 4)
    return hour, minute, second


def day_clock(raw, *, hour, now, title):
    """O-33 clock setup: (bytes, disclosure) with only the 22-byte BizHawk gambatte RTC trailer rewritten so the
    game reads `hour`:00:00 at host time `now`. The trailer is emulator state, never save data (docs/gen2/reviews/
    OMP_RTC_SOURCE_2026-09-22.md): an 8-byte big-endian base time, then dh, dl, h, m, s, the cycle counter and
    the latched copies (libgambatte cartridge.cpp :504-580). The RTC runs on from base to host time, so the game
    clock of a played fixture drifts with the wall clock (EVO-U1: silver_battle read 19:xx at 08:23 local).
    Game time = the save's wStart time + RTC (FixTime). The RTC only moves forward (to the next matching
    instant), and CartRAM is untouched. The disclosure (gen2-clock-setup-v1) re-derives from the base bytes:
    verify_gen2_release re-runs this function on the committed fixture and compares every field."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != SAVERAM:
        raise ValueError(f"base save must be exactly {SAVERAM} bytes (CartRAM + RTC trailer)")
    start_h, start_m, start_s = start_time(raw, title)
    tail = bytearray(raw[CART:])
    base, dh, dl, h, m, s = int.from_bytes(tail[:8], "big"), *tail[8:13]
    if dh & 0x40:
        raise ValueError("the RTC is halted")
    total = (((dh & 1) << 8) | dl) * 86400 + h * 3600 + m * 60 + s + max(0, now - base)
    total += (hour * 3600 - (start_h * 3600 + start_m * 60 + start_s) - total) % 86400
    days = total // 86400
    if days > 511:
        raise ValueError("the RTC day counter would overflow")
    regs = [(dh & 0xFE) | (days >> 8), days & 0xFF, total // 3600 % 24, total // 60 % 60, total % 60]
    tail[:8] = int(now).to_bytes(8, "big")
    tail[8:13] = bytes(regs)
    tail[17:22] = bytes(regs)   # the latched copies
    out = bytes(raw[:CART]) + bytes(tail)
    return out, {"schema": CLOCK_SCHEMA, "builder": BUILDER, "title": title, "field": "BizHawk gambatte RTC trailer",
                 "game_hour": hour, "host_time": int(now), "start_time": [start_h, start_m, start_s],
                 "base_sha256": hashlib.sha256(bytes(raw)).hexdigest(),
                 "old_hex": bytes(raw[CART:]).hex(), "new_hex": bytes(tail).hex(),
                 "cartram_sha256": hashlib.sha256(out[:CART]).hexdigest(), "sha256": hashlib.sha256(out).hexdigest(),
                 "source_facts": ["home/time.asm FixTime: game time = wStartHour/Minute/Second + RTC",
                                  "libgambatte cartridge.cpp:504-580: the 22-byte RTC trailer"]}


def build_named(name, *, root=ROOT):
    """(bytes, disclosure) for a SYNTH_FIXTURES, DUO_FIXTURES, TRAINER_FIXTURES or TRADE_FIXTURES name, from its base
    committed fixture. A target with an {ot2} slot places the other-OT marker inside the base name (battle_ot2_errand)."""
    title, _, kind = name.split("_", 2)
    ot2 = kind.endswith("_ot2")
    kind = kind.removesuffix("_ot2")
    target, edits = {**SYNTH_RECIPES, **DUO_RECIPES, **TRAINER_RECIPES, **TRADE_RECIPES, **PSN_RECIPES}[kind]
    marker = "_ot2" if ot2 else ""
    base = f"{title}_{target.format(ot2=marker)}" if "{ot2}" in target else f"{title}_{target}{marker}"
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
