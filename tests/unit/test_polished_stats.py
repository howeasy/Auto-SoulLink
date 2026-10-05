"""Withdraw reconstruction: savemon -> party_struct (docs/polished/WITHDRAW.md).

The oracle in this file is written from the ASSM, independently of the codec under test:
  * engine/pokemon/mon_stats.asm CalcPkmnStatC (:669-876) -- DV nibble per stat, the
    `sla/inc/rl` that forms ((base+DV)*2+1), the EV>>2 term, *level/100, the +level+10 (HP) or +5,
    the 999 cap and the nature multiply/divide.
  * engine/pokemon/mon_stats.asm GetNatureStatMultiplier (:878-912) -- raised = nature//5+2,
    lowered = nature%5+2, equal means neutral, HP is always neutral.
  * engine/items/item_effects.asm ComputeMaxPP (:3170-3216) -- base + ups*min(base//5, 7), masked.
  * engine/pc/bills_pc.asm SetTempPartyMonData (:983-1029) -- HP := MaxHP (0 for an egg),
    Status := 0, PP from RestoreTempPP, level straight from SAVEMON_LEVEL.

Both the codec and the oracle are driven by hand-transcribed arithmetic below; a disagreement means
one of them is wrong, and the red controls at the end say which.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import random
import re
import types

import pytest

from server.adapters import polished_codec as pc

REPO = pathlib.Path(__file__).resolve().parents[2]
ROM = pathlib.Path("F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc")
PIN = json.loads((REPO / "data/games/polished_crystal/engine_signals.json").read_text(encoding="utf-8"))
STATS = pc.STAT_NAMES


# ── the oracle, transcribed from the asm (no pc.* call below this line) ─────────────────────────────

def oracle_dv(dvs: dict, index: int) -> int:
    """CalcPkmnStatC's per-stat nibble pick. index is 1=HP .. 6=SpDef."""
    if index == 1:
        return dvs["hp"]
    if index == 2:
        return dvs["attack"]
    if index == 3:
        return dvs["defense"]
    if index == 4:
        return dvs["speed"]
    if index == 5:
        return dvs["special_attack"]
    return dvs["special_defense"]


def oracle_nature(nature: int, index: int) -> int:
    if index == 1:
        return 10
    raised, lowered = nature // 5 + 2, nature % 5 + 2
    if raised == lowered:
        return 10
    if index == lowered:
        return 9
    return 11 if index == raised else 10


def oracle_stat(base: int, dv: int, ev: int, level: int, index: int, nature: int) -> int:
    numerator = (base + dv) * 2 + 1 + (ev >> 2)        # sla e / inc e / rl d, then srl b / srl b
    value = numerator * level // 100                    # Multiply, then Divide by 100
    value = value + (level + 10) if index == 1 else value + 5
    value = 999 if value > 999 else value                # .max_stat
    return value * oracle_nature(nature, index) // 10   # Multiply, then Divide by 10


