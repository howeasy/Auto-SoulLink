"""RBY eligibility policy on the shared, isolated rule-state staging machinery."""
from server.protocol_journal import JournalError
from server.staged_state import StagedSoulLinkState


class StagedGen1State(StagedSoulLinkState):
    @classmethod
    def validate_game_state(cls, state):
        if state.adapter.game_id != "gen1_rby" or state.rom_type.lower().endswith("_ap") or state.is_rr:
            raise JournalError("staged rule storage is only for vanilla RBY")
        super().validate_game_state(state)
