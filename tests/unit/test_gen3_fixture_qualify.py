"""Falsifiers for tools/gen3_fixtures.py.

Synthetic flash images built the same way tests/unit/test_gen3_flash_layout.py
builds them: no ROM, no real save, no emulator. Committed-fixture assertions
read tests/fixtures/gen3/*.sav directly.
"""

import glob
import hashlib
import os
import sys

import pytest

from server.adapters import gen3_codec as codec

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import gen3_fixtures as fx  # noqa: E402  (tools/ is not a package; the tool is a script)

FIXTURES_DIR = os.path.join(REPO, "tests", "fixtures", "gen3")


def _blocks(seed: int) -> dict:
    return {
        "sb2": bytearray((seed + i) & 0xFF for i in range(codec.SAVEBLOCK2_SIZE)),
        "sb1": bytearray(codec.SAVEBLOCK1_SIZE),
        "storage": bytearray(codec.STORAGE_SIZE),
    }


def _mon(personality: int, ot_id: int, ot_name: str, *, party: bool) -> dict:
    mon = {
        "personality": personality, "ot_id": ot_id,
        "nickname": "MON", "language": 2,
        "is_bad_egg": 0, "has_species": 1, "is_egg_flag": 0,
        "block_box_rs": 0, "flags_unused": 0,
        "ot_name": ot_name, "markings": 0, "unknown": 0,
        "species": 1, "held_item": 0, "experience": 100,
        "pp_bonuses": 0, "friendship": 0, "growth_filler": 0,
        "moves": [1, 2, 3, 4], "pp": [10, 10, 10, 10],
        "evs": {"hp": 0, "attack": 0, "defense": 0, "speed": 0,
                "sp_attack": 0, "sp_defense": 0},
        "contest": [0, 0, 0, 0, 0, 0],
        "pokerus": 0, "met_location": 0, "met_level": 5,
        "met_game": 1, "pokeball": 1, "ot_gender": 0,
        "ivs": {"hp": 1, "attack": 1, "defense": 1,
                "speed": 1, "sp_attack": 1, "sp_defense": 1},
        "is_egg": 0, "ability_num": 0, "ribbons": 0,
    }
    if party:
        mon.update({"status": 0, "level": 5, "mail": 0xFF, "hp": 20,
                    "max_hp": 20, "attack": 10, "defense": 10, "speed": 10,
                    "sp_attack": 10, "sp_defense": 10})
    return mon


def _build_image(trainer_name="RED", trainer_id=0x1234, *, party_mons=None,
                  box_mons=None, counter=1, rotation=0) -> bytes:
    """One qualifying single-slot vanilla flash image (counter 1, so it lands
    in slot 1 i.e. physical sectors 14-27; matches HandleWriteSector's
    ``counter % 2`` slot rule)."""
    blocks = _blocks(0)
    blocks["sb2"][0:7] = codec.encode_name(trainer_name, 7)
    blocks["sb2"][0xA:0xE] = trainer_id.to_bytes(4, "little")
    blocks["sb1"][codec.SB1_PARTY_COUNT_OFFSET] = len(party_mons or [])
    for i, mon in enumerate(party_mons or []):
        start = codec.SB1_PARTY_OFFSET + i * codec.PARTY_MON_SIZE
        blocks["sb1"][start:start + codec.PARTY_MON_SIZE] = codec.encode_party_mon(mon)
    for (box, slot), mon in (box_mons or {}).items():
        idx = box * codec.MONS_PER_BOX + slot
        start = codec.BOX_DATA_OFFSET + idx * codec.BOX_MON_SIZE
        blocks["storage"][start:start + codec.BOX_MON_SIZE] = codec.encode_box_mon(mon)

    layout = codec.slot_layout()
    image = bytearray(codec.FLASH_SIZE)
    half = codec.NUM_SECTORS_PER_SLOT * (counter % codec.NUM_SAVE_SLOTS)
    for entry in layout:
        sid = entry["id"]
        chunk = bytes(blocks[entry["object"]])[entry["offset"]:entry["offset"] + entry["size"]]
        physical = half + (rotation + sid) % codec.NUM_SECTORS_PER_SLOT
        image[physical * codec.SECTOR_SIZE:(physical + 1) * codec.SECTOR_SIZE] = \
            codec.write_sector(chunk, sid, counter, layout)
    return bytes(image)


