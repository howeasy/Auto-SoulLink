"""Version-masked identity for the Gen 3 companions (owner ruling 2026-10-02, patch/tools/rom_identity.py).

The menu version is a FIXED-WIDTH field, so stamping a release changes only that field; qualification keys on the canonical
identity (the build with the field zeroed). These tests pin: the compiled payload really differs only in the field, the manifest
and the Radical Red pin row record the canonical hashes, a receipt or pin hash is accepted only if it is the published exact value
or listed as an earlier canonical-equal build, and build.py read-modify-writes companion_pins.json without dropping a slug.

Absent input skips; present-but-wrong input fails.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

from patch.tools import gen3_title as g, rom_identity as ri
from tools import gen3_companions as gc, rr_companion

ROOT = Path(__file__).resolve().parents[2]
ROMS = {"firered": "Pokemon - FireRed Version (USA).gba", "leafgreen": "Pokemon - LeafGreen Version (USA).gba",
        "emerald": "Pokemon - Emerald Version (USA, Europe).gba", "radical_red": "Pokemon - Radical Red.gba"}
NATIVE = ("firered", "leafgreen", "emerald")
STAMPED = "v10.20.30"                                   # the widest legal version: 'SoulLink ' + 10 characters + terminator = FIELD

spec = importlib.util.spec_from_file_location("companion_build", ROOT / "patch/tools/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def manifest() -> dict:
    return json.loads((ROOT / "patch/dist/gen3_companions.json").read_text())["titles"]


def published_version() -> str:
    """The menu version tools/stamp_release.py last stamped into the Gen 3 family ('dev' when unstamped).

    A v1 certificate stores the family's version string; a v2 certificate stores {"mode": "stamped", "version": ...}
    (Gen 3 is never certified as-built, so a v2 entry without a stamped version is a failure here, not a skip)."""
    entry = json.loads((ROOT / "patch/dist/companion_version.json").read_text())["families"]["gen3"]
    if isinstance(entry, dict):
        assert entry.get("mode") == "stamped", f"gen3 certificate entry is not stamped: {entry}"
        return entry["version"]
    return entry


def owner_rom_path(game: str) -> Path:
    root = os.environ.get("SLINK_GEN3_ROMS")
    if not root:
        pytest.skip("SLINK_GEN3_ROMS (the owner ROM directory) is required")
    path = Path(root) / ROMS[game]
    if not path.exists():
        pytest.skip(f"{path} is absent")
    return path


def need_toolchain():
    if build.GCCDIR is None:
        pytest.skip("arm-none-eabi-gcc not found (set $SLINK_ARMGCC or use the root checkout's patch/vendor)")


# ---- the payload: a stamp changes the field and nothing else --------------------------------------------------------------------------

def link_payload(tmp: Path, src: Path, version: str, title: str | None) -> bytes:
    """handlers.c linked the way build.py links it (a native companion for `title`, or Radical Red's body for None)."""
    obj, elf, binary = tmp / f"{version}.o", tmp / f"{version}.elf", tmp / f"{version}.bin"
    if title:
        header = src / "trade_targets" / f"{title}.h"
        compile_flags = ["-DSLINK_NATIVE_COMPANION=1", "-include", str(header)]
        link_flags = ["-T", str(header.with_suffix(".ld")), "-e", "slink_native_heap"]
    else:
        compile_flags, link_flags = [], ["-T", str(src / "slink.ld"), "-e", "slink_hook"]
    build.run([build.GCC, *build.CFLAGS, *compile_flags, "-D" + g.menu_define(version), "-c", str(src / "handlers.c"), "-o", str(obj)])
    build.run([build.LD, *link_flags, "--no-warn-rwx-segments", str(obj), "-o", str(elf)])
    build.run([build.OBJCOPY, "-O", "binary", str(elf), str(binary)])
    return binary.read_bytes()


@pytest.mark.parametrize("title", [*NATIVE, None])
def test_a_version_stamp_changes_only_the_field_in_the_payload(title, tmp_path):
    need_toolchain()
    dev = link_payload(tmp_path, ROOT / "patch/src", "dev", title)
    stamped = link_payload(tmp_path, ROOT / "patch/src", STAMPED, title)
    assert len(dev) == len(stamped)                                        # the payload size is the same for every legal version
    slot = ri.slot_from_text(dev, g.menu_field("dev"))
    assert slot["length"] == ri.FIELD == g.MENU_FIELD
    assert ri.slot_from_text(stamped, g.menu_field(STAMPED)) == slot       # and so is every address
    ri.assert_version_only_difference(dev, stamped, [slot])
    assert dev != stamped                                                  # the stamp did land in the field
    assert ri.canonical_sha256(dev, [slot]) == ri.canonical_sha256(stamped, [slot])


@pytest.mark.parametrize("title", [NATIVE[0], None])
def test_an_unpadded_field_would_fail_the_same_check(title, tmp_path):
    """The negative control, built into the test: with the old variable-width array the two versions differ beyond the field (or in
    size), and the very check the previous test passes raises. If native_menu.h lost its fixed width, that test would fail."""
    need_toolchain()
    src = tmp_path / "src"
    shutil.copytree(ROOT / "patch/src", src)
    header = src / "trade_targets/native_menu.h"
    text = header.read_bytes().decode()
    padded = "static const uint8_t slm_text[SLM_FIELD] = { SLINK_MENU_TEXT };"
    assert padded in text
    text = text.replace(padded, "static const uint8_t slm_text[] = { SLINK_MENU_TEXT };")
    text = "\n".join(line for line in text.splitlines() if "the version field is a fixed width" not in line)
    header.write_bytes(text.encode())
    dev = link_payload(tmp_path, src, "dev", title)
    stamped = link_payload(tmp_path, src, STAMPED, title)
    window = {"offset": dev.find(g.menu_bytes("dev")), "length": ri.FIELD}
    assert window["offset"] >= 0
    with pytest.raises(ValueError):
        ri.assert_version_only_difference(dev, stamped, [window])


@pytest.mark.parametrize("title", NATIVE)
def test_a_stamped_published_pipeline_build_differs_from_dev_only_inside_the_field(title, tmp_path, monkeypatch):
    """The whole production pipeline (payload, detours, panel tables, title assets), not just the compile."""
    need_toolchain()
    rom = owner_rom_path(title)
    monkeypatch.setattr(build, "BUILD", str(tmp_path))
    built = {}
    for version in ("dev", STAMPED):
        out, receipt = build.build_arena_probe(title, str(rom), "trade", trade_candidate=True, production=True, version=version)
        built[version] = ((out / "probe.gba").read_bytes(), receipt)
    (dev_rom, dev), (stamped_rom, stamped) = built["dev"], built[STAMPED]
    ri.assert_version_only_difference(dev_rom, stamped_rom, [dev["version_slot"]])
    assert dev["version_slot"] == stamped["version_slot"] and dev["payload_version_slot"] == stamped["payload_version_slot"]
    assert dev["payload_bytes"] == stamped["payload_bytes"]
    assert dev["canonical_sha1"] == stamped["canonical_sha1"] and dev["canonical_payload_sha256"] == stamped["canonical_payload_sha256"]
    assert dev["sha1"] != stamped["sha1"] and dev["payload_sha256"] != stamped["payload_sha256"]
    for key in ("frame_detour", "trade_detours", "panel_detours", "panel_tables", "title", "replacement", "detour"):
        assert dev[key] == stamped[key], key
    row = manifest()[title]                                                # the dev build is canonically what is published,
    assert (dev["canonical_sha1"], dev["canonical_payload_sha256"]) == (row["canonical_sha1"], row["canonical_payload_sha256"])
    assert gc.accepts(row, "rom_sha1", dev["sha1"])                        # and vouched for exactly (published, or listed after a stamp)


# ---- the published records ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("title", NATIVE)
def test_every_manifest_row_records_a_consistent_version_slot(title):
    row = manifest()[title]
    assert gc.canonical_problems(row) == []
    assert row["version_slot"]["offset"] == row["protected_spans"][0]["offset"] + row["payload_version_slot"]["offset"]
    assert row["version_slot"]["length"] == row["payload_version_slot"]["length"] == ri.FIELD
    assert row["menu_version"] == published_version()                      # the manifest records what the release stamp wrote


@pytest.mark.parametrize("title", NATIVE)
def test_stamping_the_published_payload_moves_the_exact_digest_and_not_the_canonical_one(title):
    row = manifest()[title]
    span = row["protected_spans"][0]
    payload = gc.ups_region((ROOT / "patch/dist" / row["patch"]).read_bytes(), span["offset"], span["size"])
    slot = row["payload_version_slot"]
    assert payload[slot["offset"]:slot["offset"] + slot["length"]] == g.menu_field(row["menu_version"])
    stamped = bytearray(payload)
    stamped[slot["offset"]:slot["offset"] + slot["length"]] = g.menu_field(STAMPED)
    assert hashlib.sha256(stamped).hexdigest() != row["payload_sha256"]
    assert ri.canonical_sha256(bytes(stamped), [slot]) == row["canonical_payload_sha256"]
    elsewhere = bytearray(payload)
    elsewhere[0] ^= 1
    assert ri.canonical_sha256(bytes(elsewhere), [slot]) != row["canonical_payload_sha256"]


def test_canonical_problems_names_what_is_wrong():
    row = dict(manifest()["firered"])
    assert gc.canonical_problems(row) == []
    assert gc.canonical_problems({k: v for k, v in row.items() if k != "version_slot"}) == ["no version slot recorded"]
    assert any("fixed field width" in p for p in gc.canonical_problems({**row, "version_slot": {**row["version_slot"], "length": 13}}))
    assert any("moved to its ROM address" in p for p in gc.canonical_problems({**row, "version_slot": {"offset": 0, "length": 20}}))
    assert any("not a lowercase hex" in p for p in gc.canonical_problems({**row, "equivalent_sha1s": ["nope"]}))
    assert any("lists the published build itself" in p for p in gc.canonical_problems({**row, "equivalent_sha1s": [row["rom_sha1"]]}))
    assert any("canonical_payload_sha256 differs" in p for p in gc.canonical_problems(row, payload=bytes(9000)))


def test_the_radical_red_row_is_recorded_and_reproduces_from_the_published_ups():
    from patch.tools.make_ups import ups_apply
    pins = json.loads((ROOT / "patch/dist/companion_pins.json").read_text())
    assert pins["schema"] == "slink-companion-pins-v1"
    row = pins["pins"]["rr"]
    assert {"patched_md5", "rom_sha1", "canonical_sha1", "version", "version_slot"} <= set(row)
    assert {"rb-red", "rb-blue"} <= set(pins["pins"])                       # a build never drops another slug
    rom = ups_apply(owner_rom_path("radical_red").read_bytes(), (ROOT / "patch/dist/SLink-RR.ups").read_bytes())
    slot = row["version_slot"]
    assert hashlib.md5(rom).hexdigest() == row["patched_md5"]
    assert hashlib.sha1(rom).hexdigest() == row["rom_sha1"] == rr_companion.rom_sha1()        # the one data source for the exact sha1
    assert rom[slot["offset"]:slot["offset"] + slot["length"]] == g.menu_field(row["version"])
    assert ri.canonical_sha1(rom, [slot]) == row["canonical_sha1"]
    stamped = bytearray(rom)
    stamped[slot["offset"]:slot["offset"] + slot["length"]] = g.menu_field(STAMPED)
    assert ri.canonical_sha1(bytes(stamped), [slot]) == row["canonical_sha1"]
    assert hashlib.md5(stamped).hexdigest() != row["patched_md5"]


# ---- the equivalence rule -----------------------------------------------------------------------------------------------------------

def test_a_hash_is_accepted_only_if_published_or_listed():
    row = {"payload_sha256": "a" * 64, "equivalent_payload_sha256": ["b" * 64], "rom_sha1": "c" * 40, "equivalent_sha1s": ["d" * 40]}
    assert gc.accepts(row, "payload_sha256", "a" * 64)                      # the published exact value
    assert gc.accepts(row, "payload_sha256", "b" * 64)                      # an earlier build the record lists
    assert gc.accepts(row, "rom_sha1", "d" * 40)
    assert not gc.accepts(row, "payload_sha256", "e" * 64)                  # anything else
    assert not gc.accepts(row, "rom_sha1", "b" * 64)                        # a list vouches only under its own field
    assert not gc.accepts(row, "payload_sha256", "d" * 40)
    assert gc.accepts({"payload_sha256": "a" * 64}, "payload_sha256", "a" * 64)    # an absent list is empty
    assert not gc.accepts({"payload_sha256": "a" * 64}, "payload_sha256", "b" * 64)


def test_a_stamped_rebuild_lists_the_dev_build_and_a_real_change_retires_it():
    dev = {k: v for k, v in manifest()["firered"].items() if not k.startswith("equivalent_")}           # a first publication
    stamped = {**dev, "rom_sha1": "1" * 40, "payload_sha256": "2" * 64, "menu_version": STAMPED}       # same canonical identity
    kept = build.equivalents_after_rebuild(dev, stamped)
    assert kept == {"equivalent_sha1s": [dev["rom_sha1"]], "equivalent_payload_sha256": [dev["payload_sha256"]]}
    published = {**stamped, **kept}
    assert gc.accepts(published, "rom_sha1", dev["rom_sha1"]) and gc.accepts(published, "payload_sha256", dev["payload_sha256"])
    assert gc.canonical_problems(published) == []
    # the next stamp keeps the whole history, and never lists the published build itself
    again = {**stamped, "rom_sha1": "3" * 40, "payload_sha256": "4" * 64}
    assert build.equivalents_after_rebuild(published, again)["equivalent_sha1s"] == sorted([dev["rom_sha1"], "1" * 40])
    assert build.equivalents_after_rebuild(published, {**published, "rom_sha1": dev["rom_sha1"]})["equivalent_sha1s"] == ["1" * 40]
    # a change to the code is not a stamp: the old builds no longer vouch for these bytes
    changed = {**stamped, "canonical_payload_sha256": "9" * 64}
    assert build.equivalents_after_rebuild(published, changed) == {}
    assert not gc.accepts({**changed}, "rom_sha1", dev["rom_sha1"])
    assert build.equivalents_after_rebuild({}, stamped) == {}               # the first publication has nothing to vouch for


# ---- build.py's read-modify-write of companion_pins.json ------------------------------------------------------------------------------

RB = {"patched_md5": "a" * 32, "canonical_sha1": "b" * 40, "version": "dev", "version_slot": {"offset": 16354, "length": 20}}


def seeded_pins(tmp_path, monkeypatch, rr) -> Path:
    path = tmp_path / "companion_pins.json"
    path.write_text(json.dumps({"schema": "slink-companion-pins-v1", "pins": {"rb-red": RB, "rr": rr, "rb-blue": {**RB, "patched_md5": "c" * 32}}}))
    monkeypatch.setattr(build, "pins_path", lambda: str(path))
    return path


def test_write_pin_replaces_one_slug_and_keeps_every_other(tmp_path, monkeypatch):
    old = {"patched_md5": "0" * 32, "version": "dev", "canonical_sha1": "e" * 40, "note": "kept", "equivalent_sha1s": ["f" * 40]}
    path = seeded_pins(tmp_path, monkeypatch, old)
    entry = {"patched_md5": "1" * 32, "rom_sha1": "2" * 40, "canonical_sha1": "e" * 40, "version": "dev",
             "version_slot": {"offset": 7, "length": 20}}
    build.write_pin("rr", entry)
    data = json.loads(path.read_text())
    assert data["pins"]["rb-red"] == RB and data["pins"]["rb-blue"]["patched_md5"] == "c" * 32
    assert data["pins"]["rr"] == {**entry, "note": "kept", "equivalent_sha1s": ["f" * 40]}     # same canonical identity: history kept
    build.write_pin("rr", {**entry, "canonical_sha1": "9" * 40})
    changed = json.loads(path.read_text())["pins"]["rr"]
    assert changed["note"] == "kept" and changed["equivalent_sha1s"] == []                       # a real change retires the history
    assert json.loads(path.read_text())["pins"]["rb-red"] == RB


def test_a_stamp_lists_the_build_it_replaces(tmp_path, monkeypatch):
    """A version stamp (same canonical identity, new exact sha1) keeps the replaced build admissible: cartridges patched with it
    are still in players' hands. The v0.3.0 stamp dropped Radical Red's dev build because write_pin never added it."""
    dev = {"patched_md5": "0" * 32, "rom_sha1": "d" * 40, "canonical_sha1": "e" * 40, "version": "dev"}
    path = seeded_pins(tmp_path, monkeypatch, dev)
    stamped = {**dev, "patched_md5": "1" * 32, "rom_sha1": "2" * 40, "version": "v0.3.0"}
    build.write_pin("rr", stamped)
    assert json.loads(path.read_text())["pins"]["rr"]["equivalent_sha1s"] == ["d" * 40]
    build.write_pin("rr", {**stamped, "rom_sha1": "3" * 40, "version": "v0.3.1"})   # the next stamp keeps the history
    assert json.loads(path.read_text())["pins"]["rr"]["equivalent_sha1s"] == sorted(["d" * 40, "2" * 40])
    build.write_pin("rr", {**stamped, "rom_sha1": "3" * 40, "version": "v0.3.1"})   # an unchanged rebuild adds nothing
    assert json.loads(path.read_text())["pins"]["rr"]["equivalent_sha1s"] == sorted(["d" * 40, "2" * 40])


def test_pin_problems_reports_a_stale_or_missing_row(tmp_path, monkeypatch):
    entry = {"patched_md5": "1" * 32, "rom_sha1": "2" * 40, "canonical_sha1": "e" * 40, "version": "dev",
             "version_slot": {"offset": 7, "length": 20}}
    seeded_pins(tmp_path, monkeypatch, {**entry, "equivalent_sha1s": ["f" * 40], "extra": 1})
    assert build.pin_problems("rr", entry) == []                            # other keys on the row are not this build's business
    assert build.pin_problems("rr", {**entry, "patched_md5": "2" * 32}) == [f"rr.patched_md5: committed {'1' * 32!r}, built {'2' * 32!r}"]
    assert any("version_slot" in p for p in build.pin_problems("rr", {**entry, "version_slot": {"offset": 8, "length": 20}}))
    assert build.pin_problems("gone", entry) == ["gone: no row in companion_pins.json"]


def test_rr_pin_entry_finds_the_field_where_the_payload_put_it():
    blob = bytes(range(200)) + g.menu_field("dev") + bytes(range(50))
    rom = bytes(build.CODE_BASE - build.ROM_BASE) + blob
    entry = build.rr_pin_entry(rom, blob, "dev")
    assert entry["version_slot"] == {"offset": build.CODE_BASE - build.ROM_BASE + 200, "length": ri.FIELD}
    assert entry["canonical_sha1"] == ri.canonical_sha1(rom, [entry["version_slot"]])
    assert entry["patched_md5"] == hashlib.md5(rom).hexdigest() and entry["version"] == "dev"
    assert entry["rom_sha1"] == hashlib.sha1(rom).hexdigest()
    with pytest.raises(ValueError):
        build.rr_pin_entry(bytes(build.CODE_BASE - build.ROM_BASE) + bytes(len(blob)), blob, "dev")     # ROM does not hold the field


# ---- the final-cut pins --------------------------------------------------------------------------------------------------------------

def final_cut_tree(tmp_path, rr_row) -> Path:
    from tools import gen3_final_cut as fc
    tree = tmp_path / "tree"
    (tree / "tools").mkdir(parents=True)
    (tree / "patch/dist").mkdir(parents=True)
    shutil.copyfile(ROOT / "tools/gen_gen3_write_checkpoint.py", tree / "tools/gen_gen3_write_checkpoint.py")
    (tree / "patch/dist/companion_pins.json").write_text(json.dumps({"schema": "slink-companion-pins-v1", "pins": {"rr": rr_row}}))
    assert fc.rom_pins(str(ROOT))                                           # the real tree still parses
    return tree


def test_rom_pins_carry_the_canonical_sibling_and_the_equivalent_builds(tmp_path):
    from tools import gen3_final_cut as fc
    equivalent = "5" * 40
    tree = final_cut_tree(tmp_path, {"patched_md5": "6" * 32, "rom_sha1": "8" * 40, "canonical_sha1": "7" * 40, "version": "dev",
                                     "version_slot": {"offset": 1, "length": 20}, "equivalent_sha1s": [equivalent, "junk"]})
    pins = fc.rom_pins(str(tree))
    assert pins["radical_red_companion"] == "8" * 40                               # the exact pin is the row's, not a literal
    assert pins["emerald"] == fc.rom_pins(str(ROOT))["emerald"]                    # and it did not eat the next table entry
    assert pins["radical_red_companion:md5"] == "6" * 32
    assert pins["radical_red_companion:canonical"] == "7" * 40
    assert pins["radical_red_companion:equivalent_sha1s"] == (equivalent,)         # malformed entries are not trusted
    real = fc.rom_pins(str(ROOT))
    assert real["radical_red_companion"] == rr_companion.rom_sha1()
    row = json.loads((ROOT / "patch/dist/companion_pins.json").read_text())["pins"]["rr"]
    assert real["radical_red_companion:canonical"] == row["canonical_sha1"] and real["radical_red_companion:md5"] == row["patched_md5"]


def test_a_staged_rom_matches_the_exact_pin_or_a_listed_equivalent_and_nothing_else(tmp_path):
    from tools import gen3_final_cut as fc
    files = {}
    for name in ("exact", "earlier", "stranger"):
        files[name] = tmp_path / f"{name}.gba"
        files[name].write_bytes(name.encode() * 64)
    sha1 = {n: hashlib.sha1(p.read_bytes()).hexdigest() for n, p in files.items()}
    pins = {"k": sha1["exact"], "k:md5": hashlib.md5(files["exact"].read_bytes()).hexdigest(),
            "k:equivalent_sha1s": (sha1["earlier"],)}
    assert fc._matches_pin(str(files["exact"]), "k", pins)                         # known positive: the published build
    assert fc._matches_pin(str(files["earlier"]), "k", pins)                       # known positive: a listed canonical-equal build
    assert not fc._matches_pin(str(files["stranger"]), "k", pins)                  # negative: neither
    no_list = {k: v for k, v in pins.items() if not k.endswith("equivalent_sha1s")}
    assert not fc._matches_pin(str(files["earlier"]), "k", no_list)                # negative: without the listing it is refused
    assert not fc._matches_pin(str(files["exact"]), "k", {**pins, "k:md5": "0" * 32})   # the exact pin still binds its md5


def test_a_row_without_the_exact_sha1_leaves_the_companion_unpinned_and_the_lane_refuses(tmp_path):
    from tools import gen3_final_cut as fc
    tree = final_cut_tree(tmp_path, {"patched_md5": "6" * 32, "canonical_sha1": "7" * 40, "version": "dev"})
    with pytest.raises(fc.LaneError, match="incomplete"):
        fc.rom_pins(str(tree))


# ---- Radical Red's backup body, checked structurally ------------------------------------------------------------------------------------

def staged_companion() -> bytes:
    path = ROOT / "patch/build/slink_RR.gba"
    if not path.exists():
        pytest.skip("patch/build/slink_RR.gba (the staged companion) is absent")
    rom = path.read_bytes()
    if hashlib.sha1(rom).hexdigest() not in rr_companion.accepted_sha1s():
        pytest.skip("the staged slink_RR.gba is not the pinned companion")
    return rom


def with_backup_call(rom: bytes, target: int) -> bytes:
    from tools.research import rr_special_lifecycle as lifecycle
    at = 0x0804C1F0 - 0x08000000 + lifecycle.BACKUP_BL_AT
    out = bytearray(rom)
    out[at:at + 4] = build.thumb_bl(0x0804C1F0 + lifecycle.BACKUP_BL_AT, target)
    return bytes(out)


def test_the_backup_body_check_follows_the_payload_not_a_digest_of_where_it_linked():
    from tools.research import rr_special_lifecycle as lifecycle
    rom = staged_companion()
    assert lifecycle.census(rom)["borrowed_party"]["bodies"]["backup"]["size"] == 64     # the shipped build passes
    # a payload that linked elsewhere (any later code change moves slink_backup_wrap): the same check still holds
    moved = with_backup_call(rom, lifecycle.PAYLOAD[0] + 0x1230)
    assert lifecycle.borrowed_contract(moved, companion=True)["bodies"]["backup"]["address"] == 0x0804C1F0
    # known negatives: the call left to RR's own memcpy, a call landing past the payload, any other byte of the body changed, and a
    # build the pins do not name being read as the clean ROM
    for bad in (with_backup_call(rom, 0x081E5E78), with_backup_call(rom, lifecycle.PAYLOAD[1])):
        with pytest.raises(ValueError, match="backup body changed or ambiguous"):
            lifecycle.borrowed_contract(bad, companion=True)
    other = bytearray(rom)
    other[0x0804C1F0 - 0x08000000 + 5] ^= 1
    with pytest.raises(ValueError, match="backup body changed or ambiguous"):
        lifecycle.borrowed_contract(bytes(other), companion=True)
    with pytest.raises(ValueError, match="backup body changed or ambiguous"):
        lifecycle.borrowed_contract(moved)            # sha1 not a pinned companion: judged as the clean ROM, whose call is memcpy's
