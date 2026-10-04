"""HOST MODEL/FILE checks for the command planner; never execute a compiler."""

import hashlib
import json
from pathlib import Path

import pytest

from tools import build_gen4_companion as planner

# MODEL snapshot of the verified ad7a3afa assignments. FILE tests below read the
# actual tree separately. No Makefile, C source, or compiler is executed here.
MAKE = "MWCCVER := 2.0/sp2p2\nPROC := arm946e\nOPTFLAGS := -O4,p\n"
CONFIG = """GAME_VERSION ?= HEARTGOLD
GAME_REMASTER ?= 0
GAME_LANGUAGE ?= ENGLISH
GF_DEFINES := -D$(GAME_VERSION) -DGAME_REMASTER=$(GAME_REMASTER) -D$(GAME_LANGUAGE)
ifeq ($(NO_GF_ASSERT),)
GF_DEFINES += -DPM_KEEP_ASSERTS
endif
GLB_DEFINES := -DSDK_ARM9 -DSDK_CODE_ARM -DSDK_FINALROM
DEFINES = $(GF_DEFINES) $(GLB_DEFINES) $(CLI_DEFINES)
"""
COMMON = """MWCC = $(TOOLSDIR)/mwccarm/$(MWCCVER)/mwccarm.exe
EXCCFLAGS := -Cpp_exceptions off
MWCFLAGS = $(DEFINES) $(OPTFLAGS) -sym on -enum int -lang c99 $(EXCCFLAGS) -gccext,on -proc $(PROC) -msgstyle gcc -gccinc -i ./src -i ./include -i ./include/library -i $(WORK_DIR)/files -I$(WORK_DIR)/lib/include -ipa file -interworking -inline on,noauto -char signed -W all -W pedantic -W noimpl_signedunsigned -W noimplicitconv -W nounusedarg -W nomissingreturn -W error
MW_COMPILE = $(WINE) $(MWCC) $(MWCFLAGS)
DEPFLAGS := -gccdep -MD
MW_COMPILE += $(DEPFLAGS)
"""


@pytest.fixture
def model(tmp_path, monkeypatch):
    pret = tmp_path / "pret"
    pret.mkdir()
    texts = dict(zip(planner.BUILD_FILES, (MAKE, COMMON, CONFIG), strict=True))
    for name, text in texts.items():
        (pret / name).write_bytes(text.encode())

    def git(root, *args):
        assert root == pret
        if args == ("rev-parse", "HEAD"):
            return planner.PRET_PIN
        assert args[0] == "show"
        return texts[args[1].split(":", 1)[1]].strip()

    monkeypatch.setattr(planner, "_git", git)
    repo = tmp_path / "repo"
    card_dir = repo / "patch/src/nds/gen4"
    card_dir.mkdir(parents=True)
    # Actual C2/C3/C5 files are the census input, not a fake empty scanner target.
    for source in (planner.ROOT / "patch/src/nds/gen4").iterdir():
        if source.suffix in (".c", ".h"):
            (card_dir / source.name).write_bytes(source.read_bytes())
    out = tmp_path / "out"

    def build(title="hgss", cards=(), version=None):
        return planner.plan(title, list(cards), out, pret_root=pret,
                            repo_root=repo, game_version=version)

    return build, pret, repo, out, texts


def assert_content(data, title, cards, version="HEARTGOLD"):
    assert data["title"] == title
    assert data["qualified"] is False and data["executes"] is False
    names = [Path(row["source"]).name for row in data["objects"]]
    expected = ["beacon.c", "dispatch.c"] + [f"{c}.c" for c in ("sound", "trade") if c in cards]
    assert names == expected
    switches = [f"-DSLINK_GEN4_{c.upper()}" for c in ("sound", "trade") if c in cards]
    assert data["switches"] == switches
    includes = data["include_dirs"]
    assert includes == [data["pret_root"] + "/include",
                        str(Path(data["objects"][0]["source"]).parent).replace("\\", "/"),
                        str(Path(data["objects"][0]["source"]).parents[1] / "common").replace("\\", "/")]
    # sound.c:12-16: game <sound.h> must precede the local card sound.h.
    prefix = [token for directory in includes for token in ("-i", directory)]
    for row in data["objects"]:
        assert row["argv"][1:7] == prefix
        assert [v for v in row["argv"] if v.startswith("-DSLINK_GEN4_")] == switches
        assert row["object"] == data["out"] + "/" + Path(row["source"]).stem + ".o"
        assert row["argv"][-4:] == ["-c", "-o", row["object"], row["source"]]
    flags = data["pret_flags"]
    # Independent literal expectations: pret Makefile:1-7/common.mk:125/config.mk:35-42.
    assert flags[-14:] == ["-W", "all", "-W", "pedantic", "-W", "noimpl_signedunsigned",
                           "-W", "noimplicitconv", "-W", "nounusedarg", "-W", "nomissingreturn",
                           "-W", "error"]
    assert flags[flags.index("-proc"):flags.index("-proc") + 2] == ["-proc", "arm946e"]
    assert "-O4,p" in flags
    assert flags[flags.index("-sym") + 1] == "on"
    assert flags[flags.index("-ipa") + 1] == "file"
    assert flags[flags.index("-Cpp_exceptions") + 1] == "off"
    assert data["mwcc_version"] == "2.0/sp2p2"
    assert data["dependency_flags"] == ["-gccdep", "-MD"]
    assert "companion_ipa_file" in data["unverified"]
    assert "companion_sym_on" in data["unverified"]
    if title == "hgss":
        assert flags[:7] == [f"-D{version}", "-DGAME_REMASTER=0", "-DENGLISH", "-DPM_KEEP_ASSERTS",
                             "-DSDK_ARM9", "-DSDK_CODE_ARM", "-DSDK_FINALROM"]
    else:
        assert flags[0] == "-D${GAME_VERSION_UNVERIFIED}"
        assert "hge_toolchain" in data["unverified"]
        assert not any(v in flags for v in ("-DHEARTGOLD", "-DSOULSILVER"))


