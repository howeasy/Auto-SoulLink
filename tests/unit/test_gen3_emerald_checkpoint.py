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
# battle.handoff.head rows -> (.sym symbol, offset inside that symbol).  The pack's profile carries
# the numbers; this is the independent proof that they are the Emerald .sym's, not literals.
HEAD_ROWS = {"perish_status": ("gStatuses3", 0x00),
             "perish_timer": ("gDisableStructs", 0x0F),      # DisableStruct.perishSongTimer:4
             "no_op_action": ("gChosenActionByBattler", 0x00)}


def rom_or_skip(pack: str = "gen3_emerald", title: str = "emerald") -> None:
    for kind in G.ALL_PACKS[pack][title][1]:
        if not G.ROMS[(pack, title, kind)][0].exists():
            pytest.skip(f"local copyrighted ROMs absent: {pack}/{title}/{kind}")


def pret_or_skip() -> pathlib.Path:
    repo = G.pret_repo(SYM)
    if not repo.is_dir():
        pytest.skip(f"pokeemerald not cloned: {repo}")
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


def span_gaps(names: set[str]) -> list[int]:
    """The .sym padding between consecutive functions of the player-controller run, in address order."""
    rows = sorted((a, s) for a, s, n in sym_rows() if n in names and LO <= a < HI)
    return [nxt - (a + size) for (a, size), (nxt, _) in zip(rows, rows[1:], strict=False)]


# ── 1. the .sym-derived player-controller span ──────────────────────────────────────────────

def test_player_span_is_the_c_files_functions_contiguous() -> None:
    pret_or_skip()
    names = G.player_controller_functions(SYM)
    assert len(names) == 123 and len(set(names)) == 123
    assert G.sym_text_span(G.SYM_DIR / SYM, names) == (LO, HI)
    assert G.player_span(SYM) == (LO, HI)
    inside = {n for a, s, n in sym_rows() if LO <= a < NEXT_OBJ and n != ".gcc2_compiled."}
    assert inside == set(names)                                   # set equality, no foreign symbol
    gaps = span_gaps(set(names))
    assert len(gaps) == len(names) - 1 == 122
    assert all(0 <= g < 4 for g in gaps)                            # the generator's < 4 rule, re-proved
    assert max(gaps) == 2 and gaps.count(2) == 13                    # 13 alignment gaps of 2, rest 0


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
        "Task_UnionRoomListen": 0x0800EB44, "Task_MapNamePopUpWindow": 0x080D487C}
    assert tasks["address"] == 0x03005E00
    assert "pokeemerald c65e93f2" in tasks["source"]


def test_every_task_set_up_field_tasks_creates_is_on_the_allow_list() -> None:
    """A new field task must fail here: SetUpFieldTasks' CreateTask targets are the allow-list floor."""
    lines = pret_file("src/field_tasks.c")
    start = next(i for i, ln in enumerate(lines) if ln.startswith("void SetUpFieldTasks("))
    body = []
    for line in lines[start + 1:]:
        if line == "}":                                             # column-0 brace ends the function
            break
        body.append(line)
    created = {m.group(1) for m in (re.search(r"CreateTask\(\s*(\w+)", ln) for ln in body) if m}
    assert created == {"Task_RunPerStepCallback", "Task_MuddySlope", "Task_RunTimeBasedEvents"}
    assert created <= set(emitted()["tasks"]["allowed_overworld_tasks"])


# E2-CKPT: the popup is admitted because its body reaches only window/BG/palette code.  A new
# callee in pret's popup file (a party, flag or save call) fails here before it reaches a pack.
POPUP_CALLEES = {
    "FlagGet", "FuncIsActiveTask", "CreateTask", "SetGpuReg", "ShowMapNamePopUpWindow",
    "ClearStdWindowAndFrame", "GetMapNamePopUpWindowId", "HideMapNamePopUpWindow",
    "RemoveMapNamePopUpWindow", "SetGpuReg_ForcedBlank", "DestroyTask",
    "CurrentBattlePyramidLocation", "StringCopy", "GetMapName", "AddMapNamePopUpWindow",
    "LoadMapNamePopUpWindowBg", "GetStringCenterAlignXOffset", "AddTextPrinterParameterized",
    "CopyWindowToVram", "FillBgTilemapBufferRect", "LoadBgTiles", "GetWindowAttribute",
    "CallWindowFunction", "PutWindowTilemap", "LoadPalette", "BlitBitmapToWindow"}


