"""Create lossless review artifacts from native-gate screenshots, never a visual PASS."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def collect(result: Path, first: int, last: int):
    if type(first) is not int or type(last) is not int or first < 0 or last < first or last - first >= 3600:
        raise ValueError("select a bounded interval of 1..3600 frames")
    raw = result.read_bytes()
    document = json.loads(raw)
    frames, unique = {}, {}
    for shot in document["evidence"]["runtime"]["screenshots"]:
        frame = shot["frame"]
        if type(frame) is not int:
            raise ValueError("invalid screenshot frame")
        if frame < first or frame > last:
            continue
        path = Path(shot["path"]).resolve(strict=True)
        if not path.is_relative_to(result.resolve().parent):
            raise ValueError("screenshot outside its result directory")
        with Image.open(path) as image:
            if image.format != "PNG" or image.size != (240, 160):
                raise ValueError("unexpected framebuffer format or dimensions")
            if image.convert("RGBA").getchannel("A").getextrema() != (255, 255):
                raise ValueError("transparent framebuffer cannot be normalized silently")
            rgb = image.convert("RGB").tobytes()
        if frame in frames and frames[frame]["rgb_sha256"] != sha(rgb):
            raise ValueError("different screenshots for the same frame")
        record = {"frame": frame, "path": str(path), "png_sha256": sha(path.read_bytes()),
                  "rgb_sha256": sha(rgb), "rgb": rgb}
        frames[frame] = record
        unique.setdefault(record["rgb_sha256"], record)
    if first > last or set(frames) != set(range(first, last + 1)):
        raise ValueError("missing frames in selected recording interval")
    return sha(raw), [frames[n] for n in range(first, last + 1)], sorted(unique.values(), key=lambda x: x["frame"])


def build(result: Path, ffmpeg: Path, output: Path, first: int, last: int) -> Path:
    if output.exists():
        raise ValueError("output exists; preserve previous review artifacts")
    result_hash, frames, unique = collect(result, first, last)
    source = Path(__file__).read_bytes()
    exe_hash = sha(ffmpeg.read_bytes())
    version = subprocess.run([str(ffmpeg), "-version"], capture_output=True, check=True, text=True).stdout.splitlines()[0]
    output.mkdir(parents=True, exist_ok=False)
    (output / "renderer_source.py").write_bytes(source)
    video = output / "recording.mp4"
    raw = b"".join(frame["rgb"] for frame in frames)
    command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-n", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", "240x160", "-framerate", "262144/4389", "-i", "pipe:0", "-an", "-c:v", "libx264rgb",
               "-qp", "0", "-pix_fmt", "rgb24", str(video)]
    subprocess.run(command, input=raw, capture_output=True, check=True, timeout=60)
    decoded = subprocess.run([str(ffmpeg), "-v", "error", "-i", str(video), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                             capture_output=True, check=True, timeout=60).stdout
    if decoded != raw:
        raise ValueError("decoded video differs from source framebuffers")
    pages = []
    for start in range(0, len(unique), 48):
        selected = unique[start:start + 48]
        sheet = Image.new("RGB", (1440, ((len(selected) + 5) // 6) * 176), "#111111")
        draw = ImageDraw.Draw(sheet)
        for index, frame in enumerate(selected):
            x, y = index % 6 * 240, index // 6 * 176
            draw.text((x + 3, y + 1), "Frame " + str(frame["frame"]), fill="white")
            sheet.paste(Image.frombytes("RGB", (240, 160), frame["rgb"]), (x, y + 16))
        path = output / f"unique_{len(pages) + 1:02d}.png"
        sheet.save(path)
        pages.append({"path": str(path.resolve()), "sha256": sha(path.read_bytes()), "frames": [x["frame"] for x in selected]})
    for frame in frames:
        if sha(Path(frame["path"]).read_bytes()) != frame["png_sha256"]:
            raise ValueError("source screenshot changed during encoding")
    if sha(result.read_bytes()) != result_hash or sha(ffmpeg.read_bytes()) != exe_hash or Path(__file__).read_bytes() != source:
        raise ValueError("recording input changed")
    manifest = {"schema": "slink-framebuffer-review-v1", "result_sha256": result_hash,
                "source_sha256": sha(source), "first_frame": first, "last_frame": last,
                "frame_count": len(frames), "unique_images": len(unique), "visual_review": "pending",
                "release_ready": False, "decoded_rgb_matches_all_pngs": True, "ffmpeg_sha256": exe_hash,
                "ffmpeg_version": version, "command": command, "video_sha256": sha(video.read_bytes()),
                "video": str(video.resolve()), "pages": pages,
                "frames": [{k: v for k, v in f.items() if k != "rgb"} for f in frames]}
    path = output / "recording.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("result", "ffmpeg", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    for name in ("first", "last"):
        p.add_argument("--" + name, type=int, required=True)
    print(build(**vars(p.parse_args())))
