import json

import pytest

from tests.rr.runtime.cases import CASES


@pytest.mark.parametrize("name", list(CASES))
def test_rr_correct_behavior(rr_repo, name):
    result = CASES[name](rr_repo)
    assert result.passed, json.dumps(result.document(), indent=2, ensure_ascii=False)
