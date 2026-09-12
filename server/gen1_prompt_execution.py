"""RBY prompt/acknowledged-return evidence inside the shared native window gate."""
import hashlib
import re

from server.gen1_native_trade_receipts import _bytes
from server.gen1_trade_preparation import validate_checkpoint
from server.gen1_trade_ui_receipts import validate_prompt_view, verify_partner_prompt
from server.protocol import digest
from server.protocol_journal import JournalError

ORDER = ["service", "prompt", "choice"]


def verify_preparation_prompt(policy,trade,player,command,receipt,save_point):
    own=trade['proposal']['participants'][player]
    identity={'command_id':command['command_id'],'command_sequence':command['command_sequence'],
              'context_generation':own['context']['context_generation']}
    if player==trade['initiator']:
        if receipt!={'schema':'rby-no-prompt-close-v1',**identity}:
            raise JournalError('initiator preparation has a foreign prompt obligation')
        return
    fields={'schema','command_id','command_sequence','context_generation','transaction_id',
            'proposal_digest','prompt_command_id','final_sha1','after'}
    if (not isinstance(receipt,dict) or set(receipt)!=fields or receipt['schema']!='rby-prompt-closure-v1'
            or any(type(receipt[k]) is not type(v) or receipt[k]!=v for k,v in identity.items())
            or receipt['transaction_id']!=trade['id'] or receipt['proposal_digest']!=trade['proposal_digest']
            or receipt['final_sha1']!=policy.manifests[player]['final_sha1']):
        raise JournalError('preparation lacks its exact native prompt return')
    prompt=policy.runtime.journal.command(player,receipt['prompt_command_id'])
    if (prompt['body']['cmd']!='native_trade_prompt' or prompt['body']['transaction_id']!=trade['id']
            or prompt['body']['proposal_digest']!=trade['proposal_digest'] or prompt['outcome']!='ACK'
            or not verify_partner_prompt(prompt,prompt['receipt'],manifest=policy.manifests[player])
            or receipt['after']!=prompt['receipt']['after']):
        raise JournalError('preparation prompt decision differs')
    binding=policy.runtime.gate.sessions[player].metadata['control_binding']
    initial=policy.execution.observed.get((player,prompt['command_id'],binding['binding_digest']))
    if (initial is None or initial.get('prompt_before')!=prompt['receipt']['before']
            or hashlib.sha256(save_point['cart_hex'].encode('ascii')).hexdigest()!=receipt['after']['cart_digest']):
        raise JournalError('full save did not follow the acknowledged native prompt')


