"""One inactive Gen 2 rules/presentation adapter, selected by an explicit title.

Consumes generated C/G/S facts, not the legacy Crystal tables. Pack consistency
checks are not ROM/runtime admission. Native capabilities stay disabled.
SOURCE: pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651 and
pokegold@656583c939d30f920a316177311a502dd222b57c; per-pack source receipts.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from . import gen2_codec
from .base import GameAdapter, gb_status_token, humanize_area_id

_DATA = Path(__file__).resolve().parents[2] / "data" / "games"
_ARTIFACT = {"crystal": "pokecrystal", "gold": "pokegold", "silver": "pokesilver"}
# Title binder: every Gen 2 hello spelling (server/adapters/__init__.py rows) -> its title.
# `crystal_ap` / "Crystal (AP)" are absent on purpose (O-8): they bind no title.
_TITLE_FOR_ROM_TYPE = {spelling: title for title in _ARTIFACT
                       for spelling in (title, title.capitalize())}
_COMMITS = {"pokecrystal": "7a7881d0d62e0ddbd82dcf10e7116807487ac651",
            "pokegold": "656583c939d30f920a316177311a502dd222b57c"}
_ROMS = {"crystal": "f4cd194bdee0d04ca4eac29e09b8e4e9d818c133",
         "gold": "d8b8a3600a465308c9953dfa04f0081c05bdcb94",
         "silver": "49b163f7e57702bc939d642a18f591de55d92dae"}
_KEY = re.compile(r"([0-9A-Fa-f]{4}):([0-9A-Fa-f]{4}):([0-9A-Fa-f]{2})")
_AREA = re.compile(r"[a-z][a-z0-9_]*")
# O-16 (docs/gen2/RESUME.md:61): the pack's own static area id is
# static_<lowercase map constant>_<species> -- title-independent, so a Crystal/Gold pair
# lands in ONE gift area. The trailing number is the NatDex species (tools/gen_gen2_statics.py).
_STATIC = re.compile(r"static_[a-z][a-z0-9_]*_([1-9][0-9]{0,2})\Z")
_LEGEND = re.compile(r"legend_([1-9][0-9]{0,2})\Z")
_SPLIT = {"Physical": 0, "Special": 1, "Status": 2}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, f"duplicate pack key: {path.name}/{key}")
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text("utf-8"), object_pairs_hook=unique)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unavailable or invalid Gen 2 pack: {path.name}") from error
    _require(isinstance(value, dict), f"pack must be an object: {path.name}")
    return value


def _display(value):
    return value.title().replace("'D", "'d")


class Gen2GSCAdapter(GameAdapter):
    """Game facts only; constructing this object cannot activate a runtime route.

    ``data_root`` contains the three gen2_<title> directories. No source clone,
    compiler, ROM or legacy adapter is needed at runtime. A release manifest
    must separately authenticate pack bytes; this loader checks their coherence.
    """

    def __init__(self, title: str | None = None, *, rom_type: str | None = None,
                 is_rr: bool = False, artifact_kind: str | None = None, data_root: Path = _DATA):
        # The generic factory (get_adapter on hello, persisted reload, rom_content) passes
        # rom_type/is_rr/artifact_kind, never a title: bind the title from rom_type here.
        if rom_type is not None:
            bound = _TITLE_FOR_ROM_TYPE.get(rom_type)
            _require(bound is not None and title in (None, bound), f"no Gen 2 title for rom_type {rom_type!r}")
            title = bound
        _require(not is_rr, "Gen 2 has no Radical Red layout")
        _require(isinstance(title, str) and title in _ARTIFACT, "explicit supported Gen 2 title required")
        self.title = title
        directory = Path(data_root) / f"gen2_{title}"
        profile = _json(directory / "profile.json")
        _require(profile.get("schema") == "gen2-profile-v1"
                 and set(profile.get("titles", {})) == {title}, "selected profile/title mismatch")
        self.source = copy.deepcopy(profile.get("source", {}))
        repo = "pokecrystal" if title == "crystal" else "pokegold"
        _require(self.source.get("artifact") == _ARTIFACT[title]
                 and self.source.get("repo") == repo
                 and self.source.get("commit") == _COMMITS[repo]
                 and self.source.get("rom_sha1") == _ROMS[title]
                 and self.source.get("evidence_level") == "SOURCE", "profile source/title mismatch")
        for name in ("sym_sha256", "map_sha256", "lock_sha256", "build_provenance_sha256"):
            _require(isinstance(self.source.get(name), str)
                     and re.fullmatch(r"[0-9a-f]{64}", self.source[name]), f"missing source hash: {name}")
        self._layout = gen2_codec.Gen2Layout.from_profile(profile, title)

        def load(name, schema):
            data = _json(directory / f"{name}.json")
            _require(data.get("schema") == schema, f"{name}: unsupported pack schema")
            _require(data.get("source") == self.source, f"{name}: source provenance mismatch")
            if name not in {"gifts", "static_encounters"}:
                _require(data.get("title") == title, f"{name}: title mismatch")
            return data

        species = load("species_index", "gen2-species-v1")
        self._species = {int(key): value for key, value in species["species"].items()}
        _require(set(self._species) == set(range(1, 252)), "species pack must contain exactly 1..251")
        _require(species.get("egg", {}).get("index") == 253, "egg marker mismatch")
        self._types = {}
        for ident, row in self._species.items():
            _require(row.get("national_dex") == ident and species["index_to_national"].get(str(ident)) == ident,
                     "Gen 2 species/National Dex mismatch")
            _require(isinstance(row.get("name"), str) and _integer(row.get("gender_ratio"), 0, 255),
                     "invalid species name or raw gender ratio")
            _require(len(row.get("type_ids", [])) == len(row.get("types", [])) == 2, "invalid species types")
            for number, name in zip(row["type_ids"], row["types"], strict=True):
                _require(_integer(number, 0, 27) and isinstance(name, str), "invalid type declaration")
                display = _display(name.removesuffix("_TYPE"))
                _require(number not in self._types or self._types[number] == display, "conflicting type names")
                self._types[number] = display
        evolution = load("evolutions", "gen2-evolutions-v1")
        self._families = {int(key): value for key, value in evolution["family"].items()}
        _require(set(self._families) == set(self._species), "incomplete evolution families")
        _require(all(_integer(value, 1, 251) and self._families[value] == value
                     for value in self._families.values()), "invalid evolution family representative")
        self._items = {int(key): value for key, value in load("items", "gen2-items-v1")["items"].items()}
        _require(set(self._items) == set(range(1, 255)), "incomplete item-attribute inventory")
        for row in self._items.values():
            _require(isinstance(row.get("name"), str)
                     and (isinstance(row.get("constant"), str)
                          or row.get("constant") is None and row.get("placeholder") is True)
                     and type(row.get("placeholder")) is bool and type(row.get("key_item")) is bool
                     and type(row.get("mail")) is bool
                     and _integer(row.get("permissions"), 0, 255), "invalid item attributes")
        moves = load("moves", "gen2-moves-v1")["moves"]
        self._moves = {row["id"]: row for row in moves}
        _require(len(moves) == 251 and set(self._moves) == set(range(1, 252)), "incomplete/duplicate move pack")
        for row in moves:
            _require(row.get("split") in _SPLIT and _integer(row.get("type_id"), 0, 27)
                     and isinstance(row.get("type"), str),
                     "invalid move type or split")
            # Curse's native ??? type (19) has no base-species counterpart.
            number, name = row["type_id"], row["type"]
            _require(number not in self._types or self._types[number] == name, "conflicting move type")
            self._types[number] = name
        self._encounters = load("encounter_tables", "gen2-encounter-tables-v1")
        policy = self._encounters.get("policy", {})
        _require(policy.get("egg_hatch_area") == "gift_daycare"
                 and policy.get("roamer_area") == "legend_<species>"
                 and policy.get("contest_area") == "national_park_contest"
                 and policy.get("roamer_consumes_ordinary_area") is False, "acquisition policy mismatch")
        self._roamers = {row["species"] for row in self._encounters["roamers"]["initial"]}
        _require(self._roamers and self._roamers <= self._species.keys(), "invalid roamer inventory")
        # Story caller facts remain source candidates, not permission to label a
        # whole route/city a gift or automatically bypass fixed-species clauses.
        self._gifts = load("gifts", "gen2-gifts-v1")["gifts"]
        statics = load("static_encounters", "gen2-static-encounters-v1")["encounters"]
        selected_statics = [row for row in statics if row.get("applicability", {}).get("selected")
                            and not row.get("source_unused")]
        # Every selected row carries its own canonical area id (gen2-static-canon, O-16):
        # static_<lowercase map constant>_<species>, or legend_<species> where the
        # generator's O-21 override applies (Crystal's Tin Tower Suicune, whose area_id
        # is the same value). The id SET is the whole membership check -- a numeric
        # group*256+number id or an invented one is refused, and the species suffix must
        # be the row's own species.
        self._static_ids = set()
        for row in selected_statics:
            canonical = row.get("static_area_id")
            _require(isinstance(canonical, str), "static row missing canonical area id")
            if (legend := _LEGEND.fullmatch(canonical)) is not None:
                _require(int(legend[1]) == row["species"], "static legend area/species mismatch")
            else:
                match = _STATIC.fullmatch(canonical)
                _require(match is not None and int(match[1]) == row["species"],
                         "static canonical area/species mismatch")
            self._static_ids.add(canonical)
        self._legend_species = self._roamers | {
            int(match[1]) for row in selected_statics
            if (match := _LEGEND.fullmatch(row["static_area_id"]))}
        self._areas = _json(directory / "area_map.json")
        self._area_names = {}
        for key, row in self._areas.items():
            _require(int(key) == row["map_group"] * 256 + row["map_number"], "map identity mismatch")
            _require(row["source"]["artifact"] == _ARTIFACT[title]
                     and row["source"]["commit"] == _COMMITS[repo], "map title/source mismatch")
            _require(_AREA.fullmatch(row["area_id"]) is not None, "invalid generated area id")
            _require(self._encounters["map_areas"].get(key) == row["area_id"], "encounter/map area mismatch")
            self._area_names[row["area_id"]] = _display(row["name"])
        self._tables = self._presentation_tables()
        if artifact_kind is not None:
            self.set_artifact_kind(artifact_kind)

    @property
    def game_id(self):
        return "gen2_gsc"

    # ── per-player binding (card gen2-U4b) ───────────────────────────────────────────────
    # One pairing foundation, three packs: the run's adapter is locked to whichever title
    # said hello first (the binder above), so a partner running another title would be
    # answered with the other cartridge's species, encounters and items. Declaring these two
    # methods is the WHOLE gate shared code reads -- server.py's hello path resolves them
    # with getattr and branches on nothing else, so no title, rom_type or game_id test
    # exists there. An adapter that declares neither (every other generation) keeps the one
    # run-level adapter for both players.
    def per_player_key(self, rom_type):
        """The key `rom_type` binds per player, or None for a spelling this pack does not own.

        A key is opaque to shared code: it is only ever compared with `per_player_bound_key`.
        """
        return _TITLE_FOR_ROM_TYPE.get(rom_type)

    def per_player_bound_key(self):
        """This adapter's own key -- the one a hello must DIFFER from to need its own adapter."""
        return self.title

    def is_valid_mon_key(self, key):
        match = _KEY.fullmatch(key) if isinstance(key, str) else None
        return bool(match and 1 <= int(match[3], 16) <= 251)

    def parse_ot_id(self, key):
        return key.split(":")[1].upper() if self.is_valid_mon_key(key) else ""

    def gender_from_key(self, key, species_id):
        if not self.is_valid_mon_key(key) or not _integer(species_id, 1, 251) or int(key[-2:], 16) != species_id:
            return ""
        ratio = self._species[species_id]["gender_ratio"]
        # GetGender, engine/pokemon/mon_stats.asm: C line 124 / G line 126:
        # b = AttackDV * 16 + SpeedDV; female when ratio >= b.
        if ratio == 255:
            return "genderless"
        if ratio == 254:
            return "female"
        if ratio == 0:
            return "male"
        dvs = int(key[:4], 16)
        combined = (dvs >> 8 & 0xF0) | (dvs >> 4 & 0x0F)
        return "female" if combined <= ratio else "male"

    def is_shiny(self, key):
        if not self.is_valid_mon_key(key):
            return False
        # engine/gfx/color.asm:3-43: Attack bit 1; Defense/Speed/Special exactly 10.
        dvs = int(key[:4], 16)
        return bool(dvs & 0x2000) and dvs & 0x0FFF == 0x0AAA

    def species_name(self, species_id):
        return _display(self._species[species_id]["name"]) if _integer(species_id, 1, 251) else (
            f"#{species_id}" if type(species_id) is int else "#?")

    def species_types(self, species_id):
        return tuple(self._species[species_id]["type_ids"]) if _integer(species_id, 1, 251) else None

    def type_name(self, type_id):
        return self._types.get(type_id, f"Type #{type_id}") if type(type_id) is int else "Unknown"

    def evo_family(self, species_id):
        return self._families[species_id] if _integer(species_id, 1, 251) else species_id

    def to_national_dex(self, species_id):
        return species_id if _integer(species_id, 1, 251) else 0

    def is_valid_held_item(self, item_id):
        if not _integer(item_id, 0, 254):
            return False
        if item_id == 0:
            return True
        row = self._items.get(item_id)
        # CANT_TOSS bit 7, constants/item_data_constants.asm:33-35 and
        # _CheckTossableItem, engine/items/items.asm:494-501. Mail (O-14) never
        # travels: a 70-byte mon cannot carry its sPartyMail entry. The flag is the
        # engine's MailItems list (data/items/mail_items.asm:1-12, both pins, read by
        # ItemIsMail C engine/pokemon/mail_2.asm:941-945, G :922-926), never a name.
        return bool(row and not row["placeholder"] and not row["key_item"]
                    and not row["permissions"] & 0x80 and not row["mail"])

    def item_name(self, item_id):
        if not _integer(item_id, 1, 254):
            return ""
        row = self._items.get(item_id)
        return _display(row["name"]) if row and not row["placeholder"] else ""

    def move_name(self, move_id):
        row = self._moves.get(move_id) if type(move_id) is int else None
        return row["name"] if row else ""

    def move_data(self, move_id):
        row = self._moves.get(move_id) if type(move_id) is int else None
        if row is None:
            return None
        return {"name": row["name"], "type_id": row["type_id"], "type_name": row["type"],
                "power": row["power"], "accuracy": row["accuracy"], "pp": row["pp"],
                "split": _SPLIT[row["split"]], "effect_chance": row["effect_chance"]}

    def party_blob_size(self):
        return self._layout.party_size + self._layout.name_size + self._layout.nickname_size

    def decode_party_blob(self, blob, *, species_marker=None):
        if isinstance(blob, str):
            _require(re.fullmatch(r"[0-9A-Fa-f]{140}", blob) is not None, "malformed 70-byte party blob")
            blob = bytes.fromhex(blob)
        mon = gen2_codec.decode_party_blob(blob, self._layout, species_marker=species_marker)
        mon["key"] = gen2_codec.key(mon)
        return mon

    def validate_party_blob(self, blob, *, key=None, species_marker=None):
        """Transfer shape/facts only, never write eligibility or egg detection.

        Every call requires the separately supplied species-list marker; its
        absence refuses rather than inferring non-egg status. Names retain
        all 11 bytes each. Mail/key-item/placeholder transfers remain refused.
        """
        try:
            mon = self.decode_party_blob(blob, species_marker=species_marker)
            return (self.is_valid_held_item(mon["held_item"])
                    and all(_integer(move, 0, 251) for move in mon["moves"])
                    and (key is None or self.is_valid_mon_key(key) and mon["key"] == key.upper()))
        except (ValueError, TypeError):
            return False

    def _legend(self, area_id):
        match = _LEGEND.fullmatch(area_id) if isinstance(area_id, str) else None
        return bool(match and int(match[1]) in self._legend_species)

    def is_gift_area(self, area_id):
        if not isinstance(area_id, str) or _AREA.fullmatch(area_id) is None:
            return False
        return (area_id.startswith("gift_") and len(area_id) > 5 or self._legend(area_id)
                or area_id in self._static_ids)

    def is_daycare_area(self, area_id):
        return area_id == "gift_daycare"

    def is_egg_pickup_area(self, area_id):
        # O-15: capture is at hatch, never GiveEgg or daycare pickup.
        return False

    def gift_link_area(self, area_id, *, acquisition=None, species_id=None):
        """Namespace facts; an upstream source-qualified event must supply origin.

        Optional keywords are additive to the shared one-argument hook. Existing
        calls cannot infer roaming/hatch causes from a route or changed mon key.
        """
        _require(isinstance(area_id, str) and _AREA.fullmatch(area_id), "invalid acquisition area")
        if acquisition is not None:
            _require(_integer(species_id, 1, 251), "acquisition requires actual species, not EGG")
            if acquisition == "egg_hatch":
                return "gift_daycare"
            if acquisition == "roamer":
                _require(species_id in self._roamers, "species is not a selected-title roamer")
                return f"legend_{species_id}"
            if acquisition == "contest":
                return "national_park_contest"
            _require(acquisition == "gift", "unqualified acquisition kind; egg pickup is not capture")
        if area_id.startswith("legend_"):
            _require(self._legend(area_id), "invalid selected-title legendary namespace")
        if area_id == "national_park_contest" or self.is_gift_area(area_id):
            return area_id
        return super().gift_link_area(area_id)

    def area_display_name(self, area_id):
        if not isinstance(area_id, str) or _AREA.fullmatch(area_id) is None:
            return ""
        if self._legend(area_id):
            return self.species_name(int(area_id.removeprefix("legend_")))
        return {"gift_daycare": "Egg Hatch", "national_park_contest": "Bug-Catching Contest"}.get(
            area_id, self._area_names.get(area_id, humanize_area_id(area_id)))

    def _presentation_tables(self):
        """Keep maps, times and slot rows distinct; rates are table probabilities."""
        grouped = {}

        def emit(key, label, slots, weights, **metadata):
            map_row = self._areas.get(str(key))
            _require(map_row is not None, "encounter refers to missing map")
            # A selected swarm table replaces normal lookup; it is not another
            # set of slots in the same distribution (C wildmons.asm:384-393,
            # G:401-410). Keep table identity until presentation labels exist.
            target = grouped.setdefault((map_row["area_id"], label, key,
                                         metadata.get("source_table")), [])
            for slot, (entry, weight) in enumerate(zip(slots, weights, strict=True)):
                species = entry["species"]
                _require(_integer(species, 1, 251), "unresolved encounter species")
                level = entry.get("level")
                target.append({"species_id": species, "name": self.species_name(species), "rate": weight,
                               "min_level": entry.get("min_level", level),
                               "max_level": entry.get("max_level", level), "slot": slot,
                               "map_group": map_row["map_group"], "map_number": map_row["map_number"],
                               "map_name": map_row["map_name"], **metadata})

        wild = self._encounters["wild"]
        for kind in ("grass", "water"):
            thresholds = [row["threshold"] for row in wild[f"{kind}_probabilities"]]
            _require(thresholds == sorted(set(thresholds)) and thresholds[-1] == 100, "wild slot probabilities invalid")
            weights = [high - low for low, high in zip([0, *thresholds[:-1]], thresholds, strict=True)]
            for row in wild[kind]:
                label = "Surf" if kind == "water" else {"morning": "Morn", "day": "Day", "night": "Nite"}[row["time"]]
                emit(row["map_group"] * 256 + row["map_number"], label, row["slots"], weights,
                     encounter_rate_byte=row["rate"], time=row["time"], source_table=row["table"])
        tree = self._encounters["tree"]
        sets = {row["set_id"]: row for row in tree["sets"]}
        limit = tree.get("enabled_set_limit")
        _require(_integer(limit, 2, 255) and sorted(sets) == list(range(1, limit)), "tree set gate invalid")
        for kind, maps in (("Headbutt", tree["headbutt_maps"]), ("Rock Smash", tree["rock_smash_maps"])):
            for row in maps:
                # GetTreeMons refuses set 0 and sets >= the generated bound
                # (C engine/events/treemons.asm:100-105, G :98-102: G/S UNUSED, CITY).
                if not 0 < row["set_id"] < limit:
                    continue
                _require(row["set_id"] in sets, "unknown encounter tree set")
                source = sets[row["set_id"]]
                for rarity in ("common", "rare"):
                    slots = source[rarity]
                    if slots:
                        emit(row["map_group"] * 256 + row["map_number"],
                             kind + (f" {rarity.title()}" if kind == "Headbutt" else ""),
                             slots, [entry["weight"] for entry in slots], set_id=row["set_id"])
        fishing = self._encounters["fishing"]
        groups = {row["group_id"]: row for row in fishing["groups"]}
        times = {row["group_id"]: row for row in fishing["time_groups"]}
        for key, area in self._areas.items():
            group = groups.get(area["fishing_group"])
            if group is None:
                _require(area["fishing_group"] == 0, "unknown map fishing group")
                continue
            # A rod needs a water quadrant it can stand beside: header fish groups alone
            # reach indoor maps that hold no water at all (review F3, OMP N7). The flag is
            # source/ROM-derived by tools/gen_gen2_area_map.py; the obligation stays OPEN
            # until a fixture actually fishes, so the rows keep UNQUALIFIED below.
            _require(isinstance(area.get("fishing_water"), bool), "missing fishing_water flag")
            if not area["fishing_water"]:
                continue
            for rod in ("old", "good", "super"):
                # fish.asm .loop accepts <= threshold. Random spans 0..255;
                # rates below are conditional on a bite, whose threshold is separate.
                thresholds = [entry["threshold"] for entry in group[rod]]
                _require(thresholds == sorted(set(thresholds)) and thresholds[-1] == 255, "fish thresholds invalid")
                weights = [(high - low) * 100 / 256 for low, high in zip([-1, *thresholds[:-1]], thresholds, strict=True)]
                for daytime, label in (("day", "Morn/Day"), ("night", "Nite")):
                    slots = [entry if entry["species"] else times[entry["level"]][daytime] for entry in group[rod]]
                    emit(int(key), f"{rod.title()} Rod ({label})", slots, weights,
                         fish_group=group["group_id"], bite_threshold=group["bite_threshold"],
                         selection_scope="base_group; runtime swarm selection OPEN",
                         # ponytail: known limitation, not a catchable-set claim. Rod rows are
                         # gated on the source/ROM-derived fishing_water flag, but
                         # fishing_map_association (gen2_rom_scan OPEN_OBLIGATIONS) stays OPEN
                         # until a fixture fishes: connection strips, walkable-region
                         # connectivity and runtime swarm selection are not modelled.
                         map_association="UNQUALIFIED")
        tables, maps_by_method, tables_by_map = {}, {}, {}
        for area, label, key, source_table in grouped:
            maps_by_method.setdefault((area, label), set()).add(key)
            tables_by_map.setdefault((area, label, key), set()).add(source_table)
        for (area, label, key, source_table), slots in grouped.items():
            method = label
            if source_table is not None and len(tables_by_map[area, method, key]) > 1:
                label += " (Swarm)" if source_table.startswith("Swarm") else " (Normal)"
            if len(maps_by_method[area, method]) > 1:
                label += f" ({self._areas[str(key)]['map_name']})"
            target = tables.setdefault(area, {})
            _require(label not in target, "encounter presentation variants collide")
            target[label] = slots
        contest = self._encounters["contest"]
        tables["national_park_contest"] = {"Contest": [
            {"species_id": row["species"], "name": self.species_name(row["species"]), "rate": row["weight"],
             "min_level": row["min_level"], "max_level": row["max_level"], "slot": index}
            for index, row in enumerate(contest["slots"])]}
        return tables

    def encounter_table(self, area_id):
        return copy.deepcopy(self._tables.get(area_id))

    def rom_content_fingerprint(self, payload):
        raise ValueError("Gen 2 client ROM-content admission is not qualified")

    def ingest_rom_content(self, payload):
        raise ValueError("Gen 2 client ROM-content admission is not qualified")

    def set_artifact_kind(self, kind):
        _require(kind == "clean", "Gen 2 overlay/native artifact capabilities are not qualified")

    @staticmethod
    def pairing_kind(kind):
        return kind  # Do not inherit named -> clean artifact equivalence.

    def supports_abilities(self):
        return False

    def supports_info_panel(self):
        return False

    def native_trade_ui(self):
        return False

    def supports_explode_mode(self):
        return False

    def info_panel_width(self):
        return 0

    def rival_trainer_ids(self):
        return set()

    @property
    def mons_per_box(self):
        return self._layout.constants["MONS_PER_BOX"]

    @property
    def memorial_box_index(self):
        return self._layout.constants["NUM_BOXES"] - 1

    def status_token(self, status_cond):
        return gb_status_token(status_cond) if _integer(status_cond, 0, 255) else ""

    def sprite_src(self, species_id):
        if not _integer(species_id, 1, 251):
            return ""
        folder = "crystal/transparent" if self.title == "crystal" else self.title
        return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-ii/{folder}/{species_id}.png"

    def sprite_html(self, species_id, form=0):
        source = self.sprite_src(species_id)
        return (f'<img class="mon-sprite" data-species="{species_id}" src="{source}" '
                'width="40" height="40" loading="lazy" style="image-rendering:pixelated">') if source else ""

    def ability_name(self, ability_id, species_id=0):
        return ""

    def ability_description(self, ability_id):
        return ""

    def trainer_info(self, trainer_id):
        # Base's single id cannot identify the Gen 2 (class, instance) pair.
        # No guessed packing convention or rival-team injection is activated.
        return "", ""

    def gender_symbol(self, gender):
        return {"male": "♂", "female": "♀"}.get(gender, "")

    def form_sprite_id(self, species_id):
        return None  # Unown form is presentation only, never identity.

    def gym_badge_slugs(self, rom_type):
        # ram_constants.asm:261-283: Mineral is bit 4, Storm is bit 5.
        johto = [(9, "Zephyr"), (10, "Hive"), (11, "Plain"), (12, "Fog"),
                 (14, "Mineral"), (13, "Storm"), (15, "Glacier"), (16, "Rising")]
        return [(ident, name + " Badge") for ident, name in johto] + super().gym_badge_slugs(rom_type)
