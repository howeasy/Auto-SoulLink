"""Actual HTTP launcher downloads start separate, held RBY client services."""

import asyncio
import json
import os
import secrets
import tempfile
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server.adapters import get_adapter
from server.gen1_command_receipts import Gen1ReceiptPolicy
from server.gen1_run_config import configure_runtime, create_runtime
from server.gen1_runtime import Gen1Runtime
from server.gen1_runtime_state import Gen1RuntimeState,state_type_for
from server.gen1_staged_state import StagedGen1State
from server.identity_registry import IdentityRegistry
from server.protocol_journal import JournalError
from server.server import SLinkServer, build_app
from server.state import SoulLinkState
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
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


@pytest.mark.parametrize(
    "variants,tampered",
    [(("yellow", "yellow"), False), (("red", "blue"), False), (("yellow", "yellow"), True)],
    ids=["yellow-yellow", "red-blue", "bundle-mismatch"],
)
def test_http_launcher_boots_run_bound_owned_clients_and_preserves_pending_commands(
    variants, tampered
):
    run_launcher_pair(variants, tampered)


@pytest.mark.parametrize('variants',[('yellow','yellow'),('red','blue'),('blue','yellow')])
def test_fresh_run_launchers_enroll_actual_inventory_without_synthetic_gameplay_bootstrap(variants):
    run_launcher_pair(variants,enrollment=True)


@pytest.mark.parametrize('variants',[('yellow','yellow'),('red','blue'),('blue','yellow')])
def test_generated_held_launcher_executes_only_the_permitted_faint_without_frames(variants):
    run_launcher_pair(variants,enrollment=True,faint=True)


def test_generated_held_launcher_does_not_write_when_server_withholds_permission():
    run_launcher_pair(('yellow','yellow'),enrollment=True,faint=True,withhold=True)


