"""tools/upr_pure_verify.py against the real fork output (docs/purergb/PLAN.md §6 M5).

test_upr_pure_pipeline.py proves the fork is lossless and writes inside the byte domain;
this proves what it writes is a valid game AND that each mode did what its label claims
(review cx-795d1423 #13-#17): every mode is randomized once through
server.upr_pipeline.randomize and handed to verify() with the spec it was built from. Every
per-mode check has a negative twin that hand-corrupts the output and requires the verifier
to notice — a verifier that cannot fail proves nothing. The fork CLI has no seed flag, so
only properties that hold for any seed are asserted. trainers=type_themed still crashes the
jar (see its xfail reason); wild=global / statics=similar / similar_strength were fixed in the
fork while this was written and are load-bearing. The clean-vs-clean control and the
synthetic global pair need no Java and run whenever the pure ROMs are present.
"""
from __future__ import annotations

import json
import os
import random
import time

import pytest

from server.upr_pipeline import UprPipelineError, randomize
from server.upr_settings import FAMILY_PURE, build_spec, default_spec
from tests.unit.test_upr_pure_pipeline import _fork_jar, _pure_roms
from tools.upr_pure_verify import CATEGORIES, FIELD_POOL, TM_ITEM0, _Check, _upr_item_sites, verify
from tools.upr_write_domain_diff import (
    INI,
    domains_for_spec,
    field_item_bytes,
    guaranteed_catch_byte,
    load_entry,
)

_MODES = ("wild", "starters", "statics", "trainers", "tms", "field_items")
CASES = [{c} for c in _MODES] + [{"tm_compat"}, {"wild", "starters", "trainers"}, set(_MODES) | {"tm_compat"}]
_ROM_CACHE: dict[str, bytes] = {}
ZAPDOS, MEWTWO, MAROWAK = 0x4B, 0x83, 0x91          # internal ids; the ghost static holds Marowak on a clean ROM
XFAIL_TIMEOUT = 45                                   # a healthy run is < 5 s; a hang must not eat the budget


def _clean() -> bytes:
    path = _pure_roms()["a"]
    if path not in _ROM_CACHE:
        with open(path, "rb") as f:
            _ROM_CACHE[path] = f.read()
    return _ROM_CACHE[path]


def _spec(**kw) -> dict:
    """A full OPTIONS spec: every mode unchanged, every curve 0, the family's other defaults
    (wild/trainers block legendaries ON), then ``kw``."""
    spec = {**default_spec(FAMILY_PURE), **dict.fromkeys(_MODES, "unchanged"), "tm_compat": "unchanged"}
    spec.update(kw)
    return spec


def _cases(cats: set[str]) -> dict:
    return _spec(**{c: "random" for c in cats if c in _MODES}, tm_compat="random" if "tm_compat" in cats else "unchanged")


def _verify(out: bytes, spec: dict) -> dict:
    return verify("purered", _clean(), out, spec=spec)


def _walk(out: bytes, spec: dict) -> _Check:
    """A verifier instance after a run: its wild tables / trainer parties locate corruption sites."""
    chk = _Check("purered", _clean(), out, None, False, False, INI, spec)
    chk.run()
    chk.tables = chk._wild_tables()
    return chk


def _live(chk: _Check, table: dict) -> list[tuple[int, int]]:
    """(level site, species site) of the table's randomizable slots."""
    return [(lv, sp) for lv, sp in table["slots"] if chk.clean[sp] in chk.f["ordinary"]]


@pytest.fixture(scope="module")
def randomized(tmp_path_factory):
    """One randomize per spec for the whole module; the negative tests reuse the outputs.
    Another agent may be rebuilding the jar: a failed run is retried once a minute later."""
    jar, roms = _fork_jar(), _pure_roms()
    dir_ = str(tmp_path_factory.mktemp("verify"))
    outs: dict[str, bytes] = {}

    def get(spec: dict, timeout: int | None = None, retry: bool = True) -> bytes:
        key = json.dumps(spec, sort_keys=True)
        if key not in outs:
            n = len(outs)
            settings = os.path.join(dir_, f"s{n}.rnqs")
            with open(settings, "wb") as f:
                f.write(build_spec(spec))
            out = os.path.join(dir_, f"o{n}.gbc")
            kw = {"timeout": timeout} if timeout else {}
            try:
                randomize(jar, settings, roms["a"], out, **kw)
            except UprPipelineError as first:
                if not retry:
                    raise
                time.sleep(60)
                try:
                    randomize(jar, settings, roms["a"], out, **kw)
                except UprPipelineError as second:
                    # the retry's own error would otherwise silently replace the first failure;
                    # a flaky jar and a consistently broken one need to read differently
                    raise UprPipelineError(
                        f"generation failed twice for spec={spec}: first attempt {first!r}, "
                        f"retry {second!r}"
                    ) from second
            with open(out, "rb") as f:
                outs[key] = f.read()
        return outs[key]
    return get


