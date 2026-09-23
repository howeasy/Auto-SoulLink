"""The gen3_frlg duo row of tools/e2e_duo.py, without an emulator (card C4-6a).

Synthetic flash images are built with server/adapters/gen3_codec.py exactly the way the game lays
a save out (14 sections per slot, slot = counter % 2, sectors 28-31 outside both slots), so every
rule of check_save_witness_gen3 has a positive and a named failure, and every saved-state oracle
helper is exercised on decoded saves. The runner's per-game dispatch (ROM, battery seed, GBA
config, stub fields) is checked against a recorded Popen, and the driver files are checked for
the pret symbols, paths and helper exports they name.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tests" / "unit"))

import e2e_duo as duo  # noqa: E402
import gen3_fixtures  # noqa: E402

# Reuse the RR compressed-mon builder (server/adapters/gen3_codec round-trip already proven
# there) rather than re-deriving the CompressedPokemon layout a second time.
from test_gen3_rr_save_layout import _compressed  # noqa: E402

from server.adapters import gen3_codec as codec  # noqa: E402

GEN3 = ("faint_cmd_gen3", "linked_faint_active_gen3", "boxsync_gen3", "whiteout_gen3",
        "link_gen3", "deadzone_gen3", "reconnect_gen3")
# P5 (card C5-5): RR-only, added on top of GEN3 above (which now also runs on gen3_rr_new).
GEN3_RR_ONLY = ("explode_gen3", "rival_swap_gen3", "native_absent_gen3")
OT_A = 0x99DE0D8A


# ── synthetic saves ─────────────────────────────────────────────────────────────────────────
def _mon(personality, *, party=True, ot_id=OT_A, level=5, species=7):
    mon = {
        "personality": personality, "ot_id": ot_id, "nickname": "MON", "language": 2,
        "is_bad_egg": 0, "has_species": 1, "is_egg_flag": 0, "block_box_rs": 0,
        "flags_unused": 0, "ot_name": "JONN", "markings": 0, "unknown": 0,
        "species": species, "held_item": 0, "experience": 135, "pp_bonuses": 0,
        "friendship": 70, "growth_filler": 0, "moves": [33, 39, 0, 0], "pp": [35, 30, 0, 0],
        "evs": dict.fromkeys(("hp", "attack", "defense", "speed", "sp_attack", "sp_defense"), 0),
        "contest": [0] * 6, "pokerus": 0, "met_location": 88, "met_level": 5, "met_game": 4,
        "pokeball": 4, "ot_gender": 0,
        "ivs": dict.fromkeys(("hp", "attack", "defense", "speed", "sp_attack", "sp_defense"), 7),
        "is_egg": 0, "ability_num": 0, "ribbons": 0,
    }
    if party:
        mon.update({"status": 0, "level": level, "mail": 0xFF, "hp": 20, "max_hp": 20,
                    "attack": 10, "defense": 11, "speed": 9, "sp_attack": 10, "sp_defense": 12})
    return mon


def _key(mon):
    return f"{mon['personality']:08X}:{mon['ot_id']:08X}"


def _blocks(party, boxes, balls):
    sb2 = bytearray(codec.SAVEBLOCK2_SIZE)
    sb2[0xA:0xE] = OT_A.to_bytes(4, "little")
    sb2[0xF20:0xF24] = (0x0000BEEF).to_bytes(4, "little")          # encryptionKey
    sb1 = bytearray(codec.SAVEBLOCK1_SIZE)
    sb1[codec.SB1_PARTY_COUNT_OFFSET] = len(party)
    for i, mon in enumerate(party):
        at = codec.SB1_PARTY_OFFSET + i * codec.PARTY_MON_SIZE
        sb1[at:at + codec.PARTY_MON_SIZE] = codec.encode_party_mon(mon)
    if balls:
        sb1[0x430:0x432] = (4).to_bytes(2, "little")                 # ITEM_POKE_BALL
        sb1[0x432:0x434] = (balls ^ 0xBEEF).to_bytes(2, "little")
    storage = bytearray(codec.STORAGE_SIZE)
    for (box, slot), mon in boxes.items():
        at = codec.BOX_DATA_OFFSET + (box * codec.MONS_PER_BOX + slot) * codec.BOX_MON_SIZE
        storage[at:at + codec.BOX_MON_SIZE] = codec.encode_box_mon(mon)
    return {"sb1": sb1, "sb2": sb2, "storage": storage}


def _write_slot(image, counter, party, boxes=None, balls=4):
    blocks = _blocks(party, boxes or {}, balls)
    layout = codec.slot_layout()
    half = codec.NUM_SECTORS_PER_SLOT * (counter % codec.NUM_SAVE_SLOTS)
    for entry in layout:
        chunk = bytes(blocks[entry["object"]])[entry["offset"]:entry["offset"] + entry["size"]]
        at = (half + entry["id"]) * codec.SECTOR_SIZE
        image[at:at + codec.SECTOR_SIZE] = codec.write_sector(chunk, entry["id"], counter, layout)


def _fixture(party, boxes=None, balls=4):
    """Counter 2 in slot 0, the older counter 1 in slot 1, patterned Hall of Fame sectors."""
    image = bytearray(codec.FLASH_SIZE)
    _write_slot(image, 1, party[:1], balls=balls)
    _write_slot(image, 2, party, boxes, balls=balls)
    hof = 2 * codec.NUM_SECTORS_PER_SLOT * codec.SECTOR_SIZE
    image[hof:] = bytes((i * 13 + 5) & 0xFF for i in range(codec.FLASH_SIZE - hof))
    return bytes(image)


def _saved(fixture, counter, party, boxes=None, balls=4):
    image = bytearray(fixture)
    _write_slot(image, counter, party, boxes, balls=balls)
    return bytes(image)


STARTER, PIDGEY, CATCH = _mon(0x2D356A90), _mon(0x263620B6, species=16), _mon(0x11112222, species=19)


@pytest.fixture
def pair():
    fixture = _fixture([STARTER, PIDGEY])
    return fixture, _saved(fixture, 3, [STARTER, PIDGEY])


# ── check_gen3_witness: the byte rules ──────────────────────────────────────────────────────
def test_witness_positive_and_rtc_suffix_is_normalized(pair):
    fixture, saved = pair
    facts = duo.check_gen3_witness(saved, saved, fixture, saves=1)
    assert facts["counter"] == (2, 3) and facts["site"] == facts["file"] and not facts["rtc"]
    facts = duo.check_gen3_witness(saved, saved + b"\x01" * 16, fixture, saves=1)
    assert facts["rtc"] is True


def test_witness_two_saves_skip_the_other_slot_rule(pair):
    fixture, _ = pair
    twice = _saved(_saved(fixture, 3, [STARTER, PIDGEY]), 4, [STARTER])
    assert duo.check_gen3_witness(twice, twice, fixture, saves=2)["counter"] == (2, 4)


@pytest.mark.parametrize("mutate, flushed_from, saves, message", [
    ("short", None, 1, "expected 131072"),
    ("torn", None, 1, "not a complete save"),
    ("unchanged", None, 1, "did not advance"),
    (None, None, 2, "witnessed 2 save"),
    ("hof", None, 1, "sectors 28-31 differ"),
    ("old_slot", None, 1, "the unwritten slot 0 differ"),
    (None, "other_party", 1, "decoded party differs"),
    (None, "other_boxes", 1, "decoded boxes differ"),
    (None, "footer", 1, "does not match the flushed battery"),
    (None, "bad_length", 1, "unsupported length"),
])
def test_witness_each_failure_mode_is_named(pair, mutate, flushed_from, saves, message):
    fixture, saved = pair
    witness = bytearray(saved)
    if mutate == "short":
        witness = witness[:-1]
    elif mutate == "torn":
        # slot 1 (counter 3), section id 5: a data byte flipped breaks its checksum
        witness[(14 + 5) * codec.SECTOR_SIZE + 3] ^= 0xFF
    elif mutate == "unchanged":
        witness = bytearray(fixture)
    elif mutate == "hof":
        witness[30 * codec.SECTOR_SIZE] ^= 0xFF
    elif mutate == "old_slot":
        _write_slot(witness, 2, [STARTER])        # slot 0 rewritten: still valid, not the fixture's
    witness = bytes(witness)
    flushed = witness
    if flushed_from == "other_party":
        flushed = _saved(fixture, 3, [STARTER, PIDGEY, CATCH])
    elif flushed_from == "other_boxes":
        flushed = _saved(fixture, 3, [STARTER, PIDGEY], {(0, 0): _mon(0x33334444, party=False)})
    elif flushed_from == "footer":
        # an unchecksummed byte between the section data and the footer: decodes the same
        raw = bytearray(witness)
        raw[14 * codec.SECTOR_SIZE + 0xFA0] ^= 0xFF
        flushed = bytes(raw)
    elif flushed_from == "bad_length":
        flushed = witness + b"\x00" * 3
    with pytest.raises(RuntimeError, match=re.escape(message)):
        duo.check_gen3_witness(witness, flushed, fixture, saves=saves)


# ── check_gen3_witness(rr=True): RR's own layout and its narrower "untouched" range ────────
RR_MON = (277, 0xEBEF11DA, 0x2BDDC8BF)   # species, personality, ot_id -- test_gen3_rr_save_layout's own Treecko


def _rr_mon_bytes(species, personality, ot_id, level=5):
    """A plaintext (RR is CFRU_NO_ENCRYPT) party record: expand_compressed_box_mon + the
    party-only tail, same technique test_gen3_rr_save_layout's own synthetic test uses."""
    raw = bytearray(codec.expand_compressed_box_mon(_compressed(species, personality, ot_id)))
    raw += bytes(codec.PARTY_MON_SIZE - codec.BOX_MON_SIZE)
    raw[0x54] = level
    return bytes(raw)


