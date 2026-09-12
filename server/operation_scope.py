"""Shared exact command/context scope for generation-verified operation permits."""
import re
from server.protocol import digest

SCOPE_FIELDS={'operation_id':32,'operation_digest':64,'context_generation':32,'binding_digest':64,'phase':None}


def _scope(value):
    if not isinstance(value,dict) or set(value)!=set(SCOPE_FIELDS):raise ValueError('complete operation scope required')
    for name,length in SCOPE_FIELDS.items():
        pattern=r'[a-z][a-z0-9_-]{0,63}' if length is None else r'[0-9a-f]{'+str(length)+'}'
        if not isinstance(value[name],str) or re.fullmatch(pattern,value[name]) is None:raise ValueError('invalid operation '+name)
    return dict(value)


def command_scope(command,binding,*,phase):
    sequence=command['command_sequence']
    if type(sequence) is not int or not 1<=sequence<=2**53-1 or not isinstance(command['body'],dict):
        raise ValueError('exact stored command sequence/body required')
    return _scope({'operation_id':command['command_id'],'operation_digest':digest({
        'command_id':command['command_id'],'command_sequence':sequence,'body':command['body']}),
        'context_generation':binding['context_generation'],'binding_digest':binding['binding_digest'],'phase':phase})
