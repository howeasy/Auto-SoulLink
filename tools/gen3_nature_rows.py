"""RR native Nature Changer facts and independent saved-record oracle."""
from pathlib import Path
import hashlib
import re
from tools.research.rr_special_lifecycle import census
ROOT = Path(__file__).resolve().parents[1]

def own_facts(run):
    rom = (ROOT / run._gen3_rom('a')).read_bytes()
    full = census(rom)
    from tools.research.rr_special_lifecycle import COMPANION_SHA1
    if full['rom_sha1'] != COMPANION_SHA1:
        raise RuntimeError('nature row requires the actual admitted companion ROM')
    facts = dict(full['nature'], rom_sha1=full['rom_sha1'])
    from tools.gba_map import Rom
    m = Rom(rom, 0x083526A8).map(5,4)
    path = m.bfs((11,2),(8,4))
    if path is None: raise RuntimeError('Nature Changer counter has no verified PC path')
    facts['path'] = path
    # The first native nature-list option branches to 0904C532 (actual bytecode).
    option_branch = rom[0x104C427:0x104C432]
    if option_branch.hex() != '210d800000060132c50409':
        raise RuntimeError('nature option zero branch changed')
    wrapper = next(w for w in facts['wrappers'] if w['script_call']==0x0904C532)
    facts['target_nature'] = wrapper['nature']
    # Own-ROM ListMenu creates the task at080CB904, whose final assignment loads
    # Task_ListMenuHandleInput from080CBA78. Keep this out of the shared title catalog.
    if (int.from_bytes(rom[0x15FD60+4*0x158:0x15FD64+4*0x158],'little')!=0x080CB7C5
            or rom[0xCB80C:0xCB810].hex()!='05b90c08'
            or rom[0xCBA4C:0xCBA50].hex()!='0a490160'
            or rom[0xCBA78:0xCBA7C].hex()!='29bb0c08'):
        raise RuntimeError('native Nature ListMenu task binding changed')
    facts['list_input_task']=0x080CBB28
    return facts

