"""The CONTINUE boot witness: five source-pinned sites in order, save file status 2, same-SP
returns and jumps, published once under a held frame. Nothing here grants anything."""
import json

import pytest

from pathlib import Path

from server.gen1_bootstrap_receipt import DATA
from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime  # noqa: F401

ORDER = ("load", "loaded", "chose", "pressed", "enter")
CONTINUE = json.loads((Path(__file__).resolve().parents[2] / "data/games/gen1_rby/continue_sites.json").read_text())
# Every New Game receipt already journaled carries this hash and is re-verified against it on
# reopen (gen1_bootstrap_receipt), so CONTINUE support lives in its own file and never moves it.
NEW_GAME_SOURCE_SHA256 = "e8b35f43f2429dd69a6e22a76b99958973b53c572da1780e5907f8624cc67551"


@pytest.fixture
def probe(runtime):  # noqa: F811
    start(runtime)
    runtime.globals().data_json = json.dumps(CONTINUE)
    runtime.execute("""
        package.loaded.gen1_continue_sites=assert(JSON.decode(data_json))
        profile=JSON.decode(data_json).titles.yellow;sites=profile.sites;profile_sha=JSON.decode(data_json).sha256
        rom={};bus={};hooks={};frame=100;pc=0;sp=0xDFFE;regA=2;held=true
        scope={context_generation=string.rep('a',32),physical_instance=string.rep('1',32)}
        hash=profile.clean_sha1
        memory={read_u8=function(a,d)return (d=='ROM' and rom[a] or bus[a])or 0 end}
        gameinfo={getromhash=function()return hash end}
        emu={framecount=function()return frame end,getregister=function(k)return k=='PC' and pc or k=='A' and regA or sp end}
        event={on_bus_exec=function(fn,a,name)hooks[name]=fn;return name end,
            unregisterbyid=function(name)hooks[name]=nil end}
        for kind,site in pairs(sites)do
            for i=1,#site.expected_hex,2 do
                local v=tonumber(site.expected_hex:sub(i,i+1),16)
                rom[site.rom_offset+(i-1)/2]=v;bus[site.address+(i-1)/2]=v
            end
        end
        function create()return require('gen1_continue_observer').new({variant='yellow',final_sha1=hash,
            owned=function()return scope end,held=function()return held end})end
        probe=create()
        function fire(kind)
            local site=sites[kind];pc=site.address;bus[profile.bank_address]=site.bank;frame=frame+10
            hooks['slink-continue-'..kind]()
        end
        function boot()fire('load');fire('loaded');fire('chose');fire('pressed');fire('enter')end
    """)
    return runtime


def test_the_ordered_witness_is_published_once_and_detached(probe):
    probe.execute("""
        assert(probe.peek()==nil);fire('load');fire('loaded');assert(probe.peek()==nil and probe.status().loaded)
        fire('chose');fire('pressed');assert(probe.peek()==nil)
        fire('enter');local result=probe.peek()
        assert(result.schema=='rby-continue-receipt-v1' and result.source_sha256==profile_sha and result.loaded.status==2 and result.load.sp==result.loaded.sp)
        assert(result.load.frame<result.loaded.frame and result.chose.frame<result.pressed.frame and result.pressed.frame<result.enter.frame)
        assert(result.load.bank==sites.load.bank and result.enter.pc==sites.enter.address)
        result.enter.frame=1;assert(probe.peek().enter.frame~=1)
        probe.close();assert(next(hooks)==nil);assert(not pcall(probe.peek))
    """)


def test_backing_out_of_the_continue_screen_restarts_the_choice_only(probe):
    probe.execute("""
        fire('load');fire('loaded');fire('chose');fire('pressed')
        fire('chose');assert(probe.status().chosen and probe.peek()==nil)   -- B on the info screen, chose again
        fire('pressed');fire('enter');assert(probe.peek().enter.frame==frame)
    """)


