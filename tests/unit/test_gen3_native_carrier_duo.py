"""Native FR/LG carrier input/oracle controls, without launching an emulator."""

import copy
import hashlib
import json
import struct
import tempfile
from pathlib import Path

import pytest

from tools import gen3_trade_duo as t5

ROOT = Path(__file__).resolve().parents[2]


def carrier_rows(manifest, side, decline=False):
    """Independent MODEL bytes matching the documented C structs and server protocol."""
    rows, epoch = [], 7

    def add(kind, raw=None, **fields):
        row = {"kind": kind, **fields}
        if raw is not None:
            row["raw"] = bytes(raw)
        rows.append(row)

    def packet(op, seq, state, result=0):
        raw = bytearray(547)
        struct.pack_into("<IHHHHH", raw, 0, 0x4B4E4C53, 2, op if state == "post" else 0,
                         seq, 1 if state == "enter" else 2, seq if state == "done" else seq-1)
        struct.pack_into("<II", raw, 64, 23, epoch)
        struct.pack_into("<IHHB", raw, 160, epoch, seq, op, int(state == "enter"))
        raw[48] = result
        if op == 22:
            raw[16] = raw[169] = 1
        raw[170:426] = t5.codec.encode_name("Trade?", 256)
        options = b"\x02" + t5.codec.encode_name("Trade", 6) + t5.codec.encode_name("Say hey", 8)
        raw[426:426+len(options)] = options
        struct.pack_into("<I", raw, 540, manifest["carrier"]["field_callback"])
        raw[545] = 2
        return raw

    if side == "a":
        edge = bytearray(614)
        struct.pack_into("<II", edge, 0, epoch, 0)
        struct.pack_into("<II", edge, 16, epoch, 1)
        edge[24] = 1
        edge[32] = 0x81
        edge[32+9:32+11] = bytes([4, 5])
        edge[32+24] = 2
        struct.pack_into("<hh", edge, 32+16, 10, 11)
        edge[68] = 1
        edge[68+8:68+11] = bytes([241, 4, 5])
        struct.pack_into("<hh", edge, 68+16, 10, 10)
        add("npc_edge", edge)
        add("tx", message={"event": "trade_request"})
    for seq, op in enumerate((22, 20) if side == "a" else (17,), 1):
        command = {22: "show_choices", 20: "choose_mon", 17: "show_menu"}[op]
        add("rx", message={"cmd": command, "text": "Trade?", "options": ["Trade", "Say hey"], "token": "t1"})
        add("ui_post", packet(op, seq, "post"), op=op, seq=seq)
        add("ui_enter", packet(op, seq, "enter"), op=op, seq=seq)
        if op == 20:
            chooser = packet(op, seq, "enter")
            struct.pack_into("<I", chooser, 540, manifest["hooks"]["CB2_InitPartyMenu"] | 1)
            add("chooser_entry", chooser)
        result = 1 if op == 20 else 0 if op == 22 or decline else 1
        add("ui_done", packet(op, seq, "done", result), op=op, seq=seq)
        add("tx", message={"event": "mon_chosen" if op == 20 else "menu_result", "token": "t1",
                           "slot" if op == 20 else "choice": result})
    add("native_carrier_complete", title=manifest["title"])
    return rows


@pytest.mark.parametrize("side,decline", [("a", False), ("b", False), ("a", True), ("b", True)])
def test_carrier_oracle_requires_native_ownership_results_and_wire_order(side, decline):
    from tests.unit.test_gen3_trade_duo import model_manifest

    manifest = model_manifest()
    rows = carrier_rows(manifest, side, decline)
    def check(data):
        return t5.carrier_problems(data, manifest, side, lambda row: row["raw"], decline=decline)
    assert check(rows) == []
    targets = [(r["kind"], r.get("op")) for r in rows if "raw" in r]
    for kind, op in targets:
        broken = copy.deepcopy(rows)
        broken.remove(next(r for r in broken if r["kind"] == kind and r.get("op") == op))
        assert check(broken), (kind, op)
    assert check(rows) == [], "reverting each missing witness restores the control"
    assert t5.carrier_problems(rows, manifest, side, lambda r: r["raw"], decline=decline,
                              trade_epoch=8)
    assert t5.carrier_problems(rows, manifest, side, lambda r: r["raw"], decline=decline,
                              trade_token="other-token")


@pytest.mark.parametrize("kind,offset", [
    ("ui_post", 0), ("ui_post", 6), ("ui_enter", 64), ("ui_done", 8),
    ("ui_post", 16), ("ui_enter", 169),
    ("npc_edge", 20), ("npc_edge", 56), ("ui_enter", 160), ("ui_enter", 168),
    ("ui_enter", 170), ("ui_enter", 426), ("ui_done", 12), ("ui_done", 48),
    ("ui_done", 544), ("chooser_entry", 540),
])
def test_carrier_oracle_rejects_altered_raw_bytes_and_revert_passes(kind, offset):
    from tests.unit.test_gen3_trade_duo import model_manifest

    manifest = model_manifest()
    rows = carrier_rows(manifest, "a")
    row = next(r for r in rows if r["kind"] == kind)
    raw = row["raw"]
    changed = bytearray(raw)
    changed[offset] ^= 1
    row["raw"] = bytes(changed)
    assert t5.carrier_problems(rows, manifest, "a", lambda r: r["raw"])
    row["raw"] = raw
    assert t5.carrier_problems(rows, manifest, "a", lambda r: r["raw"]) == []


