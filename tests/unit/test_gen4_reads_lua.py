"""lua/gen4/reads.lua == the Python oracle (server/adapters/gen4_codec.py), on a fake main RAM.

The REAL battery saves' general blocks (HG, SS, Pt; read-only, ABSENT saves skip by name per
tests/TESTING.md) are laid into a fake 4 MiB main RAM the way the game lays SaveData out:

  SaveData + 0x10            dynamic region: general chunk at +0 (its 0x10-byte footer is the signature),
                             PC chunk at +0xF700
  SaveData + 0x23010         save counter
  SaveData + 0x23014         42 array headers {u32 id, u32 size, u32 offset, u16 crc, u16 slot}
  SaveData + 0x232B4         slot specs {u8 id, u8 first_page, u16 num_pages, u32 offset, u32 size}

The header/spec geometry is the REAL one from the probe dump
``C:/slink/g4/probe/runs/hg_p2/savedata.bin`` (a 0x30000-byte RAM dump of the live SaveData struct,
HG, idle overworld; run row h item4): ``ARRAY_TABLE`` below is that dump's (size, offset) for the arrays
the client reads, embedded so the suite runs without the dump; ``test_probe_dump_*`` cross-checks them
when the dump is present. The only bytes where the live dump differs from the battery file's
general block are four runtime-mutable bytes (general+0x24/+0x28/+0x2C in the sysinfo array, +0x89 in
the player array), not layout.

Platinum's pageInfo table is RAM-only and was never dumped: its table is a MODEL (labelled), built
from the codec's FILE-checked Pt offsets (player array 0x64, party array 0x98), and the pack lacks Pt
party_off/trainer entries (pack gaps), so those are supplied by the model profile.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import os
import struct
from pathlib import Path

import lupa
import pytest

from server.adapters import gen4_codec as codec

ROOT = Path(__file__).resolve().parents[2]
READS = ROOT / "lua/gen4/reads.lua"
PK4 = ROOT / "lua/gen4/pk4.lua"
SAVE_DIR = Path("E:/Howard/Bizhawk/NDS/SaveRAM")
PROBE_DUMP = Path("C:/slink/g4/probe/runs/hg_p2/savedata.bin")
SAVES = {
    "hg": ("SLINK_GEN4_HG_SAVE", "Pokemon - HeartGold Version (USA).SaveRAM", "hgss", "gen4_hgss", "heartgold"),
    "ss": ("SLINK_GEN4_SS_SAVE", "Pokemon - SoulSilver Version (USA).SaveRAM", "hgss", "gen4_hgss", "soulsilver"),
    "pt": ("SLINK_GEN4_PT_SAVE", "Pokemon - Platinum Version (USA).SaveRAM", "pt", "gen4_pt", "platinum"),
}
RAM_LO, RAM_HI = 0x02000000, 0x023FFFFF
SD = 0x0227C204  # the probe run's SaveData heap address
# probe dump arrayHeaders[id] -> (size, offset)  (hg_p2/savedata.bin @ 0x23014 + id*16)
ARRAY_TABLE = {0: (0x60, 0x0), 1: (0x30, 0x60), 2: (0x5B4, 0x90), 3: (0x7A0, 0x644), 5: (0x84, 0x1234),
               41: (0x12300, 0xF700)}
PC_OFF = 0xF700
TEXT_FIELDS = {"nickname", "ot_name"}
LIST_FIELDS = {"nickname_raw", "ot_name_raw", "moves", "pp", "pp_ups", "evs", "ivs", "stats"}
PLANTED_JOHTO, PLANTED_KANTO = 0xA5, 0x3C  # the real saves read 0/0, which would prove nothing


# -- Lua plumbing --------------------------------------------------------------------------
def make_lua(reads_src: str | None = None):
    lua = lupa.LuaRuntime()
    loader = lua.eval("function(s, n) return assert(load(s, n))() end")
    pk4 = loader(PK4.read_text(encoding="utf-8"), "=pk4")
    reads = loader(reads_src if reads_src is not None else READS.read_text(encoding="utf-8"), "=reads")
    reads.pk4 = pk4
    return lua, reads


def to_lua(lua, v):
    if isinstance(v, dict):
        return lua.table_from({k: to_lua(lua, x) for k, x in v.items() if x is not None})
    if isinstance(v, list):
        return lua.table_from([to_lua(lua, x) for x in v])
    return v


def py(v):
    if lupa.lua_type(v) != "table":
        return v
    keys = list(v.keys())
    if keys and keys == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in keys]
    return {k: py(v[k]) for k in keys}


class Ram:
    """Fake NDS main RAM. Reads outside it return None and are counted (the module must never try)."""

    def __init__(self, image: bytearray | None = None):
        self.mem = bytearray(image) if image is not None else bytearray(RAM_HI - RAM_LO + 1)
        self.holes: list[tuple[int, int]] = []
        self.oob_calls = 0

    def put(self, addr: int, data: bytes):
        self.mem[addr - RAM_LO : addr - RAM_LO + len(data)] = data

    def u32_cell(self, addr: int, value: int):
        self.put(addr, struct.pack("<I", value))

    def _rd(self, size):
        def f(addr):
            if addr < RAM_LO or addr + size - 1 > RAM_HI:
                self.oob_calls += 1
                return None
            if any(lo <= addr + size - 1 and addr <= hi for lo, hi in self.holes):
                return None
            return int.from_bytes(self.mem[addr - RAM_LO : addr - RAM_LO + size], "little")
        return f

    def adapter(self, lua, boom: bool = False):
        if boom:
            def f(addr):
                raise RuntimeError("bus fault")
            return lua.table_from({"u8": f, "u16": f, "u32": f})
        return lua.table_from({"u8": self._rd(1), "u16": self._rd(2), "u32": self._rd(4)})


# -- fixture assembly ----------------------------------------------------------------------
def load_save(which: str):
    env, default, codec_profile, _, _ = SAVES[which]
    path = Path(os.environ.get(env) or SAVE_DIR / default)
    if not path.is_file():
        pytest.skip(f"{which} battery save not found: {path} (override with {env})")
    return codec.parse_save(path.read_bytes(), codec_profile)


def pack_profile(which: str) -> dict:
    _, _, _, pack, title = SAVES[which]
    doc = json.loads((ROOT / f"data/games/{pack}/profile.json").read_text(encoding="utf-8"))
    return doc["titles"][title]["profile"]


def model_pt_profile(prof: dict) -> dict:
    """MODEL: Platinum's pack carries no party_off/trainer; the PlayerProfile/Party structs are the same
    shape (codec.player()/party() read them identically), so borrow the HGSS pack's entries."""
    hg = pack_profile("hg")
    out = copy.deepcopy(prof)
    out["party_off"], out["trainer"] = copy.deepcopy(hg["party_off"]), copy.deepcopy(hg["trainer"])
    return out