def test_the_clean_rom_verifies_against_itself():
    """The control: nothing enabled, nothing changed, every semantic check holds on the
    clean bytes (a check that fails here is measuring the ROM, not the fork)."""
    clean = _clean()
    for r in (verify("purered", clean, clean, set()), verify("purered", clean, clean, spec=_spec())):
        assert r["ok"], r["failures"]
        assert all(n == 0 for n in r["changed"].values())


def test_a_synthetic_global_mapping_passes_and_a_broken_one_fails():
    """wild=global without Java: apply one bijection to every wild species byte of the clean
    ROM (legendaries and the ghost species excluded, as blockWildLegendaries and
    EncounterSet.bannedPokemon do), then break it in one non-exempt slot."""
    spec = _spec(wild="global")
    chk = _walk(_clean(), spec)
    live = [(t, sp) for t in chk.tables for _lv, sp in _live(chk, t)]
    src = sorted({chk.clean[sp] for _t, sp in live})
    pool = sorted(chk.f["ordinary"] - chk.f["legendary"] - {MAROWAK})
    rng = random.Random(0xB0B)
    image = rng.sample(pool, len(src))
    m = dict(zip(src, image, strict=True))
    out = bytearray(_clean())
    for _t, sp in live:
        out[sp] = m[out[sp]]
    r = verify("purered", _clean(), bytes(out), spec=spec)
    assert r["ok"], r["failures"]
    t, sp = next((t, sp) for t, sp in live if not t["exempt"])
    out[sp] = next(v for v in pool if v != m[chk.clean[sp]])
    r = verify("purered", _clean(), bytes(out), spec=spec)
    assert any("global 1-to-1 broken" in f for f in r["failures"]), r["failures"]


def test_a_synthetic_global_bijection_with_legendaries_allowed_passes():
    """wild=global with legendaries allowed: game1to1Encounters' remainingLeft and
    remainingRight are then the SAME 151-species list (A:1162-1174, Gen 1 bans nothing for wild
    encounters), so the native map is a genuine bijection with no reuse at all -- the strictest
    case of the injectivity check (cx-73e80e05 #1)."""
    spec = _spec(wild="global", wild_block_legendaries=False)
    chk = _walk(_clean(), spec)
    live = [(t, sp) for t in chk.tables for _lv, sp in _live(chk, t)]
    src = sorted({chk.clean[sp] for _t, sp in live})
    pool = sorted(chk.f["ordinary"] - {MAROWAK})          # every mode still bans the ghost from Tower/fishing
    rng = random.Random(0xFEED)
    image = rng.sample(pool, len(src))
    m = dict(zip(src, image, strict=True))
    out = bytearray(_clean())
    for _t, sp in live:
        out[sp] = m[out[sp]]
    r = verify("purered", _clean(), bytes(out), spec=spec)
    assert r["ok"], r["failures"]


def test_a_flooded_wild_mapping_is_rejected_by_global_and_area_injectivity():
    """Replace every one of the 880 ordinary wild/fishing species bytes with Rhydon (opaque
    slots and levels untouched): a many-to-one map is neither a bijection (wild=global) nor
    per-table injective (wild=area, restriction none or similar) (cx-73e80e05 #1)."""
    clean = _clean()
    chk = _walk(clean, _spec(wild="global"))
    out = bytearray(clean)
    RHYDON = 0x01
    flooded = 0
    for t in chk.tables:
        for _lv, sp in t["slots"]:
            if clean[sp] not in chk.f["opaque"]:
                out[sp] = RHYDON
                flooded += 1
    assert flooded == 880
    assert clean[0xB10BB] == 0x19 and out[0xB10BB] == RHYDON     # the first altered slot, table-iteration order

    for spec in (_spec(wild="global", wild_block_legendaries=False),
                 _spec(wild="area", wild_restriction="none"),
                 _spec(wild="area", wild_restriction="similar")):
        r = verify("purered", clean, bytes(out), spec=spec)
        assert not r["ok"]
        assert any("not injective" in f for f in r["failures"]), (spec, r["failures"])


