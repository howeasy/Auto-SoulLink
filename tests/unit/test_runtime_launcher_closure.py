"""Composed services retain a bounded and fully checked module closure."""

import pytest

from server.runtime_launcher import MAX_CLIENT_FILES, file_bundle, render_launcher


def test_composed_module_closure_keeps_every_hash_and_the_upper_bound(tmp_path):
    names = ["lua/slink.lua"] + [
        f"lua/service_{index}.lua" for index in range(MAX_CLIENT_FILES - 1)
    ]
    (tmp_path / "lua").mkdir()
    for name in names:
        (tmp_path / name).write_text("return {}\n")
    files = file_bundle(tmp_path, names)
    assert len(files) == MAX_CLIENT_FILES
    configuration = {"run_id": "a" * 32, "player": "a", "files": files}
    text = render_launcher(configuration, host="localhost", port=1234)
    for row in files:
        assert row["path"] in text and row["sha256"] in text
    with pytest.raises(ValueError, match="bounded"):
        file_bundle(tmp_path, names + ["lua/one_more.lua"])
    with pytest.raises(ValueError, match="bounded"):
        render_launcher({**configuration, "files": files + [files[0]]}, host="localhost", port=1234)
    with pytest.raises(ValueError, match="unique"):
        file_bundle(tmp_path, [names[0], names[0]])
