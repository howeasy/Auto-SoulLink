"""EXP-PC-RECEIPT: the retained single-cart PC observer evidence (DEV receipt, committed).

docs/gen3_emerald/probes/dev_2026-10-01/ holds two runs of gen3_scripted_play.lua against the
expansion reference build. The .txt/.shadow.log pair is the SECOND run (resumed from
emerald_pc_box_place, replayed verbatim in pclegs2.log); pclegs1.log text carries the FIRST run,
whose shadow tail recorded pc_deposit/pc_withdraw. This file gates the committed logs so the
evidence cannot be quietly edited: the STATUS counts, the per-kind callback addresses against the
pack's own site table, the reached-legs line, and the release-before-save frame order.

This is DEV evidence retained under docs/, NOT a qualification receipt: it is one development
machine, one unrandomized reference build, no emulator here, and the observer counts sites it
never fired. The G4 final-cut receipts (tools/gen3_final_cut.py --title exp) supersede it as the
qualification record; this test only holds the retained logs honest.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "data/games/gen3_exp/28877d73"
DEV = ROOT / "docs/gen3_emerald/probes/dev_2026-10-01"

TITLE = "emerald_expansion_28877d73"
# run 2 (the .txt/.shadow.log pair): box placement, the release pair, and the save
RUN2_KINDS = ("pc_box_place", "pc_release_begin", "pc_release", "save")
# run 1 (pclegs1.log's shadow tail): the two legs run 2 resumed past
RUN1_KINDS = ("pc_deposit", "pc_withdraw")
RUN2_LEGS = ("emerald_pc_box_place", "emerald_pc_release", "emerald_save_town")


def _expected_registered() -> set[int]:
    """The two counts a real observer can print for this pack: one hook per site (before
    05acb5ba) and one per site PLUS its mirror aliases (after). Derived from the pack, never
    hand-typed, so the RETAINED pre-mirror dev logs and any post-mirror log are both honest --
    while a value that is neither real count (a hand-edit, a stale pack) still fails."""
    sites = json.loads((PACK / "engine_signals.json").read_text(encoding="utf-8"))[
        "titles"][TITLE]["artifacts"]["clean"]["sites"].values()
    return {len(sites), sum(1 + len(s.get("mirror_offsets", [])) for s in sites)}


# ── parsing (text in, data out -- the negative controls mutate the text, not the files) ──────
def _kv(line: str) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=(\S+)", line))


def shadows(text: str) -> list[dict[str, str]]:
    r"""Every SHADOW row, in file order. _kv's \w+ split keeps `address` off `callback_address=`."""
    return [_kv(ln) for ln in text.splitlines() if ln.startswith("SHADOW ")]


def statuses(text: str) -> list[dict[str, str]]:
    return [_kv(ln) for ln in text.splitlines() if ln.startswith("STATUS ")]


def sites() -> dict[str, dict]:
    table = json.loads((PACK / "engine_signals.json").read_text(encoding="utf-8"))
    return table["titles"][TITLE]["artifacts"]["clean"]["sites"]


def callback_of(site: dict) -> int:
    """The address the observer must report for this site.

    engine_signals.json's `address` is the ANCHOR (the first byte of the capture window);
    `capture_offset` is where inside that window the on_bus_exec hook lands, and the observer
    logs that hook's address in BOTH `address=` and `callback_address=`. The two are equal to
    each other and to anchor+capture_offset -- NOT to the anchor alone (that is 4 lower here).
    """
    return site["address"] + site["capture_offset"]


# ── the assertions, as functions so a mutated text can be run through the same code ──────────
# Era-independent: the RETAINED dev logs say 22 (pre-05acb5ba), a post-mirror run says the hook
# count. Both real counts come from the pack; anything else is a tampered or stale log.
def check_status(text: str) -> None:
    rows = statuses(text)
    assert rows, "no STATUS line in the shadow log"
    counts = {row.get("registered") for row in rows}
    assert len(counts) == 1, f"STATUS rows disagree on registered: {counts}"
    assert int(counts.pop()) in _expected_registered(), \
        "registered is neither this pack's site count nor its hook count"
    for row in rows:
        assert row.get("rejected") == "0" and row.get("dropped") == "0", row
        assert row.get("failed") == "nil" and row.get("handler_error") == "nil", row


def check_callbacks(text: str, kinds, table) -> None:
    """Each kind fired at least once, address==callback_address==anchor+capture_offset."""
    rows = shadows(text)
    for kind in kinds:
        hits = [r for r in rows if r.get("kind") == kind]
        assert hits, f"{kind} never fired"
        for row in hits:
            assert row.get("address") == row.get("callback_address"), row
            assert int(row["address"]) == callback_of(table[kind]), \
                f"{kind}: logged {row['address']} != pack {callback_of(table[kind])}"


def check_release_before_save(text: str) -> None:
    rows = {r["kind"]: int(r["frame"]) for r in shadows(text)}
    assert rows["pc_release_begin"] == rows["pc_release"], \
        f"begin {rows['pc_release_begin']} and release {rows['pc_release']} are not one frame"
    assert sum(1 for r in shadows(text) if r.get("kind") == "pc_release") == 1, \
        "expected exactly one pc_release"
    assert rows["pc_release"] < rows["save"], \
        f"pc_release at {rows['pc_release']} is not before save at {rows['save']}"


