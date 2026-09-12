"""LIVE qualification of the battle instruction authority prototype on the original engine.

Drives lua/tests/test_gen1_battle_force_gate.lua from the Route 1 battery-save fixture, then
verifies every evidence row the executor produced with the server binding, using the hook-frame
convention the gate measured. Writes a summary next to the gate's result file.
"""
import json
import os
import tempfile
from pathlib import Path

import pytest

from server import battle_force_authority as auth, instruction_authority as generic
from server.protocol_journal import JournalError
from tools.run_gb_gate import BIZHAWK_CONFIG, REPO, run_gate

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.live, pytest.mark.slow,
              pytest.mark.skipif(os.environ.get('SLINK_LIVE') != '1', reason='explicit live emulator lane required')]
COORDS = {'red': {'x': 0xD362, 'y': 0xD361, 'map': 0xD35E}, 'blue': {'x': 0xD362, 'y': 0xD361, 'map': 0xD35E}, 'yellow': {'x': 0xD361, 'y': 0xD360, 'map': 0xD35D}}
# wStatusFlags4 (BIT_NO_BATTLES = bit 4) and wNumberOfNoRandomBattleStepsLeft, per .sym
# diagnostic PCs (red): call-target, linear and jp-target addresses around ExecutePlayerMove
DIAG_PCS = {'red': {'exec_plus3': 0x5661, 'exec_done_jp': 0x580A, 'call_site_enemy_first': 0x4361, 'call_site_player_first': 0x437D,
                    'poison_call_target': 0x43BD, 'select_enemy_move': 0x4361 - 0x3}}
MENU_PC = {'red': 0x4EB3, 'blue': 0x4EB3, 'yellow': 0x4F78}  # DisplayBattleMenu, bank $0F (.sym)
# lua/tests/gen1_battle_driver.lua sites/addresses (pinned by tests/unit/test_gen1_battle_driver_pins.py)
_DRIVER_RB = {'sites': {'display_battle_menu': 0x4EB3, 'move_selection_menu': 0x5219, 'select_enemy_move': 0x5564, 'execute_player_move': 0x565E,
                        'execute_enemy_move': 0x66BC},
              'addresses': {'wTopMenuItemY': 0xCC24, 'wTopMenuItemX': 0xCC25, 'wCurrentMenuItem': 0xCC26, 'wMaxMenuItem': 0xCC28, 'wMenuWatchedKeys': 0xCC29,
                            'wPlayerMoveListIndex': 0xCC2E, 'wPlayerMonNumber': 0xCC2F, 'wListScrollOffset': 0xCC36, 'wPlayerSelectedMove': 0xCCDC,
                            'wEnemySelectedMove': 0xCCDD, 'wActionResultOrTookBattleTurn': 0xCD6A, 'wCurItem': 0xCF91, 'wWhichPokemon': 0xCF92,
                            'wEnemyMonHP': 0xCFE6, 'wBattleMonHP': 0xD015, 'wBattleMonMoves': 0xD01C, 'wBattleMonPP': 0xD02D, 'wIsInBattle': 0xD057,
                            'wNumRunAttempts': 0xD120, 'wPartyCount': 0xD163, 'hJoyPressed': 0xFFB3, 'hJoy5': 0xFFB5, 'hLoadedROMBank': 0xFFB8}}
_DRIVER_Y = {'sites': {'display_battle_menu': 0x4F78, 'move_selection_menu': 0x5320, 'select_enemy_move': 0x56D6, 'execute_player_move': 0x57D0,
                       'execute_enemy_move': 0x6842},
             'addresses': {**_DRIVER_RB['addresses'], 'wCurItem': 0xCF90, 'wWhichPokemon': 0xCF91, 'wEnemyMonHP': 0xCFE5, 'wBattleMonHP': 0xD014,
                           'wBattleMonMoves': 0xD01B, 'wBattleMonPP': 0xD02C, 'wIsInBattle': 0xD056, 'wNumRunAttempts': 0xD11F, 'wPartyCount': 0xD162}}
DRIVER = {'red': _DRIVER_RB, 'blue': _DRIVER_RB, 'yellow': _DRIVER_Y}
FIXTURES = {v: ROOT / '.cache' / 'battle-fixtures' / f'{v}_battle.SaveRAM' for v in ('red', 'blue', 'yellow')}  # tools/gen1_battle_fixture.py
ENCOUNTER = {'red': {'status_flags4': 0xD72E, 'pacer': 0xD13C}, 'blue': {'status_flags4': 0xD72E, 'pacer': 0xD13C},
             'yellow': {'status_flags4': 0xD72D, 'pacer': 0xD13B}}


