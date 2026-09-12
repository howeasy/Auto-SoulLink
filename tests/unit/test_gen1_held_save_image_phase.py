"""No-op saves request the same phase that staged classification executes."""

from lupa.lua54 import LuaRuntime


def test_equal_preimage_postimage_requires_save_phase_without_apply():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        package.path='./lua/?.lua;'..package.path
        package.loaded.gen1_full_save={}
        package.loaded.gen1_full_save_layout={yellow={}}
        local phases={command='storage_apply',save_phase='storage_save',repair_phase='storage_repair'}
        local image=require('gen1_held_save_image').new({variant='yellow',sha=function(value)return value end},phases)
        assert(image.phase('same',{before_digest='same',after_digest='same'})=='storage_save')
        assert(image.phase('before',{before_digest='before',after_digest='after'})=='storage_apply')
        assert(image.phase('after',{before_digest='before',after_digest='after'})=='storage_save')
    """)
