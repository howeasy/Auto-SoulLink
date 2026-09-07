"""Drive only ready coordinator transitions; no admission, evidence or frame policy."""

import re
import secrets

from server.protocol_journal import JournalError
from server.trade_coordinator import PHASES


class TradeDriver:
    """Call under the owner's serialized runtime lifecycle.

    read_transaction returns current committed coordinator facts or None.
    advance(action, transaction_id, operation_id) owns authorization and the
    atomic transition. It may return None to defer; errors are never swallowed.
    """

    ACTIONS = {"accepted": "prepare", "both_prepared": "commit", "both_verified": "finalize"}

    def __init__(self, read_transaction, advance, *, new_id=None):
        if not callable(read_transaction) or not callable(advance):
            raise JournalError("owned trade state and control callbacks required")
        self.read_transaction, self.advance = read_transaction, advance
        self.new_id = new_id or (lambda: secrets.token_hex(16))

    def step(self):
        state = self.read_transaction()
        if state is None:
            return None
        if (
            not isinstance(state, dict)
            or state.get("phase") not in PHASES
            or type(state.get("recovery_required")) is not bool
            or not isinstance(state.get("transaction_id"), str)
            or re.fullmatch("[0-9a-f]{32}", state["transaction_id"]) is None
        ):
            raise JournalError("current committed trade status required")
        action = self.ACTIONS.get(state["phase"])
        if action is None or state["recovery_required"]:
            return None
        operation = self.new_id()
        if not isinstance(operation, str) or re.fullmatch("[0-9a-f]{32}", operation) is None:
            raise JournalError("fresh trade control operation identifier required")
        result = self.advance(action, state["transaction_id"], operation)
        return None if result is None else {"action": action, "result": result}
