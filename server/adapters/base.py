"""
server/adapters/base.py — Abstract base classes for game adapters.

GameRulesAdapter: Methods used by the state machine (FSM) for Soul Link logic.
GamePresentationAdapter: Methods used by the HTTP status page for display.
GameAdapter: Combined interface — most games implement both.

Each supported game (Gen 1 RBY, Gen 3 FRLG, Gen 4 HGSS/Pt, etc.) provides a
concrete adapter implementing these interfaces.

ISOLATION CONTRACT:
- Adapters MUST NOT import from server.server (circular dependency).
- Adapters load their own data files independently (from data/games/<gen>/).
- All game-specific display logic (sprites, items, areas, types) goes through
  adapter methods — never through standalone functions in server.py.
- Use gen4_hgsspt.py as the model adapter (zero external dependencies).
- Item/species data should be hardcoded or loaded from game data files,
  never imported from server.py.
"""

from abc import ABC, abstractmethod


class GameRulesAdapter(ABC):
    """Interface for game-specific Soul Link rule logic.

    Used by SoulLinkState (the FSM) to enforce link rules, determine
    shininess, gender, evolution families, and gift area detection.
    """

    @property
    @abstractmethod
    def game_id(self) -> str:
        """Unique identifier for this game family (e.g., 'frlg', 'gen1_rby')."""
        ...

    @abstractmethod
    def is_gift_area(self, area_id: str) -> bool:
        """Return True if the area is a gift/static encounter location.

        Gift areas do not activate the pokeball gate and do not generate
        no_catch events.
        """
        ...

    def is_fixed_species_gift(self, area_id: str) -> bool:
        """Return True if this gift area always produces the same predetermined species.

        Used to bypass clause checks (species/gender/type) when both players are
        guaranteed to receive an identical species with no player choice involved.
        Examples: Magikarp salesman, Eevee, Lapras.

        Areas where the player chooses (starters, fossils, Hitmonlee/Hitmonchan)
        return False — clauses still apply there.

        Default: False. Adapters override this for areas with forced species.
        """
        return False

    @abstractmethod
    def evo_family(self, species_id: int) -> int:
        """Return the base-form species ID for species lock checks.

        Single-stage mons return themselves.
        """
        ...

    @abstractmethod
    def gender_from_key(self, key: str, species_id: int) -> str:
        """Derive gender from the mon's key and species ID.

        Returns 'male', 'female', or 'genderless'.
        Key format is game-specific (adapter knows how to parse it).
        """
        ...

    @abstractmethod
    def species_types(self, species_id: int) -> tuple[int, int] | None:
        """Return (type1, type2) for a species, or None if unknown.

        Used for type lock checks.
        """
        ...

    @abstractmethod
    def is_shiny(self, key: str) -> bool:
        """Determine if a mon is shiny from its key.

        Key format is game-specific; the adapter knows how to extract
        the necessary values (e.g., personality/otId for Gen 3+,
        DVs for Gen 1-2).
        """
        ...

    @abstractmethod
    def parse_ot_id(self, key: str) -> str:
        """Extract the OT (Original Trainer) ID portion from a mon key.

        Used for player identity lock validation.
        Returns an opaque string representing the trainer identity.
        """
        ...

    @abstractmethod
    def is_valid_mon_key(self, key: str) -> bool:
        """Validate that a mon key string is well-formed for this game."""
        ...

    @abstractmethod
    def species_name(self, species_id: int) -> str:
        """Return display name for a species ID.

        Used in HUD messages and log output from the state machine.
        """
        ...

    @abstractmethod
    def type_name(self, type_id: int) -> str:
        """Return display name for a type ID (e.g., 0 -> 'Normal')."""
        ...


class GamePresentationAdapter(ABC):
    """Interface for game-specific display/UI logic.

    Used by the HTTP status page and stream overlays for sprites,
    formatted names, and other visual elements.
    """

    @abstractmethod
    def sprite_html(self, species_id: int) -> str:
        """Return an HTML <img> tag for the species sprite."""
        ...

    @abstractmethod
    def ability_name(self, ability_id: int) -> str:
        """Return display name for an ability ID."""
        ...

    @abstractmethod
    def ability_description(self, ability_id: int) -> str:
        """Return tooltip description for an ability ID."""
        ...

    @abstractmethod
    def trainer_info(self, trainer_id: int) -> tuple[str, str]:
        """Return (trainer_name, trainer_class) for a trainer ID.

        Returns ("", "") if the game doesn't support trainer lookup.
        trainer_id is 1-based as received from Lua.
        """
        ...

    @abstractmethod
    def item_name(self, item_id: int) -> str:
        """Return display name for an item ID."""
        ...

    @abstractmethod
    def area_display_name(self, area_id: str) -> str:
        """Return a human-friendly display name for an area_id."""
        ...

    @abstractmethod
    def to_national_dex(self, species_id: int) -> int:
        """Convert game-internal species ID to National Dex number."""
        ...

    @abstractmethod
    def gender_symbol(self, gender: str) -> str:
        """Return the display symbol for a gender string."""
        ...

    @abstractmethod
    def form_sprite_id(self, species_id: int) -> int | None:
        """Return alternative sprite ID for forms, or None for base form."""
        ...

    def encounter_table(self, area_id: str) -> dict[str, list[dict]] | None:
        """Return wild encounter data for an area, or None if unavailable.

        Returns a dict mapping method label → list of encounter entries, e.g.:
            {
              "Day":  [{"name": "Bidoof", "species_id": 452, "rate": 20,
                        "min_level": 2, "max_level": 4}, ...],
              "Night": [...],
            }
        Only available for RR runs in Gen3Adapter; other adapters return None.
        """
        return None

    def move_name(self, move_id: int) -> str:
        """Return display name for a move ID.

        Default returns empty string. Override in adapters with move data.
        """
        return ""

    def move_data(self, move_id: int) -> dict | None:
        """Return move details for a move ID, or None if unknown.

        Returns dict with keys: name, type_id, type_name, power, accuracy,
        pp, split (0=Physical, 1=Special, 2=Status).
        """
        return None

    @property
    def memorial_box_index(self) -> int:
        """Return the 0-based PC box index reserved for memorialized (dead) mons.

        Returns -1 if the game has no dedicated memorial box (Gen 1/2).
        Gen 3: box 13 (last of 14 boxes).
        Gen 4: box 17 (last of 18 boxes).
        """
        return -1

    def gym_badge_slugs(self, rom_type: str) -> list[tuple[int, str]]:
        """Return (pokeapi_badge_id, display_name) for each gym badge.

        IDs come from the PokeAPI sprites repo: sprites/badges/{id}.png
        at https://raw.githubusercontent.com/PokeAPI/sprites/master/
        Kanto 1-8, Johto 9-16, Hoenn 17-24, Sinnoh 25-32.
        Ordered by bit position (bit 0 = index 0). Override in adapters
        that use a region other than Kanto.
        """
        return [
            (1, "Boulder Badge"),
            (2, "Cascade Badge"),
            (3, "Thunder Badge"),
            (4, "Rainbow Badge"),
            (5, "Soul Badge"),
            (6, "Marsh Badge"),
            (7, "Volcano Badge"),
            (8, "Earth Badge"),
        ]


class GameAdapter(GameRulesAdapter, GamePresentationAdapter):
    """Combined adapter interface — most games implement both layers.

    Subclass this for a complete game adapter that provides both
    rule logic and presentation methods.
    """
    pass
