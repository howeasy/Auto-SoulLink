"""content_identity must not depend on where a UPR pair was prepared.

server/gen1_prepared_cartridges.py used to hash the raw per-player `generation` record
straight from upr_runner.py, which carries `"output": str(output)` — an absolute path
unique to the run directory. Two runs prepared from byte-identical ROM + settings + seed
therefore got different content_profile_hash values, and a resumed run was refused at
gen1_run_config.py's "resumed run must use the predecessor cartridge pair" check even
though the cartridges were identical. `content_identity` hashes a location-free view of
`generation` instead.

Round 2: `generation.custom_names.selection` is a SECOND run-local absolute path.
`selected_custom_names` (upr_runner.py:56-66) returns `{"kind": "explicit", "path":
str(resolved_path)}` (or "file"/"path", or "jar-resource"/"member") as `selection`, and
`run_pinned` (upr_runner.py:138) puts it straight into the generation record as
`custom_names": {"sha256": ..., "selection": selection}`. This is present even when the
Manager passed no explicit override (the default resolution still records an absolute
`path`). The fixture below builds `custom_names` in that real nested shape.
"""
from server.gen1_prepared_cartridges import content_identity


def _generation(output, custom_names_path=r"C:\upr\jar\customnames.rncn"):
    """A stand-in for upr_runner.py's per-player generation record (lines 56-66, 134-140):
    `output` is the run-local absolute path to randomized.gbc, and `custom_names.selection`
    (here `{"kind": "explicit", "path": custom_names_path}`) is the run-local absolute path
    selected_custom_names() resolved and recorded — a second location leak of the same kind.
    """
    return {"schema": "slink-upr-run-v1", "status": "produced_requires_semantic_scan",
        "source_commit": "deadbeef", "generation": 1, "jar_sha256": "a" * 64, "bridge_sha256": "b" * 64,
        "settings_sha256": "c" * 64, "gen1_policy_sha256": "d" * 64, "source_sha256": "e" * 64,
        "source_sha1": "f" * 40, "seed": "123456789",
        "custom_names": {"sha256": "1" * 64, "selection": {"kind": "explicit", "path": custom_names_path}},
        "effective_settings_string": "abc", "log_sha256": "2" * 64,
        "output": output, "output_sha256": "3" * 64, "output_sha1": "4" * 40, "size": 12345}


SEMANTIC_PROFILE = {"variant": "yellow", "species": ["bulbasaur", "charmander"]}
MANIFEST_SHA256 = "5" * 64


def test_content_identity_ignores_the_absolute_output_path():
    a = content_identity(SEMANTIC_PROFILE, MANIFEST_SHA256, _generation(r"C:\runs\run_1\generation\a\randomized.gbc"))
    b = content_identity(SEMANTIC_PROFILE, MANIFEST_SHA256, _generation(r"E:\other\run_2\generation\a\randomized.gbc"))
    assert a == b


def test_content_identity_ignores_the_custom_names_selection_path_even_with_output_too():
    """Both run-local absolute paths differ at once — output AND custom_names.selection.path —
    and identity must still agree, because both are just where the run happened to sit."""
    a = content_identity(SEMANTIC_PROFILE, MANIFEST_SHA256,
        _generation(r"C:\runs\run_1\generation\a\randomized.gbc", r"C:\runs\run_1\generation\a\customnames.rncn"))
    b = content_identity(SEMANTIC_PROFILE, MANIFEST_SHA256,
        _generation(r"E:\other\run_2\generation\a\randomized.gbc", r"E:\other\run_2\generation\a\customnames.rncn"))
    assert a == b


def test_content_identity_changes_with_custom_names_sha256():
    base = _generation("out")
    other = dict(base, custom_names={**base["custom_names"], "sha256": "9" * 64})
    assert (content_identity(SEMANTIC_PROFILE, MANIFEST_SHA256, base)
            != content_identity(SEMANTIC_PROFILE, MANIFEST_SHA256, other))


def test_content_identity_changes_with_settings_sha256():
    base = _generation("out")
    other = dict(base, settings_sha256="9" * 64)
    assert (content_identity(SEMANTIC_PROFILE, MANIFEST_SHA256, base)
            != content_identity(SEMANTIC_PROFILE, MANIFEST_SHA256, other))


def test_content_identity_changes_with_seed():
    base = _generation("out")
    other = dict(base, seed="987654321")
    assert (content_identity(SEMANTIC_PROFILE, MANIFEST_SHA256, base)
            != content_identity(SEMANTIC_PROFILE, MANIFEST_SHA256, other))


def test_content_identity_changes_with_output_sha256():
    base = _generation("out")
    other = dict(base, output_sha256="6" * 64)
    assert (content_identity(SEMANTIC_PROFILE, MANIFEST_SHA256, base)
            != content_identity(SEMANTIC_PROFILE, MANIFEST_SHA256, other))


def test_content_identity_changes_with_semantic_profile_or_manifest_hash():
    generation = _generation("out")
    baseline = content_identity(SEMANTIC_PROFILE, MANIFEST_SHA256, generation)
    assert content_identity({"variant": "red"}, MANIFEST_SHA256, generation) != baseline
    assert content_identity(SEMANTIC_PROFILE, "7" * 64, generation) != baseline
