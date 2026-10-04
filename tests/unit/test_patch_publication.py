"""Published vanilla companions apply through the shipped UPS and registry."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from patch.tools.make_ups import ups_apply
from server import patcher

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("title,file,cap",[
    ("firered","Pokemon - FireRed Version (USA).gba",23),
    ("leafgreen","Pokemon - LeafGreen Version (USA).gba",23),
    ("emerald","Pokemon - Emerald Version (USA, Europe).gba",87),
])
def test_published_companion_is_crc_bound_and_admitted(title,file,cap):
    manifest=json.loads((ROOT/"patch/dist/gen3_companions.json").read_text())
    row=manifest["titles"][title]
    assert row["abi"]==2 and row["capabilities"]==cap and row["production"] is True
    patch=(ROOT/"patch/dist"/row["patch"]).read_bytes()
    assert hashlib.sha256(patch).hexdigest()==row["ups_sha256"]
    assert patcher.TARGETS[title]["patch"]==row["patch"]
    roms=os.environ.get("SLINK_GEN3_ROMS")
    if not roms:pytest.skip("owner ROM directory required for UPS apply")
    clean=(Path(roms)/file).read_bytes()
    patched=ups_apply(clean,patch)
    assert hashlib.sha1(clean).hexdigest()==row["base_sha1"]
    assert hashlib.sha1(patched).hexdigest()==row["rom_sha1"]
    assert hashlib.md5(patched).hexdigest()==patcher.TARGETS[title]["patched_md5"]
    # version-masked identity: the fixed-width field holds the published version; the canonical sha1 is the ROM without it
    from patch.tools import gen3_title, rom_identity
    from tools.gen3_companions import canonical_problems
    slot = row["version_slot"]
    field_end = slot["offset"] + slot["length"]
    assert patched[slot["offset"]:field_end] == gen3_title.menu_field(row["menu_version"])
    assert canonical_problems(row, rom=patched) == []
    stamped = bytearray(patched)
    stamped[slot["offset"]:field_end] = gen3_title.menu_field("v10.20.30")   # any version other than the published one
    assert hashlib.sha1(stamped).hexdigest() != row["rom_sha1"]                            # a stamp moves the exact hash ...
    assert rom_identity.canonical_sha1(bytes(stamped), [slot]) == row["canonical_sha1"]    # ... and nothing the canonical one sees
    elsewhere = bytearray(patched)
    elsewhere[0x1000] ^= 1
    assert rom_identity.canonical_sha1(bytes(elsewhere),[slot])!=row["canonical_sha1"]     # a change outside the field is seen
    bad=bytearray(clean);bad[0x100]^=1
    with pytest.raises((ValueError,AssertionError)):
        ups_apply(bytes(bad),patch)
    from tools.gen3_companions import overlay_randomized
    randomized=bytearray(clean);randomized[0xa0]^=1
    composed=overlay_randomized(title,clean,bytes(randomized))
    assert composed[0xa0]==randomized[0xa0]
    assert composed[:0xa0]==patched[:0xa0] and composed[0xa1:]==patched[0xa1:]
    span=row["protected_spans"][0]
    randomized[span["offset"]]^=1
    with pytest.raises(ValueError,match="overlaps"):
        overlay_randomized(title,clean,bytes(randomized))