class TestValidity:
    @pytest.mark.parametrize("cats", CASES, ids=lambda c: "+".join(sorted(c)))
    def test_the_output_is_a_valid_game(self, randomized, cats):
        spec = _cases(cats)
        r = _verify(randomized(spec), spec)
        assert r["ok"], "\n".join(r["failures"])
        assert all((r["changed"][c] > 0) == (c in domains_for_spec(spec)) for c in CATEGORIES), r["changed"]

    def test_a_spirit_in_a_wild_slot_is_reported(self, randomized):
        spec = _cases(set(_MODES))
        e = load_entry("purered")
        out = bytearray(randomized(spec))
        site = e["GoodRodOffset"] + 1                       # species byte of good-rod pair 0
        out[site] = 0x1F                                    # TORCHED, classification spirit
        r = _verify(bytes(out), spec)
        assert any(f"0x{site:X}" in f and "1F" in f and f.startswith("wild") for f in r["failures"]), r["failures"]

    def test_a_double_encoded_static_that_disagrees_is_reported(self, randomized):
        spec = _cases(set(_MODES))
        out = bytearray(randomized(spec))
        out[0x1AB63] = (out[0x1AB63] % 150) + 1             # roof Zapdos inline vs object row 0x1AC2D
        r = _verify(bytes(out), spec)
        assert any("statics" in f and "disagree" in f and "0x1AB63" in f for f in r["failures"]), r["failures"]

    def test_a_duplicate_tm_is_reported(self, randomized):
        spec = _cases(set(_MODES))
        t = load_entry("purered")["TMMovesOffset"]
        out = bytearray(randomized(spec))
        out[t] = out[t + 1]
        r = _verify(bytes(out), spec)
        assert any(f.startswith("tms: duplicate") for f in r["failures"]), r["failures"]

    def test_a_write_outside_the_enabled_categories_is_reported(self, randomized):
        """Category gating: a static changed in a wild-only run is both a disabled-category
        change and an audit stray."""
        spec = _spec(wild="random")
        out = bytearray(randomized(spec))
        out[0x59654] = 0x01                                 # Route 12 Snorlax -> Rhydon
        r = _verify(bytes(out), spec)
        assert any(f.startswith("statics: disabled") for f in r["failures"]), r["failures"]
        assert any(f.startswith("audit:") and "0x59654" in f for f in r["failures"]), r["failures"]


