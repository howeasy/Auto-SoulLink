"""The shared runner must not turn absent stages, stale receipts or skips into PASS."""
from pathlib import Path

from tools import fixture_qualification as shared


def setup_case(tmp_path):
    save, rom = tmp_path / "candidate.bin", tmp_path / "cartridge.bin"
    save.write_bytes(b"candidate save")
    rom.write_bytes(b"cartridge")
    resave = tmp_path / "resaved.bin"
    resave.write_bytes(b"candidate after re-save")
    return shared.FixtureCase("candidate", {"fixture": save, "rom": rom},
                              {"game": "model-game", "model_resave": str(resave)})


def passing(context):
    outputs = {"fixture": Path(context.provenance["model_resave"])} if context.stage == "resave" else {}
    return shared.StageReceipt(context.stage, context.fingerprint, "PASS",
                               evidence={"oracle": "model-control"}, outputs=outputs)


def test_full_chain_order_and_actual_input_provenance(tmp_path):
    case = setup_case(tmp_path)
    seen = []

    def stage(context):
        seen.append((context.stage, len(context.previous)))
        assert context.artifacts["fixture"] == b"candidate save"
        if context.stage == "post_oracle":
            assert context.artifacts["resave:fixture"] == b"candidate after re-save"
        return passing(context)

    report = shared.qualify_fixtures([case], dict.fromkeys(shared.FULL_CHAIN, stage), scope="full")
    assert report["passed"] is True
    assert seen == list(zip(shared.FULL_CHAIN, range(4), strict=True))
    assert report["fixtures"][0]["artifacts"]["fixture"]["sha256"]
    assert report["required_stages"] == list(shared.FULL_CHAIN)


def test_every_missing_required_stage_refuses_before_any_callback(tmp_path):
    case = setup_case(tmp_path)
    for missing in shared.FULL_CHAIN:
        seen = []
        callbacks = {name: lambda context, seen=seen: (seen.append(context.stage), passing(context))[1]
                     for name in shared.FULL_CHAIN if name != missing}
        report = shared.qualify_fixtures([case], callbacks, scope="full")
        assert report["passed"] is False and not seen
        assert missing in str(report["errors"])


def test_failed_independent_oracle_and_skip_cannot_pass(tmp_path):
    case = setup_case(tmp_path)
    for status in ("FAIL", "SKIP"):
        callbacks = dict.fromkeys(shared.FULL_CHAIN, passing)
        callbacks["post_oracle"] = lambda context, status=status: shared.StageReceipt(
            context.stage, context.fingerprint, status, problems=("independent readback disagrees",))
        report = shared.qualify_fixtures([case], callbacks, scope="full")
        assert report["passed"] is False
        assert report["fixtures"][0]["stages"][-1]["status"] != "PASS"


def test_previous_attempt_receipt_is_stale_even_with_same_input_bytes(tmp_path):
    case = setup_case(tmp_path)
    receipts = []

    def capture(context):
        receipts.append(passing(context))
        return receipts[-1]

    assert shared.qualify_fixtures([case], {"qualify": capture}, scope="static", attempt_id="first")["passed"]
    second = shared.qualify_fixtures([case], {"qualify": lambda _: receipts[0]}, scope="static", attempt_id="second")
    assert not second["passed"] and "stale" in str(second)


def test_input_change_during_stage_refuses_and_does_not_run_later_stages(tmp_path):
    case = setup_case(tmp_path)
    seen = []

    def change(context):
        seen.append(context.stage)
        case.paths["rom"].write_bytes(b"different cartridge")
        return passing(context)

    callbacks = dict.fromkeys(shared.FULL_CHAIN, passing)
    callbacks["qualify"] = change
    report = shared.qualify_fixtures([case], callbacks, scope="full")
    assert not report["passed"] and seen == ["qualify"]
    assert "changed" in str(report)


def test_empty_duplicate_and_over_limit_inventory_fail(tmp_path):
    case = setup_case(tmp_path)
    for cases in ([], [case, case]):
        assert not shared.qualify_fixtures(cases, {"qualify": passing}, scope="static")["passed"]
    other = shared.FixtureCase("other", case.paths, case.provenance)
    assert not shared.qualify_fixtures([case, other], {"qualify": passing}, scope="static", max_fixtures=1)["passed"]


