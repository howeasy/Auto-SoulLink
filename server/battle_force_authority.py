"""R/B/Y binding of the one-instruction write authority for a battle force-faint (PROTOTYPE).

Generic lifecycle (owner / step / scope / one use / footprint, fail-safe hook-frame convention)
lives in ``server.instruction_authority``. This module pins the Gen 1 sites, the snapshot the
client must take at the instruction, and the decision: which bytes (if any) a linked mon's
death may write there. Never a held write; ``held_write_permit`` is untouched.

Sites (bank $0F), whichever the CPU reaches first inside the authorized frame:

* ``loop_head`` — ``MainInBattleLoop+0`` (core.asm Red 280 / Yellow 289): the next eleven
  bytes copy ``wBattleMonHP`` to the party slot and ``jp z, HandlePlayerMonFainted``.
* ``player_action`` — ``ExecutePlayerMove+0`` (Red 3073 / Yellow 3244): ``wPlayerSelectedMove
  = $FF`` is ``CANNOT_MOVE``, the engine's own skip (``inc a; jp z, ExecutePlayerMoveDone``,
  which sets ``b = 1``); both callers then run ``HandlePoisonBurnLeechSeed`` on the player's
  turn, whose tail ``ld a,[hli]; or [hl]; ret nz`` returns Z on zero HP, and
  ``jp z, HandlePlayerMonFainted`` (Red 437, 450 / Yellow 446, 459).

Branches decided from the client's snapshot (the server re-derives the same decision):

* active linked mon (``wPlayerMonNumber == slot``): write ``wBattleMonHP = 0000`` (+ the skip
  at ``player_action``). Identity = party slot species + DVs; the battle struct's species and
  DVs are compared too UNLESS ``TRANSFORMED`` (``wPlayerBattleStatus3`` bit 3) is set, because
  ``TransformEffect_`` copies the enemy's species and DVs into the battle struct
  (move_effects/transform.asm:57-88) while HP is not copied (":90 Skip level and max HP").
* benched linked mon (``wPlayerMonNumber != slot``): its party slot is its only copy during
  the battle; write party HP ``00 00`` and party status ``00`` for that slot. That is the
  state a genuinely fainted mon is left in (``RemoveFaintedPlayerMon`` zeroes status before
  the copy-down, Red 1022-1023); ``HasMonFainted`` (Red 1473-1480) then refuses to send it
  out, so it cannot act for the rest of the battle.

A second binding, ``rby-battle-force-explode`` (the ``force_explode`` command of Explode Mode),
shares both sites, the snapshot and every refusal above; only what the ACTIVE linked mon gets
written differs (the benched write is the faint binding's, byte for byte):

* ``loop_head``, active and NOT transformed: ``wBattleMonMoves[0..3] = EXPLOSION`` ($99) and
  ``wBattleMonPP[0..3] = 5``, eight bytes. All four slots because ``SelectMenuItem`` re-derives
  ``wPlayerSelectedMove`` from ``wBattleMonMoves[wCurrentMenuItem]`` on every confirm (core.asm
  Red 2660-2668), PP 5 so the menu never refuses a slot (``and PP_MASK; jr z, .noPP``). A
  transformed mon shows the enemy's copied moveset, not its own: refused, nothing written (the
  committed turn is still coerced below). HP is never written: the engine's own ``ExplodeEffect``
  zeroes the user's HP and status even on a miss (effects.asm), then the ordinary faint follows.
* ``player_action``, active: ``wPlayerSelectedMove = EXPLOSION``, one byte. ``GetCurrentMove``
  loads that id with no membership check and ``DecrementPP`` indexes PP by
  ``wPlayerMoveListIndex`` only. Refused when ``wActionResultOrTookBattleTurn != 0`` (an item,
  switch or failed run took the turn: ``jp nz, ExecutePlayerMoveDone`` would skip the move).

Outcome ``explode_armed`` is NOT terminal: sleep, freeze, paralysis, confusion or a RUN can still
stop the move that turn, so the caller re-issues while the death stays pending; the re-arm is
idempotent (before equals after, the footprint still verifies). Only ``benched`` is terminal.

Paths that leave the battle without reaching either site — a successful RUN or Poké Doll
(``DisplayBattleMenu`` then ``ret c`` / ``ret nz``, Red 305-309), a capture
(``.returnAfterCapturingMon`` ``scf; ret``) — end the battle before the dead mon can act;
the existing overworld held faint (``gen1_held_faint``) settles the death afterwards.
Refused (nothing written): Safari / old man / Yellow RUN + PIKACHU battle types, link
battles, an active mon that is neither the linked mon nor its Transform, a slot whose
species/DVs are not the linked mon's, an already-fainted target, an enemy at 0 HP.

Free-loop delivery (handoff item 5 on P4/P10). The durable wire carries commands, nothing
else, so the authority travels as the peer's own command ``battle_instruction`` (``COMMAND``:
``{cmd, death_id, key, authority}``), queued by ``pending_instruction`` from an observation
batch whose ``battle`` byte is non-zero (or from the ACK of the previous window) while the
peer's oldest pending command is the death's ``force_faint``/``force_explode``. Its window is
``WINDOW_FRAMES`` consecutive frames from the batch frame; the client may ENTER it late (the
command arrives several frames after the batch) and arms the same table once per frame until a
site is reached or the window, the battle or the command runs out, then closes the command with
the receipt ``RECEIPT`` (``{schema, challenge, frame, battle, rows}``). ``verify_window`` settles
those rows against the issued authority (``verify_issued`` reproduces it from its command) and
``gen1_faint_runtime.enforce`` records a ``fainted``/``benched`` verdict on the death exactly once;
``refused``/``not_reached``/``explode_armed`` leave the death pending and the ACK re-issues.
"""
import re

