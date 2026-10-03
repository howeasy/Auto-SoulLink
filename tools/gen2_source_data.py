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
from contextlib import contextmanager
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
__all__ = ["ROOT", "ARTIFACTS", "SourceContext", "OverlayContext", "Symbol",
           "load_context", "load_overlay_context", "rom_offset"]


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


class SourceUnavailable(ValueError):
    """The pinned decomp clone is ABSENT (.cache/gen2-build/<repo> not provisioned). Distinct from a
    source that exists but is dirty, at another commit or hash-mismatched: those stay plain ValueError
    hard failures. Tests turn only this one into a named skip (tests/conftest.py); a release gate that
    needs the source still counts that skip as red."""


class SourceVerificationUnavailable(ValueError):
    """The pinned checkout could not be VERIFIED because git itself could not answer -- git missing,
    killed, resource-starved, or a lock/index it could not read. A NON-ZERO git exit with no diagnostic
    is that, not a verdict: an empty stderr means git never got far enough to judge the source. The
    source may be perfectly intact. Callers must still fail closed (never treat this as verified), but
    they must report it as infrastructure, so a flaky lane is not published as a stale artifact and a
    release gate does not read it as proof the source changed."""

    def __init__(self, source: Path, args: tuple, detail: str = ""):
        command = " ".join(("git", *args))
        self.source, self.args, self.detail = Path(source), tuple(args), detail
        reason = detail or "git produced no diagnostic"
        super().__init__(f"cannot verify source {source}: git exited non-zero for `{command}` -- {reason}. "
                         f"This is an INFRASTRUCTURE failure, not a source-integrity verdict: the source is "
                         f"UNVERIFIED here, so nothing downstream may treat it as verified or as changed")




# git's own words for "I could not do the job", as opposed to "here is the answer". These are the
# failure modes a busy shared lane actually produces (several agents and test runs against one
# checkout), and none of them is a statement about the source's content.
_GIT_INFRASTRUCTURE = (
    "could not lock", "unable to create", "cannot lock", "unable to write", "failed to write",
    "index file", "too many open files", "resource temporarily unavailable", "out of memory",
    "cannot allocate", "broken pipe", "the requested operation cannot be performed",
)