@pytest.mark.parametrize(
    "fault",
    [
        "enter_first",
        "chose_before_loaded",
        "pressed_without_choice",
        "enter_without_confirmation",
        "loaded_twice",
        "bad_checksum",
        "load_stack",
        "jump_stack",
        "restart",
        "context",
        "rom",
        "instruction",
        "unheld",
    ],
)
def test_continue_observer_refuses_disorder_bad_status_lost_ownership_or_changed_sites(probe, fault):
    code = {
        "enter_first": "fire('enter')",
        "chose_before_loaded": "fire('load');fire('chose')",
        "pressed_without_choice": "fire('load');fire('loaded');fire('pressed')",
        "enter_without_confirmation": "fire('load');fire('loaded');fire('chose');fire('enter')",
        "loaded_twice": "fire('load');fire('loaded');fire('loaded')",
        "bad_checksum": "regA=1;fire('load');fire('loaded')",
        "load_stack": "fire('load');sp=sp-2;fire('loaded')",
        "jump_stack": "fire('load');fire('loaded');fire('chose');fire('pressed');sp=sp-2;fire('enter')",
        "restart": "boot();fire('load')",
        "context": "scope.context_generation='changed'",
        "rom": "hash=string.rep('f',40)",
        "instruction": "bus[sites.chose.address]=0;fire('load');fire('loaded');fire('chose')",
        "unheld": "boot();held=false",
    }[fault]
    probe.execute(code + ";assert(not pcall(probe.peek))")
    if fault not in {"context", "rom", "unheld"}:
        probe.execute("assert(probe.status().failed or not probe.status().complete)")


def test_changed_rom_anchor_refuses_installation(probe):
    probe.execute("""
        rom[sites.load.rom_offset]=0
        local ok,why=pcall(create);assert(not ok and tostring(why):find('continue ROM anchor differs: load'))
    """)


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_every_pinned_site_survives_the_canonical_companion_patch(variant):
    """The observers compare each site against the RUNNING ROM, which is the companion-patched
    cartridge, not the clean one the generator pinned from: every New Game and CONTINUE site must
    read the same bytes at the same offset in the built canonical artifact."""
    from server.gen1_cartridge_profiles import companion_profiles
    from tools.build_gen1_companion import ROOT

    manifest = companion_profiles()[variant]["manifest"]
    final = (ROOT / manifest["output"]).read_bytes()
    sites = {**DATA["titles"][variant]["sites"], **CONTINUE["titles"][variant]["sites"]}
    assert set(sites) == {"begin", "end", *ORDER}
    for kind, site in sites.items():
        expected = bytes.fromhex(site["expected_hex"])
        assert final[site["rom_offset"] : site["rom_offset"] + len(expected)] == expected, (variant, kind)


def test_new_game_receipts_keep_verifying_against_the_unchanged_bootstrap_source():
    """A journaled New Game receipt stores the bootstrap source hash and is re-verified against
    DATA["sha256"] on every reopen: adding CONTINUE support must not move it."""
    from server.gen1_bootstrap_receipt import validate
    from server.protocol_journal import JournalError

    assert DATA["sha256"] == NEW_GAME_SOURCE_SHA256
    assert CONTINUE["schema"] == "rby-continue-sites-v1" and CONTINUE["sha256"] != DATA["sha256"]
    assert set(DATA["titles"]["yellow"]) == {"source_commit", "clean_sha1", "bank_address", "fields", "sites"}
    receipt = {"schema": "rby-bootstrap-receipt-v1", "source_sha256": CONTINUE["sha256"], "variant": "yellow",
               "context_generation": "a" * 32, "physical_instance": "1" * 32, "final_sha1": DATA["titles"]["yellow"]["clean_sha1"],
               "begin": {"frame": 1, "pc": 0, "bank": 1, "sp": 0}, "end": {"frame": 2, "pc": 0, "bank": 1, "sp": 0, "point": {}}}
    with pytest.raises(JournalError, match="bootstrap source or physical context differs"):
        validate(receipt, variant="yellow", identity={}, context_generation="a" * 32, physical_instance="1" * 32,
                 final_sha1=receipt["final_sha1"], source={}, frame=10)
    receipt["source_sha256"] = DATA["sha256"]
    with pytest.raises(JournalError, match="bootstrap execution site differs"):  # past the source check
        validate(receipt, variant="yellow", identity={}, context_generation="a" * 32, physical_instance="1" * 32,
                 final_sha1=receipt["final_sha1"], source={}, frame=10)
