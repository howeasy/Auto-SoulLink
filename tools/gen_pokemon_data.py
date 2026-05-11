#!/usr/bin/env python3
"""Generate server/pokemon_data.py with FRLG/CFRU internal species IDs.

Reads a TSV of CFRU species (ID\\tNAME) and outputs the complete module
with SPECIES_NAMES, GENDER_RATIO, and EVO_FAMILY keyed by internal ID.

Usage:
    python tools/gen_pokemon_data.py > server/pokemon_data.py
    python tools/gen_pokemon_data.py --tsv path/to/cfru_all_species.tsv
    python tools/gen_pokemon_data.py -o server/pokemon_data.py
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# ── Default TSV path ────────────────────────────────────────────────────────
DEFAULT_TSV = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMP", ".")),
    "cfru_all_species.tsv",
)

# ── Name-cleaning rules ────────────────────────────────────────────────────

# Exact overrides (CFRU_NAME → display name).  Checked BEFORE generic rules.
EXACT_NAME: dict[str, str] = {
    "NIDORAN_F":  "Nidoran♀",
    "NIDORAN_M":  "Nidoran♂",
    "FARFETCHD":  "Farfetch'd",
    "MR_MIME":    "Mr. Mime",
    "HO_OH":      "Ho-Oh",
    "PORYGON2":   "Porygon2",
    "PORYGON_Z":  "Porygon-Z",
    "MIME_JR":    "Mime Jr.",
    "MR_RIME":    "Mr. Rime",
    "TYPE_NULL":  "Type: Null",
    "TAPU_KOKO":  "Tapu Koko",
    "TAPU_LELE":  "Tapu Lele",
    "TAPU_BULU":  "Tapu Bulu",
    "TAPU_FINI":  "Tapu Fini",
    "FLABEBE":    "Flabébé",
    "JANGMO_O":   "Jangmo-o",
    "HAKAMO_O":   "Hakamo-o",
    "KOMMO_O":    "Kommo-o",
    "SIRFETCHD":  "Sirfetch'd",
    # Gen 9
    "WO_CHIEN":   "Wo-Chien",
    "CHIEN_PAO":  "Chien-Pao",
    "TING_LU":    "Ting-Lu",
    "CHI_YU":     "Chi-Yu",
    # Regional forms
    "DARMANITANZEN": "Darmanitan-Zen",
    "ASHGRENINJA":   "Ash-Greninja",
}

# Form suffix → display suffix mapping for _clean_name
_FORM_SUFFIX_DISPLAY: dict[str, str] = {
    "_A": "-Alola", "_G": "-Galar", "_H": "-Hisui", "_P": "-Paldea",
    "_MEGA": " (Mega)", "_MEGA_X": " (Mega X)", "_MEGA_Y": " (Mega Y)",
    "_PRIMAL": " (Primal)", "_GIGA": " (Giga)",
    "_ORIGIN": "-Origin", "_SKY": "-Sky", "_THERIAN": "-Therian",
    "_ATTACK": "-Attack", "_DEFENSE": "-Defense", "_SPEED": "-Speed",
    "_BLACK": "-Black", "_WHITE": "-White",
    "_DUSK": "-Dusk", "_MIDNIGHT": "-Midnight", "_MIDDAY": "-Midday",
    "_RESOLUTE": "-Resolute", "_BLADE": "-Blade", "_SHIELD": "-Shield",
    "_LOW_KEY": "-Low Key", "_AMPED": "-Amped",
    "_SINGLE_STRIKE": "-Single Strike", "_RAPID_STRIKE": "-Rapid Strike",
    "_ICE_RIDER": "-Ice Rider", "_SHADOW_RIDER": "-Shadow Rider",
    "_CROWNED_SWORD": "-Crowned Sword", "_CROWNED_SHIELD": "-Crowned Shield",
    "_BLOODMOON": "-Bloodmoon",
    "_F": "♀", "_M": "♂", "_FEMALE": " (F)", "_MALE": " (M)",
    "_HEAT": "-Heat", "_WASH": "-Wash", "_FROST": "-Frost",
    "_FAN": "-Fan", "_MOW": "-Mow",
    "_SANDY": "-Sandy", "_TRASH": "-Trash",
    "_EAST": "-East", "_RED": "-Red", "_BLUE": "-Blue",
    "_STRAWBERRY": "-Strawberry", "_BERRY": "-Berry", "_CLOVER": "-Clover",
    "_FLOWER": "-Flower", "_LOVE": "-Love", "_RIBBON": "-Ribbon",
    "_STAR": "-Star",
    "_SINGLE": "-Single Strike", "_RAPID": "-Rapid Strike",
    "_WELLSPRING_MASK": "-Wellspring", "_HEARTHFLAME_MASK": "-Hearthflame",
    "_CORNERSTONE_MASK": "-Cornerstone",
    "_TERASTAL": "-Terastal", "_STELLAR": "-Stellar",
}

# Form suffixes that should be skipped entirely.
_SKIP_SUFFIXES = (
    "_MEGA", "_MEGA_X", "_MEGA_Y", "_PRIMAL", "_GIGA",
    "_ORIGIN", "_SKY", "_THERIAN",
    # Arceus forms
    "_FIGHT", "_FLYING", "_POISON", "_GROUND", "_ROCK", "_BUG",
    "_GHOST", "_STEEL", "_FIRE", "_WATER", "_GRASS", "_ELECTRIC",
    "_PSYCHIC", "_ICE", "_DRAGON", "_DARK", "_FAIRY",
    # Silvally forms (same type suffixes, but prefixed)
)

# Prefixes whose form variants (anything beyond the base name) should be
# skipped.  The base form itself is kept.
_SKIP_FORM_PREFIXES: set[str] = {
    "UNOWN", "DEOXYS", "CASTFORM", "ROTOM", "GIRATINA", "SHAYMIN",
    "ARCEUS", "WORMADAM", "SHELLOS", "GASTRODON", "BURMY", "BASCULIN",
    "MEOWSTIC", "AEGISLASH", "PUMPKABOO", "GOURGEIST", "ORICORIO",
    "LYCANROC", "WISHIWASHI", "MINIOR", "MIMIKYU", "TOXTRICITY",
    "INDEEDEE", "MORPEKO", "URSHIFU", "CALYREX", "ZACIAN", "ZAMAZENTA",
    "KYUREM", "NECROZMA", "ZYGARDE", "HOOPA", "SILVALLY",
    "VIVILLON", "FURFROU", "PIKACHU", "PICHU", "KELDEO",
    "MELOETTA", "GENESECT", "DEERLING", "SAWSBUCK", "CHERRIM",
    "HIPPOPOTAS", "HIPPOWDON", "PYROAR", "FLABEBE", "FLOETTE", "FLORGES",
    "ALCREMIE", "EISCUE", "CRAMORANT", "SINISTEA", "POLTEAGEIST",
    "ETERNATUS", "ZARUDE", "XERNEAS", "MAGEARNA",
    "DARMANITAN",
    # Gen 9
    "SQUAWKABILLY", "MAUSHOLD", "PALAFIN", "TATSUGIRI", "DUDUNSPARCE",
    "GIMMIGHOUL", "POLTCHAGEIST", "SINISTCHA", "OGERPON", "TERAPAGOS",
    "URSALUNA", "TAUROS",
}

# Regional suffixes: _A (Alola), _G (Galar), _H (Hisui), _P (Paldea)
_REGIONAL_SUFFIX_RE = re.compile(r"^(.+)_([AGHP])$")

# Gendered form suffixes
_GENDERED_SUFFIX_RE = re.compile(r"^(.+)_(F|M|FEMALE|MALE)$")

# Names that are gendered forms where we keep _M / base only
_GENDERED_KEEP_M: set[str] = {
    "BASCULEGION", "UNFEZANT", "FRILLISH", "JELLICENT",
}


def _is_form_variant(name: str) -> bool:
    """Return True if *name* is a form variant that should be skipped."""
    # Never skip exact-override names (NIDORAN_F, NIDORAN_M, etc.)
    if name in EXACT_NAME:
        return False

    if name == "EGG":
        return True
    if name == "SHADOW_WARRIOR":
        return True

    # Check exact skip suffixes
    for sfx in _SKIP_SUFFIXES:
        if name.endswith(sfx):
            return True

    # Check prefix-based form skips (UNOWN_B, DEOXYS_ATTACK, etc.)
    parts = name.split("_", 1)
    if len(parts) == 2 and parts[0] in _SKIP_FORM_PREFIXES:
        return True

    # Regional forms: MEOWTH_A, VULPIX_G, etc.
    m = _REGIONAL_SUFFIX_RE.match(name)
    if m:
        return True

    # Gendered forms: BASCULEGION_F, UNFEZANT_F, etc.
    m = _GENDERED_SUFFIX_RE.match(name)
    if m:
        base = m.group(1)
        suffix = m.group(2)
        # Skip _F / _FEMALE variants for species in the keep-M set
        if base in _GENDERED_KEEP_M and suffix in ("F", "FEMALE"):
            return True
        # Skip any _M / _MALE / _F / _FEMALE variant if the base form exists
        # (we keep base forms; gendered variants are skipped)
        if base in _GENDERED_KEEP_M and suffix in ("M", "MALE"):
            # We KEEP the _M variant only when there's no standalone base
            # The TSV has BASCULEGION_M but no plain BASCULEGION
            return False
        # Other _F/_FEMALE forms
        if suffix in ("F", "FEMALE"):
            return True
        return False

    return False


def _clean_name(raw: str) -> str:
    """Convert a CFRU constant name to a human-readable display name."""
    if raw in EXACT_NAME:
        return EXACT_NAME[raw]
    # Try form suffix mapping (longest match first)
    for suffix, display in sorted(_FORM_SUFFIX_DISPLAY.items(), key=lambda x: -len(x[0])):
        if raw.endswith(suffix):
            base_raw = raw[:-len(suffix)]
            if base_raw in EXACT_NAME:
                base_clean = EXACT_NAME[base_raw]
            else:
                base_clean = base_raw.replace("_", " ").title()
            return base_clean + display
    # Arceus/Silvally type forms: ARCEUS_FIRE → Arceus-Fire
    for prefix in ("ARCEUS", "SILVALLY"):
        if raw.startswith(prefix + "_"):
            form = raw[len(prefix) + 1:].title()
            return f"{prefix.title()}-{form}"
    # Replace underscores with spaces, then title-case
    return raw.replace("_", " ").title()


# ── Read TSV ────────────────────────────────────────────────────────────────

def read_tsv(path: str) -> dict[int, str]:
    """Return {cfru_id: CFRU_NAME} from the TSV file."""
    entries: dict[int, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            try:
                sid = int(parts[0])
            except ValueError:
                continue
            name = parts[1].strip()
            entries[sid] = name
        return entries


# ── SPECIES_NAMES ───────────────────────────────────────────────────────────

def build_species_names(raw: dict[int, str]) -> dict[int, str]:
    """Build the SPECIES_NAMES dict including base forms AND relevant variants.

    We include all species except the gap (252-276) and a few skip-only entries
    like EGG and SHADOW_WARRIOR.  Form variants get cleaned names with form
    suffixes (e.g. 'Vulpix-Alola', 'Meowth-Galar').
    """
    result: dict[int, str] = {}
    for sid, name in sorted(raw.items()):
        # Skip IDs 252-276 (FRLG gap)
        if 252 <= sid <= 276:
            continue
        # Skip true garbage entries
        if name in ("EGG", "SHADOW_WARRIOR"):
            continue
        result[sid] = _clean_name(name)
    return result


# ── GENDER_RATIO ────────────────────────────────────────────────────────────
# Only entries that deviate from the default of 127 (50/50).
# Values: 0=always-male, 31=12.5%F, 63=25%F, 191=75%F, 254=always-female,
#         255=genderless.

def build_gender_ratio(raw: dict[int, str]) -> dict[int, int]:
    """Build the GENDER_RATIO dict using CFRU internal IDs."""
    # Helper: look up ID by name
    name_to_id: dict[str, int] = {v: k for k, v in raw.items()}

    def _id(name: str) -> int | None:
        return name_to_id.get(name)

    def _ids(*names: str) -> list[int]:
        return [name_to_id[n] for n in names if n in name_to_id]

    ratio: dict[int, int] = {}

    def _set(ids: list[int], val: int) -> None:
        for i in ids:
            ratio[i] = val

    # ── 12.5% female (31) ──────────────────────────────────────────────
    # All starter lines Gen 1-8
    starters = [
        # Gen 1
        "BULBASAUR","IVYSAUR","VENUSAUR","CHARMANDER","CHARMELEON","CHARIZARD",
        "SQUIRTLE","WARTORTLE","BLASTOISE",
        # Gen 2
        "CHIKORITA","BAYLEEF","MEGANIUM","CYNDAQUIL","QUILAVA","TYPHLOSION",
        "TOTODILE","CROCONAW","FERALIGATR",
        # Gen 3
        "TREECKO","GROVYLE","SCEPTILE","TORCHIC","COMBUSKEN","BLAZIKEN",
        "MUDKIP","MARSHTOMP","SWAMPERT",
        # Gen 4
        "TURTWIG","GROTLE","TORTERRA","CHIMCHAR","MONFERNO","INFERNAPE",
        "PIPLUP","PRINPLUP","EMPOLEON",
        # Gen 5
        "SNIVY","SERVINE","SERPERIOR","TEPIG","PIGNITE","EMBOAR",
        "OSHAWOTT","DEWOTT","SAMUROTT",
        # Gen 6
        "CHESPIN","QUILLADIN","CHESNAUGHT","FENNEKIN","BRAIXEN","DELPHOX",
        "FROAKIE","FROGADIER","GRENINJA",
        # Gen 7
        "ROWLET","DARTRIX","DECIDUEYE","LITTEN","TORRACAT","INCINEROAR",
        "POPPLIO","BRIONNE","PRIMARINA",
        # Gen 8
        "GROOKEY","THWACKEY","RILLABOOM","SCORBUNNY","RABOOT","CINDERACE",
        "SOBBLE","DRIZZILE","INTELEON",
        # Gen 9
        "SPRIGATITO","FLORAGATO","MEOWSCARADA",
        "FUECOCO","CROCALOR","SKELEDIRGE",
        "QUAXLY","QUAXWELL","QUAQUAVAL",
    ]
    _set(_ids(*starters), 31)

    # Eevee + all eeveelutions
    _set(_ids("EEVEE","VAPOREON","JOLTEON","FLAREON","ESPEON","UMBREON",
              "LEAFEON","GLACEON","SYLVEON"), 31)

    # Fossil mons
    _set(_ids("OMANYTE","OMASTAR","KABUTO","KABUTOPS","AERODACTYL",
              "LILEEP","CRADILY","ANORITH","ARMALDO",
              "CRANIDOS","RAMPARDOS","SHIELDON","BASTIODON",
              "TIRTOUGA","CARRACOSTA","ARCHEN","ARCHEOPS",
              "TYRUNT","TYRANTRUM","AMAURA","AURORUS"), 31)

    # Snorlax/Munchlax
    _set(_ids("SNORLAX","MUNCHLAX"), 31)

    # Riolu/Lucario
    _set(_ids("RIOLU","LUCARIO"), 31)

    # Togepi line + Togekiss
    _set(_ids("TOGEPI","TOGETIC","TOGEKISS"), 31)

    # Larvitar line
    _set(_ids("LARVITAR","PUPITAR","TYRANITAR"), 31)

    # Bagon line
    _set(_ids("BAGON","SHELGON","SALAMENCE"), 31)

    # Dratini line
    _set(_ids("DRATINI","DRAGONAIR","DRAGONITE"), 31)

    # ── Always male (0) ───────────────────────────────────────────────
    _set(_ids("NIDORAN_M","NIDORINO","NIDOKING"), 0)
    _set(_ids("HITMONLEE","HITMONCHAN","HITMONTOP","TYROGUE"), 0)
    _set(_ids("TAUROS"), 0)
    _set(_ids("VOLBEAT"), 0)
    _set(_ids("LATIOS"), 0)
    _set(_ids("GALLADE"), 0)
    _set(_ids("MOTHIM"), 0)
    _set(_ids("SAWK","THROH"), 0)
    _set(_ids("RUFFLET","BRAVIARY"), 0)
    _set(_ids("IMPIDIMP","MORGREM","GRIMMSNARL"), 0)
    # Gen 9
    _set(_ids("OKIDOGI"), 0)
    _set(_ids("MUNKIDORI"), 0)

    # ── Always female (254) ──────────────────────────────────────────
    _set(_ids("NIDORAN_F","NIDORINA","NIDOQUEEN"), 254)
    _set(_ids("JYNX","SMOOCHUM"), 254)
    _set(_ids("CHANSEY","BLISSEY","HAPPINY"), 254)
    _set(_ids("KANGASKHAN"), 254)
    _set(_ids("MILTANK"), 254)
    _set(_ids("ILLUMISE"), 254)
    _set(_ids("LATIAS"), 254)
    _set(_ids("FROSLASS"), 254)
    _set(_ids("WORMADAM"), 254)
    _set(_ids("VESPIQUEN"), 254)
    _set(_ids("CRESSELIA"), 254)
    _set(_ids("PETILIL","LILLIGANT"), 254)
    _set(_ids("FLABEBE","FLOETTE","FLORGES"), 254)
    _set(_ids("BOUNSWEET","STEENEE","TSAREENA"), 254)
    _set(_ids("SALAZZLE"), 254)
    _set(_ids("HATENNA","HATTREM","HATTERENE"), 254)
    _set(_ids("COMBEE"), 254)  # Only female Combee evolves but ratio is still all-female for Vespiquen
    # Gen 9
    _set(_ids("TINKATINK","TINKATUFF","TINKATON"), 254)
    _set(_ids("OGERPON"), 254)
    _set(_ids("FEZANDIPITI"), 254)

    # ── Genderless (255) ─────────────────────────────────────────────
    _set(_ids("MAGNEMITE","MAGNETON","MAGNEZONE"), 255)
    _set(_ids("VOLTORB","ELECTRODE"), 255)
    _set(_ids("DITTO"), 255)
    _set(_ids("PORYGON","PORYGON2","PORYGON_Z"), 255)
    _set(_ids("STARYU","STARMIE"), 255)
    _set(_ids("UNOWN"), 255)
    # Gen 1 legends
    _set(_ids("ARTICUNO","ZAPDOS","MOLTRES","MEWTWO","MEW"), 255)
    # Gen 2 legends
    _set(_ids("RAIKOU","ENTEI","SUICUNE","LUGIA","HO_OH","CELEBI"), 255)
    # Gen 3 legends
    _set(_ids("REGIROCK","REGICE","REGISTEEL",
              "KYOGRE","GROUDON","RAYQUAZA","JIRACHI","DEOXYS"), 255)
    # Gen 3 genderless
    _set(_ids("BELDUM","METANG","METAGROSS"), 255)
    _set(_ids("LUNATONE","SOLROCK"), 255)
    _set(_ids("BALTOY","CLAYDOL"), 255)
    # Gen 4 legends
    _set(_ids("UXIE","MESPRIT","AZELF","DIALGA","PALKIA","HEATRAN",
              "REGIGIGAS","GIRATINA","PHIONE","MANAPHY","DARKRAI",
              "SHAYMIN","ARCEUS"), 255)
    _set(_ids("BRONZOR","BRONZONG"), 255)
    _set(_ids("ROTOM"), 255)
    # Gen 5 genderless
    _set(_ids("KLINK","KLANG","KLINKLANG"), 255)
    _set(_ids("GOLETT","GOLURK"), 255)
    _set(_ids("CRYOGONAL"), 255)
    _set(_ids("COBALION","TERRAKION","VIRIZION"), 255)
    _set(_ids("RESHIRAM","ZEKROM","KYUREM"), 255)
    _set(_ids("KELDEO","MELOETTA","GENESECT","VICTINI"), 255)
    # Gen 6 genderless
    _set(_ids("CARBINK"), 255)
    _set(_ids("XERNEAS","YVELTAL","ZYGARDE","DIANCIE","HOOPA","VOLCANION"), 255)
    # Gen 7 genderless
    _set(_ids("TYPE_NULL","SILVALLY"), 255)
    _set(_ids("MINIOR"), 255)
    _set(_ids("DHELMISE"), 255)
    _set(_ids("COSMOG","COSMOEM","SOLGALEO","LUNALA"), 255)
    _set(_ids("NIHILEGO","BUZZWOLE","PHEROMOSA","XURKITREE",
              "CELESTEELA","KARTANA","GUZZLORD"), 255)
    _set(_ids("NECROZMA","MARSHADOW","POIPOLE","NAGANADEL",
              "STAKATAKA","BLACEPHALON","ZERAORA","MAGEARNA"), 255)
    _set(_ids("TAPU_KOKO","TAPU_LELE","TAPU_BULU","TAPU_FINI"), 255)
    # Gen 8 genderless
    _set(_ids("FALINKS"), 255)
    _set(_ids("SINISTEA","POLTEAGEIST"), 255)
    _set(_ids("DRACOZOLT","ARCTOZOLT","DRACOVISH","ARCTOVISH"), 255)
    _set(_ids("MELTAN","MELMETAL"), 255)
    _set(_ids("ZACIAN","ZAMAZENTA","ETERNATUS"), 255)
    _set(_ids("KUBFU","URSHIFU"), 255)  # Kubfu/Urshifu are actually male/female; correction below
    _set(_ids("CALYREX","GLASTRIER","SPECTRIER"), 255)
    _set(_ids("REGIELEKI","REGIDRAGO"), 255)
    _set(_ids("ZARUDE"), 255)
    _set(_ids("ENAMORUS"), 255)  # Actually female, correction below
    # Gen 9 genderless
    # Paradox Pokémon (past)
    _set(_ids("GREAT_TUSK","SCREAM_TAIL","BRUTE_BONNET","FLUTTER_MANE",
              "SLITHER_WING","SANDY_SHOCKS","ROARING_MOON",
              "WALKING_WAKE","GOUGING_FIRE","RAGING_BOLT"), 255)
    # Paradox Pokémon (future)
    _set(_ids("IRON_TREADS","IRON_BUNDLE","IRON_HANDS","IRON_JUGULIS",
              "IRON_MOTH","IRON_THORNS","IRON_VALIANT",
              "IRON_LEAVES","IRON_BOULDER","IRON_CROWN"), 255)
    # Treasures of Ruin
    _set(_ids("WO_CHIEN","CHIEN_PAO","TING_LU","CHI_YU"), 255)
    # Other Gen 9 legends/genderless
    _set(_ids("GIMMIGHOUL","GHOLDENGO"), 255)
    _set(_ids("KORAIDON","MIRAIDON"), 255)
    _set(_ids("TERAPAGOS"), 255)
    _set(_ids("PECHARUNT"), 255)
    _set(_ids("POLTCHAGEIST","SINISTCHA"), 255)

    # Corrections for species that aren't actually genderless:
    # Kubfu/Urshifu are 12.5% female
    _set(_ids("KUBFU","URSHIFU"), 31)
    # Enamorus is always female
    _set(_ids("ENAMORUS"), 254)
    # Buzzwole, Pheromosa etc. are actually genderless (UBs), keep as-is
    # Heatran is actually gendered (50/50) — remove its genderless entry
    for heatran_id in _ids("HEATRAN"):
        ratio.pop(heatran_id, None)

    # ── 75% female (191) ─────────────────────────────────────────────
    _set(_ids("CLEFFA","CLEFAIRY","CLEFABLE"), 191)
    _set(_ids("VULPIX","NINETALES"), 191)
    _set(_ids("IGGLYBUFF","JIGGLYPUFF","WIGGLYTUFF"), 191)
    _set(_ids("SKITTY","DELCATTY"), 191)
    _set(_ids("SNORUNT","GLALIE"), 191)

    # ── 25% female (63) ──────────────────────────────────────────────
    _set(_ids("GROWLITHE","ARCANINE"), 63)
    _set(_ids("ABRA","KADABRA","ALAKAZAM"), 63)
    _set(_ids("MACHOP","MACHOKE","MACHAMP"), 63)
    _set(_ids("ELECTABUZZ","ELEKID","ELECTIVIRE"), 63)
    _set(_ids("MAGMAR","MAGBY","MAGMORTAR"), 63)

    return ratio


# ── EVO_FAMILY ──────────────────────────────────────────────────────────────

def build_evo_family(raw: dict[int, str]) -> dict[int, int]:
    """Build EVO_FAMILY mapping evolved→base using CFRU IDs."""
    name_to_id: dict[str, int] = {v: k for k, v in raw.items()}

    def _id(name: str) -> int:
        return name_to_id[name]

    def _safe_id(name: str) -> int | None:
        return name_to_id.get(name)

    evo: dict[int, int] = {}

    def _chain(base_name: str, *evolved_names: str) -> None:
        """Map all evolved names to base_name's ID."""
        base = _safe_id(base_name)
        if base is None:
            return
        for name in evolved_names:
            eid = _safe_id(name)
            if eid is not None:
                evo[eid] = base

    # ── Gen I ────────────────────────────────────────────────────────
    _chain("BULBASAUR", "IVYSAUR", "VENUSAUR")
    _chain("CHARMANDER", "CHARMELEON", "CHARIZARD")
    _chain("SQUIRTLE", "WARTORTLE", "BLASTOISE")
    _chain("CATERPIE", "METAPOD", "BUTTERFREE")
    _chain("WEEDLE", "KAKUNA", "BEEDRILL")
    _chain("PIDGEY", "PIDGEOTTO", "PIDGEOT")
    _chain("RATTATA", "RATICATE")
    _chain("SPEAROW", "FEAROW")
    _chain("EKANS", "ARBOK")
    # Pichu → Pikachu → Raichu
    _chain("PICHU", "PIKACHU", "RAICHU")
    _chain("SANDSHREW", "SANDSLASH")
    _chain("NIDORAN_F", "NIDORINA", "NIDOQUEEN")
    _chain("NIDORAN_M", "NIDORINO", "NIDOKING")
    # Cleffa → Clefairy → Clefable
    _chain("CLEFFA", "CLEFAIRY", "CLEFABLE")
    _chain("VULPIX", "NINETALES")
    # Igglybuff → Jigglypuff → Wigglytuff
    _chain("IGGLYBUFF", "JIGGLYPUFF", "WIGGLYTUFF")
    # Zubat → Golbat → Crobat
    _chain("ZUBAT", "GOLBAT", "CROBAT")
    # Oddish → Gloom → Vileplume / Bellossom
    _chain("ODDISH", "GLOOM", "VILEPLUME", "BELLOSSOM")
    _chain("PARAS", "PARASECT")
    _chain("VENONAT", "VENOMOTH")
    _chain("DIGLETT", "DUGTRIO")
    _chain("MEOWTH", "PERSIAN")
    _chain("PSYDUCK", "GOLDUCK")
    _chain("MANKEY", "PRIMEAPE", "ANNIHILAPE")
    _chain("GROWLITHE", "ARCANINE")
    # Poliwag → Poliwhirl → Poliwrath / Politoed
    _chain("POLIWAG", "POLIWHIRL", "POLIWRATH", "POLITOED")
    _chain("ABRA", "KADABRA", "ALAKAZAM")
    _chain("MACHOP", "MACHOKE", "MACHAMP")
    _chain("BELLSPROUT", "WEEPINBELL", "VICTREEBEL")
    _chain("TENTACOOL", "TENTACRUEL")
    _chain("GEODUDE", "GRAVELER", "GOLEM")
    _chain("PONYTA", "RAPIDASH")
    # Slowpoke → Slowbro / Slowking
    _chain("SLOWPOKE", "SLOWBRO", "SLOWKING")
    # Magnemite → Magneton → Magnezone
    _chain("MAGNEMITE", "MAGNETON", "MAGNEZONE")
    _chain("DODUO", "DODRIO")
    _chain("SEEL", "DEWGONG")
    _chain("GRIMER", "MUK")
    _chain("SHELLDER", "CLOYSTER")
    _chain("GASTLY", "HAUNTER", "GENGAR")
    # Onix → Steelix
    _chain("ONIX", "STEELIX")
    _chain("DROWZEE", "HYPNO")
    _chain("KRABBY", "KINGLER")
    # Voltorb → Electrode
    _chain("VOLTORB", "ELECTRODE")
    _chain("EXEGGCUTE", "EXEGGUTOR")
    _chain("CUBONE", "MAROWAK")
    # Tyrogue → Hitmonlee / Hitmonchan / Hitmontop
    _chain("TYROGUE", "HITMONLEE", "HITMONCHAN", "HITMONTOP")
    # Lickitung → Lickilicky
    _chain("LICKITUNG", "LICKILICKY")
    _chain("KOFFING", "WEEZING")
    # Rhyhorn → Rhydon → Rhyperior
    _chain("RHYHORN", "RHYDON", "RHYPERIOR")
    # Happiny → Chansey → Blissey
    _chain("HAPPINY", "CHANSEY", "BLISSEY")
    # Tangela → Tangrowth
    _chain("TANGELA", "TANGROWTH")
    # Horsea → Seadra → Kingdra
    _chain("HORSEA", "SEADRA", "KINGDRA")
    _chain("GOLDEEN", "SEAKING")
    _chain("STARYU", "STARMIE")
    # Mime Jr. → Mr. Mime → Mr. Rime
    _chain("MIME_JR", "MR_MIME", "MR_RIME")
    # Scyther → Scizor / Kleavor
    _chain("SCYTHER", "SCIZOR", "KLEAVOR")
    # Smoochum → Jynx
    _chain("SMOOCHUM", "JYNX")
    # Elekid → Electabuzz → Electivire
    _chain("ELEKID", "ELECTABUZZ", "ELECTIVIRE")
    # Magby → Magmar → Magmortar
    _chain("MAGBY", "MAGMAR", "MAGMORTAR")
    _chain("MAGIKARP", "GYARADOS")
    # Eevee → all eeveelutions
    _chain("EEVEE", "VAPOREON", "JOLTEON", "FLAREON", "ESPEON", "UMBREON",
           "LEAFEON", "GLACEON", "SYLVEON")
    # Porygon → Porygon2 → Porygon-Z
    _chain("PORYGON", "PORYGON2", "PORYGON_Z")
    _chain("OMANYTE", "OMASTAR")
    _chain("KABUTO", "KABUTOPS")
    # Munchlax → Snorlax
    _chain("MUNCHLAX", "SNORLAX")
    _chain("DRATINI", "DRAGONAIR", "DRAGONITE")

    # ── Gen II ───────────────────────────────────────────────────────
    _chain("CHIKORITA", "BAYLEEF", "MEGANIUM")
    _chain("CYNDAQUIL", "QUILAVA", "TYPHLOSION")
    _chain("TOTODILE", "CROCONAW", "FERALIGATR")
    _chain("SENTRET", "FURRET")
    _chain("HOOTHOOT", "NOCTOWL")
    _chain("LEDYBA", "LEDIAN")
    _chain("SPINARAK", "ARIADOS")
    _chain("CHINCHOU", "LANTURN")
    # Togepi → Togetic → Togekiss
    _chain("TOGEPI", "TOGETIC", "TOGEKISS")
    _chain("NATU", "XATU")
    _chain("MAREEP", "FLAAFFY", "AMPHAROS")
    # Azurill → Marill → Azumarill
    _chain("AZURILL", "MARILL", "AZUMARILL")
    # Bonsly → Sudowoodo
    _chain("BONSLY", "SUDOWOODO")
    _chain("HOPPIP", "SKIPLOOM", "JUMPLUFF")
    # Aipom → Ambipom
    _chain("AIPOM", "AMBIPOM")
    _chain("SUNKERN", "SUNFLORA")
    # Yanma → Yanmega
    _chain("YANMA", "YANMEGA")
    _chain("WOOPER", "QUAGSIRE")
    # Murkrow → Honchkrow
    _chain("MURKROW", "HONCHKROW")
    # Misdreavus → Mismagius
    _chain("MISDREAVUS", "MISMAGIUS")
    # Wynaut → Wobbuffet
    _chain("WYNAUT", "WOBBUFFET")
    # Gligar → Gliscor
    _chain("GLIGAR", "GLISCOR")
    _chain("PINECO", "FORRETRESS")
    _chain("SNUBBULL", "GRANBULL")
    _chain("TEDDIURSA", "URSARING", "URSALUNA")
    _chain("SLUGMA", "MAGCARGO")
    # Swinub → Piloswine → Mamoswine
    _chain("SWINUB", "PILOSWINE", "MAMOSWINE")
    _chain("REMORAID", "OCTILLERY")
    # Mantyke → Mantine
    _chain("MANTYKE", "MANTINE")
    _chain("HOUNDOUR", "HOUNDOOM")
    _chain("PHANPY", "DONPHAN")
    # Stantler → Wyrdeer
    _chain("STANTLER", "WYRDEER")
    _chain("LARVITAR", "PUPITAR", "TYRANITAR")
    # Sneasel → Weavile / Sneasler
    _chain("SNEASEL", "WEAVILE", "SNEASLER")

    # ── Gen III ──────────────────────────────────────────────────────
    _chain("TREECKO", "GROVYLE", "SCEPTILE")
    _chain("TORCHIC", "COMBUSKEN", "BLAZIKEN")
    _chain("MUDKIP", "MARSHTOMP", "SWAMPERT")
    _chain("POOCHYENA", "MIGHTYENA")
    _chain("ZIGZAGOON", "LINOONE", "OBSTAGOON")
    # Wurmple → Silcoon → Beautifly / Cascoon → Dustox
    _chain("WURMPLE", "SILCOON", "BEAUTIFLY", "CASCOON", "DUSTOX")
    _chain("LOTAD", "LOMBRE", "LUDICOLO")
    _chain("SEEDOT", "NUZLEAF", "SHIFTRY")
    _chain("TAILLOW", "SWELLOW")
    _chain("WINGULL", "PELIPPER")
    # Ralts → Kirlia → Gardevoir / Gallade
    _chain("RALTS", "KIRLIA", "GARDEVOIR", "GALLADE")
    _chain("SURSKIT", "MASQUERAIN")
    _chain("SHROOMISH", "BRELOOM")
    _chain("SLAKOTH", "VIGOROTH", "SLAKING")
    # Nincada → Ninjask / Shedinja
    _chain("NINCADA", "NINJASK", "SHEDINJA")
    _chain("WHISMUR", "LOUDRED", "EXPLOUD")
    _chain("MAKUHITA", "HARIYAMA")
    _chain("SKITTY", "DELCATTY")
    # Nosepass → Probopass
    _chain("NOSEPASS", "PROBOPASS")
    _chain("ARON", "LAIRON", "AGGRON")
    _chain("MEDITITE", "MEDICHAM")
    _chain("ELECTRIKE", "MANECTRIC")
    _chain("GULPIN", "SWALOT")
    _chain("CARVANHA", "SHARPEDO")
    _chain("WAILMER", "WAILORD")
    _chain("NUMEL", "CAMERUPT")
    _chain("SPOINK", "GRUMPIG")
    _chain("TRAPINCH", "VIBRAVA", "FLYGON")
    _chain("CACNEA", "CACTURNE")
    _chain("SWABLU", "ALTARIA")
    _chain("BARBOACH", "WHISCASH")
    _chain("CORPHISH", "CRAWDAUNT")
    _chain("BALTOY", "CLAYDOL")
    _chain("LILEEP", "CRADILY")
    _chain("ANORITH", "ARMALDO")
    _chain("FEEBAS", "MILOTIC")
    _chain("SHUPPET", "BANETTE")
    # Duskull → Dusclops → Dusknoir
    _chain("DUSKULL", "DUSCLOPS", "DUSKNOIR")
    # Chingling → Chimecho
    _chain("CHINGLING", "CHIMECHO")
    # Snorunt → Glalie / Froslass
    _chain("SNORUNT", "GLALIE", "FROSLASS")
    _chain("SPHEAL", "SEALEO", "WALREIN")
    # Clamperl → Huntail / Gorebyss
    _chain("CLAMPERL", "HUNTAIL", "GOREBYSS")
    _chain("BAGON", "SHELGON", "SALAMENCE")
    _chain("BELDUM", "METANG", "METAGROSS")
    # Budew → Roselia → Roserade
    _chain("BUDEW", "ROSELIA", "ROSERADE")

    # ── Gen IV ───────────────────────────────────────────────────────
    _chain("TURTWIG", "GROTLE", "TORTERRA")
    _chain("CHIMCHAR", "MONFERNO", "INFERNAPE")
    _chain("PIPLUP", "PRINPLUP", "EMPOLEON")
    _chain("STARLY", "STARAVIA", "STARAPTOR")
    _chain("BIDOOF", "BIBAREL")
    _chain("KRICKETOT", "KRICKETUNE")
    _chain("SHINX", "LUXIO", "LUXRAY")
    _chain("CRANIDOS", "RAMPARDOS")
    _chain("SHIELDON", "BASTIODON")
    _chain("BURMY", "WORMADAM", "MOTHIM")
    _chain("COMBEE", "VESPIQUEN")
    _chain("BUIZEL", "FLOATZEL")
    _chain("CHERUBI", "CHERRIM")
    _chain("SHELLOS", "GASTRODON")
    _chain("DRIFLOON", "DRIFBLIM")
    _chain("BUNEARY", "LOPUNNY")
    _chain("GLAMEOW", "PURUGLY")
    _chain("STUNKY", "SKUNTANK")
    _chain("GIBLE", "GABITE", "GARCHOMP")
    _chain("RIOLU", "LUCARIO")
    _chain("HIPPOPOTAS", "HIPPOWDON")
    _chain("SKORUPI", "DRAPION")
    _chain("CROAGUNK", "TOXICROAK")
    _chain("FINNEON", "LUMINEON")
    _chain("SNOVER", "ABOMASNOW")

    # ── Gen V ────────────────────────────────────────────────────────
    _chain("SNIVY", "SERVINE", "SERPERIOR")
    _chain("TEPIG", "PIGNITE", "EMBOAR")
    _chain("OSHAWOTT", "DEWOTT", "SAMUROTT")
    _chain("PATRAT", "WATCHOG")
    _chain("LILLIPUP", "HERDIER", "STOUTLAND")
    _chain("PURRLOIN", "LIEPARD")
    _chain("PANSAGE", "SIMISAGE")
    _chain("PANSEAR", "SIMISEAR")
    _chain("PANPOUR", "SIMIPOUR")
    _chain("MUNNA", "MUSHARNA")
    _chain("PIDOVE", "TRANQUILL", "UNFEZANT")
    _chain("BLITZLE", "ZEBSTRIKA")
    _chain("ROGGENROLA", "BOLDORE", "GIGALITH")
    _chain("WOOBAT", "SWOOBAT")
    _chain("DRILBUR", "EXCADRILL")
    _chain("TIMBURR", "GURDURR", "CONKELDURR")
    _chain("TYMPOLE", "PALPITOAD", "SEISMITOAD")
    _chain("SEWADDLE", "SWADLOON", "LEAVANNY")
    _chain("VENIPEDE", "WHIRLIPEDE", "SCOLIPEDE")
    _chain("COTTONEE", "WHIMSICOTT")
    _chain("PETILIL", "LILLIGANT")
    _chain("SANDILE", "KROKOROK", "KROOKODILE")
    _chain("DARUMAKA", "DARMANITAN")
    _chain("DWEBBLE", "CRUSTLE")
    _chain("SCRAGGY", "SCRAFTY")
    _chain("YAMASK", "COFAGRIGUS", "RUNERIGUS")
    _chain("TIRTOUGA", "CARRACOSTA")
    _chain("ARCHEN", "ARCHEOPS")
    _chain("TRUBBISH", "GARBODOR")
    _chain("ZORUA", "ZOROARK")
    _chain("MINCCINO", "CINCCINO")
    _chain("GOTHITA", "GOTHORITA", "GOTHITELLE")
    _chain("SOLOSIS", "DUOSION", "REUNICLUS")
    _chain("DUCKLETT", "SWANNA")
    _chain("VANILLITE", "VANILLISH", "VANILLUXE")
    _chain("KARRABLAST", "ESCAVALIER")
    _chain("FOONGUS", "AMOONGUSS")
    _chain("FRILLISH", "JELLICENT")
    _chain("JOLTIK", "GALVANTULA")
    _chain("FERROSEED", "FERROTHORN")
    _chain("KLINK", "KLANG", "KLINKLANG")
    _chain("TYNAMO", "EELEKTRIK", "EELEKTROSS")
    _chain("ELGYEM", "BEHEEYEM")
    _chain("LITWICK", "LAMPENT", "CHANDELURE")
    _chain("AXEW", "FRAXURE", "HAXORUS")
    _chain("CUBCHOO", "BEARTIC")
    _chain("SHELMET", "ACCELGOR")
    _chain("PAWNIARD", "BISHARP", "KINGAMBIT")
    _chain("RUFFLET", "BRAVIARY")
    _chain("VULLABY", "MANDIBUZZ")
    _chain("DEINO", "ZWEILOUS", "HYDREIGON")
    _chain("LARVESTA", "VOLCARONA")
    _chain("GOLETT", "GOLURK")

    # ── Gen VI ───────────────────────────────────────────────────────
    _chain("CHESPIN", "QUILLADIN", "CHESNAUGHT")
    _chain("FENNEKIN", "BRAIXEN", "DELPHOX")
    _chain("FROAKIE", "FROGADIER", "GRENINJA")
    _chain("BUNNELBY", "DIGGERSBY")
    _chain("FLETCHLING", "FLETCHINDER", "TALONFLAME")
    _chain("SCATTERBUG", "SPEWPA", "VIVILLON")
    _chain("LITLEO", "PYROAR")
    _chain("FLABEBE", "FLOETTE", "FLORGES")
    _chain("SKIDDO", "GOGOAT")
    _chain("PANCHAM", "PANGORO")
    _chain("ESPURR", "MEOWSTIC")
    _chain("HONEDGE", "DOUBLADE", "AEGISLASH")
    _chain("INKAY", "MALAMAR")
    _chain("BINACLE", "BARBARACLE")
    _chain("SKRELP", "DRAGALGE")
    _chain("CLAUNCHER", "CLAWITZER")
    _chain("HELIOPTILE", "HELIOLISK")
    _chain("TYRUNT", "TYRANTRUM")
    _chain("AMAURA", "AURORUS")
    _chain("GOOMY", "SLIGGOO", "GOODRA")
    _chain("PHANTUMP", "TREVENANT")
    _chain("PUMPKABOO", "GOURGEIST")
    _chain("BERGMITE", "AVALUGG")
    _chain("NOIBAT", "NOIVERN")

    # ── Gen VII ──────────────────────────────────────────────────────
    _chain("ROWLET", "DARTRIX", "DECIDUEYE")
    _chain("LITTEN", "TORRACAT", "INCINEROAR")
    _chain("POPPLIO", "BRIONNE", "PRIMARINA")
    _chain("PIKIPEK", "TRUMBEAK", "TOUCANNON")
    _chain("YUNGOOS", "GUMSHOOS")
    _chain("GRUBBIN", "CHARJABUG", "VIKAVOLT")
    _chain("CRABRAWLER", "CRABOMINABLE")
    _chain("CUTIEFLY", "RIBOMBEE")
    _chain("ROCKRUFF", "LYCANROC")
    _chain("MAREANIE", "TOXAPEX")
    _chain("MUDBRAY", "MUDSDALE")
    _chain("DEWPIDER", "ARAQUANID")
    _chain("FOMANTIS", "LURANTIS")
    _chain("MORELULL", "SHIINOTIC")
    _chain("SALANDIT", "SALAZZLE")
    _chain("STUFFUL", "BEWEAR")
    _chain("BOUNSWEET", "STEENEE", "TSAREENA")
    _chain("WIMPOD", "GOLISOPOD")
    _chain("SANDYGAST", "PALOSSAND")
    _chain("JANGMO_O", "HAKAMO_O", "KOMMO_O")
    _chain("TYPE_NULL", "SILVALLY")
    _chain("COSMOG", "COSMOEM", "SOLGALEO", "LUNALA")
    _chain("POIPOLE", "NAGANADEL")

    # ── Gen VIII ─────────────────────────────────────────────────────
    _chain("GROOKEY", "THWACKEY", "RILLABOOM")
    _chain("SCORBUNNY", "RABOOT", "CINDERACE")
    _chain("SOBBLE", "DRIZZILE", "INTELEON")
    _chain("WOOLOO", "DUBWOOL")
    _chain("CHEWTLE", "DREDNAW")
    _chain("YAMPER", "BOLTUND")
    _chain("ROLYCOLY", "CARKOL", "COALOSSAL")
    _chain("APPLIN", "FLAPPLE", "APPLETUN")
    _chain("SILICOBRA", "SANDACONDA")
    _chain("ARROKUDA", "BARRASKEWDA")
    _chain("TOXEL", "TOXTRICITY")
    _chain("SIZZLIPEDE", "CENTISKORCH")
    _chain("CLOBBOPUS", "GRAPPLOCT")
    _chain("HATENNA", "HATTREM", "HATTERENE")
    _chain("IMPIDIMP", "MORGREM", "GRIMMSNARL")
    _chain("MILCERY", "ALCREMIE")
    _chain("SINISTEA", "POLTEAGEIST")
    _chain("DREEPY", "DRAKLOAK", "DRAGAPULT")
    _chain("CUFANT", "COPPERAJAH")
    _chain("KUBFU", "URSHIFU")
    # Corsola → Cursola (Galarian)
    _chain("CORSOLA", "CURSOLA")
    # Farfetch'd → Sirfetch'd (Galarian)
    # These are regional evos but share base form with the original
    # Perrserker is Galarian Meowth evo — still maps to Meowth
    _chain("MEOWTH", "PERSIAN", "PERRSERKER")

    # Qwilfish → Overqwil (Hisuian)
    _chain("QWILFISH", "OVERQWIL")

    # ── Gen IX ───────────────────────────────────────────────────────
    _chain("SPRIGATITO", "FLORAGATO", "MEOWSCARADA")
    _chain("FUECOCO", "CROCALOR", "SKELEDIRGE")
    _chain("QUAXLY", "QUAXWELL", "QUAQUAVAL")
    _chain("LECHONK", "OINKOLOGNE")
    _chain("TAROUNTULA", "SPIDOPS")
    _chain("NYMBLE", "LOKIX")
    _chain("PAWMI", "PAWMO", "PAWMOT")
    _chain("TANDEMAUS", "MAUSHOLD")
    _chain("FIDOUGH", "DACHSBUN")
    _chain("SMOLIV", "DOLLIV", "ARBOLIVA")
    _chain("NACLI", "NACLSTACK", "GARGANACL")
    # Charcadet → Armarouge / Ceruledge
    _chain("CHARCADET", "ARMAROUGE", "CERULEDGE")
    _chain("TADBULB", "BELLIBOLT")
    _chain("WATTREL", "KILOWATTREL")
    _chain("MASCHIFF", "MABOSSTIFF")
    _chain("SHROODLE", "GRAFAIAI")
    _chain("BRAMBLIN", "BRAMBLEGHAST")
    _chain("TOEDSCOOL", "TOEDSCRUEL")
    _chain("CAPSAKID", "SCOVILLAIN")
    _chain("RELLOR", "RABSCA")
    _chain("FLITTLE", "ESPATHRA")
    _chain("TINKATINK", "TINKATUFF", "TINKATON")
    _chain("WIGLETT", "WUGTRIO")
    _chain("FINIZEN", "PALAFIN")
    _chain("VAROOM", "REVAVROOM")
    _chain("GLIMMET", "GLIMMORA")
    _chain("GREAVARD", "HOUNDSTONE")
    _chain("CETODDLE", "CETITAN")
    _chain("FRIGIBAX", "ARCTIBAX", "BAXCALIBUR")
    _chain("GIMMIGHOUL", "GHOLDENGO")
    # Cross-gen evos (Gen 9)
    _chain("GIRAFARIG", "FARIGIRAF")
    _chain("DUNSPARCE", "DUDUNSPARCE")
    # Applin → Flapple / Appletun / Dipplin → Hydrapple
    _chain("APPLIN", "FLAPPLE", "APPLETUN", "DIPPLIN", "HYDRAPPLE")
    # Duraludon → Archaludon
    _chain("DURALUDON", "ARCHALUDON")

    return evo


