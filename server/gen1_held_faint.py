"""Verify one oldest pending faint write under an unchanged owned overworld hold."""
import json
from pathlib import Path

from server.admission_context import same_admitted_context
from server.gen1_command_receipts import (
    RECEIPT_SCHEMAS,
    validate_party_snapshot,
    verify_force_faint,
)
from server.held_write_permit import VerifiedHeldWrite
from server.operation_scope import command_scope
from server.protocol import digest
from server.protocol_journal import JournalError

PROFILES=json.loads((Path(__file__).resolve().parents[1]/'data/games/gen1_rby/write_checkpoint.json').read_text())
SCHEMA='rby-held-faint-evidence-v1'


def verify_checkpoint(point,variant):
    if not isinstance(point,dict) or set(point)!={'pc','sp','rom','system'}:raise JournalError('complete overworld checkpoint required')
    profile=PROFILES[variant];p=profile['write_safe'];sp=point['sp']
    if type(point['pc']) is not int or point['pc']!=p['irq_vector'] or type(sp) is not int or not p['stack_min']<=sp<=p['stack_end']-3:
        raise JournalError('held CPU is not at the qualified overworld checkpoint')
    rom={}
    def instruction(addr,op,target):
        for i,value in enumerate((op,target&255,target>>8)):rom[str(addr+i)]=value
    instruction(p['irq_vector'],0xC3,p['vblank_entry'])
    instruction(p['overworld_loop'],0xCD,p['delay_frame']);instruction(p['overworld_loop_less_delay'],0xCD,p['delay_frame'])
    for i,value in enumerate((0x3E,1,0xE0,p['vblank_flag']&255,0x76,0xF0,p['vblank_flag']&255,0xA7)):
        rom[str(p['delay_frame']+i)]=value
    if point['rom']!=rom or any(type(value) is not int for value in point['rom'].values()):raise JournalError('held checkpoint ROM instructions differ')
    fixed={profile['BATTLE_FLAG_ADDR']:0,profile['JOY_IGNORE_ADDR']:0,p['link_state']:p['link_none'],
        p['serial_status']:p['disconnected_serial'],p['entering_cable_club']:0,p['vblank_flag']:1}
    if p.get('printer_open') is not None:fixed[p['printer_open']]=0
    expected={str(addr) for addr in fixed}|{str(profile['FONT_LOADED_ADDR'])}|{str(sp+i) for i in range(4)}
    values=point['system']
    if not isinstance(values,dict) or set(values)!=expected or any(type(v) is not int or not 0<=v<=255 for v in values.values()):
        raise JournalError('complete bounded checkpoint bytes required')
    if any(values[str(addr)]!=value for addr,value in fixed.items()) or values[str(profile['FONT_LOADED_ADDR'])]%2:
        raise JournalError('battle, text, script or serial owns the checkpoint')
    resume=values[str(sp)]+256*values[str(sp+1)];caller=values[str(sp+2)]+256*values[str(sp+3)]
    if resume!=p['delay_frame']+5 or caller not in (p['overworld_loop']+3,p['overworld_loop_less_delay']+3):
        raise JournalError('main thread is not waiting in the overworld loop')