def build_ram(which: str):
    """-> (Ram, planted codec save, lua-side profile dict, pack-gap-model flag)."""
    save = load_save(which)
    prof = pack_profile(which)
    g = bytearray(save.general)
    t = prof["trainer"] if which != "pt" else pack_profile("hg")["trainer"]
    base = (0x60 if which != "pt" else 0x64) + t["profile_off_in_array"]
    g[base + t["johto_badges_off"]], g[base + t["kanto_badges_off"]] = PLANTED_JOHTO, PLANTED_KANTO
    planted = dataclasses.replace(save, general=bytes(g))
    ram = Ram()
    sv = prof["save"]
    ram.u32_cell(prof["save_ptr"]["address"], SD)
    if which == "pt":
        # MODEL pageInfo table: id1 player @0x64, id2 party @0x98 (codec Pt FILE offsets)
        body = SD + sv["body_off"]
        assert len(g) <= sv["body_size"]
        ram.put(body, bytes(g))
        for i, (size, loc) in {1: (0x30, 0x64), 2: (0x5B4, 0x98)}.items():
            ram.put(SD + sv["table_off"] + i * sv["entry_size"], struct.pack("<IIIHH", i, size, loc, 0, i))
        prof = model_pt_profile(prof)
    else:
        assert len(g) == 0xF628, "array table/specs below describe the HG general chunk size"
        dyn = SD + sv["dynamic_region_off"]
        ram.put(SD, bytes.fromhex("01000000010000000000000000000000"))
        ram.put(dyn, bytes(g))
        ram.put(dyn + PC_OFF, save.pc)
        ram.u32_cell(SD + sv["save_counter_off"], save.counter)
        for i, (size, off) in ARRAY_TABLE.items():
            ram.put(SD + sv["array_headers_off"] + i * sv["array_header_size"], struct.pack("<IIIHH", i, size, off, 0, 0))
        spec = SD + sv["slot_specs_off"]
        ram.put(spec, struct.pack("<BBHII", 0, 0, 0x10, 0, len(g)))
        ram.put(spec + 12, struct.pack("<BBHII", 1, 0x10, 0x13, PC_OFF, len(save.pc)))
    return ram, planted, prof


@pytest.fixture(scope="module")
def lua_reads():
    return make_lua()


@pytest.fixture(scope="module", params=sorted(SAVES))
def world(request, lua_reads):
    lua, reads = lua_reads
    ram, planted, prof = build_ram(request.param)
    return request.param, lua, reads, ram, planted, prof, to_lua(lua, prof)


