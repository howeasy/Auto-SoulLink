"""
server/adapters — Game adapter registry.

Each supported game family provides an adapter implementing GameAdapter.
The registry maps game_id strings to adapter classes.
"""

from .base import GameAdapter, GameRulesAdapter, GamePresentationAdapter

# Registry: game_id -> adapter class
_REGISTRY: dict[str, type[GameAdapter]] = {}


def register_adapter(game_id: str, adapter_cls: type[GameAdapter]) -> None:
    """Register an adapter class for a game_id."""
    _REGISTRY[game_id] = adapter_cls


def get_adapter(game_id: str, **kwargs) -> GameAdapter:
    """Instantiate and return the adapter for the given game_id.

    Raises KeyError if no adapter is registered for that game_id.
    """
    if game_id not in _REGISTRY:
        raise KeyError(f"No adapter registered for game_id={game_id!r}. "
                       f"Available: {list(_REGISTRY.keys())}")
    return _REGISTRY[game_id](**kwargs)


def available_game_ids() -> list[str]:
    """Return list of registered game_ids."""
    return list(_REGISTRY.keys())


# ROM-type string (sent by the Lua client in its hello) → adapter game_id.
# Adding a new ROM variant: add an entry here AND a `_VARIANT_LABEL` entry below.
_ROM_TYPE_TO_GAME_ID: dict[str, str] = {
    "firered": "gen3_frlge", "leafgreen": "gen3_frlge", "emerald": "gen3_frlge",
    "firered_ap": "gen3_frlge", "leafgreen_ap": "gen3_frlge",
    "firered_rr": "gen3_frlge",
    "heartgold": "gen4_hgsspt", "soulsilver": "gen4_hgsspt",
    "platinum": "gen4_hgsspt", "hgss": "gen4_hgsspt",
    "renegade_platinum": "gen4_hgsspt",  # Drayano60 difficulty hack on Platinum
    "Red": "gen1_rby", "Blue": "gen1_rby", "Yellow": "gen1_rby",
    "red": "gen1_rby", "blue": "gen1_rby", "yellow": "gen1_rby",
    "Crystal": "gen2_crystal", "crystal": "gen2_crystal",
    "pokemon_black": "gen5_bw",
    "pokemon_white": "gen5_bw",
    "pokemon_black_2": "gen5_bw",
    "pokemon_white_2": "gen5_bw",
}

# ROM-type string → human-readable variant label (page titles, status UI).
_VARIANT_LABEL: dict[str, str] = {
    "firered": "FireRed", "leafgreen": "LeafGreen",
    "firered_ap": "FireRed (AP)", "leafgreen_ap": "LeafGreen (AP)",
    "firered_rr": "Radical Red",
    "heartgold": "HeartGold", "soulsilver": "SoulSilver",
    "platinum": "Platinum", "hgss": "HGSS",
    "Red": "Red", "Blue": "Blue", "Yellow": "Yellow",
    "red": "Red", "blue": "Blue", "yellow": "Yellow",
    "Crystal": "Crystal", "crystal": "Crystal",
    "pokemon_black": "Pokémon Black",
    "pokemon_white": "Pokémon White",
    "pokemon_black_2": "Pokémon Black 2",
    "pokemon_white_2": "Pokémon White 2",
}


def game_id_for_rom_type(rom_type: str) -> str | None:
    """Resolve a ROM-type string (as sent by the Lua client) to an adapter game_id.

    Returns None when the rom_type isn't recognized.
    """
    return _ROM_TYPE_TO_GAME_ID.get(rom_type)


def variant_label(rom_type: str) -> str:
    """Human-readable label for a ROM type. Falls back to the rom_type itself."""
    return _VARIANT_LABEL.get(rom_type, rom_type)


# Auto-register built-in adapters on import
from .gen3_frlge import Gen3Adapter  # noqa: E402
register_adapter("gen3_frlge", Gen3Adapter)
# Backward compat: "frlg" was the old game_id; alias to gen3_frlge
register_adapter("frlg", Gen3Adapter)

from .gen4_hgsspt import Gen4Adapter  # noqa: E402
register_adapter("gen4_hgsspt", Gen4Adapter)

try:
    from .gen5_bw import Gen5Adapter  # noqa: E402
    register_adapter("gen5_bw", Gen5Adapter)
    register_adapter("pokemon_black", Gen5Adapter)
    register_adapter("pokemon_white", Gen5Adapter)
    register_adapter("pokemon_black_2", Gen5Adapter)
    register_adapter("pokemon_white_2", Gen5Adapter)
except ImportError:
    pass

from .gen1_rby import Gen1Adapter  # noqa: E402
register_adapter("gen1_rby", Gen1Adapter)

try:
    from .gen2_crystal import Gen2CrystalAdapter  # noqa: E402
    register_adapter("gen2_crystal", Gen2CrystalAdapter)
except ImportError:
    pass  # Adapter not yet implemented
