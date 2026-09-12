"""RBY native COMMIT/release frame policy beneath the owned control-response gate.

No ordinary or recovery execution is granted. Initial native intent must match
the persisted preparation and admitted ROM; later windows must retain that exact
intent and the original routine prefix in the same live server/host binding.
"""
import copy
import re

from server.execution_window import VerifiedExecutionWindow, command_scope
from server.gen1_native_trade_receipts import SEQUENCE, _bytes
from server.gen1_trade_preparation import validate_checkpoint
from server.gen1_trade_result import TradeResultRules
from server.protocol import digest
from server.protocol_journal import JournalError
from server.trade_coordinator import COMMITTED, NAMESPACE

SCHEMA = "rby-native-window-evidence-v1"
LIMIT = 60000  # Includes time in original move-learning UI; pause spends no frames.


class NativeExecutionPolicy:
    def __init__(self, *, rules, manifests, fallback=None):
        from server.gen1_held_faint import verify as held_verifier
        if fallback is not None and fallback is not held_verifier:
            raise JournalError("only the qualified held-write verifier may compose with native execution")
        self.fallback = fallback
        if set(rules) != {"a", "b"} or set(manifests) != {"a", "b"}:
            raise JournalError("both admitted native cartridges required")
        self.rules, self.manifests = dict(rules), copy.deepcopy(manifests)
        for p in rules:
            if (not isinstance(rules[p], TradeResultRules) or rules[p].rom_sha1 != manifests[p]["final_sha1"]
                    or manifests[p]["schema"] != "gen1-native-trade-build-v1" or manifests[p]["test_probe"] is not None):
                raise JournalError("qualified native manifest and exact ROM rules required")
        self.runtime = None
        self.observed = {}
        self.published = {}

    def bind(self, runtime):
        if self.runtime is not None:raise JournalError("native execution policy already owns a runtime")
        self.runtime = runtime

    def __call__(self, player, command, evidence, document, binding):
        runtime = self.runtime
        if runtime is None or runtime.journal.snapshot().state != document:
            raise JournalError("native execution needs its current owned runtime")
        body = command["body"]
        if self.fallback is not None and body["cmd"] in {"initial_save", "force_faint", "memorialize", "acquisition_retire", "storage_apply"}:
            return self.fallback(player, command, evidence, document, binding)
        if body["cmd"] not in {"native_receptionist","native_trade_commit", "native_trade_release", "native_trade_prompt", "native_trade_prepare", "native_trade_abort"}:return None
        fields = {"schema", "command_id", "command_sequence", "context_generation", "final_sha1", "host", "native"}
        if player in document["components"].get("gen1-frame-progress", {}):
            fields.add("accounting")
        if (not isinstance(evidence, dict) or set(evidence) != fields or evidence["schema"] != SCHEMA
                or evidence["command_id"] != command["command_id"]
                or type(evidence["command_sequence"]) is not int or evidence["command_sequence"] != command["command_sequence"]
                or evidence["context_generation"] != binding["context_generation"]
                or evidence["final_sha1"] != self.rules[player].rom_sha1):
            raise JournalError("native window command/context/artifact differs")
        admitted = runtime.gate.sessions[player].metadata
        if admitted["gen1_metadata"]["cartridge"]["final_rom_sha1"] != self.rules[player].rom_sha1:
            raise JournalError("native rules differ from current cartridge admission")
        host = evidence["host"]
        host_fields = {"owner_id", "capability_id", "process_id", "frame", "steps", "held", "bounded", "failed"}
        if (not isinstance(host, dict) or set(host) != host_fields
                or host["owner_id"] != admitted["gen1_metadata"]["physical_instance"]
                or host["capability_id"] != "bizhawk-2.11.1-gambatte-exclusive-hold-v1"
                or host["held"] is not True or host["bounded"] is not True or host["failed"] is not False
                or any(type(host[n]) is not int or not 0 <= host[n] <= 2**53-1 for n in ("frame", "steps"))
                or type(host["process_id"]) is not int or host["process_id"] < 1):
            raise JournalError("owned bounded native host evidence required")
        if body['cmd']=='native_receptionist':
            if runtime.receptionist is None:raise JournalError('native receptionist policy is not selected')
            return runtime.receptionist.window(player,command,evidence,document,binding)
        trade = runtime.journal.record(NAMESPACE, body["transaction_id"]).value
        if trade["recovery_required"]:return None
        native = evidence["native"]
        if not isinstance(native, dict):raise JournalError("native phase evidence required")
        saving=body['cmd']=='native_trade_prepare' and native.get('phase')=='full_save'
        scope = command_scope(command, binding, phase='native_trade_prepare_save' if saving else body["cmd"])
        key = (player, command["command_id"], binding["binding_digest"])
        previous = self.observed.get(key)
        if previous and (host["process_id"] != previous["process_id"] or host["frame"] < previous["frame"]
                or host["steps"] < previous["steps"] or host["frame"]-previous["frame"] != host["steps"]-previous["steps"]):
            raise JournalError("native physical frame continuity changed")
        extra = {}
        if saving:
            from server.gen1_full_save import window
            result=window(self,player,command,native,binding,trade,previous)
            if result is None:return None
            fingerprint,armed,extra=result
        elif body["cmd"] in {"native_trade_prompt", "native_trade_prepare", "native_trade_abort"}:
            from server.gen1_prompt_execution import closure_window, prompt_window
            check = prompt_window if body["cmd"] == "native_trade_prompt" else closure_window
            result = check(self, player, command, native, binding, trade, previous)
            if result is None:return None
            fingerprint, armed, extra = result
        elif body["cmd"] == "native_trade_commit":
            if trade["phase"] not in COMMITTED or trade["phase"] == "link_committed":return None
            if native.get("phase") == "complete":return None
            if native.get("phase") == "before":
                if set(native) != {"phase", "intent", "checkpoint"} or previous and previous["armed"]:
                    raise JournalError("native before evidence changed after arming")
                payload = body["payload"];prepared = payload["prepared"]
                if (payload["schema"] != "paired-native-commit-v1" or digest(payload["proposal"]) != body["proposal_digest"]
                        or prepared != trade["ready"][player] or digest(prepared) != payload["prepared_digest"]
                        or digest(native["checkpoint"]) != prepared["details"]["checkpoint_digest"]):
                    raise JournalError("native execution differs from persisted paired preparation")
                own = payload["proposal"]["participants"][player]
                validate_checkpoint(native["checkpoint"], rules=self.rules[player], participant=own)
                intent = native["intent"]
                self._intent(command, intent, native["checkpoint"], binding)
                fingerprint = digest(intent)
                if previous and fingerprint != previous["intent_digest"]:
                    raise JournalError("prepared native intent changed within its binding")
                armed = False
            elif native.get("phase") == "armed":
                if set(native) != {"phase", "intent_digest", "sequence"} or previous is None:
                    raise JournalError("native arming has no verified initial window")
                sequence = native["sequence"]
                if (native["intent_digest"] != previous["intent_digest"] or not isinstance(sequence, list)
                        or sequence != SEQUENCE[:len(sequence)] or len(sequence) > len(SEQUENCE)
                        or len(sequence) < previous.get("sequence_length", 0)):
                    raise JournalError("native original execution prefix/intent differs")
                fingerprint, armed = previous["intent_digest"], True
            else:raise JournalError("unsupported native COMMIT phase")
        else:
            if trade["phase"] != "link_committed":return None
            if native.get("phase") == "released":return None
            if (set(native) != {"phase", "native_command_id", "native_intent_digest", "after"}
                    or native["phase"] not in {"before", "releasing"}):
                raise JournalError("native release evidence required")
            applied = trade["applied"][player]
            commit_key = (player, applied["command_id"], binding["binding_digest"])
            committed = self.observed.get(commit_key)
            if (committed is None or native["native_command_id"] != applied["command_id"]
                    or native["native_intent_digest"] != committed["intent_digest"]
                    or native["after"] != applied["after"]):
                raise JournalError("native release lacks its verified live COMMIT context")
            fingerprint, armed = native["native_intent_digest"], native["phase"] == "releasing"
            if armed and previous is None:raise JournalError("release has no initial execution window")
        return self.publish(player,command,evidence,document,binding,scope,fingerprint,armed,
                            {'sequence_length':len(native.get('sequence',[])),**extra})

    def publish(self,player,command,evidence,document,binding,scope,fingerprint,armed,extra):
        host=evidence['host'];key=(player,command['command_id'],binding['binding_digest']);previous=self.observed.get(key)
        if previous and (host['process_id']!=previous['process_id'] or host['frame']<previous['frame']
                or host['steps']<previous['steps'] or host['frame']-previous['frame']!=host['steps']-previous['steps']):
            raise JournalError('native physical frame continuity changed')
        start = previous["start"] if previous else host["frame"]
        remaining = LIMIT-(host["frame"]-start)
        if remaining <= 0:return None
        self.observed[key] = {"process_id": host["process_id"], "frame": host["frame"], "steps": host["steps"],
            "start": start, "intent_digest": fingerprint, "armed": armed,
            **extra}
        proof = VerifiedExecutionWindow(scope, digest(evidence), min(60, remaining), 1000, state_digest=digest(document))
        self.published[key] = proof
        return proof

    def _intent(self, command, intent, checkpoint, binding):
        body = command["body"];payload = body["payload"]
        own = payload["proposal"]["participants"][body["player"]]
        peer = payload["proposal"]["participants"]["b" if body["player"] == "a" else "a"]
        detail = payload["prepared"]["details"]
        fields = {"schema", "command_id", "command_sequence", "body_digest", "context_generation", "before",
                  "request", "token_hex", "generation", "union_hex"}
        expected = {"slot": own["slot"], "incoming": peer["snapshot"]["party"][peer["slot"]],
            "peer_name_hex": detail["peer_name_hex"], "expected_key": own["key"], "incoming_key": peer["key"],
            "evolved_species": detail["evolved_species"]}
        if (not isinstance(intent, dict) or set(intent) != fields or intent["schema"] != "gen1-native-trade-intent-v1"
                or intent["command_id"] != command["command_id"] or type(intent["command_sequence"]) is not int
                or intent["command_sequence"] != command["command_sequence"] or intent["body_digest"] != digest(body)
                or intent["context_generation"] != binding["context_generation"] or intent["request"] != expected
                or type(intent["generation"]) is not int or not 1 <= intent["generation"] <= 255
                or not isinstance(intent["token_hex"], str) or not re.fullmatch("[0-9A-F]{8}", intent["token_hex"])
                or intent["token_hex"] == "00000000"):
            raise JournalError("native prepared intent differs from the exact command")
        _bytes(intent["union_hex"], 16)
        before = intent["before"];region = self.manifests[body["player"]]["readback"]["save"]
        cart = _bytes(checkpoint["cart_hex"], 0x8000)
        expected_fields = {"party", "party_storage_hex", "save_region_hex", "dex_hex", "save_name_hex", "map"}
        if self.rules[body["player"]].variant == "yellow":expected_fields.add("pikachu_hex");_bytes(before.get("pikachu_hex"), 2)
        if (set(before) != expected_fields or before["party"] != checkpoint["party"]
                or before["party_storage_hex"] != checkpoint["party_storage_hex"] or before["map"] != checkpoint["map"]
                or before["save_name_hex"] != checkpoint["name_hex"]
                or _bytes(before["save_region_hex"], region["length"]) != cart[region["address"]:region["address"]+region["length"]]):
            raise JournalError("native intent readback differs from its prepared checkpoint")
        _bytes(before["dex_hex"], 38)
