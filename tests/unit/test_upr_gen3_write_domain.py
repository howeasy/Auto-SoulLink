"""R3-F3: the FR/LG write-domain audit (server/upr_gen3_write_domain.py,
data/games/gen3_frlg/upr_write_domains.json) -- pureRGB's T6 standard for Gen 3: disabled
settings write nothing, enabled settings write only inside their domains, 0 stray bytes.

The model rows run everywhere. The ROM rows skip by name when the pinned clean dumps, the
Manager-made outputs ($SLINK_GEN3_RAND_ROMS) or the pinned fork jar + Java are absent; a
present-but-wrong clean dump fails, and with $SLINK_GEN3_ROMS set, a run where EVERY ROM row
skipped fails (the module teardown guard).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from server import upr_gen3_write_domain as W, upr_settings as U
from tools.gen3_final_cut import ROOT_DUMPS, STAGED, rom_pins

ROOT = Path(__file__).resolve().parents[2]
FRLG = U.FAMILY_FRLG
TITLES = ("firered", "leafgreen")
MODEL = W.load_model()
# every byte where an allowed domain meets a forbidden table is one of these two fork
# normalisations (the lossless control writes them with every setting off)
KNOWN_OVERLAP = {"ability2_normalisation", "deoxys_stats"}
_ROWS: dict[str, set] = {"attempted": set(), "skipped": set()}


def _row() -> str:
    return os.environ.get("PYTEST_CURRENT_TEST", "?").rsplit(" ", 1)[0]


def _rom_skip(msg: str):
    _ROWS["skipped"].add(_row())
    pytest.skip(msg)


@pytest.fixture(scope="module", autouse=True)
def _rom_rows_must_not_all_skip():
    """With $SLINK_GEN3_ROMS set the ROM rows are expected to run: if every one that was
    selected skipped, the environment is broken, not absent -- fail rather than pass green."""
    yield
    tried = _ROWS["attempted"]
    if os.environ.get("SLINK_GEN3_ROMS") and tried and tried <= _ROWS["skipped"]:
        pytest.fail(f"SLINK_GEN3_ROMS is set but all {len(tried)} ROM/jar-backed rows skipped")


def _spans(components) -> set[int]:
    return {i for s, e in W._ranges(components) for i in range(s, e)}


def _off_spec() -> dict:
    spec = {}
    for key, opt in U.options_for(FRLG).items():
        if opt["kind"] == "choice":
            spec[key] = "unchanged" if "unchanged" in opt["choices"] else opt["default"]
        else:
            spec[key] = False if opt["kind"] == "bool" else 0
    return spec


def _on_value(opt):
    if opt["kind"] == "bool":
        return True
    if opt["kind"] == "int":
        return opt["max"]
    return next(v for v in opt["choices"] if v != "unchanged")


PARENT = {"trainers_rival_starter": {"starters": "random"},
          "shops_balance_prices": {"shops": "random"}}


# ── the model (ROM-free) ────────────────────────────────────────────────────────────────
def test_every_frlg_option_is_modelled():
    opts = U.options_for(FRLG)
    assert set(W.NO_WRITE_OPTIONS) <= set(opts), set(W.NO_WRITE_OPTIONS) - set(opts)
    off = _off_spec()
    assert W.domains_for_spec(off) == {"baseline"}
    for key, opt in opts.items():
        spec = {**off, **PARENT.get(key, {}), key: _on_value(opt)}
        base = W.domains_for_spec({**off, **PARENT.get(key, {})})
        own = W.domains_for_spec(spec) - base
        if key in W.NO_WRITE_OPTIONS:
            assert not own, (key, own)
        else:
            assert own, f"{key} enables no write domain: model it or list it in NO_WRITE_OPTIONS"


def test_model_is_well_formed():
    assert set(MODEL["titles"]) == set(TITLES)
    enable_able = set().union(*(W.domains_for_spec({**_off_spec(), **PARENT.get(k, {}), k: _on_value(o)})
                                for k, o in U.options_for(FRLG).items()))
    for title in TITLES:
        entry = MODEL["titles"][title]
        assert entry["clean_sha1"] == rom_pins(str(ROOT))[title]
        domains = entry["domains"]
        assert enable_able | set(W.FORBIDDEN_DOMAINS) <= set(domains), enable_able - set(domains)
        for name, comps in domains.items():
            assert comps and all(c["what"] and c["source"] for c in comps), name
            spans = W._ranges(comps)
            assert spans, f"{title} {name} has no ranges"
            assert all(0 <= s < e <= 16 << 20 for s, e in spans), name
            for comp in comps:                      # each component is merged and sorted
                own = W._ranges([comp])
                assert all(a[1] < b[0] for a, b in zip(own, own[1:], strict=False)), (name, comp["what"])


def test_allowed_domains_never_touch_an_engine_site_or_anchor():
    pack = ROOT / "data" / "games" / "gen3_frlg"
    signals = json.loads((pack / "engine_signals.json").read_text(encoding="utf-8"))
    anchors = json.loads((pack / "write_checkpoint.json").read_text(encoding="utf-8"))
    for title in TITLES:
        guarded = set()
        for site in signals["titles"][title]["artifacts"]["clean"]["sites"].values():
            for rec in (site, site.get("context")):
                if rec:
                    guarded |= set(range(rec["rom_offset"], rec["rom_offset"] + len(rec["expected_hex"]) // 2))
        for a in anchors[title]["anchors"].values():
            guarded |= set(range(a["rom_offset"], a["rom_offset"] + len(a["expected_hex"]["clean"]) // 2))
        domains = MODEL["titles"][title]["domains"]
        for name, comps in domains.items():
            if name not in W.FORBIDDEN_DOMAINS:
                assert not guarded & _spans(comps), (title, name)


def test_allowed_meets_forbidden_only_at_the_known_normalisations():
    for title in TITLES:
        domains = MODEL["titles"][title]["domains"]
        forbidden = set().union(*(_spans(domains[d]) for d in W.FORBIDDEN_DOMAINS))
        known = _spans([c for c in domains["baseline"] if c.get("id") in KNOWN_OVERLAP])
        for name, comps in domains.items():
            if name not in W.FORBIDDEN_DOMAINS:
                assert not (_spans(comps) & forbidden) - known, (title, name)
        assert known & forbidden                     # the overlap is real, and named
        assert {c.get("id") for c in domains["baseline"]} >= KNOWN_OVERLAP


def test_free_space_admits_only_writes_packed_from_its_start():
    clean = bytes(0x200)
    model = {"titles": {"t": {"clean_sha1": hashlib.sha1(clean).hexdigest(), "domains": {
        "baseline": [{"what": "b", "source": "s", "ranges": "0x000150+4"}],
        "free_space": [{"what": "f", "source": "s", "ranges": "0x000100+256", "packed": True}]}}}}
    out = bytearray(clean)
    for i in (0x104, 0x105, 0x10B, 0x110, 0x152):     # gaps of 5 and 4; 0x152 is baseline's
        out[i] = 1
    assert W.audit("t", clean, bytes(out), {"baseline", "free_space"}, model)["stray"] == []
    out[0x117] = 1                                    # 6 unchanged bytes after 0x110
    r = W.audit("t", clean, bytes(out), {"baseline", "free_space"}, model)
    assert r["stray"] == [0x117] and r["named"] == {"free_space (not packed from 0x000100)": 1}
    assert W.audit("t", clean, bytes(out), {"baseline"}, model)["named"] == {"free_space": 5}


def test_check_output_refuses_by_name(tmp_path, monkeypatch):
    from server.upr_pipeline import UprPipelineError
    gba, jar = tmp_path / "c.gba", tmp_path / "other.jar"
    rom = bytearray(16 << 20)
    rom[0xAC:0xB0] = b"BPRE"
    gba.write_bytes(bytes(rom))
    jar.write_bytes(b"not the modelled jar")
    with pytest.raises(UprPipelineError, match="could not run"):          # OSError: no output
        W.check_output(str(gba), str(tmp_path / "missing.gba"), {})
    with pytest.raises(UprPipelineError, match=r"covers only \['firered', 'leafgreen'\]"):
        W.check_output(str(jar), str(jar), {})
    with pytest.raises(UprPipelineError, match="not the jar the write domains were modelled from"):
        W.check_output(str(gba), str(gba), {}, jar=str(jar))
    monkeypatch.setattr(W, "MODEL_PATH", tmp_path / "gone.json")
    with pytest.raises(UprPipelineError, match="could not run.*gone.json"):
        W.check_output(str(gba), str(gba), {})


def test_field_item_pool_is_the_forks_own():
    """FIELD_TMS / FIELD_REGULAR re-derived from the fork source's Gen3Constants.setupAllowedItems."""
    import re
    src = next((b / ".cache" / "slink-upr" / "src" / "com" / "dabomstew" / "pkrandom" / "constants"
                for b in (ROOT, *ROOT.parents) if (b / ".cache" / "slink-upr" / "src").is_dir()), None)
    if src is None:
        pytest.skip("fork source tree .cache/slink-upr/src absent")
    ids = {m[1]: int(m[2]) for m in re.finditer(r"int (\w+) = (\d+);", (src / "Gen3Items.java").read_text(encoding="utf-8"))}
    body = (src / "Gen3Constants.java").read_text(encoding="utf-8").split("void setupAllowedItems()")[1].split("nonBadItemsRSE =")[0]
    items = set(range(1, ids[re.search(r"new ItemList\(Gen3Items\.(\w+)\)", body)[1]] + 1))
    tms = set()
    for kind, args in re.findall(r"allowedItems\.(banRange|banSingles|tmRange)\(([^)]*)\)", body):
        vals = [ids[a.strip().removeprefix("Gen3Items.")] if "Gen3Items" in a else int(a) for a in args.split(",")]
        if kind == "banSingles":
            items -= set(vals)
        else:
            (items.difference_update if kind == "banRange" else tms.update)(range(vals[0], vals[0] + vals[1]))
    assert W.FIELD_TMS == tms and W.FIELD_REGULAR == items - tms


