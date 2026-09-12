"""Read-only, generation-neutral exhaustive ROM change accounting.

Generation scanners authorize concrete bytes after checking their semantics.
There is no unchecked-region or 'ignore these changes' operation.
"""
import hashlib


class RomAuditError(ValueError):
    pass


class RomChangeAudit:
    def __init__(self, original, candidate):
        if not isinstance(original,bytes) or not isinstance(candidate,bytes) or len(original)!=len(candidate) or not original:
            raise RomAuditError("equal nonempty immutable ROM images required")
        self.original,self.candidate=original,candidate
        self.claims={}

    def read(self, offset, size, *, original=False):
        if type(offset) is not int or type(size) is not int or offset<0 or size<0 or offset+size>len(self.candidate):
            raise RomAuditError("ROM read is out of bounds")
        return (self.original if original else self.candidate)[offset:offset+size]

    def expect(self, offset, expected, label):
        if not isinstance(expected,bytes) or not isinstance(label,str) or not label:
            raise RomAuditError("typed expected bytes and label required")
        if self.read(offset,len(expected))!=expected:
            raise RomAuditError(f"{label}: serialized bytes differ at {offset:#x}")
        for index,value in enumerate(expected):
            address=offset+index
            if address in self.claims and self.claims[address]!=(value,label):
                raise RomAuditError(f"{label}: overlaps a different domain at {address:#x}")
            self.claims[address]=(value,label)

    def value(self, offset, allowed, label):
        value=self.read(offset,1)[0]
        if value not in allowed:
            raise RomAuditError(f"{label}: invalid value {value} at {offset:#x}")
        self.expect(offset,bytes([value]),label)
        return value

    def finish(self):
        counts={};unexplained=[]
        for offset,(before,after) in enumerate(zip(self.original,self.candidate)):
            if before==after:continue
            claim=self.claims.get(offset)
            if claim is None:
                if len(unexplained)<12:unexplained.append(hex(offset))
            else:counts[claim[1]]=counts.get(claim[1],0)+1
        if unexplained:
            raise RomAuditError("unapproved ROM writes: "+", ".join(unexplained))
        return {"schema":"slink-rom-change-audit-v1","bytes_changed":sum(counts.values()),
            "changed_by_domain":dict(sorted(counts.items())),"size":len(self.candidate),
            "source_sha256":hashlib.sha256(self.original).hexdigest(),
            "candidate_sha256":hashlib.sha256(self.candidate).hexdigest(),
            "candidate_sha1":hashlib.sha1(self.candidate).hexdigest()}
