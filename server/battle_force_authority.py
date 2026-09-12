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

Paths that leave the battle without reaching either site — a successful RUN or Poké Doll
(``DisplayBattleMenu`` then ``ret c`` / ``ret nz``, Red 305-309), a capture
(``.returnAfterCapturingMon`` ``scf; ret``) — end the battle before the dead mon can act;
the existing overworld held faint (``gen1_held_faint``) settles the death afterwards.
Refused (nothing written): Safari / old man / Yellow RUN + PIKACHU battle types, link
battles, an active mon that is neither the linked mon nor its Transform, a slot whose
species/DVs are not the linked mon's, an already-fainted target, an enemy at 0 HP.
"""
import re

from server import instruction_authority as generic
from server.operation_scope import command_scope
from server.protocol import digest
from server.protocol_journal import JournalError

BINDING = 'rby-battle-force-faint'
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
                      'wPartyMon1': 0xD16A, 'wPartyMon1HP': 0xD16B, 'wPartyMon1Status': 0xD16E, 'wPartyMon1OTID': 0xD176, 'wPartyMon1DVs': 0xD185,
                      'wPlayerMonNumber': 0xCC2F, 'wIsInBattle': 0xD056, 'wBattleType': 0xD059, 'wLinkState': 0xD12A,
                      'wEnemyMonHP': 0xCFE5, 'wActionResultOrTookBattleTurn': 0xCD6A, 'wPlayerBattleStatus3': 0xD063,
                      'hLoadedROMBank': 0xFFB8},
    },
}
SITES = ('loop_head', 'player_action')
STATE_FIELDS = {'is_in_battle', 'battle_type', 'link_state', 'player_mon_number', 'status3', 'battle_species', 'battle_dvs_hex',
                'party_species', 'party_dvs_hex', 'party_ot_id_hex', 'party_hp_hex', 'party_status', 'hp_hex', 'enemy_hp_hex',
                'action_result', 'selected_move'}
BYTE_FIELDS = ('is_in_battle', 'battle_type', 'link_state', 'player_mon_number', 'status3', 'battle_species', 'party_species',
               'party_status', 'action_result', 'selected_move')
WORD_FIELDS = ('battle_dvs_hex', 'party_dvs_hex', 'party_ot_id_hex', 'party_hp_hex', 'hp_hex', 'enemy_hp_hex')
KEY = re.compile(r'([0-9A-F]{4}):([0-9A-F]{4}):([0-9A-F]{2})')  # the codec's physical key: DVs:OTID:species (PartyCodec.validate_blob)


def member_of(key, slot):
    """The linked member a force_faint command names, parsed from its physical key."""
    match = KEY.fullmatch(key) if isinstance(key, str) else None
    if match is None or type(slot) is not int or not 0 <= slot <= 5:
        raise JournalError('physical key and party slot required')
    return {'slot': slot, 'species': int(match.group(3), 16), 'dvs_hex': match.group(1).lower(), 'ot_id_hex': match.group(2).lower()}


def sites(variant):
    a = ANCHORS[variant]
    out = {}
    for name in SITES:
        site = dict(a[name])
        site['bank'] = a['bank']
        site['writes'] = active_writes(variant, name)
        out[name] = site
    return out


def active_writes(variant, site):
    a = ANCHORS[variant]['addresses']
    rows = [{'address': a['wBattleMonHP'], 'value': 0}, {'address': a['wBattleMonHP'] + 1, 'value': 0}]
    if site == 'player_action':
        rows.append({'address': a['wPlayerSelectedMove'], 'value': 0xFF})
    return rows


def benched_writes(variant, slot):
    a = ANCHORS[variant]['addresses']
    hp = a['wPartyMon1HP'] + PARTY_STRIDE * slot
    return [{'address': hp, 'value': 0}, {'address': hp + 1, 'value': 0}, {'address': a['wPartyMon1Status'] + PARTY_STRIDE * slot, 'value': 0}]


def decide(state, member, variant, site):
    """{'writes': [...], 'refusal': None, 'outcome': 'fainted'|'benched'} or {'writes': [], 'refusal': reason}.
    Same function, same order, as lua/battle_force_authority.lua decide()."""
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
    return {'writes': active_writes(variant, site), 'refusal': None, 'outcome': 'fainted'}


def prepare(player, command, binding, death, member, host, *, variant):
    """Bind one pending owned death to one bounded step. Same obligation as gen1_held_faint.verify;
    the caller supplies the linked member's stable slot/species/DVs and the bounded owner's next step
    (``host['count']``, default 1, widens the authority to that many consecutive steps: instruction_authority window)."""
    body = command['body']
    if body.get('cmd') != 'force_faint' or 'death_id' not in body:
        raise JournalError('battle instruction authority serves force_faint only')
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
                                                host['frame'], host['step'], BINDING, {**member, 'variant': variant}, host.get('count', 1))


def issue(request, proof):
    if not isinstance(proof, generic.VerifiedInstructionAuthority) or proof.binding != BINDING:
        raise ValueError('verified battle instruction authority required')
    variant = proof.member['variant']
    return generic.issue(request, proof, sites(variant), ANCHORS[variant]['addresses'], hook_frame_offset=HOOK_FRAME_OFFSET)


def verify_evidence(authority, evidence, *, hook_frame_offset=None):
    """Return {'outcome': 'fainted'|'benched'|'refused'|'not_reached', 'site', 'reason'} or raise JournalError."""
    if authority.get('binding') != BINDING:
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
    member = authority['member']
    decision = decide(state, member, member['variant'], site)
    a = authority['addresses']
    slot = member['slot']
    before = {a['wBattleMonHP']: int(state['hp_hex'][0:2], 16), a['wBattleMonHP'] + 1: int(state['hp_hex'][2:4], 16),
              a['wPlayerSelectedMove']: state['selected_move'],
              a['wPartyMon1HP'] + PARTY_STRIDE * slot: int(state['party_hp_hex'][0:2], 16),
              a['wPartyMon1HP'] + PARTY_STRIDE * slot + 1: int(state['party_hp_hex'][2:4], 16),
              a['wPartyMon1Status'] + PARTY_STRIDE * slot: state['party_status']}
    outcome = generic.verify_footprint(evidence, decision, before)
    return {'outcome': outcome, 'site': site, 'reason': decision['refusal']}
