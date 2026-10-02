"""Emerald rand SOURCE/ROM and MODEL controls; no physical admission claim."""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from server.adapters import gen3_rom_tables as R
from tests.unit.test_gen3_rom_content_lua import collector, payload_from, symbols

ROOT = Path(__file__).resolve().parents[2]
ROM_NAME = "Pokemon - Emerald Version (USA, Europe).gba"
ROM_SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"


@pytest.fixture(scope="module")
def emerald_rom():
    folders = [Path(os.environ["SLINK_GEN3_ROMS"])] if os.environ.get("SLINK_GEN3_ROMS") else [ROOT, *ROOT.parents]
    paths = [folder / ROM_NAME for folder in folders]
    paths.append(ROOT / "patch/build/gen3_Pokemon_-_Emerald_Version_(USA,_Europe).gba")
    path = next((p for p in paths if p.is_file()), None)
    if path is None:
        pytest.skip("pinned clean Emerald ROM absent; set SLINK_GEN3_ROMS")
    rom = path.read_bytes()
    assert hashlib.sha1(rom).hexdigest() == ROM_SHA1
    return rom


def test_species_info_declarations_match_frlg_byte_for_byte():
    from tests.unit import gen3_pret

    roots = (gen3_pret.require(gen3_pret.find()), gen3_pret.require_emerald(gen3_pret.find_emerald()))
    declarations, offsets = [], []
    for root in roots:
        text = (root / "include/pokemon.h").read_text()
        body = re.search(r"struct SpeciesInfo\s*\{(.*?)\};", text, re.S)[1]
        offsets.append(re.findall(r"/\*\s*(0x[0-9A-Fa-f]+)\s*\*/", body))
        declarations.append(re.sub(r"\s+", "", re.sub(r"/\*.*?\*/", "", body, flags=re.S)))
    assert declarations[0] == declarations[1]
    assert offsets[0] == offsets[1]
    assert hashlib.sha256(declarations[1].encode()).hexdigest() == (
        "3e19a8672a0d926961f74ab416896bac1e48d18ab59e4078be0e971d6639667f")


def test_clean_emerald_proves_all_four_party_strides(emerald_rom):
    rows = [line.split() for line in (ROOT / "data/gen3/pret/pokeemerald.sym").read_text().splitlines()]
    head, = [(int(f[0], 16), int(f[2], 16)) for f in rows if len(f) == 4 and f[3] == "gTrainers"]
    parties = {int(f[0], 16): int(f[2], 16) for f in rows if len(f) == 4 and f[3].startswith("sParty_")}
    assert head[1] == 855 * 40
    counts = Counter()
    for trainer in range(855):
        at = head[0] - R.ROM_BASE + trainer * 40
        flags, count = emerald_rom[at], emerald_rom[at + 32]
        if not count:
            continue
        pointer = struct.unpack_from("<I", emerald_rom, at + 36)[0]
        assert 1 <= count <= 6 and pointer in parties
        assert parties[pointer] == count * (8, 16, 8, 16)[flags]
        counts[flags] += 1
    assert counts == {0: 672, 1: 87, 2: 31, 3: 64}


def test_emerald_table_counts_and_profile_are_symbol_sized():
    tables = R.table_symbols("emerald")
    assert {k: tables[k]["count"] for k in tables} == {
        "gTrainers": 855, "gWildMonHeaders": 125, "gEvolutionTable": 412, "gSpeciesInfo": 412}
    profile = json.loads((ROOT / "data/games/gen3_emerald/profile.json").read_text())["titles"]["emerald"]
    expected = {"gTrainers": (855, 40), "gWildMonHeaders": (125, 20), "gEvolutionTable": (412, 40),
                "gSpeciesInfo": (412, 28), "gTrainerClassNames": (66, 13)}
    for name, (count, stride) in expected.items():
        row = profile["rom_tables"][name]
        assert row["count"] == count and row["stride"] == stride and row["size"] == count * stride
        assert "pokeemerald" in profile["rom_tables_provenance"][name]


def test_unknown_hash_emerald_is_rand_and_reuses_clean_sites():
    from tests.unit.test_gen3_entry import World, _admit, lua_to_py

    w = World(pack="gen3_emerald", title="emerald", build=False)
    got = lua_to_py(_admit(w, rom_hash="00" * 20, rom_read=w._rom_read, header_code="BPEE"))
    assert (got["pack"], got["title"], got["kind"]) == ("gen3_emerald", "emerald", "rand")
    assert got["admitted_by"] == "anchors"
    w.kind = "rand"
    _, parts = w.Entry.build(w.deps())
    assert parts.kind == "rand" and parts.artifact_kind == "clean"


