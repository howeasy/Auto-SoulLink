"""EXPLODE-BIND controls at the production client and shipped capability boundaries."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit import gen3_world as gw
from tests.unit.test_gen3_client import FOE, KA, live, write_reasons

# Independent source pins: each committed pret .sym, gChosenMoveByBattler/gBattleStruct/
# gBattlerControllerFuncs/PlayerBufferExecCompleted; BattleStruct fields from battle.h.
TITLES = (
    ("gen3_frlg", "firered", 0x02023DC4, 0x02023FE8, 0x03004FE0, 0x0802E33D, 3),
    ("gen3_frlg", "leafgreen", 0x02023DC4, 0x02023FE8, 0x03004FE0, 0x0802E33D, 3),
    ("gen3_emerald", "emerald", 0x02024274, 0x0202449C, 0x03005D60, 0x0805748D, 4),
)


@pytest.mark.parametrize("pack,title,chosen,struct_ptr,controller,completed,standby", TITLES)
def test_clean_title_commits_explosion_and_hands_off_without_zeroing_hp(
        monkeypatch, pack, title, chosen, struct_ptr, controller, completed, standby):
    monkeypatch.setitem(gw.PACK_DIRS, "gen3_emerald", gw.REPO / "data/games/gen3_emerald")
    world = live(pack, title)
    world.battle_ok = True
    world.enter_battle([FOE], active=(0,))
    battle = world.ram["BATTLE_MONS_ADDR"]
    world.poke_int(battle + 0x28, 20, 2)
    world.poke_int(struct_ptr, 0x02020000, 4)
    world.poke_int(0x02020000 + 0x80, 3, 1)  # stale prior menu position must not survive
    world.poke_int(0x02020000 + 0x0C, 0, 1)
    world.command(cmd="force_explode", key=KA)
    world.step()
    assert world._read(chosen, 2) == 153
    assert [world._read(battle + 0x0C + i*2, 2) for i in range(4)] == [153]*4
    assert [world._read(battle + 0x24 + i, 1) for i in range(4)] == [5]*4
    assert world._read(controller, 4) == completed
    # battle_main.c's enum: FR/LG standby=3; Emerald adds STATE_TURN_START_RECORD, so 4.
    assert world._read(world.ram["BATTLE_COMM_ADDR"], 1) == standby
    assert world._read(0x02020000 + 0x80, 1) == 0
    assert world._read(0x02020000 + 0x0C, 1) == 1
    assert world.party_hp(0) == 20 and world._read(battle + 0x28, 2) == 20
    assert not any(addr in (battle + 0x28, battle + 0x29,
                           world.ram["PARTY_BASE"] + 86, world.ram["PARTY_BASE"] + 87)
                   for addr, _, _ in world.writes)
    assert set(write_reasons(world)) == {"battle_commit"}
    assert world.parts.native is None  # no injected or production companion dependency


@pytest.mark.parametrize("title", ("firered", "leafgreen", "emerald"))
def test_title_explode_capability_agrees_with_the_manager(title):
    from server.adapters.gen3_frlge import Gen3Adapter
    from server.manager import option_support

    assert Gen3Adapter(rom_type=title).supports_explode_mode() is True
    assert option_support("explode_mode", [title, title])["ok"] is True


@pytest.mark.parametrize("title", ("firered_ap", "emerald_expansion_28877d73", "crystal"))
def test_explode_opt_in_does_not_enable_other_cartridges(title):
    from server.manager import option_support

    assert option_support("explode_mode", [title, title])["ok"] is False


@pytest.mark.parametrize("pack,title,chosen,struct_ptr,controller,completed,standby", TITLES)
@pytest.mark.parametrize("field", ("effect", "PP"))
def test_each_title_must_prove_explosions_effect_and_pp_in_its_own_rom(
        monkeypatch, pack, title, chosen, struct_ptr, controller, completed, standby, field):
    from tests.unit.test_gen3_write_checkpoint import G, rom_or_skip

    rom_or_skip(pack, title, "clean")
    profile = json.loads((gw.REPO / "data/games" / pack / "profile.json").read_text())["titles"][title]
    offset = (profile["rom"]["BATTLE_MOVES_ADDR"] - G.ROM_BASE
              + 153 * profile["derived"]["BATTLE_MOVE_ENTRY_SIZE"]
              + (profile["derived"]["BATTLE_MOVE_PP_OFFSET"] if field == "PP" else 0))
    real = G.load_rom
    rom = real(pack, title, "clean")
    assert rom[offset] == (5 if field == "PP" else 7)

    def altered(p, t, kind):
        data = real(p, t, kind)
        return data[:offset] + bytes([data[offset] ^ 0xFF]) + data[offset + 1:] if t == title else data

    monkeypatch.setattr(G, "load_rom", altered)
    with pytest.raises(SystemExit, match=rf"battle.handoff.explode.*{field}"):
        G.build_title(pack, title, G.ALL_PACKS[pack][title][0], ("clean",))


@pytest.mark.parametrize("title,env,pin,pack", (
    ("firered", "SLINK_PRET_FIRERED_SRC", "c75f352304d529f6ba92d4f74b9cf8b5c3810788", "gen3_frlg"),
    ("emerald", "SLINK_PRET_EMERALD_SRC", "c65e93f20a5275ab03b07d6f6411096a82a60ffd", "gen3_emerald"),
))
def test_battle_struct_offsets_match_the_pinned_c_layout(tmp_path, title, env, pin, pack):
    source = Path(os.environ.get(env, ""))
    compiler = os.environ.get("SLINK_HOST_GCC") or shutil.which("gcc")
    if not (source / "include/battle.h").is_file() or not compiler:
        pytest.skip("pinned pret source and host GCC required for BattleStruct offsetof control")
    assert subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() == pin
    header = (source / "include/battle.h").read_text()
    prefix = re.search(r"struct BattleStruct\s*\{(.*?\bchosenMovePositions\[MAX_BATTLERS_COUNT\];)", header, re.S)
    assert prefix
    constants = "\n".join((source / "include/constants" / f"{name}.h").read_text()
                          for name in ("battle", "global", "pokemon"))
    declarations = []
    for name in ("MAX_BATTLERS_COUNT", "PARTY_SIZE", "MAX_MON_MOVES", "POKEMON_NAME_LENGTH"):
        values = set(re.findall(rf"^#define\s+{name}\s+(\d+)\b", constants, re.M))
        if not values and name == "MAX_BATTLERS_COUNT":
            enum = re.search(r"enum BattlerId\s*\{[^}]*\bMAX_BATTLERS_COUNT[^}]*\};", constants)
            assert enum
            declarations.append(enum[0] + "\n")
            continue
        assert len(values) == 1, (name, values)
        declarations.append(f'#define {name} {values.pop()}\n')
    # Neither pinned prefix contains a pointer: host and ARM offsets are identical here.
    probe = tmp_path / "battle_prefix.c"
    probe.write_text('#include <stddef.h>\n#include <stdio.h>\n'
                     'typedef unsigned char u8; typedef unsigned char bool8; typedef unsigned short u16;\n'
                     + ''.join(declarations)
                     + 'struct Prefix {' + prefix[1] + '};\n'
                     + 'int main(void) { printf("%u %u\\n", (unsigned)offsetof(struct Prefix, moveTarget), '
                     '(unsigned)offsetof(struct Prefix, chosenMovePositions)); return 0; }\n')
    executable = tmp_path / ("battle_prefix.exe" if os.name == "nt" else "battle_prefix")
    build = subprocess.run([compiler, str(probe), "-o", str(executable)], capture_output=True, text=True)
    assert build.returncode == 0, build.stdout + build.stderr
    offsets = [int(value) for value in subprocess.check_output([str(executable)], text=True).split()]
    assert offsets == [0x0C, 0x80]
    profile = json.loads((gw.REPO / "data/games" / pack / "profile.json").read_text())["titles"][title]
    assert [profile["derived"][key] for key in ("BATTLE_STRUCT_MOVE_TARGET_OFF", "BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF")] == offsets


@pytest.mark.parametrize("pack,title,chosen,struct_ptr,controller,completed,standby", TITLES)
@pytest.mark.parametrize("unqualified", ("doubles", "missing_handoff"))
def test_unqualified_explosion_never_writes_a_partial_commit(
        monkeypatch, pack, title, chosen, struct_ptr, controller, completed, standby, unqualified):
    monkeypatch.setitem(gw.PACK_DIRS, "gen3_emerald", gw.REPO / "data/games/gen3_emerald")
    world = live(pack, title)
    world.battle_ok = True
    world.enter_battle([FOE], active=(0,), doubles=unqualified == "doubles")
    world.poke_int(world.ram["BATTLE_MONS_ADDR"] + 0x28, 20, 2)
    world.poke_int(struct_ptr, 0x02020000, 4)
    if unqualified == "missing_handoff":
        world.parts.policy.handoff_entry = world.lua.eval("function() return nil end")
    world.command(cmd="force_explode", key=KA)
    world.step()
    assert world.writes == []
    assert world.party_hp(0) == 20