def test_audit_names_every_stray_byte():
    clean = bytes(64)
    model = {"titles": {"t": {"clean_sha1": hashlib.sha1(clean).hexdigest(), "domains": {
        "baseline": [{"what": "b", "source": "s", "ranges": "0x000000+2"}],
        "tms": [{"what": "t", "source": "s", "ranges": "0x000010+4"}],
        "types": [{"what": "x", "source": "s", "ranges": "0x000020+2"}]}}}}
    out = bytearray(clean)
    out[1] = out[0x11] = 1
    assert W.audit("t", clean, bytes(out), {"baseline", "tms"}, model)["stray"] == []
    r = W.audit("t", clean, bytes(out), {"baseline"}, model)
    assert r["stray"] == [0x11] and r["named"] == {"tms": 1}
    out[0x21] = out[0x30] = 1
    r = W.audit("t", clean, bytes(out), {"baseline", "tms"}, model)
    assert r["stray"] == [0x21, 0x30] and r["named"] == {"types": 1, "unattributed": 1}
    with pytest.raises(ValueError, match="not the pinned dump"):
        W.audit("t", bytes(out), bytes(out), {"baseline"}, model)
    with pytest.raises(ValueError, match="unknown write domain"):
        W.audit("t", clean, bytes(out), {"nope"}, model)


