"""P3a Polished Lua foundation: the generated profile (tools/gen_polished_profile.py), lua/gen2/polished.lua's
reads + party/foe entries against server/adapters/polished_codec.py, and lua/gen2/entry.lua's title detection
and DEV admission (the exact overlay sha1 only; clean release and anything else refused; vanilla untouched)."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
from pathlib import Path

import pytest

from server.adapters import polished_codec as pc
from server.adapters.gen2_polished import Gen2PolishedAdapter

lupa = pytest.importorskip("lupa")

REPO = Path(__file__).resolve().parents[2]
ROOT = str(REPO).replace("\\", "/")
PROFILE = json.loads((REPO / "data/games/polished_crystal/profile.json").read_text(encoding="utf-8"))
P = PROFILE["titles"]["polished"]
CLEAN_ROM = Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache/polished/release/polishedcrystal-3.2.3.gbc"


def _pair(result):
    return result if isinstance(result, tuple) else (result, None)


@pytest.fixture(scope="module")
def lua():
    return lupa.LuaRuntime(unpack_returned_tuples=True)


@pytest.fixture(scope="module")
def polished(lua):
    return lua.eval(f'dofile("{ROOT}/lua/gen2/polished.lua")')


@pytest.fixture(scope="module")
def entry(lua):
    return lua.eval(f'dofile("{ROOT}/lua/gen2/entry.lua")')


# ── profile ──────────────────────────────────────────────────────────────────

def _sym():
    rows = re.findall(r"^([0-9a-f]{2}):([0-9a-f]{4}) (\S+)$",
                      (REPO / "data/polished/polished_slink.sym").read_text(encoding="utf-8"), re.M)
    return {name: (int(bank, 16), int(addr, 16)) for bank, addr, name in rows}


def test_every_profile_address_is_the_overlay_sym():
    sym = _sym()
    for name, address in P["ram"].items():
        assert sym[name] == (P["ram_bank"][name], address), name
    assert P["overlay"]["ram"]["wSlinkMailbox"] == sym["wSlinkMailbox"][1] == 0xC60B
    assert P["overlay"]["abi"] == 3 and P["overlay"]["rom_sha1"] == PROFILE["source"]["overlay_sha1"]


def test_profile_pins_the_overlay_build():
    prov = json.loads((REPO / "data/polished/overlay_provenance.json").read_text(encoding="utf-8"))
    src = PROFILE["source"]
    assert src["overlay_sha1"] == prov["output"]["sha1"] and src["rom_sha1"] == prov["base_sha1"]
    assert src["overlay_sym_sha256"] == prov["symbols"]["polished_slink.sym"]
    assert src["lock_sha256"] == hashlib.sha256((REPO / "data/polished_sources.lock.json").read_bytes()).hexdigest()


def test_struct_offsets_agree_with_the_codec():
    assert {k: P["structs"]["party"][k] for k in pc.PARTY} == pc.PARTY
    battle = P["structs"]["battle"]
    assert (battle["Form"], battle["PP"], battle["HP"], battle["Type1"], battle["StructEnd"]) == (10, 11, 19, 33, 35)


# ── reads over a synthetic WRAM image laid out per the profile ──────────────

class Wram:
    def __init__(self, lua):
        self.lua, self.mem = lua, {}

    def put(self, name, data, offset=0):
        base = P["ram"][name] + offset
        for i, value in enumerate(data):
            self.mem[base + i] = value

    def io(self):
        read = lambda address, length, domain: self.lua.table_from(  # noqa: E731
            [self.mem.get(int(address) + i, 0) for i in range(int(length))])
        wrap = self.lua.eval("function(f) return function(...) return f(...) end end")  # a real Lua function
        return self.lua.table_from({"read_range": wrap(read), "bank_valid": wrap(lambda bank, address, length: True)})


def _decoder(lua):
    charmap = lua.eval(f'dofile("{ROOT}/data/games/polished_crystal/charmap.lua")')
    scanner = lua.eval(f'dofile("{ROOT}/lua/token_scanner.lua")')
    return scanner.new(lua.table_from({"glyphs": charmap.glyphs, "terminator": charmap.terminator,
                                       "max_length": 11, "unknown": lua.eval("function() return \"?\" end")}))


def _profile(lua):
    return lua.eval('function(root) local P = dofile(root .. "/lua/gen2/polished.lua") '
                    'return P.load(root, dofile(root .. "/lua/json_codec.lua")) end')(ROOT)[0]


def _mon(rng, species, *, egg=False):
    return {"species_id": species, "form": rng.randrange(32), "gender": rng.choice(["male", "female"]),
            "is_egg": egg, "shiny": rng.random() < .5, "ability_slot": rng.randrange(4), "nature": rng.randrange(25),
            "held_item": rng.choice([0, 1]), "moves": [rng.randrange(256) for _ in range(4)],  # item: none/Poke Ball
            "ot_id": rng.randrange(65536), "exp": rng.randrange(1 << 24),
            "evs": {n: rng.randrange(256) for n in pc.STAT_NAMES},
            "dvs": {n: rng.randrange(16) for n in pc.STAT_NAMES},
            "pp": [rng.randrange(64) for _ in range(4)], "pp_ups": [rng.randrange(4) for _ in range(4)],
            "happiness": rng.randrange(256), "pokerus": rng.randrange(256), "caught_data": rng.randrange(256),
            "caught_level": rng.randrange(256), "caught_location": rng.randrange(256), "level": rng.randrange(1, 101),
            "status": rng.randrange(256), "unused": rng.randrange(256), "hp": rng.randrange(1000),
            "max_hp": rng.randrange(1000), "stats": {n: rng.randrange(1000) for n in pc.STAT_NAMES[1:]}}


FIELDS = ("species_id", "form", "gender", "is_egg", "shiny", "ability_slot", "nature", "held_item", "ot_id", "exp",
          "dv_bytes", "happiness", "pokerus", "caught_data", "caught_level", "caught_location", "level", "status",
          "unused", "hp", "max_hp", "raw_hex", "ot_raw_hex", "nickname_raw_hex", "ot_name", "nickname")


def _party(lua, mons, names):
    wram = Wram(lua)
    wram.put("wPartyCount", [len(mons)])
    raws = []
    for slot, (mon, (ot, nick)) in enumerate(zip(mons, names, strict=True)):
        raw, ot_raw, nick_raw = pc.encode_party_mon(mon), pc.encode_text(ot, 8) + bytes([1, 2, 3]), pc.encode_text(nick, 11)
        wram.put("wPartyMons", raw, slot * 48)
        wram.put("wPartyMonOTs", ot_raw, slot * 11)
        wram.put("wPartyMonNicknames", nick_raw, slot * 11)
        raws.append((raw, ot_raw, nick_raw))
    return wram, raws


def test_party_decodes_exactly_like_the_codec(lua, polished):
    rng = random.Random(7)
    mons = [_mon(rng, 25), _mon(rng, 291), _mon(rng, 1)]
    wram, raws = _party(lua, mons, [("KRIS", "PIKA"), ("LYRA", "APE"), ("GOLD", "BULBASAURXX")])
    reads = _pair(polished.new(_profile(lua), wram.io(), _decoder(lua)))[0]
    party, why = _pair(reads.read_party())
    assert why is None and party.count == 3
    adapter = Gen2PolishedAdapter()
    for slot, (raw, ot_raw, nick_raw) in enumerate(raws):
        got = party.mons[slot + 1]
        want = pc.decode_party_mon(raw, ot=ot_raw, nickname=nick_raw)
        for field in FIELDS:
            assert got[field] == want[field], (slot, field)
        assert list(got.moves.values()) == want["moves"] and list(got.pp.values()) == want["pp"]
        assert list(got.pp_ups.values()) == want["pp_ups"]
        assert dict(got.evs.items()) == want["evs"] and dict(got.dvs.items()) == want["dvs"]
        assert dict(got.stats.items()) == want["stats"]
        assert got.key == pc.key(want) == polished.mon_key(got)
        entry, why = _pair(polished.party_entry(got, 1, lua.table_from([6, 7, 5, 6, 6, 12, 0])))
        assert why is None and entry.key == got.key and entry.species_id == want["species_id"]
        assert pc.decode_party_blob(bytes.fromhex(entry.blob_hex))["raw_hex"] == raw.hex()
        assert adapter.validate_party_blob(entry.blob_hex, key=entry.key)
        assert entry.active == (slot == 1) and (entry.stat_stages is not None) == (slot == 1)


def test_an_egg_is_decoded_but_has_no_party_entry(lua, polished):
    wram, _ = _party(lua, [_mon(random.Random(1), 25, egg=True)], [("KRIS", "EGG")])
    reads = _pair(polished.new(_profile(lua), wram.io(), _decoder(lua)))[0]
    mon = reads.read_party().mons[1]
    assert mon.is_egg and mon.species_id == 25
    assert _pair(polished.party_entry(mon))[0] is None


def test_bad_records_are_refused(lua, polished):
    rng = random.Random(2)
    wram, _ = _party(lua, [_mon(rng, 25)], [("KRIS", "PIKA")])
    wram.put("wPartyMons", [0], 31)                       # level 0
    reads = _pair(polished.new(_profile(lua), wram.io(), _decoder(lua)))[0]
    assert "level" in _pair(reads.read_party())[1]
    wram.put("wPartyCount", [7])
    assert "count" in _pair(reads.read_party())[1]


def test_battle_mon_and_stages(lua, polished):
    rng = random.Random(4)
    raw = bytearray(rng.randrange(256) for _ in range(35))
    b = P["structs"]["battle"]
    raw[b["Species"]], raw[b["Form"]], raw[b["Level"]] = 0x23, 0x20 | 3, 42      # species 291, form 3
    raw[b["HP"]:b["HP"] + 2], raw[b["PP"]] = (300).to_bytes(2, "big"), 0x85
    wram = Wram(lua)
    wram.put("wEnemyMon", raw)
    wram.put("wEnemyMonNickname", pc.encode_text("APE", 11))
    wram.put("wPlayerStatLevels", [7, 8, 6, 13, 1, 7, 7, 0])
    reads = _pair(polished.new(_profile(lua), wram.io(), _decoder(lua)))[0]
    mon, why = _pair(reads.read_battle_mon("enemy"))
    assert why is None and (mon.species_id, mon.form, mon.level, mon.hp, mon.nickname) == (291, 3, 42, 300, "APE")
    assert (mon.pp[1], mon.pp_ups[1]) == (5, 2)
    assert polished.foe_entry(mon).species_id == 291
    stages = reads.read_stat_stages("player")
    assert list(stages.wire.values()) == [6, 7, 5, 12, 0, 6, 6]


def test_pocket_and_player(lua, polished):
    wram = Wram(lua)
    wram.put("wNumBalls", [2, 1, 5, 3, 99, 0xFF])
    wram.put("wPlayerID", [0x12, 0x34])
    wram.put("wPlayerName", pc.encode_text("KRIS", 11))
    reads = _pair(polished.new(_profile(lua), wram.io(), _decoder(lua)))[0]
    balls = reads.read_pocket("balls")
    assert [(e.id, e.quantity) for e in balls.entries.values()] == [(1, 5), (3, 99)]
    player = reads.read_player()
    assert (player.ot_id, player.player_name) == (0x1234, "KRIS")


def test_the_shared_panel_binder_finds_the_mailbox_through_the_profile(lua):
    """lua/gen2/panel.lua reads profile.overlay.ram (wSlinkMailbox $C60B); the Polished service writes the same
    ABI 3 signature: 'SLNK', version at +4, the init cookie $A5 at +31 (patch/polished/src/slink.asm)."""
    mem = {}
    io = lua.table_from({"read_u8": lua.eval("function(f) return function(a) return f(a) end end")(
        lambda a: mem.get(int(a), 0)), "framecount": lua.eval("function() return 0 end")})
    panel_mod = lua.eval(f'dofile("{ROOT}/lua/gen2/panel.lua")')
    permit = lua.eval(f'dofile("{ROOT}/lua/write_permit.lua")')
    charmap = lua.eval(f'dofile("{ROOT}/data/games/polished_crystal/charmap.lua")')
    sanitize = lua.eval("function(s) return s end")
    panel = _pair(panel_mod.new(_profile(lua), charmap, io, panel_mod.writes(io, permit), sanitize))[0]
    assert panel is not None and panel.companion_abi(panel) is None          # no service bytes: ABSENT
    base = 0xC60B
    mem.update({base: 0x53, base + 1: 0x4C, base + 2: 0x4E, base + 3: 0x4B, base + 4: 3, base + 31: 0xA5})
    assert panel.companion_abi(panel) == 3


# ── entry: detection + dev admission ─────────────────────────────────────────

def _header(text: str) -> bytes:
    image = bytearray(0x8000)
    image[0x134:0x134 + len(text)] = text.encode("ascii")
    return bytes(image)


@pytest.mark.parametrize("header,title", [("PM_CRYSTAL", "crystal"), ("POKEMON_GLD", "gold"),
                                          ("POKEMON_SLV", "silver"), ("PKPCRYSTAL", "polished"),
                                          ("AP_CRYSTAL", None), ("POKEMON RED", None)])
def test_title_detection(entry, header, title):
    rom = _header(header)
    assert _pair(entry.detect_title(lambda a: rom[int(a)]))[0] == title


def _admit(lua, entry, rom, title="polished"):
    deps = lua.table_from({"root": ROOT, "rom_size": len(rom), "read_rom_u8": lambda a: rom[int(a)], "title": title})
    return _pair(entry.admit_polished(deps)), _pair(entry.build(deps))


def test_a_random_polished_header_is_refused(lua, entry):
    rom = bytearray(random.Random(5).randbytes(0x8000))
    rom[0x134:0x13E] = b"PKPCRYSTAL"
    (decision, why), (built, build_why) = _admit(lua, entry, bytes(rom))
    assert decision is None and "unknown artifact SHA-1" in why
    assert built is None and "unknown artifact SHA-1" in build_why


def test_a_dev_title_never_composes_a_vanilla_pack(lua, entry):
    deps = lua.table_from({"root": ROOT, "title": "polished", "candidate_only": True, "io": lua.table()})
    assert "dev title" in _pair(entry.build_candidate(deps))[1]


def _real():
    if not CLEAN_ROM.is_file():
        pytest.skip("pinned Polished release ROM absent")
    from patch.tools.make_ups import ups_apply
    clean = CLEAN_ROM.read_bytes()
    assert hashlib.sha1(clean).hexdigest() == PROFILE["source"]["rom_sha1"], "Polished release ROM is not the pin"
    return clean, ups_apply(clean, (REPO / "patch/dist/SLink-Polished.ups").read_bytes())


def test_the_overlay_is_admitted_and_the_clean_release_refused(lua, entry):
    clean, overlay = _real()
    (decision, why), (built, build_why) = _admit(lua, entry, overlay)
    assert why is None and (decision.kind, decision.title, decision.rom_type) == ("overlay", "polished", "polished_crystal")
    assert decision.rom_sha1 == PROFILE["source"]["overlay_sha1"]
    assert built is None and "not wired" in build_why
    (decision, why), (built, build_why) = _admit(lua, entry, clean)
    assert decision is None and "companion patch" in why and built is None and "companion patch" in build_why
    # the vanilla production gate never admits the Polished overlay
    deps = lua.table_from({"root": ROOT, "rom_size": len(overlay), "read_rom_u8": lambda a: overlay[int(a)]})
    assert "unknown artifact SHA-1" in _pair(entry.admit(deps))[1]
