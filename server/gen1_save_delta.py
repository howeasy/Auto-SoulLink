"""RBY save-point deltas shared by generation-owned held save operations.

No command authority, enrollment, or file ownership is established here.
"""

import copy

from server.gen1_full_save import image
from server.hex_delta import between, recover_before
from server.protocol import digest
from server.protocol_journal import JournalError


def wire_payload(payload, *, schema="rby-memorial-delta-v1"):
    before, after = payload["before"], payload["after"]
    changes = {"cart": between(before["cart_hex"], after["cart_hex"])}
    changes.update(
        {
            name: between(before["fields"][name], value)
            for name, value in after["fields"].items()
            if value != before["fields"][name]
        }
    )
    return {
        "schema": schema,
        "before_digest": digest(before),
        "before_status": before["save_status"],
        "after_digest": digest(after),
        "context_generation": payload["context_generation"],
        "final_sha1": payload["final_sha1"],
        "frame": payload["frame"],
        "changes": changes,
    }


def recover_point(current, payload):
    image(current)
    if current["save_status"] not in (payload["before_status"], 2):
        raise JournalError("partial memorial save status is foreign")
    before = copy.deepcopy(current)
    before["save_status"] = payload["before_status"]
    for name, delta in payload["changes"].items():
        if name == "cart":
            before["cart_hex"] = recover_before(current["cart_hex"], delta)
        else:
            before["fields"][name] = recover_before(current["fields"][name], delta)
    if digest(before) != payload["before_digest"]:
        raise JournalError("partial memorial differs outside its exact authorized delta")
    return before