def _rr_write_slot(image, counter, party=RR_MON, ext_byte=None, rotation=0):
    """Mutate `image` in place: one RR slot the way the game writes it (sibling of `_write_slot`
    above, RR-chunked via `_build_rr_image`'s own placement rule). `ext_byte`, when given, also
    rewrites the unrotated extension (sectors 30-31) -- omitted, it is left alone, the same way a
    real single-sector save leaves untouched chunks alone."""
    layout = codec.rr_slot_layout()
    sb1 = bytearray(codec.SAVEBLOCK1_SIZE)
    sb1[codec.SB1_PARTY_COUNT_OFFSET] = 1
    sb1[codec.SB1_PARTY_OFFSET:codec.SB1_PARTY_OFFSET + codec.PARTY_MON_SIZE] = _rr_mon_bytes(*party)
    source = {"sb2": bytes(codec.SAVEBLOCK2_SIZE), "sb1": bytes(sb1), "storage": bytes(codec.STORAGE_SIZE)}
    for sid, entry in enumerate(layout):
        chunk = source[entry["object"]][entry["offset"]:entry["offset"] + entry["size"]]
        index = ((rotation + sid) % codec.NUM_SECTORS_PER_SLOT) + codec.NUM_SECTORS_PER_SLOT * (counter % 2)
        image[index * codec.SECTOR_SIZE:(index + 1) * codec.SECTOR_SIZE] = \
            codec.write_sector(chunk, sid, counter, layout)
    if ext_byte is not None:
        ext = bytes([ext_byte]) * codec.RR_EXT_SIZE
        for n, index in enumerate(codec.RR_EXT_SECTORS):
            image[index * codec.SECTOR_SIZE:(index + 1) * codec.SECTOR_SIZE] = \
                ext[n * codec.CHUNK_SIZE_CFRU:(n + 1) * codec.CHUNK_SIZE_CFRU].ljust(codec.SECTOR_SIZE, b"\0")


def _rr_fixture(party=RR_MON, ext_byte=0x00):
    """Counter 2 in slot 0, the older counter 1 in slot 1 -- the RR sibling of `_fixture` above,
    so a one-save witness has a real (not erased) "other slot" to compare against."""
    image = bytearray(b"\xff" * codec.FLASH_SIZE)
    _rr_write_slot(image, 1, party, ext_byte=ext_byte)
    _rr_write_slot(image, 2, party, ext_byte=ext_byte)
    return bytes(image)


def _rr_saved(fixture, counter, party=RR_MON, ext_byte=None):
    image = bytearray(fixture)
    _rr_write_slot(image, counter, party, ext_byte=ext_byte)
    return bytes(image)


def test_rr_witness_positive():
    fixture = _rr_fixture()
    saved = _rr_saved(fixture, 3)
    facts = duo.check_gen3_witness(saved, saved, fixture, saves=1, rr=True)
    assert facts["counter"] == (2, 3)


