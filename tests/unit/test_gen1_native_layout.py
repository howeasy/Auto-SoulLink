"""Native execution addresses cannot be replaced while retaining a ROM hash label."""
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime


@pytest.fixture
def lua():
    value=LuaRuntime(unpack_returned_tuples=True)
    value.globals().root=Path(__file__).resolve().parents[2].as_posix()
    value.execute("""
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=require('json_codec');service=require('gen1_native_runtime')
        profiles=require('gen1_companion_profiles').profiles
        function selected(variant)
            manifest=assert(JSON.decode(JSON.encode(profiles[variant].manifest)))
            return service.validate_manifest(manifest,variant)
        end
    """)
    return value


@pytest.mark.parametrize("variant",["red","blue","yellow"])
def test_qualified_layout_is_accepted_independently_of_admitted_output_hash(lua,variant):
    assert lua.globals().selected(variant)
    # Approved UPR changes the final hash, not the execution layout. Loaded-ROM
    # and metadata admission are checked separately by the native runtime.
    lua.globals().manifest.final_sha1="f"*40
    assert lua.globals().service.validate_manifest(lua.globals().manifest,variant)


@pytest.mark.parametrize("field",["ram","foreground","native_calls","readback","receptionist","entry","payload_sha256","test_probe"])
def test_changed_native_layout_is_rejected_before_any_host_or_write_adapter(lua,field):
    assert lua.globals().selected("yellow")
    lua.globals().field=field
    lua.execute("manifest[field]={}")
    with pytest.raises(Exception,match="layout differs"):
        lua.globals().service.validate_manifest(lua.globals().manifest,"yellow")