# -- reads == oracle -----------------------------------------------------------------------
def test_save_data_and_arrays(world):
    which, lua, reads, ram, planted, prof, lprof = world
    mem = ram.adapter(lua)
    assert reads.save_data(mem, lprof) == SD
    if which == "pt":
        assert reads.array(mem, lprof, SD, 2) == (SD + 20 + 0x98, 0x5B4)
        assert reads.array(mem, lprof, SD, 1)[0] == SD + 20 + 0x64
        return
    for i, (size, off) in ARRAY_TABLE.items():
        assert tuple(reads.array(mem, lprof, SD, i)) == (SD + 0x10 + off, size)
    assert reads.array(mem, lprof, SD, "party")[0] == SD + 0x10 + 0x90  # by pack name
    got = bytes(py(reads.bytes(mem, reads.array(mem, lprof, SD, 2)[0], 12)))
    assert got == planted.general[0x90:0x9C]
    assert struct.unpack_from("<II", got) == (6, len(planted.party()))  # max, count
    assert ram.oob_calls == 0


def assert_mon_matches(core: dict, oracle: dict, slot: int):
    dec = core["decoded"]
    for k, want in oracle.items():
        if k in TEXT_FIELDS:
            continue
        if k in LIST_FIELDS:
            want = list(want)
        assert dec[k] == want, f"{k}: lua {dec[k]!r} != python {want!r}"
    assert core["slot"] == slot
    assert core["key"] == oracle["key"]
    assert (core["species"], core["level"], core["hp"], core["max_hp"]) == (
        oracle["species"], oracle["level"], oracle["hp"], oracle["max_hp"])
    assert core["moves"] == list(oracle["moves"])
    assert core["nickname_bytes"] == list(oracle["nickname_raw"])


def test_party_matches_codec(world):
    which, lua, reads, ram, planted, prof, lprof = world
    mem = ram.adapter(lua)
    got = py(reads.party(mem, lprof))
    want = planted.party()
    assert want, f"{which}: no party mon to compare (the test would prove nothing)"
    assert len(got) == len(want)
    for i, (g, w) in enumerate(zip(got, want, strict=True)):
        assert_mon_matches(g, w, i)
    # an explicit, pre-resolved SaveData gives the same answer
    assert len(py(reads.party(mem, lprof, SD))) == len(want)


def test_trainer_money_badges_match_codec(world):
    which, lua, reads, ram, planted, prof, lprof = world
    mem = ram.adapter(lua)
    want = planted.player()
    tr = py(reads.trainer(mem, lprof))
    assert tr["name_raw"] == list(want["name_raw"])
    assert (tr["otid"], tr["tid"], tr["sid"]) == (want["id"], want["tid"], want["sid"])
    assert (tr["gender"], tr["language"], tr["version"]) == (want["gender"], want["language"], want["version"])
    assert reads.money(mem, lprof) == want["money"]
    b = py(reads.badges(mem, lprof))
    assert (b["johto"], b["kanto"]) == (want["johto_badges"], want["kanto_badges"]) == (PLANTED_JOHTO, PLANTED_KANTO)
    assert b["mask"] == PLANTED_JOHTO | PLANTED_KANTO << 8 and b["count"] == 8  # 16 badges, 2 regions
    name = reads.decode_name(lua.table_from(list(want["name_raw"])), lua.table_from(codec._CHARMAP))
    assert name == want["name"] and name


def test_location_via_pack_supplied_entry_matches_the_save_layout(lua_reads):
    """The HGSS pack's Location entry (added by the pack generator) is checked against
    tools/gen4_routes.py's own decode (general+0x1234, Location = 5 x int); without it, a named gap."""
    lua, reads = lua_reads
    ram, planted, prof = build_ram("hg")
    mem = ram.adapter(lua)
    loc = prof["location"]
    assert {k: loc[k] for k in ("array_id", "map_off", "warp_off", "x_off", "y_off", "dir_off")} == {
        "array_id": 5, "map_off": 0, "warp_off": 4, "x_off": 8, "y_off": 12, "dir_off": 16}
    gap = {k: v for k, v in prof.items() if k != "location"}
    nil, why = reads.location(mem, to_lua(lua, gap))
    assert nil is None and why == "pack_gap:location"
    m, w, x, y, d = struct.unpack_from("<iiiii", planted.general, 0x1234)
    got = py(reads.location(mem, to_lua(lua, prof)))
    assert got == {"map_id": m, "warp_id": w, "x": x, "y": y, "dir": d} and (m, x, y) != (0, 0, 0)


