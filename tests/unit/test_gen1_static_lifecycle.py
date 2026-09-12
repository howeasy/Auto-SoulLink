"""One live static origin per player: consumed once by its own battle's capture, else invalidated.

Origins come from real `validate` facts, captures from real `decode_capture` facts (call frame
100, return 160), battle ends from real `validate_end` facts. Every sequence is synthetic; no
emulator ran. Facts are applied in list order, as root supplies them.
"""

import copy

import pytest

from server import event_reference
from server.gen1_static_lifecycle import (
    COMPONENT,
    HOLD,
    close,
    consume,
    new_row,
    open,
    record_key,
    stage,
    verify_state,
)
from server.protocol_journal import JournalError
from tests.unit.test_gen1_static_receipt import capture_fact, check, check_end, end_receipt, receipt

SNORLAX, ZAPDOS, VOLTORB = "static:route12_snorlax", "static:powerplant_zapdos", "static:powerplant_voltorb1"
FRAME = {"a": event_reference.make("a", "1" * 32, {"event": "observation", "acquisitions": []}),
         "b": event_reference.make("b", "2" * 32, {"event": "observation", "acquisitions": []})}


def ref(index=0, player="a"):
    return {"event": FRAME[player], "index": index}


def origin(variant, source, began=20):
    return check(receipt(variant, source, arm_frame=began - 1, began_frame=began), variant)


def ended(variant, source, frame, result=0):
    return check_end(end_receipt(variant, source, frame=frame, battle_result=result), variant)


def caught(variant, source, key=None, **over):
    fact = capture_fact(variant, source, **over)
    if key is not None:
        fact["key"] = key
    return fact


def rows(*items):
    return [{"kind": fact["kind"], "fact": fact, "source_ref": ref(index)} for index, fact in enumerate(items)]


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_an_origin_is_consumed_exactly_once(variant):
    row = new_row()
    assert open(row, origin(variant, SNORLAX), ref(0)) == SNORLAX
    first = caught(variant, SNORLAX)
    assert consume(row, first, ref(1), variant=variant) == SNORLAX
    assert row["attributions"] == {first["key"]: SNORLAX} and row["origins"][0]["state"] == "consumed"
    assert row["origins"][0]["capture"] == {"source_ref": ref(1), "key": first["key"], "call_frame": 100}
    # The same species/level/map caught again later (a wild one): the static is spent.
    later = caught(variant, SNORLAX, key="0001:2222:84")
    later["call_frame"], later["return_frame"] = 5000, 5060
    assert consume(row, later, ref(2), variant=variant) is None
    assert row["attributions"] == {first["key"]: SNORLAX}
    # The battle end after a consumed capture changes nothing (nothing is live).
    assert close(row, ended(variant, SNORLAX, 400, result=2), ref(3)) is None
    verify_state({"a": row})
    with pytest.raises(JournalError, match="already attributed"):
        consume(row, first, ref(4), variant=variant)


@pytest.mark.parametrize("result,label", [(2, "flee"), (0, "ko"), (1, "loss")])
def test_a_battle_that_ends_without_a_capture_invalidates_its_origin(result, label):
    row = new_row()
    open(row, origin("red", ZAPDOS), ref(0))
    assert close(row, ended("red", ZAPDOS, 50, result=result), ref(1)) == ZAPDOS
    assert row["origins"][0]["state"] == "ended" and row["origins"][0]["end"] == {"source_ref": ref(1), "frame": 50, "battle_result": result}
    # A later wild capture of the same species/level on the same map (call frame 100 > end frame 50) is nobody's static.
    assert consume(row, caught("red", ZAPDOS), ref(2), variant="red") is None
    assert row["attributions"] == {} and row["origins"][0]["state"] == "ended"
    verify_state({"a": row})


def test_a_ball_that_breaks_free_leaves_no_fact_so_the_origin_stays_live():
    # Source: `.returnAfterUsingItem_NoCapture` returns to the battle loop with carry clear; EndOfBattle is not reached,
    # the observer publishes nothing, and the eventual capture (many turns later) still consumes.
    row = new_row()
    open(row, origin("yellow", VOLTORB), ref(0))
    late = caught("yellow", VOLTORB)
    late["call_frame"], late["return_frame"] = 9000, 9060
    assert consume(row, late, ref(1), variant="yellow") == VOLTORB


def test_the_end_may_be_listed_before_the_capture_of_the_same_bundle():
    row = new_row()
    open(row, origin("blue", SNORLAX), ref(0))
    close(row, ended("blue", SNORLAX, 300, result=2), ref(1))  # caught: the engine writes $02 for a capture too
    assert consume(row, caught("blue", SNORLAX), ref(2), variant="blue") == SNORLAX  # call frame 100 <= end frame 300
    assert row["origins"][0]["state"] == "consumed" and row["origins"][0]["end"]["frame"] == 300
    verify_state({"a": row})
    # ...but a capture called after the end frame belongs to another battle.
    row = new_row()
    open(row, origin("blue", SNORLAX), ref(0))
    close(row, ended("blue", SNORLAX, 99, result=2), ref(1))
    assert consume(row, caught("blue", SNORLAX), ref(2), variant="blue") is None


