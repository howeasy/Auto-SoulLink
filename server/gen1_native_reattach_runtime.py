"""Server acceptance of a native client's start-of-script held read (B3 reattach evidence).

The composed native client claims and holds the emulator before its first frame, reads the
overlay word, the CPU and its persisted lease under that hold (``lua/gen1_native_reattach.lua``)
and publishes the read as its first new semantic evidence after HELLO/control, still held. This
module records that read durably and answers with the server's own verdict:

* ``released`` only when the read is physically clean (nothing published/armed/done, lease idle or
  released), the player has no pending native command, and no non-terminal trade exists;
* ``held`` otherwise, with the class that held it. A hold is terminal for this build (B2 owns
  forward recovery); nothing here mutates a trade, a window or a command.

The client releases its startup hold only on a ``released`` verdict whose ``read_digest`` equals
the read it published, and still only under its existing service-lease/pending gates. Replaying
the same operation returns the committed verdict; a different payload under the same operation
id is a journal conflict; a read whose binding, cartridge or owner differs from the current
admission is refused before anything is written.

Integration hook for Root (A-frozen file, not edited here): one line in ``Gen1Runtime._semantic``
dispatch, ``if event == "native_reattach": return record(self, player, message["operation_id"],
self._semantic(message))`` beside the ``observation`` branch, plus registering ``verify_state`` /
``verify_journal`` with the other component audits.
"""

import re

from server import event_reference
from server.protocol import digest
from server.protocol_journal import JournalError, _identifier
from server.trade_coordinator import COMMANDS, NAMESPACE, TERMINAL

COMPONENT = "gen1-native-reattach"
EVENT = "native_reattach"
SCHEMA = "rby-native-reattach-v1"
READ_SCHEMA = "rby-native-reattach-read-v1"
LEASES = frozenset({"idle", "armed", "complete", "releasing", "released"})
READ = frozenset({"schema", "frame", "pc", "sp", "bank", "overlay_hex", "published", "phase", "armed", "done",
                  "token_hex", "lease", "host"})
LEASE = frozenset({"phase", "command_id", "intent_digest", "token_hex", "receipt"})
HOST = frozenset({"owner_id", "process_id", "capability_id", "held"})
ENTRY = frozenset({"origin", "read_digest", "verdict", "class", "physical", "frame", "lease_phase"})
MAX_INT = 2**53 - 1


def key(player):
    return digest({"component": COMPONENT, "player": player})[:32]


def _hex(value, size):
    return isinstance(value, str) and len(value) == size and re.fullmatch(r"[0-9A-Fa-f]+", value) is not None


def typed(request):
    """Exact shape of the client's publication; nothing optional, nothing extra."""
    if not isinstance(request, dict) or request.get("event") != EVENT or set(request) != {"event", "payload"}:
        raise JournalError("native reattach event required")
    payload = request["payload"]
    if (not isinstance(payload, dict) or set(payload) != {"schema", "context_generation", "final_sha1", "physical", "read"}
            or payload["schema"] != SCHEMA or not _hex(payload["context_generation"], 32) or not _hex(payload["final_sha1"], 40)
            or payload["physical"] not in {"clean", "armed", "mid_routine", "lease_open"}):
        raise JournalError("complete native reattach payload required")
    read = payload["read"]
    if not isinstance(read, dict) or set(read) != READ or read["schema"] != READ_SCHEMA:
        raise JournalError("complete native reattach read required")
    for name in ("frame", "pc", "sp", "bank"):
        if type(read[name]) is not int or not 0 <= read[name] <= MAX_INT:
            raise JournalError("native reattach CPU/frame fields required")
    if not _hex(read["overlay_hex"], 32) or not all(isinstance(read[n], bool) for n in ("published", "armed", "done")):
        raise JournalError("native reattach overlay fields required")
    if read["published"] is False and (read["armed"] or read["done"] or read["phase"] is not None or read["token_hex"] is not None):
        raise JournalError("unpublished overlay cannot be armed, done or carry a token")
    if read["published"] and (type(read["phase"]) is not int or not _hex(read["token_hex"], 8)):
        raise JournalError("published overlay requires its phase and token")
    lease = read["lease"]
    if (not isinstance(lease, dict) or set(lease) != LEASE or lease["phase"] not in LEASES
            or not isinstance(lease["receipt"], bool)
            or not (lease["command_id"] is None or _hex(lease["command_id"], 32))
            or not (lease["intent_digest"] is None or _hex(lease["intent_digest"], 64))
            or not (lease["token_hex"] is None or _hex(lease["token_hex"], 8))):
        raise JournalError("native reattach lease summary required")
    host = read["host"]
    if (not isinstance(host, dict) or set(host) != HOST or not _hex(host["owner_id"], 32)
            or type(host["process_id"]) is not int or host["process_id"] < 1 or host["held"] is not True
            or host["capability_id"] != "bizhawk-2.11.1-gambatte-exclusive-hold-v1"):
        raise JournalError("native reattach read must be taken under the owner's verified hold")
    return payload


