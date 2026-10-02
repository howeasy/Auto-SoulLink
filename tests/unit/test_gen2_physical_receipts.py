"""Card gen2-N18: every committed PHYSICAL Gen 2 receipt is validated by a test, not by a binder call.

Receipts are discovered by glob over tests/fixtures/gen2/receipts/:

    <title>.engine_sites.json    engine-site receipts   -> lua/gen2/signals.lua
                                                          S.qualified_sites + S.bind_fixture_qualification
    <title>.write_window.json    write-window receipts  -> lua/gen2_write_safety.lua
                                                          M.qualified + M.bind_fixture_qualification

Each discovered receipt runs its type's production validator under lupa (the paths S.new and M.new
themselves take) against the title's committed pack and the fixture's committed
<fixture>.qualification.json report, then asserts what the receipt claims: PHYSICAL evidence, the exact
proven site set / covered controls, title-keying and the qualification binding. The parametrization is
over the files found, so a new receipt is covered the moment it lands -- and a receipt whose type has no
validator FAILS the run instead of being skipped by it.

tests/fixtures/gen2/receipts/*.qualification.json are inputs to the binding, not receipts: they carry
full-chain fixture provenance (fixture-qualification-v1), not engine evidence.

OVERLAY (docs/gen2/OVERLAY_ADMISSION.md D4/D5): receipts under tests/fixtures/gen2/receipts/overlay/ are captured on the
patched cartridge. The expected artifact is resolved from the published manifest (data/gen2/overlay_provenance.json for the
overlay sha1/base, the execution binding sidecar for its sites/checkpoint and sha256) and handed to the SAME production
validators as their view {kind, rom_sha1, base_sha1, binding_sha256, sites, checkpoint}; the qualification reports are
read from the overlay directory. A clean receipt is refused under an overlay view and vice versa.

The Crystal write-window receipt is deliberately NOT re-validated here: it is already owned by
tests/unit/test_gen2_write_safety.py::test_the_committed_crystal_receipt_still_qualifies_and_binds
(line 751), which asserts its PHYSICAL runs, its authorized write kinds and both fixture bindings.
This file covers every other receipt -- today crystal.engine_sites.json, plus any write-window receipt
that appears later (e.g. gold.write_window.json) -- and adds the title-keying, qualification-binding and
negative-control assertions on the committed bytes.
"""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
RECEIPTS = ROOT / "tests/fixtures/gen2/receipts"
OVERLAY_RECEIPTS = RECEIPTS / "overlay"
FIXTURES = ROOT / "tests/fixtures/gen2"

SIGNALS = "lua/gen2/signals.lua"
WRITE_SAFETY = "lua/gen2_write_safety.lua"
VALIDATORS = ("engine_sites", "write_window")
TITLES = ("crystal", "gold", "silver")

# The one committed receipt this file must not re-test (see the module docstring): its sibling suite
# validates it, this file validates every other receipt.
COVERED_ELSEWHERE = {"crystal.write_window.json"}
# Live-gate receipts are not production admission receipts: tools/verify_gen2_release.py validates them
# (_panel_gate_row_errors, tested in tests/unit/test_verify_gen2_release_lanes.py). Listed by suffix, not skipped silently.
GATE_SUFFIXES = (".panel_gate.json", ".sfx_gate.json", ".w6_gate.json", ".phone_gate.json", ".sp_lowwater_gate.json",
                 ".inspect_run.json")   # 055ce230: the live-new-gates run attestation, checked by the release verifier

_MODULES = {}


def _module(relpath):
    """The production Lua module under a lupa runtime, loaded the way the existing unit tests load it."""
    if relpath not in _MODULES:
        lua = LuaRuntime(unpack_returned_tuples=True)
        _MODULES[relpath] = (lua, lua.eval("dofile")((ROOT / relpath).as_posix()))
    return _MODULES[relpath]


