"""Falsifiers for the PK4 record half of server/adapters/gen4_codec.py (the PYDEC oracle).

Synthetic records are built here from the pret field layout (include/pokemon_types_def.h)
without calling the codec's own decoders, so a codec bug cannot cancel itself out.  The real
owner save is covered in test_gen4_save_layout.py.
"""

from __future__ import annotations

import contextlib
import struct
from pathlib import Path

import pytest

from server.adapters import gen4_codec as codec

HGSS, HGE = codec.PROFILES["hgss"], codec.PROFILES["hge"]
A, B, C, D = (8 + 0x20 * i for i in range(4))


def plain_mon(pid=0x12345678, *, species=155, otid=0x74C066C6, expword=135, ability=66, item=0,
              form=0, origin=7, ball=4, ball_hgss=0, party=False, level=5, hp=20, max_hp=20,
              nickname="CYNDA", ot="SPLERM") -> bytearray:
    """A logical-order (A,B,C,D) plaintext record with a distinct value in every decoded field."""
    p = bytearray(codec.PARTY_MON_SIZE if party else codec.BOX_MON_SIZE)
    struct.pack_into("<IHH", p, 0, pid, 0, 0)
    struct.pack_into("<HHII", p, A, species, item, otid, expword)
    p[A + 0x0C : A + 0x10] = bytes([70, ability, 0, 2])          # friendship, ability, marks, lang
    p[A + 0x10 : A + 0x16] = bytes([1, 2, 3, 4, 5, 6])           # EVs
    struct.pack_into("<4H", p, B, 33, 43, 0, 0)
    p[B + 8 : B + 12] = bytes([35, 30, 0, 0])
    p[B + 12 : B + 16] = bytes([1, 2, 0, 0])
    struct.pack_into("<I", p, B + 0x10, 26 | 2 << 5 | 5 << 10 | 23 << 15 | 9 << 20 | 30 << 25 | 1 << 31)
    p[B + 0x18] = 0 | (1 << 1) | (form << 3)                     # fateful 0, gender 1, form
    struct.pack_into("<2H", p, B + 0x1C, 0, 126)                 # Pt/HGSS egg / met location
    struct.pack_into("<11H", p, C, *codec.encode_name(nickname, 11))
    p[C + 0x17] = origin
    struct.pack_into("<8H", p, D, *codec.encode_name(ot, 8))
    struct.pack_into("<2H", p, D + 0x16, 0, 3002)                # DP egg / met (faraway -> PtHGSS)
    p[D + 0x1B], p[D + 0x1C], p[D + 0x1E] = ball, 5 | 1 << 7, ball_hgss
    if party:
        struct.pack_into("<IBBHHHHHHH", p, 0x88, 0, level, 0, hp, max_hp, 9, 9, 12, 11, 11)
    return p


def same_record(got: bytes, plain: bytes) -> bool:
    """Equal except the checksum word, which encrypt_box fills in (and must equal the block sum)."""
    csum = struct.unpack_from("<H", got, 6)[0]
    return got[:6] + got[8:] == plain[:6] + plain[8:] and csum == codec.checksum(got[8:0x88])


def test_primitives_known_answers():
    assert codec.crc16_ccitt(b"123456789") == 0x29B1            # CRC-16/CCITT-FALSE check value
    assert codec.checksum(struct.pack("<4H", 0xFFFF, 2, 3, 4)) == (0xFFFF + 9) & 0xFFFF
    assert codec.counter_newer(0xFFFFFFFF, 0) == -1 and codec.counter_newer(0, 0xFFFFFFFF) == 1
    assert codec.counter_newer(5, 3) == 1 and codec.counter_newer(3, 5) == -1 and codec.counter_newer(7, 7) == 0
    assert codec.counter_newer(0xFFFFFFFE, 0xFFFFFFFF) == -1    # only the exact (-1, 0) pair wraps
    assert codec.mon_key(0xEBEDBB42, 0x74C066C6) == "EBEDBB42:74C066C6"