def test_decode_name_terminator_unknown_code_and_charmap_is_the_callers(lua_reads):
    lua, reads = lua_reads
    cm = lua.table_from({0x0121: "0", 0x0122: "1"})
    assert reads.decode_name(lua.table_from([0x0121, 0x0122, 0xFFFF, 0x0121]), cm) == "01"
    assert reads.decode_name(lua.table_from([0x0121, 0x7777]), cm) == "0<$7777>"
    assert reads.decode_name(lua.table_from([0xFFFF]), cm) == ""
    assert reads.decode_name(lua.table_from([0x0121]), lua.table_from({0x0121: "Z"})) == "Z"


# -- negatives: (nil, reason), never an error, never an out-of-RAM bus access ---------------
def hg_world(lua_reads):
    lua, reads = lua_reads
    ram, planted, prof = build_ram("hg")
    return lua, reads, ram, planted, prof, to_lua(lua, prof)


def refused(res, reason):
    assert res[0] is None and res[1] == reason, res


def test_range_checks_cover_start_and_end(lua_reads):
    lua, reads = lua_reads
    ram = Ram()
    mem = ram.adapter(lua)
    assert reads.read(mem, RAM_HI - 3, 4) == 0
    refused(reads.read(mem, RAM_HI - 2, 4), "out_of_ram")        # straddles the end of RAM
    refused(reads.read(mem, RAM_LO - 1, 1), "out_of_ram")
    refused(reads.read(mem, RAM_HI + 1, 1), "out_of_ram")
    refused(reads.bytes(mem, RAM_HI - 0x1F, 0x20 + 1), "out_of_ram")
    assert len(py(reads.bytes(mem, RAM_HI - 0x1F, 0x20))) == 0x20
    assert ram.oob_calls == 0, "the adapter was reached for an out-of-range read"
    ram.holes.append((RAM_LO + 0x100, RAM_LO + 0x1FF))
    refused(reads.read(mem, RAM_LO + 0x100, 4), "unmapped")
    refused(reads.bytes(mem, RAM_LO + 0xF0, 0x20), "unmapped")
    refused(reads.read(ram.adapter(lua, boom=True), RAM_LO, 4), "unmapped")  # a raising bus is unmapped


@pytest.mark.parametrize("ptr, reason", [
    (0, "null_ptr"),
    (0x03000000, "out_of_ram"),               # outside main RAM
    (0x00100000, "out_of_ram"),
    (RAM_HI - 0x100, "out_of_ram"),           # inside RAM but the struct extent straddles the end
    (RAM_HI - 0x22000, "out_of_ram"),         # extent (0x23400) still runs past the end
])
def test_bad_save_pointer_refuses(lua_reads, ptr, reason):
    lua, reads, ram, planted, prof, lprof = hg_world(lua_reads)
    ram.u32_cell(prof["save_ptr"]["address"], ptr)
    mem = ram.adapter(lua)
    refused(reads.save_data(mem, lprof), reason)
    refused(reads.party(mem, lprof), reason)
    refused(reads.trainer(mem, lprof), reason)
    refused(reads.money(mem, lprof), reason)
    refused(reads.badges(mem, lprof), reason)
    assert ram.oob_calls == 0


def test_pointer_cell_itself_straddling_the_end_of_ram(lua_reads):
    lua, reads, ram, planted, prof, lprof = hg_world(lua_reads)
    prof["save_ptr"]["address"] = RAM_HI - 1
    refused(reads.save_data(ram.adapter(lua), to_lua(lua, prof)), "out_of_ram")
    assert ram.oob_calls == 0


def test_unmapped_save_pointer_cell(lua_reads):
    lua, reads, ram, planted, prof, lprof = hg_world(lua_reads)
    a = prof["save_ptr"]["address"]
    ram.holes.append((a, a + 3))
    refused(reads.save_data(ram.adapter(lua), lprof), "unmapped")


def corrupt_footer_magic(ram, prof):
    sv = prof["save"]
    foot = SD + sv["dynamic_region_off"] + 0xF628 - sv["chunk_footer"]["size"]
    ram.u32_cell(foot + sv["chunk_footer"]["fields"]["magic"], 0xDEADBEEF)


def test_corrupt_signature_refuses(lua_reads):
    lua, reads, ram, planted, prof, lprof = hg_world(lua_reads)
    corrupt_footer_magic(ram, prof)
    refused(reads.save_data(ram.adapter(lua), lprof), "signature")
    refused(reads.party(ram.adapter(lua), lprof), "signature")


def test_footer_size_and_slot_must_match_the_spec(lua_reads):
    for field, bad in (("size", 0x1234), ("slot", 1)):
        lua, reads, ram, planted, prof, lprof = hg_world(lua_reads)
        cf = prof["save"]["chunk_footer"]
        foot = SD + prof["save"]["dynamic_region_off"] + 0xF628 - cf["size"]
        ram.put(foot + cf["fields"][field], struct.pack("<I" if field == "size" else "<H", bad))
        refused(reads.save_data(ram.adapter(lua), lprof), "signature")


