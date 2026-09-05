"""Stage Soul Link rules and memorial history without touching live state or files.

The durable dispatcher must commit document() and take_commands() in the same
journal transaction before replacing its live state or sending either outbox.
This class is not yet selected by the live dispatcher.
"""
from __future__ import annotations

import copy

from server.binary_codec import BinaryCodecError, decode_bytes, encode_bytes
from server.protocol_journal import JournalError, _encode
from server.state import SoulLinkState

SCHEMA = "slink-staged-rules-v1"
_CORE = {"links", "area_states", "pending_captures", "mon_stats", "pokeballs_obtained", "rom_type",
         "trainer_names", "player_identity", "pending_memorials", "retry_areas", "bonus_keys", "pending_bonus",
         "run_over", "attempts_count", "rebuild_pending", "species_lock", "gender_lock", "type_lock",
         "explode_mode", "rival_team_swap", "overworld_presence", "native_messages", "native_sounds", "battle_calc", "pc_trade_npc"}
_RUNTIME = {"party_keys", "party_size", "_has_helld", "partner_blobs", "dupe_notified_areas", "queued_commands",
            "player_badges", "identity_error", "pending_trade", "_trade_token", "_trade_settle_ticks", "is_rr"}
_INTERNAL = {"_data_dir", "_links_path", "_memorial_path", "adapter", "_key_index", "save_failed", "_journal_memorial"}
_SET_MAPS = {"party_keys", "dupe_notified_areas"}


def _party_cache(value, adapter, *, decode=False):
    if not isinstance(value, dict) or set(value) != {"a", "b"}:
        raise JournalError("invalid per-player party cache")
    expected = adapter.party_blob_size()
    result = {}
    for player, entries in value.items():
        if not isinstance(entries, list) or len(entries) > 6 or (entries and not expected):
            raise JournalError("invalid party cache count or unsupported blob layout")
        result[player] = []
        for entry in entries:
            if not isinstance(entry, dict) or "blob" not in entry:
                raise JournalError("party cache entry must carry its complete blob")
            item = copy.deepcopy(entry)
            try:
                item["blob"] = (decode_bytes if decode else encode_bytes)(entry["blob"], expected_size=expected)
            except BinaryCodecError as exc:
                raise JournalError(str(exc)) from exc
            result[player].append(item)
    return result