def test_map_name_popup_reaches_only_window_code() -> None:
    lines = pret_file("src/map_name_popup.c")
    start = next(i for i, ln in enumerate(lines) if ln.startswith("void ShowMapNamePopup("))
    calls = set()
    for line in lines[start:]:
        code = line.split("//")[0]
        calls |= set(re.findall(r"\b([A-Z]\w*)\s*\(", code))
    defined = {m.group(1) for m in (re.match(r"(?:static )?\w+ \*?(\w+)\(", ln) for ln in lines[start:]) if m}
    macros = {"BG_PLTT_ID", "UNUSED"}
    assert calls - defined - macros - {"ShowMapNamePopup"} <= POPUP_CALLEES
    assert emitted()["tasks"]["allowed_overworld_tasks"]["Task_MapNamePopUpWindow"] == 0x080D487C


# OMP review cx-c2e064ee #4: the popup's out-of-file callees are followed too. Each maps to the
# pret file that defines it; the walk must close over exactly these functions, every leaf is a
# string/var READ helper, and no body assigns through a save block pointer.
POPUP_FOREIGN = {"GetMapName": "src/region_map.c",
                 "CurrentBattlePyramidLocation": "src/battle_pyramid.c",
                 "GetSecretBaseMapName": "src/secret_base.c",
                 "GetSecretBaseName": "src/secret_base.c"}
POPUP_LEAVES = {"StringCopy", "StringFill", "StringCopyN", "StringAppend", "GetNameLength",
                "ConvertInternationalString", "VarGet"}


def _pret_body(rel: str, name: str) -> list[str]:
    lines = pret_file(rel)
    start = next(i for i, ln in enumerate(lines)
                 if re.match(rf"^[A-Za-z].*[ *]{name}\(", ln) and not ln.rstrip().endswith(";"))
    end = next(i for i in range(start, len(lines)) if lines[i].startswith("}"))
    return lines[start:end + 1]


def test_map_name_popup_foreign_callees_only_read_state() -> None:
    seen, todo = set(), ["GetMapName", "CurrentBattlePyramidLocation"]
    leaves = set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        body = _pret_body(POPUP_FOREIGN[name], name)
        code = "\n".join(ln.split("//")[0] for ln in body[1:])
        assert not re.search(r"gSaveBlock\dPtr->[\w.\[\]>-]*\s*[-+|&^]?=(?!=)", code), name
        for callee in set(re.findall(r"\b([A-Z]\w*)\s*\(", code)) - {name}:
            if callee in POPUP_FOREIGN:
                todo.append(callee)
            else:
                leaves.add(callee)
    assert seen == set(POPUP_FOREIGN)
    assert leaves <= POPUP_LEAVES, leaves - POPUP_LEAVES


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
    head = {row["name"]: row for row in e["battle"]["handoff"]["head"]}
    for name, (symbol, off) in HEAD_ROWS.items():
        assert syms[symbol][0] + off == head[name]["address"], head[name]
        assert off < syms[symbol][1], head[name]                    # the row lands inside that symbol


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
    ("src/battle_main.c", r"^\s*STATE_TURN_START_RECORD,\s*$"),   # enum 0, so the next is 1
    ("include/constants/battle.h", r"#define STATUS3_PERISH_SONG\s+\(1 << 5\)"),
    ("include/battle.h", r"#define B_ACTION_NOTHING_FAINTED\s+13"),
    ("include/task.h", r"#define NUM_TASKS 16"),
    ("include/gba/m4a_internal.h", r"#define ID_NUMBER 0x68736D53"),
])
def test_offsets_are_the_pret_emerald_headers(rel: str, pattern: str) -> None:
    assert any(re.search(pattern, line) for line in pret_file(rel)), (rel, pattern)


