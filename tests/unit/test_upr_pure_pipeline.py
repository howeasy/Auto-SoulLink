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
_OVERLAY = {p: os.path.join(_REPO, "patch", "build", f"gen1_pure{t}_overlay.gbc")
            for p, t in (("a", "red"), ("b", "blue"))}
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


def test_the_pure_family_refuses_what_the_fork_cannot_honour():
    """Review cx-795d1423 #4/#5: TrainerTaggingDisabled=1 and no CanChangeTrainerText on the
    pure INI rows make these settings no-ops in stock UPR; the family refuses them by name.
    Never coerced (cx-758c671d #2): family_spec leaves an explicit selection alone so the
    Manager's build path (family_spec -> build_spec -> prepare_pair -> admit_settings) ends
    in the named refusal, and option_form marks what the pure form must disable."""
    from server.upr_settings import PURE_INERT_BOOLS, option_form
    for key in PURE_INERT_BOOLS:
        assert family_spec({key: True}, FAMILY_PURE)[key] is True
        parsed = load(build_spec({key: True, "fastest_text": False}))
        assert forbidden_enabled(parsed, FAMILY_VANILLA) == []
        assert forbidden_enabled(parsed, FAMILY_PURE) == [f"{key} (not implemented for pureRGB entries)"]
    rows = {r["key"]: r for r in option_form()}
    assert all(rows[k]["pure"] is False for k in PURE_INERT_BOOLS)
    assert rows["fastest_text"]["pure"] is False and rows["wild"]["pure"] is True
    gyms = next(c for c in rows["trainers"]["choices"] if c["value"] == "type_themed_gyms")
    assert gyms["pure"] is False and all(c["pure"] for c in rows["wild"]["choices"])
    assert family_spec({"trainers": "type_themed_gyms"}, FAMILY_PURE)["trainers"] == "type_themed_gyms"
    parsed = load(build_spec({"trainers": "type_themed_gyms", "fastest_text": False}))
    assert forbidden_enabled(parsed, FAMILY_VANILLA) == []
    assert forbidden_enabled(parsed, FAMILY_PURE) == [
        "trainers=type_themed_gyms (pure entries carry no gym/Elite tags)"]
    assert forbidden_enabled(load(build_spec(default_spec(FAMILY_PURE))), FAMILY_PURE) == []


def test_global_with_an_ignored_restriction_is_refused_for_both_families():
    """Review cx-73e80e05 #7: game1to1Encounters reads only the similar-strength restriction."""
    for restriction in ("type_themed", "catch_em_all"):
        parsed = load(build_spec({"wild": "global", "wild_restriction": restriction, "fastest_text": False}))
        for family in (FAMILY_VANILLA, FAMILY_PURE):
            assert forbidden_enabled(parsed, family) == [
                f"wild=global with wild_restriction={restriction} (UPR ignores that restriction under a global map)"]
    for restriction in ("none", "similar"):
        parsed = load(build_spec({"wild": "global", "wild_restriction": restriction, "fastest_text": False}))
        assert forbidden_enabled(parsed, FAMILY_PURE) == []
    parsed = load(build_spec({"wild": "area", "wild_restriction": "catch_em_all", "fastest_text": False}))
    assert forbidden_enabled(parsed, FAMILY_PURE) == []


def test_the_write_domains_follow_the_whole_spec_not_the_six_modes():
    """Review cx-795d1423 #11: a level curve or catch-rate tier with its parent mode unchanged
    still writes bytes; the audit domain has to come from every option."""
    from tools.upr_write_domain_diff import domains_for_spec
    off = {"wild": "unchanged", "starters": "unchanged", "trainers": "unchanged"}
    assert domains_for_spec(off) == set()
    assert domains_for_spec({**off, "wild_levels": 25}) == {"wild"}
    assert domains_for_spec({**off, "wild_min_catch_rate": 3}) == {"catch_rate"}
    assert domains_for_spec({**off, "static_levels": -10}) == {"statics"}
    assert domains_for_spec({**off, "trainers_levels": 10}) == {"trainers"}
    assert domains_for_spec({**off, "trainers_force_evolved": 30}) == {"trainers"}
    assert domains_for_spec({**off, "tm_sanity": True}) == {"tm_compat"}
    assert domains_for_spec(default_spec(FAMILY_PURE)) == {"wild", "starters", "trainers"}


