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
# Events whose commit means gameplay after the save may have happened. A free-run 'observation'
# (P10) counts when it carries signals, inventory or acquisitions; empty heartbeats do not.
GAMEPLAY_EVENTS = {"engine_signals", "inventory_observation"}


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

    @property
    def ok(self):
        return not self.reasons

    def resume_record(self):
        if not self.ok:
            raise JournalError("resume record requires a clean predecessor audit")
        return {"from_run": self.from_run, "required": self.required, "rules": self.rules,
                "contract_hash": self.contract_hash}


def _gameplay_bearing(request):
    event = request.get("event")
    if event in GAMEPLAY_EVENTS:
        return True
    return event == "observation" and any(request.get(k) is not None for k in ("signals", "inventory", "acquisitions"))


def audit_predecessor(run_dir, *, registry_entry):
    from server.gen1_engine_signal_runtime import SAVE_WITNESS
    from server.gen1_run_config import FILENAME, SCHEMA
    from_run = str(registry_entry.get("run_id", ""))
    reasons = []
    if registry_entry.get("status") == "running":
        reasons.append("predecessor run is still marked running in the registry; stop it first")
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
        return ResumeAudit(from_run, (*reasons, f"predecessor journal could not be read: {error}"))
    if registry_entry.get("cartridges") != spec["contract"]["players"]:
        reasons.append("registry cartridges differ from the predecessor journal's contract")
    if document.get("active_trade") is not None:
        reasons.append("predecessor has an open trade")
    if rules["core"].get("run_over"):
        reasons.append("predecessor run is over; nothing to resume")
    witnesses = document["components"].get(SAVE_WITNESS, {})
    signals = document["components"].get("gen1-engine-signals", {})
    required = {}
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
                reasons.append(f"player {player} save witness projection {witness['projection']!r} is not {PROJECTION!r}")
            row = db.execute("SELECT revision FROM events WHERE player=? AND operation_id=?",
                             (player, witness["operation_id"])).fetchone()
            if row is None:
                reasons.append(f"player {player} save witness has no committed event")
                continue
            entry = signals.get(player)
            if entry is not None and entry["operation_id"] == witness["operation_id"] \
                    and witness["index"] != len(entry["payload"]["signals"]) - 1:
                reasons.append(f"player {player} played after the save inside the witness batch")
            later = db.execute("SELECT request FROM events WHERE player=? AND revision>? ORDER BY revision LIMIT 4097",
                               (player, row[0])).fetchall()
            if any(_gameplay_bearing(json.loads(r[0])) for r in later):
                reasons.append(f"player {player} has committed gameplay after the save witness; hold")
            required[player] = {"digest": witness["digest"], "projection": witness["projection"],
                                "witness_index": witness["index"], "operation_id": witness["operation_id"]}
    except sqlite3.Error as error:
        return ResumeAudit(from_run, (*reasons, f"predecessor journal could not be queried: {error}"))
    finally:
        db.close()
    if reasons:
        return ResumeAudit(from_run, tuple(reasons), journal_run_id=stored.run_id, contract_hash=contract_hash)
    return ResumeAudit(from_run, (), journal_run_id=stored.run_id, contract_hash=contract_hash,
                       cartridges=spec["contract"]["players"], required=required, rules=rules)


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


def validate_resume(resume):
    """Shape of the creation-time contract (manager -> create_runtime -> Gen1RuntimeState.initial)."""
    if not isinstance(resume, dict) or set(resume) != {"from_run", "required", "rules", "contract_hash"}:
        raise JournalError("resume contract needs from_run, required, rules and contract_hash")
    if not isinstance(resume["contract_hash"], str) or len(resume["contract_hash"]) != 64:
        raise JournalError("resume contract needs the predecessor contract hash")
    validate_required(resume["from_run"], resume["required"])
    return resume


def seed(document, resume):
    """At creation: the pending contract and, per activated player, an inherited ball activation."""
    validate_resume(resume)
    document["components"][COMPONENT] = {"from_run": resume["from_run"], "required": resume["required"],
        "pending": {"a": True, "b": True}, "enrolled": {}, "imported_at": datetime.now(UTC).isoformat()}
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
    if (not isinstance(component, dict) or set(component) != {"from_run", "required", "pending", "enrolled", "imported_at"}
            or set(component["pending"]) != {"a", "b"} or any(type(v) is not bool for v in component["pending"].values())
            or not isinstance(component["enrolled"], dict) or set(component["enrolled"]) - {"a", "b"}):
        raise JournalError("invalid resume component")
    validate_required(component["from_run"], component["required"])
    initials = document["components"].get("gen1-initial-observations", {})
    for player in ("a", "b"):
        enrolled = component["enrolled"].get(player)
        if component["pending"][player] == (enrolled is not None):
            raise JournalError("resume enrollment and pending flags disagree")
        if enrolled is None:
            continue
        initial = initials.get(player)
        if not isinstance(enrolled, dict) or initial is None or enrolled != enrollment_record(
                component, player, initial, enrolled.get("continue_witness")):
            raise JournalError("resume enrollment record differs from its initial observation")
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


def enrollment_record(component, player, initial, witness):
    return {"player": player, "from_run": component["from_run"], "digest": component["required"][player]["digest"],
            "witness_index": component["required"][player]["witness_index"], "binding": initial["binding"],
            "continue_witness": witness, "record_key": digest({"resume": player, "operation": initial["operation_id"]})[:32]}


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