from server import instruction_authority as generic
from server.operation_scope import command_scope
from server.protocol import digest
from server.protocol_journal import JournalError

BINDING = 'rby-battle-force-faint'
EXPLODE = 'rby-battle-force-explode'
BINDINGS = {'force_faint': BINDING, 'force_explode': EXPLODE}  # the command names its binding; nothing else selects it
COMMAND = 'battle_instruction'  # the peer's command that carries one issued authority to the free loop
RECEIPT = 'rby-instruction-window-receipt-v1'  # its ACK receipt: the ordered evidence rows of the window
WINDOW_FRAMES = generic.MAX_WINDOW_FRAMES
TERMINAL = ('fainted', 'benched')  # the outcomes that enforce the death; explode_armed is re-issued (module docstring)
FAINTS = 'gen1-faint-settlement'
INITIAL = 'gen1-initial-observations'
EXPLOSION = 0x99  # constants/move_constants.asm: const EXPLOSION ; 99
EXPLODE_PP = 5
PARTY_STRIDE = 44
LINK_STATE_BATTLING = 4
BATTLE_TYPE_NORMAL = 0
TRANSFORMED = 1 << 3
# Frame the bus-exec hook observes (emu.framecount() inside the callback) minus the frame
# step_one was armed for. Measured live by lua/tests/test_gen1_battle_force_gate.lua on 2026-09-08:
# 0 on red, blue and yellow, both under emu.frameadvance and under platform_bounded_execution.step_one
# (BizHawk 2.11.1 Gambatte). Set back to None to refuse every reached row (fail-safe) if the host changes.
HOOK_FRAME_OFFSET = 0

