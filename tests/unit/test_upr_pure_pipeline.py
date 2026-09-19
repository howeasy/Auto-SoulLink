"""The randomized-pair pipeline on the pureRGB family (docs/purergb/PLAN.md §6 M5, gate G5).

Mirrors tests/unit/test_upr_pipeline.py for the pure titles. The family runs only on the
SLink fork jar (4.6.1-slink1): the refusals are tested without Java, everything that needs
the jar skips when it is absent (build it with tools/build_upr_fork.py; find_upr_jar looks
in .cache/slink-upr/) or when the pinned pure ROMs are not under patch/build/.
"""
from __future__ import annotations

import os

import pytest

from server import upr_pipeline
from server.upr_pipeline import (
    PUREGB_RANDOMIZER_REFUSAL,
    UprPipelineError,
    _sha1,
    family_of,
    jar_is_fork,
    preflight,
    prepare_pair,
    randomize,
)
from server.upr_settings import (
    FAMILY_PURE,
    FAMILY_VANILLA,
    build_categories,
    build_spec,
    default_spec,
    family_spec,
    forbidden_enabled,
    load,
)

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_PURERED = os.path.join(_REPO, "patch", "build", "gen1_purered.gbc")
_PUREBLUE = os.path.join(_REPO, "patch", "build", "gen1_pureblue.gbc")
_RED = os.path.join(_REPO, "patch", "build", "gen1_red.gb")
ALL_CATEGORIES = {"wild", "starters", "statics", "trainers", "tms", "field_items"}


def _fork_jar() -> str:
    from tests.conftest import find_upr_jar
    jar = find_upr_jar()
    if not jar or not jar_is_fork(jar):
        pytest.skip("the SLink fork jar (4.6.1-slink1) is not present — tools/build_upr_fork.py")
    return jar


def _pure_roms() -> dict[str, str]:
    for p in (_PURERED, _PUREBLUE):
        if not os.path.exists(p):
            pytest.skip(f"{p} not present")
    return {"a": _PURERED, "b": _PUREBLUE}


def _settings(tmp_path, cats=ALL_CATEGORIES, **kw):
    p = tmp_path / "s.rnqs"
    p.write_bytes(build_categories(cats, fastest_text=False, **kw))
    return str(p)


# ── the allowlist, no Java ───────────────────────────────────────────────────────────────
def test_the_pure_family_turns_every_tweak_off():
    """pureRGB has instant text natively and the fork offers no tweak; a file that asks for
    one would be silently trimmed by tweakForRom, so it is refused up front instead."""
    assert default_spec(FAMILY_VANILLA)["fastest_text"] is True
    assert default_spec(FAMILY_PURE)["fastest_text"] is False
    spec = family_spec({"fastest_text": True, "pc_potion": True, "wild": "random"}, FAMILY_PURE)
    assert spec["fastest_text"] is False and spec["pc_potion"] is False and spec["wild"] == "random"
    parsed = load(build_spec({"fastest_text": True}))
    assert forbidden_enabled(parsed, FAMILY_VANILLA) == []
    assert forbidden_enabled(parsed, FAMILY_PURE) == ["tweaks (FASTEST_TEXT)"]
    assert forbidden_enabled(load(build_spec(default_spec(FAMILY_PURE))), FAMILY_PURE) == []


def test_a_settings_file_with_a_tweak_is_refused_for_a_pure_pair(tmp_path):
    roms = _pure_roms()
    p = tmp_path / "ft.rnqs"
    p.write_bytes(build_categories({"wild"}, fastest_text=True))
    with pytest.raises(UprPipelineError, match="tweaks \\(FASTEST_TEXT\\)"):
        prepare_pair("jar", str(p), roms, str(tmp_path / "out"))


def test_a_pure_and_a_vanilla_rom_do_not_pair(tmp_path):
    _pure_roms()
    if not os.path.exists(_RED):
        pytest.skip("vanilla Red not present")
    with pytest.raises(UprPipelineError, match="different families"):
        family_of({"a": _PURERED, "b": _RED})
    with pytest.raises(UprPipelineError, match="different families"):
        prepare_pair("jar", _settings(tmp_path), {"a": _PURERED, "b": _RED}, str(tmp_path / "out"))


def test_the_family_is_read_off_the_roms():
    roms = _pure_roms()
    assert family_of(roms) == FAMILY_PURE
    if os.path.exists(_RED):
        assert family_of({"a": _RED, "b": _RED}) == FAMILY_VANILLA