def test_rr_witness_extension_boxes_may_legitimately_change():
    """docs/gen3/research/flash_save.md:136: sectors 30-31 (RR boxes 20-22) carry no checksum or
    generation counter of their own, and a normal save CAN rewrite them -- unlike vanilla's Hall
    of Fame, asserting byte-equality against the fixture there would be wrong, not stricter."""
    fixture = _rr_fixture(ext_byte=0x00)
    saved = _rr_saved(fixture, 3, ext_byte=0x11)
    facts = duo.check_gen3_witness(saved, saved, fixture, saves=1, rr=True)
    assert facts["counter"] == (2, 3)


def test_rr_witness_still_refuses_a_changed_hall_of_fame_sector():
    """Sectors 28-29 stay real Hall of Fame/Trainer Tower territory even under rr=True (only
    30-31 are RR's own extension) -- narrowing the range must not widen it into a no-op."""
    fixture = _rr_fixture()
    saved = bytearray(_rr_saved(fixture, 3))
    saved[28 * codec.SECTOR_SIZE] ^= 0xFF
    with pytest.raises(RuntimeError, match="sectors 28-29"):
        duo.check_gen3_witness(bytes(saved), bytes(saved), fixture, saves=1, rr=True)


def test_rr_witness_decoded_party_mismatch_is_named():
    """witness vs FLUSHED, not vs the fixture (check_gen3_witness compares those two): a
    from-scratch `saved` with a different party than the dumped witness must be caught."""
    fixture = _rr_fixture()
    witness = _rr_saved(fixture, 3, party=RR_MON)
    flushed = _rr_saved(fixture, 3, party=(1, 0xAAAABBBB, 0x2BDDC8BF))
    with pytest.raises(RuntimeError, match="decoded party differs"):
        duo.check_gen3_witness(witness, flushed, fixture, saves=1, rr=True)


# ── check_save_witness_gen3: the receipt and file rules ────────────────────────────────────
def _witness_run(tmp_path, monkeypatch, pair, scenario="faint_cmd_gen3"):
    fixture, saved = pair
    build = tmp_path / "build"
    build.mkdir(exist_ok=True)
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario, run.attempt, run.game = scenario, 1, "gen3_frlg"
    run.emus, run._started = [], 0
    run.cfg, run.gcfg = dict(duo.SCENARIOS[scenario]), dict(duo.GAMES["gen3_frlg"])
    notes = []
    run._pydec_note = notes.append
    monkeypatch.setattr(duo, "BUILD", str(build))
    monkeypatch.setattr(duo, "REPO", str(tmp_path))
    monkeypatch.setattr(run, "_gen3_flushed", lambda inst: saved)
    monkeypatch.setattr(run, "_gen3_fixture_bytes", lambda inst: fixture)
    receipts = {}
    for inst in ("a", "b"):
        path = build / f"e2e_{scenario}_{inst}_1_witness.bin"
        path.write_bytes(saved)
        rel = os.path.relpath(path, tmp_path).replace("\\", "/")
        receipts[inst] = (f"SAVE_WITNESS faint_cmd counter=2->3\n"
                          f"SAVE_WITNESS_DUMP path={rel} bytes={len(saved)} saves=1 frame=10 counter=3\n")
    return run, receipts, notes, build


def test_witness_method_positive(tmp_path, monkeypatch, pair):
    run, receipts, notes, _ = _witness_run(tmp_path, monkeypatch, pair)
    run.check_save_witness_gen3(receipts)
    assert len(notes) == 2 and all("match=true saves=1 counter=2->3" in n for n in notes)


def test_witness_method_refuses_a_half_that_never_saved(tmp_path, monkeypatch, pair):
    run, receipts, _, _ = _witness_run(tmp_path, monkeypatch, pair)
    receipts["b"] = "SAVE_WITNESS_DUMP_SKIPPED why=r0-255-r5-0\n"
    with pytest.raises(RuntimeError, match="b: the receipt carries no SAVE_WITNESS_DUMP.*r0-255"):
        run.check_save_witness_gen3(receipts)


def test_witness_method_honours_no_save_and_refuses_a_dump_there(tmp_path, monkeypatch, pair):
    run, receipts, notes, _ = _witness_run(tmp_path, monkeypatch, pair, "reconnect_gen3")
    good_a = receipts["a"]
    receipts["a"] = "WRITES 0\n"
    run.check_save_witness_gen3(receipts)
    assert "saves=0 skipped (no_save)" in notes[0]
    receipts["a"] = good_a
    with pytest.raises(RuntimeError, match="declared no_save"):
        run.check_save_witness_gen3(receipts)


def test_witness_method_refuses_a_stale_file(tmp_path, monkeypatch, pair):
    run, receipts, _, build = _witness_run(tmp_path, monkeypatch, pair)
    run._started = os.path.getmtime(build / "e2e_faint_cmd_gen3_a_1_witness.bin") + 60
    with pytest.raises(RuntimeError, match="predates this attempt"):
        run.check_save_witness_gen3(receipts)


@pytest.mark.parametrize("extra, message", [
    ("SAVE_WITNESS_DUMP_FAIL boom\n", "the last dump attempt"),
    ("SAVE_WITNESS_DUMP path=x bytes=1 saves=3 frame=1 counter=4\n", "the dump ordinals"),
])
def test_witness_method_reads_dump_outcomes_in_order(tmp_path, monkeypatch, pair, extra, message):
    run, receipts, _, _ = _witness_run(tmp_path, monkeypatch, pair)
    receipts["a"] += extra
    with pytest.raises(RuntimeError, match=message):
        run.check_save_witness_gen3(receipts)


def test_witness_method_refuses_a_path_the_body_did_not_log(tmp_path, monkeypatch, pair):
    run, receipts, _, _ = _witness_run(tmp_path, monkeypatch, pair)
    receipts["a"] = receipts["a"].replace("_a_1_witness", "_a_2_witness")
    with pytest.raises(RuntimeError, match="landed at"):
        run.check_save_witness_gen3(receipts)


# ── _run_oracle: required oracle, witness first ────────────────────────────────────────────
def _oracle_run(scenario, game="gen3_frlg", cfg=None):
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario, run.game = scenario, game
    run.cfg = cfg if cfg is not None else dict(duo.SCENARIOS[scenario])
    return run