def classify(document, journal, player, payload):
    """The server's verdict: (verdict, class). Physical facts from the read, obligations from the journal."""
    read = payload["read"]
    if read["published"] and read["done"]:
        return "held", "done_unreleased"
    if read["published"]:
        return "held", "armed"
    if payload["physical"] != "clean":
        return "held", payload["physical"]
    if read["lease"]["phase"] not in {"idle", "released"}:
        return "held", "lease_open"
    for command_id in journal.pending_ids(player):
        if journal.command(player, command_id)["body"].get("cmd") in COMMANDS:
            return "held", "pending_native_command"
    if document["active_trade"] is not None:
        return "held", "active_trade"
    for identifier, entry in document["components"].get("gen1-trade", {}).get("transactions", {}).items():
        record = journal.record(NAMESPACE, identifier)
        if record is None or record.value["phase"] not in TERMINAL or record.value.get("recovery_required"):
            return "held", "trade_open"
    return "released", "clean"


def record(runtime, player, operation, request):
    """Journal one held read and its verdict; idempotent on the operation id."""
    _identifier(operation)
    previous = runtime.journal.event(player, operation, request)
    if previous is not None:
        return previous.result
    payload = typed(request)
    session = runtime.gate.sessions.get(player)
    if session is None:
        raise JournalError("native reattach requires the admitted session")
    binding = session.metadata["control_binding"]
    admitted = session.metadata["gen1_metadata"]
    if (payload["context_generation"] != binding["context_generation"]
            or payload["final_sha1"] != admitted["cartridge"]["final_rom_sha1"]
            or payload["read"]["host"]["owner_id"] != admitted["physical_instance"]):
        raise JournalError("native reattach read differs from the current admission")
    stage = runtime.state()
    document = stage.document()
    verdict, kind = classify(document, runtime.journal, player, payload)
    entry = {"origin": event_reference.make(player, operation, request), "read_digest": digest(payload["read"]),
             "verdict": verdict, "class": kind, "physical": payload["physical"], "frame": payload["read"]["frame"],
             "lease_phase": payload["read"]["lease"]["phase"]}
    players = document["components"].setdefault(COMPONENT, {})
    players[player] = entry
    result = {"ack": "ACK", "native_reattach": {"verdict": verdict, "class": kind, "read_digest": entry["read_digest"]}}
    return runtime.journal.commit(player, operation, request, expected_revision=stage.journal_revision, state=document,
                                  commands={"a": [], "b": []}, result=result,
                                  records=[{"namespace": COMPONENT, "key": key(player), "value": entry}]).result


def verify_state(stage):
    players = stage.document()["components"].get(COMPONENT, {})
    if not isinstance(players, dict) or set(players) - {"a", "b"}:
        raise JournalError("invalid native reattach component")
    for player, entry in players.items():
        if (not isinstance(entry, dict) or set(entry) != ENTRY or not _hex(entry["read_digest"], 64)
                or entry["verdict"] not in {"released", "held"} or (entry["verdict"] == "released") != (entry["class"] == "clean")
                or entry["lease_phase"] not in LEASES or type(entry["frame"]) is not int):
            raise JournalError("complete native reattach entry required")
        if event_reference.validate(entry["origin"])["player"] != player:
            raise JournalError("native reattach reference changed player")


def verify_journal(journal, stage):
    verify_state(stage)
    players = stage.document()["components"].get(COMPONENT, {})
    for player in ("a", "b"):
        entry = players.get(player)
        record_ = journal.record(COMPONENT, key(player))
        if (entry is None) != (record_ is None) or record_ is not None and record_.value != entry:
            raise JournalError("native reattach entry differs from its atomic record")
        if entry is None:
            continue
        event = event_reference.resolve(journal, entry["origin"])
        if (event.request.get("event") != EVENT or digest(event.request["payload"]["read"]) != entry["read_digest"]
                or event.result.get("native_reattach", {}).get("verdict") != entry["verdict"]):
            raise JournalError("native reattach entry differs from its committed event")