_RB = {
    'bank': 0x0F,
    'loop_head': {'pc': 0x4233, 'expected_hex': 'cd434d2115d02ab6ca004721e6cf'},
    'player_action': {'pc': 0x565E, 'expected_hex': 'afe0f3fadccc3cca0a58afea5fd0', 'return_sites': [0x4364, 0x4380]},
    'poison_tail': {'pc': 0x4421, 'expected_hex': '2ab6c0cd5a4d0e14cd3937afc9'},
    'move_done': {'pc': 0x580A, 'expected_hex': 'afea6acd0601c9'},
    'addresses': {'wBattleMonHP': 0xD015, 'wBattleMonSpecies': 0xD014, 'wBattleMonDVs': 0xD020, 'wPlayerSelectedMove': 0xCCDC,
                  'wBattleMonMoves': 0xD01C, 'wBattleMonPP': 0xD02D,
                  'wPartyMon1': 0xD16B, 'wPartyMon1HP': 0xD16C, 'wPartyMon1Status': 0xD16F, 'wPartyMon1OTID': 0xD177, 'wPartyMon1DVs': 0xD186,
                  'wPlayerMonNumber': 0xCC2F, 'wIsInBattle': 0xD057, 'wBattleType': 0xD05A, 'wLinkState': 0xD12B,
                  'wEnemyMonHP': 0xCFE6, 'wActionResultOrTookBattleTurn': 0xCD6A, 'wPlayerBattleStatus3': 0xD064,
                  'hLoadedROMBank': 0xFFB8},
}
ANCHORS = {
    'red': _RB,
    'blue': _RB,
    'yellow': {
        'bank': 0x0F,
        'loop_head': {'pc': 0x4249, 'expected_hex': 'cd084e2114d02ab6ca1d4721e5cf'},
        'player_action': {'pc': 0x57D0, 'expected_hex': 'afe0f3fadccc3cca7c59afea5ed0', 'return_sites': [0x437A, 0x4396]},
        'poison_tail': {'pc': 0x4437, 'expected_hex': '2ab6c0cd1f4e0e14cd2f37afc9'},
        'move_done': {'pc': 0x597C, 'expected_hex': 'afea6acd0601c9'},
        'addresses': {'wBattleMonHP': 0xD014, 'wBattleMonSpecies': 0xD013, 'wBattleMonDVs': 0xD01F, 'wPlayerSelectedMove': 0xCCDC,
                      'wBattleMonMoves': 0xD01B, 'wBattleMonPP': 0xD02C,
                      'wPartyMon1': 0xD16A, 'wPartyMon1HP': 0xD16B, 'wPartyMon1Status': 0xD16E, 'wPartyMon1OTID': 0xD176, 'wPartyMon1DVs': 0xD185,
                      'wPlayerMonNumber': 0xCC2F, 'wIsInBattle': 0xD056, 'wBattleType': 0xD059, 'wLinkState': 0xD12A,
                      'wEnemyMonHP': 0xCFE5, 'wActionResultOrTookBattleTurn': 0xCD6A, 'wPlayerBattleStatus3': 0xD063,
                      'hLoadedROMBank': 0xFFB8},
    },
}
SITES = ('loop_head', 'player_action')
STATE_FIELDS = {'is_in_battle', 'battle_type', 'link_state', 'player_mon_number', 'status3', 'battle_species', 'battle_dvs_hex',
                'party_species', 'party_dvs_hex', 'party_ot_id_hex', 'party_hp_hex', 'party_status', 'hp_hex', 'enemy_hp_hex',
                'action_result', 'selected_move', 'moves_hex', 'pp_hex'}
BYTE_FIELDS = ('is_in_battle', 'battle_type', 'link_state', 'player_mon_number', 'status3', 'battle_species', 'party_species',
               'party_status', 'action_result', 'selected_move')
WORD_FIELDS = ('battle_dvs_hex', 'party_dvs_hex', 'party_ot_id_hex', 'party_hp_hex', 'hp_hex', 'enemy_hp_hex')
SLOT_FIELDS = ('moves_hex', 'pp_hex')  # wBattleMonMoves[0..3], wBattleMonPP[0..3]
KEY = re.compile(r'([0-9A-F]{4}):([0-9A-F]{4}):([0-9A-F]{2})')  # the codec's physical key: DVs:OTID:species (PartyCodec.validate_blob)


def member_of(key, slot):
    """The linked member a force_faint command names, parsed from its physical key."""
    match = KEY.fullmatch(key) if isinstance(key, str) else None
    if match is None or type(slot) is not int or not 0 <= slot <= 5:
        raise JournalError('physical key and party slot required')
    return {'slot': slot, 'species': int(match.group(3), 16), 'dvs_hex': match.group(1).lower(), 'ot_id_hex': match.group(2).lower()}


def sites(variant, binding=BINDING):
    a = ANCHORS[variant]
    out = {}
    for name in SITES:
        site = dict(a[name])
        site['bank'] = a['bank']
        site['writes'] = explode_writes(variant, name) if binding == EXPLODE else active_writes(variant, name)
        out[name] = site
    return out


def active_writes(variant, site):
    a = ANCHORS[variant]['addresses']
    rows = [{'address': a['wBattleMonHP'], 'value': 0}, {'address': a['wBattleMonHP'] + 1, 'value': 0}]
    if site == 'player_action':
        rows.append({'address': a['wPlayerSelectedMove'], 'value': 0xFF})
    return rows


