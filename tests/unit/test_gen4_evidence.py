"""MODEL: actual isolated Git commits exercise receipt validity and red/revert controls."""
import subprocess

import pytest

from tools import gen4_evidence as e

# No pack input is absent by proof any more: gen4_hge ships area_map.json/locations.json too
# (tools/gen_gen4_area_map.py proves the fork's map headers and area names byte-identical to HGSS's on
# the two pinned ROMs, and lua/gen4/inputs.lua therefore builds area_of/gift_area for that pack). Both
# packs bind the same file set, and the ABSENT marker is now only ever a work-tree state -- the
# tolerance in gen4_evidence.OPTIONAL_PACK_INPUTS stays, so an uncommitted delete/add is still refused.
PACK_FILES = tuple(
    f"data/games/{pack}/{name}"
    for pack in ("gen4_hgss", "gen4_hge")
    for name in ("profile.json", *e.PACK_INPUTS)
)


@pytest.fixture
def model_surface(monkeypatch, request):
    """Hypothetical consumer receipts can exercise WIP bytes; live tests never use this seam."""
    if request.node.get_closest_marker("live") is not None:
        return
    original = e.snapshot

    def snapshot(*args, **kwargs):
        kwargs["committed"] = False
        return original(*args, **kwargs)

    monkeypatch.setattr(e, "snapshot", snapshot)


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for key, value in (("user.name", "Evidence Test"), ("user.email", "evidence@test.invalid"), ("core.autocrlf", "false")):
        subprocess.run(["git", "config", key, value], cwd=tmp_path, check=True)
    for relative in (*e.COMMON, *e.SCRIPTS.values(), *(x for group in e.PYTHON.values() for x in group),
                     "lua/gen4/reads.lua", "lua/gen4/inputs.lua", "lua/nds/hook_binding.lua", *PACK_FILES):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"bound bytes\n")
    commit(tmp_path)
    return tmp_path


def write_pack_file(repo, relative, data=b"bound bytes\n"):
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def hge_receipt(repo, kind="probe"):
    return {**e.snapshot(kind, "heartgold_hge", repo=repo), "rom_sha1": "b" * 40}


def test_inputs_lua_and_every_pack_file_it_opens_are_bound_for_every_kind(repo):
    """inputs.lua is the ONLY opener of these files and the lua/gen4 glob already binds it for every
    kind, so the files it reads are bound for every kind too. This is the invariant that keeps a
    charmap edit from qualifying against a receipt that exercised it."""
    for kind in e.SCRIPTS:
        for title, pack in e.PACKS.items():
            files = e.snapshot(kind, title, repo=repo)["module_sha256"]
            assert "lua/gen4/inputs.lua" in files, (kind, title)
            for name in e.PACK_INPUTS:
                assert f"data/games/{pack}/{name}" in files, (kind, title, name)
            if kind in {"route", "catch"}:  # the existing two-pack coverage extends to the data too
                for name in e.PACK_INPUTS:
                    assert f"data/games/gen4_hge/{name}" in files, (kind, name)


@pytest.mark.parametrize("kind", e.SCRIPTS)
@pytest.mark.parametrize("title", tuple(e.PACKS))
def test_one_byte_charmap_edit_stale_and_revert(repo, kind, title):
    """The title's own pack dir, exactly as profile.json is bound: editing that pack's charmap moves
    the digest, so no receipt survives a charmap change it ran against."""
    charmap = f"data/games/{e.PACKS[title]}/charmap.json"
    old = {**e.snapshot(kind, title, repo=repo), "rom_sha1": "a" * 40}
    assert old["module_sha256"][charmap] != e.ABSENT
    before = old["surface_sha256"]
    path = write_pack_file(repo, charmap, b"glyphs changed\n")
    commit(repo)
    assert e.snapshot(kind, title, repo=repo)["surface_sha256"] != before
    with pytest.raises(e.StaleEvidenceError):
        e.verify(old, kind, title, "a" * 40, repo=repo)
    path.write_bytes(b"bound bytes\n")
    commit(repo)
    e.verify(old, kind, title, "a" * 40, repo=repo)


