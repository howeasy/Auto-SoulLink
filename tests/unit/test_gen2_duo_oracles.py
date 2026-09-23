"""Unit tests for tools/gen2_duo_oracles.py (card gen2-H2): a MODEL exercise of the two
`gen2_new` evidence callbacks against synthetic saves and synthetic server state. No emulator;
red-capable per refusal. Synthetic saves are built by mutating the committed played-origin
fixtures tests/fixtures/gen2/crystal_battle{,_ot2}.SaveRAM through gen2_codec's own encoder, so
every positive case is still an independently-checksummed, structurally valid Crystal save."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from server.adapters import gen2_codec as codec
from tools import gen2_duo_oracles as oracles
from tools.gen2_fixtures import _REGION_STARTS, _saved_field

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = {"a": ROOT / "tests/fixtures/gen2/crystal_battle.SaveRAM",
            "b": ROOT / "tests/fixtures/gen2/crystal_battle_ot2.SaveRAM"}
OT_IDS = {"a": 46401, "b": 44068}
CART = oracles.CARTRAM_BYTES


@pytest.fixture(scope="module")
def layout():
    return codec.for_foundation("crystal")


def _region_and_offset(layout, symbol):
    address = layout.addresses[symbol]
    for region in layout.regions:
        base = layout.addresses[_REGION_STARTS[region.name]]
        if base <= address < base + region.length:
            return region, address - base
    raise RuntimeError(f"{symbol} not in any saved region")


def _poke(cart, region, offset, data):
    for base in (region.primary, region.backup):
        cart[base + offset:base + offset + len(data)] = data


def build_capture(layout, inst, *, species=16, ot_id=None, dv_word=None, ball_delta=-1):
    """A synthetic post-battle flushed save: the committed boot fixture plus one new party
    mon and a smaller Ball pocket, re-checksummed on both the primary and backup copies.

    Returns (full_save_bytes_with_rtc_tail, decoded_new_mon).
    """
    ot_id = OT_IDS[inst] if ot_id is None else ot_id
    raw = bytearray(FIXTURES[inst].read_bytes())
    tail = bytes(raw[CART:])
    cart = bytearray(raw[:CART])
    pokemon = next(r for r in layout.regions if r.name == "pokemon")
    player = next(r for r in layout.regions if r.name == "player")

    def rel(base_symbol, symbol):
        return layout.addresses[symbol] - layout.addresses[base_symbol]

    party = codec.decode_saved_party(bytes(cart), layout, copy_name="primary")
    template = party["mons"][0]
    count = party["count"]
    dv_word = (template["dv_word"] ^ 0x1234) if dv_word is None else dv_word

    count_off = rel("wPokemonData", "wPartyCount")
    species_off = rel("wPokemonData", "wPartySpecies")
    record_off = rel("wPokemonData", "wPartyMon1") + count * layout.party_size
    ot_off = rel("wPokemonData", "wPartyMonOTs") + count * layout.name_size
    nick_off = rel("wPokemonData", "wPartyMonNicknames") + count * layout.nickname_size

    new_mon = dict(template)
    new_mon.update(species_id=species, species_marker=species, ot_id=ot_id, dv_word=dv_word,
                  raw_hex="00" * 48)
    new_mon["dvs"] = codec.decode_dvs(dv_word)
    new_record = codec.encode_party_mon(new_mon, layout)

    _poke(cart, pokemon, record_off, new_record)
    _poke(cart, pokemon, ot_off, bytes.fromhex(template["ot_raw_hex"]))
    _poke(cart, pokemon, nick_off, bytes.fromhex(template["nickname_raw_hex"]))
    _poke(cart, pokemon, species_off + count, bytes([species]))
    _poke(cart, pokemon, species_off + count + 1, bytes([255]))
    _poke(cart, pokemon, count_off, bytes([count + 1]))

    if ball_delta:
        before = _saved_field(bytes(cart), layout, "wNumBalls", 1)[0]
        pocket = _saved_field(bytes(cart), layout, "wBalls", before * 2 + 1)
        qty_off = rel("wPlayerData", "wBalls") + 1  # slot 0's quantity byte
        _poke(cart, player, qty_off, bytes([pocket[1] + ball_delta]))

    for copy_name in ("primary", "backup"):
        checksum = codec.sav_checksum(bytes(cart), layout, copy_name)
        off = layout.checksum_offsets[copy_name]
        cart[off:off + 2] = checksum.to_bytes(2, "little")

    decoded_new = codec.decode_party_mon(new_record, layout, species_marker=species)
    return bytes(cart) + tail, decoded_new


def _marker_text(*, saveram_path, cartram, title="crystal", area_id="route_29", key,
                  species, level, gate_saves=1, client_saves=1, flushed_matches=True,
                  sha256=None, site_id="capture_party_finalized", acquisition="wild",
                  destination="party", result="PASS"):
    witness = {"frame": 5000, "save_completed_frame": 4990, "gate_saves": gate_saves,
              "client_saves": client_saves,
              "cartram_sha256": sha256 or hashlib.sha256(cartram).hexdigest(),
              "cartram_bytes": len(cartram), "saveram_path": str(saveram_path),
              "saveram_bytes": len(cartram) + 22, "flushed_matches": flushed_matches}
    client = {"qualification": "PASS", "production_admitted": True, "pack": "gen2_crystal",
             "title": title, "rom_sha1": "deadbeef" * 5}
    capture = {"frame": 4800, "site_id": site_id, "acquisition": acquisition,
              "area_id": area_id, "destination": destination, "slot": 1, "key": key,
              "species_id": species, "level": level}
    lines = [f"SAVE_WITNESS {json.dumps(witness)}", f"CLIENT {json.dumps(client)}",
             f"ENGINE_CAPTURE {json.dumps(capture)}", f"CAUGHT {key}",
             f"RESULT: {result} (caught {key})" if result == "PASS" else f"RESULT: {result}"]
    return "\n".join(lines)


@pytest.fixture
def good_case(tmp_path, layout):
    decoded, results = {}, {}
    for inst, species in (("a", 16), ("b", 19)):
        save, mon = build_capture(layout, inst, species=species)
        path = tmp_path / f"{inst}.SaveRAM"
        path.write_bytes(save)
        key = codec.key(mon)
        results[inst] = _marker_text(saveram_path=path, cartram=save[:CART], key=key,
                                     species=species, level=mon["level"])
        decoded[inst] = {"key": key, "species": species, "level": mon["level"]}
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    links_doc = {"links": [{"area_id": "route_29", "status": "alive",
                            "a": {"key": decoded["a"]["key"], "species": decoded["a"]["species"],
                                  "level": decoded["a"]["level"]},
                            "b": {"key": decoded["b"]["key"], "species": decoded["b"]["species"],
                                  "level": decoded["b"]["level"]}}]}
    (data_dir / "links.json").write_text(json.dumps(links_doc), encoding="utf-8")
    return results, str(data_dir), decoded


# ---------------------------------------------------------------------------
# Positive case
# ---------------------------------------------------------------------------

def test_good_case_passes_both_stages(good_case):
    results, data_dir, _decoded = good_case
    assert oracles.check_save_witness(results) is None
    assert oracles.link_oracle(results, data_dir=data_dir) is None


# ---------------------------------------------------------------------------
# check_save_witness refusals
# ---------------------------------------------------------------------------

def test_missing_save_witness_marker_refused(good_case):
    results, _data_dir, _decoded = good_case
    bad = dict(results)
    bad["a"] = bad["a"].replace("SAVE_WITNESS ", "SAVE_WITNESS_X ")
    with pytest.raises(RuntimeError, match="missing SAVE_WITNESS"):
        oracles.check_save_witness(bad)


def test_missing_client_title_refused(good_case):
    results, _data_dir, _decoded = good_case
    bad = dict(results)
    bad["a"] = bad["a"].replace("CLIENT ", "CLIENT_X ")
    with pytest.raises(RuntimeError, match="CLIENT title"):
        oracles.check_save_witness(bad)


def test_gate_saves_mismatch_is_torn_witness(good_case):
    results, _data_dir, _decoded = good_case
    witness = oracles._last_tagged(results["a"], "SAVE_WITNESS")
    witness["gate_saves"] = witness["client_saves"] + 1
    bad = dict(results)
    bad["a"] = bad["a"].replace(f'SAVE_WITNESS {json.dumps(oracles._last_tagged(results["a"], "SAVE_WITNESS"))}',
                                f"SAVE_WITNESS {json.dumps(witness)}")
    with pytest.raises(RuntimeError, match="torn witness"):
        oracles.check_save_witness(bad)


def test_flushed_matches_false_refused(good_case):
    results, _data_dir, _decoded = good_case
    witness = oracles._last_tagged(results["a"], "SAVE_WITNESS")
    original_line = f"SAVE_WITNESS {json.dumps(witness)}"
    witness["flushed_matches"] = False
    bad = dict(results)
    bad["a"] = bad["a"].replace(original_line, f"SAVE_WITNESS {json.dumps(witness)}")
    with pytest.raises(RuntimeError, match="flushed_matches"):
        oracles.check_save_witness(bad)


def test_missing_saveram_file_refused(good_case, tmp_path):
    results, _data_dir, _decoded = good_case
    witness = oracles._last_tagged(results["a"], "SAVE_WITNESS")
    original_line = f"SAVE_WITNESS {json.dumps(witness)}"
    witness["saveram_path"] = str(tmp_path / "does_not_exist.SaveRAM")
    bad = dict(results)
    bad["a"] = bad["a"].replace(original_line, f"SAVE_WITNESS {json.dumps(witness)}")
    with pytest.raises(RuntimeError, match="does not exist"):
        oracles.check_save_witness(bad)


def test_sha256_mismatch_refused(good_case, tmp_path):
    """The independently recomputed hash must match the marker's claim, not just be well-formed."""
    results, _data_dir, _decoded = good_case
    witness = oracles._last_tagged(results["a"], "SAVE_WITNESS")
    original_line = f"SAVE_WITNESS {json.dumps(witness)}"
    witness["cartram_sha256"] = "00" * 32
    bad = dict(results)
    bad["a"] = bad["a"].replace(original_line, f"SAVE_WITNESS {json.dumps(witness)}")
    with pytest.raises(RuntimeError, match="does not match"):
        oracles.check_save_witness(bad)