class TestWild:
    AREA = _spec(wild="area")
    CATCH = _spec(wild="random", wild_restriction="catch_em_all")
    THEMED = _spec(wild="area", wild_restriction="type_themed")
    CURVED = _spec(wild="random", wild_levels=-50, wild_min_catch_rate=3)
    LEVELS_ONLY = _spec(wild_levels=50)

    def test_area_maps_each_species_once_per_table(self, randomized):
        r = _verify(randomized(self.AREA), self.AREA)
        assert r["ok"], "\n".join(r["failures"])

    def test_a_split_area_mapping_is_reported(self, randomized):
        out = bytearray(randomized(self.AREA))
        chk = _walk(bytes(out), self.AREA)
        for t in chk.tables:
            by_clean: dict[int, list[int]] = {}
            for _lv, sp in _live(chk, t):
                by_clean.setdefault(chk.clean[sp], []).append(sp)
            twin = next((sps for sps in by_clean.values() if len(sps) > 1), None)
            if twin:
                break
        out[twin[0]] = next(v for v in sorted(chk.f["ordinary"] - chk.f["legendary"]) if v != out[twin[1]])
        r = _verify(bytes(out), self.AREA)
        assert any("area 1-to-1 broken" in f and t["name"] in f for f in r["failures"]), r["failures"]

    def test_global_maps_each_species_once_across_the_rom(self, randomized):
        spec = _spec(wild="global")                          # crashed before the cx-795d1423 #2 fork fix
        r = _verify(randomized(spec), spec)
        assert r["ok"], "\n".join(r["failures"])

    def test_catch_em_all_places_every_pool_species(self, randomized):
        r = _verify(randomized(self.CATCH), self.CATCH)
        assert r["ok"], "\n".join(r["failures"])

    def test_a_species_erased_from_every_slot_is_reported(self, randomized):
        out = bytearray(randomized(self.CATCH))
        chk = _walk(bytes(out), self.CATCH)
        sites = [sp for t in chk.tables for _lv, sp in _live(chk, t)]
        gone = out[sites[0]]
        other = next(v for v in sorted(chk.f["ordinary"] - chk.f["legendary"]) if v != gone)
        for sp in sites:
            if out[sp] == gone:
                out[sp] = other
        r = _verify(bytes(out), self.CATCH)
        assert any("catch_em_all misses 1 species" in f and chk.name(gone) in f for f in r["failures"]), r["failures"]

    def test_type_themed_tables_share_a_type(self, randomized):
        r = _verify(randomized(self.THEMED), self.THEMED)
        assert r["ok"], "\n".join(r["failures"])

    def test_an_off_theme_species_is_reported(self, randomized):
        out = bytearray(randomized(self.THEMED))
        chk = _walk(bytes(out), self.THEMED)
        t = next(t for t in chk.tables if len(_live(chk, t)) > 1)
        sites = [sp for _lv, sp in _live(chk, t)]
        rest = set.intersection(*(chk.f["types"][out[sp]] for sp in sites[1:]))
        out[sites[0]] = next(v for v in sorted(chk.f["ordinary"] - chk.f["legendary"]) if not chk.f["types"][v] & rest)
        r = _verify(bytes(out), self.THEMED)
        assert any("share no type" in f and t["name"] in f for f in r["failures"]), r["failures"]

    def test_a_planted_legendary_is_reported(self, randomized):
        spec = _spec(wild="random")                          # wild_block_legendaries defaults to True
        out = bytearray(randomized(spec))
        site = load_entry("purered")["GoodRodOffset"] + 1
        out[site] = ZAPDOS
        r = _verify(bytes(out), spec)
        assert any("legendary ZAPDOS" in f and f"0x{site:X}" in f for f in r["failures"]), r["failures"]

    def test_the_ghost_species_in_a_fishing_slot_is_reported(self, randomized):
        spec = _spec(wild="random")
        out = bytearray(randomized(spec))
        site = load_entry("purered")["GoodRodOffset"] + 1
        out[site] = MAROWAK
        r = _verify(bytes(out), spec)
        assert any("ghost-Marowak species" in f and f"0x{site:X}" in f for f in r["failures"]), r["failures"]

    def test_the_level_curve_and_catch_tier_are_exact(self, randomized):
        r = _verify(randomized(self.CURVED), self.CURVED)
        assert r["ok"], "\n".join(r["failures"])

    def test_a_level_off_the_curve_is_reported(self, randomized):
        out = bytearray(randomized(self.CURVED))
        chk = _walk(bytes(out), self.CURVED)
        lv, _sp = _live(chk, chk.tables[0])[0]
        out[lv] = out[lv] % 100 + 1
        r = _verify(bytes(out), self.CURVED)
        assert any(f"0x{lv:X}" in f and "-50% curve gives" in f for f in r["failures"]), r["failures"]

    def test_a_catch_rate_below_the_tier_is_reported(self, randomized):
        out = bytearray(randomized(self.CURVED))
        e = load_entry("purered")
        site = e["PokemonStatsOffset"] + 8                   # dex 1 (Bulbasaur), tier 3 -> 200
        out[site] = 45
        r = _verify(bytes(out), self.CURVED)
        assert any(f.startswith("catch_rate: dex 1 ") and "tier 3 gives 200" in f for f in r["failures"]), r["failures"]

    def test_tier_5_patches_the_master_ball_jump_and_nothing_else(self, randomized):
        """enableGuaranteedPokemonCatching: `jp z, .captured` (CA) after `cp MASTER_BALL`
        becomes `jp` (C3) at 0xD1E9; the catch bytes stay. An unpatched output must fail."""
        spec = _spec(wild_min_catch_rate=5)
        out = randomized(spec)
        assert guaranteed_catch_byte(_clean()) == 0xD1E9 and _clean()[0xD1E9] == 0xCA and out[0xD1E9] == 0xC3
        r = _verify(out, spec)
        assert r["ok"], "\n".join(r["failures"])
        assert r["changed"]["catch_rate"] == 1
        bad = bytearray(out)
        bad[0xD1E9] = 0xCA
        r = _verify(bytes(bad), spec)
        assert any("Master-Ball jump opcode 0xD1E9 is CA, tier 5 gives C3" in f for f in r["failures"]), r["failures"]

    def test_levels_only_keeps_every_species(self, randomized):
        r = _verify(randomized(self.LEVELS_ONLY), self.LEVELS_ONLY)
        assert r["ok"], "\n".join(r["failures"])
        out = bytearray(randomized(self.LEVELS_ONLY))
        chk = _walk(bytes(out), self.LEVELS_ONLY)
        _lv, sp = _live(chk, chk.tables[0])[0]
        out[sp] = next(v for v in sorted(chk.f["ordinary"]) if v != out[sp])
        r = _verify(bytes(out), self.LEVELS_ONLY)
        assert any("must be unchanged on this mode" in f and f"0x{sp:X}" in f for f in r["failures"]), r["failures"]

    AREA_SIMILAR = _spec(wild="area", wild_restriction="similar")
    AREA_CATCH = _spec(wild="area", wild_restriction="catch_em_all")

    def test_area_similar_strength_maps_each_species_once_per_table(self, randomized):
        """pickWildPowerLvlReplacement's usedPks history (A:1096-1110) makes restriction=similar
        per-table injective the same way none/type_themed are (cx-73e80e05 #1)."""
        r = _verify(randomized(self.AREA_SIMILAR), self.AREA_SIMILAR)
        assert r["ok"], "\n".join(r["failures"])

    def test_area_catch_em_all_places_every_pool_species(self, randomized):
        """Fork patch 0005 (cx-73e80e05 #1): the per-area catch-em-all picker now draws from
        the area-banned-filtered pool on every branch, so a table can no longer receive the
        banned ghost species from the unfiltered allPokes (A:975-1006)."""
        r = _verify(randomized(self.AREA_CATCH), self.AREA_CATCH)
        assert r["ok"], "\n".join(r["failures"])


