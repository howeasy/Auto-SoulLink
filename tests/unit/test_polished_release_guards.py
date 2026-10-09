"""tests/unit/test_polished_release_guards.py — fail-closed guards for `gen2_polished`.

These tests do not assert that Polished *works*. They assert that every gate which is
supposed to refuse Polished still refuses it, so that a partial implementation cannot
quietly expose a half-finished title. Each guard names the blocker it protects and the
card that legitimately flips it.

Run:  python -m pytest tests/unit/test_polished_release_guards.py -q

Every test carries a RED CONTROL comment: the one-line mutation that would make it
fail. None of them has been applied.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
# Repo root only: adding server/ to sys.path makes `server.py` import itself and
# trips a circular import on `from server import calc_files`.
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import server.manager as manager  # noqa: E402
import server.patcher as patcher  # noqa: E402
import server.upr_pipeline as upr_pipeline  # noqa: E402

PROVENANCE = REPO / "data" / "polished" / "overlay_provenance.json"
PROVENANCE_LOCK = REPO / "data" / "polished_sources.lock.json"
POLISHED_SLUG = "polished-crystal"
POLISHED_FAMILY = "gen2_polished"



# Qualified Polished capabilities; receipt rebind remains a separate RC gate. Each entry says what made
# it true and what still gates it, so adding a row to this list is a deliberate act, not a
# blanket loosening of the guard below.
POLISHED_GRANTED = {
    "explode_mode": "Polished's companion Explosion/plain-faint path passed the pol-explodefix "
                    "oracles after ea90b9fd3; clean artifacts remain unsupported.",
    "rival_team_swap": "Polished's companion rival path passed pol-explode2/rival/synth-90mk5ijy; "
                       "only RIVAL0/1/2 are allowed, and freeze receipt rebind is still required.",
    "native_sounds": "patch/polished/src/slink_sfx.asm plays the shared semantic codes through "
                     "Polished's own PlaySFX, from the DelayFrame service (POL-SOUNDS). Still "
                     "gated on the SLink companion overlay: the clean cartridge advertises no "
                     "SFX bit, so the host posts nothing.",
}

def _provenance() -> dict:
    return json.loads(PROVENANCE.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- 1. patcher


def test_patcher_registers_polished_crystal() -> None:
    """Guard: the patcher must offer Polished.

    Blocker flipped by: nothing — `_register_polished` already registers it
    (server/patcher.py:228). This test exists because RELEASE.md F1 wrongly claimed
    the slug was absent; a grep of TARGETS misses a function that adds it at import.
    The real risk is the opposite direction: the registration silently disappearing
    when overlay_provenance.json is unreadable.

    RED CONTROL: delete `targets["polished-crystal"] = {...}` from
    `_register_polished` (server/patcher.py), or make `_polished_overlay_md5` raise.
    """
    assert POLISHED_SLUG in patcher.TARGETS, "polished-crystal must be a patcher target"
    target = patcher.TARGETS[POLISHED_SLUG]
    assert target["slug"] == POLISHED_SLUG
    assert target["patch"] == "SLink-Polished.ups"
    assert target["label"] == "Polished Crystal"


def test_patcher_polished_md5_is_the_overlay_build() -> None:
    """Guard: the target's `patched_md5` must equal the built overlay's md5, not a literal.

    Blocker flipped by: nothing; this pins the fail-closed live read so the digest can
    never drift from `data/polished/overlay_provenance.json`, which
    tools/build_polished_companion.py rewrites on every overlay change.

    RED CONTROL: hardcode `"patched_md5": "<32 hex>"` in `_register_polished`
    instead of calling `_polished_overlay_md5()`.
    """
    assert patcher.TARGETS[POLISHED_SLUG]["patched_md5"] == _provenance()["output"]["md5"]
    assert len(patcher.TARGETS[POLISHED_SLUG]["patched_md5"]) == 32


def test_patcher_polished_patch_file_exists_and_matches_provenance() -> None:
    """Guard: the UPS the patcher advertises must be the UPS the build recorded.

    Blocker flipped by: nothing. A rebuild of patch/polished/src rewrites both files;
    this fails if only one moved.

    RED CONTROL: change `ups.file` in data/polished/overlay_provenance.json, or rename
    patch/dist/SLink-Polished.ups, without rebuilding the other.
    """
    ups_row = _provenance()["output"]["ups"]
    ups_path = REPO / ups_row["file"]
    assert ups_path.is_file(), f"{ups_path} is advertised but missing"
    assert ups_path.name == patcher.TARGETS[POLISHED_SLUG]["patch"]
    assert hashlib.sha256(ups_path.read_bytes()).hexdigest() == ups_row["sha256"]


def test_patcher_polished_base_is_the_pinned_release_rom() -> None:
    """Guard: the base must be the pinned v3.2.3 release, not an arbitrary dump.

    Blocker flipped by: nothing. Polished ships as a full build, so `base_md5` is the
    release file's digest and `base_hint` names the sha1 from the source lock.

    RED CONTROL: change `base_md5` in `_register_polished`, or relax `base_hint` to a
    generic "a clean Polished Crystal ROM".
    """
    lock = json.loads(PROVENANCE_LOCK.read_text(encoding="utf-8"))
    target = patcher.TARGETS[POLISHED_SLUG]
    assert target["base_md5"] == "53d90e468c9eae4d602feacc6295a021"
    assert lock["outputs"]["polishedcrystal"]["sha1"] in target["base_hint"]


# --------------------------------------------------------------------------- 2. manager


def _polished_option_rows() -> dict[str, dict]:
    rows = {}
    for option, spec in manager.OPTION_SUPPORT.items():
        entry = spec.get(POLISHED_FAMILY) if isinstance(spec, dict) else None
        if isinstance(entry, dict) and "ok" in entry:
            rows[option] = entry
    return rows


def test_manager_polished_capabilities_match_the_qualified_grants() -> None:
    """Guard: only qualified Polished grants may report `ok`; receipt closure is separate.

    battle_calc is deliberately allowed to report ok (flipped 2026-10-04 with
    calc/src/calc/data/polished.js, tools/gen_polished_calc.py): the calculator runs its gen 3
    mechanics on Polished's own species/move/type data, and what that does NOT model is enumerated
    in docs/polished/CALC.md section 4 rather than hidden. native_sounds is the other exception:
    POL-SOUNDS shipped the overlay's own sound service, so it is asserted granted in
    POLISHED_GRANTED instead. Explode and Rival Swap passed their live oracles and are now
    companion-required grants; phone_calls and pc_trade_npc keep their own reasons.

    RED CONTROL: in server/manager.py, change any remaining `"gen2_polished": {"ok": False, ...}`
    to `"ok": True`, or refuse any qualified grant (the grant checks fail).
    """
    rows = _polished_option_rows()
    assert rows, "expected server.manager.OPTION_SUPPORT to carry gen2_polished rows"
    assert "explode_mode" in rows and "rival_team_swap" in rows
    assert rows["battle_calc"]["ok"] is True, "Polished's calculator dataset is shipped; do not re-refuse it"
    for option, entry in sorted(rows.items()):
        if option == "battle_calc":
            continue
        if option in POLISHED_GRANTED:
            assert entry["ok"] is True, f"{option} is listed as granted but is still refused"
            continue
        assert entry["ok"] is False, f"{option} flipped to ok for Polished without its card"
        assert entry.get("why"), f"{option} must carry a reason while refused"
    assert set(POLISHED_GRANTED) <= set(rows), "a granted option has no gen2_polished row"


def test_the_polished_grant_set_names_the_qualified_companion_options() -> None:
    """The grant set is a ledger: it names what is true now, not what might become true."""
    assert set(POLISHED_GRANTED) == {"native_sounds", "explode_mode", "rival_team_swap"}
    for option, why in POLISHED_GRANTED.items():
        assert "polished" in why.lower() and len(why) > 40, option



def _manager_dicts() -> list[tuple[str, dict]]:
    """Every module-level dict in server.manager that could carry a family row."""
    return [
        (name, value)
        for name, value in sorted(vars(manager).items())
        if isinstance(value, dict) and value
    ]


def test_manager_polished_randomize_is_offered() -> None:
    """Guard (flipped 2026-10-04): the Manager offers Randomize for Polished once the fork jar with the
    PolishedCrystalRomHandler is pinned (patches 0016-0021, data/upr_jars.json).

    Located by importing the module and scanning its tables for the old refusal text rather
    than naming the owning table.

    RED CONTROL: restore the gen2_polished "turn Randomize off" row in server/manager.py's
    NON_RANDOMIZABLE_GAMES.
    """
    hits = [
        (name, value[POLISHED_FAMILY])
        for name, value in _manager_dicts()
        if isinstance(value.get(POLISHED_FAMILY), str)
        and "Randomize off" in value[POLISHED_FAMILY]
    ]
    assert not hits, f"a manager table still refuses Randomize for gen2_polished: {hits}"
    assert POLISHED_FAMILY in manager.new_run_form()["randomizer_games"]


def test_manager_polished_family_is_still_listed_with_its_refusals() -> None:
    """Guard: the family stays *listed* so the refusals above remain reachable.

    Blocker flipped by: nothing. If the family key vanishes, Polished disappears instead
    of refusing - a silent regression the refusal tests above cannot catch.

    RED CONTROL: remove "gen2_polished" from GAME_FAMILY in server/manager.py, or drop
    the gen2_polished row from the family table there.
    """
    assert manager.GAME_FAMILY[POLISHED_FAMILY] == POLISHED_FAMILY
    anywhere = False
    for name, value in vars(manager).items():
        if isinstance(value, dict):
            anywhere = anywhere or POLISHED_FAMILY in value
        elif isinstance(value, (list, tuple)):
            anywhere = anywhere or any(
                POLISHED_FAMILY in row for row in value if isinstance(row, (list, tuple))
            )
    assert anywhere, "gen2_polished no longer appears in any manager table"


# --------------------------------------------------------------------------- 3. verifier


def test_release_verifier_has_no_polished_title() -> None:
    """Guard against a naive append of Polished to the release verifier's TITLES.

    Blocker flipped by: an owner ruling on how a *solo* title is verified — Polished has
    no vanilla pairing, so appending it to TITLES would drag DUO_PAIRS and
    POISON_SETUP_RECIPE into expecting a partner it cannot have
    (docs/polished/RELEASE.md §3 / F2).

    RED CONTROL: add "polished_crystal" to `TITLES` in tools/verify_gen2_release.py:61.
    """
    sys.path.insert(0, str(REPO / "tools"))
    import verify_gen2_release as verifier  # noqa: PLC0415

    assert "polished" not in " ".join(verifier.TITLES).lower()
    assert "polished_crystal" not in verifier.TITLES
    assert verifier.TITLES == ("crystal", "gold", "silver")


def test_release_verifier_duo_pairs_need_no_polished_partner() -> None:
    """Guard: the duo-pair table stays vanilla-only for the same reason.

    Blocker flipped by: the same solo-title ruling as the TITLES guard above.

    RED CONTROL: append `("polished_crystal", "polished_crystal")` to DUO_PAIRS in
    tools/verify_gen2_release.py:285.
    """
    sys.path.insert(0, str(REPO / "tools"))
    import verify_gen2_release as verifier  # noqa: PLC0415

    for initiator, partner in verifier.DUO_PAIRS:
        assert "polished" not in initiator.lower() and "polished" not in partner.lower()


# --------------------------------------------------------------------------- 4. randomizer


def test_polished_randomizer_is_enabled() -> None:
    """Guard (flipped 2026-10-04): the flag is on because the fork jar with a working
    PolishedCrystalRomHandler (patches 0016-0021) is pinned in data/upr_jars.json.

    RED CONTROL: set `POLISHED_RANDOMIZER_ENABLED = False` in server/upr_pipeline.py.
    """
    assert upr_pipeline.POLISHED_RANDOMIZER_ENABLED is True


def test_polished_randomizer_flag_gates_the_manager_paths() -> None:
    """Guard: the flag must actually be consulted, not merely declared.

    Blocker flipped by: the same jar pin + handler as above.

    RED CONTROL: delete the `POLISHED_RANDOMIZER_ENABLED` check from the Polished
    branch of server/upr_pipeline.py so the flag is defined but unused.
    """
    source = (REPO / "server" / "upr_pipeline.py").read_text(encoding="utf-8")
    uses = source.count("POLISHED_RANDOMIZER_ENABLED")
    assert uses >= 2, (
        "POLISHED_RANDOMIZER_ENABLED is declared but never read; the gate would be "
        "decorative"
    )