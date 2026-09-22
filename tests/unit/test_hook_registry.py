"""Neutral hook ownership, ordered queues and transaction/error controls."""
from pathlib import Path

from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class World:
    def __init__(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.registry = self.lua.eval("dofile")((ROOT / "lua/hook_registry.lua").as_posix())
        self.state, self.options = self.lua.eval("""function()
            local s={registered={},removed={},callbacks={},validated=0,sequence=0}
            local o={owner='test-owner',max_pending=2,sites={{id='a'},{id='b'}},
                validate=function(site)
                    s.validated=s.validated+1
                    if site.id==s.bad_site then error('bad site') end
                    return {id=site.id}
                end,
                register=function(site,fn,name)
                    assert(s.validated==2, 'registration preceded all-site validation')
                    local n=#s.registered+1
                    if n==s.fail_at then return nil end
                    s.registered[n]=name;s.callbacks[site.id]=fn
                    if s.fire_during_registration then fn() end
                    return n
                end,
                unregister=function(id)
                    s.removed[#s.removed+1]=id
                    if id==s.fail_remove then return false end
                    return true
                end,
                valid_handle=function(id) return type(id)=='number' and id>0 end,
                capture=function(site)
                    if s.capture_error then error('capture exploded') end
                    if s.drop then return nil end
                    s.sequence=s.sequence+1
                    return {kind=site.id,sequence=s.sequence}
                end,
                on_event=function(event)
                    if s.handler_error then error('handler exploded') end
                end,
            }
            return s,o
        end""")()

    def new(self):
        out = self.registry.new(self.options)
        return out if isinstance(out, tuple) else (out, None, None)


def test_all_validation_precedes_registration_and_failure_rolls_back_only_owned_handles():
    w = World()
    w.state.bad_site = "b"
    service, error, _ = w.new()
    assert service is None and "bad site" in error and len(w.state.registered) == 0
    w = World()
    w.state.fail_at = 2
    service, error, _ = w.new()
    assert service is None and "registration failed" in error
    assert list(w.state.removed.values()) == [1]


def test_duplicate_owner_refused_until_owned_handles_close_and_stale_callback_is_inert():
    w = World()
    service, error, _ = w.new()
    assert error is None
    stale = w.state.callbacks.a
    other, error, _ = w.new()
    assert other is None and "owner" in error and len(w.state.registered) == 2
    service.close(service)
    stale()
    assert service.status(service).pending == 0
    w.state.registered, w.state.removed = w.lua.table(), w.lua.table()
    w.state.validated = 0
    assert w.new()[0] is not None


def test_callback_queue_order_overflow_and_error_latches_do_not_reset_on_drain():
    w = World()
    service = w.new()[0]
    w.state.callbacks.b()
    w.state.callbacks.a()
    queued = service.drain(service)
    assert [queued[i].kind for i in (1, 2)] == ["b", "a"]
    for _ in range(3):
        w.state.callbacks.a()
    assert "buffer full" in service.status(service).failed
    assert len(service.drain(service)) == 2
    w.state.callbacks.a()
    assert len(service.drain(service)) == 0
    w = World()
    service = w.new()[0]
    w.state.capture_error = True
    w.state.callbacks.a()
    assert "capture exploded" in service.status(service).failed
    assert service.status(service).pending == 0


def test_handler_error_is_recorded_not_a_kill_switch_and_registration_callbacks_are_suppressed():
    w = World()
    w.state.fire_during_registration = True
    service = w.new()[0]
    assert service.status(service).pending == 0
    w.state.handler_error = True
    w.state.callbacks.a()
    assert "handler exploded" in service.status(service).handler_error
    assert len(service.drain(service)) == 1
    w.state.handler_error = False
    w.state.callbacks.a()
    assert len(service.drain(service)) == 1
    assert "handler exploded" in service.status(service).handler_error
    assert service.status(service).failed is None


def test_cleanup_failure_retains_owner_and_allows_explicit_retry():
    w = World()
    w.state.fail_at, w.state.fail_remove = 2, 1
    service, error, failed = w.new()
    assert service is None and "cleanup" in error and failed is not None
    assert len(failed.status(failed).cleanup_errors) == 1
    assert "owner" in w.new()[1]
    w.state.fail_remove = None
    assert failed.close(failed) is True
    w.state.registered, w.state.removed = w.lua.table(), w.lua.table()
    w.state.validated, w.state.fail_at = 0, None
    assert w.new()[0] is not None


def test_explicit_hook_names_cannot_collide_across_owners():
    w = World()
    w.options.name_for_site = w.lua.eval("function(site) return 'legacy-'..site.id end")
    assert w.new()[0] is not None
    w.options.owner = "second-owner"
    w.state.validated = 0
    service, error, _ = w.new()
    assert service is None and "name" in error and len(w.state.registered) == 2


def test_close_attempts_every_handle_even_when_first_unregister_fails():
    w = World()
    service = w.new()[0]
    w.state.fail_remove = 2
    assert service.close(service) is False
    assert list(w.state.removed.values()) == [2, 1]
    assert service.status(service).closed is True
    w.state.fail_remove = None
    assert service.close(service) is True
    assert list(w.state.removed.values()) == [2, 1, 2]


def test_validated_descriptors_and_queued_events_are_not_mutable_callback_aliases():
    w = World()
    w.options.capture = w.lua.eval("""function(site)
        local event={kind=site.id}
        site.id='rewritten'
        return event
    end""")
    w.options.on_event = w.lua.eval("function(event) event.kind='handler-rewritten' end")
    service = w.new()[0]
    w.options.sites[1].id = "caller-rewritten"
    w.state.callbacks.a()
    w.state.callbacks.a()
    queued = service.drain(service)
    assert [queued[i].kind for i in (1, 2)] == ["a", "a"]


def test_nonfinite_capacity_and_sparse_sites_refuse_without_registration():
    w = World()
    w.options.max_pending = float("inf")
    assert w.new()[0] is None and len(w.state.registered) == 0
    w = World()
    w.options.sites[3], w.options.sites[2] = w.options.sites[2], None
    assert w.new()[0] is None and len(w.state.registered) == 0
