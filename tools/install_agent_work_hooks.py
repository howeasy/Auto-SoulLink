"""Preview or install additive user-level Codex/Claude lifecycle hooks."""

import argparse
import json
import ntpath
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

EVENTS = ("SessionStart", "UserPromptSubmit", "Stop")
MARKER = "slink-agent-work-v1"


def _quote(value):
    # Windows command handlers are launched as shell commands, not argv arrays.
    value = str(value)
    if any(char in value for char in '"\r\n%!^&|<>'):
        raise ValueError("hook command path contains unsupported quoting")
    return '"' + value + '"'


def command(python, script, scope, guide, register, policy):
    python = str(python)
    if " " in python or any(char in python for char in '"\r\n%!^&|<>'):
        raise ValueError("Python executable must have a shell-safe path without spaces")
    parts = [
        script,
        "--hook-id",
        MARKER,
        "--scope-root",
        scope,
        "--guide",
        guide,
        "--register",
        register,
        "--policy",
        policy,
    ]
    return python.replace("\\", "/") + " " + " ".join(_quote(part) for part in parts)


def _tokens(command_text):
    # The installer emits one bare executable followed by quoted Windows args.
    return [quoted or bare for quoted, bare in re.findall(r'"([^"\r\n]*)"|(\S+)', command_text)]


def _ours(handler, expected_command):
    if not isinstance(handler, dict):
        return False
    cmd = handler.get("command")
    if handler.get("type") != "command" or not isinstance(cmd, str):
        return False
    actual, expected = _tokens(cmd), _tokens(expected_command)
    return (
        len(actual) >= 4
        and len(expected) >= 4
        and ntpath.basename(actual[0]).casefold() == ntpath.basename(expected[0]).casefold()
        and ntpath.normcase(ntpath.normpath(actual[1]))
        == ntpath.normcase(ntpath.normpath(expected[1]))
        and actual[2:4] == ["--hook-id", MARKER]
    )


def merge(config, hook_command):
    result = json.loads(json.dumps(config))
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("existing hooks is not an object")
    for event in EVENTS:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise ValueError(f"existing {event} hooks is not an array")
        kept = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                kept.append(entry)
                continue
            other = [handler for handler in entry["hooks"] if not _ours(handler, hook_command)]
            if other:
                kept.append({**entry, "hooks": other})
        kept.append({"hooks": [{"type": "command", "command": hook_command, "timeout": 10}]})
        hooks[event] = kept
    return result


def plan(path, hook_command):
    original = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(original, dict):
        raise ValueError(f"{path} must be a JSON object")
    return original, merge(original, hook_command)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply", action="store_true", help="write after review; default is dry-run"
    )
    parser.add_argument("--codex", type=Path, default=Path.home() / ".codex" / "hooks.json")
    parser.add_argument("--claude", type=Path, default=Path.home() / ".claude" / "settings.json")
    parser.add_argument("--scope-root", type=Path, required=True)
    parser.add_argument("--guide", type=Path, required=True)
    parser.add_argument("--register", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    cmd = command(
        Path(sys.executable).resolve(),
        Path(__file__).with_name("agent_work_guard.py").resolve(),
        *(p.resolve() for p in (args.scope_root, args.guide, args.register, args.policy)),
    )
    planned = [(path, *plan(path, cmd)) for path in (args.codex, args.claude)]
    for path, before, after in planned:
        print(
            json.dumps(
                {
                    "path": str(path),
                    "changed": before != after,
                    "handler": {"type": "command", "command": cmd, "timeout": 10},
                    "events": EVENTS,
                    "existing_keys_preserved": sorted(before),
                },
                indent=2,
            )
        )
    if args.apply:
        for path, before, after in planned:
            if before == after:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                backup = path.with_name(
                    path.name + "." + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".bak"
                )
                shutil.copy2(path, backup)
                print(f"backup: {backup}")
            tmp = path.with_name(path.name + ".agent-work.tmp")
            tmp.write_text(json.dumps(after, indent=2) + "\n", encoding="utf-8")
            tmp.replace(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
