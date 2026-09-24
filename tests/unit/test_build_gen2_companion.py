"""tools/build_gen2_companion.py: overlay selection and the main.asm hook edit.

Fast, offline unit coverage of the deterministic parts (no rgbasm/make invocation -- that is
exercised by hand per the card's falsifier and recorded in the P4.1a report). What is covered
here: which files an overlay pulls in per repo (empty overlay vs. mailbox-only vs. mailbox +
Codex's future slink.asm), and that the main.asm hook is verify-then-replace-once, matching
tools/apply_purergb_overlay.py's discipline.
"""

import hashlib
import json
import re
import sys
from itertools import product
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import build_gen2_companion as bc  # noqa: E402

# ---------------------------------------------------------------- overlay_plan


def _no_gb_dir(tmp_path: Path) -> Path:
    """An isolated, guaranteed-absent patch/gb/ stand-in so tests don't depend on whether the
    real patch/gb/slink_abi.inc (Codex, card P4.1c) has landed in this checkout yet."""
    return tmp_path / "gb-does-not-exist"


def test_empty_src_dir_is_the_empty_overlay(tmp_path):
    gb_dir = _no_gb_dir(tmp_path)
    assert bc.overlay_plan("pokecrystal", tmp_path, gb_dir) == []
    assert bc.overlay_plan("pokegold", tmp_path, gb_dir) == []


@pytest.mark.parametrize("repo", ["pokecrystal", "pokegold"])
@pytest.mark.parametrize("copies", [0, 1, 2])
def test_sfx_overlay_requires_exact_reset_hook_and_gates_caps(tmp_path, repo, copies):
    checkout = _fake_checkout(tmp_path, repo)
    _write_real_delay_asm(checkout)
    anchor = "Reset::\n" + ("\tdi\n" if repo == "pokecrystal" else "") + "\tcall InitSound\n"
    path = checkout / "home/init.asm"
    path.write_text(anchor * copies + "\txor a\n\tld c, 32\n\tcall DelayFrames\n\n\tjr Init\n\n_Start::\n\tret\n")
    src = tmp_path / "src"
    src.mkdir()
    for name in ("slink.asm", "sfx.asm"):
        (src / name).write_text("; fixture\n")
    if copies != 1:
        before = (checkout / "main.asm").read_bytes()
        with pytest.raises(RuntimeError, match="Reset"):
            bc.apply_overlay(checkout, repo, src, _no_gb_dir(tmp_path))
        assert (checkout / "main.asm").read_bytes() == before
    else:
        bc.apply_overlay(checkout, repo, src, _no_gb_dir(tmp_path))
        main = (checkout / "main.asm").read_text()
        assert main.index("DEF SLINK_SFX_ENABLED EQU 1") < main.index('INCLUDE "engine/slink/slink.asm"')
        assert main.index('/slink.asm"') < main.index('/sfx.asm"')
        assert "call SlinkResetSoundBridge" in path.read_text()
        assert path.read_text().startswith(anchor)  # preserve the soft_reset U1 anchor
        assert "\tld c, 32\n\tcall SlinkResetSoundBridge\n" in path.read_text()


@pytest.mark.parametrize("repo", ["pokecrystal", "pokegold"])
@pytest.mark.parametrize("copies", [0, 2])
def test_reset_wait_hook_refuses_missing_or_duplicate_wait(tmp_path, repo, copies):
    checkout = _fake_checkout(tmp_path, repo)
    _write_real_delay_asm(checkout)
    anchor = "Reset::\n" + ("\tdi\n" if repo == "pokecrystal" else "") + "\tcall InitSound\n"
    wait = "\tld c, 32\n\tcall DelayFrames\n\n\tjr Init\n"
    (checkout / "home/init.asm").write_text(anchor + wait * copies + "\n_Start::\n\tret\n")
    src = tmp_path / "src"
    src.mkdir()
    for name in ("slink.asm", "sfx.asm"):
        (src / name).write_text("; fixture\n")
    with pytest.raises(RuntimeError, match="Reset"):
        bc.apply_overlay(checkout, repo, src, _no_gb_dir(tmp_path))


