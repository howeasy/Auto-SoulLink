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


def test_empty_src_dir_is_the_empty_overlay(tmp_path):
    assert bc.overlay_plan("pokecrystal", tmp_path) == []
    assert bc.overlay_plan("pokegold", tmp_path) == []


def test_nonexistent_src_dir_is_also_the_empty_overlay(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert bc.overlay_plan("pokecrystal", missing) == []


def test_mailbox_stub_only_selects_the_repo_specific_file(tmp_path):
    (tmp_path / "slink_mailbox_crystal.asm").write_text("; crystal\n")
    (tmp_path / "slink_mailbox_goldsilver.asm").write_text("; gold/silver\n")
    crystal_plan = bc.overlay_plan("pokecrystal", tmp_path)
    gold_plan = bc.overlay_plan("pokegold", tmp_path)
    assert crystal_plan == [("slink_mailbox.asm", tmp_path / "slink_mailbox_crystal.asm")]
    assert gold_plan == [("slink_mailbox.asm", tmp_path / "slink_mailbox_goldsilver.asm")]


def test_shared_slink_asm_is_included_for_both_repos_when_present(tmp_path):
    (tmp_path / "slink_mailbox_crystal.asm").write_text("; crystal\n")
    (tmp_path / "slink_mailbox_goldsilver.asm").write_text("; gold/silver\n")
    (tmp_path / "slink.asm").write_text("; codex P4.1c\n")
    names = [name for name, _ in bc.overlay_plan("pokecrystal", tmp_path)]
    assert names == ["slink_mailbox.asm", "slink.asm"]


def test_shared_slink_asm_alone_without_a_mailbox_stub_is_still_picked_up(tmp_path):
    (tmp_path / "slink.asm").write_text("; codex P4.1c\n")
    names = [name for name, _ in bc.overlay_plan("pokecrystal", tmp_path)]
    assert names == ["slink.asm"]


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
    applied = bc.apply_overlay(checkout, repo, tmp_path / "empty-src")
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

    applied = bc.apply_overlay(checkout, repo, src_dir)

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
        bc.apply_overlay(checkout, "pokecrystal", src_dir)


def test_apply_overlay_refuses_a_checkout_with_the_anchor_twice(tmp_path):
    checkout = _fake_checkout(tmp_path, "pokecrystal")
    main_path = checkout / "main.asm"
    main_path.write_text(main_path.read_text(encoding="utf-8") * 2, encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "slink_mailbox_crystal.asm").write_text('SECTION "x", WRAM0[$0000]\n')

    with pytest.raises(RuntimeError, match="exactly once"):
        bc.apply_overlay(checkout, "pokecrystal", src_dir)


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
