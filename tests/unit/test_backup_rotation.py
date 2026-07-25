"""Rolling backup rotation — the last line of defence when live state gets corrupted.

`server/backup.py` had no tests, and the dashboard's rollback button restores from these slots,
so an off-by-one in the rotation silently costs the user their most recent good state.
"""
import asyncio
import json
import os

import pytest

from server.backup import backup_loop, do_backup


def _links(tmp_path, marker):
    p = tmp_path / "links.json"
    p.write_text(json.dumps({"marker": marker}))
    return str(p)


def _slot(tmp_path, stem, n):
    return tmp_path / "backups" / f"{stem}.backup.{n}.json"


def test_first_backup_lands_in_slot_1(tmp_path):
    do_backup(_links(tmp_path, "a"), str(tmp_path / "events.json"), 6)
    assert json.loads(_slot(tmp_path, "links", 1).read_text())["marker"] == "a"


def test_newest_is_slot_1_and_older_shift_up(tmp_path):
    for marker in ("a", "b", "c"):
        do_backup(_links(tmp_path, marker), str(tmp_path / "events.json"), 6)
    assert json.loads(_slot(tmp_path, "links", 1).read_text())["marker"] == "c"
    assert json.loads(_slot(tmp_path, "links", 2).read_text())["marker"] == "b"
    assert json.loads(_slot(tmp_path, "links", 3).read_text())["marker"] == "a"


def test_rotation_stops_at_max_slots_and_drops_the_oldest(tmp_path):
    markers = [str(i) for i in range(9)]
    for m in markers:
        do_backup(_links(tmp_path, m), str(tmp_path / "events.json"), 6)
    kept = sorted(os.listdir(tmp_path / "backups"))
    assert kept == [f"links.backup.{i}.json" for i in range(1, 7)]
    # slot 1 = newest, slot 6 = the 6th most recent; anything older is gone
    for i in range(1, 7):
        assert json.loads(_slot(tmp_path, "links", i).read_text())["marker"] == markers[-i]


def test_events_json_is_backed_up_alongside_links(tmp_path):
    ev = tmp_path / "events.json"
    ev.write_text('[{"e": 1}]')
    do_backup(_links(tmp_path, "a"), str(ev), 6)
    assert _slot(tmp_path, "events", 1).exists()


def test_missing_events_json_is_not_fatal(tmp_path):
    do_backup(_links(tmp_path, "a"), str(tmp_path / "nope.json"), 6)
    assert _slot(tmp_path, "links", 1).exists()
    assert not _slot(tmp_path, "events", 1).exists()


def test_missing_links_json_is_a_no_op(tmp_path):
    do_backup(str(tmp_path / "nope.json"), str(tmp_path / "events.json"), 6)
    assert not (tmp_path / "backups").exists()


@pytest.mark.asyncio
async def test_loop_skips_backups_while_inactive(tmp_path):
    task = asyncio.create_task(backup_loop(
        _links(tmp_path, "a"), str(tmp_path / "events.json"),
        max_slots=6, interval_s=0, is_active=lambda: False))
    await asyncio.sleep(0.05)
    task.cancel()
    await task
    assert not (tmp_path / "backups").exists()


@pytest.mark.asyncio
async def test_loop_survives_a_failing_cycle(tmp_path):
    """One bad write must not kill the loop — it runs for the whole session."""
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return True

    task = asyncio.create_task(backup_loop(
        _links(tmp_path, "a"), str(tmp_path / "events.json"),
        max_slots=6, interval_s=0, is_active=flaky))
    await asyncio.sleep(0.05)
    still_running = not task.done()
    task.cancel()
    await task
    assert still_running, "backup_loop died on an is_active() exception"