def test_missing_artifact_and_callback_exception_are_reported(tmp_path):
    case = setup_case(tmp_path)
    case.paths["rom"].unlink()
    report = shared.qualify_fixtures([case], {"qualify": passing}, scope="static")
    assert not report["passed"] and report["fixtures"][0]["missing_artifact"] == "rom"
    case = setup_case(tmp_path)

    def broken(_):
        raise RuntimeError("oracle unavailable")

    report = shared.qualify_fixtures([case], {"qualify": broken}, scope="static")
    assert not report["passed"] and "oracle unavailable" in str(report)


def test_enumeration_is_sorted_bounded_and_does_not_accept_empty_or_nested(tmp_path):
    (tmp_path / "b.fixture").write_bytes(b"b")
    (tmp_path / "a.fixture").write_bytes(b"a")
    (tmp_path / "ignored.txt").write_bytes(b"not fixture")
    assert [path.name for path in shared.enumerate_fixtures(tmp_path, suffix=".fixture")] == ["a.fixture", "b.fixture"]
    for directory, limit in ((tmp_path, 1), (tmp_path / "absent", 20)):
        try:
            shared.enumerate_fixtures(directory, suffix=".fixture", max_fixtures=limit)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid fixture inventory accepted")


def test_callback_cannot_mutate_captured_input_mapping(tmp_path):
    case = setup_case(tmp_path)

    def mutate(context):
        context.artifacts["fixture"] = b"replacement"
        return passing(context)

    assert not shared.qualify_fixtures([case], {"qualify": mutate}, scope="static")["passed"]


def test_resave_without_output_or_changed_resave_output_refuses(tmp_path):
    case = setup_case(tmp_path)
    callbacks = dict.fromkeys(shared.FULL_CHAIN, passing)
    callbacks["resave"] = lambda c: shared.StageReceipt(c.stage, c.fingerprint, "PASS", evidence={"result": "claimed"})
    report = shared.qualify_fixtures([case], callbacks, scope="full")
    assert not report["passed"] and "no output artifact" in str(report)
    callbacks["resave"] = passing

    def altered_output(context):
        Path(context.provenance["model_resave"]).write_bytes(b"changed after re-save")
        return passing(context)

    callbacks["post_oracle"] = altered_output
    report = shared.qualify_fixtures([case], callbacks, scope="full")
    assert not report["passed"] and "changed" in str(report)


def test_boolean_or_empty_evidence_is_not_an_oracle_receipt(tmp_path):
    case = setup_case(tmp_path)
    for callback in (lambda _: True,
                     lambda c: shared.StageReceipt(c.stage, c.fingerprint, "PASS")):
        assert not shared.qualify_fixtures([case], {"qualify": callback}, scope="static")["passed"]


def output_inventory(tmp_path, *, collide):
    cases = []
    for name in ("first", "second"):
        fixture = tmp_path / (name + ".bin")
        fixture.write_bytes(name.encode())
        output = tmp_path / ("shared-output.bin" if collide else name + "-output.bin")
        cases.append(shared.FixtureCase(name, {"fixture": fixture}, {"game": "model", "output": str(output)}))

    def stage(context):
        outputs = {}
        if context.stage == "resave":
            path = Path(context.provenance["output"])
            path.write_bytes(context.artifacts["fixture"] + b" resaved")
            outputs["fixture"] = path
        if context.stage == "post_oracle":
            assert context.artifacts["resave:fixture"] == context.artifacts["fixture"] + b" resaved"
        return shared.StageReceipt(context.stage, context.fingerprint, "PASS",
                                   evidence={"oracle": "independent model output readback"}, outputs=outputs)

    return cases, dict.fromkeys(shared.FULL_CHAIN, stage)


def test_two_full_cases_with_distinct_output_snapshots_pass(tmp_path):
    cases, callbacks = output_inventory(tmp_path, collide=False)
    report = shared.qualify_fixtures(cases, callbacks, scope="full")
    assert report["passed"] and all(row["passed"] for row in report["fixtures"])
    assert all([stage["status"] for stage in row["stages"]] == ["PASS"] * 4 for row in report["fixtures"])


def test_later_output_collision_cannot_leave_earlier_row_qualified(tmp_path):
    cases, callbacks = output_inventory(tmp_path, collide=True)
    report = shared.qualify_fixtures(cases, callbacks, scope="full")
    assert report["passed"] is False
    assert report["fixtures"][0]["passed"] is False
    assert report["fixtures"][1]["passed"] is False
    assert "final" in str(report["fixtures"][0]["problems"])
    assert "prior artifact" in str(report["fixtures"][1]["problems"])
