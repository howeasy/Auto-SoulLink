"""E1-CHECKPOINT: vanilla Emerald's write checkpoint is SOURCE facts from pokeemerald.sym + pret.

pret publishes no pokeemerald.map, so the player controller's .text span is derived from the .sym
(the functions src/battle_controller_player.c defines, contiguous, bounded by .gcc2_compiled.);
FR/LG keep their .map.  The FR/LG and RR packs must stay byte-identical.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tools"))
import gen_gen3_write_checkpoint as G  # noqa: E402

SYM = "pokeemerald.sym"
LO, HI = 0x08057458, 0x0805D116
NEXT_OBJ = 0x0805D118


def rom_or_skip(pack: str = "gen3_emerald", title: str = "emerald") -> None:
    for kind in G.ALL_PACKS[pack][title][1]:
        if not G.ROMS[(pack, title, kind)][0].exists():
            pytest.skip(f"ROM not present: {pack}/{title}/{kind}")


def pret_or_skip() -> pathlib.Path:
    repo = G.pret_repo(SYM)
    if not repo.is_dir():
        pytest.skip(f"pret checkout not present at {repo}")
    return repo


def pret_file(rel: str) -> list[str]:
    repo = pret_or_skip()
    return subprocess.run(["git", "-C", str(repo), "show", f"{G.pret_commit(SYM)}:{rel}"],
                          capture_output=True, text=True, check=True, encoding="utf-8").stdout.splitlines()


def emitted() -> dict:
    return json.loads(G.out_path("gen3_emerald").read_text(encoding="utf-8"))["emerald"]


def sym_rows() -> list[tuple[int, int, str]]:
    rows = []
    for line in (G.SYM_DIR / SYM).read_text(encoding="utf-8").splitlines():
        p = line.split()
        if len(p) == 4 and p[1] in ("l", "g"):
            rows.append((int(p[0], 16), int(p[2], 16), p[3]))
    return rows


# ── 1. the .sym-derived player-controller span ──────────────────────────────────────────────

def test_player_span_is_the_c_files_functions_contiguous() -> None:
    pret_or_skip()
    names = G.player_controller_functions(SYM)
    assert len(names) == 123 and len(set(names)) == 123
    assert G.sym_text_span(G.SYM_DIR / SYM, names) == (LO, HI)
    assert G.player_span(SYM) == (LO, HI)
    inside = {n for a, s, n in sym_rows() if LO <= a < NEXT_OBJ and n != ".gcc2_compiled."}
    assert inside == set(names)                                   # set equality, no foreign symbol


def test_player_span_bounds_are_independent_facts() -> None:
    rows = sym_rows()
    by_name: dict[str, list[tuple[int, int]]] = {}
    for a, s, n in rows:
        by_name.setdefault(n, []).append((a, s))
    (pred_a, pred_s), = by_name["BattlePalace_TryEscapeStatus"]
    assert pred_a + pred_s == LO                                  # predecessor ends exactly at lo
    assert by_name["AllocateBattleSpritesData"] == [(NEXT_OBJ, 0x40)]
    markers = {a for a, _, n in rows if n == ".gcc2_compiled."}
    assert LO in markers and NEXT_OBJ in markers
    assert not any(LO < m < NEXT_OBJ for m in markers)


def test_narrowed_or_widened_name_list_is_rejected() -> None:
    pret_or_skip()
    names = G.player_controller_functions(SYM)
    with pytest.raises(SystemExit):                               # drop the last function
        G.sym_text_span(G.SYM_DIR / SYM, [n for n in names if n != "PlayerCmdEnd"])
    with pytest.raises(SystemExit):                               # drop a middle one: the run splits
        G.sym_text_span(G.SYM_DIR / SYM, [n for n in names if n != "PlayerHandleGetMonData"])
    with pytest.raises(SystemExit):                               # a foreign name
        G.sym_text_span(G.SYM_DIR / SYM, [*names, "AllocateBattleSpritesData"])


@pytest.mark.parametrize("name,address", [
    ("HandleChooseActionAfterDma3", 0x0816A430),   # Wally
    ("HandleChooseActionAfterDma3", 0x08159A54),   # Safari
    ("HandleInputChooseAction", 0x081593D8),       # Safari
])
def test_non_player_spelling_is_outside_the_span(name: str, address: int) -> None:
    assert (address, name) in {(a, n) for a, _, n in sym_rows()}
    assert not LO <= address < HI


def test_first_spelling_is_the_players_and_a_foreign_one_stops_the_build(monkeypatch) -> None:
    syms = G.title_syms("emerald", SYM)
    assert syms["HandleInputChooseAction"][0] == 0x08057588
    assert syms["HandleChooseActionAfterDma3"][0] == 0x0805C004
    rom_or_skip()
    pret_or_skip()
    real = G.title_syms

    def safari(title, sym_file):
        out = real(title, sym_file)
        out["HandleInputChooseAction"] = (0x081593D8, out["HandleInputChooseAction"][1])
        return out
    monkeypatch.setattr(G, "title_syms", safari)
    with pytest.raises(SystemExit, match="HandleInputChooseAction"):
        G.build_title("gen3_emerald", "emerald", SYM, ("clean",))


def test_frlg_still_uses_its_map() -> None:
    for sym in ("pokefirered.sym", "pokeleafgreen.sym"):
        assert G.player_span(sym) == G.text_span(G.SYM_DIR / sym.replace(".sym", ".map"),
                                                 G.PLAYER_CONTROLLER_OBJ)


# ── 3. renames ──────────────────────────────────────────────────────────────────────────────

def test_renames_resolve_to_the_emerald_spelling() -> None:
    syms = G.title_syms("emerald", SYM)
    assert syms["sSaveDialogCB"][0] == 0x0203761C == syms["sSaveDialogCallback"][0]
    assert syms["RunSaveDialogCB"][0] == 0x0809FF4C == syms["RunSaveCallback"][0]
    fr = G.title_syms("firered", "pokefirered.sym")
    assert fr == G.parse_sym(G.SYM_DIR / "pokefirered.sym")      # no rename outside Emerald


def test_rename_to_a_missing_symbol_is_fatal(monkeypatch) -> None:
    monkeypatch.setitem(G.RENAMES, "emerald", {"sSaveDialogCB": "sNoSuchSymbol"})
    with pytest.raises(SystemExit, match="sNoSuchSymbol"):
        G.title_syms("emerald", SYM)


def test_witness_is_emitted_under_the_emerald_name() -> None:
    w = emitted()["witnesses"]["save_dialog_cb"]
    assert (w["symbol"], w["address"]) == ("sSaveDialogCallback", 0x0203761C)
    assert 0x02000000 <= w["address"] < 0x02040000                   # EWRAM in Emerald


# ── 4. the absent FR/LG task ────────────────────────────────────────────────────────────────

def test_league_lighting_task_is_excluded_with_a_reason() -> None:
    assert "Task_RunPokemonLeagueLightingEffect" not in G.title_syms("emerald", SYM)
    assert "Task_RunPokemonLeagueLightingEffect" not in G.TITLE_TASKS["emerald"]
    assert G.TASKS_EXCLUDED["emerald"]["Task_RunPokemonLeagueLightingEffect"]
    tasks = emitted()["tasks"]
    assert "Task_RunPokemonLeagueLightingEffect" not in tasks["allowed_overworld_tasks"]
    assert "Task_RunPokemonLeagueLightingEffect" in tasks["excluded_tasks"]


def test_a_missing_allowed_task_is_a_named_error_not_a_keyerror(monkeypatch) -> None:
    rom_or_skip()
    pret_or_skip()
    monkeypatch.setitem(G.TITLE_TASKS, "emerald", ("Task_RunPokemonLeagueLightingEffect",))
    with pytest.raises(SystemExit, match="Task_RunPokemonLeagueLightingEffect"):
        G.build_title("gen3_emerald", "emerald", SYM, ("clean",))


def test_allowed_tasks_are_the_emerald_field_set() -> None:
    tasks = emitted()["tasks"]
    assert tasks["allowed_overworld_tasks"] == {
        "Task_RunPerStepCallback": 0x0809D88C, "Task_RunTimeBasedEvents": 0x0809D908,
        "Task_WeatherMain": 0x080AB1B0, "Task_MuddySlope": 0x0809E638,
        "Task_InitUnionRoom": 0x0801697C, "Task_SearchForChildOrParent": 0x08016CA0,
        "Task_UnionRoomListen": 0x0800EB44}
    assert tasks["address"] == 0x03005E00
    assert "pokeemerald c65e93f2" in tasks["source"]


# ── 5. every resolved symbol is the pokeemerald.sym value ───────────────────────────────────

def test_resolved_addresses() -> None:
    e = emitted()
    a = {k: v["address"] for k, v in e["anchors"].items()}
    assert a == {"cb2_overworld": 0x08085E5C, "cb1_overworld": 0x08085E04, "run_tasks": 0x080A910C,
                 "frame_control": 0x0800051C, "try_saving_data": 0x08153338}
    p = e["predicates"]
    assert p["callback1"]["expect"] == 0x08085E05 and p["callback2"]["expect"] == 0x08085E5D
    assert p["palette_fade_active"]["address"] == 0x02037FD4
    assert p["field_controls_locked"]["address"] == 0x03000F2C
    assert (e["cpu"]["pc_min"], e["cpu"]["pc_max"]) == (0x080008AC, 0x080008AC + 0x30 - 1)
    clauses = {c["name"]: c for c in e["battle"]["clauses"]}
    assert clauses["battle_main_func"]["expect"] == 0x0803BE74 | 1
    assert clauses["battle_input_controller"]["expect"] == 0x08057588 | 1
    assert clauses["battle_not_link"]["mask"] == 0x02                    # BATTLE_TYPE_LINK (1 << 1)
    h = e["battle"]["handoff"]
    assert h["value"] == 0x0805748C | 1 and h["address"] == 0x03005D60
    assert "sym-derived" in h["source"] and "sym-derived" in clauses["battle_input_controller"]["source"]


def test_every_symbol_address_equals_the_sym() -> None:
    syms, e = G.title_syms("emerald", SYM), emitted()
    for block in (e["anchors"], e["predicates"], e["witnesses"], e["pointers"]):
        for entry in block.values():
            assert syms[entry["symbol"]][0] == entry["address"], entry
    for c in e["battle"]["clauses"]:
        assert syms[c["symbol"]][0] == c["address"], c
        if "expect_symbol" in c:
            assert syms[c["expect_symbol"]][0] | 1 == c["expect"]


def test_anchor_bytes_are_in_the_rom() -> None:
    rom_or_skip()
    rom = G.load_rom("gen3_emerald", "emerald", "clean")
    for name, a in emitted()["anchors"].items():
        got = rom[a["rom_offset"]:a["rom_offset"] + a["length"]].hex().upper()
        assert got == a["expected_hex"]["clean"], name


# ── offsets re-derived from pret pokeemerald headers ────────────────────────────────────────

@pytest.mark.parametrize("rel,pattern", [
    ("include/main.h", r"/\*0x000\*/ MainCallback callback1;"),
    ("include/main.h", r"/\*0x004\*/ MainCallback callback2;"),
    ("include/main.h", r"/\*0x439\*/ u8 inBattle:1;"),
    ("include/pokemon.h", r"/\*0x2C\*/ u16 maxHP;"),
    ("include/constants/battle.h", r"#define BATTLE_TYPE_LINK\s+\(1 << 1\)"),
    ("include/constants/battle.h", r"#define STATUS3_PERISH_SONG\s+\(1 << 5\)"),
    ("include/battle.h", r"#define B_ACTION_NOTHING_FAINTED\s+13"),
    ("include/task.h", r"#define NUM_TASKS 16"),
    ("include/gba/m4a_internal.h", r"#define ID_NUMBER 0x68736D53"),
])
def test_offsets_are_the_pret_emerald_headers(rel: str, pattern: str) -> None:
    assert any(re.search(pattern, line) for line in pret_file(rel)), (rel, pattern)


def test_emitted_offsets_and_handoff_head() -> None:
    e = emitted()
    p = e["predicates"]
    assert (p["callback1"]["offset"], p["callback2"]["offset"]) == (0, 4)
    assert (p["in_battle"]["offset"], p["in_battle"]["mask"]) == (0x439, 0x02)
    assert (p["palette_fade_active"]["offset"], p["palette_fade_active"]["mask"]) == (7, 0x80)
    clauses = {c["name"]: c for c in e["battle"]["clauses"]}
    assert clauses["battle_engine_loaded"]["offset"] == 0x2C             # BattlePokemon.maxHP
    assert e["battle"]["handoff"]["head"] == [
        {"name": "perish_status", "address": 0x020242AC, "width": 4, "set": 0x20},
        {"name": "perish_timer", "address": 0x020242BC + 0x0F, "width": 1, "keep": 0xF0},
        {"name": "no_op_action", "address": 0x0202421C, "width": 1, "value": 13}]
    assert (e["tasks"]["struct_size"], e["tasks"]["count"]) == (0x28, 16)
    s = e["sound"]
    assert s["sound_info"]["address"] == 0x03006380 and s["player_se1"]["address"] == 0x030075F0
    assert s["sound_info_ptr"]["address"] == 0x03007FF0
    assert "pokeemerald" in s["source"]


# ── 6. forbidden inventory ──────────────────────────────────────────────────────────────────

def test_forbidden_inventory_is_in_the_sym_and_off_the_allow_list() -> None:
    syms, e = G.title_syms("emerald", SYM), emitted()
    inv = e["tasks"]["forbidden_inventory"]
    for name in ("CB2_StartContest", "Task_StartContest", "Task_EnterSecretBase",
                 "Task_WarpOutOfSecretBase", "Task_DoRecordMixing", "Task_RecordMixing_Main",
                 "CB2_FrontierPass", "Task_BattlePyramidChooseMonHeldItems",
                 "Task_TrainerHillWaitForPaletteFade", "CB2_HandleStartMultiPartnerBattle",
                 "CB2_PreInitMultiBattle", "CB2_HandleStartMultiBattle", "CB2_UnionRoomBattle"):
        assert inv[name] == syms[name][0], name
    assert sum(n.startswith("Task_LinkContest_") for n in inv) == 30
    assert not set(e["tasks"]["allowed_overworld_tasks"].values()) & set(inv.values())
    assert all(v | 1 != e["predicates"]["callback2"]["expect"] for v in inv.values())


# ── 7. census pending ───────────────────────────────────────────────────────────────────────

def test_census_is_pending_not_invented() -> None:
    cpu = emitted()["cpu"]
    assert cpu["census"] == "PENDING E2" and "observed_pc" not in cpu
    assert (cpu["mode"], cpu["thumb"], cpu["symbol"]) == (0x1F, 1, "WaitForVBlank")


# ── byte identity: FR/LG + RR unchanged, Emerald current ────────────────────────────────────

@pytest.mark.parametrize("pack", ["gen3_frlg", "gen3_rr", "gen3_emerald"])
def test_committed_pack_is_what_the_generator_renders(pack: str) -> None:
    for title in G.ALL_PACKS[pack]:
        rom_or_skip(pack, title)
    if pack == "gen3_rr":
        rom_or_skip("gen3_frlg", "firered")
    if pack == "gen3_emerald":
        pret_or_skip()
    out, _ = G.build(pack)
    assert G.render(out) == G.out_path(pack).read_text(encoding="utf-8")


def test_emerald_is_not_an_admitted_pack() -> None:
    assert "gen3_emerald" not in G.PACKS and "gen3_emerald" in G.UNADMITTED_PACKS
