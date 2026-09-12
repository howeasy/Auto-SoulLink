"""Locked Gen1 RC settings policy. Passing this never admits the output ROM.

Every boolean and enum is named by the shared source-derived catalog. Integer
fields that belong to disabled controls have a canonical inactive encoding.
The semantic scanner must separately enforce all cartridge-domain invariants.
"""
from server.upr_catalog import FIELDS, read_effective, read_file, settings_file
from server.upr_settings import UprSettingsError

ALLOWED_ENUMS = {
    "startersMod": {"UNCHANGED", "CUSTOM", "COMPLETELY_RANDOM", "RANDOM_WITH_TWO_EVOLUTIONS"},
    "wildPokemonMod": {"UNCHANGED", "RANDOM", "AREA_MAPPING", "GLOBAL_MAPPING"},
    "staticPokemonMod": {"UNCHANGED", "RANDOM_MATCHING", "COMPLETELY_RANDOM", "SIMILAR_STRENGTH"},
    "trainersMod": {"UNCHANGED", "RANDOM", "DISTRIBUTED", "TYPE_THEMED", "TYPE_THEMED_ELITE4_GYMS"},
    "tmsMod": {"UNCHANGED", "RANDOM"},
    "fieldItemsMod": {"UNCHANGED", "RANDOM", "SHUFFLE", "RANDOM_EVEN"},
}
ALLOWED_BOOLEANS = frozenset({"changeImpossibleEvolutions", "makeEvolutionsEasier",
                              "removeTimeBasedEvolutions", "trainersLevelModified"})
_INTEGER_DEFAULTS = {
    "customStarters[0]": 65536, "customStarters[1]": 65536, "customStarters[2]": 65536,
    "guaranteedMoveCount": 2, "trainersForceFullyEvolvedLevel": 30,
    "minimumCatchRateLevel": 1,
}


def defaults():
    values = {}
    for name, field in FIELDS.items():
        kind = field["kind"]
        if kind == "boolean":
            values[name] = False
        elif kind == "integer":
            values[name] = _INTEGER_DEFAULTS.get(name, 0)
        elif kind == "enum":
            choices = field["choices"]
            value = "NONE" if name == "wildPokemonRestrictionMod" else "LEGENDARIES" if name == "expCurveMod" else "UNCHANGED"
            assert value in choices, "unreviewed enum default: "+name
            values[name] = value
    return values


def validate(values, *, effective=False):
    expected = defaults()
    if set(values) != set(expected):
        raise UprSettingsError("incomplete Gen1 settings catalog")
    bad = []
    for name, value in values.items():
        if name in ALLOWED_ENUMS:
            valid = value in ALLOWED_ENUMS[name]
        elif name in ALLOWED_BOOLEANS:
            valid = type(value) is bool
        elif name == "currentMiscTweaks":
            valid = type(value) is int and value in (0, 8)  # MiscTweak.FASTEST_TEXT
        elif name == "trainersLevelModifier":
            valid = type(value) is int and (-50 <= value <= 50 if values["trainersLevelModified"] else value == 0)
        elif name.startswith("customStarters["):
            valid = type(value) is int and (1 <= value <= 151 if effective or values["startersMod"] == "CUSTOM" else value == 65536)
        else:
            valid = type(value) is type(expected[name]) and value == expected[name]
        if not valid:
            bad.append(name+"="+repr(value))
    if bad:
        raise UprSettingsError("outside Gen1 RC settings policy: "+", ".join(bad))
    return values


def build_preset(changes=None):
    values = defaults()
    values.update(changes or {})
    return settings_file(validate(values))


def validate_file(raw):
    return validate(read_file(raw))


def verify_effective(raw, effective_string, canonical_starters):
    """Only source-defined inactive starter sentinel replacement may differ."""
    wanted = validate_file(raw)
    actual = validate(read_effective(effective_string), effective=True)
    if (not isinstance(canonical_starters, (tuple, list)) or len(canonical_starters) not in (2, 3)
            or any(type(species) is not int or not 1 <= species <= 151 for species in canonical_starters)):
        raise UprSettingsError("canonical starter evidence required")
    for index in range(3):
        name = f"customStarters[{index}]"
        if wanted[name] == 65536:
            wanted[name] = canonical_starters[index] if index < len(canonical_starters) else 1
    differing = [name for name in wanted if wanted[name] != actual[name]]
    if differing:
        raise UprSettingsError("effective settings changed: "+", ".join(differing))
    return actual