# ── ROM rows ────────────────────────────────────────────────────────────────────────────
def _clean_path(title: str) -> Path:
    _ROWS["attempted"].add(_row())
    env = [Path(os.environ["SLINK_GEN3_ROMS"])] if os.environ.get("SLINK_GEN3_ROMS") else []
    candidates = [base / rel for base in (*env, ROOT, *ROOT.parents) for rel in (STAGED[title], ROOT_DUMPS[title])]
    path = next((c for c in candidates if c.exists()), None)
    if path is None:
        _rom_skip(f"pinned clean {title} ROM absent (looked for {STAGED[title]} / {ROOT_DUMPS[title]})")
    digest = hashlib.sha1(path.read_bytes()).hexdigest()
    assert digest == rom_pins(str(ROOT))[title], f"{path} present but wrong {title} SHA-1 {digest}"
    return path


def _clean(title: str) -> bytes:
    return _clean_path(title).read_bytes()


def _jar() -> str:
    from server import upr_pipeline
    _ROWS["attempted"].add(_row())
    jar = upr_pipeline.find_upr_jar()
    if not jar or not upr_pipeline.jar_is_trusted(jar):
        _rom_skip("pinned SLink UPR fork jar absent (tools/build_upr_fork.py --pin)")
    return jar


def _log_spec(log: Path) -> dict:
    line = next(ln for ln in log.read_text(encoding="utf-8-sig").splitlines() if ln.startswith("Settings String:"))
    return U.spec_from_parsed(U.parse_settings_string(line.split(": ", 1)[1]), FRLG)