def run_live(variant, *, bounded_battle=True, timeout=900, fixture=None, scenarios=None):
    """`fixture`: an isolated .cache two-mon SaveRAM (disclosed fixture) instead of the committed one-mon save."""
    directory = Path(tempfile.mkdtemp(prefix=f'battle-force-{variant}-', dir=Path(REPO) / '.cache'))
    output = directory / 'result.json'
    spec = {'addresses': auth.ANCHORS[variant]['addresses'], 'sites': auth.sites(variant), 'output': output.as_posix(),
            'out_dir': directory.as_posix(), 'coord_addr': COORDS[variant], 'encounter': ENCOUNTER[variant], 'bounded_battle': bounded_battle,
            'menu_pc': MENU_PC[variant], 'diag_pcs': DIAG_PCS.get(variant, {}), 'fixture': str(fixture) if fixture else None,
            'scenarios': scenarios, 'driver': DRIVER[variant]}
    (directory / 'input.json').write_text(json.dumps(spec))
    # the bounded owner refuses a host with rewind active (platform_execution host_valid), as the bounded gate does
    config = json.loads(Path(BIZHAWK_CONFIG).read_text(encoding='utf-8-sig'))
    config['Rewind']['Enabled'] = False
    private = directory / 'config.ini'
    private.write_text(json.dumps(config))
    passed, path, log = run_gate('lua/tests/test_gen1_battle_force_gate.lua', rom_key=variant, target='battle', quiet=True, timeout=timeout,
                                 config_base=str(private), fixture_override=str(fixture) if fixture else None,
                                 extra_env={'SLINK_BATTLE_FORCE_INPUT': str(directory / 'input.json')})
    (directory / 'gate.log').write_text(log)
    result = json.loads(output.read_text()) if output.exists() else None
    return passed, path, log, result, directory


def verify_rows(result, variant):
    """Every reached row must verify with the server under the measured convention; returns the outcomes."""
    offset = result.get('hook_frame_offset_harness')
    outcomes = []
    for scenario in result['scenarios']:
        for row in scenario['reached']:
            a = dict(row['authority'])
            ev = row['evidence']
            use = result.get('hook_frame_offset_bounded') if row.get('bounded') else offset
            try:
                verdict = auth.verify_evidence(a, ev, hook_frame_offset=use)
                outcomes.append({'scenario': scenario['name'], 'site': ev['site'], **verdict, 'frame': ev['frame'], 'hook_frame': ev['hook_frame']})
            except JournalError as error:
                outcomes.append({'scenario': scenario['name'], 'site': ev['site'], 'outcome': 'REFUSED_BY_SERVER', 'reason': str(error), 'frame': ev['frame']})
    return outcomes


@pytest.mark.parametrize('variant', ['red', 'blue', 'yellow'])
def test_original_engine_battle_force_faint_prototype(variant):
    passed, path, log, result, directory = run_live(variant, fixture=FIXTURES[variant])
    assert result is not None, f'{directory}\n{path}\n{log[-4000:]}'
    outcomes = verify_rows(result, variant)
    summary = {'variant': variant, 'gate_passed': passed, 'hook_frame_offset_harness': result.get('hook_frame_offset_harness'),
               'hook_frame_offset_bounded': result.get('hook_frame_offset_bounded'), 'bounded_input': result.get('bounded_input'),
               'sram_diff_bytes': result.get('sram_diff_bytes'), 'screenshots': result.get('screenshots'), 'outcomes': outcomes,
               'scenarios': [{k: v for k, v in s.items() if k != 'reached'} | {'reached': len(s['reached'])} for s in result['scenarios']],
               'notes': result.get('notes'), 'error': result.get('error')}
    (directory / 'summary.json').write_text(json.dumps(summary, indent=1))
    assert passed and result['passed'], f'{directory}\n{json.dumps(summary, indent=1)[-6000:]}\n{log[-3000:]}'
    assert all(o['outcome'] != 'REFUSED_BY_SERVER' for o in outcomes), json.dumps(outcomes, indent=1)
    assert any(o['outcome'] == 'fainted' for o in outcomes), 'no fainted outcome was produced live'
    assert result['sram_diff_bytes'] == 0
    assert generic.SCHEMA  # imported for the reader: authority rows are generic.SCHEMA objects


@pytest.mark.parametrize('variant', ['red', 'blue', 'yellow'])
def test_active_linked_mon_faints_at_execute_player_move_under_bounded_owner(variant):
    """The one branch round 2 left open: the ACTIVE linked mon (no switch, no Transform) commits FIGHT and the
    ExecutePlayerMove+0 write (wBattleMonHP 0000 + CANNOT_MOVE) faints it in the original engine under step_one."""
    passed, path, log, result, directory = run_live(variant, fixture=FIXTURES[variant], scenarios=['fight_first'])
    assert result is not None, f'{directory}\n{path}\n{log[-4000:]}'
    outcomes = verify_rows(result, variant)
    (directory / 'summary.json').write_text(json.dumps({'variant': variant, 'passed': passed, 'outcomes': outcomes,
                                                        'checks': [(s['name'], [(c['what'], c['ok']) for c in s['checks']]) for s in result['scenarios']],
                                                        'write_rows': [s.get('write_row') for s in result['scenarios'] if s.get('write_row')]}, indent=1))
    active = [o for o in outcomes if o['scenario'] == 'fight_first' and o['site'] == 'player_action' and o['outcome'] == 'fainted']
    assert active, json.dumps(outcomes, indent=1)
    assert passed and result['passed'] and result['sram_diff_bytes'] == 0, f'{directory}\n{log[-3000:]}'
