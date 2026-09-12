"""Compact physical-job snapshots while retaining exact immutable journal proof.

Generation modules choose summaries. This helper never authorizes completion;
it binds each summary to one original full record and its commit revision.
"""

import copy
import re

from server.protocol import digest
from server.protocol_journal import JournalError, _record_key

SCHEMA = "slink-retained-physical-record-v1"


def is_retained(entry):
    return isinstance(entry, dict) and "retained" in entry


def validate_reference(reference):
    if (
        not isinstance(reference, dict)
        or set(reference)
        != {"schema", "namespace", "record_key", "record_revision", "record_digest"}
        or reference["schema"] != SCHEMA
        or type(reference["record_revision"]) is not int
        or reference["record_revision"] < 1
        or not isinstance(reference["record_digest"], str)
        or not re.fullmatch("[0-9a-f]{64}", reference["record_digest"])
    ):
        raise JournalError("complete retained physical record reference required")
    _record_key(reference["namespace"], reference["record_key"])
    return reference


def retain(namespace, key, revision, value, summary):
    if (
        not isinstance(value, dict)
        or not isinstance(summary, dict)
        or "retained" in value
        or "retained" in summary
    ):
        raise JournalError("one original physical record and detached summary required")
    reference = validate_reference(
        {
            "schema": SCHEMA,
            "namespace": namespace,
            "record_key": key,
            "record_revision": revision,
            "record_digest": digest(value),
        }
    )
    return (
        {**copy.deepcopy(summary), "retained": reference},
        {"namespace": namespace, "key": key, "value": copy.deepcopy(value)},
    )


def expand(journal, entry, *, namespace, summarize):
    if not is_retained(entry):
        return entry
    reference = validate_reference(entry["retained"])
    if reference["namespace"] != namespace:
        raise JournalError("retained physical record belongs to another component")
    record = journal.record(namespace, reference["record_key"])
    if (
        record is None
        or record.revision != reference["record_revision"]
        or is_retained(record.value)
        or digest(record.value) != reference["record_digest"]
    ):
        raise JournalError("retained physical record lost its exact immutable body/revision")
    try:
        summary = summarize(record.value)
    except (KeyError, TypeError, ValueError) as exc:
        raise JournalError("retained physical record cannot reproduce its summary") from exc
    if {**summary, "retained": reference} != entry:
        raise JournalError("retained physical summary differs from original evidence")
    return record.value
