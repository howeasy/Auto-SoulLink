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
    "emerald_expansion_28877d73": "gen3_exp",
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
    # Gen 2. lua/gen2/entry.lua sends the title-cased forms (as the legacy client did);
    # the lowercase ones mirror the Gen 1 convention above and are what new code should send.
    # Registering BOTH is deliberate: a rom_type is persisted into the run directory
    # (server/state.py), so dropping the title-cased spellings would orphan existing runs.
    #
    # Gold, Silver (and the since-refused Crystal (AP)) were once MISSING here, and the
    # failure was silent rather than loud: game_id_for_rom_type() returned None, the guard in server.py never switched the
    # adapter, and the run continued under whichever adapter was already loaded — the Gen 3
    # default. Every Gen 2 claim that did not come from a Crystal run rested on that.
    #
    # RUNTIME ROUTE. Crystal, Gold and Silver all cut over here (U5, O-22/O-23,
    # docs/gen2/reviews/OMP_U5_CUTOVER_FACTS_2026-09-23.md): the launcher (lua/slink.lua) now
    # runs the new client for every recognised Gen 2 title, so their rows point at the
    # already-registered `gen2_gsc` (bottom of this file), whose constructor binds its title
    # from the `rom_type` the generic factory forwards. Per-title admission (whether a given
    # build actually gets a client) is Entry.admit's job at runtime, not this table's --
    # a PENDING revision or an unknown hash is refused by run.lua itself, with no fallback.
    # Archipelago Crystal (`crystal_ap` / "Crystal (AP)") has NO row: owner ruling O-25
    # refuses it (see `_REFUSED_ROM_TYPES`), and the legacy adapter it ran on is gone (P3b.8).
    # Pairing does NOT read these rows: every Gen 2 spelling has its own row in
    # `_ROM_TYPE_TO_FOUNDATION` below.
    "Crystal": "gen2_gsc", "crystal": "gen2_gsc",
    "Gold": "gen2_gsc", "gold": "gen2_gsc",
    "Silver": "gen2_gsc", "silver": "gen2_gsc",
    "pokemon_black": "gen5_bw",
    "pokemon_white": "gen5_bw",
    "pokemon_black_2": "gen5_bw",
    "pokemon_white_2": "gen5_bw",
}

# ROM-type string → human-readable variant label (page titles, status UI).
_VARIANT_LABEL: dict[str, str] = {
    "firered": "FireRed", "leafgreen": "LeafGreen",
    "firered_ap": "FireRed (AP)", "leafgreen_ap": "LeafGreen (AP)",
    "firered_rr": "Radical Red", "emerald": "Emerald",
    "emerald_expansion_28877d73": "Emerald Expansion 1.17.0 (28877d73)",
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
    "pokemon_black": "Pokémon Black",
    "pokemon_white": "Pokémon White",
    "pokemon_black_2": "Pokémon Black 2",
    "pokemon_white_2": "Pokémon White 2",
}


def _route(rom_type) -> str | None:
    """Resolve a known ROM type unless an explicit refusal overrides its route."""
    if not isinstance(rom_type, str) or not rom_type:
        return None
    if rom_type in _REFUSED_ROM_TYPES:
        return None
    return _ROM_TYPE_TO_GAME_ID.get(rom_type)


def game_id_for_rom_type(rom_type: str) -> str | None:
    """Resolve a ROM-type string (as sent by the Lua client) to an adapter game_id.

    None when the rom_type isn't recognized, and None when a ruling refuses it by name --
    which is what refuses its hello at the server's gate (see `_route`).
    """
    return _route(rom_type)


def shared_calc_profile(profiles) -> dict | None:
    """The one calc profile every player's calc_profile() can share, or None.

    The rules (gen + dex) must agree or the calc stays hidden. Anything else -- the vendored
    trainer "sets" -- survives only when every player has the same one: Crystal paired with
    Gold/Silver still gets the Gen 2 calc, just without Crystal's trainer sets."""
    profiles = list(profiles)
    if not profiles or any(p is None for p in profiles):
        return None
    shared = {k: v for k, v in profiles[0].items() if all(p.get(k) == v for p in profiles)}
    return shared if "gen" in shared and "dex" in shared else None


# ROM types an owner ruling REFUSES, with the reason a refused hello names.
#
# An explicit refusal wins over the routing table. Archipelago Crystal also has no
# table row because its legacy adapter is gone.
_ARCHIPELAGO_CRYSTAL = "Archipelago Crystal is not supported (O-25)"
_REFUSED_ROM_TYPES: dict[str, str] = {
    "crystal_ap": _ARCHIPELAGO_CRYSTAL, "Crystal (AP)": _ARCHIPELAGO_CRYSTAL,
}


def unrouted_rom_type_reason(rom_type) -> str:
    """Why a rom_type with no route is refused: its ruling when one refuses it by name."""
    reason = _REFUSED_ROM_TYPES.get(rom_type) if isinstance(rom_type, str) else None
    return reason or "not a game this server routes"