def test_model_is_the_fresh_build_from_the_pinned_jar_and_roms():
    roms = {t: _clean(t) for t in TITLES}
    jar = _jar()
    digest = hashlib.sha256(Path(jar).read_bytes()).hexdigest()
    assert digest == MODEL["jar_sha256"], (
        f"the pinned fork jar is {digest}, the model was built from {MODEL['jar_sha256']}: "
        f"regenerate with `python -m server.upr_gen3_write_domain --write` and re-run the evidence")
    assert W.dumps(W.build_model(Path(jar), roms)) == W.MODEL_PATH.read_text(encoding="utf-8")


def _manager_output(title: str, kind: str) -> Path:
    folder = os.environ.get("SLINK_GEN3_RAND_ROMS")
    name = f"{'FireRed' if title == 'firered' else 'LeafGreen'}_{kind}.gba"
    path = Path(folder or "/nonexistent") / name
    if not path.exists() or not Path(f"{path}.log").exists():
        _rom_skip(f"Manager-made {name} (+ .log) absent (set SLINK_GEN3_RAND_ROMS to the folder holding it)")
    return path


@pytest.mark.parametrize("title", TITLES)
def test_allowed_output_has_zero_stray_bytes(title):
    clean = _clean(title)
    out = _manager_output(title, "allowed")
    r = W.audit(title, clean, out.read_bytes(), W.domains_for_spec(_log_spec(Path(f"{out}.log"))))
    assert r["changed"] > 1000 and r["stray"] == [], r["named"]


@pytest.mark.parametrize("title", TITLES)
def test_widest_output_strays_are_named_by_the_forbidden_settings(title):
    clean = _clean(title)
    out = _manager_output(title, "widest")
    r = W.audit(title, clean, out.read_bytes(), W.domains_for_spec(_log_spec(Path(f"{out}.log"))))
    assert r["stray"], "the widest output (types/evolutions/movesets/stats/abilities random) passed"
    assert set(r["named"]) <= set(W.FORBIDDEN_DOMAINS), r["named"]
    assert {"types", "abilities", "base_stats", "evolutions", "movesets", "type_chart"} <= set(r["named"])


def _run_fork(tmp_path: Path, title: str, spec: dict) -> tuple[bytes, bytes, dict]:
    jar = _jar()
    if not shutil.which("java"):
        _rom_skip("java not on PATH")
    clean = _clean(title)
    src, settings, out = tmp_path / f"{title}.gba", tmp_path / "s.rnqs", tmp_path / f"{title}_out.gba"
    src.write_bytes(clean)
    settings.write_bytes(U.build_spec(spec, family=FRLG))
    subprocess.run(["java", "-jar", jar, "cli", "-s", str(settings), "-i", str(src), "-o", str(out), "-l"],
                   check=True, capture_output=True, timeout=300)
    return clean, out.read_bytes(), _log_spec(Path(f"{out}.log"))


