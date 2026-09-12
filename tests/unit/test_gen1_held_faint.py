import copy
from itertools import product

import pytest

from server.gen1_held_faint import PROFILES, SCHEMA, verify, verify_checkpoint
from server.gen1_run_config import create_runtime
from server.held_write_permit import VerifiedHeldWrite
from server.protocol_journal import JournalError
from tests.unit.test_gen1_engine_signal_runtime import deliver
from tests.unit.test_gen1_faint_runtime import acknowledgement, paired, signal_batch
from tests.unit.test_gen1_sessions import contract


def checkpoint(variant):
    profile=PROFILES[variant];p=profile['write_safe'];sp=p['stack_end']-3;rom={}
    for addr,opcode,target in [(p['irq_vector'],0xC3,p['vblank_entry']),(p['overworld_loop'],0xCD,p['delay_frame']),
                               (p['overworld_loop_less_delay'],0xCD,p['delay_frame'])]:
        for i,value in enumerate((opcode,target&255,target>>8)):rom[str(addr+i)]=value
    for i,value in enumerate((0x3E,1,0xE0,p['vblank_flag']&255,0x76,0xF0,p['vblank_flag']&255,0xA7)):rom[str(p['delay_frame']+i)]=value
    system={str(addr):value for addr,value in [(profile['BATTLE_FLAG_ADDR'],0),(profile['JOY_IGNORE_ADDR'],0),
        (profile['FONT_LOADED_ADDR'],0),(p['link_state'],p['link_none']),(p['serial_status'],p['disconnected_serial']),
        (p['entering_cable_club'],0),(p['vblank_flag'],1)]}
    if p.get('printer_open') is not None:system[str(p['printer_open'])]=0
    resume=p['delay_frame']+5;caller=p['overworld_loop']+3
    for i,value in enumerate((resume&255,resume>>8,caller&255,caller>>8)):system[str(sp+i)]=value
    return {'pc':p['irq_vector'],'sp':sp,'rom':rom,'system':system}


def evidence(runtime,command):
    initial=runtime.state().document()['components']['gen1-initial-observations']['b'];variant=runtime.contract['players']['b']['variant']
    receipt=acknowledgement(runtime,'b',command)['receipt']
    for snap in (receipt['before'],receipt['after']):snap.update(battle_flag=0,active_slot=None,battle_hp=None)
    return {'schema':SCHEMA,'command_id':command['command_id'],'command_sequence':command['command_sequence'],
        'context_generation':initial['binding']['context_generation'],'final_sha1':runtime.contract['players']['b']['final_rom_sha1'],
        'host':{**initial['observation']['host'],'frame':initial['observation']['frame']},
        'checkpoint':checkpoint(variant),'intent':{'schema':'gen1-force-faint-intent-v1','before':receipt['before'],'after':receipt['after'],'slot':0},
        'current':receipt['before']}


@pytest.mark.parametrize('cmd',['force_faint','force_explode'])
@pytest.mark.parametrize('variants',list(product(('red','blue','yellow'),repeat=2)))
def test_exact_held_death_command_gets_no_frame_authority(tmp_path,variants,cmd):
    """Under Explode Mode the engine selects force_explode (state._propagate_faint); at the verified
    overworld checkpoint it is the same faint write, so the same evidence earns the permit and only the
    scope phase names the command."""
    runtime=create_runtime(tmp_path,contract(*variants),rule_options={'explode_mode':cmd=='force_explode'})
    try:
        owners=paired(runtime);deliver(runtime,'a',owners['a'],signal_batch(runtime,'a'))
        command=runtime.journal.command('b',runtime.journal.pending_ids('b')[0]);value=evidence(runtime,command)
        assert command['body']['cmd']==cmd
        proof=verify('b',command,value,runtime.state().document(),runtime.gate.sessions['b'].metadata['control_binding'])
        assert isinstance(proof,VerifiedHeldWrite) and not hasattr(proof,'frames') and proof.scope['phase']==cmd
        value['current']=value['intent']['after']
        assert isinstance(verify('b',command,value,runtime.state().document(),runtime.gate.sessions['b'].metadata['control_binding']),VerifiedHeldWrite)
    finally:runtime.close()


@pytest.mark.parametrize('cmd',['force_faint','force_explode'])
@pytest.mark.parametrize('fault',['frame','host','intent','body','context','checkpoint','battle'])
def test_changed_physical_or_command_evidence_refuses_permission(tmp_path,fault,cmd):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'),rule_options={'explode_mode':cmd=='force_explode'})
    try:
        owners=paired(runtime);deliver(runtime,'a',owners['a'],signal_batch(runtime,'a'))
        cmd=runtime.journal.command('b',runtime.journal.pending_ids('b')[0]);value=evidence(runtime,cmd)
        if fault=='frame':value['host']['frame']+=1
        elif fault=='host':value['host']['held']=False
        elif fault=='intent':value['intent']['slot']=1
        elif fault=='body':cmd['body']['key']='0000:0000:00'
        elif fault=='context':value['context_generation']='f'*32
        elif fault=='checkpoint':value['checkpoint']['pc']=0
        else:value['intent']['before']['battle_flag']=1
        with pytest.raises((JournalError,ValueError)):
            verify('b',cmd,value,runtime.state().document(),runtime.gate.sessions['b'].metadata['control_binding'])
    finally:runtime.close()


@pytest.mark.parametrize('variant',['red','blue','yellow'])
def test_all_checkpoint_reads_are_required_and_tampering_is_rejected(variant):
    point=checkpoint(variant);verify_checkpoint(point,variant)
    for domain in ('rom','system'):
        for key in point[domain]:
            changed=copy.deepcopy(point);del changed[domain][key]
            with pytest.raises(JournalError):verify_checkpoint(changed,variant)


def test_server_checkpoint_artifact_matches_the_qualified_client_profiles():
    from tools.gen_gen1_write_checkpoint import OUTPUT, generate
    assert OUTPUT.read_text()==generate()