def test_a_gen3_frlg_scenario_without_an_oracle_fails():
    run = _oracle_run("faint_cmd_gen3", cfg={"flags": [], "timeout": 1})
    with pytest.raises(RuntimeError, match="declares no post-result oracle.*gen3_frlg"):
        run._run_oracle({"a": "", "b": ""})


def test_the_gen3_witness_runs_before_the_oracle(monkeypatch):
    run = _oracle_run("boxsync_gen3")
    calls = []
    monkeypatch.setattr(run, "check_save_witness_gen3", lambda results: calls.append("witness"))
    monkeypatch.setattr(run, "check_save_witness", lambda results: calls.append("gen1 witness"))
    monkeypatch.setattr(run, "assert_boxsync_gen3_saved", lambda results: calls.append("oracle"))
    run._run_oracle({"a": "", "b": ""})
    assert calls == ["witness", "oracle"]


def test_rows_without_the_flag_keep_their_verdict_paths():
    """gen3_rr/gen2 scenarios carry no oracle and still return quietly; gen1_new still refuses."""
    assert _oracle_run("faint", game="gen3_rr")._run_oracle({}) is None
    assert _oracle_run("memorialize", game="gen2")._run_oracle({}) is None
    with pytest.raises(RuntimeError, match="a Gen 1 verdict"):
        _oracle_run("link_new", game="gen1_new", cfg={"flags": []})._run_oracle({})


# ── saved-state oracle helpers ─────────────────────────────────────────────────────────────
def _decoded(image):
    return duo.gen3_decode(image)


def test_memorial_problems_positive_and_negatives(pair):
    fixture, _ = pair
    good = _saved(fixture, 3, [STARTER], {(13, 0): _mon(PIDGEY["personality"], party=False, species=16)})
    key = _key(PIDGEY)
    assert duo.gen3_memorial_problems("b", _decoded(good), _decoded(fixture), key, 13) == []
    kept = _saved(fixture, 3, [STARTER, PIDGEY])
    assert any("still in the saved party" in p for p in
               duo.gen3_memorial_problems("b", _decoded(kept), _decoded(fixture), key, 13))
    wrong_box = _saved(fixture, 3, [STARTER], {(0, 0): _mon(PIDGEY["personality"], party=False)})
    assert any("not exactly once in the memorial" in p for p in
               duo.gen3_memorial_problems("b", _decoded(wrong_box), _decoded(fixture), key, 13))


def test_round_trip_problems_positive_and_negatives(pair):
    fixture, saved = pair
    key = _key(PIDGEY)
    assert duo.gen3_round_trip_problems("a", _decoded(saved), _decoded(fixture), key) == []
    moved = dict(PIDGEY, level=6, max_hp=22)
    changed = _saved(fixture, 3, [STARTER, moved])
    assert any("differs from the fixture" in p for p in
               duo.gen3_round_trip_problems("a", _decoded(changed), _decoded(fixture), key))
    boxed_too = _saved(fixture, 3, [STARTER, PIDGEY], {(0, 0): _mon(PIDGEY["personality"], party=False)})
    assert any("still (or also) in a saved box" in p for p in
               duo.gen3_round_trip_problems("a", _decoded(boxed_too), _decoded(fixture), key))


def test_capture_problems_and_ball_count(pair):
    fixture, _ = pair
    caught = _saved(fixture, 3, [STARTER, PIDGEY, CATCH], balls=3)
    key = _key(CATCH)
    assert duo.gen3_capture_problems("a", _decoded(caught), _decoded(fixture), key, 19) == []
    assert any("species" in p for p in
               duo.gen3_capture_problems("a", _decoded(caught), _decoded(fixture), key, 16))
    assert duo.gen3_ball_count(fixture) == 4 and duo.gen3_ball_count(caught) == 3


def test_receipt_problems_order_and_forbidden():
    text = "RX box_mon key=K\nTX stats_cache K {}\n"
    assert duo.gen3_receipt_problems("b", text, required=[duo.gen3_rx("box_mon", "K")],
                                     ordered=[(duo.gen3_rx("box_mon", "K"),
                                               duo.gen3_tx("stats_cache", "K"))]) == []
    assert duo.gen3_receipt_problems("b", text, ordered=[(duo.gen3_tx("stats_cache", "K"),
                                                          duo.gen3_rx("box_mon", "K"))])
    assert duo.gen3_receipt_problems("b", text, forbidden=[duo.gen3_rx("box_mon", "K")])
    assert re.search(duo.gen3_tx("whiteout", "-"), "TX whiteout - {}")
    assert not re.search(duo.gen3_rx("box_mon", "K"), "RX box_mon key=KX")


# ── oracle methods on stubbed runs ─────────────────────────────────────────────────────────
def _oracle_stub(monkeypatch, tmp_path, scenario, saved, fixture, links):
    run = _oracle_run(scenario)
    run.gcfg, run.emus, run.data_dir = dict(duo.GAMES["gen3_frlg"]), [], str(tmp_path)
    notes = []
    run._pydec_note = notes.append
    (tmp_path / "links.json").write_text(json.dumps({"links": links}), encoding="utf-8")
    monkeypatch.setattr(run, "_gen3_flushed", lambda inst: saved[inst])
    monkeypatch.setattr(run, "_gen3_fixture_bytes", lambda inst: fixture)
    run._link_keys = {"a": _key(PIDGEY), "b": _key(PIDGEY_B)}
    return run, notes


PIDGEY_B = _mon(0x263620B6, ot_id=0x6621F275, species=16)


def _faint_cmd_receipts(ka, kb):
    return {"a": f"RX memorialize key={ka}\nTX memorialize_done {ka} {{}}\n",
            "b": (f"RX force_faint key={kb}\n[client] [SLink-gen3] write overworld 0x02024282 +2 frame 9\n"
                  f"FORCED_HP0 {kb} frame=9 in_battle=0 battler=0\nRX memorialize key={kb}\n"
                  f"TX memorialize_done {kb} {{}}\n")}