def test_battle_comm_0_is_state_wait_action_chosen_not_before_action_chosen() -> None:
    """F-B (card E2-FIX-AB): battle_comm_0's expect is the index of STATE_WAIT_ACTION_CHOSEN in
    pokeemerald's own src/battle_main.c enum -- the parked action-menu state, the same state
    FR/LG's battle_comm_0 names (docs/gen3/research/battle_write_predicate.md:61-63) -- not
    STATE_BEFORE_ACTION_CHOSEN. The old version of this test asserted
    `STATE_BEFORE_ACTION_CHOSEN == 1`: the right NUMBER (Emerald's enum has one extra leading
    member, STATE_TURN_START_RECORD, so everything downstream shifts by one) attached to the
    wrong MEANING (STATE_BEFORE_ACTION_CHOSEN is index 1 in Emerald, but the state
    battle_comm_0 actually demands, STATE_WAIT_ACTION_CHOSEN, is index 2). commit_guard.value is
    the same by-name shift applied to STATE_WAIT_ACTION_CONFIRMED_STANDBY."""
    lines = pret_file("src/battle_main.c")
    i = next(i for i, ln in enumerate(lines) if ln.strip() == "STATE_WAIT_ACTION_CHOSEN,")
    start = max((j for j in range(i) if lines[j].strip() == "enum"), default=-1)
    assert start >= 0
    body = []
    for line in lines[start + 1:]:
        text = line.strip()
        if text == "};":
            break
        if text not in ("", "{"):
            body.append(text.rstrip(","))
    assert body[:3] == ["STATE_TURN_START_RECORD", "STATE_BEFORE_ACTION_CHOSEN", "STATE_WAIT_ACTION_CHOSEN"]
    assert body.index("STATE_WAIT_ACTION_CHOSEN") == 2              # the value battle_comm_0 demands
    clause = next(c for c in emitted()["battle"]["clauses"] if c["name"] == "battle_comm_0")
    assert clause["expect"] == 2
    # the commit guard's value is the same by-name state, shifted the same way (F-B)
    assert body.index("STATE_WAIT_ACTION_CONFIRMED_STANDBY") == 4
    assert emitted()["battle"]["commit_guard"]["value"] == 4


def test_in_battle_is_bit_1_of_byte_0x439() -> None:
    bits = [m.group(1) for m in (re.search(r"/\*0x439\*/ u8 (\w+):1;", line)
                                 for line in pret_file("include/main.h")) if m]
    assert bits == ["oamLoadDisabled", "inBattle", "anyLinkBattlerHasFrontierPass"]
    in_battle = emitted()["predicates"]["in_battle"]
    assert in_battle["offset"] == 0x439
    assert in_battle["mask"] == 1 << bits.index("inBattle") == 0x02


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


# ── 7. the E2 frame-end census ──────────────────────────────────────────────────────────────

def test_cpu_is_the_e2_census() -> None:
    cpu = emitted()["cpu"]
    assert cpu["census"] == "docs/gen3_emerald/probes/census_emerald_overworld_2026-09-25.txt"
    assert (cpu["mode"], cpu["thumb"], cpu["symbol"]) == (0x1F, 1, "WaitForVBlank")
    assert (cpu["pc_min"], cpu["pc_max"]) == (0x080008AC, 0x080008DB)      # pokeemerald.sym:1120
    final = (G.ROOT / cpu["census"]).read_text(encoding="utf-8").split("final at frame", 1)[1]
    rows = {int(m[0], 16): int(m[1]) for m in re.findall(r"R15=(0x[0-9A-F]+) x(\d+)", final)}
    rom_pcs = {pc for pc in rows if pc >= G.ROM_BASE}
    assert rom_pcs and all(cpu["pc_min"] <= pc <= cpu["pc_max"] for pc in rom_pcs)
    assert cpu["observed_pc"] == max(rows, key=rows.get) == 0x080008C8     # the modal frame end
    assert all(pc < 0x4000 for pc in set(rows) - rom_pcs)                  # the BIOS IRQ vector only
    assert sum(rows[pc] for pc in rom_pcs) > 0.9 * sum(rows.values())


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
