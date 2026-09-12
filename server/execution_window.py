"""Command-scoped execution response codec; generation/private ownership policy is external."""
from dataclasses import dataclass
from types import MappingProxyType
import re



SCHEMA="slink-operation-execution-window-v1"
from server.operation_scope import SCOPE_FIELDS, _scope, command_scope  # noqa: F401

@dataclass(frozen=True)
class VerifiedExecutionWindow:
    """A generation verifier must independently establish this proof before issuing."""
    scope: dict
    proof_digest: str
    frames: int
    ttl_ms: int
    state_digest: str | None = None

    def __post_init__(self):
        object.__setattr__(self,"scope",MappingProxyType(_scope(self.scope)))
        if not isinstance(self.proof_digest,str) or re.fullmatch(r"[0-9a-f]{64}",self.proof_digest) is None:
            raise ValueError("versioned operation evidence digest required")
        if type(self.frames) is not int or not 1<=self.frames<=600:
            raise ValueError("finite operation frame count required")
        if type(self.ttl_ms) is not int or not 1<=self.ttl_ms<=2000:
            raise ValueError("short operation lifetime required")
        if self.state_digest is not None and (not isinstance(self.state_digest,str) or re.fullmatch(r"[0-9a-f]{64}",self.state_digest) is None):
            raise ValueError("invalid verified authorization state digest")


def issue(request,proof):
    """Encode one exact challenge response. This function is not an authorization policy."""
    if not isinstance(proof,VerifiedExecutionWindow):raise ValueError("independently verified operation proof required")
    if not isinstance(request,dict) or set(request)!={"schema","challenge","scope"} or request["schema"]!=SCHEMA:
        raise ValueError("exact operation execution challenge required")
    challenge=request["challenge"]
    if not isinstance(challenge,str) or re.fullmatch(r"[0-9a-f]{32}",challenge) is None:
        raise ValueError("operation challenge nonce required")
    if _scope(request["scope"])!=dict(proof.scope):raise ValueError("operation request differs from verified scope")
    return {"schema":SCHEMA,"challenge":challenge,"scope":dict(proof.scope),"frames":proof.frames,
            "ttl_ms":proof.ttl_ms,"proof_digest":proof.proof_digest}
