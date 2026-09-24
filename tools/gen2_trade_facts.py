"""P4.3e: source/overlay facts the native Gen 2 trade duo driver needs (lua/tests/duo/gen2_trade.lua).

The runner passes ``json.dumps(trade_facts(title))`` as SLINK_GEN2_TRADE_FACTS. Everything is derived from the
pinned decomps (maps, texts), the published overlay (patch/dist UPS applied to the clean build) and its
data/gen2/<title>_slink.sym; nothing here comes from a screenshot.

  maps      Pokecenter2F and CherrygrovePokecenter1F (tools/gen2_fixtures._map_facts shape); the Route 29 and
            Cherrygrove legs are the U1f PC legs the runner already passes (SLINK_GEN2_U1_FACTS pc.to_pc)
  legs      CherrygrovePokecenter1F -> the stairs warp to POKECENTER_2F (C/G maps/CherrygrovePokecenter1F.asm:75,
            a stair tile fires on arrival); Pokecenter2F -> the trade receptionist's stand tile
  stand     one tile below LinkReceptionistScript_Trade's object_event (C maps/Pokecenter2F.asm:1039,
            G/S :590, (5, 2) facing down), faced Up; the overlay only repoints that object's script
            (patch/gen2/src/trade_receptionist.asm)
  prompts   yes/no anchors, each the row still on screen when its YesNoBox opens:
              trade_intro  Text_TradeReceptionistIntro's last row "trade?" (C :831-841, G/S :418-428)
              must_save    the proposer's forced pre-trade save, vanilla Text_MustSaveGame "link, you must"
                           (C :860-864, G/S :447-451; the overlay script, patch/gen2/src/trade_receptionist.asm)
              slink_trade  the proposer's SlinkTradeConfirmText "SLINK TRADE?" (patch/gen2/src/trade_service.asm)
              trade_offer  the responder's SlinkTradeOfferText "Trade <own>" / "for <incoming>?"
              trade_save   the responder's SlinkTradeMustSaveText "you must save" (then native Link_SaveGame)
            the native overwrite yes/no and its text are the qualification facts' save_overwrite(_text)
  symbols   the overlay's code sites (bank, addr, flat ROM offset, first byte of the PATCHED ROM) and RAM
            symbols the driver hooks/reads; sym_sha256 binds the file they came from
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CODE = ("SlinkTradeEntry", "SlinkTradePromptEntry", "SlinkTradeWaitAck", "SlinkTradeWaitApply",
        "SlinkTradeApplyPickup", "SlinkTradeCommit", "SlinkTradeWaitRelease", "SlinkTradeExit",
        "RemoveMonFromPartyOrBox", "TradeAnimation", "TradeAnimationPlayer2", "AddTempmonToParty",
        "EvolvePokemon", "EvolutionAnimation", "SaveAfterLinkTrade", "Reset",
        # refinement 2 (TRADE_CONTROL): the decline/timeout/D3/reset triggers and their proof sites
        "SlinkTradePublishDone", "SlinkTradeWaitApply.wait", "SlinkTradeItemAllowed", "StartTitleScreen",
        # reset_commit: the native save returned (B=0 at .cleanup), before DONE is published
        "SlinkTradeCommit.cleanup",
        # O-31 trade-evolve plant: StartBattle reads wTempWildMonSpecies into wCurPartySpecies (G/S
        # engine/battle/core.asm:7755-7768, C :8026+), after ChooseWildEncounter stored it (wildmons.asm:356-358)
        "StartBattle")
RAM = ("wStackBottom", "wStackTop", "wSlinkMailbox", "wPartyCount", "wPartySpecies", "wPartyMon1",
       "wPartyMonOTs", "wPartyMonNicknames", "wOTPartyCount", "wOTPartySpecies", "wOTPartyMon1",
       "wOTPartyMonOTs", "wOTPartyMonNicknames", "wCurPartyMon",
       "wTempWildMonSpecies", "wOtherTrainerClass", "wBattleMode", "wBattleType", "wMapGroup", "wMapNumber")
# O-31 (owner, "Test-only setup"): the two disclosed plants, derived from the pinned decomps + overlay.
EVOLVER, MAIL = "HAUNTER", "FLOWER_MAIL"
INTRO_ANCHOR, CONFIRM_ANCHOR = "trade?", "SLINK TRADE?"
MUST_SAVE_ANCHOR, OFFER_ANCHOR, TRADE_SAVE_ANCHOR = "link, you must", "Trade ", "you must save"


def trade_facts(title: str, root: Path = ROOT) -> dict:
    from patch.tools.make_ups import ups_apply
    from tools import gen2_fixtures, gen2_source_data
    from tools.rgbds_symbols import parse_symbols, rom_offset

    root = Path(root)
    ctx = gen2_source_data.load_context(title, root=root)
    provenance = json.loads((root / "data/gen2/overlay_provenance.json").read_text(encoding="utf-8"))
    out = provenance["outputs"]["poke" + title]
    rom = ups_apply(ctx.rom, (root / out["ups"]["file"]).read_bytes())
    assert hashlib.sha1(rom).hexdigest() == out["sha1"], f"{title}: applied overlay differs from its pin"
    sym_raw = (root / f"data/gen2/{title}_slink.sym").read_bytes()
    assert hashlib.sha256(sym_raw).hexdigest() == provenance["symbols"][f"{title}_slink.sym"], "overlay sym pin"
    symbols = parse_symbols(sym_raw.decode("utf-8"))

    areas = {row["map_const"]: row for row in gen2_fixtures.build_area_map(ctx).values()}
    by_name = {row["map_name"]: row for row in areas.values()}
    maps = {name: gen2_fixtures._map_facts(ctx, by_name[name], areas)
            for name in ("CherrygrovePokecenter1F", "Pokecenter2F")}
    stairs = next(w for w in maps["CherrygrovePokecenter1F"]["warps"] if w["destination"] == "POKECENTER_2F")
    upstairs = maps["Pokecenter2F"]
    desk = upstairs["objects"]["LinkReceptionistScript_Trade"]
    stand = {"x": desk["x"], "y": desk["y"] + 1}
    assert upstairs["grid"][stand["y"] * upstairs["width"] + stand["x"]] == 1, "receptionist stand tile not floor"

    text = ctx.read_source("maps/Pokecenter2F.asm")
    intro = text.split("Text_TradeReceptionistIntro:", 1)[1].split("done", 1)[0]
    assert f'line "{INTRO_ANCHOR}"' in intro, "receptionist intro anchor left the source"
    service = (root / "patch/gen2/src/trade_service.asm").read_text(encoding="utf-8")
    assert f'text "{CONFIRM_ANCHOR}"' in service, "SLINK TRADE confirm anchor left the overlay source"
    must = text.split("Text_MustSaveGame:", 1)[1].split("done", 1)[0]
    assert f'line "{MUST_SAVE_ANCHOR}"' in must, "Text_MustSaveGame anchor left the source"
    assert "writetext Text_MustSaveGame" in (root / "patch/gen2/src/trade_receptionist.asm").read_text(encoding="utf-8")
    offer = service.split("SlinkTradeOfferText:", 1)[1].split("done", 1)[0]
    assert f'text "{OFFER_ANCHOR}"' in offer, "responder offer anchor left the overlay source"
    save = service.split("SlinkTradeMustSaveText:", 1)[1].split("done", 1)[0]
    assert f'line "{TRADE_SAVE_ANCHOR}"' in save, "responder must-save anchor left the overlay source"

    # the trade evolver: EVOLVE_TRADE with no item (data/pokemon/evos_attacks.asm), no wild held items (so no
    # Everstone roll: data/pokemon/base_stats/haunter.asm `db NO_ITEM, NO_ITEM`), harmless at Route 29 levels
    species = gen2_fixtures.const_block(ctx.read_source("constants/pokemon_constants.asm"), "BULBASAUR")
    evos = ctx.read_source("data/pokemon/evos_attacks.asm").split(EVOLVER.title() + "EvosAttacks:", 1)[1]
    target = evos.split("db EVOLVE_TRADE, -1, ", 1)[1].split()[0]
    assert evos.split("\n", 2)[1].strip().startswith("db EVOLVE_TRADE, -1,"), "evolver is not a plain trade evolver"
    base = ctx.read_source(f"data/pokemon/base_stats/{EVOLVER.lower()}.asm")
    assert "db NO_ITEM, NO_ITEM ; items" in base, "evolver can carry a wild held item"
    # the D3 mail item: a mail id in the pack's items.json and 0 in the overlay's own SlinkTradeAllowedItems table
    items = json.loads((root / f"data/games/gen2_{title}/items.json").read_text(encoding="utf-8"))
    mail = gen2_fixtures.const_block(ctx.read_source("constants/item_constants.asm"), "NO_ITEM")[MAIL]
    table = symbols["SlinkTradeAllowedItems"]
    assert mail in items["mail_ids"] and rom[rom_offset(table.bank, table.address) + mail] == 0, "mail item not refused"
    plants = {"evolve_species": {"name": EVOLVER, "id": species[EVOLVER]}, "evolves_to": {"name": target, "id": species[target]},
              "mail_item": {"name": MAIL, "id": mail}}

    code = {}
    for name in CODE:
        s = symbols[name]
        flat = rom_offset(s.bank, s.address)
        code[name] = {"bank": s.bank, "addr": s.address, "flat": flat, "hex": rom[flat:flat + 1].hex()}
    ram = {name: {"bank": symbols[name].bank, "addr": symbols[name].address} for name in RAM}
    return {"schema": "gen2-trade-facts-v1", "title": title, "overlay_sha1": out["sha1"], "base_sha1": out["base_sha1"],
            "sym_sha256": provenance["symbols"][f"{title}_slink.sym"],
            "maps": maps,
            "legs": {"CherrygrovePokecenter1F": {"kind": "warp", "tile": {"x": stairs["x"], "y": stairs["y"]},
                                                 "carpet": stairs["carpet"]},
                     "Pokecenter2F": {"kind": "stand"}},
            "stand": stand, "receptionist": {"x": desk["x"], "y": desk["y"]},
            "prompts": {"trade_intro": [INTRO_ANCHOR], "slink_trade": [CONFIRM_ANCHOR], "must_save": [MUST_SAVE_ANCHOR],
                        "trade_offer": [OFFER_ANCHOR], "trade_save": [TRADE_SAVE_ANCHOR]},
            "code": code, "ram": ram, "plants": plants}


if __name__ == "__main__":
    print(json.dumps(trade_facts(sys.argv[1] if len(sys.argv) > 1 else "gold"), indent=1)[:4000])