@pytest.mark.parametrize("title", ["hgss", "hge"])
@pytest.mark.parametrize("cards", [(), ("sound",), ("trade",), ("trade", "sound")])
def test_plan_content_and_determinism(model, title, cards):
    build, pret, _, out, texts = model
    data = build(title, cards)
    assert_content(data, title, cards)
    assert data["pret_source_sha256"] == {
        name: hashlib.sha256((pret / name).read_bytes()).hexdigest() for name in texts
    }
    assert planner.plan_json(data) == planner.plan_json(build(title, tuple(reversed(cards))))
    assert json.loads(planner.plan_json(data)) == data
    assert not out.exists()  # Planning never writes objects or JSON.


def test_soulsilver_substitution(model):
    data = model[0](version="SOULSILVER")
    assert_content(data, "hgss", (), "SOULSILVER")


def test_template_parsed_not_hardcoded(model):
    build, pret, _, _, texts = model
    texts["Makefile"] = MAKE.replace("-O4,p", "-O3,p").replace("arm946e", "arm9")
    (pret / "Makefile").write_bytes(texts["Makefile"].encode())
    data = build()
    assert "-O3,p" in data["pret_flags"] and "-O4,p" not in data["pret_flags"]
    assert data["pret_flags"][data["pret_flags"].index("-proc") + 1] == "arm9"


@pytest.mark.parametrize("value,reason", [
    (COMMON.replace("$(PROC)", "$(UNPROVEN)"), "PRET_VARIABLE_UNSUPPORTED"),
    (COMMON.replace("-W error", "-W all"), "PRET_WARNING_ERROR_MISSING"),
    (COMMON.replace("$(WINE) $(MWCC) $(MWCFLAGS)", "$(shell touch BAD)"),
     "PRET_COMPILE_TEMPLATE_UNSUPPORTED"),
])
def test_unknown_or_weakened_template_refuses(model, value, reason):
    build, pret, _, _, texts = model
    texts["common.mk"] = value
    (pret / "common.mk").write_bytes(value.encode())
    with pytest.raises(planner.Refused, match=reason):
        build()


@pytest.mark.parametrize("title,cards,version,reason", [
    ("platinum", (), None, "UNKNOWN_TITLE"),
    ("hgss", ("sound", "sound"), None, "DUPLICATE_CARD"),
    ("hgss", ("faint",), None, "UNKNOWN_CARD"),
    ("hgss", ("panel",), None, "CARD_SOURCE_MISSING: panel.c"),
    ("hgss", (), "DIAMOND", "UNKNOWN_GAME_VERSION"),
    ("hge", (), "HEARTGOLD", "HGE_GAME_VERSION_UNVERIFIED"),
])
def test_named_refusals(model, title, cards, version, reason):
    with pytest.raises(planner.Refused, match=reason):
        model[0](title, cards, version)


@pytest.mark.parametrize("out", ["C:/tmp/build", "C:build", "F:build", "build",
                                 "F:/out/../other", "F:/out/data:stream", "//host/share/out"])
def test_output_refusal(out):
    with pytest.raises(planner.Refused, match="OUT_"):
        planner.plan("hgss", [], out)


@pytest.mark.parametrize("kind", ["missing", "pin", "modified", "root"])
def test_pret_prerequisite_refusal(model, monkeypatch, kind):
    build, pret, _, _, _ = model
    if kind == "missing":
        (pret / "Makefile").unlink()
        reason = "PRET_FILE_MISSING"
    elif kind == "pin":
        monkeypatch.setattr(planner, "_git", lambda *args: "b" * 40)
        reason = "PRET_PIN_MISMATCH"
    elif kind == "modified":
        (pret / "common.mk").write_bytes((COMMON + "# drift\n").encode())
        reason = "PRET_FILE_MODIFIED"
    else:
        (pret / "Makefile").unlink()
        (pret / "config.mk").unlink()
        (pret / "common.mk").unlink()
        pret.rmdir()
        reason = "PRET_ROOT_MISSING"
    with pytest.raises(planner.Refused, match=reason):
        build()


