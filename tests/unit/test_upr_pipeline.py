"""Producing the pair is easy; refusing to produce a bad one is the job.

A Soul Link run on randomized cartridges is fair only if both players got the SAME settings
and DIFFERENT seeds, and neither is checkable from the ROMs afterwards. So most of these
tests are about the refusals, and they are written so they do not need a jar: the validation
order is arranged to reject on the settings file and the arguments BEFORE spending a
subprocess, which makes it testable and also means an obviously bad request fails fast.

The end-to-end tests do need the real jar and skip without one (SLINK_UPR_JAR).
"""
from __future__ import annotations

import os

import pytest

from server import upr_pipeline
from server.upr_pipeline import (
    UprPipelineError,
    _check_content,
    _parse_log,
    _sha1,
    prepare_pair,
    randomize,
)
from server.upr_settings import build, build_categories

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_RED = os.path.join(_REPO, "patch", "build", "gen1_red.gb")
_BLUE = os.path.join(_REPO, "patch", "build", "gen1_blue.gb")
ALL_CATEGORIES = {"wild", "starters", "statics", "trainers", "tms", "field_items"}


def _jar() -> str:
    from tests.conftest import find_upr_jar
    jar = find_upr_jar()
    if not jar:
        pytest.skip("PokeRandoZX.jar not found — put it in .cache/upr/ or set SLINK_UPR_JAR")
    return jar


def _settings(tmp_path, **kw):
    p = tmp_path / "s.rnqs"
    p.write_bytes(build_categories(ALL_CATEGORIES, **kw))
    return str(p)


def _roms():
    for p in (_RED, _BLUE):
        if not os.path.exists(p):
            pytest.skip(f"{p} not present")
    return {"a": _RED, "b": _BLUE}


# ── reading the log ──────────────────────────────────────────────────────────────────────
def test_the_log_is_utf8_with_a_bom_and_the_settings_line_has_no_separator(tmp_path):
    """Both are real properties of UPR's output, and both break a naive reader.

    The BOM makes the first line start with \\ufeff under plain utf-8, and the settings line
    is the version integer immediately followed by Base64 (Randomizer.java writes
    VERSION + toString()), so there is nothing to split on.
    """
    log = tmp_path / "x.gbc.log"
    body = build_categories({"wild"})
    import struct
    b64 = body[8:8 + struct.unpack(">i", body[4:8])[0]].decode()
    log.write_bytes("﻿".encode() + (
        f"Randomizer Version: 4.6.1\n"
        f"Random Seed: 245612651677283\n"
        f"Settings String: 322{b64}\n").encode())
    got = _parse_log(str(log))
    assert got["seed"] == 245612651677283
    assert got["version"] == "4.6.1"
    assert got["settings_string"].startswith("322")


def test_a_log_without_a_seed_is_refused(tmp_path):
    """Without -l there is no seed anywhere; UPR's CLI has no seed flag to ask for one."""
    log = tmp_path / "x.gbc.log"
    log.write_text("Randomizer Version: 4.6.1\nnothing useful here\n", encoding="utf-8")
    with pytest.raises(UprPipelineError, match="no seed or settings line"):
        _parse_log(str(log))


def test_an_out_of_range_seed_is_refused(tmp_path):
    """RandomSource.pickSeed packs 6 bytes, so a real seed is always under 2^48."""
    log = tmp_path / "x.gbc.log"
    log.write_text(f"Random Seed: {1 << 60}\nSettings String: 322AAAA\n", encoding="utf-8")
    with pytest.raises(UprPipelineError, match="48-bit"):
        _parse_log(str(log))


# ── argument refusals, no subprocess needed ──────────────────────────────────────────────
def test_randomizing_a_rom_over_itself_is_refused(tmp_path):
    s = _settings(tmp_path)
    # __file__ stands in for the jar: it exists, so the existence checks pass and the
    # refusal under test is the one that fires.
    _roms()   # the refusal fires after the existence checks, so the dump must be present
    with pytest.raises(UprPipelineError, match="same file"):
        randomize(__file__, s, _RED, _RED)


def test_a_non_gbc_output_is_refused(tmp_path):
    """UPR APPENDS .gbc rather than replacing, so -o out.gb produces out.gb.gbc.

    Refusing up front is better than discovering the artifact somewhere unexpected.
    """
    s = _settings(tmp_path)
    _roms()
    with pytest.raises(UprPipelineError, match="must end in .gbc"):
        randomize(__file__, s, _RED, str(tmp_path / "out.gb"))


