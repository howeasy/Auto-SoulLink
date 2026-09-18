"""The pureRGB titles in the Python harness, and the end of the Lua literal sweep (P3b-e).

The harness keys almost everything by "rom key" — the ROM table, the SaveRAM filename BizHawk
will use, the fixture path, the run config. `purered`/`pureblue`/`puregreen` join `red`/`blue`/
`yellow` in those tables, with three differences that are all facts about the cartridge rather
than choices: the ROM is a BUILT file (pinned by sha1 in `data/purergb_sources.lock.json`), the
SaveRAM name is derived from the staged FILENAME (BizHawk's gamedb has never seen the hash), and
the run config pins GBC + not-SGB.

No emulator: the ROMs themselves are only touched when a checkout happens to have them.
"""

from __future__ import annotations

import json
import os
import sys

import pytest
from lupa import LuaRuntime

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import gen1_fixtures as fixtures  # noqa: E402
import gen1_playthrough as g1  # noqa: E402
from run_gb_gate import GENS, ROM_TO_GEN  # noqa: E402

PURE = ("purered", "pureblue", "puregreen")
VANILLA = ("red", "blue", "yellow")


def _lock() -> dict:
    with open(g1.PURERGB_LOCK, encoding="utf-8") as handle:
        return json.load(handle)["outputs"]


# ── the ROM table ───────────────────────────────────────────────────────────────────────────────


def test_every_pure_key_is_a_rom_key_the_gate_accepts():
    for key in PURE:
        assert key in ROM_TO_GEN and ROM_TO_GEN[key] == "gen1"
        assert key in GENS["gen1"]["saveram_names"]
        assert key in GENS["gen1"]["patched"]
        assert f"{key}_cold" in GENS["gen1"]["patched"]


def test_the_pure_rows_boot_cold_from_the_fixture_and_the_cold_row_has_none():
    for key in PURE:
        base, rom_rel, name = GENS["gen1"]["patched"][key]
        assert base == key and rom_rel is None            # staged from the lock, seeded from the fixture
        assert GENS["gen1"]["patched"][f"{key}_cold"][0] is None   # cold: no save to seed
        assert GENS["gen1"]["patched"][f"{key}_cold"][2] == name


def test_the_fixture_path_is_the_one_the_fixture_builder_writes():
    for key in PURE:
        for target in g1.TARGETS:
            assert g1.fixture_path(key, target) == os.path.join(
                _REPO, "tests", "fixtures", "gen1", f"{key}_{target}.SaveRAM")


def test_the_fixture_builder_knows_the_pure_titles():
    for key in PURE:
        assert key in fixtures.SAVERAM_NAME and key in fixtures.DUMP
        assert fixtures.DUMP[key] == f"patch/build/gen1_{key}.gbc"


def test_staging_keeps_the_gbc_extension_and_the_key_in_the_name(monkeypatch, tmp_path):
    """`staged_rom` is what every lane launches; the pure build must keep its own name.

    BUILD is redirected: staging must be proven without writing a fake cartridge into the repo
    (a leftover gen1_purered.gbc would be treated as a staged pure build by the next run).
    """
    fake = tmp_path / "pokered.gbc"
    fake.write_bytes(b"\x00" * 32)
    monkeypatch.setattr(g1, "purergb_dump", lambda _key: str(fake))
    monkeypatch.setattr(g1, "REPO", str(tmp_path))
    monkeypatch.setattr(g1, "BUILD", str(tmp_path / "patch" / "build"))
    assert g1.staged_rom("purered") == "patch/build/gen1_purered.gbc"
    assert (tmp_path / "patch" / "build" / "gen1_purered.gbc").read_bytes() == b"\x00" * 32


def test_a_missing_pure_rom_names_the_lock_output_and_the_env_var(monkeypatch, tmp_path):
    monkeypatch.setattr(g1, "PURERGB_ROMS", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="SLINK_PURERGB_ROMS"):
        g1.purergb_dump("purered")


def test_a_pure_rom_whose_sha1_is_not_the_locks_is_refused(monkeypatch, tmp_path):
    """The whole point of the lock: a rebuilt or randomized cartridge must not be run as canon."""
    monkeypatch.setattr(g1, "PURERGB_ROMS", str(tmp_path))
    (tmp_path / _lock()["pokered"]["filename"]).write_bytes(b"\x00" * 64)
    with pytest.raises(ValueError, match="not the pinned purered build"):
        g1.purergb_dump("purered")


@pytest.mark.parametrize("key", PURE)
def test_the_pinned_builds_resolve_when_they_are_present(key):
    """Skipped in a checkout without the built pureRGB cartridges (the usual case)."""
    try:
        path = g1.purergb_dump(key)
    except FileNotFoundError as exc:
        pytest.skip(f"pureRGB builds not staged here: {exc}")
    assert os.path.basename(path) == _lock()[g1.PURERGB_KEYS[key]]["filename"]