@pytest.mark.parametrize("payload,reason", [
    ("static int leak;", "CENSUS_FILE_SCOPE_OBJECT"),
    ("static void (*p)(void *);", "CENSUS_FILE_SCOPE_OBJECT"),
    ("#define POINTER 0x01FFEC00u", "CENSUS_SPAN_LITERAL"),
    ("#define POINTER 0x01006C00u", "CENSUS_SPAN_LITERAL"),
    ("#define POINTER 0x00006C00u", "CENSUS_SPAN_LITERAL"),
])
def test_census_refuses_contaminated_plan(model, payload, reason):
    build, _, repo, _, _ = model
    path = repo / "patch/src/nds/gen4/beacon.c"
    path.write_bytes(path.read_bytes() + b"\n" + payload.encode())
    with pytest.raises(planner.Refused, match=reason):
        build()


def test_detector_agrees_with_existing_c2_on_real_files():
    from tests.unit.test_gen4_c2_beacon_source import file_scope_objects, span_literals

    for path in (planner.ROOT / "patch/src/nds/gen4").iterdir():
        if path.suffix in (".c", ".h"):
            text = path.read_text(encoding="utf-8")
            assert planner.file_scope_objects(text) == file_scope_objects(text)
            assert bool(planner.span_literals(text)) == bool(span_literals(text))


def test_panel_included_when_source_exists(model):
    build, _, repo, _, _ = model
    (repo / "patch/src/nds/gen4/panel.c").write_bytes(b"void panel(void) {}\n")
    data = build(cards=("panel",))
    assert [Path(row["source"]).name for row in data["objects"]] == ["beacon.c", "dispatch.c", "panel.c"]
    assert data["switches"] == ["-DSLINK_GEN4_PANEL"]


def test_missing_enabled_source_refuses(model):
    build, _, repo, _, _ = model
    (repo / "patch/src/nds/gen4/trade.c").unlink()
    with pytest.raises(planner.Refused, match="CARD_SOURCE_MISSING: trade.c"):
        build(cards=("trade",))


def test_cli_print_and_only_explicit_write(model, monkeypatch, capsys):
    _, pret, repo, out, _ = model
    real_plan = planner.plan
    monkeypatch.setattr(planner, "plan", lambda *a, **kw: real_plan(*a, repo_root=repo, **kw))
    args = ["hgss", "--pret-root", str(pret), "--out", str(out), "--card", "sound"]
    assert planner.main([*args, "--print"]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed)["cards"] == ["sound"]
    assert not out.exists()
    assert planner.main([*args, "--write-plan"]) == 0
    assert (out / "companion-plan.json").read_bytes() == printed.encode()
    assert sorted(p.name for p in out.iterdir()) == ["companion-plan.json"]
    assert planner.main([*args, "--card", "panel"]) == 1
    assert "CARD_SOURCE_MISSING" in capsys.readouterr().err


def test_print_write_modes_are_exclusive():
    with pytest.raises(SystemExit) as exc:
        planner.main(["hgss", "--out", "F:/example", "--print", "--write-plan"])
    assert exc.value.code == 2


@pytest.mark.parametrize("label,anchor,replacement", [
    ("wrong include order", "includes + flags + dependency_flags + switches",
     "flags + includes + dependency_flags + switches"),
    ("silently skip missing card", 'raise Refused(f"CARD_SOURCE_MISSING: {name}")',
     "units.remove(name)"),
    ("switch for disabled card", 'for c in enabled]\n    arguments',
     'for c in CARDS]\n    arguments'),
])
def test_planner_mutant_red_controls(model, monkeypatch, label, anchor, replacement):
    # Mutate the actual producer, not a hand-made invalid JSON receipt. Python
    # compilation succeeds; independent output/refusal assertions then go RED.
    source = Path(planner.__file__).read_text(encoding="utf-8")
    assert source.count(anchor) == 1, label
    namespace = {"__file__": planner.__file__, "__name__": "planner_mutant"}
    exec(compile(source.replace(anchor, replacement), planner.__file__, "exec"), namespace)
    namespace["_git"] = planner._git
    build, pret, repo, out, _ = model
    if label == "silently skip missing card":
        with pytest.raises(AssertionError, match="missing card escaped refusal"):
            try:
                namespace["plan"]("hgss", ["panel"], out, pret_root=pret, repo_root=repo)
            except namespace["Refused"]:
                pass
            else:
                raise AssertionError("missing card escaped refusal")
    else:
        data = namespace["plan"]("hgss", [], out, pret_root=pret, repo_root=repo)
        with pytest.raises(AssertionError):
            assert_content(data, "hgss", ())
    assert_content(build(), "hgss", ())  # Unmutated control remains green.


def test_pinned_pret_file_plan():
    if not planner.PRET_ROOT.is_dir():
        pytest.skip("PRET_ROOT_MISSING: pinned ad7a3afa FILE inputs unavailable")
    data = planner.plan("hgss", ["sound", "trade"], "F:/slink-work/tmp/gen4-plan-file")
    assert_content(data, "hgss", ("sound", "trade"))
    assert data["pret_pin"] == "ad7a3afa0cfc144fe6837c410cb95b2727217f54"


def test_planner_is_importable():
    from tools import build_gen4_companion as planner

    assert Path(__file__).resolve().parents[2] == planner.ROOT