# ── Output formatting ───────────────────────────────────────────────────────

def _fmt_dict_int_str(name: str, d: dict[int, str], comment: str,
                      line_width: int = 78) -> str:
    """Format a dict[int, str] as a compact Python literal."""
    lines = [
        f"# {'-'*73}",
        f"# {comment}",
        f"# {'-'*73}",
        f"{name}: dict[int, str] = {{",
    ]
    items = sorted(d.items())

    # Group by generation ranges
    gen_ranges = [
        (1, 151, "Gen I"),
        (152, 251, "Gen II"),
        (277, 411, "Gen III (FRLG internal IDs 277–411)"),
        (440, 546, "Gen IV"),
        (547, 702, "Gen V"),
        (758, 938, "Gen VI"),
        (939, 1101, "Gen VII"),
        (1102, 1258, "Gen VIII"),
        (1259, 1293, "Gigantamax / Misc Forms"),
        (1294, 1440, "Gen IX"),
    ]

    def _gen_label(sid: int) -> str | None:
        for lo, hi, label in gen_ranges:
            if lo <= sid <= hi:
                return label
        return None

    current_gen = None
    buf: list[str] = []

    def flush_buf() -> None:
        if not buf:
            return
        # Join entries into lines of ~line_width
        line = "    "
        for i, entry in enumerate(buf):
            if len(line) + len(entry) + 1 > line_width and line.strip():
                lines.append(line.rstrip())
                line = "    "
            line += entry
        if line.strip():
            lines.append(line.rstrip())
        buf.clear()

    for sid, val in items:
        gen = _gen_label(sid)
        if gen != current_gen:
            flush_buf()
            if gen:
                lines.append(f"    # {gen}")
            current_gen = gen
        # Escape quotes in value
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        buf.append(f'{sid}:"{escaped}",')

    flush_buf()
    lines.append("}")
    return "\n".join(lines)


