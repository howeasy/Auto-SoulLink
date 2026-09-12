"""Single-use command permission with no frame or recovery authority."""
from dataclasses import dataclass
from types import MappingProxyType
import re

from server.operation_scope import _scope

SCHEMA='slink-held-write-permit-v1'


@dataclass(frozen=True)
class VerifiedHeldWrite:
    scope: dict
    proof_digest: str
    ttl_ms: int
    state_digest: str

    def __post_init__(self):
        object.__setattr__(self,'scope',MappingProxyType(_scope(self.scope)))
        for value in (self.proof_digest,self.state_digest):
            if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('verified held-write digest required')
        if type(self.ttl_ms) is not int or not 1<=self.ttl_ms<=1000:raise ValueError('short held-write lifetime required')


def issue(request,proof):
    if not isinstance(proof,VerifiedHeldWrite):raise ValueError('verified held-write proof required')
    if not isinstance(request,dict) or set(request)!={'schema','challenge','scope'} or request['schema']!=SCHEMA:
        raise ValueError('exact held-write request required')
    if not isinstance(request['challenge'],str) or not re.fullmatch('[0-9a-f]{32}',request['challenge']):
        raise ValueError('held-write challenge required')
    if _scope(request['scope'])!=dict(proof.scope):raise ValueError('held-write scope differs')
    return {'schema':SCHEMA,'challenge':request['challenge'],'scope':dict(proof.scope),
            'uses':1,'ttl_ms':proof.ttl_ms,'proof_digest':proof.proof_digest}
