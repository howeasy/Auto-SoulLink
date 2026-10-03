"""Gen 3 write-ownership guard (P4 card C4-5, docs/gen3/PLAN.md §5.7/§10, p4_gen1_contract_map
.md §4.3): every byte that reaches the cartridge must pass through lua/gen3/writes.lua's armed
sink -- never a raw BizHawk write call reached directly from the reducer or the box mover.

Two independent proofs:
  (a) STATIC: no `memory.write_*`/`io.write_*` call under lua/gen3/ or lua/core/ except inside
      lua/gen3/writes.lua (the sink itself) and lua/gen3/run.lua (the bootstrap, where exactly
      one `memory.write_u8` call is allowed: the one handed to Entry.build's `deps.io.write_u8`,
      the ONLY write sink production `Entry.build` accepts, `lua/gen3/entry.lua:227,260`).
      A revert-test plants a `memory.write_u8` in a scratch copy of client.lua and shows the
      scanner catches it -- a static test that cannot fail is worse than none
      (docs/gen3/research/p4_gen1_contract_map.md's own falsifier for this card).
  (b) DYNAMIC: a World run (tests/unit/gen3_world.py: a fake GBA bus over the PRODUCTION
      lua/gen3/entry.lua build) where every raw byte gen3_world.World's injected io.write_u8
      records is reconciled address-for-address, frame-for-frame, against writes.lua's own
      armed-write log -- an unlogged write proves a bypass even if the static scan somehow
      missed it. Exercised across an overworld box_mon/party_mon/memorialize round trip (the
      real lua/gen3/boxes.lua, not a double: PLAN's "the write log is corroboration, not proof"
      still wants boxes.lua's actual write_plan on this path, not the executor stub), a bench
      in-battle faint (battle_faint), a held battler landing at the overworld checkpoint after
      battle end (overworld), and RR's force_explode menu-skip commit (battle_commit).
  (c) The disabled-foundation write guard (PLAN §10): apply_trade on gen3_frlg (no trade path)
      writes nothing and sends no reply.

This is an INDEPENDENT check of lua/gen3/client.lua, lua/gen3/boxes.lua and lua/core/* (P4
cards C4-1/C4-2/C4-3): a defect found here is reported, not patched, by this card's charter.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.unit.gen3_world import World, key_of, mon_record

REPO = Path(__file__).resolve().parents[2]
GEN3_DIR = REPO / "lua" / "gen3"
CORE_DIR = REPO / "lua" / "core"
WRITES_LUA = GEN3_DIR / "writes.lua"
RUN_LUA = GEN3_DIR / "run.lua"

# A raw sink call: memory.write_u8/u16/u32(...) (the real BizHawk API) or io.write_u8/u16/u32(
# .../io_.write_u8(...) (the injected io table's sink, bypassing writes.lua). Deliberately does
# NOT match `writes:write_u8(...)`/`writes:write_bytes(...)` (colon calls on the *safe* wrapper
# writes.lua itself hands out) -- those are the whole point of this file existing.
RAW_SINK_RE = re.compile(r"\b(?:memory|io_?)\.write(?:_u8|_u16|_u32)?\s*\(")
BOOTSTRAP_PATTERN_RE = re.compile(
    r"write_u8\s*=\s*function\([^)]*\)\s*return\s+memory\.write_u8\(")


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def _lua_files():
    return sorted(GEN3_DIR.glob("*.lua")) + sorted(CORE_DIR.glob("*.lua"))


def _scan(path: Path, code: str) -> list[str]:
    """Raw-sink violations in `code` (already comment-stripped), attributed to `path`."""
    matches = list(RAW_SINK_RE.finditer(code))
    if not matches:
        return []
    if path == WRITES_LUA:
        return []                                   # the one file allowed to own the sink
    if path == RUN_LUA:
        # the ONE allowed bootstrap pattern: memory.write_u8 handed to the io table's
        # write_u8 field, nothing else.
        if len(matches) == 1 and BOOTSTRAP_PATTERN_RE.search(code):
            return []
        return [f"{path}: {len(matches)} raw sink call(s), not the one allowed bootstrap pattern"]
    return [f"{path}: {len(matches)} raw write sink call(s) outside writes.lua/run.lua"]


# ── (a) static ──────────────────────────────────────────────────────────────────────────────

def test_no_raw_write_sink_outside_writes_lua_and_runs_one_allowed_bootstrap_pattern():
    violations = []
    for path in _lua_files():
        violations += _scan(path, _strip_comments(path.read_text(encoding="utf-8")))
    assert not violations, "\n".join(violations)


def test_the_scanner_catches_a_planted_write_in_a_scratch_copy_of_client_lua(tmp_path):
    """Revert-test: a static check that cannot fail is worse than none (this card's own first
    falsifier, docs/gen3/research/p4_gen1_contract_map.md §4.3)."""
    original = (GEN3_DIR / "client.lua").read_text(encoding="utf-8")
    planted = original + '\nmemory.write_u8(0x02020000, 1, "System Bus") -- planted\n'
    scratch = tmp_path / "client.lua"
    scratch.write_text(planted, encoding="utf-8")

    assert _scan(GEN3_DIR / "client.lua", _strip_comments(original)) == []
    violations = _scan(scratch, _strip_comments(planted))
    assert violations, "the scanner did not catch a planted memory.write_u8 in client.lua"


def test_the_scanner_does_not_flag_the_safe_writes_wrapper_calls():
    """writes:write_u16(...)/writes:write_bytes(...) (client.lua) call INTO the armed sink via
    a colon method call, never bypass it; the scanner must not flag those as raw sinks."""
    code = _strip_comments('local ok = pcall(function() writes:write_u16(addr, v) end)\n'
                            'writes:write_bytes(addr, { v })\n')
    assert RAW_SINK_RE.search(code) is None


# ── World setup ─────────────────────────────────────────────────────────────────────────────

OT = 0x0000ABCD
A, B = 0x11111111, 0x22222222
KA, KB = key_of(A, OT), key_of(B, OT)
FOE = mon_record(0x77777777, 0x1234, species=19, level=3)


def _party(*pids, hp=20):
    return [mon_record(p, OT, species=4 + i, nickname=f"MON{i}", hp=hp) for i, p in enumerate(pids)]


def _live(pack="gen3_frlg", title="firered", kind=None, pids=(A, B), frames=60):
    w = World(pack, title, kind)
    w.set_party(_party(*pids))
    w.step_to(frames)
    return w


def _lua_list(t):
    return [t[i] for i in range(1, len(t) + 1)]


def _assert_every_raw_write_is_logged_and_armed(w, *, min_writes=1):
    """Every (addr, frame) gen3_world.World's injected io.write_u8 recorded (`w.writes`) falls
    inside the byte span of some writes.lua log entry (`w.parts.writes.log`) at the SAME frame
    -- not merely a count match, an address-for-address reconciliation. writes.lua only appends
    a log record after performing a write inside an armed, revalidated window
    (lua/gen3/writes.lua:26-45), so an unmatched raw write proves a byte reached the cartridge
    without ever being armed.
    """
    spans = [(int(r.frame), int(r.address), int(r.address) + int(r.len))
             for r in _lua_list(w.parts.writes.log)]
    for addr, _value, frame in w.writes:
        assert any(f == frame and lo <= addr < hi for f, lo, hi in spans), (
            f"raw write at 0x{addr:08X} frame {frame} has no matching writes.lua log entry "
            "-- it reached the cartridge without ever being armed")
    total_logged = sum(hi - lo for _, lo, hi in spans)
    assert total_logged == len(w.writes) >= min_writes, (
        f"{total_logged} bytes logged vs {len(w.writes)} bytes actually written")


def _seed_frlg_box_math(w):
    """The ROM data lua/gen3/boxes.lua's vanilla deposit/withdraw path needs beyond the site
    anchors gen3_world.World already seeds (BATTLE_MOVES_ADDR PP for moves 33/45, per its own
    __init__): the header code (for the per-game base-stats table lookup), one species' base
    stats (HP/Attack nonzero, growth rate < 6, species 4 to match _party()'s mon), and the
    PP-Up mask bytes. Experience-table thresholds are deliberately left zero-filled: unseeded
    thresholds never exceed a real mon's experience, so level_from_exp degrades to level=100
    (wrong, but not a crash) -- exact stat accuracy is lua/gen3/boxes.lua's own card (C4-3,
    tests/unit/test_gen3_boxes.py), not this write-ownership guard's concern.
    """
    w.rom[0xAC], w.rom[0xAD], w.rom[0xAE], w.rom[0xAF] = (ord(c) for c in "BPRE")
    base_addr = w.d["BASESTATS_ADDR_BY_GAME_CODE"]["BPRE"]
    entry_size = w.d["BASESTATS_ENTRY_SIZE"]
    stats = bytearray(entry_size)
    stats[0], stats[1] = 39, 52                        # hp, attack: nonzero
    stats[0x13] = 0                                    # growth rate: medium fast (< 6)
    species = 5                                        # _party(A, B)'s B is species 4+1
    for i, byte in enumerate(stats):
        w.rom[base_addr - 0x08000000 + species * entry_size + i] = byte
    mask_addr = w.profile["rom"]["PP_UP_GET_MASK_ADDR"]
    for i in range(4):
        w.rom[mask_addr - 0x08000000 + i] = 0x03


# ── (b) dynamic ─────────────────────────────────────────────────────────────────────────────

def test_a_real_overworld_box_deposit_withdraw_and_memorialize_round_trip_is_fully_logged():
    w = _live(pids=(A, B))
    _seed_frlg_box_math(w)
    assert w.parts.boxes is not None, "no production lua/gen3/boxes.lua bound"

    w.command(cmd="box_mon", key=KB)
    w.step()
    assert w.events("box_mon_failed") == [], "the seeded deposit refused: " + repr(w.sent[-3:])
    (cache,) = w.events("stats_cache")
    assert cache["key"] == KB
    _assert_every_raw_write_is_logged_and_armed(w)

    n = len(w.writes)
    w.command(cmd="party_mon", key=KB)
    w.step()
    assert [e["key"] for e in w.events("sync_retrieve_done")][-1:] == [KB]
    assert len(w.writes) > n
    _assert_every_raw_write_is_logged_and_armed(w)

    n = len(w.writes)
    w.command(cmd="memorialize", key=KB)
    w.step()
    (done,) = w.events("memorialize_done")
    assert done["key"] == KB
    assert len(w.writes) > n
    _assert_every_raw_write_is_logged_and_armed(w)


def test_a_bench_in_battle_faint_is_fully_logged():
    w = _live()
    w.battle_ok = True
    w.enter_battle([FOE], active=(0,))
    w.command(cmd="force_faint", key=KB)
    w.step()
    assert w.party_hp(1) == 0
    _assert_every_raw_write_is_logged_and_armed(w)


def test_a_held_battler_landing_at_the_overworld_checkpoint_is_fully_logged():
    w = _live()
    w.enter_battle([FOE], active=(0,))
    w.command(cmd="force_faint", key=KA)
    w.step(3)
    w.leave_battle()
    w.step(3)
    assert w.party_hp(0) == 0
    _assert_every_raw_write_is_logged_and_armed(w)


def test_rr_force_explode_menu_skip_commit_is_fully_logged():
    w = _live("gen3_rr", "radical_red")
    # The RR pack HOLDS battle_commit (REV-C5-RR-BW-FIX 2). Lift ONLY a refusal by the hold alone
    # (every other clause admitted) so the commit plan's logging stays covered for G5.
    policy, safety = w.parts.policy, w.parts.safety
    held_check = policy.check

    def check(this, snap, reason, args=None):
        ok, why = held_check(this, snap, reason, args)
        if not ok and list(safety.last_clauses.values()) == ["battle_commit_hold"]:
            return True, "hold lifted (test scaffolding)"
        return ok, why
    policy.check = check
    w.battle_ok = True
    w.poke_int(w.ram["BATTLE_STRUCT_PTR_ADDR"], 0x02020000, 4)
    w.enter_battle([FOE], active=(0,))
    w.poke_int(w.ram["BATTLE_MONS_ADDR"] + 0x28, 20, 2)     # battler 0 hp
    w.command(cmd="force_explode", key=KA)
    w.step()
    assert w.writes, "the RR menu-skip commit produced no writes"
    _assert_every_raw_write_is_logged_and_armed(w)


# ── (c) the disabled-foundation write guard (PLAN §10) ────────────────────────────────────────

def test_apply_trade_on_frlg_reports_unchanged_and_cancels_menu_with_zero_writes():
    w = _live()
    n = len(w.sent)
    w.command(cmd="apply_trade", slot=0, blob_hex="00" * 100, old_key=KA, token="t")
    w.step(3)
    assert w.writes == []
    replies = [m for m in w.sent[n:] if m["event"] not in ("tick", "safe")]
    assert [m["event"] for m in replies] == ["trade_done", "menu_result"]
    report, cancel = replies
    assert (report["token"], report["slot"], report["new_key"], report["new_species"]) == ("t", 0, KA, 0)
    assert "uncertain" not in report and "after_reset" not in report
    assert (cancel["token"], cancel["choice"], cancel["withdraw"]) == ("t", 0, True)
