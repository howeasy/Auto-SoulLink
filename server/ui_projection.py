"""Detached presentation normalization; never a gameplay permission engine."""

import math

from server.adapters import game_id_for_rom_type


def health(mon):
    """One raw-ratio HP policy for the board and reusable renderers."""
    hp, maximum = mon.get("hp"), mon.get("maxHP")
    known = all(type(value) in (int, float) and math.isfinite(value) for value in (hp, maximum))
    known = known and hp >= 0 and maximum > 0 and hp <= maximum
    if not known:
        return {"known": False, "hp": None, "maximum": None, "ratio": None, "percent": None, "bar": None, "color": "unknown"}
    ratio = hp / maximum
    return {"known": True, "hp": hp, "maximum": maximum, "ratio": ratio,
            "percent": math.floor(ratio * 100 + .5), "bar": round(max(0, min(100, ratio * 100)), 3),
            "color": "high" if ratio > .5 else "mid" if ratio > .2 else "low"}

# name, adapter fact, existing backend gate, configurable rule, verified patch fact
FEATURES = (
    ("abilities", "supports_abilities", None, False, None),
    ("info_panel", "supports_info_panel", "panel", False, "panel"),
    ("explode_mode", "supports_explode_mode", "explode_mode", True, None),
    ("rival_team_swap", "has_rival_trainers", "rival_team_swap", True, None),
    ("overworld_presence", None, "overworld_presence", True, None),
    ("native_messages", None, "native_messages", True, None),
    ("native_sounds", None, "native_sounds", True, "sfx"),
    ("battle_calc", None, "battle_calc", True, None),
    ("pc_trade_npc", None, "pc_trade_npc", True, "pc_trade"),
)


def _boolean(value):
    return value if type(value) is bool else None


def player_capabilities(facts, requested_rules):
    """Normalize only supplied facts, preserving independent unknown dimensions."""
    declared = facts.get("declared_cartridge") or {}
    rom_type = declared.get("rom_type")
    verified = facts.get("verified_cartridge") or {}
    known = bool(verified) or (isinstance(rom_type, str) and bool(game_id_for_rom_type(rom_type)))
    adapter = (facts.get("adapter") or {}) if known else {}
    gates = (facts.get("feature_gates") or {}) if known else {}
    readiness = (facts.get("feature_readiness") or {}) if known else {}
    patch = verified.get("capabilities") or {}
    admission = facts.get("admission") or {}
    admission_reason = admission.get("reason") if admission.get("state") == "rejected" else None
    result = {}
    for name, support_key, gate_key, configurable, patch_key in FEATURES:
        support = _boolean(adapter.get(support_key)) if support_key else None
        if patch_key in patch:
            support = _boolean(patch[patch_key])
        ready = _boolean(readiness.get(name))
        effective = _boolean(gates.get(gate_key)) if gate_key else None
        reason = None
        if not known:
            reason = admission_reason or "Awaiting cartridge identity."
        elif support is False:
            reason = "Not supported by this cartridge."
        elif admission_reason:
            reason = admission_reason
        elif ready is False:
            reason = "The runtime reports this feature is not ready."
        elif effective is False:
            reason = "The runtime reports this feature is inactive."
        elif support is None and effective is None:
            reason = "Availability has not been verified."
        entry = {"supported": support, "ready": ready, "effective": effective, "reason": reason}
        if configurable:
            entry["requested"] = _boolean(requested_rules.get(name))
        result[name] = entry
    return result


def move_details(adapter, mon, *, boxed=False):
    """Resolve moves through the player's adapter, preserving existing PP semantics."""
    moves = mon.get("moves", [])
    pp = mon.get("pp", [])
    bonuses = mon.get("pp_bonuses", 0)
    pp_ups = mon.get("pp_ups") or []
    result = []
    for index, move in enumerate(moves):
        if move and move > 0:
            value = adapter.move_data(move)
            if value:
                value = dict(value)
                base = value.get("pp", 0)
                if not boxed and base:
                    ups = pp_ups[index] if index < len(pp_ups) else (bonuses >> (index * 2)) & 3
                    value["pp"] = adapter.max_move_pp(base, ups)
                value["current_pp"] = value.get("pp", 0) if boxed or index >= len(pp) else pp[index]
                result.append(value)
    return result
