"""Comprehensive mock data injector — populates every widget with realistic
state for visual testing. Run while the SLink server is listening on
TCP 54321 and HTTP 8080 (the defaults).

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
import os
import urllib.request

# Defaults match `python -m server.server`. A run spawned by the Run Manager gets its own
# pair of ports (TCP from 54321, HTTP from 8081), so both are overridable rather than
# requiring a second copy of this script to talk to a managed run.
TCP_HOST = os.environ.get("SLINK_MOCK_TCP_HOST", "127.0.0.1")
TCP_PORT = int(os.environ.get("SLINK_MOCK_TCP_PORT", "54321"))
HTTP = os.environ.get("SLINK_MOCK_HTTP", "http://127.0.0.1:8080")


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


# ── Gen 1 (Red/Blue) variant ─────────────────────────────────────────────
# Gen 3 is the default because that is the game this script was written for.
# `--game gen1` swaps the whole cast: Gen 1 keys are `DVs:OTID:species`, area ids are
# underscored, and there are no abilities and no held items to send at all — passing
# Gen 3's values through would paint columns the generation does not have, which is the
# exact class of bug these mocks exist to expose.
GAME = "gen3"


def _is_gen1() -> bool:
    return GAME == "gen1"


# (area, alice_capture, bob_capture); capture = (species, key, nickname, level, held_item)
# held_item is always 0 — Gen 1 cartridges have no held-item slot.
GEN1_PAIRS = [
    ("route_1",         (25, "4A5B:30B8:19", "Sparky",  6, 0), (4,  "3C2D:7B0B:04", "Embo",   6, 0)),
    ("route_2",         (16, "5B6C:30B8:10", "Pidge",   8, 0), (19, "2D3E:7B0B:13", "Rattie", 8, 0)),
    ("viridian_forest", (13, "6C7D:30B8:0D", "Sting",   9, 0), (10, "1E2F:7B0B:0A", "Wiggle", 9, 0)),
    ("route_3",         (21, "7D8E:30B8:15", "Sparrow",11, 0), (74, "0F1A:7B0B:4A", "Rocky", 11, 0)),
    ("mt_moon_1f",      (41, "8E9F:30B8:29", "Vampy",  12, 0), (46, "9A0B:7B0B:2E", "Shroom",12, 0)),
    ("route_4",         (27, "9F0A:30B8:1B", "Shrewd", 13, 0), (23, "8B1C:7B0B:17", "Slither",13, 0)),
]

# Gen 1 move ids (pokered constants/move_constants.asm). Same slot meaning as MOVES.
GEN1_MOVES = {
    25: [84, 98, 86, 39],    # Pikachu: ThunderShock, Quick Attack, Thunder Wave, Tail Whip
    4:  [52, 10, 43, 108],   # Charmander: Ember, Scratch, Leer, Smokescreen
    16: [16, 33, 45, 98],    # Pidgey: Gust, Tackle, Sand-Attack, Quick Attack
    19: [33, 39, 98, 44],    # Rattata: Tackle, Tail Whip, Quick Attack, Bite
    13: [40, 81],            # Weedle: Poison Sting, String Shot
    10: [33, 81],            # Caterpie: Tackle, String Shot
    21: [64, 43, 98, 31],    # Spearow: Peck, Leer, Quick Attack, Fury Attack
    74: [88, 111, 33, 106],  # Geodude: Rock Throw, Defense Curl, Tackle, Harden
    41: [141, 48, 44],       # Zubat: Leech Life, Supersonic, Bite
    46: [10, 78, 147],       # Paras: Scratch, Stun Spore, Spore
    27: [10, 28, 111],       # Sandshrew: Scratch, Sand-Attack, Defense Curl
    23: [35, 40, 44],        # Ekans: Wrap, Poison Sting, Bite
}

GEN1_DEAD_ZONE_AREA = "route_22"
GEN1_DEAD_ZONE_BOB = (56, "7A8B:7B0B:38", "Mankey", 8, 0)
GEN1_BOXED_AREA = "route_5"
GEN1_BOXED_A = (60, "6D7E:30B8:3C", "Bubbles", 10, 0)
GEN1_BOXED_B = (54, "5E6F:7B0B:36", "Quack",   10, 0)


def _rom_type(player: str) -> str:
    """What each player's client reports in its hello.

    Must be a string _ROM_TYPE_TO_GAME_ID knows: an unrecognised rom_type leaves the
    server on whichever adapter it already had, silently, and the run keeps going under
    the wrong generation. Gen 1 was reporting "gen1_rby" -- an adapter game_id, which no
    client ever sends -- and produced Gen 3 abilities and genders on Red/Blue mons.

    Gen 1 uses Red and Blue, which is a real pair and exercises two different versions in
    one run. Gen 3 uses firered_rr on BOTH sides, because Radical Red is a FireRed hack
    and there is no LeafGreen build of it: "leafgreen_rr", which this script used to send,
    is not a cartridge that exists. It is routed nowhere, though server.py:3397 does carry
    a display label for it.
    """
    if _is_gen1():
        return "red" if player == "a" else "blue"
    return "firered_rr"


def _pairs():
    return GEN1_PAIRS if _is_gen1() else PAIRS


def _moves():
    return GEN1_MOVES if _is_gen1() else MOVES


def _final_areas() -> tuple[str, str]:
    """Where each player is standing when the mocks finish.

    BOTH must be areas with a wild encounter table, and they must DIFFER. Encounter data
    is per player -- two randomized cartridges do not share one -- so a player parked
    somewhere with no encounters leaves that panel empty, and an empty panel reads as
    missing data rather than as the point being made.

    Gen 3 also wants priority trainers so the Upcoming Trainers widget renders. This used
    to say pewter_museum "so the widget renders (Falkner @ Pewter Museum)", which has one
    priority trainer and no encounters at all; route_22 has seven and six.
    """
    return ("route_3", "route_24") if _is_gen1() else ("route_22", "cerulean_city")


def _dead_zone():
    return ((GEN1_DEAD_ZONE_AREA, GEN1_DEAD_ZONE_BOB) if _is_gen1()
            else (DEAD_ZONE_AREA, DEAD_ZONE_BOB))


def _boxed():
    return ((GEN1_BOXED_AREA, GEN1_BOXED_A, GEN1_BOXED_B) if _is_gen1()
            else (BOXED_AREA, BOXED_A, BOXED_B))


def _wild_foe() -> dict:
    """The mon the player is mid-battle against. Gen 1 has no abilities, so sending an
    ability_id would be a lie the enemy panel would happily render."""
    if _is_gen1():
        return {"species_id": 10, "level": 11, "hp": 28, "maxHP": 32, "active": True,
                "key": "1A2B:0000:0A", "status_cond": 0, "stat_stages": {},
                "moves": [33, 81], "pp": [35, 40]}
    return {"species_id": 10, "level": 11, "hp": 28, "maxHP": 32, "active": True,
            "ability_id": 19, "key": "WILD_CATE", "status_cond": 0, "stat_stages": {},
            "moves": [33, 81], "pp": [35, 40], "pp_bonuses": 0}


def _stored(tag: str, ot: str, species: int) -> str:
    """A box-slot key valid for the active generation.

    Gen 1 keys are structured (``DVs:OTID:species``) and the adapter rejects anything
    else, so a readable literal like "STORED_A1" would silently drop the row on Gen 1
    and leave the box table looking merely short rather than broken.
    """
    if _is_gen1():
        return f"{ord(tag[0]):02X}{int(tag[1]):02X}:{ot}:{species:02X}"
    return "STORED_" + tag


def _mon(species, key, nick, lv, item, *, gender, active):
    """One party entry, with the fields this generation actually has.

    Gen 1 gets no ability_id, no held_item_id and no gender: the adapter reports
    genderless for every key, and a card that prints "male" beside a Gen 1 mon is
    showing the player something their cartridge cannot know.
    """
    d = {"key": key, "level": lv, "hp": 20 + lv, "maxHP": 20 + lv,
         "species_id": species, "nickname": nick, "active": active,
         "moves": _moves().get(species, []), "pp": [25, 25, 25, 25]}
    if not _is_gen1():
        d.update(ability_id=1, held_item_id=item, gender=gender, pp_bonuses=0)
    return d


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
        {"event": "tick", "player": "a", "has_pokeballs": True, "party": [{"key": ("0001:30B8:19" if _is_gen1() else "BOOT0001")}], "current_area_id": "starter"},
        {"event": "tick", "player": "b", "has_pokeballs": True, "party": [{"key": ("0002:7B0B:04" if _is_gen1() else "BOOT0002")}], "current_area_id": "starter"},
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
            "in_box": False,
            **({} if _is_gen1() else {"gender": "male" if a_lv % 2 else "female",
                                      "ability_id": 1, "held_item_id": a_item}),
        })
        events.append({
            "event": "capture", "player": "b", "area_id": area,
            "species_id": b_sid, "key": b_key, "nickname": b_nick,
            "level": b_lv, "hp": 20 + b_lv, "maxHP": 20 + b_lv,
            "in_box": False,
            **({} if _is_gen1() else {"gender": "female" if b_lv % 2 else "male",
                                      "ability_id": 1, "held_item_id": b_item}),
        })

    # Dead zone: Alice misses, Bob catches (but link won't form → dead_zone)
    dz_area, _dz_bob = _dead_zone()
    events.append({"event": "area_enter", "player": "a", "area_id": dz_area})
    events.append({"event": "no_catch", "player": "a", "area_id": dz_area})
    events.append({"event": "area_enter", "player": "b", "area_id": dz_area})

    # Boxed-link area: both catch, link forms; later we move them to box
    boxed_area, boxed_a, boxed_b = _boxed()
    events.append({"event": "area_enter", "player": "a", "area_id": boxed_area})
    events.append({"event": "area_enter", "player": "b", "area_id": boxed_area})
    a_sid, a_key, a_nick, a_lv, a_item = boxed_a
    b_sid, b_key, b_nick, b_lv, b_item = boxed_b
    events.append({
        "event": "capture", "player": "a", "area_id": boxed_area,
        "species_id": a_sid, "key": a_key, "nickname": a_nick,
        "level": a_lv, "hp": 20 + a_lv, "maxHP": 20 + a_lv, "in_box": False,
        **({} if _is_gen1() else {"gender": "male", "ability_id": 1, "held_item_id": a_item}),
    })
    events.append({
        "event": "capture", "player": "b", "area_id": boxed_area,
        "species_id": b_sid, "key": b_key, "nickname": b_nick,
        "level": b_lv, "hp": 20 + b_lv, "maxHP": 20 + b_lv, "in_box": False,
        **({} if _is_gen1() else {"gender": "female", "ability_id": 1, "held_item_id": b_item}),
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
    final_a, final_b = _final_areas()
    events.append({"event": "area_enter", "player": "a", "area_id": final_a})
    events.append({"event": "area_enter", "player": "b", "area_id": final_b})

    # Send party tick with all 6 alive Alice mons (so widget shows party of 6).
    # Held items + moves propagate so the held-item, move-dropdown, and LP
    # widget rendering paths all paint.
    alice_party = [
        _mon(*a_cap, gender="male", active=(i == 0))
        for i, (_, a_cap, _) in enumerate(_pairs())
    ]
    bob_party = [
        _mon(*b_cap, gender="female", active=(i == 0))
        for i, (_, _, b_cap) in enumerate(_pairs())
    ]
    # Tick fields are FLAT (not nested under "battle_state") — the server
    # only reads in_battle / enemy_party / is_trainer_battle at the top
    # level of the tick message. See server.py handle_event tick branch.
    events.append({
        "event": "tick", "player": "a", "has_pokeballs": True,
        # Real RR area_id so the Upcoming Trainers widget renders (Falkner @ Pewter Museum).
        "party": alice_party, "current_area_id": final_a,
        "ball_count": 12, "badges": 0b00000011,  # 2 badges
        "in_battle": False, "enemy_party": [],
    })
    # Bob in active battle vs wild Caterpie — populates Enemy widget,
    # Calc preview, and the "NEW ENCOUNTER" badge when nuzlocke-active.
    # Different area (route_25 = Bugsy) so split view shows distinct trainer
    # cards per side, and combined view's Area Briefing shows two sides.
    events.append({
        "event": "tick", "player": "b", "has_pokeballs": True,
        "party": bob_party, "current_area_id": final_b,
        "ball_count": 7, "badges": 0b00000001,  # 1 badge
        "in_battle": True, "is_trainer_battle": False,
        "opponent_name": "", "opponent_class": "",
        "is_doubles": False,
        "enemy_party": [_wild_foe()],
    })

    # PC boxes. Without these every box-facing surface (the dashboard's box table,
    # the Boxed Links overlay, any "where is it stored" lookup) renders empty, and an
    # empty panel hides its own layout bugs. The boxed-link pair from BOXED_AREA is
    # deposited for real; two filler mons give the table more than one row to lay out.
    # Deliberately NOT writing into the memorial box -- that trips the contamination
    # check, which is a different behaviour from the one these mocks exist to show.
    box_a, box_b = boxed_a, boxed_b
    events.append({
        "event": "tick", "player": "a", "has_pokeballs": True,
        "party": alice_party, "current_area_id": final_a,
        "pc_boxes": [
            {"box": 0, "slot": 0, "key": box_a[1], "nickname": box_a[2],
             "species_id": box_a[0], "held_item_id": box_a[4], "moves": _moves().get(box_a[0], [])},
            {"box": 0, "slot": 1, "key": _stored("A1", "30B8", 133), "nickname": "Spare",
             "species_id": 133, "held_item_id": 0, "moves": []},
            {"box": 1, "slot": 4, "key": _stored("A2", "30B8", 63), "nickname": "Bench",
             "species_id": 63, "held_item_id": 0, "moves": []},
        ],
    })
    events.append({
        "event": "tick", "player": "b", "has_pokeballs": True,
        "party": bob_party, "current_area_id": final_b,
        "pc_boxes": [
            {"box": 0, "slot": 0, "key": box_b[1], "nickname": box_b[2],
             "species_id": box_b[0], "held_item_id": box_b[4], "moves": _moves().get(box_b[0], [])},
            {"box": 0, "slot": 1, "key": _stored("B1", "7B0B", 129), "nickname": "Reserve",
             "species_id": 129, "held_item_id": 0, "moves": []},
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
                     help="which generation's cast to inject (default: gen3)")
    GAME = _ap.parse_args().game
    asyncio.run(main())