def test_the_stock_jar_refuses_the_pure_family(tmp_path, monkeypatch):
    """Without the fork there is no entry for the cartridge; preflight greys it with the
    reason and randomize() refuses before spending a subprocess."""
    roms = _pure_roms()
    monkeypatch.setattr(upr_pipeline, "jar_is_fork", lambda _jar: False)
    pre = preflight(__file__, roms)
    assert pre["jar_fork"] is False
    assert pre["roms"]["a"]["clean"] is False
    assert pre["roms"]["a"]["title"] == PUREGB_RANDOMIZER_REFUSAL
    assert pre["ok"] is False
    with pytest.raises(UprPipelineError, match="needs SLink's UPR fork"):
        randomize(__file__, _settings(tmp_path), _PURERED, str(tmp_path / "o.gbc"))


def test_jar_is_fork_reads_the_entries_not_the_name(tmp_path):
    import zipfile
    fake = tmp_path / "PokeRandoZX.jar"
    with zipfile.ZipFile(fake, "w") as zf:
        zf.writestr("com/dabomstew/pkrandom/config/gen1_offsets.ini", "[Red (U)]\nGame=POKEMON RED\n")
    assert jar_is_fork(str(fake)) is False
    with zipfile.ZipFile(fake, "w") as zf:
        zf.writestr("com/dabomstew/pkrandom/config/gen1_offsets.ini", "[Red (U)]\n[PureRed (U)]\nLosslessMode=1\n")
    assert jar_is_fork(str(fake)) is True
    assert jar_is_fork(str(tmp_path / "missing.jar")) is False


# ── the real thing ───────────────────────────────────────────────────────────────────────
class TestAgainstTheForkJar:
    def test_preflight_ungreys_a_clean_pure_rom(self):
        jar, roms = _fork_jar(), _pure_roms()
        pre = preflight(jar, roms)
        assert pre["jar_fork"] is True
        assert pre["roms"]["a"]["clean"] is True and "purered" in pre["roms"]["a"]["title"]
        assert pre["roms"]["b"]["clean"] is True and "pureblue" in pre["roms"]["b"]["title"]
        assert pre["ok"] is True

    def test_everything_off_is_byte_identical(self, tmp_path):
        """C1's lossless baseline, through the exact CLI call the pipeline makes."""
        jar, roms = _fork_jar(), _pure_roms()
        for pid, src in roms.items():
            out = str(tmp_path / f"{pid}.gbc")
            info = randomize(jar, _settings(tmp_path, set()), src, out)
            assert info["version"] == "4.6.1-slink1"
            assert info["sha1"] == _sha1(src), f"{pid}: load->save changed bytes"

    def test_a_pair_is_produced_with_different_seeds_and_content(self, tmp_path):
        jar, roms = _fork_jar(), _pure_roms()
        res = prepare_pair(jar, _settings(tmp_path), roms, str(tmp_path / "out"))
        assert res["upr_version"] == "4.6.1-slink1"
        assert res["family"] == FAMILY_PURE
        assert set(res["categories"]) == ALL_CATEGORIES
        a, b = res["players"]["a"], res["players"]["b"]
        assert a["seed"] != b["seed"]
        assert a["content_hash"] != b["content_hash"]
        assert a["fingerprint"] != b["fingerprint"]
        assert _sha1(_PURERED) == a["source_sha1"], "the clean dump is left untouched"

    def test_a_wild_only_run_writes_only_wild_tables(self, tmp_path):
        """T6: every changed byte lies in the write domain of the enabled category."""
        from tools.upr_write_domain_diff import audit
        jar, roms = _fork_jar(), _pure_roms()
        out = str(tmp_path / "w.gbc")
        randomize(jar, _settings(tmp_path, {"wild"}), roms["a"], out)
        with open(roms["a"], "rb") as f:
            clean = f.read()
        with open(out, "rb") as f:
            got = f.read()
        r = audit("purered", clean, got, {"wild"})
        assert r["changed"] > 0 and r["stray"] == [], r["stray"][:10]
        # and the audit is not vacuous: the same output is outside the starters domain
        assert audit("purered", clean, got, {"starters"})["stray"]

    def test_an_already_randomized_pure_source_is_refused(self, tmp_path):
        jar, roms = _fork_jar(), _pure_roms()
        out = str(tmp_path / "once.gbc")
        randomize(jar, _settings(tmp_path, {"wild"}), roms["a"], out)
        with pytest.raises(UprPipelineError, match="not a clean dump"):
            prepare_pair(jar, _settings(tmp_path), {"a": out, "b": roms["b"]}, str(tmp_path / "out"))
