"""Single owner arbitration of held and native command services."""

from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def fixture():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.execute("""
        package.path=root..'/lua/?.lua;'..package.path
        log={};requests={};accepted={};revoked={};updated={}
        function service(kind)
            local s={handles=function(body)return body.cmd==kind end,
                ready=function()return true,kind end,adapter={},operations={}}
            for _,name in ipairs({'prepare','classify','apply','receipt'})do
                s.adapter[name]=function(body,value)return kind,name,value end
            end
            s.update_control=function()updated[kind]=(updated[kind]or 0)+1 end
            s.operations.request=function()return requests[kind]end
            s.operations.accept=function(packet)accepted[kind]=packet or 'withheld';return true end
            s.operations.authorize_apply=function()return true,kind end
            s.operations.revoke=function()revoked[kind]=true;if fail_revoke==kind then error('revoke failed')end end
            s.operations.status=function()return {kind=kind}end
            return s
        end
        held=service('held');native=service('native')
        Router=require('command_service_router');router=Router.new({held,native})
    """)
    return lua


def test_unique_command_routes_and_unknown_commands_stay_unavailable():
    lua = fixture()
    lua.execute("""
        for _,kind in ipairs({'held','native'})do
            local yes,why=router.ready({cmd=kind});assert(yes and why==kind)
            local a,b,c=router.adapter.apply({cmd=kind},'intent')
            assert(a==kind and b=='apply' and c=='intent')
            local permit,source=router.operations.authorize_apply({cmd=kind})
            assert(permit and source==kind)
        end
        assert(router.ready({cmd='unknown'})==false)
        assert(router.operations.authorize_apply({cmd='unknown'})==false)
    """)
    with pytest.raises(LuaError, match="no selected service"):
        lua.execute("router.adapter.apply({cmd='unknown'})")
    lua.execute("native.handles=held.handles")
    with pytest.raises(LuaError, match="multiple services"):
        lua.execute("router.adapter.apply({cmd='held'})")


def test_discovery_updates_all_services_and_response_stays_with_request_owner():
    lua = fixture()
    lua.execute("""
        requests.native={fixture=true}
        assert(router.operations.request({},{}).fixture)
        assert(updated.held==1 and updated.native==1)
        requests.native=nil;requests.held={fixture=true}
        assert(router.operations.accept({grant=true}))
        assert(accepted.native.grant and accepted.held==nil)
        assert(router.operations.request({},{}).fixture)
        assert(router.operations.accept(nil));assert(accepted.held=='withheld')
    """)
    with pytest.raises(LuaError, match="unsolicited"):
        lua.execute("router.operations.accept({grant=true})")


def test_pending_request_cannot_be_replaced_and_revoke_reaches_every_service():
    lua = fixture()
    lua.execute("requests.held={fixture=true};router.operations.request({},{})")
    with pytest.raises(LuaError, match="already in flight"):
        lua.execute("router.operations.request({},{})")
    lua.execute("fail_revoke='held'")
    with pytest.raises(LuaError, match="revoke failed"):
        lua.execute("router.operations.revoke('lost owner')")
    lua.execute(
        "assert(revoked.held and revoked.native);requests.held=nil;requests.native={fixture=true};router.operations.request({},{})"
    )
