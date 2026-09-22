"""Generate all selected Gen 2 trainer parties from ASM and verify every ROM byte.

Keeps consumer-compatible classes/named_trainers maps; adds complete typed parties.
Mystery Gift CAL2, link and Battle Tower parties remain explicit dynamic exclusions.
"""
from __future__ import annotations

import re

if __package__:
    from .gen_gen2_area_map import source_lines
    from .gen_gen2_charmap import encode, name_list, parse_charmap, run_cli, verify_table
    from .gen_gen2_statics import arguments, byte, source_ref, values
else:
    from gen_gen2_area_map import source_lines
    from gen_gen2_charmap import encode, name_list, parse_charmap, run_cli, verify_table
    from gen_gen2_statics import arguments, byte, source_ref, values


def trainer_classes(ctx):
    classes, instances, current, ordinal = {}, {}, None, 0
    for _, line in source_lines(ctx.read_source("constants/trainer_constants.asm"), ctx.title):
        if match := re.fullmatch(r"trainerclass (\w+)", line):
            current = match[1]
            classes[current] = ordinal
            instances[ordinal] = []
            ordinal += 1
        elif match := re.fullmatch(r"const (\w+)", line):
            if current is not None:
                instances[classes[current]].append(match[1])
        elif line.startswith(("const_skip", "const_next")):
            raise ValueError("unsupported trainer instance numbering")
    if classes.get("TRAINER_NONE") != 0 or classes.get("FALKNER") != 1:
        raise ValueError("trainer class origin changed")
    return classes, instances


def parse_parties(ctx, names, encoding):
    groups, group, trainer = {}, None, None
    for line_no, line in source_lines(ctx.read_source("data/trainers/parties.asm"), ctx.title):
        if line.startswith("INCLUDE ") or line == "Trainers:":
            continue
        if match := re.fullmatch(r"(\w+Group):", line):
            if trainer is not None or match[1] in groups:
                raise ValueError("unterminated trainer or duplicate group")
            group = match[1]
            groups[group] = []
        elif match := re.fullmatch(r'db "([^"\n]*)@",\s*(TRAINERTYPE_\w+)', line):
            if group is None or trainer is not None:
                raise ValueError("unexpected trainer header")
            kind = names.get(match[2])
            if kind not in (0, 1, 2, 3):
                raise ValueError("unsupported trainer party type")
            raw_name = match[1]
            encoded = encode(raw_name + "@", encoding)
            if len(encoded) > 11 or 0xff in encoded:
                raise ValueError("invalid trainer name bytes")
            trainer = {"name_raw": raw_name, "name": raw_name.title(), "trainer_type": kind,
                       "party": [], "source": source_ref(ctx, "data/trainers/parties.asm", line_no),
                       "encoded": bytearray(encoded + bytes([kind]))}
        elif line == "db -1":
            if trainer is None or not 1 <= len(trainer["party"]) <= 6:
                raise ValueError("empty/oversized/missing trainer party")
            trainer["encoded"].append(255)
            groups[group].append(trainer)
            trainer = None
        elif line.startswith("db "):
            if trainer is None:
                raise ValueError("party data outside trainer record")
            fields = [byte(token, names) for token in arguments(line[3:])]
            kind = trainer["trainer_type"]
            expected = 2 + bool(kind & 2) + 4 * bool(kind & 1)
            if len(fields) != expected or not 1 <= fields[0] <= 100 or not 1 <= fields[1] <= 251:
                raise ValueError("malformed trainer monster record")
            mon = {"level": fields[0], "species": fields[1],
                   "item": fields[2] if kind & 2 else None,
                   "moves": fields[-4:] if kind & 1 else None}
            if mon["moves"] is not None and any(move > 251 for move in mon["moves"]):
                raise ValueError("invalid trainer move")
            trainer["party"].append(mon)
            trainer["encoded"].extend(fields)
        else:
            raise ValueError(f"unsupported trainer source line {line_no}: {line}")
    if trainer is not None or not groups:
        raise ValueError("unterminated/empty trainer source")
    return groups


def display_name(name):
    return name.replace("<PKMN>", "Pokémon").replace("#", "Poké").title()


def build(ctx):
    """Derive named trainer parties and retain dynamic caller exclusions."""
    names = values(ctx)
    classes, instances = trainer_classes(ctx)
    encoding = parse_charmap(ctx.read_source("constants/charmap.asm"))["encoding"]
    groups = parse_parties(ctx, names, encoding)
    pointers = []
    for _, line in source_lines(ctx.read_source("data/trainers/party_pointers.asm"), ctx.title):
        if match := re.fullmatch(r"dw (\w+Group)", line):
            pointers.append(match[1])
        elif line != "TrainerGroups:" and not line.startswith(("table_width ", "assert_table_length ")):
            raise ValueError(f"unsupported trainer pointer source: {line}")
    if len(pointers) != len(classes) - 1 or set(pointers) != set(groups):
        raise ValueError("trainer pointer/class/group coverage mismatch")
    bank = ctx.symbol("TrainerGroups").bank
    expected = bytearray()
    for label in pointers:
        symbol = ctx.symbol(label)
        if symbol.bank != bank:
            raise ValueError("trainer group pointer crosses bank")
        expected.extend(symbol.address.to_bytes(2, "little"))
    verify_table(ctx, "TrainerGroups", bytes(expected))
    class_names, names_receipt = name_list(ctx, "data/trainers/class_names.asm", "TrainerClassNames",
                                          "TRAINER_CLASS_NAME_LENGTH", len(pointers))
    output = {"schema": "gen2-trainers-v1", "generator": "gen_gen2_trainers.py",
              "source": ctx.source_record(), "classes": {"0": "Nobody"}, "named_trainers": {},
              "class_constants": {str(value): name for name, value in classes.items()},
              "parties": {}, "class_names_rom": names_receipt,
              "open_obligations": ["MysteryGift_CAL2_party_from_SRAM", "BattleTower_and_link_parties",
                                   "runtime_trainer_dispatch_and_battle_completion"]}
    for class_id, label in enumerate(pointers, 1):
        trainers = groups[label]
        if len(trainers) != len(instances[class_id]):
            raise ValueError(f"{label}: source trainer-instance coverage mismatch")
        raw = b"".join(bytes(row["encoded"]) for row in trainers)
        offset = verify_table(ctx, label, raw)
        output["classes"][str(class_id)] = display_name(class_names[class_id - 1])
        output["named_trainers"][str(class_id)] = {}
        output["parties"][str(class_id)] = {}
        for trainer_id, trainer in enumerate(trainers, 1):
            encoded = bytes(trainer.pop("encoded"))
            trainer.update(id=trainer_id, class_id=class_id,
                           constant=instances[class_id][trainer_id - 1],
                           rom={"flat": offset, "length": len(encoded), "expected_hex": encoded.hex()},
                           runtime_party_source="SRAM_OVERRIDE" if classes.get("CAL") == class_id and trainer_id == 2 else "ROM_TABLE")
            output["named_trainers"][str(class_id)][str(trainer_id)] = trainer["name"]
            output["parties"][str(class_id)][str(trainer_id)] = trainer
            offset += len(encoded)
    return output


def main(argv=None):
    return run_cli(argv, build, "trainers.json")


if __name__ == "__main__":
    raise SystemExit(main())
