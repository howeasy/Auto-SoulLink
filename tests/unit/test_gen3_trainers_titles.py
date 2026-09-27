"""Per-title level-up learnsets for frlg_trainers.json (Codex FRLG review cx-42eabc05 finding 4).

pret level_up_learnsets.h has `#if defined(FIRERED)` / `#elif defined(LEAFGREEN)` branches (Deoxys's
forme learnset, Dugtrio's move order). tools/gen_gen3_trainers.py once parsed the raw C with both
branches in: Deoxys got LG's learnset and Dugtrio both orders, so default moves derived from the
shipped learnsets were wrong at 86 FR and 20 LG (species, level) points. The ROM test re-measures
exactly that against the pinned clean dumps.
"""
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen3_pret  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen_gen3_trainers as gen  # noqa: E402

DATA = json.loads((ROOT / "data/games/gen3_frlge/frlg_trainers.json").read_text(encoding="utf-8"))
LOCK = json.loads((ROOT / "data/gen3_sources.lock.json").read_text(encoding="utf-8"))
ROM_NAMES = {"firered": "Pokemon - FireRed Version (USA).gba",
             "leafgreen": "Pokemon - LeafGreen Version (USA).gba",
             "emerald": "Pokemon - Emerald Version (USA, Europe).gba"}
ROM_SHA1 = {"firered": LOCK["outputs"]["pokefirered"]["sha1"],
            "leafgreen": LOCK["outputs"]["pokeleafgreen"]["sha1"],
            "emerald": json.loads((ROOT / "data/gen3/pret/pokeemerald_provenance.json")
                                  .read_text(encoding="utf-8"))["rom"]["sha1"]}
TACKLE, TAUNT, KNOCK_OFF = 33, 269, 282


def clean_rom(title, env=os.environ):
    """The pinned clean dump: $SLINK_GEN3_ROMS/<name>, else the checkout or a parent. Absent skips
    by name; a file at another sha1 fails."""
    name = ROM_NAMES[title]
    dirs = [Path(env["SLINK_GEN3_ROMS"])] if env.get("SLINK_GEN3_ROMS") else [ROOT, *ROOT.parents]
    path = next((d / name for d in dirs if (d / name).is_file()), None)
    if path is None:
        pytest.skip(f"clean {title} dump not found ({name}); set SLINK_GEN3_ROMS")
    rom = path.read_bytes()
    if hashlib.sha1(rom).hexdigest() != ROM_SHA1[title]:
        pytest.fail(f"{path} is not the pinned clean {title} dump {ROM_SHA1[title]}")
    return rom


def symbol(title, name):
    for line in (ROOT / "data/gen3/pret" / f"poke{title}.sym").read_text(encoding="utf-8").splitlines():
        f = line.split()
        if len(f) == 4 and f[3] == name:
            return int(f[0], 16), int(f[2], 16)
    raise KeyError(name)


