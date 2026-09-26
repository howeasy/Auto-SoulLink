"""Server facts for one pinned pokeemerald-expansion reference build.

SOURCE: expansion e8bd1cd7, extracted from ROM 28877d73 using compiler layout.
No Lua admission or runtime qualification is implied by this server adapter.
Regenerate with tools/extract_expansion_data.py --rom <reference.gba>
--source <expansion-e8bd1cd7-checkout>
--layout data/games/gen3_exp/28877d73/layout.json
--output data/games/gen3_exp/28877d73/data.json; add --check for read-only comparison.

Recorded limits: encounter/trainer/area/static-policy packs and ability prose
are not extracted. Explicit gift_ events work; no unproved fixed-gift exemption
is inherited from vanilla. Sprites use National Dex base art, not form art.
Expansion calc is unsupported. This adapter only READS expansion data/records.

Shiny product gap: src/pokemon.c:2480-2483 at e8bd1cd7 applies
((PID_hi ^ PID_lo ^ OT_hi ^ OT_lo) < SHINY_ODDS) ^ shinyModifier;
include/constants/pokemon.h:107 pins SHINY_ODDS=8. is_shiny accepts that bit,
but shared state.py currently calls is_shiny(key) with no record. That path
can only evaluate the natural PID rule and cannot see modifier-forced shinies
(or a modifier suppressing a natural shiny). Wire integration remains OPEN.
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

from .gen3_frlge import Gen3Adapter, _parse_pid_otid_key

ROM_SHA1 = "28877d733492299599f2b8fff50493109d72653c"
ROM_TYPE = "emerald_expansion_28877d73"
PACK = Path(__file__).resolve().parents[2] / "data/games/gen3_exp/28877d73/data.json"
# include/constants/pokemon.h:5-28 at e8bd1cd7; NOT vanilla's zero-based types.
TYPE_NAMES = ("None", "Normal", "Fighting", "Flying", "Poison", "Ground", "Rock", "Bug",
              "Ghost", "Steel", "???", "Fire", "Water", "Grass", "Electric", "Psychic",
              "Ice", "Dragon", "Dark", "Fairy", "Stellar")


class Gen3ExpansionAdapter(Gen3Adapter):
    def __init__(self, **kwargs):
        if kwargs.get("rom_type", ROM_TYPE) != ROM_TYPE:
            raise ValueError("expansion reference build rom_type required")
        super().__init__(is_rr=False, rom_type="emerald")
        self._rom_type = ROM_TYPE
        data = json.loads(PACK.read_text(encoding="utf-8"))
        if data["schema"] != 1 or data["kind"] != "expansion" or data["rom_sha1"] != ROM_SHA1:
            raise ValueError("expansion data pack identity mismatch")
        self._species = {row["id"]: row for row in data["species"]}
        self._moves = {row["id"]: row for row in data["moves"]}
        self._items = {row["id"]: row for row in data["items"]}
        self._abilities = {row["id"]: row for row in data["abilities"]}

    @property
    def game_id(self):
        return "gen3_exp"

    def species_name(self, species_id):
        return self._species.get(species_id, {}).get("name", f"Species #{species_id}")

    def species_types(self, species_id):
        row = self._species.get(species_id)
        return tuple(row["types"]) if species_id and row else None

    def type_name(self, type_id):
        return TYPE_NAMES[type_id] if 0 <= type_id < len(TYPE_NAMES) else "???"

    def evo_family(self, species_id):
        return self._species.get(species_id, {}).get("family", species_id)

    def move_name(self, move_id):
        return self._moves.get(move_id, {}).get("name", f"Move #{move_id}") if move_id else ""

    @staticmethod
    def pairing_kind(kind):
        # Each future build needs explicit admission; no named/companion alias.
        return kind

    @property
    def area_pack(self):
        return "gen3_exp/28877d73"

    def is_gift_area(self, area_id):
        return (area_id or "").startswith("gift_")

    def is_fixed_species_gift(self, area_id):
        return False

    def is_daycare_area(self, area_id):
        return False

    def area_display_name(self, area_id):
        return area_id or ""  # No vanilla overrides or an invented expansion area catalog.

    def gender_from_key(self, key, species_id):
        # src/pokemon.c:1805-1818; species.genderRatio is extracted, including forms.
        row, parsed = self._species.get(species_id), _parse_pid_otid_key(key)
        if not row or parsed is None:
            return "genderless"
        ratio = row["genderRatio"]
        if ratio == 255:
            return "genderless"
        if ratio == 254:
            return "female"
        return "female" if (parsed[0] & 255) < ratio else "male"

    def is_shiny(self, key, *, shiny_modifier=0):
        if _parse_pid_otid_key(key) is None:
            return False
        if shiny_modifier not in (0, 1):
            raise ValueError("shiny_modifier must be one bit")
        return super().is_shiny(key) ^ bool(shiny_modifier)

    def species_abilities(self, species_id):
        row = self._species.get(species_id)
        return tuple(row["abilities"]) if row else ()

    def ability_name(self, ability_id, species_id=0):
        return self._abilities.get(ability_id, {}).get("name", f"Ability #{ability_id}") if ability_id else ""

    def ability_description(self, ability_id):
        return ""  # The extractor supplies names, not description strings.

    def item_name(self, item_id):
        return self._items.get(item_id, {}).get("name", f"Item #{item_id}") if item_id else ""

    def move_data(self, move_id):
        row = self._moves.get(move_id)
        if not move_id or not row:
            return None
        # include/constants/pokemon.h:236-242: none=0/physical=1/special=2/status=3.
        # Display split is physical=0/special=1/status=2; never infer from type.
        return {"name": row["name"], "type_id": row["type"], "type_name": self.type_name(row["type"]),
                "power": row["power"], "accuracy": row["accuracy"], "pp": row["pp"],
                "split": {1: 0, 2: 1, 3: 2}[row["category"]]}

    def to_national_dex(self, species_id):
        return self._species.get(species_id, {}).get("national_dex", 0)

    def sprite_src(self, species_id):
        dex = self.to_national_dex(species_id)
        return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{dex}.png" if dex else ""

    def sprite_html(self, species_id, form=0):
        url = self.sprite_src(species_id)
        return f'<img class="mon-sprite" src="{escape(url, quote=True)}" alt="">' if url else ""

    def form_sprite_id(self, species_id):
        return None

    def encounter_table(self, area_id):
        return None

    def trainer_info(self, trainer_id):
        return "", ""

    def trainers_for_area(self, area_id):
        return []

    def trainer_party(self, trainer_id):
        return []

    def trainer_brief(self, trainer_id):
        return None

    def milestone_cap_for_fight_label(self, fight_label):
        return None

    def calc_name(self, kind, name):
        return name

    def calc_profile(self):
        return None

    def calc_stats(self, detail):
        return None  # Never feed expansion records to the vanilla codec/encoder.

    def calc_nature(self, key):
        return None

    def gym_badge_slugs(self, rom_type):
        return super().gym_badge_slugs("emerald")