@pytest.mark.parametrize("title", TITLES)
def test_lossless_control_writes_exactly_the_baseline(tmp_path, title):
    """Every setting off: the fork is not byte-identical -- it writes its unconditional baseline
    (intro Pokemon, the Marowak and roamer IPS, ability-2 and Deoxys normalisation) and nothing
    else; the header and its checksum are untouched."""
    clean, out, spec = _run_fork(tmp_path, title, _off_spec())
    assert W.domains_for_spec(spec) == {"baseline"}
    r = W.audit(title, clean, out, {"baseline"})
    assert r["stray"] == [] and r["changed"] > 0
    assert out[0xA0:0xC0] == clean[0xA0:0xC0]


@pytest.mark.parametrize("title", TITLES)
def test_every_allowed_option_at_once_stays_in_its_domains(tmp_path, title):
    spec = {k: _on_value(o) for k, o in U.options_for(FRLG).items()}
    # the combinations admission refuses as unverifiable (upr_settings.forbidden_enabled)
    spec.update(trainers="random", trainers_similar_strength=False, wild_restriction="none")
    clean, out, eff = _run_fork(tmp_path, title, spec)
    r = W.audit(title, clean, out, W.domains_for_spec(eff))   # (domains overlap here, e.g. fossil
    assert r["stray"] == [], r["named"]                        # levels inside statics: no tightness)


def _assert_tight(title: str, clean: bytes, out: bytes, enabled: set[str]):
    """0 stray bytes AND every enabled domain received a byte no other enabled domain explains
    (a domain granted to a setting that never writes it -- a WIDENED domain -- fails here)."""
    r = W.audit(title, clean, out, enabled)
    assert r["stray"] == [], r["named"]
    domains = MODEL["titles"][title]["domains"]
    changed = W.changed_offsets(clean, out)
    for d in sorted(enabled - {"baseline"}):
        others = W._merge(s for o in enabled - {d} for s in W._ranges(domains[o]))
        own = W._merge(W._ranges(domains[d]))
        assert any(W._inside(own, i) and not W._inside(others, i) for i in changed), (
            f"{d} is enabled by {sorted(enabled)} but received no byte of its own: a widened domain")


def _isolation_cases():
    """Every FR/LG option that writes, alone, at every choice value (catch-rate at every tier);
    a sub-option rides on the parent PARENT names. 59 cases per title."""
    off = _off_spec()
    for key, opt in U.options_for(FRLG).items():
        if key in W.NO_WRITE_OPTIONS:
            continue
        if opt["kind"] == "choice":
            values = [v for v in opt["choices"] if v != off[key]]
        elif opt["kind"] == "int":
            values = range(1, opt["max"] + 1) if key == "wild_min_catch_rate" else [opt["max"]]
        else:
            values = [True]
        yield from ((key, v) for v in values)


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize(("key", "value"), list(_isolation_cases()))
def test_each_option_alone_writes_exactly_its_domains(tmp_path, title, key, value):
    spec = {**_off_spec(), **PARENT.get(key, {}), key: value}
    clean, out, eff = _run_fork(tmp_path, title, spec)
    enabled = W.domains_for_spec(eff)
    assert enabled - W.domains_for_spec({**_off_spec(), **PARENT.get(key, {})}), (key, "enables nothing")
    _assert_tight(title, clean, out, enabled)


def test_pipeline_entry_point_admits_allowed_and_refuses_widest_by_name():
    from server.upr_pipeline import UprPipelineError
    src = _clean_path("firered")
    allowed, widest = _manager_output("firered", "allowed"), _manager_output("firered", "widest")
    got = W.check_output(str(src), str(allowed), _log_spec(Path(f"{allowed}.log")))
    assert got["changed"] > 1000 and "baseline" in got["domains"]
    with pytest.raises(UprPipelineError, match=r"outside the write domain.*evolutions \(\d+\)"):
        W.check_output(str(src), str(widest), _log_spec(Path(f"{widest}.log")))