def nature_oracle(run, results):
    import e2e_duo as h
    from server.adapters import gen3_codec as c
    from tools.gen3_clause_rows import one, rows
    from tools.gen3_gift_egg_rows import tx_messages
    facts = own_facts(run)
    run._gen3_flush_boundary()
    text = results['a']
    baseline = one(text,'NATURE_BASELINE')
    if baseline.get('key')!=run._link_keys['a']:
        raise RuntimeError('nature operation baseline names wrong linked mon')
    operation = text[text.index('NATURE_BASELINE '):]
    pre = one(text,'NATURE_PREIMAGE')
    raw = bytes.fromhex(pre['raw_hex'])
    if (len(raw)!=100 or pre.get('slot')!=1 or pre.get('rom_sha1')!=facts['rom_sha1']
            or pre.get('raw_sha1')!=hashlib.sha1(raw).hexdigest()):
        raise RuntimeError('nature preimage slot/ROM/raw size mismatch')
    old = c.decode_party_mon(raw, rr=True)
    if old.get('checksum_ok') is False or old.get('is_bad_egg') or old.get('is_egg') or old.get('is_egg_flag'):
        raise RuntimeError('nature preimage is not a valid non-egg record')
    old_key=h.gen3_key(old)
    if old_key!=pre.get('key') or old_key!=run._link_keys['a']:
        raise RuntimeError('nature preimage does not name the linked slot')
    cancel=one(text,'NATURE_CANCEL')
    if cancel.get('key')!=old_key or cancel.get('unchanged') is not True:
        raise RuntimeError('native cancel did not preserve linked identity')
    party, boxes = run._gen3_saved('a')
    fixture_party, fixture_boxes = run._gen3_fixture_saved('a')
    if len(party)!=len(fixture_party) or len(party)<2 or boxes!=fixture_boxes:
        raise RuntimeError('nature changed party membership or boxes')
    now=party[1]; new_key=h.gen3_key(now)
    if now.get('checksum_ok') is False or now.get('is_bad_egg') or now.get('is_egg') or now.get('is_egg_flag'):
        raise RuntimeError('nature saved record is invalid or an egg')
    if now['personality']==old['personality'] or now['personality']%25!=facts['target_nature']:
        raise RuntimeError('saved PID did not acquire selected nature')
    # RR codec decodes actual fixed substructures, not guessed nickname/party-tail offsets.
    mutable={'personality','checksum','attack','defense','speed','sp_attack','sp_defense'}
    changed=h.gen3_record_diff(old,now,rr=True,mutable=mutable)
    if changed: raise RuntimeError(f'nature changed owned attributes: {changed}')
    for i, mon in enumerate(party):
        if i!=1 and h.gen3_record_diff(fixture_party[i],mon,rr=True,
                                      mutable=h.GEN3_RECORD_MUTABLE | h.GEN3_ACTIVITY_MUTABLE):
            raise RuntimeError('nature changed unrelated A party member')
    if run._gen3_saved('b')!=run._gen3_fixture_saved('b'):
        raise RuntimeError('nature changed partner saved records')
    changes=tx_messages(text,'key_change')
    expected=dict(old_key=old_key,new_key=new_key,reason='nature_change')
    if not changes or any(any(change.get(k)!=v for k,v in expected.items()) for change in changes):
        raise RuntimeError('nature requires one unique production identity migration')
    semantic=[{k:v for k,v in change.items() if k!='seq'} for change in changes]
    if any(change!=semantic[0] for change in semantic[1:]):
        raise RuntimeError('nature retry changed semantic payload')
    if any(tx_messages(operation,event) for event in ('capture','party_to_box','box_to_party','faint','no_catch')):
        raise RuntimeError('nature emitted gameplay churn')
    signals=rows(text,'NATURE_SIGNAL')
    if [s.get('kind') for s in signals]!=['nature_change_begin','nature_change'] or any(
            (s.get('point') or {}).get('R4')!=facts['party_base']+100 for s in signals):
        raise RuntimeError('nature registered points missing or wrong mon pointer')
    ack=one(text,'NATURE_ACK') if 'NATURE_ACK ' in text else None
    if ack is None or ack.get('migrated') is not True or any(ack.get(k)!=expected[k] for k in ('old_key','new_key')):
        raise RuntimeError('nature migration ACK missing or mismatched')
    chain=['NATURE_BASELINE ', 'NATURE_CANCEL ', 'NATURE_PREIMAGE ', 'NATURE_SIGNAL ', 'TX key_change ',
           'NATURE_ACK ', 'NATURE_CHANGED ', 'SAVE_WITNESS ']
    problems=h.gen3_receipt_problems('a',text,required=chain,
                                    ordered=list(zip(chain,chain[1:])))
    problems+=h.gen3_receipt_problems('b',results['b'],required=['SAVE_WITNESS '])
    for inst in ('a','b'):
        saves=re.findall(r'^SAVE_WITNESS nature counter=(\d+)->(\d+)$',results[inst],re.M)
        if len(saves)!=1 or not 0<=int(saves[0][0])<int(saves[0][1])<=0xFFFFFFFF:
            problems.append(f'{inst}: missing or nonadvancing native save witness')
    links=run._links_json()
    if len(links)!=1 or links[0].get('status')!='alive' or any(
            (links[0].get(inst) or {}).get('key')!=key for inst,key in
            (('a',new_key),('b',run._link_keys['b']))):
        raise RuntimeError('nature did not preserve the single alive link ownership')
    if problems: raise RuntimeError('; '.join(problems))
    run._pydec_note(f'nature: native points, ACK, alive migrated link and independent saved PID {old_key}->{new_key}')

def orchestrate(run):
    facts=own_facts(run)
    run._gen3_prelude(link_slot=1)
    run._gen3_area_control()  # server-only isolation of incidental Route1 RUNs
    lines=run._gen3_linked_lines()
    for inst in ('a','b'):
        lines[inst].append('NATURE '+__import__('json').dumps(facts))
    run.go(lines)
    run._gen3_mark('a',r'^NATURE_CHANGED \S+$','native Nature Changer and migration ACK')
    for inst in ('a','b'): run._append_reconnect_marker(inst,'SAVE')