def rom_learnsets(rom, title):
    """gLevelUpLearnsets: species -> [(level, move)], u16 (level << 9 | move) up to 0xFFFF."""
    addr, size = symbol(title, "gLevelUpLearnsets")
    out = {}
    for sp in range(size // 4):
        p = struct.unpack_from("<I", rom, addr - 0x08000000 + 4 * sp)[0] - 0x08000000
        out[sp] = []
        while (w := struct.unpack_from("<H", rom, p)[0]) != 0xFFFF:
            out[sp].append((w >> 9, w & 0x1FF))
            p += 2
    return out


def json_learnsets(data, title):
    """What a reader gets for `title`: the table, with that title's overrides on top."""
    table = {int(k): [tuple(e) for e in v] for k, v in data["learnsets"].items()}
    table.update({int(k): [tuple(e) for e in v]
                  for k, v in (data.get("learnsets_by_title") or {}).get(title, {}).items()})
    return table


def test_learnsets_take_each_titles_if_branch():
    root = gen3_pret.require(gen3_pret.find())
    fr, lg = gen.learnsets(root, "firered"), gen.learnsets(root, "leafgreen")
    assert gen.default_moves(fr["SPECIES_DEOXYS"], 15)[-1] == "MOVE_TAUNT"
    assert gen.default_moves(lg["SPECIES_DEOXYS"], 15)[-1] == "MOVE_KNOCK_OFF"
    assert gen.default_moves(fr["SPECIES_DUGTRIO"], 1) == [
        "MOVE_TRI_ATTACK", "MOVE_SCRATCH", "MOVE_SAND_ATTACK", "MOVE_GROWL"]
    assert gen.default_moves(lg["SPECIES_DUGTRIO"], 1) == [
        "MOVE_TRI_ATTACK", "MOVE_SAND_ATTACK", "MOVE_SCRATCH", "MOVE_GROWL"]
    assert {sp for sp in fr if fr[sp] != lg[sp]} == {"SPECIES_DUGTRIO", "SPECIES_DEOXYS"}


def test_title_branch_evaluates_pret_conditionals():
    src = "a\n#if defined(FIRERED)\nfr\n#elif defined(LEAFGREEN)\nlg\n#else\nother\n#endif\n" \
          "#ifndef GUARD\nguarded\n#endif\n#ifdef LEAFGREEN\nlg2\n#endif\n"
    assert gen.title_branch(src, "firered") == "a\nfr\n#ifndef GUARD\nguarded\n#endif\n"
    assert gen.title_branch(src, "leafgreen") == "a\nlg\n#ifndef GUARD\nguarded\n#endif\nlg2\n"
    assert gen.title_branch(src, "emerald") == "a\nother\n#ifndef GUARD\nguarded\n#endif\n"
    with pytest.raises(SystemExit):
        gen.title_branch("#if FIRERED + 1\n#endif\n", "firered")


def test_json_carries_per_title_learnsets():
    # `learnsets` is FireRed's (titles[0]); `learnsets_by_title` overrides only where LG differs
    assert DATA["titles"] == ["firered", "leafgreen"]
    assert set(DATA["learnsets_by_title"]) == {"leafgreen"}
    assert set(DATA["learnsets_by_title"]["leafgreen"]) == {"51", "410"}      # Dugtrio, Deoxys
    fr, lg = json_learnsets(DATA, "firered"), json_learnsets(DATA, "leafgreen")
    assert gen.default_moves(fr[410], 15)[-1] == TAUNT
    assert gen.default_moves(lg[410], 15)[-1] == KNOCK_OFF
    assert len(fr[51]) == len(lg[51]) == 13                         # one branch each, not both


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_default_moves_match_the_rom_learnsets(title):
    """The reviewer's measurement: every species at levels 1..100, the moves GiveBoxMonInitialMoveset
    gives from the shipped learnsets vs from the clean ROM's gLevelUpLearnsets."""
    rom = rom_learnsets(clean_rom(title), title)
    ours = json_learnsets(DATA, title)
    bad = [(sp, lv) for sp in rom for lv in range(1, 101)
           if gen.default_moves(rom[sp], lv) != gen.default_moves(ours.get(sp, []), lv)]
    assert bad == []
    assert len(rom) == 412


TABLES = {"firered": DATA, "leafgreen": DATA,
          "emerald": json.loads((ROOT / "data/games/gen3_emerald/emerald_trainers.json").read_text(encoding="utf-8"))}


@pytest.mark.parametrize("title", ["firered", "leafgreen", "emerald"])
def test_parties_match_the_rom(title):
    """Every generated party against the clean ROM gTrainers: species, level, held item, and the
    explicit moves or, for a default-moves party, GiveBoxMonInitialMoveset over the ROM's own
    gLevelUpLearnsets. pret's one-line RS dummy parties (`= {DUMMY_TRAINER_MON};`, _IV, _STARMIE)
    are emitted empty while the ROM holds the placeholder mons: those are only counted."""
    from server.adapters.gen3_frlge import Gen3Adapter
    from server.adapters.gen3_rom_tables import decode_trainers

    rom = clean_rom(title)
    ls = rom_learnsets(rom, title)
    names = Gen3Adapter(is_rr=False, rom_type=title)
    addr, size = symbol(title, "gTrainers")
    table = TABLES[title]["trainers"]
    dummies, bad = 0, []
    for tid, tr in decode_trainers(rom, addr, size // 40).items():
        ours = table[str(tid)]["party"]
        if not ours and tr["party"]:
            dummies += 1
            continue
        want = []
        for mon in tr["party"]:
            moves = mon["moves"] if "moves" in mon else gen.default_moves(ls[mon["species"]], mon["level"])
            entry = {"species": names.calc_species(mon["species"]), "level": mon["level"]}
            if mon.get("held_item"):
                entry["item"] = names.calc_name("item", names.item_name(mon["held_item"]))
            entry["moves"] = [names.calc_name("move", names.move_name(m)) for m in moves if m]
            want.append(entry)
        if want != ours:
            bad.append(tid)
    assert bad == []
    assert dummies == {"firered": 103, "leafgreen": 103, "emerald": 0}[title]
