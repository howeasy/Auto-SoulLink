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


def test_launcher_embeds_the_player_resume_contract_only_when_the_run_record_has_it(tmp_path):
    import json

    (tmp_path / "lua").mkdir()
    (tmp_path / "lua/slink.lua").write_text("return {}\n")
    configuration = {"run_id": "a" * 32, "player": "b", "files": file_bundle(tmp_path, ["lua/slink.lua"])}
    record = {"from_run": "c" * 32, "required": {"a": {"digest": "1" * 64, "projection": "cartram-0498-8000-v1"},
                                                  "b": {"digest": "2" * 64, "projection": "cartram-0498-8000-v1", "frame": 9}}}

    def embedded(text):
        line = next(line for line in text.splitlines() if line.startswith("SLINK_RUNTIME_LAUNCH_JSON="))
        return json.loads(json.loads(line.split("=", 1)[1]) if line.split("=", 1)[1].startswith('"') else "{}")

    plain = render_launcher(configuration, host="localhost", port=1234)
    assert "resume" not in embedded(plain) and render_launcher(configuration, host="localhost", port=1234, resume=None) == plain
    resumed = embedded(render_launcher(configuration, host="localhost", port=1234, resume=record))
    assert resumed["resume"] == {"from_run": "c" * 32, "required_digest": "2" * 64, "projection": "cartram-0498-8000-v1"}
    for broken in ({**record, "required": {"a": record["required"]["a"]}}, {**record, "from_run": ""},
                   {**record, "required": {"b": {"digest": "xyz", "projection": "cartram-0498-8000-v1"}}}):
        with pytest.raises(ValueError, match="resume"):
            render_launcher(configuration, host="localhost", port=1234, resume=broken)