def test_party_count_above_six_refuses(lua_reads):
    lua, reads, ram, planted, prof, lprof = hg_world(lua_reads)
    ram.u32_cell(SD + 0x10 + 0x90 + 4, 7)
    refused(reads.party(ram.adapter(lua), lprof), "party_count")
    ram.u32_cell(SD + 0x10 + 0x90 + 4, 0xFFFFFFFF)
    refused(reads.party(ram.adapter(lua), lprof), "party_count")


def test_party_max_not_six_refuses(lua_reads):
    lua, reads, ram, planted, prof, lprof = hg_world(lua_reads)
    ram.u32_cell(SD + 0x10 + 0x90, 5)
    refused(reads.party(ram.adapter(lua), lprof), "party_count")


def test_corrupt_checksum_refuses(lua_reads):
    lua, reads, ram, planted, prof, lprof = hg_world(lua_reads)
    mon0 = SD + 0x10 + 0x90 + 8
    ram.mem[mon0 + 0x30 - RAM_LO] ^= 0x01  # a body byte of mon 0: the u16-sum checksum no longer matches
    refused(reads.party(ram.adapter(lua), lprof), "party_mon0:checksum")


def test_array_header_must_name_its_own_id_and_stay_inside_the_region(lua_reads):
    lua, reads, ram, planted, prof, lprof = hg_world(lua_reads)
    sv = prof["save"]
    hdr = SD + sv["array_headers_off"] + 2 * sv["array_header_size"]
    ram.u32_cell(hdr, 9)                                  # id field no longer 2
    refused(reads.array(ram.adapter(lua), lprof, SD, 2), "bad_array")
    refused(reads.array(ram.adapter(lua), lprof, SD, 99), "bad_array_id")
    refused(reads.array(ram.adapter(lua), lprof, SD, "nope"), "bad_array_id")
    ram.u32_cell(hdr, 2)
    ram.u32_cell(hdr + 8, sv["dynamic_region_size"] - 4)  # offset + size runs past the dynamic region
    refused(reads.array(ram.adapter(lua), lprof, SD, 2), "bad_array")
    ram.u32_cell(hdr + 8, 0x90)
    ram.u32_cell(hdr + 4, 8)                              # array too small for 1 mon
    refused(reads.party(ram.adapter(lua), lprof), "bad_array")


def test_pack_gaps_are_named_not_hard_coded(lua_reads):
    lua, reads = lua_reads
    ram, planted, prof = build_ram("hg")
    mem = ram.adapter(lua)
    hge = json.loads((ROOT / "data/games/gen4_hge/profile.json").read_text(encoding="utf-8"))
    # the hge pack now carries party_off/trainer (FILE); strip them to prove a gap is named, not guessed
    hprof = {k: v for k, v in hge["titles"]["heartgold_hge"]["profile"].items() if k not in ("party_off", "trainer")}
    hp = to_lua(lua, hprof)
    refused(reads.party(mem, hp), "pack_gap:party_off")
    assert reads.trainer(mem, hp)[1].startswith("pack_gap:trainer")
    assert reads.badges(mem, hp)[1].startswith("pack_gap:trainer")
    assert reads.money(mem, hp)[1].startswith("pack_gap:trainer")
    lua2, no_pk4 = make_lua()
    no_pk4.pk4 = None
    refused(no_pk4.party(ram.adapter(lua2), to_lua(lua2, prof)), "no_pk4")
    nb = copy.deepcopy(prof)
    del nb["battle"]["man_data_off"]  # the real pack now carries the battle block; a deleted key is a named gap
    refused(reads.battle(mem, to_lua(lua, nb)), "pack_gap:battle.man_data_off")
    refused(reads.save_data(mem, lua.table_from({})), "pack_gap:save_ptr")


# -- controls: the assertions above can fail ------------------------------------------------
def test_control_unguarded_signature_would_not_refuse(lua_reads):
    """Revert-test: delete the signature comparison from the module; the corrupt-magic negative must
    then NOT refuse, which is exactly what test_corrupt_signature_refuses detects."""
    src = READS.read_text(encoding="utf-8")
    needle = "return magic == cf.magic and fsize == size and fslot == slot"
    assert needle in src
    lua, reads = make_lua(src.replace(needle, "return true"))
    ram, planted, prof = build_ram("hg")
    corrupt_footer_magic(ram, prof)
    assert reads.save_data(ram.adapter(lua), to_lua(lua, prof)) == SD  # reverted module accepts: bug caught


def test_control_unguarded_range_check_would_reach_the_bus(lua_reads):
    src = READS.read_text(encoding="utf-8")
    needle = "addr + len - 1 <= R.RAM_HI"
    assert needle in src
    lua, reads = make_lua(src.replace(needle, "true"))
    ram = Ram()
    assert reads.read(ram.adapter(lua), RAM_HI - 2, 4) == (None, "unmapped") and ram.oob_calls == 1  # reaches the adapter


