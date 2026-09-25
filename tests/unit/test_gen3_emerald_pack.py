"""gen3_emerald pack (E1-PACK): SOURCE pins plus HEADER / literal-pool / stub controls.

None of this is an emulator receipt. The ROM-backed tests skip when the owner's BPEE is absent.
"""
import hashlib
import json
import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "data/games/gen3_emerald"
ROM = Path("E:/Google Drive/SLink/Pokemon - Emerald Version (USA, Europe).gba")
ROM_SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"
PRET = Path("E:/Google Drive/SLink/.cache/pret/pokeemerald")
# the 21 FR site kinds (data/games/gen3_frlg/engine_signals.json firered clean)
KINDS = {"frame_control", "battle_begin", "battle_end", "faint", "capture_wild", "mon_given",
         "pc_move", "whiteout", "map_load", "evolve_species_store", "trade_evolve_species_store",
         "trade_begin", "trade_done", "save", "poison_hp_before", "poison_faint", "pc_deposit",
         "pc_withdraw", "pc_box_place", "pc_release_begin", "pc_release"}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def emerald() -> dict:
    return _json(PACK / "profile.json")["titles"]["emerald"]


@pytest.fixture(scope="module")
def rom() -> bytes:
    if not ROM.is_file():
        pytest.skip(f"ROM not present at {ROM}")
    data = ROM.read_bytes()
    assert hashlib.sha1(data).hexdigest() == ROM_SHA1
    return data


def test_profile_has_the_firered_key_set_and_provenance(emerald):
    firered = _json(ROOT / "data/games/gen3_frlg/profile.json")["titles"]["firered"]
    for section in ("ram", "rom", "derived"):
        assert set(emerald[section]) == set(firered[section]), section
        for key in emerald[section]:
            field = f"{section}.{key}"  # SE_SONG_HEADERS cites per id: rom.SE_SONG_HEADERS.<id>
            assert any(s == field or s.startswith(field + ".") for s in emerald["_src"]), field
    assert emerald["rom_thumb"] == firered["rom_thumb"]
    assert (emerald["admitted"], emerald["variant"], emerald["rom_sha1"]) == (False, "emerald", ROM_SHA1)


def test_profile_regenerates_byte_identical():
    from tools import gen_gen3_profile as gen

    assert gen.render(gen.build_emerald()) == (PACK / "profile.json").read_text(encoding="utf-8")


def test_profile_agrees_with_every_value_the_old_stub_carries(emerald):
    """The frlg pack's unadmitted `emerald` stub is an independent second source (never copied)."""
    stub = _json(ROOT / "data/games/gen3_frlg/profile.json")["titles"]["emerald"]
    checked = 0
    for section in ("ram", "rom", "derived"):
        for key, value in stub[section].items():
            if value is None or value == {}:
                continue  # the stub left it blank; nothing to agree with
            assert emerald[section][key] == value, (section, key)
            checked += 1
    assert checked == 15 + 1 + 8  # 15 RAM, BASESTATS_ADDR, 8 derived


def test_gf_header_control(rom, emerald):
    """pret src/rom_header_gf.c:18-94 at 0x08000100: the ROM's own save-layout API."""
    head = rom[0x100:0x204]

    def u32(off: int) -> int:
        return struct.unpack_from("<I", head, off)[0]

    # known-positive control: this really is the GF header of pokemon emerald
    assert (u32(0x00), head[0x08:0x1F]) == (3, b"pokemon emerald version")
    d, r = emerald["derived"], emerald["rom"]
    assert u32(0x50) == d["SB1_FLAGS_OFFSET"] == 0x1270    # flagsOffset
    assert u32(0x54) == d["SB1_VARS_OFFSET"] == 0x139C     # varsOffset
    assert (u32(0x88), u32(0x8C)) == (0xF2C, 0x3D88)       # saveBlock2Size, saveBlock1Size
    assert u32(0x9C) == d["SB2_OT_ID_OFFSET"]              # trainerIdOffset
    assert u32(0xA0) == d["SB2_NAME_OFFSET"]               # playerNameOffset
    assert u32(0xBC) == r["BASESTATS_ADDR"]                # speciesInfo
    assert u32(0xCC) == r["BATTLE_MOVES_ADDR"]             # moves
    assert head[0xE6] == d["SB1_BALL_POCKET_COUNT"]        # bagCountPokeballs


