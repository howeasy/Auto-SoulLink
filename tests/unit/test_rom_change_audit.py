import pytest
from server.rom_change_audit import RomAuditError,RomChangeAudit


def test_all_changed_bytes_need_validated_claims():
    audit=RomChangeAudit(b"abcdef",b"abcXef")
    with pytest.raises(RomAuditError,match="unapproved"):audit.finish()
    audit.value(3,{ord("X"),ord("Y")},"item")
    assert audit.finish()["changed_by_domain"]=={"item":1}


def test_claim_cannot_accept_a_wrong_value_or_another_domains_overlap():
    audit=RomChangeAudit(b"000",b"123")
    with pytest.raises(RomAuditError,match="serialized"):audit.expect(0,b"125","table")
    with pytest.raises(RomAuditError,match="invalid value"):audit.value(0,{9},"item")
    audit.expect(0,b"123","table")
    audit.expect(0,b"123","table")
    with pytest.raises(RomAuditError,match="overlaps"):audit.expect(1,b"2","code")


@pytest.mark.parametrize("offset,size",[(-1,1),(0,-1),(2,2),(4,0),(True,1)])
def test_bounds_refuse_negative_truncated_and_noninteger_reads(offset,size):
    with pytest.raises(RomAuditError):RomChangeAudit(b"abc",b"abc").read(offset,size)


def test_mutable_and_resized_inputs_are_refused():
    for original,candidate in ((b"a",b"ab"),(bytearray(b"a"),b"a"),(b"",b"")):
        with pytest.raises(RomAuditError):RomChangeAudit(original,candidate)
