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
