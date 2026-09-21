"""The Gen 3 packs' profile.json preserves Lua literals and pinned pret additions.

The generator is the only thing allowed to type a Gen 3 address, so every assertion here
re-derives the expected value from the Lua sources with its own regexes (no Lua runtime,
and no reuse of the generator's parser for the value checks).
"""
from __future__ import annotations

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
    assert title["_src"] == {
        "ram.POKEMON_STORAGE_BASE": f"{path}:{line} (gPokemonStorage; {pin})",
        "derived.BOX_DATA_OFFSET": f"{header}:44-48; "
                                   f"{pin}:include/pokemon.h:105-108 (u32 alignment)",
        "derived.BOXES_PER_STORE": f"{header}:7 (TOTAL_BOXES_COUNT)",
        "derived.MONS_PER_BOX": f"{header}:8-10 (IN_BOX_ROWS * IN_BOX_COLUMNS)",
        "derived.PARTY_CAPACITY": f"{pin}:include/constants/global.h:78 (PARTY_SIZE)",
    }


def test_rr_party_capacity_comes_from_its_existing_detector() -> None:
    title = _title("radical_red")
    text = SRC.read_text(encoding="utf-8")
    start = text.index("local function _detectRR()")
    match = re.search(r"if partyCount > (\d+) then return false end", text[start:])
    assert match
    line = text.count("\n", 0, start + match.start()) + 1
    assert title["derived"]["PARTY_CAPACITY"] == int(match[1]) == 6
    assert title["_src"] == {
        "derived.PARTY_CAPACITY":
            f"lua/games/gen3_frlge.lua:{line} (_detectRR partyCount limit)",
    }


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
