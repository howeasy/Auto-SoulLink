"""Render the real OBS templates and pureRGB adapter, without a server or network.

The 96px sprite canvas below models the upstream 56px cell plus 20px padding.
It makes the crop observable without fetching mutable remote artwork. Browser
geometry is MODEL evidence, not an OBS/emulator qualification receipt.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest
from jinja2 import Environment, FileSystemLoader

from server.adapters.gen1_purergb import Gen1PureRGBAdapter
from server.board import hp_class, hp_pct

REPO = Path(__file__).resolve().parents[2]


def _browser() -> str:
    configured = os.environ.get("SLINK_TEST_CHROMIUM")
    if configured:
        return configured
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        executable = shutil.which(name)
        if executable:
            return executable
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    candidates = sorted(local.glob("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"))
    candidates += sorted(local.glob("chromium-*/chrome-win64/chrome.exe"))
    if candidates:
        return str(candidates[0])
    pytest.skip("Chromium absent; set SLINK_TEST_CHROMIUM to run the rendered OBS gate")


def _dump_dom(browser: str, folder: Path, page_path: Path):
    """Run headless Chromium; a hung browser is an environment fault, so skip with a name.

    Modern Chromium's new headless mode can ignore --virtual-time-budget and never
    exit on a display-less runner, so the second attempt dumps after a plain timeout.
    """
    base = [browser, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
            "--disable-background-networking", f"--user-data-dir={folder / 'profile'}", "--dump-dom"]
    attempts = (base[:-1] + ["--virtual-time-budget=2000", "--dump-dom"],
                base[:-1] + ["--no-first-run", "--timeout=3000", "--dump-dom"])
    for argv in attempts:
        proc = subprocess.Popen(argv + [page_path.as_uri()], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                start_new_session=os.name != "nt")
        try:
            out, err = proc.communicate(timeout=25)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                proc.kill()
            else:
                os.killpg(proc.pid, 9)
            proc.communicate()
            continue
        return subprocess.CompletedProcess(argv, proc.returncode, out, err)
    pytest.skip(f"{browser} hung headless with and without virtual time (display-less runner)")


@pytest.fixture(scope="module")
def rendered_sizes(tmp_path_factory):
    adapter = Gen1PureRGBAdapter(artifact_kind="rand_overlay")
    species = next(ident for ident, entry in adapter._species.items() if entry["dex"] == 25)
    sprite = adapter.sprite_html(species)
    # A deterministic padded canvas; keep the actual adapter's HTML and styles.
    canvas = ('<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96">'
              '<rect x="20" y="20" width="56" height="56" fill="red"/></svg>')
    sprite = re.sub(r'src="[^"]*"', f'src="data:image/svg+xml,{quote(canvas)}"', sprite)
    sprite = sprite.replace('loading="lazy"', 'loading="eager"')
    env = Environment(loader=FileSystemLoader(REPO / "server" / "templates"), autoescape=True)
    env.globals.update(hp_class=hp_class, hp_pct=hp_pct)
    mon = {"species_name": "Pikachu", "nickname": "Pika", "sprite_html": sprite,
           "level": 10, "hp": 30, "maxHP": 30, "status_cond": 0, "stat_stages": [], "in_party": False}
    base = {"theme": "default", "player_id": "a", "connected": True, "trainer_name": "A",
            "fragment_url": "", "layout_class": "", "mons": [mon]}
    pair = {"a": mon, "b": mon, "area_display": "Pallet Town"}
    css = (REPO / "server" / "static" / "slink.css").read_text(encoding="utf-8")
    board_css = (REPO / "server" / "static" / "board.css").read_text(encoding="utf-8")
    # Load its real macros without evaluating the unrelated run page's context.
    board_source = (REPO / "server" / "templates" / "_board.html").read_text(encoding="utf-8")
    board_macros = env.from_string(board_source.split('<div id="mk-announcer"')[0]).module
    frames = []
    for width, height in ((320, 240), (1920, 1080)):
        scenes = {
            "party": env.get_template("stream/party.html").render(**base),
            "focus": env.get_template("stream/focus.html").render(
                **{**base, "layout_class": "ov-focus"},
                active_mons=[{"mon": mon, "moves": []}], is_doubles=False),
            "doubles": env.get_template("stream/focus.html").render(
                **{**base, "layout_class": "ov-focus"},
                active_mons=[{"mon": mon, "moves": []}] * 2, is_doubles=True),
            "boxed": env.get_template("stream/boxed_links.html").render(**base, pairs=[pair]),
            "dashboard": '<body>' + str(env.get_template("_macros.html").module.mon_card(mon)) + '</body>',
            "board": '<body class="board"><style>' + board_css + '</style>' +
                     str(board_macros.combatant(mon, "a")) + '</body>',
            "encounter": '<body class="stream"><div class="et-entry">' +
                         sprite.replace('class="mon-sprite"', 'class="enc-sprite"') + '</div></body>',
        }
        for scene, page in scenes.items():
            # Do not execute polling or fetch fonts/themes in this isolated render.
            page = re.sub(r"<script\b[^>]*>.*?</script>", "", page, flags=re.S)
            page = re.sub(r"<link\b[^>]*>", "", page)
            page = '<style>' + css + '</style>' + page
            key = f"{scene}-{width}"
            frames.append(f'<iframe id="{key}" width="{width}" height="{height}" '
                          f'style="border:0" srcdoc="{html.escape(page, quote=True)}"></iframe>')
    probe = """<script>
    window.onload = () => {
      const result = {};
      for (const frame of document.querySelectorAll('iframe')) {
        const doc = frame.contentDocument;
        const img = doc.querySelector('img.mon-sprite, img.enc-sprite');
        const box = img.parentElement;
        const ir = img.getBoundingClientRect(), br = box.getBoundingClientRect();
        const cs = frame.contentWindow.getComputedStyle(img);
        result[frame.id] = {box: [br.width, br.height], image: [ir.width, ir.height],
          offset: [ir.x-br.x, ir.y-br.y], natural: [img.naturalWidth, img.naturalHeight],
          rendering: cs.imageRendering, overflow: frame.contentWindow.getComputedStyle(box).overflow};
      }
      const pre = document.createElement('pre'); pre.id = 'measurements';
      pre.textContent = JSON.stringify(result); document.body.append(pre);
    };
    </script>"""
    folder = tmp_path_factory.mktemp("obs-sprite-render")
    page_path = folder / "render.html"
    page_path.write_text('<!doctype html>' + ''.join(frames) + probe, encoding="utf-8")
    run = _dump_dom(_browser(), folder, page_path)
    assert run.returncode == 0, run.stderr[-2000:]
    match = re.search(r'<pre id="measurements">(.*?)</pre>', run.stdout, re.S)
    assert match, "Browser did not return computed sprite geometry"
    result = json.loads(html.unescape(match[1]))
    print(json.dumps(result, sort_keys=True))
    return result


@pytest.mark.parametrize("scene,width,expected", [
    ("party", 320, 38), ("party", 1920, 58),
    ("focus", 320, 54), ("focus", 1920, 80),
    ("doubles", 320, 38), ("doubles", 1920, 52),
    ("boxed", 320, 28), ("boxed", 1920, 44),
    ("dashboard", 320, 40), ("dashboard", 1920, 40),
    ("board", 320, 48.4), ("board", 1920, 48.4),
    ("encounter", 320, 40), ("encounter", 1920, 40),
])
def test_sprite_cell_fills_the_context_size(rendered_sizes, scene, width, expected):
    sizes = rendered_sizes[f"{scene}-{width}"]
    assert sizes["natural"] == [96, 96]
    assert sizes["box"] == pytest.approx([expected, expected], abs=.1), sizes
    # A full 56px sprite cell must fill the box without squashing or clipping.
    assert sizes["image"] == pytest.approx([expected * 96 / 56] * 2, abs=.1), sizes
    assert sizes["offset"] == pytest.approx([-expected * 20 / 56] * 2, abs=.1), sizes
    assert sizes["overflow"] == "hidden"
    assert sizes["rendering"] in ("pixelated", "crisp-edges")


def test_pure_forms_keep_their_existing_base_sprite_and_missing_art_policy():
    adapter = Gen1PureRGBAdapter()
    for ident, entry in adapter._species.items():
        if entry["classification"] == "form" and entry.get("base_species") is not None:
            assert adapter.sprite_html(ident) == adapter.sprite_html(entry["base_species"])
        elif entry["classification"] != "ordinary":
            assert adapter.sprite_html(ident) == ""