def test_control_miscounted_kanto_offset_is_detected(lua_reads):
    """The pre-correction research note put the kanto byte at 0x1E (the dummy byte): the planted value
    must make that visible."""
    lua, reads, ram, planted, prof, lprof = hg_world(lua_reads)
    bad = copy.deepcopy(prof)
    bad["trainer"]["kanto_badges_off"] = 0x1E
    got = py(reads.badges(ram.adapter(lua), to_lua(lua, bad)))
    assert got["kanto"] != PLANTED_KANTO


# -- the probe dump -------------------------------------------------------------------------
def test_probe_dump_confirms_the_embedded_array_table_and_codec_layout():
    if not PROBE_DUMP.is_file():
        pytest.skip(f"probe dump not found: {PROBE_DUMP}")
    d = PROBE_DUMP.read_bytes()
    sv = pack_profile("hg")["save"]
    for i, (size, off) in ARRAY_TABLE.items():
        h = struct.unpack_from("<IIIHH", d, sv["array_headers_off"] + i * sv["array_header_size"])
        assert (h[0], h[1], h[2]) == (i, size, off)
    assert ARRAY_TABLE[41][1] == PC_OFF == struct.unpack_from("<I", d, sv["slot_specs_off"] + 12 + 4)[0]
    assert struct.unpack_from("<I", d, sv["save_counter_off"])[0] == 1
    save = load_save("hg")
    live = d[0x10 : 0x10 + len(save.general)]
    diff = [i for i, (a, b) in enumerate(zip(live, save.general, strict=True)) if a != b]
    assert diff and all(i < 0x90 for i in diff) and len(diff) <= 8, f"unexpected live/file differences {diff}"
    assert d[0x10 + PC_OFF : 0x10 + PC_OFF + len(save.pc)] == save.pc


# -- reads.battle: the zero-hook chain (C1-9 live values) -------------------------------------
# The pack's `battle` block now carries these (hgss + hge); BATTLE_MODEL is the expected-values oracle the
# real pack is asserted against (test_real_pack_battle_block_equals_the_model). SOURCE for each:
# docs/gen4/research/battle_pointer.md (man+0x1C, bs+0x2C, species/level/hp/maxHp) and checkpoint.md section 2
# (outcome byte bs+0x2420, `& 0x3F`), battle_faint_seam.md section 6 (personality +0x68, OTID +0x74).
BATTLE_MODEL = {"man_data_off": 0x1C, "max_battlers": 4, "type_off": 0x2C, "outcome_off": 0x2420,
                "outcome_mask": 0x3F, "species_off": 0x00, "level_off": 0x34, "max_hp_off": 0x50,
                "personality_off": 0x68, "otid_off": 0x74}
# the addresses the C1-9 route report observed live (HG, wild Pidgey L2, Cyndaquil battler 0)
FS, SUB, MAN, BS, CTX = 0x022A01EC, 0x022A0334, 0x022A6B04, 0x022C020C, 0x022C32D8
OWN_PID, FOE_PID, PLAYER_OTID = 0x11111111, 0x1A2B3C4D, 0x0BB83039


def battle_title() -> dict:
    doc = json.loads((ROOT / "data/games/gen4_hgss/profile.json").read_text(encoding="utf-8"))
    return copy.deepcopy(doc["titles"]["heartgold"])


@pytest.mark.parametrize("pack, title", [("hgss", "heartgold"), ("hge", "heartgold_hge")])
def test_real_pack_battle_block_equals_the_model(pack, title):
    b = json.loads((ROOT / f"data/games/gen4_{pack}/profile.json").read_text(encoding="utf-8"))["titles"][title]["profile"]["battle"]
    assert {k: b.get(k) for k in BATTLE_MODEL} == BATTLE_MODEL


FS_CELL = battle_title()["profile"]["fieldsys_ptr"]["address"]


def put_mon(ram, b, species, level, hp, max_hp, pid, otid):
    base = CTX + 0x2D40 + 0xC0 * b
    ram.put(base, struct.pack("<H", species))
    ram.put(base + 0x34, bytes([level]))
    ram.put(base + 0x4C, struct.pack("<iH", hp, max_hp))
    ram.put(base + 0x68, struct.pack("<I", pid))
    ram.put(base + 0x74, struct.pack("<I", otid))


