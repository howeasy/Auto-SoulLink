"""Generic index-preserving dispatch of a raw source-receipt wire list.

A consumed frame bundle carries ONE raw list of `{kind, receipt}` rows in the order the
client's observers published them. Whatever generation produced them, a settled fact must
point back at exactly the raw row it came from, so `source_ref = {event, index}` uses the
row's position in THAT list. Filtering by kind never renumbers: a caller that accepts one
kind still receives raw indices, and a row of a kind it does not accept is refused, never
silently skipped.

This module knows no game. A generation module (e.g. `server.gen1_source_receipts`) owns the
kind catalog, metadata/ROM policy and the per-kind decoders, and hands them in here.
"""

import copy

from server.protocol_journal import JournalError


def decode_rows(rows, *, reference, decoder, catalog, kinds=None):
    """Typed `{kind, fact, source_ref}` facts for raw `{kind, receipt}` rows, in wire order.

    `catalog` is every kind the generation knows (an unknown kind is a malformed bundle);
    `kinds` names what this caller accepts (default: the whole catalog); any other row is
    refused. `decoder(kind, receipt)` returns the fact. `source_ref.index` is the row's
    position in `rows` AS GIVEN: pass the whole raw list to keep indices wire-faithful, and
    pass `[raw[i]]` only to re-decode one row against its own stored reference.
    """
    if not isinstance(rows, list):
        raise JournalError('typed source receipt list required')
    accepted = tuple(catalog) if kinds is None else tuple(kinds)
    facts = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {'kind', 'receipt'} or row['kind'] not in catalog:
            raise JournalError('typed source receipt required')
        kind = row['kind']
        if kind not in accepted:
            raise JournalError('source receipt kind is not admitted here: ' + kind)
        facts.append({'kind': kind, 'fact': decoder(kind, row['receipt']),
                      'source_ref': {'event': copy.deepcopy(reference), 'index': index}})
    return facts


def frames_of(row, fact, table):
    """(every witness frame of a raw row in source order, the fact field naming the first one),
    via `table[kind](receipt, fact)` supplied by the generation module."""
    return table[row['kind']](row['receipt'], fact)