def test_a_capture_listed_before_its_origin_is_not_attributed():
    # Order is root's; nothing is buffered or re-sorted.
    staged = stage(new_row(), "a", rows(caught("red", SNORLAX), origin("red", SNORLAX)), FRAME["a"], variant="red")
    assert staged["attributions"] == {} and staged["records"][0]["value"]["origins"][0]["state"] == "live"


def test_re_arming_after_a_close_opens_a_new_origin():
    row = new_row()
    open(row, origin("red", VOLTORB, began=20), ref(0))
    close(row, ended("red", VOLTORB, 50, result=2), ref(1))
    open(row, origin("red", VOLTORB, began=80), ref(2))  # the site re-armed after an unobserved-outcome battle
    assert [o["state"] for o in row["origins"]] == ["ended", "live"]
    assert consume(row, caught("red", VOLTORB), ref(3), variant="red") == VOLTORB
    assert [o["state"] for o in row["origins"]] == ["ended", "consumed"]
    verify_state({"a": row})


def test_a_second_open_while_live_supersedes_the_first_and_never_attributes_to_it():
    row = new_row()
    open(row, origin("yellow", ZAPDOS, began=20), ref(0))
    open(row, origin("yellow", SNORLAX, began=120), ref(1))  # the first battle ended unobserved (reset/state load)
    assert [o["state"] for o in row["origins"]] == ["superseded", "live"]
    assert row["origins"][0]["superseded_by"] == ref(1)
    zapdos = caught("yellow", ZAPDOS)  # call frame 100: inside the superseded battle's window
    assert consume(row, zapdos, ref(2), variant="yellow") is None
    snorlax = caught("yellow", SNORLAX)  # call frame 100 < began 120: Snorlax's operands, but not provably this battle
    assert consume(row, snorlax, ref(3), variant="yellow") == HOLD
    assert row["held"] == [{"kind": "capture", "fact": snorlax, "source_ref": ref(3)}] and row["attributions"] == {}
    with pytest.raises(JournalError, match="already attributed"):
        consume(row, snorlax, ref(3), variant="yellow")
    later = caught("yellow", SNORLAX, key="0001:2222:84")
    later["call_frame"], later["return_frame"] = 130, 190
    assert consume(row, later, ref(4), variant="yellow") == SNORLAX
    verify_state({"a": row})


def test_a_capture_two_eligible_origins_both_join_is_held_not_guessed():
    row = new_row()
    open(row, origin("red", VOLTORB, began=20), ref(0))
    close(row, ended("red", VOLTORB, 150, result=2), ref(1))  # end frame 150 >= the capture call at 100
    open(row, origin("red", VOLTORB, began=90), ref(2))  # inconsistent frames: a second origin that also joins
    assert consume(row, caught("red", VOLTORB), ref(3), variant="red") == HOLD
    assert [o["state"] for o in row["origins"]] == ["ended", "live"] and row["attributions"] == {}
    verify_state({"a": row})
    with pytest.raises(JournalError, match="invalid held static capture"):
        verify_state({"a": row | {"held": row["held"] + row["held"]}})


def test_yellow_pair_consumes_the_same_static_id_independently():
    document = {"components": {"gen1-initial-observations": {
        player: {"metadata": {"gen1_metadata": {"cartridge": {"variant": "yellow"}}}} for player in "ab"}}}
    for player in "ab":
        facts = [{"kind": fact["kind"], "fact": fact, "source_ref": ref(index, player)}
                 for index, fact in enumerate([origin("yellow", ZAPDOS), caught("yellow", ZAPDOS), ended("yellow", ZAPDOS, 300, result=2)])]
        staged = stage(document, player, facts, FRAME[player])
        assert staged["attributions"] == {"ABCD:1234:4B": ZAPDOS}
        assert staged["records"] == [{"namespace": COMPONENT, "key": record_key(player), "value": document["components"][COMPONENT][player]}]
    component = document["components"][COMPONENT]
    assert set(component) == {"a", "b"} and all(component[p]["origins"][0]["state"] == "consumed" for p in "ab")
    assert component["a"]["origins"][0]["source_ref"]["event"]["player"] == "a" and component["b"]["origins"][0]["source_ref"]["event"]["player"] == "b"
    verify_state(component)


