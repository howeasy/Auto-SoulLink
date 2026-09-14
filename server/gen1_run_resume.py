"""Clean same-run resume of a closed Gen 1 run (owner policy P2a, RC_MASTER_GUIDE "Owner decisions").

A resume is a NEW run seeded with the predecessor's typed Soul Link rules state. It is allowed
only when both players' latest acknowledged START-menu saves are the last gameplay the journal
saw, nothing is owed (pending commands, an open trade) and the cartridges are the same pair.
Every read here is read-only: read_journal (mode=ro) plus one read-only sqlite transaction over
the events/commands tables.  Nothing here touches admissions, bindings, engine counters,
cursors or observations; those belong to the run that recorded them.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from server.gen1_engine_signals import SAVE_PROJECTION
from server.gen1_staged_state import StagedGen1State
from server.journal_reader import read_journal
from server.protocol import decode_frame, digest
from server.protocol_journal import JournalError, _identifier

COMPONENT = "gen1-resume"
PROJECTION = SAVE_PROJECTION
CONTINUE_SCHEMA = "rby-continue-receipt-v1"
CONTINUE_ORDER = ("load", "loaded", "chose", "pressed", "enter")
CONTINUE = json.loads((Path(__file__).resolve().parents[1] / "data/games/gen1_rby/continue_sites.json").read_text())
# ponytail: post-witness events are read in one bounded window and refused beyond it; page if a
# predecessor ever legitimately heartbeats more than this after its last save.
EVENT_WINDOW = 4096
log = logging.getLogger("slink.gen1.resume")


def save_digest(cart_hex):
    """The client's witness digest: sha256 over the UPPERCASE HEX TEXT of CartRAM[0x0498:0x8000]
    (lua/gen1_engine_signals.lua: sha256(image.cart_hex:sub(0x498*2+1))), not over the raw bytes."""
    return hashlib.sha256(cart_hex[0x498 * 2:].encode("ascii")).hexdigest()


@dataclass(frozen=True)
class ResumeAudit:
    from_run: str
    reasons: tuple
    journal_run_id: str | None = None
    contract_hash: str | None = None
    cartridges: dict | None = None
    required: dict | None = None
    rules: dict | None = None
    identities: dict | None = None
    details: dict | None = None

    @property
    def ok(self):
        return not self.reasons

    def resume_record(self):
        if not self.ok:
            raise JournalError("resume record requires a clean predecessor audit")
        return {"from_run": self.from_run, "required": self.required, "rules": self.rules,
                "contract_hash": self.contract_hash, "identities": self.identities}


def known_keys(document, rules):
    """Every compatibility key the predecessor ever attributed to each player: logical member history,
    the rules' link halves / pending captures, and the initial inventory it enrolled with. Contexts,
    events and member ids are NOT exported; the resumed run mints its own under fresh bindings."""
    keys = {"a": set(), "b": set()}
    for member in document["identities"]["members"].values():
        for row in member["history"]:
            keys[row["location"]["player"]].add(row["location"]["key"])
    for player, initial in document["components"].get("gen1-initial-observations", {}).items():
        keys[player].update(member["key"] for member in initial["inventory"]["members"])
    for link in rules["core"]["links"]:
        for player in ("a", "b"):
            if link[player] is not None:
                keys[player].add(link[player]["key"])
    for rows in rules["core"]["pending_captures"].values():
        for player, mon in rows.items():
            keys[player].add(mon["key"])
    return {player: {"known_keys": sorted(values)} for player, values in keys.items()}


# ponytail: journaled records that never carry gameplay, enumerated from their writers - extend only
# with a citation. Anything not listed here (trade, native, engine_signals, inventory, an unknown
# event) holds the resume.
#   runtime_opened / runtime_reconciliation_refused / runtime_suspended
#       server/durable_runtime.py _commit_system (:101 open, :212 refused reconciliation, :434 clean stop)
#   hello   durable_runtime._admit dispatches {event, gen1_metadata, run_id}; gen1_runtime_state.handle_event
#           refuses any other field ("RBY durable HELLO cannot carry gameplay observations")
#   sync    gen1_runtime_state.handle_event: {event} only ("sync cannot carry gameplay observations")
#   control durable_runtime.py:219 journals the control challenge when a reconciliation proof binds
LIFECYCLE_EVENTS = frozenset({"runtime_opened", "runtime_reconciliation_refused", "runtime_suspended",
                              "hello", "sync", "control"})
# command_ack is display-only when the acked command is a HUD write (gen1_runtime.py:417-419, the
# no-write receipt lane); every other receipt proves a physical mutation after the save.
DISPLAY_COMMANDS = frozenset({"hud_notice", "hud_state"})


def _no_gameplay(request, db, *, extra_events=frozenset()):
    if not isinstance(request, dict):
        return False
    event = request.get("event")
    if event in LIFECYCLE_EVENTS or event in extra_events:
        return True
    if event == "command_ack":
        row = db.execute("SELECT body FROM commands WHERE command_id=?", (str(request.get("command_id")),)).fetchone()
        return row is not None and json.loads(row[0]).get("cmd") in DISPLAY_COMMANDS
    return _pure_heartbeat(request)


def no_gameplay_since(journal, player, anchor_operation_id, *, extra_events=frozenset(), window=EVENT_WINDOW):
    """True iff PLAYER has committed nothing but no-gameplay events (per `_no_gameplay`, plus
    any of EXTRA_EVENTS a caller classifies as its own non-gameplay bookkeeping — e.g. a
    checkpoint request/upload's own typed events) since ANCHOR_OPERATION_ID's own committed
    revision. False when the anchor itself is not committed, or the window is exceeded.

    Mirrors audit_predecessor's per-player scan (:191-196) but reads the OWNING runtime's own
    live journal connection directly (server.protocol_journal.ProtocolJournal), in place of a
    read-only connection to a closed run's directory — a live runtime never needs that second
    connection, since every write it makes already serializes through this same one."""
    db = journal._db
    row = db.execute("SELECT revision FROM events WHERE player=? AND operation_id=?",
                     (player, anchor_operation_id)).fetchone()
    if row is None:
        return False
    later = db.execute("SELECT request FROM events WHERE player=? AND revision>? ORDER BY revision LIMIT ?",
                       (player, row[0], window + 1)).fetchall()
    if len(later) > window:
        return False
    return all(_no_gameplay(json.loads(r[0]), db, extra_events=extra_events) for r in later)


def checkpoint_anchor_operation(witness):
    """Which committed operation a checkpoint witness's "no gameplay since" check anchors on:
    the START-menu save witness's own operation for the legacy kind, or the native-pretrade
    kind's ready-ACK operation (R5b/N3) — one helper for both, per witness_kind, so a new kind
    only ever adds a branch here rather than duplicating the policy at each call site."""
    kind = witness.get("witness_kind", "save_witness") if isinstance(witness, dict) else None
    if kind == "save_witness":
        return witness["operation_id"]
    if kind == "native_pretrade":
        return witness["ready_operation_id"]
    raise JournalError("unknown checkpoint witness_kind")


def _pure_heartbeat(request):
    """The one event that proves nothing happened: lua/gen1_observation_loop.lua's idle publication
    (no signals, inventory or receipts, wIsInBattle 0, no trainer engagement, no native checkpoint).
    Every other committed event - trade, native, engine signals, inventory, anything unknown - is
    gameplay after the save and holds the resume."""
    # battle/trainer must be PRESENT (the loop always sends both; absence is an older, unproven shape);
    # native_checkpoint is omitted by non-native clients, so absent and null are both fine.
    return (isinstance(request, dict) and request.get("event") == "observation"
            and request.get("signals") is None and request.get("inventory") is None
            and not request.get("acquisitions") and "battle" in request and request["battle"] == 0
            and "trainer" in request and request["trainer"] is None and request.get("native_checkpoint") is None)


def audit_predecessor(run_dir, *, registry_entry):
    from server.gen1_engine_signal_runtime import SAVE_WITNESS
    from server.gen1_run_config import FILENAME, SCHEMA
    from_run = str(registry_entry.get("run_id", ""))
    reasons = []
    if registry_entry.get("status") in ("starting", "running"):
        reasons.append("predecessor run is starting or running in the registry; stop it first")
    directory = Path(run_dir).resolve()
    path = directory / FILENAME
    if not path.is_file() or not (directory / "runtime.sqlite3").is_file():
        return ResumeAudit(from_run, (*reasons, "predecessor run directory has no prepared Gen 1 runtime"))
    try:
        spec = decode_frame(path.read_bytes())
        if spec.get("schema") != SCHEMA or spec.get("initial_observations") is not True:
            raise JournalError("predecessor is not an initial-observation Gen 1 run")
        contract_hash = digest(spec["contract"])
        stored = read_journal(directory / spec["journal"], run_id=spec["run_id"], contract_hash=contract_hash)
        document = stored.snapshot.state
        rules = StagedGen1State.restore(document["rules"], data_dir=str(directory)).document()
    except (JournalError, KeyError, TypeError, ValueError, OSError) as error:
        log.warning("resume audit of %s could not read the predecessor journal: %s", from_run, error)
        return ResumeAudit(from_run, (*reasons, "predecessor journal could not be read"))
    if registry_entry.get("cartridges") != spec["contract"]["players"]:
        reasons.append("registry cartridges differ from the predecessor journal's contract")
    if document.get("active_trade") is not None:
        reasons.append("predecessor has an open trade")
    if rules["core"].get("run_over"):
        reasons.append("predecessor run is over; nothing to resume")
    # ponytail: mid-pending states HOLD (owner policy). Resuming them would need the settled acquisition
    # rows (gen1_acquisition_runtime._link_members) and death/memorial records imported too; add that
    # only if a mid-pending resume is ever actually needed.
    if rules["core"]["pending_captures"]:
        reasons.append("resume requires no pending captures")
    if any(rules["core"]["pending_memorials"].values()):
        reasons.append("resume requires completed memorials")
    witnesses = document["components"].get(SAVE_WITNESS, {})
    signals = document["components"].get("gen1-engine-signals", {})
    required = {}
    details = {}
    db = sqlite3.connect((directory / spec["journal"]).as_uri() + "?mode=ro", uri=True, isolation_level=None, timeout=2.5)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        for player in ("a", "b"):
            if db.execute("SELECT 1 FROM commands WHERE player=? AND outcome IS NULL LIMIT 1", (player,)).fetchone():
                reasons.append(f"player {player} has pending commands")
            witness = witnesses.get(player)
            if witness is None:
                reasons.append(f"player {player} has no acknowledged save witness")
                continue
            if witness["projection"] != PROJECTION:
                reason = "save witness projection is not the persistent CartRAM projection"
                if reason not in reasons:
                    reasons.append(reason)
                details.setdefault("projection", {"required": PROJECTION})[player] = witness["projection"]
            row = db.execute("SELECT revision FROM events WHERE player=? AND operation_id=?",
                             (player, witness["operation_id"])).fetchone()
            if row is None:
                reasons.append(f"player {player} save witness has no committed event")
                continue
            entry = signals.get(player)
            if entry is not None and entry["operation_id"] == witness["operation_id"] \
                    and witness["index"] != len(entry["payload"]["signals"]) - 1:
                reasons.append(f"player {player} played after the save inside the witness batch")
            later = db.execute("SELECT request FROM events WHERE player=? AND revision>? ORDER BY revision LIMIT ?",
                               (player, row[0], EVENT_WINDOW + 1)).fetchall()
            if len(later) > EVENT_WINDOW:
                reasons.append("resume audit exceeded the bounded event window")
            elif not all(_no_gameplay(json.loads(r[0]), db) for r in later):
                reasons.append(f"player {player} has committed gameplay after the save witness; hold")
            required[player] = {"digest": witness["digest"], "projection": witness["projection"],
                                "witness_index": witness["index"], "operation_id": witness["operation_id"]}
    except sqlite3.Error as error:
        log.warning("resume audit of %s could not query the predecessor journal: %s", from_run, error)
        return ResumeAudit(from_run, (*reasons, "predecessor journal could not be queried"))
    finally:
        db.close()
    if reasons:
        return ResumeAudit(from_run, tuple(reasons), journal_run_id=stored.run_id, contract_hash=contract_hash, details=details)
    return ResumeAudit(from_run, (), journal_run_id=stored.run_id, contract_hash=contract_hash,
                       cartridges=spec["contract"]["players"], required=required, rules=rules,
                       identities=known_keys(document, rules))


def validate_required(from_run, required):
    if not isinstance(from_run, str) or not from_run:
        raise JournalError("resume contract needs its predecessor registry id")
    if not isinstance(required, dict) or set(required) != {"a", "b"}:
        raise JournalError("resume contract needs both players' witnesses")
    for row in required.values():
        if (not isinstance(row, dict) or set(row) != {"digest", "projection", "witness_index", "operation_id"}
                or not isinstance(row["digest"], str) or len(row["digest"]) != 64 or row["projection"] != PROJECTION
                or type(row["witness_index"]) is not int):
            raise JournalError("resume contract witness is incomplete")
        _identifier(row["operation_id"])


def validate_identities(identities):
    if (not isinstance(identities, dict) or set(identities) != {"a", "b"}
            or any(not isinstance(row, dict) or set(row) != {"known_keys"} or not isinstance(row["known_keys"], list)
                   or any(not isinstance(key, str) for key in row["known_keys"]) for row in identities.values())):
        raise JournalError("resume contract identities must be per-player known keys only")


def validate_resume(resume):
    """Shape of the creation-time contract (manager -> create_runtime -> Gen1RuntimeState.initial)."""
    if not isinstance(resume, dict) or set(resume) != {"from_run", "required", "rules", "contract_hash", "identities"}:
        raise JournalError("resume contract needs from_run, required, rules, contract_hash and identities")
    validate_identities(resume["identities"])
    if not isinstance(resume["contract_hash"], str) or len(resume["contract_hash"]) != 64:
        raise JournalError("resume contract needs the predecessor contract hash")
    validate_required(resume["from_run"], resume["required"])
    return resume


def seed(document, resume):
    """At creation: the pending contract and, per activated player, an inherited ball activation."""
    validate_resume(resume)
    document["components"][COMPONENT] = {"from_run": resume["from_run"], "required": resume["required"],
        "identities": resume["identities"], "pending": {"a": True, "b": True}, "enrolled": {},
        "imported_at": datetime.now(UTC).isoformat()}
    activated = document["rules"]["core"]["pokeballs_obtained"]
    if any(activated.values()):
        faints = document["components"].setdefault("gen1-faint-settlement", {"activations": {}, "deaths": {}})
        for player in resume["required"]:
            if activated[player]:
                faints["activations"][player] = {"inherited": inherited(document["components"][COMPONENT], player),
                                                 "index": None, "engine_record": None}


def inherited_activation_frame(document, player):
    """First frame an inherited activation is effective: the player's enrollment frame (None before)."""
    initial = document["components"].get("gen1-initial-observations", {}).get(player)
    return None if initial is None else initial["observation"]["frame"]


def verify_state(stage):
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is None:
        return
    if (not isinstance(component, dict)
            or set(component) != {"from_run", "required", "identities", "pending", "enrolled", "imported_at"}
            or set(component["pending"]) != {"a", "b"} or any(type(v) is not bool for v in component["pending"].values())
            or not isinstance(component["enrolled"], dict) or set(component["enrolled"]) - {"a", "b"}):
        raise JournalError("invalid resume component")
    validate_required(component["from_run"], component["required"])
    validate_identities(component["identities"])
    initials = document["components"].get("gen1-initial-observations", {})
    members = document["identities"]["members"]
    for player in ("a", "b"):
        enrolled = component["enrolled"].get(player)
        if component["pending"][player] == (enrolled is not None):
            raise JournalError("resume enrollment and pending flags disagree")
        if enrolled is None:
            continue
        initial = initials.get(player)
        if not isinstance(enrolled, dict) or initial is None or enrolled != enrollment_record(
                component, player, initial, enrolled.get("continue_witness"), enrolled.get("members"), enrolled.get("links")):
            raise JournalError("resume enrollment record differs from its initial observation")
        # Provenance, not the live key: ordinary evolution/trade migrates a member's current key.
        if not isinstance(enrolled["members"], dict) or any(
                member_id not in members
                or members[member_id]["history"][0]["location"]["player"] != player
                or members[member_id]["history"][0]["location"]["key"] != key
                for key, member_id in enrolled["members"].items()):
            raise JournalError("inherited members lost their logical identities")
        if not isinstance(enrolled["links"], list) or any(link not in document["identities"]["links"] for link in enrolled["links"]):
            raise JournalError("inherited links lost their logical identities")
        if save_digest(initial["observation"]["source"]["cart_hex"]) != component["required"][player]["digest"]:
            raise JournalError("resumed enrollment lost its witnessed save projection")
        metadata = initial["metadata"]
        cartridge = metadata["gen1_metadata"]["cartridge"]
        validate_continue_witness(enrolled["continue_witness"], variant=cartridge["variant"],
            context_generation=initial["binding"]["context_generation"], physical_instance=metadata["gen1_metadata"]["physical_instance"],
            final_sha1=cartridge["final_rom_sha1"], frame=initial["observation"]["frame"])
    faints = document["components"].get("gen1-faint-settlement", {}).get("activations", {})
    for player, proof in faints.items():
        if "inherited" in proof and proof["inherited"] != inherited(component, player):
            raise JournalError("inherited activation differs from the resume contract")


def inherited(component, player):
    row = component["required"][player]
    return {"from_run": component["from_run"], "digest": row["digest"], "witness_index": row["witness_index"],
            "operation_id": row["operation_id"]}


def enrollment_record(component, player, initial, witness, members, links):
    return {"player": player, "from_run": component["from_run"], "digest": component["required"][player]["digest"],
            "witness_index": component["required"][player]["witness_index"], "binding": initial["binding"],
            "continue_witness": witness, "members": members, "links": links,
            "record_key": digest({"resume": player, "operation": initial["operation_id"]})[:32]}


def inherit_identities(stage, component, player, initial, inventory, operation):
    """Bind the predecessor's living members for this player to the fresh physical context.

    Living = ALIVE link halves, pending captures and pending memorials in the imported rules. Every
    one must be in the presented party/box; every presented key must be one the predecessor knew.
    Members are minted anew via the registry's ordinary acquire() under the new context (no
    predecessor ids, contexts or events are copied); identity links for ALIVE pairs form once both
    players are bound. Returns ({key: member_id}, [link_id]).
    """
    from server.gen1_starter_settlement import context
    from server.identity_registry import IdentityWitness
    from server.state import LinkStatus
    rules = stage.rules
    presented = {member["key"]: member["evidence_digest"] for member in inventory["members"]}
    living = set(rules.pending_memorials[player])
    living.update(rows[player].key for rows in rules.pending_captures.values() if player in rows)
    living.update(getattr(link, player).key for link in rules.links
                  if link.status == LinkStatus.ALIVE and getattr(link, player) is not None)
    for key in sorted(living - set(presented)):
        raise JournalError(f"inherited living member {key} is absent from the presented party/box")
    for key in sorted(set(presented) - set(component["identities"][player]["known_keys"])):
        raise JournalError(f"presented save carries key {key} the predecessor never knew")
    own = context(initial, player)
    members = {}
    for key in sorted(living):
        event = digest({"resume_member": key, "player": player, "operation": operation})[:32]
        members[key] = stage.identities.acquire(event, event, IdentityWitness(own, key, presented[key], 1))["member_id"]
    links = []
    partner = "b" if player == "a" else "a"
    peer_initial = stage.document()["components"].get("gen1-initial-observations", {}).get(partner)
    if peer_initial is not None:
        contexts = {player: own, partner: context(peer_initial, partner)}
        for link in rules.links:
            if link.status != LinkStatus.ALIVE or link.a is None or link.b is None:
                continue
            ids = [stage.identities.resolve(contexts[p], getattr(link, p).key) for p in ("a", "b")]
            if None in ids:
                raise JournalError(f"inherited link {link.area_id} lacks a bound logical member")
            event = digest({"resume_link": link.area_id, "operation": operation})[:32]
            links.append(stage.identities.create_link(player, event, ids)["link_id"])
    return members, links


def validate_continue_witness(witness, *, variant, context_generation, physical_instance, final_sha1, frame):
    """Structural check of lua/gen1_continue_observer.lua's published receipt: five source-pinned sites
    in order, save file status 2, same-SP load/return and choose/confirm/enter, all before the
    observation frame. A New Game bootstrap receipt has another schema and is refused here."""
    why = "resume enrollment requires a witnessed CONTINUE of the matched save"
    profile = CONTINUE["titles"].get(variant)
    if (not isinstance(witness, dict) or profile is None
            or set(witness) != {"schema", "source_sha256", "variant", "context_generation", "physical_instance", "final_sha1", *CONTINUE_ORDER}
            or witness["schema"] != CONTINUE_SCHEMA or witness["source_sha256"] != CONTINUE["sha256"]
            or witness["variant"] != variant or witness["context_generation"] != context_generation
            or witness["physical_instance"] != physical_instance or witness["final_sha1"] != final_sha1):
        raise JournalError(why)
    previous = -1
    for kind in CONTINUE_ORDER:
        stage = witness[kind]
        site = profile["sites"][kind]
        keys = {"frame", "pc", "bank", "sp", "status"} if kind == "loaded" else {"frame", "pc", "bank", "sp"}
        if (not isinstance(stage, dict) or set(stage) != keys or any(type(stage[k]) is not int for k in keys)
                or stage["pc"] != site["address"] or stage["bank"] != site["bank"] or stage["frame"] < previous
                or not 0xC000 <= stage["sp"] <= 0xFFFE):
            raise JournalError(why)
        previous = stage["frame"]
    if (witness["loaded"]["status"] != 2 or witness["load"]["sp"] != witness["loaded"]["sp"]
            or len({witness[k]["sp"] for k in ("chose", "pressed", "enter")}) != 1
            or witness["enter"]["frame"] > frame):
        raise JournalError(why)
    return witness
