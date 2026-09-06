"""Prepare and verify isolated RR native gates; this CLI does not launch emulators.

The execution API is intentionally separate for review. Fixtures require an
explicit identity sidecar; a filename, mtime, or naked RESULT: PASS is not evidence.

The sidecar schema is slink-rr-fixture-v1 with kind (battery/state), system GBA,
core mGBA, scene, fixture_sha256 and exact rom_sha256. States additionally require
emulator_sha256, emulator_version and the hash of their SyncSettings.json bytes.
Battery fixtures require ram_assertions [{address,width,expected}] and may supply
reviewed boot_inputs [{frames,buttons}]. Their database directory is explicit.

Each source dependency must be selected with --source-file; the script is always
included. This snapshots a declared closure, not an inferred complete codebase.
The arena probe's recommended required IDs are descriptor_matches_bound_rom,
frame_budget_complete, pc_reads_available, trace_complete, execute_control_observed,
read_hook_observed and write_hook_observed, with the matching
--native-manifest. It still reports ownership unresolved, including after zero hits.

Historical batteries without compatibility evidence use purpose fixture_discovery
and slink-rr-fixture-candidate-v1 (compatibility="unverified", provenance object,
no rom_sha256/ram_assertions). Only the observation-only fixture_probe.lua may run.
Its output cannot pass validate_result or claim fixture_loaded. An engine-observed
fixture must be reviewed and frozen separately before normal native validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from server.lua_literals import lua_string
from tools.emulator_sandbox import (
    ProcessIdentity,
    SandboxError,
    child_path,
    copy_verified,
    create_instance_root,
    database_saveram_name,
    digest,
    hidden_process_kwargs,
    identity,
    isolated_config,
    json_bytes,
    verify_identity,
)

SCHEMA = "slink-rr-native-gate-v1"
RESULT_SCHEMA = "slink-rr-native-gate-result-v1"
BUILTIN_ASSERTIONS = ("system_gba", "loaded_rom_sha1", "emulator_version", "fixture_loaded")
HOST_IDENTITY_HELPER = "lua/tests/rr/host_identity.lua"


@dataclass(frozen=True)
class GateSpec:
    emulator: Path
    emulator_version: str
    base_config: Path
    rom: Path
    fixture: Path
    fixture_manifest: Path
    source_root: Path
    script: str
    output_root: Path
    run_id: str
    player: str
    required_assertions: tuple[str, ...]
    source_files: tuple[str, ...] = ()
    game_db_dir: Path | None = None
    native_manifest: Path | None = None
    core: str = "mGBA"
    frames: int = 600
    probe_options: dict[str, Any] = field(default_factory=dict)
    purpose: str = "validation"


def _object_file(path: Path) -> dict[str, Any]:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise SandboxError(f"Duplicate JSON key {key!r}: {path}")
            value[key] = item
        return value

    value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise SandboxError(f"Expected JSON object: {path}")
    return value


def _validate_boot_inputs(steps: Any) -> None:
    if not isinstance(steps, list) or len(steps) > 20:
        raise SandboxError("Battery boot requires at most 20 explicit steps")
    total = 0
    for step in steps:
        if not isinstance(step, dict) or set(step) - {"frames", "buttons"}:
            raise SandboxError("Malformed battery boot step")
        frames, buttons = step.get("frames"), step.get("buttons", {})
        if type(frames) is not int or not 1 <= frames <= 600:
            raise SandboxError("Battery boot step frames must be between 1 and 600")
        if (not isinstance(buttons, dict)
                or set(buttons) - {"A", "B", "Start", "Select", "Up", "Down", "Left", "Right", "L", "R"}
                or any(type(value) is not bool for value in buttons.values())):
            raise SandboxError("Unsupported battery boot joypad input")
        total += frames
    if total > 3600:
        raise SandboxError("Battery boot exceeds 3600 frames")


def validate_fixture(spec: GateSpec, emulator: dict, rom: dict) -> dict:
    meta = _object_file(spec.fixture_manifest)
    fixture = identity(spec.fixture)
    if spec.purpose == "fixture_discovery":
        if (meta.get("schema") != "slink-rr-fixture-candidate-v1" or meta.get("kind") != "battery"
                or meta.get("compatibility") != "unverified" or "rom_sha256" in meta
                or "ram_assertions" in meta or not isinstance(meta.get("provenance"), dict)):
            raise SandboxError("Discovery requires an unverified battery candidate, not a claimed compatible fixture")
    elif meta.get("schema") != "slink-rr-fixture-v1":
        raise SandboxError("Fixture requires a slink-rr-fixture-v1 identity sidecar")
    if meta.get("fixture_sha256") != fixture["sha256"]:
        raise SandboxError("Fixture hash mismatch")
    if spec.purpose == "validation" and meta.get("rom_sha256") != rom["sha256"]:
        raise SandboxError("Fixture belongs to another ROM/patch; cross-patch state assumptions are forbidden")
    if meta.get("system") != "GBA" or meta.get("core") != spec.core:
        raise SandboxError("Fixture system/core mismatch")
    if "host" in meta:
        host = meta["host"]
        if (not isinstance(host, dict) or host.get("available") is not True
                or host.get("core_type") != "BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk"
                or not isinstance(host.get("core_assembly_file"), dict)
                or not isinstance(host.get("native_modules"), list) or not host["native_modules"]):
            raise SandboxError("Fixture host evidence lacks the actual supported core and library identities")
        for item in [host["core_assembly_file"], *host["native_modules"]]:
            if not isinstance(item, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
                raise SandboxError("Fixture host evidence has an invalid library hash")
    if not isinstance(meta.get("scene"), str) or not meta["scene"].strip():
        raise SandboxError("Fixture sidecar must identify its expected scene")
    kind = meta.get("kind")
    if kind == "battery":
        raw = spec.fixture.read_bytes()
        if len(raw) != 131088 or all(byte == 255 for byte in raw[:-16]):
            raise SandboxError("RR battery fixture must be nonblank BizHawk 128KiB flash plus 16-byte footer")
        _validate_boot_inputs(meta.get("boot_inputs", []))
    elif kind == "state":
        if meta.get("emulator_sha256") != emulator["sha256"] or meta.get("emulator_version") != spec.emulator_version:
            raise SandboxError("State fixture emulator identity mismatch")
        with zipfile.ZipFile(spec.fixture) as state:
            if len(state.namelist()) != len(set(state.namelist())):
                raise SandboxError("State ZIP contains duplicate entries")
            for name in ("BizVersion.txt", "SyncSettings.json"):
                if state.getinfo(name).file_size > 65536:
                    raise SandboxError("State metadata exceeds supported bound")
            version = state.read("BizVersion.txt").decode("utf-8").strip().split()[-1]
            if version != spec.emulator_version:
                raise SandboxError("Stale savestate version; loading it could open a modal dialog")
            sync = state.read("SyncSettings.json")
            if meta.get("sync_settings_sha256") != digest(sync):
                raise SandboxError("State sync-settings hash mismatch")
            sync_object = json.loads(sync).get("o", {})
            if spec.core != "mGBA" or "MGBAHawk+SyncSettings" not in sync_object.get("$type", ""):
                raise SandboxError("State sync settings are not the requested mGBA core")
            if sync_object.get("SkipBios") is not True:
                raise SandboxError("State requires an unstaged external BIOS; only SkipBios=true is supported")
            if not ({"Core.bin", "Core.bin.zst"} & set(state.namelist())):
                raise SandboxError("State ZIP has no core state")
            meta = dict(meta, verified_sync_settings=sync_object)
    else:
        raise SandboxError("Fixture kind must be battery or state")
    return meta


def _native_descriptor(spec: GateSpec, rom_bytes: bytes) -> dict[str, Any] | None:
    if spec.native_manifest is None:
        return None
    native = _object_file(spec.native_manifest)
    if native.get("rom_sha256") != digest(rom_bytes):
        raise SandboxError("Native build manifest does not match selected ROM bytes")
    address, size = native.get("descriptor_address"), native.get("descriptor_size")
    if not isinstance(address, int) or not isinstance(size, int) or not 4 <= size <= 4096:
        raise SandboxError("Invalid native descriptor range")
    offset = address - 0x08000000
    if offset < 0 or offset + size > len(rom_bytes):
        raise SandboxError("Native descriptor lies outside ROM")
    payload = rom_bytes[offset:offset + size]
    if payload[:4] != b"SLD2":
        raise SandboxError("Expected SLD2 native descriptor")
    return {"address": address, "size": size, "hex": payload.hex(),
            "build_id": native.get("build_id"), "manifest_sha256": identity(spec.native_manifest)["sha256"]}


def _lua_literal(value: Any) -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "{" + ",".join(_lua_literal(item) for item in value) + "}"
    if isinstance(value, dict):
        return "{" + ",".join(f"[{lua_string(key)}]={_lua_literal(item)}"
                               for key, item in sorted(value.items())) + "}"
    raise SandboxError(f"Unsupported Lua context type: {type(value).__name__}")


LUA_WRAPPER = r'''
local C = SLINK_GATE
local report = {schema="slink-rr-native-gate-result-v1", identity=C.identity,purpose=C.purpose,
    assertions={}, observed={}, evidence={runtime={}}, release_ready=false}
if C.purpose=="fixture_discovery" then report.fixture_compatibility="unverified" end
local function escape(s)
    s=tostring(s)
    local output={string.char(34)}
    for i=1,#s do
        local byte=string.byte(s,i)
        if byte==34 or byte==92 then output[#output+1]=string.char(92,byte)
        elseif byte<32 then output[#output+1]=string.char(92).."u"..string.format("%04x",byte)
        else output[#output+1]=string.char(byte) end
    end
    output[#output+1]=string.char(34)
    return table.concat(output)
end
local function encode(v)
    if type(v)=='string' then return escape(v) end
    if type(v)=='number' or type(v)=='boolean' then return tostring(v) end
    if type(v)~='table' then return 'null' end
    local list, n = {}, #v
    if n>0 then for i=1,n do list[#list+1]=encode(v[i]) end; return '['..table.concat(list,',')..']' end
    for k,x in pairs(v) do list[#list+1]=escape(k)..':'..encode(x) end
    return '{'..table.concat(list,',')..'}'
end
local function check(id, actual, expected)
    local passed=actual==expected
    report.assertions[#report.assertions+1]={id=id,kind="structural",actual=actual,
        expected=expected,passed=passed}
    if not passed then error("Structural assertion failed: "..id) end
end
local function checkpoint(phase)
    -- Partial evidence survives a wall-clock deadline, but can never validate as
    -- a completed result. The path is constant beneath this private run.
    report.complete=false;report.phase=phase
    local partial=assert(io.open(C.result_path:gsub("%.json$","_progress.json"),"w"))
    partial:write(encode(report),"\n");partial:close()
end
local function main()
    SLINK_ROOT=C.source_root
    SLINK_HOST="127.0.0.1"; SLINK_PORT=0; SLINK_PLAYER=C.identity.player
    report.observed.emulator_version=client.getversion()
    report.observed.system=emu.getsystemid()
    report.observed.rom_sha1=gameinfo.getromhash():upper():gsub('^SHA1:', '')
    check("system_gba", report.observed.system, "GBA")
    check("loaded_rom_sha1", report.observed.rom_sha1, C.identity.rom_sha1)
    check("emulator_version", report.observed.emulator_version, C.identity.emulator_version)
    if C.naming then
        report.observed.game_name=gameinfo.getromname()
        check("saveram_game_name", report.observed.game_name, C.naming.game_name)
        check("saveram_database_match", gameinfo.indatabase(), C.naming.in_database)
    end
    if C.fixture_kind=="state" then
        local ok, why=pcall(savestate.load, C.fixture_path)
        if not ok then report.observed.fixture_load_error=tostring(why) end
        check("fixture_loaded", ok, true)
    else
        -- Loading a battery is not proven by a file copy. Each battery fixture
        -- must declare a RAM precondition that the probe checks after boot.
        report.observed.battery_seeded=true
    end
    memory.usememorydomain("System Bus")
    local host,main_form=nil,nil
    if C.host_identity_path then
        host,main_form=dofile(C.host_identity_path).capture(C.requested_core)
        report.observed.host=host
        checkpoint("running_host_observed")
        if C.fixture_meta.host then
            local expected=C.fixture_meta.host
            check("actual_core_available",host.available,true)
            check("actual_core_type",host.core_type,expected.core_type)
            check("actual_core_matches_configuration",host.matches_requested_core,true)
            check("actual_core_assembly_hash",host.core_assembly_file.sha256,expected.core_assembly_file.sha256)
            check("actual_core_module_query",host.module_query_available,true)
            local function hashes(items)
                local out={};for _,item in ipairs(items) do out[#out+1]=item.sha256 end
                table.sort(out);return table.concat(out,",")
            end
            check("actual_core_native_hashes",hashes(host.native_modules),hashes(expected.native_modules))
        end
    end
    local run=dofile(C.script_path)
    check("script_callable", type(run), "function")
    run({config=C,report=report,check=check,checkpoint=checkpoint,host=host,main_form=main_form})
    report.complete=true;report.phase="complete"
end
local ok, why=pcall(main)
if not ok then report.complete=false; report.error=tostring(why) end
local out=assert(io.open(C.result_path,"w"))
out:write(encode(report),"\n");out:close()
client.exit()
'''


def prepare_gate(spec: GateSpec) -> Path:
    """Create one fresh private instance; does not execute any emulator or script."""
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", spec.emulator_version):
        raise SandboxError("An explicit stable emulator version is required")
    if spec.purpose not in ("validation", "fixture_discovery"):
        raise SandboxError("Unsupported native-gate purpose")
    if spec.purpose == "fixture_discovery" and spec.script != "lua/tests/rr/fixture_probe.lua":
        raise SandboxError("Unverified fixtures may run only the observation-only fixture probe")
    if spec.core != "mGBA":
        raise SandboxError("Only the explicitly supported mGBA core can be prepared")
    if type(spec.frames) is not int or not 1 <= spec.frames <= 10_000_000 or not spec.required_assertions:
        raise SandboxError("A bounded frame count and explicit structural assertion IDs are required")
    if spec.purpose == "fixture_discovery":
        if not isinstance(spec.probe_options, dict):
            raise SandboxError("Discovery probe options must be an object")
        steps = spec.probe_options.get("steps", [])
        if "stop_at_field" in spec.probe_options and type(spec.probe_options["stop_at_field"]) is not bool:
            raise SandboxError("Discovery stop_at_field must be a boolean")
        hold = spec.probe_options.get("host_hold_ms", 0)
        if type(hold) is not int or not 0 <= hold <= 2000:
            raise SandboxError("Discovery host hold must be bounded to 0-2000 milliseconds")
        pause = spec.probe_options.get("host_pause_before_hold", False)
        if type(pause) is not bool or (pause and not hold):
            raise SandboxError("Discovery private pause requires a boolean and a nonzero host hold")
        if not isinstance(steps, list) or len(steps) > 20:
            raise SandboxError("Discovery permits at most 20 explicit input/idle steps")
        total = spec.frames
        for step in steps:
            if not isinstance(step, dict) or set(step) - {"frames", "buttons"}:
                raise SandboxError("Malformed discovery step")
            frames, buttons = step.get("frames"), step.get("buttons", {})
            if type(frames) is not int or not 1 <= frames <= 600:
                raise SandboxError("Discovery step frames must be between 1 and 600")
            if (not isinstance(buttons, dict) or set(buttons) - {"A", "B", "Start", "Select", "Up", "Down", "Left", "Right", "L", "R"}
                    or any(type(value) is not bool for value in buttons.values())):
                raise SandboxError("Unsupported discovery joypad input")
            total += frames
        if total > 3600:
            raise SandboxError("Discovery frame budget exceeds 3600 frames")
    if len(set(spec.required_assertions)) != len(spec.required_assertions):
        raise SandboxError("Required structural assertion IDs must be unique")
    original = {name: identity(path) for name, path in (
        ("emulator", spec.emulator), ("base_config", spec.base_config), ("rom", spec.rom),
        ("fixture", spec.fixture), ("fixture_manifest", spec.fixture_manifest))}
    rom_bytes = spec.rom.read_bytes()
    fixture_meta = validate_fixture(spec, original["emulator"], original["rom"])
    config = _object_file(spec.base_config)
    descriptor = _native_descriptor(spec, rom_bytes)
    if spec.native_manifest is not None:
        original["native_manifest"] = identity(spec.native_manifest)
    files = {spec.script, *spec.source_files}
    if fixture_meta.get("host") and HOST_IDENTITY_HELPER not in files:
        raise SandboxError("Reviewed fixture host requires the explicit host_identity.lua source dependency")
    if spec.native_manifest is not None:
        native_inputs = _object_file(spec.native_manifest).get("native_inputs", {})
        if not isinstance(native_inputs, dict):
            raise SandboxError("Native source inputs must be a path-to-hash object")
        source_root = spec.source_root.resolve()
        for relative, expected_hash in native_inputs.items():
            native_source = (source_root / "patch" / relative).resolve(strict=True)
            if source_root not in native_source.parents:
                raise SandboxError("Native manifest source escapes the selected source root")
            if identity(native_source)["sha256"] != expected_hash:
                raise SandboxError(f"Native source differs from build manifest: {relative}")
            files.add(native_source.relative_to(source_root).as_posix())
    files = sorted(files)
    selected = {relative: child_path(spec.source_root, relative) for relative in files}
    for relative, source in selected.items():
        if source.is_symlink() or not source.is_file():
            raise SandboxError(f"Source must be a regular contained file: {relative}")
    source_records = [{"relative_path": relative, **identity(path)} for relative, path in selected.items()]
    source_sha = digest(json_bytes([{k: row[k] for k in ("relative_path", "sha256", "size_bytes")}
                                   for row in source_records]))
    naming = None
    if fixture_meta["kind"] == "battery":
        if spec.game_db_dir is None:
            raise SandboxError("Battery boot requires an explicit game database directory")
        naming = database_saveram_name(rom_bytes, spec.game_db_dir)
        if spec.purpose == "validation" and (
            not isinstance(fixture_meta.get("ram_assertions"), list) or not fixture_meta["ram_assertions"]
        ):
            raise SandboxError("Battery fixture requires structural RAM assertions proving its loaded scene")
        for assertion in fixture_meta.get("ram_assertions", []):
            if not isinstance(assertion, dict):
                raise SandboxError("Malformed battery RAM assertion")
            address, width, expected = (assertion.get(key) for key in ("address", "width", "expected"))
            if (type(address) is not int or type(width) is not int or width not in (1, 2, 4) or type(expected) is not int
                    or not 0 <= expected < 1 << (8 * width)
                    or not ((address >= 0x02000000 and address + width <= 0x02040000)
                            or (address >= 0x03000000 and address + width <= 0x03008000))):
                raise SandboxError("Battery RAM assertion lies outside supported unsigned RAM reads")
    root = create_instance_root(spec.output_root, spec.run_id, spec.player,
                                [spec.source_root, spec.emulator.parent])
    copies = {}
    copies["rom"] = copy_verified(spec.rom, child_path(root, "rom/rrgate.gba"))
    fixture_name = "fixture.State" if fixture_meta["kind"] == "state" else "fixture.SaveRAM"
    copies["fixture"] = copy_verified(spec.fixture, child_path(root, "fixture/" + fixture_name))
    copies["fixture_manifest"] = copy_verified(spec.fixture_manifest, child_path(root, "fixture/identity.json"))
    if naming:
        copies["seeded_battery"] = copy_verified(spec.fixture, child_path(root, "gba/saveram/" + naming["filename"]))
        copies["seeded_battery"]["mutable_runtime_copy"] = True
    for relative, source in selected.items():
        copies["source:" + relative] = copy_verified(source, child_path(root, "source/" + relative))
    cfg = isolated_config(config, root, spec.core)
    core_key = "BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk"
    core_settings = cfg.setdefault("CoreSyncSettings", {})
    if fixture_meta["kind"] == "state":
        core_settings[core_key] = fixture_meta["verified_sync_settings"]
    else:
        chosen = core_settings.setdefault(core_key, {})
        chosen.setdefault("$type", core_key + "+SyncSettings, BizHawk.Emulation.Cores")
        chosen["SkipBios"] = True  # No firmware discovery or missing-BIOS modal.
    cfg_path = child_path(root, "config.json")
    cfg_path.write_bytes(json_bytes(cfg))
    cfg_initial = child_path(root, "config.initial.json")
    cfg_initial.write_bytes(json_bytes(cfg))
    child_path(root, "logs").mkdir(exist_ok=True)
    child_path(root, "results").mkdir(exist_ok=True)
    result_path = child_path(root, "results/result.json")
    binding = {"run_id": spec.run_id, "player": spec.player, "purpose": spec.purpose, "source_sha256": source_sha,
               "probe_options_sha256": digest(json_bytes(spec.probe_options)), "frame_budget": spec.frames,
               "rom_sha256": original["rom"]["sha256"],
               "rom_sha1": hashlib.sha1(rom_bytes).hexdigest().upper(),
               "script_sha256": identity(selected[spec.script])["sha256"],
               "emulator_sha256": original["emulator"]["sha256"], "emulator_version": spec.emulator_version,
               "fixture_sha256": original["fixture"]["sha256"],
               "fixture_manifest_sha256": original["fixture_manifest"]["sha256"],
               "config_sha256": identity(cfg_path)["sha256"]}
    binding["binding_sha256"] = digest(json_bytes(binding))
    context = {"identity": binding, "purpose": spec.purpose, "fixture_kind": fixture_meta["kind"],
               "requested_core": spec.core,
               "fixture_path": copies["fixture"]["copy"]["path"],
               "script_path": child_path(root, "source/" + spec.script).as_posix(),
               "source_root": child_path(root, "source").as_posix(),
               "result_path": result_path.as_posix(), "frames": spec.frames,
               "fixture_meta": fixture_meta, "naming": naming,
               "descriptor": descriptor, "probe_options": spec.probe_options}
    if HOST_IDENTITY_HELPER in files:
        context["host_identity_path"] = child_path(root, "source/" + HOST_IDENTITY_HELPER).as_posix()
    # Database source paths do not belong in the Lua context.
    if naming:
        context["naming"] = {key: value for key, value in naming.items() if key != "database_inputs"}
    launcher_path = child_path(root, "launcher.lua")
    launcher_path.write_text("SLINK_GATE=" + _lua_literal(context) + "\n" + LUA_WRAPPER,
                             encoding="utf-8", newline="\n")
    builtin = BUILTIN_ASSERTIONS if spec.purpose == "validation" else (
        "system_gba", "loaded_rom_sha1", "emulator_version", "fixture_observation_complete",
    )
    required = list(dict.fromkeys((*builtin, *spec.required_assertions)))
    if fixture_meta.get("host"):
        required.extend(["actual_core_available", "actual_core_type", "actual_core_matches_configuration",
                         "actual_core_assembly_hash", "actual_core_module_query", "actual_core_native_hashes"])
    manifest = {"schema": SCHEMA, "purpose": spec.purpose, "phase": "prepared_not_executed", "root": str(root),
                "identity": binding, "original_inputs": list(original.values()) + source_records,
                "emulator": original["emulator"], "copies": copies,
                "config": identity(cfg_path), "config_initial": identity(cfg_initial),
                "launcher": identity(launcher_path),
                "result_path": str(result_path), "required_assertions": required,
                "command": [original["emulator"]["path"], "--config=config.json", "--lua=launcher.lua", "rom/rrgate.gba"],
                "game_database_inputs": naming["database_inputs"] if naming else [],
                "fixture_meta": fixture_meta, "release_ready": False}
    for item in manifest["original_inputs"] + manifest["game_database_inputs"]:
        verify_identity(item)
    manifest_path = child_path(root, "prepared.json")
    manifest_path.write_bytes(json_bytes(manifest))
    return manifest_path


def verify_preparation(path: Path, *, after_execution: bool = False) -> dict[str, Any]:
    prepared = _object_file(path)
    if prepared.get("schema") != SCHEMA or prepared.get("phase") != "prepared_not_executed":
        raise SandboxError("Not a supported prepared native gate")
    root = Path(prepared["root"]).resolve()
    if path.resolve().parent != root:
        raise SandboxError("Prepared manifest has moved outside its private root")
    expected_command = [prepared["emulator"]["path"], "--config=config.json", "--lua=launcher.lua", "rom/rrgate.gba"]
    if prepared["command"] != expected_command:
        raise SandboxError("Prepared command is not the private launcher command")
    binding = dict(prepared["identity"])
    expected_binding_hash = binding.pop("binding_sha256", None)
    if digest(json_bytes(binding)) != expected_binding_hash:
        raise SandboxError("Prepared identity hash mismatch")
    if prepared.get("purpose") != binding.get("purpose"):
        raise SandboxError("Prepared purpose differs from its identity binding")
    if prepared["emulator"]["sha256"] != binding["emulator_sha256"]:
        raise SandboxError("Prepared emulator identity mismatch")
    for item in prepared["original_inputs"] + prepared["game_database_inputs"]:
        verify_identity(item)
    for pair in prepared["copies"].values():
        if root not in Path(pair["copy"]["path"]).resolve().parents:
            raise SandboxError("Prepared copy escapes private root")
        if not (after_execution and pair.get("mutable_runtime_copy")):
            verify_identity(pair["copy"])
    for name in ("config", "config_initial", "launcher"):
        if root not in Path(prepared[name]["path"]).resolve().parents:
            raise SandboxError("Prepared control file escapes private root")
        if not (after_execution and name == "config"):
            verify_identity(prepared[name])
    if prepared["config_initial"]["sha256"] != binding["config_sha256"]:
        raise SandboxError("Initial configuration differs from binding")
    if Path(prepared["result_path"]).resolve() != child_path(root, "results/result.json"):
        raise SandboxError("Prepared result path is not private")
    return prepared


def _validate_bound_result(prepared: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    result_path = Path(prepared["result_path"]) if path is None else path
    if result_path.resolve() != Path(prepared["result_path"]).resolve():
        raise SandboxError("Result path does not belong to this gate")
    if not result_path.is_file() or result_path.stat().st_size > 8 * 1024 * 1024:
        raise SandboxError("Missing or oversized native-gate result")
    result = _object_file(result_path)
    if (result.get("schema") != RESULT_SCHEMA or result.get("identity") != prepared["identity"]
            or result.get("purpose") != prepared.get("purpose")):
        raise SandboxError("Result schema or run/source/ROM/emulator/fixture identity mismatch")
    if result.get("complete") is not True or result.get("release_ready") is not False:
        raise SandboxError("Native gate did not complete its bounded structural probe")
    observed = result.get("observed", {})
    if (observed.get("rom_sha1") != prepared["identity"]["rom_sha1"]
            or observed.get("emulator_version") != prepared["identity"]["emulator_version"]
            or observed.get("system") != "GBA"):
        raise SandboxError("Observed running ROM/emulator/system differs from preparation")
    assertions = result.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        raise SandboxError("A naked PASS without structural assertions is not evidence")
    seen = set()
    for item in assertions:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                or item["id"] in seen or item.get("kind") != "structural"
                or "actual" not in item or "expected" not in item or item.get("passed") is not True
                or type(item["actual"]) is not type(item["expected"])
                or item["actual"] != item["expected"]):
            raise SandboxError("Malformed, duplicate, or failed structural assertion")
        seen.add(item["id"])
    if not set(prepared["required_assertions"]) <= seen:
        raise SandboxError("Required structural assertions missing")
    return result


def validate_result(prepared: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    if prepared.get("purpose") != "validation" or prepared["identity"].get("purpose") != "validation":
        raise SandboxError("Candidate discovery cannot be accepted as a validated fixture/native gate")
    return _validate_bound_result(prepared, path)


def validate_observation(prepared: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    if prepared.get("purpose") != "fixture_discovery" or prepared["identity"].get("purpose") != "fixture_discovery":
        raise SandboxError("Not a fixture-discovery preparation")
    result = _validate_bound_result(prepared, path)
    if result.get("fixture_compatibility") != "unverified":
        raise SandboxError("Candidate observation must not claim fixture compatibility")
    if any(row["id"] == "fixture_loaded" for row in result["assertions"]):
        raise SandboxError("Candidate observation must not claim validated fixture load")
    return result


def launch_prepared(path: Path, popen=subprocess.Popen, process_api=None):
    """Execution API for later reviewed use. The CLI intentionally has no run command."""
    prepared = verify_preparation(path)
    if Path(prepared["result_path"]).exists():
        raise SandboxError("Refusing a previously executed/prepopulated gate")
    if process_api is None:
        import psutil as process_api
    root = Path(prepared["root"])
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("SLINK_") and key not in ("LUA_PATH", "LUA_CPATH")}
    env["SLINK_ROOT"] = str(root / "source")
    env["SLINK_GATE_RUN_ID"] = prepared["identity"]["run_id"]
    with (root / "logs/emulator.log").open("xb") as log:
        process = popen(prepared["command"], cwd=root, stdin=subprocess.DEVNULL,
                        stdout=log, stderr=subprocess.STDOUT, env=env, **hidden_process_kwargs())
    return process, ProcessIdentity(process.pid, process_api.Process(process.pid).create_time())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    prep = commands.add_parser("prepare")
    for name in ("emulator", "base-config", "rom", "fixture", "fixture-manifest", "source-root", "output-root"):
        prep.add_argument("--" + name, type=Path, required=True)
    for name in ("emulator-version", "script", "run-id", "player"):
        prep.add_argument("--" + name, required=True)
    prep.add_argument("--required-assertion", action="append", required=True)
    prep.add_argument("--source-file", action="append", default=[])
    prep.add_argument("--game-db-dir", type=Path)
    prep.add_argument("--native-manifest", type=Path)
    prep.add_argument("--frames", type=int, default=600)
    prep.add_argument("--purpose", choices=("validation", "fixture_discovery"), default="validation")
    verify = commands.add_parser("verify")
    verify.add_argument("--prepared", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == "prepare":
            values = vars(args).copy()
            values.pop("operation")
            values["required_assertions"] = tuple(values.pop("required_assertion"))
            values["source_files"] = tuple(values.pop("source_file"))
            path = prepare_gate(GateSpec(**values))
            print(json.dumps({"phase": "prepared_not_executed", "manifest": str(path), "release_ready": False}))
        else:
            prepared = verify_preparation(args.prepared, after_execution=True)
            if prepared["purpose"] == "fixture_discovery":
                validate_observation(prepared)
                print(json.dumps({"fixture_observation_complete": True, "fixture_compatibility": "unverified",
                                  "release_ready": False}))
            else:
                validate_result(prepared)
                print(json.dumps({"structural_probe_complete": True, "release_ready": False}))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(2, f"Native gate rejected: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
