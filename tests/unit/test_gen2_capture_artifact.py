"""Stream B (docs/gen2/OVERLAY_ADMISSION.md D2/D4/D5/D7): every Gen 2 capture tool can record receipts on the OVERLAY
artifact with HONEST identity, and the clean path is unchanged.

No emulator. Red-first falsifiers:
  * an overlay launch plan exports the EXECUTED (hashed, staged) sha1, never the clean one, and the clean base rides a
    separately named field;
  * no env override can swap an identity binding;
  * the scripted-gate context refuses a clean romhash on an overlay run and an overlay romhash on a clean run;
  * overlay receipts land in the overlay namespace and never on a clean path;
  * a U1 union refuses to mix kinds or ROMs.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from lupa import LuaError, LuaRuntime

from tests.unit import test_run_gb_gate_gen2 as gate_host
from tests.unit.test_gen2_scripted_gate import GATE, Sim, make_env, make_root
from tools import gen2_fixtures as gx

host, invoke, runner = gate_host.host, gate_host.invoke, gate_host.runner   # the pytest fixture + module under test
ROOT = Path(__file__).resolve().parents[2]
PROVENANCE = "data/gen2/overlay_provenance.json"


def overlay_out(title="crystal", artifact="pokecrystal"):
    return json.loads((ROOT / PROVENANCE).read_text(encoding="utf-8"))["outputs"][artifact]


def stage_overlay_inputs(host, with_binding=True):
    """Copy the published provenance + UPS (and optionally the binding sidecar) into the model root."""
    out = overlay_out()
    rels = [PROVENANCE, out["ups"]["file"]]
    if with_binding:
        rels.append("data/games/gen2_crystal/overlay/binding.json")
    for rel in rels:
        (host["root"] / rel).parent.mkdir(parents=True, exist_ok=True)
        (host["root"] / rel).write_bytes((ROOT / rel).read_bytes())
    return out


# --- run_gb_gate: structured {title, kind} identity ----------------------------------------------------------------

@pytest.mark.parametrize("key,expected", [
    ("crystal", ("crystal", "clean", False)), ("crystal_cold", ("crystal", "clean", True)),
    ("gold_overlay", ("gold", "overlay", False)), ("silver_overlay_cold", ("silver", "overlay", True))])
def test_gate_keys_parse_into_title_kind_and_cold(key, expected):
    assert runner.parse_gen2_key(key) == expected
    assert runner.gen2_key(*expected) == key
    descriptor = runner.describe_gen2(key)
    assert (descriptor["title"], descriptor["kind"], descriptor["cold"]) == expected
    assert descriptor["overlay"] is (expected[1] == "overlay") and key in runner.ROM_TO_GEN


@pytest.mark.parametrize("key", ["crystal_cold_overlay", "crystal_overlay_overlay", "crystal11_overlay", "overlay", "_cold"])
def test_malformed_overlay_keys_are_unregistered(key):
    with pytest.raises(ValueError, match="unregistered"):
        runner.describe_gen2(key)


def test_overlay_cold_boot_works_and_keeps_the_filename_save_name(host):
    """<title>_overlay_cold used to fail suffix parsing: it is the overlay cartridge with no battery save."""
    stage_overlay_inputs(host)
    descriptor = runner.describe_gen2("crystal_overlay_cold")
    assert descriptor["cold"] and descriptor["overlay"] and descriptor["saveram_name"] == "gen2 crystal overlay.SaveRAM"
    assert invoke(host, rom_key="crystal_overlay_cold")[0]
    command, options = host["launches"][0]
    assert command[-1] == "patch/build/gen2_crystal_overlay.gbc"
    assert options["env"]["SLINK_GEN2_COLD"] == "1" and options["env"]["SLINK_GEN2_ARTIFACT_KIND"] == "overlay"
    assert host["deletes"] == [str(host["directory"] / descriptor["saveram_name"])] and not host["copies"]


def test_an_overlay_plan_exports_the_executed_sha1_and_keeps_the_clean_base_separate(host):
    out = stage_overlay_inputs(host)
    assert invoke(host, rom_key="crystal_overlay", fixture_path=host["fixture"])[0]
    env = host["launches"][0][1]["env"]
    staged = host["root"] / "patch/build/gen2_crystal_overlay.gbc"
    executed = hashlib.sha1(staged.read_bytes()).hexdigest()
    assert executed == out["sha1"] != out["base_sha1"]
    assert env["SLINK_GEN2_EXEC_SHA1"] == executed and env["SLINK_GEN2_OVERLAY_SHA1"] == executed
    assert env["SLINK_GEN2_BASE_SHA1"] == out["base_sha1"] and env["SLINK_GEN2_ARTIFACT_KIND"] == "overlay"
    assert env["SLINK_GEN2_EXEC_SHA1"] != env["SLINK_GEN2_BASE_SHA1"]
    # the facts binding keeps the clean base under its old name; it is not the executed identity
    assert env["SLINK_GEN2_ROM_SHA1"] == out["base_sha1"]
    binding = host["root"] / "data/games/gen2_crystal/overlay/binding.json"
    assert env["SLINK_GEN2_BINDING_SHA256"] == runner.binding_sha256(binding)


def test_a_clean_plan_executes_the_clean_base(host):
    assert invoke(host, rom_key="crystal_cold")[0]
    env = host["launches"][0][1]["env"]
    assert env["SLINK_GEN2_ARTIFACT_KIND"] == "clean"
    assert env["SLINK_GEN2_EXEC_SHA1"] == env["SLINK_GEN2_BASE_SHA1"] == env["SLINK_GEN2_ROM_SHA1"]
    assert "SLINK_GEN2_OVERLAY_SHA1" not in env and "SLINK_GEN2_BINDING_SHA256" not in env


def test_the_overlay_identity_follows_the_staged_image_not_a_label(host):
    """The recorded identity is hashed from the staged bytes: a UPS that no longer yields the published sha1 refuses."""
    stage_overlay_inputs(host)
    ups = host["root"] / overlay_out()["ups"]["file"]
    ups.write_bytes(ups.read_bytes()[:-1] + bytes([ups.read_bytes()[-1] ^ 1]))
    with pytest.raises(ValueError, match="overlay"):
        invoke(host, rom_key="crystal_overlay", fixture_path=host["fixture"])
    assert not host["launches"]


@pytest.mark.parametrize("name", ["SLINK_GEN2_EXEC_SHA1", "SLINK_GEN2_BASE_SHA1", "SLINK_GEN2_ARTIFACT_KIND",
                                  "SLINK_GEN2_BINDING_SHA256", "SLINK_GEN2_OVERLAY_SHA1", "SLINK_GEN2_ROM_SHA1"])
@pytest.mark.parametrize("key", ["crystal_cold", "crystal_overlay_cold"])
def test_no_env_override_can_swap_an_identity_binding(host, name, key):
    stage_overlay_inputs(host)
    with pytest.raises(ValueError, match="overrides"):
        invoke(host, rom_key=key, env_overrides={name: "0" * 40})
    assert not host["launches"]


def test_the_runner_names_every_identity_variable_as_protected():
    protected = runner.GENS["gen2"]["protected_env"]
    assert {"SLINK_GEN2_EXEC_SHA1", "SLINK_GEN2_BASE_SHA1", "SLINK_GEN2_ARTIFACT_KIND",
            "SLINK_GEN2_BINDING_SHA256", "SLINK_GEN2_OVERLAY_SHA1", "SLINK_GEN2_ROM_SHA1"} <= protected


def test_binding_pin_is_the_lf_form_so_autocrlf_is_not_a_different_binding(tmp_path):
    lf, crlf = tmp_path / "lf.json", tmp_path / "crlf.json"
    lf.write_bytes(b'{"a":1}\n{"b":2}\n')
    crlf.write_bytes(b'{"a":1}\r\n{"b":2}\r\n')
    assert runner.binding_sha256(lf) == runner.binding_sha256(crlf) == hashlib.sha256(lf.read_bytes()).hexdigest()


# --- the scripted-gate context: base facts and executed identity are bound separately -----------------------------

OVERLAY_SHA = overlay_out()["sha1"]
CLEAN_SHA = overlay_out()["base_sha1"]


def overlay_root(tmp_path):
    """A model root that also carries the real execution binding, artifact module and pack files the context reads."""
    root = make_root(tmp_path, "crystal")
    for rel in ("lua/gen2/artifact.lua", "lua/admission.lua"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, root / rel)
    for name in ("engine_signals.json", "write_checkpoint.json"):
        shutil.copy(ROOT / "data/games/gen2_crystal" / name, root / "data/games/gen2_crystal" / name)
    (root / "data/games/gen2_crystal/overlay").mkdir()
    shutil.copy(ROOT / "data/games/gen2_crystal/overlay/binding.json", root / "data/games/gen2_crystal/overlay/binding.json")
    return root


def context_of(root, env, running_sha):
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), "crystal", "town")
    sim.install(env)
    glob = sim.lua.globals()
    glob.SLINK_GEN2_GATE_LIBRARY = True
    glob.gameinfo = sim.lua.table_from({"getromhash": lambda: running_sha.upper()})   # what the emulator reports
    gate = sim.lua.execute(GATE.read_text(encoding="utf-8"))
    return gate.context(gate.bizhawk(), glob.os.getenv)


def overlay_env(root, **changes):
    _, env = make_env(root, "crystal", "town")
    env.update(SLINK_GEN2_ARTIFACT_KIND="overlay", SLINK_GEN2_OVERLAY_SHA1=OVERLAY_SHA, SLINK_GEN2_EXEC_SHA1=OVERLAY_SHA,
               SLINK_GEN2_BASE_SHA1=CLEAN_SHA,
               SLINK_GEN2_BINDING_SHA256=runner.binding_sha256(root / "data/games/gen2_crystal/overlay/binding.json"))
    env.update(changes)
    return env


def test_an_overlay_run_binds_the_overlay_hash_and_keeps_the_clean_facts_base(tmp_path):
    root = overlay_root(tmp_path)
    ctx = context_of(root, overlay_env(root), OVERLAY_SHA)
    assert ctx.env.kind == "overlay" and ctx.env.exec_sha1 == OVERLAY_SHA
    assert ctx.env.rom_sha1 == ctx.env.base_sha1 == CLEAN_SHA   # route facts / profile / charmap still bind the clean base
    assert ctx.artifact.kind == "overlay" and ctx.artifact.rom_sha1 == OVERLAY_SHA and ctx.artifact.base_sha1 == CLEAN_SHA
    assert ctx.ident.artifact_kind == "overlay" and ctx.ident.base_sha1 == CLEAN_SHA
    assert ctx.ident.binding_sha256 == ctx.env.binding_sha256


def test_an_overlay_run_refuses_a_clean_romhash(tmp_path):
    """The old gates aliased romhash to the clean base; the context must now refuse exactly that."""
    root = overlay_root(tmp_path)
    with pytest.raises(LuaError, match="running ROM differs from the selected SHA1"):
        context_of(root, overlay_env(root), CLEAN_SHA)


def test_a_clean_run_refuses_an_overlay_romhash(tmp_path):
    root = make_root(tmp_path, "crystal")
    _, env = make_env(root, "crystal", "town")
    ctx = context_of(root, env, CLEAN_SHA)
    assert ctx.env.kind == "clean" and ctx.env.exec_sha1 == CLEAN_SHA == ctx.env.rom_sha1
    assert ctx.artifact.kind == "clean" and ctx.ident.artifact_kind is None   # clean receipts keep their shape
    with pytest.raises(LuaError, match="running ROM differs from the selected SHA1"):
        context_of(root, env, OVERLAY_SHA)


@pytest.mark.parametrize("changes,match", [
    ({"SLINK_GEN2_BINDING_SHA256": ""}, "SLINK_GEN2_BINDING_SHA256"),                       # no sidecar pin: no overlay view
    ({"SLINK_GEN2_BINDING_SHA256": "0" * 64}, "overlay execution view refused"),            # pin differs from the sidecar
    ({"SLINK_GEN2_EXEC_SHA1": CLEAN_SHA}, "differs from SLINK_GEN2_OVERLAY_SHA1"),          # exec label contradicts overlay
    ({"SLINK_GEN2_OVERLAY_SHA1": CLEAN_SHA, "SLINK_GEN2_EXEC_SHA1": CLEAN_SHA}, "equals the clean base"),
    ({"SLINK_GEN2_OVERLAY_SHA1": ""}, "requires SLINK_GEN2_OVERLAY_SHA1"),
    ({"SLINK_GEN2_ARTIFACT_KIND": "clean"}, "carries no overlay identity"),                 # a clean label on overlay data
    ({"SLINK_GEN2_ARTIFACT_KIND": "ghost"}, "unsupported SLINK_GEN2_ARTIFACT_KIND"),
])
def test_an_inconsistent_identity_refuses_before_any_input(tmp_path, changes, match):
    root = overlay_root(tmp_path)
    with pytest.raises(LuaError, match=match):
        context_of(root, overlay_env(root, **changes), OVERLAY_SHA)


def test_a_clean_run_cannot_carry_overlay_variables(tmp_path):
    root = make_root(tmp_path, "crystal")
    _, env = make_env(root, "crystal", "town")
    env["SLINK_GEN2_OVERLAY_SHA1"] = OVERLAY_SHA
    env["SLINK_GEN2_ARTIFACT_KIND"] = "clean"
    with pytest.raises(LuaError, match="carries no overlay identity"):
        context_of(root, env, CLEAN_SHA)


@pytest.mark.parametrize("gate", ["panel", "sfx", "phone"])
def test_the_overlay_gates_no_longer_fake_a_clean_romhash(gate):
    """gen2_{panel,sfx,phone}_gate.lua wrapped the running ROM in a view whose romhash returned the clean base; the
    honest context binds the overlay itself."""
    text = (ROOT / f"lua/tests/gen2_{gate}_gate.lua").read_text(encoding="utf-8")
    assert "romhash=function() return ov.base_sha1 end" not in text and "SG.context(api, getenv)" in text
    assert "getromhash = function() return cfg.base_sha1" not in (ROOT / "lua/tests/gen2_w6_gate.lua").read_text(encoding="utf-8")


# --- overlay receipts live in the overlay namespace -----------------------------------------------------------------

CLASSES = ("engine_sites", "write_window")


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_overlay_receipts_land_in_the_overlay_namespace_never_on_a_clean_path(tmp_path, title):
    from tests.live import (
        conftest as live_conftest,
        test_gen2_new_gates as live,
        test_gen2_write_windows as u2,
    )

    clean, overlay = gx.receipts_dir("clean", tmp_path), gx.receipts_dir("overlay", tmp_path)
    assert overlay == clean / "overlay" and overlay != clean
    assert live.receipts_rel("overlay") == live.RECEIPTS + "/overlay" and live.receipts_rel("clean") == live.RECEIPTS
    names = [f"{title}.{kind}.json" for kind in CLASSES] + [f"{title}_battle.qualification.json",
                                                            "live_new_gates.inspect_run.json"]
    for name in names:
        o, c = live.receipt_file(name, "overlay", repo=tmp_path), live.receipt_file(name, "clean", repo=tmp_path)
        assert o == overlay / name and c == clean / name and o != c
        o.parent.mkdir(parents=True, exist_ok=True)
        o.write_text("{}", encoding="utf-8")
        assert not c.exists()   # writing the overlay receipt never touches a clean path
    assert u2.receipt_path(title, repo=tmp_path, kind="overlay") == overlay / f"{title}.write_window.json"
    assert u2.receipt_path(title, repo=tmp_path, kind="clean") == clean / f"{title}.write_window.json"
    assert live_conftest.OVERLAY_ATTESTATION != live_conftest.ATTESTATION
    assert live_conftest.ATTESTATION.replace("receipts/", "receipts/overlay/") == live_conftest.OVERLAY_ATTESTATION
    assert gx.shipped_receipts_dir(title, "overlay", tmp_path) == gx.shipped_receipts_dir(title, "clean", tmp_path) / "overlay"


def test_the_clean_namespace_is_the_unchanged_default():
    from tests.live import test_gen2_new_gates as live
    assert gx.artifact_kind({}) == "clean" and gx.artifact_kind({"SLINK_GEN2_ARTIFACT": "overlay"}) == "overlay"
    assert gx.receipts_dir("clean") == ROOT / live.RECEIPTS
    assert live.receipt_file("crystal.engine_sites.json", "clean") == ROOT / live.RECEIPTS / "crystal.engine_sites.json"
    with pytest.raises(ValueError, match="SLINK_GEN2_ARTIFACT"):
        gx.artifact_kind({"SLINK_GEN2_ARTIFACT": "patched"})


def test_the_inspect_run_attestation_is_byte_identical_on_clean_and_adds_identity_on_overlay():
    from tests.live import conftest
    counts = {**dict.fromkeys(conftest.COUNTS, 0), "passed": 13}
    titles = dict.fromkeys(("crystal", "gold", "silver"), "PASS")
    clean = conftest.attestation(counts, titles, {"digest": "x"})
    assert "artifacts" not in clean
    ids = {t: {"kind": "overlay", "rom_sha1": OVERLAY_SHA, "binding_sha256": "a" * 64} for t in titles}
    overlay = conftest.attestation(counts, titles, {"digest": "x"}, ids)
    assert {k: v for k, v in overlay.items() if k != "artifacts"} == clean and overlay["artifacts"]["gold"]["kind"] == "overlay"


# --- run identity and the U1 union ----------------------------------------------------------------------------------

CLEAN_ID = {"kind": "clean", "rom_sha1": CLEAN_SHA, "base_sha1": CLEAN_SHA, "binding_sha256": None}
OVERLAY_ID = {"kind": "overlay", "rom_sha1": OVERLAY_SHA, "base_sha1": CLEAN_SHA, "binding_sha256": "b" * 64}


def clean_run(fixture="crystal_battle"):
    return {"fixture": fixture, "rom_sha1": CLEAN_SHA}


def overlay_run(fixture="crystal_battle", **changes):
    return {"fixture": fixture, "rom_sha1": OVERLAY_SHA, "artifact_kind": "overlay", "binding_sha256": "b" * 64, **changes}


def test_a_run_must_be_the_hashed_staged_artifact():
    gx.check_run_identity(clean_run(), CLEAN_ID)
    gx.check_run_identity(overlay_run(), OVERLAY_ID)
    for run, identity in [(overlay_run(), CLEAN_ID), (clean_run(), OVERLAY_ID),
                          (overlay_run(rom_sha1=CLEAN_SHA), OVERLAY_ID),
                          (overlay_run(binding_sha256="c" * 64), OVERLAY_ID),
                          ({"fixture": "x", "rom_sha1": OVERLAY_SHA}, OVERLAY_ID),                 # overlay sha, no kind
                          ({**clean_run(), "binding_sha256": "b" * 64}, CLEAN_ID)]:               # clean wearing a binding
        with pytest.raises(ValueError):
            gx.check_run_identity(run, identity)
    with pytest.raises(ValueError):   # an overlay identity without a sidecar pin proves nothing
        gx.check_run_identity(overlay_run(), {**OVERLAY_ID, "binding_sha256": None})


SYNTH = {"crystal_synth_grass", "crystal_synth_kyle", "crystal_synth_bill"}


def test_the_u1_union_refuses_to_mix_kinds_or_roms():
    new_overlay = [overlay_run(f"crystal_synth_{k}") for k in ("grass", "kyle", "bill")]
    kept = overlay_run("crystal_battle")
    merged = gx.merge_engine_runs({"runs": [kept, overlay_run("crystal_synth_grass", stale=True)]}, new_overlay, OVERLAY_ID, SYNTH)
    assert [r["fixture"] for r in merged] == ["crystal_battle", "crystal_synth_grass", "crystal_synth_kyle", "crystal_synth_bill"]
    assert not any(r.get("stale") for r in merged)
    # a clean run kept in an overlay union, a clean run joining it, an overlay run joining a clean union, another ROM
    with pytest.raises(ValueError):
        gx.merge_engine_runs({"runs": [clean_run()]}, new_overlay, OVERLAY_ID, SYNTH)
    with pytest.raises(ValueError):
        gx.merge_engine_runs({"runs": [kept]}, [clean_run("crystal_synth_grass")], OVERLAY_ID, SYNTH)
    with pytest.raises(ValueError):
        gx.merge_engine_runs({"runs": [clean_run()]}, new_overlay, CLEAN_ID, SYNTH)
    with pytest.raises(ValueError):
        gx.merge_engine_runs({"runs": [kept]}, [overlay_run("crystal_synth_grass", rom_sha1="d" * 40)], OVERLAY_ID, SYNTH)
    # a v1 (single-run) committed receipt is one run and is checked the same way; its code_digest is not a run field
    assert gx.merge_engine_runs({**clean_run(), "code_digest": {"d": 1}}, [], CLEAN_ID, SYNTH) == [clean_run()]
    with pytest.raises(ValueError):
        gx.merge_engine_runs({**clean_run(), "code_digest": {"d": 1}}, new_overlay, OVERLAY_ID, SYNTH)


def test_the_u1g_merge_reads_and_writes_only_its_own_kinds_receipt(tmp_path, monkeypatch):
    from tests.live import test_gen2_u1g as u1g

    monkeypatch.setattr(u1g, "REPO", tmp_path)
    monkeypatch.setattr(u1g, "RUNS", tmp_path / "runs")
    u1g.RUNS.mkdir()
    for kind in u1g.KINDS:
        (u1g.RUNS / f"crystal_synth_{kind}.run.json").write_text(json.dumps(overlay_run(f"crystal_synth_{kind}")), encoding="utf-8")
    overlay_path = u1g.live.receipt_file("crystal.engine_sites.json", "overlay", repo=tmp_path)
    clean_path = u1g.live.receipt_file("crystal.engine_sites.json", "clean", repo=tmp_path)
    overlay_path.parent.mkdir(parents=True)
    # a committed OVERLAY receipt that carries a clean run: the union refuses and leaves the file alone
    overlay_path.write_text(json.dumps({"runs": [clean_run()]}), encoding="utf-8")
    before = overlay_path.read_bytes()
    with pytest.raises(ValueError):
        u1g.merge("crystal", "overlay", OVERLAY_ID)
    assert overlay_path.read_bytes() == before and not clean_path.exists()
    # the matching committed overlay receipt merges, in the overlay file, and never creates a clean one
    overlay_path.write_text(json.dumps(overlay_run()), encoding="utf-8")
    receipt = u1g.merge("crystal", "overlay", OVERLAY_ID)
    assert [r["fixture"] for r in receipt["runs"]][0] == "crystal_battle" and not clean_path.exists()
    assert json.loads(overlay_path.read_text(encoding="utf-8"))["runs"] == receipt["runs"]


# --- qualification boots the artifact that runs ---------------------------------------------------------------------

@pytest.mark.parametrize("kind,key", [("clean", "crystal"), ("overlay", "crystal_overlay")])
def test_the_qualification_gate_boots_the_selected_artifact_in_its_own_directory(kind, key):
    calls = []

    def fake(script, rom_key, **kwargs):
        calls.append((rom_key, kwargs["saveram_dir"]))
        return False, None, "model stop"

    context = type("Ctx", (), {"fixture": "crystal_town", "fingerprint": "f" * 64,
                               "artifacts": {"route_facts": json.dumps(gx.route_facts("crystal", ROOT, kind=kind)).encode()}})()
    attempt = ROOT / ".cache/gen2-fixtures/capture-artifact-model"   # scratch under the ignored cache; removed below
    try:
        with pytest.raises(ValueError, match="did not pass"):
            gx._stage_gate(context, "boot", bytes(1), label="boot", attempt_id="capture-artifact-model", root=ROOT,
                           runner=fake, timeout=1, kind=kind)
    finally:
        shutil.rmtree(attempt, ignore_errors=True)
    (rom_key, directory), = calls
    assert rom_key == key
    assert ("qualify-overlay" in Path(directory).parts) is (kind == "overlay")


def test_overlay_route_facts_are_resolved_on_the_overlay_and_equal_the_played_facts_where_nothing_moved():
    """The played-origin receipts stay valid on the overlay because the facts they fingerprint are identical."""
    for title in ("crystal", "gold", "silver"):
        clean, overlay = gx.route_facts(title, ROOT, kind="clean"), gx.route_facts(title, ROOT, kind="overlay")
        assert overlay["rom_sha1"] == clean["rom_sha1"]   # the lineage stays the clean base
        assert overlay["fingerprint"] == clean["fingerprint"], title
        assert gx.exec_sites(title, "overlay", ROOT)["save_completed"]["symbol"] == \
            gx.exec_sites(title, "clean", ROOT)["save_completed"]["symbol"]
    with pytest.raises(ValueError, match="kind"):
        gx.route_facts("crystal", ROOT, kind="patched")


# --- overlay qualification stands on the committed clean qualification of the same bytes -------------------------------

def stage_context(name, *, rom, rom_sha1, ref):
    from types import SimpleNamespace
    spec = gx.BY_NAME[name]
    raw = (ROOT / f"tests/fixtures/gen2/{name}.SaveRAM").read_bytes()
    facts = gx.route_facts(spec.title, ROOT)
    return SimpleNamespace(
        fixture=name, stage="qualify", fingerprint="f" * 64,
        provenance={"title": spec.title, "rom_sha1": rom_sha1, "scope": "candidate fixture",
                    "route_facts_sha256": gx._facts_sha256(facts)},
        artifacts={"fixture": raw, "rom": rom, "route_facts": json.dumps(facts).encode(),
                   "profile": (ROOT / f"data/games/gen2_{spec.title}/profile.json").read_bytes(),
                   "played_receipt": json.dumps(ref).encode()})


@pytest.mark.parametrize("name", ["crystal_town", "gold_battle_errand", "silver_battle"])
def test_the_overlay_static_stage_accepts_the_clean_qualification_reference_and_refuses_a_forged_one(name):
    from tools.gen2_source_data import load_overlay_context
    spec = gx.BY_NAME[name]
    raw = (ROOT / f"tests/fixtures/gen2/{name}.SaveRAM").read_bytes()
    octx = load_overlay_context(spec.title, root=ROOT)
    ref = gx.clean_qualification_ref(spec, raw, ROOT)
    assert gx.qualify_stage(stage_context(name, rom=octx.rom, rom_sha1=octx.execution_record()["rom_sha1"],
                                          ref=ref)).status == "PASS"
    for forged in ({**ref, "fixture_sha256": "0" * 64}, {**ref, "clean_report_sha256": "0" * 64},
                   {**ref, "schema": "gen2-played-route-v1"}):
        stage = gx.qualify_stage(stage_context(name, rom=octx.rom, rom_sha1=octx.execution_record()["rom_sha1"], ref=forged))
        assert stage.status == "FAIL" and "clean-qualification reference" in stage.problems[0], forged
    # the reference is overlay-only: a CLEAN ROM still demands the played-route receipt
    clean = load_overlay_context(spec.title, root=ROOT).base
    stage = gx.qualify_stage(stage_context(name, rom=clean.rom, rom_sha1=clean.source_record()["rom_sha1"], ref=ref))
    assert stage.status == "FAIL" and "played" in stage.problems[0]


def test_the_clean_qualification_reference_names_only_the_committed_clean_bytes():
    spec = gx.BY_NAME["crystal_town"]
    raw = (ROOT / "tests/fixtures/gen2/crystal_town.SaveRAM").read_bytes()
    with pytest.raises(ValueError, match="committed clean-qualified candidate"):
        gx.clean_qualification_ref(spec, raw[:-1] + bytes([raw[-1] ^ 1]), ROOT)


def test_the_overlay_fixture_set_is_the_one_the_overlay_proofs_name():
    """The capture tools qualify/inspect exactly lua/gen2/entry.lua RECEIPT_FILES overlay.qualifications (a drift would
    leave a fixture the production proofs() reads without a capture, or capture one nothing reads)."""
    import re
    text = (ROOT / "lua/gen2/entry.lua").read_text(encoding="utf-8")
    named = set(re.findall(r'(\w+)="data/games/gen2_\w+/receipts/overlay/\1\.qualification\.json"', text))
    assert named == set(gx.OVERLAY_QUALIFIED) and set(gx.OVERLAY_QUALIFIED) <= set(gx.BY_NAME)
    from tests.live import test_gen2_new_gates as live
    assert {s.name for s in live.INSPECT_FIXTURES} >= (set(gx.OVERLAY_QUALIFIED) if live.KIND == "overlay" else set(gx.BY_NAME))