def test_short_saveram_file_refused(good_case, tmp_path):
    results, _data_dir, _decoded = good_case
    witness = oracles._last_tagged(results["a"], "SAVE_WITNESS")
    original_line = f"SAVE_WITNESS {json.dumps(witness)}"
    truncated = tmp_path / "short.SaveRAM"
    truncated.write_bytes(Path(witness["saveram_path"]).read_bytes()[:-1])
    witness["saveram_path"] = str(truncated)
    bad = dict(results)
    bad["a"] = bad["a"].replace(original_line, f"SAVE_WITNESS {json.dumps(witness)}")
    with pytest.raises(RuntimeError, match="torn save"):
        oracles.check_save_witness(bad)


def test_corrupt_checksum_refused(good_case, layout):
    """A tampered save whose reported hash matches the (also tampered) file must still fail the
    independent gen2_codec checksum/primary-backup witness."""
    results, _data_dir, _decoded = good_case
    witness = oracles._last_tagged(results["a"], "SAVE_WITNESS")
    original_line = f"SAVE_WITNESS {json.dumps(witness)}"
    path = Path(witness["saveram_path"])
    corrupt = bytearray(path.read_bytes())
    player = next(r for r in layout.regions if r.name == "player")
    corrupt[player.primary + 5] ^= 0xFF  # inside a checksummed span; checksum left stale
    path.write_bytes(bytes(corrupt))
    witness["cartram_sha256"] = hashlib.sha256(bytes(corrupt[:CART])).hexdigest()
    bad = dict(results)
    bad["a"] = bad["a"].replace(original_line, f"SAVE_WITNESS {json.dumps(witness)}")
    with pytest.raises(RuntimeError, match="checksum/primary-backup/marker witness refused"):
        oracles.check_save_witness(bad)