def oracle_max_pp(base_pp: int, ups: int) -> int:
    return (base_pp + ups * (7 if base_pp // 5 > 7 else base_pp // 5)) & 0x3F


# ── fixtures ────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def species_rows() -> dict:
    return json.loads((REPO / "data/games/polished_crystal/species_index.json")
                      .read_text(encoding="utf-8"))["species"]


@pytest.fixture(scope="module")
def move_rows() -> dict:
    return {m["id"]: m["pp"] for m in json.loads(
        (REPO / "data/games/polished_crystal/moves.json").read_text(encoding="utf-8"))["moves"]}


@pytest.fixture(scope="module")
def variants():
    if not ROM.is_file():
        pytest.skip("pinned Polished release ROM absent")
    return pc.variant_base_stats_from_rom(ROM.read_bytes(), rom_sha1=PIN["source"]["rom_sha1"])


def make_mon(rng, species_id, form=0, *, level=50, dv=None, ev=None, nature=None, moves=(1, 2, 3, 4),
             ups=(0, 1, 2, 3), extra=0):
    return {"species_id": species_id, "form": form, "level": level, "gender": "male", "shiny": False,
            "is_egg": False, "ability_slot": 0, "held_item": 0, "ot_id": 0x1234, "exp": 1000,
            "stats": dict.fromkeys(STATS[1:], 40),
            "nature": rng.randrange(25) if nature is None else nature,
            "moves": list(moves), "pp_ups": list(ups),
            "dvs": dict(zip(STATS, dv or [rng.randrange(16) for _ in STATS], strict=True)),
            "evs": dict(zip(STATS, ev or [0] * 6, strict=True)),
            "happiness": 70, "pokerus": 0, "caught_data": 0, "caught_level": 5, "caught_location": 0,
            "extra_hex": bytes([extra, 0, 0]).hex(), "nickname": "MON", "ot_name": "KRIS"}


def sealed(rng, **kwargs) -> bytes:
    return pc.encode_savemon(make_mon(rng, **kwargs))


def build(box, variants, *, apply_evs=True, natures_on=True, perfect_ivs=False):
    """Every call site names the four REQUIRED options; none is inherited from a default."""
    return pc.savemon_to_party(box, variant_base_stats=variants, apply_evs=apply_evs, natures_on=natures_on,
                               perfect_ivs=perfect_ivs)


def expected(mon: dict, rows, pp_rows, variants, perfect_ivs=False) -> bytes:
    record = pc.effective_species(mon["species_id"], mon["form"])
    if pc.is_variant_form(mon["species_id"], mon["form"]):
        base = variants[record]
    else:
        base = tuple(rows[str(record)]["base_stats"][name] for name in STATS)
    trained = bytes.fromhex(mon["extra_hex"])[0] & 0xFC
    stats = []
    for index, name in enumerate(STATS, start=1):
        dv = 15 if perfect_ivs or trained & (0x80 >> (index - 1)) else oracle_dv(mon["dvs"], index)
        stats.append(oracle_stat(base[index - 1], dv, mon["evs"][name], mon["level"], index, mon["nature"]))
    out = bytearray(48)
    entry = pc.encode_savemon(mon)
    out[0:22] = entry[0:22]
    for index in range(4):
        move = mon["moves"][index]
        out[22 + index] = (mon["pp_ups"][index] << 6) | (oracle_max_pp(pp_rows[move], mon["pp_ups"][index])
                                                        if move else 0)
    out[26], out[27] = entry[23], entry[24]
    out[28:31] = entry[25:28]
    out[31] = mon["level"]
    out[34:36] = bytes((0, 0)) if mon.get("is_egg") else bytes((stats[0] & 255, stats[0] >> 8))
    out[36:38] = bytes((stats[0] & 255, stats[0] >> 8))
    for index, value in enumerate(stats[1:], start=1):
        out[36 + index * 2:38 + index * 2] = bytes((value & 255, value >> 8))
    return bytes(out)


# ── the checks ─────────────────────────────────────────────────────────────────────────────────────

def test_the_oracle_and_the_codec_agree_on_500_random_mons(species_rows, move_rows, variants):
    rng = random.Random(0x5EED)
    records = sorted(int(k) for k in species_rows)
    for n in range(500):
        record = records[rng.randrange(len(records))]
        level = rng.choice([1, 50, 100, rng.randrange(1, 101)])
        mon = make_mon(rng, record, level=level,
                       dv=[rng.choice([0, 15, rng.randrange(16)]) for _ in STATS],
                       ev=[rng.choice([0, 255, rng.randrange(256)]) for _ in STATS],
                       moves=tuple(rng.randrange(1, 256) for _ in range(4)),
                       ups=tuple(rng.randrange(4) for _ in range(4)),
                       extra=rng.choice([0, 0xFC, rng.randrange(256)]))
        perfect = rng.choice([False, True])
        built = build(pc.encode_savemon(mon), variants, perfect_ivs=perfect)
        assert built == expected(mon, species_rows, move_rows, variants, perfect), (n, mon, perfect)


@pytest.mark.parametrize("nature", range(25))
def test_all_25_natures_shift_exactly_one_stat_each_way(species_rows, move_rows, variants, nature):
    mon = make_mon(random.Random(1), 1, level=50, dv=[8] * 6, ev=[0] * 6, nature=nature)
    party = build(pc.encode_savemon(mon), variants)
    assert party == expected(mon, species_rows, move_rows, variants), nature


def test_every_species_and_variant_form_in_the_pack(species_rows, move_rows, variants):
    """All 291 packed species plus all 46 variant forms (records 292..337)."""
    forms = {(r["species_id"], r["form_id"]) for r in json.loads(
        (REPO / "data/games/polished_crystal/forms_index.json").read_text(encoding="utf-8"))["variant_forms"]}
    for record in sorted(int(k) for k in species_rows):
        mon = make_mon(random.Random(record), record, level=50, dv=[7] * 6, ev=[32] * 6)
        assert build(pc.encode_savemon(mon), variants) == expected(
            mon, species_rows, move_rows, variants), record
    for species_id, form in sorted(forms):
        mon = make_mon(random.Random(species_id + form), species_id, form, level=42, dv=[3] * 6, ev=[0] * 6)
        assert build(pc.encode_savemon(mon), variants) == expected(
            mon, species_rows, move_rows, variants), (species_id, form)


def test_hand_checked_bulbasaur_level_50(variants):
    """Bulbasaur L50, all DVs 15, neutral: ((45+15)*2+1)*50/100 = 61, +50+10 = 121? No: 61 + 60 = 121.
    Attack: ((49+15)*2+1)*50/100 = 50, +5 = 55. Read the codec's own bytes."""
    mon = make_mon(random.Random(0), 1, level=50, dv=[15] * 6, ev=[0] * 6, nature=0)
    party = build(pc.encode_savemon(mon), variants)
    hp = party[36] | party[37] << 8
    atk = party[38] | party[39] << 8
    assert hp == (((45 + 15) * 2 + 1) * 50 // 100) + 50 + 10      # 61 + 60
    assert atk == (((49 + 15) * 2 + 1) * 50 // 100) + 5           # 50 + 5
    assert party[34:36] == party[36:38]                            # HP = MaxHP on withdraw


def test_an_egg_withdraws_with_zero_hp(species_rows, variants):
    mon = make_mon(random.Random(3), 1, level=50, dv=[15] * 6, ev=[0] * 6)
    mon["is_egg"] = True
    party = build(pc.encode_savemon(mon), variants)
    assert party[34:36] == b"\x00\x00" and party[36:38] != b"\x00\x00"


def test_a_fainted_deposit_comes_back_at_full_hp(species_rows, variants):
    """A savemon has no HP byte at all (constants/pokemon_data_constants.asm: SAVEMON_LEVEL is the last
    level-ish field; there is no SAVEMON_HP), so HP is lost with the deposit and the engine refills it."""
    mon = make_mon(random.Random(4), 1, level=20, dv=[0] * 6, ev=[0] * 6)
    party = pc.encode_party_mon(dict(mon, pp=[0, 0, 0, 0], status=0, hp=0, max_hp=60, unused=0))
    decoded = pc.decode_party_mon(party)
    decoded["extra_hex"] = mon["extra_hex"]
    decoded.update(nickname=mon["nickname"], ot_name=mon["ot_name"])
    box = pc.party_to_savemon(decoded)
    rebuilt = build(box, variants)
    assert rebuilt[34:36] == rebuilt[36:38]
    assert pc.decode_party_mon(rebuilt)["hp"] == pc.decode_party_mon(rebuilt)["max_hp"] > 0


def test_round_trip_party_to_savemon_preserves_the_savemon(species_rows, variants):
    rng = random.Random(99)
    for _ in range(50):
        mon = make_mon(rng, rng.randrange(1, 250), level=rng.randrange(1, 101),
                       moves=tuple(rng.randrange(1, 256) for _ in range(4)))
        box = pc.encode_savemon(mon)
        rebuilt = build(box, variants)
        again = pc.decode_party_mon(rebuilt)
        again["extra_hex"] = mon["extra_hex"]
        again.update(nickname=mon["nickname"], ot_name=mon["ot_name"])
        assert pc.party_to_savemon(again) == box


def test_pp_up_rounding_and_the_61_ceiling(species_rows):
    """base 40 (Surf) with three PP Ups is 61, not 64 (item_effects.asm:3195-3201)."""
    assert pc.max_pp(40, 3) == 61 == oracle_max_pp(40, 3)
    for base in range(0, 64):
        for ups in range(4):
            assert pc.max_pp(base, ups) == oracle_max_pp(base, ups)


def test_a_variant_form_without_its_base_stats_is_refused_not_guessed(variants):
    mon = make_mon(random.Random(5), 130, 21, level=50, dv=[15] * 6, ev=[0] * 6)
    with pytest.raises(ValueError, match="variant form record 292"):
        pc.savemon_to_party(pc.encode_savemon(mon), variant_base_stats=None, apply_evs=True, natures_on=True,
                            perfect_ivs=False)
    assert variants[292] == (95, 125, 79, 81, 60, 100)      # GYARADOS_RED_FORM, data/pokemon/base_stats/gyarados.asm:1


def test_the_variant_base_stats_table_is_the_pinned_rom(variants):
    assert hashlib.sha1(ROM.read_bytes()).hexdigest() == PIN["source"]["rom_sha1"]
    with pytest.raises(ValueError, match="pinned build"):
        pc.variant_base_stats_from_rom(b"\x00" * len(ROM.read_bytes()), rom_sha1=PIN["source"]["rom_sha1"])


# ── red controls: each mutant must fail the vector test ─────────────────────────────────────────────

# ── red controls: SOURCE mutants, not monkeypatches ───────────────────────────────────────────────
# Each entry is (before, after) in polished_codec.py's own text. The mutant module is exec'd from that
# text, so a control can only pass if the oracle really distinguishes the two implementations --
# monkeypatching a constant proves nothing about where the constant is read.
SOURCE_MUTANTS = {
    "Def/Spe DV nibble swap":
        ("""    dvs = [mon["dvs"][name] for name in STAT_NAMES]""",
         """    dvs = [mon["dvs"][name] for name in STAT_NAMES]
    dvs[2], dvs[3] = dvs[3], dvs[2]   # MUTANT: Def and Spe read each other's DV nibble"""),
    "nature raised/lowered swapped":
        ("""    raised, lowered = nature // 5 + 2, nature % 5 + 2""",
         """    raised, lowered = nature % 5 + 2, nature // 5 + 2"""),
    "PP cap 61 becomes 64":
        ("""    return (base_pp + ups * min(base_pp // 5, PP_UP_CAP)) & PP_MASK""",
         """    return (base_pp + ups * (base_pp // 5 or 1)) & PP_MASK"""),
    "level read one too low":
        ("""    level = _integer(mon["level"], 1, 100, "level")""",
         """    level = _integer(mon["level"], 1, 100, "level") - 1   # MUTANT: off by one"""),
    "PERFECT_IVS_OPT ignored":
        ("""dv = 15 if perfect_ivs or (trained & (0x80 >> (index - 1))) else dvs[index - 1]""",
         """dv = 15 if (trained & (0x80 >> (index - 1))) else dvs[index - 1]"""),
    "PP-Up bits dropped from the party PP byte":
        ("""        party[22 + index] = (ups << 6) | (max_pp(pp_table[move], ups) if move else 0)""",
         """        party[22 + index] = max_pp(pp_table[move], ups) if move else 0"""),
}


@pytest.fixture(scope="module")
def mutant_modules():
    """(name -> mutant module) built by exec'ing a patched copy of the codec."""
    source = (REPO / "server/adapters/polished_codec.py").read_text(encoding="utf-8")
    for name, (before, _after) in SOURCE_MUTANTS.items():
        assert before in source, f"{name}: anchor not found in polished_codec.py"
    out = {}
    for name, (before, after) in SOURCE_MUTANTS.items():
        module = types.ModuleType("mutant_" + re.sub(r"\W+", "_", name))
        module.__dict__["__file__"] = str(REPO / "server/adapters/polished_codec.py")
        exec(compile(source.replace(before, after, 1), module.__dict__["__file__"], "exec"), module.__dict__)
        out[name] = module
    return out


@pytest.mark.parametrize("name", sorted(SOURCE_MUTANTS))
def test_red_control(name, mutant_modules, species_rows, move_rows, variants):
    """Every mutant must make the reconstruction disagree with the oracle on real vectors."""
    module = mutant_modules[name]
    rng = random.Random(0xC0FFEE)
    records = sorted(int(k) for k in species_rows)
    survivors = 0
    # The first vector is seeded so the PP-cap control fires deterministically: move ids 45/166/81/255 have
    # base PP 40, 1, 40, 1, and at 3 PP Ups the capped and uncapped formulas differ on all four PP bytes.
    seeded = make_mon(rng, 1, level=50, moves=(45, 166, 81, 255), ups=(3, 3, 3, 3))
    vectors = [(seeded, True)]
    for _ in range(60):
        vectors.append((make_mon(rng, records[rng.randrange(len(records))], level=rng.randrange(1, 101),
                                 dv=[rng.randrange(16) for _ in STATS],
                                 ev=[rng.choice([0, 255, rng.randrange(256)]) for _ in STATS],
                                 moves=tuple(rng.randrange(1, 256) for _ in range(4)),
                                 ups=tuple(rng.randrange(4) for _ in range(4)),
                                 extra=rng.choice([0, 0xFC, rng.randrange(256)])), rng.choice([False, True])))
    for mon, perfect in vectors:
        mutant = module.savemon_to_party(module.encode_savemon(mon), variant_base_stats=variants,
                                         apply_evs=True, natures_on=True, perfect_ivs=perfect)
        if mutant == expected(mon, species_rows, move_rows, variants, perfect):
            survivors += 1
    assert survivors < len(vectors), (
        f"{name}: the oracle cannot tell it from the real codec ({survivors}/{len(vectors)} agree)")


# ── the required options are not decorations ───────────────────────────────────────────────────────

def test_evs_off_and_natures_off_change_the_stats(species_rows, move_rows, variants):
    mon = make_mon(random.Random(11), 1, level=50, dv=[8] * 6, ev=[100] * 6, nature=1)
    box = pc.encode_savemon(mon)
    want = expected(mon, species_rows, move_rows, variants)
    assert build(box, variants) == want
    # EVs applied (bills_pc.asm only applies them when wInitialOptions2 & %11)
    assert build(box, variants, apply_evs=False) != want
    # natures on: Lonely raises Attack; natures off: GetNature returns NO_NATURE, all neutral
    assert build(box, variants, apply_evs=False, natures_on=False) != build(box, variants, apply_evs=False)
    lonely = make_mon(random.Random(11), 1, level=50, dv=[8] * 6, ev=[100] * 6, nature=1)
    atk_on = build(pc.encode_savemon(lonely), variants)[38:40]
    atk_off = build(pc.encode_savemon(lonely), variants, natures_on=False)[38:40]
    assert atk_on != atk_off


def test_a_missing_required_option_is_a_type_error_not_a_silent_default(variants):
    mon = pc.encode_savemon(make_mon(random.Random(12), 1))
    for kwargs in ({}, {"variant_base_stats": variants}, {"variant_base_stats": variants, "apply_evs": True},
                   {"apply_evs": True, "natures_on": True, "perfect_ivs": False},
                   {"variant_base_stats": variants, "apply_evs": True, "natures_on": True}):
        with pytest.raises(TypeError):
            pc.savemon_to_party(mon, **kwargs)


def test_omitting_perfect_ivs_raises_type_error(variants):
    mon = pc.encode_savemon(make_mon(random.Random(13), 1))
    with pytest.raises(TypeError, match="perfect_ivs"):
        pc.savemon_to_party(mon, variant_base_stats=variants, apply_evs=True, natures_on=True)


def test_perfect_ivs_option_changes_exactly_the_hp_and_five_stat_low_bytes(variants):
    """mon_stats.asm:704-707: wInitialOptions PERFECT_IVS_OPT forces DV 15 on every stat."""
    mon = make_mon(random.Random(14), 1, level=50, dv=[0, 1, 2, 3, 4, 5], ev=[0] * 6, nature=0)
    box = pc.encode_savemon(mon)
    off, on = build(box, variants, perfect_ivs=False), build(box, variants, perfect_ivs=True)
    assert [i for i in range(48) if off[i] != on[i]] == [34, 36, 38, 40, 42, 44, 46]


def test_the_999_cap_is_unreachable_for_a_legal_mon(species_rows):
    """The engine clamps at 999 (mon_stats.asm:836-848) but no legal mon can reach it: the largest
    numerator is (255+15)*2+1+63 = 604, and 604*100//100 + 110 = 714. A control built on the cap
    would therefore be a no-op mutant that the oracle could never detect -- which is why it is
    replaced by the level mutant above."""
    worst = 0
    for base in range(1, 256):
        for dv in (0, 15):
            for ev in (0, 255):
                for level in (1, 50, 100):
                    worst = max(worst, ((base + dv) * 2 + 1 + (ev >> 2)) * level // 100 + level + 10)
    assert worst == 714 and worst < pc.MAX_STAT
