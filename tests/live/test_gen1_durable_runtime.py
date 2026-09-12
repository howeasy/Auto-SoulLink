"""Actual RBY hosts/LuaSocket/journals stay held while the production TCP route works."""

import asyncio
import json
import os
import secrets
import tempfile
from pathlib import Path

import pytest

from server.adapters import get_adapter
from server.gen1_command_receipts import Gen1ReceiptPolicy, validate_party_snapshot
from server.gen1_party_codec import PartyCodec
from server.gen1_runtime import Gen1Runtime
from server.gen1_runtime_state import Gen1RuntimeState
from server.gen1_staged_state import StagedGen1State
from server.identity_registry import IdentityRegistry
from server.protocol_journal import JournalError
from server.server import SLinkServer
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo, SoulLinkState
from tests.unit.test_gen1_party_codec import make_blob
from tests.unit.test_gen1_sessions import contract
from tools.run_gb_gate import BIZHAWK_CONFIG, run_gate

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
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


@pytest.mark.parametrize(
    "variants", [("yellow", "yellow"), ("red", "blue")], ids=["yellow-yellow", "red-blue"]
)
def test_actual_paired_runtime_delivers_durably_without_advancing_held_games(variants):
    async def scenario():
        directory = Path(tempfile.mkdtemp(prefix="gen1-runtime-live-", dir=ROOT / ".cache"))
        run_id = secrets.token_hex(16)
        players = dict(zip(("a", "b"), variants, strict=True))
        private_config = directory / "base-config.ini"
        configuration = json.loads(Path(BIZHAWK_CONFIG).read_text(encoding="utf-8-sig"))
        configuration["Rewind"]["Enabled"] = False
        private_config.write_text(json.dumps(configuration))
        holder, jobs = {}, []

        async def handler(reader, writer):
            if "server" not in holder:
                writer.close()
                await writer.wait_closed()
                return
            await holder["server"].handle_client(reader, writer)

        listener = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = listener.sockets[0].getsockname()[1]
        source = (ROOT / "lua/tests/test_gen1_durable_runtime_gate.lua").read_text()
        keys = {}
        runtime = None

        async def read_ready(name, player):
            path = directory / f"{name}-{player}.json"
            deadline = asyncio.get_running_loop().time() + 55
            while asyncio.get_running_loop().time() < deadline:
                if path.exists():
                    return json.loads(path.read_text())
                for job in jobs:
                    if job.done():
                        passed, result, log = await job
                        raise AssertionError(
                            f"emulator exited before {name}-{player}: {passed} {result}\n{log}"
                        )
                await asyncio.sleep(0.02)
            raise AssertionError(f"timed out waiting for {name}-{player}")

        try:
            for p, variant in players.items():
                raw = make_blob(PartyCodec(variant), dv=0x1000, otid=0)
                keys[p] = PartyCodec(variant).validate_blob(raw).key
                spec = directory / f"input-{p}.json"
                publish(
                    spec,
                    {
                        "directory": directory.as_posix(),
                        "run_id": run_id,
                        "player": p,
                        "port": port,
                        "blob": raw.hex().upper(),
                        "key": keys[p],
                    },
                )
                script = directory / f"client-{p}.lua"
                name = (directory.name + "_" + p).replace("-", "_")
                script.write_text(
                    source.replace(
                        'G.start("test_gen1_durable_runtime_gate")', f'G.start("{name}")'
                    )
                )
                jobs.append(
                    asyncio.create_task(
                        asyncio.to_thread(
                            run_gate,
                            script.relative_to(ROOT).as_posix(),
                            rom_key=variant,
                            timeout=80,
                            quiet=True,
                            config_base=str(private_config),
                            extra_env={"SLINK_DURABLE_RUNTIME_INPUT": str(spec)},
                        )
                    )
                )
            observed = {p: await read_ready("observed", p) for p in players}
            assert observed["a"]["host"]["process_id"] != observed["b"]["host"]["process_id"]
            assert observed["a"]["save_path"] != observed["b"]["save_path"]
            rules = SoulLinkState(
                data_dir=str(directory), adapter=get_adapter("gen1_rby", rom_type=variants[0])
            )
            rules.rom_type = variants[0]
            halves = {}
            for p, value in observed.items():
                mons = validate_party_snapshot(value["snapshot"], variant=players[p])
                assert mons[0].key == keys[p] and value["host"]["physical_stop_verified"]
                rules.player_identity[p] = value["context"]["save_identity"]
                halves[p] = MonInfo(mons[0].key, mons[0].level, mons[0].species_id, "NICK")
                rules.party_keys[p] = {mons[0].key}
                rules.party_size[p] = 1
                rules.pokeballs_obtained[p] = True
                rules._has_helld.add(p)
                rules._ingest_party_blobs(
                    p,
                    [
                        {
                            "slot": 0,
                            "key": mons[0].key,
                            "species_id": mons[0].species_id,
                            "level": mons[0].level,
                            "blob_hex": mons[0].raw.hex(),
                        }
                    ],
                )
            pair = LinkEntry("oaks_lab", halves["a"], halves["b"], LinkStatus.ALIVE)
            rules.links.append(pair)
            rules._index_entry(pair)
            rules.area_states["oaks_lab"] = AreaStatus.LINKED
            document = StagedGen1State.from_live(rules, {"retired_pairs": []}).document()
            spec = contract(*variants)
            initial = Gen1RuntimeState.initial(
                document, IdentityRegistry(run_id).document(), spec, data_dir=directory
            )

            def validate_event(player, event, state):
                # Deliberate transport-test stimulus, not observed gameplay proof.
                if player != "a" or event != {"event": "faint", "key": keys[player]}:
                    raise JournalError("unsupported live transport fixture event")

            runtime = Gen1Runtime(
                directory / "runtime.sqlite3",
                contract=spec,
                data_dir=directory,
                run_id=run_id,
                initial_state=initial,
                validate_event=validate_event,
                validate_receipt=Gen1ReceiptPolicy(players),
                verify_reconciliation=lambda *args: None,
            )
            holder["server"] = SLinkServer(data_dir=str(directory), gen1_runtime=runtime)
            publish(directory / "go.json", {"start": True})
            ready = {p: await read_ready("ready", p) for p in players}
            assert runtime.rule_state().links[0].status == LinkStatus.DEAD
            assert runtime.state().barrier.ticket() is None
            for p, result in ready.items():
                assert result["frame_before"] == result["frame_after"] == observed[p]["frame"]
                assert result["wram_unchanged"] and result["applied"] == 0
                assert (
                    result["host"]["physical_stop_verified"]
                    and not result["physical_execution_qualified"]
                )
            obligations = [
                entry
                for entry in ready["b"]["state"]["inbox"]
                if entry["body"]["cmd"] == "force_faint"
            ]
            assert len(obligations) == 1 and "outcome" not in obligations[0]
            stored = runtime.journal.command("b", obligations[0]["command_id"])
            assert stored["body"] == obligations[0]["body"]["body"] and stored["outcome"] is None
            assert not any(
                row["operation_id"] == ready["a"]["operation_id"]
                for row in ready["a"]["state"]["outbox"]
            )
            publish(
                directory / "verified.json",
                {
                    "variants": players,
                    "endpoints": ready,
                    "transport": "actual LuaSocket/TCP",
                    "authoritative_rule_state": "ProtocolJournal",
                    "ordinary_frames": 0,
                    "physical_writes": 0,
                    "production_launch_qualified": False,
                },
            )
            publish(directory / "finish.json", {"finish": True})
            for job in jobs:
                passed, path, log = await job
                assert passed, f"{path}\n{log[-6500:]}"
        finally:
            publish(directory / "finish.json", {"finish": True})
            listener.close()
            await listener.wait_closed()
            await asyncio.gather(*jobs, return_exceptions=True)
            if runtime is not None:
                for _ in range(100):
                    if not runtime._writers:
                        break
                    await asyncio.sleep(0.01)
                runtime.close()

    asyncio.run(scenario())
