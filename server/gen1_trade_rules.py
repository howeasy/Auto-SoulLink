"""RBY trade selection/finalization against the complete staged Soul Link rules.

Call only inside TradeCoordinator's detached policy callbacks. This module
does not persist, send, admit a cartridge, or authorize native execution.
"""
from __future__ import annotations

import copy

from server.gen1_command_receipts import validate_party_snapshot
from server.gen1_staged_state import StagedGen1State
from server.identity_registry import IdentityContext, IdentityRegistry, MigrationWitness
from server.protocol_journal import JournalError
from server.state import LinkStatus
from server.trade_coordinator import TradeParticipant, TradeProposal


class Gen1TradeRules:
    def __init__(self, result_rules, *, data_dir):
        if set(result_rules) != {"a", "b"}:
            raise JournalError("both cartridge result policies required")
        self.results = dict(result_rules)
        self.data_dir = str(data_dir)

    def _state(self, document):
        return StagedGen1State.restore(document, data_dir=self.data_dir)

    @staticmethod
    def _eligible(state, player, key):
        pair = state.find_link(player, key)
        if (state.run_over or not state.pc_trade_npc or pair is None or pair.status != LinkStatus.ALIVE
                or pair.a is None or pair.b is None):
            raise JournalError("one live linked pair is required for trade")
        for pid in ("a", "b"):
            half = getattr(pair, pid)
            if (half.key not in state.party_keys[pid] or half.key in state.pending_memorials[pid]
                    or state.rebuild_pending[pid] is not None
                    or any(command.get("key") == half.key for command in state.queued_commands[pid])):
                raise JournalError("both linked members must be in their parties without pending physical work")
        return pair

    def proposal(self, document, registry: IdentityRegistry, *, player, key, contexts, snapshots):
        state = self._state(document)
        pair = self._eligible(state, player, key)
        members, participants = [], []
        for pid in ("a", "b"):
            context = contexts[pid]
            if not isinstance(context, IdentityContext) or context.player != pid or context.game_id != "gen1_rby":
                raise JournalError("current RBY physical context required")
            saved = state.player_identity.get(pid)
            if saved != {"ot_id": context.save_identity.ot_id, "trainer_name": context.save_identity.trainer_name}:
                raise JournalError("rule identity differs from the admitted trade participant")
            snapshot = snapshots[pid]
            party = validate_party_snapshot(snapshot, variant=self.results[pid].variant)
            if (snapshot["battle_flag"] != 0 or snapshot["save_id"] != context.save_identity.ot_id
                    or snapshot["save_name"] != context.save_identity.trainer_name):
                raise JournalError("trade party/save checkpoint differs")
            half = getattr(pair, pid)
            slots = [index for index, mon in enumerate(party) if mon.key == half.key]
            if len(slots) != 1 or party[slots[0]].hp == 0:
                raise JournalError("selected live member is not uniquely present in the physical party")
            cached = sorted(state.partner_blobs[pid], key=lambda item: item["slot"])
            if [row["blob"] for row in cached] != [mon.raw for mon in party]:
                raise JournalError("physical party differs from the reconciled complete rule snapshot")
            mon = party[slots[0]]
            member = registry.resolve(context, mon.key)
            if member is None:
                raise JournalError("trade member has no committed logical identity")
            members.append(member)
            participants.append(TradeParticipant(context, member, mon.key, slots[0], mon.sha256,
                {"schema": "rby-native-party-v1", "party": [mon.raw.hex().upper() for mon in party]}))
        matches = [link_id for link_id, link in registry.document()["links"].items()
                   if set(link["members"]) == set(members)]
        if len(matches) != 1:
            raise JournalError("rule pair differs from committed logical linkage")
        return TradeProposal(matches[0], *participants)

    def finalize(self, document, trade, migrations):
        if trade.get("phase") != "both_verified" or set(trade.get("verified", {})) != {"a", "b"}:
            raise JournalError("both verified physical results required before rule migration")
        if len(migrations) != 2 or any(not isinstance(witness, MigrationWitness) for witness in migrations):
            raise JournalError("both validated logical migrations required")
        state = self._state(document)
        participants = trade["proposal"]["participants"]
        pair = self._eligible(state, "a", participants["a"]["key"])
        if pair is not self._eligible(state, "b", participants["b"]["key"]):
            raise JournalError("prepared members no longer belong to the same rule pair")
        by_player = {w.after.context.player: w for w in migrations}
        if set(by_player) != {"a", "b"}:
            raise JournalError("migration destinations are not a complete pair")
        previous = {"a": copy.deepcopy(pair.a), "b": copy.deepcopy(pair.b)}
        next_halves, after_parties = {}, {}
        for pid in ("a", "b"):
            peer = "b" if pid == "a" else "a"
            own, sender = participants[pid], participants[peer]
            native = trade["applied"][pid]
            before = [bytes.fromhex(raw) for raw in own["snapshot"]["party"]]
            incoming = bytes.fromhex(sender["snapshot"]["party"][sender["slot"]])
            after = validate_party_snapshot(native["after"]["party"], variant=self.results[pid].variant)
            self.results[pid].verify_party(before, own["slot"], incoming, [mon.raw for mon in after],
                expected_key=own["key"], incoming_key=sender["key"], boxed_keys=())
            received = after[-1]
            witness = by_player[pid]
            if (witness.member_id != sender["member_id"] or witness.before_key != sender["key"]
                    or witness.after.key != received.key or witness.after.evidence_digest != received.sha256
                    or witness.after.context.context_generation != own["context"]["context_generation"]):
                raise JournalError("verified physical result differs from the logical migration")
            collision = state.find_link(pid, received.key)
            if collision is not None and collision is not pair:
                raise JournalError("received member collides with another rule link")
            half = previous[peer]
            half.key, half.species, half.level = received.key, received.species_id, received.level
            if received.nickname != self.results[pid].codec.validate_blob(incoming).nickname:
                # The independent result policy permits only the original engine's
                # default-name evolution replacement here. Custom names are retained.
                half.nickname = state.adapter.species_name(received.species_id).upper()
            next_halves[pid], after_parties[pid] = half, after
        # All validation precedes mutation, including recipient key collisions.
        pair.a, pair.b = next_halves["a"], next_halves["b"]
        for pid in ("a", "b"):
            old = participants[pid]["key"]
            received = after_parties[pid][-1]
            state.party_keys[pid].discard(old)
            state.party_keys[pid].add(received.key)
            state.party_size[pid] = len(after_parties[pid])
            state.mon_stats.pop(state.cache_key(pid, old), None)
            hp, attack, defense, speed, special = received.computed_stats
            state.cache_stats(pid, received.key, {"level": received.level, "maxHP": hp, "attack": attack,
                "defense": defense, "speed": speed, "spAtk": special, "spDef": special})
            state.partner_blobs[pid] = [{"slot": slot, "species_id": mon.species_id, "level": mon.level,
                "key": mon.key, "blob": mon.raw} for slot, mon in enumerate(after_parties[pid])]
        for key in {participants[p]["key"] for p in ("a", "b")} | {pair.a.key, pair.b.key}:
            state._refresh_key_projection(key)
        # No synthetic success sound, legacy trade watchdog or inferred settle timer.
        # Both native services remain held until the coordinator's release commands.
        return state.document()