def _table(relpath, path):
    lua, _ = _module(relpath)
    return lua.table_from(json.loads(path.read_text(encoding="utf-8")), recursive=True)


def _unwrap(result):
    """A Lua refusal is `nil, why`; a success is the value itself. Never trust a summary flag."""
    return result if isinstance(result, tuple) else (result, None)


def _split(name):
    """(title, kind) of a receipt file name; kind is "unknown" when no validator exists for it."""
    for kind in VALIDATORS:
        suffix = f".{kind}.json"
        if name.endswith(suffix):
            return name[: -len(suffix)], kind
    return None, "unknown"


def _receipt(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _pack(title, name):
    return ROOT / "data/games" / f"gen2_{title}" / f"{name}.json"


def _qualification(fixture, artifact="clean"):
    return _qualification_dir(artifact) / f"{fixture}.qualification.json"


def _kind_of(path):
    """The artifact kind a receipt file belongs to: its directory (receipts/overlay/ is the overlay namespace)."""
    return "overlay" if Path(path).parent.name == "overlay" else "clean"


def _qualification_dir(artifact):
    return OVERLAY_RECEIPTS if artifact == "overlay" else RECEIPTS


def _view(title, artifact="clean"):
    """The executed-artifact view the production validators take: None for clean (the pack as committed), and for an
    overlay the manifest-resolved {kind, rom_sha1, base_sha1, binding_sha256, sites, checkpoint}. Identity comes from the
    published provenance and the sidecar's own bytes, never from the receipt under test."""
    if artifact == "clean":
        return None
    from tools.run_gb_gate import artifact_identity
    identity = artifact_identity(title, "overlay")
    binding = json.loads((ROOT / "data/games" / f"gen2_{title}" / "overlay/binding.json").read_text(encoding="utf-8"))
    assert binding["kind"] == "overlay" and binding["title"] == title and binding["rom_sha1"] == identity["rom_sha1"]
    return {**identity, "sites": binding["sites"], "checkpoint": binding["checkpoint"]}


def _with_view(args, view):
    """The validator's trailing optional view argument (nil = the clean pack, exactly as before)."""
    return args if view is None else [*args, _module(SIGNALS)[0].table_from(view, recursive=True)]


def _proven_sites(title, receipt, view=None):
    lua, S = _module(SIGNALS)
    return _unwrap(S.qualified_sites(*_with_view([title, _table(SIGNALS, _pack(title, "engine_signals")),
                                                  lua.table_from(receipt, recursive=True)], view)))


def _write_scope(title, receipt, view=None):
    lua, M = _module(WRITE_SAFETY)
    scope, why = _unwrap(M.qualified(*_with_view([_table(WRITE_SAFETY, _pack(title, "write_checkpoint")), title,
                                                  lua.table_from(receipt, recursive=True)], view)))
    if scope is None:
        return None, why
    return {"kinds": sorted(scope.kinds.keys()), "covered": list(scope.covered.values()),
            "uncovered": list(scope.uncovered.values())}, None


SYNTH_DIR = ROOT / "tests/fixtures/gen2"


def _engine_runs(receipt):
    """card U1G: an engine-site receipt is a v2 run list or one v1 run."""
    return receipt["runs"] if "runs" in receipt else [receipt]


def _bind(kind, receipt, view=None, artifact="clean"):
    """S.bind_fixture_qualification / M.bind_fixture_qualification: True, or nil and why."""
    lua, module = _module(SIGNALS if kind == "engine_sites" else WRITE_SAFETY)
    if kind == "engine_sites" and "runs" in receipt:
        # a v2 receipt takes every report by fixture name; a synthetic run's entry is its committed disclosure
        reports = {}
        for run in receipt["runs"]:
            disclosure = SYNTH_DIR / f"{run['fixture']}.synth.json"
            if disclosure.exists():
                committed = _receipt(disclosure)
                reports[run["fixture"]] = committed
                reports[committed["base_fixture"]] = _receipt(_qualification(committed["base_fixture"], artifact))
            else:
                reports[run["fixture"]] = _receipt(_qualification(run["fixture"], artifact))
    elif kind == "engine_sites":
        reports = _table(SIGNALS, _qualification(receipt["fixture"], artifact))
    else:
        reports = {receipt["runs"][mode]["fixture"]: _receipt(_qualification(receipt["runs"][mode]["fixture"], artifact))
                   for mode in ("town", "battle")}
    return _unwrap(module.bind_fixture_qualification(*_with_view(
        [lua.table_from(receipt, recursive=True), lua.table_from(reports, recursive=True)], view)))


def validate(kind, title, receipt, artifact="clean"):
    """The production validation path for one receipt: (proof, None), or (None, why) when refused.

    `artifact` is the kind the receipt is judged AS (its directory decides it for a committed file); an overlay is judged
    against its manifest-resolved view by the same validators. Raises when the receipt's type has no validator: an
    unvalidatable receipt is a failure, never a silent pass.
    """
    view = _view(title, artifact)
    if kind == "engine_sites":
        proven, why = _proven_sites(title, receipt, view)
        if proven is None:
            return None, why
        bound, why = _bind(kind, receipt, view, artifact)
        if bound is not True:
            return None, why
        return {"proven": sorted(proven.keys())}, None
    if kind == "write_window":
        scope, why = _write_scope(title, receipt, view)
        if scope is None:
            return None, why
        bound, why = _bind(kind, receipt, view, artifact)
        if bound is not True:
            return None, why
        return scope, None
    raise AssertionError(f"no PHYSICAL receipt validator for receipt type {kind!r}")


def validate_gate(title: str, receipt: dict, artifact: str = "clean"):
    """(ok, None) or (False, why) for a live-GATE receipt's ARTIFACT IDENTITY (B2).

    The five gate kinds (panel/sfx/phone/w6/sp_lowwater) are excluded from `discovered()` because the release
    verifier owns their physics, but nothing there recorded WHICH ARTIFACT produced them: the kind was inferred
    from the receipt's own type and `overlay_sha1` is a value both the writer and the reader take from provenance,
    so a relabelled or hand-written PASS satisfied every check. They now stamp the same identity triple the
    qualification and engine-site receipts carry, and this refuses any receipt whose identity is absent or does
    not match the manifest-resolved view -- including a receipt that claims to be clean in the overlay namespace.
    """
    view = _view(title, artifact)
    if artifact == "clean":
        if receipt.get("artifact_kind", "clean") != "clean" or "binding_sha256" in receipt:
            return False, "a clean gate receipt carries no overlay identity"
        return True, None
    for field, want in (("artifact_kind", "overlay"), ("rom_sha1", view["rom_sha1"]),
                        ("base_sha1", view["base_sha1"]), ("binding_sha256", view["binding_sha256"])):
        if receipt.get(field) != want:
            return False, f"gate receipt {field} is {receipt.get(field)!r}, not the published overlay {want!r}"
    if receipt["rom_sha1"] == view["base_sha1"]:
        return False, "gate receipt names the clean base as the executed artifact"
    observed = receipt.get("observed_rom_sha1")
    if observed is not None and observed != view["rom_sha1"]:
        return False, f"gate receipt observed_rom_sha1 {observed} is not the executed artifact"
    return True, None


def _owner(kind, title):
    """The receipt title this module lets authorize `title` (None when there is no receipt path).

    Read from the module's own keying table so the assertion follows the policy instead of restating it:
    engine sites have PHYSICAL_TITLES (Crystal only), write windows RECEIPT_TITLE (Silver follows Gold).
    """
    lua, module = _module(SIGNALS if kind == "engine_sites" else WRITE_SAFETY)
    return (module.PHYSICAL_TITLES if kind == "engine_sites" else module.RECEIPT_TITLE)[title]


def bindings(kind, receipt):
    """fixture -> (recorded sha256, qualification attempt) for the runs the binding covers. A synthetic run
    binds through its committed disclosure to the base fixture; its own bytes are the committed .SaveRAM that the
    disclosure names (checked here: the admission trust root is the disclosure, the bytes are the release lane's)."""
    if kind == "engine_sites":
        out = {}
        for run in _engine_runs(receipt):
            disclosure = SYNTH_DIR / f"{run['fixture']}.synth.json"
            if disclosure.exists():
                committed = _receipt(disclosure)
                staged = (SYNTH_DIR / f"{run['fixture']}.SaveRAM").read_bytes()
                assert hashlib.sha256(staged).hexdigest() == committed["sha256"] == run["fixture_sha256"], run["fixture"]
                out[committed["base_fixture"]] = (committed["base_sha256"], run["qualification_attempt_id"])
            else:
                out[run["fixture"]] = (run["fixture_sha256"], run["qualification_attempt_id"])
        return out
    return {receipt["runs"][mode]["fixture"]: (receipt["runs"][mode]["fixture_sha256"],
                                               receipt["runs"][mode]["qualification_attempt_id"])
            for mode in ("town", "battle")}


def discovered(root=RECEIPTS):
    """Every committed receipt of a validatable type, as pytest params: the clean ones and, beside them, the overlay
    namespace. Qualification reports are the binding's inputs, not receipts."""
    params = []
    for path in [*sorted(root.glob("*.json")), *sorted((root / "overlay").glob("*.json"))]:
        overlay = _kind_of(path) == "overlay"
        if (path.name.endswith(".qualification.json") or (path.name in COVERED_ELSEWHERE and not overlay)
                or path.name.endswith(GATE_SUFFIXES)):
            continue
        params.append(pytest.param(path, id=("overlay/" if overlay else "") + path.name))
    return params


RECEIPTS_FOUND = discovered()


@pytest.mark.parametrize("path", RECEIPTS_FOUND)
def test_a_committed_physical_receipt_still_validates(path):
    title, kind = _split(path.name)
    artifact = _kind_of(path)
    receipt = _receipt(path)
    proof, why = validate(kind, title, receipt, artifact)
    assert proof is not None, f"{path.name}: {why}"
    # the recorded artifact identity: an overlay receipt AND every run name the manifest's overlay; clean ones name none
    view = _view(title, artifact)
    for part in ([receipt, *(receipt.get("runs") or {}).values()] if isinstance(receipt.get("runs"), dict)
                 else [receipt, *(receipt.get("runs") or [])]):
        if artifact == "overlay":
            assert (part["artifact_kind"], part["rom_sha1"], part["binding_sha256"]) == (
                "overlay", view["rom_sha1"], view["binding_sha256"]), part.get("fixture")
        else:
            assert part.get("artifact_kind", "clean") == "clean" and "binding_sha256" not in part

    # (a) the receipt claims PHYSICAL evidence -- and says so for every run it rests on
    if kind == "engine_sites":
        assert {run["evidence_level"] for run in _engine_runs(receipt)} == {"PHYSICAL"}
        # (b) exactly the proven site set the receipt claims: the pack pins each hit and the
        # predecessors are present, so a dropped or inflated claim would surface here
        # (b2) card gen2-U1d: a proven battle_faint carries its own same-frame record, recomputed here from the
        # raw measurements (lua/tests/gen2_frame_align.lua F.faint_problem; S.qualified_sites does not read it)
        claimed = sorted({name for run in _engine_runs(receipt) for name in run["proven"]})
        assert proof["proven"] == claimed
        for run in _engine_runs(receipt):
            if "battle_faint" in run["proven"]:
                assert faint_aligned(run.get("faint_alignment")), run.get("faint_alignment")
    else:
        assert {run["evidence_level"] for run in receipt["runs"].values()} == {"PHYSICAL"}
        # (b) exactly the controls it declares covered, and the kinds those authorize
        assert proof["covered"] == sorted(receipt["covered_controls"])
        # card BOX: the box runs; O-30: the battle_faint run; O-32: the battle_bench run
        assert proof["kinds"] == ["backing_box", "battle_bench", "battle_faint", "box_deposit", "box_withdraw",
                                  "party_collection", "party_hp"]

    # (c) title-keying: a Crystal receipt is refused as gold/silver and vice versa. A title the module
    # itself lets this receipt cover (Silver follows Gold) is skipped rather than mis-asserted.
    for other in TITLES:
        if other == title or (artifact == "clean" and _owner(kind, other) == receipt["title"]):
            continue   # O-23 (Silver rides Gold) is clean-only: an overlay Silver is its own title
        refused, why = validate(kind, other, receipt, artifact)
        assert refused is None and why, f"{path.name} validated as {other}"

    # (d) the qualification binding, restated outside Lua: the receipt ran on the committed SaveRAM
    # bytes and names the committed report's attempt
    for fixture, (sha, attempt) in bindings(kind, receipt).items():
        report = _receipt(_qualification(fixture, artifact))
        if artifact == "overlay":   # a fresh boot/re-save/reload on the overlay: its provenance names the overlay sha1
            assert report["fixtures"][0]["provenance"]["rom_sha1"] == view["rom_sha1"], fixture
        assert sha == hashlib.sha256((FIXTURES / f"{fixture}.SaveRAM").read_bytes()).hexdigest(), fixture
        assert report["fixtures"][0]["artifacts"]["fixture"]["sha256"] == sha, fixture
        assert attempt == report["attempt_id"], fixture


def faint_aligned(f):
    """battle_faint's rule: callback == armed, wCurBattleMon a party slot, the battle mon at HP 0 and the slot's
    party record that mon (species, DVs) still above 0 in the callback, the copy-back HP 0 on that frame or the next."""
    def whole(v, lo, hi):
        return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi
    return (isinstance(f, dict) and whole(f.get("armed"), 0, 2**53) and f.get("callback") == f["armed"]
            and whole(f.get("party_count"), 1, 6) and whole(f.get("slot"), 0, f["party_count"] - 1)
            and f.get("battle_hp") == 0 and whole(f.get("battle_species"), 1, 251)
            and (f.get("party_species"), f.get("party_dvs")) == (f["battle_species"], f.get("battle_dvs"))
            and whole(f.get("callback_party_hp"), 1, 999)
            and whole(f.get("hp_zero_frame"), f["callback"], f["callback"] + 1))


@pytest.mark.parametrize("field,value", [("callback", 1), ("battle_hp", 3), ("party_species", 0), ("party_dvs", -1),
                                         ("callback_party_hp", 0), ("hp_zero_frame", 2), ("slot", 2), (None, None)])
def test_the_faint_rule_refuses_each_broken_measurement(field, value):
    good = {"armed": 10, "callback": 10, "slot": 0, "party_count": 2, "battle_hp": 0, "battle_species": 158,
            "battle_dvs": 0x1234, "party_species": 158, "party_dvs": 0x1234, "callback_party_hp": 4,
            "post_party_hp": 0, "hp_zero_frame": 10}
    assert faint_aligned(good) and faint_aligned({**good, "hp_zero_frame": 11})
    bad = None if field is None else {**good, field: good[field] + value if field in ("callback", "hp_zero_frame") else value}
    assert not faint_aligned(bad)


DELETE = object()


def _set(receipt, path, value):
    node = receipt
    keys = path.split(".")
    for key in keys[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    last = keys[-1]
    if value is DELETE:
        del node[last]
    elif isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


def _flip_hex(value, at):
    raw = bytearray(bytes.fromhex(value))
    raw[at] ^= 0x01
    return raw.hex()


def _proven_site_off(receipt, title, kind):
    """One proven site's recorded hit no longer matches the pack: off."""
    receipt = _engine_runs(receipt)[0] if kind == "engine_sites" else receipt
    if kind == "engine_sites":
        name = sorted(receipt["proven"])[0]
        row = receipt["sites"][name]
        _set(receipt, f"sites.{name}.expected_hex", _flip_hex(row["expected_hex"], 0))
        return "differs from the pack or has no live hit"
    party = receipt["runs"]["town"]["write"]["party"]
    _set(receipt, "runs.town.write.party.written_hex", _flip_hex(party["written_hex"], 0))
    return "not a read-back HP-1"


def _proven_site_on(receipt, title, kind):
    """An unproven site is claimed as proven: on."""
    receipt = _engine_runs(receipt)[0] if kind == "engine_sites" else receipt
    if kind == "engine_sites":
        silent = [name for name in sorted(receipt["sites"])
                  if name not in set(receipt["proven"]) and receipt["sites"][name]["hits"] == 0]
        assert silent, "no unproven silent site left to claim"
        _set(receipt, "proven", sorted(receipt["proven"]) + [silent[0]])
        return "differs from the pack or has no live hit"
    _set(receipt, "covered_controls", sorted(receipt["covered_controls"]) + ["textbox"])
    return "did not prove: textbox"


def _other_fixture_sha(receipt, title, kind):
    """Other fixture bytes than the qualified ones (the binding is what catches this)."""
    receipt = _engine_runs(receipt)[0] if kind == "engine_sites" else receipt
    if kind == "engine_sites":
        _set(receipt, "fixture_sha256", "0" * 64)
    else:
        _set(receipt, "runs.battle.fixture_sha256", "0" * 64)
    return "other fixture bytes"


def _model_evidence(receipt, title, kind):
    """A MODEL run relabelled PHYSICAL."""
    receipt = _engine_runs(receipt)[0] if kind == "engine_sites" else receipt
    if kind == "engine_sites":
        _set(receipt, "evidence_level", "MODEL")
        return "PHYSICAL engine-site qualification receipt required"
    _set(receipt, "runs.town.evidence_level", "MODEL")
    return "town run is not a passed PHYSICAL gate run"


def _title_swap(receipt, title, kind):
    """The Crystal payload wearing another title's name: refused by this title's validator."""
    other = next(other for other in TITLES if other != title)
    for run in (_engine_runs(receipt) if kind == "engine_sites" else [receipt]):
        _set(run, "title", other)
    _set(receipt, "title", other)
    return "another title"


NEGATIVES = {
    "a_proven_site_flipped_off": _proven_site_off,
    "an_unproven_site_flipped_on": _proven_site_on,
    "fixture_sha256_changed": _other_fixture_sha,
    "evidence_relabelled_MODEL": _model_evidence,
    "title_swapped": _title_swap,
}


@pytest.mark.parametrize("negative", sorted(NEGATIVES))
@pytest.mark.parametrize("path", RECEIPTS_FOUND)
def test_a_mutated_receipt_is_refused(path, negative):
    title, kind = _split(path.name)
    receipt = copy.deepcopy(_receipt(path))
    expected = NEGATIVES[negative](receipt, title, kind)
    proof, why = validate(kind, title, receipt, _kind_of(path))
    assert proof is None and expected in why, f"{negative}: {why}"


def _relabelled(title):
    """The committed clean engine-site receipt wearing the manifest overlay identity on the receipt and every run: the
    shape an overlay receipt takes whose sites are the overlay's (sites are identical where nothing moved)."""
    view = _view(title, "overlay")
    receipt = copy.deepcopy(_receipt(RECEIPTS / f"{title}.engine_sites.json"))
    for part in [receipt, *receipt.get("runs", [])]:
        part.update(artifact_kind="overlay", rom_sha1=view["rom_sha1"], binding_sha256=view["binding_sha256"])
    return receipt, view


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("change", ["kind_dropped", "clean_sha", "binding_changed", "base_sha"])
def test_an_overlay_receipt_with_a_borrowed_identity_is_refused(title, change):
    """The overlay identity is part of the proof (control: the well-formed one validates under the overlay view)."""
    receipt, view = _relabelled(title)
    assert _proven_sites(title, receipt, view)[0] is not None, "control: the well-formed overlay receipt is accepted"
    for part in [receipt, *receipt.get("runs", [])]:
        if change == "kind_dropped":
            part.pop("artifact_kind")
        elif change == "clean_sha":
            part["rom_sha1"] = view["base_sha1"]
        elif change == "base_sha":
            part["rom_sha1"] = "0" * 40
        else:
            part["binding_sha256"] = "0" * 64
    proof, why = _proven_sites(title, receipt, view)
    assert proof is None and why, change


def test_discovery_covers_the_overlay_namespace_and_judges_each_file_as_its_directory(tmp_path):
    (tmp_path / "overlay").mkdir()
    for name in ("crystal.engine_sites.json", "crystal.write_window.json", "crystal_town.qualification.json",
                 "crystal_overlay.panel_gate.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
        (tmp_path / "overlay" / name).write_text("{}", encoding="utf-8")
    found = {p.id for p in discovered(tmp_path)}
    # the clean write window is owned by its sibling suite; an overlay one has none and is covered here
    assert found == {"crystal.engine_sites.json", "overlay/crystal.engine_sites.json", "overlay/crystal.write_window.json"}
    assert [_kind_of(p.values[0]) for p in discovered(tmp_path)] == ["clean", "overlay", "overlay"]


def test_a_clean_receipt_is_refused_as_an_overlay_and_the_view_comes_from_the_manifest():
    """Known-positive control for the overlay path: the committed clean receipts validate as clean and are refused as
    overlay (their runs name no overlay identity), under the view the manifest resolves."""
    for title in ("crystal", "gold", "silver"):
        view = _view(title, "overlay")
        assert view["kind"] == "overlay" and view["rom_sha1"] != view["base_sha1"] and len(view["binding_sha256"]) == 64
        assert view["sites"] and view["checkpoint"]
    receipt = _receipt(RECEIPTS / "crystal.engine_sites.json")
    assert validate("engine_sites", "crystal", receipt, "clean")[0] is not None
    refused, why = validate("engine_sites", "crystal", receipt, "overlay")
    assert refused is None and why


def test_neither_validator_accepts_the_other_type_receipt():
    """Both validators are wired and mutually exclusive: an engine-site receipt is not a write-window
    receipt and the write-window receipt is not an engine-site receipt. (The write-window receipt's own
    acceptance is owned by tests/unit/test_gen2_write_safety.py, see the module docstring.)"""
    refused, why = validate("write_window", "crystal", _receipt(RECEIPTS / "crystal.engine_sites.json"))
    assert refused is None and "write-window receipt required" in why, why
    refused, why = validate("engine_sites", "crystal", _receipt(RECEIPTS / "crystal.write_window.json"))
    assert refused is None and "PHYSICAL engine-site qualification receipt required" in why, why


def test_a_receipt_type_without_a_validator_fails_rather_than_skips():
    """A new receipt file of an unknown type must fail the lane, never pass by being ignored."""
    with pytest.raises(AssertionError, match="no PHYSICAL receipt validator"):
        validate("badge_sites", "crystal", {"schema": "gen2-badge-receipt-v1"})


def test_the_uncovered_receipt_is_owned_by_its_sibling_suite():
    """The exclusion in COVERED_ELSEWHERE is a coverage choice, not a gap: the named file must exist and
    be of a type this file knows how to validate, so the exclusion can never hide an unvalidatable one."""
    assert COVERED_ELSEWHERE == {"crystal.write_window.json"}
    path = RECEIPTS / next(iter(COVERED_ELSEWHERE))
    title, kind = _split(path.name)
    assert path.is_file() and kind in VALIDATORS and title == "crystal"


GATE_KINDS = ("panel_gate", "sfx_gate", "phone_gate", "w6_gate", "sp_lowwater_gate")


def _overlay_gate_receipt(title="crystal", **overrides):
    """A well-formed overlay gate receipt: the identity every gate now stamps, plus the fields a gate carries."""
    view = _view(title, "overlay")
    receipt = {"schema": "gen2-panel-gate-v1", "title": title, "fixture": f"{title}_battle",
               "result": "PASS", "evidence_level": "PHYSICAL", "overlay_sha1": view["rom_sha1"],
               "observed_rom_sha1": view["rom_sha1"], "artifact_kind": "overlay",
               "rom_sha1": view["rom_sha1"], "base_sha1": view["base_sha1"],
               "binding_sha256": view["binding_sha256"]}
    receipt.update(overrides)
    return receipt


def test_a_gate_receipt_that_records_no_artifact_identity_is_refused():
    """B2, the negative the old gate receipts would have failed: nothing recorded WHICH artifact ran.

    Before the fix a gate receipt carried `base_sha1` and `overlay_sha1` only, the kind was inferred from the
    receipt's own type, and any PASS with the published overlay sha1 satisfied every check. The identity is now
    required, so an unlabelled receipt in the overlay namespace is refused rather than assumed to be overlay.
    """
    view = _view("crystal", "overlay")
    unlabelled = {"schema": "gen2-panel-gate-v1", "title": "crystal", "result": "PASS",
                  "evidence_level": "PHYSICAL", "overlay_sha1": view["rom_sha1"]}
    ok, why = validate_gate("crystal", unlabelled, "overlay")
    assert not ok and "artifact_kind" in why
    # the pre-fix shape judged as a clean receipt would have been accepted; it must not be either
    assert not validate_gate("crystal", dict(unlabelled, artifact_kind="overlay", binding_sha256="0" * 64),
                             "overlay")[0], "a wrong binding pin was accepted"


@pytest.mark.parametrize("change,fragment", [
    ("drop_kind", "artifact_kind"),
    ("clean_sha", "rom_sha1"),
    ("wrong_binding", "binding_sha256"),
    ("wrong_base", "base_sha1"),
    ("wrong_observed", "observed_rom_sha1"),
])
def test_an_overlay_gate_receipt_with_a_borrowed_identity_is_refused(change, fragment):
    """Every field of the stamped identity is load-bearing, including the in-emulator observation."""
    view = _view("crystal", "overlay")
    receipt = _overlay_gate_receipt()
    if change == "drop_kind":
        receipt.pop("artifact_kind")
    elif change == "clean_sha":
        receipt["rom_sha1"] = view["base_sha1"]
    elif change == "wrong_binding":
        receipt["binding_sha256"] = "0" * 64
    elif change == "wrong_base":
        receipt["base_sha1"] = "0" * 40
    else:
        receipt["observed_rom_sha1"] = view["base_sha1"]
    ok, why = validate_gate("crystal", receipt, "overlay")
    assert not ok and fragment in why, (change, why)


def test_a_clean_gate_receipt_cannot_wear_overlay_identity_and_an_overlay_one_cannot_pose_clean():
    """Both directions of the namespace rule: the two receipt kinds may not borrow each other's identity."""
    assert validate_gate("crystal", _overlay_gate_receipt(), "clean")[0] is False
    assert validate_gate("crystal", {"schema": "gen2-panel-gate-v1", "title": "crystal"}, "clean")[0] is True


@pytest.mark.parametrize("kind", GATE_KINDS)
def test_every_gate_receipt_kind_is_covered_by_the_identity_validator(kind):
    """The five gate kinds are excluded from discovery() (the release verifier owns their physics); this
    asserts none of them is excluded from the IDENTITY check, which is what used to be missing."""
    assert kind.endswith("_gate")
    ok, why = validate_gate("crystal", _overlay_gate_receipt(), "overlay")
    assert ok is True, why