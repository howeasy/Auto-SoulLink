"""Independent trade-result policy using generated facts and controlled rules."""
import copy
import json
from itertools import product
from pathlib import Path

import pytest

from server.gen1_party_codec import PartyCodec, PartyCodecError
from server.gen1_trade_result import TradeResultRules
from server.stat_experience import calculate_stat, split_dvs
from tests.unit.test_gen1_party_codec import make_blob
from tests.unit.test_gen1_stat_formula import FIELDS, calc_stats


def rules(variant="red"):
    codec = PartyCodec(variant)
    names = {int(index): bytes((128, 128+int(index)//26, 128+int(index)%26, 80)) + b"\x50"*7
             for index in codec.profile["species"]}
    records = {int(index): {"evolutions": [
        ("trade" if facts["dex"] in (64, 67, 75, 93) else "level", 1, target)
        for target in facts["evolution_targets"]], "moves": []}
        for index, facts in codec.profile["species"].items()}
    records[14]["moves"] = [(29, 95)]
    return TradeResultRules(variant, names=names, records=records, hm_moves=[15, 19, 57, 70, 148],
                            rom_sha1="a"*40)


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_evolution_preserves_every_non_evolving_field_and_damage(variant):
    policy = rules(variant)
    incoming = make_blob(policy.codec, species=147, otid=0xBEEF, dv=0x7654)
    result, = policy.outcomes(incoming)
    mon = policy.codec.validate_blob(result.blob)
    assert mon.species_index == 14 and result.evolution_path == (14,)
    assert mon.computed_stats == (22, 12, 11, 19, 21) and mon.hp == 12
    allowed = {0, 1, 2, 5, 6, *range(34, 44)}
    assert all(result.blob[i] == value for i, value in enumerate(incoming) if i not in allowed)


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("space", [True, False])
def test_learning_is_required_with_space_and_only_valid_choices_without_space(variant, space):
    policy = rules(variant)
    raw = bytearray(make_blob(policy.codec, species=147, level=29))
    if not space:
        raw[8:12] = bytes((15, 2, 3, 4))  # Cut cannot be forgotten
        raw[29:33] = bytes((10, 20, 5, 5))
    results = policy.outcomes(bytes(raw))
    assert {result.learning[-1][2] for result in results} == ({2} if space else {None, 1, 2, 3})
    for result in results:
        slot = result.learning[-1][2]
        if slot is not None:
            assert result.blob[8+slot] == 95 and result.blob[29+slot] == policy.codec.max_pp(95, 0)
        assert result.blob[8] == raw[8] and result.blob[29] == raw[29]


def test_known_level_move_is_not_relearned_or_refilled():
    policy = rules()
    raw = bytearray(make_blob(policy.codec, species=147, level=29))
    raw[8] = 95
    raw[29] = 1
    result, = policy.outcomes(bytes(raw))
    assert not result.learning and result.blob[8:12] == raw[8:12] and result.blob[29:33] == raw[29:33]


def test_default_name_comparison_ends_at_terminator_and_replaces_full_name():
    policy = rules()
    raw = bytearray(make_blob(policy.codec, species=147))
    raw[55:66] = policy._names[147][:4] + b"\x4f"*7
    result, = policy.outcomes(bytes(raw))
    assert result.blob[55:66] == policy._names[14]


def test_nontrade_entry_stops_original_evolution_list_and_methods_can_disable_trade_evolution():
    policy = rules()
    policy._records[147] = ((("level", 1, 14),), ())
    raw = make_blob(policy.codec, species=147)
    result, = policy.outcomes(raw)
    assert result.blob == raw and not result.evolution_path


def test_invalid_post_evolution_hp_is_refused_before_any_effect():
    policy = rules()
    raw = bytearray(make_blob(policy.codec, species=147))
    raw[34:36] = (999).to_bytes(2, "big")
    before = bytes(raw)
    with pytest.raises(PartyCodecError, match="invalid HP"):
        policy.outcomes(raw)
    assert bytes(raw) == before


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_equal_raw_keys_validate_local_order_without_claiming_native_completion(variant):
    policy = rules(variant)
    members = [make_blob(policy.codec, dv=0x1000+i) for i in range(3)]
    key = policy.codec.validate_blob(members[1]).key
    result = policy.verify_party(members, 1, members[1], [members[0], members[2], members[1]],
        expected_key=key, incoming_key=key, boxed_keys=())
    assert result.blob == members[1] and not hasattr(result, "native_completed")
    with pytest.raises(PartyCodecError, match="differs"):
        policy.verify_party(members, 1, members[1], members, expected_key=key, incoming_key=key, boxed_keys=())


@pytest.mark.parametrize("offset", [0, 2, 3, 4, 7, 8, 12, 14, 17, 27, 29, 33, 34, 44, 55])
def test_unrelated_poststate_corruption_is_refused(offset):
    policy = rules()
    before = make_blob(policy.codec)
    incoming = make_blob(policy.codec, species=147, otid=0xBEEF)
    outcome, = policy.outcomes(incoming)
    corrupted = bytearray(outcome.blob)
    corrupted[offset] ^= 1
    with pytest.raises(PartyCodecError):
        policy.verify_party([before], 0, incoming, [corrupted], expected_key=policy.codec.validate_blob(before).key,
            incoming_key=policy.codec.validate_blob(incoming).key, boxed_keys=())


@pytest.mark.parametrize("level", [1, 5, 29, 50, 100])
def test_shared_stat_experience_arithmetic_matches_independent_reference(level):
    base = dict(zip(FIELDS, (45, 49, 49, 45, 65), strict=True))
    for dv, exp in product((0, 0x7654, 0xAAAA, 0xFFFF), (0, 1, 15, 16, 17, 255, 256, 257, 65535)):
        expected = calc_stats(base, level, dv, dict.fromkeys(FIELDS, exp))
        actual = {field: calculate_stat(base[field], iv, level, exp, hp=(field == "hp"))
                  for field, iv in zip(FIELDS, split_dvs(dv), strict=True)}
        assert actual == expected


@pytest.mark.parametrize("where", ["missing-species", "changed-target", "bad-name", "bad-move", "bad-hm"])
def test_malformed_rule_inputs_cannot_become_prediction_policy(where):
    policy = rules()
    names = dict(policy._names)
    records = {key: {"evolutions": list(value[0]), "moves": list(value[1])} for key, value in policy._records.items()}
    hms = list(policy._hm_moves)
    if where == "missing-species": del records[153]
    elif where == "changed-target": records[147]["evolutions"] = [("trade", 1, 153)]
    elif where == "bad-name": names[147] = b"\x4f"*11
    elif where == "bad-move": records[14]["moves"] = [(29, True)]
    else: hms[0] = []
    original = copy.deepcopy((names, records, hms))
    with pytest.raises(PartyCodecError):
        TradeResultRules("red", names=names, records=records, hm_moves=hms, rom_sha1="a"*40)
    assert (names, records, hms) == original


def save_case(variant="red", *, happiness=150):
    policy = rules(variant)
    root = Path(__file__).resolve().parents[2]
    symbols = json.loads((root / "data/pret_syms.json").read_text())["pokeyellow" if variant == "yellow" else "pokered"]
    incoming = make_blob(policy.codec, species=147, otid=0xBEEF)
    outgoing = make_blob(policy.codec, species=84 if variant == "yellow" else 153)
    outcome, = policy.outcomes(incoming)
    storage = bytearray(404)
    storage[:3] = bytes((1, outcome.blob[0], 255))
    storage[8:52] = outcome.blob[:44]
    storage[272:283] = outcome.blob[44:55]
    storage[338:349] = outcome.blob[55:66]
    start = symbols["sGameData"]
    main = symbols["sMainData"] - start
    before = bytearray((i*13+7) % 256 for i in range(symbols["sMainDataCheckSum"]-start+1))
    before[:11] = outgoing[44:55]
    identity = main + symbols["wPlayerID"] - symbols["wMainDataStart"]
    before[identity:identity+2] = bytes.fromhex("1234")
    before[-1] = 255-(sum(before[:-1]) & 255)
    after = bytearray(before)
    offset = symbols["sPartyData"] - start
    after[offset:offset+404] = storage
    dex = bytes(38)
    expected_dex = bytearray(dex)
    for species in (147, 14):
        bit = policy.codec.profile["species"][str(species)]["dex"]-1
        expected_dex[bit//8] |= 1 << (bit % 8)
        expected_dex[19+bit//8] |= 1 << (bit % 8)
    after[main:main+38] = expected_dex
    pika = None
    if variant == "yellow":
        pika = bytes((happiness, 128))
        p = main + symbols["wPikachuHappiness"] - symbols["wMainDataStart"]
        after[p:p+2] = bytes((max(0, happiness-(20 if happiness >= 200 else 10)), 0))
    after[-1] = 255-(sum(after[:-1]) & 255)
    kwargs = dict(before_region=bytes(before), before_dex=dex, incoming=incoming, outgoing=outgoing,
                  outcome=outcome, save_id="1234", save_name=outgoing[44:55], before_pikachu=pika)
    return policy, bytes(after), bytes(storage), [outcome.blob], kwargs, symbols


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_complete_canonical_save_region_and_identity_are_checked(variant):
    policy, region, storage, after, kwargs, _ = save_case(variant)
    digest = policy.verify_save_region(region, storage, after, **kwargs)
    assert len(digest) == 64


@pytest.mark.parametrize("happiness", [0, 1, 9, 10, 99, 100, 199, 200, 255])
def test_yellow_happiness_bands_clamp_and_reset_mood(happiness):
    policy, region, storage, after, kwargs, _ = save_case("yellow", happiness=happiness)
    assert policy.verify_save_region(region, storage, after, **kwargs)


@pytest.mark.parametrize("tamper", ["checksum", "party", "owned", "seen", "identity", "name", "unrelated", "pika"])
def test_save_tampering_is_refused_even_with_repaired_checksum(tamper):
    policy, region, storage, after, kwargs, symbols = save_case("yellow")
    modified = bytearray(region)
    start = symbols["sGameData"]
    main = symbols["sMainData"] - start
    positions = {"checksum": len(modified)-1, "party": symbols["sPartyData"]-start+8+2,
                 "owned": main, "seen": main+19, "name": 0, "unrelated": main+50,
                 "identity": main+symbols["wPlayerID"]-symbols["wMainDataStart"],
                 "pika": main+symbols["wPikachuHappiness"]-symbols["wMainDataStart"]}
    modified[positions[tamper]] ^= 1
    if tamper != "checksum":
        modified[-1] = 255-(sum(modified[:-1]) & 255)
    with pytest.raises(PartyCodecError):
        policy.verify_save_region(bytes(modified), storage, after, **kwargs)


def test_single_use_box_inventory_is_materialized_before_both_party_checks():
    policy = rules()
    outgoing = make_blob(policy.codec)
    incoming = make_blob(policy.codec, otid=0xBEEF)
    key = policy.codec.validate_blob(outgoing).key
    peer = policy.codec.validate_blob(incoming).key
    with pytest.raises(PartyCodecError, match="duplicate"):
        policy.verify_party([outgoing], 0, incoming, [incoming], expected_key=key,
            incoming_key=peer, boxed_keys=iter([key]))
