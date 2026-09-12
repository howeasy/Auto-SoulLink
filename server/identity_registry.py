"""Journal-composed logical identities, independent of cartridge keys and rule policy.

Bindings construct typed witnesses after validating physical evidence. This module
does not read a game, grant execution, award captures/bonuses, settle deaths, or
interpret species/form policy. Mutate a detached stage and commit it with rules,
transactions and both outboxes. Raw keys are scoped observations, never global IDs.
"""
from __future__ import annotations

import copy
import secrets
from dataclasses import asdict, dataclass

from server.paired_recovery import _hex, _player
from server.protocol import digest
from server.protocol_journal import JournalError, _encode
from server.save_identity import SaveIdentity

SCHEMA = "slink-logical-identities-v1"


def _text(value, limit, name):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or not value.isprintable():
        raise JournalError(f"invalid identity {name}")
    return value


def _reference(value):
    if not isinstance(value, str) or len(value) != 34 or value[:2] not in ("a:", "b:"):
        raise JournalError("invalid player-scoped identity reference")
    _hex(value[2:], 32, "identity reference")
    return value


@dataclass(frozen=True)
class IdentityContext:
    player: str
    game_id: str
    save_identity: SaveIdentity
    binding_digest: str
    context_generation: str
    physical_instance: str

    def __post_init__(self):
        _player(self.player)
        _text(self.game_id, 64, "game")
        if not isinstance(self.save_identity, SaveIdentity):
            raise JournalError("identity context needs a validated save identity")
        _hex(self.binding_digest, 64, "binding digest")
        _hex(self.context_generation, 32, "context generation")
        _hex(self.physical_instance, 32, "physical instance")


@dataclass(frozen=True)
class IdentityWitness:
    context: IdentityContext
    key: str
    evidence_digest: str
    observed_count: int

    def __post_init__(self):
        if not isinstance(self.context, IdentityContext):
            raise JournalError("physical identity needs a validated context")
        _text(self.key, 256, "compatibility key")
        _hex(self.evidence_digest, 64, "physical evidence")
        if type(self.observed_count) is not int or self.observed_count != 1:
            raise JournalError("ambiguous physical identity requires reconciliation")


@dataclass(frozen=True)
class MigrationWitness:
    member_id: str
    source_context: IdentityContext
    before_key: str
    before_evidence_digest: str
    after: IdentityWitness

    def __post_init__(self):
        _hex(self.member_id, 32, "logical member")
        if not isinstance(self.source_context, IdentityContext) or not isinstance(self.after, IdentityWitness):
            raise JournalError("migration needs validated participant evidence")
        _text(self.before_key, 256, "before key")
        _hex(self.before_evidence_digest, 64, "before evidence")


def _save_ref(context):
    return digest({name: context[name] for name in ("game_id", "save_identity")})


def _location(witness):
    context = asdict(witness.context)
    return {"player": context["player"], "save_ref": _save_ref(context), "key": witness.key}


def _index(document):
    result = {}
    for member_id, member in document["members"].items():
        current = member["current"]
        key = (current["player"], current["save_ref"], current["key"])
        if key in result:
            raise JournalError("duplicate current physical identities require reconciliation")
        result[key] = member_id
    return result


