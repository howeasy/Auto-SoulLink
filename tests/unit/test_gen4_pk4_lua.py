"""lua/gen4/pk4.lua (the in-game Gen 4 record codec) == server/adapters/gen4_codec.py.

Real saves are read-only and follow tests/TESTING.md: an ABSENT save skips by name. Every
equality below compares the Lua decode to the independent Python oracle field by field; the
control tests prove the comparison can fail (a mutated Lua module must NOT match).
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import lupa
import pytest

from server.adapters import gen4_codec as codec

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "lua/gen4/pk4.lua"
SAVE_DIR = Path("E:/Howard/Bizhawk/NDS/SaveRAM")
SAVES = {
    "hg": ("SLINK_GEN4_HG_SAVE", "Pokemon - HeartGold Version (USA).SaveRAM", "hgss"),
    "ss": ("SLINK_GEN4_SS_SAVE", "Pokemon - SoulSilver Version (USA).SaveRAM", "hgss"),
    "pt": ("SLINK_GEN4_PT_SAVE", "Pokemon - Platinum Version (USA).SaveRAM", "pt"),
}
TEXT_FIELDS = {"nickname", "ot_name"}  # the Lua module leaves text conversion to a later card
LIST_FIELDS = {"nickname_raw", "ot_name_raw", "moves", "pp", "pp_ups", "evs", "ivs", "stats"}


def load_lua(source: str | None = None):
    lua = lupa.LuaRuntime()
    src = source if source is not None else MODULE.read_text(encoding="utf-8")
    return lua, lua.eval("function(s) return assert(load(s, '=pk4'))() end")(src)


def py(v):
    """Lua table -> list (array) or dict; scalars unchanged."""
    if lupa.lua_type(v) != "table":
        return v
    keys = list(v.keys())
    if keys and keys == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in keys]
    return {k: py(v[k]) for k in keys}


@pytest.fixture(scope="module")
def pk4():
    lua, mod = load_lua()
    return lua, mod


def decode_lua(pk4, raw: bytes, profile: str, party: bool):
    _, mod = pk4
    fn = mod.decode_party_mon if party else mod.decode_box_mon
    return py(fn(raw, mod.PROFILES[profile]))


def assert_matches_oracle(lua_mon: dict, oracle: dict):
    for k, want in oracle.items():
        if k in TEXT_FIELDS:
            continue
        if k in LIST_FIELDS:
            want = list(want)
        assert lua_mon[k] == want, f"{k}: lua {lua_mon[k]!r} != python {want!r}"


# -- raw record extraction from the real saves --------------------------------------------
def raw_records(save: codec.Gen4Save):
    """[(kind, raw_bytes)] straight out of the general/PC blocks (no decode)."""
    p = save.profile
    maxc, cur = struct.unpack_from("<II", save.general, p.party_off)
    assert maxc == 6 and cur <= 6
    out = []
    base = p.party_off + 8
    for i in range(cur):
        out.append(("party", save.general[base + i * codec.PARTY_MON_SIZE : base + (i + 1) * codec.PARTY_MON_SIZE]))
    for b in range(p.box_count):
        for s in range(30):
            off = p.boxes_off + b * p.box_stride + s * codec.BOX_MON_SIZE
            out.append(("box", save.pc[off : off + codec.BOX_MON_SIZE]))
    return out


def load_save(which: str):
    env, default, profile = SAVES[which]
    path = Path(os.environ.get(env) or SAVE_DIR / default)
    if not path.is_file():
        pytest.skip(f"{which} battery save not found: {path} (override with {env})")
    return codec.parse_save(path.read_bytes(), profile), profile


@pytest.mark.parametrize("which", sorted(SAVES))
def test_real_save_records_match_the_python_oracle(pk4, which):
    _, mod = pk4
    save, profile = load_save(which)
    prof = codec.PROFILES[profile]
    decoded = 0
    for kind, raw in raw_records(save):
        empty = codec.is_empty_slot(raw)
        assert bool(mod.is_empty_slot(raw)) == empty
        if empty:
            continue
        party = kind == "party"
        plain_py = (codec.decrypt_party if party else codec.decrypt_box)(raw)
        dec, enc_fn = (mod.decrypt_party, mod.encrypt_party) if party else (mod.decrypt_box, mod.encrypt_box)
        plain_lua = dec(raw)
        assert bytes(py(plain_lua)) == plain_py
        assert bytes(py(enc_fn(plain_lua))) == raw, "encrypt(decrypt(x)) != x"
        oracle = (codec.decode_party_mon if party else codec.decode_box_mon)(raw, prof)
        assert_matches_oracle(decode_lua(pk4, raw, profile, party), oracle)
        decoded += 1
    assert decoded, f"{which}: no populated slot to compare (the test would prove nothing)"


# -- synthetic records ---------------------------------------------------------------------
def build_plain(pid: int, *, party=True, species=250, otid=0x1234_5678, exp=1_000_000, msb=0,
                ability8=0x2A, form=0, hidden=0, level=50, hp=100, max_hp=150) -> bytes:
    p = bytearray(codec.PARTY_MON_SIZE if party else codec.BOX_MON_SIZE)
    a, b, c, d = (8 + 0x20 * i for i in range(4))
    struct.pack_into("<IHH", p, 0, pid, 0, 0)
    struct.pack_into("<HHII", p, a, species, 5, otid, exp | (msb << 31))
    p[a + 0x0C : a + 0x10] = bytes((70, ability8, 3, 2))
    struct.pack_into("<4H", p, b, 33, 45, 52, 0)
    struct.pack_into("<I", p, b + 0x10, 0x8000_0000 | 0x1F | (7 << 5))
    p[b + 0x18] = (form << 3) | 1
    p[b + 0x19] = hidden
    struct.pack_into("<11H", p, c, *codec.encode_name("Lugi", 11))
    struct.pack_into("<8H", p, d, *codec.encode_name("RED", 8))
    p[d + 0x17] = 7
    p[d + 0x1B] = 4
    p[d + 0x1C] = 30
    if party:
        struct.pack_into("<IBBHHHHHHH", p, 0x88, 0, level, 0, hp, max_hp, 90, 80, 70, 60, 50)
    return bytes(p)


def enc(plain: bytes) -> bytes:
    return (codec.encrypt_party if len(plain) == codec.PARTY_MON_SIZE else codec.encrypt_box)(plain)


@pytest.mark.parametrize("row", range(32))
def test_every_shuffle_row_decrypts_like_the_oracle(pk4, row):
    _, mod = pk4
    pid = (0xABCD_0001 & ~0x3E000) | (row << 13)
    for party in (True, False):
        raw = enc(build_plain(pid, party=party))
        lua_dec = mod.decrypt_party if party else mod.decrypt_box
        py_dec = codec.decrypt_party if party else codec.decrypt_box
        assert bytes(py(lua_dec(raw))) == py_dec(raw)


def test_hge_nine_bit_ability_form_and_hidden_bit(pk4):
    raw = enc(build_plain(0x0000_C000 | 0x1357, msb=1, ability8=0x2A, form=0x15, hidden=1))
    got = decode_lua(pk4, raw, "hge", True)
    assert got["ability"] == 0x12A and got["form"] == 0x15 and got["hidden_ability"] == 1
    assert got["exp"] == 1_000_000  # 21-bit exp: the MSB is the ability bit, not exp
    assert_matches_oracle(got, codec.decode_party_mon(raw, codec.PROFILES["hge"]))
    vanilla = decode_lua(pk4, raw, "hgss", True)  # same bytes, hgss profile: no MSB, no hidden bit
    assert vanilla["ability"] == 0x2A and "hidden_ability" not in vanilla
    assert_matches_oracle(vanilla, codec.decode_party_mon(raw, codec.PROFILES["hgss"]))


def test_core_mon_shape_and_key(pk4):
    _, mod = pk4
    raw = enc(build_plain(0xDEADBEEF))
    core = py(mod.to_core_mon(mod.decode_party_mon(raw, mod.PROFILES.hgss)))
    assert core["key"] == "DEADBEEF:12345678" == codec.mon_key(0xDEADBEEF, 0x12345678)
    assert (core["species"], core["level"], core["hp"], core["max_hp"]) == (250, 50, 100, 150)
    assert core["moves"] == [33, 45, 52, 0]
    assert core["nickname_bytes"] == list(codec.encode_name("Lugi", 11)) and "nickname" not in core


# -- negatives -----------------------------------------------------------------------------
@pytest.mark.parametrize("offset", [6, 8, 0x40, 0x87])
def test_a_flipped_byte_fails_the_checksum(pk4, offset):
    _, mod = pk4
    raw = bytearray(enc(build_plain(0xDEADBEEF, party=False)))
    raw[offset] ^= 0x01
    plain, why = mod.decrypt_box(bytes(raw))
    assert plain is None and why == "checksum"
    with pytest.raises(codec.Gen4CodecError):
        codec.decrypt_box(bytes(raw))


def test_size_and_locked_are_refused(pk4):
    _, mod = pk4
    assert tuple(mod.decrypt_box(b"\0" * 10)) == (None, "size")
    assert tuple(mod.decrypt_party(b"\0" * 0x88)) == (None, "size")
    raw = bytearray(enc(build_plain(0xDEADBEEF, party=False)))
    raw[4] |= 0x01
    assert tuple(mod.decrypt_box(bytes(raw))) == (None, "locked")


def test_wrong_pid_is_not_a_box_checksum_failure_but_the_party_tail_is_flagged(pk4):
    """The checksum is a plain sum of the shuffled blocks, so it cannot see a wrong PID on a box
    record (decrypt succeeds with scrambled blocks); the party tail is keyed by the PID and its
    tail_plausible flag is the only guard. Lua and the oracle must agree on both."""
    _, mod = pk4
    good = enc(build_plain(0x0002_0000 | 0x77, party=True))
    bad = bytearray(good)
    struct.pack_into("<I", bad, 0, 0x0004_0000 | 0x77)  # different shuffle row and tail seed
    bad = bytes(bad)
    box_lua, box_py = mod.decrypt_box(bad[:0x88]), codec.decrypt_box(bad[:0x88])
    assert box_lua is not None and bytes(py(box_lua)) == box_py  # no checksum refusal, in both
    assert box_py != codec.decrypt_box(good[:0x88])  # ...but the plaintext is garbage
    assert py(mod.decode_party_mon(bad, mod.PROFILES.hgss))["tail_plausible"] is False
    assert codec.decode_party_mon(bad, codec.PROFILES["hgss"])["tail_plausible"] is False
    assert py(mod.decode_party_mon(good, mod.PROFILES.hgss))["tail_plausible"] is True


def test_controls_mutated_lua_must_diverge_from_the_oracle():
    """Known-positive controls: break the shuffle / PRNG / party-tail seed in a COPY of the module
    and the oracle equality must go red (a probe that cannot fail proves nothing)."""
    src = MODULE.read_text(encoding="utf-8")
    raw = enc(build_plain(0x0003_0000 | 0x1357))
    want = codec.decrypt_party(raw)
    mutations = {
        "shuffle row": ("% 24 + 1", "% 24 + 2"),
        "prng multiplier": ("0x41C64E6D", "0x41C64E6C"),
        "party tail seed": ("lcg_xor(tail, 0, u(b, 0, 4))", "lcg_xor(tail, 0, 0)"),
    }
    _, mod = load_lua(src)
    assert bytes(py(mod.decrypt_party(raw))) == want  # unmutated copy is green
    for name, (old, new) in mutations.items():
        assert src.count(old) == 1, f"mutation anchor for {name!r} drifted"
        _, bad = load_lua(src.replace(old, new))
        got = bad.decrypt_party(raw)
        got = got[0] if isinstance(got, tuple) else got  # multi-return (nil, reason)
        assert got is None or bytes(py(got)) != want, f"mutating the {name} did not break the decode"


def test_module_loads_with_no_globals_leaked():
    lua = lupa.LuaRuntime()
    dump = lua.eval("function() local t = {} for k in pairs(_G) do t[#t + 1] = k end return t end")
    before = set(py(dump()))
    lua.eval("function(s) return assert(load(s, '=pk4'))() end")(MODULE.read_text(encoding="utf-8"))
    assert set(py(dump())) == before