# --- committed fixtures -----------------------------------------------------

def _committed_fixtures():
    return sorted(glob.glob(os.path.join(FIXTURES_DIR, "*.sav")))


@pytest.mark.parametrize("path", _committed_fixtures() or [None])
def test_committed_fixtures_qualify(path):
    if path is None:
        pytest.skip("no fixtures committed yet")
    with open(path, "rb") as f:
        data = f.read()
    assert len(data) == codec.FLASH_SIZE == 131072
    is_rr = "rr_" in os.path.basename(path)
    result = fx.qualify_one(data, rr=is_rr)
    assert result["ok"], result["message"]


# --- firered_party_{battle,town}[_b].sav (card gen3-P4-C4-F) ----------------

def _fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES_DIR, name), "rb") as f:
        return f.read()


@pytest.mark.parametrize("name", [
    "firered_party_battle.sav", "firered_party_battle_b.sav",
    "firered_party_town.sav", "firered_party_town_b.sav",
])
def test_fr_party_fixtures_have_a_fully_healed_two_mon_party(name):
    """firered_town.sav is pre-starter (party 0); these four are the only committed FR fixtures
    with a party at all, all built from the same route1_catch state (starter + one Route 1
    catch). The coordinator's own requirement (card gen3-P4-C4-F, 2026-09-23): every duo
    scenario these feed (faint_cmd, linked_faint_active, boxsync, whiteout) assumes a HEALTHY
    party, not merely a non-fainted one -- hp must equal max_hp for both mons."""
    data = _fixture(name)
    result = fx.qualify_one(data, rr=False)
    assert result["ok"], result["message"]
    assert len(result["party"]) == 2
    mons = codec.party_from_save(data, rr=False)
    assert len(mons) == 2
    for m in mons:
        assert m["hp"] == m["max_hp"], f"species {m['species']}: hp {m['hp']}/{m['max_hp']}"


@pytest.mark.parametrize("a_name,b_name", [
    ("firered_party_battle.sav", "firered_party_battle_b.sav"),
    ("firered_party_town.sav", "firered_party_town_b.sav"),
])
def test_fr_party_b_variant_matches_species_and_position_with_a_distinct_trainer(a_name, b_name):
    """derive_b's own contract (test_derive_b_changes_exactly_the_manifested_fields): OT
    identity changes; the owned party's species/order does not. Added 2026-09-23 (duo-harness
    finding d146b992): derive_b must ALSO never move the player -- SaveBlock1's pos (+0x00/+0x02)
    and map (+0x04/+0x05) are outside every field derive_b's own manifest ever names, so an A/B
    pair must read the identical map and tile."""
    a_body, b_body = _fixture(a_name), _fixture(b_name)
    ra, rb = fx.qualify_one(a_body, rr=False), fx.qualify_one(b_body, rr=False)
    assert ra["ok"] and rb["ok"]
    assert len(ra["party"]) == len(rb["party"]) == 2
    assert [m["species"] for m in ra["party"]] == [m["species"] for m in rb["party"]]
    assert ra["trainer_id"] != rb["trainer_id"]
    assert ra["trainer_name"] != rb["trainer_name"]
    pa, pb = codec.parse_flash(a_body), codec.parse_flash(b_body)
    assert pa["sb1"][0:6] == pb["sb1"][0:6], (
        f"{a_name} and {b_name} must stand at the same map/tile; derive_b never patches position")


def test_fr_party_battle_and_town_share_trainer_and_party_at_different_positions():
    """town is cold-booted from battle's own healed output and walked to Viridian with scripted
    normal inputs (lua/tests/gen3_fixture_from_state.lua, PHYSICAL 2026-09-23 -- see the
    README's provenance note): same trainer and same party species/levels, but a DIFFERENT
    SaveBlock1 map/position -- town is an independent in-game save, not a byte patch, so no
    byte-identity is asserted past that."""
    battle, town = _fixture("firered_party_battle.sav"), _fixture("firered_party_town.sav")
    rb, rt = fx.qualify_one(battle, rr=False), fx.qualify_one(town, rr=False)
    assert rb["ok"] and rt["ok"]
    assert rb["trainer_id"] == rt["trainer_id"]
    assert [m["species"] for m in rb["party"]] == [m["species"] for m in rt["party"]]
    assert [m["level"] for m in rb["party"]] == [m["level"] for m in rt["party"]]
    pb, pt = codec.parse_flash(battle), codec.parse_flash(town)
    assert pb["sb1"][0:6] != pt["sb1"][0:6], "town must stand somewhere other than battle's tile"


