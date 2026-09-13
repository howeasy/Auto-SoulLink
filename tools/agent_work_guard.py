"""Read-only, scoped lifecycle reminder and mechanical checkpoint check."""

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

START = "<!-- AGENT_CHECKPOINT_START -->"
END = "<!-- AGENT_CHECKPOINT_END -->"
STATES = {"active", "ready", "frozen", "blocked", "done"}


def _within(path, root):
    return path == root or root in path.parents


def _read_checkpoint(guide):
    body = guide.read_text(encoding="utf-8")
    matches = re.findall(
        re.escape(START) + r"\s*```json\s*(.*?)\s*```\s*" + re.escape(END), body, re.S
    )
    if len(matches) != 1 or body.count(START) != 1 or body.count(END) != 1:
        raise ValueError("guide must contain exactly one fenced JSON checkpoint")
    data = json.loads(matches[0])
    if not isinstance(data, dict):
        raise ValueError("checkpoint JSON must be an object")
    return data


def validate(guide, register, now=None):
    """Return mechanical issues; never update either ledger."""
    issues = []
    now = now or datetime.now(UTC)
    try:
        data = _read_checkpoint(guide)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"checkpoint unreadable: {exc}"]
    if data.get("schema") != 1:
        issues.append("checkpoint schema must be 1")
    paused = data.get("paused_by_owner") is True
    try:
        updated = datetime.fromisoformat(data["updated_at_utc"])
        if updated.tzinfo is None or (
            not paused and not -timedelta(minutes=1) <= now - updated <= timedelta(minutes=15)
        ):
            issues.append("checkpoint timestamp is stale or invalid")
    except (KeyError, TypeError, ValueError):
        issues.append("checkpoint timestamp is missing or invalid")
        updated = None
    for field in ("coordinator_session_id", "source_head", "next_action"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            issues.append(f"checkpoint {field} missing")
    if isinstance(data.get("source_head"), str) and not re.fullmatch(
        r"[0-9a-fA-F]{7,40}", data["source_head"]
    ):
        issues.append("checkpoint source_head must be a Git hex prefix")
    if "live_lane" not in data:
        issues.append("checkpoint live_lane missing")
    if paused and data.get("live_lane") is not None:
        issues.append("owner pause requires null live_lane")
    try:
        stat = register.stat()
        if (
            not paused
            and updated is not None
            and datetime.fromtimestamp(stat.st_mtime, UTC) + timedelta(minutes=1) < updated
        ):
            issues.append("worktree register predates checkpoint")
    except OSError:
        issues.append("worktree register missing")
    workers = data.get("workers")
    if not isinstance(workers, list):
        return issues + ["checkpoint workers must be an array"]
    claims = {}
    if paused and (
        not isinstance(data.get("pause_reason"), str) or not data["pause_reason"].strip()
    ):
        issues.append("owner pause reason missing")
    ids = set()
    for index, worker in enumerate(workers):
        if not isinstance(worker, dict):
            issues.append(f"worker {index} invalid")
            continue
        label = (
            worker.get("id") if isinstance(worker.get("id"), str) and worker["id"] else str(index)
        )
        for field in ("id", "owner", "state", "next_action", "reuse_decision"):
            if not isinstance(worker.get(field), str) or not worker[field].strip():
                issues.append(f"worker {label} {field} missing")
        if label in ids:
            issues.append(f"duplicate worker id {label}")
        ids.add(label)
        state = worker.get("state")
        if paused and state == "active":
            issues.append(f"worker {label} still active during owner pause")
        if not isinstance(state, str) or state not in STATES:
            issues.append(f"worker {label} state invalid")
        files = worker.get("files")
        if (
            not isinstance(files, list)
            or not files
            or any(not isinstance(f, str) or not f.strip() for f in files)
        ):
            issues.append(f"worker {label} files missing/invalid")
            continue
        if state == "active":
            for file in files:
                key = file.replace("\\", "/").casefold()
                if (
                    key.startswith("/")
                    or re.match(r"^[a-z]:", key)
                    or any(part in ("", ".", "..") for part in key.split("/"))
                ):
                    issues.append(f"worker {label} noncanonical file claim: {file}")
                    continue
                if key in claims:
                    issues.append(f"active file claim overlaps: {file} ({claims[key]}, {label})")
                claims[key] = label
        if state == "blocked" and (
            not isinstance(worker.get("blocked_reason"), str)
            or not worker["blocked_reason"].strip()
        ):
            issues.append(f"worker {label} blocked_reason missing")
        if state == "done" and (
            not isinstance(worker.get("receipt"), str)
            or not worker["receipt"].strip()
            or not isinstance(worker.get("independent_review_refs"), list)
            or not worker["independent_review_refs"]
        ):
            issues.append(f"worker {label} completion receipt/review missing")
    return issues


def handle(payload, scope_root, guide, register, policy):
    event = payload.get("hook_event_name")
    cwd = Path(payload.get("cwd") or ".").resolve()
    if not _within(cwd, scope_root.resolve()):
        return {}
    if event in ("SessionStart", "UserPromptSubmit"):
        pointer = f"SLink orchestration: read {policy}; refresh sole checkpoint in {guide} and worktree register {register}. Claim exact exclusive files and acknowledge dispatch. Keep shared lifecycle/transport/state/presentation in shared modules; game adapters own game facts. Record evidence, next action, reuse decision and independent review. Workers report to coordinator; coordinator alone updates guide."
        if event == "SessionStart":
            try:
                policy_text = policy.read_text(encoding="utf-8")
                pointer += "\nCurrent short policy:\n" + policy_text[:3500]
            except OSError:
                pointer += "\nPolicy file unreadable; report this to coordinator."
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": pointer}}
    if event != "Stop":
        return {}
    try:
        checkpoint = _read_checkpoint(guide)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        checkpoint = None
        issues = [f"checkpoint unreadable: {exc}"]
    else:
        issues = validate(guide, register)
    # Codex child hook input carries the parent session id. Only Stop is registered,
    # not SubagentStop; workers are not held for a coordinator guide update.
    if checkpoint is not None and payload.get("session_id") != checkpoint.get(
        "coordinator_session_id"
    ):
        return {}
    if checkpoint is not None and checkpoint.get("paused_by_owner") is True and not issues:
        return {}
    if not issues:
        return {}
    reason = "SLink checkpoint needs coordinator repair: " + "; ".join(issues)
    if payload.get("stop_hook_active"):
        return {"systemMessage": reason + ". Stop retry exhausted; report this failure visibly."}
    return {"decision": "block", "reason": reason}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hook-id", default="slink-agent-work-v1")
    for name in ("scope-root", "guide", "register", "policy"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        output = handle(payload, args.scope_root, args.guide, args.register, args.policy)
    except (ValueError, TypeError) as exc:
        print(f"agent work hook invalid input: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
