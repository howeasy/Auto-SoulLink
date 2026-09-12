"""Network boundary for finite RBY startup frames; never grants an unbounded run."""

import secrets

from server.admission_context import same_admitted_context
from server.execution_window import VerifiedExecutionWindow
from server.gen1_frame_journal import enroll, grant
from server.gen1_frame_runtime import COMPONENT, validate_boundary
from server.gen1_initial_observation import REASON as INITIAL_HOLD
from server.protocol import ProtocolError, digest
from server.protocol_journal import JournalError


def issue_for_control(runtime, player, request):
    if not isinstance(request, dict) or set(request) != {"window", "evidence"}:
        raise ProtocolError("complete frame window/evidence request required")
    evidence = request["evidence"]
    if (
        not isinstance(evidence, dict)
        or set(evidence) != {"schema", "boundary", "sequence"}
        or evidence["schema"] != "rby-frame-request-v1"
        or type(evidence["sequence"]) is not int
        or not 1 <= evidence["sequence"] <= 2**53 - 1
    ):
        raise ProtocolError("typed sequential frame request required")
    stage = runtime.state()
    document = stage.document()
    from server.gen1_native_frame_accounting import borrowed
    if borrowed(document, player):
        return None
    initials = document["components"].get("gen1-initial-observations", {})
    saves = document["components"].get("gen1-initial-save", {})
    if (
        set(initials) != {"a", "b"}
        or set(saves) != {"a", "b"}
        or any(saves[p]["receipt_operation"] is None for p in ("a", "b"))
    ):
        return None
    if set(runtime.gate.sessions) != {"a", "b"}:
        return None
    for p in ("a", "b"):
        if not same_admitted_context(initials[p]["metadata"], runtime.gate.sessions[p].metadata):
            raise JournalError("frame request replaced its enrolled physical context")
    if (
        stage.rules.run_over
        or document["active_trade"] is not None
        or any(runtime.journal.pending_ids(p) for p in ("a", "b"))
        or any(reason != INITIAL_HOLD for reason in stage.barrier.document()["blockers"].values())
    ):
        return None
    # Initial network integration is intentionally bounded to pre-ball gameplay.
    # Active capture/battle-command policies must be connected before widening it.
    if any(stage.rules.pokeballs_obtained.values()):
        return None
    initial = initials[player]
    entries = document["components"].get(COMPONENT, {})
    if player not in entries:
        validate_boundary(
            evidence["boundary"], initial=initial, frame=initial["observation"]["frame"]
        )
        if evidence["sequence"] != 1:
            raise JournalError("first frame request must start at enrollment")
        enroll(runtime, player, secrets.token_hex(16))
        document = runtime.state().document()
    entry = document["components"][COMPONENT][player]
    ledger = entry["ledger"]
    validate_boundary(evidence["boundary"], initial=initial, frame=ledger["frame"])
    if entry["pending_observation"] is not None:
        return None
    window = request["window"]
    if not isinstance(window, dict) or not isinstance(window.get("scope"), dict):
        raise ProtocolError("typed frame scope required")
    scope = window["scope"]
    binding = runtime.gate.sessions[player].metadata["control_binding"]
    if (
        scope.get("context_generation") != binding["context_generation"]
        or scope.get("binding_digest") != binding["binding_digest"]
        or scope.get("phase") != "ordinary"
    ):
        raise JournalError("frame scope differs from admitted ownership")
    if ledger["pending"] is not None:
        if scope != ledger["pending"]["scope"] or evidence["sequence"] != ledger["sequence"]:
            return None
    elif evidence["sequence"] != ledger["sequence"] + 1:
        raise JournalError("frame request skipped or repeated its sequence")
    semantic = {"event": "frame_grant", "window": window, "evidence": evidence}
    try:
        proof = VerifiedExecutionWindow(scope, digest(evidence), 60, 1000, digest(document))
    except (TypeError, ValueError) as error:
        raise JournalError("invalid finite frame scope") from error
    result = grant(runtime, player, scope["operation_id"], semantic, proof)
    return result["frame_window"]
