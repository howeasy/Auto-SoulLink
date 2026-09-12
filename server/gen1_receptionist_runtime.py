"""Owned native receptionist query/return, before a paired trade exists."""
import copy
import re

from server.execution_window import command_scope
from server.gen1_command_receipts import validate_party_snapshot
from server.gen1_native_trade_receipts import _bytes, validate_party_storage
from server.gen1_trade_preparation import boxed_keys
from server.identity_registry import IdentityRegistry
from server.protocol import digest
from server.protocol_journal import JournalError

COMPONENT='gen1-receptionist'
NAMESPACE='gen1-native-ui'
REASON='RBY native receptionist awaiting verified return'
PATHS=[['after_query','party','offer','offer_result','menus_restored'],
       ['after_query','party','menus_restored'],['after_query','menus_restored'],
       ['after_query','menus_restored','cable']]


def query(value,manifest):
    if (not isinstance(value,dict) or set(value)!={'schema','pc','bank','caller','overlay_hex'}
            or value['schema']!='rby-receptionist-query-v1' or type(value['pc']) is not int or value['pc']!=0x40
            or type(value['bank']) is not int or value['bank']!=manifest['receptionist']['entry']['bank']
            or type(value['caller']) is not int or value['caller']!=manifest['receptionist']['query_return']):
        raise JournalError('original receptionist query caller required')
    raw=_bytes(value['overlay_hex'],16)
    if raw[:6]!=bytes.fromhex('534C54310101') or raw[6]==raw[7]:
        raise JournalError('unanswered original receptionist query required')


def verify_state(journal,stage):
    component=stage.document()['components'].get(COMPONENT,{})
    if not isinstance(component,dict) or set(component)-{'a','b'}:
        raise JournalError('invalid receptionist obligations')
    blockers={k:v for k,v in stage.barrier.document()['blockers'].items() if v==REASON}
    expected={}
    for p in ('a','b'):
        if p not in component and any(journal.command(p,k)['body'].get('cmd')=='native_receptionist' for k in journal.pending_ids(p)):
            raise JournalError('orphaned receptionist command')
    for p,entry in component.items():
        if not isinstance(entry,dict) or set(entry)!={'visit_id','record_digest','phase'}:
            raise JournalError('invalid receptionist record binding')
        record=journal.record(NAMESPACE,entry['visit_id'])
        if record is None or digest(record.value)!=entry['record_digest'] or record.value['phase']!=entry['phase']:
            raise JournalError('receptionist obligation differs from its journal')
        pending=[journal.command(p,k)['body'] for k in journal.pending_ids(p)
                 if journal.command(p,k)['body'].get('cmd')=='native_receptionist']
        if entry['phase']=='active':
            if pending!=[record.value['body']]:raise JournalError('receptionist pending command differs')
            expected[entry['visit_id']]=REASON
        elif entry['phase']!='closed' or pending:raise JournalError('receptionist closure differs')
    if expected!=blockers:raise JournalError('receptionist recovery blockers differ')


