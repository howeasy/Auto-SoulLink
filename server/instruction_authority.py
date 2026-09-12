"""Generation-independent one-instruction write authority (owner / step / scope / one use / footprint).

A binding (e.g. ``battle_force_authority`` for R/B/Y) supplies the pinned sites, the state
snapshot shape and the decision function; this module owns everything that must be true
regardless of game: the authority names exactly one ``(owner_id, frame, step)`` of the single
bounded owner, is issued once against a verified proof, and the evidence for it must come
from a bus-exec hook that fired inside that one released frame (``held: false``), at the
pinned PC and bank, with exactly the decided byte footprint and nothing else.

Window: an authority may cover ``frames = {first, count}`` consecutive frames (count 1..
``MAX_WINDOW_FRAMES``) stepped by the same owner, steps ``step .. step+count-1``, so production
need not round-trip once per frame. It is still one use: the first site reached consumes it and
nothing may be stepped under that challenge afterwards (``verify_window``). ``frame`` stays
``frames.first``; a count of 1 is exactly the single-frame authority and carries no ``frames``.

Fail-safe: the frame number a hook observes relative to the frame being stepped is a host
convention that must be measured live. ``verify_envelope`` refuses every REACHED evidence row
until the caller passes the measured ``hook_frame_offset``; ``not_reached`` rows need no
convention because nothing was written.
"""
import re
from dataclasses import dataclass
from types import MappingProxyType

from server.operation_scope import _scope
from server.protocol_journal import JournalError

SCHEMA = 'slink-instruction-authority-v1'
EVIDENCE = 'slink-instruction-evidence-v1'
MAX_WINDOW_FRAMES = 64
ENVELOPE_FIELDS = {'schema', 'challenge', 'owner_id', 'frame', 'step', 'held', 'site', 'pc', 'bank', 'sp', 'stack_hex',
                   'hook_frame', 'state', 'writes', 'refusal'}


@dataclass(frozen=True)
class VerifiedInstructionAuthority:
    """Proof that one obligation may be enforced at one instruction of one bounded step."""
    scope: dict
    proof_digest: str
    owner_id: str
    frame: int
    step: int
    binding: str
    member: dict
    count: int = 1

    def __post_init__(self):
        object.__setattr__(self, 'scope', MappingProxyType(_scope(self.scope)))
        if not isinstance(self.proof_digest, str) or not re.fullmatch('[0-9a-f]{64}', self.proof_digest):
            raise ValueError('verified instruction proof digest required')
        if not isinstance(self.owner_id, str) or not re.fullmatch('[0-9a-f]{32}', self.owner_id):
            raise ValueError('bounded owner identity required')
        if type(self.frame) is not int or self.frame < 0 or type(self.step) is not int or self.step < 1:
            raise ValueError('exact bounded frame and positive step required')
        if not isinstance(self.binding, str) or not re.fullmatch('[a-z][a-z0-9_-]{0,63}', self.binding) or not isinstance(self.member, dict):
            raise ValueError('binding name and member required')
        if type(self.count) is not int or not 1 <= self.count <= MAX_WINDOW_FRAMES:
            raise ValueError(f'instruction window of 1..{MAX_WINDOW_FRAMES} frames required')
        object.__setattr__(self, 'member', MappingProxyType(dict(self.member)))


def issue(request, proof, sites, addresses, *, hook_frame_offset, frames=None):
    """One-use authority the client arms before each step_one of its window. Carries its own site table.
    ``frames`` defaults to the proof's window and may not differ from it."""
    if not isinstance(proof, VerifiedInstructionAuthority):
        raise ValueError('verified instruction authority required')
    if not isinstance(request, dict) or set(request) != {'schema', 'challenge', 'scope'} or request['schema'] != SCHEMA:
        raise ValueError('exact instruction authority request required')
    if not isinstance(request['challenge'], str) or not re.fullmatch('[0-9a-f]{32}', request['challenge']):
        raise ValueError('instruction authority challenge required')
    if _scope(request['scope']) != dict(proof.scope):
        raise ValueError('instruction authority scope differs')
    if type(hook_frame_offset) is not int:
        raise ValueError('measured hook frame convention required before issuing (fail-safe)')
    for name, site in sites.items():
        if set(site) - {'pc', 'bank', 'expected_hex', 'writes', 'return_sites'} or type(site['pc']) is not int or type(site['bank']) is not int:
            raise ValueError('pinned site required: ' + name)
    if frames is None:
        frames = {'first': proof.frame, 'count': proof.count}
    if frames != {'first': proof.frame, 'count': proof.count}:
        raise ValueError('instruction authority window differs from the proof')
    authority = {'schema': SCHEMA, 'challenge': request['challenge'], 'scope': dict(proof.scope), 'proof_digest': proof.proof_digest,
                 'owner_id': proof.owner_id, 'frame': proof.frame, 'step': proof.step, 'uses': 1, 'held': False,
                 'binding': proof.binding, 'member': dict(proof.member), 'sites': sites, 'addresses': dict(addresses),
                 'hook_frame_offset': hook_frame_offset}
    if proof.count > 1:  # a count of 1 is the single-frame authority, byte-for-byte as before
        authority['frames'] = dict(frames)
    return authority