# ---------------------------------------------------------------------------
# link_oracle refusals
# ---------------------------------------------------------------------------

def test_wrong_area_refused(good_case):
    results, data_dir, _decoded = good_case
    capture = oracles._last_tagged(results["a"], "ENGINE_CAPTURE")
    original_line = f"ENGINE_CAPTURE {json.dumps(capture)}"
    capture["area_id"] = "route_30"
    bad = dict(results)
    bad["a"] = bad["a"].replace(original_line, f"ENGINE_CAPTURE {json.dumps(capture)}")
    with pytest.raises(RuntimeError, match="expected 'route_29'"):
        oracles.link_oracle(bad, data_dir=data_dir)


def test_wrong_site_id_refused(good_case):
    results, data_dir, _decoded = good_case
    capture = oracles._last_tagged(results["a"], "ENGINE_CAPTURE")
    original_line = f"ENGINE_CAPTURE {json.dumps(capture)}"
    capture["site_id"] = "capture_party"
    bad = dict(results)
    bad["a"] = bad["a"].replace(original_line, f"ENGINE_CAPTURE {json.dumps(capture)}")
    with pytest.raises(RuntimeError, match="capture_party_finalized"):
        oracles.link_oracle(bad, data_dir=data_dir)


def test_no_new_mon_refused(layout, tmp_path):
    """The flushed save is byte-identical to the boot fixture: nothing was caught."""
    boot = FIXTURES["a"].read_bytes()
    path = tmp_path / "a.SaveRAM"
    path.write_bytes(boot)
    party = codec.decode_saved_party(boot[:CART], layout, copy_name="primary")
    key = codec.key(party["mons"][0])
    results = {"a": _marker_text(saveram_path=path, cartram=boot[:CART], key=key,
                                 species=party["mons"][0]["species_id"],
                                 level=party["mons"][0]["level"]),
              "b": ""}
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "links.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="expected exactly one"):
        oracles.link_oracle(results, data_dir=str(data_dir))


