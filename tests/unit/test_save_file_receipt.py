import hashlib
from pathlib import Path

import pytest

from server.protocol_journal import JournalError
from server.save_file_receipt import verify_file_image


@pytest.fixture
def receipt():
    image=bytes(range(256))*128
    proof={'schema':'slink-saveram-file-v1','path':'Z:/partner/save.SaveRAM','byte_length':len(image),
           'sha256':hashlib.sha256(image).hexdigest(),'host_profile':'qualified-host','frame':123,
           'flushed':True,'readback':True}
    return image,proof


def verify(image,proof):
    return verify_file_image(proof,image,host_profile='qualified-host',frame_from=120,frame_to=125)


def test_remote_image_verification_never_opens_the_path_and_returns_a_detached_receipt(receipt,monkeypatch):
    image,proof=receipt
    def forbidden(*args,**kwargs):raise AssertionError('remote path was opened')
    monkeypatch.setattr(Path,'open',forbidden)
    result=verify(image,proof);result['path']='different'
    assert proof['path']=='Z:/partner/save.SaveRAM'


@pytest.mark.parametrize('field,value',[('schema','unknown'),('sha256','f'*64),('byte_length',True),
    ('host_profile','different'),('frame',True),('frame',119),('frame',126),('flushed',False),('readback',False),
    ('path',''),('path','bad\npath'),('extra','unexpected')])
def test_unowned_incomplete_or_mismatched_file_proof_is_refused(receipt,field,value):
    image,proof=receipt;proof[field]=value
    with pytest.raises(JournalError):verify(image,proof)
