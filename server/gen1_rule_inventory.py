"""RBY physical party projection into the shared non-authoritative rule cache."""

from server.gen1_initial_observation import inventory
from server.gen1_party_codec import PartyCodec
from server.party_observation_cache import refresh


def refresh_party(rules, player, observation, identity):
    source = observation["source"]
    roster = inventory(source, identity)
    codec = PartyCodec(source["variant"])
    rows = []
    for member in roster["members"]:
        if member["location"] != "party":
            continue
        mon = codec.validate_blob(bytes.fromhex(member["blob_hex"]))
        hp, attack, defense, speed, special = mon.computed_stats
        rows.append(
            {
                "slot": member["slot"],
                "key": mon.key,
                "species_id": mon.species_id,
                "level": mon.level,
                "blob": mon.raw,
                "stats": {
                    "level": mon.level,
                    "maxHP": hp,
                    "attack": attack,
                    "defense": defense,
                    "speed": speed,
                    "spAtk": special,
                    "spDef": special,
                },
            }
        )
    refresh(rules, player, rows)
