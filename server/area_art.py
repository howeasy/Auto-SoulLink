"""The area's art behind a player card: `GET /area-art/{name}` on both servers.

A curated set, painted only, no maps and no screenshots: the owner's research index of
official scenic art per Kanto location (Let's Go art book paintings, Hitoshi Ariga's
ukiyo-e prints, Pokémon Masters EX's 512×512 painted backgrounds, TCG Pocket illustrations,
the Find Pokémon picture book) with Masters' generic scenes -- a forest path, a crystal
cave, a beach, a graveyard -- for the places nothing depicts. An interior with nothing of
its own takes its town's picture. Each picture is fetched once, the way the board's sprites
come from PokeAPI at view time, into `.cache/area-art/` (gitignored), never the repository.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import aiohttp
from aiohttp import web

ART_DIR = Path(__file__).resolve().parents[1] / ".cache" / "area-art"
API = "https://archives.bulbagarden.net/w/api.php"
UA = "SLink/1.0 (+https://github.com/howeasy/Auto-SoulLink)"   # MediaWiki wants one

# A source is a Bulbagarden Archives file title ("File:...") or a direct URL.
_M = "File:{} Mindscape.png"                                  # Pokémon Masters EX backgrounds
ART: dict[str, str] = {
    # towns
    "Pallet Town": _M.format("Elaine"),                       # the player's house
    "Viridian City": _M.format("Blue"),                       # the Gym, on its lawn
    "Pewter City": _M.format("Brock"),                        # the Gym: nothing shows the streets
    "Cerulean City": _M.format("Misty"),
    "Vermilion City": "https://cdn.artofpkm.com/wxbq9yhszoxju8qf09s8j72a7jzr",   # Ariga, Port of Vermilion
    "Lavender Town": "File:HaunterGeneticApex121_artwork.png",                  # the Tower behind Haunter
    "Celadon City": _M.format("Erika"),
    "Fuchsia City": _M.format("Koga"),
    "Saffron City": _M.format("Sabrina"),
    "Cinnabar Island": _M.format("Blaine"),
    "Indigo Plateau": _M.format("Chase"),                     # the League's entrance
    # the outdoors
    "Viridian Forest": "https://cdn.artofpkm.com/eswibwfxcrd73bu1r9up5523pm5b",  # Let's Go art book
    "Diglett's Cave": "https://cdn.artofpkm.com/9i9j7fiflfktwdo1uxztyy9uuelz",   # Let's Go art book
    "Route 11": "File:DiglettGeneticApex238_artwork.png",     # the cave's Route 11 mouth
    "Route 12": "https://cdn.artofpkm.com/nks3xnijyro7njmcgibg6wiee1nl",         # Ariga, Silence Bridge
    "Power Plant": "File:ZapdosexGeneticApex276_artwork.png",
    "S.S. Anne": "File:GyaradosGeneticApex233_artwork.png",
    "Seafoam Islands": "File:ArticunoexGeneticApex275_artwork.png",
    "Pokémon Mansion": "File:GrimerGeneticApex174_artwork.png",
    "Pokémon Tower": _M.format("Ghost"),                      # a graveyard under the moon
    "Safari Zone": "https://cdn.artofpkm.com/sinytgt3uvk4fw4cgk1km3vks4oc",      # Find Pokémon picture book
    "Rocket Hideout": _M.format("Giovanni"),
    # the League's rooms, the gyms, the lab
    "Lorelei's Room": _M.format("Lorelei"), "Bruno's Room": _M.format("Bruno"),
    "Agatha's Room": _M.format("Agatha"), "Lance's Room": _M.format("Lance"),
    "Champion's Room": _M.format("Blue Champion"), "Hall Of Fame": _M.format("Red Champion"),
    "Viridian Gym": _M.format("Blue"), "Pewter Gym": _M.format("Brock"), "Cerulean Gym": _M.format("Misty"),
    "Vermilion Gym": _M.format("Lt Surge"), "Celadon Gym": _M.format("Erika"), "Fuchsia Gym": _M.format("Koga"),
    "Saffron Gym": _M.format("Sabrina"), "Cinnabar Gym": _M.format("Blaine"), "Fighting Dojo": _M.format("Bruno"),
    "Oak's Lab": _M.format("Professor Oak"),
}
# nothing depicts these: Masters' generic scenes, by the kind of place
GENERIC = {
    "sea": _M.format("Summer 2024"), "cave": _M.format("Silver"), "rocky": _M.format("Ground"),
    "route": _M.format("Fairy"),
}
KIND = [
    (re.compile(r"^Route (19|20|21)$"), "sea"),
    (re.compile(r"^Route (3|4|9|10)$"), "rocky"),
    (re.compile(r"^Route \d+$"), "route"),
    (re.compile(r"^(Mt\. Moon|Rock Tunnel|Cerulean Cave|Victory Road|Underground Path)"), "cave"),
]
TOWNS = tuple(t for t in ART if t.endswith((" Town", " City", " Island", " Plateau")))
_FLOOR = re.compile(r"\s+(B?\d+F|Roof|Basement)$", re.I)
_LOCK = asyncio.Lock()   # ponytail: one lock, fetches are once-per-area-ever


def source(name: str) -> str | None:
    """Where an area's picture comes from, or None: its own entry, the place it is part of
    ('Diglett's Cave Route 2', 'Safari Zone East Rest House'), the kind of place it is, the
    town an interior is in ('Pewter Museum'). The client spells Pokémon both ways."""
    name = _FLOOR.sub("", name.strip().replace("Pokemon", "Pokémon"))
    if name in ART:
        return ART[name]
    words = name.split(" ")
    for n in range(len(words) - 1, 0, -1):
        if " ".join(words[:n]) in ART:
            return ART[" ".join(words[:n])]
    for pat, kind in KIND:
        if pat.match(name):
            return GENERIC[kind]
    for town in TOWNS:
        if town.split(" ", 1)[0] == words[0]:
            return ART[town]
    return None


def slug(src: str) -> str:
    """The cache file's stem for a source: the title or the URL's last segment, extension off."""
    stem = re.sub(r"\.(png|jpe?g|webp)$", "", src.removeprefix("File:").rsplit("/", 1)[-1], flags=re.I)
    return re.sub(r"[^\w-]+", "_", stem).strip("_").lower()


async def fetch(src: str) -> Path:
    """The picture into ART_DIR (raises on network trouble); a title is resolved first."""
    async with aiohttp.ClientSession(headers={"User-Agent": UA},
                                     timeout=aiohttp.ClientTimeout(total=20)) as s:
        url = src
        if src.startswith("File:"):
            async with s.get(API, params={"format": "json", "action": "query", "titles": src,
                                          "prop": "imageinfo", "iiprop": "url"}) as r:
                pages = (await r.json()).get("query", {}).get("pages", {})
            url = next(iter(pages.values()), {}).get("imageinfo", [{}])[0].get("url")
            if not url:
                raise aiohttp.ClientError(f"no such file on the Archives: {src}")
        async with s.get(url) as r:
            r.raise_for_status()
            data = await r.read()
            ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(r.content_type, "")
    path = ART_DIR / (slug(src) + ext)
    path.write_bytes(data)
    return path


async def resolve(name: str) -> Path | None:
    """The file for an area's picture, fetched once; None when nothing depicts it."""
    src = source(name)
    if src is None:
        return None
    ART_DIR.mkdir(parents=True, exist_ok=True)
    async with _LOCK:
        hit = next(iter(sorted(ART_DIR.glob(slug(src) + ".*"))), None)
        if hit is None:
            try:
                hit = await fetch(src)
            except (aiohttp.ClientError, TimeoutError, OSError):
                return None          # transient: ask again next time
    return hit


async def handle_area_art(request: web.Request) -> web.StreamResponse:
    path = await resolve(request.match_info["name"])
    if path is None:
        raise web.HTTPNotFound()
    # FileResponse guesses the type from Windows' registry, which does not know webp
    return web.FileResponse(path, headers={"Cache-Control": "max-age=86400",
                                           **({"Content-Type": "image/webp"} if path.suffix == ".webp" else {})})


def setup_area_art_routes(app: web.Application) -> None:
    app.router.add_get("/area-art/{name}", handle_area_art)
