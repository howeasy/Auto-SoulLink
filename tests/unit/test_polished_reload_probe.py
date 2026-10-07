"""Read-only reload oracle evidence, entirely synthetic and never a live trade receipt.

The battery builders use the existing byte codec and native save geometry. Live
traces model a cold accepted load followed by three dispatch callbacks; no driver,
BizHawk process, savestate, ROM build or Lua chunk is executed here. The sole Lua
check compiles with Lua 5.5 without calling the resulting function. These tests
were authored without running Python; integration/validation belongs to the parent.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "reload_probe", ROOT / "tools/polished_live/reload_probe.py"
)
P = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = P
SPEC.loader.exec_module(P)
ds, pc = P.ds, P.pc

SCHEMA = "polished-reload-expected-v1"
RTC = bytes.fromhex("000000006ac2a3950000000100001228fe0000000100")
SAVED_OFF = 0x2F  # wSavedAtLeastOnce - wPlayerID, pinned native PlayerData
GUARDS = {
    "script_mode": 0, "battle_mode": 0, "link_mode": 0, "paused": 0,
    "in_menu": 0, "vblank": 0, "map_status": 2, "step_flags": 0,
    "map_event_status": 0,
}
SITE_NAMES = (
    "dispatch", "load_begin", "primary_fail", "backup_begin", "backup_fail",
    "primary_loaded", "backup_loaded", "corrupt",
)


def party_row(slot=0, *, species=19, form=2, dvs="123456", ot_id=0xD1C3,
              extra=b"\x04\x05\x06", name="Bbbbbbb", nickname="Received"):
    raw = bytearray(48)
    raw[0], raw[1] = species & 0xFF, 5
    raw[2:6] = bytes([1, 2, 3, 4])
    raw[6:8] = ot_id.to_bytes(2, "big")
    raw[17:20] = bytes.fromhex(dvs)
    raw[20] = 3
    raw[21] = form | (0x20 if species & 0x100 else 0)
    raw[22:26] = bytes([10, 10, 10, 10])
    raw[31] = 12
    raw[34:38] = bytes.fromhex("001e0028")
    for at in range(38, 48, 2):
        raw[at:at + 2] = b"\x00\x14"
    ot = pc.encode_text(name, 8) + extra
    nick = pc.encode_text(nickname, 11)
    return {
        "slot": slot, "record_hex": raw.hex(), "ot_hex": ot.hex(),
        "nickname_hex": nick.hex(), "species_id": species, "form_byte": raw[21],
        "personality_byte": raw[20], "level": 12, "hp": 30,
        "ot_id_hex": f"{ot_id:04x}", "held_item": 5,
    }


def row_key(row):
    return pc.key(pc.decode_party_mon(
        bytes.fromhex(row["record_hex"]), ot=bytes.fromhex(row["ot_hex"]),
        nickname=bytes.fromhex(row["nickname_hex"]),
    ))


def given_row():
    return party_row(species=169, form=0, dvs="EFFFFF", ot_id=0xD1C2,
                     name="Aaaaaaa", nickname="Given")


def manifest(rows=None, **optional):
    rows = [party_row()] if rows is None else rows
    result = {
        "schema": SCHEMA, "party_count": len(rows),
        "party": [{"slot": r["slot"], "key": row_key(r), "ot_hex": r["ot_hex"]}
                  for r in rows],
        "absent_key": row_key(given_row()),
    }
    result.update(optional)
    return result


def snapshot(rows=None):
    rows = [party_row()] if rows is None else rows
    return {
        "kind": "snapshot", "ord": 7, "frame": 12,
        "player_id_hex": "D1C3", "player_name_hex": pc.encode_text("Bbbbbbb", 8).hex(),
        "party_count": len(rows), "party": copy.deepcopy(rows),
        "storage": {
            "main": {"metadata_hex": "00" * 660, "records": []},
            "backup": {"metadata_hex": "00" * 660, "records": []},
            "used_flags": ["00" * 26, "00" * 26],
        },
        "saved_at_least_once": 1, "save_version_hex": "000a", "save_phase": 0,
        "overlay_version_hex": "ab" * 20,
        "engine_integrity": {
            "load_started": True, "primary": "valid", "backup": "unobserved",
            "selected": "main", "corrupt": False,
        },
        "stable_frame_count": 3,
        "checkpoint": {"guards": copy.deepcopy(GUARDS), "svbk": 1, "stack_hex": "00" * 28},
    }


def savemon(row):
    decoded = pc.decode_party_mon(
        bytes.fromhex(row["record_hex"]), ot=bytes.fromhex(row["ot_hex"]),
        nickname=bytes.fromhex(row["nickname_hex"]),
    )
    return pc.encode_savemon(decoded)


def box_add(snap, row, *, copies=("main", "backup"), box=19, slot=19, db_bank=2, entry=207):
    for name in copies:
        image = snap["storage"][name]
        metadata = bytearray.fromhex(image["metadata_hex"])
        base = 33 * box
        metadata[base + slot] = entry
        if db_bank == 2:
            metadata[base + 20 + slot // 8] |= 1 << (slot % 8)
        image["metadata_hex"] = metadata.hex()
        image["records"].append({
            "box": box, "slot": slot, "db_bank": db_bank, "entry": entry,
            "record_hex": savemon(row).hex(),
        })
    flags = bytearray.fromhex(snap["storage"]["used_flags"][db_bank - 1])
    flags[(entry - 1) // 8] |= 1 << ((entry - 1) % 8)
    snap["storage"]["used_flags"][db_bank - 1] = flags.hex()


def entry_at(bank, entry):
    if entry <= 167:
        return {1: 0x4000, 2: 0x6000}[bank] + 49 * (entry - 1)
    if entry <= 195:
        return {1: 0, 2: 0x0BF1}[bank] + 49 * (entry - 168)
    return {1: 0x360C, 2: 0x3858}[bank] + 49 * (entry - 196)


def battery(rows=None, *, rtc=True, boxes=None):
    rows = [party_row()] if rows is None else rows
    buf = bytearray(32768)
    buf[ds.VERSION_AT:ds.VERSION_AT + 2] = ds.SAVE_VERSION
    buf[ds.PHASE_AT] = 0
    for c in ds.ALL_COPIES:
        buf[c.low_marker_at], buf[c.high_marker_at] = ds.LOW_MARKER, ds.HIGH_MARKER
        buf[c.at(ds.ID_OFF):c.at(ds.ID_OFF) + 2] = bytes.fromhex("d1c3")
        buf[c.at(ds.NAME_OFF):c.at(ds.NAME_OFF) + 8] = pc.encode_text("Bbbbbbb", 8)
        buf[c.at(SAVED_OFF)] = 1
        buf[c.at(ds.COUNT_OFF)] = len(rows)
        for row in rows:
            slot = row["slot"]
            for at, field in ((c.mon_at(slot), "record_hex"), (c.ot_at(slot), "ot_hex"),
                              (c.nick_at(slot), "nickname_hex")):
                raw = bytes.fromhex(row[field])
                buf[at:at + len(raw)] = raw
    if boxes is not None:
        for c in ds.ALL_COPIES:
            image = boxes["storage"][c.name]
            metadata = bytes.fromhex(image["metadata_hex"])
            buf[c.newbox_at:c.newbox_at + len(metadata)] = metadata
            for row in image["records"]:
                at = entry_at(row["db_bank"], row["entry"])
                buf[at:at + 49] = bytes.fromhex(row["record_hex"])
    ds._reseal(buf)
    return bytes(buf) + (RTC if rtc else b"")


def result(actual, expected):
    verdict, reasons = actual
    assert verdict == expected, reasons
    if verdict != "PASS":
        assert reasons, f"{verdict} must explain the failed evidence"


@pytest.mark.parametrize("rtc", [False, True], ids=["cart-32768", "rtc-32790"])
def test_offline_accepts_both_exact_sizes_without_mutating_input(rtc):
    source = bytearray(battery(rtc=rtc))
    before = bytes(source)
    evidence = P.extract_save(source)
    result(P.evaluate_offline(source, manifest()), "PASS")
    assert bytes(source) == before
    assert evidence["fixture_size"] == len(before)
    assert evidence["fixture_sha256"] == hashlib.sha256(before).hexdigest()
    for c in ds.ALL_COPIES:
        assert evidence["integrity"][c.name] == {
            "stored": ds.region_sum(before, c), "computed": ds.region_sum(before, c),
            "valid": True, "markers_valid": True,
        }
        assert evidence["copies"][c.name]["overlay_version_hex"] is None
        assert evidence["copies"][c.name]["party"][0]["record_hex"] == party_row()["record_hex"]
    assert before[32768:] == (RTC if rtc else b"")


@pytest.mark.parametrize("size", [0, 32767, 32769, 32789, 32791],
                         ids=["empty", "short-cart", "cart-plus-one", "short-rtc", "long-rtc"])
def test_offline_wrong_size_is_a_refusal(size):
    result(P.evaluate_offline(bytes(size), manifest()), "FAIL")
    with pytest.raises(ValueError):
        P.extract_save(bytes(size))


@pytest.mark.parametrize("copy_name", ["main", "backup"], ids=["main", "backup"])
@pytest.mark.parametrize("damage", ["checksum", "low-marker", "high-marker"],
                         ids=["checksum", "low-marker", "high-marker"])
def test_offline_checks_both_native_integrity_regions(copy_name, damage):
    source = bytearray(battery())
    c = ds.MAIN if copy_name == "main" else ds.BACKUP
    at = {"checksum": c.checksum_at, "low-marker": c.low_marker_at,
          "high-marker": c.high_marker_at}[damage]
    source[at] ^= 1
    result(P.evaluate_offline(source, manifest()), "FAIL")


@pytest.mark.parametrize("damage", ["version", "phase", "saved-main", "saved-backup"],
                         ids=["native-version", "save-in-progress", "main-never-saved", "backup-never-saved"])
def test_offline_requires_complete_native_save(damage):
    source = bytearray(battery())
    if damage == "version":
        source[ds.VERSION_AT] ^= 1
    elif damage == "phase":
        source[ds.PHASE_AT] = 1
    else:
        c = ds.MAIN if damage == "saved-main" else ds.BACKUP
        source[c.at(SAVED_OFF)] = 0
        ds._reseal(source)
    result(P.evaluate_offline(source, manifest()), "FAIL" if damage == "version" else "INCOMPLETE")


def test_offline_cannot_invent_rom_only_overlay_version():
    result(P.evaluate_offline(battery(), manifest(overlay_version_hex="ab" * 20)), "INCOMPLETE")
    result(P.compare_manifest(snapshot(), manifest(overlay_version_hex="ab" * 20)), "PASS")
    result(P.compare_manifest(snapshot(), manifest(overlay_version_hex="cd" * 20)), "FAIL")


def test_compare_does_not_modify_mutable_snapshot_or_manifest():
    snap, expected = snapshot(), manifest()
    snap["party"][0]["nickname_hex"] = pc.encode_text("Rename", 11).hex()
    originals = copy.deepcopy((snap, expected))
    result(P.compare_manifest(snap, expected), "PASS")
    assert (snap, expected) == originals


@pytest.mark.parametrize("case,verdict", [
    ("baseline", "PASS"), ("given-party", "STILL_PRESENT_GIVEN"),
    ("count", "PARTY_COUNT_MISMATCH"), ("received", "MISSING_RECEIVED"),
    ("ot-id", "OT_MISMATCH"), ("ot-name", "OT_MISMATCH"),
    ("ot-extra", "OT_MISMATCH"), ("not-saved", "INCOMPLETE"),
    ("bad-record", "FAIL"), ("box-count", "CENSUS_MISMATCH"),
], ids=["pass", "given-party", "party-count", "missing-received", "ot-id", "ot-name",
        "ot-extra", "never-saved", "malformed-record", "box-count"])
def test_compare_named_verdicts(case, verdict):
    snap, expected = snapshot(), manifest()
    if case == "given-party":
        snap["party"][0] = given_row()
    elif case == "count":
        snap = snapshot([party_row(), party_row(1, dvs="654321")])
    elif case == "received":
        snap["party"][0] = party_row(dvs="654321")
    elif case == "ot-id":
        snap["party"][0] = party_row(ot_id=0xD1C2)
    elif case in {"ot-name", "ot-extra"}:
        snap["party"][0] = party_row(name="Aaaaaaa") if case == "ot-name" else party_row(extra=b"\x04\x05\x07")
    elif case == "not-saved":
        snap["saved_at_least_once"] = 0
    elif case == "bad-record":
        snap["party"][0]["record_hex"] = "00"
    elif case == "box-count":
        expected["box_counts"] = [1] + [0] * 19
    result(P.compare_manifest(snap, expected), verdict)


@pytest.mark.parametrize("copy_name", ["main", "backup"], ids=["main", "backup"])
@pytest.mark.parametrize("case,verdict", [
    ("count", "PARTY_COUNT_MISMATCH"), ("key", "MISSING_RECEIVED"),
    ("ot-id", "OT_MISMATCH"), ("ot-name", "OT_MISMATCH"), ("ot-extra", "OT_MISMATCH"),
], ids=["count", "key", "ot-id", "ot-name", "ot-extra"])
def test_offline_checks_each_copy_against_expected_not_only_main(copy_name, case, verdict):
    source = bytearray(battery())
    c = ds.MAIN if copy_name == "main" else ds.BACKUP
    if case == "count":
        source[c.at(ds.COUNT_OFF)] = 2
        row = party_row(1, dvs="654321")
        for at, field in ((c.mon_at(1), "record_hex"), (c.ot_at(1), "ot_hex"),
                          (c.nick_at(1), "nickname_hex")):
            value = bytes.fromhex(row[field])
            source[at:at + len(value)] = value
    elif case == "key":
        source[c.mon_at(0) + 17] ^= 1
    elif case == "ot-id":
        source[c.mon_at(0) + 7] ^= 1
    elif case == "ot-name":
        source[c.ot_at(0)] = pc.encode_text("A", 1)[0]
    else:
        source[c.ot_at(0) + 10] ^= 1
    ds._reseal(source)
    result(P.evaluate_offline(source, manifest()), verdict)


@pytest.mark.parametrize("species,form,expected_species,expected_traits", [
    (0x137, 0, "137", "00"), (19, 2, "013", "02"), (201, 2, "0C9", "00"),
], ids=["ninth-species-bit", "regional-form", "cosmetic-form"])
def test_identity_uses_existing_codec_semantics(species, form, expected_species, expected_traits):
    row = party_row(species=species, form=form)
    expected = manifest([row])
    assert expected["party"][0]["key"].split(":")[2:] == [expected_species, expected_traits]
    result(P.compare_manifest(snapshot([row]), expected), "PASS")
    result(P.evaluate_offline(battery([row]), expected), "PASS")


def test_cosmetic_change_is_same_identity_but_regional_change_is_not():
    result(P.compare_manifest(snapshot([party_row(species=201, form=3)]),
                              manifest([party_row(species=201, form=2)])), "PASS")
    result(P.compare_manifest(snapshot([party_row(species=19, form=0)]),
                              manifest([party_row(species=19, form=2)])), "MISSING_RECEIVED")


@pytest.mark.parametrize("claimed", ["species_id", "form_byte", "personality_byte", "level", "hp",
                                     "ot_id_hex", "held_item"],
                         ids=["species", "form", "personality", "level", "hp", "ot-id", "held-item"])
def test_decoded_claims_cannot_override_raw_party_bytes(claimed):
    snap = snapshot()
    snap["party"][0][claimed] = "FFFF" if claimed == "ot_id_hex" else snap["party"][0][claimed] + 1
    result(P.compare_manifest(snap, manifest()), "FAIL")


@pytest.mark.parametrize("copies", [("main", "backup"), ("main",), ("backup",)],
                         ids=["both-pointer-copies", "main-only", "backup-only"])
def test_given_hidden_in_last_box_is_not_absent(copies):
    snap = snapshot()
    box_add(snap, given_row(), copies=copies)
    # Disagreeing pointer copies outrank given-present, but never become PASS.
    result(P.compare_manifest(snap, manifest()),
           "STILL_PRESENT_GIVEN" if len(copies) == 2 else "CENSUS_MISMATCH")
    result(P.evaluate_offline(battery(boxes=snap), manifest()),
           "STILL_PRESENT_GIVEN" if len(copies) == 2 else "CENSUS_MISMATCH")


@pytest.mark.parametrize("bank,entry", [(1, 1), (1, 167), (1, 168), (1, 195), (1, 196), (1, 207),
                                        (2, 1), (2, 167), (2, 168), (2, 195), (2, 196), (2, 207)],
                         ids=["db1-first-a", "db1-last-a", "db1-first-b", "db1-last-b", "db1-first-c",
                              "db1-last-c", "db2-first-a", "db2-last-a", "db2-first-b", "db2-last-b",
                              "db2-first-c", "db2-last-c"])
def test_box_census_covers_each_native_database_section_boundary(bank, entry):
    snap = snapshot()
    box_add(snap, given_row(), db_bank=bank, entry=entry)
    result(P.compare_manifest(snap, manifest()), "STILL_PRESENT_GIVEN")
    result(P.evaluate_offline(battery(boxes=snap), manifest()), "STILL_PRESENT_GIVEN")


@pytest.mark.parametrize("damage", ["alias", "unallocated", "bad-seal", "missing-record", "extra-record",
                                   "wrong-record-pointer", "copy-reference", "copy-count"],
                         ids=["alias-pointer", "dangling-allocation", "bad-savemon-checksum", "missing-record",
                              "extra-record", "record-pointer", "split-reference", "split-count"])
def test_census_mismatch_never_proves_absence(damage):
    snap = snapshot()
    box_add(snap, party_row(dvs="654321"))
    main = snap["storage"]["main"]
    if damage == "unallocated":
        snap["storage"]["used_flags"] = ["00" * 26, "00" * 26]
    elif damage == "bad-seal":
        for name in ("main", "backup"):
            raw = bytearray.fromhex(snap["storage"][name]["records"][0]["record_hex"])
            raw[1] ^= 1
            snap["storage"][name]["records"][0]["record_hex"] = raw.hex()
    elif damage == "missing-record":
        main["records"] = []
    elif damage == "extra-record":
        main["records"].append({**main["records"][0], "slot": 18})
    elif damage == "wrong-record-pointer":
        main["records"][0]["entry"] = 206
    elif damage == "copy-reference":
        metadata = bytearray.fromhex(main["metadata_hex"])
        metadata[19 * 33 + 19] = 206
        main["metadata_hex"] = metadata.hex()
    elif damage == "copy-count":
        snap["storage"]["backup"] = {"metadata_hex": "00" * 660, "records": []}
    else:
        for name in ("main", "backup"):
            image = snap["storage"][name]
            metadata = bytearray.fromhex(image["metadata_hex"])
            metadata[19 * 33 + 18] = 207
            metadata[19 * 33 + 22] |= 1 << 2
            image["metadata_hex"] = metadata.hex()
            image["records"].append({**image["records"][0], "slot": 18})
    result(P.compare_manifest(snap, manifest()), "CENSUS_MISMATCH")


def test_unreferenced_savemon_garbage_is_not_a_captured_or_present_mon():
    source = bytearray(battery())
    at = entry_at(2, 207)
    source[at:at + 49] = savemon(given_row())
    ds._reseal(source)
    result(P.evaluate_offline(source, manifest(box_counts=[0] * 20)), "PASS")
    evidence = P.extract_save(source)
    for name in ("main", "backup"):
        assert evidence["copies"][name]["storage"]["main"]["records"] == []
        assert evidence["copies"][name]["storage"]["backup"]["records"] == []


@pytest.mark.parametrize("mutation", ["extra-field", "schema", "bool-count", "zero-count", "count-seven",
                                     "duplicate-slot", "missing-slot", "reordered", "lower-key", "bad-ot",
                                     "bad-player", "bad-box-count", "extra-party-field"],
                         ids=["unknown-field", "schema", "boolean-count", "count-zero", "count-seven",
                              "duplicate-slot", "missing-slot", "slot-order", "noncanonical-key", "ot-width",
                              "player-width", "box-count-width", "unknown-party-field"])
def test_manifest_parser_enforces_complete_canonical_contract(mutation):
    expected = manifest([party_row(), party_row(1, dvs="654321")])
    if mutation == "extra-field":
        expected["route"] = []
    elif mutation == "schema":
        expected["schema"] = "wrong"
    elif mutation == "bool-count":
        expected["party_count"] = True
    elif mutation == "zero-count":
        expected["party_count"] = 0
    elif mutation == "count-seven":
        expected["party_count"] = 7
    elif mutation == "duplicate-slot":
        expected["party"][1]["slot"] = 0
    elif mutation == "missing-slot":
        expected["party"].pop()
    elif mutation == "reordered":
        expected["party"].reverse()
    elif mutation == "lower-key":
        expected["absent_key"] = expected["absent_key"].lower()
    elif mutation == "bad-ot":
        expected["party"][0]["ot_hex"] = "00"
    elif mutation == "bad-player":
        expected["player"] = {"id_hex": "D1", "name_hex": "00" * 8}
    elif mutation == "bad-box-count":
        expected["box_counts"] = [0] * 19
    else:
        expected["party"][0]["species"] = 19
    with pytest.raises(ValueError):
        P.parse_expected(expected)


@pytest.mark.parametrize("field", ["id_hex", "name_hex"], ids=["player-id", "player-name"])
def test_optional_player_fields_are_real_ot_checks(field):
    expected = manifest(player={"id_hex": "D1C3", "name_hex": pc.encode_text("Bbbbbbb", 8).hex()})
    result(P.compare_manifest(snapshot(), expected), "PASS")
    expected["player"][field] = "D1C2" if field == "id_hex" else pc.encode_text("Aaaaaaa", 8).hex()
    result(P.compare_manifest(snapshot(), expected), "OT_MISMATCH")
    result(P.evaluate_offline(battery(), expected), "OT_MISMATCH")


@pytest.fixture
def config():
    sites = {name: {"bank": 0x7E if name == "dispatch" else 5,
                    "addr": 0x4700 + 8 * i, "rom_offset": 0x1000 + 8 * i, "bytes": "00"}
             for i, name in enumerate(SITE_NAMES)}
    contract = {
        "schema": "polished-reload-contract-v1", "sites": sites,
        "rombank_addr": 0xFF87, "svbk_addr": 0xFF70,
        "pins": [{"offset": i, "value": i + 1} for i in range(9)],
        "guards": {name: {"domain": "System Bus", "offset": 0xC100 + i}
                   for i, name in enumerate(GUARDS)},
        "ram": {}, "storage": {"main": 0x30E4, "backup": 0x3378, "boxes": 20,
                                  "slots": 20, "metadata_size": 33, "sections": []},
        "save": {"phase_offset": 0x0BE5, "version_offset": 0x0BE2},
        "version": {"offset": 0x200, "length": 20, "hex": "ab" * 20},
        "stable_frames": 3,
    }
    return {"run_id": "synthetic-cold-reload", "provenance": {"rom_sha1": "a" * 40,
            "fixture_sha256": hashlib.sha256(battery()).hexdigest()}, "contract": contract,
            "frames": 100, "trace_cap": 1000,
            "steps": [{"phase": "idle", "frames": 100, "buttons": []}]}


def stack_hex(config):
    raw = bytearray(28)
    for pin in config["contract"]["pins"]:
        raw[pin["offset"]] = pin["value"]
    return raw.hex()


def hook(config, kind, frame, **overrides):
    site = config["contract"]["sites"][kind]
    row = {"kind": kind, "frame": frame, "hook_addr": site["addr"], "pc": site["addr"],
           "sp": 0xC0D2, "bank": site["bank"], "matched": True, "qualified": True,
           "hook_bytes": site["bytes"]}
    if kind == "dispatch":
        row.update(guards=copy.deepcopy(GUARDS), svbk=1, stack_hex=stack_hex(config),
                   engine_clean=True, stack_match=True)
    if kind in ("primary_fail", "backup_fail"):
        row.update(checksum_flags=0x80, checksum_zero=True)
    row.update(overrides)
    return row


def envelope(config, rows):
    trace = [{"kind": "begin", "frame": 0, "run_id": config["run_id"],
              "provenance": copy.deepcopy(config["provenance"]), "cold_boot": True}] + copy.deepcopy(rows)
    counts = {}
    for name, site in config["contract"]["sites"].items():
        retained = [r for r in rows if r["kind"] == name]
        wrong = Counter(str(int(r["bank"])) for r in retained if r["bank"] != site["bank"])
        counts[name] = {
            "total": len(retained),
            "qualified": sum(r["bank"] == site["bank"] and r["pc"] == site["addr"] for r in retained),
            "wrong_pc": sum(r["bank"] == site["bank"] and r["pc"] != site["addr"] for r in retained),
            "wrong_banks": dict(wrong), "wrong_bank_samples": min(16, sum(wrong.values())),
        }
    elapsed = 12 if any(r["kind"] == "snapshot" for r in rows) else config["frames"]
    trace.append({"kind": "final", "frame": elapsed, "completed": True, "elapsed": elapsed,
                  "guest_writes": 0, "cpu_changes": 0, "driver_errors": 0, "overflows": 0,
                  "snapshot_count": sum(r["kind"] == "snapshot" for r in rows),
                  "wrong_bank_sample_limit": 16, "hook_counts": counts})
    for i, row in enumerate(trace, 1):
        row["ord"] = i
    return trace


def pass_rows(config, snap=None, *, backup=False):
    snap = snapshot() if snap is None else copy.deepcopy(snap)
    snap["checkpoint"]["stack_hex"] = stack_hex(config)
    if backup:
        snap["engine_integrity"].update(primary="invalid", backup="valid", selected="backup")
        load = [hook(config, "load_begin", 1),
                hook(config, "primary_fail", 2, checksum_flags=0, checksum_zero=False),
                hook(config, "backup_begin", 3), hook(config, "backup_fail", 4),
                hook(config, "backup_loaded", 5)]
    else:
        load = [hook(config, "load_begin", 1), hook(config, "primary_fail", 2),
                hook(config, "primary_loaded", 3)]
    return [*load, *(hook(config, "dispatch", f) for f in (10, 11, 12)), snap]


@pytest.mark.parametrize("backup", [False, True], ids=["primary-accepted", "backup-accepted"])
def test_live_requires_positive_native_copy_acceptance(config, backup):
    trace = envelope(config, pass_rows(config, backup=backup))
    originals = copy.deepcopy((trace, config))
    result(P.evaluate(trace, manifest(), config), "PASS")
    assert (trace, config) == originals


@pytest.mark.parametrize("case,verdict", [
    ("given", "STILL_PRESENT_GIVEN"), ("count", "PARTY_COUNT_MISMATCH"),
    ("missing", "MISSING_RECEIVED"), ("ot", "OT_MISMATCH"),
    ("census", "CENSUS_MISMATCH"), ("saved", "INCOMPLETE"), ("hex", "FAIL"),
], ids=["given", "count", "missing", "ot", "census", "saved", "hex"])
def test_live_uses_same_snapshot_verdicts(config, case, verdict):
    snap = snapshot()
    if case == "given":
        snap["party"][0] = given_row()
    elif case == "count":
        snap = snapshot([party_row(), party_row(1, dvs="654321")])
    elif case == "missing":
        snap["party"][0] = party_row(dvs="654321")
    elif case == "ot":
        snap["party"][0] = party_row(extra=b"\x04\x05\x07")
    elif case == "census":
        box_add(snap, given_row(), copies=("backup",))
    elif case == "saved":
        snap["saved_at_least_once"] = 0
    else:
        snap["party"][0]["record_hex"] = "oops"
    result(P.evaluate(envelope(config, pass_rows(config, snap)), manifest(), config), verdict)


@pytest.mark.parametrize("case", ["empty", "wrong-bank"], ids=["no-callbacks", "wrong-bank-only"])
def test_live_no_qualified_measurement_is_no_hit(config, case):
    rows = [] if case == "empty" else [hook(config, "dispatch", 10, bank=37, matched=False, qualified=False)]
    result(P.evaluate(envelope(config, rows), manifest(), config), "NO_HIT")


@pytest.mark.parametrize("field", ["guest_writes", "cpu_changes", "driver_errors", "overflows"],
                         ids=["memory-write", "register-change", "driver-error", "capacity-overflow"])
def test_live_read_only_and_capacity_contract_is_fail_closed(config, field):
    trace = envelope(config, pass_rows(config))
    trace[-1][field] = 1
    result(P.evaluate(trace, manifest(), config), "FAIL")


@pytest.mark.parametrize("case", ["missing-total", "inconsistent-total", "wrong-pc", "wrong-ord",
                                  "backwards-frame", "provenance", "warm-boot", "lying-bank",
                                  "lying-stack", "lying-engine", "wrong-bank-key", "snapshot-count"],
                         ids=["missing-count", "false-count", "wrong-pc", "ordinal", "frame",
                              "provenance", "not-cold", "bank-qualification", "stack-claim", "engine-claim",
                              "noncanonical-bank-key", "snapshot-counter"])
def test_live_rejects_forged_or_inconsistent_recording(config, case):
    trace = envelope(config, pass_rows(config))
    dispatch = next(r for r in trace if r["kind"] == "dispatch")
    if case == "missing-total":
        del trace[-1]["hook_counts"]["dispatch"]["total"]
    elif case == "inconsistent-total":
        trace[-1]["hook_counts"]["dispatch"]["total"] += 1
    elif case == "wrong-pc":
        dispatch.update(pc=dispatch["pc"] + 1, qualified=False)
        trace[-1]["hook_counts"]["dispatch"].update(qualified=2, wrong_pc=1)
    elif case == "wrong-ord":
        trace[2]["ord"] = 1
    elif case == "backwards-frame":
        trace[2]["frame"] = 0
    elif case == "provenance":
        trace[0]["provenance"]["fixture_sha256"] = "f" * 64
    elif case == "warm-boot":
        trace[0]["cold_boot"] = False
    elif case == "lying-bank":
        dispatch["bank"] = 37
    elif case == "lying-stack":
        dispatch["stack_hex"] = "00" * 28
    elif case == "lying-engine":
        dispatch["guards"]["battle_mode"] = 1
    elif case == "wrong-bank-key":
        trace[-1]["hook_counts"]["dispatch"]["wrong_banks"] = {"37.0": 1}
    else:
        trace[-1]["snapshot_count"] = 2
    result(P.evaluate(trace, manifest(), config), "FAIL")


@pytest.mark.parametrize("case", ["no-final", "incomplete-final", "no-begin", "no-load-start",
                                  "no-load-accept", "no-stability", "repeated-frame", "frame-gap"],
                         ids=["truncated", "encoder-fallback-final", "missing-begin", "missing-load-begin",
                              "missing-accepted-copy", "only-two-frames", "same-frame", "nonconsecutive-frames"])
def test_live_missing_cold_load_or_stability_evidence_cannot_pass(config, case):
    rows = pass_rows(config)
    if case == "no-load-start":
        rows = [r for r in rows if r["kind"] != "load_begin"]
    elif case == "no-load-accept":
        rows = [r for r in rows if r["kind"] != "primary_loaded"]
    elif case == "no-stability":
        rows.pop(4)
    elif case in {"repeated-frame", "frame-gap"}:
        # Duplicate frame is not a third distinct frame; a gap restarts the streak.
        rows[4]["frame"] = 10 if case == "repeated-frame" else 12
    trace = envelope(config, rows)
    if case == "no-final":
        trace.pop()
    elif case == "incomplete-final":
        trace[-1]["completed"] = False
    elif case == "no-begin":
        trace.pop(0)
    result(P.evaluate(trace, manifest(), config),
           "FAIL" if case in {"no-begin", "no-load-start"} else "INCOMPLETE")


@pytest.mark.parametrize("kind", ["primary_fail", "backup_loaded", "corrupt"],
                         ids=["primary-failed-after-accept", "both-copies-accepted", "corrupt-after-accept"])
def test_contradictory_native_engine_branches_fail(config, kind):
    rows = pass_rows(config)
    evidence = {"checksum_flags": 0, "checksum_zero": False} if kind == "primary_fail" else {}
    rows.insert(3, hook(config, kind, 4, **evidence))
    result(P.evaluate(envelope(config, rows), manifest(), config), "FAIL")


def test_fallback_error_and_incomplete_final_are_failure_not_silent_success(config):
    trace = envelope(config, [])
    trace[-1].update(driver_errors=1, completed=False)
    trace.insert(-1, {"kind": "driver_error", "frame": 1, "error": "encoder returned nil"})
    for i, row in enumerate(trace, 1):
        row["ord"] = i
    result(P.evaluate(trace, manifest(), config), "FAIL")


@pytest.mark.parametrize("case", ["bad-buttons", "reset", "synthetic", "no-idle", "bool-frames", "over-cap"],
                         ids=["unknown-button", "reset", "synthetic-field", "missing-release", "boolean-frames", "frame-cap"])
def test_route_parser_only_admits_native_actions_and_idle_release(tmp_path, case):
    route = {"steps": [{"phase": "setup", "frames": 3, "buttons": ["A"]},
                       {"phase": "idle", "frames": 3, "buttons": []}]}
    if case in {"bad-buttons", "reset"}:
        route["steps"][0]["buttons"] = ["magic" if case == "bad-buttons" else "Reset"]
    elif case == "synthetic":
        route["steps"][0]["write_u8"] = 0
    elif case == "no-idle":
        route["steps"].pop()
    elif case == "bool-frames":
        route["steps"][0]["frames"] = True
    else:
        route["steps"][0]["frames"] = 101
    path = tmp_path / "route.json"
    path.write_text(json.dumps(route), encoding="utf-8")
    with pytest.raises(ValueError):
        P.parse_route(path, 100)


def test_lua55_compile_only_does_not_execute_driver():
    lua55 = pytest.importorskip("lupa.lua55")
    lua = lua55.LuaRuntime(unpack_returned_tuples=True)
    # load returns a function; never call it (it would depend on BizHawk globals).
    compile_chunk = lua.eval("function(source) local fn, err = load(source, '@reload_probe.lua'); return fn ~= nil, err end")
    ok, error = compile_chunk((ROOT / "tools/polished_live/reload_probe.lua").read_text(encoding="utf-8"))
    assert ok, error


@pytest.mark.parametrize("dry_run", [False, True], ids=["offline", "offline-dry-run"])
def test_offline_cli_does_not_prepare_launch_or_modify_fixture(tmp_path, monkeypatch, capsys, dry_run):
    fixture = tmp_path / "battery.SaveRAM"
    expected = tmp_path / "expected.json"
    fixture.write_bytes(battery())
    expected.write_text(json.dumps(manifest()), encoding="utf-8")
    before_env, before_files = dict(os.environ), set(tmp_path.iterdir())
    before = fixture.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("offline CLI must not prepare a ROM, import a harness, or create a lane")

    monkeypatch.setattr(P, "prepare", forbidden)
    before_modules = set(sys.modules)
    args = ["--offline", "--fixture", str(fixture), "--expected", str(expected)]
    if dry_run:
        args.append("--dry-run")
    assert P.main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["measurement_verdict" if dry_run else "verdict"] == (None if dry_run else "PASS")
    assert fixture.read_bytes() == before
    assert before[32768:] == RTC
    assert dict(os.environ) == before_env
    assert set(tmp_path.iterdir()) == before_files
    assert not any("harness" in name for name in set(sys.modules) - before_modules)


def test_live_dry_run_validates_without_creating_lane_or_importing_harness(tmp_path, monkeypatch, capsys, config):
    fixture, expected, route = (tmp_path / name for name in ("battery.SaveRAM", "expected.json", "route.json"))
    fixture.write_bytes(battery())
    expected.write_text(json.dumps(manifest()), encoding="utf-8")
    route.write_text(json.dumps({"steps": [{"phase": "idle", "frames": 3, "buttons": []}]}), encoding="utf-8")
    monkeypatch.setattr(P, "prepare", lambda: (bytes(0x20000), config["contract"], config["provenance"]))
    before_env, before_modules = dict(os.environ), set(sys.modules)
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    assert P.main(["--dry-run", "--fixture", str(fixture), "--expected", str(expected),
                   "--route", str(route)]) == 0
    assert json.loads(capsys.readouterr().out)["measurement_verdict"] is None
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == before
    assert dict(os.environ) == before_env
    assert not any("harness" in name for name in set(sys.modules) - before_modules)


@pytest.mark.parametrize("case,verdict", [
    ("census-and-given", "CENSUS_MISMATCH"),
    ("given-and-count", "STILL_PRESENT_GIVEN"),
    ("count-and-missing", "PARTY_COUNT_MISMATCH"),
    ("missing-and-ot", "MISSING_RECEIVED"),
    ("incomplete-and-given", "INCOMPLETE"),
    ("fail-and-incomplete", "FAIL"),
], ids=["census-before-given", "given-before-count", "count-before-missing",
        "missing-before-ot", "incomplete-before-given", "fail-before-incomplete"])
def test_verdict_precedence_is_consistent_for_compare_and_live(config, case, verdict):
    snap = snapshot()
    if case == "census-and-given":
        box_add(snap, given_row(), copies=("main",))
    elif case == "given-and-count":
        snap = snapshot([party_row(), {**given_row(), "slot": 1}])
    elif case == "count-and-missing":
        snap = snapshot([party_row(dvs="654321"), party_row(1, dvs="abcdef")])
    elif case == "missing-and-ot":
        snap["party"][0] = party_row(dvs="654321", extra=b"\x01\x02\x03")
    elif case == "incomplete-and-given":
        snap["party"][0] = given_row()
        snap["saved_at_least_once"] = 0
    else:
        snap["saved_at_least_once"] = 0
        snap["save_version_hex"] = "ffff"
    result(P.compare_manifest(snap, manifest()), verdict)
    result(P.evaluate(envelope(config, pass_rows(config, snap)), manifest(), config), verdict)


@pytest.mark.parametrize("cap,verdict", [(6, "PASS"), (5, "FAIL")],
                         ids=["exact-protected-boundary", "one-protected-overflow"])
def test_protected_capacity_boundary_is_explicit(config, cap, verdict):
    config["trace_cap"] = cap
    result(P.evaluate(envelope(config, pass_rows(config)), manifest(), config), verdict)


def test_wrong_bank_samples_do_not_consume_protected_capacity(config):
    config["trace_cap"] = 6
    samples = [hook(config, "dispatch", 1, bank=37, matched=False, qualified=False)
               for _ in range(16)]
    trace = envelope(config, [*samples, *pass_rows(config)])
    totals = trace[-1]["hook_counts"]["dispatch"]
    # Thirty-seven callbacks were observed; only the first sixteen diagnostics survive.
    totals.update(total=40, wrong_banks={"37": 37}, wrong_bank_samples=16)
    result(P.evaluate(trace, manifest(), config), "PASS")


@pytest.mark.parametrize("site", ["primary_fail", "backup_fail"],
                         ids=["primary-checksum", "backup-checksum"])
@pytest.mark.parametrize("damage", ["missing-flags", "boolean-flags", "inconsistent-zero", "missing-zero"],
                         ids=["flags-absent", "flags-not-byte", "zero-claim-forged", "zero-absent"])
def test_checksum_epilogue_requires_cpu_flags_not_symbol_name(config, site, damage):
    rows = pass_rows(config, backup=site == "backup_fail")
    row = next(r for r in rows if r["kind"] == site)
    if damage == "missing-flags":
        del row["checksum_flags"]
    elif damage == "boolean-flags":
        row["checksum_flags"] = True
    elif damage == "inconsistent-zero":
        row["checksum_zero"] = not row["checksum_zero"]
    else:
        del row["checksum_zero"]
    result(P.evaluate(envelope(config, rows), manifest(), config), "FAIL")


@pytest.mark.parametrize("case", ["allocation", "stable-count", "accepted-copy"],
                         ids=["missing-live-flags", "missing-stability-count", "forged-copy-selection"])
def test_snapshot_success_claims_do_not_replace_observed_witnesses(config, case):
    snap = snapshot()
    if case == "allocation":
        snap["storage"]["used_flags"] = None
    elif case == "stable-count":
        del snap["stable_frame_count"]
    else:
        snap["engine_integrity"]["backup"] = "valid"
    result(P.evaluate(envelope(config, pass_rows(config, snap)), manifest(), config), "INCOMPLETE")


def test_successful_primary_does_not_claim_unexecuted_backup_checksum(config):
    trace = envelope(config, pass_rows(config))
    snap = next(r for r in trace if r["kind"] == "snapshot")
    assert snap["engine_integrity"]["backup"] == "unobserved"
    assert trace[-1]["hook_counts"]["backup_fail"]["total"] == 0
    result(P.evaluate(trace, manifest(), config), "PASS")


def test_manifest_parse_is_pure_and_normalizes_nonidentity_hex():
    expected = manifest(player={"id_hex": "D1C3", "name_hex": pc.encode_text("Bbbbbbb", 8).hex().upper()},
                        overlay_version_hex="AB" * 20, box_counts=[0] * 20)
    expected["party"][0]["ot_hex"] = expected["party"][0]["ot_hex"].upper()
    before = copy.deepcopy(expected)
    parsed = P.parse_expected(expected)
    assert expected == before
    assert parsed["party"][0]["key"] == before["party"][0]["key"]
    assert parsed["party"][0]["ot_hex"] == before["party"][0]["ot_hex"].lower()
    assert parsed["overlay_version_hex"] == "ab" * 20


def test_route_accepts_native_setup_followed_by_released_idle(tmp_path):
    route = {"steps": [{"phase": "setup", "frames": 3, "buttons": ["A", "Right"]},
                       {"phase": "idle", "frames": 3, "buttons": []}]}
    path = tmp_path / "route.json"
    path.write_text(json.dumps(route), encoding="utf-8")
    assert P.parse_route(path, 6) == route["steps"]


@pytest.mark.parametrize("mode", ["offline-route", "live-no-route"],
                         ids=["offline-rejects-route", "live-requires-route"])
def test_cli_rejects_incompatible_modes_without_side_effects(tmp_path, mode):
    fixture, expected, route = (tmp_path / name for name in ("battery.SaveRAM", "expected.json", "route.json"))
    fixture.write_bytes(battery())
    expected.write_text(json.dumps(manifest()), encoding="utf-8")
    route.write_text(json.dumps({"steps": [{"phase": "idle", "frames": 3, "buttons": []}]}), encoding="utf-8")
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    args = ["--fixture", str(fixture), "--expected", str(expected)]
    if mode == "offline-route":
        args += ["--offline", "--route", str(route)]
    with pytest.raises(SystemExit) as error:
        P.parse_args(args)
    assert error.value.code == 2
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize("damage", ["alias", "bad-seal", "invalid-entry", "split-copies"],
                         ids=["aliased-reference", "bad-savemon", "entry-208", "main-backup-disagree"])
def test_offline_census_rejects_persistent_pointer_and_entry_damage(damage):
    snap = snapshot()
    box_add(snap, party_row(dvs="654321"), db_bank=2, entry=207)
    source = bytearray(battery(boxes=snap))
    if damage == "bad-seal":
        source[entry_at(2, 207) + 1] ^= 1
    else:
        copies = (ds.MAIN,) if damage == "split-copies" else ds.ALL_COPIES
        for c in copies:
            base = c.newbox_at + 19 * 33
            if damage == "alias":
                source[base + 18] = 207
                source[base + 22] |= 1 << 2
            else:
                source[base + 19] = 208 if damage == "invalid-entry" else 0
    ds._reseal(source)
    result(P.evaluate_offline(source, manifest()), "CENSUS_MISMATCH")


def test_every_expected_slot_key_is_required_not_merely_received_key_membership(config):
    rows = [party_row(), party_row(1, dvs="654321")]
    expected = manifest(rows)
    result(P.compare_manifest(snapshot(rows), expected), "PASS")
    result(P.evaluate_offline(battery(rows), expected), "PASS")
    changed = [rows[0], party_row(1, dvs="abcdef")]
    result(P.compare_manifest(snapshot(changed), expected), "MISSING_RECEIVED")
    result(P.evaluate_offline(battery(changed), expected), "MISSING_RECEIVED")
    result(P.evaluate(envelope(config, pass_rows(config, snapshot(changed))), expected, config),
           "MISSING_RECEIVED")


@pytest.mark.parametrize("field,value", [
    ("party_count", True), ("party", {}), ("player_id_hex", "xyz"),
    ("save_phase", False), ("saved_at_least_once", None),
    ("overlay_version_hex", "ab"), ("storage", []),
], ids=["bool-count", "party-object", "bad-player-hex", "bool-phase", "missing-saved",
        "short-overlay", "storage-array"])
def test_malformed_snapshot_types_and_hex_are_failure(field, value):
    snap = snapshot()
    snap[field] = value
    result(P.compare_manifest(snap, manifest()), "FAIL")


def test_box_occupancy_optional_manifest_reads_twenty_counts_from_each_copy():
    snap = snapshot()
    box_add(snap, party_row(dvs="654321"), box=0, slot=0, db_bank=1, entry=1)
    expected = manifest(box_counts=[1] + [0] * 19)
    result(P.compare_manifest(snap, expected), "PASS")
    result(P.evaluate_offline(battery(boxes=snap), expected), "PASS")
    expected["box_counts"] = [0] * 19 + [1]
    result(P.compare_manifest(snap, expected), "CENSUS_MISMATCH")
    result(P.evaluate_offline(battery(boxes=snap), expected), "CENSUS_MISMATCH")


@pytest.fixture
def synthetic_contract_inputs():
    # Linked symbol geometry is a repository artifact, not a machine-local ROM.
    symbols = P.read_symbols(ROOT / "data/polished/polished_slink.sym")
    rom = bytearray(0x200000)
    for index, label in enumerate(P.SITES.values()):
        bank, address = symbols[label]
        at = bank * 0x4000 + address - 0x4000
        rom[at:at + 4] = bytes([index + 1, 2, 3, 4])
    bank, address = symbols["SlinkVersionText"]
    version_at = bank * 0x4000 + address - 0x4000
    rom[version_at:version_at + 20] = bytes.fromhex("ab" * 20)
    proof = {"output": {"version_slot": {"offset": version_at, "length": 20}}}
    return symbols, bytes(rom), proof


@pytest.mark.parametrize("case", ["party-stride", "ot-stride", "nickname-stride", "saved-layout",
                                  "database-layout", "checksum-region", "native-bank", "ram-bank",
                                  "short-rom", "version-slot"],
                         ids=["party-size", "ot-size", "nickname-size", "saved-flag-offset",
                              "savemon-section", "native-checksum", "load-hook-bank", "wram-mapping",
                              "anchor-outside-rom", "version-outside-pinned-slot"])
def test_contract_refuses_geometry_that_cannot_read_native_save(synthetic_contract_inputs, case):
    symbols, rom, proof = synthetic_contract_inputs
    symbols, proof = copy.deepcopy(symbols), copy.deepcopy(proof)
    if case in {"party-stride", "ot-stride", "nickname-stride"}:
        label = {"party-stride": "wPartyMon2", "ot-stride": "wPartyMon2OT",
                 "nickname-stride": "wPartyMon2Nickname"}[case]
        bank, address = symbols[label]
        symbols[label] = bank, address + 1
    elif case in {"saved-layout", "database-layout", "checksum-region"}:
        label = {"saved-layout": "wSavedAtLeastOnce", "database-layout": "sBoxMons2C",
                 "checksum-region": "sChecksum"}[case]
        bank, address = symbols[label]
        symbols[label] = bank, address + 1
    elif case == "native-bank":
        _, address = symbols["TryLoadSaveFile"]
        symbols["TryLoadSaveFile"] = 6, address
    elif case == "ram-bank":
        _, address = symbols["wPlayerID"]
        symbols["wPlayerID"] = 3, address
    elif case == "short-rom":
        rom = rom[:1]
    else:
        proof["output"]["version_slot"]["offset"] += 1
    with pytest.raises(ValueError):
        P.derive_contract(symbols, rom, proof)
