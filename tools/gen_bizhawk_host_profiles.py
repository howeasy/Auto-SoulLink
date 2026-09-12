"""Export the shared actuator's pinned host facts for the local launch tool."""
import json
from pathlib import Path

from lupa.lua54 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'data/bizhawk_host_profiles.json'


def generated():
    lua=LuaRuntime(unpack_returned_tuples=True)
    module=lua.execute((ROOT/'lua/platform_execution.lua').read_text(encoding='utf-8'))
    profiles={name:dict(module.supported_profile(name).items()) for name in ('gambatte','mgba')}
    return json.dumps({'schema':1,'profiles':profiles},indent=2,sort_keys=True)+'\n'


if __name__=='__main__':TARGET.write_text(generated(),encoding='utf-8')