def window(authority):
    """``(first, count)`` of the authority's frame window; no ``frames`` means the one frame ``frame``."""
    frames = authority.get('frames')
    if frames is None:
        return authority['frame'], 1
    if (not isinstance(frames, dict) or set(frames) != {'first', 'count'} or frames['first'] != authority['frame']
            or type(frames['count']) is not int or not 1 <= frames['count'] <= MAX_WINDOW_FRAMES):
        raise JournalError('instruction authority window is malformed')
    return frames['first'], frames['count']


def verify_envelope(authority, evidence, *, hook_frame_offset=None):
    """Check everything generic; return the reached site name, or None for an unreached frame.
    `hook_frame_offset` defaults to the convention the authority itself carried to the client."""
    if hook_frame_offset is None:
        hook_frame_offset = authority.get('hook_frame_offset')
    if not isinstance(evidence, dict) or set(evidence) != ENVELOPE_FIELDS:
        raise JournalError('complete instruction evidence required')
    if evidence['schema'] != EVIDENCE or evidence['challenge'] != authority['challenge'] or evidence['owner_id'] != authority['owner_id']:
        raise JournalError('evidence answers a different instruction authority')
    first, count = window(authority)
    if (type(evidence['frame']) is not int or not first <= evidence['frame'] < first + count
            or evidence['step'] != authority['step'] + (evidence['frame'] - first)):
        raise JournalError('evidence is not from the authorized bounded step')
    if evidence['held'] is not False:
        raise JournalError('a bus-exec hook cannot fire in a held frame; evidence claims otherwise')
    site = evidence['site']
    if site is None:
        if any(evidence[k] is not None for k in ('pc', 'bank', 'sp', 'stack_hex', 'hook_frame', 'state', 'refusal')) or evidence['writes'] != []:
            raise JournalError('an unreached authority carries no instruction state')
        return None
    if site not in authority['sites']:
        raise JournalError('unknown instruction site')
    if hook_frame_offset is None:
        raise JournalError('hook frame convention is unverified; reached evidence cannot be trusted')
    if type(evidence['hook_frame']) is not int or evidence['hook_frame'] - evidence['frame'] != hook_frame_offset:
        raise JournalError('hook fired outside the authorized frame')
    pinned = authority['sites'][site]
    if evidence['pc'] != pinned['pc'] or evidence['bank'] != pinned['bank']:
        raise JournalError('evidence PC/bank is not the pinned instruction')
    if (type(evidence['sp']) is not int or not 0xC000 <= evidence['sp'] <= 0xDFFC or not isinstance(evidence['stack_hex'], str)
            or not re.fullmatch('[0-9a-f]{8}', evidence['stack_hex'])):
        raise JournalError('stack window required')
    if pinned.get('return_sites'):
        ret = int(evidence['stack_hex'][0:2], 16) + 256 * int(evidence['stack_hex'][2:4], 16)
        if ret not in pinned['return_sites']:
            raise JournalError('instruction was not entered from its pinned caller')
    return site


def verify_window(authority, rows, *, verify_row, hook_frame_offset=None):
    """Settle the ordered per-frame evidence rows of one authority's window.
    ``verify_row(authority, row, hook_frame_offset=...)`` is the binding's verifier (e.g. battle_force_authority.verify_evidence)
    and must return ``{'outcome': ...}``. Rows must run contiguously from ``frames.first``, at most ``count`` of them; at most
    one may be reached (writes or refusal) and it must be the last: nothing is stepped under a consumed challenge.
    Returns ``{'covered': [first, last], 'outcome': <reached row's outcome or 'not_reached'>, 'row': reached_row_or_None}``."""
    first, count = window(authority)
    if not isinstance(rows, list) or not 1 <= len(rows) <= count:
        raise JournalError('instruction window evidence must cover one to count frames')
    reached, outcome = None, 'not_reached'
    for i, row in enumerate(rows):
        settled = verify_row(authority, row, hook_frame_offset=hook_frame_offset)
        if row['frame'] != first + i:
            raise JournalError('instruction window evidence is not contiguous')
        if row['site'] is not None:
            if i != len(rows) - 1:
                raise JournalError('a reached row must be the last row of its instruction window')
            reached, outcome = row, settled['outcome']
    return {'covered': [first, first + len(rows) - 1], 'outcome': outcome, 'row': reached}


def verify_footprint(evidence, decision, before):
    """The client wrote exactly what the binding decides from the client's own snapshot, nothing else.
    ``decision`` = {'writes': [{address, value}], 'refusal': str|None}; ``before`` maps address -> byte before."""
    if decision['refusal'] is not None:
        if evidence['writes'] != [] or evidence['refusal'] != decision['refusal']:
            raise JournalError('client wrote or misreported a refused instruction')
        return 'refused'
    if evidence['refusal'] is not None:
        raise JournalError('client refused an admissible instruction')
    expected = decision['writes']
    rows = evidence['writes']
    if (not isinstance(rows, list) or len(rows) != len(expected)
            or any(not isinstance(w, dict) or set(w) != {'address', 'before_hex', 'after_hex'} for w in rows)):
        raise JournalError('exact authorized write set required')
    for w, e in zip(rows, expected, strict=True):
        if w['address'] != e['address'] or w['after_hex'] != f"{e['value']:02x}" or w['before_hex'] != f"{before[e['address']]:02x}":
            raise JournalError('write outside the authorized byte set or readback differs')
    return 'fainted' if decision.get('outcome') is None else decision['outcome']
