"""Tracked selected-run lifecycle and evidence helpers. Importing has no side effects."""

import asyncio
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import psutil
from pytest import MonkeyPatch

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp(process):
    return {"pid": process.pid, "create_time": process.create_time()}


def matching(identity):
    try:
        process = psutil.Process(identity["pid"])
        return process if process.create_time() == identity["create_time"] else None
    except psutil.NoSuchProcess:
        return None


def observe(job):
    assert job["identity"] is not None, "CLI identity unavailable; descendants unknown"
    parent = matching(job["identity"])
    if parent is not None:
        for child in parent.children(recursive=True):
            identity = stamp(child)
            job["children"][(identity["pid"], identity["create_time"])] = identity
    (job["owned"] / f"{job['player']}-process.json").write_text(json.dumps({
        key: job[key] for key in ("argv", "identity", "log")
    } | {"children": list(job["children"].values())}, indent=2) + "\n")
    return job["process"].poll()


def cleanup_job(job):
    results = []
    if job["identity"] is None:
        # This handle came directly from our successful Popen. Its descendants
        # were never identity-qualified, so cleanup remains HOLD even if it exits.
        result = {"pid": job["process"].pid, "identity_unavailable": True,
                  "descendants_unknown": True}
        try:
            if job["process"].poll() is None:
                job["process"].terminate()
                try:
                    job["process"].wait(timeout=5)
                except subprocess.TimeoutExpired:
                    job["process"].kill()
                    job["process"].wait(timeout=5)
            result["alive_after"] = job["process"].poll() is None
        except BaseException as error:
            result["cleanup_error"] = f"{type(error).__name__}: {error}"
        results.append(result)
    for identity in list(reversed(list(job["children"].values()))) + [job["identity"]]:
        if identity is None:
            continue
        try:
            process = matching(identity)
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    if matching(identity) is not None:
                        process.kill()
                        process.wait(timeout=5)
            results.append({**identity, "alive_after": matching(identity) is not None})
        except BaseException as error:
            results.append({**identity, "cleanup_error": f"{type(error).__name__}: {error}"})
    return results


def cleanup_observed_job(job):
    observation_error = None
    try:
        observe(job)
    except BaseException as error:
        observation_error = f"{type(error).__name__}: {error}"
    try:
        results = cleanup_job(job)
    except BaseException as error:
        results = [{"cleanup_error": f"{type(error).__name__}: {error}"}]
    if observation_error is not None:
        results.append({"observation_error": observation_error, "descendants_unknown": True})
    return results


def cleanup_requires_hold(outcome):
    return bool(outcome["survivors"] or outcome["survivor_audit_unknown"] or any(
        "cleanup_error" in item or item.get("alive_after") or item.get("descendants_unknown")
        for values in outcome["cleanup"].values() for item in values
    ) or outcome.get("resource_cleanup_errors"))


async def drain_owned_handlers(listener, tasks, errors, timeout=5, listener_timeout=5):
    """Stop only this listener and await only connections accepted by it."""
    if listener is not None:
        try:
            listener.close()
        except BaseException as error:
            errors.append({"listener_close": f"{type(error).__name__}: {error}"})
    active = set(tasks)
    if active:
        _, pending = await asyncio.wait(active, timeout=timeout)
        if pending:
            errors.append({"owned_handlers_timeout": len(pending)})
            for task in pending:
                task.cancel()
            _, remaining = await asyncio.wait(pending, timeout=2)
            if remaining:
                errors.append({"owned_handlers_uncancelled": len(remaining)})
    if listener is not None:
        try:
            await asyncio.wait_for(listener.wait_closed(), timeout=listener_timeout)
        except BaseException as error:
            errors.append({"listener_wait": f"{type(error).__name__}: {error}"})