# --- import: RTC-suffix strip -----------------------------------------------

def test_import_strips_optional_rtc_suffix(tmp_path):
    body = _build_image()
    rtc = bytes(range(16))
    src = tmp_path / "with_rtc.SaveRAM"
    src.write_bytes(body + rtc)
    imported = fx.import_savedata(src.read_bytes(), rr=False)
    assert imported == body
    assert len(imported) == codec.FLASH_SIZE


def test_import_refuses_blank_save(tmp_path):
    blank = b"\xFF" * codec.FLASH_SIZE
    with pytest.raises(ValueError, match="blank"):
        fx.import_savedata(blank, rr=False)


# --- torn save refusal -------------------------------------------------------

def test_import_refuses_torn_save():
    image = bytearray(_build_image(counter=1))
    # Corrupt one sector's checksum in the selected slot -> torn/incomplete.
    half = codec.NUM_SECTORS_PER_SLOT * (1 % codec.NUM_SAVE_SLOTS)
    off = half * codec.SECTOR_SIZE + codec.OFF_SECTOR_CHECKSUM
    image[off] ^= 0xFF
    with pytest.raises(ValueError, match="qualify_flash refused"):
        fx.import_savedata(bytes(image), rr=False)


# --- derive-b: exact manifest, re-qualifies ---------------------------------

def test_derive_b_changes_exactly_the_manifested_fields():
    owned = _mon(0x1111, 0x1234, "RED", party=True)
    foreign = _mon(0x2222, 0x9999, "BLU", party=False)  # traded-mon provenance
    image_a = _build_image(trainer_name="RED", trainer_id=0x1234,
                            party_mons=[owned], box_mons={(0, 0): foreign})
    ok, msg = codec.qualify_flash(image_a)
    assert ok, msg

    image_b, manifest = fx.derive_b(image_a)
    assert len(image_b) == codec.FLASH_SIZE
    ok, msg = codec.qualify_flash(image_b)
    assert ok, msg

    # Manifest names sb2 identity + the one owned party mon; the foreign
    # box mon (different OTID) must NOT be in the manifest or changed.
    joined = "\n".join(manifest)
    assert "playerTrainerId" in joined
    assert "playerName" in joined
    assert "party[0]" in joined
    assert "box[0][0]" not in joined

    parsed_a, parsed_b = codec.parse_flash(image_a), codec.parse_flash(image_b)
    assert parsed_b["storage"] == parsed_a["storage"]  # foreign box mon untouched

    old_name, old_tid = fx._trainer_identity(parsed_a["sb2"])
    new_name, new_tid = fx._trainer_identity(parsed_b["sb2"])
    assert new_tid != old_tid
    assert new_name != old_name

    mon_a = codec.decode_party_mon(
        parsed_a["sb1"][codec.SB1_PARTY_OFFSET:codec.SB1_PARTY_OFFSET + codec.PARTY_MON_SIZE])
    mon_b = codec.decode_party_mon(
        parsed_b["sb1"][codec.SB1_PARTY_OFFSET:codec.SB1_PARTY_OFFSET + codec.PARTY_MON_SIZE])
    assert mon_b["ot_id"] == new_tid
    assert mon_b["species"] == mon_a["species"]  # unrelated payload preserved
    assert mon_b["checksum_ok"] is True


@pytest.fixture(scope="module")
def rr_source():
    with open(os.path.join(FIXTURES_DIR, "rr_town.sav"), "rb") as f:
        data = f.read()
    assert hashlib.sha256(data).hexdigest() == (
        "b4b991f623c969eeb5c3d06ef54ef2da73cda62b4759a2c730aece7c18def9a3")
    return data


