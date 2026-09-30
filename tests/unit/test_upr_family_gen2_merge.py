"""Landing-merge guard: a Gen 2 pair keeps its own family through family_of (master's Gen 2 branch
and the Gen 3 branch both live in the same loop; a merge that let one overwrite the other would
report the wrong family), and every family the Manager can name has display words."""
import hashlib

from server import manager, upr_pipeline


def test_gen2_pair_is_the_gen2_family(tmp_path, monkeypatch):
    rom = bytes(range(256)) * 4096                       # 1 MiB, not a GBA image
    for name in ("a.gbc", "b.gbc"):
        (tmp_path / name).write_bytes(rom)
    monkeypatch.setattr(upr_pipeline, "_gen2_clean_sha1s",
                        lambda: {hashlib.sha1(rom).hexdigest(): "crystal"})
    fam = upr_pipeline.family_of({"a": str(tmp_path / "a.gbc"), "b": str(tmp_path / "b.gbc")})
    assert fam == upr_pipeline.FAMILY_GEN2


def test_every_manager_family_has_words():
    assert "gen2" in manager.GAME_FAMILY and "gen3" in manager.GAME_FAMILY and "gen3_e" in manager.GAME_FAMILY
    assert set(manager.GAME_FAMILY.values()) <= set(manager.FAMILY_WORDS)
