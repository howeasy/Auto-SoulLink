"""RBY coordinator policy using native UI/preparation/save/closure evidence.

The observation owner supplies current checkpoints. This policy does not invent
bootstrap, consent, ordinary execution or controlled recovery from lost context.
Remote save paths are opaque receipt metadata, never server filesystem inputs.
"""
import copy

from server.gen1_native_execution import NativeExecutionPolicy
from server.gen1_native_trade_receipts import (
    _bytes,
    verify_native_release,
    verify_native_trade_receipt,
)
from server.gen1_trade_preparation import SYMBOLS, preparation_payload, verify_preparation
from server.gen1_trade_rules import Gen1TradeRules
from server.gen1_trade_ui_receipts import verify_partner_prompt, verify_receptionist_offer
from server.identity_registry import (
    IdentityContext,
    IdentityRegistry,
    IdentityWitness,
    MigrationWitness,
)
from server.protocol import digest
from server.protocol_journal import JournalError
from server.save_file_receipt import verify_file_image
from server.save_identity import SaveIdentity
from server.trade_coordinator import TradeVerification


def contexts(document):
    return {p:IdentityContext(**{**raw,"save_identity":SaveIdentity(**raw["save_identity"])})
        for p,raw in document["identities"]["contexts"].items()}


class NativeTradePolicy:
    def __init__(self):
        self.runtime=None
        self.control=object()
        self.prepared={}

    def configure(self,execution,*,read_checkpoints,read_candidate_checkpoints=None):
        if (self.runtime is not None or not isinstance(execution,NativeExecutionPolicy)
                or execution.runtime is None or not callable(read_checkpoints)
                or getattr(execution.runtime.trade.policy,"policy",None) is not self
                or read_candidate_checkpoints is not None and not callable(read_candidate_checkpoints)):
            raise JournalError("matching owned native runtime and observation reader required")
        self.execution=execution;self.runtime=execution.runtime
        self.rules=execution.rules;self.manifests=copy.deepcopy(execution.manifests)
        self.read_checkpoints=read_checkpoints
        self.read_candidate_checkpoints=read_candidate_checkpoints
        self.binding=Gen1TradeRules(self.rules,data_dir=self.runtime.data_dir)

    def candidate_checkpoints(self,player):
        # This reader only computes receptionist menu eligibility. offer() and
        # prepare() always retain the paired current-checkpoint reader below.
        if self.read_candidate_checkpoints is not None:
            return self.read_candidate_checkpoints(player)
        return self.read_checkpoints()

    def authorize(self,action,player,authority,state,trade):
        if self.runtime is None:return False
        valid=authority is self.control if player is None else self.runtime.gate.owns(player,authority)
        return valid and (not trade or not trade["recovery_required"] or action=="interrupt")

    def offer(self,player,payload,state):
        if self.runtime.receptionist is not None:self.runtime.receptionist.offer(player,payload)
        points=self.read_checkpoints();current=contexts(state)
        key=verify_receptionist_offer(payload,manifest=self.manifests[player],context=current[player],
            snapshot=points[player]["party"])
        return self.binding.proposal(state["rules"],IdentityRegistry.restore(state["identities"],run_id=self.runtime.journal.run_id),
            player=player,key=key,contexts=current,snapshots={p:v["party"] for p,v in points.items()})

    def install_receptionist(self):
        from server.gen1_receptionist_runtime import ReceptionistRuntime
        if self.runtime is None or self.runtime.receptionist is not None:raise JournalError('owned unselected receptionist required')
        self.runtime.receptionist=ReceptionistRuntime(self)
        return self.runtime.receptionist

    def prompt(self,trade,player):
        return {"schema":"rby-native-prompt-v1","proposal":trade["proposal"]}

    def decision(self,trade,player,command,receipt):
        return verify_partner_prompt(command,receipt,manifest=self.manifests[player]),receipt

    def prepare(self,trade,player):
        return preparation_payload(trade,player,rules=self.rules,checkpoints=self.read_checkpoints())

    def ready(self,trade,player,command,receipt):
        from server.gen1_full_save import verify_receipt
        if (not isinstance(receipt,dict) or set(receipt)!={'schema','stages'} or receipt['schema']!='rby-saved-ready-v1'
                or not isinstance(receipt['stages'],dict) or set(receipt['stages'])!={'prompt','save','ready'}):
            raise JournalError('full-save preparation stages are required')
        ready=receipt['stages']['ready']
        prepared=verify_preparation(command,ready,rules=self.rules[player])
        verify_receipt(self,trade,player,command,receipt['stages']['save'],ready['checkpoint'])
        from server.gen1_prompt_execution import verify_preparation_prompt
        verify_preparation_prompt(self,trade,player,command,receipt['stages']['prompt'],receipt['stages']['save']['point'])
        # Cache is not authority: every use rechecks its digest against the committed
        # PreparedTrade. The trade composition hook retains the same verified stages in the
        # trade_ready commit (gen1_native_preparation), so a reopened runtime reads them back.
        if self.prepared.get("transaction_id")!=trade["id"]:
            self.prepared={"transaction_id":trade["id"],"players":{}}
        self.prepared["players"][player]={"checkpoint":copy.deepcopy(ready["checkpoint"]),
            "save":copy.deepcopy(receipt["stages"]["save"]),"prompt":copy.deepcopy(receipt["stages"]["prompt"])}
        return prepared

    def _cached_checkpoint(self,trade,player):
        stage=self.prepared.get("players",{}).get(player)
        if self.prepared.get("transaction_id")!=trade["id"] or stage is None:return None
        return stage["checkpoint"] if isinstance(stage,dict) and "checkpoint" in stage else stage

    def checkpoint(self,trade,player):
        expected=trade["ready"][player]["details"]["checkpoint_digest"]
        point=self._cached_checkpoint(trade,player)
        if point is None and self.runtime is not None:
            from server.gen1_native_preparation import stored
            entry=stored(self.runtime.state().document(),trade["id"],player)
            if entry is not None:
                point=entry["checkpoint"]
                if digest(point)==expected:
                    self.prepared.setdefault("players",{})
                    if self.prepared.get("transaction_id")!=trade["id"]:
                        self.prepared={"transaction_id":trade["id"],"players":{}}
                    self.prepared["players"][player]={"checkpoint":copy.deepcopy(point),
                        "save":entry["save"],"prompt":entry["prompt"]}
        if point is None or digest(point)!=expected:
            raise JournalError("native preparation evidence differs from its committed proof; recovery required")
        return point

    def commit(self,trade,state,authority):
        for player in ("a","b"):self.checkpoint(trade,player)
        return {"schema":"rby-native-commit-authority-v1",
            "prepared":{p:trade["ready"][p]["details"]["checkpoint_digest"] for p in ("a","b")}}

    def applied(self,trade,player,command,receipt):
        verify_native_trade_receipt(command,receipt,rules=self.rules[player],
            boxed_keys=trade["ready"][player]["details"]["boxed_keys"])
        return receipt

    def verified(self,trade,player,command,receipt):
        if (not isinstance(receipt,dict) or set(receipt)!={"schema","native","file","save_image_hex"}
                or receipt["schema"]!="rby-file-backed-v1" or receipt["native"]!=trade["applied"][player]):
            raise JournalError("complete native and file-image evidence required")
        native=receipt["native"]
        result=verify_native_trade_receipt(command,native,rules=self.rules[player],
            boxed_keys=trade["ready"][player]["details"]["boxed_keys"])
        image=_bytes(receipt["save_image_hex"],0x8000)
        proof=receipt["file"]
        binding=self.runtime.gate.sessions[player].metadata["control_binding"]
        progress=self.execution.observed.get((player,command["command_id"],binding["binding_digest"]))
        # The previous window can still be consumed while a renewal is in flight.
        if progress is None:
            raise JournalError("file flush is outside the owned native frame window")
        verify_file_image(proof,image,host_profile='bizhawk-2.11.1-gambatte-exclusive-hold-v1',
            frame_from=progress['frame'],frame_to=progress['frame']+120)
        region=self.manifests[player]["readback"]["save"]
        if image[region["address"]:region["address"]+region["length"]]!=_bytes(native["after"]["save_region_hex"]):
            raise JournalError("file image differs from verified canonical native save")
        before=_bytes(self.checkpoint(trade,player)["cart_hex"],0x8000)
        symbols=SYMBOLS["pokeyellow" if self.rules[player].variant=="yellow" else "pokered"]
        sprite_start=symbols["sSpriteBuffer0"]-0xA000
        sprite_end=symbols["sSpriteBuffer2"]-0xA000+symbols["sSpriteBuffer1"]-symbols["sSpriteBuffer0"]
        # Only sprite workspace in bank0 may differ; Hall of Fame, bank padding
        # and inactive PC storage remain protected. The bank1 region was checked
        # byte-for-byte by the independent native result verifier above.
        if any(value!=before[i] for i,value in enumerate(image)
                if not (sprite_start<=i<sprite_end or region["address"]<=i<region["address"]+region["length"])):
            raise JournalError("native save changed data outside its verified save/sprite regions")
        own=trade["proposal"]["participants"][player]
        peer=trade["proposal"]["participants"]["b" if player=="a" else "a"]
        def context(part):
            raw=part["context"];return IdentityContext(**{**raw,"save_identity":SaveIdentity(**raw["save_identity"])})
        witness=MigrationWitness(peer["member_id"],context(peer),peer["key"],peer["evidence_digest"],
            IdentityWitness(context(own),result.received_key,result.received_digest,1))
        return TradeVerification(witness,native,proof)

    def auxiliary(self,trade,player,command,receipt):
        if command["body"]["cmd"]=="native_trade_abort":
            from server.gen1_trade_abort_receipts import verify_abort
            return verify_abort(self,trade,player,command,receipt)
        if command["body"]["cmd"]!="native_trade_release":
            raise JournalError("native cancellation/retirement policy is not selected")
        return verify_native_release(command,receipt,trade=trade)

    def finalize(self,rules,trade,migrations):
        return self.binding.finalize(rules,trade,migrations)