def test_the_vanilla_rom_table_is_unchanged():
    assert g1.ROMS == {
        "red": "Pokemon - Red Version (USA, Europe) (SGB Enhanced).gb",
        "blue": "Pokemon - Blue Version (USA, Europe) (SGB Enhanced).gb",
        "yellow": "Pokemon - Yellow Version (USA, Europe).gbc",
    }
    assert g1.dump_keys() == VANILLA + PURE
    assert GENS["gen1"]["saveram_names"]["red"] == "Pokemon - Red Version (USA, Europe).SaveRAM"
    assert GENS["gen1"]["saveram_names"]["blue"] == "Pokemon - Blue Version (USA, Europe).SaveRAM"
    assert GENS["gen1"]["saveram_names"]["yellow"] == "Pokemon - Yellow Version (USA, Europe).SaveRAM"
    assert GENS["gen1"]["patched"]["blue_patched"][2] == "slink blue.SaveRAM"


# ── the SaveRAM name rule ───────────────────────────────────────────────────────────────────────


def test_save_name_for_reproduces_both_known_bizhawk_fallbacks():
    """Measured on this machine's Gameboy/SaveRAM directory, so the rule is evidence, not theory."""
    assert g1.save_name_for("patch/build/gen1_red_ap.gb") == "gen1 red ap.SaveRAM"
    assert g1.save_name_for("patch/gen1/build/slink_blue.gb") == "slink blue.SaveRAM"
    assert g1.save_name_for("patch/gen1/build/slink_red_randomized.gb") == "slink red randomized.SaveRAM"


def test_every_pure_saveram_name_is_the_filename_derivation():
    for key in PURE:
        rom_rel = fixtures.DUMP[key]
        assert GENS["gen1"]["saveram_names"][key] == g1.save_name_for(rom_rel)


def test_run_gate_resolves_a_pure_key_to_the_staged_build_and_says_how_to_get_it(monkeypatch, tmp_path):
    """No emulator: the gate refuses at ROM resolution, which is the branch a pure key takes."""
    import run_gb_gate

    dump = tmp_path / "pokered.gbc"
    dump.write_bytes(b"\x00" * 32)
    monkeypatch.setattr(g1, "purergb_dump", lambda _key: str(dump))
    monkeypatch.setattr(g1, "REPO", str(tmp_path))
    monkeypatch.setattr(g1, "BUILD", str(tmp_path / "patch" / "build"))
    (tmp_path / "patch" / "build").mkdir(parents=True)
    (tmp_path / "patch" / "build" / "gen1_purered.gbc").unlink(missing_ok=True)
    with pytest.raises(FileNotFoundError, match="pinned pureRGB source"):
        run_gb_gate.run_gate("lua/tests/test_gen1_inspect_gate.lua", rom_key="purered")


def test_the_launcher_only_names_a_title_for_a_build_that_cannot_be_admitted(monkeypatch):
    """A vanilla companion-patch artifact is vanilla-layout and unadmitted, so the gate is told its
    family; a pureRGB key is never named from outside (it must be admitted on its bytes)."""
    import run_gb_gate

    monkeypatch.delenv("SLINK_GATE_TITLE", raising=False)
    assert "SLINK_GATE_TITLE" not in run_gb_gate.gate_env("red_patched", None)
    assert run_gb_gate.gate_env("red_patched", "red")["SLINK_GATE_TITLE"] == "red"
    assert [run_gb_gate.named_title(k) for k in ("red_patched", "blue_patched", "red_rand_patched")] == \
           ["red", "blue", "red"]
    for key in PURE + VANILLA + tuple(f"{k}_cold" for k in VANILLA + PURE):
        assert run_gb_gate.named_title(key) is None
    assert run_gb_gate.gate_env("red")["SLINK_ROOT"].replace(chr(92), "/") == _REPO.replace(chr(92), "/")


# ── the run config ──────────────────────────────────────────────────────────────────────────────


def _config(tmp_path, name="cfg.ini"):
    runtime = {"ConsoleMode": 0, "RealTimeRTC": True, "InitialTime": 5}
    cfg = {
        "SoundEnabled": True,
        "GBCore": "Gambatte",
        "CoreSyncSettings": {
            "BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy": runtime,
        },
    }
    path = tmp_path / name
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def _written(src, dst, **kwargs) -> dict:
    g1.write_run_config(str(src), str(dst), **kwargs)
    with open(dst, encoding="utf-8-sig") as handle:
        return json.load(handle)