def _fmt_dict_int_int(name: str, d: dict[int, int], comment: str,
                      line_width: int = 78) -> str:
    """Format a dict[int, int] as a compact Python literal."""
    lines = [
        f"# {'-'*73}",
        f"# {comment}",
        f"# {'-'*73}",
        f"{name}: dict[int, int] = {{",
    ]
    items = sorted(d.items())

    buf: list[str] = []

    def flush_buf() -> None:
        if not buf:
            return
        line = "    "
        for entry in buf:
            if len(line) + len(entry) + 1 > line_width and line.strip():
                lines.append(line.rstrip())
                line = "    "
            line += entry
        if line.strip():
            lines.append(line.rstrip())
        buf.clear()

    for sid, val in items:
        buf.append(f"{sid}:{val},")

    flush_buf()
    lines.append("}")
    return "\n".join(lines)


def generate_module(species_names: dict[int, str],
                    gender_ratio: dict[int, int],
                    evo_family: dict[int, int],
                    cfru_to_national: dict[int, int] | None = None) -> str:
    """Return the full pokemon_data.py source."""
    parts = []

    # Module docstring
    parts.append('"""')
    parts.append("server/pokemon_data.py — Shared Pokémon data tables and helpers.")
    parts.append("")
    parts.append("Extracted from server.py so that both server.py and state.py can")
    parts.append("import species names, gender ratios, type data, and evolution families")
    parts.append("without circular dependencies.")
    parts.append("")
    parts.append("NOTE: Species IDs use FRLG/CFRU internal ordering, NOT National Dex.")
    parts.append("Gen 1–2 IDs (1–251) match NatDex. Gen 3 uses IDs 277–411.")
    parts.append("Gen 4+ uses CFRU IDs starting at 440.")
    parts.append("IDs 252–276 are unused gaps in the FRLG internal table.")
    parts.append('"""')
    parts.append("")

    # SPECIES_NAMES
    parts.append(_fmt_dict_int_str(
        "SPECIES_NAMES", species_names,
        "FRLG/CFRU internal species IDs → display names.\n"
        "# Keyed by CFRU internal ID (NOT national dex number).",
    ))
    parts.append("")
    parts.append("")

    # GENDER_RATIO
    parts.append(_fmt_dict_int_int(
        "GENDER_RATIO", gender_ratio,
        "Gender ratio thresholds.\n"
        "# threshold 0=always-male, 254=always-female, 255=genderless.\n"
        "# Otherwise: personality&0xFF < threshold → Female, else → Male.\n"
        "# Default for unlisted species: 127 (50/50).",
    ))
    parts.append("")
    parts.append("")

    # gender_from_key_species function
    parts.append('''\
def gender_from_key_species(key_str: str, species_id: int) -> str:
    """Derive gender ('male'/'female'/'genderless') from the mon key and species.

    Personality is the first component of the key (PERSONALITY:OTID).
    Gender formula (Gen III): personality & 0xFF < threshold → female, else male.
    """
    if not key_str or not species_id:
        return ""
    try:
        personality = int(key_str.split(":")[0], 16)
    except (ValueError, IndexError):
        return ""
    threshold = GENDER_RATIO.get(species_id, 127)
    if threshold == 255:
        return "genderless"
    if threshold == 254:
        return "female"
    if threshold == 0:
        return "male"
    return "female" if (personality & 0xFF) < threshold else "male"''')
    parts.append("")
    parts.append("")
    parts.append('GENDER_SYMBOL = {"male": "♂", "female": "♀", "genderless": ""}')
    parts.append("")
    parts.append("")

    # EVO_FAMILY
    parts.append(_fmt_dict_int_int(
        "EVO_FAMILY", evo_family,
        "Evolution families — maps evolved species → base-form species ID.\n"
        "#\n"
        "# Single-stage mons are NOT listed — base_form() returns the species\n"
        "# itself for any missing key.  Split evos share the same base form.\n"
        "# Uses CFRU internal IDs.",
    ))
    parts.append("")
    parts.append("")

    # CFRU_TO_NATIONAL
    if cfru_to_national:
        parts.append(_fmt_dict_int_int(
            "CFRU_TO_NATIONAL", cfru_to_national,
            "CFRU internal species ID → National Pokédex number.\n"
            "# Only non-identity mappings (where CFRU ID != NatDex).\n"
            "# Gen 1–2 (1–251) are identity and not listed.\n"
            "# Use to_national() for sprite URLs and display.",
        ))
        parts.append("")
        parts.append("")
        parts.append('''\
def to_national(cfru_id: int) -> int:
    """Convert a CFRU/FRLG internal species ID to National Pokédex number.

    Gen 1–2 IDs (1–251) pass through unchanged.
    Gen 3+ CFRU IDs are mapped via CFRU_TO_NATIONAL.
    Returns the input ID if no mapping exists.
    """
    if cfru_id <= 251:
        return cfru_id
    return CFRU_TO_NATIONAL.get(cfru_id, cfru_id)''')
    else:
        # Fallback: identity mapping if no CFRU data provided
        parts.append("CFRU_TO_NATIONAL: dict[int, int] = {}")
        parts.append("")
        parts.append("")
        parts.append('''\
def to_national(cfru_id: int) -> int:
    """Convert a CFRU/FRLG internal species ID to National Pokédex number."""
    return CFRU_TO_NATIONAL.get(cfru_id, cfru_id)''')
    parts.append("")
    parts.append("")

    # base_form function
    parts.append('''\
def base_form(species_id: int) -> int:
    """Return the base-form species ID for any mon in an evolution chain.

    Single-stage mons and base forms return themselves.
    """
    return EVO_FAMILY.get(species_id, species_id)''')
    parts.append("")

    return "\n".join(parts)


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tsv", default=DEFAULT_TSV,
                        help="Path to cfru_all_species.tsv")
    parser.add_argument("--natdex-map",
                        default=os.path.join(
                            os.environ.get("TEMP", os.environ.get("TMP", ".")),
                            "cfru_to_natdex.json"),
                        help="Path to CFRU→NatDex JSON mapping")
    parser.add_argument("-o", "--output", default=None,
                        help="Output file (default: stdout)")
    args = parser.parse_args()

    raw = read_tsv(args.tsv)
    if not raw:
        print(f"ERROR: No species found in {args.tsv}", file=sys.stderr)
        sys.exit(1)

    species_names = build_species_names(raw)
    gender_ratio = build_gender_ratio(raw)
    evo_family = build_evo_family(raw)

    # Filter gender_ratio and evo_family to only include species in names
    gender_ratio = {k: v for k, v in gender_ratio.items() if k in species_names}
    evo_family = {k: v for k, v in evo_family.items() if k in species_names}

    # Load CFRU→NatDex mapping if available
    import json
    cfru_to_national: dict[int, int] | None = None
    if os.path.isfile(args.natdex_map):
        with open(args.natdex_map, "r") as f:
            cfru_to_national = {int(k): v for k, v in json.load(f).items()}
        print(f"Loaded {len(cfru_to_national)} CFRU→NatDex mappings "
              f"from {args.natdex_map}", file=sys.stderr)

    source = generate_module(species_names, gender_ratio, evo_family,
                             cfru_to_national)

    if args.output:
        Path(args.output).write_text(source, encoding="utf-8")
        print(f"Wrote {args.output} ({len(species_names)} species, "
              f"{len(gender_ratio)} gender entries, "
              f"{len(evo_family)} evo entries)", file=sys.stderr)
    else:
        sys.stdout.buffer.write(source.encode("utf-8"))


if __name__ == "__main__":
    main()
