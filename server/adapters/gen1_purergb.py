"""Gen 1 pureRGB (PureRed/PureBlue/PureGreen) adapter over the pure data pack.

pureRGB (Vortyne, v2.7.6, pinned commit 7e7a4653) is a pret/pokered source fork: same
engine, same struct geometry (docs/purergb/PLAN.md §4 row 4 — party 44 / box 33 / 6 / 20 /
12, 11-byte names, 66-byte transfer blob), different species/types/evolutions/trainers/
items/moves/charmap/areas/statics/WRAM+SRAM addresses.

This adapter owns its own tables end to end. It does NOT subclass Gen1Adapter and swap a
``_DATA`` path: Gen1Adapter's tables are module-level globals computed once, at import
time, from ``data/games/gen1_rby/`` — a subclass that only reassigned that path would
still run every inherited data-bound method against the OLD vanilla tables, because those
methods close over the vanilla module globals, not over ``self`` (docs/purergb/PLAN.md
§11.2 B2 names this exact anti-pattern). Every data-bound method below is therefore
overridden with pure-specific logic backed by its own instance-loaded pack; only the
methods PLAN.md's census marks "inherit" (struct geometry, the key format, the six growth
curves, the no-gender/no-shiny/no-ability facts) are left to Gen1Adapter's implementation.

Wire species are internal indices throughout, exactly as for vanilla, INCLUDING dex-0
species: pureRGB's PokedexOrder is many-to-one (39 forms/spirits/unused slots share dex
0), and one of them — MISSINGNO, internal id 0xB5 = 181 — is a real, catchable species.
Every lookup below is keyed by internal id first; national dex is only ever a display
detail, and a dex of 0 is never treated as "no such species" here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from server.pokemon_data import species_name as national_species_name

from . import gen1_codec
from .base import humanize_area_id
from .gen1_rby import Gen1Adapter

_DATA = Path(__file__).resolve().parents[2] / "data" / "games" / "gen1_purergb"


def _json(name: str) -> dict:
    with (_DATA / name).open(encoding="utf-8") as stream:
        return json.load(stream)


# rom_type (as sent by the Lua client's hello) -> the pack's own title key.
_ROM_VARIANT = {
    "PureRed": "purered", "purered": "purered",
    "PureBlue": "pureblue", "pureblue": "pureblue",
    "PureGreen": "puregreen", "puregreen": "puregreen",
}
_STATIC_ID = re.compile(r"static_(\d+)_(\d+)\Z")


def _display_case(name: str) -> str:
    """Title-case an all-caps pack string (trainer classes, non-dex species names).

    The pack stores names as pureRGB's own in-game text, which the Game Boy font shows
    entirely in capitals ("BUG CATCHER", "MISSINGNO."). Ordinary (dex 1-151) species
    route through server.pokemon_data.species_name instead of this, which is why this
    helper never needs to special-case apostrophes/periods the way vanilla's own
    Farfetch'd/Mr. Mime names would (PLAN.md §11.2 A10 lists no non-dex name with either).
    """
    return name.title() if name.isupper() else name


class Gen1PureRGBAdapter(Gen1Adapter):
    """One per-player view of a pureRGB cartridge (PureRed/PureBlue/PureGreen)."""

    def __init__(self, **kwargs):
        rom_type = kwargs.get("rom_type") or "PureRed"
        if rom_type not in _ROM_VARIANT:
            # Same fail-closed rule as Gen1Adapter (docs/purergb/PLAN.md §4 row 2): an
            # unrecognised variant is a routing bug, never a silent default.
            raise ValueError(f"unrecognised pureRGB rom_type: {rom_type!r}")
        self._variant = _ROM_VARIANT[rom_type]
        self._enc_variant = self._variant
        # clean / overlay / rand / rand_overlay (the hello's artifact_kind; the SLink companion
        # overlay -- randomized or not -- is the only pure build with the native panel +
        # receptionist, PLAN M3). Whoever constructs the adapter for a committed run passes
        # it; a clean cartridge is the safe default.
        self._artifact_kind = kwargs.get("artifact_kind") or "clean"
        self._rom_encounters: dict[str, dict[str, list[dict]]] | None = None
        self._layout = gen1_codec.for_foundation("gen1_purergb")

        area_map = _json("area_map.json")
        self._area_by_map = {int(k): v["area_id"] for k, v in area_map.items()}
        # First-wins, like Gen1Adapter's own _AREA_NAMES: several map ids share one
        # collapsed area_id (U10's dungeon/town-building collapse), each with its OWN
        # `name` (Pallet Town's area_id also covers Oak's Lab and both rival/player
        # houses) — the lowest map id's name is the area's displayed name.
        self._area_names: dict[str, str] = {}
        for _, row in sorted(area_map.items(), key=lambda kv: int(kv[0])):
            self._area_names.setdefault(row["area_id"], row["name"])

        species_pack = _json("species_index.json")
        self._species: dict[int, dict] = {int(k): v for k, v in species_pack["species"].items()}

        types_pack = _json("types.json")
        self._type_names = {int(k): v for k, v in types_pack["type_names"].items()}
        self._type_id = {name: ident for ident, name in self._type_names.items()}
        self._species_types = {int(k): tuple(v) for k, v in types_pack["species_types"].items()}

        self._family = {int(k): v for k, v in _json("evolutions.json")["family"].items()}

        trainers_pack = _json("trainers.json")
        self._trainers = trainers_pack["classes"]
        self._rival_ids = frozenset(trainers_pack["rival_ids"])

        statics_pack = _json("static_encounters.json")
        # (map, natdex) — the SAME namespace vanilla's _STATIC_SITES uses and the one the
        # shared Lua client's area_id ("static_<map>_<dex>") already speaks. A dex of 0 is
        # admitted (MISSINGNO's static site, map 107): _STATIC_ID's \d+ never special-cases
        # it, and area_display_name below does not treat it as "unknown".
        self._static_sites = frozenset(
            (int(map_id), self._species[internal]["dex"])
            for map_id, internal_list in statics_pack["statics"].items()
            for internal in internal_list
        )

        self._moves = {row["id"]: row for row in _json("moves.json")["moves"]}
        self._items = _json("items.json")["items"]

        encounters_pack = _json("encounter_tables.json")
        # species_id_space is "internal" here (unlike vanilla's NatDex-keyed file), so
        # encounter_table() below must NOT run these through natdex_to_internal.
        self._encounters = {k: v for k, v in encounters_pack.items()
                            if k not in ("species_id_space",)}
        self._floor_labels = _json("floor_labels.json")

        # Narrative (non-static) grants: tools/gen_gen1_gifts.py's own table -- pureRGB has no
        # equivalent of vanilla's hand-typed _GIFT_AREAS/_FIXED_GIFTS (docs/purergb/PLAN.md
        # A2). An area is a gift area if any gift site's map routes into it; it is a
        # fixed-species gift area only when every such site resolves to the SAME one known
        # species (two Fighting Dojo rooms or six Game Corner prizes each give one species,
        # but two different ones per area, so the area itself stays non-fixed — same
        # derivation tests/unit/test_gen1_gifts.py proves against vanilla's literals).
        #
        # Every gift map has its OWN area id in this pack's area_map.json: the generator's
        # `gift_building_own_area` rule gives a table-less gift interior its own id ahead of the
        # inheritance rules (the same thing vanilla does by hand for oaks_lab /
        # celadon_mansion_roof / game_corner), and refuses to emit a map where a gift area
        # coincides with a wild/fishing area. So no wild-area filter is needed here: marking a
        # city as a gift area because a gift building stood in it would dead-zone that city's
        # real wild water, which is the Route-4 class bug tests/unit/test_gen1_gift_areas.py
        # catches for vanilla and test_the_pure_gift_areas_carry_no_wild_table catches here.
        species_by_area: dict[str, set[int | None]] = {}
        for gift in _json("gifts.json")["gifts"]:
            area = self._area_by_map.get(gift["map_id"])
            if area is None:
                continue
            species_by_area.setdefault(area, set())
            species_by_area[area].add(gift["species"] if gift["fixed_species"] else None)
        self._gift_areas = frozenset(species_by_area)
        self._fixed_gift_areas = frozenset(
            area for area, species in species_by_area.items()
            if len(species) == 1 and next(iter(species)) is not None
        )

    # ── identity ─────────────────────────────────────────────────────────────────────────
    @property
    def game_id(self) -> str:
        return "gen1_purergb"

    # ── rules-facing ─────────────────────────────────────────────────────────────────────
    def is_gift_area(self, area_id: str) -> bool:
        if not isinstance(area_id, str):
            return False
        static = _STATIC_ID.fullmatch(area_id)
        # The "gift"/"gift_" namespace is the shared gift contract (base.gift_link_area): the
        # client names an out-of-battle acquisition gift_map_<map> and the server links it there.
        return (area_id == "gift" or area_id.startswith("gift_") or area_id in self._gift_areas
                or bool(static and (int(static[1]), int(static[2])) in self._static_sites))

    def is_fixed_species_gift(self, area_id: str) -> bool:
        # Every static site here is a script/object-event placed encounter with no player
        # choice (a fixed species at a fixed level), exactly like vanilla's _STATIC_SITES
        # membership. Narrative gifts (Eevee, Magikarp, the Silph/Celadon Lapras, the
        # Fighting Dojo, the Game Corner, the fossil rooms) are gifts.json's own table.
        static = _STATIC_ID.fullmatch(area_id) if isinstance(area_id, str) else None
        return bool(static and (int(static[1]), int(static[2])) in self._static_sites) or (
            area_id in self._fixed_gift_areas)

    def evo_family(self, species_id: int) -> int:
        # PLAN.md §11.2 A13: families are keyed by INTERNAL id here (unlike vanilla's
        # dex-keyed table), and a form resolves its family through its base species.
        entry = self._species.get(species_id)
        base = entry.get("base_species") if entry else None
        lookup_id = base if base is not None else species_id
        return self._family.get(lookup_id, lookup_id)

    def species_types(self, species_id: int) -> tuple[int, int] | None:
        return self._species_types.get(species_id)

    def species_name(self, species_id: int) -> str:
        entry = self._species.get(species_id)
        if not entry:
            return f"#{species_id}"
        if entry["classification"] == "ordinary":
            # The ~151 ordinary species keep vanilla's own name text (PLAN.md §11.2 A10:
            # only 13 non-dex/form names differ), so this reuses the same display source
            # vanilla's adapter uses rather than re-deriving Farfetch'd/Mr. Mime casing.
            return national_species_name(entry["dex"], False)
        return _display_case(entry["name"])

    def type_name(self, type_id: int) -> str:
        return self._type_names.get(type_id, f"Type #{type_id}")

    def rival_trainer_ids(self) -> set[int]:
        return set(self._rival_ids)

    # ── presentation ─────────────────────────────────────────────────────────────────────
    @property
    def artifact_kind(self) -> str:
        return self._artifact_kind

    def set_artifact_kind(self, kind: str) -> None:
        """Bind the run's committed artifact kind (server/state.py `artifact_kind`)."""
        self._artifact_kind = kind or "clean"

    def _is_overlay(self) -> bool:
        return self._artifact_kind in ("overlay", "rand_overlay")

    def supports_info_panel(self) -> bool:
        # The native panel ships in the SLink source overlay (M3), not in a clean pureRGB ROM.
        return self._is_overlay()

    def native_trade_ui(self) -> bool:
        # The receptionist + native trade scene ship in the same overlay.
        return self._is_overlay()

    def info_panel_width(self) -> int:
        # Game Boy tilemap width, as the vanilla adapter reports for its panel.
        return 20 if self.supports_info_panel() else 0

    def sprite_src(self, species_id: int) -> str:
        dex = self._sprite_dex(species_id)
        if not dex:
            return ""
        return ("https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/"
                f"versions/generation-i/red-blue/transparent/{dex}.png")

    def sprite_html(self, species_id: int, form: int = 0) -> str:
        dex = self._sprite_dex(species_id)
        if not dex:
            return ""
        url = self.sprite_src(species_id)
        return (
            '<span style="display:inline-block;width:40px;height:40px;'
            'overflow:hidden;vertical-align:middle">'
            f'<img class="mon-sprite" data-species="{dex}" src="{url}" '
            'width="52" height="52" loading="lazy" '
            'onerror="this.style.visibility=&#39;hidden&#39;" '
            'style="image-rendering:pixelated;margin:-6px"></span>'
        )

    def _sprite_dex(self, species_id: int) -> int:
        """The vanilla-art dex to show for this internal id, or 0 for no sensible fallback.

        Ordinary species use their own dex directly. A form (Floating Magneton, Hardened
        Onix, ...) falls back to its base species' art — the same creature, no dedicated
        pureRGB sprite exists. Spirits/MissingNo/picture-only/unused species have no
        Generation-I PokeAPI art at all and get no sprite (PLAN.md §11.2 literal 35).
        """
        entry = self._species.get(species_id)
        if not entry:
            return 0
        if entry["classification"] == "form" and entry.get("base_species") is not None:
            base = self._species.get(entry["base_species"])
            return base["dex"] if base else 0
        return entry["dex"] if entry["classification"] == "ordinary" else 0

    def trainer_info(self, trainer_id: int) -> tuple[str, str]:
        cls = self._trainers.get(str(trainer_id))
        if not cls:
            return "", ""
        if trainer_id in self._rival_ids:
            # "name" is null for the three rival/champion slots by design (GetTrainerName
            # substitutes wRivalName at read time — README, trainers.json) — there is no
            # fixed name to show, only the class vanilla's own table spells "Rival".
            return "", "Rival"
        name = _display_case(cls["name"])
        return name, name

    def item_name(self, item_id: int) -> str:
        if not item_id:
            return ""
        row = self._items.get(str(item_id))
        return row["name"] if row else f"Item #{item_id}"

    def area_display_name(self, area_id: str) -> str:
        if area_id in self._area_names:
            return self._area_names[area_id]
        static = _STATIC_ID.fullmatch(area_id)
        if static:
            map_id, dex = int(static[1]), int(static[2])
            location = self._area_names.get(self._area_by_map.get(map_id, ""), f"Map {map_id}")
            # dex 0 in a static area id is always MISSINGNO here (the only dex-0 species
            # this pack's static list ever names, map 107) — never "unknown".
            name = "MISSINGNO." if dex == 0 else national_species_name(dex, False)
            return f"{location} — {name}"
        return humanize_area_id(area_id)

    def to_national_dex(self, species_id: int) -> int:
        entry = self._species.get(species_id)
        return entry["dex"] if entry else 0

    def move_name(self, move_id: int) -> str:
        row = self._moves.get(move_id)
        return row["name"] if row else ""

    def move_data(self, move_id: int) -> dict | None:
        row = self._moves.get(move_id)
        if not row:
            return None
        return {"name": row["name"], "type_id": self._type_id.get(row["type"], 0),
                "type_name": row["type"], "power": row["power"],
                "accuracy": row["accuracy"], "pp": row["pp"],
                "split": {"Physical": 0, "Special": 1, "Status": 2}[row["split"]]}

    def encounter_table(self, area_id: str) -> dict[str, list[dict]] | None:
        if self._rom_encounters is not None:
            return self._rom_encounters.get(area_id)
        raw = self._encounters.get(self._variant, {}).get(area_id)
        # Unlike vanilla, entries are ALREADY internal-index species ids here
        # (encounter_tables.json's species_id_space: "internal"), so no conversion runs.
        return raw

    def ingest_rom_content(self, payload: dict) -> dict[str, dict[str, list[dict]]] | None:
        from .gen1_rom_scan import build_encounter_tables, parse_client_content

        content = parse_client_content(payload)
        identity = {idx: idx for idx in self._species}
        return build_encounter_tables(content, self._area_by_map, identity, self.species_name,
                                      floor_labels=self._floor_labels)

    def rom_content_fingerprint(self, payload: dict) -> str | None:
        from .gen1_rom_scan import content_fingerprint, parse_client_content

        content = parse_client_content(payload)
        return content_fingerprint(content["variant"], content["wild"], content["fishing"])

    def validate_party_blob(self, blob_hex: str | bytes) -> bool:
        """Validate the 66-byte transfer blob against THIS pack's species domain.

        Overridden rather than inherited: Gen1Adapter's body checks vanilla natdex > 0,
        which would reject a legitimate pureRGB MISSINGNO transfer (dex 0) and would
        validate against the wrong dex table besides. Not called by state ingestion
        (docs/purergb/research/p3/server_literals_bbcd037.md §2), same as vanilla's.
        """
        try:
            blob = bytes.fromhex(blob_hex) if isinstance(blob_hex, str) else blob_hex
            if not isinstance(blob, bytes) or len(blob) != self.party_blob_size():
                return False
            mon = gen1_codec.decode_party_mon(blob[:gen1_codec.PARTY_MON_SIZE])
            return mon["species"] in self._species
        except ValueError:
            return False