def test_faint_cmd_oracle_positive_and_negative(monkeypatch, tmp_path):
    fix_a = _fixture([STARTER, PIDGEY])
    saved_a = _saved(fix_a, 3, [STARTER], {(13, 0): _mon(PIDGEY["personality"], party=False, species=16)})
    ka = _key(PIDGEY)
    # one synthetic save serves both halves here, so both halves carry A's key
    link = [{"a": {"key": ka}, "b": {"key": ka}, "status": "memorial"}]
    run, notes = _oracle_stub(monkeypatch, tmp_path, "faint_cmd_gen3", {"a": saved_a, "b": saved_a},
                              fix_a, link)
    run._link_keys = {"a": ka, "b": ka}
    receipts = _faint_cmd_receipts(ka, ka)
    run.assert_faint_cmd_gen3_saved(receipts)
    assert notes and "faint_cmd" in notes[-1]
    receipts["b"] = receipts["b"].replace("in_battle=0", "in_battle=1")
    with pytest.raises(RuntimeError, match="FORCED_HP0"):
        run.assert_faint_cmd_gen3_saved(receipts)


def test_boxsync_oracle_reads_the_keyed_ack_order(monkeypatch, tmp_path):
    fixture = _fixture([STARTER, PIDGEY])
    saved = _saved(fixture, 3, [STARTER, PIDGEY])
    k = _key(PIDGEY)
    run, _ = _oracle_stub(monkeypatch, tmp_path, "boxsync_gen3", {"a": saved, "b": saved}, fixture,
                          [{"a": {"key": k}, "b": {"key": "B"}, "status": "alive"}])
    run._link_keys = {"a": k, "b": "B"}
    monkeypatch.setattr(run, "_gen3_flushed", lambda inst: saved)
    receipts = {"a": f"TX party_to_box {k} {{}}\nTX box_to_party {k} {{}}\n",
                "b": "RX box_mon key=B\nTX stats_cache B {}\nRX party_mon key=B\nTX sync_retrieve_done B {}\n"}
    # B's key is not in the synthetic save: the round-trip helper must say so
    with pytest.raises(RuntimeError, match="b: B appears 0x"):
        run.assert_boxsync_gen3_saved(receipts)
    run._link_keys = {"a": k, "b": k}
    (tmp_path / "links.json").write_text(json.dumps({"links": [
        {"a": {"key": k}, "b": {"key": k}, "status": "alive"}]}), encoding="utf-8")
    receipts["b"] = receipts["b"].replace(" B", f" {k}").replace("=B", f"={k}")
    run.assert_boxsync_gen3_saved(receipts)
    receipts["b"] = receipts["b"].replace(f"TX stats_cache {k}", "TX nothing")
    with pytest.raises(RuntimeError, match="stats_cache"):
        run.assert_boxsync_gen3_saved(receipts)


def test_link_oracle_counts_the_thrown_balls(monkeypatch, tmp_path):
    fixture = _fixture([STARTER, PIDGEY])
    caught = _saved(fixture, 3, [STARTER, PIDGEY, CATCH], balls=2)
    k = _key(CATCH)
    run, notes = _oracle_stub(monkeypatch, tmp_path, "link_gen3", {"a": caught, "b": caught}, fixture,
                              [{"a": {"key": k}, "b": {"key": k}, "status": "alive", "area_id": "route_1"}])
    run._link_keys = {"a": k, "b": k}
    line = f'TX capture {k} {{"area_id":"route_1","event":"capture","key":"{k}","species_id":19}}\n'
    receipts = dict.fromkeys(("a", "b"), line + "THREW 1\nTHREW 2\n")
    run.assert_link_gen3_saved(receipts)
    assert any("BAG_BALLS baseline=4 final=2 throws=2" in n for n in notes)
    receipts["a"] = line + "THREW 1\n"
    with pytest.raises(RuntimeError, match="saved 2 Poke Balls"):
        run.assert_link_gen3_saved(receipts)


# ── RR-only oracles (P5, card C5-5) ─────────────────────────────────────────────────────────
def test_native_absent_oracle_positive_and_negative():
    run = _oracle_run("native_absent_gen3", game="gen3_rr_new")
    notes = []
    run._pydec_note = notes.append
    receipts = dict.fromkeys(("a", "b"), "RX apply_trade key=00000000:00000000\nWRITES 0\n")
    run.assert_native_absent_gen3_saved(receipts)
    assert notes and "native_absent" in notes[-1]
    bad = dict(receipts, b="RX apply_trade key=00000000:00000000\nWRITES 1\n")
    with pytest.raises(RuntimeError, match="WRITES 0"):
        run.assert_native_absent_gen3_saved(bad)
    missing = dict(receipts, a="WRITES 0\n")   # no RX apply_trade at all
    with pytest.raises(RuntimeError, match="RX apply_trade"):
        run.assert_native_absent_gen3_saved(missing)


def test_rival_swap_oracle_asserts_the_documented_refresh_failed_limit():
    run = _oracle_run("rival_swap_gen3", game="gen3_rr_new")
    notes = []
    run._pydec_note = notes.append
    a_untouched = ([STARTER], {})
    run._gen3_saved = lambda inst: a_untouched
    run._gen3_fixture_saved = lambda inst: a_untouched
    b_receipt = ("READY_IN_BATTLE\nRX replace_rival_team\n"
                'TX rival_team_replaced - {"error":"refresh_failed","species_ids":[],"trainer_id":0}\n')
    receipts = {"a": "", "b": b_receipt}
    run.assert_rival_swap_gen3_saved(receipts)
    assert notes and "refresh_failed" in notes[-1]
    # A successful swap (a future refresh_enemy landing) is NOT this scenario's expected outcome:
    # the oracle names it, it does not silently accept a "better" reply.
    ok_reply = dict(receipts, b=b_receipt.replace("refresh_failed", "ok"))
    with pytest.raises(RuntimeError, match="expected 'refresh_failed'"):
        run.assert_rival_swap_gen3_saved(ok_reply)
    no_marker = dict(receipts, b=b_receipt.replace("READY_IN_BATTLE\n", ""))
    with pytest.raises(RuntimeError, match="READY_IN_BATTLE"):
        run.assert_rival_swap_gen3_saved(no_marker)


