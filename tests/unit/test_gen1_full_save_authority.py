import copy
import hashlib
from types import SimpleNamespace

import pytest

from server.gen1_full_save import SYMBOLS, image, layout, verify_receipt
from server.protocol import digest
from server.protocol_journal import JournalError
from server.trade_coordinator import NAMESPACE
from tests.unit.test_gen1_prompt_execution import case, closure, verify  # noqa: F401


@pytest.fixture
def saving(case):  # noqa: F811
    command,evidence=closure(case)
    checkpoint=copy.deepcopy(case[3]['native']['checkpoint'])
    variant=checkpoint['party']['variant'];info=layout(variant)
    fields={name:'00'*region['length'] for name,region in info['regions'].items()}
    fields.update(name=checkpoint['name_hex'],party=checkpoint['party_storage_hex'],box=checkpoint['active_box_hex'])
    symbols=SYMBOLS['pokeyellow' if variant=='yellow' else 'pokered'];main=bytearray.fromhex(fields['main'])
    for name,value in [('wCurMap',checkpoint['map']),('wCurrentBoxNum',checkpoint['current_box'])]:
        main[symbols[name]-symbols['wMainDataStart']]=value
    fields['main']=main.hex().upper()
    point={'schema':'rby-full-save-point-v1','variant':variant,'fields':fields,
           'save_status':1,'cart_hex':checkpoint['cart_hex']}
    intent={'schema':'rby-full-save-intent-v1','command_id':command['command_id'],
            'command_sequence':command['command_sequence'],'body_digest':digest(command['body']),
            'context_generation':evidence['context_generation'],'point':point,'checkpoint':checkpoint,
            'image_hex':image(point).hex().upper()}
    evidence['native']={'phase':'full_save','intent':intent,'current':copy.deepcopy(point),'before':True,'after':False}
    return case,command,evidence


def test_full_save_has_its_own_verified_phase_and_no_frame_progress(saving):
    scenario,command,evidence=saving
    assert verify(scenario,evidence,command).scope['phase']=='native_trade_prepare_save'
    after=copy.deepcopy(evidence);after['native']['current'].update(cart_hex=after['native']['intent']['image_hex'],save_status=2)
    after['native'].update(before=False,after=True)
    assert verify(scenario,after,command)


@pytest.mark.parametrize('fault',['body','context','image','missing_source','party','main_map','claim_after','first_after'])
def test_unverified_full_save_state_has_no_authority(saving,fault):
    scenario,command,evidence=saving;intent=evidence['native']['intent']
    if fault=='body':intent['body_digest']='f'*64
    elif fault=='context':intent['context_generation']='f'*32
    elif fault=='image':intent['image_hex']='00'*0x8000
    elif fault=='missing_source':del intent['point']['fields']['sprites']
    elif fault=='party':intent['point']['fields']['party']='00'*404
    elif fault=='main_map':intent['point']['fields']['main']='FF'*1929
    elif fault=='claim_after':evidence['native']['after']=True
    else:
        evidence['native']['current'].update(cart_hex=intent['image_hex'],save_status=2)
        evidence['native'].update(before=False,after=True)
    with pytest.raises(JournalError):verify(scenario,evidence,command)


def test_current_complete_file_image_is_required_before_preparation(saving):
    scenario,command,evidence=saving;run,execution,_,_=scenario
    verify(scenario,evidence,command);intent=evidence['native']['intent']
    policy=SimpleNamespace(runtime=run.runtime,execution=execution,manifests=execution.manifests)
    receipt={'schema':'rby-full-save-receipt-v1','command_id':command['command_id'],
             'command_sequence':command['command_sequence'],'context_generation':evidence['context_generation'],
             'final_sha1':evidence['final_sha1'],'point':intent['point'],'image_hex':intent['image_hex'],
             'file':{'schema':'slink-saveram-file-v1','path':'Z:/peer/save.SaveRAM','byte_length':0x8000,
                     'sha256':hashlib.sha256(bytes.fromhex(intent['image_hex'])).hexdigest(),
                     'host_profile':'bizhawk-2.11.1-gambatte-exclusive-hold-v1','frame':100,'flushed':True,'readback':True}}
    checkpoint=copy.deepcopy(intent['checkpoint']);checkpoint['cart_hex']=intent['image_hex']
    trade=run.runtime.journal.record(NAMESPACE,run.tx).value
    assert verify_receipt(policy,trade,'b',command,receipt,checkpoint)==receipt
    receipt['file']['frame']=101
    with pytest.raises(JournalError):verify_receipt(policy,trade,'b',command,receipt,checkpoint)