def checked_events(runtime):
    """SQL enumerates identities only; journal APIs verify every body and digest."""
    database = sqlite3.connect((Path(runtime.data_dir) / "runtime.sqlite3").resolve().as_uri() + "?mode=ro", uri=True)
    try:
        identifiers = database.execute(
            "SELECT player, operation_id, revision FROM events ORDER BY revision").fetchall()
    finally:
        database.close()
    rows = []
    for player, operation, revision in identifiers:
        event = runtime.journal.event_snapshot(player, operation)
        assert event is not None and event.revision == revision
        rows.append((player, revision, event.request, event.result, operation))
    return rows


def enrollment_ready(components, pending):
    required = ("gen1-native-reattach", "gen1-initial-observations",
                "gen1-new-game-bootstrap", "gen1-initial-save")
    return (all(set(components.get(name, {})) == {"a", "b"} for name in required)
            and all(components["gen1-initial-save"][player].get("receipt_operation")
                    for player in ("a", "b"))
            and not any(pending.values()))


def observation_sequence(rows, player):
    observed = [row for row in rows if row[0] == player and row[2].get("event") == "observation"]
    assert all(row[3].get("ack") == "ACK" for row in observed), "non-ACKed observation"
    sequence = [row[2]["sequence"] for row in observed]
    assert sequence == list(range(1, len(sequence) + 1)), "observation sequence gap"
    return sequence


def progress(owned, stage, **fields):
    (owned / "progress.json").write_text(json.dumps({"stage": stage, "at": time.time(), **fields}, indent=2) + "\n")


def emulator_child(job, emulator):
    for identity in job["children"].values():
        process = matching(identity)
        if process is not None and Path(process.exe()).resolve() == emulator:
            return identity
    raise AssertionError(f"{job['player']} identity-checked EmuHawk child missing")


def audit_enrollment(runtime, document, save_directories, jobs, rows, emulator):
    from server.event_reference import resolve
    from server.gen1_initial_save_runtime import prepared

    snapshot = runtime.journal.snapshot()
    assert snapshot.state == document, "current checked snapshot advanced during audit"
    assert runtime.service_current(), "paired control/service release not current"
    evidence = {}
    for player in ("a", "b"):
        components = document["components"]
        native = components["gen1-native-reattach"][player]
        assert all(native[key] == value for key, value in
                   (("verdict", "released"), ("class", "clean"), ("physical", "clean")))
        assert all(native.get(key) is not None for key in
                   ("read_digest", "frame", "lease_phase", "context_generation", "binding_digest"))
        initial = components["gen1-initial-observations"][player]
        assert all(key in initial for key in ("operation_id", "metadata", "binding", "observation", "inventory"))
        child = emulator_child(jobs[player], emulator)
        host = initial["observation"]["host"]
        physical = initial["metadata"]["gen1_metadata"]["physical_instance"]
        assert host["process_id"] == child["pid"] and host["owner_id"] == physical and host["held"] is True
        assert native["context_generation"] == initial["binding"]["context_generation"]
        assert native["binding_digest"] == initial["binding"]["binding_digest"]
        origin = resolve(runtime.journal, native["origin"])
        assert origin.request["event"] == "native_reattach"
        read = origin.request["payload"]["read"]
        assert origin.request["payload"]["physical"] == "clean"
        assert origin.request["payload"]["context_generation"] == native["context_generation"]
        assert read["host"]["process_id"] == child["pid"]
        assert read["host"]["owner_id"] == physical and read["host"]["held"] is True
        assert origin.result["ack"] == "ACK"
        assert origin.result["native_reattach"]["verdict"] == "released"
        assert origin.result["native_reattach"]["read_digest"] == native["read_digest"]
        assert read["frame"] == native["frame"]
        bootstrap = components["gen1-new-game-bootstrap"][player]
        assert bootstrap["operation_id"]
        save = components["gen1-initial-save"][player]
        assert save["receipt_operation"]
        event = runtime.journal.event_snapshot(player, save["receipt_operation"])
        assert event is not None and event.result == {"ack": "ACK"}
        proof = event.request["receipt"]["file"]
        expected = bytes.fromhex(prepared(document, player)["after"]["cart_hex"])
        file_receipt = verify_initial_save_file(proof, expected, save_directories[player])
        sequence = observation_sequence(rows, player)
        evidence[player] = {"native_reattach": native, "initial_observation": initial,
                            "bootstrap": bootstrap, "initial_save": save,
                            "save_file": file_receipt, "observation_count": len(sequence),
                            "observation_sequence": sequence,
                            "native_event_revision": origin.revision, "emulator_child": child}
    pending = {player: runtime.journal.pending_ids(player) for player in ("a", "b")}
    assert not any(pending.values()), "pending server commands"
    return {"players": evidence, "pending_ids": pending, "service_current": True,
            "events": [{"player": p, "revision": n, "operation_id": op,
                        "request": request, "result": result}
                       for p, n, request, result, op in rows]}


