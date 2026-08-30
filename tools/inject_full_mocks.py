"""Comprehensive mock data injector — populates every widget with realistic
state for visual testing. Run while the SLink server is listening on
TCP 54321 and HTTP 8080 (the defaults).

    python tools/inject_full_mocks.py                 # Gen 3 (Radical Red)
    python tools/inject_full_mocks.py --game gen1     # Gen 1 (Red/Blue)

GEN 1 IS NOT COSMETIC HERE. Every Gen 1 rendering defect the sweep found reached the
browser precisely because there was no Gen 1 payload to look at: the sprite that carried
no class for the stylesheet to select on, the badge bitmask rendered as a count, one
Special drawn as two stat chips. What differs is not decoration — the key FORMAT
(DDDD:TTTT:II; adapters reject a malformed one and render blanks), the area ids, and held
items, which Gen 1 does not have at all.

What you get after running:
* Both players (Alice / Bob) connected, FireRed / LeafGreen
* 6 linked party pairs (12 mons total) across routes 1-6
* 1 dead-zone link at route7 (Alice missed) → Memorial + Killfeed populate
* 1 boxed-link pair (route8) → Boxed Links populates
* 1 active battle on player B vs a wild Caterpie → Enemy widget
* 1 shiny captured → Shiny Counter shows ≥ 1
* Attempt counter set to 7
* Lock rules: species clause enabled

After running, refresh http://localhost:8099/ in your browser. If the
widgets still show "no data", call /api/reset first.
"""
import asyncio
import contextlib
import json
import urllib.request

TCP_HOST = "127.0.0.1"
TCP_PORT = 54321
HTTP = "http://127.0.0.1:8080"


async def send_tcp(events: list[dict]) -> None:
    r, w = await asyncio.open_connection(TCP_HOST, TCP_PORT)
    for m in events:
        w.write((json.dumps(m) + "\n").encode())
        await w.drain()
        # The server replies with newline-JSON; consume the response to
        # keep the connection clean.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(r.readline(), timeout=2.0)
    w.close()
    await w.wait_closed()


def http_post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        HTTP + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=4) as r:
        return json.loads(r.read().decode("utf-8"))


# Six linked pairs — each row is (area, alice_capture, bob_capture).
# species_id, key, nickname, level, held_item_id
# Held items use real Gen 3 FRLG IDs so the held-item rendering path is
# exercised with name lookups (verify against `adapter.item_name`):
#   183=Quick Claw, 186=Choice Band, 196=Focus Band, 197=Lucky Egg,
#   200=Leftovers, 202=Light Ball, 217=Silk Scarf.
# ── The game under test ──────────────────────────────────────────────────────────────
# Gen 3 by default, because that is what this script was written for. `--game gen1` swaps
# in a Gen 1 payload, which is not cosmetic: every Gen 1 rendering defect this sweep found
# reached the browser precisely because there was no Gen 1 mock to look at. The differences
# that matter are the key FORMAT (adapters reject a malformed one and render blanks), the
# area ids, and held items — Gen 1 has none, so a payload that carries them exercises a
# path the cartridge cannot produce.
GAME = "gen3"


def _is_gen1() -> bool:
    return GAME == "gen1"


# Gen 1 keys are DDDD:TTTT:II — DVs, OT id, species INDEX (not dex). The index values here
# are the real internal ones, so `toNatDex`-shaped lookups resolve: 0x99 Pikachu,
# 0xB0 Charmander, 0x24 Pidgey, 0xA5 Rattata, 0x05 Spearow, 0xA6 Geodude.
GEN1_PAIRS = [
    ("route_1",  (25, "AABB:30B8:99", "Sparky",  6, 0),  (4,  "CCDD:7B0B:B0", "Embo",   6, 0)),
    ("route_2",  (16, "1122:30B8:24", "Pidge",   8, 0),  (19, "3344:7B0B:A5", "Rattie", 8, 0)),
    ("route_3",  (21, "5566:30B8:05", "Sparrow", 9, 0),  (74, "7788:7B0B:A6", "Rocky",  9, 0)),
    ("route_4",  (29, "99AA:30B8:03", "Nidi",   11, 0),  (41, "BBCC:7B0B:6B", "Vampy", 11, 0)),
    ("route_5",  (27, "DDEE:30B8:60", "Shrewd", 12, 0),  (37, "FF00:7B0B:04", "Flick", 12, 0)),
    ("route_6",  (43, "0F1E:30B8:B9", "Smelly", 13, 0),  (69, "2D3C:7B0B:BC", "Twig",  13, 0)),
]