def test_the_field_item_domain_is_exactly_uprs_allowed_pool():
    """Review cx-758c671d #5: the writer touches only pickups whose current item passes
    Gen1Constants.allowedItems (vanilla's list, kept by the fork), so pureRGB's HYPER BALL
    (5, vanilla's banned TOWN MAP) is not a legal target either. The constant is re-derived
    from the fork source when it is checked out."""
    import re

    from tools.upr_write_domain_diff import UPR_GEN1_ALLOWED_ITEMS, audit
    assert 5 not in UPR_GEN1_ALLOWED_ITEMS and 0x14 in UPR_GEN1_ALLOWED_ITEMS
    assert 201 in UPR_GEN1_ALLOWED_ITEMS and 196 not in UPR_GEN1_ALLOWED_ITEMS
    src = os.path.join(_REPO, ".cache", "slink-upr", "src", "com", "dabomstew", "pkrandom", "constants")
    if os.path.isdir(src):
        with open(os.path.join(src, "Gen1Items.java"), encoding="utf-8") as f:
            names = {m[1]: int(m[2]) for m in re.finditer(r"int (\w+) = (\d+);", f.read())}
        with open(os.path.join(src, "Gen1Constants.java"), encoding="utf-8") as f:
            java = f.read()
        body = java[java.index("setupAllowedItems() {"):java.index("return allowedItems;")]
        allowed = set(range(1, names["tm50"] + 1))
        for m in re.finditer(r"banSingles\(([^)]*)\)", body):
            allowed -= {names[n.strip().split(".")[-1]] for n in m[1].split(",")}
        for m in re.finditer(r"banRange\((\w+\.)?(\w+), (\d+)\)", body):
            start = names.get(m[2], {"hmsStartIndex": names["hm01"]}.get(m[2]))
            length = int(m[3]) if m[3] != "hmCount" else 5
            allowed -= set(range(start, start + length))
        allowed -= set(range(names["hm01"], names["hm01"] + 5))
        assert allowed == set(UPR_GEN1_ALLOWED_ITEMS)
    roms = _pure_roms()
    with open(roms["a"], "rb") as f:
        clean = f.read()
    assert clean[0x46206] == 0x05                        # a HYPER BALL pickup
    out = bytearray(clean)
    out[0x46206] = 0x14
    assert audit("purered", clean, bytes(out), {"field_items"})["stray"] == [0x46206]


def test_catch_rate_tier_5_owns_the_guaranteed_catch_opcode():
    """Review cx-758c671d #1: tier 5 also turns `jp z,.captured` into `jp` (CA -> C3 after
    CF 7E FE 01, 0xD1E9); that byte belongs to the catch_rate domain and nothing else does."""
    from tools.upr_write_domain_diff import audit, guaranteed_catch_byte
    roms = _pure_roms()
    with open(roms["a"], "rb") as f:
        clean = f.read()
    assert guaranteed_catch_byte(clean) == 0xD1E9 and clean[0xD1E9] == 0xCA
    out = bytearray(clean)
    out[0xD1E9] = 0xC3
    assert audit("purered", clean, bytes(out), {"catch_rate"})["stray"] == []
    assert audit("purered", clean, bytes(out), {"wild"})["stray"] == [0xD1E9]
    out[0xD1EA] ^= 0xFF                                  # the neighbour is still code
    assert audit("purered", clean, bytes(out), {"catch_rate"})["stray"] == [0xD1EA]


def test_the_field_item_domain_never_covers_a_key_item_site():
    """Review cx-795d1423 #10: the Secret Key pickup (Mansion B1F, PureRed 0x523A4) is not a
    legal write target -- a randomizer that replaced it must be caught, so the audit domain
    excludes it although the writer's walk visits it."""
    from tools.upr_write_domain_diff import audit, field_item_bytes, load_entry
    roms = _pure_roms()
    with open(roms["a"], "rb") as f:
        clean = f.read()
    assert 0x523A4 in field_item_bytes(clean, load_entry("purered")) and clean[0x523A4] == 0x2B
    out = bytearray(clean)
    out[0x523A4] = 0x14                                  # Potion where the Secret Key was
    r = audit("purered", clean, bytes(out), {"field_items"})
    assert r["stray"] == [0x523A4]


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


