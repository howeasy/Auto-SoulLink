"""Per-ROM ingest for randomized FR/LG (docs/gen3/research/randomized_gen3_design.md R2, server half).

The pinned clean dumps skip by name when absent and fail on a wrong SHA-1 (tests/TESTING.md). The
UPR outputs the design built (FireRed_allowed.gba, FireRed_widest.gba, LeafGreen_*.gba) are read
from $SLINK_GEN3_RAND_ROMS and skip by name when absent; they are never committed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from server import upr_pipeline
from server.adapters import gen3_frlge, gen3_rom_tables
from server.adapters.gen3_frlge import ForbiddenRomTables, Gen3Adapter
from server.server import SLinkServer
from tests.unit.test_gen3_rom_content_lua import collector, payload_from, symbols
from tools.gen3_final_cut import STAGED, rom_pins

ROOT = Path(__file__).resolve().parents[2]
PRET = json.loads((ROOT / "data/games/gen3_frlge/frlg_trainers.json").read_text(encoding="utf-8"))
TITLES = {"firered": "FireRed", "leafgreen": "LeafGreen"}
BROCK = 414


def _payload(rom: bytes, title: str) -> dict:
    """The hello `rom_content` exactly as the client builds it: the real lua/gen3/rom_content.lua."""
    _, obj, _ = collector(rom, symbols(title, len(rom)))
    return payload_from(obj)


def _without(payload: dict, title: str, name: str) -> dict:
    """The same report with one table's bytes cut out, fingerprint recomputed."""
    addr, size = gen3_frlge._symbol(title, name)
    rom = {}
    for row in payload["tables"]:
        a, raw = row["addr"], bytes.fromhex(row["hex"])
        cut = range(max(addr, a) - a, min(addr + size, a + len(raw)) - a)
        if not cut:                             # region does not touch the span: keep it whole
            rom[a] = raw
            continue
        if cut.start:
            rom[a] = raw[:cut.start]
        if cut.stop < len(raw):
            rom[a + cut.stop] = raw[cut.stop:]
    assert sum(map(len, rom.values())) == sum(len(r["hex"]) // 2 for r in payload["tables"]) - size
    tables = [{"addr": a, "hex": raw.hex()} for a, raw in sorted(rom.items())]
    return {"tables": tables, "fingerprint": gen3_frlge._transport_sha1(rom)}


def _clean(title: str) -> bytes:
    candidates = [base / STAGED[title] for base in (ROOT, *ROOT.parents)]
    path = next((c for c in candidates if c.exists()), candidates[0])
    if not path.exists():
        pytest.skip(f"pinned clean {title} ROM absent: {path}")
    rom = path.read_bytes()
    assert hashlib.sha1(rom).hexdigest() == rom_pins(str(ROOT))[title], f"{path}: wrong {title} SHA-1"
    return rom


def _randomized(title: str, variant: str) -> bytes:
    name = f"{TITLES[title]}_{variant}.gba"
    folder = os.environ.get("SLINK_GEN3_RAND_ROMS")
    if not folder or not (Path(folder) / name).exists():
        pytest.skip(f"randomized {name} absent (set SLINK_GEN3_RAND_ROMS to the folder holding it)")
    return (Path(folder) / name).read_bytes()


def _ingested(payload: dict, title: str) -> Gen3Adapter:
    adapter = Gen3Adapter(rom_type=title, artifact_kind="rand")
    adapter.use_rom_encounters(adapter.ingest_rom_content(payload))
    return adapter


# ── ROM-free ─────────────────────────────────────────────────────────────────────────────

_ZEROS = bytes(64)


@pytest.mark.parametrize("payload", (
    None, [], {}, {"tables": []}, {"tables": [], "fingerprint": hashlib.sha1(b"").hexdigest()},
    {"tables": [{"addr": 0x08000000, "hex": "zz"}], "fingerprint": ""},
    {"tables": [{"addr": 0x08000000, "hex": _ZEROS.hex()}], "fingerprint": "0" * 40},  # wrong sha1
    {"tables": [{"addr": 0x08000000, "hex": _ZEROS.hex()}],                         # tables absent
     "fingerprint": hashlib.sha1(_ZEROS).hexdigest()},
    {"tables": [{"addr": 0x08000100, "hex": "00"}, {"addr": 0x08000000, "hex": "00"}],  # unsorted
     "fingerprint": hashlib.sha1(b"\x00\x00").hexdigest()},
    {"tables": [{"addr": "08000000", "hex": "00"}], "fingerprint": hashlib.sha1(b"\x00").hexdigest()},
))
def test_a_malformed_payload_raises_from_both_hooks(payload):
    adapter = Gen3Adapter(rom_type="firered", artifact_kind="rand")
    with pytest.raises(Exception):  # noqa: B017 - any failure; the server treats all alike
        adapter.ingest_rom_content(payload)
    with pytest.raises(Exception):  # noqa: B017
        adapter.rom_content_fingerprint(payload)


def test_an_unreadable_report_leaves_the_player_with_nothing_not_retail(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.state.rom_type, srv.state.artifact_kind = "firered", "rand"
    srv.adapter.set_artifact_kind("rand")
    srv.connected_players["a"] = {"rom_type": "firered"}
    srv._ingest_rom_content("a", {"tables": [{"addr": 0x08000000, "hex": "zz"}], "fingerprint": ""})
    adapter = srv.adapter_for("a")
    assert adapter is not srv.adapter
    assert adapter.trainer_brief(BROCK) is None and adapter.trainers_for_area("pewter_city") == []
    assert adapter.encounter_table("route_1") is None
    assert srv._trainer_panel_html("pewter_city", "a") == ""
    # whatever the kind: a failed report ({}) never falls back to the retail table
    clean = Gen3Adapter(rom_type="firered")
    clean.use_rom_encounters({})
    assert clean.trainer_brief(BROCK) is None


def test_rr_cannot_read_its_rom():
    rr = Gen3Adapter(is_rr=True, rom_type="firered_rr")
    assert rr.ingest_rom_content({"tables": []}) is None
    assert rr.rom_content_fingerprint({"tables": []}) is None


# ── clean control: the cartridge reproduces pret ─────────────────────────────────────────

@pytest.mark.parametrize("title", TITLES)
def test_clean_ingest_reproduces_pret(title):
    rom = _clean(title)
    payload = _payload(rom, title)
    adapter = _ingested(payload, title)
    table = adapter._rom_trainers
    assert table["trainers_by_area"] == PRET["trainers_by_area"]
    for tid, want in PRET["trainers"].items():
        got = table["trainers"][int(tid)]
        if not want["party"]:
            continue
        assert (got["name"], got["class"]) == (want["name"], want["class"]), tid
        for k in ("area", "key", "level_cap", "fight_label", "rival", "const"):
            assert got.get(k) == want.get(k), (tid, k)
        assert "calc_label" not in got
        assert len(got["party"]) == len(want["party"]), tid
        for g, w in zip(got["party"], want["party"], strict=True):
            assert (g["species"], g["level"], g.get("item")) == (w["species"], w["level"], w.get("item")), tid
            if "moves" in g:        # default-move mons carry none (ponytail in _rom_trainer_table)
                assert g["moves"] == w["moves"], tid
    assert adapter.encounter_table("route_1")["Grass"][0]["name"] in ("Pidgey", "Rattata")
    # the client report decodes like the whole file, and its fingerprint is recomputed alike
    assert gen3_frlge.decode_verified(rom, title)["trainers"] == gen3_frlge.decode_verified(
        gen3_frlge.parse_rom_content(payload), title)["trainers"]
    assert payload["fingerprint"].startswith({"firered": "9a973779", "leafgreen": "b633dc96"}[title])
    assert adapter.rom_content_fingerprint(payload) == upr_pipeline.gen3_fingerprint_rom(rom)
    # the client's fingerprint string is checked against its bytes, never trusted
    with pytest.raises(ValueError, match="SHA-1"):
        adapter.ingest_rom_content({**payload, "fingerprint": "0" * 40})
    # a whole-ROM report covers both titles' table heads: ambiguous, refused
    whole = {"tables": [{"addr": gen3_rom_tables.ROM_BASE, "hex": rom.hex()}],
             "fingerprint": hashlib.sha1(rom).hexdigest()}
    with pytest.raises(ValueError, match="firered', 'leafgreen"):
        adapter.ingest_rom_content(whole)


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("table", ("gTrainerClassNames", "gSpeciesInfo"))
def test_a_report_missing_a_table_is_refused(title, table):
    payload = _without(_payload(_clean(title), title), title, table)
    with pytest.raises(ValueError, match="no FR/LG title"):
        Gen3Adapter(rom_type=title).ingest_rom_content(payload)


# ── randomized: allowed is read, widest is refused by name ────────────────────────────────

@pytest.mark.parametrize("title", TITLES)
def test_allowed_shows_the_cartridge_parties(title):
    rom = _randomized(title, "allowed")
    adapter = _ingested(_payload(rom, title), title)
    decoded = gen3_rom_tables.decode_rom_tables(rom, title)["trainers"]
    differs = [tid for tid, t in PRET["trainers"].items()
               if [m["species"] for m in t["party"]]
               != [m["species"] for m in adapter.trainer_party(int(tid))]]
    assert differs, "no trainer party differs from retail: the ROM table was not adopted"
    brief = adapter.trainer_brief(BROCK)
    assert [m["species"] for m in brief["party"]] == [
        adapter.calc_species(m["species"]) for m in decoded[BROCK]["party"]]
    assert brief["name"] == "Brock" and "calc_label" not in brief
    clean = _clean(title)
    assert (adapter.rom_content_fingerprint(_payload(rom, title))
            != adapter.rom_content_fingerprint(_payload(clean, title)))


@pytest.mark.parametrize("title", TITLES)
def test_allowed_through_the_server_is_per_player(title, tmp_path):
    rom = _randomized(title, "allowed")
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.state.rom_type, srv.state.artifact_kind = title, "rand"
    srv.connected_players["a"] = {"rom_type": title}
    srv._ingest_rom_content("a", _payload(rom, title))
    party = srv.adapter_for("a").trainer_brief(BROCK)["party"]
    decoded = gen3_rom_tables.decode_rom_tables(rom, title)["trainers"][BROCK]["party"]
    assert [m["species"] for m in party] == [srv.adapter.calc_species(m["species"]) for m in decoded]
    assert srv.adapter_for("b").trainer_brief(BROCK) is None, "the other player's run shows nothing"


@pytest.mark.parametrize("title", TITLES)
def test_widest_is_refused_by_name(title, tmp_path):
    rom = _randomized(title, "widest")
    adapter = Gen3Adapter(rom_type=title, artifact_kind="rand")
    payload = _payload(rom, title)
    with pytest.raises(ForbiddenRomTables, match="evolutions and types/abilities/base stats"):
        adapter.ingest_rom_content(payload)
    with pytest.raises(ForbiddenRomTables):
        adapter.rom_content_fingerprint(payload)
    with pytest.raises(ForbiddenRomTables):
        gen3_frlge.decode_verified(rom, title)          # the Manager's whole-file path (R3)
    # a contract run rejects the hello with that name
    srv = SLinkServer(data_dir=str(tmp_path))
    srv._rom_contract = {"players": {"a": {"fingerprint": "0" * 64}}}
    verdict = srv._decide_admission("a", {"rom_content": _payload(rom, title)})
    assert verdict["state"] == "rejected" and "randomized evolutions" in verdict["reason"]


@pytest.mark.parametrize("title", TITLES)
def test_the_pinned_rule_digests_are_the_clean_tables(title):
    rom = _clean(title)
    tables = gen3_rom_tables.decode_rom_tables(rom, title)
    assert gen3_frlge._evolutions_digest(tables["evolutions"]) == gen3_frlge._EVOLUTIONS_SHA256
    addr, size = gen3_frlge._symbol(title, "gSpeciesInfo")
    raw = rom[addr - gen3_rom_tables.ROM_BASE:][:size]
    assert gen3_frlge._species_rules_digest(raw, title) == gen3_frlge._SPECIES_RULES_SHA256
    # known-positive control: one changed type byte is caught
    bumped = bytearray(raw)
    bumped[gen3_frlge.SPECIES_INFO_SIZE + 6] ^= 1
    assert gen3_frlge._species_rules_digest(bytes(bumped), title) != gen3_frlge._SPECIES_RULES_SHA256


# ── the Manager's contract (R3): a Manager-made pair is admitted, each only as itself ───────

def test_the_client_report_matches_the_managers_contract(tmp_path):
    run = Path(os.environ.get("SLINK_GEN3_RAND_ROMS") or "/nonexistent") / "r3_run"
    if not (run / "rom_contract.json").exists():
        pytest.skip(f"Manager-made pair absent: {run} (set SLINK_GEN3_RAND_ROMS)")
    stored = json.loads((run / "rom_contract.json").read_text(encoding="utf-8"))
    roms = {p: (run / "roms" / f"{p}_randomized.gba").read_bytes() for p in "ab"}
    assert all(hashlib.sha1(roms[p]).hexdigest() == stored["players"][p]["rom_sha1"] for p in "ab")
    # The contract the Manager writes TODAY for these files (a contract made before the decoder
    # changed carries a stale fingerprint: the value is a function of the decode, FRLG-R2c).
    contract = {"players": {p: {"fingerprint": upr_pipeline.gen3_fingerprint_rom(roms[p]),
                                "rom_sha1": stored["players"][p]["rom_sha1"]} for p in "ab"}}
    srv = SLinkServer(data_dir=str(tmp_path))
    srv._rom_contract = contract
    for player, other in (("a", "b"), ("b", "a")):
        rom = roms[player]
        title = upr_pipeline.gen3_title(rom)
        payload = _payload(rom, title)
        want = contract["players"][player]["fingerprint"]
        assert Gen3Adapter(rom_type=title).rom_content_fingerprint(payload) == want
        msg = {"rom_content": payload, "rom_sha1": hashlib.sha1(rom).hexdigest()}
        assert srv._decide_admission(player, msg) == {
            "state": "admitted", "reason": "cartridge matches the contract"}
        wrong = srv._decide_admission(other, msg)
        assert wrong["state"] == "rejected" and "not the cartridge built for player" in wrong["reason"]
