"""Automated proof that a native GPU child surface coexists with WebView2."""
import argparse,ctypes,json,os,subprocess,threading,time
from pathlib import Path
import webview

def main(a):
    root=Path(__file__).resolve().parents[2];a.results.mkdir(parents=True,exist_ok=True)
    window=webview.create_window('VlogCraft architecture lab — GPU / WebView2',
        html='<html style="background:#111924;color:#deedf5;font:16px Segoe UI"><body><h2>Local architecture lab</h2><p>Native D3D11 surface with an independent WebView2 interface.</p><script>window.labTicks=0;function tick(){window.labTicks++;requestAnimationFrame(tick)}tick()</script></body></html>',
        width=1020,height=740)
    result={};failure=[]
    def loaded():
        try:
            from System import Action
            from System.Drawing import Point,Size,Color
            from System.Windows.Forms import Panel
            form=window.native
            handles=[]
            def create():
                panel=Panel();panel.Location=Point(20,110);panel.Size=Size(960,540);panel.BackColor=Color.Black
                form.Controls.Add(panel);panel.BringToFront();handles.append(int(panel.Handle.ToInt64()))
            form.Invoke(Action(create));parent=handles[0]
            sdk=root/'build/tools/architecture/ffmpeg-shared/ffmpeg-9.0.2-full_build-shared/bin'
            env=dict(os.environ,PATH=str(sdk)+os.pathsep+os.environ['PATH'])
            cmd=[str(root/'build/tools/architecture/native_d3d11.exe'),'--present','--parent',str(parent),'--frames','120',*[str(p.resolve()) for p in a.media]]
            with subprocess.Popen(cmd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE) as process:
                found=[]
                callback_type=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
                def inspect(hwnd,_):
                    label=ctypes.create_unicode_buffer(128);ctypes.windll.user32.GetClassNameW(hwnd,label,128)
                    if label.value=='VlogCraftEnginePrototype':found.append(hwnd)
                    return True
                callback=callback_type(inspect)
                limit=time.monotonic()+8
                while time.monotonic()<limit and process.poll() is None and not found:
                    ctypes.windll.user32.EnumChildWindows(ctypes.c_void_p(parent),callback,0);time.sleep(.03)
                assert found,'No native GPU child appeared'
                get_parent=ctypes.windll.user32.GetParent;get_parent.restype=ctypes.c_void_p;get_parent.argtypes=[ctypes.c_void_p]
                assert get_parent(found[0])==parent
                visible=bool(ctypes.windll.user32.IsWindowVisible(ctypes.c_void_p(found[0])));assert visible
                out,err=process.communicate(timeout=20);assert process.returncode==0,err.decode(errors='replace')
                data=json.loads(out.decode().strip().splitlines()[-1]);assert data['present_calls']==120
                ticks=window.evaluate_js('window.labTicks');assert ticks>10,ticks
                result.update(native_surface_parented=True,native_surface_visible=visible,webview_animation_callbacks=ticks,engine=data)
                (a.results/'host.json').write_text(json.dumps(result,indent=2))
                print(json.dumps(result),flush=True)
        except Exception as error:
            failure.append(error);print(repr(error),flush=True)
        finally:window.destroy()
    window.events.loaded+=loaded
    webview.start(gui='edgechromium')
    if failure:raise failure[0]
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('results',type=Path);p.add_argument('media',type=Path,nargs='+');main(p.parse_args())