def _rr_regions(image):
    parsed = codec.parse_flash(image, cfru=True)
    return parsed, {
        codec.RR_SAVEBLOCK2_ADDR: bytearray(parsed["sb2"]),
        codec.RR_SAVEBLOCK1_ADDR: bytearray(parsed["sb1"]),
        codec.RR_STORAGE_ADDR: bytearray(parsed["storage"]),
        codec.RR_EXT_ADDR: bytearray(b"".join(
            image[s * codec.SECTOR_SIZE:s * codec.SECTOR_SIZE + codec.CHUNK_SIZE_CFRU]
            for s in codec.RR_EXT_SECTORS)),
    }


def _rr_populate_all_boxes(image):
    """Seed every box in the real image in memory; no derived fixture is written.

    rr_save_layout.md:91-100 / codec:688-695: boxes span storage, SB1, SB2,
    and the FF0-payload extension (including the sector-30/31 straddle).
    """
    parsed, regions = _rr_regions(image)
    old_name, old_tid = fx._trainer_identity(parsed["sb2"])
    foreign_tid = old_tid ^ 0x12345678
    sb1 = regions[codec.RR_SAVEBLOCK1_ADDR]
    # A foreign party member must retain its full provenance too.
    mon = bytearray(sb1[codec.SB1_PARTY_OFFSET:codec.SB1_PARTY_OFFSET + codec.PARTY_MON_SIZE])
    mon[0:4] = (0xABCD5678).to_bytes(4, "little")
    mon[4:8] = foreign_tid.to_bytes(4, "little")
    mon[0x14:0x1B] = codec.encode_name("FOREIGN", 7)
    start = codec.SB1_PARTY_OFFSET + codec.PARTY_MON_SIZE
    sb1[start:start + codec.PARTY_MON_SIZE] = mon
    sb1[codec.SB1_PARTY_COUNT_OFFSET] = 2
    for box, address in enumerate(codec.RR_BOX_BASES):
        base = next(base for base, raw in regions.items()
                    if base <= address and address + codec.RR_BOX_STRIDE <= base + len(raw))
        for slot in range(codec.MONS_PER_BOX):
            # Both party and compressed headers use OTID +4 / OT-name +14;
            # growth starts at +1C in the packed 3A record (codec:344-362).
            raw = bytearray(codec.COMPRESSED_MON_SIZE)
            raw[0:4] = (0x1000 + box * 30 + slot).to_bytes(4, "little")
            owned = slot % 2 == 0
            raw[4:8] = (old_tid if owned else foreign_tid).to_bytes(4, "little")
            raw[8:18] = codec.encode_name("BOXMON", 10)
            raw[18:20] = b"\x02\x02"
            raw[0x14:0x1B] = codec.encode_name(old_name if owned else "FOREIGN", 7)
            raw[0x1C:0x1E] = (277).to_bytes(2, "little")
            off = address - base + slot * codec.COMPRESSED_MON_SIZE
            regions[base][off:off + codec.COMPRESSED_MON_SIZE] = raw
    result = bytearray(image)
    bases = {"sb2": codec.RR_SAVEBLOCK2_ADDR, "sb1": codec.RR_SAVEBLOCK1_ADDR,
             "storage": codec.RR_STORAGE_ADDR}
    half = parsed["slot"] * codec.NUM_SECTORS_PER_SLOT
    for s in parsed["sectors"][half:half + codec.NUM_SECTORS_PER_SLOT]:
        e = codec.rr_slot_layout()[s["id"]]
        start = s["index"] * codec.SECTOR_SIZE
        chunk = regions[bases[e["object"]]][e["offset"]:e["offset"] + e["size"]]
        result[start:start + e["size"]] = chunk
        checksum = codec.sector_checksum(bytes(chunk), e["size"])
        result[start + codec.OFF_SECTOR_CHECKSUM:start + codec.OFF_SECTOR_CHECKSUM + 2] = \
            checksum.to_bytes(2, "little")
    for n, s in enumerate(codec.RR_EXT_SECTORS):
        start = s * codec.SECTOR_SIZE
        result[start:start + codec.CHUNK_SIZE_CFRU] = regions[codec.RR_EXT_ADDR][
            n * codec.CHUNK_SIZE_CFRU:(n + 1) * codec.CHUNK_SIZE_CFRU]
    return bytes(result)


