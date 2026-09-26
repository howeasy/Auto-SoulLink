"""tools/gen3_reads_pydec.py: the reads.lua-vs-gen3_codec.py differ (card gen3-P3-C3-14).

Entirely synthetic -- no ROM, no save file, no emulator. Builds a fake
patch/build/gen3_reads_dump.txt (DUMP + LUA lines) the way
lua/tests/probe_gen3_reads_dump.lua would, using gen3_codec's OWN encoder to produce the raw
bytes so the "LUA" lines are known-correct by construction; the tool then re-decodes those same
bytes and must agree.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "tools"))
sys.path.insert(0, str(_REPO))
import gen3_reads_pydec as pydec  # noqa: E402

from server.adapters import gen3_codec as codec  # noqa: E402


def _mon(personality: int, *, party: bool = True) -> dict:
    mon = {
        "personality": personality, "ot_id": 0xDEADBEEF, "nickname": "NIDOKING",
        "language": 2, "is_bad_egg": 0, "has_species": 1, "is_egg_flag": 0,
        "block_box_rs": 0, "flags_unused": 0, "ot_name": "ASH", "markings": 0x0A,
        "unknown": 0x1234, "species": 34, "held_item": 0x0C, "experience": 125000,
        "pp_bonuses": 0b11010011, "friendship": 200, "growth_filler": 0,
        "moves": [85, 89, 63, 231], "pp": [15, 10, 5, 10],
        "evs": {"hp": 252, "attack": 128, "defense": 6,
                "speed": 64, "sp_attack": 32, "sp_defense": 8},
        "contest": [1, 2, 3, 4, 5, 6],
        "pokerus": 0xF3, "met_location": 88, "met_level": 37,
        "met_game": 4, "pokeball": 3, "ot_gender": 1,
        "ivs": {"hp": 31, "attack": 30, "defense": 29,
                "speed": 28, "sp_attack": 27, "sp_defense": 26},
        "is_egg": 0, "ability_num": 1, "ribbons": 0x0000_2AAA,
    }
    if party:
        mon.update({"status": 0x00000040, "level": 54, "mail": 0xFF,
                    "hp": 111, "max_hp": 160, "attack": 120, "defense": 90,
                    "speed": 95, "sp_attack": 85, "sp_defense": 80})
    return mon


def _write_dump(path: Path, name: str, raw: bytes, decoded_rows: list[dict]) -> None:
    lines = [f"DUMP name={name} addr=0x2024000 len={len(raw)} frame=1 hex={raw.hex()}"]
    for slot, mon in enumerate(decoded_rows):
        fields = pydec._mon_to_fields(mon)
        lines.append(
            f"LUA name={name} slot={slot} key={fields['key']} species={fields['species']} "
            f"level={fields['level']} hp={fields['hp']} nickname={fields['nickname']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_synthetic_dump_agrees_vanilla(tmp_path, capsys):
    mon = _mon(0x1234ABCD)
    raw = codec.encode_party_mon(mon, rr=False)
    decoded = codec.decode_party_mon(raw, rr=False)
    dump = tmp_path / "dump.txt"
    _write_dump(dump, "party", raw, [decoded])

    rc = pydec.main([str(dump), "--title", "firered"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK" in out


def test_synthetic_dump_agrees_rr(tmp_path, capsys):
    mon = _mon(0x1234ABCD)
    raw = codec.encode_party_mon(mon, rr=True)
    decoded = codec.decode_party_mon(raw, rr=True)
    dump = tmp_path / "dump.txt"
    _write_dump(dump, "party", raw, [decoded])

    rc = pydec.main([str(dump), "--title", "radical_red"])
    assert rc == 0


def test_flipped_byte_is_detected(tmp_path, capsys):
    """The planted-offender control (PLAN §5.7 mutation test): --mutate flips one byte of the
    dumped record after the LUA lines were already written from the ORIGINAL bytes, so the
    tool must now disagree with itself."""
    mon = _mon(0x1234ABCD)
    raw = codec.encode_party_mon(mon, rr=False)
    decoded = codec.decode_party_mon(raw, rr=False)
    dump = tmp_path / "dump.txt"
    _write_dump(dump, "party", raw, [decoded])

    rc = pydec.main([str(dump), "--title", "firered", "--mutate"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "difference" in out


def test_refuses_unknown_title(tmp_path):
    mon = _mon(0x1234ABCD)
    raw = codec.encode_party_mon(mon, rr=False)
    decoded = codec.decode_party_mon(raw, rr=False)
    dump = tmp_path / "dump.txt"
    _write_dump(dump, "party", raw, [decoded])

    with pytest.raises(SystemExit) as exc:
        pydec.main([str(dump), "--title", "emerald_hack_9000"])
    assert exc.value.code == 2


def test_refuses_missing_dump(tmp_path):
    with pytest.raises(SystemExit) as exc:
        pydec.main([str(tmp_path / "nope.txt"), "--title", "firered"])
    assert exc.value.code == 2


# ── P4 card C4-2a: the new trainer/location/badges/bag/battle-type decoders ──────────────
def test_decode_trainer_reads_the_ot_id_and_name():
    sb2 = bytearray(20)
    sb2[0:7] = codec.encode_name("ASH", 7)
    sb2[0x0A:0x0E] = (0x12345678).to_bytes(4, "little")
    assert pydec.decode_trainer(bytes(sb2)) == {"ot_id": 0x12345678, "name": "ASH"}


def test_decode_location_is_signed():
    """Adversarial: a negative (>=0x80) mapGroup byte must decode to a negative int, not
    wrap to a huge unsigned value."""
    sb1 = bytearray(10)
    sb1[4], sb1[5] = 250, 3          # 250 == -6 as a signed byte
    assert pydec.decode_location(bytes(sb1)) == {"map_group": -6, "map_num": 3}


def test_decode_badges_isolates_the_one_shared_byte():
    """Adversarial: badge 8 only (bit 7), and a wider int with garbage above bit 7 that must
    be masked off rather than leaking into the bitmask."""
    assert pydec.decode_badges(0b10000000) == 0x80
    assert pydec.decode_badges(0x1_80) == 0x80


def test_decode_ball_pocket_xors_the_low_16_bits_of_a_wide_key_and_skips_empty_slots():
    """Adversarial: a key with bits set above bit 15 must not affect the decrypted quantity,
    and a slot with itemId==ITEM_NONE must not contribute even if its raw quantity is nonzero."""
    key = 0xABCD1234
    qty = 37
    raw = bytearray(8)
    raw[0:2] = (4).to_bytes(2, "little")                      # slot 0: item id 4 (a ball)
    raw[2:4] = (qty ^ (key & 0xFFFF)).to_bytes(2, "little")    # encrypted quantity
    raw[4:6] = (0).to_bytes(2, "little")                       # slot 1: ITEM_NONE
    raw[6:8] = (999).to_bytes(2, "little")                     # garbage raw quantity, must be skipped
    assert pydec.decode_ball_pocket(bytes(raw), 2, key) == {"ball_count": 37, "has_pokeballs": True}
    # unencrypted (CFRU/RR): the raw quantity IS the count
    raw2 = bytearray(4)
    raw2[0:2] = (4).to_bytes(2, "little")
    raw2[2:4] = (12).to_bytes(2, "little")
    assert pydec.decode_ball_pocket(bytes(raw2), 1) == {"ball_count": 12, "has_pokeballs": True}


def test_decode_battle_type_reads_both_masks_independently():
    trainer_mask, double_mask = 0x08, 0x01
    assert pydec.decode_battle_type(0x08, trainer_mask, double_mask) == {
        "is_trainer": True, "is_doubles": False}
    assert pydec.decode_battle_type(0x09, trainer_mask, double_mask) == {
        "is_trainer": True, "is_doubles": True}
    assert pydec.decode_battle_type(0x10, trainer_mask, double_mask) == {
        "is_trainer": False, "is_doubles": False}


def demo():
    """ponytail: smallest runnable check without pytest."""
    mon = _mon(0x1234ABCD)
    raw = codec.encode_party_mon(mon, rr=False)
    decoded = codec.decode_party_mon(raw, rr=False)
    fields = pydec._mon_to_fields(decoded)
    assert fields["species"] == "34", fields
    print("demo ok")


if __name__ == "__main__":
    demo()