def explode_writes(variant, site):
    a = ANCHORS[variant]['addresses']
    if site == 'player_action':
        return [{'address': a['wPlayerSelectedMove'], 'value': EXPLOSION}]
    return ([{'address': a['wBattleMonMoves'] + i, 'value': EXPLOSION} for i in range(4)]
            + [{'address': a['wBattleMonPP'] + i, 'value': EXPLODE_PP} for i in range(4)])


def benched_writes(variant, slot):
    a = ANCHORS[variant]['addresses']
    hp = a['wPartyMon1HP'] + PARTY_STRIDE * slot
    return [{'address': hp, 'value': 0}, {'address': hp + 1, 'value': 0}, {'address': a['wPartyMon1Status'] + PARTY_STRIDE * slot, 'value': 0}]


def decide(state, member, variant, site, binding=BINDING):
    """{'writes': [...], 'refusal': None, 'outcome': 'fainted'|'explode_armed'|'benched'} or {'writes': [], 'refusal': reason}.
    Same function, same order, as lua/battle_force_authority.lua decide(); ``binding`` selects the active write."""
    def refuse(reason):
        return {'writes': [], 'refusal': reason}
    if state['is_in_battle'] not in (1, 2):
        return refuse('not in a wild or trainer battle')
    if state['battle_type'] != BATTLE_TYPE_NORMAL:
        return refuse('no player mon in play for this battle type')
    if state['link_state'] == LINK_STATE_BATTLING:
        return refuse('link battle would desync')
    if (state['party_species'] != member['species'] or state['party_dvs_hex'] != member['dvs_hex']
            or state['party_ot_id_hex'] != member['ot_id_hex']):
        return refuse('party slot is not the linked mon')
    if state['player_mon_number'] != member['slot']:
        if state['party_hp_hex'] == '0000':
            return refuse('already fainted')
        return {'writes': benched_writes(variant, member['slot']), 'refusal': None, 'outcome': 'benched'}
    if not state['status3'] & TRANSFORMED and (state['battle_species'] != member['species'] or state['battle_dvs_hex'] != member['dvs_hex']):
        return refuse('active battle struct is not the linked mon')
    if state['hp_hex'] == '0000':
        return refuse('already fainted')
    if state['enemy_hp_hex'] == '0000':
        return refuse('enemy faint path owns this turn')
    if binding != EXPLODE:
        return {'writes': active_writes(variant, site), 'refusal': None, 'outcome': 'fainted'}
    if site == 'loop_head' and state['status3'] & TRANSFORMED:
        return refuse('transformed battle mon keeps the copied moveset')
    if site == 'player_action' and state['action_result'] != 0:
        return refuse('turn already taken')
    return {'writes': explode_writes(variant, site), 'refusal': None, 'outcome': 'explode_armed'}


def prepare(player, command, binding, death, member, host, *, variant):
    """Bind one pending owned death to one bounded step. Same obligation as gen1_held_faint.verify;
    the caller supplies the linked member's stable slot/species/DVs and the bounded owner's next step
    (``host['count']``, default 1, widens the authority to that many consecutive steps: instruction_authority window)."""
    body = command['body']
    name = BINDINGS.get(body.get('cmd'))
    if name is None or 'death_id' not in body:
        raise JournalError('battle instruction authority serves force_faint and force_explode only')
    if (not isinstance(death, dict) or death.get('phase') != 'pending_faint' or death.get('peer') != player
            or death.get('peer_key') != body.get('key')):
        raise JournalError('battle instruction authority lacks its pending owned death obligation')
    if not isinstance(member, dict) or set(member) != {'slot', 'species', 'dvs_hex', 'ot_id_hex'}:
        raise JournalError('stable linked member slot/species/DVs/OT id required')
    if member != member_of(body['key'], member['slot']):
        raise JournalError('linked member differs from the physical key the command names')
    if not isinstance(host, dict) or not {'owner_id', 'frame', 'step'} <= set(host) <= {'owner_id', 'frame', 'step', 'count'}:
        raise JournalError('bounded owner id, frame and step required')
    if variant not in ANCHORS:
        raise JournalError('unsupported title')
    proof = {'death_id': body['death_id'], 'key': body['key'], 'member': member, 'host': host, 'variant': variant}
    return generic.VerifiedInstructionAuthority(command_scope(command, binding, phase='battle_force_faint'), digest(proof), host['owner_id'],
                                                host['frame'], host['step'], name, {**member, 'variant': variant}, host.get('count', 1))