def _assert_rr_identity_only(before, after):
    """Independent whole-image byte whitelist; preserves parasite/footer/RTC too."""
    parsed = codec.parse_flash(before, cfru=True)
    new = codec.parse_flash(after, cfru=True)
    old_name, old_tid = fx._trainer_identity(parsed["sb2"])
    new_name, new_tid = fx._trainer_identity(new["sb2"])
    assert new_tid == old_tid ^ 0xFFFFFFFF and new_name != old_name
    assert (new["slot"], new["counter"], new["rotation"]) == (
        parsed["slot"], parsed["counter"], parsed["rotation"])
    allowed_ram = set(range(codec.RR_SAVEBLOCK2_ADDR, codec.RR_SAVEBLOCK2_ADDR + 7))
    allowed_ram.update(range(codec.RR_SAVEBLOCK2_ADDR + 0xA, codec.RR_SAVEBLOCK2_ADDR + 0xE))
    addresses = [codec.RR_SAVEBLOCK1_ADDR + codec.SB1_PARTY_OFFSET + i * codec.PARTY_MON_SIZE
                 for i in range(len(codec.rr_party_from_save(before)))]
    addresses += [base + i * codec.COMPRESSED_MON_SIZE for base in codec.RR_BOX_BASES
                  for i in range(codec.MONS_PER_BOX)]
    old_mons = codec.rr_party_from_save(before) + [m for b in codec.rr_boxes_from_save(before) for m in b]
    new_mons = codec.rr_party_from_save(after) + [m for b in codec.rr_boxes_from_save(after) for m in b]
    owned_count = 0
    for address, old, changed in zip(addresses, old_mons, new_mons, strict=True):
        if old["species"] and old["ot_id"] == old_tid:
            owned_count += 1
            assert changed["ot_id"] == new_tid and changed["ot_name"] == new_name
            excluded = {"ot_id", "ot_name", "ot_name_raw"}
            assert {k: v for k, v in changed.items() if k not in excluded} == {
                k: v for k, v in old.items() if k not in excluded}
            allowed_ram.update(range(address + 4, address + 8))
            allowed_ram.update(range(address + 0x14, address + 0x1B))
        else:
            assert changed == old
    assert owned_count > 0  # real fixture has one owned party mon; boxes may be empty
    allowed_file = set()
    bases = {"sb2": codec.RR_SAVEBLOCK2_ADDR, "sb1": codec.RR_SAVEBLOCK1_ADDR,
             "storage": codec.RR_STORAGE_ADDR}
    half = parsed["slot"] * codec.NUM_SECTORS_PER_SLOT
    for s in parsed["sectors"][half:half + codec.NUM_SECTORS_PER_SLOT]:
        e = codec.rr_slot_layout()[s["id"]]
        start = s["index"] * codec.SECTOR_SIZE
        ram = bases[e["object"]] + e["offset"]
        allowed_file.update(start + a - ram for a in allowed_ram if ram <= a < ram + e["size"])
        allowed_file.update((start + codec.OFF_SECTOR_CHECKSUM, start + codec.OFF_SECTOR_CHECKSUM + 1))
        assert codec.read_sector(after, s["index"], codec.rr_slot_layout())["checksum_ok"]
    for n, s in enumerate(codec.RR_EXT_SECTORS):
        ram = codec.RR_EXT_ADDR + n * codec.CHUNK_SIZE_CFRU
        allowed_file.update(s * codec.SECTOR_SIZE + a - ram for a in allowed_ram
                            if ram <= a < ram + codec.CHUNK_SIZE_CFRU)
    assert len(before) == len(after)
    assert all(a == b or i in allowed_file for i, (a, b) in enumerate(zip(before, after, strict=True)))
    assert codec.qualify_flash(after, cfru=True) == (True, "ok")


def test_derive_b_rr_real_fixture_rekeys_and_preserves_every_other_byte(rr_source):
    result, manifest = fx.derive_b(rr_source, rr=True)
    _assert_rr_identity_only(rr_source, result)
    report = fx.qualify_one(result, rr=True)
    assert report["ok"] and report["boxes"] == 0
    assert "party[0]" in "\n".join(manifest)
    assert "inactive rotating slot preserved" in "\n".join(manifest)


def test_derive_b_rr_all_box_regions_and_foreign_party_are_preserved(rr_source):
    source = _rr_populate_all_boxes(rr_source)
    assert fx.qualify_one(source, rr=True)["boxes"] == 750
    result, manifest = fx.derive_b(source, rr=True)
    _assert_rr_identity_only(source, result)
    assert sum(line.startswith("box[") for line in manifest) == 375
    assert not any(line.startswith("party[1]") for line in manifest)
    assert fx.qualify_one(result, rr=True)["boxes"] == 750


