"""MODEL: actual isolated Git commits exercise receipt validity and red/revert controls."""
import subprocess

import pytest

from tools import gen4_evidence as e


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
                     "lua/gen4/reads.lua", "lua/nds/hook_binding.lua", "data/games/gen4_hgss/profile.json", "data/games/gen4_hge/profile.json"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"bound bytes\n")
    commit(tmp_path)
    return tmp_path


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
