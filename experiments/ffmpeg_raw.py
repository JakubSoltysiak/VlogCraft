"""Isolated continuous video-only FFmpeg → bounded RGBA pipe → local WebGL proof."""
import argparse,json,os,subprocess,sys,tempfile,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import webview
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'benchmarks'),str(ROOT/'tests')]
from engine_profile import scene
from performance import Resources
import render_engine
HTML=r"""<!doctype html><html style="background:#111924;color:#dce8f2;font:16px Segoe UI"><body><h2>Local FFmpeg raw-program prototype</h2><p id="status">Preparing video-only stream…</p><canvas id="screen" width="WIDTH" height="HEIGHT"></canvas><script>
(async()=>{
const gl=document.getElementById('screen').getContext('webgl2',{alpha:false});
if(!gl)throw Error('WebGL2 unavailable');
function shader(type,code){const s=gl.createShader(type);gl.shaderSource(s,code);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;}
const vs=shader(gl.VERTEX_SHADER,'#version 300 es\nconst vec2 P[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));out vec2 uv;void main(){vec2 p=P[gl_VertexID];uv=(p+1.)*.5;gl_Position=vec4(p,0,1);}');
const fs=shader(gl.FRAGMENT_SHADER,'#version 300 es\nprecision highp float;in vec2 uv;uniform sampler2D image;out vec4 color;void main(){color=texture(image,vec2(uv.x,1.-uv.y));}');
const program=gl.createProgram();gl.attachShader(program,vs);gl.attachShader(program,fs);gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error('shader link');
gl.useProgram(program);const texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA8,WIDTH,HEIGHT,0,gl.RGBA,gl.UNSIGNED_BYTE,null);gl.viewport(0,0,WIDTH,HEIGHT);
const start=performance.now(),reader=(await fetch('/frames')).body.getReader(),frame=new Uint8Array(WIDTH*HEIGHT*4);
let part=new Uint8Array(),offset=0,first=null,draws=0;
async function exact(){
 let filled=0;
 while(filled<frame.length){if(offset===part.length){const chunk=await reader.read();if(chunk.done)throw Error('Incomplete raw frame');part=chunk.value;offset=0;}
 const length=Math.min(frame.length-filled,part.length-offset);frame.set(part.subarray(offset,offset+length),filled);offset+=length;filled+=length;}
}
for(let n=0;n<FRAMES;n++){
 await exact();gl.texSubImage2D(gl.TEXTURE_2D,0,0,0,WIDTH,HEIGHT,gl.RGBA,gl.UNSIGNED_BYTE,frame);gl.drawArrays(gl.TRIANGLES,0,3);gl.finish();draws++;
 await new Promise(requestAnimationFrame);if(first===null)first=(performance.now()-start)/1000;
 if(n===0&&CAPTURE){const pixels=new Uint8Array(frame.length);gl.readPixels(0,0,WIDTH,HEIGHT,gl.RGBA,gl.UNSIGNED_BYTE,pixels);await fetch('/capture',{method:'POST',body:pixels});}
 document.getElementById('status').textContent='Completed program frames '+draws+' / FRAMES';
}
const elapsed=(performance.now()-start)/1000;
await fetch('/done',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({completed_frames:draws,first_canvas_frame_seconds:first,total_seconds:elapsed,canvas_completed_fps:draws/elapsed,audio:false,temporary_encoded_files:false,physical_presentation_qualified:false,capture:CAPTURE})});
})().catch(async error=>{await fetch('/done',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({error:error.message})});});
</script></body></html>"""
def main(a):
    a.results=a.results.resolve();a.results.mkdir(parents=True,exist_ok=True)
    width=a.width;height=width*9//16
    state=scene([p.resolve() for p in a.media],a.frames/60,width,len(a.media),a.effects)
    if a.effects:state['tracks'][0]['clips'][0].update(mask='ellipse',maskRadius=.5,feather=.1)
    done=threading.Event();producer_done=threading.Event();result={};timings={};active=[]
    with tempfile.TemporaryDirectory(prefix='raw-program-',dir=a.results) as folder:
        work=Path(folder)
        cmd=render_engine.segment_command(state,0,a.frames/60,work/'video.mp4',work,'preview','video')
        cmd=cmd[:cmd.index('-map')]+['-map','[finished]','-an','-frames:v',str(a.frames),'-c:v','rawvideo','-pix_fmt','rgba','-threads','1','-f','rawvideo','pipe:1']
        html=HTML.replace('WIDTH',str(width)).replace('HEIGHT',str(height)).replace('FRAMES',str(a.frames)).replace('CAPTURE','true' if a.capture else 'false')
        script=work/'inline.js';script.write_text(html.split('<script>',1)[1].split('</script>',1)[0])
        subprocess.run(['node','--check',str(script)],check=True,capture_output=True)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path=='/':
                    data=html.encode();self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
                if self.path!='/frames':self.send_error(404);return
                self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Connection','close');self.end_headers()
                start=time.perf_counter()
                with tempfile.TemporaryFile() as errors,subprocess.Popen(cmd,cwd=work,stdout=subprocess.PIPE,stderr=errors,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) as process:
                    active.append(process)
                    try:
                        for n in range(a.frames):
                            frame=bytearray()
                            while len(frame)<width*height*4:
                                chunk=process.stdout.read(width*height*4-len(frame))
                                if not chunk:raise RuntimeError('Incomplete FFmpeg program frame')
                                frame.extend(chunk)
                            if n==0:
                                timings['first_raw_frame_seconds']=time.perf_counter()-start
                                if a.capture:(a.results/'producer-first.rgba').write_bytes(frame)
                            self.wfile.write(frame);self.wfile.flush()
                        if process.wait(timeout=10):raise RuntimeError('Raw producer failed')
                        timings['producer_stream_seconds']=time.perf_counter()-start
                    except Exception as error:
                        result['producer_error']=str(error)
                    finally:
                        if process.poll() is None:process.kill();process.wait()
                        active.remove(process)
                        errors.seek(0);(a.results/'producer.log').write_bytes(errors.read());producer_done.set()
                self.close_connection=True
            def do_POST(self):
                length=int(self.headers.get('Content-Length','0'))
                if length>width*height*4+16384:self.send_error(413);return
                data=self.rfile.read(length)
                if self.path=='/capture':(a.results/'canvas-first.rgba').write_bytes(data)
                elif self.path=='/done':result.update(json.loads(data));done.set()
                else:self.send_error(404);return
                self.send_response(200);self.send_header('Content-Length','0');self.end_headers()
        http=ThreadingHTTPServer(('127.0.0.1',0),Handler);http.daemon_threads=True
        threading.Thread(target=http.serve_forever,daemon=True).start()
        window=webview.create_window('VlogCraft architecture lab — FFmpeg raw',f'http://127.0.0.1:{http.server_port}/',width=width+80,height=height+180)
        resources=Resources(os.getpid())
        def finish():
            if not done.wait(180):result['error']='Raw program timeout'
            if result.get('completed_frames') and not producer_done.wait(15):result['producer_error']='Producer did not drain'
            window.destroy()
        window.events.loaded+=lambda:threading.Thread(target=finish,daemon=True).start()
        try:webview.start(gui='edgechromium')
        finally:
            for process in list(active):
                if process.poll() is None:process.terminate()
            http.shutdown();http.server_close()
        result.update(timings);result['resources']=resources.finish()
        if a.capture and (a.results/'canvas-first.rgba').is_file():
            import numpy as np
            expected=np.fromfile(a.results/'producer-first.rgba',np.uint8).reshape(height,width,4)
            actual=np.fromfile(a.results/'canvas-first.rgba',np.uint8).reshape(height,width,4)[::-1]
            result['canvas_upload_mean_absolute_error']=float(np.abs(actual.astype(float)-expected).mean())
            assert result['canvas_upload_mean_absolute_error']<1,result
        (a.results/'raw-program.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
        assert not result.get('error') and not result.get('producer_error'),result
        assert result.get('completed_frames')==a.frames,result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('results',type=Path);p.add_argument('media',type=Path,nargs='+')
    p.add_argument('--width',type=int,default=960);p.add_argument('--frames',type=int,default=120);p.add_argument('--effects',action='store_true');p.add_argument('--capture',action='store_true');main(p.parse_args())
