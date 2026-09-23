"""The Gen 3 packs' profile.json preserves Lua literals and pinned pret additions.

Legacy values are independently re-derived from Lua sources without executing Lua.
RR-P5 facts additionally check the admitted binaries, instruction/literal anchors,
independent direct pool reads, and mutations that must refuse stale witnesses.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SRC = REPO / "lua" / "games" / "gen3_frlge.lua"
PROFILES = {p: REPO / "data" / "games" / p / "profile.json" for p in ("gen3_frlg", "gen3_rr")}

# which Lua profile table each admitted/unadmitted title reads today
TITLE_TABLE = {
    "firered": "vanilla", "leafgreen": "vanilla", "firered_ap": "ap", "emerald": "emerald",
    "radical_red": "radical_red",
}


def _load(pack: str) -> dict:
    return json.loads(PROFILES[pack].read_text(encoding="utf-8"))


def _title(name: str) -> dict:
    pack = "gen3_rr" if name == "radical_red" else "gen3_frlg"
    return _load(pack)["titles"][name]


def _flat(title: dict) -> dict:
    """{key: value} across ram/rom/derived -- section placement is checked separately."""
    out = {}
    for section in ("ram", "rom", "derived"):
        for key, val in title[section].items():
            assert key not in out, f"{key} appears in two sections"
            out[key] = val
    return out


# ── the Lua tables, sliced with an independent regex ─────────────────────────────
def _table_text(table: str) -> str:
    text = SRC.read_text(encoding="utf-8")
    if table == "emerald":
        start = re.search(r"^GEN3\.profiles\.emerald = \{", text, re.M).end()
    else:
        start = re.search(r"^    " + table + r" = \{", text, re.M).end()
    depth, i = 1, start
    while depth:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[start:i]


SCALAR = re.compile(r"^\s+([A-Z][A-Z0-9_]*)\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*,", re.M)
SE_ENTRY = re.compile(r"^\s+\[(\d+)\]\s*=\s*(0x[0-9A-Fa-f]+)\s*,", re.M)


def _num(lit: str) -> int:
    return int(lit, 16) if lit[:2].lower() == "0x" else int(lit)


@pytest.mark.parametrize("name", sorted(TITLE_TABLE))
def test_every_scalar_literal_survives_at_the_same_key(name: str) -> None:
    body = _table_text(TITLE_TABLE[name])
    flat = _flat(_title(name))
    found = dict(SCALAR.findall(body))
    assert len(found) >= 15, f"{name}: the slice regex found only {len(found)} literals"
    for key, lit in found.items():
        assert key in flat, f"{name}: {key} is missing from profile.json"
        assert flat[key] == _num(lit), f"{name}: {key} changed value"


@pytest.mark.parametrize("name", ["firered", "leafgreen", "firered_ap", "radical_red"])
def test_se_song_headers_survive(name: str) -> None:
    body = _table_text(TITLE_TABLE[name])
    se_block = body[body.index("SE_SONG_HEADERS"):]
    se_block = se_block[:se_block.index("}")]
    want = {k: _num(v) for k, v in SE_ENTRY.findall(se_block)}
    assert want, f"{name}: no SE_SONG_HEADERS entries sliced"
    assert _title(name)["rom"]["SE_SONG_HEADERS"] == want


def test_cfru_box_bases_are_the_25_computed_lua_expressions() -> None:
    bases = _title("radical_red")["derived"]["CFRU_BOX_BASES"]
    assert len(bases) == 25
    expected = [0x02029318 + 1740 * i for i in range(19)]
    expected += [0x0203CB44 + 1740 * i for i in range(3)]
    expected += [0x02027434 + 1740 * i for i in range(2)]
    expected += [0x02024638]
    assert bases == expected


def test_rr_storage_flags() -> None:
    derived = _title("radical_red")["derived"]
    assert derived["PARTY_IN_SB1"] is False
    assert derived["CFRU_NO_ENCRYPT"] is True


@pytest.mark.parametrize("name", ["firered", "leafgreen"])
def test_vanilla_storage_and_party_facts(name: str) -> None:
    title = _title(name)
    pin = "pret/pokefirered@c75f352304d529f6ba92d4f74b9cf8b5c3810788"
    header = f"{pin}:include/pokemon_storage_system.h"
    path = f"data/gen3/pret/poke{name}.sym"
    lines = (REPO / path).read_text(encoding="utf-8").splitlines()
    storage = [(i, line.split()) for i, line in enumerate(lines, 1)
               if line.split()[-1:] == ["gPokemonStorage"]]
    assert len(storage) == 1
    line, fields = storage[0]
    assert title["ram"]["POKEMON_STORAGE_BASE"] == int(fields[0], 16) == 0x02029314
    # Offset 4 accounts for u32 alignment, despite the header's stale 0x0001 comment.
    expected = {"BOX_DATA_OFFSET": 4, "BOXES_PER_STORE": 14,
                "MONS_PER_BOX": 30, "PARTY_CAPACITY": 6}
    for key, value in expected.items():
        assert title["derived"][key] == value
    base_src = {
        "ram.POKEMON_STORAGE_BASE": f"{path}:{line} (gPokemonStorage; {pin})",
        "derived.BOX_DATA_OFFSET": f"{header}:44-48; "
                                   f"{pin}:include/pokemon.h:105-108 (u32 alignment)",
        "derived.BOXES_PER_STORE": f"{header}:7 (TOTAL_BOXES_COUNT)",
        "derived.MONS_PER_BOX": f"{header}:8-10 (IN_BOX_ROWS * IN_BOX_COLUMNS)",
        "derived.PARTY_CAPACITY": f"{pin}:include/constants/global.h:78 (PARTY_SIZE)",
    }
    # P4 card C4-2a: every additional trainer/location/badges/bag/battle citation this card
    # adds, present for exactly the two vanilla titles and nothing else.
    c4_2a_derived_keys = {
        "EXPERIENCE_TABLE_ENTRY_COUNT", "MAX_LEVEL",
        "SB2_OT_ID_OFFSET", "SB2_NAME_OFFSET", "SB1_LOCATION_MAP_GROUP_OFFSET",
        "SB1_LOCATION_MAP_NUM_OFFSET", "SB1_BADGE_BYTE_OFFSET", "OUTCOME_WON", "OUTCOME_LOST",
        "OUTCOME_DREW", "OUTCOME_RAN", "OUTCOME_CAUGHT", "BATTLE_TYPE_TRAINER_MASK",
        "BATTLE_TYPE_DOUBLE_MASK", "GMAIN_INBATTLE_OFFSET", "GMAIN_INBATTLE_MASK",
        "BATTLE_MOVE_ENTRY_SIZE", "BATTLE_MOVE_PP_OFFSET", "BASESTATS_GROWTH_RATE_OFFSET",
        "SHEDINJA_SPECIES_ID",
    }
    c4_2a_sym_keys = {"ram.TRAINER_OPPONENT_ADDR", "rom.EXPERIENCE_TABLES_ADDR",
                       "rom.BATTLE_MOVES_ADDR", "rom.PP_UP_GET_MASK_ADDR"}
    for key in c4_2a_derived_keys:
        assert f"derived.{key}" in title["_src"], f"{name}: derived.{key} has no _src citation"
        base_src[f"derived.{key}"] = title["_src"][f"derived.{key}"]
    for key in c4_2a_sym_keys:
        assert key in title["_src"], f"{name}: {key} has no _src citation"
        assert path in title["_src"][key], f"{name}: {key} citation does not name its own .sym file"
        base_src[key] = title["_src"][key]
    assert title["_src"] == base_src


def test_rr_party_capacity_comes_from_its_existing_detector() -> None:
    title = _title("radical_red")
    text = SRC.read_text(encoding="utf-8")
    start = text.index("local function _detectRR()")
    match = re.search(r"if partyCount > (\d+) then return false end", text[start:])
    assert match
    line = text.count("\n", 0, start + match.start()) + 1
    assert title["derived"]["PARTY_CAPACITY"] == int(match[1]) == 6
    # The legacy pointer row is documented where it lives: 0x03003840 is the old client's, not
    # the pack's pointer (card C3-33), so a reader cannot mistake it for the new client's source.
    legacy = title["ram"]["SB1_PTR_ADDR"]
    assert legacy == 0x03003840
    hit = re.search(rf"^\s*SB1_PTR_ADDR\s*=\s*0x{legacy:08X}\s*,", text, re.M)
    assert hit, "the radical_red SB1_PTR_ADDR literal is gone from the Lua table"
    legacy_line = text.count("\n", 0, hit.start()) + 1
    base_src = {
        "derived.PARTY_CAPACITY":
            f"lua/games/gen3_frlge.lua:{line} (_detectRR partyCount limit)",
        "ram.SB1_PTR_ADDR":
            f"lua/games/gen3_frlge.lua:{legacy_line} "
            "(the old client's address, kept for parity: it is a literal-pool constant inside "
            "IntrMain_Buffer, not the pointer -- the new client reads "
            "write_checkpoint.pointers.gSaveBlock1Ptr, which is ROM-derived)",
    }
    # P4 card C4-2a addendum 4/5: old-client-evidenced RR facts, every citation naming
    # lua/memory_gba.lua (production-tested), never a pret path (RR has no pret source).
    rr_c4_2a_keys = {
        "SB1_LOCATION_MAP_GROUP_OFFSET", "SB1_LOCATION_MAP_NUM_OFFSET", "SB1_BADGE_BYTE_OFFSET",
        "BATTLE_TYPE_TRAINER_MASK", "BATTLE_TYPE_DOUBLE_MASK", "OUTCOME_WON", "OUTCOME_LOST",
        "OUTCOME_DREW",
    }
    for key in rr_c4_2a_keys:
        cite = title["_src"].get(f"derived.{key}")
        assert cite and "lua/memory_gba.lua" in cite, f"radical_red: derived.{key} needs an old-client citation"
        base_src[f"derived.{key}"] = cite
    # SHEDINJA_SPECIES_ID comes from the RR species table, not the old client.
    shedinja_cite = title["_src"].get("derived.SHEDINJA_SPECIES_ID")
    assert shedinja_cite and "rr_species.json" in shedinja_cite
    base_src["derived.SHEDINJA_SPECIES_ID"] = shedinja_cite
    for section, key in RR_BINARY_VALUES:
        cite = title["_src"].get(f"{section}.{key}")
        assert cite and cite.startswith("rom:patch/build/slink_RR.gba sha1=")
        base_src[f"{section}.{key}"] = cite
    assert title["_src"] == base_src
    assert title["derived"]["SHEDINJA_SPECIES_ID"] == 303
    # values already agree with the pinned pret constants used for FR/LG (never RR-only guesses)
    assert title["derived"]["SB1_LOCATION_MAP_GROUP_OFFSET"] == 0x04
    assert title["derived"]["SB1_BADGE_BYTE_OFFSET"] == 0x104
    assert title["derived"]["OUTCOME_CAUGHT"] == 7 and title["derived"]["OUTCOME_RAN"] == 4
    # values this card could NOT find evidence for stay absent (RR-OPEN, reported to the owner)
    for key in ("SB2_NAME_OFFSET", "GMAIN_INBATTLE_OFFSET", "GMAIN_INBATTLE_MASK"):
        assert key not in title["derived"] and key not in title["ram"] and key not in title["rom"]


RR_BINARY_VALUES = {
    ("derived", "SB2_OT_ID_OFFSET"): 0xA,
    ("rom", "EXPERIENCE_TABLES_ADDR"): 0x0915514C,
    ("derived", "EXPERIENCE_TABLE_ENTRY_COUNT"): 256,
    ("derived", "MAX_LEVEL"): 250,
    ("rom", "BATTLE_MOVES_ADDR"): 0x091521D0,
    ("derived", "BATTLE_MOVE_ENTRY_SIZE"): 12,
    ("derived", "BATTLE_MOVE_PP_OFFSET"): 4,
    ("rom", "PP_UP_GET_MASK_ADDR"): 0x0825DEA1,
    ("derived", "BASESTATS_GROWTH_RATE_OFFSET"): 0x13,
    ("rom", "HANDLE_TURN_ACTION_SELECTION_ADDR"): 0x08014041,
}


def test_rr_rom_pins_are_in_the_generated_profile():
    from tools.gen_gen3_profile import rr_rom_facts

    facts = rr_rom_facts()
    title = _title("radical_red")
    for (section, key), expected in RR_BINARY_VALUES.items():
        assert title[section][key] == facts[section, key][0] == expected
    assert "HANDLE_TURN_ACTION_SELECTION_ADDR" in title["rom_thumb"]
    # Odd-address byte data must not accidentally become a Thumb function pin.
    assert "PP_UP_GET_MASK_ADDR" not in title["rom_thumb"]


@pytest.mark.parametrize("anchor", ["calculate_pp", "box_level", "trainer_id", "pp_up_masks",
                                    "action_callback_store", "action_callback_pool",
                                    "action_callback_entry"])
def test_rr_rom_anchor_mutation_refuses_the_facts(anchor):
    from tools.gen_gen3_profile import RR_ROM_ANCHORS, rr_rom_facts

    end = max(off + len(bytes.fromhex(raw)) for off, raw in RR_ROM_ANCHORS.values())
    image = bytearray(end)
    for offset, raw in RR_ROM_ANCHORS.values():
        image[offset:offset + len(bytes.fromhex(raw))] = bytes.fromhex(raw)
    assert rr_rom_facts(bytes(image))
    image[RR_ROM_ANCHORS[anchor][0]] ^= 1
    with pytest.raises(ValueError, match=f"anchor mismatch: {anchor}"):
        rr_rom_facts(bytes(image))


@pytest.mark.parametrize("path,digest", [
    (REPO / "patch/build/slink_RR.gba", "b7d1e0756fcc66575878affc8f7b95c45386bb1c"),
    (pathlib.Path("E:/Google Drive/SLink/Pokemon - Radical Red.gba"),
     "964f951a0fdaf209e4ea1344883ef0d557bb3a80"),
])
def test_rr_rom_anchors_match_both_admitted_binaries(path, digest):
    from tools.gen_gen3_profile import RR_ROM_ANCHORS, rr_rom_facts

    if not path.exists():
        pytest.skip("local copyrighted RR ROM absent; embedded-anchor MODEL tests still run")
    raw = path.read_bytes()
    assert hashlib.sha1(raw).hexdigest() == digest
    facts = rr_rom_facts(raw)
    for (section, key), value in RR_BINARY_VALUES.items():
        assert facts[section, key][0] == value
    for name, (offset, expected) in RR_ROM_ANCHORS.items():
        assert _title("radical_red")["_rom_anchors"][name] == {
            "rom_offset": offset, "expected_hex": expected.upper(),
        }
    # Independent direct literal readers corroborate the generator's Thumb LDR decoder.
    assert int.from_bytes(raw[0x4105C:0x41060], "little") == 0x091521D0
    assert int.from_bytes(raw[0x3E894:0x3E898], "little") == 0x0915514C
    assert raw[0x25DEA1:0x25DEA5] == bytes([3, 12, 48, 192])
    assert raw[0x11521D0 + 153 * 12 + 4] == 5  # Explosion PP, relocated table


@pytest.mark.parametrize("name", ["firered", "leafgreen"])
def test_frlg_experience_dimensions_are_explicit(name):
    d = _title(name)["derived"]
    assert d["EXPERIENCE_TABLE_ENTRY_COUNT"] == 101
    assert d["MAX_LEVEL"] == 100


@pytest.mark.parametrize("name,symbol,section,key", [
    ("firered", "gTrainerBattleOpponent_A", "ram", "TRAINER_OPPONENT_ADDR"),
    ("leafgreen", "gTrainerBattleOpponent_A", "ram", "TRAINER_OPPONENT_ADDR"),
    ("firered", "gExperienceTables", "rom", "EXPERIENCE_TABLES_ADDR"),
    ("leafgreen", "gExperienceTables", "rom", "EXPERIENCE_TABLES_ADDR"),
    ("firered", "gBattleMoves", "rom", "BATTLE_MOVES_ADDR"),
    ("leafgreen", "gBattleMoves", "rom", "BATTLE_MOVES_ADDR"),
    ("firered", "gPPUpGetMask", "rom", "PP_UP_GET_MASK_ADDR"),
    ("leafgreen", "gPPUpGetMask", "rom", "PP_UP_GET_MASK_ADDR"),
])
def test_p4_c4_2a_sym_addresses_match_the_titles_own_sym_file(name, symbol, section, key) -> None:
    """P4 card C4-2a: independently re-derives each new address straight from the title's own
    .sym file (never trusts the generator's own regex)."""
    path = f"data/gen3/pret/poke{name}.sym"
    text = (REPO / path).read_text(encoding="utf-8")
    matches = re.findall(rf"^([0-9a-fA-F]{{8}})\s+g\s+[0-9a-fA-F]+\s+{symbol}$", text, re.M)
    assert len(matches) == 1, f"{path}: expected exactly one {symbol}"
    assert _title(name)[section][key] == int(matches[0], 16)


def test_p4_c4_2a_engine_constants_match_the_pinned_pret_header() -> None:
    """The battle/flags/pokemon constants this card added, re-derived from the pinned pret
    header independent of the generator's own copies."""
    _pin_dir = pathlib.Path("E:/Google Drive/SLink/.cache/pret/pokefirered")
    pin_dir = _pin_dir if _pin_dir.exists() else None
    if pin_dir is None:
        pytest.skip("no local pret checkout to re-derive against (values are still pinned in "
                    "tools/gen_gen3_profile.py:FRLG_DERIVED with a file:line citation each)")
    battle_h = (pin_dir / "include" / "constants" / "battle.h").read_text(encoding="utf-8")
    flags_h = (pin_dir / "include" / "constants" / "flags.h").read_text(encoding="utf-8")
    pokemon_h = (pin_dir / "include" / "pokemon.h").read_text(encoding="utf-8")
    for name in ("firered", "leafgreen"):
        derived = _title(name)["derived"]
        for const, key in (("B_OUTCOME_WON", "OUTCOME_WON"), ("B_OUTCOME_LOST", "OUTCOME_LOST"),
                           ("B_OUTCOME_DREW", "OUTCOME_DREW"), ("B_OUTCOME_RAN", "OUTCOME_RAN"),
                           ("B_OUTCOME_CAUGHT", "OUTCOME_CAUGHT"),
                           ("BATTLE_TYPE_TRAINER", "BATTLE_TYPE_TRAINER_MASK"),
                           ("BATTLE_TYPE_DOUBLE", "BATTLE_TYPE_DOUBLE_MASK")):
            m = re.search(rf"^#define {const}\s+\(?(0x[0-9A-Fa-f]+|\d+)(\s*<<\s*(\d+))?", battle_h, re.M)
            assert m, const
            want = _num(m[1]) << int(m[3]) if m[3] else _num(m[1])
            assert derived[key] == want
        assert derived["SB1_BADGE_BYTE_OFFSET"] == 0x104
        # SYS_FLAGS itself is a chained macro (TRAINER_FLAGS_END + 1); its pinned value 0x800
        # is cross-checked by tests/unit/test_gen3_reads.py's live badge-byte reads instead of
        # re-expanded here. This only re-derives the FLAG_BADGE01_GET offset from it.
        assert re.search(r"^#define SYS_FLAGS \(TRAINER_FLAGS_END \+ 1\)", flags_h, re.M)
        badge01 = _num(re.search(r"^#define FLAG_BADGE01_GET\s+\(SYS_FLAGS \+ (0x[0-9A-Fa-f]+)\)",
                                  flags_h, re.M)[1])
        assert (0x800 + badge01) >> 3 == derived["SB1_BADGE_BYTE_OFFSET"]
        growth_off = re.search(r"/\* 0x13 \*/ u8 growthRate;", pokemon_h)
        assert growth_off, "growthRate moved in pokemon.h"
        assert derived["BASESTATS_GROWTH_RATE_OFFSET"] == 0x13


@pytest.mark.parametrize("name", ["firered_ap", "emerald"])
def test_pret_additions_do_not_admit_unverified_titles(name: str) -> None:
    title = _title(name)
    assert "_src" not in title
    assert "BOX_DATA_OFFSET" not in title["derived"]
    assert "PARTY_CAPACITY" not in title["derived"]


def test_thumb_addresses_are_kept_verbatim_and_marked() -> None:
    rr = _title("radical_red")
    assert rr["rom"]["CB2_EVOLUTION_LOAD_ADDR"] == 0x080CE0E9  # odd: the Thumb bit stays
    assert "CB2_EVOLUTION_LOAD_ADDR" in rr["rom_thumb"]
    assert "BASESTATS_ENTRY_SIZE" not in rr["rom_thumb"]
    for name in TITLE_TABLE:
        title = _title(name)
        for key in title["rom_thumb"]:
            vals = title["rom"][key]
            for val in (vals if isinstance(vals, list) else [vals]):
                assert val & 1, f"{name}: {key} is in rom_thumb but is even"


def test_pinned_rom_hashes() -> None:
    assert _title("firered")["rom_sha1"] == "41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc"
    assert _title("leafgreen")["rom_sha1"] == "574fa542ffebb14be69902d1d36f1ec0a4afd71e"
    rr = _title("radical_red")
    assert rr["rom_sha1"] == "964f951a0fdaf209e4ea1344883ef0d557bb3a80"
    assert rr["rom_md5"] == "8529f3a45d32bce4da637976fcf269d4"
    # LeafGreen reads the vanilla table today; divergence is UNVERIFIED (P2 card C2-3)
    assert _title("leafgreen")["ram"] == _title("firered")["ram"]


def test_admission_flags_and_source_block() -> None:
    frlg = _load("gen3_frlg")
    assert [t for t, v in frlg["titles"].items() if v["admitted"]] == ["firered", "leafgreen"]
    assert frlg["titles"]["firered_ap"]["admitted"] is False
    assert frlg["titles"]["emerald"]["admitted"] is False
    assert _load("gen3_rr")["titles"]["radical_red"]["admitted"] is True
    for pack, data in ((p, _load(p)) for p in PROFILES):
        assert data["source"]["file"] == "lua/games/gen3_frlge.lua"
        assert re.fullmatch(r"[0-9a-f]{40}|unknown", data["source"]["git_head"]), pack


# ── the native (companion) block ─────────────────────────────────────────────────
def test_native_is_present_only_in_gen3_rr() -> None:
    assert "native" not in _load("gen3_frlg")
    assert "native" in _load("gen3_rr")


def test_native_matches_the_mailbox_and_ghost_sources() -> None:
    native = dict(_load("gen3_rr")["native"])
    src = native.pop("_src")
    mailbox = (REPO / "lua" / "mailbox.lua").read_text(encoding="utf-8")
    want = {m.group(1): _num(m.group(2)) for m in
            re.finditer(r"^MB\.([A-Z][A-Z0-9_]*)\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*(?:--.*)?$",
                        mailbox, re.M)}
    ghost = (REPO / "lua" / "peer_ghost_npc.lua").read_text(encoding="utf-8")
    want["OBJECT_EVENTS_BASE"] = int(re.search(r"^local OE = (0x[0-9A-Fa-f]+)", ghost, re.M)[1], 16)
    cb2 = re.search(r"memory\.read_u32_le\((0x[0-9A-Fa-f]+)\) ~= (0x[0-9A-Fa-f]+)", ghost)
    want["GMAIN_CB2_PTR"], want["CB2_OVERWORLD"] = int(cb2[1], 16), int(cb2[2], 16)
    want["SPRITES_BASE"] = int(
        re.search(r"read_u32_le\((0x[0-9A-Fa-f]+) \+ lsid\*0x44", ghost)[1], 16)
    want["OBJ_PALETTE_BUF"] = int(
        re.search(r"read_u16_le\((0x[0-9A-Fa-f]+) \+ lslot\*0x20", ghost)[1], 16)
    want["CAMERA_Y_ADDR"] = int(
        re.search(r"read_s16_le\((0x[0-9A-Fa-f]+)\) \+ 8", ghost)[1], 16)
    assert native == want
    # the ABI anchors the card names, spelled out so a silent regex drift is caught
    assert native["BASE"] == 0x0203F800 and native["BLOB_BUF"] == 0x0203FA00
    assert native["TEXT_BUF"] == 0x0203F900 and native["MENU_BUF"] == 0x0203FC90
    assert native["BATTLE_NOTIF"] == 0x0203FD00 and native["EVR"] == 0x0203FD10
    assert native["PI_COUNT"] == 0x0203F8D3 and native["TN_ENABLE"] == 0x0203F8D4
    assert native["CALC_OFF"] == 0x0203F8D8 and native["INFO"] == 0x0203FD44
    assert native["GH"] == 0x0203F850 and native["SW"] == 0x0203F840
    assert native["OBJECT_EVENTS_BASE"] == 0x02036E38
    assert set(src) == set(native)
    for name, where in src.items():
        path, line = where.rsplit(":", 1)
        assert path in ("lua/mailbox.lua", "lua/peer_ghost_npc.lua")
        text = (REPO / path).read_text(encoding="utf-8").splitlines()[int(line) - 1]
        assert re.search(r"0x[0-9A-Fa-f]+|= *\d", text), f"{name}: {where} has no literal"


# ── the P2 exit condition + file hygiene ─────────────────────────────────────────
def test_check_mode_passes_on_the_committed_profiles() -> None:
    run = subprocess.run([sys.executable, "tools/gen_gen3_profile.py", "--check"],
                         cwd=REPO, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize("pack", sorted(PROFILES))
def test_json_is_deterministic(pack: str) -> None:
    raw = PROFILES[pack].read_bytes()
    assert b"\r\n" not in raw, f"{pack}: CRLF line endings"
    text = raw.decode("utf-8")
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"