def run_launcher_pair(variants, tampered=False, *, companion=False,randomized=False,enrollment=False,faint=False,withhold=False,memorial=False,memorial_fault=None,reconnect_memorial=False,factory=False):
    async def scenario():
        directory = Path(tempfile.mkdtemp(prefix="gen1-launcher-", dir=ROOT / ".cache"))
        run_id = secrets.token_hex(16)
        runner=run_gate
        if factory:
            from tests.live.bizhawk_factory_fixture import run_factory_gate
            runner=run_factory_gate
        players = dict(zip(("a", "b"), variants, strict=True))
        private = json.loads(Path(BIZHAWK_CONFIG).read_text(encoding="utf-8-sig"))
        private["Rewind"]["Enabled"] = False
        config = directory / "base-config.ini"
        config.write_text(json.dumps(private))
        source = (ROOT / "lua/tests/test_gen1_launcher_gate.lua").read_text()
        jobs, runtime, listener, web = [], None, None, None
        cartridges=None
        if randomized:
            from server.gen1_upr_pipeline import prepare_pair
            from server.gen1_prepared_cartridges import PreparedCartridges
            from server.gen1_upr_policy import build_preset
            from tests.integration.test_upr_pinned import PRESETS,user_jar
            paths={p:ROOT/f"patch/build/gen1_{v}{'.gbc' if v=='yellow' else '.gb'}" for p,v in players.items()}
            prepare_pair(user_jar(),build_preset(PRESETS["combined"]),paths,directory/"artifacts",
                seeds={"a":"123456789","b":"987654321"})
            cartridges=PreparedCartridges(directory/"artifacts")

        async def wait(name, player):
            file = directory / f"{name}-{player}.json"
            deadline = asyncio.get_running_loop().time() + 55
            while asyncio.get_running_loop().time() < deadline:
                if file.exists():
                    return json.loads(file.read_text())
                for job in jobs:
                    if job.done():
                        passed, path, log = await job
                        raise AssertionError(
                            f"emulator exited before {name}: {passed} {path}\n{log}"
                        )
                await asyncio.sleep(0.02)
            raise AssertionError("launcher test timed out")

        try:
            for p, variant in players.items():
                fixture=None
                if enrollment:
                    # The older held-only fixture has inconsistent party XP; it
                    # never passed through a semantic party codec. Prepare a valid
                    # physical save before boot, not synthetic server rule state.
                    from server.gen1_full_save import SYMBOLS,layout
                    from server.gen1_party_codec import PartyCodec
                    from tests.unit.test_gen1_party_codec import make_blob
                    data=bytearray((ROOT/f'tests/fixtures/gen1/{variant}_town.SaveRAM').read_bytes())
                    info=layout(variant);offset=info['regions']['party']['target']
                    symbols=SYMBOLS['pokeyellow' if variant=='yellow' else 'pokered']
                    player_id=info['regions']['main']['target']+symbols['wPlayerID']-symbols['wMainDataStart']
                    blob=make_blob(PartyCodec(variant),species=data[offset+8],level=data[offset+41],
                                   dv=0x1234,otid=int.from_bytes(data[player_id:player_id+2],'big'))
                    party=bytearray(404);party[:3]=bytes((1,blob[0],255));party[8:52]=blob[:44]
                    party[272:283]=blob[44:55];party[338:349]=blob[55:]
                    if memorial:
                        second=make_blob(PartyCodec(variant),species=153,level=5,dv=0x5678)
                        party[:4]=bytes((2,blob[0],second[0],255));party[52:96]=second[:44]
                        party[283:294]=second[44:55];party[349:360]=second[55:]
                    data[offset:offset+404]=party;data[info['checksum']]=(255-sum(data[info['start']:info['end']]))&255
                    fixture=directory/f'initial-{p}.SaveRAM';fixture.write_bytes(data)
                script = directory / f"gate-{p}.lua"
                script.write_text(
                    source.replace(
                        'G.start("test_gen1_launcher_gate")',
                        f'G.start("{directory.name.replace("-", "_")}_{p}")',
                    )
                )
                spec = directory / f"input-{p}.json"
                publish(
                    spec,
                    {
                        "directory": directory.as_posix(),"run_id":run_id,
                        "player": p,
                        "launcher": (directory / f"download-{p}.lua").as_posix(),
                        "expect_mismatch": tampered,
                        "enrollment":enrollment,
                        "faint":faint,"withhold":withhold,"memorial":memorial,"memorial_fault":memorial_fault if p=="b" else None,
                    },
                )
                jobs.append(
                    asyncio.create_task(
                        asyncio.to_thread(
                            runner,
                            script.relative_to(ROOT).as_posix(),
                            rom_key=variant+("_companion" if companion else ""),
                            timeout=85,
                            quiet=True,
                            config_base=str(config),
                            fixture_override=str(fixture) if fixture else None,
                            cartridge_override={"path":str(cartridges.directory/cartridges.manifest(p)["output"]),
                                "sha256":cartridges.manifest(p)["companion"]["final_sha256"],
                                "saveram_name":"candidate.SaveRAM"} if cartridges else None,
                            extra_env={
                                "SLINK_LAUNCHER_TEST_INPUT": str(spec),
                                "SLINK_CLIENT_STORAGE_ROOT": str(directory / "client-data"),
                            },
                        )
                    )
                )
            observed = {p: await wait("observed", p) for p in players}
            rules = SoulLinkState(
                data_dir=str(directory), adapter=get_adapter("gen1_rby", rom_type=variants[0])
            )
            rules.rom_type = variants[0]
            rules.player_identity = {p: data["save_identity"] for p, data in observed.items()}
            document = StagedGen1State.from_live(rules, {"retired_pairs": []}).document()
            if cartridges:
                expected=cartridges.contract()
            elif companion:
                from server.gen1_admission import CONTRACT_SCHEMA, cartridge_metadata
                from server.gen1_cartridge_profiles import companion_profiles
                profiles = companion_profiles()
                expected = {"schema": CONTRACT_SCHEMA, "players": {p: cartridge_metadata(profiles[v]) for p,v in players.items()}}
            else:
                expected = contract(*variants)
            initial = state_type_for(cartridges).initial(
                document, IdentityRegistry(run_id).document(), expected, data_dir=directory
            )

            def unavailable(*args):
                raise JournalError("held launcher test accepts no gameplay observations")

            runtime = create_runtime(directory,expected,run_id=run_id,prepared_cartridges=cartridges) if enrollment else Gen1Runtime(
                directory / "runtime.sqlite3",
                contract=expected,
                data_dir=directory,
                run_id=run_id,
                initial_state=initial,
                validate_event=unavailable,
                validate_receipt=Gen1ReceiptPolicy(players),
                verify_reconciliation=lambda *args: None,
                prepared_cartridges=cartridges,
            )
            # Only legacy held-service qualification injects an obligation. The
            # enrollment case starts from the production factory's empty state.
            snap = runtime.journal.snapshot()
            if enrollment:
                assert not snap.state['rules']['core']['player_identity'] and not snap.state['identities']['members']
            else:runtime.journal.commit(
                "a",
                secrets.token_hex(16),
                {"event": "prepared_fixture_obligations"},
                expected_revision=snap.revision,
                state=snap.state,
                commands={p: [{"cmd": "launcher_qualification", "player": p}] for p in players},
                result={"ack": "ACK"},
            )
            configure_runtime(runtime)
            srv = SLinkServer(data_dir=str(directory), gen1_runtime=runtime)
            listener = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0,limit=4*1024*1024)
            srv._tcp_port = listener.sockets[0].getsockname()[1]
            web = TestClient(TestServer(build_app(srv)))
            await web.start_server()
            for p in players:
                response = await web.get("/launcher/" + p)
                assert response.status == 200
                text = await response.text()
                if tampered:
                    from server.gen1_launcher import configuration

                    fingerprint = configuration(runtime, p)["files"][0]["sha256"]
                    text = text.replace(fingerprint, "0" * 64)
                (directory / f"download-{p}.lua").write_text(text)
            publish(directory / "go.json", {"ready": True})
            if tampered:
                for job in jobs:
                    passed, path, log = await job
                    assert passed, f"{path}\n{log}"
                assert not runtime.gate.sessions and not (directory / "client-data").exists()
                publish(
                    directory / "verified.json",
                    {"bundle_mismatch_refused": True, "admitted": False, "journal_created": False},
                )
                return
            ready = {p: await wait("ready", p) for p in players}
            assert ready["a"]["status"]["journal_path"] != ready["b"]["status"]["journal_path"]
            assert (
                ready["a"]["status"]["host"]["process_id"]
                != ready["b"]["status"]["host"]["process_id"]
            )
            for p, result in ready.items():
                assert result["actual_generated_launcher"] and result["wram_unchanged"] and result['sram_unchanged']
                assert result["frame_before"] == result["frame_after"]
                status = result["status"]
                assert (
                    status["run_id"] == run_id
                    and status["player"] == p
                    and not status["ordinary_execution"]
                )
                for attempt in range(50):
                    try:
                        saved=json.loads(Path(status['journal_path']).read_text())['document']
                        break
                    except PermissionError:
                        if attempt==49:raise
                        await asyncio.sleep(.02)  # Owner's short atomic-replace file lock.

                assert saved["binding"]["run_id"] == run_id and saved["binding"]["player"] == p
                if enrollment:
                    from server.gen1_initial_observation import COMPONENT
                    recorded=runtime.state().document()['components'][COMPONENT][p]
                    assert status['initial_observation']=='acknowledged' and not saved['payload']['inbox']
                    assert recorded['inventory']['party_count']==(2 if memorial else 1)
                    assert recorded['inventory']['members'][0]['blob_hex']==observed[p]['blob']
                    assert not runtime.state().identities.document()['members']
                    assert not runtime.state().document()['rules']['core']['links']
                    assert runtime.state().barrier.ticket() is None
                else:
                    entry = saved["payload"]["inbox"][0]
                    assert entry["body"]["body"] == {"cmd": "launcher_qualification", "player": p}
                    assert "outcome" not in entry
                    assert runtime.journal.command(p, entry["command_id"])["outcome"] is None
            if faint:
                from tests.unit.held_faint_fixture import publish_death
                refused=[]
                if withhold:
                    def deny(*args):refused.append(True);return None
                    runtime.verify_operation_execution=deny
                phases=[];reconnected=[];fault_armed=[]
                if memorial:
                    original_verifier=runtime.verify_operation_execution
                    def observe_authority(player,command,evidence,state,binding):
                        phase=evidence.get('phase')
                        if phase:phases.append((player,phase))
                        if memorial_fault is not None and player=='b' and phase=='memorialize' and not fault_armed:
                            publish(directory/'memorial-fault-go.json',{'armed':True});fault_armed.append(True)
                        if reconnect_memorial and phase=='memorial_save' and not reconnected:
                            reconnected.append({p:s.session_id for p,s in runtime.gate.sessions.items()})
                            runtime.suspend('explicit same-core reconnect fixture before save permit')
                        return original_verifier(player,command,evidence,state,binding)
                    runtime.verify_operation_execution=observe_authority
                command=publish_death(runtime)
                if memorial:
                    publish(directory/'death-fixture.json',{'actor_faint':True})
                    results={p:await wait('memorial',p) for p in ('a','b')}
                    deadline=asyncio.get_running_loop().time()+20
                    while next(iter(runtime.state().document()['components']['gen1-faint-settlement']['deaths'].values()))['phase']!='memorial_complete':
                        assert asyncio.get_running_loop().time()<deadline,'paired memorial save ACK did not close'
                        await asyncio.sleep(.02)
                    for p in ('a','b'):
                        from server.gen1_memorial_runtime import expand_entry
                        entry=expand_entry(runtime.journal,runtime.state().document()['components']['gen1-memorial-settlement']['entries'][p][-1])
                        assert results[p]['point']==entry['payload']['after']
                        assert results[p]['unchanged_outside_owned_ranges']
                        proof=entry['receipt_event']['message']['receipt']['file']
                        assert Path(proof['path']).read_bytes()==bytes.fromhex(entry['payload']['after']['cart_hex'])
                    assert results['a']['save_path']!=results['b']['save_path']
                    if factory:
                        assert all(Path(results[p]['save_path']).parent==directory/'client-data'/run_id/p/'SaveRAM' for p in ('a','b'))
                    if memorial_fault is not None:
                        assert results['b']['repair_injected'] and ('b','memorial_repair') in phases
                    if reconnect_memorial:
                        assert reconnected and all(runtime.gate.sessions[p].session_id!=old for p,old in reconnected[0].items())
                else:
                    result=await wait('faint','b')
                    deadline=asyncio.get_running_loop().time()+15
                    while (not refused if withhold else runtime.journal.command('b',command['command_id'])['outcome'] is None):
                        assert asyncio.get_running_loop().time()<deadline,'faint ACK did not reach server'
                        await asyncio.sleep(.02)
                    assert result['sram_unchanged'] and result['status']['ordinary_execution'] is False
                    assert result['only_target_hp_changed'] is (not withhold)
                    assert runtime.journal.command('b',command['command_id'])['outcome']==(None if withhold else 'ACK')
                    assert runtime.state().barrier.ticket() is None
                    assert next(iter(runtime.state().document()['components']['gen1-faint-settlement']['deaths'].values()))['phase']==('pending_faint' if withhold else 'pending_memorial')
            publish(
                directory / "verified.json",
                {"players": ready, "mode": "held_service", "gameplay_qualified": False},
            )
            publish(directory / "finish.json", {"finish": True})
            for job in jobs:
                passed, path, log = await job
                assert passed, f"{path}\n{log}"
        finally:
            publish(directory / "finish.json", {"finish": True})
            if web:
                await web.close()
            if listener:
                listener.close()
                await listener.wait_closed()
            await asyncio.gather(*jobs, return_exceptions=True)
            if runtime:
                for _ in range(80):
                    if not runtime._writers:
                        break
                    await asyncio.sleep(0.01)
                runtime.close()

    asyncio.run(scenario())