class ReceptionistRuntime:
    def __init__(self,policy):
        self.policy=policy;self.runtime=policy.runtime;self.execution=policy.execution

    def _record(self,stage,player,visit,record):
        document=stage.document();component=document['components'].setdefault(COMPONENT,{})
        component[player]={'visit_id':visit,'phase':record['phase'],'record_digest':digest(record)}
        blockers=stage.barrier.document()['blockers']
        if record['phase']=='active':blockers[visit]=REASON
        else:blockers.pop(visit,None)
        stage.barrier.set_blockers(blockers)
        document['components']['gen1-runtime']['recovery']=stage.barrier.document()
        return document

    def start(self,player,operation,message):
        old=self.runtime.journal.event(player,operation,message)
        if old is not None:return old.result
        if set(message)!={'event','payload'} or not isinstance(message['payload'],dict):
            raise JournalError('typed receptionist entry required')
        payload=message['payload'];stage=self.runtime.state();document=stage.document()
        if set(self.runtime.gate.sessions)!={'a','b'}:raise JournalError('paired admission required for receptionist')
        if set(payload)!={'schema','context_generation','final_sha1','query','checkpoint'} or payload['schema']!='rby-receptionist-entry-v1':
            raise JournalError('complete receptionist entry required')
        if document['active_trade'] or any(x['phase']=='active' for x in document['components'].get(COMPONENT,{}).values()):
            raise JournalError('prior native UI/trade must finish first')
        if any(self.runtime.journal.pending_ids(p) for p in ('a','b')):raise JournalError('prior commands require closure')
        from server.gen1_native_policy import contexts
        contexts_now=contexts(document);own=contexts_now[player];manifest=self.policy.manifests[player]
        points=self.policy.candidate_checkpoints(player)
        if (payload['context_generation']!=own.context_generation or payload['final_sha1']!=manifest['final_sha1']
                or payload['checkpoint']!=points[player]):
            raise JournalError('receptionist entry differs from owned observation')
        query(payload['query'],manifest)
        point=payload['checkpoint'];party=validate_party_snapshot(point['party'],variant=self.policy.rules[player].variant)
        validate_party_storage(point['party_storage_hex'],party);boxed_keys(point,self.policy.rules[player].codec)
        registry=IdentityRegistry.restore(document['identities'],run_id=self.runtime.journal.run_id)
        snapshots={p:v['party'] for p,v in points.items()}
        mask=0
        for slot,mon in enumerate(party):
            try:self.policy.binding.proposal(document['rules'],registry,player=player,key=mon.key,contexts=contexts_now,snapshots=snapshots)
            except JournalError:continue  # ineligible slot; no rule mutation or encounter inference
            mask|=1<<slot
        visit=digest({'player':player,'operation_id':operation})[:32]
        body={'cmd':'native_receptionist','player':player,'visit_id':visit,'payload':copy.deepcopy(payload),'eligible_mask':mask}
        record={'phase':'active','body':body}
        commands={'a':[],'b':[]};commands[player]=[body]
        result=self.runtime.journal.commit(player,operation,message,expected_revision=stage.journal_revision,
            state=self._record(stage,player,visit,record),commands=commands,result={'ack':'ACK','visit_id':visit},
            records=[{'namespace':NAMESPACE,'key':visit,'value':record}])
        return result.result

    def window(self,player,command,evidence,document,binding):
        body=command['body'];record=self.runtime.journal.record(NAMESPACE,body['visit_id'])
        if record is None or record.value!={'phase':'active','body':body}:raise JournalError('active receptionist command required')
        if body['payload']['context_generation']!=binding['context_generation']:raise JournalError('receptionist context changed')
        native=evidence['native'];intent=native.get('intent')
        scope=command_scope(command,binding,phase='native_receptionist')
        previous=self.execution.observed.get((player,command['command_id'],binding['binding_digest']))
        if native.get('phase')=='before':
            if set(native)!={'phase','intent','query','checkpoint'} or native['checkpoint']!=body['payload']['checkpoint']:
                raise JournalError('receptionist initial checkpoint differs')
            query(native['query'],self.policy.manifests[player])
            if native['query']!=body['payload']['query']:raise JournalError('receptionist query changed')
            fields={'schema','command_id','command_sequence','body_digest','context_generation','token_hex'}
            if (not isinstance(intent,dict) or set(intent)!=fields or intent['schema']!='rby-receptionist-intent-v1'
                    or intent['command_id']!=command['command_id'] or type(intent['command_sequence']) is not int
                    or intent['command_sequence']!=command['command_sequence'] or intent['body_digest']!=digest(body)
                    or intent['context_generation']!=binding['context_generation'] or not isinstance(intent['token_hex'],str)
                    or not re.fullmatch('[0-9A-F]{8}',intent['token_hex']) or intent['token_hex']=='00000000'):
                raise JournalError('receptionist intent differs from its command')
            fingerprint=digest(intent)
            if previous and (previous['armed'] or previous['intent_digest']!=fingerprint):raise JournalError('receptionist intent regressed')
            armed=False;sequence=[]
        elif native.get('phase')=='active':
            if set(native)!={'phase','intent_digest','sequence'} or previous is None:raise JournalError('receptionist lacks its initial window')
            sequence=native['sequence']
            if (not isinstance(sequence,list) or not any(path[:len(sequence)]==sequence for path in PATHS)
                    or len(sequence)<previous.get('sequence_length',0) or native['intent_digest']!=previous['intent_digest']):
                raise JournalError('receptionist original execution prefix differs')
            fingerprint=previous['intent_digest'];armed=True
        elif native.get('phase')=='complete':return None
        else:raise JournalError('unknown receptionist phase')
        return self.execution.publish(player,command,evidence,document,binding,scope,fingerprint,armed,
                                      {'sequence_length':len(sequence),'token_hex':intent['token_hex'] if intent else previous['token_hex']})

    def offer(self,player,payload):
        commands=self.runtime.journal.pending_ids(player)
        if not commands:raise JournalError('native receptionist must own the offer')
        command=self.runtime.journal.command(player,commands[0]);body=command['body']
        if body['cmd']!='native_receptionist':raise JournalError('native receptionist must own the offer')
        binding=self.runtime.gate.sessions[player].metadata['control_binding']
        seen=self.execution.observed.get((player,command['command_id'],binding['binding_digest']))
        raw=_bytes(body['payload']['query']['overlay_hex'],16)
        slot=payload.get('slot')
        if (seen is None or payload.get('token_hex')!=seen['token_hex'] or payload.get('query_generation')!=raw[6]
                or type(slot) is not int or not 0<=slot<6 or not body['eligible_mask']&(1<<slot)
                or payload.get('snapshot')!=body['payload']['checkpoint']['party']):
            raise JournalError('offer differs from the owned receptionist query/selection')

    def acknowledge(self,player,operation,message):
        old=self.runtime.journal.event(player,operation,message)
        if old is not None:return old.result
        if set(message)!={'event','command_id','command_sequence','receipt','outcome'} or message['outcome']!='ACK':
            raise JournalError('typed receptionist return ACK required')
        command=self.runtime.journal.command(player,message['command_id']);body=command['body'];receipt=message['receipt']
        fields={'schema','command_id','command_sequence','context_generation','final_sha1','sequence','checkpoint','offer_operation_id','frame','token_hex'}
        if (body['cmd']!='native_receptionist' or not isinstance(receipt,dict) or set(receipt)!=fields
                or receipt['schema']!='rby-receptionist-return-v1' or receipt['command_id']!=command['command_id']
                or type(receipt['command_sequence']) is not int or receipt['command_sequence']!=command['command_sequence']
                or type(message['command_sequence']) is not int or message['command_sequence']!=command['command_sequence']
                or receipt['context_generation']!=body['payload']['context_generation']
                or receipt['final_sha1']!=body['payload']['final_sha1'] or receipt['sequence'] not in PATHS
                or receipt['checkpoint']!=body['payload']['checkpoint']):
            raise JournalError('native receptionist return differs')
        binding=self.runtime.gate.sessions[player].metadata['control_binding']
        seen=self.execution.observed.get((player,command['command_id'],binding['binding_digest']))
        if (seen is None or type(receipt['frame']) is not int or not seen['start']<receipt['frame']<=seen['frame']+120
                or receipt['token_hex']!=seen['token_hex']):raise JournalError('native receptionist return lacks owned execution')
        offer=receipt['offer_operation_id']
        if 'offer' in receipt['sequence']:
            if not isinstance(offer,str) or not re.fullmatch('[0-9a-f]{32}',offer):raise JournalError('receptionist offer acknowledgement required')
            from server.gen1_trade_recovery import transactions
            from server.trade_coordinator import NAMESPACE as TRADES
            records=[self.runtime.journal.record(TRADES,key).value for key in transactions(self.runtime.state().document())]
            if not any(row['initiator']==player and row['history'][0]['event_id']==offer for row in records):
                raise JournalError('receptionist return has no acknowledged trade offer')
        elif offer is not None:raise JournalError('cancelled receptionist cannot claim an offer')
        stage=self.runtime.state();record=self.runtime.journal.record(NAMESPACE,body['visit_id'])
        if record is None or record.value!={'phase':'active','body':body}:raise JournalError('receptionist lease is not active')
        value={'phase':'closed','body':body,'receipt':receipt}
        return self.runtime.journal.commit(player,operation,message,expected_revision=stage.journal_revision,
            state=self._record(stage,player,body['visit_id'],value),commands={'a':[],'b':[]},result={'ack':'ACK'},
            acknowledgements=[{'player':player,'command_id':command['command_id'],'outcome':'ACK','receipt':receipt}],
            records=[{'namespace':NAMESPACE,'key':body['visit_id'],'value':value}]).result
