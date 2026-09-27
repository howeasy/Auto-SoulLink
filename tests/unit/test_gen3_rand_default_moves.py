"""RF-2 F5: sparse reports do not prove the cartridge's level-up learnsets."""
import struct

import pytest

from server.adapters import gen3_frlge, gen3_rom_tables
from tests.unit.test_gen3_rom_ingest import _clean, _payload


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
@pytest.mark.parametrize("kind", ("rand", "clean"))
def test_unshipped_learnset_edit_cannot_publish_inferred_default_moves(title, kind):
    clean = _clean(title)
    raw = bytearray(clean)
    head, _ = gen3_frlge._symbol(title, "gLevelUpLearnsets")
    learnset = struct.unpack_from("<I", raw, head - gen3_rom_tables.ROM_BASE + 19 * 4)[0]
    offset = learnset - gen3_rom_tables.ROM_BASE
    assert struct.unpack_from("<H", raw, offset)[0] == (1 << 9) | 33  # Rattata: Tackle
    struct.pack_into("<H", raw, offset, (1 << 9) | 150)              # SYNTH: Splash
    report = _payload(bytes(raw), title)
    assert report == _payload(clean, title), "this edit is outside the shipped table closure"
    # Clean-equivalent reports may normalize rand to clean: neither effective kind is proof.
    adapter = gen3_frlge.Gen3Adapter(rom_type=title, artifact_kind=kind)
    adapter.use_rom_encounters(adapter.ingest_rom_content(report))
    ben = adapter.trainer_party(89)
    assert ben[0]["species"] == "Rattata"
    assert "moves" not in ben[0], "cartridge learnsets were not shipped or verified"
    # An explicit trainer moveset IS part of the report and remains available.
    assert adapter.trainer_party(414)[0]["moves"] == ["Tackle", "Defense Curl"]
