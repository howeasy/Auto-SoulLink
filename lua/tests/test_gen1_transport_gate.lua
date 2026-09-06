-- Exercise the real LuaSocket DLL against a local fragmented TCP peer. No game
-- memory transformations or production dispatcher are involved in this wire gate.
local ROOT=SLINK_ROOT or os.getenv('SLINK_ROOT')
local G=dofile(ROOT..'/lua/tests/gatelib.lua')
local t=G.start("test_gen1_transport_gate",{no_boot=true})
local C=require('connector')
local port=assert(tonumber(os.getenv('SLINK_TRANSPORT_PORT')))
local token=assert(os.getenv('SLINK_TRANSPORT_TOKEN'))
-- Multibyte glyphs deliberately cross the fixed read/send byte boundaries.
local payload=token..':'..string.rep('é12345678',30000)
local expected_long='R'..string.rep('éabc',40000)
local stage,held,number,long_seen,survived,ready='flood',0,0,false,false,false
local outgoing_progress,maximum_queue=0,0
local ok,err=pcall(function()
    C.init('127.0.0.1',port)
    assert(C.send(payload))
    for frame=1,30000 do
        C.pump()
        local status=C.queue_status()
        maximum_queue=math.max(maximum_queue,status.receive_lines)
        assert(status.receive_lines<=status.max_queue_lines,'receive message bound')
        assert(status.receive_bytes<=status.max_queue_bytes,'receive byte bound')
        assert(status.partial_receive_bytes<=status.max_line,'partial frame bound')
        assert(status.ready_receive_bytes<=status.max_line,'completed pending frame bound')
        assert(status.pending_receive_bytes<=status.read_chunk,'chunk remainder bound')
        if stage=='flood' then
            local progress=status.send_lines==0 and #payload+1 or status.send_offset
            assert(progress>=outgoing_progress and progress-outgoing_progress<=status.io_budget,'absolute send offset/budget')
            outgoing_progress=progress
            if status.receive_lines>=status.max_queue_lines then held=held+1 end
            -- Deliberately stop consuming while the peer floods us. The socket
            -- pump must remain bounded and responsive until consumers resume.
            if held>=60 then stage='drain' end
        elseif stage=='drain' then
            while true do
                local line=C.receive()
                if not line then break end
                if number<1000 then
                    assert(line=='n:'..number,'line order/fidelity')
                    number=number+1
                elseif not long_seen then
                    assert(line==expected_long,'fragmented long-line fidelity');long_seen=true
                elseif not survived then
                    assert(line=='survived','oversized line tail must never be delivered');survived=true
                else
                    assert(line=='ready','end of first stream');ready=true;stage='stale';break
                end
            end
        elseif stage=='stale' then
            if status.receive_lines>0 then
                C.disconnect()
                t.check('complete stale response is discarded on disconnect',C.receive()==nil and C.queue_status().receive_lines==0)
                C.init('127.0.0.1',port)
                stage='fresh'
            end
        elseif stage=='fresh' then
            local line=C.receive()
            if line then
                assert(line=='fresh:'..token,'new connection received stale or mixed bytes')
                assert(C.send('ack:'..token))
                stage='ack'
            end
        elseif stage=='ack' and status.send_lines==0 then
            t.check('all 1000 queued responses retain order',number==1000)
            t.check('real long frame survives fragmentation',long_seen)
            t.check('oversized frame is skipped through its delimiter',survived and ready)
            t.check('receive backpressure reached the declared cap',maximum_queue==status.max_queue_lines)
            t.check('real partial sends covered the full outbound frame',outgoing_progress==#payload+1)
            stage='done';break
        end
        t.step()
    end
    assert(stage=='done','transport exchange did not complete: '..stage)
end)
C.disconnect()
t.check('real LuaSocket exchange completed',ok,tostring(err))
t.finish()
