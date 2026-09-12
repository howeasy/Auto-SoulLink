"""Actual HTTP launcher + server: normal New Game evidence reaches the durable handler once.

Cold boot with a blank SaveRAM and normal menu inputs; the client acquires its one host,
enrolls, and publishes exactly one raw bootstrap receipt. Legacy overworld fixtures
never witness New Game and must publish nothing while keeping their hold.
"""

import asyncio
import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server.gen1_bootstrap_runtime import COMPONENT
from server.gen1_initial_observation import COMPONENT as INITIAL, blocker
from server.gen1_run_config import configure_runtime, create_runtime
from server.server import SLinkServer, build_app
from tests.unit.test_gen1_sessions import contract
from tools.run_gb_gate import BIZHAWK_CONFIG, BUILD, run_gate
from tools.verify_canonical_sources import verify

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("SLINK_LIVE") != "1", reason="explicit live emulator lane required"
    ),
]


def publish(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def enrollment_fixture(variant, directory, player):
    # Same valid physical save the held-launcher regression prepares; not rule state.
    from server.gen1_full_save import SYMBOLS, layout
    from server.gen1_party_codec import PartyCodec
    from tests.unit.test_gen1_party_codec import make_blob

    data = bytearray((ROOT / f"tests/fixtures/gen1/{variant}_town.SaveRAM").read_bytes())
    info = layout(variant)
    offset = info["regions"]["party"]["target"]
    symbols = SYMBOLS["pokeyellow" if variant == "yellow" else "pokered"]
    player_id = info["regions"]["main"]["target"] + symbols["wPlayerID"] - symbols["wMainDataStart"]
    blob = make_blob(
        PartyCodec(variant),
        species=data[offset + 8],
        level=data[offset + 41],
        dv=0x1234,
        otid=int.from_bytes(data[player_id : player_id + 2], "big"),
    )
    party = bytearray(404)
    party[:3] = bytes((1, blob[0], 255))
    party[8:52] = blob[:44]
    party[272:283] = blob[44:55]
    party[338:349] = blob[55:]
    data[offset : offset + 404] = party
    data[info["checksum"]] = (255 - sum(data[info["start"] : info["end"]])) & 255
    fixture = directory / f"initial-{player}.SaveRAM"
    fixture.write_bytes(data)
    return fixture


def run_bootstrap_pair(variants, *, cold_boot):
    assert not verify()["failures"]

    async def scenario():
        directory = Path(tempfile.mkdtemp(prefix="gen1-bootstrap-launcher-", dir=ROOT / ".cache"))
        run_id = secrets.token_hex(16)
        players = dict(zip(("a", "b"), variants, strict=True))
        private = json.loads(Path(BIZHAWK_CONFIG).read_text(encoding="utf-8-sig"))
        private["Rewind"]["Enabled"] = False
        config = directory / "base-config.ini"
        config.write_text(json.dumps(private))
        gate_name = "test_gen1_bootstrap_launcher_gate"
        source = (ROOT / f"lua/tests/{gate_name}.lua").read_text()
        jobs, listener, web = [], None, None
        runtime = None

        async def wait(name, player, seconds):
            file = directory / f"{name}-{player}.json"
            deadline = asyncio.get_running_loop().time() + seconds
            while asyncio.get_running_loop().time() < deadline:
                if file.exists():
                    return json.loads(file.read_text())
                for job in jobs:
                    if job.done():
                        passed, path, log = await job
                        raise AssertionError(f"emulator exited before {name}: {passed} {path}\n{log}")
                await asyncio.sleep(0.02)
            raise AssertionError(f"launcher test timed out waiting for {name}-{player}")

        try:
            for p, variant in players.items():
                if cold_boot:
                    fixture = directory / f"blank-{p}.SaveRAM"
                    fixture.write_bytes(b"\xff" * 0x8000)
                else:
                    fixture = enrollment_fixture(variant, directory, p)
                script = directory / f"gate-{p}.lua"
                script.write_text(
                    source.replace(
                        f'G.start("{gate_name}"',
                        f'G.start("{directory.name.replace("-", "_")}_{p}"',
                    )
                )
                spec = directory / f"input-{p}.json"
                publish(
                    spec,
                    {
                        "directory": directory.as_posix(),
                        "run_id": run_id,
                        "player": p,
                        "launcher": (directory / f"download-{p}.lua").as_posix(),
                        "cold_boot": cold_boot,
                    },
                )
                jobs.append(
                    asyncio.create_task(
                        asyncio.to_thread(
                            run_gate,
                            script.relative_to(ROOT).as_posix(),
                            rom_key=variant,
                            timeout=420 if cold_boot else 85,
                            quiet=True,
                            config_base=str(config),
                            fixture_override=str(fixture),
                            extra_env={
                                "SLINK_LAUNCHER_TEST_INPUT": str(spec),
                                "SLINK_CLIENT_STORAGE_ROOT": str(directory / "client-data"),
                            },
                        )
                    )
                )
            observed = {p: await wait("observed", p, 55) for p in players}
            assert all(row["cold_boot"] is cold_boot for row in observed.values())
            expected = contract(*variants)
            runtime = create_runtime(directory, expected, run_id=run_id)
            snap = runtime.journal.snapshot()
            assert not snap.state["rules"]["core"]["player_identity"]
            configure_runtime(runtime)
            srv = SLinkServer(data_dir=str(directory), gen1_runtime=runtime)
            listener = await asyncio.start_server(
                srv.handle_client, "127.0.0.1", 0, limit=4 * 1024 * 1024
            )
            srv._tcp_port = listener.sockets[0].getsockname()[1]
            web = TestClient(TestServer(build_app(srv)))
            await web.start_server()
            for p in players:
                response = await web.get("/launcher/" + p)
                assert response.status == 200
                (directory / f"download-{p}.lua").write_text(await response.text())
            publish(directory / "go.json", {"ready": True})
            ready = {p: await wait("ready", p, 400 if cold_boot else 55) for p in players}
            if cold_boot:
                deadline = asyncio.get_running_loop().time() + 45
                while True:
                    saves = runtime.journal.snapshot().state["components"].get("gen1-initial-save", {})
                    if set(saves) == set(players) and all(row["receipt_operation"] for row in saves.values()):
                        break
                    if asyncio.get_running_loop().time() >= deadline:
                        raise AssertionError("normal launcher initial save did not obtain its file receipt")
                    for job in jobs:
                        if job.done():
                            passed, path, log = await job
                            raise AssertionError(f"emulator exited before initial save: {passed} {path}\n{log}")
                    await asyncio.sleep(0.05)
            document = runtime.state().document()
            state = runtime.state()
            for p, result in ready.items():
                status = result["status"]
                assert result["actual_generated_launcher"]
                assert result["held_frame"] == result["frame_after"]
                assert status["run_id"] == run_id and status["player"] == p
                assert not status["ordinary_execution"]
                assert status["initial_observation"] == "acknowledged"
                assert status["host"]["physical_stop_verified"]
                for attempt in range(50):
                    try:
                        saved = json.loads(Path(status["journal_path"]).read_text())["document"]
                        break
                    except PermissionError:
                        if attempt == 49:
                            raise
                        await asyncio.sleep(0.02)
                assert saved["binding"]["run_id"] == run_id and saved["binding"]["player"] == p
                assert not saved["payload"]["inbox"]
                # One host per process: the client's own hold is the only owner.
                assert status["host"]["owner_id"] == status["context"]["physical_instance"]
                if cold_boot:
                    # Lua drops nil-valued keys on encode: absent means "not failed".
                    assert status["bootstrap"]["complete"] and status["bootstrap"].get("failed") is None
                    assert status.get("bootstrap_observation") == "acknowledged"
                    assert result["frames_driven"] > 0
                    cursor = saved["payload"]["observation"]["bootstrap"]
                    assert cursor["phase"] == "acknowledged"
                    raw = cursor["payload"]["payload"]
                    recorded = document["components"][COMPONENT][p]
                    assert recorded["payload"] == raw  # the wire carried the raw receipt
                    assert recorded["operation_id"] == cursor["operation_id"]
                    proof = recorded["proof"]
                    assert proof["entry_frame"] < proof["return_frame"] <= proof["frame"]
                    assert proof["frame"] == document["components"][INITIAL][p]["observation"]["frame"]
                    assert raw["context_generation"] == status["context"]["context_generation"]
                    assert raw["physical_instance"] == status["context"]["physical_instance"]
                    save = document["components"]["gen1-initial-save"][p]
                    saved_event = runtime.journal.event_snapshot(p, save["receipt_operation"])
                    saved_receipt = saved_event.request["receipt"]
                    save_path = Path(saved_receipt["file"]["path"]).resolve()
                    assert save_path.parent.name == "SaveRAM"
                    assert save_path.is_relative_to(Path(BUILD).resolve())
                    assert save_path != (directory / f"blank-{p}.SaveRAM").resolve()
                    actual_file = save_path.read_bytes()
                    assert actual_file.hex().upper() == saved_receipt["after"]["cart_hex"]
                    assert hashlib.sha256(actual_file).hexdigest() == saved_receipt["file"]["sha256"]
                    assert saved_receipt["after"]["fields"] == document["components"][INITIAL][p]["observation"]["source"]["fields"]
                    assert saved_receipt["after"]["save_status"] == 2
                    labels = {Path(shot).name.split("-", 1)[1] for shot in result["screenshots"]}
                    assert labels == {"intro.png", "held-checkpoint.png"}
                    for shot in result["screenshots"]:
                        assert Path(shot).is_file() and Path(shot).stat().st_size > 0
                    assert (
                        Path(result["screenshots"][0]).read_bytes()
                        != Path(result["screenshots"][1]).read_bytes()
                    )
                else:
                    assert status["bootstrap"]["started"] is False
                    assert status["bootstrap"]["complete"] is False
                    assert status["bootstrap"].get("failed") is None
                    assert status.get("bootstrap_observation") is None  # nil key is absent
                    assert "bootstrap" not in saved["payload"]["observation"]
                    assert COMPONENT not in document["components"]
                assert blocker(run_id, p) in state.barrier.document()["blockers"]
            # Exact initial saves finish; gameplay remains held with no new links.
            assert not document["identities"]["members"] and not document["rules"]["core"]["links"]
            assert state.barrier.ticket() is None
            assert not runtime.journal.pending_ids("a") and not runtime.journal.pending_ids("b")
            if cold_boot:
                for p in players:
                    fixture = directory / f"blank-{p}.SaveRAM"
                    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == hashlib.sha256(
                        b"\xff" * 0x8000
                    ).hexdigest()
            publish(directory / "finish.json", {"done": True})
            for job in jobs:
                passed, path, log = await job
                assert passed, f"{path}\n{log[-4000:]}"
            if cold_boot:
                paths = []
                for p in players:
                    shot = directory / f"{p}-initial-save-complete.png"
                    assert shot.is_file() and shot.stat().st_size > 0
                    entry = document["components"]["gen1-initial-save"][p]
                    event = runtime.journal.event_snapshot(p, entry["receipt_operation"])
                    paths.append(Path(event.request["receipt"]["file"]["path"]).resolve())
                assert paths[0] != paths[1]
        finally:
            if web is not None:
                await web.close()
            if listener is not None:
                listener.close()
                await listener.wait_closed()
            if runtime is not None:
                runtime.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "variants",
    [("yellow", "yellow"), ("red", "blue"), ("blue", "yellow")],
    ids=lambda pair: "-".join(pair),
)
def test_generated_launcher_publishes_one_raw_new_game_receipt_from_a_normal_cold_boot(variants):
    run_bootstrap_pair(variants, cold_boot=True)


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue")], ids=lambda pair: "-".join(pair))
def test_legacy_fixture_launch_retains_hold_and_never_synthesizes_bootstrap_history(variants):
    run_bootstrap_pair(variants, cold_boot=False)
