import json

import pytest
from PIL import Image

from tools.rr.frame_recording import build, collect


def result(tmp_path, *, frames=(10, 11), colors=("red", "blue"), size=(240, 160), mode="RGB"):
    shots = []
    for i, (frame, color) in enumerate(zip(frames, colors, strict=True)):
        path = tmp_path / (str(i) + ".png")
        Image.new(mode, size, color).save(path)
        shots.append({"frame": frame, "path": str(path)})
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"evidence": {"runtime": {"screenshots": shots}}}))
    return path


def test_distinct_frames_remain_in_video_even_when_pixels_repeat(tmp_path):
    path = result(tmp_path, colors=("red", "red"))
    _, frames, unique = collect(path, 10, 11)
    assert len(frames) == 2 and len(unique) == 1


@pytest.mark.parametrize("fault", ["missing_png", "missing_frame", "conflicting_duplicate", "dimensions", "transparent"])
def test_missing_or_ambiguous_visual_evidence_fails(tmp_path, fault):
    if fault == "conflicting_duplicate":
        path = result(tmp_path, frames=(10, 10))
    elif fault == "dimensions":
        path = result(tmp_path, size=(120, 80))
    elif fault == "transparent":
        path = result(tmp_path, mode="RGBA", colors=((255, 0, 0, 0), (0, 0, 255, 255)))
    else:
        path = result(tmp_path, frames=(10, 12) if fault == "missing_frame" else (10, 11))
        if fault == "missing_png":
            (tmp_path / "0.png").unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        collect(path, 10, 11)


def test_existing_output_refuses_before_opening_inputs(tmp_path):
    with pytest.raises(ValueError, match="output exists"):
        build(tmp_path / "missing.json", tmp_path / "missing.exe", tmp_path, 10, 11)