PAIRS = [
    ("route1",  (25, "PIKA001", "Sparky",  6, 202),  (4,  "CHAR001", "Embo",   6, 196)),
    ("route2",  (16, "PIDG002", "Pidge",   8, 0),    (19, "RATT002", "Rattie", 8, 183)),
    ("route3",  (21, "SPEA003", "Sparrow", 9, 210),  (74, "GEOD003", "Rocky",  9, 0)),
    ("route4",  (29, "NIDO004", "Nidi",   11, 0),    (41, "ZUBA004", "Vampy", 11, 200)),
    ("route5",  (27, "SAND005", "Shrewd", 12, 186),  (37, "VULP005", "Flick", 12, 0)),
    ("route6",  (43, "ODDI006", "Smelly", 13, 0),    (69, "BELL006", "Twig",  13, 197)),
]

# Common moves for each species (Gen 3 FRLG IDs). The party tick passes
# these in `moves:[...]` so move dropdowns render under each row.
MOVES = {
    25:  [84, 98, 86, 39],   # Pikachu: ThunderShock, QuickAttack, ThunderWave, Tail Whip
    4:   [52, 10, 43, 108],  # Charmander: Ember, Scratch, Leer, Smokescreen
    16:  [16, 33, 45, 98],   # Pidgey: Gust, Tackle, Sand-Attack, Quick Attack
    19:  [33, 39, 98, 44],   # Rattata: Tackle, Tail Whip, Quick Attack, Bite
    21:  [64, 43, 98, 31],   # Spearow: Peck, Leer, Quick Attack, Fury Attack
    74:  [88, 111, 33, 106], # Geodude: Rock Throw, Defense Curl, Tackle, Harden
    29:  [40, 33, 44, 24],   # Nidoran♀: Poison Sting, Tackle, Bite, Double Kick
    41:  [141, 48, 109, 44], # Zubat: Leech Life, Supersonic, Confuse Ray, Bite
    27:  [10, 28, 111, 154], # Sandshrew: Scratch, Sand-Attack, Defense Curl, Fury Cutter
    37:  [52, 39, 46, 44],   # Vulpix: Ember, Tail Whip, Roar, Bite
    43:  [71, 78, 230, 51],  # Oddish: Absorb, Sweet Scent, Sweet Kiss, Acid
    69:  [22, 71, 78, 51],   # Bellsprout: Vine Whip, Absorb, Sweet Scent, Acid
}

# Dead-zone pair (Alice missed, Bob would have caught Caterpie)
DEAD_ZONE_AREA = "route7"
DEAD_ZONE_BOB = (10, "CATE007", "Cat",     8, 0)

# Boxed pair (both caught but neither in party — would show in Boxed Links)
BOXED_AREA = "route8"
BOXED_A = (60, "POLI008", "Bubbles", 10, 217)
BOXED_B = (54, "PSYD008", "Quack",   10, 183)

# The same three fixtures for Gen 1. REAL area ids, not "route7": an id the adapter does
# not know renders with no display name and no encounter table, which is exactly the empty
# widget this script exists to avoid. Alice stands in Mt. Moon so the multi-floor encounter
# widget has something to show; Bob is on Route 4, which is where Mt. Moon lets out.
GEN1_DEAD_ZONE_AREA = "route_7"
GEN1_DEAD_ZONE_BOB = (10, "4A5B:7B0B:7B", "Cat", 8, 0)
GEN1_BOXED_AREA = "route_8"
GEN1_BOXED_A = (60, "6C7D:30B8:47", "Bubbles", 10, 0)
GEN1_BOXED_B = (54, "8E9F:7B0B:2F", "Quack", 10, 0)


def _rom_type(player: str) -> str:
    if _is_gen1():
        # Red and Blue, so the pair is the shape a real Gen 1 run has.
        return "gen1_rby"
    return "firered_rr" if player == "a" else "leafgreen_rr"


def _pairs():
    return GEN1_PAIRS if _is_gen1() else PAIRS


