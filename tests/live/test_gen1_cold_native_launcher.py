"""Reproduced native cartridges obtain their party/history through real New Game."""

import asyncio
import contextlib
import hashlib
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server.gen1_launcher import configuration
from server.gen1_prepared_cartridges import PreparedCartridges
from server.gen1_run_config import create_runtime
from server.gen1_upr_pipeline import prepare_pair
from server.gen1_upr_policy import build_preset
from server.server import SLinkServer, build_app
from server.trade_coordinator import NAMESPACE
from tests.integration.test_upr_pinned import user_jar
from tests.live.test_gen1_bootstrap_launcher import publish
from tools.gen1_playthrough import staged_rom
from tools.run_gb_gate import BIZHAWK_CONFIG, run_gate

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.live, pytest.mark.slow,
              pytest.mark.skipif(os.environ.get('SLINK_LIVE') != '1', reason='explicit live emulator lane required')]


@pytest.mark.parametrize('variants', [('yellow', 'yellow'), ('red', 'blue')], ids=['yellow-yellow', 'red-blue'])
def test_real_new_game_starters_reach_composed_receptionist_and_native_trade(variants):
    asyncio.run(run_cold_native_pair(variants))


async def run_cold_native_pair(variants):
    directory = Path(tempfile.mkdtemp(prefix='cold-native-launcher-', dir=ROOT / '.cache'))
    players = dict(zip(('a', 'b'), variants, strict=True))
    sources = {player: ROOT / staged_rom(variant) for player, variant in players.items()}
    prepare_pair(user_jar(), build_preset({}), sources, directory / 'cartridges',
                 seeds={'a': '123456789', 'b': '987654321'})
    cartridges = PreparedCartridges(directory / 'cartridges')
    runtime = create_runtime(directory, cartridges.contract(), run_id=secrets.token_hex(16),
                             prepared_cartridges=cartridges, ordinary_frames=True, native_trade=True)
    server_timings = []
    process = runtime.process

    def timed_process(message, owner):
        started = time.perf_counter()
        try:
            return process(message, owner)
        finally:
            server_timings.append({'player': message.get('player'), 'operation': message.get('operation_id'),
                'event': message.get('event'), 'started': started, 'finished': time.perf_counter()})

    runtime.process = timed_process
    source_paths = {item['path'] for item in configuration(runtime, 'a')['files']}
    source_paths.update({'lua/tests/gen1_cold_trade_inputs.lua', 'lua/tests/test_gen1_cold_native_launcher_gate.lua',
                         'lua/tests/gen1_cold_timing.lua'})
    source_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(source_paths)}
    publish(directory / 'source-closure-before.json', source_hashes)
    host_config = json.loads(Path(BIZHAWK_CONFIG).read_text(encoding='utf-8-sig'))
    host_config['Rewind']['Enabled'] = False
    config = directory / 'host.ini'
    config.write_text(json.dumps(host_config))
    server = SLinkServer(data_dir=str(directory), gen1_runtime=runtime)
    listener = await asyncio.start_server(server.handle_client, '127.0.0.1', 0, limit=4 * 1024 * 1024)
    server._tcp_port = listener.sockets[0].getsockname()[1]
    web = TestClient(TestServer(build_app(server)))
    await web.start_server()
    jobs = []
    try:
        for player, variant in players.items():
            response = await web.get('/launcher/' + player)
            assert response.status == 200
            launcher = directory / f'launcher-{player}.lua'
            text = await response.text()
            assert 'native_manifest' in text and 'ordinary_frames' in text
            launcher.write_text(text)
            blank = directory / f'blank-{player}.SaveRAM'
            blank.write_bytes(b'\xff' * 0x8000)
            publish(directory / f'source-save-before-{player}.json',
                    {'path': str(blank), 'sha256': hashlib.sha256(blank.read_bytes()).hexdigest()})
            manifest = cartridges.manifest(player)
            rom = cartridges.directory / manifest['output']
            assert hashlib.sha1(rom.read_bytes()).hexdigest() == manifest['final_sha1']
            script = directory / f'gate-{player}.lua'
            gate = (ROOT / 'lua/tests/test_gen1_cold_native_launcher_gate.lua').read_text()
            script.write_text(gate.replace('G.start("test_gen1_cold_native_launcher_gate"',
                                          f'G.start("{directory.name.replace("-", "_")}_{player}"'))
            spec = directory / f'input-{player}.json'
            publish(spec, {'directory': directory.as_posix(), 'player': player,
                           'launcher': launcher.as_posix(), 'manifest': manifest})
            jobs.append(asyncio.create_task(asyncio.to_thread(
                run_gate, script.relative_to(ROOT).as_posix(), rom_key=variant, timeout=1200,
                quiet=True, config_base=str(config), fixture_override=str(blank),
                cartridge_override={'path': str(rom), 'sha256': hashlib.sha256(rom.read_bytes()).hexdigest(),
                                    'saveram_name': 'candidate.SaveRAM'},
                extra_env={'SLINK_COLD_NATIVE_INPUT': str(spec),
                           'SLINK_CLIENT_STORAGE_ROOT': str(directory / 'client-data')},
            )))
        publish(directory / 'go.json', {'ready': True})
        transaction = None
        last_progress = None
        deadline = asyncio.get_running_loop().time() + 1150
        while asyncio.get_running_loop().time() < deadline:
            for player in players:
                error = directory / f'error-{player}.json'
                if error.exists():
                    raise AssertionError(error.read_text())
            document = runtime.journal.snapshot().state
            components = document['components']
            saves = components.get('gen1-initial-save', {})
            saved = set(saves) == {'a', 'b'} and all(row['receipt_operation'] for row in saves.values())
            starters = components.get('gen1-starter-settlement', {})
            linked = set(starters.get('settled', {})) == {'a', 'b'} and bool(starters.get('link_id'))
            routes = {}
            for player in players:
                path = directory / f'route-{player}.json'
                if path.exists():
                    # Test diagnostics are not protocol evidence.
                    with contextlib.suppress(PermissionError, json.JSONDecodeError):
                        routes[player] = json.loads(path.read_text())
            at_center = len(routes) == 2 and all(row['route']['center_ready'] for row in routes.values())
            transaction = document['active_trade'] or transaction
            trade = runtime.journal.record(NAMESPACE, transaction).value if transaction else None
            handed = components.get('gen1-native-frame-accounting', {})
            complete = bool(trade and trade['phase'] == 'link_committed' and set(handed) == {'a', 'b'}
                            and all(row['phase'] == 'handed_back' for row in handed.values()))
            progress = {'saved': bool(saved), 'linked': bool(linked), 'both_at_center': at_center,
                        'trade_complete': complete}
            if progress != last_progress:
                publish(directory / 'handshake.json', progress)
                last_progress = progress
            if all((directory / f'complete-{player}.json').exists() for player in players):
                break
            for job in jobs:
                if job.done():
                    passed, path, log = await job
                    if not passed:
                        raise AssertionError(f'{path}\n{log[-5000:]}')
            await asyncio.sleep(0.1)
        else:
            raise AssertionError(f'cold native route timed out: {directory}')
        for job in jobs:
            passed, path, log = await job
            assert passed, f'{path}\n{log[-5000:]}'
        assert transaction is not None
        trade = runtime.journal.record(NAMESPACE, transaction).value
        assert trade['phase'] == 'link_committed'
        for player in players:
            result = json.loads((directory / f'complete-{player}.json').read_text())
            assert result['native_calls'].get('InternalClockTradeAnim') == 1
            assert trade['applied'][player]['counts']['InternalClockTradeAnim'] == 1
            assert not result['status']['frame_progress']['native_borrowed']
            assert (directory / f'{player}-trade-complete.png').is_file()
            assert (directory / f'blank-{player}.SaveRAM').read_bytes() == b'\xff' * 0x8000
        publish(directory / 'verified.json', {'transaction': transaction, 'trade': trade,
                                             'source': 'normal New Game, source-settled starters, original inputs'})
    finally:
        publish(directory / 'abort.json', {'reason': 'paired cold route ended'})
        await asyncio.gather(*jobs, return_exceptions=True)
        await web.close()
        listener.close()
        await listener.wait_closed()
        runtime.close()
        publish(directory / 'server-timing.json', server_timings)
        current = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(source_paths)}
        publish(directory / 'source-closure-after.json', current)
        for player in players:
            blank = directory / f'blank-{player}.SaveRAM'
            if blank.exists():
                publish(directory / f'source-save-after-{player}.json',
                        {'path': str(blank), 'sha256': hashlib.sha256(blank.read_bytes()).hexdigest()})
        assert source_hashes == current, 'client source closure changed during cold native route'
