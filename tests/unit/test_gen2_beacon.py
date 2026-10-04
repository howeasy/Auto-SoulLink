"""R6 overlay beacon: data/games/gen2_<title>/overlay/beacon.json (tools/gen_gen2_beacon.py) is the digest
lua/gen2/entry.lua re-hashes for a rand_overlay cartridge. It must cover every overlay-changed byte (the companion
pins included), name the binding's overlay, and stay current; --check goes red on any drift. Clean builds absent
skip; a clean build at the wrong sha1 fails (tests/unit/test_gen2_rand_admission.py `_clean`).
"""
import json
import shutil

import pytest

from tests.unit.test_gen2_rand_admission import COMPANION_PINS, ROOT, _binding, _clean
from tools import gen_gen2_beacon as gen

TITLES = ("crystal", "gold", "silver")


def _beacon(title):
    return json.loads((ROOT / gen.BEACON.format(title=title)).read_text(encoding="utf-8"))


def _pool_args():
    args = []
    for title in TITLES:
        _clean(title)                                                 # skip when absent, fail when wrong
        source = "pokecrystal" if title == "crystal" else "pokegold"
        artifact = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]["artifact"]
        args += ["--rom", str(ROOT / f".cache/gen2-build/{source}/{artifact}.gbc")]
    return args


@pytest.mark.parametrize("title", TITLES)
def test_the_beacon_is_pinned_to_the_binding_and_covers_the_companion_pins(title):
    beacon, binding = _beacon(title), _binding(title)
    assert beacon["schema"] == gen.SCHEMA and beacon["title"] == title
    assert beacon["source"]["overlay_sha1"] == binding["rom_sha1"]
    assert beacon["source"]["clean_sha1"] == binding["base_sha1"]
    assert beacon["source"]["ups_sha256"] == binding["ups_sha256"]
    spans = [(s["offset"], s["offset"] + s["length"]) for s in beacon["spans"]]
    assert all(a < b for a, b in spans) and all(b < c for (_, b), (c, _) in zip(spans, spans[1:], strict=False))
    assert beacon["count"] == len(spans) and beacon["total"] == sum(b - a for a, b in spans)
    covered = {i for a, b in spans for i in range(a, b)}
    for edit in binding["builder_substitutions"]:
        offset = COMPANION_PINS[title][edit["symbol"]]
        changed = [offset + i for i, (x, y) in enumerate(zip(bytes.fromhex(edit["before_hex"]),
                                                             bytes.fromhex(edit["after_hex"]), strict=True)) if x != y]
        assert changed and set(changed) <= covered, (title, edit["symbol"])


def test_the_committed_beacons_are_current():
    assert gen.main(["--check", *_pool_args()]) == 0


def test_check_goes_red_on_a_modified_span(tmp_path):
    args = _pool_args()
    for title in TITLES:
        out = tmp_path / gen.BEACON.format(title=title)
        out.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / gen.BEACON.format(title=title), out)
    assert gen.main(["--check", *args], out_root=tmp_path) == 0
    path = tmp_path / gen.BEACON.format(title="gold")
    doc = json.loads(path.read_text())
    doc["spans"][3]["length"] += 1
    path.write_text(gen.render(doc))
    assert gen.main(["--check", *args], out_root=tmp_path) == 1


def test_the_generator_refuses_a_clean_build_off_its_pin():
    image = bytearray(_clean("crystal"))
    image[0x200] ^= 0xFF
    with pytest.raises(SystemExit, match="not the pinned"):
        gen.build("crystal", bytes(image))