def _areas() -> tuple[str, str]:
    """(alice area, bob area) — real ids for the game, so the area widgets resolve."""
    return ("mt_moon", "route_4") if _is_gen1() else ("pewter_museum", "route_25")


def _dead_zone():
    return ((GEN1_DEAD_ZONE_AREA, GEN1_DEAD_ZONE_BOB) if _is_gen1()
            else (DEAD_ZONE_AREA, DEAD_ZONE_BOB))


def _boxed():
    return ((GEN1_BOXED_AREA, GEN1_BOXED_A, GEN1_BOXED_B) if _is_gen1()
            else (BOXED_AREA, BOXED_A, BOXED_B))


async def main() -> None:
    print("Resetting server state...")
    try:
        http_post("/api/reset", {})
    except Exception as e:
        print(f"  reset failed: {e}")

    print("Sending hellos + initial tick...")
    # Use Radical Red ROM types so the Upcoming Trainers widget activates
    # (the trainers_for_area / encounter_table adapter methods are RR-gated).
    await send_tcp([
        {"event": "hello", "player": "a", "rom_type": _rom_type("a"), "trainer_name": "Alice",
         "has_pokeballs": True, **({"ot_id": "30B8"} if _is_gen1() else {})},
        {"event": "hello", "player": "b", "rom_type": _rom_type("b"), "trainer_name": "Bob",
         "has_pokeballs": True, **({"ot_id": "7B0B"} if _is_gen1() else {})},
        # Tick events with party of 1 dummy so size > 0 and quarantine logic kicks in.
        # We'll set proper parties after all captures.
        {"event": "tick", "player": "a", "has_pokeballs": True, "party": [{"key": "BOOT0001"}], "current_area_id": "starter"},
        {"event": "tick", "player": "b", "has_pokeballs": True, "party": [{"key": "BOOT0002"}], "current_area_id": "starter"},
    ])

    print("Sending 6 paired captures + faint + shiny...")
    events: list[dict] = []
    # 6 linked pairs
    for area, (a_sid, a_key, a_nick, a_lv, a_item), (b_sid, b_key, b_nick, b_lv, b_item) in _pairs():
        events.append({"event": "area_enter", "player": "a", "area_id": area})
        events.append({"event": "area_enter", "player": "b", "area_id": area})
        events.append({
            "event": "capture", "player": "a", "area_id": area,
            "species_id": a_sid, "key": a_key, "nickname": a_nick,
            "level": a_lv, "hp": 20 + a_lv, "maxHP": 20 + a_lv,
            "gender": "male" if a_lv % 2 else "female",
            "ability_id": 1, "held_item_id": a_item, "in_box": False,
        })
        events.append({
            "event": "capture", "player": "b", "area_id": area,
            "species_id": b_sid, "key": b_key, "nickname": b_nick,
            "level": b_lv, "hp": 20 + b_lv, "maxHP": 20 + b_lv,
            "gender": "female" if b_lv % 2 else "male",
            "ability_id": 1, "held_item_id": b_item, "in_box": False,
        })

    # Dead zone: Alice misses, Bob catches (but link won't form → dead_zone)
    dz_area, dz_bob = _dead_zone()
    box_area, box_a, box_b = _boxed()
    events.append({"event": "area_enter", "player": "a", "area_id": dz_area})
    events.append({"event": "no_catch", "player": "a", "area_id": dz_area})
    events.append({"event": "area_enter", "player": "b", "area_id": dz_area})

    # Boxed-link area: both catch, link forms; later we move them to box
    events.append({"event": "area_enter", "player": "a", "area_id": box_area})
    events.append({"event": "area_enter", "player": "b", "area_id": box_area})
    a_sid, a_key, a_nick, a_lv, a_item = box_a
    b_sid, b_key, b_nick, b_lv, b_item = box_b
    events.append({
        "event": "capture", "player": "a", "area_id": box_area,
        "species_id": a_sid, "key": a_key, "nickname": a_nick,
        "level": a_lv, "hp": 20 + a_lv, "maxHP": 20 + a_lv,
        "gender": "male", "ability_id": 1, "held_item_id": a_item, "in_box": False,
    })
    events.append({
        "event": "capture", "player": "b", "area_id": box_area,
        "species_id": b_sid, "key": b_key, "nickname": b_nick,
        "level": b_lv, "hp": 20 + b_lv, "maxHP": 20 + b_lv,
        "gender": "female", "ability_id": 1, "held_item_id": b_item, "in_box": False,
    })

    # Faint one of the linked party mons — the route3 pair becomes a Memorial
    events.append({
        "event": "faint", "player": "a", "key": _pairs()[2][1][1],
        "area_id": _pairs()[2][0],
    })

    # Final area positions — drive each player into a real RR area that has
    # entries in rr_priority_trainers.json so the Upcoming Trainers widget
    # renders. A → Pewter Museum (Falkner), B → Route 25 (Bugsy). Different
    # areas exercise the split-view trainer column per player AND keep both
    # populated in the combined view's Area Briefing card.
    events.append({"event": "area_enter", "player": "a", "area_id": _areas()[0]})
    events.append({"event": "area_enter", "player": "b", "area_id": _areas()[1]})

    # Send party tick with all 6 alive Alice mons (so widget shows party of 6).
    # Held items + moves propagate so the held-item, move-dropdown, and LP
    # widget rendering paths all paint.
    alice_party = [
        {"key": a_key, "level": a_lv, "hp": 20 + a_lv, "maxHP": 20 + a_lv,
         "species_id": a_sid, "nickname": a_nick, "ability_id": 1,
         "held_item_id": a_item, "gender": "male",
         "moves": MOVES.get(a_sid, []),
         "pp": [25, 25, 25, 25], "pp_bonuses": 0,
         "active": (i == 0)}
        for i, (_, (a_sid, a_key, a_nick, a_lv, a_item), _) in enumerate(_pairs())
    ]
    bob_party = [
        {"key": b_key, "level": b_lv, "hp": 20 + b_lv, "maxHP": 20 + b_lv,
         "species_id": b_sid, "nickname": b_nick, "ability_id": 1,
         "held_item_id": b_item, "gender": "female",
         "moves": MOVES.get(b_sid, []),
         "pp": [25, 25, 25, 25], "pp_bonuses": 0,
         "active": (i == 0)}
        for i, (_, _, (b_sid, b_key, b_nick, b_lv, b_item)) in enumerate(_pairs())
    ]
    # Tick fields are FLAT (not nested under "battle_state") — the server
    # only reads in_battle / enemy_party / is_trainer_battle at the top
    # level of the tick message. See server.py handle_event tick branch.
    events.append({
        "event": "tick", "player": "a", "has_pokeballs": True,
        # Real RR area_id so the Upcoming Trainers widget renders (Falkner @ Pewter Museum).
        "party": alice_party, "current_area_id": _areas()[0],
        "ball_count": 12, "badges": 0b00000011,  # 2 badges
        "in_battle": False, "enemy_party": [],
    })
    # Bob in active battle vs wild Caterpie — populates Enemy widget,
    # Calc preview, and the "NEW ENCOUNTER" badge when nuzlocke-active.
    # Different area (route_25 = Bugsy) so split view shows distinct trainer
    # cards per side, and combined view's Area Briefing shows two sides.
    events.append({
        "event": "tick", "player": "b", "has_pokeballs": True,
        "party": bob_party, "current_area_id": _areas()[1],
        "ball_count": 7, "badges": 0b00000001,  # 1 badge
        "in_battle": True, "is_trainer_battle": False,
        "opponent_name": "", "opponent_class": "",
        "is_doubles": False,
        "enemy_party": [
            {"species_id": 10, "level": 11, "hp": 28, "maxHP": 32,
             "active": True, "ability_id": 19, "key": "WILD_CATE",
             "status_cond": 0, "stat_stages": {},
             "moves": [33, 81], "pp": [35, 40], "pp_bonuses": 0},
        ],
    })

    await send_tcp(events)

    print("Bumping attempt counter via /api/attempts...")
    try:
        http_post("/api/attempts", {"count": 7})
    except Exception as e:
        print(f"  /api/attempts failed: {e}")

    print("Done. Refresh http://localhost:8080/ in the browser.")


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser(description=__doc__)
    _ap.add_argument("--game", choices=("gen3", "gen1"), default="gen3",
                     help="which generation's payload to inject (default: gen3)")
    _args = _ap.parse_args()
    globals()['GAME'] = _args.game
    print(f"Injecting the {GAME} payload…")
    asyncio.run(main())
