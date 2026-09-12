"""R/B/Y source-receipt catalog: which wire kinds exist, how each decodes, which frames it claims.

`bundle['acquisitions']` rows: captures, scripted grants, static-battle origins and ends, NPC
exchanges, wild-encounter begins and ends, and ordinary evolutions. Metadata/ROM policy lives here (admitted cartridge,
UPR-rewritten operands, canonical fallback); the index-preserving walk over the raw list is the
generic `server.source_receipts.decode_rows`. This module settles nothing.
"""

import hashlib

from server import source_receipts
from server.gen1_capture_receipt import (
    DATA as CAPTURE_DATA,
    SCHEMA as CAPTURE_SCHEMA,
    decode_capture,
)
from server.gen1_grant_receipt import DATA as GRANT_DATA, validate as validate_grant
from server.gen1_npc_exchange_receipt import (
    SCHEMA as EXCHANGE_SCHEMA,
    validate as validate_exchange,
)
from server.gen1_static_receipt import (
    DATA as STATIC_DATA,
    validate as validate_origin,
    validate_end,
)
from server.gen1_wild_encounter_receipt import validate as validate_wild
from server.protocol_journal import JournalError

KINDS = ('capture', 'grant', 'static_origin', 'static_battle_end', 'npc_exchange', 'wild_begin', 'wild_end', 'evolution')
ACQUISITION_KINDS = ('capture', 'grant')
LIFECYCLE_KINDS = ('static_origin', 'static_battle_end', 'capture')
EXCHANGE_KINDS = ('npc_exchange',)
ENCOUNTER_KINDS = ('wild_begin', 'wild_end')  # transport only: the wild lifecycle consumes these elsewhere
EVOLUTION_KINDS = ('evolution',)
CAPTURE_HEADER = {'schema', 'source_sha256', 'variant', 'context_generation', 'final_sha1', 'receipt'}


def _operands(rom, cartridge, site, label):
    """The pinned species bytes as the admitted ROM holds them (an approved UPR rewrite)."""
    if not isinstance(rom, bytes) or hashlib.sha1(rom).hexdigest() != cartridge['final_rom_sha1']:
        raise JournalError(label + ' operands differ from admitted ROM bytes')
    if site is None or any(offset >= len(rom) for offset in site['species']['rom_offsets']):
        raise JournalError(label + ' source operand leaves admitted ROM')
    return {offset: rom[offset] for offset in site['species']['rom_offsets']}


def _canonical(cartridge, label):
    from server.gen1_acquisition_runtime import _canonical_cartridges

    if cartridge not in _canonical_cartridges():
        raise JournalError('randomized ' + label + ' requires complete admitted ROM bytes')


def decoder(metadata, binding, *, rom=None, rom_bytes=None):
    """The per-kind decoder for one admitted context: `decoder(kind, receipt) -> fact`.
    `rom` is the admitted cartridge image for pinned mutable operands (`rom_bytes` a pre-read map)."""
    cartridge = metadata['gen1_metadata']['cartridge']
    variant = cartridge['variant']
    scope = {
        'variant': variant,
        'identity': metadata['save_identity'],
        'context_generation': binding['context_generation'],
        'physical_instance': metadata['gen1_metadata']['physical_instance'],
        'final_sha1': cartridge['final_rom_sha1'],
    }

    def pinned_operands(data, receipt, label):
        if rom is not None:
            sites = data['titles'][variant]['sites']
            return _operands(rom, cartridge, sites.get(receipt.get('source_id')) if isinstance(receipt, dict) else None, label)
        _canonical(cartridge, label)
        return rom_bytes

    def decode_one(kind, receipt):
        if kind == 'evolution':
            from server.gen1_evolution_receipt import validate as validate_evolution
            return validate_evolution(receipt, rom=rom, **scope)
        if kind == 'capture':
            if (not isinstance(receipt, dict) or set(receipt) != CAPTURE_HEADER
                    or receipt['schema'] != CAPTURE_SCHEMA or receipt['source_sha256'] != CAPTURE_DATA['sha256']
                    or receipt['variant'] != variant or receipt['context_generation'] != binding['context_generation']
                    or receipt['final_sha1'] != cartridge['final_rom_sha1']):
                raise JournalError('capture receipt differs from admission/source')
            return decode_capture(receipt['receipt'], variant, metadata['save_identity'])
        if kind == 'grant':
            fact = validate_grant(receipt, rom_bytes=pinned_operands(GRANT_DATA, receipt, 'grant'), **scope)
            if 'paid' in receipt:
                # Stabilization cannot predate the last required payment witness.
                fact = {**fact, 'settlement_frame': receipt['paid']['frame']}
            return fact
        if kind == 'static_origin':
            return validate_origin(receipt, rom_bytes=pinned_operands(STATIC_DATA, receipt, 'static'), **scope)
        if kind == 'static_battle_end':
            return validate_end(receipt, **scope)
        if kind in ENCOUNTER_KINDS:
            # wire kind 'wild_begin'/'wild_end' must carry a receipt of kind 'begin'/'end'
            if not isinstance(receipt, dict) or receipt.get('kind') != kind[len('wild_'):]:
                raise JournalError('wild encounter row kind differs from its receipt')
            return validate_wild(receipt, **scope)
        if not isinstance(receipt, dict) or receipt.get('schema') != EXCHANGE_SCHEMA:
            raise JournalError('exchange receipt differs from its source schema')
        return validate_exchange(receipt, **scope)

    return decode_one


def decode(rows, metadata, binding, *, reference, rom=None, rom_bytes=None, kinds=KINDS):
    """Typed `{kind, fact, source_ref}` facts for raw `{kind, receipt}` rows, in wire order (see source_receipts.decode_rows)."""
    return source_receipts.decode_rows(rows, reference=reference, decoder=decoder(metadata, binding, rom=rom, rom_bytes=rom_bytes),
                                       catalog=KINDS, kinds=kinds)


def _grant_frames(receipt, fact):
    values = [receipt['call']['frame'], receipt['return']['frame']]
    if 'paid' in receipt:
        values.append(receipt['paid']['frame'])
    return values, fact['call_frame']


FRAMES = {
    'evolution': lambda receipt, fact: ([receipt['before']['frame'], receipt['after']['frame']], fact['call_frame']),
    'capture': lambda receipt, fact: ([receipt['receipt']['begin']['frame'], receipt['receipt']['end']['frame']], fact['call_frame']),
    'grant': _grant_frames,
    'static_origin': lambda receipt, fact: ([receipt['arm']['frame'], receipt['began']['frame']], fact['arm_frame']),
    'static_battle_end': lambda receipt, fact: ([receipt['end']['frame']], fact['frame']),
    'wild_begin': lambda receipt, fact: ([receipt['witness']['frame']], fact['frame']),
    'wild_end': lambda receipt, fact: ([receipt['witness']['frame']], fact['frame']),
    'npc_exchange': lambda receipt, fact: ([receipt['call']['frame'], receipt['remove']['frame'], receipt['return']['frame']], fact['call_frame']),
}


def witness_frames(row, fact):
    """(every witness frame of a raw row in source order, the fact field naming the first one)."""
    return source_receipts.frames_of(row, fact, FRAMES)
