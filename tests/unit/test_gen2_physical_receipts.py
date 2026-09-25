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
GATE_SUFFIXES = (".panel_gate.json", ".sfx_gate.json", ".w6_gate.json", ".phone_gate.json",
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


def _qualification(fixture):
    return RECEIPTS / f"{fixture}.qualification.json"


def _proven_sites(title, receipt):
    lua, S = _module(SIGNALS)
    return _unwrap(S.qualified_sites(title, _table(SIGNALS, _pack(title, "engine_signals")),
                                     lua.table_from(receipt, recursive=True)))


def _write_scope(title, receipt):
    lua, M = _module(WRITE_SAFETY)
    scope, why = _unwrap(M.qualified(_table(WRITE_SAFETY, _pack(title, "write_checkpoint")), title,
                                     lua.table_from(receipt, recursive=True)))
    if scope is None:
        return None, why
    return {"kinds": sorted(scope.kinds.keys()), "covered": list(scope.covered.values()),
            "uncovered": list(scope.uncovered.values())}, None


SYNTH_DIR = ROOT / "tests/fixtures/gen2"


def _engine_runs(receipt):
    """card U1G: an engine-site receipt is a v2 run list or one v1 run."""
    return receipt["runs"] if "runs" in receipt else [receipt]


def _bind(kind, receipt):
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
                reports[committed["base_fixture"]] = _receipt(_qualification(committed["base_fixture"]))
            else:
                reports[run["fixture"]] = _receipt(_qualification(run["fixture"]))
    elif kind == "engine_sites":
        reports = _table(SIGNALS, _qualification(receipt["fixture"]))
    else:
        reports = {receipt["runs"][mode]["fixture"]: _receipt(_qualification(receipt["runs"][mode]["fixture"]))
                   for mode in ("town", "battle")}
    return _unwrap(module.bind_fixture_qualification(lua.table_from(receipt, recursive=True),
                                                     lua.table_from(reports, recursive=True)))


def validate(kind, title, receipt):
    """The production validation path for one receipt: (proof, None), or (None, why) when refused.

    Raises when the receipt's type has no validator: an unvalidatable receipt is a failure, never a
    silent pass.
    """
    if kind == "engine_sites":
        proven, why = _proven_sites(title, receipt)
        if proven is None:
            return None, why
        bound, why = _bind(kind, receipt)
        if bound is not True:
            return None, why
        return {"proven": sorted(proven.keys())}, None
    if kind == "write_window":
        scope, why = _write_scope(title, receipt)
        if scope is None:
            return None, why
        bound, why = _bind(kind, receipt)
        if bound is not True:
            return None, why
        return scope, None
    raise AssertionError(f"no PHYSICAL receipt validator for receipt type {kind!r}")


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


def discovered():
    """Every committed receipt of a validatable type, as pytest params. Qualification reports are the
    binding's inputs, not receipts."""
    params = []
    for path in sorted(RECEIPTS.glob("*.json")):
        if (path.name.endswith(".qualification.json") or path.name in COVERED_ELSEWHERE
                or path.name.endswith(GATE_SUFFIXES)):
            continue
        params.append(pytest.param(path, id=path.name))
    return params


RECEIPTS_FOUND = discovered()


@pytest.mark.parametrize("path", RECEIPTS_FOUND)
def test_a_committed_physical_receipt_still_validates(path):
    title, kind = _split(path.name)
    receipt = _receipt(path)
    proof, why = validate(kind, title, receipt)
    assert proof is not None, f"{path.name}: {why}"

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
        if other == title or _owner(kind, other) == receipt["title"]:
            continue
        refused, why = validate(kind, other, receipt)
        assert refused is None and why, f"{path.name} validated as {other}"

    # (d) the qualification binding, restated outside Lua: the receipt ran on the committed SaveRAM
    # bytes and names the committed report's attempt
    for fixture, (sha, attempt) in bindings(kind, receipt).items():
        report = _receipt(_qualification(fixture))
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
    proof, why = validate(kind, title, receipt)
    assert proof is None and expected in why, f"{negative}: {why}"


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