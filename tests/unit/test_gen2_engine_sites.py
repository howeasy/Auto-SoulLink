"""Refusal controls for source-backed CPU candidates, separate from live firing."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import gen_gen2_engine_signals as generator
from tools.gen2_source_data import load_context
from tools.gen_gen2_engine_signals import REQUIRED_SIGNALS, generate_pack, read_specs
from tools.rgbds_symbols import Symbol
from tools.verify_gen2_rom_layout import verify_pack


@pytest.fixture
def sample():
    source = "Anchor:\n\tld a, [wCurBattleMon]\n\tld c, a\n"
    context = SimpleNamespace(
        title="crystal", source_commit="fixture", artifact="pokecrystal",
        rom=bytes(0x4000) + bytes.fromhex("FA 34 D2 4F") + bytes(0x3FFC),
        symbols={"Anchor": Symbol(1, 0x4000), "wCurBattleMon": Symbol(1, 0xD234),
                 "hROMBank": Symbol(0, 0xFF9D)},
    )
    context.symbol = lambda name: context.symbols[name]
    context.read_source = lambda path: source
    context.source_record = lambda: {"repo": "pokecrystal", "commit": "fixture"}
    specs = {
        "schema": "gen2-engine-site-specs-v1", "source_commits": {"pokecrystal": "fixture"},
        "inventory": {signal: {"sites": [], "remaining": "Physical proof required"}
                      for signal in REQUIRED_SIGNALS},
        "sites": [{"id": "faint", "signal": "player_faint", "phase": "entry",
                   "semantics": "Before copyback; read active battle mon",
                   "point_symbols": ["wCurBattleMon"],
                   "sources": {"pokecrystal": {
                       "file": "engine/test.asm", "symbol": "Anchor",
                       "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                       "instructions": ["ld a, [wCurBattleMon]", "ld c, a"],
                       "hook_index": 0, "hook_count": 2, "evidence": [],
                   }}}],
    }
    specs["inventory"]["player_faint"]["sites"] = ["faint"]
    return context, specs


def test_source_instructions_define_cpu_boundary_and_bytes(sample):
    context, specs = sample
    pack = generate_pack(context, specs)
    site = pack["titles"]["crystal"]["sites"]["faint"]
    assert (site["bank"], site["addr"], site["rom_offset"]) == (1, 0x4000, 0x4000)
    assert site["expected_hex"] == "fa34d24f"
    assert site["kind"] == "CPU_INSTRUCTION"
    assert site["maturity"] == "SOURCE_CANDIDATE"
    assert pack["runtime_admission"] == "NOT_GRANTED"
    assert pack["f3_complete"] is False
    verify_pack(context, pack, specs)


@pytest.mark.parametrize("field,value", [
    ("expected_hex", "fa35d24f"), ("bank", 2), ("addr", 0x4001),
    ("rom_offset", 0x8000), ("kind", "SCRIPT_BYTECODE"),
    ("maturity", "PHYSICAL"),
])
def test_pack_mutations_fail_verifier(sample, field, value):
    context, specs = sample
    pack = generate_pack(context, specs)
    pack["titles"]["crystal"]["sites"]["faint"][field] = value
    with pytest.raises(ValueError):
        verify_pack(context, pack, specs)


def test_script_label_is_refused_even_when_rom_bytes_are_plausible_cpu_bytes(sample):
    context, specs = sample
    text = "Anchor:\n\twritetext Text\n"
    context.read_source = lambda path: text
    row = specs["sites"][0]["sources"]["pokecrystal"]
    row.update(instructions=["writetext Text"], hook_count=1,
               source_sha256=hashlib.sha256(text.encode()).hexdigest())
    with pytest.raises(ValueError, match="CPU|unsupported"):
        generate_pack(context, specs)


def test_source_shape_and_hash_drift_fail(sample):
    context, specs = sample
    broken = copy.deepcopy(specs)
    broken["sites"][0]["sources"]["pokecrystal"]["instructions"][0] = "xor a"
    with pytest.raises(ValueError, match="source instructions"):
        generate_pack(context, broken)
    broken = copy.deepcopy(specs)
    broken["sites"][0]["sources"]["pokecrystal"]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="source hash"):
        generate_pack(context, broken)


def test_rom_opcode_and_symbol_operand_drift_fail(sample):
    context, specs = sample
    context.rom = context.rom[:0x4000] + bytes.fromhex("fa35d24f") + context.rom[0x4004:]
    with pytest.raises(ValueError, match="instruction bytes"):
        generate_pack(context, specs)


def test_missing_signal_inventory_cannot_appear_complete(sample):
    context, specs = sample
    del specs["inventory"]["egg_hatch"]
    with pytest.raises(ValueError, match="inventory"):
        generate_pack(context, specs)


@pytest.mark.parametrize("conditions", [
    {"flags": {"C": 2}}, {"flags": {"carry": 1}},
    {"register_values": {"B": 256}}, {"register_values": {"unknown": 1}},
    {"register_symbols": {"A": "wCurBattleMon"}},
    {"requires_prior": {"site_ids": ["absent"], "consume_once": True}},
])
def test_invalid_success_or_lifecycle_guards_refuse(sample, conditions):
    context, specs = sample
    specs["sites"][0]["conditions"] = conditions
    with pytest.raises(ValueError):
        generate_pack(context, specs)


def test_final_site_cannot_drop_its_success_latch(sample):
    context, specs = sample
    final = copy.deepcopy(specs["sites"][0])
    final["id"] = "faint_final"
    final["conditions"] = {"requires_prior": {
        "site_ids": ["faint"], "match_symbols": ["wCurBattleMon"], "consume_once": True,
    }}
    specs["sites"].append(final)
    specs["inventory"]["player_faint"]["sites"].append("faint_final")
    pack = generate_pack(context, specs)
    guard = pack["titles"]["crystal"]["sites"]["faint_final"]["guards"]
    assert guard["requires_prior"]["scope"] == "current_operation"
    assert "reset" in guard["requires_prior"]["invalidate_on"]
    pack["titles"]["crystal"]["sites"]["faint_final"]["guards"] = {}
    with pytest.raises(ValueError):
        verify_pack(context, pack, specs)


def test_stale_source_provenance_or_missing_site_fails(sample):
    context, specs = sample
    pack = generate_pack(context, specs)
    pack["source"]["commit"] = "stale"
    with pytest.raises(ValueError):
        verify_pack(context, pack, specs)
    pack = generate_pack(context, specs)
    del pack["titles"]["crystal"]["sites"]["faint"]
    with pytest.raises(ValueError):
        verify_pack(context, pack, specs)


def test_generation_validates_all_titles_before_publishing(sample, tmp_path, monkeypatch):
    context, specs = sample
    spec_path = tmp_path / "data/gen2/engine_site_specs.json"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(json.dumps(specs), encoding="utf-8")
    outputs = []
    for title in ("crystal", "gold", "silver"):
        path = tmp_path / f"data/games/gen2_{title}/engine_signals.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"existing reviewed pack")
        outputs.append((path, path.stat().st_mtime_ns))

    def load(title, root):
        if title != "crystal":
            raise ValueError("later title source hash mismatch")
        return context

    monkeypatch.setattr(generator, "load_context", load)
    assert generator.main(["--root", str(tmp_path)]) == 1
    assert all(path.read_bytes() == b"existing reviewed pack" and path.stat().st_mtime_ns == mtime
               for path, mtime in outputs)


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_real_locked_rom_source_and_generated_pack_agree(title):
    # P1's actual build artifacts and clean pinned source are required inputs.
    # Missing inputs fail; this test never reports an absent source lane as SKIP.
    root = Path(__file__).resolve().parents[2]
    context = load_context(title, root=root)
    specs = read_specs(root / "data/gen2/engine_site_specs.json")
    pack = json.loads((root / f"data/games/gen2_{title}/engine_signals.json").read_text("utf-8"))
    verify_pack(context, pack, specs)
    sites = pack["titles"][title]["sites"]
    assert len(sites) == 43
    whiteout = sites["whiteout_before_heal"]
    assert whiteout["symbol"] == "Special"
    assert whiteout["addr"] != context.symbol("Script_Whiteout").address
    assert whiteout["guards"]["registers"]["DE"] == (
        context.symbol("HealPartySpecial").address - context.symbol("SpecialsPointers").address
    ) // 3
    assert [guard["sp_offset"] for guard in whiteout["guards"]["stack_words_equals"]] == [0, 4]
    assert sites["capture_party"]["phase"] == "post_insert_pre_nickname"
    assert sites["capture_box"]["phase"] == "post_insert_pre_nickname"
    assert sites["save_completed"]["expected_hex"] == "c9"
    assert sites["save_completed"]["phase"] == "before_success_return"
    inventory = pack["titles"][title]["inventory"]
    assert all(row["sites"] for row in inventory.values())
    assert pack["f3_complete"] is False
    assert all(row["physical_status"] == "OPEN" for row in inventory.values())
    for route in ("party", "box"):
        final = sites[f"capture_{route}_finalized"]
        assert final["symbol"] == "PokeBallEffect.return_from_capture"
        assert final["guards"]["requires_prior"]["site_ids"] == [f"capture_{route}"]
    assert sites["hatch_finalized"]["guards"]["requires_prior"]["match_symbols"] == ["wCurPartyMon"]
    assert sites["contest_box_finalized"]["guards"]["requires_prior"]["site_ids"] == ["contest_box_inserted"]
    assert sites["gift_party_finalized"]["guards"]["flags"] == {"Z": 1}
    assert sites["gift_box_finalized"]["guards"]["registers"] == {"B": 1}
    assert sites["bag_ball_received"]["guards"]["registers"] == {"DE": context.symbol("wNumBalls").address}
    assert sites["bag_ball_received"]["guards"]["flags"] == {"C": 1}
    assert sites["script_wild_staged"]["kind"] == "CPU_INSTRUCTION"
    for route in ("party", "box"):
        roamer = sites[f"roamer_{route}_finalized"]
        assert roamer["guards"]["memory_equals"][0]["value"] == 5
        assert roamer["guards"]["requires_prior"]["site_ids"] == [f"capture_{route}"]
        assert roamer["event_role"] == "CLASSIFICATION_ONLY"
    assert "BATTLETYPE_SUICUNE" in inventory["roamer_capture"]["remaining"]
    for name in ("link_trade_received", "link_trade_saved"):
        assert sites[name]["guards"]["memory_equals"][0]["value"] == 2


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_evolution_site_carries_the_rom_pre_evolution_table(title):
    root = Path(__file__).resolve().parents[2]
    pack = json.loads((root / f"data/games/gen2_{title}/engine_signals.json").read_text("utf-8"))
    table = pack["titles"][title]["sites"]["evolution_species_published"]["identity_migration"]
    # Independent witness: tools/gen_gen2_evos.py's forward graph, reversed.
    forward = json.loads((root / f"data/games/gen2_{title}/evolutions.json").read_text("utf-8"))["evolutions"]
    assert table["old_species_by_new"] == {str(new): int(old) for old, news in forward.items() for new in news}
    assert table["old_species_by_new"]["26"] == 25 and "1" not in table["old_species_by_new"]


def test_a_species_with_two_pre_evolutions_is_refused():
    constants = "\tconst_def 1\n" + "".join(f"\tconst EVOLVE_{name}\n"
                                              for name in ("LEVEL", "ITEM", "TRADE", "HAPPINESS", "STAT"))
    pointers = "EvosAttacksPointers::\n" + "\tdw Mon\n" * 251
    def context(second):
        rom = bytearray(0x8000)
        lists = {1: [1, 16, 3, 0], 2: second}
        cursor = 0x4000 + 2 * 251
        empty = cursor
        rom[empty] = 0
        cursor += 1
        for species in range(1, 252):
            address = empty
            if species in lists:
                address = cursor
                rom[cursor:cursor + len(lists[species])] = bytes(lists[species])
                cursor += len(lists[species])
            rom[0x4000 + 2 * (species - 1):0x4002 + 2 * (species - 1)] = address.to_bytes(2, "little")
        return SimpleNamespace(rom=bytes(rom), symbol=lambda name: Symbol(1, 0x4000))
    read = lambda path: constants if "constants" in path else pointers
    ok = generator._pre_evolutions(context([5, 20, 1, 4, 0]), read, 1)  # STAT entries are 4 bytes
    assert ok["old_species_by_new"] == {"3": 1, "4": 2}
    with pytest.raises(ValueError, match="unique"):
        generator._pre_evolutions(context([1, 32, 3, 0]), read, 1)