def _git(source: Path, *args: str) -> str:
    """One read-only git query against the pinned checkout, with two deliberately distinct failures.

    INTEGRITY. This module judges the source itself, and it does so by comparing git's SUCCESSFUL
    output (rev-parse/ls-files/status) -- "source tree is dirty", "source HEAD differs from locked
    commit". A git that RAN and reported some OTHER failure has therefore not judged the content, so
    it stays a plain ValueError and --check and the release gates keep failing closed on it.

    INFRASTRUCTURE. A git that could not do its job at all -- no diagnostic, a spawn error, or one of
    its own lock/resource complaints -- could not answer, so the source is UNVERIFIED rather than
    changed. That is SourceVerificationUnavailable: still a refusal (it never returns a value, so it
    can never be mistaken for a verification), but reported as infrastructure so a busy lane is not
    published as a stale artifact. Observed on this repo: the whole-file test run that failed while
    the same test passed alone was exactly a non-zero git exit with no diagnostic.
    """
    try:
        result = subprocess.run(["git", "-C", str(source), *args], capture_output=True,
                                text=True, check=False)
    except OSError as exc:   # git absent, not executable, or out of processes: never a source verdict
        raise SourceVerificationUnavailable(source, args, detail=f"{type(exc).__name__}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or "").strip()
        if not detail:
            raise SourceVerificationUnavailable(source, args)
        if any(marker in detail.lower() for marker in _GIT_INFRASTRUCTURE):
            raise SourceVerificationUnavailable(source, args, detail=detail)
        raise ValueError(f"cannot verify source {source}: {detail}")
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


@dataclass(frozen=True)
class OverlayContext:
    """Verified executed bytes/symbols with the unchanged clean fact lineage.

    Consumers use execution_record() for cartridge identity, never source_record().
    No build, mutable source overlay, or implicit clean fallback occurs here.
    """

    base: SourceContext
    rom: bytes
    symbols: dict[str, Symbol]
    publication: dict
    publication_sha256: str
    ups_sha256: str
    sym_sha256: str
    map_sha256: str

    def __getattr__(self, name):
        return getattr(self.base, name)

    def symbol(self, name: str) -> Symbol:
        try:
            return self.symbols[name]
        except KeyError as exc:
            raise ValueError(f"{self.title}: overlay symbol {name!r} missing") from exc

    def source_record(self) -> dict:
        return self.base.source_record()

    def execution_record(self) -> dict:
        out = self.publication["outputs"][self.artifact]
        return {"kind": "overlay", "title": self.title, "rom_sha1": out["sha1"],
                "base_sha1": out["base_sha1"], "ups_sha256": self.ups_sha256,
                "sym_sha256": self.sym_sha256, "map_sha256": self.map_sha256,
                "overlay_provenance_sha256": self.publication_sha256}


def load_overlay_context(title: str, root: Path = ROOT) -> OverlayContext:
    """Apply the published UPS to the locked base and verify all execution inputs."""
    from patch.tools.make_ups import ups_apply

    root = Path(root).resolve()
    base = load_context(title, root=root)
    raw = (root / "data/gen2/overlay_provenance.json").read_bytes()
    publication = _json(raw, "overlay provenance")
    if publication.get("schema") != "gen2-overlay-provenance-v1":
        raise ValueError("overlay provenance: unsupported schema")
    if publication.get("sources") != base.lock["sources"]:
        raise ValueError("overlay provenance source commits differ from clean lock")
    overlay = publication["overlay"]
    source_dir = (root / overlay["src_dir"]).resolve()
    if not source_dir.is_relative_to(root):
        raise ValueError("overlay assembly input directory escapes the repository")
    for name, expected in overlay["sources_sha256"].items():
        source = (root / name if name.startswith("patch/") else source_dir / name).resolve()
        if not source.is_relative_to(root):
            raise ValueError("overlay assembly input escapes the repository")
        _hash(source.read_bytes().replace(b"\r\n", b"\n"), expected, f"overlay source {name}")
    out = publication["outputs"][base.artifact]
    if out.get("base_sha1") != base.source_record()["rom_sha1"] or out.get("slink_title") != title:
        raise ValueError("overlay provenance base/title differs from clean facts")
    if out.get("identical_to_clean") is not False or out.get("sha1") == out.get("base_sha1"):
        raise ValueError("null overlay is not an executed overlay artifact")
    relative = Path(out["ups"]["file"])
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root):
        raise ValueError("overlay UPS path escapes the repository")
    ups = path.read_bytes()
    _hash(ups, out["ups"]["sha256"], "overlay UPS")
    rom = ups_apply(base.rom, ups)
    _hash(rom, out["sha1"], "overlay ROM", "sha1")
    if len(rom) != len(base.rom):
        raise ValueError("overlay changed ROM geometry")
    symbols = None
    hashes = {}
    for ext in ("sym", "map"):
        name = f"{title}_slink.{ext}"
        text = (root / "data/gen2" / name).read_bytes().replace(b"\r\n", b"\n")
        _hash(text, publication["symbols"][name], name)
        hashes[ext] = hashlib.sha256(text).hexdigest()
        if ext == "sym":
            symbols = parse_symbols(text.decode("utf-8"))
    assert symbols is not None
    for name, old in base.symbols.items():
        new = symbols.get(name)
        movable = old.bank == 4 and 0x4000 <= old.address < 0x8000
        if new is None or (movable and (new.bank != 4 or not 0x4000 <= new.address < 0x8000)):
            raise ValueError(f"{title}: overlay symbol scope differs: {name}")
        if not movable and new != old:
            raise ValueError(f"{title}: overlay moved symbol outside bank 4: {name}")
    return OverlayContext(base, rom, symbols, publication, hashlib.sha256(raw).hexdigest(),
                          hashlib.sha256(ups).hexdigest(), hashes["sym"], hashes["map"])


_SHARED: dict | None = None   # {(title, root): SourceContext} inside shared_contexts()


@contextmanager
def shared_contexts():
    """One verified SourceContext per title per run (the e2e_duo preflight): every load_context inside the
    block returns the same object, so its per-context read_source memo serves route/qualify/U1/trade facts
    alike instead of each caller re-verifying the pinned checkout. Outside the block nothing is shared."""
    global _SHARED
    outer = _SHARED
    _SHARED = {} if outer is None else outer
    try:
        yield
    finally:
        _SHARED = outer


def load_context(title: str, root: Path = ROOT) -> SourceContext:
    if _SHARED is None:
        return _load_context(title, root)
    key = (title, Path(root).resolve())
    if key not in _SHARED:
        _SHARED[key] = _load_context(title, root)
    return _SHARED[key]


def _load_context(title: str, root: Path = ROOT) -> SourceContext:
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
    if not source.is_dir():
        raise SourceUnavailable(f"{spec['source']} not cloned: {source}")
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
