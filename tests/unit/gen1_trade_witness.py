"""Producer-shaped MODEL of trade_service.asm's saved frame and first CopyData."""
def plant_restore(rom, profile):
    ram, derived = profile["ram"], profile["derived"]
    lease = ram["wSerialPartyMonsPatchList"]
    backup = ram["wEnemyMons"] + derived["battle_struct_size"]
    service = profile.get("trade", {}).get("service", {"bank": 63, "addr": 0x4500})
    def word(value):
        return value.to_bytes(2, "little")

    code = (b"\x21" + word(lease) + bytes.fromhex("2A572A5FD5") * 8
            + b"\x21" + word(backup) + b"\x11" + word(lease)
            + bytes.fromhex("011000CD") + word(0xAE if profile.get("trade") else 0xB5)
            + bytes.fromhex("F80A7EFE0320"))
    # Deliberately relocated within the service: tests must not assume a fixed PC.
    offset = service["bank"] * 0x4000 + service["addr"] - 0x4000 + 0x28
    rom[offset-15:offset] = (b"\xfa" + word(lease+6) + b"\x47\xfa" + word(lease+7)
                             + b"\xb8\xc8\xfa" + word(lease+9) + b"\xea" + word(0xCD3D))
    rom[offset:offset + len(code)] = code
    return bytes(rom)


def consume_world(world):
    trade = world.client.trade
    published = bytes(trade.expected[i] for i in range(1, 17))
    base = world.ram["wSerialPartyMonsPatchList"]
    backup = world.ram["wEnemyMons"] + world.d["battle_struct_size"]
    sp = 0xDE80
    world.bus[base:base + 16] = world.bus[backup:backup + 16]
    world.bus[sp:sp + 16] = published[::-1]
    site = trade.pickup_site(lambda addr: world.rom[int(addr)])
    world.bus[world.ram["hLoadedROMBank"]] = site.bank
    world.regs["PC"], world.regs["SP"] = site.address, sp
    world.hooks["SLink-gen1-trade_consumed"][0]()


def enter_world(world):
    # Exercise the old observer too when revert-checking against R2.
    hook = world.hooks.get("SLink-gen1-trade_request")
    if hook is None:
        from tests.unit.test_gen1_trade_poll import _fire
        _fire(world)
        return
    pickup = world.client.trade.pickup_site(lambda addr: world.rom[int(addr)])
    world.bus[world.ram["hLoadedROMBank"]] = pickup.bank
    world.regs["PC"] = pickup.address - 55
    hook[0]()
