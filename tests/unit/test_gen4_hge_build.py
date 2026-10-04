"""hge build tool controls; subprocess is faked, so no network or box is touched."""

import hashlib
import json
import subprocess

import pytest

from tools import gen4_hge_build as hb

HEAD = "ab" * 20
NDS = b"fresh-test-nds"
FILES = {"test.nds": NDS, "offsets.ini": b"offsets", "rom_gen.ld": b"ld"}
NM = b"## build/linked.o\n00000001 a ABSLOCAL\n023d8060 T x\n00000002 A ABSGLOBAL\n"


class Box:
    """Fake git/ssh/scp/tar: records every call, simulates the box."""

    def __init__(self, tmp_path, dirty="", reachable=True):
        self.dirty, self.reachable, self.calls = dirty, reachable, []
        self.fork = tmp_path / "fork"
        self.cache = tmp_path / "cache"
        self.fork.mkdir()
        self.cache.mkdir()
        self.lock = tmp_path / "lock.json"
        self.set_pin(hashlib.sha1(NDS).hexdigest())

    def set_pin(self, sha1):
        self.lock.write_text(json.dumps({"artifacts": {"heartgold_hge": {"sha1": sha1}}}))

    def install(self, monkeypatch):
        monkeypatch.setattr(hb.subprocess, "run", self.run)
        monkeypatch.setattr(hb.subprocess, "Popen", self.popen)
        monkeypatch.setattr(hb, "FORK", self.fork)
        monkeypatch.setattr(hb, "CACHE", self.cache)
        monkeypatch.setattr(hb, "LOCK", self.lock)

    def popen(self, argv, **kw):
        self.calls.append((argv, kw))
        pipe = type("P", (), {"close": lambda s: None})()
        return type("Tar", (), {"stdout": pipe, "wait": lambda s: 0, "returncode": 0})()

    def run(self, argv, **kw):
        self.calls.append((argv, kw))
        rc, out = 0, b""
        if argv[0] == "git":
            out = (self.dirty if "status" in argv else HEAD + "\n").encode()
        elif argv[0] == "ssh":
            if argv[-1] == "true" and not self.reachable:
                rc = 255
            elif "arm-none-eabi-nm" in argv[-1]:
                out = NM
            elif "make" in argv[-1]:
                kw["stdout"].write(b"make ok\n")
        elif argv[0] == "scp":
            for name, data in FILES.items():
                (kw["cwd"] / name).write_bytes(data)
        text = kw.get("text")
        return subprocess.CompletedProcess(argv, rc, out.decode() if text else out, b"")

    def ssh_cmds(self):
        return [c[0][-1] for c in self.calls if c[0][0] == "ssh"]


def test_dirty_fork_refused_before_any_ssh(tmp_path, monkeypatch):
    box = Box(tmp_path, dirty=" M src/x.c\n")
    box.install(monkeypatch)
    assert hb.main(["--build"]) == 1
    assert box.ssh_cmds() == [] and list(box.cache.iterdir()) == []


def test_plan_is_default_and_touches_nothing(tmp_path, monkeypatch, capsys):
    box = Box(tmp_path)
    box.install(monkeypatch)
    assert hb.main([]) == 0 and hb.main(["--plan"]) == 0
    assert box.calls == [] and list(box.cache.iterdir()) == []
    assert "make -j8" in capsys.readouterr().out


def test_hash_mismatch_fails_with_both_hashes(tmp_path, monkeypatch, capsys):
    box = Box(tmp_path)
    box.set_pin("0" * 40)
    box.install(monkeypatch)
    assert hb.main(["--build"]) == 1
    out = capsys.readouterr().out
    assert "0" * 40 in out and hashlib.sha1(NDS).hexdigest() in out and "FAIL" in out
    man = json.loads((box.cache / f"build-{HEAD[:12]}" / "manifest.json").read_text())
    assert man["result"] == "FAIL"


def test_unreachable_is_skip_code(tmp_path, monkeypatch):
    box = Box(tmp_path, reachable=False)
    box.install(monkeypatch)
    assert hb.main(["--build"]) == 2
    assert not any("make" in c for c in box.ssh_cmds())


def test_pass_manifest_fields_and_export_compare(tmp_path, monkeypatch):
    box = Box(tmp_path)
    box.install(monkeypatch)
    (box.cache / "offsets.ini").write_bytes(b"offsets")  # equal
    (box.cache / "rom_gen.ld").write_bytes(b"old")  # different
    (box.cache / "nm_all.txt").write_bytes(b"## build/linked.o\n023d8060 T x\n")  # equal once a/A symbols are dropped
    assert hb.main(["--build"]) == 0
    man = json.loads((box.cache / f"build-{HEAD[:12]}" / "manifest.json").read_text())
    assert man["fork_commit"] == HEAD and man["result"] == "PASS"
    assert man["box_build_command"].endswith("make -j8") and man["started_utc"] and man["finished_utc"]
    assert man["fresh_sha1"] == man["pinned_sha1"] == hashlib.sha1(NDS).hexdigest()
    for name in ("test.nds", "offsets.ini", "rom_gen.ld", "nm_all.txt"):
        assert {"sha1", "md5", "sha256", "size_bytes"} <= set(man["files"][name])
    assert man["files"]["test.nds"]["md5"] == hashlib.md5(NDS).hexdigest()
    assert man["exports_vs_cache"] == {"offsets.ini": "equal", "rom_gen.ld": "different", "nm_all.txt": "equal"}
    assert (box.cache / f"build-{HEAD[:12]}" / "nm_all.txt").read_bytes() == NM  # raw nm is stored unfiltered


def test_sync_uses_build_remote_excludes_and_incremental_make(tmp_path, monkeypatch):
    box = Box(tmp_path)
    box.install(monkeypatch)
    hb.main(["--build"])
    tar = next(c for c in box.calls if c[0][0] == "tar")[0]
    assert {"--exclude-vcs", "--exclude=*.nds", "--exclude=.venv", "--exclude=./build_output", "--exclude=./docs"} <= set(tar)
    assert any(c.endswith("make -j8") for c in box.ssh_cmds())


def test_writes_only_under_cache_never_in_fork(tmp_path, monkeypatch):
    box = Box(tmp_path)
    box.install(monkeypatch)
    assert hb.main(["--build"]) == 0
    out = (box.cache / f"build-{HEAD[:12]}").resolve()
    for argv, kw in box.calls:
        if argv[0] == "scp":  # scp lands in cwd (dest ".") and must be the cache dir
            assert kw["cwd"].resolve() == out and argv[-1] == "."
            assert not any(a.startswith(str(box.fork)) for a in argv)
    assert not list(box.fork.iterdir())
    assert not any(p.is_relative_to(box.fork) for p in box.cache.rglob("*"))


def test_cache_inside_fork_refused(tmp_path, monkeypatch):
    box = Box(tmp_path)
    box.install(monkeypatch)
    monkeypatch.setattr(hb, "CACHE", box.fork / "build_output")
    with pytest.raises(hb.Refused):
        hb.build()
    assert box.ssh_cmds() == []