def test_prng_is_the_pret_lcg():
    # first output of seed 0: 0x6073 >> 16 == 0; second: (0x6073*0x41C64E6D+0x6073)>>16
    s = (0 * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
    s = (s * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
    assert codec._lcg_xor(b"\0\0\0\0", 0) == struct.pack("<2H", 0, s >> 16)
    blob = bytes(range(32))
    assert codec._lcg_xor(codec._lcg_xor(blob, 0xBEEF), 0xBEEF) == blob   # symmetric


@pytest.mark.parametrize("row", range(32))
def test_box_roundtrip_every_shuffle_row(row):
    plain = bytes(plain_mon(pid=(row << 13) | 0xA5A5_0123 & ~0x3E000))
    raw = codec.encrypt_box(plain)
    assert raw != plain and same_record(codec.decrypt_box(raw), plain)
    mon = codec.decode_box_mon(raw, HGSS)
    assert (mon["species"], mon["tid"], mon["sid"]) == (155, 26310, 29888)
    assert mon["moves"] == (33, 43, 0, 0) and mon["ivs"] == (26, 2, 5, 23, 9, 30)
    assert mon["key"] == f"{mon['pid']:08X}:74C066C6" and mon["nickname"] == "CYNDA"


def test_shuffle_table_verbatim_and_duplicate_rows_matter(monkeypatch):
    assert codec._SHUFFLE[24:32] == codec._SHUFFLE[0:8]
    assert all(sorted(r) == [0, 0x20, 0x40, 0x60] for r in codec._SHUFFLE)
    pid = 25 << 13                                             # a row only the duplicates cover
    assert codec.block_offsets(pid) == codec._SHUFFLE[1]
    raw = codec.encrypt_box(bytes(plain_mon(pid=pid)))
    assert codec.decode_box_mon(raw, HGSS)["species"] == 155
    # Known-positive control: a 24-row table (rows 24-31 missing) must fail on that pid.
    monkeypatch.setattr(codec, "_SHUFFLE", codec._SHUFFLE[:24])
    with pytest.raises(IndexError):
        codec.block_offsets(pid)
    monkeypatch.undo()
    # The row is load-bearing: the same stored bytes under another row decode to other blocks.
    other = bytearray(codec.encrypt_box(bytes(plain_mon(pid=1 << 13))))
    other[2] ^= 0x02                                             # pid bit 17: row 1 becomes row 17
    assert codec.decode_box_mon(bytes(other), HGSS)["species"] != 155


def test_every_flipped_byte_is_refused():
    raw = codec.encrypt_box(bytes(plain_mon()))
    for i in (6, 7, 8, 9, 0x40, 0x87):                           # checksum field and data bytes
        bad = bytearray(raw)
        bad[i] ^= 0x01
        with pytest.raises(codec.Gen4CodecError) as exc:
            codec.decode_box_mon(bytes(bad), HGSS)
        assert exc.value.reason == "checksum", i


def test_locked_plaintext_record_is_refused_not_xored():
    plain = bytearray(codec.encrypt_box(bytes(plain_mon())))
    plain[4] |= 0x03                                             # partyDecrypted|boxDecrypted
    with pytest.raises(codec.Gen4CodecError) as exc:
        codec.decode_box_mon(bytes(plain), HGSS)
    assert exc.value.reason == "locked"


def test_wrong_sizes_refused():
    with pytest.raises(codec.Gen4CodecError):
        codec.decrypt_box(b"\0" * 0x87)
    with pytest.raises(codec.Gen4CodecError):
        codec.decrypt_party(b"\0" * 0x88)


def test_empty_slots_detected():
    assert codec.is_empty_slot(bytes(codec.BOX_MON_SIZE))
    assert codec.is_empty_slot(codec.encrypt_box(bytes(codec.BOX_MON_SIZE)))        # ZeroBoxMonData form
    assert not codec.is_empty_slot(codec.encrypt_box(bytes(plain_mon())))


def test_party_roundtrip_and_tail_seed():
    plain = bytes(plain_mon(party=True))
    raw = codec.encrypt_party(plain)
    assert len(raw) == 0xEC and same_record(codec.decrypt_party(raw), plain)
    mon = codec.decode_party_mon(raw, HGSS)
    assert (mon["level"], mon["hp"], mon["max_hp"], mon["stats"]) == (5, 20, 20, (9, 9, 12, 11, 11))
    assert mon["tail_plausible"]
    # The tail really is encrypted (HP is not readable at 0x8E), and under the PID seed only.
    assert struct.unpack_from("<H", raw, 0x8E)[0] != 20
    pid = struct.unpack_from("<I", raw, 0)[0]
    assert codec._lcg_xor(raw[0x88:], pid) == plain[0x88:]
    wrong = raw[:0x88] + codec._lcg_xor(plain[0x88:], pid ^ 0x1234)
    bad = codec.decode_party_mon(wrong, HGSS)
    assert bad["species"] == 155 and not bad["tail_plausible"]   # box half fine, tail detectably wrong


def test_hge_ability_msb_and_exp_mask():
    exp = 135 | (0x3FF << 21)                                    # junk in the 10 unused bits
    word = exp | (1 << 31)                                       # abilityMSB set
    raw = codec.encrypt_box(bytes(plain_mon(expword=word, ability=0x2F)))
    hge = codec.decode_box_mon(raw, HGE)
    assert hge["ability"] == 0x12F and hge["exp"] == 135
    nomsb = codec.decode_box_mon(codec.encrypt_box(bytes(plain_mon(expword=135, ability=0x2F))), HGE)
    assert nomsb["ability"] == 0x2F
    vanilla = codec.decode_box_mon(raw, HGSS)                    # vanilla: u8 ability, full u32 exp
    assert vanilla["ability"] == 0x2F and vanilla["exp"] == word


def test_form_is_five_bits_and_ball_rule():
    assert codec.decode_box_mon(codec.encrypt_box(bytes(plain_mon(form=31))), HGSS)["form"] == 31
    mon = codec.decode_box_mon(codec.encrypt_box(bytes(plain_mon(form=7))), HGE)
    assert (mon["form"], mon["gender"], mon["fateful"]) == (7, 1, 0)
    # src/pokemon.c:833-837: block D +0x1E wins only for an HG/SS origin and only when nonzero
    for origin, hgss_ball, want in ((7, 0x10, 0x10), (8, 0x11, 0x11), (7, 0, 4), (4, 0x10, 4)):
        raw = codec.encrypt_box(bytes(plain_mon(origin=origin, ball=4, ball_hgss=hgss_ball)))
        assert codec.decode_box_mon(raw, HGSS)["ball"] == want, (origin, hgss_ball)


def test_met_location_rule():
    mon = codec.decode_box_mon(codec.encrypt_box(bytes(plain_mon())), HGSS)
    assert mon["met_location"] == 126 and mon["egg_location"] == 0     # DP = faraway -> PtHGSS
    p = plain_mon()
    struct.pack_into("<H", p, D + 0x18, 77)                      # a real DP location wins
    assert codec.decode_box_mon(codec.encrypt_box(bytes(p)), HGSS)["met_location"] == 77


def test_charmap_roundtrip_and_pret_run():
    assert len(codec._LATIN_RUN) == 0x1E2 - 0x121 + 1
    for ch, code in (("0", 0x121), ("A", 0x12B), ("a", 0x145), ("z", 0x15E), ("À", 0x15F),
                     ("$", 0x1A8), ("!", 0x1AB), ("♂", 0x1BB), ("-", 0x1BE), ("%", 0x1D2)):
        assert codec._CHARMAP[code] == ch
    assert codec.decode_name(codec.encode_name("Box 1", 20)) == "Box 1"
    assert codec.encode_name("AB", 4) == (0x12B, 0x12C, 0xFFFF, 0xFFFF)
    assert codec.decode_name((0x12B, 0x7777, 0xFFFF, 0x12C)) == "A<$7777>"
    assert codec.encode_name("A<$7777>", 4)[:2] == (0x12B, 0x7777)
    with pytest.raises(codec.Gen4CodecError):
        codec.encode_name("ABCD", 4)                              # no room for the terminator
    with pytest.raises(codec.Gen4CodecError):
        codec.encode_name("\u3042", 4)                            # kana is not in the Latin run


def test_charmap_matches_pret_file_when_present():
    path = Path("E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold/charmap.txt")
    if not path.is_file():
        pytest.skip(f"pokeheartgold charmap.txt not found: {path}")
    pret = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if len(line) > 5 and line[4] == "=" and not line.startswith("//"):
            with contextlib.suppress(ValueError):
                pret[int(line[:4], 16)] = line[5:]
    assert len(pret) > 1000, "charmap.txt parsed to almost nothing"
    for code, ch in codec._CHARMAP.items():
        assert pret.get(code) == ch, f"{code:04X}: ours {ch!r} pret {pret.get(code)!r}"
