"""Polled readers see only complete writes (OMP review cx-aa9c1052 of the 0.2 s poll, 157e1ef7)."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import e2e_duo as duo  # noqa: E402


def test_a_receipt_line_still_being_written_is_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(duo, "BUILD", str(tmp_path))
    path = tmp_path / "e2e_torn_a_result.txt"
    path.write_text("MYKEY 0 ABCD", encoding="utf-8")
    assert duo.extract_keys(duo.read_result("torn", "a")) == {}
    path.write_text("MYKEY 0 ABCD1234:5678\nBALL_FACT {\"a\"", encoding="utf-8")
    text = duo.read_result("torn", "a")
    assert duo.extract_keys(text) == {0: "ABCD1234:5678"}
    assert "BALL_FACT" not in text


def test_events_json_mid_rewrite_is_retried(tmp_path):
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.data_dir = str(tmp_path)
    path = tmp_path / "events.json"
    path.write_text("[{\"event\": \"hel", encoding="utf-8")

    def finish():
        time.sleep(0.2)
        path.write_text(json.dumps([{"event": "hello"}]), encoding="utf-8")

    threading.Thread(target=finish).start()
    assert run._reconnect_events() == [{"event": "hello"}]
