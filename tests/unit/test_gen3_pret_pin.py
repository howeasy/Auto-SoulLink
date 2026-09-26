"""gen3_pret: a pret clone found by walking up must be at the pin, or the test fails."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen3_pret  # noqa: E402


def test_absent_clone_skips(tmp_path):
    with pytest.raises(pytest.skip.Exception):
        gen3_pret.require(tmp_path / "nope")


def test_clone_at_the_pin_is_returned(tmp_path):
    assert gen3_pret.require(tmp_path, rev=lambda p: gen3_pret.PIN) == tmp_path


def test_clone_at_another_commit_fails(tmp_path):
    with pytest.raises(pytest.fail.Exception, match="not the pinned"):
        gen3_pret.require(tmp_path, rev=lambda p: "0" * 40)


def test_env_override_wins_over_the_walk_up(tmp_path):
    assert gen3_pret.find(env={"SLINK_PRET_FIRERED_SRC": str(tmp_path)}) == tmp_path


def test_gen1s_pokered_variable_is_not_read(tmp_path):
    """SLINK_PRET_SRC is Gen 1's pret/pokered path (tools/gen1_foundation.py:11); setting it the
    documented way must not steer the FireRed lookup (Gen1-Collab2 reproduced 8 failures)."""
    assert gen3_pret.find(root=tmp_path, env={"SLINK_PRET_SRC": "E:/elsewhere/pokered"}) == tmp_path / gen3_pret.REL
