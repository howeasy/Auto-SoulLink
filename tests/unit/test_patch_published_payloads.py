"""Default-run FR/LG artifact identity, without owner ROMs or a compiler."""
import hashlib
import json
import zlib
from pathlib import Path
from patch.tools.make_ups import _ups_decode

ROOT=Path(__file__).resolve().parents[2]

def test_frlg_published_payloads_match_the_native_receipts():
    baseline=json.loads((ROOT/"tests/fixtures/gen3/native_payload_receipts.json").read_text())
    manifest=json.loads((ROOT/"patch/dist/gen3_companions.json").read_text())
    for title,want in baseline["titles"].items():
        row=manifest["titles"][title]
        patch=(ROOT/"patch/dist"/row["patch"]).read_bytes()
        assert patch[:4]==b"UPS1" and zlib.crc32(patch[:-4])==int.from_bytes(patch[-4:],"little")
        source_size,pos=_ups_decode(patch,4);target_size,pos=_ups_decode(patch,pos)
        assert source_size==target_size==0x1000000
        # The builder proves this entire injection region is FF in the exact
        # base ROM. Reconstruct ONLY that payload from the shipped XOR delta.
        offset,size=want["offset"],want["size"]
        payload=bytearray(b"\xff"*size)
        address=0
        while pos<len(patch)-12:
            delta,pos=_ups_decode(patch,pos);address+=delta
            while pos<len(patch)-12:
                value=patch[pos];pos+=1
                if offset<=address<offset+size:payload[address-offset]^=value
                address+=1
                if value==0:break
        assert hashlib.sha256(payload).hexdigest()==want["payload_sha256"],title
        assert row["payload_sha256"]==want["payload_sha256"]
        assert row["protected_spans"][0]=={"offset":offset,"size":size}
