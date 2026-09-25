"""The overlay launcher's URL builder (stream_index.html previewUrl), run under node.

With no ?filter= the server shows only the default-on event types, so a launcher with
every pill on has to say `filter=all`."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "server" / "templates" / "stream_index.html"


def _preview_url(active: list[str], all_filters: list[str]) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    method = re.search(r"^    previewUrl\(\) \{.*?^    \},", SRC.read_text(encoding="utf-8"),
                       re.S | re.M).group(0)
    js = ("var o = {" + method + "};"
          "o.current = {slug: 'killfeed', layouts: [''], event_filters: true};"
          "o.params = {theme: '', layout: '', speed: '1', pause: '2'};"
          f"o.activeFilters = new Set({json.dumps(active)}); o.allFilters = {json.dumps(all_filters)};"
          "console.log(o.previewUrl());")
    return subprocess.run([node, "-e", js], capture_output=True, text=True, check=True,
                          timeout=30).stdout.strip()


def test_every_pill_on_asks_for_all():
    assert _preview_url(["faint", "catch", "box"], ["faint", "catch", "box"]) == "/stream/killfeed?filter=all"


def test_a_subset_is_listed():
    assert _preview_url(["faint", "catch"], ["faint", "catch", "box"]) == "/stream/killfeed?filter=faint,catch"