class IdentityRegistry:
    def __init__(self, run_id, *, new_id=None):
        self._new_id = new_id or (lambda: secrets.token_hex(16))
        self._replaying = False
        self._document = {"schema": SCHEMA, "run_id": _hex(run_id, 32, "run"),
                          "contexts": {"a": None, "b": None}, "members": {},
                          "context_history": {"a": [], "b": []},
                          "acquisitions": {}, "links": {}, "events": {}, "ordinal": 0}

    def document(self):
        return copy.deepcopy(self._document)

    @staticmethod
    def _context(document, context):
        if not isinstance(context, IdentityContext) or document["contexts"][context.player] != asdict(context):
            raise JournalError("identity witness has a stale or unadmitted context")

    def bind_context(self, context):
        if not isinstance(context, IdentityContext):
            raise JournalError("validated identity context required")
        proposed = asdict(context)
        prior = self._document["contexts"][context.player]
        if prior == proposed:
            return False
        if prior is not None and _save_ref(prior) != _save_ref(proposed):
            raise JournalError("another save cannot replace this run's identity binding")
        if any(row["context"] == proposed for row in self._document["context_history"][context.player]):
            raise JournalError("retired identity context cannot become current again")
        peer = self._document["contexts"]["b" if context.player == "a" else "a"]
        if peer and peer["physical_instance"] == proposed["physical_instance"]:
            raise JournalError("the two player bindings need independent physical instances")
        staged = self._document if self._replaying else self.document()
        staged["contexts"][context.player] = proposed
        staged["ordinal"] += 1
        staged["context_history"][context.player].append({"ordinal": staged["ordinal"], "context": copy.deepcopy(proposed)})
        self._publish(staged)
        return True

    def _mint(self, document):
        value = _hex(self._new_id(), 32, "new logical identifier")
        if value in document["members"] or value in document["links"]:
            raise JournalError("logical identifier source repeated a prior identity")
        return value

    def _publish(self, document):
        # The replay engine uses the normal action implementations but must not
        # recursively invoke full history replay. These live transition invariants
        # still apply at EVERY intermediate step, including during restore.
        _index(document)
        linked = set()
        for link in document["links"].values():
            self._member_list(link["members"])
            if any(m not in document["members"] or m in linked for m in link["members"]):
                raise JournalError("unknown member or duplicate link membership")
            linked.update(link["members"])
        if not self._replaying:
            self.validate(document, replay_history=False)
        self._document = document

    def _event(self, issuer, event_id, kind, request, apply):
        _player(issuer)
        ref = issuer + ":" + _hex(event_id, 32, "semantic event")
        signature = digest({"kind": kind, "request": request})
        old = self._document["events"].get(ref)
        if old is not None:
            if old["digest"] != signature:
                raise JournalError("semantic identity event was reused with different content or meaning")
            replay = copy.deepcopy(old["result"])
            replay["replayed"] = True
            if "created" in replay:
                replay["created"] = False
            return replay
        staged = self._document if self._replaying else self.document()
        result = apply(staged)
        staged["ordinal"] += 1
        staged["events"][ref] = {"kind": kind, "digest": signature, "request": copy.deepcopy(request),
                                  "ordinal": staged["ordinal"], "result": copy.deepcopy(result)}
        self._publish(staged)
        return {**copy.deepcopy(result), "replayed": False}

    def acquire(self, event_id, acquisition_id, witness, *, existing_member_id=None):
        """Create once per acquisition transaction, or explicitly alias a proved duplicate.

        Different detector events may share one acquisition_id. A new transaction
        using an already-owned raw key is refused unless the binding explicitly
        confirms existing_member_id; neither retry/alias creates another member.
        """
        if not isinstance(witness, IdentityWitness):
            raise JournalError("acquisition requires a typed physical witness")
        _hex(acquisition_id, 32, "acquisition transaction")
        if existing_member_id is not None:
            _hex(existing_member_id, 32, "existing member")
        player = witness.context.player
        reference = player + ":" + acquisition_id
        request = {"acquisition_id": acquisition_id, "witness": asdict(witness),
                   "existing_member_id": existing_member_id}
        def apply(staged):
            self._context(staged, witness.context)
            location = _location(witness)
            current_id = _index(staged).get((player, location["save_ref"], witness.key))
            previous = staged["acquisitions"].get(reference)
            if previous is not None:
                member_id = previous["member_id"]
                if current_id != member_id or existing_member_id not in (None, member_id):
                    raise JournalError("acquisition replay has conflicting physical identity")
                return {"member_id": member_id, "created": False, "acquisition_id": acquisition_id}
            if current_id is not None:
                if existing_member_id != current_id:
                    raise JournalError("physical key is already bound; confirm duplicate acquisition or reconcile")
                member_id, created = current_id, False
            else:
                if existing_member_id is not None:
                    raise JournalError("duplicate acquisition witness does not locate its existing member")
                member_id, created = self._mint(staged), True
                staged["members"][member_id] = {"origin_acquisition": reference, "current": copy.deepcopy(location),
                    "history": [{"event": player + ":" + event_id, "location": copy.deepcopy(location),
                                 "evidence_digest": witness.evidence_digest}]}
            staged["acquisitions"][reference] = {"member_id": member_id, "origin": copy.deepcopy(location)}
            return {"member_id": member_id, "created": created, "acquisition_id": acquisition_id}
        return self._event(player, event_id, "acquisition", request, apply)

    def migrate_many(self, issuer, event_id, witnesses):
        """Atomically rekey/transfer members; create no capture, member or link.

        source_context identifies the currently admitted participant. The binding
        validates before_evidence_digest against persisted preparation/history and
        the after witness against fresh readback. This class cannot prove either.
        """
        if not isinstance(witnesses, (tuple, list)) or not 1 <= len(witnesses) <= 64:
            raise JournalError("a bounded explicit migration batch is required")
        if any(not isinstance(w, MigrationWitness) for w in witnesses):
            raise JournalError("migration batch needs typed witnesses")
        request = {"witnesses": [asdict(w) for w in witnesses]}
        def apply(staged):
            if len({w.member_id for w in witnesses}) != len(witnesses):
                raise JournalError("duplicate member in migration batch")
            for w in witnesses:
                self._context(staged, w.source_context)
                self._context(staged, w.after.context)
                member = staged["members"].get(w.member_id)
                before = {"player": w.source_context.player, "save_ref": _save_ref(asdict(w.source_context)),
                          "key": w.before_key}
                if member is None or member["current"] != before:
                    raise JournalError("migration before identity differs from the logical member")
                after = _location(w.after)
                if after == before:
                    raise JournalError("migration must witness a key or ownership change")
                member["current"] = copy.deepcopy(after)
                member["history"].append({"event": issuer + ":" + event_id, "location": copy.deepcopy(after),
                    "evidence_digest": w.after.evidence_digest, "before_evidence_digest": w.before_evidence_digest})
            _index(staged)  # Validate final ownership together; swaps need no intermediate vacancy.
            return {"member_ids": [w.member_id for w in witnesses], "created_members": 0}
        return self._event(issuer, event_id, "identity_migration", request, apply)

    def create_link(self, issuer, event_id, members):
        """Identity bookkeeping only; the rule coordinator decides valid pairing."""
        self._member_list(members)
        def apply(staged):
            if any(member not in staged["members"] for member in members):
                raise JournalError("link refers to an unknown member")
            link_id = self._mint(staged)
            staged["links"][link_id] = {"members": list(members), "history": [], "created_by": issuer + ":" + event_id}
            return {"link_id": link_id}
        return self._event(issuer, event_id, "link_creation", {"members": list(members)}, apply)

    def replace_link_members(self, issuer, event_id, assignments):
        """Stage explicitly coordinated pairing changes without replacing link IDs."""
        if not isinstance(assignments, dict) or not assignments or len(assignments) > 64:
            raise JournalError("bounded link assignments required")
        for link_id, members in assignments.items():
            _hex(link_id, 32, "link")
            self._member_list(members)
        def apply(staged):
            for link_id, members in assignments.items():
                if link_id not in staged["links"] or any(m not in staged["members"] for m in members):
                    raise JournalError("link assignment refers to an unknown identity")
                link = staged["links"][link_id]
                link["history"].append({"event": issuer + ":" + event_id, "members": link["members"]})
                link["members"] = list(members)
            return {"link_ids": sorted(assignments)}
        return self._event(issuer, event_id, "link_assignment", assignments, apply)

    def resolve(self, context, key):
        self._context(self._document, context)
        _text(key, 256, "compatibility key")
        return _index(self._document).get((context.player, _save_ref(asdict(context)), key))

    def member(self, member_id):
        _hex(member_id, 32, "logical member")
        if member_id not in self._document["members"]:
            raise JournalError("unknown logical member")
        return copy.deepcopy(self._document["members"][member_id])

    def historical_members(self, player, key):
        _player(player)
        _text(key, 256, "compatibility key")
        return sorted(member_id for member_id, member in self._document["members"].items()
                      if any(row["location"]["player"] == player and row["location"]["key"] == key
                             for row in member["history"]))

    @staticmethod
    def _member_list(members):
        if not isinstance(members, (tuple, list)) or len(members) > 2:
            raise JournalError("explicit zero-to-two unique link members required")
        for member in members:
            _hex(member, 32, "logical member")
        if len(set(members)) != len(members):
            raise JournalError("duplicate link member")

    @staticmethod
    def _read_context(raw):
        try:
            checked = IdentityContext(**(raw | {"save_identity": SaveIdentity(**raw["save_identity"])}))
        except (TypeError, ValueError, KeyError) as error:
            raise JournalError("invalid persisted identity context") from error
        if asdict(checked) != raw:
            raise JournalError("identity context did not restore exactly")
        return checked

    @classmethod
    def _read_witness(cls, raw):
        try:
            checked = IdentityWitness(**(raw | {"context": cls._read_context(raw["context"])}))
        except (TypeError, ValueError, KeyError) as error:
            raise JournalError("invalid persisted identity witness") from error
        if asdict(checked) != raw:
            raise JournalError("identity witness did not restore exactly")
        return checked

    @classmethod
    def _read_migration(cls, raw):
        try:
            checked = MigrationWitness(**(raw | {"source_context": cls._read_context(raw["source_context"]),
                                                "after": cls._read_witness(raw["after"])}))
        except (TypeError, ValueError, KeyError) as error:
            raise JournalError("invalid persisted migration witness") from error
        if asdict(checked) != raw:
            raise JournalError("migration witness did not restore exactly")
        return checked

    @classmethod
    def _validate_events(cls, document):
        ordinals = []
        for ref, event in document["events"].items():
            _reference(ref)
            if not isinstance(event, dict) or set(event) != {"kind", "digest", "request", "result", "ordinal"}:
                raise JournalError("invalid identity event record")
            if not isinstance(event["kind"], str) or event["kind"] not in {"acquisition", "identity_migration", "link_creation", "link_assignment"}:
                raise JournalError("unknown identity event kind")
            if type(event["ordinal"]) is not int or event["ordinal"] < 1:
                raise JournalError("invalid identity action ordinal")
            ordinals.append(event["ordinal"])
            request, result = event["request"], event["result"]
            if not isinstance(request, dict) or not isinstance(result, dict):
                raise JournalError("identity event request/result must be objects")
            _hex(event["digest"], 64, "event digest")
            if event["digest"] != digest({"kind": event["kind"], "request": request}):
                raise JournalError("identity event request digest differs")
            if event["kind"] == "acquisition":
                if set(request) != {"acquisition_id", "witness", "existing_member_id"}:
                    raise JournalError("invalid acquisition request")
                _hex(request["acquisition_id"], 32, "acquisition transaction")
                if request["existing_member_id"] is not None:
                    _hex(request["existing_member_id"], 32, "alias member")
                witness = cls._read_witness(request["witness"])
                if witness.context.player != ref[0]:
                    raise JournalError("acquisition witness belongs to another player")
                if not any(row["context"] == asdict(witness.context) for row in document["context_history"][witness.context.player]):
                    raise JournalError("acquisition uses an unknown historical context")
                if set(result) != {"member_id", "created", "acquisition_id"} or type(result["created"]) is not bool:
                    raise JournalError("invalid acquisition result")
                _hex(result["member_id"], 32, "acquisition member")
                if result["acquisition_id"] != request["acquisition_id"]:
                    raise JournalError("acquisition result differs from request")
            elif event["kind"] == "identity_migration":
                if set(request) != {"witnesses"} or not isinstance(request["witnesses"], list) or not 1 <= len(request["witnesses"]) <= 64:
                    raise JournalError("invalid migration request")
                witnesses = [cls._read_migration(raw) for raw in request["witnesses"]]
                if len({w.member_id for w in witnesses}) != len(witnesses):
                    raise JournalError("duplicate migration request member")
                if (set(result) != {"member_ids", "created_members"} or type(result["created_members"]) is not int
                        or result["created_members"] != 0 or result["member_ids"] != [w.member_id for w in witnesses]):
                    raise JournalError("migration result differs from its witnessed participants")
                for witness in witnesses:
                    for context in (witness.source_context, witness.after.context):
                        if not any(row["context"] == asdict(context) for row in document["context_history"][context.player]):
                            raise JournalError("migration uses an unknown historical context")
            elif event["kind"] == "link_creation":
                if set(request) != {"members"}:
                    raise JournalError("invalid link creation request")
                cls._member_list(request["members"])
                if set(result) != {"link_id"}:
                    raise JournalError("invalid link creation result")
                _hex(result["link_id"], 32, "created link")
            else:
                if not 1 <= len(request) <= 64:
                    raise JournalError("invalid link assignment request")
                for link_id, members in request.items():
                    _hex(link_id, 32, "assignment link")
                    cls._member_list(members)
                if set(result) != {"link_ids"} or result["link_ids"] != sorted(request):
                    raise JournalError("link assignment result differs from its request")
        ordinals.extend(row["ordinal"] for history in document["context_history"].values() for row in history)
        if (type(document["ordinal"]) is not int or document["ordinal"] != len(ordinals)
                or sorted(ordinals) != list(range(1, len(ordinals) + 1))):
            raise JournalError("missing or duplicate identity transition ordinal")

    @classmethod
    def _replay_history(cls, document):
        identifiers = []
        def supplied_id():
            if not identifiers:
                raise JournalError("restored transition would create an unrecorded identity")
            return identifiers.pop(0)
        replay = cls(document["run_id"], new_id=supplied_id)
        replay._replaying = True
        timeline = [(row["ordinal"], "context", row["context"])
                    for history in document["context_history"].values() for row in history]
        timeline.extend((event["ordinal"], ref, event) for ref, event in document["events"].items())
        for ordinal, ref, item in sorted(timeline):
            if ref == "context":
                replay.bind_context(cls._read_context(item))
            else:
                request, result = item["request"], item["result"]
                if item["kind"] == "acquisition":
                    if result["created"]:
                        identifiers.append(result["member_id"])
                    replay.acquire(ref[2:], request["acquisition_id"], cls._read_witness(request["witness"]),
                                   existing_member_id=request["existing_member_id"])
                elif item["kind"] == "identity_migration":
                    replay.migrate_many(ref[0], ref[2:], [cls._read_migration(w) for w in request["witnesses"]])
                elif item["kind"] == "link_creation":
                    identifiers.append(result["link_id"])
                    replay.create_link(ref[0], ref[2:], request["members"])
                else:
                    replay.replace_link_members(ref[0], ref[2:], request)
                if replay._document["events"].get(ref) != item:
                    raise JournalError("restored action result differs from logical replay")
            if identifiers or replay._document["ordinal"] != ordinal:
                raise JournalError("restored transition did not consume its recorded identity/ordinal")
        if replay._document != document:
            raise JournalError("identity registry did not replay exactly")

    @classmethod
    def validate(cls, document, *, replay_history=True):
        _encode(document)
        if set(document) != {"schema", "run_id", "contexts", "context_history", "members", "acquisitions", "links", "events", "ordinal"} or document["schema"] != SCHEMA:
            raise JournalError("unsupported or incomplete identity registry")
        _hex(document["run_id"], 32, "run")
        if not isinstance(document["contexts"], dict) or set(document["contexts"]) != {"a", "b"}:
            raise JournalError("incomplete player identity contexts")
        for name in ("members", "acquisitions", "links", "events"):
            if not isinstance(document[name], dict):
                raise JournalError("invalid identity collection: " + name)
        if not isinstance(document["context_history"], dict) or set(document["context_history"]) != {"a", "b"}:
            raise JournalError("incomplete context history")
        for player, context in document["contexts"].items():
            history = document["context_history"][player]
            if not isinstance(history, list):
                raise JournalError("invalid context history")
            for row in history:
                if (not isinstance(row, dict) or set(row) != {"ordinal", "context"}
                        or type(row["ordinal"]) is not int or row["ordinal"] < 1):
                    raise JournalError("invalid context binding history")
            if context != (history[-1]["context"] if history else None) or len({digest(row["context"]) for row in history}) != len(history):
                raise JournalError("current/retired contexts are inconsistent")
            for row in history:
                historic = cls._read_context(row["context"])
                if historic.player != player or _save_ref(row["context"]) != _save_ref(context):
                    raise JournalError("context history replaced a player/save")
            if context is not None:
                checked = cls._read_context(context)
                if checked.player != player or asdict(checked) != context:
                    raise JournalError("persisted context differs from its player")
        a, b = document["contexts"].values()
        if a and b and a["physical_instance"] == b["physical_instance"]:
            raise JournalError("duplicate physical instance")
        cls._validate_events(document)
        first_acquisition_events = {}
        for event_ref, event in document["events"].items():
            if event["kind"] == "acquisition":
                key = event_ref[:2] + event["request"]["acquisition_id"]
                prior = first_acquisition_events.get(key)
                if prior is None or event["ordinal"] < prior["ordinal"]:
                    first_acquisition_events[key] = event
        def location(value):
            if not isinstance(value, dict) or set(value) != {"player", "save_ref", "key"}:
                raise JournalError("invalid physical location identity")
            _player(value["player"])
            _hex(value["save_ref"], 64, "save reference")
            _text(value["key"], 256, "compatibility key")
        for member_id, member in document["members"].items():
            _hex(member_id, 32, "logical member")
            if not isinstance(member, dict) or set(member) != {"origin_acquisition", "current", "history"}:
                raise JournalError("incomplete logical member")
            location(member["current"])
            owner = document["contexts"][member["current"]["player"]]
            if owner is None or _save_ref(owner) != member["current"]["save_ref"]:
                raise JournalError("current member is bound to another save")
            if not isinstance(member["history"], list) or not member["history"]:
                raise JournalError("member identity history is missing")
            previous_location, previous_ordinal = None, 0
            for index, row in enumerate(member["history"]):
                if not isinstance(row, dict) or set(row) not in (
                        {"event", "location", "evidence_digest"}, {"event", "location", "evidence_digest", "before_evidence_digest"}):
                    raise JournalError("invalid member identity history")
                location(row["location"])
                _reference(row["event"])
                if row["event"] not in document["events"]:
                    raise JournalError("member history lost its identity event")
                _hex(row["evidence_digest"], 64, "identity evidence")
                if "before_evidence_digest" in row:
                    _hex(row["before_evidence_digest"], 64, "before evidence")
                event = document["events"][row["event"]]
                if event["ordinal"] <= previous_ordinal:
                    raise JournalError("member history is not in action order")
                if index == 0:
                    if (event["kind"] != "acquisition" or event["result"]["created"] is not True
                            or event["result"]["member_id"] != member_id or "before_evidence_digest" in row):
                        raise JournalError("member history does not start at its creating acquisition")
                    witness = cls._read_witness(event["request"]["witness"])
                    expected_origin = row["event"][:2] + event["request"]["acquisition_id"]
                    if (member["origin_acquisition"] != expected_origin or row["location"] != _location(witness)
                            or row["evidence_digest"] != witness.evidence_digest
                            or event["request"]["existing_member_id"] is not None):
                        raise JournalError("member acquisition origin differs from its witness")
                else:
                    if event["kind"] != "identity_migration" or "before_evidence_digest" not in row:
                        raise JournalError("member history requires a witnessed migration")
                    matches = [raw for raw in event["request"]["witnesses"] if raw["member_id"] == member_id]
                    if len(matches) != 1:
                        raise JournalError("member history names another migration participant")
                    witness = cls._read_migration(matches[0])
                    before = {"player": witness.source_context.player, "save_ref": _save_ref(asdict(witness.source_context)),
                              "key": witness.before_key}
                    if (before != previous_location or row["location"] != _location(witness.after)
                            or row["evidence_digest"] != witness.after.evidence_digest
                            or row["before_evidence_digest"] != witness.before_evidence_digest):
                        raise JournalError("member migration chain differs from its evidence")
                previous_location, previous_ordinal = row["location"], event["ordinal"]
            if member["history"][-1]["location"] != member["current"]:
                raise JournalError("current identity differs from its migration history")
            origin = document["acquisitions"].get(_reference(member["origin_acquisition"]))
            if not isinstance(origin, dict) or origin.get("member_id") != member_id or origin.get("origin") != member["history"][0]["location"]:
                raise JournalError("member lost its acquisition identity")
        _index(document)
        for ref, acquisition in document["acquisitions"].items():
            _reference(ref)
            if not isinstance(acquisition, dict) or set(acquisition) != {"member_id", "origin"}:
                raise JournalError("invalid acquisition bookkeeping")
            _hex(acquisition["member_id"], 32, "acquisition member")
            if acquisition["member_id"] not in document["members"]:
                raise JournalError("acquisition refers to an unknown member")
            location(acquisition["origin"])
            if acquisition["origin"]["player"] != ref[0]:
                raise JournalError("acquisition owner differs from its scoped reference")
            member = document["members"][acquisition["member_id"]]
            if not any(row["location"] == acquisition["origin"] for row in member["history"]):
                raise JournalError("acquisition origin has no witnessed member history")
            first = first_acquisition_events.get(ref)
            if first is None or _location(cls._read_witness(first["request"]["witness"])) != acquisition["origin"]:
                raise JournalError("acquisition origin differs from its first recorded observation")
        linked = set()
        for link_id, link in document["links"].items():
            _hex(link_id, 32, "logical link")
            if link_id in document["members"] or not isinstance(link, dict) or set(link) != {"members", "history", "created_by"}:
                raise JournalError("invalid logical link")
            created_by = document["events"].get(_reference(link["created_by"]))
            if created_by is None or created_by["kind"] != "link_creation" or created_by["result"]["link_id"] != link_id:
                raise JournalError("link creation provenance differs from its identity")
            previous_members, previous_ordinal = created_by["request"]["members"], created_by["ordinal"]
            cls._member_list(link["members"])
            if any(member not in document["members"] or member in linked for member in link["members"]):
                raise JournalError("unknown member or duplicate link membership")
            linked.update(link["members"])
            if not isinstance(link["history"], list):
                raise JournalError("invalid link identity history")
            for row in link["history"]:
                if not isinstance(row, dict) or set(row) != {"event", "members"}:
                    raise JournalError("invalid link assignment history")
                _reference(row["event"])
                if row["event"] not in document["events"]:
                    raise JournalError("link history lost its identity event")
                cls._member_list(row["members"])
                if any(member not in document["members"] for member in row["members"]):
                    raise JournalError("unknown historical link member")
                event = document["events"][row["event"]]
                if (event["kind"] != "link_assignment" or link_id not in event["request"]
                        or event["ordinal"] <= previous_ordinal or row["members"] != previous_members):
                    raise JournalError("link history differs from its assignment provenance")
                previous_members, previous_ordinal = event["request"][link_id], event["ordinal"]
            if link["members"] != previous_members:
                raise JournalError("current link membership differs from its assignment history")
        for ref, event in document["events"].items():
            _reference(ref)
            result = event["result"]
            if event["kind"] == "acquisition":
                if set(result) != {"member_id", "created", "acquisition_id"} or type(result["created"]) is not bool:
                    raise JournalError("invalid acquisition result")
                _hex(result["acquisition_id"], 32, "acquisition result")
                acquired = document["acquisitions"].get(ref[:2] + result["acquisition_id"])
                if acquired is None or acquired["member_id"] != result["member_id"]:
                    raise JournalError("acquisition result lost its member")
                member = document["members"][result["member_id"]]
                witness = cls._read_witness(event["request"]["witness"])
                prior = [row for row in member["history"] if document["events"][row["event"]]["ordinal"] <= event["ordinal"]]
                if not prior or prior[-1]["location"] != _location(witness):
                    raise JournalError("acquisition witness differs from the member at that action")
                if result["created"] != (member["history"][0]["event"] == ref):
                    raise JournalError("acquisition creation result differs from member provenance")
                if event["request"]["existing_member_id"] not in (None, result["member_id"]):
                    raise JournalError("confirmed acquisition alias targets another member")
            elif event["kind"] == "link_creation":
                if set(result) != {"link_id"} or result["link_id"] not in document["links"]:
                    raise JournalError("link result lost its identity")
                if document["links"][result["link_id"]]["created_by"] != ref:
                    raise JournalError("link creation result belongs to another action")
            else:
                field = "member_ids" if event["kind"] == "identity_migration" else "link_ids"
                keys = {field, "created_members"} if field == "member_ids" else {field}
                if set(result) != keys or not isinstance(result[field], list) or not 1 <= len(result[field]) <= 64:
                    raise JournalError("invalid migration/assignment result")
                if field == "member_ids" and (type(result["created_members"]) is not int or result["created_members"] != 0):
                    raise JournalError("identity migration cannot create members")
                known = document["members"] if field == "member_ids" else document["links"]
                for value in result[field]:
                    _hex(value, 32, "result identity")
                    if value not in known:
                        raise JournalError("migration result lost its identity")
                if len(set(result[field])) != len(result[field]):
                    raise JournalError("duplicate result identity")
                for value in result[field]:
                    history = known[value]["history"]
                    if sum(row["event"] == ref for row in history) != 1:
                        raise JournalError("identity action has no unique corresponding history row")
        if replay_history:
            cls._replay_history(document)

    @classmethod
    def restore(cls, document, *, run_id, new_id=None):
        cls.validate(document)
        if document["run_id"] != _hex(run_id, 32, "expected run"):
            raise JournalError("identity registry belongs to another run")
        result = cls(document["run_id"], new_id=new_id)
        result._document = copy.deepcopy(document)
        return result
