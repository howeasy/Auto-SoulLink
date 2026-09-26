"""Controls for native aliases, bounded table bytes, and unsupported ASM."""
from types import SimpleNamespace

import pytest

from tools import gen_gen2_charmap as generator
from tools.gen_gen2_charmap import (
    constants,
    encode,
    integer,
    parse_charmap,
    table_bytes,
    verify_table,
)

CHARMAP = '''charmap "@", $50
charmap "<ENEMY>", $3f
charmap "A", $80
charmap "é", $ea
charmap "'d", $d0
; Actual characters (from other graphics files)
charmap "⁂", $3f
; Japanese kana
charmap "ア", $80
pushc
newcharmap unown
charmap "@", $ff
popc
'''


def test_native_alias_context_cannot_overwrite_english_or_terminator():
    doc = parse_charmap(CHARMAP)
    assert doc["terminator"] == 0x50
    assert doc["glyphs"][0x80] == "A"
    assert doc["glyphs"][0x3f] == "<ENEMY>"
    assert [row["text"] for row in doc["aliases"][0x3f]] == ["<ENEMY>", "⁂"]
    assert doc["encoding"]["ア"] == 0x80
    assert doc["excluded_named_charmaps"] == ["unown"]


def test_encoding_uses_longest_token_and_preserves_native_accent():
    assert encode("A'dé@", parse_charmap(CHARMAP)["encoding"]) == bytes([0x80, 0xd0, 0xea, 0x50])
    with pytest.raises(ValueError, match="unmapped"):
        encode("Z", parse_charmap(CHARMAP)["encoding"])


@pytest.mark.parametrize("change", [lambda x: x.replace('"@", $50', '"@", $51'),
                                   lambda x: x + 'charmap "A", $81\n',
                                   lambda x: x + 'charmap unknown, $81\n',
                                   lambda x: x + 'pushc\n'])
def test_malformed_or_changed_charmap_refuses(change):
    with pytest.raises(ValueError):
        parse_charmap(change(CHARMAP))


def test_integer_source_refuses_execution_and_unknown_identifiers():
    assert integer("$ff * 95 / 100") == 242
    with pytest.raises(ValueError):
        integer("unknown + 1")
    with pytest.raises(ValueError):
        integer("__import__('os')")


def test_const_directives_preserve_holes_and_negative_step():
    result = constants("const_def $7f, -1\nconst EVENT\nconst GIFT\nconst_next 2\nshift_const FLAG")
    assert result == {"EVENT": 127, "GIFT": 126, "FLAG": 4}
    with pytest.raises(ValueError, match="unsupported"):
        constants("const_def\nIF _GOLD\nconst A\nENDC")


def test_rom_table_bounds_and_literal_mismatch_refuse():
    ctx = SimpleNamespace(rom=b"\x00" * 0x8000, symbol=lambda _: (1, 0x7fff))
    assert table_bytes(ctx, "Table", 1) == (0x7fff, b"\x00")
    with pytest.raises(ValueError, match="bounds"):
        table_bytes(ctx, "Table", 2)
    with pytest.raises(ValueError, match="mismatch"):
        verify_table(ctx, "Table", b"\x01")


def test_check_refuses_stale_pack_without_touching_bytes_or_mtime(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "load_context", lambda title, root: SimpleNamespace(title=title))
    path = tmp_path / "data/games/gen2_crystal/test.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"stale\n")
    before = path.read_bytes(), path.stat().st_mtime_ns
    assert generator.run_cli(["--root", str(tmp_path), "--title", "crystal", "--check"],
                             lambda ctx: {"title": ctx.title}, "test.json") == 1
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_late_title_validation_failure_does_not_publish_earlier_title(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "load_context", lambda title, root: SimpleNamespace(title=title))

    def build(ctx):
        if ctx.title == "gold":
            raise ValueError("corrupt second title source")
        return {"title": ctx.title}

    assert generator.run_cli(["--root", str(tmp_path)], build, "test.json") == 1
    assert not list((tmp_path / "data").rglob("test.json"))
