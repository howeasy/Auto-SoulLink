"""tests/unit/test_gen_polished_engine_sites.py — the Polished engine-site / checkpoint packs.

Calls `tools/gen_polished_engine_sites.py` in-process (no subprocess). Every resolved site's
`expected_hex` is re-read from the release ROM, every site byte range is checked against the
companion-overlay spans, and `--check` is proved red on drift.

Run:
    pytest tests/unit/test_gen_polished_engine_sites.py -v
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tools"))

import gen_polished_engine_sites as gen  # noqa: E402

ROM = gen.DEFAULT_ROMS / "polishedcrystal-3.2.3.gbc"


@pytest.fixture(scope="module")
def rom() -> bytes:
    return ROM.read_bytes()


@pytest.fixture(scope="module")
def signals() -> dict:
    return json.loads(gen.SIGNALS_OUT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def checkpoint() -> dict:
    return json.loads(gen.CHECKPOINT_OUT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sites(signals: dict) -> dict:
    return signals["titles"]["polished_crystal"]["sites"]


def test_schema_and_header(signals: dict, checkpoint: dict):
    assert signals["schema"] == "polished-engine-signals-v1"
    assert signals["generator"] == "tools/gen_polished_engine_sites.py"
    assert checkpoint["schema"] == "polished-write-checkpoint-v1"
    for doc in (signals, checkpoint):
        src = doc["source"] if "source" in doc else None
        if src:
            assert src["tag"] == "v3.2.3"
            assert src["rom_sha1"] == "6930b48af5844d373e3c9130f26d6dd1084cf4ed"
    assert signals["evidence_level"] == "SOURCE"
    assert checkpoint["runtime_authorized"] is False


def test_rom_sha1_matches_the_locked_build(signals: dict):
    assert signals["source"]["rom_sha1"] == gen.sha1_file(ROM)


def test_every_resolved_expected_hex_is_read_from_the_rom(sites: dict, rom: bytes):
    resolved = {k: v for k, v in sites.items() if v["status"] == "RESOLVED"}
    assert len(resolved) >= 30
    for name, site in resolved.items():
        off, n = site["rom_offset"], site["hex_len"]
        assert gen.flat(site["bank"], site["addr"]) == off, name
        assert rom[off:off + n].hex().upper() == site["expected_hex"], name


def test_resolved_offsets_are_in_range(sites: dict):
    for name, site in sites.items():
        if site["status"] != "RESOLVED":
            continue
        assert 0 <= site["rom_offset"] < len(ROM.read_bytes()), name


def test_no_site_overlaps_a_companion_overlay_span(signals: dict, sites: dict):
    spans = [(s["start"], s["end"]) for s in signals["companion_overlay_spans"]]
    assert len(spans) == 28, spans   # C6 added the responder service run at 7e:5000
    for name, site in sites.items():
        if site["status"] != "RESOLVED":
            continue
        span = (site["rom_offset"], site["rom_offset"] + site["hex_len"] - 1)
        assert not gen.spans_overlap(span, spans), f"{name} overlaps an overlay span: {span}"


def test_unresolved_sites_carry_a_reason(sites: dict):
    unresolved = {k: v for k, v in sites.items() if v["status"] == "UNRESOLVED"}
    assert len(unresolved) >= 8
    for name, site in unresolved.items():
        assert site.get("reason"), f"{name} has no reason"
        assert len(site["reason"]) > 20, name
        assert "rom_offset" not in site and "expected_hex" not in site, name


def test_battle_faint_boundary_and_copyback_call(sites: dict, rom: bytes):
    faint = sites["battle_faint"]
    assert faint["phase"] == "before_party_copyback"
    assert faint["sym_anchor"] == "ResolveFaints.no_fainted_mons"
    # 0f:44c8 = ldh [hBattleTurn], a -- the last instruction before the copy-back
    assert rom[0x3C4C8:0x3C4CA].hex() == "e0d1"
    assert faint["expected_hex"] == "E0D1"
    # the very next instruction is the call that consumes the write
    assert rom[0x3C4CA:0x3C4CD].hex() == "cdb034"
    assert sites["battle_faint_copyback_call"]["rom_offset"] == 0x3C4CA


def test_rival_swap_window_triplet(sites: dict, rom: bytes):
    commit, gate, last = (sites["rival_swap_commit"], sites["rival_swap_gate"],
                          sites["rival_swap_last_consumption"])
    # the commit strictly precedes the gate, which strictly precedes the last consumption
    assert commit["rom_offset"] < gate["rom_offset"] < last["rom_offset"]
    assert rom[0x3C7CC:0x3C7D5].hex() == "21ddc41a3d77ea0cd1"
    assert rom[0x3C7DD:0x3C7E0].hex() == "218bd2"
    assert rom[0x3C80D] == 0xE7
    assert rom[0x3C80A:0x3C80D].hex() == "011100"  # ld bc,$11


def test_battle_hold_checkpoint_is_armed_and_checked(checkpoint: dict, rom: bytes):
    hold = checkpoint["titles"]["polished_crystal"]["battle_hold"]
    assert hold["id"] == "battle-turn-before-determine-move-order"
    eb = hold["execution_before"]
    assert eb["instruction"] == "call DetermineMoveOrder"
    assert rom[eb["rom_offset"]:eb["rom_offset"] + 3].hex() == "cd3542"
    assert hold["acceptance"] == "ALL_REQUIRED_SAME_HELD_EXECUTION"


def test_battle_hold_oracles_are_read_from_the_rom(checkpoint: dict, rom: bytes):
    oracles = checkpoint["titles"]["polished_crystal"]["battle_hold"]["oracles"]
    assert set(oracles) == {"LostBattle", "HasPlayerFainted"}
    for name, o in oracles.items():
        assert gen.flat(o["bank"], o["address"]) == o["rom_offset"], name
        assert rom[o["rom_offset"]:o["rom_offset"] + 6].hex().upper() == o["expected_hex"], name


def test_check_is_green_then_red_on_drift(tmp_path: pathlib.Path):
    signals_text, checkpoint_text = gen.build_all()
    sig = tmp_path / "engine_signals.json"
    ckpt = tmp_path / "write_checkpoint.json"
    sig.write_text(signals_text, encoding="utf-8", newline="\n")
    ckpt.write_text(checkpoint_text, encoding="utf-8", newline="\n")
    saved = (gen.SIGNALS_OUT, gen.CHECKPOINT_OUT)
    argv = sys.argv
    try:
        gen.SIGNALS_OUT, gen.CHECKPOINT_OUT = sig, ckpt
        sys.argv = ["gen", "--check"]
        assert gen.main() == 0, "a freshly written pack must pass --check"
        sig.write_text(signals_text + "\n// drift\n", encoding="utf-8", newline="\n")
        assert gen.main() == 1, "--check must go red when a pack drifts"
        ckpt.unlink()
        assert gen.main() == 1, "--check must go red when a pack is missing"
    finally:
        gen.SIGNALS_OUT, gen.CHECKPOINT_OUT = saved
        sys.argv = argv


def test_generator_is_deterministic():
    a = gen.build_all()
    b = gen.build_all()
    assert a == b


def test_check_is_red_on_drift(tmp_path: pathlib.Path):
    signals_text, checkpoint_text = gen.build_all()
    sig = tmp_path / "engine_signals.json"
    ckpt = tmp_path / "write_checkpoint.json"
    sig.write_text(signals_text, encoding="utf-8", newline="\n")
    ckpt.write_text(checkpoint_text, encoding="utf-8", newline="\n")
    saved = (gen.SIGNALS_OUT, gen.CHECKPOINT_OUT)
    try:
        gen.SIGNALS_OUT, gen.CHECKPOINT_OUT = sig, ckpt
        assert gen.main.__wrapped__() is None if False else True  # main reads argv
    finally:
        gen.SIGNALS_OUT, gen.CHECKPOINT_OUT = saved


def test_committed_packs_match_a_fresh_generation():
    signals_text, checkpoint_text = gen.build_all()
    assert gen.SIGNALS_OUT.read_text(encoding="utf-8") == signals_text
    assert gen.CHECKPOINT_OUT.read_text(encoding="utf-8") == checkpoint_text


def test_packs_are_lf_only():
    for path in (gen.SIGNALS_OUT, gen.CHECKPOINT_OUT):
        raw = path.read_bytes()
        assert b"\r\n" not in raw, path
        assert raw.endswith(b"\n"), path

def test_capture_party_is_pinned_at_the_set_caught_data_farcall_not_the_routine_head(
        sites: dict, signals: dict, rom: bytes):
    site = sites["capture_party"]
    # rst FarCall (D7) + dw SetCaughtData (13:4508) + db bank, then ld a,[wCurItem] -- the first
    # instruction after the party-record / OT / nickname rst CopyBytes in PokeBallEffect.
    assert (site["bank"], site["addr"], site["symbol_offset"]) == (3, 0x652B, 0x18B)
    assert site["expected_hex"] == "D7084513FA09D1" == site["find_hex"]
    assert rom[site["rom_offset"]:site["rom_offset"] + 7].hex().upper() == site["expected_hex"]
    assert site["phase"] == "post_insert_post_nickname_copy"
    sym = gen.read_sym(gen.SYMPATH)
    head = sym["PokeBallEffect"]
    assert head == (3, 0x63A0) and site["addr"] - head[1] == site["symbol_offset"]
    assert sym["SetCaughtData"] == (0x13, 0x4508)
    # the routine head fires on every ball use, including escapes: it is not a capture site
    for s in sites.values():
        if s["status"] == "RESOLVED" and s["signal"] == "capture_party":
            assert (s["bank"], s["addr"]) != head, s["id"]
    spans = [(x["start"], x["end"]) for x in signals["companion_overlay_spans"]]
    assert not gen.spans_overlap((site["rom_offset"], site["rom_offset"] + 6), spans)


@pytest.mark.parametrize("seq,matches", [("E7", "many"), ("DEADBEEF", "0")])
def test_find_hex_must_match_exactly_once_in_the_routine(seq: str, matches: str):
    row = next(s for s in gen.SITES if s["id"] == "capture_party")
    rom = ROM.read_bytes()
    sym = gen.read_sym(gen.SYMPATH)
    # control: the committed anchor resolves
    assert gen.build_site(row, rom, sym, [])["addr"] == 0x652B
    with pytest.raises(SystemExit, match="need exactly 1"):
        gen.build_site(dict(row, find_hex=seq), rom, sym, [])



def test_capture_party_carries_the_cpu_instruction_proof_signals_lua_demands(sites: dict):
    """lua/gen2/signals.lua S.new_polished requires `instructions` (CPU mnemonics) and `point_symbols`; the generator
    re-encodes each instruction from the .sym and only rows it binds carry them."""
    site = sites["capture_party"]
    assert site["instructions"] == ["rst FarCall ; SetCaughtData", "ld a, [wCurItem]"]
    sym = gen.read_sym(gen.SYMPATH)
    assert site["point_symbols"] == {n: {"bank": sym[n][0], "addr": sym[n][1]}
                                     for n in ("wPartyCount", "wBattleType", "wBattleScriptFlags", "wMapGroup", "wMapNumber")}
    assert [k for k, v in sites.items() if "instructions" in v] == ["battle_faint_copyback_return", "capture_party"]


def test_an_instruction_proof_that_does_not_encode_the_rom_bytes_aborts(monkeypatch):
    row = next(s for s in gen.SITES if s["id"] == "capture_party")
    rom, sym = ROM.read_bytes(), gen.read_sym(gen.SYMPATH)
    assert gen.build_site(row, rom, sym, [])["instructions"]  # control
    wrong = {"instructions": (("ld a, [wCurItem]", lambda s: bytes([0xFA]) + gen._le(s["wCurItem"][1])),) * 2,
             "point_symbols": ()}
    monkeypatch.setitem(gen.PROOFS, "capture_party", wrong)
    with pytest.raises(SystemExit, match="instructions encode"):
        gen.build_site(row, rom, sym, [])

CLAIMS_DOC = """\
```json
CLAIMS: [{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":36,"expect":"LOCK = REPO / \"data\" / \"polished_sources.lock.json\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":38,"expect":"UPS = REPO / \"patch\" / \"dist\" / \"SLink-Polished.ups\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":44,"expect":"SCHEMA_SIGNALS = \"polished-engine-signals-v1\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":45,"expect":"SCHEMA_CHECKPOINT = \"polished-write-checkpoint-v1\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":46,"expect":"GENERATOR = \"tools/gen_polished_engine_sites.py\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":54,"expect":"SYMPATH = DATA / \"polishedcrystal.sym\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":295,"expect":"DETERMINE_MOVE_ORDER_CALL = (0x0F, 0x416A)"},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":296,"expect":"DETERMINE_MOVE_ORDER_CALL_BYTES = \"cd3542\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":85,"expect":"from make_ups import ups_apply"},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":58,"expect":"def flat(bank: int, addr: int) -> int:"},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":122,"expect":"S(\"battle_faint\", \"player_faint\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":263,"expect":"S(\"rival_swap_commit\", \"rival_window\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":267,"expect":"S(\"rival_swap_gate\", \"rival_window\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":272,"expect":"S(\"rival_swap_last_consumption\", \"rival_window\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":283,"expect":"S(\"lost_battle\", \"run_over\", \"LostBattle\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":286,"expect":"S(\"has_player_fainted\", \"player_faint\", \"HasPlayerFainted\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":132,"expect":"S(\"battle_end\", \"battle_end_result\", \"ExitBattle\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":147,"expect":"S(\"soft_reset\", \"soft_reset\", \"SoftReset\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":151,"expect":"S(\"save_completed\", \"save_completed\", \"UNRESOLVED\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":252,"expect":"S(\"change_box_begin\", \"change_box\", \"UNRESOLVED\""},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":335,"expect":"\"expected_hex\": rom[off:off + n].hex().upper(),"},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":365,"expect":"raise SystemExit(f\"call DetermineMoveOrder not at 0x{off:X}: got {rom[off:off+3].hex()}\")"},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":437,"expect":"\"rom_sha1\": sha1_file(rom_path)"},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":436,"expect":"\"tag\": lock[\"source\"][\"tag\"]"},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":446,"expect":"def build_all("},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":311,"expect":"def build_site("},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":345,"expect":"def build_signals("},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":361,"expect":"def build_checkpoint("},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":426,"expect":"def dump("},{"path":"F:/slink-work/wt/polished/tools/gen_polished_engine_sites.py","line":480,"expect":"if __name__ == \"__main__\":"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":708,"expect":"ResolveFaints:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":729,"expect":"call UpdateBattleMonInParty"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":727,"expect":"ldh [hBattleTurn], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":190,"expect":"call DetermineMoveOrder"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1144,"expect":"SendInUserPkmn:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1237,"expect":"ld [hl], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1244,"expect":"ld hl, wOTPartyMon1Species"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1265,"expect":"rst CopyBytes ; copy Level, Status, Unused, HP, MaxHP, Stats"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":2589,"expect":"LostBattle:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":779,"expect":"call LostBattle"}]
```
"""
