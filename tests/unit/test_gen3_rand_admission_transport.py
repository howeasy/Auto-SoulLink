"""RF-1 finding 3: the transport report is an ordered, exact ROM-table closure."""
from __future__ import annotations

import copy
import hashlib
import struct

import pytest

from server.adapters.gen3_frlge import Gen3Adapter
from tests.unit.test_gen3_rand_admission import randomized_payload
from tests.unit.test_gen3_rom_content_lua import symbols
from tests.unit.test_gen3_rom_ingest import _clean, _payload


def test_duplicate_region_is_refused_before_dictionary_overwrite():
    report = randomized_payload()
    report["tables"].insert(0, copy.deepcopy(report["tables"][0]))
    # The old parser silently deduplicated this and accepted the original hash.
    adapter = Gen3Adapter(rom_type="firered", artifact_kind="rand")
    with pytest.raises(ValueError, match="ascending|overlap|duplicate"):
        adapter.rom_content_fingerprint(report)
    with pytest.raises(ValueError, match="ascending|overlap|duplicate"):
        adapter.ingest_rom_content(report)


def test_unreferenced_region_is_refused_even_with_a_valid_transport_hash():
    report = randomized_payload()
    report["tables"].insert(0, {"addr": 0x08000100, "hex": "1234"})
    report["fingerprint"] = hashlib.sha1(
        b"".join(bytes.fromhex(row["hex"]) for row in report["tables"])).hexdigest()
    adapter = Gen3Adapter(rom_type="firered", artifact_kind="rand")
    with pytest.raises(ValueError, match="unreferenced|extra"):
        adapter.rom_content_fingerprint(report)
    with pytest.raises(ValueError, match="unreferenced|extra"):
        adapter.ingest_rom_content(report)


@pytest.mark.parametrize("fault", ("reversed", "overlap"))
def test_noncanonical_region_order_or_overlap_is_refused(fault):
    report = randomized_payload()
    if fault == "reversed":
        report["tables"].reverse()  # old sorted-map hash still matches
    else:
        report["tables"].insert(1, {"addr": report["tables"][0]["addr"] + 1, "hex": "00"})
    with pytest.raises(ValueError, match="ascending|overlap"):
        Gen3Adapter(rom_type="firered").rom_content_fingerprint(report)


def test_extra_byte_inside_a_region_is_not_hidden_by_coalescing():
    raw = _clean("firered")
    report = _payload(raw, "firered")
    first, second = report["tables"][:2]
    end = first["addr"] + len(first["hex"]) // 2
    assert end < second["addr"], "control needs a real gap between required ranges"
    first["hex"] += raw[end - 0x08000000:end - 0x08000000 + 1].hex()
    report["fingerprint"] = hashlib.sha1(
        b"".join(bytes.fromhex(row["hex"]) for row in report["tables"])).hexdigest()
    with pytest.raises(ValueError, match="unreferenced|extra"):
        Gen3Adapter(rom_type="firered").ingest_rom_content(report)


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
@pytest.mark.parametrize("shared", (False, True))
def test_repointed_and_shared_party_references_remain_valid(title, shared):
    raw = bytearray(_clean(title))
    head = symbols(title, len(raw))["gTrainers"]["address"] - 0x08000000
    brock, misty = head + 414 * 40, head + 415 * 40
    assert raw[brock] == raw[misty] == 1
    assert raw[brock + 32] == raw[misty + 32] == 2
    source = struct.unpack_from("<I", raw, brock + 36)[0] - 0x08000000
    moved = 0x08000000 + len(raw)
    raw.extend(raw[source:source + 32])
    struct.pack_into("<I", raw, brock + 36, moved)
    if shared:
        struct.pack_into("<I", raw, misty + 36, moved)
    adapter = Gen3Adapter(rom_type=title, artifact_kind="rand")
    report = _payload(bytes(raw), title)
    adapter.use_rom_encounters(adapter.ingest_rom_content(report))
    assert [mon["species"] for mon in adapter.trainer_party(414)] == ["Geodude", "Onix"]
    if shared:
        assert adapter.trainer_party(415) == adapter.trainer_party(414)
    assert adapter.rom_content_fingerprint(report)
