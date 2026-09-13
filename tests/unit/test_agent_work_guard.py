import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from agent_work_guard import END, START, handle, validate  # noqa: E402
from install_agent_work_hooks import command, merge, plan  # noqa: E402


def fixture(tmp_path, **changes):
    data = {
        "schema": 1,
        "updated_at_utc": datetime.now(UTC).isoformat(),
        "coordinator_session_id": "root-id",
        "source_head": "d2b5a97",
        "live_lane": None,
        "next_action": "freeze reviewed work",
        "workers": [
            {
                "id": "w",
                "owner": "worker",
                "state": "active",
                "files": ["a.py"],
                "next_action": "test",
                "reuse_decision": "shared helper",
            }
        ],
    }
    data.update(changes)
    guide = tmp_path / "guide.md"
    guide.write_text(f"{START}\n```json\n{json.dumps(data)}\n```\n{END}\n", encoding="utf-8")
    register = tmp_path / "register.md"
    register.write_text("Current worktree claims", encoding="utf-8")
    return guide, register


def event(tmp_path, guide, register, name="Stop", session="root-id", **kwargs):
    return handle(
        {"cwd": str(tmp_path), "hook_event_name": name, "session_id": session, **kwargs},
        tmp_path,
        guide,
        register,
        tmp_path / "policy.md",
    )


def test_injection_scope_and_worker_stop(tmp_path):
    guide, register = fixture(tmp_path)
    out = event(tmp_path, guide, register, "SessionStart")
    assert "guide.md" in out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert event(tmp_path, guide, register, "UserPromptSubmit")
    assert event(tmp_path, guide, register, session="worker-id") == {}
    assert (
        handle(
            {"cwd": str(tmp_path.parent), "hook_event_name": "Stop", "session_id": "root-id"},
            tmp_path,
            guide,
            register,
            tmp_path / "policy",
        )
        == {}
    )


def test_missing_stale_duplicate_and_bounded_retry(tmp_path):
    guide, register = fixture(
        tmp_path,
        workers=[
            {
                "id": "a",
                "owner": "one",
                "state": "active",
                "files": ["A.py"],
                "next_action": "x",
                "reuse_decision": "shared",
            },
            {
                "id": "b",
                "owner": "two",
                "state": "active",
                "files": ["a.py"],
                "next_action": "y",
                "reuse_decision": "specific",
            },
        ],
        updated_at_utc=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    )
    issues = validate(guide, register)
    assert any("stale" in issue for issue in issues)
    assert any("overlaps" in issue for issue in issues)
    assert event(tmp_path, guide, register)["decision"] == "block"
    assert (
        "Stop retry exhausted"
        in event(tmp_path, guide, register, stop_hook_active=True)["systemMessage"]
    )
    guide.write_text("missing", encoding="utf-8")
    assert "unreadable" in validate(guide, register)[0]
    assert event(tmp_path, guide, register)["decision"] == "block"
    assert (
        "retry exhausted"
        in event(tmp_path, guide, register, stop_hook_active=True)["systemMessage"]
    )
    guide.write_text(f"{START}\n```json\n[]\n```\n{END}", encoding="utf-8")
    assert "JSON must be an object" in event(tmp_path, guide, register)["reason"]


def test_noncanonical_claims_and_full_session_policy(tmp_path):
    guide, register = fixture(
        tmp_path,
        workers=[
            {
                "id": "a",
                "owner": "one",
                "state": "active",
                "files": ["a/../x.py"],
                "next_action": "x",
                "reuse_decision": "shared",
            },
            {
                "id": "b",
                "owner": "two",
                "state": "active",
                "files": ["/absolute.py"],
                "next_action": "y",
                "reuse_decision": "specific",
            },
        ],
    )
    assert sum("noncanonical" in issue for issue in validate(guide, register)) == 2
    policy = tmp_path / "policy.md"
    policy.write_text("Actual short policy text", encoding="utf-8")
    out = event(tmp_path, guide, register, "SessionStart")
    assert "Actual short policy text" in out["hookSpecificOutput"]["additionalContext"]


