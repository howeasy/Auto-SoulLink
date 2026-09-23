"""tools/build_gen2_companion.py: overlay selection and the main.asm hook edit.

Fast, offline unit coverage of the deterministic parts (no rgbasm/make invocation -- that is
exercised by hand per the card's falsifier and recorded in the P4.1a report). What is covered
here: which files an overlay pulls in per repo (empty overlay vs. mailbox-only vs. mailbox +
Codex's future slink.asm), and that the main.asm hook is verify-then-replace-once, matching
tools/apply_purergb_overlay.py's discipline.
"""

import re
import sys
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