def test_stage_applies_in_list_order_and_returns_the_detached_record():
    row = new_row()
    facts = rows(origin("red", SNORLAX), ended("red", SNORLAX, 300, result=2), caught("red", SNORLAX))
    facts.insert(1, {"kind": "grant", "fact": {"kind": "scripted_grant"}, "source_ref": ref(9)})  # root's whole acquisition list
    staged = stage(row, "a", facts, FRAME["a"], variant="red")
    assert staged["attributions"] == {"ABCD:1234:84": SNORLAX}
    assert staged["records"][0]["value"] == row and staged["records"][0]["value"] is not row
    with pytest.raises(JournalError, match="unknown static lifecycle fact kind"):
        stage(new_row(), "a", [{"kind": "trade", "fact": {}, "source_ref": ref(0)}], FRAME["a"], variant="red")
    with pytest.raises(JournalError, match="not a row of this frame"):
        stage(new_row(), "a", [{"kind": "static_origin", "fact": origin("red", SNORLAX), "source_ref": ref(0, "b")}], FRAME["a"], variant="red")
    with pytest.raises(JournalError, match="another player"):
        stage(new_row(), "b", [], FRAME["a"], variant="red")
    with pytest.raises(JournalError, match="variant required"):
        stage(new_row(), "a", [], FRAME["a"], variant="gold")
    with pytest.raises(JournalError, match="source row"):
        open(new_row(), origin("red", SNORLAX), {"event": FRAME["a"]})


def test_lifecycle_refuses_malformed_facts():
    row = new_row()
    with pytest.raises(JournalError, match="origin fact required"):
        open(row, caught("red", SNORLAX), ref(0))
    with pytest.raises(JournalError, match="origin fact required"):
        open(row, origin("red", SNORLAX) | {"static_id": "static:mew"}, ref(0))
    with pytest.raises(JournalError, match="capture fact required"):
        consume(row, origin("red", SNORLAX), ref(0), variant="red")
    with pytest.raises(JournalError, match="battle end fact required"):
        close(row, caught("red", SNORLAX), ref(0))
    with pytest.raises(JournalError, match="battle end fact required"):
        close(row, ended("red", SNORLAX, 50) | {"battle_result": 3}, ref(0))
    assert row == new_row()


def healthy():
    row = new_row()
    open(row, origin("red", SNORLAX), ref(0))
    consume(row, caught("red", SNORLAX), ref(1), variant="red")
    open(row, origin("red", ZAPDOS, began=200), ref(2))
    close(row, ended("red", ZAPDOS, 250), ref(3))
    open(row, origin("red", VOLTORB, began=300), ref(4))
    verify_state({"a": row})
    return row


@pytest.mark.parametrize(
    "fault",
    ["two_live", "consumed_without_source_ref", "consumed_without_capture", "attribution_never_opened", "attribution_missing",
     "foreign_source", "unknown_static", "capture_before_began", "capture_after_end", "superseded_marker", "extra_player",
     "bad_result", "row_shape", "state_name"],
)
def test_verify_state_catches_corrupted_rows(fault):
    row = healthy()
    match = None
    if fault == "two_live":
        row["origins"][1]["state"], row["origins"][1]["end"], match = "live", None, "more than one live"
    elif fault == "consumed_without_source_ref":
        del row["origins"][0]["capture"]["source_ref"]
        match = "not inside its battle"
    elif fault == "consumed_without_capture":
        row["origins"][0]["capture"], match = None, "resolution differs"
    elif fault == "attribution_never_opened":
        row["attributions"]["FFFF:0000:84"], match = "static:route16_snorlax", "attributions differ"
    elif fault == "attribution_missing":
        row["attributions"], match = {}, "attributions differ"
    elif fault == "foreign_source":
        row["origins"][2]["source_ref"], match = ref(0, "b"), "another player"
    elif fault == "unknown_static":
        row["origins"][2]["static_id"] = row["origins"][2]["fact"]["static_id"] = "static:mew"
        match = "differs from its fact"
    elif fault == "capture_before_began":
        row["origins"][0]["capture"]["call_frame"], match = 19, "not inside its battle"
    elif fault == "capture_after_end":
        row["origins"][0]["end"] = {"source_ref": ref(7), "frame": 99, "battle_result": 2}
        match = "not inside its battle"
    elif fault == "superseded_marker":
        row["origins"][2]["superseded_by"], match = ref(8), "resolution differs"
    elif fault == "extra_player":
        with pytest.raises(JournalError, match="invalid static origin component"):
            verify_state({"a": row, "c": new_row()})
        return
    elif fault == "bad_result":
        row["origins"][1]["end"]["battle_result"], match = 3, "invalid static battle end"
    elif fault == "row_shape":
        row["live"], match = None, "invalid static origin row"
    else:
        row["origins"][2]["state"], match = "open", "invalid static origin record"
    with pytest.raises(JournalError, match=match):
        verify_state({"a": row})


def test_verify_state_accepts_restored_copies_and_empty_rows():
    row = healthy()
    verify_state({"a": copy.deepcopy(row), "b": new_row()})
    verify_state({})