def check_reached(text: str) -> None:
    line = next((ln for ln in text.splitlines() if ln.startswith("RESULT:")), None)
    assert line, "no RESULT line in the result file"
    assert line.startswith("RESULT: PASS "), line
    reached = line.split("reached:", 1)[1].split("|", 1)[0]
    assert [x.strip() for x in reached.split(",") if x.strip()] == list(RUN2_LEGS), line


# ── the committed evidence ───────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def run2_shadow() -> str:
    return (DEV / "gen3_scripted_play_emerald_result.shadow.log").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def run1_shadow() -> str:
    # pclegs1.log embeds the run-1 result text (phase/RESULT lines) AND its shadow tail; only
    # the latter carries STATUS/SHADOW rows, so prefix filtering is the whole extraction.
    return (DEV / "pclegs1.log").read_text(encoding="utf-8")


def test_run2_status_counts_register_22_and_nothing_lost(run2_shadow):
    check_status(run2_shadow)


def test_run1_status_counts_register_22_and_nothing_lost(run1_shadow):
    check_status(run1_shadow)


def test_run2_fired_every_pc_leg_kind_at_the_pack_address(run2_shadow):
    check_callbacks(run2_shadow, RUN2_KINDS, sites())


def test_run1_fired_deposit_and_withdraw_at_the_pack_address(run1_shadow):
    check_callbacks(run1_shadow, RUN1_KINDS, sites())


def test_run1_never_ran_the_release_or_save_legs(run1_shadow):
    fired = {r.get("kind") for r in shadows(run1_shadow)}
    assert not fired & {"pc_release_begin", "pc_release", "save"}, fired


def test_release_begin_and_release_share_a_frame_and_precede_the_save(run2_shadow):
    check_release_before_save(run2_shadow)


def test_result_file_passes_and_reached_exactly_the_three_legs():
    check_reached((DEV / "gen3_scripted_play_emerald_result.txt").read_text(encoding="utf-8"))


# ── (e) negative controls: the SAME assertions over a mutated text must fail ─────────────────
def _first_address_digit_bumped(text: str) -> str:
    """Bump the first SHADOW pair's address in BOTH fields.

    Both together, so address==callback_address still holds and the check that actually fails
    is the one against the pack's site table -- a control that only moved `address=` would be
    caught by the cheaper equality and would never prove the pack comparison is load-bearing.
    """
    out = text.splitlines(keepends=True)
    for i, ln in enumerate(out):
        m = re.search(r"^SHADOW .*?\baddress=(\d+)", ln)
        if m:
            n = m.group(1)
            bumped = n[:-1] + ("0" if n[-1] != "0" else "1")
            out[i] = ln.replace(f"address={n} callback_address={n}",
                                f"address={bumped} callback_address={bumped}", 1)
            return "".join(out)
    raise AssertionError("no SHADOW address to mutate")


def _frames_separated(text: str) -> str:
    """Move the pc_release row one frame later, breaking the begin/release frame-window pair."""
    out = text.splitlines(keepends=True)
    for i, ln in enumerate(out):
        if " kind=pc_release " in ln:
            out[i] = re.sub(r"frame=\d+", "frame=99999", ln, count=1)
            return "".join(out)
    raise AssertionError("no pc_release row to move")


def test_control_a_wrong_address_fails_the_callback_check(run2_shadow):
    with pytest.raises(AssertionError):
        check_callbacks(_first_address_digit_bumped(run2_shadow), RUN2_KINDS, sites())


def test_control_a_moved_release_fails_the_frame_pairing(run2_shadow):
    with pytest.raises(AssertionError):
        check_release_before_save(_frames_separated(run2_shadow))


def test_control_a_rejected_site_fails_the_status_check(run2_shadow):
    with pytest.raises(AssertionError):
        check_status(run2_shadow.replace("rejected=0", "rejected=1", 1))


def test_control_a_registered_value_that_is_neither_pack_count_fails_the_status_check(run2_shadow):
    """The era-independent gate still bites: the site count and the hook count are the ONLY
    accepted values, so a hand-edited or stale count (23) fails. EVERY row is mutated, or the
    rows-disagree check fires first and proves nothing about the count."""
    with pytest.raises(AssertionError, match="neither this pack's site count nor its hook count"):
        check_status(re.sub(r"registered=\d+", "registered=23", run2_shadow))


def test_control_rows_disagreeing_on_registered_fail_the_status_check(run2_shadow):
    out = re.sub(r"registered=22", "registered=44", run2_shadow, count=1)
    assert out != run2_shadow, "no STATUS row to mutate"
    with pytest.raises(AssertionError, match="disagree on registered"):
        check_status(out)


def test_control_a_dropped_leg_fails_the_reached_check():
    text = (DEV / "gen3_scripted_play_emerald_result.txt").read_text(encoding="utf-8")
    with pytest.raises(AssertionError):
        check_reached(text.replace("emerald_pc_release,", "", 1))


def test_control_a_failed_result_fails_the_reached_check():
    text = (DEV / "gen3_scripted_play_emerald_result.txt").read_text(encoding="utf-8")
    with pytest.raises(AssertionError):
        check_reached(text.replace("RESULT: PASS", "RESULT: FAIL", 1))