def test_a_pure_run_pins_gbc_and_not_sgb(tmp_path):
    cfg = _written(_config(tmp_path), tmp_path / "pure.ini", purergb=True)
    assert cfg["GbAsSgb"] is False
    runtime = cfg["CoreSyncSettings"]["BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy"]
    # GambatteSyncSettings.ConsoleModeType: Auto 0, GB 1, GBC 2, GBA 3, SGB2 4.
    assert runtime["ConsoleMode"] == 2
    assert runtime["RealTimeRTC"] is False and runtime["InitialTime"] == 0


def test_a_vanilla_run_leaves_the_console_alone(tmp_path):
    cfg = _written(_config(tmp_path), tmp_path / "vanilla.ini")
    assert "GbAsSgb" not in cfg
    runtime = cfg["CoreSyncSettings"]["BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy"]
    assert runtime["ConsoleMode"] == 0


# ── the client agrees on the titles and the sha1s ────────────────────────────────────────────────


@pytest.fixture(scope="module")
def lua():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().memory = runtime.table(read_u8=lambda _addr, _domain=None: 0)
    runtime.globals().gameinfo = runtime.table(getromhash=lambda: "ab" * 20)
    return runtime


def _dofile(lua, rel):
    return lua.execute(f'return dofile("{os.path.join(_REPO, rel).replace(chr(92), "/")}")')


@pytest.mark.parametrize("key", PURE)
def test_entry_admits_each_pure_sha1_as_its_own_title(lua, key):
    """The harness key and the pack's admitted title are the same string: sha1 -> title, and the
    pack is the pure one — which is what makes gen1_gate hand the driver the pure facts table."""
    entry = _dofile(lua, "lua/gen1/entry.lua")
    sha = _lock()[g1.PURERGB_KEYS[key]]["sha1"]
    admitted = entry.admit(lua.table(root=_REPO.replace("\\", "/"),
                                     json=_dofile(lua, "lua/json_codec.lua"), rom_sha1=sha,
                                     indatabase=False, header="POKEMON RED"))
    assert admitted["title"] == key
    assert admitted["pack"] == "gen1_purergb"
    assert admitted["kind"] == "clean"


def test_entry_still_admits_the_vanilla_sha1s(lua):
    entry = _dofile(lua, "lua/gen1/entry.lua")
    with open(os.path.join(_REPO, "data", "games", "gen1_rby", "profile.json"), encoding="utf-8") as handle:
        titles = json.load(handle)["titles"]
    admitted = entry.admit(lua.table(root=_REPO.replace("\\", "/"),
                                     json=_dofile(lua, "lua/json_codec.lua"),
                                     rom_sha1=titles["red"]["rom_sha1"], indatabase=False,
                                     header="POKEMON RED"))
    assert admitted["title"] == "red" and admitted["pack"] == "gen1_rby"


# ── the scripted host: title -> facts table and symbols ─────────────────────────────────────────


def _play(lua, title, **opts):
    host = _dofile(lua, "lua/tests/gen1_scripted_play.lua")
    return host.new(_REPO.replace("\\", "/"), title, "a", lua.table(**opts))


@pytest.mark.parametrize("title", PURE)
def test_a_pure_title_takes_the_pure_facts_and_the_pure_symbols(lua, title):
    play = _play(lua, title)
    assert play.expected["facts"]["TRAINER"]["OPP_RIVAL1"] == 221
    assert play.expected["facts"]["EVENT"]["OAK_GOT_PARCEL"] == 37
    assert play.modules["lab"]["file"] == "gen1_rb_ball_gate_inputs.lua"
    # wCurMap moved +8 on pureRGB (PLAN A9): 0xD35E vanilla, 0xD366 pure.
    assert play.symbols["wCurMap"] == 0xD366


@pytest.mark.parametrize("title", VANILLA)
def test_a_vanilla_title_keeps_the_vanilla_facts(lua, title):
    play = _play(lua, title)
    assert play.expected["facts"]["TRAINER"]["OPP_RIVAL1"] == 225
    assert play.symbols["wCurMap"] in (0xD35E, 0xD35D)      # Red/Blue, Yellow
    expected_lab = "gen1_y_ball_gate_inputs.lua" if title == "yellow" else "gen1_rb_ball_gate_inputs.lua"
    assert play.modules["lab"]["file"] == expected_lab


def test_an_unknown_title_is_still_refused(lua):
    with pytest.raises(Exception, match="Red/Blue lab route and a Yellow one"):
        _play(lua, "green")


def test_the_facts_escape_hatch_still_overrides_the_title(lua):
    """`opts.facts` stays for a caller that knows better than the title (the pure probes did)."""
    play = _play(lua, "red", facts="gen1_pure_facts.lua")
    assert play.expected["facts"]["TRAINER"]["OPP_RIVAL1"] == 221