# ── per-game dispatch: ROM, battery, config, stub ──────────────────────────────────────────
def test_the_row_resolves_titles_fixtures_and_one_line_leafgreen():
    row = duo.GAMES["gen3_frlg"]
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.gcfg, run.cfg = dict(row), dict(duo.SCENARIOS["boxsync_gen3"])
    assert run.is_gen3_battery and run._gen3_title("b") == "firered"
    assert run._gen3_fixture_path("a").endswith(os.path.join("gen3", "firered_party_battle.sav"))
    assert run._gen3_fixture_path("b").endswith(os.path.join("gen3", "firered_party_town_b.sav"))
    run.gcfg = dict(row, sides=dict(row["sides"], b=("leafgreen", "leafgreen_party_{target}")))
    assert run._gen3_title("b") == "leafgreen"
    assert run._gen3_fixture_path("b").endswith("leafgreen_party_town.sav")
    # P5: radical_red joined (GAMES["gen3_rr_new"]) alongside firered/leafgreen.
    assert set(duo.GEN3_TITLES) == {"firered", "leafgreen", "radical_red"}
    for inst in ("a", "b"):
        assert row["sides"][inst][0] in duo.GEN3_TITLES


def _gba_config(tmp_path):
    path = tmp_path / "config.ini"
    path.write_text(json.dumps({"MainWindowPosition": "1200, -1300", "PathEntries": {"Paths": [
        {"System": "GBA", "Type": "Save RAM", "Path": ""}]}}), encoding="utf-8")
    return path


def test_launch_seeds_the_flash_body_and_writes_a_gba_config(monkeypatch, tmp_path):
    fixture = _fixture([STARTER, PIDGEY])
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "firered_party_town.sav").write_bytes(fixture + b"\x07" * 16)   # RTC suffix dropped
    (fixtures / "firered_party_town_b.sav").write_bytes(fixture)
    monkeypatch.setattr(duo, "GEN3_FIXTURES", str(fixtures))
    monkeypatch.setattr(duo, "BUILD", str(tmp_path))
    monkeypatch.setattr(duo, "BIZHAWK_CONFIG", str(_gba_config(tmp_path)))
    monkeypatch.setattr(duo, "_LANE_ORDINAL", {})
    launched = []
    monkeypatch.setattr(duo.subprocess, "Popen", lambda argv, **kw: launched.append(argv))
    monkeypatch.setattr(gen3_fixtures, "stage_rom", lambda src: "patch/build/gen3_fr.gba")
    args = argparse.Namespace(game="gen3_frlg", lane="t", scenario="faint_cmd_gen3", idle_jitter=0)
    run = duo.DuoRun("faint_cmd_gen3", args, attempt=1)
    monkeypatch.setattr(run, "_gen3_rom", lambda inst: f"patch/build/gen3_{inst}.gba")
    run.launch_instance("a")
    battery = Path(run._saveram_dir("a")) / "Pokemon - FireRed Version (USA).SaveRAM"
    assert battery.read_bytes() == fixture
    cfg = json.loads(Path(run.cfg_path("a")).read_text(encoding="utf-8-sig"))
    gba = [e for e in cfg["PathEntries"]["Paths"] if e["System"] == "GBA"]
    assert gba[0]["Path"] == run._saveram_dir("a").replace("\\", "/")
    stub = Path(run.stub_path("a")).read_text()
    assert 'title = "firered"' in stub and 'scenario_prefix = "gen3_"' in stub
    assert 'game = "gen3_frlg"' in stub and "duo_gen3_main.lua" in stub
    assert launched[0][-1] == "patch/build/gen3_a.gba"


def test_gen3_rom_prefers_the_dump_then_the_staged_copy(monkeypatch, tmp_path):
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.gcfg, run.cfg = dict(duo.GAMES["gen3_frlg"]), dict(duo.SCENARIOS["link_gen3"])
    root = tmp_path / "main" / "wt"
    root.mkdir(parents=True)
    monkeypatch.setattr(duo, "REPO", str(root))
    (tmp_path / "main" / "Pokemon - FireRed Version (USA).gba").write_bytes(b"rom")
    staged = []
    monkeypatch.setattr(gen3_fixtures, "stage_rom", lambda src: staged.append(src) or "staged.gba")
    assert run._gen3_rom("a") == "staged.gba" and staged[0].endswith("FireRed Version (USA).gba")
    (tmp_path / "main" / "Pokemon - FireRed Version (USA).gba").unlink()
    with pytest.raises(FileNotFoundError, match="FireRed"):
        run._gen3_rom("a")


# ── RR ROM/battery staging: staged companion build vs the raw clean dump (P5, C5-5) ────────
def test_gen3_rr_rom_companion_uses_the_staged_build_directly(monkeypatch, tmp_path):
    """No dump search at all for the ordinary (default) kind: `staged` (ROM_REL) short-circuits
    it, so a companion-kind run never depends on a raw RR dump being reachable."""
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.gcfg, run.cfg = dict(duo.GAMES["gen3_rr_new"]), dict(duo.SCENARIOS["faint_cmd_gen3"])
    root = tmp_path / "wt"
    (root / "patch" / "build").mkdir(parents=True)
    (root / duo.ROM_REL).write_bytes(b"rom")
    monkeypatch.setattr(duo, "REPO", str(root))
    assert run._gen3_rom("a") == duo.ROM_REL


def test_gen3_rr_rom_companion_missing_build_refuses(monkeypatch, tmp_path):
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.gcfg, run.cfg = dict(duo.GAMES["gen3_rr_new"]), dict(duo.SCENARIOS["faint_cmd_gen3"])
    (tmp_path / "empty").mkdir()
    monkeypatch.setattr(duo, "REPO", str(tmp_path / "empty"))
    with pytest.raises(FileNotFoundError, match="slink_RR"):
        run._gen3_rom("a")


def test_gen3_rr_rom_clean_kind_searches_the_raw_dump(monkeypatch, tmp_path):
    """native_absent_gen3's `rom_kind: {"b": "clean"}` bypasses `staged` and searches for the
    raw dump (patch/tools/build.py:91 DEFAULT_RR / patch/README.md:18), same rule as firered."""
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.gcfg, run.cfg = dict(duo.GAMES["gen3_rr_new"]), dict(duo.SCENARIOS["native_absent_gen3"])
    root = tmp_path / "main" / "wt"
    root.mkdir(parents=True)
    monkeypatch.setattr(duo, "REPO", str(root))
    (tmp_path / "main" / duo.GEN3_CLEAN_RR_ROM).write_bytes(b"rom")
    staged = []
    monkeypatch.setattr(gen3_fixtures, "stage_rom", lambda src: staged.append(src) or "staged_clean.gba")
    assert run._gen3_rom("b") == "staged_clean.gba"
    assert staged[0].endswith(duo.GEN3_CLEAN_RR_ROM)


