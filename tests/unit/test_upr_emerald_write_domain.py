"""E-MGR: independent Emerald model and strict seeded fork isolation controls."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pytest

from server import upr_gen3_write_domain as W, upr_settings as U
from tests.unit import test_upr_gen3_write_domain as F

ROOT = Path(__file__).resolve().parents[2]
FAMILY = "gen3_emerald"
MODEL_PATH = ROOT / "data/games/gen3_emerald/upr_write_domains.json"


def _off_spec():
    return U.family_spec(F._off_spec(), FAMILY)


@pytest.fixture(scope="module")
def clean():
    return F._clean("emerald")


@pytest.fixture(scope="module")
def jar():
    return F._jar()


@pytest.fixture(scope="module")
def model():
    return W.load_model(title="emerald")


@pytest.fixture(scope="module", autouse=True)
def required_inputs_when_requested():
    if os.environ.get("SLINK_GEN3_ROMS"):
        try:
            F._clean("emerald")
            F._seeded_probe(F._jar())
        except pytest.skip.Exception as exc:
            pytest.fail(f"E-MGR ROM checks explicitly requested but a prerequisite is missing: {exc}")


def test_emerald_model_is_rebuilt_from_its_own_pinned_inputs(model, clean, jar):
    assert W.build_model(Path(jar), {"emerald": clean}) == model
    assert set(model["titles"]) == {"emerald"}
    assert model["jar_sha256"] == hashlib.sha256(Path(jar).read_bytes()).hexdigest()
    assert model["titles"]["emerald"]["ini_section"] == "Emerald (U)"
    assert model["titles"]["emerald"]["clean_sha1"] == hashlib.sha1(clean).hexdigest()
    assert model["titles"]["emerald"]["symbol_sha256"] == hashlib.sha256((W.SYM_DIR / "pokeemerald.sym").read_bytes()).hexdigest()
    assert W.dumps(model) == MODEL_PATH.read_text(encoding="utf-8")


def test_emerald_options_refuse_the_frlg_only_fossil_tweak():
    options = U.options_for(FAMILY)
    assert set(options) == set(U.options_for(U.FAMILY_FRLG)) - {"balance_static_levels"}
    bad = U.load(U.build_spec({"balance_static_levels": True}, family=U.FAMILY_FRLG))
    assert any("BALANCE_STATIC_LEVELS" in why for why in U.forbidden_enabled(bad, FAMILY))


def test_facility_domains_are_never_in_an_allowed_write_span(model):
    domains = model["titles"]["emerald"]["domains"]
    forbidden = set(model["forbidden_domains"])
    facilities = {"frontier", "pyramid", "trainer_hill", "contests", "secret_bases"}
    assert facilities <= forbidden
    protected = set().union(*(F._spans(domains[name]) for name in facilities))
    assert protected
    for name, components in domains.items():
        if name not in forbidden:
            assert not F._spans(components) & protected, name


def test_pinned_facility_source_array_census_has_no_allowed_overlap(model):
    from tests.unit import gen3_pret

    root = gen3_pret.require_emerald(gen3_pret.find_emerald())
    markers = ("frontier", "battle_tower", "battle_factory", "battle_arena", "battle_dome", "battle_palace",
               "battle_pike", "pyramid", "trainer_hill", "contest", "secret_base")
    sources = [p for p in (root / "src").rglob("*")
               if p.suffix in (".c", ".h") and any(word in p.as_posix().lower() for word in markers)]
    names = {name for path in sources for name in re.findall(
        r"\bconst\s+[^;={}]+?\b(\w+)\s*\[[^;={}]*=\s*\{", path.read_text(encoding="utf-8"))}
    # All homonymous local symbols are included, a conservative superset of the
    # source arrays. This covers generic sTextColors etc. beyond named facility symbols.
    symbols = [(a, n, name) for a, n, name in W._syms("emerald") if n and name in names]
    assert (len(sources), len(names), len(symbols)) == (33, 920, 996)
    domains = model["titles"]["emerald"]["domains"]
    allowed = [span for name, c in domains.items() if name not in model["forbidden_domains"] for span in W._ranges(c)]
    assert not [(name, a) for a, n, name in symbols if any(start < a + n and end > a for start, end in allowed)]


def test_allowed_and_widest_emerald_outputs_are_classified(model, clean):
    folder = os.environ.get("SLINK_GEN3_RAND_ROMS")
    if not folder:
        pytest.skip("set SLINK_GEN3_RAND_ROMS for Emerald output controls")
    for mode in ("allowed", "widest"):
        path = Path(folder) / f"Emerald_{mode}.gba"
        lines = Path(str(path) + ".log").read_text(encoding="utf-8").splitlines()
        settings = next(line.split(": ", 1)[1] for line in lines if line.startswith("Settings String: "))
        spec = U.spec_from_parsed(U.parse_settings_string(settings), FAMILY)
        report = W.audit("emerald", clean, path.read_bytes(), W.domains_for_spec(spec), model)
        assert report["changed"] > 0
        if mode == "allowed":
            assert report["stray"] == [], report["named"]
        else:
            assert report["stray"] and "unattributed" not in report["named"], report["named"]
            assert {"base_stats", "types", "abilities", "evolutions", "movesets"} <= set(report["named"])


def test_emerald_lossless_baseline_preserves_rules_and_header(tmp_path, model):
    from server.adapters import gen3_rom_tables as R

    clean, out, spec = F._run_fork(tmp_path, "emerald", _off_spec(), family=FAMILY)
    assert W.domains_for_spec(spec) == {"baseline"}
    assert W.audit("emerald", clean, out, {"baseline"}, model)["stray"] == []
    assert clean[0xA0:0xC0] == out[0xA0:0xC0]
    table = R.table_symbols("emerald")["gSpeciesInfo"]
    offset = table["address"] - R.ROM_BASE
    projected = [R.normalised_species_rules(rom[offset:offset + table["size"]], "emerald") for rom in (clean, out)]
    assert projected[0] == projected[1]
    assert hashlib.sha256(projected[1]).hexdigest() == R.EMERALD_SPECIES_RULES_FACTS["normalised_species_rules_sha256"]


@pytest.mark.parametrize(("key", "value"), [(k, v) for k, v in F._isolation_cases() if k != "balance_static_levels"])
def test_every_emerald_writing_option_alone_is_tight(tmp_path, model, key, value):
    spec = {**_off_spec(), **F.PARENT.get(key, {}), key: value}
    clean, out, effective = F._run_fork(tmp_path, "emerald", spec, family=FAMILY)
    F._assert_tight("emerald", clean, out, W.domains_for_spec(effective), model)


def test_every_emerald_allowed_option_at_once_is_tight(tmp_path, model):
    spec = {k: F._on_value(opt) for k, opt in U.options_for(FAMILY).items()}
    spec.update(trainers="random", trainers_similar_strength=False, wild_restriction="none")
    clean, out, effective = F._run_fork(tmp_path, "emerald", spec, family=FAMILY)
    F._assert_tight("emerald", clean, out, W.domains_for_spec(effective), model)


@pytest.mark.parametrize("domain", (*W.FORBIDDEN_DOMAINS, *W.EMERALD_FACILITIES))
def test_every_emerald_forbidden_domain_has_a_named_mutation_falsifier(model, clean, domain):
    domains = model["titles"]["emerald"]["domains"]
    enabled = set(domains) - set(model["forbidden_domains"])
    allowed = W._merge(span for name in enabled for span in W._ranges(domains[name]))
    offset = next(i for start, end in W._ranges(domains[domain]) for i in range(start, end) if not W._inside(allowed, i))
    out = bytearray(clean)
    out[offset] ^= 1
    report = W.audit("emerald", clean, bytes(out), enabled, model)
    assert report["stray"] == [offset] and domain in report["named"]
    assert W.audit("emerald", clean, clean, enabled, model)["stray"] == []


def test_emerald_free_space_stays_packed(model, clean):
    domains = model["titles"]["emerald"]["domains"]
    start, end = W._ranges(domains["free_space"])[0]
    assert start == 0xE40000 and end == len(clean)
    out = bytearray(clean)
    out[start + 4] = 1
    assert W.audit("emerald", clean, bytes(out), {"baseline", "free_space"}, model)["stray"] == []
    out[start + 0x100000] = 1
    result = W.audit("emerald", clean, bytes(out), {"baseline", "free_space"}, model)
    assert result["stray"] == [start + 0x100000]
    assert result["named"] == {"free_space (not packed from 0xE40000)": 1}


def test_emerald_runtime_audit_enforces_its_jar_and_required_model(tmp_path, clean, jar, monkeypatch):
    from server.upr_pipeline import UprPipelineError

    source = tmp_path / "emerald.gba"
    source.write_bytes(clean)
    wrong = tmp_path / "wrong.jar"
    wrong.write_bytes(b"not the modelled fork")
    with pytest.raises(UprPipelineError, match="not the jar the write domains were modelled from"):
        W.check_output(str(source), str(source), {}, jar=str(wrong))
    monkeypatch.setattr(W, "EMERALD_MODEL_PATH", tmp_path / "missing.json")
    with pytest.raises(UprPipelineError, match="write-domain audit could not run.*missing.json"):
        W.check_output(str(source), str(source), {}, jar=jar)


def test_facility_mutation_can_pass_content_checks_but_never_the_manager_audit(tmp_path, clean, jar):
    from server import upr_pipeline as P

    source, output = tmp_path / "source.gba", tmp_path / "output.gba"
    source.write_bytes(clean)
    offset, _, _ = next(row for row in W._syms("emerald") if row[2] == "gBattleFrontierMons")
    changed = bytearray(clean)
    changed[offset] ^= 1
    output.write_bytes(changed)
    P._check_content_gen3(str(source), str(output))  # these facility bytes are outside the sparse client report
    with pytest.raises(P.UprPipelineError, match="outside the write domain.*frontier"):
        W.check_output(str(source), str(output), {}, jar=jar)


def test_emerald_wild_domain_is_exactly_the_encounter_slot_arrays(model, clean):
    """The wild walk stops at gWildMonHeaders' terminator and admits only *Mons slot arrays."""
    syms = W._syms("emerald")
    (hdr, size), = [(a, n) for a, n, name in syms if name == "gWildMonHeaders"]
    wild = W._ranges(model["titles"]["emerald"]["domains"]["wild"])
    arrays = [(a, a + n) for a, n, name in syms if name.endswith("Mons")]
    assert all(any(a <= s and e <= b for a, b in arrays) for s, e in wild)
    assert not any(hdr <= s < hdr + size for s, _e in wild)
    assert clean[hdr + size - 20:hdr + size - 18] == bytes((0xFF, 0xFF))   # the walk terminator ends the symbol
    end = max(e for _s, e in wild)
    out = bytearray(clean)
    out[end] ^= 1
    assert W.audit("emerald", clean, bytes(out), {"wild"}, model)["stray"] == [end]


@pytest.mark.parametrize("domain", ("base_stats", "frontier"))
def test_a_forbidden_domain_cannot_be_enabled(model, clean, domain):
    with pytest.raises(ValueError, match="forbidden write domain"):
        W.audit("emerald", clean, clean, {domain}, model)


def test_no_title_admits_another_titles_rom(model, clean):
    with pytest.raises(ValueError, match="not the pinned dump"):
        W.audit("emerald", bytes(len(clean)), clean, {"wild"}, model)