class TestStatics:
    MATCHING = _spec(statics="matching", static_levels=20)
    ZAPDOS_SITES = (0x1AC2D, 0x1EDAE, 0x1AB63)

    def test_matching_keeps_legendaries_legendary_and_records_distinct(self, randomized):
        r = _verify(randomized(self.MATCHING), self.MATCHING)
        assert r["ok"], "\n".join(r["failures"])

    def test_a_legendary_turned_ordinary_is_reported(self, randomized):
        out = bytearray(randomized(self.MATCHING))
        for o in self.ZAPDOS_SITES:
            out[o] = 0x01                                    # Rhydon
        r = _verify(bytes(out), self.MATCHING)
        assert any("matching broken @0x1AC2D: ZAPDOS (4B) -> RHYDON (01)" in f for f in r["failures"]), r["failures"]

    def test_a_repeated_static_is_reported(self, randomized):
        out = bytearray(randomized(self.MATCHING))
        out[0x59654] = out[0x59A41]                          # Route 12 Snorlax record := Route 16 record's species
        r = _verify(bytes(out), self.MATCHING)
        assert any("placed 2 times" in f for f in r["failures"]), r["failures"]

    def test_a_static_level_off_the_curve_is_reported(self, randomized):
        out = bytearray(randomized(self.MATCHING))
        out[0x59659] = out[0x59659] % 100 + 1                # Route 12 Snorlax level
        r = _verify(bytes(out), self.MATCHING)
        assert any("0x59659" in f and "+20% curve gives" in f for f in r["failures"]), r["failures"]

    def test_similar_strength_keeps_records_distinct(self, randomized):
        spec = _spec(statics="similar")                      # hung before the cx-795d1423 #1 fork fix
        r = _verify(randomized(spec), spec)
        assert r["ok"], "\n".join(r["failures"])

    def test_an_off_strength_static_is_reported(self, randomized):
        """pickStaticPowerLvlReplacement's expanding BST window (A:7059-7082): Weedle (BST 175)
        replaced by Mewtwo (BST 590) is nowhere near any window it would expand to."""
        spec = _spec(statics="similar")
        out = bytearray(randomized(spec))
        out[0x190AD] = MEWTWO                                 # a Weedle static (clean species WEEDLE, BST 175)
        r = _verify(bytes(out), spec)
        assert any("similar_strength band" in f and "0x190AD" in f for f in r["failures"]), r["failures"]


class TestStarters:
    SPEC = _spec(starters="two_evos")

    def test_two_evos_starters_are_base_species_with_two_stages_ahead(self, randomized):
        r = _verify(randomized(self.SPEC), self.SPEC)
        assert r["ok"], "\n".join(r["failures"])
        out = bytearray(randomized(self.SPEC))
        for o in load_entry("purered")["StarterOffsets1"]:
            out[o] = 0x01                                    # Rhydon: nothing evolves into or from it
        r = _verify(bytes(out), self.SPEC)
        assert any("starter 1 RHYDON (01) is not a base species with two evolutions ahead" in f
                   for f in r["failures"]), r["failures"]

    def test_starters_random_that_happens_to_redraw_the_original_trio_is_not_a_failure(self):
        """random2EvosPokemon-adjacent starter picking (A:4019-4028) only rejects a DUPLICATE
        among the chosen trio, never the original species -- so a clean-vs-clean comparison
        (the legal "redrew the same 3" outcome) must pass, not report starters as silently
        broken (cx-73e80e05 #6)."""
        clean = _clean()
        r = verify("purered", clean, clean, spec=_spec(starters="random"))
        assert r["ok"], r["failures"]
        assert any("starters" in w for w in r["warnings"])