def test_battle_type_literal_pool_control(rom, emerald):
    addr = emerald["ram"]["BATTLE_TYPE_ADDR"]
    assert addr == 0x02022FEC
    assert rom.count(struct.pack("<I", addr)) == 457
    # the probe's negative control: one page up is never referenced
    assert rom.count(struct.pack("<I", addr + 0x1000)) == 0


def test_every_site_is_at_its_rom_offset_inside_its_function(rom):
    document = _json(PACK / "engine_signals.json")
    assert (document["pack"], document["live_verified"]) == ("gen3_emerald", False)
    artifact = document["titles"]["emerald"]["artifacts"]["clean"]
    assert artifact["rom_sha1"] == ROM_SHA1
    assert set(artifact["sites"]) == KINDS
    for kind, site in artifact["sites"].items():
        data = bytes.fromhex(site["expected_hex"])
        assert 8 <= len(data) <= 16, kind
        assert rom[site["rom_offset"]:site["rom_offset"] + len(data)] == data, kind
        assert rom.count(data) == 1, kind
        assert site["address"] == 0x08000000 + site["rom_offset"], kind
        assert site["address"] % 2 == site["capture_offset"] % 2 == 0, kind
        assert site["mode"] == "thumb" and site["point"], kind
        fn = site["function"]
        hook = site["address"] + site["capture_offset"]
        assert fn["address"] + fn["capture_offset"] == hook, kind
        assert fn["address"] <= hook < fn["address"] + fn["size"], kind
        ctx = site["context"]
        assert ctx["rom_offset"] == fn["address"] - 0x08000000, kind
        assert rom[ctx["rom_offset"]:ctx["rom_offset"] + len(ctx["expected_hex"]) // 2].hex().upper() \
            == ctx["expected_hex"], kind
    assert "UNVERIFIED" not in json.dumps(document)


def test_engine_signals_regenerate_byte_identical(rom):
    from tools import gen_gen3_engine_signals as gen

    pack, inventory = gen.build_emerald(rom)
    assert json.dumps(pack, indent=2, sort_keys=True) + "\n" == \
        (PACK / "engine_signals.json").read_text(encoding="utf-8")
    assert gen.document_emerald(inventory) == gen.EMERALD_DOC.read_text(encoding="utf-8")


def test_resolver_refuses_a_corrupted_entry(rom):
    from tools import gen_gen3_engine_signals as gen

    function, *_ = gen.EMERALD_BINDINGS["faint"]
    at = gen.emerald_symbols()[0][function]["address"] - 0x08000000
    bad = rom[:at] + bytes([rom[at] ^ 0xFF]) + rom[at + 1:]
    assert gen.emerald_resolve("faint", bad)["status"] == "UNVERIFIED"
    assert gen.emerald_resolve("faint", rom)["status"] == "PINNED"


def test_pret_citations_carry_their_identifier(emerald):
    """Every `pret/pokeemerald@<sha>:path:lines (ident` in _src names lines that contain ident."""
    if not PRET.is_dir():
        pytest.skip(f"pret checkout not present at {PRET}")
    cite = re.compile(r"pret/pokeemerald@[0-9a-f]{40}:([\w/.]+):(\d+)(?:-(\d+))? \(([^;)]+)")
    checked = 0
    for key, where in emerald["_src"].items():
        for path, lo, hi, ident in cite.findall(where):
            lines = (PRET / path).read_text(encoding="utf-8").splitlines()[int(lo) - 1:int(hi or lo)]
            assert ident.split("|")[0] in "\n".join(lines), (key, path, lo, ident)
            checked += 1
    assert checked >= 50