def prompt_window(policy, player, command, native, binding, trade, previous):
    body = command["body"]
    if trade["phase"] != "offered" or player == trade["initiator"]:
        return None
    if native.get("phase") == "complete":
        return None
    if native.get("phase") == "before":
        if set(native) != {"phase", "intent", "checkpoint"} or previous and previous["armed"]:
            raise JournalError("prompt before evidence changed after arming")
        payload = body["payload"]
        if (payload["schema"] != "rby-native-prompt-v1" or payload["proposal"] != trade["proposal"]
                or digest(payload["proposal"]) != body["proposal_digest"]):
            raise JournalError("prompt differs from the persisted proposal")
        own = trade["proposal"]["participants"][player]
        peer = trade["proposal"]["participants"]["b" if player == "a" else "a"]
        point = native["checkpoint"]
        validate_checkpoint(point, rules=policy.rules[player], participant=own)
        intent = native["intent"]
        fields = {"schema", "command_id", "command_sequence", "body_digest", "context_generation",
                  "before", "request", "generation", "token_hex", "union_hex"}
        if (not isinstance(intent, dict) or set(intent) != fields or intent["schema"] != "rby-partner-prompt-intent-v1"
                or intent["command_id"] != command["command_id"] or type(intent["command_sequence"]) is not int
                or intent["command_sequence"] != command["command_sequence"] or intent["body_digest"] != digest(body)
                or intent["context_generation"] != binding["context_generation"]
                or intent["request"] != {"slot": own["slot"], "incoming": peer["snapshot"]["party"][peer["slot"]]}
                or type(intent["generation"]) is not int or not 1 <= intent["generation"] <= 255
                or not isinstance(intent["token_hex"], str) or not re.fullmatch("[0-9A-F]{8}", intent["token_hex"])
                or intent["token_hex"] == "00000000"):
            raise JournalError("native prompt intent differs from its command/context")
        _bytes(intent["union_hex"], 16)
        before = intent["before"]
        validate_prompt_view(before, manifest=policy.manifests[player], participant=own)
        if (before["party"] != point["party"] or before["party_storage_hex"] != point["party_storage_hex"]
                or before["map"] != point["map"]
                or before["cart_digest"] != hashlib.sha256(point["cart_hex"].encode("ascii")).hexdigest()):
            raise JournalError("prompt view differs from its physical checkpoint")
        fingerprint = digest(intent)
        if previous and fingerprint != previous["intent_digest"]:
            raise JournalError("prompt intent changed within its binding")
        return fingerprint, False, {"prompt_before": before}
    if native.get("phase") == "armed":
        if set(native) != {"phase", "intent_digest", "sequence"} or previous is None:
            raise JournalError("prompt arming has no initial verified window")
        sequence = native["sequence"]
        if (native["intent_digest"] != previous["intent_digest"] or not isinstance(sequence, list)
                or sequence != ORDER[:len(sequence)] or len(sequence) > len(ORDER)
                or len(sequence) < previous.get("sequence_length", 0)):
            raise JournalError("native prompt execution prefix/intent changed")
        return previous["intent_digest"], True, {"prompt_before": previous["prompt_before"]}
    raise JournalError("unsupported native prompt phase")


def closure_window(policy, player, command, native, binding, trade, previous):
    body = command["body"]
    allowed = {"preparing", "both_prepared"} if body["cmd"] == "native_trade_prepare" else {"cancelled", "declined", "expired"}
    if trade["phase"] not in allowed or player == trade["initiator"]:
        return None
    if body["cmd"]=="native_trade_prepare":
        if body["payload"]["schema"]!="rby-native-prepare-v1" or body["payload"]["proposal"]!=trade["proposal"]:
            raise JournalError("native preparation closure payload differs")
    elif body["payload"]["schema"]!="trade-abort-v1" or body["payload"]["terminal_phase"]!=trade["phase"]:
        raise JournalError("native abort closure payload differs")
    if native.get("phase") == "prompt_closed":
        return None
    if (set(native) != {"phase", "prompt_command_id", "prompt_intent_digest", "receipt"}
            or native["phase"] not in {"prompt_before", "prompt_closing"}):
        raise JournalError("acknowledged native prompt closure evidence required")
    prompt = policy.runtime.journal.command(player, native["prompt_command_id"])
    if (prompt["body"]["cmd"] != "native_trade_prompt" or prompt["body"]["transaction_id"] != body["transaction_id"]
            or prompt["body"]["proposal_digest"] != body["proposal_digest"] or prompt["outcome"] != "ACK"
            or prompt["receipt"] != native["receipt"]):
        raise JournalError("prompt closure lacks its exact acknowledged decision")
    accepted = verify_partner_prompt(prompt, native["receipt"], manifest=policy.manifests[player])
    if body["cmd"] == "native_trade_prepare" and not accepted:
        raise JournalError("declined prompt cannot authorize preparation")
    start = policy.observed.get((player, prompt["command_id"], binding["binding_digest"]))
    if (start is None or native["prompt_intent_digest"] != start["intent_digest"]
            or native["receipt"]["before"] != start["prompt_before"]):
        raise JournalError("prompt return has no verified live context")
    armed = native["phase"] == "prompt_closing"
    if armed and previous is None or previous and previous["armed"] and not armed:
        raise JournalError("prompt closure lost its initial window or regressed")
    return start["intent_digest"], armed, {}
