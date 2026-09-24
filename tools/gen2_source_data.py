"""Verified, read-only source context for selected Gen 2 data generators.

    from tools.gen2_source_data import load_context, rom_offset
    ctx = load_context("crystal")
    offset = rom_offset(*ctx.symbol("BaseData"))

This boundary admits source facts, never runtime write permission. It validates
the P1 receipt and exact disk bytes on every load; there is no implicit repinning,
legacy symbol JSON fallback, source checkout, or build operation.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from .gen_gen2_admission import validate_provenance
    from .rgbds_symbols import Symbol, parse_symbols, rom_offset
else:
    from gen_gen2_admission import validate_provenance
    from rgbds_symbols import Symbol, parse_symbols, rom_offset

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = {"crystal": "pokecrystal", "gold": "pokegold", "silver": "pokesilver"}
__all__ = ["ROOT", "ARTIFACTS", "SourceContext", "Symbol", "load_context", "rom_offset"]


def _json(raw: bytes, label: str) -> dict:
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(f"{label}: expected an object")
    return value


def _hash(data: bytes, expected: str, label: str, algorithm: str = "sha256") -> None:
    actual = hashlib.new(algorithm, data).hexdigest()
    if actual != expected:
        raise ValueError(f"{label}: {algorithm} {actual} differs from pinned {expected}")


def _git(source: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(source), *args], capture_output=True,
                            text=True, check=False)
    if result.returncode:
        raise ValueError(f"cannot verify source {source}: {result.stderr.strip()}")
    return result.stdout.strip()


def _source_blob(source: Path, commit: str, relative: str) -> str:
    # The worktree can change immediately after status succeeds. Read the exact
    # commit's blob instead; cat-file does not apply checkout/textconv filters.
    # Disable replacement refs so a local replacement cannot substitute content
    # while retaining the locked commit's name in generated provenance.
    result = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(source), "cat-file", "blob",
         f"{commit}:{relative}"],
        capture_output=True, check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"cannot read pinned source blob {commit}:{relative}: {detail}")
    # Match Path.read_text(encoding='utf-8') universal-newline behavior without
    # stripping leading/trailing whitespace or blank lines from the source.
    return result.stdout.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


@dataclass(frozen=True)
class SourceContext:
    title: str
    artifact: str
    rom: bytes
    symbols: dict[str, Symbol]
    source_dir: Path
    source_commit: str
    lock: dict
    provenance: dict
    lock_sha256: str
    provenance_sha256: str

    def symbol(self, name: str) -> Symbol:
        try:
            return self.symbols[name]
        except KeyError as exc:
            raise ValueError(f"{self.title}: required symbol {name!r} missing") from exc

    def read_source(self, relative: str) -> str:
        # ponytail: per-context memo; the HEAD/tracked/clean checks run on a path's first read in this
        # context (one context per run), later reads reuse the verified blob instead of 4 git spawns each
        cache = self.__dict__.setdefault("_source_cache", {})
        if relative not in cache:
            cache[relative] = self._read_source_checked(relative)
        return cache[relative]

    def _read_source_checked(self, relative: str) -> str:
        path = (self.source_dir / relative).resolve()
        if not path.is_relative_to(self.source_dir):
            raise ValueError(f"source path escapes pinned checkout: {relative!r}")
        if _git(self.source_dir, "rev-parse", "HEAD") != self.source_commit:
            raise ValueError(f"{self.title}: source HEAD changed after context creation")
        # Source content must be tracked, not an ignored build artifact masquerading
        # as an ASM input. Keep the checkout checks, but never use its mutable text
        # as the returned source authority after those checks have completed.
        rel = path.relative_to(self.source_dir).as_posix()
        tracked = _git(self.source_dir, "ls-files", "--error-unmatch", "--", rel)
        if tracked != rel:
            raise ValueError(f"source path is not uniquely tracked: {relative!r}")
        if _git(self.source_dir, "status", "--porcelain", "--", rel):
            raise ValueError(f"source changed after verification: {relative!r}")
        return _source_blob(self.source_dir, self.source_commit, rel)

    def source_record(self) -> dict:
        spec = self.lock["outputs"][self.artifact]
        return {
            "evidence_level": "SOURCE", "artifact": self.artifact,
            "repo": spec["source"], "commit": self.source_commit,
            "rom_sha1": spec["sha1"], "sym_sha256": spec["sym_sha256"],
            "map_sha256": spec["map_sha256"], "lock_sha256": self.lock_sha256,
            "build_provenance_sha256": self.provenance_sha256,
        }


def load_context(title: str, root: Path = ROOT) -> SourceContext:
    if title not in ARTIFACTS:
        raise ValueError(f"unsupported selected title {title!r}; expected {tuple(ARTIFACTS)}")
    root = Path(root).resolve()
    lock_raw = (root / "data/gen2_sources.lock.json").read_bytes()
    provenance_raw = (root / "data/gen2/build_provenance.json").read_bytes()
    lock = _json(lock_raw, "source lock")
    provenance = _json(provenance_raw, "build provenance")
    validate_provenance(lock, provenance, lock_bytes=lock_raw)
    artifact = ARTIFACTS[title]
    sym_raw = None
    for name, spec in lock["outputs"].items():
        for ext in ("sym", "map"):
            filename = f"{name}.{ext}"
            raw = (root / "data/gen2" / filename).read_bytes()
            _hash(raw, spec[f"{ext}_sha256"], filename)
            if name == artifact and ext == "sym":
                sym_raw = raw
    spec = lock["outputs"][artifact]
    source = (root / ".cache/gen2-build" / spec["source"]).resolve()
    expected_commit = lock["sources"][spec["source"]]["commit"]
    if Path(_git(source, "rev-parse", "--show-toplevel")).resolve() != source:
        raise ValueError(f"source directory is not a repository root: {source}")
    if _git(source, "rev-parse", "HEAD") != expected_commit:
        raise ValueError(f"{title}: source HEAD differs from locked commit")
    if _git(source, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError(f"{title}: source tree is dirty")
    rom = (source / spec["filename"]).read_bytes()
    _hash(rom, spec["sha1"], spec["filename"], "sha1")
    if sym_raw is None:
        raise ValueError(f"selected symbol artifact missing: {artifact}")
    return SourceContext(title, artifact, rom, parse_symbols(sym_raw.decode("utf-8")), source,
                         expected_commit, lock, provenance, hashlib.sha256(lock_raw).hexdigest(),
                         hashlib.sha256(provenance_raw).hexdigest())
