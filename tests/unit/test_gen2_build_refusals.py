"""Independent public-CLI refusal oracles; all source/tool/build IO is synthetic.

Every negative starts from a successful complete build. Only subprocess.run is
faked: lock parsing, source checks, executable inspection, hashing, map parsing,
and publication use the production path. These are MODEL tests, not build receipts.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    "pokecrystal": "7a7881d0d62e0ddbd82dcf10e7116807487ac651",
    "pokegold": "656583c939d30f920a316177311a502dd222b57c",
}
OUTPUTS = {
    "pokecrystal": "pokecrystal",
    "pokecrystal11": "pokecrystal",
    "pokegold": "pokegold",
    "pokesilver": "pokegold",
}
RGBDS_TOOLS = ("rgbasm", "rgblink", "rgbfix", "rgbgfx")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot(directory: Path) -> dict[str, tuple[bytes, int]]:
    """Catch same-byte rewrites as well as changed/added/deleted files."""
    if not directory.exists():
        return {}
    return {
        str(path.relative_to(directory)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in directory.rglob("*")
        if path.is_file()
    }


class BuildWorld:
    """A small subprocess boundary representing two user-provided repositories."""

    def __init__(self, root: Path):
        self.root = root
        self.lock_path = root / "sources.lock.json"
        self.out = root / "published"
        self.repos = {name: root / name for name in SOURCES}
        self.heads = dict(SOURCES)
        self.dirty: dict[str, str] = {}
        self.versions = {name: f"{name} v1.0.3\n" for name in RGBDS_TOOLS}
        self.rgbds = root / "rgbds-v1.0.3"
        self.devkit = root / "w64devkit-2.10.0" / "bin"
        self.calls: list[list[str]] = []
        self.omit: set[str] = set()
        self.corrupt: set[str] = set()
        self.artifacts: dict[str, bytes] = {}
        for repo in self.repos.values():
            (repo / ".git").mkdir(parents=True)
            (repo / "Makefile").write_text("# synthetic upstream source\n", encoding="utf-8")
        for directory, names in (
            (self.rgbds, RGBDS_TOOLS),
            (self.devkit, ("make", "gcc", "g++", "cc", "sh", "bash", "busybox")),
        ):
            directory.mkdir(parents=True)
            for name in names:
                path = directory / (name + (".exe" if os.name == "nt" else ""))
                path.write_bytes(f"synthetic executable: {name}\n".encode())
                path.chmod(0o755)
        (self.devkit.parent / "VERSION").write_text("2.10.0\n", encoding="ascii")
        self.lock = {
            "schema_version": 1,
            "rgbds_version": "v1.0.3",
            "w64devkit_version": "2.10.0",
            "sources": {
                name: {
                    "url": f"https://github.com/pret/{name}",
                    "commit": commit,
                    "make_targets": [f"{key}.gbc" for key, source in OUTPUTS.items() if source == name],
                }
                for name, commit in SOURCES.items()
            },
            "outputs": {},
        }
        self.generation(1)

    def generation(self, number: int) -> None:
        for name, source in OUTPUTS.items():
            rom = (f"synthetic ROM {name}\n".encode() * 64)[:512]
            sym = f"; generation {number}\n00:0100 {name}_Entry\n".encode()
            # This is ordinary RGBDS map syntax, independent of parse_map's schema.
            map_data = (
                "ROM0 bank #0:\n"
                "  EMPTY: $0000-$00ff ($0100 bytes)\n"
                f'  SECTION: $0100-$010f ($0010 bytes) ["{name} generation {number}"]\n'
                "  EMPTY: $0110-$3fff ($3ef0 bytes)\n"
                "  TOTAL EMPTY: $3ff0 bytes\n"
            ).encode()
            self.artifacts.update({f"{name}.gbc": rom, f"{name}.sym": sym, f"{name}.map": map_data})
            self.lock["outputs"][name] = {
                "source": source,
                "filename": f"{name}.gbc",
                "sha1": hashlib.sha1(rom).hexdigest(),
                "state": "BUILT",
                "sym_sha256": _sha256(sym),
                "map_sha256": _sha256(map_data),
            }
        self.write_lock()

    def write_lock(self) -> None:
        self.lock_path.write_text(json.dumps(self.lock, indent=2) + "\n", encoding="utf-8")

    def argv(self, *extra: str, out: Path | None = None) -> list[str]:
        return [
            "--lock", str(self.lock_path),
            "--out-dir", str(self.out if out is None else out),
            "--crystal-repo", str(self.repos["pokecrystal"]),
            "--gold-repo", str(self.repos["pokegold"]),
            "--rgbds-bin", str(self.rgbds),
            "--w64devkit-bin", str(self.devkit),
            *extra,
        ]

    def run(self, command, **kwargs):
        args = [str(item) for item in command]
        self.calls.append(args)
        executable = Path(args[0]).stem
        stdout = ""
        if executable == "git":
            # No synthetic checkout/reset hides mutations of caller-owned sources.
            if "-C" in args:
                index = args.index("-C")
                repo = Path(args[index + 1])
                operation = args[index + 2:]
            else:
                repo = Path(kwargs["cwd"])
                operation = args[1:]
            source = next(name for name, path in self.repos.items() if path == repo)
            if operation[:2] == ["rev-parse", "HEAD"]:
                stdout = self.heads[source] + "\n"
            elif operation and operation[0] == "status":
                stdout = self.dirty.get(source, "")
            elif operation == ["rev-parse", "--is-inside-work-tree"]:
                stdout = "true\n"
            elif operation == ["rev-parse", "--show-toplevel"]:
                stdout = str(repo) + "\n"
            else:
                raise AssertionError(f"Unexpected Git operation on provided repository: {args!r}")
        elif executable in RGBDS_TOOLS and args[1:] in (["--version"], ["-V"]):
            stdout = self.versions[executable]
        elif executable in {"make", "gcc", "g++", "cc", "sh", "bash", "busybox"} and "--version" in args:
            stdout = {
                "make": "GNU Make 4.4.1\n",
                "gcc": "gcc (GCC) 15.1.0\n",
                "g++": "g++ (GCC) 15.1.0\n",
            }.get(executable, f"{executable} 1.0\n")
        elif executable == "sh" and args[1:] == ["--help"]:
            stdout = "BusyBox ash shell\n"
        elif executable == "sh" and args[1:] == ["-c", "printf gen2-shell-ready"]:
            stdout = "gen2-shell-ready"
        elif executable == "make":
            repo = Path(kwargs["cwd"])
            source = next(name for name, path in self.repos.items() if path == repo)
            if "clean" in args:
                for path in repo.iterdir():
                    if path.suffix in {".gbc", ".sym", ".map"}:
                        path.unlink()
            else:
                for name, owner in OUTPUTS.items():
                    if owner != source:
                        continue
                    for extension in ("gbc", "sym", "map"):
                        filename = f"{name}.{extension}"
                        path = repo / filename
                        if filename in self.omit:
                            path.unlink(missing_ok=True)
                        else:
                            data = self.artifacts[filename]
                            path.write_bytes(data + b"CORRUPT" if filename in self.corrupt else data)
        else:
            raise AssertionError(f"Unexpected external process (no real builds or network): {args!r}")
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    def receipt(self):
        return _snapshot(self.out), (self.lock_path.read_bytes(), self.lock_path.stat().st_mtime_ns)


@pytest.fixture
def working_build(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "tools"))
    builder = importlib.import_module("build_gen2_syms")
    world = BuildWorld(tmp_path)
    monkeypatch.setattr(subprocess, "run", world.run)
    assert builder.main(world.argv()) == 0, "refusal oracle requires a working positive fixture"
    expected = {f"{name}.{ext}" for name in OUTPUTS for ext in ("sym", "map")}
    expected.update({"build_provenance.json", "linker_slack.json"})
    assert set(_snapshot(world.out)) == expected
    for filename, data in world.artifacts.items():
        if not filename.endswith(".gbc"):
            assert (world.out / filename).read_bytes() == data
    return builder, world


@pytest.mark.parametrize("source", SOURCES)
def test_wrong_provided_source_head_refuses_without_reset(working_build, source):
    builder, world = working_build
    before = world.receipt()
    world.heads[source] = "0" * 40
    assert builder.main(world.argv()) != 0
    assert world.receipt() == before


@pytest.mark.parametrize("source", SOURCES)
def test_tracked_source_edit_refuses(working_build, source):
    builder, world = working_build
    before = world.receipt()
    world.dirty[source] = " M main.asm\n"
    assert builder.main(world.argv()) != 0
    assert world.receipt() == before


@pytest.mark.parametrize("executable", RGBDS_TOOLS)
def test_override_directory_label_cannot_replace_actual_version_check(working_build, executable):
    builder, world = working_build
    before = world.receipt()
    world.versions[executable] = f"{executable} v1.0.2\n"
    assert world.rgbds.name == "rgbds-v1.0.3"
    assert builder.main(world.argv()) != 0
    assert world.receipt() == before


@pytest.mark.parametrize("name", OUTPUTS)
def test_each_rom_hash_is_required(working_build, name):
    builder, world = working_build
    before = world.receipt()
    world.corrupt.add(f"{name}.gbc")
    assert builder.main(world.argv()) != 0
    assert world.receipt() == before


@pytest.mark.parametrize("extension", ("sym", "map"))
def test_missing_final_title_artifact_refuses(working_build, extension):
    builder, world = working_build
    before = world.receipt()
    world.omit.add(f"pokesilver.{extension}")
    assert builder.main(world.argv()) != 0
    assert world.receipt() == before


def test_check_rebuilds_without_writing_output_or_lock(working_build):
    builder, world = working_build
    before = world.receipt()
    world.calls.clear()
    assert builder.main(world.argv("--check")) == 0
    assert any(Path(call[0]).stem == "make" and "--version" not in call for call in world.calls)
    assert world.receipt() == before


def test_check_refuses_artifact_drift_without_repairing_it(working_build):
    builder, world = working_build
    (world.out / "pokecrystal.sym").write_bytes(b"different published symbol table\n")
    before = world.receipt()
    assert builder.main(world.argv("--check")) != 0
    assert world.receipt() == before


def test_late_invalid_rom_cannot_partially_publish_new_artifact_bytes(working_build):
    builder, world = working_build
    old_output = _snapshot(world.out)
    world.generation(2)
    # Establish the entire candidate generation is valid before adding one fault.
    candidate = world.root / "verified-candidate"
    assert builder.main(world.argv(out=candidate)) == 0
    assert (candidate / "pokecrystal.sym").read_bytes() != (world.out / "pokecrystal.sym").read_bytes()
    before = world.receipt()
    world.corrupt.add("pokesilver.gbc")
    assert builder.main(world.argv()) != 0
    assert world.receipt() == before
    assert _snapshot(world.out) == old_output