def issue(request, proof):
    if not isinstance(proof, generic.VerifiedInstructionAuthority) or proof.binding not in BINDINGS.values():
        raise ValueError('verified battle instruction authority required')
    variant = proof.member['variant']
    return generic.issue(request, proof, sites(variant, proof.binding), ANCHORS[variant]['addresses'], hook_frame_offset=HOOK_FRAME_OFFSET)


def verify_evidence(authority, evidence, *, hook_frame_offset=None):
    """Return {'outcome': 'fainted'|'explode_armed'|'benched'|'refused'|'not_reached', 'site', 'reason'} or raise JournalError."""
    if authority.get('binding') not in BINDINGS.values():
        raise JournalError('authority is not a battle force-faint authority')
    site = generic.verify_envelope(authority, evidence, hook_frame_offset=hook_frame_offset)
    if site is None:
        return {'outcome': 'not_reached', 'site': None, 'reason': 'neither pinned PC was executed in the authorized frame'}
    state = evidence['state']
    if not isinstance(state, dict) or set(state) != STATE_FIELDS:
        raise JournalError('complete instruction state snapshot required')
    for key in BYTE_FIELDS:
        if type(state[key]) is not int or not 0 <= state[key] <= 255:
            raise JournalError('instruction state bytes required')
    for key in WORD_FIELDS:
        if not isinstance(state[key], str) or not re.fullmatch('[0-9a-f]{4}', state[key]):
            raise JournalError('instruction state words required')
    for key in SLOT_FIELDS:
        if not isinstance(state[key], str) or not re.fullmatch('[0-9a-f]{8}', state[key]):
            raise JournalError('instruction state move slots required')
    member = authority['member']
    decision = decide(state, member, member['variant'], site, binding=authority['binding'])
    a = authority['addresses']
    slot = member['slot']
    before = {a['wBattleMonHP']: int(state['hp_hex'][0:2], 16), a['wBattleMonHP'] + 1: int(state['hp_hex'][2:4], 16),
              a['wPlayerSelectedMove']: state['selected_move'],
              a['wPartyMon1HP'] + PARTY_STRIDE * slot: int(state['party_hp_hex'][0:2], 16),
              a['wPartyMon1HP'] + PARTY_STRIDE * slot + 1: int(state['party_hp_hex'][2:4], 16),
              a['wPartyMon1Status'] + PARTY_STRIDE * slot: state['party_status']}
    for i in range(4):
        before[a['wBattleMonMoves'] + i] = int(state['moves_hex'][2 * i:2 * i + 2], 16)
        before[a['wBattleMonPP'] + i] = int(state['pp_hex'][2 * i:2 * i + 2], 16)
    outcome = generic.verify_footprint(evidence, decision, before)
    return {'outcome': outcome, 'site': site, 'reason': decision['refusal']}


def challenge_for(seed, death_id):
    """Deterministic one-use challenge: the issuing event and the death it serves (a replay reproduces it)."""
    return digest({'instruction': seed, 'death_id': death_id})[:32]


