"""Test-only host for checked selected launchers and normal scripted buttons.

Importing is inert. The explicit module CLI acquires the product process lease,
uses product prepare/launch, and substitutes only a separate Lua bootstrap.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

from server.bizhawk_launch import launch, prepare, validate_manifest
from server.runtime_lease import RuntimeLease

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "lua/tests/gen1_scripted_new_game.lua"
RB_ROUTE = ROOT / "lua/tests/gen1_rb_ball_gate_inputs.lua"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare_scripted_plan(root, spec, *, rom, launcher, base_config, bootstrap=BOOTSTRAP,
                          route_mode=None):
    """Preserve product preflight and stage only test Lua beside checked launcher."""
    validate_manifest(spec)
    root = Path(root).resolve()
    bootstrap = Path(bootstrap).resolve()
    if bootstrap != BOOTSTRAP.resolve():
        raise ValueError("the checked test-only bootstrap source is required")
    plan = prepare(root, spec, rom=rom, launcher=launcher, base_config=base_config)
    match = re.fullmatch(r"slink_(red|blue|yellow)\.gb", Path(rom).name)
    if match is None:
        raise ValueError("scripted selected companion filename required")
    staged = Path(plan["cwd"]).resolve()
    if not staged.is_relative_to(root):
        raise ValueError("scripted host directory leaves owned root")
    source = bootstrap.read_bytes()
    if not source or len(source) > 128 * 1024:
        raise ValueError("bounded scripted bootstrap required")
    destination = staged / "scripted_new_game.lua"
    if destination.exists() and destination.read_bytes() != source:
        raise ValueError("existing scripted bootstrap differs")
    destination.write_bytes(source)
    if route_mode not in (None, "rb-starter-rival"):
        raise ValueError("unsupported scripted route")
    if route_mode == "rb-starter-rival":
        if match.group(1) not in ("red", "blue"):
            raise ValueError("R/B lab route requires Red or Blue")
        route_bytes = RB_ROUTE.read_bytes()
        route_destination = staged / "gen1_rb_ball_gate_inputs.lua"
        if route_destination.exists() and route_destination.read_bytes() != route_bytes:
            raise ValueError("existing R/B route module differs")
        route_destination.write_bytes(route_bytes)
    input_path = staged / "scripted_input.json"
    input_data = {"schema": "gen1-scripted-normal-buttons-v1", "player": spec["player"],
                  "variant": match.group(1),
                  "run_id": spec["run_id"],
                  "rom_sha1": spec["rom_sha1"], "launcher": str(staged / "launcher.lua"),
                  "progress": str(staged / "scripted_progress.json"),
                  "failure": str(staged / "scripted_failure.json"),
                  "max_boot_frames": 20000, "deadline_seconds": 1800}
    if route_mode == "rb-starter-rival":
        input_data["route"] = {"mode": route_mode, "module": str(route_destination),
                               "handshake": str(staged / "rb_route_go.json"),
                               "progress": str(staged / "rb_route_progress.json")}
    if input_path.exists() and json.loads(input_path.read_text()) != input_data:
        raise ValueError("existing scripted input differs")
    input_path.write_text(json.dumps(input_data, indent=2) + "\n")
    if plan["arguments"][1] != "--lua=launcher.lua":
        raise ValueError("product Lua argument changed")
    plan["arguments"][1] = "--lua=scripted_new_game.lua"
    plan["environment"]["SLINK_SCRIPTED_INPUT"] = str(input_path)
    plan["scripted_bootstrap_sha256"] = sha(destination)
    if route_mode == "rb-starter-rival":
        plan["rb_route_sha256"] = sha(route_destination)
    plan["checked_launcher_sha256"] = sha(staged / "launcher.lua")
    if plan["checked_launcher_sha256"] != spec["launcher_sha256"]:
        raise ValueError("scripted host changed checked launcher")
    return plan


def scripted_failure(directory):
    """Read the test driver's owned failure marker, if it published one."""
    marker = Path(directory) / "scripted_failure.json"
    try:
        raw = marker.read_text()
    except FileNotFoundError:
        return None
    detail = json.loads(raw)
    if not isinstance(detail, dict) or detail.get("stage") != "failure" or not isinstance(detail.get("error"), str):
        raise ValueError("invalid scripted failure marker")
    return detail


def scripted_progress(directory):
    marker = Path(directory) / "scripted_progress.json"
    try:
        raw = marker.read_text()
    except FileNotFoundError:
        return None
    detail = json.loads(raw)
    if not isinstance(detail, dict) or detail.get("stage") not in {
            "wrapper-ready", "normal-buttons", "input-stopped"}:
        raise ValueError("invalid scripted progress marker")
    return detail


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "rom", "emuhawk", "base-config", "root"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--route", choices=("rb-starter-rival",))
    args = parser.parse_args(argv)
    spec = json.loads(args.manifest.read_text())
    validate_manifest(spec)
    root = args.root.resolve()
    home = (root / spec["run_id"] / spec["player"]).resolve()
    if not home.is_relative_to(root):
        raise ValueError("scripted player home leaves owned root")
    home.mkdir(parents=True, exist_ok=True)
    with RuntimeLease(home / ".process.lock"):
        plan = prepare_scripted_plan(root, spec, rom=args.rom, launcher=args.manifest.with_name("launcher.lua"),
                                     base_config=args.base_config, route_mode=args.route)
        receipt = {
            "launch_mode": "scripted-selected-launcher", "arguments": plan["arguments"],
            "checked_launcher_sha256": plan["checked_launcher_sha256"],
            "scripted_bootstrap_sha256": plan["scripted_bootstrap_sha256"],
            "environment": {key: plan["environment"][key] for key in (
                "SLINK_ROOT", "SLINK_CLIENT_STORAGE_ROOT", "SLINK_SAVERAM_DIRECTORY",
                "SLINK_SCRIPTED_INPUT")}}
        if args.route:
            receipt["route_mode"] = args.route
            receipt["rb_route_sha256"] = plan["rb_route_sha256"]
        (Path(plan["cwd"]) / "scripted_plan.json").write_text(json.dumps(receipt, indent=2) + "\n")
        return launch(plan, args.emuhawk).wait()


if __name__ == "__main__":
    raise SystemExit(main())