class TestTrainers:
    DISTRIBUTED = _spec(trainers="distributed")
    THEMED = _spec(trainers="type_themed")
    THEMED_WEIGHTED = _spec(trainers="type_themed", trainers_match_typing=True)
    FORCED = _spec(trainers="random", trainers_force_evolved=30, trainers_levels=25)
    FORCED_ONLY = _spec(trainers_force_evolved=1)

    @staticmethod
    def _slots(chk: _Check):
        return [(where, lv, sp, mask) for where, slots in chk.parties for lv, sp, mask in slots]

    def test_distributed_is_a_valid_pool_draw(self, randomized):
        """"Evenly distributed" has no seed-independent invariant (every multiset is a legal
        outcome of the running-mean rule, see _trainer_modes); what is checkable is the pool."""
        r = _verify(randomized(self.DISTRIBUTED), self.DISTRIBUTED)
        assert r["ok"], "\n".join(r["failures"])
        out = bytearray(randomized(self.DISTRIBUTED))
        chk = _walk(bytes(out), self.DISTRIBUTED)
        where, _lv, sp, _m = self._slots(chk)[0]
        out[sp] = 0x1F                                       # TORCHED, a spirit: never in the pool
        r = _verify(bytes(out), self.DISTRIBUTED)
        assert any("TORCHED (1F) is not randomizable" in f and where in f for f in r["failures"]), r["failures"]

    def test_type_themed_parties_share_a_type(self, randomized):
        """Fork patch 0004: randomType() used to draw the pure ExtraTypes (GAS/WOOD/ABNORMAL/
        TRI/WIND/SOUND) no species carries -> empty pool -> nextInt(0) crash."""
        r = _verify(randomized(self.THEMED), self.THEMED)
        assert r["ok"], "\n".join(r["failures"])

    def test_type_themed_with_match_typing_shares_a_type(self, randomized):
        """pickType(weightByFrequency=true) never draws a zero-weight type, so the same mode
        with trainers_match_typing on runs and every party shares a type."""
        r = _verify(randomized(self.THEMED_WEIGHTED), self.THEMED_WEIGHTED)
        assert r["ok"], "\n".join(r["failures"])

    def test_an_off_theme_party_member_is_reported(self, randomized):
        out = bytearray(randomized(self.THEMED_WEIGHTED))
        chk = _walk(bytes(out), self.THEMED_WEIGHTED)
        where, slots = next((w, s) for w, s in chk.parties if len(s) > 1)
        rest = set.intersection(*(chk.f["types"][out[sp]] for _lv, sp, _m in slots[1:]))
        out[slots[0][1]] = next(v for v in sorted(chk.f["ordinary"] - chk.f["legendary"])
                                if not chk.f["types"][v] & rest)
        r = _verify(bytes(out), self.THEMED_WEIGHTED)
        assert any("share no type" in f and where in f for f in r["failures"]), r["failures"]

    def test_force_evolved_and_the_level_curve_hold(self, randomized):
        r = _verify(randomized(self.FORCED), self.FORCED)
        assert r["ok"], "\n".join(r["failures"])

    def test_an_unevolved_high_level_mon_is_reported(self, randomized):
        out = bytearray(randomized(self.FORCED))
        chk = _walk(bytes(out), self.FORCED)
        where, _lv, sp, _m = next(s for s in self._slots(chk) if (out[s[1]] & s[3]) >= 30)
        out[sp] = next(v for v in sorted(chk.f["evos"]) if v in chk.f["ordinary"])   # something that still evolves
        r = _verify(bytes(out), self.FORCED)
        assert any("still evolves" in f and where in f for f in r["failures"]), r["failures"]

    def test_a_trainer_level_off_the_curve_is_reported(self, randomized):
        out = bytearray(randomized(self.FORCED))
        chk = _walk(bytes(out), self.FORCED)
        where, lv, _sp, mask = self._slots(chk)[0]
        out[lv] = (out[lv] & ~mask & 0xFF) | ((out[lv] & mask) % 100 + 1)
        r = _verify(bytes(out), self.FORCED)
        assert any(f"0x{lv:X}" in f and "+25% curve gives" in f for f in r["failures"]), r["failures"]

    def test_a_planted_trainer_legendary_is_reported(self, randomized):
        out = bytearray(randomized(self.FORCED))            # trainers_block_legendaries defaults to True
        chk = _walk(bytes(out), self.FORCED)
        where, _lv, sp, _m = self._slots(chk)[0]
        out[sp] = MEWTWO
        r = _verify(bytes(out), self.FORCED)
        assert any("legendary MEWTWO" in f and where in f for f in r["failures"]), r["failures"]

    def test_force_evolved_alone_only_walks_the_evolution_chain(self, randomized):
        r = _verify(randomized(self.FORCED_ONLY), self.FORCED_ONLY)
        assert r["ok"], "\n".join(r["failures"])
        out = bytearray(randomized(self.FORCED_ONLY))
        chk = _walk(bytes(out), self.FORCED_ONLY)
        where, _lv, sp, _m = self._slots(chk)[0]
        out[sp] = 0x01 if out[sp] != 0x01 else 0x02          # Rhydon / Kangaskhan evolve from nothing
        r = _verify(bytes(out), self.FORCED_ONLY)
        assert any("is not an evolution of it" in f and where in f for f in r["failures"]), r["failures"]

    def test_similar_strength_is_a_valid_pool_draw(self, randomized):
        spec = _spec(trainers="random", trainers_similar_strength=True)   # hung before the cx-795d1423 #1 fix
        r = _verify(randomized(spec), spec)
        assert r["ok"], "\n".join(r["failures"])

    def test_an_off_strength_trainer_pokemon_is_reported(self, randomized):
        """pickTrainerPokeReplacement's expanding BST window (A:6925-6946): Rattata (BST 218)
        replaced by Mewtwo (BST 590, class 2's own initial +-10% window already holds nine
        candidates in 197-239) is nowhere near it."""
        spec = _spec(trainers="random", trainers_similar_strength=True)
        out = bytearray(randomized(spec))
        out[0x39589] = MEWTWO
        r = _verify(bytes(out), spec)
        assert any("similar_strength band" in f and "0x39589" in f for f in r["failures"]), r["failures"]

    FORCE_EVOLVED_UNCHANGED = _spec(trainers_force_evolved=100)

    def test_force_evolved_alone_leaves_low_level_trainer_pokemon_untouched(self, randomized):
        """forceFullyEvolvedTrainerPokes only touches tp.level >= minLevel (A:2069-2089); below
        that, trainers "unchanged" means byte-identical, not "any reachable evolution"
        (cx-73e80e05 #3). 0x39FF3 (level 100, mask 0x7F) is a Magikarp that must evolve to
        Gyarados; 0x39589 (level 11) is a Rattata that must not change at all."""
        out = randomized(self.FORCE_EVOLVED_UNCHANGED)
        assert out[0x39589] == 0xA5                          # untouched: level 11 < the threshold
        assert out[0x39FF3] == 0x16                          # GYARADOS: level 100 >= the threshold
        r = _verify(out, self.FORCE_EVOLVED_UNCHANGED)
        assert r["ok"], "\n".join(r["failures"])
        bad = bytearray(out)
        bad[0x39589] = 0xA6                                  # RATICATE: an evolution of Rattata, but still level 11
        r = _verify(bytes(bad), self.FORCE_EVOLVED_UNCHANGED)
        assert any("changed below the force_evolved threshold" in f and "0x39589" in f
                   for f in r["failures"]), r["failures"]