class StagedSoulLinkState(SoulLinkState):
    VOLATILE_EVENTS = frozenset({"ghost_pos"})
    VOLATILE_COMMANDS = frozenset({"ghost_pos"})

    @classmethod
    def validate_game_state(cls, state):
        """Title-specific subclasses may add admission/layout restrictions."""
        if state.pending_trade is not None:
            raise JournalError("legacy trade record requires recovery before durable dispatch")
        if type(state.is_rr) is not bool:
            raise JournalError("invalid rule-adapter mode")
        if hasattr(state.adapter, "_is_rr") and state.adapter._is_rr != state.is_rr:
            raise JournalError("rule-adapter mode disagrees with state")
        cls._require_durable_commands(state.queued_commands)

    @classmethod
    def _require_durable_commands(cls, commands):
        for queue in commands.values():
            if any(isinstance(command, dict) and command.get("cmd") in cls.VOLATILE_COMMANDS for command in queue):
                raise JournalError("transient commands require the volatile channel")

    def handle_event(self, player_id, msg, **options):
        if msg.get("event") in self.VOLATILE_EVENTS:
            raise JournalError("transient events require the volatile channel")
        return super().handle_event(player_id, msg, **options)

    @classmethod
    def from_live(cls, state, memorial):
        cls.validate_game_state(state)
        unknown = set(vars(state)) - _CORE - _RUNTIME - _INTERNAL
        if unknown:
            raise JournalError("unclassified rule-state fields: " + ", ".join(sorted(unknown)))
        if not isinstance(memorial, dict) or set(memorial) != {"retired_pairs"} or not isinstance(memorial["retired_pairs"], list):
            raise JournalError("invalid memorial document")
        staged = cls.__new__(cls)
        # Adapter data is read-only during a rule transition. Preserve its identity;
        # deepcopy preserves the links/_key_index alias graph for everything else.
        staged.__dict__ = copy.deepcopy(vars(state), {id(state.adapter): state.adapter})
        staged._journal_memorial = copy.deepcopy(memorial)
        staged.save_failed = ""
        _encode(staged.document())
        return staged

    def _save(self):
        # Domain handlers may call this multiple times. The outer transaction owns
        # publication; no file or partial journal state can escape these calls.
        _encode(self.document())
        self.save_failed = ""

    def _write_memorial(self, entry):
        self._journal_memorial["retired_pairs"].append(self._memorial_record(entry))
        _encode(self.document())

    def document(self):
        self.validate_game_state(self)
        unknown = set(vars(self)) - _CORE - _RUNTIME - _INTERNAL
        if unknown:
            raise JournalError("unclassified rule-state fields: " + ", ".join(sorted(unknown)))
        core = self.to_document()
        # Sets are unordered; a restart may not change the authoritative digest.
        for field in ("pending_memorials", "retry_areas", "bonus_keys"):
            core[field] = {player: sorted(values) for player, values in core[field].items()}
        for rebuild in core["rebuild_pending"].values():
            if rebuild:
                rebuild["restored_keys"] = sorted(rebuild["restored_keys"])
        runtime = {}
        for field in sorted(_RUNTIME):
            value = getattr(self, field)
            if field in _SET_MAPS:
                runtime[field] = {player: sorted(keys) for player, keys in value.items()}
            elif field == "_has_helld":
                runtime[field] = sorted(value)
            elif field == "partner_blobs":
                runtime[field] = _party_cache(value, self.adapter)
            else:
                runtime[field] = copy.deepcopy(value)
        return {"schema": SCHEMA, "core": core, "runtime": runtime, "memorial": copy.deepcopy(self._journal_memorial)}

    @classmethod
    def restore(cls, document, *, data_dir):
        _encode(document)
        if set(document) != {"schema", "core", "runtime", "memorial"} or document["schema"] != SCHEMA:
            raise JournalError("unsupported staged rule document")
        if not isinstance(document["runtime"], dict) or set(document["runtime"]) != _RUNTIME:
            raise JournalError("incomplete staged runtime state")
        core = document["core"]
        if not isinstance(core, dict) or not isinstance(core.get("game_id"), str):
            raise JournalError("staged state must name its game adapter")
        if type(document["runtime"]["is_rr"]) is not bool:
            raise JournalError("invalid persisted rule-adapter mode")
        base = SoulLinkState.from_document(core, data_dir=data_dir, is_rr=document["runtime"]["is_rr"])
        state = cls.from_live(base, document["memorial"])
        for field, value in document["runtime"].items():
            if field in _SET_MAPS:
                if not isinstance(value, dict) or set(value) != {"a", "b"}:
                    raise JournalError("invalid per-player set map")
                if any(not isinstance(keys, list) or any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys) for keys in value.values()):
                    raise JournalError("invalid or duplicate runtime keys")
                setattr(state, field, {player: set(keys) for player, keys in value.items()})
            elif field == "_has_helld":
                if not isinstance(value, list) or any(player not in ("a", "b") for player in value) or len(set(value)) != len(value):
                    raise JournalError("invalid HELLO ownership set")
                state._has_helld = set(value)
            elif field == "partner_blobs":
                state.partner_blobs = _party_cache(value, state.adapter, decode=True)
            else:
                setattr(state, field, copy.deepcopy(value))
        # Restoration may neither drop unknown fields nor coerce malformed values.
        if _encode(state.document())[0] != _encode(document)[0]:
            raise JournalError("staged rule document did not restore exactly")
        return state

    def take_commands(self, player, immediate):
        """Drain both staged queues into the atomic journal commit's arguments."""
        if player not in ("a", "b") or not isinstance(immediate, list):
            raise JournalError("invalid immediate command result")
        result = {p: copy.deepcopy(self.queued_commands[p]) for p in ("a", "b")}
        result[player] = copy.deepcopy(immediate) + result[player]
        self._require_durable_commands(result)
        self.queued_commands = {"a": [], "b": []}
        return result