def verify_initial_save_file(proof, expected, save_directory):
    """Independent file read at the one-time enrollment boundary only."""
    path = Path(proof["path"])
    assert not path.is_symlink() and path.is_file(), "receipt file is not a regular file"
    assert path.resolve().parent == Path(save_directory).resolve(), "file outside exact player SaveRAM"
    actual = path.read_bytes()
    assert actual == expected and len(actual) == proof["byte_length"]
    assert hashlib.sha256(actual).hexdigest() == proof["sha256"]
    assert proof["flushed"] is True and proof["readback"] is True
    return {"path": str(path), "sha256": sha(path), "byte_length": len(actual), "receipt": proof}


def private_receipt(job, spec, rom, emulator):
    owned = job["owned"]
    private = owned / "clients" / spec["run_id"] / spec["player"]
    assert private.resolve().is_relative_to((owned / "clients").resolve())
    files = {name: private / "emulator" / name for name in
             ("launcher.lua", "launch.json", "config.ini", "game.gb", "slink_path.cfg")}
    assert all(path.is_file() for path in files.values()), files
    assert sha(files["launcher.lua"]) == spec["launcher_sha256"]
    assert hashlib.sha1(files["game.gb"].read_bytes()).hexdigest() == spec["rom_sha1"]
    assert files["game.gb"].read_bytes() == rom.read_bytes()
    assert json.loads(files["launch.json"].read_text()) == spec
    assert files["slink_path.cfg"].read_text().strip().replace("\\", "/").rstrip("/").lower() == ROOT.as_posix().rstrip("/").lower()
    config = json.loads(files["config.ini"].read_text())
    saves = private / "SaveRAM"
    paths = [entry["Path"] for entry in config["PathEntries"]["Paths"]
             if isinstance(entry, dict) and entry.get("Type") == "Save RAM"
             and entry.get("System") in {"GB_GBC_SGB", "GBL", "GB", "GBC", "SGB"}]
    assert paths and all(Path(path).resolve() == saves.resolve() for path in paths)
    assert config["FrameSkip"] == 0 and config["AutoMinimizeSkipping"] is False
    assert any(matching(child) is not None and Path(matching(child).exe()).resolve() == emulator
               for child in job["children"].values()), "identity-checked emulator child missing"
    return {"private": str(private), "save_directory": str(saves),
            "staged_sha256": {name: sha(path) for name, path in files.items()},
            "save_files": {str(path): sha(path) for path in saves.glob("*.SaveRAM")},
            "save_paths": paths, "root_cache": files["slink_path.cfg"].read_text()}


