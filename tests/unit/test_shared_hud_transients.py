"""Shared HUD pixels and semantic notice fit on the GB viewport."""

from pathlib import Path

from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def test_link_notice_fits_and_expires_on_retained_gui_canvas():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.execute(r"""
        pixels={};texts={};clears=0
        -- Normal source-over drawing: an alpha-zero box leaves prior pixels intact.
        gui={drawBox=function(x,y,x2,y2,line,fill)
                if line~=0 and line~=0x00000000 then pixels['box']='painted' end
            end,
            drawText=function(x,y,text)
                texts[#texts+1]=text;pixels['text']=text
            end,
            clearGraphics=function()pixels={};clears=clears+1 end}
        HUD=dofile(root..'/lua/hud.lua')
        HUD.init({screen_w=160,screen_h=144,hud_x=2,hud_y=134,hud_right=158,
            prompt_y=36,prompt_h=10,gameover_y=50,font_size=8,char_width=5})
        assert(HUD.present({kind='link_formed',surface='prompt',
            text='BULBASAUR and CHARMANDER linked!',frames=3}))
    """)
    assert lua.eval("pixels['text']") == "Linked!"
    lua.execute("HUD.render();HUD.render();HUD.render();HUD.render()")
    assert lua.eval("HUD.retained().prompt") == 0
    assert lua.eval("pixels['text']") is None
    assert lua.eval("pixels['box']") is None


def test_terminal_banner_survives_transient_expiry():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.execute(r"""
        pixels={};gui={
            drawBox=function(x,y,x2,y2,line)
                if line~=0 and line~=0x00000000 then pixels[y]='painted' end
            end,
            drawText=function(x,y,text)pixels[text]=true end,
            clearGraphics=function()pixels={} end}
        HUD=dofile(root..'/lua/hud.lua')
        HUD.init({screen_w=160,screen_h=144,hud_x=2,hud_y=134,hud_right=158,
            prompt_y=36,prompt_h=10,gameover_y=50,font_size=8,char_width=5})
        HUD.set_game_over()
        HUD.present({surface='prompt',text='Notice',frames=1})
        HUD.render();HUD.render()
    """)
    assert lua.eval("pixels['GAME OVER!']") is True
    assert lua.eval("pixels[36]") is None


def test_one_frame_notice_is_visible_at_next_render():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.execute(r"""
        pixels={};gui={drawBox=function()end,
            drawText=function(_,_,text)pixels.text=text end,
            clearGraphics=function()pixels={} end}
        HUD=dofile(root..'/lua/hud.lua')
        HUD.present({surface='hud',text='Once',frames=1})
        HUD.render()
    """)
    assert lua.eval("pixels.text") == "Once"


def test_empty_never_painted_hud_needs_no_gui():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.execute("HUD=dofile(root..'/lua/hud.lua');HUD.render();assert(HUD.clear());HUD.render()")