def test_gen3_rr_battery_path_companion_kind_uses_the_pinned_saveram_name(tmp_path):
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.gcfg, run.cfg = dict(duo.GAMES["gen3_rr_new"]), dict(duo.SCENARIOS["faint_cmd_gen3"])
    run._saveram_dir = lambda inst: str(tmp_path)
    assert os.path.basename(run._gen3_battery_path("a")) == "slink RR.SaveRAM"


def test_gen3_rr_battery_path_clean_kind_computes_the_saveram_name(monkeypatch, tmp_path):
    """No hand-transcribed saveram name for the clean side: it is derived from whatever
    `_gen3_rom` actually staged (gen3_fixtures.saveram_name), avoiding a transcription error."""
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.gcfg, run.cfg = dict(duo.GAMES["gen3_rr_new"]), dict(duo.SCENARIOS["native_absent_gen3"])
    run._saveram_dir = lambda inst: str(tmp_path)
    monkeypatch.setattr(run, "_gen3_rom", lambda inst: "patch/build/gen3_Pokemon_-_Radical_Red.gba")
    path = run._gen3_battery_path("b")
    assert os.path.basename(path) == "gen3 Pokemon - Radical Red.SaveRAM"


# ── the driver files: symbols, paths and helpers they name exist ──────────────────────────
DRIVER = REPO / "lua" / "tests" / "duo" / "duo_gen3_main.lua"
SCRIPTED = REPO / "lua" / "tests" / "gen3_scripted_play.lua"


def test_every_scenario_has_its_module_and_runner_half():
    row = duo.GAMES["gen3_frlg"]
    for name in GEN3:
        base = name[:-len("_gen3")]
        assert (REPO / "lua" / "tests" / "duo" / f"scenario_{row['scenario_prefix']}{base}.lua").is_file(), name
        assert callable(getattr(duo.DuoRun, f"orchestrate_{name}", None)), name


def test_every_rr_only_scenario_has_its_module_oracle_and_runner_half():
    """P5 (card C5-5): explode_gen3/rival_swap_gen3/native_absent_gen3, on gen3_rr_new."""
    row = duo.GAMES["gen3_rr_new"]
    for name in GEN3_RR_ONLY:
        base = name[:-len("_gen3")]
        assert (REPO / "lua" / "tests" / "duo" / f"scenario_{row['scenario_prefix']}{base}.lua").is_file(), name
        assert callable(getattr(duo.DuoRun, f"orchestrate_{name}", None)), name
        oracle = duo.SCENARIOS[name]["oracle"]
        assert oracle == f"assert_{name}_saved" and callable(getattr(duo.DuoRun, oracle, None)), name
        assert duo.SCENARIOS[name]["games"] == ("gen3_rr_new",), name


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_every_pret_symbol_the_driver_reads_exists(title):
    text = DRIVER.read_text(encoding="utf-8")
    names = re.findall(r'"(\w+)"', re.search(r"local SYMS = \{(.*?)\}", text, re.S).group(1))
    syms = {line.split()[-1] for line in (REPO / "data" / "gen3" / "pret" / f"poke{title}.sym")
            .read_text(encoding="utf-8").splitlines() if len(line.split()) == 4}
    assert names and not [n for n in names if n not in syms]


def test_the_scripted_play_exports_and_paths_the_driver_uses_exist():
    text = DRIVER.read_text(encoding="utf-8") + "".join(
        p.read_text(encoding="utf-8") for p in (REPO / "lua" / "tests" / "duo").glob("scenario_gen3_*.lua"))
    scripted = SCRIPTED.read_text(encoding="utf-8")
    exports = scripted[scripted.rindex("\nreturn {"):]
    for name in set(re.findall(r"\bSP\.(\w+)", text)):
        assert re.search(rf"\b{name}\s*=", exports), f"gen3_scripted_play does not export {name}"
    paths = scripted[scripted.index("local PATHS = {"):scripted.index("local H = {")]
    used = set(re.findall(r'(?:follow\(cp, |reversed\()"(\w+)"', text)) - {"pc_to_pokecenter_entrance"}
    for name in used:
        assert re.search(rf"^\s+{name} = \{{", paths, re.M), f"no PATHS entry {name}"
    for dest in set(re.findall(r"SP\.DEST\.(\w+)", text)):
        assert re.search(rf"\b{dest} = \{{", scripted), f"no DEST {dest}"


# ── the scenario modules' control flow, under lupa with a fake ctx ─────────────────────────
# Not the game: every ctx primitive answers "it worked". What this catches is a Lua slip (a nil
# call, a misspelt ctx field, a branch that never returns) and the markers each half logs, which
# are exactly what the runner and the oracles read.
_FAKE_CTX = r"""
function FAKE(scenario, player, phase, spec)
    spec = spec or {}
    local logs = {}
    local party = { { slot = 0, key = "K0", hp = 5, max_hp = 20, species = 7, level = 9 },
                    { slot = 1, key = "K1", hp = 5, max_hp = 17, species = 16, level = 4 },
                    { slot = 2, key = "K9", hp = 9, max_hp = 9, species = 19, level = 3 } }
    local ctx = { player = player, phase = phase, fmt = string.format, cp = {}, finished = "done",
                  D = {}, hp0_tag = "FORCED_HP0" }
    ctx.log = function(s) logs[#logs + 1] = tostring(s) end
    ctx.frames = function() end
    ctx.wait_until = function(pred) return pred() end
    ctx.mash_until = function(pred) return pred() end
    ctx.wait_go = function() return true end
    ctx.go_has = function() return true end
    ctx.linked = function() return spec.linked or "K1" end
    ctx.partner_done = function() return true end
    ctx.party = function() return party end
    local gone = {}   -- a mirrored deposit leaves the party until the mirrored withdraw
    ctx.find = function(k) for _, m in ipairs(party) do if m.key == k and not gone[k] then return m end end end
    ctx.sent = function(event) if event == "box_mon_failed" or event == "sync_retrieve_failed" then return 0 end return spec.sent or 1 end
    ctx.received = function(cmd) if cmd == "force_faint" and player == "a" then return 0 end return 1 end
    ctx.wait_sent = function(event, key)
        if event == "stats_cache" then gone[key] = true end
        if event == "sync_retrieve_done" then gone[key] = nil end
        return true
    end
    ctx.wait_received = function() return spec.received ~= false end
    ctx.last_sent = function(event)
        if event == "rival_team_replaced" then return spec.rival_reply or { error = "refresh_failed" } end
        return { area_id = "route_1", species_id = 16 }
    end
    ctx.await_turn = function() return spec.turn or "action" end
    ctx.zero_hp = function() return spec.zero_hp_ok ~= false end
    ctx.hp0 = function() return spec.hp0 end
    ctx.battle_hold = function() return { why = "active battler" } end
    ctx.save = function() return true end
    ctx.catch = function() return "K9" end
    ctx.hunt = function() return true end
    ctx.run_away = function() return true end
    ctx.lose_active = function() return true end
    ctx.switch_to = function() return true end
    ctx.in_battle = function() return false end
    ctx.battler_slot = function() return 0 end
    ctx.walk_to_pc = function() end
    ctx.walk_pc_to_grass = function() end
    ctx.pc_deposit = function() return spec.linked or "K1" end
    ctx.pc_withdraw = function() return spec.linked or "K1" end
    ctx.try = function(fn, ...) return pcall(fn, ...) end
    ctx.writes = function() return spec.writes or 0 end
    ctx.wrong_save_hud = function() return true end
    ctx.SP = { verify_fight_cursor = function() return "fight" end }
    ctx.play = { fight_through = function() return true end, wait_scene_settled = function() return true end,
                 where = function() return "here" end }
    local fn = dofile(SCENARIO_DIR .. "/scenario_gen3_" .. scenario .. ".lua")
    local ok, pass, msg = pcall(fn, ctx)
    return ok, pass, tostring(ok and msg or pass), table.concat(logs, "\n")
end
"""