def verify(player,command,evidence,state,binding):
    body=command['body']
    if body.get('cmd')=='initial_save':
        from server.gen1_initial_save_runtime import verify_operation
        return verify_operation(player,command,evidence,state,binding)
    if body.get('cmd')=='memorialize':
        from server.gen1_memorial_runtime import verify_operation
        return verify_operation(player,command,evidence,state,binding)
    if body.get('cmd')=='acquisition_retire':
        from server.gen1_retirement_runtime import verify_operation
        return verify_operation(player,command,evidence,state,binding)
    if body.get('cmd')=='storage_apply':
        from server.gen1_storage_runtime import verify_operation
        return verify_operation(player,command,evidence,state,binding)
    if body.get('cmd')=='replace_rival_team':
        from server.gen1_held_rival_team import verify as verify_rival_team
        return verify_rival_team(player,command,evidence,state,binding)
    # force_explode at the verified overworld checkpoint is the faint write (the in-battle form is the
    # rby-battle-force-explode instruction binding, battle_force_authority); only the receipt schema
    # and the permit phase name the command.
    if body.get('cmd') not in RECEIPT_SCHEMAS or 'death_id' not in body:return None
    if not isinstance(evidence,dict) or set(evidence)!={'schema','command_id','command_sequence','context_generation',
            'final_sha1','host','checkpoint','intent','current'} or evidence['schema']!=SCHEMA:
        raise JournalError('complete held faint evidence required')
    initial=state['components'].get('gen1-initial-observations',{}).get(player)
    death=state['components'].get('gen1-faint-settlement',{}).get('deaths',{}).get(body['death_id'])
    if initial is None or death is None or death['phase']!='pending_faint' or death['peer']!=player or death['peer_key']!=body.get('key'):
        raise JournalError('held faint lacks its pending owned death obligation')
    metadata=verify_owned_checkpoint(player,command,evidence,state,binding)
    variant=metadata['gen1_metadata']['cartridge']['variant']
    intent=evidence['intent']
    if not isinstance(intent,dict) or set(intent)!={'schema','before','after','slot'} or intent['schema']!='gen1-force-faint-intent-v1':
        raise JournalError('exact prepared faint intent required')
    result=verify_force_faint(body,intent['before'],intent['after'],variant=variant,identity=metadata['save_identity'])
    if type(intent['slot']) is not int or intent['slot']!=result['slot'] or intent['before']['battle_flag']!=0:
        raise JournalError('held faint may only write the verified overworld party slot')
    validate_party_snapshot(evidence['current'],variant=variant)
    if evidence['current'] not in (intent['before'],intent['after']):raise JournalError('faint readback diverged from prepared intent')
    return VerifiedHeldWrite(command_scope(command,binding,phase=body['cmd']),digest(evidence),1000,digest(state))


def verify_owned_host(player,command,evidence,state,binding,*,historical=False):
    initial=state['components'].get('gen1-initial-observations',{}).get(player)
    if initial is None:raise JournalError('held operation requires initial enrollment')
    admission=state['components']['gen1-runtime']['admissions'][player]
    if initial['binding']['context_generation']!=binding['context_generation'] or not historical and (
            admission is None or admission['binding']!={k:binding[k] for k in ('binding_digest','context_generation')}
            or not same_admitted_context(initial['metadata'], {**admission['metadata'], 'control_binding': binding})):
        raise JournalError('held faint requires its original admitted context')
    metadata=initial['metadata'];cartridge=metadata['gen1_metadata']['cartridge'];host=evidence['host']
    if (evidence['command_id']!=command['command_id'] or type(evidence['command_sequence']) is not int
            or evidence['command_sequence']!=command['command_sequence'] or evidence['context_generation']!=binding['context_generation']
            or evidence['final_sha1']!=cartridge['final_rom_sha1']):raise JournalError('faint evidence differs from command/cartridge/context')
    if not isinstance(host,dict) or set(host)!={'owner_id','capability_id','process_id','frame','held'}:
        raise JournalError('owned held host proof required')
    if (host['owner_id']!=metadata['gen1_metadata']['physical_instance'] or host['capability_id']!='bizhawk-2.11.1-gambatte-exclusive-hold-v1'
            or type(host['process_id']) is not int or host['process_id']!=initial['observation']['host']['process_id']
            or type(host['frame']) is not int or host['held'] is not True):
        raise JournalError('faint host/frame differs from the enrolled fixed hold')
    progress=state['components'].get('gen1-observation-progress',{}).get(player)
    if progress is not None:
        # Free-run (P10): the hold is momentary and the server keeps no step count, so a write
        # frame must not precede the latest observation checkpoint it followed (the enrollment
        # frame when re-verified later, once the checkpoint has moved past the write).
        if host['frame']<(initial['observation']['frame'] if historical else progress['frame']):
            raise JournalError('faint host/frame precedes the observation checkpoint')
    elif host['frame'] != initial['observation']['frame']:
        raise JournalError('faint host/frame differs from the enrolled fixed hold')
    if not historical and state['active_trade'] is not None:raise JournalError('trade owns the party')
    return metadata


def verify_owned_checkpoint(player,command,evidence,state,binding,*,historical=False):
    metadata=verify_owned_host(player,command,evidence,state,binding,historical=historical)
    verify_checkpoint(evidence['checkpoint'],metadata['gen1_metadata']['cartridge']['variant'])
    return metadata