def test_a_randomizer_that_never_terminates_is_killed_and_refused(tmp_path):
    """Review cx-795d1423 #1: three pure settings hang the 4.6.1-slink1 jar; the pipeline must
    bound the run and kill the process tree, not wait forever. A fake java that sleeps stands
    in for the hang (no Java needed)."""
    import sys
    roms = _pure_roms()
    fake = tmp_path / "java.py"
    fake.write_text("import time; time.sleep(60)", encoding="utf-8")
    launcher = tmp_path / ("java.cmd" if os.name == "nt" else "java.sh")
    if os.name == "nt":
        launcher.write_text(f'@"{sys.executable}" "{fake}" %*', encoding="utf-8")
    else:
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$@"', encoding="utf-8")
        launcher.chmod(0o755)
    jar = _fork_jar()
    with pytest.raises(UprPipelineError, match="did not finish within 2 s"):
        randomize(jar, _settings(tmp_path, {"wild"}), roms["a"], str(tmp_path / "o.gbc"),
                  java=str(launcher), timeout=2)


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


def test_jar_entries_name_what_a_jar_can_randomize(tmp_path):
    """A jar without the overlay sections must refuse an overlay source BEFORE Java runs
    (the UI asks this up front; review cx-795d1423 #3)."""
    import zipfile

    from server.adapters.gen1_rom_scan import identify
    from server.upr_pipeline import jar_entries, jar_entry_for, jar_supports
    old = tmp_path / "old.jar"
    with zipfile.ZipFile(old, "w") as zf:
        zf.writestr("com/dabomstew/pkrandom/config/gen1_offsets.ini",
                    "[Red (U)]\nGame=POKEMON RED\n[PureRed (U)]\nGame=POKEMON RED\n")
    assert jar_entries(str(old)) == {"Red (U)", "PureRed (U)"}
    clean = {"foundation": "gen1_purergb", "variant": "purered", "kind": "clean"}
    overlay = {"foundation": "gen1_purergb", "variant": "purered", "kind": "overlay"}
    assert jar_entry_for(clean) == "PureRed (U)" and jar_entry_for(overlay) == "PureRed overlay (U)"
    assert jar_entry_for({"foundation": "gen1_rby", "variant": "red"}) is None
    assert jar_supports(str(old), clean) and not jar_supports(str(old), overlay)
    assert jar_supports(str(old), {"foundation": "gen1_rby", "variant": "red"})
    roms = _pure_roms()
    if os.path.exists(_OVERLAY["a"]):
        with open(_OVERLAY["a"], "rb") as f:
            ident = identify(f.read())
        assert ident["kind"] == "overlay"
        with pytest.raises(UprPipelineError, match="no entry for the overlay build"):
            randomize(str(old), _settings(tmp_path, {"wild"}), _OVERLAY["a"], str(tmp_path / "o.gbc"))
    jar = _fork_jar()
    assert {"PureRed (U)", "PureBlue (U)", "PureGreen (U)", "PureRed overlay (U)",
            "PureBlue overlay (U)", "PureGreen overlay (U)"} <= jar_entries(jar)
    with open(roms["a"], "rb") as f:
        assert jar_supports(jar, identify(f.read()))


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
        assert pre["roms"]["a"]["clean"] is True and pre["roms"]["a"]["title"].startswith("PureRed")
        assert pre["roms"]["b"]["clean"] is True and pre["roms"]["b"]["title"].startswith("PureBlue")
        assert "PureRed overlay (U)" in pre["jar_entries"]
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

    @pytest.mark.parametrize("cats", [
        {"wild"}, {"starters"}, {"statics"}, {"trainers"}, {"tms"}, {"field_items"},
        {"wild", "starters", "trainers"},            # the shipping default spec
        ALL_CATEGORIES,
    ], ids=lambda c: "+".join(sorted(c)))
    def test_every_category_writes_only_its_own_domain(self, tmp_path, cats):
        """T6 for every category the pure family can enable, not just wild: a category whose
        writer strays (a code byte, an unlisted table) is refused here before it ships."""
        from tools.upr_write_domain_diff import audit
        jar, roms = _fork_jar(), _pure_roms()
        out = str(tmp_path / "c.gbc")
        randomize(jar, _settings(tmp_path, cats), roms["a"], out)
        with open(roms["a"], "rb") as f:
            clean = f.read()
        with open(out, "rb") as f:
            got = f.read()
        r = audit("purered", clean, got, set(cats))
        if cats != {"starters"}:              # the original trio is a legal starters draw (cx-73e80e05 #8)
            assert r["changed"] > 0, f"{sorted(cats)} enabled but nothing changed"
        assert r["stray"] == [], [f"0x{i:06X}: {clean[i]:02X}->{got[i]:02X}" for i in r["stray"][:12]]

    @pytest.mark.parametrize("extra", [
        {"wild_levels": 25}, {"wild_min_catch_rate": 3}, {"wild_min_catch_rate": 5}, {"static_levels": -10},
        {"trainers_levels": 10}, {"trainers_force_evolved": 30}, {"tm_sanity": True},
    ], ids=lambda d: "=".join(str(x) for x in next(iter(d.items()))))
    def test_a_sub_option_alone_writes_only_its_own_domain(self, tmp_path, extra):
        """#11: each modifier with its parent mode unchanged, through the spec-derived domains."""
        from tools.upr_write_domain_diff import audit, domains_for_spec
        jar, roms = _fork_jar(), _pure_roms()
        spec = {"wild": "unchanged", "starters": "unchanged", "trainers": "unchanged",
                "fastest_text": False, **extra}
        p = tmp_path / "sub.rnqs"
        p.write_bytes(build_spec(spec))
        out = str(tmp_path / "sub.gbc")
        randomize(jar, str(p), roms["a"], out)
        with open(roms["a"], "rb") as f:
            clean = f.read()
        with open(out, "rb") as f:
            got = f.read()
        r = audit("purered", clean, got, domains_for_spec(spec))
        assert r["changed"] > 0, f"{extra} enabled but nothing changed"
        assert r["stray"] == [], [f"0x{i:06X}: {clean[i]:02X}->{got[i]:02X}" for i in r["stray"][:12]]

    @pytest.mark.parametrize("cats", [{"starters"}, {"statics"}, {"trainers"}, {"tms"}, {"field_items"}],
                             ids=lambda c: next(iter(c)))
    def test_a_pair_randomized_in_one_non_wild_category_is_accepted(self, tmp_path, cats):
        """#9: the pair check compares the produced bytes; content_hash covers only
        wild/fishing/base stats and is identical for these pairs."""
        jar, roms = _fork_jar(), _pure_roms()
        res = prepare_pair(jar, _settings(tmp_path, cats), roms, str(tmp_path / "one"))
        assert res["players"]["a"]["sha1"] != res["players"]["b"]["sha1"]
        assert res["players"]["a"]["write_domain"]["categories"] == sorted(cats)

    def test_tm_compat_writes_only_the_base_stat_tm_bytes(self, tmp_path):
        from tools.upr_write_domain_diff import audit
        jar, roms = _fork_jar(), _pure_roms()
        p = tmp_path / "tmc.rnqs"
        p.write_bytes(build_spec({"wild": "unchanged", "starters": "unchanged", "trainers": "unchanged",
                                  "tm_compat": "random", "fastest_text": False}))
        out = str(tmp_path / "tmc.gbc")
        randomize(jar, str(p), roms["a"], out)
        with open(roms["a"], "rb") as f:
            clean = f.read()
        with open(out, "rb") as f:
            got = f.read()
        r = audit("purered", clean, got, {"tm_compat"})
        assert r["changed"] > 0
        assert r["stray"] == [], [f"0x{i:06X}" for i in r["stray"][:12]]

    def test_prepare_pair_runs_the_write_domain_audit_and_refuses_a_stray_byte(self, tmp_path, monkeypatch):
        """The audit is a standing check on every produced pure pair, not a test-only tool."""
        jar, roms = _fork_jar(), _pure_roms()
        res = prepare_pair(jar, _settings(tmp_path), roms, str(tmp_path / "ok"))
        assert res["players"]["a"]["write_domain"]["changed"] > 0
        assert set(res["players"]["a"]["write_domain"]["categories"]) == ALL_CATEGORIES
        real = upr_pipeline.randomize

        def stray(jar, settings, src, out, **kw):
            info = real(jar, settings, src, out, **kw)
            with open(out, "r+b") as f:
                f.seek(0x150)                        # _Start: a code byte no category owns
                byte = f.read(1)[0]
                f.seek(0x150)
                f.write(bytes([byte ^ 0xFF]))
            return info
        monkeypatch.setattr(upr_pipeline, "randomize", stray)
        with pytest.raises(UprPipelineError, match="outside the write domain"):
            prepare_pair(jar, _settings(tmp_path), roms, str(tmp_path / "bad"))

    def test_an_overlay_pair_is_randomized_against_the_overlay_entry(self, tmp_path):
        """Review cx-795d1423 #3: the jar used to know only the clean CRCs, so an overlay source
        failed outright (or, worse, could fall back to the vanilla entry). The rebuilt jar
        carries the overlay entries; the pipeline audit must judge the output by them."""
        from tools.upr_write_domain_diff import audit
        jar = _fork_jar()
        for p in _OVERLAY.values():
            if not os.path.exists(p):
                pytest.skip(f"{p} not present")
        res = prepare_pair(jar, _settings(tmp_path), _OVERLAY, str(tmp_path / "ovl"))
        assert res["family"] == FAMILY_PURE
        assert res["players"]["a"]["write_domain"]["changed"] > 0
        with open(_OVERLAY["a"], "rb") as f:
            clean = f.read()
        with open(res["players"]["a"]["output"], "rb") as f:
            got = f.read()
        # the control: judged by the CLEAN entry the same output shows the shifted sites as stray
        assert audit("purered", clean, got, ALL_CATEGORIES)["stray"]
        assert audit("purered_overlay", clean, got, ALL_CATEGORIES)["stray"] == []

    @pytest.mark.parametrize("spec", [
        {"wild": "random", "wild_restriction": "similar"}, {"statics": "similar"},
        {"trainers": "random", "trainers_similar_strength": True}, {"wild": "global"},
    ], ids=["wild_similar", "statics_similar", "trainers_similar_strength", "wild_global"])
    def test_the_formerly_hanging_and_crashing_modes_finish(self, tmp_path, spec):
        """Review cx-795d1423 #1/#2, fixed in the fork (patch 0003: similar-strength step floor,
        global map skips the fixed sentinel slots). A bounded run: a regression hangs -> the
        pipeline kills it after 60 s and this fails instead of waiting."""
        from tools.upr_write_domain_diff import audit, domains_for_spec
        jar, roms = _fork_jar(), _pure_roms()
        full = {"wild": "unchanged", "starters": "unchanged", "trainers": "unchanged",
                "fastest_text": False, **spec}
        p = tmp_path / "m.rnqs"
        p.write_bytes(build_spec(full))
        out = str(tmp_path / "m.gbc")
        randomize(jar, str(p), roms["a"], out, timeout=60)
        with open(roms["a"], "rb") as f:
            clean = f.read()
        with open(out, "rb") as f:
            got = f.read()
        r = audit("purered", clean, got, domains_for_spec(full))
        assert r["changed"] > 0 and r["stray"] == []

    def test_an_already_randomized_pure_source_is_refused(self, tmp_path):
        jar, roms = _fork_jar(), _pure_roms()
        out = str(tmp_path / "once.gbc")
        randomize(jar, _settings(tmp_path, {"wild"}), roms["a"], out)
        with pytest.raises(UprPipelineError, match="not a clean dump"):
            prepare_pair(jar, _settings(tmp_path), {"a": out, "b": roms["b"]}, str(tmp_path / "out"))