def battle_ram() -> Ram:
    ram = Ram()
    ram.u32_cell(FS_CELL, FS)
    ram.u32_cell(FS + 0, SUB)
    ram.u32_cell(SUB + 4, MAN)
    ram.u32_cell(MAN + 0x0C, 12)
    ram.u32_cell(MAN + 0x1C, BS)
    ram.u32_cell(BS + 0x30, CTX)
    ram.u32_cell(BS + 0x2C, 0)
    ram.put(BS + 0x2420, bytes([0x40 | 4]))                    # raw byte: a flag above the mask + MON_CAUGHT
    ram.put(CTX + 0x219C, bytes([0, 0, 6, 6]))
    put_mon(ram, 0, 155, 5, 20, 20, OWN_PID, PLAYER_OTID)
    put_mon(ram, 1, 16, 2, 13, 13, FOE_PID, 0)
    return ram


def is_ok(res):
    return not isinstance(res, tuple)            # a refusal comes back as (nil, reason)


def read_battle(lua, reads, ram, title=None, boom=False):
    return reads.battle(ram.adapter(lua, boom=boom), to_lua(lua, title if title is not None else battle_title()))


def test_battle_chain_reads_the_c1_9_live_values(lua_reads):
    lua, reads = lua_reads
    ram = battle_ram()
    out = py(read_battle(lua, reads, ram))
    assert out["fingerprint"] == "022A01EC.022A0334.022A6B04.022C020C.022C32D8"
    assert (out["btype"], out["outcome_raw"], out["outcome"]) == (0, 0x44, 4)       # the mask drops the flag bit
    own, foe = out["mons"]
    assert (own["b"], own["species"], own["level"], own["hp"], own["max_hp"], own["slot"]) == (0, 155, 5, 20, 20, 0)
    assert own["key"] == f"{OWN_PID:08X}:{PLAYER_OTID:08X}"
    assert (foe["b"], foe["species"], foe["level"], foe["hp"], foe["max_hp"]) == (1, 16, 2, 13, 13)
    assert foe["pid"] == FOE_PID and foe["otid"] == 0 and len(out["mons"]) == 2      # battlers 2/3 are empty
    assert ram.oob_calls == 0


def test_battle_chain_template_comes_from_the_pack_phase_case_or_the_battle_block(lua_reads):
    lua, reads = lua_reads
    ram = battle_ram()
    title = battle_title()
    assert is_ok(read_battle(lua, reads, ram, title))            # the real pack's battle block states it
    sect = copy.deepcopy(title["profile"])
    del sect["battle"]["template_id"]                            # profile alone, no title predicate: a named gap
    assert read_battle(lua, reads, ram, sect)[1] == "pack_gap:battle.template_id|phase_cases.battle.predicate"
    del title["profile"]["battle"]["template_id"]                # the title's battle phase_case predicate still serves
    assert is_ok(read_battle(lua, reads, ram, title))


def test_battle_pack_gaps_are_named_never_guessed(lua_reads):
    lua, reads = lua_reads
    ram = battle_ram()
    t = battle_title()
    for k in BATTLE_MODEL.keys() - {"man_data_off"}:
        t["profile"]["battle"].pop(k)
    t["profile"]["battle"].pop("man_data_off")
    refused(read_battle(lua, reads, ram, t), "pack_gap:battle.man_data_off")
    for k in BATTLE_MODEL:
        t = battle_title()
        del t["profile"]["battle"][k]
        refused(read_battle(lua, reads, ram, t), "pack_gap:battle." + k)
    t = battle_title()
    t["profile"]["battle"]["hp_width"] = 2                                 # the full-width s32 read is mandatory
    refused(read_battle(lua, reads, ram, t), "pack_gap:battle.hp_width")
    t = battle_title()
    del t["profile"]["fieldsys_ptr"]
    refused(read_battle(lua, reads, ram, t), "pack_gap:fieldsys_ptr")
    pt = to_lua(lua, pack_profile("pt"))                                   # Platinum carries no battle block at all
    assert not is_ok(reads.battle(ram.adapter(lua), pt))