def test_derive_b_rr_preserves_optional_rtc_suffix(rr_source):
    source = rr_source + bytes(range(codec.RTC_SUFFIX_SIZE))
    result, _ = fx.derive_b(source, rr=True)
    _assert_rr_identity_only(source, result)
    assert result[-codec.RTC_SUFFIX_SIZE:] == source[-codec.RTC_SUFFIX_SIZE:]


def test_derive_b_rr_rejects_corrupted_chunk_checksum(rr_source):
    image = bytearray(rr_source)
    slot = codec.parse_flash(rr_source, cfru=True)["slot"]
    offset = slot * codec.NUM_SECTORS_PER_SLOT * codec.SECTOR_SIZE + codec.OFF_SECTOR_CHECKSUM
    image[offset] ^= 0xFF
    with pytest.raises(ValueError, match="does not qualify"):
        fx.derive_b(bytes(image), rr=True)


def test_derive_b_rr_cli_routes_to_rr_qualification(rr_source, tmp_path, capsys):
    source, target = tmp_path / "a.sav", tmp_path / "b.sav"
    source.write_bytes(rr_source)
    args = fx.build_parser().parse_args(["derive-b", "--rr", str(source), str(target)])
    assert args.func(args) == 0
    _assert_rr_identity_only(rr_source, target.read_bytes())
    q = fx.build_parser().parse_args(["qualify", "--rr", str(target)])
    assert q.func(q) == 0
    assert "UNVERIFIED" not in capsys.readouterr().out


# --- boot-check / make-fr (card C2-6b): argument handling + the post-run verdict ---
#
# No emulator anywhere in here. The emulator lane is the coordinator's; what is falsifiable
# without one is (a) the two subcommands' CLI surface and (b) boot_check_verdict, which is
# the whole judgement the run's PASS/FAIL rests on.

def _parse(argv):
    return fx.build_parser().parse_args(argv)


def test_boot_check_argument_handling():
    args = _parse(["boot-check", "--rom", "patch/build/slink_RR.gba",
                   "--fixture", "tests/fixtures/gen3/rr_town.sav", "--rr"])
    assert (args.rom, args.fixture, args.rr) == (
        "patch/build/slink_RR.gba", "tests/fixtures/gen3/rr_town.sav", True)
    assert args.saveram_name is None and args.timeout > 0
    assert args.func is fx.cmd_boot_check
    assert _parse(["boot-check", "--rom", "r.gba", "--fixture", "f.sav"]).rr is False
    assert _parse(["boot-check", "--rom", "r.gba", "--fixture", "f.sav",
                   "--saveram-name", "Pokemon - FireRed Version (USA).SaveRAM"
                   ]).saveram_name == "Pokemon - FireRed Version (USA).SaveRAM"
    for missing in (["boot-check", "--rom", "r.gba"], ["boot-check", "--fixture", "f.sav"]):
        with pytest.raises(SystemExit):
            _parse(missing)


def test_make_fr_argument_handling():
    args = _parse(["make-fr", "--rom", "fr.gba", "--out",
                   "tests/fixtures/gen3/firered_town.sav"])
    assert (args.rom, args.out) == ("fr.gba", "tests/fixtures/gen3/firered_town.sav")
    assert args.func is fx.cmd_make_fr
    # make-fr is vanilla by construction: no --rr to get it wrong with.
    with pytest.raises(SystemExit):
        _parse(["make-fr", "--rom", "fr.gba", "--out", "o.sav", "--rr"])
    with pytest.raises(SystemExit):
        _parse(["make-fr", "--rom", "fr.gba"])


def test_saveram_name_matches_observed_gba_underscore_normalization():
    # BizHawk writes the optional RTC suffix itself; the seeded name must not carry one.
    assert fx.saveram_name("patch/build/gen3_slink_RR.gba") == "gen3 slink RR.SaveRAM"
    assert fx.saveram_name("a/b/firered.gba") == "firered.SaveRAM"