def test_clean_emerald_is_readable_by_the_existing_lua_collector_and_decoder(emerald_rom):
    _, obj, _ = collector(emerald_rom, symbols("emerald", len(emerald_rom)))
    report = payload_from(obj)
    sparse = {row["addr"]: bytes.fromhex(row["hex"]) for row in report["tables"]}
    decoded = R.decode_rom_tables(sparse, "emerald")
    assert len(decoded["trainers"]) == 855 and len(decoded["evolutions"]) == 412
    assert len(decoded["wild_encounters"]) == 116  # 124 rows include Altering Cave alternatives


def test_emerald_rule_facts_are_generated_from_the_pinned_rom(emerald_rom):
    from tools import gen_gen3_species_rules as G

    facts = G.build_emerald(emerald_rom)
    assert facts == json.loads((ROOT / "data/games/gen3_emerald/species_rules.json").read_text())
    assert facts["titles"]["emerald"]["rom_sha1"] == ROM_SHA1
    assert facts["record_size"] == 28 and facts["second_ability_offset"] == 23
    assert [r["offset"] for r in facts["bytes"]] == list(range(28))
    assert facts["bytes"] == G.byte_policy()
    with pytest.raises(ValueError, match="SHA-1-pinned"):
        G.build_emerald(bytes([emerald_rom[0] ^ 1]) + emerald_rom[1:])


def test_emerald_normalisation_uses_its_pinned_empty_slots_and_speed_forme(emerald_rom):
    table = symbols("emerald", len(emerald_rom))["gSpeciesInfo"]
    at = table["address"] - R.ROM_BASE
    raw = emerald_rom[at:at + table["size"]]
    expected = R.normalised_species_rules(raw, "emerald")
    modified = bytearray(raw)
    for species in range(412):
        if raw[species * 28 + 23] == 0:
            modified[species * 28 + 23] = modified[species * 28 + 22]
    modified[410 * 28:410 * 28 + 6] = bytes([50, 95, 90, 180, 95, 90])
    assert R.normalised_species_rules(bytes(modified), "emerald") == expected
    modified[333 * 28 + 23] = 0  # Vibrava's second LEVITATE slot is real, not originally empty
    assert R.normalised_species_rules(bytes(modified), "emerald") != expected


def emerald_payload(rom):
    _, obj, _ = collector(rom, symbols("emerald", len(rom)))
    return payload_from(obj)


def test_emerald_clean_equivalent_rand_pairs_clean(emerald_rom):
    from server.adapters.gen3_frlge import Gen3Adapter

    report = emerald_payload(emerald_rom)
    adapter = Gen3Adapter(rom_type="emerald", artifact_kind="rand")
    assert adapter.supports_randomized("emerald") is True
    assert adapter.refused_rom_content(report) == ""
    assert adapter.pairing_kind_for("rand", report) == "clean"


def test_emerald_adopts_own_trainer_and_encounter_tables(emerald_rom):
    from server.adapters.gen3_frlge import Gen3Adapter

    source = json.loads((ROOT / "data/games/gen3_emerald/emerald_trainers.json").read_text())
    tid, retail = next((int(k), v) for k, v in source["trainers"].items() if v.get("const") == "TRAINER_ROXANNE_1")
    rom = bytearray(emerald_rom)
    table = symbols("emerald", len(rom))["gTrainers"]["address"] - R.ROM_BASE
    party = struct.unpack_from("<I", rom, table + tid * 40 + 36)[0] - R.ROM_BASE
    struct.pack_into("<HH", rom, party + 2, 42, 392)  # Ralts, level42; rules untouched
    wild = symbols("emerald", len(rom))["gWildMonHeaders"]["address"] - R.ROM_BASE
    route = next(at for at in range(wild, wild + 124 * 20, 20) if rom[at:at + 2] == b"\x00\x11")
    info = struct.unpack_from("<I", rom, route + 4)[0] - R.ROM_BASE
    slots = struct.unpack_from("<I", rom, info + 4)[0] - R.ROM_BASE
    struct.pack_into("<H", rom, slots + 2, 25)  # Pikachu in Route102's first grass slot
    report = emerald_payload(bytes(rom))
    adapter = Gen3Adapter(rom_type="emerald", artifact_kind="rand")
    assert adapter.trainer_brief(tid) is None
    assert adapter.refused_rom_content(report) == ""
    adapter.use_rom_encounters(adapter.ingest_rom_content(report))
    brief = adapter.trainer_brief(tid)
    assert brief["party"][0]["species"] == "Ralts" and brief["party"][0]["level"] == 42
    assert "calc_label" not in brief and brief["level_cap"] == 42
    assert adapter.trainers_for_area(retail["area"])
    encounters = adapter.encounter_table("route_102")
    assert any(mon["species_id"] == 25 for mon in encounters["Grass"])
    assert adapter.pairing_kind_for("rand", report) == "rand"