class TestTMs:
    SPEC = _spec(tms="random", tm_keep_field=True, tm_sanity=True)
    FULL = _spec(tm_compat="full")

    def test_full_compat_sets_all_55_bits_of_every_record(self, randomized):
        r = _verify(randomized(self.FULL), self.FULL)
        assert r["ok"], "\n".join(r["failures"])
        e = load_entry("purered")
        out = bytearray(randomized(self.FULL))
        site = e["PokemonStatsOffset"] + 3 * e["BaseStatsEntrySize"] + 0x14      # dex 4, TM01
        out[site] &= 0xFE
        r = _verify(bytes(out), self.FULL)
        assert any("dex 4 lacks TM/HM bits [1]" in f for f in r["failures"]), r["failures"]

    def test_field_tms_are_kept_and_level_up_moves_stay_learnable(self, randomized):
        r = _verify(randomized(self.SPEC), self.SPEC)
        assert r["ok"], "\n".join(r["failures"])
        t = load_entry("purered")["TMMovesOffset"]
        assert randomized(self.SPEC)[t + 27] == 0x5B         # TM28 Dig, the one pureRGB field-move TM

    def test_a_replaced_field_tm_is_reported(self, randomized):
        out = bytearray(randomized(self.SPEC))
        t = load_entry("purered")["TMMovesOffset"]
        chk = _walk(bytes(out), self.SPEC)
        out[t + 27] = next(m for m in sorted(chk.f["moves"]) if m not in out[t:t + 55])
        r = _verify(bytes(out), self.SPEC)
        assert any(f.startswith("tms: TM28 held field move 5B") for f in r["failures"]), r["failures"]

    def test_transform_or_struggle_as_a_tm_move_is_reported(self, randomized):
        """Transform (Gen1Constants.bannedLevelupMoves) and Struggle
        (GlobalConstants.bannedRandomMoves) are excluded unconditionally from randomizeTMMoves
        (A:4475-4497) -- neither can legally sit in a TM slot on any tms= mode."""
        spec = _spec(tms="random")
        t = load_entry("purered")["TMMovesOffset"]
        for banned in (0x90, 0xA5):
            out = bytearray(randomized(spec))
            out[t] = banned
            r = _verify(bytes(out), spec)
            assert any(f"TM01 @0x{t:X} = {banned:02X}" in f and "banned from random TM selection" in f
                       for f in r["failures"]), (banned, r["failures"])

    def test_a_cleared_required_compat_bit_is_reported(self, randomized):
        out = bytearray(randomized(self.SPEC))
        chk = _walk(bytes(out), self.SPEC)
        e = load_entry("purered")
        t, size = e["TMMovesOffset"], e["BaseStatsEntrySize"]
        for internal in sorted(chk.f["ordinary"]):
            hit = next((n for n in range(1, 51) if out[t + n - 1] in chk._learnset(internal)), None)
            if hit:
                break
        site = e["PokemonStatsOffset"] + (chk.f["dex"][internal] - 1) * size + 0x14 + (hit - 1) // 8
        out[site] &= ~(1 << ((hit - 1) % 8)) & 0xFF
        r = _verify(bytes(out), self.SPEC)
        assert any(f"dex {chk.f['dex'][internal]} learns" in f and f"TM{hit:02d}" in f for f in r["failures"]), r["failures"]

    PREFER_TYPE = _spec(tm_compat="prefer_type")

    def test_prefer_type_gives_every_bug_type_species_the_cut_hm(self, randomized):
        """getMoveCompatibilityProbability (A:4623-4640): a same-type move under
        requiredEarlyOn (Cut, the only entry in Gen1Constants.earlyRequiredHMs) reaches
        probability 0.9*1.8 capped at 1.0 -- every Bug-type species (Cut's type in pureRGB,
        data/moves/moves.asm:30) must learn HM01, not just Caterpie."""
        r = _verify(randomized(self.PREFER_TYPE), self.PREFER_TYPE)
        assert r["ok"], "\n".join(r["failures"])

    def test_a_missing_guaranteed_hm_bit_on_a_same_type_species_is_reported(self, randomized):
        out = bytearray(randomized(self.PREFER_TYPE))
        chk = _walk(bytes(out), self.PREFER_TYPE)
        e = load_entry("purered")
        size = e["BaseStatsEntrySize"]
        cut_type = chk.f["move_types"][15]
        by_dex = {chk.f["dex"][i]: i for i in chk.f["ordinary"]}
        dex = next(d for d in range(1, 152) if cut_type in chk.f["types"][by_dex[d]])
        site = e["PokemonStatsOffset"] + (dex - 1) * size + 0x14 + 6      # byte 6 of the compat block: HM01 = bit 0x04
        out[site] &= ~0x04 & 0xFF
        r = _verify(bytes(out), self.PREFER_TYPE)
        assert any(f"dex {dex} shares Cut's type and must learn HM01" in f for f in r["failures"]), r["failures"]


