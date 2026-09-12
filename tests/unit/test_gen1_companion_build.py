"""Exact legal ROM inputs and RGBDS are explicit local release prerequisites."""

import hashlib
import json
from pathlib import Path

import pytest

from patch.tools.make_ups import ups_apply
from server.gen1_admission import AdmissionError
from server.gen1_cartridge_profiles import companion_profiles, contract_from_files
from tools.build_gen1_companion import CATALOG, ROOT, build, catalog, outputs


def test_rebuild_reproduces_both_generated_catalogs_without_rom_distribution():
    data = catalog()
    for path, content in outputs(data).items():
        assert path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_companion_has_exact_spans_header_full_file_hashes_and_round_trip(variant, tmp_path):
    manifest = build(variant)
    profile = companion_profiles()[variant]
    final = (ROOT / manifest["output"]).read_bytes()
    lock = json.loads((ROOT / "data/pret_sources.lock.json").read_text())
    base_name = {"red": "pokered", "blue": "pokeblue", "yellow": "pokeyellow"}[variant]
    base = (ROOT / lock["clean_roms"][base_name]["filename"]).read_bytes()
    patch = (ROOT / manifest["companion"]["ups"]).read_bytes()
    assert len(final) == len(base) == 0x100000 and final[0x100:0x150] == base[0x100:0x150]
    assert ups_apply(base, patch) == final
    assert hashlib.sha256(final).hexdigest() == profile["rom_sha256"]
    assert hashlib.sha1(final).hexdigest() == profile["final_rom_sha1"]
    contract = contract_from_files({"a": ROOT / manifest["output"], "b": ROOT / manifest["output"]})
    assert contract["players"]["a"]["capabilities"]["pc_trade"]
    changed = bytearray(final)
    changed[0x90000] ^= 1
    invalid = tmp_path / "unknown.gb"
    invalid.write_bytes(changed)
    with pytest.raises(AdmissionError):
        contract_from_files({"a": invalid, "b": ROOT / manifest["output"]})
    assert CATALOG.parent == Path(ROOT / "data/games/gen1_rby")
