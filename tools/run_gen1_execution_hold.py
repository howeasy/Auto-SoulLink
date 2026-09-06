"""Private, attributed Gambatte actuator qualification; no production selection."""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.lua_literals import lua_string  # noqa: E402
from tools import run_gb_gate as gate  # noqa: E402

VARIANTS = {"red": "pokered", "blue": "pokeblue", "yellow": "pokeyellow"}
MODES = ("lifecycle", "external_clear", "stopped_reload")
SOURCES = (
    "lua/platform_execution.lua", "lua/platform_clock.lua",
    "lua/tests/platform_execution_probe.lua", "lua/tests/platform_execution_owner_helper.lua",
    "lua/tests/test_gen1_execution_hold_gate.lua", "lua/tests/gatelib.lua",
    "lua/json_codec.lua", "lua/memory_gb.lua", "lua/games/gen1_rby.lua",
    "tools/run_gen1_execution_hold.py", "tools/run_gb_gate.py", "tools/gen1_playthrough.py",
    "server/lua_literals.py",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_probe(variant, mode, *, paused=False):
    if variant not in VARIANTS or mode not in MODES or type(paused) is not bool:
        raise ValueError("explicit RBY title, probe mode and boolean pause state required")
    sources = {name: sha256(ROOT / name) for name in SOURCES}
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/platform_execution.lua").read_text(encoding="utf-8"))
    profile = dict(module.supported_profile("gambatte"))
    pin = json.loads((ROOT / "data/pret_sources.lock.json").read_text())["clean_roms"][VARIANTS[variant]]
    rom = (ROOT / pin["filename"]).read_bytes()
    if hashlib.sha1(rom).hexdigest() != pin["sha1"]:
        raise ValueError("exact canonical cartridge required")
    fixture = f"tests/fixtures/gen1/{variant}_town.SaveRAM"
    inputs = {fixture: sha256(ROOT / fixture), "data/pret_sources.lock.json": sha256(ROOT / "data/pret_sources.lock.json"),
              pin["filename"]: hashlib.sha256(rom).hexdigest()}
    tag = f"{variant}-{mode}-paused{int(paused)}-{secrets.token_hex(4)}"
    directory = ROOT / ".cache/gambatte-host-probes" / tag
    directory.mkdir(parents=True)
    config = json.loads(Path(gate.BIZHAWK_CONFIG).read_text(encoding="utf-8-sig"))
    # The actuator refuses active rewind. Only this private configuration is
    # changed; neither the adapter nor this runner alters the user's config.
    config["Rewind"]["Enabled"] = False
    private_config = directory / "base-config.ini"
    private_config.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    request = {
        "purpose": "validation", "source_root": ROOT.as_posix(),
        "result_path": (directory / "result.json").as_posix(), "variant": variant,
        "rom_sha1": pin["sha1"], "frames": 10000, "fixture_kind": "prebooted",
        "private_rewind_enabled": False, "private_config_sha256": sha256(private_config),
        "descriptor": {"address": 0x134, "size": 16, "hex": rom[0x134:0x144].hex(), "domain": "System Bus"},
        "probe_options": {
            "mode": mode, "initial_paused": paused, "profile": "gambatte",
            "owner_id": secrets.token_hex(16), "contender_id": secrets.token_hex(16), "hold_ms": 250,
            "adapter_sha256": sources["lua/platform_execution.lua"], "expected_host": profile,
            "helper_path": (ROOT / "lua/tests/platform_execution_owner_helper.lua").as_posix(),
        },
    }
    input_file = directory / "input.json"
    input_file.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    # Each process has its own input, script and gate-result name as well as
    # run_gb_gate's independent configuration/SaveRAM. No shared mutable input.
    template = (ROOT / "lua/tests/test_gen1_execution_hold_gate.lua").read_text(encoding="utf-8")
    substitutions = {
        'G.start("test_gen1_execution_hold_gate")': "G.start(" + lua_string("execution_hold_" + tag.replace("-", "_")) + ")",
        'ROOT.."/.cache/gen1-execution-probe-input.json"': lua_string(input_file.as_posix()),
    }
    for old, new in substitutions.items():
        if template.count(old) != 1:
            raise ValueError("probe template changed; review generated script inputs")
        template = template.replace(old, new)
    bootstrap = directory / "probe.lua"
    bootstrap.write_bytes(template.encode())
    passed, path, log = gate.run_gate(bootstrap.relative_to(ROOT).as_posix(), rom_key=variant,
                                    target="town", timeout=60, quiet=True, config_base=str(private_config))
    (directory / "gate.log").write_text(log, encoding="utf-8")
    drift = [name for name, value in sources.items() if sha256(ROOT / name) != value]
    drift.extend(name for name, value in inputs.items() if sha256(ROOT / name) != value)
    if sha256(private_config) != request["private_config_sha256"]:
        drift.append("private base configuration")
    result_file = directory / "result.json"
    result = json.loads(result_file.read_text()) if result_file.is_file() else {}
    summary = {
        "passed": passed and result.get("passed") is True and not drift,
        "variant": variant, "mode": mode, "paused": paused, "directory": str(directory),
        "sources": sources, "inputs": inputs, "source_drift": drift, "profile": profile,
        "input_sha256": sha256(input_file), "bootstrap_sha256": sha256(bootstrap),
        "fixture_sha256": inputs[fixture],
        "result_sha256": sha256(result_file) if result_file.is_file() else None,
        "gate_log_sha256": sha256(directory / "gate.log"), "gate_result_path": path,
        "failure": result.get("failure"), "release_ready": False,
    }
    (directory / "attribution.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=VARIANTS, default="yellow")
    parser.add_argument("--mode", choices=MODES, default="lifecycle")
    parser.add_argument("--paused", action="store_true")
    args = parser.parse_args(argv)
    result = run_probe(args.variant, args.mode, paused=args.paused)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
