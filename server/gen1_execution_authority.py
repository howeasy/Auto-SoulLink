"""Private RBY control-response binding for independently verified operation windows."""
import copy

from server.durable_runtime import TIMEOUT
from server.execution_window import VerifiedExecutionWindow,command_scope,issue
from server.held_write_permit import VerifiedHeldWrite, issue as issue_write
from server.protocol import ProtocolError,digest
from server.protocol_journal import JournalError
from server.trade_coordinator import COMMANDS


def issue_for_control(runtime,player,request,verify):
    """Called only after the ordinary session/challenge/watchdog validation.

    The configured verifier owns cartridge/native/recovery policy and returns
    either no authority or a typed proof bound to this exact journal state.
    This module supplies no permissive default and never clears a recovery barrier.
    """
    if not callable(verify):raise ProtocolError("operation execution policy is not configured")
    if not isinstance(request,dict) or set(request)!={"window","evidence"}:
        raise ProtocolError("complete operation window/evidence request required")
    evidence=request["evidence"]
    if not isinstance(evidence,dict) or not isinstance(evidence.get("schema"),str) or not evidence["schema"]:
        raise ProtocolError("versioned operation evidence required")
    window=request["window"]
    if not isinstance(window,dict) or not isinstance(window.get("scope"),dict):
        raise ProtocolError("operation window scope required")
    scope=window["scope"]
    identifier=scope.get("operation_id")
    command=runtime.journal.command(player,identifier)
    pending=runtime.journal.pending_ids(player)
    if command["outcome"] is not None or not pending or pending[0]!=identifier:
        raise JournalError("operation window must name the oldest pending command")
    if command["body"].get("cmd") in COMMANDS:
        if runtime.trade is None:raise JournalError("native trade policy is not configured")
        runtime.trade.authorize_delivery(player,identifier,owner=runtime.gate.sessions[player].owner)
    stage=runtime.state()
    revision=stage.journal_revision
    document=stage.document()
    binding=copy.deepcopy(runtime.gate.sessions[player].metadata["control_binding"])
    owners={p:(session.owner,copy.deepcopy(session.metadata)) for p,session in runtime.gate.sessions.items()}
    def current():
        now=runtime._now()
        return (runtime._failed is None and set(runtime.gate.sessions)=={"a","b"}
            and set(runtime._control_seen)=={"a","b"} and all(now-seen<TIMEOUT for seen in runtime._control_seen.values())
            and all(p in owners and session.owner is owners[p][0] and session.metadata==owners[p][1]
                    for p,session in runtime.gate.sessions.items()))
    if not current():raise JournalError("fresh unchanged paired owners required for operation authority")
    proof=verify(player,copy.deepcopy(command),copy.deepcopy(evidence),copy.deepcopy(document),copy.deepcopy(binding))
    if not current() or runtime.journal.snapshot().revision!=revision:
        raise JournalError("operation authorization changed during verification")
    if proof is None:return None
    if not isinstance(proof,(VerifiedExecutionWindow,VerifiedHeldWrite)) or proof.state_digest!=digest(document):
        raise JournalError("operation proof lacks the current verified journal-state binding")
    expected=command_scope(command,binding,phase=proof.scope["phase"])
    if dict(proof.scope)!=expected:raise JournalError("operation proof differs from the trusted command/context")
    return issue_write(window,proof) if isinstance(proof,VerifiedHeldWrite) else issue(window,proof)