def test_uncommitted_charmap_edit_is_refused(repo):
    write_pack_file(repo, "data/games/gen4_hgss/charmap.json", b"WIP glyphs\n")
    with pytest.raises(e.StaleEvidenceError, match="charmap.json"):
        e.snapshot("probe", "heartgold", repo=repo)


def test_the_hge_area_files_are_bound_like_hgss_and_an_edit_stales_and_reverts(repo):
    """Shipping the file must move the digest: that is the whole reason ABSENT was recorded under its own
    path, and it is what makes "add it later" a stale receipt rather than a silent change."""
    old = hge_receipt(repo)
    files = old["module_sha256"]
    for name in ("area_map.json", "locations.json"):
        assert files[f"data/games/gen4_hge/{name}"] not in (None, e.ABSENT), name
    assert files["data/games/gen4_hge/charmap.json"] != e.ABSENT
    before = old["surface_sha256"]
    write_pack_file(repo, "data/games/gen4_hge/area_map.json", b'{"maps":{"0":"route_1"}}\n')
    commit(repo)
    new = hge_receipt(repo)
    assert new["surface_sha256"] != before
    with pytest.raises(e.StaleEvidenceError, match="area_map.json"):
        e.verify(old, "probe", "heartgold_hge", "b" * 40, repo=repo)
    e.verify(new, "probe", "heartgold_hge", "b" * 40, repo=repo)
    write_pack_file(repo, "data/games/gen4_hge/area_map.json")
    commit(repo)
    e.verify(old, "probe", "heartgold_hge", "b" * 40, repo=repo)


@pytest.mark.parametrize("pack", ["gen4_hgss", "gen4_hge"])
def test_every_pack_area_file_is_hashed_never_marked_absent(repo, pack):
    """The absent marker is a PACK fact, not a filename rule: both packs ship both files and neither is
    ever exempt, so an hge receipt says nothing about which files the producers could open."""
    title = "heartgold" if pack == "gen4_hgss" else "heartgold_hge"
    files = e.snapshot("probe", title, repo=repo)["module_sha256"]
    for name in ("area_map.json", "locations.json"):
        assert files[f"data/games/{pack}/{name}"] not in (None, e.ABSENT), name


def test_absent_is_recorded_not_a_bypass_and_a_missing_charmap_is_refused(repo):
    """Red control: ABSENT cannot be forged over a file that exists, and charmap.json -- which every
    pack ships -- stays a hard dependency rather than inheriting the area files' tolerance."""
    old = hge_receipt(repo)
    forged = {**old, "module_sha256": {**old["module_sha256"], "data/games/gen4_hge/charmap.json": e.ABSENT}}
    forged["surface_sha256"] = e.surface_hash("probe", forged["module_sha256"])
    with pytest.raises(e.StaleEvidenceError, match="charmap.json"):
        e.verify(forged, "probe", "heartgold_hge", "b" * 40, repo=repo)
    (repo / "data/games/gen4_hge/charmap.json").unlink()
    commit(repo)
    with pytest.raises(e.StaleEvidenceError, match="charmap.json"):
        e.snapshot("probe", "heartgold_hge", repo=repo)
    write_pack_file(repo, "data/games/gen4_hge/charmap.json")
    commit(repo)
    e.verify(old, "probe", "heartgold_hge", "b" * 40, repo=repo)


def test_deleting_a_shipped_area_file_in_the_work_tree_is_refused_not_absent(repo):
    """A file the pack ships cannot be turned into an ABSENT receipt by an uncommitted delete: the
    bytes are still at HEAD, so the deletion is an uncommitted dependency change, not a pack gap."""
    old = {**e.snapshot("probe", "heartgold", repo=repo), "rom_sha1": "a" * 40}
    path = repo / "data/games/gen4_hgss/area_map.json"
    path.unlink()
    with pytest.raises(e.StaleEvidenceError, match="area_map.json"):
        e.snapshot("probe", "heartgold", repo=repo)
    write_pack_file(repo, "data/games/gen4_hgss/area_map.json")
    e.verify(old, "probe", "heartgold", "a" * 40, repo=repo)