@pytest.mark.parametrize("field", [0, 6, 16, 19, 22, 23])
def test_emerald_rule_changing_content_is_refused(emerald_rom, field):
    from server.adapters.gen3_frlge import Gen3Adapter

    rom = bytearray(emerald_rom)
    table = symbols("emerald", len(rom))["gSpeciesInfo"]["address"] - R.ROM_BASE
    rom[table + 333 * 28 + field] ^= 1
    report = emerald_payload(bytes(rom))
    adapter = Gen3Adapter(rom_type="emerald", artifact_kind="rand")
    assert "types/abilities/base stats/growth rates/gender ratios" in adapter.refused_rom_content(report)
    assert adapter.pairing_kind_for("rand", report) == "rand"


def test_emerald_evolution_changes_are_refused(emerald_rom):
    from server.adapters.gen3_frlge import Gen3Adapter

    rom = bytearray(emerald_rom)
    at = symbols("emerald", len(rom))["gEvolutionTable"]["address"] - R.ROM_BASE
    struct.pack_into("<H", rom, at + 40 + 4, 3)
    report = emerald_payload(bytes(rom))
    adapter = Gen3Adapter(rom_type="emerald", artifact_kind="rand")
    assert "randomized evolutions" in adapter.refused_rom_content(report)


def test_emerald_keeps_allowed_catch_rate_and_wild_items_outside_fixed_rules(emerald_rom):
    from server.adapters.gen3_frlge import Gen3Adapter

    rom = bytearray(emerald_rom)
    at = symbols("emerald", len(rom))["gSpeciesInfo"]["address"] - R.ROM_BASE + 28
    rom[at + 8] ^= 1
    struct.pack_into("<HH", rom, at + 12, 1, 2)
    adapter = Gen3Adapter(rom_type="emerald", artifact_kind="rand")
    assert adapter.refused_rom_content(emerald_payload(bytes(rom))) == ""


def test_emerald_sparse_default_move_parties_never_inherit_retail_moves_or_calc_labels(emerald_rom):
    from server.adapters.gen3_frlge import Gen3Adapter

    head = symbols("emerald", len(emerald_rom))["gTrainers"]["address"] - R.ROM_BASE
    tid = next(i for i in range(855) if emerald_rom[head + i * 40] == 0 and emerald_rom[head + i * 40 + 32])
    adapter = Gen3Adapter(rom_type="emerald", artifact_kind="rand")
    adapter.use_rom_encounters(adapter.ingest_rom_content(emerald_payload(emerald_rom)))
    brief = adapter.trainer_brief(tid)
    assert "calc_label" not in brief
    assert all("moves" not in mon for mon in brief["party"])


def test_manager_refuses_an_unqualified_jar_for_emerald_before_calling_upr(emerald_rom, monkeypatch, tmp_path):
    from server import upr_pipeline as U

    source, output, jar, settings = (tmp_path / n for n in ("clean.gba", "out.gba", "upr.jar", "settings.rnqs"))
    source.write_bytes(emerald_rom)
    jar.write_bytes(b"model jar")
    settings.write_bytes(b"model settings")
    monkeypatch.setattr(U.shutil, "which", lambda _: "java")
    with pytest.raises(U.UprPipelineError, match="Emerald.*fork jar"):
        U.randomize(str(jar), str(settings), str(source), str(output))


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_emerald_rom_content_reaches_real_hello_admission(emerald_rom, tmp_path, changed):
    from server.server import SLinkServer
    from tests.unit.test_gen3_rand_admission import client, hello

    rom = bytearray(emerald_rom)
    if changed:
        head = symbols("emerald", len(rom))["gTrainers"]["address"] - R.ROM_BASE
        pointer = struct.unpack_from("<I", rom, head + 265 * 40 + 36)[0] - R.ROM_BASE
        struct.pack_into("<HH", rom, pointer + 2, 42, 392)
    report = emerald_payload(bytes(rom))
    server = SLinkServer(data_dir=str(tmp_path))
    async with client(server) as send:
        response = await send(hello("emerald", "rand", rom_content=report))
        assert not any(c.get("refused") for c in response["commands"])
        assert server.admission["a"]["state"] == "admitted"
        assert server.adapter_for("a").trainer_brief(265)["party"][0]["level"] == (42 if changed else 12)
        # Clean-equivalent payload pairs with clean; changed cartridge tables keep rand.
        # (a companion peer: it pairs as clean, and a clean Emerald would be refused outright)
        peer = hello("emerald", "companion", player="b", trainer_name="B", ot_id="7B0B")
        response = await send(peer)
    if changed:
        assert "Mixed artifact kinds" in server.state.identity_error["b"]
    else:
        assert server.admission["b"]["state"] == "admitted"