def test_malformed_nested_worker_fields_are_bounded(tmp_path):
    guide, register = fixture(
        tmp_path,
        workers=[
            {
                "id": ["invalid"],
                "owner": "worker",
                "state": {"active": True},
                "files": ["a.py"],
                "next_action": "x",
                "reuse_decision": "shared",
            },
        ],
    )
    first = event(tmp_path, guide, register)
    assert first["decision"] == "block"
    assert "state invalid" in first["reason"] and "id missing" in first["reason"]
    second = event(tmp_path, guide, register, stop_hook_active=True)
    assert "Stop retry exhausted" in second["systemMessage"]


def test_pause_and_handoff(tmp_path):
    frozen = {
        "id": "w",
        "owner": "worker",
        "state": "frozen",
        "files": ["a.py"],
        "next_action": "await review",
        "reuse_decision": "shared",
    }
    guide, register = fixture(
        tmp_path,
        workers=[frozen],
        paused_by_owner=True,
        pause_reason="owner requested pause",
        updated_at_utc=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
    )
    assert event(tmp_path, guide, register) == {}
    guide, register = fixture(
        tmp_path, workers=[dict(frozen, state="blocked", blocked_reason="prerequisite")]
    )
    assert event(tmp_path, guide, register) == {}
    guide, register = fixture(
        tmp_path,
        workers=[
            dict(frozen, state="done", receipt="receipt.md", independent_review_refs=["review.md"])
        ],
    )
    assert event(tmp_path, guide, register) == {}
    guide, register = fixture(tmp_path, workers=[dict(frozen, state="done")])
    assert "completion receipt" in event(tmp_path, guide, register)["reason"]


def test_installer_preserves_other_handlers_and_idempotent(tmp_path):
    path = tmp_path / "hooks.json"
    original = {
        "notify": "keep",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "existing"}]}]},
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    sample = 'python.exe "agent_work_guard.py" "--hook-id" "slink-agent-work-v1"'
    before, after = plan(path, sample)
    assert before == original and json.loads(path.read_text()) == original
    assert after["hooks"]["Stop"][0] == original["hooks"]["Stop"][0]
    assert after["notify"] == "keep"
    assert merge(after, sample) == after
    cmd = command(
        Path("python.exe"),
        Path("agent_work_guard.py"),
        tmp_path,
        tmp_path / "guide",
        tmp_path / "register",
        tmp_path / "policy",
    )
    assert '"agent_work_guard.py"' in cmd and '"--scope-root"' in cmd
    assert cmd.startswith("python.exe ") and '"slink-agent-work-v1"' in cmd
    upgraded = merge(after, cmd)
    assert len(upgraded["hooks"]["Stop"]) == 2
    assert upgraded["hooks"]["Stop"][0] == original["hooks"]["Stop"][0]
    assert merge(upgraded, cmd) == upgraded
    unrelated = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": 'echo "agent_work_guard.py" "--hook-id" "slink-agent-work-v1"',
                        },
                        {
                            "type": "command",
                            "command": 'python.exe "C:/Other/agent_work_guard.py" "--hook-id" "slink-agent-work-v1"',
                        },
                        {
                            "type": "command",
                            "command": 'python.exe "agent_work_guard.py" "--hook-id" "different-marker"',
                        },
                        {
                            "type": "command",
                            "command": 'C:/New/Python/python.exe "agent_work_guard.py" "--hook-id" "slink-agent-work-v1"',
                        },
                    ]
                }
            ]
        }
    }
    changed = merge(unrelated, cmd)
    assert len(changed["hooks"]["Stop"]) == 2
    assert len(changed["hooks"]["Stop"][0]["hooks"]) == 3
    assert merge(changed, cmd) == changed
