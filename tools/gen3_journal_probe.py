"""Harness-only RR trade journal contention probe on one private install root."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


def journal_snapshot(root: Path) -> dict:
    from gen3_trade_duo import journal_state

    return journal_state((root / "slink_gen3_trade.log").read_bytes(),
                         (root / "slink_gen3_trade.guard").read_bytes())


def _private_root(run) -> Path:
    from e2e_duo import REPO

    root = Path(REPO).resolve()
    named = os.environ.get("SLINK_JOURNAL_PROBE_ROOT")
    state = os.environ.get("SLINK_STATE_DIR")
    if not named or Path(named).resolve() != root or not state or Path(state).resolve() == root:
        raise RuntimeError("journal probe needs an exact private SLINK_JOURNAL_PROBE_ROOT and SLINK_STATE_DIR")
    if run.game != "gen3_rr":
        raise RuntimeError("journal probe only runs on the RR companion pair")
    return root


def orchestrate(run) -> None:
    root = _private_root(run)
    shell = shutil.which("pwsh")
    if not shell:
        raise RuntimeError("journal probe needs PowerShell 7 for the external OS guard")
    run._gen3_prelude(link_slot=1)
    before = None

    def genesis_ready():
        nonlocal before
        try:
            before = journal_snapshot(root)
        except (OSError, ValueError):  # a client may own the guard for this frame
            return False
        if before["records"]:
            raise RuntimeError("journal probe root has an unsettled trade intent")
        return True

    run.wait_for("private sealed journal genesis", genesis_ready, 60)
    run._journal_probe_before_counter = before["counter"]
    run._journal_probe_root = root
    run._pydec_note(f"JOURNAL_PROBE_ROOT root={root} guard={root / 'slink_gen3_trade.guard'} "
                    f"counter_before={before['counter']}")
    ka, kb = run._link_keys["a"], run._link_keys["b"]
    lines = run._gen3_linked_lines()
    lines["a"].append(f"PARTNER {kb}")
    lines["b"].append(f"PARTNER {ka}")
    run.go(lines)
    for inst in "ab":
        run._gen3_mark(inst, rf"^JOURNAL_PROBE_ARMED player={inst} frame=\d+$", "probe armed", 120)

    held = Path(run.data_dir) / "journal_guard_held.txt"
    release = Path(run.data_dir) / "journal_guard_release.txt"
    helper = subprocess.Popen(
        [shell, "-NoProfile", "-File", str(root / "tools/gen3_journal_lock_holder.ps1"),
         "-Root", str(root), "-HeldMarker", str(held), "-ReleaseMarker", str(release)],
        cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        run.wait_for("owned OS guard acquired", lambda: held.exists() or helper.poll() is not None, 60)
        if not held.exists() or helper.poll() is not None:
            output, _ = helper.communicate(timeout=5)
            raise RuntimeError("external OS guard helper exited before the hold: " + output)
        run._pydec_note(held.read_text(encoding="utf-8").strip())
        for inst in "ab":
            run._append_reconnect_marker(inst, "LOCK_HELD")
        for inst in "ab":
            run._gen3_mark(inst, rf"^JOURNAL_PROBE_HIDDEN player={inst} frame=\d+$",
                           "production hidden tick under OS guard", 120)

        def server_hidden(want):
            status = run._status() or {}
            players = status.get("players") or {}
            return all((players.get(inst, {}).get("trade_recovery") or {}).get("hidden") is want
                       for inst in "ab")

        run.wait_for("server sees both hidden parties under OS guard", lambda: server_hidden(True), 60)
        run._pydec_note("JOURNAL_PROBE_SERVER_HIDDEN both=true")
        release.write_text("release\n", encoding="utf-8")
        output, _ = helper.communicate(timeout=30)
        if helper.returncode != 0 or "LOCK_RELEASED pid=" not in output:
            raise RuntimeError("external OS guard did not close cleanly: " + output)
        run._pydec_note(output.strip())
        for inst in "ab":
            run._append_reconnect_marker(inst, "LOCK_RELEASED")
        for inst in "ab":
            run._gen3_mark(inst, rf"^JOURNAL_PROBE_RECOVERED player={inst} frame=\d+ party=[1-6]$",
                           "same-session visible tick after guard release", 120)
        run.wait_for("server sees both visible parties after release", lambda: server_hidden(False), 60)
        run._pydec_note("JOURNAL_PROBE_SERVER_RECOVERED both=true")
        for inst in "ab":
            run._append_reconnect_marker(inst, "TRADE_GO")
        run._gen3_mark("a", rf"^TRADED gave={re.escape(ka)} got={re.escape(kb)} ", "A traded")
        run._gen3_mark("b", rf"^TRADED gave={re.escape(kb)} got={re.escape(ka)} ", "B traded")

        def rekeyed():
            return any((e.get("a") or {}).get("key") == kb and (e.get("b") or {}).get("key") == ka
                       for e in run._links_json())

        run.wait_for("links.json re-keyed by the native commit", rekeyed, 120)

        def retired():
            try:
                state = journal_snapshot(root)
            except (OSError, ValueError):
                return False
            if state["records"] or state["counter"] != before["counter"] + 2:
                return False
            run._journal_probe_final_state = state
            return True

        run.wait_for("sealed journal terminal retirement for both players", retired, 120)
        run._pydec_note(f"JOURNAL_PROBE_RETIRED counter={before['counter']}->"
                        f"{run._journal_probe_final_state['counter']} records=0")
        for inst in "ab":
            run._append_reconnect_marker(inst, "SAVE")
    finally:
        if helper.poll() is None:
            release.write_text("release\n", encoding="utf-8")
            try:
                helper.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                helper.kill()  # only this probe's child; closing its handle releases the guard
                helper.communicate(timeout=5)


def saved_oracle(run, results) -> None:
    from e2e_duo import gen3_codec, gen3_codec_title

    for inst in "ab":
        text = results[inst]
        markers = ("JOURNAL_PROBE_ARMED", "JOURNAL_PROBE_HIDDEN", "JOURNAL_PROBE_RECOVERED", "TRADED")
        offsets = [text.find(marker) for marker in markers]
        if any(at < 0 for at in offsets) or offsets != sorted(offsets):
            raise RuntimeError(f"{inst}: probe did not witness ordered hidden/recovered/native trade")
    state = journal_snapshot(run._journal_probe_root)
    if state["records"] or state["counter"] != run._journal_probe_before_counter + 2:
        raise RuntimeError("sealed journal did not retain both terminal retirements after emulator exit")
    run.assert_trade_gen3_saved(results)  # independent flash parties, records, and server link re-key
    codec = gen3_codec()
    for inst in "ab":
        fixture, _ = codec.split_rtc(run._gen3_fixture_bytes(inst))
        flushed, _ = codec.split_rtc(run._gen3_flushed(inst))
        title = gen3_codec_title(run._gen3_title(inst))
        before = codec.parse_flash(fixture, cfru=True, title=title)["counter"]
        after = codec.parse_flash(flushed, cfru=True, title=title)["counter"]
        if after != before + 3:  # native pre-save, native post-save, ordinary runner SAVE
            raise RuntimeError(f"{inst}: independent saved flash counter {before}->{after}, expected +3")
        run._pydec_note(f"JOURNAL_PROBE_SAVE inst={inst} counter={before}->{after} delta=3")