def test_existing_party_mon_changed_refused(layout, tmp_path):
    save, mon = build_capture(layout, "a", species=16)
    cart = bytearray(save[:CART])
    pokemon = next(r for r in layout.regions if r.name == "pokemon")
    # Flip the STARTER's (slot 0) DV word: species-list marker is untouched, so the record
    # stays structurally decodable, but its full identity key now differs.
    dv_off = layout.addresses["wPartyMon1"] - layout.addresses["wPokemonData"] + layout.constants["MON_DVS"]
    _poke(cart, pokemon, dv_off, bytes([0xFF, 0xFF]))
    for copy_name in ("primary", "backup"):
        checksum = codec.sav_checksum(bytes(cart), layout, copy_name)
        off = layout.checksum_offsets[copy_name]
        cart[off:off + 2] = checksum.to_bytes(2, "little")
    tail = save[CART:]
    save = bytes(cart) + tail
    path = tmp_path / "a.SaveRAM"
    path.write_bytes(save)
    key = codec.key(mon)
    results = {"a": _marker_text(saveram_path=path, cartram=save[:CART], key=key,
                                 species=mon["species_id"], level=mon["level"])}
    with pytest.raises(RuntimeError, match="changed identity"):
        oracles.link_oracle(results, data_dir=str(tmp_path))


def test_ot_id_mismatch_refused(layout, tmp_path):
    save, mon = build_capture(layout, "a", species=16, ot_id=1)
    path = tmp_path / "a.SaveRAM"
    path.write_bytes(save)
    key = codec.key(mon)
    results = {"a": _marker_text(saveram_path=path, cartram=save[:CART], key=key,
                                 species=mon["species_id"], level=mon["level"])}
    with pytest.raises(RuntimeError, match="OT id"):
        oracles.link_oracle(results, data_dir=str(tmp_path))