def test_pure_pairing_does_not_normalize_foreign_tables_for_emerald(tmp_path):
    from server.adapters.gen3_frlge import Gen3Adapter
    from server.server import SLinkServer
    from tests.unit.test_gen3_rom_ingest import _clean, _payload

    report = _payload(_clean("firered"), "firered")
    assert Gen3Adapter.pairing_kind_for_title("emerald", "rand", report) == "rand"
    server = SLinkServer(data_dir=str(tmp_path))
    server.state.rom_type, server.state.artifact_kind = "emerald", "clean"
    assert "Mixed artifact kinds" in server._mixed_games_error("a", "emerald", "rand", rom_content=report)


def test_protocol_describes_emerald_randomized_admission_and_title_aware_pairing():
    protocol = (ROOT / "docs/protocol.md").read_text(encoding="utf-8")
    assert protocol.count("randomized FR/LG and Emerald") >= 2
    assert "pairing_kind_for_title" in protocol
    assert "Emerald, RR, expansion" not in protocol


def test_manager_identification_and_preflight_refuse_an_incomplete_emerald_header(tmp_path):
    from server import upr_pipeline as U

    raw = bytearray(0xC0)
    raw[0xAC:0xB0] = b"BPEE"
    source = tmp_path / "emerald.gba"
    source.write_bytes(raw)
    info = U.describe_rom(str(source), jar_fork=True)
    assert info["clean"] is False
    assert "Emerald header is not a supported" in info["title"]
    check = U.preflight("", {"a": str(source), "b": str(source)})
    assert check["ok"] is False
    assert check["roms"]["a"]["title"] == info["title"]
    assert U.GEN3_CODES[b"BPEE"] == "emerald" and U.gen3_identify(bytes(raw)) is None


def test_manager_provision_refuses_an_incomplete_emerald_header_before_java(tmp_path, monkeypatch):
    from server import cartridges, upr_pipeline as U

    raw = bytearray(0xC0)
    raw[0xAC:0xB0] = b"BPEE"
    source = tmp_path / "emerald.gba"
    source.write_bytes(raw)
    calls = []
    monkeypatch.setattr(U, "randomize", lambda *a, **kw: calls.append("Java"))
    with pytest.raises(cartridges.CartridgeError, match="Emerald header is not a supported"):
        cartridges.provision(str(tmp_path / "run"), {"a": str(source), "b": str(source)},
                             companion=False, randomize={"settings_path": "unused.rnqs"})
    assert calls == []


