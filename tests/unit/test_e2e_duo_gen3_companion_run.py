"""--gen3-companion: an explicit, per-run opt-in that makes the FR/LG/Emerald duo rows boot the PATCHED cartridges
(patch/build/slink_{FireRed,LeafGreen,Emerald}.gba), pin-checked, and prove from each CLIENT's own admission line that the cartridge
was the companion by hash. Without the flag nothing changes (the rows keep resolving the clean dumps). No emulator is started."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import e2e_duo as duo  # noqa: E402

from tools import gen3_final_cut  # noqa: E402

BODY = {"firered": b"patched fr " * 9, "leafgreen": b"patched lg " * 9, "emerald": b"patched em " * 9}
PINS = {f"{t}_companion": hashlib.sha1(b).hexdigest() for t, b in BODY.items()}
FILE = {"firered": "slink_FireRed.gba", "leafgreen": "slink_LeafGreen.gba", "emerald": "slink_Emerald.gba"}
PACK = {"firered": "gen3_frlg", "leafgreen": "gen3_frlg", "emerald": "gen3_emerald"}


def _run(tmp_path, monkeypatch, title, companion=True, rom_bytes=None, scenario="faint_cmd_gen3"):
    (tmp_path / "patch/build").mkdir(parents=True, exist_ok=True)
    if rom_bytes is not None:
        (tmp_path / "patch/build" / FILE[title]).write_bytes(rom_bytes)
    monkeypatch.setattr(duo, "REPO", str(tmp_path))
    monkeypatch.setattr(gen3_final_cut, "rom_pins", lambda tree, **kw: dict(PINS, **{title: "0" * 40}))
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.game = "gen3_emerald" if title == "emerald" else "gen3_frlg"
    run.gcfg, run.cfg = dict(duo.GAMES[run.game]), dict(duo.SCENARIOS[scenario])
    run.gen3_companion = companion
    monkeypatch.setattr(run, "_gen3_title", lambda inst: title)
    return run


@pytest.mark.parametrize("title", ["firered", "leafgreen", "emerald"])
def test_the_flag_resolves_the_pinned_companion_cartridge(tmp_path, monkeypatch, title):
    run = _run(tmp_path, monkeypatch, title, rom_bytes=BODY[title])
    assert run._gen3_rom("a") == f"patch/build/{FILE[title]}"                      # repo-relative, space-free


@pytest.mark.parametrize("title", ["firered", "leafgreen", "emerald"])
def test_a_wrong_or_missing_companion_is_refused_not_substituted(tmp_path, monkeypatch, title):
    run = _run(tmp_path, monkeypatch, title, rom_bytes=b"the clean dump or some other build")
    with pytest.raises(RuntimeError, match="does not match"):
        run._gen3_rom("a")                                                         # a wrong file at the right path
    (tmp_path / "patch/build" / FILE[title]).unlink()
    with pytest.raises(FileNotFoundError, match="companion"):
        run._gen3_rom("a")                                                         # no silent fall back to the clean dump


def test_without_the_flag_the_row_keeps_resolving_the_clean_dump(tmp_path, monkeypatch):
    (tmp_path / "Pokemon - FireRed Version (USA).gba").write_bytes(b"clean")
    run = _run(tmp_path, monkeypatch, "firered", companion=False, rom_bytes=BODY["firered"])   # companion IS staged and pinned
    monkeypatch.setattr("gen3_fixtures.stage_rom", lambda path: "patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba")
    assert run._gen3_rom("a") == "patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba"        # negative control: opt-in only
    bare = _run(tmp_path, monkeypatch, "firered", rom_bytes=BODY["firered"])
    del bare.gen3_companion                                                        # a DuoRun built without the attribute
    assert bare._gen3_rom("a") == "patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba"


def test_the_flag_is_only_valid_on_fr_lg_emerald_pairings():
    for game in ("gen3_frlg", "gen3_lgfr", "gen3_emerald"):
        assert duo.gen3_companion_game_problem(game) is None
    for game in ("gen3_rr", "gen3_exp", "gen3_fr_trade", "gen1_new", "gen2_new"):
        assert duo.gen3_companion_game_problem(game)


def test_main_refuses_the_flag_on_a_game_it_cannot_apply_to(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["e2e_duo.py", "--game", "gen3_rr", "--scenario", "faint_cmd_gen3", "--gen3-companion"])
    with pytest.raises(SystemExit, match="gen3-companion"):
        duo.main()


# ---- the client's own admission line is the proof; every side must be the companion, by hash, equal to the pin ----

def _line(inst, title, kind="companion", how="hash", rom=None):
    rom = rom or PINS[f"{title}_companion"][:8]
    return f"[client] [SLink-gen3] {PACK[title]}/{title} ({kind} by {how}) player {inst} -> 127.0.0.1:60673 (rom {rom})"


def _texts(a="firered", b="leafgreen"):
    return {"a": "boot\n" + _line("a", a) + "\nRESULT: PASS\n", "b": "boot\n" + _line("b", b) + "\nRESULT: PASS\n"}


SIDES = {"a": "firered", "b": "leafgreen"}


def test_companion_admission_accepts_two_companion_by_hash_lines_equal_to_the_pins():
    problems, lines = duo.gen3_companion_admission_problems(_texts(), SIDES, PINS)
    assert problems == [] and len(lines) == 2 and "(companion by hash)" in lines[0]


@pytest.mark.parametrize("mutate,why", [
    (lambda t: t.update(a=t["a"].replace("companion by hash", "clean by hash")), "a clean cartridge"),
    (lambda t: t.update(b=t["b"].replace("by hash", "by anchors")), "admitted by anchors, not by hash"),
    (lambda t: t.update(b=t["b"].replace(PINS["leafgreen_companion"][:8], "deadbeef")), "a hash that is not the pin"),
    (lambda t: t.update(a=t["a"].replace("firered (", "leafgreen (")), "the wrong title"),
    (lambda t: t.update(a=t["a"].replace("player a", "player b")), "the other player's line"),
    (lambda t: t.update(b="no admission line at all\nRESULT: PASS\n"), "no line"),
    (lambda t: t.update(a=t["a"] + _line("a", "firered", kind="clean") + "\n"), "a second, clean admission in the same side"),
])
def test_companion_admission_rejects_everything_but_the_exact_proof(mutate, why):
    texts = _texts()
    mutate(texts)
    problems, _lines = duo.gen3_companion_admission_problems(texts, SIDES, PINS)
    assert problems, why


def test_a_same_dump_mislabel_is_rejected():
    """Both sides admit the same companion hash for two different titles, or a clean-labelled line carries the companion hash."""
    texts = {"a": _line("a", "firered", kind="clean", rom=PINS["firered_companion"][:8]), "b": _line("b", "leafgreen")}
    problems, _ = duo.gen3_companion_admission_problems(texts, SIDES, PINS)
    assert problems


def test_a_run_oracle_without_the_proof_fails_and_with_it_notes_the_lines(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, "firered")
    sides = {"a": "firered", "b": "leafgreen"}
    monkeypatch.setattr(run, "_gen3_title", lambda inst: sides[inst])
    notes = []
    monkeypatch.setattr(run, "_pydec_note", notes.append)
    with pytest.raises(RuntimeError, match="companion"):
        run._gen3_require_companion_admission({"a": "RESULT: PASS\n", "b": "RESULT: PASS\n"})
    run._gen3_require_companion_admission(_texts())
    assert [n for n in notes if n.startswith("COMPANION_ADMISSION a: [client] [SLink-gen3] gen3_frlg/firered (companion by hash)")]
    clean = _run(tmp_path, monkeypatch, "firered", companion=False)
    notes.clear()
    monkeypatch.setattr(clean, "_pydec_note", notes.append)
    clean._gen3_require_companion_admission({"a": "RESULT: PASS\n", "b": "RESULT: PASS\n"})   # not a companion run: no demand
    assert notes == []


def test_the_protected_span_probe_proves_only_a_by_hash_and_needs_no_flag(tmp_path, monkeypatch):
    """probe_protected_span_flip_gen3: B is an UNKNOWN-hash cart on purpose, so --gen3-companion demands the by-hash proof of A alone, and the\n    launch preflight does not treat the probe's staged companion carts as clean ones."""
    run = _run(tmp_path, monkeypatch, "firered", scenario="probe_protected_span_flip_gen3")
    sides = {"a": "firered", "b": "leafgreen"}
    monkeypatch.setattr(run, "_gen3_title", lambda inst: sides[inst])
    notes = []
    monkeypatch.setattr(run, "_pydec_note", notes.append)
    flipped_b = {"a": _texts()["a"], "b": "boot\n[SLink-gen3] refused: unknown cart\nRESULT: PASS\n"}
    run._gen3_require_companion_admission(flipped_b)                                  # B has no by-hash line: fine for the probe
    assert [n for n in notes if n.startswith("COMPANION_ADMISSION a:")] and not [n for n in notes if "COMPANION_ADMISSION b" in n]
    with pytest.raises(RuntimeError, match="companion"):                              # A is still held to the proof
        run._gen3_require_companion_admission({"a": "RESULT: PASS\n", "b": flipped_b["b"]})
    ordinary = _run(tmp_path, monkeypatch, "firered")                                  # negative control: any other row still needs both
    monkeypatch.setattr(ordinary, "_gen3_title", lambda inst: sides[inst])
    with pytest.raises(RuntimeError, match="companion"):
        ordinary._gen3_require_companion_admission(flipped_b)
    for companion in (False, True):
        run.gen3_companion = companion
        assert run._gen3_launch_refusal_problems() == [], companion
    ordinary.gen3_companion = False
    assert ordinary._gen3_launch_refusal_problems()                                   # a clean plan row is still refused up front