def test_a_pack_file_absent_at_head_and_created_uncommitted_is_refused(repo):
    """The mirror of the delete control: even an OPTIONAL path the commit does not carry cannot be added
    in the work tree, or a receipt could qualify against bytes no commit has."""
    path = repo / "data/games/gen4_hge/area_map.json"
    path.unlink()
    commit(repo)
    absent = hge_receipt(repo)
    assert absent["module_sha256"]["data/games/gen4_hge/area_map.json"] == e.ABSENT
    write_pack_file(repo, "data/games/gen4_hge/area_map.json", b'{"maps":{}}')
    with pytest.raises(e.StaleEvidenceError, match="area_map.json"):
        e.snapshot("probe", "heartgold_hge", repo=repo)
    path.unlink()
    e.verify(absent, "probe", "heartgold_hge", "b" * 40, repo=repo)


def commit(repo):
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "isolated evidence fixture"], cwd=repo, check=True)


def receipt(repo, kind="probe"):
    return {**e.snapshot(kind, "heartgold", repo=repo), "rom_sha1": "a" * 40}


def test_docs_only_commit_keeps_receipt_valid(repo):
    old = receipt(repo)
    (repo / "docs.md").write_text("documentation only\n")
    commit(repo)
    assert e.snapshot("probe", "heartgold", repo=repo)["source_head"] != old["source_head"]
    e.verify(old, "probe", "heartgold", "a" * 40, repo=repo)


@pytest.mark.parametrize("kind", e.SCRIPTS)
@pytest.mark.parametrize("category", ("script", "json", "registry", "gen4", "nds", "pack", "python"))
def test_one_byte_dependency_edit_stale_and_revert(repo, kind, category):
    relative = {"script": e.SCRIPTS[kind], "json": "lua/json_codec.lua", "registry": "lua/hook_registry.lua",
                "gen4": "lua/gen4/reads.lua", "nds": "lua/nds/hook_binding.lua", "pack": "data/games/gen4_hgss/profile.json",
                "python": e.PYTHON[kind][0]}[category]
    old = receipt(repo, kind)
    path = repo / relative
    original = path.read_bytes()
    path.write_bytes(b"B" + original[1:])
    with pytest.raises(e.StaleEvidenceError):
        e.verify(old, kind, "heartgold", "a" * 40, repo=repo)
    commit(repo)  # A committed dependency change also invalidates the previous surface.
    with pytest.raises(e.StaleEvidenceError):
        e.verify(old, kind, "heartgold", "a" * 40, repo=repo)
    path.write_bytes(original)
    commit(repo)
    e.verify(old, kind, "heartgold", "a" * 40, repo=repo)


def test_rom_title_trimmed_manifest_new_module_red_and_revert(repo):
    old = receipt(repo)
    for title, rom in (("soulsilver", "a" * 40), ("heartgold", "b" * 40)):
        with pytest.raises(e.StaleEvidenceError):
            e.verify(old, "probe", title, rom, repo=repo)
        e.verify(old, "probe", "heartgold", "a" * 40, repo=repo)
    trimmed = {**old, "module_sha256": {}}
    with pytest.raises(e.StaleEvidenceError):
        e.verify(trimmed, "probe", "heartgold", "a" * 40, repo=repo)
    path = repo / "lua/gen4/new_module.lua"
    path.write_bytes(b"new dependency\n")
    with pytest.raises(e.StaleEvidenceError):
        e.verify(old, "probe", "heartgold", "a" * 40, repo=repo)
    path.unlink()
    e.verify(old, "probe", "heartgold", "a" * 40, repo=repo)


def test_crlf_compares_to_git_without_treating_it_as_uncommitted_code(repo):
    path = repo / "lua/json_codec.lua"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    e.snapshot("probe", "heartgold", repo=repo)


def test_wrong_kind_and_forged_aggregate_are_stale(repo):
    old = receipt(repo)
    with pytest.raises(e.StaleEvidenceError):
        e.verify(old, "faint", "heartgold", "a" * 40, repo=repo)
    with pytest.raises(e.StaleEvidenceError):
        e.verify({**old, "surface_sha256": "0" * 64}, "probe", "heartgold", "a" * 40, repo=repo)
    e.verify(old, "probe", "heartgold", "a" * 40, repo=repo)
