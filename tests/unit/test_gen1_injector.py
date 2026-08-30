"""The structural injector: the delivery path for a ROM whose hash cannot be known.

A UPS is a delta against ONE exact source and carries that source's CRC32, so it cannot
patch a randomized cartridge — every seed is a different file. `build.py` has the opposite
constraint: it is the deterministic build tool and is gated on the two pinned clean SHA-1s,
which is correct and must stay that way.

So `inject.py` asks a different question. Not "is this the dump I expect?" but "does every
byte I am about to overwrite hold exactly what the manifest says it should?" — twelve
spans, the eight-byte VBlank hook site, an empty target bank, an untouched header.

The refusals matter more than the success. A half-patched cartridge boots and then
misbehaves in a way nobody can attribute, so every check runs before anything is written.
"""
from __future__ import annotations

import importlib.util
import os

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_TOOLS = os.path.join(_REPO, "patch", "gen1", "tools")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_TOOLS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def inj():
    import sys
    sys.path.insert(0, _TOOLS)
    return _load("inject")


@pytest.fixture(scope="module")
def manifest():
    import sys
    sys.path.insert(0, _TOOLS)
    return _load("manifest")


@pytest.fixture
def clean():
    path = os.path.join(_REPO, "patch", "build", "gen1_red.gb")
    if not os.path.exists(path):
        pytest.skip("clean Red dump not present (ROMs are gitignored)")
    with open(path, "rb") as f:
        return f.read()


# ── the manifest is shared, not duplicated ───────────────────────────────────────────

def test_both_paths_read_the_same_manifest(inj, manifest):
    """The reason this is one module and not two copies. build.py applies these spans to
    a pinned clean dump; inject.py applies them structurally. If either kept its own copy
    they would drift, and the drift would only show up on a player's cartridge."""
    build_src_path = os.path.join(_TOOLS, "build.py")
    with open(build_src_path, encoding="utf-8") as f:
        build_src = f.read()
    assert "from manifest import" in build_src, "build.py no longer shares the manifest"
    assert "MENU_PATCHES" not in build_src.split("from manifest import")[0], \
        "build.py appears to define its own MENU_PATCHES again"
    assert len(manifest.MENU_PATCHES) >= 9


# ── the happy path ───────────────────────────────────────────────────────────────────

def test_a_clean_rom_injects(inj, clean, manifest):
    out = inj.inject(clean)
    assert len(out) == len(clean), "the ROM changed size"
    lo, hi = manifest.PROTECTED_RANGE
    assert out[lo:hi + 1] == clean[lo:hi + 1], "the cartridge header was modified"


def test_the_result_carries_the_module_and_the_hook(inj, clean, manifest):
    out = inj.inject(clean)
    payload = inj.load_payload()
    base = manifest.INJECT_OFFSET
    assert out[base:base + len(payload)] == payload
    site = out[manifest.HOOK_SITE:manifest.HOOK_SITE + len(manifest.HOOK_ORIGINAL)]
    assert site[1] == manifest.HOOK_BANK
    assert (site[3] | (site[4] << 8)) == manifest.HOOK_TARGET


def test_it_matches_what_the_build_tool_produces(inj, clean):
    """The strongest available check: the structural path and the hash-gated build path
    must agree byte for byte on the one input where both can run."""
    built = os.path.join(_REPO, "patch", "gen1", "build", "slink_red.gb")
    if not os.path.exists(built):
        pytest.skip("slink_red.gb not built — `python patch/gen1/tools/build.py`")
    with open(built, "rb") as f:
        expected = f.read()
    assert inj.inject(clean) == expected


# ── the refusals ─────────────────────────────────────────────────────────────────────

def test_a_wrong_sized_file_is_refused(inj):
    with pytest.raises(inj.InjectError, match="Game Boy ROM"):
        inj.inject(b"\x00" * 4096)


def test_a_rom_whose_hook_site_moved_is_refused(inj, clean, manifest):
    """The randomized path has no hash to lean on, so this check IS the safety."""
    broken = bytearray(clean)
    broken[manifest.HOOK_SITE] ^= 0xFF
    with pytest.raises(inj.InjectError) as e:
        inj.inject(bytes(broken))
    assert "hook site" in str(e.value)
    assert "nothing was written" in str(e.value)


def test_a_rom_whose_menu_span_moved_is_refused(inj, clean, manifest):
    off = manifest.MENU_PATCHES[2][0]
    broken = bytearray(clean)
    broken[off] ^= 0xFF
    with pytest.raises(inj.InjectError) as e:
        inj.inject(bytes(broken))
    assert f"{off:#06x}" in str(e.value)


def test_a_rom_with_a_used_target_bank_is_refused(inj, clean, manifest):
    """A hack that already uses bank $3F would have its code destroyed."""
    broken = bytearray(clean)
    broken[manifest.INJECT_OFFSET + 0x100] = 0x42
    with pytest.raises(inj.InjectError, match="not empty"):
        inj.inject(bytes(broken))


def test_every_problem_is_reported_at_once(inj, clean, manifest):
    """One refusal listing everything wrong, rather than one per run: whoever is holding
    an unpatchable ROM needs to know what it is, not the first thing checked."""
    broken = bytearray(clean)
    broken[manifest.HOOK_SITE] ^= 0xFF
    broken[manifest.MENU_PATCHES[0][0]] ^= 0xFF
    broken[manifest.MENU_PATCHES[1][0]] ^= 0xFF
    with pytest.raises(inj.InjectError) as e:
        inj.inject(bytes(broken))
    assert str(e.value).count("  - ") >= 3


# ── the reapply matrix ───────────────────────────────────────────────────────────────

def test_reapplying_the_same_patch_is_a_named_no_op(inj, clean):
    once = inj.inject(clean)
    with pytest.raises(inj.InjectError, match="already carries exactly this"):
        inj.inject(once)


def test_a_different_slink_patch_is_refused_with_a_way_forward(inj, clean, manifest):
    """ABI 2 in the field. Re-patching over it cannot work — the spans it displaced no
    longer hold what the manifest expects — so say that, rather than emitting twelve
    span mismatches that read like a corrupt ROM."""
    once = bytearray(inj.inject(clean))
    # Change the ABI byte the module writes, so it is recognisably a different build.
    bank = once[manifest.INJECT_OFFSET:manifest.INJECT_OFFSET + 0x4000]
    idx = bank.find(bytes([0x3E, 0x53, 0xEA, 0xE2, 0xDE]))
    assert idx >= 0, "beacon writer not found — this test's premise is stale"
    for i in range(idx, idx + 64):
        if bank[i] == 0x3E and bank[i + 2:i + 5] == bytes([0xEA, 0xE6, 0xDE]):
            once[manifest.INJECT_OFFSET + i + 1] = 2
            break
    else:
        pytest.fail("ABI store not found in the payload")
    with pytest.raises(inj.InjectError) as e:
        inj.inject(bytes(once))
    assert "ABI 2" in str(e.value)
    assert "unpatched randomized ROM" in str(e.value)


def test_describe_reads_the_abi_out_of_a_patched_rom(inj, clean):
    st = inj.describe(inj.inject(clean))
    assert st["already"] is not None
    assert st["already"]["abi"] == 3
    assert st["already"]["identical"] is True


def test_describe_never_raises_on_rubbish(inj):
    """It is the reporting path — the CLI's --check and the caller's decision input —
    so it has to survive anything handed to it."""
    for blob in (b"", b"\x00" * 10, b"\xff" * (1024 * 1024)):
        inj.describe(blob)
