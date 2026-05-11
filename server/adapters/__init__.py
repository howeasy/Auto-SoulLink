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
