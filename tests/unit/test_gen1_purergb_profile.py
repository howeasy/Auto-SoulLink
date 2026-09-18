"""pureRGB pack (PLAN §6 M1): the profile, write checkpoint and admission table are what the pinned
build says.

Symbol/lock checks run everywhere; anything that needs the pinned source or the built ROMs
(regeneration, ROM byte slices) skips unless SLINK_PURERGB_SRC points at the locked checkout.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import gen1_foundation as F  # noqa: E402
import gen_gen1_admission_profiles as gen_admission  # noqa: E402
import gen_gen1_profile as gen  # noqa: E402
import gen_gen1_write_checkpoint as gen_wc  # noqa: E402

DATA = REPO / "data" / "games" / "gen1_purergb"
TITLES = ("purered", "pureblue", "puregreen")
LOCK = json.loads((REPO / "data" / "purergb_sources.lock.json").read_text(encoding="utf-8"))


def _json(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def _rom(title: str) -> bytes:
    try:
        return F.rom_path("purergb", title).read_bytes()
    except SystemExit as e:
        pytest.skip(f"pureRGB build not available: {e}")


PROFILE = _json("profile")


def test_profile_lists_the_pure_titles_from_the_lock():
    assert PROFILE["schema"] == "gen1-profile-v1"
    assert set(PROFILE["titles"]) == set(TITLES)
    for title, t in PROFILE["titles"].items():
        assert t["repo"] == "purergb"
        rom_key = pathlib.Path(F.foundation("purergb")["titles"][title][1]).stem
        assert t["rom_sha1"] == LOCK["outputs"][rom_key]["sha1"], title
    for sym_name, src in PROFILE["source"].items():
        assert src["commit"] == LOCK["source"]["commit"]
        assert hashlib.sha256((REPO / "data" / "purergb" / sym_name).read_bytes()).hexdigest() == src["sha256"]


def test_every_symbol_including_the_pure_extras_is_present():
    want = set(gen.RAM_SYMBOLS) | set(gen.EXTRA_RAM_SYMBOLS["purergb"])
    for title, t in PROFILE["titles"].items():
        assert set(t["ram"]) == want, title
        assert set(gen.ROM_SYMBOLS) <= set(t["rom"]), title
        assert "MewBaseStats" not in t["rom"] and "SuperRodFishingSlots" not in t["rom"]  # absent in pureRGB
        assert "SuperRodData" in t["rom"]
    # one RAM layout for all three titles (PLAN §11.2 A9)
    assert PROFILE["titles"]["purered"]["ram"] == PROFILE["titles"]["pureblue"]["ram"] == \
        PROFILE["titles"]["puregreen"]["ram"]


def test_geometry_and_pure_constants():
    for title, t in PROFILE["titles"].items():
        d = t["derived"]
        assert {k: d[k] for k in ("party_struct_size", "box_struct_size", "party_capacity", "box_capacity",
                                  "name_length", "sram_box_stride", "sram_boxes_per_bank", "sram_box_banks")} == {
            "party_struct_size": 44, "box_struct_size": 33, "party_capacity": 6, "box_capacity": 20,
            "name_length": 11, "sram_box_stride": 1122, "sram_boxes_per_bank": 6, "sram_box_banks": [2, 3]}, title
        assert d["ball_items"] == [1, 2, 3, 4, 5, 8]
        assert d["opp_id_offset"] == 197 and d["rival_trainer_ids"] == [221, 237, 238]
        assert d["bag_capacity"] == 30 == (t["ram"]["wPocketAbraNick"] - t["ram"]["wBagItems"] - 1) // 2
        assert d["base_stats_stride"] == 35 and d["dex_count"] == 152 and d["species_count"] == 190
        assert d["wram_bank_gate"] is True and d["hardware"] == "cgb"


def test_design_critical_anchors_in_the_profiles_own_words():
    rom = PROFILE["titles"]["purered"]["rom"]
    for name, bank, addr in (("DelayFrame", 0x00, 0x1E76), ("DelayFrame.halt", 0x00, 0x1E8D),
                             ("OverworldLoop", 0x00, 0x03D6), ("MainInBattleLoop", 0x0F, 0x424D),
                             ("InitWildBattle", 0x0F, 0x6F37), ("RemoveFaintedPlayerMon", 0x0F, 0x47CD),
                             ("EndOfBattle", 0x3A, 0x44FD), ("SaveMenu.save", 0x1C, 0x77CE),
                             ("InGameTrade_DoTrade", 0x1C, 0x54CC)):
        assert (rom[name]["bank"], rom[name]["addr"]) == (bank, addr), name
    names = ("DelayFrame", "DelayFrame.halt", "OverworldLoop", "MainInBattleLoop", "InitWildBattle",
             "RemoveFaintedPlayerMon", "EndOfBattle", "SaveMenu.save", "InGameTrade_DoTrade")
    for title in TITLES:  # the anchors above are shared; bank 1 / bank $1D symbols drift a byte per title
        assert {k: PROFILE["titles"][title]["rom"][k] for k in names} == {k: rom[k] for k in names}, title


def test_profile_regenerates_byte_identically():
    try:
        F.source_root("purergb")
    except SystemExit as e:
        pytest.skip(str(e))
    assert (DATA / "profile.json").read_text(encoding="utf-8") == gen.render(gen.build("purergb"))


# --- write checkpoint --------------------------------------------------------------------------

def test_checkpoint_predicates_follow_the_profile():
    wc = _json("write_checkpoint")
    assert set(wc) == set(TITLES)
    for title, t in wc.items():
        p = PROFILE["titles"][title]
        ws = t["write_safe"]
        assert ws["version"] == gen_wc.VERSION
        assert t["BATTLE_FLAG_ADDR"] == p["ram"]["wIsInBattle"]
        assert t["FONT_LOADED_ADDR"] == p["ram"]["wFontLoaded"]
        assert t["JOY_IGNORE_ADDR"] == p["ram"]["wJoyIgnore"]
        assert ws["delay_frame"] == p["rom"]["DelayFrame"]["addr"]
        assert ws["delay_frame_halt"] == p["rom"]["DelayFrame.halt"]["addr"] == ws["delay_frame"] + 23
        assert ws["delay_frame_resume"] == ws["delay_frame"] + 24  # [SP] at the VBlank IRQ
        assert ws["overworld_loop"] == p["rom"]["OverworldLoop"]["addr"]
        assert ws["overworld_return"] == ws["overworld_loop"] + 1 == ws["overworld_loop_less_delay"]  # [SP+2]
        assert ws["delay_frame_bank"] == p["ram"]["wDelayFrameBank"]
        assert ws["link_state"] == p["ram"]["wLinkState"] and ws["link_none"] == 0
        assert ws["serial_status"] == p["ram"]["hSerialConnectionStatus"] and ws["disconnected_serial"] == 0xFF
        assert ws["irq_vector"] == 0x0040 and ws["wram_banks"] == [0, 1] and ws["wram_bank_register"] == 0xFF70
        assert ws["stack_min"] == 0xDF00 and ws["stack_end"] == 0xDFFF
        assert ws["expected_hex"]["delay_frame_halt"] == "7600F0D6A720F9C9"
        assert ws["expected_hex"]["overworld_loop"].startswith("D7")  # rst _DelayFrame
        assert ws["expected_hex"]["irq_vector"] == "C3" + ws["vblank_entry"].to_bytes(2, "little").hex().upper()
        assert ws["expected_hex"]["delay_frame_rst"] == "C3" + ws["delay_frame"].to_bytes(2, "little").hex().upper()


@pytest.mark.parametrize("title", TITLES)
def test_checkpoint_bytes_are_in_the_built_rom(title):
    rom = _rom(title)
    assert hashlib.sha1(rom).hexdigest() == PROFILE["titles"][title]["rom_sha1"]
    ws = _json("write_checkpoint")[title]["write_safe"]
    for key, hexs in ws["expected_hex"].items():
        want = bytes.fromhex(hexs)
        assert rom[ws[key]:ws[key] + len(want)] == want, key


def test_checkpoint_regenerates_byte_identically():
    try:
        F.source_root("purergb")
    except SystemExit as e:
        pytest.skip(str(e))
    assert (DATA / "write_checkpoint.json").read_text(encoding="utf-8") == gen_wc.render(gen_wc.build())


# --- admission table ---------------------------------------------------------------------------

def test_admission_table_matches_the_lock_and_the_profile():
    adm = _json("admission")
    by_title = {row["title"]: (sha1, row) for sha1, row in adm.items()}
    assert set(by_title) == set(TITLES)
    for title, (sha1, row) in by_title.items():
        rom_key = pathlib.Path(F.foundation("purergb")["titles"][title][1]).stem
        want = LOCK["outputs"][rom_key]
        assert sha1 == want["sha1"] == PROFILE["titles"][title]["rom_sha1"]
        assert (row["header_crc"], row["crc32"], row["header_title"]) == (want["header_crc"], want["crc32"], want["title"])
        assert row["kind"] == "clean" and row["profile_id"] == f"gen1_purergb/{title}"
        assert row["size"] == 0x100000 and len(row["md5"]) == 32


@pytest.mark.parametrize("title", TITLES)
def test_admission_hashes_are_the_built_rom(title):
    rom = _rom(title)
    sha1 = hashlib.sha1(rom).hexdigest()
    row = _json("admission")[sha1]
    assert row["title"] == title
    assert {k: row[k] for k in ("header_title", "header_crc", "crc32", "md5", "size")} == gen_admission.describe(rom)
