"""
server/adapters — Game adapter registry.

Each supported game family provides an adapter implementing GameAdapter.
The registry maps game_id strings to adapter classes.
"""

# The two ABCs are re-exported for adapter authors, not used here.
from .base import GameAdapter, GamePresentationAdapter, GameRulesAdapter  # noqa: F401

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
    # Archipelago (Alchav's Red/Blue world). Same adapter, same RAM layout — the AP fork
    # only changes ROM content. Yellow has no upstream AP world.
    "red_ap": "gen1_rby", "blue_ap": "gen1_rby",
    # pureRGB (Vortyne): a second Gen 1 foundation, not a vanilla variant — its own
    # adapter, its own data/games/gen1_purergb/ pack (docs/purergb/PLAN.md §4 row 2).
    "PureRed": "gen1_purergb", "PureBlue": "gen1_purergb", "PureGreen": "gen1_purergb",
    "purered": "gen1_purergb", "pureblue": "gen1_purergb", "puregreen": "gen1_purergb",
    # Gen 2. `lua/games/gen2_crystal.lua:rom_type_for_variant` returns the title-cased forms;
    # the lowercase ones mirror the Gen 1 convention above and are what new code should send.
    # Registering BOTH is deliberate: a rom_type is persisted into the run directory
    # (server/state.py), so dropping the title-cased spellings would orphan existing runs.
    #
    # Gold, Silver and Crystal (AP) were MISSING here, and the failure was silent rather than
    # loud: game_id_for_rom_type() returned None, the guard in server.py never switched the
    # adapter, and the run continued under whichever adapter was already loaded — the Gen 3
    # default. Every Gen 2 claim that did not come from a Crystal run rested on that.
    #
    # RUNTIME ROUTE ONLY. These rows still pick the LEGACY `gen2_crystal` adapter, because
    # the shipped launcher runs the legacy client until the G3 cutover (docs/gen2/PLAN.md
    # §5.9). Pairing does NOT read them: every Gen 2 spelling has its own row in
    # `_ROM_TYPE_TO_FOUNDATION` below. The cutover re-points these rows to the already
    # registered `gen2_gsc` (bottom of this file), whose constructor binds its title from
    # the `rom_type` the generic factory forwards; `crystal_ap` binds no title (O-8).
    "Crystal": "gen2_crystal", "crystal": "gen2_crystal",
    "Gold": "gen2_crystal", "gold": "gen2_crystal",
    "Silver": "gen2_crystal", "silver": "gen2_crystal",
    "Crystal (AP)": "gen2_crystal", "crystal_ap": "gen2_crystal",
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
    "red_ap": "Red (AP)", "blue_ap": "Blue (AP)",
    "PureRed": "PureRed", "PureBlue": "PureBlue", "PureGreen": "PureGreen",
    "purered": "PureRed", "pureblue": "PureBlue", "puregreen": "PureGreen",
    "Crystal": "Crystal", "crystal": "Crystal",
    "Gold": "Gold", "gold": "Gold",
    "Silver": "Silver", "silver": "Silver",
    "Crystal (AP)": "Crystal (AP)", "crystal_ap": "Crystal (AP)",
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


# ROM-type string → PAIRING FOUNDATION, where a game_id is too coarse to pair on.
# A foundation is a data pack + memory layout, not a class: Radical Red and vanilla
# FireRed share `Gen3Adapter` but share no layout, so a clean FR must not pair with a
# clean RR. Everything absent here derives its foundation from its game_id, which is
# already fine-grained enough (the Gen 1 packs differ by game_id: gen1_rby vs
# gen1_purergb). Adding a Gen 3 ROM variant: add it here too (docs/gen3/PLAN.md §5.1).
_ROM_TYPE_TO_FOUNDATION: dict[str, str] = {
    "firered": "gen3_frlg", "leafgreen": "gen3_frlg", "emerald": "gen3_frlg",
    "firered_ap": "gen3_frlg", "leafgreen_ap": "gen3_frlg",
    "firered_rr": "gen3_rr",
    # Gen 2 (docs/gen2/PLAN.md §5.9, owner O-16): ONE foundation for Gold, Silver and
    # Crystal, so every Gen 2 pairing is admitted with no title relation in shared code.
    # EVERY spelling has a row: the title-cased ones are what both clients send and what
    # existing run directories persist, and a missing row would silently fall back to the
    # legacy game_id. `crystal_ap` has NO row on purpose (O-8, not admitted in the RC): it
    # keeps the legacy foundation `gen2_crystal`, so it never pairs with a gen2_gsc half.
    "Crystal": "gen2_gsc", "crystal": "gen2_gsc",
    "Gold": "gen2_gsc", "gold": "gen2_gsc",
    "Silver": "gen2_gsc", "silver": "gen2_gsc",
}


def foundation_for_rom_type(rom_type: str) -> str | None:
    """Derive the pairing foundation for a ROM type, or None when unrecognized.

    DERIVED, never trusted: a hello may carry `foundation`, and it is only allowed to
    agree with this. An unknown rom_type answers None so the caller refuses it instead
    of silently reusing whichever adapter is already installed.
    """
    game_id = _ROM_TYPE_TO_GAME_ID.get(rom_type)
    if game_id is None:
        return None
    return _ROM_TYPE_TO_FOUNDATION.get(rom_type, game_id)


def adapter_class_for_rom_type(rom_type: str) -> type[GameAdapter] | None:
    """The registered adapter CLASS for a ROM type, without instantiating it.

    For pure class-level lookups (`pairing_kind`) on a hello that may still be refused:
    no candidate adapter is installed to answer the question. None when unrecognized.
    """
    game_id = _ROM_TYPE_TO_GAME_ID.get(rom_type)
    return _REGISTRY.get(game_id) if game_id else None


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

from .gen1_purergb import Gen1PureRGBAdapter  # noqa: E402

register_adapter("gen1_purergb", Gen1PureRGBAdapter)

from .gen2_crystal import Gen2CrystalAdapter  # noqa: E402

register_adapter("gen2_crystal", Gen2CrystalAdapter)

# Registered but NOT routed: no rom_type row selects it until the G3 cutover (U5).
from .gen2_gsc import Gen2GSCAdapter  # noqa: E402

register_adapter("gen2_gsc", Gen2GSCAdapter)
