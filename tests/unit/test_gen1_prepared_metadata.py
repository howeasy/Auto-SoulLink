"""Prepared metadata requires the exact loaded hash and keeps the default catalog closed."""
import json
from pathlib import Path
import pytest
from lupa.lua54 import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]


def runtime(variant="yellow"):
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.globals().package.path=(ROOT/"lua/?.lua").as_posix()+";"+(ROOT/"data/games/gen1_rby/?.lua").as_posix()+";"+lua.globals().package.path
    lua.execute("JSON=require('json_codec');Profiles=require('gen1_runtime_profiles');actual_hash=string.rep('f',40);gameinfo={getromhash=function()return actual_hash end}")
    metadata={"variant":variant,"final_rom_sha1":"f"*40,"content_profile_schema":"gen1-rby-scanned-companion-content-v1",
        "content_profile_hash":"e"*64,"patch_version":3,"party_codec":"gen1-rby-party-v1",
        "capabilities":{"panel":variant!="yellow","pc_trade":True,"sfx":False}}
    return lua,metadata


@pytest.mark.parametrize("variant",["red","blue","yellow"])
def test_prepared_metadata_is_explicit_exact_and_detached(variant):
    lua,metadata=runtime(variant);lua.globals().variant=variant
    assert lua.eval("Profiles.metadata(variant)")[0] is None
    lua.globals().payload=json.dumps(metadata)
    lua.execute("prepared=assert(JSON.decode(payload));result=assert(Profiles.metadata(variant,prepared));result.capabilities.sfx=true")
    assert lua.eval("prepared.capabilities.sfx") is False
    assert json.loads(lua.eval("JSON.encode(assert(Profiles.metadata(variant,prepared)))"))==metadata


@pytest.mark.parametrize("field,value",[("variant","orange"),("final_rom_sha1","a"*40),
    ("content_profile_hash","bad"),("patch_version",2),("party_codec","gen2"),("unknown",True)])
def test_wrong_prepared_identity_or_shape_is_refused(field,value):
    lua,metadata=runtime();metadata[field]=value;lua.globals().payload=json.dumps(metadata)
    assert lua.eval("Profiles.metadata('yellow',assert(JSON.decode(payload)))")[0] is None


@pytest.mark.parametrize("field,value",[("panel",True),("sfx",True),("pc_trade",False),("unknown",True)])
def test_yellow_cannot_inherit_unverified_capabilities(field,value):
    lua,metadata=runtime();metadata["capabilities"][field]=value;lua.globals().payload=json.dumps(metadata)
    assert lua.eval("Profiles.metadata('yellow',assert(JSON.decode(payload)))")[0] is None


def test_unknown_variant_is_not_admitted_even_with_matching_claims():
    lua,metadata=runtime("orange");lua.globals().payload=json.dumps(metadata)
    assert lua.eval("Profiles.metadata('orange',assert(JSON.decode(payload)))")[0] is None