@pytest.mark.parametrize("name, edit, reason", [
    ("wrong template id (another launched app)", lambda r: r.u32_cell(MAN + 0x0C, 7), "not_battle"),
    ("nothing launched", lambda r: r.u32_cell(SUB + 4, 0), "no_app"),
    ("null FieldSystem", lambda r: r.u32_cell(FS_CELL, 0), "null_ptr:fs"),
    ("null sub-struct", lambda r: r.u32_cell(FS, 0), "null_ptr:sub"),
    ("null BattleSystem", lambda r: r.u32_cell(MAN + 0x1C, 0), "null_ptr:bs"),
    ("null context", lambda r: r.u32_cell(BS + 0x30, 0), "null_ptr:ctx"),
    ("FieldSystem out of RAM", lambda r: r.u32_cell(FS_CELL, 0x03000000), "out_of_ram"),
    ("sub-struct out of RAM", lambda r: r.u32_cell(FS, 0x00100000), "out_of_ram"),
    ("manager out of RAM", lambda r: r.u32_cell(SUB + 4, 0x03000010), "out_of_ram"),
    ("BattleSystem out of RAM", lambda r: r.u32_cell(MAN + 0x1C, 0x04000000), "out_of_ram"),
    ("context so near the end its battlers run past RAM", lambda r: r.u32_cell(BS + 0x30, RAM_HI - 0xFFF),
     "out_of_ram"),
    ("BattleSystem not word aligned", lambda r: r.u32_cell(MAN + 0x1C, BS + 2), "bad_ptr:bs"),
    ("manager not word aligned", lambda r: r.u32_cell(SUB + 4, MAN + 1), "bad_ptr:man"),
    ("selectedMonIndex above the sentinel", lambda r: r.put(CTX + 0x219C, bytes([0, 7, 6, 6])), "bad_selected"),
    ("level 0", lambda r: put_mon(r, 0, 155, 0, 20, 20, OWN_PID, PLAYER_OTID), "bad_battler0:level"),
    ("level 101", lambda r: put_mon(r, 1, 16, 101, 13, 13, FOE_PID, 0), "bad_battler1:level"),
    ("hp above maxHp", lambda r: put_mon(r, 1, 16, 2, 14, 13, FOE_PID, 0), "bad_battler1:hp"),
    ("negative hp (stale high half)", lambda r: put_mon(r, 0, 155, 5, -1, 20, OWN_PID, PLAYER_OTID), "bad_battler0:hp"),
    ("maxHp 0", lambda r: put_mon(r, 0, 155, 5, 0, 0, OWN_PID, PLAYER_OTID), "bad_battler0:max_hp"),
    ("species beyond any real id", lambda r: put_mon(r, 1, 0x7FFF, 2, 13, 13, FOE_PID, 0), "bad_battler1:species"),
])
def test_battle_chain_refusals(lua_reads, name, edit, reason):
    lua, reads = lua_reads
    ram = battle_ram()
    edit(ram)
    refused(read_battle(lua, reads, ram), reason)
    assert ram.oob_calls == 0, "a bad pointer reached the bus"


def test_battle_chain_unmapped_bus_and_hole(lua_reads):
    lua, reads = lua_reads
    ram = battle_ram()
    refused(read_battle(lua, reads, ram, boom=True), "unmapped")
    ram.holes.append((CTX + 0x2D40 + 0xC0, CTX + 0x2D40 + 0xC0 + 0xBF))   # battler 1's block unreadable
    refused(read_battle(lua, reads, ram), "unmapped")


def test_battle_slot_sentinel_6_is_no_mon_on_the_field(lua_reads):
    lua, reads = lua_reads
    ram = battle_ram()
    ram.put(CTX + 0x219C, bytes([0, 6, 6, 6]))
    own, foe = py(read_battle(lua, reads, ram))["mons"]
    assert own["slot"] == 0 and foe.get("slot") is None


def test_battle_chain_is_reacquired_every_call_and_the_fingerprint_follows_the_heap(lua_reads):
    lua, reads = lua_reads
    ram = battle_ram()
    first = py(read_battle(lua, reads, ram))["fingerprint"]
    assert py(read_battle(lua, reads, ram))["fingerprint"] == first
    ram.u32_cell(MAN + 0x1C, BS + 0x4000)                    # the next battle's block landed elsewhere
    ram.u32_cell(BS + 0x4000 + 0x30, CTX)
    assert py(read_battle(lua, reads, ram))["fingerprint"] != first
    ram.u32_cell(SUB + 4, 0)                                  # the application ended: no stale chain survives
    refused(read_battle(lua, reads, ram), "no_app")


def test_control_without_the_template_check_another_launched_app_is_read_as_a_battle(lua_reads):
    src = READS.read_text(encoding="utf-8")
    needle = 'if tid ~= t_id then return nil, "not_battle" end'
    assert needle in src
    lua, reads = make_lua(src.replace(needle, ""))
    ram = battle_ram()
    ram.u32_cell(MAN + 0x0C, 7)
    assert is_ok(read_battle(lua, reads, ram))        # reverted module accepts the bag/party app: bug caught


def test_control_without_the_alignment_guard_a_misaligned_pointer_is_followed(lua_reads):
    src = READS.read_text(encoding="utf-8")
    needle = 'if v & 3 ~= 0 then return nil, "bad_ptr:" .. name end'
    assert needle in src
    lua, reads = make_lua(src.replace(needle, ""))
    ram = battle_ram()
    ram.u32_cell(MAN + 0x1C, BS + 2)
    assert not (isinstance(r := read_battle(lua, reads, ram), tuple) and r[1] == "bad_ptr:bs")     # reverted module dereferences the garbage pointer
