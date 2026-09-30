"""RF-5: the Manager must use the same validated symbol spans as ROM decoding."""
import pytest

from server import upr_pipeline
from server.adapters import gen3_rom_tables


@pytest.mark.parametrize("address,size", (("07ffffc8", "0000001c"), ("08000000", "0000001d")),
                         ids=("negative-rom-base", "not-a-whole-record"))
def test_malformed_species_symbol_is_a_named_pipeline_refusal(tmp_path, monkeypatch, address, size):
    (tmp_path / "pokefirered.sym").write_text(
        "08000100 g 00000028 gTrainers\n"
        "08000200 g 00000014 gWildMonHeaders\n"
        "08000300 g 00000028 gEvolutionTable\n"
        f"{address} g {size} gSpeciesInfo\n", encoding="utf-8")
    monkeypatch.setattr(gen3_rom_tables, "SYMBOL_DIR", tmp_path)
    # With base -56 and size 28, Python slicing used to read the penultimate ROM record.
    # A 29-byte span used to escape as a raw ValueError instead of UprPipelineError.
    with pytest.raises(upr_pipeline.UprPipelineError, match="gSpeciesInfo"):
        upr_pipeline._gen3_species_rules(bytes(56), "firered")