@pytest.mark.parametrize("titles", [("firered", "leafgreen"), ("leafgreen", "firered")])
def test_pair_preflight_binds_each_title_and_shared_run_without_reusing_rom_facts(titles):
    for title in titles:
        if not (ROOT / f"patch/build/candidate-{title}-trade/receipt.json").exists():
            pytest.skip(f"private {title} native carrier candidate absent")
    with tempfile.TemporaryDirectory(prefix="t5-pair-", dir=ROOT / "patch/build") as directory:
        pair = t5.prepare_pair(ROOT, Path(directory), dict(zip("ab", titles, strict=True)))
        a, b = pair["players"]["a"], pair["players"]["b"]
        assert (a["title"], b["title"]) == titles
        assert a["rom_sha1"] != b["rom_sha1"]
        assert a["hooks"]["TrySavingData"] != b["hooks"]["TrySavingData"]
        assert a["hooks"]["CB2_InitPartyMenu"] != b["hooks"]["CB2_InitPartyMenu"]
        assert a["nonce"] == b["nonce"] == pair["nonce"]
        assert a["journal_path"] == b["journal_path"]
        for side, manifest in pair["players"].items():
            assert manifest["player"] == side and manifest["carrier_mode"] == "native"
            t5.validate_prepared(ROOT, manifest)
            fixture = (ROOT / pair["fixtures"][side]["path"]).read_bytes()
            assert t5.codec.party_from_save(fixture)[1]["species"] == 64


def test_the_pair_is_firered_against_leafgreen_not_one_candidate_used_twice():
    """The card claimed "Both sides use the same private FireRed candidate". That is a
    different, wrong lane: prepare_pair refuses any title pair that is not exactly
    {firered, leafgreen}, so each side gets its own ROM SHA-1, pret symbols and detours.

    test_pair_preflight... asserts the two manifests' rom_sha1 really differ, but it
    skips without the private candidate builds (patch/build/ is not committed), so the
    contract that MAKES them differ is pinned here where it always runs."""
    from tools import e2e_duo

    sides = e2e_duo.GAMES["gen3_fr_trade"]["sides"]
    assert (sides["a"][0], sides["b"][0]) == ("firered", "leafgreen")
    for pair in ({"a": "firered", "b": "firered"}, {"a": "leafgreen", "b": "leafgreen"}):
        with pytest.raises(ValueError, match="both FR and LG"):
            t5.prepare_pair(ROOT, ROOT / "patch/build", pair)


@pytest.mark.parametrize("decline,wrong_answer", [(False, False), (True, False), (True, True)])
def test_offer_driver_uses_only_joypad_and_refuses_a_wrong_native_answer(decline, wrong_answer):
    from lupa import lua54

    from tests.unit.test_gen3_trade_duo import model_manifest

    lua = lua54.LuaRuntime(unpack_returned_tuples=True)
    driver = lua.execute((ROOT / "lua/tests/duo/gen3_trade_driver.lua").read_text())
    manifest = model_manifest()
    c = manifest["carrier"]
    commands, answers = [], []

    def press(keys):
        buttons = list(keys.keys())
        commands.extend(buttons)
        if buttons and not answers:
            answers.append(int(not decline) ^ int(wrong_answer))

    def wait(predicate, *_):
        return any(predicate() for _ in range(64))

    lua.globals().joypad = lua.table(set=press)
    lua.globals().memory = lua.table(
        read_u8=lambda address, *_: int(address == c["state"]+8),
        read_u16_le=lambda address, *_: 17 if address == c["state"]+6 else 0,
        read_u32_le=lambda *_: 0,
    )
    ctx = lua.table(player="b", D=lua.table(native_decline=decline),
                    sent=lambda *_: len(answers), wait_received=lambda *_: True, wait_until=wait,
                    last_sent=lambda *_: lua.table(choice=answers[-1]), log=lambda *_: None)
    h = lua.table(manifest=lua.table_from(manifest, recursive=True), carrier_complete=lambda: True)
    if wrong_answer:
        with pytest.raises(lua54.LuaError, match="wrong native offer answer"):
            driver.select(ctx, h)
    else:
        assert driver.select(ctx, h)
    assert commands == ["B" if decline else "A"]


def test_receipt_archive_preserves_bytes_and_refuses_another_runs_nonce(tmp_path):
    from tools.e2e_duo import DuoRun

    run = DuoRun.__new__(DuoRun)
    run.data_dir = str(tmp_path / "run")
    run._native_candidate = {"nonce": "ab" * 16}
    run._phase_result_path = lambda side, phase: str(tmp_path / f"{side}_{phase}.txt")
    body = ("T5 " + json.dumps({"kind": "override", "side": "a", "phase": "initial",
                               "value": "ab" * 16}) + "\r\nT5 {partial").encode()
    (tmp_path / "a_initial.txt").write_bytes(body)
    (tmp_path / "b_initial.txt").write_bytes(body.replace(b'"a"', b'"b"').replace(b"abab", b"cdcd"))
    run._archive_native_receipts()
    archive = Path(run.data_dir) / "receipts"
    assert (archive / "a_initial.txt").read_bytes() == body
    assert not (archive / "b_initial.txt").exists()
    assert json.loads((archive / "sha256.json").read_text()) == {
        "a_initial.txt": hashlib.sha256(body).hexdigest()
    }
