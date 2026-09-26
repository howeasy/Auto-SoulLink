"""The vanilla Gen 3 item table names exactly the FR/LG ids (pret pokefirered c75f3523,
include/constants/items.h + src/data/items.json; data/gen3_sources.lock.json).

Found by the Emerald planning lane (OMP cx-2143b165): ids 52-62 are unused placeholders in Gen 3 and
ITEMS_COUNT is 377, yet the table named Park/Cherish/Dusk/Heal/Quick Ball and 622-631, and it had no
FRLG key items (259-288, 349-374)."""
from server.adapters.gen3_frlge import Gen3Adapter
from server.data.items.gen3_vanilla import ITEM_NAMES


def test_no_non_gen3_item_is_named():
    assert not set(range(52, 63)) & set(ITEM_NAMES)
    assert 347 not in ITEM_NAMES and 348 not in ITEM_NAMES
    assert max(ITEM_NAMES) < 375                     # 375/376 are Emerald-only, >= 377 never occurs


def test_anchors_and_the_frlg_key_items():
    assert (ITEM_NAMES[1], ITEM_NAMES[4], ITEM_NAMES[13]) == ("Master Ball", "Poké Ball", "Potion")
    assert ITEM_NAMES[259] == "Mach Bike" and ITEM_NAMES[288] == "Devon Scope"
    assert ITEM_NAMES[349] == "Oak's Parcel" and ITEM_NAMES[364] == "TM Case" and ITEM_NAMES[374] == "Sapphire"


def test_the_vanilla_adapter_names_a_key_item_and_not_a_placeholder():
    a = Gen3Adapter(is_rr=False)
    assert a.item_name(362) == "VS Seeker"
    assert a.item_name(60) == "Item #60"
