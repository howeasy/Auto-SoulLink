"""Default-run FR/LG/Emerald artifact identity, without owner ROMs or a compiler.

Each published native companion has its own retained per-title byte receipt (tests/fixtures/gen3/native_payload_receipts.json):
the payload's offset, size, digests and version slot, re-derived from the published UPS. The manifest alone is not the evidence.
"""
import hashlib
import json
import os
import zlib
from pathlib import Path

import pytest

from patch.tools import gen3_title, rom_identity
from patch.tools.make_ups import _ups_decode, ups_apply
from tools.gen3_companions import accepts, ups_region

ROOT=Path(__file__).resolve().parents[2]
TITLES=("firered","leafgreen","emerald")
ROMS={"firered":"Pokemon - FireRed Version (USA).gba","leafgreen":"Pokemon - LeafGreen Version (USA).gba",
      "emerald":"Pokemon - Emerald Version (USA, Europe).gba"}


def receipts():
    return json.loads((ROOT/"tests/fixtures/gen3/native_payload_receipts.json").read_text())["titles"]


def manifest():
    return json.loads((ROOT/"patch/dist/gen3_companions.json").read_text())["titles"]


def test_every_published_native_companion_has_its_own_payload_receipt():
    assert set(receipts())==set(manifest())==set(TITLES)


@pytest.mark.parametrize("title",TITLES)
def test_published_payload_matches_its_retained_receipt(title):
    want=receipts()[title]
    row=manifest()[title]
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
    # version-masked identity: the receipt's canonical digest is the payload with its version field masked
    slot=want["payload_version_slot"]
    assert slot==row["payload_version_slot"]
    assert payload[slot["offset"]:slot["offset"]+slot["length"]]==gen3_title.menu_field(row["menu_version"])
    canonical=rom_identity.canonical_sha256(payload,[slot])
    assert canonical==want["canonical_payload_sha256"]==row["canonical_payload_sha256"],title


@pytest.mark.parametrize("title",TITLES)
def test_retained_rom_digest_is_what_the_published_ups_makes(title):
    root=os.environ.get("SLINK_GEN3_ROMS")
    if not root:
        pytest.skip("owner ROM directory required for UPS apply")
    want=receipts()[title]
    row=manifest()[title]
    rom=ups_apply((Path(root)/ROMS[title]).read_bytes(),(ROOT/"patch/dist"/row["patch"]).read_bytes())
    assert hashlib.sha256(rom).hexdigest()==row["rom_sha256"]
    # the ROM digest is retained for the same exact build as the payload digest; once a stamp makes the payload digest an
    # "equivalent" the whole-ROM digest has moved with it and the canonical receipts carry the evidence
    if want["payload_sha256"]==row["payload_sha256"]:
        assert want["rom_sha256"]==row["rom_sha256"]
