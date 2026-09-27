"""RF-3: immutable pinned symbol files are read once per title/source directory."""
from pathlib import Path

import pytest

from server.adapters.gen3_rom_tables import table_symbols

SYMS = ("08000100 g 00000028 gTrainers\n"
        "08000200 g 00000014 gWildMonHeaders\n"
        "08000300 g 00000028 gEvolutionTable\n"
        "08000500 g 0000001c gSpeciesInfo\n")


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
def test_repeated_table_decodes_reuse_the_pinned_symbols(tmp_path, monkeypatch, title):
    path = tmp_path / f"poke{title}.sym"
    path.write_text(SYMS, encoding="utf-8")
    reads = []
    real = Path.read_text

    def read_text(self, *args, **kwargs):
        if self == path:
            reads.append(self)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    for _ in range(5):
        assert table_symbols(title, symbol_dir=tmp_path)["gTrainers"]["count"] == 1
    assert reads == [path], "each hello decode re-read the same .sym file"


def test_the_symbol_cache_keeps_fixture_directories_separate(tmp_path):
    for directory, address in (("first", "08000100"), ("second", "08000400")):
        root = tmp_path / directory
        root.mkdir()
        (root / "pokefirered.sym").write_text(SYMS.replace("08000100", address), encoding="utf-8")
    assert table_symbols("firered", symbol_dir=tmp_path / "first")["gTrainers"]["address"] == 0x08000100
    assert table_symbols("firered", symbol_dir=tmp_path / "second")["gTrainers"]["address"] == 0x08000400