def test_sfx_absent_keeps_reset_and_caps_unchanged(tmp_path):
    checkout = _fake_checkout(tmp_path, "pokecrystal")
    _write_real_delay_asm(checkout)
    init = checkout / "home/init.asm"
    init.write_text("Reset::\n\tdi\n\tcall InitSound\n")
    before = init.read_bytes()
    src = tmp_path / "src"
    src.mkdir()
    (src / "slink.asm").write_text("; fixture\n")
    bc.apply_overlay(checkout, "pokecrystal", src, _no_gb_dir(tmp_path))
    assert init.read_bytes() == before
    assert "SLINK_SFX_ENABLED" not in (checkout / "main.asm").read_text()


def test_nonexistent_src_dir_is_also_the_empty_overlay(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert bc.overlay_plan("pokecrystal", missing, _no_gb_dir(tmp_path)) == []


def test_mailbox_stub_only_selects_the_repo_specific_file(tmp_path):
    gb_dir = _no_gb_dir(tmp_path)
    (tmp_path / "slink_mailbox_crystal.asm").write_text("; crystal\n")
    (tmp_path / "slink_mailbox_goldsilver.asm").write_text("; gold/silver\n")
    crystal_plan = bc.overlay_plan("pokecrystal", tmp_path, gb_dir)
    gold_plan = bc.overlay_plan("pokegold", tmp_path, gb_dir)
    assert crystal_plan == [("slink_mailbox.asm", tmp_path / "slink_mailbox_crystal.asm", True)]
    assert gold_plan == [("slink_mailbox.asm", tmp_path / "slink_mailbox_goldsilver.asm", True)]


def test_shared_slink_asm_is_included_for_both_repos_when_present(tmp_path):
    gb_dir = _no_gb_dir(tmp_path)
    (tmp_path / "slink_mailbox_crystal.asm").write_text("; crystal\n")
    (tmp_path / "slink_mailbox_goldsilver.asm").write_text("; gold/silver\n")
    (tmp_path / "slink.asm").write_text("; codex P4.1c\n")
    names = [name for name, _path, _include in bc.overlay_plan("pokecrystal", tmp_path, gb_dir)]
    assert names == ["slink_mailbox.asm", "slink.asm"]


def test_shared_slink_asm_alone_without_a_mailbox_stub_is_still_picked_up(tmp_path):
    gb_dir = _no_gb_dir(tmp_path)
    (tmp_path / "slink.asm").write_text("; codex P4.1c\n")
    names = [name for name, _path, _include in bc.overlay_plan("pokecrystal", tmp_path, gb_dir)]
    assert names == ["slink.asm"]


# ---------------------------------------------------------------- shared ABI header (gb_dir)
# Coordinator follow-up gen2-p41a-abi-copy: Codex's P4.1c owns patch/gb/slink_abi.inc (shared
# with Gen 1) and slink.asm INCLUDEs it as engine/slink/slink_abi.inc. This tool copies -- never
# duplicates -- that one committed file. It is copy-only: no main.asm INCLUDE, because slink.asm
# is the file that references it.


def test_shared_abi_header_absent_is_a_no_op(tmp_path):
    """The file doesn't exist yet (Codex writes it in P4.1c); absence must never be an error."""
    gb_dir = _no_gb_dir(tmp_path)
    assert bc.overlay_plan("pokecrystal", tmp_path, gb_dir) == []
    (tmp_path / "slink_mailbox_crystal.asm").write_text("; crystal\n")
    names = [name for name, _path, _include in bc.overlay_plan("pokecrystal", tmp_path, gb_dir)]
    assert bc.SHARED_ABI_NAME not in names


def test_shared_abi_header_present_is_copied_but_not_included(tmp_path):
    gb_dir = tmp_path / "gb"
    gb_dir.mkdir()
    (gb_dir / bc.SHARED_ABI_NAME).write_text("; shared ABI (patch/gb/slink_abi.inc)\n")
    plan = bc.overlay_plan("pokecrystal", tmp_path, gb_dir)
    assert (bc.SHARED_ABI_NAME, gb_dir / bc.SHARED_ABI_NAME, False) in plan


# --------------------------------------------------- external_source_hashes (input provenance)
# Coordinator follow-up (Codex review): sources_sha256 only hashed files inside src_dir, so a
# file apply_overlay copies from elsewhere (the shared ABI include) was compiled into the ROM but
# missing from the input provenance. external_source_hashes() fills that gap, keyed by the file's
# path relative to the repo root, and never duplicates what sources_sha256 already covers.


def test_external_source_hashes_empty_when_abi_include_absent(tmp_path):
    gb_dir = _no_gb_dir(tmp_path)
    assert bc.external_source_hashes(["pokecrystal", "pokegold"], tmp_path, gb_dir) == {}


def test_external_source_hashes_includes_the_abi_include_when_present(tmp_path):
    gb_dir = tmp_path / "gb"
    gb_dir.mkdir()
    abi_path = gb_dir / bc.SHARED_ABI_NAME
    abi_path.write_text("; shared ABI\n")

    hashes = bc.external_source_hashes(["pokecrystal", "pokegold"], tmp_path, gb_dir)

    resolved = abi_path.resolve()
    expected_key = (resolved.relative_to(bc.ROOT).as_posix() if resolved.is_relative_to(bc.ROOT)
                    else resolved.as_posix())
    assert expected_key in hashes, f"missing {expected_key!r} in {hashes!r}"
    assert hashes[expected_key] == bc._sha256(abi_path.read_bytes())
    # Shared across both repos: one entry, not one per repo.
    assert len(hashes) == 1


def test_external_source_hashes_never_duplicates_files_already_inside_src_dir(tmp_path):
    """A file that happens to live under src_dir (e.g. the mailbox stub) is sources_sha256's job,
    not external_source_hashes'."""
    (tmp_path / "slink_mailbox_crystal.asm").write_text("; crystal\n")
    hashes = bc.external_source_hashes(["pokecrystal"], tmp_path, _no_gb_dir(tmp_path))
    assert hashes == {}


# ---------------------------------------------------------------- apply_overlay


def _fake_checkout(tmp_path: Path, repo: str) -> Path:
    """A minimal checkout: just enough of main.asm for the anchor to match once."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    if repo == "pokecrystal":
        body = (
            'SECTION "Crystal Events", ROMX\n\n'
            'INCLUDE "engine/events/battle_tower/load_trainer.asm"\n'
            'INCLUDE "engine/events/odd_egg.asm"\n\n\n'
            'SECTION "Stadium 2 Checksums", ROMX[$7DE0], BANK[$7F]\n'
            '\tds $220\n'
        )
    else:
        body = (
            'SECTION "Credits Strings", ROMX\n\n'
            'INCLUDE "data/credits_strings.asm"\n\n\n'
            'SECTION "Stadium 2 Checksums", ROMX[$7DF8], BANK[$7F]\n'
            '\tds $208\n'
        )
    (checkout / "main.asm").write_text(body, encoding="utf-8")
    return checkout


@pytest.mark.parametrize("repo", ["pokecrystal", "pokegold"])
def test_empty_overlay_touches_nothing(tmp_path, repo):
    checkout = _fake_checkout(tmp_path, repo)
    before = (checkout / "main.asm").read_text(encoding="utf-8")
    applied = bc.apply_overlay(checkout, repo, tmp_path / "empty-src", _no_gb_dir(tmp_path))
    assert applied == []
    assert (checkout / "main.asm").read_text(encoding="utf-8") == before
    assert not (checkout / bc.OVERLAY_DST).exists()


@pytest.mark.parametrize("repo,stub_name", [
    ("pokecrystal", "slink_mailbox_crystal.asm"),
    ("pokegold", "slink_mailbox_goldsilver.asm"),
])
def test_mailbox_only_overlay_copies_the_stub_and_hooks_main_asm(tmp_path, repo, stub_name):
    checkout = _fake_checkout(tmp_path, repo)
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / stub_name).write_text('SECTION "SLink Mailbox", WRAM0[$0000]\n\tds 1\n')

    applied = bc.apply_overlay(checkout, repo, src_dir, _no_gb_dir(tmp_path))

    assert applied == ["slink_mailbox.asm"]
    copied = checkout / bc.OVERLAY_DST / "slink_mailbox.asm"
    assert copied.read_text(encoding="utf-8") == (src_dir / stub_name).read_text(encoding="utf-8")
    main_text = (checkout / "main.asm").read_text(encoding="utf-8")
    assert 'INCLUDE "engine/slink/slink_mailbox.asm"' in main_text
    # The anchor's tail (the fixed-address suffix, which differs per repo) survives untouched.
    assert 'SECTION "Stadium 2 Checksums", ROMX[$7' in main_text
    # Nothing else in main.asm moved: exactly one INCLUDE line was inserted.
    assert main_text.count('INCLUDE "engine/slink/slink_mailbox.asm"') == 1


def test_apply_overlay_refuses_a_checkout_missing_the_anchor(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "main.asm").write_text("; not a real pokecrystal main.asm\n", encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "slink_mailbox_crystal.asm").write_text('SECTION "x", WRAM0[$0000]\n')

    with pytest.raises(RuntimeError, match="exactly once"):
        bc.apply_overlay(checkout, "pokecrystal", src_dir, _no_gb_dir(tmp_path))


def test_apply_overlay_refuses_a_checkout_with_the_anchor_twice(tmp_path):
    checkout = _fake_checkout(tmp_path, "pokecrystal")
    main_path = checkout / "main.asm"
    main_path.write_text(main_path.read_text(encoding="utf-8") * 2, encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "slink_mailbox_crystal.asm").write_text('SECTION "x", WRAM0[$0000]\n')

    with pytest.raises(RuntimeError, match="exactly once"):
        bc.apply_overlay(checkout, "pokecrystal", src_dir, _no_gb_dir(tmp_path))


def test_apply_overlay_copies_shared_abi_header_alongside_the_mailbox_stub(tmp_path):
    checkout = _fake_checkout(tmp_path, "pokecrystal")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "slink_mailbox_crystal.asm").write_text('SECTION "SLink Mailbox", WRAM0[$0000]\n\tds 1\n')
    gb_dir = tmp_path / "gb"
    gb_dir.mkdir()
    (gb_dir / bc.SHARED_ABI_NAME).write_text("; shared ABI\n")

    applied = bc.apply_overlay(checkout, "pokecrystal", src_dir, gb_dir)

    assert bc.SHARED_ABI_NAME in applied
    copied = checkout / bc.OVERLAY_DST / bc.SHARED_ABI_NAME
    assert copied.read_text(encoding="utf-8") == "; shared ABI\n"
    # Copy-only: it is never given its own main.asm INCLUDE line (slink.asm will INCLUDE it).
    main_text = (checkout / "main.asm").read_text(encoding="utf-8")
    assert f'INCLUDE "{bc.OVERLAY_DST}/{bc.SHARED_ABI_NAME}"' not in main_text


def test_apply_overlay_with_only_the_shared_abi_header_never_touches_main_asm(tmp_path):
    """A copy-only file with no includable consumer yet must not trigger the main.asm hook --
    this keeps the empty-overlay falsifier valid even after patch/gb/slink_abi.inc lands."""
    checkout = _fake_checkout(tmp_path, "pokecrystal")
    before = (checkout / "main.asm").read_text(encoding="utf-8")
    gb_dir = tmp_path / "gb"
    gb_dir.mkdir()
    (gb_dir / bc.SHARED_ABI_NAME).write_text("; shared ABI\n")

    applied = bc.apply_overlay(checkout, "pokecrystal", tmp_path / "empty-src", gb_dir)

    assert applied == [bc.SHARED_ABI_NAME]
    assert (checkout / "main.asm").read_text(encoding="utf-8") == before
    assert (checkout / bc.OVERLAY_DST / bc.SHARED_ABI_NAME).is_file()


# ---------------------------------------------------------------- DelayFrame hook (home/delay.asm)
# Coordinator follow-up gen2-p41a-delay-hook: applied only when slink.asm (card P4.1c) is present,
# verify-then-replace-once, same size (5 bytes either way) -- this tool owns just the source edit,
# never the ROM0 bridge body (Codex's, in slink.asm).


def _write_real_delay_asm(checkout: Path) -> None:
    (checkout / "home").mkdir(parents=True, exist_ok=True)
    (checkout / "home" / "delay.asm").write_text(
        'DelayFrame::\n; Wait for one frame\n\tld a, 1\n\tld [wVBlankOccurred], a\n\n'
        '; Wait for the next VBlank, halting to conserve battery\n.halt\n\thalt\n\tnop\n'
        '\tld a, [wVBlankOccurred]\n\tand a\n\tjr nz, .halt\n\tret\n',
        encoding="utf-8",
    )


def test_delay_hook_not_applied_when_slink_asm_absent(tmp_path):
    checkout = _fake_checkout(tmp_path, "pokecrystal")
    _write_real_delay_asm(checkout)
    before = (checkout / "home" / "delay.asm").read_text(encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "slink_mailbox_crystal.asm").write_text('SECTION "SLink Mailbox", WRAM0[$0000]\n\tds 1\n')

    applied = bc.apply_overlay(checkout, "pokecrystal", src_dir, _no_gb_dir(tmp_path))

    assert "slink.asm" not in applied
    assert (checkout / "home" / "delay.asm").read_text(encoding="utf-8") == before


def test_delay_hook_applied_when_slink_asm_present(tmp_path):
    checkout = _fake_checkout(tmp_path, "pokecrystal")
    _write_real_delay_asm(checkout)
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "slink_mailbox_crystal.asm").write_text('SECTION "SLink Mailbox", WRAM0[$0000]\n\tds 1\n')
    (src_dir / "slink.asm").write_text("; codex P4.1c\n")

    applied = bc.apply_overlay(checkout, "pokecrystal", src_dir, _no_gb_dir(tmp_path))

    assert "slink.asm" in applied
    delay_text = (checkout / "home" / "delay.asm").read_text(encoding="utf-8")
    assert "call SlinkDelayFrameBridge" in delay_text
    assert "\tld a, 1\n\tld [wVBlankOccurred], a\n" not in delay_text
    # Everything after the lead-in (the .halt loop) is untouched.
    assert ".halt\n\thalt\n\tnop\n\tld a, [wVBlankOccurred]\n\tand a\n\tjr nz, .halt\n\tret\n" in delay_text


def test_apply_delay_hook_refuses_a_missing_anchor(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / "home").mkdir(parents=True)
    (checkout / "home" / "delay.asm").write_text("; not the real delay.asm\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="exactly once"):
        bc.apply_delay_hook(checkout)


def test_apply_delay_hook_refuses_a_duplicate_anchor(tmp_path):
    checkout = tmp_path / "checkout"
    _write_real_delay_asm(checkout)
    path = checkout / "home" / "delay.asm"
    path.write_text(path.read_text(encoding="utf-8") * 2, encoding="utf-8")

    with pytest.raises(RuntimeError, match="exactly once"):
        bc.apply_delay_hook(checkout)


def test_delay_anchor_and_replacement_are_the_same_instruction_count():
    """Sanity check on the hand-verified byte-size claim: 2 replaced instructions in, 3 in
    (call + 2 nops), each mnemonic present exactly once/twice as expected."""
    assert bc.DELAY_ANCHOR.count("ld a, 1") == 1
    assert bc.DELAY_ANCHOR.count("ld [wVBlankOccurred], a") == 1
    assert bc.DELAY_REPLACEMENT.count("call SlinkDelayFrameBridge") == 1
    assert bc.DELAY_REPLACEMENT.count("nop") == 2


# ---------------------------------------------------------------- rom_facts


def test_rom_facts_reports_sha1_md5_crc32_and_size():
    data = bytes(range(256)) * 4
    facts = bc.rom_facts(data)
    assert facts["size"] == len(data)
    assert set(facts) == {"sha1", "md5", "header_crc", "crc32", "title", "size"}
    assert len(facts["sha1"]) == 40
    assert len(facts["md5"]) == 32


# ---------------------------------------------------------------- committed overlay sources


@pytest.mark.parametrize("filename,address,size", [
    ("slink_mailbox_crystal.asm", "$CFD8", 40),
    ("slink_mailbox_goldsilver.asm", "$C1D9", 39),
])
def test_committed_mailbox_stub_reserves_the_owner_ruled_span(filename, address, size):
    """O-27 D1: Crystal reserves $CFD8-$CFFF (40 B), Gold/Silver $C1D9-$C1FF (39 B)."""
    text = (ROOT / "patch" / "gen2" / "src" / filename).read_text(encoding="utf-8")
    section = re.search(r'SECTION "SLink Mailbox", WRAM0\[(\$[0-9A-Fa-f]+)\]', text)
    assert section is not None, f"{filename}: no fixed-address SLink Mailbox SECTION"
    assert section.group(1) == address
    ds_match = re.search(r"^\tds\s+([^;\n]+)", text, re.MULTILINE)
    assert ds_match is not None, f"{filename}: no ds reservation"
    expr = ds_match.group(1).strip().replace("$", "0x")
    assert eval(expr, {"__builtins__": {}}) == size


def test_repo_mailbox_stub_files_exist_on_disk():
    for repo, name in bc.REPO_MAILBOX_STUB.items():
        assert (ROOT / "patch" / "gen2" / "src" / name).is_file(), f"{repo}: missing {name}"


def test_titles_cover_crystal_gold_silver_only():
    assert set(bc.TITLES) == {"pokecrystal", "pokegold", "pokesilver"}
    assert {title for title, _ups, _repo in bc.TITLES.values()} == {"crystal", "gold", "silver"}
    assert {repo for _title, _ups, repo in bc.TITLES.values()} == {"pokecrystal", "pokegold"}


def _panel_source(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    for name in ("slink.asm", "panel_flags.asm", "panel.asm", "panel_start.asm"):
        (source / name).write_text(f"; {name}\n")
    return source


@pytest.mark.parametrize("repo", ["pokecrystal", "pokegold"])
def test_panel_trio_includes_and_replaces_only_exit(tmp_path, repo):
    checkout = _fake_checkout(tmp_path, repo)
    _write_real_delay_asm(checkout)
    target = checkout / "engine/menus/start_menu.asm"
    target.parent.mkdir(parents=True)
    original = (ROOT / ".cache/gen2-build" / repo / "engine/menus/start_menu.asm").read_text()
    target.write_text(original)
    bc.apply_overlay(checkout, repo, _panel_source(tmp_path), _no_gb_dir(tmp_path))
    main = (checkout / "main.asm").read_text()
    assert main.index('/panel_flags.asm"') < main.index('/slink.asm"') < main.index('/panel.asm"')
    assert '/panel_start.asm"' not in main
    changed = target.read_text()
    assert changed.endswith('INCLUDE "engine/slink/panel_start.asm"\n')
    assert changed.count("\tconst STARTMENUITEM_SLINK") == 1
    assert changed.count("\tdw SlinkStartMenuEntry, SlinkMenuString, SlinkMenuDesc") == 1
    assert "\tld a, STARTMENUITEM_EXIT\n" not in changed
    assert changed.count("\tld a, STARTMENUITEM_SLINK\n") == 1
    # Existing handlers and non-EXIT availability conditions remain byte-for-byte source.
    restored = changed.replace("\tconst STARTMENUITEM_SLINK ; 9\n", "")
    restored = restored.replace("\tdw SlinkStartMenuEntry, SlinkMenuString, SlinkMenuDesc\n", "")
    restored = restored.replace("\tld a, STARTMENUITEM_SLINK\n", "\tld a, STARTMENUITEM_EXIT\n")
    assert restored.removesuffix('\nINCLUDE "engine/slink/panel_start.asm"\n') == original


@pytest.mark.parametrize("missing", ["panel_flags.asm", "panel.asm", "panel_start.asm", "slink.asm"])
def test_partial_panel_trio_is_refused_before_checkout_edits(tmp_path, missing):
    src = _panel_source(tmp_path)
    (src / missing).unlink()
    checkout = _fake_checkout(tmp_path, "pokecrystal")
    before = (checkout / "main.asm").read_bytes()
    with pytest.raises(RuntimeError, match="panel"):
        bc.apply_overlay(checkout, "pokecrystal", src, _no_gb_dir(tmp_path))
    assert (checkout / "main.asm").read_bytes() == before
    assert not (checkout / bc.OVERLAY_DST).exists()


@pytest.mark.parametrize("which", ["constant", "table", "exit"])
@pytest.mark.parametrize("count", [0, 2])
def test_start_hook_refuses_nonunique_anchors_without_edit(tmp_path, which, count):
    anchors = {"constant": "\tconst STARTMENUITEM_QUIT     ; 8\n",
               "table": "\tdw StartMenu_Quit,     .QuitString,     .QuitDesc\n",
               "exit": "\tld a, STARTMENUITEM_EXIT\n"}
    original = (ROOT / ".cache/gen2-build/pokecrystal/engine/menus/start_menu.asm").read_text()
    damaged = original.replace(anchors[which], anchors[which] * count)
    target = tmp_path / "engine/menus/start_menu.asm"
    target.parent.mkdir(parents=True)
    target.write_text(damaged)
    with pytest.raises(RuntimeError, match="exactly once"):
        bc.apply_start_menu_hook(tmp_path)
    assert target.read_text() == damaged


def test_published_provenance_matches_patch_bytes_without_build():
    report = json.loads(bc.PROVENANCE_PATH.read_text())
    # This checks the artifact, not a frozen previous build hash; future panel artifacts work too.
    for key, (_title, patch_name, repo) in bc.TITLES.items():
        output = report["outputs"][key]
        base = (ROOT / ".cache/gen2-build" / repo / output["filename"]).read_bytes()
        patched = bc.ups_apply(base, (bc.DIST / patch_name).read_bytes())
        assert output["sha1"] == hashlib.sha1(patched).hexdigest()
        assert output["identical_to_clean"] == (patched == base)
        assert output["identical_to_clean"] is False


def test_replaced_exit_keeps_every_native_menu_within_screen():
    # Native SetUpMenuItems: conditional dex/party/pack/gear/save-or-quit,
    # always status/options/exit. O-28 replaces the last item without adding one.
    for dex, party, gear, link, contest in product((False, True), repeat=5):
        rows = int(dex) + int(party) + int(gear) + int(not link and not contest)
        rows += 3 + int(not link)
        top = 2 if contest else 0
        assert top + 2 * rows + 1 <= 17
    # The rejected append-only implementation cannot pass these full-menu examples.
    assert 0 + 2 * (8 + 1) + 1 > 17
    assert 2 + 2 * (7 + 1) + 1 > 17


def _symbol_pair(tmp_path, mutation=None):
    old = {"StartMenu.Items": (4, 0x66EB), "Tail": (4, 0x7500),
           "DelayFrame": (0, 0x456), "RuntimeHook": (3, 0x6789), "State": (4, 0xD123)}
    new = {**old, "Tail": (4, 0x7540), "SlinkStartMenuEntry": (4, 0x7F10),
           "SlinkMenuString": (4, 0x7F20), "SlinkMenuDesc": (4, 0x7F26)}
    if mutation:
        mutation(new)
    paths = [tmp_path / "clean.sym", tmp_path / "overlay.sym"]
    for path, rows in zip(paths, (old, new), strict=True):
        path.write_text("".join(f"{bank:02x}:{address:04x} {name}\n"
                                for name, (bank, address) in rows.items()))
    return paths


def test_symbol_scope_accepts_only_bank4_growth(tmp_path):
    bc.verify_symbol_scope(*_symbol_pair(tmp_path), panel=True)


@pytest.mark.parametrize("mutation", [
    lambda rows: rows.update(RuntimeHook=(3, 0x678A)),
    lambda rows: rows.update(DelayFrame=(0, 0x457)),
    lambda rows: rows.update(State=(4, 0xD124)),  # bank-4 WRAM is not bank-4 ROM
    lambda rows: rows.update(Tail=(5, 0x4540)),
    lambda rows: rows.pop("Tail"),
    lambda rows: rows.update(SlinkMenuString=(0x75, 0x4200)),
])
def test_symbol_scope_refuses_nonlocal_growth(tmp_path, mutation):
    with pytest.raises(RuntimeError):
        bc.verify_symbol_scope(*_symbol_pair(tmp_path, mutation), panel=True)


def test_caps_zero_build_cannot_move_bank4_either(tmp_path):
    with pytest.raises(RuntimeError, match="Tail"):
        bc.verify_symbol_scope(*_symbol_pair(tmp_path), panel=False)