# game_ids whose adapter is GONE: a run persisted under one is refused at load
# (server/state.py load(), via persisted_migration_refusal), whatever its rom_type resolves to
# today -- including nothing -- rather than reopened under the default adapter.
#
# `gen2_crystal` is the legacy Gen 2 adapter, removed by P3b.8. Crystal/Gold/Silver moved to
# `gen2_gsc` at U5, but the two adapters put the SAME physical gift event under DIFFERENT
# area_id keys (a starter pickup was bare "new_bark_town" under the old adapter,
# "gift_new_bark_town" under gen2_gsc; the daycare was bare "route_34" vs "gift_daycare"), so
# reinterpreting old keys would silently orphan a pending gift/daycare capture or mis-track
# area cooldowns. Archipelago Crystal, its last route, is refused outright (O-25).
_RETIRED_GAME_IDS: dict[str, str] = {
    "gen2_crystal": "the legacy Gen 2 adapter, removed at the P3b.8 cutover",
}


def persisted_migration_refusal(old_game_id: str, new_game_id: str | None) -> str | None:
    """None if a run persisted under old_game_id may reload under new_game_id.

    Otherwise, the operator-facing reason it must not (see
    _RETIRED_GAME_IDS). new_game_id is what the run's rom_type resolves to today, or None when
    it no longer routes.
    """
    retired = _RETIRED_GAME_IDS.get(old_game_id)
    if not retired:
        return None
    now = (f"its rom_type now resolves to {new_game_id!r}, and the two adapters use "
           f"incompatible area_id/state formats -- reopening it there would silently "
           f"corrupt or orphan persisted gift/daycare state"
           if new_game_id else "its rom_type no longer routes to any adapter")
    return (f"this run was saved under adapter {old_game_id!r} ({retired}); {now}. Archive "
            f"or delete this run's links.json to start a fresh run.")


# ROM-type string → PAIRING FOUNDATION, where a game_id is too coarse to pair on.
# A foundation is a data pack + memory layout, not a class: Radical Red and vanilla
# FireRed share `Gen3Adapter` but share no layout, so a clean FR must not pair with a
# clean RR. Everything absent here derives its foundation from its game_id, which is
# already fine-grained enough (the Gen 1 packs differ by game_id: gen1_rby vs
# gen1_purergb). Adding a Gen 3 ROM variant: add it here too (docs/gen3/PLAN.md §5.1).
_ROM_TYPE_TO_FOUNDATION: dict[str, str] = {
    "firered": "gen3_frlg", "leafgreen": "gen3_frlg",
    "firered_ap": "gen3_frlg", "leafgreen_ap": "gen3_frlg",
    "firered_rr": "gen3_rr",
    # Emerald shares Gen3Adapter (game_id gen3_frlge) but not FR/LG's layout or maps: its own
    # pack, so it pairs only with Emerald (docs/gen3_emerald/PLAN.md §2 decision 5).
    "emerald": "gen3_emerald",
    "emerald_expansion_28877d73": "gen3_exp",
    # Gen 2 (docs/gen2/PLAN.md §5.9, owner O-16): ONE foundation for Gold, Silver and
    # Crystal, so every Gen 2 pairing is admitted with no title relation in shared code.
    # EVERY spelling has a row: the title-cased ones are what both clients send and what
    # existing run directories persist, and a missing row would silently fall back to the
    # legacy game_id. `crystal_ap` has no row: it is refused (O-25), so it has no foundation.
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
    game_id = _route(rom_type)
    if game_id is None:
        return None
    return _ROM_TYPE_TO_FOUNDATION.get(rom_type, game_id)


def adapter_class_for_rom_type(rom_type: str) -> type[GameAdapter] | None:
    """The registered adapter CLASS for a rom_type, without instantiating it.

    For pure class-level lookups (`pairing_kind`) on a hello that may still be refused:
    no candidate adapter is installed to answer the question. None when unrecognized --
    and None when a ruling refuses the rom_type, which is the same answer.
    """
    game_id = _route(rom_type)
    return _REGISTRY.get(game_id) if game_id else None


def variant_label(rom_type: str) -> str:
    """Human-readable label for a ROM type. Falls back to the rom_type itself."""
    return _VARIANT_LABEL.get(rom_type, rom_type)


# Auto-register built-in adapters on import
from .gen3_frlge import Gen3Adapter  # noqa: E402

register_adapter("gen3_frlge", Gen3Adapter)
# Backward compat: "frlg" was the old game_id; alias to gen3_frlge
register_adapter("frlg", Gen3Adapter)

from .gen3_expansion import Gen3ExpansionAdapter  # noqa: E402

register_adapter("gen3_exp", Gen3ExpansionAdapter)

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

# Routed for Crystal, Gold and Silver (U5 cutover, above).
from .gen2_gsc import Gen2GSCAdapter  # noqa: E402

register_adapter("gen2_gsc", Gen2GSCAdapter)