@pytest.mark.parametrize("missing", ["jar", "settings", "source ROM"])
def test_a_missing_input_is_named(tmp_path, missing):
    s = _settings(tmp_path)
    args = {"jar": str(tmp_path / "nope.jar"), "settings_path": s, "source_rom": _RED}
    if missing == "settings":
        args["settings_path"] = str(tmp_path / "nope.rnqs")
    elif missing == "source ROM":
        args["source_rom"] = str(tmp_path / "nope.gb")
    else:
        pass
    if missing != "jar":
        args["jar"] = __file__          # exists, so the named failure is the intended one
    with pytest.raises(UprPipelineError, match=missing):
        randomize(output_rom=str(tmp_path / "o.gbc"), **args)


# ── settings refusals, before any subprocess ─────────────────────────────────────────────
def test_settings_that_touch_rule_data_are_refused(tmp_path):
    """Types and evolutions decide the type and species clauses."""
    p = tmp_path / "bad.rnqs"
    p.write_bytes(build({"types_UNCHANGED": False}))
    with pytest.raises(UprPipelineError, match="change data the Soul Link rules read"):
        prepare_pair("jar", str(p), _roms(), str(tmp_path / "out"))


def test_an_older_settings_version_is_refused(tmp_path):
    """UPR would run SettingsUpdater and merely warn, but an updated file is not the file
    the other player used, so "same settings" would quietly stop being true."""
    import struct
    raw = bytearray(build_categories({"wild"}))
    raw[:4] = struct.pack(">i", 321)
    p = tmp_path / "old.rnqs"
    p.write_bytes(bytes(raw))
    with pytest.raises(UprPipelineError, match="not 4.6.1"):
        prepare_pair("jar", str(p), _roms(), str(tmp_path / "out"))


def test_both_players_are_required(tmp_path):
    s = _settings(tmp_path)
    with pytest.raises(UprPipelineError, match="players a and b"):
        prepare_pair("jar", s, {"a": _RED}, str(tmp_path / "out"))


def test_identical_seeds_are_refused(tmp_path, monkeypatch):
    """Cannot be forced through the real jar -- UPR picks its own seed -- so the check is
    exercised directly. Without it a pair could silently share one table."""
    s = _settings(tmp_path)

    def fake(jar, settings_path, source_rom, output_rom, java="java", timeout=0):
        return {"seed": 42, "settings_string": "322", "output": output_rom,
                "log": output_rom + ".log", "sha1": "x", "source_sha1": "y", "version": "4.6.1"}

    monkeypatch.setattr(upr_pipeline, "randomize", fake)
    monkeypatch.setattr(upr_pipeline, "parse_settings_string",
                        lambda _s: {"flags": {}, "misc_tweaks": 0})
    monkeypatch.setattr(upr_pipeline, "forbidden_enabled", lambda _p, _family=None: [])
    monkeypatch.setattr(upr_pipeline, "categories_enabled", lambda _p: {"wild"})
    monkeypatch.setattr(upr_pipeline, "spec_from_parsed", lambda _p: {"wild": "random"})
    monkeypatch.setattr(upr_pipeline, "_check_content", lambda _s, _o: {"wild": {}})
    with pytest.raises(UprPipelineError, match="both players got seed 42"):
        prepare_pair("jar", s, _roms(), str(tmp_path / "out"))


