"""Default-run FR/LG artifact identity, without owner ROMs or a compiler."""
import hashlib
import json
import zlib
from pathlib import Path

from patch.tools import rom_identity
from patch.tools.make_ups import _ups_decode
from tools.gen3_companions import accepts, ups_region

ROOT=Path(__file__).resolve().parents[2]

def test_frlg_published_payloads_match_the_native_receipts():
    baseline=json.loads((ROOT/"tests/fixtures/gen3/native_payload_receipts.json").read_text())
    manifest=json.loads((ROOT/"patch/dist/gen3_companions.json").read_text())
    for title,want in baseline["titles"].items():
        row=manifest["titles"][title]
        patch=(ROOT/"patch/dist"/row["patch"]).read_bytes()
        assert patch[:4]==b"UPS1" and zlib.crc32(patch[:-4])==int.from_bytes(patch[-4:],"little")
        source_size,pos=_ups_decode(patch,4)
        target_size,pos=_ups_decode(patch,pos)
        assert source_size==target_size==0x1000000
        # The builder proves this entire injection region is FF in the exact
        # base ROM. Reconstruct ONLY that payload from the shipped XOR delta.
        offset,size=want["offset"],want["size"]
        payload=ups_region(patch,offset,size)
        # the shipped bytes are the manifest's published build; the receipt's retained digest is that exact build or an earlier
        # one the record lists as canonical-equal (a version stamp only)
        assert hashlib.sha256(payload).hexdigest()==row["payload_sha256"],title
        assert accepts(row,"payload_sha256",want["payload_sha256"]),title
        assert row["protected_spans"][0]=={"offset":offset,"size":size}
        # version-masked identity: the receipt's canonical digest is the payload with its fixed-width version field zeroed
        assert want["payload_version_slot"]==row["payload_version_slot"]
        canonical=rom_identity.canonical_sha256(payload,[want["payload_version_slot"]])
        assert canonical==want["canonical_payload_sha256"]==row["canonical_payload_sha256"],title
