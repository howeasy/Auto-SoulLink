import json

import pytest

from tools.polished_live.overlay_pin import overlay_sha1


def test_pin_follows_provenance_without_a_process_cache(tmp_path):
    path = tmp_path / "data/polished/overlay_provenance.json"
    path.parent.mkdir(parents=True)
    for value in ("1" * 40, "2" * 40):
        path.write_text(json.dumps({"output": {"sha1": value}}))
        assert overlay_sha1(tmp_path) == value


@pytest.mark.parametrize("value", [None, "bad", "A" * 40], ids=["null", "short", "uppercase"])
def test_bad_pin_refuses(tmp_path, value):
    path = tmp_path / "data/polished/overlay_provenance.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"output": {"sha1": value}}))
    with pytest.raises(ValueError):
        overlay_sha1(tmp_path)
