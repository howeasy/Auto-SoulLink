"""TG-MULTI: battle-script opponents inherit their owning map, never text/partner arguments."""
from pathlib import Path

import pytest

from tools.gen_gen3_trainers import trainer_maps


@pytest.mark.parametrize("shared", (False, True))
@pytest.mark.parametrize("macro,args,opponents", (
    ("multi_2_vs_2", "TRAINER_MAXIE, TRAINER_LOSE_TEXT_A, TRAINER_TABITHA, TRAINER_LOSE_TEXT_B, TRAINER_PARTNER",
     {"TRAINER_MAXIE", "TRAINER_TABITHA"}),
    ("multi_fixed_2_vs_2", "TRAINER_MAXIE, TRAINER_LOSE_TEXT_A, TRAINER_TABITHA, TRAINER_LOSE_TEXT_B, TRAINER_PARTNER",
     {"TRAINER_MAXIE", "TRAINER_TABITHA"}),
    ("multi_2_vs_1", "TRAINER_MAXIE, TRAINER_LOSE_TEXT_A, TRAINER_PARTNER", {"TRAINER_MAXIE"}),
    ("multi_fixed_2_vs_1", "TRAINER_MAXIE, TRAINER_LOSE_TEXT_A, TRAINER_PARTNER", {"TRAINER_MAXIE"}),
    ("setmultitrainerbattle", "TRAINER_MAXIE, TRAINER_LOSE_TEXT_A, TRAINER_TABITHA, TRAINER_LOSE_TEXT_B, TRAINER_PARTNER",
     {"TRAINER_MAXIE", "TRAINER_TABITHA"}),
))
def test_multi_battle_maps_only_opponent_arguments(tmp_path: Path, shared, macro, args, opponents):
    # Argument roles are from expansion e8bd1cd7 asm/macros/battle_frontier/battle_tower.inc
    # :121-160 and asm/macros/event.inc:2674-2682. Text/partner names deliberately also look
    # like TRAINER_*: scanning every constant on the line would incorrectly add them.
    directory = tmp_path / ("data/scripts" if shared else "data/maps/SpaceCenter")
    directory.mkdir(parents=True)
    (directory / "scripts.inc").write_text(f"SpaceCenterBattle::\n\t{macro} {args} @ TRAINER_COMMENT\n")
    maps = {"SpaceCenter": {"id": "MAP_SPACE_CENTER", "object_events": [{"script": "SpaceCenterBattle"}]}}
    assert trainer_maps(tmp_path, maps) == {trainer: {"MAP_SPACE_CENTER"} for trainer in opponents}