class TestFieldItems:
    SHUFFLE = _spec(field_items="shuffle")
    EVEN = _spec(field_items="random_even")
    RANDOM = _spec(field_items="random")

    @staticmethod
    def _sites(clean: bytes):
        e = load_entry("purered")
        sites = sorted(_upr_item_sites(clean, e))
        return ([o for o in sites if clean[o] in FIELD_POOL],
                [o for o in sites if TM_ITEM0 <= clean[o] < TM_ITEM0 + 50],
                [o for o in sites if clean[o] == 0x05])      # HYPER BALL: pureRGB's id, vanilla's banned TOWN MAP

    def test_shuffle_preserves_both_multisets(self, randomized):
        r = _verify(randomized(self.SHUFFLE), self.SHUFFLE)
        assert r["ok"], "\n".join(r["failures"])

    def test_a_swapped_in_item_is_reported(self, randomized):
        out = bytearray(randomized(self.SHUFFLE))
        pool, _tms, _hyper = self._sites(_clean())
        out[pool[0]] = next(v for v in sorted(FIELD_POOL) if v != out[pool[0]])
        r = _verify(bytes(out), self.SHUFFLE)
        assert any("shuffle changed the multiset of items" in f for f in r["failures"]), r["failures"]

    def test_random_and_random_even_keep_field_tms_distinct_and_required(self, randomized):
        """"Evenly spread" has no seed-independent invariant (every multiset is a legal outcome
        of the running-mean re-roll, see field_items); the TM rule and the pool are."""
        for spec in (self.EVEN, self.RANDOM):
            r = _verify(randomized(spec), spec)
            assert r["ok"], "\n".join(r["failures"])

    def test_a_banned_pure_item_placed_is_reported(self, randomized):
        out = bytearray(randomized(self.EVEN))
        pool, _tms, _hyper = self._sites(_clean())
        out[pool[0]] = 0x17                                  # OLD COIN: pureRGB's id, vanilla's banned THUNDERBADGE
        r = _verify(bytes(out), self.EVEN)
        assert any(f"0x{pool[0]:X}" in f and "Old Coin (17) is not in UPR's pool" in f for f in r["failures"]), r["failures"]

    def test_a_repeated_field_tm_is_reported(self, randomized):
        out = bytearray(randomized(self.RANDOM))
        _pool, tms, _hyper = self._sites(_clean())
        out[tms[0]] = out[tms[1]]
        r = _verify(bytes(out), self.RANDOM)
        assert any("field TMs repeat" in f for f in r["failures"]), r["failures"]

    def test_pure_only_items_are_outside_the_pool_and_stay_put(self, randomized):
        """UPR's Gen1Constants.allowedItems is vanilla's: HYPER BALL (0x05 = TOWN MAP there)
        is never placed and its three pickups are byte-identical; a Potion planted there is
        reported. APEX CHIP 0x32, POCKET ABRA 0x2C and BOOSTER CHIP 0x4B are banned the same
        way (ppUpGlitch / ?44 / expAll) and never appear in any pickup."""
        clean = _clean()
        out = bytearray(randomized(self.RANDOM))
        pool, tms, hyper = self._sites(clean)
        assert len(hyper) == 3 and all(out[o] == 0x05 for o in hyper)
        assert not {0x05, 0x2C, 0x32, 0x4B} & FIELD_POOL
        assert not {0x05, 0x2C, 0x32, 0x4B} & {out[o] for o in pool + tms}
        out[hyper[0]] = 0x14
        r = _verify(bytes(out), self.RANDOM)
        assert any(f"0x{hyper[0]:X} Hyper Ball (05) is outside UPR's pool" in f for f in r["failures"]), r["failures"]

    def test_a_pickup_in_an_unreachable_map_is_reported_when_touched(self, randomized):
        """UPR loads maps by walking connections and warps from map 0 (preloadMap); the
        audit's field_item_bytes sees six more sites in maps nothing leads to. They are never
        rewritten, and a write there is reported even though the audit allows it."""
        clean = _clean()
        e = load_entry("purered")
        extra = sorted(field_item_bytes(clean, e) - _upr_item_sites(clean, e))
        assert [(o, clean[o]) for o in extra] == [(0xEC34, 0x0B), (0xEC67, 0xCD), (0x42407, 0x04),
                                                  (0x42442, 0x80), (0x4245B, 0x7E), (0x4248E, 0x90)]
        out = bytearray(randomized(self.RANDOM))
        assert all(out[o] == clean[o] for o in extra)
        out[0xEC67] = TM_ITEM0
        r = _verify(bytes(out), self.RANDOM)
        assert any("0xEC67 TM05 (CD) sits in a map no connection or warp reaches" in f for f in r["failures"]), r["failures"]
