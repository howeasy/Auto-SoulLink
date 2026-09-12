"""Real immutable record references without restoring large images into snapshots."""
import copy

import pytest

from server.protocol import canonical_json
from server.protocol_journal import JournalError,ProtocolJournal
from server.retained_physical_record import expand,retain


def summary(value):
    return {'id':value['id'],'complete':value['complete']}


@pytest.mark.parametrize('fault',[None,'missing','digest','revision','namespace','summary'])
def test_retained_record_checks_body_revision_namespace_and_exact_summary(tmp_path,fault):
    value={'id':'a'*32,'complete':True,'image':'00'*100000}
    entry,record=retain('physical-test','b'*32,1,value,summary(value))
    original=copy.deepcopy(entry)
    journal=ProtocolJournal(tmp_path/'journal.sqlite3',contract_hash='c'*64)
    try:
        journal.bootstrap({})
        journal.commit('a','d'*32,{'event':'physical-complete'},expected_revision=0,state={'entry':entry},
                       commands={'a':[],'b':[]},result={'ack':'ACK'},records=[record])
        assert len(canonical_json(journal.snapshot().state))<1024
        if fault=='missing':
            journal._db.execute('DELETE FROM records WHERE namespace=? AND record_key=?',('physical-test','b'*32))
        elif fault in ('digest','revision','namespace'):
            name={'digest':'record_digest','revision':'record_revision','namespace':'namespace'}[fault]
            entry['retained'][name]={'digest':'f'*64,'revision':2,'namespace':'other'}[fault]
        elif fault=='summary':
            entry['complete']=False
        if fault is not None:
            with pytest.raises(JournalError):
                expand(journal,entry,namespace='physical-test',summarize=summary)
        else:
            assert expand(journal,entry,namespace='physical-test',summarize=summary)==value
            assert journal.snapshot().state=={'entry':original}
    finally:
        journal.close()