def test_engine_capture_key_disagreement_refused(good_case):
    results, data_dir, _decoded = good_case
    capture = oracles._last_tagged(results["a"], "ENGINE_CAPTURE")
    original_line = f"ENGINE_CAPTURE {json.dumps(capture)}"
    capture["key"] = "0000:0000:01"
    bad = dict(results)
    bad["a"] = bad["a"].replace(original_line, f"ENGINE_CAPTURE {json.dumps(capture)}")
    with pytest.raises(RuntimeError, match="disagrees"):
        oracles.link_oracle(bad, data_dir=data_dir)


def test_unchanged_ball_pocket_refused(layout, tmp_path):
    save, mon = build_capture(layout, "a", species=16, ball_delta=0)
    path = tmp_path / "a.SaveRAM"
    path.write_bytes(save)
    key = codec.key(mon)
    results = {"a": _marker_text(saveram_path=path, cartram=save[:CART], key=key,
                                 species=mon["species_id"], level=mon["level"])}
    with pytest.raises(RuntimeError, match="unchanged Ball pocket"):
        oracles.link_oracle(results, data_dir=str(tmp_path))


def test_identical_full_keys_refused(layout, tmp_path):
    """Both sides somehow produce the exact same DV:OT:species key."""
    results = {}
    for inst in ("a", "b"):
        save, mon = build_capture(layout, inst, species=16, ot_id=55, dv_word=0xABCD)
        path = tmp_path / f"{inst}.SaveRAM"
        path.write_bytes(save)
        key = codec.key(mon)
        results[inst] = _marker_text(saveram_path=path, cartram=save[:CART], key=key,
                                     species=16, level=mon["level"])
    with pytest.raises(RuntimeError, match="identical full key"):
        oracles.link_oracle(results, data_dir=str(tmp_path), ot_ids={"a": 55, "b": 55})


def test_missing_links_json_refused(good_case, tmp_path):
    results, _data_dir, _decoded = good_case
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir(exist_ok=True)
    with pytest.raises(RuntimeError, match="no links.json"):
        oracles.link_oracle(results, data_dir=str(empty_dir))


def test_no_matching_link_refused(good_case, tmp_path):
    results, _data_dir, _decoded = good_case
    data_dir = tmp_path / "other"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "links.json").write_text(json.dumps({"links": []}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="expected exactly one alive"):
        oracles.link_oracle(results, data_dir=str(data_dir))


def test_altered_links_json_key_refused(good_case, tmp_path):
    results, data_dir, decoded = good_case
    document = json.loads((Path(data_dir) / "links.json").read_text(encoding="utf-8"))
    document["links"][0]["a"]["key"] = "9999:9999:01"
    (Path(data_dir) / "links.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RuntimeError, match="altered links.json"):
        oracles.link_oracle(results, data_dir=data_dir)


def test_altered_links_json_species_refused(good_case, tmp_path):
    results, data_dir, decoded = good_case
    document = json.loads((Path(data_dir) / "links.json").read_text(encoding="utf-8"))
    document["links"][0]["b"]["species"] = 999
    (Path(data_dir) / "links.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RuntimeError, match="altered links.json"):
        oracles.link_oracle(results, data_dir=data_dir)


def test_duplicate_key_elsewhere_in_links_json_refused(good_case, tmp_path):
    """The server accepted (or leaked) a key the two saves don't independently show twice."""
    results, data_dir, decoded = good_case
    document = json.loads((Path(data_dir) / "links.json").read_text(encoding="utf-8"))
    document["pending_captures"] = {"route_1": {"a": {"key": decoded["a"]["key"], "level": 5,
                                                      "species": decoded["a"]["species"]}}}
    (Path(data_dir) / "links.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RuntimeError, match="accepted something the saves don't show"):
        oracles.link_oracle(results, data_dir=data_dir)