class SelectedRun:
    """Own one selected Manager/CLI/TCP run and its preserved evidence directory."""

    enrollment_ready = staticmethod(enrollment_ready)
    observation_sequence = staticmethod(observation_sequence)

    def __init__(self, owned, variants, *, emulator, base_config, limit, source_cut="15727ec"):
        self.owned = Path(owned).resolve()
        self.variants = tuple(variants)
        assert len(self.variants) == 2 and all(v in {"red", "blue", "yellow"} for v in self.variants)
        self.emulator = Path(emulator).resolve()
        self.base_config = Path(base_config).resolve()
        self.limit = limit
        assert type(limit) in (int, float) and 0 < limit <= 1800
        self.source_cut = source_cut
        self.patch = MonkeyPatch()
        self.client = self.runtime = self.listener = None
        self.handlers = set()
        self.handler_errors = []
        self.jobs = []
        self.downloads = {}
        self._owns_output = False
        self.outcome = {"status": "HOLD", "variants": self.variants,
                        "owned": str(self.owned), "source_cut": source_cut,
                        "limit_seconds": limit, "human_inputs_only": True}

    async def __aenter__(self):
        try:
            await self.start()
        except BaseException as error:
            self.outcome["error"] = f"{type(error).__name__}: {error}"
            await self.finish()
            raise
        return self

    async def __aexit__(self, kind, error, traceback):
        if error is not None:
            self.outcome["status"] = "HOLD"
            self.outcome["error"] = f"{kind.__name__}: {error}"
        await self.finish()
        assert self.outcome["status"] != "HOLD", "selected run audit/cleanup HOLD"

    def _preflight(self):
        assert self.owned.is_relative_to((ROOT / ".cache").resolve()), "owned output must be under RC cache"
        assert not self.owned.exists() and not (self.owned.parent / f"{self.owned.name}-summary.json").exists()
        assert self.emulator.is_file() and self.base_config.is_file()
        source_files = ("tools/launch_bizhawk.py", "server/bizhawk_launch.py",
                        "server/runtime_launcher.py", "server/manager.py", "server/gen1_run_config.py",
                        "server/server.py", "tests/live/test_gen1_native_selected_fresh.py",
                        "tests/live/gen1_selected_scenario.py")
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        assert subprocess.run(["git", "merge-base", "--is-ancestor", self.source_cut, head],
                              cwd=ROOT, check=False).returncode == 0
        # Product source is pinned independently of this tracked scenario module.
        assert subprocess.run(["git", "diff", "--quiet", self.source_cut, "--", *source_files[:-1]],
                              cwd=ROOT, check=False).returncode == 0
        self.outcome.update(source_head=head, source_files={name: sha(ROOT / name) for name in source_files},
                            emulator=str(self.emulator), base_config=str(self.base_config))
        self.owned.mkdir(parents=True, exist_ok=False)
        self._owns_output = True

    async def start(self):
        """Explicit physical action; never called by test collection or import."""
        from server import manager
        from server.gen1_run_config import open_runtime
        from server.server import SLinkServer
        from tests.live.test_gen1_native_selected_fresh import selected_manager

        self._preflight()
        self.client, run, run_dir, session_id = await selected_manager(self.owned, self.variants, self.patch)
        self.runtime = open_runtime(run_dir)
        server = SLinkServer(data_dir=str(run_dir), gen1_runtime=self.runtime)

        async def owned_client(reader, writer):
            try:
                await server.handle_client(reader, writer)
            except BaseException as error:
                self.handler_errors.append({"handler": f"{type(error).__name__}: {error}"})
            finally:
                self.handlers.discard(asyncio.current_task())

        def accepted_client(reader, writer):
            self.handlers.add(asyncio.create_task(owned_client(reader, writer)))

        self.listener = await asyncio.start_server(accepted_client, "127.0.0.1", 0, limit=4 * 1024 * 1024)
        server._tcp_port = self.listener.sockets[0].getsockname()[1]
        records = manager._load_registry()
        assert len(records) == 1 and records[0]["run_id"] == run["run_id"]
        records[0]["tcp_port"] = server._tcp_port
        manager._save_registry(records)
        self.outcome["manager"] = {"run_id": run["run_id"], "session_id": session_id,
                                   "tcp_port": server._tcp_port, "run_directory": str(run_dir)}
        for player, variant in zip(("a", "b"), self.variants, strict=True):
            endpoint = f"/api/runs/{run['run_id']}/launcher/{player}"
            plain = await self.client.get(endpoint)
            assert plain.status == 200
            launcher = (await plain.text()).encode()
            response = await self.client.get(endpoint + "?bundle=1")
            assert response.status == 200
            raw = await response.read()
            destination = self.owned / "downloads" / player
            destination.mkdir(parents=True)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                assert set(archive.namelist()) == {"launch.json", "launcher.lua", "README.txt"}
                for name in archive.namelist():
                    (destination / name).write_bytes(archive.read(name))
            (destination / "bundle.zip").write_bytes(raw)
            assert (destination / "launcher.lua").read_bytes() == launcher
            manifest = destination / "launch.json"
            spec = json.loads(manifest.read_text())
            assert spec["run_id"] == session_id and spec["player"] == player
            assert spec["launcher_sha256"] == hashlib.sha256(launcher).hexdigest()
            rom = run_dir / "prepared/final" / player / f"slink_{variant}.gb"
            assert hashlib.sha1(rom.read_bytes()).hexdigest() == spec["rom_sha1"]
            self.downloads[player] = {"manifest": manifest, "rom": rom}
            self.outcome.setdefault("downloads", {})[player] = {
                "bundle_sha256": hashlib.sha256(raw).hexdigest(),
                "members": {name: sha(destination / name) for name in
                            ("launch.json", "launcher.lua", "README.txt")}, "rom_sha256": sha(rom)}
        base = json.loads(self.base_config.read_text(encoding="utf-8-sig"))
        before = {key: base[key] for key in ("FrameSkip", "AutoMinimizeSkipping",
                  "AutoLoadLastSaveSlot", "AutoSaveLastSaveSlot", "AutosaveSaveRAM")}
        assert before == {"FrameSkip": 4, "AutoMinimizeSkipping": True,
                          "AutoLoadLastSaveSlot": False, "AutoSaveLastSaveSlot": False,
                          "AutosaveSaveRAM": False}, before
        base["FrameSkip"] = 0
        base["AutoMinimizeSkipping"] = False
        private_config = self.owned / "base-config.ini"
        private_config.write_text(json.dumps(base, indent=2) + "\n")
        self.outcome["input_hashes"] = {"emulator": sha(self.emulator), "source_config": sha(self.base_config),
                                        "private_config": sha(private_config)}
        for player in ("a", "b"):
            entry = self.downloads[player]
            argv = [sys.executable, str(ROOT / "tools/launch_bizhawk.py"),
                    "--manifest", str(entry["manifest"]), "--rom", str(entry["rom"]),
                    "--emuhawk", str(self.emulator), "--base-config", str(private_config),
                    "--root", str(self.owned / "clients")]
            log = self.owned / f"{player}.log"
            with log.open("wb") as output:
                process = subprocess.Popen(argv, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            job = {"player": player, "argv": argv, "process": process, "owned": self.owned,
                   "identity": None, "children": {}, "log": str(log)}
            self.jobs.append(job)
            job["identity"] = stamp(psutil.Process(process.pid))
            observe(job)
        assert self.jobs[0]["identity"] != self.jobs[1]["identity"]

    async def wait(self, ready, *, poll=0.25):
        """Checked snapshot polling; ready sees components and pending IDs only."""
        assert self.runtime is not None and 0 < poll <= 1
        deadline = time.monotonic() + self.limit
        announced = False
        last_progress = 0.0
        while time.monotonic() < deadline:
            for job in self.jobs:
                if observe(job) is not None:
                    raise RuntimeError(f"{job['player']} CLI exited before readiness; see {job['log']}")
            if not announced:
                try:
                    child_ids = {job["player"]: emulator_child(job, self.emulator) for job in self.jobs}
                except AssertionError:
                    child_ids = None
                if child_ids is not None:
                    (self.owned / "ready-for-human.json").write_text(json.dumps({
                        "stage": "ready-for-human-new-game", "at": time.time(),
                        "manager": self.outcome["manager"], "emulator_children": child_ids,
                        "instruction": "Use normal New Game inputs in both emulator windows"}, indent=2) + "\n")
                    announced = True
            components = self.runtime.journal.snapshot().state.get("components", {})
            pending = {player: self.runtime.journal.pending_ids(player) for player in ("a", "b")}
            now = time.monotonic()
            if now - last_progress >= 5:
                progress(self.owned, "awaiting-scenario", manager=self.outcome["manager"],
                         ready_for_human=announced, pending_ids=pending,
                         components={name: sorted(components.get(name, {})) for name in (
                             "gen1-native-reattach", "gen1-initial-observations",
                             "gen1-new-game-bootstrap", "gen1-initial-save")},
                         elapsed_seconds=round(self.limit - (deadline - now), 1))
                last_progress = now
            if ready(components, pending):
                rows = checked_events(self.runtime)
                for player in ("a", "b"):
                    observation_sequence(rows, player)
                if self.runtime.service_current():
                    return rows
            await asyncio.sleep(poll)
        raise TimeoutError("selected scenario readiness timed out")

    def audit_enrollment(self, rows):
        """One-time initial-save image check, before any later scenario save."""
        assert self.runtime is not None
        document = self.runtime.state().document()
        players = {job["player"]: private_receipt(
            job, json.loads(self.downloads[job["player"]]["manifest"].read_text()),
            self.downloads[job["player"]]["rom"], self.emulator) for job in self.jobs}
        evidence = audit_enrollment(self.runtime, document, {
            player: Path(players[player]["save_directory"]) for player in ("a", "b")},
            {job["player"]: job for job in self.jobs}, rows, self.emulator)
        self.outcome["enrollment"] = {"document": document, "players": players, "evidence": evidence}
        return evidence

    def audit_scenario(self, name, evidence):
        """Store a later scenario's own result without rechecking initial save bytes."""
        assert self.outcome.get("enrollment") is not None
        assert name not in self.outcome.setdefault("scenario_results", {})
        self.outcome["scenario_results"][name] = evidence

    async def finish(self):
        self.outcome["jobs"] = [{key: job[key] for key in ("player", "argv", "identity", "log")}
                                | {"pid": job["process"].pid, "children": list(job["children"].values())}
                                for job in self.jobs]
        self.outcome["cleanup"] = {job["player"]: cleanup_observed_job(job) for job in reversed(self.jobs)}
        self.outcome["survivors"] = []
        self.outcome["survivor_audit_unknown"] = []
        for job in self.jobs:
            for identity in list(job["children"].values()) + ([job["identity"]] if job["identity"] else []):
                try:
                    if matching(identity) is not None:
                        self.outcome["survivors"].append(identity)
                except BaseException as error:
                    self.outcome["survivor_audit_unknown"].append({**identity, "error": str(error)})
        errors = self.outcome.setdefault("resource_cleanup_errors", [])
        try:
            await drain_owned_handlers(self.listener, self.handlers, errors)
        except BaseException as error:
            errors.append({"owned_handlers_drain": f"{type(error).__name__}: {error}"})
        errors.extend(self.handler_errors)
        for name, action in (("runtime", lambda: self.runtime.close() if self.runtime is not None else None),
                             ("patch", self.patch.undo)):
            try:
                action()
            except BaseException as error:
                errors.append({name: str(error)})
        if self.client is not None:
            try:
                await self.client.close()
            except BaseException as error:
                errors.append({"manager_client": str(error)})
        if cleanup_requires_hold(self.outcome):
            self.outcome["status"] = "HOLD"
        if "input_hashes" in self.outcome:
            try:
                self.outcome["source_config_after"] = sha(self.base_config)
                if self.outcome["source_config_after"] != self.outcome["input_hashes"]["source_config"]:
                    self.outcome["status"] = "HOLD"
            except BaseException as error:
                self.outcome["status"] = "HOLD"
                self.outcome["config_audit_error"] = str(error)
        if self._owns_output:
            summary = self.owned.parent / f"{self.owned.name}-summary.json"
            summary.write_text(json.dumps(self.outcome, indent=2, default=str) + "\n")
            if self.outcome["status"] == "HOLD":
                progress(self.owned, "HOLD", summary=str(summary), error=self.outcome.get("error"))
        return self.outcome
