"""Gen 4 names tool -- CARD gen4-G2-names.

tools/gen_gen4_names.py writes data/games/gen4_{hgss,hge}/names.json from the pinned ROMs (msg NARC a/0/2/7).
Tests that need a ROM or source clone skip BY NAME when it is absent and FAIL when it is present but wrong
(absent skips, wrong fails). Revert-tested controls: test_check_goes_red_on_one_edited_name (edit one name),
test_wrong_rom_hash_refuses (any file that is not the pinned ROM), test_plus50_property (hge id shift).
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen_gen4_names as g  # noqa: E402

DATA = ROOT / "data" / "games"


def committed(mode: str) -> dict:
    return json.loads((DATA / f"gen4_{mode}" / "names.json").read_text(encoding="utf-8"))


def fresh(mode: str) -> tuple[dict, Path]:
    """Regenerate from the real ROM + clone; skip by name if absent, fail if wrong."""
    try:
        rom, sha1 = g.locate_rom(mode, None)
        src, commit = g.locate_src(mode, None)
    except g.Absent as exc:
        pytest.skip(str(exc))
    except g.Mismatch as exc:
        pytest.fail(str(exc))
    return json.loads(g.build(mode, rom, sha1, src, commit)), rom


@pytest.fixture(scope="module")
def hgss():
    return fresh("hgss")[0]


@pytest.fixture(scope="module")
def hge():
    return fresh("hge")[0]


# ── ROM-free: codec + derivations on synthetic input ─────────────────────────────────────────────


def encode_msg(strings: list[str], charmap: dict[int, str], seed: int = 0x1234) -> bytes:
    rev = {v: k for k, v in charmap.items()}
    n = len(strings)
    table, body, off = [], b"", 4 + 8 * n
    for i, s in enumerate(strings):
        codes = [rev[c] for c in s] + [0xFFFF]
        key = ((i + 1) * 0x91BD3) & 0xFFFF
        enc = b""
        for c in codes:
            enc += struct.pack("<H", c ^ key)
            key = (key + 0x493D) & 0xFFFF
        k = (seed * 0x2FD * (i + 1)) & 0xFFFF
        k32 = k | (k << 16)
        table.append(struct.pack("<II", off ^ k32, len(codes) ^ k32))
        body += enc
        off += len(enc)
    return struct.pack("<HH", n, seed) + b"".join(table) + body


def test_codec_roundtrip():
    cm = {0: "\\x0000", 0x12: "A", 0x13: "B", 0x14: " "}
    msgs = ["AB", "", "B A", "ABBA"]
    assert g.decode_msg(encode_msg(msgs, cm), cm) == msgs


def test_codec_rejects_unmapped_char():
    with pytest.raises(ValueError, match="not in charmap"):
        g.decode_msg(encode_msg(["AB"], {0x12: "A", 0x13: "B"}), {0x12: "A"})


def test_dex_derivation_and_form_chain():
    h = "\n".join(
        [
            "#define SPECIES_NONE 0",
            "#define SPECIES_A 1",
            "#define SPECIES_B 2",
            "#define SPECIES_EGG 3",
            "#define SPECIES_BAD_EGG 4",
            "#define SPECIES_5 5  // filler",
            "#define SPECIES_C (SPECIES_B + 4)",
            "#define MAX_CANONICAL_MON_NUM (SPECIES_C)",
            "#define SPECIES_MEGA_START (MAX_CANONICAL_MON_NUM + 1)",
            "#define SPECIES_MEGA_A (SPECIES_MEGA_START)",
            "#define SPECIES_GMAX_MEGA_A (SPECIES_MEGA_START + 1)",
        ]
    )
    dex, defs = g.dex_table(h, "SPECIES_C")
    assert dex == {1: 1, 2: 2, 6: 3}  # Egg/Bad Egg/numeric filler take no dex slot
    m = "[SPECIES_MEGA_A - SPECIES_MEGA_START] = SPECIES_A,\n    [SPECIES_GMAX_MEGA_A - SPECIES_MEGA_START] = SPECIES_MEGA_A,"
    assert g.form_bases(m, defs) == {7: 1, 8: 7}


# ── ROM-free: refusals ───────────────────────────────────────────────────────────────────────────


def test_wrong_rom_hash_refuses(tmp_path, capsys):
    bogus = tmp_path / "not_a_rom.nds"
    bogus.write_bytes(b"\0" * 64)
    assert g.main(["hgss", "--rom", str(bogus)]) == 1
    assert "pinned" in capsys.readouterr().err


def test_absent_rom_is_open(tmp_path, capsys):
    assert g.main(["hge", "--rom", str(tmp_path / "nope.nds")]) == 2
    assert "OPEN" in capsys.readouterr().err


# ── committed JSON only ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["hgss", "hge"])
def test_committed_shape(mode):
    d = committed(mode)
    assert d["_schema"] == g.SCHEMA
    assert d["rom_sha1"] == g.gen4_pins.ROM_SPECS["heartgold" if mode == "hgss" else "heartgold_hge"][0]
    assert set(d) >= {"species", "moves", "items", "abilities", "natures", "source", "rom_sha1"}
    assert len(d["natures"]) == 25


def test_plus50_property():
    """hge canonical species 544..1075 are dex 494..1025 (id = dex + 50); 1..493 are identity; forms point at a base."""
    sp = committed("hge")["species"]
    assert sp["544"] == {"name": "Victini", "dex": 494}
    assert sp["1075"] == {"name": "Pecharunt", "dex": 1025}
    assert all(sp[str(i)]["dex"] == i for i in range(1, 494))
    assert all(sp[str(i)]["dex"] == i - 50 for i in range(544, 1076))
    assert all(sp[str(i)]["dex"] is None for i in (0, 494, 495, *range(496, 544)))
    forms = {int(k): v for k, v in sp.items() if int(k) > 1075 and "base" in v}
    assert forms and all(1 <= v["base"] <= 1075 and v["dex"] == sp[str(v["base"])]["dex"] for v in forms.values())
    assert sp["1076"]["base"] == 3  # Mega Venusaur -> Venusaur


def test_case_preserved_as_stored():
    assert committed("hgss")["species"]["1"]["name"] == "BULBASAUR"
    assert committed("hge")["species"]["1"]["name"] == "Bulbasaur"
    assert committed("hgss")["species"]["494"]["name"] == "Egg"


# ── real ROM (skip by name when absent) ──────────────────────────────────────────────────────────


def test_hgss_names(hgss):
    sp = hgss["species"]
    assert sp["1"] == {"name": "BULBASAUR", "dex": 1}
    assert sp["493"] == {"name": "ARCEUS", "dex": 493}
    assert sp["494"] == {"name": "Egg", "dex": None, "placeholder": True}
    assert hgss["moves"]["467"] == "Shadow Force"
    assert hgss["items"]["1"] == "Master Ball"
    assert hgss["abilities"]["1"] == "Stench"
    assert hgss["natures"]["3"] == "Adamant"
    assert (len(sp), len(hgss["moves"]), len(hgss["items"])) == (496, 468, 537)
    assert hgss == committed("hgss")


def test_hge_names(hge):
    sp = hge["species"]
    assert sp["544"] == {"name": "Victini", "dex": 494}
    assert sp["1075"] == {"name": "Pecharunt", "dex": 1025}
    assert hge["moves"]["467"] == "Shadow Force"
    assert hge["moves"]["471"] == "Hone Claws"  # 3-id gap above 467
    assert hge["items"]["113"] == "Tea"  # a vanilla "???" slot hge fills
    assert (len(sp), len(hge["moves"]), len(hge["items"])) == (1476, 923, 2685)
    assert sum(1 for v in sp.values() if v["dex"] is not None) == 1025 + sum(1 for v in sp.values() if "base" in v)
    assert hge == committed("hge")


@pytest.mark.parametrize("mode", ["hgss", "hge"])
def test_check_ok_then_red_on_one_edited_name(mode, tmp_path):
    """--check is green on the real output, and red after editing a single name (the revert test)."""
    doc, _rom = fresh(mode)
    out = tmp_path / f"gen4_{mode}"
    out.mkdir()
    target = out / "names.json"
    text = (DATA / f"gen4_{mode}" / "names.json").read_text(encoding="utf-8")
    target.write_bytes(text.replace("\n", "\r\n").encode())  # CRLF checkout must still pass
    assert g.main([mode, "--check", "--out-dir", str(out)]) == 0
    assert doc["moves"]["467"] in text
    target.write_text(text.replace('"Shadow Force"', '"Shadow Farce"', 1), encoding="utf-8", newline="\n")
    assert g.main([mode, "--check", "--out-dir", str(out)]) == 1


# ── G2 review fixes (OMP cx-e1b48fc8): form-chain guard, placeholders, unnamed forms ─────────────


def test_form_chain_guard_raises_a_named_error_on_a_cycle_or_missing_root():
    """Revert: restore the bare `while root not in dex: root = bases[root]` -> the cycle never ends, the
    missing root is a KeyError instead of FormChainError."""
    dex = {1: 1, 2: 2}
    assert g.canonical_root(10, {10: 1}, dex) == 1
    assert g.canonical_root(11, {11: 10, 10: 2}, dex) == 2  # a form that maps to another form
    with pytest.raises(g.FormChainError, match="cyclic"):
        g.canonical_root(10, {10: 11, 11: 12, 12: 10}, dex)
    with pytest.raises(g.FormChainError, match="cyclic"):
        g.canonical_root(10, {10: 10}, dex)
    with pytest.raises(g.FormChainError, match="ends at 99"):
        g.canonical_root(10, {10: 99}, dex)


def test_placeholder_ids_are_marked_and_forms_keep_the_raw_name():
    sp = committed("hge")["species"]
    placeholders = sorted(int(k) for k, v in sp.items() if v.get("placeholder"))
    assert placeholders == [0, *range(494, 544), 1314, 1315] and len(placeholders) == 53
    assert all(v["dex"] is None and "base" not in v for k, v in sp.items() if v.get("placeholder"))
    assert sp["494"]["name"] == "Egg" and sp["0"]["name"] == "-----"
    unnamed = {k: v for k, v in sp.items() if "raw_name" in v}
    assert len(unnamed) == 398 and all(v["raw_name"] == "-----" and "base" in v for v in unnamed.values())
    assert sp["1076"] == {"name": "Venusaur (form 1076)", "raw_name": "-----", "dex": 3, "base": 3}
    assert not any(v["name"] == "-----" and "base" in v for v in sp.values()), "an unnamed form kept the dash name"
    assert [k for k, v in sp.items() if v["name"] == "-----"] == [str(i) for i in (0, *range(496, 544), 1314, 1315)]
    hgss = committed("hgss")["species"]
    assert sorted(int(k) for k, v in hgss.items() if v.get("placeholder")) == [0, 494, 495]


def test_unnamed_form_fallback_is_applied_by_the_generator(hge):
    """The committed-JSON test above cannot see a generator revert; this one regenerates (skips without the ROM)."""
    sp = hge["species"]
    assert sp["1076"]["name"] == "Venusaur (form 1076)" and sp["1076"]["raw_name"] == "-----"
    assert sum(1 for v in sp.values() if v.get("placeholder")) == 53