def pending_instruction(runtime, stage, document, player, *, frame, seed, binding, ignore=None):
    """The ``battle_instruction`` command for ``player``'s oldest pending death command, or None.

    None when nothing is pending, the oldest pending command is not ``force_faint``/``force_explode``,
    its death is not ``pending_faint`` (or already carries ``enforcement``), another window is still
    outstanding (``ignore`` names the one being acknowledged), or the linked member is not in the
    party roster. ``frame`` is the first frame of the ``WINDOW_FRAMES`` window; the step is the
    free-run anchor rule (frames since enrollment, plus one), so per-frame steps stay monotonic
    across windows. The command body is the journal's, so a replay reproduces the same authority."""
    pending = [i for i in runtime.journal.pending_ids(player) if i != ignore]
    if not pending:
        return None
    commands = [runtime.journal.command(player, identifier) for identifier in pending]
    if any(c['body'].get('cmd') == COMMAND for c in commands):
        return None
    command = commands[0]
    body = command['body']
    if body.get('cmd') not in BINDINGS or 'death_id' not in body:
        return None
    death = document['components'].get(FAINTS, {}).get('deaths', {}).get(body['death_id'])
    if (death is None or death.get('phase') != 'pending_faint' or 'enforcement' in death or death.get('peer') != player
            or death.get('peer_key') != body.get('key')):
        return None
    row = next((r for r in stage.rules.partner_blobs[player] if r['key'] == body['key']), None)
    if row is None:
        return None
    initial = document['components'][INITIAL][player]
    anchor = initial['observation']['frame']
    if type(frame) is not int or frame < anchor:
        raise JournalError('instruction window must start at or after the enrollment frame')
    variant = initial['metadata']['gen1_metadata']['cartridge']['variant']
    host = {'owner_id': initial['metadata']['gen1_metadata']['physical_instance'], 'frame': frame, 'step': frame - anchor + 1,
            'count': WINDOW_FRAMES}
    proof = prepare(player, command, binding, death, member_of(body['key'], row['slot']), host, variant=variant)
    authority = issue({'schema': generic.SCHEMA, 'challenge': challenge_for(seed, body['death_id']), 'scope': dict(proof.scope)}, proof)
    return {'cmd': COMMAND, 'death_id': body['death_id'], 'key': body['key'], 'authority': authority}


def verify_issued(authority, command, binding, *, player, anchor, owner_id):
    """The journaled authority is exactly what ``prepare``/``issue`` produce for its death command under the
    free-run anchor rule for the enrolled owner; a tampered owner, frame, step, member, sites or addresses is
    refused (the challenge is deterministic from the issuing event, ``challenge_for``, and the receipt must echo it)."""
    if not isinstance(authority, dict) or not isinstance(authority.get('member'), dict) or not isinstance(authority.get('challenge'), str):
        raise JournalError('battle instruction authority required')
    if authority.get('owner_id') != owner_id:
        raise JournalError('battle instruction authority names another owner')
    body = command['body']
    member = {k: authority['member'].get(k) for k in ('slot', 'species', 'dvs_hex', 'ot_id_hex')}
    variant = authority['member'].get('variant')
    if variant not in ANCHORS:
        raise JournalError('battle instruction authority names an unsupported title')
    first, count = generic.window(authority)
    if type(anchor) is not int or authority.get('step') != first - anchor + 1 or count != WINDOW_FRAMES:
        raise JournalError('battle instruction authority window differs from the free-run rule')
    death = {'phase': 'pending_faint', 'peer': player, 'peer_key': body.get('key')}
    host = {'owner_id': authority.get('owner_id'), 'frame': first, 'step': authority['step'], 'count': count}
    try:
        proof = prepare(player, command, binding, death, member, host, variant=variant)
        expected = issue({'schema': generic.SCHEMA, 'challenge': authority['challenge'], 'scope': dict(proof.scope)}, proof)
    except (ValueError, TypeError) as error:
        raise JournalError('battle instruction authority does not reproduce from its command') from error
    if authority != expected:
        raise JournalError('battle instruction authority differs from the one its command issues')
    return expected


def verify_window(authority, rows, *, hook_frame_offset=None):
    """Settle the ordered rows of one free-loop window. The client may have entered the window late, so the
    rows start anywhere inside ``frames`` and run contiguously from there (the generic verifier is given the
    authority rebased to that entry frame, which keeps every per-row frame/step check exact).
    Returns ``{'covered': [first, last], 'outcome', 'row'}`` exactly as ``instruction_authority.verify_window``."""
    first, count = generic.window(authority)
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise JournalError('instruction window evidence must cover one to count frames')
    start = rows[0].get('frame')
    if type(start) is not int or not first <= start < first + count:
        raise JournalError('instruction window evidence starts outside the authority window')
    rebased = {**authority, 'frame': start, 'step': authority['step'] + (start - first)}
    if 'frames' in authority:
        rebased['frames'] = {'first': start, 'count': first + count - start}
    return generic.verify_window(rebased, rows, verify_row=verify_evidence, hook_frame_offset=hook_frame_offset)
