"""Generation-independent exact command provenance for physical job receipts."""

from server.event_reference import resolve
from server.protocol_journal import JournalError


def issued(journal, player, origin, body):
    event = resolve(journal, origin)
    matches = []
    for identifier in event.command_ids:
        try:
            command = journal.command(player, identifier)
        except JournalError:
            continue  # The same commit can publish commands for the other player.
        if command["body"] == body:
            matches.append(command)
    if len(matches) != 1:
        raise JournalError("physical job lacks one exact issuing command")
    return matches[0]
