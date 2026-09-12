"""Bound pre-COMMIT retirement, with native prompt closure where required."""
from server.gen1_trade_preparation import validate_checkpoint
from server.gen1_trade_ui_receipts import verify_partner_prompt
from server.protocol_journal import JournalError


def verify_abort(policy, trade, player, command, receipt):
    body=command["body"]
    if (body["cmd"]!="native_trade_abort" or body["payload"]["schema"]!="trade-abort-v1"
            or trade["phase"] not in {"cancelled","declined","expired"}
            or body["payload"]["terminal_phase"]!=trade["phase"] or trade["applied"] or trade["verified"]):
        raise JournalError("only an uncommitted trade can be retired")
    fields={"schema","command_id","command_sequence","transaction_id","proposal_digest","context_generation","final_sha1"}
    closing=isinstance(receipt,dict) and receipt.get("schema")=="rby-prompt-closure-v1"
    fields.update({"prompt_command_id","after"} if closing else {"checkpoint"})
    if (not isinstance(receipt,dict) or set(receipt)!=fields
            or receipt["schema"] not in {"rby-prompt-closure-v1","rby-trade-abort-v1"}):
        raise JournalError("typed native abort/closure receipt required")
    for key in ("command_id","command_sequence"):
        if type(receipt[key]) is not type(command[key]) or receipt[key]!=command[key]:
            raise JournalError("abort command identity differs")
    own=trade["proposal"]["participants"][player]
    if (receipt["transaction_id"]!=trade["id"] or receipt["proposal_digest"]!=trade["proposal_digest"]
            or receipt["context_generation"]!=own["context"]["context_generation"]
            or receipt["final_sha1"]!=policy.manifests[player]["final_sha1"]):
        raise JournalError("abort transaction/context/cartridge differs")
    if closing:
        prompt=policy.runtime.journal.command(player,receipt["prompt_command_id"])
        if (prompt["body"]["cmd"]!="native_trade_prompt" or prompt["body"]["transaction_id"]!=trade["id"]
                or prompt["outcome"]!="ACK"):
            raise JournalError("prompt return lacks its acknowledged decision")
        verify_partner_prompt(prompt,prompt["receipt"],manifest=policy.manifests[player])
        binding=policy.runtime.gate.sessions[player].metadata["control_binding"]
        initial=policy.execution.observed.get((player,prompt["command_id"],binding["binding_digest"]))
        closing_window=policy.execution.observed.get((player,command["command_id"],binding["binding_digest"]))
        if (initial is None or closing_window is None or initial["intent_digest"]!=closing_window["intent_digest"]
                or receipt["after"]!=prompt["receipt"]["after"]):
            raise JournalError("native prompt closure lacks its current verified return window")
    else:
        if player!=trade["initiator"]:
            raise JournalError("prompt participant requires a native closure receipt")
        validate_checkpoint(receipt["checkpoint"],rules=policy.rules[player],participant=own)
    return receipt
