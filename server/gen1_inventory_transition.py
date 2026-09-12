"""RBY checkpoint differences, not acquisition or physical-command authority."""
from server.gen1_initial_observation import inventory
from server.keyed_inventory import compare
from server.protocol_journal import JournalError


def _transition(before, after, save):
    if before.get('variant') != after.get('variant'):
        raise JournalError('inventory transition changed cartridge variant')
    old, new = inventory(before, save), inventory(after, save)
    delta = compare(old['members'], new['members'], limit=246)
    # A disappearing authoritative storage bank cannot be treated as releases.
    if old['boxes_initialized'] and not new['boxes_initialized']:
        raise JournalError('initialized storage disappeared; reconciliation required')
    movements, faints, changed = [], [], []
    for pair in delta['matched']:
        pre, post = pair['before'], pair['after']
        location = lambda row: {k: row[k] for k in ('location', 'box', 'slot')}
        if location(pre) != location(post):
            movements.append({'key': pair['key'], 'before': location(pre), 'after': location(post)})
        if pre['location'] == post['location'] == 'party':
            a, b = bytes.fromhex(pre['blob_hex']), bytes.fromhex(post['blob_hex'])
            if int.from_bytes(a[1:3], 'big') > 0 and b[1:3] == b'\0\0':
                faints.append(pair['key'])
        if pre['evidence_digest'] != post['evidence_digest']:
            changed.append(pair['key'])
    return {'added': delta['added'], 'removed': delta['removed'], 'movements': movements,
            'party_hp_zero': faints, 'changed': changed,
            'before_digest': old['source_digest'], 'after_digest': new['source_digest']}


def transition(before, after, save, *, attribution=None):
    """Separate witnessed authorized effects from every still-unattributed gap."""
    if attribution is None:
        return _transition(before, after, save)
    from server.gen1_authorized_inventory import replay
    steps, baseline = replay(before, attribution)
    if not steps:
        return _transition(before, after, save)
    gaps = [_transition(start, pre, save) for start, pre, _post, _ref in steps]
    gaps.append(_transition(baseline, after, save))
    result = {key: [item for gap in gaps for item in gap[key]] for key in (
        'added', 'removed', 'movements', 'party_hp_zero', 'changed')}
    result.update(before_digest=gaps[0]['before_digest'], after_digest=gaps[-1]['after_digest'],
                  authorized_writes=[ref for _start, _pre, _post, ref in steps],
                  unattributed_segments=gaps)
    return result