@pytest.fixture(scope="module")
def lua():
    from lupa import LuaRuntime

    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().SCENARIO_DIR = str(REPO / "lua" / "tests" / "duo").replace("\\", "/")
    runtime.execute(_FAKE_CTX)
    return runtime


def _run_module(lua, scenario, player, phase, spec):
    """spec values: str -> Lua string, "lua:<expr>" -> that Lua expression, int -> number."""
    fields = []
    for key, value in spec.items():
        if isinstance(value, str) and value.startswith("lua:"):
            fields.append(f"{key} = {value[4:]}")
        elif isinstance(value, str):
            fields.append(f'{key} = "{value}"')
        else:
            fields.append(f"{key} = {value}")
    return lua.globals().FAKE(scenario, player, phase, lua.eval("{" + ", ".join(fields) + "}"))


@pytest.mark.parametrize("scenario, player, phase, spec, markers", [
    ("faint_cmd", "a", "initial", {}, ["READY K1"]),
    ("faint_cmd", "b", "initial", {"hp0": "lua:{frame=1,in_battle=false}"}, ["READY K1"]),
    ("linked_faint_active", "a", "initial", {"linked": "K0"}, ["LINKED_FAINTED K0"]),
    ("linked_faint_active", "b", "initial",
     {"linked": "K0", "hp0": "lua:{frame=9,in_battle=true,battler=false}"},
     ["READY_ACTIVE K0", "ACTIVE_HOLD K0 why=active battler", "SWITCHED_OUT K0",
      "BENCH_HP0_IN_BATTLE K0"]),
    ("boxsync", "a", "initial", {}, ["DEPOSITED K1", "WITHDRAWN K1"]),
    ("boxsync", "b", "initial", {}, ["MIRROR_DEPOSITED K1", "MIRROR_WITHDRAWN K1"]),
    ("whiteout", "a", "initial", {}, ["DEPOSITED_FOR_REBUILD K1", "WHITED_OUT at here"]),
    ("whiteout", "b", "initial", {}, ["DEPOSITED_FOR_REBUILD K1", "MIRROR_WITHDRAWN K1"]),
    ("link", "a", "initial", {}, ["CAUGHT K9"]),
    ("deadzone", "a", "initial", {}, ["NO_CATCH area=route_1 species=16"]),
    ("deadzone", "b", "initial", {"hp0": "lua:{frame=1,in_battle=false}"}, ["CAUGHT K9", "RETIRED K9"]),
    ("reconnect", "b", "initial", {}, ["RECONNECT_READY b"]),
    ("reconnect", "a", "same_save", {}, ["RECONNECT_HELLO same_save count=1"]),
    ("reconnect", "a", "wrong_save", {}, ["RECONNECT_HELLO wrong_save count=1"]),
    # RR-only (P5, card C5-5): explode is not covered here (its B half polls raw memory/joypad
    # globals this harness does not stub -- see the card's final report).
    ("rival_swap", "b", "initial", {}, ["READY_IN_BATTLE"]),
    ("rival_swap", "a", "initial", {}, []),
    ("native_absent", "a", "initial", {}, ["PROBE_SETTLED writes=0"]),
    ("native_absent", "b", "initial", {}, ["PROBE_SETTLED writes=0"]),
])
def test_scenario_modules_run_their_happy_path(lua, scenario, player, phase, spec, markers):
    ok, passed, msg, logs = _run_module(lua, scenario, player, phase, spec)
    assert ok, msg
    assert passed is True, msg
    for marker in markers:
        assert marker in logs, (marker, logs)


@pytest.mark.parametrize("scenario, player, phase, spec, reason", [
    ("linked_faint_active", "b", "initial", {"linked": "K0"}, "never reached HP 0 in battle"),
    ("faint_cmd", "b", "initial", {}, "never took K1 to HP 0"),
    ("reconnect", "a", "wrong_save", {"writes": 2}, "wrote 2 time(s)"),
    ("reconnect", "a", "initial", {}, "the runner never killed A"),
    ("rival_swap", "b", "initial", {"turn": "party"}, "never reached the action menu"),
    ("rival_swap", "b", "initial", {"rival_reply": "lua:{error='ok'}"}, "expected error=refresh_failed"),
    ("native_absent", "b", "initial", {"received": "lua:false"}, "probe never arrived"),
])
def test_scenario_modules_fail_with_a_named_reason(lua, scenario, player, phase, spec, reason):
    ok, passed, msg, _ = _run_module(lua, scenario, player, phase, spec)
    assert ok and passed is False and reason in msg, msg