def test_our_emuhawk_pids_scopes_to_our_own_lua_driver_never_a_blanket_match():
    # 2026-09-23: a blanket `taskkill /IM EmuHawk.exe` here killed five in-flight Gen 2 gate
    # runs in a concurrent worktree. our_emuhawk_pids is what makes the kill safe to scope: a
    # Gen 2 (or any other lane's) command line must NOT match, and our own must.
    # Real command-line shape (run_gate.py's `cmd`): --config=<fixed name>.ini
    # --lua=<script> <rom> -- the run_dir itself never appears there, only inside the config
    # file, so the Lua-driver-path branch is what actually fires for a real launch.
    gen2_proc = {"ProcessId": 111, "CommandLine": (
        'E:\\Howard\\Bizhawk\\EmuHawk.exe --config=patch/build/gate_cfg_gen2_scripted_play.ini '
        '--lua=lua/tests/gen2_scripted_play.lua patch/build/gen2_pokemon_crystal.gbc')}
    unrelated_proc = {"ProcessId": 222, "CommandLine": None}
    ours_proc = {"ProcessId": 333, "CommandLine": (
        'E:\\Howard\\Bizhawk\\EmuHawk.exe '
        '--config=patch/build/gate_cfg_gen3_fixture_from_state.ini '
        '--lua=lua/tests/gen3_fixture_from_state.lua '
        'patch/build/gen3_gen3_Pokemon_-_FireRed_Version_(USA).gba')}
    run_dir_proc = {"ProcessId": 444, "CommandLine":
                    f"something referencing {fx.RUN_DIR.as_posix()}/make_fr_party_battle"}
    assert fx.our_emuhawk_pids([gen2_proc, unrelated_proc]) == []
    assert fx.our_emuhawk_pids([ours_proc]) == [333]
    assert fx.our_emuhawk_pids([gen2_proc, ours_proc, unrelated_proc]) == [333]
    assert fx.our_emuhawk_pids([run_dir_proc]) == [444]


def _q(counter, party, ok=True, message="ok"):
    return {"ok": ok, "message": message, "counter": counter,
            "party": [{"species": s, "level": lv} for s, lv in party]}


def test_boot_check_verdict_accepts_one_save_with_an_unchanged_party():
    ok, problems = fx.boot_check_verdict(_q(4, [(1, 5), (4, 7)]), _q(5, [(1, 5), (4, 7)]))
    assert (ok, problems) == (True, [])


def test_boot_check_verdict_refuses_a_counter_that_did_not_move():
    ok, problems = fx.boot_check_verdict(_q(4, [(1, 5)]), _q(4, [(1, 5)]))
    assert not ok
    assert "save counter 4 -> 4" in problems[0]


def test_boot_check_verdict_refuses_more_than_one_save():
    # Two saves is not the scenario being signed, and it means the driver did something else.
    ok, problems = fx.boot_check_verdict(_q(4, [(1, 5)]), _q(6, [(1, 5)]))
    assert not ok and "expected exactly one in-game save" in problems[0]


def test_boot_check_verdict_refuses_a_changed_party():
    ok, problems = fx.boot_check_verdict(_q(4, [(1, 5)]), _q(5, [(1, 6)]))
    assert not ok and "party changed" in problems[0]
    ok, problems = fx.boot_check_verdict(_q(4, [(1, 5)]), _q(5, []))
    assert not ok and "party changed" in problems[0]


def test_boot_check_verdict_refuses_a_flushed_save_that_does_not_qualify():
    ok, problems = fx.boot_check_verdict(
        _q(4, [(1, 5)]), _q(5, [(1, 5)], ok=False, message="sector 3 missing"))
    assert not ok
    assert any("does not qualify" in p and "sector 3 missing" in p for p in problems)


def test_boot_check_verdict_over_real_images():
    """The synthetic pair, end to end through qualify_one rather than hand-built dicts:
    the same save re-written with the counter bumped is a PASS, the untouched one a FAIL."""
    mon = _mon(0xAABBCCDD, 0x1234, "RED", party=True)
    before = fx.qualify_one(_build_image(party_mons=[mon], counter=4), rr=False)
    after = fx.qualify_one(_build_image(party_mons=[mon], counter=5), rr=False)
    assert before["ok"] and after["ok"]
    assert fx.boot_check_verdict(before, after) == (True, [])
    ok, problems = fx.boot_check_verdict(before, before)
    assert not ok and problems