# ── the real thing ───────────────────────────────────────────────────────────────────────
class TestAgainstTheRealJar:
    def test_a_pair_is_produced_with_different_seeds_and_content(self, tmp_path):
        res = prepare_pair(_jar(), _settings(tmp_path), _roms(), str(tmp_path / "out"))
        assert res["upr_version"] in upr_pipeline.ACCEPTED_UPR_VERSIONS
        assert res["family"] == "gen1_rby"
        assert set(res["categories"]) == ALL_CATEGORIES
        a, b = res["players"]["a"], res["players"]["b"]
        assert a["seed"] != b["seed"], "the whole point of the pairing"
        assert a["content_hash"] != b["content_hash"]
        assert a["sha1"] != b["sha1"]
        for side in (a, b):
            assert os.path.exists(side["output"]) and os.path.exists(side["log"])
            assert 0 <= side["seed"] < (1 << 48)

    def test_the_source_rom_is_left_untouched(self, tmp_path):
        """Randomizing must never consume the clean dump it was given."""
        roms = _roms()
        before = _sha1(_RED)
        prepare_pair(_jar(), _settings(tmp_path), roms, str(tmp_path / "out"))
        assert _sha1(_RED) == before

    def test_an_already_randomized_source_is_refused(self, tmp_path):
        """Randomizing a randomized ROM makes the result unreproducible: its provenance is
        two seeds deep and the pipeline can only account for one."""
        first = prepare_pair(_jar(), _settings(tmp_path), _roms(), str(tmp_path / "out"))
        once = first["players"]["a"]["output"]
        with pytest.raises(UprPipelineError, match="not a clean dump"):
            prepare_pair(_jar(), _settings(tmp_path), {"a": once, "b": _BLUE},
                         str(tmp_path / "out2"))

    def test_the_effective_settings_are_read_back_not_assumed(self, tmp_path):
        """tweakForRom mutates settings in place and the CLI discards its own report of it.

        The categories reported here come from the LOG, so they are what actually ran.
        """
        res = prepare_pair(_jar(), _settings(tmp_path), _roms(), str(tmp_path / "out"))
        assert res["players"]["a"]["categories"] == res["players"]["b"]["categories"]
        assert set(res["players"]["a"]["categories"]) == ALL_CATEGORIES

    def test_a_wild_only_run_leaves_types_and_base_stats_alone(self, tmp_path):
        """The check that makes 'types deviate' mean 'a forbidden setting was on'.

        UPR rewrites every base-stat record on every save regardless of settings, so this
        passing is a real measurement, not a tautology.
        """
        p = tmp_path / "wild.rnqs"
        p.write_bytes(build_categories({"wild"}))
        res = prepare_pair(_jar(), str(p), _roms(), str(tmp_path / "out"))
        assert res["categories"] == ["wild"]


# ── evolutions must survive the round trip unchanged ─────────────────────────────────

class TestEvolutionDrift:
    """UPR rewrites and REPOINTS the evolution region on every save, so the check that
    catches a real change has to compare the logical graph rather than the bytes.

    Both halves are load-bearing and pull in opposite directions:
      * a wild-only randomization must PASS despite every record having moved;
      * an actually-altered evolution target must FAIL.
    A check that only did the second could be satisfied by comparing bytes, and would then
    reject every legitimate run.
    """

    def _rom(self, path):
        if not os.path.exists(path):
            pytest.skip(f"{path} not present (ROMs are gitignored)")
        with open(path, "rb") as f:
            return f.read()

    def _mutated(self, tmp_path, rom: bytes) -> str:
        """Change one evolution TARGET, leaving the layout alone.

        Deliberately not a byte-scramble: the point is to prove the check sees a semantic
        change, not that it notices corruption.
        """
        from server.adapters.gen1_rom_scan import _syms_for, sym_to_offset
        _, syms = _syms_for(rom)
        base = sym_to_offset(syms["EvosMovesPointerTable"])
        bank = base & ~0x3FFF
        out = bytearray(rom)
        for i in range(190):
            lo, hi = rom[base + 2 * i], rom[base + 2 * i + 1]
            off = bank + ((lo | (hi << 8)) - 0x4000)
            if rom[off] == 1:                       # EVOLVE_LEVEL: method, level, species
                out[off + 2] = (rom[off + 2] % 190) + 1
                break
        else:
            pytest.fail("no level evolution found to mutate — the scan is wrong")
        path = str(tmp_path / "mutated.gbc")
        with open(path, "wb") as f:
            f.write(bytes(out))
        return path

    def test_a_changed_evolution_target_is_refused(self, tmp_path):
        rom = self._rom(_RED)
        mutated = self._mutated(tmp_path, rom)
        with pytest.raises(UprPipelineError, match="evolution targets differ"):
            _check_content(_RED, mutated)

    def test_the_mutation_is_actually_visible_in_the_graph(self, tmp_path):
        """Control: if the mutation did not change the graph, the test above would be
        asserting on something else entirely."""
        from server.adapters.gen1_rom_scan import evolution_graph
        rom = self._rom(_RED)
        mutated = self._mutated(tmp_path, rom)
        with open(mutated, "rb") as f:
            assert evolution_graph(f.read()) != evolution_graph(rom)

    def test_an_unmodified_copy_still_passes(self, tmp_path):
        """The other control, and the one that matters most: repacking is not drift.
        A check strict enough to fail here would reject every real randomized run."""
        rom = self._rom(_RED)
        same = str(tmp_path / "same.gbc")
        with open(same, "wb") as f:
            f.write(rom)
        _check_content(_RED, same)      # must not raise
