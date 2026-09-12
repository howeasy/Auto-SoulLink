"""Exercise production launch preparation; only the town save/gate are fixtures."""
import json
import shutil
import subprocess
from pathlib import Path

from server.bizhawk_launch import launch, manifest, prepare
from tests.unit.test_gen1_sessions import contract
from tools import gen1_playthrough as play
from tools.run_gb_gate import GENS, _result_path_for

ROOT=Path(__file__).resolve().parents[2]


def run_factory_gate(script, *, rom_key, timeout, quiet, config_base, fixture_override, extra_env, **unused):
    assert rom_key in ('red','blue','yellow') and fixture_override
    input_path=Path(extra_env['SLINK_LAUNCHER_TEST_INPUT']);value=json.loads(input_path.read_text())
    directory=Path(value['directory']);player=value['player']
    muted=directory/('factory-base-'+player+'.ini')
    play.write_run_config(config_base,str(muted))  # Test-only audio/window/RTC controls.
    script=ROOT/script
    spec=manifest(run_id=value['run_id'],player=player,profile='gambatte',
        rom_sha1=contract(rom_key,rom_key)['players']['a']['final_rom_sha1'],launcher=script.read_text())
    plan=prepare(directory/'client-data',spec,rom=ROOT/play.staged_rom(rom_key),launcher=script,base_config=muted)
    save=Path(plan['save_directory'])/GENS['gen1']['saveram_names'][rom_key]
    shutil.copyfile(fixture_override,save)  # Explicit pre-run source fixture, not runtime mutation.
    plan['environment'].update(extra_env)
    plan['environment']['SLINK_GATE_SAVERAM']=str(save)
    result=Path(_result_path_for(str(script)))
    process=launch(plan,play.EMUHAWK)
    try:process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill();process.wait(timeout=10)
        return False,str(result),'production factory gate timed out'
    text=result.read_text() if result.exists() else ''
    verdict=next((line for line in reversed(text.splitlines()) if line.startswith('RESULT:')),'')
    return process.returncode==0 and verdict.startswith('RESULT: PASS'),str(result),text