@pytest.mark.parametrize("fault", ("missing_file", "missing_pin"))
def test_emerald_rule_facts_are_required_at_import(fault):
    # A subprocess isolates the import without replacing the module held by other tests.
    script = '''
import io, json
from pathlib import Path
path = Path('data/games/gen3_emerald/species_rules.json')
facts = json.loads(path.read_text())
original = Path.open
def opened(self, *args, **kwargs):
    if self.as_posix().endswith('data/games/gen3_emerald/species_rules.json'):
        if FAULT == 'missing_file':
            raise FileNotFoundError('Emerald species_rules fixture absent')
        facts.pop('evolutions_sha256', None)
        return io.StringIO(json.dumps(facts))
    return original(self, *args, **kwargs)
Path.open = opened
import server.adapters.gen3_rom_tables
'''
    result = subprocess.run([sys.executable, "-c", "FAULT=" + repr(fault) + "\n" + script],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0, "missing Emerald rule facts silently survived import"
    assert ("FileNotFoundError" if fault == "missing_file" else "evolutions_sha256") in result.stderr


def test_emerald_pins_are_read_from_its_file_and_drive_rule_refusal(emerald_rom, monkeypatch):
    from server.adapters import gen3_frlge as A

    facts = json.loads((ROOT / "data/games/gen3_emerald/species_rules.json").read_text())
    assert facts == R.EMERALD_SPECIES_RULES_FACTS
    assert A.CLEAN_CONTENT_SHA256["emerald"] == facts["clean_content_sha256"]
    # The values currently coincide with FR/LG. Poison only the Emerald pin; falling
    # back to FR/LG would accept this cartridge and fail this control.
    monkeypatch.setitem(R.EMERALD_SPECIES_RULES_FACTS, "evolutions_sha256", "00" * 32)
    with pytest.raises(A.ForbiddenRomTables, match="randomized evolutions"):
        A.decode_verified(emerald_rom, "emerald")


def test_emerald_refuses_the_attack_forme_even_though_it_accepts_speed_forme(emerald_rom):
    from server.adapters.gen3_frlge import ForbiddenRomTables, Gen3Adapter

    assert all(forme != R.DEOXYS_NORMAL for forme in R.DEOXYS_FORME.values())
    rom = bytearray(emerald_rom)
    at = symbols("emerald", len(rom))["gSpeciesInfo"]["address"] - R.ROM_BASE + R.DEOXYS * 28
    rom[at:at + 6] = R.DEOXYS_FORME["firered"]
    with pytest.raises(ForbiddenRomTables, match="base stats"):
        Gen3Adapter(rom_type="emerald", artifact_kind="rand").ingest_rom_content(emerald_payload(bytes(rom)))


def test_emerald_wild_headers_do_not_map_to_facility_areas(emerald_rom):
    wild = R.decode_rom_tables(emerald_rom, "emerald")["wild_encounters"]
    areas = json.loads((ROOT / "data/games/gen3_emerald/area_map.json").read_text())
    mapped = [areas.get(f"{group}:{number}", "") for group, number in wild]
    assert not [area for area in mapped if any(word in area for word in ("frontier", "pyramid", "trainer_hill"))]
    cave = next(key for key in wild if areas.get(f"{key[0]}:{key[1]}") == "altering_cave")
    assert len(wild[cave]) == 9  # the display uses set 0, not the current runtime selector


@pytest.mark.asyncio
async def test_committed_emerald_rand_rejects_a_firered_report_at_admission(tmp_path, emerald_rom):
    from server.server import SLinkServer
    from tests.unit.test_gen3_rand_admission import client, hello
    from tests.unit.test_gen3_rom_ingest import _clean, _payload

    server = SLinkServer(data_dir=str(tmp_path))
    changed = bytearray(emerald_rom)
    head = symbols("emerald", len(changed))["gTrainers"]["address"] - R.ROM_BASE
    party = struct.unpack_from("<I", changed, head + 265 * 40 + 36)[0] - R.ROM_BASE
    changed[party + 2] = 42
    report = _payload(_clean("firered"), "firered")
    async with client(server) as send:
        await send(hello("emerald", "rand", rom_content=emerald_payload(bytes(changed))))
        assert server.admission["a"]["state"] == "admitted" and server.state.artifact_kind == "rand"
        await send(hello("emerald", "rand", player="b", trainer_name="B", ot_id="7B0B", rom_content=report))
    assert server.admission["b"]["state"] == "rejected"
    assert "not an Emerald cartridge report" in server.admission["b"]["reason"]
    assert not server.state.player_identity.get("b") and not server.party_details["b"]


@pytest.mark.asyncio
async def test_commit_path_never_normalises_a_foreign_title_report_to_clean(emerald_rom, tmp_path):
    """Integration-merge audit (OMP cx-4b7ffc34 F1), end-to-end REGRESSION GUARD (not a
    falsifier of the commit-site edit: admission already refuses this hello before the commit
    runs, so the test passes with or without it). A legacy run (rom_type committed, kind empty)
    receiving an FR/LG `rand` hello carrying clean *Emerald* tables must never commit `clean`;
    the commit site now also uses the title-aware rule as defence in depth."""
    from server.adapters.gen3_frlge import Gen3Adapter
    from server.server import SLinkServer
    from tests.unit.test_gen3_rand_admission import client, hello

    report = emerald_payload(emerald_rom)
    assert Gen3Adapter.pairing_kind_for_title("firered", "rand", report) == "rand"
    server = SLinkServer(data_dir=str(tmp_path))
    server.state.rom_type, server.state.artifact_kind = "firered", ""
    async with client(server) as send:
        await send(hello(rom_type="firered", kind="rand", rom_content=report))
    assert server.state.artifact_kind != "clean"
